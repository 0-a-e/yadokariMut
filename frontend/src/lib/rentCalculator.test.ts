import { describe, expect, it } from 'vitest';
import {
  calcStayDays,
  preferredPlanCodeForDays,
  selectPlanByDays,
  calculateRentTotal,
  defaultDateRange,
  CONTRACT_FEE_YEN,
  type CalculatorPlan,
} from './rentCalculator';

const allPlans: CalculatorPlan[] = [
  {
    plan_code: 's_short',
    plan_name: 'Sショート1ヶ月未満',
    available: true,
    discounted_daily_rent_yen: 4100,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 8800,
  },
  {
    plan_code: 'short',
    plan_name: 'ショート1ヶ月~3ヶ月',
    available: true,
    discounted_daily_rent_yen: 2800,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 16500,
  },
  {
    plan_code: 'middle',
    plan_name: 'ミドル3ヶ月～6ヶ月',
    available: true,
    discounted_daily_rent_yen: 2650,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 27500,
  },
  {
    plan_code: 'long',
    plan_name: 'ロング6ヶ月以上',
    available: true,
    discounted_daily_rent_yen: 2500,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 38500,
  },
];

describe('calcStayDays', () => {
  it('counts inclusive days', () => {
    expect(calcStayDays('2026-05-01', '2026-05-01')).toBe(1);
    expect(calcStayDays('2026-05-01', '2026-05-07')).toBe(7);
    expect(calcStayDays('2026-05-01', '2026-05-30')).toBe(30);
  });

  it('returns null for invalid ranges', () => {
    expect(calcStayDays('2026-05-07', '2026-05-01')).toBeNull();
    expect(calcStayDays('bad', '2026-05-01')).toBeNull();
  });
});

describe('preferredPlanCodeForDays', () => {
  it('maps stay length to BraTTo plan bands', () => {
    expect(preferredPlanCodeForDays(1)).toBe('s_short');
    expect(preferredPlanCodeForDays(29)).toBe('s_short');
    expect(preferredPlanCodeForDays(30)).toBe('short');
    expect(preferredPlanCodeForDays(90)).toBe('short');
    expect(preferredPlanCodeForDays(91)).toBe('middle');
    expect(preferredPlanCodeForDays(180)).toBe('middle');
    expect(preferredPlanCodeForDays(181)).toBe('long');
  });
});

describe('selectPlanByDays', () => {
  it('selects preferred band when available', () => {
    const s = selectPlanByDays(allPlans, 14)!;
    expect(s.selectedCode).toBe('s_short');
    expect(s.usedFallback).toBe(false);

    const s45 = selectPlanByDays(allPlans, 45)!;
    expect(s45.selectedCode).toBe('short');
  });

  it('falls back to longer/shorter bands', () => {
    const noSShort = allPlans.filter((p) => p.plan_code !== 's_short');
    const s = selectPlanByDays(noSShort, 14)!;
    expect(s.preferred).toBe('s_short');
    expect(s.selectedCode).toBe('short');
    expect(s.usedFallback).toBe(true);
  });
});

describe('calculateRentTotal', () => {
  it('uses effective daily when campaign is expired', () => {
    const expiredPlan: CalculatorPlan[] = [
      {
        plan_code: 'short',
        plan_name: 'ショート',
        available: true,
        original_daily_rent_yen: 4600,
        discounted_daily_rent_yen: 3600,
        effective_daily_rent_yen: 4600,
        campaign_applied: false,
        campaign_expired: true,
        expired_campaign_label: '早割キャンペーン',
        management_fee_daily_yen: 1000,
        cleaning_fee_yen: 10000,
      },
    ];
    const r = calculateRentTotal({
      checkIn: '2026-07-01',
      checkOut: '2026-07-30',
      plans: expiredPlan,
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.breakdown.rentDaily).toBe(4600);
      expect(r.warnings.some((w) => w.includes('期限切れ'))).toBe(true);
    }
  });

  it('applies structured yen discount with period_max', () => {
    const plan: CalculatorPlan[] = [
      {
        plan_code: 'short',
        plan_name: 'ショート',
        available: true,
        original_daily_rent_yen: 4000,
        discounted_daily_rent_yen: 3500,
        effective_daily_rent_yen: 3500,
        campaign_applied: true,
        effective_campaign_label: '早割キャンペーン',
        management_fee_daily_yen: 0,
        cleaning_fee_yen: 0,
      },
    ];
    const r = calculateRentTotal({
      checkIn: '2026-07-01',
      checkOut: '2026-07-30',
      plans: plan,
      campaigns: [
        {
          campaign_type: '早割',
          is_active: true,
          target_plan_code: 'all',
          discount_unit: 'yen',
          discount_value: 500,
          period_max_days: 10,
          starts_on: '2026-06-01',
          ends_on: '2026-08-01',
        },
      ],
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      // total_off = 500*10 = 5000 → daily off = 5000/30 = 166 → rentDaily = 4000-166 = 3834
      expect(r.breakdown.rentDaily).toBe(4000 - Math.floor((500 * 10) / 30));
    }
  });

  it('computes full total for 30-day short band', () => {
    const r = calculateRentTotal({
      checkIn: '2026-05-01',
      checkOut: '2026-05-30',
      plans: allPlans,
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.stayDays).toBe(30);
      expect(r.selectedPlanCode).toBe('short');
      expect(r.grandTotal).toBe((2800 + 1250) * 30 + 16500 + CONTRACT_FEE_YEN);
      expect(r.breakdown.rentTotal).toBe(2800 * 30);
      expect(r.breakdown.managementTotal).toBe(1250 * 30);
      expect(r.breakdown.cleaningFee).toBe(16500);
      expect(r.breakdown.contractFee).toBe(5500);
    }
  });

  it('keeps stay days when falling back from missing s_short', () => {
    const noSShort = allPlans.filter((p) => p.plan_code !== 's_short');
    const r = calculateRentTotal({
      checkIn: '2026-05-01',
      checkOut: '2026-05-14',
      plans: noSShort,
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.stayDays).toBe(14);
      expect(r.usedFallback).toBe(true);
      expect(r.selectedPlanCode).toBe('short');
      expect(r.grandTotal).toBe((2800 + 1250) * 14 + 16500 + CONTRACT_FEE_YEN);
      expect(r.fallbackNote).toContain('Sショート');
    }
  });

  it('validates dates and plans', () => {
    expect(calculateRentTotal({ checkIn: '', checkOut: '', plans: allPlans }).ok).toBe(false);
    expect(
      calculateRentTotal({
        checkIn: '2026-05-10',
        checkOut: '2026-05-01',
        plans: allPlans,
      }).ok,
    ).toBe(false);
    expect(
      calculateRentTotal({
        checkIn: '2026-05-01',
        checkOut: '2026-05-10',
        plans: [],
      }).ok,
    ).toBe(false);
  });
});

describe('defaultDateRange', () => {
  it('uses next month start through the following month start', () => {
    const r = defaultDateRange(new Date(2026, 6, 20)); // 2026-07-20
    expect(r.checkIn).toBe('2026-08-01');
    expect(r.checkOut).toBe('2026-09-01');
  });

  it('rolls over the year in December', () => {
    const r = defaultDateRange(new Date(2026, 11, 15)); // 2026-12-15
    expect(r.checkIn).toBe('2027-01-01');
    expect(r.checkOut).toBe('2027-02-01');
  });
});
