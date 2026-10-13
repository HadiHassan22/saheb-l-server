"""Checks for how proposals end (ending.py) and look (cards.py): a vote
closing, an admin passing one at once, an admin withdrawing one, and what
each kind of proposal does then. Fake Discord objects; no network.

    python -m unittest
"""

import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import actions
import appeals
import cards
import cases
import code_changes
import ending
import judge
import kinds
import layout
import proposals
import setting_changes
import settings
import store

NOW = 1_800_000_000
DAY = proposals.DAY
VETERAN = NOW - 30 * DAY
ADMIN = 7


class Message:
    """A posted card in #votes, or record in #proposals."""

    def __init__(self, id):
        self.id = id
        self.jump_url = f"https://discord.com/channels/99/6/{id}"
        self.edits, self.deleted = [], False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def delete(self):
        self.deleted = True


class Thread:
    """A proposal's thread under its card."""

    def __init__(self):
        self.id = 61
        self.said, self.archived = [], False

    async def send(self, text, **kwargs):
        self.said.append(text)

    async def edit(self, archived=False):
        self.archived = archived


class Ending(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.card, self.record = Message(60), Message(70)
        self.votes = types.SimpleNamespace(
            id=6, send=mock.AsyncMock(return_value=self.card),
            fetch_message=mock.AsyncMock(return_value=self.card))
        self.records = types.SimpleNamespace(
            id=5, send=mock.AsyncMock(return_value=self.record),
            fetch_message=mock.AsyncMock(return_value=self.record))
        self.thread = Thread()
        self.channels = {6: self.votes, 5: self.records, 61: self.thread}
        self.guild = object()
        self.client = types.SimpleNamespace(
            get_channel=self.channels.get, get_guild=lambda gid: self.guild,
            fetch_channel=mock.AsyncMock(side_effect=discord.NotFound(mock.Mock(), "")))
        self.logged = []

        async def server_log(guild, text):
            self.logged.append(text)

        self.patches = [
            mock.patch.object(layout, "channel",
                              lambda guild, name: self.records if name == "proposals"
                              else self.votes),
            mock.patch.object(layout, "server_log", server_log),
            mock.patch.object(layout, "post_texts", mock.AsyncMock()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def posted(self, p):
        """As if `p` had been put to a vote: its card is up in #votes, with
        its thread."""
        proposals.attach_message(p["no"], self.votes.id, self.card.id)
        return proposals.record(p["no"], thread_id=self.thread.id)

    def shown(self):
        """What the record in #proposals says now."""
        embed = (self.record.edits[-1]["embed"] if self.record.edits
                 else self.records.send.call_args.kwargs["embed"])
        return embed.description

    def vote(self, no, yes=0, no_votes=0):
        for voter in range(10, 10 + yes):
            proposals.cast(no, voter, VETERAN, "yes", NOW + 60)
        for voter in range(50, 50 + no_votes):
            proposals.cast(no, voter, VETERAN, "no", NOW + 60)

    async def test_a_passed_vote_is_carried_out_and_recorded_in_proposals(self):
        p = self.posted(setting_changes.KIND.open(1, "voting_hours", 48, "", NOW))
        self.vote(p["no"], yes=5)
        p = await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(settings.current()["voting_hours"], 48)
        self.assertEqual(p["outcome"], "Voting window is now 48 hours.")
        self.assertTrue(self.card.deleted)  # #votes is only what is open
        self.assertEqual((p["channel_id"], p["message_id"]), (5, 70))
        self.assertIn(p["outcome"], self.shown())
        self.assertIn("<#61>", self.shown())  # the discussion stays reachable
        self.assertEqual(self.thread.said,
                         ["Proposal 1 passed (5 yes, 0 no). Voting window is now 48 hours."])
        self.assertTrue(self.thread.archived)
        self.assertEqual(self.logged, [])  # nobody but the vote decided it

    async def test_a_vote_that_fails_or_falls_short_carries_nothing_out(self):
        short = self.posted(setting_changes.KIND.open(1, "voting_hours", 48, "", NOW))
        failed = self.posted(setting_changes.KIND.open(2, "quorum", 8, "", NOW))
        self.vote(short["no"], yes=2)
        self.vote(failed["no"], yes=2, no_votes=3)
        await ending.close(self.client, short["no"], NOW + DAY)
        await ending.close(self.client, failed["no"], NOW + DAY)
        self.assertEqual((settings.current()["voting_hours"], settings.current()["quorum"]),
                         (24, 5))
        self.assertEqual(self.thread.said, [
            "Proposal 1 did not get enough votes to count (2 yes, 0 no; it needed 5).",
            "Proposal 2 failed (2 yes, 3 no)."])

    async def test_a_vote_ends_once(self):
        p = self.posted(code_changes.KIND.open(1, "Trivia", "A game.", NOW))
        self.vote(p["no"], yes=5)
        await ending.close(self.client, p["no"], NOW + DAY)
        await ending.close(self.client, p["no"], NOW + DAY + 60)
        self.assertEqual(len(self.thread.said), 1)
        self.assertIn("written as a code change", self.thread.said[0])
        self.records.send.assert_awaited_once()

    async def test_an_admin_passes_one_logged_before_it_is_carried_out(self):
        order = []

        async def made(guild, action):
            order.append(len(self.logged))
            return "Done: <#2> has its new topic."

        p = actions.KIND.open(ADMIN, {"kind": actions.TOPIC, "channel": "cars",
                                      "topic": "Vroom"}, NOW)
        with mock.patch.object(actions, "carry_out", made):
            p, said = await ending.pass_now(self.client, self.guild, p["no"], ADMIN, NOW)
        self.assertEqual((p["status"], p["shipped_by"]), (proposals.PASSED, ADMIN))
        self.assertEqual(said, "Done: <#2> has its new topic.")
        self.votes.send.assert_not_awaited()  # never put to a vote
        self.records.send.assert_awaited_once()  # recorded, already passed
        self.assertEqual(self.logged[0], f"<@{ADMIN}> passed proposal 1 (New topic for cars) "
                                         f"without a vote, as an admin: {self.record.jump_url}")
        self.assertEqual(order, [1])
        self.assertIn(said, self.shown())
        self.assertEqual(self.thread.said, [])  # the record says it; no vote to announce
        with self.assertRaisesRegex(proposals.Refused, "closed"):
            await ending.pass_now(self.client, self.guild, p["no"], ADMIN, NOW)

    async def test_a_withdrawn_appeal_frees_the_case_and_says_so_in_mod_log(self):
        case = cases.open_case(NOW, user_id=8, action=cases.WARN, rule=1, severity="minor",
                               explanation="Rude.", excerpt="x", decided_by=judge.FIRST_CHECK)
        p = self.posted(appeals.KIND.open(9, case["no"], "A mistake.", NOW))
        notes = []

        async def note(guild, case, text):
            notes.append(text)

        with mock.patch.object(appeals, "_note", note):
            p = await ending.withdraw(self.client, self.guild, p["no"], ADMIN, "Duplicate", NOW)
        self.assertEqual(p["status"], proposals.WITHDRAWN)
        self.assertIsNone(cases.get(case["no"])["appeal"])
        self.assertIn("appealed again", notes[0])
        self.assertEqual(self.logged,
                         [f"<@{ADMIN}> withdrew proposal 1 ({p['title']}) as an admin: "
                          "Duplicate"])
        self.assertIn("Duplicate", self.shown())
        self.assertTrue(self.card.deleted)
        self.assertEqual(self.thread.said, [])
        self.assertTrue(self.thread.archived)

    async def test_a_failure_carrying_it_out_still_gets_its_result_posted(self):
        p = self.posted(actions.KIND.open(1, {"kind": actions.TOPIC, "channel": "cars",
                                              "topic": "Vroom"}, NOW))
        self.vote(p["no"], yes=5)
        with mock.patch.object(actions, "carry_out", mock.AsyncMock(side_effect=KeyError)):
            p = await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(p["status"], proposals.PASSED)
        self.assertEqual(self.thread.said,
                         ["Proposal 1 passed (5 yes, 0 no). The bot couldn't carry it out."])

    async def test_a_card_that_is_gone_stops_nothing_else(self):
        p = setting_changes.KIND.open(1, "quorum", 8, "", NOW)
        proposals.attach_message(p["no"], 404, 60)
        self.vote(p["no"], yes=5)
        await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(settings.current()["quorum"], 8)
        self.records.send.assert_awaited_once()

    async def test_a_card_from_before_votes_had_a_channel_becomes_the_record(self):
        p = setting_changes.KIND.open(1, "quorum", 8, "", NOW)
        proposals.attach_message(p["no"], self.records.id, self.card.id)
        self.records.fetch_message.return_value = self.card
        self.channels[self.card.id] = self.thread  # its thread has the card's id
        self.vote(p["no"], yes=5)
        p = await ending.close(self.client, p["no"], NOW + DAY)
        self.records.send.assert_not_awaited()
        self.assertFalse(self.card.deleted)
        self.assertIsNone(self.card.edits[0]["view"])  # the vote buttons go
        self.assertEqual(p["thread_id"], self.card.id)
        self.assertEqual(len(self.thread.said), 1)


class Kinds(unittest.TestCase):
    def test_every_kind_of_proposal_is_registered(self):
        self.assertEqual(set(kinds.KINDS), {proposals.GENERAL, proposals.SETTING,
                                            proposals.ACTION, proposals.APPEAL})


class Words(unittest.TestCase):
    def closed(self, kind, status, yes, no, **fields):
        return {"kind": kind, "no": 4, "status": status, "quorum": 5,
                "totals": {"yes": yes, "no": no}, **fields}

    def test_a_result_says_the_count_in_the_kinds_words_and_what_came_of_it(self):
        appeal = self.closed(proposals.APPEAL, proposals.PASSED, 4, 1,
                             outcome="Case 2 is overturned.")
        self.assertEqual(cards.result(appeal),
                         "Proposal 4 passed (4 overturn, 1 keep). Case 2 is overturned.")
        short = self.closed(proposals.GENERAL, proposals.NO_QUORUM, 1, 1)
        self.assertEqual(cards.result(short), "Proposal 4 did not get enough votes to count "
                                              "(1 yes, 1 no; it needed 5).")

    def test_a_result_fits_in_a_message(self):
        long = self.closed(proposals.ACTION, proposals.PASSED, 5, 0, outcome="x" * 3000)
        self.assertLessEqual(len(cards.result(long)), 2000)


if __name__ == "__main__":
    unittest.main()
