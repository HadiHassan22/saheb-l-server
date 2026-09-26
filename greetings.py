"""The daily greeting in one channel.

The first time a member posts in the greeting channel on a given day, the
bot replies "ija el batal". One greeting per member per day, in that
channel alone. The bot notices who posted and when, never what the
message says: all it keeps is who was greeted on which day, and a day is
the one Beirut is in, so the greeting comes back every morning.
"""

from datetime import datetime, timezone

import quick
import store

CHANNEL_ID = 1551963729627971617   # the channel the greeting is for
GREETING = "ija el batal"


def greeted(member_id, now):
    """True if this member has already been greeted today; otherwise
    remembers them for today and returns False."""
    day = now.astimezone(quick.BEIRUT).date().isoformat()
    greeted_on = store.load("greetings", {})
    if greeted_on.get(str(member_id)) == day:
        return True
    greeted_on[str(member_id)] = day
    store.save("greetings", greeted_on)
    return False


async def on_message(message, now=None):
    if message.channel.id != CHANNEL_ID or message.author.bot:
        return
    if not (message.content.strip() or message.attachments):
        return  # nothing was posted: a system message, not a member
    now = now or datetime.now(timezone.utc)
    if greeted(message.author.id, now):
        return
    await message.reply(GREETING, mention_author=False)
