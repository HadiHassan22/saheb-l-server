# Saheb l Server

A Discord bot that is the sole moderator and governor of a server. The
experiment: if an AI holds all the power and every member holds one equal
vote over what it does, does the server become fairer than one run by human
moderators?

> **Status:** the bot builds its own server, talks with members in
> `#ask-saheb`, runs votes, moderates, puts appeals to a vote, and carries
> out what passes: server changes directly, anything else by rewriting its
> own code. See [Roadmap](#roadmap).

## How the server works

This is the text the bot posts in `#welcome`, with the current settings
filled in.

This server is an experiment: it is moderated and governed entirely by Saheb
l Server, an AI bot. There are no human moderators, and apart from the
admins below, no member has more say than any other.

**The owner.** Discord requires a human owner. The owner keeps the bot online, pays for its AI and picks the
admins, and has the same powers as an admin. Otherwise the owner is a
member with one vote like everyone else.

**Admins.** Members the owner picks (they have the Admin role; see
`/admin list`) look after the server while it's young. They can do
anything a vote can, at once and without a vote: change channels, roles,
settings and the rules, kick or ban, or have the bot's code changed. They
can also take down any open proposal. They act only through the bot,
never with Discord's own tools, and everything they do is posted in
#server-log with who did it.

**Moderation.** The bot doesn't read every message. Discord's AutoMod
passes it messages with flagged words in English or Arabic, and it reads
the conversation around each one and decides whether to do nothing, warn,
delete the message, time the member out, or ban them for severe or
repeated violations. Every action is posted in `#mod-log` with the
reasoning.

**Talk to the bot.** Ask Saheb l Server anything in `#ask-saheb`, in
English, Arabic or Arabizi: tag it or reply to one of its messages, with an
image attached if you want it to see one. It
changes your name color when you ask (or
pick one in `#roles`), answers questions about the server, and drafts
proposals for anything that affects everyone. It never files a proposal
until you press the button, and it can't change anything for everyone
without a vote.

**Appeals.** Think the bot got it wrong? Use `/appeal` with the case
number, or the Appeal button in its message to you. The community votes,
and can overturn any action.

**Community votes.** Anyone can make a proposal with `/propose`, and change
one of the bot's settings with `/propose-setting`.

- Voting stays open for 24 hours.
- A proposal needs at least 5 votes to count (or half the server's
  members, if that's fewer, but never under 3), and more than 50% yes to
  pass.
- Members who have been here for 7 days can vote. Everyone who joined in
  the server's first week can vote right away.

**Votes are carried out automatically.** A passed change to the server,
like a new channel, is made by the bot at once. Anything else is written
as a code change, checked automatically and deployed, and what changed is
posted under its proposal.

**What votes can't change.** Who the admins are, the bot's access keys, the system that
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
| 5 | A full community layout, name colors, and `#ask-saheb`: members talk to the bot, which acts on its own for them and drafts proposals for everyone else. **Done.** |

## The server it builds

The bot is made for a brand-new, empty server. On its first start it builds
this, adopting Discord's default `#general` and General voice channel:

| Category | Channels |
| --- | --- |
| Start here | `#welcome`, `#rules`, `#roles`, `#mod-log`, `#server-log`: read-only, posted by the bot |
| Governance | `#ask-saheb` (talk to the bot), `#proposals` (the bot posts; members discuss in each proposal's thread) |
| Hangout | `#general`, `#introductions`, `#memes`, `#media`, `#off-topic` |
| Lebanon | `#lebanon-news`, `#politics-and-religion` (30-second slowmode), `#diaspora` |
| Interests | `#food`, `#pets`, `#gaming`, `#music`, `#sports`, `#movies-and-tv`, `#tech`, `#cars`, `#study-and-work` |
| Voice | General, Ahwe, Lounge, Gaming 1, Gaming 2, Study Room, AFK |
| Bot | `#automod-alerts`: hidden, AutoMod's alerts to the moderator |

It also sets the server's verification level to medium, scans media from
all members for explicit content, sets notifications to mentions only, and
moves members idle for 15 minutes to AFK. It creates the 14 name-color
roles and puts the color picker in `#roles`.

The layout is in `layout.py`. Once the server is running, channels change
by vote (see below): a channel deleted by vote stays deleted.
On every start it recreates anything missing and brings its AutoMod rules
and the `#welcome` and `#rules` posts up to date. It runs one server: the
first one it's invited to becomes its home, and it leaves any other.

## Talking to the bot

In `#ask-saheb`, members talk to Saheb l Server in their own words, and it
answers in the language they use, never using an em dash. It answers only
messages that tag it or reply to it, so members can also talk to each
other there. It is the only channel where the bot reads ordinary
messages. If such a message has an image attached, the bot can see it too
(up to 3 images, 5 MB each) and use what's in it, for example drafting an
emoji or the server's icon straight from the attachment. The model
understands the request, and code decides what is allowed: every tool is
in one of four tiers, fixed in `assistant.py`.

| Tier | Rule | What |
| --- | --- | --- |
| Look | Answers from the server's records | settings, channels, roles, events, rules, proposals, moderation cases |
| Personal | Only the member asking, who can undo it: done at once | name color; join or leave a role; nickname; an invite link (up to 10 uses, 24 hours, 5 a day) |
| Light | Small, shared, reversible: done at once, posted in `#server-log` with who asked, limited per member | schedule or cancel your own event (Beirut time); a temporary voice channel (closes when empty or after up to 12 hours); start a thread; pin or unpin a message |
| Draft | Changes the server for everyone, or acts on a member: a vote | see below |

What a vote can order, carried out by code when it passes (`actions.py`):

| Area | Changes |
| --- | --- |
| Channels and categories | create, rename, delete; a channel's topic and slowmode |
| Roles | create (with a color, and whether members can join it), rename, recolor, delete: always cosmetic |
| Emojis | add (from an image attached in `#ask-saheb`), remove |
| The server | rename it; set its icon |
| Rules | reword, add, remove added rules; rules 4 to 6 and the original rules stay |
| AutoMod | add or remove watch words; blocked words stay |
| Events | cancel someone else's event |
| Members | kick, ban, unban |
| Settings | any of the settings, within its range |
| Anything else | a general proposal, written as code by the self-update workflow |

- **Drafts are filed by the member, not the bot.** The reply carries a
  **File it** button that only the member who asked can press, once.
- **Admins can skip any vote.** For an admin (picked by the owner with
  `/admin add`, see `admins.py`; the owner counts as one), every draft
  also gets a **Ship it** button: it is posted as already passed and
  carried out like a passed vote. A code change still goes through the
  self-update workflow's checks. `/admin withdraw` takes down any open
  proposal, `/admin chat-limit` switches the chat limit, and `/admin
  github` shows admins, and only them, where the code is. Every admin
  action is posted in `#server-log`. What admins can do can grow by code
  change; who they are can't.
- **Votes about a member** (kick, ban) need the member @mentioned and a
  reason, hide their count until they close, need `removal_percent`
  (66% to start, never below 60%) to pass, and the member can't vote on
  them. The member is told why by DM. Immediate danger stays with the
  moderator.
- **Nobody but the admins holds power over anyone.** Roles are created with no
  permissions, and `guard.py` takes moderation-level permissions off every
  role and channel override whenever one changes, and every hour, however
  they got there, and says so in `#server-log`. That includes pinging
  `@everyone`, which only the bot can do.
- **What it can't do for a member, whatever anyone says:** give anyone
  power, act on another member without a vote, change a moderation
  decision, or skip a vote (admins' Ship it button is code, not a tool). There is no tool for
  any of it, and claiming to be the owner
  changes nothing. The channels the bot depends on can't be renamed or
  deleted, even by vote. A code change can't add anything to the personal
  or light tiers: only the owner can, by committing directly.
- **Costs.** The chat model (`ai.CHAT`, DeepSeek V4.1 Flash, picked with
  `chat_eval.py`) on the owner's OpenRouter key and monthly budget: about
  0.02 of a cent per answer, against 0.6 to 0.9 on Claude Haiku, which
  still does the moderation. The budget
  records what OpenRouter actually billed. Requests go only to providers
  with zero data retention: they keep nothing members write. Each member can ask 20
  times in 10 minutes (an admin can switch this off), and it remembers
  their last few exchanges for half an hour.

## What still needs a human

Almost everything runs without one. What can't:

- **Owning the server.** Discord requires a human owner and never lets a
  bot hold ownership. The owner keeps powers no bot can take away, so the
  owner's account is a matter of trust and security (turn on 2FA).
  Deleting the server and transferring it are owner-only.
- **Paying.** Railway, OpenRouter, Anthropic, and any server boosts.
  Boost-only features (a vanity invite link, a banner, larger uploads)
  need members to boost.
- **Keys.** The Discord token, the API keys and the GitHub secret, set
  once, and replaced if one ever leaks. The Discord developer portal
  settings.
- **The law and Discord.** The bot deletes illegal content and bans
  whoever posted it, but reporting it to Discord or the authorities, and
  answering Discord's own warnings, is a person's job.
- **Recovery.** If the bot is down or broken past the automatic rollback,
  banned by Discord, or has lost its data, only the owner can step in.
- **The protected core** ([PROTECTED.md](PROTECTED.md)), by design.
- **What Discord hides from bots:** what is said in voice, direct
  messages between members, members' real ages or identities, and applying
  for Server Discovery or Partner status.

## Name colors

Members pick one of 14 colors in `#roles` or with `/color`, or ask for one
in `#ask-saheb`. A color only changes how a name looks: the roles carry no
permissions, sit at the bottom of the role list, and a member holds one at
a time. The list is in `colors.py`, so changing it is a proposal.

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
  `automod.py`. That includes `#ask-saheb`: the bot reads messages there
  to answer them, not to moderate them.

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
| `chat.py` | `#ask-saheb`: rate limits, memory, and the File it and Ship it buttons |
| `admins.py` | The admins the owner picks, `/admin` (protected) |
| `assistant.py` | What the bot may do when asked: 29 tools, their tiers, the conversation |
| `actions.py` | Everything a vote can order, checked and carried out by code |
| `quick.py` | What's done at once when asked: personal and light actions, with their limits |
| `guard.py` | Keeps every role cosmetic (protected) |
| `colors.py` | The name colors, the `#roles` picker and `/color` |
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
| `chat_eval.py` | Compares chat models on example `#ask-saheb` messages: tool, language, speed, cost |
| `test_*.py` | Tests that need no network, no keys and no Discord server |

## Running it

1. **In the [Discord developer portal](https://discord.com/developers/applications):**
   create an application and add a bot. Under **Bot**, turn on **Message
   Content Intent** and **Server Members Intent** (the bot won't start
   without them), and copy the token.
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
OPENROUTER_API_KEY=sk-or-... .venv/bin/python chat_eval.py   # compare chat models
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
