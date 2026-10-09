import { describe, expect, it } from 'vitest';
import {
  calcStayDays,
  selectPlanByDays,
  calculateRentTotal,
  calculateRentTotalByDays,
  planDisplayLabel,
  type CalculatorPlan,
} from './rentCalculator.ts';

const allPlans: CalculatorPlan[] = [
  {
    plan_code: 's_short',
    plan_name: 'Sショート1ヶ月未満',
    plan_label: 'Sショート',
    duration_text: '1ヶ月未満',
    duration_min_days: 1,
    duration_max_days: 29,
    available: true,
    discounted_daily_rent_yen: 4100,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 8800,
  },
  {
    plan_code: 'short',
    plan_name: 'ショート1ヶ月~3ヶ月',
    plan_label: 'ショート',
    duration_text: '1〜3ヶ月',
    duration_min_days: 30,
    duration_max_days: 89,
    available: true,
    discounted_daily_rent_yen: 2800,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 16500,
  },
  {
    plan_code: 'middle',
    plan_name: 'ミドル3ヶ月～6ヶ月',
    plan_label: 'ミドル',
    duration_text: '3〜6ヶ月',
    duration_min_days: 90,
    duration_max_days: 179,
    available: true,
    discounted_daily_rent_yen: 2650,
    management_fee_daily_yen: 1250,
    cleaning_fee_yen: 27500,
  },
  {
    plan_code: 'long',
    plan_name: 'ロング6ヶ月以上',
    plan_label: 'ロング',
    duration_text: '6ヶ月以上',
    duration_min_days: 180,
    duration_max_days: null,
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
        duration_min_days: 30,
        duration_max_days: 89,
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
        duration_min_days: 30,
        duration_max_days: 89,
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
      contractFeeYen: 5500,
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.stayDays).toBe(30);
      expect(r.selectedPlanCode).toBe('short');
      expect(r.grandTotal).toBe((2800 + 1250) * 30 + 16500 + 5500);
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
      // 手数料未指定 = 算出不能 → 総額から除外
      expect(r.grandTotal).toBe((2800 + 1250) * 14 + 16500);
      expect(r.fallbackNote).toContain('ショート');
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

describe('calculateRentTotalByDays', () => {
  /** 既存テストの「structured yen discount」フィクスチャを流用したキャンペーン */
  const earlyBirdCampaign = {
    campaign_type: '早割',
    target_plan_code: 'all',
    discount_unit: 'yen',
    discount_value: 500,
    period_max_days: 10,
    starts_on: '2026-06-01',
    ends_on: '2026-08-01',
  };

  it('returns the same outcome as calculateRentTotal with onDate=checkIn', () => {
    const viaDates = calculateRentTotal({
      checkIn: '2026-07-01',
      checkOut: '2026-07-30',
      plans: allPlans,
      campaigns: [earlyBirdCampaign],
    });
    const viaDays = calculateRentTotalByDays({
      stayDays: 30,
      plans: allPlans,
      campaigns: [earlyBirdCampaign],
      onDate: '2026-07-01',
    });
    expect(viaDates.ok).toBe(true);
    expect(viaDays).toEqual(viaDates);
  });

  it('skips out-of-period campaigns when onDate is before the window', () => {
    const plan: CalculatorPlan[] = [
      {
        plan_code: 'short',
        plan_name: 'ショート',
        duration_min_days: 30,
        duration_max_days: 89,
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
    const inPeriod = calculateRentTotalByDays({
      stayDays: 30,
      plans: plan,
      campaigns: [earlyBirdCampaign],
      onDate: '2026-07-01',
    });
    const beforePeriod = calculateRentTotalByDays({
      stayDays: 30,
      plans: plan,
      campaigns: [earlyBirdCampaign],
      onDate: '2026-05-20',
    });
    expect(inPeriod.ok && beforePeriod.ok).toBe(true);
    if (inPeriod.ok && beforePeriod.ok) {
      // 期間内: 4000 - floor(500×10/30) のキャンペーン反映
      expect(inPeriod.breakdown.rentDaily).toBe(4000 - Math.floor((500 * 10) / 30));
      // 基準日が期間前: キャンペーン不適用 → effective(=定価ベース)のまま
      expect(beforePeriod.breakdown.rentDaily).toBe(3500);
    }
  });
});

/** UnionMonthly の非対称バンド(BE UNION_DURATION_BANDS ミラー)。semi_short を含む5帯 */
const unionPlans: CalculatorPlan[] = [
  {
    plan_key: 's_short',
    plan_code: 's_short',
    plan_name: 'Sショート（7〜14日）',
    duration_min_days: 7,
    duration_max_days: 14,
    available: true,
    presentation_unit: 'per_day',
    discounted_daily_rent_yen: 6000,
    original_daily_rent_yen: 6000,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 0,
  },
  {
    plan_key: 'semi_short',
    plan_code: 'semi_short',
    plan_name: 'セミショート（15〜29日）',
    duration_min_days: 15,
    duration_max_days: 29,
    available: true,
    presentation_unit: 'per_day',
    discounted_daily_rent_yen: 4500,
    original_daily_rent_yen: 4500,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 0,
  },
  {
    plan_key: 'short',
    plan_code: 'short',
    plan_name: 'ショート（30〜89日）',
    duration_min_days: 30,
    duration_max_days: 89,
    available: true,
    presentation_unit: 'per_month',
    utilities_yen: 9000,
    utilities_included: false,
    discounted_daily_rent_yen: 3000,
    original_daily_rent_yen: 3000,
    management_fee_daily_yen: 500,
    cleaning_fee_yen: 20000,
  },
  {
    plan_key: 'middle',
    plan_code: 'middle',
    plan_name: 'ミドル（90〜209日）',
    duration_min_days: 90,
    duration_max_days: 209,
    available: true,
    presentation_unit: 'per_day',
    discounted_daily_rent_yen: 2600,
    original_daily_rent_yen: 2600,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 40000,
  },
  {
    plan_key: 'long',
    plan_code: 'long',
    plan_name: 'ロング（210〜729日）',
    duration_min_days: 210,
    duration_max_days: 729,
    available: true,
    presentation_unit: 'per_day',
    discounted_daily_rent_yen: 2400,
    original_daily_rent_yen: 2400,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 60000,
  },
];

describe('duration帯データ駆動のプラン選択(乖離1: Union非対称バンド)', () => {
  it('selects middle for a 100-day stay instead of the legacy short misjudgement', () => {
    // レガシー固定バンド(<181 middle)では 100日は short と誤判定される帯
    const r = calculateRentTotalByDays({ stayDays: 100, plans: unionPlans, onDate: '2026-07-01' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.selectedPlan.plan_key).toBe('middle');
      expect(r.usedFallback).toBe(false);
    }
  });

  it('selects semi_short for a 15-day stay and long for a 300-day stay', () => {
    const r15 = calculateRentTotalByDays({ stayDays: 15, plans: unionPlans, onDate: '2026-07-01' });
    expect(r15.ok && r15.selectedPlan.plan_key).toBe('semi_short');

    const r300 = calculateRentTotalByDays({
      stayDays: 300,
      plans: unionPlans,
      onDate: '2026-07-01',
    });
    expect(r300.ok && r300.selectedPlan.plan_key).toBe('long');
  });

  it('resolves semi_short via plan_label wire vocabulary (semi_short誤表示の回帰)', () => {
    // 修正前: PLAN_LABELS が閉集合で normalizePlanCode の plan_name 再導出に落ち、
    // 「セミショート（15日以上-1ヶ月未満）」が s_short に誤分類されていた(-α で発火した
    // 表示バグ)。第1.7段本体は表示の正を BE 解決の plan_label とし再導出を廃止した。
    const r = calculateRentTotalByDays({ stayDays: 20, plans: unionPlans, onDate: '2026-07-01' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.selectedPlan.plan_key).toBe('semi_short');
      expect(r.selectedPlanCode).toBe('semi_short');
      // 表示経路(RentSimulator / filterLogic.planLabel)は planDisplayLabel を使う
      expect(planDisplayLabel(r.selectedPlan)).toContain('セミショート');
    }
  });

  it('falls back to the closest longer band when no band contains the stay', () => {
    // 100日だが middle が unavailable → 210-729 の long で代替(BE select_plan_for_stay 準拠)
    const noMiddle = unionPlans.filter((p) => p.plan_key !== 'middle');
    const r = calculateRentTotalByDays({ stayDays: 100, plans: noMiddle, onDate: '2026-07-01' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.selectedPlan.plan_key).toBe('long');
      expect(r.usedFallback).toBe(true);
      expect(r.fallbackNote).toContain('対応する料金プラン帯がないため');
    }
  });

  it('duration データのないプランのみは計算不能(レガシー文字列バンド経路は削除済み)', () => {
    // BE が duration なしデータを生産不能(本番 0 件)のため推定経路は廃止した(設計 §3.6)。
    // 壊れたデータが混入した場合は明示的な計算不能として返す。
    const noDuration = allPlans.map((p) => ({
      ...p,
      duration_min_days: undefined,
      duration_max_days: undefined,
    }));
    const r = calculateRentTotalByDays({ stayDays: 45, plans: noDuration, onDate: '2026-07-01' });
    expect(r.ok).toBe(false);
  });
});

describe('光熱費の加算(乖離2: utilities_included=false)', () => {
  it('adds utilities per day when not included (per_month → floor division by 30)', () => {
    const r = calculateRentTotalByDays({ stayDays: 60, plans: unionPlans, onDate: '2026-07-01' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      // short(30-89) 選択: 月額9000円 → 日額 floor(9000/30)=300
      expect(r.breakdown.utilitiesDaily).toBe(300);
      expect(r.breakdown.utilitiesTotal).toBe(300 * 60);
      expect(r.grandTotal).toBe((3000 + 500) * 60 + 300 * 60 + 20000);
      expect(r.warnings.some((w) => w.includes('光熱費'))).toBe(true);
    }
  });

  it('adds nothing when utilities are included', () => {
    const included = unionPlans.map((p) =>
      p.plan_key === 'short' ? { ...p, utilities_included: true } : p
    );
    const r = calculateRentTotalByDays({ stayDays: 60, plans: included, onDate: '2026-07-01' });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.breakdown.utilitiesDaily).toBe(0);
      expect(r.breakdown.utilitiesTotal).toBe(0);
    }
  });
});

describe('契約事務手数料(乖離3: contract_fee_yen)', () => {
  it('uses the property contract_fee_yen when provided', () => {
    const r = calculateRentTotalByDays({
      stayDays: 30,
      plans: unionPlans,
      contractFeeYen: 9900,
      onDate: '2026-07-01',
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.breakdown.contractFee).toBe(9900);
    }
  });

  it('treats null/undefined fee as unknown: excluded from total with a warning', () => {
    const withNull = calculateRentTotalByDays({
      stayDays: 30,
      plans: unionPlans,
      contractFeeYen: null,
      onDate: '2026-07-01',
    });
    const without = calculateRentTotalByDays({
      stayDays: 30,
      plans: unionPlans,
      onDate: '2026-07-01',
    });
    for (const r of [withNull, without]) {
      expect(r.ok).toBe(true);
      if (r.ok) {
        expect(r.breakdown.contractFee).toBeNull();
        expect(r.warnings.some((w) => w.includes('契約事務手数料') && w.includes('不明'))).toBe(
          true,
        );
      }
    }
    // unionMonthly short = (3000+500)*30 + 光熱300*30 + 清掃20000。手数料は加算されない
    expect(withNull.ok && withNull.grandTotal).toBe((3000 + 500) * 30 + 300 * 30 + 20000);
  });

  it('threads contract_fee_yen from property properties via computeStayEstimate', async () => {
    const { computeStayEstimate } = await import('./filterLogic.ts');
    const props = {
      id: 1,
      title: 't',
      detail_url: 'u',
      address: 'a',
      layout: '1K',
      area_m2: 20,
      min_daily_rent: 3000,
      min_plan_total: null,
      min_plan_name: null,
      min_walk_minutes: null,
      thumbnail_url: null,
      images: [],
      total_score: 0,
      shortlist_status: 'none',
      access_summary: '',
      feature_summary: '',
      station_summary: '',
      contract_fee_yen: 9900,
      rent_plans: unionPlans,
      campaigns: [],
    } as Parameters<typeof computeStayEstimate>[0];
    const est = computeStayEstimate(props, '2026-07-01', '2026-07-30');
    expect(est.ok).toBe(true);
    // GeoJSON 由来(contract_fee_yen 無し)は算出不能 → 手数料は加算されない
    const { contract_fee_yen: _omit, ...geoProps } = props;
    const estGeo = computeStayEstimate(geoProps as typeof props, '2026-07-01', '2026-07-30');
    expect(est.stayTotalYen).toBe(estGeo.stayTotalYen! + 9900);
  });
});

describe('planDisplayLabel(設計§3.6: plan_label+帯レンジ合成)', () => {
  it('synthesizes range from duration_text (既存表示と同等・承認3)', () => {
    expect(
      planDisplayLabel({
        plan_label: 'セミショート',
        duration_text: '15日以上-1ヶ月未満',
        plan_name: 'セミショート（15日以上-1ヶ月未満）',
      })
    ).toBe('セミショート（15日以上-1ヶ月未満）');
  });

  it('falls back to raw plan_name when plan_label is missing', () => {
    expect(planDisplayLabel({ plan_name: '特殊プラン' })).toBe('特殊プラン');
  });

  it('omits range when duration_text is absent', () => {
    expect(planDisplayLabel({ plan_label: 'ロング', plan_name: 'ロング6ヶ月以上' })).toBe('ロング');
  });
});
