import React, { useMemo, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert.tsx';
import { SingleToggleGroup } from '@/components/ui/toggle-group.tsx';
import { EmptyState } from '@/components/shared/EmptyState.tsx';
import { LoadingState } from '@/components/shared/LoadingState.tsx';
import type { PriceTrendMode, PriceTrendPoint } from '../../types.ts';
import { formatYen } from '../../lib/format.ts';
import PriceTrendChart from './charts/PriceTrendChart.tsx';
import { KpiCard } from './charts/KpiCard.tsx';
import { usePriceTrend } from '../../hooks/usePriceTrend.ts';

/** 集計モード切替。既定は前進補完推計(取得構成に左右されない市場トレンド) */
const MODE_OPTIONS: ReadonlyArray<{ value: PriceTrendMode; label: string }> = [
  { value: 'carried', label: '前進補完推計' },
  { value: 'scraped', label: '当日取得分' },
];

/** 期間プリセット(value は日数。'0' = 全期間) */
const PERIOD_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: '30', label: '30日' },
  { value: '60', label: '60日' },
  { value: '90', label: '90日' },
  { value: '0', label: '全期間' },
];

/** プロバイダ切替の「すべて」 */
const PROVIDER_ALL = 'all';

/**
 * 価格変動タブ。データは1回だけ取得し(days=365で最長。hook内でキャッシュ済み)、
 * モード・プロバイダ切替・期間プリセットは取得済み系列のクライアント側絞り込みで行う。
 */
export const PriceTrendTab: React.FC = () => {
  const { data, loading, error } = usePriceTrend(365);
  const [mode, setMode] = useState<PriceTrendMode>('carried');
  const [provider, setProvider] = useState<string>(PROVIDER_ALL);
  const [periodDays, setPeriodDays] = useState<string>('90');

  /** 選択中のモード・系列(全プロバイダ or プロバイダ別)を期間で絞り込む */
  const series: PriceTrendPoint[] = useMemo(() => {
    if (!data) return [];
    const modeSeries = data.series[mode];
    const raw =
      provider === PROVIDER_ALL ? modeSeries.all : (modeSeries.by_site[provider] ?? []);
    if (periodDays === '0') return raw;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - Number(periodDays));
    // DB側の日付はローカルタイム基準のため UTC ではなくローカル日付で比較する
    const cutoffIso = `${cutoff.getFullYear()}-${String(cutoff.getMonth() + 1).padStart(2, '0')}-${String(cutoff.getDate()).padStart(2, '0')}`;
    return raw.filter((p) => p.date >= cutoffIso);
  }, [data, mode, provider, periodDays]);

  const last = series.length > 0 ? series[series.length - 1] : null;
  const downTotal = useMemo(() => series.reduce((acc, p) => acc + p.down, 0), [series]);
  const upTotal = useMemo(() => series.reduce((acc, p) => acc + p.up, 0), [series]);

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return (
      <Alert variant="destructive" className="text-xs">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!data || series.length === 0) {
    return <EmptyState message="この期間の価格データがまだありません。" />;
  }

  return (
    <>
      {/* ── コントロール: 集計モード / プロバイダ切替 + 期間プリセット ── */}
      <div className="flex flex-wrap items-center gap-3">
        <SingleToggleGroup
          options={MODE_OPTIONS}
          value={mode}
          onChange={setMode}
          size="sm"
          itemClassName="text-xs"
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <SingleToggleGroup
          options={[
            { value: PROVIDER_ALL, label: 'すべて' },
            ...data.providers.map((p) => ({ value: p.id, label: p.display_name })),
          ]}
          value={provider}
          onChange={setProvider}
          size="sm"
          itemClassName="text-xs"
        />
        <SingleToggleGroup
          options={PERIOD_OPTIONS}
          value={periodDays}
          onChange={setPeriodDays}
          size="sm"
          className="ml-auto"
          itemClassName="text-xs"
        />
      </div>

      {/* ── KPIチップ(選択中の系列の最新日 + 期間内合計) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          label={mode === 'carried' ? '掲載物件数(推計)' : '取得物件数(当日)'}
          value={last ? last.count.toLocaleString() : '-'}
        />
        <KpiCard
          label="日額中央値(最新)"
          accent
          value={last ? formatYen(last.median) : '-'}
        />
        <KpiCard label="日額平均(最新)" value={last ? formatYen(last.avg) : '-'} />
        <KpiCard
          label="値下げ / 値上げ(期間内)"
          value={
            <>
              <span className="text-success">{downTotal}</span>
              <span className="text-text-muted text-sm mx-1">/</span>
              <span className="text-danger">{upTotal}</span>
              <span className="text-xs text-text-muted ml-1">件</span>
            </>
          }
        />
      </div>

      <PriceTrendChart series={series} />

      <p className="text-[11px] text-text-muted m-0 leading-relaxed">
        {mode === 'carried'
          ? `各物件の直近${data.carried_window_days}日以内の取得値を前進補間し、既知の全物件を母集団に集計した推計です。日々の取得構成に左右されない市場トレンドを示します。`
          : 'その日に取得成功した物件のみの集計です。サイト・県の取得構成により数値が日次で変動します。'}
        {' '}品質ガード適用(異常値除外 {data.meta.excluded_rows.toLocaleString()} 行)・
        取得日時 {data.generated_at.slice(0, 16).replace('T', ' ')}。
      </p>
    </>
  );
};
