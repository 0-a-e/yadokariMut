import { useAgentContext } from "@copilotkit/react-core/v2";
import { BoundsData, MapFilters, PropertyFeature } from "../types.ts";
import { calcStayDays } from "../lib/rentCalculator.ts";
import type { LayerConfigState } from "../lib/layers/types.ts";
import { flattenStack } from "../lib/layers/state.ts";
import { catalogById } from "../lib/layers/catalog.ts";

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
  /** All saved shortlist features (not limited to current filter; may include unlisted ones) */
  savedFeatures: PropertyFeature[] = [],
  /** 現在の地図レイヤ構成（ベース/オーバーレイ/グループ） */
  layerConfig: LayerConfigState = {
    v: 2,
    stack: [],
    groups: [],
    properties: { id: "properties", visible: true, opacity: 1 },
  },
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
          // 生成型では BE 応答キーが null/欠損を許すため、コンテキスト用に null へ正規化する
          title: selectedFeature.properties.title ?? null,
          address: selectedFeature.properties.address ?? null,
          prefecture: selectedFeature.properties.prefecture_name ?? null,
          catalogMinPlanTotal: selectedFeature.properties.min_plan_total ?? null,
          stayTotalYen: selEst?.stayTotalYen ?? null,
          stayDays: selEst?.stayDays ?? null,
          layout: selectedFeature.properties.layout ?? null,
          area: selectedFeature.properties.area_m2 ?? null,
          walkMinutes: selectedFeature.properties.min_walk_minutes ?? null,
          score: selectedFeature.properties.total_score ?? null,
          shortlistStatus: selectedFeature.properties.shortlist_status,
          isActive: selectedFeature.properties.is_active !== false,
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
      "savedIds は現在のフィルタ結果に含まれる保存済み物件。isActive=false はサイト掲載終了（必ずユーザーに伝える）。" +
      "比較時は showComparison に stayTotalYen を載せる。",
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
      areaMode: filters.areaMode,
      drawnShape: filters.drawnPolygon != null,
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
        title: f.properties.title ?? null,
        score: f.properties.total_score ?? null,
        stayTotalYen: f.properties.stay_estimate?.stayTotalYen ?? null,
        catalogMinPlanTotal: f.properties.min_plan_total ?? null,
        catalogDailyYen: f.properties.min_daily_rent ?? null,
        layout: f.properties.layout ?? null,
        walk: f.properties.min_walk_minutes ?? null,
      })),
      savedProperties: savedList.slice(0, 10).map((f) => ({
        id: f.properties.id,
        title: f.properties.title ?? null,
        stayTotalYen: f.properties.stay_estimate?.stayTotalYen ?? null,
        catalogDailyYen: f.properties.min_daily_rent ?? null,
        score: f.properties.total_score ?? null,
        shortlistComment: f.properties.shortlist_comment ?? null,
        isActive: f.properties.is_active !== false,
      })),
    },
  });

  // ── 地図レイヤ構成 ──
  const flatLayers = flattenStack(layerConfig.stack);
  const baseLayer = flatLayers.find((l) => catalogById.get(l.id)?.role === "base");
  const overlays = flatLayers
    .filter((l) => catalogById.get(l.id)?.role !== "base")
    .map((l) => {
      const entry = catalogById.get(l.id);
      const groupName = l.groupId
        ? (layerConfig.groups.find((g) => g.id === l.groupId)?.name ?? null)
        : null;
      return (
        `${l.id}(${entry?.name ?? l.id}, 透明度${Math.round(l.opacity * 100)}%, ` +
        `${l.visible ? "表示" : "非表示"}${groupName ? `, ${groupName}` : ""})`
      );
    });
  const groupSummaries = layerConfig.groups.map(
    (g) =>
      `${g.name}(透明度${Math.round(g.opacity * 100)}%, ${g.visible ? "表示" : "非表示"})`,
  );

  useAgentContext({
    description:
      "現在の地図レイヤ構成。変更は addMapLayer / removeMapLayer / setMapLayerVisibility / " +
      "setMapLayerOpacity / setMapLayerOrder / setMapProvider を使う。" +
      "propertiesLayer は物件ピン(検索結果)レイヤ。最前面固定でスタック外のため " +
      "setMapLayerOrder の対象外(非表示でも物件データ自体は有効)。",
    value: {
      baseMap: baseLayer?.id ?? "なし",
      propertiesLayer: {
        visible: layerConfig.properties.visible !== false,
        opacity: layerConfig.properties.opacity,
      },
      activeOverlays: overlays,
      overlayCount: overlays.length,
      groups: groupSummaries,
    },
  });
}
