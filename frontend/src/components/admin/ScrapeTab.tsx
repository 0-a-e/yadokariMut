/**
 * 設定モーダル「スクレイプ管理」タブの本体。
 *
 * 統計/ソース/ローテーションの取得と2秒ポーリング、ソース別設定
 * (useSourceSettings)、タスク起動(triggerTask)をここで担い、
 * 表示は区画コンポーネント(SourceList/RotationSection/…)へ委譲する。
 */
import React, { useEffect, useState, useRef, useCallback } from 'react';
import type {
  AdminSourceInfo,
  AdminStats,
  PropertyGeoJSON,
  RotationSourceStatus,
  RotationSettingsResponse,
  ScrapeSettingsResponse,
} from '../../types.ts';
import { Card } from '@/components/ui/card.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import { Alert, AlertDescription } from '@/components/ui/alert.tsx';
import { useSourceSettings } from '../../hooks/useSourceSettings.ts';
import {
  fetchAdminSources,
  fetchAdminStatus,
  fetchRotationSettings as fetchRotationSettingsApi,
  fetchRotationStatus,
  fetchScrapeSettings as fetchScrapeSettingsApi,
  postRotationSettings,
  postScrapeSettings,
  startGeocode,
  startRotationRun,
  startScrape,
  type ScrapeRequestBody,
} from '../../lib/api/admin.ts';
import { apiErrorMessage } from '../../lib/api/client.ts';
import { notify } from '../../lib/notify.ts';
import { nextBatchPrefLabels } from './adminHelpers.ts';
import { SourceList } from './SourceList.tsx';
import { TransferSection } from './TransferSection.tsx';
import { RotationSection } from './RotationSection.tsx';
import { TaskStatusSection } from './TaskStatusSection.tsx';
import { RecentRunsSection } from './RecentRunsSection.tsx';
import { GeoJsonUploadSection } from './GeoJsonUploadSection.tsx';

interface ScrapeTabProps {
  /** モーダルの開閉。閉じている間はポーリングも止める */
  isOpen: boolean;
  onGeoJsonLoaded?: (data: PropertyGeoJSON) => void;
}

export const ScrapeTab: React.FC<ScrapeTabProps> = ({ isOpen, onGeoJsonLoaded }) => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [sources, setSources] = useState<AdminSourceInfo[]>([]);
  const [rotationSources, setRotationSources] = useState<RotationSourceStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  /** Selected prefecture slugs per source id */
  const [selectedPrefs, setSelectedPrefs] = useState<Record<string, string[]>>({});
  /** ソース別スクレイプ設定(取得間隔/制限時クールダウン)の実効値 */
  const [scrapeSettings, setScrapeSettings] = useState<ScrapeSettingsResponse | null>(null);
  /** ソース別ローテーション設定(日次上限/既定1県件数)の実効値 */
  const [rotationSettings, setRotationSettings] = useState<RotationSettingsResponse | null>(null);
  const consoleRef = useRef<HTMLPreElement>(null);

  const fetchStats = useCallback(async () => {
    try {
      setStats(await fetchAdminStatus());
      setError(null);
    } catch (err: unknown) {
      console.error(err);
      setError('接続エラー: サーバーが起動していない可能性があります。');
    }
  }, []);

  const fetchSources = useCallback(async () => {
    try {
      setSources((await fetchAdminSources()).sources || []);
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchRotation = useCallback(async () => {
    try {
      setRotationSources((await fetchRotationStatus()).sources || []);
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchScrapeSettings = useCallback(async () => {
    try {
      setScrapeSettings(await fetchScrapeSettingsApi());
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchRotationSettings = useCallback(async () => {
    try {
      setRotationSettings(await fetchRotationSettingsApi());
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    fetchStats();
    fetchSources();
    fetchRotation();
    fetchScrapeSettings();
    fetchRotationSettings();
    const interval = setInterval(() => {
      fetchStats();
      fetchSources();
      fetchRotation();
    }, 2000);
    return () => clearInterval(interval);
  }, [isOpen, fetchStats, fetchSources, fetchRotation, fetchScrapeSettings, fetchRotationSettings]);

  // スクレイプ設定: 下書き管理・保存・既定戻しは useSourceSettings に委譲
  const scrapeCtl = useSourceSettings({
    settings: scrapeSettings,
    keys: ['delay_seconds', 'cooldown_seconds'] as const,
    postSettings: postScrapeSettings,
    refetch: fetchScrapeSettings,
    draftFromSource: (s) => ({
      delay_seconds: String(s.delay_seconds),
      cooldown_seconds: String(s.cooldown_seconds),
    }),
    parseValue: (v) => {
      const trimmed = v.trim();
      if (trimmed === '') return null;
      const n = Number(trimmed);
      return Number.isFinite(n) ? n : NaN;
    },
    invalidMessage: '数値を入力してください(空欄で既定に戻ります)。',
    savedMessage: '保存しました。次回のスクレイプから適用されます。',
    resetSavedMessage: 'デフォルトに戻して保存しました。次回のスクレイプから適用されます。',
  });

  // ローテーション設定: 同じ下請けをキーと文言だけ変えて再利用
  const rotationCtl = useSourceSettings({
    settings: rotationSettings,
    keys: ['daily_limit', 'default_est'] as const,
    postSettings: postRotationSettings,
    refetch: () => Promise.all([fetchRotationSettings(), fetchRotation()]),
    draftFromSource: (s) => ({
      daily_limit: String(s.daily_limit),
      default_est: String(s.default_est),
    }),
    parseValue: (v) => {
      const trimmed = v.trim();
      if (trimmed === '') return null;
      const n = Number(trimmed);
      return Number.isInteger(n) ? n : NaN;
    },
    invalidMessage: '整数を入力してください(空欄で既定に戻ります)。',
    savedMessage: '保存しました。次回のローテーション実行から適用されます。',
    resetSavedMessage: 'デフォルトに戻して保存しました。次回のローテーション実行から適用されます。',
  });

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [stats?.task_status?.logs]);

  const triggerTask = async (run: () => Promise<unknown>, confirmMsg: string, successMsg: string) => {
    if (!confirm(confirmMsg)) return;
    try {
      await run();
      notify(successMsg);
      fetchStats();
      fetchSources();
    } catch (err: unknown) {
      notify('エラー: ' + apiErrorMessage(err, '起動失敗'), 'error');
    }
  };

  const togglePref = (sourceId: string, slug: string) => {
    setSelectedPrefs((prev) => {
      const cur = new Set(prev[sourceId] || []);
      if (cur.has(slug)) cur.delete(slug);
      else cur.add(slug);
      return { ...prev, [sourceId]: Array.from(cur) };
    });
  };

  const setAllPrefs = (sourceId: string, slugs: string[], checked: boolean) => {
    setSelectedPrefs((prev) => ({
      ...prev,
      [sourceId]: checked ? [...slugs] : [],
    }));
  };

  const triggerScrape = (
    sourceIds: string[] | 'all',
    opts?: { prefs?: string[]; labelExtra?: string },
  ) => {
    const isAll = sourceIds === 'all';
    const label = isAll ? '登録済み全ソース' : (sourceIds as string[]).join(', ');
    const prefs = opts?.prefs;
    const prefNote =
      prefs && prefs.length > 0
        ? `\n対象都道府県: ${prefs.join(', ')}（${prefs.length} 件）`
        : '\n対象: ソースの全都道府県';
    const body: ScrapeRequestBody = {
      sources: isAll ? ['all'] : sourceIds,
      pages: null,
      all_pages: true,
      list_only: false,
      mark_inactive: true,
      geocode: true,
      geocode_limit: 300,
    };
    if (prefs && prefs.length > 0) {
      body.prefs = prefs;
    }
    triggerTask(
      () => startScrape(body),
      `${label} の再取得を開始しますか？${prefNote}\n` +
        '（ページ上限なし・対象県の未掲載は inactive 化・ジオコーディングあり）' +
        (opts?.labelExtra ? `\n${opts.labelExtra}` : ''),
      'スクレイピングタスクを開始しました。',
    );
  };

  const triggerGeocode = () =>
    triggerTask(
      () => startGeocode(100),
      '未解決の住所に対してジオコーディングタスクを開始しますか？',
      'ジオコーディングタスクを開始しました。',
    );

  const triggerRotationRun = (src: RotationSourceStatus) => {
    const labels = nextBatchPrefLabels(src) || '—';
    triggerTask(
      () => startRotationRun(src.id),
      `【${src.display_name}】県ローテーションの 1 バッチを実行しますか？\n` +
        `次回バッチ: ${labels}（予想 ${src.next_batch?.est_items ?? 0} 件）`,
      'ローテーションタスクを開始しました。',
    );
  };

  const isRunning = stats?.task_status?.status === 'running';
  const availableSources = sources.filter((s) => s.available);

  return (
    <>
      {error && (
        <Alert variant="destructive" className="text-xs">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
        <span>HTTP:</span>
        <Badge variant="outline" className="text-xs">
          mode={stats?.http?.mode ?? '…'}
          {stats?.http?.proxy_enabled ? ' · proxy on' : ' · proxy off'}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card size="sm" className="text-center p-3">
          <span className="text-xs text-text-muted block mb-1">総物件数</span>
          <span className="text-lg font-bold text-accent">
            {stats ? stats.db_stats.total_properties : '-'}
          </span>
        </Card>
        <Card size="sm" className="text-center p-3">
          <span className="text-xs text-text-muted block mb-1">座標なし物件</span>
          <span className="text-lg font-bold text-warning">
            {stats ? stats.db_stats.missing_coordinates : '-'}
          </span>
        </Card>
        <Card size="sm" className="text-center p-3">
          <span className="text-xs text-text-muted block mb-1">保存済み物件</span>
          <span className="text-lg font-bold text-success">
            {stats ? stats.db_stats.shortlist.saved || 0 : '-'}
          </span>
        </Card>
      </div>

      {/* Multi-source rescrape */}
      <div>
        <div className="flex justify-between items-center gap-3 mb-3">
          <h3 className="text-sm border-l-[3px] border-primary pl-2 text-text m-0">
            データ源の再取得
          </h3>
          <Button
            size="sm"
            variant="default"
            className="whitespace-nowrap shrink-0 hover:shadow-[0_0_12px_var(--primary-glow)]"
            disabled={isRunning || availableSources.length === 0}
            onClick={() => triggerScrape('all')}
          >
            一括再取得
          </Button>
        </div>
        <p className="text-xs text-text-muted mb-3">
          サイトを展開して都道府県を選び、選択分だけ再取得できます。inactive 化は
          <strong className="font-medium text-text">対象県のみ</strong>
          に限定されます。新しいサイトは adapter 登録とカタログ定義でこの一覧に現れます。
        </p>

        <SourceList
          sources={sources}
          selectedPrefs={selectedPrefs}
          onTogglePref={togglePref}
          onSetAllPrefs={setAllPrefs}
          isRunning={isRunning}
          scrapeSettings={scrapeSettings}
          scrapeCtl={scrapeCtl}
          onTriggerScrape={triggerScrape}
        />

        {/* Nested: transfer metrics (proxy cost estimation), collapsed by default */}
        {stats?.transfer && <TransferSection stats={stats} />}
      </div>

      {/* Prefecture rotation (cron batch scrape) */}
      <RotationSection
        rotationSources={rotationSources}
        rotationSettings={rotationSettings}
        rotationCtl={rotationCtl}
        isRunning={isRunning}
        onRotationRun={triggerRotationRun}
      />

      <div>
        <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
          その他のバックグラウンド操作
        </h3>
        {[
          {
            label: 'ジオコーディング解決',
            desc: '緯度経度のない物件の住所を座標に解決',
            action: triggerGeocode,
            btnLabel: '座標解決',
          },
        ].map(({ label, desc, action, btnLabel }) => (
          <div key={label} className="flex justify-between items-center py-3 gap-4">
            <div>
              <strong className="text-sm block">{label}</strong>
              <span className="text-xs text-text-muted">{desc}</span>
            </div>
            <Button
              size="sm"
              variant="default"
              className="whitespace-nowrap hover:shadow-[0_0_12px_var(--primary-glow)] hover:-translate-y-px"
              onClick={action}
              disabled={isRunning}
            >
              {btnLabel}
            </Button>
          </div>
        ))}
      </div>

      <TaskStatusSection stats={stats} isRunning={isRunning} consoleRef={consoleRef} />

      {/* 直近のスクレイプ実行(DB由来のためプロセス再起動後も残る) */}
      {(stats?.recent_runs?.length ?? 0) > 0 && (
        <RecentRunsSection runs={stats!.recent_runs!} />
      )}

      {onGeoJsonLoaded && (
        <GeoJsonUploadSection
          onGeoJsonLoaded={(data: unknown) => onGeoJsonLoaded(data as PropertyGeoJSON)}
        />
      )}
    </>
  );
};
