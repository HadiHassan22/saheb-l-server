"""Checks for the self-update system: the protected-core check, what the bot
says as a proposal goes through the workflow, and what it tells the
workflow. No network.

    python -m unittest
"""

import asyncio
import copy
import importlib.util
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import admins
import code_changes
import health
import layout
import proposals
import setting_changes
import store
import updates
import workflow

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

    def test_the_github_token_is_protected(self):
        self.assertEqual(protected.path_problems(["workflow.py"]),
                         ["changes a protected file: workflow.py"])
        diff = ('+++ b/updates.py\n+t = workflow._token()\n'
                "+t = store.load('github', {})\n+p = store.DATA_DIR / 'github.json'\n"
                "+await workflow.start()\n+data = await workflow.get('pulls')\n")
        self.assertEqual(len(protected.access_problems(diff)), 3)

    def test_code_that_could_link_members_to_github_is_refused(self):
        diff = ("+++ b/updates.py\n+    text = pr['html_url']\n"
                '+PULLS = "https://api.github.com/repos/x/pulls"\n'
                "+++ b/chat.py\n+see https://github.com/someone/repo\n"
                "+++ b/README.md\n+[code](https://github.com/o/r)\n"
                "+++ b/test_chat.py\n+url = 'https://github.com/o/r'\n")
        found = protected.github_problems(diff)
        self.assertEqual([f.split(":")[0] for f in found], ["updates.py", "chat.py"])

    def test_similar_names_are_not_protected(self):
        self.assertEqual(protected.path_problems(["ai_helpers.py", "github.py"]), [])


class ProtectedValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The real values, read the way the workflow reads them.
        cls.base = protected.snapshot(str(HERE))

    def changed(self, edit, admin=False):
        head = copy.deepcopy(self.base)
        edit(head)
        return protected.value_problems(self.base, head, admin)

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

    def test_setting_ranges_can_widen_but_only_an_admin_narrows_or_drops_one(self):
        def narrow(h):
            h["ranges"]["quorum"] = [4, 100]
            del h["ranges"]["review_percent"]
        found = self.changed(narrow)
        self.assertIn("narrows the range of the setting quorum from [3, 100] to [4, 100]",
                      found)
        self.assertIn("removes the setting review_percent", found)
        self.assertEqual(self.changed(narrow, admin=True), [])
        self.assertEqual(self.changed(lambda h: h["ranges"].update(quorum=[1, 200])), [])

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

    def test_core_channels_move_only_for_an_admin_and_rules_4_to_6_never(self):
        def loosen(h):
            h["core_channels"].remove("mod-log")
            h["fixed_rules"].remove(5)
            h["floor_rule_text"][0][1] = "Doxxing is fine."
        self.assertEqual(self.changed(loosen), [
            "lets a vote rename or delete #mod-log",
            "lets a vote change rule 5",
            "changes the text of rules 4 to 6",
        ])
        self.assertEqual(self.changed(loosen, admin=True), [
            "lets a vote change rule 5",
            "changes the text of rules 4 to 6",
        ])

    def test_the_safety_floor_holds_for_an_admin_too(self):
        found = self.changed(lambda h: h["block_words"].remove("free nitro"), admin=True)
        self.assertEqual(len(found), 1, found)


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

    def test_every_stage_has_a_message_and_none_links_to_github(self):
        for stage in updates.ORDER:
            said = updates.message(3, stage, "Added a trivia game.")
            self.assertIn("Proposal 3", said.replace("proposal 3", "Proposal 3"))
            self.assertNotIn("http", said)
        self.assertIn("trivia", updates.message(3, updates.NO_CHANGE, "trivia"))
        self.assertNotIn("trivia", updates.message(3, updates.WRITING, "trivia"))

    def test_members_get_the_summary_without_links(self):
        body = ("Proposal 3. It passed a vote in the server.\n\nAdded trivia, see "
                "https://github.com/o/r/pull/3 and <https://example.com>.\n\n"
                "**Why it wasn't merged**\n- The tests fail.")
        summary = updates.summary_of({"body": body})
        self.assertTrue(summary.startswith("Added trivia"))
        self.assertNotIn("github", summary)
        self.assertNotIn("http", summary)
        self.assertIn("The tests fail.", summary)
        self.assertEqual(updates.summary_of({"body": None}), "")
        self.assertLessEqual(len(updates.summary_of({"body": "x" * 5000})), 1501)


class WithTempData(unittest.IsolatedAsyncioTestCase):
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

    def test_admins_can_find_a_proposals_code_change(self):
        updates.advance(5, updates.WRITING, pr("proposal-5", "open"))
        self.assertEqual(updates.link(5), "https://github.com/o/r/pull/proposal-5")
        self.assertIsNone(updates.link(6))
        self.assertTrue(updates.link().startswith("https://github.com/"))

    def test_the_running_commit_names_its_proposal(self):
        updates.advance(4, updates.MERGED, pr("proposal-4", merged=True, sha="1234567abc"))
        with mock.patch.object(health, "COMMIT", "1234567"):
            self.assertEqual(updates.running_proposal(), 4)
        with mock.patch.object(health, "COMMIT", "local"):
            self.assertIsNone(updates.running_proposal())


def run(id, status="completed", conclusion="success", event="schedule"):
    return {"id": id, "run_number": id, "status": status, "conclusion": conclusion,
            "event": event, "html_url": f"https://github.com/o/r/actions/runs/{id}"}


class Runs(unittest.TestCase):
    def test_the_first_look_announces_nothing(self):
        seen = {}
        self.assertEqual(updates.run_news([run(2, conclusion="failure"), run(1)], seen), [])
        self.assertEqual(updates.run_news([run(2, conclusion="failure"), run(1)], seen), [])

    def test_runs_someone_started_are_announced_and_the_timers_are_not(self):
        seen = {}
        updates.run_news([run(1)], seen)
        news = updates.run_news([run(3, "in_progress", None, "workflow_dispatch"),
                                 run(2, "in_progress", None), run(1)], seen)
        self.assertEqual(len(news), 1)
        self.assertIn("running (run 3", news[0])
        self.assertEqual(updates.run_news([run(3, "in_progress", None, "workflow_dispatch"),
                                           run(1)], seen), [])

    def test_a_string_of_failures_is_announced_once_and_so_is_the_recovery(self):
        seen = {}
        updates.run_news([run(1)], seen)
        runs = [run(1)]
        said = []
        for id, conclusion in ((2, "failure"), (3, "timed_out"), (4, "cancelled"),
                               (5, "success"), (6, "success")):
            runs.insert(0, run(id, conclusion=conclusion))
            said += updates.run_news(runs, seen)
        self.assertEqual(len(said), 2)
        self.assertIn("failed (run 2", said[0])
        self.assertIn("works again (run 5", said[1])

    def test_a_run_finishing_after_a_newer_one_is_still_seen(self):
        seen = {}
        updates.run_news([run(1)], seen)
        updates.run_news([run(3, conclusion="cancelled"), run(2, "in_progress", None)], seen)
        news = updates.run_news([run(3, conclusion="cancelled"),
                                 run(2, conclusion="failure")], seen)
        self.assertEqual(len(news), 1)
        self.assertIn("failed (run 2", news[0])


class Starting(WithTempData):
    def setUp(self):
        super().setUp()
        updates._last.update(at=0.0, refused=None)
        self.told = []
        patcher = mock.patch.object(admins, "post", self.post)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def post(self, guild, text):
        self.told.append(text)
        return True

    async def test_without_a_token_the_admins_are_told_once(self):
        guild = object()
        self.assertFalse(await updates.start(guild, "proposal 3"))
        self.assertFalse(await updates.start(guild, "proposal 4"))
        self.assertEqual(len(self.told), 1)
        self.assertIn("proposal 3", self.told[0])
        self.assertIn("/github-key", self.told[0])

    async def test_a_start_is_reported_and_clears_the_last_refusal(self):
        with mock.patch.object(workflow, "start", mock.AsyncMock(
                side_effect=[workflow.Refused("GitHub answered 500"), None, None])):
            await updates.start(None, "proposal 1")
            self.assertTrue(await updates.start(object(), "proposal 2"))
            self.assertEqual(self.told, ["Started the self-update workflow for proposal 2."])
            self.assertIsNone(updates._last["refused"])

    async def test_a_passed_code_change_starts_the_workflow(self):
        started = mock.AsyncMock()
        with mock.patch.object(updates, "start", started):
            said = await code_changes.KIND.carry_out(None, "guild", {"no": 8})
            await asyncio.gather(*updates._tasks)
        started.assert_awaited_once_with("guild", "proposal 8")
        self.assertIn("written as a code change", said)


class Reading(WithTempData):
    class Session:
        """Answers GETs from `statuses` in turn, noting each call's headers."""
        def __init__(self, statuses):
            self.statuses, self.headers = list(statuses), []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, params=None, headers=None):
            self.headers.append(headers)
            status = self.statuses.pop(0)
            response = mock.MagicMock(status=status)
            response.json = mock.AsyncMock(return_value={"ok": status})
            response.__aenter__ = mock.AsyncMock(return_value=response)
            response.__aexit__ = mock.AsyncMock(return_value=False)
            return response

    async def test_a_token_github_refuses_falls_back_to_the_public_api(self):
        store.save("github", {"token": "secret"}, private=True)
        session = self.Session([401, 200])
        with mock.patch.object(workflow.aiohttp, "ClientSession", lambda **kw: session):
            self.assertEqual(await workflow.get("pulls"), {"ok": 200})
        self.assertIn("Authorization", session.headers[0])
        self.assertNotIn("Authorization", session.headers[1])

    async def test_without_a_token_reads_are_public_and_failures_say_why(self):
        session = self.Session([403])
        with mock.patch.object(workflow.aiohttp, "ClientSession", lambda **kw: session):
            with self.assertRaisesRegex(workflow.Refused, "Actions: read and write"):
                await workflow.get("pulls")
        self.assertEqual(len(session.headers), 1)
        self.assertNotIn("Authorization", session.headers[0])


class AdminLog(WithTempData):
    OWNER, ADMIN, MEMBER = 1, 2, 3

    def setUp(self):
        super().setUp()
        self.people = {i: discord.Object(id=i)
                       for i in (self.OWNER, self.ADMIN, self.MEMBER)}
        self.guild = types.SimpleNamespace(owner_id=self.OWNER, default_role="everyone",
                                           get_member=self.people.get)
        self.channel = mock.Mock(spec=discord.TextChannel)
        self.channel.overwrites = {"everyone": discord.PermissionOverwrite(),
                                   self.people[self.MEMBER]: discord.PermissionOverwrite(
                                       view_channel=True)}
        self.channel.edit = mock.AsyncMock()
        self.channel.send = mock.AsyncMock()
        patcher = mock.patch.object(layout, "channel", lambda guild, name: self.channel)
        patcher.start()
        self.addCleanup(patcher.stop)
        admins.add(self.ADMIN)

    async def test_only_the_admins_and_the_owner_can_read_it(self):
        self.assertTrue(await admins.post(self.guild, "Run 4 failed."))
        wanted = self.channel.edit.await_args.kwargs["overwrites"]
        self.assertFalse(wanted["everyone"].view_channel)
        readers = {target.id for target, o in wanted.items()
                   if target != "everyone" and o.view_channel}
        self.assertEqual(readers, {self.OWNER, self.ADMIN})
        self.channel.send.assert_awaited_once()

    async def test_nothing_is_posted_if_it_cant_be_kept_private(self):
        self.channel.edit.side_effect = discord.HTTPException(mock.Mock(status=403), "no")
        self.assertFalse(await admins.post(self.guild, "Run 4 failed."))
        self.channel.send.assert_not_awaited()

    async def test_it_is_left_alone_when_already_right(self):
        await admins.post(self.guild, "one")
        self.channel.overwrites = self.channel.edit.await_args.kwargs["overwrites"]
        self.channel.edit.reset_mock()
        await admins.post(self.guild, "two")
        self.channel.edit.assert_not_awaited()


class Passed(WithTempData):
    def test_only_passed_general_proposals_are_offered_oldest_first(self):
        for n in range(4):
            code_changes.KIND.open(n + 1, f"Idea {n}", "Do it.", NOW)
        setting_changes.KIND.open(9, "quorum", 8, "", NOW)
        for no in (1, 2, 3, 5):
            for voter in range(10, 15):
                proposals.cast(no, voter, 0, "yes" if no != 2 else "no", NOW + 60)
            proposals.close(no, NOW + proposals.DAY)
        self.assertEqual([p["no"] for p in health.passed_proposals()], [1, 3])
        self.assertEqual(health.passed_proposals()[0],
                         {"no": 1, "title": "Idea 0", "details": "Do it.", "shipped": False})

    def test_waiting_is_what_passed_and_has_no_pull_request_yet(self):
        for n in range(3):
            proposals.pass_now(code_changes.KIND.open(7, f"Idea {n}", "Do it.", NOW)["no"],
                               7, NOW)
        updates.advance(1, updates.FAILED)
        updates.advance(2, updates.WRITING)
        self.assertEqual(updates.waiting(), [3])

    def test_a_change_an_admin_shipped_is_offered_at_once(self):
        proposals.pass_now(code_changes.KIND.open(7, "Dark mode", "Add it.", NOW)["no"],
                           7, NOW)
        self.assertEqual(health.passed_proposals(),
                         [{"no": 1, "title": "Dark mode", "details": "Add it.",
                           "shipped": True}])


if __name__ == "__main__":
    unittest.main()
