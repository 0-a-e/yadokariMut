"""バックグラウンドタスクランナ (scrape / geocode / rotation) と状態共有。

TASK_STATUS は admin UI (/api/admin/status)・409 判定・ログ蓄積の正本で、
web 層の各ルータと同一オブジェクトを共有する。旧 web_server.py から
挙動を変更せず移設している。
"""

from datetime import datetime
from typing import List, Optional

from web.rotation_jobs import _rotation_failure_policy, _rotation_pref_catalog

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


def run_geocode_task(limit: Optional[int], force: bool, provider: Optional[str], retry_only: bool):
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = "geocode"
    TASK_STATUS["error"] = None
    try:
        from store.geocode_v2 import geocode_missing_v2

        log_task("Starting batch geocoding task (v2)...")
        stats = geocode_missing_v2(
            limit=limit, provider=provider, force=force, retry_only=retry_only
        )
        log_task(
            f"Geocoding completed. Processed: {stats.get('processed', 0)}, "
            f"Success: {stats.get('success', 0)}, Failed: {stats.get('failed', 0)}, "
            f"Skipped: {stats.get('skipped', 0)}, Unchanged: {stats.get('unchanged', 0)}"
        )
        # spec §3.5 / §3.8: 障害スキップ・サーキットブレーカ打ち切りは警告のみで
        # タスク自体は正常終了扱い(geocode は後処理ベストエフォート)
        if stats.get("skipped"):
            log_task(
                f"warn: {stats['skipped']} 件はプロバイダ障害等のため記録なしスキップ。"
                "時間を置いて再実行してください"
            )
        if stats.get("aborted"):
            log_task(
                "warn: geocode aborted by circuit breaker "
                f"after {stats.get('skipped', 0)} consecutive provider system errors"
            )
    except Exception as e:
        error_msg = f"Geocoding task failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()


def run_scrape_task(
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
    TASK_STATUS["current_task"] = "scrape"
    TASK_STATUS["error"] = None
    try:
        from ingest.pipeline import IngestPipeline
        from scrape_settings import apply_to_source_config
        from sources.registry import SourceRegistry
        from store.geocode_v2 import geocode_missing_v2
        from store.repository import Repository
        from store.source_catalog import load_app_config, resolve_scrape_sources

        from sources.http.metrics import get_transfer_metrics
        from sources.http.settings import load_http_settings

        source_ids = resolve_scrape_sources(sources)
        http_settings = load_http_settings()
        log_task(
            f"scrape start: sources={source_ids} all_pages={all_pages} pages={pages} "
            f"http_mode={http_settings.mode} proxy_enabled={http_settings.proxy_enabled}"
            + (" rotation=true" if rotation else "")
        )

        metrics = get_transfer_metrics()
        metrics.start_session(label=f"scrape:{','.join(source_ids)}")

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
            # DB保存のソース別上書き(取得間隔/制限時クールダウン)を適用。
            # run 時の明示指定(delay パラメタ)がさらに優先
            src_cfg = apply_to_source_config(sid, src_cfg)
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
            f"scrape transfer session: "
            f"dl_mb={sess_total.get('bytes_downloaded_mb', 0)} "
            f"up_mb={sess_total.get('bytes_uploaded_mb', 0)} "
            f"requests={sess_total.get('requests', 0)} "
            f"proxy_req={sess_total.get('proxy_requests', 0)}"
        )
        # stash last session on TASK_STATUS for admin UI
        TASK_STATUS["last_transfer"] = session_snap
        if overall == "error":
            error_msg = "scrape finished with ERRORS: " + "; ".join(fatal_notes)
            log_task(error_msg)
            TASK_STATUS["error"] = error_msg
            TASK_STATUS["last_result"] = "error"
        elif overall == "partial":
            log_task("scrape completed with warnings (partial).")
            TASK_STATUS["last_result"] = "partial"
        else:
            log_task("scrape completed successfully.")
            TASK_STATUS["last_result"] = "ok"
    except Exception as e:
        error_msg = f"scrape failed: {str(e)}"
        log_task(error_msg)
        TASK_STATUS["error"] = error_msg
        TASK_STATUS["last_result"] = "error"
    finally:
        TASK_STATUS["status"] = "idle"
        TASK_STATUS["current_task"] = None
        TASK_STATUS["last_run"] = datetime.now().isoformat()


def run_rotation_job(source_id: str):
    """県ローテーション・スクレイプジョブ（スケジューラ / 手動API共通）.

    daily_limit / default_est は実行開始時に rotation_settings の実効値を
    解決する(保存値 > コード既定)。DB 変更は再起動不要で次回実行から反映。
    """
    if TASK_STATUS["status"] == "running":
        log_task("skipped: another task running")
        return

    try:
        from ingest.rotation import RotationPlanner
        from rotation_settings import resolve_effective_limits
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

        limits = resolve_effective_limits(source_id)
        pref_catalog = _rotation_pref_catalog(source_id)
        planner = RotationPlanner(repo)
        batch = planner.plan(
            source_id,
            pref_catalog=pref_catalog,
            daily_limit=limits["daily_limit"],
            default_est=limits["default_est"],
            **_rotation_failure_policy(),
        )
        log_task(
            f"rotation[{source_id}]: "
            f"limits(daily={limits['daily_limit']}, est={limits['default_est']}) "
            f"batch={batch.prefs} est={batch.est_items} "
            f"unlimited={batch.unlimited} reason={batch.reason or '-'}"
        )
        if not batch.prefs:
            return
        run_scrape_task(
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
