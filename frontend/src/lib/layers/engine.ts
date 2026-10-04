import L from 'leaflet';
import type { LayerConfigState } from './types.ts';
import { catalogById } from './catalog.ts';
import { getAdapter } from './adapters/index.ts';
import { VectorEngine, type VectorItem } from './vector.ts';

const LAYER_PANE_PREFIX = 'yl-';
const GROUP_PANE_PREFIX = 'yg-';
/**
 * カスタムpaneのスタック基準値。tilePane(200)より上、overlayPane(400)・
 * markerPane(600, 物件ピン)より下に収まる範囲で重ね順を振る。
 */
const BASE_Z_INDEX = 300;

/**
 * LayerConfigState(v2ネストスタック) → Leaflet地図への差分適用。
 * - レイヤごとに専用paneを割り当て、paneのzIndex/opacity/displayで
 *   順序・透明度・表示を制御する(アダプタ種別に依存しない統一方式)
 * - グループブロックは専用paneでメンバーを包み、グループ単位の透明度(CSS合成)と
 *   表示/非表示を実現する。ブロックのスタック位置がそのまま重ね順になる
 */
export class LayerEngine {
  private readonly map: L.Map;
  private readonly layerById = new Map<string, L.Layer>();
  private readonly groupPaneNames = new Set<string>();
  /** ベクタレイヤ(maplibre)の実体を担うエンジン(composition) */
  private readonly vectorEngine: VectorEngine;
  /** vector エントリ現在適用中の attribution(entryId → 文字列) */
  private readonly vectorAttributions = new Map<string, string>();

  constructor(map: L.Map) {
    this.map = map;
    this.vectorEngine = new VectorEngine(map);
  }

  sync(config: LayerConfigState): void {
    const map = this.map;
    const runtimeIds = new Set<string>();
    const activeGroupIds = new Set<string>();
    const total = config.stack.length;
    const seenPanes = new Set<string>();
    const vectorItems: VectorItem[] = [];

    const ensureLayer = (
      state: { id: string; visible: boolean; opacity: number },
      parentEl: HTMLElement,
      z: number,
    ) => {
      const entry = catalogById.get(state.id);
      if (!entry) return;
      if (entry.adapter === 'maplibre') return; // VectorEngine 側で処理(ここを通らない設計)
      runtimeIds.add(state.id);

      const paneName = LAYER_PANE_PREFIX + state.id;
      let pane = map.getPane(paneName);
      if (!pane) {
        pane = map.createPane(paneName, parentEl);
      } else if (pane.parentElement !== parentEl) {
        // グループ割当変更に追従してpaneを移動
        parentEl.appendChild(pane);
      }
      seenPanes.add(paneName);
      pane.style.zIndex = String(z);
      pane.style.opacity = String(state.opacity ?? 1);
      pane.style.display = state.visible === false ? 'none' : '';

      const adapter = getAdapter(entry.adapter);
      if (!adapter) return; // 未登録アダプタ(段階的マージ中)はpaneだけ確保してスキップ
      let layer = this.layerById.get(state.id);
      if (!layer) {
        layer = adapter.create(entry, paneName);
        this.layerById.set(state.id, layer);
        map.addLayer(layer);
      }
    };

    config.stack.forEach((item, index) => {
      const z = BASE_Z_INDEX + (total - index);
      if (item.kind === 'layer') {
        // ベクタレイヤは pane/L.Layer を作らず VectorEngine へ
        const entry = catalogById.get(item.id);
        if (entry?.adapter === 'maplibre') {
          runtimeIds.add(item.id);
          vectorItems.push({ entry, opacity: item.opacity, visible: item.visible, z });
          return;
        }
        const mapPane = map.getPane('mapPane')!;
        ensureLayer(item, mapPane, z);
        return;
      }

      // グループブロック: 専用pane + メンバーの相対順
      const group = config.groups.find((g) => g.id === item.groupId);
      const gpName = GROUP_PANE_PREFIX + item.groupId;
      let gPane = map.getPane(gpName);
      if (!gPane) {
        gPane = map.createPane(gpName);
        this.groupPaneNames.add(gpName);
      }
      seenPanes.add(gpName);
      gPane.style.zIndex = String(z);
      gPane.style.opacity = String(group?.opacity ?? 1);
      gPane.style.display = group?.visible === false ? 'none' : '';
      activeGroupIds.add(item.groupId);

      const mTotal = item.members.length;
      item.members.forEach((member, mIndex) => {
        // グループ内ベクタレイヤは pane CSS が効かないため、実効値を計算して渡す
        const entry = catalogById.get(member.id);
        if (entry?.adapter === 'maplibre') {
          runtimeIds.add(member.id);
          vectorItems.push({
            entry,
            opacity: member.opacity * (group?.opacity ?? 1),
            visible: member.visible && group?.visible !== false,
            z,
          });
          return;
        }
        ensureLayer(member, gPane, 100 + (mTotal - mIndex));
      });
    });

    this.syncVector(vectorItems);

    // 無効化されたレイヤの除去
    for (const [id, layer] of [...this.layerById]) {
      if (!runtimeIds.has(id)) {
        map.removeLayer(layer);
        this.layerById.delete(id);
        this.removePane(LAYER_PANE_PREFIX + id);
      }
    }
    // メンバーがいなくなったグループpaneの除去
    for (const gpName of [...this.groupPaneNames]) {
      if (!activeGroupIds.has(gpName.slice(GROUP_PANE_PREFIX.length))) {
        this.removePane(gpName);
        this.groupPaneNames.delete(gpName);
      }
    }
  }

  destroy(): void {
    for (const [, layer] of this.layerById) {
      this.map.removeLayer(layer);
    }
    this.layerById.clear();
    for (const gpName of [...this.groupPaneNames]) {
      this.removePane(gpName);
      this.groupPaneNames.delete(gpName);
    }
    for (const [, attribution] of this.vectorAttributions) {
      this.map.attributionControl?.removeAttribution(attribution);
    }
    this.vectorAttributions.clear();
    this.vectorEngine.destroy();
  }

  /**
   * ベクタレイヤ一群を VectorEngine へ反映し、attribution を管理する
   * (tileAdapter が L.tileLayer のオプションで行うのと同等の挙動)。
   */
  private syncVector(items: VectorItem[]): void {
    const activeIds = new Set(items.map((item) => item.entry.id));
    for (const [id, attribution] of [...this.vectorAttributions]) {
      if (!activeIds.has(id)) {
        this.map.attributionControl?.removeAttribution(attribution);
        this.vectorAttributions.delete(id);
      }
    }
    for (const item of items) {
      if (this.vectorAttributions.has(item.entry.id)) continue;
      this.map.attributionControl?.addAttribution(item.entry.attribution);
      this.vectorAttributions.set(item.entry.id, item.entry.attribution);
    }
    this.vectorEngine.sync(items);
  }

  private removePane(name: string): void {
    const pane = this.map.getPane(name);
    if (pane) pane.remove();
    delete (this.map as unknown as { _panes: Record<string, HTMLElement> })._panes[name];
  }
}
