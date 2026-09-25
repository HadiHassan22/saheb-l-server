"""Checks for pickers in #roles: making, changing and removing them as a
server change, and what picking does. Fake Discord objects; no network.

    python -m unittest
"""

import shutil
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import discord

import actions
import ai
import assistant
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
        # No AI unless a test gives it an answer: the bot's groups stay as they are.
        self.review = mock.AsyncMock(side_effect=ai.Unavailable("no key"))
        self._ai = mock.patch.object(ai, "review", self.review)
        self._ai.start()

    def tearDown(self):
        self._ai.stop()
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
        self.assertEqual(pickers.made_by_members(), [])
        # Its roles stay, and can still be taken, in the Opt-in roles picker.
        self.assertEqual(pickers.find(pickers.OPT_IN)["roles"], [10, self.roles[-1].id])

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


class OptIn(WithGuild):
    """Every role members can join is in a picker in #roles."""

    def auto(self):
        return [p for p in pickers.all_pickers() if p.get("auto")]

    async def test_a_new_opt_in_role_can_be_taken_in_roles_at_once(self):
        await self.carry_out(kind=actions.ROLE_CREATE, name="Gamers")
        picker = pickers.find(pickers.OPT_IN)
        self.assertEqual((picker["roles"], picker["one"]), ([self.roles[-1].id, 10], False))
        options = self.messages[-1].sent[1]["view"].children[0].item.options
        self.assertEqual([o.label for o in options], ["Gamers", "Lebanese", "None of these"])
        self.assertIn("Some open a channel", self.messages[-1].sent[0])

    async def test_a_role_leaves_it_when_another_picker_offers_it_or_it_closes(self):
        await actions.offer_opt_in(self.guild)
        self.assertEqual(pickers.find(pickers.OPT_IN)["roles"], [10])
        await self.carry_out(kind=actions.PICKER_CREATE, title="From", roles=["Lebanese"])
        self.assertEqual(self.auto(), [])  # Lebanese is offered by From now
        self.messages[0].delete.assert_awaited_once()
        await self.carry_out(kind=actions.ROLE_CREATE, name="Gamers")
        await self.carry_out(kind=actions.ROLE_EDIT, role="Gamers", joinable=False)
        self.assertEqual(self.auto(), [])

    async def test_more_roles_than_a_dropdown_holds_make_a_second_picker(self):
        store.save("roles", {str(200 + n): {"joinable": True} for n in range(30)})
        self.roles.extend(role(200 + n, f"Role {n:02}") for n in range(30))
        await actions.offer_opt_in(self.guild)
        titles = sorted((p["title"], len(p["roles"])) for p in self.auto())
        self.assertEqual(titles, [(pickers.OPT_IN, 24), (f"{pickers.OPT_IN} (2)", 6)])

    async def test_the_bots_own_picker_cant_be_changed_directly(self):
        await actions.offer_opt_in(self.guild)
        problem = await actions.check(self.guild, {"kind": actions.PICKER_DELETE,
                                                   "picker": pickers.OPT_IN})
        self.assertIn("keeps", problem)


class Grouping(WithGuild):
    """A new role goes in the picker it belongs to, made the first time."""

    async def test_a_gamer_role_then_movie_night_both_land_in_interests(self):
        said, action = await self.carry_out(kind=actions.ROLE_CREATE, name="Gamer",
                                            picker="Interests")
        self.assertIn("in the Interests picker", said)
        self.assertIn("made with it", actions.describe(action)[1])
        gamer = self.roles[-1]
        self.assertTrue(gamer.created_with["mentionable"])  # members can ping it
        await self.carry_out(kind=actions.ROLE_CREATE, name="Movie night", picker="interests")
        interests = pickers.find("Interests")
        self.assertEqual((interests["roles"], interests["one"]),
                         ([gamer.id, self.roles[-1].id], False))
        self.assertEqual(len(pickers.made_by_members()), 1)
        self.assertNotIn(gamer.id, pickers.find(pickers.OPT_IN)["roles"])

    async def test_a_new_kind_of_role_starts_its_own_pick_one_picker(self):
        await self.carry_out(kind=actions.ROLE_CREATE, name="Gamer", picker="Interests")
        await self.carry_out(kind=actions.ROLE_CREATE, name="+18", picker="Age", one=True)
        await self.carry_out(kind=actions.ROLE_CREATE, name="-18", picker="Age")
        age = pickers.find("Age")
        self.assertEqual((len(age["roles"]), age["one"]), (2, True))
        self.assertEqual(sorted(p["title"] for p in pickers.made_by_members()),
                         ["Age", "Interests"])

    async def test_a_role_nobody_joins_goes_in_no_picker(self):
        said, _ = await self.carry_out(kind=actions.ROLE_CREATE, name="Staff",
                                       joinable=False, picker="Interests")
        self.assertNotIn("picker", said)
        self.assertIsNone(pickers.find("Interests"))

    def test_the_bot_is_told_which_pickers_exist(self):
        pickers.save({"title": "Interests", "roles": [1, 2], "one": False, "message_id": None})
        prompt = assistant.system(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertIn("Pickers in #roles now: Interests (pick any, 2 roles).", prompt)


class SmartGroups(WithGuild):
    """Roles in no picker are grouped the way a person would group them."""

    def setUp(self):
        super().setUp()
        self.male, self.female, self.gamer = role(20, "Male"), role(21, "Female"), role(22, "Gamer")
        self.roles.extend([self.male, self.female, self.gamer])
        store.save("roles", {str(r): {"joinable": True} for r in (10, 20, 21, 22)})

    def auto(self):
        return {p["title"]: (p["roles"], p["one"]) for p in pickers.all_pickers()
                if p.get("auto")}

    async def test_male_and_female_go_in_a_pick_one_gender_picker(self):
        # Roles are numbered by name: Female, Gamer, Lebanese, Male.
        self.review.side_effect = None
        self.review.return_value = {"groups": [{"title": "Gender", "one": True,
                                                "roles": [1, 4]}]}
        await actions.offer_opt_in(self.guild)
        self.assertEqual(self.auto(), {"Gender": ([21, 20], True),
                                       pickers.OPT_IN: ([22, 10], False)})
        prompt = self.review.call_args.args[0]
        self.assertIn("1. Female", prompt)
        self.assertIn("Pick one.", [m.sent[0] for m in self.messages][0])
        await actions.offer_opt_in(self.guild)  # nothing changed: the AI isn't asked again
        self.assertEqual(self.review.await_count, 1)

    async def test_without_the_ai_new_roles_go_in_opt_in_and_groups_stay(self):
        await actions.offer_opt_in(self.guild)
        self.assertEqual(self.auto(), {pickers.OPT_IN: ([21, 22, 10, 20], False)})
        store.save("groups", {"roles": [21, 22, 10, 20], "groups": [
            {"title": "Gender", "one": True, "roles": [21, 20]}]})
        self.roles.append(role(23, "Chess"))
        store.save("roles", {str(r): {"joinable": True} for r in (10, 20, 21, 22, 23)})
        await actions.offer_opt_in(self.guild)
        self.assertEqual(self.auto(), {"Gender": ([21, 20], True),
                                       pickers.OPT_IN: ([23, 22, 10], False)})
        self.assertEqual(self.review.await_count, 2)  # tried each time: nothing remembered

    def test_the_ais_groups_are_checked(self):
        answer = {"groups": [
            {"title": "Gender", "one": True, "roles": [1, 4, 4]},
            {"title": "Solo", "one": False, "roles": [2]},          # one role: no group
            {"title": "From", "one": True, "roles": [3, 9]},        # 9 doesn't exist
            {"title": "Taken", "one": False, "roles": [2, 3]},      # a member's title
            {"title": "Again", "one": False, "roles": [1, 2]},      # 1 is in Gender
            {"title": " ", "one": False, "roles": [2, 3]},
        ]}
        self.assertEqual(pickers._groups(answer, 4, ["taken"]), [("Gender", True, [0, 3])])
        self.assertEqual(pickers._groups({"groups": None}, 4, []), [])

    async def test_changing_a_bots_group_makes_it_the_members(self):
        store.save("groups", {"roles": [21, 22, 10, 20], "groups": [
            {"title": "Gender", "one": True, "roles": [21, 20]}]})
        await actions.offer_opt_in(self.guild)
        self.assertIn("keeps", await actions.check(self.guild, {
            "kind": actions.PICKER_DELETE, "picker": "Gender"}))
        await self.carry_out(kind=actions.PICKER_EDIT, picker="Gender", title="Gender?")
        self.assertEqual([p["title"] for p in pickers.made_by_members()], ["Gender?"])
        self.assertEqual(list(self.auto()), [pickers.OPT_IN])

    async def test_a_new_role_named_for_a_bots_group_joins_it(self):
        store.save("groups", {"roles": [21, 22, 10, 20], "groups": [
            {"title": "Gender", "one": True, "roles": [21, 20]}]})
        await actions.offer_opt_in(self.guild)
        said, _ = await self.carry_out(kind=actions.ROLE_CREATE, name="Non-binary",
                                       picker="gender")
        self.assertIn("in the Gender picker", said)
        gender = pickers.find("Gender")
        self.assertEqual((gender["roles"][-1], gender["one"], gender.get("auto")),
                         (self.roles[-1].id, True, None))

    def test_the_bot_is_told_about_its_own_groups(self):
        pickers.save({"title": "Gender", "roles": [20, 21], "one": True, "auto": True,
                      "message_id": None})
        prompt = assistant.system(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertIn("Gender (pick one, 2 roles)", prompt)


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
