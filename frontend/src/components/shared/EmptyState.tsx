import type { ComponentType, ReactNode } from 'react';
import { Empty, EmptyDescription, EmptyMedia } from '@/components/ui/empty.tsx';
import { cn } from '../../lib/utils.ts';

/**
 * 空状態表示の正本(docs/fe-floor-orientation-redesign-plan.md §6.1)。
 *
 * 呼び出し側の props(message / className / dashed / icon / iconClassName)は
 * 従来どおりで、17 箇所の呼び出しは無修正のままこの正本へ追従する。
 * - dashed / icon: hextaUI `empty`(base-ui)で組む。破線枠は --hairline、
 *   レイアウトは旧実装と同じく「伸びない」プレースホルダ(flex-none)
 * - それ以外: 表・アコーディオン内に収まる 1 行フォールバック(旧と同じ素の <p>)。
 *   hextaUI Empty は text-center / flex-1 を基底に持つため、親のレイアウトと
 *   文字揃えを引き継ぐ 1 行用法では使わない(§6.1 の「主要箇所のみ移行」方針)
 * 色は既存のプロジェクト固有トークン(text-text-muted)に合わせる。
 */
export function EmptyState({
  message,
  className,
  dashed,
  icon: Icon,
  iconClassName,
}: {
  message: ReactNode;
  className?: string;
  dashed?: boolean;
  icon?: ComponentType<{ className?: string }>;
  iconClassName?: string;
}) {
  if (dashed) {
    return (
      <Empty
        variant="outline"
        size="sm"
        className={cn('flex-none gap-1 rounded-md p-3 text-[11px] text-text-muted', className)}
      >
        {Icon && (
          <EmptyMedia className="mb-0">
            <Icon className={cn('size-4', iconClassName)} />
          </EmptyMedia>
        )}
        <EmptyDescription className="text-[11px] text-text-muted">{message}</EmptyDescription>
      </Empty>
    );
  }
  if (Icon) {
    return (
      <Empty size="sm" className={cn('flex-none gap-1.5 text-sm text-text-muted italic', className)}>
        <EmptyMedia className="mb-0">
          <Icon className={cn('size-5', iconClassName)} />
        </EmptyMedia>
        <EmptyDescription className="text-sm text-text-muted">{message}</EmptyDescription>
      </Empty>
    );
  }
  return <p className={cn('text-sm text-text-muted italic', className)}>{message}</p>;
}
