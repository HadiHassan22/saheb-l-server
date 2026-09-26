"""Checks for the admins' powers: the Admin role keeps Discord's powers and
stays on the admins alone, what admins do with Discord's own tools is
posted in #server-log, and only admins get the admin tools in #ask-saheb.
Fake Discord objects; no network.

    python -m unittest
"""

import json
import shutil
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import discord

import admins
import assistant
import guard
import layout
import quick
import store

OWNER, ADMIN, STRANGER, BOT = 1, 7, 9, 2


def role(id, name, position=1, permissions=None, members=()):
    r = mock.Mock(spec=discord.Role)
    r.id, r.name, r.position, r.managed = id, name, position, False
    r.permissions = permissions or discord.Permissions.none()
    r.members = list(members)
    r.__ge__ = lambda self, other: self.position >= other.position
    r.edit = mock.AsyncMock()
    return r


def member(id, roles=()):
    return types.SimpleNamespace(id=id, mention=f"<@{id}>", display_name=f"m{id}", bot=False,
                                 roles=list(roles), add_roles=mock.AsyncMock(),
                                 remove_roles=mock.AsyncMock())


class WithTempData(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        store.save("layout", {"guild_id": 99, "channels": {}, "messages": {}})
        self.said = []

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    async def report(self, text):
        self.said.append(text)

    def guild(self, *roles, members=()):
        bot_role = role(50, "Saheb l Server", position=50)
        bot_role.managed = True
        by_id = {m.id: m for m in members}
        g = types.SimpleNamespace(id=99, owner_id=OWNER, roles=[*roles, bot_role],
                                  channels=[], get_member=by_id.get)
        g.me = types.SimpleNamespace(id=BOT, top_role=bot_role)
        g.get_role = lambda rid: next((r for r in g.roles if r.id == rid), None)
        return g


class Role(WithTempData):
    async def test_the_admin_role_keeps_its_powers_and_only_admins_hold_it(self):
        admins.add(ADMIN)
        stranger, admin, owner = member(STRANGER), member(ADMIN), member(OWNER)
        admin_role = role(20, "Admin", position=10, members=[stranger, owner])
        mods = role(21, "Mods", permissions=discord.Permissions(ban_members=True))
        g = self.guild(admin_role, mods, members=[stranger, admin, owner])
        await guard.sweep(g, self.report)
        admin_role.edit.assert_awaited_once_with(permissions=admins.POWERS,
                                                 reason="The admins' role keeps its powers")
        mods.edit.assert_awaited()  # every other role still loses its powers
        stranger.remove_roles.assert_awaited_once()
        owner.remove_roles.assert_not_awaited()
        admin.add_roles.assert_awaited_once()
        self.assertTrue(any("Took the Admin role from <@9>" in s for s in self.said))
        self.assertEqual(admins.role_id(), 20)

    async def test_the_owner_and_admins_pick_admins(self):
        admins.add(ADMIN)
        home = types.SimpleNamespace(id=99, owner_id=OWNER)
        asking = lambda user: types.SimpleNamespace(guild=home,
                                                    user=types.SimpleNamespace(id=user))
        self.assertIsNone(admins._refusal(asking(OWNER)))
        self.assertIsNone(admins._refusal(asking(ADMIN)))
        self.assertIn("owner and the admins", admins._refusal(asking(STRANGER)))


class AuditLog(WithTempData):
    def entry(self, action, user_id, target, reason=None, before=None, after=None):
        g = self.guild()
        return types.SimpleNamespace(
            guild=g, user_id=user_id, action=action, target=target, reason=reason,
            changes=types.SimpleNamespace(before=before or types.SimpleNamespace(),
                                          after=after or types.SimpleNamespace()))

    async def posted(self, entry):
        with mock.patch.object(layout, "server_log", mock.AsyncMock()) as logged:
            await admins.on_audit_log_entry(entry)
        return [call.args[1] for call in logged.call_args_list]

    async def test_what_an_admin_does_in_discord_is_posted(self):
        admins.add(ADMIN)
        said = await self.posted(self.entry(discord.AuditLogAction.kick, ADMIN,
                                            member(5), reason="Spam"))
        self.assertEqual(said, ["<@7> kicked <@5>, as an admin, with Discord's own "
                                "tools. Reason: Spam"])
        until = datetime(2026, 9, 26, tzinfo=timezone.utc)
        said = await self.posted(self.entry(discord.AuditLogAction.member_update, OWNER,
                                            member(5),
                                            after=types.SimpleNamespace(timed_out_until=until)))
        self.assertIn(f"timed out <@5> until <t:{int(until.timestamp())}:f>", said[0])

    async def test_an_admin_changing_their_own_nickname_is_not_posted(self):
        admins.add(ADMIN)
        self.assertEqual(await self.posted(self.entry(discord.AuditLogAction.member_update,
                                                      ADMIN, member(ADMIN))), [])

    async def test_the_bot_and_members_who_arent_admins_are_not_posted(self):
        self.assertEqual(await self.posted(self.entry(discord.AuditLogAction.kick, BOT,
                                                      member(5))), [])
        self.assertEqual(await self.posted(self.entry(discord.AuditLogAction.kick, STRANGER,
                                                      member(5))), [])

    async def test_giving_the_admin_role_in_discord_makes_an_admin(self):
        admins.add(ADMIN)
        store.save("admin_role", {"id": 20})
        admin_role = role(20, "Admin")
        entry = self.entry(discord.AuditLogAction.member_role_update, ADMIN, member(8),
                           after=types.SimpleNamespace(roles=[admin_role]))
        entry.guild.roles.append(admin_role)
        with mock.patch.object(admins, "_update_log_channel", mock.AsyncMock()):
            await self.posted(entry)
        self.assertTrue(admins.is_admin(8))
        entry.changes = types.SimpleNamespace(before=types.SimpleNamespace(roles=[admin_role]),
                                              after=types.SimpleNamespace(roles=[]))
        with mock.patch.object(admins, "_update_log_channel", mock.AsyncMock()):
            await self.posted(entry)
        self.assertFalse(admins.is_admin(8))


class Tools(WithTempData):
    async def test_admin_tools_answer_admins_only(self):
        g = self.guild(members=[member(8)])
        ctx = assistant.Context(guild=g, member=member(STRANGER))
        said = json.loads(await assistant.run_tool(ctx, "set_admin",
                                                   {"member": "<@8>", "admin": True}))
        self.assertEqual(said, {"error": "No such tool."})
        ctx.admin = True
        with mock.patch.object(admins, "make", mock.AsyncMock(return_value="m8 is now an admin.")):
            said = json.loads(await assistant.run_tool(ctx, "set_admin",
                                                       {"member": "<@8>", "admin": True}))
        self.assertEqual(said, {"result": "m8 is now an admin."})

    async def test_giving_a_role_to_everyone_is_admins_only(self):
        ctx = assistant.Context(guild=self.guild(), member=mock.Mock(spec=discord.Member))
        said = json.loads(await assistant.run_tool(ctx, "give_role_to_all",
                                                   {"role": "Gamers"}))
        self.assertEqual(said, {"error": "No such tool."})
        ctx.admin = True
        with mock.patch.object(quick, "give_role_to_all",
                               mock.AsyncMock(return_value="Done: Gamers is now on 3 members.")) as give:
            said = json.loads(await assistant.run_tool(ctx, "give_role_to_all",
                                                       {"role": "Gamers"}))
        give.assert_awaited_once_with(ctx.member, "Gamers")
        self.assertEqual(said, {"result": "Done: Gamers is now on 3 members."})


if __name__ == "__main__":
    unittest.main()
