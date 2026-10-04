import React, { useState, useEffect, useRef } from 'react';
import { MapFilters, PropertyFeature } from '../../types.ts';
import { PropertyCard } from './PropertyCard.tsx';
import { Button } from '@/components/ui/button.tsx';
import { ScrollArea } from '@/components/ui/scroll-area.tsx';
import { Separator } from '@/components/ui/separator.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip.tsx';
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible.tsx';
import {
  FaHouseChimney,
  FaMoon,
  FaMap,
  FaSatellite,
  FaBars,
  FaGear,
  FaChartLine,
  FaLayerGroup,
  FaScaleBalanced,
  FaMapLocationDot,
  FaListUl,
  FaFilter,
  FaVectorSquare,
} from 'react-icons/fa6';
import { Menu, MenuTrigger, MenuContent, MenuItem } from '@/components/ui/menu.tsx';
import { cn } from '@/lib/utils.ts';
import {
  type BaseLayerId,
  type LayerConfigState,
} from '../../lib/layers/types.ts';
import type { LayerActions } from '../../lib/layers/state.ts';
import { flattenStack } from '../../lib/layers/state.ts';
import { catalogById } from '../../lib/layers/catalog.ts';
import type { FeSettings } from '../../lib/feSettings.ts';
import { LayerPanel } from '../layers/LayerPanel.tsx';
import { FilterPanel } from './FilterPanel.tsx';

/** ベースマップ切替タブ(左)。labelはaria-label用の短縮形(ツールチップはカタログ名) */
const BASE_TABS: { id: BaseLayerId; label: string; icon: React.ReactNode }[] = [
  { id: 'dark', label: 'ダーク', icon: <FaMoon /> },
  { id: 'pale', label: '淡色', icon: <FaMap /> },
  { id: 'std', label: '地図', icon: <FaMapLocationDot /> },
  { id: 'satellite', label: '衛星', icon: <FaSatellite /> },
  { id: 'gsi_std_vector', label: 'ベクタ', icon: <FaVectorSquare /> },
];

/** コンテンツ切替タブ(右) */
const VIEW_TABS: { id: 'settings' | 'layers'; label: string; icon: React.ReactNode }[] = [
  { id: 'settings', label: 'リスト', icon: <FaListUl /> },
  { id: 'layers', label: 'レイヤ', icon: <FaLayerGroup /> },
];

interface SidebarProps {
  filteredFeatures: PropertyFeature[];
  selectedId: number | null;
  /** レイヤ設定(ベース選択導出・LayerPanelへの中継) */
  layerConfig: LayerConfigState;
  layerActions: LayerActions;
  /** バックエンド保存のデフォルト設定(LayerPanel/LayerSettingsDialogへの中継) */
  feSettings: FeSettings;
  /** 部分マージ保存(AppのupdateFeSettings。自動保存+Toastは呼び出し側UIで行う) */
  onFeSettingsChange: (update: FeSettings) => Promise<FeSettings | null>;
  onAdminToggle: () => void;
  /** メニュー「分析」から分析モーダルを開く */
  onOpenAnalysis: () => void;
  filters: MapFilters;
  onFiltersChange: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  prefectureOptions: string[];
  sourceOptions?: { id: string; label: string; count: number }[];
  onCardClick: (feature: PropertyFeature) => void;
  /** カードホバー状態の変化(null=離れた)。マップピンハイライト連動用 */
  onCardHover: (id: number | null) => void;
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
  layerConfig,
  layerActions,
  feSettings,
  onFeSettingsChange,
  onAdminToggle,
  onOpenAnalysis,
  filters,
  onFiltersChange,
  prefectureOptions,
  sourceOptions = [],
  onCardClick,
  onCardHover,
  className = '',
  compactHeader = false,
  excludedUnestimable = 0,
  savedCount = 0,
  onOpenComparison,
}) => {
  const [displayedLimit, setDisplayedLimit] = useState(30);
  /** コンテンツ切替(リスト=フィルタ/物件一覧、レイヤ=LayerPanel)。永続化なし */
  const [sidebarView, setSidebarView] = useState<'settings' | 'layers'>('settings');
  /** フィルタ操作系(ご利用期間〜詳細フィルタ/リセット)の開閉。デフォルトオープン・永続化なし */
  const [filtersSectionOpen, setFiltersSectionOpen] = useState(true);
  const sidebarContentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDisplayedLimit(30);
  }, [filteredFeatures]);

  // レイヤビューへ切替えた際、カードが非表示でもマウスが乗ったままになるため
  // 残ったホバー状態(マップのゴーストピン等)をクリアする
  useEffect(() => {
    if (sidebarView === 'layers') onCardHover(null);
  }, [sidebarView, onCardHover]);

  const handleScroll = () => {
    const el = sidebarContentRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 150) {
      if (displayedLimit < filteredFeatures.length) setDisplayedLimit((prev) => prev + 30);
    }
  };

  const stayMode = filters.priceMode === 'stay';
  const displayedFeatures = filteredFeatures.slice(0, displayedLimit);

  /** 選択中ベースはレイヤ配列から導出(ローカルstate禁止)。無ければ全部未選択 */
  const activeBase =
    (flattenStack(layerConfig.stack).find((l) => catalogById.get(l.id)?.role === 'base')?.id as
      | BaseLayerId
      | undefined) ?? null;

  return (
    <div
      className={cn(
        'w-full h-full min-h-0 bg-panel backdrop-blur-glass border-r border-border flex flex-col',
        'shadow-[10px_0_30px_rgba(0,0,0,0.35)]',
        className,
      )}
    >
      {/* ── ヘッダー: ロゴ + [ベース4タブ(icon)][設定/レイヤ切替(icon)][ギア] の1行 ── */}
      <div className="p-4 sm:p-5 border-b border-border shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
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

          <div
            className={cn(
              'flex flex-wrap items-center gap-1.5',
              compactHeader ? 'w-full justify-between' : 'ml-auto',
            )}
          >
            <div
              className="flex gap-1 rounded-lg border border-border bg-white/[0.04] p-1"
              role="group"
              aria-label="ベースマップ"
            >
              {BASE_TABS.map((tab) => {
                const selected = activeBase === tab.id;
                return (
                  <Tooltip key={tab.id}>
                    <TooltipTrigger
                      onClick={() => layerActions.selectBase(tab.id)}
                      render={
                        <Button
                          variant={selected ? 'default' : 'ghost'}
                          size="icon-sm"
                          aria-pressed={selected}
                          aria-label={tab.label}
                          className={cn(
                            'h-7 w-7 p-0',
                            selected
                              ? 'shadow-[0_2px_8px_rgba(133,77,255,0.3)]'
                              : 'text-text-muted hover:text-text',
                          )}
                        >
                          {tab.icon}
                        </Button>
                      }
                    />
                    <TooltipContent>
                      {catalogById.get(tab.id)?.name ?? tab.label}
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
            <div
              className="flex gap-1 rounded-lg border border-border bg-white/[0.04] p-1"
              role="group"
              aria-label="サイドバーコンテンツ"
            >
              {VIEW_TABS.map((tab) => {
                const selected = sidebarView === tab.id;
                return (
                  <Tooltip key={tab.id}>
                    <TooltipTrigger
                      onClick={() => setSidebarView(tab.id)}
                      render={
                        <Button
                          variant={selected ? 'default' : 'ghost'}
                          size="icon-sm"
                          aria-pressed={selected}
                          aria-label={tab.label}
                          className={
                            selected
                              ? 'shadow-[0_2px_8px_rgba(133,77,255,0.3)]'
                              : 'text-text-muted hover:text-text'
                          }
                        >
                          {tab.icon}
                        </Button>
                      }
                    />
                    <TooltipContent>{tab.label}</TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
            <Menu>
              <MenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="メニュー"
                    className="text-text-muted hover:text-text"
                  >
                    <FaBars />
                  </Button>
                }
              />
              <MenuContent align="end">
                <MenuItem onClick={onAdminToggle}>
                  <FaGear className="text-sm text-text-muted" />
                  設定
                </MenuItem>
                <MenuItem onClick={onOpenAnalysis}>
                  <FaChartLine className="text-sm text-text-muted" />
                  分析
                </MenuItem>
              </MenuContent>
            </Menu>
          </div>
        </div>
      </div>

      <div
        className={cn(
          // gapを付けない: 折りたたみ後も空のCollapsibleルートボックスがgap分の余白を
          // 残すため、区切り分はCollapsibleContent内のgap/pbで賄う(閉時は余白ゼロ)
          'p-4 sm:p-5 overflow-y-auto grow flex flex-col min-h-0 app-scrollbar',
          sidebarView === 'layers' && 'hidden',
        )}
        ref={sidebarContentRef}
        onScroll={handleScroll}
      >
        {/* ── フィルタ操作系(ヘッダー下のフィルタアイコンボタンで開閉) ──
            閉じている間はパネルごとアンマウントされ、この位置には何も出ない */}
        <Collapsible open={filtersSectionOpen} onOpenChange={setFiltersSectionOpen}>
          <CollapsibleContent className="flex flex-col gap-4 pb-4">
            <FilterPanel
              filters={filters}
              onFiltersChange={onFiltersChange}
              prefectureOptions={prefectureOptions}
              sourceOptions={sourceOptions}
            />

            {/* 仕切り線はフィルタ群に同梱(折りたたみ時に線と余白が残留しないようパネルごと畳む) */}
            <Separator />
          </CollapsibleContent>
        </Collapsible>

        <div>
          <div className="flex items-center justify-between gap-2 mb-1">
            <p className="text-sm text-text-muted m-0">物件数: {filteredFeatures.length}件</p>
            <div className="flex items-center gap-1.5 shrink-0">
              <Tooltip>
                <TooltipTrigger
                  onClick={() => setFiltersSectionOpen((v) => !v)}
                  render={
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-pressed={filtersSectionOpen}
                      aria-label={filtersSectionOpen ? 'フィルタを折りたたむ' : 'フィルタを表示'}
                      className={cn(
                        'shrink-0',
                        filtersSectionOpen
                          ? 'text-primary'
                          : 'text-text-muted hover:text-text',
                      )}
                    >
                      <FaFilter />
                    </Button>
                  }
                />
                <TooltipContent>
                  {filtersSectionOpen ? 'フィルタを折りたたむ' : 'フィルタを表示'}
                </TooltipContent>
              </Tooltip>
              {onOpenComparison && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs font-semibold"
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
                  onHoverChange={onCardHover}
                  priceMode={filters.priceMode}
                />
              ))}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* ── レイヤビュー(設定ビューの兄弟。設定側は hidden でマウント維持) ── */}
      {sidebarView === 'layers' && (
        <div className="min-h-0 grow">
          <LayerPanel
            layerConfig={layerConfig}
            layerActions={layerActions}
            feSettings={feSettings}
            onFeSettingsChange={onFeSettingsChange}
          />
        </div>
      )}
    </div>
  );
};
