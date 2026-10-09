/**
 * 設定モーダル。表示は共通シェル(SettingsModalShell)に委譲し、
 * ここではタブ定義とコンテンツ切替のみを持つ。
 *
 * 旧「地図表示」タブ(物件ピンのクラスタリング等のglobal設定)は、
 * レイヤパネル物件ピン行の設定モーダル(PropertiesLayerSettingsDialog)へ移設済み。
 *
 * スクレイプ管理タブはタブ切替でも下書き入力等の状態を保持するため、
 * 開いている間はマウントし続けて非表示で切り替える(他タブは都度マウント)。
 */
import React, { useState } from 'react';
import type { BuildingGeoJSON, BuildingFeature } from '../../types.ts';
import { FaGear, FaCloudArrowDown, FaFileExport } from 'react-icons/fa6';
import { ExportTab } from './ExportTab.tsx';
import { ScrapeTab } from './ScrapeTab.tsx';
import { SettingsModalShell } from '../shared/SettingsModalShell.tsx';

interface AdminModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGeoJsonLoaded?: (data: BuildingGeoJSON) => void;
  /** エクスポートタブ用: 表示中(フィルタ適用済み)の建物(B2-δ §4.7・units を flatten して ids 化) */
  filteredBuildings?: BuildingFeature[];
  /** エクスポートタブ用: 全建物 */
  allBuildings?: BuildingFeature[];
}

/** タブ定義(モバイル幅では横並び上部タブ、広幅では左タブ列) */
type AdminTabId = 'scrape' | 'export';

const ADMIN_TABS: ReadonlyArray<{ id: AdminTabId; label: string; icon: React.ReactNode }> = [
  { id: 'scrape', label: 'スクレイプ管理', icon: <FaCloudArrowDown /> },
  { id: 'export', label: 'エクスポート', icon: <FaFileExport /> },
];

export const AdminModal: React.FC<AdminModalProps> = ({ isOpen, onClose, onGeoJsonLoaded, filteredBuildings, allBuildings }) => {
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
      {activeTab === 'export' && filteredBuildings && allBuildings && (
        /* ── エクスポートタブ (Google Earth 用 KML) ── */
        <div className="p-5 flex flex-col gap-5">
          <ExportTab filteredBuildings={filteredBuildings} allBuildings={allBuildings} />
        </div>
      )}
    </SettingsModalShell>
  );
};
