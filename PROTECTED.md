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
| `guard.py` | Takes moderation-level permissions off every role and channel override except the Admin role, so nobody but the admins can act on the server except through the bot. |
| `admins.py` | Who the admins are, and that only the owner and the admins pick them. It keeps the Admin role, the one role with Discord's powers, on the admins alone, and posts what admins do with Discord's own tools in `#server-log`. No other file may touch the stored list of admins. It also keeps `#admin-log` readable by the admins and the owner alone, checked before every post. |
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
  are cosmetic, and every role but Admin loses Discord's own moderation
  powers (`guard.py`); the bot keeps the Admin role, which has
  Administrator, on the admins alone (`admins.py`). A role may still open
  a channel to whoever holds it: seeing a channel is not power over
  anyone.
- Change who the admins are, or who picks them. Only the owner and the
  admins do (`admins.py`), and no other file may touch the stored list.
  What admins can do is not protected: it is up to the owner, and an
  admin's code change can extend it. Today admins can do anything a vote
  can, at once, just by asking the bot, withdraw any open proposal, and
  act directly with Discord's own tools. Every admin action is posted in
  `#server-log` with who did it: the bot's, and what they do directly,
  read from Discord's audit log. A change that lets an admin act without
  that record is refused.
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
