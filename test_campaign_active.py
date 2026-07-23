#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for campaign_active (effective rent + is_active)."""

import unittest
from datetime import date

from campaign_active import (
    annotate_campaigns,
    campaign_is_active,
    compute_min_rent_from_plans,
    normalize_campaign_label,
    resolve_plan_effective_rent,
    resolve_plans_effective_rent,
)


class TestNormalizeLabel(unittest.TestCase):
    def test_hayawari(self):
        self.assertEqual(normalize_campaign_label("早割キャンペーン"), "早割")

    def test_tanki(self):
        self.assertEqual(normalize_campaign_label("短期割キャンペーン"), "特別割引")

    def test_ambiguous(self):
        self.assertIsNone(normalize_campaign_label("キャンペーン"))

    def test_empty(self):
        self.assertIsNone(normalize_campaign_label(None))
        self.assertIsNone(normalize_campaign_label(""))


class TestCampaignIsActive(unittest.TestCase):
    def test_expired(self):
        cam = {"starts_on": "2026-05-01", "ends_on": "2026-06-01"}
        self.assertFalse(campaign_is_active(cam, on_date=date(2026, 7, 20)))

    def test_active_in_range(self):
        cam = {"starts_on": "2026-05-01", "ends_on": "2026-08-01"}
        self.assertTrue(campaign_is_active(cam, on_date=date(2026, 7, 20)))

    def test_future_start(self):
        cam = {"starts_on": "2026-08-01", "ends_on": "2026-09-01"}
        self.assertFalse(campaign_is_active(cam, on_date=date(2026, 7, 20)))

    def test_null_end_still_active(self):
        cam = {"starts_on": None, "ends_on": None}
        self.assertTrue(campaign_is_active(cam, on_date=date(2026, 7, 20)))

    def test_require_known_end(self):
        cam = {"starts_on": None, "ends_on": None}
        self.assertFalse(
            campaign_is_active(cam, on_date=date(2026, 7, 20), require_known_end=True)
        )

    def test_annotate_date_end_unknown(self):
        cams = annotate_campaigns(
            [{"campaign_type": "500円割", "starts_on": None, "ends_on": None}],
            on_date=date(2026, 7, 20),
        )
        self.assertTrue(cams[0]["is_active"])
        self.assertTrue(cams[0]["date_end_unknown"])


class TestEffectiveRent(unittest.TestCase):
    def test_expired_hayawari_falls_back_to_original(self):
        plan = {
            "plan_code": "short",
            "plan_name": "ショート",
            "available": 1,
            "campaign_label": "早割キャンペーン",
            "original_daily_rent_yen": 4600,
            "discounted_daily_rent_yen": 3600,
            "original_total_yen": 4600 * 30,
            "discounted_total_yen": 3600 * 30,
        }
        cams = [
            {
                "campaign_type": "早割",
                "target_plan_code": "all",
                "starts_on": "2026-05-21",
                "ends_on": "2026-06-21",
            }
        ]
        out = resolve_plan_effective_rent(plan, cams, on_date=date(2026, 7, 20))
        self.assertEqual(out["effective_daily_rent_yen"], 4600)
        self.assertFalse(out["campaign_applied"])
        self.assertTrue(out["campaign_expired"])
        self.assertIsNone(out["effective_campaign_label"])

    def test_active_campaign_keeps_discount(self):
        plan = {
            "plan_code": "s_short",
            "plan_name": "Sショート",
            "available": 1,
            "campaign_label": "短期割キャンペーン",
            "original_daily_rent_yen": 5000,
            "discounted_daily_rent_yen": 4000,
            "original_total_yen": 100000,
            "discounted_total_yen": 80000,
        }
        cams = [
            {
                "campaign_type": "特別割引",
                "target_plan_code": "s_short",
                "starts_on": "2026-07-01",
                "ends_on": "2026-08-31",
            }
        ]
        out = resolve_plan_effective_rent(plan, cams, on_date=date(2026, 7, 20))
        self.assertEqual(out["effective_daily_rent_yen"], 4000)
        self.assertTrue(out["campaign_applied"])
        self.assertEqual(out["effective_campaign_label"], "短期割キャンペーン")

    def test_no_label_keeps_discounted(self):
        plan = {
            "plan_code": "long",
            "available": 1,
            "campaign_label": None,
            "original_daily_rent_yen": 3000,
            "discounted_daily_rent_yen": 3000,
        }
        out = resolve_plan_effective_rent(plan, [], on_date=date(2026, 7, 20))
        self.assertEqual(out["effective_daily_rent_yen"], 3000)
        self.assertFalse(out["campaign_applied"])

    def test_wrong_plan_target_does_not_match(self):
        plan = {
            "plan_code": "short",
            "available": 1,
            "campaign_label": "短期割キャンペーン",
            "original_daily_rent_yen": 5000,
            "discounted_daily_rent_yen": 4000,
        }
        cams = [
            {
                "campaign_type": "特別割引",
                "target_plan_code": "s_short",  # not short
                "starts_on": "2026-07-01",
                "ends_on": "2026-08-31",
            }
        ]
        out = resolve_plan_effective_rent(plan, cams, on_date=date(2026, 7, 20))
        self.assertEqual(out["effective_daily_rent_yen"], 5000)
        self.assertFalse(out["campaign_applied"])

    def test_min_from_effective(self):
        plans = resolve_plans_effective_rent(
            [
                {
                    "plan_code": "s_short",
                    "plan_name": "S",
                    "available": 1,
                    "campaign_label": "早割キャンペーン",
                    "original_daily_rent_yen": 5000,
                    "discounted_daily_rent_yen": 3000,
                    "discounted_total_yen": 90000,
                    "original_total_yen": 150000,
                },
                {
                    "plan_code": "long",
                    "plan_name": "L",
                    "available": 1,
                    "campaign_label": None,
                    "original_daily_rent_yen": 2500,
                    "discounted_daily_rent_yen": 2500,
                    "discounted_total_yen": 450000,
                    "original_total_yen": 450000,
                },
            ],
            [
                {
                    "campaign_type": "早割",
                    "target_plan_code": "all",
                    "starts_on": "2026-01-01",
                    "ends_on": "2026-02-01",  # expired
                }
            ],
            on_date=date(2026, 7, 20),
        )
        mins = compute_min_rent_from_plans(plans)
        # expired s_short → 5000, long → 2500 → min is long
        self.assertEqual(mins["min_daily_rent"], 2500)
        self.assertEqual(mins["min_plan_name"], "L")

    def test_corrupt_nine_x_snapshot_recomputed_from_structured_yen(self):
        """Site 1000%OFF bug: disc=9×orig while 早割 is ¥1000/day."""
        plan = {
            "plan_code": "short",
            "plan_name": "ショート1ヶ月~3ヶ月",
            "available": 1,
            "campaign_label": "早割キャンペーン",
            "original_daily_rent_yen": 4000,
            "discounted_daily_rent_yen": 36000,
            "original_total_yen": 120000,
            "discounted_total_yen": -1080000,
            "total_period_days": 30,
            "raw_text": "早割キャンペーン\n4,000円/日\n➡\n-36,000円/日\n(月 -1,080,000円/30日)",
        }
        cams = [
            {
                "campaign_type": "早割",
                "target_plan_code": "all",
                "discount_unit": "yen",
                "discount_value": 1000,
                "discount_max_yen": 120000,
                "period_max_days": 120,
                "starts_on": "2026-07-01",
                "ends_on": "2026-07-31",
            }
        ]
        out = resolve_plan_effective_rent(plan, cams, on_date=date(2026, 7, 20))
        self.assertEqual(out["effective_daily_rent_yen"], 3000)
        self.assertTrue(out["price_corrected"])
        self.assertEqual(out["price_resolution_status"], "corrected")
        self.assertIn("structured", out["price_resolution_method"] or "")

    def test_min_skips_non_positive_daily(self):
        mins = compute_min_rent_from_plans(
            [
                {
                    "available": 1,
                    "plan_name": "bad",
                    "effective_daily_rent_yen": -36000,
                    "effective_total_yen": -1,
                },
                {
                    "available": 1,
                    "plan_name": "ok",
                    "effective_daily_rent_yen": 3000,
                    "effective_total_yen": 90000,
                },
            ]
        )
        self.assertEqual(mins["min_daily_rent"], 3000)
        self.assertEqual(mins["min_plan_name"], "ok")


class TestEffectivePriceFilter(unittest.TestCase):
    """R1: max_monthly filter must use effective totals, not discounted snapshots."""

    def test_expired_discount_excluded_when_original_over_cap(self):
        from services import _passes_effective_price_filter

        plans = resolve_plans_effective_rent(
            [
                {
                    "plan_code": "short",
                    "plan_name": "ショート",
                    "available": 1,
                    "campaign_label": "早割キャンペーン",
                    "original_daily_rent_yen": 4600,
                    "discounted_daily_rent_yen": 3600,
                    "original_total_yen": 138000,
                    "discounted_total_yen": 30800,
                }
            ],
            [
                {
                    "campaign_type": "早割",
                    "target_plan_code": "all",
                    "starts_on": "2026-05-01",
                    "ends_on": "2026-06-01",
                }
            ],
            on_date=date(2026, 7, 20),
        )
        mins = compute_min_rent_from_plans(plans)
        # discounted 30800 would pass a 90000 cap, but effective is original
        self.assertFalse(
            _passes_effective_price_filter(
                plans,
                max_monthly_total_yen=90000,
                min_plan_total=mins["min_plan_total"],
            )
        )
        self.assertTrue(
            _passes_effective_price_filter(
                plans,
                max_monthly_total_yen=150000,
                min_plan_total=mins["min_plan_total"],
            )
        )

    def test_plan_code_specific_effective_total(self):
        from services import _passes_effective_price_filter

        plans = resolve_plans_effective_rent(
            [
                {
                    "plan_code": "short",
                    "plan_name": "ショート",
                    "available": 1,
                    "campaign_label": "早割キャンペーン",
                    "original_daily_rent_yen": 4000,
                    "discounted_daily_rent_yen": 3000,
                    "original_total_yen": 120000,
                    "discounted_total_yen": 90000,
                }
            ],
            [
                {
                    "campaign_type": "早割",
                    "target_plan_code": "all",
                    "starts_on": "2026-01-01",
                    "ends_on": "2026-12-31",
                }
            ],
            on_date=date(2026, 7, 20),
        )
        self.assertTrue(
            _passes_effective_price_filter(
                plans,
                max_monthly_total_yen=100000,
                plan_code="short",
            )
        )
        self.assertFalse(
            _passes_effective_price_filter(
                plans,
                max_monthly_total_yen=80000,
                plan_code="short",
            )
        )


if __name__ == "__main__":
    unittest.main()
