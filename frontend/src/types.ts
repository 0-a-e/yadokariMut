/**
 * FE 型サーフェス。
 *
 * BE 応答の契約正本は src/api_models.py (pydantic) であり、
 * frontend/openapi.json (scripts/export_openapi.py が生成) を
 * openapi-typescript で変換した src/lib/api/schema.d.ts に型として取り込む。
 * このファイルは同名エイリアスで再輸出するため、呼び出し側は従来どおり
 * types.ts から import すればよい。
 *
 * - BE 応答を直接受ける型 → 生成型のエイリアス(名前差はここで吸収)
 * - POST ボディ(BE が意図的に未モデル化の部分マージ更新) → 引き続き手書き
 * - FE 内部の型・定数(MapFilters 等) → 引き続きここで定義
 */
import type { components } from './lib/api/schema';

type Schemas = components['schemas'];

// ============================================================
// BE 応答型(生成型のエイリアス)
// ============================================================

export type RentPlan = Schemas['RentPlan'];

export type Campaign = Schemas['Campaign'];

/**
 * Snapshot row from property_snapshots (discounted, not effective).
 * BE は品質ガード(0.25x〜4x 参照値比)適用後の値のみ返すが、旧キャッシュ等の
 * 欠損に備え parseDaily (lib/analysis/propertyHistory.ts) が null/NaN を
 * 防御的に扱うため、このフィールドのみ nullable を許容する。
 */
export type PriceHistoryPoint = Omit<
  Schemas['PriceHistoryPoint'],
  'min_discounted_daily_rent_yen'
> & { min_discounted_daily_rent_yen: number | null };

/** 品質ガード(0.25x〜4x 参照値比)適用後の価格履歴メタ。破損値は BE が除外する */
export type PriceHistoryMeta = Schemas['PriceHistoryMeta'];

/** GET /api/analysis/price-trend の日次集計 1 点 */
export type PriceTrendPoint = Schemas['PriceTrendPoint'];

/** 価格変動タブの集計モード。carried=前進補完推計(既定) / scraped=当日取得分 */
export type PriceTrendMode = 'carried' | 'scraped';

/** GET /api/analysis/price-trend のレスポンス(全プロバイダ分を一括返却) */
export type PriceTrendResponse = Schemas['PriceTrendResponse'];

/** Response shape from GET /api/properties/{id}. */
export type PropertyDetailResponse = Schemas['PropertyDetailResponse'];

// ── 管理 API ──

export type TransferBucket = Schemas['TransferBucket'];

/** 1スクレイプrunのサマリ(GET /api/admin/status recent_runs — DB由来で再起動後も残る) */
export type ScrapeRunSummary = Schemas['ScrapeRunSummary'];

/** GET /api/admin/status */
export type AdminStats = Schemas['AdminStatsResponse'];

/** Per-prefecture (ListTarget) status under a source — GET /api/admin/sources */
export type AdminTargetInfo = Schemas['AdminTargetInfo'];

/** GET /api/admin/sources */
export type AdminSourceInfo = Schemas['AdminSourceInfo'];

export type AdminSourcesResponse = Schemas['AdminSourcesResponse'];

/** 次回実行バッチのプレビュー — GET /api/admin/rotation */
export type RotationBatchPreview = Schemas['RotationBatchPreview'];

/** 県（ListTarget）ごとのローテーション状態 — GET /api/admin/rotation */
export type RotationPrefStatus = Schemas['RotationPrefStatus'];

/** ソースごとの県ローテーション状態 — GET /api/admin/rotation */
export type RotationSourceStatus = Schemas['RotationSourceStatus'];

/** GET /api/admin/rotation */
export type RotationStatusResponse = Schemas['RotationStatusResponse'];

/** ソース1件分のスクレイプ設定(実効値 + 保存済み上書き) — GET /api/admin/scrape-settings */
export type ScrapeSourceSettings = Schemas['ScrapeSourceSettings'];

/** GET /api/admin/scrape-settings */
export type ScrapeSettingsResponse = Schemas['ScrapeSettingsResponse'];

/** ソース1件分のローテーション設定(実効値 + 保存済み上書き) — GET /api/admin/rotation-settings */
export type RotationSourceSettings = Schemas['RotationSourceSettings'];

/** GET /api/admin/rotation-settings */
export type RotationSettingsResponse = Schemas['RotationSettingsResponse'];

// ── チャットスレッド API ──

export type ChatThreadSummary = Schemas['ChatThreadSummary'];

export type ChatThreadsResponse = Schemas['ChatThreadsResponse'];

export type ChatThreadMessage = Schemas['ChatThreadMessage'];

export type ChatThreadMessagesResponse = Schemas['ChatThreadMessagesResponse'];

export type ChatThreadDeleteResponse = Schemas['ChatThreadDeleteResponse'];

// ============================================================
// GeoJSON
// ============================================================

/**
 * GeoJSON Feature の properties。
 * 生成型(= BE /api/geojson 応答)に、FE 側で付与する派生フィールドを
 * 交差型で追加する(BE は返さない: Worker 計算値・詳細 API 由来の遅延値)。
 */
export type PropertyProperties = Schemas['PropertyProperties'] & {
  /** stay モードのフィルタ結果に付与（Worker 内で計算。永続フィールドではない） */
  stay_estimate?: StayEstimateSummary | null;
  /** Shortlist memo (from detail API; not on GeoJSON by default) */
  shortlist_comment?: string | null;
  /**
   * 契約事務手数料(円)。詳細API(properties 行)のみに含まれ、GeoJSON properties
   * には無い(無い経路では計算側の既定値 5500 にフォールバック)。null = 未設定
   */
  contract_fee_yen?: number | null;
  /** Lazy-fetched from GET /api/properties/{id} */
  price_history?: PriceHistoryPoint[];
};

/** GeoJSON Feature 1 件 (Point)。geometry は生成型([lng, lat] の number[])をそのまま使う */
export type PropertyFeature = Omit<Schemas['PropertyFeature'], 'properties'> & {
  properties: PropertyProperties;
};

/** GET /api/geojson の FeatureCollection 応答(features は FE 内部契約の PropertyFeature) */
export type PropertyGeoJSON = Omit<Schemas['PropertyGeoJSON'], 'features'> & {
  features: PropertyFeature[];
};

// ============================================================
// POST ボディ(BE が意図的に未モデル化の部分マージ更新。null = 既定へ戻す)
// ============================================================

/** POST /api/admin/rotation-settings (部分マージ。null で既定へ戻す) */
export interface RotationSettingsUpdate {
  sources: {
    [sourceId: string]:
      | Partial<{ daily_limit: number | null; default_est: number | null }>
      | null;
  };
}

/** POST /api/admin/scrape-settings のボディ。null で該当キーを既定へ戻す */
export interface ScrapeSettingsUpdate {
  sources: Record<
    string,
    | null
    | Partial<{ delay_seconds: number | null; cooldown_seconds: number | null }>
  >;
}

// ============================================================
// FE 内部型( BE 応答を直接受けない )
// ============================================================

/** 分析モーダルの表示対象。market=市場全体(メニューから) / property=物件単位(詳細パネルから) */
export type AnalysisTarget =
  | { kind: 'market' }
  | { kind: 'property'; propertyId: number };

export type ShortlistStatusFilter = 'all' | 'saved' | 'unsaved' | 'hide' | 'reject';
export type SortKey = 'score' | 'price_asc' | 'price_desc' | 'area_desc';
/** 掲載状態フィルタ（全て / 掲載中 / 非掲載）。既定は掲載中 */
export type ListingVisibilityFilter = 'all' | 'active' | 'inactive';
export type ShortlistStatus = 'saved' | 'hide' | 'reject' | 'none';
/** catalog = カタログ最安 / stay = 指定期間の試算総額 */
export type PriceMode = 'catalog' | 'stay';

/** catalog スライダー右端 = 制限なし */
export const CATALOG_PRICE_UNLIMITED = 300_000;
/** stay スライダー右端 = 制限なし */
export const STAY_PRICE_UNLIMITED = 1_000_000;

/** フィルタ結果に付与する期間総額サマリ（Worker 内で計算） */
export interface StayEstimateSummary {
  ok: boolean;
  stayDays: number;
  stayTotalYen: number | null;
  rentDailyYen: number | null;
  selectedPlanCode: string | null;
  usedFallback: boolean;
  planLabel: string | null;
}

/** 範囲絞り込みモード: 全件 / 地図表示範囲 / 囲った範囲 */
export type AreaMode = 'all' | 'viewport' | 'drawn';

export interface MapFilters {
  maxPrice: number;
  areaRange: [number, number];
  layout: string;
  status: ShortlistStatusFilter;
  listingVisibility: ListingVisibilityFilter;
  searchQuery: string;
  areaMode: AreaMode;
  /** areaMode='drawn' で使う閉多角形の頂点列 [lng, lat][]（矩形は4頂点） */
  drawnPolygon: [number, number][] | null;
  maxWalkMinutes: number | null;
  minScore: number | null;
  prefecture: string | null;
  requiredFeatures: string[];
  /** Empty = all sources */
  sources: string[];
  sortBy: SortKey;
  priceMode: PriceMode;
  /** YYYY-MM-DD */
  checkIn: string;
  /** YYYY-MM-DD */
  checkOut: string;
}

export const DEFAULT_MAP_FILTERS: MapFilters = {
  maxPrice: STAY_PRICE_UNLIMITED,
  areaRange: [10, 50],
  layout: 'all',
  status: 'all',
  listingVisibility: 'active',
  searchQuery: '',
  areaMode: 'all',
  drawnPolygon: null,
  maxWalkMinutes: null,
  minScore: null,
  prefecture: null,
  requiredFeatures: [],
  sources: [],
  sortBy: 'score',
  priceMode: 'stay',
  checkIn: '2026-08-01',
  checkOut: '2026-09-01',
};

/** Differentiating equipment toggles (partial-match against feature_summary). */
export const FEATURE_TOGGLE_OPTIONS = [
  'オートロック',
  'セパレート',
  '洗濯機',
  'エレベーター',
  'クローゼット',
  'モニター付きインターホン',
] as const;

export interface BoundsData {
  southWest: [number, number]; // [lat, lng]
  northEast: [number, number]; // [lat, lng]
}
