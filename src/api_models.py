"""API 応答の契約正本 (pydantic v2 モデル).

このモジュールが OpenAPI (/openapi.json) の components.schemas の正本となり、
FE の型は openapi-typescript による自動生成に置き換わる。レスポンスキーの
追加・変更は必ずこのモジュール経由で行う。

設計方針:
- nullable な DB 列 / 条件付きでしか付与されないキーは Optional で表現する
- 同義キー (plan_key/plan_code, plan_name/duration_text 等) は現状維持のため
  残す。削除は FE 側の手書き型整理と同時に行う
- effective_* 系フィールドは「基準日 = as-of-today (今日)」で解決した値。
  滞在期間 (check-in/check-out) での試算は別契約であり、FE の client-side
  worker (rentCalculator) が担うため BE は滞在試算値を返さない
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# 物件共通: 料金プラン / キャンペーン
# ============================================================


class RentPlan(BaseModel):
    """物件の料金プラン 1 件。

    金額の原単位は presentation_unit (per_day / per_month 等)。
    ``*_daily_rent_yen`` は日額換算 (整数・切捨て)、
    ``*_total_yen`` は 30 日換算の概算総額 (日額 + 共益費日額) x 30。

    ``effective_*`` 系 (effective_rent_yen / effective_daily_rent_yen /
    effective_total_yen / effective_campaign_label) は **基準日 =
    as-of-today (今日) でキャンペーンを解決した値**。有効キャンペーンが
    あれば割引後、無ければ通常価格 (rent_current_yen → rent_original_yen)
    にフォールバックする。滞在期間 (check-in/check-out) を基準にした試算は
    この契約には含まれず、FE 側の rentCalculator が別途計算する。
    """

    plan_key: Optional[str] = Field(None, description="プランキー (property_id 内で一意)")
    plan_code: Optional[str] = Field(
        None, description="plan_key のエイリアス (FE/legacy 同義キー。現状維持)"
    )
    plan_name: Optional[str] = Field(None, description="プラン名")
    duration_text: Optional[str] = Field(
        None, description="plan_name のエイリアス (legacy 同義キー。現状維持)"
    )
    duration_min_days: Optional[int] = Field(None, description="最短滞在日数")
    duration_max_days: Optional[int] = Field(None, description="最長滞在日数 (無期限は null)")
    available: bool = Field(True, description="取扱ありフラグ")
    campaign_label: Optional[str] = Field(None, description="プラン行に付記されたキャンペーンラベル")
    presentation_unit: str = Field("per_day", description="金額の原単位 (per_day / per_month)")
    rent_original_yen: Optional[int] = Field(None, description="定価 (presentation_unit 原単位)")
    rent_current_yen: Optional[int] = Field(None, description="現行価格 (同上)")
    management_yen: Optional[int] = Field(None, description="共益費 (同上)")
    utilities_yen: Optional[int] = Field(None, description="水光熱費 (同上)")
    utilities_included: bool = Field(True, description="水光熱費込みフラグ")
    cleaning_yen: Optional[int] = Field(None, description="清掃費 (同上)")
    original_daily_rent_yen: Optional[int] = Field(None, description="定価の日額換算")
    discounted_daily_rent_yen: Optional[int] = Field(None, description="現行価格の日額換算")
    management_fee_daily_yen: int = Field(0, description="共益費の日額換算 (無ければ 0)")
    cleaning_fee_yen: Optional[int] = Field(None, description="cleaning_yen のエイリアス")
    raw_text: Optional[str] = Field(None, description="抽出元の生テキスト")
    original_total_yen: Optional[int] = Field(None, description="定価の 30 日換算総額 ( rent+共益 )")
    discounted_total_yen: Optional[int] = Field(None, description="現行価格の 30 日換算総額")
    total_period_days: int = Field(30, description="総額換算の基準日数 (固定 30)")
    effective_rent_yen: Optional[int] = Field(
        None, description="as-of-today で解決した実効価格 (presentation_unit 原単位)"
    )
    effective_daily_rent_yen: Optional[int] = Field(
        None, description="as-of-today で解決した実効日額"
    )
    effective_total_yen: Optional[int] = Field(
        None, description="as-of-today の実効日額による 30 日換算総額 (日額未確定なら null)"
    )
    campaign_applied: bool = Field(False, description="as-of-today でキャンペーン割引が適用中か")
    campaign_expired: bool = Field(False, description="参照したキャンペーンが期限切れか")
    effective_campaign_label: Optional[str] = Field(
        None, description="as-of-today で有効なキャンペーンの表示ラベル"
    )
    expired_campaign_label: Optional[str] = Field(
        None, description="期限切れで参照されたキャンペーンの表示ラベル"
    )
    matched_campaign_type: Optional[str] = Field(
        None, description="適合したキャンペーン型 (discount / package 等)"
    )


class Campaign(BaseModel):
    """物件に紐づくキャンペーン 1 件 (campaigns テーブル行 + legacy エイリアス)。

    starts_on / ends_on は ISO 日付 (未記載は null)。ends_on が null の場合は
    期間未記載 (継続 or 不明) を示す。
    """

    id: Optional[int] = None
    property_id: Optional[int] = None
    campaign_type: Optional[str] = Field(None, description="キャンペーン型")
    title: Optional[str] = Field(None, description="見出し")
    content: Optional[str] = Field(None, description="本文")
    target_period_text: Optional[str] = Field(None, description="対象期間の生テキスト")
    target_condition_text: Optional[str] = Field(None, description="対象条件の生テキスト")
    starts_on: Optional[str] = Field(None, description="開始日 (YYYY-MM-DD)")
    ends_on: Optional[str] = Field(None, description="終了日 (YYYY-MM-DD). null=期間未記載")
    target_plan_key: Optional[str] = Field(None, description="対象プランキー (空=全プラン)")
    target_plan_code: Optional[str] = Field(
        None, description="target_plan_key のエイリアス (legacy 同義キー。現状維持)"
    )
    discount_unit: Optional[str] = Field(
        None, description="割引単位 (yen / percent / package / pokkiri 等)"
    )
    discount_value: Optional[int] = Field(None, description="割引量 (単位は discount_unit)")
    discount_max_yen: Optional[int] = Field(None, description="割引上限円")
    period_max_days: Optional[int] = Field(None, description="適用期間上限日数")
    stay_min_days: Optional[int] = Field(None, description="適用最少滞在日数")
    stay_max_days: Optional[int] = Field(None, description="適用最大滞在日数")
    contract_within_days: Optional[int] = Field(None, description="契約期限 (n 日以内)")
    package_rent_benefit_yen: Optional[int] = Field(None, description="パッケ 適用の家賃相当優待円")
    package_cleaning_benefit_yen: Optional[int] = Field(None, description="パッケ適用の清掃費優待円")
    package_fee_benefit_yen: Optional[int] = Field(None, description="パッケ適用の手数料優待円")
    package_total_benefit_yen: Optional[int] = Field(None, description="パッケ適用の優待合計円")
    structure_source: Optional[str] = Field(None, description="構造化の由来 (llm / mechanical 等)")
    parse_ok: Optional[int] = Field(None, description="構造化成功フラグ (0/1)")
    parse_warnings: Optional[str] = Field(None, description="構造化時の警告 (JSON)")
    raw_json: Optional[str] = Field(None, description="抽出元の生 JSON")
    scraped_at: Optional[str] = Field(None, description="取得日時")


# ============================================================
# 物件詳細 (GET /api/properties/{property_id})
# ============================================================


class PropertyAccessInfo(BaseModel):
    """アクセス 1 行 (交通)。"""

    line_name: Optional[str] = Field(None, description="路線名")
    station_name: Optional[str] = Field(None, description="駅名")
    walk_minutes: Optional[int] = Field(None, description="徒歩分数")
    raw_text: Optional[str] = Field(None, description="抽出元の生テキスト")


class PropertyImageInfo(BaseModel):
    """画像 1 枚。"""

    image_url: str
    image_type: Optional[str] = Field(None, description="thumbnail / gallery / other")
    alt_text: Optional[str] = None
    sort_order: Optional[int] = None


class PropertyLinkInfo(BaseModel):
    """関連リンク 1 件。"""

    link_type: str
    url: str
    label: Optional[str] = None


class PropertyFeatureInfo(BaseModel):
    """設備 1 件。"""

    feature_name: str
    feature_category: Optional[str] = Field(None, description="building / room 等の分類")


class ShortlistInfo(BaseModel):
    """ショートリスト状態 (未登録物件は null)。"""

    status: str = Field(..., description="saved / hide / reject")
    comment: Optional[str] = None
    updated_at: str


class PriceHistoryPoint(BaseModel):
    """価格履歴 1 点 (品質ガード適用後の割引日額)。"""

    scraped_at: str
    min_discounted_daily_rent_yen: int
    min_discounted_monthly_total_yen: Optional[int] = None


class PriceHistoryMeta(BaseModel):
    """価格履歴の品質ガード開示メタ (破損値除外件数)。"""

    total_count: int
    dropped_count: int
    first_at: Optional[str] = None
    last_at: Optional[str] = None


class PropertyDetailResponse(BaseModel):
    """GET /api/properties/{property_id} の応答。

    properties テーブル行 (SELECT * の全列) + 子テーブル (accesses / images /
    links / features / campaigns / rent_plans / shortlist / price_history)。
    """

    # ── properties 行の全列 ──
    id: int
    source_site: str
    external_id: str
    entity_type: str = "room"
    parent_property_id: Optional[int] = None
    title: Optional[str] = None
    detail_url: Optional[str] = None
    prefecture_slug: Optional[str] = None
    prefecture_name: Optional[str] = None
    municipality: Optional[str] = Field(None, description="市区町村 (相場比較のピア grouping 用)")
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_source: Optional[str] = None
    geocode_confidence: Optional[float] = None
    layout: Optional[str] = None
    area_m2: Optional[float] = None
    area_m2_max: Optional[float] = None
    built_year: Optional[int] = None
    built_month: Optional[int] = None
    construction_year_text: Optional[str] = None
    capacity_text: Optional[str] = None
    structure: Optional[str] = None
    floors_text: Optional[str] = None
    floor_number: Optional[str] = None
    point_text: Optional[str] = Field(None, description="物件紹介文 (POINT)")
    availability_text: Optional[str] = None
    min_stay_days: Optional[int] = None
    contract_fee_yen: Optional[int] = None
    first_seen_at: Optional[str] = Field(None, description="初回検知日時 (掲載日数の算出に使用)")
    last_seen_at: Optional[str] = Field(None, description="最終確認日時 (掲載終了時の参考値基準)")
    detail_scraped_at: Optional[str] = None
    is_active: bool = Field(True, description="false = サイト掲載終了 (価格等は最終取得時点の参考値)")
    catalog_rent_per_day_yen: Optional[int] = None
    catalog_total_hint_yen: Optional[int] = None
    total_score: Optional[float] = Field(
        None, description="総合スコア (スコアリング再活用予定のため維持)"
    )
    rent_score: Optional[float] = None
    walk_score: Optional[float] = None
    area_score: Optional[float] = None
    age_score: Optional[float] = None
    commute_score: Optional[float] = None

    # ── 派生 / 子テーブル ──
    source_property_id: Optional[str] = Field(None, description="external_id のエイリアス")
    source_display_name: str = Field("", description="ソースの表示名")
    accesses: List[PropertyAccessInfo] = []
    images: List[PropertyImageInfo] = []
    links: List[PropertyLinkInfo] = []
    features: List[PropertyFeatureInfo] = []
    campaigns: List[Campaign] = []
    rent_plans: List[RentPlan] = []
    shortlist: Optional[ShortlistInfo] = None
    price_history: List[PriceHistoryPoint] = []
    price_history_meta: Optional[PriceHistoryMeta] = None


# ============================================================
# GeoJSON (GET /api/geojson)
# ============================================================


class GeoJSONPoint(BaseModel):
    """Point ジオメトリ。coordinates は [lng, lat]。"""

    type: Literal["Point"]
    coordinates: List[float]


class PropertyProperties(BaseModel):
    """GeoJSON Feature の properties (検索結果 1 物件分)。

    一括 /api/geojson と /api/geojson/stream の feature 行で同一ペイロード。
    """

    id: int
    room_id: Optional[str] = Field(None, description="external_id のエイリアス (legacy)")
    source_site: Optional[str] = None
    source_display_name: Optional[str] = None
    title: Optional[str] = None
    detail_url: Optional[str] = None
    address: Optional[str] = None
    prefecture_name: Optional[str] = None
    municipality: Optional[str] = None
    layout: Optional[str] = None
    area_m2: Optional[float] = None
    min_daily_rent: Optional[int] = Field(None, description="最安実効日額 (as-of-today)")
    min_plan_total: Optional[int] = Field(None, description="最安プランの 30 日換算総額")
    min_plan_name: Optional[str] = None
    min_walk_minutes: Optional[int] = None
    thumbnail_url: Optional[str] = None
    images: List[str] = Field([], description="画像 URL のリスト")
    total_score: Optional[float] = Field(
        None, description="総合スコア (スコアリング再活用予定のため維持)"
    )
    shortlist_status: str = Field("none", description="saved / hide / reject / none")
    is_active: bool = Field(True, description="false = サイト掲載終了")
    last_seen_at: Optional[str] = None
    access_summary: str = Field("", description="カンマ区切りのアクセス要約")
    feature_summary: str = Field("", description="カンマ区切りの設備要約")
    station_summary: str = Field("", description="カンマ区切りの駅名要約")
    point_text: Optional[str] = None
    rent_plans: List[RentPlan] = []
    campaigns: List[Campaign] = []


class PropertyFeature(BaseModel):
    """GeoJSON Feature 1 件 (Point)。"""

    type: Literal["Feature"]
    geometry: GeoJSONPoint
    properties: PropertyProperties


class PropertyGeoJSON(BaseModel):
    """GET /api/geojson の FeatureCollection 応答。"""

    type: Literal["FeatureCollection"]
    features: List[PropertyFeature]


# ============================================================
# 価格変動推移 (GET /api/analysis/price-trend)
# ============================================================


class PriceTrendPoint(BaseModel):
    """価格変動の日次集計 1 点。"""

    date: str = Field(..., description="YYYY-MM-DD")
    median: int = Field(..., description="日額中央値 (円)")
    avg: int = Field(..., description="日額平均 (円)")
    count: int = Field(..., description="代表値が存在する物件数")
    down: int = Field(..., description="直前代表値比で値下げした物件数")
    up: int = Field(..., description="直前代表値比で値上げした物件数")


class PriceTrendSeriesSet(BaseModel):
    """1 モード分の系列 (全プロバイダ統合 + プロバイダ別)。"""

    all: List[PriceTrendPoint]
    by_site: Dict[str, List[PriceTrendPoint]] = Field(
        {}, description="キー=source_site id"
    )


class PriceTrendSeries(BaseModel):
    """carried=前進補完推計 / scraped=当日取得分。"""

    carried: PriceTrendSeriesSet
    scraped: PriceTrendSeriesSet


class PriceTrendProvider(BaseModel):
    id: str
    display_name: str


class PriceTrendMeta(BaseModel):
    """品質ガードの適用状況。"""

    snapshot_rows: int
    guarded_rows: int
    excluded_rows: int


class PriceTrendResponse(BaseModel):
    """GET /api/analysis/price-trend の応答 (全プロバイダ分を一括返却)。"""

    days: int = Field(..., description="集計期間 (日数)")
    carried_window_days: int = Field(..., description="前進補完で既知値とみなす窓 (日数)")
    generated_at: str
    providers: List[PriceTrendProvider]
    series: PriceTrendSeries
    meta: PriceTrendMeta


# ============================================================
# ショートリスト更新 (POST /api/properties/{property_id}/shortlist)
# ============================================================


class ShortlistUpdateResponse(BaseModel):
    status: Literal["success"]
    property_id: Optional[int] = None
    shortlist_status: str


# ============================================================
# チャットスレッド (GET/DELETE /api/chat/threads*)
# ============================================================


class ChatThreadSummary(BaseModel):
    """チャットセッション 1 件 (チェックポイント DB 由来)。"""

    id: str
    checkpointCount: int
    title: str
    preview: str
    updatedAt: Optional[str] = None
    messageCount: int


class ChatThreadsResponse(BaseModel):
    threads: List[ChatThreadSummary]


class ChatThreadMessage(BaseModel):
    """AG-UI 向けに正規化したメッセージ 1 件。"""

    id: str
    role: str = Field(..., description="user / assistant")
    content: str


class ChatThreadMessagesResponse(BaseModel):
    threadId: str
    messages: List[ChatThreadMessage]


class ChatThreadDeleteResponse(BaseModel):
    status: str = Field(..., description="success / error")
    thread_id: str
    message: Optional[str] = Field(None, description="error 時の詳細")


# ============================================================
# 管理 API
# ============================================================


class HealthResponse(BaseModel):
    """GET /api/copilotkit/health。"""

    status: Literal["ok"]


class TransferBucket(BaseModel):
    """ソース別転送統計 1 バケット。"""

    requests: int
    bytes_downloaded: int
    bytes_uploaded: int
    bytes_downloaded_mb: float
    bytes_uploaded_mb: float
    direct_requests: int
    proxy_requests: int
    restricted_hits: int
    errors: int


class TransferPack(BaseModel):
    by_source: Dict[str, TransferBucket] = {}
    total: TransferBucket


class TransferSnapshot(BaseModel):
    """スクレイプ HTTP 転送メトリクスのスナップショット。"""

    lifetime: TransferPack
    session: Optional[TransferPack] = None
    session_label: Optional[str] = None
    session_started_at: Optional[float] = None


class TaskStatus(BaseModel):
    """バックグラウンドタスクの実行状態 (プロセス内・再起動で消える)。"""

    status: Literal["idle", "running"]
    current_task: Optional[str] = None
    last_run: Optional[str] = None
    error: Optional[str] = None
    last_result: Optional[Literal["ok", "partial", "error"]] = Field(
        None, description="直前タスクの結果 (未実行は null)"
    )
    logs: List[str] = []
    last_transfer: Optional[TransferSnapshot] = None


class ScrapeRunSummary(BaseModel):
    """スクレイプ run 1 件のサマリ (DB 由来・再起動後も残る)。"""

    id: int
    source_site: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: str
    list_pages: Optional[int] = None
    list_items: Optional[int] = None
    detail_ok: Optional[int] = None
    detail_fail: Optional[int] = None
    error_summary: Optional[str] = None


class AdminHttpInfo(BaseModel):
    mode: str
    proxy_enabled: bool


class AdminDbStats(BaseModel):
    total_properties: int
    missing_coordinates: int
    shortlist: Dict[str, int] = Field({}, description="状態→件数マップ")
    by_source: Dict[str, int] = Field({}, description="source_site→件数マップ")


class AdminStatsResponse(BaseModel):
    """GET /api/admin/status の応答。"""

    task_status: TaskStatus
    recent_runs: List[ScrapeRunSummary] = []
    http: AdminHttpInfo
    transfer: Optional[TransferSnapshot] = None
    db_stats: AdminDbStats


class AdminTargetCounts(BaseModel):
    total: int
    active: int
    missing_coords: int


class AdminTargetInfo(BaseModel):
    """ソース配下のクロール対象 (通常は県) 1 件。"""

    key: str
    slug: str
    name: str
    counts: AdminTargetCounts
    last_seen_at: Optional[str] = None
    last_detail_scraped_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_list_items: Optional[int] = None
    last_run_detail_ok: Optional[int] = None
    has_data: bool


class AdminSourceInfo(BaseModel):
    """GET /api/admin/sources の sources 要素 1 件。"""

    id: str
    display_name: str
    description: Optional[str] = None
    enabled: bool
    registered: bool
    available: bool
    prefectures: List[str] = []
    targets: List[AdminTargetInfo] = []
    default_pages: Optional[int] = None
    default_all_pages: Optional[bool] = None
    supports_all_pages: Optional[bool] = None
    default_mark_inactive: Optional[bool] = None
    counts: AdminTargetCounts


class AdminSourcesResponse(BaseModel):
    sources: List[AdminSourceInfo]


class RotationBatchPreview(BaseModel):
    """次回実行バッチのプレビュー。"""

    prefs: List[str] = Field([], description="対象県スラッグ (実行順)")
    est_items: int = Field(0, description="予想取得件数")
    unlimited: bool = Field(False, description="1 県あたり予算上限を無視する単独県バッチか")
    reason: str = Field("", description="バッチ内容の理由コード (空文字=通常バッチ)")


class RotationPrefStatus(BaseModel):
    """県ごとのローテーション状態。"""

    slug: str
    name: str
    known_total: Optional[int] = Field(None, description="既知物件数 (未計測は null)")
    last_full_ok_at: Optional[str] = Field(None, description="前回フル取得成功時刻")
    last_run_at: Optional[str] = None
    consecutive_failures: int = Field(0, description="連続スクレイプ失敗数")
    suppressed: bool = Field(False, description="連続失敗によるクールダウン中か")
    is_running: bool = Field(False, description="現在スクレイプ実行中か")
    queue_position: int = Field(..., description="次回バッチの順番 (昇順で実行)")


class RotationSourceStatus(BaseModel):
    """ソースごとの県ローテーション状態。"""

    id: str
    display_name: str
    cron: str = Field(..., description="cron 式 (実行時刻)")
    daily_limit: int = Field(..., description="1 日あたり取得上限の実効値")
    used_today: int
    default_est: int = Field(..., description="1 県あたりの既定取得件数の実効値")
    next_batch: RotationBatchPreview
    prefs: List[RotationPrefStatus]


class RotationStatusResponse(BaseModel):
    """GET /api/admin/rotation の応答。"""

    sources: List[RotationSourceStatus]


# ============================================================
# 設定系 API (GET/POST /api/fe-settings, /api/admin/scrape-settings,
#             /api/admin/rotation-settings)
# ============================================================
#
# POST ボディは意図的に pydantic 化していない (update: dict)。部分マージ +
# null = 保存済みキーの削除 (既定へ戻す) という契約を保持するためで、
# バリデーションは各設定モジュール (JsonSettingsStore) が行い、違反は
# web_server が HTTPException(400) に変換する。


class ScrapeSettingsDefaults(BaseModel):
    """スクレイプ設定のコード既定値。"""

    delay_seconds: float = Field(..., description="リクエスト間隔の既定値 (秒)")
    cooldown_seconds: float = Field(..., description="制限検知時クールダウンの既定値 (秒)")


class ScrapeSourceSettings(BaseModel):
    """ソース 1 件分のスクレイプ設定 (実効値 or 保存値)。

    GET (実効値一覧) では delay/cooldown は常に値入り。POST (部分マージ後の
    保存値) では保存済みキーのみ値入りで、未保存キーは null になる。
    """

    delay_seconds: Optional[float] = Field(
        None,
        description="リクエスト間隔 (秒)。実効値 = 保存値 > config.json > コード既定",
    )
    cooldown_seconds: Optional[float] = Field(
        None, description="制限検知時クールダウン (秒)。実効値の優先順位は delay_seconds と同一"
    )
    saved: Optional[Dict[str, Any]] = Field(
        None,
        description="DB 保存済みの上書き (未保存キーは欠損)。POST 応答 (保存値のみ) では null",
    )


class ScrapeSettingsResponse(BaseModel):
    """GET /api/admin/scrape-settings の応答 (ソース別実効値一覧)。

    POST /api/admin/scrape-settings は部分マージ後の「保存値」全体を返す
    現行契約のため、defaults と個別ソースの未保存キー / saved は null になる。
    """

    defaults: Optional[ScrapeSettingsDefaults] = None
    sources: Dict[str, ScrapeSourceSettings] = Field(
        {}, description="キー = SOURCE_CATALOG 由来の source id"
    )


class RotationSettingsDefaults(BaseModel):
    """ローテーション設定のコード既定値。"""

    daily_limit: int = Field(..., description="1 日あたり取得上限の既定値 (件)")
    default_est: int = Field(..., description="known_total 未計測県の予算見積り既定値 (件)")


class RotationSourceSettings(BaseModel):
    """ソース 1 件分のローテーション設定 (実効値 or 保存値)。

    GET (実効値一覧) では daily_limit / default_est は常に値入り。POST (部分
    マージ後の保存値) では保存済みキーのみ値入りで、未保存キーは null になる。
    """

    daily_limit: Optional[int] = Field(
        None, description="1 日あたり取得上限 (件)。実効値 = 保存値 > コード既定"
    )
    default_est: Optional[int] = Field(
        None, description="known_total 未計測県の予算見積り件数 (件)。実効値の優先順位は daily_limit と同一"
    )
    saved: Optional[Dict[str, Any]] = Field(
        None,
        description="DB 保存済みの上書き (未保存キーは欠損)。POST 応答 (保存値のみ) では null",
    )


class RotationSettingsResponse(BaseModel):
    """GET /api/admin/rotation-settings の応答 (ソース別実効値一覧)。

    POST /api/admin/rotation-settings は部分マージ後の「保存値」全体を返す
    現行契約のため、defaults と個別ソースの未保存キー / saved は null になる。
    """

    defaults: Optional[RotationSettingsDefaults] = None
    sources: Dict[str, RotationSourceSettings] = Field(
        {}, description="キー = SOURCE_CATALOG 由来の source id"
    )


class FeLayerOverrides(BaseModel):
    """レイヤ 1 件分の保存済みデフォルト上書き (未指定キーはカタログ既定へフォールバック)。"""

    defaultOpacity: Optional[float] = Field(
        None, description="レイヤ追加時のデフォルト透明度 (0-1)"
    )
    clustering: Optional[bool] = Field(
        None, description="クラスタリング対応レイヤ (oshima) のクラスタ表示"
    )


class FeGlobalSettings(BaseModel):
    """アプリ全体の表示設定。"""

    pinClustering: Optional[bool] = Field(
        None, description="物件ピンのクラスタリング (未指定/null = true)"
    )


class FeSettingsResponse(BaseModel):
    """GET/POST /api/fe-settings の応答 (フロントエンド既定値設定)。

    契約型は frontend/src/lib/feSettings.ts の FeSettings と整合する。
    layers は layerId → 上書きの自由 dict。POST は部分マージ後の全体を返す。
    """

    model_config = ConfigDict(populate_by_name=True)

    layers: Dict[str, FeLayerOverrides] = {}
    global_: FeGlobalSettings = Field(
        default_factory=FeGlobalSettings,
        alias="global",
        description="アプリ全体の表示設定 (global は Python 予約語のため属性名は global_)",
    )


# ============================================================
# バックグラウンドタスク起動応答 (共通)
# ============================================================


class TaskStartResponse(BaseModel):
    """バックグラウンドタスク起動の共通応答。"""

    status: Literal["started"]
    task: str


class ScrapeStartResponse(TaskStartResponse):
    """POST /api/admin/scrape の起動応答。"""

    sources: List[str] = Field([], description="解決後の source id 群")
    prefs: Optional[List[str]] = None
    all_pages: bool = False
    pages: Optional[int] = None
    mark_inactive: bool = True


class RotationRunStartResponse(TaskStartResponse):
    """POST /api/admin/rotation/run の起動応答。"""

    source: str
