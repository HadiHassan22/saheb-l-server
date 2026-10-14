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


# Only public configuration fields, never member answers or arbitrary payloads.
_AUDIT_FIELDS = {
    "onboarding": ("enabled", "mode", "default_channels", "prompts"),
    "onboarding_prompt": ("title", "type", "single_select", "required",
                          "in_onboarding", "options"),
    "home_settings": ("enabled", "welcome_message", "resource_channels",
                      "new_member_actions"),
    "channel": ("name", "topic", "nsfw", "position", "slowmode_delay",
                "bitrate", "user_limit", "default_auto_archive_duration"),
    "role": ("name", "permissions", "colour", "hoist", "mentionable", "position"),
    "guild": ("name", "description", "verification_level", "explicit_content_filter",
              "default_notifications", "afk_timeout", "afk_channel", "system_channel",
              "rules_channel", "public_updates_channel", "preferred_locale"),
}
_AUDIT_STRUCTURES = {
    "prompts": ("id", "title", "required", "single_select", "in_onboarding"),
    "options": ("id", "title", "channel_ids", "role_ids"),
    "welcome_message": ("message",),  # not author IDs
    "resource_channels": ("channel_id", "title"),
    "new_member_actions": ("channel_id", "title", "action_type"),
}
_AUDIT_ENUMS = (discord.ChannelType, discord.VerificationLevel, discord.ContentFilter,
                discord.NotificationLevel, discord.Locale, discord.OnboardingMode,
                discord.OnboardingPromptType)


def _audit_bound(value, limit):
    return value[:limit] + ("…" if len(value) > limit else "")


def _audit_text(value, limit=120):
    """Bound public strings and neutralize formatting, mentions and controls."""
    truncated = len(value) > limit
    value = "".join(c if c.isprintable() else " " for c in value[:limit])
    value = discord.utils.escape_markdown(value).replace("@", "@\u200b")
    return value[:limit] + ("…" if truncated or len(value) > limit else "")


def _audit_id(value):
    return str(value) if type(value) is int and 0 <= value < 10**20 else None


def _audit_value(value, field="", depth=0):
    if field == "topic":
        return "changed"  # topics may contain private channel instructions
    if depth > 4:
        return "unavailable"
    if field in _AUDIT_STRUCTURES and type(value) in (str, int, bool, set):
        return "unavailable"
    if value is None:
        return "none"
    if type(value) is bool:
        return "yes" if value else "no"
    if type(value) is int:
        return _audit_id(value) or "unavailable"
    if type(value) is str:
        return _audit_text(value)
    if isinstance(value, _AUDIT_ENUMS):
        return _audit_text(value.name)
    if isinstance(value, (discord.Permissions, discord.Colour)):
        return _audit_id(value.value) or "unavailable"
    if type(value) in (list, tuple):
        items = [_audit_value(item, field, depth + 1) for item in value[:3]]
        omitted = f"; +{len(value) - 3} more" if len(value) > 3 else ""
        return "[" + _audit_bound("; ".join(items), 130) + omitted + "]"
    if type(value) is set and field in ("channel_ids", "role_ids"):
        return _audit_value(sorted(i for i in value if _audit_id(i)), field, depth + 1)
    fields = _AUDIT_STRUCTURES.get(field)
    if fields:
        parts = []
        for key in fields:
            found = value.get(key) if type(value) is dict else getattr(value, key, None)
            if found is not None:
                parts.append(f"{key}={_audit_value(found, key, depth + 1)}")
        return _audit_bound(", ".join(parts), 160) if parts else "unavailable"
    # Cached public channel/role/guild references, including unresolved Objects.
    ident = _audit_id(getattr(value, "id", None))
    if ident:
        return f"ID {ident}"
    return "unavailable"  # never repr() unknown objects or dictionaries


def _audit_same(old, new):
    """Safe equality only for scalars; never compare arbitrary payloads deeply."""
    if old is new:
        return True
    if type(old) is type(new) and type(old) in (str, int, bool, type(None)):
        return old == new
    if type(old) is type(new) and type(old) in (discord.Permissions, discord.Colour):
        return type(old.value) is int and type(new.value) is int and old.value == new.value
    return False  # audit diff presence is evidence, not a repr/deep equality check


def _audit_details(entry):
    action = entry.action.name
    group = next((key for key in _AUDIT_FIELDS
                  if action in (f"{key}_create", f"{key}_update", f"{key}_delete")), None)
    if group is None:
        return ""
    changes = getattr(entry, "changes", None)
    before, after = getattr(changes, "before", None), getattr(changes, "after", None)
    missing = object()
    parts = []
    for field in _AUDIT_FIELDS[group]:
        old, new = getattr(before, field, missing), getattr(after, field, missing)
        if old is missing and new is missing:
            continue
        if group == "channel" and field in ("name", "topic"):
            # Public audit transport: channel names/topics can be private,
            # including deleted/uncached channels. Never disclose their text.
            if not _audit_same(old, new):
                parts.append(f"{field}: changed")
        else:
            old_text = "unset" if old is missing else _audit_value(old, field)
            new_text = "unset" if new is missing else _audit_value(new, field)
            if old_text != new_text:
                parts.append(f"{field}: {old_text} → {new_text}")
            elif not _audit_same(old, new):
                parts.append(f"{field}: changed (shown: {new_text})")
        if len(parts) == 6:
            break
    return (" [" + "; ".join(parts)[:800] + "]") if parts else ""


def _target(entry):
    target = getattr(entry, "target", None)
    changes = getattr(entry, "changes", None)
    before = getattr(changes, "before", None)
    mention = getattr(target, "mention", None)
    ident = _audit_id(getattr(target, "id", None))
    # Keep canonical Discord references; server_log already suppresses pings.
    if ident and mention in (f"<@{ident}>", f"<@!{ident}>", f"<@&{ident}>", f"<#{ident}>"):
        return mention
    action = entry.action.name
    if action.startswith(("channel_", "overwrite_")) or action == "message_bulk_delete":
        return f"channel (ID {ident})" if ident else "channel"
    for value in (getattr(target, "name", None), getattr(before, "name", None)):
        if type(value) is str and value:
            return _audit_text(value)
    label = ("server onboarding prompt" if action.startswith("onboarding_prompt_") else
             "server onboarding" if action.startswith("onboarding_") else
             "server home settings" if action.startswith("home_settings_") else "target")
    return f"{label} (ID {ident})" if ident else label


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
    return text + _audit_details(entry)


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
