/**
 * Explorer URL search-param model (TanStack Router Phase R1).
 *
 * Keys: checkIn, checkOut, priceMode, id, compare, view
 * - Dates / priceMode: history.replace
 * - id open / view=compare open: history.push
 * - Priority for dates: URL > localStorage > default
 * - compare is an explicit ID list (not shortlist-only), max 5
 */

export const EXPLORER_MAX_COMPARE = 5;

export type ExplorerPriceMode = 'stay' | 'catalog';
export type ExplorerView = 'compare';

/** Validated search shape for `/`. All fields optional (omit = default). */
export interface ExplorerSearch {
  checkIn?: string;
  checkOut?: string;
  priceMode?: ExplorerPriceMode;
  id?: number;
  /** Explicit comparison property ids (order preserved, max 5). */
  compare?: number[];
  view?: ExplorerView;
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isIsoDate(value: string): boolean {
  if (!ISO_DATE_RE.test(value)) return false;
  const [y, m, d] = value.split('-').map(Number);
  if (!y || !m || !d) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
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

  const checkIn =
    typeof raw.checkIn === 'string' && isIsoDate(raw.checkIn)
      ? raw.checkIn
      : undefined;
  const checkOut =
    typeof raw.checkOut === 'string' && isIsoDate(raw.checkOut)
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

  const compare = parseCompareIds(raw.compare);
  if (compare.length > 0) result.compare = compare;

  if (raw.view === 'compare') result.view = 'compare';

  return result;
}

/** Patch applied to explorer search (undefined = leave, null = clear). */
export type ExplorerSearchPatch = {
  checkIn?: string | null;
  checkOut?: string | null;
  priceMode?: ExplorerPriceMode | null;
  id?: number | null;
  compare?: number[] | null;
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
  if (patch.compare !== undefined) {
    if (patch.compare == null) delete next.compare;
    else {
      const ids = normalizeCompareIds(patch.compare);
      if (ids.length) next.compare = ids;
      else delete next.compare;
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
  if (search.compare?.length) out.compare = search.compare;
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
  if (compact.compare?.length) out.compare = compact.compare.join(',');
  if (compact.view) out.view = compact.view;
  return out;
}
