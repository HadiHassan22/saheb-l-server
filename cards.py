"""How a proposal looks in #proposals: its card, the result posted under
it when the vote ends, and posting either. The words that differ by kind
of proposal come from its kind (kinds.py); everything else is the same
for every proposal.
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


def choices(p):
    """What Yes and No mean on `p`."""
    return kinds.of(p).choices


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
        embed.add_field(name="Result",
                        value=f"**Passed by an admin**, <@{p['shipped_by']}>, without a vote",
                        inline=False)
    elif p.get("withdrawn_by"):
        embed.add_field(name="Result",
                        value=f"**Withdrawn by an admin**, <@{p['withdrawn_by']}>, before "
                              "the vote ended",
                        inline=False)
        if p.get("note"):
            embed.add_field(name="Why", value=p["note"][:1000], inline=False)
    else:
        embed.add_field(
            name="Result",
            value=f"**{RESULTS[p['status']]}**: {yes} {say['yes']} · {no} {say['no']}",
            inline=False,
        )
    if p.get("outcome"):
        embed.add_field(name="Outcome", value=p["outcome"][:1000], inline=False)
    footer = (f"Secret ballot. Members of {p['voter_min_days']}+ days, and everyone "
              "who joined in the server's first week, can vote. "
              "Discuss in the thread." + kinds.of(p).footer)
    if p.get("shipped_by"):
        footer = "An admin skipped the vote. " + kinds.of(p).shipped_footer
    elif p.get("withdrawn_by"):
        footer = "An admin withdrew this proposal. Its ballots were not counted."
    embed.set_footer(text=footer)
    return embed


def result(p):
    """What is said under `p`'s card when its vote ends."""
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


async def post(p, channel, view=discord.utils.MISSING):
    """Post `p`'s card in `channel`, with a thread for discussing it, and
    return the message."""
    message = await channel.send(embed=card(p), view=view)
    proposals.attach_message(p["no"], channel.id, message.id)
    try:
        await message.create_thread(name=f"Proposal {p['no']}: {p['title']}"[:100])
    except discord.HTTPException as e:
        log.warning(f"no thread for proposal {p['no']}: {e!r}")
    return message


async def reply(client, p, text):
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
