# The protected core

A passed proposal can change anything about Saheb l Server except what is
listed here. The self-update workflow refuses any change that touches it,
before the change is merged. Only the server owner can change these, by
committing to the repository directly, and doing so is visible to everyone
in the repository's history.

## Files that can't be changed

| Path | Why |
| --- | --- |
| `.github/` | The self-update workflow and its checks. A change here could switch the checks off. |
| `PROTECTED.md` | This list. |
| `ai.py`, `store.py` | Where the AI key is kept and how it is used, and how private files are written. |
| `health.py` | The health check. Rollback relies on it to tell whether a new version came up. |
| `guard.py` | Takes moderation-level permissions off every role and channel override, so no member ever holds power over another. |
| `admins.py` | Who the admins are, and that only the owner picks them. No other file may touch the stored list of admins either. |
| `railway.json`, `railpack.json` | How the bot is deployed and health-checked. |
| `CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.agents/`, `.mcp.json` | Claude Code reads these by itself on every self-update run. A change here would instruct every later run. |

## Values that can't be changed

These live in files a proposal may otherwise change. The check compares
them with the version currently running.

- **Setting ranges.** No setting in `settings.py` can be removed, and the
  minimum and maximum of each can't change. New settings can be added.
- **The safety floor:**
  - every AutoMod rule that blocks, and every blocked word and pattern
    (scams and phone numbers), stays in `automod.py`. More can be added;
  - the doxxing, sexual content and scam questions stay in `judge.py`,
    under the same rules of conduct;
  - private information, sexual content and scam links are never quoted
    in `#mod-log` (`judge.HIDDEN_RULES` can only grow);
  - the self-harm support message keeps Embrace's lifeline (1564), and the
    score that triggers it can't be raised (`judge.SUPPORT_AT`).

- **What happens without a vote.** The things the bot does the moment
  it's asked (the personal and light tiers in `assistant.py`) can't grow:
  no tool can be added to them or moved into them. Tools can be removed
  from them, or added as drafts that need a vote.
- **The channels the bot depends on** (`actions.CORE`) stay protected
  from being renamed or deleted by vote.
- **The rules.** Rules 4 to 6 stay fixed (`conduct.FIXED`), and their
  original text can't change.

## What no change may do

- Give any role or member power over others: roles here are cosmetic.
  The one exception is set here, not by vote: admins the owner picks
  (`admins.py`) can skip the vote on a code change, which still goes
  through every check below. They can't skip any other vote.

- Read, print, store or send any key or token: the Discord token, the AI
  key, or any other secret. New code may not read environment variables
  at all.
- Run code it builds at runtime (`eval`, `exec`, `subprocess`, dynamic
  imports).
- Break Discord's Terms of Service or Community Guidelines.
