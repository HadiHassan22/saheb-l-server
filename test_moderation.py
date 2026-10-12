"""Checks for judging, sanctions, case records, the AutoMod lists and the
posted texts. No Discord server and no network needed.

    python -m unittest
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

import automod
import cases
import conduct
import judge
import scold
import settings
import store

NOW = 1_800_000_000
DEFAULTS = {name: spec["default"] for name, spec in settings.SETTINGS.items()}
CLEAN = {"warnings": 0, "timeouts": 0}


def answers(**scores):
    return {name: {"type": "noul", "noul": p} for name, p in scores.items()}


class FirstCheck(unittest.TestCase):
    def test_every_question_is_a_noul_with_both_criteria(self):
        asked = judge.questions()
        self.assertEqual(set(asked),
                         set(judge.HAZARDS) | {"self_harm", "steering", "severity"})
        self.assertEqual(asked["severity"]["type"], "score")
        self.assertEqual(len(asked["severity"]["criteria"]), 4)
        for question in asked.values():
            if question["type"] == "noul":
                self.assertTrue(question["criteria"]["true"] and question["criteria"]["false"])

    def test_screen_finds_the_top_hazard_and_tolerates_missing_answers(self):
        screening = judge.screen(answers(harassment=0.96, hate=0.4, steering=0.1))
        self.assertEqual((screening.top, screening.top_score), ("harassment", 0.96))
        self.assertEqual((screening.self_harm, screening.scores["scam"]), (0.0, 0.0))

    def route(self, **scores):
        return judge.route(judge.screen(answers(**scores)), DEFAULTS)

    def test_routes_from_the_playground_results(self):
        self.assertEqual(self.route(harassment=0.08), judge.CLEAR)       # banter
        self.assertEqual(self.route(harassment=0.96), judge.ACT)         # targeted
        self.assertEqual(self.route(hate=0.90), judge.ACT)               # sectarian
        self.assertEqual(self.route(harassment=0.72, steering=0.9), judge.REVIEW)

    def test_steering_is_reviewed_even_when_it_scores_low(self):
        self.assertEqual(self.route(harassment=0.1, steering=0.9), judge.REVIEW)
        self.assertEqual(self.route(harassment=0.1, steering=0.2), judge.CLEAR)

    def test_the_dials_move_the_bands(self):
        screening = judge.screen(answers(harassment=0.6))
        self.assertEqual(judge.route(screening, DEFAULTS), judge.REVIEW)
        self.assertEqual(judge.route(screening, dict(DEFAULTS, act_percent=60)), judge.ACT)
        self.assertEqual(judge.route(screening, dict(DEFAULTS, review_percent=70)),
                         judge.CLEAR)

    def test_first_check_verdict_takes_the_rule_and_severity_from_jev(self):
        def verdict(severity, **scores):
            found = answers(**scores)
            found["severity"] = {"type": "score", "score": severity}
            return judge.first_check_verdict(judge.screen(found))
        v = verdict(1.1, harassment=0.96)
        self.assertEqual((v.rule, v.severity, v.decided_by), (1, "mild", judge.FIRST_CHECK))
        self.assertEqual(verdict(1.8, hate=0.9).severity, "serious")
        self.assertEqual(verdict(2.7, threat=0.91).rule, 3)
        self.assertEqual(verdict(2.7, threat=0.91).severity, "severe")
        self.assertEqual(verdict(0.2, harassment=0.85).severity, "mild")  # never "none"

    def test_insults_and_hate_are_never_severe(self):
        def verdict(**scores):
            found = answers(**scores)
            found["severity"] = {"type": "score", "score": 2.9}
            return judge.first_check_verdict(judge.screen(found))
        self.assertEqual(verdict(harassment=0.96).severity, "serious")
        self.assertEqual(verdict(hate=0.96).severity, "serious")
        self.assertEqual(verdict(threat=0.96).severity, "severe")
        reviewed = judge.verdict({"violation": True, "rule": 1, "severity": "severe",
                                  "explanation": "Insulted a member."})
        self.assertEqual(reviewed.severity, "serious")

    def test_only_threats_doxxing_sexual_content_and_scams_can_be_severe(self):
        self.assertEqual({rule for rule in range(1, 12)
                          if judge.capped(rule, "severe") == "severe"}, {3, 4, 5, 6})
        self.assertEqual(judge.capped(7, "serious"), "serious")
        self.assertEqual(judge.capped(1, "mild"), "mild")

    def test_both_judges_are_told_words_alone_are_never_severe(self):
        self.assertIn("Words alone are never severe", judge.SEVERITY_LEVELS[3])
        prompt = judge.review_prompt("x")
        self.assertIn("Words alone are never severe", prompt)
        self.assertIn("serious at most", prompt)
        self.assertIn("free speech server", prompt)

    def test_joking_that_someone_got_doxxed_is_not_doxxing(self):
        question, true, false = judge.HAZARDS["doxxing"][1:]
        self.assertEqual(judge.HAZARDS["doxxing"][0], 4)  # the protected floor
        self.assertIn("actually contains", true)
        self.assertIn("horsy doxxed", false)
        self.assertIn("is not doxxing", judge.review_prompt("x"))

    def test_the_first_check_alone_only_ever_warns(self):
        v = judge.Verdict(rule=1, severity="serious", explanation="", decided_by="first check")
        self.assertTrue(judge.stands_alone(v, CLEAN, DEFAULTS))
        self.assertFalse(judge.stands_alone(v, {"warnings": 1, "timeouts": 0}, DEFAULTS))
        v.severity = "severe"
        self.assertFalse(judge.stands_alone(v, CLEAN, DEFAULTS))

    def test_arabic_sexual_swearing_is_not_sexual_content(self):
        self.assertIn("Arabic swearing", judge.HAZARDS["sexual"][3])
        self.assertIn("not sexual content", judge.review_prompt("x"))

    def test_explanation_prompt_says_the_decision_is_final(self):
        v = judge.Verdict(rule=2, severity="serious", explanation="",
                          decided_by=judge.FIRST_CHECK)
        prompt = judge.explain_prompt("STATE", v)
        self.assertIn("No hate", prompt)
        self.assertIn("not yours to review", prompt)
        self.assertIn("Never use an em dash", prompt)
        screening = judge.screen(answers(hate=0.9))
        self.assertIn("90% likely to be hate", judge.fallback_explanation(v, screening))

    def test_state_shows_conversation_then_flagged_message(self):
        text = judge.state(["[rami]: hi"], "karim", "ya 7mar")
        self.assertTrue(text.startswith("Recent messages:\n[rami]: hi"))
        self.assertTrue(text.endswith('Flagged message (from karim): "ya 7mar"'))
        self.assertIn("(no earlier messages)", judge.state([], "karim", "x"))


class Review(unittest.TestCase):
    def test_prompt_carries_every_rule_and_the_conversation(self):
        prompt = judge.review_prompt("STATE")
        for title, _ in conduct.rules():
            self.assertIn(title, prompt)
        self.assertIn("STATE", prompt)
        self.assertIn("Never use an em dash", prompt)

    def test_only_a_well_formed_violation_becomes_a_verdict(self):
        ok = {"violation": True, "rule": 1, "severity": "mild", "explanation": "Insulted Rami."}
        self.assertEqual((judge.verdict(ok).rule, judge.verdict(ok).decided_by),
                         (1, judge.REVIEWED))
        self.assertIsNone(judge.verdict(dict(ok, violation=False)))
        self.assertIsNone(judge.verdict(dict(ok, rule=0)))
        self.assertIsNone(judge.verdict(dict(ok, rule=99)))
        self.assertIsNone(judge.verdict(dict(ok, severity="none")))
        self.assertIsNone(judge.verdict(dict(ok, explanation=" ")))
        self.assertIsNone(judge.verdict({}))


class SectarianTalk(unittest.TestCase):
    def test_the_check_asks_the_topic_and_the_severity(self):
        asked = judge.sectarian_questions()
        self.assertEqual(set(asked), {"topic", "severity"})
        self.assertEqual(asked["severity"]["type"], "score")
        self.assertEqual(len(asked["severity"]["criteria"]), 4)
        self.assertTrue(asked["topic"]["criteria"]["true"]
                        and asked["topic"]["criteria"]["false"])

    def found(self, topic=0.95, severity=1.0):
        return judge.sectarian({"topic": {"noul": topic}, "severity": {"score": severity}})

    def test_only_clearly_inflammatory_talk_is_passed_on(self):
        self.assertFalse(judge.escalates(self.found(severity=1.2), DEFAULTS))  # a joke
        self.assertFalse(judge.escalates(self.found(topic=0.2, severity=2.8), DEFAULTS))
        self.assertTrue(judge.escalates(self.found(severity=2.1), DEFAULTS))
        self.assertTrue(judge.escalates(self.found(severity=2.8), DEFAULTS))
        self.assertFalse(judge.escalates(judge.sectarian({}), DEFAULTS))  # never a guess

    def test_the_dial_moves_the_gate(self):
        talk = self.found(topic=0.6, severity=2.5)
        self.assertFalse(judge.escalates(talk, dict(DEFAULTS, sectarian_percent=80)))
        self.assertTrue(judge.escalates(talk, dict(DEFAULTS, sectarian_percent=50)))


class Sanctions(unittest.TestCase):
    def check(self, severity, record, action, minutes=0, call=False):
        got = judge.sanction(severity, record, DEFAULTS)
        self.assertEqual((got.action, got.minutes, got.call_admins), (action, minutes, call))

    def test_mild_warns_until_warnings_add_up_to_a_timeout(self):
        self.check("mild", CLEAN, cases.WARN)
        self.check("mild", {"warnings": 1, "timeouts": 0}, cases.WARN)
        self.check("mild", {"warnings": 2, "timeouts": 0}, cases.TIMEOUT, 60)
        self.check("mild", {"warnings": 2, "timeouts": 1}, cases.TIMEOUT, 24 * 60)

    def test_serious_is_a_warning_first_then_timeouts_then_the_admins(self):
        self.check("serious", CLEAN, cases.WARN)
        self.check("serious", {"warnings": 1, "timeouts": 0}, cases.TIMEOUT, 60)
        self.check("serious", {"warnings": 0, "timeouts": 1}, cases.TIMEOUT, 24 * 60)
        self.check("serious", {"warnings": 0, "timeouts": 2}, cases.TIMEOUT, 24 * 60,
                   call=True)

    def test_mild_never_bans_however_long_the_record(self):
        self.check("mild", {"warnings": 9, "timeouts": 9}, cases.TIMEOUT, 24 * 60)

    def test_severe_holds_even_a_clean_record_and_calls_the_admins(self):
        self.check("severe", CLEAN, cases.TIMEOUT, 24 * 60, call=True)

    def test_only_private_information_sexual_content_and_scams_are_deleted(self):
        self.assertEqual({rule for rule in range(1, 9) if judge.removes(rule)}, {4, 5, 6})

    def test_the_bot_never_bans(self):
        for severity in judge.SEVERITIES:
            for n in range(5):
                record = {"warnings": n, "timeouts": n}
                self.assertNotEqual(judge.sanction(severity, record, DEFAULTS).action,
                                    cases.BAN)

    def test_settings_move_the_ladder(self):
        s = dict(DEFAULTS, warnings_before_timeout=1, first_timeout_minutes=15)
        got = judge.sanction("mild", CLEAN, s)
        self.assertEqual((got.action, got.minutes), (cases.TIMEOUT, 15))


class Records(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def open(self, user, action, at):
        return cases.open_case(at, user_id=user, action=action, minutes=0)

    def test_record_counts_recent_active_cases_for_that_member_only(self):
        self.open(1, cases.WARN, NOW - 40 * cases.DAY)   # too old
        self.open(1, cases.WARN, NOW - cases.DAY)
        self.open(1, cases.TIMEOUT, NOW - cases.DAY)
        overturned = self.open(1, cases.WARN, NOW - cases.DAY)
        self.open(2, cases.WARN, NOW - cases.DAY)
        cases.update(overturned["no"], status=cases.OVERTURNED)
        self.assertEqual(cases.record_of(1, NOW, 30), {"warnings": 1, "timeouts": 1})
        self.assertEqual(cases.last_action_at(1), NOW - cases.DAY)
        self.assertIsNone(cases.last_action_at(3))

    def test_case_numbers_count_up(self):
        self.assertEqual([self.open(1, cases.WARN, NOW)["no"] for _ in range(3)], [1, 2, 3])


class AutoModLists(unittest.TestCase):
    def test_keywords_fit_discords_limits(self):
        for words in (automod.ENGLISH, automod.ARABIC, automod.ARABIZI_WORDS,
                      automod.SECTARIAN, automod.BLOCK_WORDS):
            self.assertLessEqual(len(words), 1000)
            self.assertEqual(len(words), len(set(words)), "duplicate keyword")
            for word in words:
                self.assertLessEqual(len(word), 60, word)

    def test_patterns_fit_discords_limits_and_compile(self):
        for patterns in (automod.ARABIZI, automod.ENGLISH_PATTERNS, automod.BLOCK_PATTERNS):
            self.assertLessEqual(len(patterns), 10)
            for pattern in patterns:
                self.assertLessEqual(len(pattern), 260, pattern)
                re.compile(pattern)

    def test_arabizi_patterns_catch_the_common_spellings(self):
        caught = ["ya sharmouta", "ya 7mar", "kess emmak", "ya manyak",
                  "yel3an deenak", "bedba7ak", "ba3ref wen saken"]
        for text in caught:
            self.assertTrue(any(re.search(p, text) for p in automod.ARABIZI), text)
        for text in ("I love my nike shoes", "Nick is here", "the kalbe"):
            self.assertFalse(any(re.search(p, text) for p in automod.ARABIZI), text)

    def test_lebanese_swearing_and_the_n_word_are_watched(self):
        patterns = automod.ARABIZI + automod.ENGLISH_PATTERNS
        def caught(text):
            return any(re.search(p, text) for p in patterns)
        for text in ("ayre fik", "AYRAK", "zabre", "zebrak", "zobr", "yel3an abouk",
                     "nigga", "n1gg3r", "n i g g a", "n.i.g.g.e.r", "NIGGERS"):
            self.assertTrue(caught(text), text)
        for text in ("zebra crossing", "air", "error", "Niger", "Nigeria", "bigger",
                     "snigger", "ayers rock"):
            self.assertFalse(caught(text), text)
        for word in ("kessemmak", "sharmoota", "ka7be", "mnayak", "ibn el 7aram"):
            self.assertIn(word, automod.ARABIZI_WORDS)
        for word in ("أيري", "زبك", "كسك", "*ديوث*", "نيغا"):
            self.assertIn(word, automod.ARABIC)

    def test_rules_stay_within_discords_per_server_limits(self):
        import discord
        saved, store.DATA_DIR = store.DATA_DIR, Path(tempfile.mkdtemp())
        try:
            automod.save_community_words({"added": ["x"], "removed": []})
            rules = automod.plan()
        finally:
            shutil.rmtree(store.DATA_DIR)
            store.DATA_DIR = saved
        keyword = [t for _, t, _ in rules
                   if t.type == discord.AutoModRuleTriggerType.keyword]
        self.assertLessEqual(len(keyword), 6)
        for trigger in keyword:
            self.assertLessEqual(len(trigger.keyword_filter), 1000)
            self.assertLessEqual(len(trigger.regex_patterns), 10)

    def test_phone_numbers_are_blocked_but_prices_are_not(self):
        def blocked(text):
            return any(re.search(p, text) for p in automod.BLOCK_PATTERNS)
        self.assertTrue(blocked("call her on 03 123456"))
        self.assertTrue(blocked("+961 71 234 567"))
        self.assertFalse(blocked("it costs 70 000 000 LL"))
        self.assertFalse(blocked("70,000,000"))

    def test_sectarian_words_are_watched_but_never_blocked(self):
        rules = {name: block for name, _, block in automod.plan()}
        self.assertFalse(rules[automod.PREFIX + "watch sectarian talk"])

    def test_sectarian_hit_finds_the_words_but_not_ordinary_talk(self):
        caught = ["ya wahhabi", "he is a rafidhi", "Death to America!",
                  "the party of satan", "حزب الشيطان", "يا زنديق", "الموت لأمريكا"]
        for text in caught:
            self.assertTrue(automod.sectarian_hit(text), text)
        for text in ("hezbollah won the election", "I go to church in jounieh",
                     "the government fell again", "ya 7mar"):
            self.assertFalse(automod.sectarian_hit(text), text)

    def test_plan_names_are_unique_and_prefixed(self):
        import discord  # only here: the lists above need no discord
        names = [name for name, _, _ in automod.plan()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n.startswith(automod.PREFIX) for n in names))
        self.assertIsNotNone(discord)


class Texts(unittest.TestCase):
    def test_posts_fit_in_one_embed(self):
        title, rules = conduct.rules_text()
        self.assertLessEqual(len(rules), 4096)
        title, welcome = conduct.welcome_text("<@1234567890123456789>",
                                              "<#1234567890123456789>", "<#1>")
        self.assertLessEqual(len(welcome), 4096)
        self.assertIn("24 hours", welcome)
        self.assertIn("<#1>", welcome)

    def test_the_guide_says_how_to_use_the_bot(self):
        title, guide = conduct.tutorial_text("<#1>", "<#2>")
        self.assertLessEqual(len(title), 256)   # an embed title
        self.assertLessEqual(len(guide), 4096)  # one embed
        self.assertIn("<#1>", guide)            # where to talk to the bot
        self.assertIn("<#2>", guide)            # where the votes are
        for said in ("Beirut", "invite link", "/propose", "/appeal", "cosmetic",
                     "without a vote", "temporary voice channel", "soundboard"):
            self.assertIn(said, guide)
        self.assertNotIn("—", guide)            # the bot never uses an em dash


if __name__ == "__main__":
    unittest.main()


class Scolding(unittest.TestCase):
    CASE = {"no": 12, "action": cases.TIMEOUT, "minutes": 60, "rule": 1,
            "severity": "serious"}

    def test_the_prompt_says_the_case_is_decided_and_keeps_politics_out(self):
        prompt = scold.prompt("Flagged message: x", self.CASE)
        self.assertIn("final and not yours to change", prompt)
        self.assertIn("timeout (60 minutes)", prompt)
        self.assertIn("No politics, religion or sect", prompt)
        self.assertIn("Do not repeat slurs", prompt)

    def test_the_reply_fits_and_carries_the_case(self):
        text = scold.reply({"reply": "ya 3ayb — " + "x" * 3000}, self.CASE)
        self.assertLessEqual(len(text), 2000)
        self.assertNotIn("—", text)
        self.assertIn("-# Timeout (60 minutes) · case 12 · rule 1", text)
        self.assertIn("/appeal case:12", text)

    def test_every_stock_line_fits(self):
        for n in range(len(scold.FALLBACKS)):
            text = scold.reply(None, dict(self.CASE, no=n))
            self.assertLessEqual(len(text), 2000)
            self.assertNotIn("—", text)
