import { Progress } from '@/components/ui/progress.tsx';
import type { GeojsonLoadProgressState } from '@/lib/geojsonStream.ts';

/**
 * 初期ロード中(ページ表示〜物件情報表示)の進捗オーバーレイ。
 *
 * ストリーム読み込み中は「受信件数/総件数」の確定バー、
 * フォールバック先の一括読み込み中は非確定(アニメーション)バーを表示する。
 * 総件数(total)は NDJSON meta 行の概算値(post-filter未反映)のため、
 * 受信数が総数を超え得る。percent は min(100, …) でクリップして吸収する。
 * バー本体は hextaUI `progress`(base-ui)。value を渡さない場合は不定表現になる。
 */
export function GeojsonLoadProgress({ progress }: { progress: GeojsonLoadProgressState }) {
  const label =
    progress.phase === 'stream'
      ? progress.total != null
        ? `物件情報(建物)を読み込み中… ${progress.received.toLocaleString()} / ${progress.total.toLocaleString()} 件`
        : `物件情報(建物)を読み込み中… ${progress.received.toLocaleString()} 件`
      : '物件情報(建物)を一括読み込み中…';

  const percent =
    progress.phase === 'stream' && progress.total != null && progress.total > 0
      ? Math.min(100, Math.round((progress.received / progress.total) * 100))
      : null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed left-1/2 -translate-x-1/2 z-[1600] bottom-[calc(env(safe-area-inset-bottom)+4.75rem)] md:bottom-6 pointer-events-none"
    >
      <div className="bg-[#12141c]/95 backdrop-blur-md border border-border rounded-lg px-4 py-2.5 shadow-xl w-[300px] max-w-[calc(100vw-2rem)]">
        <p className="text-xs text-text-muted mb-2 text-center truncate">{label}</p>
        {percent != null ? (
          <Progress value={percent} aria-label={label} />
        ) : (
          // value=null で base-ui が不定(indeterminate)表現になる
          <Progress value={null} aria-label={label} />
        )}
      </div>
    </div>
  );
}
