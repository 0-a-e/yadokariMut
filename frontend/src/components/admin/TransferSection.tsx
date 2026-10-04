/**
 * スクレイプ転送量の内訳(プロキシ API 料金見積もり参考用)。
 * 折りたたみアコードン。stats.transfer が無い場合は呼び出し側で非表示にする。
 */
import React from 'react';
import type { AdminStats } from '../../types.ts';
import { Card } from '@/components/ui/card.tsx';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion.tsx';

export const TransferSection: React.FC<{ stats: AdminStats }> = ({ stats }) => {
  const lifetime = stats.transfer?.lifetime;
  if (!lifetime?.total) return null;

  return (
    <Accordion className="mt-3">
      <AccordionItem value="transfer" className="border-0">
        <AccordionTrigger className="py-2 text-xs font-medium text-text-muted hover:no-underline hover:text-text gap-2">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 min-w-0">
            <span>スクレイプ転送量</span>
            <span className="font-normal text-[11px] text-text-muted/80">
              プロセス累計 · DL{' '}
              {lifetime.total.bytes_downloaded_mb} MB ·{' '}
              {lifetime.total.requests} req
              {lifetime.total.restricted_hits > 0
                ? ` · 制限 ${lifetime.total.restricted_hits}`
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
                {lifetime.total.bytes_downloaded_mb} MB
              </span>
            </Card>
            <Card size="sm" className="p-2 text-center">
              <span className="text-[10px] text-text-muted block">リクエスト</span>
              <span className="text-sm font-bold">
                {lifetime.total.requests}
              </span>
            </Card>
            <Card size="sm" className="p-2 text-center">
              <span className="text-[10px] text-text-muted block">direct / proxy</span>
              <span className="text-sm font-bold">
                {lifetime.total.direct_requests}/
                {lifetime.total.proxy_requests}
              </span>
            </Card>
            <Card size="sm" className="p-2 text-center">
              <span className="text-[10px] text-text-muted block">制限ヒット</span>
              <span className="text-sm font-bold text-warning">
                {lifetime.total.restricted_hits}
              </span>
            </Card>
          </div>
          {Object.keys(lifetime.by_source || {}).length > 0 && (
            <div className="border border-border rounded-lg overflow-hidden text-xs">
              <div className="grid grid-cols-4 gap-1 bg-white/[0.04] px-2 py-1.5 text-text-muted font-semibold">
                <span>ソース</span>
                <span className="text-right">DL MB</span>
                <span className="text-right">req</span>
                <span className="text-right">制限</span>
              </div>
              {Object.entries(lifetime.by_source).map(([sid, b]) => (
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
  );
};
