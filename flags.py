"""Members flag a message for Saheb by reacting to it with 🚩.

Telling Saheb about someone in chat only gives it your word, and a member
could lie to get someone else in trouble. A flag gives it the message
itself: the moderator reads it and the conversation before it and judges
it like an AutoMod alert (moderator.handle_flag). Saheb then either
replies to it, or scolds its author and acts, at most a warning or a
`flag_timeout_minutes` timeout. Who flagged it is never part of the
judgement.

The bot takes the 🚩 straight off again, so the author doesn't see who
flagged them and nobody piles on. Each message is judged once, only if it
is recent, and each member can flag a few an hour, because every judgement
costs the owner's AI budget.
"""

import asyncio
import collections
import logging
import time

import discord

import cases
import layout
import moderator

log = logging.getLogger("flags")

FLAG = "🚩"
PER_WINDOW, WINDOW = 5, 60 * 60     # flags per member per window
MAX_AGE = 24 * 60 * 60              # older messages can't be flagged

_flagged = collections.defaultdict(collections.deque)
_judged = {}


def allowed(member_id, now):
    """True if this member may flag again now, and counts the flag."""
    flagged = _flagged[member_id]
    while flagged and now - flagged[0] > WINDOW:
        flagged.popleft()
    if len(flagged) >= PER_WINDOW:
        return False
    flagged.append(now)
    return True


def judged(message_id, now):
    """True if this message was already flagged. Forgotten after MAX_AGE,
    when it can't be flagged anyway."""
    for old in [m for m, t in _judged.items() if now - t > MAX_AGE]:
        del _judged[old]
    return message_id in _judged


async def on_reaction(payload: discord.RawReactionActionEvent, client):
    if str(payload.emoji) != FLAG or payload.guild_id != layout.home_id():
        return
    flagger = payload.member
    if flagger is None or flagger.bot:
        return
    guild = client.get_guild(payload.guild_id)
    channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
    if channel is None:
        return
    try:
        await channel.get_partial_message(payload.message_id).remove_reaction(
            FLAG, flagger)
    except discord.HTTPException:
        pass  # the flag still counts; it just stays visible
    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.HTTPException:
        return
    author = message.author
    if (author.bot or author.id == flagger.id or not isinstance(author, discord.Member)
            or not message.content.strip()):
        return
    now = time.time()
    if (now - message.created_at.timestamp() > MAX_AGE or judged(message.id, now)
            or cases.about_message(message.id)):
        return
    if not allowed(flagger.id, now):
        try:
            await flagger.send(f"You've flagged {PER_WINDOW} messages in the last hour. "
                               "Give it a little while before flagging more.")
        except discord.HTTPException:
            pass
        return
    _judged[message.id] = now
    lock = moderator._locks.setdefault(author.id, asyncio.Lock())
    async with lock:
        try:
            await moderator.handle_flag(message)
        except Exception as e:
            log.error(f"flag on {message.id} could not be handled: {e!r}")
