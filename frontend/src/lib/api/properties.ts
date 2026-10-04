/**
 * 物件 API (/api/properties/*) のクライアント。
 * 戻り値型は生成 schema (openapi-typescript) 由来。
 * エラーは client.ts の ApiError(detail 抽出付き)として投げる。
 */
import type { ShortlistStatus } from '../../types.ts';
import { fetchJson, postJson, type Schemas } from './client.ts';

export type PropertyDetailResponse = Schemas['PropertyDetailResponse'];
export type ShortlistUpdateResponse = Schemas['ShortlistUpdateResponse'];

/** GET /api/properties/{id} — 物件詳細(properties 行 + 子テーブル) */
export function fetchPropertyDetail(propertyId: number | string): Promise<PropertyDetailResponse> {
  return fetchJson<PropertyDetailResponse>(`/api/properties/${propertyId}`);
}

/** POST /api/properties/{id}/shortlist — ショートリスト状態・メモの更新 */
export function postShortlist(
  propertyId: number,
  status: ShortlistStatus,
  comment?: string | null,
): Promise<ShortlistUpdateResponse> {
  return postJson<ShortlistUpdateResponse>(`/api/properties/${propertyId}/shortlist`, {
    status,
    comment: comment ?? null,
  });
}
