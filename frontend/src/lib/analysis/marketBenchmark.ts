import type { PropertyFeature } from '../../types.ts';

/** 相場比較で切り替えられる指標 */
export type MarketMetric = 'daily' | 'perSqm' | 'area' | 'walk';

/** 指標の表示定義(label は切替ボタン・KPI 見出し, formatValue は KPI/軸/ツールチップ共通) */
export interface MetricDef {
  id: MarketMetric;
  label: string;
  unit: string;
  formatValue: (v: number) => string;
}

export const METRICS: Record<MarketMetric, MetricDef> = {
  daily: {
    id: 'daily',
    label: '日額',
    unit: '円',
    formatValue: (v) => `${Math.round(v).toLocaleString()}円`,
  },
  perSqm: {
    id: 'perSqm',
    label: '㎡単価',
    unit: '円/㎡',
    formatValue: (v) => `${v.toFixed(1)}円/㎡`,
  },
  area: {
    id: 'area',
    label: '面積',
    unit: '㎡',
    formatValue: (v) => `${v.toFixed(1)}㎡`,
  },
  walk: {
    id: 'walk',
    label: '徒歩分',
    unit: '分',
    formatValue: (v) => `${Math.round(v)}分`,
  },
};

/** ピア比較の範囲。municipality=同市区町村×間取り / prefecture=同都道府県×間取り */
export type MarketScope = 'municipality' | 'prefecture';

export interface PeerSet {
  peers: PropertyFeature[];
  scope: MarketScope;
  /** 例「横浜市 × 1R」「神奈川県 × 1K」 */
  groupLabel: string;
  /** 市区町村で5件未満だったため都道府県にフォールバックしたか */
  fallback: boolean;
}

/** null / 非数 / 0以下の数値を無効とみなす(掲載データの欠損・異常値ガード) */
function positiveOrNull(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;
}

/**
 * self と同じ「市区町村×間取り」の掲載中ピア集合を作る。
 * 同市区町村のピアが minPeers 件未満のときは「都道府県×間取り」へフォールバックする。
 * 掲載終了(is_active === false)と self 自身は除外。
 */
export function buildPeerSet(
  allFeatures: PropertyFeature[],
  self: PropertyFeature,
  minPeers = 5,
): PeerSet {
  const selfId = self.properties.id;
  const layout = self.properties.layout;
  const municipality = self.properties.municipality ?? null;
  const prefecture = self.properties.prefecture_name ?? null;
  // 掲載中かつ self 以外のみを候補にする
  const candidates = allFeatures.filter(
    (f) => f.properties.id !== selfId && f.properties.is_active !== false,
  );

  // 市区町村スコープ(self の municipality が取れない物件はそもそも対象にならない)
  if (municipality != null) {
    const peers = candidates.filter(
      (f) => f.properties.layout === layout && f.properties.municipality === municipality,
    );
    if (peers.length >= minPeers) {
      return {
        peers,
        scope: 'municipality',
        groupLabel: `${municipality} × ${layout}`,
        fallback: false,
      };
    }
  }

  // 都道府県スコープ(市区町村が少ない or self に市区町村がない場合。municipality null の物件も許容)
  const scopeKey = prefecture ?? municipality ?? '不明';
  const peers = candidates.filter(
    (f) => f.properties.layout === layout && f.properties.prefecture_name === prefecture,
  );
  return {
    peers,
    scope: 'prefecture',
    groupLabel: `${scopeKey} × ${layout}`,
    // municipality 自体が無いケースは「フォールバック」ではなく最初から都道府県単位
    fallback: municipality != null,
  };
}

/** 指標に応じた数値を取り出す。欠損(null)や0以下は比較対象外として null */
export function metricValue(feature: PropertyFeature, metric: MarketMetric): number | null {
  const p = feature.properties;
  const rent = positiveOrNull(p.min_daily_rent);
  const area = positiveOrNull(p.area_m2);
  switch (metric) {
    case 'daily':
      return rent;
    case 'perSqm':
      // 両方が有効な値のときのみ単価を算出(0除算防止)
      return rent != null && area != null ? rent / area : null;
    case 'area':
      return area;
    case 'walk':
      return positiveOrNull(p.min_walk_minutes);
  }
}

/** 数値集合の統計サマリ(5数要約)。有効値が1件もなければ null */
export interface NumericSummary {
  count: number;
  min: number;
  p25: number;
  median: number;
  p75: number;
  max: number;
}

export function numericSummary(values: number[]): NumericSummary | null {
  const valid = values.filter((v) => Number.isFinite(v));
  if (valid.length === 0) return null;
  const sorted = [...valid].sort((a, b) => a - b);
  // 線形補間(0.25 / 0.5 / 0.75 分位点)。中央値は奇数なら要素値・偶数なら中間値
  const at = (pos: number): number => {
    const idx = pos * (sorted.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
  };
  return {
    count: sorted.length,
    min: sorted[0],
    p25: at(0.25),
    median: at(0.5),
    p75: at(0.75),
    max: sorted[sorted.length - 1],
  };
}

/**
 * self がピアの中で何パーセントの位置か(0=最安値, 100=最高値)。
 * 同値のピアは上位側(高い側)に数えるため、self より安いピアの割合を返す。
 */
export function percentileRank(peerValues: number[], selfValue: number): number | null {
  if (!Number.isFinite(selfValue) || peerValues.length === 0) return null;
  const strictlyLess = peerValues.filter((v) => v < selfValue).length;
  return (strictlyLess / peerValues.length) * 100;
}

/** 最小二乗直線(y = slope * x + intercept)。点が2点未満、または x が全て同一(垂直線)なら null */
export function linearRegression(
  points: { x: number; y: number }[],
): { slope: number; intercept: number } | null {
  const valid = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (valid.length < 2) return null;
  const n = valid.length;
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  for (const p of valid) {
    sx += p.x;
    sy += p.y;
    sxx += p.x * p.x;
    sxy += p.x * p.y;
  }
  const denom = n * sxx - sx * sx;
  if (denom === 0) return null;
  const slope = (n * sxy - sx * sy) / denom;
  const intercept = (sy - slope * sx) / n;
  return { slope, intercept };
}

/** ヒストグラムのビン1個分 */
export interface HistogramBin {
  from: number;
  to: number;
  count: number;
  hasSelf: boolean;
}

/**
 * ヒストグラムのビンを作る。ビン幅は rawWidth=(範囲/binCount) を
 * nice number(1, 2, 2.5, 5, 10 × 10^n)へ丸めてキリの良い幅にする。
 * selfValue がピア範囲外でも見えるよう、範囲は self を含めて広げる。
 */
export function buildBins(
  values: number[],
  selfValue: number | null,
  binCount = 12,
): { bins: HistogramBin[]; selfBinIndex: number | null } {
  const valid = values.filter((v) => Number.isFinite(v));
  const self = selfValue != null && Number.isFinite(selfValue) ? selfValue : null;
  if (valid.length === 0) return { bins: [], selfBinIndex: null };

  const min = Math.min(...valid, self ?? Infinity);
  const max = Math.max(...valid, self ?? -Infinity);

  // ビン幅の nice 化: 上位桁の仮数を 1/2/2.5/5/10 のいずれかに丸める
  const rawWidth = Math.max(max - min, 0) / Math.max(binCount, 1);
  let width = 1;
  if (rawWidth > 0) {
    const exp = Math.floor(Math.log10(rawWidth));
    const base = Math.pow(10, exp);
    const frac = rawWidth / base;
    const nice = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 2.5 ? 2.5 : frac <= 5 ? 5 : 10;
    width = nice * base;
  }

  // 範囲の下端をビン幅で切り捨てた位置から開始し、max を覆うまで並べる
  const start = Math.floor(min / width) * width;
  let count = Math.ceil((max - start) / width);
  if (max >= start + count * width) count += 1; // max が境界ちょうどのときの1ビン追加

  const bins: HistogramBin[] = Array.from({ length: count }, (_, i) => ({
    from: start + i * width,
    to: start + (i + 1) * width,
    count: 0,
    hasSelf: false,
  }));
  for (const v of valid) {
    const idx = Math.floor((v - start) / width);
    if (idx >= 0 && idx < bins.length) bins[idx].count += 1;
  }

  // self の所属ビン(from <= v < to。最終ビンの右端境界は次ビン起点に倒す)
  let selfBinIndex: number | null = null;
  if (self != null) {
    const idx = Math.floor((self - start) / width);
    if (idx >= 0 && idx < bins.length) selfBinIndex = idx;
    if (selfBinIndex != null) bins[selfBinIndex].hasSelf = true;
  }
  return { bins, selfBinIndex };
}
