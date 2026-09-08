import L from 'leaflet';
import type { LayerAdapter, LayerCatalogEntry } from '../types';

/**
 * オシマランド(大島てる)事故物件マーカーレイヤ。
 *
 * - マーカー取得: POST https://api.oshimaland.co.jp/map に可視範囲の
 *   quadkey(Webメルカトル・Bing式)を 100キー以下のバッチで送る
 * - 最深ズーム16。それ未満では count 付きクラスタが返る
 * - 公式想定の Cache-Control: max-age=3600 に合わせ1時間のキャッシュで
 *   リクエストを絞る(負荷配慮)。失敗したバッチは黙ってスキップし、
 *   次回の moveend で再試行
 * - clustering オプション(setOshimaRuntimeOptions / index.ts の
 *   configureAdapter で変更)で2モード:
 *   - false(既定): z16固定の個別マーカーのみ。zoom<12 や可視z16キー過多
 *     (>800)では取得せず非表示
 *   - true: 従来どおり tz=min(zoom,16)。tz<16はサーバーcluster円を描画
 */
const MAP_API_URL = 'https://api.oshimaland.co.jp/map';
const DETAIL_API_URL = 'https://www.oshimaland.co.jp/d';
/** 実データを持つ最深ズーム(仕様)。これを超えるズームでは16のデータを拡大表示 */
const MAX_NATIVE_ZOOM = 16;
/** 1リクエストあたりのキー数上限(約180キーで413になるため余裕を持つ) */
const BATCH_SIZE = 100;
/** タイルデータのキャッシュTTL。公式の Cache-Control: max-age=3600 に準拠 */
const TILE_CACHE_TTL_MS = 60 * 60 * 1000;
const TILE_CACHE_MAX = 4096;
/** 物件詳細の遅延取得キャッシュTTL */
const DETAIL_CACHE_TTL_MS = 60 * 1000;
const DETAIL_CACHE_MAX = 512;
/** moveend/zoomend 連打対策のデバウンス */
const FETCH_DEBOUNCE_MS = 300;
/**
 * クラスタリング無効(個別マーカー)モードの最低ズーム。未満では
 * z16の個別取得が爆発するため何もリクエスト/描画しない
 */
const UNCLUSTERED_MIN_ZOOM = 12;
/** 個別マーカーモードで1画面に許容するz16 quadkey数の上限。超過時はそのズームで非表示 */
const MAX_UNCLUSTERED_KEYS = 800;

interface OshimaMarker {
  key: string;
  latitude: number;
  longitude: number;
  cluster_key?: string;
}

interface OshimaCluster {
  cluster_key: string;
  count: number;
  latitude: number;
  longitude: number;
}

interface OshimaTileData {
  markers: OshimaMarker[];
  clusters: OshimaCluster[];
}

interface CacheEntry<T> {
  ts: number;
  data: T;
}

/** タイル(quadkey単位)キャッシュ。モジュール共有でレイヤ再追加時も再取得しない */
const tileCache = new Map<string, CacheEntry<OshimaTileData>>();
/** 物件詳細ポップアップHTMLのキャッシュ(失敗時のリンクのみHTMLも60秒保持) */
const detailCache = new Map<string, CacheEntry<string>>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function trimCache<T>(cache: Map<string, CacheEntry<T>>, max: number): void {
  while (cache.size > max) {
    const oldest = cache.keys().next();
    if (oldest.done) break;
    cache.delete(oldest.value);
  }
}

function freshEntry<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
  ttlMs: number,
): CacheEntry<T> | undefined {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.ts < ttlMs) return entry;
  return undefined;
}

// ── Webメルカトルタイル計算(Bing式quadkey) ──────────────────────────

function lngToWorldX(lng: number, zoom: number): number {
  return ((lng + 180) / 360) * (1 << zoom);
}

function latToWorldY(lat: number, zoom: number): number {
  const maxLat = 85.05112878;
  const clipped = Math.max(-maxLat, Math.min(maxLat, lat));
  const sin = Math.sin((clipped * Math.PI) / 180);
  return (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * (1 << zoom);
}

/** タイル座標 → Bing式quadkey(上位ビットから x/y を2bitずつ連結) */
function tileToQuadkey(x: number, y: number, zoom: number): string {
  let quadkey = '';
  for (let i = zoom; i > 0; i--) {
    let digit = 0;
    const mask = 1 << (i - 1);
    if ((x & mask) !== 0) digit += 1;
    if ((y & mask) !== 0) digit += 2;
    quadkey += String(digit);
  }
  return quadkey;
}

/** 現在の可視範囲にある quadkey 一覧(経度は反子午線またぎを含めてラップ) */
function visibleQuadkeys(map: L.Map, zoom: number): string[] {
  const bounds = map.getBounds();
  const max = 1 << zoom;
  const clamp = (v: number) => Math.max(0, Math.min(max - 1, Math.floor(v)));

  const x0 = clamp(lngToWorldX(bounds.getWest(), zoom));
  const spanX =
    ((clamp(lngToWorldX(bounds.getEast(), zoom)) - x0 + max) % max) + 1;
  const y0 = clamp(latToWorldY(bounds.getNorth(), zoom));
  const spanY =
    clamp(latToWorldY(bounds.getSouth(), zoom)) - y0 + 1;

  const keys: string[] = [];
  for (let iy = 0; iy < spanY; iy++) {
    for (let ix = 0; ix < spanX; ix++) {
      keys.push(tileToQuadkey((x0 + ix) % max, y0 + iy, zoom));
    }
  }
  return keys;
}

// ── APIレスポンスのパース(不正データは黙って落とす) ─────────────────

function parseMarkers(value: unknown): OshimaMarker[] {
  if (!Array.isArray(value)) return [];
  const out: OshimaMarker[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const { key, latitude, longitude } = item;
    if (
      typeof key === 'string' &&
      key.length > 0 &&
      typeof latitude === 'number' &&
      Number.isFinite(latitude) &&
      typeof longitude === 'number' &&
      Number.isFinite(longitude)
    ) {
      out.push({ key, latitude, longitude });
    }
  }
  return out;
}

function parseClusters(value: unknown): OshimaCluster[] {
  if (!Array.isArray(value)) return [];
  const out: OshimaCluster[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const { cluster_key, count, latitude, longitude } = item;
    if (
      typeof cluster_key === 'string' &&
      typeof count === 'number' &&
      Number.isFinite(count) &&
      typeof latitude === 'number' &&
      Number.isFinite(latitude) &&
      typeof longitude === 'number' &&
      Number.isFinite(longitude)
    ) {
      out.push({ cluster_key, count, latitude, longitude });
    }
  }
  return out;
}

/** バッチレスポンスを quadkey 単位でキャッシュへ格納 */
function storeTileResponse(batch: readonly string[], json: unknown): void {
  const body = isRecord(json) ? json : {};
  const markers = isRecord(body.markers) ? body.markers : {};
  const clusters = isRecord(body.clusters) ? body.clusters : {};
  const ts = Date.now();
  for (const quadkey of batch) {
    tileCache.set(quadkey, {
      ts,
      data: {
        markers: parseMarkers(markers[quadkey]),
        clusters: parseClusters(clusters[quadkey]),
      },
    });
  }
  trimCache(tileCache, TILE_CACHE_MAX);
}

// ── ポップアップHTML生成(外部文字列は必ずエスケープ) ────────────────

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      default:
        return '&#39;';
    }
  });
}

function fieldText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}

function shorten(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) + '…' : value;
}

function detailLinkHtml(key: string): string {
  return (
    '<div style="margin-top:6px;">' +
    `<a href="${DETAIL_API_URL}/${encodeURIComponent(key)}" target="_blank" rel="noopener" ` +
    'style="color:#c0392b;">大島てるで詳細を見る</a></div>'
  );
}

/** 詳細取得失敗・JSON不正時に必ず開くフォールバック(リンクのみ) */
function linkOnlyPopupHtml(key: string): string {
  return `<div style="min-width:160px;">${detailLinkHtml(key)}</div>`;
}

function detailPopupHtml(key: string, json: unknown): string {
  if (!isRecord(json)) return linkOnlyPopupHtml(key);
  const dt = fieldText(json.dt);
  const ad = fieldText(json.ad);
  const info = fieldText(json.info);
  const rows: string[] = [];
  if (dt) rows.push(`<div style="font-weight:700;">${escapeHtml(dt)}</div>`);
  if (ad) rows.push(`<div style="margin-top:2px;">${escapeHtml(ad)}</div>`);
  if (info) {
    rows.push(
      `<div style="margin-top:4px;font-size:12px;color:#555;">${escapeHtml(shorten(info, 160))}</div>`,
    );
  }
  rows.push(detailLinkHtml(key));
  return `<div style="min-width:180px;">${rows.join('')}</div>`;
}

// ── アイコン ─────────────────────────────────────────────────────

/** 事故物件マーカー: 赤系円(白枠・中央に白点) */
const PROPERTY_ICON = L.divIcon({
  className: '',
  html:
    '<div style="display:flex;align-items:center;justify-content:center;' +
    'width:22px;height:22px;box-sizing:border-box;border-radius:50%;' +
    'background:#d43c33;border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,0.4);">' +
    '<span style="display:block;width:6px;height:6px;border-radius:50%;background:#fff;"></span></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
  popupAnchor: [0, -12],
});

/** クラスタ: 濃い赤の円に件数を表示 */
function clusterIcon(count: number): L.DivIcon {
  const n = Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
  const label = n > 999 ? '999+' : String(n);
  return L.divIcon({
    className: '',
    html:
      '<div style="display:flex;align-items:center;justify-content:center;' +
      'width:22px;height:22px;box-sizing:border-box;border-radius:50%;' +
      'background:#8f1d1d;border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,0.4);' +
      `color:#fff;font:bold 10px/1 sans-serif;">${label}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    popupAnchor: [0, -11],
  });
}

// ── 実行時オプション(configureAdapter で差し替え) ───────────────────

/**
 * oshimaアダプタの実行時オプション。
 * - clustering: true  = 現行動作(tz=min(zoom,16)。tz<16はサーバーcluster円を描画)
 * - clustering: false = 個別マーカーモード(既定)。z16固定で個別マーカーのみ
 *   (レイヤ設定モーダル: 別branch / ここではApp側effectから注入される)
 */
export interface OshimaRuntimeOptions {
  clustering: boolean;
}

const runtimeOptions: OshimaRuntimeOptions = { clustering: false };

/** アクティブなOshimaLayer。オプション変更時に再取得を促すために保持 */
const activeInstances = new Set<OshimaLayer>();

/**
 * 実行時オプションを更新し、登録済みレイヤへ再取得/再描画を促す。
 * (index.ts の configureAdapter('oshima', ...) から呼ばれる)
 */
export function setOshimaRuntimeOptions(options: Partial<OshimaRuntimeOptions>): void {
  if (options.clustering === undefined || options.clustering === runtimeOptions.clustering) {
    return;
  }
  runtimeOptions.clustering = options.clustering;
  for (const layer of activeInstances) {
    layer.notifyOptionsChanged();
  }
}

// ── レイヤ本体 ───────────────────────────────────────────────────

class OshimaLayer extends L.Layer {
  private readonly paneName: string;
  private readonly group = L.layerGroup();
  private map: L.Map | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private aborter: AbortController | null = null;

  constructor(paneName: string) {
    super();
    this.paneName = paneName;
  }

  onAdd(map: L.Map): this {
    this.map = map;
    activeInstances.add(this);
    map.on('moveend', this.handleMoveEnd, this);
    map.on('zoomend', this.handleMoveEnd, this);
    if (!map.hasLayer(this.group)) map.addLayer(this.group);
    this.scheduleFetch();
    return this;
  }

  onRemove(map: L.Map): this {
    map.off('moveend', this.handleMoveEnd, this);
    map.off('zoomend', this.handleMoveEnd, this);
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.aborter?.abort();
    this.aborter = null;
    map.removeLayer(this.group);
    this.group.clearLayers();
    this.map = null;
    activeInstances.delete(this);
    return this;
  }

  private readonly handleMoveEnd = (): void => {
    this.scheduleFetch();
  };

  /** configureAdapter でのオプション変更時に、現行モードで再取得/再描画させる */
  notifyOptionsChanged(): void {
    this.scheduleFetch();
  }

  /** 300msデバウンス後に可視範囲を取得(連続パンでは前のfetchを中断) */
  private scheduleFetch(): void {
    if (this.debounceTimer !== null) clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      void this.fetchVisible();
    }, FETCH_DEBOUNCE_MS);
  }

  private async fetchVisible(): Promise<void> {
    const map = this.map;
    if (!map) return;
    const rawZoom = Math.round(map.getZoom());

    let targetZoom: number;
    let keys: string[];
    if (runtimeOptions.clustering) {
      // クラスタあり(現行動作): tz=min(zoom,16)。tz<16はcluster円も描く
      targetZoom = Math.max(0, Math.min(rawZoom, MAX_NATIVE_ZOOM));
      keys = visibleQuadkeys(map, targetZoom);
    } else {
      // 個別マーカーモード(既定): z16固定で個別マーカーのみ。低ズームや
      // キー数過多では取得自体を行わず、既存描画も空にする
      if (rawZoom < UNCLUSTERED_MIN_ZOOM) {
        this.cancelFetch();
        this.group.clearLayers();
        return;
      }
      keys = visibleQuadkeys(map, MAX_NATIVE_ZOOM);
      if (keys.length > MAX_UNCLUSTERED_KEYS) {
        this.cancelFetch();
        this.group.clearLayers();
        return;
      }
      targetZoom = MAX_NATIVE_ZOOM;
    }

    const missing = keys.filter((k) => !freshEntry(tileCache, k, TILE_CACHE_TTL_MS));

    if (missing.length > 0) {
      this.aborter?.abort();
      const aborter = new AbortController();
      this.aborter = aborter;
      let aborted = false;
      for (let i = 0; i < missing.length; i += BATCH_SIZE) {
        if (aborter.signal.aborted) {
          aborted = true;
          break;
        }
        const batch = missing.slice(i, i + BATCH_SIZE);
        try {
          const res = await fetch(MAP_API_URL, {
            method: 'POST',
            mode: 'cors',
            // application/json だとCORSプリフライト(OPTIONS)が403で拒否されるため、
            // プリフライト不要な text/plain でJSONボディを送る(公式クライアントと同じ回避法)
            headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
            body: JSON.stringify({ keys: batch }),
            signal: aborter.signal,
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          storeTileResponse(batch, await res.json());
        } catch (err) {
          if (aborter.signal.aborted) {
            aborted = true;
            break;
          }
          // 全滅(オフライン等)してもエラー表示はせず、次回のmoveendで再試行
          console.warn('[oshima] マーカー取得に失敗しました(スキップ)', err);
        }
      }
      if (aborted) return; // 後続の要求が引き継ぐので描画しない
    }

    this.render(keys, targetZoom);
  }

  /** 進行中のフェッチがあれば中断する(モード切替・非表示化時) */
  private cancelFetch(): void {
    this.aborter?.abort();
    this.aborter = null;
  }

  /** 可視quadkeyのキャッシュデータを描画(marker.keyで全体重複排除) */
  private render(keys: readonly string[], zoom: number): void {
    this.group.clearLayers();
    const seen = new Set<string>();
    for (const quadkey of keys) {
      const entry = freshEntry(tileCache, quadkey, TILE_CACHE_TTL_MS);
      if (!entry) continue;
      for (const m of entry.data.markers) {
        if (seen.has(m.key)) continue;
        seen.add(m.key);
        const marker = L.marker([m.latitude, m.longitude], {
          pane: this.paneName,
          icon: PROPERTY_ICON,
          title: '大島てる 事故物件',
        });
        marker.on('click', () => {
          void this.openDetailPopup(marker, m.key);
        });
        this.group.addLayer(marker);
      }
      if (zoom < MAX_NATIVE_ZOOM) {
        for (const c of entry.data.clusters) {
          this.group.addLayer(
            L.marker([c.latitude, c.longitude], {
              pane: this.paneName,
              icon: clusterIcon(c.count),
              title: `大島てる 事故物件 ${c.count}件`,
            }),
          );
        }
      }
    }
  }

  /** クリック時に詳細を遅延取得。失敗時もリンクのみのポップアップを必ず開く */
  private async openDetailPopup(marker: L.Marker, key: string): Promise<void> {
    const cached = freshEntry(detailCache, key, DETAIL_CACHE_TTL_MS);
    if (cached) {
      marker.bindPopup(cached.data, { maxWidth: 320 });
      marker.openPopup();
      return;
    }
    // 先に読み込み中ポップアップを開いておく(失敗時も開いたままになる)
    marker.bindPopup('<div style="min-width:120px;">読み込み中…</div>', {
      maxWidth: 320,
    });
    marker.openPopup();

    let html: string;
    try {
      const res = await fetch(`${DETAIL_API_URL}/${encodeURIComponent(key)}.json`, {
        mode: 'cors',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      html = detailPopupHtml(key, await res.json());
    } catch (err) {
      // www側はCloudflare保護下で失敗しうる。リンクのみで代替
      console.warn('[oshima] 詳細取得に失敗しました(リンクのみ表示)', err);
      html = linkOnlyPopupHtml(key);
    }
    detailCache.set(key, { ts: Date.now(), data: html });
    trimCache(detailCache, DETAIL_CACHE_MAX);
    // 待機中にマーカーが描画し直されても害のないよう、存在チェックなしで呼ぶ
    marker.setPopupContent(html);
    marker.openPopup();
  }
}

export const oshimaAdapter: LayerAdapter = {
  create: (_entry: LayerCatalogEntry, paneName: string): L.Layer =>
    new OshimaLayer(paneName),
};
