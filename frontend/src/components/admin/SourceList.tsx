/**
 * 「データ源の再取得」のソース別アコーディオン一覧。
 * 状態は保持せず、選択県・下書き・起動は ScrapeTab から受ける。
 */
import React from 'react';
import type { AdminSourceInfo, ScrapeSettingsResponse } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import { Input } from '@/components/ui/input.tsx';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion.tsx';
import { FaArrowRotateLeft } from 'react-icons/fa6';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip.tsx';
import { Checkbox } from '@/components/ui/checkbox.tsx';
import type { SourceSettingsController } from '../../hooks/useSourceSettings.ts';
import { LoadingState } from '@/components/shared/LoadingState.tsx';
import { formatAdminTs, runStatusBadgeClass } from './adminHelpers.ts';

type ScrapeCtl = SourceSettingsController<'delay_seconds' | 'cooldown_seconds'>;

interface SourceListProps {
  sources: AdminSourceInfo[];
  /** ソース id → 選択中の県 slug 一覧 */
  selectedPrefs: Record<string, string[]>;
  onTogglePref: (sourceId: string, slug: string) => void;
  onSetAllPrefs: (sourceId: string, slugs: string[], checked: boolean) => void;
  isRunning: boolean;
  scrapeSettings: ScrapeSettingsResponse | null;
  scrapeCtl: ScrapeCtl;
  onTriggerScrape: (
    sourceIds: string[] | 'all',
    opts?: { prefs?: string[]; labelExtra?: string },
  ) => void;
}

export const SourceList: React.FC<SourceListProps> = ({
  sources,
  selectedPrefs,
  onTogglePref,
  onSetAllPrefs,
  isRunning,
  scrapeSettings,
  scrapeCtl,
  onTriggerScrape,
}) => {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {sources.length === 0 && <LoadingState className="p-3 text-xs" label="ソース情報を読み込み中…" />}
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
              {/* ヘッダー行: テキスト左 / 全県再取得+chevron右。
                  trigger が行全域を覆い(ボタンは上に重なるオーバーレイ)、
                  ボタン以外のクリックで開閉する。chevron は trigger 内置の
                  アイコン(ml-auto)が最右・垂直中央に載る */}
              <div className="relative">
                <AccordionTrigger className="items-center px-3 py-3 hover:no-underline text-left min-w-0">
                  <div className="min-w-0 pr-28">
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
                <div className="absolute right-9 top-1/2 -translate-y-1/2 z-10">
                  <Button
                    size="sm"
                    variant="default"
                    className="whitespace-nowrap"
                    disabled={isRunning || !src.available}
                    onClick={() => onTriggerScrape([src.id])}
                  >
                    全県再取得
                  </Button>
                </div>
              </div>
              <AccordionContent className="px-3 pb-3">
                {src.description && (
                  <p className="text-xs text-text-muted mb-2">{src.description}</p>
                )}
                {scrapeSettings?.sources[src.id] && (
                  /* 設定行: 入力左 / ヒント+保存ボタン右(justify-between)。
                      狭幅では flex-wrap で入力行→ヒント+保存行の順に折り返す */
                  <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2 mb-3 p-2.5 rounded-md border border-border bg-white/[0.02]">
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="flex flex-col gap-1 text-[11px] text-text-muted">
                        <span className="flex items-center gap-1.5">
                          取得間隔(秒)
                          {scrapeSettings.sources[src.id].saved?.delay_seconds !=
                            null && (
                            <Badge variant="outline" className="text-[9px] h-4 px-1">
                              上書き中
                            </Badge>
                          )}
                        </span>
                        <span className="flex items-center gap-1">
                          <Input
                            type="number"
                            step={0.5}
                            min={0.5}
                            max={30}
                            className="h-7 w-24 text-xs"
                            disabled={isRunning || !src.available}
                            value={scrapeCtl.drafts[src.id]?.delay_seconds ?? ''}
                            placeholder={`既定 ${scrapeSettings.defaults?.delay_seconds}`}
                            onChange={(e) =>
                              scrapeCtl.updateDraft(src.id, 'delay_seconds', e.target.value)
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
                                  disabled={isRunning || !src.available}
                                  onClick={() =>
                                    scrapeCtl.resetKey(src.id, 'delay_seconds')
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
                          制限時クールダウン(秒)
                          {scrapeSettings.sources[src.id].saved?.cooldown_seconds !=
                            null && (
                            <Badge variant="outline" className="text-[9px] h-4 px-1">
                              上書き中
                            </Badge>
                          )}
                        </span>
                        <span className="flex items-center gap-1">
                          <Input
                            type="number"
                            step={30}
                            min={0}
                            max={7200}
                            className="h-7 w-24 text-xs"
                            disabled={isRunning || !src.available}
                            value={scrapeCtl.drafts[src.id]?.cooldown_seconds ?? ''}
                            placeholder={`既定 ${scrapeSettings.defaults?.cooldown_seconds}`}
                            onChange={(e) =>
                              scrapeCtl.updateDraft(src.id, 'cooldown_seconds', e.target.value)
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
                                  disabled={isRunning || !src.available}
                                  onClick={() =>
                                    scrapeCtl.resetKey(src.id, 'cooldown_seconds')
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
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-text-muted leading-snug max-w-56">
                        空欄で保存すると既定に戻ります。設定は夜間ローテーションにも適用されます。
                      </span>
                      <Button
                        size="sm"
                        variant="secondary"
                        className="h-7 text-xs whitespace-nowrap"
                        disabled={isRunning || !src.available}
                        onClick={() => scrapeCtl.saveSource(src.id)}
                      >
                        保存
                      </Button>
                    </div>
                  </div>
                )}
                {targets.length === 0 ? (
                  <p className="text-xs text-text-muted">
                    都道府県ターゲットがありません（adapter 未接続または未定義）。
                  </p>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2 mb-2">
                      <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                        <Checkbox
                          checked={allSelected}
                          disabled={isRunning || !src.available}
                          onCheckedChange={(checked) =>
                            onSetAllPrefs(src.id, slugs, checked)
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
                          selected.length === 0
                        }
                        onClick={() =>
                          onTriggerScrape([src.id], {
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
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              disabled={isRunning || !src.available}
                              onCheckedChange={() => onTogglePref(src.id, t.slug)}
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
  );
};
