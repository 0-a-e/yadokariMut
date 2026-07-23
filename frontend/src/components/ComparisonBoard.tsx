import React, { useMemo } from 'react';
import type { PropertyFeature } from '../types';
import { computeStayEstimate } from '../lib/filterLogic';
import {
  activeCampaignSummary,
  COMPARISON_BOARD_ROWS,
  computeHighlightIds,
  type ComparisonPropertyInput,
} from '../lib/comparisonRows';
import { EXPLORER_MAX_COMPARE } from '../lib/explorerSearch';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { FaScaleBalanced, FaMapLocationDot, FaCheck } from 'react-icons/fa6';

export interface ComparisonBoardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Picker candidates (saved shortlist + any compare targets resolved from map data).
   */
  candidateFeatures: PropertyFeature[];
  /** Explicit compare id list (URL SoT). */
  compareIds: number[];
  onCompareIdsChange: (ids: number[]) => void;
  checkIn: string;
  checkOut: string;
  onSelectFeature: (id: number) => void;
}

function toComparisonInput(
  f: PropertyFeature,
  checkIn: string,
  checkOut: string,
): ComparisonPropertyInput {
  const p = f.properties;
  const est =
    p.stay_estimate?.ok && p.stay_estimate.stayTotalYen != null
      ? p.stay_estimate
      : computeStayEstimate(p, checkIn, checkOut);
  return {
    id: p.id,
    title: p.title || `ID ${p.id}`,
    catalogDailyYen: p.min_daily_rent,
    stayTotalYen: est?.ok ? est.stayTotalYen : null,
    stayDays: est?.ok ? est.stayDays : null,
    layout: p.layout,
    areaM2: p.area_m2,
    walkMinutes: p.min_walk_minutes,
    score: p.total_score,
    address: p.address,
    featureSummary: p.feature_summary,
    campaignsActive: activeCampaignSummary(p.campaigns),
    shortlistStatus: p.shortlist_status,
    shortlistComment: p.shortlist_comment ?? null,
  };
}

export const ComparisonBoard: React.FC<ComparisonBoardProps> = ({
  open,
  onOpenChange,
  candidateFeatures,
  compareIds,
  onCompareIdsChange,
  checkIn,
  checkOut,
  onSelectFeature,
}) => {
  const selectedFeatures = useMemo(() => {
    const map = new Map(candidateFeatures.map((f) => [f.properties.id, f]));
    return compareIds
      .map((id) => map.get(id))
      .filter(Boolean) as PropertyFeature[];
  }, [candidateFeatures, compareIds]);

  const rowsData = useMemo(
    () => selectedFeatures.map((f) => toComparisonInput(f, checkIn, checkOut)),
    [selectedFeatures, checkIn, checkOut],
  );

  const highlights = useMemo(
    () => computeHighlightIds(rowsData, COMPARISON_BOARD_ROWS),
    [rowsData],
  );

  const missingIds = useMemo(() => {
    const have = new Set(candidateFeatures.map((f) => f.properties.id));
    return compareIds.filter((id) => !have.has(id));
  }, [candidateFeatures, compareIds]);

  const toggleId = (id: number) => {
    if (compareIds.includes(id)) {
      onCompareIdsChange(compareIds.filter((x) => x !== id));
      return;
    }
    if (compareIds.length >= EXPLORER_MAX_COMPARE) return;
    onCompareIdsChange([...compareIds, id]);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="h-[min(92dvh,880px)] max-h-[92dvh] w-full sm:max-w-none p-0 gap-0 bg-panel border-border text-text"
        showCloseButton
      >
        <SheetHeader className="border-b border-border px-4 py-3 shrink-0">
          <SheetTitle className="flex items-center gap-2 text-text">
            <FaScaleBalanced className="text-accent" />
            比較ボード
          </SheetTitle>
          <SheetDescription className="text-text-muted">
            最大{EXPLORER_MAX_COMPARE}件を横並び比較（期間総額は {checkIn} 〜 {checkOut}）。
            共有 URL の compare は明示 ID リストです。
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-4 overflow-y-auto min-h-0 flex-1 p-4 app-scrollbar">
          {candidateFeatures.length === 0 && compareIds.length === 0 ? (
            <p className="text-sm text-text-muted">
              比較対象がありません。詳細パネルで「保存」するか、共有 URL の compare
              で物件 ID を指定してください。
            </p>
          ) : (
            <>
              <div className="flex flex-col gap-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                  比較する物件（{compareIds.length}/{EXPLORER_MAX_COMPARE}）
                </div>
                {missingIds.length > 0 && (
                  <p className="text-xs text-amber-400/90">
                    データ未取得または非表示の ID: {missingIds.join(', ')}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {candidateFeatures.map((f) => {
                    const id = f.properties.id;
                    const checked = compareIds.includes(id);
                    const disabled = !checked && compareIds.length >= EXPLORER_MAX_COMPARE;
                    const isSaved = f.properties.shortlist_status === 'saved';
                    return (
                      <button
                        key={id}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleId(id)}
                        className={cn(
                          'inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors max-w-full text-left',
                          checked
                            ? 'border-primary/50 bg-primary/10 text-text'
                            : 'border-border bg-white/[0.03] text-text-muted hover:border-primary/30',
                          disabled && 'opacity-40 cursor-not-allowed',
                        )}
                      >
                        <span
                          className={cn(
                            'flex size-4 shrink-0 items-center justify-center rounded border text-[10px]',
                            checked
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-input',
                          )}
                        >
                          {checked ? <FaCheck /> : null}
                        </span>
                        <span className="truncate max-w-[200px]">
                          {f.properties.title || `ID ${id}`}
                        </span>
                        {!isSaved && (
                          <Badge variant="secondary" className="text-[10px] py-0 px-1 shrink-0">
                            URL
                          </Badge>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {rowsData.length === 0 ? (
                <p className="text-sm text-text-muted">
                  比較する物件を1件以上選んでください。
                </p>
              ) : (
                <div className="w-full overflow-x-auto rounded-xl border border-border bg-black/20">
                  <table className="w-full text-xs border-collapse min-w-[480px]">
                    <thead>
                      <tr>
                        <th className="text-left p-2.5 border-b border-border text-text-muted sticky left-0 bg-[#1a1c26] z-10 min-w-[96px]">
                          項目
                        </th>
                        {rowsData.map((p) => (
                          <th
                            key={p.id}
                            className="text-left p-2.5 border-b border-border text-text font-semibold min-w-[140px] max-w-[180px] align-bottom"
                          >
                            <div className="flex flex-col gap-1.5 items-start">
                              <button
                                type="button"
                                className="text-accent hover:underline text-left leading-snug"
                                onClick={() => {
                                  onSelectFeature(p.id);
                                  onOpenChange(false);
                                }}
                              >
                                {p.title}
                              </button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 text-[11px] px-2"
                                onClick={() => {
                                  onSelectFeature(p.id);
                                  onOpenChange(false);
                                }}
                              >
                                <FaMapLocationDot data-icon="inline-start" />
                                地図
                              </Button>
                            </div>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {COMPARISON_BOARD_ROWS.map((row) => (
                        <tr key={row.key} className="border-b border-border/40">
                          <td className="p-2.5 text-text-muted sticky left-0 bg-[#1a1c26] font-medium z-10">
                            {row.label}
                          </td>
                          {rowsData.map((p) => {
                            const win = highlights[row.key]?.has(p.id);
                            return (
                              <td
                                key={p.id}
                                className={cn(
                                  'p-2.5 text-text align-top max-w-[180px] break-words',
                                  win && 'text-accent font-semibold bg-primary/[0.07]',
                                )}
                              >
                                {row.get(p)}
                                {win && (
                                  <Badge
                                    variant="secondary"
                                    className="ml-1 text-[10px] py-0 px-1 align-middle"
                                  >
                                    最良
                                  </Badge>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
};
