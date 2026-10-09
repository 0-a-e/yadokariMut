#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""プラン表示語彙辞書 (domain.plan_catalog・設計 §3.6 / 第 1.7 段) のテスト.

- 5 正規コードのラベル解決 (レンジ無し・名称のみ)
- 開集合: 未知コードは plan_name 生値フォールバック (生名 → plan_label 一意表示)
- campaigns の擬似コード all は辞書外で「すべてのプラン」に解決
- 差分検知 (§5-5): 観測語彙 (plan_key ∪ target_plan_key・all 除外) vs 辞書コード
- semi_short 誤分類の回帰 (§4.3): 辞書解決により Sショート に誤表示されないこと
"""

import unittest

from domain.plan_catalog import (
    ALL_PLANS_LABEL,
    PLAN_CATALOG,
    plan_catalog_codes,
    plan_label,
    target_plan_label,
    unknown_plan_codes,
)
from domain.models import Campaign, PricePlan
from helpers import ScopedDb, make_draft
from store.repository import Repository, open_connection


class TestPlanLabel(unittest.TestCase):
    """辞書 5 コードのラベル解決 (名称のみ・帯レンジは含めない)."""

    def test_five_codes_resolve_to_catalog_labels(self):
        expected = {
            "s_short": "Sショート",
            "semi_short": "セミショート",
            "short": "ショート",
            "middle": "ミドル",
            "long": "ロング",
        }
        self.assertEqual(set(plan_catalog_codes()), set(expected))
        for code, label in expected.items():
            with self.subTest(code=code):
                self.assertEqual(plan_label(code, None), label)
                # 既知コードでは plan_name より辞書ラベルを優先する
                self.assertEqual(plan_label(code, "どんな生名でも"), label)

    def test_known_code_with_range_like_plan_name_drops_range(self):
        """unionmonthly のレンジ付き plan_name でもラベルはレンジ無し (§3.6)."""
        self.assertEqual(
            plan_label("semi_short", "セミショート（15日以上-1ヶ月未満）"),
            "セミショート",
        )

    def test_semi_short_is_not_misclassified_as_s_short(self):
        """semi_short 誤分類の回帰 (§4.3・-α の BE 側相当).

        FE normalizePlanCode の 4 コード閉集合では semi_short が plan_name
        の「1ヶ月未満」部分一致で Sショート に誤分類されていた。BE 辞書解決
        では semi_short が正しく「セミショート」に解決されることを固定する。
        """
        raw_name = "セミショート（15日以上-1ヶ月未満）"
        self.assertNotEqual(plan_label("semi_short", raw_name), "Sショート")
        self.assertEqual(plan_label("semi_short", raw_name), "セミショート")

    def test_unknown_code_falls_back_to_raw_plan_name(self):
        """開集合: 辞書に無い plan_key は plan_name 生値で配信 (§3.6)."""
        self.assertEqual(plan_label("super_short", "スーパーショート"), "スーパーショート")
        # code NULL / 空 も生名フォールバック
        self.assertEqual(plan_label(None, "謎のプラン"), "謎のプラン")
        self.assertEqual(plan_label("", "謎のプラン"), "謎のプラン")

    def test_unknown_code_without_plan_name_returns_empty(self):
        self.assertEqual(plan_label("super_short", None), "")
        self.assertEqual(plan_label(None, None), "")


class TestTargetPlanLabel(unittest.TestCase):
    """campaigns.target_plan_key の表示解決 (all は辞書外の擬似コード)."""

    def test_all_and_empty_mean_all_plans(self):
        self.assertEqual(target_plan_label("all"), ALL_PLANS_LABEL)
        # campaign_targets_plan_key と同じ語彙: 空 / NULL も全プラン扱い
        self.assertEqual(target_plan_label(None), ALL_PLANS_LABEL)
        self.assertEqual(target_plan_label(""), ALL_PLANS_LABEL)
        self.assertEqual(target_plan_label("  "), ALL_PLANS_LABEL)

    def test_all_is_not_in_catalog(self):
        """all はプラン語彙辞書に入れない (差分検知の母集団からも除外)."""
        self.assertNotIn("all", PLAN_CATALOG)
        self.assertNotIn("all", plan_catalog_codes())

    def test_known_and_unknown_codes(self):
        self.assertEqual(target_plan_label("middle"), "ミドル")
        self.assertEqual(target_plan_label("semi_short"), "セミショート")
        # 未知コードは生値 (差分検知で仕分けるまでの一時表示)
        self.assertEqual(target_plan_label("super_short"), "super_short")


class TestUnknownPlanCodes(unittest.TestCase):
    """差分検知ロジック (§5-5): 観測語彙 vs 辞書コード集合."""

    def test_closed_vocabulary_yields_no_unknowns(self):
        observed = ["s_short", "semi_short", "short", "middle", "long", "all", None, ""]
        self.assertEqual(unknown_plan_codes(observed), [])

    def test_unmapped_code_is_reported_sorted_and_normalized(self):
        observed = ["short", " SUPER_SHORT ", "super_short", None, "all"]
        # 正規化 (strip + lower) で畳まれ、ソート済みで返る (決定的)
        self.assertEqual(unknown_plan_codes(observed), ["super_short"])

    def test_case_folding_against_known_codes(self):
        # DB 正本は小書き正規化済みだが、未来の揺れは正規化で吸収して検知対象外
        self.assertEqual(unknown_plan_codes(["SHORT", "Long"]), [])


class TestVocabularyDiffAgainstDb(unittest.TestCase):
    """fixtures DB の実語彙 (SELECT DISTINCT 相当) vs 辞書の差分検知 (§5-5).

    実 DB が手元に無いため fixtures ベースで、差分検知 CLI / 日次ジョブが
    行う「観測語彙集合の組立 → unknown_plan_codes」の一連を検証する。
    """

    def setUp(self):
        self._db = ScopedDb("plan-catalog")
        self.addCleanup(self._db.close)
        self.repo = Repository()

    def _observed_vocabulary(self) -> list[str | None]:
        """SELECT DISTINCT plan_key ∪ campaigns.target_plan_key 相当の語彙集合."""
        with open_connection() as conn:
            plan_keys = [
                r["plan_key"] for r in conn.execute("SELECT DISTINCT plan_key FROM price_plans")
            ]
            targets = [
                r["target_plan_key"]
                for r in conn.execute("SELECT DISTINCT target_plan_key FROM campaigns")
            ]
        return plan_keys + targets

    def test_known_vocabulary_yields_no_unknowns(self):
        self.repo.upsert_property(
            make_draft(
                "vocab-known",
                price_plans=[
                    PricePlan(plan_key=key, plan_name=key, duration_min_days=1)
                    for key in ("s_short", "semi_short", "short", "middle", "long")
                ],
                campaigns=[Campaign(title="全プラン対象", target_plan_key="all")],
            )
        )
        self.assertEqual(unknown_plan_codes(self._observed_vocabulary()), [])

    def test_unmapped_plan_key_is_detected(self):
        """新サイトが未知コードを書き込んだら差分検知が検出する (開集合の運用前提)."""
        self.repo.upsert_property(
            make_draft(
                "vocab-new",
                price_plans=[
                    PricePlan(plan_key="short", plan_name="ショート", duration_min_days=30),
                    PricePlan(
                        plan_key="super_short",
                        plan_name="スーパーショート",
                        duration_min_days=1,
                    ),
                ],
                campaigns=[Campaign(title="対象", target_plan_key="super_short")],
            )
        )
        self.assertEqual(unknown_plan_codes(self._observed_vocabulary()), ["super_short"])


class TestDeliveryDetailRoute(unittest.TestCase):
    """詳細経路 (get_property_detail) も辞書解決ラベルを配信すること (§3.6).

    search / geojson / KML 経由の plan_label は test_web_api /
    test_search_batching / test_export_kml_api 側の assert で担保。
    本クラスは detail 経路 (campaign_row_to_api のもう一つの呼び出し元) と、
    semi_short 誤分類の wire レベル回帰 (§4.3) を検証する。
    """

    def setUp(self):
        self._db = ScopedDb("plan-catalog-detail")
        self.addCleanup(self._db.close)
        self.repo = Repository()

    def test_detail_carries_plan_label_and_target_plan_label(self):
        from store import api_queries

        pid = self.repo.upsert_property(
            make_draft(
                "detail-label",
                price_plans=[
                    PricePlan(
                        plan_key="semi_short",
                        plan_name="セミショート（15日以上-1ヶ月未満）",
                        duration_min_days=15,
                        duration_max_days=29,
                        presentation_unit="per_day",
                        rent_current_yen=3000,
                    ),
                    PricePlan(
                        plan_key="long",
                        plan_name="ロング",
                        duration_min_days=210,
                        presentation_unit="per_day",
                        rent_current_yen=2000,
                    ),
                ],
                campaigns=[
                    Campaign(title="セミショート限定", target_plan_key="semi_short"),
                    Campaign(title="全プラン対象", target_plan_key="all"),
                ],
            )
        )
        detail = api_queries.get_property_detail(pid)
        plans = {p["plan_key"]: p for p in detail["rent_plans"]}
        # レンジ付き plan_name でもラベルはレンジ無し。Sショート 誤分類は起きない
        self.assertEqual(plans["semi_short"]["plan_label"], "セミショート")
        self.assertEqual(plans["long"]["plan_label"], "ロング")
        camps = {c["title"]: c for c in detail["campaigns"]}
        self.assertEqual(camps["セミショート限定"]["target_plan_label"], "セミショート")
        self.assertEqual(camps["全プラン対象"]["target_plan_label"], "すべてのプラン")


if __name__ == "__main__":
    unittest.main()
