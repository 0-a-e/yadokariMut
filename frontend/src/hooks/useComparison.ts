import { useCallback, useMemo } from 'react';
import type {
  BuildingFeature,
  MapFilters,
  PropertyFeature,
  PropertyGeoJSON,
} from '../types.ts';
import type { ExplorerSearch, ExplorerSearchPatch } from '../lib/explorerSearch.ts';
import { EXPLORER_MAX_COMPARE, normalizeCompareIds } from '../lib/explorerSearch.ts';
import type { PatchExplorerSearchOptions } from './useExplorerSearch.ts';
import { withStayEstimate } from '../lib/filterLogic.ts';
import { savedCountOf } from '../lib/building.ts';

/** rawBuildings 未指定時の安定空配列(useMemo 依存の同一性維持用) */
const EMPTY_BUILDINGS: BuildingFeature[] = [];

interface UseComparisonOptions {
  rawGeojsonData: PropertyGeoJSON | null;
  filteredFeatures: PropertyFeature[];
  filters: MapFilters;
  search: ExplorerSearch;
  patchSearch: (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => void;
  /**
   * 建物比較候補の母集団(生建物 Feature 配列・Phase B2-δ §4.5)。
   * 部屋比較と対称に、現在のフィルタ外の建物も URL 明示 id で比較できるように
   * raw(全件)側から解決する。
   */
  rawBuildings?: BuildingFeature[];
}

/**
 * 比較モード(?view=compare&compare=…/bcompare=…)の状態導出。
 * 部屋比較: 候補はショートリスト(saved)と URL 明示の compare id を統合し、
 * 期間総額(stay_estimate)を付与して返す。
 * 建物比較(B2-δ): 候補は saved 部屋を持つ建物と URL 明示の bcompare id。
 */
export function useComparison({
  rawGeojsonData,
  filteredFeatures,
  filters,
  search,
  patchSearch,
  rawBuildings,
}: UseComparisonOptions): {
  savedFeatures: PropertyFeature[];
  compareIds: number[];
  comparisonOpen: boolean;
  compareCandidateFeatures: PropertyFeature[];
  handleCompareIdsChange: (ids: number[]) => void;
  handleComparisonOpenChange: (open: boolean) => void;
  handleOpenComparison: () => void;
  /** 建物比較(Phase B2-δ) */
  compareBuildingIds: number[];
  compareBuildingCandidates: BuildingFeature[];
  handleCompareBuildingIdsChange: (ids: number[]) => void;
} {
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

  // ── 建物比較(Phase B2-δ §4.5) ──

  const buildings = rawBuildings ?? EMPTY_BUILDINGS;
  const compareBuildingIds = search.bcompare ?? [];

  /**
   * Candidates: 建物saved OR saved 部屋を 1 つ以上持つ建物 + URL 明示 bcompare id
   * (建物ショートリスト承認 U4 — フィルタ「保存済み」の建物モード意味論と同一)。
   */
  const compareBuildingCandidates = useMemo(() => {
    const saved = buildings.filter(
      (b) =>
        b.properties.shortlist_status === 'saved' || savedCountOf(b.properties) > 0,
    );
    const byId = new Map<number, BuildingFeature>();
    for (const b of saved) {
      byId.set(b.properties.id, b);
    }
    for (const id of compareBuildingIds) {
      if (byId.has(id)) continue;
      const raw = buildings.find((f) => f.properties.id === id);
      if (raw) byId.set(id, raw);
    }
    // Order: compare ids first (for picker checked state), then remaining saved
    const ordered: BuildingFeature[] = [];
    const seen = new Set<number>();
    for (const id of compareBuildingIds) {
      const b = byId.get(id);
      if (b) {
        ordered.push(b);
        seen.add(id);
      }
    }
    for (const b of saved) {
      if (!seen.has(b.properties.id)) ordered.push(b);
    }
    return ordered;
  }, [buildings, compareBuildingIds]);

  const handleCompareBuildingIdsChange = useCallback(
    (ids: number[]) => {
      const next = normalizeCompareIds(ids).slice(0, EXPLORER_MAX_COMPARE);
      patchSearch({ bcompare: next.length ? next : null }, { replace: true });
    },
    [patchSearch],
  );

  return {
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
  };
}
