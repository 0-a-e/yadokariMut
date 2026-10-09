import React, { useMemo, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Slider } from '@/components/ui/slider.tsx';
import type { PropertyFeature } from '../../types.ts';
import { formatYen } from '../../lib/format.ts';
import { KpiCard } from './charts/KpiCard.tsx';
import CostBreakdownBar from './charts/CostBreakdownBar.tsx';
import PlanCostCurveChart from './charts/PlanCostCurveChart.tsx';
import { buildPlanCurve, filterBrokenPlans, planDiscounts } from '../../lib/analysis/planCurve.ts';
import {
  calculateRentTotalByDays,
  getAsOfToday,
  type CalcOutcome,
} from '../../lib/rentCalculator.ts';
import { AsOfNote } from './AsOfNote.tsx';
import { EmptyState } from '@/components/shared/EmptyState.tsx';

interface PlanCostTabProps {
  feature: PropertyFeature;
}

/** スライダーで選べる最大滞在日数(カーブの掃引上限と揃える) */
const MAX_STAY_DAYS = 730;

/**
 * 物件モード・タブ「料金プラン」。滞在日数ごとの実質1日単価カーブで
 * プラン境界(30日/91日/181日)の段差=まとめ買い割引を見せ、
 * 選択日数の総額内訳と各プランの割引率を併記する。
 */
export const PlanCostTab: React.FC<PlanCostTabProps> = ({ feature }) => {
  const plans = feature.properties.rent_plans ?? [];
  const campaigns = feature.properties.campaigns;
  // 契約事務手数料は GeoJSON の BE 解決済み実効値(物件値 > サイト既定)。
  // null = 取得元サイトの既定が未登録で算出不能
  const contractFeeYen = feature.properties.contract_fee_yen ?? null;

  const [days, setDays] = useState(30);

  // 破損プラン(rent<=0)はカーブ・試算のいずれからも除外し警告表示する
  const { usable } = useMemo(() => filterBrokenPlans(plans), [plans]);
  const curve = useMemo(
    () => buildPlanCurve(plans, campaigns, 730, contractFeeYen),
    [plans, campaigns, contractFeeYen]
  );
  const discounts = useMemo(() => planDiscounts(plans), [plans]);
  const outcome: CalcOutcome = useMemo(
    () =>
      calculateRentTotalByDays({
        stayDays: days,
        plans: usable,
        campaigns,
        contractFeeYen,
        // 分析面は as-of-today 基準(契約)。滞在シミュレーション面はチェックイン日
        onDate: getAsOfToday(),
      }),
    [days, usable, campaigns, contractFeeYen]
  );

  if (plans.length === 0) {
    return <EmptyState message="料金プラン情報がありません。" />;
  }

  const perDay = outcome.ok ? Math.round(outcome.grandTotal / outcome.stayDays) : null;
  // 手数料不明(=総額・単価から除外)はグリッド上部で赤字警告する
  const feeUnknown =
    (outcome.ok ? outcome.breakdown.contractFee : contractFeeYen) == null;
  // 注記用の実際の手数料(パッケージキャンペーン適用時は outcome 側が減額後の値)
  const feeNote = outcome.ok
    ? outcome.breakdown.contractFee?.toLocaleString()
    : (contractFeeYen ?? null)?.toLocaleString();

  return (
    <>
      {curve.excludedPlans.length > 0 && (
        <Alert variant="destructive" className="text-xs">
          <AlertDescription>
            破損データのため一部プランを除外({curve.excludedPlans.join('、')})
          </AlertDescription>
        </Alert>
      )}
      {!outcome.ok && (
        <Alert variant="destructive" className="text-xs">
          <AlertDescription>{outcome.error}</AlertDescription>
        </Alert>
      )}
      {feeUnknown && (
        <p className="text-xs text-danger font-medium m-0 leading-relaxed">
          契約事務手数料が不明(取得元サイトの既定が未登録)のため、総額・実質1日単価から除外しています。
        </p>
      )}

      {/* ── KPI(選択中の日数の試算 + 最安点) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <KpiCard
          label={`適用プラン(${days.toLocaleString()}日)`}
          value={
            outcome.ok ? (
              <span className="text-sm">{outcome.selectedPlan.plan_name}</span>
            ) : (
              '-'
            )
          }
        />
        <KpiCard
          label="日額"
          value={outcome.ok ? formatYen(outcome.breakdown.rentDaily) : '-'}
        />
        <KpiCard
          label="総額"
          accent
          value={outcome.ok ? formatYen(outcome.grandTotal) : '-'}
        />
        <KpiCard
          label="実質1日単価"
          value={perDay != null ? formatYen(perDay) : '-'}
        />
        <KpiCard
          label="1日単価が最安になる日数"
          value={curve.cheapest ? `${curve.cheapest.days.toLocaleString()}日` : '-'}
        />
      </div>

      {/* ── 滞在日数スライダー ── */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-text">滞在日数</span>
          <span className="text-xs tabular-nums text-text-muted">
            {days.toLocaleString()}日
          </span>
        </div>
        <Slider
          aria-label="滞在日数"
          value={[days]}
          onValueChange={(vals) => {
            const v = Array.isArray(vals) ? vals[0] : vals;
            setDays(Math.min(MAX_STAY_DAYS, Math.max(1, Number(v))));
          }}
          min={1}
          max={MAX_STAY_DAYS}
          step={1}
        />
      </div>

      <PlanCostCurveChart
        rows={curve.rows}
        selectedDays={days}
        onSelectDays={setDays}
        labels={curve.labels}
      />

      {outcome.ok && (
        <CostBreakdownBar breakdown={outcome.breakdown} total={outcome.grandTotal} />
      )}

      {/* ── 定価→現在値の割引率チップ ── */}
      <div className="flex flex-wrap gap-1.5">
        {discounts.map((d) => (
          <Badge key={`${d.planCode}-${d.planName}`} variant="secondary">
            {d.planName}
            {d.discountPct != null ? (
              <span className="ml-1 text-success">
                {d.discountPct >= 0 ? `-${d.discountPct}%` : `+${Math.abs(d.discountPct)}%`}
              </span>
            ) : (
              <span className="ml-1 text-text-muted">割引なし</span>
            )}
          </Badge>
        ))}
      </div>

      <p className="text-[11px] text-text-muted m-0 leading-relaxed">
        実質1日単価 =(賃料+管理費+光熱費)×日数+清掃費+契約事務手数料
        {feeUnknown ? '不明(総額から除外)' : `${feeNote}円`} を日数で割った値。
      </p>
      <AsOfNote />
    </>
  );
};
