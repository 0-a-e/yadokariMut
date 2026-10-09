/**
 * キャンペーン情報のカード一覧。割引構造の要約文言(structBits)の組み立てもここに持つ。
 */
import React from 'react';
import type { Campaign } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { Card } from '@/components/ui/card.tsx';
import { formatYen } from '../../lib/format.ts';
import { FaRegCalendar, FaCircleInfo } from 'react-icons/fa6';

export const CampaignCards: React.FC<{ campaigns: Campaign[] }> = ({ campaigns }) => {
  return (
    <div className="flex flex-col gap-2.5 mt-1">
      {campaigns.map((cam, idx) => {
        // 表示の正は BE 解決の target_plan_label(設計 §3.6。all=すべてのプラン含む)。
        // 欠損(旧キャッシュ)時のみ target_plan_code 生値にフォールバック。
        const planName = cam.target_plan_label
          || (cam.target_plan_code ? cam.target_plan_code : null);
        // BE campaigns に is_active / date_end_unknown 列は無い(常時有効扱い)

        return (
          <Card
            key={idx}
            className="p-3 border border-success/30 bg-success/[0.03] shadow-[0_2px_8px_rgba(34,197,94,0.05)] transition-all duration-300"
          >
            <div className="flex justify-between items-start gap-2 mb-1.5">
              <div className="flex flex-wrap gap-1.5 items-center">
                <Badge
                  variant="default"
                  className="text-xs font-bold px-1.5 py-0.5 bg-success text-white"
                >
                  {cam.campaign_type || 'キャンペーン'}
                </Badge>
                {planName && (
                  <Badge
                    variant="outline"
                    className="text-xs px-1.5 py-0.5 border-[#a37aff]/30 text-[#a37aff]"
                  >
                    {planName}
                  </Badge>
                )}
              </div>
            </div>
            <h4 className="text-xs font-bold text-white mb-1">{cam.title}</h4>
            <p className="text-xs text-text/80 leading-[1.5] mb-2">{cam.content}</p>
            {(() => {
              const structBits: string[] = [];
              if (cam.discount_unit === 'yen' && cam.discount_value != null) {
                structBits.push(`日額 ${formatYen(cam.discount_value)}引き`);
              } else if (
                cam.discount_unit === 'percent' &&
                cam.discount_value != null
              ) {
                structBits.push(`${cam.discount_value}% OFF`);
              } else if (
                cam.discount_unit === 'package' &&
                cam.package_total_benefit_yen != null
              ) {
                structBits.push(
                  `お得額 最大${formatYen(cam.package_total_benefit_yen)}`
                );
              } else if (
                cam.discount_unit === 'pokkiri' &&
                cam.discount_value != null
              ) {
                structBits.push(
                  `月額 ${formatYen(cam.discount_value)}ポッキリ`
                );
              } else if (cam.discount_unit === 'free_first_week') {
                structBits.push('初週無料');
              }
              if (cam.period_max_days != null)
                structBits.push(`最大${cam.period_max_days}日適用`);
              if (cam.discount_max_yen != null)
                structBits.push(`上限${formatYen(cam.discount_max_yen)}`);
              if (cam.stay_min_days != null || cam.stay_max_days != null) {
                const a =
                  cam.stay_min_days != null ? `${cam.stay_min_days}日` : '';
                const b =
                  cam.stay_max_days != null ? `${cam.stay_max_days}日` : '';
                structBits.push(`滞在 ${a}${a && b ? '〜' : ''}${b}`);
              }
              return structBits.length > 0 ? (
                <p className="text-xs text-accent/90 mb-2 m-0 leading-relaxed">
                  {structBits.join(' · ')}
                </p>
              ) : null;
            })()}

            <div className="grid grid-cols-1 gap-1 text-xs text-text-muted border-t border-border/40 pt-1.5 mt-1.5">
              <div className="flex items-start gap-1">
                <FaRegCalendar className="text-accent mt-[1px]" />
                <span>
                  <strong>期間: </strong>
                  {cam.starts_on && cam.ends_on
                    ? `${cam.starts_on.replace(/-/g, '/')} 〜 ${cam.ends_on.replace(/-/g, '/')}`
                    : cam.target_period_text || '期間指定なし'}
                </span>
              </div>
              {cam.target_condition_text && (
                <div className="flex items-start gap-1">
                  <FaCircleInfo className="text-accent mt-[1px]" />
                  <span>
                    <strong>条件: </strong>
                    {cam.target_condition_text}
                  </span>
                </div>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
};
