import React from 'react';
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cn } from '@/lib/utils.ts';
import { formatYen } from '../../../lib/format.ts';
// tooltipカード・軸整形の共通実装(chartTheme)を利用
import { TooltipCard, formatTick } from '../../shared/charts/chartTheme.tsx';

/** スパークラインの1点(PriceHistorySection が series から生成する) */
export interface PriceHistoryChartPoint {
  /** 元の ISO タイムスタンプ(scraped_at) */
  scraped_at: string;
  /** ミリ秒タイムスタンプ(時間軸に使用) */
  ts: number;
  daily: number;
  /** 前回点との差分(最初の点は null) */
  diff: number | null;
}

interface PriceHistoryChartProps {
  points: PriceHistoryChartPoint[];
}

/** 差分の色分け。アプリ規約に合わせ「下落=緑(success)/上昇=赤(danger)」 */
function diffClass(diff: number): string {
  return diff < 0 ? 'text-success' : 'text-danger';
}

/**
 * ツールチップは「金額 + 前回差分」のみ(日付は下の軸で読めるため出さない)。
 * 差分は変動方向で色分けする。
 */
function SparklineTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: PriceHistoryChartPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text">{formatYen(p.daily)}</div>
      {p.diff != null && p.diff !== 0 && (
        <div className={cn('font-medium', diffClass(p.diff))}>
          {p.diff < 0 ? '▼' : '▲'} {formatYen(Math.abs(p.diff))}
        </div>
      )}
      {p.diff === 0 && <div className="text-text-muted">変動なし</div>}
    </TooltipCard>
  );
}

/** 価格履歴の小型ラインチャート(recharts)。末尾点の強調は旧SVG版に倣う */
const PriceHistoryChart: React.FC<PriceHistoryChartProps> = ({ points }) => {
  if (points.length < 2) return null;

  const dropped = points[points.length - 1].daily < points[0].daily;
  const stroke = dropped
    ? 'var(--color-success, #00e676)'
    : 'var(--color-accent, #00f2fe)';

  return (
    <div className="w-full h-16" role="img" aria-label="価格推移スパークライン">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 6, right: 10, bottom: 0, left: 10 }}>
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={formatTick}
            tick={{ fontSize: 9, fill: 'var(--color-text-muted)' }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis hide domain={['auto', 'auto']} />
          <Tooltip
            content={<SparklineTooltip />}
            cursor={{ stroke: 'var(--color-border)', strokeDasharray: '3 3' }}
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="daily"
            stroke={stroke}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0, fill: stroke }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default PriceHistoryChart;
