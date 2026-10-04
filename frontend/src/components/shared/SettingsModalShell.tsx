/**
 * 設定・分析モーダル共通のシェル(全画面ダイアログ + タブ列 + コンテンツペイン)。
 *
 * - タブは base-ui Tabs(ui/tabs)で、矢印キー移動・roving tabindex を得る
 * - キーボードの向きは orientation prop に追従するため、**見た目の縦横も
 *   同じ orientation 値から出す**(CSS ブレークポイントでの切替は行わない)。
 *   判定は Tailwind sm と同一の 640px。基準をずらすと
 *   「見た目は縦並びなのに矢印キーは左右」という不整合が生じる
 * - コンテンツは Panel(TabsContent)を使わず value 制御 + 呼び出し側の
 *   条件/hidden 描画に任せる(タブ往復で状態を保持するスクレイプタブ等のため)
 */
import React from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog.tsx';
import { Button } from '@/components/ui/button.tsx';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs.tsx';
import { FaXmark } from 'react-icons/fa6';
import { useMediaQuery } from '../../hooks/useMediaQuery.ts';
import { cn } from '@/lib/utils.ts';

/** Tailwind の sm ブレークポイントと同一値(これを基準に縦/横タブを切替) */
const SM_QUERY = '(min-width: 640px)';

export interface SettingsModalShellTab<T extends string> {
  id: T;
  label: string;
  icon: React.ReactNode;
}

interface SettingsModalShellProps<T extends string> {
  isOpen: boolean;
  onClose: () => void;
  /** DialogTitle の中身(アイコン+見出し。物件単位バッジ等の追記もここへ) */
  title: React.ReactNode;
  tabs: ReadonlyArray<SettingsModalShellTab<T>>;
  activeTab: T;
  onTabChange: (id: T) => void;
  /** タブ列の aria-label(例: 「設定カテゴリ」) */
  tablistLabel: string;
  /** タブ列とコンテンツの間に差し込む帯(分析モーダルの物件ヘッダ等) */
  headerSlot?: React.ReactNode;
  /** 閉じるボタンの data-testid(テスト用。任意) */
  closeTestId?: string;
  children: React.ReactNode;
}

export function SettingsModalShell<T extends string>({
  isOpen,
  onClose,
  title,
  tabs,
  activeTab,
  onTabChange,
  tablistLabel,
  headerSlot,
  closeTestId,
  children,
}: SettingsModalShellProps<T>) {
  // タブ方向の単一シグナル。640px 未満=横並び上部タブ(モバイル)、以上=左タブ列
  const isWide = useMediaQuery(SM_QUERY);
  const orientation = isWide ? ('vertical' as const) : ('horizontal' as const);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="w-[calc(100%-2rem)] h-[calc(100dvh-2rem)] sm:w-[calc(100%-4rem)] sm:h-[calc(100dvh-4rem)] max-w-none sm:max-w-none flex flex-col overflow-hidden bg-panel backdrop-blur-glass p-0 gap-0 [&>*]:min-w-0"
      >
        <DialogHeader className="flex flex-row justify-between items-center py-[18px] px-5 border-b border-border gap-0 shrink-0">
          <DialogTitle className="text-base font-semibold text-text flex items-center gap-2">
            {title}
          </DialogTitle>
          <Button variant="ghost" size="icon-sm" onClick={onClose} data-testid={closeTestId}>
            <FaXmark className="text-lg text-text-muted" />
          </Button>
        </DialogHeader>

        {headerSlot}

        {/* ── タブ列 + コンテンツ。縦横は orientation 値にのみ依存する ──
            モーダルは画面基準の固定サイズ(4辺等幅の余白)で、スクロールは
            コンテンツペイン側のみ。タブ列の背景は bg-panel が半透明のため
            不透明色を敷く */}
        <Tabs
          orientation={orientation}
          value={activeTab}
          onValueChange={(value) => {
            if (value != null) onTabChange(value as T);
          }}
          className={cn(
            'flex flex-1 min-h-0 min-w-0',
            orientation === 'vertical' ? 'flex-row' : 'flex-col',
          )}
        >
          <TabsList
            aria-label={tablistLabel}
            className={cn(
              'flex h-auto shrink-0 gap-1 rounded-none p-2 bg-[#161821] z-10',
              orientation === 'vertical'
                ? 'flex-col w-[192px] border-b-0 border-r border-border'
                : 'flex-row w-full border-b border-border',
            )}
          >
            {tabs.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className={cn(
                  'h-auto flex items-center gap-2 rounded-md px-3 py-2',
                  'text-xs sm:text-sm font-medium transition-colors whitespace-nowrap',
                  orientation === 'vertical'
                    ? 'w-full flex-none justify-start'
                    : 'flex-1 justify-center',
                  'text-text-muted dark:text-text-muted',
                  'hover:bg-white/[0.04] hover:text-text dark:hover:text-text',
                  'data-active:bg-primary/15 data-active:text-text',
                  'data-active:border-transparent',
                  'dark:data-active:bg-primary/15 dark:data-active:text-text dark:data-active:border-transparent',
                )}
              >
                <span className="text-base shrink-0">{tab.icon}</span>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* padding は呼び出し側コンテンツが持つ(タブ毎に包絡を変えられるように) */}
          <div className="min-w-0 flex-1 overflow-y-auto app-scrollbar">
            {children}
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
