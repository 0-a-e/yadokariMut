#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ingest.source_config (resolve_source_adapter_config の優先順位)."""

import unittest

from ingest.source_config import resolve_source_adapter_config
from scrape_settings import save_scrape_settings

SID = "bratto"


class ResolveSourceAdapterConfigTest(unittest.TestCase):
    def setUp(self):
        # scrape_settings の保存先 DB を隔離 PG DB へ差し替える
        from helpers import ScopedDb

        self._db = ScopedDb("source-config")
        self.addCleanup(self._db.close)

    def test_config_only_values_win(self):
        # (a) DB 保存が無ければ config.json 由来の値をそのまま使う
        cfg = {"sources": {SID: {"delay_seconds": 2.0}}}
        out = resolve_source_adapter_config(SID, config=cfg)
        self.assertEqual(out, {"delay_seconds": 2.0})

    def test_saved_db_value_wins_over_config(self):
        # (b) DB 保存値 (scrape_settings) は config.json 由来の値を上書きする
        cfg = {"sources": {SID: {"delay_seconds": 2.0}}}
        save_scrape_settings(
            {"sources": {SID: {"delay_seconds": 4.0, "cooldown_seconds": 900}}}
        )
        out = resolve_source_adapter_config(SID, config=cfg)
        self.assertEqual(out["delay_seconds"], 4.0)
        self.assertEqual(out["cooldown_seconds"], 900.0)

    def test_explicit_delay_wins_over_saved(self):
        # (c) run 時の明示 delay は DB 保存値よりさらに優先する
        cfg = {"sources": {SID: {"delay_seconds": 2.0}}}
        save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
        out = resolve_source_adapter_config(SID, delay=1.5, config=cfg)
        self.assertEqual(out["delay_seconds"], 1.5)

    def test_pref_filter_is_applied(self):
        # (d) pref_filter は config.json 由来の有無に関わらず run 時指定を反映する
        cfg = {"sources": {SID: {}}}
        out = resolve_source_adapter_config(
            SID, pref_filter=["tokyo", "osaka"], config=cfg
        )
        self.assertEqual(out["pref_filter"], ["tokyo", "osaka"])

    def test_saved_keys_do_not_break_pref_filter(self):
        # (e) 保存キーは delay_seconds / cooldown_seconds のみ。
        # pref_filter は保存上書きの対象外で config 由来の値が壊れない
        cfg = {"sources": {SID: {"delay_seconds": 2.0, "pref_filter": ["chiba"]}}}
        save_scrape_settings({"sources": {SID: {"delay_seconds": 4.0}}})
        out = resolve_source_adapter_config(SID, config=cfg)
        self.assertEqual(out, {"delay_seconds": 4.0, "pref_filter": ["chiba"]})


if __name__ == "__main__":
    unittest.main()
