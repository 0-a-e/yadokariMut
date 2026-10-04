import React, { useEffect, useMemo, useState } from 'react';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group.tsx';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table.tsx';
import { cn } from '@/lib/utils.ts';
import { Loader2 } from 'lucide-react';
import type {
  PriceHistoryPoint,
  PropertyFeature,
} from '../../types.ts';
import { fetchPropertyDetail, type PropertyDetailResponse } from '../../lib/api/properties.ts';
import PropertyPriceChart from './charts/PropertyPriceChart.tsx';
import type { MarketMedianPoint } from './charts/PropertyPriceChart.tsx';
import { KpiCard } from './charts/KpiCard.tsx';
import { usePriceTrend } from '../../hooks/usePriceTrend.ts';
import {
  extractChangeEvents,
  formatDate,
  priceDeltaFromHistory,
  summarizeHistory,
  toHistoryChartPoints,
} from '../../lib/analysis/propertyHistory.ts';

interface PropertyPriceTabProps {
  feature: PropertyFeature;
}

/** 期間プリセット(value は日数。'0' = 全期間) */
const PERIOD_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: '0', label: '全期間' },
  { value: '90', label: '90日' },
  { value: '30', label: '30日' },
];

/** price_history が無い場合の共用の空配列(useMemo 依存の参照安定化用) */
const EMPTY_HISTORY: PriceHistoryPoint[] = [];

/** 差分の色分け。アプリ規約に合わせ「下落=緑(success)/上昇=赤(danger)」 */
function deltaClass(delta: number): string {
  return delta < 0 ? 'text-success' : 'text-danger';
}

/**
 * 物件モード・タブ「価格推移」。品質ガード適用済みの掲載最安日額(割引込み)の系列を
 * 同県の市場中央値(前進補完推計)と重ねて表示する。
 * 詳細APIは1回だけ取得し、それまでは GeoJSON 側に付与済みの履歴で初期描画する。
 */
export const PropertyPriceTab: React.FC<PropertyPriceTabProps> = ({ feature }) => {
  const property = feature.properties;

  const [detail, setDetail] = useState<PropertyDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setDetailLoading(true);
    fetchPropertyDetail(property.id)
      .then((json) => {
        if (!cancelled) setDetail(json);
      })
      .catch((e) => {
        // 失敗時も GeoJSON 由来の履歴(キャッシュ済み)で表示を続ける
        console.error(e);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [property.id]);

  // 市場中央値は物件と同じ都道府県で取得(hook内でキャッシュ済み)
  const { data: marketData, error: marketError } = usePriceTrend(365, property.prefecture_name);

  const [periodDays, setPeriodDays] = useState<string>('0');

  // 詳細APIの結果を優先し、無ければ GeoJSON 付与分にフォールバック
  const initialHistory = property.price_history ?? EMPTY_HISTORY;
  const history: PriceHistoryPoint[] = detail?.price_history ?? initialHistory;
  const meta = detail?.price_history_meta ?? null;
  const firstSeenAt = detail?.first_seen_at ?? null;

  const chartPoints = useMemo(() => toHistoryChartPoints(history), [history]);

  /** 期間の下限(ミリ秒)。全期間は null */
  const cutoffTs = useMemo(
    () => (periodDays === '0' ? null : Date.now() - Number(periodDays) * 24 * 60 * 60 * 1000),
    [periodDays],
  );

  /** 期間絞り込み後の物件系列 */
  const points = useMemo(
    () => (cutoffTs == null ? chartPoints : chartPoints.filter((p) => p.ts >= cutoffTs)),
    [chartPoints, cutoffTs],
  );

  /** 市場中央値を物件系列と同一の時間軸(ローカル時刻の ts)に変換し、同一期間で切り詰める */
  const market = useMemo<MarketMedianPoint[] | null>(() => {
    if (!marketData) return null;
    const all = marketData.series.carried.all.map((p) => ({
      ts: new Date(`${p.date}T00:00:00`).getTime(),
      median: p.median,
    }));
    return cutoffTs == null ? all : all.filter((m) => m.ts >= cutoffTs);
  }, [marketData, cutoffTs]);

  const summary = useMemo(() => summarizeHistory(points), [points]);
  const events = useMemo(() => extractChangeEvents(points), [points]);

  // 前回比は絞り込み後の生履歴の末尾2点から算出(既存の共通関数を利用)
  const delta = useMemo(() => {
    const withinPeriod =
      cutoffTs == null ? history : history.filter((p) => new Date(p.scraped_at).getTime() >= cutoffTs);
    return priceDeltaFromHistory(withinPeriod);
  }, [history, cutoffTs]);

  // 掲載日数(first_seen_at が取れた時のみ表示する任意KPI)
  const listingDays = useMemo(() => {
    if (!firstSeenAt) return null;
    const t = new Date(firstSeenAt).getTime();
    if (Number.isNaN(t)) return null;
    return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
  }, [firstSeenAt]);

  // 「現在」の値は期間絞り込みに左右されない最終既知値を用いる
  const currentDaily =
    chartPoints.length > 0 ? chartPoints[chartPoints.length - 1].daily : property.min_daily_rent;

  if (detailLoading && initialHistory.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted">
        <Loader2 className="mr-2 size-4 animate-spin" />
        読み込み中…
      </div>
    );
  }

  if (points.length < 2) {
    return (
      <p className="text-sm text-text-muted italic">
        比較できる履歴がまだありません(2回以上の収集が必要)。
        {currentDaily != null ? `現在 ${currentDaily.toLocaleString()}円` : '現在の取得値はまだありません'}
      </p>
    );
  }

  return (
    <>
      {/* ── コントロール: 期間プリセット ── */}
      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup
          multiple={false}
          value={[periodDays]}
          onValueChange={(vals) => {
            const next = vals[0];
            if (next) setPeriodDays(next);
          }}
          size="sm"
          className="ml-auto"
        >
          {PERIOD_OPTIONS.map((opt) => (
            <ToggleGroupItem key={opt.value} value={opt.value} className="text-xs">
              {opt.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {/* ── KPIチップ(選択中の期間の集計) ── */}
      <div
        className={cn(
          'grid grid-cols-2 gap-3',
          listingDays != null ? 'sm:grid-cols-5' : 'sm:grid-cols-4',
        )}
      >
        <KpiCard
          label="現在日額"
          accent
          value={summary ? `${summary.last.toLocaleString()}円` : '-'}
        />
        <KpiCard
          label="前回比"
          value={
            delta ? (
              <span className={deltaClass(delta.delta)}>
                {delta.delta < 0 ? '▼' : '▲'} {Math.abs(delta.delta).toLocaleString()}円
              </span>
            ) : (
              '-'
            )
          }
        />
        <KpiCard
          label="期間最安"
          value={
            summary ? (
              <>
                <span className="text-success">{summary.min.toLocaleString()}円</span>
                <span className="block text-[10px] font-normal text-text-muted">
                  {formatDate(summary.minAt)}
                </span>
              </>
            ) : (
              '-'
            )
          }
        />
        <KpiCard
          label="期間最高"
          value={
            summary ? (
              <>
                <span className="text-danger">{summary.max.toLocaleString()}円</span>
                <span className="block text-[10px] font-normal text-text-muted">
                  {formatDate(summary.maxAt)}
                </span>
              </>
            ) : (
              '-'
            )
          }
        />
        {listingDays != null && <KpiCard label="掲載日数" value={`${listingDays.toLocaleString()}日`} />}
      </div>

      {/* ── チャート(物件日額 + 同県の市場中央値) ── */}
      <PropertyPriceChart
        points={points}
        market={market}
        selectedDays={periodDays === '0' ? null : Number(periodDays)}
      />

      {/* ── 変動イベント一覧(新しい順) ── */}
      <section className="flex flex-col gap-1">
        <h3 className="text-xs text-text-muted m-0">変動履歴</h3>
        {events.length === 0 ? (
          <p className="text-sm text-text-muted italic m-0">期間中の変動はありません</p>
        ) : (
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs text-text-muted">日付</TableHead>
                <TableHead className="text-xs text-text-muted">変動</TableHead>
                <TableHead className="text-xs text-text-muted text-right">変動額</TableHead>
                <TableHead className="text-xs text-text-muted text-right">変動率</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((e) => (
                <TableRow key={e.scraped_at}>
                  <TableCell className="text-text/90">{formatDate(e.scraped_at)}</TableCell>
                  <TableCell className={cn('font-semibold', deltaClass(e.delta))}>
                    {e.delta < 0 ? '▼値下げ' : '▲値上げ'}
                  </TableCell>
                  <TableCell className={cn('text-right font-semibold', deltaClass(e.delta))}>
                    {e.delta > 0 ? '+' : ''}
                    {e.delta.toLocaleString()}円
                  </TableCell>
                  <TableCell className="text-right text-text-muted">
                    {e.pct > 0 ? '+' : ''}
                    {e.pct}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {/* ── 注記(データの意味) ── */}
      <div className="text-[11px] text-text-muted leading-relaxed">
        <p className="m-0">
          スクレイプ時点の掲載最安日額(割引込み)。期限切れキャンペーンを含む場合があります。
        </p>
        {meta && meta.dropped_count > 0 && (
          <p className="m-0">不整合のため{meta.dropped_count.toLocaleString()}件の取得値を除外しています。</p>
        )}
        <p className="m-0">
          破線の市場中央値は{property.prefecture_name ?? '同一県'}
          の物件を母集団に前進補完した推計値です。
          {marketError && ' 市場データを取得できなかったため、物件系列のみ表示しています。'}
        </p>
      </div>
    </>
  );
};
