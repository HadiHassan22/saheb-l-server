"""The AI the moderator uses, all through one OpenRouter key.

- The first check is TypeSafe's Jev, on OpenRouter's Decisions API. It is
  pinned to one version because the review threshold was tuned on it.
- The full review is Claude Haiku, through providers.OpenRouter, which also
  answers members in #ask-saheb.

The server owner sets the key and a monthly budget with /ai-key; paying for
the AI is part of keeping the bot online. The key is stored in a file only
the bot's own user can read. OPENROUTER_API_KEY in the environment is used
when no key has been set, for running the bot locally.
"""

import json
import os
import time

import aiohttp

import providers
import store

FIRST_CHECK = "typesafe/jev-1.13"
REVIEWER = "anthropic/claude-haiku-4.5"
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_BUDGET = 10.0


class Unavailable(Exception):
    """No key, or this month's budget is spent. Moderation pauses; AutoMod's
    own blocks keep working."""


def _secrets():
    return store.load("ai", {})


def key():
    return _secrets().get("key") or os.environ.get("OPENROUTER_API_KEY", "")


def configure(new_key, budget):
    saved = _secrets()
    saved.update(key=new_key.strip(), budget=float(budget))
    store.save("ai", saved, private=True)


def _month(now):
    return time.strftime("%Y-%m", time.gmtime(now))


def spending(now):
    """(spent, budget) in dollars for the current month."""
    saved = _secrets()
    spent = saved.get("spent", {}).get(_month(now), 0.0)
    return spent, saved.get("budget", DEFAULT_BUDGET)


def _spend(amount, now):
    saved = _secrets()
    month = _month(now)
    saved["spent"] = {month: saved.get("spent", {}).get(month, 0.0) + amount}
    store.save("ai", saved, private=True)


def _ready(now):
    if not key():
        raise Unavailable("no AI key has been set")
    spent, budget = spending(now)
    if spent >= budget:
        raise Unavailable(f"this month's AI budget (${budget:.2f}) is spent")


async def first_check(state, questions, api_key=None):
    """Jev's answers, as {question: answer}."""
    if api_key is None:
        _ready(time.time())
    async with aiohttp.ClientSession(timeout=providers.TIMEOUT) as session:
        async with session.post(
            DECISIONS_URL,
            headers={"Authorization": f"Bearer {api_key or key()}",
                     "Content-Type": "application/json",
                     "X-Title": "Saheb l Server"},
            json={"model": FIRST_CHECK, "state": state, "questions": questions},
        ) as response:
            body = await response.text()
            if response.status >= 400:
                raise providers.ProviderError(providers._terse(body),
                                              code=response.status)
    data = json.loads(body)
    if api_key is None:
        _spend(float((data.get("usage") or {}).get("cost") or 0.0), time.time())
    return data.get("answers") or {}


async def review(prompt, schema):
    """Haiku's structured answer to `prompt`."""
    now = time.time()
    _ready(now)
    answer, tokens_in, tokens_out = await providers.OpenRouter(key()).json_answer(
        REVIEWER, prompt, schema, max_tokens=400)
    price_in, price_out = providers.prices("openrouter", REVIEWER)
    _spend((tokens_in * price_in + tokens_out * price_out) / 1_000_000, now)
    return answer


async def converse(system, turns, tools, max_tokens=600):
    """One turn of conversation with tools, through REVIEWER."""
    now = time.time()
    _ready(now)
    reply = await providers.OpenRouter(key()).converse(
        REVIEWER, system, turns, tools=tools, max_tokens=max_tokens)
    price_in, price_out = providers.prices("openrouter", REVIEWER)
    _spend((reply.tokens_in * price_in + reply.tokens_out * price_out) / 1_000_000, now)
    return reply


async def check_key(candidate):
    """Raise providers.ProviderError if `candidate` cannot reach the first
    check. Costs a fraction of a cent."""
    await first_check("Hello", {"greeting": {
        "type": "noul", "instructions": "Is this a greeting?"}}, api_key=candidate)
