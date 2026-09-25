"""Proposals from opening to close, the same for every kind of proposal
(kinds.py). No Discord here: voting_ui.py and ending.py do that.

Every time is epoch seconds and is passed in, so the whole lifecycle can be
tested without a clock or a server.

A proposal locks in the rules at the moment it opens. Changing the quorum
while a vote is running would change what that vote needs mid-count.

Ballots are secret. Who voted which way is kept only while the vote is
open, so each person can change their vote, and is deleted at close,
leaving the totals.

A new server has nobody who has been in it long enough to vote. So
everyone who joins in the bot's first week in the server (the founding
week) can vote at once, and keeps that right; after it, newcomers wait
the usual time. A small server can't reach the quorum either, so the
quorum a proposal opens with is at most half the server's members, and
never below the lowest quorum the setting allows.
"""

import settings
import store

# The kinds of proposal, each defined in its own module (kinds.py).
GENERAL = "general"  # code_changes.py
SETTING = "setting"  # setting_changes.py
APPEAL = "appeal"  # appeals.py
ACTION = "action"  # a server change, actions.py

OPEN = "open"
PASSED = "passed"
FAILED = "failed"
NO_QUORUM = "no_quorum"
WITHDRAWN = "withdrawn"  # taken down by an admin before the vote ended

DAY = 24 * 60 * 60
FOUNDING = 7 * DAY  # from when the bot joined the server


class Refused(Exception):
    """Something a member tried that the rules don't allow. The message is
    shown to them as is."""


def _load():
    return store.load("proposals", {"next_no": 1, "proposals": {}})


def _save(data):
    store.save("proposals", data)


def get(no):
    return _load()["proposals"].get(str(no))


def all_proposals():
    return list(_load()["proposals"].values())


def _check_limit(data, current, author_id):
    mine = [p for p in data["proposals"].values()
            if p["author_id"] == author_id and p["status"] == OPEN]
    if len(mine) >= current["max_open_per_member"]:
        raise Refused(
            f"You already have {len(mine)} proposals open, which is the limit. "
            "Wait for one to close first."
        )


def file(author_id, kind, title, details, now, excluded=(), blind=False,
         bar="pass_percent", **fields):
    """Open a proposal of `kind` (kinds.py) and return it, with its number
    and the voting rules it locks in. The kind has already checked it.
    `excluded`: members who can't vote on it. `blind`: its count stays
    hidden until it closes. `bar`: the setting it needs to pass, above
    that share of Yes. Anything else in `fields` is kept on it for its
    kind."""
    current = settings.current()
    data = _load()
    _check_limit(data, current, author_id)
    no = data["next_no"]
    proposal = {
        **fields,
        "kind": kind,
        "title": title,
        "details": details,
        "no": no,
        "author_id": author_id,
        "opened_at": now,
        "closes_at": now + current["voting_hours"] * 60 * 60,
        "quorum": current["quorum"],
        "pass_percent": current[bar],
        "voter_min_days": current["voter_min_days"],
        "status": OPEN,
        "votes": {},
        "excluded": list(excluded),
        "channel_id": None,
        "message_id": None,
    }
    if blind:
        proposal["blind"] = True
    data["next_no"] = no + 1
    data["proposals"][str(no)] = proposal
    _save(data)
    return proposal


def pass_now(no, admin_id, now):
    """Pass a just-opened proposal on an admin's word, without a vote
    (admins.py), and return it. Carrying it out is ending.py's job, and
    checking that `admin_id` is an admin is the caller's."""
    data = _load()
    proposal = data["proposals"][str(no)]
    if proposal["status"] != OPEN:
        raise Refused("Voting on this proposal has closed.")
    proposal.update(status=PASSED, shipped_by=admin_id, closes_at=now, closed_at=now,
                    totals={"yes": 0, "no": 0}, votes={})
    _save(data)
    return proposal


def withdraw(no, admin_id, reason, now):
    """Take an open proposal down on an admin's word, and return it. Its
    ballots are destroyed as at close, and nothing is carried out."""
    data = _load()
    proposal = data["proposals"].get(str(no))
    if proposal is None:
        raise Refused("That proposal doesn't exist.")
    if proposal["status"] != OPEN:
        raise Refused("Only an open proposal can be withdrawn.")
    yes, against = tally(proposal)
    proposal.update(status=WITHDRAWN, withdrawn_by=admin_id, note=reason.strip() or None,
                    totals={"yes": yes, "no": against}, closed_at=now, votes={})
    _save(data)
    return proposal


def quorum_for(quorum, members):
    """The quorum for a server of `members` people: the setting, or half
    the members rounded up if that's fewer, never below the setting's
    floor. `members` is None if unknown."""
    if members is None:
        return quorum
    floor = settings.SETTINGS["quorum"]["min"]
    return max(floor, min(quorum, -(-members // 2)))


def fit_quorum(no, members):
    """Scale a just-opened proposal's quorum to the server's size, and
    return the proposal."""
    data = _load()
    proposal = data["proposals"][str(no)]
    if proposal["status"] == OPEN:
        proposal["quorum"] = quorum_for(proposal["quorum"], members)
        _save(data)
    return proposal


def attach_message(no, channel_id, message_id):
    return record(no, channel_id=channel_id, message_id=message_id)


def record(no, **fields):
    """Keep `fields` on proposal `no`, and return it."""
    data = _load()
    proposal = data["proposals"][str(no)]
    proposal.update(fields)
    _save(data)
    return proposal


def founder(joined_at, founded_at):
    """True if the member joined during the founding week. `founded_at` is
    when the bot joined the server, or None if unknown."""
    return (joined_at is not None and founded_at is not None
            and joined_at < founded_at + FOUNDING)


def cast(no, voter_id, joined_at, choice, now, founded_at=None):
    """Record or change a vote and return the proposal. `joined_at` is when
    the voter joined the server and `founded_at` when the bot did, either
    None if unknown."""
    if choice not in ("yes", "no"):
        raise ValueError(choice)
    data = _load()
    proposal = data["proposals"].get(str(no))
    if proposal is None:
        raise Refused("That proposal doesn't exist.")
    if proposal["status"] != OPEN or now >= proposal["closes_at"]:
        raise Refused("Voting on this proposal has closed.")
    if voter_id in proposal.get("excluded", []):
        raise Refused("Nobody votes on their own case.")
    min_days = proposal["voter_min_days"]
    if not founder(joined_at, founded_at) and (
            joined_at is None or now - joined_at < min_days * DAY):
        raise Refused(f"You can vote once you've been in the server for "
                      f"{min_days} days.")
    proposal["votes"][str(voter_id)] = choice
    _save(data)
    return proposal


def tally(proposal):
    """(yes, no). Open proposals count their ballots; closed ones keep only
    the totals."""
    if proposal["status"] == OPEN:
        votes = list(proposal["votes"].values())
        return votes.count("yes"), votes.count("no")
    return proposal["totals"]["yes"], proposal["totals"]["no"]


def outcome(yes, no, quorum, pass_percent):
    if yes + no < quorum:
        return NO_QUORUM
    if yes * 100 > pass_percent * (yes + no):
        return PASSED
    return FAILED


def due(now):
    """Open proposals whose voting window has ended."""
    return [p for p in _load()["proposals"].values()
            if p["status"] == OPEN and now >= p["closes_at"]]


def close(no, now):
    """Count the votes, destroy the ballots, and return the closed proposal.
    Carrying out the result is ending.py's job."""
    data = _load()
    proposal = data["proposals"][str(no)]
    if proposal["status"] != OPEN:
        return proposal
    yes, against = tally(proposal)
    proposal.update(
        status=outcome(yes, against, proposal["quorum"], proposal["pass_percent"]),
        totals={"yes": yes, "no": against},
        closed_at=now,
        votes={},
    )
    _save(data)
    return proposal

