"""The av command: shows a member's avatar, or the sender's own when no one
is mentioned.

It's a slash command, so the bot reads nothing a member types in chat; it
only gets the member the command was given. Members can also tag Saheb
and ask ("av @Karim"): the chat's get_avatar tool (assistant.py) shows the
same picture under its reply. Either way it's posted for everyone to see,
like the other replies in the server.
"""

from typing import Optional

import discord
from discord import app_commands


def embed(member):
    """The embed that shows `member`'s avatar."""
    shown = discord.Embed(title=f"{member.display_name}'s avatar"[:256])
    shown.set_image(url=member.display_avatar.url)
    return shown


@app_commands.command(name="av", description="Show a member's avatar")
@app_commands.describe(member="The member whose avatar to show (yours if left out)")
async def av(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    await interaction.response.send_message(embed=embed(member or interaction.user))


def setup(tree):
    tree.add_command(av)
