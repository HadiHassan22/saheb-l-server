"""The daily greeting: on a member's first message each day in the
channel the members chose for it, the bot says "ija el batal" and then
stays quiet until the next day.

It is a cheer and nothing else. The message is never read: only who spoke
where and when matters, so ordinary talk anywhere else is still unseen.
"""

import time
from datetime import datetime

import quick
import store

GREETING = "ija el batal"
# The channel the greeting lives in: members moved it here instead of
# #general. Channels are remembered by id, so renaming it changes nothing.
CHANNEL = 1552743198923686072


def _state():
    return store.load("greetings", {"day": "", "said": []})


def greet_once(member_id, now):
    """True the first time this member speaks today (Beirut time), and
    remembers it until tomorrow."""
    day = datetime.fromtimestamp(now, quick.BEIRUT).date().isoformat()
    state = _state()
    if state["day"] != day:
        state = {"day": day, "said": []}
    if member_id in state["said"]:
        return False
    state["said"].append(member_id)
    store.save("greetings", state)
    return True


async def on_message(message):
    if message.author.bot or message.guild is None:
        return
    if message.channel.id != CHANNEL:
        return
    if greet_once(message.author.id, time.time()):
        await message.reply(GREETING, mention_author=False)
