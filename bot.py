"""Saheb l Server: connects to Discord, builds and keeps its server,
reports whether it is up, and loads each feature. See README.md.

It runs one server. The first server it is invited to becomes its home,
and it leaves any other it is added to.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

import appeals  # noqa: E402  (store.py reads its directory from the environment)
import health  # noqa: E402
import layout  # noqa: E402
import moderator  # noqa: E402
import updates  # noqa: E402
import voting_ui  # noqa: E402

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
        # the few before it; nothing else reads message text.
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.started_at = datetime.now(timezone.utc)
        self.home = None

    async def setup_hook(self):
        await health.serve(self)
        voting_ui.setup(self, self.tree)
        moderator.setup(self.tree)
        appeals.setup(self, self.tree)
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
        except discord.HTTPException as e:
            # Commands are still worth syncing; the next start retries the rest.
            log.error(f"building the server stopped partway: {e!r}")
        # Commands go to the home server alone, where they appear at once,
        # and nowhere globally, or they would show up twice.
        self.tree.copy_global_to(guild=home)
        await self.tree.sync(guild=home)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info(f"running {home.name}")

    async def on_automod_action(self, execution):
        await moderator.on_automod_action(execution)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    Bot().run(TOKEN, log_handler=None)
