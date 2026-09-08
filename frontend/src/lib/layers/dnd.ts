import React from 'react';
import { PointerSensor } from '@dnd-kit/core';

/**
 * レイヤ行のDnD発火セマンティクス(dnd-kitセンサはリスナーを付けた要素全体で
 * 共通のため、イベント発火元で挙動を切り替える):
 * - ドラッガー(HANDLE_ATTR マーク箇所)  : 制約をバイパスして即時発火
 * - 行本体(操作系を除く全域)           : 長押し発火(delay+tolerance)
 * - 操作系(button 等)                  : 発火しない
 */

/** ドラッグ即時発火ゾーン(グリップアイコン / グループヘッダー)の目印 */
export const DND_HANDLE_ATTR = 'data-dnd-handle';

/** 長押しドラッグの発火から除外する操作系セレクタ */
export const DND_INTERACTIVE_SELECTOR = [
  'button',
  'a',
  'input',
  'select',
  'textarea',
  '[role="slider"]',
  '[role="switch"]',
  '[data-slot="slider"]',
].join(', ');

type DragStartZone = 'handle' | 'body' | null;

/** pointerdown 発火元の分類 */
export function dragStartZone(event: { target: EventTarget | null }): DragStartZone {
  const target = event.target as HTMLElement | null;
  if (!target) return null;
  if (target.closest(`[${DND_HANDLE_ATTR}]`)) return 'handle';
  if (target.closest(DND_INTERACTIVE_SELECTOR)) return null;
  return 'body';
}

/**
 * レイヤ行用の適応型PointerSensor。
 * useSensor(AdaptivePointerSensor, { activationConstraint: { delay, tolerance },
 * bypassActivationConstraint }) と組み合わせて使う。
 * activator は「発火元が操作系以外か」のみを判定し、即時/長押しの分岐は
 * bypassActivationConstraint 側で行う(センサはインスタンスごとに1つの制約しか持てないため)。
 */
export class AdaptivePointerSensor extends PointerSensor {
  static activators = [
    {
      eventName: 'onPointerDown' as const,
      handler: (event: React.PointerEvent) => {
        const { nativeEvent } = event;
        if (!nativeEvent.isPrimary || nativeEvent.button !== 0) return false;
        return dragStartZone(event) != null;
      },
    },
  ] as unknown as typeof PointerSensor['activators'];
}
