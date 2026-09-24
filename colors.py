"""Name colors members pick for themselves, in #roles or with /color.

A color role only changes how a name looks. It carries no permissions,
sits at the bottom of the role list, and a member holds at most one, so a
color gives nobody more say than anyone else. The list is code: changing
it is a proposal like any other.
"""

import time

import discord
from discord import app_commands

import store

COLORS = [
    ("Cedar", 0x2E7D32),
    ("Tabbouleh", 0x7CB342),
    ("Za'atar", 0x8A9A5B),
    ("Qadisha", 0x26A69A),
    ("Mediterranean", 0x1E88E5),
    ("Faraya Sky", 0x4FC3F7),
    ("Gemmayzeh Night", 0x7E57C2),
    ("Jounieh Sunset", 0xF4845F),
    ("Knefeh", 0xE9A23B),
    ("Batroun Lemon", 0xF2C94C),
    ("Byblos Sand", 0xC8A27A),
    ("Pomegranate", 0xC62828),
    ("Beirut Pink", 0xEC407A),
    ("Baalbek Stone", 0x9E9E9E),
]
NONE = "No color"
PICKER_TEXT = ("**Pick a name color.** Colors are only for looks: they give no "
               "powers, and you can change yours whenever you like, here or with "
               "`/color`.")
COOLDOWN = 10  # seconds between changes, per member

_last_change = {}


def _saved():
    return store.load("colors", {"roles": {}, "message": None})


def changes(held, chosen, color_ids):
    """(add, remove) role ids to go from the roles `held` to wearing only the
    color `chosen` (a role id, or None for no color)."""
    remove = [r for r in held if r in color_ids and r != chosen]
    add = [chosen] if chosen is not None and chosen not in held else []
    return add, remove


async def install(guild, roles_channel):
    """Create or update the color roles and the picker in #roles."""
    saved = _saved()
    wanted = dict(COLORS)
    for name, value in COLORS:
        role = guild.get_role(saved["roles"].get(name) or 0)
        if role is None:
            role = await guild.create_role(
                name=name, colour=discord.Colour(value),
                permissions=discord.Permissions.none(), hoist=False, mentionable=False,
                reason="Name color")
        elif role.colour.value != value:
            await role.edit(colour=discord.Colour(value), reason="Name color")
        saved["roles"][name] = role.id
    for name in [n for n in saved["roles"] if n not in wanted]:
        role = guild.get_role(saved["roles"].pop(name))
        if role is not None:
            await role.delete(reason="No longer one of the name colors")
    store.save("colors", saved)

    if roles_channel is None:
        return
    message = None
    if saved["message"]:
        try:
            message = await roles_channel.fetch_message(saved["message"])
        except discord.NotFound:
            message = None
    if message is None:
        message = await roles_channel.send(PICKER_TEXT, view=Picker())
        saved["message"] = message.id
        store.save("colors", saved)
    else:
        await message.edit(content=PICKER_TEXT, view=Picker())


async def wear(member, name):
    """Give `member` the color `name` (or NONE) and take off any other.
    Returns what to tell them."""
    now = time.time()
    if now - _last_change.get(member.id, 0) < COOLDOWN:
        return "You just changed your color. Try again in a few seconds."
    ids = _saved()["roles"]
    chosen = ids.get(name) if name != NONE else None
    if name != NONE and chosen is None:
        return "That color isn't available."
    add, remove = changes([r.id for r in member.roles], chosen, set(ids.values()))
    if remove:
        await member.remove_roles(*[discord.Object(r) for r in remove], reason="Name color")
    if add:
        await member.add_roles(*[discord.Object(r) for r in add], reason="Name color")
    _last_change[member.id] = now
    return "Your color is removed." if chosen is None else f"You're now **{name}**."


class Picker(discord.ui.View):
    """The dropdown in #roles. Persistent: it keeps working across restarts."""

    def __init__(self):
        super().__init__(timeout=None)
        select = discord.ui.Select(
            custom_id="color-picker", placeholder="Choose a name color",
            options=[discord.SelectOption(label=name, value=name) for name, _ in COLORS]
            + [discord.SelectOption(label=NONE, value=NONE)])
        select.callback = self.picked
        self.add_item(select)

    async def picked(self, interaction):
        name = interaction.data["values"][0]
        await interaction.response.send_message(await wear(interaction.user, name),
                                                ephemeral=True)


@app_commands.command(name="color", description="Pick your name color")
@app_commands.choices(color=[app_commands.Choice(name=n, value=n) for n, _ in COLORS]
                      + [app_commands.Choice(name=NONE, value=NONE)])
async def color(interaction: discord.Interaction, color: app_commands.Choice[str]):
    await interaction.response.send_message(await wear(interaction.user, color.value),
                                            ephemeral=True)


def setup(client, tree):
    client.add_view(Picker())
    tree.add_command(color)
