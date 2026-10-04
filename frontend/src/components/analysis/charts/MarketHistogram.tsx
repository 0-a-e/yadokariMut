import React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AXIS_TICK, COLOR_ACCENT, COLOR_GRID, TooltipCard } from '../../shared/charts/chartTheme.tsx';
import type { MetricDef } from '../../../lib/analysis/marketBenchmark.ts';

/** ピア(自物件以外)のバー色。自物件ビンは chartTheme の COLOR_ACCENT で強調する */
const PEER_BAR_COLOR = '#3d4354';

interface HistogramRow {
  from: number;
  to: number;
  count: number;
  hasSelf: boolean;
}

interface MarketHistogramProps {
  bins: HistogramRow[];
  metric: MetricDef;
}

/** ビンの範囲・件数・自物件を含むかを表示するツールチップ */
function BinTooltip({
  active,
  payload,
  metric,
}: {
  active?: boolean;
  payload?: Array<{ payload?: HistogramRow }>;
  metric: MetricDef;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const bin = payload[0]?.payload;
  if (!bin) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">
        {metric.formatValue(bin.from)}〜{metric.formatValue(bin.to)}
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block size-2 rounded-full"
          style={{ background: bin.hasSelf ? COLOR_ACCENT : PEER_BAR_COLOR }}
        />
        <span className="text-text-muted">件数</span>
        <span className="font-semibold text-text ml-auto pl-3">{bin.count}件</span>
      </div>
      {bin.hasSelf && <div className="text-[11px] text-accent mt-0.5">このビンに自物件を含む</div>}
    </TooltipCard>
  );
}

/** 相場比較の指標分布ヒストグラム。自物件が属するビンを accent 色で強調する */
const MarketHistogram: React.FC<MarketHistogramProps> = ({ bins, metric }) => {
  if (bins.length === 0) return null;

  return (
    <div className="w-full h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" strokeOpacity={0.5} vertical={false} />
          <XAxis
            dataKey="from"
            tickFormatter={(v) => metric.formatValue(Number(v))}
            tick={AXIS_TICK}
            axisLine={{ stroke: COLOR_GRID }}
            tickLine={false}
          />
          <YAxis tick={AXIS_TICK} width={32} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip
            content={<BinTooltip metric={metric} />}
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            isAnimationActive={false}
          />
          <Bar dataKey="count" isAnimationActive={false}>
            {bins.map((bin) => (
              <Cell key={bin.from} fill={bin.hasSelf ? COLOR_ACCENT : PEER_BAR_COLOR} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MarketHistogram;
