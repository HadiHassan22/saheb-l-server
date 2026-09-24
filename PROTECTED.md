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
| `railway.json`, `railpack.json` | How the bot is deployed and health-checked. |

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

## What no change may do

- Read, print, store or send any key or token: the Discord token, the AI
  key, or any other secret. New code may not read environment variables
  at all.
- Run code it builds at runtime (`eval`, `exec`, `subprocess`, dynamic
  imports).
- Break Discord's Terms of Service or Community Guidelines.
