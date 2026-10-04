import type { LayerAdapter } from '../types.ts';

/**
 * maplibre アダプタのプレースホルダ。
 *
 * adapter === 'maplibre' のエントリは LayerEngine が通常の pane/L.Layer
 * 生成をスキップし、VectorEngine(engine.ts の所有)へ引き渡すため、
 * この create が呼ばれることはない(呼ばれたら設計違反なので即失敗)。
 * アダプタ登録の網羅テスト(getAdapter で全 kind が取得できる)のために
 * registry へ登録だけ行う。
 */
export const maplibreAdapter: LayerAdapter = {
  create(): never {
    throw new Error('maplibre adapter は VectorEngine 経由でのみ動作します(直接 create は禁止)');
  },
};
