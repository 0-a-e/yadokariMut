import React from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { PriceTrendPoint } from '../../../types.ts';
// 色・軸・tooltip・凡例の共通定義は chartTheme へ切り出し(旧ローカル名は意味でalias)
import {
  AXIS_TICK,
  COLOR_ACCENT as COLOR_MEDIAN,
  COLOR_DANGER as COLOR_UP,
  COLOR_GRID,
  COLOR_MUTED as COLOR_AVG,
  COLOR_SUCCESS as COLOR_DOWN,
  COLOR_WARNING as COLOR_COUNT,
  TooltipCard,
  TrendLegend,
  formatTickDate,
  formatYen,
} from '../../shared/charts/chartTheme.tsx';

interface PriceTrendChartProps {
  series: PriceTrendPoint[];
}

function PriceTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: PriceTrendPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">{p.date}</div>
      <div className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full" style={{ background: COLOR_MEDIAN }} />
        <span className="text-text-muted">中央値</span>
        <span className="font-semibold text-text ml-auto pl-3">{p.median.toLocaleString()}円</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full" style={{ background: COLOR_AVG }} />
        <span className="text-text-muted">平均</span>
        <span className="font-semibold text-text ml-auto pl-3">{p.avg.toLocaleString()}円</span>
      </div>
    </TooltipCard>
  );
}

function ChangeTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: PriceTrendPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">{p.date}</div>
      <div className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full" style={{ background: COLOR_DOWN }} />
        <span className="text-text-muted">値下げ</span>
        <span className="font-semibold text-success ml-auto pl-3">{p.down}件</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full" style={{ background: COLOR_UP }} />
        <span className="text-text-muted">値上げ</span>
        <span className="font-semibold text-danger ml-auto pl-3">{p.up}件</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full" style={{ background: COLOR_COUNT }} />
        <span className="text-text-muted">掲載物件数</span>
        <span className="font-semibold text-text ml-auto pl-3">{p.count.toLocaleString()}件</span>
      </div>
    </TooltipCard>
  );
}

/**
 * 価格変動推移の2段チャート(ホバー連動)。
 * 上段=日額の中央値/平均ライン、下段=値下げ/値上げ件数の積み上げバー+掲載物件数ライン。
 */
const PriceTrendChart: React.FC<PriceTrendChartProps> = ({ series }) => {
  if (series.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <TrendLegend
          items={[
            { color: COLOR_MEDIAN, label: '日額中央値' },
            { color: COLOR_AVG, label: '日額平均', dashed: true },
          ]}
        />
        <div className="w-full h-56">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} syncId="price-trend">
              <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" strokeOpacity={0.5} vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatTickDate}
                tick={AXIS_TICK}
                axisLine={{ stroke: COLOR_GRID }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={formatYen}
                tick={AXIS_TICK}
                width={64}
                axisLine={false}
                tickLine={false}
                domain={['auto', 'auto']}
              />
              <Tooltip content={<PriceTooltip />} cursor={{ stroke: COLOR_GRID, strokeDasharray: '3 3' }} isAnimationActive={false} />
              <Line
                type="linear"
                dataKey="median"
                name="中央値"
                stroke={COLOR_MEDIAN}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="avg"
                name="平均"
                stroke={COLOR_AVG}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <TrendLegend
          items={[
            { color: COLOR_DOWN, label: '値下げ物件数' },
            { color: COLOR_UP, label: '値上げ物件数' },
            { color: COLOR_COUNT, label: '掲載物件数' },
          ]}
        />
        <div className="w-full h-44">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} syncId="price-trend">
              <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" strokeOpacity={0.5} vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatTickDate}
                tick={AXIS_TICK}
                axisLine={{ stroke: COLOR_GRID }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                yAxisId="left"
                tick={AXIS_TICK}
                width={64}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <YAxis yAxisId="right" orientation="right" tick={AXIS_TICK} width={56} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip content={<ChangeTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} isAnimationActive={false} />
              <Bar yAxisId="left" dataKey="down" name="値下げ" stackId="change" fill={COLOR_DOWN} isAnimationActive={false} />
              <Bar yAxisId="left" dataKey="up" name="値上げ" stackId="change" fill={COLOR_UP} isAnimationActive={false} />
              <Line
                yAxisId="right"
                type="linear"
                dataKey="count"
                name="掲載物件数"
                stroke={COLOR_COUNT}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

export default PriceTrendChart;
