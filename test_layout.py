"""Checks for the server plan and the name colors. No Discord server needed.

    python -m unittest
"""

import re
import shutil
import tempfile
import types
import unittest
import unittest.mock
import zlib
from pathlib import Path

import colors
import layout
import store

ROOMS = [spec for _, channels in layout.PLAN for spec in channels]
NEEDED = ("welcome", "rules", "roles", "mod-log", "proposals", "general",
          "automod-alerts", "admin-log", "AFK")


class Plan(unittest.TestCase):
    def test_every_channel_the_code_looks_up_exists(self):
        names = [spec["name"] for spec in ROOMS]
        self.assertEqual(len(names), len(set(names)), "channel names must be unique")
        for name in NEEDED:
            self.assertIn(name, names)

    def test_text_channel_names_and_settings_are_ones_discord_accepts(self):
        for spec in ROOMS:
            if spec["kind"] in (layout.VOICE, layout.AFK):
                continue
            self.assertRegex(spec["name"], r"^[a-z0-9-]{1,100}$")
            self.assertLessEqual(len(spec["topic"]), 1024)
            self.assertTrue(0 <= spec["slowmode"] <= 21600)

    def test_the_heated_channels_are_slowed_down(self):
        by_name = {spec["name"]: spec for spec in ROOMS}
        self.assertGreater(by_name["politics-and-religion"]["slowmode"], 0)
        self.assertIn("Rule 2", by_name["politics-and-religion"]["topic"])

    def test_only_the_bot_posts_in_the_record_channels(self):
        by_name = {spec["name"]: spec for spec in ROOMS}
        for name in ("welcome", "rules", "roles", "mod-log"):
            self.assertEqual(by_name[name]["kind"], layout.READ_ONLY)
        self.assertEqual(by_name["automod-alerts"]["kind"], layout.HIDDEN)
        self.assertEqual(by_name["admin-log"]["kind"], layout.HIDDEN)

    def test_the_plan_fits_discords_limits(self):
        self.assertLessEqual(len(ROOMS) + len(layout.PLAN), 500)
        for _, channels in layout.PLAN:
            self.assertLessEqual(len(channels), 50)


class Colors(unittest.TestCase):
    def test_the_list_fits_one_dropdown(self):
        names = [name for name, _, _ in colors.COLORS]
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(len(names) + 1, 25)  # plus "No color"
        self.assertNotIn(colors.NONE, names)
        for name, value, look in colors.COLORS:
            self.assertTrue(0 < value <= 0xFFFFFF)
            self.assertLessEqual(len(f"{name} ({look})"), 100)  # a /color choice

    def test_each_color_gets_a_dot_of_its_own_color(self):
        names = [colors.swatch_name(n, v) for n, v, _ in colors.COLORS]
        self.assertEqual(len(names), len(set(names)))
        for name in names:  # Discord's rule for emoji names
            self.assertRegex(name, r"^[A-Za-z0-9_]{2,32}$")
        self.assertEqual(colors.swatch_name("Za'atar", 0x8A9A5B), "swatch_zaatar_8a9a5b")
        png = colors.dot_png(0x26A69A, size=8)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertLess(len(colors.dot_png(0x26A69A)), 256 * 1024)  # Discord's limit
        rows = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
        self.assertIn(bytes.fromhex("26a69aff"), rows)
        self.assertEqual(rows[1:5], bytes.fromhex("26a69a00"))  # a corner is clear

    def test_every_color_says_what_it_looks_like(self):
        select = colors.Picker().children[0]
        self.assertEqual(select.options[3].description, "Teal")
        text = colors.picker_text({"Qadisha": 11, "Cedar": 12})
        self.assertIn("<@&11> teal", text)
        self.assertIn("<@&12> dark green", text)
        self.assertLessEqual(len(colors.picker_text(
            {n: 10**18 for n, _, _ in colors.COLORS})), 2000)

    def test_picking_a_color_swaps_it_and_leaves_other_roles_alone(self):
        color_ids = {1, 2, 3}
        self.assertEqual(colors.changes([9, 1], 2, color_ids), ([2], [1]))
        self.assertEqual(colors.changes([9, 2], 2, color_ids), ([], []))
        self.assertEqual(colors.changes([9, 1, 3], None, color_ids), ([], [1, 3]))
        self.assertEqual(colors.changes([9], None, color_ids), ([], []))

    def test_the_picker_offers_every_color_and_none(self):
        select = colors.Picker().children[0]
        self.assertEqual(select.custom_id, "color-picker")
        self.assertEqual([o.value for o in select.options][-1], colors.NONE)
        self.assertEqual(len(select.options), len(colors.COLORS) + 1)


class Wearing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved_dir = store.DATA_DIR
        self._tmp = tempfile.mkdtemp()
        store.DATA_DIR = Path(self._tmp)
        store.save("colors", {"roles": {"Cedar": 1, "Knefeh": 2}, "message": None})
        colors._last_change.clear()

    def tearDown(self):
        store.DATA_DIR = self._saved_dir
        shutil.rmtree(self._tmp)

    def member(self, *role_ids):
        m = types.SimpleNamespace(id=7, roles=[types.SimpleNamespace(id=r) for r in role_ids],
                                  added=[], removed=[])

        async def add_roles(*roles, reason=None):
            m.added += [r.id for r in roles]

        async def remove_roles(*roles, reason=None):
            m.removed += [r.id for r in roles]
        m.add_roles, m.remove_roles = add_roles, remove_roles
        return m

    async def test_wearing_a_color_replaces_the_old_one(self):
        m = self.member(99, 1)
        self.assertIn("Knefeh", await colors.wear(m, "Knefeh"))
        self.assertEqual((m.added, m.removed), ([2], [1]))

    async def test_changes_are_rate_limited(self):
        m = self.member()
        await colors.wear(m, "Cedar")
        self.assertIn("few seconds", await colors.wear(m, "Knefeh"))
        self.assertEqual(m.added, [1])

    async def test_unknown_colors_are_refused_and_none_removes(self):
        self.assertIn("isn't available", await colors.wear(self.member(), "Gold"))
        m = self.member(2)
        self.assertIn("removed", await colors.wear(m, colors.NONE))
        self.assertEqual(m.removed, [2])


if __name__ == "__main__":
    unittest.main()


class RulesChannel(unittest.IsolatedAsyncioTestCase):
    """Discord's own rules channel becomes #rules."""

    def guild(self, rules, old, posters):
        async def history(limit):
            for author_id in posters:
                yield types.SimpleNamespace(author=types.SimpleNamespace(id=author_id))
        old.history = history
        return types.SimpleNamespace(
            rules_channel=rules, me=types.SimpleNamespace(id=1),
            default_role=object(), get_channel={old.id: old}.get)

    def channel(self, channel_id):
        channel = types.SimpleNamespace(id=channel_id)
        channel.edit = unittest.mock.AsyncMock()
        channel.delete = unittest.mock.AsyncMock()
        return channel

    async def test_the_rules_move_and_the_bots_old_channel_goes(self):
        rules, old = self.channel(50), self.channel(40)
        saved = {"channels": {"rules": 40}, "messages": {"rules": 99}}
        await layout._adopt_rules_channel(self.guild(rules, old, [1, 1]), saved, "cat")
        self.assertEqual(saved, {"channels": {"rules": 50}, "messages": {}})
        rules.edit.assert_awaited_once()
        self.assertEqual(rules.edit.call_args.kwargs["category"], "cat")
        old.delete.assert_awaited_once()

    async def test_an_old_channel_members_posted_in_is_kept(self):
        rules, old = self.channel(50), self.channel(40)
        saved = {"channels": {"rules": 40}, "messages": {}}
        await layout._adopt_rules_channel(self.guild(rules, old, [1, 7]), saved, "cat")
        self.assertEqual(saved["channels"]["rules"], 50)
        old.delete.assert_not_awaited()

    async def test_nothing_changes_without_a_rules_channel_or_once_moved(self):
        old = self.channel(40)
        for rules in (None, old):
            saved = {"channels": {"rules": 40}, "messages": {"rules": 99}}
            await layout._adopt_rules_channel(self.guild(rules, old, [1]), saved, "cat")
            self.assertEqual(saved, {"channels": {"rules": 40}, "messages": {"rules": 99}})
        old.edit.assert_not_awaited()
