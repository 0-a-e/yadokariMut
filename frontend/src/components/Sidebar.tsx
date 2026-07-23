import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  CATALOG_PRICE_UNLIMITED,
  FEATURE_TOGGLE_OPTIONS,
  MapFilters,
  PropertyFeature,
  ShortlistStatusFilter,
  SortKey,
  STAY_PRICE_UNLIMITED,
} from '../types';
import { isPriceUnlimited, stayBandSummary } from '../lib/filterLogic';
import { PropertyCard } from './PropertyCard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  FaHouseChimney,
  FaMoon,
  FaMap,
  FaSatellite,
  FaGear,
  FaBookmark,
  FaExpand,
  FaEyeSlash,
  FaCircleXmark,
  FaCalendarDays,
  FaSliders,
  FaChevronDown,
  FaScaleBalanced,
} from 'react-icons/fa6';
import { cn } from '@/lib/utils';

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
  { key: 'saved', label: '保存', icon: 'saved' },
  { key: 'unsaved', label: '未分類' },
  { key: 'hide', label: '非表示', icon: 'hide' },
  { key: 'reject', label: '見送り', icon: 'reject' },
];

const FILTERS_OPEN_KEY = 'yadokari:sidebar:filters-open';

function sortOptions(priceMode: MapFilters['priceMode']): { value: SortKey; label: string }[] {
  return [
    { value: 'score', label: 'スコア' },
    {
      value: 'price_asc',
      label: priceMode === 'stay' ? '総額↑' : '安い順',
    },
    {
      value: 'price_desc',
      label: priceMode === 'stay' ? '総額↓' : '高い順',
    },
    { value: 'area_desc', label: '広い順' },
  ];
}

/** Secondary filters tucked into Collapsible (not period / price / sort / keyword). */
function countActiveDetailFilters(filters: MapFilters): number {
  let n = 0;
  if (filters.areaRange[0] !== 10 || filters.areaRange[1] !== 50) n += 1;
  if (filters.maxWalkMinutes != null) n += 1;
  if (filters.minScore != null) n += 1;
  if (filters.layout !== 'all') n += 1;
  if (filters.prefecture) n += 1;
  if (filters.sources && filters.sources.length > 0) n += 1;
  if (filters.requiredFeatures.length > 0) n += 1;
  if (filters.status !== 'all') n += 1;
  if (filters.boundsEnabled) n += 1;
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

interface SidebarProps {
  filteredFeatures: PropertyFeature[];
  selectedId: number | null;
  activeLayer: 'dark' | 'pale' | 'satellite';
  onLayerChange: (layer: 'dark' | 'pale' | 'satellite') => void;
  onAdminToggle: () => void;
  filters: MapFilters;
  onFiltersChange: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  prefectureOptions: string[];
  sourceOptions?: { id: string; label: string; count: number }[];
  onCardClick: (feature: PropertyFeature) => void;
  className?: string;
  compactHeader?: boolean;
  excludedUnestimable?: number;
  /** Total saved shortlist count (may exceed current filter) */
  savedCount?: number;
  onOpenComparison?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  filteredFeatures,
  selectedId,
  activeLayer,
  onLayerChange,
  onAdminToggle,
  filters,
  onFiltersChange,
  prefectureOptions,
  sourceOptions = [],
  onCardClick,
  className = '',
  compactHeader = false,
  excludedUnestimable = 0,
  savedCount = 0,
  onOpenComparison,
}) => {
  const [displayedLimit, setDisplayedLimit] = useState(30);
  const [filtersOpen, setFiltersOpen] = useState(() => {
    try {
      return localStorage.getItem(FILTERS_OPEN_KEY) === '1';
    } catch {
      return false;
    }
  });
  const sidebarContentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDisplayedLimit(30);
  }, [filteredFeatures]);

  useEffect(() => {
    try {
      localStorage.setItem(FILTERS_OPEN_KEY, filtersOpen ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [filtersOpen]);

  const handleScroll = () => {
    const el = sidebarContentRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 150) {
      if (displayedLimit < filteredFeatures.length) setDisplayedLimit((prev) => prev + 30);
    }
  };

  const stayMode = filters.priceMode === 'stay';
  const priceUnlimited = isPriceUnlimited(filters);
  const displayPriceText = priceUnlimited
    ? '制限なし'
    : `${(filters.maxPrice / 10000).toFixed(1)}万円以下`;
  const bandSummary = stayBandSummary(filters.checkIn, filters.checkOut);
  const walkText =
    filters.maxWalkMinutes == null ? '制限なし' : `徒歩${filters.maxWalkMinutes}分以内`;
  const scoreText = filters.minScore == null ? '制限なし' : `${filters.minScore}点以上`;
  const displayedFeatures = filteredFeatures.slice(0, displayedLimit);
  const priceSliderMax = stayMode ? STAY_PRICE_UNLIMITED : CATALOG_PRICE_UNLIMITED;
  const priceSliderMin = stayMode ? 30_000 : 50_000;
  const detailActiveCount = useMemo(() => countActiveDetailFilters(filters), [filters]);

  const layerLabels: Record<string, string> = {
    dark: 'ダークテーマ (CartoDB)',
    pale: '淡色日本語地図 (国土地理院)',
    satellite: '航空写真 (国土地理院)',
  };

  return (
    <div
      className={cn(
        'w-full h-full min-h-0 bg-panel backdrop-blur-glass border-r border-border flex flex-col',
        'shadow-[10px_0_30px_rgba(0,0,0,0.35)]',
        className,
      )}
    >
      <div className="p-4 sm:p-5 border-b border-border shrink-0">
        <div className="flex justify-between items-start gap-2">
          <div className={cn('flex items-center gap-3', compactHeader && 'hidden')}>
            <div className="bg-gradient-to-br from-primary to-accent size-9 rounded-[10px] flex items-center justify-center text-white text-lg shadow-[0_4px_15px_var(--primary-glow)]">
              <FaHouseChimney />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-[0.5px] bg-gradient-to-r from-white to-[#b9c1d6] bg-clip-text text-transparent">
                yadokariMut
              </h1>
              <p className="text-xs text-text-muted font-normal">Monthly Mansion Explorer</p>
            </div>
          </div>

          <div className="flex gap-1 bg-white/[0.04] border border-border rounded-lg p-1 ml-auto">
            {(['dark', 'pale', 'satellite'] as const).map((layer) => (
              <Tooltip key={layer}>
                <TooltipTrigger
                  onClick={() => onLayerChange(layer)}
                  render={
                    <Button
                      variant={activeLayer === layer ? 'default' : 'ghost'}
                      size="icon-sm"
                      className={
                        activeLayer === layer
                          ? 'shadow-[0_2px_8px_rgba(133,77,255,0.3)]'
                          : 'text-text-muted hover:text-text'
                      }
                    >
                      {layer === 'dark' ? <FaMoon /> : layer === 'pale' ? <FaMap /> : <FaSatellite />}
                    </Button>
                  }
                />
                <TooltipContent>{layerLabels[layer]}</TooltipContent>
              </Tooltip>
            ))}
            <Tooltip>
              <TooltipTrigger
                onClick={onAdminToggle}
                render={
                  <Button variant="ghost" size="icon-sm" className="text-text-muted hover:text-text">
                    <FaGear />
                  </Button>
                }
              />
              <TooltipContent>管理者ダッシュボード</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>

      <div
        className="p-4 sm:p-5 overflow-y-auto grow flex flex-col gap-4 min-h-0 app-scrollbar"
        ref={sidebarContentRef}
        onScroll={handleScroll}
      >
        {/* ── Primary: period + price ── */}
        <div className="rounded-xl border border-border/80 bg-white/[0.03] p-3 flex flex-col gap-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[1px] text-text-muted">
            <FaCalendarDays className="text-accent" />
            ご利用期間
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
          <ToggleGroup
            multiple={false}
            value={[filters.priceMode]}
            onValueChange={(vals) => {
              const next = vals[0] as MapFilters['priceMode'] | undefined;
              if (next === 'stay' || next === 'catalog') {
                onFiltersChange({ priceMode: next });
              }
            }}
            variant="outline"
            size="sm"
            className="flex flex-wrap w-full max-w-full"
          >
            <ToggleGroupItem value="stay" className="flex-1 text-xs">
              期間総額
            </ToggleGroupItem>
            <ToggleGroupItem value="catalog" className="flex-1 text-xs">
              カタログ
            </ToggleGroupItem>
          </ToggleGroup>
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

        <FilterSection label="並び替え">
          <ToggleGroup
            multiple={false}
            value={[filters.sortBy]}
            onValueChange={(vals) => {
              const next = vals[0] as SortKey | undefined;
              if (next) onFiltersChange({ sortBy: next });
            }}
            variant="outline"
            size="sm"
            className="flex flex-wrap w-full max-w-full"
          >
            {sortOptions(filters.priceMode).map(({ value, label }) => (
              <ToggleGroupItem key={value} value={value} className="text-xs">
                {label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
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
              <ToggleGroup
                multiple={false}
                value={[filters.layout]}
                onValueChange={(vals) => {
                  const next = vals[0];
                  if (next) onFiltersChange({ layout: next });
                }}
                variant="outline"
                size="sm"
                className="flex flex-wrap w-full max-w-full"
              >
                {LAYOUT_OPTIONS.map(({ value, label }) => (
                  <ToggleGroupItem key={value} value={value} className="text-xs">
                    {label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </FilterSection>

            <FilterSection label="都道府県">
              <select
                className="h-9 w-full rounded-lg border border-border bg-white/[0.04] px-3 text-sm text-text outline-none focus:border-primary"
                value={filters.prefecture ?? ''}
                onChange={(e) =>
                  onFiltersChange({ prefecture: e.target.value ? e.target.value : null })
                }
              >
                <option value="">すべて</option>
                {prefectureOptions.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
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
                {FEATURE_TOGGLE_OPTIONS.map((name) => (
                  <ToggleGroupItem key={name} value={name} className="text-xs">
                    {name}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </FilterSection>

            <FilterSection label="ショートリスト">
              <ToggleGroup
                multiple={false}
                value={[filters.status]}
                onValueChange={(vals) => {
                  const next = vals[0] as ShortlistStatusFilter | undefined;
                  if (next) onFiltersChange({ status: next });
                }}
                variant="outline"
                size="sm"
                className="flex flex-wrap w-full max-w-full"
              >
                {STATUS_OPTIONS.map(({ key, label, icon }) => (
                  <ToggleGroupItem key={key} value={key} className="text-xs gap-1">
                    {icon === 'saved' && (
                      <FaBookmark style={{ color: 'var(--success)' }} />
                    )}
                    {icon === 'hide' && <FaEyeSlash />}
                    {icon === 'reject' && <FaCircleXmark />}
                    {label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </FilterSection>

            <div className="flex flex-col gap-2">
              <Button
                variant={filters.boundsEnabled ? 'default' : 'outline'}
                size="sm"
                className={cn(
                  'w-full text-xs font-semibold',
                  filters.boundsEnabled
                    ? 'shadow-[0_4px_10px_rgba(133,77,255,0.3)]'
                    : 'text-text-muted',
                )}
                onClick={() => onFiltersChange({ boundsEnabled: !filters.boundsEnabled })}
              >
                <FaExpand
                  className={cn('mr-2', filters.boundsEnabled ? 'text-white' : 'text-text-muted')}
                />
                {filters.boundsEnabled ? '地図範囲で絞り込み中' : '地図範囲で絞り込む'}
              </Button>
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

        <Separator />

        <div>
          <div className="flex items-center justify-between gap-2 mb-1">
            <p className="text-sm text-text-muted m-0">物件数: {filteredFeatures.length}件</p>
            {onOpenComparison && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs font-semibold shrink-0"
                disabled={savedCount < 1}
                onClick={onOpenComparison}
              >
                <FaScaleBalanced data-icon="inline-start" />
                比較
                {savedCount > 0 && (
                  <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">
                    {savedCount}
                  </Badge>
                )}
              </Button>
            )}
          </div>
          {stayMode && excludedUnestimable > 0 && (
            <p className="text-[11px] text-text-muted/80 mb-3 m-0">
              期間総額を計算できない物件を {excludedUnestimable} 件除外
            </p>
          )}
          {!(stayMode && excludedUnestimable > 0) && <div className="mb-3" />}
          <ScrollArea className="h-auto max-h-none">
            <div className="flex flex-col gap-3">
              {displayedFeatures.map((feat) => (
                <PropertyCard
                  key={feat.properties.id}
                  feature={feat}
                  isActive={selectedId === feat.properties.id}
                  onClick={() => onCardClick(feat)}
                  priceMode={filters.priceMode}
                />
              ))}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  );
};
