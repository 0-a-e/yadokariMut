/**
 * 建物 API (/api/buildings/*) のクライアント。
 * 戻り値型は生成 schema (openapi-typescript) 由来。
 * エラーは client.ts の ApiError(detail 抽出付き)として投げる。
 */
import { postJson, type Schemas } from './client.ts';

export type BuildingShortlistUpdateResponse = Schemas['BuildingShortlistUpdateResponse'];
export type BuildingShortlistStatus = 'saved' | 'none';

/** POST /api/buildings/{buildingId}/shortlist — 建物ショートリスト(ブックマーク)更新 */
export function postBuildingShortlist(
  buildingId: number,
  status: BuildingShortlistStatus,
  comment?: string | null,
): Promise<BuildingShortlistUpdateResponse> {
  return postJson<BuildingShortlistUpdateResponse>(
    `/api/buildings/${buildingId}/shortlist`,
    { status, comment: comment ?? null },
  );
}
