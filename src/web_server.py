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
            repo = Repository()
            repo.init_db()
            try:
                aborted = repo.fail_stale_running_runs()
                if aborted:
                    logging.getLogger(__name__).info(
                        "Aborted %d stale scrape run(s) left by a previous process.",
                        aborted,
                    )
            except Exception as cleanup_err:
                logging.getLogger(__name__).warning(
                    "stale scrape run cleanup failed: %s", cleanup_err
                )
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

    # スケジューラー起動処理（県ローテーション・スクレイプ）
    enable_scheduler = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    if enable_scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        try:
            scheduler = BackgroundScheduler()
            registered_any = False
            for scfg in _rotation_source_config():
                sid = scfg["id"]
                cron_expr = scfg["cron"]
                fields = cron_expr.split()
                if len(fields) != 5:
                    log_task(
                        f"Invalid cron expression for rotation[{sid}]: "
                        f"'{cron_expr}'. Job not registered."
                    )
                    continue
                trigger = CronTrigger(
                    minute=fields[0],
                    hour=fields[1],
                    day=fields[2],
                    month=fields[3],
                    day_of_week=fields[4],
                )
                lim = scfg["daily_limit"]
                est = scfg["default_est"]
                scheduler.add_job(
                    lambda sid=sid, lim=lim, est=est: run_rotation_job(
                        sid, daily_limit=lim, default_est=est
                    ),
                    trigger,
                    id=f"rotation_{sid}",
                    name=f"Rotation Scrape: {sid}",
                )
                registered_any = True
                log_task(
                    f"Rotation job registered: {sid} cron='{cron_expr}' "
                    f"daily_limit={lim}"
                )
            if registered_any:
                scheduler.start()
                log_task("Rotation scheduler started successfully.")
            else:
                log_task("No rotation sources configured. Scheduler not started.")
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


# ── Frontend default settings (map layer v2 設計 doc §2) ──
@app.get("/api/fe-settings")
def get_frontend_settings():
    """Return saved frontend default settings (layers / global). Empty when unset."""
    from fe_settings import get_fe_settings

    return get_fe_settings()


@app.post("/api/fe-settings")
def save_frontend_settings(update: dict):
    """Partial-merge save of frontend default settings.

    - `{"layers": {"<id>": {"defaultOpacity": 0.6}}}` → そのキーのみ上書き
    - null 送信でその保存済みキー/レイヤを削除(カタログ既定へ戻す)
    - 返り値は保存後の全体設定
    """
    from fe_settings import save_fe_settings

    try:
        return save_fe_settings(update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Global status tracking for background operations
TASK_STATUS = {
    "status": "idle",  # "idle" or "running"
    "current_task": None,
    "last_run": None,
    "error": None,
    # Outcome of the last finished task: "ok" / "partial" / "error" (None until first run)
    "last_result": None,
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


# ============================================================
# 県ローテーション・スクレイプ（夜間一括ジョブの後継）
# ============================================================
def _rotation_source_config() -> List[dict]:
    """Resolve rotation schedule config from env.

    Returns [{id, cron, daily_limit, default_est}] in ROTATION_SOURCES order.
    - ROTATION_SOURCES: comma separated source ids (default "bratto,unionmonthly")
    - ROTATION_CRON_{SID}: per-source cron (defaults below / "0 8,20 * * *")
    - ROTATION_DAILY_LIMIT_{SID}: per-source daily item limit (default 500)
    - ROTATION_DEFAULT_EST: default per-prefecture item estimate (default 60)
    """
    raw = os.environ.get("ROTATION_SOURCES", "bratto,unionmonthly")
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    try:
        default_est = int(os.environ.get("ROTATION_DEFAULT_EST") or 60)
    except ValueError:
        default_est = 60
    default_crons = {
        "bratto": "0 2,14 * * *",
        "unionmonthly": "0 5,17 * * *",
    }
    out: List[dict] = []
    for sid in ids:
        upper = sid.upper()
        cron = os.environ.get(f"ROTATION_CRON_{upper}") or default_crons.get(
            sid, "0 8,20 * * *"
        )
        try:
            daily_limit = int(os.environ.get(f"ROTATION_DAILY_LIMIT_{upper}") or 500)
        except ValueError:
            daily_limit = 500
        out.append(
            {
                "id": sid,
                "cron": cron,
                "daily_limit": daily_limit,
                "default_est": default_est,
            }
        )
    return out


def _rotation_failure_policy() -> dict:
    """Resolve failure-backoff policy from env.

    - ROTATION_FAILURE_MAX: consecutive failures before cooldown (default 3)
    - ROTATION_FAILURE_COOLDOWN_HOURS: cooldown window from the last attempt (default 48)
    """
    try:
        max_failures = int(os.environ.get("ROTATION_FAILURE_MAX", "3"))
    except ValueError:
        max_failures = 3
    try:
        cooldown_hours = int(os.environ.get("ROTATION_FAILURE_COOLDOWN_HOURS", "48"))
    except ValueError:
        cooldown_hours = 48
    return {
        "max_consecutive_failures": max_failures,
        "failure_cooldown_hours": cooldown_hours,
    }


def _rotation_pref_catalog(source_id: str) -> List[str]:
    """Prefecture slugs eligible for rotation.

    config.json の sources.<id>.prefectures を優先し、無ければアダプタの
    discover_list_targets() にフォールバックする。
    """
    from store.source_catalog import load_app_config

    cfg = (load_app_config().get("sources") or {}).get(source_id) or {}
    pref_catalog = list((cfg.get("prefectures") or {}).keys())
    if pref_catalog:
        return pref_catalog
    try:
        import sources  # noqa: F401 — register adapters
        from sources.registry import SourceRegistry

        clean = {k: v for k, v in (cfg or {}).items() if k != "pref_filter"}
        adapter = SourceRegistry.create(source_id, clean)
        pref_catalog = [
            t.prefecture_slug or t.key for t in adapter.discover_list_targets()
        ]
    except Exception as e:
        log_task(f"rotation[{source_id}]: pref catalog discovery failed: {e}")
        pref_catalog = []
    return pref_catalog


def run_rotation_job(source_id: str, *, daily_limit: int = 500, default_est: int = 60):
    """県ローテーション・スクレイプジョブ（スケジューラ / 手動API共通）."""
    if TASK_STATUS["status"] == "running":
        log_task("skipped: another task running")
        return

    try:
        from ingest.rotation import RotationPlanner
        from store.repository import Repository
    except Exception as e:
        log_task(f"rotation[{source_id}]: rotation module unavailable: {e}")
        return

    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = f"rotation:{source_id}"
    TASK_STATUS["error"] = None
    try:
        repo = Repository()
        repo.init_db()

        pref_catalog = _rotation_pref_catalog(source_id)
        planner = RotationPlanner(repo)
        batch = planner.plan(
            source_id,
            pref_catalog=pref_catalog,
            daily_limit=daily_limit,
            default_est=default_est,
            **_rotation_failure_policy(),
        )
        log_task(
            f"rotation[{source_id}]: batch={batch.prefs} est={batch.est_items} "
            f"unlimited={batch.unlimited} reason={batch.reason or '-'}"
        )
        if not batch.prefs:
            return
        run_scrape_v2_task(
            sources=[source_id],
            all_pages=True,
            pages=5,
            max_details=None,
            list_only=False,
            mark_inactive=True,
            prefs=batch.prefs,
            geocode=True,
            geocode_limit=100,
            rotation=True,
        )
    except Exception as e:
        error_msg = f"rotation job failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()


def _rotation_queue_key(slug: str, states_by_slug: dict) -> tuple:
    """Sort key matching RotationPlanner's queue order.

    rotation.py 仕様: last_full_ok_at NULLS FIRST → 昇順、
    known_total 昇順（None は最大）、slug 昇順。
    """
    st = states_by_slug.get(slug) or {}
    last_full = st.get("last_full_ok_at")
    known_total = st.get("known_total")
    last_full_key = (1, str(last_full)) if last_full else (0, "")
    known_key = (1, int(known_total)) if known_total is not None else (2, 0)
    return (last_full_key, known_key, slug)

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
    rotation: bool = False,
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
            + (" rotation=true" if rotation else "")
        )

        metrics = get_transfer_metrics()
        metrics.start_session(label=f"scrape-v2:{','.join(source_ids)}")

        config = load_app_config()
        repo = Repository()
        repo.init_db()
        # 直列実行の保証(TASK_STATUSロック)より前に生き残っている running 行は
        # 前プロセスの残骸。admin UI の is_running ゴースト表示を防ぐため打ち切る
        try:
            repo.fail_stale_running_runs()
        except Exception as cleanup_err:
            log_task(f"warn: stale scrape run cleanup failed: {cleanup_err}")

        max_pages = None if all_pages else pages
        # Aggregate per-source outcomes: escalate to "error" only when a whole
        # source run failed (every target errored — e.g. site unreachable /
        # IP-blocked). Mere detail-level failures stay "partial" warnings.
        overall = "ok"
        fatal_notes: list[str] = []
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
                extra_run_meta=({"rotation": True} if rotation else None),
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
            if result.status == "error":
                overall = "error"
                failed_targets = sum(
                    1 for tr in result.by_target.values() if tr.status == "error"
                )
                fatal_notes.append(
                    f"{sid}: {failed_targets}/{len(result.by_target)} 県すべて失敗 "
                    f"(list_items={result.list_items})"
                )
            elif result.status == "partial" and overall == "ok":
                overall = "partial"
            # rotation_state 更新（手動実行でも反映。失敗しても継続）
            try:
                from ingest.rotation import RotationPlanner

                RotationPlanner(repo).record_result(sid, result.by_target)
            except Exception as rot_err:
                log_task(f"[{sid}] warn: rotation_state update failed: {rot_err}")

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
        if overall == "error":
            error_msg = "scrape-v2 finished with ERRORS: " + "; ".join(fatal_notes)
            log_task(error_msg)
            TASK_STATUS["error"] = error_msg
            TASK_STATUS["last_result"] = "error"
        elif overall == "partial":
            log_task("scrape-v2 completed with warnings (partial).")
            TASK_STATUS["last_result"] = "partial"
        else:
            log_task("scrape-v2 completed successfully.")
            TASK_STATUS["last_result"] = "ok"
    except Exception as e:
        error_msg = f"scrape-v2 failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
        TASK_STATUS["last_result"] = "error"
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
                "is_active": bool(prop.get("is_active", True)),
                "last_seen_at": prop.get("last_seen_at"),
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

    # Recent run rows straight from the DB: unlike in-memory TASK_STATUS these
    # survive restarts, so e.g. a failed nightly rotation run stays visible.
    recent_runs: list = []
    if data_layer == "v2":
        try:
            from store.repository import Repository

            recent_runs = Repository().recent_scrape_runs(limit=8)
        except Exception:
            recent_runs = []

    return {
        "task_status": TASK_STATUS,
        "data_layer": data_layer,
        "recent_runs": recent_runs,
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


@app.get("/api/admin/rotation")
def get_rotation_status():
    """県ローテーション・スケジュールの状態（admin UI 用・読み取り専用）."""
    from store.pref_master import pref_display_name
    from store.source_catalog import SOURCE_CATALOG

    display_names = {
        e.get("id"): (e.get("display_name") or e.get("id"))
        for e in SOURCE_CATALOG
    }

    repo = None
    try:
        from store.repository import Repository

        repo = Repository()
    except Exception:
        repo = None

    planner_cls = None
    try:
        from ingest.rotation import RotationPlanner

        planner_cls = RotationPlanner
    except Exception:
        planner_cls = None

    sources_out: List[dict] = []
    for scfg in _rotation_source_config():
        sid = scfg["id"]
        pref_catalog = _rotation_pref_catalog(sid)

        used_today = 0
        states: List[dict] = []
        running: set = set()
        if repo is not None:
            try:
                # Seed first so the very first call after deploy also shows known_total
                repo.seed_rotation_state(sid, pref_catalog)
            except Exception:
                pass
            try:
                used_today = repo.rotation_usage_today(sid) or 0
            except Exception:
                used_today = 0
            try:
                states = repo.load_rotation_states(sid) or []
            except Exception:
                states = []
            try:
                running = repo.running_scrape_targets(sid) or set()
            except Exception:
                running = set()

        states_by_slug = {
            s.get("prefecture_slug"): s
            for s in states
            if isinstance(s, dict) and s.get("prefecture_slug")
        }

        # queue_position は planner.plan と同じソートキーで整列
        order = sorted(
            pref_catalog, key=lambda slug: _rotation_queue_key(slug, states_by_slug)
        )

        next_batch = {"prefs": [], "est_items": 0, "unlimited": False, "reason": ""}
        failure_policy = _rotation_failure_policy()
        if planner_cls is not None and repo is not None:
            try:
                planner = planner_cls(repo)
                batch = planner.plan(
                    sid,
                    pref_catalog=pref_catalog,
                    daily_limit=scfg["daily_limit"],
                    default_est=scfg["default_est"],
                    **failure_policy,
                )
                next_batch = {
                    "prefs": list(batch.prefs),
                    "est_items": batch.est_items,
                    "unlimited": bool(batch.unlimited),
                    "reason": batch.reason or "",
                }
            except Exception as e:
                next_batch = {"prefs": [], "reason": str(e)}

        prefs_out = []
        for pos, slug in enumerate(order, start=1):
            st = states_by_slug.get(slug) or {}
            try:
                failures = int(st.get("consecutive_failures") or 0)
            except (TypeError, ValueError):
                failures = 0
            from ingest.rotation import is_suppressed

            prefs_out.append(
                {
                    "slug": slug,
                    "name": pref_display_name(slug),
                    "known_total": st.get("known_total"),
                    "last_full_ok_at": st.get("last_full_ok_at"),
                    "last_run_at": st.get("last_run_at"),
                    "consecutive_failures": failures,
                    "suppressed": is_suppressed(st, now=datetime.now(), **failure_policy),
                    "is_running": slug in running,
                    "queue_position": pos,
                }
            )

        sources_out.append(
            {
                "id": sid,
                "display_name": display_names.get(sid, sid),
                "cron": scfg["cron"],
                "daily_limit": scfg["daily_limit"],
                "used_today": used_today,
                "default_est": scfg["default_est"],
                "next_batch": next_batch,
                "prefs": prefs_out,
            }
        )

    return {"sources": sources_out}


class RotationRunRequest(BaseModel):
    """Body for manual rotation run."""

    source: str


@app.post("/api/admin/rotation/run")
def trigger_rotation_run(background_tasks: BackgroundTasks, body: RotationRunRequest):
    """手動で県ローテーション・スクレイプを1ソース分実行する."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Another task is already running: {TASK_STATUS['current_task']}",
        )

    cfg = {c["id"]: c for c in _rotation_source_config()}
    if body.source not in cfg:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown rotation source: {body.source}. "
            f"Available: {sorted(cfg.keys())}",
        )

    scfg = cfg[body.source]
    background_tasks.add_task(
        run_rotation_job,
        body.source,
        daily_limit=scfg["daily_limit"],
        default_est=scfg["default_est"],
    )
    return {"status": "started", "task": "rotation", "source": body.source}


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

# StaticFiles はエンドポイント定義の最後に配置（/api/copilotkit への到達を保証するため）
from fastapi.staticfiles import StaticFiles
frontend_dist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
if os.path.exists(frontend_dist_path):
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
