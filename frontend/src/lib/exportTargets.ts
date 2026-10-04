import type { PropertyFeature } from '../types.ts';

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
  return base.filter((f) => f.properties.is_active !== false);
}

/** エクスポート対象フィーチャーから物件 ID のリストを作る */
export function featuresToIds(features: PropertyFeature[]): number[] {
  return features.map((f) => f.properties.id);
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
