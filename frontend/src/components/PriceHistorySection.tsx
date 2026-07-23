import React, { useMemo } from 'react';
import type { PriceHistoryPoint } from '../types';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { FaChartLine } from 'react-icons/fa6';
import { cn } from '@/lib/utils';

interface PriceHistorySectionProps {
  history: PriceHistoryPoint[];
  className?: string;
}

function parseDaily(p: PriceHistoryPoint): number | null {
  const v = p.min_discounted_daily_rent_yen;
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

function formatDate(iso: string): string {
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

/** Simple SVG sparkline for discounted daily rent history. */
function Sparkline({ values }: { values: number[] }) {
  const w = 240;
  const h = 48;
  const pad = 4;
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (v - min) / span) * (h - pad * 2);
    return `${x},${y}`;
  });
  const polyline = pts.join(' ');
  const last = values[values.length - 1];
  const lastX = pad + ((values.length - 1) / (values.length - 1)) * (w - pad * 2);
  const lastY = pad + (1 - (last - min) / span) * (h - pad * 2);

  const dropped = last < values[0];
  const stroke = dropped ? 'var(--color-success, #22c55e)' : 'var(--color-accent, #c4b5fd)';

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full max-w-[280px] h-12"
      role="img"
      aria-label="価格推移スパークライン"
    >
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={polyline}
      />
      <circle cx={lastX} cy={lastY} r="3.5" fill={stroke} />
    </svg>
  );
}

export function priceDeltaFromHistory(history: PriceHistoryPoint[]): {
  delta: number;
  latest: number;
  previous: number;
} | null {
  const withDaily = history
    .map((p) => ({ at: p.scraped_at, daily: parseDaily(p) }))
    .filter((x): x is { at: string; daily: number } => x.daily != null);
  if (withDaily.length < 2) return null;
  const previous = withDaily[withDaily.length - 2].daily;
  const latest = withDaily[withDaily.length - 1].daily;
  return { delta: latest - previous, latest, previous };
}

export const PriceHistorySection: React.FC<PriceHistorySectionProps> = ({
  history,
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

      <Sparkline values={series.map((s) => s.daily)} />

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
    </div>
  );
};
