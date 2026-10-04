from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from typing import Optional

from mcp.server.mcpserver import MCPServer

from store import api_queries


mcp = MCPServer(
    "yadokari-mut",
    instructions=(
        "Search, compare, shortlist, and export monthly apartment properties "
        "from the local YadokariMut SQLite database."
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


@mcp.tool()
def search_properties(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[list[str]] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    limit: int = 50,
) -> list[dict]:
    """Search properties with structured filters.

    limit は既定 50、最大 10000 (API 側の全件取得時既定と同じ上限)。
    MCP はエージェント UX 向けの絞り込み一覧 (既定 50)、API は全件取得
    (既定 10000) という位置づけの違いであり、既定値は意図的に異なる。

    結果には掲載終了(is_active=false)の shortlist 判定済み物件も含まれる。
    is_active=false の物件は必ずユーザーに「掲載終了」である旨を伝えること。
    価格等は最終取得時点の参考値。
    """
    return api_queries.search_properties(
        {
            "prefecture_name": prefecture_name,
            "max_monthly_total_yen": max_monthly_total_yen,
            "max_walk_minutes": max_walk_minutes,
            "min_area_m2": min_area_m2,
            "required_features": required_features,
            "saved_only": saved_only,
            "exclude_hidden": exclude_hidden,
            "limit": limit,
        }
    )


@mcp.tool()
def get_property_detail(
    property_id: str,
    by: str = "auto",
    source: Optional[str] = None,
) -> Optional[dict]:
    """Fetch complete details for a property.

    by: "auto"(既定) は数字キーを properties.id として優先し、該当が無ければ
    room_id(external_id) として解決する。"id" は properties.id のみ、"external"
    は room_id のみ。room_id は (source_site, external_id) でのみ一意なため、
    source 未指定で複数ソースに一致した場合はエラーを返す(source に
    "unionmonthly" 等を指定する)。数値の room_id を確実に引きたい場合は
    by="external" を明示すること(properties.id と値域が重なるため)。

    レスポンスの is_active=false はサイト掲載終了を示す。その場合の価格・
    キャンペーン等は最終取得時点の参考値であり、ユーザーに必ず伝えること。
    """
    try:
        return api_queries.get_property_detail(property_id, by=by, source=source)
    except api_queries.AmbiguousPropertyLookup as e:
        return _query_error(e)


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
    """Export filtered properties as a GeoJSON file for map viewing.

    各 feature の properties に is_active を含む（false=サイト掲載終了）。
    未指定時は API 側と同じ上限 10000 件で全件取得する。
    """
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": required_features,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
    }
    return api_queries.export_geojson(params, file_path)


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
    """Export filtered properties as a KML file for Google Earth/My Maps."""
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": required_features,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
    }
    return api_queries.export_kml(params, file_path)


@mcp.tool()
def geocode_properties(
    limit: Optional[int] = 20,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = None,
) -> dict:
    """Geocode properties in the database that are missing coordinates. Useful to fix map display exclusions.

    モード: 既定では座標のない物件のみ。force で全件、retry_only で一度でも
    ジオコード/失敗記録のある物件を再試行する。filter_expr は廃止された。
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

    from store.geocode_v2 import geocode_missing_v2
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
        if stats.get("skipped"):
            message += (
                f" {stats['skipped']} 件はプロバイダ障害等のため記録なしスキップ。"
                "時間を置いて再実行してください"
            )
        if stats.get("aborted"):
            message += " The batch aborted early (circuit breaker on consecutive provider errors)."

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
