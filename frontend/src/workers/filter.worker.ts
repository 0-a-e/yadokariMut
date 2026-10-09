import type { BoundsData, BuildingGeoJSON, MapFilters } from '../types.ts';
import { applyBuildingFilters } from '../lib/filterLogic.ts';

export interface FilterRequestData {
  rawBuildingData: BuildingGeoJSON | null;
  filters: MapFilters;
  mapBounds: BoundsData | null;
}

self.onmessage = function (
  e: MessageEvent<{ type: string; requestId: number; data: FilterRequestData }>,
) {
  const { type, requestId, data } = e.data;
  if (type === 'filter') {
    const { rawBuildingData, filters, mapBounds } = data;
    const { buildings, matchedRoomIds, excludedUnestimable } = applyBuildingFilters(
      rawBuildingData,
      filters,
      mapBounds,
    );
    self.postMessage({
      type: 'filterResult',
      requestId,
      buildings,
      matchedRoomIds,
      excludedUnestimable,
    });
  }
};
