import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MultiCombobox } from './combobox.tsx';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './dropdown-menu.tsx';

/**
 * オーバーレイ系ポップアップの重なり規約(docs/fe-floor-orientation-redesign-plan.md §11)。
 *
 * 本プロジェクトは詳細パネル z-[1000] / モバイルシート z-[2100] / モーダル z-[9998-9999] の
 * 多層構成。hextaUI のレジストリ既定は `z-50`(単層アプリ前提)で、そのままだと
 * パネルの下に隠れて操作不能になる(2026-10-10 の BuildingPanel 並び順セレクトで実害)。
 * 正規化(normalize-hextaui.mjs)が z-[10000] へ寄せるため、その規約を固定する。
 */
const OVERLAY_FILES = ['select.tsx', 'dropdown-menu.tsx', 'combobox.tsx'] as const;

describe('オーバーレイの z-index 規約', () => {
  for (const file of OVERLAY_FILES) {
    it(`${file} のポップアップは z-[10000] を使い z-50 を残さない`, () => {
      const src = readFileSync(new URL(`./${file}`, import.meta.url), 'utf8');
      expect(src).not.toMatch(/isolate z-50/);
      expect(src).toMatch(/isolate z-\[10000\]/);
    });
  }
});

describe('MultiCombobox(hextaUI combobox アダプタ)', () => {
  const items = [
    { value: 'a', label: 'タグA' },
    { value: 'b', label: 'タグB' },
  ];

  it('選択値はチップで描画し、選択済みならプレースホルダを出さない', () => {
    const html = renderToStaticMarkup(
      React.createElement(MultiCombobox, {
        items,
        value: ['a'],
        onValueChange: () => {},
        placeholder: 'タグを検索',
      }),
    );
    expect(html).toContain('タグA');
    expect(html).not.toContain('タグを検索');
    expect(html).toContain('combobox-chips');
  });

  it('未選択ならプレースホルダを出し、ポップアップは開いていない', () => {
    const html = renderToStaticMarkup(
      React.createElement(MultiCombobox, {
        items,
        value: [],
        onValueChange: () => {},
        placeholder: 'タグを検索',
      }),
    );
    expect(html).toContain('タグを検索');
    expect(html).not.toContain('combobox-content');
  });
});

describe('DropdownMenu(hextaUI)', () => {
  it('トリガーを描画できる(正規化の煙テスト)', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        DropdownMenu,
        null,
        React.createElement(DropdownMenuTrigger, {
          render: React.createElement('button', { type: 'button' }, 'メニュー'),
        }),
        React.createElement(
          DropdownMenuContent,
          null,
          React.createElement(DropdownMenuItem, null, '設定'),
        ),
      ),
    );
    expect(html).toContain('メニュー');
  });
});
