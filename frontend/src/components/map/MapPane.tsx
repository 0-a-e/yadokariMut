import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet.markercluster';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import { FaVectorSquare, FaDrawPolygon, FaXmark, FaEraser } from 'react-icons/fa6';
import { PropertyFeature, BoundsData } from '../../types.ts';
import { getScoreColor } from '../../lib/score.ts';
import { LayerEngine, PROPERTIES_PANE } from '../../lib/layers/engine.ts';
import type { LayerConfigState } from '../../lib/layers/types.ts';
import { MapLegendControl } from './MapLegendControl.tsx';
import { Button } from '@/components/ui/button.tsx';

/** Geoman は描画開始時に遅延ロード(初期バンドル影響ゼロ)。side-effect で L に pm が生える */
let geomanLoadPromise: Promise<unknown> | null = null;
function ensureGeoman(): Promise<unknown> {
  geomanLoadPromise ??= import('@geoman-io/leaflet-geoman-free');
  return geomanLoadPromise;
}

/** 囲みシェイプの表示色(accent) */
const SHAPE_COLOR = '#854dff';

type DrawTool = 'rect' | 'polygon';

interface MapPaneProps {
  filteredFeatures: PropertyFeature[];
  selectedId: number | null;
  /** サイドバーカードのホバー中物件(ホバーハイライト連動) */
  hoveredId: number | null;
  layerConfig: LayerConfigState;
  /** 物件ピンのクラスタリング(未指定=true=クラスタあり) */
  pinClustering: boolean;
  /** 確定済みの囲み範囲([lng, lat][], null=未描画) */
  drawnPolygon: [number, number][] | null;
  /** 囲み描画モード(App側マスタスイッチ。trueで描画開始を要求) */
  drawMode: boolean;
  onDrawModeChange: (active: boolean) => void;
  onShapeDrawn: (polygon: [number, number][]) => void;
  onShapeClear: () => void;
  onMarkerClick: (feature: PropertyFeature) => void;
  onMapMove?: (center: [number, number], zoom: number, bounds: BoundsData) => void;
  onMapInit?: (map: L.Map, cluster: any) => void;
  /** When false, container may be hidden; set true to trigger invalidateSize. */
  isVisible?: boolean;
}

export const MapPane: React.FC<MapPaneProps> = ({
  filteredFeatures, selectedId, hoveredId, layerConfig, pinClustering,
  drawnPolygon, drawMode, onDrawModeChange, onShapeDrawn, onShapeClear,
  onMarkerClick, onMapMove, onMapInit,
  isVisible = true,
}) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const clusterGroupRef = useRef<any>(null);
  const layerEngineRef = useRef<LayerEngine | null>(null);
  const markersRef = useRef<{ [key: number]: L.Marker }>({});
  const isFirstLoadRef = useRef(true);
  const isPanningToSelectedRef = useRef(false);
  const prevFeatureSignatureRef = useRef<string>('');
  /** 現行グループが markerClusterGroup かどうか(pinClustering トグルで作り直す) */
  const groupIsClusterRef = useRef<boolean>(pinClustering);
  /** 初期化effect内で最新propsを読むためのref */
  const pinClusteringRef = useRef(pinClustering);
  const onMapInitRef = useRef(onMapInit);
  useEffect(() => {
    pinClusteringRef.current = pinClustering;
  }, [pinClustering]);
  useEffect(() => {
    onMapInitRef.current = onMapInit;
  }, [onMapInit]);

  // ── 囲み描画(Geoman) ──
  const [uiTool, setUiTool] = useState<DrawTool | null>(null);
  const activeToolRef = useRef<DrawTool | null>(null);
  const geomanWiredRef = useRef(false);
  const shapeLayerRef = useRef<L.Polygon | null>(null);
  const prevShapeSigRef = useRef('');
  const lastToolRef = useRef<DrawTool>('rect');
  const onShapeDrawnRef = useRef(onShapeDrawn);
  const onShapeClearRef = useRef(onShapeClear);
  const onDrawModeChangeRef = useRef(onDrawModeChange);
  useEffect(() => { onShapeDrawnRef.current = onShapeDrawn; }, [onShapeDrawn]);
  useEffect(() => { onShapeClearRef.current = onShapeClear; }, [onShapeClear]);
  useEffect(() => { onDrawModeChangeRef.current = onDrawModeChange; }, [onDrawModeChange]);

  /** pm:create を一度だけ配線。確定時に頂点抽出して App へ(表示は drawnPolygon props の effect が担う) */
  const wireGeoman = (map: L.Map) => {
    if (geomanWiredRef.current) return;
    geomanWiredRef.current = true;
    map.on('pm:create', (e: any) => {
      const ring = (e.layer as L.Polygon).getLatLngs()[0] as L.LatLng[];
      const polygon: [number, number][] = ring.map((ll) => [ll.lng, ll.lat]);
      map.pm.disableDraw();
      (e.layer as L.Layer).remove();
      activeToolRef.current = null;
      setUiTool(null);
      onShapeDrawnRef.current(polygon);
    });
  };

  const startDraw = async (tool: DrawTool) => {
    const map = mapInstanceRef.current;
    if (!map) return;
    await ensureGeoman();
    if (mapInstanceRef.current !== map) return;
    // Geoman は addInitHook で pm を生やすため、マップ生成後に動的ロードすると
    // 既存インスタンスに pm が無い。initMap フック相当を手動で適用する
    const m = map as any;
    if (!m.pm) {
      m.pm = new (L as any).PM.Map(map);
      m.pm.setGlobalOptions({});
    }
    wireGeoman(map);
    if (activeToolRef.current) map.pm.disableDraw();
    map.pm.enableDraw(tool === 'rect' ? 'Rectangle' : 'Polygon', {
      allowSelfIntersection: false,
      finishOn: tool === 'polygon' ? 'dblclick' : null,
      templineStyle: { color: SHAPE_COLOR },
      hintlineStyle: { color: SHAPE_COLOR, dashArray: '5,5' },
    });
    activeToolRef.current = tool;
    lastToolRef.current = tool;
    setUiTool(tool);
    onDrawModeChangeRef.current(true);
  };

  const stopDraw = () => {
    const map = mapInstanceRef.current;
    if (map && activeToolRef.current) map.pm.disableDraw();
    activeToolRef.current = null;
    setUiTool(null);
  };

  // App側マスタスイッチ ⇄ 内部ツール状態の同期(Sidebarの「囲む」からの描画開始要求)
  useEffect(() => {
    if (drawMode && !activeToolRef.current) {
      void startDraw(lastToolRef.current);
    } else if (!drawMode && activeToolRef.current) {
      stopDraw();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawMode]);

  // 描画中はマーカーがクリックを奪う(leaflet-interactive が pointer-events:auto 持ち)ため
  // コンテナクラスで一括無効化する。ベクタフィーチャのクリックポップアップも
  // 頂点確定クリックと衝突するため描画中は無効化する
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    map.getContainer().classList.toggle('leaflet-draw-active', !!uiTool);
    layerEngineRef.current?.setFeatureClickEnabled(!uiTool);
  }, [uiTool]);

  // 確定済みシェイプの表示(drawnPolygon が単一の情報源)
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const sig = drawnPolygon ? JSON.stringify(drawnPolygon) : '';
    if (sig === prevShapeSigRef.current) return;
    prevShapeSigRef.current = sig;
    if (shapeLayerRef.current) {
      map.removeLayer(shapeLayerRef.current);
      shapeLayerRef.current = null;
    }
    if (drawnPolygon && drawnPolygon.length >= 3) {
      shapeLayerRef.current = L.polygon(
        drawnPolygon.map(([lng, lat]) => [lat, lng] as L.LatLngExpression),
        {
          pmIgnore: true,
          interactive: false,
          color: SHAPE_COLOR,
          weight: 2,
          opacity: 0.9,
          dashArray: '6 4',
          fillColor: SHAPE_COLOR,
          fillOpacity: 0.08,
        },
      ).addTo(map);
    }
  }, [drawnPolygon]);

  /**
   * ピングループを生成する。markercluster に実行時トグルAPIは無いため、
   * pinClustering 変化時はグループを作り直してマーカーを再投入する。
   * 無効時は L.featureGroup()(getBounds を持つため AIツール側の
   * mapPaneRef.cluster.getBounds() 呼び出しと互換)を使う。
   * 物件ピンはレイヤシステムの専用pane(最前面固定)に載る:
   * クラスタ円は clusterPane、個別マーカーは marker 生成時の pane 指定。
   * これによりレイヤパネルの物件行(表示/不透明度)が pane CSS 経由で効く
   */
  const buildPinGroup = (clustering: boolean): any => {
    if (!clustering) return L.featureGroup();
    return (L as any).markerClusterGroup({
      clusterPane: PROPERTIES_PANE,
      showCoverageOnHover: false,
      maxClusterRadius: 45,
      iconCreateFunction: (cluster: any) => {
        const childCount = cluster.getChildCount();
        let c = ' marker-cluster-';
        if (childCount < 10) c += 'small';
        else if (childCount < 100) c += 'medium';
        else c += 'large';
        return new L.DivIcon({ html: `<div><span>${childCount}</span></div>`, className: 'marker-cluster' + c, iconSize: new L.Point(40, 40) });
      },
    });
  };

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    const map = L.map(mapRef.current, { zoomControl: false, maxZoom: 20 }).setView([35.6812, 139.7671], 13);
    mapInstanceRef.current = map;
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Resizable panels / tab visibility changes need invalidateSize
    const ro = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
    });
    ro.observe(mapRef.current);
    // store for cleanup on unmount of this init effect
    (map as any)._resizeObserver = ro;

    layerEngineRef.current = new LayerEngine(map);

    // 物件ピンpaneを先行作成(cluster group が pane名を参照するため)。
    // zIndex/opacity/display は engine.syncProperties が制御する
    if (!map.getPane(PROPERTIES_PANE)) map.createPane(PROPERTIES_PANE);

    const pinGroup = buildPinGroup(pinClusteringRef.current);
    map.addLayer(pinGroup);
    clusterGroupRef.current = pinGroup;
    groupIsClusterRef.current = pinClusteringRef.current;

    if (onMapInit) {
      onMapInit(map, pinGroup);
    }

    return () => {
      try {
        ro.disconnect();
      } catch {
        /* ignore */
      }
      layerEngineRef.current?.destroy();
      layerEngineRef.current = null;
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    const t = window.setTimeout(() => {
      mapInstanceRef.current?.invalidateSize({ animate: false });
    }, 80);
    return () => window.clearTimeout(t);
  }, [isVisible]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !onMapMove) return;

    const handleMove = () => {
      if (isPanningToSelectedRef.current) return;
      const center = map.getCenter();
      const b = map.getBounds();
      const bounds: BoundsData = {
        southWest: [b.getSouthWest().lat, b.getSouthWest().lng],
        northEast: [b.getNorthEast().lat, b.getNorthEast().lng],
      };
      onMapMove([center.lat, center.lng], map.getZoom(), bounds);
    };

    map.on('moveend', handleMove);
    return () => { map.off('moveend', handleMove); };
  }, [onMapMove]);

  useEffect(() => {
    layerEngineRef.current?.sync(layerConfig);
    layerEngineRef.current?.syncProperties(layerConfig.properties);
  }, [layerConfig]);

  // pinClustering トグル: markercluster に実行時トグルAPIは無いため
  // グループを作り直し、markersRef の現行マーカーを新しいグループへ再投入する
  useEffect(() => {
    const map = mapInstanceRef.current;
    const prevGroup = clusterGroupRef.current;
    if (!map || !prevGroup) return;
    if (pinClustering === groupIsClusterRef.current) return;

    const nextGroup = buildPinGroup(pinClustering);
    map.removeLayer(prevGroup);
    map.addLayer(nextGroup);
    clusterGroupRef.current = nextGroup;
    groupIsClusterRef.current = pinClustering;

    const markers = Object.values(markersRef.current);
    if (pinClustering) {
      (nextGroup as any).addLayers(markers);
    } else {
      markers.forEach((m) => nextGroup.addLayer(m));
    }

    // App 側 mapPaneRef 経由の AIツールに現行グループを渡し続ける
    onMapInitRef.current?.(map, nextGroup);
  }, [pinClustering]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const cluster = clusterGroupRef.current;
    if (!map || !cluster) return;

    const signature = filteredFeatures.map(f => `${f.properties.id}-${f.properties.shortlist_status}`).join(',');
    if (signature === prevFeatureSignatureRef.current) {
      return;
    }
    prevFeatureSignatureRef.current = signature;

    cluster.clearLayers();
    markersRef.current = {};

    const markers: L.Marker[] = [];
    filteredFeatures.forEach((feat) => {
      const coords = feat.geometry?.coordinates;
      if (!coords || coords.length < 2) return;

      const latlng: L.LatLngExpression = [coords[1], coords[0]];
      const score = feat.properties.total_score || 0;
      const color = getScoreColor(score);
      const scoreRound = Math.round(score);

      const html = `
        <div class="custom-div-icon">
          <div class="marker-pin" style="background-color: ${color};" id="marker-pin-${feat.properties.id}"></div>
          <div class="marker-label">${scoreRound}</div>
        </div>`;

      const icon = L.divIcon({ html, iconSize: [32, 32], iconAnchor: [16, 32], className: '' });
      const marker = L.marker(latlng, { icon, pane: PROPERTIES_PANE }).on('click', () => onMarkerClick(feat));

      // Bind custom tooltip showing details and active campaigns
      // BE campaigns に is_active 列は無い(常時有効)。掲載中判定は日付で行う
      const activeCampaigns = feat.properties.campaigns ?? [];
      
      const campaignBadges = activeCampaigns.length > 0
        ? `<div class="mt-1 flex flex-wrap gap-1">
            ${activeCampaigns.map(c => `
              <span style="background-color: rgba(0, 230, 118, 0.12); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.3); border-radius: 4px; padding: 2px 4px; font-size: calc(9px * var(--font-scale)); font-weight: 700; display: inline-flex; align-items: center; gap: 2px; white-space: nowrap;">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" style="width:9px;height:9px;display:inline;fill:#00e676;margin-right:2px"><path d="M0 80V229.5c0 17 6.7 33.3 18.7 45.3L176 432c24.9 24.9 65.4 24.9 90.3 0L421.3 278.3c24.9-24.9 24.9-65.4 0-90.3L263.8 30.3C252.8 19.3 236.5 4.7 224 0H80C35.8 0 0 35.8 0 80zm112 48a32 32 0 1 1 0 64 32 32 0 1 1 0-64z"/></svg>${(c.title ?? '').length > 12 ? (c.title ?? '').substring(0, 12) + '...' : (c.title ?? '')}
              </span>
            `).join('')}
           </div>`
        : '';
        
      const tooltipContent = `
        <div style="padding: 6px; font-family: 'Outfit', 'Noto Sans JP', sans-serif;">
          <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #fff; margin-bottom: 2px;">${feat.properties.title}</div>
          <div style="font-size: calc(10px * var(--font-scale)); color: #8e95a5; margin-bottom: 4px;">
            ${feat.properties.layout} | ${feat.properties.area_m2 ? `${feat.properties.area_m2}㎡` : '広さ不明'} | ${feat.properties.min_walk_minutes ? `徒歩${feat.properties.min_walk_minutes}分` : '徒歩不明'}
          </div>
          <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #00f2fe;">
            ${
              feat.properties.stay_estimate?.ok &&
              feat.properties.stay_estimate.stayTotalYen != null
                ? `${feat.properties.stay_estimate.stayTotalYen.toLocaleString()}円（${feat.properties.stay_estimate.stayDays}日）`
                : feat.properties.min_daily_rent
                  ? `${feat.properties.min_daily_rent.toLocaleString()}円/日`
                  : '詳細参照'
            }
          </div>
          ${campaignBadges}
        </div>
      `;
      
      marker.bindTooltip(tooltipContent, {
        direction: 'top',
        offset: [0, -26],
        className: 'leaflet-custom-tooltip border border-border bg-panel backdrop-blur-glass shadow-lg rounded-lg text-text',
        sticky: false
      });

      markersRef.current[feat.properties.id] = marker;
      markers.push(marker);
    });

    // markerClusterGroup なら bulk addLayers、featureGroup なら個別 addLayer
    if (groupIsClusterRef.current && typeof (cluster as any).addLayers === 'function') {
      (cluster as any).addLayers(markers);
    } else {
      markers.forEach((m) => cluster.addLayer(m));
    }
    if (markers.length > 0 && isFirstLoadRef.current) {
      isFirstLoadRef.current = false;
      // クラスタ有無によらず全マーカーが収まる範囲へフィット
      const bounds = L.latLngBounds(markers.map((m) => m.getLatLng()));
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [filteredFeatures, onMarkerClick]);

  useEffect(() => {
    document.querySelectorAll('.marker-pin').forEach((el) => {
      const pin = el as HTMLElement;
      pin.classList.remove('active');
      pin.style.borderColor = '#fff';
    });

    if (selectedId === null) return;

    const pin = document.getElementById(`marker-pin-${selectedId}`);
    if (pin) {
      pin.classList.add('active');
      pin.style.borderColor = 'var(--accent)';
    }

    const marker = markersRef.current[selectedId];
    const cluster = clusterGroupRef.current;
    const map = mapInstanceRef.current;
    if (marker && typeof marker.getLatLng === 'function' && map) {
      const latlng = marker.getLatLng();
      if (latlng) {
        isPanningToSelectedRef.current = true;
        const onPanComplete = () => {
          setTimeout(() => {
            isPanningToSelectedRef.current = false;
          }, 300);
        };

        // zoomToShowLayer はクラスタ時のみ。無効時(featureGroup)は直接 panTo
        if (
          groupIsClusterRef.current &&
          cluster &&
          typeof (cluster as any).zoomToShowLayer === 'function' &&
          typeof cluster.hasLayer === 'function' &&
          cluster.hasLayer(marker) &&
          (marker as any).__parent
        ) {
          try {
            cluster.zoomToShowLayer(marker, () => {
              map.panTo(latlng);
              onPanComplete();
            });
          } catch {
            // マーカーがクラスター内にない場合などのフォールバック
            map.panTo(latlng);
            onPanComplete();
          }
        } else {
          map.panTo(latlng);
          onPanComplete();
        }
      }
    }
  }, [selectedId]);

  // ── サイドバーホバー連動ハイライト ──
  // ピンが見える状態なら .hovered で拡大、クラスタ内なら正確な位置に
  // ゴーストピンを一時描画し親クラスタにリングを付ける(カメラは動かさない)
  const hoverTimerRef = useRef<number | null>(null);
  const hoverPinElRef = useRef<HTMLElement | null>(null);
  const hoverZBoostRef = useRef<L.Marker | null>(null);
  const hoverGhostRef = useRef<L.Marker | null>(null);
  const hoverClusterElRef = useRef<HTMLElement | null>(null);
  const hoveredIdRef = useRef<number | null>(null);
  useEffect(() => {
    hoveredIdRef.current = hoveredId;
  }, [hoveredId]);

  /** ホバー演出の全消去(冪等) */
  const clearHoverFx = () => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    hoverPinElRef.current?.classList.remove('hovered');
    hoverPinElRef.current = null;
    hoverZBoostRef.current?.setZIndexOffset(0);
    hoverZBoostRef.current = null;
    if (hoverGhostRef.current) {
      mapInstanceRef.current?.removeLayer(hoverGhostRef.current);
      hoverGhostRef.current = null;
    }
    hoverClusterElRef.current?.classList.remove('marker-cluster--hover');
    hoverClusterElRef.current = null;
  };

  /** hoveredId の演出適用(markercluster再構築後も冪等に再適用できる) */
  const applyHoverFx = () => {
    const map = mapInstanceRef.current;
    const id = hoveredIdRef.current;
    const marker = id != null ? markersRef.current[id] : undefined;
    if (!map || !marker) return;
    // 物件レイヤ非表示中は演出しない(ゴーストピンはpane外に直接addするため
    // 非表示paneの制御が効かず、非表示を突き抜けて描画されてしまう)
    if (map.getPane(PROPERTIES_PANE)?.style.display === 'none') return;

    const pinEl = document.getElementById(`marker-pin-${id}`);
    if (pinEl) {
      pinEl.classList.add('hovered');
      hoverPinElRef.current = pinEl;
      marker.setZIndexOffset(1000);
      hoverZBoostRef.current = marker;
      return;
    }

    // クラスタ内(DOM不在): ゴーストピン+親クラスタのリング
    const ghost = L.marker(marker.getLatLng(), {
      icon: L.divIcon({
        html: '<div class="ghost-pin"></div>',
        className: '',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      }),
      interactive: false,
      keyboard: false,
      zIndexOffset: 1000,
    });
    ghost.addTo(map);
    hoverGhostRef.current = ghost;

    const cluster = clusterGroupRef.current;
    if (
      groupIsClusterRef.current &&
      cluster &&
      typeof (cluster as any).getVisibleParent === 'function'
    ) {
      const parent = (cluster as any).getVisibleParent(marker);
      if (parent && parent !== marker && (parent as any)._icon) {
        const el = (parent as any)._icon as HTMLElement;
        el.classList.add('marker-cluster--hover');
        hoverClusterElRef.current = el;
      }
    }
  };

  useEffect(() => {
    clearHoverFx();
    if (hoveredId === null) return;
    // 120ms遅延: リスト流し読み時の連切替で演出がちらつくのを防ぐ
    hoverTimerRef.current = window.setTimeout(() => {
      hoverTimerRef.current = null;
      applyHoverFx();
    }, 120);
    return () => clearHoverFx();
  }, [hoveredId, filteredFeatures, pinClustering]);

  // ホバー中のパン/ズームでピンのクラスタ内外が変わったら演出を張り直す
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const handleMoveEnd = () => {
      if (hoveredIdRef.current === null) return;
      clearHoverFx();
      window.setTimeout(applyHoverFx, 0);
    };
    map.on('moveend', handleMoveEnd);
    return () => {
      map.off('moveend', handleMoveEnd);
      clearHoverFx();
    };
  }, []);

  return (
    <div className="grow h-full w-full min-h-0 relative">
      <div id="map" ref={mapRef} className="absolute inset-0 h-full w-full" />
      {/* 地図上凡例(表示中レイヤの凡例を左下に列挙。凡例定義なしor非表示レイヤのみなら非表示) */}
      <MapLegendControl config={layerConfig} />
      {/* 囲み描画コントロール(右上はDetailPanelと衝突するため左上)。
          半透明+blurだと地図タイル次第で視認性が落ちるため、アプリ背景色の不透明リスト型にする
          (行間の境界線は置かず、外周の枠+影のみでクラスタ輪郭を確保) */}
      <div className="absolute left-3 top-3 z-[1200] flex flex-col min-w-[7.5rem] overflow-hidden rounded-lg border border-border bg-bg shadow-md">
        {uiTool ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-full justify-start gap-1.5 rounded-none px-3 text-xs"
            onClick={() => {
              stopDraw();
              onDrawModeChangeRef.current(false);
            }}
          >
            <FaXmark className="text-text-muted" />
            {uiTool === 'rect' ? '矩形' : 'なげなわ'}描画中 — キャンセル
          </Button>
        ) : (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-full justify-start gap-1.5 rounded-none px-3 text-xs"
              title="地図をドラッグして矩形で囲む"
              onClick={() => void startDraw('rect')}
            >
              <FaVectorSquare className="text-text-muted" />
              矩形
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-full justify-start gap-1.5 rounded-none px-3 text-xs"
              title="クリックで頂点を結び、囲んだ範囲で絞り込む"
              onClick={() => void startDraw('polygon')}
            >
              <FaDrawPolygon className="text-text-muted" />
              なげなわ
            </Button>
            {drawnPolygon && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-full justify-start gap-1.5 rounded-none px-3 text-xs text-[color-mix(in_oklab,var(--color-danger)_75%,white)] hover:text-danger"
                onClick={() => onShapeClearRef.current()}
              >
                <FaEraser />
                範囲を解除
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
};
