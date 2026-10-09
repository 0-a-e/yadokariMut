import { LAYER_TAGS } from './types.ts';
import type {
  FeaturePopupDef,
  LayerCatalogEntry,
  LayerTag,
  LegendEntry,
  LegendShape,
  VectorLayerDef,
} from './types.ts';
import gsiStdVectorStyle from './styles/gsi_std_vector.json';
import gsiContoursStyle from './styles/gsi_contours.json';

/** ベンダリングしたGSIスタイル断片(scripts/vendor-gsi-style.mjs 生成)を VectorLayerDef へ */
function toVectorDef(style: {
  sources: Record<string, unknown>;
  layers: unknown[];
  glyphs?: string;
  sprite?: string;
}): VectorLayerDef {
  return {
    sources: style.sources as VectorLayerDef['sources'],
    layers: style.layers,
    glyphs: style.glyphs,
    sprite: style.sprite,
  };
}

/**
 * 凡例定義ヘルパー(見本の形状をレイヤ単位で一括指定)。
 * shape はジオメトリ種に合わせる(circle=ポイント, line=ライン, square=面)。
 * レイヤ名ポップオーバーと地図上凡例コントロール(MapLegendControl)の両方が参照する。
 */
function legendOf(
  shape: LegendShape,
  items: ReadonlyArray<[color: string, label: string]>,
): LegendEntry[] {
  return items.map(([color, label]) => ({ color, label, shape }));
}

/**
 * 国土数値情報(MLIT NLFTP)レイヤのカタログエントリを組み立てる。
 * scripts/ksj パイプラインで生成した PMTiles を /api/tiles/{code}/{z}/{x}/{y}.pbf
 * で配信(ZXY直参照)する maplibre エントリの定型(単一source・minzoom 4)を集約。
 * MapLibre layers・凡例・ポップアップはエントリごとの差分として渡す。
 */
function ksjEntry(options: {
  /** KSJデータセットコード(n03等)。id・source key・tiles URL に使う */
  code: string;
  /** データセット名(行政区域等)。name・attribution に使う */
  title: string;
  /** データの年度(name の「国土数値情報 {year}」) */
  year: number;
  /** タイルソースの maxzoom */
  maxzoom: number;
  defaultOpacity: number;
  /** 生成日(note)。省略時は '2026-09-16' */
  generated?: string;
  tags: LayerTag[];
  description: string;
  /** MapLibre layers 定義(エントリごとの差分。内容は変更しない) */
  layers: unknown[];
  legend?: LegendEntry[];
  featurePopup?: FeaturePopupDef;
}): LayerCatalogEntry {
  const {
    code,
    title,
    year,
    maxzoom,
    defaultOpacity,
    generated = '2026-09-16',
    tags,
    description,
    layers,
    legend,
    featurePopup,
  } = options;
  return {
    id: `ksj_${code}`,
    name: `${title} (国土数値情報 ${year})`,
    tags,
    adapter: 'maplibre',
    attribution: `出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(${title})</a>`,
    vector: {
      sources: {
        [code]: {
          type: 'vector',
          tiles: [`/api/tiles/${code}/{z}/{x}/{y}.pbf`],
          minzoom: 4,
          maxzoom,
        },
      },
      layers,
    },
    description,
    note: `生成: ${generated} (scripts/ksj)`,
    defaultOpacity,
    ...(legend !== undefined && { legend }),
    ...(featurePopup !== undefined && { featurePopup }),
  };
}

/**
 * レイヤカタログ。ズーム値は地理院地図の公式レイヤ定義
 * (refs/gsi-layers/gsi_layers*.txt, gsi_hazard.txt)の実値に準拠。
 * maxZoom は一律 20 とし、実解像度は maxNativeZoom で表現する
 * (公式より広いズームでは拡大表示 = 設計doc §4.3 の方針)。
 */
const GSI = 'https://cyberjapandata.gsi.go.jp/xyz';
const HAZARD = 'https://disaportaldata.gsi.go.jp/raster';
const GSI_ATTR =
  '出典: <a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">国土地理院</a>';
const HAZARD_ATTR =
  '出典: <a href="https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/copyright/opendata.html" target="_blank" rel="noopener">国土数値情報(ハザードマップポータル)</a>';
const OSHIMA_ATTR =
  '出典: <a href="https://www.oshimaland.co.jp/" target="_blank" rel="noopener">大島てる</a>';

/**
 * 地理院タイル(ラスタ)のカタログエントリを組み立てる。
 * maxZoom は一律 20(公式画像の拡大表示)、urlPath は省略時 id
 * (地理院レイヤの大半は id と同名パス)。HAZARD ポータル群は hazardTile から使う。
 */
function gsiTile(options: {
  id: string;
  name: string;
  tags: LayerTag[];
  /** タイルURLパス。省略時は id */
  urlPath?: string;
  /** タイル拡張子。省略時 'png' */
  ext?: 'png' | 'jpg';
  minZoom?: number;
  maxNativeZoom: number;
  defaultOpacity?: number;
  note?: string;
  /** ベースマップは 'base' */
  role?: 'base';
  /** 省略時 GSI_ATTR(別出典は上書き) */
  attribution?: string;
  /** 省略時 GSI(別ホストは上書き) */
  baseUrl?: string;
}): LayerCatalogEntry {
  const {
    id,
    name,
    tags,
    urlPath = id,
    ext = 'png',
    minZoom,
    maxNativeZoom,
    defaultOpacity,
    note,
    role,
    attribution = GSI_ATTR,
    baseUrl = GSI,
  } = options;
  return {
    id,
    name,
    tags,
    ...(role !== undefined && { role }),
    adapter: 'tile',
    attribution,
    urlTemplate: `${baseUrl}/${urlPath}/{z}/{x}/{y}.${ext}`,
    ...(minZoom !== undefined && { minZoom }),
    maxNativeZoom,
    maxZoom: 20,
    ...(defaultOpacity !== undefined && { defaultOpacity }),
    ...(note !== undefined && { note }),
  };
}

/** ハザードマップポータル(国土数値情報)群の定型。公式定義は minZoom 2 / maxNativeZoom 17 */
function hazardTile(options: {
  id: string;
  name: string;
  /** タイルパスはレイヤidと別名のため必須(例: 01_flood_l2_shinsuishin_data) */
  urlPath: string;
  defaultOpacity: number;
  note?: string;
}): LayerCatalogEntry {
  return gsiTile({
    ...options,
    tags: ['hazard'],
    attribution: HAZARD_ATTR,
    baseUrl: HAZARD,
    minZoom: 2,
    maxNativeZoom: 17,
  });
}

export const LAYER_CATALOG: LayerCatalogEntry[] = [
  // ── ベースマップ(上部タブ = selectBase ショートカット) ──
  {
    id: 'dark',
    name: 'ダークモード (CARTO)',
    tags: ['basemap'],
    adapter: 'tile',
    role: 'base',
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    urlTemplate: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    subdomains: 'abcd',
    maxNativeZoom: 20,
    maxZoom: 20,
  },
  gsiTile({
    id: 'pale',
    name: '淡色地図 (国土地理院)',
    tags: ['basemap'],
    role: 'base',
    minZoom: 5,
    maxNativeZoom: 18,
  }),
  gsiTile({
    id: 'std',
    name: '標準地図 (国土地理院)',
    tags: ['basemap'],
    role: 'base',
    minZoom: 5,
    maxNativeZoom: 18,
  }),
  gsiTile({
    id: 'satellite',
    name: '衛星写真 (国土地理院)',
    tags: ['basemap', 'photo'],
    urlPath: 'seamlessphoto',
    ext: 'jpg',
    role: 'base',
    minZoom: 2,
    maxNativeZoom: 18,
  }),

  // ── 基本地図系オーバーレイ ──
  gsiTile({
    id: 'blank',
    name: '白地図',
    tags: ['basemap'],
    minZoom: 5,
    maxNativeZoom: 14,
    defaultOpacity: 0.5,
  }),

  // ── 写真・衛星 ──
  gsiTile({
    id: 'airphoto',
    name: '簡易空中写真 (2004年〜)',
    tags: ['photo'],
    ext: 'jpg',
    minZoom: 5,
    maxNativeZoom: 18,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'nendophoto2017',
    name: '全国写真 2017年',
    tags: ['photo', 'history'],
    ext: 'jpg',
    minZoom: 14,
    maxNativeZoom: 18,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'nendophoto2019',
    name: '全国写真 2019年',
    tags: ['photo', 'history'],
    ext: 'jpg',
    minZoom: 14,
    maxNativeZoom: 18,
    defaultOpacity: 0.5,
  }),

  // ── 歴史(年代別空中写真) ──
  gsiTile({
    id: 'gazo1',
    name: '国土画像情報 (1974-1978)',
    tags: ['history', 'photo'],
    ext: 'jpg',
    minZoom: 10,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'gazo2',
    name: '国土画像情報 (1979-1983)',
    tags: ['history', 'photo'],
    ext: 'jpg',
    minZoom: 10,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'gazo3',
    name: '国土画像情報 (1984-1986)',
    tags: ['history', 'photo'],
    ext: 'jpg',
    minZoom: 10,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'gazo4',
    name: '国土画像情報 (1987-1990)',
    tags: ['history', 'photo'],
    ext: 'jpg',
    minZoom: 10,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),

  // ── 標高・起伏 ──
  gsiTile({
    id: 'relief',
    name: '色別標高図',
    tags: ['terrain'],
    maxNativeZoom: 15,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'slopemap',
    name: '傾斜量図',
    tags: ['terrain', 'hazard'],
    minZoom: 3,
    maxNativeZoom: 15,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'hillshademap',
    name: '陰影起伏図',
    tags: ['terrain'],
    minZoom: 2,
    maxNativeZoom: 16,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'sekishoku',
    name: '赤色立体地図',
    tags: ['terrain'],
    minZoom: 2,
    maxNativeZoom: 14,
    defaultOpacity: 0.5,
  }),

  // ── 土地条件 ──
  gsiTile({
    id: 'lcm25k_2012',
    name: '土地条件図 (1995年国土数値情報)',
    tags: ['landform'],
    minZoom: 4,
    maxNativeZoom: 16,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'lcmfc2',
    name: '治水地形分類図',
    tags: ['landform', 'history'],
    minZoom: 5,
    maxNativeZoom: 16,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'swale',
    name: '明治期の低湿地',
    tags: ['history', 'landform'],
    minZoom: 5,
    maxNativeZoom: 16,
    defaultOpacity: 0.3,
  }),
  gsiTile({
    id: 'lake1',
    name: '湖沼図',
    tags: ['landform'],
    minZoom: 5,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),

  // ── 火山 ──
  gsiTile({
    id: 'vlcd',
    name: '火山土地条件図',
    tags: ['volcano'],
    minZoom: 2,
    maxNativeZoom: 16,
    defaultOpacity: 0.45,
  }),
  gsiTile({
    id: 'vbm',
    name: '火山基本図',
    tags: ['volcano'],
    minZoom: 2,
    maxNativeZoom: 17,
    defaultOpacity: 0.5,
  }),

  // ── 災害(活断層) ──
  gsiTile({
    id: 'afm',
    name: '活断層図 (都市圏活断層図)',
    tags: ['hazard'],
    maxNativeZoom: 16,
    defaultOpacity: 0.4,
  }),

  // ── 磁気(2020.0年値) ──
  gsiTile({
    id: 'jikizu2020_chijiki_d',
    name: '磁気図2020 (偏角)',
    tags: ['magnetic'],
    minZoom: 4,
    maxNativeZoom: 13,
    defaultOpacity: 0.25,
  }),
  gsiTile({
    id: 'jikizu2020_chijiki_i',
    name: '磁気図2020 (伏角)',
    tags: ['magnetic'],
    minZoom: 4,
    maxNativeZoom: 8,
    defaultOpacity: 0.25,
  }),
  gsiTile({
    id: 'jikizu2020_chijiki_f',
    name: '磁気図2020 (全磁力)',
    tags: ['magnetic'],
    minZoom: 4,
    maxNativeZoom: 8,
    defaultOpacity: 0.25,
  }),
  gsiTile({
    id: 'jikizu2020_chijiki_h',
    name: '磁気図2020 (水平分力)',
    tags: ['magnetic'],
    minZoom: 4,
    maxNativeZoom: 8,
    defaultOpacity: 0.25,
  }),
  gsiTile({
    id: 'jikizu2020_chijiki_z',
    name: '磁気図2020 (鉛直分力)',
    tags: ['magnetic'],
    minZoom: 4,
    maxNativeZoom: 8,
    defaultOpacity: 0.25,
  }),

  // ── 土地利用 ──
  gsiTile({
    id: 'lum4bl_2020',
    name: '宅地利用動向調査 (2020)',
    tags: ['landuse'],
    minZoom: 13,
    maxNativeZoom: 16,
    defaultOpacity: 0.5,
  }),
  gsiTile({
    id: 'lum200k',
    name: '20万分1土地利用図 (1982-1983)',
    tags: ['landuse'],
    minZoom: 11,
    maxNativeZoom: 14,
    defaultOpacity: 0.5,
  }),

  // ── 災害(ハザードマップポータル。公式定義は minZoom2/maxZoom17) ──
  hazardTile({
    id: 'flood_l2',
    name: '洪水浸水想定区域 (想定最大規模)',
    urlPath: '01_flood_l2_shinsuishin_data',
    defaultOpacity: 0.6,
    note: '深さごとの浸水ランク表示。浸水しない区域はタイルが存在しない',
  }),
  hazardTile({
    id: 'flood_l1',
    name: '洪水浸水想定区域 (計画規模)',
    urlPath: '01_flood_l1_shinsuishin_newlegend_data',
    defaultOpacity: 0.6,
    note: '計画規模(現在の凡例)。浸水しない区域はタイルが存在しない',
  }),
  hazardTile({
    id: 'tsunami',
    name: '津波浸水想定 (想定最大規模)',
    urlPath: '04_tsunami_newlegend_data',
    defaultOpacity: 0.6,
  }),
  hazardTile({
    id: 'kyukeisha',
    name: '急傾斜地の崩壊警戒区域',
    urlPath: '05_kyukeishakeikaikuiki',
    defaultOpacity: 0.6,
    note: '黄=警戒区域, 赤=特別警戒区域',
  }),
  hazardTile({
    id: 'dosekiryu',
    name: '土石流警戒区域',
    urlPath: '05_dosekiryukeikaikuiki',
    defaultOpacity: 0.5,
    note: '黄=警戒区域, 赤=特別警戒区域',
  }),
  hazardTile({
    id: 'jisuberi',
    name: '地すべり警戒区域',
    urlPath: '05_jisuberikeikaikuiki',
    defaultOpacity: 0.5,
    note: '黄=警戒区域, 赤=特別警戒区域',
  }),

  // ── 防災・避難(オシマランド。アダプタは feat/layers-oshima で登録) ──
  {
    id: 'oshima',
    name: '大島てる (事故物件マーク)',
    tags: ['safety'],
    adapter: 'oshima',
    attribution: OSHIMA_ATTR,
    note: '非公式API。クラスタリング無効時はズーム12未満で非表示。1時間キャッシュ',
    defaultOpacity: 1,
    settings: ['defaultOpacity', 'clustering'],
  },

  // ── ベクタタイル(MapLibre GL。VectorEngine が単一canvasで描画) ──
  {
    id: 'gsi_std_vector',
    name: '標準地図ベクタ (国土地理院)',
    tags: ['basemap'],
    adapter: 'maplibre',
    attribution: GSI_ATTR,
    role: 'base',
    vector: toVectorDef(gsiStdVectorStyle),
    description:
      '地理院の最適化ベクトルタイル(試験公開)。ラスタ版「標準地図」との併用切り替え可能',
    note: '試験公開のため、提供URL・内容が変わる可能性があります',
  },
  {
    id: 'gsi_contours',
    name: '等高線ベクタ (国土地理院)',
    tags: ['terrain'],
    adapter: 'maplibre',
    attribution: GSI_ATTR,
    vector: toVectorDef(gsiContoursStyle),
    defaultOpacity: 0.9,
    description: 'ベクタタイルの等高線。ラスタの陰影図・色別標高図と重ねられる',
    legend: legendOf('line', [
      ['rgb(200,160,60)', '計曲線(50m間隔・太線)'],
      ['rgb(200,160,60)', '主曲線(細線)'],
    ]),
  },

  // ── 国土数値情報(MLIT NLFTP)。scripts/ksj パイプラインで生成した
  //    PMTiles を /api/tiles/{code}/{z}/{x}/{y}.pbf で配信(ZXY直参照)。
  //    凡例の色は OH3 (refs/oh3-layers) の attribution 内凡例に準拠。
  ksjEntry({
    code: 'n03',
    title: '行政区域',
    year: 2024,
    maxzoom: 13,
    defaultOpacity: 0.5,
    tags: ['admin'],
    description:
      '都道府県・市区町村の行政界(面)。2024年(令和6年)版の47都道府県分を結合。北海道の支庁・振興局界を含む',
    layers: [
      {
        id: 'n03-fill',
        type: 'fill',
        source: 'n03',
        'source-layer': 'polygon',
        paint: { 'fill-color': '#9575cd', 'fill-opacity': 1 },
      },
    ],
  }),
  ksjEntry({
    code: 'l01',
    title: '地価公示',
    year: 2026,
    maxzoom: 7,
    defaultOpacity: 1,
    tags: ['realestate'],
    description:
      '2026年(令和8年)地価公示の標準地 約2.6万点(全国)。色は現況価格(円/m²)による7段階。標準地名・所在地を属性に持つ',
    layers: [
      {
        id: 'l01-circle',
        type: 'circle',
        source: 'l01',
        'source-layer': 'point',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2, 16, 5],
          'circle-color': [
            'step',
            ['get', 'L01_008'],
            'rgb(245,245,81)',
            100000,
            'rgb(239,211,71)',
            250000,
            'rgb(235,178,61)',
            500000,
            'rgb(231,145,52)',
            750000,
            'rgb(226,84,39)',
            1000000,
            'rgb(225,61,35)',
            10000000,
            'rgb(225,49,33)',
          ],
          'circle-opacity': 1,
        },
      },
    ],
    legend: legendOf('circle', [
      ['rgb(225,49,33)', '1000万円以上/m²'],
      ['rgb(225,61,35)', '100万〜1000万円/m²'],
      ['rgb(226,84,39)', '75万〜100万円/m²'],
      ['rgb(231,145,52)', '50万〜75万円/m²'],
      ['rgb(235,178,61)', '25万〜50万円/m²'],
      ['rgb(239,211,71)', '10万〜25万円/m²'],
      ['rgb(245,245,81)', '10万円未満/m²'],
    ]),
    featurePopup: {
      titleKey: 'L01_024',
      fields: [
        { key: 'L01_008', label: '公示価格', format: 'jpy-m2' },
        { key: 'L01_025', label: '所在地' },
        { key: 'L01_007', label: '公示年' },
      ],
    },
  }),
  ksjEntry({
    code: 'a29',
    title: '用途地域',
    year: 2019,
    maxzoom: 12,
    defaultOpacity: 0.5,
    tags: ['urbanplanning'],
    description:
      '都市計画法に基づく用途地域の指定範囲(2019年・令和元年調査、全国結合)。住居系から工業専用まで12区分(A29_004)で色分け',
    layers: [
      {
        id: 'a29-fill',
        type: 'fill',
        source: 'a29',
        'source-layer': 'polygon',
        paint: {
          'fill-color': [
            'match',
            ['get', 'A29_004'],
            1,
            'rgb(0,180,0)',
            2,
            'rgb(60,190,90)',
            3,
            'rgb(100,200,100)',
            4,
            'rgb(150,220,150)',
            5,
            'rgb(200,240,200)',
            6,
            'rgb(200,240,200)',
            7,
            'rgb(255,230,180)',
            8,
            'rgb(255,180,180)',
            9,
            'rgb(255,100,100)',
            10,
            'rgb(200,150,255)',
            11,
            'rgb(150,150,200)',
            12,
            'rgb(100,100,180)',
            'rgb(204,204,204)',
          ],
          'fill-opacity': 1,
        },
      },
    ],
    legend: legendOf('square', [
      ['rgb(0,180,0)', '第1種低層住居専用地域'],
      ['rgb(60,190,90)', '第2種低層住居専用地域'],
      ['rgb(100,200,100)', '第1種中高層住居専用地域'],
      ['rgb(150,220,150)', '第2種中高層住居専用地域'],
      ['rgb(200,240,200)', '第1種・第2種住居地域'],
      ['rgb(255,230,180)', '準住居地域'],
      ['rgb(255,180,180)', '近隣商業地域'],
      ['rgb(255,100,100)', '商業地域'],
      ['rgb(200,150,255)', '準工業地域'],
      ['rgb(150,150,200)', '工業地域'],
      ['rgb(100,100,180)', '工業専用地域'],
    ]),
  }),
  ksjEntry({
    code: 'a09',
    title: '都市地域',
    year: 2018,
    maxzoom: 12,
    defaultOpacity: 0.5,
    tags: ['urbanplanning'],
    description:
      '都市計画区域の区域区分(線引き)。2018年(平成30年)調べ・全国結合。都市計画区域/市街化区域/市街化調整区域/区域区分未定を色分け',
    layers: [
      {
        id: 'a09-fill',
        type: 'fill',
        source: 'a09',
        'source-layer': 'polygon',
        paint: {
          'fill-color': [
            'match',
            ['get', 'layer_no'],
            1,
            'rgb(173,216,230)',
            2,
            'rgb(255,200,150)',
            3,
            'rgb(150,220,150)',
            4,
            'rgb(230,230,210)',
            'rgb(204,204,204)',
          ],
          'fill-opacity': 1,
        },
      },
    ],
    legend: legendOf('square', [
      ['rgb(173,216,230)', '都市計画区域'],
      ['rgb(255,200,150)', '市街化区域'],
      ['rgb(150,220,150)', '市街化調整区域'],
      ['rgb(230,230,210)', '区域区分が定められていない都市計画区域'],
    ]),
  }),
  ksjEntry({
    code: 'n02',
    title: '鉄道',
    year: 2025,
    maxzoom: 10,
    defaultOpacity: 0.9,
    tags: ['transport'],
    description:
      '鉄道路線・駅構内のライン(2025年・令和7年版、全国)。路線名・事業者名(N02_003/N02_004)を属性に持つ',
    layers: [
      {
        id: 'n02-line',
        type: 'line',
        source: 'n02',
        'source-layer': 'line',
        paint: {
          'line-color': '#555555',
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 2],
          'line-opacity': 1,
        },
      },
    ],
    featurePopup: {
      titleKey: 'N02_003',
      fields: [{ key: 'N02_004', label: '事業者' }],
    },
  }),
  ksjEntry({
    code: 's12',
    title: '駅別乗降客数',
    year: 2024,
    maxzoom: 9,
    defaultOpacity: 0.9,
    generated: '2026-10-05',
    tags: ['transport'],
    description:
      '駅ごとの1日平均乗降客数(2024年・令和6年、全国)。駅構内のラインを乗降客数10段階で色分け(欠測は灰色)。駅名・路線名・事業者名を属性に持つ',
    layers: [
      {
        id: 's12-line',
        type: 'line',
        source: 's12',
        'source-layer': 'line',
        paint: {
          'line-color': [
            'step',
            // S12_061 = 1日平均乗降客数(2024年度)。欠測駅は変換時に
            // 0→null されているため step の既定色(灰色)に落ちる
            ['get', 'S12_061'],
            'hsl(0,0%,75%)',
            1,
            'hsl(240,100%,50%)',
            100,
            'hsl(230,100%,55%)',
            300,
            'hsl(220,100%,60%)',
            500,
            'hsl(210,100%,65%)',
            1000,
            'hsl(200,100%,70%)',
            5000,
            'hsl(180,100%,50%)',
            20000,
            'hsl(150,100%,50%)',
            100000,
            'hsl(120,100%,50%)',
            500000,
            'hsl(60,100%,50%)',
            1200000,
            'hsl(0,100%,50%)',
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 2],
          'line-opacity': 1,
        },
      },
    ],
    legend: legendOf('line', [
      ['hsl(0,0%,75%)', 'データなし'],
      ['hsl(240,100%,50%)', '1 - 99人'],
      ['hsl(230,100%,55%)', '100 - 299人'],
      ['hsl(220,100%,60%)', '300 - 499人'],
      ['hsl(210,100%,65%)', '500 - 999人'],
      ['hsl(200,100%,70%)', '1000 - 4999人'],
      ['hsl(180,100%,50%)', '5000 - 19999人'],
      ['hsl(150,100%,50%)', '20000 - 99999人'],
      ['hsl(120,100%,50%)', '100000 - 499999人'],
      ['hsl(60,100%,50%)', '500000 - 1199999人'],
      ['hsl(0,100%,50%)', '1200000人+'],
    ]),
    featurePopup: {
      // 現行KSJスキーマ(v3系): S12_001=駅名 / S12_002=運営会社 / S12_003=路線名
      titleKey: 'S12_001',
      fields: [
        { key: 'S12_003', label: '路線' },
        { key: 'S12_002', label: '事業者' },
        { key: 'S12_061', label: '1日平均乗降客数', format: 'int' },
      ],
    },
  }),
];

export const catalogById: ReadonlyMap<string, LayerCatalogEntry> = new Map(
  LAYER_CATALOG.map((entry) => [entry.id, entry]),
);

/** カタログのうちベースマップ(role:'base')のみ。カタログ定義順(差し替えメニューの並び順) */
export const baseEntries: LayerCatalogEntry[] = LAYER_CATALOG.filter(
  (entry) => entry.role === 'base',
);

/** タグ→LAYER_TAGS定義順のインデックス(未定義タグは最後尾にソート) */
const TAG_ORDER: ReadonlyMap<LayerTag, number> = new Map(
  LAYER_TAGS.map((t, i) => [t.id, i] as const),
);

/** タグの定義順ソートキー(未定義タグは最後尾)。無効リストの並び順契約の正本 */
export function tagOrderOf(tag: LayerTag | undefined): number {
  return tag != null ? (TAG_ORDER.get(tag) ?? LAYER_TAGS.length) : LAYER_TAGS.length;
}

/** カタログのうち未有効のレイヤ(無効リスト表示用)。タグ定義順→名前順 */
export function disabledEntries(enabledIds: ReadonlySet<string>): LayerCatalogEntry[] {
  return LAYER_CATALOG.filter((entry) => !enabledIds.has(entry.id)).sort((a, b) => {
    const orderA = tagOrderOf(a.tags[0]);
    const orderB = tagOrderOf(b.tags[0]);
    if (orderA !== orderB) return orderA - orderB;
    return a.name.localeCompare(b.name, 'ja');
  });
}
