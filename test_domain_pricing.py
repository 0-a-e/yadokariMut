#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for domain.pricing (v2 stay + effective SSOT)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from domain.models import Campaign, PricePlan
from domain.pricing import (
    CONTRACT_FEE_YEN,
    MONTH_DAYS,
    calc_stay_days,
    calculate_stay_total,
    compute_catalog_min_daily,
    plan_rent_per_day,
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
        expected = (3600 + 500) * 30 + 20000 + CONTRACT_FEE_YEN
        self.assertEqual(result.grand_total, expected)


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


if __name__ == "__main__":
    unittest.main()
