import { describe, expect, it } from 'vitest';
import {
  AGENT_COMPARISON_ROWS,
  BUILDING_COMPARISON_ROWS,
  COMPARISON_BOARD_ROWS,
  buildingFeaturesLabel,
  computeHighlightIds,
  type ComparisonBuildingInput,
} from './comparisonRows.ts';

function getRow<T extends { key: string }>(rows: readonly T[], key: string): T {
  const row = rows.find((r) => r.key === key);
  if (!row) throw new Error(`row not found: ${key}`);
  return row;
}

describe('AGENT_COMPARISON_ROWS', () => {
  it('状態行は fmtStatus 経由でラベル変換される(生値を表示しない)', () => {
    const row = getRow(AGENT_COMPARISON_ROWS, 'status');
    expect(row.get({ id: 1, title: 'x', shortlistStatus: 'saved' })).toBe('保存済');
    expect(row.get({ id: 1, title: 'x', shortlistStatus: 'reject' })).toBe('見送り');
    expect(row.get({ id: 1, title: 'x', shortlistStatus: 'none' })).toBe('未分類');
    expect(row.get({ id: 1, title: 'x' })).toBe('未分類');
  });

  it('カタログ日額行は catalogDailyYen を優先し rent にフォールバックする', () => {
    const row = getRow(AGENT_COMPARISON_ROWS, 'rent');
    expect(row.get({ id: 1, title: 'x', catalogDailyYen: 5000 })).toBe('5,000円/日');
    expect(row.get({ id: 1, title: 'x', rent: 7000 })).toBe('7,000円');
    expect(row.get({ id: 1, title: 'x' })).toBe('—');
  });

  it('期間総額行は日数付きで整形する', () => {
    const row = getRow(AGENT_COMPARISON_ROWS, 'stayTotal');
    expect(row.get({ id: 1, title: 'x', stayTotalYen: 120000, stayDays: 30 })).toBe(
      '120,000円（30日）',
    );
    expect(row.get({ id: 1, title: 'x' })).toBe('—');
  });
});

describe('COMPARISON_BOARD_ROWS', () => {
  it('最高値ハイライト対象の id 集合を計算する', () => {
    const scoreRow = getRow(COMPARISON_BOARD_ROWS, 'score');
    const ids = computeHighlightIds(
      [
        { id: 1, title: 'a', score: 3.2 },
        { id: 2, title: 'b', score: 4.8 },
        { id: 3, title: 'c', score: 4.8 },
      ],
      [scoreRow],
    );
    expect([...(ids['score'] ?? [])].sort()).toEqual([2, 3]);
  });

  // ── 所在階・向き(§4.2 / §6.2) ── raw 値から lib/room.ts が表示を導出する ──
  it('所在階行は floorNumber/floorNumberMax を表示し、欠損は —', () => {
    const row = getRow(COMPARISON_BOARD_ROWS, 'floor');
    expect(row.get({ id: 1, title: 'x', floorNumber: 5, floorNumberMax: 5 })).toBe('5階');
    expect(row.get({ id: 1, title: 'x', floorNumber: -1 })).toBe('地下1階');
    expect(row.get({ id: 1, title: 'x', floorNumber: 1, floorNumberMax: 2 })).toBe('1〜2階');
    expect(row.get({ id: 1, title: 'x', floorNumber: null })).toBe('—');
    expect(row.get({ id: 1, title: 'x' })).toBe('—');
  });

  it('向き行は orientationDeg を 16 風位へ表示し、欠損(bratto は常に null)は —', () => {
    const row = getRow(COMPARISON_BOARD_ROWS, 'orientation');
    expect(row.get({ id: 1, title: 'x', orientationDeg: 135 })).toBe('南東');
    expect(row.get({ id: 1, title: 'x', orientationDeg: 0 })).toBe('北');
    expect(row.get({ id: 1, title: 'x', orientationDeg: null })).toBe('—');
    expect(row.get({ id: 1, title: 'x' })).toBe('—');
  });

  it('agent 比較行にも所在階・向きが載る(units の raw 値をそのまま渡せる)', () => {
    const floorRow = getRow(AGENT_COMPARISON_ROWS, 'floor');
    const orientationRow = getRow(AGENT_COMPARISON_ROWS, 'orientation');
    expect(floorRow.get({ id: 1, title: 'x', floorNumber: 3, floorNumberMax: 3 })).toBe('3階');
    expect(orientationRow.get({ id: 1, title: 'x', orientationDeg: 203 })).toBe('南南西');
    expect(orientationRow.get({ id: 1, title: 'x', orientationDeg: null })).toBe('—');
  });
});

// ── 建物比較行(Phase B2-δ §4.5) ──

function bInput(id: number, partial: Partial<ComparisonBuildingInput> = {}): ComparisonBuildingInput {
  return {
    id,
    name: `Building${id}`,
    address: '東京都多摩市永山1-1',
    builtYear: 2015,
    structure: 'RC',
    floorsLabel: '8階建',
    stationSummary: '渋谷, 新宿',
    featuresLabel: 'エレベーター, 宅配BOX',
    sourceSitesLabel: 'unionmonthly, bratto',
    unitsCount: 5,
    activeUnitsCount: 3,
    minDailyRent: 4800,
    maxDailyRent: 7500,
    minPlanTotal: 144000,
    savedCount: 1,
    walkMinutes: 7,
    ...partial,
  };
}

describe('buildingFeaturesLabel', () => {
  it('FE 語彙で引ける code はラベル化し、未知 code は生値のままカンマ列挙する', () => {
    expect(buildingFeaturesLabel(['elevator', 'unknown_code'])).toBe(
      'エレベーター, unknown_code',
    );
  });

  it('空配列 / null / undefined は空文字', () => {
    expect(buildingFeaturesLabel([])).toBe('');
    expect(buildingFeaturesLabel(null)).toBe('');
    expect(buildingFeaturesLabel(undefined)).toBe('');
  });
});

describe('BUILDING_COMPARISON_ROWS', () => {
  it('部屋数行は active/全 の形で返す', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'unitsCount');
    expect(row.get(bInput(1))).toBe('3/5部屋');
    expect(row.get(bInput(2, { activeUnitsCount: null, unitsCount: null }))).toBe('0/0部屋');
  });

  it('最安日額帯行は formatRentBand の帯表示(同値は単値・欠損はプレースホルダ)', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'rentBand');
    expect(row.get(bInput(1))).toBe('4,800円〜7,500円/日');
    expect(row.get(bInput(2, { minDailyRent: 5000, maxDailyRent: 5000 }))).toBe('5,000円/日');
    expect(row.get(bInput(3, { minDailyRent: null, maxDailyRent: null }))).toBe('—/日');
  });

  it('最安30日総額行と saved 部屋数行を整形する', () => {
    expect(getRow(BUILDING_COMPARISON_ROWS, 'minPlanTotal').get(bInput(1))).toBe('144,000円');
    expect(
      getRow(BUILDING_COMPARISON_ROWS, 'minPlanTotal').get(bInput(2, { minPlanTotal: null })),
    ).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'savedCount').get(bInput(1))).toBe('1部屋');
  });

  it('期間総額(最安)行は日数付き。stay モード外(null)は —', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'stayTotal');
    expect(row.get(bInput(1, { minStayTotalYen: 210000, stayDays: 30 }))).toBe(
      '210,000円（30日）',
    );
    expect(row.get(bInput(1))).toBe('—');
  });

  it('共通軸の欠損は — に落ちる', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'builtYear');
    expect(row.get(bInput(1, { builtYear: null }))).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'structure').get(bInput(1, { structure: null }))).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'floors').get(bInput(1, { floorsLabel: null }))).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'address').get(bInput(1, { address: null }))).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'access').get(bInput(1, { stationSummary: '' }))).toBe('—');
    expect(getRow(BUILDING_COMPARISON_ROWS, 'sources').get(bInput(1, { sourceSitesLabel: '' }))).toBe('—');
  });

  it('最良ハイライト: 最安日額帯(=min_daily_rent)・徒歩の最小 id 集合を計算する', () => {
    const highlights = computeHighlightIds(
      [
        bInput(1, { minDailyRent: 5200, walkMinutes: 9 }),
        bInput(2, { minDailyRent: 4800, walkMinutes: 7 }),
        bInput(3, { minDailyRent: 4800, walkMinutes: 12 }),
      ],
      BUILDING_COMPARISON_ROWS,
    );
    expect([...(highlights['rentBand'] ?? [])].sort()).toEqual([2, 3]);
    expect(highlights['walk']).toEqual(new Set([2]));
    // stay 未指定カラムはハイライト対象外
    expect(highlights['stayTotal']).toBeUndefined();
  });

  it('建物設備行は 80 字で打ち切る', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'features');
    const long = Array.from({ length: 20 }, (_, i) => `f${i}`).join(', ');
    expect(row.get(bInput(1, { featuresLabel: long }))).toBe(`${long.slice(0, 80)}…`);
  });

  // ── 階数(buildingFloorsLabel の出力。確定値 / 下限。§5) ──
  it('階数行は floorsLabel(確定値「8階建」/ 下限「6階以上」)をそのまま表示し、欠損は —', () => {
    const row = getRow(BUILDING_COMPARISON_ROWS, 'floors');
    expect(row.get(bInput(1, { floorsLabel: '8階建' }))).toBe('8階建');
    // unionmonthly 建物は building_floors が無く、掲載部屋の最高階からの下限表記になる
    expect(row.get(bInput(2, { floorsLabel: '6階以上' }))).toBe('6階以上');
    expect(row.get(bInput(3, { floorsLabel: null }))).toBe('—');
  });
});
