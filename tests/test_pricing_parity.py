#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BE/FE 賃料計算エンジン parity テスト.

contracts/stay_calc_cases.json の共有ケースを FE (lib/rentCalculator.ts,
frontend/src/lib/rentCalculator.parity.test.ts) と同一の入力・期待値で消費し、
両エンジンの数値・プラン選択・警告文言の一致を保証する。期待値の正本は
JSON 側にあり、本テストは JSON をそのままアサートするだけ(変換ロジック無し)。
"""

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from domain.pricing import calculate_stay_total

CASES_PATH = Path(__file__).resolve().parents[1] / "contracts" / "stay_calc_cases.json"


def _load_cases() -> list[dict]:
    with CASES_PATH.open(encoding="utf-8") as f:
        return json.load(f)["cases"]


class StayCalcParityTest(unittest.TestCase):
    """calculate_stay_total が共有期待値と完全一致することを検証する."""

    maxDiff = None

    def test_parity_cases(self) -> None:
        cases = _load_cases()
        self.assertGreater(len(cases), 10)
        for case in cases:
            with self.subTest(case=case["name"]):
                self._run_case(case)

    def _run_case(self, case: dict) -> None:
        inp = case["input"]
        if case.get("entry") == "days":
            # FE の日数指定入口(stayDays + onDate)は、BE では
            # on_date を check_in とし stay_days 日後を check_out とした日付入口と等価
            on = date.fromisoformat(inp["on_date"])
            check_in = inp["on_date"]
            check_out = (on + timedelta(days=int(inp["stay_days"]) - 1)).isoformat()
        else:
            check_in = inp["check_in"]
            check_out = inp["check_out"]

        result = calculate_stay_total(
            check_in=check_in,
            check_out=check_out,
            plans=case["plans"],
            campaigns=case.get("campaigns") or [],
            contract_fee_yen=inp.get("contract_fee_yen"),
        )
        exp = case["expected"]

        self.assertEqual(bool(result.ok), bool(exp["ok"]))
        if not exp["ok"]:
            self.assertEqual(result.error, exp["error"])
            return
        self.assertTrue(result.ok)

        self.assertEqual(result.stay_days, exp["stay_days"])
        self.assertEqual(result.plan_key, exp["plan_key"])
        self.assertEqual(result.used_fallback, exp["used_fallback"])
        self.assertEqual(result.grand_total, exp["grand_total"])
        self.assertEqual(result.warnings, exp["warnings"])

        bd = exp["breakdown"]
        assert result.breakdown is not None
        self.assertEqual(result.breakdown.rent_daily, bd["rent_daily"])
        self.assertEqual(result.breakdown.management_daily, bd["management_daily"])
        self.assertEqual(result.breakdown.utilities_daily, bd["utilities_daily"])
        self.assertEqual(result.breakdown.rent_total, bd["rent_total"])
        self.assertEqual(result.breakdown.management_total, bd["management_total"])
        self.assertEqual(result.breakdown.utilities_total, bd["utilities_total"])
        self.assertEqual(result.breakdown.cleaning_fee, bd["cleaning_fee"])
        self.assertEqual(result.breakdown.contract_fee, bd["contract_fee"])


if __name__ == "__main__":
    unittest.main()
