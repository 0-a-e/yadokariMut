import { describe, expect, it } from 'vitest';
import { defaultDateRange } from './stayDates.ts';

describe('defaultDateRange', () => {
  it('uses next month start through the following month start', () => {
    const r = defaultDateRange(new Date(2026, 6, 20)); // 2026-07-20
    expect(r.checkIn).toBe('2026-08-01');
    expect(r.checkOut).toBe('2026-09-01');
  });

  it('rolls over the year in December', () => {
    const r = defaultDateRange(new Date(2026, 11, 15)); // 2026-12-15
    expect(r.checkIn).toBe('2027-01-01');
    expect(r.checkOut).toBe('2027-02-01');
  });
});
