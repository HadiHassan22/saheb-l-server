"""Checks for how a proposal's card is posted (cards.py): a vote that opens
mentions the Proposal role, and posting anything else mentions nobody. Fake
Discord objects; no network.

    python -m unittest
"""

import unittest
from unittest import mock

import discord

import cards
import proposals


class Post(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = mock.create_autospec(discord.Message, instance=True)
        self.message.id = 60
        self.channel = mock.create_autospec(discord.TextChannel, instance=True)
        self.channel.id = 6
        self.channel.send.return_value = self.message
        for patch in (mock.patch.object(cards, "card", return_value=mock.Mock(spec=discord.Embed)),
                      mock.patch.object(proposals, "attach_message")):
            patch.start()
            self.addCleanup(patch.stop)

    async def test_a_vote_that_opens_mentions_the_proposal_role(self):
        await cards.post({"no": 212, "title": "Ping"}, self.channel, ping=True)

        content = self.channel.send.call_args.args[0]
        allowed = self.channel.send.call_args.kwargs["allowed_mentions"].to_dict()
        self.assertEqual(content, f"<@&{cards.PROPOSAL_ROLE_ID}>")
        self.assertEqual(allowed["roles"], [cards.PROPOSAL_ROLE_ID])
        self.assertEqual(allowed["parse"], [])

    async def test_a_card_posted_without_a_vote_mentions_nobody(self):
        await cards.post({"no": 212, "title": "Ping"}, self.channel)

        self.assertIsNone(self.channel.send.call_args.args[0])
        self.assertIsNone(self.channel.send.call_args.kwargs["allowed_mentions"])


if __name__ == "__main__":
    unittest.main()
