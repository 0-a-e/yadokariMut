/**
 * フロントエンド設定クライアント(GET/POST /api/fe-settings)。
 *
 * - /api 以下は同一オリジン(global fetch は accessAuth.ts のガード付きラッパーが
 *   セッション切れを検出する)。転送は lib/api/client の共通ラッパ経由
 * - GET は起動時の既定値読み込み用。失敗時は EMPTY_FE_SETTINGS
 *   (= すべてカタログ既定にフォールバック)を返し、起動をブロックしない
 * - POST は部分マージ保存(null 送信でその保存済みキーを削除)。失敗時は throw
 *   (!ok は ApiError。message は detail 文字列を優先)
 */
import { EMPTY_FE_SETTINGS, type FeSettings } from '../feSettings.ts';
import { fetchJson, postJson } from './client.ts';

const FE_SETTINGS_URL = '/api/fe-settings';

function parseSettings(data: unknown): FeSettings {
  if (!data || typeof data !== 'object') return EMPTY_FE_SETTINGS;
  const d = data as Partial<FeSettings>;
  return {
    layers: d.layers ?? {},
    global: d.global ?? {},
  };
}

/** 保存済みのフロントエンド設定を取得する。失敗時は EMPTY_FE_SETTINGS。 */
export async function fetchFeSettings(): Promise<FeSettings> {
  try {
    return parseSettings(await fetchJson<FeSettings>(FE_SETTINGS_URL));
  } catch {
    return EMPTY_FE_SETTINGS;
  }
}

/** 部分マージ保存(update に無いキーは触らない / null は削除)。失敗時は throw。 */
export async function postFeSettings(update: FeSettings): Promise<FeSettings> {
  const data = await postJson<FeSettings>(FE_SETTINGS_URL, update);
  return parseSettings(data);
}
