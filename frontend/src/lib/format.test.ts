import { describe, expect, it } from 'vitest';
import {
  formatYen,
  formatYenCompact,
  formatDailyRentDisplay,
  formatPlanTotalDisplay,
  formatPriceDisplay,
  formatStayHeader,
  hasStayEstimate,
} from './format.ts';
import { formatRentBand } from './format.ts';
import type { StayEstimateSummary } from '../types.ts';

/** StayEstimateSummary のテストファクトリ(未指定フィールドの既定は表示不能側に倒す) */
function makeEst(overrides: Partial<StayEstimateSummary> = {}): StayEstimateSummary {
  return {
    ok: true,
    stayDays: 30,
    stayTotalYen: 180_000,
    rentDailyYen: 6_000,
    selectedPlanCode: 'short',
    usedFallback: false,
    planLabel: 'ショート',
    ...overrides,
  };
}

describe('formatYen', () => {
  it('正数を「N,NNN円」に整形する', () => {
    expect(formatYen(1234567)).toBe('1,234,567円');
    expect(formatYen(980)).toBe('980円');
  });

  it('0 を「0円」に整形する', () => {
    expect(formatYen(0)).toBe('0円');
  });

  it('負数も符号付きで整形する', () => {
    expect(formatYen(-1500)).toBe('-1,500円');
  });

  it('null / undefined は既定 fallback「—」を返す', () => {
    expect(formatYen(null)).toBe('—');
    expect(formatYen(undefined)).toBe('—');
  });

  it('NaN は既定 fallback「—」を返す', () => {
    expect(formatYen(Number.NaN)).toBe('—');
  });

  it('fallback を指定できる', () => {
    expect(formatYen(null, '不明')).toBe('不明');
    expect(formatYen(undefined, '-')).toBe('-');
    expect(formatYen(Number.NaN, 'N/A')).toBe('N/A');
  });

  it('有効な数値は fallback を無視する', () => {
    expect(formatYen(500, '不明')).toBe('500円');
  });
});

describe('formatYenCompact', () => {
  it('円単位を付けず桁区切りのみ整形する(チャート軸用)', () => {
    expect(formatYenCompact(1234567)).toBe('1,234,567');
    expect(formatYenCompact(0)).toBe('0');
    expect(formatYenCompact(-980)).toBe('-980');
  });
});

describe('hasStayEstimate', () => {
  it('ok かつ stayTotalYen があるとき true', () => {
    expect(hasStayEstimate(makeEst())).toBe(true);
  });

  it('ok=false / 総額なし / null / 未指定のとき false', () => {
    expect(hasStayEstimate(makeEst({ ok: false }))).toBe(false);
    expect(hasStayEstimate(makeEst({ stayTotalYen: null }))).toBe(false);
    expect(hasStayEstimate(null)).toBe(false);
    expect(hasStayEstimate(undefined)).toBe(false);
  });
});

describe('formatStayHeader', () => {
  it('表示可能な stay 試算から「N,NNN円（D日）」を作る', () => {
    expect(formatStayHeader(makeEst({ stayTotalYen: 123_456, stayDays: 45 }))).toBe(
      '123,456円（45日）',
    );
  });

  it('表示不能な stay 試算は null', () => {
    expect(formatStayHeader(makeEst({ ok: false }))).toBeNull();
    expect(formatStayHeader(makeEst({ stayTotalYen: null }))).toBeNull();
    expect(formatStayHeader(undefined)).toBeNull();
  });
});

describe('formatDailyRentDisplay', () => {
  it('日額から「N,NNN円/日」を作る', () => {
    expect(formatDailyRentDisplay(6_800)).toBe('6,800円/日');
  });

  it('0 / null / undefined は「詳細参照」', () => {
    expect(formatDailyRentDisplay(0)).toBe('詳細参照');
    expect(formatDailyRentDisplay(null)).toBe('詳細参照');
    expect(formatDailyRentDisplay(undefined)).toBe('詳細参照');
  });
});

describe('formatPlanTotalDisplay', () => {
  it('総額から「(総額:N,NNN円)」を作る', () => {
    expect(formatPlanTotalDisplay(234_567)).toBe('(総額:234,567円)');
  });

  it('0 / null / undefined は空文字', () => {
    expect(formatPlanTotalDisplay(0)).toBe('');
    expect(formatPlanTotalDisplay(null)).toBe('');
    expect(formatPlanTotalDisplay(undefined)).toBe('');
  });
});

describe('formatPriceDisplay', () => {
  it('stay 試算が有効なら期間総額を最優先する(日額があっても stay を返す)', () => {
    expect(
      formatPriceDisplay({ stayEst: makeEst(), minDailyRent: 6_000 }),
    ).toBe('180,000円（30日）');
  });

  it('stay 試算が無効ならカタログ日額にフォールバックする', () => {
    expect(
      formatPriceDisplay({ stayEst: makeEst({ ok: false }), minDailyRent: 6_800 }),
    ).toBe('6,800円/日');
    expect(
      formatPriceDisplay({
        stayEst: makeEst({ stayTotalYen: null }),
        minDailyRent: 6_800,
      }),
    ).toBe('6,800円/日');
    expect(formatPriceDisplay({ stayEst: null, minDailyRent: 6_800 })).toBe('6,800円/日');
  });

  it('stay 試算も日額も無ければ「詳細参照」', () => {
    expect(formatPriceDisplay({ stayEst: makeEst({ ok: false }), minDailyRent: 0 })).toBe(
      '詳細参照',
    );
    expect(formatPriceDisplay({})).toBe('詳細参照');
  });

  it('minPlanTotal は 1 行表示に含めない(総額は呼び出し側で formatPlanTotalDisplay と組む)', () => {
    expect(
      formatPriceDisplay({ minDailyRent: 6_800, minPlanTotal: 234_567 }),
    ).toBe('6,800円/日');
  });
});

describe('formatRentBand(建物最安〜最高帯・Phase B2)', () => {
  it('min == max(または max 欠損)は単値表示', () => {
    expect(formatRentBand(4800, 4800)).toBe('4,800円/日');
    expect(formatRentBand(4800, null)).toBe('4,800円/日');
  });

  it('min < max は帯表示。min 欠損は上限のみ', () => {
    expect(formatRentBand(4800, 7500)).toBe('4,800円〜7,500円/日');
    expect(formatRentBand(null, 7500)).toBe('〜7,500円/日');
  });

  it('両方欠損は「—/日」', () => {
    expect(formatRentBand(null, null)).toBe('—/日');
  });
});
