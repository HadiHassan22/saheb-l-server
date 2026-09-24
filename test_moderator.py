"""The whole path from an AutoMod alert to a posted case, against fake
Discord objects and fake AI answers. No network and no Discord server.

    python -m unittest
"""

import shutil
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import ai
import cases
import layout
import moderator
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
        self.patches = [
            mock.patch.object(layout, "channel", lambda guild, name: self.log),
            mock.patch.object(ai, "review", self.fake_review),
        ]
        for p in self.patches:
            p.start()
        self.reviews = []
        self.review_answer = {}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def fake_review(self, prompt, schema):
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
        self.assertTrue(case["deleted"])
        self.assertEqual(channel.deleted, [123])
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

    async def test_the_record_escalates_to_a_timeout_then_a_ban(self):
        self.review_answer = {"explanation": "Insulted a member."}
        member = Member()
        for _ in range(2):
            cases.open_case(int(time.time()) - 60, user_id=member.id,
                            action=cases.TIMEOUT, minutes=60)
        with mock.patch.object(moderator, "COOLDOWN", 0):
            await self.run_alert(jev(1.8, harassment=0.96), member=member)
        self.assertEqual(cases.get(3)["action"], cases.BAN)

    async def test_a_severe_threat_bans_and_is_messaged_before_the_ban(self):
        self.review_answer = {"explanation": "Threatened a member's home."}
        member, _ = await self.run_alert(jev(2.8, threat=0.91),
                                         content="I know which building you live in")
        self.assertEqual(cases.get(1)["action"], cases.BAN)
        self.assertIn("Ban", member.sent[0])

    async def test_private_information_is_not_quoted_in_the_log(self):
        self.review_answer = {"explanation": "Posted a member's phone number."}
        await self.run_alert(jev(2.8, doxxing=0.95), content="her number is 03 123456")
        fields = {f.name: f.value for f in self.log.sent[0].fields}
        self.assertNotIn("123456", fields["Message"])

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


if __name__ == "__main__":
    unittest.main()
