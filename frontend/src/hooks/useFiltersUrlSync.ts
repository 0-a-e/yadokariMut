import { useCallback, useEffect, useRef, useState } from 'react';
import type { MapFilters } from '../types.ts';
import type { ExplorerSearch, ExplorerSearchPatch } from '../lib/explorerSearch.ts';
import type { PatchExplorerSearchOptions } from './useExplorerSearch.ts';
import { createDefaultMapFilters, mergeMapFilters } from '../lib/filterLogic.ts';
import { loadStoredDateRange, saveStoredDateRange } from '../lib/stayDates.ts';

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

/**
 * フィルタ状態と TanStack Router search params の双方向同期。
 *
 * - URL → filters: back/forward・共有リンクの反映
 * - filters → URL: 期間 / priceMode の変更を search へ反映(自分の反映由来の
 *   変化は syncingFromUrlRef でエコーバック防止)
 * - 期間はシミュレータ・リロード用に localStorage へも保存
 */
export function useFiltersUrlSync(
  search: ExplorerSearch,
  patchSearch: (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => void,
): {
  filters: MapFilters;
  filtersRef: React.RefObject<MapFilters>;
  patchFilters: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  handleDatesChange: (checkIn: string, checkOut: string) => void;
} {
  const [filters, setFilters] = useState<MapFilters>(() => initialMapFilters(search));
  const filtersRef = useRef(filters);
  /** Skip echoing our own navigations when syncing URL → filters. */
  const syncingFromUrlRef = useRef(false);

  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

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

  return { filters, filtersRef, patchFilters, handleDatesChange };
}
