import { describe, expect, it } from 'vitest';
import {
  applyExplorerSearchPatch,
  compactExplorerSearch,
  explorerSearchForNavigate,
  parseCompareIds,
  parseExplorerSearch,
} from './explorerSearch';

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

  it('omits stay mode and empty fields', () => {
    expect(explorerSearchForNavigate({ priceMode: 'stay' })).toEqual({});
    expect(compactExplorerSearch({ priceMode: 'stay', compare: [] })).toEqual({});
  });
});
