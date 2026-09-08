export interface RentPlan {
  plan_code?: string | null;
  plan_name: string;
  duration_text?: string | null;
  available: boolean;
  discounted_daily_rent_yen: number | null;
  original_daily_rent_yen: number | null;
  campaign_label: string | null;
  discounted_total_yen: number | null;
  total_period_days: number | null;
  management_fee_daily_yen: number | null;
  cleaning_fee_yen: number | null;
  /** Active-campaign-aware daily rent (falls back to original when expired) */
  effective_daily_rent_yen?: number | null;
  effective_total_yen?: number | null;
  /** True when an active campaign justifies the discounted snapshot */
  campaign_applied?: boolean;
  campaign_expired?: boolean;
  expired_campaign_label?: string | null;
  effective_campaign_label?: string | null;
  matched_campaign_type?: string | null;
}

export interface Campaign {
  campaign_type: string;
  title: string;
  content: string;
  target_period_text: string;
  target_condition_text: string | null;
  starts_on: string | null;
  ends_on: string | null;
  target_plan_code?: string;
  is_active?: boolean;
  /** ends_on is NULL (ongoing or unknown period) */
  date_end_unknown?: boolean;
  /** yen | percent | package | pokkiri | free_first_week | unknown */
  discount_unit?: string | null;
  discount_value?: number | null;
  discount_max_yen?: number | null;
  period_max_days?: number | null;
  stay_min_days?: number | null;
  stay_max_days?: number | null;
  contract_within_days?: number | null;
  package_rent_benefit_yen?: number | null;
  package_cleaning_benefit_yen?: number | null;
  package_fee_benefit_yen?: number | null;
  package_total_benefit_yen?: number | null;
  structure_source?: string | null;
  parse_ok?: number | null;
}

/** Snapshot row from property_snapshots (discounted, not effective). */
export interface PriceHistoryPoint {
  scraped_at: string;
  min_discounted_daily_rent_yen: number | null;
  min_discounted_monthly_total_yen?: number | null;
}

export interface PropertyProperties {
  id: number;
  room_id: string;
  /** Multi-source site key (e.g. bratto, unionmonthly) */
  source_site?: string | null;
  /** Human-readable source label for badges */
  source_display_name?: string | null;
  title: string;
  detail_url: string;
  address: string;
  prefecture_name?: string | null;
  layout: string;
  area_m2: number | null;
  min_daily_rent: number | null;
  min_plan_total: number | null;
  min_plan_name: string | null;
  min_walk_minutes: number | null;
  thumbnail_url: string | null;
  images: string[];
  total_score: number;
  shortlist_status: 'saved' | 'hide' | 'reject' | 'none';
  /** false = 掲載終了（サイトから消えた物件。shortlist判定済みのみ表示される） */
  is_active?: boolean;
  /** 最終確認日時（掲載終了時に「最終取得時点」の参考値である旨を示す） */
  last_seen_at?: string | null;
  /** Shortlist memo (from detail API; not on GeoJSON by default) */
  shortlist_comment?: string | null;
  access_summary: string;
  feature_summary: string;
  station_summary: string;
  /** 物件紹介文（POINT）。無い場合は null/空 */
  point_text?: string | null;
  rent_plans: RentPlan[];
  campaigns?: Campaign[];
  /** stay モードのフィルタ結果に付与（永続フィールドではない） */
  stay_estimate?: StayEstimateSummary | null;
  /** Lazy-fetched from GET /api/properties/{id} */
  price_history?: PriceHistoryPoint[];
}

/** Response shape from GET /api/properties/{id} (subset we use on FE). */
export interface PropertyDetailResponse {
  id: number;
  shortlist?: {
    status?: string | null;
    comment?: string | null;
    updated_at?: string | null;
  } | null;
  price_history?: PriceHistoryPoint[];
  point_text?: string | null;
  campaigns?: Campaign[];
  rent_plans?: RentPlan[];
  /** false = サイト掲載終了（価格等は最終取得時点の参考値） */
  is_active?: boolean;
  detail_scraped_at?: string | null;
  last_seen_at?: string | null;
}

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

export interface MapFilters {
  maxPrice: number;
  areaRange: [number, number];
  layout: string;
  status: ShortlistStatusFilter;
  listingVisibility: ListingVisibilityFilter;
  searchQuery: string;
  boundsEnabled: boolean;
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
  boundsEnabled: false,
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

export interface PropertyFeature {
  type: 'Feature';
  geometry: {
    type: 'Point';
    coordinates: [number, number]; // [lng, lat]
  };
  properties: PropertyProperties;
}

export interface PropertyGeoJSON {
  type: 'FeatureCollection';
  features: PropertyFeature[];
}

export interface BoundsData {
  southWest: [number, number]; // [lat, lng]
  northEast: [number, number]; // [lat, lng]
}

export interface TransferBucket {
  requests: number;
  bytes_downloaded: number;
  bytes_uploaded: number;
  bytes_downloaded_mb: number;
  bytes_uploaded_mb: number;
  direct_requests: number;
  proxy_requests: number;
  restricted_hits: number;
  errors: number;
}

export interface TransferSnapshot {
  lifetime: {
    by_source: Record<string, TransferBucket>;
    total: TransferBucket;
  };
  session?: {
    by_source: Record<string, TransferBucket>;
    total: TransferBucket;
  };
  session_label?: string | null;
  session_started_at?: number | null;
}

/** 1スクレイプrunのサマリ(GET /api/admin/status recent_runs — DB由来で再起動後も残る) */
export interface ScrapeRunSummary {
  id: number;
  source_site: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  list_pages: number | null;
  list_items: number | null;
  detail_ok: number | null;
  detail_fail: number | null;
  error_summary: string | null;
}

export interface AdminStats {
  task_status: {
    status: 'idle' | 'running';
    current_task: string | null;
    last_run: string | null;
    error: string | null;
    /** 直前タスクの結果: ok / partial / error(未実行時 null) */
    last_result?: 'ok' | 'partial' | 'error' | null;
    logs: string[];
    last_transfer?: TransferSnapshot | null;
  };
  data_layer?: 'v1' | 'v2';
  recent_runs?: ScrapeRunSummary[];
  http?: {
    mode: string;
    proxy_enabled: boolean;
  };
  transfer?: TransferSnapshot | null;
  db_stats: {
    total_properties: number;
    missing_coordinates: number;
    shortlist: {
      saved?: number;
      hide?: number;
      reject?: number;
    };
    by_source?: Record<string, number>;
  };
}

/** Per-prefecture (ListTarget) status under a source — GET /api/admin/sources */
export interface AdminTargetInfo {
  key: string;
  slug: string;
  name: string;
  counts: {
    total: number;
    active: number;
    missing_coords: number;
  };
  last_seen_at?: string | null;
  last_detail_scraped_at?: string | null;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_run_list_items?: number | null;
  last_run_detail_ok?: number | null;
  has_data: boolean;
}

/** GET /api/admin/sources */
export interface AdminSourceInfo {
  id: string;
  display_name: string;
  description?: string;
  enabled: boolean;
  registered: boolean;
  available: boolean;
  prefectures: string[];
  /** Crawl targets (usually prefectures) with DB + run status */
  targets?: AdminTargetInfo[];
  default_pages?: number | null;
  default_all_pages?: boolean;
  supports_all_pages?: boolean;
  default_mark_inactive?: boolean;
  counts: {
    total: number;
    active: number;
    missing_coords: number;
  };
}

export interface AdminSourcesResponse {
  data_layer: 'v1' | 'v2';
  sources: AdminSourceInfo[];
}

/** 次回実行バッチのプレビュー — GET /api/admin/rotation */
export interface RotationBatchPreview {
  /** 対象県スラッグ（実行順） */
  prefs: string[];
  /** 予想取得件数 */
  est_items: number;
  /** 単独県なので 1 県あたりの予算上限を無視する */
  unlimited: boolean;
  /** バッチ内容の理由コード（空文字 = 通常バッチ） */
  reason: string;
}

/** 県（ListTarget）ごとのローテーション状態 — GET /api/admin/rotation */
export interface RotationPrefStatus {
  slug: string;
  name: string;
  /** 既知物件数（未計測は null） */
  known_total: number | null;
  /** 前回フル取得成功時刻（未取得は null） */
  last_full_ok_at: string | null;
  last_run_at: string | null;
  /** 連続スクレイプ失敗数（成功で 0 にリセット。旧 API では欠損） */
  consecutive_failures?: number | null;
  /** 連続失敗によりクールダウン中でローテーション選定から一時除外されているか */
  suppressed?: boolean | null;
  /** 現在スクレイプ実行中か（旧 API では欠損） */
  is_running?: boolean | null;
  /** 次回バッチの順番（昇順で実行） */
  queue_position: number;
}

/** ソースごとの県ローテーション状態 — GET /api/admin/rotation */
export interface RotationSourceStatus {
  id: string;
  display_name: string;
  /** cron 式（実行時刻） */
  cron: string;
  daily_limit: number;
  used_today: number;
  /** 1 県あたりの既定取得件数（予算計算用） */
  default_est: number;
  next_batch: RotationBatchPreview;
  prefs: RotationPrefStatus[];
}

/** GET /api/admin/rotation */
export interface RotationStatusResponse {
  sources: RotationSourceStatus[];
}
