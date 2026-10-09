import { describe, expect, it } from 'vitest';
import { getScoreColor } from './score.ts';

/**
 * スコア帯 → 表示色の契約。
 *
 * 返値は DOM inline style(カードバッジ / マップピンの divIcon HTML)でのみ
 * 使用され、Canvas 描画には渡さないため var(--color-*) 参照が有効。
 * このテストは「どの帯がどのテーマトークンに対応するか」の契約を固定する
 * (トークン自体の実値の正本は frontend/src/index.css の @theme)。
 * Canvas 描画へ色を渡す実装を追加する場合は、var() を getComputedStyle で
 * 解決してから渡すこと(CSS 変数は Canvas で解決されない)。
 */
describe('getScoreColor', () => {
  it('score 0 / 未定義は muted(スコア無し帯)', () => {
    expect(getScoreColor(0)).toBe('var(--color-text-muted)');
  });

  it('80以上は success', () => {
    expect(getScoreColor(80)).toBe('var(--color-success)');
    expect(getScoreColor(99)).toBe('var(--color-success)');
  });

  it('60以上80未満はシアン(同値のテーマ変数が無いため hex 維持)', () => {
    expect(getScoreColor(60)).toBe('#00f2fe');
    expect(getScoreColor(79)).toBe('#00f2fe');
  });

  it('40以上60未満は warning', () => {
    expect(getScoreColor(40)).toBe('var(--color-warning)');
    expect(getScoreColor(59)).toBe('var(--color-warning)');
  });

  it('40未満は danger', () => {
    expect(getScoreColor(1)).toBe('var(--color-danger)');
  });

  it('参照するテーマ変数は index.css @theme に実在する', () => {
    // 各トークンが index.css 上で定義されていることの軽い契約(var() 文字列の形)
    for (const c of [getScoreColor(0), getScoreColor(80), getScoreColor(40), getScoreColor(1)]) {
      expect(c).toMatch(/^var\(--color-[a-z-]+\)$/);
    }
  });
});
