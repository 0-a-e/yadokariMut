/** Local metadata for chat sessions (titles / recency), merged with server checkpoints. */
import type {
  ChatThreadMessage,
  ChatThreadMessagesResponse,
  ChatThreadsResponse,
} from '../types.ts';
import { fetchApi, fetchJson } from './api/client.ts';
import { createId } from './utils.ts';

export interface ChatSessionMeta {
  id: string;
  title: string;
  preview?: string;
  updatedAt: string;
  messageCount?: number;
}

const META_KEY = 'yadokariMut.chatSessions';
export const ACTIVE_THREAD_KEY = 'yadokariMut.chatThreadId';

export function loadSessionMeta(): ChatSessionMeta[] {
  try {
    const raw = localStorage.getItem(META_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveSessionMeta(list: ChatSessionMeta[]): void {
  try {
    localStorage.setItem(META_KEY, JSON.stringify(list.slice(0, 100)));
  } catch {
    /* ignore quota */
  }
}

export function upsertSessionMeta(entry: ChatSessionMeta): ChatSessionMeta[] {
  const list = loadSessionMeta().filter((s) => s.id !== entry.id);
  list.unshift(entry);
  saveSessionMeta(list);
  return list;
}

export function removeSessionMeta(id: string): ChatSessionMeta[] {
  const list = loadSessionMeta().filter((s) => s.id !== id);
  saveSessionMeta(list);
  return list;
}

export function setActiveThreadId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_THREAD_KEY, id);
  } catch {
    /* ignore */
  }
}

/**
 * アクティブスレッド id を読み、無ければ新規発行して保存する。
 * App の初期化時に 1 回呼ぶ。
 */
export function loadOrCreateActiveThread(): string {
  try {
    const existing = localStorage.getItem(ACTIVE_THREAD_KEY);
    if (existing) return existing;
  } catch {
    /* ignore */
  }
  const id = createId();
  setActiveThreadId(id);
  upsertSessionMeta({
    id,
    title: '新しい会話',
    updatedAt: new Date().toISOString(),
    messageCount: 0,
  });
  return id;
}

export function titleFromMessage(text: string): string {
  const t = text.trim().replace(/\s+/g, ' ');
  if (!t) return '新しい会話';
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
}

/** Server-side thread row (GET /api/chat/threads の要素を FE 用に正規化したビュー) */
export interface ServerThread {
  id: string;
  title: string;
  preview?: string;
  updatedAt?: string | null;
  messageCount?: number;
  checkpointCount?: number;
}

/** Merge server threads with local meta (local title wins if newer). */
export function mergeThreads(
  server: ServerThread[],
  local: ChatSessionMeta[],
): ChatSessionMeta[] {
  const map = new Map<string, ChatSessionMeta>();

  for (const s of server) {
    map.set(s.id, {
      id: s.id,
      title: s.title || `会話 ${s.id.slice(0, 8)}`,
      preview: s.preview,
      updatedAt: s.updatedAt || new Date().toISOString(),
      messageCount: s.messageCount,
    });
  }

  for (const l of local) {
    const existing = map.get(l.id);
    if (!existing) {
      map.set(l.id, l);
    } else {
      // Prefer non-generic local title
      const preferLocalTitle =
        l.title &&
        !l.title.startsWith('会話 ') &&
        (existing.title.startsWith('会話 ') || l.title.length >= existing.title.length);
      map.set(l.id, {
        ...existing,
        title: preferLocalTitle ? l.title : existing.title,
        preview: l.preview || existing.preview,
        updatedAt:
          (l.updatedAt || '') > (existing.updatedAt || '')
            ? l.updatedAt
            : existing.updatedAt,
      });
    }
  }

  return [...map.values()].sort((a, b) =>
    (b.updatedAt || '').localeCompare(a.updatedAt || ''),
  );
}

/** GET /api/chat/threads — チェックポイント DB 由来のセッション一覧。失敗時は [] */
export async function fetchServerThreads(): Promise<ServerThread[]> {
  try {
    const data = await fetchJson<ChatThreadsResponse>('/api/chat/threads');
    const threads = Array.isArray(data.threads) ? data.threads : [];
    // 生成型(ChatThreadSummary) → FE 内部ビュー(ServerThread)へ写像する
    return threads.map((t) => ({
      id: t.id,
      title: t.title,
      preview: t.preview,
      updatedAt: t.updatedAt ?? null,
      messageCount: t.messageCount,
      checkpointCount: t.checkpointCount,
    }));
  } catch {
    return [];
  }
}

/** GET /api/chat/threads/{id}/messages — AG-UI 正規化済みメッセージ。失敗時は [] */
export async function fetchThreadMessages(
  threadId: string,
): Promise<ChatThreadMessage[]> {
  try {
    const data = await fetchJson<ChatThreadMessagesResponse>(
      `/api/chat/threads/${encodeURIComponent(threadId)}/messages`,
    );
    return Array.isArray(data.messages) ? data.messages : [];
  } catch {
    return [];
  }
}

/** DELETE /api/chat/threads/{id} — チェックポイント削除。成功/失敗を真偽で返す */
export async function deleteServerThread(threadId: string): Promise<boolean> {
  try {
    await fetchApi(`/api/chat/threads/${encodeURIComponent(threadId)}`, {
      method: 'DELETE',
    });
    return true;
  } catch {
    return false;
  }
}
