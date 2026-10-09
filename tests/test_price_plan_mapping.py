#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""price_plan_row_to_rent_plan / apply_effective_rent_plans の換算透過テスト (決定 11).

単位未知など換算不能な日額を 0 円へ畳み込まず null を透過し、30 日総額も
null となること (「or 0」畳み込みの無声失敗防止) を検証する。
store.queries._common は純関数のため DB を介さず行辞書を直接与える。
"""

from __future__ import annotations

import unittest

from store.queries._common import (
    MONTH_DAYS,
    apply_effective_rent_plans,
    price_plan_row_to_rent_plan,
)


def _row(**overrides):
    base = {
        "plan_key": "short",
        "plan_name": "ショート",
        "duration_min_days": 30,
        "duration_max_days": 89,
        "available": 1,
        "presentation_unit": "per_day",
        "rent_original_yen": 4000,
        "rent_current_yen": 3600,
        "management_yen": 500,
        "utilities_yen": None,
        "utilities_included": 1,
        "cleaning_yen": 20000,
        "campaign_label": None,
        "raw_text": None,
    }
    base.update(overrides)
    return base


class TestPricePlanRowToRentPlanTransparency(unittest.TestCase):
    def test_management_null_is_transparent(self):
        # 決定 11: 共益費未記載は 0 円へ畳み込まず null (「なし」と「不能」の区別)
        plan = price_plan_row_to_rent_plan(_row(management_yen=None))
        self.assertIsNone(plan["management_fee_daily_yen"])
        # 日額が null なら 30 日総額も null
        self.assertIsNone(plan["discounted_total_yen"])
        self.assertIsNone(plan["original_total_yen"])

    def test_totals_compose_with_management(self):
        plan = price_plan_row_to_rent_plan(_row())
        self.assertEqual(plan["management_fee_daily_yen"], 500)
        self.assertEqual(plan["original_total_yen"], (4000 + 500) * MONTH_DAYS)
        self.assertEqual(plan["discounted_total_yen"], (3600 + 500) * MONTH_DAYS)

    def test_unknown_unit_propagates_none_to_daily_and_totals(self):
        plan = price_plan_row_to_rent_plan(_row(presentation_unit="per_week"))
        self.assertIsNone(plan["original_daily_rent_yen"])
        self.assertIsNone(plan["discounted_daily_rent_yen"])
        self.assertIsNone(plan["management_fee_daily_yen"])
        self.assertIsNone(plan["original_total_yen"])
        self.assertIsNone(plan["discounted_total_yen"])

    def test_effective_total_null_when_management_null(self):
        plans = [price_plan_row_to_rent_plan(_row(management_yen=None))]
        out = apply_effective_rent_plans(plans, [])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["effective_daily_rent_yen"], 3600)
        self.assertIsNone(out[0]["effective_total_yen"])

    def test_effective_total_composes_when_calculable(self):
        plans = [price_plan_row_to_rent_plan(_row())]
        out = apply_effective_rent_plans(plans, [])
        self.assertEqual(out[0]["effective_daily_rent_yen"], 3600)
        self.assertEqual(out[0]["effective_total_yen"], (3600 + 500) * MONTH_DAYS)


if __name__ == "__main__":
    unittest.main()
