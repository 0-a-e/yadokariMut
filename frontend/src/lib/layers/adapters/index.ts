import type { AdapterKind, LayerAdapter } from '../types.ts';
import { tileAdapter } from './tile.ts';
import { oshimaAdapter, setOshimaRuntimeOptions } from './oshima.ts';
import { maplibreAdapter } from './maplibre.ts';

const registry: Partial<Record<AdapterKind, LayerAdapter>> = {
  tile: tileAdapter,
  maplibre: maplibreAdapter,
};

registerAdapter('oshima', oshimaAdapter);

export function registerAdapter(kind: AdapterKind, adapter: LayerAdapter): void {
  registry[kind] = adapter;
}

export function getAdapter(kind: AdapterKind): LayerAdapter | undefined {
  return registry[kind];
}

/** アダプタ実行時オプション */
export interface OshimaAdapterOptions {
  /** 大島てるのクラスタ円を表示するか。false(既定)=個別マーカーのみ */
  clustering: boolean;
}

/**
 * アダプタの実行時オプションを差し替える。
 * 既定は { clustering: false }。呼び出し時に既に地図へ載っている
 * レイヤインスタンスへは再取得/再描画が即時通知される
 * (App.tsx の feSettings 反映effectから呼ぶ)。
 */
export function configureAdapter(
  kind: 'oshima',
  options: Partial<OshimaAdapterOptions>,
): void {
  if (kind !== 'oshima') return;
  setOshimaRuntimeOptions(options);
}
