"""The Discord side of voting: /propose, /propose-setting, /settings, the
vote buttons on each proposal's card, opening proposals, and closing votes
when time is up. Also what admins can do to proposals (admins.py): pass
one at once, and take one down with /admin withdraw.

How a proposal looks is in cards.py, and every way one ends in ending.py.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import tasks

import admins
import cards
import code_changes
import ending
import layout
import proposals
import setting_changes
import settings

log = logging.getLogger("voting")


class VoteButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"vote:(?P<choice>yes|no):(?P<no>\d+)"):
    """A Yes or No button. The proposal number is in the button's id, so the
    buttons keep working across restarts."""

    def __init__(self, choice, no, label=None):
        super().__init__(discord.ui.Button(
            label=(label or choice).capitalize(),
            style=(discord.ButtonStyle.success if choice == "yes"
                   else discord.ButtonStyle.danger),
            custom_id=f"vote:{choice}:{no}",
        ))
        self.choice = choice
        self.no = no

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["choice"], int(match["no"]))

    async def callback(self, interaction):
        joined = getattr(interaction.user, "joined_at", None)
        me = interaction.guild.me if interaction.guild else None
        founded = me.joined_at if me else None
        try:
            p = proposals.cast(self.no, interaction.user.id,
                               joined.timestamp() if joined else None,
                               self.choice, time.time(),
                               founded.timestamp() if founded else None)
        except proposals.Refused as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        await interaction.response.send_message(
            f"You voted **{cards.choices(p)[self.choice]}**. You can change it until "
            "voting closes.",
            ephemeral=True,
        )
        await interaction.message.edit(embed=cards.card(proposals.get(self.no)))


def vote_buttons(p):
    say = cards.choices(p)
    view = discord.ui.View(timeout=None)
    view.add_item(VoteButton("yes", p["no"], say["yes"]))
    view.add_item(VoteButton("no", p["no"], say["no"]))
    return view


def people(guild):
    """How many people, not bots, are in the server. Until Discord has sent
    the member list, every member but this bot, or None if unknown."""
    if guild.chunked:
        return sum(not m.bot for m in guild.members)
    count = guild.member_count
    return count - 1 if count else None


async def publish(interaction, opener, guild=None, by_admin=False):
    """Open a proposal with `opener(now)` and post it in the proposals
    channel, with a thread for discussion. Returns the proposal, or None if
    nothing was opened. `guild` is for interactions that arrive by DM.
    `by_admin` passes it at once and carries it out, as a passed vote
    would be; checking that the member is an admin is the caller's job."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = guild or interaction.guild
    try:
        if by_admin:
            p, said = await ship(interaction.client, guild, opener, interaction.user.id)
            await interaction.followup.send(
                f"Proposal {p['no']} passed without a vote. {said or ''}"[:2000],
                ephemeral=True)
            return p
        channel = layout.channel(guild, "proposals")
        if channel is None:
            raise proposals.Refused("The proposals channel isn't set up yet, so nothing "
                                    "was proposed.")
        p = opener(int(time.time()))
    except proposals.Refused as e:
        return await interaction.followup.send(str(e), ephemeral=True)
    p = proposals.fit_quorum(p["no"], people(channel.guild))
    message = await cards.post(p, channel, vote_buttons(p))
    await interaction.followup.send(f"Proposal {p['no']} is up: {message.jump_url}",
                                    ephemeral=True)
    return p


async def ship(client, guild, opener, admin_id):
    """What an admin asked for, done at once: the proposal `opener(now)`
    opens is passed on their word, its card posted, and it is carried out
    as a passed vote would be (ending.py). Returns the proposal and a
    sentence saying what came of it. Raises proposals.Refused if it can't
    be opened; checking that `admin_id` is an admin is the caller's job."""
    if layout.channel(guild, "proposals") is None:
        raise proposals.Refused("The proposals channel isn't set up yet.")
    p = opener(int(time.time()))
    return await ending.pass_now(client, guild, p["no"], admin_id, int(time.time()))


@admins.group.command(name="withdraw",
                      description="Admins: take an open proposal down without a vote")
@app_commands.describe(proposal="The proposal's number", reason="Why (shown on its card)")
async def withdraw(interaction: discord.Interaction, proposal: int, reason: str = ""):
    if not admins.allowed(interaction.user.id, interaction.guild):
        return await interaction.response.send_message(
            "Only an admin can withdraw a proposal.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        p = await ending.withdraw(interaction.client, interaction.guild, proposal,
                                  interaction.user.id, reason[:500], int(time.time()))
    except proposals.Refused as e:
        return await interaction.followup.send(str(e), ephemeral=True)
    await interaction.followup.send(f"Proposal {p['no']} is withdrawn.", ephemeral=True)


class ProposeForm(discord.ui.Modal, title="New proposal"):
    name = discord.ui.TextInput(label="Title", max_length=100)
    details = discord.ui.TextInput(
        label="What should change, and why",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    async def on_submit(self, interaction):
        await publish(interaction, lambda now: code_changes.KIND.open(
            interaction.user.id, self.name.value, self.details.value, now))


@app_commands.command(name="propose", description="Propose something for the server to vote on")
async def propose(interaction: discord.Interaction):
    await interaction.response.send_modal(ProposeForm())


@app_commands.command(name="propose-setting",
                      description="Propose changing one of the bot's settings")
@app_commands.describe(setting="The setting to change", value="Its new value",
                       reason="Why (optional)")
@app_commands.choices(setting=[
    app_commands.Choice(name=spec["label"][:100], value=name)
    for name, spec in settings.SETTINGS.items()
])
async def propose_setting(interaction: discord.Interaction,
                          setting: app_commands.Choice[str], value: int,
                          reason: str = ""):
    await publish(interaction, lambda now: setting_changes.KIND.open(
        interaction.user.id, setting.value, value, reason, now))


@app_commands.command(name="settings", description="The settings the bot runs by")
async def show_settings(interaction: discord.Interaction):
    lines = []
    for group in (settings.VOTING, settings.MODERATION):
        lines.append(f"### {group}")
        lines += [f"**{spec['label']}**: {settings.describe(name, value)} "
                  f"(can be {spec['min']} to {spec['max']})"
                  for name, value in settings.current().items()
                  if (spec := settings.SETTINGS[name])["group"] == group]
    lines.append("\nAny of these can be changed by vote with `/propose-setting`.")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tasks.loop(minutes=1)
async def close_due(client):
    await client.wait_until_ready()
    for due in proposals.due(time.time()):
        # An exception escaping a task loop stops it for good, and then no
        # vote ever closes again.
        try:
            await ending.close(client, due["no"], int(time.time()))
        except Exception as e:
            log.error(f"closing proposal {due['no']} failed: {e!r}")


def setup(client, tree):
    client.add_dynamic_items(VoteButton)
    for command in (propose, propose_setting, show_settings):
        tree.add_command(command)
    close_due.start(client)
