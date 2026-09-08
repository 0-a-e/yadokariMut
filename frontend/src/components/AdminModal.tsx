import React, { useEffect, useState, useRef, useCallback } from 'react';
import {
  AdminSourceInfo,
  AdminStats,
  PropertyGeoJSON,
  RotationSourceStatus,
} from '../types';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion';
import { FaGear, FaXmark, FaCloudArrowUp, FaCloudArrowDown, FaMapLocationDot } from 'react-icons/fa6';
import { Loader2 } from 'lucide-react';
import { MapDisplaySettingsTab } from './MapDisplaySettingsTab';
import type { FeSettings } from '../lib/feSettings';

interface AdminModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGeoJsonLoaded?: (data: PropertyGeoJSON) => void;
  /** フロントエンド設定(地図表示タブで表示・更新) */
  feSettings?: FeSettings;
  /** App の updateFeSettings(部分マージ保存。失敗時 null) */
  onFeSettingsUpdate?: (update: FeSettings) => Promise<FeSettings | null>;
}

function formatAdminTs(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 16);
    return d.toLocaleString('ja-JP', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso.slice(0, 16);
  }
}

/** next_batch.reason の日本語表示マップ（未登録コードはそのまま表示） */
const ROTATION_REASON_LABELS: Record<string, string> = {
  daily_budget_exhausted: '本日の予算を使い切り',
};

/** run/task ステータス → バッジ配色(エラー=赤・部分失敗/中断=黄・OK=緑) */
function runStatusBadgeClass(status: string | null | undefined): string {
  switch (status) {
    case 'error':
      return 'bg-danger/[0.12] text-danger border-danger/30';
    case 'partial':
    case 'aborted':
      return 'bg-warning/[0.12] text-warning border-warning/30';
    case 'running':
      return 'bg-primary/10 text-primary border-primary/30';
    default:
      return 'bg-success/10 text-success border-success/30';
  }
}

/** 次回バッチ対象県の表示ラベル（県名があれば名前、無ければ slug） */
function nextBatchPrefLabels(src: RotationSourceStatus): string {
  const bySlug = new Map((src.prefs || []).map((p) => [p.slug, p]));
  return (src.next_batch?.prefs || [])
    .map((slug) => bySlug.get(slug)?.name || slug)
    .join(', ');
}

/** タブ定義(iPad設定風の左タブ列。モバイル幅では横並び上部タブ) */
type AdminTabId = 'scrape' | 'map';

const ADMIN_TABS: ReadonlyArray<{ id: AdminTabId; label: string; icon: React.ReactNode }> = [
  { id: 'scrape', label: 'スクレイプ管理', icon: <FaCloudArrowDown /> },
  { id: 'map', label: '地図表示', icon: <FaMapLocationDot /> },
];

export const AdminModal: React.FC<AdminModalProps> = ({ isOpen, onClose, onGeoJsonLoaded, feSettings, onFeSettingsUpdate }) => {
  const [activeTab, setActiveTab] = useState<AdminTabId>('scrape');
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [sources, setSources] = useState<AdminSourceInfo[]>([]);
  const [rotationSources, setRotationSources] = useState<RotationSourceStatus[]>([]);
  const [dataLayer, setDataLayer] = useState<'v1' | 'v2' | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Selected prefecture slugs per source id */
  const [selectedPrefs, setSelectedPrefs] = useState<Record<string, string[]>>({});
  const consoleRef = useRef<HTMLPreElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/status');
      if (!res.ok) throw new Error('Could not fetch status');
      const data = await res.json();
      setStats(data);
      if (data.data_layer) setDataLayer(data.data_layer);
      setError(null);
    } catch (err: unknown) {
      console.error(err);
      setError('接続エラー: サーバーが起動していない可能性があります。');
    }
  }, []);

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/sources');
      if (!res.ok) throw new Error('Could not fetch sources');
      const data = await res.json();
      setSources(data.sources || []);
      if (data.data_layer) setDataLayer(data.data_layer);
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchRotation = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/rotation');
      if (!res.ok) throw new Error('Could not fetch rotation status');
      const data = await res.json();
      setRotationSources(data.sources || []);
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    fetchStats();
    fetchSources();
    fetchRotation();
    const interval = setInterval(() => {
      fetchStats();
      fetchSources();
      fetchRotation();
    }, 2000);
    return () => clearInterval(interval);
  }, [isOpen, fetchStats, fetchSources, fetchRotation]);

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [stats?.task_status?.logs]);

  const triggerTask = async (url: string, confirmMsg: string, successMsg: string, init?: RequestInit) => {
    if (!confirm(confirmMsg)) return;
    try {
      const res = await fetch(url, { method: 'POST', ...init });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || '起動失敗');
      }
      alert(successMsg);
      fetchStats();
      fetchSources();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      alert('エラー: ' + msg);
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

  const triggerScrapeV2 = (
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
    const body: Record<string, unknown> = {
      sources: isAll ? ['all'] : sourceIds,
      pages: null,
      all_pages: true,
      mark_inactive: true,
      geocode: true,
      geocode_limit: 300,
    };
    if (prefs && prefs.length > 0) {
      body.prefs = prefs;
    }
    triggerTask(
      '/api/admin/scrape-v2',
      `【v2】${label} の再取得を開始しますか？${prefNote}\n` +
        '（ページ上限なし・対象県の未掲載は inactive 化・ジオコーディングあり）' +
        (opts?.labelExtra ? `\n${opts.labelExtra}` : ''),
      'v2 スクレイピングタスクを開始しました。',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    );
  };

  const triggerGeocode = () =>
    triggerTask(
      '/api/admin/geocode?limit=100',
      '未解決の住所に対してジオコーディングタスクを開始しますか？',
      'ジオコーディングタスクを開始しました。',
    );
  const triggerScore = () =>
    triggerTask(
      '/api/admin/score',
      'すべての物件に対して通勤スコア等の再計算を開始しますか？（v1 スコアリング）',
      'スコア再計算タスクを開始しました。',
    );

  const triggerRotationRun = (src: RotationSourceStatus) => {
    const labels = nextBatchPrefLabels(src) || '—';
    triggerTask(
      '/api/admin/rotation/run',
      `【${src.display_name}】県ローテーションの 1 バッチを実行しますか？\n` +
        `次回バッチ: ${labels}（予想 ${src.next_batch?.est_items ?? 0} 件）`,
      'ローテーションタスクを開始しました。',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: src.id }),
      },
    );
  };

  const isRunning = stats?.task_status?.status === 'running';
  const taskResult = stats?.task_status?.last_result ?? null;
  // 待機中は直前タスクの結果をバッジに反映(エラー/一部失敗を見逃さない)
  const taskError = !isRunning ? stats?.task_status.error ?? null : null;
  const idleBadgeStatus = taskError
    ? 'error'
    : taskResult === 'partial'
      ? 'partial'
      : 'ok';
  const availableSources = sources.filter((s) => s.available);

  const readGeoJsonFile = (file: File) => {
    if (!onGeoJsonLoaded) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        onGeoJsonLoaded(JSON.parse(evt.target?.result as string));
        alert('GeoJSON を読み込みました。');
      } catch {
        alert('JSONパースに失敗しました。正しいGeoJSONファイルを選択してください。');
      }
    };
    reader.readAsText(file);
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="w-[calc(100%-2rem)] h-[calc(100dvh-2rem)] sm:w-[calc(100%-4rem)] sm:h-[calc(100dvh-4rem)] max-w-none sm:max-w-none flex flex-col overflow-hidden bg-panel backdrop-blur-glass p-0 gap-0 [&>*]:min-w-0"
      >
        <DialogHeader className="flex flex-row justify-between items-center py-[18px] px-5 border-b border-border gap-0 shrink-0">
          <DialogTitle className="text-base font-semibold text-text flex items-center gap-2">
            <FaGear /> 設定
          </DialogTitle>
          <Button variant="ghost" size="icon-sm" onClick={onClose}>
            <FaXmark className="text-lg text-text-muted" />
          </Button>
        </DialogHeader>

        {/* ── 垂直タブ列 + コンテンツ(iPad設定風) ──
            モーダルは画面基準の固定サイズ(4辺等幅の余白)で、スクロールは
            コンテンツペイン側のみ。モバイル(<640px)ではタブが横並び上部。
            タブ列の背景は bg-panel が半透明のため不透明色を敷く */}
        <div className="flex flex-col sm:flex-row flex-1 min-h-0 min-w-0">
          <div
            role="tablist"
            aria-label="設定カテゴリ"
            className="flex sm:flex-col gap-1 w-full sm:w-[192px] shrink-0 p-2 border-b sm:border-b-0 sm:border-r border-border bg-[#161821] z-10"
          >
            {ADMIN_TABS.map((tab) => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTab(tab.id)}
                  className={
                    'flex-1 sm:flex-none flex items-center justify-center sm:justify-start gap-2 rounded-md px-3 py-2 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ' +
                    (active
                      ? 'bg-primary/15 text-text'
                      : 'text-text-muted hover:bg-white/[0.04] hover:text-text')
                  }
                >
                  <span className="text-base shrink-0">{tab.icon}</span>
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="p-5 flex flex-col gap-5 min-w-0 flex-1 overflow-y-auto app-scrollbar">
          {activeTab === 'scrape' ? (
          <>
          {error && (
            <Alert variant="destructive" className="text-xs">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
            <span>データ層:</span>
            <Badge variant="outline" className="text-xs">
              {dataLayer || stats?.data_layer || '…'}
            </Badge>
            <span>HTTP:</span>
            <Badge variant="outline" className="text-xs">
              mode={stats?.http?.mode ?? '…'}
              {stats?.http?.proxy_enabled ? ' · proxy on' : ' · proxy off'}
            </Badge>
            {dataLayer === 'v1' && (
              <span className="text-warning">再取得ボタンは v2 必須です（compose で v2 を有効化）</span>
            )}
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

          {/* Multi-source rescrape (v2) */}
          <div>
            <div className="flex justify-between items-center gap-3 mb-3">
              <h3 className="text-sm border-l-[3px] border-primary pl-2 text-text m-0">
                データ源の再取得（v2）
              </h3>
              <Button
                size="sm"
                variant="default"
                className="whitespace-nowrap shrink-0 hover:shadow-[0_0_12px_var(--primary-glow)]"
                disabled={isRunning || availableSources.length === 0 || dataLayer === 'v1'}
                onClick={() => triggerScrapeV2('all')}
              >
                一括再取得
              </Button>
            </div>
            <p className="text-xs text-text-muted mb-3">
              サイトを展開して都道府県を選び、選択分だけ再取得できます。inactive 化は
              <strong className="font-medium text-text">対象県のみ</strong>
              に限定されます。新しいサイトは adapter 登録とカタログ定義でこの一覧に現れます。
            </p>

            <div className="border border-border rounded-lg overflow-hidden">
              {sources.length === 0 && (
                <div className="p-3 text-xs text-text-muted">ソース情報を読み込み中…</div>
              )}
              <Accordion>
                {sources.map((src) => {
                  const targets = src.targets || [];
                  const slugs = targets.map((t) => t.slug);
                  const selected = selectedPrefs[src.id] || [];
                  const allSelected =
                    slugs.length > 0 && slugs.every((s) => selected.includes(s));
                  const scrapedN = targets.filter((t) => t.has_data).length;

                  return (
                    <AccordionItem key={src.id} value={src.id} className="border-b border-border last:border-b-0 px-0">
                      <div className="flex items-stretch gap-0">
                        <AccordionTrigger className="flex-1 px-3 py-3 hover:no-underline text-left min-w-0">
                          <div className="min-w-0 pr-2">
                            <div className="flex items-center gap-2 flex-wrap">
                              <strong className="text-sm">{src.display_name}</strong>
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {src.id}
                              </Badge>
                              {!src.available && (
                                <Badge variant="secondary" className="text-[10px]">
                                  未接続
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-text-muted mt-1 font-normal">
                              有効 {src.counts.active} / 全体 {src.counts.total}
                              {src.counts.missing_coords > 0
                                ? ` · 座標なし ${src.counts.missing_coords}`
                                : ''}
                              {targets.length
                                ? ` · 都道府県 ${scrapedN}/${targets.length} 取得済`
                                : src.prefectures?.length
                                  ? ` · 都道府県 ${src.prefectures.length}`
                                  : ''}
                            </p>
                          </div>
                        </AccordionTrigger>
                        <div className="flex items-center pr-3 shrink-0">
                          <Button
                            size="sm"
                            variant="default"
                            className="whitespace-nowrap"
                            disabled={isRunning || !src.available || dataLayer === 'v1'}
                            onClick={(e) => {
                              e.stopPropagation();
                              triggerScrapeV2([src.id]);
                            }}
                          >
                            全県再取得
                          </Button>
                        </div>
                      </div>
                      <AccordionContent className="px-3 pb-3">
                        {src.description && (
                          <p className="text-xs text-text-muted mb-2">{src.description}</p>
                        )}
                        {targets.length === 0 ? (
                          <p className="text-xs text-text-muted">
                            都道府県ターゲットがありません（adapter 未接続または未定義）。
                          </p>
                        ) : (
                          <>
                            <div className="flex flex-wrap items-center gap-2 mb-2">
                              <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                                <input
                                  type="checkbox"
                                  className="rounded border-border"
                                  checked={allSelected}
                                  disabled={isRunning || !src.available}
                                  onChange={(e) =>
                                    setAllPrefs(src.id, slugs, e.target.checked)
                                  }
                                />
                                全選択
                              </label>
                              <span className="text-[11px] text-text-muted">
                                選択 {selected.length} / {targets.length}
                              </span>
                              <Button
                                size="sm"
                                variant="secondary"
                                className="ml-auto whitespace-nowrap h-7 text-xs"
                                disabled={
                                  isRunning ||
                                  !src.available ||
                                  dataLayer === 'v1' ||
                                  selected.length === 0
                                }
                                onClick={() =>
                                  triggerScrapeV2([src.id], {
                                    prefs: selected,
                                  })
                                }
                              >
                                選択した県を再取得
                              </Button>
                            </div>
                            <div className="max-h-52 overflow-y-auto border border-border rounded-md divide-y divide-border app-scrollbar">
                              {targets.map((t) => {
                                const checked = selected.includes(t.slug);
                                return (
                                  <label
                                    key={t.slug}
                                    className="flex items-start gap-2 px-2 py-1.5 text-xs cursor-pointer hover:bg-white/[0.03]"
                                  >
                                    <input
                                      type="checkbox"
                                      className="mt-0.5 rounded border-border shrink-0"
                                      checked={checked}
                                      disabled={isRunning || !src.available}
                                      onChange={() => togglePref(src.id, t.slug)}
                                    />
                                    <span className="min-w-0 flex-1">
                                      <span className="flex items-center gap-1.5 flex-wrap">
                                        <span className="font-medium text-text">
                                          {t.name}
                                        </span>
                                        <span className="font-mono text-[10px] text-text-muted">
                                          {t.slug}
                                        </span>
                                        {!t.has_data ? (
                                          <Badge
                                            variant="secondary"
                                            className="text-[9px] h-4 px-1"
                                          >
                                            未取得
                                          </Badge>
                                        ) : (
                                          <Badge
                                            variant="outline"
                                            className="text-[9px] h-4 px-1"
                                          >
                                            有効 {t.counts.active}
                                          </Badge>
                                        )}
                                        {t.last_run_status && (
                                          <Badge
                                            variant="outline"
                                            className={`text-[9px] h-4 px-1 font-mono ${runStatusBadgeClass(
                                              t.last_run_status,
                                            )}`}
                                          >
                                            run:{t.last_run_status}
                                          </Badge>
                                        )}
                                      </span>
                                      <span className="block text-[11px] text-text-muted mt-0.5">
                                        最終物件 {formatAdminTs(t.last_seen_at)}
                                        {' · '}
                                        最終クロール {formatAdminTs(t.last_run_at)}
                                        {t.counts.missing_coords > 0
                                          ? ` · 座標なし ${t.counts.missing_coords}`
                                          : ''}
                                      </span>
                                    </span>
                                  </label>
                                );
                              })}
                            </div>
                          </>
                        )}
                      </AccordionContent>
                    </AccordionItem>
                  );
                })}
              </Accordion>
            </div>

            {/* Nested: transfer metrics (proxy cost estimation), collapsed by default */}
            {stats?.transfer?.lifetime?.total && (
              <Accordion className="mt-3">
                <AccordionItem value="transfer" className="border-0">
                  <AccordionTrigger className="py-2 text-xs font-medium text-text-muted hover:no-underline hover:text-text gap-2">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 min-w-0">
                      <span>スクレイプ転送量</span>
                      <span className="font-normal text-[11px] text-text-muted/80">
                        プロセス累計 · DL{' '}
                        {stats.transfer.lifetime.total.bytes_downloaded_mb} MB ·{' '}
                        {stats.transfer.lifetime.total.requests} req
                        {stats.transfer.lifetime.total.restricted_hits > 0
                          ? ` · 制限 ${stats.transfer.lifetime.total.restricted_hits}`
                          : ''}
                      </span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="pb-2">
                    <p className="text-[11px] text-text-muted mb-2">
                      プロキシ API 料金見積もりの参考用。ダウンロード主体。プロセス再起動でリセットされます。
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
                      <Card size="sm" className="p-2 text-center">
                        <span className="text-[10px] text-text-muted block">DL 合計</span>
                        <span className="text-sm font-bold text-accent">
                          {stats.transfer.lifetime.total.bytes_downloaded_mb} MB
                        </span>
                      </Card>
                      <Card size="sm" className="p-2 text-center">
                        <span className="text-[10px] text-text-muted block">リクエスト</span>
                        <span className="text-sm font-bold">
                          {stats.transfer.lifetime.total.requests}
                        </span>
                      </Card>
                      <Card size="sm" className="p-2 text-center">
                        <span className="text-[10px] text-text-muted block">direct / proxy</span>
                        <span className="text-sm font-bold">
                          {stats.transfer.lifetime.total.direct_requests}/
                          {stats.transfer.lifetime.total.proxy_requests}
                        </span>
                      </Card>
                      <Card size="sm" className="p-2 text-center">
                        <span className="text-[10px] text-text-muted block">制限ヒット</span>
                        <span className="text-sm font-bold text-warning">
                          {stats.transfer.lifetime.total.restricted_hits}
                        </span>
                      </Card>
                    </div>
                    {Object.keys(stats.transfer.lifetime.by_source || {}).length > 0 && (
                      <div className="border border-border rounded-lg overflow-hidden text-xs">
                        <div className="grid grid-cols-4 gap-1 bg-white/[0.04] px-2 py-1.5 text-text-muted font-semibold">
                          <span>ソース</span>
                          <span className="text-right">DL MB</span>
                          <span className="text-right">req</span>
                          <span className="text-right">制限</span>
                        </div>
                        {Object.entries(stats.transfer.lifetime.by_source).map(([sid, b]) => (
                          <div
                            key={sid}
                            className="grid grid-cols-4 gap-1 px-2 py-1.5 border-t border-border"
                          >
                            <span className="font-mono truncate">{sid}</span>
                            <span className="text-right">{b.bytes_downloaded_mb}</span>
                            <span className="text-right">{b.requests}</span>
                            <span className="text-right">{b.restricted_hits}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {stats.task_status?.last_transfer?.session?.total && (
                      <p className="text-[11px] text-text-muted mt-2">
                        直近セッション (
                        {stats.task_status.last_transfer.session_label || 'scrape'}): DL{' '}
                        {stats.task_status.last_transfer.session.total.bytes_downloaded_mb} MB /{' '}
                        {stats.task_status.last_transfer.session.total.requests} req
                      </p>
                    )}
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
          </div>

          {/* Prefecture rotation (cron batch scrape) */}
          <div>
            <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
              県ローテーション
            </h3>
            <p className="text-xs text-text-muted mb-3">
              cron 時刻ごとに各県を 1 バッチずつ順番に取得します。次のバッチを手動で先行実行できます。
            </p>
            {rotationSources.length === 0 ? (
              <div className="border border-border rounded-lg p-3 text-xs text-text-muted">
                ローテーション情報を読み込み中…
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {rotationSources.map((src) => {
                  const sortedPrefs = [...src.prefs].sort(
                    (a, b) => a.queue_position - b.queue_position,
                  );
                  const nb = src.next_batch;
                  return (
                    <div key={src.id} className="border border-border rounded-lg p-3">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <strong className="text-sm">{src.display_name}</strong>
                        <Badge variant="outline" className="text-[10px] font-mono">
                          {src.id}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] font-mono">
                          cron {src.cron}
                        </Badge>
                        <span className="ml-auto text-xs text-text-muted whitespace-nowrap">
                          本日 {src.used_today} / {src.daily_limit} 件
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2 text-xs">
                        <span className="text-text-muted">次回バッチ:</span>
                        <span className="font-medium text-text">
                          {nextBatchPrefLabels(src) || '—'}
                        </span>
                        <span className="text-text-muted">
                          予想 {nb?.est_items ?? 0} 件
                        </span>
                        {nb?.unlimited && (
                          <Badge variant="secondary" className="text-[10px]">
                            上限無視(単独県)
                          </Badge>
                        )}
                        {nb?.reason && (
                          <span className="text-warning">
                            {ROTATION_REASON_LABELS[nb.reason] || nb.reason}
                          </span>
                        )}
                        <Button
                          size="sm"
                          variant="default"
                          className="ml-auto whitespace-nowrap h-7 text-xs hover:shadow-[0_0_12px_var(--primary-glow)]"
                          disabled={isRunning}
                          onClick={() => triggerRotationRun(src)}
                        >
                          1バッチ実行
                        </Button>
                      </div>

                      <div className="max-h-60 overflow-auto border border-border rounded-md app-scrollbar text-xs">
                        <div className="w-max min-w-full">
                        <div className="grid grid-cols-[2.5rem_minmax(0,1fr)_4.5rem_5.5rem_6rem_6rem] gap-1 divide-x divide-border/60 bg-white/[0.04] px-2 py-1.5 text-text-muted font-semibold">
                          <span>順位</span>
                          <span>県名</span>
                          <span className="text-right">既知件数</span>
                          <span className="text-right">連続失敗</span>
                          <span>前回完全取得</span>
                          <span>前回実行</span>
                        </div>
                        {sortedPrefs.map((p) => (
                          <div
                            key={p.slug}
                            className={
                              'grid grid-cols-[2.5rem_minmax(0,1fr)_4.5rem_5.5rem_6rem_6rem] gap-1 divide-x divide-border/60 px-2 py-1.5 border-t border-border' +
                              (p.is_running === true ? ' bg-primary/[0.06]' : '')
                            }
                          >
                            <span className="font-mono text-text-muted">
                              {p.queue_position}
                            </span>
                            <span className="flex items-center justify-between gap-1 min-w-0">
                              <span className="truncate min-w-0">
                                <span className="font-medium text-text">{p.name}</span>{' '}
                                <span className="font-mono text-[10px] text-text-muted">
                                  {p.slug}
                                </span>
                              </span>
                              {p.is_running === true && (
                                <Loader2
                                  className="size-3 animate-spin shrink-0 text-primary"
                                  aria-label="取得中"
                                />
                              )}
                            </span>
                            <span className="text-right">{p.known_total ?? '-'}</span>
                            <span className="flex items-center justify-end gap-1">
                              <span
                                className={
                                  p.consecutive_failures ? '' : 'text-text-muted'
                                }
                              >
                                {p.consecutive_failures ?? 0}
                              </span>
                              {p.suppressed === true && (
                                <Badge className="border-warning/30 bg-warning/[0.15] px-1.5 text-[10px] text-warning">
                                  抑止中
                                </Badge>
                              )}
                            </span>
                            <span className={p.last_full_ok_at ? '' : 'text-text-muted'}>
                              {p.last_full_ok_at ? formatAdminTs(p.last_full_ok_at) : '未取得'}
                            </span>
                            <span>{formatAdminTs(p.last_run_at)}</span>
                          </div>
                        ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

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
              {
                label: 'スコア再計算',
                desc: '全物件の主要駅への通勤時間スコア等を一括更新',
                action: triggerScore,
                btnLabel: 'スコア再計算',
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

          <div>
            <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
              タスクステータス & 実行ログ
            </h3>
            <Badge
              variant={isRunning ? 'default' : 'outline'}
              className={`mb-2 text-xs ${
                isRunning
                  ? 'bg-warning/[0.15] text-warning border-warning/30'
                  : runStatusBadgeClass(idleBadgeStatus)
              }`}
            >
              ステータス:{' '}
              {stats
                ? isRunning
                  ? `実行中 (${stats.task_status.current_task})`
                  : taskError
                    ? 'エラーあり'
                    : taskResult === 'partial'
                      ? '一部失敗 (partial)'
                      : '待機中 (Idle)'
                : '読み込み中...'}
            </Badge>
            {!isRunning && taskError && (
              <p className="mb-2 text-xs leading-snug text-danger/90 break-all">
                {taskError}
              </p>
            )}
            <pre
              className="bg-black/40 text-[#a5b4fc] font-mono p-3 rounded-md text-xs max-h-40 overflow-y-auto whitespace-pre-wrap border border-border"
              ref={consoleRef}
            >
              {stats && stats.task_status.logs.length > 0
                ? stats.task_status.logs.join('\n')
                : '実行ログはありません。'}
            </pre>
          </div>

          {/* 直近のスクレイプ実行(DB由来のためプロセス再起動後も残る) */}
          {(stats?.recent_runs?.length ?? 0) > 0 && (
            <div>
              <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text flex items-baseline gap-2 flex-wrap">
                直近のスクレイプ実行
                <span className="text-[11px] font-normal text-text-muted">
                  DB記録・再起動後も保持
                </span>
              </h3>
              <div className="max-h-44 overflow-y-auto border border-border rounded-md divide-y divide-border app-scrollbar">
                {stats!.recent_runs!.map((r) => (
                  <div key={r.id} className="px-2 py-1.5 text-xs">
                    <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                      <Badge
                        variant="outline"
                        className={`text-[9px] h-4 px-1 font-mono ${runStatusBadgeClass(r.status)}`}
                      >
                        {r.status}
                      </Badge>
                      <span className="font-medium text-text">{r.source_site}</span>
                      <span className="font-mono text-[10px] text-text-muted">
                        #{r.id}
                      </span>
                      <span className="font-mono text-[10px] text-text-muted whitespace-nowrap">
                        {formatAdminTs(r.started_at)}〜{formatAdminTs(r.finished_at)}
                      </span>
                      <span className="font-mono text-[10px] text-text-muted whitespace-nowrap">
                        {r.list_items ?? 0}件・詳細 ok:{r.detail_ok ?? 0} fail:
                        {r.detail_fail ?? 0}
                      </span>
                    </div>
                    {r.error_summary && (
                      <p
                        className={`mt-0.5 text-[10px] leading-snug break-all ${
                          r.status === 'error' ? 'text-danger/80' : 'text-text-muted'
                        }`}
                      >
                        {r.error_summary.length > 300
                          ? `${r.error_summary.slice(0, 300)}…`
                          : r.error_summary}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {onGeoJsonLoaded && (
            <div>
              <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
                開発用: GeoJSON 読込
              </h3>
              <div
                className="border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all duration-300 bg-white/[0.01] hover:border-primary hover:bg-primary/[0.05]"
                style={{
                  borderColor: isDragOver ? 'var(--accent)' : 'rgba(133, 77, 255, 0.3)',
                }}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragOver(true);
                }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragOver(false);
                  const file = e.dataTransfer.files?.[0];
                  if (file) readGeoJsonFile(file);
                }}
              >
                <FaCloudArrowUp className="text-2xl text-primary mb-2 inline-block" />
                <p className="text-sm text-text-muted">
                  <b>map.geojson</b> をアップロード
                </p>
                <p className="text-xs text-text-muted mt-1">
                  通常は API 経由で読み込みます（開発・デバッグ用）
                </p>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) readGeoJsonFile(file);
                  }}
                  accept=".geojson,application/json"
                  hidden
                />
              </div>
            </div>
          )}
          </>
          ) : feSettings && onFeSettingsUpdate ? (
            /* ── 地図表示タブ ── */
            <MapDisplaySettingsTab feSettings={feSettings} onUpdate={onFeSettingsUpdate} />
          ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
