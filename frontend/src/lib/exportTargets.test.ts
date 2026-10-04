import { describe, expect, it } from 'vitest';
import type { PropertyFeature } from '../types.ts';
import {
  exportFilename,
  featuresToIds,
  selectExportFeatures,
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
      room_id: `room-${id}`,
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
