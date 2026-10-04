import { useCallback, useMemo } from 'react';
import type { MapFilters, PropertyFeature, PropertyGeoJSON } from '../types.ts';
import type { ExplorerSearch, ExplorerSearchPatch } from '../lib/explorerSearch.ts';
import { EXPLORER_MAX_COMPARE, normalizeCompareIds } from '../lib/explorerSearch.ts';
import type { PatchExplorerSearchOptions } from './useExplorerSearch.ts';
import { withStayEstimate } from '../lib/filterLogic.ts';

interface UseComparisonOptions {
  rawGeojsonData: PropertyGeoJSON | null;
  filteredFeatures: PropertyFeature[];
  filters: MapFilters;
  search: ExplorerSearch;
  patchSearch: (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => void;
}

/**
 * 比較モード(?view=compare&compare=…)の状態導出。
 * 候補はショートリスト(saved)と URL 明示の compare id を統合し、
 * 期間総額(stay_estimate)を付与して返す。
 */
export function useComparison({
  rawGeojsonData,
  filteredFeatures,
  filters,
  search,
  patchSearch,
}: UseComparisonOptions): {
  savedFeatures: PropertyFeature[];
  compareIds: number[];
  comparisonOpen: boolean;
  compareCandidateFeatures: PropertyFeature[];
  handleCompareIdsChange: (ids: number[]) => void;
  handleComparisonOpenChange: (open: boolean) => void;
  handleOpenComparison: () => void;
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

  return {
    savedFeatures,
    compareIds,
    comparisonOpen,
    compareCandidateFeatures,
    handleCompareIdsChange,
    handleComparisonOpenChange,
    handleOpenComparison,
  };
}
