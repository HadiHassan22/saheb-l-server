"""The Discord side of voting: /propose, /propose-setting, /settings, the
card each proposal is posted as, its vote buttons, and closing votes when
time is up.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import tasks

import layout
import proposals
import settings

log = logging.getLogger("voting")

COLOURS = {
    proposals.OPEN: discord.Colour.blurple(),
    proposals.PASSED: discord.Colour.green(),
    proposals.FAILED: discord.Colour.red(),
    proposals.NO_QUORUM: discord.Colour.light_grey(),
}
RESULTS = {
    proposals.PASSED: "Passed",
    proposals.FAILED: "Failed",
    proposals.NO_QUORUM: "Not enough votes",
}
# What Yes and No mean on each kind of proposal.
CHOICES = {proposals.APPEAL: {"yes": "overturn", "no": "keep"}}
PLAIN = {"yes": "yes", "no": "no"}

# Called as `await hook(client, proposal)` after a proposal closes and its
# result is posted. Appeals register here to carry out their result.
AFTER_CLOSE = []


def choices(p):
    return CHOICES.get(p["kind"], PLAIN)


def card(p):
    yes, no = proposals.tally(p)
    say = choices(p)
    embed = discord.Embed(
        title=f"Proposal {p['no']}: {p['title']}"[:256],
        description=p["details"][:4000],
        colour=COLOURS[p["status"]],
    )
    embed.add_field(name="Proposed by", value=f"<@{p['author_id']}>")
    if p["status"] == proposals.OPEN:
        embed.add_field(name="Closes", value=f"<t:{int(p['closes_at'])}:R>")
        # A vote about a person shows turnout only, so nobody votes with the
        # crowd against someone.
        counted = (f"{yes + no} voted so far; the count is hidden until it closes"
                   if p.get("blind") else f"{yes} {say['yes']} · {no} {say['no']}")
        embed.add_field(
            name="Votes",
            value=(f"{counted}\nNeeds at least {p['quorum']} votes, and more than "
                   f"{p['pass_percent']}% {say['yes']}"),
            inline=False,
        )
    elif p.get("shipped_by"):
        embed.add_field(name="Result", value="**Shipped by an admin** without a vote",
                        inline=False)
    else:
        embed.add_field(
            name="Result",
            value=f"**{RESULTS[p['status']]}**: {yes} {say['yes']} · {no} {say['no']}",
            inline=False,
        )
        if p.get("note"):
            embed.add_field(name="Note", value=p["note"], inline=False)
    footer = (f"Secret ballot. Members of {p['voter_min_days']}+ days, and everyone "
              "who joined in the server's first week, can vote. "
              "Discuss in the thread.")
    if p.get("shipped_by"):
        footer = ("An admin skipped the vote on this code change. It still goes through "
                  "every automatic check, and progress is posted here.")
    elif p["kind"] == proposals.APPEAL:
        footer += " The member this case is about can't vote on it."
    embed.set_footer(text=footer)
    return embed


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
            f"You voted **{choices(p)[self.choice]}**. You can change it until "
            "voting closes.",
            ephemeral=True,
        )
        await interaction.message.edit(embed=card(proposals.get(self.no)))


def vote_buttons(p):
    say = choices(p)
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


async def publish(interaction, opener, guild=None):
    """Open a proposal with `opener(now)` and post it in the proposals
    channel, with a thread for discussion. Returns the proposal, or None if
    nothing was opened. `guild` is for interactions that arrive by DM."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    channel = layout.channel(guild or interaction.guild, "proposals")
    if channel is None:
        return await interaction.followup.send(
            "The proposals channel isn't set up yet, so nothing was proposed.",
            ephemeral=True,
        )
    try:
        p = opener(int(time.time()))
    except proposals.Refused as e:
        return await interaction.followup.send(str(e), ephemeral=True)
    p = proposals.fit_quorum(p["no"], people(channel.guild))
    view = vote_buttons(p) if p["status"] == proposals.OPEN else discord.utils.MISSING
    message = await channel.send(embed=card(p), view=view)
    proposals.attach_message(p["no"], channel.id, message.id)
    try:
        await message.create_thread(name=f"Proposal {p['no']}: {p['title']}"[:100])
    except discord.HTTPException as e:
        log.warning(f"no thread for proposal {p['no']}: {e!r}")
    await interaction.followup.send(f"Proposal {p['no']} is up: {message.jump_url}",
                                    ephemeral=True)
    if p.get("shipped_by"):
        await layout.server_log(
            channel.guild, f"<@{p['shipped_by']}> shipped proposal {p['no']} without a vote, "
            f"as an admin: {message.jump_url}")
    return p


class ProposeForm(discord.ui.Modal, title="New proposal"):
    name = discord.ui.TextInput(label="Title", max_length=100)
    details = discord.ui.TextInput(
        label="What should change, and why",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    async def on_submit(self, interaction):
        await publish(interaction, lambda now: proposals.open_proposal(
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
    await publish(interaction, lambda now: proposals.open_proposal(
        interaction.user.id, "", reason, now, setting=setting.value, value=value))


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


def announcement(p):
    yes, no = proposals.tally(p)
    say = choices(p)
    counts = f"{yes} {say['yes']}, {no} {say['no']}"
    if p["status"] == proposals.NO_QUORUM:
        stands = (f" Case {p['case_no']} stands."
                  if p["kind"] == proposals.APPEAL else "")
        return (f"Proposal {p['no']} did not get enough votes to count "
                f"({counts}; it needed {p['quorum']}).{stands}")
    if p["kind"] == proposals.APPEAL:
        if p["status"] == proposals.PASSED:
            return (f"Proposal {p['no']} passed ({counts}): case {p['case_no']} "
                    "is overturned.")
        return f"Proposal {p['no']} failed ({counts}): case {p['case_no']} stands."
    if p["status"] == proposals.FAILED:
        return f"Proposal {p['no']} failed ({counts})."
    if p.get("note"):
        return f"Proposal {p['no']} passed ({counts}). {p['note']}"
    if p["kind"] == proposals.ACTION:
        return f"Proposal {p['no']} passed ({counts}). The bot is making the change now."
    if p["kind"] == proposals.SETTING:
        return (f"Proposal {p['no']} passed ({counts}). "
                f"{settings.SETTINGS[p['setting']]['label']} is now "
                f"{settings.describe(p['setting'], p['value'])}.")
    return (f"Proposal {p['no']} passed ({counts}). It will now be written as a "
            "code change, checked, and deployed automatically. Progress will be "
            "posted here.")


@tasks.loop(minutes=1)
async def close_due(client):
    await client.wait_until_ready()
    for due in proposals.due(time.time()):
        # An exception escaping a task loop stops it for good, and then no
        # vote ever closes again.
        try:
            p = proposals.close(due["no"], int(time.time()))
        except Exception as e:
            log.error(f"closing proposal {due['no']} failed: {e!r}")
            continue
        log.info(f"proposal {p['no']} closed: {p['status']}")
        try:
            await post_result(client, p)
        except Exception as e:
            log.error(f"the result of proposal {p['no']} was not posted: {e!r}")
        for hook in AFTER_CLOSE:
            try:
                await hook(client, p)
            except Exception as e:
                log.error(f"{hook.__name__} failed for proposal {p['no']}: {e!r}")


async def reply_to(client, p, text):
    """Say something under proposal `p`'s card, or in its channel if the
    card is gone."""
    channel = client.get_channel((p or {}).get("channel_id") or 0)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(p["message_id"])
        await message.reply(text, mention_author=False)
    except discord.HTTPException:
        await channel.send(text)


async def post_result(client, p):
    channel = client.get_channel(p["channel_id"] or 0)
    if channel is None:
        return
    message = await channel.fetch_message(p["message_id"])
    await message.edit(embed=card(p), view=None)
    await message.reply(announcement(p), mention_author=False)
    if p["kind"] == proposals.SETTING and p["status"] == proposals.PASSED:
        await layout.post_texts(channel.guild)  # #welcome quotes the settings


def setup(client, tree):
    client.add_dynamic_items(VoteButton)
    for command in (propose, propose_setting, show_settings):
        tree.add_command(command)
    close_due.start(client)
