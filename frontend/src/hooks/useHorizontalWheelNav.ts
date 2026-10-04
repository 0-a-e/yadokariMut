import { useEffect, useRef } from 'react';

/** 1ジェスチャーと判定するまでの横方向の累積移動量 (px) */
const NAV_THRESHOLD_PX = 24;
/** 連続入力で複数枚送りにならないよう、送り直しまでの最短間隔 (ms) */
const NAV_COOLDOWN_MS = 250;
/** これ以上入力が途切れたら新しいジェスチャーとして累積をリセットする (ms) */
const GESTURE_IDLE_MS = 200;
/** 縦スクロールのノイズを拾わないため、横が優勢と見なす比率 */
const HORIZONTAL_DOMINANCE = 1.5;
/** deltaMode が行/ページ単位のホイール入力を px に換算する係数 */
const LINE_TO_PX = 16;
const PAGE_TO_PX = 100;

interface HorizontalWheelNavOptions {
  /** wheel を監視する要素 (カードは embla viewport、モーダルは document) */
  target: HTMLElement | Document | null;
  /** 横方向のホイール入力で1枚戻る */
  onPrev: () => void;
  /** 横方向のホイール入力で1枚進む */
  onNext: () => void;
  /** false の間はリスナーを張らない (画像1枚のみ / モーダル閉時など) */
  enabled?: boolean;
}

/**
 * マウスホイールの横倒し / トラックパッドの横スワイプでスライダを送る。
 *
 * 縦スクロールを奪わないよう「横成分が明確に優勢」な入力だけを扱い、
 * それ以外は素通しする (詳細パネルは縦スクロール領域の中にスライダを持つ)。
 */
export function useHorizontalWheelNav({
  target,
  onPrev,
  onNext,
  enabled = true,
}: HorizontalWheelNavOptions) {
  // ハンドラ差し替えでリスナーを張り直さないよう最新の関数を参照する
  const handlersRef = useRef({ onPrev, onNext });
  handlersRef.current = { onPrev, onNext };

  useEffect(() => {
    if (!enabled || !target) return;

    let accumulated = 0;
    let lastEventAt = 0;
    let lastNavAt = 0;

    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return; // ピンチズーム等には関与しない

      const scale =
        event.deltaMode === 1 ? LINE_TO_PX : event.deltaMode === 2 ? PAGE_TO_PX : 1;
      const deltaX = event.deltaX * scale;
      const deltaY = event.deltaY * scale;
      const absX = Math.abs(deltaX);
      const absY = Math.abs(deltaY);

      const now = performance.now();
      if (now - lastEventAt > GESTURE_IDLE_MS) accumulated = 0;
      lastEventAt = now;

      // 横が優勢でない入力はページ/パネルの縦スクロールに委ねる
      if (absX === 0 || absX < absY * HORIZONTAL_DOMINANCE) {
        accumulated = 0;
        return;
      }

      // ブラウザの横スワイプによる履歴移動などに流さない
      event.preventDefault();

      accumulated += deltaX;
      if (Math.abs(accumulated) < NAV_THRESHOLD_PX) return;

      // クールダウン中も累積を捨て、1ジェスチャー=1枚を保つ
      accumulated = 0;
      if (now - lastNavAt < NAV_COOLDOWN_MS) return;
      lastNavAt = now;

      if (deltaX > 0) handlersRef.current.onNext();
      else handlersRef.current.onPrev();
    };

    const listener = (event: Event) => handleWheel(event as WheelEvent);
    target.addEventListener('wheel', listener, { passive: false });
    return () => target.removeEventListener('wheel', listener);
  }, [target, enabled]);
}
