#!/usr/bin/env node
/**
 * 国土地理院「最適化ベクトルタイル」の公式 MapLibre スタイルをベンダリングする。
 *
 * 出所(いずれも試験公開・CORS許可):
 *   - スタイル std.json: https://gsi-cyberjapan.github.io/optimal_bvmap/style/std.json
 *     (生成元リポジトリ: https://github.com/gsi-cyberjapan/optimal_bvmap)
 *   - タイル(PMTiles): https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/optimal_bvmap-v1.pmtiles
 *   - glyphs/sprite: https://gsi-cyberjapan.github.io/optimal_bvmap/{glyphs,sprite}
 *
 * 生成物(frontend/ 基準の相対パス):
 *   - src/lib/layers/styles/gsi_std_vector.json
 *       標準地図(ベクタ)用スタイル断片。source id `v` → `gsi-std` にリネームし、
 *       layer id を `gsi-std:{元id}` 形式にする。terrain/sky は Leaflet 2D では
 *       無意味なため削除(light は保持)。
 *   - src/lib/layers/styles/gsi_contours.json
 *       std.json から等高線(source-layer `Cntr`)に関わる layer のみ抽出した
 *       スタイル断片。source id は `gsi-bvmap`。線色は公式スタイルのまま。
 *
 * タイルURLについて(重要):
 *   元スタイルは `pmtiles://…/optimal_bvmap-v1.pmtiles/{z}/{x}/{y}` 形式だが、
 *   maplibre-gl v6 はタイル取得を Worker 内で行うため、main-thread の
 *   addProtocol('pmtiles', …) では pmtiles:// タイルが取得できない
 *   (Worker 側登録は importScriptInWorkers の実験APIが必要)。
 *   そのため同一データの直接ZXY配信 `…/optimal_bvmap-v1/{z}/{x}/{y}.pbf`
 *   (CORS *) に書き換えて出力する。
 *
 * 生成日: 2026-09-16(初回)。再実行: `node scripts/vendor-gsi-style.mjs`
 * (オフライン再実行時は第1引数にローカルの std.json パスを渡せる)
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(SCRIPT_DIR, '..');
const OUT_DIR = path.join(FRONTEND_DIR, 'src/lib/layers/styles');

const STYLE_URL = 'https://gsi-cyberjapan.github.io/optimal_bvmap/style/std.json';
const SOURCE_REPOSITORY = 'https://github.com/gsi-cyberjapan/optimal_bvmap';

/** 元スタイルの vector source id */
const ORIG_SOURCE_ID = 'v';
/** 標準地図断片の source id */
const STD_SOURCE_ID = 'gsi-std';
/** 等高線断片の source id */
const CTR_SOURCE_ID = 'gsi-bvmap';
/** 等高線系 layer が使う source-layer 名(変更時は出力を grep して確認) */
const CONTOUR_SOURCE_LAYERS = new Set(['Cntr']);

/**
 * 直接ZXY配信のタイルURL(maplibre-gl v6 の Worker 内タイル取得は
 * カスタムプロトコル非対応のため pmtiles:// を置き換える)
 */
const DIRECT_TILES_URL =
  'https://cyberjapandata.gsi.go.jp/xyz/optimal_bvmap-v1/{z}/{x}/{y}.pbf';

/** 簡易ディープクローン(JSON由来のため構造は JSON 互換のみ) */
const clone = (value) => structuredClone(value);

/**
 * layer の source 参照をリネームし、layer id にプレフィックスを付ける。
 * layer id 重複があればエラー(公式スタイル側で重複した場合に検知)。
 */
function retagLayers(style, sourceId, idPrefix) {
  const seen = new Set();
  const layers = style.layers.map((layer) => {
    const next = clone(layer);
    next.id = `${idPrefix}:${layer.id}`;
    if (seen.has(next.id)) {
      throw new Error(`layer id が重複しました: ${next.id}`);
    }
    seen.add(next.id);
    if (next.source === ORIG_SOURCE_ID) next.source = sourceId;
    return next;
  });
  return layers;
}

async function loadStyle() {
  const arg = process.argv[2];
  if (arg) {
    console.log(`ローカルファイルから読み込み: ${arg}`);
    return JSON.parse(await readFile(arg, 'utf8'));
  }
  console.log(`ダウンロード: ${STYLE_URL}`);
  const res = await fetch(STYLE_URL);
  if (!res.ok) throw new Error(`スタイル取得に失敗: HTTP ${res.status}`);
  return res.json();
}

async function main() {
  const original = await loadStyle();
  const generatedAt = new Date().toISOString().slice(0, 10);

  const origSource = original.sources?.[ORIG_SOURCE_ID];
  if (origSource?.type !== 'vector') {
    throw new Error(`公式スタイルの構成が変わりました: sources.${ORIG_SOURCE_ID} が vector ではありません`);
  }
  /** pmtiles:// を直接ZXY URL に差し替えた source(minzoom/maxzoom等はそのまま) */
  const directSource = { ...clone(origSource), tiles: [DIRECT_TILES_URL] };

  // ── 標準地図(ベクタ)断片 ──
  // terrain/sky は Leaflet 2D 同期では意味がないため載せない(light は保持)
  const stdStyle = {
    version: 8,
    metadata: {
      'yadokari:source': STYLE_URL,
      'yadokari:repository': SOURCE_REPOSITORY,
      'yadokari:generatedAt': generatedAt,
    },
    name: original.name,
    glyphs: original.glyphs,
    sprite: original.sprite,
    ...(original.light !== undefined ? { light: original.light } : {}),
    sources: { [STD_SOURCE_ID]: clone(directSource) },
    layers: retagLayers(original, STD_SOURCE_ID, 'gsi-std'),
  };

  // ── 等高線断片(std.json から Cntr 系 layer のみ抽出) ──
  const contourLayers = original.layers.filter(
    (layer) => typeof layer['source-layer'] === 'string' && CONTOUR_SOURCE_LAYERS.has(layer['source-layer']),
  );
  if (contourLayers.length === 0) {
    throw new Error('等高線 layer(source-layer Cntr)が見つかりません。公式スタイルの構成を確認してください');
  }
  const usesIcon = contourLayers.some((layer) => layer.layout && 'icon-image' in layer.layout);
  const ctrStyle = {
    version: 8,
    metadata: {
      'yadokari:source': STYLE_URL,
      'yadokari:repository': SOURCE_REPOSITORY,
      'yadokari:generatedAt': generatedAt,
      'yadokari:note': 'std.json から等高線(source-layer Cntr)のみ抽出',
    },
    glyphs: original.glyphs, // 標高数値ラベル(等高線数値部)で必要
    ...(usesIcon ? { sprite: original.sprite } : {}),
    sources: { [CTR_SOURCE_ID]: clone(directSource) },
    layers: retagLayers({ layers: contourLayers }, CTR_SOURCE_ID, 'gsi-ctr'),
  };

  await mkdir(OUT_DIR, { recursive: true });
  const stdPath = path.join(OUT_DIR, 'gsi_std_vector.json');
  const ctrPath = path.join(OUT_DIR, 'gsi_contours.json');
  await writeFile(stdPath, JSON.stringify(stdStyle, null, 2) + '\n', 'utf8');
  await writeFile(ctrPath, JSON.stringify(ctrStyle, null, 2) + '\n', 'utf8');

  console.log(`書き込み: ${path.relative(FRONTEND_DIR, stdPath)} (layers=${stdStyle.layers.length})`);
  console.log(`書き込み: ${path.relative(FRONTEND_DIR, ctrPath)} (layers=${ctrStyle.layers.length})`);
  for (const layer of ctrStyle.layers) {
    if (layer.type === 'line' && layer.paint?.['line-color'] !== undefined) {
      console.log(`  等高線の線色: ${JSON.stringify(layer.paint['line-color'])}`);
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
