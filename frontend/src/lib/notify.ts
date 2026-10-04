/**
 * toast による簡易通知ヘルパ。
 *
 * 旧 alert() の置き換え用。エラーは長め(8秒)、それ以外は既定(5秒)で自動消滅する。
 * 決定を問う確認(confirm)は代替できないため、そちらは window.confirm のまま。
 */
import { toast } from '@/components/ui/toast.tsx';
import { createId } from './utils.ts';

export type NotifyType = 'success' | 'error' | 'info' | 'warning';

export function notify(title: string, type: NotifyType = 'success', timeout?: number): void {
  toast.add({
    id: `notify-${createId()}`,
    title,
    type,
    timeout: timeout ?? (type === 'error' ? 8000 : 5000),
  });
}
