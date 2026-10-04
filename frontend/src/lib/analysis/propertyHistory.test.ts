import { describe, expect, it } from 'vitest';
import type { PriceHistoryPoint } from '../types';
import {
  extractChangeEvents,
  parseDaily,
  priceDeltaFromHistory,
  summarizeHistory,
  toHistoryChartPoints,
} from './propertyHistory.ts';

/** テスト用の1点を組み立てる(欠損値は min_discounted_daily_rent_yen: null で表現) */
const pt = (scraped_at: string, daily: number | null): PriceHistoryPoint => ({
  scraped_at,
  min_discounted_daily_rent_yen: daily,
});

/** 変動2回を含む正常系列(わざと昇順でない順序で用意し、ソートを検証する) */
const normalSeries: PriceHistoryPoint[] = [
  pt('2026-09-01T10:00:00Z', 6000),
  pt('2026-09-05T10:00:00Z', 5400), // -600 (-10%)
  pt('2026-09-03T10:00:00Z', 6000), // 順不同(ソート対象)
  pt('2026-09-10T10:00:00Z', 5700), // +300 (+5.6%)
];

/** 正常系列を scraped_at 昇順に並べたもの */
const toSorted = (series: PriceHistoryPoint[]): PriceHistoryPoint[] =>
  [...series].sort((a, b) => a.scraped_at.localeCompare(b.scraped_at));

describe('parseDaily', () => {
  it('数値はそのまま返し、欠損/非数は null', () => {
    expect(parseDaily(pt('2026-09-01T10:00:00Z', 6000))).toBe(6000);
    expect(parseDaily({ scraped_at: 'x', min_discounted_daily_rent_yen: null })).toBeNull();
    expect(parseDaily({ scraped_at: 'x', min_discounted_daily_rent_yen: Number.NaN })).toBeNull();
    expect(parseDaily({ scraped_at: 'x' })).toBeNull();
  });
});

describe('toHistoryChartPoints', () => {
  it('正常系列: 昇順ソート・ミリ秒ts・前回比diffを付与する', () => {
    const points = toHistoryChartPoints(normalSeries);
    expect(points.map((p) => p.daily)).toEqual([6000, 6000, 5400, 5700]);
    expect(points.map((p) => p.scraped_at)).toEqual([
      '2026-09-01T10:00:00Z',
      '2026-09-03T10:00:00Z',
      '2026-09-05T10:00:00Z',
      '2026-09-10T10:00:00Z',
    ]);
    // 最初の点の diff は null、以降は直前点との差分
    expect(points.map((p) => p.diff)).toEqual([null, 0, -600, 300]);
    // ts は scraped_at をミリ秒にしたもの
    expect(points[0].ts).toBe(new Date('2026-09-01T10:00:00Z').getTime());
  });

  it('1点のみ: diff は null', () => {
    const points = toHistoryChartPoints([pt('2026-09-01T10:00:00Z', 5000)]);
    expect(points).toHaveLength(1);
    expect(points[0]).toEqual({
      scraped_at: '2026-09-01T10:00:00Z',
      ts: new Date('2026-09-01T10:00:00Z').getTime(),
      daily: 5000,
      diff: null,
    });
  });

  it('空配列: 空配列を返す', () => {
    expect(toHistoryChartPoints([])).toEqual([]);
  });

  it('daily が null / 0 の点は除外する', () => {
    const points = toHistoryChartPoints([
      pt('2026-09-01T10:00:00Z', null),
      pt('2026-09-02T10:00:00Z', 0),
      pt('2026-09-03T10:00:00Z', 4000),
      pt('2026-09-04T10:00:00Z', 3500),
    ]);
    expect(points.map((p) => p.daily)).toEqual([4000, 3500]);
    // 除外後の最初の有効点を基準に diff が付く
    expect(points.map((p) => p.diff)).toEqual([null, -500]);
  });
});

describe('extractChangeEvents', () => {
  it('変動のあった遷移のみを新しい順に返す', () => {
    const points = toHistoryChartPoints(normalSeries);
    const events = extractChangeEvents(points);
    expect(events).toEqual([
      {
        scraped_at: '2026-09-10T10:00:00Z',
        from: 5400,
        to: 5700,
        delta: 300,
        pct: 5.6,
      },
      {
        scraped_at: '2026-09-05T10:00:00Z',
        from: 6000,
        to: 5400,
        delta: -600,
        pct: -10,
      },
    ]);
  });

  it('変動がなければ空配列', () => {
    const points = toHistoryChartPoints([
      pt('2026-09-01T10:00:00Z', 5000),
      pt('2026-09-02T10:00:00Z', 5000),
    ]);
    expect(extractChangeEvents(points)).toEqual([]);
  });

  it('1点のみ・空配列でも空配列', () => {
    expect(extractChangeEvents(toHistoryChartPoints([pt('2026-09-01T10:00:00Z', 5000)]))).toEqual(
      [],
    );
    expect(extractChangeEvents([])).toEqual([]);
  });
});

describe('summarizeHistory', () => {
  it('正常系列: 件数・最安/最高(と日時)・最初/最終を集計する', () => {
    const points = toHistoryChartPoints(normalSeries);
    expect(summarizeHistory(points)).toEqual({
      count: 4,
      min: 5400,
      minAt: '2026-09-05T10:00:00Z',
      max: 6000,
      maxAt: '2026-09-01T10:00:00Z',
      first: 6000,
      last: 5700,
    });
  });

  it('1点のみ: min/max/first/last が同一', () => {
    const points = toHistoryChartPoints([pt('2026-09-01T10:00:00Z', 5000)]);
    expect(summarizeHistory(points)).toEqual({
      count: 1,
      min: 5000,
      minAt: '2026-09-01T10:00:00Z',
      max: 5000,
      maxAt: '2026-09-01T10:00:00Z',
      first: 5000,
      last: 5000,
    });
  });

  it('空配列: null', () => {
    expect(summarizeHistory([])).toBeNull();
  });
});

describe('priceDeltaFromHistory', () => {
  it('配列末尾2点から最新値と前回比を返す(ソートはしない・与えられた順序のまま)', () => {
    expect(priceDeltaFromHistory(normalSeries)).toEqual({
      delta: -300, // 5700 - 6000
      latest: 5700,
      previous: 6000, // 与えられた配列順での末尾から2点目(09-03 の 6000)
    });
    // 昇順に並べた配列を渡せば時系列上の直前点との比較になる
    expect(priceDeltaFromHistory(toSorted(normalSeries))).toEqual({
      delta: 300,
      latest: 5700,
      previous: 5400,
    });
  });

  it('有効点が2点未満なら null', () => {
    expect(priceDeltaFromHistory([])).toBeNull();
    expect(priceDeltaFromHistory([pt('2026-09-01T10:00:00Z', 5000)])).toBeNull();
    expect(priceDeltaFromHistory([pt('2026-09-01T10:00:00Z', null)])).toBeNull();
  });
});
