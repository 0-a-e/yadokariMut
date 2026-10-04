#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sources.parsing (スカラー共通パース層) のテスト。"""

import unittest

from sources.parsing import (
    parse_access_parts,
    parse_area,
    parse_dates_from_text,
    parse_japanese_era,
    parse_money,
    parse_walk_minutes,
    split_access,
)


class TestParseMoney(unittest.TestCase):
    """bratto 版(円優先)を正として統合した金額パース。"""

    def test_yen_priority(self):
        self.assertEqual(parse_money("4,900円/日"), 4900)
        # 期間接尾辞付き総額でも「円」直前の数値を優先する
        self.assertEqual(parse_money("(月 75,000円/30日)"), 75000)
        self.assertEqual(parse_money("(週 14,350円/7日)"), 14350)
        self.assertEqual(parse_money("-1,080,000円/30日"), -1080000)

    def test_plain_numbers(self):
        self.assertEqual(parse_money("16,500"), 16500)
        self.assertEqual(parse_money("¥0"), 0)
        self.assertEqual(parse_money("384,000円"), 384000)

    def test_invalid(self):
        self.assertIsNone(parse_money(""))
        self.assertIsNone(parse_money(None))
        self.assertIsNone(parse_money("円のみ"))


class TestParseArea(unittest.TestCase):
    def test_area(self):
        self.assertEqual(parse_area("19.16㎡"), 19.16)
        self.assertEqual(parse_area("38.91m²"), 38.91)
        self.assertIsNone(parse_area(""))
        self.assertIsNone(parse_area(None))


class TestParseWalkMinutes(unittest.TestCase):
    def test_walk(self):
        self.assertEqual(parse_walk_minutes("徒歩 5分"), 5)
        self.assertEqual(parse_walk_minutes("徒歩8分"), 8)
        self.assertIsNone(parse_walk_minutes(""))
        self.assertIsNone(parse_walk_minutes(None))


class TestParseDatesFromText(unittest.TestCase):
    def test_year_carry(self):
        s, e = parse_dates_from_text("2026年5月1日から5月31日までの間にご契約いただいた方対象！")
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_month_only(self):
        s, e = parse_dates_from_text("2026年5月", default_year=2026)
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_nojapanese_month_with_default_year(self):
        s, e = parse_dates_from_text("5月中にご契約", default_year=2026)
        self.assertEqual(s, "2026-05-01")
        self.assertEqual(e, "2026-05-31")

    def test_empty(self):
        self.assertEqual(parse_dates_from_text(""), (None, None))
        self.assertEqual(parse_dates_from_text(None), (None, None))


class TestParseJapaneseEra(unittest.TestCase):
    """和暦/西暦の築年パース(unionmonthly の西暦専用実装を置換した共通版)。"""

    def test_showa(self):
        self.assertEqual(parse_japanese_era("昭和59年7月"), (1984, 7))

    def test_heisei(self):
        self.assertEqual(parse_japanese_era("平成15年3月"), (2003, 3))

    def test_reiwa_gannen(self):
        self.assertEqual(parse_japanese_era("令和元年5月"), (2019, 5))

    def test_reiwa(self):
        self.assertEqual(parse_japanese_era("令和6年11月築"), (2024, 11))

    def test_western(self):
        self.assertEqual(parse_japanese_era("200612"), (2006, 12))
        self.assertEqual(parse_japanese_era("2024年11月"), (2024, 11))
        self.assertEqual(parse_japanese_era("2024年"), (2024, None))

    def test_unparsable(self):
        self.assertEqual(parse_japanese_era(""), (None, None))
        self.assertEqual(parse_japanese_era(None), (None, None))
        self.assertEqual(parse_japanese_era("不明"), (None, None))


class TestSplitAccess(unittest.TestCase):
    """unionmonthly 系(寛容分割)。"""

    def test_fullwidth_spaces(self):
        self.assertEqual(split_access("JR山手線　渋谷駅　徒歩8分"), ("JR山手線", "渋谷駅", 8))

    def test_walk_only(self):
        self.assertEqual(split_access("徒歩8分"), (None, None, 8))

    def test_station_only(self):
        self.assertEqual(split_access("渋谷駅"), (None, "渋谷駅", None))


class TestParseAccessParts(unittest.TestCase):
    """bratto 系(厳密マッチ→フォールバック)。"""

    def test_strict(self):
        self.assertEqual(parse_access_parts("京成本線 千住大橋駅 徒歩 4分"), ("京成本線", "千住大橋駅", 4))

    def test_fallback(self):
        # 旧 bratto 実装の挙動を保持: フォールバック時の路線名は
        # 空文字列になる(空文字→None への正規化は行わない)
        line, station, walk = parse_access_parts("渋谷駅徒歩8分")
        self.assertEqual(line, "")
        self.assertEqual(station, "渋谷駅")
        self.assertEqual(walk, 8)


class TestBrattoParserCompatShim(unittest.TestCase):
    """旧 import 経路 (sources.bratto.parser) が再輸出を維持すること。"""

    def test_reexported(self):
        from sources.bratto import parser as legacy

        self.assertIs(legacy.parse_money, parse_money)
        self.assertIs(legacy.parse_area, parse_area)
        self.assertIs(legacy.parse_walk_minutes, parse_walk_minutes)
        self.assertIs(legacy.parse_dates_from_text, parse_dates_from_text)
        self.assertIs(legacy.parse_japanese_era, parse_japanese_era)


if __name__ == "__main__":
    unittest.main()
