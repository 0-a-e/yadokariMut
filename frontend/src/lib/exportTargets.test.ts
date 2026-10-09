import { describe, expect, it } from 'vitest';
import type { BuildingFeature, BuildingUnit, PropertyFeature } from '../types.ts';
import {
  exportFilename,
  featuresToIds,
  selectExportFeatures,
  selectExportUnits,
  unitsToIds,
} from './exportTargets.ts';

function feat(
  id: number,
  opts: { isActive?: boolean; coords?: [number, number] } = {},
): PropertyFeature {
  return {
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: opts.coords ?? [139.7, 35.66], // [lng, lat]
    },
    properties: {
      id,
      title: `物件${id}`,
      detail_url: 'https://example.test/',
      address: '東京都',
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
      feature_categories: [],
      station_summary: '',
      rent_plans: [],
      campaigns: [],
      is_active: opts.isActive ?? true,
    },
  };
}

describe('selectExportFeatures', () => {
  const all = [
    feat(1, { isActive: true }),
    feat(2, { isActive: false }),
    feat(3, { isActive: true }),
  ];
  const filtered = [all[0], all[1]];

  it('filtered スコープは表示中リストを全件返す', () => {
    const got = selectExportFeatures(all, filtered, {
      scope: 'filtered',
      includeInactive: true,
    });
    expect(got.map((f) => f.properties.id)).toEqual([1, 2]);
  });

  it('includeInactive=false は掲載終了を除く', () => {
    expect(
      selectExportFeatures(all, filtered, {
        scope: 'filtered',
        includeInactive: false,
      }).map((f) => f.properties.id),
    ).toEqual([1]);
    expect(
      selectExportFeatures(all, filtered, {
        scope: 'all',
        includeInactive: false,
      }).map((f) => f.properties.id),
    ).toEqual([1, 3]);
  });

  it('all スコープは全物件を元リスト順で返す', () => {
    const got = selectExportFeatures(all, filtered, {
      scope: 'all',
      includeInactive: true,
    });
    expect(got.map((f) => f.properties.id)).toEqual([1, 2, 3]);
  });
});

describe('featuresToIds', () => {
  it('properties.id の配列を返す', () => {
    const feats = [feat(5), feat(2)];
    expect(featuresToIds(feats)).toEqual([5, 2]);
  });
});

describe('exportFilename', () => {
  it('yadokari_YYYYMMDD_HHMM.kml 形式で返す', () => {
    const name = exportFilename(new Date(2026, 8, 15, 9, 5)); // 2026-09-15 09:05
    expect(name).toBe('yadokari_20260915_0905.kml');
  });
});

// ── 建物版(Phase B2-δ §4.7) ──

function exportUnit(id: number, opts: { isActive?: boolean; status?: string | null } = {}): BuildingUnit {
  return {
    id,
    title: `Room${id}`,
    total_score: 0,
    is_active: opts.isActive ?? true,
    shortlist_status: (opts.status ?? null) as BuildingUnit['shortlist_status'],
    access_summary: [],
    images: [],
    feature_summary: '',
    feature_categories: [],
    rent_plans: [],
    campaigns: [],
  };
}

function exportBuilding(id: number, units: BuildingUnit[]): BuildingFeature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [139.7, 35.6] },
    properties: {
      id,
      kind: 'building',
      name: `Building${id}`,
      address: '東京都',
      prefecture_name: '東京都',
      municipality: '多摩市',
      is_active: units.some((u) => u.is_active),
      units_count: units.length,
      active_units_count: units.filter((u) => u.is_active).length,
      source_sites: ['unionmonthly'],
      building_names: [],
      feature_categories: [],
      has_campaign: false,
      access_summary: [],
      station_summary: '',
      thumbnail_url: null,
      units,
    },
  };
}

describe('selectExportUnits', () => {
  // u1: 掲載中 / u2: 非掲載+saved / u3: 非掲載+手付かず(BE units には本来載らない防御対象)
  const b1 = exportBuilding(1, [
    exportUnit(11),
    exportUnit(12, { isActive: false, status: 'saved' }),
    exportUnit(13, { isActive: false }),
  ]);
  const b2 = exportBuilding(2, [exportUnit(21, { isActive: false, status: 'hide' }), exportUnit(22)]);
  const allBuildings = [b1, b2];

  it('includeInactive=true は可視部屋全部(is_active または saved/hide/reject)を返す', () => {
    expect(selectExportUnits(allBuildings, true).map((u) => u.id)).toEqual([
      11, 12, 21, 22,
    ]);
  });

  it('includeInactive=false は掲載終了(is_active=false)を除く', () => {
    expect(selectExportUnits(allBuildings, false).map((u) => u.id)).toEqual([11, 22]);
  });

  it('建物順・units 順は元リスト順を維持する', () => {
    const got = selectExportUnits([b2, b1], true).map((u) => u.id);
    expect(got).toEqual([21, 22, 11, 12]);
  });
});

describe('unitsToIds', () => {
  it('units の id 配列を返す', () => {
    expect(unitsToIds([exportUnit(5), exportUnit(2)])).toEqual([5, 2]);
  });
});
