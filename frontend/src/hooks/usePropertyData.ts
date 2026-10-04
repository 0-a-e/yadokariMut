import { useEffect, useRef, useState } from 'react';
import type { PropertyGeoJSON } from '../types.ts';
import { streamGeojson } from '../lib/geojsonStream.ts';
import type { GeojsonLoadProgressState } from '../lib/geojsonStream.ts';
import { fetchGeojsonBulk, fetchLocalGeojson } from '../lib/api/geojson.ts';

/**
 * 物件 GeoJSON の初期ロード。
 *
 * NDJSONストリームで物件単位の進捗を出しつつ読み込み、失敗時は
 * 一括API → /map.geojson(ローカル) の順にフォールバックする。
 * rawGeojsonRef は Worker 実行や id 解決など、最新値を同期的に読みたい箇所向け。
 */
export function usePropertyData(): {
  rawGeojsonData: PropertyGeoJSON | null;
  setRawGeojsonData: React.Dispatch<React.SetStateAction<PropertyGeoJSON | null>>;
  rawGeojsonRef: React.MutableRefObject<PropertyGeoJSON | null>;
  /** 初期ロード進捗(ページ表示〜物件情報表示の間のみ非null) */
  geojsonProgress: GeojsonLoadProgressState | null;
} {
  const [rawGeojsonData, setRawGeojsonData] = useState<PropertyGeoJSON | null>(null);
  const [geojsonProgress, setGeojsonProgress] = useState<GeojsonLoadProgressState | null>(null);
  const rawGeojsonRef = useRef<PropertyGeoJSON | null>(null);

  useEffect(() => {
    rawGeojsonRef.current = rawGeojsonData;
  }, [rawGeojsonData]);

  useEffect(() => {
    const load = async () => {
      setGeojsonProgress({ phase: 'stream', received: 0, total: null });
      try {
        const data = await streamGeojson((p) => {
          setGeojsonProgress({ phase: 'stream', received: p.received, total: p.total });
        });
        setRawGeojsonData(data);
        setGeojsonProgress(null);
        return;
      } catch (e) {
        console.warn('API geojson stream failed, falling back to bulk fetch...', e);
      }
      setGeojsonProgress({ phase: 'bulk', received: 0, total: null });
      try {
        const data = await fetchGeojsonBulk();
        setRawGeojsonData(data);
        setGeojsonProgress(null);
        return;
      } catch (e) {
        console.warn('API geojson fetch failed, falling back to local file...');
      }
      setGeojsonProgress({ phase: 'local', received: 0, total: null });
      try {
        const data = await fetchLocalGeojson();
        if (data) {
          setRawGeojsonData(data);
        }
      } catch (e) {
        console.error('Could not load map.geojson', e);
      } finally {
        setGeojsonProgress(null);
      }
    };
    void load();
  }, []);

  return { rawGeojsonData, setRawGeojsonData, rawGeojsonRef, geojsonProgress };
}
