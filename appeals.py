"""Appeals: any moderation case can be put to a community vote, once.

- The member a case is about gets an Appeal button in the message that
  told them about it, because a banned or timed-out member can't use the
  server's slash commands.
- Anyone in the server can use /appeal on a case that still stands, which
  also covers a banned member whose DMs are closed.
- An appeal is a proposal in #proposals, voted Overturn or Keep under the
  usual rules. The member it is about can't vote on it.
- If it passes, the bot undoes what it can: it lifts the timeout, or
  unbans and sends an invite back. A deleted message can't be restored.
  An overturned case stops counting towards the member's record.
- Every result updates the case in #mod-log and posts the running share
  of appeals that overturned the moderator: if that share is high, the
  moderator is too strict.
"""

import logging

import discord
from discord import app_commands

import cases
import conduct
import judge
import layout
import proposals
import voting_ui

log = logging.getLogger("appeals")

INVITE_DAYS = 7
UNDO = {
    cases.WARN: "remove the warning from their record",
    cases.TIMEOUT: "lift the timeout, if it is still running, and remove it from "
                   "their record",
    cases.BAN: "unban them and send them an invite back",
}


def appeal_text(case, reason):
    """(title, details) of the appeal proposal for `case`."""
    rule_title = conduct.RULES[case["rule"] - 1][0]
    if case["rule"] in judge.HIDDEN_RULES or not case.get("excerpt"):
        quoted = "(not repeated here)"
    else:
        quoted = "||" + discord.utils.escape_markdown(case["excerpt"]) + "||"
    decided = ("the first check alone" if case.get("decided_by") == judge.FIRST_CHECK
               else "a second review")
    undo = UNDO[case["action"]]
    if case.get("deleted"):
        undo += ". The deleted message can't be restored"
    details = (
        f"**The case.** {cases.label(case)} for <@{case['user_id']}> under rule "
        f"{case['rule']} ({rule_title}), {case['severity']} severity, decided by "
        f"{decided}.\n"
        f"**The moderator's explanation.** {case['explanation']}\n"
        f"**The message.** {quoted}\n\n"
        f"**Why it should be overturned.** {reason.strip()}\n\n"
        f"Overturning it will {undo}."
    )
    return f"Appeal of case {case['no']}: {cases.label(case)}", details


async def file(interaction, case_no, reason, guild):
    """Open the appeal and post it. The check that the case can still be
    appealed and marking it appealed happen in one step with no await
    between them, so two appeals of the same case can't both get through."""
    def opener(now):
        case = cases.get(case_no)
        problem = cases.why_not_appealable(case)
        if problem:
            raise proposals.Refused(problem)
        title, details = appeal_text(case, reason)
        p = proposals.open_appeal(interaction.user.id, case_no, case["user_id"],
                                  title, details, now)
        cases.update(case_no, appeal=p["no"])
        return p

    p = await voting_ui.publish(interaction, opener, guild=guild)
    if p is not None:
        await _note(guild, cases.get(case_no),
                    f"Under appeal: proposal {p['no']}, closing <t:{int(p['closes_at'])}:R>.")


class AppealForm(discord.ui.Modal, title="Appeal"):
    reason = discord.ui.TextInput(
        label="Why should this be overturned?", style=discord.TextStyle.paragraph,
        min_length=10, max_length=1000)

    def __init__(self, case_no, guild):
        super().__init__(title=f"Appeal case {case_no}")
        self.case_no = case_no
        self.guild = guild

    async def on_submit(self, interaction):
        await file(interaction, self.case_no, self.reason.value, self.guild)


class AppealButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"appeal:(?P<case>\d+)"):
    """In the DM that tells a member about their case. It works after a ban,
    when the member can no longer reach the server's commands."""

    def __init__(self, case_no):
        super().__init__(discord.ui.Button(label="Appeal", style=discord.ButtonStyle.primary,
                                           custom_id=f"appeal:{case_no}"))
        self.case_no = case_no

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["case"]))

    async def callback(self, interaction):
        case = cases.get(self.case_no)
        if case is None or case["user_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "This button is for the member the case is about.", ephemeral=True)
        problem = cases.why_not_appealable(case)
        if problem:
            return await interaction.response.send_message(problem, ephemeral=True)
        guild = interaction.client.get_guild(layout.home_id() or 0)
        await interaction.response.send_modal(AppealForm(self.case_no, guild))


def appeal_view(case_no):
    view = discord.ui.View(timeout=None)
    view.add_item(AppealButton(case_no))
    return view


@app_commands.command(name="appeal",
                      description="Put a moderation case to a community vote")
@app_commands.describe(case="The case number, from #mod-log")
async def appeal(interaction: discord.Interaction, case: int):
    problem = cases.why_not_appealable(cases.get(case))
    if problem:
        return await interaction.response.send_message(problem, ephemeral=True)
    await interaction.response.send_modal(AppealForm(case, interaction.guild))


async def settle(client, p):
    """Carry out a closed appeal. Registered in voting_ui.AFTER_CLOSE."""
    if p["kind"] != proposals.APPEAL:
        return
    guild = client.get_guild(layout.home_id() or 0)
    case = cases.get(p["case_no"])
    if p["status"] != proposals.PASSED:
        cases.update(case["no"], appeal_result="upheld")
        await _note(guild, case, f"Appealed in proposal {p['no']}, which did not pass. "
                                 "The action stands.")
        await _tell(client, case["user_id"],
                    f"Your appeal of case {case['no']} did not pass, so the action stands.")
    else:
        done = await _undo(client, guild, case)
        cases.update(case["no"], status=cases.OVERTURNED, appeal_result="overturned")
        await _note(guild, case, f"**Overturned** by proposal {p['no']}. {done}")
    await _post_record(guild)


async def _undo(client, guild, case):
    """Undo what the case did, and say what was done."""
    user_id = case["user_id"]
    reason = f"Case {case['no']} overturned by appeal"
    said = []
    if case["action"] == cases.TIMEOUT:
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member.is_timed_out():
                await member.timeout(None, reason=reason)
                said.append("The timeout was lifted.")
            else:
                said.append("The timeout had already ended.")
        except discord.NotFound:
            said.append("They have left the server.")
        await _tell(client, user_id, f"Your appeal of case {case['no']} passed: it is "
                                     "overturned and no longer counts on your record.")
    elif case["action"] == cases.BAN:
        try:
            await guild.unban(discord.Object(user_id), reason=reason)
        except discord.NotFound:
            pass  # already unbanned
        welcome = layout.channel(guild, "welcome")
        invite = await welcome.create_invite(max_uses=1, max_age=INVITE_DAYS * 86400,
                                             unique=True, reason=reason)
        # Discord may refuse: a bot can usually only message people it shares
        # a server with, and this member was just outside it.
        if await _tell(client, user_id, f"Your appeal of case {case['no']} passed and "
                                        f"you are unbanned. Your invite back, valid "
                                        f"for {INVITE_DAYS} days: {invite.url}"):
            said.append("They were unbanned and sent an invite back.")
        else:
            said.append("They were unbanned, but couldn't be messaged: anyone in touch "
                        "with them can send them an invite.")
    else:
        await _tell(client, user_id, f"Your appeal of case {case['no']} passed: the "
                                     "warning is removed from your record.")
        said.append("The warning no longer counts on their record.")
    if case.get("deleted"):
        said.append("The deleted message can't be restored.")
    return " ".join(said)


async def _tell(client, user_id, text):
    """DM a member. True if it was delivered."""
    try:
        user = client.get_user(user_id) or await client.fetch_user(user_id)
        await user.send(text)
        return True
    except discord.HTTPException:
        return False


async def _note(guild, case, text):
    """Set the Appeal line on the case's #mod-log entry."""
    log_channel = layout.channel(guild, "mod-log")
    if log_channel is None or not case.get("log_message_id"):
        return
    try:
        message = await log_channel.fetch_message(case["log_message_id"])
        embed = message.embeds[0]
        names = [field.name for field in embed.fields]
        if "Appeal" in names:
            embed.set_field_at(names.index("Appeal"), name="Appeal", value=text, inline=False)
        else:
            embed.add_field(name="Appeal", value=text, inline=False)
        await message.edit(embed=embed)
    except (discord.HTTPException, IndexError) as e:
        log.warning(f"could not update case {case['no']} in #mod-log: {e!r}")


async def _post_record(guild):
    overturned, decided = cases.appeal_record()
    log_channel = layout.channel(guild, "mod-log")
    if log_channel is None or not decided:
        return
    await log_channel.send(
        f"Appeals so far: the community has overturned {overturned} of {decided} "
        f"appealed cases ({overturned / decided:.0%}). A high share means the "
        "moderator is too strict.")


def setup(client, tree):
    client.add_dynamic_items(AppealButton)
    tree.add_command(appeal)
    voting_ui.AFTER_CLOSE.append(settle)
