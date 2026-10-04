/**
 * 分析モーダル。表示は共通シェル(SettingsModalShell)に委譲し、
 * ここでは対象(市場/物件)の解決とタブ定義・コンテンツ切替のみを持つ。
 */
import React, { useEffect, useState } from 'react';
import {
  FaChartLine,
  FaArrowTrendUp,
  FaYenSign,
  FaScaleBalanced,
} from 'react-icons/fa6';
import { PriceTrendTab } from './PriceTrendTab.tsx';
import { PropertyHeader } from './PropertyHeader.tsx';
import { PropertyPriceTab } from './PropertyPriceTab.tsx';
import { PlanCostTab } from './PlanCostTab.tsx';
import { MarketTab } from './MarketTab.tsx';
import { SettingsModalShell } from '../shared/SettingsModalShell.tsx';
import type { AnalysisTarget, PropertyFeature } from '../../types.ts';

/** タブ定義(モバイル幅では横並び上部タブ、広幅では左タブ列) */
type MarketTabId = 'price-trend';
type PropertyTabId = 'price' | 'plan-cost' | 'market-position';

const MARKET_TABS: ReadonlyArray<{ id: MarketTabId; label: string; icon: React.ReactNode }> = [
  { id: 'price-trend', label: '価格変動', icon: <FaArrowTrendUp /> },
];

const PROPERTY_TABS: ReadonlyArray<{ id: PropertyTabId; label: string; icon: React.ReactNode }> = [
  { id: 'price', label: '価格推移', icon: <FaArrowTrendUp /> },
  { id: 'plan-cost', label: '料金プラン', icon: <FaYenSign /> },
  { id: 'market-position', label: '相場比較', icon: <FaScaleBalanced /> },
];

interface AnalysisModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 表示対象(市場全体 or 物件単位) */
  target: AnalysisTarget;
  /** フィルタ前の全物件(物件モードの対象解決と相場比較の母集団) */
  allFeatures: PropertyFeature[];
  /** モーダルを開いたまま対象を切替える(相場比較の近隣物件クリック等) */
  onTargetChange: (target: AnalysisTarget) => void;
}

export const AnalysisModal: React.FC<AnalysisModalProps> = ({
  isOpen,
  onClose,
  target,
  allFeatures,
  onTargetChange,
}) => {
  const [marketTab, setMarketTab] = useState<MarketTabId>('price-trend');
  const [propertyTab, setPropertyTab] = useState<PropertyTabId>('price');

  const isPropertyMode = target.kind === 'property';
  const feature = isPropertyMode
    ? allFeatures.find((f) => f.properties.id === target.propertyId) ?? null
    : null;

  const tabs = isPropertyMode ? PROPERTY_TABS : MARKET_TABS;
  const activeTab = isPropertyMode ? propertyTab : marketTab;
  // タブidは 'price-trend' だけが市場/物件で重複しない識別子なので、リテラルで判別して適切なsetterへ
  const handleTabClick = (id: MarketTabId | PropertyTabId) => {
    if (id === 'price-trend') {
      setMarketTab('price-trend');
      return;
    }
    setPropertyTab(id);
  };

  // 対象を開き直したときは常に先頭タブから(物件→別物件の切替でもリセット)
  useEffect(() => {
    if (isOpen) {
      setMarketTab('price-trend');
      setPropertyTab('price');
    }
  }, [isOpen, target.kind, isPropertyMode ? target.propertyId : 0]);

  const switchProperty = (propertyId: number) => {
    onTargetChange({ kind: 'property', propertyId });
    setPropertyTab('price');
  };

  return (
    <SettingsModalShell
      isOpen={isOpen}
      onClose={onClose}
      closeTestId="analysis-close"
      title={
        <>
          <FaChartLine /> 分析
          {isPropertyMode && (
            <span className="text-xs font-normal text-text-muted ml-1">物件単位</span>
          )}
        </>
      }
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={handleTabClick}
      tablistLabel={isPropertyMode ? '物件分析カテゴリ' : '分析カテゴリ'}
      headerSlot={
        /* ── 物件モードのヘッダ(サムネ+KPI+市場全体への導線) ── */
        isPropertyMode && feature ? (
          <div className="px-5 py-3 border-b border-border shrink-0">
            <PropertyHeader
              feature={feature}
              onOpenMarket={() => onTargetChange({ kind: 'market' })}
            />
          </div>
        ) : undefined
      }
    >
      <div className="p-5 flex flex-col gap-5">
        {!isPropertyMode && marketTab === 'price-trend' && <PriceTrendTab />}
        {isPropertyMode && !feature && (
          <p className="text-sm text-text-muted italic">
            この物件のデータが見つかりません(再取得中の可能性があります)。
          </p>
        )}
        {isPropertyMode && feature && propertyTab === 'price' && (
          <PropertyPriceTab feature={feature} />
        )}
        {isPropertyMode && feature && propertyTab === 'plan-cost' && (
          <PlanCostTab feature={feature} />
        )}
        {isPropertyMode && feature && propertyTab === 'market-position' && (
          <MarketTab
            feature={feature}
            allFeatures={allFeatures}
            onSwitchProperty={switchProperty}
          />
        )}
      </div>
    </SettingsModalShell>
  );
};
