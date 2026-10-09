import type { BuildingFeature, BuildingUnit, PropertyFeature } from '../types.ts';
import { isListed } from './filterLogic.ts';

/** エクスポート範囲 (表示中=フィルタ適用済み / 全物件) */
export type ExportScope = 'filtered' | 'all';

export interface ExportOptions {
  scope: ExportScope;
  /** 掲載終了 (is_active=false) を対象に含めるか */
  includeInactive: boolean;
}

/**
 * エクスポート対象のフィーチャーを選ぶ (元リストの順序を維持)。
 * scope='filtered' は表示中 (フィルタ適用済み) リスト、'all' は全物件。
 */
export function selectExportFeatures(
  allFeatures: PropertyFeature[],
  filteredFeatures: PropertyFeature[],
  options: ExportOptions,
): PropertyFeature[] {
  const base = options.scope === 'all' ? allFeatures : filteredFeatures;
  if (options.includeInactive) return base;
  return base.filter((f) => isListed(f.properties));
}

/** エクスポート対象フィーチャーから物件 ID のリストを作る */
export function featuresToIds(features: PropertyFeature[]): number[] {
  return features.map((f) => f.properties.id);
}

/**
 * 可視部屋の判定正本(Phase B2-δ §4.7)。
 * is_active な部屋、または shortlist で手を付けた部屋(saved/hide/reject)が可視。
 * shortlist 未登録(none/null)かつ非掲載の部屋は BE の units に載らない想定だが、
 * 契約変更に備え FE 側でも防御的に除外する。
 */
function isExportVisibleUnit(unit: BuildingUnit): boolean {
  if (unit.is_active) return true;
  const status = unit.shortlist_status;
  return status === 'saved' || status === 'hide' || status === 'reject';
}

/**
 * 建物配列からエクスポート対象部屋(units)を選ぶ(B2-δ §4.7)。
 * 対象 = 可視部屋(is_active または saved/hide/reject)。includeInactive=false は
 * is_active===false を除外する(掲載終了を含めない)。
 * 建物順・units 順ともに元リスト順を維持する。
 */
export function selectExportUnits(
  buildings: BuildingFeature[],
  includeInactive: boolean,
): BuildingUnit[] {
  const out: BuildingUnit[] = [];
  for (const b of buildings) {
    for (const unit of b.properties.units) {
      if (!isExportVisibleUnit(unit)) continue;
      if (!includeInactive && unit.is_active === false) continue;
      out.push(unit);
    }
  }
  return out;
}

/** エクスポート対象部屋から部屋 ID のリストを作る */
export function unitsToIds(units: BuildingUnit[]): number[] {
  return units.map((u) => u.id);
}

/** ダウンロードファイル名 (yadokari_YYYYMMDD_HHMM.kml) */
export function exportFilename(now: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  const ts =
    `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
    `_${p(now.getHours())}${p(now.getMinutes())}`;
  return `yadokari_${ts}.kml`;
}

/** Blob をファイルとしてダウンロードさせる */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
