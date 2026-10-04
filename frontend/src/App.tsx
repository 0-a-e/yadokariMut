import React, { useState, useEffect, useRef, useCallback, useMemo, Suspense } from 'react';
import L from 'leaflet';
import {
  PropertyFeature,
  BoundsData,
  ShortlistStatus,
  AnalysisTarget,
} from './types.ts';
import { collectPrefectures, collectSources } from './lib/filterLogic.ts';
import { Sidebar } from './components/sidebar/Sidebar.tsx';
import { MapPane } from './components/map/MapPane.tsx';
import { DetailPanel } from './components/detail/DetailPanel.tsx';
import { ComparisonBoard } from './components/shared/ComparisonBoard.tsx';
import { AdminModal } from './components/admin/AdminModal.tsx';
/** recharts を含むため遅延ロード */
const AnalysisModal = React.lazy(() =>
  import('./components/analysis/AnalysisModal.tsx').then((m) => ({ default: m.AnalysisModal })),
);
import { LightboxModal } from './components/shared/LightboxModal.tsx';
import { GeojsonLoadProgress } from './components/shared/GeojsonLoadProgress.tsx';
import { AccessSessionDialog } from './components/shared/AccessSessionDialog.tsx';
import { AgentChat } from './components/chat/AgentChat.tsx';
import { useCopilotMapContext } from './hooks/useCopilotContext.ts';
import { useMapActions } from './hooks/useMapActions.ts';
import { useIsMobile } from './hooks/useIsMobile.ts';
import { usePropertyData } from './hooks/usePropertyData.ts';
import { useFilteredFeatures } from './hooks/useFilteredFeatures.ts';
import { useFiltersUrlSync } from './hooks/useFiltersUrlSync.ts';
import { useSelectedFeature } from './hooks/useSelectedFeature.ts';
import { useComparison } from './hooks/useComparison.ts';
import { useDrawnAreaMode } from './hooks/useDrawnAreaMode.ts';
import { useFeSettings } from './hooks/useFeSettings.ts';
import type { LayerConfigState } from './lib/layers/types.ts';
import { catalogById } from './lib/layers/catalog.ts';
import {
  loadLayerConfig,
  makeLayerActions,
  saveLayerConfig,
  type LayerActions,
} from './lib/layers/state.ts';
import { resolveInitialOpacity, resolvePinClustering } from './lib/feSettings.ts';
import { useExplorerSearch } from './hooks/useExplorerSearch.ts';
import { TooltipProvider } from '@/components/ui/tooltip.tsx';
import { Toaster, toast } from '@/components/ui/toast.tsx';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable.tsx';
import { FaMapLocationDot, FaCircle, FaHouse } from 'react-icons/fa6';
import { loadOrCreateActiveThread, setActiveThreadId } from './lib/chatSessions.ts';
import { createId } from './lib/utils.ts';

type MobileTab = 'list' | 'map' | 'chat';

export const App: React.FC = () => {
  const isMobile = useIsMobile();
  const { search, patchSearch } = useExplorerSearch();

  const { rawGeojsonData, setRawGeojsonData, rawGeojsonRef, geojsonProgress } =
    usePropertyData();
  const { feSettings, feSettingsRef, updateFeSettings } = useFeSettings();

  const [layerConfig, setLayerConfig] = useState<LayerConfigState>(() => loadLayerConfig());
  const layerActions = useMemo(
    () =>
      makeLayerActions(
        (updater) => setLayerConfig((c) => updater(c)),
        (id) => resolveInitialOpacity(feSettingsRef.current, catalogById.get(id)),
      ),
    // feSettingsRef は最新値読み込み用のため依存に不要
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  /**
   * 削除系をtoast+復元付きにラップ(設計doc §4)。
   * 実行前のlayerConfig snapshotを確保し、toastの[復元]で直接戻す。
   */
  const undoableLayerActions: LayerActions = useMemo(() => {
    const withUndo = (label: string, run: () => void) => {
      const snapshot = JSON.parse(JSON.stringify(layerConfig)) as LayerConfigState;
      run();
      const toastId = `undo-${createId()}`;
      toast.add({
        id: toastId,
        title: `「${label}」を削除しました`,
        timeout: 6000,
        actionProps: {
          children: '復元',
          onClick: () => {
            setLayerConfig(() => snapshot);
            toast.close(toastId);
          },
        },
      });
    };
    return {
      ...layerActions,
      removeLayer: (id) =>
        withUndo(catalogById.get(id)?.name ?? id, () => layerActions.removeLayer(id)),
      removeGroup: (groupId) => {
        const name = layerConfig.groups.find((g) => g.id === groupId)?.name ?? groupId;
        withUndo(name, () => layerActions.removeGroup(groupId));
      },
    };
  }, [layerActions, layerConfig]);
  useEffect(() => {
    saveLayerConfig(layerConfig);
  }, [layerConfig]);

  const [isAdminOpen, setIsAdminOpen] = useState(false);
  /** 分析モーダルの表示対象(null=閉じる)。市場全体(メニュー)or 物件単位(詳細パネル) */
  const [analysisTarget, setAnalysisTarget] = useState<AnalysisTarget | null>(null);
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);
  const [lightboxImages, setLightboxImages] = useState<string[]>([]);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [threadId, setThreadId] = useState<string>(() => loadOrCreateActiveThread());
  const [mobileTab, setMobileTab] = useState<MobileTab>('map');
  /** サイドバーカードのホバー中物件(マップピンハイライト連動) */
  const [hoveredPropertyId, setHoveredPropertyId] = useState<number | null>(null);
  const [mapBounds, setMapBounds] = useState<BoundsData | null>(null);
  const [mapState, setMapState] = useState<{ center: [number, number] | null; zoom: number }>({
    center: null,
    zoom: 13,
  });
  const mapPaneRef = useRef<{ map: L.Map | null; cluster: any }>({ map: null, cluster: null });

  const { filters, filtersRef, patchFilters, handleDatesChange } = useFiltersUrlSync(
    search,
    patchSearch,
  );
  const { filteredFeatures, filteredFeaturesRef, excludedUnestimable } = useFilteredFeatures(
    rawGeojsonData,
    filters,
    mapBounds,
  );

  const resolveFeatureById = useCallback(
    (id: number): PropertyFeature | null => {
      const filtered = filteredFeaturesRef.current.find((f) => f.properties.id === id);
      if (filtered) return filtered;
      return rawGeojsonRef.current?.features.find((f) => f.properties.id === id) ?? null;
    },
    [filteredFeaturesRef, rawGeojsonRef],
  );

  const { selectedFeature, setSelectedFeature, openFeature, closeFeature } =
    useSelectedFeature({
      search,
      patchSearch,
      resolveFeatureById,
      rawGeojsonData,
      filteredFeatures,
      isMobile,
      setMobileTab,
    });

  const {
    savedFeatures,
    compareIds,
    comparisonOpen,
    compareCandidateFeatures,
    handleCompareIdsChange,
    handleComparisonOpenChange,
    handleOpenComparison,
  } = useComparison({ rawGeojsonData, filteredFeatures, filters, search, patchSearch });

  const { drawMode, handleShapeDrawn, handleShapeClear, handleDrawModeChange } =
    useDrawnAreaMode({ filters, filtersRef, patchFilters, isMobile, setMobileTab });

  const prefectureOptions = useMemo(
    () => collectPrefectures(rawGeojsonData),
    [rawGeojsonData],
  );

  const sourceOptions = useMemo(
    () => collectSources(rawGeojsonData),
    [rawGeojsonData],
  );

  /** ショートリスト状態のローカル反映(選択中 + 全件データの双方へパッチ) */
  const applyShortlistLocal = useCallback(
    (propertyId: number, status: ShortlistStatus, comment?: string | null) => {
      const patchProps = (props: PropertyFeature['properties']) => ({
        ...props,
        shortlist_status: status,
        ...(comment !== undefined ? { shortlist_comment: comment } : {}),
      });
      setSelectedFeature((prev) =>
        prev && prev.properties.id === propertyId
          ? { ...prev, properties: patchProps(prev.properties) }
          : prev,
      );
      setRawGeojsonData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          features: prev.features.map((feat) =>
            feat.properties.id === propertyId
              ? { ...feat, properties: patchProps(feat.properties) }
              : feat,
          ),
        };
      });
    },
    [setSelectedFeature, setRawGeojsonData],
  );

  useCopilotMapContext(
    mapState,
    selectedFeature,
    filteredFeatures,
    filters,
    mapBounds,
    excludedUnestimable,
    savedFeatures,
    layerConfig,
  );

  useMapActions({
    mapPaneRef,
    filteredFeatures,
    rawGeojsonRef,
    filtersRef,
    mapBounds,
    onSelectFeature: (feature) => {
      openFeature(feature);
    },
    layerConfig,
    layerActions: layerActions,
    onPatchFilters: patchFilters,
    onShortlistLocal: applyShortlistLocal,
    resolveFeatureById,
  });

  const handleMapMove = (center: [number, number], zoom: number, bounds: BoundsData) => {
    setMapState({ center, zoom });
    setMapBounds(bounds);
  };

  const handleMapInit = (map: L.Map, cluster: any) => {
    mapPaneRef.current = { map, cluster };
  };

  /** 詳細API由来の遅延フィールド(comment / price_history 等)をローカルへマージ */
  const applyDetailPatch = useCallback(
    (
      propertyId: number,
      patch: {
        shortlist_comment?: string | null;
        shortlist_status?: ShortlistStatus;
        price_history?: PropertyFeature['properties']['price_history'];
        contract_fee_yen?: number | null;
      },
    ) => {
      const merge = (props: PropertyFeature['properties']) => ({
        ...props,
        ...(patch.shortlist_comment !== undefined
          ? { shortlist_comment: patch.shortlist_comment }
          : {}),
        ...(patch.shortlist_status !== undefined
          ? { shortlist_status: patch.shortlist_status }
          : {}),
        ...(patch.price_history !== undefined ? { price_history: patch.price_history } : {}),
        ...(patch.contract_fee_yen !== undefined
          ? { contract_fee_yen: patch.contract_fee_yen }
          : {}),
      });
      setSelectedFeature((prev) =>
        prev && prev.properties.id === propertyId
          ? { ...prev, properties: merge(prev.properties) }
          : prev,
      );
      setRawGeojsonData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          features: prev.features.map((feat) =>
            feat.properties.id === propertyId
              ? { ...feat, properties: merge(feat.properties) }
              : feat,
          ),
        };
      });
    },
    [setSelectedFeature, setRawGeojsonData],
  );

  const handleShortlistUpdate = (
    propertyId: number,
    status: ShortlistStatus,
    comment?: string | null,
  ) => {
    applyShortlistLocal(propertyId, status, comment);
  };

  const handleOpenLightbox = (images: string[], index: number) => {
    setLightboxImages(images);
    setLightboxIndex(index);
    setIsLightboxOpen(true);
  };
  // 表示中のインデックスはLightboxModal(Carousel)内部で管理されるため、
  // Appが持つlightboxIndexはオープン時の初期値としてのみ使う

  const handleCardClick = (feature: PropertyFeature) => {
    // タッチ端末ではタップでmouseenterのみ飛びmouseleaveが来ないことがあるため、
    // 選択時にホバー状態を明示クリアする(マップのゴーストピン残存防止)
    setHoveredPropertyId(null);
    openFeature(feature);
  };

  const handleSelectFeatureById = useCallback(
    (id: number) => {
      const feat = resolveFeatureById(id);
      if (feat) openFeature(feat);
    },
    [resolveFeatureById, openFeature],
  );

  const handleThreadChange = useCallback((id: string) => {
    setActiveThreadId(id);
    setThreadId(id);
  }, []);

  const handleMarkerClick = (feature: PropertyFeature) => {
    openFeature(feature);
  };

  const mapVisible = !isMobile || mobileTab === 'map';
  const pinClustering = resolvePinClustering(feSettings);

  const sidebarNode = (
    <Sidebar
      filteredFeatures={filteredFeatures}
      selectedId={selectedFeature?.properties.id ?? null}
      layerConfig={layerConfig}
      layerActions={undoableLayerActions}
      feSettings={feSettings}
      onFeSettingsChange={updateFeSettings}
      onAdminToggle={() => setIsAdminOpen(true)}
      onOpenAnalysis={() => setAnalysisTarget({ kind: 'market' })}
      filters={filters}
      onFiltersChange={patchFilters}
      prefectureOptions={prefectureOptions}
      sourceOptions={sourceOptions}
      onCardClick={handleCardClick}
      onCardHover={setHoveredPropertyId}
      compactHeader={isMobile}
      excludedUnestimable={excludedUnestimable}
      savedCount={savedFeatures.length}
      onOpenComparison={handleOpenComparison}
    />
  );

  const mapNode = (
    <div className="relative h-full w-full min-h-0 bg-bg">
      <MapPane
        filteredFeatures={filteredFeatures}
        selectedId={selectedFeature?.properties.id ?? null}
        hoveredId={hoveredPropertyId}
        layerConfig={layerConfig}
        pinClustering={pinClustering}
        drawnPolygon={filters.drawnPolygon}
        drawMode={drawMode}
        onDrawModeChange={handleDrawModeChange}
        onShapeDrawn={handleShapeDrawn}
        onShapeClear={handleShapeClear}
        onMarkerClick={handleMarkerClick}
        onMapMove={handleMapMove}
        onMapInit={handleMapInit}
        isVisible={mapVisible}
      />
      <DetailPanel
        feature={selectedFeature}
        onClose={closeFeature}
        onShortlistUpdate={handleShortlistUpdate}
        onImageClick={handleOpenLightbox}
        checkIn={filters.checkIn}
        checkOut={filters.checkOut}
        onDatesChange={handleDatesChange}
        onDetailPatch={applyDetailPatch}
        onOpenAnalysis={(propertyId) => setAnalysisTarget({ kind: 'property', propertyId })}
      />
    </div>
  );

  const chatNode = (
    <div className="h-full w-full min-h-0 bg-panel border-l border-border flex flex-col overflow-hidden">
      <AgentChat
        threadId={threadId}
        onThreadChange={handleThreadChange}
        onSelectFeature={handleSelectFeatureById}
      />
    </div>
  );

  return (
    <TooltipProvider>
      <div className="flex flex-col w-full h-full relative overflow-hidden">
        {!isMobile ? (
          /* ── Desktop: resizable 3-pane ── */
          <ResizablePanelGroup orientation="horizontal" className="h-full w-full min-h-0">
            <ResizablePanel defaultSize="26" minSize="18" maxSize="40" className="min-w-0">
              {sidebarNode}
            </ResizablePanel>
            <ResizableHandle withHandle className="bg-border hover:bg-primary/40 transition-colors w-1.5" />
            <ResizablePanel defaultSize="46" minSize="30" className="min-w-0">
              {mapNode}
            </ResizablePanel>
            <ResizableHandle withHandle className="bg-border hover:bg-primary/40 transition-colors w-1.5" />
            <ResizablePanel defaultSize="28" minSize="20" maxSize="42" className="min-w-0">
              {chatNode}
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          /* ── Mobile: single pane + bottom tabs ── */
          <div className="flex flex-col h-full w-full min-h-0">
            <div className="flex-1 min-h-0 relative overflow-hidden">
              <div className={`h-full w-full ${mobileTab === 'list' ? 'block' : 'hidden'}`}>
                {sidebarNode}
              </div>
              {/* Keep map mounted while on mobile for Leaflet stability */}
              <div
                className={`h-full w-full ${
                  mobileTab === 'map'
                    ? 'block'
                    : 'invisible absolute inset-0 pointer-events-none'
                }`}
              >
                {mapNode}
              </div>
              <div className={`h-full w-full ${mobileTab === 'chat' ? 'block' : 'hidden'}`}>
                {chatNode}
              </div>
            </div>

            <nav className="shrink-0 border-t border-border bg-[#12141c]/95 backdrop-blur-md pb-[env(safe-area-inset-bottom)] z-[2200]">
              <div className="grid grid-cols-3 h-14">
                {(
                  [
                    { id: 'list' as const, label: 'ホーム', icon: <FaHouse /> },
                    { id: 'map' as const, label: '地図', icon: <FaMapLocationDot /> },
                    { id: 'chat' as const, label: 'AI', icon: <FaCircle /> },
                  ] as const
                ).map((tab) => {
                  const active = mobileTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setMobileTab(tab.id)}
                      className={`flex flex-col items-center justify-center gap-0.5 text-[11px] font-semibold transition-colors ${
                        active ? 'text-primary' : 'text-text-muted hover:text-text'
                      }`}
                    >
                      <span className={`text-lg ${active ? 'scale-110' : ''} transition-transform`}>
                        {tab.icon}
                      </span>
                      {tab.label}
                    </button>
                  );
                })}
              </div>
            </nav>
          </div>
        )}

        <AdminModal
          isOpen={isAdminOpen}
          onClose={() => setIsAdminOpen(false)}
          onGeoJsonLoaded={setRawGeojsonData}
          feSettings={feSettings}
          onFeSettingsUpdate={updateFeSettings}
          filteredFeatures={filteredFeatures}
          allFeatures={rawGeojsonData?.features ?? []}
        />

        <Suspense fallback={null}>
          <AnalysisModal
            isOpen={analysisTarget !== null}
            onClose={() => setAnalysisTarget(null)}
            target={analysisTarget ?? { kind: 'market' }}
            allFeatures={rawGeojsonData?.features ?? []}
            onTargetChange={setAnalysisTarget}
          />
        </Suspense>

        <AccessSessionDialog />

        {geojsonProgress && <GeojsonLoadProgress progress={geojsonProgress} />}

        <Toaster />

        <LightboxModal
          isOpen={isLightboxOpen}
          images={lightboxImages}
          initialIndex={lightboxIndex}
          title={selectedFeature?.properties.title ?? ''}
          onClose={() => setIsLightboxOpen(false)}
        />

        <ComparisonBoard
          open={comparisonOpen}
          onOpenChange={handleComparisonOpenChange}
          candidateFeatures={compareCandidateFeatures}
          compareIds={compareIds}
          onCompareIdsChange={handleCompareIdsChange}
          checkIn={filters.checkIn}
          checkOut={filters.checkOut}
          onSelectFeature={handleSelectFeatureById}
        />
      </div>
    </TooltipProvider>
  );
};
