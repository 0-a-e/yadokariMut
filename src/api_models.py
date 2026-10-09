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

import datetime as dt
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from domain.models import PresentationUnit
from domain.pricing import MONTH_DAYS

# ============================================================
# ショートリスト状態語彙 (H5-BE)
# FE 正本: frontend/src/types.ts SHORTLIST_STATUS_VALUES と同期テストで保証
# (tests/test_api_contract_sync.py)
# ============================================================
ShortlistStatus = Literal["saved", "hide", "reject", "none"]

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
    plan_label: str = Field(
        "",
        description=(
            "表示ラベル (BE 辞書解決・正本: domain.plan_catalog)。"
            "帯レンジを含まない名称のみ。未知コードは plan_name (生値) フォールバック"
        ),
    )
    duration_min_days: Optional[int] = Field(None, description="最短滞在日数")
    duration_max_days: Optional[int] = Field(None, description="最長滞在日数 (無期限は null)")
    available: bool = Field(True, description="取扱ありフラグ")
    campaign_label: Optional[str] = Field(None, description="プラン行に付記されたキャンペーンラベル")
    # 語彙正本: domain.models.PresentationUnit (Literal・決定 11)。openapi 生成型は enum 化
    presentation_unit: PresentationUnit = Field("per_day", description="金額の原単位 (per_day / per_month)")
    rent_original_yen: Optional[int] = Field(None, description="定価 (presentation_unit 原単位)")
    rent_current_yen: Optional[int] = Field(None, description="現行価格 (同上)")
    management_yen: Optional[int] = Field(None, description="共益費 (同上)")
    utilities_yen: Optional[int] = Field(None, description="水光熱費 (同上)")
    utilities_included: bool = Field(True, description="水光熱費込みフラグ")
    cleaning_yen: Optional[int] = Field(None, description="清掃費 (同上)")
    original_daily_rent_yen: Optional[int] = Field(None, description="定価の日額換算")
    discounted_daily_rent_yen: Optional[int] = Field(None, description="現行価格の日額換算")
    # 決定 11: 共益費未記載・単位未知など換算不能は 0 円へ畳み込まず null を透過
    # (FE は CalculatorPlan 経由で ?? 0 フォールバックを持つため契約変更は安全)
    management_fee_daily_yen: Optional[int] = Field(
        None, description="共益費の日額換算 (換算不能なら null — 決定 11)"
    )
    cleaning_fee_yen: Optional[int] = Field(None, description="cleaning_yen のエイリアス")
    raw_text: Optional[str] = Field(None, description="抽出元の生テキスト")
    original_total_yen: Optional[int] = Field(None, description="定価の 30 日換算総額 ( rent+共益 )")
    discounted_total_yen: Optional[int] = Field(None, description="現行価格の 30 日換算総額")
    total_period_days: int = Field(
        MONTH_DAYS, description="総額換算の基準日数 (固定 30。正本: domain.pricing.MONTH_DAYS)"
    )
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
    starts_on: Optional[dt.date] = Field(None, description="開始日 (YYYY-MM-DD)")
    ends_on: Optional[dt.date] = Field(None, description="終了日 (YYYY-MM-DD). null=期間未記載")
    target_plan_key: Optional[str] = Field(None, description="対象プランキー (空=全プラン)")
    target_plan_code: Optional[str] = Field(
        None, description="target_plan_key のエイリアス (legacy 同義キー。現状維持)"
    )
    target_plan_label: str = Field(
        "",
        description=(
            "対象プランの表示ラベル (BE 辞書解決・正本: domain.plan_catalog)。"
            "all / 空 = すべてのプラン。未知コードは生値"
        ),
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
    parse_ok: Optional[bool] = Field(None, description="構造化成功フラグ")
    parse_warnings: Optional[str] = Field(None, description="構造化時の警告 (JSON)")
    raw_json: Optional[dict] = Field(None, description="抽出元の生 JSON (jsonb)")
    scraped_at: Optional[dt.datetime] = Field(None, description="取得日時")


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
    """画像 1 枚。

    media_id は rustfs クラスタ代表ストアの格納済みメディアID
    (docs/media-storage-rustfs-plan.md §2.8)。未取得・機能無効時は null で、
    その場合は従来どおり image_url(元サイトURL)を直接参照する。
    """

    image_url: str
    image_type: Optional[str] = Field(None, description="thumbnail / gallery / other")
    alt_text: Optional[str] = None
    sort_order: Optional[int] = None
    media_id: Optional[int] = Field(
        None, description="保存メディアのID (GET /api/media/{media_id})"
    )
    dhash: Optional[str] = Field(
        None, description="知覚ハッシュ 16進16桁 (クラスタ代表・近重複判定用)"
    )
    has_thumb: Optional[bool] = Field(
        None, description="640px WebP サムネイルの有無 (?variant=thumb が有効)"
    )


class PropertyLinkInfo(BaseModel):
    """関連リンク 1 件。"""

    link_type: str
    url: str
    label: Optional[str] = None


class PropertyFeatureInfo(BaseModel):
    """設備 1 件。"""

    feature_name: str


class ShortlistInfo(BaseModel):
    """ショートリスト状態 (未登録物件は null)。"""

    status: str = Field(..., description="saved / hide / reject")
    comment: Optional[str] = None
    updated_at: dt.datetime


class PriceHistoryPoint(BaseModel):
    """価格履歴 1 点 (品質ガード適用後の割引日額)。"""

    scraped_at: dt.datetime
    min_discounted_daily_rent_yen: int
    min_discounted_monthly_total_yen: Optional[int] = None


class PriceHistoryMeta(BaseModel):
    """価格履歴の品質ガード開示メタ (破損値除外件数)。"""

    total_count: int
    dropped_count: int
    first_at: Optional[dt.datetime] = None
    last_at: Optional[dt.datetime] = None


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
    floors_text: Optional[str] = Field(
        None, description="階数まわりの原文キャッシュ (bratto=階建セル / unionmonthly=所在階セル)"
    )
    floor_number: Optional[int] = Field(None, description="所在階 (min・地下は負数)")
    floor_number_max: Optional[int] = Field(
        None, description="所在階 (max・複数階「1・2階」のみ min と異なる)"
    )
    building_floors: Optional[int] = Field(None, description="建物階数 (bratto のみ取得可)")
    orientation_text: Optional[str] = Field(
        None, description="向きのパース原文 ('南東' 等。bratto は非公開のため常に null)"
    )
    orientation_deg: Optional[int] = Field(
        None, description="向きの角度 0-359 (北=0・不明は null / null ≠ 北=0)"
    )
    orientation_source: Optional[str] = Field(
        None, description="向きの取得経路 ('spec_parse' 等)。精度はこの値から導出"
    )
    point_text: Optional[str] = Field(None, description="物件紹介文 (POINT)")
    availability_text: Optional[str] = None
    min_stay_days: Optional[int] = None
    contract_fee_yen: Optional[int] = Field(
        None,
        description="契約事務手数料の実効値 (物件個別値 > サイト既定)。null = 取得元サイトの既定が未登録で算出不能",
    )
    first_seen_at: Optional[dt.datetime] = Field(None, description="初回検知日時 (掲載日数の算出に使用)")
    last_seen_at: Optional[dt.datetime] = Field(None, description="最終確認日時 (掲載終了時の参考値基準)")
    detail_scraped_at: Optional[dt.datetime] = None
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
# 物件検索リクエスト (H2: 検索フィルタパラメータ契約の正本)
# Web (/api/geojson, /api/geojson/stream) / MCP (search_properties,
# export_geojson, export_kml) / CLI (export-map) の6箇所で手書きされていた
# params dict 組立をここへ集約する。詳細は docs/ssot-commonization-survey.md H2。
# ============================================================


class SearchFilters(BaseModel):
    """物件検索フィルタのリクエスト契約 (Web / MCP / CLI 共通)。

    queries 層 (store.queries.search.iter_search_properties /
    store.queries.export) が期待する params dict へは
    to_query_params() で変換する。limit は呼び出し層ごとの既定差
    (MCP 一覧 50 / API 全件 10000 / export は queries 側で 10000 補完) を
    吸収するため Optional とし、呼び出し側が設定する。

    required_features は CSV 正規化 (strip + 空要素除去) の正本が queries 層
    (iter_search_properties 冒頭) にあるため、カンマ区切り文字列
    (Web QUERY STRING) も list[str] (MCP / CLI) も生値のまま受け入れる。
    モデル側では分割・正規化しない。
    """

    prefecture_name: Optional[str] = Field(
        None, description="県名 (表示名の完全一致)"
    )
    max_monthly_total_yen: Optional[int] = Field(
        None, description="30日換算総額の上限円 (post filter)"
    )
    max_walk_minutes: Optional[int] = Field(
        None, description="最寄り駅徒歩分数の上限 (post filter)"
    )
    min_area_m2: Optional[float] = Field(
        None, description="専有面積の下限 (m2・SQL WHERE)"
    )
    required_features: Optional[Union[str, List[str]]] = Field(
        None,
        description=(
            "必須設備。カンマ区切り文字列 or 配列の生値。"
            "正規化 (strip + 空要素除去) の正本は queries 層"
        ),
    )
    saved_only: bool = Field(False, description="ショートリスト saved のみ")
    exclude_hidden: bool = Field(True, description="hide / reject を除外")
    natural_query: Optional[str] = Field(
        None,
        description=(
            "自然文意味検索クエリ(PG移行 Phase 7・pgvector + gemini-embedding-2)。"
            "指定時は意味距離の昜順に建物がソートされ、embedding 未カバーの物件は"
            "結果から除外される。構造フィルタ(県 / features / 徒歩等)との併用可"
        ),
    )
    limit: Optional[int] = Field(
        None,
        description=(
            "最大取得件数。None = queries 層の既定 (50) で、export 系は "
            "queries 側が 10000 に補完する。呼び出し層ごとの既定差を吸収"
        ),
    )

    def to_query_params(self) -> Dict[str, Any]:
        """queries 層が期待する params dict へ変換する.

        None のキーは除外する (queries 層は params.get() で読むため
        「値 None」=「キー無し」と等価)。required_features は正規化せず
        生値のまま渡す (CSV 分割の正本は iter_search_properties 冒頭)。
        """
        return self.model_dump(exclude_none=True)


# ============================================================
# 建物 GeoJSON (GET /api/buildings/geojson) — 建物単位集約モデル Phase B1
# (正本: docs/building-aggregation-design.md §6.1。組立実体は
#  store.queries.buildings。B1 では FE は消費しないが契約の自己記述性のため
#  response_model に接続し openapi 生成型に載せる)
# ============================================================


class BuildingNameInfo(BaseModel):
    """ソース別建物名 1 件 (building_names 行・名寄せ監査の正本)。"""

    source_site: str = Field(..., description="ソース site id")
    name: str = Field(..., description="そのソースでの建物名")


class BuildingUnitProperties(BaseModel):
    """建物 Feature の units 要素 = 建物に所属する部屋 1 件。

    store.queries.buildings._assemble_rooms が載せる search 結果 1 物件の
    dict (_property_row_to_result 出力 + feature_categories) をそのまま
    搭載するため、部屋単位 /api/geojson の PropertyProperties (表示用に
    文字列化・整形済み) とはキー構成が意図的に異なる:

    - access_summary は文字列ではなく行リスト ("JR 渋谷駅 徒歩5分" 等)
    - images は URL 文字列ではなく {image_url, image_type, sort_order} の行 dict
    - source_property_id / external_id / prefecture_slug / built_year /
      built_month / lat / lng など生列を追加で保持
    - feature_summary は設備名カンマ結合(重複語除去済み・B2-ε で復旧:
      詳細パネル・比較ボードの設備表示と searchHaystack が消費)
    - station_summary は持たない (建物側 properties の station_summary に集約)
    """

    id: int
    source_site: Optional[str] = None
    source_display_name: Optional[str] = None
    source_property_id: Optional[str] = Field(
        None, description="external_id のエイリアス (MCP 互換)"
    )
    external_id: Optional[str] = Field(None, description="取得元サイトの物件 ID")
    title: Optional[str] = None
    detail_url: Optional[str] = None
    address: Optional[str] = None
    prefecture_name: Optional[str] = None
    prefecture_slug: Optional[str] = None
    municipality: Optional[str] = None
    layout: Optional[str] = None
    area_m2: Optional[float] = None
    built_year: Optional[int] = None
    built_month: Optional[int] = None
    floor_number: Optional[int] = Field(
        None, description="所在階 (min・地下は負数 / null = 取得元で非公開)"
    )
    floor_number_max: Optional[int] = Field(
        None, description="所在階 (max・複数階「1・2階」のみ min と異なる)"
    )
    orientation_deg: Optional[int] = Field(
        None,
        description="向きの角度 0-359 (北=0・不明は null / null ≠ 北=0。bratto は常に null)",
    )
    total_score: float = Field(
        0, description="総合スコア (スコアリング再活用予定のため維持・未スコアは 0)"
    )
    lat: Optional[float] = Field(
        None, description="部屋行の緯度 (建物代表座標は親 Feature の geometry)"
    )
    lng: Optional[float] = Field(
        None, description="部屋行の経度 (建物代表座標は親 Feature の geometry)"
    )
    point_text: Optional[str] = None
    min_walk_minutes: Optional[int] = None
    min_daily_rent: Optional[int] = Field(None, description="最安実効日額 (as-of-today)")
    min_plan_total: Optional[int] = Field(None, description="最安プランの 30 日換算総額")
    min_plan_name: Optional[str] = None
    min_plan_label: Optional[str] = Field(
        None, description="最安プランの表示ラベル (辞書解決・正本: domain.plan_catalog)"
    )
    thumbnail_url: Optional[str] = None
    shortlist_status: Optional[ShortlistStatus] = Field(
        None, description="saved / hide / reject / none (ショートリスト未登録は null)"
    )
    shortlist_updated_at: Optional[dt.datetime] = Field(
        None,
        description=(
            "ショートリスト行の最終更新時刻 (ISO・行登録時のみ。"
            "FE 最終編集順ソート用・未登録は null)"
        ),
    )
    is_active: bool = Field(True, description="false = サイト掲載終了")
    last_seen_at: Optional[dt.datetime] = None
    contract_fee_yen: Optional[int] = Field(
        None,
        description="契約事務手数料の実効値 (物件個別値 > サイト既定)。null = 算出不能",
    )
    feature_summary: str = Field(
        "", description="設備名のカンマ区切り要約(重複語除去済み)"
    )
    access_summary: List[str] = Field(
        [], description="アクセス行リスト ('JR 渋谷駅 徒歩5分' 等・文字列化前)"
    )
    images: List[PropertyImageInfo] = Field(
        [], description="画像行リスト (URL は image_url)"
    )
    feature_categories: List[str] = Field(
        [],
        description="部屋の充足可能カテゴリ code 集合 (単純/複合 code + 導出の親/横断 code)",
    )
    rent_plans: List[RentPlan] = []
    campaigns: List[Campaign] = []


class BuildingProperties(BaseModel):
    """建物 GeoJSON Feature の properties (検索結果 1 建物分)。

    一括 /api/buildings/geojson と /api/buildings/geojson/stream の feature 行
    で同一ペイロード。units は FE 向け GeoJSON では建物の可視部屋全て
    (units="all"・worker が現行フィルタを部屋単位で再適用する構成を維持)。
    """

    id: int = Field(..., description="buildings.id")
    kind: Literal["building"] = Field(
        "building", description="部屋単位 Feature (kind 無し) との識別子"
    )
    name: Optional[str] = Field(None, description="建物代表名 (canonical_name)")
    address: Optional[str] = Field(None, description="表示用代表住所")
    prefecture_slug: Optional[str] = None
    prefecture_name: Optional[str] = None
    municipality: Optional[str] = None
    built_year: Optional[int] = Field(None, description="築年 (建物内多数決の代表値)")
    structure: Optional[str] = Field(None, description="構造 (建物内多数決の代表値)")
    building_floors: Optional[int] = Field(None, description="建物階数 (建物内多数決の代表値)")
    is_active: bool = Field(
        True, description="false = active 部屋が 1 つも無い建物 (all_inactive)"
    )
    units_count: Optional[int] = Field(None, description="所属部屋数 (キャッシュ列)")
    active_units_count: Optional[int] = Field(None, description="active 部屋数 (キャッシュ列)")
    source_sites: List[str] = Field(
        [], description="所属部屋の source_site 一覧 (重複除去・出現順)"
    )
    building_names: List[BuildingNameInfo] = Field(
        [], description="ソース別建物名 (クロスソース名寄せ時の併記・監査用)"
    )
    feature_categories: List[str] = Field(
        [],
        description=(
            "建物レベル導出 code 集合 (所属部屋 code のうち sub='building' 語彙の"
            " union + 導出の親/横断 code・辞書順)"
        ),
    )
    min_daily_rent: Optional[int] = Field(None, description="所属部屋の最安実効日額")
    max_daily_rent: Optional[int] = Field(
        None, description="所属部屋の最高実効日額 (帯表示用)"
    )
    min_plan_total: Optional[int] = Field(None, description="最安部屋の 30 日換算総額")
    min_plan_label: Optional[str] = Field(None, description="最安部屋のプラン表示ラベル")
    min_walk_minutes: Optional[int] = Field(None, description="所属部屋の最小徒歩分数")
    thumbnail_url: Optional[str] = Field(
        None, description="代表写真 (現行 thumbnail 選別規則の建物内適用)"
    )
    has_campaign: bool = Field(
        False, description="active なキャンペーンを 1 つ以上の所属部屋が持つ (建物レベル束ねなし)"
    )
    access_summary: List[str] = Field(
        [], description="部屋 accesses の union + 重複除去 ('JR 渋谷駅 徒歩5分' 等)"
    )
    station_summary: str = Field("", description="カンマ区切りの駅名要約")
    units: List[BuildingUnitProperties] = Field(
        [], description="所属部屋一式 (id/title/layout/rent_plans/campaigns/...)"
    )
    shortlist_status: Optional[ShortlistStatus] = Field(
        None, description="建物ショートリスト状態 (saved / none・未登録は null)"
    )
    shortlist_comment: Optional[str] = Field(
        None, description="建物ショートリストのメモ (未登録は null)"
    )
    shortlist_updated_at: Optional[dt.datetime] = Field(
        None,
        description=(
            "建物ショートリスト行の最終更新時刻 (ISO・行登録時のみ。"
            "FE 最終編集順ソートの建物側キー・未登録は null)"
        ),
    )


class GeoJSONPoint(BaseModel):
    """Point ジオメトリ。coordinates は [lng, lat]。(旧部屋GeoJSONと共用の形状・
    B2-ε で旧側モデル削除後は建物 Feature 専用)"""

    type: Literal["Point"]
    coordinates: List[float]


class BuildingFeature(BaseModel):
    """建物 GeoJSON Feature 1 件 (Point・建物代表座標)。"""

    type: Literal["Feature"]
    geometry: GeoJSONPoint
    properties: BuildingProperties


class BuildingGeoJSON(BaseModel):
    """GET /api/buildings/geojson の FeatureCollection 応答。"""

    type: Literal["FeatureCollection"]
    features: List[BuildingFeature]


# ============================================================
# 価格変動推移 (GET /api/analysis/price-trend)
# ============================================================


class PriceTrendPoint(BaseModel):
    """価格変動の日次集計 1 点。"""

    date: dt.date = Field(..., description="YYYY-MM-DD")
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
    generated_at: dt.datetime
    providers: List[PriceTrendProvider]
    series: PriceTrendSeries
    meta: PriceTrendMeta


# ============================================================
# ショートリスト更新 (POST /api/properties/{property_id}/shortlist)
# ============================================================


class ShortlistUpdateResponse(BaseModel):
    status: Literal["success"]
    property_id: Optional[int] = None
    shortlist_status: ShortlistStatus


# ============================================================
# 建物ショートリスト更新 (POST /api/buildings/{building_id}/shortlist)
# ============================================================


class BuildingShortlistUpdateRequest(BaseModel):
    status: Literal["saved", "none"]
    comment: Optional[str] = None


class BuildingShortlistUpdateResponse(BaseModel):
    status: Literal["success"]
    building_id: int
    shortlist_status: Literal["saved", "none"]


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
    started_at: Optional[dt.datetime] = None
    finished_at: Optional[dt.datetime] = None
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
    building_shortlist: Dict[str, int] = Field(
        {}, description="建物ショートリストの状態→件数マップ"
    )
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
    last_seen_at: Optional[dt.datetime] = None
    last_detail_scraped_at: Optional[dt.datetime] = None
    last_run_at: Optional[dt.datetime] = None
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
    last_full_ok_at: Optional[dt.datetime] = Field(None, description="前回フル取得成功時刻")
    last_run_at: Optional[dt.datetime] = None
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
    pinBalloonPermanent: Optional[bool] = Field(
        None,
        description=(
            "物件バルーン(tooltip)の常時表示 "
            "(クラスタリング無効時のみ実効。未指定/null = false)"
        ),
    )
    mapBackground: Optional[Literal["black", "white"]] = Field(
        None,
        description=(
            "最下レイヤ(基本地図)下に見える地図コンテナの背景色 "
            "(未指定/null = 'black' = 従来色)"
        ),
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
