/**
 * GeoJSON 取得クライアント。
 *
 * - /api/geojson: BE 応答(FeatureCollection)。NDJSON ストリーム版は
 *   lib/geojsonStream.ts (streamGeojson) が担当し、失敗時のフォールバック先
 * - /map.geojson: public/ 配下のローカルフォールバックファイル
 */
import type { PropertyGeoJSON } from '../../types.ts';
import { fetchApi } from './client.ts';

/** GET /api/geojson — 物件 FeatureCollection を一括取得 */
export async function fetchGeojsonBulk(): Promise<PropertyGeoJSON> {
  const res = await fetchApi('/api/geojson');
  return (await res.json()) as PropertyGeoJSON;
}

/**
 * GET /map.geojson — ローカルフォールバックファイルを取得。
 * 旧実装同士、404 等 !ok は null を返し(呼び出し側で静かにスキップ)、
 * network error のみ例外として投げる。
 */
export async function fetchLocalGeojson(): Promise<PropertyGeoJSON | null> {
  const res = await fetch('/map.geojson');
  if (!res.ok) return null;
  return (await res.json()) as PropertyGeoJSON;
}
