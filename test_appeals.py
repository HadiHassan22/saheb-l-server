"""Checks for appeals: who can appeal and vote, what the appeal says, and
carrying out the result. Fake Discord objects; no network.

    python -m unittest
"""

import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import appeals
import cases
import judge
import layout
import proposals
import store
import voting_ui

NOW = 1_800_000_000
SUBJECT, APPELLANT = 7, 8


class WithTempData(unittest.TestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def case(self, action=cases.TIMEOUT, rule=1, **fields):
        return cases.open_case(
            NOW, **{**dict(user_id=SUBJECT, action=action, minutes=60, deleted=True,
                           rule=rule, severity="serious", explanation="Insulted Rami.",
                           excerpt="ya 7mar", decided_by=judge.FIRST_CHECK), **fields})


class Withdrawing(WithTempData, unittest.IsolatedAsyncioTestCase):
    async def withdraw(self, user_id, no):
        sent, card = [], mock.Mock(edit=mock.AsyncMock())
        channel = mock.Mock(fetch_message=mock.AsyncMock(return_value=card))
        interaction = types.SimpleNamespace(
            user=types.SimpleNamespace(id=user_id, mention=f"<@{user_id}>"),
            guild=types.SimpleNamespace(id=99, owner_id=1),
            client=types.SimpleNamespace(get_channel=lambda cid: channel),
            response=types.SimpleNamespace(
                send_message=mock.AsyncMock(side_effect=lambda text, **k: sent.append(text))))
        with mock.patch.object(layout, "home_id", lambda: 99), \
                mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            await voting_ui.withdraw.callback(interaction, no, "Filed by mistake")
        return sent[0], card, logged

    async def test_an_admin_withdraws_an_appeal_and_the_case_can_be_appealed_again(self):
        case = self.case()
        p = proposals.open_appeal(APPELLANT, case["no"], SUBJECT, "Appeal", "Details", NOW)
        cases.update(case["no"], appeal=p["no"])
        said, card, logged = await self.withdraw(APPELLANT, p["no"])
        self.assertIn("Only an admin", said)
        logged.assert_not_awaited()
        said, card, logged = await self.withdraw(1, p["no"])  # the owner
        self.assertIn("withdrawn", said)
        card.edit.assert_awaited_once()
        self.assertIn("Filed by mistake", logged.call_args.args[1])
        self.assertEqual(proposals.get(p["no"])["status"], proposals.WITHDRAWN)
        self.assertIsNone(cases.why_not_appealable(cases.get(case["no"])))


class Rules(WithTempData):
    def test_each_standing_case_can_be_appealed_once(self):
        case = self.case()
        self.assertIsNone(cases.why_not_appealable(case))
        self.assertIn("no case", cases.why_not_appealable(None))
        self.assertIn("already been appealed",
                      cases.why_not_appealable(cases.update(case["no"], appeal=3)))
        other = cases.update(self.case()["no"], status=cases.OVERTURNED)
        self.assertIn("overturned", cases.why_not_appealable(other))

    def test_the_member_a_case_is_about_cannot_vote_on_it(self):
        p = proposals.open_appeal(APPELLANT, 1, SUBJECT, "Appeal", "Details", NOW)
        self.assertEqual((p["kind"], p["case_no"], p["excluded"]),
                         (proposals.APPEAL, 1, [SUBJECT]))
        with self.assertRaisesRegex(proposals.Refused, "own case"):
            proposals.cast(p["no"], SUBJECT, NOW - 30 * cases.DAY, "yes", NOW)
        proposals.cast(p["no"], APPELLANT, NOW - 30 * cases.DAY, "yes", NOW)

    def test_appeals_count_towards_the_open_proposal_limit(self):
        for n in range(3):
            proposals.open_appeal(APPELLANT, n, SUBJECT, "Appeal", "Details", NOW)
        with self.assertRaisesRegex(proposals.Refused, "limit"):
            proposals.open_appeal(APPELLANT, 9, SUBJECT, "Appeal", "Details", NOW)

    def test_appeal_record_counts_decided_appeals_only(self):
        for result in ("overturned", "upheld", None):
            cases.update(self.case()["no"], appeal_result=result)
        self.assertEqual(cases.appeal_record(), (1, 2))


class Text(WithTempData):
    def test_the_appeal_shows_the_case_the_reason_and_what_overturning_does(self):
        title, details = appeals.appeal_text(self.case(), "We were joking.")
        self.assertEqual(title, "Appeal of case 1: Timeout (60 minutes)")
        for part in ("<@7>", "No harassment", "Insulted Rami.", "||ya 7mar||",
                     "We were joking.", "lift the timeout", "can't be restored"):
            self.assertIn(part, details)

    def test_private_information_is_not_repeated(self):
        _, details = appeals.appeal_text(self.case(rule=4, excerpt="03 123456"), "Mistake.")
        self.assertNotIn("123456", details)

    def test_appeal_cards_vote_overturn_or_keep(self):
        p = proposals.open_appeal(APPELLANT, 1, SUBJECT, "Appeal of case 1", "Details", NOW)
        labels = [item.item.label for item in voting_ui.vote_buttons(p).children]
        self.assertEqual(labels, ["Overturn", "Keep"])
        self.assertIn("0 overturn · 0 keep", voting_ui.card(p).fields[2].value)


class Filing(WithTempData, unittest.IsolatedAsyncioTestCase):
    async def fake_publish(self, interaction, opener, guild=None):
        try:
            return opener(NOW)
        except proposals.Refused as e:
            self.refused.append(str(e))
            return None

    async def test_two_appeals_of_one_case_cannot_both_get_through(self):
        self.refused = []
        case = self.case()
        interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=APPELLANT))
        with mock.patch.object(voting_ui, "publish", self.fake_publish), \
                mock.patch.object(appeals, "_note", mock.AsyncMock()):
            await appeals.file(interaction, case["no"], "Mistake.", None)
            await appeals.file(interaction, case["no"], "Mistake again.", None)
        self.assertEqual(cases.get(case["no"])["appeal"], 1)
        self.assertEqual(len(self.refused), 1)


class Member:
    def __init__(self, timed_out=True):
        self.timed_out = timed_out
        self.lifted = False

    def is_timed_out(self):
        return self.timed_out

    async def timeout(self, length, reason=None):
        self.lifted = length is None


class Settling(WithTempData, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.member = Member()
        self.unbanned = []
        self.dms = []
        self.log_posts = []
        self.notes = []

        async def unban(user, reason=None):
            self.unbanned.append(user.id)

        async def fetch_member(user_id):
            return self.member

        async def create_invite(**kwargs):
            return types.SimpleNamespace(url="https://discord.gg/abc")

        async def send(text):
            self.log_posts.append(text)

        self.guild = types.SimpleNamespace(get_member=lambda uid: None,
                                           fetch_member=fetch_member, unban=unban)
        channels = {"welcome": types.SimpleNamespace(create_invite=create_invite),
                    "mod-log": types.SimpleNamespace(send=send)}

        async def dm(client, user_id, text):
            self.dms.append(text)
            return True

        async def note(guild, case, text):
            self.notes.append(text)

        self.client = types.SimpleNamespace(get_guild=lambda gid: self.guild)
        self.patches = [
            mock.patch.object(layout, "channel", lambda guild, name: channels.get(name)),
            mock.patch.object(appeals, "_tell", dm),
            mock.patch.object(appeals, "_note", note),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def closed(self, case, status):
        return {"kind": proposals.APPEAL, "no": 5, "case_no": case["no"], "status": status}

    async def test_an_overturned_timeout_is_lifted_and_leaves_the_record(self):
        case = self.case()
        await appeals.settle(self.client, self.closed(case, proposals.PASSED))
        self.assertTrue(self.member.lifted)
        after = cases.get(case["no"])
        self.assertEqual((after["status"], after["appeal_result"]),
                         (cases.OVERTURNED, "overturned"))
        self.assertEqual(cases.record_of(SUBJECT, NOW, 30), {"warnings": 0, "timeouts": 0})
        self.assertIn("timeout was lifted", self.notes[0])
        self.assertIn("can't be restored", self.notes[0])
        self.assertIn("1 of 1", self.log_posts[0])

    async def test_an_overturned_ban_unbans_and_sends_an_invite(self):
        case = self.case(action=cases.BAN)
        await appeals.settle(self.client, self.closed(case, proposals.PASSED))
        self.assertEqual(self.unbanned, [SUBJECT])
        self.assertIn("https://discord.gg/abc", self.dms[0])
        self.assertIn("sent an invite back", self.notes[0])

    async def test_a_failed_appeal_leaves_the_case_standing(self):
        case = self.case()
        await appeals.settle(self.client, self.closed(case, proposals.NO_QUORUM))
        after = cases.get(case["no"])
        self.assertEqual((after["status"], after["appeal_result"]), (cases.ACTIVE, "upheld"))
        self.assertFalse(self.member.lifted)
        self.assertIn("action stands", self.dms[0])
        self.assertIn("0 of 1", self.log_posts[0])

    async def test_other_proposals_are_ignored(self):
        await appeals.settle(self.client, {"kind": proposals.GENERAL, "status": "passed"})
        self.assertEqual((self.notes, self.log_posts), ([], []))


class Note(unittest.IsolatedAsyncioTestCase):
    async def test_the_appeal_line_is_added_once_then_replaced(self):
        embed = discord.Embed(title="Case 1")
        edits = []

        async def fetch_message(message_id):
            async def edit(embed):
                edits.append(embed)
            return types.SimpleNamespace(embeds=[embed], edit=edit)

        log_channel = types.SimpleNamespace(fetch_message=fetch_message)
        with mock.patch.object(layout, "channel", lambda guild, name: log_channel):
            case = {"no": 1, "log_message_id": 99}
            await appeals._note(None, case, "Under appeal")
            await appeals._note(None, case, "Overturned")
        fields = [(f.name, f.value) for f in edits[-1].fields]
        self.assertEqual(fields, [("Appeal", "Overturned")])


if __name__ == "__main__":
    unittest.main()
