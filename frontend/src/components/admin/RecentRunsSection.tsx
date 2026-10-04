/**
 * 「直近のスクレイプ実行」区画(DB由来のためプロセス再起動後も残る)。
 * runs が空の場合は呼び出し側で非表示にする。
 */
import React from 'react';
import type { ScrapeRunSummary } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { formatAdminTs, runStatusBadgeClass } from './adminHelpers.ts';

export const RecentRunsSection: React.FC<{ runs: ScrapeRunSummary[] }> = ({ runs }) => {
  return (
    <div>
      <h3 className="text-sm mb-3 border-l-[3px] border-primary pl-2 text-text flex items-baseline gap-2 flex-wrap">
        直近のスクレイプ実行
        <span className="text-[11px] font-normal text-text-muted">
          DB記録・再起動後も保持
        </span>
      </h3>
      <div className="max-h-44 overflow-y-auto border border-border rounded-md divide-y divide-border app-scrollbar">
        {runs.map((r) => (
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
  );
};
