import { useEffect, useRef, useState } from 'react';
import type { BuildingGeoJSON } from '../types.ts';
import { streamBuildingGeojson } from '../lib/geojsonStream.ts';
import type { GeojsonLoadProgressState } from '../lib/geojsonStream.ts';
import { fetchBuildingsGeojson } from '../lib/api/geojson.ts';

/**
 * 建物 GeoJSON(1 Feature = 1 建物 + units)の初期ロード(Phase B2-α)。
 *
 * NDJSON ストリームで建物単位の進捗を出しつつ読み込み、失敗時は一括 API へ
 * フォールバックする(旧 3 段目 /map.geojson は B2 承認で廃止・計画 §9-8)。
 * rawBuildingRef は Worker 実行や id 解決など、最新値を同期的に読みたい箇所向け。
 */
export function useBuildingData(): {
  rawBuildingData: BuildingGeoJSON | null;
  setRawBuildingData: React.Dispatch<React.SetStateAction<BuildingGeoJSON | null>>;
  rawBuildingRef: React.RefObject<BuildingGeoJSON | null>;
  /** 初期ロード進捗(ページ表示〜物件情報表示の間のみ非null) */
  geojsonProgress: GeojsonLoadProgressState | null;
} {
  const [rawBuildingData, setRawBuildingData] = useState<BuildingGeoJSON | null>(null);
  const [geojsonProgress, setGeojsonProgress] = useState<GeojsonLoadProgressState | null>(null);
  const rawBuildingRef = useRef<BuildingGeoJSON | null>(null);

  useEffect(() => {
    rawBuildingRef.current = rawBuildingData;
  }, [rawBuildingData]);

  useEffect(() => {
    const load = async () => {
      setGeojsonProgress({ phase: 'stream', received: 0, total: null });
      try {
        const data = await streamBuildingGeojson((p) => {
          setGeojsonProgress({ phase: 'stream', received: p.received, total: p.total });
        });
        setRawBuildingData(data);
        setGeojsonProgress(null);
        return;
      } catch (e) {
        console.warn('Building geojson stream failed, falling back to bulk fetch...', e);
      }
      setGeojsonProgress({ phase: 'bulk', received: 0, total: null });
      try {
        const data = await fetchBuildingsGeojson();
        setRawBuildingData(data);
      } catch (e) {
        console.error('Could not load building geojson', e);
      } finally {
        setGeojsonProgress(null);
      }
    };
    void load();
  }, []);

  return { rawBuildingData, setRawBuildingData, rawBuildingRef, geojsonProgress };
}
