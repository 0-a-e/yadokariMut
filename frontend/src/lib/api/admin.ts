/**
 * 管理 API (/api/admin/*) のクライアント。
 *
 * 戻り値型は生成 schema (openapi-typescript) 由来。POST 設定系のボディ型は
 * BE が意図的に未モデル化(部分マージ + null=既定へ戻す)のため types.ts の
 * 手書き契約(ScrapeSettingsUpdate / RotationSettingsUpdate)を使う。
 * エラーは client.ts の ApiError(detail 抽出付き)として投げる。
 */
import type {
  AdminStatsResponse,
  RotationSettingsUpdate,
  ScrapeSettingsUpdate,
} from '../../types.ts';
import { fetchJson, postJson, type Schemas } from './client.ts';

/** AdminStatsResponse の正本は types.ts(生成 schema のエイリアス面)。旧 import 経路互換のため再 export */
export type { AdminStatsResponse };
export type AdminSourcesResponse = Schemas['AdminSourcesResponse'];
export type RotationStatusResponse = Schemas['RotationStatusResponse'];
export type ScrapeSettingsResponse = Schemas['ScrapeSettingsResponse'];
export type RotationSettingsResponse = Schemas['RotationSettingsResponse'];
export type ScrapeStartResponse = Schemas['ScrapeStartResponse'];
export type TaskStartResponse = Schemas['TaskStartResponse'];
export type RotationRunStartResponse = Schemas['RotationRunStartResponse'];

/** POST /api/admin/scrape のボディ(BE ScrapeRequest ミラー) */
export type ScrapeRequestBody = Schemas['ScrapeRequest'];

/** GET /api/admin/status — タスク状態・直近run・DB統計・転送量 */
export function fetchAdminStatus(): Promise<AdminStatsResponse> {
  return fetchJson<AdminStatsResponse>('/api/admin/status');
}

/** GET /api/admin/sources — ソース一覧(カタログ + 県別 DB/実行状態) */
export function fetchAdminSources(): Promise<AdminSourcesResponse> {
  return fetchJson<AdminSourcesResponse>('/api/admin/sources');
}

/** GET /api/admin/rotation — 県ローテーションの状態 */
export function fetchRotationStatus(): Promise<RotationStatusResponse> {
  return fetchJson<RotationStatusResponse>('/api/admin/rotation');
}

/** GET /api/admin/scrape-settings — ソース別スクレイプ設定(実効値) */
export function fetchScrapeSettings(): Promise<ScrapeSettingsResponse> {
  return fetchJson<ScrapeSettingsResponse>('/api/admin/scrape-settings');
}

/** POST /api/admin/scrape-settings — 部分マージ保存(null で既定へ戻す) */
export function postScrapeSettings(
  update: ScrapeSettingsUpdate,
): Promise<ScrapeSettingsResponse> {
  return postJson<ScrapeSettingsResponse>('/api/admin/scrape-settings', update);
}

/** GET /api/admin/rotation-settings — ソース別ローテーション設定(実効値) */
export function fetchRotationSettings(): Promise<RotationSettingsResponse> {
  return fetchJson<RotationSettingsResponse>('/api/admin/rotation-settings');
}

/** POST /api/admin/rotation-settings — 部分マージ保存(null で既定へ戻す) */
export function postRotationSettings(
  update: RotationSettingsUpdate,
): Promise<RotationSettingsResponse> {
  return postJson<RotationSettingsResponse>('/api/admin/rotation-settings', update);
}

/** POST /api/admin/scrape — 再スクレイプをバックグラウンド起動 */
export function startScrape(body: ScrapeRequestBody): Promise<ScrapeStartResponse> {
  return postJson<ScrapeStartResponse>('/api/admin/scrape', body);
}

/** POST /api/admin/geocode?limit=N — 未解決住所のジオコーディングを起動 */
export function startGeocode(limit: number): Promise<TaskStartResponse> {
  return postJson<TaskStartResponse>(`/api/admin/geocode?limit=${limit}`, undefined);
}

/** POST /api/admin/rotation/run — 県ローテーション 1 バッチを手動実行 */
export function startRotationRun(source: string): Promise<RotationRunStartResponse> {
  return postJson<RotationRunStartResponse>('/api/admin/rotation/run', { source });
}
