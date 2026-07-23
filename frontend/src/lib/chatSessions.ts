/** Local metadata for chat sessions (titles / recency), merged with server checkpoints. */

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

export function titleFromMessage(text: string): string {
  const t = text.trim().replace(/\s+/g, ' ');
  if (!t) return '新しい会話';
  return t.length > 40 ? `${t.slice(0, 40)}…` : t;
}

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

export async function fetchServerThreads(): Promise<ServerThread[]> {
  try {
    const res = await fetch('/api/chat/threads');
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.threads) ? data.threads : [];
  } catch {
    return [];
  }
}

export async function fetchThreadMessages(
  threadId: string,
): Promise<{ id: string; role: string; content: string }[]> {
  try {
    const res = await fetch(`/api/chat/threads/${encodeURIComponent(threadId)}/messages`);
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data.messages) ? data.messages : [];
  } catch {
    return [];
  }
}

export async function deleteServerThread(threadId: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/chat/threads/${encodeURIComponent(threadId)}`, {
      method: 'DELETE',
    });
    return res.ok;
  } catch {
    return false;
  }
}
