import type { LayerCatalogEntry } from './layers/types.ts';
import type { components } from './api/schema';

type Schemas = components['schemas'];

/**
 * バックエンド保存のフロントエンド設定(GET/POST /api/fe-settings)の契約型。
 * 契約正本は生成 schema (BE FeSettingsResponse)。layers はレイヤ毎の上書き
 * 設定(未指定キーはカタログのデフォルトにフォールバック)、global は
 * アプリ全体の表示設定。保存値は「デフォルト」のみ。レイヤの実行時状態
 * (並び順・現在透明度)は localStorage(yadokari:layers)側に置く(設計 doc §2)。
 */
export type LayerSettingOverrides = Schemas['FeLayerOverrides'];

/** global は BE が既定値付きで必ず返す(未指定/null 無し)ため必須に固定する */
export type FeSettings = Omit<Schemas['FeSettingsResponse'], 'global'> & {
  global: NonNullable<Schemas['FeSettingsResponse']['global']>;
};

export const EMPTY_FE_SETTINGS: FeSettings = { layers: {}, global: {} };

/** レイヤ追加時に適用する透明度: サーバー保存値 → カタログ値 → 1 */
export function resolveInitialOpacity(
  feSettings: FeSettings | undefined,
  entry: LayerCatalogEntry | undefined,
): number {
  const saved = feSettings?.layers[entry?.id ?? '']?.defaultOpacity;
  if (typeof saved === 'number' && Number.isFinite(saved)) {
    return Math.min(1, Math.max(0, saved));
  }
  return entry?.defaultOpacity ?? 1;
}

/** 物件ピンのクラスタリング(既定=true=現行動作) */
export function resolvePinClustering(feSettings: FeSettings | undefined): boolean {
  return feSettings?.global.pinClustering !== false;
}

/**
 * 物件バルーン(ピンのtooltip)常時表示の保存値(既定=false=ホバー/クリック時のみ)。
 * 実効値はクラスタ表示中に個別マーカーが描画されないため MapPane 側で
 * 「この値 && !resolvePinClustering」に減じられる(常時表示トグルのdisabledも同条件)。
 */
export function resolvePinBalloonPermanent(feSettings: FeSettings | undefined): boolean {
  return feSettings?.global.pinBalloonPermanent === true;
}

/** 最下レイヤ(基本地図)下に見える地図コンテナ背景色(契約は BE FeGlobalSettings.mapBackground) */
export type MapBackground = NonNullable<
  Schemas['FeGlobalSettings']['mapBackground']
>;

/**
 * 地図コンテナ背景色の保存値(既定='black'=従来の #1a1a24)。
 * 'white' 選択時は MapPane がコンテナへ map-bg-light クラスを付与する。
 */
export function resolveMapBackground(feSettings: FeSettings | undefined): MapBackground {
  return feSettings?.global.mapBackground ?? 'black';
}
