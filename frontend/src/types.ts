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

/** 物件画像 1 行({image_url, image_type, sort_order}・建物 units の images 要素と共用) */
export type PropertyImageInfoLike = Schemas['PropertyImageInfo'];

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

/** GET /api/admin/status(lib/api/admin.ts の公開名 AdminStatsResponse の正本) */
export type AdminStatsResponse = Schemas['AdminStatsResponse'];

/** AdminStatsResponse の旧別名。コンポーネント側 (admin/*) で使用 */
export type AdminStats = AdminStatsResponse;

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
// GeoJSON(部屋平面リスト・FE 所有の型)
// ============================================================

/**
 * 部屋 1 件の表示用ビュー(RoomRow / 詳細パネル / 比較 / Worker が消費する正本型)。
 *
 * BuildingUnit(建物 units の生 shape)を基底にした**上位集合型**で、
 * 表示に最適化した 3 フィールド(images / access_summary / station_summary)と
 * 必須性の保証(shortlist_status)だけを上書きする。
 *
 * 手書きの写像(旧 PropertyProperties)は BE の列追加が FE へ届かない事故
 * (階数・向きが units から落ちていた)を招いたため、基底型 + 上書きへ変更した
 * (docs/fe-floor-orientation-redesign-plan.md §7.1 / D8)。
 * 供給元は lib/building.ts normalizeUnit(建物 units の正規化)のみ。
 */
export interface RoomView
  extends Omit<BuildingUnit, 'images' | 'access_summary' | 'shortlist_status'> {
  /** 表示用の画像 URL 配列(sort_order 昇順。BE は行 dict {image_url, image_type, sort_order}) */
  images: string[];
  /** カンマ区切りのアクセス要約(BE は行リスト) */
  access_summary: string;
  /** カンマ区切りの駅名要約(units は持たないため建物 properties から継承) */
  station_summary: string;
  /** ショートリスト状態(normalizeUnit が 'none' を保証) */
  shortlist_status: ShortlistStatus;
}

/**
 * 旧名(互換エイリアス)。30+ ファイルの一括 rename を分離するため残置し、
 * 新規コードは RoomView を使う(docs/fe-floor-orientation-redesign-plan.md §7.1)。
 */
export type PropertyProperties = RoomView;

/** GeoJSON Feature 1 件 (Point)。geometry は建物 Feature と同じ生成型 GeoJSONPoint([lng, lat]) */
export interface PropertyFeature {
  type: 'Feature';
  geometry: Schemas['GeoJSONPoint'];
  properties: RoomView;
}

/** 建物 units の正規化結果を組み立てる FeatureCollection(collectPrefectures 等の FE 内部契約) */
export interface PropertyGeoJSON {
  type: 'FeatureCollection';
  features: PropertyFeature[];
}

// ============================================================
// 建物単位集約(Phase B2 — docs/building-aggregation-b2-fe-plan.md)
// ============================================================

/** GET /api/buildings/geojson の Feature properties(1 建物分・生成型そのまま) */
export type BuildingProperties = Schemas['BuildingProperties'];

/**
 * 建物 Feature の units 要素 = 部屋 1 件(生成型)。search 結果 dict を原生で
 * 搭載するため、PropertyProperties とはキー構成が非対称(images は行 dict・
 * access_summary は行リスト)。lib/building.ts normalizeUnit で変換する。
 */
export type BuildingUnitProperties = Schemas['BuildingUnitProperties'];

/**
 * units 要素の FE 内部型。Worker 計算値(stay_estimate)と詳細 API 由来の
 * 遅延フィールドを FE 派生として交差追加(PropertyProperties と同じ形式)。
 */
export type BuildingUnit = BuildingUnitProperties & {
  /** stay モードのフィルタ結果に付与(Worker 内で計算。永続フィールドではない) */
  stay_estimate?: StayEstimateSummary | null;
  /** Shortlist memo (from detail API; patchFeatureProperties で units へ書き戻す) */
  shortlist_comment?: string | null;
  /** Lazy-fetched from GET /api/properties/{id} */
  price_history?: PriceHistoryPoint[];
};

/** 建物 GeoJSON Feature(FE 内部契約の units 型へ置換) */
export type BuildingFeature = Omit<Schemas['BuildingFeature'], 'properties'> & {
  properties: Omit<BuildingProperties, 'units'> & { units: BuildingUnit[] };
};

/** GET /api/buildings/geojson(+stream)の FeatureCollection 応答 */
export type BuildingGeoJSON = Omit<Schemas['BuildingGeoJSON'], 'features'> & {
  features: BuildingFeature[];
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

/** ショートリスト状態の正本値リスト(zod z.enum 等から参照)。表示ラベル正本は lib/shortlist.ts */
export const SHORTLIST_STATUS_VALUES = ['saved', 'hide', 'reject', 'none'] as const;
export type ShortlistStatus = (typeof SHORTLIST_STATUS_VALUES)[number];

/** ショートリスト状態フィルタの正本値リスト(zod z.enum 等から参照) */
export const SHORTLIST_STATUS_FILTER_VALUES = [
  'all',
  'saved',
  'unsaved',
  'hide',
  'reject',
] as const;
export type ShortlistStatusFilter = (typeof SHORTLIST_STATUS_FILTER_VALUES)[number];

/**
 * 並び替えキーの正本値リスト(zod z.enum 等から参照)。
 * updated_desc = ショートリストの最終編集順(新しい順・saved 表示時の既定)。
 */
export const SORT_KEY_VALUES = [
  'score',
  'price_asc',
  'price_desc',
  'area_desc',
  'updated_desc',
] as const;
export type SortKey = (typeof SORT_KEY_VALUES)[number];

/** 掲載状態フィルタ（全て / 掲載中 / 非掲載）。既定は掲載中 */
export type ListingVisibilityFilter = 'all' | 'active' | 'inactive';

/** 価格モードの正本値リスト(zod z.enum 等から参照)。catalog = カタログ最安 / stay = 指定期間の試算総額 */
export const PRICE_MODE_VALUES = ['catalog', 'stay'] as const;
export type PriceMode = (typeof PRICE_MODE_VALUES)[number];

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

/** 範囲絞り込みモードの正本値リスト(zod z.enum 等から参照): 全件 / 地図表示範囲 / 囲った範囲 */
export const AREA_MODE_VALUES = ['all', 'viewport', 'drawn'] as const;
export type AreaMode = (typeof AREA_MODE_VALUES)[number];

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

/** 面積フィルタの既定範囲(㎡)。reset時フォールバック・詳細フィルタ活性判定の正本 */
export const DEFAULT_AREA_RANGE: [number, number] = [10, 50];

/**
 * MapFilters のうち実行時コンテキストに依存しない静的既定値。
 * 動的5項(checkIn / checkOut / sortBy / maxPrice / priceMode)は
 * createDefaultMapFilters()(lib/filterLogic.ts)が defaultDateRange() や
 * 価格センチネル・既定ソートで常に上書きするため、ここでは保持しない。
 * MapFilters のフル既定は必ず createDefaultMapFilters() 経由で取得すること。
 */
export const DEFAULT_STATIC_FILTERS: Omit<
  MapFilters,
  'checkIn' | 'checkOut' | 'sortBy' | 'maxPrice' | 'priceMode'
> = {
  areaRange: DEFAULT_AREA_RANGE,
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
};

/**
 * 差別化設備トグル。value は BE 機能カテゴリ辞書の code(wire 語彙・決定 14)。
 * 判定は feature_categories 配列への集合包含(表記ゆれの影響を受けない)。
 * 同期契約: value ⊆ 辞書の feature 単位 code(単純/複合/親 — tests/test_api_contract_sync.py)。
 * label は UI コピー(FE 管轄・辞書 label に縛られない)。
 */
export interface FeatureToggleOption {
  value: string;
  label: string;
}

export const FEATURE_TOGGLE_OPTIONS: readonly FeatureToggleOption[] = [
  { value: 'auto_lock', label: 'オートロック' },
  { value: 'elevator', label: 'エレベーター' },
  { value: 'delivery_box', label: '宅配ボックス' },
  { value: 'internet.fee_free', label: 'インターネット無料' },
  { value: 'bicycle_parking.fee_free', label: '駐輪場(無料)' },
  { value: 'bicycle_parking.fee_paid', label: '駐輪場(有料)' },
  { value: 'bicycle_parking', label: '駐輪場あり' },
  { value: 'parking.fee_free', label: '駐車場(無料)' },
  { value: 'parking', label: '駐車場あり' },
  { value: 'motorcycle_parking.fee_free', label: 'バイク置き場(無料)' },
  { value: 'motorcycle_parking', label: 'バイク置き場あり' },
  { value: 'separate_bath_toilet', label: 'バストイレ別' },
  { value: 'bathroom_dryer', label: '浴室乾燥機' },
  { value: 'independent_washstand', label: '独立洗面台' },
  { value: 'washlet', label: 'ウォシュレット' },
  { value: 'flooring', label: 'フローリング' },
  { value: 'loft', label: 'ロフト' },
  { value: 'dressing_area', label: '脱衣所' },
  { value: 'gas_stove', label: 'ガスコンロ' },
  { value: 'ih_stove', label: 'IHコンロ' },
  { value: 'electric_stove', label: '電気コンロ' },
  { value: 'chair', label: '椅子' },
  { value: 'sofa', label: 'ソファー' },
  { value: 'mirror', label: '姿見鏡' },
  { value: 'rug', label: 'ラグマット' },
  { value: 'ashtray', label: '灰皿' },
  { value: 'bluetooth_speaker', label: 'Bluetoothスピーカー' },
  { value: 'foreigner_friendly', label: '外国人可' },
  { value: 'no_smoking', label: '禁煙' },
  { value: 'corner_room', label: '角部屋' },
  { value: 'pets_allowed', label: 'ペット可' },
  { value: 'female_oriented', label: '女性向け' },
  { value: 'top_floor', label: '最上階' },
  { value: 'relatively_new', label: '築浅' },
  { value: 'near_convenience_store', label: 'コンビニ至近' },
  { value: 'near_supermarket', label: 'スーパー至近' },
];

export interface BoundsData {
  southWest: [number, number]; // [lat, lng]
  northEast: [number, number]; // [lat, lng]
}
