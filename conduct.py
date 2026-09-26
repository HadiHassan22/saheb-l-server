"""The server's rules of conduct and the texts posted in #rules, #welcome
and #guide. The moderator judges messages against `rules()`.

The guide in #guide is the friendly tutorial for members: what to ask the
bot, what it does at once, and what takes a vote. It is written in the
bot's own warm voice, with a little Lebanese Arabic where it fits.

The rules start as DEFAULT_RULES and change by vote (actions.py). Two
limits hold whatever a vote says: rules 4 to 6 (doxxing, sexual content,
scams) are the safety floor and can't be edited, and none of the original
rules can be removed, because the moderator's questions refer to them by
number. Added rules can be edited and removed.
"""

import settings
import store

FIXED = {4, 5, 6}

DEFAULT_RULES = [
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


def rules():
    """The rules in force, as [(title, body)], numbered from 1."""
    saved = store.load("rules", None)
    return [tuple(rule) for rule in saved] if saved else list(DEFAULT_RULES)


def save_rules(new):
    store.save("rules", [list(rule) for rule in new])


def title(n):
    """Rule `n`'s title, even for a rule removed since a case cited it."""
    current = rules()
    return current[n - 1][0] if 1 <= n <= len(current) else f"Rule {n} (since removed)"


def rules_text():
    """(title, text) for #rules."""
    lines = [f"**{n}. {title}.** {body}" for n, (title, body) in enumerate(rules(), 1)]
    lines += ["", "These rules can be changed by a community vote. See `/propose`."]
    return "Rules", "\n".join(lines)


def welcome_text(owner_mention, mod_log_mention, ask_mention):
    """(title, text) for #welcome."""
    s = settings.current()
    return "How this server works", f"""This server is an experiment: it is moderated and governed entirely by Saheb l Server, an AI bot. There are no human moderators, and apart from the admins below, no member has more say than any other.

**The owner.** Discord requires a human owner, so {owner_mention} holds that role. The owner keeps the bot online, pays for its AI and picks admins, and has the same powers as an admin (below). Otherwise the owner is a member with one vote like everyone else.

**Admins.** Members the owner or another admin picks (they have the Admin role; see `/admin list`) look after the server while it's young. They can do anything a vote can, at once and without a vote: they ask the bot and it's done, whether that's channels, roles, settings or the rules, kicking or banning, overturning a moderation case, or having the bot's code changed. The Admin role is the only role with Discord's own powers, so they can also act directly. Everything they do, through the bot or directly, is posted in #server-log with who did it. They also read #admin-log, where the bot reports how code changes are going, with links to the code.

**Moderation.** The bot doesn't read every message. Discord's AutoMod passes it messages with flagged words in English or Arabic, and it reads the conversation around each one and decides whether to do nothing, warn, delete the message, time the member out, or ban them for severe or repeated violations. Every action is posted in {mod_log_mention} with the reasoning.

**Talk to the bot.** Ask Saheb l Server anything in {ask_mention}, in English, Arabic or Arabizi. Tag it or reply to one of its messages; it doesn't answer anything else.
- For you, right away: your name color, joining a role, your nickname, an invite link.
- For everyone, right away: scheduling an event, a temporary voice channel, a thread, a pin. These are posted in #server-log with who asked.
- Anything else that affects everyone (channels, roles, pickers in #roles, the questions new members are asked, emojis and stickers, the rules, removing a member) it drafts as a proposal, and you file it with a button. Once a vote passes, the bot does it.

**Appeals.** Think the bot got it wrong? Use `/appeal` with the case number, or the Appeal button in its message to you. The community votes, and can overturn any action.

**Community votes.** Anyone can make a proposal with `/propose`, and change one of the bot's settings with `/propose-setting` (see them with `/settings`).
- Voting stays open for {s['voting_hours']} hours.
- A proposal needs at least {s['quorum']} votes to count (or half the server's members, if that's fewer, but never under 3), and more than {s['pass_percent']}% yes to pass.
- Members who have been here for {s['voter_min_days']} days can vote. Everyone who joined in the server's first week can vote right away.

**Votes are carried out automatically.** A passed change to the server, like a new channel, is made by the bot at once. Anything else is written as a code change, checked automatically and deployed, and what changed is posted under its proposal.

**What votes can't change.** Roles here are only cosmetic (a role can open a channel to whoever holds it, but gives no power over anyone), and nobody but the admins holds power over anyone. Nor can votes change who the admins are, the bot's access keys, the system that updates and rolls back its code, the range each setting can take, the safety floor (blocking scams, phone numbers and sexual content involving minors, and the self-harm support line), and anything Discord's Terms of Service require.

**Fair warning.** The bot will make mistakes, a vote might break something, and it might go offline. If so, we roll back to a working version and keep going."""


def tutorial_text(ask_mention, proposals_mention):
    """(title, text) for #guide: how members use the bot, in its own
    words, pointing at the places they need."""
    return "How to use Saheb l Server", f"""Ahla! This is the guide to using me, Saheb l Server. There are no commands to memorize: just talk to me. Write in English, Arabic or Arabizi, whatever is easier.

**Just talk to me in {ask_mention}.** Tag me or reply to one of my messages, and ask me anything. Say hi and have a little chat, or ask about the server: the channels, the roles, what events are coming up, the rules, open proposals, a moderation case, how this place works for new members. You get a plain answer.

**Things I do for you right away, just ask.** Your name color, joining or leaving a role, your nickname, or an invite link to bring a friend in. It's done the moment you ask, and you can undo it yourself.

**Small shared things I do in public, with your name on them.** Schedule an event (times are Beirut time), cancel an event you made, open a temporary voice channel, start a thread, pin or unpin a message. These happen right away and are posted in #server-log with who asked.

**Anything that changes the server for everyone goes to a vote.** Tell me what you want and I'll draft it for you. You file it with the button under my reply, or write one yourself with /propose, and members vote on the card in {proposals_mention} with Yes and No. That covers channels and categories, roles, the pickers in #roles, the questions new members are asked, emojis and stickers, the server's name or icon, the rules, AutoMod watch words, cancelling someone else's event, settings, and kicking, banning or unbanning a member. Anything else is a general proposal: if it passes and it needs new code, I write it into my own code, it's checked, and it goes live.

**No human moderators here.** The members govern this server by voting, and I carry out what you decide. Think a moderation call was wrong? Use /appeal with the case number, or the Appeal button in my message to you, and the community votes on it.

**The limits, so nobody is surprised.** Roles here are only cosmetic: a color for your name, or a channel you can see, never power over anyone. Only the admins have powers, and they answer to the owner (see #welcome). And whatever you ask me for yourself: I never change the server for everyone or act on another member without a vote. That's what keeps everyone equal here.

New here? #welcome explains how the server works, and #rules is what the moderator enforces. Yalla, come say hi in {ask_mention}."""
