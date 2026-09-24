# Saheb l Server

A Discord bot that is the sole moderator and governor of a server. The
experiment: if an AI holds all the power and every member holds one equal
vote over what it does, does the server become fairer than one run by human
moderators?

> **Status: phase 4.** The bot builds its own server, runs votes,
> moderates, puts appeals to a vote, and rewrites itself when a proposal
> passes. See [Roadmap](#roadmap).

## How the server works

This is the text the bot posts in `#welcome`, with the current settings
filled in.

This server is an experiment: it is moderated and governed entirely by Saheb
l Server, an AI bot. There are no human moderators, and no member has
more say than any other.

**The owner.** Discord requires a human owner. The role is purely
technical: the owner keeps the bot online and pays for its AI, and does not
moderate, make rules, or overrule votes. On this server the owner is just
another member with one vote.

**Moderation.** The bot doesn't read every message. Discord's AutoMod
passes it messages with flagged words in English or Arabic, and it reads
the conversation around each one and decides whether to do nothing, warn,
delete the message, time the member out, or ban them for severe or
repeated violations. Every action is posted in `#mod-log` with the
reasoning.

**Appeals.** Think the bot got it wrong? Use `/appeal` with the case
number, or the Appeal button in its message to you. The community votes,
and can overturn any action.

**Community votes.** Anyone can make a proposal with `/propose`, and change
one of the bot's settings with `/propose-setting`.

- Voting stays open for 24 hours.
- A proposal needs at least 5 votes to count, and more than 50% yes to pass.
- Members who have been here for 7 days can vote.

**The bot rewrites itself.** When a proposal passes, the bot writes the
code change, checks it automatically, and deploys it. Every change is
public on GitHub.

**What votes can't change.** The bot's access keys, the system that
updates and rolls back its code, the range each setting can take, the
safety floor (blocking scams, phone numbers and sexual content involving
minors, and the self-harm support line), and anything Discord's Terms of
Service require.

**Fair warning.** The bot will make mistakes, a vote might break
something, and it might go offline. If so, we roll back to a working
version and keep going.

## Roadmap

| Phase | What it adds |
| --- | --- |
| 0 | A clean start: connects to Discord, health check for Railway. **Done.** |
| 1 | Equal votes: `/propose`, anyone in the server 7+ days votes, 24h window, 5-vote quorum, majority to pass. Settings change only by vote. **Done.** |
| 2 | The bot builds its own server, and moderates what AutoMod flags, with every action in `#mod-log`. **Done.** |
| 3 | Appeals: `/appeal` or the Appeal button opens a public vote that can overturn any action. **Done.** |
| 4 | Self-rewriting: a passed proposal is written as code, checked, merged and deployed, and rolled back if the new version doesn't come up. **Done.** |

## The server it builds

The bot is made for a brand-new, empty server. On its first start it builds
this, adopting Discord's default `#general` and General voice channel:

| Category | Channels |
| --- | --- |
| Start here | `#welcome`, `#rules`, `#mod-log`: read-only, posted by the bot |
| Governance | `#proposals`: the bot posts, members discuss in each proposal's thread |
| Community | `#general`, `#off-topic`, General (voice) |
| Bot | `#automod-alerts`: hidden, AutoMod's alerts to the moderator |

It also sets the server's verification level to medium, scans media from
all members for explicit content, and sets notifications to mentions only.
On every start it recreates anything missing and brings its AutoMod rules
and the `#welcome` and `#rules` posts up to date. It runs one server: the
first one it's invited to becomes its home, and it leaves any other.

## Voting

- **`/propose`** opens a form for a title and details. The proposal is
  posted in `#proposals` with Yes and No buttons and a thread for
  discussion.
- **`/propose-setting`** proposes changing one of the settings below. If
  it passes, the bot applies the change itself.
- **`/settings`** shows every setting and the range it can be set to.

A proposal runs by the settings in force when it opened. Ballots are
secret: the card shows only the totals, you can change your vote until it
closes, and who voted which way is deleted when it does. Anyone can
propose; only members who have been in the server long enough can vote.
Leaving and rejoining restarts that clock.

## Moderation

AutoMod is the net, and the bot is the judge:

1. **AutoMod flags.** Broad watch lists in English, Arabic script and
   Arabizi (Arabic in Latin letters and digits) send matches to the bot
   without removing anything. A few things are blocked immediately and
   then judged: scam lures, Lebanese phone numbers, slurs, sexual content,
   mass mentions and spam.
2. **A fast first check.** [Jev](https://openrouter.ai/typesafe/jev-1.13)
   reads the flagged message and the eight before it, and answers yes/no
   questions (harassment, hate, threats, doxxing, sexual content, scams,
   self-harm, and whether the message is talking to the moderator), plus
   how severe it is. It costs about $0.00002 a message, which is why the
   watch lists can afford to be broad.
3. **Routing, by Jev's highest score:**
   - **80% or more:** Jev's verdict stands. Claude Haiku writes the public
     explanation of the decision but cannot overrule it.
   - **30% to 80%, or the message talks to the moderator:** Jev is unsure,
     so Haiku reviews the conversation and decides.
   - **Under 30%:** cleared. Nothing happens and nothing is posted.
4. **The sanction is picked in code**, never by a model, from the severity
   and the member's record over the last 30 days:
   - mild: a warning; after 3 warnings, a timeout
   - serious: a warning with the message deleted; with any record, a
     timeout (60 minutes first, 24 hours after that); after 2 timeouts, a
     ban
   - severe (threats, doxxing, anything sexual involving minors, scams): a
     ban
5. **Everything is public.** The member gets a DM, and `#mod-log` gets the
   case: the rule, the explanation, the member's record, Jev's score, and
   which judge decided. The flagged message is quoted behind a spoiler,
   except for private information, sexual content and scam links, which
   are never repeated.

A self-harm signal never leads to a sanction. The member gets a private
message with Embrace's lifeline (1564) instead.

Every number above is a setting the community can change by vote:

| Setting | Starts at | Can be set to |
| --- | --- | --- |
| Voting window | 24 hours | 1 to 168 hours |
| Votes needed to count | 5 | 3 to 100 |
| Yes votes needed to pass | more than 50% | 50% to 90% |
| Time in the server before you can vote | 7 days | 0 to 90 days |
| Open proposals per member | 3 | 1 to 20 |
| How long a warning or timeout counts | 30 days | 7 to 180 days |
| Warnings before a timeout | 3 | 1 to 10 |
| Length of a first timeout | 60 minutes | 10 to 1440 minutes |
| Length of each later timeout | 24 hours | 1 to 168 hours |
| Timeouts before a ban | 2 | 1 to 10 |
| How sure the first check must be to act alone | 80% | 50% to 99% |
| How likely a message must look to get a second look | 30% | 10% to 90% |

The ranges are fixed in code and cannot be voted on, so no single vote can
make later votes meaningless or switch moderation off.

Known limits:

- Discord's AutoMod never applies to members with Administrator or Manage
  Server, which includes the owner. The bot can't change that.
- The bot can only act on members whose highest role is below its own.
- Anything AutoMod doesn't flag is never seen. The watch lists are in
  `automod.py`.

To check how the first check scores a set of example messages with the
current dials, run `calibrate.py` (see [Running it](#running-it)).

## Appeals

- **Who can appeal.** The member a case is about gets an **Appeal** button
  in the bot's message telling them about it. That button still works
  after a ban or during a timeout, when the server's commands are out of
  reach. Anyone in the server can also use **`/appeal`** on any case that
  still stands, which covers a banned member whose DMs are closed, and
  anyone who thinks a call was unfair.
- **Once per case.** Each case can be appealed once. The appeal counts
  towards the appellant's limit of open proposals.
- **The vote.** An appeal is a proposal in `#proposals` showing the case,
  the moderator's explanation, the message (unless it was private
  information, sexual content or a scam) and the appellant's reason. It is
  voted **Overturn** or **Keep** under the usual rules. The member it is
  about can't vote on it.
- **If it passes**, the bot lifts the timeout, or unbans the member and
  sends them a one-use invite back (Discord may refuse that message, since
  they are no longer in the server; if so, `#mod-log` says so). The case
  stops counting towards their record. A deleted message can't be
  restored.
- **The strictness gauge.** Each case's `#mod-log` entry is updated when
  it is appealed and when the appeal closes, and every result posts the
  running share of appeals that overturned the moderator. A high share
  means the moderator is too strict.

## Self-updating

When a proposal passes, [a GitHub workflow](.github/workflows/self-update.yml)
puts it into effect with no human in the loop. Every ten minutes it looks
for passed proposals that haven't been handled, and for the oldest one:

1. **Claude Code writes the change** (Sonnet 5) on a branch named
   `proposal-N`. It can read and edit files and nothing else: no shell,
   no GitHub credentials. If the proposal needs no code, or can't be done
   within the protected core, it changes nothing and says why.
2. **The tests run**, with no secrets available. If they fail, Claude
   gets one chance to fix its change.
3. **The protected-core check** refuses any change to the files and
   values listed in [PROTECTED.md](PROTECTED.md), and any added line that
   reads environment variables or keys or runs code built at runtime.
4. **A security review** by Opus 5.5 reads the whole diff against the
   proposal and rejects anything that could leak a secret, contact a new
   host, add a suspicious dependency, work around the protected core,
   break Discord's rules, or go beyond what was voted for.
5. **The result is recorded as a pull request**, whatever happens:
   merged, or closed as `failed` or `no-change` with the reasons. A change
   that contains anything that looks like a secret is thrown away and
   never published.
6. **Railway deploys the merge.** Its health check keeps the old version
   running until the new one connects. The workflow waits up to 15
   minutes for `/healthz` to report the new commit; if it doesn't, it
   reverts the change.

The bot follows each proposal through GitHub's public API and replies
under its card in `#proposals`: deploying, live, needs no change, failed,
or rolled back.

Each proposal is attempted once. To try again, propose it again.

## Files

| File | What it does |
| --- | --- |
| `bot.py` | Entrypoint: connects, picks the home server, loads everything |
| `health.py` | `/healthz` and `/api/passed`, which the update system relies on (protected) |
| `updates.py` | Follows passed proposals through GitHub and reports in `#proposals` |
| `PROTECTED.md` | What votes can't change (protected) |
| `.github/` | The self-update workflow, its protected-core check and security review (protected) |
| `layout.py` | Builds and repairs the server; knows where each channel is |
| `conduct.py` | The rules of conduct and the `#welcome` text |
| `settings.py` | The votable settings and their fixed ranges |
| `proposals.py`, `voting_ui.py` | Proposals, ballots and closing; their Discord side |
| `automod.py` | The AutoMod rules and watch lists |
| `judge.py` | The questions, routing, verdicts and sanction ladder; no Discord |
| `moderator.py` | Handles AutoMod alerts, applies sanctions, posts cases; `/ai-key` |
| `cases.py` | Numbered moderation cases and each member's record |
| `appeals.py` | `/appeal`, the Appeal button, and carrying out a vote's result |
| `ai.py` | The OpenRouter key, the two model calls, and the monthly budget (protected) |
| `providers.py` | One interface over OpenRouter, Claude, Gemini and Grok |
| `store.py` | Saves state as JSON files on the volume (protected) |
| `calibrate.py` | Scores example messages with the real first check |
| `test_*.py` | Tests that need no network, no keys and no Discord server |

## Running it

1. **In the [Discord developer portal](https://discord.com/developers/applications):**
   create an application and add a bot. Under **Bot**, turn on **Message
   Content Intent** and copy the token.
2. **Create a brand-new server** and invite the bot with the `bot` and
   `applications.commands` scopes and the **Administrator** permission.
   Invite it to this server only: the first server it joins becomes its
   home.
3. **Start it** (below, or on Railway). It builds the server within a
   few seconds of connecting.
4. **As the server owner, run `/ai-key`** and paste an
   [OpenRouter](https://openrouter.ai/keys) key and a monthly budget.
   Until then, moderation is paused and says so in `#mod-log`, but
   AutoMod's blocks still work.
5. **Turn on self-updating** (see [Hosting](#hosting-on-railway)). Until
   then, passed proposals are recorded but not put into effect.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest     # tests
.venv/bin/python bot.py          # run the bot (needs DISCORD_TOKEN in .env)
OPENROUTER_API_KEY=sk-or-... .venv/bin/python calibrate.py
```

## Hosting on Railway

- **Variables:** only `DISCORD_TOKEN`.
- **Volume:** attach one, at any mount path. The bot finds it through
  `RAILWAY_VOLUME_MOUNT_PATH`, which Railway sets itself. Without a
  volume, every redeploy forgets the server layout, proposals, votes,
  settings, cases and the AI key.
- **Health check:** `railway.json` starts `python bot.py` and waits for
  `/healthz` to answer before treating a deploy as live, so a version that
  fails to connect never replaces the one that works.
- **Deploys:** from the repository's `main` branch, automatically on every
  push. The self-update workflow merges into `main`.
- **Public address:** generate a Railway domain for the service (Settings,
  then Networking). The workflow reads `/healthz` and `/api/passed` there.

To turn on self-updating, in the GitHub repository's settings:

- **Variable `BOT_URL`:** the Railway address, for example
  `https://saheb-l-server.up.railway.app`.
- **Secret `ANTHROPIC_API_KEY`:** a key from the
  [Anthropic Console](https://console.anthropic.com), ideally with a
  monthly spend limit. Each proposal costs roughly a dollar or two to
  write and review.
- **Actions, then General:** allow GitHub Actions to create pull requests.
- **The repository must stay public:** the bot reads pull requests through
  GitHub's public API, with no key.
