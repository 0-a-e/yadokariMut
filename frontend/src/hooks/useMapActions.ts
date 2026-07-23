import { useEffect, useRef } from "react";
import { useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod/v4";
import {
  BoundsData,
  MapFilters,
  PropertyFeature,
  PropertyGeoJSON,
  ShortlistStatus,
} from "../types";
import { applyMapFilters, mergeMapFilters } from "../lib/filterLogic";
import L from "leaflet";

interface UseMapActionsProps {
  mapPaneRef: React.MutableRefObject<{ map: L.Map | null; cluster: any }>;
  filteredFeatures: PropertyFeature[];
  rawGeojsonRef: React.MutableRefObject<PropertyGeoJSON | null>;
  filtersRef: React.MutableRefObject<MapFilters>;
  mapBounds: BoundsData | null;
  onSelectFeature: (feature: PropertyFeature) => void;
  onLayerChange: (layer: "dark" | "pale" | "satellite") => void;
  onPatchFilters: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  onShortlistLocal: (
    propertyId: number,
    status: ShortlistStatus,
    comment?: string | null,
  ) => void;
  resolveFeatureById: (id: number) => PropertyFeature | null;
}

const sortKeySchema = z.enum(["score", "price_asc", "price_desc", "area_desc"]);
const statusSchema = z.enum(["all", "saved", "unsaved", "hide", "reject"]);

export function useMapActions({
  mapPaneRef,
  filteredFeatures,
  rawGeojsonRef,
  filtersRef,
  mapBounds,
  onSelectFeature,
  onLayerChange,
  onPatchFilters,
  onShortlistLocal,
  resolveFeatureById,
}: UseMapActionsProps) {
  const filteredFeaturesRef = useRef(filteredFeatures);
  useEffect(() => {
    filteredFeaturesRef.current = filteredFeatures;
  }, [filteredFeatures]);

  const onSelectFeatureRef = useRef(onSelectFeature);
  useEffect(() => {
    onSelectFeatureRef.current = onSelectFeature;
  }, [onSelectFeature]);

  const onLayerChangeRef = useRef(onLayerChange);
  useEffect(() => {
    onLayerChangeRef.current = onLayerChange;
  }, [onLayerChange]);

  const onPatchFiltersRef = useRef(onPatchFilters);
  useEffect(() => {
    onPatchFiltersRef.current = onPatchFilters;
  }, [onPatchFilters]);

  const onShortlistLocalRef = useRef(onShortlistLocal);
  useEffect(() => {
    onShortlistLocalRef.current = onShortlistLocal;
  }, [onShortlistLocal]);

  const resolveFeatureByIdRef = useRef(resolveFeatureById);
  useEffect(() => {
    resolveFeatureByIdRef.current = resolveFeatureById;
  }, [resolveFeatureById]);

  const mapBoundsRef = useRef(mapBounds);
  useEffect(() => {
    mapBoundsRef.current = mapBounds;
  }, [mapBounds]);

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
        map.fitBounds(bounds, { padding: [50, 50] });
        return "Map fitted to filtered properties";
      }
      return "No properties to fit";
    },
  });

  useFrontendTool({
    name: "setMapProvider",
    description:
      "地図のレイヤープロバイダを切り替える。'dark' (ダークモード)、'pale' (標準/淡色)、'satellite' (航空写真)のいずれかを指定する。",
    parameters: z.object({
      provider: z
        .enum(["dark", "pale", "satellite"])
        .describe("切り替え先の地図プロバイダ名（'dark' | 'pale' | 'satellite'）"),
    }),
    handler: async ({ provider }) => {
      onLayerChangeRef.current(provider);
      return `Map provider switched to ${provider}`;
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
      "priceMode=stay（既定）: checkIn/checkOut の期間総額で比較。maxPrice は期間総額上限（1000000=制限なし）。" +
      "priceMode=catalog: カタログ最安。maxPrice は月額相当（300000=制限なし）。" +
      "日付は YYYY-MM-DD。万円は円に換算。fitMap=true で適用後に地図フィット。",
    parameters: z.object({
      reset: z.boolean().optional().describe("trueなら全フィルターを初期値に戻してから適用"),
      priceMode: z
        .enum(["stay", "catalog"])
        .optional()
        .describe("stay=期間総額比較 / catalog=カタログ価格"),
      checkIn: z.string().optional().describe("入居日 YYYY-MM-DD（stay で使用）"),
      checkOut: z.string().optional().describe("退去日 YYYY-MM-DD（stay で使用）"),
      maxPrice: z
        .number()
        .optional()
        .describe(
          "価格上限（円）。stay 時は期間総額（1000000=制限なし）、catalog 時は月額相当（300000=制限なし）",
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
        .describe("必須設備（feature_summary部分一致AND）。指定時は配列ごと置換"),
      sortBy: sortKeySchema.optional(),
      boundsEnabled: z.boolean().optional().describe("地図表示範囲で絞り込むか"),
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
        const cur = args.reset
          ? ([10, 50] as [number, number])
          : filtersRef.current.areaRange;
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
      if (args.boundsEnabled !== undefined) patch.boundsEnabled = args.boundsEnabled;

      const next = mergeMapFilters(filtersRef.current, patch);
      onPatchFiltersRef.current(patch);

      const bounds = next.boundsEnabled ? mapBoundsRef.current : null;
      const { features, excludedUnestimable } = applyMapFilters(
        rawGeojsonRef.current,
        next,
        bounds,
      );

      if (args.fitMap) {
        const map = mapPaneRef.current?.map;
        const cluster = mapPaneRef.current?.cluster;
        if (map && cluster) {
          setTimeout(() => {
            const b = cluster.getBounds();
            if (b.isValid()) map.fitBounds(b, { padding: [50, 50] });
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
      status: z.enum(["saved", "hide", "reject", "none"]),
      comment: z.string().optional(),
    }),
    handler: async ({ id, status, comment }) => {
      const feature = resolveFeatureByIdRef.current(id);
      try {
        const res = await fetch(`/api/properties/${id}/shortlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, comment: comment ?? null }),
        });
        if (!res.ok) {
          const text = await res.text();
          return `Failed to update shortlist: HTTP ${res.status} ${text}`;
        }
        onShortlistLocalRef.current(id, status, comment ?? null);
        const title = feature?.properties.title ?? `id=${id}`;
        return JSON.stringify({ ok: true, id, status, title, comment: comment ?? null });
      } catch (e) {
        return `Failed to update shortlist: ${e}`;
      }
    },
  });
}
