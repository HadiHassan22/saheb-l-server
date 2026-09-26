"""Things done the moment a member asks, with no vote.

- Personal: they affect only the member asking, who can undo them: joining
  or leaving a role, their nickname, an invite link to bring someone in.
- Light: small shared things: an event, a temporary voice channel, a
  thread, a pin. They happen at once, are posted in #server-log with who
  asked, are limited per member, and can be undone by vote.
- Admin: done on an admin's word alone, posted in #server-log with who
  asked: giving an existing role to every member of the server.

Each function returns what to tell the member, or raises Refused.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

import actions
import layout
import pickers
import store

BEIRUT = ZoneInfo("Asia/Beirut")
DAY = 24 * 60 * 60
# How many of each a member can do per day.
DAILY = {"invite": 5, "event": 3, "voice": 3, "thread": 10, "pin": 10}
EVENTS_EACH, VOICE_EACH, VOICE_TOTAL = 3, 1, 10
VOICE_HOURS, EMPTY_GRACE = 12, 15 * 60
LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")


class Refused(Exception):
    """Said to the member as is."""


def _state():
    return store.load("quick", {"used": {}, "events": {}, "voice": {}})


def spend(member_id, kind, now):
    """Count one use of `kind`, or refuse if today's allowance is used."""
    state = _state()
    used = [t for t in state["used"].get(f"{member_id}:{kind}", []) if now - t < DAY]
    if len(used) >= DAILY[kind]:
        raise Refused(f"You've used today's {DAILY[kind]}. Try again tomorrow.")
    state["used"][f"{member_id}:{kind}"] = used + [now]
    store.save("quick", state)


def open_to_everyone(guild, channel):
    """True for a text channel members can post in: not one of the bot's."""
    if not isinstance(channel, discord.TextChannel):
        return False
    return channel.overwrites_for(guild.default_role).send_messages is not False


def find_channel(guild, name):
    asked = str(name or "").strip().lstrip("#")
    return (discord.utils.get(guild.channels, name=asked)
            or discord.utils.get(guild.channels, name=actions.text_name(asked)))


def beirut_time(text, now):
    """A start time written "YYYY-MM-DD HH:MM" in Beirut time, as UTC."""
    try:
        local = datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise Refused("Give the start as a date and time, like 2026-10-02 20:00.")
    start = local.replace(tzinfo=BEIRUT).astimezone(timezone.utc)
    if not now + timedelta(minutes=5) <= start <= now + timedelta(days=60):
        raise Refused("An event has to start between five minutes and 60 days from now.")
    return start


# ---------- personal ----------

async def join_role(member, name, join=True):
    roles = actions.voted_roles()
    role = next((r for r in member.guild.roles
                 if r.id in roles and r.name.lower() == str(name).strip().lstrip("@").lower()),
                None)
    if role is None or not roles[role.id]["joinable"]:
        raise Refused("That isn't a role members can join. Ask me to list the roles.")
    if join:
        # A picker where members pick one: joining one of its roles leaves the others.
        others = {r for p in pickers.holding(role.id) if p["one"] for r in p["roles"]} - {role.id}
        left = [r for r in member.roles if r.id in others] if others else []
        if left:
            await member.remove_roles(*left, reason="Picked another in its picker")
        await member.add_roles(role, reason="Joined by asking")
        return f"You're in {role.name}." + (
            f" You've left {', '.join(r.name for r in left)}." if left else "")
    await member.remove_roles(role, reason="Left by asking")
    return f"You've left {role.name}."


async def set_nickname(member, nickname):
    nickname = str(nickname or "").strip()
    if len(nickname) > 32:
        raise Refused("A nickname can be at most 32 characters.")
    if member.id == member.guild.owner_id:
        raise Refused("Discord doesn't let bots change the server owner's nickname.")
    await member.edit(nick=nickname or None, reason="Asked for it")
    return f"Your nickname is now {nickname}." if nickname else "Your nickname is reset."


async def create_invite(member, uses=1, hours=24):
    spend(member.id, "invite", time.time())
    uses, hours = max(1, min(int(uses), 10)), max(1, min(int(hours), 24))
    invite = await layout.channel(member.guild, "welcome").create_invite(
        max_uses=uses, max_age=hours * 3600, unique=True,
        reason=f"Asked for by {member.display_name}")
    await layout.server_log(member.guild, f"{member.display_name} made an invite link "
                                          f"({uses} use{'s' * (uses > 1)}, {hours} hours).")
    return f"Here's your invite, good for {uses} use{'s' * (uses > 1)} over {hours} hours: {invite.url}"


# ---------- light ----------

async def create_event(member, name, start, hours=2, place="", description=""):
    guild, now = member.guild, datetime.now(timezone.utc)
    begins = beirut_time(start, now)
    hours = max(0.5, min(float(hours), 12))
    state = _state()
    live = [e for e, owner in state["events"].items()
            if owner == member.id and guild.get_scheduled_event(int(e))]
    if len(live) >= EVENTS_EACH:
        raise Refused(f"You already have {EVENTS_EACH} upcoming events.")
    spend(member.id, "event", now.timestamp())
    voice = find_channel(guild, place)
    where = {}
    if isinstance(voice, discord.VoiceChannel):
        where = {"entity_type": discord.EntityType.voice, "channel": voice}
    else:
        where = {"entity_type": discord.EntityType.external,
                 "location": str(place or "To be decided")[:100]}
    event = await guild.create_scheduled_event(
        name=str(name)[:100], start_time=begins, end_time=begins + timedelta(hours=hours),
        description=str(description or "")[:1000], privacy_level=discord.PrivacyLevel.guild_only,
        reason=f"Asked for by {member.display_name}", **where)
    state = _state()
    state["events"][str(event.id)] = member.id
    store.save("quick", state)
    local = begins.astimezone(BEIRUT).strftime("%a %d %b, %H:%M")
    await layout.server_log(guild, f"{member.display_name} scheduled **{event.name}** for "
                                   f"{local} (Beirut time).")
    return f"Scheduled **{event.name}** for {local} Beirut time: {event.url}"


async def cancel_my_event(member, name):
    guild = member.guild
    event = discord.utils.get(guild.scheduled_events, name=str(name).strip())
    if event is None:
        raise Refused("There's no upcoming event by that name.")
    if _state()["events"].get(str(event.id)) != member.id:
        raise Refused("You can only cancel events you asked for. Anyone else's takes a vote.")
    await event.cancel(reason=f"Cancelled by {member.display_name}, who made it")
    await layout.server_log(guild, f"{member.display_name} cancelled their event {event.name}.")
    return f"{event.name} is cancelled."


async def create_temp_voice(member, name, hours=3):
    guild, now = member.guild, time.time()
    state = _state()
    mine = [c for c, v in state["voice"].items() if v["owner"] == member.id]
    if len(mine) >= VOICE_EACH:
        raise Refused("You already have a temporary voice channel open.")
    if len(state["voice"]) >= VOICE_TOTAL:
        raise Refused("There are already as many temporary voice channels as allowed.")
    spend(member.id, "voice", now)
    hours = max(1, min(int(hours), VOICE_HOURS))
    made = await guild.create_voice_channel(
        str(name or f"{member.display_name}'s room")[:100],
        category=layout.channel(guild, "category:Voice"),
        reason=f"Temporary, asked for by {member.display_name}")
    state = _state()
    state["voice"][str(made.id)] = {"owner": member.id, "created": now,
                                    "expires": now + hours * 3600}
    store.save("quick", state)
    await layout.server_log(guild, f"{member.display_name} opened the temporary voice "
                                   f"channel {made.name} for {hours} hours.")
    return (f"{made.mention} is open for {hours} hours. It closes early if it's been "
            "empty for 15 minutes.")


async def start_thread(member, channel, name):
    guild = member.guild
    target = find_channel(guild, channel)
    if not open_to_everyone(guild, target):
        raise Refused("Threads can only be started in channels members post in.")
    spend(member.id, "thread", time.time())
    thread = await target.create_thread(
        name=str(name)[:100], type=discord.ChannelType.public_thread,
        auto_archive_duration=1440, reason=f"Asked for by {member.display_name}")
    await layout.server_log(guild, f"{member.display_name} started the thread "
                                   f"{thread.name} in #{target.name}.")
    return f"Started {thread.mention}."


async def pin(member, link, pinned=True):
    guild = member.guild
    match = LINK.search(str(link or ""))
    if match is None or int(match[1]) != guild.id:
        raise Refused("Paste the link to the message (right-click it, Copy Message Link).")
    target = guild.get_channel(int(match[2]))
    if not open_to_everyone(guild, target):
        raise Refused("Messages can only be pinned in channels members post in.")
    spend(member.id, "pin", time.time())
    message = await target.fetch_message(int(match[3]))
    if pinned:
        await message.pin(reason=f"Asked for by {member.display_name}")
    else:
        await message.unpin(reason=f"Asked for by {member.display_name}")
    done = "pinned" if pinned else "unpinned"
    await layout.server_log(guild, f"{member.display_name} {done} a message in "
                                   f"#{target.name}: {message.jump_url}")
    return f"Done: {done}."


# ---------- admin ----------

async def give_role_to_all(member, name):
    """Give every member of the server the existing role `name`, asked for
    by `member`, who must be an admin (the caller checks). Only roles made
    by vote go round the whole server, so no role with powers ever does.
    Posted in #server-log with who asked. Returns what to tell them, or
    raises Refused."""
    guild = member.guild
    wanted = str(name or "").strip().lstrip("@")
    roles = actions.voted_roles()
    role = next((r for r in guild.roles
                 if r.id in roles and r.name.lower() == wanted.lower()), None)
    if role is None:
        raise Refused("That isn't a role made by vote, so it can't go to everyone. "
                      "Ask me to list the roles.")
    given, missed = 0, 0
    for one in guild.members:
        if any(r.id == role.id for r in one.roles):
            continue  # it already has it
        try:
            await one.add_roles(role, reason=f"Asked for by {member.display_name}")
        except discord.HTTPException:
            missed += 1
            continue
        given += 1
    await layout.server_log(guild, f"<@{member.id}> gave every member the role "
                                   f"{role.name} ({given} newly given it).")
    said = (f"Everyone already has {role.name}." if not given and not missed
            else f"Done: {role.name} is now on {given} member{'s' * (given != 1)}.")
    if missed:
        said += f" Left out {missed} member{'s' * (missed != 1)} I can't act on."
    return said


# ---------- temporary voice channels close themselves ----------

@tasks.loop(minutes=5)
async def tidy(client):
    await client.wait_until_ready()
    guild = client.get_guild(layout.home_id() or 0)
    if guild is None:
        return
    state, now = _state(), time.time()
    for channel_id, room in list(state["voice"].items()):
        channel = guild.get_channel(int(channel_id))
        expired = now > room["expires"]
        abandoned = now - room["created"] > EMPTY_GRACE and channel and not channel.members
        if channel is None or expired or abandoned:
            if channel is not None:
                try:
                    await channel.delete(reason="Temporary voice channel closed")
                except discord.HTTPException:
                    continue
            del state["voice"][channel_id]
    store.save("quick", state)


def setup(client):
    tidy.start(client)
