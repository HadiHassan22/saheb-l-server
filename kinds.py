"""What makes one kind of proposal different from another.

Every proposal is voted on, counted and ended the same way (proposals.py,
ending.py). What differs is how it is opened, what Yes and No mean on its
card, and what the bot does once it has passed or failed. Each kind keeps
all of that in its own module, which registers it here:

- general proposals, written as a code change (code_changes.py);
- setting changes (setting_changes.py);
- server changes (actions.py);
- appeals of a moderation case (appeals.py).

A new kind is one new module, imported in bot.py so it is registered
before any proposal of its kind is shown or ended.
"""

import proposals

KINDS = {}


class Kind:
    """The defaults are a plain yes-or-no vote that does nothing when it
    passes. A kind overrides what it needs."""

    choices = {"yes": "yes", "no": "no"}  # what Yes and No mean on its card
    footer = ""  # added to its card's footer while it is put to a vote
    shipped_footer = "The bot carries it out at once, and says so here."

    def open_draft(self, author_id, draft, now):
        """Open a proposal from a draft the bot wrote in #ask-saheb
        (assistant.py), and return it."""
        raise proposals.Refused("This can't be filed from #ask-saheb.")

    async def carry_out(self, client, guild, p):
        """Do what `p` says, now that it has passed by vote or an admin.
        Returns a sentence for members saying what came of it, or None.
        `guild` is the home server, or None if the bot can't see it."""
        return None

    async def not_passed(self, client, guild, p):
        """`p` failed, didn't get enough votes, or was withdrawn. Returns a
        sentence for members, or None."""
        return None


def register(name, kind):
    KINDS[name] = kind
    return kind


def of(p):
    """The kind of proposal `p` (or of draft `p`)."""
    return KINDS[p["kind"]]
