"""The 🚩 reaction: which flags reach the moderator, against fake Discord
objects. No network and no Discord server.

    python -m unittest test_flags
"""

import shutil
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import discord

import cases
import flags
import layout
import moderator
import store

HOME = 99


def person(member_id, bot=False):
    member = mock.Mock(spec=discord.Member)
    member.id, member.bot = member_id, bot
    member.send = mock.AsyncMock()
    return member


class Reactions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        flags._flagged.clear()
        flags._judged.clear()
        self.handled = []
        self.removed = []
        self.flagger = person(1)
        self.author = person(2)
        self.message = types.SimpleNamespace(
            id=500, author=self.author, content="ya 7mar",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=3))
        partial = types.SimpleNamespace(remove_reaction=mock.AsyncMock(
            side_effect=lambda emoji, member: self.removed.append((emoji, member.id))))
        self.channel = types.SimpleNamespace(
            get_partial_message=mock.Mock(return_value=partial),
            fetch_message=mock.AsyncMock(side_effect=lambda _: self.message))
        guild = types.SimpleNamespace(get_channel_or_thread=mock.Mock(
            return_value=self.channel))
        self.client = types.SimpleNamespace(get_guild=mock.Mock(return_value=guild))
        self.patches = [
            mock.patch.object(layout, "home_id", mock.Mock(return_value=HOME)),
            mock.patch.object(moderator, "handle_flag", mock.AsyncMock(
                side_effect=lambda message: self.handled.append(message.id))),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def react(self, emoji=flags.FLAG, flagger=None, guild_id=HOME, message_id=500):
        payload = types.SimpleNamespace(
            emoji=emoji, guild_id=guild_id, channel_id=40, message_id=message_id,
            member=flagger or self.flagger)
        await flags.on_reaction(payload, self.client)

    async def test_a_flag_reaches_the_moderator_and_comes_off_at_once(self):
        await self.react()
        self.assertEqual(self.handled, [500])
        self.assertEqual(self.removed, [(flags.FLAG, 1)])  # nobody sees who flagged

    async def test_other_reactions_and_other_servers_are_ignored(self):
        await self.react(emoji="👍")
        await self.react(guild_id=HOME + 1)
        self.assertEqual((self.handled, self.removed), ([], []))

    async def test_bots_own_messages_and_the_bots_flags_are_ignored(self):
        await self.react(flagger=person(3, bot=True))
        self.message.author = person(4, bot=True)
        await self.react()
        self.message.author = self.flagger
        await self.react()
        self.assertEqual(self.handled, [])

    async def test_a_message_is_judged_once(self):
        await self.react()
        await self.react(flagger=person(5))
        self.assertEqual(self.handled, [500])

    async def test_a_message_with_a_case_already_is_left_alone(self):
        cases.open_case(int(time.time()), user_id=2, action=cases.WARN, minutes=0,
                        message_id=500)
        await self.react()
        self.assertEqual(self.handled, [])

    async def test_old_messages_cant_be_flagged(self):
        self.message.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        await self.react()
        self.assertEqual(self.handled, [])

    async def test_each_member_can_flag_a_few_an_hour(self):
        for n in range(flags.PER_WINDOW + 1):
            self.message.id = 600 + n
            await self.react(message_id=600 + n)
        self.assertEqual(len(self.handled), flags.PER_WINDOW)
        self.assertIn("Give it a little while", self.flagger.send.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
