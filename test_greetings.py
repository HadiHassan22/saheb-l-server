"""Checks for the daily greeting: once a day per member, on the first
message in the channel the members chose and nowhere else. Fake Discord
objects and a temporary store; no network.

    python -m unittest
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import discord

import greetings
import store

NOW = 1_800_000_000
TOMORROW = NOW + 2 * 24 * 60 * 60


class Greetings(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def test_each_member_is_greeted_once_a_day(self):
        self.assertTrue(greetings.greet_once(7, NOW))
        self.assertFalse(greetings.greet_once(7, NOW + 60))
        self.assertTrue(greetings.greet_once(8, NOW + 60))
        self.assertTrue(greetings.greet_once(7, TOMORROW))
        self.assertFalse(greetings.greet_once(7, TOMORROW + 60))

    def message(self, channel_id=greetings.CHANNEL, bot=False):
        message = mock.create_autospec(discord.Message, instance=True)
        message.author = mock.create_autospec(discord.Member, instance=True)
        message.author.id, message.author.bot = 7, bot
        message.channel = mock.create_autospec(discord.TextChannel, instance=True)
        message.channel.id = channel_id
        message.guild = mock.create_autospec(discord.Guild, instance=True)
        return message

    async def test_the_bot_says_it_on_the_first_message_of_the_day_only(self):
        message = self.message()
        await greetings.on_message(message)
        message.reply.assert_awaited_once_with(greetings.GREETING, mention_author=False)
        await greetings.on_message(message)
        message.reply.assert_awaited_once()

    async def test_it_only_speaks_in_the_greeting_channel(self):
        elsewhere = self.message(channel_id=1)  # say, #general
        await greetings.on_message(elsewhere)
        elsewhere.reply.assert_not_awaited()
        here = self.message()
        await greetings.on_message(here)
        here.reply.assert_awaited_once()

    async def test_bots_and_direct_messages_are_ignored(self):
        bot = self.message(bot=True)
        await greetings.on_message(bot)
        bot.reply.assert_not_awaited()
        dm = self.message()
        dm.guild = None
        await greetings.on_message(dm)
        dm.reply.assert_not_awaited()
        mine = self.message()
        await greetings.on_message(mine)
        mine.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
