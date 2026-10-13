"""How a proposal looks. While it is put to a vote, its card is in #votes,
with the vote buttons and a thread for talking it over. When it ends, the
card leaves #votes and its thread is archived, and a record of how it went
takes its place in #proposals, kept up to date as a code change is
deployed. So #votes is only what is being voted on now, and #proposals is
how every proposal ended. Both are kept short: the full text is in the
thread. The words that differ by kind of proposal come from its kind
(kinds.py); everything else is the same for every proposal.
"""

import logging

import discord

import kinds
import proposals

log = logging.getLogger("cards")

COLOURS = {
    proposals.OPEN: discord.Colour.blurple(),
    proposals.PASSED: discord.Colour.green(),
    proposals.FAILED: discord.Colour.red(),
    proposals.NO_QUORUM: discord.Colour.light_grey(),
    proposals.WITHDRAWN: discord.Colour.dark_grey(),
}
RESULTS = {
    proposals.PASSED: "Passed",
    proposals.FAILED: "Failed",
    proposals.NO_QUORUM: "Not enough votes",
    proposals.WITHDRAWN: "Withdrawn",
}
# The role mentioned when a vote opens, so members see it and can vote.
PROPOSAL_ROLE_ID = 1558960826977616003
# How much of a proposal's text its card in #votes shows, and its record
# in #proposals. The rest is in its thread.
CARD_TEXT, RECORD_TEXT = 300, 150
# A week, so a thread stays in sight for the whole vote.
THREAD_ARCHIVE_MINUTES = 10080


def choices(p):
    """What Yes and No mean on `p`."""
    return kinds.of(p).choices


def shortened(text, size):
    return text if len(text) <= size else text[:size - 1].rstrip() + "…"


def card(p):
    """`p`'s card in #votes while it is open, or its record in #proposals
    once it has ended."""
    yes, no = proposals.tally(p)
    say = choices(p)
    embed = discord.Embed(title=f"Proposal {p['no']}: {p['title']}"[:256],
                          colour=COLOURS[p["status"]])
    if p["status"] == proposals.OPEN:
        # A vote about a person shows turnout only, so nobody votes with the
        # crowd against someone.
        counted = (f"{yes + no} voted so far, count hidden until it closes"
                   if p.get("blind") else f"{yes} {say['yes']} · {no} {say['no']}")
        embed.description = (
            f"{shortened(p['details'], CARD_TEXT)}\n\n"
            f"By <@{p['author_id']}> · closes <t:{int(p['closes_at'])}:R>\n"
            f"**{counted}** · needs {p['quorum']} votes and more than "
            f"{p['pass_percent']}% {say['yes']}")
        embed.set_footer(text=f"Secret ballot. Members of {p['voter_min_days']}+ days, and "
                              "everyone from the server's first week, can vote. Talk it "
                              "over in the thread." + kinds.of(p).footer)
        return embed
    if p.get("shipped_by"):
        result = f"**Passed by an admin**, <@{p['shipped_by']}>, without a vote"
        embed.set_footer(text="An admin skipped the vote. " + kinds.of(p).shipped_footer)
    elif p.get("withdrawn_by"):
        result = (f"**Withdrawn by an admin**, <@{p['withdrawn_by']}>"
                  + (f": {p['note'][:500]}" if p.get("note") else ""))
        embed.set_footer(text="An admin withdrew this proposal. Its ballots were not "
                              "counted.")
    else:
        result = f"**{RESULTS[p['status']]}**: {yes} {say['yes']} · {no} {say['no']}"
    lines = [shortened(p["details"], RECORD_TEXT), "",
             f"By <@{p['author_id']}> · {result}"]
    if p.get("outcome"):
        lines.append(p["outcome"][:1000])
    if p.get("progress"):
        lines.append(f"**Code change:** {p['progress']}")
        if p.get("summary"):
            lines.append(p["summary"][:1500])
    if p.get("thread_id"):
        lines.append(f"Full text and discussion: <#{p['thread_id']}>")
    embed.description = "\n".join(lines)[:4096]
    return embed


def result(p):
    """What is said in `p`'s thread when its vote ends."""
    yes, no = proposals.tally(p)
    say = choices(p)
    counts = f"{yes} {say['yes']}, {no} {say['no']}"
    outcome = f" {p['outcome']}" if p.get("outcome") else ""
    if p["status"] == proposals.NO_QUORUM:
        said = (f"Proposal {p['no']} did not get enough votes to count "
                f"({counts}; it needed {p['quorum']}).")
    elif p["status"] == proposals.PASSED:
        said = f"Proposal {p['no']} passed ({counts})."
    else:
        said = f"Proposal {p['no']} failed ({counts})."
    return (said + outcome)[:2000]


async def post(p, channel, view=discord.utils.MISSING, ping=False):
    """Post `p`'s card in #votes (`channel`), with a thread for talking it
    over that opens with its full text, and return the card. `ping` also
    mentions the Proposal role, for a vote that has just opened."""
    content = f"<@&{PROPOSAL_ROLE_ID}>" if ping else None
    allowed = (discord.AllowedMentions(everyone=False, users=False,
                                       roles=[discord.Object(id=PROPOSAL_ROLE_ID)])
               if ping else None)
    message = await channel.send(content, embed=card(p), view=view, allowed_mentions=allowed)
    proposals.attach_message(p["no"], channel.id, message.id)
    try:
        thread = await message.create_thread(name=f"Proposal {p['no']}: {p['title']}"[:100],
                                             auto_archive_duration=THREAD_ARCHIVE_MINUTES)
        proposals.record(p["no"], thread_id=thread.id)
        if len(p["details"]) > CARD_TEXT:
            for start in range(0, len(p["details"]), 2000):
                await thread.send(p["details"][start:start + 2000],
                                  allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        log.warning(f"no thread for proposal {p['no']}: {e!r}")
    return message


async def post_record(p, channel):
    """Post how `p` ended in #proposals (`channel`), and return it. It is
    `p`'s message from then on."""
    message = await channel.send(embed=card(p))
    proposals.attach_message(p["no"], channel.id, message.id)
    return message


async def refresh(client, p):
    """Show `p` as it is now on its card or record."""
    channel = client.get_channel((p or {}).get("channel_id") or 0)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(p["message_id"])
        await message.edit(embed=card(p))
    except discord.HTTPException as e:
        log.warning(f"proposal {p['no']} wasn't updated: {e!r}")


async def close_thread(client, p, text=None):
    """Say `text`, if any, in `p`'s thread, and archive it: the vote is
    over."""
    thread_id = (p or {}).get("thread_id")
    if not thread_id:
        return
    try:
        thread = client.get_channel(thread_id) or await client.fetch_channel(thread_id)
        if text:
            await thread.send(text, allowed_mentions=discord.AllowedMentions.none())
        await thread.edit(archived=True)
    except discord.HTTPException as e:
        log.warning(f"proposal {p['no']}'s thread wasn't closed: {e!r}")
