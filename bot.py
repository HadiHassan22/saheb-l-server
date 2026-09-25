"""Saheb l Server: connects to Discord, builds and keeps its server,
reports whether it is up, and loads each feature. See README.md.

It runs one server. The first server it is invited to becomes its home,
and it leaves any other it is added to.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

import actions  # noqa: E402  (store.py reads its directory from the environment)
import admins  # noqa: E402
import appeals  # noqa: E402
import chat  # noqa: E402
import code_changes  # noqa: E402, F401  (each kind of proposal registers itself: kinds.py)
import colors  # noqa: E402
import guard  # noqa: E402
import health  # noqa: E402
import layout  # noqa: E402
import moderator  # noqa: E402
import pickers  # noqa: E402
import quick  # noqa: E402
import setting_changes  # noqa: E402, F401
import updates  # noqa: E402
import voting_ui  # noqa: E402
import workflow  # noqa: E402

log = logging.getLogger("bot")

TOKEN = (os.environ.get("DISCORD_TOKEN") or "").strip()
if not TOKEN:
    raise SystemExit(
        "DISCORD_TOKEN is not set. Locally it goes in a .env file next to "
        "bot.py; on Railway it is a service variable. It is the bot token "
        "from the Discord developer portal."
    )

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        # Privileged: switch it on in the developer portal (Bot -> Message
        # Content Intent). It lets the moderator read a flagged message and
        # the few before it, and the bot answer in #ask-saheb. Messages
        # anywhere else are never read.
        intents.message_content = True
        # Privileged too (Bot -> Server Members Intent). It lets the bot see
        # who is in the server, so a proposal's quorum counts people and not
        # other bots (proposals.quorum_for).
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.started_at = datetime.now(timezone.utc)
        self.home = None

    async def setup_hook(self):
        await health.serve(self)
        voting_ui.setup(self, self.tree)
        admins.setup(self.tree)
        moderator.setup(self.tree)
        workflow.setup(self.tree)
        appeals.setup(self, self.tree)
        colors.setup(self, self.tree)
        pickers.setup(self)
        chat.setup(self)
        quick.setup(self)
        updates.setup(self)

    async def on_ready(self):
        log.info(f"logged in as {self.user} ({self.user.id}), commit {health.COMMIT}")
        if self.home is not None:
            return  # a reconnect, not a first start
        home = self.get_guild(layout.home_id() or 0) or (
            self.guilds[0] if self.guilds else None)
        if home is None:
            log.info("not in any server yet; invite the bot to one")
            return
        await self.settle_in(home)

    async def on_guild_join(self, guild):
        if self.home is None:
            await self.settle_in(guild)
        elif guild.id != self.home.id:
            log.warning(f"left {guild.name}: this bot runs {self.home.name} only")
            await guild.leave()

    async def settle_in(self, home):
        self.home = home
        for other in self.guilds:
            if other.id != home.id:
                log.warning(f"left {other.name}: this bot runs {home.name} only")
                await other.leave()
        try:
            await layout.build(home)
            await pickers.install(home)
            await admins.log_channel(home)
            await guard.sweep(home, self.report)
        except discord.HTTPException as e:
            # Commands are still worth syncing; the next start retries the rest.
            log.error(f"building the server stopped partway: {e!r}")
        guard.hourly.start(self, home.id, self.report)
        # Commands go to the home server alone, where they appear at once,
        # and nowhere globally, or they would show up twice.
        self.tree.copy_global_to(guild=home)
        await self.tree.sync(guild=home)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info(f"running {home.name}")

    async def report(self, text):
        """What the guard took away, said publicly."""
        if self.home is not None:
            await layout.server_log(self.home, text)

    async def _changed(self, thing):
        if self.home is not None and thing.guild.id == self.home.id:
            asyncio.create_task(guard.soon(self.home, self.report))

    async def on_guild_role_create(self, role):
        await self._changed(role)

    async def on_guild_role_update(self, before, after):
        await self._changed(after)

    async def on_guild_channel_create(self, channel):
        await self._changed(channel)

    async def on_guild_channel_update(self, before, after):
        await self._changed(after)

    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            await self._changed(after)

    async def on_audit_log_entry_create(self, entry):
        # Discord's own record of what someone did; admins.py posts an
        # admin's in #server-log. Needs View Audit Log, which Administrator
        # includes.
        if self.home is not None and entry.guild.id == self.home.id:
            try:
                await admins.on_audit_log_entry(entry)
            except discord.HTTPException as e:
                log.warning(f"an admin's action wasn't posted: {e!r}")

    async def on_automod_action(self, execution):
        await moderator.on_automod_action(execution)

    async def on_message(self, message):
        await chat.on_message(message, self)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    Bot().run(TOKEN, log_handler=None)
