/**
 * 建物ピン tooltip の HTML 生成(B2-β・docs/building-aggregation-b2-fe-plan.md §4.1)。
 *
 * MapPane が divIcon/tooltip に注入する HTML 文字列を純関数として切り出し
 * (テストの主戦場)。テーマ色は var() 参照で正本(index.css @theme・
 * 生成 DOM は CSS 変数解決可能)。hex 直書き(#fff / #00f2fe)は現行 tooltip と
 * 同値のテーマ変数が無いため維持(MapPane 内コメントの TODO と同源)。
 */
import type { BuildingProperties } from '../../types.ts';
import { buildingDisplayName, type RentBand } from '../../lib/building.ts';
import { formatRentBand, formatYen } from '../../lib/format.ts';

/**
 * 建物ピンの塗り色。優先度: all_inactive(グレー) > 建物saved(保存色) >
 * 部屋saved≥1(保存色 45% mix) > 既定(primary)。非掲載は事実情報のため最優先
 * (部屋平面の inactive 優先表示と対称)。hasSavedUnit は savedCountOf>0 を
 * MapPane 側で計算して渡す(units 全体は本純関数の入力にしない)。
 */
export function buildingPinColor(
  p: Pick<BuildingProperties, 'is_active' | 'shortlist_status'>,
  hasSavedUnit = false,
): string {
  if (p.is_active === false) return 'var(--color-text-muted)';
  if (p.shortlist_status === 'saved') return 'var(--color-success)';
  if (hasSavedUnit) {
    return 'color-mix(in srgb, var(--color-success) 45%, var(--primary))';
  }
  return 'var(--primary)';
}

/** 2行目の価格帯。stay 帯(stayBandOfUnits の結果)が有効なら期間総額帯へ差し替え */
function bandText(p: BuildingProperties, stayBand: RentBand | null | undefined): string {
  if (stayBand && stayBand.min != null) {
    const { min, max } = stayBand;
    return max == null || max === min ? formatYen(min) : `${formatYen(min)}〜${formatYen(max)}`;
  }
  // stay 帯が計算不能な建物(unestimable のみ等)はカタログ代表値へフォールバック
  return formatRentBand(p.min_daily_rent, p.max_daily_rent);
}

/**
 * 建物 tooltip HTML:
 *   1行目 建物名(無名は municipality+address 短縮)
 *   2行目 {active_units_count}部屋 · 最安〜最高帯(stay モードは期間総額帯)
 *   3行目 徒歩N分 + キャンペーン実施中 badge(has_campaign 時)
 */
export function buildingTooltipHtml(
  p: BuildingProperties,
  stayBand?: RentBand | null,
): string {
  const unitCount = p.active_units_count ?? p.units.length;
  const walk = p.min_walk_minutes != null ? `徒歩${p.min_walk_minutes}分` : '徒歩不明';

  // キャンペーン badge(現行部屋 tooltip の badge スタイルを建物単位の 1 badge に集約)。
  // BE campaigns に is_active 列は無い(常時有効)ため建物側 has_campaign のみ判定
  const campaignBadge = p.has_campaign
    ? `<span style="background-color: color-mix(in srgb, var(--color-success) 12%, transparent); color: var(--color-success); border: 1px solid color-mix(in srgb, var(--color-success) 30%, transparent); border-radius: 4px; padding: 2px 4px; font-size: calc(9px * var(--font-scale)); font-weight: 700; display: inline-flex; align-items: center; gap: 2px; white-space: nowrap;">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" style="width:9px;height:9px;display:inline;fill:var(--color-success);margin-right:2px"><path d="M0 80V229.5c0 17 6.7 33.3 18.7 45.3L176 432c24.9 24.9 65.4 24.9 90.3 0L421.3 278.3c24.9-24.9 24.9-65.4 0-90.3L263.8 30.3C252.8 19.3 236.5 4.7 224 0H80C35.8 0 0 35.8 0 80zm112 48a32 32 0 1 1 0 64 32 32 0 1 1 0-64z"/></svg>キャンペーン実施中
      </span>`
    : '';

  const savedBadge =
    p.shortlist_status === 'saved'
      ? `<span style="background-color: color-mix(in srgb, var(--color-success) 12%, transparent); color: var(--color-success); border: 1px solid color-mix(in srgb, var(--color-success) 30%, transparent); border-radius: 4px; padding: 1px 4px; font-size: calc(9px * var(--font-scale)); font-weight: 700; margin-left: 4px; white-space: nowrap;">保存済</span>`
      : '';

  return `
    <div style="padding: 6px; font-family: 'Outfit', 'Noto Sans JP', sans-serif;">
      <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #fff; margin-bottom: 2px;">${buildingDisplayName(p)}${savedBadge}</div>
      <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #00f2fe; margin-bottom: 2px;">${unitCount}部屋 · ${bandText(p, stayBand)}</div>
      <div style="font-size: calc(10px * var(--font-scale)); color: var(--color-text-muted); display: flex; align-items: center; gap: 4px;">
        <span>${walk}</span>${campaignBadge}
      </div>
    </div>
  `;
}
