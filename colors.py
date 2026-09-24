"""Name colors members pick for themselves, in #roles or with /color.

A color role only changes how a name looks. It carries no permissions,
sits at the bottom of the role list, and a member holds at most one, so a
color gives nobody more say than anyone else. The list is code: changing
it is a proposal like any other.

A dropdown can only show text and an emoji, so each color gets a dot of
its exact color as an emoji. They are the bot's own (application) emojis,
drawn here, and use none of the server's emoji slots.
"""

import logging
import re
import struct
import time
import zlib

import discord
from discord import app_commands

import store

log = logging.getLogger("colors")

# (name, color, what it looks like). The names alone don't say which color
# is which, so every place a color is offered says it plainly too.
COLORS = [
    ("Cedar", 0x2E7D32, "dark green"),
    ("Tabbouleh", 0x7CB342, "light green"),
    ("Za'atar", 0x8A9A5B, "olive"),
    ("Qadisha", 0x26A69A, "teal"),
    ("Mediterranean", 0x1E88E5, "blue"),
    ("Faraya Sky", 0x4FC3F7, "light blue"),
    ("Gemmayzeh Night", 0x7E57C2, "purple"),
    ("Jounieh Sunset", 0xF4845F, "coral"),
    ("Knefeh", 0xE9A23B, "orange"),
    ("Batroun Lemon", 0xF2C94C, "yellow"),
    ("Byblos Sand", 0xC8A27A, "sand beige"),
    ("Pomegranate", 0xC62828, "red"),
    ("Beirut Pink", 0xEC407A, "pink"),
    ("Baalbek Stone", 0x9E9E9E, "grey"),
]
NONE = "No color"
PICKER_TEXT = ("**Pick a name color.** Colors are only for looks: they give no "
               "powers, and you can change yours whenever you like, here or with "
               "`/color`.")
COOLDOWN = 10  # seconds between changes, per member

_last_change = {}
_client = None  # set by setup(); uploading emojis needs it
SWATCH = "swatch_"
DOT = 64  # pixels


def dot_png(value, size=DOT):
    """A PNG of a round dot in the color `value`, on a transparent ground."""
    rgb = value.to_bytes(3, "big")
    r = size / 2
    rows = b"".join(
        b"\0" + b"".join(rgb + (b"\xff" if (x + .5 - r) ** 2 + (y + .5 - r) ** 2 <= r * r
                                 else b"\0") for x in range(size))
        for y in range(size))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def swatch_name(name, value):
    """The emoji's name. It carries the color, so a changed color gets a
    new dot."""
    return f"{SWATCH}{re.sub(r'[^a-z0-9]', '', name.lower())}_{value:06x}"


async def _swatches():
    """{color name: emoji} for every color, uploading missing dots and
    deleting ones no color uses. Empty if the emojis can't be managed."""
    if _client is None:
        return {}
    try:
        have = {e.name: e for e in await _client.fetch_application_emojis()}
        values = {n: v for n, v, _ in COLORS}
        wanted = {swatch_name(n, v): n for n, v in values.items()}
        for stale in [e for name, e in have.items()
                      if name.startswith(SWATCH) and name not in wanted]:
            await stale.delete()
        found = {}
        for emoji_name, color in wanted.items():
            emoji = have.get(emoji_name) or await _client.create_application_emoji(
                name=emoji_name, image=dot_png(values[color]))
            found[color] = emoji
        return found
    except discord.HTTPException as e:
        log.warning(f"no color dots in the picker: {e!r}")
        return {}


def _saved():
    return store.load("colors", {"roles": {}, "message": None})


def picker_text(role_ids):
    """The #roles message: the colors as role mentions, which Discord draws
    in each role's own color, so members see what they're picking."""
    shown = [f"<@&{role_ids[name]}> {look}" for name, _, look in COLORS
             if role_ids.get(name)]
    return PICKER_TEXT + ("\n\n" + "\n".join(shown) if shown else "")


def changes(held, chosen, color_ids):
    """(add, remove) role ids to go from the roles `held` to wearing only the
    color `chosen` (a role id, or None for no color)."""
    remove = [r for r in held if r in color_ids and r != chosen]
    add = [chosen] if chosen is not None and chosen not in held else []
    return add, remove


async def install(guild, roles_channel):
    """Create or update the color roles and the picker in #roles."""
    saved = _saved()
    wanted = {name for name, _, _ in COLORS}
    for name, value, _ in COLORS:
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
    picker = Picker(await _swatches())
    message = None
    if saved["message"]:
        try:
            message = await roles_channel.fetch_message(saved["message"])
        except discord.NotFound:
            message = None
    text = picker_text(saved["roles"])
    quiet = discord.AllowedMentions.none()
    if message is None:
        message = await roles_channel.send(text, view=picker, allowed_mentions=quiet)
        saved["message"] = message.id
        store.save("colors", saved)
    else:
        await message.edit(content=text, view=picker, allowed_mentions=quiet)


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
    """The dropdown in #roles. Persistent: it keeps working across restarts.
    `dots` is {color name: emoji}; the view registered at startup only
    needs to answer, so it has none."""

    def __init__(self, dots=None):
        super().__init__(timeout=None)
        dots = dots or {}
        select = discord.ui.Select(
            custom_id="color-picker", placeholder="Choose a name color",
            options=[discord.SelectOption(label=name, value=name, description=look.capitalize(),
                                          emoji=dots.get(name))
                     for name, _, look in COLORS]
            + [discord.SelectOption(label=NONE, value=NONE)])
        select.callback = self.picked
        self.add_item(select)

    async def picked(self, interaction):
        name = interaction.data["values"][0]
        await interaction.response.send_message(await wear(interaction.user, name),
                                                ephemeral=True)


@app_commands.command(name="color", description="Pick your name color")
@app_commands.choices(color=[app_commands.Choice(name=f"{n} ({look})", value=n)
                             for n, _, look in COLORS]
                      + [app_commands.Choice(name=NONE, value=NONE)])
async def color(interaction: discord.Interaction, color: app_commands.Choice[str]):
    await interaction.response.send_message(await wear(interaction.user, color.value),
                                            ephemeral=True)


def setup(client, tree):
    global _client
    _client = client
    client.add_view(Picker())
    tree.add_command(color)
