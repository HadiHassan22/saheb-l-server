"""Acts on AutoMod alerts: gathers the conversation around a flagged
message, has it judged (see judge.py), applies the sanction, tells the
member, and posts the case in #mod-log. Also the owner's /ai-key.

The bot never reads messages AutoMod did not flag. For a flagged one it
reads the few messages before it, because the same word is a joke in one
conversation and an attack in another.
"""

import asyncio
import logging
import time
from datetime import timedelta

import discord
from discord import app_commands

import ai
import appeals
import cases
import conduct
import judge
import layout
import providers
import settings

log = logging.getLogger("moderator")

CONTEXT_MESSAGES = 8
# One message can trip several rules, and each sends its own alert.
DUPLICATE_WINDOW = 5 * 60
# Right after a sanction, further alerts from the same member (a spam
# burst) are left to AutoMod instead of stacking sanctions.
COOLDOWN = 60
SUPPORT_LINE = (
    "It sounded like you might be going through something heavy. You're not "
    "in any trouble. If you're in Lebanon, Embrace's lifeline is free and "
    "confidential: call **1564**. If you're somewhere else, please reach out "
    "to someone you trust or a local helpline."
)

_locks = {}
_seen = {}
_supported = {}
_paused_notice = None


def _fresh(key, now):
    """True the first time `key` is seen in DUPLICATE_WINDOW."""
    for old in [k for k, t in _seen.items() if now - t > DUPLICATE_WINDOW]:
        del _seen[old]
    if key in _seen:
        return False
    _seen[key] = now
    return True


async def on_automod_action(execution: discord.AutoModAction):
    if execution.action.type != discord.AutoModRuleActionType.send_alert_message:
        return
    if execution.guild_id != layout.home_id() or not execution.content:
        return
    now = time.time()
    if not _fresh((execution.user_id, execution.message_id or execution.content), now):
        return
    lock = _locks.setdefault(execution.user_id, asyncio.Lock())
    async with lock:
        try:
            await handle(execution)
        except Exception as e:
            log.error(f"alert from {execution.user_id} could not be handled: {e!r}")


async def _context(channel, message_id):
    lines = []
    before = discord.Object(message_id) if message_id else None
    async for message in channel.history(limit=CONTEXT_MESSAGES, before=before):
        text = message.content or ("(attachment)" if message.attachments else "")
        if text:
            lines.append(f"[{message.author.display_name}]: {text[:300]}")
    return list(reversed(lines))


async def handle(execution):
    guild = execution.guild
    member = execution.member or await guild.fetch_member(execution.user_id)
    if member.bot:
        return
    last = cases.last_action_at(member.id)
    if last and time.time() - last < COOLDOWN:
        return
    channel = execution.channel or await guild.fetch_channel(execution.channel_id)
    lines = await _context(channel, execution.message_id)
    state = judge.state(lines, member.display_name, execution.content[:1000])

    try:
        screening = judge.screen(await ai.first_check(state, judge.questions()))
    except ai.Unavailable as e:
        return await _paused(guild, str(e))
    except providers.ProviderError as e:
        return log.warning(f"first check failed: {e}")
    log.info(f"alert from {member.id}: {screening.top} {screening.top_score:.2f}, "
             f"steering {screening.steering:.2f}")

    if screening.self_harm >= judge.SUPPORT_AT:
        await _support(member)
    s = settings.current()
    route = judge.route(screening, s)
    if route == judge.CLEAR:
        return
    if route == judge.ACT:
        verdict = await _explained(judge.first_check_verdict(screening), state, screening)
    else:
        try:
            verdict = judge.verdict(await ai.review(judge.review_prompt(state),
                                                    judge.REVIEW_SCHEMA))
        except ai.Unavailable as e:
            return await _paused(guild, str(e))
        except providers.ProviderError as e:
            return log.warning(f"review failed: {e}")
        if verdict is None:
            return

    now = int(time.time())
    record = cases.record_of(member.id, now, s["warning_days"])
    sanction = judge.sanction(verdict.severity, record, s)
    case = cases.open_case(
        now, user_id=member.id, action=sanction.action, minutes=sanction.minutes,
        deleted=False, rule=verdict.rule, severity=verdict.severity,
        explanation=verdict.explanation, scores=screening.scores, record=record,
        channel_id=channel.id, message_id=execution.message_id,
        excerpt=execution.content[:300], decided_by=verdict.decided_by,
    )
    problem = await _apply(guild, member, channel, execution.message_id, sanction, case)
    case = cases.update(case["no"], deleted=sanction.delete and not problem,
                        problem=problem)
    await _post(guild, member, case, screening)


async def _explained(verdict, state, screening):
    """The first check's verdict with its public explanation. The decision
    stands whether or not the explanation can be written."""
    try:
        answer = await ai.review(judge.explain_prompt(state, verdict), judge.EXPLAIN_SCHEMA)
        verdict.explanation = str(answer.get("explanation") or "").strip()[:500]
    except (ai.Unavailable, providers.ProviderError) as e:
        log.warning(f"explanation not written: {e}")
    if not verdict.explanation:
        verdict.explanation = judge.fallback_explanation(verdict, screening)
    return verdict


async def _apply(guild, member, channel, message_id, sanction, case):
    """Carry out the sanction. Returns None, or what could not be done."""
    if member.id == guild.owner_id or member.top_role >= guild.me.top_role:
        return "the bot's role is not above this member's, so nothing was applied"
    title = conduct.RULES[case["rule"] - 1][0]
    try:
        await member.send(
            f"**{cases.label(case)}** in {guild.name}, case {case['no']}.\n"
            f"{case['explanation']} (Rule {case['rule']}: {title}.)\n"
            "Every case is posted publicly in the server's #mod-log. If you think "
            "it's wrong, press Appeal and the community will vote on it.",
            view=appeals.appeal_view(case["no"]))
    except discord.HTTPException:
        pass  # DMs closed; the public log still says it
    reason = f"Case {case['no']}: rule {case['rule']}"
    try:
        if sanction.delete and message_id:
            try:
                await channel.get_partial_message(message_id).delete()
            except discord.NotFound:
                pass
        if sanction.action == cases.TIMEOUT:
            await member.timeout(timedelta(minutes=sanction.minutes), reason=reason)
        elif sanction.action == cases.BAN:
            await guild.ban(member, reason=reason, delete_message_seconds=3600)
    except discord.HTTPException as e:
        return f"Discord refused: {e.text or e.status}"
    return None


async def _post(guild, member, case, screening):
    log_channel = layout.channel(guild, "mod-log")
    if log_channel is None:
        return
    title = conduct.RULES[case["rule"] - 1][0]
    embed = discord.Embed(
        title=f"Case {case['no']} · {cases.label(case)}"
              + (" · message deleted" if case["deleted"] else ""),
        description=case["explanation"],
        colour={cases.WARN: discord.Colour.gold(), cases.TIMEOUT: discord.Colour.orange(),
                cases.BAN: discord.Colour.red()}[case["action"]],
    )
    embed.add_field(name="Member", value=f"<@{case['user_id']}>")
    embed.add_field(name="Rule", value=f"{case['rule']}. {title}")
    embed.add_field(name="Severity", value=case["severity"])
    record = case["record"]
    days = settings.current()["warning_days"]
    embed.add_field(
        name=f"Record before this (last {days} days)",
        value=f"{record['warnings']} warnings, {record['timeouts']} timeouts",
        inline=False,
    )
    embed.add_field(
        name="First check",
        value=f"{screening.top.replace('_', ' ')}: {screening.top_score:.0%} likely",
    )
    embed.add_field(
        name="Decided by",
        value=("the first check, which was sure enough to act on its own"
               if case["decided_by"] == judge.FIRST_CHECK
               else "a second review, because the first check was unsure"),
    )
    if case["rule"] in judge.HIDDEN_RULES:
        excerpt = "(not repeated here, to avoid spreading it)"
    else:
        excerpt = "||" + discord.utils.escape_markdown(case["excerpt"]) + "||"
    embed.add_field(name="Message", value=excerpt[:1024], inline=False)
    if case.get("problem"):
        embed.add_field(name="Not applied", value=case["problem"], inline=False)
    embed.set_footer(text=f"Think this is wrong? Anyone can appeal it with "
                          f"/appeal case:{case['no']}")
    message = await log_channel.send(embed=embed,
                                     allowed_mentions=discord.AllowedMentions.none())
    cases.update(case["no"], log_message_id=message.id)


async def _support(member):
    now = time.time()
    if now - _supported.get(member.id, 0) < 24 * 60 * 60:
        return
    _supported[member.id] = now
    try:
        await member.send(SUPPORT_LINE)
    except discord.HTTPException:
        pass


async def _paused(guild, why):
    """Say once, publicly, that moderation is paused and why."""
    global _paused_notice
    if _paused_notice == why:
        return
    _paused_notice = why
    log_channel = layout.channel(guild, "mod-log")
    if log_channel:
        await log_channel.send(
            f"Moderation is paused: {why}. AutoMod still blocks scams, phone "
            "numbers, slurs, mass mentions and spam in the meantime.")


class KeyForm(discord.ui.Modal, title="AI key"):
    key = discord.ui.TextInput(label="OpenRouter API key", placeholder="sk-or-v1-...",
                               min_length=20, max_length=200)
    budget = discord.ui.TextInput(label="Monthly budget in US dollars",
                                  default=f"{ai.DEFAULT_BUDGET:g}", max_length=6)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            budget = float(self.budget.value)
        except ValueError:
            return await interaction.followup.send("The budget must be a number.",
                                                   ephemeral=True)
        try:
            await ai.check_key(self.key.value.strip())
        except providers.ProviderError as e:
            return await interaction.followup.send(
                f"OpenRouter refused that key: {e}", ephemeral=True)
        ai.configure(self.key.value, budget)
        global _paused_notice
        _paused_notice = None
        spent, _ = ai.spending(time.time())
        await interaction.followup.send(
            f"Saved. Moderation is on, with a budget of ${budget:.2f} a month "
            f"(${spent:.2f} spent so far this month).", ephemeral=True)


@app_commands.command(name="ai-key",
                      description="Owner only: set the AI key and monthly budget")
@app_commands.default_permissions(administrator=True)
async def ai_key(interaction: discord.Interaction):
    if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Only the server owner can set the AI key, because the owner pays for it.",
            ephemeral=True)
    await interaction.response.send_modal(KeyForm())


def setup(tree):
    """Registers /ai-key. bot.py forwards AutoMod events to
    on_automod_action."""
    tree.add_command(ai_key)
