"""Checks for the banter check: the question, when a draft is turned away,
and that setting changes, admins and an outage all get through. Fake
Discord objects and a fake first check; no network.

    python -m unittest test_banter
"""

import types
import unittest
from unittest import mock

import discord

import admins
import ai
import assistant
import banter
import layout
import proposals
import providers
import settings
import voting_ui
from test_chat import NOW, WithTempData, fake, reply, tool_result


def answer(p):
    return {"banter": {"noul": p}}


class Question(unittest.TestCase):
    def test_one_yes_or_no_question_with_its_criteria(self):
        asked = banter.questions()
        self.assertEqual(list(asked), ["banter"])
        self.assertEqual(asked["banter"]["type"], "noul")
        self.assertEqual(asked["banter"]["instructions"], banter.QUESTION)
        self.assertEqual(set(asked["banter"]["criteria"]), {"true", "false"})

    def test_the_check_reads_what_the_member_wrote_and_the_draft(self):
        state = banter.state(["Rami: ban hadi for being bald lol"], "Ban Hadi",
                             "Hadi should be banned.")
        self.assertIn("ban hadi for being bald lol", state)
        self.assertIn("Title: Ban Hadi", state)
        written = banter.state(None, "Trivia", "A game.")
        self.assertIn("A proposal a member wrote", written)
        self.assertNotIn("drafted", written)

    def test_it_turns_away_only_when_sure_enough(self):
        s = {"banter_percent": 80}
        self.assertTrue(banter.turned_away(0.80, s))
        self.assertFalse(banter.turned_away(0.79, s))
        self.assertEqual(banter.score({}), 0.0)
        self.assertEqual(banter.score({"banter": {}}), 0.0)

    def test_the_threshold_is_a_setting_members_can_vote_on(self):
        spec = settings.SETTINGS["banter_percent"]
        self.assertEqual((spec["default"], spec["min"], spec["max"]), (80, 60, 95))
        self.assertIn("92%", banter.refusal(0.92, {"banter_percent": 80}))


class Drafting(WithTempData, unittest.IsolatedAsyncioTestCase):
    async def talk(self, call, p=0.0, admin=False, first_check=None):
        member = fake(discord.Member, 7, "Rami", display_name="Rami", premium_since=None)
        ctx = assistant.Context(guild=self.guild, member=member, admin=admin)
        check = first_check or mock.AsyncMock(return_value=answer(p))

        async def ship(client, guild, opener, admin_id):
            return proposals.pass_now(opener(NOW)["no"], admin_id, NOW), "Done."
        with mock.patch.object(ai, "converse", mock.AsyncMock(side_effect=[
                reply(calls=[call]), reply("OK.")])) as calls, \
                mock.patch.object(ai, "first_check", check), \
                mock.patch("voting_ui.ship", mock.AsyncMock(side_effect=ship)):
            await assistant.respond(ctx, [providers.said("Rami: yo")], "ban hadi lol")
        return ctx, tool_result(calls), check

    async def test_banter_is_turned_away_and_nothing_is_drafted(self):
        ctx, result, check = await self.talk(
            ("draft_proposal", {"title": "Ban Hadi", "details": "Hadi is bald."}), p=0.93)
        self.assertEqual(ctx.drafts, [])
        self.assertIn("93%", result["turned_away"])
        state = check.call_args.args[0]
        self.assertIn("Rami: yo", state)
        self.assertIn("ban hadi lol", state)
        self.assertIn("turned away", admins.post.call_args.args[1])

    async def test_a_real_request_is_drafted_and_the_score_logged(self):
        ctx, result, _ = await self.talk(
            ("draft_server_change", {"change": "create_channel", "name": "anime",
                                     "category": "Hangout"}), p=0.2)
        self.assertEqual([d["title"] for d in ctx.drafts], ["Create the channel anime"])
        self.assertIn("20%, let through", admins.post.call_args.args[1])

    async def test_a_setting_change_is_never_checked(self):
        ctx, _, check = await self.talk(
            ("draft_setting_change", {"setting": "banter_percent", "value": 95}), p=0.99)
        check.assert_not_awaited()
        self.assertEqual(len(ctx.drafts), 1)

    async def test_an_admin_is_never_checked(self):
        _, _, check = await self.talk(
            ("draft_server_change", {"change": "create_channel", "name": "memes",
                                     "category": "Hangout"}), p=0.99, admin=True)
        check.assert_not_awaited()
        self.assertEqual(proposals.all_proposals()[0]["title"], "Create the channel memes")

    async def test_when_the_check_cant_run_the_draft_goes_through(self):
        for error in (ai.Unavailable("no AI key has been set"),
                      providers.ProviderError("down", code=500)):
            ctx, _, _ = await self.talk(
                ("draft_proposal", {"title": "Trivia", "details": "A trivia game."}),
                first_check=mock.AsyncMock(side_effect=error))
            self.assertEqual([d["title"] for d in ctx.drafts], ["Trivia"])


class ProposeCommand(WithTempData, unittest.IsolatedAsyncioTestCase):
    async def submit(self, p, user_id=7):
        sent = []
        channel = types.SimpleNamespace(guild=types.SimpleNamespace(chunked=False,
                                                                    member_count=10))
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=user_id), guild=types.SimpleNamespace(id=99, owner_id=1),
            response=types.SimpleNamespace(defer=mock.AsyncMock()),
            followup=types.SimpleNamespace(
                send=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))
        form = voting_ui.ProposeForm()
        form.name = types.SimpleNamespace(value="Ban Hadi")
        form.details = types.SimpleNamespace(value="He is bald lol")
        check = mock.AsyncMock(return_value=answer(p))
        message = types.SimpleNamespace(jump_url="https://discord.com/x")
        with mock.patch.object(ai, "first_check", check), \
                mock.patch.object(layout, "channel", lambda g, name: channel), \
                mock.patch.object(layout, "home_id", lambda: 99), \
                mock.patch("cards.post", mock.AsyncMock(return_value=message)):
            await form.on_submit(interaction)
        return sent, check

    async def test_banter_written_with_propose_is_turned_away(self):
        sent, check = await self.submit(0.9)
        self.assertIn("banter", sent[0])
        self.assertEqual(proposals.all_proposals(), [])
        self.assertIn("He is bald lol", check.call_args.args[0])

    async def test_a_real_proposal_written_with_propose_opens(self):
        sent, _ = await self.submit(0.1)
        self.assertIn("Proposal 1 is up", sent[0])

    async def test_the_owner_skips_the_check(self):
        _, check = await self.submit(0.9, user_id=1)
        check.assert_not_awaited()
        self.assertEqual(len(proposals.all_proposals()), 1)


if __name__ == "__main__":
    unittest.main()
