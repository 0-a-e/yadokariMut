import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog.tsx';
import { Button } from '@/components/ui/button.tsx';
import { onSessionExpired, relogin } from '@/lib/accessAuth.ts';

/**
 * Cloudflare Access のセッション切れを通知する全共通ダイアログ。
 * lib/accessAuth の fetch ガードが認証 302 を検出すると表示され、
 * 「再ログイン」で SW / Cache Storage 解除 → 再読み込み（Access 再認証 →
 * 元の URL へ復帰）を行う。
 */
export function AccessSessionDialog() {
  const [open, setOpen] = useState(false);

  useEffect(
    () =>
      onSessionExpired(() => {
        setOpen(true);
      }),
    [],
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent showCloseButton={false} className="max-w-[440px] bg-panel backdrop-blur-glass">
        <DialogHeader>
          <DialogTitle>ログインセッションの有効期限が切れました</DialogTitle>
          <DialogDescription>
            Cloudflare Access の再認証が必要です。再ログインすると元の画面に戻ります。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button onClick={() => void relogin()}>再ログイン</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
