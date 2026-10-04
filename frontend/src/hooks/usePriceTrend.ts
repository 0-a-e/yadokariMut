import { useEffect, useState } from 'react';
import type { PriceTrendResponse } from '../types.ts';
import { fetchPriceTrend } from '../lib/api/analysis.ts';

export interface UsePriceTrendResult {
  data: PriceTrendResponse | null;
  loading: boolean;
  error: string | null;
}

const ERROR_MESSAGE = '接続エラー: 価格変動データを取得できませんでした。';

/**
 * モジュールスコープのキャッシュ。同一パラメータのリクエストは Promise ごと共有し、
 * コンポーネントを跨ぐ再fetchを防ぐ(市場全体タブ ⇔ 物件タブの往復で再取得しない目的)。
 * 失敗した Promise はキャッシュしない(キャッシュから除去し、後続マウントで再試行可能にする)。
 */
const cache = new Map<string, Promise<PriceTrendResponse>>();

/**
 * GET /api/analysis/price-trend を取得する hook。
 * prefecture_name を渡すと県で絞り込んだ系列を要求する。
 */
export function usePriceTrend(days: number, prefectureName?: string | null): UsePriceTrendResult {
  const [data, setData] = useState<PriceTrendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const key = `${days}|${prefectureName ?? ''}`;
    let promise = cache.get(key);
    if (!promise) {
      promise = fetchPriceTrend(days, prefectureName);
      cache.set(key, promise);
      promise.catch(() => cache.delete(key));
    }
    promise.then(
      (json) => {
        if (cancelled) return;
        setData(json);
        setError(null);
        setLoading(false);
      },
      (e) => {
        // 失敗は reject を握り潰さず、既存タブと同じ文言のエラーとして返す
        console.error(e);
        if (!cancelled) {
          setError(ERROR_MESSAGE);
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [days, prefectureName]);

  return { data, loading, error };
}
