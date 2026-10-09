/**
 * 「県ローテーション」区画。ソース別のキュー状態・設定行・1バッチ手動実行。
 * 状態は保持せず、実行値(rotationSettings)と下書き操作(rotationCtl)は ScrapeTab から受ける。
 */
import React from 'react';
import type { RotationSourceStatus, RotationSettingsResponse } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import { Input } from '@/components/ui/input.tsx';
import { FaArrowRotateLeft } from 'react-icons/fa6';
import { Loader2 } from 'lucide-react';
import { LoadingState } from '@/components/shared/LoadingState.tsx';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip.tsx';
import type { SourceSettingsController } from '../../hooks/useSourceSettings.ts';
import { formatAdminTs, nextBatchPrefLabels, ROTATION_REASON_LABELS } from './adminHelpers.ts';

type RotationCtl = SourceSettingsController<'daily_limit' | 'default_est'>;

interface RotationSectionProps {
  rotationSources: RotationSourceStatus[];
  rotationSettings: RotationSettingsResponse | null;
  rotationCtl: RotationCtl;
  isRunning: boolean;
  onRotationRun: (src: RotationSourceStatus) => void;
}

export const RotationSection: React.FC<RotationSectionProps> = ({
  rotationSources,
  rotationSettings,
  rotationCtl,
  isRunning,
  onRotationRun,
}) => {
  return (
    <div>
      <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text">
        県ローテーション
      </h3>
      <p className="text-xs text-text-muted mb-3">
        cron 時刻ごとに各県を 1 バッチずつ順番に取得します。次のバッチを手動で先行実行できます。
      </p>
      {rotationSources.length === 0 ? (
        <LoadingState
          label="ローテーション情報を読み込み中…"
          className="border border-border rounded-lg p-3 text-xs"
        />
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

                {rotationSettings?.sources[src.id] && (
                  /* 設定行: 入力左 / 保存ボタン右(justify-between)。
                      狭幅では flex-wrap で入力行→保存行の順に折り返す */
                  <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2 mb-2 p-2.5 rounded-md border border-border bg-white/[0.02]">
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="flex flex-col gap-1 text-[11px] text-text-muted">
                        <span className="flex items-center gap-1.5">
                          日次取得上限(件)
                          {rotationSettings.sources[src.id].saved?.daily_limit !=
                            null && (
                            <Badge variant="outline" className="text-[9px] h-4 px-1">
                              上書き中
                            </Badge>
                          )}
                        </span>
                        <span className="flex items-center gap-1">
                          <Input
                            type="number"
                            step={1}
                            min={1}
                            max={10000}
                            className="h-7 w-24 text-xs"
                            disabled={isRunning}
                            value={rotationCtl.drafts[src.id]?.daily_limit ?? ''}
                            placeholder={`既定 ${rotationSettings.defaults?.daily_limit}`}
                            onChange={(e) =>
                              rotationCtl.updateDraft(src.id, 'daily_limit', e.target.value)
                            }
                          />
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label="デフォルトに戻す"
                                  className="text-text-muted hover:text-text"
                                  disabled={isRunning}
                                  onClick={() =>
                                    rotationCtl.resetKey(src.id, 'daily_limit')
                                  }
                                />
                              }
                            >
                              <FaArrowRotateLeft className="text-xs" />
                            </TooltipTrigger>
                            <TooltipContent>デフォルトに戻す</TooltipContent>
                          </Tooltip>
                        </span>
                      </label>
                      <label className="flex flex-col gap-1 text-[11px] text-text-muted">
                        <span className="flex items-center gap-1.5">
                          既定1県件数(件)
                          {rotationSettings.sources[src.id].saved?.default_est !=
                            null && (
                            <Badge variant="outline" className="text-[9px] h-4 px-1">
                              上書き中
                            </Badge>
                          )}
                        </span>
                        <span className="flex items-center gap-1">
                          <Input
                            type="number"
                            step={1}
                            min={1}
                            max={10000}
                            className="h-7 w-24 text-xs"
                            disabled={isRunning}
                            value={rotationCtl.drafts[src.id]?.default_est ?? ''}
                            placeholder={`既定 ${rotationSettings.defaults?.default_est}`}
                            onChange={(e) =>
                              rotationCtl.updateDraft(src.id, 'default_est', e.target.value)
                            }
                          />
                          <Tooltip>
                            <TooltipTrigger
                              render={
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label="デフォルトに戻す"
                                  className="text-text-muted hover:text-text"
                                  disabled={isRunning}
                                  onClick={() =>
                                    rotationCtl.resetKey(src.id, 'default_est')
                                  }
                                />
                              }
                            >
                              <FaArrowRotateLeft className="text-xs" />
                            </TooltipTrigger>
                            <TooltipContent>デフォルトに戻す</TooltipContent>
                          </Tooltip>
                        </span>
                      </label>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      className="h-7 text-xs whitespace-nowrap"
                      disabled={isRunning}
                      onClick={() => rotationCtl.saveSource(src.id)}
                    >
                      保存
                    </Button>
                  </div>
                )}

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
                    onClick={() => onRotationRun(src)}
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
  );
};
