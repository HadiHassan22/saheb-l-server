"""Starting the self-update workflow from the bot, and reading GitHub with
the owner's token. PROTECTED: see PROTECTED.md.

GitHub's timer for the workflow is best-effort: it has gone over an hour
without running, and a passed proposal waits all that time. So the bot
asks GitHub to start the workflow as soon as a general proposal passes
(updates.py), and the timer stays as the backup.

Starting a workflow needs a token. The owner makes a fine-grained one for
this repository only, with only "Actions: read and write", and gives it to
the bot with /github-key. It is kept in a file only the bot's own user can
read, like the AI key, and it never leaves this file: other code can only
start the workflow, or read the repository through GitHub's API, by
calling this file. A leaked token could start the workflow, which only
acts on proposals the bot lists at /api/passed, and read or cancel its
runs; nothing else.

Without a token everything still works: reads use GitHub's public API
with no key, and passed proposals wait for the timer.
"""

import os

import aiohttp
import discord
from discord import app_commands

import admins
import store

# Railway names the repository it deploys from; the fallback is for
# running locally.
REPO = (f"{os.environ.get('RAILWAY_GIT_REPO_OWNER') or 'HadiHassan22'}/"
        f"{os.environ.get('RAILWAY_GIT_REPO_NAME') or 'saheb-l-server'}")
API = f"https://api.github.com/repos/{REPO}"
WORKFLOW = "self-update.yml"
TIMEOUT = aiohttp.ClientTimeout(total=30)
# Sent back on every call made with a fine-grained token that expires.
EXPIRY = "github-authentication-token-expiration"


class Refused(Exception):
    """GitHub couldn't be asked, or said no. Says why, for the admins."""


def _token():
    return store.load("github", {}).get("token", "")


def configured():
    return bool(_token())


def _headers(token):
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _why(status):
    return {
        401: "GitHub refused the token: it is wrong or has expired",
        403: "the token isn't allowed to (it needs Actions: read and write on this "
             "repository), or GitHub's rate limit was reached",
        404: "GitHub can't see the workflow with this token (it needs access to "
             "this repository)",
    }.get(status, f"GitHub answered {status}")


async def get(path, params=None):
    """GitHub's answer to GET `path` under this repository, as JSON. Uses
    the token when one is set and works with it, and the public API
    otherwise. Raises Refused."""
    token = _token()
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for attempt in ([token, ""] if token else [""]):
                async with session.get(f"{API}/{path}", params=params,
                                       headers=_headers(attempt)) as r:
                    if r.status == 200:
                        return await r.json()
                    status = r.status
    except (aiohttp.ClientError, TimeoutError) as e:
        raise Refused(f"GitHub couldn't be reached ({type(e).__name__})") from None
    raise Refused(_why(status))


async def start(token=None):
    """Ask GitHub to run the self-update workflow on main now. Returns when
    the token expires, or None. Raises Refused. `token` is one to try
    instead of the saved one."""
    token = token or _token()
    if not token:
        raise Refused("no GitHub token is set; the owner can set one with /github-key")
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(f"{API}/actions/workflows/{WORKFLOW}/dispatches",
                                    json={"ref": "main"}, headers=_headers(token)) as r:
                if r.status != 204:
                    raise Refused(_why(r.status))
                return r.headers.get(EXPIRY)
    except (aiohttp.ClientError, TimeoutError) as e:
        raise Refused(f"GitHub couldn't be reached ({type(e).__name__})") from None


class TokenForm(discord.ui.Modal, title="GitHub token"):
    token = discord.ui.TextInput(label="Token: this repo, Actions read and write",
                                 placeholder="github_pat_...", max_length=255)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        candidate = self.token.value.strip()
        # Starting the workflow is the only real test of the token. The run
        # does nothing if no proposal is waiting, and catches up if one is.
        try:
            expiry = await start(candidate)
        except Refused as e:
            return await interaction.followup.send(f"That token didn't work: {e}.",
                                                   ephemeral=True)
        store.save("github", {"token": candidate, "expires": expiry}, private=True)
        until = f" It expires {expiry}." if expiry else ""
        await interaction.followup.send(
            "Saved, and the self-update workflow started once to check it. From now "
            f"on the bot starts it as soon as a proposal passes.{until}", ephemeral=True)
        await admins.post(interaction.guild, "The owner set the GitHub token the bot uses "
                          f"to start the self-update workflow.{until}")


@app_commands.command(name="github-key",
                      description="Owner only: the token that lets the bot start updates")
@app_commands.default_permissions(administrator=True)
async def github_key(interaction: discord.Interaction):
    if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Only the server owner can set the GitHub token.", ephemeral=True)
    await interaction.response.send_modal(TokenForm())


def setup(tree):
    tree.add_command(github_key)
