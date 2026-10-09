import { describe, expect, it } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RoomRow } from './RoomRow.tsx';
import type { BuildingUnit } from '../../types.ts';

/** 必須フィールドを満たす最小の部屋(表示契約の検証用) */
const baseUnit: BuildingUnit = {
  id: 1,
  total_score: 0,
  is_active: true,
  feature_summary: '',
  feature_categories: [],
  access_summary: [],
  images: [],
  rent_plans: [],
  campaigns: [],
  shortlist_status: 'none',
  layout: '1K',
  area_m2: 25,
  min_daily_rent: 4500,
  floor_number: 5,
  floor_number_max: 5,
  orientation_deg: 135,
};

function render(unit: BuildingUnit, matched = false): string {
  return renderToStaticMarkup(
    React.createElement(RoomRow, {
      unit,
      matched,
      priceMode: 'catalog' as const,
      onClick: () => {},
      density: 'dense' as const,
    }),
  );
}

describe('RoomRow(部屋行の表示契約・§4.3)', () => {
  it('所在階・方角はデータがある場合のみチップで表示する', () => {
    const html = render(baseUnit);
    expect(html).toContain('5階');
    expect(html).toContain('南東');
    expect(html).toContain('1K');
    expect(html).toContain('4,500円/日');

    const bare = render({
      ...baseUnit,
      floor_number: null,
      floor_number_max: null,
      orientation_deg: null,
    });
    expect(bare).not.toContain('階');
    expect(bare).not.toContain('南東');
    expect(bare).toContain('4,500円/日');
  });

  it('地下階は「地下1階」表記になる', () => {
    expect(render({ ...baseUnit, floor_number: -1, floor_number_max: -1 })).toContain(
      '地下1階',
    );
  });

  it('一致マークはダーク地のチップ + 成功色アイコン(緑地に緑アイコンを置かない)', () => {
    const html = render(baseUnit, true);
    // チップ背景はテーマのダーク面(bg-bg)。tone(タイル全面塗り)は使わない
    expect(html).toContain('bg-bg');
    expect(html).toContain('text-success');
    expect(html).toContain('size-3.5');
  });

  it('一致していない行はマークを出さない', () => {
    expect(render(baseUnit, false)).not.toContain('bg-bg');
  });

  it('掲載終了の部屋は薄色で表示する', () => {
    expect(render({ ...baseUnit, is_active: false })).toContain('text-text-muted/60');
  });
});
