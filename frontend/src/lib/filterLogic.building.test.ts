import { describe, expect, it } from 'vitest';
import {
  applyBuildingFilters,
  flattenMatchedUnits,
} from './filterLogic.ts';
import {
  BuildingFeature,
  BuildingUnit,
  MapFilters,
} from '../types.ts';
import {
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_STATIC_FILTERS,
  STAY_PRICE_UNLIMITED,
} from '../types.ts';
import type { RentPlan } from '../types.ts';

/**
 * 建物単位フィルタ(applyBuildingFilters)の意味論テスト(Phase B2-α〜ε)。
 *
 * B2-ε で旧部屋単位パイプライン(applyMapFilters)は廃止されたため、建物パイプライン
 * 単体で意味論を直接検証する。部屋条件カーネル(価格/間取り/設備等の個別判定)は
 * filterLogic.test.ts(1部屋=1建物フィクスチャ)を参照。
 */

function plan(daily: number): RentPlan {
  return {
    available: true,
    duration_min_days: 30,
    duration_max_days: 89,
    presentation_unit: 'per_day',
    utilities_included: true,
    campaign_applied: false,
    campaign_expired: false,
    discounted_daily_rent_yen: daily,
    original_daily_rent_yen: daily,
    campaign_label: null,
    discounted_total_yen: daily * 30,
    total_period_days: 30,
    management_fee_daily_yen: 0,
    cleaning_fee_yen: 0,
    plan_code: 'monthly',
    plan_name: 'マンスリー',
  } as RentPlan;
}

function unit(id: number, partial: Partial<BuildingUnit> = {}): BuildingUnit {
  return {
    id,
    source_site: 'unionmonthly',
    source_display_name: 'ユニオンマンスリー',
    title: `Room${id}`,
    address: '東京都多摩市永山1-1',
    prefecture_name: '東京都',
    municipality: '多摩市',
    layout: '1K',
    area_m2: 25,
    min_daily_rent: 4800,
    min_plan_total: 144000,
    total_score: 50,
    shortlist_status: 'none',
    is_active: true,
    min_walk_minutes: 5,
    contract_fee_yen: 5500,
    access_summary: ['JR 南多摩駅 徒歩5分'],
    images: [],
    feature_summary: '',
    feature_categories: ['elevator'],
    rent_plans: [plan(4800)],
    campaigns: [],
    ...partial,
  };
}

function bldg(
  id: number,
  units: BuildingUnit[],
  partial: Partial<BuildingFeature['properties']> = {},
  coords: [number, number] = [139.7, 35.6],
): BuildingFeature {
  const activeCnt = units.filter((u) => u.is_active).length;
  const minDaily = units.reduce<number | null>(
    (m, u) => (u.min_daily_rent == null ? m : m == null ? u.min_daily_rent : Math.min(m, u.min_daily_rent)),
    null,
  );
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: coords },
    properties: {
      id,
      kind: 'building',
      name: `Building${id}`,
      address: '東京都多摩市永山1-1',
      prefecture_name: '東京都',
      municipality: '多摩市',
      is_active: activeCnt > 0,
      units_count: units.length,
      active_units_count: activeCnt,
      source_sites: [...new Set(units.map((u) => u.source_site ?? ''))].filter(Boolean),
      building_names: [],
      feature_categories: [],
      min_daily_rent: minDaily,
      max_daily_rent: minDaily,
      min_plan_total: 144000,
      has_campaign: false,
      access_summary: ['JR 南多摩駅 徒歩5分'],
      station_summary: '南多摩',
      thumbnail_url: null,
      ...partial,
      units,
    },
  };
}

const catalogBase: MapFilters = {
  ...DEFAULT_STATIC_FILTERS,
  checkIn: '2026-08-01',
  checkOut: '2026-09-01',
  priceMode: 'catalog',
  maxPrice: CATALOG_PRICE_UNLIMITED,
  sortBy: 'price_asc',
};


const stayFilters = (): MapFilters => ({
  ...DEFAULT_STATIC_FILTERS,
  checkIn: '2026-08-01',
  checkOut: '2026-08-31',
  priceMode: 'stay',
  maxPrice: STAY_PRICE_UNLIMITED,
  sortBy: 'price_asc',
});

function buildingsFixture(): BuildingFeature[] {
  return [
    // 建物1: 2部屋(1K 安め / 2LDK 高め)
    bldg(1, [
      unit(10, { min_daily_rent: 4800, min_plan_total: 144000 }),
      unit(11, {
        layout: '2LDK',
        area_m2: 45,
        min_daily_rent: 7500,
        min_plan_total: 225000,
        title: 'Room11 corner',
        feature_categories: ['elevator', 'separate_bath_toilet'],
      }),
    ]),
    // 建物2: 1部屋・閑静県・部屋 title に固有語
    bldg(
      2,
      [unit(20, { title: 'Room20 静岡', prefecture_name: '静岡県', min_daily_rent: 3000, min_plan_total: 90000, feature_categories: [] })],
      { prefecture_name: '静岡県' },
      [138.3, 34.9],
    ),
    // 建物3: mixed(active + 非 active)
    bldg(3, [
      unit(30, { shortlist_status: 'saved' }),
      unit(31, { is_active: false, shortlist_status: 'hide' }),
    ]),
    // 建物4: all_inactive(掲載終了)
    bldg(4, [unit(40, { is_active: false }), unit(41, { is_active: false })], {
      min_daily_rent: 2000,
      min_plan_total: 60000,
    }),
  ];
}

function matchedIds(result: ReturnType<typeof applyBuildingFilters>): Set<number> {
  return result.matchedRoomIds;
}

describe('applyBuildingFilters — 部屋条件の採用意味論(§6.1)', () => {
  it('catalog 標準フィルタ(active 既定)で条件を満たす部屋を持つ建物のみ採用する', () => {
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildingsFixture() },
      catalogBase,
      null,
    );
    // マッチ部屋: 10/11(建物1)・20(建物2)・30(建物3 の active 部屋)。
    // 31 は非 active、建物4 は all_inactive で全部屋弾かれるため不採用
    expect(matchedIds(next)).toEqual(new Set([10, 11, 20, 30]));
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1, 2, 3]);
  });

  it('価格上限・間取り・面積・設備・徒歩・県・ソースの複合条件を unit 条件として判定する', () => {
    const buildings = buildingsFixture();
    const filters: MapFilters = {
      ...catalogBase,
      maxPrice: 150000,
      layout: '1K',
      areaRange: [20, 30],
      requiredFeatures: ['elevator'],
      maxWalkMinutes: 10,
      prefecture: '東京都',
      sources: ['unionmonthly'],
    };
    const next = applyBuildingFilters({ type: 'FeatureCollection', features: buildings }, filters, null);
    // 10 と 30 のみが複合条件を満たす(11 は 2LDK・20 は静岡県・31 は非 active)
    expect(matchedIds(next)).toEqual(new Set([10, 30]));
  });

  it('stay モード: 計算可能部屋のマッチと除外カウント(部屋数)', () => {
    const buildings = [
      bldg(1, [
        unit(10, { rent_plans: [plan(4800)] }),
        unit(11, { rent_plans: [], min_daily_rent: null, min_plan_total: null }), // 計算不能
      ]),
      bldg(2, [unit(20, { rent_plans: [] , min_daily_rent: null, min_plan_total: null })]), // 全室計算不能
    ];
    const next = applyBuildingFilters({ type: 'FeatureCollection', features: buildings }, stayFilters(), null);
    expect(matchedIds(next)).toEqual(new Set([10]));
    expect(next.excludedUnestimable).toBe(2); // 11, 20 の 2 部屋(建物数でなく部屋数)
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1]); // 建物2 は全室計算不能で不採用
  });

  it('フリーワード(部屋フィールドのみヒット)でマッチ部屋が絞られる', () => {
    const buildings = buildingsFixture();
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, searchQuery: 'Room11' },
      null,
    );
    expect(matchedIds(next)).toEqual(new Set([11]));
  });

  it('フリーワードの建物名 OR 拡大: 建物名ヒットで建物を採用し条件を満たす部屋がマッチする', () => {
    const buildings = buildingsFixture();
    // 建物名 "Building1" にヒット。ワード以外条件は無制限のため全部屋がマッチ対象
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, searchQuery: 'building1' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1]);
    expect(matchedIds(next)).toEqual(new Set([10, 11]));
  });

  it('建物名ヒットでも他条件を満たす部屋が無ければ不採用(§6.1 の一般則を維持)', () => {
    const buildings = buildingsFixture();
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, searchQuery: 'building1', layout: '3LDK' },
      null,
    );
    expect(next.buildings).toEqual([]);
  });

  it('building_names(別名)もワード対象に含む', () => {
    const buildings = [
      bldg(1, [unit(10)], {
        name: '南多摩レジデンス',
        building_names: [{ source_site: 'bratto', name: 'ブラット南多摩' }],
      }),
    ];
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, searchQuery: 'ブラット' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1]);
  });

  it('viewport は建物代表座標で判定する', () => {
    const buildings = buildingsFixture();
    const bounds = { southWest: [35.5, 139.6] as [number, number], northEast: [35.7, 139.8] as [number, number] };
    const filters = { ...catalogBase, areaMode: 'viewport' as const };
    const next = applyBuildingFilters({ type: 'FeatureCollection', features: buildings }, filters, bounds);
    // 建物1(139.7,35.6)・3 も同座標 → 採用。建物2(静岡)は除外
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1, 3]);
  });
});

describe('applyBuildingFilters — listingVisibility(設計 §8 の建物版)', () => {
  it('active(既定): mixed 建物は active 部屋のみマッチ。all_inactive 建物は不採用', () => {
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildingsFixture() },
      { ...catalogBase, listingVisibility: 'active' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1, 2, 3]);
    expect(matchedIds(next).has(31)).toBe(false); // mixed の非 active 部屋は弾かれる
    expect(matchedIds(next).has(30)).toBe(true);
  });

  it('all: 全建物を採用し全部屋(可視 units)がマッチする', () => {
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildingsFixture() },
      { ...catalogBase, listingVisibility: 'all' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([1, 2, 3, 4]);
    expect(matchedIds(next).has(40)).toBe(true);
  });

  it('inactive: all_inactive 建物のみ(mixed の非 active 部屋は出さない・設計 §8)', () => {
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildingsFixture() },
      { ...catalogBase, listingVisibility: 'inactive' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([4]);
    expect(matchedIds(next)).toEqual(new Set([40, 41]));
  });
});

describe('applyBuildingFilters — 建物代表値ソート(計画 §4.2)', () => {
  it('price_asc は建物最安日額順。all_inactive 建物は末尾', () => {
    // 建物代表値(properties 側)でソートされるため bldg 第 3 引数で指定する
    const buildings = [
      bldg(1, [unit(10, { min_daily_rent: 6000 })], { min_plan_total: 180000 }),
      bldg(2, [unit(20, { min_daily_rent: 3000 })], { min_plan_total: 90000 }),
      bldg(3, [unit(30, { is_active: false })], { min_daily_rent: 1000, min_plan_total: 30000 }),
    ];
    // all_inactive 建物を採用させるため listingVisibility: 'all'
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, listingVisibility: 'all' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1, 3]);
  });

  it('stay モードの価格ソートは units の期間総額最安(計画 §4.2 承認)', () => {
    const buildings = [
      bldg(1, [unit(10, { rent_plans: [plan(6000)] })]),
      bldg(2, [unit(20, { rent_plans: [plan(3000)] })]),
    ];
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      stayFilters(),
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1]);
    // units に stay_estimate が付与されている
    const b1units = next.buildings[0].properties.units;
    expect(b1units[0].stay_estimate?.stayTotalYen).not.toBeNull();
  });
});

describe('applyBuildingFilters — 最終編集順ソート(updated_desc)', () => {
  it('建物saved の updated_at が新しい順。未編集(null)は末尾・all_inactive はさらに末尾', () => {
    const buildings = [
      bldg(1, [unit(10)], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
      bldg(2, [unit(20)], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-05T10:00:00Z',
      }),
      bldg(3, [unit(30)]),
      bldg(4, [unit(40, { is_active: false })], { min_daily_rent: 2000 }),
    ];
    // all_inactive 建物を採用させるため listingVisibility: 'all'
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, listingVisibility: 'all', sortBy: 'updated_desc' },
      null,
    );
    // 建物3は未編集でアクティブ内末尾、建物4は all_inactive で最終
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1, 3, 4]);
  });

  it('部屋saved の updated_at も建物キーに合流(建物/部屋の最大値)', () => {
    const buildings = [
      bldg(1, [unit(10)], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
      bldg(2, [
        unit(20, {
          shortlist_status: 'saved',
          shortlist_updated_at: '2026-10-08T10:00:00Z',
        }),
      ], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
    ];
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, sortBy: 'updated_desc' },
      null,
    );
    // 建物2は部屋saved(10-08)が建物saved(10-01)より新しいため先頭
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1]);
  });

  it('hide 編集は最終編集時刻に含めない(saved 行のみ合流)', () => {
    const buildings = [
      bldg(1, [
        unit(10, {
          shortlist_status: 'hide',
          shortlist_updated_at: '2026-10-09T10:00:00Z',
        }),
      ], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
      bldg(2, [
        unit(20, {
          shortlist_status: 'saved',
          shortlist_updated_at: '2026-10-05T10:00:00Z',
        }),
      ]),
    ];
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, sortBy: 'updated_desc' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1]);
  });

  it('同時刻はスコア降順のタイブレーク', () => {
    const buildings = [
      bldg(1, [unit(10, { total_score: 30 })], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
      bldg(2, [unit(20, { total_score: 80 })], {
        shortlist_status: 'saved',
        shortlist_updated_at: '2026-10-01T10:00:00Z',
      }),
    ];
    const next = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, sortBy: 'updated_desc' },
      null,
    );
    expect(next.buildings.map((b) => b.properties.id)).toEqual([2, 1]);
  });

  it('部屋平面リスト(flattenMatchedUnits)も saved 部屋の最終編集順・未編集は末尾', () => {
    const buildings = [
      bldg(1, [
        unit(10, {
          shortlist_status: 'saved',
          shortlist_updated_at: '2026-10-01T10:00:00Z',
        }),
        unit(11, {
          shortlist_status: 'saved',
          shortlist_updated_at: '2026-10-05T10:00:00Z',
        }),
        unit(12, { total_score: 90 }),
      ]),
    ];
    const result = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, sortBy: 'updated_desc' },
      null,
    );
    const flat = flattenMatchedUnits(result.buildings, result.matchedRoomIds, 'updated_desc', {
      ...catalogBase,
      sortBy: 'updated_desc',
    });
    expect(flat.map((f) => f.properties.id)).toEqual([11, 10, 12]);
  });
});

describe('flattenMatchedUnits(B2-α の UI 互換出力)', () => {
  it('マッチ部屋のみを平面化しソート済みで返す(採用建物の全 units ではない)', () => {
    const buildings = buildingsFixture();
    const result = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, layout: '1K' },
      null,
    );
    const flat = flattenMatchedUnits(result.buildings, result.matchedRoomIds, 'price_asc', {
      ...catalogBase,
      layout: '1K',
    });
    // 10(総額144k) / 20(総額90k) / 30(総額144k) の price_asc。31 は mixed の非 active、
    // 40/41 は all_inactive 建物のため listingVisibility 既定(active)で不採用
    expect(flat.map((f) => f.properties.id)).toEqual([20, 10, 30]);
    expect(flat[0].properties.layout).toBe('1K');
  });
});

describe('status フィルタの建物モード意味論(建物ショートリスト承認 U1)', () => {
  it("saved = 建物saved OR 部屋saved≥1(建物saved のみの建物も採用)", () => {
    const buildings = [
      bldg(1, [unit(10)], { shortlist_status: 'saved' }), // 建物saved のみ
      bldg(2, [unit(20, { shortlist_status: 'saved' })]), // 部屋saved のみ
      bldg(3, [unit(30)]), // どちらでもない
    ];
    const result = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, status: 'saved' },
      null,
    );
    expect(result.buildings.map((b) => b.properties.id)).toEqual([1, 2]);
  });

  it('unsaved = 建物saved 無し AND 部屋saved 0(どちらかでも saved なら不採用)', () => {
    const buildings = [
      bldg(1, [unit(10)], { shortlist_status: 'saved' }),
      bldg(2, [unit(20, { shortlist_status: 'saved' })]),
      bldg(3, [unit(30)]),
      bldg(4, [unit(40, { shortlist_status: 'hide' })]), // saved 以外の状態は unsaved 側
    ];
    const result = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, status: 'unsaved' },
      null,
    );
    expect(result.buildings.map((b) => b.properties.id)).toEqual([3, 4]);
  });

  it('saved フィルタ時は建物の条件一致部屋全部屋がマッチ扱い(saved 部屋に限定しない)', () => {
    const buildings = [
      bldg(1, [unit(10), unit(11)], { shortlist_status: 'saved' }),
    ];
    const result = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, status: 'saved' },
      null,
    );
    expect(result.buildings).toHaveLength(1);
    expect([...result.matchedRoomIds].sort()).toEqual([10, 11]);
  });

  it('hide/reject は部屋単位のまま(該当部屋を持つ建物のみ採用)', () => {
    const buildings = [
      bldg(1, [unit(10, { shortlist_status: 'hide' })]),
      bldg(2, [unit(20)]),
    ];
    const hide = applyBuildingFilters(
      { type: 'FeatureCollection', features: buildings },
      { ...catalogBase, status: 'hide' },
      null,
    );
    expect(hide.buildings.map((b) => b.properties.id)).toEqual([1]);
    expect([...hide.matchedRoomIds]).toEqual([10]);

    const reject = applyBuildingFilters(
      {
        type: 'FeatureCollection',
        features: [bldg(3, [unit(30, { shortlist_status: 'reject' })]), bldg(4, [unit(40)])],
      },
      { ...catalogBase, status: 'reject' },
      null,
    );
    expect(reject.buildings.map((b) => b.properties.id)).toEqual([3]);
  });
});
