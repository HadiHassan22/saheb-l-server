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

    def test_explanation_prompt_says_the_decision_is_final(self):
        v = judge.Verdict(rule=2, severity="serious", explanation="",
                          decided_by=judge.FIRST_CHECK)
        prompt = judge.explain_prompt("STATE", v)
        self.assertIn("No hate", prompt)
        self.assertIn("not yours to review", prompt)
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
        for title, _ in conduct.RULES:
            self.assertIn(title, prompt)
        self.assertIn("STATE", prompt)

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


class Sanctions(unittest.TestCase):
    def check(self, severity, record, action, minutes=0, delete=None):
        got = judge.sanction(severity, record, DEFAULTS)
        self.assertEqual((got.action, got.minutes), (action, minutes))
        if delete is not None:
            self.assertEqual(got.delete, delete)

    def test_mild_warns_until_warnings_add_up_to_a_timeout(self):
        self.check("mild", CLEAN, cases.WARN, delete=False)
        self.check("mild", {"warnings": 1, "timeouts": 0}, cases.WARN)
        self.check("mild", {"warnings": 2, "timeouts": 0}, cases.TIMEOUT, 60, delete=False)
        self.check("mild", {"warnings": 2, "timeouts": 1}, cases.TIMEOUT, 24 * 60)

    def test_serious_is_a_deleted_warning_first_then_timeouts_then_a_ban(self):
        self.check("serious", CLEAN, cases.WARN, delete=True)
        self.check("serious", {"warnings": 1, "timeouts": 0}, cases.TIMEOUT, 60, delete=True)
        self.check("serious", {"warnings": 0, "timeouts": 1}, cases.TIMEOUT, 24 * 60)
        self.check("serious", {"warnings": 0, "timeouts": 2}, cases.BAN, delete=True)

    def test_mild_never_bans_however_long_the_record(self):
        self.check("mild", {"warnings": 9, "timeouts": 9}, cases.TIMEOUT, 24 * 60)

    def test_severe_bans_even_a_clean_record(self):
        self.check("severe", CLEAN, cases.BAN, delete=True)

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
        for words in (automod.ENGLISH, automod.ARABIC, automod.BLOCK_WORDS):
            self.assertLessEqual(len(words), 1000)
            self.assertEqual(len(words), len(set(words)), "duplicate keyword")
            for word in words:
                self.assertLessEqual(len(word), 60, word)

    def test_patterns_fit_discords_limits_and_compile(self):
        for patterns in (automod.ARABIZI, automod.BLOCK_PATTERNS):
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

    def test_phone_numbers_are_blocked_but_prices_are_not(self):
        def blocked(text):
            return any(re.search(p, text) for p in automod.BLOCK_PATTERNS)
        self.assertTrue(blocked("call her on 03 123456"))
        self.assertTrue(blocked("+961 71 234 567"))
        self.assertFalse(blocked("it costs 70 000 000 LL"))
        self.assertFalse(blocked("70,000,000"))

    def test_plan_names_are_unique_and_prefixed(self):
        import discord  # only here: the lists above need no discord
        names = [name for name, _, _ in automod.plan()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n.startswith(automod.PREFIX) for n in names))
        self.assertIsNotNone(discord)


class Texts(unittest.TestCase):
    def test_posts_fit_in_one_discord_message(self):
        self.assertLessEqual(len(conduct.rules_text()), 2000)
        welcome = conduct.welcome_text("<@1234567890123456789>", "<#1234567890123456789>")
        self.assertLessEqual(len(welcome), 2000)
        self.assertIn("24 hours", welcome)


if __name__ == "__main__":
    unittest.main()
