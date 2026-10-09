import { useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod/v4";
import type {
  BoundsData,
  BuildingGeoJSON,
  MapFilters,
  PropertyFeature,
  ShortlistStatus,
} from "../types.ts";
import {
  AREA_MODE_VALUES,
  CATALOG_PRICE_UNLIMITED,
  DEFAULT_AREA_RANGE,
  PRICE_MODE_VALUES,
  SHORTLIST_STATUS_FILTER_VALUES,
  SHORTLIST_STATUS_VALUES,
  SORT_KEY_VALUES,
  STAY_PRICE_UNLIMITED,
} from "../types.ts";
import {
  applyBuildingFilters,
  flattenMatchedUnits,
  mergeMapFilters,
} from "../lib/filterLogic.ts";
import { postBuildingShortlist } from "../lib/api/buildings.ts";
import { postShortlist } from "../lib/api/properties.ts";
import { FIT_BOUNDS_PADDING } from "../lib/mapDefaults.ts";
import type { LayerConfigState } from "../lib/layers/types.ts";
import { LAYER_TAGS } from "../lib/layers/types.ts";
import { catalogById, LAYER_CATALOG } from "../lib/layers/catalog.ts";
import type { LayerActions } from "../lib/layers/state.ts";
import { flattenOrderIds } from "../lib/layers/state.ts";
import { useLatestRef } from "./useLatestRef.ts";
import L from "leaflet";

interface UseMapActionsProps {
  mapPaneRef: React.RefObject<{ map: L.Map | null; cluster: any }>;
  filteredFeatures: PropertyFeature[];
  /**
   * 建物 Feature の生データ正本(B2-δ §4.6)。applyFilters の建物意味論再実行
   * (worker と同一の applyBuildingFilters)と selectBuilding の解決に使う。
   */
  rawBuildingData: BuildingGeoJSON | null;
  filtersRef: React.RefObject<MapFilters>;
  mapBounds: BoundsData | null;
  onSelectFeature: (feature: PropertyFeature) => void;
  /** 建物選択(建物パネル開設は App 側・B2-γ で BuildingPanel へ差し替え) */
  onSelectBuilding: (buildingId: number) => void;
  layerConfig: LayerConfigState;
  layerActions: LayerActions;
  onPatchFilters: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  onShortlistLocal: (
    propertyId: number,
    status: ShortlistStatus,
    comment?: string | null,
  ) => void;
  /** 建物ショートリストの楽観反映(App の applyBuildingShortlistLocal) */
  onBuildingShortlistLocal: (
    buildingId: number,
    status: 'saved' | 'none',
    comment?: string | null,
  ) => void;
  resolveFeatureById: (id: number) => PropertyFeature | null;
}

const sortKeySchema = z.enum(SORT_KEY_VALUES);
const statusSchema = z.enum(SHORTLIST_STATUS_FILTER_VALUES);

export function useMapActions({
  mapPaneRef,
  filteredFeatures,
  rawBuildingData,
  filtersRef,
  mapBounds,
  onSelectFeature,
  onSelectBuilding,
  layerConfig,
  layerActions,
  onPatchFilters,
  onShortlistLocal,
  onBuildingShortlistLocal,
  resolveFeatureById,
}: UseMapActionsProps) {
  const filteredFeaturesRef = useLatestRef(filteredFeatures);
  const rawBuildingDataRef = useLatestRef(rawBuildingData);
  const onSelectFeatureRef = useLatestRef(onSelectFeature);
  const onSelectBuildingRef = useLatestRef(onSelectBuilding);
  const layerConfigRef = useLatestRef(layerConfig);
  const layerActionsRef = useLatestRef(layerActions);
  const onPatchFiltersRef = useLatestRef(onPatchFilters);
  const onShortlistLocalRef = useLatestRef(onShortlistLocal);
  const onBuildingShortlistLocalRef = useLatestRef(onBuildingShortlistLocal);
  const resolveFeatureByIdRef = useLatestRef(resolveFeatureById);
  const mapBoundsRef = useLatestRef(mapBounds);

  useFrontendTool({
    name: "focusMap",
    description:
      "地図を指定された位置に移動し、ズームレベルを変更する。物件をユーザーに見せたい時に必ず呼び出すこと。",
    parameters: z.object({
      lat: z.number().describe("緯度（例: 35.6812）"),
      lng: z.number().describe("経度（例: 139.7671）"),
      zoom: z
        .number()
        .min(1)
        .max(20)
        .optional()
        .describe("ズームレベル（1-20、デフォルト15）"),
    }),
    handler: async ({ lat, lng, zoom }) => {
      const map = mapPaneRef.current?.map;
      if (!map) return "Map not initialized";
      map.flyTo([lat, lng], zoom ?? 15, { duration: 1.5 });
      return `Map focused to [${lat}, ${lng}] at zoom ${zoom ?? 15}`;
    },
  });

  useFrontendTool({
    name: "selectProperty",
    description:
      "指定されたIDの物件を選択状態にし、詳細パネルを表示する。フィルタ外でも raw データから選択可能。focusMapと組み合わせて使用すること。",
    parameters: z.object({
      id: z.number().describe("物件のID（properties.id）"),
    }),
    handler: async ({ id }) => {
      const feature = resolveFeatureByIdRef.current(id);
      if (!feature) {
        return `Property with id ${id} not found in loaded map data.`;
      }
      const inFiltered = filteredFeaturesRef.current.some(
        (f) => f.properties.id === id,
      );
      onSelectFeatureRef.current(feature);
      if (!inFiltered) {
        return `Property selected: ${feature.properties.title} (currently hidden by map filters; consider applyFilters to reveal it).`;
      }
      return `Property selected: ${feature.properties.title}`;
    },
  });

  useFrontendTool({
    name: "selectBuilding",
    description:
      "指定されたIDの建物を選択状態にし、建物の詳細を表示する。建物単位（topBuildings の id 等）でユーザーに見せたい時に使う。" +
      "部屋単位の選択は selectProperty を使う。focusMapと組み合わせて使用すること。",
    parameters: z.object({
      building_id: z.number().describe("建物のID（建物Featureのproperties.id・topBuildings の id）"),
    }),
    handler: async ({ building_id }) => {
      const building = rawBuildingDataRef.current?.features.find(
        (f) => f.properties.id === building_id,
      );
      if (!building) {
        return `Building with id ${building_id} not found in loaded map data.`;
      }
      onSelectBuildingRef.current(building_id);
      const name = building.properties.name ?? `id=${building_id}`;
      const rooms =
        building.properties.active_units_count ??
        building.properties.units_count ??
        building.properties.units.length;
      return `Building selected: ${name} (${rooms}部屋)`;
    },
  });

  useFrontendTool({
    name: "fitMapToFiltered",
    description:
      "現在フィルタリングされている全物件が収まるように、地図の表示範囲を自動調整する。",
    parameters: z.object({}),
    handler: async () => {
      const map = mapPaneRef.current?.map;
      const cluster = mapPaneRef.current?.cluster;
      if (!map || !cluster) return "Map not initialized";

      const bounds = cluster.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: FIT_BOUNDS_PADDING });
        return "Map fitted to filtered properties";
      }
      return "No properties to fit";
    },
  });

  useFrontendTool({
    name: "setMapProvider",
    description:
      "地図のレイヤープロバイダを切り替える。'dark' (ダークモード)、'pale' (淡色日本語)、'std' (標準地図)、'satellite' (衛星写真)のいずれかを指定する。",
    parameters: z.object({
      provider: z
        .enum(["dark", "pale", "std", "satellite"])
        .describe("切り替え先の地図プロバイダ名（'dark' | 'pale' | 'std' | 'satellite'）"),
    }),
    handler: async ({ provider }) => {
      layerActionsRef.current.selectBase(provider);
      return `Map provider switched to ${provider}`;
    },
  });

  /** カタログ全体をタグごとの1行に圧縮した一覧(LLMへのヒント用。「タグラベル: id=名前, …」) */
  const layerCatalogSummary = () =>
    LAYER_TAGS.map((tag) => {
      const entries = LAYER_CATALOG.filter((e) => e.tags[0] === tag.id);
      if (entries.length === 0) return null;
      return `${tag.label}: ${entries.map((e) => `${e.id}=${e.name}`).join(", ")}`;
    })
      .filter((line): line is string => line != null)
      .join("\n");

  const layerName = (id: string) => catalogById.get(id)?.name ?? id;

  useFrontendTool({
    name: "addMapLayer",
    description:
      "地図にレイヤを追加する（最前面に重ねる）。物件の災害リスク確認には flood_l2（洪水浸水想定）や dosekiryu（土石流警戒区域）等を重ねる。" +
      "主なid例: relief=色別標高図, slopemap=傾斜量図, hillshademap=陰影起伏図, flood_l2=洪水浸水想定(想定最大規模), " +
      "flood_l1=洪水浸水想定(計画規模), tsunami=津波浸水想定, dosekiryu=土石流警戒区域, jisuberi=地すべり警戒区域, " +
      "kyukeisha=急傾斜地崩壊警戒, afm=活断層図, oshima=大島てる事故物件, airphoto=空中写真, sekishoku=赤色立体地図。",
    parameters: z.object({
      layerId: z
        .string()
        .describe("追加するレイヤID（例: flood_l2, relief, oshima）"),
    }),
    handler: async ({ layerId }) => {
      const entry = catalogById.get(layerId);
      if (!entry) {
        return `レイヤ「${layerId}」はカタログに存在しません。利用可能レイヤ一覧(タグ: id=名前):\n${layerCatalogSummary()}`;
      }
      if (flattenOrderIds(layerConfigRef.current.stack).includes(layerId)) {
        return `レイヤ ${entry.name} (${layerId}) はすでに表示中です。`;
      }
      layerActionsRef.current.addLayer(layerId);
      return `${entry.name} を最前面に追加しました。`;
    },
  });

  useFrontendTool({
    name: "removeMapLayer",
    description:
      "地図からレイヤを削除する。災害レイヤで確認した後の片付けにも使う。",
    parameters: z.object({
      layerId: z.string().describe("削除するレイヤID"),
    }),
    handler: async ({ layerId }) => {
      const current = flattenOrderIds(layerConfigRef.current.stack);
      if (!current.includes(layerId)) {
        const ids = current.join(", ");
        return `レイヤ ${layerId} は現在有効ではありません。現在のレイヤ: ${ids || "なし"}`;
      }
      layerActionsRef.current.removeLayer(layerId);
      return `レイヤ ${layerName(layerId)} を削除しました。`;
    },
  });

  useFrontendTool({
    name: "setMapLayerVisibility",
    description:
      "追加済みレイヤの表示/非表示を切り替える（レイヤは削除されない）。",
    parameters: z.object({
      layerId: z.string().describe("対象レイヤID"),
      visible: z.boolean().describe("true=表示, false=非表示"),
    }),
    handler: async ({ layerId, visible }) => {
      if (!flattenOrderIds(layerConfigRef.current.stack).includes(layerId)) {
        return `レイヤ ${layerId} は現在有効ではありません。先に addMapLayer を呼び出してください。`;
      }
      layerActionsRef.current.setLayerVisible(layerId, visible);
      return `レイヤ ${layerName(layerId)} を${visible ? "表示" : "非表示"}にしました。`;
    },
  });

  useFrontendTool({
    name: "setMapLayerOpacity",
    description:
      "追加済みレイヤの不透明度を変更する（0=完全な透明 〜 1=完全な不透明）。下の地図を見せたい時に下げる。",
    parameters: z.object({
      layerId: z.string().describe("対象レイヤID"),
      opacity: z
        .number()
        .min(0)
        .max(1)
        .describe("不透明度 0-1（例: 0.5）"),
    }),
    handler: async ({ layerId, opacity }) => {
      if (!flattenOrderIds(layerConfigRef.current.stack).includes(layerId)) {
        return `レイヤ ${layerId} は現在有効ではありません。先に addMapLayer を呼び出してください。`;
      }
      layerActionsRef.current.setLayerOpacity(layerId, opacity);
      return `レイヤ ${layerName(layerId)} の不透明度を ${opacity} に変更しました。`;
    },
  });

  useFrontendTool({
    name: "setMapLayerOrder",
    description:
      "有効レイヤの重ね順を変更する。layerIds は現在有効な全レイヤIDを過不足なく並べ替えた配列（先頭=最前面）。" +
      "過不足があると無視されるため、全レイヤを必ず列挙すること。",
    parameters: z.object({
      layerIds: z
        .array(z.string())
        .describe("有効レイヤ全IDの並べ替え配列（先頭=最前面。例: ['flood_l2', 'pale']）"),
    }),
    handler: async ({ layerIds }) => {
      const current = flattenOrderIds(layerConfigRef.current.stack);
      const currentSet = new Set(current);
      const nextSet = new Set(layerIds);
      const isPermutation =
        layerIds.length === current.length &&
        layerIds.every((id) => currentSet.has(id)) &&
        nextSet.size === layerIds.length;
      if (!isPermutation) {
        return (
          `並べ替えは反映されませんでした。layerIds は現在有効な全レイヤ（${current.length}枚）を` +
          `過不足・重複なく指定する必要があります。現在の順序（先頭=最前面）: [${current.join(", ")}]`
        );
      }
      layerActionsRef.current.setLayerOrder(layerIds);
      return `レイヤの重ね順を変更しました（先頭=最前面）: [${layerIds.join(", ")}]`;
    },
  });

  useFrontendTool({
    name: "openOfficialSite",
    description:
      "指定された物件の公式サイトを新しいタブで開く。",
    parameters: z.object({
      id: z.number().describe("物件のID（properties.id）"),
    }),
    handler: async ({ id }) => {
      const feature = resolveFeatureByIdRef.current(id);
      if (!feature) return `Property with id ${id} not found.`;
      const url = feature.properties.detail_url;
      if (!url) return `Official site URL not available for property id ${id}.`;
      window.open(url, "_blank", "noopener,noreferrer");
      return `Opened official site for: ${feature.properties.title}`;
    },
  });

  useFrontendTool({
    name: "openGoogleEarth",
    description:
      "指定された物件の位置をGoogle Earthで新しいタブで開く。",
    parameters: z.object({
      id: z.number().describe("物件のID（properties.id）"),
    }),
    handler: async ({ id }) => {
      const feature = resolveFeatureByIdRef.current(id);
      if (!feature) return `Property with id ${id} not found.`;
      const coords = feature.geometry?.coordinates;
      if (!coords) return `Coordinates not available for property id ${id}.`;
      const earthUrl = `https://earth.google.com/web/search/${coords[1]},${coords[0]}`;
      window.open(earthUrl, "_blank", "noopener,noreferrer");
      return `Opened Google Earth for: ${feature.properties.title}`;
    },
  });

  useFrontendTool({
    name: "applyFilters",
    description:
      "地図UIのフィルターを部分更新する。ユーザーが期間・価格・地域などで絞る指示をしたら必ず使う。" +
      "省略フィールドは変更しない。reset=true で既定（期間総額モード）に戻してから適用。" +
      `priceMode=stay（既定）: checkIn/checkOut の期間総額で比較。maxPrice は期間総額上限（${STAY_PRICE_UNLIMITED}=制限なし）。` +
      `priceMode=catalog: カタログ最安。maxPrice は月額相当（${CATALOG_PRICE_UNLIMITED}=制限なし）。` +
      "日付は YYYY-MM-DD。万円は円に換算。fitMap=true で適用後に地図フィット。",
    parameters: z.object({
      reset: z.boolean().optional().describe("trueなら全フィルターを初期値に戻してから適用"),
      priceMode: z
        .enum(PRICE_MODE_VALUES)
        .optional()
        .describe("stay=期間総額比較 / catalog=カタログ価格"),
      checkIn: z.string().optional().describe("入居日 YYYY-MM-DD（stay で使用）"),
      checkOut: z.string().optional().describe("退去日 YYYY-MM-DD（stay で使用）"),
      maxPrice: z
        .number()
        .optional()
        .describe(
          `価格上限（円）。stay 時は期間総額（${STAY_PRICE_UNLIMITED}=制限なし）、catalog 時は月額相当（${CATALOG_PRICE_UNLIMITED}=制限なし）`,
        ),
      minArea: z.number().optional().describe("面積下限㎡"),
      maxArea: z.number().optional().describe("面積上限㎡"),
      layout: z.string().optional().describe("間取り。'all'|'1R'|'1K'|'1DK'|'1LDK' 等"),
      status: statusSchema.optional().describe("ショートリスト状態フィルタ"),
      searchQuery: z.string().optional().describe("フリーワード"),
      maxWalkMinutes: z
        .number()
        .nullable()
        .optional()
        .describe("徒歩分上限。nullで制限なし"),
      minScore: z.number().nullable().optional().describe("スコア下限。nullで制限なし"),
      prefecture: z
        .string()
        .nullable()
        .optional()
        .describe("都道府県名（例: 東京都）。nullで制限なし"),
      requiredFeatures: z
        .array(z.string())
        .optional()
        .describe(
          "必須設備（カテゴリcode集合への包含AND・code/ラベル/生値いずれも指定可）。指定時は配列ごと置換",
        ),
      sortBy: sortKeySchema.optional(),
      areaMode: z
        .enum(AREA_MODE_VALUES)
        .optional()
        .describe(
          "範囲絞り込み。all=全物件 / viewport=現在の地図表示範囲 / drawn=ユーザーが囲んだ範囲(未描画時はエラー)",
        ),
      fitMap: z.boolean().optional().describe("適用後にfitMapToFiltered相当を実行"),
    }),
    handler: async (args) => {
      const patch: Partial<MapFilters> & { reset?: boolean } = {};
      if (args.reset) patch.reset = true;
      if (args.priceMode !== undefined) patch.priceMode = args.priceMode;
      if (args.checkIn !== undefined) patch.checkIn = args.checkIn;
      if (args.checkOut !== undefined) patch.checkOut = args.checkOut;
      if (args.maxPrice !== undefined) patch.maxPrice = args.maxPrice;
      if (args.minArea !== undefined || args.maxArea !== undefined) {
        const cur = args.reset ? DEFAULT_AREA_RANGE : filtersRef.current.areaRange;
        patch.areaRange = [
          args.minArea !== undefined ? args.minArea : cur[0],
          args.maxArea !== undefined ? args.maxArea : cur[1],
        ];
      }
      if (args.layout !== undefined) patch.layout = args.layout;
      if (args.status !== undefined) patch.status = args.status;
      if (args.searchQuery !== undefined) patch.searchQuery = args.searchQuery;
      if (args.maxWalkMinutes !== undefined) patch.maxWalkMinutes = args.maxWalkMinutes;
      if (args.minScore !== undefined) patch.minScore = args.minScore;
      if (args.prefecture !== undefined) patch.prefecture = args.prefecture;
      if (args.requiredFeatures !== undefined) {
        patch.requiredFeatures = args.requiredFeatures;
      }
      if (args.sortBy !== undefined) patch.sortBy = args.sortBy;
      if (args.areaMode !== undefined) {
        if (args.areaMode === "drawn" && !filtersRef.current.drawnPolygon) {
          return JSON.stringify({
            ok: false,
            error:
              "囲まれた範囲が未描画のため drawn は指定できません。ユーザーに地図上で「矩形/なげなわ」で範囲を囲ってもらうか、viewport を使ってください。",
          });
        }
        patch.areaMode = args.areaMode;
      }

      const next = mergeMapFilters(filtersRef.current, patch);
      onPatchFiltersRef.current(patch);

      const bounds = next.areaMode === "viewport" ? mapBoundsRef.current : null;
      // B2-δ: 再実行も建物意味論(worker と同一の applyBuildingFilters)へ統一。
      // 応答形式は現行どおり部屋平面(features/件数)を維持する
      const { buildings, matchedRoomIds, excludedUnestimable } = applyBuildingFilters(
        rawBuildingDataRef.current,
        next,
        bounds,
      );
      const features = flattenMatchedUnits(buildings, matchedRoomIds, next.sortBy, next);

      if (args.fitMap) {
        const map = mapPaneRef.current?.map;
        const cluster = mapPaneRef.current?.cluster;
        if (map && cluster) {
          setTimeout(() => {
            const b = cluster.getBounds();
            if (b.isValid()) map.fitBounds(b, { padding: FIT_BOUNDS_PADDING });
          }, 400);
        }
      }

      return JSON.stringify({
        ok: true,
        applied: {
          priceMode: next.priceMode,
          checkIn: next.checkIn,
          checkOut: next.checkOut,
          maxPrice: next.maxPrice,
          sortBy: next.sortBy,
          prefecture: next.prefecture,
          layout: next.layout,
        },
        buildingCount: buildings.length,
        filteredCount: features.length,
        excludedUnestimable,
        sampleIds: features.slice(0, 5).map((f) => f.properties.id),
        sampleTitles: features.slice(0, 5).map((f) => f.properties.title),
        sampleStayTotals: features.slice(0, 5).map(
          (f) => f.properties.stay_estimate?.stayTotalYen ?? null,
        ),
      });
    },
  });

  useFrontendTool({
    name: "updateShortlist",
    description:
      "物件のショートリスト状態を更新する（saved/hide/reject/none）。UIとDBを同期するため、ユーザーが保存・見送り等を指示したらMCPのupdate_shortlistではなく必ずこのツールを使う。",
    parameters: z.object({
      id: z.number().describe("物件ID"),
      status: z.enum(SHORTLIST_STATUS_VALUES),
      comment: z.string().optional(),
    }),
    handler: async ({ id, status, comment }) => {
      const feature = resolveFeatureByIdRef.current(id);
      try {
        await postShortlist(id, status, comment ?? null);
        onShortlistLocalRef.current(id, status, comment ?? null);
        const title = feature?.properties.title ?? `id=${id}`;
        return JSON.stringify({ ok: true, id, status, title, comment: comment ?? null });
      } catch (e) {
        return `Failed to update shortlist: ${e}`;
      }
    },
  });

  useFrontendTool({
    name: "updateBuildingShortlist",
    description:
      "建物のブックマーク(ショートリスト)状態を更新する(saved/none のみ)。UIとDBを同期するため、ユーザーが建物の保存等を指示したらMCPのupdate_building_shortlistではなく必ずこのツールを使う。建物IDは search_properties 応答の建物 id。",
    parameters: z.object({
      buildingId: z.number().describe("建物ID(buildings.id)"),
      status: z.enum(["saved", "none"]),
      comment: z.string().optional(),
    }),
    handler: async ({ buildingId, status, comment }) => {
      try {
        await postBuildingShortlist(buildingId, status, comment ?? null);
        onBuildingShortlistLocalRef.current(buildingId, status, comment ?? null);
        const b = rawBuildingDataRef.current?.features.find(
          (f) => f.properties.id === buildingId,
        );
        const name = b?.properties.name ?? `building_id=${buildingId}`;
        return JSON.stringify({ ok: true, buildingId, status, name, comment: comment ?? null });
      } catch (e) {
        return `Failed to update building shortlist: ${e}`;
      }
    },
  });
}
