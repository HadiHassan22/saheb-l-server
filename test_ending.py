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


class Card:
    """A posted proposal card."""

    def __init__(self):
        self.id = 60
        self.jump_url = "https://discord.com/channels/99/6/60"
        self.edits, self.replies = [], []
        self.create_thread = mock.AsyncMock()

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def reply(self, text, **kwargs):
        self.replies.append(text)


class Ending(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.card = Card()
        self.channel = types.SimpleNamespace(
            id=6, send=mock.AsyncMock(return_value=self.card),
            fetch_message=mock.AsyncMock(return_value=self.card))
        self.guild = object()
        self.client = types.SimpleNamespace(get_channel=lambda cid: self.channel,
                                            get_guild=lambda gid: self.guild)
        self.logged = []

        async def server_log(guild, text):
            self.logged.append(text)

        self.patches = [
            mock.patch.object(layout, "channel", lambda guild, name: self.channel),
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
        """As if `p` had been put to a vote: its card is up."""
        return proposals.attach_message(p["no"], self.channel.id, self.card.id)

    def vote(self, no, yes=0, no_votes=0):
        for voter in range(10, 10 + yes):
            proposals.cast(no, voter, VETERAN, "yes", NOW + 60)
        for voter in range(50, 50 + no_votes):
            proposals.cast(no, voter, VETERAN, "no", NOW + 60)

    async def test_a_passed_vote_is_carried_out_and_its_result_said_under_the_card(self):
        p = self.posted(setting_changes.KIND.open(1, "voting_hours", 48, "", NOW))
        self.vote(p["no"], yes=5)
        p = await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(settings.current()["voting_hours"], 48)
        self.assertEqual(p["outcome"], "Voting window is now 48 hours.")
        self.assertIsNone(self.card.edits[0]["view"])  # the vote buttons go
        self.assertEqual(self.card.edits[-1]["embed"].fields[-1].value, p["outcome"])
        self.assertEqual(self.card.replies,
                         ["Proposal 1 passed (5 yes, 0 no). Voting window is now 48 hours."])
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
        self.assertEqual(self.card.replies, [
            "Proposal 1 did not get enough votes to count (2 yes, 0 no; it needed 5).",
            "Proposal 2 failed (2 yes, 3 no)."])

    async def test_a_vote_ends_once(self):
        p = self.posted(code_changes.KIND.open(1, "Trivia", "A game.", NOW))
        self.vote(p["no"], yes=5)
        await ending.close(self.client, p["no"], NOW + DAY)
        await ending.close(self.client, p["no"], NOW + DAY + 60)
        self.assertEqual(len(self.card.replies), 1)
        self.assertIn("written as a code change", self.card.replies[0])

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
        self.channel.send.assert_awaited_once()  # its card is posted, already passed
        self.assertEqual(self.logged[0], f"<@{ADMIN}> passed proposal 1 (New topic for cars) "
                                         f"without a vote, as an admin: {self.card.jump_url}")
        self.assertEqual(order, [1])
        self.assertEqual(self.card.replies, [])  # the card says it; no vote to announce
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
        self.assertEqual(self.card.edits[0]["embed"].fields[-1].value, "Duplicate")
        self.assertEqual(self.card.replies, [])

    async def test_a_failure_carrying_it_out_still_gets_its_result_posted(self):
        p = self.posted(actions.KIND.open(1, {"kind": actions.TOPIC, "channel": "cars",
                                              "topic": "Vroom"}, NOW))
        self.vote(p["no"], yes=5)
        with mock.patch.object(actions, "carry_out", mock.AsyncMock(side_effect=KeyError)):
            p = await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(p["status"], proposals.PASSED)
        self.assertEqual(self.card.replies,
                         ["Proposal 1 passed (5 yes, 0 no). The bot couldn't carry it out."])

    async def test_a_card_that_is_gone_stops_nothing_else(self):
        p = setting_changes.KIND.open(1, "quorum", 8, "", NOW)
        proposals.attach_message(p["no"], 404, 60)
        self.client.get_channel = lambda cid: None
        self.vote(p["no"], yes=5)
        await ending.close(self.client, p["no"], NOW + DAY)
        self.assertEqual(settings.current()["quorum"], 8)


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
