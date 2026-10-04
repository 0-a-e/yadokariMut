import React from 'react';
import { Badge } from '@/components/ui/badge.tsx';
import { KpiCard } from '@/components/analysis/charts/KpiCard.tsx';
import { FaArrowRightLong } from 'react-icons/fa6';
import { priceDeltaFromHistory } from '@/lib/analysis/propertyHistory.ts';
import type { PropertyFeature } from '../../types.ts';

interface PropertyHeaderProps {
  feature: PropertyFeature;
  /** ヘッダの「市場全体を見る」でコンテキストを市場に戻す */
  onOpenMarket: () => void;
}

/** 物件モードのヘッダ: サムネ+物件名+基本KPI。市場全体タブへの導線も持つ */
export const PropertyHeader: React.FC<PropertyHeaderProps> = ({
  feature,
  onOpenMarket,
}) => {
  const p = feature.properties;
  const thumb = p.thumbnail_url || p.images?.[0] || null;
  const delta = p.price_history ? priceDeltaFromHistory(p.price_history) : null;
  const planCount = p.rent_plans?.length ?? 0;

  return (
    <div className="flex items-center gap-4 flex-wrap">
      <div className="flex items-center gap-3 min-w-0 flex-1">
        {thumb ? (
          <div
            className="size-14 rounded-lg bg-cover bg-center border border-border shrink-0"
            style={{ backgroundImage: `url('${thumb}')` }}
            role="img"
            aria-label={p.title ?? undefined}
          />
        ) : (
          <div className="size-14 rounded-lg border border-border bg-white/[0.04] shrink-0" />
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-bold text-text truncate max-w-[36rem]" title={p.title ?? undefined}>
              {p.title || '無題の物件'}
            </h2>
            {p.source_display_name && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
                {p.source_display_name}
              </Badge>
            )}
          </div>
          <div className="text-xs text-text-muted mt-0.5 truncate">
            {[p.municipality || p.prefecture_name, p.layout, p.area_m2 ? `${p.area_m2}㎡` : null]
              .filter(Boolean)
              .join(' · ')}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 shrink-0">
        <KpiCard
          label="現在日額"
          value={p.min_daily_rent ? `${p.min_daily_rent.toLocaleString()}円` : '-'}
          accent
        />
        {delta ? (
          <KpiCard
            label="前回比"
            value={
              <span className={delta.delta < 0 ? 'text-success' : delta.delta > 0 ? 'text-danger' : ''}>
                {delta.delta === 0 ? '変動なし' : `${delta.delta > 0 ? '+' : ''}${delta.delta.toLocaleString()}円`}
              </span>
            }
          />
        ) : (
          <KpiCard label="前回比" value="-" />
        )}
        <KpiCard label="プラン数" value={`${planCount}`} />
      </div>

      <button
        type="button"
        onClick={onOpenMarket}
        data-testid="analysis-open-market"
        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-transparent border border-border rounded-md px-2.5 py-1.5 cursor-pointer transition-colors shrink-0"
      >
        市場全体を見る
        <FaArrowRightLong />
      </button>
    </div>
  );
};
