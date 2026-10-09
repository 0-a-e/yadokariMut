/**
 * Shared comparison row definitions for ComparisonBoard and showComparison GenUI.
 */
import { fmtStatus } from './shortlist.ts';

// 状態ラベル変換の正本(lib/shortlist.ts)。既存 import 経路を壊さないよう再輸出する
export { fmtStatus };

import { formatRentBand, formatYen } from './format.ts';
import { formatOrientation, formatRoomFloor } from './room.ts';
import { FEATURE_TOGGLE_OPTIONS } from '../types.ts';

export interface ComparisonPropertyInput {
  id: number;
  title: string;
  /** Catalog effective min daily rent (yen/day) */
  catalogDailyYen?: number | null;
  /** Stay total estimate for current period */
  stayTotalYen?: number | null;
  stayDays?: number | null;
  layout?: string | null;
  areaM2?: number | null;
  /** 所在階 (min・地下は負数)。表示は lib/room.ts が導出する */
  floorNumber?: number | null;
  /** 所在階 (max・複数階「1・2階」のみ min と異なる) */
  floorNumberMax?: number | null;
  /** 向きの角度 0-359 (北=0・不明は null。bratto は常に null) */
  orientationDeg?: number | null;
  walkMinutes?: number | null;
  score?: number | null;
  address?: string | null;
  featureSummary?: string | null;
  campaignsActive?: string | null;
  shortlistStatus?: string | null;
  shortlistComment?: string | null;
  /** Agent legacy field: generic "rent" display value */
  rent?: number | null;
}

export interface ComparisonRowDef<T = ComparisonPropertyInput> {
  key: string;
  label: string;
  get: (p: T) => string;
  /** Highlight lowest numeric value across columns (price-like rows) */
  highlightMin?: boolean;
  /** Highlight highest numeric value (score, area) */
  highlightMax?: boolean;
  extractNumeric?: (p: T) => number | null;
}

/** Canonical rows for the side-by-side comparison board. */
export const COMPARISON_BOARD_ROWS: ComparisonRowDef[] = [
  {
    key: 'stayTotal',
    label: '期間総額',
    get: (p) => {
      if (p.stayTotalYen == null) return '—';
      const days = p.stayDays != null ? `（${p.stayDays}日）` : '';
      return `${formatYen(p.stayTotalYen)}${days}`;
    },
    highlightMin: true,
    extractNumeric: (p) => p.stayTotalYen ?? null,
  },
  {
    key: 'catalogDaily',
    label: 'カタログ日額',
    get: (p) => {
      if (p.catalogDailyYen != null) return `${formatYen(p.catalogDailyYen)}/日`;
      if (p.rent != null) return formatYen(p.rent);
      return '—';
    },
    highlightMin: true,
    extractNumeric: (p) => p.catalogDailyYen ?? p.rent ?? null,
  },
  {
    key: 'layout',
    label: '間取り',
    get: (p) => p.layout || '—',
  },
  {
    key: 'area',
    label: '面積',
    get: (p) => (p.areaM2 != null ? `${p.areaM2}㎡` : '—'),
    highlightMax: true,
    extractNumeric: (p) => p.areaM2 ?? null,
  },
  {
    key: 'floor',
    label: '所在階',
    get: (p) => formatRoomFloor(p.floorNumber, p.floorNumberMax) ?? '—',
  },
  {
    key: 'orientation',
    label: '向き',
    get: (p) => formatOrientation(p.orientationDeg) ?? '—',
  },
  {
    key: 'walk',
    label: '徒歩',
    get: (p) => (p.walkMinutes != null ? `${p.walkMinutes}分` : '—'),
    highlightMin: true,
    extractNumeric: (p) => p.walkMinutes ?? null,
  },
  {
    key: 'score',
    label: 'スコア',
    get: (p) => (p.score != null ? p.score.toFixed(1) : '—'),
    highlightMax: true,
    extractNumeric: (p) => p.score ?? null,
  },
  {
    key: 'campaigns',
    label: '有効CP',
    get: (p) => p.campaignsActive?.trim() || '—',
  },
  {
    key: 'features',
    label: '設備要約',
    get: (p) => {
      const f = p.featureSummary?.trim();
      if (!f) return '—';
      return f.length > 80 ? `${f.slice(0, 80)}…` : f;
    },
  },
  {
    key: 'comment',
    label: 'メモ',
    get: (p) => p.shortlistComment?.trim() || '—',
  },
  {
    key: 'status',
    label: '状態',
    get: (p) => fmtStatus(p.shortlistStatus),
  },
  {
    key: 'address',
    label: '住所',
    get: (p) => p.address || '—',
  },
];

/** Rows for agent showComparison (slightly leaner; includes stay total). */
export const AGENT_COMPARISON_ROWS: ComparisonRowDef[] = [
  {
    key: 'stayTotal',
    label: '期間総額',
    get: (p) => {
      if (p.stayTotalYen != null) {
        const days = p.stayDays != null ? `（${p.stayDays}日）` : '';
        return `${formatYen(p.stayTotalYen)}${days}`;
      }
      return '—';
    },
  },
  {
    key: 'rent',
    label: 'カタログ日額',
    get: (p) => {
      if (p.catalogDailyYen != null) return `${formatYen(p.catalogDailyYen)}/日`;
      if (p.rent != null) return formatYen(p.rent);
      return '—';
    },
  },
  {
    key: 'layout',
    label: '間取り',
    get: (p) => p.layout || '—',
  },
  {
    key: 'area',
    label: '面積',
    get: (p) => (p.areaM2 != null ? `${p.areaM2}㎡` : '—'),
  },
  {
    key: 'floor',
    label: '所在階',
    get: (p) => formatRoomFloor(p.floorNumber, p.floorNumberMax) ?? '—',
  },
  {
    key: 'orientation',
    label: '向き',
    get: (p) => formatOrientation(p.orientationDeg) ?? '—',
  },
  {
    key: 'walk',
    label: '徒歩',
    get: (p) => (p.walkMinutes != null ? `${p.walkMinutes}分` : '—'),
  },
  {
    key: 'score',
    label: 'スコア',
    get: (p) => (p.score != null ? p.score.toFixed(1) : '—'),
  },
  {
    key: 'address',
    label: '住所',
    get: (p) => p.address || '—',
  },
  {
    key: 'features',
    label: '設備',
    get: (p) => p.featureSummary || '—',
  },
  {
    key: 'status',
    label: '状態',
    get: (p) => fmtStatus(p.shortlistStatus),
  },
];

/**
 * For each row with highlightMin/Max, return the set of property ids that win.
 */
export function computeHighlightIds<T extends { id: number }>(
  properties: T[],
  rows: ComparisonRowDef<T>[],
): Record<string, Set<number>> {
  const out: Record<string, Set<number>> = {};
  for (const row of rows) {
    if (!row.extractNumeric || (!row.highlightMin && !row.highlightMax)) continue;
    const vals = properties
      .map((p) => ({ id: p.id, v: row.extractNumeric!(p) }))
      .filter((x): x is { id: number; v: number } => x.v != null && !Number.isNaN(x.v));
    if (vals.length < 2) continue;
    const target = row.highlightMin
      ? Math.min(...vals.map((x) => x.v))
      : Math.max(...vals.map((x) => x.v));
    out[row.key] = new Set(vals.filter((x) => x.v === target).map((x) => x.id));
  }
  return out;
}

export function activeCampaignSummary(
  campaigns:
    | { title?: string | null; campaign_type?: string | null }[]
    | undefined
    | null,
): string {
  // BE campaigns に is_active 列は無い(常時有効)。掲載中判定は日付で行う
  if (!campaigns?.length) return '';
  return campaigns
    .map((c) => c.title || c.campaign_type || 'CP')
    .filter(Boolean)
    .slice(0, 3)
    .join(' · ');
}

// ============================================================
// 建物比較行(Phase B2-δ / docs/building-aggregation-b2-fe-plan.md §4.5)
// ============================================================

/** 建物比較ボード 1 列分の入力(ComparisonBoard の建物タブから組立) */
export interface ComparisonBuildingInput {
  id: number;
  /** 建物代表名(canonical)。無名は住所等のフォールバックを呼び出し側で載せる */
  name: string;
  address?: string | null;
  builtYear?: number | null;
  structure?: string | null;
  /** 建物階数の表示(buildingFloorsLabel の出力。確定値「8階建」/下限「6階以上」)。無しは '—' */
  floorsLabel?: string | null;
  /** カンマ区切りの駅名要約(建物代表値) */
  stationSummary?: string | null;
  /** 建物設備の表示列(buildingFeaturesLabel の出力) */
  featuresLabel?: string | null;
  /** ソース一覧の表示列(source_sites のカンマ列挙) */
  sourceSitesLabel?: string | null;
  unitsCount?: number | null;
  activeUnitsCount?: number | null;
  minDailyRent?: number | null;
  maxDailyRent?: number | null;
  /** 最安部屋の 30 日換算総額(建物代表値) */
  minPlanTotal?: number | null;
  /** stay モード時の units 期間総額最安(カタログモードは null) */
  minStayTotalYen?: number | null;
  stayDays?: number | null;
  /** saved 部屋数(savedCountOf) */
  savedCount?: number | null;
  walkMinutes?: number | null;
}

/**
 * 建物設備の表示列。FE 語彙(FEATURE_TOGGLE_OPTIONS)で引ける code はラベル化し、
 * 未知の code は生値のままカンマ列挙する(計画 §4.5)。
 */
export function buildingFeaturesLabel(
  codes: readonly string[] | null | undefined,
): string {
  if (!codes?.length) return '';
  return codes
    .map((code) => FEATURE_TOGGLE_OPTIONS.find((o) => o.value === code)?.label ?? code)
    .join(', ');
}

/**
 * 建物比較の行定義(計画 §4.5 未決 3 への回答)。
 * 共通軸(住所〜ソース)→ 差分軸(部屋数〜徒歩)の順。ハイライトは最安帯・
 * 最安 30 日総額・期間総額最安・徒歩に適用(部屋版 computeHighlightIds を流用)。
 */
export const BUILDING_COMPARISON_ROWS: ComparisonRowDef<ComparisonBuildingInput>[] = [
  // ── 共通軸 ──
  {
    key: 'address',
    label: '住所',
    get: (b) => b.address || '—',
  },
  {
    key: 'builtYear',
    label: '築年',
    get: (b) => (b.builtYear != null ? `${b.builtYear}年` : '—'),
  },
  {
    key: 'structure',
    label: '構造',
    get: (b) => b.structure || '—',
  },
  {
    key: 'floors',
    label: '階数',
    // 表示導出の正本は lib/building.ts(確定値「N階建」/ 掲載部屋からの下限「N階以上」)
    get: (b) => b.floorsLabel || '—',
  },
  {
    key: 'access',
    label: 'アクセス',
    get: (b) => b.stationSummary || '—',
  },
  {
    key: 'features',
    label: '建物設備',
    get: (b) => {
      const f = b.featuresLabel?.trim();
      if (!f) return '—';
      return f.length > 80 ? `${f.slice(0, 80)}…` : f;
    },
  },
  {
    key: 'sources',
    label: 'ソース',
    get: (b) => b.sourceSitesLabel || '—',
  },
  // ── 差分軸 ──
  {
    key: 'unitsCount',
    label: '部屋数',
    get: (b) => `${b.activeUnitsCount ?? b.unitsCount ?? 0}/${b.unitsCount ?? 0}部屋`,
  },
  {
    key: 'rentBand',
    label: '最安日額帯',
    get: (b) => formatRentBand(b.minDailyRent, b.maxDailyRent),
    highlightMin: true,
    extractNumeric: (b) => b.minDailyRent ?? null,
  },
  {
    key: 'minPlanTotal',
    label: '最安30日総額',
    get: (b) => (b.minPlanTotal != null ? formatYen(b.minPlanTotal) : '—'),
    highlightMin: true,
    extractNumeric: (b) => b.minPlanTotal ?? null,
  },
  {
    key: 'stayTotal',
    label: '期間総額(最安)',
    get: (b) => {
      if (b.minStayTotalYen == null) return '—';
      const days = b.stayDays != null ? `（${b.stayDays}日）` : '';
      return `${formatYen(b.minStayTotalYen)}${days}`;
    },
    highlightMin: true,
    extractNumeric: (b) => b.minStayTotalYen ?? null,
  },
  {
    key: 'savedCount',
    label: 'saved部屋数',
    get: (b) => `${b.savedCount ?? 0}部屋`,
  },
  {
    key: 'walk',
    label: '徒歩',
    get: (b) => (b.walkMinutes != null ? `${b.walkMinutes}分` : '—'),
    highlightMin: true,
    extractNumeric: (b) => b.walkMinutes ?? null,
  },
];
