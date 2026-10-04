import { useCallback, useEffect, useState } from 'react';
import type { PropertyFeature, PropertyGeoJSON } from '../types.ts';
import type { ExplorerSearch, ExplorerSearchPatch } from '../lib/explorerSearch.ts';
import type { PatchExplorerSearchOptions } from './useExplorerSearch.ts';

interface UseSelectedFeatureOptions {
  search: ExplorerSearch;
  patchSearch: (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => void;
  /** フィルタ済み→全件の順に id 解決する(usePropertyData/useFilteredFeatures の ref 使用) */
  resolveFeatureById: (id: number) => PropertyFeature | null;
  rawGeojsonData: PropertyGeoJSON | null;
  filteredFeatures: PropertyFeature[];
  isMobile: boolean;
  /** 選択時に地図タブへ切り替える(モバイルのみ) */
  setMobileTab: (tab: 'map') => void;
}

/**
 * 選択中物件と URL search param(?id=)の双方向同期。
 *
 * - open/close で URL へ反映(back で閉じる履歴を作る)
 * - URL id / データロード / back-forward から選択を復元
 * - フィルタ結果の更新に追従して stay_estimate 等を同期
 */
export function useSelectedFeature({
  search,
  patchSearch,
  resolveFeatureById,
  rawGeojsonData,
  filteredFeatures,
  isMobile,
  setMobileTab,
}: UseSelectedFeatureOptions): {
  selectedFeature: PropertyFeature | null;
  setSelectedFeature: React.Dispatch<React.SetStateAction<PropertyFeature | null>>;
  openFeature: (feature: PropertyFeature) => void;
  closeFeature: () => void;
} {
  const [selectedFeature, setSelectedFeature] = useState<PropertyFeature | null>(null);

  // Keep selected feature's stay_estimate in sync with filtered list
  useEffect(() => {
    if (!selectedFeature) return;
    const id = selectedFeature.properties.id;
    const updated = filteredFeatures.find((f) => f.properties.id === id);
    if (updated && updated !== selectedFeature) {
      setSelectedFeature(updated);
    }
  }, [filteredFeatures]); // eslint-disable-line react-hooks/exhaustive-deps

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

  /** Open property — push history (back closes). */
  const openFeature = useCallback(
    (feature: PropertyFeature) => {
      setSelectedFeature(feature);
      if (isMobile) setMobileTab('map');
      if (search.id !== feature.properties.id) {
        patchSearch({ id: feature.properties.id }, { replace: false });
      }
    },
    [isMobile, patchSearch, search.id, setMobileTab],
  );

  const closeFeature = useCallback(() => {
    setSelectedFeature(null);
    if (search.id != null) {
      patchSearch({ id: null }, { replace: true });
    }
  }, [patchSearch, search.id]);

  return { selectedFeature, setSelectedFeature, openFeature, closeFeature };
}
