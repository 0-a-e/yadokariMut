import type { ReactNode } from 'react';

/**
 * チャート共通の色・軸トークンとtooltipカード・凡例。
 * recharts を利用するコンポーネントの規約レイヤ(PriceTrendChart などから import する)。
 */

export const COLOR_ACCENT = 'var(--color-accent, #00f2fe)';
export const COLOR_MUTED = 'var(--color-text-muted, #8a93a6)';
export const COLOR_SUCCESS = 'var(--color-success, #00e676)';
export const COLOR_DANGER = 'var(--color-danger, #ff1744)';
export const COLOR_WARNING = 'var(--color-warning, #ffb300)';
export const COLOR_GRID = 'var(--color-border, #2a2e3a)';

/** 軸の目盛り共通スタイル */
export const AXIS_TICK = { fontSize: 10, fill: 'var(--color-text-muted)' };

// 日付・金額整形は lib/format 正本からの再export(チャート側の import 経路互換)
export { formatTickDate, formatYen } from '../../../lib/format.ts';

/** 時間軸の目盛り整形(ミリ秒タイムスタンプ → "10/4") */
export function formatTick(ts: number): string {
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** ツールチップ共通のカード */
export function TooltipCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-panel px-3 py-2 text-xs shadow-lg backdrop-blur-sm">
      {children}
    </div>
  );
}

/** 凡例(色点 or 破線 + ラベル) */
export function TrendLegend({
  items,
}: {
  items: { color: string; label: string; dashed?: boolean }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-1.5">
          {it.dashed ? (
            <span
              className="inline-block w-4 border-t-2 border-dashed"
              style={{ borderColor: it.color }}
            />
          ) : (
            <span className="inline-block size-2 rounded-full" style={{ background: it.color }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

/**
 * プランバンドの表示色(滞在短=寒色 → 滞在長=暖色)。
 * 既存の --chart-1..5 はグレー階調で識別性が足りないため専用定義。
 */
export const PLAN_COLORS: Record<string, string> = {
  s_short: '#38bdf8',
  semi_short: '#818cf8',
  short: '#a78bfa',
  middle: '#e879f9',
  long: '#fb923c',
};

/** プランコードに対する表示色。未知のコードは accent にフォールバック */
export function planColor(code?: string | null): string {
  if (!code) return COLOR_ACCENT;
  return PLAN_COLORS[code] ?? COLOR_ACCENT;
}
