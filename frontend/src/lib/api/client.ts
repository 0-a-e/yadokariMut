/**
 * lib/api 共通の fetch ラッパ。
 *
 * - /api 以下は同一オリジンへの素の fetch。グローバル fetch は accessAuth.ts
 *   のガード付きラッパーに差し替わっており、Cloudflare Access のセッション
 *   切れ(302)は SessionExpiredError としてここから透過的に投げられる
 *   (このガードは accessAuth.ts に置き続ける)
 * - !ok 応答は FastAPI の error body ({ detail: ... }) を取り出して
 *   ApiError に載せる。呼び出し側は apiErrorMessage() で旧実装と同一の
 *   フォールバック文言を維持できる
 */

import type { components } from './schema';

export type Schemas = components['schemas'];

/** HTTP エラー(detail 抽出付き)。message は detail 文字列を優先する */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, fallbackMessage: string) {
    super(typeof detail === 'string' && detail ? detail : fallbackMessage);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  /** detail 文字列があればそれを、無ければ fallback を返す(旧実装の alert 文言維持用) */
  messageWith(fallback: string): string {
    return typeof this.detail === 'string' && this.detail ? this.detail : fallback;
  }
}

/** !ok なら ApiError を投げ、ok なら Response を返す */
export async function fetchApi(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = body?.detail ?? null;
    } catch {
      /* error body が JSON でない場合は detail 無しで扱う */
    }
    throw new ApiError(res.status, detail, `${init?.method ?? 'GET'} ${url} failed: ${res.status}`);
  }
  return res;
}

/** JSON API 呼び出し。!ok / network error は例外 */
export async function fetchJson<T = unknown>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetchApi(url, init);
  return (await res.json()) as T;
}

/** JSON ボディ付き POST。!ok / network error は例外 */
export async function postJson<T = unknown>(url: string, body: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * 例外からユーザ向けメッセージを組み立てる。
 * ApiError は detail 文字列を優先し、無ければ fallback(旧実装の文言)。
 * それ以外は旧実装同士 err.message / String(err)。
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.messageWith(fallback);
  return err instanceof Error ? err.message : String(err);
}
