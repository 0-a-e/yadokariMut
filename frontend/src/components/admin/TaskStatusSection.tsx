/**
 * 「タスクステータス & 実行ログ」区画。
 * 実行中フラグ(isRunning)は ScrapeTab が持つため受ける。それ以外の
 * 直前タスク結果の派生値はここで算出する。
 */
import React from 'react';
import type { AdminStats } from '../../types.ts';
import { Badge } from '@/components/ui/badge.tsx';
import { runStatusBadgeClass } from './adminHelpers.ts';

interface TaskStatusSectionProps {
  stats: AdminStats | null;
  isRunning: boolean;
  consoleRef: React.RefObject<HTMLPreElement | null>;
}

export const TaskStatusSection: React.FC<TaskStatusSectionProps> = ({
  stats,
  isRunning,
  consoleRef,
}) => {
  const taskResult = stats?.task_status?.last_result ?? null;
  // 待機中は直前タスクの結果をバッジに反映(エラー/一部失敗を見逃さない)
  const taskError = !isRunning ? stats?.task_status.error ?? null : null;
  const idleBadgeStatus = taskError
    ? 'error'
    : taskResult === 'partial'
      ? 'partial'
      : 'ok';

  return (
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
          : '読み込み中…'}
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
  );
};
