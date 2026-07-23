import sys
import os
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# CopilotKit + LangGraph AG-UI
from copilotkit import LangGraphAGUIAgent
from ag_ui_langgraph.endpoint import EventEncoder
from ag_ui.core.types import RunAgentInput
from agent_service import _build_graph, _cleanup_mcp
from database import get_db_connection
from services import (
    db_search_properties,
    db_update_shortlist,
    db_get_property_detail,
    db_compare_properties,
    clean_point_text,
)
from campaign_active import annotate_campaigns
from scraper import scrape_list_pages, scrape_detail_pages
from geocoder import geocode_missing_properties
from commute_scorer import update_all_scores
from campaign_classifier import run_classification
from feature_classifier import run_feature_classification


@asynccontextmanager
async def lifespan(app: FastAPI):
    # v2 DB マウント時はスキーマを保証
    try:
        from store.api_queries import use_v2_data_layer
        from store.repository import Repository

        if use_v2_data_layer():
            Repository().init_db()
            logging.getLogger(__name__).info("v2 schema ensured on startup.")
    except Exception as e:
        print(f"v2 schema init skipped/failed: {e}")

    # 起動時: graph をビルドし、app.state に agent を保存
    try:
        graph = await _build_graph()
        logger = logging.getLogger(__name__)
        logger.info("LangGraph agent built successfully.")

        app.state.agent = LangGraphAGUIAgent(
            name="yadokari_agent",
            description="YadokariMut property search assistant",
            graph=graph,
        )
        logger.info("Agent stored in app.state")
    except Exception as e:
        print(f"Failed to build LangGraph agent: {e}")
        raise

    # 既存のスケジューラー起動処理
    enable_scheduler = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    if enable_scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        cron_expr = os.environ.get("SCHEDULER_CRON", "0 2 * * *")
        log_task(f"Initializing APScheduler. Cron: '{cron_expr}'")

        try:
            scheduler = BackgroundScheduler()
            fields = cron_expr.split()
            if len(fields) == 5:
                trigger = CronTrigger(
                    minute=fields[0],
                    hour=fields[1],
                    day=fields[2],
                    month=fields[3],
                    day_of_week=fields[4]
                )
                scheduler.add_job(
                    run_scheduled_scraping_job,
                    trigger,
                    id="daily_scrape",
                    name="Daily Scrape, Score, Geocode Job"
                )
                scheduler.start()
                log_task("Scheduler started successfully.")
            else:
                log_task(f"Invalid cron expression: '{cron_expr}'. Scheduler not started.")
        except Exception as e:
            log_task(f"Failed to start scheduler: {str(e)}")

    yield

    # 終了時: MCP接続のクリーンアップ
    await _cleanup_mcp()


app = FastAPI(
    title="YadokariMut API Server",
    description="Web API for YadokariMut Monthly Mansion Explorer",
    version="2.0.0",
    lifespan=lifespan,
)

# ============================================================
# AG-UI Direct Endpoint (module-level registration)
# MUST be registered BEFORE StaticFiles mount
# ============================================================
@app.post("/api/copilotkit")
async def copilotkit_agent_endpoint(input_data: RunAgentInput, request: Request):
    """AG-UI direct agent endpoint for CopilotKit frontend."""
    logger = logging.getLogger(__name__)
    try:
        logger.info(f"Received copilotkit request: thread_id={input_data.thread_id}, run_id={input_data.run_id}")
        logger.info(f"Input messages: {input_data.messages}")
    except Exception as e:
        logger.error(f"Failed to log request meta: {e}")

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized yet")

    encoder = EventEncoder(accept=request.headers.get("accept"))
    request_agent = agent.clone()

    async def event_generator():
        try:
            async for event in request_agent.run(input_data):
                yield encoder.encode(event)
        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)
            try:
                # Attempt to retrieve current messages in state for debugging
                from langchain_core.runnables import ensure_config
                config = ensure_config(request_agent.config.copy() if request_agent.config else {})
                config["configurable"] = {**(config.get('configurable', {})), "thread_id": input_data.thread_id}
                state = await request_agent.graph.aget_state(config)
                logger.error(f"Messages count in state: {len(state.values.get('messages', []))}")
                for i, msg in enumerate(state.values.get('messages', [])):
                    logger.error(f"Msg {i}: type={type(msg).__name__}, content={str(msg.content)[:200]}, additional_kwargs={msg.additional_kwargs if hasattr(msg, 'additional_kwargs') else None}")
            except Exception as ex:
                logger.error(f"Failed to dump messages for debug: {ex}")
            # AG-UI RunErrorEvent requires `message` (not `error`)
            from ag_ui.core import EventType, RunErrorEvent
            try:
                yield encoder.encode(
                    RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code="agent_execution_error")
                )
            except Exception:
                import json
                yield f'data: {json.dumps({"type": "RUN_ERROR", "message": str(e), "code": "agent_execution_error"})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type=encoder.get_content_type(),
    )


@app.get("/api/copilotkit/health")
def copilotkit_health():
    """Health check for CopilotKit agent endpoint."""
    return {"status": "ok"}


# ── Chat thread session management (checkpoint-backed) ──
@app.get("/api/chat/threads")
async def list_chat_threads(limit: int = Query(100, ge=1, le=500)):
    """List past chat sessions stored in the agent checkpoint DB."""
    from chat_threads import list_threads

    threads = await list_threads(limit=limit)
    return {"threads": threads}


@app.get("/api/chat/threads/{thread_id}/messages")
async def get_chat_thread_messages(thread_id: str):
    """Return AG-UI-friendly messages for a checkpoint thread."""
    from chat_threads import get_thread_messages

    messages = await get_thread_messages(thread_id)
    return {"threadId": thread_id, "messages": messages}


@app.delete("/api/chat/threads/{thread_id}")
async def delete_chat_thread(thread_id: str):
    """Delete a chat thread's checkpoints."""
    from chat_threads import delete_thread

    result = await delete_thread(thread_id)
    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message") or "delete failed")
    return result


# Global status tracking for background operations
TASK_STATUS = {
    "status": "idle",  # "idle" or "running"
    "current_task": None,
    "last_run": None,
    "error": None,
    "logs": [],
    "last_transfer": None,  # scrape session transfer snapshot
}

def log_task(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    print(log_entry)
    TASK_STATUS["logs"].append(log_entry)
    if len(TASK_STATUS["logs"]) > 200:
        TASK_STATUS["logs"].pop(0)

# Request schema for updating shortlist
class ShortlistUpdateRequest(BaseModel):
    status: str
    comment: Optional[str] = None

# Background Task Runners
def run_scrape_task(prefectures: List[str], max_pages: int, delay: float, classify: bool):
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = "scrape"
    TASK_STATUS["error"] = None
    
    try:
        log_task(f"Starting scraping process for prefectures: {prefectures} (max pages: {max_pages})")
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
        if not os.path.exists(config_path):
            raise FileNotFoundError("config.json not found")
            
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        all_crawled = []
        for pref in prefectures:
            log_task(f"Scraping list pages for {pref}...")
            crawled = scrape_list_pages(pref, config, max_pages=max_pages, delay=delay)
            all_crawled.extend(crawled)
            
        if all_crawled:
            log_task(f"Scraping detail pages for {len(all_crawled)} properties...")
            scrape_detail_pages(all_crawled, delay=delay)
            
            log_task("Running geocoding for missing coordinates...")
            geocode_missing_properties()
            
            log_task("Recalculating property scores...")
            update_all_scores()
            
            if classify:
                log_task("Structuring campaigns (mechanical)...")
                run_classification(use_batch=False, use_llm_residuals=False, force=True)
                log_task("Classifying property features...")
                run_feature_classification(use_batch=False)
                
            log_task("Scraping task completed successfully.")
        else:
            log_task("No properties found to scrape details.")
            
    except Exception as e:
        error_msg = f"Scrape task failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()

def run_geocode_task(limit: Optional[int], force: bool, provider: Optional[str], retry_only: bool, filter_expr: Optional[str]):
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = "geocode"
    TASK_STATUS["error"] = None
    try:
        log_task("Starting batch geocoding task...")
        try:
            from store.api_queries import use_v2_data_layer
            from store.geocode_v2 import geocode_missing_v2

            if use_v2_data_layer() and not force and not retry_only and not filter_expr:
                stats = geocode_missing_v2(limit=limit, provider=provider)
                log_task(
                    f"Geocoding completed (v2). Processed: {stats.get('processed', 0)}, "
                    f"Success: {stats.get('success', 0)}, Failed: {stats.get('failed', 0)}"
                )
                return
        except Exception as e:
            log_task(f"v2 geocode path failed, trying v1: {e}")

        stats = geocode_missing_properties(
            limit=limit,
            force=force,
            provider=provider,
            retry_only=retry_only,
            filter_expr=filter_expr
        )
        log_task(f"Geocoding completed. Processed: {stats.get('processed', 0)}, Success: {stats.get('success', 0)}, Failed: {stats.get('failed', 0)}")
    except Exception as e:
        error_msg = f"Geocoding task failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()

def run_score_task():
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = "score"
    TASK_STATUS["error"] = None
    try:
        log_task("Starting score recalculation task...")
        update_all_scores()
        log_task("Score recalculation completed.")
    except Exception as e:
        error_msg = f"Scoring task failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None


def run_scrape_v2_task(
    sources: List[str],
    *,
    pages: Optional[int] = 5,
    all_pages: bool = False,
    max_details: Optional[int] = None,
    list_only: bool = False,
    mark_inactive: bool = True,
    prefs: Optional[List[str]] = None,
    delay: Optional[float] = None,
    geocode: bool = True,
    geocode_limit: int = 200,
):
    """Multi-source v2 ingest via SourceAdapter + IngestPipeline."""
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = "scrape-v2"
    TASK_STATUS["error"] = None
    try:
        # NOTE: never `import sources` here — it would shadow the `sources` param
        # and break resolve_scrape_sources (TypeError: module has no len()).
        import sources as _sources_pkg  # noqa: F401 — register adapters
        from ingest.pipeline import IngestPipeline
        from sources.registry import SourceRegistry
        from store.api_queries import use_v2_data_layer
        from store.geocode_v2 import geocode_missing_v2
        from store.repository import Repository
        from store.source_catalog import load_app_config, resolve_scrape_sources

        if not use_v2_data_layer():
            raise RuntimeError(
                "v2 data layer is not active. Set YADOKARIMUT_DATA_LAYER=v2 "
                "or ensure yadokari_mut_v2.db is mounted."
            )

        from sources.http.metrics import get_transfer_metrics
        from sources.http.settings import load_http_settings

        source_ids = resolve_scrape_sources(sources)
        http_settings = load_http_settings()
        log_task(
            f"scrape-v2 start: sources={source_ids} all_pages={all_pages} pages={pages} "
            f"http_mode={http_settings.mode} proxy_enabled={http_settings.proxy_enabled}"
        )

        metrics = get_transfer_metrics()
        metrics.start_session(label=f"scrape-v2:{','.join(source_ids)}")

        config = load_app_config()
        repo = Repository()
        repo.init_db()

        max_pages = None if all_pages else pages
        for sid in source_ids:
            src_cfg = dict((config.get("sources") or {}).get(sid) or {})
            if prefs:
                src_cfg["pref_filter"] = prefs
            if delay is not None:
                src_cfg["delay_seconds"] = delay
            log_task(f"[{sid}] building adapter / pipeline...")
            adapter = SourceRegistry.create(sid, src_cfg)
            pipeline = IngestPipeline(adapter, repo, save_raw=True)
            result = pipeline.run(
                max_pages=max_pages,
                list_only=list_only,
                max_details=max_details,
                mark_inactive=mark_inactive,
            )
            xfer = result.transfer or {}
            log_task(
                f"[{sid}] done list_pages={result.list_pages} list_items={result.list_items} "
                f"detail_ok={result.detail_ok} detail_fail={result.detail_fail} "
                f"errors={len(result.errors)} "
                f"dl_mb={xfer.get('bytes_downloaded_mb', 0)} req={xfer.get('requests', 0)}"
            )
            for err in result.errors[:8]:
                log_task(f"[{sid}] warn: {err}")

        if geocode and not list_only:
            log_task(f"Geocoding missing coordinates (limit={geocode_limit})...")
            gstats = geocode_missing_v2(limit=geocode_limit)
            log_task(
                f"Geocode done: success={gstats.get('success', 0)} "
                f"failed={gstats.get('failed', 0)}"
            )

        session_snap = metrics.end_session()
        sess_total = (session_snap.get("session") or {}).get("total") or {}
        log_task(
            f"scrape-v2 transfer session: "
            f"dl_mb={sess_total.get('bytes_downloaded_mb', 0)} "
            f"up_mb={sess_total.get('bytes_uploaded_mb', 0)} "
            f"requests={sess_total.get('requests', 0)} "
            f"proxy_req={sess_total.get('proxy_requests', 0)}"
        )
        # stash last session on TASK_STATUS for admin UI
        TASK_STATUS["last_transfer"] = session_snap
        log_task("scrape-v2 completed successfully.")
    except Exception as e:
        error_msg = f"scrape-v2 failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()


# Dynamic GeoJSON Builder Helper
def get_geojson_data(params: dict) -> dict:
    properties = db_search_properties(params)
    property_ids = [prop["id"] for prop in properties]
    features_map = {}
    campaigns_map = {}

    # Prefer campaigns already on search results (v2 includes them)
    for prop in properties:
        pid = prop["id"]
        if prop.get("campaigns") is not None:
            campaigns_map[pid] = prop["campaigns"]

    if property_ids:
        try:
            from store.api_queries import use_v2_data_layer
            use_v2 = use_v2_data_layer()
        except ImportError:
            use_v2 = False

        if use_v2:
            from store.repository import Repository
            conn = Repository().connect()
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(property_ids))
            cursor.execute(
                f"SELECT property_id, feature_name FROM property_features WHERE property_id IN ({placeholders})",
                property_ids,
            )
            for row in cursor.fetchall():
                features_map.setdefault(row["property_id"], []).append(row["feature_name"])
            conn.close()
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(property_ids))

            cursor.execute(
                f"SELECT property_id, feature_name FROM property_features WHERE property_id IN ({placeholders})",
                property_ids
            )
            for row in cursor.fetchall():
                pid = row["property_id"]
                fname = row["feature_name"]
                features_map.setdefault(pid, []).append(fname)

            cursor.execute(
                f"""SELECT property_id, campaign_type, title, content, target_period_text, target_condition_text,
                           starts_on, ends_on, target_plan_code,
                           discount_unit, discount_value, discount_max_yen, period_max_days,
                           stay_min_days, stay_max_days, contract_within_days,
                           package_rent_benefit_yen, package_cleaning_benefit_yen,
                           package_fee_benefit_yen, package_total_benefit_yen,
                           structure_source, parse_ok
                    FROM campaigns WHERE property_id IN ({placeholders})""",
                property_ids
            )
            for row in cursor.fetchall():
                pid = row["property_id"]
                if pid in campaigns_map:
                    continue
                c_dict = {k: row[k] for k in row.keys() if k != "property_id"}
                campaigns_map.setdefault(pid, []).append(c_dict)

            for prop in properties:
                pid = prop["id"]
                if pid not in campaigns_map:
                    campaigns_map[pid] = annotate_campaigns(campaigns_map.get(pid, []))
                elif prop.get("campaigns") is None:
                    campaigns_map[pid] = annotate_campaigns(campaigns_map.get(pid, []))

            conn.close()
        
    features = []
    for prop in properties:
        lat = prop["lat"]
        lng = prop["lng"]
        if lat is None or lng is None:
            continue
            
        pid = prop["id"]
        prop_features = features_map.get(pid, [])
        feature_summary = ", ".join(prop_features)
        
        access_raw = prop.get("access_summary") or []
        if isinstance(access_raw, str):
            access_str = access_raw
            access_list = [x.strip() for x in access_raw.split(",") if x.strip()]
        else:
            access_list = list(access_raw)
            access_str = ", ".join(access_list)

        station_list = []
        for a in access_list:
            parts = str(a).split(" ")
            if len(parts) > 1:
                station_list.append(parts[1])
        station_summary = ", ".join(station_list)

        # rent_plans / min_* are already effective-resolved in db_search_properties
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lng, lat]
            },
            "properties": {
                "id": prop["id"],
                "room_id": prop.get("source_property_id") or prop.get("external_id"),
                "source_site": prop.get("source_site"),
                "source_display_name": prop.get("source_display_name"),
                "title": prop["title"],
                "detail_url": prop["detail_url"],
                "address": prop["address"],
                "prefecture_name": prop.get("prefecture_name"),
                "layout": prop["layout"],
                "area_m2": prop["area_m2"],
                "min_daily_rent": prop["min_daily_rent"],
                "min_plan_total": prop["min_plan_total"],
                "min_plan_name": prop["min_plan_name"],
                "min_walk_minutes": prop["min_walk_minutes"],
                "thumbnail_url": prop["thumbnail_url"],
                "images": [
                    (img["image_url"] if isinstance(img, dict) else img)
                    for img in prop.get("images", [])
                ],
                "total_score": prop["total_score"],
                "shortlist_status": prop["shortlist_status"] or "none",
                "access_summary": access_str,
                "feature_summary": feature_summary,
                "station_summary": station_summary,
                "point_text": clean_point_text(prop.get("point_text")),
                "rent_plans": prop.get("rent_plans", []),
                "campaigns": campaigns_map.get(pid, prop.get("campaigns") or [])
            }
        })
        
    return {
        "type": "FeatureCollection",
        "features": features
    }

# ==================== ENDPOINTS ====================

@app.get("/")
def get_map_viewer():
    """Serves the main map viewer application HTML (React index.html or fallback map_viewer.html)."""
    viewer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist", "index.html")
    if os.path.exists(viewer_path):
        return FileResponse(viewer_path)
        
    fallback_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "map_viewer.html")
    if os.path.exists(fallback_path):
        return FileResponse(fallback_path)
        
    raise HTTPException(
        status_code=404, 
        detail="Frontend build not found. Please run 'pnpm build' in the frontend directory."
    )

@app.get("/map.geojson")
@app.get("/api/geojson")
def get_geojson_api(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    plan_code: Optional[str] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[str] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    limit: int = 10000,
):
    """
    Returns property search results directly formatted as a GeoJSON FeatureCollection.
    If map_viewer.html falls back to map.geojson, this serves the same endpoint.
    """
    features_list = None
    if required_features:
        features_list = [f.strip() for f in required_features.split(",") if f.strip()]
        
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "plan_code": plan_code,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": features_list,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
        "limit": limit
    }
    return get_geojson_data(params)

@app.get("/api/properties/{property_id}")
def get_property_detail_api(property_id: str):
    """Gets detailed information for a single property."""
    detail = db_get_property_detail(property_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Property not found")
    return detail

@app.post("/api/properties/{property_id}/shortlist")
def update_shortlist_api(property_id: str, data: ShortlistUpdateRequest):
    """Updates shortlist status (saved, hide, reject, or None)."""
    res = db_update_shortlist(property_id, data.status, data.comment)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

# Admin & Background Tasks endpoints

@app.get("/api/admin/status")
def get_admin_status():
    """Gets statistics and background scheduler/scraper status."""
    data_layer = "v1"
    by_source: dict = {}
    total_properties = 0
    missing_coordinates = 0
    shortlist_stats: dict = {}
    try:
        from store.api_queries import use_v2_data_layer
        from store.repository import Repository

        if use_v2_data_layer():
            data_layer = "v2"
            conn = Repository().connect()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM properties WHERE is_active = 1")
            total_properties = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM properties WHERE is_active = 1 AND (lat IS NULL OR lng IS NULL)"
            )
            missing_coordinates = cursor.fetchone()[0]
            cursor.execute("SELECT status, COUNT(*) FROM shortlists GROUP BY status")
            shortlist_stats = {row[0]: row[1] for row in cursor.fetchall()}
            for row in cursor.execute(
                """
                SELECT source_site, COUNT(*) AS n
                FROM properties WHERE is_active = 1
                GROUP BY source_site
                """
            ):
                by_source[row["source_site"]] = row["n"]
            conn.close()
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM properties")
            total_properties = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM properties WHERE lat IS NULL OR lng IS NULL")
            missing_coordinates = cursor.fetchone()[0]
            cursor.execute("SELECT status, COUNT(*) FROM shortlists GROUP BY status")
            shortlist_stats = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()
    except Exception:
        total_properties = 0
        missing_coordinates = 0
        shortlist_stats = {}

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

    return {
        "task_status": TASK_STATUS,
        "data_layer": data_layer,
        "http": {
            "mode": http_mode,
            "proxy_enabled": proxy_enabled,
        },
        "transfer": transfer,
        "db_stats": {
            "total_properties": total_properties,
            "missing_coordinates": missing_coordinates,
            "shortlist": shortlist_stats,
            "by_source": by_source,
        },
    }


@app.get("/api/admin/sources")
def get_admin_sources():
    """List ingest sources for admin UI (catalog + registry + counts)."""
    from store.api_queries import use_v2_data_layer
    from store.source_catalog import list_source_admin_info

    return {
        "data_layer": "v2" if use_v2_data_layer() else "v1",
        "sources": list_source_admin_info(),
    }


class ScrapeV2Request(BaseModel):
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


@app.post("/api/admin/scrape-v2")
def trigger_scrape_v2(
    background_tasks: BackgroundTasks,
    body: Optional[ScrapeV2Request] = None,
    source: Optional[str] = Query(None, description="Single source id or 'all'"),
    pages: Optional[int] = Query(None),
    all_pages: Optional[bool] = Query(None),
):
    """Trigger multi-source v2 scrape (per-source or bulk)."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Another task is already running: {TASK_STATUS['current_task']}",
        )

    req = body or ScrapeV2Request()
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
        run_scrape_v2_task,
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
        "task": "scrape-v2",
        "sources": resolved,
        "prefs": req.prefs,
        "all_pages": bool(use_all_pages),
        "pages": use_pages,
        "mark_inactive": req.mark_inactive,
    }


@app.post("/api/admin/scrape")
def trigger_scrape(
    background_tasks: BackgroundTasks,
    prefectures: Optional[List[str]] = Query(None),
    all_prefectures: bool = False,
    pages: int = 5,
    all_pages: bool = False,
    delay: float = 1.5,
    classify: bool = True,
):
    """Triggers scraping online data for configured prefectures in the background."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(status_code=409, detail=f"Another task is already running: {TASK_STATUS['current_task']}")
        
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=500, detail="config.json not found")
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    configured_prefectures = list(config["sources"]["bratto"]["prefectures"].keys())
    
    target_prefectures = []
    if all_prefectures:
        target_prefectures = configured_prefectures
    elif prefectures:
        # Validate prefectures
        invalid = [p for p in prefectures if p not in configured_prefectures]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid prefectures: {invalid}. Available: {configured_prefectures}")
        target_prefectures = prefectures
    else:
        raise HTTPException(status_code=400, detail="Must specify prefectures or all_prefectures=true")
        
    max_pages = 999999 if all_pages else pages
    
    background_tasks.add_task(
        run_scrape_task,
        target_prefectures,
        max_pages,
        delay,
        classify
    )
    
    return {"status": "started", "task": "scrape", "target_prefectures": target_prefectures}

@app.post("/api/admin/geocode")
def trigger_geocode(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = 20,
    force: bool = False,
    provider: Optional[str] = None,
    retry_only: bool = False,
    filter_expr: Optional[str] = None,
):
    """Triggers geocoding properties missing coordinates in the database."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(status_code=409, detail=f"Another task is already running: {TASK_STATUS['current_task']}")
        
    background_tasks.add_task(
        run_geocode_task,
        limit,
        force,
        provider,
        retry_only,
        filter_expr
    )
    return {"status": "started", "task": "geocode"}

@app.post("/api/admin/score")
def trigger_score(background_tasks: BackgroundTasks):
    """Triggers recalculation of commuting scores."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(status_code=409, detail=f"Another task is already running: {TASK_STATUS['current_task']}")
        
    background_tasks.add_task(run_score_task)
    return {"status": "started", "task": "score"}

def run_scheduled_scraping_job():
    log_task("Scheduled daily scrape triggered.")
    try:
        from store.api_queries import use_v2_data_layer

        if use_v2_data_layer():
            # v2: all available sources, limited pages for nightly job
            run_scrape_v2_task(
                sources=["all"],
                pages=5,
                all_pages=False,
                max_details=None,
                list_only=False,
                mark_inactive=True,
                geocode=True,
                geocode_limit=300,
            )
            return
    except Exception as e:
        log_task(f"v2 scheduled scrape failed, falling back to v1: {e}")

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    if not os.path.exists(config_path):
        log_task("Scheduled job failed: config.json not found.")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    configured_prefectures = list(config["sources"]["bratto"]["prefectures"].keys())

    run_scrape_task(
        prefectures=configured_prefectures,
        max_pages=5,
        delay=1.5,
        classify=True,
    )

# StaticFiles はエンドポイント定義の最後に配置（/api/copilotkit への到達を保証するため）
from fastapi.staticfiles import StaticFiles
frontend_dist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
if os.path.exists(frontend_dist_path):
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
