"""Checks for #ask-saheb: what the bot may do on its own, drafting and
filing proposals, server changes, and carrying them out after a vote.
Fake Discord objects and fake model replies; no network.

    python -m unittest
"""

import asyncio
import contextlib
import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import actions
import admins
import ai
import assistant
import chat
import colors
import layout
import proposals
import providers
import store
import voting_ui

NOW = 1_800_000_000


def fake(cls, id, name, **fields):
    thing = mock.Mock(spec=cls)
    thing.id, thing.name = id, name
    for key, value in fields.items():
        setattr(thing, key, value)
    return thing


def guild():
    hangout = fake(discord.CategoryChannel, 100, "Hangout")
    voice = fake(discord.CategoryChannel, 101, "Voice")
    general = fake(discord.TextChannel, 1, "general", mention="<#1>")
    cars = fake(discord.TextChannel, 2, "cars", mention="<#2>")
    welcome = fake(discord.TextChannel, 3, "welcome", mention="<#3>")
    gaming = fake(discord.VoiceChannel, 4, "Gaming 1", mention="<#4>")
    hangout.channels, voice.channels = [general, cars, welcome], [gaming]
    everything = [hangout, voice, general, cars, welcome, gaming]
    g = types.SimpleNamespace(id=99, channels=everything, categories=[hangout, voice])
    g.get_channel = lambda cid: next((c for c in everything if c.id == cid), None)
    return g


class WithTempData(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.guild = guild()
        self._layout = mock.patch.object(
            layout, "channel",
            lambda g, name: next((c for c in g.channels if c.name == name), None))
        self._layout.start()

    def tearDown(self):
        self._layout.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)


class Checks(WithTempData, unittest.IsolatedAsyncioTestCase):
    def check(self, **action):
        return asyncio.run(actions.check(self.guild, action)), action

    def test_a_new_channel_is_named_the_way_discord_would_name_it(self):
        problem, action = self.check(kind=actions.CREATE, name="Anime & Manga",
                                     category="Hangout")
        self.assertIsNone(problem)
        self.assertEqual((action["name"], action["channel_type"]), ("anime-manga", "text"))

    def test_creating_needs_a_new_name_and_a_real_category(self):
        self.assertIn("already", self.check(kind=actions.CREATE, name="cars",
                                            category="Hangout")[0])
        self.assertIn("Hangout, Voice", self.check(kind=actions.CREATE, name="anime",
                                                   category="Nowhere")[0])

    def test_the_channels_the_bot_depends_on_cant_be_renamed_or_deleted(self):
        self.assertIn("depends on", self.check(kind=actions.DELETE, channel="#welcome")[0])
        self.assertIn("depends on", self.check(kind=actions.RENAME, channel="welcome",
                                               name="hello")[0])
        problem, action = self.check(kind=actions.TOPIC, channel="welcome", topic="Hi")
        self.assertIsNone(problem)

    def test_channels_are_found_by_their_real_name_and_remembered_by_id(self):
        problem, action = self.check(kind=actions.RENAME, channel="Gaming 1", name="Gaming A")
        self.assertIsNone(problem)
        self.assertEqual((action["channel_id"], action["name"]), (4, "Gaming A"))
        self.assertIn("no channel", self.check(kind=actions.DELETE, channel="nope")[0])

    def test_topic_and_slowmode_rules(self):
        self.assertIn("Only text", self.check(kind=actions.SLOWMODE, channel="Gaming 1",
                                              slowmode=10)[0])
        self.assertIn("21600", self.check(kind=actions.SLOWMODE, channel="cars",
                                          slowmode=99999)[0])
        self.assertIn("how many", self.check(kind=actions.SLOWMODE, channel="cars")[0])
        self.assertIn("isn't a change", self.check(kind="give_admin")[0])

    def test_the_proposal_says_what_will_happen(self):
        _, action = self.check(kind=actions.DELETE, channel="cars", reason="Nobody uses it")
        title, details = actions.describe(action)
        self.assertEqual(title, "Delete cars")
        self.assertIn("can't be restored", details)
        self.assertIn("Nobody uses it", details)


class Tiers(unittest.TestCase):
    def test_every_tool_has_a_tier_and_a_handler(self):
        names = [tool["name"] for tool in assistant.TOOLS]
        self.assertEqual(set(names), set(assistant.TIER))
        self.assertEqual(set(names), set(assistant._TOOLS))

    def test_what_happens_without_a_vote_is_exactly_this(self):
        def tier(t):
            return {n for n, x in assistant.TIER.items() if x == t}
        self.assertEqual(tier(assistant.SELF), {
            "set_my_color", "join_role", "leave_role", "set_my_nickname", "create_invite"})
        self.assertEqual(tier(assistant.LIGHT), {
            "create_event", "cancel_my_event", "create_temp_voice", "start_thread",
            "pin_message", "unpin_message"})
        self.assertTrue(all(n.startswith(("draft_", "get_", "list_"))
                            for n in tier(assistant.DRAFT) | tier(assistant.LOOK)))

    def test_only_a_draft_can_name_another_member(self):
        for tool in assistant.TOOLS:
            keys = set(tool["parameters"]["properties"])
            self.assertFalse(keys & {"user", "user_id", "target"}, tool["name"])
            if assistant.TIER[tool["name"]] != assistant.DRAFT:
                self.assertNotIn("member", keys, tool["name"])
        member_tool = next(t for t in assistant.TOOLS if t["name"] == "draft_member_action")
        self.assertIn("reason", member_tool["parameters"]["required"])


def tool_result(converse):
    """The first tool result the model was shown."""
    turns = converse.call_args_list[-1].args[1]
    return json.loads(next(t for t in turns if t["role"] == "tool")["results"][0]["result"])


def reply(text="", calls=()):
    return providers.Reply(text=text, calls=[providers.Call(name=n, args=a, id=f"c{i}")
                                             for i, (n, a) in enumerate(calls)])


class Conversation(WithTempData, unittest.IsolatedAsyncioTestCase):
    def ctx(self):
        return assistant.Context(guild=self.guild, member=types.SimpleNamespace(
            id=7, display_name="Hadi"))

    async def talk(self, *replies, text="hi"):
        ctx = self.ctx()
        with mock.patch.object(ai, "converse", mock.AsyncMock(side_effect=list(replies))) as c:
            answer = await assistant.respond(ctx, [], text)
        return ctx, answer, c

    async def test_asking_for_blue_changes_only_your_own_color(self):
        with mock.patch.object(colors, "wear", mock.AsyncMock(return_value="You're now Mediterranean.")) as wear:
            ctx, answer, _ = await self.talk(
                reply(calls=[("set_my_color", {"color": "Mediterranean"})]),
                reply("Done, you're Mediterranean blue."), text="make my color blue")
        wear.assert_awaited_once_with(ctx.member, "Mediterranean")
        self.assertEqual(answer, "Done, you're Mediterranean blue.")

    async def test_asking_for_a_channel_drafts_a_proposal_and_files_nothing(self):
        ctx, answer, calls = await self.talk(
            reply(calls=[("draft_server_change", {"change": "create_channel", "name": "anime",
                                                  "category": "Hangout"})]),
            reply("I drafted it; press the button to file it."))
        self.assertEqual([d["title"] for d in ctx.drafts], ["Create the channel anime"])
        self.assertEqual(proposals.all_proposals(), [])
        result = tool_result(calls)
        self.assertIn("button", result["note"])

    async def test_a_draft_that_cant_be_done_comes_back_as_an_error(self):
        ctx, _, calls = await self.talk(
            reply(calls=[("draft_server_change", {"change": "delete_channel",
                                                  "channel": "welcome"})]),
            reply("That channel can't be deleted."))
        self.assertEqual(ctx.drafts, [])
        result = tool_result(calls)
        self.assertIn("depends on", result["error"])

    async def test_unknown_tools_and_endless_tool_loops_are_stopped(self):
        _, answer, _ = await self.talk(
            *[reply(calls=[("grant_admin", {})])] * assistant.MAX_ROUNDS)
        self.assertIn("too many steps", answer)

    async def test_a_filed_draft_becomes_the_right_kind_of_proposal(self):
        ctx, _, _ = await self.talk(
            reply(calls=[("draft_server_change", {"change": "set_slowmode", "channel": "cars",
                                                  "slowmode": 30}),
                         ("draft_setting_change", {"setting": "quorum", "value": 8}),
                         ("draft_proposal", {"title": "Trivia", "details": "A trivia game."})]),
            reply("Three drafts."))
        filed = [assistant.opener(d, 7)(NOW) for d in ctx.drafts]
        self.assertEqual([p["kind"] for p in filed],
                         [proposals.ACTION, proposals.SETTING, proposals.GENERAL])
        self.assertEqual(filed[0]["action"]["slowmode"], 30)
        self.assertEqual(filed[1]["value"], 8)


class Chat(WithTempData, unittest.IsolatedAsyncioTestCase):
    def test_each_member_is_rate_limited_on_their_own(self):
        self.assertTrue(all(chat.allowed(1, NOW + i) for i in range(chat.PER_WINDOW)))
        self.assertFalse(chat.allowed(1, NOW + 10))
        self.assertTrue(chat.allowed(2, NOW + 10))
        self.assertTrue(chat.allowed(1, NOW + chat.WINDOW + 1))

    def test_memory_keeps_recent_text_and_forgets_after_a_while(self):
        chat.remember(5, NOW, "Hadi: hi", "Hello!")
        self.assertEqual([t["role"] for t in chat.history(5, NOW + 60)], ["user", "model"])
        self.assertEqual(chat.history(5, NOW + chat.MEMORY_TTL + 1), [])

    async def say(self, content, mentions=(), roles=(), reply_to=None):
        """Post `content` in #ask-saheb and return what the bot answered, or
        None if it stayed quiet."""
        role = mock.Mock(spec=discord.Role, id=600)
        role.is_bot_managed.return_value = True
        me = types.SimpleNamespace(id=500, roles=[role])
        ask = types.SimpleNamespace(id=5, typing=contextlib.nullcontext,
                                    fetch_message=mock.AsyncMock(return_value=reply_to))
        reference = None
        if reply_to is not None:
            reference = types.SimpleNamespace(message_id=reply_to.id, resolved=None,
                                              cached_message=None)
        message = types.SimpleNamespace(
            content=content, attachments=[], reference=reference, channel=ask,
            author=types.SimpleNamespace(id=7, bot=False, display_name="Rami"),
            guild=types.SimpleNamespace(id=99, me=me),
            mentions=[me if m == "me" else m for m in mentions],
            role_mentions=[role if r == "me" else r for r in roles],
            reply=mock.AsyncMock())
        respond = mock.AsyncMock(return_value="Hi Rami")
        with mock.patch.object(layout, "home_id", lambda: 99), \
                mock.patch.object(layout, "channel", lambda g, name: ask), \
                mock.patch.object(assistant, "respond", respond):
            await chat.on_message(message)
        if not respond.await_count:
            message.reply.assert_not_awaited()
            return None
        return respond.call_args.args[2]

    async def test_it_answers_only_when_tagged_or_replied_to(self):
        self.assertIsNone(await self.say("anyone here?"))
        friend = types.SimpleNamespace(id=8, display_name="Maya")
        self.assertIsNone(await self.say("<@8> hi", mentions=[friend]))
        self.assertEqual(await self.say("<@500> what's the quorum?", mentions=["me"]),
                         "what's the quorum?")
        self.assertEqual(await self.say("<@&600>  hello", roles=["me"]), "hello")
        theirs = mock.Mock(spec=discord.Message, id=70, content="nice",
                           author=types.SimpleNamespace(id=8))
        self.assertIsNone(await self.say("agreed", reply_to=theirs))
        mine = mock.Mock(spec=discord.Message, id=71, content="The quorum is 5.",
                         author=types.SimpleNamespace(id=500))
        text = await self.say("and to pass?", reply_to=mine)
        self.assertIn("and to pass?", text)
        self.assertIn("The quorum is 5.", text)

    async def press(self, draft_no, user_id):
        sent = []
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=user_id),
            response=types.SimpleNamespace(
                send_message=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))
        publish = mock.AsyncMock(side_effect=lambda i, opener: opener(NOW))
        with mock.patch("voting_ui.publish", publish):
            await chat.FileDraft(draft_no).callback(interaction)
        return sent, publish

    async def test_only_the_asker_can_file_their_draft_and_only_once(self):
        draft = assistant.save_draft(7, proposals.GENERAL, "Trivia", "A game.", {}, NOW)
        sent, publish = await self.press(draft["no"], 8)
        self.assertIn("Only the member", sent[0])
        publish.assert_not_awaited()
        await self.press(draft["no"], 7)
        self.assertEqual(assistant.get_draft(draft["no"])["filed"], 1)
        sent, _ = await self.press(draft["no"], 7)
        self.assertIn("Already filed", sent[0])


class Admins(WithTempData, unittest.IsolatedAsyncioTestCase):
    def test_only_the_owner_picks_admins_in_the_home_server(self):
        home = types.SimpleNamespace(id=99, owner_id=1)
        asking = lambda user, g=home: types.SimpleNamespace(
            guild=g, user=types.SimpleNamespace(id=user))
        with mock.patch.object(layout, "home_id", lambda: 99):
            self.assertIsNone(admins._refusal(asking(1)))
            self.assertIn("owner", admins._refusal(asking(2)))
            self.assertIn("server itself",
                          admins._refusal(asking(1, types.SimpleNamespace(id=5, owner_id=1))))
        self.assertTrue(admins.add(7))
        self.assertFalse(admins.add(7))
        self.assertTrue(admins.is_admin(7))
        self.assertTrue(admins.remove(7))
        self.assertFalse(admins.is_admin(7))

    def buttons(self, view):
        return [item.item.custom_id for item in view.children]

    def test_admins_also_get_ship_it_on_code_changes_only(self):
        general = assistant.save_draft(7, proposals.GENERAL, "Dark mode", "Add it.", {}, NOW)
        setting = assistant.save_draft(7, proposals.SETTING, "Quorum", "", {}, NOW)
        drafts = [general, setting]
        g, s = general["no"], setting["no"]
        self.assertEqual(self.buttons(chat.drafts_view(drafts)), [f"draft:{g}", f"draft:{s}"])
        self.assertEqual(self.buttons(chat.drafts_view(drafts, admin=True)),
                         [f"draft:{g}", f"ship:{g}", f"draft:{s}"])

    async def ship(self, draft_no, user_id):
        sent = []
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=user_id),
            response=types.SimpleNamespace(
                send_message=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))
        publish = mock.AsyncMock(side_effect=lambda i, opener: opener(NOW))
        with mock.patch("voting_ui.publish", publish):
            await chat.ShipDraft(draft_no).callback(interaction)
        return sent, publish

    async def test_ship_it_checks_the_admin_again_when_pressed(self):
        draft = assistant.save_draft(7, proposals.GENERAL, "Dark mode", "Add it.", {}, NOW)
        sent, publish = await self.ship(draft["no"], 7)
        self.assertIn("Only an admin", sent[0])
        publish.assert_not_awaited()
        admins.add(7)
        _, publish = await self.ship(draft["no"], 7)
        p = proposals.get(assistant.get_draft(draft["no"])["filed"])
        self.assertEqual((p["status"], p["shipped_by"]), (proposals.PASSED, 7))
        sent, _ = await self.ship(draft["no"], 7)
        self.assertIn("Already filed", sent[0])

    async def test_admins_can_only_ship_code_changes_and_only_their_own(self):
        admins.add(7)
        admins.add(8)
        setting = assistant.save_draft(7, proposals.SETTING, "Quorum", "", {}, NOW)
        sent, publish = await self.ship(setting["no"], 7)
        self.assertIn("Only an admin can ship a code change", sent[0])
        general = assistant.save_draft(7, proposals.GENERAL, "Dark mode", "Add it.", {}, NOW)
        sent, publish = await self.ship(general["no"], 8)
        self.assertIn("Only the member", sent[0])
        publish.assert_not_awaited()

    def test_a_shipped_card_says_so_and_has_no_vote_buttons(self):
        p = proposals.ship(7, "Dark mode", "Add it.", NOW)
        embed = voting_ui.card(p)
        self.assertIn("Shipped by an admin", embed.fields[-1].value)
        self.assertIn("skipped the vote", embed.footer.text)


class Counting(unittest.TestCase):
    def test_the_quorum_counts_people_not_bots(self):
        members = [types.SimpleNamespace(bot=b) for b in (False, False, False, True, True)]
        loaded = types.SimpleNamespace(chunked=True, members=members, member_count=5)
        self.assertEqual(voting_ui.people(loaded), 3)
        loading = types.SimpleNamespace(chunked=False, members=[], member_count=5)
        self.assertEqual(voting_ui.people(loading), 4)
        unknown = types.SimpleNamespace(chunked=False, members=[], member_count=None)
        self.assertIsNone(voting_ui.people(unknown))


class CarryingOut(WithTempData, unittest.IsolatedAsyncioTestCase):
    async def test_a_passed_change_is_made_and_reported(self):
        made = fake(discord.TextChannel, 50, "anime", mention="<#50>")
        self.guild.create_text_channel = mock.AsyncMock(return_value=made)
        action = {"kind": actions.CREATE, "name": "anime", "category": "Hangout"}
        await actions.check(self.guild, action)
        client = types.SimpleNamespace(get_guild=lambda gid: self.guild)
        p = {"kind": proposals.ACTION, "status": proposals.PASSED, "no": 3, "action": action,
             "title": "Create the channel anime"}
        with mock.patch("voting_ui.reply_to", mock.AsyncMock()) as said, \
                mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            await actions.settle(client, p)
        self.assertIn("Proposal 3", logged.call_args.args[1])
        self.guild.create_text_channel.assert_awaited_once()
        self.assertIn("<#50> is open", said.call_args.args[2])

    async def test_a_deleted_planned_channel_is_not_rebuilt(self):
        store.save("layout", {"guild_id": 99, "channels": {"cars": 2}, "messages": {}})
        self.guild.channels[3].delete = mock.AsyncMock()
        said = await actions.carry_out(self.guild, {"kind": actions.DELETE, "channel": "cars"})
        self.assertIn("deleted", said)
        saved = store.load("layout", {})
        self.assertEqual((saved["channels"], saved["removed"]), ({}, ["cars"]))

    async def test_failed_votes_change_nothing(self):
        with mock.patch.object(actions, "carry_out", mock.AsyncMock()) as carry:
            await actions.settle(None, {"kind": proposals.ACTION, "status": proposals.FAILED})
        carry.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
