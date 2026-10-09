import { describe, expect, it } from 'vitest';
import { SHORTLIST_STATUS_VALUES } from '../types.ts';
import { fmtStatus, SHORTLIST_STATUS_LABELS } from './shortlist.ts';

describe('SHORTLIST_STATUS_LABELS', () => {
  it('ショートリスト状態4値を過不足なくカバーし、ラベルが空でない', () => {
    expect(Object.keys(SHORTLIST_STATUS_LABELS).sort()).toEqual(
      [...SHORTLIST_STATUS_VALUES].sort(),
    );
    for (const value of SHORTLIST_STATUS_VALUES) {
      expect(SHORTLIST_STATUS_LABELS[value].length).toBeGreaterThan(0);
    }
  });

  it('saved のラベルは「保存済」に統一されている', () => {
    expect(SHORTLIST_STATUS_LABELS.saved).toBe('保存済');
    expect(SHORTLIST_STATUS_LABELS.hide).toBe('非表示');
    expect(SHORTLIST_STATUS_LABELS.reject).toBe('見送り');
    expect(SHORTLIST_STATUS_LABELS.none).toBe('未分類');
  });
});

describe('fmtStatus', () => {
  it('null / undefined / 空文字 / none は「未分類」を返す', () => {
    expect(fmtStatus(null)).toBe('未分類');
    expect(fmtStatus(undefined)).toBe('未分類');
    expect(fmtStatus('')).toBe('未分類');
    expect(fmtStatus('none')).toBe('未分類');
  });

  it('既知の状態値は対応ラベルへ変換する', () => {
    expect(fmtStatus('saved')).toBe('保存済');
    expect(fmtStatus('hide')).toBe('非表示');
    expect(fmtStatus('reject')).toBe('見送り');
  });

  it('不明な値は生値をそのまま返す', () => {
    expect(fmtStatus('unknown_status')).toBe('unknown_status');
  });
});
