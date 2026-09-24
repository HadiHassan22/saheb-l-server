"""Who the admins are. PROTECTED: see PROTECTED.md.

Admins are the exception to one member, one vote: they keep the server
under control while it's young. What they can do is not in this file and
not protected (an admin's code change can extend it); who they are is:

- Only the server owner adds or removes admins, with /admin. The list is
  kept by the bot, and no other file may touch it. The Admin role on
  Discord only shows who is on it: like every role here it gives no
  Discord powers (guard.py), and holding it without being on the list does
  nothing. The owner counts as an admin without being on it.
- Admins act through the bot, never with Discord's own tools, so every
  admin action is posted in #server-log with who did it. Today they can do
  anything a vote can, at once (Ship it, in chat.py), withdraw any open
  proposal (/admin withdraw, voting_ui.py) and switch #ask-saheb's rate
  limit (/admin chat-limit, chat.py).
"""

import logging

import discord
from discord import app_commands

import layout
import store

log = logging.getLogger("admins")

ROLE = "Admin"


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


async def _role(guild):
    """The Admin role, made with no permissions if it doesn't exist yet."""
    role = discord.utils.get(guild.roles, name=ROLE)
    if role is None:
        role = await guild.create_role(
            name=ROLE, permissions=discord.Permissions.none(),
            colour=discord.Colour.gold(), hoist=True,
            reason="Shows who the owner picked as an admin")
    return role


def _refusal(interaction):
    """Why this person can't change the admins here, or None."""
    guild = interaction.guild
    if guild is None or guild.id != layout.home_id():
        return "Admins are picked in the server itself."
    if interaction.user.id != guild.owner_id:
        return "Only the server owner picks admins."
    return None


group = app_commands.Group(
    name="admin", description="Admins: act without a vote; the owner picks them")


@group.command(name="add", description="Owner only: make a member an admin")
@app_commands.describe(member="The member to make an admin")
async def add_admin(interaction: discord.Interaction, member: discord.Member):
    refusal = _refusal(interaction)
    if refusal or member.bot:
        return await interaction.response.send_message(
            refusal or "Bots can't be admins.", ephemeral=True)
    if not add(member.id):
        return await interaction.response.send_message(
            f"{member.display_name} is already an admin.", ephemeral=True)
    try:
        await member.add_roles(await _role(interaction.guild), reason="Made an admin")
    except discord.HTTPException as e:
        log.warning(f"couldn't give {member.id} the admin role: {e!r}")
    await layout.server_log(
        interaction.guild, f"{interaction.user.mention} made {member.mention} an admin: "
        "they can do what a vote can, without one.")
    await interaction.response.send_message(f"{member.display_name} is now an admin.",
                                            ephemeral=True)


@group.command(name="remove", description="Owner only: stop a member being an admin")
@app_commands.describe(member="The admin to remove")
async def remove_admin(interaction: discord.Interaction, member: discord.Member):
    refusal = _refusal(interaction)
    if refusal:
        return await interaction.response.send_message(refusal, ephemeral=True)
    if not remove(member.id):
        return await interaction.response.send_message(
            f"{member.display_name} isn't an admin.", ephemeral=True)
    role = discord.utils.get(interaction.guild.roles, name=ROLE)
    if role is not None:
        try:
            await member.remove_roles(role, reason="No longer an admin")
        except discord.HTTPException as e:
            log.warning(f"couldn't take the admin role from {member.id}: {e!r}")
    await layout.server_log(
        interaction.guild, f"{interaction.user.mention} removed {member.mention} as an admin.")
    await interaction.response.send_message(
        f"{member.display_name} is no longer an admin.", ephemeral=True)


@group.command(name="list", description="Who the admins are")
async def list_admins(interaction: discord.Interaction):
    found = sorted(ids())
    text = ("Admins: " + ", ".join(f"<@{i}>" for i in found)) if found else "No admins."
    await interaction.response.send_message(
        text[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def setup(tree):
    tree.add_command(group)
