import React from 'react';
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { PlanCurveRow } from '../../../lib/analysis/planCurve.ts';
import { PLAN_LABELS, type PlanCode } from '../../../lib/rentCalculator.ts';
// 色・軸・tooltip・凡例の共通定義は chartTheme へ切り出し
import {
  AXIS_TICK,
  COLOR_GRID,
  COLOR_WARNING,
  PLAN_COLORS,
  TooltipCard,
  TrendLegend,
  formatYen,
  planColor,
} from '../../shared/charts/chartTheme.tsx';

interface PlanCostCurveChartProps {
  rows: PlanCurveRow[];
  selectedDays: number;
  onSelectDays?: (days: number) => void;
}

/** チャート用に values をフラット化した1点。planCode/total/perDay は tooltip 表示用に同居させる */
interface CurvePoint {
  days: number;
  planCode: string;
  total: number;
  perDay: number;
  [code: string]: number | string | null;
}

/** PLAN_LABELS に無いコード(semi_short 等)のフォールバック表示名 */
const EXTRA_PLAN_LABELS: Record<string, string> = {
  semi_short: 'セミショート',
};

/** プランコードの表示名(PLAN_LABELS → セミショート等の補完 → コードそのまま) */
function planLabel(code: string): string {
  return PLAN_LABELS[code as PlanCode] ?? EXTRA_PLAN_LABELS[code] ?? code;
}

function CurveTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: CurvePoint }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">{p.days.toLocaleString()}日</div>
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block size-2 rounded-full"
          style={{ background: planColor(p.planCode) }}
        />
        <span className="text-text-muted">適用プラン</span>
        <span className="font-semibold text-text ml-auto pl-3">{planLabel(p.planCode)}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">総額</span>
        <span className="font-semibold text-text ml-auto pl-3">
          {p.total.toLocaleString()}円
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">実質1日単価</span>
        <span className="font-semibold text-text ml-auto pl-3">
          {p.perDay.toLocaleString()}円
        </span>
      </div>
    </TooltipCard>
  );
}

/**
 * 滞在日数×実質1日単価のカーブ。プラン別に Line を分け、30日/91日/181日境界の
 * 段差(まとめ買い割引)を見せる。選択中の日数は Warning 色の縦破線で示す。
 */
const PlanCostCurveChart: React.FC<PlanCostCurveChartProps> = ({
  rows,
  selectedDays,
  onSelectDays,
}) => {
  if (rows.length === 0) return null;

  // dataKey はネスト不可のため values を1点ずつフラット形状に展開する
  const data: CurvePoint[] = rows.map((r) => {
    const point: CurvePoint = {
      days: r.days,
      planCode: r.planCode,
      total: r.total,
      perDay: r.perDay,
    };
    for (const [code, value] of Object.entries(r.values)) {
      point[code] = value;
    }
    return point;
  });

  // 表示対象のプランコード(バンド順。未知コードが混在した場合は末尾に追加)
  const presentCodes = new Set(rows.map((r) => r.planCode));
  const codes = Object.keys(PLAN_COLORS).filter((c) => presentCodes.has(c));
  for (const c of presentCodes) {
    if (!codes.includes(c)) codes.push(c);
  }

  const maxDays = rows[rows.length - 1].days;

  return (
    <div className="flex flex-col gap-1">
      <TrendLegend items={codes.map((code) => ({ color: planColor(code), label: planLabel(code) }))} />
      <div className="w-full h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            onClick={(state: unknown) => {
              const label = (state as { activeLabel?: string | number } | null)?.activeLabel;
              if (onSelectDays && label != null) onSelectDays(Number(label));
            }}
          >
            <CartesianGrid stroke={COLOR_GRID} strokeDasharray="3 3" strokeOpacity={0.5} vertical={false} />
            <XAxis
              dataKey="days"
              type="number"
              domain={[1, maxDays]}
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: COLOR_GRID }}
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
              content={<CurveTooltip />}
              cursor={{ stroke: COLOR_GRID, strokeDasharray: '3 3' }}
              isAnimationActive={false}
            />
            <ReferenceLine x={selectedDays} stroke={COLOR_WARNING} strokeDasharray="4 2" />
            {codes.map((code) => (
              <Line
                key={code}
                type="stepAfter"
                dataKey={code}
                name={planLabel(code)}
                stroke={planColor(code)}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default PlanCostCurveChart;
