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


def guild(roles=(), channels=()):
    bot_role = role(99, "Saheb l Server", position=50, managed=True)
    g = types.SimpleNamespace(id=5, owner_id=OWNER, roles=[*roles, bot_role], channels=list(channels),
                              categories=[], emojis=[], emoji_limit=50)
    g.me = types.SimpleNamespace(id=BOT, top_role=bot_role)
    g.get_role = lambda rid: next((r for r in g.roles if r.id == rid), None)
    g.get_channel = lambda cid: next((c for c in g.channels if c.id == cid), None)
    return g


def channel(id, name):
    return types.SimpleNamespace(id=id, name=name)


def onboarding_prompt(title):
    return types.SimpleNamespace(title=title)


def with_onboarding(g, prompts):
    """Attach a fake `guild.onboarding()` returning `prompts` (titles), and
    record edits on the returned mock's `edit`."""
    fetched = types.SimpleNamespace(prompts=[onboarding_prompt(t) for t in prompts],
                                    edit=mock.AsyncMock())
    g.onboarding = mock.AsyncMock(return_value=fetched)
    return fetched


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


class Onboarding(WithTempData):
    def setUp(self):
        super().setUp()
        store.save("roles", {"40": {"joinable": True}})

    def option(self, **kwargs):
        return {"title": "Gaming", "channels": ["gaming"], **kwargs}

    async def test_an_option_needs_a_channel_or_a_role(self):
        g = guild(channels=[channel(1, "gaming")])
        with_onboarding(g, [])
        problem = await actions.check(g, {"kind": actions.ONBOARDING_ADD, "title": "Interests",
                                          "options": [{"title": "Gaming"}]})
        self.assertIn("needs at least one channel or role", problem)

    async def test_only_a_channel_that_exists_or_a_role_made_by_vote_can_be_offered(self):
        g = guild(channels=[channel(1, "gaming")], roles=[role(41, "Quiet")])
        with_onboarding(g, [])
        self.assertIn("no channel", await actions.check(
            g, {"kind": actions.ONBOARDING_ADD, "title": "Interests",
                "options": [self.option(channels=["nope"])]}))
        self.assertIn("made by vote", await actions.check(
            g, {"kind": actions.ONBOARDING_ADD, "title": "Interests",
                "options": [self.option(channels=[], roles=["Quiet"])]}))

    async def test_onboarding_must_be_turned_on(self):
        g = guild(channels=[channel(1, "gaming")])
        g.onboarding = mock.AsyncMock(side_effect=discord.HTTPException(mock.Mock(status=400), "x"))
        problem = await actions.check(
            g, {"kind": actions.ONBOARDING_ADD, "title": "Interests", "options": [self.option()]})
        self.assertIn("Onboarding isn't turned on", problem)

    async def test_adding_a_prompt_keeps_the_others_and_saves_the_new_one(self):
        g = guild(channels=[channel(1, "gaming")])
        fetched = with_onboarding(g, ["Pronouns"])
        action = {"kind": actions.ONBOARDING_ADD, "title": "Interests",
                  "options": [self.option()]}
        self.assertIsNone(await actions.check(g, action))
        await actions.carry_out(g, action)
        saved = fetched.edit.call_args.kwargs["prompts"]
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0].title, "Pronouns")
        self.assertEqual(saved[1].title, "Interests")
        self.assertEqual(saved[1].options[0].title, "Gaming")
        self.assertEqual([c.id for c in saved[1].options[0].channels], [1])

    async def test_editing_a_prompt_replaces_only_that_one(self):
        g = guild(channels=[channel(1, "gaming")])
        fetched = with_onboarding(g, ["Pronouns", "Interests"])
        action = {"kind": actions.ONBOARDING_EDIT, "number": 2, "title": "Hobbies",
                  "options": [self.option()]}
        self.assertIsNone(await actions.check(g, action))
        self.assertEqual(action["old_title"], "Interests")
        await actions.carry_out(g, action)
        saved = fetched.edit.call_args.kwargs["prompts"]
        self.assertEqual([p.title for p in saved], ["Pronouns", "Hobbies"])

    async def test_removing_a_prompt_by_a_bad_number_is_refused(self):
        g = guild(channels=[channel(1, "gaming")])
        with_onboarding(g, ["Pronouns"])
        problem = await actions.check(g, {"kind": actions.ONBOARDING_REMOVE, "number": 5})
        self.assertIn("There are 1 onboarding prompts", problem)

    async def test_removing_a_prompt_leaves_the_rest(self):
        g = guild(channels=[channel(1, "gaming")])
        fetched = with_onboarding(g, ["Pronouns", "Interests"])
        action = {"kind": actions.ONBOARDING_REMOVE, "number": 1}
        self.assertIsNone(await actions.check(g, action))
        await actions.carry_out(g, action)
        saved = fetched.edit.call_args.kwargs["prompts"]
        self.assertEqual([p.title for p in saved], ["Interests"])


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
        above = role(12, "Admin", position=60,
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
