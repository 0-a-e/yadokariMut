import type {
  BoundsData,
  MapFilters,
  PropertyFeature,
  PropertyGeoJSON,
  SortKey,
  StayEstimateSummary,
} from '../types';
import {
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_MAP_FILTERS,
  STAY_PRICE_UNLIMITED,
} from '../types';
import {
  calcStayDays,
  calculateRentTotal,
  defaultDateRange,
  preferredPlanCodeForDays,
  PLAN_LABELS,
  type CalculatorCampaign,
  type CalculatorPlan,
  type PlanCode,
} from './rentCalculator';

export interface FilterApplyResult {
  features: PropertyFeature[];
  /** stay モードで総額を計算できず除外した件数 */
  excludedUnestimable: number;
}

export function monthlyTotalYen(props: PropertyFeature['properties']): number {
  return props.min_plan_total || (props.min_daily_rent || 0) * 30;
}

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

/** Build stay estimate via shared rent calculator (same as detail simulator). */
export function computeStayEstimate(
  props: PropertyFeature['properties'],
  checkIn: string,
  checkOut: string,
): StayEstimateSummary {
  const plans = (props.rent_plans || []) as CalculatorPlan[];
  const campaigns = (props.campaigns || []) as CalculatorCampaign[];
  const r = calculateRentTotal({ checkIn, checkOut, plans, campaigns });
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
  const code = r.selectedPlanCode as PlanCode;
  return {
    ok: true,
    stayDays: r.stayDays,
    stayTotalYen: r.grandTotal,
    rentDailyYen: r.breakdown.rentDaily,
    selectedPlanCode: code,
    usedFallback: r.usedFallback,
    planLabel: PLAN_LABELS[code] || r.selectedPlan.plan_name,
  };
}

export function createDefaultMapFilters(today: Date = new Date()): MapFilters {
  const range = defaultDateRange(today);
  return {
    ...DEFAULT_MAP_FILTERS,
    maxPrice: STAY_PRICE_UNLIMITED,
    priceMode: 'stay',
    checkIn: range.checkIn,
    checkOut: range.checkOut,
    sortBy: 'price_asc',
  };
}

function datesValid(checkIn: string, checkOut: string): boolean {
  if (!checkIn || !checkOut) return false;
  return checkIn <= checkOut;
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

  if (filters.searchQuery) {
    const q = filters.searchQuery.toLowerCase();
    const haystack = [
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
    if (!haystack.includes(q)) return false;
  }

  if (filters.boundsEnabled && mapBounds) {
    const coords = feat.geometry?.coordinates;
    if (coords && coords.length >= 2) {
      const [lng, lat] = coords;
      const [swLat, swLng] = mapBounds.southWest;
      const [neLat, neLng] = mapBounds.northEast;
      if (lat < swLat || lat > neLat || lng < swLng || lng > neLng) {
        return false;
      }
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
    const summary = (props.feature_summary || '').toLowerCase();
    for (const featName of filters.requiredFeatures) {
      if (!summary.includes(featName.toLowerCase())) return false;
    }
  }

  return true;
}

function sortFeatures(
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
      case 'score':
      default: {
        const scoreDiff = (pb.total_score || 0) - (pa.total_score || 0);
        if (scoreDiff !== 0) return scoreDiff;
        return priceForSort(pa, filters) - priceForSort(pb, filters);
      }
    }
  });
  return sorted;
}

/**
 * Enrich features with stay_estimate when in stay mode, filter, sort.
 * Unestimable properties in stay mode are excluded (counted in excludedUnestimable).
 */
export function applyMapFilters(
  rawGeojsonData: PropertyGeoJSON | null,
  filters: MapFilters,
  mapBounds: BoundsData | null,
): FilterApplyResult {
  if (!rawGeojsonData?.features) {
    return { features: [], excludedUnestimable: 0 };
  }

  const stayActive =
    filters.priceMode === 'stay' && datesValid(filters.checkIn, filters.checkOut);

  let excludedUnestimable = 0;
  const prepared: PropertyFeature[] = [];

  for (const feat of rawGeojsonData.features) {
    if (stayActive) {
      const estimate = computeStayEstimate(
        feat.properties,
        filters.checkIn,
        filters.checkOut,
      );
      if (!estimate.ok || estimate.stayTotalYen == null) {
        excludedUnestimable += 1;
        continue;
      }
      prepared.push({
        ...feat,
        properties: {
          ...feat.properties,
          stay_estimate: estimate,
        },
      });
    } else {
      // catalog or invalid dates: strip stay_estimate
      const { stay_estimate: _drop, ...rest } = feat.properties;
      prepared.push({
        ...feat,
        properties: { ...rest, stay_estimate: null },
      });
    }
  }

  const matched = prepared.filter((feat) => matchesMapFilters(feat, filters, mapBounds));
  return {
    features: sortFeatures(matched, filters.sortBy, filters),
    excludedUnestimable,
  };
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

/** Stay length + preferred plan band label (for sidebar summary). */
export function stayBandSummary(checkIn: string, checkOut: string): string | null {
  const days = calcStayDays(checkIn, checkOut);
  if (days == null) return null;
  const band = preferredPlanCodeForDays(days);
  return `${days}日 · ${PLAN_LABELS[band]}`;
}
