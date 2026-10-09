/**
 * ショートリスト状態の表示語彙の正本。
 *
 * 値リスト(union 正本)は types.ts (SHORTLIST_STATUS_VALUES) に置き、
 * このモジュールは状態値 → 表示ラベルの対応と、
 * shortlist_status 生値の表示用変換 (fmtStatus) を一元管理する。
 */
import type { ShortlistStatus } from '../types.ts';

/** ショートリスト状態の表示ラベル正本(saved は「保存済」に統一) */
export const SHORTLIST_STATUS_LABELS: Record<ShortlistStatus, string> = {
  saved: '保存済',
  hide: '非表示',
  reject: '見送り',
  none: '未分類',
};

/**
 * shortlist_status 生値を表示ラベルへ変換する。
 * 空値 / 'none' は「未分類」。不明な値は生値をそのまま返す(既存挙動維持)。
 */
export function fmtStatus(s: string | null | undefined): string {
  if (!s || s === 'none') return '未分類';
  return SHORTLIST_STATUS_LABELS[s as ShortlistStatus] ?? s;
}
