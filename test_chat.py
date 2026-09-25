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
import cards
import chat
import code_changes
import colors
import layout
import proposals
import providers
import setting_changes
import settings
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

    def test_a_channel_the_bot_depends_on_cant_be_purged(self):
        self.assertIn("depends on", self.check(kind=actions.PURGE, channel="welcome")[0])
        problem, action = self.check(kind=actions.PURGE, channel="cars")
        self.assertIsNone(problem)
        title, details = actions.describe(action)
        self.assertEqual(title, "Clear cars's history")
        self.assertIn("can't be restored", details)

    def test_only_text_channels_can_be_purged(self):
        self.assertIn("Only text", self.check(kind=actions.PURGE, channel="Gaming 1")[0])


class System(unittest.TestCase):
    def test_the_bot_is_told_never_to_use_an_em_dash(self):
        self.assertIn("Never use an em dash", assistant.SYSTEM)

    def test_only_irreversible_channel_changes_need_confirming(self):
        for kind in (actions.DELETE, actions.CATEGORY_DELETE, actions.PURGE):
            self.assertTrue(assistant.needs_confirming(
                proposals.ACTION, {"kind": kind}))
        self.assertFalse(assistant.needs_confirming(
            proposals.ACTION, {"kind": actions.TOPIC}))


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


def attachment(content_type, data, size=None):
    a = mock.Mock(spec=discord.Attachment)
    a.content_type, a.size = content_type, size if size is not None else len(data)
    a.read = mock.AsyncMock(return_value=data)
    return a


class Conversation(WithTempData, unittest.IsolatedAsyncioTestCase):
    def ctx(self, attachments=()):
        return assistant.Context(guild=self.guild, member=types.SimpleNamespace(
            id=7, display_name="Hadi"), attachments=list(attachments))

    async def talk(self, *replies, text="hi", attachments=()):
        ctx = self.ctx(attachments)
        with mock.patch.object(ai, "converse", mock.AsyncMock(side_effect=list(replies))) as c:
            answer = await assistant.respond(ctx, [], text)
        return ctx, answer, c

    def sent_images(self, calls):
        turns = calls.call_args_list[0].args[1]
        return next(t for t in turns if t["role"] == "user")["images"]

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

    async def test_an_attached_image_is_shown_to_the_model(self):
        picture = attachment("image/png", b"pixels")
        pdf = attachment("application/pdf", b"not a picture")
        ctx, answer, calls = await self.talk(
            reply("That's a nice picture."), attachments=[picture, pdf])
        self.assertEqual(self.sent_images(calls), [("image/png", b"pixels")])
        self.assertEqual(answer, "That's a nice picture.")

    async def test_images_that_are_too_big_or_too_many_are_left_out(self):
        too_big = attachment("image/png", b"x", size=assistant.MAX_VIEWABLE_BYTES + 1)
        many = [attachment("image/png", f"img{i}".encode())
                for i in range(assistant.MAX_VIEWABLE_IMAGES + 2)]
        _, _, calls = await self.talk(reply("ok"), attachments=[too_big, *many])
        self.assertEqual(len(self.sent_images(calls)), assistant.MAX_VIEWABLE_IMAGES)

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


    async def test_an_admins_request_is_done_at_once_except_deleting(self):
        async def ship(client, guild, opener, admin_id):
            p = proposals.pass_now(opener(NOW)["no"], admin_id, NOW)
            return p, "Done: slowmode in <#2> is 30 seconds."
        ship = mock.AsyncMock(side_effect=ship)
        ctx = assistant.Context(guild=self.guild, member=types.SimpleNamespace(
            id=7, display_name="Hadi"), admin=True)
        with mock.patch.object(ai, "converse", mock.AsyncMock(side_effect=[
                reply(calls=[("draft_channel_change", {"change": "set_slowmode",
                                                       "channel": "cars", "slowmode": 30}),
                             ("draft_channel_change", {"change": "delete_channel",
                                                       "channel": "cars"})]),
                reply("Done, and confirm the deletion.")])) as calls, \
                mock.patch("voting_ui.ship", ship):
            await assistant.respond(ctx, [], "slow #cars down, then delete it")
        ship.assert_awaited_once()
        results = next(t for t in calls.call_args.args[1] if t["role"] == "tool")["results"]
        done, deleting = [json.loads(r["result"]) for r in results]
        self.assertIn("30 seconds", done["result"])
        self.assertEqual(proposals.all_proposals()[0]["shipped_by"], 7)
        self.assertIn("Ship it", deleting["note"])
        self.assertEqual([d["title"] for d in ctx.drafts], ["Delete cars"])

    async def test_a_member_who_isnt_an_admin_only_gets_a_draft(self):
        with mock.patch("voting_ui.ship", mock.AsyncMock()) as ship:
            ctx, _, _ = await self.talk(
                reply(calls=[("draft_setting_change", {"setting": "quorum", "value": 8})]),
                reply("Drafted."))
        ship.assert_not_awaited()
        self.assertEqual(len(ctx.drafts), 1)
        self.assertEqual(proposals.all_proposals(), [])


class Shipping(WithTempData, unittest.IsolatedAsyncioTestCase):
    """voting_ui.ship: an admin's request from #ask-saheb, done at once."""

    async def ship(self, opener, done="Done."):
        message = types.SimpleNamespace(id=70, jump_url="https://discord.com/x",
                                        create_thread=mock.AsyncMock(), edit=mock.AsyncMock(),
                                        reply=mock.AsyncMock())
        channel = types.SimpleNamespace(id=6, send=mock.AsyncMock(return_value=message))
        logged = mock.AsyncMock()
        with mock.patch.object(layout, "channel", lambda g, name: channel), \
                mock.patch.object(layout, "server_log", logged), \
                mock.patch.object(layout, "post_texts", mock.AsyncMock()), \
                mock.patch.object(actions, "carry_out", mock.AsyncMock(return_value=done)):
            p, said = await voting_ui.ship(None, object(), opener, 7)
        return p, said, channel, logged

    async def test_it_passes_posts_logs_and_says_what_was_done(self):
        action = {"kind": actions.TOPIC, "channel": "cars", "topic": "Vroom"}
        p, said, channel, logged = await self.ship(
            lambda now: actions.KIND.open(7, action, now), "Done: <#2> has its new topic.")
        self.assertEqual((p["status"], p["shipped_by"]), (proposals.PASSED, 7))
        self.assertEqual(proposals.get(p["no"])["message_id"], 70)
        channel.send.assert_awaited_once()
        self.assertIn("<@7> passed proposal", logged.call_args_list[0].args[1])
        self.assertEqual(said, "Done: <#2> has its new topic.")

    async def test_a_setting_or_code_change_says_what_happens_next(self):
        _, said, _, _ = await self.ship(
            lambda now: setting_changes.KIND.open(7, "quorum", 8, "", now))
        self.assertIn("is now at least 8 votes", said)
        self.assertEqual(settings.current()["quorum"], 8)
        _, said, _, _ = await self.ship(
            lambda now: code_changes.KIND.open(7, "Trivia", "A trivia game.", now))
        self.assertIn("code change", said)

    async def test_a_refused_opener_opens_nothing(self):
        def refuse(now):
            raise proposals.Refused("No.")
        with self.assertRaises(proposals.Refused):
            await self.ship(refuse)
        self.assertEqual(proposals.all_proposals(), [])


class Chat(WithTempData, unittest.IsolatedAsyncioTestCase):
    def test_each_member_is_rate_limited_on_their_own(self):
        self.assertTrue(all(chat.allowed(1, NOW + i) for i in range(chat.PER_WINDOW)))
        self.assertFalse(chat.allowed(1, NOW + 10))
        self.assertTrue(chat.allowed(2, NOW + 10))
        self.assertTrue(chat.allowed(1, NOW + chat.WINDOW + 1))

    def test_an_admin_can_switch_the_limit_off(self):
        for i in range(chat.PER_WINDOW):
            chat.allowed(3, NOW + i)
        self.assertFalse(chat.allowed(3, NOW + 30))
        store.save("chat", {"limited": False})
        self.assertTrue(all(chat.allowed(3, NOW + 30) for _ in range(100)))

    async def switch(self, user_id, on):
        sent = []
        interaction = types.SimpleNamespace(
            guild=types.SimpleNamespace(id=99, owner_id=1), user=types.SimpleNamespace(
                id=user_id, mention=f"<@{user_id}>"),
            response=types.SimpleNamespace(
                send_message=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))
        with mock.patch.object(layout, "home_id", lambda: 99), \
                mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            await chat.chat_limit.callback(interaction, on)
        return sent[0], logged

    async def test_only_admins_and_the_owner_switch_the_limit(self):
        said, logged = await self.switch(7, False)
        self.assertIn("Only an admin", said)
        logged.assert_not_awaited()
        self.assertTrue(chat.limited())
        admins.add(7)
        said, logged = await self.switch(7, False)
        self.assertIn("off", said)
        self.assertFalse(chat.limited())
        self.assertIn("<@7> turned", logged.call_args.args[1])
        said, _ = await self.switch(1, True)
        self.assertTrue(chat.limited())

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
            guild=types.SimpleNamespace(id=99, me=me, owner_id=1),
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

    def test_admins_get_ship_it_on_every_draft(self):
        general = assistant.save_draft(7, proposals.GENERAL, "Dark mode", "Add it.", {}, NOW)
        setting = assistant.save_draft(7, proposals.SETTING, "Quorum", "", {}, NOW)
        drafts = [general, setting]
        g, s = general["no"], setting["no"]
        self.assertEqual(self.buttons(chat.drafts_view(drafts)), [f"draft:{g}", f"draft:{s}"])
        self.assertEqual(self.buttons(chat.drafts_view(drafts, admin=True)),
                         [f"draft:{g}", f"ship:{g}", f"draft:{s}", f"ship:{s}"])

    def test_admin_powers_are_for_admins_and_the_owner_in_the_home_server(self):
        home = types.SimpleNamespace(id=99, owner_id=1)
        admins.add(7)
        with mock.patch.object(layout, "home_id", lambda: 99):
            self.assertTrue(admins.allowed(7, home))
            self.assertTrue(admins.allowed(1, home))
            self.assertFalse(admins.allowed(8, home))
            self.assertFalse(admins.allowed(7, types.SimpleNamespace(id=5, owner_id=1)))
            self.assertFalse(admins.allowed(7, None))

    async def ship(self, draft_no, user_id):
        sent = []
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=user_id), guild=types.SimpleNamespace(id=99, owner_id=1),
            response=types.SimpleNamespace(
                send_message=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))

        async def publish(i, opener, by_admin=False):
            p = opener(NOW)
            return proposals.pass_now(p["no"], i.user.id, NOW) if by_admin else p
        publish = mock.AsyncMock(side_effect=publish)
        with mock.patch("voting_ui.publish", publish), \
                mock.patch.object(layout, "home_id", lambda: 99):
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

    async def test_an_admin_can_pass_a_setting_but_only_their_own_draft(self):
        admins.add(7)
        admins.add(8)
        setting = assistant.save_draft(7, proposals.SETTING, "Quorum", "",
                                       {"setting": "quorum", "value": 8}, NOW)
        sent, publish = await self.ship(setting["no"], 8)
        self.assertIn("Only the member", sent[0])
        publish.assert_not_awaited()
        await self.ship(setting["no"], 7)
        p = proposals.get(assistant.get_draft(setting["no"])["filed"])
        self.assertEqual((p["setting"], p["value"], p["shipped_by"]), ("quorum", 8, 7))

    def test_a_card_says_which_admin_passed_or_withdrew_it(self):
        p = proposals.pass_now(code_changes.KIND.open(7, "Dark mode", "Add it.", NOW)["no"],
                               7, NOW)
        embed = cards.card(p)
        self.assertIn("Passed by an admin", embed.fields[-1].value)
        self.assertIn("still goes through every automatic check", embed.footer.text)
        q = proposals.withdraw(code_changes.KIND.open(8, "Spam", "Spam.", NOW)["no"],
                               7, "Off topic", NOW)
        embed = cards.card(q)
        self.assertIn("Withdrawn by an admin", embed.fields[-2].value)
        self.assertEqual(embed.fields[-1].value, "Off topic")


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
        p = {"kind": proposals.ACTION, "status": proposals.PASSED, "no": 3, "action": action,
             "title": "Create the channel anime"}
        with mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            said = await actions.KIND.carry_out(None, self.guild, p)
        self.assertIn("Proposal 3", logged.call_args.args[1])
        self.guild.create_text_channel.assert_awaited_once()
        self.assertIn("<#50> is open", said)

    async def test_purging_deletes_every_message_and_leaves_the_channel(self):
        cars = self.guild.channels[3]
        cars.purge = mock.AsyncMock(return_value=[object(), object()])
        said = await actions.carry_out(self.guild, {"kind": actions.PURGE, "channel": "cars"})
        cars.purge.assert_awaited_once_with(limit=None, reason=actions.REASON)
        self.assertIn("2 messages deleted", said)

    async def test_a_deleted_planned_channel_is_not_rebuilt(self):
        store.save("layout", {"guild_id": 99, "channels": {"cars": 2}, "messages": {}})
        self.guild.channels[3].delete = mock.AsyncMock()
        said = await actions.carry_out(self.guild, {"kind": actions.DELETE, "channel": "cars"})
        self.assertIn("deleted", said)
        saved = store.load("layout", {})
        self.assertEqual((saved["channels"], saved["removed"]), ({}, ["cars"]))


if __name__ == "__main__":
    unittest.main()
