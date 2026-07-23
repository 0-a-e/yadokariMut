import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet.markercluster';
import { PropertyFeature, BoundsData } from '../types';
import { getScoreColor } from './PropertyCard';

interface MapPaneProps {
  filteredFeatures: PropertyFeature[];
  selectedId: number | null;
  activeLayer: 'dark' | 'pale' | 'satellite';
  onMarkerClick: (feature: PropertyFeature) => void;
  onMapMove?: (center: [number, number], zoom: number, bounds: BoundsData) => void;
  onMapInit?: (map: L.Map, cluster: any) => void;
  /** When false, container may be hidden; set true to trigger invalidateSize. */
  isVisible?: boolean;
}

export const MapPane: React.FC<MapPaneProps> = ({
  filteredFeatures, selectedId, activeLayer, onMarkerClick, onMapMove, onMapInit,
  isVisible = true,
}) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const clusterGroupRef = useRef<any>(null);
  const layersRef = useRef<{ [key: string]: L.TileLayer }>({});
  const markersRef = useRef<{ [key: number]: L.Marker }>({});
  const isFirstLoadRef = useRef(true);
  const isPanningToSelectedRef = useRef(false);
  const prevFeatureSignatureRef = useRef<string>('');

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    const map = L.map(mapRef.current, { zoomControl: false }).setView([35.6812, 139.7671], 13);
    mapInstanceRef.current = map;
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Resizable panels / tab visibility changes need invalidateSize
    const ro = new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
    });
    ro.observe(mapRef.current);
    // store for cleanup on unmount of this init effect
    (map as any)._resizeObserver = ro;

    const darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd', maxZoom: 20,
    });
    const paleLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>', maxZoom: 18,
    });
    const satelliteLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg', {
      attribution: '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>', maxZoom: 18,
    });

    layersRef.current = { dark: darkLayer, pale: paleLayer, satellite: satelliteLayer };
    paleLayer.addTo(map);

    const clusterGroup = (L as any).markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 45,
      iconCreateFunction: (cluster: any) => {
        const childCount = cluster.getChildCount();
        let c = ' marker-cluster-';
        if (childCount < 10) c += 'small';
        else if (childCount < 100) c += 'medium';
        else c += 'large';
        return new L.DivIcon({ html: `<div><span>${childCount}</span></div>`, className: 'marker-cluster' + c, iconSize: new L.Point(40, 40) });
      },
    });
    map.addLayer(clusterGroup);
    clusterGroupRef.current = clusterGroup;

    if (onMapInit) {
      onMapInit(map, clusterGroup);
    }

    return () => {
      try {
        ro.disconnect();
      } catch {
        /* ignore */
      }
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    const t = window.setTimeout(() => {
      mapInstanceRef.current?.invalidateSize({ animate: false });
    }, 80);
    return () => window.clearTimeout(t);
  }, [isVisible]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !onMapMove) return;

    const handleMove = () => {
      if (isPanningToSelectedRef.current) return;
      const center = map.getCenter();
      const b = map.getBounds();
      const bounds: BoundsData = {
        southWest: [b.getSouthWest().lat, b.getSouthWest().lng],
        northEast: [b.getNorthEast().lat, b.getNorthEast().lng],
      };
      onMapMove([center.lat, center.lng], map.getZoom(), bounds);
    };

    map.on('moveend', handleMove);
    return () => { map.off('moveend', handleMove); };
  }, [onMapMove]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    Object.entries(layersRef.current).forEach(([name, layer]) => {
      if (name === activeLayer) { if (!map.hasLayer(layer)) layer.addTo(map); }
      else { if (map.hasLayer(layer)) map.removeLayer(layer); }
    });
  }, [activeLayer]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const cluster = clusterGroupRef.current;
    if (!map || !cluster) return;

    const signature = filteredFeatures.map(f => `${f.properties.id}-${f.properties.shortlist_status}`).join(',');
    if (signature === prevFeatureSignatureRef.current) {
      return;
    }
    prevFeatureSignatureRef.current = signature;

    cluster.clearLayers();
    markersRef.current = {};

    const markers: L.Marker[] = [];
    filteredFeatures.forEach((feat) => {
      const coords = feat.geometry?.coordinates;
      if (!coords || coords.length < 2) return;

      const latlng: L.LatLngExpression = [coords[1], coords[0]];
      const score = feat.properties.total_score || 0;
      const color = getScoreColor(score);
      const scoreRound = Math.round(score);

      const html = `
        <div class="custom-div-icon">
          <div class="marker-pin" style="background-color: ${color};" id="marker-pin-${feat.properties.id}"></div>
          <div class="marker-label">${scoreRound}</div>
        </div>`;

      const icon = L.divIcon({ html, iconSize: [32, 32], iconAnchor: [16, 32], className: '' });
      const marker = L.marker(latlng, { icon }).on('click', () => onMarkerClick(feat));

      // Bind custom tooltip showing details and active campaigns
      const activeCampaigns = feat.properties.campaigns 
        ? feat.properties.campaigns.filter(c => c.is_active !== false)
        : [];
      
      const campaignBadges = activeCampaigns.length > 0
        ? `<div class="mt-1 flex flex-wrap gap-1">
            ${activeCampaigns.map(c => `
              <span style="background-color: rgba(0, 230, 118, 0.12); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.3); border-radius: 4px; padding: 2px 4px; font-size: calc(9px * var(--font-scale)); font-weight: 700; display: inline-flex; align-items: center; gap: 2px; white-space: nowrap;">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" style="width:9px;height:9px;display:inline;fill:#00e676;margin-right:2px"><path d="M0 80V229.5c0 17 6.7 33.3 18.7 45.3L176 432c24.9 24.9 65.4 24.9 90.3 0L421.3 278.3c24.9-24.9 24.9-65.4 0-90.3L263.8 30.3C252.8 19.3 236.5 4.7 224 0H80C35.8 0 0 35.8 0 80zm112 48a32 32 0 1 1 0 64 32 32 0 1 1 0-64z"/></svg>${c.title.length > 12 ? c.title.substring(0, 12) + '...' : c.title}
              </span>
            `).join('')}
           </div>`
        : '';
        
      const tooltipContent = `
        <div style="padding: 6px; font-family: 'Outfit', 'Noto Sans JP', sans-serif;">
          <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #fff; margin-bottom: 2px;">${feat.properties.title}</div>
          <div style="font-size: calc(10px * var(--font-scale)); color: #8e95a5; margin-bottom: 4px;">
            ${feat.properties.layout} | ${feat.properties.area_m2 ? `${feat.properties.area_m2}㎡` : '広さ不明'} | ${feat.properties.min_walk_minutes ? `徒歩${feat.properties.min_walk_minutes}分` : '徒歩不明'}
          </div>
          <div style="font-weight: 700; font-size: calc(11px * var(--font-scale)); color: #00f2fe;">
            ${
              feat.properties.stay_estimate?.ok &&
              feat.properties.stay_estimate.stayTotalYen != null
                ? `${feat.properties.stay_estimate.stayTotalYen.toLocaleString()}円（${feat.properties.stay_estimate.stayDays}日）`
                : feat.properties.min_daily_rent
                  ? `${feat.properties.min_daily_rent.toLocaleString()}円/日`
                  : '詳細参照'
            }
          </div>
          ${campaignBadges}
        </div>
      `;
      
      marker.bindTooltip(tooltipContent, {
        direction: 'top',
        offset: [0, -26],
        className: 'leaflet-custom-tooltip border border-border bg-panel backdrop-blur-glass shadow-lg rounded-lg text-text',
        sticky: false
      });

      markersRef.current[feat.properties.id] = marker;
      markers.push(marker);
    });

    cluster.addLayers(markers);
    if (markers.length > 0 && isFirstLoadRef.current) {
      map.fitBounds(cluster.getBounds(), { padding: [50, 50] });
      isFirstLoadRef.current = false;
    }
  }, [filteredFeatures, onMarkerClick]);

  useEffect(() => {
    document.querySelectorAll('.marker-pin').forEach((el) => {
      const pin = el as HTMLElement;
      pin.classList.remove('active');
      pin.style.borderColor = '#fff';
    });

    if (selectedId === null) return;

    const pin = document.getElementById(`marker-pin-${selectedId}`);
    if (pin) {
      pin.classList.add('active');
      pin.style.borderColor = 'var(--accent)';
    }

    const marker = markersRef.current[selectedId];
    const cluster = clusterGroupRef.current;
    const map = mapInstanceRef.current;
    if (marker && typeof marker.getLatLng === 'function' && map) {
      const latlng = marker.getLatLng();
      if (latlng) {
        isPanningToSelectedRef.current = true;
        const onPanComplete = () => {
          setTimeout(() => {
            isPanningToSelectedRef.current = false;
          }, 300);
        };

        if (cluster && typeof cluster.hasLayer === 'function' && cluster.hasLayer(marker) && (marker as any).__parent) {
          try {
            cluster.zoomToShowLayer(marker, () => {
              map.panTo(latlng);
              onPanComplete();
            });
          } catch {
            // マーカーがクラスター内にない場合などのフォールバック
            map.panTo(latlng);
            onPanComplete();
          }
        } else {
          map.panTo(latlng);
          onPanComplete();
        }
      }
    }
  }, [selectedId]);

  return (
    <div className="grow h-full w-full min-h-0 relative">
      <div id="map" ref={mapRef} className="absolute inset-0 h-full w-full" />
    </div>
  );
};
