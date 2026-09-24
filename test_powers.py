"""Checks for the wider powers: roles, rules and watch words by vote, votes
about a member, things done at once, and the guard that keeps every role
cosmetic. Fake Discord objects; no network.

    python -m unittest
"""

import shutil
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import discord

import actions
import automod
import conduct
import guard
import layout
import proposals
import quick
import store
import voting_ui

NOW = 1_800_000_000
OWNER, BOT, MEMBER = 1, 2, 7


class WithTempData(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)


def role(id, name, position=1, permissions=None, managed=False):
    r = mock.Mock(spec=discord.Role)
    r.id, r.name, r.managed, r.position = id, name, managed, position
    r.permissions = permissions or discord.Permissions.none()
    r.__ge__ = lambda self, other: self.position >= other.position
    r.edit = mock.AsyncMock()
    return r


def guild(roles=()):
    bot_role = role(99, "Saheb l Server", position=50, managed=True)
    g = types.SimpleNamespace(id=5, owner_id=OWNER, roles=[*roles, bot_role], channels=[],
                              categories=[], emojis=[], emoji_limit=50)
    g.me = types.SimpleNamespace(id=BOT, top_role=bot_role)
    g.get_role = lambda rid: next((r for r in g.roles if r.id == rid), None)
    g.get_channel = lambda cid: None
    return g


class Roles(WithTempData):
    async def test_a_new_role_has_no_powers_and_is_remembered(self):
        g = guild()
        g.create_role = mock.AsyncMock(return_value=role(40, "Gamers"))
        action = {"kind": actions.ROLE_CREATE, "name": "Gamers", "color": "#1E88E5"}
        self.assertIsNone(await actions.check(g, action))
        await actions.carry_out(g, action)
        kwargs = g.create_role.call_args.kwargs
        self.assertEqual(kwargs["permissions"], discord.Permissions.none())
        self.assertFalse(kwargs["hoist"])
        self.assertEqual(actions.voted_roles(), {40: {"joinable": True}})

    async def test_only_roles_made_by_vote_can_be_changed(self):
        g = guild([role(41, "Cedar")])
        problem = await actions.check(g, {"kind": actions.ROLE_DELETE, "role": "Cedar"})
        self.assertIn("made by vote", problem)
        self.assertIn("#1E88E5", await actions.check(
            g, {"kind": actions.ROLE_CREATE, "name": "X", "color": "blue"}))


class Rules(WithTempData):
    async def check(self, **action):
        return await actions.check(guild(), action)

    async def test_the_safety_floor_and_the_original_rules_hold(self):
        self.assertIn("safety floor", await self.check(
            kind=actions.RULE_EDIT, number=4, title="x", body="y"))
        self.assertIn("can't be removed", await self.check(kind=actions.RULE_REMOVE, number=2))
        self.assertIsNone(await self.check(kind=actions.RULE_EDIT, number=1,
                                           title="Be kind", body="Mostly."))

    async def test_added_rules_can_be_removed_and_titles_survive_removal(self):
        g = guild()
        with mock.patch.object(layout, "post_texts", mock.AsyncMock()):
            await actions.carry_out(g, {"kind": actions.RULE_ADD, "title": "No spoilers",
                                        "body": "Tag them."})
            self.assertEqual(conduct.rules()[-1], ("No spoilers", "Tag them."))
            self.assertIsNone(await self.check(kind=actions.RULE_REMOVE, number=9))
            await actions.carry_out(g, {"kind": actions.RULE_REMOVE, "number": 9})
        self.assertEqual(len(conduct.rules()), len(conduct.DEFAULT_RULES))
        self.assertIn("since removed", conduct.title(9))


class WatchWords(WithTempData):
    async def test_votes_change_what_is_watched_but_never_what_is_blocked(self):
        self.assertIn("safety floor", await actions.check(
            guild(), {"kind": actions.WATCH_REMOVE, "words": ["free nitro"]}))
        self.assertIn("aren't on", await actions.check(
            guild(), {"kind": actions.WATCH_REMOVE, "words": ["banana"]}))
        with mock.patch.object(automod, "install", mock.AsyncMock()), \
                mock.patch.object(layout, "channel", lambda g, n: None):
            await actions.carry_out(guild(), {"kind": actions.WATCH_ADD, "words": ["Tfeh"]})
            await actions.carry_out(guild(), {"kind": actions.WATCH_REMOVE, "words": ["clown"]})
        names = {name: trigger for name, trigger, _ in automod.plan()}
        self.assertEqual(names[automod.PREFIX + "watch words added by vote"].keyword_filter,
                         ["tfeh"])
        self.assertNotIn("clown", names[automod.PREFIX + "watch English"].keyword_filter)
        self.assertIn("free nitro", names[automod.PREFIX + "block scams and phone numbers"]
                      .keyword_filter)


class People(WithTempData):
    def people_guild(self, target_position=1):
        g = guild()
        member = types.SimpleNamespace(id=MEMBER, display_name="Tony",
                                       top_role=role(3, "x", position=target_position))
        g.fetch_member = mock.AsyncMock(return_value=member)
        return g

    async def test_a_member_vote_needs_a_mention_and_a_reason(self):
        g = self.people_guild()
        self.assertIn("Mention", await actions.check(g, {"kind": actions.KICK, "member": "Tony"}))
        self.assertIn("Say why", await actions.check(g, {"kind": actions.KICK,
                                                         "member": f"<@{MEMBER}>"}))
        action = {"kind": actions.BAN, "member": f"<@{MEMBER}>", "reason": "Spam"}
        self.assertIsNone(await actions.check(g, action))
        self.assertEqual(action["member_name"], "Tony")

    async def test_the_owner_and_the_bot_cant_be_removed(self):
        g = self.people_guild()
        for who in (OWNER, BOT):
            self.assertIn("can't be removed", await actions.check(
                g, {"kind": actions.BAN, "member": str(who), "reason": "x"}))

    def test_a_vote_about_a_member_is_blind_they_cant_vote_and_the_bar_is_higher(self):
        p = proposals.open_action(8, {"kind": actions.BAN, "member": str(MEMBER)},
                                  "Ban Tony", "Details", NOW, about=MEMBER)
        self.assertEqual((p["excluded"], p["blind"], p["pass_percent"]), ([MEMBER], True, 66))
        with self.assertRaisesRegex(proposals.Refused, "own case"):
            proposals.cast(p["no"], MEMBER, 0, "no", NOW + 1)
        proposals.cast(p["no"], 9, 0, "yes", NOW + 1)
        votes = voting_ui.card(proposals.get(p["no"])).fields[2].value
        self.assertIn("1 voted so far", votes)
        self.assertNotIn("1 yes", votes)


class Quick(WithTempData):
    def test_each_kind_has_a_daily_allowance(self):
        for _ in range(quick.DAILY["pin"]):
            quick.spend(MEMBER, "pin", NOW)
        with self.assertRaisesRegex(quick.Refused, "tomorrow"):
            quick.spend(MEMBER, "pin", NOW + 60)
        quick.spend(MEMBER, "invite", NOW + 60)
        quick.spend(MEMBER, "pin", NOW + quick.DAY + 1)

    def test_event_times_are_beirut_time_and_near_future(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        start = quick.beirut_time("2026-09-25 20:00", now)
        self.assertEqual(start, datetime(2026, 9, 25, 17, 0, tzinfo=timezone.utc))
        for bad in ("tomorrow at 8", "2026-09-24 12:00", "2027-01-01 10:00"):
            with self.assertRaises(quick.Refused):
                quick.beirut_time(bad, now)

    async def test_only_joinable_roles_made_by_vote_can_be_joined(self):
        store.save("roles", {"40": {"joinable": True}, "41": {"joinable": False}})
        gamers, staff = role(40, "Gamers"), role(41, "Quiet")
        member = types.SimpleNamespace(guild=guild([gamers, staff]),
                                       add_roles=mock.AsyncMock(), remove_roles=mock.AsyncMock())
        self.assertIn("in Gamers", await quick.join_role(member, "@gamers"))
        member.add_roles.assert_awaited_once_with(gamers, reason="Joined by asking")
        for name in ("Quiet", "Saheb l Server", "Nope"):
            with self.assertRaises(quick.Refused):
                await quick.join_role(member, name)

    async def test_pins_only_by_link_into_this_server(self):
        member = types.SimpleNamespace(id=MEMBER, guild=guild(), display_name="Hadi")
        with self.assertRaisesRegex(quick.Refused, "link"):
            await quick.pin(member, "https://discord.com/channels/999/1/2")
        with self.assertRaisesRegex(quick.Refused, "link"):
            await quick.pin(member, "pin the last message")


class Guard(unittest.IsolatedAsyncioTestCase):
    def test_powers_are_taken_and_everything_else_kept(self):
        kept = discord.Permissions(send_messages=True, connect=True, change_nickname=True)
        self.assertIsNone(guard.stripped(kept))
        taken = guard.stripped(discord.Permissions(administrator=True, send_messages=True))
        self.assertEqual(taken, discord.Permissions(send_messages=True))
        overwrite = discord.PermissionOverwrite(manage_messages=True, send_messages=True,
                                                ban_members=False)
        allow, deny = guard.stripped_overwrite(overwrite).pair()
        self.assertEqual((allow, deny), (discord.Permissions(send_messages=True),
                                         discord.Permissions(ban_members=True)))

    async def test_the_sweep_takes_powers_from_every_role_it_can_and_says_so(self):
        guard._warned.clear()
        mods = role(10, "Mods", permissions=discord.Permissions(ban_members=True))
        fine = role(11, "Gamers", permissions=discord.Permissions(send_messages=True))
        above = role(12, "Owner's", position=60, permissions=discord.Permissions(administrator=True))
        g = guild([mods, fine, above])
        said = []

        async def report(text):
            said.append(text)
        await guard.sweep(g, report)
        await guard.sweep(g, report)
        mods.edit.assert_awaited()
        self.assertEqual(mods.edit.call_args.kwargs["permissions"], discord.Permissions.none())
        fine.edit.assert_not_awaited()
        above.edit.assert_not_awaited()
        self.assertEqual(sum("only the server owner" in s for s in said), 1)
        self.assertTrue(any("ban_members" in s and "Mods" in s for s in said))


if __name__ == "__main__":
    unittest.main()
