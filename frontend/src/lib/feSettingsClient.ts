/**
 * バックエンド保存のフロントエンド設定クライアント(GET/POST /api/fe-settings)。
 *
 * - /api 以下は同一オリジン(global fetch は accessAuth.ts のガード付きラッパーが
 *   セッション切れを検出する)なので素の fetch を使う
 * - GET は起動時の既定値読み込み用。失敗時は EMPTY_FE_SETTINGS
 *   (= すべてカタログ既定にフォールバック)を返し、起動をブロックしない
 * - POST は部分マージ保存(null 送信でその保存済みキーを削除)。失敗時は throw
 */
import { EMPTY_FE_SETTINGS, type FeSettings } from './feSettings';

const FE_SETTINGS_URL = '/api/fe-settings';

async function parseSettings(res: Response): Promise<FeSettings> {
  const data = (await res.json()) as FeSettings | null;
  if (!data || typeof data !== 'object') return EMPTY_FE_SETTINGS;
  return {
    layers: data.layers ?? {},
    global: data.global ?? {},
  };
}

/** 保存済みのフロントエンド設定を取得する。失敗時は EMPTY_FE_SETTINGS。 */
export async function fetchFeSettings(): Promise<FeSettings> {
  try {
    const res = await fetch(FE_SETTINGS_URL);
    if (!res.ok) return EMPTY_FE_SETTINGS;
    return await parseSettings(res);
  } catch {
    return EMPTY_FE_SETTINGS;
  }
}

/** 部分マージ保存(update に無いキーは触らない / null は削除)。失敗時は throw。 */
export async function postFeSettings(update: FeSettings): Promise<FeSettings> {
  const res = await fetch(FE_SETTINGS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    let detail = `POST ${FE_SETTINGS_URL} failed: ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* ignore body parse errors */
    }
    throw new Error(detail);
  }
  return parseSettings(res);
}
