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
import moderator
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

    async def test_configuration_details_are_posted_without_changing_reasons_or_filters(self):
        admins.add(ADMIN)
        entry = self.entry(discord.AuditLogAction.onboarding_update, ADMIN, None,
                           reason="Review setup", before=types.SimpleNamespace(enabled=False),
                           after=types.SimpleNamespace(enabled=True))
        said = await self.posted(entry)
        self.assertEqual(len(said), 1)
        self.assertIn("enabled: no → yes", said[0])
        self.assertTrue(said[0].endswith(" Reason: Review setup"))
        entry.guild.id = 100
        self.assertEqual(await self.posted(entry), [])

    async def test_private_channel_topic_values_never_reach_public_log(self):
        admins.add(ADMIN)
        entry = self.entry(discord.AuditLogAction.channel_update, ADMIN,
            types.SimpleNamespace(id=42, name="admin-log", mention="<#42>"),
            before=types.SimpleNamespace(topic="PRIVATE_OLD_INSTRUCTIONS", name="PRIVATE_OLD_NAME"),
            after=types.SimpleNamespace(topic="PRIVATE_NEW_INSTRUCTIONS", name="PRIVATE_NEW_NAME"))
        said = await self.posted(entry)
        self.assertEqual(len(said), 1)
        self.assertIn("topic: changed", said[0])
        self.assertNotIn("PRIVATE_OLD_INSTRUCTIONS", said[0])
        self.assertNotIn("PRIVATE_NEW_INSTRUCTIONS", said[0])
        self.assertIn("name: changed", said[0])
        self.assertNotIn("PRIVATE_OLD_NAME", said[0])
        self.assertNotIn("PRIVATE_NEW_NAME", said[0])

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


class AuditDetails(unittest.TestCase):
    def entry(self, action, target=None, before=None, after=None):
        return types.SimpleNamespace(
            action=getattr(discord.AuditLogAction, action), target=target,
            changes=types.SimpleNamespace(before=before or types.SimpleNamespace(),
                                          after=after or types.SimpleNamespace()))

    def test_missing_targets_have_action_specific_fallbacks(self):
        for action, label in (("onboarding_update", "server onboarding"),
                              ("onboarding_prompt_create", "server onboarding prompt"),
                              ("home_settings_update", "server home settings")):
            with self.subTest(action=action):
                entry = self.entry(action)
                del entry.target
                self.assertIn(label, admins.did(entry))
                self.assertNotIn("something", admins.did(entry))
        self.assertEqual(admins._target(self.entry("channel_delete")), "channel")

    def test_uncached_target_id_is_retained(self):
        entry = self.entry("onboarding_prompt_update", discord.Object(id=12345))
        self.assertIn("server onboarding prompt (ID 12345)", admins.did(entry))
        self.assertEqual(admins._target(self.entry("role_delete", discord.Object(id=456))),
                         "target (ID 456)")

    def test_public_name_and_deleted_name_fallbacks(self):
        self.assertEqual(admins._target(self.entry("channel_update",
                         types.SimpleNamespace(id=42, name="general", mention="<#42>"))), "<#42>")
        self.assertEqual(admins._target(self.entry("role_delete",
                         before=types.SimpleNamespace(name="Games"))), "Games")

    def test_onboarding_configuration_before_and_after(self):
        entry = self.entry("onboarding_update",
                          before=types.SimpleNamespace(enabled=False, default_channels=[]),
                          after=types.SimpleNamespace(enabled=True,
                              mode=discord.OnboardingMode.advanced,
                              default_channels=[discord.Object(id=42)]))
        text = admins.did(entry)
        self.assertIn("enabled: no → yes", text)
        self.assertIn("mode: unset → advanced", text)
        self.assertIn("default_channels: [] →", text)
        self.assertIn("ID 42", text)

    def test_prompt_public_configuration(self):
        option = discord.OnboardingPromptOption(title="Games", roles=[123], channels=[42])
        entry = self.entry("onboarding_prompt_update", discord.Object(id=5),
                          before=types.SimpleNamespace(title="Interests", required=False),
                          after=types.SimpleNamespace(title="Choose interests", required=True,
                              single_select=False, in_onboarding=True, options=[option]))
        text = admins.did(entry)
        for fragment in ("Interests → Choose interests", "required: no → yes",
                         "single_select: unset → no", "Games", "channel_ids=", "42",
                         "role_ids=", "123"):
            self.assertIn(fragment, text)

    def test_onboarding_prompts_list_is_public_and_bounded(self):
        prompt = discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice,
                                          title="Pick games", options=[])
        text = admins.did(self.entry("onboarding_update",
                                    after=types.SimpleNamespace(prompts=[prompt] * 20)))
        self.assertIn("Pick games", text)
        self.assertIn("+17 more", text)
        self.assertLess(len(text), 1100)

    def test_home_settings_nested_public_fields_only(self):
        entry = self.entry("home_settings_update", after=types.SimpleNamespace(
            enabled=True, welcome_message={"message": "Welcome", "author_ids": [9988],
                                            "token": "DO_NOT_PRINT"},
            resource_channels=[{"channel_id": "42", "title": "Rules",
                                "access_token": "DO_NOT_PRINT"}],
            new_member_actions=[{"channel_id": "43", "title": "Introduce yourself",
                                 "action_type": 1, "responses": ["PRIVATE_ANSWER"]}]))
        text = admins.did(entry)
        for fragment in ("Welcome", "Rules", "42", "Introduce yourself", "action_type=1"):
            self.assertIn(fragment, text)
        for secret in ("9988", "author_ids", "token", "DO_NOT_PRINT", "PRIVATE_ANSWER"):
            self.assertNotIn(secret, text)

    def test_changed_public_channel_role_and_guild_fields(self):
        cases = (("channel_update", "nsfw", False, True),
                 ("role_update", "mentionable", False, True),
                 ("guild_update", "afk_timeout", 60, 300))
        for action, field, old, new in cases:
            with self.subTest(action=action):
                text = admins.did(self.entry(action,
                    before=types.SimpleNamespace(**{field: old}),
                    after=types.SimpleNamespace(**{field: new})))
                self.assertIn(field + ":", text)
                self.assertIn(" → ", text)
        text = admins.did(self.entry("role_update", after=types.SimpleNamespace(
            permissions=discord.Permissions(administrator=True), colour=discord.Colour.red())))
        self.assertIn("permissions: unset → 8", text)
        self.assertIn("colour:", text)

    def test_topic_values_are_redacted_for_all_channel_actions_and_targets(self):
        private = types.SimpleNamespace(id=42, name="admin-log", mention="<#42>")
        for action in ("channel_create", "channel_update", "channel_delete"):
            for target in (private, discord.Object(id=42), None):
                with self.subTest(action=action, target_type=type(target).__name__):
                    before = (types.SimpleNamespace(topic="PRIVATE_OLD_INSTRUCTIONS")
                              if action != "channel_create" else None)
                    after = (types.SimpleNamespace(topic="PRIVATE_NEW_INSTRUCTIONS")
                             if action != "channel_delete" else None)
                    text = admins.did(self.entry(action, target, before, after))
                    self.assertIn("topic: changed", text)
                    self.assertNotIn("PRIVATE_OLD_INSTRUCTIONS", text)
                    self.assertNotIn("PRIVATE_NEW_INSTRUCTIONS", text)
        self.assertEqual(admins._audit_value("PRIVATE_TOPIC", "topic"), "changed")
        unchanged = admins.did(self.entry("channel_update", private,
            types.SimpleNamespace(topic="PRIVATE_UNCHANGED"),
            types.SimpleNamespace(topic="PRIVATE_UNCHANGED")))
        self.assertNotIn("topic:", unchanged)
        self.assertNotIn("PRIVATE_UNCHANGED", unchanged)

    def test_hidden_channel_names_are_redacted_in_changes_and_target_fallbacks(self):
        for action in ("channel_create", "channel_update", "channel_delete"):
            for target in (types.SimpleNamespace(id=42, name="PRIVATE_TARGET_NAME"),
                           discord.Object(id=42), None):
                with self.subTest(action=action, target_type=type(target).__name__):
                    before = (types.SimpleNamespace(name="PRIVATE_OLD_NAME")
                              if action != "channel_create" else None)
                    after = (types.SimpleNamespace(name="PRIVATE_NEW_NAME")
                             if action != "channel_delete" else None)
                    text = admins.did(self.entry(action, target, before, after))
                    self.assertIn("name: changed", text)
                    self.assertIn("channel", text)
                    for private in ("PRIVATE_TARGET_NAME", "PRIVATE_OLD_NAME", "PRIVATE_NEW_NAME"):
                        self.assertNotIn(private, text)
        self.assertEqual(admins._target(self.entry("channel_delete",
            types.SimpleNamespace(id=42, name="PRIVATE_TARGET_NAME"))), "channel (ID 42)")
        self.assertEqual(admins._target(self.entry("channel_delete",
            before=types.SimpleNamespace(name="PRIVATE_OLD_NAME"))), "channel")

    def test_named_channel_references_are_logged_as_ids_only(self):
        channel = types.SimpleNamespace(id=42, name="PRIVATE_REFERENCE_NAME")
        for action, field, value in (("guild_update", "afk_channel", channel),
                                     ("onboarding_update", "default_channels", [channel])):
            with self.subTest(action=action):
                text = admins.did(self.entry(action,
                    after=types.SimpleNamespace(**{field: value})))
                self.assertIn("ID 42", text)
                self.assertNotIn("PRIVATE_REFERENCE_NAME", text)
        self.assertEqual(admins._audit_value(channel), "ID 42")

    def test_unexpected_fields_and_objects_are_not_dumped(self):
        class Secret:
            def __repr__(self):
                raise AssertionError("must not repr arbitrary objects")
            def __str__(self):
                raise AssertionError("must not stringify arbitrary objects")
        text = admins.did(self.entry("channel_update", after=types.SimpleNamespace(
            name=Secret(), topic=Secret(), bitrate=Secret(),
            token="SECRET_TOKEN", password="SECRET_PASSWORD",
            unexpected={"secret": "SECRET_PAYLOAD"})))
        self.assertIn("unavailable", text)
        self.assertIn("topic: changed", text)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("password", text)
        self.assertNotIn("unexpected", text)

    def test_member_answers_are_never_summarized(self):
        answers = types.SimpleNamespace(responses="PRIVATE_ANSWER", answers="PRIVATE_ANSWER",
                                        selected_options=["PRIVATE_ANSWER"], title="PRIVATE_ANSWER")
        for action in ("member_update", "onboarding_update", "home_settings_update"):
            self.assertNotIn("PRIVATE_ANSWER", admins.did(self.entry(action, after=answers)))
        text = admins.did(self.entry("onboarding_prompt_update",
                          after=types.SimpleNamespace(options=["PRIVATE_ANSWER"])))
        self.assertNotIn("PRIVATE_ANSWER", text)

    def test_hostile_strings_and_collections_are_bounded(self):
        hostile = "@everyone <@123> **bold** \x00\n\u202e" + "x" * 10000
        entry = self.entry("channel_update", types.SimpleNamespace(name=hostile),
            after=types.SimpleNamespace(name=hostile, topic=hostile, nsfw=True,
                position=2, slowmode_delay=3, bitrate=64000, user_limit=50))
        text = admins.did(entry)
        self.assertLess(len(text), 1100)
        self.assertNotIn("@everyone", text)
        self.assertNotIn("<@123>", text)
        for control in ("\x00", "\n", "\u202e"):
            self.assertNotIn(control, text)
        self.assertNotIn("user_limit:", text)  # at most six changed fields
        self.assertEqual(text, admins.did(entry))
        recursive = []
        recursive.append(recursive)
        self.assertLess(len(admins._audit_value(recursive)), 200)

    def test_lossy_collection_summary_still_reports_fourth_item_change(self):
        old = [discord.Object(id=i) for i in (1, 2, 3, 4)]
        new = [discord.Object(id=i) for i in (1, 2, 3, 99)]
        text = admins.did(self.entry("onboarding_update",
            before=types.SimpleNamespace(default_channels=old),
            after=types.SimpleNamespace(default_channels=new)))
        self.assertIn("default_channels: changed (shown:", text)
        self.assertIn("+1 more", text)
        self.assertLess(len(text), 1100)

    def test_lossy_long_string_summary_still_reports_suffix_change(self):
        text = admins.did(self.entry("guild_update",
            before=types.SimpleNamespace(description="x" * 120 + "old suffix"),
            after=types.SimpleNamespace(description="x" * 120 + "new suffix")))
        self.assertIn("description: changed (shown:", text)
        self.assertNotIn("old suffix", text)
        self.assertNotIn("new suffix", text)
        self.assertLess(len(text), 1100)

    def test_hidden_prompt_options_and_type_changes_are_not_silent(self):
        old = discord.OnboardingPrompt(type=discord.OnboardingPromptType.multiple_choice,
            title="Pick games", options=[discord.OnboardingPromptOption(title="Old option")])
        new = discord.OnboardingPrompt(type=discord.OnboardingPromptType.dropdown,
            title="Pick games", options=[discord.OnboardingPromptOption(title="New option")])
        text = admins.did(self.entry("onboarding_update",
            before=types.SimpleNamespace(prompts=[old]),
            after=types.SimpleNamespace(prompts=[new])))
        self.assertIn("prompts: changed (shown:", text)

    def test_lossy_unknown_values_never_invoke_comparison_or_repr(self):
        class Hostile:
            def __repr__(self):
                raise AssertionError("must not repr payload")
            def __str__(self):
                raise AssertionError("must not stringify payload")
            def __eq__(self, other):
                raise AssertionError("must not compare payload")
        text = admins.did(self.entry("role_update",
            before=types.SimpleNamespace(name=Hostile()),
            after=types.SimpleNamespace(name=Hostile())))
        self.assertIn("name: changed (shown: unavailable)", text)
        old, new = [], []
        old.append(old)
        new.append(new)
        text = admins.did(self.entry("onboarding_update",
            before=types.SimpleNamespace(default_channels=old),
            after=types.SimpleNamespace(default_channels=new)))
        self.assertIn("default_channels: changed (shown:", text)
        self.assertLess(len(text), 1100)

    def test_real_audit_diff_missing_old_and_new_values_are_none(self):
        entry = self.entry("onboarding_prompt_update", discord.Object(id=123))
        entry.changes = discord.AuditLogChanges(entry, [
            {"key": "title", "new_value": "Pick games"},
            {"key": "single_select", "old_value": True},
            {"key": "required", "old_value": False, "new_value": True},
        ])
        self.assertIsNone(entry.changes.before.title)
        self.assertIsNone(entry.changes.after.single_select)
        text = admins.did(entry)
        self.assertIn("title: none → Pick games", text)
        self.assertIn("single_select: yes → none", text)
        self.assertIn("required: no → yes", text)

    def test_unchanged_and_non_whitelisted_actions_keep_existing_wording(self):
        entry = self.entry("guild_update", before=types.SimpleNamespace(name="Same"),
                          after=types.SimpleNamespace(name="Same"))
        self.assertEqual(admins.did(entry), "changed the server's settings")
        entry = self.entry("kick", member(5), after=types.SimpleNamespace(name="ignored"))
        self.assertEqual(admins.did(entry), "kicked <@5>")


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

    async def test_warning_a_member_is_admins_only(self):
        target = mock.create_autospec(discord.Member, instance=True)
        target.id, target.display_name = 8, "m8"
        guild = mock.create_autospec(discord.Guild, instance=True)
        guild.get_member.return_value = target
        asker = mock.create_autospec(discord.Member, instance=True)
        asker.id = ADMIN
        ctx = assistant.Context(guild=guild, member=asker)
        args = {"member": "<@8>", "rule": 2, "reason": "Keep it civil."}
        said = json.loads(await assistant.run_tool(ctx, "warn_member", args))
        self.assertEqual(said, {"error": "No such tool."})
        ctx.admin = True
        with mock.patch.object(moderator, "warn_by_admin",
                               mock.AsyncMock(return_value={"no": 4})) as warn, \
                mock.patch.object(layout, "server_log", mock.AsyncMock()) as server_log:
            said = json.loads(await assistant.run_tool(ctx, "warn_member", args))
        warn.assert_awaited_once_with(guild, target, 2, "Keep it civil.", ADMIN)
        server_log.assert_awaited_once()
        self.assertEqual(said, {"result": "Warned m8 as case 4. It counts on their record."})

    async def test_a_warning_names_a_rule_that_exists(self):
        target = mock.create_autospec(discord.Member, instance=True)
        target.id = 8
        guild = mock.create_autospec(discord.Guild, instance=True)
        guild.get_member.return_value = target
        asker = mock.create_autospec(discord.Member, instance=True)
        asker.id = ADMIN
        ctx = assistant.Context(guild=guild, member=asker, admin=True)
        with mock.patch.object(moderator, "warn_by_admin", mock.AsyncMock()) as warn:
            said = json.loads(await assistant.run_tool(
                ctx, "warn_member", {"member": "<@8>", "rule": 99, "reason": "Rude."}))
        warn.assert_not_awaited()
        self.assertIn("error", said)


if __name__ == "__main__":
    unittest.main()
