import type {
  BoundsData,
  BuildingFeature,
  BuildingGeoJSON,
  BuildingUnit,
  MapFilters,
  PropertyFeature,
  PropertyGeoJSON,
  SortKey,
  StayEstimateSummary,
} from '../types.ts';
import {
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_STATIC_FILTERS,
  STAY_PRICE_UNLIMITED,
} from '../types.ts';
import {
  calcStayDays,
  calculateRentTotal,
  planDisplayLabel,
} from './rentCalculator.ts';
import { defaultDateRange } from './stayDates.ts';
import { normalizeUnit } from './building.ts';

export function monthlyTotalYen(props: PropertyFeature['properties']): number {
  return props.min_plan_total || (props.min_daily_rent || 0) * 30;
}

/**
 * 掲載中判定の正本。is_active === false のみ「非掲載」扱いとする。
 * BE 生成型の契約では is_active は常に booleanだが、任意/null の入力も
 * 受けられるよう防御的に optional で受ける(null/undefined は掲載扱い)。
 */
export const isListed = (p: { is_active?: boolean | null }): boolean => p.is_active !== false;

export function isPriceUnlimited(filters: MapFilters): boolean {
  if (filters.priceMode === 'stay') {
    return filters.maxPrice >= STAY_PRICE_UNLIMITED;
  }
  return filters.maxPrice >= CATALOG_PRICE_UNLIMITED;
}

export function priceForSort(props: PropertyFeature['properties'], filters: MapFilters): number {
  if (filters.priceMode === 'stay') {
    const total = props.stay_estimate?.stayTotalYen;
    if (total != null) return total;
    return Number.POSITIVE_INFINITY;
  }
  return monthlyTotalYen(props);
}

/**
 * Build stay estimate via shared rent calculator (same as detail simulator).
 * 引数は計算に必要な最小構造の Pick 派生(建物 units(BuildingUnitProperties)を
 * 正規化なしで直接渡せるようにするため・計画 §6.2)。
 */
export type StayEstimateSource = Pick<
  PropertyFeature['properties'],
  'rent_plans' | 'campaigns'
> & { contract_fee_yen?: number | null };

export function computeStayEstimate(
  props: StayEstimateSource,
  checkIn: string,
  checkOut: string,
): StayEstimateSummary {
  // 生成型 RentPlan[] / Campaign[] は計算器の CalculatorPlan[] / CalculatorCampaign[]
  // (Partial<Pick> 派生) に構造的部分型としてそのまま代入できる
  const plans = props.rent_plans || [];
  const campaigns = props.campaigns || [];
  // 契約事務手数料は GeoJSON が BE 解決済みの実効値(物件値 > サイト既定)を
  // 最初から載せてくる。null(算出不能)は総額から除外された概算として扱う
  const r = calculateRentTotal({
    checkIn,
    checkOut,
    plans,
    campaigns,
    contractFeeYen: props.contract_fee_yen ?? null,
  });
  if (!r.ok) {
    return {
      ok: false,
      stayDays: 0,
      stayTotalYen: null,
      rentDailyYen: null,
      selectedPlanCode: null,
      usedFallback: false,
      planLabel: null,
    };
  }
  const code = r.selectedPlanCode;
  return {
    ok: true,
    stayDays: r.stayDays,
    stayTotalYen: r.grandTotal,
    rentDailyYen: r.breakdown.rentDaily,
    selectedPlanCode: code,
    usedFallback: r.usedFallback,
    planLabel: planDisplayLabel(r.selectedPlan) || null,
  };
}

export function createDefaultMapFilters(today: Date = new Date()): MapFilters {
  const range = defaultDateRange(today);
  return {
    ...DEFAULT_STATIC_FILTERS,
    maxPrice: STAY_PRICE_UNLIMITED,
    priceMode: 'stay',
    sortBy: 'price_asc',
    checkIn: range.checkIn,
    checkOut: range.checkOut,
  };
}

function datesValid(checkIn: string, checkOut: string): boolean {
  if (!checkIn || !checkOut) return false;
  return checkIn <= checkOut;
}

/**
 * Ray-cast point-in-polygon. ring is an unclosed [lng, lat][] ring.
 * Antimeridian crossings are not handled (domestic use only).
 */
export function pointInPolygon(lng: number, lat: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** フリーワード検索の対象テキスト(部屋単位・matchesMapFilters と建物フィルタで共用) */
function searchHaystack(props: PropertyFeature['properties']): string {
  return [
    props.title,
    props.address,
    props.feature_summary,
    props.access_summary,
    props.station_summary,
    props.prefecture_name,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

/** フリーワード判定(部屋単位の haystack に対する包含) */
export function matchesSearchQuery(props: PropertyFeature['properties'], query: string): boolean {
  return searchHaystack(props).includes(query.toLowerCase());
}

export function matchesMapFilters(
  feat: PropertyFeature,
  filters: MapFilters,
  mapBounds: BoundsData | null,
): boolean {
  const props = feat.properties;

  if (!isPriceUnlimited(filters)) {
    if (filters.priceMode === 'stay') {
      const total = props.stay_estimate?.stayTotalYen;
      if (total == null || total > filters.maxPrice) return false;
    } else if (monthlyTotalYen(props) > filters.maxPrice) {
      return false;
    }
  }

  if (props.area_m2 != null) {
    if (props.area_m2 < filters.areaRange[0] || props.area_m2 > filters.areaRange[1]) {
      return false;
    }
  }

  if (filters.layout !== 'all' && props.layout && !props.layout.includes(filters.layout)) {
    return false;
  }

  const status = props.shortlist_status || 'none';
  if (filters.status === 'saved' && status !== 'saved') return false;
  if (filters.status === 'unsaved' && status !== 'none') return false;
  if (filters.status === 'hide' && status !== 'hide') return false;
  if (filters.status === 'reject' && status !== 'reject') return false;

  // 掲載状態（全て/掲載中/非掲載）。is_active 未定義は掲載扱い（旧データ互換）
  const isActive = isListed(props);
  if (filters.listingVisibility === 'active' && !isActive) return false;
  if (filters.listingVisibility === 'inactive' && isActive) return false;

  if (filters.searchQuery) {
    if (!matchesSearchQuery(props, filters.searchQuery)) return false;
  }

  if (filters.areaMode === 'viewport' && mapBounds) {
    const coords = feat.geometry?.coordinates;
    if (coords && coords.length >= 2) {
      const [lng, lat] = coords;
      const [swLat, swLng] = mapBounds.southWest;
      const [neLat, neLng] = mapBounds.northEast;
      if (lat < swLat || lat > neLat || lng < swLng || lng > neLng) {
        return false;
      }
    }
  } else if (
    filters.areaMode === 'drawn' &&
    filters.drawnPolygon &&
    filters.drawnPolygon.length >= 3
  ) {
    const coords = feat.geometry?.coordinates;
    if (coords && coords.length >= 2 && !pointInPolygon(coords[0], coords[1], filters.drawnPolygon)) {
      return false;
    }
  }

  if (filters.maxWalkMinutes != null) {
    if (props.min_walk_minutes == null || props.min_walk_minutes > filters.maxWalkMinutes) {
      return false;
    }
  }

  if (filters.minScore != null) {
    if ((props.total_score || 0) < filters.minScore) return false;
  }

  if (filters.prefecture) {
    const pref = props.prefecture_name || '';
    if (pref !== filters.prefecture && !pref.includes(filters.prefecture)) {
      return false;
    }
  }

  if (filters.sources && filters.sources.length > 0) {
    const site = props.source_site || '';
    if (!filters.sources.includes(site)) return false;
  }

  if (filters.requiredFeatures.length > 0) {
    // 必須設備判定: feature_categories(充足可能 code 集合)への包含比較(設計 §3.4)。
    // FE は辞書を持たず、トグルが発行する code との単一配列包含のみ。
    // BE は常に feature_categories を載せるため、欠落/空 = 条件不充足で非表示。
    const cats = props.feature_categories ?? [];
    for (const req of filters.requiredFeatures) {
      if (!cats.includes(req)) return false;
    }
  }

  return true;
}

/**
 * 部屋のショートリスト最終編集時刻(saved 行のみ対象・未保存は null)。
 * ISO 文字列のため辞書順比較 = 時系列比較。
 */
function roomUpdatedAt(props: PropertyFeature['properties']): string | null {
  return props.shortlist_status === 'saved' ? (props.shortlist_updated_at ?? null) : null;
}

/** null(未編集)は末尾へ。同時刻は 0(呼び出し側のタイブレークへ) */
function compareUpdatedDesc(a: string | null, b: string | null): number {
  if (a === null || b === null) {
    if (a !== null) return -1;
    if (b !== null) return 1;
    return 0;
  }
  return b.localeCompare(a);
}

export function sortFeatures(
  features: PropertyFeature[],
  sortBy: SortKey,
  filters: MapFilters,
): PropertyFeature[] {
  const sorted = [...features];
  sorted.sort((a, b) => {
    const pa = a.properties;
    const pb = b.properties;
    switch (sortBy) {
      case 'price_asc': {
        const diff = priceForSort(pa, filters) - priceForSort(pb, filters);
        if (diff !== 0) return diff;
        return (pb.total_score || 0) - (pa.total_score || 0);
      }
      case 'price_desc': {
        const diff = priceForSort(pb, filters) - priceForSort(pa, filters);
        if (diff !== 0) return diff;
        return (pb.total_score || 0) - (pa.total_score || 0);
      }
      case 'area_desc':
        return (pb.area_m2 || 0) - (pa.area_m2 || 0);
      case 'updated_desc': {
        const tDiff = compareUpdatedDesc(roomUpdatedAt(pa), roomUpdatedAt(pb));
        if (tDiff !== 0) return tDiff;
        return (pb.total_score || 0) - (pa.total_score || 0);
      }
      case 'score':
      default: {
        const scoreDiff = (pb.total_score || 0) - (pa.total_score || 0);
        if (scoreDiff !== 0) return scoreDiff;
        return priceForSort(pa, filters) - priceForSort(pb, filters);
      }
    }
  });
  // 掲載終了(is_active === false)はどのソートキーでも末尾に回す
  const activeList: PropertyFeature[] = [];
  const inactiveList: PropertyFeature[] = [];
  for (const feat of sorted) {
    (!isListed(feat.properties) ? inactiveList : activeList).push(feat);
  }
  return [...activeList, ...inactiveList];
}

export function mergeMapFilters(
  current: MapFilters,
  patch: Partial<MapFilters> & { reset?: boolean },
): MapFilters {
  if (patch.reset) {
    const { reset: _r, ...rest } = patch;
    const base = createDefaultMapFilters();
    // Keep stored period if patch doesn't override and current had valid dates
    if (!rest.checkIn && current.checkIn) base.checkIn = current.checkIn;
    if (!rest.checkOut && current.checkOut) base.checkOut = current.checkOut;
    // reset + saved 指定(AI の reset:true 併用)でも saved ビュー既定を適用
    if (rest.status === 'saved' && rest.sortBy === undefined) {
      base.sortBy = 'updated_desc';
    }
    return { ...base, ...rest };
  }

  const next: MapFilters = { ...current };
  for (const [key, value] of Object.entries(patch) as [keyof MapFilters | 'reset', unknown][]) {
    if (key === 'reset' || value === undefined) continue;
    (next as unknown as Record<string, unknown>)[key] = value;
  }

  // Mode switch: reset price ceiling sentinel to avoid empty/full list surprises
  if (patch.priceMode !== undefined && patch.priceMode !== current.priceMode) {
    if (patch.maxPrice === undefined) {
      next.maxPrice =
        patch.priceMode === 'stay' ? STAY_PRICE_UNLIMITED : CATALOG_PRICE_UNLIMITED;
    }
  }

  // status 切替時の並び替え連動(saved ビューの既定は最終編集順):
  // saved へ入るときは同一 patch での明示指定が無ければ最終編集順へ、
  // 抜けるときに最終編集順が残っていれば全体ビューの既定(安い順)へ戻す
  if (patch.status !== undefined && patch.status !== current.status) {
    if (patch.status === 'saved' && patch.sortBy === undefined) {
      next.sortBy = 'updated_desc';
    } else if (patch.status !== 'saved' && next.sortBy === 'updated_desc') {
      next.sortBy = 'price_asc';
    }
  }

  // Clamp checkout
  if (next.checkIn && next.checkOut && next.checkOut < next.checkIn) {
    next.checkOut = next.checkIn;
  }

  return next;
}

export function collectPrefectures(rawGeojsonData: PropertyGeoJSON | null): string[] {
  if (!rawGeojsonData?.features) return [];
  const counts = new Map<string, number>();
  for (const f of rawGeojsonData.features) {
    const p = f.properties.prefecture_name;
    if (!p) continue;
    counts.set(p, (counts.get(p) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name]) => name);
}

/** Distinct source_site values present in the loaded GeoJSON. */
export function collectSources(rawGeojsonData: PropertyGeoJSON | null): {
  id: string;
  label: string;
  count: number;
}[] {
  if (!rawGeojsonData?.features) return [];
  const counts = new Map<string, { label: string; count: number }>();
  for (const f of rawGeojsonData.features) {
    const id = f.properties.source_site;
    if (!id) continue;
    const label = f.properties.source_display_name || id;
    const cur = counts.get(id);
    if (cur) cur.count += 1;
    else counts.set(id, { label, count: 1 });
  }
  return [...counts.entries()]
    .map(([id, v]) => ({ id, label: v.label, count: v.count }))
    .sort((a, b) => b.count - a.count);
}

/** 滞在日数のサマリ(サイドバー表示)。帯バンド名はサイト間で実態がズレるため
 *  表示しない(2026-10-08 承認・案B: 日数のみ)。 */
export function stayBandSummary(checkIn: string, checkOut: string): string | null {
  const days = calcStayDays(checkIn, checkOut);
  if (days == null) return null;
  return `${days}日`;
}

/**
 * フィルタ結果の stay_estimate を元フィーチャーへ反映する。
 * フィルタ済みリストに計算済み値があればそれを優先し、無ければここで再計算する。
 * 保存済み一覧・比較候補の表示用(App の useComparison から使用)。
 */
export function withStayEstimate(
  f: PropertyFeature,
  filtered: PropertyFeature | undefined,
  checkIn: string,
  checkOut: string,
): PropertyFeature {
  if (filtered?.properties.stay_estimate) {
    return {
      ...f,
      properties: {
        ...f.properties,
        stay_estimate: filtered.properties.stay_estimate,
        shortlist_comment:
          f.properties.shortlist_comment ?? filtered.properties.shortlist_comment,
      },
    };
  }
  const est = computeStayEstimate(f.properties, checkIn, checkOut);
  return {
    ...f,
    properties: {
      ...f.properties,
      stay_estimate: est.ok ? est : f.properties.stay_estimate,
    },
  };
}

// ============================================================
// 建物単位フィルタ(Phase B2-α / docs/building-aggregation-b2-fe-plan.md §6.2)
//
// 意味論: 部屋条件(設備/価格/面積/間取り/徒歩/スコア/ワード/shortlist/
// 掲載状態)は「条件を満たす部屋を 1 つ以上持つ建物」を採用する(BE 検索
// (§6.1)と同一)。units には建物の可視部屋全部屋が載るため、FE は unit 単位で
// 再判定して matchedRoomIds を出す(サイドバーカードのフィルタ一致強調用)。
// ============================================================

export interface BuildingFilterResult {
  /** 採用建物(建物代表値ソート済み・units に stay_estimate 付与済み) */
  buildings: BuildingFeature[];
  /** フィルタ条件を通過した部屋 id の集合(採用建物内) */
  matchedRoomIds: Set<number>;
  /** stay モードで総額を計算できなかった unit 数(部屋数カウント・計画 §4.4 承認) */
  excludedUnestimable: number;
}

/** フリーワード検索の対象テキスト(建物単位: 代表名+ソース別名+住所) */
function buildingSearchHaystack(b: BuildingFeature['properties']): string {
  return [
    b.name,
    ...b.building_names.map((n) => n.name),
    b.address,
    b.municipality,
    b.prefecture_name,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

/** 建物の価格ソート値(stay モードは units の期間総額最安・計画 §4.2 承認) */
function buildingPriceForSort(b: BuildingFeature['properties'], filters: MapFilters): number {
  if (filters.priceMode === 'stay') {
    let min: number | null = null;
    for (const u of b.units) {
      const total = u.stay_estimate?.stayTotalYen;
      if (total != null && (min === null || total < min)) min = total;
    }
    return min ?? Number.POSITIVE_INFINITY;
  }
  if (b.min_plan_total != null) return b.min_plan_total;
  if (b.min_daily_rent != null) return b.min_daily_rent * 30;
  return Number.POSITIVE_INFINITY;
}

function buildingMaxScore(b: BuildingFeature['properties']): number {
  let max = 0;
  for (const u of b.units) {
    const s = u.total_score ?? 0;
    if (s > max) max = s;
  }
  return max;
}

function buildingMaxArea(b: BuildingFeature['properties']): number {
  let max: number | null = null;
  for (const u of b.units) {
    if (u.area_m2 != null && (max === null || u.area_m2 > max)) max = u.area_m2;
  }
  return max ?? 0;
}

/**
 * 建物のショートリスト最終編集時刻(建物saved の updated_at と
 * 保存済み部屋の updated_at の最大値・未保存は null)。
 */
function buildingUpdatedAt(b: BuildingFeature['properties']): string | null {
  let max: string | null =
    b.shortlist_status === 'saved' ? (b.shortlist_updated_at ?? null) : null;
  for (const u of b.units) {
    if ((u.shortlist_status ?? 'none') !== 'saved') continue;
    const t = u.shortlist_updated_at;
    if (t && (max === null || t > max)) max = t;
  }
  return max;
}

/** 建物代表値ソート(計画 §4.2)。all_inactive 建物はどのキーでも末尾 */
function sortBuildings(
  buildings: BuildingFeature[],
  sortBy: SortKey,
  filters: MapFilters,
): BuildingFeature[] {
  const sorted = [...buildings];
  sorted.sort((a, b) => {
    const pa = a.properties;
    const pb = b.properties;
    switch (sortBy) {
      case 'price_asc': {
        const diff = buildingPriceForSort(pa, filters) - buildingPriceForSort(pb, filters);
        if (diff !== 0) return diff;
        return buildingMaxScore(pb) - buildingMaxScore(pa);
      }
      case 'price_desc': {
        const diff = buildingPriceForSort(pb, filters) - buildingPriceForSort(pa, filters);
        if (diff !== 0) return diff;
        return buildingMaxScore(pb) - buildingMaxScore(pa);
      }
      case 'area_desc':
        return buildingMaxArea(pb) - buildingMaxArea(pa);
      case 'updated_desc': {
        const tDiff = compareUpdatedDesc(buildingUpdatedAt(pa), buildingUpdatedAt(pb));
        if (tDiff !== 0) return tDiff;
        return buildingMaxScore(pb) - buildingMaxScore(pa);
      }
      case 'score':
      default: {
        const scoreDiff = buildingMaxScore(pb) - buildingMaxScore(pa);
        if (scoreDiff !== 0) return scoreDiff;
        return buildingPriceForSort(pa, filters) - buildingPriceForSort(pb, filters);
      }
    }
  });
  const activeList: BuildingFeature[] = [];
  const inactiveList: BuildingFeature[] = [];
  for (const b of sorted) {
    (!b.properties.is_active ? inactiveList : activeList).push(b);
  }
  return [...activeList, ...inactiveList];
}

/**
 * 建物意味論フィルタ(Worker で実行)。部屋条件(設備/価格/面積/間取り/徒歩/スコア/
 * shortlist/掲載状態)は matchesMapFilters へ normalizeUnit 済み pseudo Feature を
 * 流して判定する(BE 検索 §6.1 と同一の「条件を満たす部屋を 1 つ以上持つ建物」採用)。
 *
 * - stay 計算は全 units へ付与(計算不能 unit は除外+カウント。カウント単位は部屋)
 * - フリーワードは「部屋 haystack OR 建物名(代表+別名)/住所」の OR(計画 §4.4)。
 *   ワード以外の条件はあくまで unit 条件として判定する(§6.1 の一般則を維持)
 * - listingVisibility: active = unit の is_active 判定(mixed 建物は非 active 部屋を
 *   弾いて採用)/ all = 全 units / inactive = **all_inactive 建物のみ**(設計 §8・
 *   unit の is_active 判定は無効化。該当建物は全部屋非 active のため実質同値)
 */
export function applyBuildingFilters(
  raw: BuildingGeoJSON | null,
  filters: MapFilters,
  mapBounds: BoundsData | null,
): BuildingFilterResult {
  if (!raw?.features) {
    return { buildings: [], matchedRoomIds: new Set<number>(), excludedUnestimable: 0 };
  }

  const stayActive =
    filters.priceMode === 'stay' && datesValid(filters.checkIn, filters.checkOut);
  const query = filters.searchQuery ? filters.searchQuery.toLowerCase() : '';

  const inactiveOnly = filters.listingVisibility === 'inactive';
  const unitFilters: MapFilters = inactiveOnly
    ? { ...filters, listingVisibility: 'all' }
    : filters;
  // status フィルタの建物モード意味論(承認 U1):
  // - saved/unsaved は建物単位判定(建物saved OR 部屋saved≥1 / その否定)のため
  //   部屋単位の status 絞りは外し、建物採用条件として先に判定する
  // - hide/reject は部屋単位のまま(該当部屋のみマッチ・建物採用)
  const statusFilter = filters.status;
  const unitStatusFilter =
    statusFilter === 'hide' || statusFilter === 'reject' ? statusFilter : 'all';
  const pseudoFilters: MapFilters = {
    ...unitFilters,
    searchQuery: '',
    status: unitStatusFilter,
  };

  let excludedUnestimable = 0;
  const adopted: BuildingFeature[] = [];
  const matchedRoomIds = new Set<number>();

  for (const feat of raw.features) {
    const base = feat.properties;
    if (!base.units.length) continue;
    if (inactiveOnly && base.is_active) continue;

    // 建物単位の saved 判定(U3 の可視性貫通と同じ正否: 建物saved は部屋と独立)
    if (statusFilter === 'saved' || statusFilter === 'unsaved') {
      const buildingSaved = base.shortlist_status === 'saved';
      const hasSavedUnit = base.units.some((u) => u.shortlist_status === 'saved');
      const isSavedBuilding = buildingSaved || hasSavedUnit;
      if (statusFilter === 'saved' && !isSavedBuilding) continue;
      if (statusFilter === 'unsaved' && isSavedBuilding) continue;
    }

    // 全 units へ stay_estimate 付与(catalog / 期間無効時は strip)
    const units: BuildingUnit[] = [];
    for (const unit of base.units) {
      if (stayActive) {
        const estimate = computeStayEstimate(unit, filters.checkIn, filters.checkOut);
        if (!estimate.ok || estimate.stayTotalYen == null) {
          excludedUnestimable += 1;
          continue;
        }
        units.push({ ...unit, stay_estimate: estimate });
      } else {
        const { stay_estimate: _drop, ...rest } = unit;
        units.push({ ...rest, stay_estimate: null });
      }
    }
    if (!units.length) continue;

    const building: BuildingFeature = {
      ...feat,
      properties: { ...base, units },
    };
    const buildingWordOk =
      !query || buildingSearchHaystack(building.properties).includes(query);

    let anyMatched = false;
    for (const unit of units) {
      const pseudo: PropertyFeature = {
        type: 'Feature',
        geometry: building.geometry,
        properties: normalizeUnit(unit, building.properties),
      };
      if (!matchesMapFilters(pseudo, pseudoFilters, mapBounds)) continue;
      if (query && !buildingWordOk && !matchesSearchQuery(pseudo.properties, query)) continue;
      anyMatched = true;
      matchedRoomIds.add(unit.id);
    }
    if (anyMatched) adopted.push(building);
  }

  return {
    buildings: sortBuildings(adopted, filters.sortBy, filters),
    matchedRoomIds,
    excludedUnestimable,
  };
}

/** 建物配列 + matchedRoomIds → 部屋平面リスト(B2-α の UI 互換出力・B2-β で廃止) */
export function flattenMatchedUnits(
  buildings: BuildingFeature[],
  matchedRoomIds: Set<number>,
  sortBy: SortKey,
  filters: MapFilters,
): PropertyFeature[] {
  const flat: PropertyFeature[] = [];
  for (const b of buildings) {
    for (const unit of b.properties.units) {
      if (!matchedRoomIds.has(unit.id)) continue;
      flat.push({
        type: 'Feature',
        geometry: b.geometry,
        properties: normalizeUnit(unit, b.properties),
      });
    }
  }
  return sortFeatures(flat, sortBy, filters);
}
