#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_text 合成 (domain.embedding_text・Phase 7a) のテスト.

DB 不要の純関数テスト。代表パターン:

- 全列あり (bratto 風・point_text 付き) の合成スナップショット
- point_text 無し (unionmonthly 風) の構造化列のみの合成
- 欠損列だらけでも文字列 "None" が混入しないこと
- SEARCH_TEXT_CAP (2000 字) 超過時のセクション単位省略 (⑥設備から落とす)
- search_text_hash の安定性
"""

import unittest

from domain.embedding_text import (
    DOCUMENT_PREFIX,
    SEARCH_TEXT_CAP,
    compose_search_text,
    search_text_hash,
)


def _bratto_prop() -> dict:
    """bratto 風の全列あり properties 行 (0001_pg_baseline.py の列定義準拠)。"""
    return {
        "id": 1,
        "source_site": "bratto",
        "external_id": "b0001",
        "title": "新宿セントラルパークタワー307号室",
        "prefecture_name": "東京都",
        "municipality": "新宿区",
        "address": "西新宿3-7-1",
        "layout": "1LDK",
        "area_m2": 25.53,
        "area_m2_max": None,
        "built_year": 2015,
        "structure": "RC",
        "floor_number": 3,
        "orientation_text": "南",
        "capacity_text": "2人",
        "point_text": "駅近物件♪\n近隣には  コンビニや飲食店が揃っております☆",
    }


def _bratto_children() -> tuple[list[str], list[dict], list[dict], list[dict]]:
    features = ["エアコン", "オートロック", "エアコン", "Wi-Fi"]
    accesses = [
        {
            "line_name": "JR山手線",
            "station_name": "新宿",
            "walk_minutes": 7,
            "raw_text": "JR山手線 新宿駅 徒歩7分",
        },
        {
            "line_name": "都営大江戸線",
            "station_name": "都庁前",
            "walk_minutes": 4,
            "raw_text": None,
        },
    ]
    plans = [
        {
            "plan_key": "s_short",
            "plan_name": "Sショート",
            "duration_min_days": 1,
            "duration_max_days": 29,
            "presentation_unit": "per_day",
            "rent_original_yen": 5000,
            "rent_current_yen": 4500,
            "raw_text": "Sショート 4,500円/日",
        },
        {
            "plan_key": "monthly",
            "plan_name": "マンスリー",
            "duration_min_days": 30,
            "duration_max_days": None,
            "presentation_unit": "per_month",
            "rent_original_yen": 120000,
            "rent_current_yen": 110000,
            "raw_text": None,
        },
    ]
    campaigns = [
        {"title": "初期費用半額", "content": "期間限定"},
        {"title": "初期費用半額", "content": "期間限定"},
    ]
    return features, accesses, plans, campaigns


class ComposeSearchTextFullTest(unittest.TestCase):
    """全列あり (bratto 風) の合成。"""

    def test_snapshot_with_all_sections(self):
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        expected = "\n".join(
            [
                "text: 新宿セントラルパークタワー307号室。"
                "東京都新宿区西新宿3-7-1にあるマンスリーマンション。"
                "間取りは1LDK、専有面積は25.53㎡、築2015年、RC、3階、南向き、定員2人。",
                "駅近物件♪ 近隣には コンビニや飲食店が揃っております☆",
                "アクセス: JR山手線 新宿駅 徒歩7分、都営大江戸線 都庁前駅 徒歩4分",
                "賃料プラン: Sショート 4,500円/日 (1〜29日)、マンスリー 110,000円/月 (30日〜)",
                "キャンペーン: 初期費用半額: 期間限定",
                "設備: エアコン、オートロック、Wi-Fi",
            ]
        )
        self.assertEqual(text, expected)

    def test_document_prefix_is_part_of_search_text(self):
        """非対称指示 (text: 接頭辞) は search_text 本体に含まれる (hash 対象)。"""
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        self.assertTrue(text.startswith(DOCUMENT_PREFIX))
        self.assertLessEqual(len(text), SEARCH_TEXT_CAP)

    def test_point_text_is_normalized(self):
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        self.assertIn("駅近物件♪ 近隣には コンビニや飲食店が揃っております☆", text)
        self.assertNotIn("\n", text.split("\n")[1])  # point_text 内に改行を残さない

    def test_features_are_deduplicated_preserving_order(self):
        features = ["エアコン", "オートロック", "エアコン", "Wi-Fi", "オートロック"]
        text = compose_search_text(_bratto_prop(), features, [], [], [])
        self.assertIn("設備: エアコン、オートロック、Wi-Fi", text)
        self.assertEqual(text.count("エアコン"), 1)
        self.assertEqual(text.count("オートロック"), 1)

    def test_area_range_and_max_only(self):
        prop = _bratto_prop() | {"area_m2": 20.0, "area_m2_max": 30.0}
        text = compose_search_text(prop, [], [], [], [])
        self.assertIn("専有面積は20.0〜30.0㎡", text)
        prop_max_only = _bratto_prop() | {"area_m2": None, "area_m2_max": 30.0}
        text = compose_search_text(prop_max_only, [], [], [], [])
        self.assertIn("専有面積は最大30.0㎡", text)

    def test_station_name_already_with_suffix_is_not_duplicated(self):
        accesses = [{"line_name": "JR山手線", "station_name": "新宿駅", "walk_minutes": 7}]
        text = compose_search_text(_bratto_prop(), [], accesses, [], [])
        self.assertIn("JR山手線 新宿駅 徒歩7分", text)
        self.assertNotIn("新宿駅駅", text)

    def test_access_and_plan_fall_back_to_raw_text(self):
        accesses = [{"raw_text": "JR中央線　立川駅\n徒歩10分"}]
        plans = [{"raw_text": "デイリー 3,000円/日"}]
        text = compose_search_text(_bratto_prop(), [], accesses, plans, [])
        self.assertIn("アクセス: JR中央線 立川駅 徒歩10分", text)
        self.assertIn("賃料プラン: デイリー 3,000円/日", text)

    def test_orientation_suffix_not_duplicated(self):
        prop = _bratto_prop() | {"orientation_text": "南向き"}
        text = compose_search_text(prop, [], [], [], [])
        self.assertIn("南向き、", text)
        self.assertNotIn("南向き向き", text)


class ComposeSearchTextUnionMonthlyTest(unittest.TestCase):
    """point_text 無し (unionmonthly 風) は構造化列のみで合成する。"""

    def test_unionmonthly_like_without_point_text(self):
        prop = {
            "title": "立川レジデンス101",
            "prefecture_name": "東京都",
            "municipality": "立川市",
            "address": "曙町2-1-1",
            "layout": "1K",
            "area_m2": 20.0,
            "built_year": 2020,
            "orientation_text": "南",
            "point_text": None,
        }
        text = compose_search_text(prop, ["バス・トイレ別"], [], [], [])
        self.assertIn("立川レジデンス101。東京都立川市曙町2-1-1にあるマンスリーマンション。", text)
        self.assertIn("間取りは1K、専有面積は20.0㎡、築2020年、南向き。", text)
        self.assertNotIn("駅近物件", text)  # 説明文セクションが立たない
        self.assertIn("設備: バス・トイレ別", text)
        self.assertNotIn("None", text)


class ComposeSearchTextMissingValuesTest(unittest.TestCase):
    """欠損列が多くても文字列 "None" が混入しないこと。"""

    def test_minimal_prop_with_none_children(self):
        prop = {
            "title": "ミニマム物件",
            "prefecture_name": None,
            "municipality": None,
            "address": None,
            "layout": None,
            "area_m2": None,
            "built_year": None,
            "structure": None,
            "floor_number": None,
            "orientation_text": None,
            "capacity_text": None,
            "point_text": None,
        }
        accesses = [{"line_name": None, "station_name": None, "walk_minutes": None, "raw_text": None}]
        plans = [{"plan_name": None, "rent_current_yen": None, "rent_original_yen": None, "raw_text": None}]
        campaigns = [{"title": None, "content": None}]
        text = compose_search_text(prop, ["", "  ", "エアコン"], accesses, plans, campaigns)
        self.assertEqual(text, "text: ミニマム物件。\n設備: エアコン")
        self.assertNotIn("None", text)
        self.assertNotIn("アクセス:", text)
        self.assertNotIn("賃料プラン:", text)
        self.assertNotIn("キャンペーン:", text)

    def test_empty_everything_returns_empty_string(self):
        self.assertEqual(compose_search_text({}, [], [], [], []), "")

    def test_builtin_name_none_is_not_leaked_from_non_numeric_values(self):
        # 非数値ゴミ (built_year="不明" 等) も "None" 同様に混入させない
        prop = _bratto_prop() | {"built_year": "不明", "floor_number": "x"}
        text = compose_search_text(prop, [], [], [], [])
        self.assertNotIn("築不明年", text)
        self.assertNotIn("x階", text)
        self.assertIn("間取りは1LDK", text)


class ComposeSearchTextCapTest(unittest.TestCase):
    """SEARCH_TEXT_CAP 超過時は低優先度セクションから丸ごと省略する。"""

    def test_cap_is_2000(self):
        self.assertEqual(SEARCH_TEXT_CAP, 2000)

    def test_features_dropped_first_when_over_cap(self):
        features, accesses, plans, campaigns = _bratto_children()
        features = [f"設備サンプル{i:03d}番" for i in range(200)]  # 200 件 (実データ max 62 の意地悪版)
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        self.assertLessEqual(len(text), SEARCH_TEXT_CAP)
        self.assertNotIn("設備:", text)  # ⑥設備が丸ごと落ちる
        # ①〜⑤は維持
        self.assertIn("新宿セントラルパークタワー307号室", text)
        self.assertIn("駅近物件♪", text)
        self.assertIn("アクセス: JR山手線 新宿駅", text)
        self.assertIn("賃料プラン: Sショート", text)
        self.assertIn("キャンペーン: 初期費用半額", text)

    def test_point_text_survives_at_expense_of_lower_sections(self):
        # ①+② がギリギリ収まる (~1991 字) 場合: ② は維持され ③〜⑥ が落ちる
        prop = _bratto_prop() | {"point_text": "あ" * 1900}
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(prop, features, accesses, plans, campaigns)
        self.assertLessEqual(len(text), SEARCH_TEXT_CAP)
        self.assertIn("新宿セントラルパークタワー307号室", text)  # ①は保持
        self.assertIn("あ" * 1900, text)  # ②も優先度順に保持
        self.assertNotIn("アクセス:", text)
        self.assertNotIn("賃料プラン:", text)
        self.assertNotIn("キャンペーン:", text)
        self.assertNotIn("設備:", text)

    def test_point_text_dropped_when_head_plus_point_exceeds_cap(self):
        # ①+② でも超過する場合: ② も丸ごと落ちて ① のみ残る
        prop = _bratto_prop() | {"point_text": "あ" * 1980}
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(prop, features, accesses, plans, campaigns)
        self.assertLessEqual(len(text), SEARCH_TEXT_CAP)
        self.assertIn("新宿セントラルパークタワー307号室", text)  # ①は保持
        self.assertNotIn("あ" * 1980, text)
        self.assertNotIn("アクセス:", text)
        self.assertNotIn("賃料プラン:", text)
        self.assertNotIn("キャンペーン:", text)
        self.assertNotIn("設備:", text)

    def test_no_truncation_inside_a_section(self):
        # 設備 100 件程度でキャップ内に収まる場合は途中切断されない
        features, accesses, plans, campaigns = _bratto_children()
        features = [f"設備{i:03d}" for i in range(100)]
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        self.assertLessEqual(len(text), SEARCH_TEXT_CAP)
        self.assertIn("設備: 設備000、設備001", text)
        self.assertIn("設備099", text)


class SearchTextHashTest(unittest.TestCase):
    """search_text_hash の安定性。"""

    def test_same_input_same_hash(self):
        features, accesses, plans, campaigns = _bratto_children()
        text1 = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        text2 = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        self.assertEqual(search_text_hash(text1), search_text_hash(text2))

    def test_different_input_different_hash(self):
        features, accesses, plans, campaigns = _bratto_children()
        text = compose_search_text(_bratto_prop(), features, accesses, plans, campaigns)
        changed = compose_search_text(
            _bratto_prop() | {"title": "内容が変わった物件"},
            features,
            accesses,
            plans,
            campaigns,
        )
        self.assertNotEqual(search_text_hash(text), search_text_hash(changed))

    def test_hash_format(self):
        digest = search_text_hash("何かのテキスト")
        self.assertIsInstance(digest, str)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, digest.lower())
        int(digest, 16)  # 16 進として解釈できること


if __name__ == "__main__":
    unittest.main()
