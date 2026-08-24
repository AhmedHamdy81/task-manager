"""Task preset catalog helpers."""

from __future__ import annotations

import unittest

import task_preset_support as tps


class ClassifyScopeTitlesTests(unittest.TestCase):
    def test_splits_default_added_existed_missing(self):
        defaults = tps.DEFAULT_TASK_TITLES_BY_SCOPE["needs_offline_editing"]
        existing = [defaults[0], defaults[1], "Sync", "First Edit"]
        result = tps.classify_scope_titles("needs_offline_editing", existing)
        self.assertEqual(result["default"], list(defaults))
        self.assertEqual(result["added"], ["Sync", "First Edit"])
        self.assertEqual(result["existed"], [defaults[0], defaults[1]])
        self.assertEqual(result["missing"], list(defaults[2:]))

    def test_unknown_scope_is_all_added(self):
        result = tps.classify_scope_titles("not_a_scope", ["Custom"])
        self.assertEqual(result["default"], [])
        self.assertEqual(result["added"], ["Custom"])
        self.assertEqual(result["existed"], [])
        self.assertEqual(result["missing"], [])
