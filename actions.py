"""Changes a vote can order, carried out by code when it passes. A
proposal to make one is the server-change kind of proposal (kinds.py).

Each change is checked twice: when it is drafted, so members only ever vote
on something that can actually be done, and again when it is carried out,
because the server may have changed during the vote. Things are named by
their current name when drafting and remembered by id after that.

Limits that hold whatever a vote says:
- the channels the bot depends on can't be renamed, deleted, purged or
  hidden, so the moderation and admin logs, and the record of every admin
  action, can't be wiped by a vote or an admin acting alone;
- roles are cosmetic: they are created with no permissions, and guard.py
  takes away any that appear later. A role can still open a channel to
  whoever holds it (set_channel_access): seeing a channel is not a power
  over anyone;
- rules 4 to 6 and the original rules can't be removed (conduct.py), and
  only watch words change, never what AutoMod blocks (automod.py);
- a vote about a member (kick, ban) needs `removal_percent`, hides its
  count until it closes, and the member can't vote on it.
"""

import logging
import re
import uuid

import discord

import automod
import conduct
import kinds
import layout
import onboarding
import pickers
import proposals
import store

log = logging.getLogger("actions")

CREATE, RENAME, DELETE, TOPIC, SLOWMODE, PURGE = (
    "create_channel", "rename_channel", "delete_channel", "set_topic", "set_slowmode",
    "purge_channel")
ACCESS = "set_channel_access"  # who can see a channel: everyone, or the holders of some roles
CATEGORY_CREATE, CATEGORY_RENAME, CATEGORY_DELETE = (
    "create_category", "rename_category", "delete_category")
ROLE_CREATE, ROLE_EDIT, ROLE_DELETE = "create_role", "edit_role", "delete_role"
EMOJI_ADD, EMOJI_REMOVE = "add_emoji", "remove_emoji"
SERVER_NAME, SERVER_ICON = "rename_server", "set_server_icon"
RULE_EDIT, RULE_ADD, RULE_REMOVE = "edit_rule", "add_rule", "remove_rule"
WATCH_ADD, WATCH_REMOVE = "add_watch_words", "remove_watch_words"
EVENT_CANCEL = "cancel_event"
KICK, BAN, UNBAN = "kick_member", "ban_member", "unban_member"
PICKER_CREATE, PICKER_EDIT, PICKER_DELETE = "create_picker", "edit_picker", "delete_picker"
ONBOARDING_CHANNELS, ONBOARDING_QUESTION, ONBOARDING_REMOVE = (
    "set_onboarding_channels", "set_onboarding_question", "remove_onboarding_question")

CHANNEL_KINDS = (CREATE, RENAME, DELETE, TOPIC, SLOWMODE, PURGE, ACCESS,
                 CATEGORY_CREATE, CATEGORY_RENAME, CATEGORY_DELETE)
ROLE_KINDS = (ROLE_CREATE, ROLE_EDIT, ROLE_DELETE)
EMOJI_KINDS = (EMOJI_ADD, EMOJI_REMOVE)
SERVER_KINDS = (SERVER_NAME, SERVER_ICON)
RULE_KINDS = (RULE_EDIT, RULE_ADD, RULE_REMOVE)
WATCH_KINDS = (WATCH_ADD, WATCH_REMOVE)
PEOPLE_KINDS = (KICK, BAN, UNBAN)
PICKER_KINDS = (PICKER_CREATE, PICKER_EDIT, PICKER_DELETE)
ONBOARDING_KINDS = (ONBOARDING_CHANNELS, ONBOARDING_QUESTION, ONBOARDING_REMOVE)
KINDS = (CHANNEL_KINDS + ROLE_KINDS + EMOJI_KINDS + SERVER_KINDS + RULE_KINDS
         + WATCH_KINDS + (EVENT_CANCEL,) + PEOPLE_KINDS + PICKER_KINDS + ONBOARDING_KINDS)
# Votes about a member: a higher bar, a hidden count, and no vote for them.
ABOUT_A_MEMBER = (KICK, BAN)

CORE = {"welcome", "rules", "roles", "mod-log", "server-log", "proposals", "ask-saheb",
        "automod-alerts", "admin-log", "AFK"}
TEXT_NAME = re.compile(r"^[a-z0-9-]{1,100}$")
EMOJI_NAME = re.compile(r"^[A-Za-z0-9_]{2,32}$")
MAX_CHANNELS, MAX_ROLES, MAX_RULES = 450, 100, 20
MAX_EMOJI_BYTES, MAX_ICON_BYTES = 256 * 1024, 4 * 1024 * 1024
REASON = "Ordered by a community vote"


# ---------- shared helpers ----------

def text_name(name):
    """How Discord would name a text channel: lowercase, dashes for spaces."""
    name = re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", str(name).strip().lower()))
    return re.sub(r"-{2,}", "-", name).strip("-")[:100]


def core_ids(guild):
    return {found.id for name in CORE if (found := layout.channel(guild, name))}


def member_id(text):
    """A member id from a mention or a bare id, else None."""
    digits = re.sub(r"[<@!>\s]", "", str(text or ""))
    return int(digits) if digits.isdigit() else None


def _roles():
    """Roles made by vote: {role id: {"joinable": bool}}."""
    return store.load("roles", {})


def voted_roles():
    return {int(k): v for k, v in _roles().items()}


def _save_role(role_id, joinable):
    saved = _roles()
    saved[str(role_id)] = {"joinable": joinable}
    store.save("roles", saved)


def _forget_role(role_id):
    saved = _roles()
    saved.pop(str(role_id), None)
    store.save("roles", saved)


def save_image(data):
    """Keep an attached image until the vote closes; Discord's attachment
    links expire sooner than that. Returns its name."""
    folder = store.DATA_DIR / "images"
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    (folder / name).write_bytes(data)
    return name


def load_image(name):
    return (store.DATA_DIR / "images" / name).read_bytes()


def _colour(value):
    """A discord.Colour from "#RRGGBB", or None."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value or "").strip())
    return discord.Colour(int(match[1], 16)) if match else None


# ---------- checking ----------

async def check(guild, action):
    """None if `action` can be carried out in `guild`, else why not. Fills
    in ids and normalised names as it goes."""
    kind = action.get("kind")
    if kind not in KINDS:
        return "That isn't a change a vote can order."
    if kind in CHANNEL_KINDS:
        return _check_channel(guild, action)
    if kind in ROLE_KINDS:
        return _check_role(guild, action)
    if kind in EMOJI_KINDS:
        return _check_emoji(guild, action)
    if kind in SERVER_KINDS:
        return _check_server(guild, action)
    if kind in RULE_KINDS:
        return _check_rule(action)
    if kind in WATCH_KINDS:
        return _check_watch(action)
    if kind == EVENT_CANCEL:
        return _check_event(guild, action)
    if kind in PICKER_KINDS:
        return _check_picker(guild, action)
    if kind in ONBOARDING_KINDS:
        return _check_onboarding(guild, action)
    return await _check_member(guild, action)


def _check_channel(guild, action):
    kind = action["kind"]
    if kind == CATEGORY_CREATE:
        name = str(action.get("name") or "").strip()[:100]
        if not name:
            return "Give the category a name."
        if discord.utils.get(guild.categories, name=name):
            return f"There's already a category called {name}."
        action["name"] = name
        return None
    if kind in (CATEGORY_RENAME, CATEGORY_DELETE):
        category = (guild.get_channel(action.get("category_id") or 0)
                    or discord.utils.get(guild.categories, name=action.get("category")))
        if not isinstance(category, discord.CategoryChannel):
            return "There's no category by that name."
        action["category_id"], action["category"] = category.id, category.name
        if kind == CATEGORY_DELETE and category.channels:
            return "Only an empty category can be deleted. Move or delete its channels first."
        if kind == CATEGORY_RENAME:
            new = str(action.get("name") or "").strip()[:100]
            if not new or new == category.name:
                return "That isn't a new name."
            action["name"] = new
        return None
    if kind == CREATE:
        voice = action.get("channel_type") == "voice"
        name = str(action.get("name") or "").strip()[:100] if voice else text_name(action.get("name"))
        if not name or (not voice and not TEXT_NAME.match(name)):
            return "That isn't a usable channel name."
        action["name"] = name
        action["channel_type"] = "voice" if voice else "text"
        if any(c.name == name for c in guild.channels):
            return f"There's already a channel called {name}."
        category = discord.utils.get(guild.categories, name=action.get("category"))
        if category is None:
            return ("Pick one of the existing categories: "
                    + ", ".join(c.name for c in guild.categories) + ".")
        if len(guild.channels) >= MAX_CHANNELS:
            return "The server has too many channels for another."
        return _check_text_settings(action)

    asked = str(action.get("channel") or "").strip().lstrip("#")
    target = (guild.get_channel(action.get("channel_id") or 0)
              or discord.utils.get(guild.channels, name=asked)
              or discord.utils.get(guild.channels, name=text_name(asked)))
    if target is None or isinstance(target, discord.CategoryChannel):
        return "There's no channel by that name."
    action["channel_id"] = target.id
    action["channel"] = target.name
    if target.id in core_ids(guild) and kind in (RENAME, DELETE, PURGE, ACCESS):
        return (f"#{target.name} is one the bot depends on, so it can't be renamed, "
                "deleted, purged or hidden.")
    if kind == ACCESS:
        names = action.get("roles") or []
        return _pick_roles(guild, names if isinstance(names, list) else [names], action,
                           allow_none=True)
    if kind == RENAME:
        voice = isinstance(target, discord.VoiceChannel)
        new = str(action.get("name") or "").strip()[:100] if voice else text_name(action.get("name"))
        if not new or new == target.name:
            return "That isn't a new usable name."
        action["name"] = new
    if kind in (TOPIC, SLOWMODE) and not isinstance(target, discord.TextChannel):
        return "Only text channels have a topic and slowmode."
    if kind == PURGE:
        return (None if isinstance(target, discord.TextChannel)
                else "Only text channels can be purged.")
    return _check_text_settings(action)


def _check_text_settings(action):
    topic = action.get("topic")
    if topic is not None and len(str(topic)) > 1024:
        return "A topic can be at most 1024 characters."
    slowmode = action.get("slowmode")
    if slowmode is not None and not (isinstance(slowmode, int) and 0 <= slowmode <= 21600):
        return "Slowmode is a number of seconds from 0 to 21600 (six hours)."
    if action["kind"] == SLOWMODE and slowmode is None:
        return "Say how many seconds of slowmode."
    if action["kind"] == TOPIC and topic is None:
        return "Say what the topic should be."
    return None


def _check_role(guild, action):
    kind = action["kind"]
    if kind == ROLE_CREATE:
        name = str(action.get("name") or "").strip()[:100]
        if not name:
            return "Give the role a name."
        if discord.utils.get(guild.roles, name=name):
            return f"There's already a role called {name}."
        if len(voted_roles()) >= MAX_ROLES:
            return "There are already as many roles as the server allows by vote."
        action["name"] = name
        action["joinable"] = bool(action.get("joinable", True))
        problem = _check_role_picker(action)
        if problem:
            return problem
    else:
        role = guild.get_role(action.get("role_id") or 0) or discord.utils.get(
            guild.roles, name=str(action.get("role") or "").strip().lstrip("@"))
        if role is None or role.id not in voted_roles():
            return "Only roles made by vote can be changed this way; that one isn't."
        action["role_id"], action["role"] = role.id, role.name
        if kind == ROLE_EDIT:
            changes = [k for k in ("name", "color", "joinable") if action.get(k) is not None]
            if not changes:
                return "Say what to change: its name, its color, or whether members can join it."
    if action.get("color") is not None and _colour(action["color"]) is None:
        return "A color is written like #1E88E5."
    return None


def _pick_roles(guild, names, action, allow_none=False):
    """Check the roles named in a picker or a channel's access: roles made
    by vote, or new ones, made with it (no powers, members can join them).
    Any other existing role (a name color, the Admin role) can't be used.
    Sets action["roles"] and action["new_roles"]."""
    names = list(dict.fromkeys(str(n).strip().lstrip("@")[:100] for n in names
                               if str(n).strip()))
    if not (0 if allow_none else 1) <= len(names) <= pickers.MAX_ROLES:
        return f"Name 1 to {pickers.MAX_ROLES} roles."
    voted, new = voted_roles(), []
    for name in names:
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            new.append(name)
        elif role.id not in voted:
            return f"{name} is a role members can't give themselves, so it can't be used."
    if len(voted) + len(new) > MAX_ROLES:
        return "That would make more roles than the server allows by vote."
    action["roles"], action["new_roles"] = names, new
    return None


async def _make_roles(guild, names):
    for name in names:
        role = await guild.create_role(name=name, permissions=discord.Permissions.none(),
                                       hoist=False, mentionable=False, reason=REASON)
        _save_role(role.id, True)


def _check_picker(guild, action):
    """A picker offers roles made by vote. Names it doesn't find yet are
    new roles, made with it; any other existing role (a name color, the
    Admin role) can't be offered."""
    kind = action["kind"]
    if kind != PICKER_CREATE:
        picker = pickers.get(action.get("picker_no") or 0) or pickers.find(action.get("picker"))
        if picker is None:
            return "There's no picker by that name. Ask me to list the roles to see them."
        if picker.get("auto") and kind == PICKER_DELETE:
            return (f"The bot keeps {picker['title']} itself: it offers every role members "
                    "can join that no other picker does. Change it, or the roles, instead.")
        action["picker_no"], action["picker"] = picker["no"], picker["title"]
        if kind == PICKER_DELETE:
            return None
        if picker.get("auto") and len(pickers.made_by_members()) >= pickers.MAX_PICKERS:
            return f"There are already {pickers.MAX_PICKERS} pickers, which is the most."
        if all(action.get(k) is None for k in ("title", "roles", "one")):
            return "Say what to change: its title, its roles, or whether members pick one."
    elif len(pickers.made_by_members()) >= pickers.MAX_PICKERS:
        return f"There are already {pickers.MAX_PICKERS} pickers, which is the most."
    if action.get("title") is not None:
        title = str(action["title"]).strip()[:100]
        if not title:
            return "Give the picker a title, like \"Where are you from?\"."
        same = pickers.find(title)
        if same is not None and same["no"] != action.get("picker_no"):
            return f"There's already a picker called {title}."
        action["title"] = title
    elif kind == PICKER_CREATE:
        return "Give the picker a title, like \"Where are you from?\"."
    if action.get("roles") is not None:
        names = action["roles"] if isinstance(action["roles"], list) else [action["roles"]]
        problem = _pick_roles(guild, names, action)
        if problem:
            return problem
    elif kind == PICKER_CREATE:
        return "Say which roles the picker offers."
    if action.get("one") is not None or kind == PICKER_CREATE:
        action["one"] = bool(action.get("one", True))
    return None


def _check_role_picker(action):
    """A new role members can join goes in a picker in #roles: `picker`
    names one that exists, or a new one (members pick any, unless `one`)."""
    title = str(action.get("picker") or "").strip()[:100]
    found = pickers.find(title) if title else None
    if (not title or not action["joinable"]
            or (found and found["title"].startswith(pickers.OPT_IN))):
        action.pop("picker", None)  # the bot's own pickers offer it anyway
        return None
    # A group the bot made becomes an ordinary picker when a role is put in it.
    if ((found is None or found.get("auto"))
            and len(pickers.made_by_members()) >= pickers.MAX_PICKERS):
        return f"There are already {pickers.MAX_PICKERS} pickers; put it in one of those."
    if found is not None and len(found["roles"]) >= pickers.MAX_ROLES:
        return f"The picker {found['title']} is full."
    action["picker"] = found["title"] if found else title
    action["new_picker"] = found is None
    return None


def _find_channel(guild, name):
    asked = str(name or "").strip().lstrip("#")
    found = (discord.utils.get(guild.channels, name=asked)
             or discord.utils.get(guild.channels, name=text_name(asked)))
    return None if isinstance(found, discord.CategoryChannel) else found


def _onboarding_channels(guild, names):
    """Channel ids for `names`, or why not: onboarding can only show
    channels everyone can see."""
    ids = []
    for name in names if isinstance(names, list) else [names]:
        found = _find_channel(guild, name)
        if found is None:
            return None, f"There's no channel called {name}."
        if not onboarding.seen_by_everyone(guild, found):
            return None, f"#{found.name} is hidden from some members, so onboarding can't show it."
        ids.append(found.id)
    return list(dict.fromkeys(ids)), None


def _check_onboarding(guild, action):
    """The server's own onboarding questions and default channels. The
    questions from pickers change with the pickers."""
    kind, current = action["kind"], onboarding.saved(guild)
    if kind == ONBOARDING_CHANNELS:
        add, problem = _onboarding_channels(guild, action.get("add") or [])
        if problem:
            return problem
        remove, problem = _onboarding_channels(guild, action.get("remove") or [])
        if problem:
            return problem
        if not add and not remove:
            return "Say which channels to add to or remove from the ones new members see."
        after = [c for c in dict.fromkeys(current["channels"] + add) if c not in remove]
        seen = [c for i in after if (c := guild.get_channel(i))]
        if (len(seen) < onboarding.MIN_CHANNELS
                or sum(onboarding.open_to_talk(guild, c) for c in seen) < onboarding.MIN_OPEN):
            return (f"Discord needs at least {onboarding.MIN_CHANNELS} default channels, "
                    f"{onboarding.MIN_OPEN} of them ones everyone can write in.")
        action["add"] = [guild.get_channel(c).name for c in add]
        action["remove"] = [guild.get_channel(c).name for c in remove]
        action["channel_ids"] = after
        return None
    asked = action.get("question") or (action.get("title") if kind == ONBOARDING_QUESTION
                                       else None)
    existing = onboarding.find(guild, asked)
    if pickers.find(asked) is not None:
        return (f"{pickers.find(asked)['title']} is a picker in #roles, and onboarding asks "
                "it as it is. Change the picker instead.")
    if kind == ONBOARDING_REMOVE:
        if existing is None:
            return "There's no onboarding question by that name."
        action["question"] = existing["title"]
        return None
    if action.get("question") and existing is None:
        return "There's no onboarding question by that name."
    title = str(action.get("title") or (existing or {}).get("title") or "").strip()
    if not 1 <= len(title) <= onboarding.MAX_TITLE:
        return f"Give the question a title of up to {onboarding.MAX_TITLE} characters."
    clash = onboarding.find(guild, title)
    if pickers.find(title) is not None or (clash is not None and clash is not existing):
        return f"There's already a question or picker called {title}."
    if existing is None and (len(current["questions"]) + len(pickers.all_pickers())
                             >= onboarding.MAX_QUESTIONS):
        return f"Onboarding holds at most {onboarding.MAX_QUESTIONS} questions, pickers included."
    options = action.get("options") or []
    if not isinstance(options, list) or not 1 <= len(options) <= onboarding.MAX_OPTIONS:
        return f"A question needs 1 to {onboarding.MAX_OPTIONS} answers."
    voted, checked = voted_roles(), []
    for option in options:
        if not isinstance(option, dict):
            return "Each answer needs a title, and the channels or roles it gives."
        name = str(option.get("title") or "").strip()
        if not 1 <= len(name) <= onboarding.MAX_OPTION_TITLE:
            return f"Each answer needs a title of up to {onboarding.MAX_OPTION_TITLE} characters."
        description = str(option.get("description") or "").strip()
        if len(description) > onboarding.MAX_DESCRIPTION:
            return f"An answer's description can be at most {onboarding.MAX_DESCRIPTION} characters."
        emoji = str(option.get("emoji") or "").strip()
        if len(emoji) > 32 or " " in emoji:
            return "An answer's emoji is a single emoji."
        channels, problem = _onboarding_channels(guild, option.get("channels") or [])
        if problem:
            return problem
        roles = []
        for role_name in option.get("roles") or []:
            role = discord.utils.get(guild.roles, name=str(role_name).strip().lstrip("@"))
            if role is None or not voted.get(role.id, {}).get("joinable"):
                return f"{role_name} isn't a role members can join, so onboarding can't give it."
            roles.append(role.name)
        if not channels and not roles:
            return f"The answer {name} needs a channel or a role to give."
        checked.append({"title": name, "emoji": emoji or None,
                        "description": description or None,
                        "channels": [guild.get_channel(c).name for c in channels],
                        "roles": roles})
    action.update(title=title, one=bool(action.get("one", (existing or {}).get("one", False))),
                  options=checked)
    if existing is not None:
        action["question"] = existing["title"]
    return None


def _check_emoji(guild, action):
    name = str(action.get("name") or "").strip().strip(":")
    if action["kind"] == EMOJI_ADD:
        if not EMOJI_NAME.match(name):
            return "An emoji name is 2 to 32 letters, digits or underscores."
        if discord.utils.get(guild.emojis, name=name):
            return f"There's already an emoji called {name}."
        if not action.get("image"):
            return "Attach the image to your message."
        if len(guild.emojis) >= guild.emoji_limit:
            return "The server has no emoji slots left."
        action["name"] = name
        return None
    emoji = discord.utils.get(guild.emojis, name=name)
    if emoji is None:
        return "There's no emoji by that name."
    action["name"], action["emoji_id"] = emoji.name, emoji.id
    return None


def _check_server(guild, action):
    if action["kind"] == SERVER_NAME:
        name = str(action.get("name") or "").strip()
        if not 2 <= len(name) <= 100:
            return "A server name is 2 to 100 characters."
        action["name"] = name
        return None
    if not action.get("image"):
        return "Attach the image to your message."
    return None


def _check_rule(action):
    current, kind = conduct.rules(), action["kind"]
    number = action.get("number")
    if kind in (RULE_EDIT, RULE_REMOVE):
        if not isinstance(number, int) or not 1 <= number <= len(current):
            return f"There are {len(current)} rules; pick one of those numbers."
        if kind == RULE_EDIT and number in conduct.FIXED:
            return f"Rule {number} is part of the safety floor and can't be changed by vote."
        if kind == RULE_REMOVE and number <= len(conduct.DEFAULT_RULES):
            return (f"The first {len(conduct.DEFAULT_RULES)} rules can't be removed, only "
                    "reworded (except 4 to 6).")
    if kind in (RULE_EDIT, RULE_ADD):
        title = str(action.get("title") or "").strip()
        body = str(action.get("body") or "").strip()
        if not title or not body or len(title) > 60 or len(body) > 500:
            return "A rule needs a short title (up to 60 characters) and its text (up to 500)."
        if kind == RULE_ADD and len(current) >= MAX_RULES:
            return f"There can be at most {MAX_RULES} rules."
        action["title"], action["body"] = title, body
    return None


def _check_watch(action):
    words = [str(w).strip().lower() for w in action.get("words") or [] if str(w).strip()]
    if not words:
        return "List the words."
    if any(len(w) > 60 for w in words):
        return "Each word or phrase can be at most 60 characters."
    community = automod.community_words()
    if action["kind"] == WATCH_ADD:
        if len(community["added"]) + len(words) > 1000:
            return "The watch list added by vote is full."
    else:
        known = (set(automod.ENGLISH) | set(automod.ARABIC) | set(automod.SECTARIAN)
                 | set(community["added"]))
        if any(w in set(automod.BLOCK_WORDS) for w in words):
            return "Blocked words are part of the safety floor and can't be removed."
        missing = [w for w in words if w not in known]
        if missing:
            return "These aren't on the watch lists: " + ", ".join(missing)
    action["words"] = words
    return None


def _check_event(guild, action):
    event = (guild.get_scheduled_event(action.get("event_id") or 0)
             or discord.utils.get(guild.scheduled_events, name=action.get("event")))
    if event is None:
        return "There's no upcoming event by that name."
    action["event_id"], action["event"] = event.id, event.name
    return None


async def _check_member(guild, action):
    target = member_id(action.get("member"))
    if target is None:
        return "Mention the member (@name) so there's no doubt who is meant."
    action["member"] = str(target)
    if target in (guild.owner_id, guild.me.id):
        return "That member can't be removed by the bot."
    if action["kind"] == UNBAN:
        try:
            ban = await guild.fetch_ban(discord.Object(target))
        except discord.NotFound:
            return "That member isn't banned."
        action["member_name"] = ban.user.name
        return None
    try:
        found = await guild.fetch_member(target)
    except discord.NotFound:
        return "That member isn't in the server."
    if found.top_role >= guild.me.top_role:
        return "That member's role is above the bot's, so it can't act on them."
    action["member_name"] = found.display_name
    if not str(action.get("reason") or "").strip():
        return "Say why: members vote on the reason."
    return None


# ---------- describing ----------

def describe(action):
    """(title, details) of the proposal for `action`."""
    kind, a = action["kind"], action
    lines = {
        CREATE: lambda: (f"Create the {'voice ' if a['channel_type'] == 'voice' else ''}channel "
                         f"{a['name']}", f"Create **{a['name']}** in {a['category']}."
                         + (f" Topic: {a['topic']}" if a.get("topic") else "")
                         + (f" Slowmode: {a['slowmode']} seconds." if a.get("slowmode") else "")),
        RENAME: lambda: (f"Rename {a['channel']} to {a['name']}",
                         f"Rename **{a['channel']}** to **{a['name']}**."),
        DELETE: lambda: (f"Delete {a['channel']}", f"Delete **{a['channel']}**. Its messages "
                         "are deleted with it and can't be restored."),
        TOPIC: lambda: (f"New topic for {a['channel']}",
                        f"Set the topic of **{a['channel']}** to: {a['topic']}"),
        SLOWMODE: lambda: (f"Slowmode of {a['slowmode']}s in {a['channel']}",
                           f"Set slowmode in **{a['channel']}** to {a['slowmode']} seconds."),
        PURGE: lambda: (f"Clear {a['channel']}'s history", f"Delete every message in "
                        f"**{a['channel']}**. The channel stays; its messages can't be restored."),
        ACCESS: lambda: ((f"Open {a['channel']} to everyone", f"Let everyone see **"
                          f"{a['channel']}** again.") if not a["roles"] else
                         (f"Make {a['channel']} opt-in", f"Only members with "
                          + " or ".join(f"**{r}**" for r in a["roles"])
                          + f" can see **{a['channel']}**. Anyone can join "
                          + ("that role" if len(a["roles"]) == 1 else "those roles")
                          + " in #roles or by asking the bot."
                          + (" New roles, made with it and giving no powers: "
                             + ", ".join(a["new_roles"]) + "." if a.get("new_roles") else ""))),
        CATEGORY_CREATE: lambda: (f"Create the category {a['name']}",
                                  f"Create a category called **{a['name']}**."),
        CATEGORY_RENAME: lambda: (f"Rename the category {a['category']}",
                                  f"Rename **{a['category']}** to **{a['name']}**."),
        CATEGORY_DELETE: lambda: (f"Delete the category {a['category']}",
                                  f"Delete the empty category **{a['category']}**."),
        ROLE_CREATE: lambda: (f"Create the role {a['name']}", f"Create the role **{a['name']}**"
                              + (f" in {a['color']}" if a.get("color") else "")
                              + ((f". Members take it in the **{a['picker']}** picker in "
                                  "#roles" + (", made with it" if a.get("new_picker") else "")
                                  + ", or by asking the bot, and anyone can ping it."
                                  if a.get("picker") else
                                  ". Members take it in #roles or by asking the bot, and "
                                  "anyone can ping it.") if a["joinable"] else ".")
                              + " Like every role here, it gives no powers."),
        ROLE_EDIT: lambda: (f"Change the role {a['role']}", f"Change **{a['role']}**: "
                            + ", ".join(f"{k} to {a[k]}" for k in ("name", "color", "joinable")
                                        if a.get(k) is not None) + "."),
        ROLE_DELETE: lambda: (f"Delete the role {a['role']}", f"Delete the role **{a['role']}**."),
        EMOJI_ADD: lambda: (f"Add the emoji :{a['name']}:",
                            f"Add the attached image as the emoji **:{a['name']}:**."),
        EMOJI_REMOVE: lambda: (f"Remove the emoji :{a['name']}:",
                               f"Remove the emoji **:{a['name']}:**."),
        SERVER_NAME: lambda: ("Rename the server", f"Rename the server to **{a['name']}**."),
        SERVER_ICON: lambda: ("New server icon", "Set the attached image as the server icon."),
        RULE_EDIT: lambda: (f"Reword rule {a['number']}", f"Change rule {a['number']} to: "
                            f"**{a['title']}.** {a['body']}"),
        RULE_ADD: lambda: (f"New rule: {a['title']}", f"Add a rule: **{a['title']}.** {a['body']}"),
        RULE_REMOVE: lambda: (f"Remove rule {a['number']}", f"Remove rule {a['number']}: "
                              f"{conduct.title(a['number'])}."),
        WATCH_ADD: lambda: ("Watch more words", "Have AutoMod pass these to the moderator: "
                            + ", ".join(f"`{w}`" for w in a["words"])),
        WATCH_REMOVE: lambda: ("Watch fewer words", "Stop AutoMod passing these to the "
                               "moderator: " + ", ".join(f"`{w}`" for w in a["words"])),
        EVENT_CANCEL: lambda: (f"Cancel the event {a['event']}",
                               f"Cancel the event **{a['event']}**."),
        KICK: lambda: (f"Kick {a['member_name']}", f"Remove <@{a['member']}> from the server. "
                       "They can come back with a new invite."),
        BAN: lambda: (f"Ban {a['member_name']}", f"Ban <@{a['member']}> from the server."),
        UNBAN: lambda: (f"Unban {a['member_name']}", f"Lift the ban on {a['member_name']}."),
        PICKER_CREATE: lambda: (f"Add a picker: {a['title']}", _picker_details(a)),
        PICKER_EDIT: lambda: (f"Change the picker {a['picker']}", _picker_details(a)),
        PICKER_DELETE: lambda: (f"Remove the picker {a['picker']}",
                                f"Remove the picker **{a['picker']}** from #roles. Its roles "
                                "stay, and so does whoever has them."),
        ONBOARDING_CHANNELS: lambda: ("Change the channels new members see", " ".join(
            filter(None, [
                ("New members also see " + ", ".join(f"#{c}" for c in a["add"]) + "."
                 if a["add"] else ""),
                ("They no longer see " + ", ".join(f"#{c}" for c in a["remove"])
                 + " at first; they can still find them in Browse Channels."
                 if a["remove"] else "")]))),
        ONBOARDING_QUESTION: lambda: ((f"Change the onboarding question {a['question']}"
                                       if a.get("question") else
                                       f"Ask new members: {a['title']}"), _question_details(a)),
        ONBOARDING_REMOVE: lambda: (f"Stop asking new members {a['question']}",
                                    f"Take the question **{a['question']}** out of "
                                    "onboarding. Whoever answered it keeps what it gave them."),
    }
    title, details = lines[kind]()
    if action.get("reason"):
        details += f"\n\n**Why.** {action['reason']}"
    if kind in ABOUT_A_MEMBER:
        details += ("\n\nA vote about a member: it hides its count until it closes, "
                    "they can't vote on it, and it needs a higher share to pass.")
    details += "\n\nIf this passes, the bot makes the change itself."
    return title[:100], details


def _picker_details(a):
    said = []
    if a["kind"] == PICKER_CREATE:
        said.append(f"Post a picker in #roles called **{a['title']}**.")
    else:
        said.append(f"Change the picker **{a['picker']}** in #roles"
                    + (f": call it **{a['title']}**." if a.get("title") else "."))
    if a.get("roles") is not None:
        said.append("It offers: " + ", ".join(a["roles"]) + ".")
    if a.get("new_roles"):
        said.append("New roles, made with it and giving no powers: "
                    + ", ".join(a["new_roles"]) + ".")
    if a.get("one") is not None:
        said.append("Members pick one." if a["one"] else "Members pick any that fit.")
    return " ".join(said)


def _question_details(a):
    said = [f"When they join, new members are asked **{a['title']}**"
            + (" and pick one:" if a["one"] else " and pick any:")]
    for option in a["options"]:
        gives = ([f"#{c}" for c in option["channels"]]
                 + [f"the role {r}" for r in option["roles"]])
        emoji = f"{option['emoji']} " if option["emoji"] else ""
        said.append(f"- {emoji}**{option['title']}**"
                    + (f" ({option['description']})" if option["description"] else "")
                    + ": " + ", ".join(gives))
    return "\n".join(said)[:1500]


# ---------- carrying out ----------

async def offer_opt_in(guild):
    """Bring the Opt-in roles picker in #roles up to date (pickers.py)."""
    await pickers.sync_opt_in(guild, [r for r, v in voted_roles().items() if v["joinable"]])


async def carry_out(guild, action):
    """Make the change. Returns a sentence saying what happened."""
    said = await _carry_out(guild, action)
    if action["kind"] in ROLE_KINDS + PICKER_KINDS + (ACCESS,):
        try:
            await offer_opt_in(guild)
        except discord.HTTPException as e:
            log.warning(f"the Opt-in roles picker wasn't updated: {e!r}")
    if action["kind"] in ROLE_KINDS + PICKER_KINDS + CHANNEL_KINDS + ONBOARDING_KINDS:
        problem = await onboarding.sync(guild)
        if problem and action["kind"] in ONBOARDING_KINDS and said.startswith("Done"):
            said += f" Discord doesn't show it yet: {problem}."
    return said


async def _carry_out(guild, action):
    problem = await check(guild, action)
    if problem:
        return f"It couldn't be done: {problem}"
    kind, a = action["kind"], action
    if kind == CREATE:
        category = discord.utils.get(guild.categories, name=a["category"])
        if a["channel_type"] == "voice":
            made = await guild.create_voice_channel(a["name"], category=category, reason=REASON)
        else:
            made = await guild.create_text_channel(
                a["name"], category=category, topic=a.get("topic") or None,
                slowmode_delay=a.get("slowmode") or 0, reason=REASON)
        return f"Done: {made.mention} is open."
    if kind == CATEGORY_CREATE:
        await guild.create_category(a["name"], reason=REASON)
        return f"Done: the category {a['name']} exists."
    if kind in (CATEGORY_RENAME, CATEGORY_DELETE):
        category = guild.get_channel(a["category_id"])
        if kind == CATEGORY_RENAME:
            await category.edit(name=a["name"], reason=REASON)
            return f"Done: the category is now {a['name']}."
        await category.delete(reason=REASON)
        return f"Done: the category {a['category']} is deleted."
    if kind == ACCESS:
        return await _carry_out_access(guild, a)
    if kind in (RENAME, DELETE, TOPIC, SLOWMODE, PURGE):
        return await _carry_out_channel(guild, a)
    if kind in ROLE_KINDS:
        return await _carry_out_role(guild, a)
    if kind == EMOJI_ADD:
        await guild.create_custom_emoji(name=a["name"], image=load_image(a["image"]),
                                        reason=REASON)
        return f"Done: :{a['name']}: is added."
    if kind == EMOJI_REMOVE:
        await guild.get_emoji(a["emoji_id"]).delete(reason=REASON)
        return f"Done: :{a['name']}: is removed."
    if kind == SERVER_NAME:
        await guild.edit(name=a["name"], reason=REASON)
        return f"Done: the server is now called {a['name']}."
    if kind == SERVER_ICON:
        await guild.edit(icon=load_image(a["image"]), reason=REASON)
        return "Done: the server has its new icon."
    if kind in RULE_KINDS:
        return await _carry_out_rule(guild, a)
    if kind in WATCH_KINDS:
        words = automod.community_words()
        if kind == WATCH_ADD:
            words["added"] = sorted(set(words["added"]) | set(a["words"]))
            words["removed"] = [w for w in words["removed"] if w not in a["words"]]
        else:
            words["added"] = [w for w in words["added"] if w not in a["words"]]
            words["removed"] = sorted(set(words["removed"]) | set(a["words"]))
        automod.save_community_words(words)
        await automod.install(guild, layout.channel(guild, "automod-alerts"))
        return "Done: AutoMod's watch list is updated."
    if kind == EVENT_CANCEL:
        await guild.get_scheduled_event(a["event_id"]).cancel(reason=REASON)
        return f"Done: {a['event']} is cancelled."
    if kind in PICKER_KINDS:
        return await _carry_out_picker(guild, a)
    if kind in ONBOARDING_KINDS:
        return _carry_out_onboarding(guild, a)
    return await _carry_out_member(guild, a)


async def _carry_out_channel(guild, a):
    target = guild.get_channel(a["channel_id"])
    kind = a["kind"]
    if kind == RENAME:
        await target.edit(name=a["name"], reason=REASON)
        return f"Done: renamed to {target.mention}."
    if kind == DELETE:
        name = target.name
        await target.delete(reason=REASON)
        layout.forget(guild, a["channel_id"])
        return f"Done: #{name} is deleted."
    if kind == TOPIC:
        await target.edit(topic=a["topic"], reason=REASON)
        return f"Done: {target.mention} has its new topic."
    if kind == SLOWMODE:
        await target.edit(slowmode_delay=a["slowmode"], reason=REASON)
        return f"Done: slowmode in {target.mention} is {a['slowmode']} seconds."
    deleted = await target.purge(limit=None, reason=REASON)
    return f"Done: {len(deleted)} messages deleted from {target.mention}."


async def _carry_out_access(guild, a):
    """Only the given roles see the channel, or everyone if none. Other
    overrides (the bot's, the Admin role's) are left alone; seeing a
    channel is not a power, so guard.py lets it be."""
    target = guild.get_channel(a["channel_id"])
    await _make_roles(guild, a.get("new_roles", []))
    voted = voted_roles()
    wanted = {discord.utils.get(guild.roles, name=name) for name in a["roles"]}
    overwrites = {t: o for t, o in target.overwrites.items()
                  if not (isinstance(t, discord.Role) and t.id in voted)}
    everyone = overwrites.get(guild.default_role, discord.PermissionOverwrite())
    everyone.update(view_channel=False if wanted else None)
    overwrites[guild.default_role] = everyone
    for role in wanted:
        overwrites[role] = discord.PermissionOverwrite(view_channel=True)
    await target.edit(overwrites=overwrites, reason=REASON)
    if not wanted:
        return f"Done: everyone can see {target.mention}."
    return (f"Done: only members with {', '.join(r.name for r in wanted)} can see "
            f"{target.mention}.")


async def _carry_out_role(guild, a):
    kind = a["kind"]
    if kind == ROLE_CREATE:
        role = await guild.create_role(
            name=a["name"], colour=_colour(a.get("color")) or discord.Colour.default(),
            permissions=discord.Permissions.none(), hoist=False,
            mentionable=a["joinable"], reason=REASON)
        _save_role(role.id, a["joinable"])
        if not a.get("picker"):
            return f"Done: the role {role.name} exists."
        picker = pickers.find(a["picker"]) or {"no": None, "message_id": None,
                                               "title": a["picker"], "roles": [],
                                               "one": bool(a.get("one", False))}
        picker["roles"] = picker["roles"] + [role.id]
        picker.pop("auto", None)
        await pickers.show(guild, pickers.save(picker))
        return f"Done: the role {role.name} exists, in the {picker['title']} picker in #roles."
    role = guild.get_role(a["role_id"])
    if kind == ROLE_DELETE:
        await role.delete(reason=REASON)
        _forget_role(role.id)
        await pickers.role_gone(guild, role.id)
        return f"Done: the role {a['role']} is deleted."
    changes = {}
    if a.get("name"):
        changes["name"] = a["name"]
    if a.get("color"):
        changes["colour"] = _colour(a["color"])
    if a.get("joinable") is not None:
        changes["mentionable"] = bool(a["joinable"])
        _save_role(role.id, bool(a["joinable"]))
    await role.edit(reason=REASON, **changes)
    return f"Done: the role {role.name} is updated."


async def _carry_out_picker(guild, a):
    if a["kind"] == PICKER_DELETE:
        picker = pickers.get(a["picker_no"])
        await pickers.hide(guild, picker)
        pickers.forget(picker["no"])
        return f"Done: the picker {a['picker']} is removed."
    await _make_roles(guild, a.get("new_roles", []))
    picker = (pickers.get(a["picker_no"]) if a["kind"] == PICKER_EDIT
              else {"no": None, "message_id": None})
    picker.pop("auto", None)  # changing one the bot kept makes it the members'
    if a.get("title"):
        picker["title"] = a["title"]
    if a.get("roles") is not None:
        picker["roles"] = [discord.utils.get(guild.roles, name=name).id for name in a["roles"]]
    if a.get("one") is not None:
        picker["one"] = a["one"]
    picker = pickers.save(picker)
    if not await pickers.show(guild, picker):
        return f"The picker {picker['title']} is saved, but there's no #roles to post it in."
    return f"Done: the picker {picker['title']} is in #roles."


def _carry_out_onboarding(guild, a):
    """Change what's stored; carry_out then writes the page."""
    data = onboarding.saved(guild)
    if a["kind"] == ONBOARDING_CHANNELS:
        data["channels"] = a["channel_ids"]
        onboarding.save(data)
        return "Done: new members see the new set of channels."
    at = next((i for i, q in enumerate(data["questions"])
               if q["title"] == a.get("question")), None)
    if a["kind"] == ONBOARDING_REMOVE:
        del data["questions"][at]
        onboarding.save(data)
        return f"Done: new members aren't asked {a['question']} any more."
    question = {"title": a["title"], "one": a["one"], "options": [
        {**option, "channels": [c.id for n in option["channels"]
                                if (c := _find_channel(guild, n))],
         "roles": [r.id for n in option["roles"]
                   if (r := discord.utils.get(guild.roles, name=n))]}
        for option in a["options"]]}
    if at is None:
        data["questions"].append(question)
    else:
        data["questions"][at] = question
    onboarding.save(data)
    return f"Done: new members are asked {a['title']}."


async def _carry_out_rule(guild, a):
    current = conduct.rules()
    if a["kind"] == RULE_EDIT:
        current[a["number"] - 1] = (a["title"], a["body"])
    elif a["kind"] == RULE_ADD:
        current.append((a["title"], a["body"]))
    else:
        del current[a["number"] - 1]
    conduct.save_rules(current)
    await layout.post_texts(guild)
    return "Done: #rules is updated."


async def _carry_out_member(guild, a):
    target = int(a["member"])
    if a["kind"] == UNBAN:
        await guild.unban(discord.Object(target), reason=REASON)
        return f"Done: {a['member_name']} is unbanned."
    member = await guild.fetch_member(target)
    try:
        who = "An admin of" if a.get("by_admin") else "A community vote in"
        await member.send(f"{who} {guild.name} decided to "
                          f"{'ban' if a['kind'] == BAN else 'remove'} you. "
                          f"The reason given: {a.get('reason', '')}")
    except discord.HTTPException:
        pass
    if a["kind"] == BAN:
        await guild.ban(member, reason=REASON, delete_message_seconds=0)
        return f"Done: {a['member_name']} is banned."
    await guild.kick(member, reason=REASON)
    return f"Done: {a['member_name']} is removed from the server."


class ServerChange(kinds.Kind):
    """A proposal to make one of the changes above."""

    def open(self, author_id, action, now):
        """Open a vote on `action`, already checked. A vote about a member
        (ABOUT_A_MEMBER) hides its count, they can't vote on it, and it
        needs `removal_percent` to pass."""
        title, details = describe(action)
        if action["kind"] in ABOUT_A_MEMBER:
            return proposals.file(author_id, proposals.ACTION, title, details, now,
                                  excluded=[int(action["member"])], blind=True,
                                  bar="removal_percent", action=action)
        return proposals.file(author_id, proposals.ACTION, title, details, now,
                              action=action)

    def open_draft(self, author_id, draft, now):
        return self.open(author_id, draft["payload"], now)

    async def carry_out(self, client, guild, p):
        if guild is None:
            return "It couldn't be done: the bot can't see the server."
        try:
            said = await carry_out(guild, {**p["action"],
                                           "by_admin": bool(p.get("shipped_by"))})
        except (discord.HTTPException, OSError) as e:
            said = f"It couldn't be done: {getattr(e, 'status', '') or e.__class__.__name__}."
        log.info(f"proposal {p['no']}: {said}")
        await layout.server_log(guild, f"Proposal {p['no']} ({p['title']}): {said}")
        return said


KIND = kinds.register(proposals.ACTION, ServerChange())
