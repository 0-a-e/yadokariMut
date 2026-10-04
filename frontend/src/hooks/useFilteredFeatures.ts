import { useEffect, useRef, useState } from 'react';
import type { BoundsData, MapFilters, PropertyFeature, PropertyGeoJSON } from '../types.ts';

/**
 * フィルタ Worker のライフサイクル管理。
 * rawGeojsonData / filters / (viewport モードの) mapBounds の変更を
 * filter.worker.ts へ送り、計算結果のフィーチャー一覧を返す。
 */
export function useFilteredFeatures(
  rawGeojsonData: PropertyGeoJSON | null,
  filters: MapFilters,
  mapBounds: BoundsData | null,
): {
  filteredFeatures: PropertyFeature[];
  filteredFeaturesRef: React.MutableRefObject<PropertyFeature[]>;
  /** stay モードで総額を計算できず除外した件数 */
  excludedUnestimable: number;
} {
  const [filteredFeatures, setFilteredFeatures] = useState<PropertyFeature[]>([]);
  const [excludedUnestimable, setExcludedUnestimable] = useState(0);
  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);
  const filteredFeaturesRef = useRef(filteredFeatures);

  useEffect(() => {
    filteredFeaturesRef.current = filteredFeatures;
  }, [filteredFeatures]);

  useEffect(() => {
    workerRef.current = new Worker(new URL('../workers/filter.worker.ts', import.meta.url), {
      type: 'module',
    });
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
        mapBounds: filters.areaMode === 'viewport' ? mapBounds : null,
      },
    });
  }, [rawGeojsonData, filters, filters.areaMode === 'viewport' ? mapBounds : null]);

  return { filteredFeatures, filteredFeaturesRef, excludedUnestimable };
}
