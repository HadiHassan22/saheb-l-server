"""The server the bot builds for itself, and where everything in it is.

The bot is made for a brand-new server and needs Administrator. On its
first start it builds the layout below, adopting Discord's default
#general and General voice channel and removing the empty default
categories. On every start after that it recreates anything missing and
brings the AutoMod rules and the #welcome and #rules posts up to date.
Channels are remembered by id, so renaming one changes nothing.

Once the server is a Community server, Discord has a rules channel of its
own (Server Settings, Safety Setup) and points new members at it. The bot
uses that one as #rules, so the rules are where Discord sends people.
"""

import logging

import discord

import automod
import colors
import conduct
import store

log = logging.getLogger("layout")

READ_ONLY = "read only"          # members read and react; only the bot posts
THREADS_ONLY = "threads only"    # members talk in threads the bot opens
OPEN = "open"
HIDDEN = "hidden"                # the bot alone
VOICE = "voice"
AFK = "afk"                      # the voice channel idle members are moved to


def room(name, kind=OPEN, topic="", slowmode=0):
    """One channel in the plan. `slowmode` is seconds between a member's
    messages; `name` is also how the bot finds the channel again."""
    return {"name": name, "kind": kind, "topic": topic, "slowmode": slowmode}


PLAN = [
    ("Start here", [
        room("welcome", READ_ONLY, "How this server works."),
        room("rules", READ_ONLY, "The rules the moderator enforces. Change them by vote."),
        room("roles", READ_ONLY,
             "Pick a name color here or with /color. Colors are only for looks: "
             "they give no powers."),
        room("mod-log", READ_ONLY, "Every moderation action, with the reasoning."),
        room("server-log", READ_ONLY,
             "Everything the bot does to the server: votes carried out, events, pins, "
             "temporary channels, and who asked."),
    ]),
    ("Governance", [
        room("ask-saheb",
             topic="Tag Saheb l Server or reply to it: ask how things work, change "
                   "your name color, or have it draft a proposal.", slowmode=5),
        room("proposals", THREADS_ONLY,
             "Use /propose to add one. Discuss each proposal in its thread."),
    ]),
    ("Hangout", [
        room("general", topic="Everything and nothing. English, Arabic and Arabizi "
                              "all welcome."),
        room("introductions", topic="New here? Say hi: where you're from and what "
                                    "you're into.", slowmode=60),
        room("memes"),
        room("media", topic="Photos, videos, and things you made."),
        room("off-topic"),
    ]),
    ("Lebanon", [
        room("lebanon-news", topic="News from Lebanon. Share your source.", slowmode=10),
        room("politics-and-religion",
             topic="Argue about ideas, not people. Rule 2 applies: attacking anyone "
                   "for their religion, sect or background isn't allowed.",
             slowmode=30),
        room("diaspora", topic="For Lebanese abroad: where you are, and what you miss."),
    ]),
    ("Interests", [
        room("food", topic="Recipes, the best man2oushe in town, and what you ate today."),
        room("pets", topic="Pictures required."),
        room("gaming", topic="What you're playing, and who wants to join."),
        room("music"),
        room("sports", topic="Football, basketball, and everything else."),
        room("movies-and-tv"),
        room("tech"),
        room("cars"),
        room("study-and-work", topic="University, careers, and getting through exams."),
    ]),
    ("Voice", [
        room("General", VOICE),
        room("Ahwe", VOICE),
        room("Lounge", VOICE),
        room("Gaming 1", VOICE),
        room("Gaming 2", VOICE),
        room("Study Room", VOICE),
        room("AFK", AFK),
    ]),
    ("Bot", [
        room("automod-alerts", HIDDEN,
             "AutoMod's alerts to the moderator. Hidden to keep flagged messages "
             "private; every action taken is in #mod-log."),
        # Who can read it is admins.py's job, not the plan's.
        room("admin-log", HIDDEN,
             "For the admins and the owner: how code changes are going, with links."),
    ]),
]

DEFAULT_CATEGORIES = ("Text Channels", "Voice Channels")


def _saved():
    saved = store.load("layout", {"guild_id": None, "channels": {}, "messages": {}})
    saved.setdefault("removed", [])
    return saved


def forget(guild, channel_id):
    """A planned channel was deleted by vote: stop rebuilding it."""
    saved = _saved()
    for name, known in list(saved["channels"].items()):
        if known == channel_id:
            del saved["channels"][name]
            saved["removed"].append(name)
    store.save("layout", saved)


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


async def _adopt_rules_channel(guild, saved, category):
    """Use Discord's own rules channel as #rules, if the server has one
    and it isn't #rules already. The #rules the bot built before is
    deleted, but only if nobody but the bot ever posted in it."""
    rules = guild.rules_channel
    if rules is None or saved["channels"].get("rules") == rules.id:
        return
    old = guild.get_channel(saved["channels"].get("rules") or 0)
    saved["channels"]["rules"] = rules.id
    saved["messages"].pop("rules", None)
    await rules.edit(category=category, overwrites=_overwrites(READ_ONLY, guild))
    if old is None:
        return
    try:
        if all(m.author.id == guild.me.id for m in [m async for m in old.history(limit=50)]):
            await old.delete(reason="The rules moved to the server's rules channel")
    except discord.HTTPException as e:
        log.warning(f"the old #rules was not deleted: {e!r}")


def _adoptable(guild, name, kind):
    """Discord's default channel of this name, on the first build only."""
    kind_class = discord.VoiceChannel if kind in (VOICE, AFK) else discord.TextChannel
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
        saved = {"guild_id": guild.id, "channels": {}, "messages": {}, "removed": []}

    for category_name, channels in PLAN:
        category = guild.get_channel(saved["channels"].get(f"category:{category_name}") or 0)
        if category is None:
            category = await guild.create_category(category_name)
        saved["channels"][f"category:{category_name}"] = category.id
        if any(spec["name"] == "rules" for spec in channels):
            await _adopt_rules_channel(guild, saved, category)
        for spec in channels:
            name, kind = spec["name"], spec["kind"]
            if name in saved["removed"]:
                continue
            existing = guild.get_channel(saved["channels"].get(name) or 0)
            if existing is None and first:
                existing = _adoptable(guild, name, kind)
                if existing is not None:
                    await existing.edit(category=category,
                                        overwrites=_overwrites(kind, guild))
            if existing is None:
                if kind in (VOICE, AFK):
                    existing = await guild.create_voice_channel(name, category=category)
                else:
                    existing = await guild.create_text_channel(
                        name, category=category, topic=spec["topic"] or None,
                        slowmode_delay=spec["slowmode"],
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
                afk_channel=guild.get_channel(saved["channels"]["AFK"]),
                afk_timeout=900,
                reason="Initial setup",
            )
        except discord.HTTPException as e:
            log.warning(f"could not apply server settings: {e!r}")

    store.save("layout", saved)
    await automod.install(guild, channel(guild, "automod-alerts"))
    await post_texts(guild)
    await colors.install(guild, channel(guild, "roles"))
    return True


async def server_log(guild, text):
    """Say publicly what the bot did to the server, in #server-log."""
    target = channel(guild, "server-log")
    if target is not None:
        await target.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())


async def post_texts(guild):
    """Post #welcome and #rules, or edit them if the text has changed (for
    example after a vote changes a setting)."""
    owner = guild.owner.mention if guild.owner else "the server owner"
    mod_log = channel(guild, "mod-log")
    saved = _saved()
    ask = channel(guild, "ask-saheb")
    welcome = conduct.welcome_text(owner, mod_log.mention if mod_log else "#mod-log",
                                   ask.mention if ask else "#ask-saheb")
    # Embeds rather than plain messages: a description holds 4096 characters.
    for name, (title, text) in (("welcome", welcome), ("rules", conduct.rules_text())):
        target = channel(guild, name)
        if target is None:
            continue
        embed = discord.Embed(title=title, description=text, colour=discord.Colour.green())
        message = None
        if saved["messages"].get(name):
            try:
                message = await target.fetch_message(saved["messages"][name])
            except discord.NotFound:
                message = None
        if message is None:
            message = await target.send(embed=embed)
            saved["messages"][name] = message.id
        elif not message.embeds or message.embeds[0].description != text:
            await message.edit(content=None, embed=embed)
    store.save("layout", saved)
