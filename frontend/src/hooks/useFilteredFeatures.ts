import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  BoundsData,
  BuildingFeature,
  BuildingGeoJSON,
  MapFilters,
  PropertyFeature,
} from '../types.ts';
import { flattenMatchedUnits } from '../lib/filterLogic.ts';

/**
 * フィルタ Worker のライフサイクル管理(Phase B2-α で建物契約へ)。
 * rawBuildingData / filters / (viewport モードの) mapBounds の変更を
 * filter.worker.ts へ送り、採用建物一覧を返す。
 *
 * B2-β から地図(MapPane)/サイドバー(Sidebar)は filteredBuildings を直接消費する。
 * filteredFeatures(B2-α の平面互換出力)は部屋パネル(useSelectedFeature の
 * stay 同期)/ useComparison / useCopilotContext / useMapActions / AdminModal 等の
 * 部屋オブジェクト需要が残る間は維持する(γ〜δ で段階的に吸収予定)。
 */
export function useFilteredFeatures(
  rawBuildingData: BuildingGeoJSON | null,
  filters: MapFilters,
  mapBounds: BoundsData | null,
): {
  /** B2-α 互換: フィルタ通過部屋の平面リスト(ソート済み・部屋パネル/AI 用に維持) */
  filteredFeatures: PropertyFeature[];
  filteredFeaturesRef: React.RefObject<PropertyFeature[]>;
  /** 採用建物(建物代表値ソート済み・units に stay_estimate 付与済み) */
  filteredBuildings: BuildingFeature[];
  /** フィルタ条件を通過した部屋 id 集合(採用建物内) */
  matchedRoomIds: Set<number>;
  /** stay モードで総額を計算できず除外した unit 数(部屋数) */
  excludedUnestimable: number;
} {
  const [filteredBuildings, setFilteredBuildings] = useState<BuildingFeature[]>([]);
  const [matchedRoomIds, setMatchedRoomIds] = useState<Set<number>>(new Set());
  const [excludedUnestimable, setExcludedUnestimable] = useState(0);
  const workerRef = useRef<Worker | null>(null);
  const requestIdRef = useRef(0);

  const filteredFeatures = useMemo(
    () => flattenMatchedUnits(filteredBuildings, matchedRoomIds, filters.sortBy, filters),
    [filteredBuildings, matchedRoomIds, filters],
  );
  const filteredFeaturesRef = useRef(filteredFeatures);

  useEffect(() => {
    filteredFeaturesRef.current = filteredFeatures;
  }, [filteredFeatures]);

  useEffect(() => {
    workerRef.current = new Worker(new URL('../workers/filter.worker.ts', import.meta.url), {
      type: 'module',
    });
    workerRef.current.onmessage = (
      e: MessageEvent<{
        type: string;
        requestId: number;
        buildings: BuildingFeature[];
        matchedRoomIds: Set<number>;
        excludedUnestimable: number;
      }>,
    ) => {
      const { type, requestId, buildings, matchedRoomIds: matched, excludedUnestimable: excluded } =
        e.data;
      if (type === 'filterResult' && requestId === requestIdRef.current) {
        setFilteredBuildings(buildings);
        setMatchedRoomIds(matched ?? new Set());
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
        rawBuildingData,
        filters,
        mapBounds: filters.areaMode === 'viewport' ? mapBounds : null,
      },
    });
  }, [rawBuildingData, filters, filters.areaMode === 'viewport' ? mapBounds : null]);

  return {
    filteredFeatures,
    filteredFeaturesRef,
    filteredBuildings,
    matchedRoomIds,
    excludedUnestimable,
  };
}
