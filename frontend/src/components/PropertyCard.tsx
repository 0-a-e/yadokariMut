import React from 'react';
import { PriceMode, PropertyFeature } from '../types';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function getScoreColor(score: number): string {
  if (!score) return '#8e95a5';
  if (score >= 80) return '#00e676';
  if (score >= 60) return '#00f2fe';
  if (score >= 40) return '#ffb300';
  return '#ff1744';
}

interface PropertyCardProps {
  feature: PropertyFeature;
  isActive: boolean;
  onClick: () => void;
  priceMode?: PriceMode;
}

export const PropertyCard: React.FC<PropertyCardProps> = ({
  feature,
  isActive,
  onClick,
  priceMode = 'catalog',
}) => {
  const props = feature.properties;
  const score = props.total_score || 0;
  const scoreColor = getScoreColor(score);
  const scoreRound = Math.round(score);
  const est = props.stay_estimate;
  const stayMode = priceMode === 'stay' && est?.ok && est.stayTotalYen != null;

  return (
    <Card
      onClick={onClick}
      size="sm"
      className={`
        cursor-pointer transition-all duration-300
        hover:border-primary hover:bg-primary/[0.04] hover:-translate-y-0.5
        ${isActive ? '!border-primary !bg-primary/[0.04] -translate-y-0.5' : ''}
      `}
    >
      <CardContent className="flex gap-3 p-3">
        <div
          className="w-20 h-20 rounded-lg bg-cover bg-center shrink-0 relative bg-white/[0.05]"
          style={{ backgroundImage: `url('${props.thumbnail_url || ''}')` }}
        >
          <Badge
            className="absolute top-1 left-1 text-xs font-bold py-0.5 px-1.5 border-0"
            style={{ background: scoreColor }}
          >
            {scoreRound}
          </Badge>
        </div>

        <div className="flex flex-col justify-between min-w-0 grow">
          <div>
            <div
              className="text-sm font-semibold whitespace-nowrap overflow-hidden text-ellipsis"
              title={props.title}
            >
              {props.title || '無題の物件'}
            </div>
            {(props.source_display_name || props.source_site) && (
              <div className="mt-0.5">
                <Badge variant="secondary" className="text-[10px] py-0 px-1.5 font-normal">
                  {props.source_display_name || props.source_site}
                </Badge>
              </div>
            )}
            <div className="text-xs text-text-muted whitespace-nowrap overflow-hidden text-ellipsis mt-0.5">
              {props.layout || ''} {props.area_m2 ? `| ${props.area_m2}㎡` : ''}
            </div>
            <div
              className="text-xs text-text-muted whitespace-nowrap overflow-hidden text-ellipsis"
              title={props.access_summary}
            >
              {props.access_summary || ''}
            </div>
          </div>
          <div className="flex justify-between items-end mt-1 gap-2">
            {stayMode ? (
              <div className="min-w-0">
                <div className="text-sm font-bold text-accent">
                  {est!.stayTotalYen!.toLocaleString()}円
                </div>
                <div className="text-[11px] text-text-muted flex flex-wrap items-center gap-1">
                  <span>
                    {est!.stayDays}日
                    {est!.planLabel ? ` · ${est!.planLabel}` : ''}
                  </span>
                  {est!.rentDailyYen != null && (
                    <span>· {est!.rentDailyYen.toLocaleString()}円/日相当</span>
                  )}
                  {est!.usedFallback && (
                    <Badge
                      variant="outline"
                      className="text-[10px] py-0 px-1 h-4 border-border/60 text-text-muted font-normal"
                    >
                      プラン代替
                    </Badge>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-sm font-bold text-accent">
                {props.min_daily_rent
                  ? `${props.min_daily_rent.toLocaleString()}円/日`
                  : '詳細参照'}{' '}
                <span className="text-xs font-normal text-text-muted">
                  {props.min_plan_total
                    ? `(総額:${props.min_plan_total.toLocaleString()}円)`
                    : ''}
                </span>
              </div>
            )}
            {props.shortlist_status === 'saved' && (
              <Badge
                variant="outline"
                className="text-xs font-semibold py-0.5 px-1.5 uppercase bg-success/[0.15] text-success border-success/30 shrink-0"
              >
                Saved
              </Badge>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
