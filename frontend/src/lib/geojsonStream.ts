/**
 * /api/geojson/stream (NDJSON) の読み込み。
 *
 * 行契約(1行1JSONオブジェクト。行順は保証される):
 * - {"type":"meta","total":<number>}   … 先頭。全体件数の概算値(post-filter
 *   前の DB 総件数のため、end.count と一致する保証はない。進捗表示の目安)
 * - {"type":"feature","feature":{...}} … 物件 Feature ×N 行
 * - {"type":"end","count":<number>}    … 末尾。確定受信件数
 *
 * onProgress は進捗表示用に受け取り件数を通知する(200msスロットル。終了時は必ず最終値を通知)。
 * total は上記の通り概算値のため、表示側(GeojsonLoadProgress)は total != null のときのみ
 * 「受信/総数」形式の確定バーを出し、進捗率のクリップ(min 100%)で超過を吸収する。
 * end行が来る前に接続が切れた場合はエラーを投げる(呼び出し側で一括取得へフォールバック)。
 */
import type { PropertyFeature, PropertyGeoJSON } from '@/types.ts';

export interface GeojsonStreamProgress {
  received: number;
  total: number | null;
}

/** 初期ロードの進捗表示状態。phase は stream → bulk(一括API) → local(/map.geojson) のフォールバック順 */
export interface GeojsonLoadProgressState extends GeojsonStreamProgress {
  phase: 'stream' | 'bulk' | 'local';
}

const PROGRESS_THROTTLE_MS = 200;

export async function streamGeojson(
  onProgress: (progress: GeojsonStreamProgress) => void,
  signal?: AbortSignal,
): Promise<PropertyGeoJSON> {
  const res = await fetch('/api/geojson/stream', { signal });
  if (!res.ok || !res.body) {
    throw new Error(`geojson stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const features: PropertyFeature[] = [];
  let total: number | null = null;
  let receivedEnd = false;
  let buffer = '';
  let lastEmit = 0;

  const emit = (force = false) => {
    const now = performance.now();
    if (force || now - lastEmit >= PROGRESS_THROTTLE_MS) {
      lastEmit = now;
      onProgress({ received: features.length, total });
    }
  };

  const consumeLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const msg = JSON.parse(trimmed) as {
      type: 'meta' | 'feature' | 'end';
      total?: number;
      feature?: PropertyFeature;
      count?: number;
    };
    if (msg.type === 'meta') {
      if (typeof msg.total === 'number') total = msg.total;
    } else if (msg.type === 'feature' && msg.feature) {
      features.push(msg.feature);
    } else if (msg.type === 'end') {
      receivedEnd = true;
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });

    let newlineIndex: number;
    while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
      consumeLine(buffer.slice(0, newlineIndex));
      buffer = buffer.slice(newlineIndex + 1);
    }
    emit();

    if (done) break;
  }
  buffer += decoder.decode();
  if (buffer) consumeLine(buffer);

  if (!receivedEnd) {
    // プロキシ等で打ち切られた可能性があるため一括取得へフォールバックさせる
    throw new Error(`geojson stream ended without end marker (${features.length} features)`);
  }
  emit(true);

  return { type: 'FeatureCollection', features };
}
