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

**The owner.** Discord requires a human owner. The owner keeps the bot online, pays for its AI and picks
admins, and has the same powers as an admin. Otherwise the owner is a
member with one vote like everyone else.

**Admins.** Members the owner or another admin picks (they have the Admin
role; see `/admin list`) look after the server while it's young. They can
do anything a vote can, at once and without a vote: they ask the bot in
#ask-saheb and it's done, no questions asked, whether that's changing
channels, roles, settings or the rules, kicking or banning, overturning a
moderation case, making someone an admin, or having the bot's code
changed. Deleting a channel or category waits for them to confirm. They
can also take down any open proposal. The Admin role is the only role
with Discord's own powers (Administrator), so they can also act directly;
the bot keeps that role on the admins alone. Everything they do, through
the bot or directly (read from Discord's audit log), is posted in
#server-log with who did it. They also read #admin-log, where the bot
reports how code changes are going, with links to the code.

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
updates and rolls back its code, how far each setting can go (a range
can widen, but only an admin can narrow it), the
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
| Bot | `#automod-alerts`: hidden, AutoMod's alerts to the moderator; `#admin-log`: only the admins and the owner can read it |

It also sets the server's verification level to medium, scans media from
all members for explicit content, sets notifications to mentions only, and
moves members idle for 15 minutes to AFK. It creates the 14 name-color
roles and puts the color picker in `#roles`.

The layout is in `layout.py`. Once the server is running, channels change
by vote (see below): a channel deleted by vote stays deleted.
On every start it recreates anything missing and brings its AutoMod rules
and the `#welcome` and `#rules` posts up to date. Nothing is made twice:
each category, channel and name color is looked for before it is made, so
running the setup again over a server that already has the layout fills
in only what is missing. Once the server is a
Community server with a rules channel of Discord's own (Server Settings,
Safety Setup), the bot uses that channel as `#rules` and deletes the one
it built, if only the bot ever posted there. It runs one server: the
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
| Look | Answers from the server's records | settings, channels, roles, events, rules, proposals, moderation cases, onboarding |
| Personal | Only the member asking, who can undo it: done at once | name color; join or leave a role; nickname; an invite link (up to 10 uses, 24 hours, 5 a day) |
| Light | Small, shared, reversible: done at once, posted in `#server-log` with who asked, limited per member | schedule or cancel your own event (Beirut time); a temporary voice channel (closes when empty or after up to 12 hours); start a thread; pin or unpin a message |
| Draft | Changes the server for everyone, or acts on a member: a vote | see below |

What a vote can order, carried out by code when it passes (`actions.py`):

| Area | Changes |
| --- | --- |
| Channels and categories | create, rename, delete; a channel's topic and slowmode; clear a channel's message history; who can see a channel (everyone, or only members with some roles, made with it if new, which anyone can join) |
| Roles | create (with a color, and whether members can join it), rename, recolor, delete: always cosmetic |
| Pickers in `#roles` | create, change, remove a dropdown where members give themselves roles (pick one, or any); new roles are made with it |
| Onboarding | the questions new members answer when they join (each answer shows channels and/or gives joinable roles), and the channels they see from the start |
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
- **Admins skip the vote.** For an admin (picked by the owner or an admin
  with `/admin add` or by asking the bot, see `admins.py`; the owner
  counts as one), what they ask for is done at once, without questions:
  posted in `#proposals` as already passed and carried out like a passed
  vote, and the bot says what came of it. Admins also get two tools
  members don't: making or removing admins, and overturning a moderation
  case.
  Deleting a channel or category, or clearing a channel's history, is the
  exception: it comes back as a draft with a **Ship it** button to
  confirm, since the history is lost for good. A code change still goes
  through the self-update workflow's checks. `/admin withdraw` takes down any open
  proposal, `/admin retry` has a code change that failed, changed nothing
  or was rolled back tried again, `/admin chat-limit` switches the chat
  limit, and `/admin github` shows admins, and only them, where the code
  is. Every admin
  action is posted in `#server-log`. What admins can do can grow by code
  change; who they are can't: only the owner and the admins change that.
- **Votes about a member** (kick, ban) need the member @mentioned and a
  reason, hide their count until they close, need `removal_percent`
  (66% to start, never below 60%) to pass, and the member can't vote on
  them. The member is told why by DM. Immediate danger stays with the
  moderator.
- **Nobody but the admins holds power over anyone.** Roles are created with no
  permissions, and `guard.py` takes moderation-level permissions off every
  role and channel override whenever one changes, and every hour, however
  they got there, and says so in `#server-log`. The Admin role is the one
  exception, and the bot takes it from anyone who isn't an admin. A role
  can still open a channel to whoever holds it: seeing a channel is not
  power over anyone. That includes pinging
  `@everyone`, which only the bot can do.
- **What it can't do for a member who isn't an admin, whatever anyone
  says:** give anyone power, act on another member without a vote, change
  a moderation decision, or skip a vote. Whether a member is an admin is checked in
  code, never decided by the model. There is no tool for
  any of it, and claiming to be the owner
  changes nothing. The channels the bot depends on can't be renamed or
  deleted, even by vote. A code change can add things members do at once
  (the personal and light tiers), but none that lets a member act on
  another.
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

Other pickers in `#roles` group the roles members give themselves. Ask for
a role ("create a gamer role") and the bot files it under the picker it
belongs to, Interests say, or starts a new one when it's a new kind of
thing (Age, pick one, for -18 or +18). Later roles of the same kind land in
the same picker. Pickers can also be asked for directly: "a picker for
Lebanese or International", say. Each is a
title and up to 24 roles made by vote, where members pick one or any that
fit, and the roles it names that don't exist yet are made with it. Joining
one of a pick-one picker's roles by asking the bot leaves the others. A
role can also make a channel opt-in: only members who hold it see it.

Every role members can join is always in a picker. The ones no other
picker offers are in pickers the bot keeps itself, grouped the way a person
would: Male and Female go in a **Gender** picker where members pick one,
and roles that fit no group go in **Opt-in roles**. The AI suggests the
groups and code checks them (a title of its own, at least two roles, at
most five groups); they are only worked out again when that set of roles
changes, and without the AI new roles simply go in Opt-in roles. A new
opt-in role, like one for a hidden channel, appears at once, and leaves
when it's deleted, can't be joined any more, or gets a picker of its own.
Changing one of the bot's groups, or putting a new role in it, makes it an
ordinary picker.

## Onboarding

On a Community server, Discord asks new members a few questions when they
join and shows them a set of channels from the start. The bot keeps that
page (`onboarding.py`). By default new members see the Start here and
Governance channels, the Hangout channels and the General, Ahwe and Lounge
voice channels, and are asked:

- **What are you into?** (any): Food, Pets, Gaming, Music, Sports, Movies
  and TV, Tech, Cars, Study and work, each showing its channels.
- **What do you want to follow about Lebanon?** (any): News, Politics and
  religion, Diaspora.

Every picker in `#roles` is asked there too, with the same roles and the
same pick one or pick any, so a role added later is offered to new members
at once. The questions and the default channels change like any server
change, by vote or at once by an admin; a picker's question changes with
the picker. Channels only some members can see are left out, since
Discord refuses them, and the default channels keep Discord's minimum of
7, with 5 everyone can write in. The page is only written when what the
bot would write changes, so an admin's edit in Discord's own settings stays
until the next such change. Until the server is a Community server, the
bot keeps the page ready but can't show it.

## Voting

- **`/propose`** opens a form for a title and details. The proposal is
  posted in `#proposals` with Yes and No buttons and a thread for
  discussion.
- **`/propose-setting`** proposes changing one of the settings below. If
  it passes, the bot applies the change itself.
- **`/settings`** shows every setting and the range it can be set to.

A proposal runs by the settings in force when it opened. Ballots are
secret: the card shows only the totals, you can change your vote until it
closes, and who voted which way is deleted when it does. When it closes,
the bot carries out the result, then updates the card and says under it
how the vote went and what came of it. Anyone can
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

The ranges are set in code, not by a vote on a setting. A code change can
widen a range; only one an admin shipped can narrow or remove one.

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
  towards the appellant's limit of open proposals. If an admin withdraws
  the appeal, it doesn't count: the case can be appealed again, and its
  `#mod-log` entry says so.
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
puts it into effect with no human in the loop. The bot starts it at once
(with the token the owner gave it, `/github-key`), and again whenever a
passed proposal is still waiting and no run is going; GitHub also starts
it every ten minutes, when it gets round to it. Each run takes the oldest
passed proposal that hasn't been handled:

1. **Claude Code writes the change** on a branch named `proposal-N`,
   with a model from OpenRouter (MiMo V2.6 Pro unless the `CODER_MODEL`
   variable names another). It can read and edit files and nothing else:
   no shell, no GitHub credentials. If Claude Code can't run, for example
   because the OpenRouter credit ran out, the try is recorded as failed,
   not as a change that needed no code. If the proposal needs no code, or can't be done
   within the protected core, it changes nothing and says why.
2. **The tests run**, with no secrets available. If they fail, Claude
   gets one chance to fix its change.
3. **The protected-core check** refuses any change to the files and
   values listed in [PROTECTED.md](PROTECTED.md), and any added line that
   reads environment variables or keys or runs code built at runtime.
4. **A security review**, for a change members voted for, reads the
   whole diff against the proposal (Claude Haiku 4.5 through OpenRouter,
   unless the `REVIEWER_MODEL` variable names another) and rejects anything that could leak a secret, contact a new
   host, add a suspicious dependency, work around the protected core,
   break Discord's rules, or do something materially different from what
   was voted for. An admin's change skips it: admins can already do
   anything a vote can. If this check or the protected-core check refuses
   the change, Claude is told why and gets one more try, with the tests and
   every check run again.
5. **The result is recorded as a pull request**, whatever happens:
   merged, or closed as `failed` or `no-change` with the reasons. A change
   that contains anything that looks like a secret is thrown away and
   never published.
6. **Railway deploys the merge.** Its health check keeps the old version
   running until the new one connects. The workflow waits up to 15
   minutes for `/healthz` to report the new commit; if it doesn't, it
   reverts the change.

The bot follows each proposal through GitHub's API and replies under its
card in `#proposals`: deploying, live, needs no change, failed, or rolled
back. `#admin-log` gets the same with a link to the pull request, plus
each time the bot starts the workflow (or couldn't), runs it started, and
runs that fail. Only the admins and the owner can read it: the bot checks
that before every post.

Each proposal is tried once. If that try failed, changed nothing or was
rolled back, an admin can have it tried again with `/admin retry`: the new
try gets its own branch (`proposal-N-try-2`), starts from what the last
one changed, and is told why it wasn't kept.

## Files

| File | What it does |
| --- | --- |
| `bot.py` | Entrypoint: connects, picks the home server, loads everything |
| `chat.py` | `#ask-saheb`: rate limits, memory, and the File it and Ship it buttons |
| `admins.py` | The admins, `/admin`, the Admin role, posting admins' own Discord actions, and who reads `#admin-log` (protected) |
| `pickers.py` | The pickers in `#roles`, made by vote or grouped by the bot: one dropdown answers them all |
| `onboarding.py` | Discord's onboarding: the default questions and channels, and every picker as a question |
| `assistant.py` | What the bot may do when asked: 34 tools, their tiers, the conversation |
| `actions.py` | Everything a vote can order, checked and carried out by code; the server-change kind of proposal |
| `quick.py` | What's done at once when asked: personal and light actions, with their limits |
| `guard.py` | Keeps every role but Admin cosmetic (protected) |
| `colors.py` | The name colors, the `#roles` picker and `/color` |
| `health.py` | `/healthz` and `/api/passed`, which the update system relies on (protected) |
| `updates.py` | Follows passed proposals through GitHub, starts the workflow, and reports in `#proposals` and `#admin-log` |
| `workflow.py` | The GitHub token, `/github-key`, and starting the workflow (protected) |
| `PROTECTED.md` | What votes can't change (protected) |
| `.github/` | The self-update workflow, its protected-core check and security review (protected) |
| `layout.py` | Builds and repairs the server; knows where each channel is |
| `conduct.py` | The rules of conduct and the `#welcome` text |
| `settings.py` | The votable settings and their fixed ranges |
| `proposals.py`, `voting_ui.py` | Proposals and ballots, the same for every kind; their commands and vote buttons |
| `kinds.py` | What differs between kinds of proposal, each in its own module |
| `code_changes.py`, `setting_changes.py` | General proposals and setting changes, as kinds of proposal |
| `ending.py` | Every way a proposal ends: its vote closes, or an admin passes or withdraws it |
| `cards.py` | How a proposal looks in `#proposals`: its card and its result |
| `automod.py` | The AutoMod rules and watch lists |
| `judge.py` | The questions, routing, verdicts and sanction ladder; no Discord |
| `moderator.py` | Handles AutoMod alerts, applies sanctions, posts cases; `/ai-key` |
| `cases.py` | Numbered moderation cases and each member's record |
| `appeals.py` | `/appeal`, the Appeal button, and the appeal kind of proposal |
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
6. **As the server owner, run `/github-key`** with a GitHub token (see
   below), so the bot can start the workflow as soon as a proposal passes.
   Without it, proposals wait for GitHub's timer.

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
- **Secret `OPENROUTER_API_KEY`:** an OpenRouter key for the workflow,
  ideally its own with a credit limit, and with zero data retention on
  in OpenRouter's privacy settings (Claude Code's requests can't ask for
  it themselves). Each proposal costs a few cents to write and review.
- **Variables `CODER_MODEL` and `REVIEWER_MODEL`** (optional): any
  OpenRouter model id, to change which model writes or reviews.
- **Actions, then General:** allow GitHub Actions to create pull requests.
- **The repository must stay public:** the bot reads pull requests through
  GitHub's public API when its token can't.

The token for `/github-key`: in GitHub, Settings, Developer settings,
Fine-grained tokens, generate one with an expiry, **Only select
repositories** (this one), and under repository permissions only
**Actions: Read and write**. The bot checks it by starting the workflow
once, keeps it in a file only it can read, and says in `#admin-log` if
GitHub stops accepting it. Anyone holding it could only start, read or
cancel the workflow's runs, and a run only acts on proposals the bot
lists as passed.
