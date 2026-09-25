"""Who the admins are. PROTECTED: see PROTECTED.md.

Admins are the exception to one member, one vote: they keep the server
under control while it's young. What they can do is not in this file and
not protected (an admin's code change can extend it); who they are is:

- The owner and the admins add or remove admins, with /admin or by asking
  the bot. The list is kept by the bot, and no other file may touch it.
  The owner counts as an admin without being on it.
- The Admin role is the one role with Discord's own powers (Administrator;
  guard.py strips every other). The bot keeps it on exactly the people on
  the list: an admin who gives it to someone in Discord makes them an
  admin, and anyone else who ends up with it loses it.
- Every admin action is posted in #server-log with who did it: what they
  ask the bot for, and, read from Discord's audit log, what they do with
  Discord's own tools. What they can do is listed in README.md, not here,
  since it can grow by code change.
- #admin-log is where the bot tells admins what members don't see: how
  the self-update workflow is doing, with links to the code. Only the
  admins and the owner can read it, and that is checked and repaired
  here before every post, so no other file can open it to members.
"""

import logging

import discord
from discord import app_commands

import layout
import store

log = logging.getLogger("admins")

ROLE = "Admin"
CHANNEL = "admin-log"
POWERS = discord.Permissions(administrator=True)


def ids():
    return set(store.load("admins", []))


def is_admin(user_id):
    return user_id in ids()


def allowed(user_id, guild):
    """True if `user_id` may use admin powers in `guild`: an admin, or the
    owner, and only in the home server."""
    return (guild is not None and guild.id == layout.home_id()
            and (is_admin(user_id) or user_id == guild.owner_id))


def _save(found):
    store.save("admins", sorted(found))


def add(user_id):
    """True if `user_id` wasn't an admin and now is."""
    found = ids()
    if user_id in found:
        return False
    _save(found | {user_id})
    return True


def remove(user_id):
    """True if `user_id` was an admin and now isn't."""
    found = ids()
    if user_id not in found:
        return False
    _save(found - {user_id})
    return True


def role_id():
    """The Admin role's id, or None before it exists."""
    return store.load("admin_role", {}).get("id")


def role(guild):
    """The Admin role in `guild`, by id, or by name the first time."""
    found = guild.get_role(role_id() or 0) or discord.utils.get(guild.roles, name=ROLE)
    if found is not None and found.id != role_id():
        store.save("admin_role", {"id": found.id})
    return found


async def _role(guild):
    """The Admin role, made if it doesn't exist yet."""
    found = role(guild)
    if found is None:
        found = await guild.create_role(
            name=ROLE, permissions=POWERS, colour=discord.Colour.gold(), hoist=True,
            reason="The admins' role")
        store.save("admin_role", {"id": found.id})
    return found


async def keep(guild, report):
    """Keep the Admin role's powers, and keep it on the admins alone.
    `report(text)` is told what changed, to say publicly. Runs with every
    guard.py sweep."""
    if not ids() and role(guild) is None:
        return
    found = await _role(guild)
    if found >= guild.me.top_role:
        log.warning("the Admin role sits above the bot, so the bot can't manage it")
        return
    if not found.permissions.administrator:
        await found.edit(permissions=POWERS, reason="The admins' role keeps its powers")
    listed = ids()
    for member in found.members:
        if member.id not in listed and member.id != guild.owner_id:
            await member.remove_roles(found, reason="Only admins hold the Admin role")
            await report(f"Took the Admin role from {member.mention}: only admins hold it. "
                         "An admin can make them one with /admin add.")
    for user_id in listed:
        member = guild.get_member(user_id)
        if member is not None and found not in member.roles:
            await member.add_roles(found, reason="An admin")


async def log_channel(guild):
    """#admin-log, readable by the admins in the server and the owner and
    nobody else, or None if the server has none. Raises
    discord.HTTPException if its permissions couldn't be put right."""
    channel = layout.channel(guild, CHANNEL)
    if channel is None:
        return None
    readers = {guild.get_member(i) for i in ids() | {guild.owner_id}} - {None}
    wanted = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    wanted.update({member: discord.PermissionOverwrite(view_channel=True, send_messages=False)
                   for member in readers})
    if channel.overwrites != wanted:
        await channel.edit(overwrites=wanted, reason="Only the admins read #admin-log")
    return channel


async def post(guild, text):
    """Tell the admins `text` in #admin-log. Says nothing, and returns
    False, if it couldn't be kept to them."""
    try:
        channel = await log_channel(guild)
        if channel is None:
            return False
        await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions.none(),
                           suppress_embeds=True)
        return True
    except discord.HTTPException as e:
        log.warning(f"couldn't post in #admin-log: {e!r}")
        return False


async def _update_log_channel(guild):
    try:
        await log_channel(guild)
    except discord.HTTPException as e:
        log.warning(f"couldn't update who reads #admin-log: {e!r}")


def _refusal(interaction):
    """Why this person can't change the admins here, or None."""
    guild = interaction.guild
    if guild is None or guild.id != layout.home_id():
        return "Admins are picked in the server itself."
    if not allowed(interaction.user.id, guild):
        return "Only the owner and the admins pick admins."
    return None


async def make(guild, member, by_id):
    """Make `member` an admin, on the word of `by_id` (the owner or an
    admin: the caller checks). Returns what to tell them."""
    if member.bot:
        return "Bots can't be admins."
    if not add(member.id):
        return f"{member.display_name} is already an admin."
    try:
        await member.add_roles(await _role(guild), reason="Made an admin")
    except discord.HTTPException as e:
        log.warning(f"couldn't give {member.id} the admin role: {e!r}")
    await _update_log_channel(guild)
    await layout.server_log(guild, f"<@{by_id}> made {member.mention} an admin: they can "
                                   "do what a vote can, without one.")
    return f"{member.display_name} is now an admin."


async def unmake(guild, member, by_id):
    """Stop `member` being an admin, on the word of `by_id`. Returns what
    to tell them."""
    if not remove(member.id):
        return f"{member.display_name} isn't an admin."
    found = role(guild)
    if found is not None:
        try:
            await member.remove_roles(found, reason="No longer an admin")
        except discord.HTTPException as e:
            log.warning(f"couldn't take the admin role from {member.id}: {e!r}")
    await _update_log_channel(guild)
    await layout.server_log(guild, f"<@{by_id}> removed {member.mention} as an admin.")
    return f"{member.display_name} is no longer an admin."


group = app_commands.Group(
    name="admin", description="Admins: act without a vote, and pick other admins")


@group.command(name="add", description="Admins: make a member an admin")
@app_commands.describe(member="The member to make an admin")
async def add_admin(interaction: discord.Interaction, member: discord.Member):
    refusal = _refusal(interaction)
    if refusal:
        return await interaction.response.send_message(refusal, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    said = await make(interaction.guild, member, interaction.user.id)
    await interaction.followup.send(said, ephemeral=True)


@group.command(name="remove", description="Admins: stop a member being an admin")
@app_commands.describe(member="The admin to remove")
async def remove_admin(interaction: discord.Interaction, member: discord.Member):
    refusal = _refusal(interaction)
    if refusal:
        return await interaction.response.send_message(refusal, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    said = await unmake(interaction.guild, member, interaction.user.id)
    await interaction.followup.send(said, ephemeral=True)


@group.command(name="list", description="Who the admins are")
async def list_admins(interaction: discord.Interaction):
    found = sorted(ids())
    text = ("Admins: " + ", ".join(f"<@{i}>" for i in found)) if found else "No admins."
    await interaction.response.send_message(
        text[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# What an admin did with Discord's own tools, as posted in #server-log.
# {target} is who or what it was done to.
DID = {
    discord.AuditLogAction.kick: "kicked {target}",
    discord.AuditLogAction.ban: "banned {target}",
    discord.AuditLogAction.unban: "unbanned {target}",
    discord.AuditLogAction.member_update: "changed {target}'s nickname or voice state",
    discord.AuditLogAction.member_role_update: "changed the roles of {target}",
    discord.AuditLogAction.member_move: "moved members between voice channels",
    discord.AuditLogAction.member_disconnect: "disconnected members from voice",
    discord.AuditLogAction.channel_create: "created the channel {target}",
    discord.AuditLogAction.channel_update: "changed the channel {target}",
    discord.AuditLogAction.channel_delete: "deleted the channel {target}",
    discord.AuditLogAction.overwrite_create: "changed who can do what in {target}",
    discord.AuditLogAction.overwrite_update: "changed who can do what in {target}",
    discord.AuditLogAction.overwrite_delete: "changed who can do what in {target}",
    discord.AuditLogAction.role_create: "created the role {target}",
    discord.AuditLogAction.role_update: "changed the role {target}",
    discord.AuditLogAction.role_delete: "deleted the role {target}",
    discord.AuditLogAction.message_delete: "deleted a message by {target}",
    discord.AuditLogAction.message_bulk_delete: "deleted messages in {target}",
    discord.AuditLogAction.message_pin: "pinned a message by {target}",
    discord.AuditLogAction.message_unpin: "unpinned a message by {target}",
    discord.AuditLogAction.guild_update: "changed the server's settings",
    discord.AuditLogAction.emoji_create: "added an emoji",
    discord.AuditLogAction.emoji_delete: "removed an emoji",
}


def _target(entry):
    target = entry.target
    before = getattr(entry.changes, "before", None)
    return (getattr(target, "mention", None) or getattr(target, "name", None)
            or getattr(before, "name", None) or "something")


def did(entry):
    """What `entry` says an admin did, as a sentence's end."""
    after = getattr(entry.changes, "after", None)
    if entry.action == discord.AuditLogAction.member_update and hasattr(after, "timed_out_until"):
        until = after.timed_out_until
        text = (f"timed out {_target(entry)} until <t:{int(until.timestamp())}:f>" if until
                else f"lifted {_target(entry)}'s timeout")
    elif entry.action in DID:
        text = DID[entry.action].format(target=_target(entry))
    else:
        text = f"{entry.action.name.replace('_', ' ')} ({_target(entry)})"
    return text


async def on_audit_log_entry(entry):
    """An admin's action with Discord's own tools: post it in #server-log,
    and if they gave or took the Admin role, make or unmake an admin."""
    guild = entry.guild
    if (guild.id != layout.home_id() or entry.user_id in (None, guild.me.id)
            or not allowed(entry.user_id, guild)):
        return
    if (entry.action == discord.AuditLogAction.member_update
            and getattr(entry.target, "id", None) == entry.user_id):
        return  # their own nickname: not an action on anyone
    found = role(guild)
    if entry.action == discord.AuditLogAction.member_role_update and found is not None:
        added = getattr(entry.changes.after, "roles", None) or []
        taken = getattr(entry.changes.before, "roles", None) or []
        user_id = getattr(entry.target, "id", None)
        if user_id is not None and any(r.id == found.id for r in added):
            if user_id != guild.owner_id and not getattr(entry.target, "bot", False):
                add(user_id)
        if user_id is not None and any(r.id == found.id for r in taken):
            remove(user_id)
        await _update_log_channel(guild)
    await layout.server_log(guild, f"<@{entry.user_id}> {did(entry)}, as an admin, with "
                                   "Discord's own tools."
                                   + (f" Reason: {entry.reason}" if entry.reason else ""))


def setup(tree):
    tree.add_command(group)
