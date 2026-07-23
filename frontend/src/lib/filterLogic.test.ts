import { describe, expect, it } from 'vitest';
import {
  applyMapFilters,
  mergeMapFilters,
  monthlyTotalYen,
  createDefaultMapFilters,
  computeStayEstimate,
} from './filterLogic';
import {
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_MAP_FILTERS,
  MapFilters,
  PropertyFeature,
  PropertyGeoJSON,
  STAY_PRICE_UNLIMITED,
} from '../types';
import type { RentPlan } from '../types';

function plan(partial: Partial<RentPlan> & { plan_code: string; plan_name: string }): RentPlan {
  return {
    available: true,
    discounted_daily_rent_yen: 3000,
    original_daily_rent_yen: 3000,
    campaign_label: null,
    discounted_total_yen: 90000,
    total_period_days: 30,
    management_fee_daily_yen: 1000,
    cleaning_fee_yen: 10000,
    ...partial,
  };
}

function feat(
  partial: Partial<PropertyFeature['properties']> & { id: number },
  coords: [number, number] = [139.7, 35.6],
): PropertyFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: coords },
    properties: {
      room_id: String(partial.id),
      title: partial.title ?? `P${partial.id}`,
      detail_url: '',
      address: partial.address ?? '東京都',
      prefecture_name: partial.prefecture_name ?? '東京都',
      layout: partial.layout ?? '1K',
      area_m2: partial.area_m2 ?? 20,
      min_daily_rent: partial.min_daily_rent ?? 3000,
      min_plan_total: partial.min_plan_total ?? 90000,
      min_plan_name: null,
      min_walk_minutes: partial.min_walk_minutes ?? 5,
      thumbnail_url: null,
      images: [],
      total_score: partial.total_score ?? 50,
      shortlist_status: partial.shortlist_status ?? 'none',
      access_summary: '',
      feature_summary: partial.feature_summary ?? '',
      station_summary: '',
      rent_plans: partial.rent_plans ?? [],
      ...partial,
    },
  };
}

const catalogBase: MapFilters = {
  ...DEFAULT_MAP_FILTERS,
  priceMode: 'catalog',
  maxPrice: CATALOG_PRICE_UNLIMITED,
  sortBy: 'score',
};

const data: PropertyGeoJSON = {
  type: 'FeatureCollection',
  features: [
    feat({
      id: 1,
      layout: '1K',
      min_plan_total: 80000,
      min_walk_minutes: 5,
      total_score: 90,
      feature_summary: 'オートロック, 洗濯機',
    }),
    feat({
      id: 2,
      layout: '1R',
      min_plan_total: 150000,
      min_walk_minutes: 15,
      total_score: 40,
      prefecture_name: '大阪府',
      feature_summary: 'エレベーター',
    }),
    feat({
      id: 3,
      layout: '1K+ロフト',
      min_plan_total: 100000,
      min_walk_minutes: 8,
      total_score: 70,
      shortlist_status: 'saved',
    }),
    feat({
      id: 4,
      layout: '1DK',
      min_plan_total: 120000,
      min_walk_minutes: 3,
      total_score: 60,
      shortlist_status: 'hide',
    }),
  ],
};

describe('applyMapFilters (catalog)', () => {
  it('filters by max price', () => {
    const r = applyMapFilters(data, { ...catalogBase, maxPrice: 100000 }, null);
    expect(r.features.map((f) => f.properties.id).sort()).toEqual([1, 3]);
  });

  it('filters by layout includes', () => {
    const r = applyMapFilters(data, { ...catalogBase, layout: '1K' }, null);
    expect(r.features.map((f) => f.properties.id).sort()).toEqual([1, 3]);
  });

  it('filters by walk minutes', () => {
    const r = applyMapFilters(data, { ...catalogBase, maxWalkMinutes: 8 }, null);
    expect(r.features.every((f) => (f.properties.min_walk_minutes ?? 99) <= 8)).toBe(true);
    expect(r.features.map((f) => f.properties.id)).not.toContain(2);
  });

  it('filters by min score', () => {
    const r = applyMapFilters(data, { ...catalogBase, minScore: 70 }, null);
    expect(r.features.map((f) => f.properties.id).sort()).toEqual([1, 3]);
  });

  it('filters by prefecture', () => {
    const r = applyMapFilters(data, { ...catalogBase, prefecture: '大阪府' }, null);
    expect(r.features.map((f) => f.properties.id)).toEqual([2]);
  });

  it('filters by required features AND', () => {
    const r = applyMapFilters(
      data,
      { ...catalogBase, requiredFeatures: ['オートロック', '洗濯機'] },
      null,
    );
    expect(r.features.map((f) => f.properties.id)).toEqual([1]);
  });

  it('filters shortlist hide', () => {
    const r = applyMapFilters(data, { ...catalogBase, status: 'hide' }, null);
    expect(r.features.map((f) => f.properties.id)).toEqual([4]);
  });

  it('sorts by price ascending', () => {
    const r = applyMapFilters(data, { ...catalogBase, sortBy: 'price_asc' }, null);
    const prices = r.features.map((f) => monthlyTotalYen(f.properties));
    expect(prices).toEqual([...prices].sort((a, b) => a - b));
  });
});

describe('applyMapFilters (stay)', () => {
  const stayPlansCheap: RentPlan[] = [
    plan({
      plan_code: 'short',
      plan_name: 'ショート',
      discounted_daily_rent_yen: 2000,
      original_daily_rent_yen: 2000,
      management_fee_daily_yen: 0,
      cleaning_fee_yen: 0,
    }),
  ];
  const stayPlansExpensive: RentPlan[] = [
    plan({
      plan_code: 'short',
      plan_name: 'ショート',
      discounted_daily_rent_yen: 8000,
      original_daily_rent_yen: 8000,
      management_fee_daily_yen: 0,
      cleaning_fee_yen: 0,
    }),
  ];

  const stayData: PropertyGeoJSON = {
    type: 'FeatureCollection',
    features: [
      feat({ id: 10, title: 'cheap', rent_plans: stayPlansCheap, total_score: 50 }),
      feat({ id: 11, title: 'expensive', rent_plans: stayPlansExpensive, total_score: 90 }),
      feat({ id: 12, title: 'no plans', rent_plans: [], total_score: 99 }),
    ],
  };

  const stayFilters: MapFilters = {
    ...DEFAULT_MAP_FILTERS,
    priceMode: 'stay',
    checkIn: '2026-08-01',
    checkOut: '2026-08-30', // 30 days → short
    maxPrice: STAY_PRICE_UNLIMITED,
    sortBy: 'price_asc',
  };

  it('excludes unestimable and reports count', () => {
    const r = applyMapFilters(stayData, stayFilters, null);
    expect(r.excludedUnestimable).toBe(1);
    expect(r.features.map((f) => f.properties.id).sort()).toEqual([10, 11]);
  });

  it('sorts by stay total ascending', () => {
    const r = applyMapFilters(stayData, stayFilters, null);
    expect(r.features.map((f) => f.properties.id)).toEqual([10, 11]);
    const totals = r.features.map((f) => f.properties.stay_estimate?.stayTotalYen);
    expect(totals[0]!).toBeLessThan(totals[1]!);
  });

  it('filters by stay total maxPrice', () => {
    // 30d * 2000 + 5500 = 65500 for cheap; expensive much higher
    const r = applyMapFilters(
      stayData,
      { ...stayFilters, maxPrice: 100_000 },
      null,
    );
    expect(r.features.map((f) => f.properties.id)).toEqual([10]);
  });

  it('uses original daily when campaign expired on estimate', () => {
    const props = feat({
      id: 99,
      rent_plans: [
        plan({
          plan_code: 'short',
          plan_name: 'ショート',
          original_daily_rent_yen: 4600,
          discounted_daily_rent_yen: 3600,
          effective_daily_rent_yen: 4600,
          campaign_applied: false,
          campaign_expired: true,
          expired_campaign_label: '早割キャンペーン',
          management_fee_daily_yen: 0,
          cleaning_fee_yen: 0,
        }),
      ],
    }).properties;
    const est = computeStayEstimate(props, '2026-08-01', '2026-08-30');
    expect(est.ok).toBe(true);
    expect(est.rentDailyYen).toBe(4600);
  });
});

describe('mergeMapFilters', () => {
  it('partial merge keeps other fields', () => {
    const next = mergeMapFilters(catalogBase, { maxPrice: 120000, layout: '1K' });
    expect(next.maxPrice).toBe(120000);
    expect(next.layout).toBe('1K');
    expect(next.areaRange).toEqual(catalogBase.areaRange);
  });

  it('reset restores stay defaults then applies patch', () => {
    const dirty = { ...catalogBase, maxPrice: 100000, layout: '1R' };
    const next = mergeMapFilters(dirty, { reset: true, layout: '1K' });
    expect(next.priceMode).toBe('stay');
    expect(next.maxPrice).toBe(STAY_PRICE_UNLIMITED);
    expect(next.layout).toBe('1K');
  });

  it('switching priceMode resets maxPrice sentinel', () => {
    const stay = createDefaultMapFilters();
    const toCatalog = mergeMapFilters(stay, { priceMode: 'catalog' });
    expect(toCatalog.maxPrice).toBe(CATALOG_PRICE_UNLIMITED);
    const toStay = mergeMapFilters(toCatalog, { priceMode: 'stay' });
    expect(toStay.maxPrice).toBe(STAY_PRICE_UNLIMITED);
  });
});
