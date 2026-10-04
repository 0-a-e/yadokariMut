/**
 * 滞在期間(チェックイン/チェックアウト)の既定値と localStorage 永続化。
 *
 * 旧 rentCalculator に同居していたが、アプリ全体の期間ポリシー
 * (フィルタ初期値・URL/リロード復元)と料金計算は関心事が異なるため分離。
 * 日付の実解析は rentCalculator の parseIsoDate を再利用する。
 */
import { parseIsoDate } from './rentCalculator.ts';

/** Default date range: check-in = first day of next month, check-out = one month later. */
export function defaultDateRange(today: Date = new Date()): { checkIn: string; checkOut: string } {
  const pad = (n: number) => String(n).padStart(2, '0');
  const toIso = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  // 来月1日 〜 その1ヶ月後（翌々月1日）
  const checkIn = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  const checkOut = new Date(today.getFullYear(), today.getMonth() + 2, 1);
  return { checkIn: toIso(checkIn), checkOut: toIso(checkOut) };
}

const RENT_SIM_DATE_STORAGE_KEY = 'yadokari:rent-sim:dates';
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE_RE.test(value)) return false;
  return parseIsoDate(value) != null;
}

/** Load simulator period from localStorage, or fall back to defaultDateRange(). */
export function loadStoredDateRange(today: Date = new Date()): {
  checkIn: string;
  checkOut: string;
} {
  try {
    if (typeof localStorage === 'undefined') return defaultDateRange(today);
    const raw = localStorage.getItem(RENT_SIM_DATE_STORAGE_KEY);
    if (!raw) return defaultDateRange(today);
    const parsed = JSON.parse(raw) as { checkIn?: unknown; checkOut?: unknown };
    const checkIn = typeof parsed.checkIn === 'string' ? parsed.checkIn : '';
    const checkOut = typeof parsed.checkOut === 'string' ? parsed.checkOut : '';
    if (!isValidIsoDate(checkIn) || !isValidIsoDate(checkOut)) {
      return defaultDateRange(today);
    }
    const start = parseIsoDate(checkIn)!;
    const end = parseIsoDate(checkOut)!;
    if (end.getTime() < start.getTime()) return defaultDateRange(today);
    return { checkIn, checkOut };
  } catch {
    return defaultDateRange(today);
  }
}

/** Persist simulator period for the next visit. */
export function saveStoredDateRange(checkIn: string, checkOut: string): void {
  try {
    if (typeof localStorage === 'undefined') return;
    if (!isValidIsoDate(checkIn) || !isValidIsoDate(checkOut)) return;
    localStorage.setItem(
      RENT_SIM_DATE_STORAGE_KEY,
      JSON.stringify({ checkIn, checkOut })
    );
  } catch {
    // quota / private mode — ignore
  }
}
