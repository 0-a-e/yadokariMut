/**
 * 分析 API (/api/analysis/*) のクライアント。
 * 戻り値型は生成 schema (openapi-typescript) 由来。
 */
import type { PriceTrendResponse } from '../../types.ts';
import { fetchJson } from './client.ts';

/** GET /api/analysis/price-trend — 価格変動の日次集計(全プロバイダ分) */
export async function fetchPriceTrend(
  days: number,
  prefectureName?: string | null,
): Promise<PriceTrendResponse> {
  let url = `/api/analysis/price-trend?days=${days}`;
  if (prefectureName) {
    url += `&prefecture_name=${encodeURIComponent(prefectureName)}`;
  }
  return fetchJson<PriceTrendResponse>(url);
}
