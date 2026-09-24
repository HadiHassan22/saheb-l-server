"""Every moderation action, numbered, and each member's recent record."""

import store

DAY = 24 * 60 * 60

WARN = "warn"
TIMEOUT = "timeout"
BAN = "ban"

ACTIVE = "active"
OVERTURNED = "overturned"


def _load():
    return store.load("cases", {"next_no": 1, "cases": {}})


def _save(data):
    store.save("cases", data)


def get(no):
    return _load()["cases"].get(str(no))


def record_of(user_id, now, days):
    """How many warnings and timeouts this member has had in the last
    `days` days, not counting overturned ones."""
    since = now - days * DAY
    counts = {WARN: 0, TIMEOUT: 0}
    for case in _load()["cases"].values():
        if (case["user_id"] == user_id and case["status"] == ACTIVE
                and case["at"] >= since and case["action"] in counts):
            counts[case["action"]] += 1
    return {"warnings": counts[WARN], "timeouts": counts[TIMEOUT]}


def last_action_at(user_id):
    times = [c["at"] for c in _load()["cases"].values() if c["user_id"] == user_id]
    return max(times, default=None)


def open_case(now, **fields):
    """Record an action and return the case with its number. `fields`:
    user_id, action, minutes, deleted, rule, severity, explanation, scores,
    record, channel_id, message_id."""
    data = _load()
    no = data["next_no"]
    case = dict(fields, no=no, at=now, status=ACTIVE, log_message_id=None)
    data["next_no"] = no + 1
    data["cases"][str(no)] = case
    _save(data)
    return case


def update(no, **fields):
    data = _load()
    data["cases"][str(no)].update(fields)
    _save(data)
    return data["cases"][str(no)]


def label(case):
    """"Warning", "Timeout (60 minutes)", "Ban"."""
    if case["action"] == TIMEOUT:
        minutes = case["minutes"]
        length = (f"{minutes // 60} hours" if minutes >= 120 and minutes % 60 == 0
                  else f"{minutes} minutes")
        return f"Timeout ({length})"
    return {WARN: "Warning", BAN: "Ban"}[case["action"]]


def why_not_appealable(case):
    """None if `case` can be appealed, else why not. Each case can be
    appealed once, and only while it stands."""
    if case is None:
        return "There is no case with that number."
    if case["status"] != ACTIVE:
        return f"Case {case['no']} has already been overturned."
    if case.get("appeal"):
        return (f"Case {case['no']} has already been appealed "
                f"(proposal {case['appeal']}).")
    return None


def appeal_record():
    """(overturned, decided): how many appeals the community has decided,
    and how many of those overturned the moderator."""
    decided = [c for c in _load()["cases"].values() if c.get("appeal_result")]
    overturned = sum(c["appeal_result"] == "overturned" for c in decided)
    return overturned, len(decided)
