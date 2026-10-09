/**
 * 表示整形ユーティリティ(日付・金額)。
 * 旧来コンポーネント毎に重複していた ja-JP ロケール整形を集約する。
 * チャート軸用の派生整形は components/charts/chartTheme 経由で利用する。
 */

import type { StayEstimateSummary } from '../types.ts';

/** 現在時刻の Asia/Tokyo (+09:00) 付き isoformat。
 *
 * shortlist_updated_at 等の「BE 出力と辞書順比較される」値の楽観更新注入に使う。
 * BE は Phase 6c (D9-5) から +09:00 付きで返すため、new Date().toISOString()
 * (UTC・Z付き) を注入すると辞書順 = 時系列の比較が崩れる。
 */
export function nowJstIso(): string {
  return new Date(Date.now() + 9 * 3600_000).toISOString().replace('Z', '+09:00');
}

/** ISOタイムスタンプの表示用整形(日本語ローカル日付)。不正値は先頭10文字にフォールバック */
export function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString('ja-JP', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

/** セッション一覧用の時刻整形(「10/4 14:30」相当)。不正値は空文字 */
export function formatSessionTime(iso?: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('ja-JP', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

/** 管理画面用の短縮時刻整形(「10/04 14:30」相当)。null は "—"、不正値は先頭16文字 */
export function formatAdminTs(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 16);
    return d.toLocaleString('ja-JP', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16);
  }
}

/** 軸ラベル用の日付整形("2026-10-04" → "10/4") */
export function formatTickDate(date: string): string {
  const [m, d] = date.slice(5).split('-');
  return `${Number(m)}/${Number(d)}`;
}

/**
 * 金額表示の正本整形。「12,345円」。
 * null / undefined / NaN は fallback(既定「—」)を返す。
 */
export function formatYen(v: number | null | undefined, fallback = '—'): string {
  return v == null || Number.isNaN(v) ? fallback : `${v.toLocaleString()}円`;
}

/**
 * チャート軸・スパークライン用の桁区切り整形(円単位なし)。旧 formatYen。
 * 軸ラベルはスペース制約が厳しいため単位を付けず、tickFormatter に直接渡せる形を維持する。
 */
export function formatYenCompact(v: number): string {
  return v.toLocaleString();
}

// ============================================================
// 価格表示(stay試算優先のフォールバック表示)
// ============================================================

/**
 * 価格表示の入力ソース。GeoJSON properties 相当の値を任意フィールドで渡す。
 * null / undefined はいずれも「情報なし」扱い。
 */
export interface PriceDisplaySource {
  /** Worker が stay モード絞り込み時に付与する期間試算(stay_estimate) */
  stayEst?: StayEstimateSummary | null;
  /** カタログ最安日額(円/日)。0 は「詳細参照」扱い(現行の truthiness 判定を維持) */
  minDailyRent?: number | null;
  /** カタログ最安プラン総額(円)。0 は表示しない(現行の truthiness 判定を維持) */
  minPlanTotal?: number | null;
}

/**
 * stay 試算が表示可能か(ok かつ総額あり)。
 * PropertyCard / DetailPanel / MapPane で重複していた判定核。
 */
export function hasStayEstimate(est?: StayEstimateSummary | null): boolean {
  return !!est?.ok && est.stayTotalYen != null;
}

/** 期間総額ヘッダー「N,NNN円（D日）」。stay 試算が表示不能なら null */
export function formatStayHeader(est?: StayEstimateSummary | null): string | null {
  return hasStayEstimate(est) ? `${formatYen(est!.stayTotalYen)}（${est!.stayDays}日）` : null;
}

/** 日額表示「N,NNN円/日」。minDailyRent が無ければ「詳細参照」 */
export function formatDailyRentDisplay(minDailyRent?: number | null): string {
  return minDailyRent ? `${formatYen(minDailyRent)}/日` : '詳細参照';
}

/**
 * カタログ総額の括弧装飾「(総額:N,NNN円)」。minPlanTotal が無ければ空文字。
 * 旧実装のラベル揺れ(「総額:」/「プラン総額: 」)は「総額:」に統一済み。
 */
export function formatPlanTotalDisplay(minPlanTotal?: number | null): string {
  return minPlanTotal ? `(総額:${formatYen(minPlanTotal)})` : '';
}

/**
 * 価格表示の正本(1行テキスト)。
 * stay 試算優先「N,NNN円（D日）」→ カタログ日額「N,NNN円/日」→「詳細参照」。
 * マップポップアップ等の HTML 文字列にそのまま埋め込めるプレーンテキストを返す。
 * 呼び出し側で日額と総額を別スタイルに組みたい場合は
 * formatDailyRentDisplay / formatPlanTotalDisplay を直接使う。
 */
export function formatPriceDisplay(src: PriceDisplaySource): string {
  return formatStayHeader(src.stayEst) ?? formatDailyRentDisplay(src.minDailyRent);
}

// ============================================================
// 建物単位集約(Phase B2)
// ============================================================

/**
 * 建物の最安〜最高帯表示「N,NNN円〜N,NNN円/日」(建物代表値・設計 §4.1)。
 * min == max(または max 欠損)は単値「N,NNN円/日」。両方欠損は「—/日」。
 */
export function formatRentBand(
  min: number | null | undefined,
  max: number | null | undefined,
): string {
  if (min == null && max == null) return '—/日';
  if (min == null) return `〜${formatYen(max)}/日`;
  if (max == null || max === min) return `${formatYen(min)}/日`;
  return `${formatYen(min)}〜${formatYen(max)}/日`;
}

/**
 * 期間総額帯(stayBand)を優先する建物帯表示の正本。
 * stayBand が有効(stay モードで試算可能)なら期間総額の帯(単位なし)、
 * 無ければカタログ日額帯(formatRentBand)へフォールバックする。
 * 建物カード / 建物パネル / 地図 tooltip の 3 実装をここへ一本化した
 * (docs/fe-floor-orientation-redesign-plan.md §7.2)。
 */
export function formatRentBandText(
  catalogMin: number | null | undefined,
  catalogMax: number | null | undefined,
  stayBand?: { min: number | null; max: number | null } | null,
): string {
  if (stayBand && stayBand.min != null) {
    return stayBand.max == null || stayBand.max === stayBand.min
      ? formatYen(stayBand.min)
      : `${formatYen(stayBand.min)}〜${formatYen(stayBand.max)}`;
  }
  return formatRentBand(catalogMin, catalogMax);
}
