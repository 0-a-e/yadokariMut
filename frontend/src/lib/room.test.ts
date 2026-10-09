import { describe, expect, it } from 'vitest';
import {
  formatFloorRange,
  formatOrientation,
  formatRoomFloor,
  normalizeOrientationDeg,
  orientationRotationDeg,
  roomFloorLabel,
  roomOrientationLabel,
  unitFloorOf,
  WIND_LABELS_16,
} from './room.ts';

describe('formatOrientation(16 風位の逆引き)', () => {
  it('BE が保存する 16 風位の角度をすべてラベルへ戻せる', () => {
    // 正本: src/sources/parsing.py の _WIND_DEG_16(deg は 22.5 の半上げ整数化)
    const expected: Array<[number, string]> = [
      [0, '北'],
      [23, '北北東'],
      [45, '北東'],
      [68, '東北東'],
      [90, '東'],
      [113, '東南東'],
      [135, '南東'],
      [158, '南南東'],
      [180, '南'],
      [203, '南南西'],
      [225, '南西'],
      [248, '西南西'],
      [270, '西'],
      [293, '西北西'],
      [315, '北西'],
      [338, '北北西'],
    ];
    for (const [deg, label] of expected) {
      expect(formatOrientation(deg), `deg=${deg}`).toBe(label);
    }
  });

  it('境界は半上げ(round_half_up と同一規則)で解決する', () => {
    // 11.25 が北/北北東の境界。半上げなので北北東側へ倒れる
    expect(formatOrientation(11.25)).toBe('北北東');
    expect(formatOrientation(11)).toBe('北');
    // 349 は北(0°)寄り
    expect(formatOrientation(349)).toBe('北');
    expect(formatOrientation(359)).toBe('北');
  });

  it('null / 非数値は null(「北」と「不明」を混同しない)', () => {
    expect(formatOrientation(null)).toBeNull();
    expect(formatOrientation(undefined)).toBeNull();
    expect(formatOrientation(Number.NaN)).toBeNull();
  });

  it('WIND_LABELS_16 は 16 要素で北始まり(表示の正本)', () => {
    expect(WIND_LABELS_16).toHaveLength(16);
    expect(WIND_LABELS_16[0]).toBe('北');
    expect(WIND_LABELS_16[8]).toBe('南');
  });
});

describe('normalizeOrientationDeg / orientationRotationDeg', () => {
  it('0 ≤ deg < 360 へ折り返す(小数は保持)', () => {
    expect(normalizeOrientationDeg(135)).toBe(135);
    expect(normalizeOrientationDeg(360)).toBe(0);
    expect(normalizeOrientationDeg(-90)).toBe(270);
    expect(normalizeOrientationDeg(11.25)).toBe(11.25);
  });

  it('数値でなければ null(アイコンを描かないシグナル)', () => {
    expect(normalizeOrientationDeg(null)).toBeNull();
    expect(normalizeOrientationDeg(Number.POSITIVE_INFINITY)).toBeNull();
    expect(orientationRotationDeg(null)).toBeNull();
    expect(orientationRotationDeg(135)).toBe(135);
  });
});

describe('formatRoomFloor(所在階の表示)', () => {
  it('単一階は「5階」', () => {
    expect(formatRoomFloor(5, 5)).toBe('5階');
    expect(formatRoomFloor(5, null)).toBe('5階');
    expect(formatRoomFloor(5)).toBe('5階');
  });

  it('複数階は「1〜2階」(max > min のときのみ)', () => {
    expect(formatRoomFloor(1, 2)).toBe('1〜2階');
    // max が min 以下・不正なら単一表記へフォールバック
    expect(formatRoomFloor(2, 1)).toBe('2階');
    expect(formatRoomFloor(2, Number.NaN)).toBe('2階');
  });

  it('地下は「地下1階」', () => {
    expect(formatRoomFloor(-1, -1)).toBe('地下1階');
    expect(formatRoomFloor(-2, -1)).toBe('地下2階');
  });

  it('null / 0 は null(行ごと非表示にするシグナル)', () => {
    expect(formatRoomFloor(null, null)).toBeNull();
    expect(formatRoomFloor(0, 0)).toBeNull();
    expect(formatRoomFloor(Number.NaN, null)).toBeNull();
  });
});

describe('formatFloorRange(掲載部屋の階数レンジ)', () => {
  it('min〜max / 同一階は単一表記', () => {
    expect(formatFloorRange({ min: 1, max: 6 })).toBe('1〜6階');
    expect(formatFloorRange({ min: 3, max: 3 })).toBe('3階');
  });

  it('正の階数が無ければ null', () => {
    expect(formatFloorRange(null)).toBeNull();
    expect(formatFloorRange({ min: 0, max: 0 })).toBeNull();
  });
});

describe('unitFloorOf(建物階数導出用の畳み込み)', () => {
  it('floor_number_max を優先し、無ければ floor_number', () => {
    expect(unitFloorOf({ floor_number: 5, floor_number_max: 6 })).toBe(6);
    expect(unitFloorOf({ floor_number: 5, floor_number_max: null })).toBe(5);
    expect(unitFloorOf({ floor_number: null, floor_number_max: null })).toBeNull();
  });

  it('地下・0 は導出に使わない(建物階数の下限を汚さない)', () => {
    expect(unitFloorOf({ floor_number: -1, floor_number_max: null })).toBeNull();
    expect(unitFloorOf({ floor_number: 0, floor_number_max: 0 })).toBeNull();
  });
});

describe('roomFloorLabel / roomOrientationLabel(共通入口)', () => {
  it('units の生フィールドから表示用ラベルを作る', () => {
    expect(roomFloorLabel({ floor_number: 3, floor_number_max: 4 })).toBe('3〜4階');
    expect(roomOrientationLabel({ orientation_deg: 135 })).toBe('南東');
    expect(roomOrientationLabel({ orientation_deg: null })).toBeNull();
  });
});
