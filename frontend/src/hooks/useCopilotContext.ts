import { useAgentContext } from "@copilotkit/react-core/v2";
import { BoundsData, MapFilters, PropertyFeature } from "../types";
import { calcStayDays } from "../lib/rentCalculator";

interface MapState {
  center: [number, number] | null;
  zoom: number;
}

export function useCopilotMapContext(
  mapState: MapState,
  selectedFeature: PropertyFeature | null,
  filteredFeatures: PropertyFeature[],
  filters: MapFilters,
  mapBounds: BoundsData | null,
  excludedUnestimable = 0,
  /** All saved shortlist features (not limited to current filter) */
  savedFeatures: PropertyFeature[] = [],
) {
  useAgentContext({
    description:
      "現在のマップ表示範囲（中心緯度経度とズームレベル）。ユーザーがどのエリアを見ているかを示す。",
    value: {
      center: mapState.center ?? [35.6812, 139.7671],
      zoom: mapState.zoom,
      bounds: mapBounds
        ? {
            southWest: [...mapBounds.southWest],
            northEast: [...mapBounds.northEast],
          }
        : null,
    },
  });

  const selEst = selectedFeature?.properties.stay_estimate;
  useAgentContext({
    description: "ユーザーが現在選択している物件の情報。選択がない場合はnull。",
    value: selectedFeature
      ? {
          id: selectedFeature.properties.id,
          title: selectedFeature.properties.title,
          address: selectedFeature.properties.address,
          prefecture: selectedFeature.properties.prefecture_name ?? null,
          catalogMinPlanTotal: selectedFeature.properties.min_plan_total,
          stayTotalYen: selEst?.stayTotalYen ?? null,
          stayDays: selEst?.stayDays ?? null,
          layout: selectedFeature.properties.layout,
          area: selectedFeature.properties.area_m2,
          walkMinutes: selectedFeature.properties.min_walk_minutes,
          score: selectedFeature.properties.total_score,
          shortlistStatus: selectedFeature.properties.shortlist_status,
        }
      : null,
  });

  const stayDays = calcStayDays(filters.checkIn, filters.checkOut);
  const savedList =
    savedFeatures.length > 0
      ? savedFeatures
      : filteredFeatures.filter((f) => f.properties.shortlist_status === "saved");
  const savedIds = savedList.map((f) => f.properties.id);

  useAgentContext({
    description:
      "地図UIフィルター。applyFilters で変更する。" +
      "priceMode=stay では checkIn/checkOut 期間の試算総額で比較・maxPriceは期間総額上限（1000000=制限なし）。" +
      "priceMode=catalog ではカタログ最安（maxPrice 300000=制限なし）。" +
      "savedIds は現在のフィルタ結果に含まれる保存済み物件。比較時は showComparison に stayTotalYen を載せる。",
    value: {
      priceMode: filters.priceMode,
      checkIn: filters.checkIn,
      checkOut: filters.checkOut,
      stayDays,
      maxPrice: filters.maxPrice,
      areaRange: [...filters.areaRange],
      layout: filters.layout,
      status: filters.status,
      searchQuery: filters.searchQuery,
      boundsEnabled: filters.boundsEnabled,
      maxWalkMinutes: filters.maxWalkMinutes,
      minScore: filters.minScore,
      prefecture: filters.prefecture,
      requiredFeatures: [...filters.requiredFeatures],
      sortBy: filters.sortBy,
      filteredCount: filteredFeatures.length,
      excludedUnestimable,
      savedIds,
      savedCount: savedIds.length,
      visiblePropertyIds: filteredFeatures.slice(0, 15).map((f) => f.properties.id),
      topProperties: filteredFeatures.slice(0, 5).map((f) => ({
        id: f.properties.id,
        title: f.properties.title,
        score: f.properties.total_score,
        stayTotalYen: f.properties.stay_estimate?.stayTotalYen ?? null,
        catalogMinPlanTotal: f.properties.min_plan_total,
        catalogDailyYen: f.properties.min_daily_rent,
        layout: f.properties.layout,
        walk: f.properties.min_walk_minutes,
      })),
      savedProperties: savedList.slice(0, 10).map((f) => ({
        id: f.properties.id,
        title: f.properties.title,
        stayTotalYen: f.properties.stay_estimate?.stayTotalYen ?? null,
        catalogDailyYen: f.properties.min_daily_rent,
        score: f.properties.total_score,
        shortlistComment: f.properties.shortlist_comment ?? null,
      })),
    },
  });
}
