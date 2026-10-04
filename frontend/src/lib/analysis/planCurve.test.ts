import { describe, expect, it } from 'vitest';
import {
  buildPlanCurve,
  filterBrokenPlans,
  planDiscounts,
} from './planCurve.ts';
import { CONTRACT_FEE_YEN, type CalculatorPlan } from '../rentCalculator.ts';

/** 30日境界をまたぐ2プラン(s_short は日額5000円 / short は月額90000円=日額3000円) */
const twoPlans: CalculatorPlan[] = [
  {
    plan_code: 's_short',
    plan_name: 'Sショート（1ヶ月未満）',
    available: true,
    discounted_daily_rent_yen: 5000,
    original_daily_rent_yen: 6000,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 15000,
  },
  {
    plan_code: 'short',
    plan_name: 'ショート（1〜3ヶ月）',
    available: true,
    discounted_daily_rent_yen: null,
    original_daily_rent_yen: 3000,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 30000,
  },
];

describe('buildPlanCurve', () => {
  it('shows per-day step down at the 30-day plan boundary', () => {
    const result = buildPlanCurve(twoPlans);
    const row29 = result.rows.find((r) => r.days === 29)!;
    const row30 = result.rows.find((r) => r.days === 30)!;

    expect(row29.planCode).toBe('s_short');
    expect(row30.planCode).toBe('short');

    // 総額 = 賃料×日数 + 清掃費 + 契約事務手数料
    expect(row29.total).toBe(5000 * 29 + 15000 + CONTRACT_FEE_YEN);
    expect(row30.total).toBe(3000 * 30 + 30000 + CONTRACT_FEE_YEN);

    // 30日境界で実質1日単価が段差的に下がる(165500/29=5707 → 125500/30=4183)
    expect(row29.perDay).toBe(5707);
    expect(row30.perDay).toBe(4183);
    expect(row30.perDay).toBeLessThan(row29.perDay);

    // 適用されなかったプランの系列は null
    expect(row29.values['short']).toBeNull();
    expect(row30.values['s_short']).toBeNull();
  });

  it('picks the cheapest row on or after the boundary', () => {
    const result = buildPlanCurve(twoPlans);
    expect(result.cheapest).not.toBeNull();
    // 清掃費+事務手数料の固定費が希薄化する長期側が最安
    expect(result.cheapest!.days).toBeGreaterThanOrEqual(30);
    expect(result.cheapest!.planCode).toBe('short');
    const minPerDay = Math.min(...result.rows.map((r) => r.perDay));
    expect(result.cheapest!.perDay).toBe(minPerDay);
  });

  it('includes plan band boundary days even beyond the 7-day stride', () => {
    const result = buildPlanCurve(twoPlans);
    // 91日(s_short→short→middle 境界)は7刻み(91,98,...)に含まれる
    expect(result.rows.some((r) => r.days === 91)).toBe(true);
    // 181日(middle→long 境界)は7刻みに含まれないため境界追加で補われる
    expect(result.rows.some((r) => r.days === 181)).toBe(true);
  });

  it('excludes broken plans with non-positive rent', () => {
    const broken: CalculatorPlan[] = [
      { ...twoPlans[0], discounted_daily_rent_yen: 0 },
      { ...twoPlans[1], discounted_daily_rent_yen: -500, original_daily_rent_yen: -500 },
    ];
    const result = buildPlanCurve(broken);
    expect(result.excludedPlans).toEqual(['s_short', 'short']);
    // 計算可能なプランが残らないためカーブは空
    expect(result.rows).toEqual([]);
    expect(result.cheapest).toBeNull();
  });

  it('still builds the curve from the remaining plans when one is broken', () => {
    const mixed: CalculatorPlan[] = [
      { ...twoPlans[0], discounted_daily_rent_yen: 0 },
      twoPlans[1],
    ];
    const result = buildPlanCurve(mixed);
    expect(result.excludedPlans).toEqual(['s_short']);
    expect(result.rows.length).toBeGreaterThan(0);
    for (const row of result.rows) {
      expect(row.planCode).toBe('short');
      expect(row.values['s_short']).toBeUndefined();
    }
  });
});

describe('filterBrokenPlans', () => {
  it('splits usable plans and excluded codes in input order', () => {
    const { usable, excluded } = filterBrokenPlans(twoPlans);
    expect(usable.map((p) => p.plan_code)).toEqual(['s_short', 'short']);
    expect(excluded).toEqual([]);
  });
});

describe('planDiscounts', () => {
  it('computes discount percentage rounded to 1 decimal', () => {
    const plans: CalculatorPlan[] = [
      {
        plan_code: 'short',
        plan_name: 'ショート',
        available: true,
        discounted_daily_rent_yen: 3500,
        original_daily_rent_yen: 5000,
        management_fee_daily_yen: 0,
        cleaning_fee_yen: 0,
      },
      {
        plan_code: 'middle',
        plan_name: 'ミドル',
        available: true,
        discounted_daily_rent_yen: 2900,
        original_daily_rent_yen: 3000,
        management_fee_daily_yen: 0,
        cleaning_fee_yen: 0,
      },
      {
        plan_code: 'long',
        plan_name: 'ロング',
        available: true,
        discounted_daily_rent_yen: null,
        original_daily_rent_yen: 4000,
        management_fee_daily_yen: 0,
        cleaning_fee_yen: 0,
      },
    ];
    const info = planDiscounts(plans);
    expect(info[0].discountPct).toBe(30);
    expect(info[1].discountPct).toBe(3.3);
    // 定価のみで現在値が不明なプランは割引率 null
    expect(info[2].discountPct).toBeNull();
    expect(info[0].currentDaily).toBe(3500);
    expect(info[0].originalDaily).toBe(5000);
  });
});
