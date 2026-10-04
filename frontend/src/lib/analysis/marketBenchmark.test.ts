import { describe, expect, it } from 'vitest';
import {
  buildBins,
  buildPeerSet,
  linearRegression,
  metricValue,
  METRICS,
  numericSummary,
  percentileRank,
} from './marketBenchmark.ts';
import type { MarketMetric } from './marketBenchmark.ts';
import type { PropertyFeature, PropertyProperties } from '../../types.ts';

/** テスト用の最小 PropertyFeature を生成(未指定フィールドは神奈川県横浜市 1R の既定値) */
const feature = (id: number, overrides: Partial<PropertyProperties> = {}): PropertyFeature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [139.63, 35.45] },
  properties: {
    id,
    room_id: `room-${id}`,
    title: `物件${id}`,
    detail_url: `https://example.com/${id}`,
    address: '神奈川県横浜市',
    prefecture_name: '神奈川県',
    municipality: '横浜市',
    layout: '1R',
    area_m2: 20,
    min_daily_rent: 3000,
    min_plan_total: null,
    min_plan_name: null,
    min_walk_minutes: 8,
    thumbnail_url: null,
    images: [],
    total_score: 0,
    shortlist_status: 'none',
    is_active: true,
    access_summary: '',
    feature_summary: '',
    station_summary: '',
    rent_plans: [],
    campaigns: [],
    ...overrides,
  },
});

describe('buildPeerSet', () => {
  it('同市区町村×間取りが5件以上なら municipality スコープを使う', () => {
    const self = feature(0);
    const peers = [
      feature(1),
      feature(2),
      feature(3, { min_daily_rent: 3200 }),
      feature(4, { min_daily_rent: 3400 }),
      feature(5, { min_daily_rent: 3600 }),
    ];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('municipality');
    expect(set.fallback).toBe(false);
    expect(set.groupLabel).toBe('横浜市 × 1R');
    // self 自身は含まない
    expect(set.peers.map((p) => p.properties.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it('市区町村が5件未満なら都道府県×間取りにフォールバックする', () => {
    const self = feature(0);
    const peers = [
      // 横浜市 1R は4件のみ
      feature(1),
      feature(2),
      feature(3),
      feature(4),
      // 同県の川崎市 1R を追加して県単位では6件
      feature(5, { municipality: '川崎市' }),
      feature(6, { municipality: '川崎市' }),
    ];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('prefecture');
    expect(set.fallback).toBe(true);
    expect(set.groupLabel).toBe('神奈川県 × 1R');
    expect(set.peers).toHaveLength(6);
  });

  it('is_active=false の物件はどちらのスコープでも除外する', () => {
    const self = feature(0);
    const peers = [
      feature(1),
      feature(2),
      feature(3),
      feature(4),
      // 5件目は掲載終了 → 実質4件でフォールバックする
      feature(5, { is_active: false }),
      feature(6, { municipality: '川崎市' }),
      feature(7, { municipality: '川崎市' }),
    ];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('prefecture');
    expect(set.fallback).toBe(true);
    expect(set.peers.map((p) => p.properties.id)).not.toContain(5);
  });

  it('self と異なる間取りの物件は除外する', () => {
    const self = feature(0);
    const peers = [
      feature(1, { layout: '1K' }),
      feature(2, { layout: '1K' }),
      feature(3),
      feature(4),
      feature(5),
      feature(6),
      feature(7),
    ];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('municipality');
    expect(set.peers.map((p) => p.properties.id)).toEqual([3, 4, 5, 6, 7]);
  });

  it('municipality が null のピアは市区町村スコープ外だが都道府県スコープでは許容する', () => {
    const self = feature(0);
    const peers = [
      feature(1, { municipality: null }),
      feature(2, { municipality: null }),
      feature(3, { municipality: null }),
      feature(4),
      // 市区町村スコープの候補は4件(null 除く)なのでフォールバック
      feature(5, { municipality: null }),
    ];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('prefecture');
    expect(set.fallback).toBe(true);
    expect(set.peers).toHaveLength(5);
  });

  it('municipality が null の self は最初から都道府県スコープになる(フォールバック扱いにしない)', () => {
    const self = feature(0, { municipality: null });
    const peers = [feature(1), feature(2), feature(3), feature(4), feature(5)];
    const set = buildPeerSet([self, ...peers], self);
    expect(set.scope).toBe('prefecture');
    expect(set.fallback).toBe(false);
    expect(set.groupLabel).toBe('神奈川県 × 1R');
    expect(set.peers).toHaveLength(5);
  });
});

describe('metricValue', () => {
  const cases: [MarketMetric, Partial<PropertyProperties>, number | null][] = [
    ['daily', { min_daily_rent: 3500 }, 3500],
    ['daily', { min_daily_rent: null }, null],
    ['daily', { min_daily_rent: 0 }, null],
    ['perSqm', { min_daily_rent: 2500, area_m2: 20 }, 125],
    ['perSqm', { min_daily_rent: 2500, area_m2: null }, null],
    ['perSqm', { min_daily_rent: null, area_m2: 20 }, null],
    ['perSqm', { min_daily_rent: 0, area_m2: 20 }, null], // 0除算・無効値ガード
    ['perSqm', { min_daily_rent: 2500, area_m2: 0 }, null],
    ['area', { area_m2: 25.5 }, 25.5],
    ['area', { area_m2: null }, null],
    ['walk', { min_walk_minutes: 7 }, 7],
    ['walk', { min_walk_minutes: 0 }, null],
    ['walk', { min_walk_minutes: null }, null],
  ];
  it.each(cases)('metric=%s のとき %j は %s を返す', (metric, overrides, expected) => {
    expect(metricValue(feature(1, overrides), metric)).toBe(expected);
  });
});

describe('numericSummary', () => {
  it('奇数件のとき中央値は中央の要素', () => {
    expect(numericSummary([5, 1, 3, 2, 4])).toEqual({
      count: 5,
      min: 1,
      p25: 2,
      median: 3,
      p75: 4,
      max: 5,
    });
  });

  it('偶数件のとき中央値は中間2点の平均', () => {
    const s = numericSummary([1, 2, 3, 4]);
    expect(s).not.toBeNull();
    expect(s?.median).toBe(2.5);
    expect(s?.p25).toBe(1.75); // 線形補間
    expect(s?.p75).toBe(3.25);
    expect(s?.min).toBe(1);
    expect(s?.max).toBe(4);
    expect(s?.count).toBe(4);
  });

  it('空配列・非数のみのときは null', () => {
    expect(numericSummary([])).toBeNull();
    expect(numericSummary([Number.NaN, Number.POSITIVE_INFINITY])).toBeNull();
  });
});

describe('percentileRank', () => {
  it('最安値なら 0', () => {
    expect(percentileRank([10, 20, 30], 5)).toBe(0);
  });

  it('最高値(同値なし)なら 100', () => {
    expect(percentileRank([10, 20], 30)).toBe(100);
  });

  it('同値は上位側に数える', () => {
    // 20 より安いのは 10 の1件 / 全3件
    expect(percentileRank([10, 20, 20], 20)).toBeCloseTo(33.33, 1);
    expect(percentileRank([10, 10], 10)).toBe(0);
  });

  it('ピアが空なら null', () => {
    expect(percentileRank([], 10)).toBeNull();
  });
});

describe('linearRegression', () => {
  it('2点なら厳密な直線を返す', () => {
    expect(linearRegression([{ x: 0, y: 1 }, { x: 2, y: 5 }])).toEqual({
      slope: 2,
      intercept: 1,
    });
  });

  it('3点以上なら最小二乗の近似直線を返す', () => {
    expect(linearRegression([{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }])).toEqual({
      slope: 1,
      intercept: 0,
    });
    const r = linearRegression([{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 0 }]);
    expect(r).not.toBeNull();
    expect(r?.slope).toBe(0);
    expect(r?.intercept).toBeCloseTo(1 / 3, 6);
  });

  it('点が2点未満・x が全て同一のときは null', () => {
    expect(linearRegression([])).toBeNull();
    expect(linearRegression([{ x: 1, y: 2 }])).toBeNull();
    expect(linearRegression([{ x: 3, y: 1 }, { x: 3, y: 2 }])).toBeNull();
  });
});

describe('buildBins', () => {
  it('self の所属ビンを特定する', () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
    const { bins, selfBinIndex } = buildBins(values, 5);
    // 幅1のビンが12個(1〜12, 13)
    expect(bins).toHaveLength(12);
    expect(bins[0].from).toBe(1);
    expect(bins[0].to).toBe(2);
    expect(bins.every((b) => b.count === 1)).toBe(true);
    expect(selfBinIndex).toBe(4);
    expect(bins[4].hasSelf).toBe(true);
    expect(bins.filter((b) => b.hasSelf)).toHaveLength(1);
  });

  it('selfValue が null のときは強調ビンを作らない', () => {
    const { bins, selfBinIndex } = buildBins([1, 2, 3], null);
    expect(selfBinIndex).toBeNull();
    expect(bins.every((b) => !b.hasSelf)).toBe(true);
  });

  it('self がピアの範囲外のときは範囲を広げて強調する', () => {
    const { bins, selfBinIndex } = buildBins([10, 20], 100);
    expect(selfBinIndex).not.toBeNull();
    const selfBin = selfBinIndex != null ? bins[selfBinIndex] : null;
    expect(selfBin?.hasSelf).toBe(true);
    expect(selfBin?.count).toBe(0); // self は件数に数えない
    // 10, 20, 100 がそれぞれ別ビンに収まる
    expect(bins.find((b) => b.count === 1)).toBeDefined();
  });

  it('値が全て同一のときは1ビンに収める', () => {
    const { bins, selfBinIndex } = buildBins([500, 500, 500], 500);
    expect(bins).toHaveLength(1);
    expect(bins[0].count).toBe(3);
    expect(selfBinIndex).toBe(0);
    expect(bins[0].hasSelf).toBe(true);
  });

  it('空配列のときはビンを作らない', () => {
    expect(buildBins([], null)).toEqual({ bins: [], selfBinIndex: null });
  });
});

describe('METRICS', () => {
  it('4指標が揃っており formatValue が単位付きで整形する', () => {
    expect(Object.keys(METRICS)).toEqual(['daily', 'perSqm', 'area', 'walk']);
    expect(METRICS.daily.formatValue(3500)).toBe('3,500円');
    expect(METRICS.perSqm.formatValue(125.5)).toBe('125.5円/㎡');
    expect(METRICS.area.formatValue(25.44)).toBe('25.4㎡');
    expect(METRICS.walk.formatValue(7)).toBe('7分');
  });
});
