/**
 * 「ご利用料金」のプラン別料金テーブル。プランが無い場合は代替文言を表示する。
 */
import React from 'react';
import type { RentPlan } from '../../types.ts';
import { Table, TableHeader, TableBody, TableHead, TableRow, TableCell } from '@/components/ui/table.tsx';

export const RentPlansTable: React.FC<{ plans: RentPlan[] }> = ({ plans }) => {
  if (!plans || plans.length === 0) {
    return (
      <p className="text-sm leading-[1.6] text-text-muted italic">
        料金プラン情報がありません
      </p>
    );
  }

  return (
    <Table className="mt-1 text-xs">
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
            プラン
          </TableHead>
          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
            賃料 (日額/総額)
          </TableHead>
          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
            管理費
          </TableHead>
          <TableHead className="text-xs font-semibold uppercase tracking-[0.5px] text-text-muted">
            清掃費
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {plans.map((plan, idx) => {
          let rentText = <span className="text-text-muted italic">取扱無</span>;
          let mngText = '-';
          let clnText = '-';

          if (plan.available) {
            const effDaily =
              plan.effective_daily_rent_yen ?? plan.discounted_daily_rent_yen;
            const effTotal =
              plan.effective_total_yen ?? plan.discounted_total_yen;
            const dailyVal = effDaily
              ? `${effDaily.toLocaleString()}円/日`
              : '0円/日';
            const showOriginalStrike =
              plan.original_daily_rent_yen != null &&
              effDaily != null &&
              plan.original_daily_rent_yen !== effDaily;
            const originalVal = showOriginalStrike ? (
              <span className="line-through text-text-muted text-xs mr-1">
                {plan.original_daily_rent_yen!.toLocaleString()}円
              </span>
            ) : null;
            const totalVal =
              effTotal && plan.total_period_days ? (
                <span className="text-xs text-text-muted block mt-0.5">
                  ({plan.total_period_days}日総額:{' '}
                  {effTotal.toLocaleString()}円)
                </span>
              ) : null;
            const appliedLabel =
              plan.effective_campaign_label ??
              (plan.campaign_applied ? plan.campaign_label : null);
            const campaignVal = appliedLabel ? (
              <>
                <br />
                <span className="inline-block bg-primary/[0.15] text-[#a37aff] py-0.5 px-1.5 rounded text-xs font-semibold mt-0.5 border border-primary/30">
                  {appliedLabel}
                </span>
              </>
            ) : plan.campaign_expired ? (
              <>
                <br />
                <span className="inline-block bg-white/10 text-text-muted py-0.5 px-1.5 rounded text-xs font-semibold mt-0.5 border border-border/50">
                  {plan.expired_campaign_label || 'キャンペーン'}（適用終了）
                </span>
              </>
            ) : null;

            rentText = (
              <>
                <span className="text-accent font-bold">
                  {originalVal}
                  {dailyVal}
                </span>
                {campaignVal}
                {totalVal}
              </>
            );
            mngText =
              plan.management_fee_daily_yen != null
                ? `${plan.management_fee_daily_yen.toLocaleString()}円/日`
                : '0円/日';
            clnText =
              plan.cleaning_fee_yen != null
                ? `${plan.cleaning_fee_yen.toLocaleString()}円`
                : '0円';
          }

          return (
            <TableRow key={idx}>
              <TableCell className="font-semibold">{plan.plan_name}</TableCell>
              <TableCell>{rentText}</TableCell>
              <TableCell>{mngText}</TableCell>
              <TableCell>{clnText}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};
