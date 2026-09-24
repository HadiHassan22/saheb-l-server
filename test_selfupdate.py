"""Checks for the self-update system: the protected-core check, what the bot
says as a proposal goes through the workflow, and what it tells the
workflow. No network.

    python -m unittest
"""

import copy
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import health
import proposals
import store
import updates

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    "protected", HERE / ".github" / "selfupdate" / "protected.py")
protected = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protected)

NOW = 1_800_000_000


class ProtectedPaths(unittest.TestCase):
    def test_protected_files_and_the_workflow_folder_are_refused(self):
        changed = ["judge.py", ".github/workflows/self-update.yml", "ai.py",
                   "PROTECTED.md", "health.py", "README.md", "guard.py"]
        self.assertEqual(protected.path_problems(changed), [
            "changes a protected file: .github/workflows/self-update.yml",
            "changes a protected file: ai.py",
            "changes a protected file: PROTECTED.md",
            "changes a protected file: health.py",
            "changes a protected file: guard.py",
        ])

    def test_files_claude_code_reads_by_itself_are_protected(self):
        for path in ("CLAUDE.md", "CLAUDE.local.md", ".claude/settings.json",
                     ".agents/skills/x/SKILL.md", ".mcp.json"):
            self.assertEqual(len(protected.path_problems([path])), 1, path)
        self.assertEqual(protected.path_problems(["docs/CLAUDE.md.txt"]), [])

    def test_the_admins_are_protected(self):
        self.assertEqual(protected.path_problems(["admins.py"]),
                         ["changes a protected file: admins.py"])
        diff = ('+++ b/chat.py\n+store.save("admins", everyone)\n'
                "+ok = admins.is_admin(member.id)\n-store.load('admins', [])\n")
        found = protected.admin_problems(diff)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("chat.py: touches the list of admins"))

    def test_similar_names_are_not_protected(self):
        self.assertEqual(protected.path_problems(["ai_helpers.py", "github.py"]), [])


class ProtectedValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The real values, read the way the workflow reads them.
        cls.base = protected.snapshot(str(HERE))

    def changed(self, edit):
        head = copy.deepcopy(self.base)
        edit(head)
        return protected.value_problems(self.base, head)

    def test_the_snapshot_reads_the_running_code(self):
        self.assertEqual(self.base["ranges"]["quorum"], [3, 100])
        self.assertIn("1564", self.base["support_line"])
        self.assertTrue(self.base["block_rules"])

    def test_an_unchanged_or_extended_core_passes(self):
        self.assertEqual(self.changed(lambda h: None), [])

        def extend(h):
            h["ranges"]["new_setting"] = [1, 5]
            h["block_words"].append("free robux")
            h["hidden_rules"].append(3)
            h["support_at"] = 0.5
        self.assertEqual(self.changed(extend), [])

    def test_setting_ranges_cant_move_or_disappear(self):
        def narrow(h):
            h["ranges"]["quorum"] = [1, 100]
            del h["ranges"]["review_percent"]
        found = self.changed(narrow)
        self.assertIn("changes the range of the setting quorum from [3, 100] to [1, 100]",
                      found)
        self.assertIn("removes the setting review_percent", found)

    def test_the_safety_floor_cant_be_lowered(self):
        def weaken(h):
            h["block_words"].remove("free nitro")
            h["block_rules"].pop()
            h["hazards"].pop("doxxing")
            h["hidden_rules"].remove(4)
            h["support_at"] = 0.95
            h["support_line"] = "Take care."
        found = self.changed(weaken)
        self.assertEqual(len(found), 6, found)

    def test_nothing_new_happens_without_a_vote_and_the_core_stays(self):
        def loosen(h):
            h["instant_tools"].append("ban_member_now")
            h["core_channels"].remove("mod-log")
            h["fixed_rules"].remove(5)
            h["floor_rule_text"][0][1] = "Doxxing is fine."
        found = self.changed(loosen)
        self.assertEqual(found, [
            "lets the bot do ban_member_now without a vote",
            "lets a vote rename or delete #mod-log",
            "lets a vote change rule 5",
            "changes the text of rules 4 to 6",
        ])
        tightened = self.changed(lambda h: h["instant_tools"].remove("pin_message"))
        self.assertEqual(tightened, [])


class Scans(unittest.TestCase):
    DIFF = """diff --git a/judge.py b/judge.py
--- a/judge.py
+++ b/judge.py
@@ -1,2 +1,4 @@
 import os
+token = os.environ["DISCORD_TOKEN"]
+print("harmless")
+data = store.load("ai", {})
"""

    def test_added_lines_that_reach_for_secrets_are_refused(self):
        found = protected.access_problems(self.DIFF)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(f.startswith("judge.py:") for f in found))

    def test_removed_and_context_lines_are_ignored(self):
        diff = self.DIFF.replace("+token", "-token").replace("+data", " data")
        self.assertEqual(protected.access_problems(diff), [])

    def test_anything_that_looks_like_a_secret_is_caught(self):
        for secret in ("sk-ant-api03-abcdefghijklmnop", "sk-or-v1-0123456789abcdef",
                       "ghs_" + "a" * 36, "github_pat_" + "b" * 30,
                       "MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl." + "c" * 30):
            self.assertTrue(protected.contains_secret(f"x = '{secret}'"), secret)
        self.assertFalse(protected.contains_secret("the quorum is 5 and sk is fine"))


def pr(ref, state="closed", merged=False, labels=(), sha="abcdef1234"):
    return {"head": {"ref": ref}, "state": state,
            "merged_at": "2026-09-24T12:00:00Z" if merged else None,
            "labels": [{"name": n} for n in labels],
            "merge_commit_sha": sha if merged else None,
            "html_url": f"https://github.com/o/r/pull/{ref}"}


class Stages(unittest.TestCase):
    def test_pull_requests_map_to_stages(self):
        self.assertEqual(updates.proposal_of(pr("proposal-12")), 12)
        self.assertEqual(updates.proposal_of(pr("revert-proposal-12")), 12)
        self.assertIsNone(updates.proposal_of(pr("dependabot/pip")))
        self.assertEqual(updates.stage_of(pr("proposal-1", "open")), updates.WRITING)
        self.assertEqual(updates.stage_of(pr("proposal-1", merged=True)), updates.MERGED)
        self.assertEqual(updates.stage_of(pr("proposal-1", labels=["no-change"])),
                         updates.NO_CHANGE)
        self.assertEqual(updates.stage_of(pr("proposal-1", labels=["failed"])), updates.FAILED)
        self.assertEqual(updates.stage_of(pr("revert-proposal-1", merged=True)),
                         updates.ROLLED_BACK)
        self.assertIsNone(updates.stage_of(pr("revert-proposal-1", "open")))

    def test_every_stage_has_a_message(self):
        for stage in updates.ORDER:
            self.assertIn("Proposal 3", updates.message(3, stage, "https://x").replace(
                "proposal 3", "Proposal 3"))


class WithTempData(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)


class Progress(WithTempData):
    def test_stages_are_announced_once_and_never_go_backwards(self):
        self.assertTrue(updates.advance(1, updates.WRITING))
        self.assertFalse(updates.advance(1, updates.WRITING))
        self.assertTrue(updates.advance(1, updates.MERGED, pr("proposal-1", merged=True)))
        self.assertFalse(updates.advance(1, updates.WRITING))
        self.assertTrue(updates.advance(1, updates.ROLLED_BACK))

    def test_the_running_commit_names_its_proposal(self):
        updates.advance(4, updates.MERGED, pr("proposal-4", merged=True, sha="1234567abc"))
        with mock.patch.object(health, "COMMIT", "1234567"):
            self.assertEqual(updates.running_proposal(), 4)
        with mock.patch.object(health, "COMMIT", "local"):
            self.assertIsNone(updates.running_proposal())


class Passed(WithTempData):
    def test_only_passed_general_proposals_are_offered_oldest_first(self):
        for n in range(4):
            proposals.open_proposal(n + 1, f"Idea {n}", "Do it.", NOW)
        proposals.open_proposal(9, "", "", NOW, setting="quorum", value=8)
        for no in (1, 2, 3, 5):
            for voter in range(10, 15):
                proposals.cast(no, voter, 0, "yes" if no != 2 else "no", NOW + 60)
            proposals.close(no, NOW + proposals.DAY)
        self.assertEqual([p["no"] for p in health.passed_proposals()], [1, 3])
        self.assertEqual(health.passed_proposals()[0],
                         {"no": 1, "title": "Idea 0", "details": "Do it.", "shipped": False})

    def test_a_change_an_admin_shipped_is_offered_at_once(self):
        proposals.ship(7, "Dark mode", "Add it.", NOW)
        self.assertEqual(health.passed_proposals(),
                         [{"no": 1, "title": "Dark mode", "details": "Add it.",
                           "shipped": True}])


if __name__ == "__main__":
    unittest.main()
