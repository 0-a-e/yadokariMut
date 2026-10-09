#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""都道府県名マスタ (store.pref_master) の正本性テスト.

- PREF_DISPLAY_NAMES が 47 都道府県名を全値で網羅していること (欠落検知)
- config.json の sources.*.prefectures がマスタの slug/県名と一致していること
  (tests/test_site_contract_fee.py の catalog 全走査パターンを踏襲)
- 住所走査 (_split_pref_muni) がマスタ派生リストでも挙動不変であること
- bratto の県マップが config 依存で 0 件化しないこと (回帰防止)
"""

from __future__ import annotations

import unittest

from store.pref_master import PREF_DISPLAY_NAMES, pref_display_name
from store.source_catalog import load_app_config


# 47都道府県の表示名 (北海道/東京都/京都府/大阪府 + 43県)
ALL_47_PREF_NAMES = {
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府",
    "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県",
    "山口県", "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
    "沖縄県",
}


class PrefDisplayNamesTest(unittest.TestCase):
    """PREF_DISPLAY_NAMES の網羅性."""

    def test_covers_all_47_prefecture_names(self):
        values = set(PREF_DISPLAY_NAMES.values())
        self.assertEqual(values, ALL_47_PREF_NAMES)

    def test_values_are_unique_47(self):
        # gunma/gumma 別名 slug で値が重複するため、slug 数は 48・一意値は 47
        self.assertEqual(len(PREF_DISPLAY_NAMES), 48)
        self.assertEqual(len(set(PREF_DISPLAY_NAMES.values())), 47)

    def test_pref_display_name_fallback(self):
        self.assertEqual(pref_display_name("tokyo"), "東京都")
        self.assertEqual(pref_display_name("gumma"), "群馬県")
        # 不明 slug は slug 自身を返す (既存挙動)
        self.assertEqual(pref_display_name("fakesite"), "fakesite")
        self.assertEqual(pref_display_name(None, "X"), "X")


class ConfigPrefecturesContractTest(unittest.TestCase):
    """config.json sources.*.prefectures ↔ マスタの整合."""

    def test_config_sources_exist_for_sweep(self):
        # 全走査が空振りにならないための前提 (既知2サイト)
        cfg = load_app_config().get("sources", {})
        for sid in ("bratto", "unionmonthly"):
            self.assertIsInstance(
                cfg.get(sid, {}).get("prefectures"),
                dict,
                f"{sid}: config.json に prefectures が無い",
            )

    def test_config_prefecture_slug_and_name_match_master(self):
        sources = load_app_config().get("sources", {})
        checked = 0
        for sid, scfg in sources.items():
            prefs = scfg.get("prefectures") if isinstance(scfg, dict) else None
            if not isinstance(prefs, dict):
                continue
            for slug, meta in prefs.items():
                self.assertIn(
                    slug,
                    PREF_DISPLAY_NAMES,
                    f"{sid}.{slug}: マスタに無い slug",
                )
                name = meta.get("name") if isinstance(meta, dict) else None
                self.assertEqual(
                    name,
                    pref_display_name(slug),
                    f"{sid}.{slug}: config の name がマスタ表示名と不一致",
                )
                checked += 1
        self.assertGreaterEqual(checked, 47, "config 走査が期待より少ない")


class SplitPrefMuniTest(unittest.TestCase):
    """unionmonthly detail_parser._split_pref_muni (マスタ派生リスト版)."""

    def test_gunma_address(self):
        from sources.unionmonthly.detail_parser import _split_pref_muni

        self.assertEqual(
            _split_pref_muni("群馬県前橋市大手町1-1-1"), ("群馬県", "前橋市")
        )

    def test_hokkaido_address(self):
        from sources.unionmonthly.detail_parser import _split_pref_muni

        self.assertEqual(
            _split_pref_muni("北海道札幌市中央区北1条西2丁目"),
            ("北海道", "札幌市"),
        )

    def test_address_without_prefecture(self):
        from sources.unionmonthly.detail_parser import _split_pref_muni

        self.assertEqual(_split_pref_muni("渋谷区神南1-1-1"), (None, None))

    def test_none_and_empty(self):
        from sources.unionmonthly.detail_parser import _split_pref_muni

        self.assertEqual(_split_pref_muni(None), (None, None))
        self.assertEqual(_split_pref_muni(""), (None, None))


class BrattoPrefectureMapTest(unittest.TestCase):
    """bratto normalize._load_prefecture_map の 0 件化回帰防止."""

    def test_returns_47_entry_map(self):
        from sources.bratto.normalize import _load_prefecture_map

        name_to_slug, slug_to_name = _load_prefecture_map()
        self.assertEqual(len(name_to_slug), 47)
        self.assertEqual(len(slug_to_name), 47)
        # 正本由来の県名が入る (config name と同一値であることの合図)
        self.assertEqual(set(name_to_slug), ALL_47_PREF_NAMES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
