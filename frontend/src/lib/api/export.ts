/**
 * エクスポート API (/api/export/*) のクライアント。
 * KML はバイナリ応答のため Blob で返す。
 */
import { fetchApi } from './client.ts';

/** POST /api/export/kml — 物件 ID 群を Google Earth 用 KML として取得 */
export async function postKmlExport(ids: number[]): Promise<Blob> {
  const res = await fetchApi('/api/export/kml', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  return res.blob();
}
