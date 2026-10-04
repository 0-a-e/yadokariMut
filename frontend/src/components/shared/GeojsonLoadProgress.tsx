import type { GeojsonLoadProgressState } from '@/lib/geojsonStream.ts';

/**
 * 初期ロード中(ページ表示〜物件情報表示)の進捗オーバーレイ。
 *
 * ストリーム読み込み中は「受信件数/総件数」の確定バー、
 * フォールバック先の一括/ローカル読み込み中は非確定(アニメーション)バーを表示する。
 * 総件数(total)は NDJSON meta 行の概算値(post-filter未反映)のため、
 * 受信数が総数を超え得る。percent は min(100, …) でクリップして吸収する。
 */
export function GeojsonLoadProgress({ progress }: { progress: GeojsonLoadProgressState }) {
  const label =
    progress.phase === 'stream'
      ? progress.total != null
        ? `物件情報を読み込み中… ${progress.received.toLocaleString()} / ${progress.total.toLocaleString()} 件`
        : `物件情報を読み込み中… ${progress.received.toLocaleString()} 件`
      : progress.phase === 'bulk'
        ? '物件情報を一括読み込み中…'
        : 'ローカルデータを読み込み中…';

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
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div
              className="h-full bg-primary transition-[width] duration-200 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
        ) : (
          <div className="h-1.5 rounded-full bg-border overflow-hidden relative">
            <div className="absolute inset-y-0 left-0 w-1/3 bg-primary animate-[geojson-indeterminate_1.2s_ease-in-out_infinite]" />
          </div>
        )}
      </div>
    </div>
  );
}
