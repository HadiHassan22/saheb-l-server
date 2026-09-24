"""Checks for providers.py that need no network and no API keys.

    python -m unittest
"""

import unittest

import providers


class Lookup(unittest.TestCase):
    def test_every_provider_describes_and_prices_itself(self):
        for name in providers.NAMES:
            with self.subTest(name=name):
                self.assertTrue(providers.label(name))
                self.assertTrue(providers.default_model(name))
                self.assertTrue(all(p > 0 for p in providers.prices(name)))
                read, write = providers.cache_rates(name)
                self.assertLess(read, 1.0)
                self.assertGreaterEqual(write, 1.0)

    def test_claude_prices_each_listed_model_separately(self):
        haiku = providers.prices("claude", "claude-haiku-4-5")
        opus = providers.prices("claude", "claude-opus-5")
        self.assertGreater(sum(opus), sum(haiku))

    def test_unlisted_model_falls_back_to_provider_estimate(self):
        self.assertEqual(providers.prices("claude", "claude-something-else"),
                         providers.prices("claude"))

    def test_unknown_provider(self):
        self.assertEqual(providers.prices("nope"), (0.0, 0.0))
        self.assertEqual(providers.cache_rates("nope"), (1.0, 1.0))
        self.assertEqual(providers.label("nope"), "nope")
        with self.assertRaises(providers.ProviderError):
            providers.build("nope", "key")


class Transcripts(unittest.TestCase):
    def conversation(self, raw):
        """`raw` is the tool-calling turn in the provider's own shape."""
        asked = providers.Reply(
            calls=[providers.Call(name="lookup", args={}, id="call_1")], raw=raw,
        )
        return [
            providers.said("what is open?"),
            providers.answered(asked),
            providers.returned([
                {"id": "call_1", "name": "lookup", "result": "one"},
                {"id": "call_2", "name": "lookup", "result": "two"},
            ]),
            providers.answered(providers.Reply(text="Two things.")),
        ]

    def test_claude_sends_all_tool_results_in_one_user_turn(self):
        claude = providers.Claude.__new__(providers.Claude)
        messages = claude._messages(
            self.conversation([{"type": "tool_use", "id": "call_1"}]))
        self.assertEqual([m["role"] for m in messages],
                         ["user", "assistant", "user", "assistant"])
        self.assertEqual(messages[1]["content"], [{"type": "tool_use", "id": "call_1"}])
        self.assertEqual([r["tool_use_id"] for r in messages[2]["content"]],
                         ["call_1", "call_2"])

    def test_grok_sends_system_first_and_one_message_per_tool_result(self):
        grok = providers.Grok("key")
        raw = {"role": "assistant", "tool_calls": [{"id": "call_1"}]}
        messages = grok._messages(["stable", "volatile"], self.conversation(raw))
        self.assertEqual(messages[0], {"role": "system", "content": "stable\nvolatile"})
        self.assertEqual([m["role"] for m in messages[1:]],
                         ["user", "assistant", "tool", "tool", "assistant"])
        self.assertIs(messages[2], raw)


class SystemPrompt(unittest.TestCase):
    def test_list_caches_the_first_part_only(self):
        blocks = providers._cached_system_blocks(["STABLE", "VOLATILE"])
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", blocks[1])
        self.assertTrue(blocks[1]["text"].endswith(providers.NO_THINKING))

    def test_single_string_is_never_cached(self):
        blocks = providers._cached_system_blocks("ALL OF IT")
        self.assertNotIn("cache_control", blocks[0])
        self.assertEqual(providers._cached_system_blocks(None), [])


class Helpers(unittest.TestCase):
    def test_visible_strips_leaked_thinking(self):
        self.assertEqual(providers._visible("<thinking>hmm</thinking>Done."), "Done.")
        self.assertEqual(providers._visible("  Done.  "), "Done.")

    def test_closed_shuts_every_object_without_touching_the_original(self):
        schema = {"type": "object", "properties": {
            "inner": {"type": "object", "properties": {}},
            "open": {"type": "object", "additionalProperties": True},
        }}
        closed = providers._closed(schema)
        self.assertIs(closed["additionalProperties"], False)
        self.assertIs(closed["properties"]["inner"]["additionalProperties"], False)
        self.assertIs(closed["properties"]["open"]["additionalProperties"], True)
        self.assertNotIn("additionalProperties", schema)

    def test_loads_and_terse_never_raise(self):
        self.assertEqual(providers._loads("not json"), {})
        self.assertEqual(providers._loads(None), {})
        self.assertEqual(providers._terse('{"error": {"message": "bad key"}}'), "bad key")
        self.assertEqual(providers._terse("plain text"), "plain text")


if __name__ == "__main__":
    unittest.main()
