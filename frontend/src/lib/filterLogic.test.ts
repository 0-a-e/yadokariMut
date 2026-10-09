import { describe, expect, it } from 'vitest';
import {
  applyBuildingFilters,
  computeStayEstimate,
  createDefaultMapFilters,
  flattenMatchedUnits,
  isListed,
  mergeMapFilters,
  monthlyTotalYen,
  pointInPolygon,
} from './filterLogic.ts';
import { defaultDateRange } from './stayDates.ts';
import {
  BoundsData,
  BuildingFeature,
  BuildingUnit,
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_STATIC_FILTERS,
  MapFilters,
  STAY_PRICE_UNLIMITED,
} from '../types.ts';
import type { RentPlan } from '../types.ts';

/**
 * 部屋条件カーネル(matchesMapFilters)の意味論テスト。
 *
 * B2-ε で旧部屋単位パイプライン(applyMapFilters)は廃止されたため、本番経路である
 * applyBuildingFilters(建物パイプライン)経由で検証する。フィクスチャは「1部屋=1建物」
 * で建物代表座標に部屋座標を使うため、建物採用 = 部屋条件通過として直接
 * assertion できる(複数部屋の建物オーケストレーション意味論は
 * filterLogic.building.test.ts を参照)。
 */

/**
 * 型レベル契約: MapFilters の全キーを列挙し、過不足がないことをコンパイル時に担保する。
 * (satisfies で「一覧に無いキー」を、Exclude で「一覧から漏れたキー」を検知)
 */
const ALL_FILTER_KEYS = [
  'maxPrice',
  'areaRange',
  'layout',
  'status',
  'listingVisibility',
  'searchQuery',
  'areaMode',
  'drawnPolygon',
  'maxWalkMinutes',
  'minScore',
  'prefecture',
  'requiredFeatures',
  'sources',
  'sortBy',
  'priceMode',
  'checkIn',
  'checkOut',
] as const satisfies readonly (keyof MapFilters)[];
type _MissingKeys = Exclude<keyof MapFilters, (typeof ALL_FILTER_KEYS)[number]> extends never
  ? true
  : never;
// キー漏れがあればコンパイルエラーになるガード
const _allKeysCovered: _MissingKeys = true;

function plan(partial: Partial<RentPlan> & { plan_code: string; plan_name: string }): RentPlan {
  return {
    available: true,
    // データ駆動プラン選択の前提: 帯データ(無い場合は partial 側で上書き)
    duration_min_days: 30,
    duration_max_days: 89,
    presentation_unit: 'per_day',
    utilities_included: true,
    campaign_applied: false,
    campaign_expired: false,
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

function unit(id: number, partial: Partial<BuildingUnit> = {}): BuildingUnit {
  return {
    id,
    source_site: 'unionmonthly',
    source_display_name: 'ユニオンマンスリー',
    title: `P${id}`,
    address: '東京都',
    prefecture_name: '東京都',
    municipality: '渋谷区',
    layout: '1K',
    area_m2: 20,
    min_daily_rent: 3000,
    min_plan_total: 90000,
    min_plan_name: null,
    min_walk_minutes: 5,
    thumbnail_url: null,
    total_score: 50,
    shortlist_status: 'none',
    is_active: true,
    access_summary: ['JR 渋谷駅 徒歩5分'],
    images: [],
    feature_summary: '',
    feature_categories: [],
    rent_plans: [],
    campaigns: [],
    ...partial,
  };
}

/** 部屋条件カーネル用フィクスチャ: 1部屋を 1建物で包み、建物代表座標を明示座標にする */
function wrapBuilding(u: BuildingUnit, coords: [number, number] = [139.7, 35.6]): BuildingFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: coords },
    properties: {
      id: u.id,
      kind: 'building',
      name: `B${u.id}`,
      address: u.address ?? null,
      prefecture_name: u.prefecture_name ?? null,
      municipality: u.municipality ?? null,
      is_active: u.is_active,
      units_count: 1,
      active_units_count: u.is_active ? 1 : 0,
      source_sites: u.source_site ? [u.source_site] : [],
      building_names: [],
      feature_categories: [],
      min_daily_rent: u.min_daily_rent ?? null,
      max_daily_rent: u.min_daily_rent ?? null,
      min_plan_total: u.min_plan_total ?? null,
      min_plan_label: null,
      min_walk_minutes: u.min_walk_minutes ?? null,
      thumbnail_url: null,
      has_campaign: false,
      access_summary: [],
      station_summary: '',
      units: [u],
    },
  };
}

type CoordsOf = (u: BuildingUnit) => [number, number];

function runFilters(
  units: BuildingUnit[],
  filters: MapFilters,
  bounds: BoundsData | null = null,
  coordsOf: CoordsOf = () => [139.7, 35.6],
): ReturnType<typeof applyBuildingFilters> {
  return applyBuildingFilters(
    { type: 'FeatureCollection', features: units.map((u) => wrapBuilding(u, coordsOf(u))) },
    filters,
    bounds,
  );
}

/** マッチした部屋 id の集合(建物採用と部屋条件の両方を通過) */
const matchedIds = (
  units: BuildingUnit[],
  filters: MapFilters,
  bounds: BoundsData | null = null,
  coordsOf: CoordsOf = () => [139.7, 35.6],
): Set<number> => runFilters(units, filters, bounds, coordsOf).matchedRoomIds;

/** マッチ部屋を部屋ソート(sortFeatures)済み平面リストへ展開 */
const matchedRooms = (units: BuildingUnit[], filters: MapFilters) => {
  const r = runFilters(units, filters);
  return flattenMatchedUnits(r.buildings, r.matchedRoomIds, filters.sortBy, filters);
};

const catalogBase: MapFilters = {
  ...DEFAULT_STATIC_FILTERS,
  // DEFAULT_STATIC_FILTERS は動的5項を含まないため明示する(catalog モードでは期間未使用)
  checkIn: '2026-08-01',
  checkOut: '2026-09-01',
  priceMode: 'catalog',
  maxPrice: CATALOG_PRICE_UNLIMITED,
  sortBy: 'score',
};

const data: BuildingUnit[] = [
  unit(1, { layout: '1K', min_plan_total: 80000, min_walk_minutes: 5, total_score: 90 }),
  unit(2, {
    layout: '1R',
    min_plan_total: 150000,
    min_walk_minutes: 15,
    total_score: 40,
    prefecture_name: '大阪府',
  }),
  unit(3, { layout: '1K+ロフト', min_plan_total: 100000, min_walk_minutes: 8, total_score: 70, shortlist_status: 'saved' }),
  unit(4, { layout: '1DK', min_plan_total: 120000, min_walk_minutes: 3, total_score: 60, shortlist_status: 'hide' }),
];

describe('部屋条件フィルタ(applyBuildingFilters 経由・catalog)', () => {
  it('filters by max price', () => {
    expect(matchedIds(data, { ...catalogBase, maxPrice: 100000 })).toEqual(new Set([1, 3]));
  });

  it('filters by layout includes', () => {
    expect(matchedIds(data, { ...catalogBase, layout: '1K' })).toEqual(new Set([1, 3]));
  });

  it('filters by walk minutes', () => {
    const ids = matchedIds(data, { ...catalogBase, maxWalkMinutes: 8 });
    expect(ids).not.toContain(2);
    for (const u of data) {
      if ((u.min_walk_minutes ?? 99) <= 8) expect(ids.has(u.id)).toBe(true);
    }
  });

  it('filters by min score', () => {
    expect(matchedIds(data, { ...catalogBase, minScore: 70 })).toEqual(new Set([1, 3]));
  });

  it('filters by prefecture', () => {
    expect(matchedIds(data, { ...catalogBase, prefecture: '大阪府' })).toEqual(new Set([2]));
  });

  it('filters by required features AND', () => {
    const withCats = [unit(1, { feature_categories: ['auto_lock', 'washing_machine'] })];
    expect(
      matchedIds(withCats, {
        ...catalogBase,
        requiredFeatures: ['auto_lock', 'washing_machine'],
      }),
    ).toEqual(new Set([1]));
    // 1 つでも欠ければ非表示
    expect(
      matchedIds(withCats, { ...catalogBase, requiredFeatures: ['auto_lock', 'loft'] }),
    ).toEqual(new Set());
  });

  it('filters by source_site', () => {
    const mixed = [
      unit(1),
      unit(2, { source_site: 'bratto', source_display_name: 'ブラット' }),
    ];
    expect(matchedIds(mixed, { ...catalogBase, sources: ['bratto'] })).toEqual(new Set([2]));
  });

  it('filters shortlist hide', () => {
    expect(matchedIds(data, { ...catalogBase, status: 'hide' })).toEqual(new Set([4]));
  });

  it('sorts by price ascending', () => {
    const rooms = matchedRooms(data, { ...catalogBase, sortBy: 'price_asc' });
    const prices = rooms.map((f) => monthlyTotalYen(f.properties));
    expect(prices).toEqual([...prices].sort((a, b) => a - b));
  });
});

describe('部屋条件フィルタ(applyBuildingFilters 経由・stay)', () => {
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

  const stayData: BuildingUnit[] = [
    unit(10, { title: 'cheap', rent_plans: stayPlansCheap, total_score: 50 }),
    unit(11, { title: 'expensive', rent_plans: stayPlansExpensive, total_score: 90 }),
    unit(12, { title: 'no plans', rent_plans: [], total_score: 99 }),
  ];

  const stayFilters: MapFilters = {
    ...DEFAULT_STATIC_FILTERS,
    priceMode: 'stay',
    checkIn: '2026-08-01',
    checkOut: '2026-08-30', // 30 days → short
    maxPrice: STAY_PRICE_UNLIMITED,
    sortBy: 'price_asc',
  };

  it('excludes unestimable and reports count', () => {
    const r = runFilters(stayData, stayFilters);
    expect(r.excludedUnestimable).toBe(1);
    expect(r.matchedRoomIds).toEqual(new Set([10, 11]));
  });

  it('sorts by stay total ascending', () => {
    const rooms = matchedRooms(stayData, stayFilters);
    expect(rooms.map((f) => f.properties.id)).toEqual([10, 11]);
    const totals = rooms.map((f) => f.properties.stay_estimate?.stayTotalYen);
    expect(totals[0]!).toBeLessThan(totals[1]!);
  });

  it('filters by stay total maxPrice', () => {
    // 30d * 2000 = 60000 for cheap (手数料は fixture 未設定 = 算出不能で除外);
    // expensive much higher
    const ids = matchedRooms(stayData, { ...stayFilters, maxPrice: 100_000 }).map(
      (f) => f.properties.id,
    );
    expect(ids).toEqual([10]);
  });

  it('uses original daily when campaign expired on estimate', () => {
    const props = unit(99, {
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
    });
    const est = computeStayEstimate(props, '2026-08-01', '2026-08-30');
    expect(est.ok).toBe(true);
    expect(est.rentDailyYen).toBe(4600);
  });
});

describe('必須設備(カテゴリcode集合包含・設計§3.4)', () => {
  const base = { ...catalogBase, requiredFeatures: [] as string[] };

  it('feature_categories 配列の包含で判定する(部分一致に頼らない)', () => {
    // 生値は「室内洗濯機」でも code washing_machine が充足していればヒット
    const rooms = [
      unit(1, {
        feature_summary: '室内洗濯機、オートロック',
        feature_categories: ['washing_machine', 'auto_lock'],
      }),
    ];
    expect(matchedIds(rooms, { ...base, requiredFeatures: ['washing_machine'] })).toEqual(
      new Set([1]),
    );
  });

  it('複合code・親code も包含判定で使える', () => {
    const rooms = [
      unit(2, {
        feature_summary: '駐輪可（無料）',
        feature_categories: ['bicycle_parking.fee_free', 'bicycle_parking', 'fee_free'],
      }),
    ];
    expect(matchedIds(rooms, { ...base, requiredFeatures: ['bicycle_parking.fee_free'] }).has(2)).toBe(true);
    expect(matchedIds(rooms, { ...base, requiredFeatures: ['bicycle_parking'] }).has(2)).toBe(true);
    expect(matchedIds(rooms, { ...base, requiredFeatures: ['parking.fee_free'] })).toEqual(new Set());
  });

  it('feature_categories が空の部屋は設備条件で非表示(B2-ε: 部分一致フォールバック廃止)', () => {
    const rooms = [unit(3, { feature_summary: 'オートロック', feature_categories: [] })];
    expect(matchedIds(rooms, { ...base, requiredFeatures: ['オートロック'] })).toEqual(new Set());
  });
});

describe('isListed(掲載中判定の正本)', () => {
  it('is_active === false のみ非掲載扱いとする', () => {
    expect(isListed({ is_active: true })).toBe(true);
    expect(isListed({ is_active: false })).toBe(false);
    // BE 契約では常に boolean だが、null/undefined は防御的に掲載扱い
    expect(isListed({})).toBe(true);
    expect(isListed({ is_active: null })).toBe(true);
  });
});

describe('部屋ソート(sortFeatures・flattenMatchedUnits 経由)', () => {
  it('非掲載部屋はどのソートキーでも末尾に回る', () => {
    const rooms = [unit(10, { total_score: 99, is_active: false }), unit(11, { total_score: 10 })];
    const filters: MapFilters = {
      ...catalogBase,
      listingVisibility: 'all',
      sortBy: 'score',
    };
    expect(matchedRooms(rooms, filters).map((f) => f.properties.id)).toEqual([11, 10]);
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

  it('saved ビューへの切替時は既定で最終編集順(updated_desc)へ寄せる', () => {
    const next = mergeMapFilters(catalogBase, { status: 'saved' });
    expect(next.status).toBe('saved');
    expect(next.sortBy).toBe('updated_desc');
  });

  it('saved ビューからの退出時は updated_desc を全体ビュー既定(安い順)へ戻す', () => {
    const saved: MapFilters = {
      ...catalogBase,
      status: 'saved',
      sortBy: 'updated_desc',
    };
    const next = mergeMapFilters(saved, { status: 'all' });
    expect(next.status).toBe('all');
    expect(next.sortBy).toBe('price_asc');
  });

  it('saved 切替時も同一 patch での明示 sortBy を優先する', () => {
    const next = mergeMapFilters(catalogBase, { status: 'saved', sortBy: 'score' });
    expect(next.status).toBe('saved');
    expect(next.sortBy).toBe('score');
  });

  it('status 非遷移のパッチでは sortBy を書き換えない', () => {
    const saved: MapFilters = {
      ...catalogBase,
      status: 'saved',
      sortBy: 'updated_desc',
    };
    const next = mergeMapFilters(saved, { maxPrice: 100000 });
    expect(next.sortBy).toBe('updated_desc');
  });

  it('reset + status=saved の併用でも saved ビュー既定(updated_desc)を適用する', () => {
    const next = mergeMapFilters(catalogBase, { reset: true, status: 'saved' });
    expect(next.status).toBe('saved');
    expect(next.sortBy).toBe('updated_desc');
  });
});

describe('createDefaultMapFilters (全フィールド生成の契約)', () => {
  const fixed = new Date(2026, 9, 8); // 2026-10-08 (local)

  it('MapFilters の全キーを欠落なく埋める(defaultDateRange の動的値を含む)', () => {
    const f = createDefaultMapFilters(fixed);
    for (const key of ALL_FILTER_KEYS) {
      expect(f[key]).toBeDefined();
    }
  });

  it('動的5項は実行時既定で上書きされる', () => {
    const f = createDefaultMapFilters(fixed);
    const range = defaultDateRange(fixed);
    expect(f.checkIn).toBe(range.checkIn);
    expect(f.checkOut).toBe(range.checkOut);
    expect(f.checkIn).toBe('2026-11-01'); // 翌月1日
    expect(f.checkOut).toBe('2026-12-01'); // その1ヶ月後
    expect(f.maxPrice).toBe(STAY_PRICE_UNLIMITED);
    expect(f.priceMode).toBe('stay');
    expect(f.sortBy).toBe('price_asc');
  });

  it('静的既定は DEFAULT_STATIC_FILTERS を継承する', () => {
    const f = createDefaultMapFilters(fixed);
    expect(f.areaRange).toEqual([...DEFAULT_STATIC_FILTERS.areaRange]);
    expect(f.layout).toBe('all');
    expect(f.status).toBe('all');
    expect(f.listingVisibility).toBe('active');
    expect(f.searchQuery).toBe('');
    expect(f.areaMode).toBe('all');
    expect(f.drawnPolygon).toBeNull();
    expect(f.maxWalkMinutes).toBeNull();
    expect(f.minScore).toBeNull();
    expect(f.prefecture).toBeNull();
    expect(f.requiredFeatures).toEqual([]);
    expect(f.sources).toEqual([]);
  });
});

describe('pointInPolygon (レイキャスト)', () => {
  const rect: [number, number][] = [
    [139.65, 35.55],
    [139.75, 35.55],
    [139.75, 35.65],
    [139.65, 35.65],
  ];

  it('矩形の内側', () => {
    expect(pointInPolygon(139.7, 35.6, rect)).toBe(true);
  });

  it('矩形の外側', () => {
    expect(pointInPolygon(139.8, 35.6, rect)).toBe(false);
    expect(pointInPolygon(139.7, 35.7, rect)).toBe(false);
  });

  it('凹みのあるL字ポリゴン', () => {
    const lShape: [number, number][] = [
      [0, 0],
      [2, 0],
      [2, 1],
      [1, 1],
      [1, 2],
      [0, 2],
    ];
    expect(pointInPolygon(0.5, 0.5, lShape)).toBe(true);
    expect(pointInPolygon(1.5, 1.5, lShape)).toBe(false);
    expect(pointInPolygon(-0.5, 1.5, lShape)).toBe(false);
  });

  it('時計回りと反時計回りで結果が一致', () => {
    expect(pointInPolygon(139.7, 35.6, [...rect].reverse())).toBe(true);
  });
});

describe('areaMode=drawn (囲った範囲で絞り込み)', () => {
  const polygon: [number, number][] = [
    [139.65, 35.55],
    [139.75, 35.55],
    [139.75, 35.65],
    [139.65, 35.65],
  ];
  const drawnBase: MapFilters = { ...catalogBase, areaMode: 'drawn', drawnPolygon: polygon };
  const rooms = [unit(20), unit(21)];
  // 1部屋=1建物のため建物代表座標 = 部屋座標。20 は内側・21 は外側
  const coordsOf: CoordsOf = (u) => (u.id === 20 ? [139.7, 35.6] : [139.8, 35.6]);

  it('ポリゴン内の物件のみ残る', () => {
    expect(matchedIds(rooms, drawnBase, null, coordsOf)).toEqual(new Set([20]));
  });

  it('drawnPolygon が null なら範囲制限なし', () => {
    expect(matchedIds(rooms, { ...drawnBase, drawnPolygon: null }, null, coordsOf)).toEqual(
      new Set([20, 21]),
    );
  });

  it('areaMode=all ならポリゴンを無視', () => {
    expect(matchedIds(rooms, { ...drawnBase, areaMode: 'all' }, null, coordsOf)).toEqual(
      new Set([20, 21]),
    );
  });
});
