"""Changes a vote can order, carried out by code when it passes.

Each change is checked twice: when it is drafted, so members only ever vote
on something that can actually be done, and again when it is carried out,
because the server may have changed during the vote. Things are named by
their current name when drafting and remembered by id after that.

Limits that hold whatever a vote says:
- the channels the bot depends on can't be renamed or deleted;
- roles are cosmetic: they are created with no permissions, and guard.py
  takes away any that appear later;
- rules 4 to 6 and the original rules can't be removed (conduct.py), and
  only watch words change, never what AutoMod blocks (automod.py);
- a vote about a member (kick, ban) needs `removal_percent`, hides its
  count until it closes, and the member can't vote on it.
"""

import logging
import re
import uuid

import discord

import automod
import conduct
import layout
import proposals
import store
import voting_ui

log = logging.getLogger("actions")

CREATE, RENAME, DELETE, TOPIC, SLOWMODE = (
    "create_channel", "rename_channel", "delete_channel", "set_topic", "set_slowmode")
CATEGORY_CREATE, CATEGORY_RENAME, CATEGORY_DELETE = (
    "create_category", "rename_category", "delete_category")
ROLE_CREATE, ROLE_EDIT, ROLE_DELETE = "create_role", "edit_role", "delete_role"
EMOJI_ADD, EMOJI_REMOVE = "add_emoji", "remove_emoji"
SERVER_NAME, SERVER_ICON = "rename_server", "set_server_icon"
RULE_EDIT, RULE_ADD, RULE_REMOVE = "edit_rule", "add_rule", "remove_rule"
WATCH_ADD, WATCH_REMOVE = "add_watch_words", "remove_watch_words"
EVENT_CANCEL = "cancel_event"
KICK, BAN, UNBAN = "kick_member", "ban_member", "unban_member"

CHANNEL_KINDS = (CREATE, RENAME, DELETE, TOPIC, SLOWMODE,
                 CATEGORY_CREATE, CATEGORY_RENAME, CATEGORY_DELETE)
ROLE_KINDS = (ROLE_CREATE, ROLE_EDIT, ROLE_DELETE)
EMOJI_KINDS = (EMOJI_ADD, EMOJI_REMOVE)
SERVER_KINDS = (SERVER_NAME, SERVER_ICON)
RULE_KINDS = (RULE_EDIT, RULE_ADD, RULE_REMOVE)
WATCH_KINDS = (WATCH_ADD, WATCH_REMOVE)
PEOPLE_KINDS = (KICK, BAN, UNBAN)
KINDS = (CHANNEL_KINDS + ROLE_KINDS + EMOJI_KINDS + SERVER_KINDS + RULE_KINDS
         + WATCH_KINDS + (EVENT_CANCEL,) + PEOPLE_KINDS)
# Votes about a member: a higher bar, a hidden count, and no vote for them.
ABOUT_A_MEMBER = (KICK, BAN)

CORE = {"welcome", "rules", "roles", "mod-log", "server-log", "proposals", "ask-saheb",
        "automod-alerts", "AFK"}
TEXT_NAME = re.compile(r"^[a-z0-9-]{1,100}$")
EMOJI_NAME = re.compile(r"^[A-Za-z0-9_]{2,32}$")
MAX_CHANNELS, MAX_ROLES, MAX_RULES = 450, 100, 20
MAX_EMOJI_BYTES, MAX_ICON_BYTES = 256 * 1024, 4 * 1024 * 1024
REASON = "Ordered by a community vote"


# ---------- shared helpers ----------

def text_name(name):
    """How Discord would name a text channel: lowercase, dashes for spaces."""
    name = re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", str(name).strip().lower()))
    return re.sub(r"-{2,}", "-", name).strip("-")[:100]


def core_ids(guild):
    return {found.id for name in CORE if (found := layout.channel(guild, name))}


def member_id(text):
    """A member id from a mention or a bare id, else None."""
    digits = re.sub(r"[<@!>\s]", "", str(text or ""))
    return int(digits) if digits.isdigit() else None


def _roles():
    """Roles made by vote: {role id: {"joinable": bool}}."""
    return store.load("roles", {})


def voted_roles():
    return {int(k): v for k, v in _roles().items()}


def _save_role(role_id, joinable):
    saved = _roles()
    saved[str(role_id)] = {"joinable": joinable}
    store.save("roles", saved)


def _forget_role(role_id):
    saved = _roles()
    saved.pop(str(role_id), None)
    store.save("roles", saved)


def save_image(data):
    """Keep an attached image until the vote closes; Discord's attachment
    links expire sooner than that. Returns its name."""
    folder = store.DATA_DIR / "images"
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    (folder / name).write_bytes(data)
    return name


def load_image(name):
    return (store.DATA_DIR / "images" / name).read_bytes()


def _colour(value):
    """A discord.Colour from "#RRGGBB", or None."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value or "").strip())
    return discord.Colour(int(match[1], 16)) if match else None


# ---------- checking ----------

async def check(guild, action):
    """None if `action` can be carried out in `guild`, else why not. Fills
    in ids and normalised names as it goes."""
    kind = action.get("kind")
    if kind not in KINDS:
        return "That isn't a change a vote can order."
    if kind in CHANNEL_KINDS:
        return _check_channel(guild, action)
    if kind in ROLE_KINDS:
        return _check_role(guild, action)
    if kind in EMOJI_KINDS:
        return _check_emoji(guild, action)
    if kind in SERVER_KINDS:
        return _check_server(guild, action)
    if kind in RULE_KINDS:
        return _check_rule(action)
    if kind in WATCH_KINDS:
        return _check_watch(action)
    if kind == EVENT_CANCEL:
        return _check_event(guild, action)
    return await _check_member(guild, action)


def _check_channel(guild, action):
    kind = action["kind"]
    if kind == CATEGORY_CREATE:
        name = str(action.get("name") or "").strip()[:100]
        if not name:
            return "Give the category a name."
        if discord.utils.get(guild.categories, name=name):
            return f"There's already a category called {name}."
        action["name"] = name
        return None
    if kind in (CATEGORY_RENAME, CATEGORY_DELETE):
        category = (guild.get_channel(action.get("category_id") or 0)
                    or discord.utils.get(guild.categories, name=action.get("category")))
        if not isinstance(category, discord.CategoryChannel):
            return "There's no category by that name."
        action["category_id"], action["category"] = category.id, category.name
        if kind == CATEGORY_DELETE and category.channels:
            return "Only an empty category can be deleted. Move or delete its channels first."
        if kind == CATEGORY_RENAME:
            new = str(action.get("name") or "").strip()[:100]
            if not new or new == category.name:
                return "That isn't a new name."
            action["name"] = new
        return None
    if kind == CREATE:
        voice = action.get("channel_type") == "voice"
        name = str(action.get("name") or "").strip()[:100] if voice else text_name(action.get("name"))
        if not name or (not voice and not TEXT_NAME.match(name)):
            return "That isn't a usable channel name."
        action["name"] = name
        action["channel_type"] = "voice" if voice else "text"
        if any(c.name == name for c in guild.channels):
            return f"There's already a channel called {name}."
        category = discord.utils.get(guild.categories, name=action.get("category"))
        if category is None:
            return ("Pick one of the existing categories: "
                    + ", ".join(c.name for c in guild.categories) + ".")
        if len(guild.channels) >= MAX_CHANNELS:
            return "The server has too many channels for another."
        return _check_text_settings(action)

    asked = str(action.get("channel") or "").strip().lstrip("#")
    target = (guild.get_channel(action.get("channel_id") or 0)
              or discord.utils.get(guild.channels, name=asked)
              or discord.utils.get(guild.channels, name=text_name(asked)))
    if target is None or isinstance(target, discord.CategoryChannel):
        return "There's no channel by that name."
    action["channel_id"] = target.id
    action["channel"] = target.name
    if target.id in core_ids(guild) and kind in (RENAME, DELETE):
        return f"#{target.name} is one the bot depends on, so it can't be renamed or deleted."
    if kind == RENAME:
        voice = isinstance(target, discord.VoiceChannel)
        new = str(action.get("name") or "").strip()[:100] if voice else text_name(action.get("name"))
        if not new or new == target.name:
            return "That isn't a new usable name."
        action["name"] = new
    if kind in (TOPIC, SLOWMODE) and not isinstance(target, discord.TextChannel):
        return "Only text channels have a topic and slowmode."
    return _check_text_settings(action)


def _check_text_settings(action):
    topic = action.get("topic")
    if topic is not None and len(str(topic)) > 1024:
        return "A topic can be at most 1024 characters."
    slowmode = action.get("slowmode")
    if slowmode is not None and not (isinstance(slowmode, int) and 0 <= slowmode <= 21600):
        return "Slowmode is a number of seconds from 0 to 21600 (six hours)."
    if action["kind"] == SLOWMODE and slowmode is None:
        return "Say how many seconds of slowmode."
    if action["kind"] == TOPIC and topic is None:
        return "Say what the topic should be."
    return None


def _check_role(guild, action):
    kind = action["kind"]
    if kind == ROLE_CREATE:
        name = str(action.get("name") or "").strip()[:100]
        if not name:
            return "Give the role a name."
        if discord.utils.get(guild.roles, name=name):
            return f"There's already a role called {name}."
        if len(voted_roles()) >= MAX_ROLES:
            return "There are already as many roles as the server allows by vote."
        action["name"] = name
        action["joinable"] = bool(action.get("joinable", True))
    else:
        role = guild.get_role(action.get("role_id") or 0) or discord.utils.get(
            guild.roles, name=str(action.get("role") or "").strip().lstrip("@"))
        if role is None or role.id not in voted_roles():
            return "Only roles made by vote can be changed this way; that one isn't."
        action["role_id"], action["role"] = role.id, role.name
        if kind == ROLE_EDIT:
            changes = [k for k in ("name", "color", "joinable") if action.get(k) is not None]
            if not changes:
                return "Say what to change: its name, its color, or whether members can join it."
    if action.get("color") is not None and _colour(action["color"]) is None:
        return "A color is written like #1E88E5."
    return None


def _check_emoji(guild, action):
    name = str(action.get("name") or "").strip().strip(":")
    if action["kind"] == EMOJI_ADD:
        if not EMOJI_NAME.match(name):
            return "An emoji name is 2 to 32 letters, digits or underscores."
        if discord.utils.get(guild.emojis, name=name):
            return f"There's already an emoji called {name}."
        if not action.get("image"):
            return "Attach the image to your message."
        if len(guild.emojis) >= guild.emoji_limit:
            return "The server has no emoji slots left."
        action["name"] = name
        return None
    emoji = discord.utils.get(guild.emojis, name=name)
    if emoji is None:
        return "There's no emoji by that name."
    action["name"], action["emoji_id"] = emoji.name, emoji.id
    return None


def _check_server(guild, action):
    if action["kind"] == SERVER_NAME:
        name = str(action.get("name") or "").strip()
        if not 2 <= len(name) <= 100:
            return "A server name is 2 to 100 characters."
        action["name"] = name
        return None
    if not action.get("image"):
        return "Attach the image to your message."
    return None


def _check_rule(action):
    current, kind = conduct.rules(), action["kind"]
    number = action.get("number")
    if kind in (RULE_EDIT, RULE_REMOVE):
        if not isinstance(number, int) or not 1 <= number <= len(current):
            return f"There are {len(current)} rules; pick one of those numbers."
        if kind == RULE_EDIT and number in conduct.FIXED:
            return f"Rule {number} is part of the safety floor and can't be changed by vote."
        if kind == RULE_REMOVE and number <= len(conduct.DEFAULT_RULES):
            return (f"The first {len(conduct.DEFAULT_RULES)} rules can't be removed, only "
                    "reworded (except 4 to 6).")
    if kind in (RULE_EDIT, RULE_ADD):
        title = str(action.get("title") or "").strip()
        body = str(action.get("body") or "").strip()
        if not title or not body or len(title) > 60 or len(body) > 500:
            return "A rule needs a short title (up to 60 characters) and its text (up to 500)."
        if kind == RULE_ADD and len(current) >= MAX_RULES:
            return f"There can be at most {MAX_RULES} rules."
        action["title"], action["body"] = title, body
    return None


def _check_watch(action):
    words = [str(w).strip().lower() for w in action.get("words") or [] if str(w).strip()]
    if not words:
        return "List the words."
    if any(len(w) > 60 for w in words):
        return "Each word or phrase can be at most 60 characters."
    community = automod.community_words()
    if action["kind"] == WATCH_ADD:
        if len(community["added"]) + len(words) > 1000:
            return "The watch list added by vote is full."
    else:
        known = set(automod.ENGLISH) | set(automod.ARABIC) | set(community["added"])
        if any(w in set(automod.BLOCK_WORDS) for w in words):
            return "Blocked words are part of the safety floor and can't be removed."
        missing = [w for w in words if w not in known]
        if missing:
            return "These aren't on the watch lists: " + ", ".join(missing)
    action["words"] = words
    return None


def _check_event(guild, action):
    event = (guild.get_scheduled_event(action.get("event_id") or 0)
             or discord.utils.get(guild.scheduled_events, name=action.get("event")))
    if event is None:
        return "There's no upcoming event by that name."
    action["event_id"], action["event"] = event.id, event.name
    return None


async def _check_member(guild, action):
    target = member_id(action.get("member"))
    if target is None:
        return "Mention the member (@name) so there's no doubt who is meant."
    action["member"] = str(target)
    if target in (guild.owner_id, guild.me.id):
        return "That member can't be removed by the bot."
    if action["kind"] == UNBAN:
        try:
            ban = await guild.fetch_ban(discord.Object(target))
        except discord.NotFound:
            return "That member isn't banned."
        action["member_name"] = ban.user.name
        return None
    try:
        found = await guild.fetch_member(target)
    except discord.NotFound:
        return "That member isn't in the server."
    if found.top_role >= guild.me.top_role:
        return "That member's role is above the bot's, so it can't act on them."
    action["member_name"] = found.display_name
    if not str(action.get("reason") or "").strip():
        return "Say why: members vote on the reason."
    return None


# ---------- describing ----------

def describe(action):
    """(title, details) of the proposal for `action`."""
    kind, a = action["kind"], action
    lines = {
        CREATE: lambda: (f"Create the {'voice ' if a['channel_type'] == 'voice' else ''}channel "
                         f"{a['name']}", f"Create **{a['name']}** in {a['category']}."
                         + (f" Topic: {a['topic']}" if a.get("topic") else "")
                         + (f" Slowmode: {a['slowmode']} seconds." if a.get("slowmode") else "")),
        RENAME: lambda: (f"Rename {a['channel']} to {a['name']}",
                         f"Rename **{a['channel']}** to **{a['name']}**."),
        DELETE: lambda: (f"Delete {a['channel']}", f"Delete **{a['channel']}**. Its messages "
                         "are deleted with it and can't be restored."),
        TOPIC: lambda: (f"New topic for {a['channel']}",
                        f"Set the topic of **{a['channel']}** to: {a['topic']}"),
        SLOWMODE: lambda: (f"Slowmode of {a['slowmode']}s in {a['channel']}",
                           f"Set slowmode in **{a['channel']}** to {a['slowmode']} seconds."),
        CATEGORY_CREATE: lambda: (f"Create the category {a['name']}",
                                  f"Create a category called **{a['name']}**."),
        CATEGORY_RENAME: lambda: (f"Rename the category {a['category']}",
                                  f"Rename **{a['category']}** to **{a['name']}**."),
        CATEGORY_DELETE: lambda: (f"Delete the category {a['category']}",
                                  f"Delete the empty category **{a['category']}**."),
        ROLE_CREATE: lambda: (f"Create the role {a['name']}", f"Create the role **{a['name']}**"
                              + (f" in {a['color']}" if a.get("color") else "")
                              + (". Members can join and leave it themselves by asking the bot."
                                 if a["joinable"] else ".")
                              + " Like every role here, it gives no powers."),
        ROLE_EDIT: lambda: (f"Change the role {a['role']}", f"Change **{a['role']}**: "
                            + ", ".join(f"{k} to {a[k]}" for k in ("name", "color", "joinable")
                                        if a.get(k) is not None) + "."),
        ROLE_DELETE: lambda: (f"Delete the role {a['role']}", f"Delete the role **{a['role']}**."),
        EMOJI_ADD: lambda: (f"Add the emoji :{a['name']}:",
                            f"Add the attached image as the emoji **:{a['name']}:**."),
        EMOJI_REMOVE: lambda: (f"Remove the emoji :{a['name']}:",
                               f"Remove the emoji **:{a['name']}:**."),
        SERVER_NAME: lambda: ("Rename the server", f"Rename the server to **{a['name']}**."),
        SERVER_ICON: lambda: ("New server icon", "Set the attached image as the server icon."),
        RULE_EDIT: lambda: (f"Reword rule {a['number']}", f"Change rule {a['number']} to: "
                            f"**{a['title']}.** {a['body']}"),
        RULE_ADD: lambda: (f"New rule: {a['title']}", f"Add a rule: **{a['title']}.** {a['body']}"),
        RULE_REMOVE: lambda: (f"Remove rule {a['number']}", f"Remove rule {a['number']}: "
                              f"{conduct.title(a['number'])}."),
        WATCH_ADD: lambda: ("Watch more words", "Have AutoMod pass these to the moderator: "
                            + ", ".join(f"`{w}`" for w in a["words"])),
        WATCH_REMOVE: lambda: ("Watch fewer words", "Stop AutoMod passing these to the "
                               "moderator: " + ", ".join(f"`{w}`" for w in a["words"])),
        EVENT_CANCEL: lambda: (f"Cancel the event {a['event']}",
                               f"Cancel the event **{a['event']}**."),
        KICK: lambda: (f"Kick {a['member_name']}", f"Remove <@{a['member']}> from the server. "
                       "They can come back with a new invite."),
        BAN: lambda: (f"Ban {a['member_name']}", f"Ban <@{a['member']}> from the server."),
        UNBAN: lambda: (f"Unban {a['member_name']}", f"Lift the ban on {a['member_name']}."),
    }
    title, details = lines[kind]()
    if action.get("reason"):
        details += f"\n\n**Why.** {action['reason']}"
    if kind in ABOUT_A_MEMBER:
        details += ("\n\nA vote about a member: it hides its count until it closes, "
                    "they can't vote on it, and it needs a higher share to pass.")
    details += "\n\nIf this passes, the bot makes the change itself."
    return title[:100], details


# ---------- carrying out ----------

async def carry_out(guild, action):
    """Make the change. Returns a sentence saying what happened."""
    problem = await check(guild, action)
    if problem:
        return f"It couldn't be done: {problem}"
    kind, a = action["kind"], action
    if kind == CREATE:
        category = discord.utils.get(guild.categories, name=a["category"])
        if a["channel_type"] == "voice":
            made = await guild.create_voice_channel(a["name"], category=category, reason=REASON)
        else:
            made = await guild.create_text_channel(
                a["name"], category=category, topic=a.get("topic") or None,
                slowmode_delay=a.get("slowmode") or 0, reason=REASON)
        return f"Done: {made.mention} is open."
    if kind == CATEGORY_CREATE:
        await guild.create_category(a["name"], reason=REASON)
        return f"Done: the category {a['name']} exists."
    if kind in (CATEGORY_RENAME, CATEGORY_DELETE):
        category = guild.get_channel(a["category_id"])
        if kind == CATEGORY_RENAME:
            await category.edit(name=a["name"], reason=REASON)
            return f"Done: the category is now {a['name']}."
        await category.delete(reason=REASON)
        return f"Done: the category {a['category']} is deleted."
    if kind in (RENAME, DELETE, TOPIC, SLOWMODE):
        return await _carry_out_channel(guild, a)
    if kind in ROLE_KINDS:
        return await _carry_out_role(guild, a)
    if kind == EMOJI_ADD:
        await guild.create_custom_emoji(name=a["name"], image=load_image(a["image"]),
                                        reason=REASON)
        return f"Done: :{a['name']}: is added."
    if kind == EMOJI_REMOVE:
        await guild.get_emoji(a["emoji_id"]).delete(reason=REASON)
        return f"Done: :{a['name']}: is removed."
    if kind == SERVER_NAME:
        await guild.edit(name=a["name"], reason=REASON)
        return f"Done: the server is now called {a['name']}."
    if kind == SERVER_ICON:
        await guild.edit(icon=load_image(a["image"]), reason=REASON)
        return "Done: the server has its new icon."
    if kind in RULE_KINDS:
        return await _carry_out_rule(guild, a)
    if kind in WATCH_KINDS:
        words = automod.community_words()
        if kind == WATCH_ADD:
            words["added"] = sorted(set(words["added"]) | set(a["words"]))
            words["removed"] = [w for w in words["removed"] if w not in a["words"]]
        else:
            words["added"] = [w for w in words["added"] if w not in a["words"]]
            words["removed"] = sorted(set(words["removed"]) | set(a["words"]))
        automod.save_community_words(words)
        await automod.install(guild, layout.channel(guild, "automod-alerts"))
        return "Done: AutoMod's watch list is updated."
    if kind == EVENT_CANCEL:
        await guild.get_scheduled_event(a["event_id"]).cancel(reason=REASON)
        return f"Done: {a['event']} is cancelled."
    return await _carry_out_member(guild, a)


async def _carry_out_channel(guild, a):
    target = guild.get_channel(a["channel_id"])
    kind = a["kind"]
    if kind == RENAME:
        await target.edit(name=a["name"], reason=REASON)
        return f"Done: renamed to {target.mention}."
    if kind == DELETE:
        name = target.name
        await target.delete(reason=REASON)
        layout.forget(guild, a["channel_id"])
        return f"Done: #{name} is deleted."
    if kind == TOPIC:
        await target.edit(topic=a["topic"], reason=REASON)
        return f"Done: {target.mention} has its new topic."
    await target.edit(slowmode_delay=a["slowmode"], reason=REASON)
    return f"Done: slowmode in {target.mention} is {a['slowmode']} seconds."


async def _carry_out_role(guild, a):
    kind = a["kind"]
    if kind == ROLE_CREATE:
        role = await guild.create_role(
            name=a["name"], colour=_colour(a.get("color")) or discord.Colour.default(),
            permissions=discord.Permissions.none(), hoist=False,
            mentionable=a["joinable"], reason=REASON)
        _save_role(role.id, a["joinable"])
        return f"Done: the role {role.name} exists."
    role = guild.get_role(a["role_id"])
    if kind == ROLE_DELETE:
        await role.delete(reason=REASON)
        _forget_role(role.id)
        return f"Done: the role {a['role']} is deleted."
    changes = {}
    if a.get("name"):
        changes["name"] = a["name"]
    if a.get("color"):
        changes["colour"] = _colour(a["color"])
    if a.get("joinable") is not None:
        changes["mentionable"] = bool(a["joinable"])
        _save_role(role.id, bool(a["joinable"]))
    await role.edit(reason=REASON, **changes)
    return f"Done: the role {role.name} is updated."


async def _carry_out_rule(guild, a):
    current = conduct.rules()
    if a["kind"] == RULE_EDIT:
        current[a["number"] - 1] = (a["title"], a["body"])
    elif a["kind"] == RULE_ADD:
        current.append((a["title"], a["body"]))
    else:
        del current[a["number"] - 1]
    conduct.save_rules(current)
    await layout.post_texts(guild)
    return "Done: #rules is updated."


async def _carry_out_member(guild, a):
    target = int(a["member"])
    if a["kind"] == UNBAN:
        await guild.unban(discord.Object(target), reason=REASON)
        return f"Done: {a['member_name']} is unbanned."
    member = await guild.fetch_member(target)
    try:
        await member.send(f"A community vote in {guild.name} decided to "
                          f"{'ban' if a['kind'] == BAN else 'remove'} you. "
                          f"The reason given: {a.get('reason', '')}")
    except discord.HTTPException:
        pass
    if a["kind"] == BAN:
        await guild.ban(member, reason=REASON, delete_message_seconds=0)
        return f"Done: {a['member_name']} is banned."
    await guild.kick(member, reason=REASON)
    return f"Done: {a['member_name']} is removed from the server."


async def settle(client, p):
    """Carry out a passed change. Registered in voting_ui.AFTER_CLOSE."""
    if p["kind"] != proposals.ACTION or p["status"] != proposals.PASSED:
        return
    guild = client.get_guild(layout.home_id() or 0)
    try:
        said = await carry_out(guild, dict(p["action"]))
    except (discord.HTTPException, OSError) as e:
        said = f"It couldn't be done: {getattr(e, 'status', '') or e.__class__.__name__}."
    log.info(f"proposal {p['no']}: {said}")
    await voting_ui.reply_to(client, p, said)
    await layout.server_log(guild, f"Proposal {p['no']} ({p['title']}): {said}")


def setup():
    voting_ui.AFTER_CLOSE.append(settle)
