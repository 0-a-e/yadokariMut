/**
 * 表示整形ユーティリティ(日付・金額)。
 * 旧来コンポーネント毎に重複していた ja-JP ロケール整形を集約する。
 * チャート軸用の派生整形は components/charts/chartTheme 経由で利用する。
 */

/** ISOタイムスタンプの表示用整形(日本語ローカル日付)。不正値は先頭10文字にフォールバック */
export function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString('ja-JP', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

/** セッション一覧用の時刻整形(「10/4 14:30」相当)。不正値は空文字 */
export function formatSessionTime(iso?: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('ja-JP', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

/** 管理画面用の短縮時刻整形(「10/04 14:30」相当)。null は "—"、不正値は先頭16文字 */
export function formatAdminTs(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 16);
    return d.toLocaleString('ja-JP', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16);
  }
}

/** 軸ラベル用の日付整形("2026-10-04" → "10/4") */
export function formatTickDate(date: string): string {
  const [m, d] = date.slice(5).split('-');
  return `${Number(m)}/${Number(d)}`;
}

/** 金額の桁区切り整形 */
export function formatYen(v: number): string {
  return v.toLocaleString();
}
