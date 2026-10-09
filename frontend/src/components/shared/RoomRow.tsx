/**
 * 部屋行の表示正本(docs/fe-floor-orientation-redesign-plan.md §4.3 / D7)。
 *
 * サイドバー建物カードのアコーディオン部屋一覧(dense)と、建物詳細パネルの
 * 部屋一覧(normal)が共有する唯一の実装。旧実装は 2 本あり、一致マーク・
 * 保存マーク・掲載終了・価格整形をそれぞれ再実装していた(A1)。
 *
 * 所在階・方角は「データがある場合のみ」表示する(§4.2)。
 * - 所在階: floor_number / floor_number_max → 「5階」「地下1階」「1〜2階」
 * - 方角: orientation_deg → 16 風位「南東」(bratto は原理的に null)
 *
 * 見た目は hextaUI `item`(base-ui)で構成する。固定幅の桁揃え(w-12)は
 * 11px 前提で拡張余地が無かったため、flex + tabular-nums へ置き換えた。
 */
import type { ReactNode } from 'react';
import { Bookmark, CircleCheck, Compass } from 'lucide-react';
import { Badge } from '@/components/ui/badge.tsx';
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from '@/components/ui/item.tsx';
import { cn } from '@/lib/utils.ts';
import type { BuildingUnit, PriceMode } from '../../types.ts';
import { roomFloorLabel, roomOrientationLabel } from '../../lib/room.ts';
import { formatDailyRentDisplay, formatYen, hasStayEstimate } from '../../lib/format.ts';

export interface RoomRowProps {
  unit: BuildingUnit;
  /** フィルタ条件を通過した部屋(一致マーク/バッジ) */
  matched: boolean;
  /** catalog=カタログ日額 / stay=期間総額(Worker 試算) */
  priceMode: PriceMode;
  onClick: (unit: BuildingUnit) => void;
  /**
   * dense = サイドバー建物カードのアコーディオン(2 行・小サイズ)
   * normal = 建物詳細パネルの部屋一覧(カード型・チップ表示)
   */
  density?: 'dense' | 'normal';
  className?: string;
}

/** 部屋の所在階・方角のファクトチップ(データがある分のみ)。他画面からも再利用する */
export function RoomFactChips({
  unit,
  className,
  size = 'sm',
}: {
  unit: Pick<BuildingUnit, 'floor_number' | 'floor_number_max' | 'orientation_deg'>;
  className?: string;
  size?: 'sm' | 'xs';
}) {
  const floor = roomFloorLabel(unit);
  const orientation = roomOrientationLabel(unit);
  if (!floor && !orientation) return null;
  const chip = cn(
    'inline-flex items-center gap-0.5 rounded border border-border/70 bg-white/[0.04] px-1 py-0 font-normal text-text-muted',
    size === 'xs' ? 'text-[10px]' : 'text-[11px]',
  );
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      {floor && (
        <span className={chip} title="所在階">
          {floor}
        </span>
      )}
      {orientation && (
        <span className={chip} title="部屋の向き">
          <Compass className="size-2.5" aria-hidden="true" />
          {orientation}
        </span>
      )}
    </span>
  );
}

/** 部屋の価格表示(モード別の正本) */
export function roomPriceLabel(unit: BuildingUnit, priceMode: PriceMode): string {
  const est = unit.stay_estimate;
  if (priceMode === 'stay' && hasStayEstimate(est)) {
    return `${formatYen(est!.stayTotalYen)}(期間総額)`;
  }
  return unit.min_daily_rent != null ? `${formatYen(unit.min_daily_rent)}/日` : '詳細参照';
}

export function RoomRow({
  unit,
  matched,
  priceMode,
  onClick,
  density = 'normal',
  className,
}: RoomRowProps) {
  const dense = density === 'dense';
  const inactive = unit.is_active === false;
  const saved = unit.shortlist_status === 'saved';
  const area = unit.area_m2 != null ? `${unit.area_m2}㎡` : null;
  const price = roomPriceLabel(unit, priceMode);
  const densePrice =
    priceMode === 'stay' && hasStayEstimate(unit.stay_estimate)
      ? formatYen(unit.stay_estimate!.stayTotalYen)
      : formatDailyRentDisplay(unit.min_daily_rent);

  /**
   * 一致マーク。背景はテーマのダーク面(bg-bg)+ヘアライン、アイコンは成功色のまま
   * 拡大して視認性を確保する。
   *
   * ItemMedia(variant="icon")は使わない: xs サイズでは `not-data-tone` の
   * group ルールが背景とリングを打ち消し、tone を付けるとタイル全面が緑に塗られて
   * アイコンが同化する(いずれも variant 修飾のため className で上書きできない)。
   * プレーンな span にして見た目を確定的にする。
   */
  const matchedIcon: ReactNode = matched ? (
    <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-bg ring-1 ring-border">
      <CircleCheck className="size-3.5 text-success" aria-label="フィルタ一致" />
    </span>
  ) : null;

  return (
    <Item
      size={dense ? 'xs' : 'sm'}
      render={
        <button
          type="button"
          onClick={() => onClick(unit)}
          title={unit.title ?? undefined}
        />
      }
      className={cn(
        dense
          ? 'gap-1.5 px-1.5 py-1 text-[11px]'
          : cn(
              'gap-2 rounded-lg border px-3 py-2 text-sm',
              matched
                ? 'border-primary/50 bg-primary/[0.07] hover:bg-primary/[0.12]'
                : 'border-border bg-white/[0.02] hover:bg-white/[0.05]',
            ),
        inactive && (dense ? 'text-text-muted/60' : 'opacity-55'),
        className,
      )}
    >
      {dense ? matchedIcon : null}
      <ItemContent className={dense ? 'gap-0' : 'gap-0.5'}>
        <ItemTitle
          className={cn(
            'flex w-full items-center gap-1.5',
            dense ? 'text-[11px] font-normal' : 'text-sm font-medium text-text',
          )}
        >
          <span className="truncate">
            {unit.layout ?? '—'}
            {area && <span className="text-text-muted"> {area}</span>}
          </span>
          {!dense && <RoomFactChips unit={unit} />}
          {saved && <Bookmark className="size-3 shrink-0 text-primary" aria-label="保存済み" />}
          {!dense && inactive && (
            <Badge variant="outline" className="h-auto px-1 py-0 text-[9px]">
              掲載終了
            </Badge>
          )}
        </ItemTitle>
        {dense ? (
          <RoomFactChips unit={unit} size="xs" className="mt-0.5" />
        ) : (
          <ItemDescription className="text-xs text-text-muted">{price}</ItemDescription>
        )}
      </ItemContent>
      <ItemActions className={dense ? 'text-[11px] font-semibold' : undefined}>
        {dense ? (
          <span className="tabular-nums">{densePrice}</span>
        ) : (
          matched && (
            <Badge variant="outline" className="h-auto shrink-0 gap-1 py-0.5 text-[10px]">
              <CircleCheck className="size-2.5 text-success" />
              条件一致
            </Badge>
          )
        )}
      </ItemActions>
    </Item>
  );
}
