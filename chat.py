"""#ask-saheb: members talk to the bot in their own words (assistant.py
decides what it may do). Messages in every other channel are ignored.

It answers only when tagged or replied to, so members can also talk to
each other in the channel without every message costing an answer.

Each member gets a short memory of their own recent exchanges, forgotten
after half an hour, and a limit on how often they can ask, because every
answer costs the owner's AI budget. An admin can switch the limit off with
/admin chat-limit; the monthly budget in ai.py still caps the spending.
"""

import collections
import logging
import time

import discord
from discord import app_commands

import admins
import ai
import assistant
import layout
import providers
import store
import voting_ui

log = logging.getLogger("chat")

PER_WINDOW, WINDOW = 20, 10 * 60     # messages per member per window
MEMORY, MEMORY_TTL = 6, 30 * 60       # turns kept per member, and for how long

_asked = collections.defaultdict(collections.deque)
_memory = {}


def limited():
    """True unless an admin has switched the limit off."""
    return store.load("chat", {}).get("limited", True)


def allowed(member_id, now):
    """True if this member may ask again now, and counts the question."""
    if not limited():
        return True
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


async def replied_to(message, me):
    """The bot's message this one replies to, or None."""
    ref = message.reference
    if ref is None or ref.message_id is None:
        return None
    replied = ref.resolved if isinstance(ref.resolved, discord.Message) else None
    if replied is None and ref.cached_message is None:
        try:
            replied = await message.channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return None
    replied = replied or ref.cached_message
    return replied if replied.author.id == me.id else None


def tagged(message, me):
    """True if the message mentions the bot, or its own role (Discord often
    offers the role when someone types @Saheb)."""
    return (any(m.id == me.id for m in message.mentions)
            or any(r.is_bot_managed() and r in me.roles for r in message.role_mentions))


class ShipDraft(discord.ui.DynamicItem[discord.ui.Button], template=r"ship:(?P<no>\d+)"):
    """Does what an admin's draft asks at once, without a vote (admins.py):
    it is filed as passed and carried out like a passed vote. Whether they
    are an admin is checked again when they press it."""

    def __init__(self, no):
        super().__init__(discord.ui.Button(
            label="Ship it (no vote)", style=discord.ButtonStyle.danger,
            custom_id=f"ship:{no}"))
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
                "Only the member who asked for this draft can ship it.", ephemeral=True)
        if not admins.allowed(interaction.user.id, interaction.guild):
            return await interaction.response.send_message(
                "Only an admin can skip the vote. Use File it instead.", ephemeral=True)
        if draft["filed"]:
            return await interaction.response.send_message(
                f"Already filed as proposal {draft['filed']}.", ephemeral=True)
        p = await voting_ui.publish(interaction, assistant.opener(draft, interaction.user.id),
                                    by_admin=True)
        if p is not None:
            assistant.mark_filed(self.no, p["no"])


def drafts_view(drafts, admin=False):
    """A File it button for each draft, and for an admin, a Ship it button
    that skips the vote."""
    if not drafts:
        return discord.utils.MISSING
    view = discord.ui.View(timeout=None)
    for draft in drafts[:5]:
        view.add_item(FileDraft(draft["no"], draft["title"]))
        if admin:
            view.add_item(ShipDraft(draft["no"]))
    return view


def strip_tag(content, me):
    """The message without the bot's own mention or role mention."""
    for tag in [f"<@{me.id}>", f"<@!{me.id}>"] + [
            f"<@&{r.id}>" for r in me.roles if r.is_bot_managed()]:
        content = content.replace(tag, "")
    return " ".join(content.split())


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
    me = message.guild.me
    replied = await replied_to(message, me)
    if replied is None and not tagged(message, me):
        return
    now = time.time()
    if not allowed(message.author.id, now):
        return await message.reply("You've asked a lot in a short time. Give it a few "
                                   "minutes.", mention_author=False)
    ctx = assistant.Context(guild=message.guild, member=message.author,
                            attachments=list(message.attachments))
    text = strip_tag(message.content, me)[:1500] or "(tagged you with no text)"
    others = [m for m in message.mentions if m.id != me.id]
    if others:
        # The model sees raw mentions; name them, so a draft about a member
        # carries the exact member meant.
        text += "\n(Mentioned: " + ", ".join(
            f"{m.display_name} = <@{m.id}>" for m in others) + ")"
    if replied is not None and replied.content:
        # It may be an answer to someone else, not in this member's memory.
        text += f"\n(Replying to your message: {replied.content[:500]})"
    if message.attachments:
        text += f"\n({len(message.attachments)} attachment(s))"
    admin = admins.allowed(message.author.id, message.guild)
    if admin:
        text += ("\n(This member is an admin: every draft you make for them also gets a "
                 "Ship it button, which does it at once without a vote.)")
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
    await message.reply(answer[:2000], view=drafts_view(ctx.drafts, admin),
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none())


@admins.group.command(name="chat-limit",
                      description="Admins: turn the #ask-saheb limit on or off")
@app_commands.describe(on=f"On: each member can ask {PER_WINDOW} times in "
                          f"{WINDOW // 60} minutes. Off: no limit.")
async def chat_limit(interaction: discord.Interaction, on: bool):
    guild, user = interaction.guild, interaction.user
    if not admins.allowed(user.id, guild):
        return await interaction.response.send_message(
            "Only an admin can change this.", ephemeral=True)
    store.save("chat", {"limited": on})
    said = (f"on: each member can ask {PER_WINDOW} times in {WINDOW // 60} minutes"
            if on else "off")
    await layout.server_log(guild, f"{user.mention} turned the #ask-saheb limit {said}.")
    await interaction.response.send_message(f"The #ask-saheb limit is {said}.",
                                            ephemeral=True)


def setup(client):
    client.add_dynamic_items(FileDraft, ShipDraft)
