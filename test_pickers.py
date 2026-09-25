"""Checks for pickers in #roles: making, changing and removing them as a
server change, and what picking does. Fake Discord objects; no network.

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
import layout
import pickers
import quick
import store


def role(id, name):
    r = mock.Mock(spec=discord.Role)
    r.id, r.name = id, name
    r.edit, r.delete = mock.AsyncMock(), mock.AsyncMock()
    return r


class Target:
    """Something a channel override can be for, like @everyone."""

    def __init__(self, id):
        self.id = id


class Message:
    def __init__(self, id):
        self.id = id
        self.sent = self.edited = None
        self.delete = mock.AsyncMock()

    async def edit(self, **kwargs):
        self.edited = kwargs


class WithGuild(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.lebanese = role(10, "Lebanese")
        self.teal = role(11, "Teal")  # a name color: not made by vote
        self.roles = [self.lebanese, self.teal]
        store.save("roles", {"10": {"joinable": True}})
        self.messages = []

        async def create_role(name, **kwargs):
            made = role(100 + len(self.roles), name)
            made.created_with = kwargs
            self.roles.append(made)
            return made

        async def send(text, **kwargs):
            message = Message(500 + len(self.messages))
            message.sent = (text, kwargs)
            self.messages.append(message)
            return message

        async def fetch_message(message_id):
            found = next((m for m in self.messages if m.id == message_id), None)
            if found is None:
                raise discord.NotFound(mock.Mock(status=404), "gone")
            return found

        self.channel = types.SimpleNamespace(send=send, fetch_message=fetch_message)
        self.guild = types.SimpleNamespace(
            roles=self.roles, create_role=create_role, get_role=lambda rid: next(
                (r for r in self.roles if r.id == rid), None))
        self._layout = mock.patch.object(layout, "channel", lambda g, name: self.channel)
        self._layout.start()

    def tearDown(self):
        self._layout.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def carry_out(self, **action):
        problem = await actions.check(self.guild, action)
        self.assertIsNone(problem)
        return await actions.carry_out(self.guild, action), action


class Making(WithGuild):
    async def test_a_picker_makes_its_new_roles_and_is_posted_in_roles(self):
        said, action = await self.carry_out(kind=actions.PICKER_CREATE,
                                            title="Where are you from?",
                                            roles=["Lebanese", "International"], one=True)
        self.assertIn("is in #roles", said)
        self.assertEqual(action["new_roles"], ["International"])
        made = self.roles[-1]
        self.assertEqual(made.created_with["permissions"], discord.Permissions.none())
        self.assertTrue(actions.voted_roles()[made.id]["joinable"])
        picker = pickers.find("where are you from?")
        self.assertEqual((picker["roles"], picker["one"]), ([10, made.id], True))
        select = self.messages[0].sent[1]["view"].children[0].item
        self.assertEqual([o.label for o in select.options],
                         ["Lebanese", "International", "None of these"])
        self.assertEqual(select.max_values, 1)
        title, details = actions.describe(action)
        self.assertIn("Where are you from?", title)
        self.assertIn("giving no powers: International", details)

    async def test_only_roles_made_by_vote_can_be_offered(self):
        action = {"kind": actions.PICKER_CREATE, "title": "Colors", "roles": ["Teal"]}
        self.assertIn("can't give themselves", await actions.check(self.guild, action))
        many = {"kind": actions.PICKER_CREATE, "title": "Games",
                "roles": [f"Game {n}" for n in range(pickers.MAX_ROLES + 1)]}
        self.assertIn("1 to 24", await actions.check(self.guild, many))
        self.assertIn("title", await actions.check(
            self.guild, {"kind": actions.PICKER_CREATE, "roles": ["Lebanese"]}))

    async def test_a_picker_can_be_changed_and_removed_and_its_roles_stay(self):
        await self.carry_out(kind=actions.PICKER_CREATE, title="From", roles=["Lebanese"])
        self.assertIn("already", await actions.check(
            self.guild, {"kind": actions.PICKER_CREATE, "title": "from", "roles": ["X"]}))
        said, _ = await self.carry_out(kind=actions.PICKER_EDIT, picker="From",
                                       roles=["Lebanese", "Syrian"], one=False)
        self.assertIn("From", said)
        edited = self.messages[0].edited["view"].children[0].item
        self.assertEqual((len(edited.options), edited.max_values), (3, 3))
        await self.carry_out(kind=actions.PICKER_DELETE, picker="From")
        self.messages[0].delete.assert_awaited_once()
        self.assertEqual(pickers.all_pickers(), [])
        self.assertIn(10, actions.voted_roles())

    async def test_a_deleted_role_leaves_its_pickers(self):
        await self.carry_out(kind=actions.PICKER_CREATE, title="From",
                             roles=["Lebanese", "Syrian"])
        syrian = self.roles[-1]
        await self.carry_out(kind=actions.ROLE_DELETE, role="Syrian")
        self.roles.remove(syrian)
        self.assertEqual(pickers.find("From")["roles"], [10])


class Access(WithGuild):
    def politics(self):
        everyone = Target(1)
        self.guild.default_role = everyone
        bot = Target(2)
        channel = types.SimpleNamespace(id=30, name="politics-and-religion",
                                        mention="<#30>", overwrites={
                                            bot: discord.PermissionOverwrite(view_channel=True)},
                                        edit=mock.AsyncMock())
        self.guild.channels = [channel]
        self.guild.get_channel = lambda cid: channel if cid == 30 else None
        return channel, everyone, bot

    async def test_an_opt_in_channel_is_seen_only_by_its_role_which_is_made_with_it(self):
        channel, everyone, bot = self.politics()
        with mock.patch.object(actions, "core_ids", lambda g: set()):
            said, action = await self.carry_out(kind=actions.ACCESS,
                                                channel="politics-and-religion",
                                                roles=["Politics and religion"])
        made = self.roles[-1]
        self.assertEqual(made.name, "Politics and religion")
        self.assertEqual(made.created_with["permissions"], discord.Permissions.none())
        self.assertTrue(actions.voted_roles()[made.id]["joinable"])
        overwrites = channel.edit.call_args.kwargs["overwrites"]
        self.assertFalse(overwrites[everyone].view_channel)
        self.assertTrue(overwrites[made].view_channel)
        self.assertTrue(overwrites[bot].view_channel)  # other overrides are kept
        self.assertIn("only members with Politics and religion", said)
        self.assertIn("opt-in", actions.describe(action)[0])

    async def test_no_roles_opens_it_again_and_core_channels_cant_be_hidden(self):
        channel, everyone, _ = self.politics()
        channel.overwrites = {everyone: discord.PermissionOverwrite(view_channel=False),
                              self.lebanese: discord.PermissionOverwrite(view_channel=True)}
        with mock.patch.object(actions, "core_ids", lambda g: set()):
            said, _ = await self.carry_out(kind=actions.ACCESS, channel="politics-and-religion",
                                           roles=[])
        overwrites = channel.edit.call_args.kwargs["overwrites"]
        self.assertIsNone(overwrites[everyone].view_channel)
        self.assertNotIn(self.lebanese, overwrites)
        self.assertIn("everyone can see", said)
        with mock.patch.object(actions, "core_ids", lambda g: {30}):
            self.assertIn("hidden", await actions.check(self.guild, {
                "kind": actions.ACCESS, "channel": "politics-and-religion", "roles": ["X"]}))


class Picking(WithGuild):
    def test_pick_one_swaps_and_pick_several_sets_exactly_the_chosen(self):
        one = {"roles": [1, 2, 3], "one": True}
        self.assertEqual(pickers.changes([1, 9], [2], one), ([2], [1]))
        self.assertEqual(pickers.changes([1, 9], [], one), ([], [1]))
        several = {"roles": [1, 2, 3], "one": False}
        self.assertEqual(pickers.changes([1, 9], [2, 3], several), ([2, 3], [1]))
        self.assertEqual(pickers.changes([], [7], several), ([], []))  # not offered

    async def test_choosing_in_the_dropdown_gives_the_roles(self):
        picker = pickers.save({"title": "From", "roles": [10, 11], "one": True,
                               "message_id": None})
        member = types.SimpleNamespace(roles=[self.teal], add_roles=mock.AsyncMock(),
                                       remove_roles=mock.AsyncMock())
        sent = []
        interaction = types.SimpleNamespace(
            user=member, guild=self.guild, data={"values": ["10"]},
            response=types.SimpleNamespace(send_message=mock.AsyncMock(
                side_effect=lambda text, **k: sent.append(text))))
        await pickers.PickerSelect(picker["no"]).callback(interaction)
        self.assertEqual([o.id for o in member.add_roles.call_args.args], [10])
        self.assertEqual([o.id for o in member.remove_roles.call_args.args], [11])
        self.assertIn("Lebanese", sent[0])

    async def test_joining_by_asking_respects_a_pick_one_picker(self):
        store.save("roles", {"10": {"joinable": True}, "12": {"joinable": True}})
        syrian = role(12, "Syrian")
        self.roles.append(syrian)
        pickers.save({"title": "From", "roles": [10, 12], "one": True, "message_id": None})
        member = types.SimpleNamespace(guild=self.guild, roles=[self.lebanese],
                                       add_roles=mock.AsyncMock(),
                                       remove_roles=mock.AsyncMock())
        said = await quick.join_role(member, "Syrian")
        member.remove_roles.assert_awaited_once_with(self.lebanese,
                                                     reason="Picked another in its picker")
        self.assertIn("left Lebanese", said)


if __name__ == "__main__":
    unittest.main()
