import { describe, expect, it } from 'vitest';
import { buildingPinColor, buildingTooltipHtml } from './buildingTooltip.ts';
import type { BuildingProperties } from '../../types.ts';

function bprops(partial: Partial<BuildingProperties> = {}): BuildingProperties {
  return {
    id: 1,
    kind: 'building',
    name: '南多摩レジデンス',
    address: '東京都多摩市永山1-1-1',
    municipality: '多摩市',
    is_active: true,
    units_count: 12,
    active_units_count: 12,
    source_sites: ['unionmonthly'],
    building_names: [],
    feature_categories: [],
    min_daily_rent: 4800,
    max_daily_rent: 7500,
    min_walk_minutes: 7,
    has_campaign: false,
    access_summary: [],
    station_summary: '',
    units: [],
    ...partial,
  };
}

describe('buildingPinColor(建物ショートリスト拡張後の優先度色分け)', () => {
  it('active 建物は既定色(primary)、all_inactive は非掲載系グレー', () => {
    expect(buildingPinColor(bprops({ is_active: true }))).toBe('var(--primary)');
    expect(buildingPinColor(bprops({ is_active: false }))).toBe('var(--color-text-muted)');
  });

  it('建物saved は保存色(saved部屋の有無に依らず最優先・非掲載はグレー優先)', () => {
    expect(buildingPinColor(bprops({ shortlist_status: 'saved' }))).toBe(
      'var(--color-success)',
    );
    expect(buildingPinColor(bprops({ shortlist_status: 'saved' }), true)).toBe(
      'var(--color-success)',
    );
    // 非掲載は事実情報として最優先(建物saved より上)
    expect(buildingPinColor(bprops({ is_active: false, shortlist_status: 'saved' }))).toBe(
      'var(--color-text-muted)',
    );
  });

  it('建物未保存 + 部屋saved≥1 は保存色 45% mix', () => {
    expect(buildingPinColor(bprops({}), true)).toBe(
      'color-mix(in srgb, var(--color-success) 45%, var(--primary))',
    );
    expect(buildingPinColor(bprops({}), false)).toBe('var(--primary)');
  });
});

describe('buildingTooltipHtml(建物 tooltip・設計 §4.1)', () => {
  it('1行目=建物名 / 2行目=部屋数とカタログ帯 / 3行目=徒歩', () => {
    const html = buildingTooltipHtml(bprops());
    expect(html).toContain('南多摩レジデンス');
    expect(html).toContain('12部屋');
    expect(html).toContain('4,800円〜7,500円/日');
    expect(html).toContain('徒歩7分');
    expect(html).not.toContain('キャンペーン実施中');
  });

  it('無名建物は municipality+address の短縮へフォールバックする', () => {
    const html = buildingTooltipHtml(bprops({ name: null }));
    expect(html).toContain('多摩市 東京都多摩市永山1-1-1');
  });

  it('has_campaign 時はキャンペーン実施中 badge を出す', () => {
    const html = buildingTooltipHtml(bprops({ has_campaign: true }));
    expect(html).toContain('キャンペーン実施中');
  });

  it('建物saved 時は 1行目に保存済 badge を出す', () => {
    const html = buildingTooltipHtml(bprops({ shortlist_status: 'saved' }));
    expect(html).toContain('保存済');
    expect(buildingTooltipHtml(bprops())).not.toContain('保存済');
  });

  it('stay 帯を渡すと 2行目の帯が期間総額(min〜max・formatYen)へ差し替わる', () => {
    const html = buildingTooltipHtml(bprops(), { min: 100000, max: 200000 });
    expect(html).toContain('100,000円〜200,000円');
    expect(html).not.toContain('/日');
  });

  it('stay 帯が同値なら単値表示', () => {
    const html = buildingTooltipHtml(bprops(), { min: 144000, max: 144000 });
    expect(html).toContain('144,000円');
  });

  it('stay 帯が計算不能(null)ならカタログ帯へフォールバックする', () => {
    const html = buildingTooltipHtml(bprops(), { min: null, max: null });
    expect(html).toContain('4,800円〜7,500円/日');
  });

  it('active_units_count 欠損時は units.length へフォールバックする', () => {
    const html = buildingTooltipHtml(bprops({ active_units_count: null, units_count: 3 }));
    expect(html).toContain('0部屋'); // fixture の units は空配列
  });
});
