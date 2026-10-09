import React from 'react';
import { FaBookmark, FaChevronDown } from 'react-icons/fa6';
import type { BuildingFeature, BuildingUnit, PriceMode } from '../../types.ts';
import { Card, CardContent } from '@/components/ui/card.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { RoomRow } from '../shared/RoomRow.tsx';
import {
  buildingDisplayName,
  buildingSpecParts,
  roomCounts,
  savedCountOf,
  sortRooms,
  stayBandOfUnits,
} from '../../lib/building.ts';
import { formatRentBandText } from '../../lib/format.ts';

interface BuildingCardProps {
  building: BuildingFeature;
  isActive: boolean;
  /** フィルタ条件通過部屋(部屋行の上位ソート+一致マーク・§4.2) */
  matchedRoomIds: Set<number>;
  priceMode: PriceMode;
  /** 部屋一覧アコーディオンの展開状態(親 Sidebar が建物 id で保持・A13) */
  expanded: boolean;
  /** 展開状態のトグル(建物 id 単位・フィルタ/ソートの並び替えでも維持する) */
  onToggleExpanded: (buildingId: number) => void;
  /** カード本体クリック(建物選択導線) */
  onClick: () => void;
  /** 部屋行クリック(部屋パネル直開のショートカット・§4.2) */
  onUnitClick: (unit: BuildingUnit) => void;
  /** ホバー状態の変化(サイドバー→マップのピンハイライト連動。null=離れた) */
  onHoverChange?: (id: number | null) => void;
}

/**
 * サイドバーの建物カード(B2-β・docs/building-aggregation-b2-fe-plan.md §4.2)。
 * カード 1 枚 = 1 建物。部屋行はアコーディオン展開(既定折りたたみ・
 * 展開状態は親 Sidebar が建物 id の集合で保持し、並び替えで畳まれないようにする
 * (docs/fe-floor-orientation-redesign-plan.md §2.4 A13)。
 * スタイル資産は PropertyCard(PropertyCard 削除済み)から流用。
 */
export const BuildingCard: React.FC<BuildingCardProps> = ({
  building,
  isActive,
  matchedRoomIds,
  priceMode,
  expanded,
  onToggleExpanded,
  onClick,
  onUnitClick,
  onHoverChange,
}) => {
  const p = building.properties;
  const savedCount = savedCountOf(p);
  const counts = roomCounts(p);
  const allInactive = p.is_active === false;
  const stayMode = priceMode === 'stay';

  // カード価格帯: catalog=建物代表値のカタログ帯 / stay=マッチ部屋の期間総額帯
  // (マッチ部屋が 0 の防御フォールバックとして全 units を使う)
  const matchedUnits = React.useMemo(
    () => p.units.filter((u) => matchedRoomIds.has(u.id)),
    [p.units, matchedRoomIds],
  );
  const stayBand = stayMode
    ? stayBandOfUnits(matchedUnits.length > 0 ? matchedUnits : p.units)
    : null;
  const bandText = formatRentBandText(p.min_daily_rent, p.max_daily_rent, stayBand);

  // 部屋行: matched 上位ソート(sortRooms)。設計 §4.2 の「全部屋載せる」契約
  const unitRows = React.useMemo(
    () => sortRooms(p.units, matchedRoomIds),
    [p.units, matchedRoomIds],
  );

  const specParts = buildingSpecParts(p);

  return (
    <Card
      onClick={onClick}
      onMouseEnter={() => onHoverChange?.(p.id)}
      onMouseLeave={() => onHoverChange?.(null)}
      size="sm"
      className={`
        cursor-pointer transition-all duration-300
        hover:border-primary hover:bg-primary/[0.04] hover:-translate-y-0.5
        ${isActive ? '!border-primary !bg-primary/[0.04] -translate-y-0.5' : ''}
        ${allInactive ? 'opacity-60 saturate-50' : ''}
      `}
    >
      <CardContent className="flex flex-col gap-0 p-3">
        <div className="flex gap-3">
          {/* 代表写真 */}
          <div
            className="w-20 h-20 rounded-lg bg-cover bg-center shrink-0 bg-white/[0.05]"
            style={{ backgroundImage: `url('${p.thumbnail_url ?? ''}')` }}
          />

          <div className="flex flex-col justify-between min-w-0 grow">
            <div>
              <div className="flex items-start justify-between gap-1.5">
                <div
                  className="text-sm font-semibold whitespace-nowrap overflow-hidden text-ellipsis"
                  title={buildingDisplayName(p)}
                >
                  {buildingDisplayName(p)}
                </div>
                <span className="text-xs text-text-muted shrink-0 whitespace-nowrap">
                  {/* 掲載中/全部屋。一致時は単一表記(比較ボードの active/全 表記と同型) */}
                  {counts.active === counts.total
                    ? `${counts.total}部屋`
                    : `${counts.active}/${counts.total}部屋`}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1 mt-0.5">
                {p.source_sites.map((site) => (
                  <Badge
                    key={site}
                    variant="secondary"
                    className="text-[10px] py-0 px-1.5 font-normal"
                  >
                    {site}
                  </Badge>
                ))}
                {p.shortlist_status === 'saved' && (
                  <FaBookmark
                    className="text-primary shrink-0"
                    title="保存済み建物(建物ブックマーク)"
                  />
                )}
                {savedCount > 0 && (
                  <Badge
                    variant="outline"
                    className="text-[10px] font-semibold py-0.5 px-1.5 bg-success/[0.15] text-success border-success/30"
                  >
                    <FaBookmark className="mr-0.5" />
                    {savedCount}
                  </Badge>
                )}
                {allInactive && (
                  <Badge
                    variant="outline"
                    className="text-[10px] font-semibold py-0.5 px-1.5 bg-warning/[0.15] text-warning border-warning/30"
                  >
                    掲載終了
                  </Badge>
                )}
              </div>
              <div className="text-sm font-bold text-accent whitespace-nowrap overflow-hidden text-ellipsis mt-0.5">
                {bandText}
                {p.min_walk_minutes != null && (
                  <span className="text-xs font-normal text-text-muted"> · 徒歩{p.min_walk_minutes}分</span>
                )}
              </div>
              {(specParts.length > 0 || p.has_campaign) && (
                <div className="flex flex-wrap items-center gap-1 text-xs text-text-muted whitespace-nowrap overflow-hidden text-ellipsis">
                  {specParts.join(' · ')}
                  {p.has_campaign && (
                    <Badge
                      variant="outline"
                      className="text-[10px] font-semibold py-0 px-1.5 bg-success/[0.15] text-success border-success/30"
                    >
                      キャンペーン
                    </Badge>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* アコーディオン部屋一覧(既定折りたたみ・展開状態は親 Sidebar が保持) */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpanded(p.id);
          }}
          aria-expanded={expanded}
          className="mt-2 flex items-center gap-1 text-xs text-text-muted hover:text-text transition-colors"
        >
          <FaChevronDown
            className={`transition-transform duration-200 ${expanded ? '' : '-rotate-90'}`}
          />
          部屋一覧({counts.total})
        </button>
        {expanded && (
          // 部屋行クリックでカード本体(建物選択)へ伝播させない(旧実装の stopPropagation 相当)
          <div className="mt-1.5 flex flex-col" onClick={(e) => e.stopPropagation()}>
            {unitRows.map((u) => (
              <RoomRow
                key={u.id}
                unit={u}
                matched={matchedRoomIds.has(u.id)}
                priceMode={priceMode}
                onClick={onUnitClick}
                density="dense"
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
