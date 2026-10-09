/**
 * サイドバーのフィルタ操作系UI(利用期間〜詳細フィルタ/リセット)。
 * 開閉の有無(セクション全体の折りたたみ)は Sidebar 側が管理し、
 * 詳細フィルタの開閉状態のみここで localStorage に永続化する。
 * 並び替えは建物数行の Select へ移設(Sidebar 側)。
 */
import React, { useMemo, useState, useEffect } from 'react';
import type {
  AreaMode,
  ListingVisibilityFilter,
  MapFilters,
  ShortlistStatusFilter,
} from '../../types.ts';
import {
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_AREA_RANGE,
  FEATURE_TOGGLE_OPTIONS,
  STAY_PRICE_UNLIMITED,
} from '../../types.ts';
import { isPriceUnlimited, stayBandSummary } from '../../lib/filterLogic.ts';
// 状態ラベルはショートリスト語彙の正本(lib/shortlist.ts)から参照する。
// unsaved(未分類フィルタ)は none と同義のため none のラベルを共有する。
import { SHORTLIST_STATUS_LABELS } from '../../lib/shortlist.ts';
import { Button } from '@/components/ui/button.tsx';
import { Input } from '@/components/ui/input.tsx';
import { Slider } from '@/components/ui/slider.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible.tsx';
import {
  SingleToggleGroup,
  ToggleGroup,
  ToggleGroupItem,
} from '@/components/ui/toggle-group.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select.tsx';
import {
  FaBookmark,
  FaExpand,
  FaEyeSlash,
  FaCircleXmark,
  FaCalendarDays,
  FaSliders,
  FaChevronDown,
  FaVectorSquare,
} from 'react-icons/fa6';
import { cn } from '@/lib/utils.ts';

const FILTERS_OPEN_KEY = 'yadokari:sidebar:filters-open';

const PRICE_MODE_OPTIONS: { value: MapFilters['priceMode']; label: string }[] = [
  { value: 'stay', label: '期間総額' },
  { value: 'catalog', label: 'カタログ' },
];

const LAYOUT_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'すべて' },
  { value: '1R', label: '1R' },
  { value: '1K', label: '1K' },
  { value: '1DK', label: '1DK' },
  { value: '1LDK', label: '1LDK' },
];

const STATUS_OPTIONS: {
  key: ShortlistStatusFilter;
  label: string;
  icon?: 'saved' | 'hide' | 'reject';
}[] = [
  { key: 'all', label: 'すべて' },
  { key: 'saved', label: SHORTLIST_STATUS_LABELS.saved, icon: 'saved' },
  { key: 'unsaved', label: SHORTLIST_STATUS_LABELS.none },
  { key: 'hide', label: SHORTLIST_STATUS_LABELS.hide, icon: 'hide' },
  { key: 'reject', label: SHORTLIST_STATUS_LABELS.reject, icon: 'reject' },
];

const LISTING_VISIBILITY_OPTIONS: {
  value: ListingVisibilityFilter;
  label: string;
}[] = [
  { value: 'all', label: '全て' },
  { value: 'active', label: '掲載中' },
  { value: 'inactive', label: '非掲載' },
];

/**
 * 都道府県セレクトの「すべて」を表す値。
 * 空文字は base-ui Select の未選択表現と衝突し得るため sentinel を使い、
 * フィルタ値へは null を渡す(ネイティブ select 時代の value="" 相当)。
 */
const PREFECTURE_ALL = '__all__';

/** ショートリスト切替用(icon を label に埋め込んだ SingleToggleGroup 用オプション) */
const STATUS_TOGGLE_OPTIONS: {
  value: ShortlistStatusFilter;
  label: React.ReactNode;
}[] = STATUS_OPTIONS.map(({ key, label, icon }) => ({
  value: key,
  label: (
    <>
      {icon === 'saved' && <FaBookmark style={{ color: 'var(--success)' }} />}
      {icon === 'hide' && <FaEyeSlash />}
      {icon === 'reject' && <FaCircleXmark />}
      {label}
    </>
  ),
}));

/** 絞り込み範囲切替用(icon を label に埋め込んだ SingleToggleGroup 用オプション) */
const AREA_MODE_OPTIONS: { value: AreaMode; label: React.ReactNode }[] = [
  { value: 'all', label: '全体' },
  {
    value: 'viewport',
    label: (
      <>
        <FaExpand />
        表示範囲
      </>
    ),
  },
  {
    value: 'drawn',
    label: (
      <>
        <FaVectorSquare />
        囲む
      </>
    ),
  },
];

/** Secondary filters tucked into Collapsible (not period / price / keyword). */
function countActiveDetailFilters(filters: MapFilters): number {
  let n = 0;
  if (
    filters.areaRange[0] !== DEFAULT_AREA_RANGE[0] ||
    filters.areaRange[1] !== DEFAULT_AREA_RANGE[1]
  ) {
    n += 1;
  }
  if (filters.maxWalkMinutes != null) n += 1;
  if (filters.minScore != null) n += 1;
  if (filters.layout !== 'all') n += 1;
  if (filters.prefecture) n += 1;
  if (filters.sources && filters.sources.length > 0) n += 1;
  if (filters.requiredFeatures.length > 0) n += 1;
  if (filters.status !== 'all') n += 1;
  if (filters.areaMode !== 'all') n += 1;
  return n;
}

function FilterSection({
  label,
  valueText,
  children,
}: {
  label: string;
  valueText?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-between text-xs font-semibold uppercase tracking-[1px] text-text-muted">
        <span>{label}</span>
        {valueText != null && (
          <span className="text-accent font-semibold normal-case tracking-normal">{valueText}</span>
        )}
      </div>
      {children}
    </div>
  );
}

interface FilterPanelProps {
  filters: MapFilters;
  onFiltersChange: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  prefectureOptions: string[];
  sourceOptions?: { id: string; label: string; count: number }[];
}

export const FilterPanel: React.FC<FilterPanelProps> = ({
  filters,
  onFiltersChange,
  prefectureOptions,
  sourceOptions = [],
}) => {
  /** セレクトの値→ラベル対応(base-ui の items。選択中ラベルの表示に使う) */
  const prefectureItemMap: Record<string, string> = {
    [PREFECTURE_ALL]: 'すべて',
    ...Object.fromEntries(prefectureOptions.map((p) => [p, p])),
  };
  const [filtersOpen, setFiltersOpen] = useState(() => {
    try {
      return localStorage.getItem(FILTERS_OPEN_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(FILTERS_OPEN_KEY, filtersOpen ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [filtersOpen]);

  const stayMode = filters.priceMode === 'stay';
  const priceUnlimited = isPriceUnlimited(filters);
  const displayPriceText = priceUnlimited
    ? '制限なし'
    : `${(filters.maxPrice / 10000).toFixed(1)}万円以下`;
  const bandSummary = stayBandSummary(filters.checkIn, filters.checkOut);
  const walkText =
    filters.maxWalkMinutes == null ? '制限なし' : `徒歩${filters.maxWalkMinutes}分以内`;
  const scoreText = filters.minScore == null ? '制限なし' : `${filters.minScore}点以上`;
  const priceSliderMax = stayMode ? STAY_PRICE_UNLIMITED : CATALOG_PRICE_UNLIMITED;
  const priceSliderMin = stayMode ? 30_000 : 50_000;
  const detailActiveCount = useMemo(() => countActiveDetailFilters(filters), [filters]);

  return (
    <>
      {/* ── Primary: period + price ── */}
      <div className="rounded-xl border border-border/80 bg-white/[0.03] p-3 flex flex-col gap-2.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[1px] text-text-muted">
          <FaCalendarDays className="text-accent" />
          利用期間
        </div>
        <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-end max-[380px]:grid-cols-1">
          <label className="flex flex-col gap-1 min-w-0">
            <span className="text-[11px] text-text-muted">入居日</span>
            <Input
              type="date"
              value={filters.checkIn}
              onChange={(e) => {
                const checkIn = e.target.value;
                const checkOut =
                  filters.checkOut && checkIn && filters.checkOut < checkIn
                    ? checkIn
                    : filters.checkOut;
                onFiltersChange({ checkIn, checkOut });
              }}
              className="bg-white/[0.04] text-sm h-9"
            />
          </label>
          <span className="text-text-muted text-sm pb-2 text-center max-[380px]:hidden">〜</span>
          <label className="flex flex-col gap-1 min-w-0">
            <span className="text-[11px] text-text-muted">退去日</span>
            <Input
              type="date"
              value={filters.checkOut}
              min={filters.checkIn || undefined}
              onChange={(e) => onFiltersChange({ checkOut: e.target.value })}
              className="bg-white/[0.04] text-sm h-9"
            />
          </label>
        </div>
        {bandSummary && (
          <p className="text-[11px] text-text-muted m-0">
            {bandSummary}
            {stayMode ? ' · 期間総額で比較中' : ' · カタログ価格で表示中'}
          </p>
        )}
        <SingleToggleGroup
          options={PRICE_MODE_OPTIONS}
          value={filters.priceMode}
          onChange={(priceMode) => onFiltersChange({ priceMode })}
          variant="outline"
          size="sm"
          className="flex flex-wrap w-full max-w-full"
          itemClassName="flex-1 text-xs"
        />
      </div>

      <FilterSection
        label={stayMode ? '期間総額の上限' : '月額家賃の上限'}
        valueText={displayPriceText}
      >
        <Slider
          value={[Math.min(filters.maxPrice, priceSliderMax)]}
          onValueChange={(vals) => {
            const v = Array.isArray(vals) ? vals[0] : vals;
            onFiltersChange({ maxPrice: v });
          }}
          min={priceSliderMin}
          max={priceSliderMax}
          step={5000}
        />
      </FilterSection>

      <FilterSection label="フリーワード">
        <Input
          type="text"
          placeholder="駅名・物件名・設備…"
          value={filters.searchQuery}
          onChange={(e) => onFiltersChange({ searchQuery: e.target.value })}
          className="h-9"
        />
      </FilterSection>

      <FilterSection label="掲載状態">
        <SingleToggleGroup
          options={LISTING_VISIBILITY_OPTIONS}
          value={filters.listingVisibility}
          onChange={(listingVisibility) => onFiltersChange({ listingVisibility })}
          variant="outline"
          size="sm"
          className="flex flex-wrap w-full max-w-full"
          itemClassName="text-xs"
        />
      </FilterSection>

      {/* ── Secondary: Collapsible (not Accordion — single expand block) ── */}
      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen}>
        <CollapsibleTrigger
          className={cn(
            'flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-border',
            'bg-transparent px-3 text-xs font-semibold text-text-muted outline-none',
            'hover:bg-white/[0.04] hover:text-text focus-visible:border-primary',
          )}
        >
          <span className="flex items-center gap-2">
            <FaSliders className="text-accent" />
            詳細フィルタ
            {detailActiveCount > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-5 font-semibold">
                {detailActiveCount}
              </Badge>
            )}
          </span>
          <FaChevronDown
            className={cn(
              'text-text-muted transition-transform duration-200',
              filtersOpen && 'rotate-180',
            )}
          />
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-4 pt-3">
          <FilterSection
            label="面積範囲 (㎡)"
            valueText={`${filters.areaRange[0]}〜${filters.areaRange[1]}㎡`}
          >
            <Slider
              value={filters.areaRange}
              onValueChange={(vals) => {
                if (Array.isArray(vals) && vals.length === 2) {
                  onFiltersChange({ areaRange: vals as [number, number] });
                }
              }}
              min={10}
              max={50}
              step={1}
            />
          </FilterSection>

          <FilterSection label="駅徒歩" valueText={walkText}>
            <Slider
              value={[filters.maxWalkMinutes ?? 25]}
              onValueChange={(vals) => {
                const v = Array.isArray(vals) ? vals[0] : vals;
                onFiltersChange({ maxWalkMinutes: v >= 25 ? null : v });
              }}
              min={1}
              max={25}
              step={1}
            />
            <p className="text-[10px] text-text-muted m-0">25 = 制限なし</p>
          </FilterSection>

          <FilterSection label="スコア下限" valueText={scoreText}>
            <Slider
              value={[filters.minScore ?? 0]}
              onValueChange={(vals) => {
                const v = Array.isArray(vals) ? vals[0] : vals;
                onFiltersChange({ minScore: v <= 0 ? null : v });
              }}
              min={0}
              max={100}
              step={5}
            />
          </FilterSection>

          <FilterSection label="間取り">
            <SingleToggleGroup
              options={LAYOUT_OPTIONS}
              value={filters.layout}
              onChange={(layout) => onFiltersChange({ layout })}
              variant="outline"
              size="sm"
              className="flex flex-wrap w-full max-w-full"
              itemClassName="text-xs"
            />
          </FilterSection>

          <FilterSection label="都道府県">
            <Select
              items={prefectureItemMap}
              value={filters.prefecture ?? PREFECTURE_ALL}
              onValueChange={(value) => {
                if (typeof value !== 'string') return;
                onFiltersChange({ prefecture: value === PREFECTURE_ALL ? null : value });
              }}
            >
              <SelectTrigger size="default" aria-label="都道府県" className="w-full text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={PREFECTURE_ALL}>すべて</SelectItem>
                {prefectureOptions.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterSection>

          {sourceOptions.length > 0 && (
            <FilterSection label="データ源">
              <ToggleGroup
                multiple
                value={filters.sources || []}
                onValueChange={(vals) => {
                  onFiltersChange({ sources: vals as string[] });
                }}
                variant="outline"
                size="sm"
                className="flex flex-wrap w-full max-w-full"
              >
                {sourceOptions.map(({ id, label, count }) => (
                  <ToggleGroupItem key={id} value={id} className="text-xs">
                    {label}
                    <span className="ml-1 opacity-60">{count}</span>
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </FilterSection>
          )}

          <FilterSection label="設備">
            <ToggleGroup
              multiple
              value={filters.requiredFeatures}
              onValueChange={(vals) => {
                onFiltersChange({ requiredFeatures: vals as string[] });
              }}
              variant="outline"
              size="sm"
              className="flex flex-wrap w-full max-w-full"
            >
              {FEATURE_TOGGLE_OPTIONS.map((opt) => (
                <ToggleGroupItem key={opt.value} value={opt.value} className="text-xs">
                  {opt.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </FilterSection>

          <FilterSection label="ショートリスト">
            <SingleToggleGroup
              options={STATUS_TOGGLE_OPTIONS}
              value={filters.status}
              onChange={(status) => onFiltersChange({ status })}
              variant="outline"
              size="sm"
              className="flex flex-wrap w-full max-w-full"
              itemClassName="text-xs gap-1"
            />
          </FilterSection>

          <FilterSection label="絞り込み範囲">
            <SingleToggleGroup
              options={AREA_MODE_OPTIONS}
              value={filters.areaMode}
              onChange={(areaMode) => onFiltersChange({ areaMode })}
              variant="outline"
              size="sm"
              className="flex w-full"
              itemClassName="flex-1 text-xs gap-1"
            />
            {filters.areaMode === 'drawn' && (
              <p className="text-xs text-text-muted m-0">
                {filters.drawnPolygon
                  ? '囲んだ範囲で絞り込み中(地図の「範囲を解除」で解除)'
                  : '地図上で範囲を囲んでください'}
              </p>
            )}
          </FilterSection>

          <div className="flex flex-col gap-2">
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs font-semibold text-text-muted hover:text-text"
              onClick={() => onFiltersChange({ reset: true })}
            >
              フィルターをリセット
            </Button>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </>
  );
};
