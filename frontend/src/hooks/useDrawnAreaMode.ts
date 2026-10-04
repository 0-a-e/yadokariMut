import { useCallback, useEffect, useRef, useState } from 'react';
import type { MapFilters } from '../types.ts';

interface UseDrawnAreaModeOptions {
  filters: MapFilters;
  filtersRef: React.MutableRefObject<MapFilters>;
  patchFilters: (patch: Partial<MapFilters> & { reset?: boolean }) => void;
  isMobile: boolean;
  /** 描画要求時に地図タブへ切り替える(モバイルのみ) */
  setMobileTab: (tab: 'map') => void;
}

/**
 * 囲み範囲フィルタの描画モード(MapPane の Geoman 起動スイッチ)。
 *
 * - 「囲む」が選ばれたのにシェイプ未描画なら描画モードへ(モバイルは地図タブへ切替)
 * - 「囲む」から他モードへ切り替えた場合は描画も止める
 *   (地図ボタンから直接描画した場合は areaMode が all のままなので止めない)
 */
export function useDrawnAreaMode({
  filters,
  filtersRef,
  patchFilters,
  isMobile,
  setMobileTab,
}: UseDrawnAreaModeOptions): {
  drawMode: boolean;
  handleShapeDrawn: (polygon: [number, number][]) => void;
  handleShapeClear: () => void;
  handleDrawModeChange: (active: boolean) => void;
} {
  const [drawMode, setDrawMode] = useState(false);
  const prevAreaModeRef = useRef(filters.areaMode);

  useEffect(() => {
    const prev = prevAreaModeRef.current;
    prevAreaModeRef.current = filters.areaMode;
    if (filters.areaMode === 'drawn' && !filters.drawnPolygon) {
      if (!drawMode) {
        setDrawMode(true);
        if (isMobile) setMobileTab('map');
      }
    } else if (prev === 'drawn' && filters.areaMode !== 'drawn' && drawMode && !filters.drawnPolygon) {
      setDrawMode(false);
    }
  }, [filters.areaMode, filters.drawnPolygon, drawMode, isMobile, setMobileTab]);

  const handleShapeDrawn = useCallback(
    (polygon: [number, number][]) => {
      setDrawMode(false);
      patchFilters({ drawnPolygon: polygon, areaMode: 'drawn' });
    },
    [patchFilters],
  );

  const handleShapeClear = useCallback(() => {
    setDrawMode(false);
    const patch: Partial<MapFilters> = { drawnPolygon: null };
    if (filtersRef.current.areaMode === 'drawn') patch.areaMode = 'all';
    patchFilters(patch);
  }, [patchFilters, filtersRef]);

  const handleDrawModeChange = useCallback(
    (active: boolean) => {
      setDrawMode(active);
      // 描画をキャンセルしてシェイプ未確定なら「囲む」選択を取り消す
      if (!active && filtersRef.current.areaMode === 'drawn' && !filtersRef.current.drawnPolygon) {
        patchFilters({ areaMode: 'all' });
      }
    },
    [patchFilters, filtersRef],
  );

  return { drawMode, handleShapeDrawn, handleShapeClear, handleDrawModeChange };
}
