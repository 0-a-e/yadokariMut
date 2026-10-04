import React from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { CalcBreakdown } from '../../../lib/rentCalculator.ts';
// 色・tooltip・凡例の共通定義は chartTheme へ切り出し
import {
  COLOR_ACCENT,
  COLOR_DANGER,
  COLOR_MUTED,
  COLOR_WARNING,
  TooltipCard,
  TrendLegend,
} from '../../shared/charts/chartTheme.tsx';

interface CostBreakdownBarProps {
  breakdown: CalcBreakdown;
  total: number;
}

/** 積み上げセグメント定義(賃料→管理費→光熱費→清掃費→契約事務手数料)。
 * 光熱費は utilities_included=false の物件のみ意味を持つ値なので、0 のときは凡例からも落とす */
const SEGMENTS: ReadonlyArray<{ key: keyof CalcBreakdown; label: string; color: string }> = [
  { key: 'rentTotal', label: '賃料', color: COLOR_ACCENT },
  { key: 'managementTotal', label: '管理費', color: COLOR_MUTED },
  { key: 'utilitiesTotal', label: '光熱費', color: '#38bdf8' },
  { key: 'cleaningFee', label: '清掃費', color: COLOR_WARNING },
  { key: 'contractFee', label: '契約事務手数料', color: COLOR_DANGER },
];

function BreakdownTooltip({
  active,
  payload,
  total,
}: {
  active?: boolean;
  payload?: Array<{ name?: string | number; value?: number | string; color?: string }>;
  total: number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <TooltipCard>
      <div className="font-semibold text-text mb-1">費用内訳</div>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-1.5">
          <span
            className="inline-block size-2 rounded-full"
            style={{ background: entry.color }}
          />
          <span className="text-text-muted">{entry.name}</span>
          <span className="font-semibold text-text ml-auto pl-3">
            {Number(entry.value ?? 0).toLocaleString()}円
          </span>
        </div>
      ))}
      <div className="mt-1 pt-1 border-t border-border flex items-center gap-1.5">
        <span className="text-text-muted">総額</span>
        <span className="font-semibold text-text ml-auto pl-3">{total.toLocaleString()}円</span>
      </div>
    </TooltipCard>
  );
}

/** 選択した滞在日数の費用内訳を1本の積み上げ横バーで表示する */
const CostBreakdownBar: React.FC<CostBreakdownBarProps> = ({ breakdown, total }) => {
  const data = [{ name: '内訳', ...breakdown }];
  // 光熱費0(utilities_included=true 等)の物件では光熱費セグメントを省略する
  const segments =
    breakdown.utilitiesTotal > 0
      ? SEGMENTS
      : SEGMENTS.filter((s) => s.key !== 'utilitiesTotal');

  return (
    <div className="flex flex-col gap-1">
      <TrendLegend items={segments.map((s) => ({ color: s.color, label: s.label }))} />
      <div className="w-full h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <XAxis type="number" hide domain={[0, 'dataMax']} />
            <YAxis type="category" dataKey="name" hide />
            <Tooltip
              content={<BreakdownTooltip total={total} />}
              cursor={false}
              isAnimationActive={false}
            />
            {segments.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId="cost"
                fill={s.color}
                barSize={24}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default CostBreakdownBar;
