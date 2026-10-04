/**
 * 設定モーダル。表示は共通シェル(SettingsModalShell)に委譲し、
 * ここではタブ定義とコンテンツ切替のみを持つ。
 *
 * スクレイプ管理タブはタブ切替でも下書き入力等の状態を保持するため、
 * 開いている間はマウントし続けて非表示で切り替える(他タブは都度マウント)。
 */
import React, { useState } from 'react';
import type { PropertyFeature, PropertyGeoJSON } from '../../types.ts';
import { FaGear, FaCloudArrowDown, FaMapLocationDot, FaFileExport } from 'react-icons/fa6';
import { MapDisplaySettingsTab } from './MapDisplaySettingsTab.tsx';
import { ExportTab } from './ExportTab.tsx';
import { ScrapeTab } from './ScrapeTab.tsx';
import { SettingsModalShell } from '../shared/SettingsModalShell.tsx';
import type { FeSettings } from '../../lib/feSettings.ts';

interface AdminModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGeoJsonLoaded?: (data: PropertyGeoJSON) => void;
  /** フロントエンド設定(地図表示タブで表示・更新) */
  feSettings?: FeSettings;
  /** App の updateFeSettings(部分マージ保存。失敗時 null) */
  onFeSettingsUpdate?: (update: FeSettings) => Promise<FeSettings | null>;
  /** エクスポートタブ用: 表示中(フィルタ適用済み)の物件フィーチャー */
  filteredFeatures?: PropertyFeature[];
  /** エクスポートタブ用: 全物件フィーチャー */
  allFeatures?: PropertyFeature[];
}

/** タブ定義(モバイル幅では横並び上部タブ、広幅では左タブ列) */
type AdminTabId = 'scrape' | 'map' | 'export';

const ADMIN_TABS: ReadonlyArray<{ id: AdminTabId; label: string; icon: React.ReactNode }> = [
  { id: 'scrape', label: 'スクレイプ管理', icon: <FaCloudArrowDown /> },
  { id: 'map', label: '地図表示', icon: <FaMapLocationDot /> },
  { id: 'export', label: 'エクスポート', icon: <FaFileExport /> },
];

export const AdminModal: React.FC<AdminModalProps> = ({ isOpen, onClose, onGeoJsonLoaded, feSettings, onFeSettingsUpdate, filteredFeatures, allFeatures }) => {
  const [activeTab, setActiveTab] = useState<AdminTabId>('scrape');

  return (
    <SettingsModalShell
      isOpen={isOpen}
      onClose={onClose}
      title={
        <>
          <FaGear /> 設定
        </>
      }
      tabs={ADMIN_TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      tablistLabel="設定カテゴリ"
    >
      {/* スクレイプ管理: マウント維持(非表示切替)で下書き・ポーリング状態を保持 */}
      <div className={activeTab === 'scrape' ? 'p-5 flex flex-col gap-5' : 'hidden'}>
        <ScrapeTab isOpen={isOpen} onGeoJsonLoaded={onGeoJsonLoaded} />
      </div>
      {activeTab === 'map' && feSettings && onFeSettingsUpdate && (
        /* ── 地図表示タブ ── */
        <div className="p-5 flex flex-col gap-5">
          <MapDisplaySettingsTab feSettings={feSettings} onUpdate={onFeSettingsUpdate} />
        </div>
      )}
      {activeTab === 'export' && filteredFeatures && allFeatures && (
        /* ── エクスポートタブ (Google Earth 用 KML) ── */
        <div className="p-5 flex flex-col gap-5">
          <ExportTab filteredFeatures={filteredFeatures} allFeatures={allFeatures} />
        </div>
      )}
    </SettingsModalShell>
  );
};
