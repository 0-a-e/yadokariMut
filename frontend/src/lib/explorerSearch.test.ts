import { describe, expect, it } from 'vitest';
import {
  applyExplorerSearchPatch,
  compactExplorerSearch,
  explorerSearchForNavigate,
  parseCompareIds,
  parseExplorerSearch,
} from './explorerSearch.ts';

describe('parseCompareIds', () => {
  it('parses comma-separated ids and dedupes', () => {
    expect(parseCompareIds('3,1,3,2')).toEqual([3, 1, 2]);
  });

  it('caps at 5', () => {
    expect(parseCompareIds('1,2,3,4,5,6,7')).toEqual([1, 2, 3, 4, 5]);
  });

  it('parses JSON array form', () => {
    expect(parseCompareIds('[10,20]')).toEqual([10, 20]);
  });

  it('parses number array', () => {
    expect(parseCompareIds([5, 0, -1, 5, 8])).toEqual([5, 8]);
  });

  it('returns empty for junk', () => {
    expect(parseCompareIds('')).toEqual([]);
    expect(parseCompareIds('a,b')).toEqual([]);
    expect(parseCompareIds(null)).toEqual([]);
  });
});

describe('parseExplorerSearch', () => {
  it('accepts valid stay period and catalog mode', () => {
    expect(
      parseExplorerSearch({
        checkIn: '2026-08-01',
        checkOut: '2026-09-01',
        priceMode: 'catalog',
      }),
    ).toEqual({
      checkIn: '2026-08-01',
      checkOut: '2026-09-01',
      priceMode: 'catalog',
    });
  });

  it('drops inverted or invalid dates', () => {
    expect(
      parseExplorerSearch({ checkIn: '2026-09-01', checkOut: '2026-08-01' }),
    ).toEqual({});
    expect(parseExplorerSearch({ checkIn: 'not-a-date', checkOut: '2026-08-01' })).toEqual(
      {},
    );
    expect(parseExplorerSearch({ checkIn: '2026-08-01' })).toEqual({});
  });

  it('parses id, compare, view', () => {
    expect(
      parseExplorerSearch({
        id: '42',
        compare: '1,2,3',
        view: 'compare',
      }),
    ).toEqual({
      id: 42,
      compare: [1, 2, 3],
      view: 'compare',
    });
  });

  it('parses bcompare like compare (dedupe, cap 5, drop invalid)', () => {
    expect(parseExplorerSearch({ bcompare: '7,8,7,0,x,9,10,11,12,13' })).toEqual({
      bcompare: [7, 8, 9, 10, 11],
    });
    expect(parseExplorerSearch({ bcompare: '' })).toEqual({});
    expect(parseExplorerSearch({ bcompare: 'a' })).toEqual({});
  });

  it('ignores unknown view and bad id', () => {
    expect(parseExplorerSearch({ view: 'map', id: '0' })).toEqual({});
  });
});

describe('applyExplorerSearchPatch', () => {
  it('merges and clears with null', () => {
    const prev = parseExplorerSearch({
      checkIn: '2026-08-01',
      checkOut: '2026-09-01',
      id: 1,
      view: 'compare',
      compare: '1,2',
    });
    expect(
      applyExplorerSearchPatch(prev, { id: null, view: null, priceMode: 'catalog' }),
    ).toEqual({
      checkIn: '2026-08-01',
      checkOut: '2026-09-01',
      priceMode: 'catalog',
      compare: [1, 2],
    });
  });

  it('omits priceMode stay from compact result', () => {
    expect(applyExplorerSearchPatch({}, { priceMode: 'stay' })).toEqual({});
    expect(applyExplorerSearchPatch({ priceMode: 'catalog' }, { priceMode: 'stay' })).toEqual(
      {},
    );
  });

  it('updates compare list', () => {
    expect(
      applyExplorerSearchPatch({ compare: [1] }, { compare: [9, 8, 7] }),
    ).toEqual({ compare: [9, 8, 7] });
    expect(applyExplorerSearchPatch({ compare: [1] }, { compare: [] })).toEqual({});
  });

  it('updates and clears bcompare list', () => {
    expect(
      applyExplorerSearchPatch({ bcompare: [1] }, { bcompare: [9, 8] }),
    ).toEqual({ bcompare: [9, 8] });
    expect(applyExplorerSearchPatch({ bcompare: [1] }, { bcompare: null })).toEqual({});
    expect(applyExplorerSearchPatch({ bcompare: [1] }, { bcompare: [] })).toEqual({});
    // compare には影響しない(両立可・計画 §5)
    expect(
      applyExplorerSearchPatch({ compare: [1], bcompare: [2] }, { bcompare: [3] }),
    ).toEqual({ compare: [1], bcompare: [3] });
  });
});

describe('explorerSearchForNavigate', () => {
  it('serializes compare as comma string', () => {
    expect(
      explorerSearchForNavigate({
        compare: [1, 2, 3],
        priceMode: 'catalog',
        id: 9,
        view: 'compare',
        checkIn: '2026-08-01',
        checkOut: '2026-08-15',
      }),
    ).toEqual({
      compare: '1,2,3',
      priceMode: 'catalog',
      id: 9,
      view: 'compare',
      checkIn: '2026-08-01',
      checkOut: '2026-08-15',
    });
  });

  it('serializes bcompare as comma string and omits it when empty', () => {
    expect(
      explorerSearchForNavigate({ view: 'compare', bcompare: [4, 5] }),
    ).toEqual({ view: 'compare', bcompare: '4,5' });
    expect(explorerSearchForNavigate({ bcompare: [] })).toEqual({});
  });

  it('omits stay mode and empty fields', () => {
    expect(explorerSearchForNavigate({ priceMode: 'stay' })).toEqual({});
    expect(compactExplorerSearch({ priceMode: 'stay', compare: [] })).toEqual({});
  });
});

// ── Phase B2-γ: 建物選択 ?b= ──

describe('explorerSearch ?b=(建物選択・Phase B2-γ)', () => {
  it('b を正の整数で受ける', () => {
    expect(parseExplorerSearch({ b: '123' }).b).toBe(123);
    expect(parseExplorerSearch({ b: 45 }).b).toBe(45);
    expect(parseExplorerSearch({ b: 'abc' }).b).toBeUndefined();
    expect(parseExplorerSearch({ b: '-1' }).b).toBeUndefined();
  });

  it('id(部屋)と併用できる。patch で b を更新/クリアできる', () => {
    const base = parseExplorerSearch({ id: '10', b: '1' });
    expect(base).toMatchObject({ id: 10, b: 1 });
    const updated = applyExplorerSearchPatch(base, { b: 2 });
    expect(updated).toMatchObject({ id: 10, b: 2 });
    const cleared = applyExplorerSearchPatch(updated, { b: null });
    expect(cleared.b).toBeUndefined();
    expect(cleared.id).toBe(10);
  });

  it('compact/serialize に b が含まれる', () => {
    const nav = explorerSearchForNavigate(parseExplorerSearch({ b: '7' }));
    expect(nav.b).toBe(7);
  });
});
