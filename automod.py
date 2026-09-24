"""The AutoMod rules the bot installs, and the words they watch for.

AutoMod is the net and the bot is the judge. The "watch" rules only alert
the bot, so a message is never removed for containing a word: most of what
they catch is friends joking or swearing at the traffic, and the judge
clears those for a fraction of a cent. That is why the lists can be broad.
Only scams and posted phone numbers are blocked outright, because a
scam link that waits for a verdict has already been clicked.

Discord's limits, checked in tests: a keyword is at most 60 characters and
a rule holds at most 1000 of them; a regex is at most 260 characters and a
rule holds at most 10. Keywords match whole words unless wrapped in `*`.
Arabic prefixes (ال، و، ب) attach to the word, so distinctive Arabic stems
are wrapped; short or common ones are not, because `*نيك*` also matches
"تكنيك".
"""

import logging

import discord

log = logging.getLogger("automod")

PREFIX = "Saheb l Server: "

ENGLISH = [
    "idiot", "moron", "retard", "retarded", "stupid", "dumbass", "dumb",
    "loser", "worthless", "pathetic", "trash", "garbage", "scum", "clown",
    "bitch", "b1tch", "whore", "slut", "cunt", "twat", "dick", "prick",
    "asshole", "bastard", "motherfucker", "fuck you", "fuck off", "fuck u",
    "stfu", "shut up", "shut the fuck up", "ugly", "fat", "freak",
    "kys", "kill yourself", "kill urself", "go die", "hope you die",
    "neck yourself", "nobody likes you", "no one likes you",
    "everyone hates you", "nobody wants you", "no one wants you",
    "kill you", "i'll kill you", "ill kill you", "gonna kill you",
    "i'll find you", "i will find you", "where you live", "your address",
    "i know where", "watch your back", "you're dead", "ur dead",
    "dox", "doxx", "*doxxed*", "terrorist", "go back to", "your kind",
    "you people", "nazi", "jihadi", "infidel", "kafir", "kuffar",
    "nudes", "send nudes", "porn", "*onlyfans*",
]

ARABIC = [
    "*شرموط*", "*منيوك*", "*منايك*", "منيك", "متناك", "*عرص*", "كس",
    "كسمك", "كس امك", "كس اختك", "*كسختك*", "طيز", "طيزك", "زب", "زبي",
    "*زبر*", "اير", "ايري", "ايرك", "نيك", "ينيك", "نيكك", "انيك", "بنيك",
    "*نياك*", "*قحب*", "*عاهر*", "خول", "خولات", "لوطي", "*لواط*", "شاذ",
    "*شواذ*", "حمار", "حمارة", "كلب", "كلبة", "حيوان", "جحش", "خرا",
    "خرية", "وسخ", "*حقير*", "*تافه*", "زبالة", "حثالة", "يلعن",
    "يلعن دينك", "يلعن ربك", "يلعن امك", "رافضي", "*روافض*", "*نواصب*",
    "ناصبي", "مجوس", "*مجوسي*", "صليبي", "*صليبيين*", "كافر", "كفار",
    "داعشي", "*دواعش*", "بقتلك", "رح اقتلك", "*اقتلك*", "بدبحك", "*ادبحك*",
    "بدفنك", "بعرف وين ساكن", "بعرف وين بتسكن", "انتحر", "موت يا",
]

# Arabic written in Latin letters, with digits for the letters Latin lacks
# (3 = ع, 7 = ح, 2 = ء, 5 = خ). Spelling varies too much for word lists,
# so these are patterns. (?i) makes each one case-insensitive.
ARABIZI = [
    r"(?i)shar+m(o|ou|u)+t+(a|e)?h?",
    r"(?i)\b(m?[ae]?n[ae]?y+[ae]?k|mnay+ek|nay+ek|n[iy]+k+(ak|ik|ek|o)?)\b",
    r"(?i)\b(kos|k[ou]?s+|kess|kiss)\s*(e?m+[ae]k|o?mak|e?okht(ak|ek|ik)|ekhtak|e5tak)\b",
    r"(?i)\b(kos|ayre?|ayri|ayreh|zeb+|zob+|tiz+|teez|3[ae]?rs|a3ras|m3aras)\b",
    r"(?i)\b(5ara|khara|kalb|kelb|7mar|7mara|7ayawan|7ayawen|jahesh|ja7esh|habal|ahbal|zbele|zbeleh|wa?sa5)\b",
    r"(?i)\b(5[ae]wal|khawal|louti|looti|shaz|rafid[iy]?|rawafed|nawaseb|nasib[iy]|majous|salib[iy]|kafer|3abeed|abeed|dawa3esh|da3eshi)\b",
    r"(?i)(2?e?2tl|2t[ou]?l|a2tl)(ak|ek|ik|kon)\b|\bb?ed?b[ae]7(ak|ek|kon)\b|\bb?e?dfn(ak|ek)\b|ba3ref\s*wen\s*(saken|sakne|btskon)",
    r"(?i)\by[ie]?l?3an\s*(deen|din|rab+|allah|emm|omm)",
]

# Blocked outright, then still judged. Scam lures and Lebanese phone
# numbers, the most common kind of doxxing here.
BLOCK_WORDS = [
    "free nitro", "nitro for free", "claim your nitro", "*dlscord*",
    "*disc0rd*", "*discorcl*", "*dicsord*", "*steamcommunlty*",
    "*steamcomunity*", "*nitro-gift*",
]
BLOCK_PATTERNS = [
    r"(\+|00)961[\s.-]?0?(3|7[016890]|81)[\s.-]?\d{3}[\s.-]?\d{3}",
    # Local numbers only in the "03 123456" / "71-123456" shape: a looser
    # pattern also blocks prices like "70 000 000 LL".
    r"\b(03|70|71|76|78|79|81)[\s/-]\d{6}\b",
]
BLOCK_MESSAGE = ("Blocked: this looked like a scam or someone's phone "
                 "number. It has been passed to the moderator.")


def plan():
    """(name, trigger, block) for every rule the bot keeps. Names are how
    the bot recognises its own rules again on the next start."""
    T = discord.AutoModRuleTriggerType
    return [
        (PREFIX + "watch English",
         discord.AutoModTrigger(type=T.keyword, keyword_filter=ENGLISH), False),
        (PREFIX + "watch Arabic",
         discord.AutoModTrigger(type=T.keyword, keyword_filter=ARABIC), False),
        (PREFIX + "watch Arabizi",
         discord.AutoModTrigger(type=T.keyword, regex_patterns=ARABIZI), False),
        (PREFIX + "block scams and phone numbers",
         discord.AutoModTrigger(type=T.keyword, keyword_filter=BLOCK_WORDS,
                                regex_patterns=BLOCK_PATTERNS), True),
        (PREFIX + "block slurs and sexual content",
         discord.AutoModTrigger(type=T.keyword_preset,
                                presets=discord.AutoModPresets(
                                    slurs=True, sexual_content=True)), True),
        (PREFIX + "block mass mentions",
         discord.AutoModTrigger(type=T.mention_spam, mention_limit=6,
                                mention_raid_protection=True), True),
        (PREFIX + "block spam",
         discord.AutoModTrigger(type=T.spam), True),
    ]


def _actions(alert_channel, block):
    actions = [discord.AutoModRuleAction(channel_id=alert_channel.id)]
    if block:
        actions.insert(0, discord.AutoModRuleAction(
            type=discord.AutoModRuleActionType.block_message,
            custom_message=BLOCK_MESSAGE))
    return actions


async def install(guild, alert_channel):
    """Create the bot's rules, or bring existing ones back in line with the
    plan. Rules someone else made are left alone."""
    existing = {r.name: r for r in await guild.fetch_automod_rules()}
    for name, trigger, block in plan():
        kwargs = dict(
            trigger=trigger,
            actions=_actions(alert_channel, block),
            enabled=True,
            reason="Saheb l Server keeps its AutoMod rules in line with its code",
        )
        # The spam trigger takes no trigger metadata on edit.
        if trigger.type == discord.AutoModRuleTriggerType.spam:
            kwargs.pop("trigger")
        try:
            if name in existing:
                await existing[name].edit(**kwargs)
            else:
                kwargs["trigger"] = trigger
                await guild.create_automod_rule(
                    name=name, event_type=discord.AutoModRuleEventType.message_send,
                    **kwargs)
        except discord.HTTPException as e:
            log.error(f"AutoMod rule {name!r} could not be installed: {e!r}")
