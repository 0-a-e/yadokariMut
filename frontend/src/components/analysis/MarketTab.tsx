import React, { useMemo, useState } from 'react';
import { SingleToggleGroup } from '@/components/ui/toggle-group.tsx';
import { EmptyState } from '@/components/shared/EmptyState.tsx';
import { Badge } from '@/components/ui/badge.tsx';
import { Button } from '@/components/ui/button.tsx';
import { KpiCard } from './charts/KpiCard.tsx';
import MarketHistogram from './charts/MarketHistogram.tsx';
import MarketScatter from './charts/MarketScatter.tsx';
import { COLOR_ACCENT, COLOR_MUTED, TrendLegend } from '../shared/charts/chartTheme.tsx';
import {
  buildBins,
  buildPeerSet,
  linearRegression,
  METRICS,
  metricValue,
  numericSummary,
  percentileRank,
} from '../../lib/analysis/marketBenchmark.ts';
import type { MarketMetric, MetricDef } from '../../lib/analysis/marketBenchmark.ts';
import type { PropertyFeature } from '../../types.ts';

interface MarketTabProps {
  feature: PropertyFeature;
  /** 相場比較の母集団(フィルタ前の全物件) */
  allFeatures: PropertyFeature[];
  /** 近隣物件クリックで分析対象を切替える */
  onSwitchProperty: (propertyId: number) => void;
}

/** 近隣リスト1行分(指標値でソート済み) */
interface NeighborRow {
  feature: PropertyFeature;
  value: number;
  side: 'low' | 'high';
}

/** 指標分布セクションの見出し+凡例(ピアのバー色は MarketHistogram の PEER_BAR_COLOR と揃える) */
const PEER_COLOR = '#3d4354';

/**
 * 物件モード・タブ「相場比較」。同市区町村×間取り(少ない場合は同都道府県)の
 * 掲載中物件との価格ポジショニングを、KPI・分布ヒストグラム・面積×日額散布図・近隣リストで示す。
 * 母集団はフィルタ前の全物件(allFeatures)で、日額は掲載最安(キャンペーン適用済み)基準。
 */
export const MarketTab: React.FC<MarketTabProps> = ({ feature, allFeatures, onSwitchProperty }) => {
  const [metric, setMetric] = useState<MarketMetric>('daily');

  // ピア集合(同市区町村×間取り → 5件未満なら都道府県×間取り)は指標に依存しないため1回だけ組む
  const peerSet = useMemo(() => buildPeerSet(allFeatures, feature), [allFeatures, feature]);
  const metricDef: MetricDef = METRICS[metric];

  /** 選択指標の統計(中央値・自物件値・分布ビン・パーセンタイル順位) */
  const stats = useMemo(() => {
    const peerValues = peerSet.peers
      .map((p) => metricValue(p, metric))
      .filter((v): v is number => v != null);
    const summary = numericSummary(peerValues);
    const selfValue = metricValue(feature, metric);
    const bins = buildBins(peerValues, selfValue);
    const rank = selfValue != null ? percentileRank(peerValues, selfValue) : null;
    // 中央値比(安いと100未満)。median が無効値のときは非表示
    const ratio =
      selfValue != null && summary != null && summary.median > 0
        ? Math.round((selfValue / summary.median) * 100)
        : null;
    return { summary, selfValue, bins, rank, ratio };
  }, [peerSet, metric, feature]);

  /** 面積×日額散布図の点(両方そろうピアのみ)。5点未満は散布図ごと非表示 */
  const scatter = useMemo(() => {
    const points = peerSet.peers
      .map((p) => ({ x: metricValue(p, 'area'), y: metricValue(p, 'daily') }))
      .filter((pt): pt is { x: number; y: number } => pt.x != null && pt.y != null);
    const selfArea = metricValue(feature, 'area');
    const selfDaily = metricValue(feature, 'daily');
    const self = selfArea != null && selfDaily != null ? { x: selfArea, y: selfDaily } : null;
    const regression = points.length >= 5 ? linearRegression(points) : null;
    return { points, self, regression };
  }, [peerSet, feature]);

  /** 近隣リスト: 選択指標でソートし、自物件の直下3件(安い側)と直上3件(高い側) */
  const neighbors = useMemo((): NeighborRow[] => {
    const rows = peerSet.peers
      .map((p) => ({ feature: p, value: metricValue(p, metric) }))
      .filter((r): r is { feature: PropertyFeature; value: number } => r.value != null)
      .sort((a, b) => a.value - b.value || a.feature.properties.id - b.feature.properties.id);
    const selfValue = stats.selfValue;
    const withSide = (rs: { feature: PropertyFeature; value: number }[], side: 'low' | 'high') =>
      rs.map((r) => ({ ...r, side }));
    // self 値が取れない指標(徒歩分なし等)は最安側・最高側の両端で代用する
    if (selfValue == null) {
      const low = withSide(rows.slice(0, 3), 'low');
      const rest = rows.slice(low.length);
      return [...low, ...withSide(rest.slice(-3), 'high')];
    }
    // 同値は上位側に数える(percentileRank と同じ扱い)
    const boundary = rows.findIndex((r) => r.value >= selfValue);
    const below = boundary < 0 ? rows : rows.slice(0, boundary);
    const above = boundary < 0 ? [] : rows.slice(boundary);
    return [
      ...withSide(below.slice(-3), 'low'),
      ...withSide(above.slice(0, 3), 'high'),
    ];
  }, [peerSet, metric, stats.selfValue]);

  // ピア0件は比較そのものが成立しない
  if (peerSet.peers.length === 0) {
    return <EmptyState message="比較できる同条件物件がありません。" />;
  }

  return (
    <>
      {/* ── 比較スコープ(例: 横浜市 × 1R の掲載中 12件と比較) ── */}
      <div>
        <p className="text-sm text-text m-0">
          <span className="font-semibold">{peerSet.groupLabel}</span>{' '}
          の掲載中 {peerSet.peers.length}件と比較
        </p>
        {peerSet.fallback && (
          <p className="text-[11px] text-text-muted m-0 mt-0.5">
            同市区町村×間取りが少ないため都道府県単位で比較しています。
          </p>
        )}
      </div>

      {/* ── 指標切替 ── */}
      <div className="flex flex-wrap items-center gap-3">
        <SingleToggleGroup
          options={Object.values(METRICS).map((def) => ({ value: def.id, label: def.label }))}
          value={metric}
          onChange={setMetric}
          size="sm"
          itemClassName="text-xs"
        />
      </div>

      {/* ── KPIチップ(中央値 / 自物件 / 中央値比 / 位置) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          label={`${metricDef.label}中央値`}
          value={stats.summary ? metricDef.formatValue(stats.summary.median) : '-'}
        />
        <KpiCard
          label="自物件"
          accent
          value={stats.selfValue != null ? metricDef.formatValue(stats.selfValue) : '-'}
        />
        <KpiCard
          label="中央値比"
          value={
            stats.ratio != null ? (
              <span className={stats.ratio < 100 ? 'text-success' : stats.ratio > 100 ? 'text-danger' : undefined}>
                {stats.ratio}%
              </span>
            ) : (
              '-'
            )
          }
        />
        <KpiCard
          label="位置"
          value={stats.rank != null ? `下位 ${Math.round(stats.rank)}%` : '-'}
        />
      </div>

      {/* ── 指標分布ヒストグラム(自物件ビンを強調) ── */}
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium text-text-muted m-0">{metricDef.label}の分布</p>
          <TrendLegend
            items={[
              { color: PEER_COLOR, label: 'ピア物件' },
              ...(stats.selfValue != null ? [{ color: COLOR_ACCENT, label: '自物件ビン' }] : []),
            ]}
          />
        </div>
        <MarketHistogram bins={stats.bins.bins} metric={metricDef} />
      </div>

      {/* ── 面積×日額の散布図(5点未満は非表示) ── */}
      {scatter.points.length >= 5 && (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-medium text-text-muted m-0">面積と日額の関係</p>
            <TrendLegend
              items={[
                { color: PEER_COLOR, label: 'ピア物件' },
                ...(scatter.self ? [{ color: COLOR_ACCENT, label: '自物件' }] : []),
                ...(scatter.regression ? [{ color: COLOR_MUTED, label: '回帰直線', dashed: true }] : []),
              ]}
            />
          </div>
          <MarketScatter
            points={scatter.points}
            self={scatter.self}
            regression={scatter.regression}
          />
        </div>
      )}

      {/* ── 近隣リスト(クリックで分析対象を切替) ── */}
      {neighbors.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium text-text-muted m-0">この物件の周辺(安い側/高い側)</p>
          <div className="flex flex-col">
            {neighbors.map((row) => (
              <Button
                key={row.feature.properties.id}
                variant="ghost"
                size="sm"
                className="w-full justify-between gap-2 h-auto py-1.5 px-2"
                onClick={() => onSwitchProperty(row.feature.properties.id)}
              >
                <span className="flex flex-col items-start min-w-0 text-left">
                  <span className="text-xs text-text truncate w-full">{row.feature.properties.title}</span>
                  <span className="text-[11px] text-text-muted truncate w-full">
                    {row.feature.properties.municipality ?? row.feature.properties.prefecture_name ?? ''}
                  </span>
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  <Badge variant={row.side === 'low' ? 'secondary' : 'outline'} className="text-[10px]">
                    {row.side === 'low' ? '安い側' : '高い側'}
                  </Badge>
                  <span className="text-xs font-semibold text-text whitespace-nowrap">
                    {metricDef.formatValue(row.value)}
                  </span>
                </span>
              </Button>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-text-muted m-0 leading-relaxed">
        比較対象は掲載中の全物件(フィルタ前)。日額は掲載最安(キャンペーン適用済み)。
      </p>
    </>
  );
};
