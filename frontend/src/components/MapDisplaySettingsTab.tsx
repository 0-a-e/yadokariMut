import React, { useState } from 'react';
import { resolvePinClustering, type FeSettings } from '../lib/feSettings';

/**
 * 管理者モーダル「地図表示」タブ。
 * 表示ON/OFF系のグローバル設定(feSettings.global)の置き場。
 * 将来追加予定の表示設定(ラベル表示・デフォルト透明度など)もここに並べる。
 *
 * トグルの表示値は props(feSettings) 由来のため、保存失敗時は
 * setFeSettings が走らず自動で元の値に戻る(楽観更新しない)。
 * Toastは別branchで導入予定のため、失敗は簡易テキストで表示する。
 */
interface MapDisplaySettingsTabProps {
  feSettings: FeSettings;
  /** App の updateFeSettings(部分マージ保存。失敗時 null) */
  onUpdate: (update: FeSettings) => Promise<FeSettings | null>;
}

export const MapDisplaySettingsTab: React.FC<MapDisplaySettingsTabProps> = ({
  feSettings,
  onUpdate,
}) => {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pinClustering = resolvePinClustering(feSettings);

  const handlePinClusteringChange = async (value: boolean) => {
    if (value === pinClustering || saving) return;
    setSaving(true);
    setError(null);
    const next = await onUpdate({
      ...feSettings,
      global: { ...feSettings.global, pinClustering: value },
    });
    if (!next) {
      setError('設定の保存に失敗しました。サーバーが起動しているか確認してください。');
    }
    setSaving(false);
  };

  return (
    <div className="flex flex-col gap-5 min-w-0">
      <div>
        <h3 className="text-sm mb-1 border-l-[3px] border-primary pl-2 text-text">
          地図表示
        </h3>
        <p className="text-xs text-text-muted">
          物件ピンやレイヤの見え方に関する表示設定。変更はただちに保存されます。
        </p>
      </div>

      <div className="border border-border rounded-lg">
        <div className="flex items-center justify-between gap-4 px-3 py-3">
          <div className="min-w-0">
            <strong className="text-sm block">物件ピンのクラスタリング</strong>
            <span className="text-xs text-text-muted block mt-0.5">
              近接する物件ピンをまとめて表示します。オフにするとすべての物件ピンを個別に描画します。
            </span>
          </div>
          {/* ui/switch が未整備のため簡易スイッチボタン */}
          <button
            type="button"
            role="switch"
            aria-checked={pinClustering}
            aria-label="物件ピンのクラスタリング"
            disabled={saving}
            onClick={() => void handlePinClusteringChange(!pinClustering)}
            className={`relative inline-flex h-[24px] w-[44px] shrink-0 items-center rounded-full transition-colors duration-200 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 ${
              pinClustering ? 'bg-primary' : 'bg-white/15'
            }`}
          >
            <span
              className={`inline-block h-[18px] w-[18px] rounded-full bg-white shadow transition-transform duration-200 ${
                pinClustering ? 'translate-x-[23px]' : 'translate-x-[3px]'
              }`}
            />
          </button>
        </div>
      </div>

      {error && (
        <p className="text-xs text-warning" role="alert">
          {error}
        </p>
      )}
    </div>
  );
};
