"""Admins: members the owner picks, who can have a code change made
without a vote. PROTECTED: see PROTECTED.md.

This is the one exception to one member, one vote, and it is kept narrow:

- Only the server owner adds or removes admins, with /admin. The list is
  kept by the bot. The Admin role on Discord only shows who is on it: like
  every role here it gives no Discord powers (guard.py), and holding it
  without being on the list does nothing.
- An admin can skip the vote on a code change (a general proposal drafted
  in #ask-saheb), nothing else. Server changes, settings, kicks, bans and
  appeals still go to a vote.
- A shipped change goes through the same self-update workflow as a voted
  one: the tests, the protected-core check, the security review, and the
  rollback. It is posted in #proposals and #server-log with who shipped it.
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
    name="admin", description="Admins can have a code change made without a vote")


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
        "they can have a code change made without a vote.")
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
