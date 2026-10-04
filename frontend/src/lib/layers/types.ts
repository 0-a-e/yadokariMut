import type * as L from 'leaflet';

/** アダプタ種別。新データソースはここに追加して adapters/ に実装する */
export type AdapterKind = 'tile' | 'oshima' | 'maplibre';

/**
 * 固定タグ(国土地理院のレイヤ分類に基づく)。
 * 追加・変更は docs/map-layer-system-research.md §2.2 のタグ体系に合わせる。
 * realestate〜facility は今後のデータレイヤ(ベクタ基盤)向けの予約枠。
 */
export type LayerTag =
  | 'basemap'        // 基本地図
  | 'photo'          // 写真・衛星
  | 'terrain'        // 標高・起伏
  | 'landform'       // 土地条件
  | 'hazard'         // 災害
  | 'volcano'        // 火山
  | 'magnetic'       // 磁気
  | 'history'        // 歴史
  | 'landuse'        // 土地利用
  | 'safety'         // 防災・避難
  | 'realestate'     // 土地・不動産
  | 'urbanplanning'  // 都市計画
  | 'admin'          // 行政・地域
  | 'population'     // 統計・人口
  | 'transport'      // 交通
  | 'facility';      // 公共施設

export const LAYER_TAGS: ReadonlyArray<{ id: LayerTag; label: string }> = [
  { id: 'basemap', label: '基本地図' },
  { id: 'photo', label: '写真・衛星' },
  { id: 'terrain', label: '標高・起伏' },
  { id: 'landform', label: '土地条件' },
  { id: 'hazard', label: '災害' },
  { id: 'volcano', label: '火山' },
  { id: 'magnetic', label: '磁気' },
  { id: 'history', label: '歴史' },
  { id: 'landuse', label: '土地利用' },
  { id: 'safety', label: '防災・避難' },
  { id: 'realestate', label: '土地・不動産' },
  { id: 'urbanplanning', label: '都市計画' },
  { id: 'admin', label: '行政・地域' },
  { id: 'population', label: '統計・人口' },
  { id: 'transport', label: '交通' },
  { id: 'facility', label: '公共施設' },
];

/** タグ→ラベル。Record<LayerTag, string> 型が網羅性を保証する */
export const LAYER_TAG_LABELS: Record<LayerTag, string> = {
  basemap: '基本地図',
  photo: '写真・衛星',
  terrain: '標高・起伏',
  landform: '土地条件',
  hazard: '災害',
  volcano: '火山',
  magnetic: '磁気',
  history: '歴史',
  landuse: '土地利用',
  safety: '防災・避難',
  realestate: '土地・不動産',
  urbanplanning: '都市計画',
  admin: '行政・地域',
  population: '統計・人口',
  transport: '交通',
  facility: '公共施設',
};

/** maplibre アダプタ(VectorEngine)用のスタイル断片 */
export interface VectorLayerDef {
  sources: Record<
    string,
    {
      type: 'vector';
      tiles: string[];
      attribution?: string;
      minzoom?: number;
      maxzoom?: number;
    }
  >;
  /** MapLibre LayerSpecification 相当(緩い型でよい) */
  layers: unknown[];
  glyphs?: string;
  sprite?: string;
}

/** レイヤ設定モーダルに表示する設定項目の種類(拡張点) */
export type LayerSettingKind = 'defaultOpacity' | 'clustering';

/** カタログエントリ(コードに埋め込む静的定義) */
export interface LayerCatalogEntry {
  id: string;
  name: string;
  tags: LayerTag[];
  adapter: AdapterKind;
  attribution: string;
  /** tile アダプタ用 */
  urlTemplate?: string;
  minZoom?: number;
  /** タイルソースが実データを持つ最大ズーム。超えるズームは拡大表示 */
  maxNativeZoom?: number;
  maxZoom?: number;
  subdomains?: string;
  /** ベースマップ(上部切替タブと紐付く全画面不透明レイヤ) */
  role?: 'base';
  /** UI表示用の補足(凡例の注意書きなど) */
  note?: string;
  /** 出荷時デフォルト透明度(0-1)。省略時は1 */
  defaultOpacity?: number;
  /** 設定モーダルに表示する項目(defaultOpacityは全レイヤ共通で表示) */
  settings?: LayerSettingKind[];
  /** maplibre アダプタ用スタイル断片(adapter === 'maplibre' の場合必須) */
  vector?: VectorLayerDef;
  /** 凡例ポップオーバー用の説明文(description か legend のいずれかで表示) */
  description?: string;
  /** 凡例エントリ(色見本+ラベル) */
  legend?: { color: string; label: string }[];
}

/**
 * 実行時のレイヤ状態(v2)。ベースマップも通常のレイヤとして載る
 * (ベースらしさはカタログ側の role だけが知っている)。
 */
export interface LayerRuntime {
  id: string;
  visible: boolean;
  opacity: number;
}

/** スタックの要素: 単独レイヤ、またはアトミックなグループブロック(v2) */
export type StackItem =
  | ({ kind: 'layer' } & LayerRuntime)
  | { kind: 'group'; groupId: string; members: LayerRuntime[] };

export interface LayerGroup {
  id: string;
  name: string;
  visible: boolean;
  opacity: number;
  collapsed: boolean;
}

/**
 * レイヤ構成(v2スキーマ)。stack先頭=最前面(GIMP方式)。
 * グループはスタック内に1ブロックとして1回だけ現れ、メンバーを内包する。
 */
export interface LayerConfigState {
  v: 2;
  stack: StackItem[];
  groups: LayerGroup[];
}

/** 上部タブが束ねるベースマップ固定種(末尾の gsi_std_vector がベクタ版標準地図) */
export const BASE_LAYER_PRESETS = [
  'dark',
  'pale',
  'std',
  'satellite',
  'gsi_std_vector',
] as const;
export type BaseLayerId = (typeof BASE_LAYER_PRESETS)[number];

/** レイヤアダプタ。engine が呼ぶ抽象。paneName を持つ Leaflet レイヤを生成する */
export interface LayerAdapter {
  create(entry: LayerCatalogEntry, paneName: string): L.Layer;
}
