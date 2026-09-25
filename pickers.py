"""Pickers in #roles: a dropdown where members give themselves roles, such
as where they're from, their age group or what they play.

A picker is data, not code: a title, the roles it offers, and whether a
member picks one of them or several. It is made, changed and removed like
any server change (actions.py), by a vote or at once by an admin, and one
piece of code here answers every picker, so a new one needs no code
change. Picking only adds and removes that picker's roles, which are made
by vote and carry no powers. The name colors have their own picker
(colors.py).

Every role members can join that no other picker offers is offered in
"Opt-in roles", a picker the bot keeps itself (`sync_opt_in`): a role made
opt-in, like one that opens a channel, can always be taken in #roles.
"""

import logging

import discord

import layout
import store

log = logging.getLogger("pickers")

MAX_PICKERS = 10
MAX_ROLES = 24  # a dropdown holds 25 options, and one is "None of these"
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
    if picker.get("auto"):
        how = "Pick any you want. Some open a channel that only their holders see."
    return f"**{picker['title']}**\n{how}"[:2000]


def made_by_members():
    """The pickers made by vote or an admin, not the ones the bot keeps."""
    return [p for p in all_pickers() if not p.get("auto")]


async def sync_opt_in(guild, joinable):
    """Offer every role in `joinable` (ids of roles members can join) that
    no other picker offers in the Opt-in roles picker, split in two or more
    if there are more than a dropdown holds. It appears when the first such
    role does and goes when the last one does."""
    offered = {r for p in made_by_members() for r in p["roles"]}
    wanted = sorted((r for r in joinable if r not in offered and guild.get_role(r)),
                    key=lambda r: guild.get_role(r).name.lower())
    chunks = [wanted[i:i + MAX_ROLES] for i in range(0, len(wanted), MAX_ROLES)]
    kept = sorted((p for p in all_pickers() if p.get("auto")), key=lambda p: p["no"])
    for i, chunk in enumerate(chunks):
        title = OPT_IN if i == 0 else f"{OPT_IN} ({i + 1})"
        picker = kept[i] if i < len(kept) else {"no": None, "message_id": None,
                                                "auto": True, "one": False}
        if picker.get("roles") != chunk or picker.get("title") != title:
            picker.update(title=title, roles=chunk)
            await show(guild, save(picker))
    for extra in kept[len(chunks):]:
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
