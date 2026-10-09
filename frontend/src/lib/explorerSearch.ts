/**
 * Explorer URL search-param model (TanStack Router Phase R1).
 *
 * Keys: checkIn, checkOut, priceMode, id, b, compare, bcompare, view
 * - Dates / priceMode: history.replace
 * - id / b open / view=compare open: history.push
 * - Priority for dates: URL > localStorage > default
 * - compare is an explicit ID list (not shortlist-only), max 5
 * - b is the selected building id (Phase B2-γ: 建物パネル。id(部屋)と併用可)
 * - bcompare is the building-comparison counterpart of compare (Phase B2-δ, §4.5)
 */
import { parseIsoDate } from './rentCalculator.ts';

export const EXPLORER_MAX_COMPARE = 5;

export type ExplorerPriceMode = 'stay' | 'catalog';
export type ExplorerView = 'compare';

/** Validated search shape for `/`. All fields optional (omit = default). */
export interface ExplorerSearch {
  checkIn?: string;
  checkOut?: string;
  priceMode?: ExplorerPriceMode;
  id?: number;
  /** Selected building id(建物パネル・Phase B2-γ)。id(部屋)と併用可 */
  b?: number;
  /** Explicit comparison property ids (order preserved, max 5). */
  compare?: number[];
  /** Explicit comparison building ids (order preserved, max 5). Phase B2-δ §4.5. */
  bcompare?: number[];
  view?: ExplorerView;
}

function parsePositiveInt(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value.trim());
    if (Number.isInteger(n) && n > 0) return n;
  }
  return undefined;
}

/** Parse compare from string "1,2,3", JSON array, or single number. */
export function parseCompareIds(value: unknown): number[] {
  let parts: unknown[] = [];
  if (value == null || value === '') return [];
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return [];
    // JSON array form from TanStack default stringify: "[1,2,3]"
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed) as unknown;
        if (Array.isArray(parsed)) parts = parsed;
        else parts = [parsed];
      } catch {
        parts = trimmed.split(',');
      }
    } else {
      parts = trimmed.split(',');
    }
  } else if (Array.isArray(value)) {
    parts = value;
  } else {
    parts = [value];
  }

  const ids: number[] = [];
  const seen = new Set<number>();
  for (const p of parts) {
    const n = parsePositiveInt(typeof p === 'string' ? p.trim() : p);
    if (n == null || seen.has(n)) continue;
    seen.add(n);
    ids.push(n);
    if (ids.length >= EXPLORER_MAX_COMPARE) break;
  }
  return ids;
}

export function normalizeCompareIds(ids: number[]): number[] {
  return parseCompareIds(ids);
}

/**
 * Normalize raw URL search into ExplorerSearch.
 * Invalid values are dropped (never throws).
 */
export function parseExplorerSearch(
  raw: Record<string, unknown>,
): ExplorerSearch {
  const result: ExplorerSearch = {};

  // 日付の妥当性判定は rentCalculator の parseIsoDate に一元化
  // (stayDates.isValidIsoDate と同じ委譲パターン。閏日等の実在日チェックを含む)
  const checkIn =
    typeof raw.checkIn === 'string' && parseIsoDate(raw.checkIn) != null
      ? raw.checkIn
      : undefined;
  const checkOut =
    typeof raw.checkOut === 'string' && parseIsoDate(raw.checkOut) != null
      ? raw.checkOut
      : undefined;
  if (checkIn && checkOut && checkIn <= checkOut) {
    result.checkIn = checkIn;
    result.checkOut = checkOut;
  }

  if (raw.priceMode === 'stay' || raw.priceMode === 'catalog') {
    result.priceMode = raw.priceMode;
  }

  const id = parsePositiveInt(raw.id);
  if (id != null) result.id = id;

  const b = parsePositiveInt(raw.b);
  if (b != null) result.b = b;

  const compare = parseCompareIds(raw.compare);
  if (compare.length > 0) result.compare = compare;

  const bcompare = parseCompareIds(raw.bcompare);
  if (bcompare.length > 0) result.bcompare = bcompare;

  if (raw.view === 'compare') result.view = 'compare';

  return result;
}

/** Patch applied to explorer search (undefined = leave, null = clear). */
export type ExplorerSearchPatch = {
  checkIn?: string | null;
  checkOut?: string | null;
  priceMode?: ExplorerPriceMode | null;
  id?: number | null;
  b?: number | null;
  compare?: number[] | null;
  bcompare?: number[] | null;
  view?: ExplorerView | null;
};

/**
 * Merge patch into previous search, then strip empties / defaults for clean URLs.
 * priceMode=stay is omitted; empty compare/view/id omitted.
 */
export function applyExplorerSearchPatch(
  prev: ExplorerSearch,
  patch: ExplorerSearchPatch,
): ExplorerSearch {
  const next: ExplorerSearch = { ...prev };

  if (patch.checkIn !== undefined) {
    if (patch.checkIn == null) delete next.checkIn;
    else next.checkIn = patch.checkIn;
  }
  if (patch.checkOut !== undefined) {
    if (patch.checkOut == null) delete next.checkOut;
    else next.checkOut = patch.checkOut;
  }
  if (patch.priceMode !== undefined) {
    if (patch.priceMode == null) delete next.priceMode;
    else next.priceMode = patch.priceMode;
  }
  if (patch.id !== undefined) {
    if (patch.id == null) delete next.id;
    else next.id = patch.id;
  }
  if (patch.b !== undefined) {
    if (patch.b == null) delete next.b;
    else next.b = patch.b;
  }
  if (patch.compare !== undefined) {
    if (patch.compare == null) delete next.compare;
    else {
      const ids = normalizeCompareIds(patch.compare);
      if (ids.length) next.compare = ids;
      else delete next.compare;
    }
  }
  if (patch.bcompare !== undefined) {
    if (patch.bcompare == null) delete next.bcompare;
    else {
      const ids = normalizeCompareIds(patch.bcompare);
      if (ids.length) next.bcompare = ids;
      else delete next.bcompare;
    }
  }
  if (patch.view !== undefined) {
    if (patch.view == null) delete next.view;
    else next.view = patch.view;
  }

  // Keep date pair consistent
  if (next.checkIn && next.checkOut && next.checkIn > next.checkOut) {
    delete next.checkIn;
    delete next.checkOut;
  } else if ((next.checkIn && !next.checkOut) || (!next.checkIn && next.checkOut)) {
    // incomplete pair — drop both from URL
    delete next.checkIn;
    delete next.checkOut;
  }

  return compactExplorerSearch(next);
}

/** Drop default-ish values so shared URLs stay short. */
export function compactExplorerSearch(search: ExplorerSearch): ExplorerSearch {
  const out: ExplorerSearch = {};
  if (search.checkIn) out.checkIn = search.checkIn;
  if (search.checkOut) out.checkOut = search.checkOut;
  if (search.priceMode && search.priceMode !== 'stay') {
    out.priceMode = search.priceMode;
  }
  if (search.id != null) out.id = search.id;
  if (search.b != null) out.b = search.b;
  if (search.compare?.length) out.compare = search.compare;
  if (search.bcompare?.length) out.bcompare = search.bcompare;
  if (search.view === 'compare') out.view = 'compare';
  return out;
}

/**
 * Serialize for navigate(). Arrays become comma strings so URLs look like
 * `?compare=1,2,3` instead of JSON-encoded arrays.
 */
export function explorerSearchForNavigate(
  search: ExplorerSearch,
): Record<string, string | number> {
  const compact = compactExplorerSearch(search);
  const out: Record<string, string | number> = {};
  if (compact.checkIn) out.checkIn = compact.checkIn;
  if (compact.checkOut) out.checkOut = compact.checkOut;
  if (compact.priceMode) out.priceMode = compact.priceMode;
  if (compact.id != null) out.id = compact.id;
  if (compact.b != null) out.b = compact.b;
  if (compact.compare?.length) out.compare = compact.compare.join(',');
  if (compact.bcompare?.length) out.bcompare = compact.bcompare.join(',');
  if (compact.view) out.view = compact.view;
  return out;
}
