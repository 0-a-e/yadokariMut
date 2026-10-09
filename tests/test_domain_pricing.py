#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for domain.pricing (v2 stay + effective SSOT)."""

import unittest


from domain.models import Campaign, PricePlan
from domain.pricing import (
    MONTH_DAYS,
    calc_stay_days,
    calculate_stay_total,
    compute_catalog_min_daily,
    plan_management_per_day,
    plan_rent_per_day,
    plan_utilities_per_day,
    resolve_plan_effective,
    select_plan_for_stay,
    to_per_day,
)


def _bratto_plans():
    """Typical BraTTo-style daily plans with official duration bands."""
    return [
        PricePlan(
            plan_key="s_short",
            plan_name="Sショート",
            duration_min_days=1,
            duration_max_days=29,
            presentation_unit="per_day",
            rent_original_yen=5000,
            rent_current_yen=4500,
            management_yen=500,
            cleaning_yen=15000,
            campaign_label="早割",
        ),
        PricePlan(
            plan_key="short",
            plan_name="ショート",
            duration_min_days=30,
            duration_max_days=90,
            presentation_unit="per_day",
            rent_original_yen=4000,
            rent_current_yen=3600,
            management_yen=500,
            cleaning_yen=20000,
            campaign_label="早割",
        ),
        PricePlan(
            plan_key="middle",
            plan_name="ミドル",
            duration_min_days=91,
            duration_max_days=180,
            presentation_unit="per_day",
            rent_original_yen=3500,
            rent_current_yen=3200,
            management_yen=500,
            cleaning_yen=25000,
        ),
        PricePlan(
            plan_key="long",
            plan_name="ロング",
            duration_min_days=181,
            duration_max_days=None,
            presentation_unit="per_day",
            rent_original_yen=3000,
            rent_current_yen=3000,
            management_yen=500,
            cleaning_yen=30000,
        ),
    ]


def _union_plans():
    """Union Monthly monthly presentation (rent + kyoeihi style)."""
    return [
        PricePlan(
            plan_key="short",
            plan_name="ショート",
            duration_min_days=30,
            duration_max_days=89,
            presentation_unit="per_month",
            rent_original_yen=396000,
            rent_current_yen=354000,
            management_yen=28500,
            cleaning_yen=0,
            campaign_label="キャンペーン料金",
        ),
        PricePlan(
            plan_key="middle",
            plan_name="ミドル",
            duration_min_days=90,
            duration_max_days=209,
            presentation_unit="per_month",
            rent_original_yen=390000,
            rent_current_yen=345000,
            management_yen=28500,
            cleaning_yen=0,
            campaign_label="キャンペーン料金",
        ),
        PricePlan(
            plan_key="long",
            plan_name="ロング",
            duration_min_days=210,
            duration_max_days=729,
            presentation_unit="per_month",
            rent_original_yen=384000,
            rent_current_yen=336000,
            management_yen=28500,
            cleaning_yen=0,
            campaign_label="キャンペーン料金",
        ),
    ]


class TestStayDays(unittest.TestCase):
    def test_inclusive(self):
        self.assertEqual(calc_stay_days("2026-08-01", "2026-08-01"), 1)
        self.assertEqual(calc_stay_days("2026-08-01", "2026-08-30"), 30)
        self.assertEqual(calc_stay_days("2026-08-01", "2026-08-31"), 31)

    def test_invalid(self):
        self.assertIsNone(calc_stay_days("2026-08-10", "2026-08-01"))
        self.assertIsNone(calc_stay_days("bad", "2026-08-01"))


class TestToPerDay(unittest.TestCase):
    def test_daily(self):
        self.assertEqual(to_per_day(3600, "per_day"), 3600)

    def test_monthly(self):
        self.assertEqual(to_per_day(336000, "per_month"), 336000 // MONTH_DAYS)
        self.assertEqual(to_per_day(28500, "per_month"), 28500 // MONTH_DAYS)


class TestToPerDayStrict(unittest.TestCase):
    """to_per_day の厳格化 (決定 11): 正式単位 2 値のみ・未知単位は None 返し.

    正式単位集合の正本は domain.models.PresentationUnit。daily/day/monthly/
    month エイリアス受容は廃止し、エイリアス解決はパーサ/正規化層の責務。
    未知単位の黙認 per_day 換算は「約 7 倍過大」の無声失敗のため禁止。
    """

    def test_official_units_convert(self):
        self.assertEqual(to_per_day(3600, "per_day"), 3600)
        self.assertEqual(to_per_day(336000, "per_month"), 336000 // MONTH_DAYS)

    def test_unknown_unit_returns_none(self):
        self.assertIsNone(to_per_day(1000, "per_week"))

    def test_aliases_rejected(self):
        for alias in ("daily", "day", "monthly", "month"):
            self.assertIsNone(to_per_day(1000, alias), alias)

    def test_missing_unit_returns_none(self):
        self.assertIsNone(to_per_day(1000, ""))


class TestPerDayNonePropagation(unittest.TestCase):
    """plan_management/utilities_per_day の None 伝播 (決定 11).

    換算不能 (単位未知) を 0 円へ畳み込まない。0 円は「共益費なし」と
    「算出不能」を区別できず、日額合計の無声失敗になるため。
    """

    def _plan(self, **overrides) -> PricePlan:
        base = dict(
            plan_key="short",
            plan_name="ショート",
            duration_min_days=30,
            duration_max_days=89,
            presentation_unit="per_day",
            rent_original_yen=4000,
            rent_current_yen=3600,
            management_yen=500,
        )
        base.update(overrides)
        return PricePlan(**base)

    def test_management_unknown_unit_is_none(self):
        plan = self._plan(presentation_unit="per_week")
        self.assertIsNone(plan_management_per_day(plan))

    def test_management_missing_is_zero(self):
        plan = self._plan(management_yen=None)
        self.assertEqual(plan_management_per_day(plan), 0)

    def test_utilities_unknown_unit_is_none(self):
        plan = self._plan(
            presentation_unit="per_week",
            utilities_included=False,
            utilities_yen=3000,
        )
        self.assertIsNone(plan_utilities_per_day(plan))

    def test_utilities_included_is_zero_even_if_unit_unknown(self):
        # 光熱費込みは金額換算を要しないため 0 円のまま
        plan = self._plan(presentation_unit="per_week", utilities_included=True)
        self.assertEqual(plan_utilities_per_day(plan), 0)

    def test_rent_per_day_unknown_unit_is_none(self):
        plan = self._plan(presentation_unit="per_week")
        self.assertIsNone(plan_rent_per_day(plan))

    def test_stay_total_excludes_incalculable_plan(self):
        # 日額合計が算出不能なプランは明示的な欠落として計算しない
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=[self._plan(presentation_unit="per_week")],
            use_structured_campaigns=False,
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.breakdown)
        self.assertIsNone(result.grand_total)

    def test_stay_total_structured_campaign_path_excludes_too(self):
        # 構造化キャンペーン経路でも original 日額の算出不能は欠落扱い
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=[self._plan(presentation_unit="per_week")],
            campaigns=[
                Campaign(
                    campaign_type="500円割",
                    discount_unit="yen",
                    discount_value=500,
                    target_plan_key="short",
                    starts_on="2026-01-01",
                    ends_on="2026-12-31",
                )
            ],
            use_structured_campaigns=True,
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.grand_total)


class TestSelectPlan(unittest.TestCase):
    def test_exact_short(self):
        sel = select_plan_for_stay(_bratto_plans(), 45)
        self.assertIsNotNone(sel)
        self.assertEqual(sel["plan_key"], "short")
        self.assertFalse(sel["used_fallback"])

    def test_exact_long(self):
        sel = select_plan_for_stay(_bratto_plans(), 200)
        self.assertEqual(sel["plan_key"], "long")

    def test_union_middle(self):
        sel = select_plan_for_stay(_union_plans(), 100)
        self.assertEqual(sel["plan_key"], "middle")
        self.assertFalse(sel["used_fallback"])

    def test_fallback_when_s_short_missing(self):
        plans = [p for p in _bratto_plans() if p.plan_key != "s_short"]
        sel = select_plan_for_stay(plans, 14)
        self.assertIsNotNone(sel)
        self.assertTrue(sel["used_fallback"])
        self.assertEqual(sel["plan_key"], "short")


class TestEffective(unittest.TestCase):
    def test_active_campaign_keeps_current(self):
        plan = _bratto_plans()[1]
        cams = [
            Campaign(
                campaign_type="早割",
                starts_on="2026-01-01",
                ends_on="2026-12-31",
                target_plan_key="all",
                is_active=True,
            )
        ]
        resolved = resolve_plan_effective(plan, cams, on_date="2026-08-01")
        self.assertTrue(resolved.campaign_applied)
        self.assertEqual(resolved.effective_rent_yen, 3600)

    def test_expired_campaign_falls_to_original(self):
        plan = _bratto_plans()[1]
        cams = [
            Campaign(
                campaign_type="早割",
                starts_on="2025-01-01",
                ends_on="2025-06-01",
                target_plan_key="short",
            )
        ]
        resolved = resolve_plan_effective(plan, cams, on_date="2026-08-01")
        self.assertTrue(resolved.campaign_expired)
        self.assertEqual(resolved.effective_rent_yen, 4000)


class TestStayTotalBratto(unittest.TestCase):
    def test_30_day_short(self):
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=_bratto_plans(),
            campaigns=[
                Campaign(
                    campaign_type="早割",
                    starts_on="2026-01-01",
                    ends_on="2026-12-31",
                    target_plan_key="all",
                )
            ],
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.stay_days, 30)
        self.assertEqual(result.plan_key, "short")
        # effective current 3600 + mgmt 500
        self.assertEqual(result.breakdown.rent_daily, 3600)
        self.assertEqual(result.breakdown.management_daily, 500)
        # contract_fee_yen 未指定 = 算出不能 → 総額から除外し warnings で明示
        expected = (3600 + 500) * 30 + 20000
        self.assertEqual(result.grand_total, expected)
        self.assertIsNone(result.breakdown.contract_fee)
        self.assertTrue(any("契約事務手数料" in w and "不明" in w for w in result.warnings))


class TestStayTotalUnion(unittest.TestCase):
    def test_monthly_to_daily_long(self):
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2027-03-01",  # ~213 days inclusive? Aug1-Mar1 = 212+1=213
            plans=_union_plans(),
            campaigns=[
                Campaign(
                    campaign_type="キャンペーン料金",
                    starts_on="2026-01-01",
                    ends_on="2027-12-31",
                    target_plan_key="all",
                )
            ],
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.plan_key, "long")
        rent_daily = 336000 // MONTH_DAYS
        mgmt_daily = 28500 // MONTH_DAYS
        self.assertEqual(result.breakdown.rent_daily, rent_daily)
        self.assertEqual(result.breakdown.management_daily, mgmt_daily)
        self.assertEqual(plan_rent_per_day(resolve_plan_effective(_union_plans()[2], [
            Campaign(campaign_type="キャンペーン料金", starts_on="2026-01-01", ends_on="2027-12-31"),
        ], on_date="2026-08-01")), rent_daily)

    def test_union_short_band(self):
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-09-15",  # 46 days
            plans=_union_plans(),
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.plan_key, "short")
        self.assertEqual(result.breakdown.rent_daily, 354000 // MONTH_DAYS)


class TestCatalogMin(unittest.TestCase):
    def test_min_among_bratto(self):
        resolved = [resolve_plan_effective(p) for p in _bratto_plans()]
        mins = compute_catalog_min_daily(resolved)
        # long effective 3000 is cheapest daily
        self.assertEqual(mins["catalog_rent_per_day_yen"], 3000)
        self.assertEqual(mins["plan_key"], "long")


class TestStructuredYenCampaign(unittest.TestCase):
    def test_yen_discount(self):
        plans = [
            PricePlan(
                plan_key="short",
                plan_name="ショート",
                duration_min_days=30,
                duration_max_days=90,
                presentation_unit="per_day",
                rent_original_yen=4000,
                rent_current_yen=4000,
                management_yen=0,
                cleaning_yen=10000,
            )
        ]
        cams = [
            Campaign(
                campaign_type="500円割",
                discount_unit="yen",
                discount_value=500,
                target_plan_key="short",
                starts_on="2026-01-01",
                ends_on="2026-12-31",
            )
        ]
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=plans,
            campaigns=cams,
            use_structured_campaigns=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.breakdown.rent_daily, 3500)


class TestPlanCodeMaps(unittest.TestCase):
    """パーサ共有のプランコード語彙マップ (サイトパッケージ移設後の所在確認)。

    語彙正本の所在は設計 §3.6 により src/sources/<site>/plans.py へ移設
    (表示ラベルの SSOT は domain.plan_catalog)。import 先変更のみで
    assertion は移設前と同一を維持する。
    """

    def test_resolve_bratto_plan_code(self):
        from sources.bratto.plans import resolve_bratto_plan_code

        self.assertEqual(resolve_bratto_plan_code("Sショート 1日~29日"), "s_short")
        self.assertEqual(resolve_bratto_plan_code("sショート"), "s_short")
        # 「ショート」が「sショート」に部分一致するため s_short が優先される(辞書順)
        self.assertEqual(resolve_bratto_plan_code("ショート 30日~89日"), "short")
        self.assertEqual(resolve_bratto_plan_code("ミドル 3ヶ月~6ヶ月"), "middle")
        self.assertEqual(resolve_bratto_plan_code("ロング 6ヶ月以上"), "long")
        self.assertEqual(resolve_bratto_plan_code("謎のプラン"), "other")
        self.assertEqual(resolve_bratto_plan_code(""), "other")

    def test_union_plan_code_map(self):
        from sources.unionmonthly.plans import UNION_PLAN_CODE_MAP

        self.assertEqual(UNION_PLAN_CODE_MAP["ショート"], "short")
        self.assertEqual(UNION_PLAN_CODE_MAP["スーパーショート"], "s_short")
        self.assertEqual(UNION_PLAN_CODE_MAP["sショート"], "s_short")
        self.assertEqual(UNION_PLAN_CODE_MAP["セミショート"], "semi_short")
        self.assertEqual(UNION_PLAN_CODE_MAP["ミドル"], "middle")
        self.assertEqual(UNION_PLAN_CODE_MAP["ロング"], "long")


class TestCampaignAliasHelpers(unittest.TestCase):
    """campaign target_plan エイリアス変換の正本2関数 (code→key / key→code)。

    DB 列は target_plan_key のみ (store.schema) を正本とする。
    """

    def test_campaign_with_plan_key_code_only(self):
        from domain.pricing import campaign_with_plan_key

        src = {"target_plan_code": "short", "title": "c1"}
        out = campaign_with_plan_key(src)
        self.assertEqual(out["target_plan_key"], "short")
        # legacy code は保持 (応答への載せ忘れ防止)
        self.assertEqual(out["target_plan_code"], "short")
        # 純関数: 入力は変更しない
        self.assertIsNone(src.get("target_plan_key"))

    def test_campaign_with_plan_key_key_only_unchanged(self):
        from domain.pricing import campaign_with_plan_key

        src = {"target_plan_key": "long"}
        out = campaign_with_plan_key(src)
        self.assertEqual(out["target_plan_key"], "long")
        self.assertNotIn("target_plan_code", out)

    def test_campaign_with_plan_key_both_prefers_key(self):
        from domain.pricing import campaign_with_plan_key

        out = campaign_with_plan_key(
            {"target_plan_key": "middle", "target_plan_code": "s_short"}
        )
        self.assertEqual(out["target_plan_key"], "middle")

    def test_campaign_with_plan_key_accepts_dataclass(self):
        from domain.pricing import campaign_with_plan_key

        out = campaign_with_plan_key(Campaign(title="c2", target_plan_key="all"))
        self.assertEqual(out["target_plan_key"], "all")

    def test_campaign_with_plan_code_alias(self):
        from domain.pricing import campaign_with_plan_code_alias

        src = {"target_plan_key": "long", "title": "c3"}
        out = campaign_with_plan_code_alias(src)
        self.assertEqual(out["target_plan_code"], "long")
        self.assertEqual(out["target_plan_key"], "long")
        self.assertEqual(src, {"target_plan_key": "long", "title": "c3"})

    def test_campaign_targets_plan_key_via_alias(self):
        from domain.pricing import campaign_targets_plan_key

        # code のみの legacy 入力でも key 正規化を経由して合致する
        self.assertTrue(campaign_targets_plan_key({"target_plan_code": "short"}, "short"))
        self.assertFalse(campaign_targets_plan_key({"target_plan_code": "short"}, "long"))


if __name__ == "__main__":
    unittest.main()
