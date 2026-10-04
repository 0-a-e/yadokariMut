import L from 'leaflet';
import type { LayerAdapter, LayerCatalogEntry } from '../types.ts';

/** XYZラスタタイル汎用アダプタ(GSI/CARTO等のEPSG:3857タイルに対応) */
export const tileAdapter: LayerAdapter = {
  create(entry: LayerCatalogEntry, paneName: string): L.Layer {
    return L.tileLayer(entry.urlTemplate ?? '', {
      pane: paneName,
      attribution: entry.attribution,
      minZoom: entry.minZoom,
      maxNativeZoom: entry.maxNativeZoom,
      maxZoom: entry.maxZoom ?? 20,
      subdomains: entry.subdomains ?? 'abc',
    });
  },
};
