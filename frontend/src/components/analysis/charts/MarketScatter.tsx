import React from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import { formatYen } from '../../../lib/format.ts';
import { AXIS_TICK, COLOR_ACCENT, COLOR_GRID, COLOR_MUTED, TooltipCard, TooltipRow, formatYenCompact } from '../../shared/charts/chartTheme.tsx';

/** ピアの点色(控えめなダークグレー) */
const PEER_POINT_COLOR = '#3d4354';
/** 自物件の点サイズ(ZAxis range は円の面積。ピア既定64に対して大きめ) */
const SELF_POINT_SIZE = 220;

interface ScatterPoint {
  x: number;
  y: number;
  isSelf?: boolean;
}

interface MarketScatterProps {
  /** ピアの(面積, 日額)点列 */
  points: { x: number; y: number }[];
  /** 自物件の点(null なら描かない) */
  self: { x: number; y: number } | null;
  /** 回帰直線(null なら描かない) */
  regression: { slope: number; intercept: number } | null;
}

/** 回帰直線 series の名前(ツールチップ除外用) */
const REGRESSION_NAME = '回帰直線';

/** 面積・日額を表示するツールチップ(回帰直線のホバーは除外) */
function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; payload?: ScatterPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const entry = payload.find((p) => p.name !== REGRESSION_NAME);
  const point = entry?.payload;
  if (!point) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">
        {point.isSelf ? '自物件' : 'ピア物件'}
      </div>
      <TooltipRow label="面積" value={`${point.x.toFixed(1)}㎡`} />
      <TooltipRow label="日額" value={formatYen(Math.round(point.y))} />
    </TooltipCard>
  );
}

/** 面積×日額の散布図。自物件を大きい点で重ね、回帰直線を破線で引く */
const MarketScatter: React.FC<MarketScatterProps> = ({ points, self, regression }) => {
  if (points.length === 0) return null;

  // 軸の範囲は self と回帰直線の両端を含めて余白5%を足す(全点が同じ値のときは±1で崩れ防止)
  const selfPoint: ScatterPoint | null = self ? { ...self, isSelf: true } : null;
  const allPoints: ScatterPoint[] = [...points, ...(selfPoint ? [selfPoint] : [])];
  const rawXMin = Math.min(...allPoints.map((p) => p.x));
  const rawXMax = Math.max(...allPoints.map((p) => p.x));

  // 回帰直線は x 範囲両端の2点だけの別 series として渡す
  const regressionData: { x: number; y: number }[] | null =
    regression
      ? [
          { x: rawXMin, y: regression.slope * rawXMin + regression.intercept },
          { x: rawXMax, y: regression.slope * rawXMax + regression.intercept },
        ]
      : null;

  const pad = (min: number, max: number): [number, number] => {
    const d = max - min;
    const margin = d > 0 ? d * 0.05 : Math.abs(max) * 0.05 || 1;
    return [min - margin, max + margin];
  };
  const [xDomainMin, xDomainMax] = pad(rawXMin, rawXMax);
  const yValues = [
    ...allPoints.map((p) => p.y),
    ...(regressionData?.map((p) => p.y) ?? []),
  ];
  const [yDomainMin, yDomainMax] = pad(Math.min(...yValues), Math.max(...yValues));

  return (
    <div className="w-full h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" strokeOpacity={0.5} />
          <XAxis
            dataKey="x"
            type="number"
            domain={[xDomainMin, xDomainMax]}
            tickFormatter={(v) => `${Number(v).toFixed(1)}㎡`}
            tick={AXIS_TICK}
            axisLine={{ stroke: COLOR_GRID }}
            tickLine={false}
          />
          <YAxis
            dataKey="y"
            type="number"
            domain={[yDomainMin, yDomainMax]}
            tickFormatter={formatYenCompact}
            tick={AXIS_TICK}
            width={64}
            axisLine={false}
            tickLine={false}
          />
          <ZAxis range={[64, 64]} />
          <ZAxis zAxisId="self" range={[SELF_POINT_SIZE, SELF_POINT_SIZE]} />
          <Tooltip
            content={<ScatterTooltip />}
            cursor={{ stroke: COLOR_GRID, strokeDasharray: '3 3' }}
            isAnimationActive={false}
          />
          <Scatter data={points} fill={PEER_POINT_COLOR} isAnimationActive={false} />
          <Scatter
            data={selfPoint ? [selfPoint] : []}
            zAxisId="self"
            fill={COLOR_ACCENT}
            isAnimationActive={false}
          />
          {regressionData && (
            <Line
              data={regressionData}
              dataKey="y"
              name={REGRESSION_NAME}
              type="linear"
              stroke={COLOR_MUTED}
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MarketScatter;
