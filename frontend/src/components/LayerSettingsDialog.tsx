import React, { useEffect, useRef, useState } from 'react';
import { catalogById } from '../lib/layers/catalog';
import type { FeSettings, LayerSettingOverrides } from '../lib/feSettings';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { toast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';

/** 自動保存のdebounce待ち(ms) */
const SAVE_DEBOUNCE_MS = 600;

interface LayerSettingsDialogProps {
  layerId: string;
  feSettings: FeSettings;
  /** 部分マージ保存。失敗時は null を返す(updateFeSettings と同じ契約) */
  onUpdate: (update: FeSettings) => Promise<FeSettings | null>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * レイヤ設定モーダル(設計doc §1)。カタログ entry.settings で出し分け。
 * - デフォルト透明度: 0-100%スライダー → 600ms debounce → 自動保存+Toast
 * - [デフォルトに戻す]: 保存済み defaultOpacity を null 送信で削除
 * - clustering(oshima): トグル。注記「無効時はズーム12未満で非表示」
 */
export const LayerSettingsDialog: React.FC<LayerSettingsDialogProps> = ({
  layerId,
  feSettings,
  onUpdate,
  open,
  onOpenChange,
}) => {
  const entry = catalogById.get(layerId);
  const overrides: LayerSettingOverrides | undefined = feSettings.layers[layerId];

  const catalogPct = Math.round((entry?.defaultOpacity ?? 1) * 100);
  const savedOpacity = overrides?.defaultOpacity;
  const savedPct =
    typeof savedOpacity === 'number' ? Math.round(savedOpacity * 100) : null;

  const [opacityPct, setOpacityPct] = useState(() =>
    typeof savedOpacity === 'number' ? Math.round(savedOpacity * 100) : catalogPct,
  );
  const timerRef = useRef<number | null>(null);

  // 保存済み値の変化(取得完了・保存成功・デフォルト戻し)へ追従
  useEffect(() => {
    setOpacityPct(
      typeof savedOpacity === 'number' ? Math.round(savedOpacity * 100) : catalogPct,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layerId, savedOpacity]);

  const clearTimer = () => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const saveOverrides = async (update: LayerSettingOverrides, successTitle: string) => {
    const result = await onUpdate({ layers: { [layerId]: update }, global: {} });
    if (result != null) {
      toast.add({ title: successTitle, timeout: 2500, type: 'success' });
    } else {
      toast.add({ title: '保存に失敗しました', timeout: 4000, type: 'error' });
    }
  };

  /** 600ms debounce 付きの自動保存 */
  const scheduleSave = (update: LayerSettingOverrides, successTitle: string) => {
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      void saveOverrides(update, successTitle);
    }, SAVE_DEBOUNCE_MS);
  };

  const handleOpacityChange = (vals: number | readonly number[]) => {
    const v = Array.isArray(vals) ? vals[0] : vals;
    if (typeof v !== 'number') return;
    setOpacityPct(v);
    scheduleSave({ defaultOpacity: v / 100 }, '保存しました');
  };

  const handleResetOpacity = () => {
    clearTimer();
    setOpacityPct(catalogPct);
    void saveOverrides({ defaultOpacity: null }, 'デフォルトに戻しました');
  };

  const clusteringEnabled = overrides?.clustering === true;
  const showClustering = entry?.settings?.includes('clustering') ?? false;

  const handleClusteringToggle = () => {
    const next = !clusteringEnabled;
    void saveOverrides({ clustering: next }, '保存しました');
  };

  if (!entry) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label={`${entry.name}の設定`}>
        <DialogHeader>
          <DialogTitle>{entry.name}</DialogTitle>
          <DialogDescription>
            このレイヤを追加したときに適用されるデフォルト設定です。変更は自動保存されます。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* ── デフォルト透明度 ── */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-text">デフォルト透明度</span>
              <span className="text-xs tabular-nums text-text-muted">
                {opacityPct}%
              </span>
            </div>
            <Slider
              aria-label={`${entry.name}のデフォルト透明度`}
              value={[opacityPct]}
              onValueChange={handleOpacityChange}
              min={0}
              max={100}
              step={1}
            />
            <div className="flex items-center justify-between gap-2">
              <p className="m-0 text-[10px] text-text-muted">
                カタログ初期値: {catalogPct}% / 保存済み: {savedPct != null ? `${savedPct}%` : 'なし'}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="h-6 shrink-0 px-2 text-[11px] font-semibold text-text-muted hover:text-text"
                onClick={handleResetOpacity}
                disabled={savedPct == null && opacityPct === catalogPct}
              >
                デフォルトに戻す
              </Button>
            </div>
          </div>

          {/* ── クラスタリング(oshima等、settingsに含まれるレイヤのみ) ── */}
          {showClustering && (
            <div className="flex flex-col gap-1.5 border-t border-border pt-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-medium text-text">クラスタリング</span>
                  <p className="m-0 text-[10px] text-text-muted">
                    無効時は常時個別マーカー表示(ズーム12未満では非表示)
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={clusteringEnabled}
                  aria-label={`${entry.name}のクラスタリング`}
                  onClick={handleClusteringToggle}
                  className={cn(
                    'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors outline-none',
                    'focus-visible:border-primary',
                    clusteringEnabled
                      ? 'border-primary bg-primary/70'
                      : 'border-border bg-white/[0.06]',
                  )}
                >
                  <span
                    className={cn(
                      'inline-block size-3.5 rounded-full bg-white shadow transition-transform',
                      clusteringEnabled ? 'translate-x-[18px]' : 'translate-x-[3px]',
                    )}
                  />
                </button>
              </div>
              <p className="m-0 text-[10px] text-text-muted">
                保存済み: {clusteringEnabled ? '有効' : '無効'}(初期値: 無効)
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
