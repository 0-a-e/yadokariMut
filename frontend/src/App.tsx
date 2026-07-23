import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import L from 'leaflet';
import {
  PropertyGeoJSON,
  PropertyFeature,
  BoundsData,
  MapFilters,
  ShortlistStatus,
} from './types';
import {
  collectPrefectures,
  collectSources,
  computeStayEstimate,
  createDefaultMapFilters,
  mergeMapFilters,
} from './lib/filterLogic';
import { loadStoredDateRange, saveStoredDateRange } from './lib/rentCalculator';
import {
  EXPLORER_MAX_COMPARE,
  normalizeCompareIds,
} from './lib/explorerSearch';
import { Sidebar } from './components/Sidebar';
import { MapPane } from './components/MapPane';
import { DetailPanel } from './components/DetailPanel';
import { ComparisonBoard } from './components/ComparisonBoard';
import { AdminModal } from './components/AdminModal';
import { LightboxModal } from './components/LightboxModal';
import { AgentChat } from './components/AgentChat';
import { useCopilotMapContext } from './hooks/useCopilotContext';
import { useMapActions } from './hooks/useMapActions';
import { useExplorerSearch } from './hooks/useExplorerSearch';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { FaListUl, FaMapLocationDot, FaCircle } from 'react-icons/fa6';
import { ACTIVE_THREAD_KEY, setActiveThreadId, upsertSessionMeta } from './lib/chatSessions';
import { createId } from './lib/utils';

/** Build initial filters: URL dates/mode > localStorage dates > defaults. */
function initialMapFilters(search: {
  checkIn?: string;
  checkOut?: string;
  priceMode?: 'stay' | 'catalog';
}): MapFilters {
  const base = createDefaultMapFilters();
  let checkIn = base.checkIn;
  let checkOut = base.checkOut;
  try {
    const stored = loadStoredDateRange();
    checkIn = stored.checkIn;
    checkOut = stored.checkOut;
  } catch {
    /* ignore */
  }
  if (search.checkIn && search.checkOut) {
    checkIn = search.checkIn;
    checkOut = search.checkOut;
  }
  const priceMode = search.priceMode ?? base.priceMode;
  return mergeMapFilters(base, { checkIn, checkOut, priceMode });
}

type MobileTab = 'list' | 'map' | 'chat';

function loadOrCreateThreadId(): string {
  try {
    const existing = localStorage.getItem(ACTIVE_THREAD_KEY);
    if (existing) return existing;
  } catch {
    /* ignore */
  }
  const id = createId();
  setActiveThreadId(id);
  upsertSessionMeta({
    id,
    title: '新しい会話',
    updatedAt: new Date().toISOString(),
    messageCount: 0,
  });
  return id;
}

function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false,
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const apply = () => setIsMobile(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [breakpoint]);
  return isMobile;
}

function withStayEstimate(
  f: PropertyFeature,
  filtered: PropertyFeature | undefined,
  checkIn: string,
  checkOut: string,
): PropertyFeature {
  if (filtered?.properties.stay_estimate) {
    return {
      ...f,
      properties: {
        ...f.properties,
        stay_estimate: filtered.properties.stay_estimate,
        shortlist_comment:
          f.properties.shortlist_comment ?? filtered.properties.shortlist_comment,
      },
    };
  }
  const est = computeStayEstimate(f.properties, checkIn, checkOut);
  return {
    ...f,
    properties: {
      ...f.properties,
      stay_estimate: est.ok ? est : f.properties.stay_estimate,
    },
  };
}

export const App: React.FC = () => {
  const isMobile = useIsMobile();
  const { search, patchSearch } = useExplorerSearch();

  const [rawGeojsonData, setRawGeojsonData] = useState<PropertyGeoJSON | null>(null);
  const [filteredFeatures, setFilteredFeatures] = useState<PropertyFeature[]>([]);
  const [selectedFeature, setSelectedFeature] = useState<PropertyFeature | null>(null);
  const [activeLayer, setActiveLayer] = useState<'dark' | 'pale' | 'satellite'>('pale');
  const [isAdminOpen, setIsAdminOpen] = useState(false);
  const [isLightboxOpen, setIsLightboxOpen] = useState(false);
  const [lightboxImages, setLightboxImages] = useState<string[]>([]);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [threadId, setThreadId] = useState<string>(() => loadOrCreateThreadId());
  const [mobileTab, setMobileTab] = useState<MobileTab>('map');

  const [filters, setFilters] = useState<MapFilters>(() => initialMapFilters(search));
  const [excludedUnestimable, setExcludedUnestimable] = useState(0);
  const [mapBounds, setMapBounds] = useState<BoundsData | null>(null);

  const [mapState, setMapState] = useState<{ center: [number, number] | null; zoom: number }>({
    center: null,
    zoom: 13,
  });

  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);
  const mapPaneRef = useRef<{ map: L.Map | null; cluster: any }>({ map: null, cluster: null });
  const rawGeojsonRef = useRef<PropertyGeoJSON | null>(null);
  const filtersRef = useRef(filters);
  const filteredFeaturesRef = useRef(filteredFeatures);
  /** Skip echoing our own navigations when syncing URL → filters. */
  const syncingFromUrlRef = useRef(false);

  useEffect(() => {
    rawGeojsonRef.current = rawGeojsonData;
  }, [rawGeojsonData]);
  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);
  useEffect(() => {
    filteredFeaturesRef.current = filteredFeatures;
  }, [filteredFeatures]);

  // ── URL → filters (back/forward + shared links) ──
  useEffect(() => {
    const patch: Partial<MapFilters> = {};
    if (search.checkIn && search.checkOut) {
      if (
        search.checkIn !== filtersRef.current.checkIn ||
        search.checkOut !== filtersRef.current.checkOut
      ) {
        patch.checkIn = search.checkIn;
        patch.checkOut = search.checkOut;
      }
    }
    if (search.priceMode && search.priceMode !== filtersRef.current.priceMode) {
      patch.priceMode = search.priceMode;
    }
    if (Object.keys(patch).length === 0) return;
    syncingFromUrlRef.current = true;
    setFilters((prev) => mergeMapFilters(prev, patch));
    queueMicrotask(() => {
      syncingFromUrlRef.current = false;
    });
  }, [search.checkIn, search.checkOut, search.priceMode]);

  // Persist stay dates for simulator / reloads without URL
  useEffect(() => {
    if (filters.checkIn && filters.checkOut) {
      saveStoredDateRange(filters.checkIn, filters.checkOut);
    }
  }, [filters.checkIn, filters.checkOut]);

  // Keep selected feature's stay_estimate in sync with filtered list
  useEffect(() => {
    if (!selectedFeature) return;
    const id = selectedFeature.properties.id;
    const updated = filteredFeatures.find((f) => f.properties.id === id);
    if (updated && updated !== selectedFeature) {
      setSelectedFeature(updated);
    }
  }, [filteredFeatures]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolveFeatureById = useCallback((id: number): PropertyFeature | null => {
    const filtered = filteredFeaturesRef.current.find((f) => f.properties.id === id);
    if (filtered) return filtered;
    return rawGeojsonRef.current?.features.find((f) => f.properties.id === id) ?? null;
  }, []);

  // ── URL id → selection (after data load / back-forward) ──
  useEffect(() => {
    if (search.id == null) {
      if (selectedFeature) setSelectedFeature(null);
      return;
    }
    if (selectedFeature?.properties.id === search.id) return;
    const feat = resolveFeatureById(search.id);
    if (feat) {
      setSelectedFeature(feat);
      if (isMobile) setMobileTab('map');
    }
    // If geojson not loaded yet, wait for next rawGeojsonData change
  }, [search.id, rawGeojsonData, filteredFeatures, resolveFeatureById, isMobile]); // eslint-disable-line react-hooks/exhaustive-deps

  const prefectureOptions = useMemo(
    () => collectPrefectures(rawGeojsonData),
    [rawGeojsonData],
  );

  const sourceOptions = useMemo(
    () => collectSources(rawGeojsonData),
    [rawGeojsonData],
  );

  const patchFilters = useCallback(
    (patch: Partial<MapFilters> & { reset?: boolean }) => {
      setFilters((prev) => {
        const next = mergeMapFilters(prev, patch);
        if (!syncingFromUrlRef.current) {
          const urlPatch: {
            checkIn?: string | null;
            checkOut?: string | null;
            priceMode?: 'stay' | 'catalog' | null;
          } = {};
          let touchUrl = false;
          if (
            patch.checkIn !== undefined ||
            patch.checkOut !== undefined ||
            patch.reset
          ) {
            urlPatch.checkIn = next.checkIn;
            urlPatch.checkOut = next.checkOut;
            touchUrl = true;
          }
          if (patch.priceMode !== undefined || patch.reset) {
            urlPatch.priceMode = next.priceMode;
            touchUrl = true;
          }
          if (touchUrl) {
            patchSearch(urlPatch, { replace: true });
          }
        }
        return next;
      });
    },
    [patchSearch],
  );

  const handleDatesChange = useCallback(
    (checkIn: string, checkOut: string) => {
      setFilters((prev) => mergeMapFilters(prev, { checkIn, checkOut }));
      patchSearch({ checkIn, checkOut }, { replace: true });
    },
    [patchSearch],
  );

  /** Open property — push history (back closes). */
  const openFeature = useCallback(
    (feature: PropertyFeature) => {
      setSelectedFeature(feature);
      if (isMobile) setMobileTab('map');
      if (search.id !== feature.properties.id) {
        patchSearch({ id: feature.properties.id }, { replace: false });
      }
    },
    [isMobile, patchSearch, search.id],
  );

  const closeFeature = useCallback(() => {
    setSelectedFeature(null);
    if (search.id != null) {
      patchSearch({ id: null }, { replace: true });
    }
  }, [patchSearch, search.id]);

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
    [],
  );

  const applyDetailPatch = useCallback(
    (
      propertyId: number,
      patch: {
        shortlist_comment?: string | null;
        shortlist_status?: ShortlistStatus;
        price_history?: PropertyFeature['properties']['price_history'];
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
    [],
  );

  const savedFeatures = useMemo(() => {
    if (!rawGeojsonData) return [];
    return rawGeojsonData.features
      .filter((f) => f.properties.shortlist_status === 'saved')
      .map((f) => {
        const filtered = filteredFeatures.find((x) => x.properties.id === f.properties.id);
        return withStayEstimate(f, filtered, filters.checkIn, filters.checkOut);
      });
  }, [rawGeojsonData, filteredFeatures, filters.checkIn, filters.checkOut]);

  const compareIds = search.compare ?? [];
  const comparisonOpen = search.view === 'compare';

  /** Candidates: saved + any explicit compare ids resolved from full dataset. */
  const compareCandidateFeatures = useMemo(() => {
    if (!rawGeojsonData) return savedFeatures;
    const byId = new Map<number, PropertyFeature>();
    for (const f of savedFeatures) {
      byId.set(f.properties.id, f);
    }
    for (const id of compareIds) {
      if (byId.has(id)) continue;
      const raw = rawGeojsonData.features.find((f) => f.properties.id === id);
      if (!raw) continue;
      const filtered = filteredFeatures.find((x) => x.properties.id === id);
      byId.set(id, withStayEstimate(raw, filtered, filters.checkIn, filters.checkOut));
    }
    // Order: compare ids first (for picker checked state), then remaining saved
    const ordered: PropertyFeature[] = [];
    const seen = new Set<number>();
    for (const id of compareIds) {
      const f = byId.get(id);
      if (f) {
        ordered.push(f);
        seen.add(id);
      }
    }
    for (const f of savedFeatures) {
      if (!seen.has(f.properties.id)) ordered.push(f);
    }
    return ordered;
  }, [
    rawGeojsonData,
    savedFeatures,
    compareIds,
    filteredFeatures,
    filters.checkIn,
    filters.checkOut,
  ]);

  const handleCompareIdsChange = useCallback(
    (ids: number[]) => {
      const next = normalizeCompareIds(ids).slice(0, EXPLORER_MAX_COMPARE);
      patchSearch({ compare: next.length ? next : null }, { replace: true });
    },
    [patchSearch],
  );

  const handleComparisonOpenChange = useCallback(
    (open: boolean) => {
      if (open) {
        // Seed compare from shortlist if URL has no explicit list
        let nextCompare = search.compare;
        if (!nextCompare?.length && savedFeatures.length > 0) {
          nextCompare = savedFeatures
            .slice(0, Math.min(EXPLORER_MAX_COMPARE, savedFeatures.length))
            .map((f) => f.properties.id);
        }
        patchSearch(
          {
            view: 'compare',
            ...(nextCompare?.length && !search.compare?.length
              ? { compare: nextCompare }
              : {}),
          },
          { replace: false },
        );
      } else {
        // Close panel only; keep compare ids for share links
        patchSearch({ view: null }, { replace: true });
      }
    },
    [patchSearch, search.compare, savedFeatures],
  );

  const handleOpenComparison = useCallback(() => {
    handleComparisonOpenChange(true);
  }, [handleComparisonOpenChange]);

  useCopilotMapContext(
    mapState,
    selectedFeature,
    filteredFeatures,
    filters,
    mapBounds,
    excludedUnestimable,
    savedFeatures,
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
    onLayerChange: setActiveLayer,
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

  const loadDefaultData = async () => {
    try {
      const res = await fetch('/api/geojson');
      if (res.ok) {
        const data = await res.json();
        setRawGeojsonData(data);
        return;
      }
    } catch (e) {
      console.warn('API geojson fetch failed, falling back to local file...');
    }
    try {
      const res = await fetch('/map.geojson');
      if (res.ok) {
        const data = await res.json();
        setRawGeojsonData(data);
      }
    } catch (e) {
      console.error('Could not load map.geojson', e);
    }
  };

  useEffect(() => {
    loadDefaultData();
  }, []);

  useEffect(() => {
    workerRef.current = new Worker(
      new URL('./workers/filter.worker.ts', import.meta.url),
      { type: 'module' },
    );
    workerRef.current.onmessage = (e) => {
      const { type, requestId, features, excludedUnestimable: excluded } = e.data;
      if (type === 'filterResult' && requestId === requestIdRef.current) {
        setFilteredFeatures(features);
        setExcludedUnestimable(typeof excluded === 'number' ? excluded : 0);
      }
    };
    return () => {
      workerRef.current?.terminate();
    };
  }, []);

  useEffect(() => {
    if (!workerRef.current) return;
    requestIdRef.current++;
    workerRef.current.postMessage({
      type: 'filter',
      requestId: requestIdRef.current,
      data: {
        rawGeojsonData,
        filters,
        mapBounds: filters.boundsEnabled ? mapBounds : null,
      },
    });
  }, [rawGeojsonData, filters, filters.boundsEnabled ? mapBounds : null]);

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
  const handleLightboxPrev = () => {
    if (lightboxImages.length === 0) return;
    setLightboxIndex((prev) => (prev - 1 + lightboxImages.length) % lightboxImages.length);
  };
  const handleLightboxNext = () => {
    if (lightboxImages.length === 0) return;
    setLightboxIndex((prev) => (prev + 1) % lightboxImages.length);
  };

  const handleCardClick = (feature: PropertyFeature) => {
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

  const sidebarNode = (
    <Sidebar
      filteredFeatures={filteredFeatures}
      selectedId={selectedFeature?.properties.id ?? null}
      activeLayer={activeLayer}
      onLayerChange={setActiveLayer}
      onAdminToggle={() => setIsAdminOpen(true)}
      filters={filters}
      onFiltersChange={patchFilters}
      prefectureOptions={prefectureOptions}
      sourceOptions={sourceOptions}
      onCardClick={handleCardClick}
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
        activeLayer={activeLayer}
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
                    { id: 'list' as const, label: 'リスト', icon: <FaListUl /> },
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
        />

        <LightboxModal
          isOpen={isLightboxOpen}
          images={lightboxImages}
          currentIndex={lightboxIndex}
          title={selectedFeature?.properties.title ?? ''}
          onClose={() => setIsLightboxOpen(false)}
          onPrev={handleLightboxPrev}
          onNext={handleLightboxNext}
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
