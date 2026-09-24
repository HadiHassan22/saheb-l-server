"""The numbers the bot runs by. Each one can only be changed by a passed vote.

The bounds are fixed in code and are not themselves votable. They stop a
single vote from making every later vote meaningless, for example by
setting the quorum to one person, or from switching moderation off.
"""

import store

VOTING = "Voting"
MODERATION = "Moderation"

SETTINGS = {
    "voting_hours": {
        "default": 24, "min": 1, "max": 168, "group": VOTING,
        "label": "Voting window",
        "describe": "{} hours",
    },
    "quorum": {
        "default": 5, "min": 3, "max": 100, "group": VOTING,
        "label": "Votes needed to count",
        "describe": "at least {} votes",
    },
    "pass_percent": {
        "default": 50, "min": 50, "max": 90, "group": VOTING,
        "label": "Yes votes needed to pass",
        "describe": "more than {}% of votes cast",
    },
    "voter_min_days": {
        "default": 7, "min": 0, "max": 90, "group": VOTING,
        "label": "Time in the server before you can vote",
        "describe": "{} days",
    },
    "max_open_per_member": {
        "default": 3, "min": 1, "max": 20, "group": VOTING,
        "label": "Open proposals per member",
        "describe": "{} at a time",
    },
    "warning_days": {
        "default": 30, "min": 7, "max": 180, "group": MODERATION,
        "label": "How long a warning or timeout counts against you",
        "describe": "{} days",
    },
    "warnings_before_timeout": {
        "default": 3, "min": 1, "max": 10, "group": MODERATION,
        "label": "Warnings before a timeout",
        "describe": "{} warnings",
    },
    "first_timeout_minutes": {
        "default": 60, "min": 10, "max": 1440, "group": MODERATION,
        "label": "Length of a first timeout",
        "describe": "{} minutes",
    },
    "repeat_timeout_hours": {
        "default": 24, "min": 1, "max": 168, "group": MODERATION,
        "label": "Length of each later timeout",
        "describe": "{} hours",
    },
    "timeouts_before_ban": {
        "default": 2, "min": 1, "max": 10, "group": MODERATION,
        "label": "Timeouts before a ban, except for severe violations",
        "describe": "{} timeouts",
    },
    # The two strictness dials. Every flagged message gets a fast first
    # check. At or above `act_percent` its verdict stands; between the two,
    # a second model reviews it; below `review_percent` it is cleared.
    # Lower is stricter for both.
    "act_percent": {
        "default": 80, "min": 50, "max": 99, "group": MODERATION,
        "label": "How sure the first check must be to act on its own",
        "describe": "{}%",
    },
    "review_percent": {
        "default": 30, "min": 10, "max": 90, "group": MODERATION,
        "label": "How likely a flagged message must look to get a second look",
        "describe": "{}%",
    },
}


def current():
    """Every setting's value: whatever a vote set it to, else its default."""
    saved = store.load("settings", {})
    return {name: saved.get(name, spec["default"]) for name, spec in SETTINGS.items()}


def check(name, value):
    """None if `value` is allowed for setting `name`, else why not."""
    spec = SETTINGS.get(name)
    if spec is None:
        return f"there is no setting called {name}"
    if not spec["min"] <= value <= spec["max"]:
        return f"{spec['label']} must be between {spec['min']} and {spec['max']}"
    return None


def apply(name, value):
    """Called only when a vote to change `name` passes."""
    problem = check(name, value)
    if problem:
        raise ValueError(problem)
    saved = store.load("settings", {})
    saved[name] = value
    store.save("settings", saved)


def describe(name, value):
    return SETTINGS[name]["describe"].format(value)
