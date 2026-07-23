/**
 * Shared comparison row definitions for ComparisonBoard and showComparison GenUI.
 */

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

export interface ComparisonRowDef {
  key: string;
  label: string;
  get: (p: ComparisonPropertyInput) => string;
  /** Highlight lowest numeric value across columns (price-like rows) */
  highlightMin?: boolean;
  /** Highlight highest numeric value (score, area) */
  highlightMax?: boolean;
  extractNumeric?: (p: ComparisonPropertyInput) => number | null;
}

function fmtYen(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${n.toLocaleString()}円`;
}

function fmtStatus(s: string | null | undefined): string {
  if (!s || s === 'none') return '未分類';
  const map: Record<string, string> = {
    saved: '保存',
    hide: '非表示',
    reject: '見送り',
  };
  return map[s] ?? s;
}

/** Canonical rows for the side-by-side comparison board. */
export const COMPARISON_BOARD_ROWS: ComparisonRowDef[] = [
  {
    key: 'stayTotal',
    label: '期間総額',
    get: (p) => {
      if (p.stayTotalYen == null) return '—';
      const days = p.stayDays != null ? `（${p.stayDays}日）` : '';
      return `${fmtYen(p.stayTotalYen)}${days}`;
    },
    highlightMin: true,
    extractNumeric: (p) => p.stayTotalYen ?? null,
  },
  {
    key: 'catalogDaily',
    label: 'カタログ日額',
    get: (p) => {
      if (p.catalogDailyYen != null) return `${fmtYen(p.catalogDailyYen)}/日`;
      if (p.rent != null) return fmtYen(p.rent);
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
        return `${fmtYen(p.stayTotalYen)}${days}`;
      }
      return '—';
    },
  },
  {
    key: 'rent',
    label: 'カタログ日額',
    get: (p) => {
      if (p.catalogDailyYen != null) return `${fmtYen(p.catalogDailyYen)}/日`;
      if (p.rent != null) return fmtYen(p.rent);
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
export function computeHighlightIds(
  properties: ComparisonPropertyInput[],
  rows: ComparisonRowDef[],
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
    | { title?: string | null; is_active?: boolean; campaign_type?: string | null }[]
    | undefined
    | null,
): string {
  if (!campaigns?.length) return '';
  const active = campaigns.filter((c) => c.is_active !== false);
  if (!active.length) return '';
  return active
    .map((c) => c.title || c.campaign_type || 'CP')
    .filter(Boolean)
    .slice(0, 3)
    .join(' · ');
}
