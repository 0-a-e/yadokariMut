/**
 * BE/FE 賃料計算エンジン parity テスト。
 *
 * contracts/stay_calc_cases.json の共有ケースを BE (domain/pricing.calculate_stay_total,
 * tests/test_pricing_parity.py) と同一の入力・期待値で消費し、両エンジンの
 * 数値・プラン選択・警告文言の一致を保証する。期待値の正本は JSON 側にあり、
 * 本テストは JSON をそのままアサートするだけ(変換ロジック無し)。
 */
import { describe, expect, it } from 'vitest';
import parityData from '../../../contracts/stay_calc_cases.json';
import {
  calculateRentTotal,
  calculateRentTotalByDays,
  type CalcOutcome,
  type CalculatorCampaign,
  type CalculatorPlan,
} from './rentCalculator.ts';

interface ParityExpectedOk {
  ok: true;
  stay_days: number;
  plan_key: string;
  used_fallback: boolean;
  breakdown: {
    rent_daily: number;
    management_daily: number;
    utilities_daily: number;
    rent_total: number;
    management_total: number;
    utilities_total: number;
    cleaning_fee: number;
    contract_fee: number | null;
  };
  grand_total: number;
  warnings: string[];
}

interface ParityCase {
  name: string;
  entry: 'dates' | 'days';
  input: {
    check_in?: string;
    check_out?: string;
    stay_days?: number;
    on_date?: string;
    contract_fee_yen?: number | null;
  };
  plans: CalculatorPlan[];
  campaigns?: CalculatorCampaign[];
  expected: ParityExpectedOk | { ok: false; error: string };
}

const cases = parityData.cases as ParityCase[];

function runCase(c: ParityCase): CalcOutcome {
  const contractFeeYen = c.input.contract_fee_yen ?? null;
  if (c.entry === 'days') {
    return calculateRentTotalByDays({
      stayDays: c.input.stay_days!,
      plans: c.plans,
      campaigns: c.campaigns ?? [],
      contractFeeYen,
      onDate: c.input.on_date!,
    });
  }
  return calculateRentTotal({
    checkIn: c.input.check_in!,
    checkOut: c.input.check_out!,
    plans: c.plans,
    campaigns: c.campaigns ?? [],
    contractFeeYen,
  });
}

describe('賃料計算エンジン parity (contracts/stay_calc_cases.json)', () => {
  it('共有ケースがロードできる', () => {
    expect(cases.length).toBeGreaterThan(10);
  });

  for (const c of cases) {
    it(c.name, () => {
      const outcome = runCase(c);
      const exp = c.expected;

      if (!exp.ok) {
        expect(outcome.ok).toBe(false);
        if (!outcome.ok) expect(outcome.error).toBe(exp.error);
        return;
      }
      if (!outcome.ok) throw new Error(`ok を期待したが失敗: ${outcome.error}`);

      expect(outcome.stayDays).toBe(exp.stay_days);
      // BE plan_key との照合は wire の plan_code 生値で(正規化表示コードではない)
      expect(outcome.selectedPlan.plan_code).toBe(exp.plan_key);
      expect(outcome.usedFallback).toBe(exp.used_fallback);
      expect(outcome.grandTotal).toBe(exp.grand_total);
      expect(outcome.warnings).toEqual(exp.warnings);
      expect(outcome.breakdown).toEqual({
        rentDaily: exp.breakdown.rent_daily,
        managementDaily: exp.breakdown.management_daily,
        utilitiesDaily: exp.breakdown.utilities_daily,
        rentTotal: exp.breakdown.rent_total,
        managementTotal: exp.breakdown.management_total,
        utilitiesTotal: exp.breakdown.utilities_total,
        cleaningFee: exp.breakdown.cleaning_fee,
        contractFee: exp.breakdown.contract_fee,
      });
    });
  }
});
