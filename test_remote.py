"""Checks for remote control (remote.py): only admins reach the browser,
a chat request waits for the admin who asked, members never see the tool,
and the protected-core check keeps it that way. No network.

    python -m unittest test_remote
"""

import importlib.util
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import discord

import admins
import assistant
import layout
import remote
import store

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location(
    "protected", HERE / ".github" / "selfupdate" / "protected.py")
protected = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protected)

OWNER, ADMIN, OTHER_ADMIN, MEMBER = 1, 2, 3, 4
URL = "https://relay.example"


class Session:
    """Answers the relay's requests from `answers` in turn, noting each."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def request(self, method, url, headers=None, **kwargs):
        self.calls.append((method, url, headers, kwargs))
        status, body = self.answers.pop(0)
        response = mock.MagicMock(status=status)
        response.json = mock.AsyncMock(return_value=body)
        response.__aenter__ = mock.AsyncMock(return_value=response)
        response.__aexit__ = mock.AsyncMock(return_value=False)
        return response


class WithTempData(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        self.guild = types.SimpleNamespace(id=99, owner_id=OWNER)
        for patcher in (mock.patch.object(layout, "home_id", lambda: 99),
                        mock.patch.object(layout, "server_log", mock.AsyncMock()),
                        mock.patch.object(admins, "post", mock.AsyncMock())):
            self.addCleanup(patcher.stop)
            patcher.start()
        admins.add(ADMIN)
        admins.add(OTHER_ADMIN)

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def set_up_relay(self):
        store.save("remote", {"url": URL, "token": "key"}, private=True)

    def interaction(self, user_id):
        return types.SimpleNamespace(
            guild=self.guild, user=types.SimpleNamespace(id=user_id, mention=f"<@{user_id}>"),
            response=types.SimpleNamespace(send_message=mock.AsyncMock(),
                                           defer=mock.AsyncMock(),
                                           send_modal=mock.AsyncMock(),
                                           edit_message=mock.AsyncMock()),
            followup=types.SimpleNamespace(send=mock.AsyncMock()))

    def said(self, interaction):
        return interaction.response.send_message.await_args.args[0]


class Relay(WithTempData):
    def test_every_instruction_goes_straight_to_the_server(self):
        told = remote.prompt("  change our vanity tag ")
        self.assertTrue(told.startswith(
            "use aside browser, go into the liban server then change our vanity tag"))
        self.assertTrue(told.endswith(remote.GUARD))

    async def test_nothing_is_sent_without_an_address_and_key(self):
        with mock.patch.object(remote.aiohttp, "ClientSession") as session:
            with self.assertRaisesRegex(remote.Refused, "/remote-key"):
                await remote.run("change our vanity tag")
        session.assert_not_called()

    async def test_a_job_is_followed_until_it_ends(self):
        self.set_up_relay()
        session = Session([(201, {"id": "j1", "status": "running"}),
                           (200, {"id": "j1", "status": "running"}),
                           (200, {"id": "j1", "status": "succeeded", "result": "Done.",
                                  "finished_at": 5})])
        slept = []

        async def sleep(seconds):
            slept.append(seconds)

        with mock.patch.object(remote.aiohttp, "ClientSession", lambda **kw: session):
            job = await remote.run("change our vanity tag", sleep=sleep)
        self.assertEqual(remote.report(job), "Done.")
        method, url, headers, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", URL + "/v1/jobs"))
        self.assertEqual(headers["Authorization"], "Bearer key")
        self.assertEqual(kwargs["json"], {"profile": "aside",
                                          "prompt": remote.prompt("change our vanity tag")})
        self.assertEqual([c[:2] for c in session.calls[1:]],
                         [("GET", URL + "/v1/jobs/j1")] * 2)
        self.assertEqual(slept, [remote.POLL, remote.POLL])

    async def test_it_gives_up_on_a_job_that_never_ends(self):
        self.set_up_relay()
        session = Session([(201, {"id": "j1", "status": "running"})] * 3)
        times = iter([0, 10, remote.GIVE_UP + 1])

        async def sleep(seconds):
            pass

        with mock.patch.object(remote.aiohttp, "ClientSession", lambda **kw: session):
            with self.assertRaisesRegex(remote.Refused, "still at it"):
                await remote.run("x", sleep=sleep, clock=lambda: next(times))

    async def test_a_refused_key_says_why(self):
        self.set_up_relay()
        with mock.patch.object(remote.aiohttp, "ClientSession",
                               lambda **kw: Session([(401, {})])):
            with self.assertRaisesRegex(remote.Refused, "refused the key"):
                await remote.run("x")

    def test_a_failure_reports_the_error(self):
        self.assertIn("browser crashed", remote.report(
            {"status": "failed", "error": "browser crashed"}))


class SlashCommands(WithTempData):
    async def test_members_cant_start_it(self):
        self.set_up_relay()
        with mock.patch.object(remote, "run", mock.AsyncMock()) as run:
            interaction = self.interaction(MEMBER)
            await remote.remote_control.callback(interaction, "change our vanity tag")
        self.assertIn("Only admins", self.said(interaction))
        run.assert_not_awaited()
        layout.server_log.assert_not_awaited()

    async def test_an_admin_starts_it_and_it_is_logged(self):
        self.set_up_relay()
        job = {"status": "succeeded", "result": "Vanity set to liban."}
        with mock.patch.object(remote, "run", mock.AsyncMock(return_value=job)) as run:
            interaction = self.interaction(ADMIN)
            await remote.remote_control.callback(interaction, "change our vanity tag")
        run.assert_awaited_once_with("change our vanity tag")
        first = layout.server_log.await_args_list[0].args[1]
        self.assertIn("<@2>", first)
        self.assertIn("change our vanity tag", first)
        self.assertIn("Vanity set to liban.", admins.post.await_args.args[1])
        self.assertNotIn("Vanity set", " ".join(
            c.args[1] for c in layout.server_log.await_args_list))
        self.assertEqual(interaction.followup.send.await_args.args[0], "Vanity set to liban.")

    async def test_one_request_at_a_time(self):
        self.set_up_relay()
        async with remote._busy:
            interaction = self.interaction(ADMIN)
            await remote.remote_control.callback(interaction, "x")
        self.assertIn("busy", self.said(interaction))

    async def test_any_admin_can_set_the_key_but_no_member(self):
        member = self.interaction(MEMBER)
        await remote.remote_key.callback(member)
        member.response.send_modal.assert_not_awaited()
        admin = self.interaction(ADMIN)
        await remote.remote_key.callback(admin)
        admin.response.send_modal.assert_awaited_once()

    async def form(self, user_id, url):
        form = remote.KeyForm()
        form.url._value, form.token._value = url, " key "
        interaction = self.interaction(user_id)
        with mock.patch.object(remote.aiohttp, "ClientSession",
                               lambda **kw: Session([(200, {"jobs": []})])):
            await form.on_submit(interaction)
        return interaction

    async def test_the_key_is_checked_and_kept_private(self):
        await self.form(MEMBER, URL)
        self.assertFalse(remote.configured())
        interaction = await self.form(ADMIN, "http://relay.example")
        self.assertIn("https://", interaction.followup.send.await_args.args[0])
        self.assertFalse(remote.configured())
        await self.form(ADMIN, URL)
        self.assertEqual(store.load("remote", {}), {"url": URL, "token": "key"})
        self.assertEqual((store.DATA_DIR / "remote.json").stat().st_mode & 0o777, 0o600)

    def test_members_dont_see_the_commands(self):
        for command in (remote.remote_control, remote.remote_key):
            self.assertTrue(command.default_permissions.administrator)
            self.assertTrue(command.guild_only)


class Chat(WithTempData):
    def setUp(self):
        super().setUp()
        self.set_up_relay()
        self.channel = mock.Mock(spec=discord.TextChannel)
        self.channel.send = mock.AsyncMock()
        patcher = mock.patch.object(admins, "log_channel",
                                    mock.AsyncMock(return_value=self.channel))
        patcher.start()
        self.addCleanup(patcher.stop)

    def member(self, user_id):
        return types.SimpleNamespace(id=user_id, mention=f"<@{user_id}>")

    def test_the_tool_is_only_offered_to_admins(self):
        self.assertIn("remote_control", {t["name"] for t in assistant.ADMIN_TOOLS})
        self.assertNotIn("remote_control", {t["name"] for t in assistant.TOOLS})
        self.assertEqual(assistant.TIER["remote_control"], assistant.ADMIN)
        self.assertNotIn("remote", assistant.SYSTEM.lower())

    async def test_a_member_cant_call_it_even_by_name(self):
        ctx = assistant.Context(guild=self.guild, member=self.member(MEMBER), admin=False)
        with mock.patch.object(remote, "ask", mock.AsyncMock()) as ask:
            said = await assistant.run_tool(ctx, "remote_control", {"instruction": "x"})
        self.assertIn("No such tool", said)
        ask.assert_not_awaited()
        # And if code ever let it through, remote.py checks again.
        self.assertEqual(await remote.ask(self.guild, self.member(MEMBER), "x"),
                         "No such tool.")
        self.channel.send.assert_not_awaited()

    async def test_a_chat_request_only_waits_in_admin_log(self):
        ctx = assistant.Context(guild=self.guild, member=self.member(ADMIN), admin=True)
        with mock.patch.object(remote, "run", mock.AsyncMock()) as run:
            said = await assistant.run_tool(ctx, "remote_control",
                                            {"instruction": "change our vanity tag"})
        self.assertIn("Run it", said)
        run.assert_not_awaited()
        sent = self.channel.send.await_args
        self.assertIn("change our vanity tag", sent.args[0])
        self.assertLessEqual(len(sent.args[0]), 2000)
        view = sent.kwargs["view"]
        self.assertEqual((view.admin_id, view.instruction), (ADMIN, "change our vanity tag"))

    async def press(self, view, user_id):
        interaction = self.interaction(user_id)
        await view.run_it.callback(interaction)
        return interaction

    async def test_only_the_admin_who_asked_can_run_it(self):
        await remote.ask(self.guild, self.member(ADMIN), "change our vanity tag")
        view = self.channel.send.await_args.kwargs["view"]
        job = {"status": "succeeded", "result": "Done."}
        with mock.patch.object(remote, "run", mock.AsyncMock(return_value=job)) as run:
            for someone in (MEMBER, OTHER_ADMIN):
                interaction = await self.press(view, someone)
                self.assertIn("Only the admin who asked", self.said(interaction))
            run.assert_not_awaited()
            await self.press(view, ADMIN)
        run.assert_awaited_once_with("change our vanity tag")
        self.assertTrue(view.is_finished())

    async def test_an_admin_removed_since_cant_run_it(self):
        await remote.ask(self.guild, self.member(ADMIN), "x")
        view = self.channel.send.await_args.kwargs["view"]
        admins.remove(ADMIN)
        with mock.patch.object(remote, "run", mock.AsyncMock()) as run:
            interaction = await self.press(view, ADMIN)
        self.assertIn("Only admins", self.said(interaction))
        run.assert_not_awaited()


class Protected(unittest.TestCase):
    def test_remote_control_is_protected(self):
        self.assertEqual(protected.path_problems(["remote.py"]),
                         ["changes a protected file: remote.py"])

    def test_no_other_file_reaches_the_browser_or_its_key(self):
        diff = ("+++ b/chat.py\n+c = store.load('remote', {})\n"
                "+p = store.DATA_DIR / 'remote.json'\n+t = remote._config()\n"
                "+job = await remote.run(text)\n+await remote._carry_out(i, text)\n"
                "+v = remote.Confirm(member.id, text)\n"
                "+said = await remote.ask(ctx.guild, ctx.member, text)\n")
        self.assertEqual(len(protected.access_problems(diff)), 6)

    def test_a_relay_key_is_caught_as_a_secret(self):
        self.assertTrue(protected.contains_secret(
            "token = 'al_" + "a1" * 10 + "_" + "Bc9_" * 10 + "'"))
