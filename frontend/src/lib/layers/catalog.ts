import { LAYER_TAGS } from './types.ts';
import type {
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
  {
    id: 'pale',
    name: '淡色地図 (国土地理院)',
    tags: ['basemap'],
    adapter: 'tile',
    role: 'base',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/pale/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 18,
    maxZoom: 20,
  },
  {
    id: 'std',
    name: '標準地図 (国土地理院)',
    tags: ['basemap'],
    adapter: 'tile',
    role: 'base',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/std/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 18,
    maxZoom: 20,
  },
  {
    id: 'satellite',
    name: '衛星写真 (国土地理院)',
    tags: ['basemap', 'photo'],
    adapter: 'tile',
    role: 'base',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/seamlessphoto/{z}/{x}/{y}.jpg`,
    minZoom: 2,
    maxNativeZoom: 18,
    maxZoom: 20,
  },

  // ── 基本地図系オーバーレイ ──
  {
    id: 'blank',
    name: '白地図',
    tags: ['basemap'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/blank/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 14,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 写真・衛星 ──
  {
    id: 'airphoto',
    name: '簡易空中写真 (2004年〜)',
    tags: ['photo'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/airphoto/{z}/{x}/{y}.jpg`,
    minZoom: 5,
    maxNativeZoom: 18,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'nendophoto2017',
    name: '全国写真 2017年',
    tags: ['photo', 'history'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/nendophoto2017/{z}/{x}/{y}.jpg`,
    minZoom: 14,
    maxNativeZoom: 18,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'nendophoto2019',
    name: '全国写真 2019年',
    tags: ['photo', 'history'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/nendophoto2019/{z}/{x}/{y}.jpg`,
    minZoom: 14,
    maxNativeZoom: 18,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 歴史(年代別空中写真) ──
  {
    id: 'gazo1',
    name: '国土画像情報 (1974-1978)',
    tags: ['history', 'photo'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/gazo1/{z}/{x}/{y}.jpg`,
    minZoom: 10,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'gazo2',
    name: '国土画像情報 (1979-1983)',
    tags: ['history', 'photo'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/gazo2/{z}/{x}/{y}.jpg`,
    minZoom: 10,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'gazo3',
    name: '国土画像情報 (1984-1986)',
    tags: ['history', 'photo'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/gazo3/{z}/{x}/{y}.jpg`,
    minZoom: 10,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'gazo4',
    name: '国土画像情報 (1987-1990)',
    tags: ['history', 'photo'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/gazo4/{z}/{x}/{y}.jpg`,
    minZoom: 10,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 標高・起伏 ──
  {
    id: 'relief',
    name: '色別標高図',
    tags: ['terrain'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/relief/{z}/{x}/{y}.png`,
    maxNativeZoom: 15,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'slopemap',
    name: '傾斜量図',
    tags: ['terrain', 'hazard'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/slopemap/{z}/{x}/{y}.png`,
    minZoom: 3,
    maxNativeZoom: 15,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'hillshademap',
    name: '陰影起伏図',
    tags: ['terrain'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/hillshademap/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'sekishoku',
    name: '赤色立体地図',
    tags: ['terrain'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/sekishoku/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 14,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 土地条件 ──
  {
    id: 'lcm25k_2012',
    name: '土地条件図 (1995年国土数値情報)',
    tags: ['landform'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/lcm25k_2012/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'lcmfc2',
    name: '治水地形分類図',
    tags: ['landform', 'history'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/lcmfc2/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'swale',
    name: '明治期の低湿地',
    tags: ['history', 'landform'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/swale/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.3,
  },
  {
    id: 'lake1',
    name: '湖沼図',
    tags: ['landform'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/lake1/{z}/{x}/{y}.png`,
    minZoom: 5,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 火山 ──
  {
    id: 'vlcd',
    name: '火山土地条件図',
    tags: ['volcano'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/vlcd/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.45,
  },
  {
    id: 'vbm',
    name: '火山基本図',
    tags: ['volcano'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/vbm/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 災害(活断層) ──
  {
    id: 'afm',
    name: '活断層図 (都市圏活断層図)',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/afm/{z}/{x}/{y}.png`,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.4,
  },

  // ── 磁気(2020.0年値) ──
  {
    id: 'jikizu2020_chijiki_d',
    name: '磁気図2020 (偏角)',
    tags: ['magnetic'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/jikizu2020_chijiki_d/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 13,
    maxZoom: 20,
    defaultOpacity: 0.25,
  },
  {
    id: 'jikizu2020_chijiki_i',
    name: '磁気図2020 (伏角)',
    tags: ['magnetic'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/jikizu2020_chijiki_i/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 8,
    maxZoom: 20,
    defaultOpacity: 0.25,
  },
  {
    id: 'jikizu2020_chijiki_f',
    name: '磁気図2020 (全磁力)',
    tags: ['magnetic'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/jikizu2020_chijiki_f/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 8,
    maxZoom: 20,
    defaultOpacity: 0.25,
  },
  {
    id: 'jikizu2020_chijiki_h',
    name: '磁気図2020 (水平分力)',
    tags: ['magnetic'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/jikizu2020_chijiki_h/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 8,
    maxZoom: 20,
    defaultOpacity: 0.25,
  },
  {
    id: 'jikizu2020_chijiki_z',
    name: '磁気図2020 (鉛直分力)',
    tags: ['magnetic'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/jikizu2020_chijiki_z/{z}/{x}/{y}.png`,
    minZoom: 4,
    maxNativeZoom: 8,
    maxZoom: 20,
    defaultOpacity: 0.25,
  },

  // ── 土地利用 ──
  {
    id: 'lum4bl_2020',
    name: '宅地利用動向調査 (2020)',
    tags: ['landuse'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/lum4bl_2020/{z}/{x}/{y}.png`,
    minZoom: 13,
    maxNativeZoom: 16,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },
  {
    id: 'lum200k',
    name: '20万分1土地利用図 (1982-1983)',
    tags: ['landuse'],
    adapter: 'tile',
    attribution: GSI_ATTR,
    urlTemplate: `${GSI}/lum200k/{z}/{x}/{y}.png`,
    minZoom: 11,
    maxNativeZoom: 14,
    maxZoom: 20,
    defaultOpacity: 0.5,
  },

  // ── 災害(ハザードマップポータル。公式定義は minZoom2/maxZoom17) ──
  {
    id: 'flood_l2',
    name: '洪水浸水想定区域 (想定最大規模)',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    note: '深さごとの浸水ランク表示。浸水しない区域はタイルが存在しない',
    defaultOpacity: 0.6,
  },
  {
    id: 'flood_l1',
    name: '洪水浸水想定区域 (計画規模)',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/01_flood_l1_shinsuishin_newlegend_data/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    note: '計画規模(現在の凡例)。浸水しない区域はタイルが存在しない',
    defaultOpacity: 0.6,
  },
  {
    id: 'tsunami',
    name: '津波浸水想定 (想定最大規模)',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/04_tsunami_newlegend_data/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    defaultOpacity: 0.6,
  },
  {
    id: 'kyukeisha',
    name: '急傾斜地の崩壊警戒区域',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/05_kyukeishakeikaikuiki/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    note: '黄=警戒区域, 赤=特別警戒区域',
    defaultOpacity: 0.6,
  },
  {
    id: 'dosekiryu',
    name: '土石流警戒区域',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/05_dosekiryukeikaikuiki/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    note: '黄=警戒区域, 赤=特別警戒区域',
    defaultOpacity: 0.5,
  },
  {
    id: 'jisuberi',
    name: '地すべり警戒区域',
    tags: ['hazard'],
    adapter: 'tile',
    attribution: HAZARD_ATTR,
    urlTemplate: `${HAZARD}/05_jisuberikeikaikuiki/{z}/{x}/{y}.png`,
    minZoom: 2,
    maxNativeZoom: 17,
    maxZoom: 20,
    note: '黄=警戒区域, 赤=特別警戒区域',
    defaultOpacity: 0.5,
  },

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
  {
    id: 'ksj_n03',
    name: '行政区域 (国土数値情報 2024)',
    tags: ['admin'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(行政区域)</a>',
    vector: {
      sources: {
        n03: { type: 'vector', tiles: ['/api/tiles/n03/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 13 },
      },
      layers: [
        {
          id: 'n03-fill',
          type: 'fill',
          source: 'n03',
          'source-layer': 'polygon',
          paint: { 'fill-color': '#9575cd', 'fill-opacity': 1 },
        },
      ],
    },
    description:
      '都道府県・市区町村の行政界(面)。2024年(令和6年)版の47都道府県分を結合。北海道の支庁・振興局界を含む',
    note: '生成: 2026-09-16 (scripts/ksj)',
    defaultOpacity: 0.5,
  },
  {
    id: 'ksj_l01',
    name: '地価公示 (国土数値情報 2026)',
    tags: ['realestate'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(地価公示)</a>',
    vector: {
      sources: {
        l01: { type: 'vector', tiles: ['/api/tiles/l01/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 7 },
      },
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
    },
    description:
      '2026年(令和8年)地価公示の標準地 約2.6万点(全国)。色は現況価格(円/m²)による7段階。標準地名・所在地を属性に持つ',
    note: '生成: 2026-09-16 (scripts/ksj)',
    defaultOpacity: 1,
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
  },
  {
    id: 'ksj_a29',
    name: '用途地域 (国土数値情報 2019)',
    tags: ['urbanplanning'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(用途地域)</a>',
    vector: {
      sources: {
        a29: { type: 'vector', tiles: ['/api/tiles/a29/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 12 },
      },
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
    },
    description:
      '都市計画法に基づく用途地域の指定範囲(2019年・令和元年調査、全国結合)。住居系から工業専用まで12区分(A29_004)で色分け',
    note: '生成: 2026-09-16 (scripts/ksj)',
    defaultOpacity: 0.5,
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
  },
  {
    id: 'ksj_a09',
    name: '都市地域 (国土数値情報 2018)',
    tags: ['urbanplanning'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(都市地域)</a>',
    vector: {
      sources: {
        a09: { type: 'vector', tiles: ['/api/tiles/a09/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 12 },
      },
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
    },
    description:
      '都市計画区域の区域区分(線引き)。2018年(平成30年)調べ・全国結合。都市計画区域/市街化区域/市街化調整区域/区域区分未定を色分け',
    note: '生成: 2026-09-16 (scripts/ksj)',
    defaultOpacity: 0.5,
    legend: legendOf('square', [
      ['rgb(173,216,230)', '都市計画区域'],
      ['rgb(255,200,150)', '市街化区域'],
      ['rgb(150,220,150)', '市街化調整区域'],
      ['rgb(230,230,210)', '区域区分が定められていない都市計画区域'],
    ]),
  },
  {
    id: 'ksj_n02',
    name: '鉄道 (国土数値情報 2025)',
    tags: ['transport'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(鉄道)</a>',
    vector: {
      sources: {
        n02: { type: 'vector', tiles: ['/api/tiles/n02/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 10 },
      },
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
    },
    description:
      '鉄道路線・駅構内のライン(2025年・令和7年版、全国)。路線名・事業者名(N02_003/N02_004)を属性に持つ',
    note: '生成: 2026-09-16 (scripts/ksj)',
    defaultOpacity: 0.9,
    featurePopup: {
      titleKey: 'N02_003',
      fields: [{ key: 'N02_004', label: '事業者' }],
    },
  },
  {
    id: 'ksj_s12',
    name: '駅別乗降客数 (国土数値情報 2024)',
    tags: ['transport'],
    adapter: 'maplibre',
    attribution:
      '出典: <a href="https://nlftp.mlit.go.jp/ksj/" target="_blank" rel="noopener">国土数値情報(駅別乗降客数)</a>',
    vector: {
      sources: {
        s12: { type: 'vector', tiles: ['/api/tiles/s12/{z}/{x}/{y}.pbf'], minzoom: 4, maxzoom: 9 },
      },
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
    },
    description:
      '駅ごとの1日平均乗降客数(2024年・令和6年、全国)。駅構内のラインを乗降客数10段階で色分け(欠測は灰色)。駅名・路線名・事業者名を属性に持つ',
    note: '生成: 2026-10-05 (scripts/ksj)',
    defaultOpacity: 0.9,
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
  },
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

/** カタログのうち未有効のレイヤ(無効リスト表示用)。タグ定義順→名前順 */
export function disabledEntries(enabledIds: ReadonlySet<string>): LayerCatalogEntry[] {
  const last = LAYER_TAGS.length;
  const orderOf = (tag: LayerTag | undefined): number =>
    tag != null ? (TAG_ORDER.get(tag) ?? last) : last;
  return LAYER_CATALOG.filter((entry) => !enabledIds.has(entry.id)).sort((a, b) => {
    const orderA = orderOf(a.tags[0]);
    const orderB = orderOf(b.tags[0]);
    if (orderA !== orderB) return orderA - orderB;
    return a.name.localeCompare(b.name, 'ja');
  });
}
