import React, { useState, useEffect, useRef, useCallback, useMemo, Suspense } from 'react';
import L from 'leaflet';
import type {
  BuildingFeature,
  BuildingUnit,
  PropertyFeature,
  BoundsData,
  ShortlistStatus,
  AnalysisTarget,
} from './types.ts';
import { collectPrefectures, collectSources } from './lib/filterLogic.ts';
import { nowJstIso } from './lib/format.ts';
import { buildRoomIndex, buildingDisplayName, normalizeUnit, type RoomIndexEntry } from './lib/building.ts';
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
import { useBuildingData } from './hooks/useBuildingData.ts';
import { useFilteredFeatures } from './hooks/useFilteredFeatures.ts';
import { flattenBuildingFeatures } from './lib/building.ts';
import { BuildingPanel } from './components/detail/BuildingPanel.tsx';
import { postBuildingShortlist } from './lib/api/buildings.ts';
import { postShortlist } from './lib/api/properties.ts';
import { notify } from './lib/notify.ts';
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
import {
  resolveInitialOpacity,
  resolveMapBackground,
  resolvePinBalloonPermanent,
  resolvePinClustering,
} from './lib/feSettings.ts';
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
import { DEFAULT_ZOOM } from './lib/mapDefaults.ts';

type MobileTab = 'list' | 'map' | 'chat';

export const App: React.FC = () => {
  const isMobile = useIsMobile();
  const { search, patchSearch } = useExplorerSearch();

  const { rawBuildingData, setRawBuildingData, geojsonProgress } = useBuildingData();
  /**
   * 全 units の部屋平面リスト(B2-α 互換供給面)。生データの正本は
   * rawBuildingData(建物 Feature)で、部屋オブジェクトが必要な下流
   * (useComparison / AnalysisModal / resolveFeatureById / AI context)へは
   * この派生を渡す。B2-β 以降に各 UI が建物を直接消費する形へ移行する。
   */
  const flatRawFeatures = useMemo(
    () => (rawBuildingData ? flattenBuildingFeatures(rawBuildingData.features) : []),
    [rawBuildingData],
  );
  const flatRawFeaturesRef = useRef(flatRawFeatures);
  useEffect(() => {
    flatRawFeaturesRef.current = flatRawFeatures;
  }, [flatRawFeatures]);
  const flatRawCollection = useMemo(
    () => ({ type: 'FeatureCollection' as const, features: flatRawFeatures }),
    [flatRawFeatures],
  );
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
  /** サイドバーカードのホバー中建物(マップピンハイライト連動) */
  const [hoveredBuildingId, setHoveredBuildingId] = useState<number | null>(null);
  const [mapBounds, setMapBounds] = useState<BoundsData | null>(null);
  const [mapState, setMapState] = useState<{ center: [number, number] | null; zoom: number }>({
    center: null,
    zoom: DEFAULT_ZOOM,
  });
  const mapPaneRef = useRef<{ map: L.Map | null; cluster: any }>({ map: null, cluster: null });

  const { filters, filtersRef, patchFilters, handleDatesChange } = useFiltersUrlSync(
    search,
    patchSearch,
  );
  const {
    filteredFeatures,
    filteredFeaturesRef,
    filteredBuildings,
    matchedRoomIds,
    excludedUnestimable,
  } = useFilteredFeatures(rawBuildingData, filters, mapBounds);
  /**
   * roomId → 建物の索引(全 raw 建物対象)。選択中部屋の建物解決
   * (selectedBuildingId)と部屋行クリックの建物解決(handleUnitClick)で共用。
   */
  const roomIndex = useMemo(
    () =>
      rawBuildingData
        ? buildRoomIndex(rawBuildingData.features)
        : new Map<number, RoomIndexEntry>(),
    [rawBuildingData],
  );
  const buildingById = useMemo(() => {
    const m = new Map<number, BuildingFeature>();
    rawBuildingData?.features.forEach((f) => m.set(f.properties.id, f));
    return m;
  }, [rawBuildingData]);

  /** 建物 id → 建物 Feature(raw 正本から・Phase B2-γ) */
  const resolveBuildingById = useCallback(
    (buildingId: number): BuildingFeature | null => buildingById.get(buildingId) ?? null,
    [buildingById],
  );

  /** 部屋 id → 所属建物(buildRoomIndex 経由・Phase B2-γ) */
  const resolveBuildingByRoomId = useCallback(
    (roomId: number): BuildingFeature | null => {
      const entry = roomIndex.get(roomId);
      return entry ? (buildingById.get(entry.buildingId) ?? null) : null;
    },
    [roomIndex, buildingById],
  );

  const resolveFeatureById = useCallback(
    (id: number): PropertyFeature | null => {
      const filtered = filteredFeaturesRef.current.find((f) => f.properties.id === id);
      if (filtered) return filtered;
      return flatRawFeaturesRef.current.find((f) => f.properties.id === id) ?? null;
    },
    [filteredFeaturesRef, flatRawFeaturesRef],
  );

  const {
    selectedFeature,
    setSelectedFeature,
    openFeature,
    closeFeature,
    selectedBuilding,
    setSelectedBuilding,
    openBuilding,
    closeBuilding,
  } = useSelectedFeature({
    search,
    patchSearch,
    resolveFeatureById,
    resolveBuildingById,
    resolveBuildingByRoomId,
    rawGeojsonData: flatRawCollection,
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
    compareBuildingIds,
    compareBuildingCandidates,
    handleCompareBuildingIdsChange,
  } = useComparison({
    rawGeojsonData: flatRawCollection,
    filteredFeatures,
    filters,
    search,
    patchSearch,
    rawBuildings: rawBuildingData?.features,
  });

  const { drawMode, handleShapeDrawn, handleShapeClear, handleDrawModeChange } =
    useDrawnAreaMode({ filters, filtersRef, patchFilters, isMobile, setMobileTab });

  const prefectureOptions = useMemo(
    () => collectPrefectures(flatRawCollection),
    [flatRawCollection],
  );

  const sourceOptions = useMemo(
    () => collectSources(flatRawCollection),
    [flatRawCollection],
  );

  /**
   * 選択中フィーチャー(selectedFeature)と全件データ(rawBuildingData の該当 unit)の
   * 双方へ properties パッチを適用する共通走査。ショートリスト反映・詳細API遅延
   * フィールドのマージ(applyShortlistLocal / applyDetailPatch)がこの1本を通る。
   * patch はスプレッド適用のため、unit 由来の拡張フィールド
   * (source_property_id / images 行配列等)は失われない。
   */
  const patchFeatureProperties = useCallback(
    (
      propertyId: number,
      /** unit(BuildingUnit)と平面(PropertyProperties)の共通キーに限定した部分パッチ */
      patch: Partial<
        Pick<
          PropertyFeature['properties'],
          | 'shortlist_status'
          | 'shortlist_updated_at'
          | 'shortlist_comment'
          | 'price_history'
          | 'stay_estimate'
        >
      >,
    ) => {
      setSelectedFeature((prev) =>
        prev && prev.properties.id === propertyId
          ? { ...prev, properties: { ...prev.properties, ...patch } }
          : prev,
      );
      setRawBuildingData((prev) => {
        if (!prev) return prev;
        let touched = false;
        const features = prev.features.map((feat) => {
          const idx = feat.properties.units.findIndex((u) => u.id === propertyId);
          if (idx < 0) return feat;
          touched = true;
          const units = feat.properties.units.map((u, i) =>
            i === idx ? { ...u, ...patch } : u,
          );
          return { ...feat, properties: { ...feat.properties, units } };
        });
        return touched ? { ...prev, features } : prev;
      });
    },
    [setSelectedFeature, setRawBuildingData],
  );

  /** ショートリスト状態のローカル反映(パッチ内容の組み立てのみ担う) */
  const applyShortlistLocal = useCallback(
    (propertyId: number, status: ShortlistStatus, comment?: string | null) => {
      patchFeatureProperties(propertyId, {
        shortlist_status: status,
        // BE upsert と同じ「更新のたびに updated_at が進む」意味論を再現
        // (最終編集順ソートが再取得なしで反映される)
        shortlist_updated_at: nowJstIso(),
        ...(comment !== undefined ? { shortlist_comment: comment } : {}),
      });
    },
    [patchFeatureProperties],
  );

  /**
   * 建物選択(建物パネル ?b= を開く・βγ統合後の本導線)。selectBuilding ツール・
   * showBuildings カード・比較ボード建物タブの「地図」ボタンがこの1本に集約される。
   */
  const handleSelectBuildingById = useCallback(
    (buildingId: number) => {
      const building = resolveBuildingById(buildingId);
      if (building) openBuilding(building);
    },
    [resolveBuildingById, openBuilding],
  );


  /** 建物ショートリストのローカル反映(selectedBuilding + raw の建物 properties へ) */
  const applyBuildingShortlistLocal = useCallback(
    (buildingId: number, status: 'saved' | 'none', comment?: string | null) => {
      const patchProps = (props: BuildingFeature['properties']): BuildingFeature['properties'] => ({
        ...props,
        shortlist_status: status,
        // BE upsert と同じ「更新のたびに updated_at が進む」意味論を再現
        // (最終編集順ソートが再取得なしで反映される)
        shortlist_updated_at: nowJstIso(),
        ...(comment !== undefined ? { shortlist_comment: comment } : {}),
      });
      setSelectedBuilding((prev) =>
        prev && prev.properties.id === buildingId
          ? { ...prev, properties: patchProps(prev.properties) }
          : prev,
      );
      setRawBuildingData((prev) => {
        if (!prev) return prev;
        let touched = false;
        const features = prev.features.map((feat) => {
          if (feat.properties.id !== buildingId) return feat;
          touched = true;
          return { ...feat, properties: patchProps(feat.properties) };
        });
        return touched ? { ...prev, features } : prev;
      });
    },
    [setSelectedBuilding, setRawBuildingData],
  );

  const handleBuildingShortlistUpdate = useCallback(
    async (buildingId: number, status: 'saved' | 'none', comment?: string | null) => {
      try {
        await postBuildingShortlist(buildingId, status, comment ?? null);
        applyBuildingShortlistLocal(buildingId, status, comment);
      } catch (err) {
        console.error(err);
        notify('建物の保存状態の更新に失敗しました。', 'error');
      }
    },
    [applyBuildingShortlistLocal],
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
    filteredBuildings,
  );

  useMapActions({
    mapPaneRef,
    filteredFeatures,
    rawBuildingData,
    filtersRef,
    mapBounds,
    onSelectFeature: (feature) => {
      openFeature(feature);
    },
    onSelectBuilding: handleSelectBuildingById,
    layerConfig,
    layerActions: layerActions,
    onPatchFilters: patchFilters,
    onShortlistLocal: applyShortlistLocal,
    onBuildingShortlistLocal: applyBuildingShortlistLocal,
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
      },
    ) => {
      patchFeatureProperties(propertyId, patch);
    },
    [patchFeatureProperties],
  );

  const handleShortlistUpdate = (
    propertyId: number,
    status: ShortlistStatus,
    comment?: string | null,
  ) => {
    applyShortlistLocal(propertyId, status, comment);
  };


  /**
   * 「この建物をまとめて非表示」(Phase B2-γ・計画 §4.3 承認)。
   * saved 以外の active 部屋へ hide を個別 POST(BE 新 API 不要・最大 63 部屋)し、
   * ローカル反映(applyShortlistLocal)で units へ一括適用 → ピン sig 変化で再構築。
   */
  const handleBulkHideUnits = useCallback(
    async (units: BuildingUnit[]) => {
      const results = await Promise.allSettled(
        units.map((u) => postShortlist(u.id, 'hide')),
      );
      const failed = results.filter((r) => r.status === 'rejected').length;
      for (const [i, u] of units.entries()) {
        if (results[i].status === 'fulfilled') {
          applyShortlistLocal(u.id, 'hide');
        }
      }
      if (failed > 0) {
        notify(`${failed} 件の非表示に失敗しました。再度お試しください。`, 'error');
      } else {
        notify(`${units.length} 部屋を非表示にしました。`);
      }
    },
    [applyShortlistLocal],
  );

  const handleOpenLightbox = (images: string[], index: number) => {
    setLightboxImages(images);
    setLightboxIndex(index);
    setIsLightboxOpen(true);
  };
  // 表示中のインデックスはLightboxModal(Carousel)内部で管理されるため、
  // Appが持つlightboxIndexはオープン時の初期値としてのみ使う

  /**
   * 建物クリック(β導線・γ統合): 建物パネルを開く(?b= push・部屋パネルは閉じる)。
   * タッチ端末のゴーストピン残存防止でホバー状態を明示クリアするのはカードと同じ。
   */
  const handleBuildingClick = useCallback(
    (building: BuildingFeature) => {
      setHoveredBuildingId(null);
      openBuilding(building);
    },
    [openBuilding],
  );

  /** 建物カードの部屋行クリック(該当部屋のパネル直開・§4.2) */
  const handleUnitClick = useCallback(
    (unit: BuildingUnit) => {
      const entry = roomIndex.get(unit.id);
      const building = entry ? buildingById.get(entry.buildingId) : undefined;
      if (!building) return;
      openFeature({
        type: 'Feature',
        geometry: building.geometry,
        properties: normalizeUnit(unit, building.properties),
      });
    },
    [roomIndex, buildingById, openFeature],
  );

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

  /**
   * 選択中建物のハイライト対象(?b= の正本優先。?id= のみの場合は所属建物へ波及)。
   * 地図/サイドバーの選択ハイライトは建物単位で共有する。
   */
  const selectedBuildingId =
    selectedBuilding?.properties.id ??
    (selectedFeature
      ? (roomIndex.get(selectedFeature.properties.id)?.buildingId ?? null)
      : null);

  const mapVisible = !isMobile || mobileTab === 'map';
  const pinClustering = resolvePinClustering(feSettings);
  /** 物件バルーン常時表示の保存値(実効値は MapPane 内でクラスタリングと掛けて算出) */
  const pinBalloonPermanent = resolvePinBalloonPermanent(feSettings);
  /** 最下レイヤ(基本地図)下のコンテナ背景色(LayerPanel「基底の背景色」トグル) */
  const mapBackground = resolveMapBackground(feSettings);

  const sidebarNode = (
    <Sidebar
      buildings={filteredBuildings}
      matchedRoomIds={matchedRoomIds}
      selectedBuildingId={selectedBuildingId}
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
      onBuildingClick={handleBuildingClick}
      onUnitClick={handleUnitClick}
      onCardHover={setHoveredBuildingId}
      compactHeader={isMobile}
      excludedUnestimable={excludedUnestimable}
      savedCount={savedFeatures.length}
      onOpenComparison={handleOpenComparison}
    />
  );

  const mapNode = (
    <div className="relative h-full w-full min-h-0 bg-bg">
      <MapPane
        buildings={filteredBuildings}
        matchedRoomIds={matchedRoomIds}
        selectedBuildingId={selectedBuildingId}
        hoveredBuildingId={hoveredBuildingId}
        priceMode={filters.priceMode}
        checkIn={filters.checkIn}
        checkOut={filters.checkOut}
        layerConfig={layerConfig}
        pinClustering={pinClustering}
        pinBalloonPermanent={pinBalloonPermanent}
        mapBackground={mapBackground}
        drawnPolygon={filters.drawnPolygon}
        drawMode={drawMode}
        onDrawModeChange={handleDrawModeChange}
        onShapeDrawn={handleShapeDrawn}
        onShapeClear={handleShapeClear}
        onBuildingClick={handleBuildingClick}
        onMapMove={handleMapMove}
        onMapInit={handleMapInit}
        isVisible={mapVisible}
      />
      {/* 建物パネル(2 層の上層・?b=。部屋パネルが開いていれば下層に隠れる) */}
      <BuildingPanel
        building={selectedFeature ? null : selectedBuilding}
        matchedRoomIds={matchedRoomIds}
        onClose={closeBuilding}
        onUnitClick={handleUnitClick}
        onBulkHide={handleBulkHideUnits}
        onAddToCompare={(buildingId) => {
          // 上限 5 は normalizeCompareIds(useComparison)が担保。被りは除去される
          handleCompareBuildingIdsChange([...compareBuildingIds, buildingId]);
          notify('建物を比較候補に追加しました。');
        }}
        onImageClick={handleOpenLightbox}
        isStayMode={filters.priceMode === 'stay'}
        onBuildingShortlistUpdate={handleBuildingShortlistUpdate}
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
        onBackToBuilding={selectedBuilding ? closeFeature : undefined}
      />
    </div>
  );

  const chatNode = (
    <div className="h-full w-full min-h-0 bg-panel border-l border-border flex flex-col overflow-hidden">
      <AgentChat
        threadId={threadId}
        onThreadChange={handleThreadChange}
        onSelectFeature={handleSelectFeatureById}
        onSelectBuilding={handleSelectBuildingById}
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
          onGeoJsonLoaded={setRawBuildingData}
          filteredBuildings={filteredBuildings}
          allBuildings={rawBuildingData?.features ?? []}
        />

        <Suspense fallback={null}>
          <AnalysisModal
            isOpen={analysisTarget !== null}
            onClose={() => setAnalysisTarget(null)}
            target={analysisTarget ?? { kind: 'market' }}
            allFeatures={flatRawFeatures}
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
          // 建物パネルからのオープンは部屋 Feature が無いので建物表示名へフォールバック
          title={selectedFeature?.properties.title
            ?? (selectedBuilding ? buildingDisplayName(selectedBuilding.properties) : '')}
          onClose={() => setIsLightboxOpen(false)}
        />

        <ComparisonBoard
          open={comparisonOpen}
          onOpenChange={handleComparisonOpenChange}
          candidateFeatures={compareCandidateFeatures}
          compareIds={compareIds}
          onCompareIdsChange={handleCompareIdsChange}
          buildingCandidates={compareBuildingCandidates}
          compareBuildingIds={compareBuildingIds}
          onCompareBuildingIdsChange={handleCompareBuildingIdsChange}
          onSelectBuilding={handleSelectBuildingById}
          checkIn={filters.checkIn}
          checkOut={filters.checkOut}
          priceMode={filters.priceMode}
          onSelectFeature={handleSelectFeatureById}
        />
      </div>
    </TooltipProvider>
  );
};
