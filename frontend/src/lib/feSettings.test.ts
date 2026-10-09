import { describe, expect, it } from 'vitest';
import {
  EMPTY_FE_SETTINGS,
  resolveMapBackground,
  resolvePinBalloonPermanent,
  resolvePinClustering,
  type FeSettings,
} from './feSettings.ts';

/** global の一部だけを上書きした FeSettings を組むヘルパ */
function withGlobal(global: Partial<FeSettings['global']>): FeSettings {
  return { ...EMPTY_FE_SETTINGS, global };
}

describe('resolvePinClustering', () => {
  it('未設定・EMPTY では true(現行動作)を返す', () => {
    expect(resolvePinClustering(undefined)).toBe(true);
    expect(resolvePinClustering(EMPTY_FE_SETTINGS)).toBe(true);
  });

  it('false 保存時のみ false を返す(null は未指定扱い)', () => {
    expect(resolvePinClustering(withGlobal({ pinClustering: false }))).toBe(false);
    expect(resolvePinClustering(withGlobal({ pinClustering: null }))).toBe(true);
    expect(resolvePinClustering(withGlobal({ pinClustering: true }))).toBe(true);
  });
});

describe('resolvePinBalloonPermanent', () => {
  it('未設定・EMPTY・null では false(ホバー/クリック時のみ)を返す', () => {
    expect(resolvePinBalloonPermanent(undefined)).toBe(false);
    expect(resolvePinBalloonPermanent(EMPTY_FE_SETTINGS)).toBe(false);
    expect(resolvePinBalloonPermanent(withGlobal({ pinBalloonPermanent: null }))).toBe(false);
  });

  it('true 保存時のみ true を返す', () => {
    expect(resolvePinBalloonPermanent(withGlobal({ pinBalloonPermanent: true }))).toBe(true);
    expect(resolvePinBalloonPermanent(withGlobal({ pinBalloonPermanent: false }))).toBe(false);
  });
});

describe('resolveMapBackground', () => {
  it('未設定・EMPTY・null では black(従来の #1a1a24)を返す', () => {
    expect(resolveMapBackground(undefined)).toBe('black');
    expect(resolveMapBackground(EMPTY_FE_SETTINGS)).toBe('black');
    expect(resolveMapBackground(withGlobal({ mapBackground: null }))).toBe('black');
  });

  it('保存値 black / white をそのまま返す', () => {
    expect(resolveMapBackground(withGlobal({ mapBackground: 'black' }))).toBe('black');
    expect(resolveMapBackground(withGlobal({ mapBackground: 'white' }))).toBe('white');
  });
});
