# CLAUDE.md

Guidance for Claude Code in this repository. It is read by the owner's
interactive sessions and by every self-update run (see below), so it holds
nothing private. This file is in the protected core: only the owner
changes it, by committing.

Read README.md (what the bot does, as members see it) and PROTECTED.md
(what no change may touch) before changing anything.

## What this is

Saheb l Server is a Discord bot that is the sole moderator and governor of
one server. Members vote on what it does; passed proposals are carried out
by code (`actions.py`) or, when they need new code, by the self-update
workflow rewriting the bot. Admins (`admins.py`) can do anything a vote
can, at once, but only through the bot, which logs it in #server-log.

## Commands

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -W ignore -m unittest                    # all tests
.venv/bin/python -W ignore -m unittest test_proposals     # one file
.venv/bin/python -W ignore -m unittest test_proposals.Settings.test_applied_value_persists
.venv/bin/python bot.py        # needs DISCORD_TOKEN in .env
```

Python 3.13, discord.py 2.7, `unittest` only. `calibrate.py` and
`chat_eval.py` call real models and cost money; run them only when asked.

## Architecture

Flat modules at the root, one feature each. `bot.py` connects, adopts the
first server it joins as home (leaving any other), calls each module's
`setup()`, and routes Discord events to them.

- **Pure logic, no Discord or network:** `proposals.py` (vote lifecycle,
  times passed in as epoch seconds), `judge.py` (routing a flagged
  message), `settings.py` (every tunable number, with bounds fixed in
  code), `cases.py`, `conduct.py`. Test these directly.
- **Voting:** `proposals.py` is the lifecycle every proposal shares.
  Each kind of proposal (`kinds.py`) is one module that says how it
  opens, what Yes and No mean, and what it does when it passes or not:
  `code_changes.py` (general), `setting_changes.py`, `actions.py` (server
  changes), `appeals.py`. Every ending, a vote closing or an admin's Ship
  it or withdraw, goes through `ending.py`, which updates the card
  (`cards.py`), logs admin actions and calls the kind. `voting_ui.py`
  holds the commands, the vote buttons and opening.
- **Moderation:** AutoMod (`automod.py` word lists) flags, `moderator.py`
  gathers context and applies the sanction `judge.py` picks. The bot never
  reads unflagged messages.
- **#ask-saheb:** `chat.py` handles messages (only when tagged or replied
  to); `assistant.py` defines the tools and their tiers (look, personal,
  light, draft, and admin-only tools); `quick.py` does the instant ones.
  The bot does whatever an admin asks.
- **AI:** everything goes through one OpenRouter key; `ai.py` holds the
  models and budget, `providers.py` the provider interface.
- **Server shape:** `layout.py` builds and repairs channels and roles;
  `colors.py` name colors; `pickers.py` the other pickers in #roles (data,
  made by vote); `guard.py` strips moderation powers from every role but
  Admin, so roles stay cosmetic.
- **State:** `store.py`, JSON files in `data/` or the Railway volume.
  Things are stored by id, not name.
- **Self-update:** `.github/workflows/self-update.yml` runs
  `.github/selfupdate/run.py`, which has Claude Code write a passed
  proposal's change, runs the tests without secrets, checks the protected
  core (`protected.py`), has it reviewed, merges, and rolls back if
  `/healthz` (`health.py`) doesn't show the new commit. The bot starts
  it when a proposal passes (`workflow.py`, the owner's `/github-key`
  token); GitHub's timer is the backup. `updates.py` reports progress
  under the card and, with links, in #admin-log (only admins can read it:
  `admins.post`).

## Rules for every change

- **Protected core:** never edit the files PROTECTED.md lists or change
  the values it protects. The check in `.github/selfupdate/protected.py`
  refuses such changes, and `test_selfupdate.py` tests it.
- **No secrets, no environment.** New code may not read environment
  variables, keys or tokens, or run code built at runtime (`eval`, `exec`,
  `subprocess`, dynamic imports).
- **No GitHub links members can see.** No message, embed or answer may
  contain a link to the repository; `updates.summary_of` strips them and
  the protected-core check refuses added lines with `github.com` or
  `html_url`.
- **Roles never carry power, except Admin.** Anything that lets a member
  act on others goes through a vote or an admin. The Admin role has
  Discord's powers; `admins.py` keeps it on the admins alone and posts
  what they do with it in #server-log. A role may open a channel to its
  holders (seeing a channel isn't power).
- **Discord limits:** anything shown in Discord must fit (embed and
  message lengths, at most 25 command choices, name lengths); tests check
  these, so add such checks for new text.

## Conventions

- Keep pure logic Discord-free. Test Discord code with fakes
  (`mock.Mock(spec=discord.X)`, `SimpleNamespace`), never a live server or
  the network.
- Module docstrings say why, in plain English; match the comment density
  and naming around the code you touch. Behaviour changes update the
  README, which mirrors the #welcome text.
- Every new number that members might want to tune goes in `settings.py`
  with a fixed range.
- Commit messages: a short sentence as the title, then a prose body on
  what changed and why.
