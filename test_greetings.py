"""The daily greeting: the first time a member posts in the greeting
channel on a given day, the bot replies "ija el batal". Fake Discord
objects and a temporary data directory; no network.

    python -m unittest
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import discord

import greetings
import store

MORNING = datetime(2026, 9, 26, 9, 0, tzinfo=timezone.utc)      # daytime in Beirut
EVENING = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)     # later the same day
NEXT_MORNING = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)


class WithTempData(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)


class OnceADay(WithTempData, unittest.TestCase):
    def test_the_first_greeting_of_the_day_comes_once(self):
        self.assertFalse(greetings.greeted(7, MORNING))
        self.assertTrue(greetings.greeted(7, EVENING))

    def test_each_member_is_greeted_on_their_own(self):
        self.assertFalse(greetings.greeted(7, MORNING))
        self.assertFalse(greetings.greeted(8, EVENING))

    def test_the_next_day_greets_again(self):
        self.assertFalse(greetings.greeted(7, MORNING))
        self.assertTrue(greetings.greeted(7, EVENING))
        self.assertFalse(greetings.greeted(7, NEXT_MORNING))

    def test_a_day_is_the_day_in_beirut(self):
        # These fall before and after Beirut's midnight, clear of it.
        self.assertFalse(greetings.greeted(7, datetime(2026, 9, 26, 18, 0,
                                                      tzinfo=timezone.utc)))
        self.assertFalse(greetings.greeted(7, datetime(2026, 9, 26, 23, 0,
                                                      tzinfo=timezone.utc)))


class Replying(WithTempData, unittest.IsolatedAsyncioTestCase):
    def post(self, channel_id=greetings.CHANNEL_ID, author_id=7, bot=False,
             content="sabah el nouwar", attachments=()):
        message = mock.create_autospec(discord.Message, instance=True)
        message.author = mock.Mock(spec=discord.Member, id=author_id, bot=bot)
        message.channel = mock.Mock(spec=discord.TextChannel, id=channel_id)
        message.content = content
        message.attachments = list(attachments)
        return message

    async def test_the_first_message_of_the_day_is_greeted(self):
        message = self.post()
        await greetings.on_message(message, MORNING)
        message.reply.assert_awaited_once_with("ija el batal", mention_author=False)

    async def test_the_rest_of_the_day_is_left_alone(self):
        first, second = self.post(), self.post()
        await greetings.on_message(first, MORNING)
        await greetings.on_message(second, EVENING)
        first.reply.assert_awaited_once()
        second.reply.assert_not_awaited()

    async def test_it_only_greets_in_that_channel(self):
        message = self.post(channel_id=2)
        await greetings.on_message(message, MORNING)
        message.reply.assert_not_awaited()

    async def test_a_bot_is_not_greeted(self):
        message = self.post(bot=True)
        await greetings.on_message(message, MORNING)
        message.reply.assert_not_awaited()

    async def test_an_empty_message_is_not_a_post(self):
        message = self.post(content="  ")
        await greetings.on_message(message, MORNING)
        message.reply.assert_not_awaited()

    async def test_an_attachment_counts_as_a_post(self):
        message = self.post(content="", attachments=[mock.Mock(spec=discord.Attachment)])
        await greetings.on_message(message, MORNING)
        message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
