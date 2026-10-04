import React, { Suspense, useMemo } from 'react';
import type { PriceHistoryMeta, PriceHistoryPoint } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table.tsx';
import { FaChartLine } from 'react-icons/fa6';
import { cn } from '@/lib/utils.ts';
// 純関数は物件分析機能と共有するため lib/analysis へ切り出し
import {
  formatDate,
  parseDaily,
  priceDeltaFromHistory,
} from '../../lib/analysis/propertyHistory.ts';

/** DetailPanel が ./PriceHistorySection 経由で import し続けられるよう再exportを維持 */
export { priceDeltaFromHistory } from '../../lib/analysis/propertyHistory.ts';

/** recharts を含むため遅延ロード(地図初期表示のバンドルに載せない) */
const PriceHistoryChart = React.lazy(() => import('./charts/PriceHistoryChart.tsx'));

interface PriceHistorySectionProps {
  history: PriceHistoryPoint[];
  /** 品質ガードの除外件数などのメタ(詳細APIの price_history_meta) */
  meta?: PriceHistoryMeta | null;
  className?: string;
}

export const PriceHistorySection: React.FC<PriceHistorySectionProps> = ({
  history,
  meta,
  className,
}) => {
  const series = useMemo(() => {
    return history
      .map((p) => ({
        scraped_at: p.scraped_at,
        daily: parseDaily(p),
      }))
      .filter((x): x is { scraped_at: string; daily: number } => x.daily != null);
  }, [history]);

  const deltaInfo = useMemo(() => priceDeltaFromHistory(history), [history]);

  /** チャート用の点列(差分は前回点比。旧SVG版と同じ「下落=緑」色分けはchart側で行う) */
  const chartPoints = useMemo(() => {
    let prev: number | null = null;
    return series
      .map((s) => {
        const diff = prev == null ? null : s.daily - prev;
        prev = s.daily;
        return {
          scraped_at: s.scraped_at,
          ts: new Date(s.scraped_at).getTime(),
          daily: s.daily,
          diff,
        };
      })
      .filter((p) => !Number.isNaN(p.ts));
  }, [series]);

  if (series.length < 2) return null;

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-muted flex items-center gap-1.5">
          <FaChartLine className="text-accent" />
          掲載上の最安（スナップショット）
        </span>
        {deltaInfo && deltaInfo.delta !== 0 && (
          <Badge
            variant={deltaInfo.delta < 0 ? 'default' : 'secondary'}
            className={cn(
              'font-semibold text-xs',
              deltaInfo.delta < 0 && 'bg-success/20 text-success border-success/40',
              deltaInfo.delta > 0 && 'bg-warning/15 text-warning border-warning/40',
            )}
          >
            {deltaInfo.delta < 0 ? '' : '+'}
            {deltaInfo.delta.toLocaleString()}円
            <span className="font-normal opacity-80 ml-1">前回比</span>
          </Badge>
        )}
        {deltaInfo && deltaInfo.delta === 0 && (
          <Badge variant="secondary" className="text-xs">
            前回比 変動なし
          </Badge>
        )}
      </div>

      <Suspense fallback={<div className="w-full h-16 rounded-md bg-white/[0.03]" />}>
        <PriceHistoryChart points={chartPoints} />
      </Suspense>

      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs text-text-muted">日時</TableHead>
            <TableHead className="text-xs text-text-muted text-right">日額</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...series].reverse().map((row, i) => (
            <TableRow key={`${row.scraped_at}-${i}`}>
              <TableCell className="text-text/90">{formatDate(row.scraped_at)}</TableCell>
              <TableCell className="text-right font-semibold text-accent">
                {row.daily.toLocaleString()}円
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-[11px] text-text-muted m-0 leading-relaxed">
        スクレイプ時点の割引後最安です。期限切れキャンペーンを含む場合があり、現行の有効賃料・期間総額とは異なることがあります。
      </p>
      {meta && meta.dropped_count > 0 && (
        <p className="text-[11px] text-warning/90 m-0 leading-relaxed">
          品質ガードにより {meta.dropped_count.toLocaleString()} 件の異常値を除外しています。
        </p>
      )}
    </div>
  );
};
