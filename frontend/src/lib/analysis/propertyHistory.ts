import type { PriceHistoryPoint } from '../../types.ts';

/** スナップショット1点から割引後日額を取り出す(欠損/非数は null) */
export function parseDaily(p: PriceHistoryPoint): number | null {
  const v = p.min_discounted_daily_rent_yen;
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

// 日付整形は lib/format 正本から(既存 import 互換のため再export)
export { formatDate } from '../format.ts';

/** 履歴の末尾2点から最新値と前回比差分を算出(有効点が2点未満なら null) */
export function priceDeltaFromHistory(history: PriceHistoryPoint[]): {
  delta: number;
  latest: number;
  previous: number;
} | null {
  const withDaily = history
    .map((p) => ({ at: p.scraped_at, daily: parseDaily(p) }))
    .filter((x): x is { at: string; daily: number } => x.daily != null);
  if (withDaily.length < 2) return null;
  const previous = withDaily[withDaily.length - 2].daily;
  const latest = withDaily[withDaily.length - 1].daily;
  return { delta: latest - previous, latest, previous };
}

/** チャート描画用の点。ts はミリ秒、diff は前回比(最初の点は null) */
export interface HistoryChartPoint {
  scraped_at: string;
  ts: number;
  daily: number;
  diff: number | null;
}

/**
 * price_history をチャート描画用の点列に変換する。
 * parseDaily で null の点を除外し、破損値ガードの漏れに備えて daily <= 0 も防御的に除外。
 * 戻り値は scraped_at 昇順にソートする。
 */
export function toHistoryChartPoints(history: PriceHistoryPoint[]): HistoryChartPoint[] {
  const valid = history
    .map((p) => ({ scraped_at: p.scraped_at, daily: parseDaily(p) }))
    .filter((x): x is { scraped_at: string; daily: number } => x.daily != null && x.daily > 0);
  valid.sort((a, b) => new Date(a.scraped_at).getTime() - new Date(b.scraped_at).getTime());
  return valid.map((x, i) => ({
    scraped_at: x.scraped_at,
    ts: new Date(x.scraped_at).getTime(),
    daily: x.daily,
    diff: i === 0 ? null : x.daily - valid[i - 1].daily,
  }));
}

/** 値が変わった遷移の一覧(新しい順) */
export interface PriceChangeEvent {
  scraped_at: string;
  /** 直前の値 */
  from: number;
  /** 変動後の値 */
  to: number;
  /** 差分(to - from) */
  delta: number;
  /** 変動率(%)。小数第2位で丸め */
  pct: number;
}

/** diff != 0 の点から価格変動イベントを抽出する(新しい順) */
export function extractChangeEvents(points: HistoryChartPoint[]): PriceChangeEvent[] {
  return points
    .filter((p) => p.diff != null && p.diff !== 0)
    .map((p) => {
      const delta = p.diff as number;
      const from = p.daily - delta;
      return {
        scraped_at: p.scraped_at,
        from,
        to: p.daily,
        delta,
        pct: Math.round((delta / from) * 1000) / 10,
      };
    })
    .reverse();
}

/** 系列のサマリ。points は昇順前提 */
export interface HistorySummary {
  count: number;
  min: number;
  /** 最安値の取得日時(scraped_at) */
  minAt: string;
  max: number;
  /** 最高値の取得日時(scraped_at) */
  maxAt: string;
  first: number;
  last: number;
}

/** 系列の最安/最高/最初/最終を集計する(空配列なら null) */
export function summarizeHistory(points: HistoryChartPoint[]): HistorySummary | null {
  if (points.length === 0) return null;
  let min = points[0].daily;
  let minAt = points[0].scraped_at;
  let max = points[0].daily;
  let maxAt = points[0].scraped_at;
  for (const p of points) {
    if (p.daily < min) {
      min = p.daily;
      minAt = p.scraped_at;
    }
    if (p.daily > max) {
      max = p.daily;
      maxAt = p.scraped_at;
    }
  }
  return {
    count: points.length,
    min,
    minAt,
    max,
    maxAt,
    first: points[0].daily,
    last: points[points.length - 1].daily,
  };
}
