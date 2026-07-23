import React, { useMemo, useCallback } from 'react';
import { Campaign, RentPlan } from '../types';
import {
  calculateRentTotal,
  type PlanCode,
  PLAN_LABELS,
} from '../lib/rentCalculator';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { FaCalculator, FaCircleInfo } from 'react-icons/fa6';

interface RentSimulatorProps {
  plans: RentPlan[];
  campaigns?: Campaign[];
  /** @deprecated kept for call-site compatibility */
  propertyId?: number;
  /** Hide the section title when embedded in an Accordion */
  hideTitle?: boolean;
  checkIn: string;
  checkOut: string;
  onDatesChange: (checkIn: string, checkOut: string) => void;
}

function yen(n: number): string {
  return `${n.toLocaleString()}円`;
}

export const RentSimulator: React.FC<RentSimulatorProps> = ({
  plans,
  campaigns,
  hideTitle = false,
  checkIn,
  checkOut,
  onDatesChange,
}) => {
  const handleCheckIn = useCallback(
    (value: string) => {
      const nextOut = checkOut && value && checkOut < value ? value : checkOut;
      onDatesChange(value, nextOut);
    },
    [checkOut, onDatesChange],
  );

  const result = useMemo(
    () => calculateRentTotal({ checkIn, checkOut, plans, campaigns }),
    [checkIn, checkOut, plans, campaigns],
  );

  const availableCount = plans.filter((p) => p.available).length;
  if (availableCount === 0) {
    return null;
  }

  return (
    <div>
      {!hideTitle && (
        <h3 className="text-sm font-semibold uppercase tracking-[0.5px] text-text-muted border-b border-border pb-1 mb-2 flex items-center gap-1.5">
          <FaCalculator className="text-accent" />
          料金シミュレーター
        </h3>
      )}

      <Card className="p-0 border-border/80">
        <CardContent className="p-3 flex flex-col gap-3">
          <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-end max-md:grid-cols-1">
            <label className="flex flex-col gap-1 min-w-0">
              <span className="text-xs text-text-muted">入居日</span>
              <Input
                type="date"
                value={checkIn}
                onChange={(e) => handleCheckIn(e.target.value)}
                className="bg-white/[0.04] text-sm"
              />
            </label>
            <span className="text-text-muted text-sm pb-2 text-center max-md:hidden">〜</span>
            <label className="flex flex-col gap-1 min-w-0">
              <span className="text-xs text-text-muted">退去日</span>
              <Input
                type="date"
                value={checkOut}
                min={checkIn || undefined}
                onChange={(e) => onDatesChange(checkIn, e.target.value)}
                className="bg-white/[0.04] text-sm"
              />
            </label>
          </div>

          {!result.ok ? (
            <p className="text-sm text-warning m-0">{result.error}</p>
          ) : (
            <div className="flex flex-col gap-2.5">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-text-muted">ご利用日数</span>
                <span className="font-bold text-accent">{result.stayDays.toLocaleString()}日</span>
                <Badge variant="outline" className="text-xs border-primary/40 text-[#a37aff]">
                  {PLAN_LABELS[result.selectedPlanCode as PlanCode] || result.selectedPlan.plan_name}
                </Badge>
                {result.usedFallback && (
                  <Badge variant="secondary" className="text-xs">
                    プラン代替
                  </Badge>
                )}
              </div>

              {result.fallbackNote && (
                <p className="text-xs text-text-muted m-0 leading-relaxed flex gap-1.5 items-start">
                  <FaCircleInfo className="mt-0.5 shrink-0" />
                  <span>{result.fallbackNote}</span>
                </p>
              )}

              <div className="rounded-lg border border-border/60 bg-white/[0.02] overflow-hidden text-xs">
                <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 px-2.5 py-1.5 border-b border-border/40 text-text-muted">
                  <span>内訳</span>
                  <span className="text-right">計算</span>
                  <span className="text-right min-w-[5.5rem]">金額</span>
                </div>
                <BreakdownRow
                  label="賃料"
                  calc={`${result.breakdown.rentDaily.toLocaleString()}円 × ${result.stayDays}日`}
                  amount={result.breakdown.rentTotal}
                />
                <BreakdownRow
                  label="管理費"
                  calc={`${result.breakdown.managementDaily.toLocaleString()}円 × ${result.stayDays}日`}
                  amount={result.breakdown.managementTotal}
                />
                <BreakdownRow label="清掃費" amount={result.breakdown.cleaningFee} />
                <BreakdownRow label="契約事務手数料" amount={result.breakdown.contractFee} />
                <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 px-2.5 py-2 bg-primary/[0.08] border-t border-border/50 font-bold text-sm">
                  <span>合計</span>
                  <span />
                  <span className="text-right text-accent min-w-[5.5rem]">
                    {yen(result.grandTotal)}
                  </span>
                </div>
              </div>

              {result.warnings
                .filter((w) => w !== result.fallbackNote)
                .map((w, i) => (
                  <p
                    key={i}
                    className="text-xs text-text-muted m-0 leading-relaxed flex gap-1.5 items-start"
                  >
                    <FaCircleInfo className="mt-0.5 shrink-0 text-accent" />
                    <span>{w}</span>
                  </p>
                ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

const BreakdownRow: React.FC<{ label: string; calc?: string; amount: number }> = ({
  label,
  calc,
  amount,
}) => (
  <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 px-2.5 py-1.5 border-b border-border/30 last:border-0">
    <span className="text-text">{label}</span>
    <span className="text-text-muted text-right">{calc || ''}</span>
    <span className="text-right min-w-[5.5rem] font-medium">{yen(amount)}</span>
  </div>
);
