/**
 * 建物パネル(Phase B2-γ・docs/building-aggregation-b2-fe-plan.md §4.3)。
 *
 * 詳細 2 層の上層: 建物サマリ(代表写真ギャラリー/スペック/アクセス/建物設備/
 * ソース別名)と部屋一覧を表示し、部屋行クリックで既存の部屋パネル(DetailPanel)
 * へ繋ぐ。選択導線・URL(?b=)は useSelectedFeature が担う。
 *
 * - ギャラリー: composeBuildingGallery(承認仕様)のスライドから URL を ImageCarousel へ
 *   (url=カルーセル用 thumb variant / fullUrl=ライトボックス用オリジナル)
 * - スペック: hextaUI ItemGroup で項目立て(§5.2)。階数は buildingFloorsLabel
 *   (確定「8階建」/ 確定値が無ければ下限「6階以上」で断定しない・§5.1 D5)
 * - 部屋行: shared/RoomRow(normal)へ一本化。フィルタ一致は matched として強調
 * - 並び順: sortRooms(価格順=既定 / 階順)(§6.3)
 * - まとめて非表示: saved 以外の active 部屋へ hide(bulkHideTargetUnits・確認ダイアログ付き)
 */
import React, { useMemo, useRef, useState } from 'react';
import type { BuildingFeature, BuildingUnit } from '../../types.ts';
import { FEATURE_TOGGLE_OPTIONS } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog.tsx';
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from '@/components/ui/item.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select.tsx';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { ImageCarousel } from './ImageCarousel.tsx';
import { RoomRow } from '@/components/shared/RoomRow.tsx';
import {
  bulkHideTargetUnits,
  buildingAgeStructureParts,
  buildingDisplayName,
  buildingFloorInfo,
  buildingFloorsLabel,
  composeBuildingGallery,
  roomCounts,
  sortRooms,
  ROOM_SORT_DEFAULT,
  ROOM_SORT_OPTIONS,
  type RoomSortMode,
} from '../../lib/building.ts';
import { formatYen, formatRentBand } from '../../lib/format.ts';
import { formatFloorRange } from '../../lib/room.ts';
import { useIsMobile } from '../../hooks/useIsMobile.ts';
import { useSwipeDismiss } from '../../hooks/useSwipeDismiss.ts';
import {
  FaXmark,
  FaBookmark,
  FaEyeSlash,
  FaScaleBalanced,
  FaTrain,
} from 'react-icons/fa6';

/** feature_categories code → トグル語彙ラベル(FEATURE_TOGGLE_OPTIONS は UI copy の正本) */
const FEATURE_LABEL_MAP: ReadonlyMap<string, string> = new Map(
  FEATURE_TOGGLE_OPTIONS.map((o) => [o.value, o.label]),
);

export function featureCategoryLabel(code: string): string {
  return FEATURE_LABEL_MAP.get(code) ?? code;
}

/**
 * 並び順の表示ラベル(§6.3)。方向アローは「昇順=↑ / 降順=↓」の標準慣習で、
 * 文言(低い順 / 高い順)が曖昧さを消す。
 */
function roomSortLabel(opt: (typeof ROOM_SORT_OPTIONS)[number]): React.ReactNode {
  const Icon = opt.direction === 'asc' ? ArrowUp : ArrowDown;
  return (
    <>
      <Icon className="size-3.5 text-text-muted" aria-hidden="true" />
      {opt.label}
    </>
  );
}

/** Select の選択値ラベル(値→ラベルの対応。base-ui の items へ渡す) */
const roomSortItemMap: Record<string, React.ReactNode> = Object.fromEntries(
  ROOM_SORT_OPTIONS.map((o) => [o.value, o.label]),
);

/**
 * 建物スペック 1 行(ラベル / 値)。§5.2 の項目立てを Item で組む。
 * 値は ItemDescription(text-text)側で、プレースホルダの「—」は呼び出し側が渡す。
 */
const SpecRow: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <Item size="xs">
    <ItemContent className="flex-row items-baseline gap-3">
      <ItemTitle className="w-20 shrink-0 text-xs font-normal text-text-muted">
        {label}
      </ItemTitle>
      <ItemDescription className="min-w-0 flex-1 text-xs text-text">
        {children}
      </ItemDescription>
    </ItemContent>
  </Item>
);

interface BuildingPanelProps {
  building: BuildingFeature | null;
  /** フィルタ条件を通過した部屋 id(部屋行の一致強調) */
  matchedRoomIds: Set<number>;
  onClose: () => void;
  /** 部屋行クリック → 部屋パネル(DetailPanel) */
  onUnitClick: (unit: BuildingUnit) => void;
  /** まとめて非表示(確認後に呼ぶ。App が postShortlist を束ねる) */
  onBulkHide: (units: BuildingUnit[]) => void;
  /** 比較へ追加(δ統合時に ?bcompare= へ接続) */
  onAddToCompare?: (buildingId: number) => void;
  onImageClick: (images: string[], index: number) => void;
  /** stay モード時は部屋行の価格を期間総額で表示 */
  isStayMode: boolean;
  /** 建物ショートリスト(ブックマーク)更新。App が postBuildingShortlist を束ねる */
  onBuildingShortlistUpdate?: (
    buildingId: number,
    status: 'saved' | 'none',
    comment?: string | null,
  ) => void;
}

export const BuildingPanel: React.FC<BuildingPanelProps> = ({
  building,
  matchedRoomIds,
  onClose,
  onUnitClick,
  onBulkHide,
  onAddToCompare,
  onImageClick,
  isStayMode,
  onBuildingShortlistUpdate,
}) => {
  const isMobile = useIsMobile();
  const scrollBodyRef = useRef<HTMLDivElement | null>(null);
  /** 退場を始めた建物id。退場中に別建物へ差し替わったら閉じないためのガード */
  const dismissingIdRef = useRef<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  /** 部屋一覧の並び順(§6.3)。建物を跨いで保持する */
  const [sortMode, setSortMode] = useState<RoomSortMode>(ROOM_SORT_DEFAULT);
  /** 建物メモ下書き(建物ショートリストの comment・debounce 保存は部屋パネルと同型) */
  const buildingId = building?.properties.id ?? null;
  const [commentDraft, setCommentDraft] = useState('');
  const [commentDirty, setCommentDirty] = useState(false);
  const commentTimerRef = useRef<number | null>(null);
  const buildingSaved = building?.properties.shortlist_status === 'saved';

  // 建物差し替え時にメモ下書きを最新へ(未保存の下書きは破棄)
  React.useEffect(() => {
    if (commentTimerRef.current) window.clearTimeout(commentTimerRef.current);
    setCommentDraft(building?.properties.shortlist_comment ?? '');
    setCommentDirty(false);
  }, [buildingId]); // eslint-disable-line react-hooks/exhaustive-deps

  const scheduleCommentSave = React.useCallback(
    (id: number, comment: string) => {
      if (commentTimerRef.current) window.clearTimeout(commentTimerRef.current);
      commentTimerRef.current = window.setTimeout(() => {
        // メモのみの保存は saved へ昇格(部屋の saveComment と同様)
        onBuildingShortlistUpdate?.(id, 'saved', comment);
        setCommentDirty(false);
      }, 600);
    },
    [onBuildingShortlistUpdate],
  );

  const swipe = useSwipeDismiss({
    enabled: isMobile,
    direction: 'down',
    scrollContainerRef: scrollBodyRef,
    distanceThresholdPx: 120,
    velocityThresholdPxMs: 0.55,
    onDismiss: onClose,
    onDismissStart: () => {
      dismissingIdRef.current = building?.properties.id ?? null;
    },
    isDismissValid: () => building?.properties.id === dismissingIdRef.current,
  });

  const gallery = useMemo(
    () => (building ? composeBuildingGallery(building.properties) : []),
    [building],
  );
  const galleryUrls = useMemo(() => gallery.map((s) => s.url), [gallery]);
  /** ライトボックス用オリジナル(media 未保存の行は url と同一の外部 URL) */
  const galleryFullUrls = useMemo(
    () => gallery.map((s) => s.fullUrl ?? s.url),
    [gallery],
  );

  /**
   * 部屋行順: フィルタ一致部屋を先頭へ(両モード共通)。内部は active 優先 →
   * 価格順(既定)/ 階順(不明は末尾)を sortRooms の正本に委ねる(§4.2・§6.3)
   */
  const orderedUnits = useMemo(() => {
    if (!building) return [];
    return sortRooms(building.properties.units, matchedRoomIds, sortMode);
  }, [building, matchedRoomIds, sortMode]);

  const hideTargets = useMemo(
    () => (building ? bulkHideTargetUnits(building.properties) : null),
    [building],
  );

  if (!building) return null;
  const p = building.properties;
  const altNames = p.building_names.filter((n) => n.name && n.name !== p.name);
  /** 建物階数(確定値 or 下限)と掲載部屋レンジ・件数(要件2・§5) */
  const floorInfo = buildingFloorInfo(p);
  const floorsLabel = buildingFloorsLabel(floorInfo);
  /** 確定値が無く掲載部屋からの下限のみ = 「N階建」と断定しない(§5.1 D5) */
  const floorsIsLowerBound = floorInfo.known == null && floorInfo.lowerBound != null;
  const counts = roomCounts(p);
  const unitFloorRangeText = formatFloorRange(floorInfo.unitFloorRange);
  /** 築年 / 構造(階数を伴わない単独行の正本) */
  const structureParts = buildingAgeStructureParts(p);

  return (
    <div
      ref={swipe.targetRef}
      {...swipe.bind}
      className={`
        detail-panel
        ${swipe.isDragging ? 'select-none' : ''}
        absolute z-[1000] bg-panel backdrop-blur-glass border border-border
        flex flex-col overflow-hidden shadow-[0_10px_40px_rgba(0,0,0,0.6)]
        transition-all duration-400 ease-[cubic-bezier(0.16,1,0.3,1)]
        top-3 right-3 bottom-3 w-[min(420px,calc(100%-1.5rem))] rounded-2xl
        max-md:top-auto max-md:right-0 max-md:left-0 max-md:bottom-0 max-md:w-full
        max-md:max-h-[72dvh] max-md:rounded-t-[20px] max-md:rounded-b-none max-md:z-[2100]
        max-md:shadow-[0_-10px_30px_rgba(0,0,0,0.6)]
        opacity-100 translate-x-0 scale-100 pointer-events-auto max-md:translate-y-0
      `}
    >
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-3 right-3 max-md:hidden bg-black/50 border border-white/20 text-white hover:bg-black/80 hover:scale-110 z-[11]"
        onClick={onClose}
      >
        <FaXmark />
      </Button>

      <div ref={scrollBodyRef} className="overflow-y-auto grow min-h-0 overscroll-contain app-scrollbar">
        <div className="flex flex-col gap-4">
          <ImageCarousel
            images={galleryUrls}
            fullImages={galleryFullUrls}
            propertyId={p.id}
            onImageClick={onImageClick}
          />

          <div className="px-4 flex flex-col gap-2">
            <div className="flex items-start gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-text leading-snug">
                {buildingDisplayName(p)}
              </h2>
              {buildingSaved && (
                <FaBookmark className="shrink-0 text-primary" aria-label="保存済み建物" />
              )}
              {p.is_active ? (
                <Badge variant="outline" className="shrink-0">
                  {counts.active}部屋掲載
                </Badge>
              ) : (
                <Badge variant="outline" className="shrink-0 opacity-60">
                  掲載終了
                </Badge>
              )}
            </div>

            <p className="text-sm text-text">
              {formatRentBand(p.min_daily_rent, p.max_daily_rent)}
              {p.min_plan_total != null && (
                <span className="text-text-muted"> (最安30日 {formatYen(p.min_plan_total)})</span>
              )}
              {p.min_walk_minutes != null && (
                <span className="text-text-muted"> · 徒歩{p.min_walk_minutes}分</span>
              )}
              {p.has_campaign && <span className="text-accent"> · キャンペーン実施中</span>}
            </p>

            {/* 建物スペックの項目立て(§5.2)。階数を先頭に置く(要件2) */}
            <ItemGroup variant="grouped" className="mt-1">
              <SpecRow label="階数">
                {floorsLabel ?? '—'}
                {floorsIsLowerBound && (
                  <span
                    className="ml-1.5 text-[10px] text-text-muted"
                    title="建物階数は取得元で非公開のため掲載部屋からの下限"
                  >
                    掲載部屋の最高階
                  </span>
                )}
              </SpecRow>
              <SpecRow label="築年 / 構造">
                {structureParts.length > 0 ? structureParts.join(' · ') : '—'}
              </SpecRow>
              <SpecRow label="掲載部屋">
                {unitFloorRangeText
                  ? `${unitFloorRangeText} / ${counts.active}室`
                  : `${counts.active}室`}
              </SpecRow>
              <SpecRow label="住所">{p.address ?? '—'}</SpecRow>
              <SpecRow label="最寄駅">{p.station_summary || '—'}</SpecRow>
              <SpecRow label="ソース">{p.source_sites.join(', ') || '—'}</SpecRow>
            </ItemGroup>

            {p.access_summary.length > 0 && (
              <div className="text-xs text-text-muted flex flex-col gap-0.5">
                {p.access_summary.slice(0, 6).map((a) => (
                  <span key={a} className="flex items-center gap-1.5">
                    <FaTrain className="shrink-0 text-text-muted/70" />
                    {a}
                  </span>
                ))}
              </div>
            )}

            {p.feature_categories.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {p.feature_categories.map((code) => (
                  <Badge key={code} variant="secondary" className="text-[10px]">
                    {featureCategoryLabel(code)}
                  </Badge>
                ))}
              </div>
            )}

            {/* クロスソース名寄せ時の併記(設計 §4.8・監査用に建物パネル限定) */}
            {altNames.length > 0 && (
              <p className="text-xs text-text-muted">
                別名:{' '}
                {altNames.map((n) => `${n.source_site}「${n.name}」`).join(' / ')}
              </p>
            )}
          </div>

          <div className="px-4 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-text">
                部屋一覧({counts.total})
              </h3>
              {/* 並び順(§6.3)。価格/階 × 低い順/高い順の 4 択。
                  matched 優先は sortRooms 側で全モード共通 */}
              <Select
                items={roomSortItemMap}
                value={sortMode}
                onValueChange={(value) => {
                  if (typeof value === 'string') setSortMode(value as RoomSortMode);
                }}
              >
                <SelectTrigger
                  size="sm"
                  aria-label="部屋の並び順"
                  className="shrink-0 text-xs font-semibold"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  {ROOM_SORT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value} className="text-xs">
                      {roomSortLabel(opt)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              {orderedUnits.map((u) => (
                <RoomRow
                  key={u.id}
                  unit={u}
                  matched={matchedRoomIds.has(u.id)}
                  priceMode={isStayMode ? 'stay' : 'catalog'}
                  onClick={onUnitClick}
                  density="normal"
                />
              ))}
            </div>
          </div>

          {onBuildingShortlistUpdate && (
            <div className="px-4 flex flex-col gap-2">
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className={
                    buildingSaved
                      ? 'flex-1 text-xs font-medium bg-success/[0.15] text-success border-success hover:bg-success/20 hover:text-success'
                      : 'flex-1 text-xs font-medium text-text-muted hover:text-text hover:bg-white/[0.06]'
                  }
                  onClick={() =>
                    onBuildingShortlistUpdate(
                      p.id,
                      buildingSaved ? 'none' : 'saved',
                      commentDirty ? commentDraft : undefined,
                    )
                  }
                >
                  <FaBookmark className="mr-1.5" />
                  {buildingSaved ? '保存済み(建物)' : '建物を保存'}
                </Button>
              </div>
              {(buildingSaved || commentDraft !== '') && (
                <textarea
                  value={commentDraft}
                  onChange={(e) => {
                    setCommentDraft(e.target.value);
                    setCommentDirty(true);
                    scheduleCommentSave(p.id, e.target.value);
                  }}
                  placeholder="建物メモ(自動保存)"
                  rows={2}
                  className="w-full rounded-lg border border-border bg-white/[0.03] px-3 py-2 text-xs text-text placeholder:text-text-muted/60 focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              )}
            </div>
          )}

          <div className="px-4 pb-4 flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1 min-w-[140px]"
              disabled={!hideTargets}
              onClick={() => setConfirmOpen(true)}
            >
              <FaEyeSlash className="mr-1.5" />
              この建物をまとめて非表示
            </Button>
            {onAddToCompare && (
              <Button
                variant="outline"
                size="sm"
                className="flex-1 min-w-[120px]"
                onClick={() => onAddToCompare(p.id)}
              >
                <FaScaleBalanced className="mr-1.5" />
                比較に追加
              </Button>
            )}
          </div>
        </div>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>この建物をまとめて非表示</DialogTitle>
            <DialogDescription>
              この建物の掲載中 {hideTargets?.length ?? 0} 部屋をすべて「非表示」にします。
              保存済み部屋は除外されます。({buildingDisplayName(p)})
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              キャンセル
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirmOpen(false);
                if (hideTargets) onBulkHide(hideTargets);
              }}
            >
              非表示にする
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
