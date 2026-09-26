"""Checks for the settings and the proposal lifecycle. No Discord needed.

    python -m unittest
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import code_changes
import proposals
import setting_changes
import settings
import store

NOW = 1_800_000_000
DAY = proposals.DAY
VETERAN = NOW - 30 * DAY  # joined long enough ago to vote


class WithTempData(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def general(self, author=1, now=NOW):
        return code_changes.KIND.open(author, " Title ", " Details ", now)

    def vote(self, no, votes, now=NOW + 60):
        """votes: {voter_id: "yes" | "no"}"""
        for voter, choice in votes.items():
            proposals.cast(no, voter, VETERAN, choice, now)


class Settings(WithTempData):
    def test_defaults_match_the_server_description(self):
        self.assertEqual(settings.current(), {
            "voting_hours": 24, "quorum": 5, "pass_percent": 50, "removal_percent": 66,
            "voter_min_days": 7, "max_open_per_member": 3,
            "warning_days": 30, "warnings_before_timeout": 3,
            "first_timeout_minutes": 60, "repeat_timeout_hours": 24,
            "timeouts_before_ban": 2, "act_percent": 80, "review_percent": 30,
            "sectarian_percent": 80,
        })

    def test_values_outside_the_bounds_are_refused(self):
        self.assertIsNone(settings.check("quorum", 3))
        self.assertIn("between 3 and 100", settings.check("quorum", 2))
        self.assertIn("between 50 and 90", settings.check("pass_percent", 40))
        self.assertIn("no setting", settings.check("owner_powers", 1))
        with self.assertRaises(ValueError):
            settings.apply("quorum", 1)

    def test_applied_value_persists(self):
        settings.apply("voting_hours", 48)
        self.assertEqual(settings.current()["voting_hours"], 48)


class Opening(WithTempData):
    def test_proposal_locks_in_the_rules_it_opened_under(self):
        p = self.general()
        self.assertEqual((p["no"], p["title"], p["details"]), (1, "Title", "Details"))
        self.assertEqual(p["closes_at"], NOW + 24 * 60 * 60)
        settings.apply("quorum", 10)
        self.assertEqual(proposals.get(1)["quorum"], 5)
        self.assertEqual(self.general()["quorum"], 10)

    def test_numbers_are_never_reused(self):
        self.assertEqual([self.general()["no"] for _ in range(3)], [1, 2, 3])

    def test_open_proposal_limit_is_per_member_and_frees_up_on_close(self):
        for _ in range(3):
            self.general(author=1)
        with self.assertRaisesRegex(proposals.Refused, "limit"):
            self.general(author=1)
        self.general(author=2)
        proposals.close(1, NOW + DAY)
        self.general(author=1)

    def test_setting_proposal_is_checked_and_described(self):
        with self.assertRaisesRegex(proposals.Refused, "between 3 and 100"):
            setting_changes.KIND.open(1, "quorum", 1, "", NOW)
        with self.assertRaisesRegex(proposals.Refused, "already"):
            setting_changes.KIND.open(1, "quorum", 5, "", NOW)
        p = setting_changes.KIND.open(1, "voting_hours", 48, "too slow", NOW)
        self.assertEqual(p["title"], "Voting window: 48 hours")
        self.assertIn("from 24 hours to 48 hours", p["details"])
        self.assertIn("too slow", p["details"])


class Voting(WithTempData):
    def test_only_members_past_the_minimum_can_vote(self):
        self.general()
        proposals.cast(1, 10, NOW - 7 * DAY, "yes", NOW)
        with self.assertRaisesRegex(proposals.Refused, "7 days"):
            proposals.cast(1, 11, NOW - 6 * DAY, "yes", NOW)
        with self.assertRaisesRegex(proposals.Refused, "7 days"):
            proposals.cast(1, 12, None, "yes", NOW)

    def test_whoever_joins_in_the_founding_week_can_vote_at_once(self):
        founded = NOW - 3 * DAY  # the bot joined three days ago
        self.general()
        proposals.cast(1, 10, NOW - 60, "yes", NOW, founded)
        proposals.cast(1, 11, founded - DAY, "yes", NOW, founded)  # was here first
        later = founded + 10 * DAY
        self.general(now=later)
        proposals.cast(2, 10, NOW - 60, "yes", later + 60, founded)  # keeps the right
        with self.assertRaisesRegex(proposals.Refused, "7 days"):
            proposals.cast(2, 12, founded + 8 * DAY, "yes", later + 60, founded)
        with self.assertRaisesRegex(proposals.Refused, "7 days"):
            proposals.cast(2, 13, None, "yes", later + 60, founded)

    def test_a_vote_can_be_changed_and_counts_once(self):
        self.general()
        self.vote(1, {10: "yes"})
        self.vote(1, {10: "no"})
        self.assertEqual(proposals.tally(proposals.get(1)), (0, 1))

    def test_no_voting_after_the_window_or_on_unknown_proposals(self):
        self.general()
        with self.assertRaisesRegex(proposals.Refused, "closed"):
            proposals.cast(1, 10, VETERAN, "yes", NOW + DAY)
        with self.assertRaisesRegex(proposals.Refused, "exist"):
            proposals.cast(99, 10, VETERAN, "yes", NOW)


class Admins(WithTempData):
    def test_an_admin_passes_a_proposal_at_once(self):
        p = proposals.pass_now(self.general()["no"], 7, NOW)
        self.assertEqual((p["status"], p["shipped_by"], p["totals"]),
                         (proposals.PASSED, 7, {"yes": 0, "no": 0}))
        self.assertEqual(proposals.due(NOW + 2 * DAY), [])
        with self.assertRaisesRegex(proposals.Refused, "has closed"):
            proposals.cast(p["no"], 10, VETERAN, "no", NOW)
        with self.assertRaisesRegex(proposals.Refused, "has closed"):
            proposals.pass_now(p["no"], 7, NOW)

    def test_an_admin_withdraws_an_open_proposal_and_nothing_is_counted(self):
        p = self.general()
        self.vote(p["no"], {10: "yes", 11: "no"})
        w = proposals.withdraw(p["no"], 7, " Duplicate ", NOW + 60)
        self.assertEqual((w["status"], w["withdrawn_by"], w["note"], w["votes"]),
                         (proposals.WITHDRAWN, 7, "Duplicate", {}))
        self.assertEqual(proposals.due(NOW + 2 * DAY), [])
        with self.assertRaisesRegex(proposals.Refused, "Only an open"):
            proposals.withdraw(p["no"], 7, "", NOW)
        with self.assertRaisesRegex(proposals.Refused, "doesn't exist"):
            proposals.withdraw(99, 7, "", NOW)


class SmallServer(WithTempData):
    def test_the_quorum_is_at_most_half_the_server_and_never_below_the_floor(self):
        self.assertEqual([proposals.quorum_for(5, n) for n in (1, 3, 6, 7, 9, 500)],
                         [3, 3, 3, 4, 5, 5])
        self.assertEqual(proposals.quorum_for(5, None), 5)

    def test_a_proposal_opens_with_the_quorum_for_the_server_it_is_in(self):
        p = self.general()
        self.assertEqual(proposals.fit_quorum(p["no"], 3)["quorum"], 3)
        self.vote(p["no"], {10: "yes", 11: "yes", 12: "no"})
        self.assertEqual(proposals.close(p["no"], NOW + DAY)["status"], proposals.PASSED)
        shipped = proposals.pass_now(self.general(author=7)["no"], 7, NOW)
        self.assertEqual(proposals.fit_quorum(shipped["no"], 3)["quorum"], 5)


class Outcome(unittest.TestCase):
    def test_quorum_then_strict_majority(self):
        self.assertEqual(proposals.outcome(4, 0, 5, 50), proposals.NO_QUORUM)
        self.assertEqual(proposals.outcome(3, 2, 5, 50), proposals.PASSED)
        self.assertEqual(proposals.outcome(3, 3, 5, 50), proposals.FAILED)

    def test_threshold_means_more_than(self):
        self.assertEqual(proposals.outcome(3, 2, 5, 60), proposals.FAILED)
        self.assertEqual(proposals.outcome(4, 1, 5, 60), proposals.PASSED)


class Closing(WithTempData):
    def test_due_only_after_the_window(self):
        self.general()
        self.assertEqual(proposals.due(NOW + DAY - 1), [])
        self.assertEqual([p["no"] for p in proposals.due(NOW + DAY)], [1])

    def test_close_keeps_totals_and_destroys_ballots(self):
        self.general()
        self.vote(1, {10: "yes", 11: "yes", 12: "yes", 13: "no", 14: "no"})
        p = proposals.close(1, NOW + DAY)
        self.assertEqual((p["no"], p["status"], p["totals"], p["votes"]),
                         (1, proposals.PASSED, {"yes": 3, "no": 2}, {}))
        self.assertEqual(proposals.get(1)["votes"], {})
        self.assertEqual(proposals.due(NOW + 2 * DAY), [])
        self.assertEqual(proposals.close(1, NOW + 2 * DAY)["closed_at"], NOW + DAY)

    def test_closing_carries_nothing_out(self):
        setting_changes.KIND.open(1, "voting_hours", 48, "", NOW)
        self.vote(1, {v: "yes" for v in range(10, 15)})
        self.assertEqual(proposals.close(1, NOW + DAY)["status"], proposals.PASSED)
        self.assertEqual(settings.current()["voting_hours"], 24)  # ending.py applies it

if __name__ == "__main__":
    unittest.main()
