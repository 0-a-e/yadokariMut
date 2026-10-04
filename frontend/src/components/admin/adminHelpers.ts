/**
 * スクレイプ管理タブ内の表示ヘルパ。ScrapeTab と区画コンポーネントで共用する。
 */
import type { RotationSourceStatus } from '../../types.ts';

// 時刻整形は lib/format 正本から(区画コンポーネントの import 経路互換のため再export)
export { formatAdminTs } from '../../lib/format.ts';

/** next_batch.reason の日本語表示マップ（未登録コードはそのまま表示） */
export const ROTATION_REASON_LABELS: Record<string, string> = {
  daily_budget_exhausted: '本日の予算を使い切り',
};

/** run/task ステータス → バッジ配色(エラー=赤・部分失敗/中断=黄・OK=緑) */
export function runStatusBadgeClass(status: string | null | undefined): string {
  switch (status) {
    case 'error':
      return 'bg-danger/[0.12] text-danger border-danger/30';
    case 'partial':
    case 'aborted':
      return 'bg-warning/[0.12] text-warning border-warning/30';
    case 'running':
      return 'bg-primary/10 text-primary border-primary/30';
    default:
      return 'bg-success/10 text-success border-success/30';
  }
}

/** 次回バッチ対象県の表示ラベル（県名があれば名前、無ければ slug） */
export function nextBatchPrefLabels(src: RotationSourceStatus): string {
  const bySlug = new Map((src.prefs || []).map((p) => [p.slug, p]));
  return (src.next_batch?.prefs || [])
    .map((slug) => bySlug.get(slug)?.name || slug)
    .join(', ');
}
