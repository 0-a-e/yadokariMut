/**
 * 建物 GeoJSON 取得クライアント(Phase B2-α で部屋単位 /api/geojson から切替)。
 *
 * - /api/buildings/geojson: BE 応答(FeatureCollection・1 Feature = 1 建物 + units)。
 *   NDJSON ストリーム版は lib/geojsonStream.ts (streamBuildingGeojson) が担当し、
 *   失敗時のフォールバック先
 * - 旧 3 段目 /map.geojson(ローカル静的ファイル)は B2 承認(計画 §9-8)で廃止
 */
import type { BuildingGeoJSON } from '../../types.ts';
import { fetchApi } from './client.ts';

/** GET /api/buildings/geojson — 建物 FeatureCollection を一括取得 */
export async function fetchBuildingsGeojson(): Promise<BuildingGeoJSON> {
  const res = await fetchApi('/api/buildings/geojson');
  return (await res.json()) as BuildingGeoJSON;
}
