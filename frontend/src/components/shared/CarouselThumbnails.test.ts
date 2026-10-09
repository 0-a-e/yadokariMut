import { describe, expect, it } from 'vitest';
import { IDLE_HIDE_MS, thumbnailWheelDelta } from './CarouselThumbnails.tsx';

describe('thumbnailWheelDelta', () => {
  it('縦回転(deltaY)をそのまま横スクロール量に変換する', () => {
    expect(thumbnailWheelDelta({ deltaY: 120, deltaX: 0 })).toBe(120);
    expect(thumbnailWheelDelta({ deltaY: -120, deltaX: 0 })).toBe(-120);
  });

  it('横倒し(deltaX)をそのまま横スクロール量に変換する', () => {
    expect(thumbnailWheelDelta({ deltaY: 0, deltaX: 100 })).toBe(100);
  });

  it('縦横の混合入力は加算する(斜め入力)', () => {
    expect(thumbnailWheelDelta({ deltaY: 80, deltaX: 40 })).toBe(120);
  });

  it('無入力は null(何もせずページの縦スクロールも奪わない)', () => {
    expect(thumbnailWheelDelta({ deltaY: 0, deltaX: 0 })).toBeNull();
  });

  it('IDLE_HIDE_MS は 3 秒(設計決定値)', () => {
    expect(IDLE_HIDE_MS).toBe(3000);
  });
});
