import { describe, expect, it } from 'vitest';
import {
  buildFeaturePopupHtml,
  catalogIdFromGlLayerId,
  formatPopupValue,
} from './featurePopup.ts';

describe('catalogIdFromGlLayerId', () => {
  it('gl:{catalogId}:{index} から catalogId を取り出す', () => {
    expect(catalogIdFromGlLayerId('gl:ksj_l01:0')).toBe('ksj_l01');
    expect(catalogIdFromGlLayerId('gl:gsi_std_vector:12')).toBe('gsi_std_vector');
  });

  it('接頭辞が違う/形式不正な id は null', () => {
    expect(catalogIdFromGlLayerId('l01-circle')).toBeNull();
    expect(catalogIdFromGlLayerId('gl:')).toBeNull();
    expect(catalogIdFromGlLayerId('gl:nonamespace')).toBeNull();
    expect(catalogIdFromGlLayerId('')).toBeNull();
  });
});

describe('formatPopupValue', () => {
  it('plain は文字列/数値をそのまま文字列化', () => {
    expect(formatPopupValue('さいたま大宮', 'plain')).toBe('さいたま大宮');
    expect(formatPopupValue(2026, 'plain')).toBe('2026');
  });

  it('int は3桁カンマ区切り', () => {
    expect(formatPopupValue(1234567, 'int')).toBe('1,234,567');
    expect(formatPopupValue(42, 'int')).toBe('42');
  });

  it('jpy-m2 は円/m²付き', () => {
    expect(formatPopupValue(67100000, 'jpy-m2')).toBe('67,100,000円/m²');
  });

  it('undefined/null と非finite数は空文字', () => {
    expect(formatPopupValue(undefined, 'int')).toBe('');
    expect(formatPopupValue(null, 'plain')).toBe('');
    expect(formatPopupValue(Number.NaN, 'int')).toBe('');
    expect(formatPopupValue({ obj: 1 }, 'plain')).toBe('');
  });
});

describe('buildFeaturePopupHtml', () => {
  const l01Def = {
    titleKey: 'L01_024',
    fields: [
      { key: 'L01_008', label: '公示価格', format: 'jpy-m2' as const },
      { key: 'L01_025', label: '所在地' },
      { key: 'L01_007', label: '公示年' },
    ],
  };

  it('タイトル+fields順に行を組み立てる', () => {
    const html = buildFeaturePopupHtml(l01Def, {
      L01_024: 'さいたま大宮',
      L01_008: 456000,
      L01_025: '埼玉県さいたま市大宮区…',
      L01_007: 2026,
    });
    expect(html).toContain('さいたま大宮');
    expect(html).toContain('456,000円/m²');
    expect(html).toContain('埼玉県さいたま市大宮区…');
    expect(html).toContain('公示年');
    // タイトルが行より前
    expect(html.indexOf('さいたま大宮')).toBeLessThan(html.indexOf('公示価格'));
  });

  it('属性値のHTML特殊文字はエスケープされる(XSSガード)', () => {
    const html = buildFeaturePopupHtml(l01Def, {
      L01_024: '<script>alert(1)</script>',
      L01_008: 1,
      L01_025: 'a&b"c',
      L01_007: 2026,
    });
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('a&amp;b&quot;c');
  });

  it('欠損属性の行はスキップされ、タイトル欠損でも本体は表示される', () => {
    const html = buildFeaturePopupHtml(l01Def, { L01_008: 100 });
    expect(html).toContain('100円/m²');
    expect(html).not.toContain('所在地');
    expect(html).not.toContain('公示年');
  });
});
