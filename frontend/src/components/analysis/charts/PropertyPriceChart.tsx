import React, { useMemo } from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cn } from '@/lib/utils.ts';
import type { HistoryChartPoint } from '../../../lib/analysis/propertyHistory.ts';
import { formatDate } from '../../../lib/analysis/propertyHistory.ts';
// 色・軸・tooltip・凡例の共通定義は chartTheme を利用(PriceTrendChart と同じ規約レイヤ)
import {
  AXIS_TICK,
  COLOR_ACCENT,
  COLOR_GRID,
  COLOR_MUTED,
  TooltipCard,
  TrendLegend,
  formatTick,
  formatYen,
} from '../../shared/charts/chartTheme.tsx';

/** 市場中央値の1点(PropertyPriceTab が usePriceTrend の carried 系列から生成する) */
export interface MarketMedianPoint {
  /** ミリ秒タイムスタンプ(物件系列と同一の時間軸でマージする) */
  ts: number;
  median: number;
}

interface PropertyPriceChartProps {
  /** 物件の掲載最安日額系列(昇順) */
  points: HistoryChartPoint[];
  /** 同県の市場中央値(前進補完推計)。取得失敗時は null */
  market: MarketMedianPoint[] | null;
  /** 期間絞り込み後の日数(全期間は null)。将来の期間マーカー表示用の予約パラメータ */
  selectedDays: number | null;
}

/** 両系列を ts でマージした1行。無い側の値は undefined(recharts が描画をスキップする) */
interface MergedPoint {
  ts: number;
  daily?: number;
  /** 前回比(物件系列のみ。最初の点は null) */
  diff?: number | null;
  marketMedian?: number;
}

/** 差分の色分け。アプリ規約に合わせ「下落=緑(success)/上昇=赤(danger)」 */
function diffClass(diff: number): string {
  return diff < 0 ? 'text-success' : 'text-danger';
}

/**
 * ツールチップ: 日付 / 物件日額(+前回差分を方向で色分け) / 市場中央値(存在する時のみ)。
 * 物件と市場は同一データ配列にマージしているため payload[0].payload から読む。
 */
function PriceTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: MergedPoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <TooltipCard>
      {/* ts はローカル時刻由来のため、一度 ISO に戻してから共通の formatDate で整形する */}
      <div className="font-semibold text-text mb-1">{formatDate(new Date(p.ts).toISOString())}</div>
      {p.daily != null && (
        <div className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-full" style={{ background: COLOR_ACCENT }} />
          <span className="text-text-muted">この物件の日額</span>
          <span className="font-semibold text-text ml-auto pl-3">
            {p.daily.toLocaleString()}円
          </span>
        </div>
      )}
      {p.daily != null && p.diff != null && p.diff !== 0 && (
        <div className={cn('text-right font-medium', diffClass(p.diff))}>
          {p.diff < 0 ? '▼' : '▲'} {Math.abs(p.diff).toLocaleString()}円
        </div>
      )}
      {p.marketMedian != null && (
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-4 border-t-2 border-dashed"
            style={{ borderColor: COLOR_MUTED }}
          />
          <span className="text-text-muted">同県の中央値(推計)</span>
          <span className="font-semibold text-text ml-auto pl-3">
            {p.marketMedian.toLocaleString()}円
          </span>
        </div>
      )}
    </TooltipCard>
  );
}

/**
 * 物件の掲載最安日額(実線・階段補間)に市場中央値(破線・線形)を重ねたチャート。
 * recharts は1つのデータ配列しか取れないため、両系列を ts 昇順にマージして渡す。
 */
const PropertyPriceChart: React.FC<PropertyPriceChartProps> = ({ points, market }) => {
  // 物件系列と市場系列を ts 昇順で1配列にマージする(同一 ts は1行に統合)。
  // 早期リターンより先にフックを呼ぶ(Rules of Hooks)
  const data = useMemo<MergedPoint[]>(() => {
    const byTs = new Map<number, MergedPoint>();
    for (const p of points) {
      byTs.set(p.ts, { ts: p.ts, daily: p.daily, diff: p.diff });
    }
    for (const m of market ?? []) {
      const row = byTs.get(m.ts) ?? { ts: m.ts };
      row.marketMedian = m.median;
      byTs.set(m.ts, row);
    }
    return [...byTs.values()].sort((a, b) => a.ts - b.ts);
  }, [points, market]);

  if (points.length < 2) return null;

  const hasMarket = (market?.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-1">
      <TrendLegend
        items={[
          { color: COLOR_ACCENT, label: 'この物件の日額' },
          ...(hasMarket
            ? [{ color: COLOR_MUTED, label: '同県の中央値(前進補完推計)', dashed: true }]
            : []),
        ]}
      />
      <div className="w-full h-64" role="img" aria-label="物件の価格推移チャート">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid
              stroke={COLOR_GRID}
              strokeDasharray="3 3"
              strokeOpacity={0.5}
              vertical={false}
            />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={formatTick}
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
            <Tooltip
              content={<PriceTooltip />}
              cursor={{ stroke: COLOR_GRID, strokeDasharray: '3 3' }}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="daily"
              stroke={COLOR_ACCENT}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="marketMedian"
              stroke={COLOR_MUTED}
              strokeDasharray="4 4"
              strokeWidth={1.5}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default PropertyPriceChart;
