import { useCallback, useEffect, useState } from 'react';
import type { BuildingFeature, PropertyFeature, PropertyGeoJSON } from '../types.ts';
import type { ExplorerSearch, ExplorerSearchPatch } from '../lib/explorerSearch.ts';
import type { PatchExplorerSearchOptions } from './useExplorerSearch.ts';

interface UseSelectedFeatureOptions {
  search: ExplorerSearch;
  patchSearch: (patch: ExplorerSearchPatch, opts?: PatchExplorerSearchOptions) => void;
  /** フィルタ済み→全件の順に id 解決する(平面リストの ref) */
  resolveFeatureById: (id: number) => PropertyFeature | null;
  /** 建物 id → 建物 Feature(raw 正本から解決) */
  resolveBuildingById: (buildingId: number) => BuildingFeature | null;
  /** 部屋 id → 所属建物(buildRoomIndex 経由) */
  resolveBuildingByRoomId: (roomId: number) => BuildingFeature | null;
  /** 平面全件(データロード検知・建物再解決のトリガ) */
  rawGeojsonData: PropertyGeoJSON | null;
  filteredFeatures: PropertyFeature[];
  isMobile: boolean;
  /** 選択時に地図タブへ切り替える(モバイルのみ) */
  setMobileTab: (tab: 'map') => void;
}

/**
 * 選択状態と URL search param の双方向同期(Phase B2-γ で建物 2 層へ拡張)。
 *
 * - 部屋: `?id=`(従来どおり・共有 URL / AI selectProperty の互換)
 * - 建物: `?b=`(建物パネル)。?id= と併用可(部屋パネル最前面・閉じると建物パネルへ戻る)
 * - openFeature は建物が解決できるなら ?b= を同時 push(2 層導線を保つ)
 * - 建物パネルを開く/閉じる(openBuilding / closeBuilding)は URL へ反映
 *   (back で閉じる履歴を作る)
 * - URL id / b / データロード / back-forward から選択を復元
 * - フィルタ結果の更新に追従して stay_estimate 等を同期
 */
export function useSelectedFeature({
  search,
  patchSearch,
  resolveFeatureById,
  resolveBuildingById,
  resolveBuildingByRoomId,
  rawGeojsonData,
  filteredFeatures,
  isMobile,
  setMobileTab,
}: UseSelectedFeatureOptions): {
  selectedFeature: PropertyFeature | null;
  setSelectedFeature: React.Dispatch<React.SetStateAction<PropertyFeature | null>>;
  openFeature: (feature: PropertyFeature) => void;
  closeFeature: () => void;
  /** 建物パネル表示中の建物(?b= のみ。?id= 併用時は部屋パネルが最前面) */
  selectedBuilding: BuildingFeature | null;
  /** 建物ショートリストの楽観反映など selectedBuilding への部分パッチ用 */
  setSelectedBuilding: React.Dispatch<React.SetStateAction<BuildingFeature | null>>;
  openBuilding: (building: BuildingFeature) => void;
  closeBuilding: () => void;
} {
  const [selectedFeature, setSelectedFeature] = useState<PropertyFeature | null>(null);
  const [selectedBuilding, setSelectedBuilding] = useState<BuildingFeature | null>(null);

  // Keep selected feature's stay_estimate in sync with filtered list
  useEffect(() => {
    if (!selectedFeature) return;
    const id = selectedFeature.properties.id;
    const updated = filteredFeatures.find((f) => f.properties.id === id);
    if (updated && updated !== selectedFeature) {
      setSelectedFeature(updated);
    }
  }, [filteredFeatures]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── URL b → building (after data load / back-forward) ──
  useEffect(() => {
    if (search.b == null) {
      if (selectedBuilding) setSelectedBuilding(null);
      return;
    }
    if (selectedBuilding?.properties.id === search.b) return;
    const building = resolveBuildingById(search.b);
    if (building) {
      setSelectedBuilding(building);
      if (isMobile) setMobileTab('map');
    }
    // 建物データ未ロード時は次の rawGeojsonData 変更を待つ
  }, [search.b, rawGeojsonData, resolveBuildingById, isMobile]); // eslint-disable-line react-hooks/exhaustive-deps

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

  /** Open room — push history (back closes). 建物が解決できれば ?b= を同時付与 */
  const openFeature = useCallback(
    (feature: PropertyFeature) => {
      setSelectedFeature(feature);
      if (isMobile) setMobileTab('map');
      const roomId = feature.properties.id;
      const building = resolveBuildingByRoomId(roomId);
      const patch: ExplorerSearchPatch = { id: roomId };
      if (building && building.properties.id !== search.b) {
        patch.b = building.properties.id;
      }
      if (search.id !== roomId || patch.b !== undefined) {
        patchSearch(patch, { replace: false });
      }
    },
    [isMobile, patchSearch, search.id, search.b, setMobileTab, resolveBuildingByRoomId],
  );

  /** Close room — ?id= のみクリア(?b= が残っていれば建物パネルへ戻る) */
  const closeFeature = useCallback(() => {
    setSelectedFeature(null);
    if (search.id != null) {
      patchSearch({ id: null }, { replace: true });
    }
  }, [patchSearch, search.id]);

  /** Open building — push history。部屋パネルは閉じる(建物パネルが最前面) */
  const openBuilding = useCallback(
    (building: BuildingFeature) => {
      setSelectedBuilding(building);
      setSelectedFeature(null);
      if (isMobile) setMobileTab('map');
      if (search.b !== building.properties.id || search.id != null) {
        patchSearch({ b: building.properties.id, id: null }, { replace: false });
      }
    },
    [isMobile, patchSearch, search.b, search.id, setMobileTab],
  );

  /** Close building — ?b= ?id= ともクリア(両パネルを閉じる) */
  const closeBuilding = useCallback(() => {
    setSelectedBuilding(null);
    setSelectedFeature(null);
    if (search.b != null || search.id != null) {
      patchSearch({ b: null, id: null }, { replace: true });
    }
  }, [patchSearch, search.b, search.id]);

  return {
    selectedFeature,
    setSelectedFeature,
    openFeature,
    closeFeature,
    selectedBuilding,
    setSelectedBuilding,
    openBuilding,
    closeBuilding,
  };
}
