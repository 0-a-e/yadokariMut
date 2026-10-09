import type { ReactNode } from 'react';
import { Spinner } from '@/components/ui/spinner.tsx';
import { cn } from '../../lib/utils.ts';

/** 読み込み中表示(スピナー+中央寄せ)。テキストのみの薄い用法は className 上書きで対応 */
export function LoadingState({
  label = '読み込み中…',
  className,
}: {
  label?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn('flex items-center justify-center py-16 text-text-muted', className)}
    >
      {/* スピナー自体は装飾(可視ラベルを status として読み上げる) */}
      <Spinner aria-hidden="true" className="mr-2" />
      {label}
    </div>
  );
}
