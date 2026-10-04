import { describe, expect, it } from 'vitest';
import {
  ENGAGE_DISTANCE_PX,
  ENGAGE_DOMINANCE,
  MIN_FLING_PX,
  shouldEngage,
  shouldReleaseDismiss,
} from './useSwipeDismiss.ts';

describe('shouldEngage', () => {
  it('閾値以下の縦移動では発始しない', () => {
    expect(shouldEngage(ENGAGE_DISTANCE_PX, 0, 'down')).toBe(false);
    expect(shouldEngage(ENGAGE_DISTANCE_PX, 0, 'vertical')).toBe(false);
    expect(shouldEngage(ENGAGE_DISTANCE_PX - 1, 0, 'vertical')).toBe(false);
  });

  it('縦成分が横成分の支配倍率を超えなければ発始しない(横スワイプ=画像送りを保護)', () => {
    expect(shouldEngage(30, 30 / ENGAGE_DOMINANCE, 'vertical')).toBe(false);
    expect(shouldEngage(30, 30 / ENGAGE_DOMINANCE - 1, 'vertical')).toBe(true);
  });

  it("direction 'down' は下方向のみ発始する", () => {
    expect(shouldEngage(30, 2, 'down')).toBe(true);
    expect(shouldEngage(-30, 2, 'down')).toBe(false);
    expect(shouldEngage(-30, 2, 'vertical')).toBe(true);
  });

  it('境界値: 厳密に閾値超のときのみ発始する', () => {
    // ady > |dx| * DOMINANCE(同値は不発)
    const dx = 10;
    expect(shouldEngage(dx * ENGAGE_DOMINANCE + 1, dx, 'down')).toBe(true);
  });
});

describe('shouldReleaseDismiss', () => {
  const base = {
    distanceThresholdPx: 110,
    velocity: 0,
    velocityThresholdPxMs: 0.5,
    minFlingPx: MIN_FLING_PX,
  };

  it('距離閾値に達していれば速度不問で確定', () => {
    expect(shouldReleaseDismiss({ ...base, dy: 120, velocity: 0 })).toBe(true);
  });

  it('フリング: 最低移動量以上かつ速度閾値以上で確定', () => {
    expect(
      shouldReleaseDismiss({ ...base, dy: MIN_FLING_PX, velocity: 0.8 }),
    ).toBe(true);
  });

  it('移動量不足のフリングは不確定', () => {
    expect(
      shouldReleaseDismiss({ ...base, dy: MIN_FLING_PX - 1, velocity: 5 }),
    ).toBe(false);
  });

  it('速度不足のフリングは不確定', () => {
    expect(
      shouldReleaseDismiss({ ...base, dy: MIN_FLING_PX, velocity: 0.3 }),
    ).toBe(false);
  });

  it("上方向の移動も絶対値で判定('vertical' の上スワイプ)", () => {
    expect(
      shouldReleaseDismiss({ ...base, dy: -120, velocity: -0.6 }),
    ).toBe(true);
  });

  it("'down' 側で上方向へ戻した分は距離として数えないよう、呼び出し側クランプ前提", () => {
    // クランプ後の dy=0(指が開始点に戻って離した)は不確定
    expect(shouldReleaseDismiss({ ...base, dy: 0, velocity: 0 })).toBe(false);
  });
});
