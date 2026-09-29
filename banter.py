"""The banter check: is a proposal a real request, or banter?

Members mostly ask the chat model for their proposals, and it drafts
whatever it is asked, turning "ban hadi for being bald lol" into a proper
proposal. So before a member's draft is saved, one question goes to the
same first check the moderator uses (Jev), which sees what the member
actually wrote as well as the draft. It gives a probability, and the draft
is turned away only when that is at least `banter_percent`: when it is
unsure, the proposal goes to a vote, since a joke that gets through only
fails its vote but a real idea turned away is never heard.

The question is the same for everyone, and #welcome quotes it. Setting
changes are never checked, so members can always vote to loosen it, and
admins' drafts aren't either. No Discord and no network here.
"""

QUESTION = "Is this banter rather than a real request to change the server or the bot?"
TRUE = ("It is a joke, trolling, teasing or insulting someone, nonsense, or something "
        "the member clearly doesn't mean.")
FALSE = ("It is a change the member actually wants, even if it is silly, small or "
         "unlikely to pass.")


def questions():
    return {"banter": {"type": "noul", "instructions": QUESTION,
                       "criteria": {"true": TRUE, "false": FALSE}}}


def state(asked, title, details):
    """What the check reads. `asked` is what the member wrote to the chat
    model, oldest first, or None when they wrote the proposal themself."""
    draft = f"Title: {title}\n{details}"
    if asked is None:
        return f"A proposal a member wrote for the server to vote on:\n{draft}"
    shown = "\n".join(asked) if asked else "(nothing)"
    return (f"What the member wrote to the bot, oldest first:\n{shown}\n\n"
            f"The proposal the bot drafted from it:\n{draft}")


def score(answers):
    """How likely the check thinks it is banter, 0 to 1. A missing answer
    counts as 0, so the proposal goes through."""
    return float((answers.get("banter") or {}).get("noul") or 0.0)


def turned_away(score, s):
    return score * 100 >= s["banter_percent"]


def refusal(score, s):
    """What the member is told."""
    return (f"The banter check turned this away: it is {score:.0%} sure this is banter "
            f"rather than a real request (it turns away {s['banter_percent']}% or more). "
            "If you mean it, say plainly what should change and why.")
