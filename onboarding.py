"""Discord's onboarding: what a new member is asked when they join, and the
channels they see from the start.

Discord shows it only on a Community server. It has two parts here:

- The server's own questions, which point members to channels ("What are
  you into?" Gaming opens #gaming), and the default channels everyone sees.
  Both start as the defaults below, the kind of welcome most community
  servers have, and change like any server change (actions.py), by a vote
  or at once by an admin.
- Every picker in #roles, asked as a question too, with the same roles and
  the same pick one or pick any (pickers.py). A role added to a picker
  later is offered to new members at once, with no change here.

Channels and roles are stored by id. A channel that's gone, or that
@everyone can't see (an opt-in one), is left out when the page is written;
Discord refuses those. The page is only written when what the bot would
write changes, so an admin's edit in Discord's own settings stays until the
next change to the pickers or to this.
"""

import json
import logging

import discord

import layout
import pickers
import store

log = logging.getLogger("onboarding")

MAX_QUESTIONS = 15
MAX_OPTIONS = 50
MAX_TITLE, MAX_OPTION_TITLE, MAX_DESCRIPTION = 100, 50, 100
MIN_CHANNELS, MIN_OPEN = 7, 5  # Discord's minimum: 7 default channels, 5 members can talk in
REASON = "Keeping onboarding in step with the server"

# Planned channel names (layout.PLAN), turned into ids the first time.
DEFAULT_CHANNELS = ["welcome", "rules", "roles", "ask-saheb", "proposals", "mod-log",
                    "server-log", "general", "introductions", "memes", "media",
                    "off-topic", "General", "Ahwe", "Lounge"]
DEFAULT_QUESTIONS = [
    ("What are you into?", False, [
        ("Food", "🍽️", "Recipes, and the best man2oushe in town", ["food"]),
        ("Pets", "🐾", "Pictures required", ["pets"]),
        ("Gaming", "🎮", "What you're playing, and who wants to join",
         ["gaming", "Gaming 1", "Gaming 2"]),
        ("Music", "🎵", None, ["music"]),
        ("Sports", "⚽", "Football, basketball, and everything else", ["sports"]),
        ("Movies and TV", "🎬", None, ["movies-and-tv"]),
        ("Tech", "💻", None, ["tech"]),
        ("Cars", "🚗", None, ["cars"]),
        ("Study and work", "📚", "University, careers, and getting through exams",
         ["study-and-work", "Study Room"]),
    ]),
    ("What do you want to follow about Lebanon?", False, [
        ("News", "📰", "News from Lebanon, with sources", ["lebanon-news"]),
        ("Politics and religion", "🗳️", "Argue about ideas, not people",
         ["politics-and-religion"]),
        ("Diaspora", "✈️", "For Lebanese abroad", ["diaspora"]),
    ]),
]


def _ids(guild, names):
    return [found.id for name in names if (found := layout.channel(guild, name))]


def saved(guild):
    """{"channels": [ids], "questions": [...], "sent": ...}, starting from
    the defaults the first time."""
    data = store.load("onboarding", None)
    if data is None:
        data = {"channels": _ids(guild, DEFAULT_CHANNELS), "sent": None, "questions": [
            {"title": title, "one": one, "options": [
                {"title": option, "emoji": emoji, "description": description,
                 "channels": _ids(guild, channels), "roles": []}
                for option, emoji, description, channels in options]}
            for title, one, options in DEFAULT_QUESTIONS]}
        store.save("onboarding", data)
    return data


def save(data):
    store.save("onboarding", data)


def find(guild, title):
    """The server's own question called `title`, ignoring case, or None."""
    title = str(title or "").strip().lower()
    return next((q for q in saved(guild)["questions"] if q["title"].lower() == title), None)


def seen_by_everyone(guild, channel):
    return channel.permissions_for(guild.default_role).view_channel


def open_to_talk(guild, channel):
    """A text channel @everyone can see and write in: Discord counts these."""
    allowed = channel.permissions_for(guild.default_role)
    return (isinstance(channel, discord.TextChannel) and allowed.view_channel
            and allowed.send_messages)


def _usable(guild, ids):
    return [c.id for i in ids if (c := guild.get_channel(i)) is not None
            and not isinstance(c, discord.CategoryChannel) and seen_by_everyone(guild, c)]


def page(guild):
    """What the onboarding page should say now, as plain data: the default
    channels, and the questions (the server's own, then one per picker).
    Missing and hidden channels, missing roles, and options left with
    neither, are dropped."""
    data = saved(guild)
    asked = []
    for question in data["questions"]:
        asked.append({"title": question["title"], "one": question["one"], "options": [
            {**option, "channels": _usable(guild, option["channels"]),
             "roles": [r for r in option["roles"] if guild.get_role(r)]}
            for option in question["options"]]})
    # Members' pickers first, the bot's own groups after, Opt-in roles last.
    shown = sorted(pickers.all_pickers(), key=lambda p: (
        bool(p.get("auto")), p["title"].startswith(pickers.OPT_IN), p["no"]))
    for picker in shown:
        asked.append({"title": picker["title"], "one": picker["one"], "options": [
            {"title": role.name[:MAX_OPTION_TITLE], "emoji": None, "description": None,
             "channels": [], "roles": [role.id]}
            for r in picker["roles"] if (role := guild.get_role(r))]})
    for question in asked:
        question["options"] = [o for o in question["options"]
                               if o["channels"] or o["roles"]][:MAX_OPTIONS]
    asked = [q for q in asked if q["options"]][:MAX_QUESTIONS]
    return {"channels": _usable(guild, data["channels"]), "questions": asked}


def _prompts(questions):
    return [discord.OnboardingPrompt(
        type=(discord.OnboardingPromptType.dropdown if len(q["options"]) > 12
              else discord.OnboardingPromptType.multiple_choice),
        title=q["title"][:MAX_TITLE], single_select=q["one"], required=False,
        in_onboarding=True, options=[discord.OnboardingPromptOption(
            title=o["title"][:MAX_OPTION_TITLE], emoji=o.get("emoji") or discord.utils.MISSING,
            description=(o.get("description") or None) and o["description"][:MAX_DESCRIPTION],
            channels=o["channels"], roles=o["roles"])
            for o in q["options"]])
        for q in questions]


def is_community(guild):
    return "COMMUNITY" in (getattr(guild, "features", None) or [])


async def sync(guild):
    """Write the onboarding page if it has changed. Returns None, or why it
    wasn't written."""
    if not is_community(guild):
        return "onboarding only exists once the server is a Community server"
    wanted = page(guild)
    signature = json.dumps(wanted, sort_keys=True, ensure_ascii=False)
    data = saved(guild)
    if data.get("sent") == signature:
        return None
    try:
        await guild.edit_onboarding(
            prompts=_prompts(wanted["questions"]),
            default_channels=[discord.Object(c) for c in wanted["channels"]],
            enabled=True, mode=discord.OnboardingMode.default, reason=REASON)
    except discord.HTTPException as e:
        log.warning(f"onboarding wasn't updated: {e!r}")
        return f"Discord refused it ({e.text or e.status})"
    data["sent"] = signature
    save(data)
    return None
