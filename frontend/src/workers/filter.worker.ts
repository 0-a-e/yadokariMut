import { BoundsData, MapFilters, PropertyGeoJSON } from '../types';
import { applyMapFilters } from '../lib/filterLogic';

export interface FilterRequestData {
  rawGeojsonData: PropertyGeoJSON | null;
  filters: MapFilters;
  mapBounds: BoundsData | null;
}

self.onmessage = function (
  e: MessageEvent<{ type: string; requestId: number; data: FilterRequestData }>,
) {
  const { type, requestId, data } = e.data;
  if (type === 'filter') {
    const { rawGeojsonData, filters, mapBounds } = data;
    const { features, excludedUnestimable } = applyMapFilters(
      rawGeojsonData,
      filters,
      mapBounds,
    );
    self.postMessage({ type: 'filterResult', requestId, features, excludedUnestimable });
  }
};
