"""Following each passed proposal through the self-update workflow, and
saying what happened under the proposal's card in #proposals.

The workflow (.github/workflows/self-update.yml) writes the change for
proposal N on a branch named `proposal-N`, checks it, and records the
outcome as a pull request:

- merged: every check passed and it is deploying;
- closed with the label `no-change`: the proposal needs no code change,
  or can't be done without touching the protected core;
- closed with the label `failed`: the change failed a check;
- a merged `revert-proposal-N`: the new version didn't come up, so it was
  rolled back.

The bot reads these from GitHub's public API every five minutes, with no
key: the repository is public. When the commit it is running is a
proposal's, it says that proposal is live.

Members get the status and the summary written for them, never a link:
the repository is under the owner's own GitHub account, and linking it
from the server would tie the two together. Admins can ask for the link
with /admin github, which only they see.
"""

import logging
import os
import re

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

import admins
import health
import proposals
import store
import voting_ui

log = logging.getLogger("updates")

# Railway names the repository it deploys from; the fallback is for
# running locally.
REPO = (f"{os.environ.get('RAILWAY_GIT_REPO_OWNER') or 'HadiHassan22'}/"
        f"{os.environ.get('RAILWAY_GIT_REPO_NAME') or 'saheb-l-server'}")
PULLS = f"https://api.github.com/repos/{REPO}/pulls"

WRITING, NO_CHANGE, FAILED, MERGED, LIVE, ROLLED_BACK = (
    "writing", "no change", "failed", "merged", "live", "rolled back")
# A stage is only ever announced once, and never goes backwards.
ORDER = [WRITING, NO_CHANGE, FAILED, MERGED, LIVE, ROLLED_BACK]

BRANCH = re.compile(r"^(revert-)?proposal-(\d+)$")


def proposal_of(pr):
    match = BRANCH.match(pr["head"]["ref"])
    return int(match[2]) if match else None


def stage_of(pr):
    """What a pull request says about its proposal, or None."""
    if pr["head"]["ref"].startswith("revert-"):
        return ROLLED_BACK if pr.get("merged_at") else None
    if pr.get("merged_at"):
        return MERGED
    if pr["state"] == "open":
        return WRITING
    labels = {label["name"] for label in pr.get("labels", [])}
    return NO_CHANGE if "no-change" in labels else FAILED


LINK = re.compile(r"<?https?://\S+>?")


def summary_of(pr):
    """What the workflow wrote for members, without the line saying how the
    proposal was approved and without any link."""
    body = (pr or {}).get("body") or ""
    kept = body.split("\n\n", 1)[1] if body.startswith("Proposal ") and "\n\n" in body else body
    kept = LINK.sub("", kept).strip()
    return kept[:1500] + ("…" if len(kept) > 1500 else "")


def message(no, stage, summary=""):
    said = {
        WRITING: f"The change for proposal {no} is written and being checked.",
        MERGED: f"Proposal {no} is written as code, passed every check, and is deploying.",
        LIVE: f"Proposal {no} is live.",
        NO_CHANGE: f"Proposal {no} needs no code change, or can't be done without "
                   "touching the protected core.",
        FAILED: f"Proposal {no} couldn't be put into effect: the change failed a check.",
        ROLLED_BACK: f"Proposal {no} was rolled back: the new version didn't start.",
    }[stage]
    if summary and stage in (MERGED, NO_CHANGE, FAILED):
        said += "\n\n" + summary
    return said


def _saved():
    return store.load("updates", {"stages": {}, "commits": {}})


def advance(no, stage, pr=None):
    """Record `stage` for proposal `no` if it moves it forward. Returns
    True if it did, meaning it should be announced."""
    saved = _saved()
    old = saved["stages"].get(str(no))
    if old is not None and ORDER.index(stage) <= ORDER.index(old):
        return False
    saved["stages"][str(no)] = stage
    if pr and pr.get("html_url") and stage != ROLLED_BACK:
        saved.setdefault("links", {})[str(no)] = pr["html_url"]
    if stage == MERGED and pr and pr.get("merge_commit_sha"):
        saved["commits"][pr["merge_commit_sha"][:7]] = no
    store.save("updates", saved)
    return True


def running_proposal():
    """The proposal whose merge is the commit now running, if any."""
    return _saved()["commits"].get(health.COMMIT)


async def _say(client, no, text):
    await voting_ui.reply_to(client, proposals.get(no), text)


async def _pull_requests():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(PULLS, params={"state": "all", "per_page": "100",
                                              "sort": "updated", "direction": "desc"},
                               headers={"Accept": "application/vnd.github+json"}) as r:
            if r.status != 200:
                raise RuntimeError(f"GitHub answered {r.status}")
            return await r.json()


@tasks.loop(minutes=5)
async def follow(client):
    await client.wait_until_ready()
    try:
        live = running_proposal()
        if live is not None and advance(live, LIVE):
            await _say(client, live, message(live, LIVE))
        for pr in reversed(await _pull_requests()):
            no = proposal_of(pr)
            stage = stage_of(pr)
            if no is None or stage is None:
                continue
            p = proposals.get(no)
            if not p or p["status"] != proposals.PASSED:
                continue
            if advance(no, stage, pr):
                await _say(client, no, message(no, stage, summary_of(pr)))
    except Exception as e:
        # GitHub limits unauthenticated calls; the next round tries again.
        log.warning(f"could not follow updates: {e!r}")


def link(no=None):
    """The repository, or proposal `no`'s pull request if it has one."""
    if no is not None:
        return _saved().get("links", {}).get(str(no))
    return f"https://github.com/{REPO}"


@admins.group.command(name="github",
                      description="Admins: the code behind the bot, seen only by you")
@app_commands.describe(proposal="A proposal's number, for its code change (optional)")
async def github(interaction: discord.Interaction, proposal: int = None):
    if not admins.allowed(interaction.user.id, interaction.guild):
        return await interaction.response.send_message(
            "Only admins can see where the code is kept.", ephemeral=True)
    found = link(proposal)
    text = (f"Proposal {proposal}'s code change: <{found}>" if found
            else f"Proposal {proposal} has no code change yet." if proposal is not None
            else f"The code: <{link()}>")
    await interaction.response.send_message(text, ephemeral=True)


def setup(client):
    follow.start(client)
