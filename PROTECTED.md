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
| `guard.py` | Takes moderation-level permissions off every role and channel override, the Admin role included, so nobody can act on the server except through the bot, which logs it. |
| `admins.py` | Who the admins are, and that only the owner picks them. No other file may touch the stored list of admins either. It also keeps `#admin-log` readable by the admins and the owner alone, checked before every post. |
| `workflow.py` | The GitHub token the owner gives with `/github-key`, which lets the bot start the self-update workflow. No other file may read it. |
| `railway.json`, `railpack.json` | How the bot is deployed and health-checked. |
| `CLAUDE.md`, `CLAUDE.local.md`, `.claude/`, `.agents/`, `.mcp.json` | Claude Code reads these by itself on every self-update run. A change here would instruct every later run. |

## Values that can't be changed

These live in files a proposal may otherwise change. The check compares
them with the version currently running. A proposal an admin shipped
without a vote may also narrow or remove setting ranges and change the
protected channels; the safety floor and rules 4 to 6 hold for everyone.

- **Setting ranges.** No setting in `settings.py` can be removed, and no
  range can narrow: a range can widen, and new settings can be added.
- **The safety floor:**
  - every AutoMod rule that blocks, and every blocked word and pattern
    (scams and phone numbers), stays in `automod.py`. More can be added;
  - the doxxing, sexual content and scam questions stay in `judge.py`,
    under the same rules of conduct;
  - private information, sexual content and scam links are never quoted
    in `#mod-log` (`judge.HIDDEN_RULES` can only grow);
  - the self-harm support message keeps Embrace's lifeline (1564), and the
    score that triggers it can't be raised (`judge.SUPPORT_AT`).

- **The channels the bot depends on** (`actions.CORE`) stay protected
  from being renamed or deleted by vote.
- **The rules.** Rules 4 to 6 stay fixed (`conduct.FIXED`), and their
  original text can't change.

## What no change may do

- Give any role or member power over others, except the admins. Roles
  are cosmetic, and every role, the Admin role included, loses Discord's
  own moderation powers (`guard.py`).
- Change who the admins are, or who picks them. Only the owner does
  (`admins.py`), and no other file may touch the stored list. What admins
  can do is not protected: it is up to the owner, and an admin's code
  change can extend it. Today admins can do anything a vote can, at once,
  just by asking the bot, and withdraw any open proposal. They act only
  through the bot, which posts every admin action in `#server-log` with
  who did it; a change that lets an admin act without that record is
  refused.
- Show members where the code is kept. The repository is on the owner's
  own GitHub account, and linking to it from the server would identify
  them. No message, embed or answer members can see may contain a GitHub
  link; admins can ask for it with `/admin github`, which only they see.
  Members still get every status and summary, without the link. Admins
  get links in `#admin-log`, which only they and the owner can read.

- Read, print, store or send any key or token: the Discord token, the AI
  key, the GitHub token, or any other secret. New code may not read environment variables
  at all.
- Run code it builds at runtime (`eval`, `exec`, `subprocess`, dynamic
  imports).
- Break Discord's Terms of Service or Community Guidelines.
