import type { FC, ReactNode } from 'react';
import { Card } from '@/components/ui/card.tsx';

interface KpiCardProps {
  /** 上段の小さめラベル */
  label: ReactNode;
  /** 下段の強調値。色分けした複数 span を含む複雑な中身もそのまま渡せる */
  value: ReactNode;
  /** true で値を accent 色にする */
  accent?: boolean;
}

/**
 * 分析系タブで使うKPIチップ。ラベル + 強調値の2段構えの小型カード。
 * PriceTrendTab のKPIカード群と同じ見た目(size=sm・中央寄せ・p-3)。
 */
export const KpiCard: FC<KpiCardProps> = ({ label, value, accent = false }) => {
  return (
    <Card size="sm" className="text-center p-3">
      <span className="text-xs text-text-muted block mb-1">{label}</span>
      <span className={`text-lg font-bold ${accent ? 'text-accent' : 'text-text'}`}>{value}</span>
    </Card>
  );
};
