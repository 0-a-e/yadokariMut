"""admin API: status / sources / scrape / scrape-settings / geocode。

geocode を `router` と別の `geocode_router` に分離しているのは挙動上の理由
ではなく、旧 web_server.py の登録順 (status..scrape → rotation 一式 →
geocode) を web.app.create_app() で再現し、frontend/openapi.json を byte
同値に保つため (登録順が OpenAPI paths の並びになるため)。
"""

from typing import List, Optional

from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

import api_models
from web.tasks import (
    TASK_STATUS,
    require_task_idle,
    run_geocode_task,
    run_scrape_task,
)

router = APIRouter()
geocode_router = APIRouter()


@router.get("/api/admin/status", response_model=api_models.AdminStatsResponse)
def get_admin_status():
    """Gets statistics and background scheduler/scraper status."""
    try:
        from store.repository import Repository

        db_stats = Repository().db_stats()
    except Exception:
        db_stats = {
            "total_properties": 0,
            "missing_coordinates": 0,
            "shortlist": {},
            "by_source": {},
        }

    transfer = None
    try:
        from sources.http.metrics import get_transfer_metrics
        from sources.http.settings import load_http_settings

        transfer = get_transfer_metrics().snapshot()
        http_mode = load_http_settings().mode
        proxy_enabled = load_http_settings().proxy_enabled
    except Exception:
        http_mode = "off"
        proxy_enabled = False

    # Recent run rows straight from the DB: unlike in-memory TASK_STATUS these
    # survive restarts, so e.g. a failed nightly rotation run stays visible.
    recent_runs: list = []
    try:
        from store.repository import Repository

        recent_runs = Repository().recent_scrape_runs(limit=8)
    except Exception:
        recent_runs = []

    return {
        "task_status": TASK_STATUS,
        "recent_runs": recent_runs,
        "http": {
            "mode": http_mode,
            "proxy_enabled": proxy_enabled,
        },
        "transfer": transfer,
        "db_stats": db_stats,
    }


@router.get("/api/admin/sources", response_model=api_models.AdminSourcesResponse)
def get_admin_sources():
    """List ingest sources for admin UI (catalog + registry + counts)."""
    from store.source_catalog import list_source_admin_info

    return {
        "sources": list_source_admin_info(),
    }


@router.get(
    "/api/admin/scrape-settings", response_model=api_models.ScrapeSettingsResponse
)
def get_admin_scrape_settings():
    """ソース別スクレイプ設定(取得間隔/制限時クールダウン)の実効値を返す。"""
    from scrape_settings import effective_source_settings

    return effective_source_settings()


@router.post(
    "/api/admin/scrape-settings", response_model=api_models.ScrapeSettingsResponse
)
def save_admin_scrape_settings(update: dict):
    """ソース別スクレイプ設定の部分マージ保存(null で該当キーを既定へ戻す)。

    ボディは意図的に pydantic モデル化しない (update: dict)。null = 保存済み
    キーの削除 (既定へ戻す) という部分マージ契約を保持するためで、値の
    バリデーションは scrape_settings 側で行い、違反は 400 で返す。
    返り値は部分マージ後の保存値全体 (defaults / saved は null)。
    """
    from scrape_settings import save_scrape_settings

    try:
        return save_scrape_settings(update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class ScrapeRequest(BaseModel):
    """Body for multi-source v2 rescrape."""

    sources: Optional[List[str]] = None  # e.g. ["bratto"] or ["all"]
    pages: Optional[int] = 5
    all_pages: bool = False
    max_details: Optional[int] = None
    list_only: bool = False
    mark_inactive: bool = True
    prefs: Optional[List[str]] = None
    delay: Optional[float] = None
    geocode: bool = True
    geocode_limit: int = 200


@router.post(
    "/api/admin/scrape",
    response_model=api_models.ScrapeStartResponse,
    dependencies=[Depends(require_task_idle)],
)
def trigger_scrape(
    background_tasks: BackgroundTasks,
    body: Optional[ScrapeRequest] = None,
    source: Optional[str] = Query(None, description="Single source id or 'all'"),
    pages: Optional[int] = Query(None),
    all_pages: Optional[bool] = Query(None),
):
    """Trigger multi-source v2 scrape (per-source or bulk)."""
    req = body or ScrapeRequest()
    sources = list(req.sources or [])
    if source:
        sources = [source]
    if not sources:
        sources = ["all"]

    # Query overrides
    use_all_pages = req.all_pages if all_pages is None else all_pages
    use_pages = req.pages if pages is None else pages

    try:
        from store.source_catalog import resolve_scrape_sources

        resolved = resolve_scrape_sources(sources)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not resolved:
        raise HTTPException(status_code=400, detail="No available sources to scrape")

    background_tasks.add_task(
        run_scrape_task,
        resolved,
        pages=use_pages,
        all_pages=bool(use_all_pages),
        max_details=req.max_details,
        list_only=req.list_only,
        mark_inactive=req.mark_inactive,
        prefs=req.prefs,
        delay=req.delay,
        geocode=req.geocode,
        geocode_limit=req.geocode_limit,
    )
    return {
        "status": "started",
        "task": "scrape",
        "sources": resolved,
        "prefs": req.prefs,
        "all_pages": bool(use_all_pages),
        "pages": use_pages,
        "mark_inactive": req.mark_inactive,
    }


@geocode_router.post(
    "/api/admin/geocode",
    response_model=api_models.TaskStartResponse,
    dependencies=[Depends(require_task_idle)],
)
def trigger_geocode(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = 20,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = Query(
        None, description="Removed: filter_expr is no longer supported (v2)"
    ),
):
    """Triggers geocoding of v2 properties in the background (spec §3.3 modes)."""
    # spec §3.7: filter_expr 拒否 / provider 白色リスト / force≠retry_only 排他の
    # 3 ルールは MCP (mcp_server.geocode_properties) と共通の実装で検証する。
    # ここでは ValueError を手書き 422 に変換する。
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
        raise HTTPException(status_code=422, detail=str(e))

    background_tasks.add_task(
        run_geocode_task,
        limit,
        force,
        provider,
        retry_only,
    )
    return {"status": "started", "task": "geocode"}
