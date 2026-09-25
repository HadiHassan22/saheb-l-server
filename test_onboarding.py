"""Checks for Discord's onboarding: the default page, keeping it in step
with the pickers, and changing it as a server change. Fake Discord
objects; no network.

    python -m unittest
"""

import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import actions
import ai
import assistant
import layout
import onboarding
import pickers
import store

EVERYONE = types.SimpleNamespace(id=1)


def channel(id, name, kind=discord.TextChannel, see=True, send=True):
    made = mock.Mock(spec=kind)
    made.id, made.name = id, name
    made.permissions_for = lambda target: discord.Permissions(view_channel=see,
                                                               send_messages=send)
    return made


def role(id, name):
    made = mock.Mock(spec=discord.Role)
    made.id, made.name = id, name
    return made


class WithGuild(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        # Every planned channel, as the bot builds it.
        self.channels = {}
        for n, (_, rooms) in enumerate(layout.PLAN):
            for m, spec in enumerate(rooms):
                kind = (discord.VoiceChannel if spec["kind"] in (layout.VOICE, layout.AFK)
                        else discord.TextChannel)
                talk = spec["kind"] in (layout.OPEN,)
                self.channels[spec["name"]] = channel(1000 + 100 * n + m, spec["name"],
                                                      kind, send=talk)
        self.roles = [role(10, "Gamer"), role(11, "Teal")]
        store.save("roles", {"10": {"joinable": True}})
        self.guild = types.SimpleNamespace(
            features=["COMMUNITY"], default_role=EVERYONE, roles=self.roles,
            channels=list(self.channels.values()),
            get_channel=lambda cid: next(
                (c for c in self.channels.values() if c.id == cid), None),
            get_role=lambda rid: next((r for r in self.roles if r.id == rid), None),
            edit_onboarding=mock.AsyncMock())
        self._layout = mock.patch.object(layout, "channel",
                                         lambda g, name: self.channels.get(name))
        self._layout.start()
        self._ai = mock.patch.object(ai, "review",
                                     mock.AsyncMock(side_effect=ai.Unavailable("no key")))
        self._ai.start()

    def tearDown(self):
        self._ai.stop()
        self._layout.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def sent(self):
        return self.guild.edit_onboarding.call_args.kwargs

    async def carry_out(self, **action):
        problem = await actions.check(self.guild, action)
        self.assertIsNone(problem)
        return await actions.carry_out(self.guild, action), action


class Defaults(WithGuild):
    async def test_the_default_page_is_a_standard_welcome(self):
        self.assertIsNone(await onboarding.sync(self.guild))
        sent = self.sent()
        self.assertTrue(sent["enabled"])
        self.assertEqual(sent["mode"], discord.OnboardingMode.default)
        names = [c.name for i in sent["default_channels"]
                 if (c := self.guild.get_channel(i.id))]
        self.assertEqual(names, onboarding.DEFAULT_CHANNELS)
        seen = [self.guild.get_channel(i.id) for i in sent["default_channels"]]
        self.assertGreaterEqual(len(seen), onboarding.MIN_CHANNELS)
        self.assertGreaterEqual(sum(onboarding.open_to_talk(self.guild, c) for c in seen),
                                onboarding.MIN_OPEN)
        titles = [p.title for p in sent["prompts"]]
        self.assertEqual(titles, [q[0] for q in onboarding.DEFAULT_QUESTIONS])
        gaming = sent["prompts"][0].options[2]
        self.assertEqual((gaming.title, str(gaming.emoji)), ("Gaming", "🎮"))
        self.assertEqual(gaming.channel_ids, {self.channels[n].id
                                              for n in ("gaming", "Gaming 1", "Gaming 2")})
        self.assertTrue(all(not p.required and p.in_onboarding for p in sent["prompts"]))

    def test_the_defaults_fit_discords_limits(self):
        self.assertLessEqual(len(onboarding.DEFAULT_QUESTIONS), onboarding.MAX_QUESTIONS)
        for title, _, options in onboarding.DEFAULT_QUESTIONS:
            self.assertLessEqual(len(title), onboarding.MAX_TITLE)
            self.assertLessEqual(len(options), 12)  # shown as buttons, not a dropdown
            for name, _, description, channels in options:
                self.assertLessEqual(len(name), onboarding.MAX_OPTION_TITLE)
                self.assertLessEqual(len(description or ""), onboarding.MAX_DESCRIPTION)
                planned = {spec["name"] for _, rooms in layout.PLAN for spec in rooms}
                self.assertTrue(set(channels) <= planned)
        planned = {spec["name"] for _, rooms in layout.PLAN for spec in rooms}
        self.assertTrue(set(onboarding.DEFAULT_CHANNELS) <= planned)

    async def test_nothing_is_written_off_a_community_server(self):
        self.guild.features = []
        self.assertIn("Community", await onboarding.sync(self.guild))
        self.guild.edit_onboarding.assert_not_awaited()


class InStep(WithGuild):
    async def test_every_picker_is_a_question_with_the_same_roles(self):
        pickers.save({"title": "Gender", "roles": [20, 21], "one": True, "message_id": None})
        pickers.save({"title": pickers.OPT_IN, "roles": [10], "one": False, "auto": True,
                      "message_id": None})
        pickers.save({"title": "Gone", "roles": [99], "one": True, "message_id": None})
        self.roles.extend([role(20, "Male"), role(21, "Female")])
        await onboarding.sync(self.guild)
        prompts = {p.title: p for p in self.sent()["prompts"]}
        gender = prompts["Gender"]
        self.assertTrue(gender.single_select)
        self.assertEqual([(o.title, o.role_ids) for o in gender.options],
                         [("Male", {20}), ("Female", {21})])
        self.assertFalse(prompts[pickers.OPT_IN].single_select)
        self.assertNotIn("Gone", prompts)  # no role left to offer
        self.assertEqual(list(prompts)[-1], pickers.OPT_IN)

    async def test_it_is_only_written_when_it_changes(self):
        await onboarding.sync(self.guild)
        await onboarding.sync(self.guild)
        self.assertEqual(self.guild.edit_onboarding.await_count, 1)
        with mock.patch.object(pickers, "show", mock.AsyncMock(return_value=True)):
            await self.carry_out(kind=actions.PICKER_CREATE, title="Play", roles=["Gamer"])
        self.assertEqual(self.guild.edit_onboarding.await_count, 2)
        self.assertIn("Play", [p.title for p in self.sent()["prompts"]])

    async def test_hidden_and_deleted_channels_are_left_out(self):
        self.channels["gaming"].permissions_for = lambda t: discord.Permissions.none()
        del self.channels["pets"]
        await onboarding.sync(self.guild)
        into = self.sent()["prompts"][0]
        self.assertNotIn("Pets", [o.title for o in into.options])
        gaming = next(o for o in into.options if o.title == "Gaming")
        self.assertNotIn(self.channels["gaming"].id, gaming.channel_ids)

    async def test_a_refusal_is_reported_and_tried_again_next_time(self):
        self.guild.edit_onboarding.side_effect = discord.HTTPException(
            mock.Mock(status=400), "Invalid Form Body")
        self.assertIn("Invalid Form Body", await onboarding.sync(self.guild))
        self.guild.edit_onboarding.side_effect = None
        self.assertIsNone(await onboarding.sync(self.guild))
        self.assertEqual(self.guild.edit_onboarding.await_count, 2)


class Changing(WithGuild):
    async def test_a_question_that_points_to_channels_and_roles(self):
        said, action = await self.carry_out(
            kind=actions.ONBOARDING_QUESTION, title="How did you find us?", one=True,
            options=[{"title": "A friend", "emoji": "🤝", "channels": ["#introductions"]},
                     {"title": "Gaming", "roles": ["@Gamer"], "channels": ["Gaming 1"]}])
        self.assertIn("are asked How did you find us?", said)
        title, details = actions.describe(action)
        self.assertEqual(title, "Ask new members: How did you find us?")
        self.assertIn("- 🤝 **A friend**: #introductions", details)
        self.assertIn("the role Gamer", details)
        asked = next(p for p in self.sent()["prompts"] if p.title == "How did you find us?")
        self.assertTrue(asked.single_select)
        self.assertEqual(asked.options[1].role_ids, {10})

    async def test_changing_and_removing_a_question(self):
        into = onboarding.DEFAULT_QUESTIONS[0][0]
        _, action = await self.carry_out(
            kind=actions.ONBOARDING_QUESTION, question=into.upper(), title="Hobbies?",
            options=[{"title": "Food", "channels": ["food"]}])
        self.assertEqual(actions.describe(action)[0], f"Change the onboarding question {into}")
        self.assertIsNone(onboarding.find(self.guild, into))
        self.assertEqual(len(onboarding.find(self.guild, "hobbies?")["options"]), 1)
        await self.carry_out(kind=actions.ONBOARDING_REMOVE, question="Hobbies?")
        self.assertNotIn("Hobbies?", [p.title for p in self.sent()["prompts"]])

    async def test_what_a_question_cant_do(self):
        pickers.save({"title": "Gender", "roles": [10], "one": True, "message_id": None})
        self.channels["secret"] = channel(9, "secret", see=False)
        self.guild.channels.append(self.channels["secret"])
        cases = [
            ({"title": "Gender", "options": [{"title": "X", "roles": ["Gamer"]}]}, "picker"),
            ({"title": "Q", "options": [{"title": "X", "roles": ["Teal"]}]}, "can't give"),
            ({"title": "Q", "options": [{"title": "X", "channels": ["secret"]}]}, "hidden"),
            ({"title": "Q", "options": [{"title": "X", "channels": ["nowhere"]}]}, "no channel"),
            ({"title": "Q", "options": [{"title": "X"}]}, "needs a channel or a role"),
            ({"title": "Q", "options": [{"title": "X" * 51, "channels": ["food"]}]}, "50"),
            ({"title": "Q", "options": []}, "answers"),
            ({"question": "Nope", "options": [{"title": "X", "channels": ["food"]}]},
             "no onboarding question"),
        ]
        for fields, expected in cases:
            problem = await actions.check(self.guild, {"kind": actions.ONBOARDING_QUESTION,
                                                       **fields})
            self.assertIn(expected, problem or "", fields)
        problem = await actions.check(self.guild, {"kind": actions.ONBOARDING_REMOVE,
                                                   "question": "Gender"})
        self.assertIn("Change the picker", problem)

    async def test_default_channels_keep_discords_minimum(self):
        said, action = await self.carry_out(kind=actions.ONBOARDING_CHANNELS,
                                            add=["food"], remove=["mod-log"])
        self.assertIn("New members also see #food", actions.describe(action)[1])
        ids = {c.id for c in self.sent()["default_channels"]}
        self.assertIn(self.channels["food"].id, ids)
        self.assertNotIn(self.channels["mod-log"].id, ids)
        open_ones = ["ask-saheb", "general", "introductions", "memes", "media", "off-topic"]
        problem = await actions.check(self.guild, {"kind": actions.ONBOARDING_CHANNELS,
                                                   "remove": open_ones[:3]})
        self.assertIn("at least 7", problem)

    async def test_the_change_is_kept_off_a_community_server_and_says_so(self):
        self.guild.features = []
        said, _ = await self.carry_out(kind=actions.ONBOARDING_REMOVE,
                                       question=onboarding.DEFAULT_QUESTIONS[1][0])
        self.assertIn("Community", said)
        self.assertEqual(len(onboarding.saved(self.guild)["questions"]), 1)

    async def test_the_bot_can_show_the_page(self):
        pickers.save({"title": "Play", "roles": [10], "one": False, "message_id": None})
        ctx = assistant.Context(guild=self.guild, member=None)
        shown = json.loads(await assistant.run_tool(ctx, "get_onboarding", {}))
        self.assertTrue(shown["shown"])
        self.assertIn("welcome", shown["default_channels"])
        play = shown["questions"][-1]
        self.assertEqual((play["title"], play["from_picker"], play["answers"][0]["roles"]),
                         ("Play", True, ["Gamer"]))


if __name__ == "__main__":
    unittest.main()
