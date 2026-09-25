"""Pickers in #roles: a dropdown where members give themselves roles, such
as where they're from, their age group or what they play.

A picker is data, not code: a title, the roles it offers, and whether a
member picks one of them or several. It is made, changed and removed like
any server change (actions.py), by a vote or at once by an admin, and one
piece of code here answers every picker, so a new one needs no code
change. Picking only adds and removes that picker's roles, which are made
by vote and carry no powers. The name colors have their own picker
(colors.py).

Every role members can join that no other picker offers is still offered
in #roles, in pickers the bot keeps itself (`sync_opt_in`), so a role made
opt-in, like one that opens a channel, can always be taken. The bot groups
them the way a person would: Male and Female go in a Gender picker where
members pick one, and roles that fit no group go in "Opt-in roles". The AI
suggests the groups and code checks them; without the AI, new roles go in
Opt-in roles and the groups already made stay. An admin or a vote can take
one of these pickers over by changing it (actions.py).

Discord's onboarding asks new members the same questions (onboarding.py).
"""

import logging

import discord

import ai
import layout
import providers
import store

log = logging.getLogger("pickers")

MAX_PICKERS = 10
MAX_ROLES = 24  # a dropdown holds 25 options, and one is "None of these"
MAX_GROUPS = 5  # pickers the bot makes itself, besides Opt-in roles
NONE = "none"
OPT_IN = "Opt-in roles"


def _saved():
    return store.load("pickers", {"next": 1, "pickers": {}})


def all_pickers():
    return list(_saved()["pickers"].values())


def get(no):
    return _saved()["pickers"].get(str(no))


def find(title):
    """The picker called `title`, ignoring case, or None."""
    title = str(title or "").strip().lower()
    return next((p for p in all_pickers() if p["title"].lower() == title), None)


def save(picker):
    """Keep `picker`, numbering it if it is new, and return it."""
    data = _saved()
    if not picker.get("no"):
        picker["no"] = data["next"]
        data["next"] += 1
    data["pickers"][str(picker["no"])] = picker
    store.save("pickers", data)
    return picker


def forget(no):
    data = _saved()
    data["pickers"].pop(str(no), None)
    store.save("pickers", data)


def holding(role_id):
    """The pickers that offer `role_id`."""
    return [p for p in all_pickers() if role_id in p["roles"]]


def changes(held, chosen, picker):
    """(add, remove) role ids to go from the roles `held` to holding exactly
    the roles `chosen` from this picker. Roles outside it are untouched."""
    offered = set(picker["roles"])
    chosen = [r for r in chosen if r in offered][:1 if picker["one"] else None]
    remove = [r for r in held if r in offered and r not in chosen]
    add = [r for r in chosen if r not in held]
    return add, remove


def text(picker):
    how = "Pick one." if picker["one"] else "Pick any that fit."
    if picker.get("auto") and picker["title"].startswith(OPT_IN):
        how = "Pick any you want. Some open a channel that only their holders see."
    return f"**{picker['title']}**\n{how}"[:2000]


def made_by_members():
    """The pickers made by vote or an admin, not the ones the bot keeps."""
    return [p for p in all_pickers() if not p.get("auto")]


GROUPING_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "one": {"type": "boolean"},
                       "roles": {"type": "array", "items": {"type": "integer"}}},
        "required": ["title", "one", "roles"]}}},
    "required": ["groups"],
}


def grouping_prompt(names, taken, before):
    """What the AI is asked. `names` are the roles to group, numbered from
    1; `taken`, titles already used by other pickers; `before`, the groups
    as they were, as (title, one, names)."""
    listed = "\n".join(f"{n}. {name}" for n, name in enumerate(names, 1))
    kept = "".join(f"\n- {title} ({'pick one' if one else 'pick any'}): {', '.join(roles)}"
                   for title, one, roles in before)
    return f"""A Discord server has a #roles channel where members give themselves roles from dropdowns ("pickers"). These roles are in no picker yet:
{listed}

Group roles that are the same kind of thing under a short title a member would expect, like Gender, Age, Pronouns, Where you're from or Interests. Set "one" to true when a member should hold only one role of the group because the choices exclude each other (Male and Female, age groups); false when a member may hold several (hobbies, games, notifications). A group needs at least two roles. Leave out any role that fits no group; it goes in a general "{OPT_IN}" picker. Don't use these titles: {", ".join([OPT_IN, *taken])}.
{("Keep these groups where the roles still fit, so members aren't surprised:" + kept) if kept else ""}
Answer with the groups, each listing its roles by number."""


def _groups(answer, count, taken):
    """The AI's groups, checked: [(title, one, [indexes])], each role in at
    most one group, two to MAX_ROLES roles each, titles fresh and short."""
    groups, used = [], set()
    taken = {t.lower() for t in [*taken, OPT_IN]}
    for group in (answer or {}).get("groups") or []:
        title = str(group.get("title") or "").strip()[:45]
        picked = [n - 1 for n in dict.fromkeys(group.get("roles") or [])
                  if isinstance(n, int) and 1 <= n <= count and n - 1 not in used]
        if not title or title.lower() in taken or not 2 <= len(picked) <= MAX_ROLES:
            continue
        groups.append((title, bool(group.get("one")), picked))
        used.update(picked)
        taken.add(title.lower())
        if len(groups) == MAX_GROUPS:
            break
    return groups


async def _grouped(guild, wanted):
    """[(title, one, [role ids])] for the roles in `wanted`, the ones in no
    group last under Opt-in roles. The groups are remembered for this set
    of roles, so the AI is only asked again when it changes."""
    saved = store.load("groups", {"roles": [], "groups": []})
    taken = [p["title"] for p in made_by_members()]
    before = [(g["title"], g["one"], [r for r in g["roles"] if r in wanted])
              for g in saved["groups"]]
    before = [g for g in before if len(g[2]) >= 2
              and g[0].lower() not in {t.lower() for t in taken}]
    if sorted(saved["roles"]) != sorted(wanted) and len(wanted) >= 2:
        names = [guild.get_role(r).name for r in wanted]
        hint = [(t, one, [guild.get_role(r).name for r in roles]) for t, one, roles in before]
        try:
            answer = await ai.review(grouping_prompt(names, taken, hint), GROUPING_SCHEMA)
            before = [(t, one, [wanted[i] for i in picked])
                      for t, one, picked in _groups(answer, len(wanted), taken)]
            store.save("groups", {"roles": wanted, "groups": [
                {"title": t, "one": one, "roles": roles} for t, one, roles in before]})
        except ai.Unavailable as e:
            log.info(f"the opt-in roles weren't grouped: {e}")
        except (providers.ProviderError, ValueError, TypeError, AttributeError) as e:
            # Not remembered either way, so the next change asks again.
            log.warning(f"the opt-in roles weren't grouped: {e!r}")
    grouped = {r for _, _, roles in before for r in roles}
    rest = [r for r in wanted if r not in grouped]
    chunks = [rest[i:i + MAX_ROLES] for i in range(0, len(rest), MAX_ROLES)]
    return before + [(OPT_IN if i == 0 else f"{OPT_IN} ({i + 1})", False, chunk)
                     for i, chunk in enumerate(chunks)]


async def sync_opt_in(guild, joinable):
    """Offer every role in `joinable` (ids of roles members can join) that
    no other picker offers, in the pickers the bot keeps: groups of roles
    that go together, then Opt-in roles, split in two or more past what a
    dropdown holds. A picker appears when its first role does and goes
    when its last one does."""
    offered = {r for p in made_by_members() for r in p["roles"]}
    wanted = sorted((r for r in joinable if r not in offered and guild.get_role(r)),
                    key=lambda r: guild.get_role(r).name.lower())
    groups = await _grouped(guild, wanted)
    kept = sorted((p for p in all_pickers() if p.get("auto")), key=lambda p: p["no"])
    # The same title keeps the same message in #roles; others are reused in turn.
    by_title = {p["title"]: p for p in kept}
    spare = [p for p in kept if p["title"] not in {title for title, _, _ in groups}]
    for title, one, roles in groups:
        picker = by_title.get(title) or (spare.pop(0) if spare else
                                         {"no": None, "message_id": None, "auto": True})
        if (picker.get("roles"), picker.get("title"), picker.get("one")) != (roles, title, one):
            picker.update(title=title, roles=roles, one=one)
            await show(guild, save(picker))
    for extra in spare:
        await hide(guild, extra)
        forget(extra["no"])


class PickerSelect(discord.ui.DynamicItem[discord.ui.Select],
                   template=r"picker:(?P<no>\d+)"):
    """The dropdown of one picker. Its number is in its id, so every picker
    keeps working across restarts without registering each one."""

    def __init__(self, no, options=(), one=True):
        options = list(options) or [discord.SelectOption(label="None of these", value=NONE)]
        super().__init__(discord.ui.Select(
            custom_id=f"picker:{no}", placeholder="Choose" if one else "Choose any",
            min_values=1, max_values=1 if one else len(options), options=options))
        self.no = no

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["no"]), item.options, item.max_values == 1)

    async def callback(self, interaction):
        picker = get(self.no)
        if picker is None:
            return await interaction.response.send_message(
                "This picker has been removed.", ephemeral=True)
        values = interaction.data.get("values", [])
        chosen = [] if NONE in values else [int(v) for v in values if v.isdigit()]
        member = interaction.user
        add, remove = changes([r.id for r in member.roles], chosen, picker)
        try:
            if remove:
                await member.remove_roles(*[discord.Object(r) for r in remove],
                                          reason=f"Picked in {picker['title']}")
            if add:
                await member.add_roles(*[discord.Object(r) for r in add],
                                       reason=f"Picked in {picker['title']}")
        except discord.HTTPException:
            return await interaction.response.send_message(
                "That didn't work. Try again in a moment.", ephemeral=True)
        now = [r for r in picker["roles"] if r in chosen]
        names = [role.name for r in now if (role := interaction.guild.get_role(r))]
        said = (f"You now have: {', '.join(names)}." if names
                else f"You have none of the {picker['title']} roles now.")
        await interaction.response.send_message(said[:2000], ephemeral=True)


def view(guild, picker):
    """The dropdown for `picker`, listing the roles that still exist."""
    options = [discord.SelectOption(label=role.name[:100], value=str(role.id))
               for r in picker["roles"] if (role := guild.get_role(r))]
    options.append(discord.SelectOption(label="None of these", value=NONE))
    item = PickerSelect(picker["no"], options, picker["one"])
    shown = discord.ui.View(timeout=None)
    shown.add_item(item)
    return shown


async def show(guild, picker):
    """Post `picker` in #roles, or update it where it is. Returns False if
    there is no #roles to post it in."""
    channel = layout.channel(guild, "roles")
    if channel is None:
        return False
    message = None
    if picker.get("message_id"):
        try:
            message = await channel.fetch_message(picker["message_id"])
        except discord.NotFound:
            message = None
    if message is None:
        message = await channel.send(text(picker), view=view(guild, picker),
                                     allowed_mentions=discord.AllowedMentions.none())
        picker["message_id"] = message.id
        save(picker)
    else:
        await message.edit(content=text(picker), view=view(guild, picker))
    return True


async def hide(guild, picker):
    channel = layout.channel(guild, "roles")
    if channel is None or not picker.get("message_id"):
        return
    try:
        message = await channel.fetch_message(picker["message_id"])
        await message.delete()
    except discord.NotFound:
        pass


async def role_gone(guild, role_id):
    """A role was deleted: take it out of every picker that offered it."""
    for picker in holding(role_id):
        picker["roles"] = [r for r in picker["roles"] if r != role_id]
        save(picker)
        try:
            await show(guild, picker)
        except discord.HTTPException as e:
            log.warning(f"picker {picker['no']} wasn't updated: {e!r}")


async def install(guild):
    """Put back any picker whose message is gone, and bring the rest up to
    date. Runs when the bot starts."""
    for picker in all_pickers():
        try:
            await show(guild, picker)
        except discord.HTTPException as e:
            log.warning(f"picker {picker['no']} wasn't shown: {e!r}")


def setup(client):
    client.add_dynamic_items(PickerSelect)
