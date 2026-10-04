import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../lib/api/client.ts';
import { notify } from '../lib/notify.ts';

/**
 * 設定モーダルの「ソース別設定」下請けフック。
 *
 * AdminModal のスクレイプ設定(delay_seconds/cooldown_seconds)と
 * ローテーション設定(daily_limit/default_est)は、キーと文言が違うだけで
 * 同じライフサイクルを持つ:
 *
 * 1. GET 済みの実効値(settings)から未初期化ソースの下書きを埋める
 * 2. updateDraft: 入力中の下書きを 1 キー更新(空文字 = 既定へ戻す)
 * 3. saveSource: 1 ソース分の下書きを部分マージ保存(空欄は null 送信)
 * 4. resetKey: 1 キーを既定値へ戻す(null 保存 = 上書き削除)
 *
 * API クライアント(lib/api/admin.ts)と初期下書きの組み立て関数を
 * 呼び出し側から注入する。保存・エラーの通知文言(toast)もオプションで受ける。
 */

/** ソース id → 入力中下書き(空文字 = 既定へ戻す) */
export type SourceDrafts<K extends string> = Record<string, Record<K, string>>;

export interface UseSourceSettingsOptions<K extends string, Source> {
  /** GET /api/{scrape,rotation}-settings の応答(実効値)。null の間は下書きを埋めない */
  settings: {
    /** 既定値(プレースホルダ / resetKey の戻し先)。GET 応答では常に値入り */
    defaults?: Record<K, number> | null;
    sources: Record<string, Source>;
  } | null;
  /** draft を初期化・保存するキー一覧(実行順) */
  keys: readonly K[];
  /** POST の設定 API クライアント(部分マージ保存。null で該当キーを既定へ戻す) */
  postSettings: (update: {
    sources: Record<string, Partial<Record<K, number | null>> | null>;
  }) => Promise<unknown>;
  /** 保存成功後の再取得(例: fetchScrapeSettings / Promise.all 2件) */
  refetch: () => Promise<unknown> | void;
  /** ソース1件分の実効値から下書き初期値を組み立てる */
  draftFromSource: (source: Source) => Record<K, string>;
  /** 下書き文字列の数値パース。空欄は null。非数は NaN を返す(保存中断の判定用) */
  parseValue: (value: string) => number | null;
  /** 数値不正時の alert 文言 */
  invalidMessage: string;
  /** 保存成功時の alert 文言 */
  savedMessage: string;
  /** 既定へ戻す保存成功時の alert 文言 */
  resetSavedMessage: string;
}

export interface SourceSettingsController<K extends string> {
  drafts: SourceDrafts<K>;
  updateDraft: (sourceId: string, key: K, value: string) => void;
  /** 1ソース分の下書きを保存。空欄は null(既定へ戻す)として送る */
  saveSource: (sourceId: string) => Promise<void>;
  /** 1キーを既定値へ戻す(null 保存 = 上書き削除)。既定値は BE 応答のみを参照 */
  resetKey: (sourceId: string, key: K) => Promise<void>;
}

export function useSourceSettings<K extends string, Source>(
  options: UseSourceSettingsOptions<K, Source>,
): SourceSettingsController<K> {
  const { settings, keys, draftFromSource } = options;
  const [drafts, setDrafts] = useState<SourceDrafts<K>>({});

  // 設定を取得したら未初期化のソースだけ下書きを実効値で埋める
  // (保存済みの下書き・保存後の再取得は上書きしない)
  useEffect(() => {
    if (!settings) return;
    setDrafts((prev) => {
      const next = { ...prev };
      for (const [sid, source] of Object.entries(settings.sources)) {
        if (!(sid in next)) {
          next[sid] = draftFromSource(source);
        }
      }
      return next;
    });
  }, [settings, draftFromSource]);

  const updateDraft = useCallback(
    (sourceId: string, key: K, value: string) => {
      setDrafts((prev) => ({
        ...prev,
        [sourceId]: {
          ...blankDraft(keys),
          ...prev[sourceId],
          [key]: value,
        },
      }));
    },
    [keys],
  );

  const saveSource = useCallback(
    async (sourceId: string) => {
      const draft = drafts[sourceId];
      if (!draft) return;
      const patch: Partial<Record<K, number | null>> = {};
      for (const key of keys) {
        const parsed = options.parseValue(draft[key]);
        if (Number.isNaN(parsed)) {
          notify(options.invalidMessage, 'error');
          return;
        }
        if (parsed !== null) patch[key] = parsed;
      }

      try {
        await options.postSettings({ sources: { [sourceId]: patch } });
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[sourceId];
          return next;
        });
        await options.refetch();
        notify(options.savedMessage);
      } catch (err: unknown) {
        notify('エラー: ' + apiErrorMessage(err, '保存失敗'), 'error');
      }
    },
    // options オブジェクトは毎レンダリング新しくなるため drafts/keys のみ依存させる
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [drafts, keys],
  );

  const resetKey = useCallback(
    async (sourceId: string, key: K) => {
      const defaultValue = settings?.defaults?.[key];
      if (defaultValue == null) return;
      updateDraft(sourceId, key, String(defaultValue));
      try {
        await options.postSettings({
          sources: {
            [sourceId]: { [key]: null } as Partial<Record<K, number | null>>,
          },
        });
        await options.refetch();
        notify(options.resetSavedMessage);
      } catch (err: unknown) {
        notify('エラー: ' + apiErrorMessage(err, '保存失敗'), 'error');
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [settings, updateDraft, keys],
  );

  return { drafts, updateDraft, saveSource, resetKey };
}

/** 全キーを空文字で初期化した下書き(updateDraft の未初期化ソース分の既定) */
function blankDraft<K extends string>(keys: readonly K[]): Record<K, string> {
  const draft = {} as Record<K, string>;
  for (const key of keys) draft[key] = '';
  return draft;
}
