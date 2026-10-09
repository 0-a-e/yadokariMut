import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SessionExpiredError,
  createAuthGuardedFetch,
  installAccessAuthGuard,
  isAuthRedirectResponse,
  isGuardedUrl,
  onSessionExpired,
  relogin,
} from './accessAuth.ts';

const ORIGIN = 'https://yadokari-mut.0ae.io';

beforeEach(() => {
  // node 環境（window 無し）でもブラウザと同じ origin 判定になるよう stub する
  vi.stubGlobal('window', {
    location: { origin: ORIGIN, reload: vi.fn() },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('isAuthRedirectResponse', () => {
  it('opaqueredirect（redirect: manual の 302）を認証リダイレクトと判定する', () => {
    expect(isAuthRedirectResponse({ type: 'opaqueredirect', status: 0 })).toBe(true);
  });

  it('通常の応答は判定しない', () => {
    expect(isAuthRedirectResponse({ type: 'basic', status: 200 })).toBe(false);
    expect(isAuthRedirectResponse({ type: 'cors', status: 302 })).toBe(false);
  });
});

describe('isGuardedUrl', () => {
  it('同一オリジンの /api をガード対象とする', () => {
    expect(isGuardedUrl('/api/properties', ORIGIN)).toBe(true);
    expect(isGuardedUrl('/api/', ORIGIN)).toBe(true);
    expect(isGuardedUrl(`${ORIGIN}/api/properties/1`, ORIGIN)).toBe(true);
  });

  it('API パス以外・別オリジン・不正 URL はガード対象外とする', () => {
    expect(isGuardedUrl('/', ORIGIN)).toBe(false);
    expect(isGuardedUrl('/map.geojson', ORIGIN)).toBe(false);
    expect(isGuardedUrl('/assets/index.js', ORIGIN)).toBe(false);
    expect(isGuardedUrl('https://example.com/api/properties', ORIGIN)).toBe(false);
    expect(isGuardedUrl('not a url', ORIGIN)).toBe(false);
  });
});

describe('createAuthGuardedFetch', () => {
  it('ガード対象 URL には redirect: manual を付けて呼ぶ', async () => {
    const ok = { type: 'basic', status: 200 } as Response;
    const original = vi.fn().mockResolvedValue(ok);
    const wrapped = createAuthGuardedFetch(original);

    await wrapped('/api/properties', { headers: { 'x-a': '1' } });

    expect(original).toHaveBeenCalledWith('/api/properties', {
      headers: { 'x-a': '1' },
      redirect: 'manual',
    });
  });

  it('ガード対象 URL の opaqueredirect を SessionExpiredError に変換し通知する', async () => {
    const opaque = { type: 'opaqueredirect', status: 0 } as Response;
    const original = vi.fn().mockResolvedValue(opaque);
    const wrapped = createAuthGuardedFetch(original);
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    await expect(wrapped('/api/properties')).rejects.toBeInstanceOf(SessionExpiredError);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('ガード対象外の URL は init を変えず元の fetch に素通しする', async () => {
    const redirect = { type: 'cors', status: 302 } as Response;
    const original = vi.fn().mockResolvedValue(redirect);
    const wrapped = createAuthGuardedFetch(original);
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    const res = await wrapped('https://example.com/redirect');

    expect(res).toBe(redirect);
    expect(original).toHaveBeenCalledWith('https://example.com/redirect', undefined);
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });
});

describe('installAccessAuthGuard', () => {
  it('グローバル fetch をガード付きに差し替える（冪等）', async () => {
    const opaque = { type: 'opaqueredirect', status: 0 } as Response;
    const original = vi.fn().mockResolvedValue(opaque);
    vi.stubGlobal('fetch', original);
    // モジュール内の installed フラグはプロセス共有のため、このテスト単体で
    // 「差し替えられること」と「二重差替えしないこと」を検証する
    const listener = vi.fn();
    const unsubscribe = onSessionExpired(listener);

    installAccessAuthGuard();
    const replaced = globalThis.fetch;
    expect(replaced).not.toBe(original);

    installAccessAuthGuard();
    expect(globalThis.fetch).toBe(replaced);

    await expect(replaced('/api/properties')).rejects.toBeInstanceOf(
      SessionExpiredError,
    );
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});

describe('relogin', () => {
  it('SW 登録と Cache Storage を全解除してから再読み込みする', async () => {
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi
      .fn()
      .mockResolvedValue([{ unregister }, { unregister }]);
    vi.stubGlobal('navigator', {
      serviceWorker: { getRegistrations },
    });
    const cacheKeys = vi.fn().mockResolvedValue(['precache-v1', 'runtime-v1']);
    const cacheDelete = vi.fn().mockResolvedValue(true);
    vi.stubGlobal('caches', { keys: cacheKeys, delete: cacheDelete });
    const reload = vi.fn();
    vi.stubGlobal('window', { location: { reload } });

    await relogin();

    expect(getRegistrations).toHaveBeenCalledTimes(1);
    expect(unregister).toHaveBeenCalledTimes(2);
    expect(cacheKeys).toHaveBeenCalledTimes(1);
    expect(cacheDelete.mock.calls).toEqual([['precache-v1'], ['runtime-v1']]);
    // 解除完了後に reload が走る
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
