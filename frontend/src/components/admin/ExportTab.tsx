import React, { useMemo, useState } from 'react';
import { FaFileExport } from 'react-icons/fa6';
import type { PropertyFeature } from '../../types.ts';
import {
  downloadBlob,
  exportFilename,
  featuresToIds,
  selectExportFeatures,
  type ExportScope,
} from '../../lib/exportTargets.ts';
import { postKmlExport } from '../../lib/api/export.ts';
import { ApiError } from '../../lib/api/client.ts';
import { Checkbox } from '@/components/ui/checkbox.tsx';

interface ExportTabProps {
  /** 表示中 (フィルタ適用済み) の物件 */
  filteredFeatures: PropertyFeature[];
  /** 全物件 */
  allFeatures: PropertyFeature[];
}

/**
 * 管理者モーダル「エクスポート」タブ。
 * Google Earth で開ける KML を BE (/api/export/kml) 経由でダウンロードする。
 * 送信するのは物件 ID のみで、KML への変換は BE 側で行う。
 */
export const ExportTab: React.FC<ExportTabProps> = ({
  filteredFeatures,
  allFeatures,
}) => {
  const [scope, setScope] = useState<ExportScope>('filtered');
  const [includeInactive, setIncludeInactive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doneCount, setDoneCount] = useState<number | null>(null);

  const options = useMemo(
    () => ({ scope, includeInactive }),
    [scope, includeInactive],
  );
  const targets = useMemo(
    () => selectExportFeatures(allFeatures, filteredFeatures, options),
    [allFeatures, filteredFeatures, options],
  );
  const targetCount = targets.length;

  const handleDownload = async () => {
    if (busy || targetCount === 0) return;
    setBusy(true);
    setError(null);
    setDoneCount(null);
    try {
      const blob = await postKmlExport(featuresToIds(targets));
      downloadBlob(blob, exportFilename());
      setDoneCount(targetCount);
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? // detail 無しの !ok は旧文言(ステータス付き)を維持
            err.messageWith(`ダウンロードに失敗しました (${err.status})`)
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const scopeRows: ReadonlyArray<{
    id: ExportScope;
    label: string;
    desc: string;
  }> = [
    {
      id: 'filtered',
      label: '表示中の物件',
      desc: '現在のフィルタ・絞り込みで表示されているリスト',
    },
    {
      id: 'all',
      label: 'すべての物件',
      desc: '全地域・全フィルタ解除の物件一覧',
    },
  ];

  return (
    <div className="flex flex-col gap-5 min-w-0">
      <div>
        <h3 className="text-sm mb-1 border-l-[3px] border-primary pl-2 text-text">
          エクスポート
        </h3>
        <p className="text-xs text-text-muted">
          物件を Google Earth で開ける KML ファイルとしてダウンロードします。
          各ピンの吹き出しには賃料・間取り・画像・詳細ページへのリンクが含まれます。
        </p>
      </div>

      {/* 範囲選択 */}
      <div>
        <h4 className="text-xs font-semibold text-text-muted mb-2">対象範囲</h4>
        <div className="border border-border rounded-lg divide-y divide-border">
          {scopeRows.map((row) => {
            const count = selectExportFeatures(
              allFeatures,
              filteredFeatures,
              { scope: row.id, includeInactive },
            ).length;
            return (
              <label
                key={row.id}
                className="flex items-start gap-3 px-3 py-2.5 cursor-pointer hover:bg-white/[0.03]"
              >
                <input
                  type="radio"
                  name="export-scope"
                  className="mt-0.5 accent-[var(--primary)]"
                  checked={scope === row.id}
                  onChange={() => setScope(row.id)}
                />
                <span className="min-w-0">
                  <span className="text-sm text-text block">
                    {row.label}
                    <span className="ml-2 text-xs text-text-muted">
                      {count.toLocaleString()} 件
                    </span>
                  </span>
                  <span className="text-[11px] text-text-muted block mt-0.5">
                    {row.desc}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      {/* 掲載終了の扱い */}
      <div className="border border-border rounded-lg">
        <label className="flex items-center justify-between gap-4 px-3 py-3 cursor-pointer">
          <span className="min-w-0">
            <strong className="text-sm block">掲載終了の物件を含める</strong>
            <span className="text-xs text-text-muted block mt-0.5">
              オフにするとサイトから消えた物件 (is_active=false) を除きます。
              含めた分はグレーのピンで出力されます。
            </span>
          </span>
          <Checkbox
            className="shrink-0"
            checked={includeInactive}
            onCheckedChange={(checked) => setIncludeInactive(checked)}
          />
        </label>
      </div>

      {/* ダウンロード */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md bg-primary text-white text-sm font-medium px-4 py-2 transition-all hover:shadow-[0_0_12px_var(--primary-glow)] hover:-translate-y-px disabled:opacity-50 disabled:pointer-events-none"
          disabled={busy || targetCount === 0}
          onClick={() => void handleDownload()}
        >
          <FaFileExport className="text-base" />
          {busy ? '生成中…' : `KMLをダウンロード (${targetCount.toLocaleString()} 件)`}
        </button>
        {doneCount != null && !error && (
          <span className="text-xs text-success">
            KML ({doneCount.toLocaleString()} 件) をダウンロードしました。
          </span>
        )}
      </div>

      {error && (
        <p className="text-xs text-warning" role="alert">
          {error}
        </p>
      )}
    </div>
  );
};
