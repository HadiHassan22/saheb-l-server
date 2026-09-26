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
import cards
import conduct
import guard
import layout
import proposals
import quick
import store

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


class Stickers(WithTempData):
    """Stickers by vote, mirroring emojis: a name and an attached image in,
    a name out."""

    def sticker(self, id, name):
        s = mock.Mock(spec=discord.GuildSticker)
        s.id, s.name = id, name
        s.delete = mock.AsyncMock()
        return s

    def guild(self, stickers=()):
        g = mock.create_autospec(discord.Guild, instance=True)
        g.stickers, g.sticker_limit = list(stickers), 5
        return g

    async def test_adding_a_sticker_uploads_the_attached_image(self):
        g = self.guild()
        action = {"kind": actions.STICKER_ADD, "name": "catdance",
                  "image": actions.save_image(b"pixels")}
        self.assertIsNone(await actions.check(g, action))
        said = await actions.carry_out(g, action)
        g.create_sticker.assert_awaited_once()
        kwargs = g.create_sticker.call_args.kwargs
        self.assertEqual((kwargs["name"], kwargs["emoji"], kwargs["reason"]),
                         ("catdance", "catdance", actions.REASON))
        sent = kwargs["file"]
        self.assertIsInstance(sent, discord.File)
        sent.reset()
        self.assertEqual(sent.fp.read(), b"pixels")
        self.assertIn("catdance is added", said)

    async def test_removing_a_sticker_deletes_the_one_by_that_name(self):
        s = self.sticker(40, "catdance")
        g = self.guild([s])
        action = {"kind": actions.STICKER_REMOVE, "name": "catdance"}
        self.assertIsNone(await actions.check(g, action))
        self.assertEqual(action["sticker_id"], 40)
        said = await actions.carry_out(g, action)
        s.delete.assert_awaited_once_with(reason=actions.REASON)
        self.assertIn("catdance is removed", said)

    async def test_a_sticker_needs_a_short_name_an_image_and_a_free_slot(self):
        g = self.guild([self.sticker(40, "catdance")])
        self.assertIn("2 to 30 characters", await actions.check(
            g, {"kind": actions.STICKER_ADD, "name": "x", "image": "i"}))
        self.assertIn("already a sticker", await actions.check(
            g, {"kind": actions.STICKER_ADD, "name": "catdance", "image": "i"}))
        self.assertIn("Attach the image", await actions.check(
            self.guild(), {"kind": actions.STICKER_ADD, "name": "nyan"}))
        full = self.guild([self.sticker(i, f"s{i}") for i in range(5)])
        self.assertIn("no sticker slots", await actions.check(
            full, {"kind": actions.STICKER_ADD, "name": "nyan", "image": "i"}))
        self.assertIn("no sticker by that name", await actions.check(
            g, {"kind": actions.STICKER_REMOVE, "name": "nyan"}))

    def test_the_proposal_says_what_will_happen(self):
        title, details = actions.describe({"kind": actions.STICKER_ADD, "name": "catdance"})
        self.assertEqual(title, "Add the sticker catdance")
        self.assertIn("attached image as the sticker **catdance**", details)
        title, details = actions.describe({"kind": actions.STICKER_REMOVE, "name": "catdance"})
        self.assertEqual(title, "Remove the sticker catdance")
        self.assertLessEqual(len("Proposal 99: " + title), 256)  # a card's title
        self.assertLessEqual(len(details), 4000)                 # one embed


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
        p = actions.KIND.open(8, {"kind": actions.BAN, "member": str(MEMBER),
                                  "member_name": "Tony", "reason": "Spam"}, NOW)
        self.assertEqual((p["excluded"], p["blind"], p["pass_percent"]), ([MEMBER], True, 66))
        with self.assertRaisesRegex(proposals.Refused, "own case"):
            proposals.cast(p["no"], MEMBER, 0, "no", NOW + 1)
        proposals.cast(p["no"], 9, 0, "yes", NOW + 1)
        votes = cards.card(proposals.get(p["no"])).fields[2].value
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


class GiveToEveryone(WithTempData):
    """quick.give_role_to_all: an admin gives an existing role to every
    member of the server in one go."""

    def member(self, id, name, *has):
        one = mock.Mock(spec=discord.Member)
        one.id, one.display_name, one.roles = id, name, list(has)
        one.add_roles = mock.AsyncMock()
        return one

    def server(self, *members, roles=()):
        guild = mock.Mock(spec=discord.Guild)
        guild.roles, guild.members = list(roles), list(members)
        asking = self.member(9, "Nestled")
        asking.guild = guild
        store.save("roles", {"40": {"joinable": True}})
        return asking

    async def test_only_a_role_made_by_vote_goes_round_the_whole_server(self):
        gamers, cedar = role(40, "Gamers"), role(41, "Cedar")
        maya = self.member(1, "Maya")
        asking = self.server(maya, roles=[gamers, cedar])
        for name in ("Cedar", "Saheb l Server", "Nope"):
            with self.assertRaisesRegex(quick.Refused, "made by vote"):
                await quick.give_role_to_all(asking, name)
        maya.add_roles.assert_not_awaited()

    async def test_it_gives_the_role_to_every_member_and_leaves_out_who_it_cant(self):
        gamers = role(40, "Gamers")
        maya, tony, rami = (self.member(2, "Maya", gamers), self.member(3, "Tony"),
                            self.member(4, "Rami"))
        tony.add_roles = mock.AsyncMock(
            side_effect=discord.HTTPException(mock.Mock(status=403), "no"))
        asking = self.server(maya, tony, rami, roles=[gamers])
        with mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            said = await quick.give_role_to_all(asking, "@gamers")
        maya.add_roles.assert_not_awaited()  # it has the role already
        rami.add_roles.assert_awaited_once_with(gamers, reason="Asked for by Nestled")
        self.assertIn("Gamers is now on 1 member", said)
        self.assertIn("1 member I can't act on", said)
        self.assertIn("<@9> gave every member the role Gamers", logged.call_args.args[1])

    async def test_when_everyone_has_the_role_it_says_so_and_still_logs_it(self):
        gamers = role(40, "Gamers")
        maya = self.member(2, "Maya", gamers)
        asking = self.server(maya, roles=[gamers])
        with mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            said = await quick.give_role_to_all(asking, "Gamers")
        self.assertEqual(said, "Everyone already has Gamers.")
        maya.add_roles.assert_not_awaited()
        logged.assert_awaited_once()


class Guard(WithTempData):
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

    async def test_a_role_it_cant_fix_is_reported_once_across_restarts(self):
        above = role(12, "Mods", position=60,
                     permissions=discord.Permissions(ban_members=True))
        g = guild([above])
        said = []

        async def report(text):
            said.append(text)
        await guard.sweep(g, report)
        await guard.sweep(g, report)  # as after a redeploy: only the saved state is kept
        self.assertEqual(len(said), 1)
        above.permissions = discord.Permissions(ban_members=True, kick_members=True)
        await guard.sweep(g, report)  # its powers changed: worth saying again
        above.permissions = discord.Permissions.none()
        await guard.sweep(g, report)  # fixed by the owner
        above.permissions = discord.Permissions(ban_members=True)
        await guard.sweep(g, report)  # and broken again
        self.assertEqual(len(said), 3)


if __name__ == "__main__":
    unittest.main()
