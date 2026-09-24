"""#ask-saheb: members talk to the bot in their own words (assistant.py
decides what it may do). Messages in every other channel are ignored.

Each member gets a short memory of their own recent exchanges, forgotten
after half an hour, and a limit on how often they can ask, because every
answer costs the owner's AI budget.
"""

import collections
import logging
import time

import discord

import ai
import assistant
import layout
import providers
import voting_ui

log = logging.getLogger("chat")

PER_WINDOW, WINDOW = 8, 10 * 60      # messages per member per window
MEMORY, MEMORY_TTL = 6, 30 * 60       # turns kept per member, and for how long

_asked = collections.defaultdict(collections.deque)
_memory = {}


def allowed(member_id, now):
    """True if this member may ask again now, and counts the question."""
    asked = _asked[member_id]
    while asked and now - asked[0] > WINDOW:
        asked.popleft()
    if len(asked) >= PER_WINDOW:
        return False
    asked.append(now)
    return True


def history(member_id, now):
    kept = _memory.get(member_id)
    if not kept or now - kept[0] > MEMORY_TTL:
        return []
    return kept[1]


def remember(member_id, now, question, answer):
    """Keep the exchange as plain text: tool rounds are not replayed."""
    turns = history(member_id, now) + [
        providers.said(question), providers.answered(providers.Reply(text=answer))]
    _memory[member_id] = (now, turns[-MEMORY:])


class FileDraft(discord.ui.DynamicItem[discord.ui.Button], template=r"draft:(?P<no>\d+)"):
    """Files a draft the bot wrote. Only the member it was written for can
    press it, and it files once."""

    def __init__(self, no, title=""):
        super().__init__(discord.ui.Button(
            label=f"File it: {title}"[:80] if title else "File it",
            style=discord.ButtonStyle.primary, custom_id=f"draft:{no}"))
        self.no = no

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["no"]))

    async def callback(self, interaction):
        draft = assistant.get_draft(self.no)
        if draft is None:
            return await interaction.response.send_message(
                "That draft has expired. Ask again for a new one.", ephemeral=True)
        if draft["author_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "Only the member who asked for this draft can file it.", ephemeral=True)
        if draft["filed"]:
            return await interaction.response.send_message(
                f"Already filed as proposal {draft['filed']}.", ephemeral=True)
        p = await voting_ui.publish(interaction, assistant.opener(draft, interaction.user.id))
        if p is not None:
            assistant.mark_filed(self.no, p["no"])


def drafts_view(drafts):
    if not drafts:
        return discord.utils.MISSING
    view = discord.ui.View(timeout=None)
    for draft in drafts[:5]:
        view.add_item(FileDraft(draft["no"], draft["title"]))
    return view


async def on_message(message):
    if message.author.bot or message.guild is None:
        return
    if not (message.content.strip() or message.attachments):
        return
    if message.guild.id != layout.home_id():
        return
    ask = layout.channel(message.guild, "ask-saheb")
    if ask is None or message.channel.id != ask.id:
        return
    now = time.time()
    if not allowed(message.author.id, now):
        return await message.reply("You've asked a lot in a short time. Give it a few "
                                   "minutes.", mention_author=False)
    ctx = assistant.Context(guild=message.guild, member=message.author,
                            attachments=list(message.attachments))
    text = message.content[:1500]
    if message.mentions:
        # The model sees raw mentions; name them, so a draft about a member
        # carries the exact member meant.
        text += "\n(Mentioned: " + ", ".join(
            f"{m.display_name} = <@{m.id}>" for m in message.mentions) + ")"
    if message.attachments:
        text += f"\n({len(message.attachments)} attachment(s))"
    try:
        async with message.channel.typing():
            answer = await assistant.respond(ctx, history(message.author.id, now), text)
    except ai.Unavailable as e:
        return await message.reply(f"I'm paused: {e}.", mention_author=False)
    except providers.ProviderError as e:
        log.warning(f"chat failed: {e}")
        return await message.reply("I couldn't think just now. Try again in a minute.",
                                   mention_author=False)
    remember(message.author.id, now, f"{message.author.display_name}: {text}", answer)
    await message.reply(answer[:2000], view=drafts_view(ctx.drafts), mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none())


def setup(client):
    client.add_dynamic_items(FileDraft)
