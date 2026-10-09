"""FastAPI アプリの組立 (create_app) と lifespan。

旧 src/web_server.py 単一モジュール (30 超エンドポイント + タスク実行 +
スケジューラ) を web パッケージへ分割した際の組立点。互換入口は
src/web_server.py シム (`from web.app import app`)。
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

# サーバ起動の早期に .env を読む。module-level load_dotenv を持つモジュールは
# import グラフに含めない規約のため、ここが唯一の読み込み点になる
load_dotenv()

# CopilotKit + LangGraph AG-UI
from agent.patches import apply_agent_patches
from agent_service import _build_graph, _cleanup_mcp
from copilotkit import LangGraphAGUIAgent

from web import REPO_ROOT
from web.rotation_jobs import _rotation_source_config
from web.tasks import log_task, run_embedding_sync, run_media_sync, run_rotation_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時のデータ整備(スキーマ保証は Alembic = db-init / deploy 时の役割):
    # 機能カテゴリ辞書の差分同期 + 前プロセス残りの stale run 掃除
    try:
        from store.pg import open_connection
        from store.repository import Repository
        from store.schema import sync_feature_dictionary

        with open_connection() as conn:
            sync_feature_dictionary(conn)
        try:
            aborted = Repository().fail_stale_running_runs()
            if aborted:
                logging.getLogger(__name__).info(
                    "Aborted %d stale scrape run/target row(s) left by a previous process.",
                    aborted,
                )
        except Exception as cleanup_err:
            logging.getLogger(__name__).warning(
                "stale scrape run cleanup failed: %s", cleanup_err
            )
        logging.getLogger(__name__).info("DB startup checks done.")
    except Exception as e:
        print(f"DB startup checks skipped/failed: {e}")

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
                scheduler.add_job(
                    lambda sid=sid: run_rotation_job(sid),
                    trigger,
                    id=f"rotation_{sid}",
                    name=f"Rotation Scrape: {sid}",
                )
                registered_any = True
                log_task(f"Rotation job registered: {sid} cron='{cron_expr}'")

            # 意味検索 embedding の日次差分同期 (PG移行 Phase 7a)。
            # 既定 06:00 = unionmonthly 深夜ローテーション(05時)後。
            embedding_cron = os.environ.get("EMBEDDING_SYNC_CRON", "0 6 * * *")
            efields = embedding_cron.split()
            if len(efields) != 5:
                log_task(
                    f"Invalid cron expression for embedding sync: '{embedding_cron}'. Job not registered."
                )
            else:
                scheduler.add_job(
                    run_embedding_sync,
                    CronTrigger(
                        minute=efields[0],
                        hour=efields[1],
                        day=efields[2],
                        month=efields[3],
                        day_of_week=efields[4],
                    ),
                    id="embedding_sync",
                    name="Embedding Sync (semantic search)",
                )
                registered_any = True
                log_task(f"Embedding sync job registered: cron='{embedding_cron}'")

            # メディア画像の日次取り込み (docs/media-storage-rustfs-plan.md §2.6)。
            # 既定 04:30 = rotation(05時)・embedding sync(06:00)より前の閑帯。
            media_cron = os.environ.get("MEDIA_SYNC_CRON", "30 4 * * *")
            mfields = media_cron.split()
            if len(mfields) != 5:
                log_task(
                    f"Invalid cron expression for media sync: '{media_cron}'. Job not registered."
                )
            else:
                scheduler.add_job(
                    run_media_sync,
                    CronTrigger(
                        minute=mfields[0],
                        hour=mfields[1],
                        day=mfields[2],
                        month=mfields[3],
                        day_of_week=mfields[4],
                    ),
                    id="media_sync",
                    name="Media Sync (rustfs)",
                )
                registered_any = True
                log_task(f"Media sync job registered: cron='{media_cron}'")
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


def create_app() -> FastAPI:
    """FastAPI アプリを組み立てる。

    ルータの登録順は旧 web_server.py のエンドポイント定義順を再現する。
    FastAPI の OpenAPI paths は登録順に出力されるため、frontend/openapi.json
    (scripts/export_openapi.py) を byte 同値に保つうえで順序の維持が必須。
    """
    # reasoning_content 連携の monkey-patch。旧来は agent_service の import
    # 副作用だったものを明示適用に分離した (agent/patches.py 参照)
    apply_agent_patches()

    app = FastAPI(
        title="YadokariMut API Server",
        description="Web API for YadokariMut Monthly Mansion Explorer",
        version="2.0.0",
        lifespan=lifespan,
    )

    from web.routers import (
        admin,
        agent,
        analysis,
        buildings_geojson,
        chat,
        export,
        fe_settings,
        geojson,
        media,
        properties,
        rotation,
    )

    app.include_router(agent.router)
    app.include_router(chat.router)
    app.include_router(fe_settings.router)
    app.include_router(geojson.router)
    # 建物単位 GeoJSON (Phase B1・docs/building-aggregation-design.md §6.1)。
    # 新設のため部屋単位 geojson の直後に登録 (既存 paths の相対順は不変)
    app.include_router(buildings_geojson.router)
    app.include_router(export.router)
    # 旧定義順 (detail → price-trend → shortlist) を再現するため、properties
    # の shortlist は別 router インスタンス (挙動差なし / OpenAPI 順序維持用)
    app.include_router(properties.router)
    app.include_router(analysis.router)
    app.include_router(properties.shortlist_router)
    # 旧定義順 (status..scrape → rotation 一式 → geocode) を再現するため
    # admin の geocode も別 router インスタンスに分離
    app.include_router(admin.router)
    app.include_router(rotation.router)
    app.include_router(admin.geocode_router)
    # メディア配信 (rustfs プロキシ・docs/media-storage-rustfs-plan.md §2.8)。
    # 既存 paths の相対順は不変のまま末尾側へ追加。
    app.include_router(media.router)

    # ── Vector tiles (PMTiles → ZXY 配信) ──
    # pmtiles が未導入の環境でもサーバ全体の起動を壊さないよう guarded import
    # (依存は requirements.txt に追加済み。静的マウントより先に登録する)
    try:
        from tiles import router as tiles_router

        app.include_router(tiles_router)
    except Exception as e:
        print(f"tiles router registration skipped: {e}")

    # StaticFiles はエンドポイント定義の最後に配置（/api/copilotkit への到達を保証するため）
    from fastapi.staticfiles import StaticFiles

    frontend_dist_path = os.path.join(REPO_ROOT, "frontend", "dist")
    if os.path.exists(frontend_dist_path):
        app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")

    return app


app = create_app()
