import { useCallback, useEffect, useRef, useState } from 'react';
import { configureAdapter } from '../lib/layers/adapters/index.ts';
import {
  EMPTY_FE_SETTINGS,
  type FeSettings,
} from '../lib/feSettings.ts';
import { fetchFeSettings, postFeSettings } from '../lib/api/feSettings.ts';

/**
 * バックエンド保存のフロントエンド設定(レイヤ毎/全体のデフォルト)。
 *
 * - 起動時に取得。失敗時は EMPTY(カタログ既定で動作、起動をブロックしない)
 * - updateFeSettings は部分マージ保存。失敗時は null を返す
 *   (自動保存+Toast は呼び出し側 UI の責務)
 * - oshima アダプタへクラスタリング設定を即時反映
 */
export function useFeSettings(): {
  feSettings: FeSettings;
  feSettingsRef: React.MutableRefObject<FeSettings>;
  updateFeSettings: (update: FeSettings) => Promise<FeSettings | null>;
} {
  const [feSettings, setFeSettings] = useState<FeSettings>(EMPTY_FE_SETTINGS);
  const feSettingsRef = useRef(feSettings);

  useEffect(() => {
    feSettingsRef.current = feSettings;
  }, [feSettings]);

  useEffect(() => {
    let alive = true;
    fetchFeSettings().then((s) => {
      if (alive) setFeSettings(s);
    });
    return () => {
      alive = false;
    };
  }, []);

  const updateFeSettings = useCallback(async (update: FeSettings): Promise<FeSettings | null> => {
    try {
      const next = await postFeSettings(update);
      setFeSettings(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  // oshimaアダプタへクラスタリング設定を反映(変更時はアクティブレイヤへ即時通知される)
  useEffect(() => {
    configureAdapter('oshima', { clustering: feSettings.layers.oshima?.clustering ?? false });
  }, [feSettings.layers.oshima?.clustering]);

  return { feSettings, feSettingsRef, updateFeSettings };
}
