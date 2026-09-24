"""The server the bot builds for itself, and where everything in it is.

The bot is made for a brand-new server and needs Administrator. On its
first start it builds the layout below, adopting Discord's default
#general and General voice channel and removing the empty default
categories. On every start after that it recreates anything missing and
brings the AutoMod rules and the #welcome and #rules posts up to date.
Channels are remembered by id, so renaming one changes nothing.
"""

import logging

import discord

import automod
import conduct
import store

log = logging.getLogger("layout")

READ_ONLY = "read only"          # members read and react; only the bot posts
THREADS_ONLY = "threads only"    # members talk in threads the bot opens
OPEN = "open"
HIDDEN = "hidden"                # the bot alone
VOICE = "voice"

PLAN = [
    ("Start here", [
        ("welcome", READ_ONLY, "How this server works."),
        ("rules", READ_ONLY, "The rules the moderator enforces. Change them by vote."),
        ("mod-log", READ_ONLY, "Every moderation action, with the reasoning."),
    ]),
    ("Governance", [
        ("proposals", THREADS_ONLY,
         "Use /propose to add one. Discuss each proposal in its thread."),
    ]),
    ("Community", [
        ("general", OPEN, ""),
        ("off-topic", OPEN, ""),
        ("General", VOICE, ""),
    ]),
    ("Bot", [
        ("automod-alerts", HIDDEN,
         "AutoMod's alerts to the moderator. Hidden to keep flagged messages "
         "private; every action taken is in #mod-log."),
    ]),
]

DEFAULT_CATEGORIES = ("Text Channels", "Voice Channels")


def _saved():
    return store.load("layout", {"guild_id": None, "channels": {}, "messages": {}})


def home_id():
    return _saved()["guild_id"]


def channel(guild, name):
    """A channel from the plan, by its planned name, or None."""
    channel_id = _saved()["channels"].get(name)
    return guild.get_channel(channel_id) if guild and channel_id else None


def _overwrites(kind, guild):
    everyone = guild.default_role
    closed = discord.PermissionOverwrite(
        send_messages=False, create_public_threads=False,
        create_private_threads=False, send_messages_in_threads=False)
    if kind == READ_ONLY:
        return {everyone: closed}
    if kind == THREADS_ONLY:
        closed.send_messages_in_threads = True
        return {everyone: closed}
    if kind == HIDDEN:
        return {everyone: discord.PermissionOverwrite(view_channel=False)}
    return {}


def _adoptable(guild, name, kind):
    """Discord's default channel of this name, on the first build only."""
    kind_class = discord.VoiceChannel if kind == VOICE else discord.TextChannel
    for existing in guild.channels:
        if isinstance(existing, kind_class) and existing.name == name:
            return existing
    return None


async def build(guild):
    """Build or repair the layout. Returns False if the bot lacks the
    permission to, and logs why."""
    if not guild.me.guild_permissions.administrator:
        log.error(f"{guild.name}: the bot needs Administrator to run this server")
        return False
    saved = _saved()
    first = saved["guild_id"] != guild.id
    if first:
        saved = {"guild_id": guild.id, "channels": {}, "messages": {}}

    for category_name, channels in PLAN:
        category = guild.get_channel(saved["channels"].get(f"category:{category_name}") or 0)
        if category is None:
            category = await guild.create_category(category_name)
        saved["channels"][f"category:{category_name}"] = category.id
        for name, kind, topic in channels:
            existing = guild.get_channel(saved["channels"].get(name) or 0)
            if existing is None and first:
                existing = _adoptable(guild, name, kind)
                if existing is not None:
                    await existing.edit(category=category,
                                        overwrites=_overwrites(kind, guild))
            if existing is None:
                if kind == VOICE:
                    existing = await guild.create_voice_channel(name, category=category)
                else:
                    existing = await guild.create_text_channel(
                        name, category=category, topic=topic or None,
                        overwrites=_overwrites(kind, guild))
            saved["channels"][name] = existing.id

    if first:
        for leftover in guild.categories:
            if leftover.name in DEFAULT_CATEGORIES and not leftover.channels:
                await leftover.delete(reason="Replaced by the bot's layout")
        try:
            await guild.edit(
                verification_level=discord.VerificationLevel.medium,
                explicit_content_filter=discord.ContentFilter.all_members,
                default_notifications=discord.NotificationLevel.only_mentions,
                system_channel=guild.get_channel(saved["channels"]["general"]),
                reason="Initial setup",
            )
        except discord.HTTPException as e:
            log.warning(f"could not apply server settings: {e!r}")

    store.save("layout", saved)
    await automod.install(guild, channel(guild, "automod-alerts"))
    await post_texts(guild)
    return True


async def post_texts(guild):
    """Post #welcome and #rules, or edit them if the text has changed (for
    example after a vote changes a setting)."""
    owner = guild.owner.mention if guild.owner else "the server owner"
    mod_log = channel(guild, "mod-log")
    saved = _saved()
    welcome = conduct.welcome_text(owner, mod_log.mention if mod_log else "#mod-log")
    for name, text in (("welcome", welcome),
                       ("rules", conduct.rules_text())):
        target = channel(guild, name)
        if target is None:
            continue
        message = None
        if saved["messages"].get(name):
            try:
                message = await target.fetch_message(saved["messages"][name])
            except discord.NotFound:
                message = None
        if message is None:
            message = await target.send(text, allowed_mentions=discord.AllowedMentions.none())
            saved["messages"][name] = message.id
        elif message.content != text:
            await message.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
    store.save("layout", saved)
