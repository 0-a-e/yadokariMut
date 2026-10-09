import React from 'react';
import {
  resolvePinBalloonPermanent,
  resolvePinClustering,
  type FeSettings,
} from '../../lib/feSettings.ts';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog.tsx';
import { Switch } from '@/components/ui/switch.tsx';
import { toast } from '@/components/ui/toast.tsx';

interface PropertiesLayerSettingsDialogProps {
  feSettings: FeSettings;
  /** 部分マージ保存。失敗時は null を返す(updateFeSettings と同じ契約) */
  onUpdate: (update: FeSettings) => Promise<FeSettings | null>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * 物件ピン(スタック外の最前面固定レイヤ)の設定モーダル。
 * LayerSettingsDialog がカタログ entry 駆動(feSettings.layers 保存)なのに対し、
 * 物件ピンは entry を持たないため保存先も global(feSettings.global)のみ:
 * - pinClustering: 物件ピンのクラスタリング(既定 true=現行動作)
 * - pinBalloonPermanent: 物件バルーン(ピンのtooltip)の常時表示(既定 false)
 *
 * バルーン常時表示はクラスタ表示中に個別マーカーが描画されないため実効せず、
 * トグルもクラスタリング無効時のみ操作可(保存値は保持し、無効化時に戻せる)。
 * トグルは離散操作のため debounce 無しの即時保存+Toast(契約は LayerSettingsDialog と同一)。
 */
export const PropertiesLayerSettingsDialog: React.FC<PropertiesLayerSettingsDialogProps> = ({
  feSettings,
  onUpdate,
  open,
  onOpenChange,
}) => {
  const clustering = resolvePinClustering(feSettings);
  const balloonPermanent = resolvePinBalloonPermanent(feSettings);

  const saveGlobal = async (
    key: 'pinClustering' | 'pinBalloonPermanent',
    value: boolean,
    successTitle: string,
  ) => {
    const result = await onUpdate({ layers: {}, global: { [key]: value } });
    if (result != null) {
      toast.add({ title: successTitle, timeout: 2500, type: 'success' });
    } else {
      toast.add({ title: '保存に失敗しました', timeout: 4000, type: 'error' });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label="物件ピンの設定">
        <DialogHeader>
          <DialogTitle>物件ピン</DialogTitle>
          <DialogDescription>
            物件ピン(検索結果ピン)の表示に関する設定です。変更は自動保存されます。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {/* ── クラスタリング ── */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-text">物件ピンのクラスタリング</span>
                <p className="m-0 text-[10px] text-text-muted">
                  近接する物件ピンをまとめて表示します。オフにするとすべての物件ピンを個別に描画します。
                </p>
              </div>
              <Switch
                checked={clustering}
                onCheckedChange={() => void saveGlobal('pinClustering', !clustering, '保存しました')}
                aria-label="物件ピンのクラスタリング"
              />
            </div>
            <p className="m-0 text-[10px] text-text-muted">
              保存済み: {clustering ? '有効' : '無効'}(初期値: 有効)
            </p>
          </div>

          {/* ── 物件バルーン常時表示(クラスタリング無効時のみ実効) ── */}
          <div className="flex flex-col gap-1.5 border-t border-border pt-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-text">物件バルーンの常時表示</span>
                <p className="m-0 text-[10px] text-text-muted">
                  すべての物件ピンに詳細バルーンを常時表示します(ピン数が多いほど描画負荷が上がります)。
                </p>
              </div>
              <Switch
                checked={balloonPermanent}
                disabled={!clustering}
                onCheckedChange={() =>
                  void saveGlobal('pinBalloonPermanent', !balloonPermanent, '保存しました')
                }
                aria-label="物件バルーンの常時表示"
              />
            </div>
            <p className="m-0 text-[10px] text-text-muted">
              {clustering
                ? 'クラスタリング無効時のみ設定できます(保存値は保持されます)。'
                : '保存済み: ' + (balloonPermanent ? '有効' : '無効') + '(初期値: 無効)'}
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
