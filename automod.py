"""The AutoMod rules the bot installs, and the words they watch for.

AutoMod is the net and the bot is the judge. The "watch" rules only alert
the bot, so a message is never removed for containing a word: most of what
they catch is friends joking or swearing at the traffic, and the judge
clears those for a fraction of a cent. That is why the lists can be broad.
Only scams and posted phone numbers are blocked outright, because a
scam link that waits for a verdict has already been clicked.

Discord's limits, checked in tests: a keyword is at most 60 characters and
a rule holds at most 1000 of them; a regex is at most 260 characters and a
rule holds at most 10. A server holds at most 6 keyword rules, and the bot
can already use all 6, so new words join an existing rule rather than
starting one: a rule takes keywords and patterns together. Discord's
patterns are Rust regexes: no lookarounds. Keywords match whole words unless wrapped in `*`.
Arabic prefixes (ال، و، ب) attach to the word, so distinctive Arabic stems
are wrapped; short or common ones are not, because `*نيك*` also matches
"تكنيك".

SECTARIAN is narrower still: sect and community slurs, inflammatory
political slogans and religious insults, the flashpoints of Lebanese talk.
Ordinary political vocabulary (party names, politicians, beliefs) is left
out on purpose. Those words mean nothing inside #politics-and-religion,
where that talk belongs, and outside it the message is classified before
anything happens to it (judge.py).
"""

import logging
import re

import discord

import store

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
    # The n-word and its spellings. Discord's slur preset blocks the common
    # ones; these catch the rest, and ENGLISH_PATTERNS the spaced-out ones.
    "nigger", "niggers", "nigga", "niggas", "niggaz", "niggah", "nigguh",
    "nigg3r", "n1gger", "n1gga", "n1gg3r", "n1ggas", "nigg@", "niqqa", "niqqer",
    "niqqas", "nibba", "nibbas", "nibber", "niga", "nigah", "negroes",
]

# Spellings keywords can't list: letters spaced or dotted out ("n i g g a").
# Two g's, so Niger and Nigeria are left alone.
ENGLISH_PATTERNS = [
    r"(?i)\bn+[\W_]*[i1!|y]+[\W_]*[gq9]+[\W_]*[gq9]+[\W_]*(a+h?|[e3]+[\W_]*r+|uh|az)[\W_]*s?\b",
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
    # More Lebanese swearing: the forms of اير, زب and كس the stems above
    # miss, and the insults they leave out.
    "أير", "أيري", "أيرك", "ايرو", "ايره", "ايرها", "ايرى", "زبك", "زبه",
    "زبو", "زبها", "كسك", "كسه", "كسو", "كسها", "كسم", "كسامك", "كس أمك",
    "كس اخت", "*منتاك*", "منيكة", "نيكو", "نيكها", "نيكني", "بنيكك", "بنيكها",
    "انيكك", "طيزي", "طيزه", "طيزو", "طيزها", "خراء", "كول خرا", "كل خرا",
    "*شراميط*", "*قحاب*", "*ديوث*", "قواد", "واطي", "ابن الحرام", "ابن حرام",
    "ابن الكلب", "ابن كلب", "تفو",
    # The n-word in Arabic letters.
    "نيجا", "نيغا", "نيقا", "نيغر", "نيقر",
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
    r"(?i)\by[ie]?l?3an\s*(deen|din|rab+|allah|emm|omm|ab[ou]+[ky]?|[eo]?kht|e?5t|3ard|sharaf|ebn|ibn)",
    # اير and زبر with their endings: ayre, ayri, ayrak, eyre, zabre,
    # zebrak, zobr. Not zebra, error or air.
    r"(?i)\b(a+y+r+|e+y+r+|za+b+r+|ze+b+r+|zo+b+r+|zi+b+r+|zb+r+)(e+|i+|o+|ou|eh|a+k|e+k|i+k|kon|ha|na)?\b",
]

# Lebanese swearing in Latin letters that is easier to list than to
# pattern: joined-up and variant spellings. Watched with ARABIZI.
ARABIZI_WORDS = [
    # اير and زب
    "ayre", "ayri", "ayrak", "ayrik", "ayrek", "ayro", "ayreh", "ayree",
    "ayre fik", "ayri fik", "ayre feek", "ayri feek", "ayre bi", "ayri bi",
    "zabre", "zabri", "zabrak", "zebre", "zebri", "zebrak", "zbre", "zobr",
    "zobre", "zabbre", "zebbre", "zebbe", "zebbak", "zebbi", "zibbi",
    "zibbak", "zubb", "zob", "zeb", "zebi", "zebak",
    # كس
    "kess", "kos", "koss", "kessemmak", "kesemmak", "kesemak", "kesmak",
    "kessmak", "kosomak", "kosommak", "kossomak", "kosomk", "ksomak", "ksmk",
    "kesekhtak", "kese5tak", "koskhtak", "kes emmak", "kos emmak", "kes emak",
    "kos omak", "kes ommak", "kes ekhtak", "kes e5tak", "kes 5altak",
    # نيك and منيوك
    "nayek", "naykak", "nayki", "naykek", "nekak", "nektak", "neekak", "nikak",
    "nikik", "niktak", "bnikak", "bnekak", "benekak", "nayekak", "mnayak",
    "mnayek", "mnayik", "mnayke", "mnaykeen", "manyak", "manyok", "manyouk",
    "manyouke", "manayek", "metnak", "metnake", "mitnak", "mitnek", "mntak",
    # شرموطة and قحبة
    "sharmouta", "sharmoota", "sharmuta", "sharmout", "sharmoot", "shrmota",
    "charmouta", "charmoota", "charmuta", "sharameet", "a7be", "a7ba", "2a7be",
    "2a7ba", "ka7be", "ka7ba", "qa7ba", "qa7be", "kahbe", "kahba", "qahba",
    # عرص, طيز and خرا
    "3arse", "3arsa", "3arseh", "3rse", "3arss", "m3arras", "m3arrase", "teez", "teezak", "tizak", "tizzak", "tizik", "teezik", "tizi",
    "teezi", "khara", "kharyan", "5aryan", "kharya", "5arye", "kol khara",
    "kol 5ara", "ekol khara", "akol 5ara", "kel khara", "kel 5ara",
    # حمار, جحش, حيوان, حقير, واطي, ديوث, ابن الحرام
    "hmar", "himar", "7imar", "hmara", "jahsh", "ja7sh", "je7sh", "hayawan",
    "hayawen", "7aywan", "haywan", "7aywen", "7a2ir", "ha2ir", "7a2eer",
    "haqir", "wate", "wati", "wa6e", "wa6i", "dayouth", "dayyouth", "dayous",
    "dayyous", "ibn el 7aram", "ebn el 7aram", "ibn 7aram", "ebn 7aram",
    "ibn el haram", "ebn el haram", "ibn el kalb", "ebn el kalb", "ibn kalb",
    "ya kalb", "ya kelb",
    # يلعن
    "yel3an abouk", "yil3an abouk", "yel3an ebn", "yel3an 3ardak",
    "yel3an sharafak", "yel3an ekhtak", "yl3n",
]

# Sect and community slurs, inflammatory political slogans and religious
# insults: a narrow list of sectarian and political flashpoints, not
# general political vocabulary. Only watched, never blocked, and only
# outside #politics-and-religion (see the module docstring).
SECTARIAN = [
    "wahhabi", "wahabi", "safawi", "rafidhi", "nawasib", "majoos",
    "crusader", "crusaders", "zionist", "zionists",
    "apostate", "apostates", "heretic", "heretics",
    "death to america", "death to israel", "party of satan",
    "*وهابي*", "*صهيوني*", "*صهاين*", "*ارهابي*", "*إرهابي*",
    "*مرتد*", "*زنديق*", "*زنادق*",
    "حزب الشيطان", "*الموت لأمريكا*", "*الموت لامريكا*",
    "*الموت لاسرائيل*", "*الموت لإسرائيل*",
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


def community_words():
    """Watch words changed by vote: {"added": [...], "removed": [...]}. Only
    the watch lists change this way; what is blocked is the safety floor."""
    return store.load("watch_words", {"added": [], "removed": []})


def save_community_words(words):
    store.save("watch_words", words)


def sectarian_words():
    """SECTARIAN as it is watched: less any word a vote removed."""
    removed = set(community_words()["removed"])
    return [w for w in SECTARIAN if w not in removed]


def sectarian_hit(text):
    """True when `text` uses one of the sectarian watch words. Matches the
    way Discord matches keywords: whole words unless the word is wrapped
    in `*`, and case does not matter."""
    lowered = text.casefold()
    for word in sectarian_words():
        stem = word.strip("*")
        if word.startswith("*"):
            if stem in lowered:
                return True
        elif re.search(rf"(?<!\w){re.escape(stem)}(?!\w)", lowered):
            return True
    return False


def plan():
    """(name, trigger, block) for every rule the bot keeps. Names are how
    the bot recognises its own rules again on the next start."""
    T = discord.AutoModRuleTriggerType
    words = community_words()
    removed = set(words["removed"])
    rules = [
        (PREFIX + "watch English", discord.AutoModTrigger(
            type=T.keyword, keyword_filter=[w for w in ENGLISH if w not in removed],
            regex_patterns=ENGLISH_PATTERNS), False),
        (PREFIX + "watch Arabic", discord.AutoModTrigger(
            type=T.keyword, keyword_filter=[w for w in ARABIC if w not in removed]), False),
    ]
    if words["added"]:
        rules.append((PREFIX + "watch words added by vote", discord.AutoModTrigger(
            type=T.keyword, keyword_filter=words["added"][:1000]), False))
    return rules + [
        (PREFIX + "watch Arabizi", discord.AutoModTrigger(
            type=T.keyword, keyword_filter=[w for w in ARABIZI_WORDS if w not in removed],
            regex_patterns=ARABIZI), False),
        (PREFIX + "watch sectarian talk", discord.AutoModTrigger(
            type=T.keyword, keyword_filter=sectarian_words()), False),
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
    planned = plan()
    wanted = {name for name, _, _ in planned}
    for name, rule in existing.items():
        if name.startswith(PREFIX) and name not in wanted:
            await rule.delete(reason="No longer part of the bot's AutoMod rules")
    for name, trigger, block in planned:
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
