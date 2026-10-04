import L from 'leaflet';
import * as maplibregl from 'maplibre-gl';
import { Protocol } from 'pmtiles';
import maplibreGL from '@maplibre/maplibre-gl-leaflet';
import type { LayerCatalogEntry, VectorLayerDef } from './types.ts';

/**
 * maplibre-gl v6 はタイル取得を専用 Web Worker で行う。Worker の URL は
 * import.meta.url から導出されるが、Vite(dev/prebundle・build とも)は
 * maplibre-gl-worker.mjs をその位置へ出力しないため、`?worker&url` で
 * バンドル資産の URL を得て setWorkerUrl に渡す(公式移行ガイドと
 * protomaps/PMTiles#666 と同じ手法)。これを怠ると Worker が起動せず
 * ベクタタイルが一切読み込まれない(背景レイヤだけ描かれる)。
 */
import maplibreGlWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

/**
 * VectorEngine: Leaflet と MapLibre GL の橋渡し。
 *
 * - ベクタレイヤ(adapter === 'maplibre')が最初に必要になった時点で
 *   単一の maplibregl.Map を遅延生成する(未使用時はWebGLコストゼロ)
 * - @maplibre/maplibre-gl-leaflet プラグナが canvas を載せる専用pane `yl-gl`
 *   を使い、Leaflet のドラッグが GL canvas に飲み込まれないよう
 *   pointer-events: none を必須とする
 * - ベクタは1枚のcanvasでありラスタpane群の中間に挟めないため、
 *   スタック内の最下位ベクタ位置にブロック全体が来る
 *   (pane zIndex = 渡された items の最小 z - 1、ただし201未満にしない)
 */

/** VectorEngine.sync への入力。opacity/visible はグループ込みの実効値 */
export interface VectorItem {
  entry: LayerCatalogEntry;
  opacity: number;
  visible: boolean;
  z: number;
}

/** GL canvas を置くLeafletペイン */
const GL_PANE = 'yl-gl';
/** ペイン zIndex の下限(tilePane=200 の直上) */
const MIN_GL_Z_INDEX = 201;

/**
 * pmtiles:// プロトコルはプロセスで一度だけ登録する。
 * 注意: maplibre-gl v6 はタイル取得を Worker 内で行うため、この main-thread
 * 登録だけでは pmtiles:// タイルは取得できない(Worker 側登録には実験APIの
 * importScriptInWorkers が必要)。このため vendored スタイルのタイルURLは
 * 直接ZXY配信(.pbf)に書き換えてあり、pmtiles:// は実質予備。
 */
let pmtilesRegistered = false;
function ensurePmtilesProtocol(): void {
  if (pmtilesRegistered) return;
  maplibregl.addProtocol('pmtiles', new Protocol().tile);
  pmtilesRegistered = true;
}

/** setPaintProperty は name に厳格な共有union型を要求するため、緩い型で呼ぶ */
type SetPaintPropertyLoose = (layerId: string, name: string, value: number) => void;

/** レイヤ種別 → opacity を適用する paint プロパティ */
const OPACITY_PAINT_PROPS: Record<string, string[]> = {
  background: ['background-opacity'],
  fill: ['fill-opacity'],
  line: ['line-opacity'],
  symbol: ['icon-opacity', 'text-opacity'],
  circle: ['circle-opacity'],
  'fill-extrusion': ['fill-extrusion-opacity'],
  heatmap: ['heatmap-opacity'],
  raster: ['raster-opacity'],
};

/** MapLibre LayerSpecification の読み取りに必要な最小の形 */
interface StyleLayerLike {
  id: string;
  type: string;
  source?: string;
}

/** @maplibre/maplibre-gl-leaflet は pane オプションで配置先を指定できる */
type GlLayerOptions = L.LeafletMaplibreGLOptions & { pane?: string };

/** エントリ単位の適用状態(同一sync内の再適用を省くためのキャッシュ) */
interface EntryState {
  opacity: number;
  visible: boolean;
}

export class VectorEngine {
  private readonly map: L.Map;
  /** プラグナレイヤ(L.Leaflet) */
  private glLeafletLayer: L.MaplibreGL | null = null;
  private glMap: maplibregl.Map | null = null;
  /** 初期 style の load が済んだか(操作はこれ以降のみ) */
  private glReady = false;
  /** load 前に sync が来た場合の待機値 */
  private pendingItems: VectorItem[] | null = null;
  /** catalogId → GL上の layer id 一覧 */
  private readonly entryLayers = new Map<string, string[]>();
  /** catalogId → layer id と同順のレイヤ種別(addEntry時に確定) */
  private readonly entryLayerTypes = new Map<string, string[]>();
  /** catalogId → GL上の source id 一覧 */
  private readonly entrySources = new Map<string, string[]>();
  private readonly entryStates = new Map<string, EntryState>();
  private appliedGlyphs: string | undefined;
  private appliedSprite: string | undefined;
  private lastOrderSignature = '';

  constructor(map: L.Map) {
    this.map = map;
  }

  /**
   * ベクタレイヤ全体の状態を反映する。items 空なら全 source/layer を
   * 削除する(GLインスタンスとペインは保持し、再追加に備える)。
   */
  sync(items: VectorItem[]): void {
    if (!this.glLeafletLayer) {
      if (items.length === 0) return; // 未生成なら何もしない(WebGLコストゼロ)
      this.initGl();
    }
    if (!this.glReady) {
      this.pendingItems = items;
      return;
    }
    this.apply(items);
  }

  /** GLインスタンスとペインを破棄する(LayerEngine.destroy から呼ばれる) */
  destroy(): void {
    if (this.glLeafletLayer) {
      this.map.removeLayer(this.glLeafletLayer); // プラグナが glMap.remove() する
      this.glLeafletLayer = null;
    }
    this.glMap = null;
    this.glReady = false;
    this.pendingItems = null;
    this.entryLayers.clear();
    this.entryLayerTypes.clear();
    this.entrySources.clear();
    this.entryStates.clear();
    this.appliedGlyphs = undefined;
    this.appliedSprite = undefined;
    this.lastOrderSignature = '';
    const pane = this.map.getPane(GL_PANE);
    if (pane) {
      pane.remove();
      delete (this.map as unknown as { _panes: Record<string, HTMLElement> })._panes[GL_PANE];
    }
  }

  // ── 初期化 ─────────────────────────────────────────────────────

  private initGl(): void {
    ensurePmtilesProtocol();
    maplibregl.setWorkerUrl(maplibreGlWorkerUrl);
    let pane = this.map.getPane(GL_PANE);
    if (!pane) pane = this.map.createPane(GL_PANE);
    // GL canvas が Leaflet のドラッグを飲み込まないための必須設定
    pane.style.pointerEvents = 'none';
    pane.style.zIndex = String(MIN_GL_Z_INDEX);

    const options: GlLayerOptions = {
      interactive: false,
      attributionControl: false,
      style: { version: 8, sources: {}, layers: [] },
      pane: GL_PANE,
    };
    const layer = maplibreGL(options);
    this.glLeafletLayer = layer;
    this.map.addLayer(layer);
    this.glMap = layer.getMaplibreMap();
    this.glMap.once('load', () => {
      this.glReady = true;
      const pending = this.pendingItems;
      this.pendingItems = null;
      if (pending) this.apply(pending);
    });
  }

  // ── 差分適用 ───────────────────────────────────────────────────

  private apply(items: VectorItem[]): void {
    const glMap = this.glMap;
    if (!glMap || !this.glReady) return;
    const desired = new Map(items.map((item) => [item.entry.id, item]));

    // 1. 削除: なくなったエントリの layer/source を除去
    for (const [catalogId, layerIds] of [...this.entryLayers]) {
      if (desired.has(catalogId)) continue;
      for (const id of layerIds) {
        if (glMap.getLayer(id)) glMap.removeLayer(id);
      }
      this.entryLayers.delete(catalogId);
      this.entryLayerTypes.delete(catalogId);
      this.entryStates.delete(catalogId);
    }
    for (const [catalogId, sourceIds] of [...this.entrySources]) {
      if (desired.has(catalogId)) continue;
      for (const id of sourceIds) {
        if (glMap.getSource(id)) glMap.removeSource(id);
      }
      this.entrySources.delete(catalogId);
    }

    // 2. 追加: 新規エントリの source/layer を登録
    for (const item of items) {
      if (this.entryLayers.has(item.entry.id)) continue;
      this.addEntry(item.entry);
    }

    // 3. 状態: visibility / opacity(前回値と同じならスキップ)
    for (const item of items) {
      this.applyState(item);
    }

    // 4. 並び順: z 昇順(スタックの下位=奥 から)に moveLayer で最前面へ
    const ordered = [...items].sort((a, b) => a.z - b.z);
    const signature = ordered.map((i) => `${i.entry.id}:${i.z}`).join('|');
    if (signature !== this.lastOrderSignature) {
      for (const item of ordered) {
        for (const id of this.entryLayers.get(item.entry.id) ?? []) {
          glMap.moveLayer(id);
        }
      }
      this.lastOrderSignature = signature;
    }

    // 5. ペイン位置: 最下位ベクタの直下(tilePane より上)
    const pane = this.map.getPane(GL_PANE);
    if (pane && ordered.length > 0) {
      const minZ = Math.min(...ordered.map((i) => i.z));
      pane.style.zIndex = String(Math.max(MIN_GL_Z_INDEX, minZ - 1));
    }
  }

  /** エントリの source/layer を GL map へ追加(idは名前空間で分離) */
  private addEntry(entry: LayerCatalogEntry): void {
    const glMap = this.glMap;
    const def = entry.vector;
    if (!glMap || !def) return;

    this.applyAssets(def);

    const sourceIds: string[] = [];
    for (const [origId, source] of Object.entries(def.sources)) {
      const mappedId = `gl:${entry.id}:${origId}`;
      if (!glMap.getSource(mappedId)) {
        glMap.addSource(mappedId, {
          type: 'vector',
          tiles: source.tiles,
          attribution: source.attribution,
          minzoom: source.minzoom,
          maxzoom: source.maxzoom,
        });
      }
      sourceIds.push(mappedId);
    }
    this.entrySources.set(entry.id, sourceIds);

    const styleLayers = def.layers as StyleLayerLike[];
    const layerIds: string[] = [];
    const layerTypes: string[] = [];
    styleLayers.forEach((styleLayer, index) => {
      if (!styleLayer || typeof styleLayer.id !== 'string') return;
      const layerId = `gl:${entry.id}:${index}`;
      const clone: Record<string, unknown> = { ...styleLayer };
      clone.id = layerId;
      if (typeof styleLayer.source === 'string') {
        clone.source = `gl:${entry.id}:${styleLayer.source}`;
      }
      try {
        glMap.addLayer(clone as maplibregl.LayerSpecification);
        layerIds.push(layerId);
        layerTypes.push(styleLayer.type);
      } catch (err) {
        // 不正なスタイル定義が後続のmoveLayer等を壊さないよう分離して記録する
        console.error(`[vector] レイヤ追加失敗: ${entry.id}[${index}]`, err);
      }
    });
    this.entryLayers.set(entry.id, layerIds);
    this.entryLayerTypes.set(entry.id, layerTypes);
  }

  /** glyphs/sprite を GL map へ適用(競合時は警告して既存優先) */
  private applyAssets(def: VectorLayerDef): void {
    const glMap = this.glMap;
    if (!glMap) return;
    if (def.glyphs !== undefined) {
      if (this.appliedGlyphs === undefined) {
        glMap.setGlyphs(def.glyphs);
        this.appliedGlyphs = def.glyphs;
      } else if (this.appliedGlyphs !== def.glyphs) {
        console.warn(
          `[vector] glyphs の競合: 既存 ${this.appliedGlyphs} を優先します(無視: ${def.glyphs})`,
        );
      }
    }
    if (def.sprite !== undefined) {
      if (this.appliedSprite === undefined) {
        glMap.setSprite(def.sprite);
        this.appliedSprite = def.sprite;
      } else if (this.appliedSprite !== def.sprite) {
        console.warn(
          `[vector] sprite の競合: 既存 ${this.appliedSprite} を優先します(無視: ${def.sprite})`,
        );
      }
    }
  }

  /** 表示/不透明度を適用(同一状態の再適用はスキップ) */
  private applyState(item: VectorItem): void {
    const glMap = this.glMap;
    if (!glMap) return;
    const prev = this.entryStates.get(item.entry.id);
    if (prev && prev.opacity === item.opacity && prev.visible === item.visible) return;

    const layerIds = this.entryLayers.get(item.entry.id) ?? [];
    const layerTypes = this.entryLayerTypes.get(item.entry.id) ?? [];
    layerIds.forEach((layerId, index) => {
      if (!glMap.getLayer(layerId)) return;
      glMap.setLayoutProperty(layerId, 'visibility', item.visible ? 'visible' : 'none');
      const setPaint = glMap.setPaintProperty.bind(glMap) as SetPaintPropertyLoose;
      for (const prop of OPACITY_PAINT_PROPS[layerTypes[index]] ?? []) {
        setPaint(layerId, prop, item.opacity);
      }
    });
    this.entryStates.set(item.entry.id, { opacity: item.opacity, visible: item.visible });
  }
}
