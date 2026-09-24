"""No member holds power over another. PROTECTED: see PROTECTED.md.

Roles here are cosmetic: a color, an interest, something to be pinged
for. This takes every permission that would let a member act on others or
on the server away from every role and every channel override, however it
got there: a vote, a code change, or someone with the owner's account.
The bot's own role, which Discord manages, is the only one left with them.
The Admin role is stripped like any other: admins (admins.py) act through
the bot, which posts what they do in #server-log.

It runs when the bot starts, every hour, and whenever a role or channel
changes. The owner's own powers come from owning the server, not from a
role, so this can't touch them; that is why the owner is a trust question
rather than a code question.
"""

import asyncio
import logging

import discord
from discord.ext import tasks

log = logging.getLogger("guard")

POWERS = discord.Permissions(
    administrator=True, manage_guild=True, manage_roles=True, manage_channels=True,
    kick_members=True, ban_members=True, moderate_members=True, manage_messages=True,
    manage_webhooks=True, manage_nicknames=True, manage_expressions=True,
    manage_events=True, manage_threads=True, mention_everyone=True, move_members=True,
    mute_members=True, deafen_members=True, view_audit_log=True,
    view_guild_insights=True, create_expressions=True, create_events=True,
)
NAMES = [name for name, on in POWERS if on]
_warned = set()


def stripped(permissions):
    """`permissions` without any of POWERS, or None if it had none."""
    if not permissions.value & POWERS.value:
        return None
    return discord.Permissions(permissions.value & ~POWERS.value)


def stripped_overwrite(overwrite):
    """`overwrite` with every power it allowed set back to neutral, or None
    if it allowed none."""
    allow, deny = overwrite.pair()
    if not allow.value & POWERS.value:
        return None
    changed = discord.PermissionOverwrite.from_pair(
        discord.Permissions(allow.value & ~POWERS.value), deny)
    return changed


async def sweep(guild, report=None):
    """Take powers off every role and channel override. `report(text)` is
    told what was taken, so it can be said publicly."""
    for role in guild.roles:
        if role.managed:
            continue
        if role >= guild.me.top_role:
            # Only the owner can make a role the bot can't edit. Say so,
            # once per start, rather than let it pass quietly.
            if stripped(role.permissions) is not None and role.id not in _warned:
                _warned.add(role.id)
                if report:
                    await report(f"The role {role.name} has moderation permissions and "
                                 "sits above the bot, so only the server owner can "
                                 "change it.")
            continue
        new = stripped(role.permissions)
        if new is not None:
            taken = [n for n in NAMES if getattr(role.permissions, n)]
            await role.edit(permissions=new, reason="Roles here are cosmetic")
            if report:
                await report(f"Removed {', '.join(taken)} from the role {role.name}: "
                             "roles here are cosmetic, and nobody holds power over others.")
    for channel in guild.channels:
        for target, overwrite in list(channel.overwrites.items()):
            if target == guild.me or getattr(target, "managed", False):
                continue
            new = stripped_overwrite(overwrite)
            if new is not None:
                await channel.set_permissions(target, overwrite=new,
                                              reason="Nobody holds power over others")
                if report:
                    await report(f"Removed moderation permissions for {target.name} in "
                                 f"#{channel.name}: nobody holds power over others.")


_pending = set()


async def soon(guild, report):
    """Sweep a few seconds from now, once, however many changes asked."""
    if guild.id in _pending:
        return
    _pending.add(guild.id)
    try:
        await asyncio.sleep(10)
        await sweep(guild, report)
    except discord.HTTPException as e:
        log.warning(f"sweep failed: {e!r}")
    finally:
        _pending.discard(guild.id)


@tasks.loop(hours=1)
async def hourly(client, guild_id, report):
    await client.wait_until_ready()
    guild = client.get_guild(guild_id)
    if guild is not None:
        try:
            await sweep(guild, report)
        except discord.HTTPException as e:
            log.warning(f"sweep failed: {e!r}")
