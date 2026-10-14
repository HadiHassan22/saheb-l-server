"""The av command: the mentioned member's avatar, or the sender's own when
no one is mentioned. Fake Discord objects; no network.

    python -m unittest
"""

import unittest
from unittest import mock

import discord
from discord import app_commands

import avatars


def member(name, avatar_url):
    person = mock.create_autospec(discord.Member, instance=True)
    person.display_name = name
    person.display_avatar = mock.create_autospec(discord.Asset, instance=True)
    person.display_avatar.url = avatar_url
    return person


def interaction(sender):
    sent = mock.create_autospec(discord.Interaction, instance=True)
    sent.user = sender
    sent.response = mock.create_autospec(discord.InteractionResponse, instance=True)
    return sent


class Showing(unittest.IsolatedAsyncioTestCase):
    async def test_without_a_mention_the_senders_own_avatar_is_shown(self):
        sender = member("Layla", "https://cdn.example/layla.png")
        sent = interaction(sender)
        await avatars.av.callback(sent, None)
        embed = sent.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(embed.image.url, "https://cdn.example/layla.png")
        self.assertEqual(embed.title, "Layla's avatar")

    async def test_a_mention_shows_that_members_avatar(self):
        sender = member("Layla", "https://cdn.example/layla.png")
        other = member("Karim", "https://cdn.example/karim.png")
        sent = interaction(sender)
        await avatars.av.callback(sent, other)
        embed = sent.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(embed.image.url, "https://cdn.example/karim.png")
        self.assertEqual(embed.title, "Karim's avatar")

    async def test_the_reply_is_public(self):
        sent = interaction(member("Layla", "https://cdn.example/layla.png"))
        await avatars.av.callback(sent, None)
        self.assertFalse(sent.response.send_message.await_args.kwargs.get("ephemeral", False))


class Registering(unittest.TestCase):
    def test_it_is_added_to_the_command_tree_as_av(self):
        tree = mock.create_autospec(app_commands.CommandTree, instance=True)
        avatars.setup(tree)
        tree.add_command.assert_called_once_with(avatars.av)
        self.assertEqual(avatars.av.name, "av")


if __name__ == "__main__":
    unittest.main()
