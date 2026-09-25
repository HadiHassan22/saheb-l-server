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

Each proposal is tried once. After a try that wasn't kept (failed, no
change, rolled back), an admin can ask for another with /admin retry: it
runs on its own branch, `proposal-N-try-2` and so on, and the workflow
shows it what the last try changed and why it wasn't kept. Pull requests
from earlier tries are then ignored.

The bot reads these from GitHub every five minutes (workflow.py, with the
owner's token if there is one, else the public API). When the commit it is
running is a proposal's, it says that proposal is live.

It also starts the workflow itself (workflow.py) as soon as a general
proposal passes, and again whenever one is still waiting and no run is
going: the workflow does one proposal per run, and GitHub's own timer for
it can go an hour without running.

The admins get more, in #admin-log (admins.py), which only they and the
owner can read: each stage with its pull request, every start of the
workflow, and the runs that fail, with links.

Members get the status and the summary written for them, never a link:
the repository is under the owner's own GitHub account, and linking it
from the server would tie the two together. Admins can ask for the link
with /admin github, which only they see.
"""

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import tasks

import admins
import cards
import health
import layout
import proposals
import store
import workflow

log = logging.getLogger("updates")

REPO = workflow.REPO

WRITING, NO_CHANGE, FAILED, MERGED, LIVE, ROLLED_BACK = (
    "writing", "no change", "failed", "merged", "live", "rolled back")
# A stage is only ever announced once, and never goes backwards.
ORDER = [WRITING, NO_CHANGE, FAILED, MERGED, LIVE, ROLLED_BACK]

BRANCH = re.compile(r"^(revert-)?proposal-(\d+)(?:-try-(\d+))?$")
# What an admin can ask to try again: a try that is over and wasn't kept.
RETRYABLE = (NO_CHANGE, FAILED, ROLLED_BACK)


def proposal_of(pr):
    match = BRANCH.match(pr["head"]["ref"])
    return int(match[2]) if match else None


def attempt_of(pr):
    """Which try at its proposal a pull request is, from 1."""
    match = BRANCH.match(pr["head"]["ref"])
    return int(match[3] or 1) if match else None


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
    await cards.reply(client, proposals.get(no), text)


async def _tell_admins(guild, text):
    if guild is not None:
        await admins.post(guild, text)


def waiting():
    """Passed general proposals the workflow hasn't taken up yet."""
    stages = _saved()["stages"]
    return [p["no"] for p in health.passed_proposals() if str(p["no"]) not in stages]


FAILED_RUN = ("failure", "timed_out", "startup_failure")


def run_news(runs, seen):
    """What to tell the admins about the workflow's `runs`, newest first as
    GitHub lists them. `seen` records what was already said, and is
    updated. A run someone started (the bot, or an admin by hand) is
    announced when it starts; the timer's runs, which mostly find nothing
    to do, aren't. A string of failed runs is announced once, and so is the
    first success after it. The first time, nothing is announced."""
    first = "done" not in seen
    seen.setdefault("done", [])
    seen.setdefault("started", [])
    seen.setdefault("failing", False)
    news = []
    for run in reversed(runs):
        where = f"run {run['run_number']}: <{run['html_url']}>"
        if run["status"] != "completed":
            if run["id"] not in seen["started"]:
                seen["started"].append(run["id"])
                if run["event"] == "workflow_dispatch" and not first:
                    news.append(f"The self-update workflow is running ({where})")
            continue
        if run["id"] in seen["done"]:
            continue
        seen["done"].append(run["id"])
        if first:
            continue
        if run["conclusion"] in FAILED_RUN and not seen["failing"]:
            seen["failing"] = True
            news.append(f"The self-update workflow failed ({where})")
        elif run["conclusion"] == "success" and seen["failing"]:
            seen["failing"] = False
            news.append(f"The self-update workflow works again ({where})")
    seen["done"], seen["started"] = seen["done"][-100:], seen["started"][-100:]
    return news


_last = {"at": 0.0, "refused": None}
# Starting again for proposals still waiting: not more often than this.
RETRY_EVERY = 15 * 60
_tasks = set()


async def start(guild, why):
    """Ask GitHub to run the workflow now, and tell the admins how it went.
    The timer is the backup, so a refusal only delays; the same refusal
    twice in a row is said once."""
    _last["at"] = time.time()
    try:
        await workflow.start()
    except workflow.Refused as e:
        log.warning(f"couldn't start the self-update workflow: {e}")
        if _last["refused"] != str(e):
            _last["refused"] = str(e)
            await _tell_admins(guild, f"Couldn't start the self-update workflow for {why}: "
                                      f"{e}. GitHub's timer will start it, within the hour "
                                      "usually.")
        return False
    _last["refused"] = None
    await _tell_admins(guild, f"Started the self-update workflow for {why}.")
    return True


def start_soon(guild, no):
    """Start the workflow for proposal `no`, which just passed, without
    holding up the rest of its ending."""
    async def run():
        try:
            await start(guild, f"proposal {no}")
        except Exception as e:
            log.error(f"starting the workflow for proposal {no} failed: {e!r}")
    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@tasks.loop(minutes=5)
async def follow(client):
    await client.wait_until_ready()
    guild = client.get_guild(layout.home_id() or 0)
    try:
        live = running_proposal()
        if live is not None and advance(live, LIVE):
            await _say(client, live, message(live, LIVE))
            await _tell_admins(guild, message(live, LIVE))
        for pr in reversed(await workflow.get("pulls", {
                "state": "all", "per_page": "100", "sort": "updated", "direction": "desc"})):
            no = proposal_of(pr)
            stage = stage_of(pr)
            if no is None or stage is None:
                continue
            p = proposals.get(no)
            if (not p or p["status"] != proposals.PASSED
                    or attempt_of(pr) != proposals.attempt(p)):
                continue
            if advance(no, stage, pr):
                await _say(client, no, message(no, stage, summary_of(pr)))
                await _tell_admins(guild, f"{message(no, stage)}\n<{pr['html_url']}>")
        runs = (await workflow.get(f"actions/workflows/{workflow.WORKFLOW}/runs",
                                   {"per_page": "20"}))["workflow_runs"]
        saved = _saved()
        for text in run_news(runs, saved.setdefault("runs", {})):
            await _tell_admins(guild, text)
        store.save("updates", saved)
        going = any(run["status"] != "completed" for run in runs)
        if (waiting() and not going and workflow.configured()
                and time.time() - _last["at"] >= RETRY_EVERY):
            await start(guild, "the proposals still waiting")
    except Exception as e:
        # GitHub limits calls without a token; the next round tries again.
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


def retry(no):
    """Have the workflow try proposal `no`'s code change again, and return
    the proposal. Raises proposals.Refused unless its last try is over and
    wasn't kept; checking that the caller is an admin is the caller's job."""
    saved = _saved()
    if saved["stages"].get(str(no)) not in RETRYABLE:
        raise proposals.Refused("Only a proposal whose code change failed, changed nothing "
                                "or was rolled back can be tried again.")
    p = proposals.retry(no)
    # Its stages start over, so the new try is announced like the first.
    del saved["stages"][str(no)]
    saved.get("links", {}).pop(str(no), None)
    store.save("updates", saved)
    return p


@admins.group.command(name="retry",
                      description="Admins: try a proposal's code change again")
@app_commands.describe(proposal="The proposal's number")
async def retry_command(interaction: discord.Interaction, proposal: int):
    if not admins.allowed(interaction.user.id, interaction.guild):
        return await interaction.response.send_message(
            "Only an admin can have a code change tried again.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        p = retry(proposal)
    except proposals.Refused as e:
        return await interaction.followup.send(str(e), ephemeral=True)
    try:
        await layout.server_log(
            interaction.guild, f"<@{interaction.user.id}> asked for proposal {p['no']} "
                               f"({p['title']}) to be tried again, as an admin.")
    except discord.HTTPException as e:
        log.error(f"proposal {p['no']}'s retry wasn't logged: {e!r}")
    await _say(interaction.client, p["no"],
               f"An admin asked for proposal {p['no']}'s code change to be tried again, "
               "starting from what went wrong last time. Progress will be posted here.")
    start_soon(interaction.guild, p["no"])
    await interaction.followup.send(
        f"Proposal {p['no']} will be tried again (try {proposals.attempt(p)}).",
        ephemeral=True)


def setup(client):
    follow.start(client)
