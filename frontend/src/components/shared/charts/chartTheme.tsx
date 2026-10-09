import type { ReactNode } from 'react';
import { cn } from '../../../lib/utils.ts';

/**
 * チャート共通の色・軸トークンとtooltipカード・凡例。
 * recharts を利用するコンポーネントの規約レイヤ(PriceTrendChart などから import する)。
 * fallback は index.css @theme の実値と一致させる(SVG属性は var() 参照が有効で、
 * 通常時は変数が解決されるため fallback は非DOM文脈・変数未定義時の保険)。
 */

export const COLOR_ACCENT = 'var(--color-accent, #00f2fe)';
export const COLOR_MUTED = 'var(--color-text-muted, #8e95a5)';
export const COLOR_SUCCESS = 'var(--color-success, #00e676)';
export const COLOR_DANGER = 'var(--color-danger, #ff1744)';
export const COLOR_WARNING = 'var(--color-warning, #ffb300)';
export const COLOR_GRID = 'var(--color-border, #2a2e3a)';

/** 軸の目盛り共通スタイル */
export const AXIS_TICK = { fontSize: 10, fill: 'var(--color-text-muted)' };

// 日付・金額整形は lib/format 正本からの再export(チャート側の import 経路互換)
export { formatTickDate, formatYenCompact } from '../../../lib/format.ts';

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

/** dot/破線マーカー(凡例・Tooltip行で共用) */
export function ChartMarker({ color, dashed }: { color?: string; dashed?: boolean }) {
  if (!color) return null;
  return dashed ? (
    <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: color }} />
  ) : (
    <span className="inline-block size-2 rounded-full" style={{ background: color }} />
  );
}

/** Tooltip内の1行(ラベル+右寄せ値) */
export function TooltipRow({
  label,
  value,
  color,
  dashed,
  valueClassName,
}: {
  label: ReactNode;
  value: ReactNode; // toLocaleString()円 等の整形は呼び出し側
  color?: string; // dotマーカーの色(未指定=マーカーなし)
  dashed?: boolean; // 破線マーカー(color必須)
  valueClassName?: string; // 値部分の色上書き(text-success 等)
}) {
  return (
    <div className="flex items-center gap-1.5">
      <ChartMarker color={color} dashed={dashed} />
      <span className="text-text-muted">{label}</span>
      <span className={cn('font-semibold ml-auto pl-3', valueClassName ?? 'text-text')}>
        {value}
      </span>
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
          <ChartMarker color={it.color} dashed={it.dashed} />
          {it.label}
        </span>
      ))}
    </div>
  );
}

/**
 * プランバンドの表示色(滞在短=寒色 → 滞在長=暖色)。
 * 既存の --chart-1..5 はグレー階調で識別性が足りないため専用定義。
 * TODO: 同値のテーマ変数(--color-*)が存在しないため hex 直書き。テーマ側に
 * 変数が追加されたら var() 参照へ寄せる。
 */
export const PLAN_COLORS: Record<string, string> = {
  s_short: '#38bdf8',
  semi_short: '#818cf8',
  short: '#a78bfa',
  middle: '#e879f9',
  long: '#fb923c',
};

/** 未知プランコード用の予備パレット(2026-10-08・設計 §3.6)。
 *  PlanCode 型を string 開放したことに伴い、新サイト等の未知コードも凡例で
 *  識別できるようにする。割当順は codes のソート順(=辞書コード順)で決定的。 */
const PLAN_COLOR_RESERVE = ['#f87171', '#4ade80', '#fbbf24', '#2dd4bf', '#c084fc', '#f472b6'];

/** コード集合へ色を決定的に割り当てる(既知コードは PLAN_COLORS、未知は予備パレット順)。 */
export function assignPlanColors(codes: readonly string[]): Record<string, string> {
  const assigned: Record<string, string> = {};
  let reserveIdx = 0;
  for (const code of codes) {
    assigned[code] =
      PLAN_COLORS[code] ?? PLAN_COLOR_RESERVE[reserveIdx++ % PLAN_COLOR_RESERVE.length];
  }
  return assigned;
}

/** プランコードに対する表示色。未知のコードは accent にフォールバック
 *  (複数コードを並べる凡例では assignPlanColors を使う方が識別性が高い) */
export function planColor(code?: string | null): string {
  if (!code) return COLOR_ACCENT;
  return PLAN_COLORS[code] ?? COLOR_ACCENT;
}
