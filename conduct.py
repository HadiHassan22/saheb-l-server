"""The server's rules of conduct and the welcome text, as posted in
#rules and #welcome. The moderator judges messages against RULES.
"""

import settings

RULES = [
    ("No harassment",
     "Don't insult, demean or pile on another member. Teasing between "
     "friends is fine; if someone asks you to stop, stop."),
    ("No hate",
     "No slurs or attacks on anyone's religion, sect, ethnicity, nationality, "
     "gender or sexuality. Arguing about politics and religion is allowed; "
     "attacking people for who they are is not."),
    ("No threats",
     "No threats of violence or harm, including veiled ones."),
    ("No doxxing",
     "Never post someone's private information: phone number, address, "
     "workplace, photos, or real identity without their consent."),
    ("No sexual content",
     "Nothing sexually explicit, and never anything sexual involving minors."),
    ("No spam or scams",
     "No flooding, mass mentions, unsolicited ads or phishing links."),
    ("Swearing is allowed",
     "Swearing on its own is fine. Aiming it at someone to hurt them is not."),
    ("Follow Discord's rules",
     "Discord's Terms of Service and Community Guidelines apply here too."),
]


def rules_text():
    lines = ["# Rules", ""]
    for n, (title, body) in enumerate(RULES, 1):
        lines.append(f"**{n}. {title}.** {body}")
    lines += ["", "These rules can be changed by a community vote. See "
              "`/propose`."]
    return "\n".join(lines)


def welcome_text(owner_mention, mod_log_mention):
    s = settings.current()
    return f"""# How this server works

This server is an experiment: it is moderated and governed entirely by Saheb l Server, an AI bot. There are no human moderators, and no member has more say than any other.

**The owner.** Discord requires a human owner, so {owner_mention} holds that role. It is purely technical: the owner keeps the bot online and pays for its AI, and does not moderate, make rules, or overrule votes. On this server the owner is just another member with one vote.

**Moderation.** The bot doesn't read every message. Discord's AutoMod passes it messages with flagged words in English or Arabic, and it reads the conversation around each one and decides whether to do nothing, warn, delete the message, time the member out, or ban them for severe or repeated violations. Every action is posted in {mod_log_mention} with the reasoning.

**Appeals.** Think the bot got it wrong? Use `/appeal` with the case number, or the Appeal button in its message to you. The community votes, and can overturn any action.

**Community votes.** Anyone can make a proposal with `/propose`, and change one of the bot's settings with `/propose-setting` (see them with `/settings`).
- Voting stays open for {s['voting_hours']} hours.
- A proposal needs at least {s['quorum']} votes to count, and more than {s['pass_percent']}% yes to pass.
- Members who have been here for {s['voter_min_days']} days can vote.

**The bot rewrites itself.** When a proposal passes, the bot writes the code change, checks it automatically, and deploys it. Every change is public on GitHub.

**What votes can't change.** The bot's access keys, the system that updates and rolls back its code, the range each setting can take, the safety floor (blocking scams, phone numbers and sexual content involving minors, and the self-harm support line), and anything Discord's Terms of Service require.

**Fair warning.** The bot will make mistakes, a vote might break something, and it might go offline. If so, we roll back to a working version and keep going."""
