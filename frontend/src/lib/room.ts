/**
 * 部屋(room)単位の表示導出の正本
 * (docs/fe-floor-orientation-redesign-plan.md §4.2 / D6)。
 *
 * BE は生値のみを配信し(docs/floor-number-ssot-plan.md・docs/orientation-model-plan.md)、
 * 表示用の文字列化はここに一元化する。コンポーネント内で階数・方角の文字列を
 * 組み立てることは禁止(重複実装が A1〜A5 の温床になった経緯がある)。
 *
 * 入力は properties の整数列(floor_number / floor_number_max / orientation_deg)。
 */
import type { BuildingUnit, BuildingUnitProperties } from '../types.ts';

/**
 * 16 風位ラベル(北 = 0 起点・時計回り、22.5° 刻み)。
 * 正本: src/sources/parsing.py の `_WIND_DEG_16` の逆引き(deg が正・label は表示用)。
 */
export const WIND_LABELS_16 = [
  '北',
  '北北東',
  '北東',
  '東北東',
  '東',
  '東南東',
  '南東',
  '南南東',
  '南',
  '南南西',
  '南西',
  '西南西',
  '西',
  '西北西',
  '北西',
  '北北西',
] as const;

/** 1 風位あたりの角度(16 方位) */
const DEG_PER_WIND = 22.5;

/**
 * 向き角度の正規化。0 ≤ deg < 360 へ折り返し、数値でない値は null を返す
 * (小数は保持する。風位への丸めは表示側で 22.5° の半上げとして行う)。
 */
export function normalizeOrientationDeg(deg: number | null | undefined): number | null {
  if (deg == null || !Number.isFinite(deg)) return null;
  return ((deg % 360) + 360) % 360;
}
/**
 * 向き角度 → 16 風位ラベル(例: 135 → 「南東」)。
 *
 * 丸めは BE `sources.parsing.round_half_up` と同一規則(22.5° の半上げ)で、
 * 保存値と表示が食い違わないようにする(docs/orientation-model-plan.md D7)。
 * null / 非数値は null(「北」と「不明」を混同しない)。
 */
export function formatOrientation(deg: number | null | undefined): string | null {
  const normalized = normalizeOrientationDeg(deg);
  if (normalized == null) return null;
  const index = Math.floor(normalized / DEG_PER_WIND + 0.5);
  return WIND_LABELS_16[((index % 16) + 16) % 16];
}

/**
 * 方位アイコンの回転角(北 = 0 の時計回り)。CSS の `rotate()` にそのまま渡す。
 * 不明は null(アイコンを描かない)。
 */
export function orientationRotationDeg(deg: number | null | undefined): number | null {
  return normalizeOrientationDeg(deg);
}

/**
 * 所在階の表示(例: 5階 / 地下1階 / 1〜2階)。
 *
 * - 地下は `地下N階`(parse_floor_text が負数で表現する)
 * - `floorMax` が `floor` より大きい場合のみ複数階表記(「1・2階」のようなレンジ)
 * - 0 / 不明 / 非数値は null(行ごと非表示にするためのシグナル。空欄プレースホルダを出さない)
 */
export function formatRoomFloor(
  floor: number | null | undefined,
  floorMax?: number | null,
): string | null {
  if (floor == null || !Number.isFinite(floor) || floor === 0) return null;
  if (floor < 0) return `地下${-floor}階`;
  const max = floorMax != null && Number.isFinite(floorMax) && floorMax > floor ? floorMax : null;
  return max == null ? `${floor}階` : `${floor}〜${max}階`;
}

/**
 * 掲載部屋の階数レンジ表示(例: 「1〜6階」)。建物パネルの「掲載部屋」行で使う。
 * 地下・不明は対象外(正の階数のみ)。該当なしは null。
 */
export function formatFloorRange(range: { min: number; max: number } | null): string | null {
  if (!range) return null;
  const { min, max } = range;
  if (min <= 0 || max <= 0) return null;
  return min === max ? `${min}階` : `${min}〜${max}階`;
}

/** 部屋 1 件の階数(所在階・複数階の上限)を 1 つの整数へ畳む(建物階数の導出用) */
export function unitFloorOf(
  unit: Pick<BuildingUnitProperties, 'floor_number' | 'floor_number_max'>,
): number | null {
  const max = unit.floor_number_max;
  if (max != null && Number.isFinite(max) && max > 0) return max;
  const min = unit.floor_number;
  return min != null && Number.isFinite(min) && min > 0 ? min : null;
}

/** 部屋 1 件の所在階表示(RoomRow / 詳細スペック / 比較行の共通入口) */
export function roomFloorLabel(unit: Pick<BuildingUnit, 'floor_number' | 'floor_number_max'>): string | null {
  return formatRoomFloor(unit.floor_number, unit.floor_number_max);
}

/** 部屋 1 件の向き表示(共通入口) */
export function roomOrientationLabel(unit: Pick<BuildingUnit, 'orientation_deg'>): string | null {
  return formatOrientation(unit.orientation_deg);
}
