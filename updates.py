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
"""

import logging
import os
import re

import aiohttp
from discord.ext import tasks

import health
import proposals
import store

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


def message(no, stage, url):
    return {
        WRITING: f"The change for proposal {no} is written and being checked: <{url}>",
        MERGED: f"Proposal {no} is written as code, passed every check, and is "
                f"deploying: <{url}>",
        LIVE: f"Proposal {no} is live.",
        NO_CHANGE: f"Proposal {no} needs no code change, or can't be done without "
                   f"touching the protected core. Why: <{url}>",
        FAILED: f"Proposal {no} couldn't be put into effect: the change failed a "
                f"check. Details: <{url}>",
        ROLLED_BACK: f"Proposal {no} was rolled back: the new version didn't start. "
                     f"Details: <{url}>",
    }[stage]


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
    if stage == MERGED and pr and pr.get("merge_commit_sha"):
        saved["commits"][pr["merge_commit_sha"][:7]] = no
    store.save("updates", saved)
    return True


def running_proposal():
    """The proposal whose merge is the commit now running, if any."""
    return _saved()["commits"].get(health.COMMIT)


async def _say(client, no, text):
    p = proposals.get(no)
    channel = client.get_channel((p or {}).get("channel_id") or 0)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(p["message_id"])
        await message.reply(text, mention_author=False)
    except Exception:
        await channel.send(text)


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
            await _say(client, live, message(live, LIVE, ""))
        for pr in reversed(await _pull_requests()):
            no = proposal_of(pr)
            stage = stage_of(pr)
            if no is None or stage is None:
                continue
            p = proposals.get(no)
            if not p or p["status"] != proposals.PASSED:
                continue
            if advance(no, stage, pr):
                await _say(client, no, message(no, stage, pr["html_url"]))
    except Exception as e:
        # GitHub limits unauthenticated calls; the next round tries again.
        log.warning(f"could not follow updates: {e!r}")


def setup(client):
    follow.start(client)
