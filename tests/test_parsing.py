#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sources.parsing (スカラー共通パース層) のテスト。"""

import unittest

from sources.parsing import (
    FloorSpec,
    OrientationSpec,
    parse_access_parts,
    parse_area,
    parse_dates_from_text,
    parse_floor_text,
    parse_japanese_era,
    parse_money,
    parse_orientation_text,
    parse_walk_minutes,
    round_half_up,
    split_access,
)


class TestParseFloorText(unittest.TestCase):
    """階数パース (docs/floor-number-ssot-plan.md §3.1)。

    入力パターンは 2026-10-08 本番生HTML全件PoC の観測値に基づく
    (bratto「階建」セル / unionmonthly「所在階」セル)。
    """

    def test_bratto_concat_room_floor(self):
        self.assertEqual(parse_floor_text("10階建7階"), FloorSpec(7, 7, 10))
        self.assertEqual(parse_floor_text("3階建2階"), FloorSpec(2, 2, 3))

    def test_bratto_concat_goshitsu_number(self):
        # M>=100 は号室番号 (803号室 = 8階)。PoC で不整合 0 を確認済み
        self.assertEqual(parse_floor_text("9階建803階"), FloorSpec(8, 8, 9))
        self.assertEqual(parse_floor_text("14階建1302階"), FloorSpec(13, 13, 14))
        self.assertEqual(parse_floor_text("9階建410階"), FloorSpec(4, 4, 9))

    def test_bratto_building_only(self):
        self.assertEqual(parse_floor_text("10階建"), FloorSpec(None, None, 10))
        self.assertEqual(parse_floor_text("２階建"), FloorSpec(None, None, 2))  # 全角

    def test_bratto_multi_floor(self):
        self.assertEqual(parse_floor_text("2階建1・2階"), FloorSpec(1, 2, 2, multi_floor=True))

    def test_room_floor_exceeds_building_is_rejected(self):
        # 階数解釈が建物階数を超える / 号室解釾結果が建物階数を超える場合は不成立
        self.assertEqual(parse_floor_text("9階建11階"), FloorSpec(None, None, 9))
        self.assertEqual(parse_floor_text("2階建905階"), FloorSpec(None, None, 2))

    def test_union_shozokai(self):
        self.assertEqual(parse_floor_text("6階"), FloorSpec(6, 6, None))
        self.assertEqual(parse_floor_text("6階/11階建"), FloorSpec(6, 6, 11))

    def test_basement(self):
        self.assertEqual(parse_floor_text("地下1階"), FloorSpec(-1, -1, None))
        self.assertEqual(parse_floor_text("B3F"), FloorSpec(-3, -3, None))

    def test_empty_and_unmatched(self):
        self.assertEqual(parse_floor_text(""), FloorSpec())
        self.assertEqual(parse_floor_text(None), FloorSpec())
        self.assertEqual(parse_floor_text("   "), FloorSpec())
        self.assertEqual(parse_floor_text("階建"), FloorSpec())
        self.assertEqual(parse_floor_text("最上階"), FloorSpec())


class TestParseOrientationText(unittest.TestCase):
    """向き角度パース (docs/orientation-model-plan.md §3)。

    入力は 2026-10-08 本番生HTML全件PoC の観測 12 種 + 16 風位の残りを含む。
    """

    def test_observed_primary_winds(self):
        # 観測 8 正名
        expected = {
            "南": 180, "東": 90, "南西": 225, "西": 270,
            "南東": 135, "北東": 45, "北西": 315, "北": 0,
        }
        for raw, deg in expected.items():
            self.assertEqual(parse_orientation_text(raw), OrientationSpec(raw, deg), raw)

    def test_observed_aliases(self):
        # alias 吸収(東南→南東・東北→北東)。text(原文)は呼び出し側が保持する
        self.assertEqual(parse_orientation_text("東南"), OrientationSpec("南東", 135))
        self.assertEqual(parse_orientation_text("東北"), OrientationSpec("北東", 45))

    def test_observed_16_wind_granularity(self):
        # 16 風位粒度の実在値(潰さず保持)
        self.assertEqual(parse_orientation_text("南南西"), OrientationSpec("南南西", 203))
        self.assertEqual(parse_orientation_text("北北東"), OrientationSpec("北北東", 23))

    def test_all_16_winds_covered(self):
        # 未観測 4 種を含む 16 風位が全て閉集合で定義されている
        expected = {
            "北": 0, "北北東": 23, "北東": 45, "東北東": 68,
            "東": 90, "東南東": 113, "南東": 135, "南南東": 158,
            "南": 180, "南南西": 203, "南西": 225, "西南西": 248,
            "西": 270, "西北西": 293, "北西": 315, "北北西": 338,
        }
        for raw, deg in expected.items():
            spec = parse_orientation_text(raw)
            self.assertEqual((spec.label, spec.deg), (raw, deg), raw)

    def test_unknown_is_tolerant(self):
        self.assertEqual(parse_orientation_text("角部屋"), OrientationSpec())
        self.assertEqual(parse_orientation_text(""), OrientationSpec())
        self.assertEqual(parse_orientation_text(None), OrientationSpec())
        self.assertEqual(parse_orientation_text("南向き"), OrientationSpec())

    def test_round_half_up(self):
        # 半上げ一元(round() の half-to-even は使わない): 22.5→23 / 202.5→203
        self.assertEqual(round_half_up(22.5), 23)
        self.assertEqual(round_half_up(157.5), 158)
        self.assertEqual(round_half_up(202.5), 203)
        self.assertEqual(round_half_up(337.5), 338)
        self.assertEqual(round_half_up(0.5), 1)


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

    def test_western_bare_year(self):
        # bratto で実測された「年」接尾辞なしの西暦のみ表記
        self.assertEqual(parse_japanese_era("2019"), (2019, None))
        self.assertEqual(parse_japanese_era("2021"), (2021, None))
        # 月付きの既存解釈を壊さない
        self.assertEqual(parse_japanese_era("2024年11月"), (2024, 11))

    def test_era_omitted_2digit_year_stays_unparsable(self):
        # 元号省略の「18年」は紀年法が確定できないため None のまま
        self.assertEqual(parse_japanese_era("18年"), (None, None))
        self.assertEqual(parse_japanese_era("23年"), (None, None))

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
