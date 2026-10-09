import { useEffect, useState } from 'react';
import type { PropertyDetailResponse } from '../lib/api/properties.ts';
import { fetchPropertyDetail } from '../lib/api/properties.ts';

export interface UsePropertyDetailResult {
  /** propertyId と一致する詳細応答のみ返す(id 切替の過渡では null) */
  detail: PropertyDetailResponse | null;
  loading: boolean;
  error: string | null;
}

/**
 * モジュールスコープのPromiseキャッシュ。同一物件の詳細を DetailPanel ⇔ AnalysisModal
 * (物件価格タブ)間で共有し、二重fetch・タブ往復の再fetchを防ぐ。
 * 失敗したPromiseはキャッシュしない(usePriceTrend と同方針)。
 */
const cache = new Map<string, Promise<PropertyDetailResponse>>();

export function usePropertyDetail(
  propertyId: number | null | undefined,
): UsePropertyDetailResult {
  const [loaded, setLoaded] = useState<{ id: string; detail: PropertyDetailResponse } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = propertyId != null ? String(propertyId) : null;

  useEffect(() => {
    if (key == null) {
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    let promise = cache.get(key);
    if (!promise) {
      promise = fetchPropertyDetail(key);
      cache.set(key, promise);
      promise.catch(() => cache.delete(key));
    }
    promise.then(
      (json) => {
        if (cancelled) return;
        setLoaded({ id: key, detail: json });
        setLoading(false);
      },
      (e) => {
        console.error('property detail fetch failed', e);
        if (!cancelled) {
          setError('詳細データの取得に失敗しました');
          setLoading(false);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key]);

  // 切替過渡(次物件のfetch中)で前物件のデータが漏れないよう照合して返す
  const detail = loaded && loaded.id === key ? loaded.detail : null;
  return { detail, loading, error };
}
