import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject, TouchEvent as ReactTouchEvent } from 'react';

/**
 * モバイル向け「縦スワイプで閉じる」ジェスチャ。
 *
 * 下シート(DetailPanel)と全画面ライトボックス(LightboxModal)の共用。
 * - 発始判定: 縦移動が ENGAGE_DISTANCE_PX 超かつ横成分の ENGAGE_DOMINANCE 倍優勢
 *   (横スワイプ=画像カルーセル送りと共存するための dominance ゲート)。
 * - scrollContainerRef を渡すと、その要素の scrollTop === 0 のときのみ発始する
 *   (パネル内スクロール中の縦ドラッグはコンテンツスクロールとして優先)。
 * - ドラッグ追従は targetRef の DOM に直接 inline style を書くため state 更新が走らず、
 *   離す/退場で inline を外せば要素側の transition クラスが現在位置から復帰してくれる。
 * - 退場は translateY(100%) への遷移後に onDismiss() を呼ぶ(呼び出し元は即 unmount 前提)。
 *   Tailwind v4 の translate-* は transform と独立プロパティのため両者は合成される。
 *
 * 判定ロジックは shouldEngage / shouldReleaseDismiss として pure に export(テスト対象)。
 */

/** スワイプ発始とみなす最小縦移動(px) */
export const ENGAGE_DISTANCE_PX = 12;
/** 縦成分が横成分の何倍優勢なら縦スワイプとみなすか */
export const ENGAGE_DOMINANCE = 1.5;
/** フリング(速度による確定)に必要な最低移動量(px) */
export const MIN_FLING_PX = 48;
/** 退場アニメ時間(ms) */
export const EXIT_DURATION_MS = 320;
const EXIT_EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';
/** fadeWithDrag 時の減衰: |offset| / FADE_DIVISOR だけ透明化(下限 FADE_MIN) */
const FADE_DIVISOR = 450;
const FADE_MIN = 0.55;

export type SwipeDirection = 'down' | 'vertical';
type SwipePhase = 'idle' | 'dragging' | 'exiting';

/** 発始(ドラッグ追従開始)判定。'down' は下方向のみ */
export function shouldEngage(
  dy: number,
  dx: number,
  direction: SwipeDirection,
): boolean {
  const ady = Math.abs(dy);
  if (ady <= ENGAGE_DISTANCE_PX) return false;
  if (ady <= Math.abs(dx) * ENGAGE_DOMINANCE) return false;
  return direction === 'vertical' || dy > 0;
}

export interface SwipeReleaseInput {
  /** 開始点からの縦移動量(px、下プラス)。'down' では呼び出し側で max(0, dy) にクランプする */
  dy: number;
  /** 直近の縦速度(px/ms、下プラス) */
  velocity: number;
  /** 距離閾値: この移動量に達していれば確定 */
  distanceThresholdPx: number;
  /** 速度閾値: minFlingPx 以上かつこの速度以上なら確定(フリング) */
  velocityThresholdPxMs: number;
  /** フリング成立に必要な最低移動量 */
  minFlingPx: number;
}

/** 指を離した時点で閉じるか(距離 or フリング速度) */
export function shouldReleaseDismiss(input: SwipeReleaseInput): boolean {
  const dist = Math.abs(input.dy);
  if (dist >= input.distanceThresholdPx) return true;
  return (
    dist >= input.minFlingPx && Math.abs(input.velocity) >= input.velocityThresholdPxMs
  );
}

export interface UseSwipeDismissOptions {
  /** false の間は一切反応しない(モバイル判定などは呼び出し側で合成) */
  enabled: boolean;
  /** 'down': 下方向のみ(下シート) / 'vertical': 上下両方向(全画面ビューア) */
  direction: SwipeDirection;
  /** 指定時、この要素の scrollTop === 0 のときのみ発始(スクロール領域との両立) */
  scrollContainerRef?: RefObject<HTMLElement | null>;
  /** 距離閾値(px)。既定 110 */
  distanceThresholdPx?: number;
  /** フリング速度閾値(px/ms)。既定 0.5 */
  velocityThresholdPxMs?: number;
  /** ドラッグに応えて透明化する(全画面画像ビューア向け) */
  fadeWithDrag?: boolean;
  /** 退場確定時に呼ばれる */
  onDismiss: () => void;
  /** 退場開始時に呼ばれる(競合ガード用に「どの対象を閉じようとしているか」を記録する等) */
  onDismissStart?: () => void;
  /**
   * 退場タイマー発火時に対象がまだ有効か(退場中に別物件が選択される等の競合ガード)。
   * false の場合は onDismiss を呼ばずスタイルのみ復帰する。既定は常に有効。
   */
  isDismissValid?: () => boolean;
}

export function useSwipeDismiss(options: UseSwipeDismissOptions) {
  /** transform を適用する要素(bind と同じ要素に付ける) */
  const targetRef = useRef<HTMLDivElement | null>(null);
  /** ハンドラ内から常に最新 options を読むための退避 */
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [isDragging, setIsDragging] = useState(false);
  const phaseRef = useRef<SwipePhase>('idle');
  const startRef = useRef({ x: 0, y: 0 });
  const startStampRef = useRef(0);
  /** 指速の平滑化用サンプル */
  const lastSampleRef = useRef({ y: 0, stamp: 0 });
  const velocityRef = useRef(0);
  const exitTimerRef = useRef<number | undefined>(undefined);

  const clearInlineStyles = useCallback(() => {
    const el = targetRef.current;
    if (!el) return;
    el.style.transition = '';
    el.style.transform = '';
    el.style.opacity = '';
    el.style.willChange = '';
  }, []);

  /** ドラッグ中断 → クラスの transition-all でスプリングバック */
  const cancelDrag = useCallback(() => {
    if (phaseRef.current !== 'dragging') return;
    phaseRef.current = 'idle';
    setIsDragging(false);
    clearInlineStyles();
  }, [clearInlineStyles]);

  const finishExit = useCallback(() => {
    exitTimerRef.current = undefined;
    phaseRef.current = 'idle';
    clearInlineStyles();
    // 退場中に対象が別物に差し替わっていたら閉じない(スタイル復帰のみ)
    if (optionsRef.current.isDismissValid?.() ?? true) {
      optionsRef.current.onDismiss();
    }
  }, [clearInlineStyles]);

  useEffect(
    () => () => {
      window.clearTimeout(exitTimerRef.current);
    },
    [],
  );

  const onTouchStart = useCallback((e: ReactTouchEvent<HTMLElement>) => {
    const o = optionsRef.current;
    if (!o.enabled || phaseRef.current !== 'idle') return;
    if (e.touches.length !== 1) return;
    const t = e.touches[0];
    startRef.current = { x: t.clientX, y: t.clientY };
    startStampRef.current = e.timeStamp;
    lastSampleRef.current = { y: t.clientY, stamp: e.timeStamp };
    velocityRef.current = 0;
  }, []);

  const onTouchMove = useCallback(
    (e: ReactTouchEvent<HTMLElement>) => {
      const o = optionsRef.current;
      if (!o.enabled || phaseRef.current === 'exiting') return;
      const el = targetRef.current;
      if (!el) return;
      // 多指(ピンチ等)が混ざったらドラッグを諦める
      if (e.touches.length !== 1) {
        cancelDrag();
        return;
      }
      const t = e.touches[0];
      const dy = t.clientY - startRef.current.y;
      const dx = t.clientX - startRef.current.x;

      if (phaseRef.current === 'idle') {
        const scrollLocked = o.scrollContainerRef
          ? (o.scrollContainerRef.current?.scrollTop ?? 0) === 0
          : true;
        if (!scrollLocked || !shouldEngage(dy, dx, o.direction)) return;
        phaseRef.current = 'dragging';
        setIsDragging(true);
        // ドラッグ中はクラスの transition を inline で打ち消して指に密着させる
        el.style.transition = 'none';
        el.style.willChange = 'transform';
      }

      const dt = e.timeStamp - lastSampleRef.current.stamp;
      if (dt > 0) {
        const inst = (t.clientY - lastSampleRef.current.y) / dt;
        velocityRef.current = velocityRef.current * 0.4 + inst * 0.6;
        lastSampleRef.current = { y: t.clientY, stamp: e.timeStamp };
      }

      const offset = o.direction === 'down' ? Math.max(0, dy) : dy;
      el.style.transform = `translateY(${offset}px)`;
      if (o.fadeWithDrag) {
        el.style.opacity = String(
          Math.max(FADE_MIN, 1 - Math.abs(offset) / FADE_DIVISOR),
        );
      }
    },
    [cancelDrag],
  );

  const onTouchEnd = useCallback(
    (e: ReactTouchEvent<HTMLElement>) => {
      const o = optionsRef.current;
      if (phaseRef.current !== 'dragging') return;
      const el = targetRef.current;
      const t = e.changedTouches[0];
      if (!el || !t) {
        cancelDrag();
        return;
      }
      const rawDy = t.clientY - startRef.current.y;
      // 'down' では上方向へ戻した分は距離・速度ともに dismiss に数えない
      const dy = o.direction === 'down' ? Math.max(0, rawDy) : rawDy;
      const velocity =
        o.direction === 'down' ? Math.max(0, velocityRef.current) : velocityRef.current;
      const dismiss = shouldReleaseDismiss({
        dy,
        velocity,
        distanceThresholdPx: o.distanceThresholdPx ?? 110,
        velocityThresholdPxMs: o.velocityThresholdPxMs ?? 0.5,
        minFlingPx: MIN_FLING_PX,
      });
      if (!dismiss) {
        cancelDrag();
        return;
      }
      // 退場: 現在位置から translateY(100%) へ。inline transform は
      // Tailwind v4 の translate プロパティと独立のため滑らかに合成される
      phaseRef.current = 'exiting';
      setIsDragging(false);
      o.onDismissStart?.();
      el.style.transition = `transform ${EXIT_DURATION_MS}ms ${EXIT_EASE}, opacity ${EXIT_DURATION_MS}ms ${EXIT_EASE}`;
      el.style.transform = 'translateY(100%)';
      if (o.fadeWithDrag) el.style.opacity = '0';
      exitTimerRef.current = window.setTimeout(finishExit, EXIT_DURATION_MS + 20);
    },
    [cancelDrag, finishExit],
  );

  const onTouchCancel = useCallback(() => {
    cancelDrag();
  }, [cancelDrag]);

  const bind = useMemo(
    () => ({ onTouchStart, onTouchMove, onTouchEnd, onTouchCancel }),
    [onTouchStart, onTouchMove, onTouchEnd, onTouchCancel],
  );

  return { targetRef, bind, isDragging };
}
