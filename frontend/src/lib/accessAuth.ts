/**
 * Cloudflare Access のセッション切れ検出と再ログイン。
 *
 * 本アプリは同一オリジンの /api 以下へ素の fetch で
 * アクセスする。Access のセッションが切れるとこれらのリクエストは
 * cloudflareaccess.com のログインページへ 302 されるが、既定の
 * redirect: 'follow' では fetch がリダイレクトを追いかけて CORS 違反の
 * 汎用 TypeError になるため、利用者には理由が伝わらない。
 *
 * そこでグローバル fetch をラップし、ガード対象 URL のリクエストのみ
 * redirect: 'manual' で送信する。302 は type 'opaqueredirect'（status 0）
 * として届くため、これを SessionExpiredError に変換しつつ
 * onSessionExpired で通知する。UI は通知を受けて再ログインダイアログ
 * （AccessSessionDialog）を出し、再認証後は Access が元の URL へ戻す。
 */

/** Access の認証リダイレクト（セッション切れ）で API 呼び出しが失敗した際のエラー。 */
export class SessionExpiredError extends Error {
  constructor() {
    super('ログインセッションが切れています。再ログインが必要です。')
    this.name = 'SessionExpiredError'
  }
}

/** redirect: 'manual' な fetch の応答が認証リダイレクトかを判定する（純関数）。 */
export function isAuthRedirectResponse(
  res: Pick<Response, 'type' | 'status'>,
): boolean {
  // redirect: 'manual' の同オリジン 302 は type 'opaqueredirect'（status 0）
  // として届く。API が自前でリダイレクトを返すことはないため、これが
  // 出たら認証プロキシの 302 とみなせる。
  return res.type === 'opaqueredirect'
}

/**
 * ガード対象 URL（同一オリジンの /api）かを判定する（純関数）。
 * origin はテストのため明示的に受け取る。
 */
export function isGuardedUrl(url: string, origin: string): boolean {
  try {
    const resolved = new URL(url, origin)
    if (resolved.origin !== origin) return false
    return (
      resolved.pathname === '/api' ||
      resolved.pathname.startsWith('/api/')
    )
  } catch {
    return false
  }
}

type SessionExpiredListener = () => void

const sessionExpiredListeners = new Set<SessionExpiredListener>()

/** セッション切れ検出時のコールバックを登録する。解除関数を返す。 */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener)
  return () => {
    sessionExpiredListeners.delete(listener)
  }
}

function notifySessionExpired(): void {
  for (const listener of sessionExpiredListeners) {
    listener()
  }
}

/**
 * fetch を Access セッション切れ検出つきに包む（純関数）。
 * ガード対象 URL には redirect: 'manual' を強制し、opaqueredirect を
 * SessionExpiredError へ変換する。それ以外は元の fetch を素通しする。
 */
export function createAuthGuardedFetch(
  originalFetch: typeof fetch,
): typeof fetch {
  return (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url
    const origin =
      typeof window !== 'undefined' && window.location
        ? window.location.origin
        : 'http://localhost'
    if (!isGuardedUrl(url, origin)) {
      return originalFetch(input, init)
    }
    return originalFetch(input, { ...init, redirect: 'manual' }).then(
      (res) => {
        if (isAuthRedirectResponse(res)) {
          notifySessionExpired()
          throw new SessionExpiredError()
        }
        return res
      },
    )
  }
}

let guardInstalled = false

/**
 * グローバル fetch に Access セッション切れ検出を仕込む（冪等）。
 * main.tsx の描画前に呼ぶことで、散在する fetch 呼び出し（コンポーネント、
 * CopilotKit / AG-UI の HttpAgent 含む）を一括で保護する。
 */
export function installAccessAuthGuard(): void {
  if (guardInstalled || typeof globalThis.fetch !== 'function') return
  guardInstalled = true
  globalThis.fetch = createAuthGuardedFetch(globalThis.fetch)
}

/**
 * Cloudflare Access の再ログインへ遷移する。
 *
 * Service Worker の precache が画面を出し続ける種類の障害に備え、SW 登録と
 * Cache Storage を全解除してから再読み込みし、ナビゲーションをネットワーク
 * 直行にする。認証が済むと Access が元の URL へ戻し、SW は次のロードで
 * 自動再登録されるため PWA は復活する。
 */
export async function relogin(): Promise<void> {
  if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
    const registrations = await navigator.serviceWorker.getRegistrations()
    await Promise.all(
      registrations.map((registration) => registration.unregister()),
    )
  }
  if (typeof caches !== 'undefined') {
    const keys = await caches.keys()
    await Promise.all(keys.map((key) => caches.delete(key)))
  }
  window.location.reload()
}
