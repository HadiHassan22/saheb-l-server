"""The av command: shows a member's avatar, or the sender's own when no one
is mentioned.

It's a slash command, so the bot reads nothing a member types in chat; it
only gets the member the command was given. The picture is posted for
everyone to see, like the other replies in the server.
"""

from typing import Optional

import discord
from discord import app_commands


@app_commands.command(name="av", description="Show a member's avatar")
@app_commands.describe(member="The member whose avatar to show (yours if left out)")
async def av(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"{member.display_name}'s avatar")
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


def setup(tree):
    tree.add_command(av)
