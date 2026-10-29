"""The whole path from an AutoMod alert to a posted case, against fake
Discord objects and fake AI answers. No network and no Discord server.

    python -m unittest
"""

import shutil
from datetime import timedelta
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import admins
import ai
import appeals
import cases
import judge
import layout
import moderator
import scold
import settings
import store

OWNER, BOT_ROLE, MEMBER_ROLE = 1, 10, 0


class Sent:
    """Anything that can be sent to: records what was sent."""

    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(kwargs.get("embed") or content)
        return types.SimpleNamespace(id=900 + len(self.sent))


class Channel(Sent):
    def __init__(self, history):
        super().__init__()
        self.id = 50
        self._history = history
        self.deleted = []
        self.references = []

    async def send(self, content=None, reference=None, **kwargs):
        if reference is not None:
            self.references.append(reference.message_id)
        return await super().send(content, **kwargs)

    def history(self, limit, before=None):
        async def messages():
            for author, text in reversed(self._history[-limit:]):
                yield types.SimpleNamespace(
                    author=types.SimpleNamespace(display_name=author),
                    content=text, attachments=[])
        return messages()

    def get_partial_message(self, message_id):
        channel = self

        class Partial:
            async def delete(self):
                channel.deleted.append(message_id)
        return Partial()


class Member(Sent):
    def __init__(self, member_id=7):
        super().__init__()
        self.id = member_id
        self.bot = False
        self.display_name = "karim"
        self.top_role = MEMBER_ROLE
        self.timed_out = None

    async def timeout(self, length, reason=None):
        self.timed_out = length


def alert(member, channel, content, message_id=123):
    guild = types.SimpleNamespace(
        id=99, name="Test", owner_id=OWNER, me=types.SimpleNamespace(top_role=BOT_ROLE),
        banned=[])

    async def ban(user, reason=None, delete_message_seconds=0):
        guild.banned.append(user.id)
    guild.ban = ban
    return types.SimpleNamespace(
        action=types.SimpleNamespace(type=None), guild=guild, guild_id=99,
        member=member, user_id=member.id, channel=channel, channel_id=channel.id,
        content=content, message_id=message_id)


def jev(severity=1.0, **scores):
    found = {name: {"type": "noul", "noul": p} for name, p in scores.items()}
    found["severity"] = {"type": "score", "score": severity}
    return found


class Flow(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.log = Sent()
        self.politics = None
        self.admin_log = Sent()
        self.patches = [
            mock.patch.object(layout, "channel", self.channel_of),
            mock.patch.object(ai, "review", self.fake_review),
            mock.patch.object(admins, "log_channel",
                              mock.AsyncMock(return_value=self.admin_log)),
            mock.patch.object(admins, "role", mock.Mock(
                return_value=types.SimpleNamespace(id=5, mention="<@&5>"))),
        ]
        for p in self.patches:
            p.start()
        moderator._supported.clear()  # the support line is sent once a day
        self.reviews = []
        self.review_answer = {}
        self.scolds = []
        self.scold_answer = {"reply": "3ayb ya karim, behave!"}

    def channel_of(self, guild, name):
        return self.log if name == "mod-log" else self.politics

    def politics_channel(self, channel_id):
        politics = mock.Mock(spec=discord.TextChannel)
        politics.id = channel_id
        self.politics = politics
        return politics

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def fake_review(self, prompt, schema):
        if schema is scold.SCHEMA:
            self.scolds.append(prompt)
            return self.scold_answer
        self.reviews.append(prompt)
        return self.review_answer

    async def run_alert(self, answers, content="ya 7mar, no one wants you here",
                        member=None):
        member = member or Member()
        channel = Channel([("rami", "stop insulting me"), ("karim", content)])
        with mock.patch.object(ai, "first_check", mock.AsyncMock(return_value=answers)):
            await moderator.handle(alert(member, channel, content))
        return member, channel

    async def test_banter_is_cleared_without_a_review(self):
        member, _ = await self.run_alert(jev(0.1, harassment=0.08))
        self.assertEqual((self.reviews, self.log.sent, member.sent), ([], [], []))

    async def test_a_confident_first_check_acts_and_haiku_only_explains(self):
        self.review_answer = {"explanation": "Karim insulted Rami after being asked to stop."}
        member, channel = await self.run_alert(jev(1.8, harassment=0.96))
        self.assertEqual(len(self.reviews), 1)
        self.assertIn("not yours to review", self.reviews[0])
        case = cases.get(1)
        self.assertEqual((case["action"], case["rule"], case["severity"], case["decided_by"]),
                         (cases.WARN, 1, "serious", "first check"))
        self.assertFalse(case["deleted"])
        self.assertEqual(channel.deleted, [])  # it stays up, and gets scolded
        self.assertEqual(channel.sent[0],
                         "3ayb ya karim, behave!\n-# " + scold.footer(case))
        self.assertEqual(channel.references, [123])
        self.assertIn("Karim insulted Rami", member.sent[0])
        self.assertEqual(self.log.sent[0].description, case["explanation"])

    async def test_the_first_checks_decision_stands_even_without_an_explanation(self):
        self.review_answer = {}
        await self.run_alert(jev(1.2, hate=0.9))
        self.assertIn("90% likely to be hate", cases.get(1)["explanation"])

    async def test_an_unsure_first_check_lets_the_review_decide(self):
        self.review_answer = {"violation": False, "rule": 0, "severity": "none",
                              "explanation": ""}
        await self.run_alert(jev(1.0, harassment=0.55))
        self.assertEqual(len(self.reviews), 1)
        self.assertIsNone(cases.get(1))

        self.review_answer = {"violation": True, "rule": 1, "severity": "mild",
                              "explanation": "Told a member they were a worthless joke."}
        await self.run_alert(jev(1.0, harassment=0.72, steering=0.9),
                             member=Member(member_id=8))
        self.assertEqual(cases.get(1)["decided_by"], "review")

    async def test_the_record_escalates_to_calling_the_admins_never_a_ban(self):
        self.review_answer = {"violation": True, "rule": 1, "severity": "serious",
                              "explanation": "Insulted a member."}
        member = Member()
        for _ in range(2):
            cases.open_case(int(time.time()) - 60, user_id=member.id,
                            action=cases.TIMEOUT, minutes=60)
        with mock.patch.object(moderator, "COOLDOWN", 0):
            await self.run_alert(jev(1.8, harassment=0.96), member=member)
        case = cases.get(3)
        self.assertEqual((case["action"], case["minutes"], case["called_admins"]),
                         (cases.TIMEOUT, 24 * 60, True))
        self.assertEqual(case["decided_by"], "review")
        self.assertEqual(member.timed_out, timedelta(hours=24))
        self.assertIn("<@&5> Case 3 needs you", self.admin_log.sent[0])
        self.assertIn("after 2 timeouts", self.admin_log.sent[0])

    async def test_a_timeout_or_ban_is_never_the_first_checks_alone(self):
        member = Member()
        cases.open_case(int(time.time()) - 60, user_id=member.id,
                        action=cases.WARN, minutes=0)
        self.review_answer = {"violation": False, "rule": 0, "severity": "none",
                              "explanation": ""}
        with mock.patch.object(moderator, "COOLDOWN", 0):
            await self.run_alert(jev(1.8, harassment=0.96), member=member)
        self.assertEqual(len(self.reviews), 1)
        self.assertNotIn("not yours to review", self.reviews[0])
        self.assertIsNone(cases.get(2))
        self.assertEqual(member.sent, [])

    async def test_the_first_checks_warnings_never_add_up_to_a_timeout(self):
        member = Member()
        for _ in range(5):
            cases.open_case(int(time.time()) - 600, user_id=member.id, action=cases.WARN,
                            minutes=0, decided_by=judge.FIRST_CHECK)
        self.review_answer = {"explanation": "Called a member a donkey."}
        with mock.patch.object(moderator, "COOLDOWN", 0):
            await self.run_alert(jev(1.8, harassment=0.96), member=member)
        self.assertEqual(len(self.reviews), 1)
        self.assertIn("not yours to review", self.reviews[0])  # Jev's warning stands
        case = cases.get(6)
        self.assertEqual((case["action"], case["record"]),
                         (cases.WARN, {"warnings": 0, "timeouts": 0}))
        self.assertIsNone(member.timed_out)

    async def test_a_severe_threat_holds_the_member_and_calls_the_admins(self):
        self.review_answer = {"violation": True, "rule": 3, "severity": "severe",
                              "explanation": "Threatened a member's home."}
        member, channel = await self.run_alert(jev(2.8, threat=0.91),
                                               content="I know which building you live in")
        case = cases.get(1)
        self.assertEqual((case["action"], case["called_admins"]), (cases.TIMEOUT, True))
        self.assertEqual(channel.deleted, [])
        self.assertEqual(member.timed_out, timedelta(hours=24))
        self.assertIn("asked to look at it", member.sent[0])
        self.assertIn("a severe violation", self.admin_log.sent[0])
        fields = {f.name: f.value for f in self.log.sent[0].fields}
        self.assertIn("called to decide", fields["Admins"])

    async def test_a_plain_warning_calls_nobody(self):
        self.review_answer = {"explanation": "Insulted a member."}
        await self.run_alert(jev(1.8, harassment=0.96))
        self.assertFalse(cases.get(1)["called_admins"])
        self.assertEqual(self.admin_log.sent, [])

    async def test_private_information_is_not_quoted_in_the_log(self):
        self.review_answer = {"violation": True, "rule": 4, "severity": "severe",
                              "explanation": "Posted a member's phone number."}
        await self.run_alert(jev(2.8, doxxing=0.95), content="her number is 03 123456")
        fields = {f.name: f.value for f in self.log.sent[0].fields}
        self.assertNotIn("123456", fields["Message"])

    async def test_private_information_is_deleted_and_scolded_in_the_channel(self):
        self.review_answer = {"violation": True, "rule": 4, "severity": "severe",
                              "explanation": "Posted a member's phone number."}
        _, channel = await self.run_alert(jev(2.8, doxxing=0.95),
                                          content="her number is 03 123456")
        self.assertTrue(cases.get(1)["deleted"])
        self.assertEqual(channel.deleted, [123])
        self.assertEqual(channel.references, [])  # nothing left to reply to
        self.assertTrue(channel.sent[0].startswith("<@7> 3ayb"))
        self.assertIn("Do not mention or hint at what the message said", self.scolds[0])

    async def test_a_scolding_that_cant_be_written_gets_a_stock_line(self):
        self.review_answer = {"explanation": "Insulted a member."}
        self.scold_answer = {}
        _, channel = await self.run_alert(jev(1.8, harassment=0.96))
        self.assertTrue(channel.sent[0].startswith(scold.FALLBACKS[1]))

    async def test_members_above_the_bot_are_logged_but_not_touched(self):
        self.review_answer = {"explanation": "Insulted a member."}
        member = Member()
        member.top_role = BOT_ROLE + 1
        await self.run_alert(jev(1.8, harassment=0.96), member=member)
        self.assertEqual(member.sent, [])
        self.assertIn("not above", cases.get(1)["problem"])

    async def test_self_harm_gets_a_support_line_and_no_sanction(self):
        member, _ = await self.run_alert(jev(0.5, self_harm=0.9),
                                         content="i want to kill myself")
        self.assertIn("1564", member.sent[0])
        self.assertIsNone(cases.get(1))

    async def test_without_a_key_moderation_says_once_that_it_is_paused(self):
        async def unavailable(*args):
            raise ai.Unavailable("no AI key has been set")
        moderator._paused_notice = None
        with mock.patch.object(ai, "first_check", unavailable):
            for _ in range(2):
                await moderator.handle(alert(Member(), Channel([]), "x"))
        self.assertEqual(len(self.log.sent), 1)
        self.assertIn("paused", self.log.sent[0])

    async def run_sectarian(self, talk, content, screening=None, channel=None):
        """Handle an alert with a sectarian watch word. The first check is
        asked the sectarian check first, and only if that passes the usual
        questions."""
        channel = channel or Channel([("rami", "say that again"), ("karim", content)])
        answers = [talk] + ([screening] if screening is not None else [])
        with mock.patch.object(ai, "first_check",
                               mock.AsyncMock(side_effect=answers)) as first:
            await moderator.handle(alert(Member(), channel, content))
        return channel, first

    async def test_sectarian_talk_in_the_politics_channel_is_left_alone(self):
        channel = Channel([("karim", "ya zionist")])
        self.politics_channel(channel.id)
        _, first = await self.run_sectarian(
            {"topic": {"noul": 0.99}, "severity": {"score": 2.9}},
            "ya zionist", channel=channel)
        self.assertEqual(first.await_count, 0)  # not even classified
        self.assertIsNone(cases.get(1))
        self.assertEqual((self.log.sent, self.reviews), ([], []))

    async def test_a_thread_in_the_politics_channel_is_left_alone_too(self):
        channel = Channel([("karim", "ya zionist")])
        channel.parent_id = self.politics_channel(70).id
        _, first = await self.run_sectarian(
            {"topic": {"noul": 0.99}, "severity": {"score": 2.9}},
            "ya zionist", channel=channel)
        self.assertEqual(first.await_count, 0)
        self.assertIsNone(cases.get(1))

    async def test_a_mild_mention_is_let_through(self):
        self.politics_channel(70)
        _, first = await self.run_sectarian(
            {"topic": {"noul": 0.95}, "severity": {"score": 1.2}},
            "ya zionist lol", screening=jev(1.8, hate=0.9))
        self.assertEqual(first.await_count, 1)  # classified, then let through
        self.assertIsNone(cases.get(1))
        self.assertEqual((self.log.sent, self.reviews), ([], []))

    async def test_clearly_inflammatory_talk_is_judged_as_a_normal_case(self):
        self.review_answer = {"explanation": "Attacked a community with a slogan."}
        self.politics_channel(70)
        channel, first = await self.run_sectarian(
            {"topic": {"noul": 0.95}, "severity": {"score": 2.6}},
            "ya zionist, death to israel", screening=jev(1.8, hate=0.9))
        self.assertEqual(first.await_count, 2)
        case = cases.get(1)
        self.assertEqual((case["action"], case["rule"], case["severity"]),
                         (cases.WARN, 2, "serious"))
        self.assertFalse(case["deleted"])
        self.assertEqual(channel.deleted, [])
        self.assertIn("Attacked a community", case["explanation"])
        self.assertIn("Attacked a community", self.log.sent[0].description)

    async def run_flag(self, answers, content="ya 7mar, no one wants you here",
                       member=None):
        """A message a member flagged with 🚩 (flags.py does the checks
        before this)."""
        member = member or Member()
        channel = Channel([("rami", "stop insulting me")])
        message = types.SimpleNamespace(
            id=123, content=content, author=member, channel=channel,
            guild=alert(member, channel, content).guild, replies=[])

        async def reply(text, **kwargs):
            message.replies.append(text)
        message.reply = reply
        with mock.patch.object(ai, "first_check", mock.AsyncMock(return_value=answers)):
            await moderator.handle_flag(message)
        return member, channel, message

    async def test_a_flag_is_always_reviewed_and_its_timeout_kept_short(self):
        self.review_answer = {"violation": True, "rule": 1, "severity": "serious",
                              "explanation": "Insulted a member after being asked to stop."}
        member = Member()
        cases.open_case(int(time.time()) - 3600, user_id=member.id,
                        action=cases.TIMEOUT, minutes=60)
        _, channel, _ = await self.run_flag(jev(1.8, harassment=0.96), member=member)
        self.assertEqual(len(self.reviews), 1)
        self.assertNotIn("not yours to review", self.reviews[0])  # not Jev's alone
        case = cases.get(2)
        self.assertEqual((case["action"], case["minutes"], case["flagged"]),
                         (cases.TIMEOUT, 5, True))
        self.assertEqual(member.timed_out, timedelta(minutes=5))
        self.assertEqual(channel.references, [123])  # scolded in a reply
        fields = {f.name: f.value for f in self.log.sent[0].fields}
        self.assertIn("flagged the message with 🚩", fields["Decided by"])

    async def test_a_severe_flag_calls_the_admins_but_still_holds_five_minutes(self):
        self.review_answer = {"violation": True, "rule": 3, "severity": "severe",
                              "explanation": "Threatened a member's home."}
        member, _, _ = await self.run_flag(jev(2.8, threat=0.91))
        case = cases.get(1)
        self.assertEqual((case["minutes"], case["called_admins"]), (5, True))
        self.assertEqual(member.timed_out, timedelta(minutes=5))
        self.assertIn("<@&5> Case 1 needs you", self.admin_log.sent[0])

    async def test_a_flag_that_breaks_no_rule_gets_a_reply(self):
        self.review_answer = {"violation": False, "rule": 0, "severity": "none",
                              "explanation": ""}
        self.scold_answer = {"reply": "Ahla w sahla, nothing wrong here."}
        member, channel, message = await self.run_flag(jev(1.0, harassment=0.55))
        self.assertIsNone(cases.get(1))
        self.assertEqual((member.sent, self.log.sent, channel.sent), ([], [], []))
        self.assertEqual(message.replies, [
            "Ahla w sahla, nothing wrong here.\n-# Flagged with 🚩 · no rule broken"])
        self.assertIn("breaks no rule", self.scolds[0])

    async def test_a_flag_jev_clears_is_answered_without_a_review(self):
        _, _, message = await self.run_flag(jev(0.1, harassment=0.05), content="hi all")
        self.assertEqual(self.reviews, [])
        self.assertEqual(len(message.replies), 1)
        self.assertIsNone(cases.get(1))

    async def test_a_flag_on_someone_who_may_be_hurting_gets_no_joke(self):
        member, _, message = await self.run_flag(jev(0.5, self_harm=0.9),
                                                 content="i want to kill myself")
        self.assertIn("1564", member.sent[0])
        self.assertEqual((message.replies, self.scolds), ([], []))


class AdminWarnings(unittest.IsolatedAsyncioTestCase):
    """A warning an admin gives on command: a case like any other, told to
    the member, posted in #mod-log, and counted on the record."""

    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        message = mock.create_autospec(discord.Message, instance=True)
        message.id = 901
        self.log = mock.create_autospec(discord.TextChannel, instance=True)
        self.log.send = mock.AsyncMock(return_value=message)
        self.patch = mock.patch.object(layout, "channel", return_value=self.log)
        self.patch.start()
        self.guild = mock.create_autospec(discord.Guild, instance=True)
        self.guild.name = "Test"
        self.member = mock.create_autospec(discord.Member, instance=True)
        self.member.id = 7
        self.member.send = mock.AsyncMock()

    def tearDown(self):
        self.patch.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def test_it_is_a_case_on_the_record_and_is_posted_in_mod_log(self):
        case = await moderator.warn_by_admin(self.guild, self.member, 2, "Keep it civil.", 42)
        self.assertEqual((case["action"], case["decided_by"]), (cases.WARN, cases.BY_ADMIN))
        self.assertEqual(cases.record_of(7, int(time.time()), 30),
                         {"warnings": 1, "timeouts": 0})
        self.assertEqual(cases.get(case["no"])["log_message_id"], 901)
        embed = self.log.send.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "Case 1 · Warning")
        self.assertEqual([f.value for f in embed.fields if f.name == "Decided by"],
                         ["<@42>, an admin, alone"])

    async def test_the_member_is_told_why_and_can_appeal(self):
        await moderator.warn_by_admin(self.guild, self.member, 2, "Keep it civil.", 42)
        self.member.send.assert_awaited_once()
        self.assertIn("Keep it civil.", self.member.send.await_args.args[0])
        self.assertIn("Rule 2", self.member.send.await_args.args[0])

    async def test_an_appeal_says_an_admin_decided_it(self):
        case = await moderator.warn_by_admin(self.guild, self.member, 2, "Keep it civil.", 42)
        _, details = appeals.appeal_text(case, "It was a joke.")
        self.assertIn("decided by an admin alone", details)
        self.assertNotIn("None", details)

    async def test_warnings_from_admins_add_up_to_a_timeout(self):
        for _ in range(2):
            await moderator.warn_by_admin(self.guild, self.member, 2, "Again.", 42)
        record = cases.record_of(7, int(time.time()), 30)
        self.assertEqual(record, {"warnings": 2, "timeouts": 0})
        self.assertEqual(judge.sanction(judge.MILD, record, settings.current()).action,
                         cases.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
