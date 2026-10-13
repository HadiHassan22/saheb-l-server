"""Checks for how a proposal looks (cards.py): its card in #votes is short,
mentions the Proposal role when a vote opens and gets a thread with the
full text; its record in #proposals says how it ended in a few lines; and
its thread is told the result and archived. Fake Discord objects; no
network.

    python -m unittest
"""

import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import cards
import code_changes
import proposals
import store

NOW = 1_800_000_000


class WithTempData(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)


class Post(WithTempData):
    def setUp(self):
        super().setUp()
        self.p = code_changes.KIND.open(3, "Ping", "Ping voters.", NOW)
        self.thread = mock.create_autospec(discord.Thread, instance=True)
        self.thread.id = 61
        self.message = mock.create_autospec(discord.Message, instance=True)
        self.message.id = 60
        self.message.create_thread.return_value = self.thread
        self.votes = mock.create_autospec(discord.TextChannel, instance=True)
        self.votes.id = 6
        self.votes.send.return_value = self.message

    async def test_a_vote_that_opens_mentions_the_proposal_role(self):
        await cards.post(self.p, self.votes, ping=True)

        content = self.votes.send.call_args.args[0]
        allowed = self.votes.send.call_args.kwargs["allowed_mentions"].to_dict()
        self.assertEqual(content, f"<@&{cards.PROPOSAL_ROLE_ID}>")
        self.assertEqual(allowed["roles"], [cards.PROPOSAL_ROLE_ID])
        self.assertEqual(allowed["parse"], [])

    async def test_a_card_posted_without_a_vote_mentions_nobody(self):
        await cards.post(self.p, self.votes)

        self.assertIsNone(self.votes.send.call_args.args[0])
        self.assertIsNone(self.votes.send.call_args.kwargs["allowed_mentions"])

    async def test_each_vote_has_its_own_thread(self):
        await cards.post(self.p, self.votes)

        p = proposals.get(self.p["no"])
        self.assertEqual((p["channel_id"], p["message_id"], p["thread_id"]), (6, 60, 61))
        self.thread.send.assert_not_awaited()  # the card already shows all of it

    async def test_a_long_proposal_is_cut_short_on_its_card_and_in_full_in_its_thread(self):
        details = "word " * 1000
        p = code_changes.KIND.open(3, "Long", details, NOW)
        await cards.post(p, self.votes)

        shown = self.votes.send.call_args.kwargs["embed"].description
        self.assertLess(len(shown), cards.CARD_TEXT + 200)
        said = "".join(call.args[0] for call in self.thread.send.call_args_list)
        self.assertEqual(said, details.strip())
        self.assertTrue(all(len(call.args[0]) <= 2000
                            for call in self.thread.send.call_args_list))

    async def test_a_thread_that_fails_still_leaves_the_vote_up(self):
        self.message.create_thread.side_effect = discord.HTTPException(
            mock.Mock(status=403), "no")

        message = await cards.post(self.p, self.votes)

        self.assertIs(message, self.message)
        self.assertNotIn("thread_id", proposals.get(self.p["no"]))


class Looks(WithTempData):
    def test_an_open_card_is_short_and_has_no_fields(self):
        p = code_changes.KIND.open(3, "Ping", "Ping voters. " * 100, NOW)
        embed = cards.card(p)
        self.assertEqual(embed.fields, [])
        self.assertIn("0 yes · 0 no", embed.description)
        self.assertIn("closes <t:", embed.description)
        self.assertLess(len(embed.description), 500)

    def test_a_record_says_how_it_ended_where_its_code_is_and_links_its_thread(self):
        p = code_changes.KIND.open(3, "Ping", "Ping voters. " * 100, NOW)
        p = proposals.record(proposals.close(p["no"], NOW + 2 * proposals.DAY)["no"],
                             thread_id=61, outcome="It will be written as code.",
                             progress="live", summary="Votes now ping the role.")
        shown = cards.card(p).description
        self.assertIn("**Not enough votes**: 0 yes · 0 no", shown)
        self.assertIn("It will be written as code.", shown)
        self.assertIn("**Code change:** live", shown)
        self.assertIn("Votes now ping the role.", shown)
        self.assertIn("<#61>", shown)
        self.assertLess(len(shown), 400)


class Thread(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.thread = types.SimpleNamespace(id=61, send=mock.AsyncMock(), edit=mock.AsyncMock())
        self.client = types.SimpleNamespace(
            get_channel={61: self.thread}.get,
            fetch_channel=mock.AsyncMock(side_effect=discord.NotFound(mock.Mock(), "gone")))

    async def test_the_result_is_said_and_the_thread_archived(self):
        await cards.close_thread(self.client, {"no": 1, "thread_id": 61}, "Passed.")
        self.thread.send.assert_awaited_once()
        self.thread.edit.assert_awaited_once_with(archived=True)

    async def test_a_thread_that_is_gone_stops_nothing(self):
        await cards.close_thread(self.client, {"no": 1, "thread_id": 404}, "Passed.")
        await cards.close_thread(self.client, {"no": 1}, "Passed.")
        self.thread.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
