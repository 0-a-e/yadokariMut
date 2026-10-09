from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from typing import Optional

from mcp.server.mcpserver import MCPServer

import api_models
from store import api_queries
from domain.feature_categories import format_categories_docstring
from domain.feature_resolution import resolve_requirements
from store.queries import buildings as buildings_queries
from store.queries.buildings import count_buildings, search_buildings
from store.queries.geojson import export_building_geojson

# docstring はモジュールロード時に 1 回だけ生成する(設計 §3.5・辞書からの自動生成)
_CATEGORIES_DOC = format_categories_docstring()


mcp = MCPServer(
    "yadokari-mut",
    instructions=(
        "Search, compare, shortlist, and export monthly apartment properties "
        "from the local YadokariMut PostgreSQL database."
    ),
    log_level="ERROR",
)


def _query_error(e: BaseException) -> dict:
    """api_queries 由来の例外 (AmbiguousPropertyLookup / NotFound 相当) を
    MCP 共通エラー応答へ変換する.

    MCP クライアント互換のため応答形状 (200 + {"status": "error", "message"})
    は変更しない。API 側の 409/404 HTTPException とは意図的に異なる表現で、
    web_server 側は変更しない。例外 → status:error 変換はここに集約する。
    """
    return {"status": "error", "message": str(e)}


def _expand_categories_doc(fn):
    """docstring 内の {_CATEGORIES_DOC} を辞書自動生成の一覧で差し替える.

    f-string は Python の仕様上 __doc__ にならないため、@mcp.tool() が
    __doc__ を読む前 (登録前) に展開するためのデコレータ (設計 §3.5)。
    """
    fn.__doc__ = (fn.__doc__ or "").replace("{_CATEGORIES_DOC}", _CATEGORIES_DOC)
    return fn


@mcp.tool()
@_expand_categories_doc
def search_properties(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    natural_query: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Search apartment BUILDINGS with structured filters (aggregated model).

    建物単位集約モデル (docs/building-aggregation-design.md §6.2・破壊的変更)。
    応答 results の 1 要素 = 1 建物。limit の単位は部屋数ではなく**建物数**
    (既定 50、最大 10000 — API 側の全件取得時既定と同じ上限)。

    探査ガイド: **まず建物で絞り(本ツール)、次に units で部屋を選ぶ**。
    - 本ツール: 絞り込み+建物サマリ+条件一致部屋の一覧
    - get_building_detail: 建物 1 件の可視部屋全件(units="all" 相当)
    - get_property_detail: 部屋 1 件の完全詳細

    フィルタ意味論: 部屋条件(required_features / max_monthly / max_walk /
    min_area 等)は「**条件を満たす部屋を 1 つ以上持つ建物**」がヒットし、
    units 配列には**条件一致部屋のみ**載る(エージェントに無関係な部屋は
    載せない)。可視性(掲載終了 / hide / reject)は建物ヒット判定の前段で
    部屋単位に適用される。

    natural_query(PG移行 Phase 7・意味検索): 自然文(例「駅から近くて静かな
    物件」「海の見える部屋」)を指定すると意味検索(pgvector + gemini-embedding-2)
    が有効になり、結果は**意味的な近さの昜順**でソートされる。構造フィルタとの
    併用可(併用時はフィルタ適用後に意味順)。embedding 未カバーの物件は結果から
    除外される。構造条件で表現できない曖昧な希望(雰囲気 / 立地の質 等)がある
    場合に使うこと。

    建物フィールド:
    - kind: 常に "building"(部屋応答との判別用)
    - name: 代表建物名(canonical_name)/ building_names: ソース別名一覧
    - address / prefecture_name / municipality / lat,lng(代表座標)
    - built_year / structure / building_floors(多数決の代表値)
    - units_count: 全部屋数 / active_units_count: 掲載中部屋数
    - min_daily_rent / max_daily_rent: 日額帯(表示用) /
      min_plan_total / min_plan_label: 最安部屋の 30 日総額と表示ラベル
    - min_walk_minutes: 最寄り駅徒歩の最小値 / thumbnail_url: 代表写真
    - has_campaign: 有効キャンペーンの有無(内容は units 内の部屋を見ること)
    - access_summary: 駅アクセス結合 / station_summary: 駅名結合
    - feature_categories: 建物レベル導出 code(部屋 feature の union)
    - is_active: 掲載中部屋が 1 つ以上あるか。false(=全部屋掲載終了・
      shortlist 判定済みのため表示)の場合は必ずユーザーに「掲載終了」の旨を
      伝えること。価格等は最終取得時点の参考値。
    - units: 条件一致部屋の配列(各要素は部屋 dict — id / title / layout /
      area_m2 / rent_plans / campaigns / feature_categories / is_active /
      shortlist_status / detail_url / images)。units 内の is_active=false は
      その部屋のみの掲載終了。「この建物の他の部屋」を確認する場合は
      get_building_detail を使う。

    required_features は機能カテゴリ code の AND(要件ごとに OR・feature 単位判定):
    - 単純 code(例 'auto_lock')・複合 code('bicycle_parking.fee_free'=駐輪場無料)を
      直接指定できる。親 code('bicycle_parking'=費用軸を問わない駐輪場あり)は子 code
      全体の OR、横断 code('fee_free'=「何かの費用無料」)は他要件との佃用も可
      (feature 単位で正確)。
    - カテゴリの label・DB 生値('室内洗濯機' 等)も指定可(所属 code へ丸める)。
    - 辞書に無い値は DB 生値との完全一致として扱う(過少検出になり得る)。
    - 判定根拠は部屋の feature_categories(建物 feature_categories は部屋の union)。
    応答 meta.required_resolved に入力値の解決結果(codes / 生値 fallback 区別)と
    candidates_exhausted(候補を使い切ったのに limit 未満なら静かな過少返却の疑い・
    候補単位は建物)を返す。0 件のときはまず meta を確認すること。
    meta.total_buildings は limit 適用前のヒット建物総数、meta.total_units は
    応答に載った units の総数(limit 内のみ・全ヒット建物の総部屋数ではない)。

    カテゴリ一覧(code(label) — group/sub 構造):
    {_CATEGORIES_DOC}
    """
    state: dict = {}
    # params dict の組立正本は api_models.SearchFilters (H2)
    params = api_models.SearchFilters(
        prefecture_name=prefecture_name,
        max_monthly_total_yen=max_monthly_total_yen,
        max_walk_minutes=max_walk_minutes,
        min_area_m2=min_area_m2,
        required_features=required_features,
        saved_only=saved_only,
        exclude_hidden=exclude_hidden,
        natural_query=natural_query,
        limit=limit,
    ).to_query_params()
    # MCP は条件一致部屋のみ搭載 (設計 §6.1 units="matching"・候補単位=建物)
    results = search_buildings(params, state=state, units="matching")
    requirements = resolve_requirements(required_features or [])
    return {
        "meta": {
            "count": len(results),
            "total_buildings": count_buildings(params),
            "total_units": sum(len(b.get("units") or []) for b in results),
            "required_resolved": [
                {"input": r.raw, "codes": sorted(r.codes), "is_fallback": r.is_fallback}
                for r in requirements
            ],
            "candidates_exhausted": state.get("candidates_exhausted"),
        },
        "results": results,
    }


@mcp.tool()
def get_property_detail(
    property_id: str,
    by: str = "auto",
    source: Optional[str] = None,
) -> Optional[dict]:
    """Fetch complete details for a room (property).

    by: "auto"(既定) は数字キーを properties.id として優先し、該当が無ければ
    room_id(external_id) として解決する。"id" は properties.id のみ、"external"
    は room_id のみ。room_id は (source_site, external_id) でのみ一意なため、
    source 未指定で複数ソースに一致した場合はエラーを返す(source に
    "unionmonthly" 等を指定する)。数値の room_id を確実に引きたい場合は
    by="external" を明示すること(properties.id と値域が重なるため)。

    レスポンスの is_active=false はサイト掲載終了を示す。その場合の価格・
    キャンペーン等は最終取得時点の参考値であり、ユーザーに必ず伝えること。

    building セクション (建物単位集約モデル §6.2): 応答には
    building: {building_id, name(代表建物名), address} が載る。この部屋の
    所属建物の概要であり、建物の全部屋を見るには get_building_detail に
    building_id を渡す。建物未割当の部屋は building=null。
    """
    try:
        return api_queries.get_property_detail(property_id, by=by, source=source)
    except api_queries.AmbiguousPropertyLookup as e:
        return _query_error(e)


@mcp.tool()
def get_building_detail(building_id: int) -> dict:
    """Fetch complete details for a building with all its visible rooms (units).

    建物単位集約モデル (docs/building-aggregation-design.md §6.2)。
    building_id は search_properties 応答の各建物の id を使う。

    応答は建物サマリ (kind="building" / name=代表建物名 / address /
    prefecture_name / municipality / lat,lng 代表座標 / built_year / structure /
    building_floors / units_count=全部屋数 / active_units_count=掲載中部屋数 /
    min_daily_rent〜max_daily_rent の日額帯 / min_plan_total・min_plan_label=
    最安部屋の 30 日総額と表示ラベル / min_walk_minutes / thumbnail_url /
    has_campaign / access_summary・station_summary / feature_categories=
    建物レベル導出 code / building_names=ソース別名 / is_active) に、
    **可視部屋全件の units 配列** (掲載終了部屋を含む。各要素は部屋 dict で
    is_active=false が区別できる) を加えたもの。この建物に条件一致部屋が
    何部屋あるかを見る場合は search_properties の units を使うこと。

    is_active=false の建物(全部屋掲載終了)・units 内の is_active=false 部屋は
    価格等が最終取得時点の参考値であるため、ユーザーに必ず「掲載終了」の旨を
    伝えること。
    """
    detail = buildings_queries.get_building_detail(building_id)
    if detail is None:
        return _query_error(LookupError(f"Building with ID '{building_id}' not found"))
    return detail


@mcp.tool()
def compare_properties(
    property_ids: list[str],
    by: str = "auto",
    source: Optional[str] = None,
) -> dict:
    """Compare multiple properties side by side.

    by / source は get_property_detail と同じ。
    """
    try:
        return api_queries.compare_properties(property_ids, by=by, source=source)
    except api_queries.AmbiguousPropertyLookup as e:
        return _query_error(e)


@mcp.tool()
def update_building_shortlist(
    building_id: int,
    status: str,
    comment: Optional[str] = None,
) -> dict:
    """Set shortlist status for a building. Status must be saved or none.

    建物ショートリスト(ブックマーク)。部屋の update_shortlist と対称だが、
    建物側は当面 saved(+メモ)のみ。building_id は search_properties 応答の
    各建物の id / get_building_detail の id を使う。
    """
    res = api_queries.update_building_shortlist(building_id, status, comment)
    if not res.get("ok"):
        return _query_error(
            LookupError(f"Building with id '{building_id}' not found")
        )
    return {
        "status": "success",
        "building_id": res.get("building_id"),
        "shortlist_status": status,
    }


@mcp.tool()
def update_shortlist(
    property_id: str,
    status: str,
    comment: Optional[str] = None,
    by: str = "auto",
    source: Optional[str] = None,
) -> dict:
    """Set shortlist status for a property. Status must be saved, hide, reject, or none.

    by / source は get_property_detail と同じ。数値の room_id を指定する場合は
    properties.id との衝突を避けるため by="external" を明示すること。
    """
    try:
        res = api_queries.update_shortlist(
            property_id, status, comment, by=by, source=source
        )
    except api_queries.AmbiguousPropertyLookup as e:
        return _query_error(e)
    if not res.get("ok"):
        # NotFound 相当 (api_queries は {"ok": False} を返すためここで例外化して変換)
        return _query_error(
            LookupError(f"Property with ID/room_id '{property_id}' not found")
        )
    return {"status": "success", "property_id": res.get("property_id"), "shortlist_status": status}


@mcp.tool()
def export_geojson(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    file_path: Optional[str] = None,
) -> dict:
    """Export filtered buildings as a GeoJSON file for map viewing.

    建物単位集約モデル (docs/building-aggregation-design.md §6.2)。1 feature =
    1 建物で、properties に建物サマリ (kind/name/units_count/min_daily_rent 等) と
    **全部屋の units 配列**を含む (search_properties と異なり units は条件一致に
    限らない)。feature_count の単位は建物数。各 feature の properties に
    is_active を含む（false=掲載終了部屋・建物あり。ユーザーに必ず伝えること）。
    未指定時は API 側と同じ上限 10000 建物で取得する。
    required_features の意味(機能カテゴリ code の AND・カテゴリ一覧)は
    search_properties ツールの説明を参照(同一の判定エンジン)。
    """
    # params dict の組立正本は api_models.SearchFilters (H2)。
    # limit 未指定 (None) は export 系 queries 側が 10000 に補完するため
    # そのまま渡す
    params = api_models.SearchFilters(
        prefecture_name=prefecture_name,
        max_monthly_total_yen=max_monthly_total_yen,
        max_walk_minutes=max_walk_minutes,
        min_area_m2=min_area_m2,
        required_features=required_features,
        saved_only=saved_only,
        exclude_hidden=exclude_hidden,
    ).to_query_params()
    return export_building_geojson(params, file_path)


@mcp.tool()
def export_kml(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    file_path: Optional[str] = None,
) -> dict:
    """Export filtered properties as a KML file for Google Earth/My Maps.

    required_features の意味(機能カテゴリ code の AND・カテゴリ一覧)は
    search_properties ツールの説明を参照(同一の判定エンジン)。
    """
    # params dict の組立正本は api_models.SearchFilters (H2)。
    # limit 未指定 (None) は export 系 queries 側が 10000 に補完するため
    # そのまま渡す
    params = api_models.SearchFilters(
        prefecture_name=prefecture_name,
        max_monthly_total_yen=max_monthly_total_yen,
        max_walk_minutes=max_walk_minutes,
        min_area_m2=min_area_m2,
        required_features=required_features,
        saved_only=saved_only,
        exclude_hidden=exclude_hidden,
    ).to_query_params()
    return api_queries.export_kml(params, file_path)


@mcp.tool()
def geocode_properties(
    limit: Optional[int] = 20,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = None,
) -> dict:
    """Geocode buildings (B2-ε: building-first) and unassigned rooms missing coordinates. Useful to fix map display exclusions.

    座標のない建物を住所でジオコーディングし、成功時は所属部屋へ代表座標を
    backfill する。未割当(building 未割当)の部屋のみ従来の部屋単位で処理。
    モード: 既定では座標のない対象のみ。force で全件、retry_only で一度でも
    ジオコード/失敗記録のある対象を再試行する。filter_expr は廃止された。
    引数ルール (filter_expr 拒否 / provider 白色リスト / force≠retry_only 排他)
    は API (/api/admin/geocode) と共通の validate_geocode_args で検証し、
    違反は status:error 応答で返す。
    """
    from store.geocode_v2 import validate_geocode_args

    try:
        validate_geocode_args(
            limit,
            force=force,
            provider=provider,
            retry_only=retry_only,
            filter_expr=filter_expr,
        )
    except ValueError as e:
        return _query_error(e)

    from store.geocode_v2 import (
        format_geocode_warnings,
        geocode_missing_v2,
        geocode_result_warnings,
    )
    try:
        stats = geocode_missing_v2(
            limit=limit, provider=provider, force=force, retry_only=retry_only
        )
        remaining = stats.get("remaining", 0)
        if remaining > 0:
            message = (
                f"Geocoding batch executed. Processed {stats['processed']} properties "
                f"(Success: {stats['success']}, Failed: {stats['failed']}, "
                f"Unchanged: {stats.get('unchanged', 0)}). "
                f"Note: {remaining} properties are still remaining and need geocoding."
            )
        else:
            message = f"Geocoding completed. All {stats['total_found']} matching properties have been processed."
        # spec §3.8: skipped / unchanged / 打ち切りをエージェントに区別して伝える
        if stats.get("unchanged"):
            message += (
                f" {stats['unchanged']} properties already had valid coordinates "
                "and were left unchanged."
            )
        # 警告文言は geocode_v2 の正本 formatter から生成(MCP は en 慣習。
        # skipped 行のみ spec §3.8 契約により日本語のまま含まれる)
        for line in format_geocode_warnings(geocode_result_warnings(stats), lang="en"):
            message += f" {line}"

        return {
            "status": "success",
            "message": message,
            "details": stats
        }
    except Exception as e:
        return _query_error(e)


def run_mcp_server():
    """Run the official MCP stdio server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
