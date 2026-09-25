"""Every way a proposal ends, in one place: its vote closes, an admin
passes it at once (Ship it), or an admin withdraws it.

Each moves the proposal to its final state (proposals.py) and then takes
the same steps in the same order:

1. its card shows the result, posted if it was never put to a vote;
2. if an admin ended it, #server-log says who, before anything is done;
3. its kind does what the ending means (kinds.py): a server change is
   made, a setting applied, an appeal's case overturned or left standing,
   or freed to be appealed again if the appeal was withdrawn;
4. what came of it is added to the card and, when a vote decided it,
   said under the card.

So no kind of proposal, and no way of ending one, can skip a step. A step
that fails is logged and the rest still happen. Checking that an admin is
an admin is the caller's job (admins.py).
"""

import logging

import discord

import cards
import kinds
import layout
import proposals

log = logging.getLogger("ending")


async def close(client, no, now):
    """Close proposal `no`'s vote and carry out the result, unless it has
    ended already. Returns the proposal."""
    if proposals.get(no)["status"] != proposals.OPEN:
        return proposals.get(no)
    p = proposals.close(no, now)
    log.info(f"proposal {no} closed: {p['status']}")
    p, _ = await _end(client, client.get_guild(layout.home_id() or 0), p)
    return p


async def pass_now(client, guild, no, admin_id, now):
    """Pass open proposal `no` on an admin's word, without a vote, and carry
    it out. Returns the proposal and a sentence saying what came of it.
    Raises proposals.Refused if it isn't open."""
    return await _end(client, guild, proposals.pass_now(no, admin_id, now), admin_id)


async def withdraw(client, guild, no, admin_id, reason, now):
    """Take open proposal `no` down on an admin's word, and return it.
    Raises proposals.Refused if it isn't open."""
    p, _ = await _end(client, guild, proposals.withdraw(no, admin_id, reason, now), admin_id)
    return p


async def _end(client, guild, p, admin_id=None):
    message = await _show(client, guild, p)
    if admin_id is not None:
        await _log(guild, p, admin_id, message)
    said = await _carry_out(client, guild, p)
    if said:
        p = proposals.record(p["no"], outcome=said[:1000])
    if message is not None:
        try:
            if said:
                await message.edit(embed=cards.card(p))
            if admin_id is None:
                await message.reply(cards.result(p), mention_author=False)
        except discord.HTTPException as e:
            log.warning(f"the result of proposal {p['no']} wasn't posted: {e!r}")
    return p, said


async def _show(client, guild, p):
    """Update `p`'s card, or post it if it has none. Returns the message,
    or None if there is nowhere to show it."""
    try:
        if p.get("message_id"):
            channel = client.get_channel(p["channel_id"] or 0)
            if channel is None:
                return None
            message = await channel.fetch_message(p["message_id"])
            await message.edit(embed=cards.card(p), view=None)
            return message
        channel = layout.channel(guild, "proposals")
        return await cards.post(p, channel) if channel is not None else None
    except discord.HTTPException as e:
        log.warning(f"proposal {p['no']}'s card wasn't updated: {e!r}")
        return None


async def _log(guild, p, admin_id, message):
    if p["status"] == proposals.WITHDRAWN:
        text = (f"<@{admin_id}> withdrew proposal {p['no']} ({p['title']}) as an admin"
                + (f": {p['note']}" if p.get("note") else "."))
    else:
        text = (f"<@{admin_id}> passed proposal {p['no']} ({p['title']}) without a vote, "
                "as an admin" + (f": {message.jump_url}" if message is not None else "."))
    try:
        await layout.server_log(guild, text)
    except discord.HTTPException as e:
        log.error(f"proposal {p['no']}'s admin action wasn't logged: {e!r}")


async def _carry_out(client, guild, p):
    kind = kinds.of(p)
    try:
        if p["status"] == proposals.PASSED:
            return await kind.carry_out(client, guild, p)
        return await kind.not_passed(client, guild, p)
    except Exception as e:
        log.error(f"carrying out proposal {p['no']} ({p['status']}) failed: {e!r}")
        return "The bot couldn't carry it out." if p["status"] == proposals.PASSED else None
