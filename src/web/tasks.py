"""バックグラウンドタスクランナ (scrape / geocode / rotation) と状態共有。

TASK_STATUS は admin UI (/api/admin/status)・409 判定・ログ蓄積の正本で、
web 層の各ルータと同一オブジェクトを共有する。旧 web_server.py から
挙動を変更せず移設している。

タスク前後の TASK_STATUS 遷移 (running 設定 / idle 復元) は acquire_task に
一元化し、実行中排他の 409 判定は require_task_idle dependency として
各ルータから使う。
"""

from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException

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


class TaskBusyError(Exception):
    """acquire_task が競合検知で送出 (呼び出し側でスキップ/409を判断する)."""

    def __init__(self, current_task: str | None):
        self.current_task = current_task


# rotation ジョブが保持中のスロットで run_scrape_task を呼ぶ入れ子実行の深さ。
# 深さ 0 でない間の再取得は競合ではなく入れ子として通し、idle 復元は深さが
# 0 に戻った時のみ行う (RLock 相当。単一書き込みは TASK_STATUS 排他の前提と一致)。
# 入れ子から抜ける際は current_task を保持者 (rotation:<id>) に戻す。
_task_lock_depth = 0


@contextmanager
def acquire_task(name: str):
    """タスク実行区間の TASK_STATUS 遷移を一元化する.

    取得に成功すると status=running/current_task/error=None を設定し、
    抜ける際に status=idle/current_task=None/last_run を必ず復元する。
    last_result は関数本体側の責務(geocode/rotation は設定しない)なので
    ここでは触らない。
    """
    global _task_lock_depth
    if TASK_STATUS["status"] == "running" and _task_lock_depth == 0:
        raise TaskBusyError(TASK_STATUS["current_task"])
    prev_task = TASK_STATUS["current_task"]
    TASK_STATUS["status"] = "running"
    TASK_STATUS["current_task"] = name
    TASK_STATUS["error"] = None
    _task_lock_depth += 1
    try:
        yield
    finally:
        _task_lock_depth -= 1
        if _task_lock_depth == 0:
            TASK_STATUS["status"] = "idle"
            TASK_STATUS["current_task"] = None
            TASK_STATUS["last_run"] = datetime.now().isoformat()
        else:
            TASK_STATUS["current_task"] = prev_task


def require_task_idle():
    """実行中タスク排他の 409 ガード唯一実装 (router から Depends で使用)."""
    if TASK_STATUS["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Another task is already running: {TASK_STATUS['current_task']}",
        )


def run_geocode_task(limit: Optional[int], force: bool, provider: Optional[str], retry_only: bool):
    with acquire_task("geocode"):
        try:
            from store.geocode_v2 import (
                format_geocode_warnings,
                geocode_missing_v2,
                geocode_result_warnings,
            )

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
            # タスク自体は正常終了扱い(geocode は後処理ベストエフォート)。
            # 文言は geocode_v2 の正本 formatter から生成
            for line in format_geocode_warnings(geocode_result_warnings(stats)):
                log_task(line)
        except Exception as e:
            error_msg = f"Geocoding task failed: {str(e)}"
            log_task(error_msg)
            TASK_STATUS["error"] = error_msg


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
    with acquire_task("scrape"):
        try:
            from ingest.pipeline import IngestPipeline
            from ingest.source_config import resolve_source_adapter_config
            from sources.registry import SourceRegistry
            from store.geocode_v2 import (
                format_geocode_warnings,
                geocode_missing_v2,
                geocode_result_warnings,
            )
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
                src_cfg = resolve_source_adapter_config(
                    sid, pref_filter=prefs, delay=delay, config=config
                )
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
                # スクレイプ後 geocode も単独タスクと同一の警告を出す
                # (握りつぶし解消。文言は正本 formatter 経由)
                for line in format_geocode_warnings(geocode_result_warnings(gstats)):
                    log_task(line)

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


def run_embedding_sync(wait_secs: int = 120):
    """意味検索 embedding の日次差分同期ジョブ(Batch API 経路・docs/embedding-batch-api-plan.md)。

    未カバー / search_text_hash 不一致の可視物件を Gemini Batch API へ submit し、
    bounded 待機(既定 120 秒)内に完了した分を適用する(実体は
    store.embeddings_batch.run_batch_sync)。未完了分は Gemini 側ジョブが保持され、
    翌日の本ジョブ / CLI 再実行の冒頭で適用される。limit は廃止(D3: batch は
    レート制限リスクがなく pending の取りこぼしが無い)。外部 API 呼び出しを含むが
    DB アクセスは読み取り+property_embeddings への upsert+app_settings 1 行のみのため
    TASK_STATUS の実行中排他には参加させない(scrape と同時実行しても安全・
    失敗はログに残すだけ)。
    """
    try:
        from store.embeddings_batch import run_batch_sync

        stats = run_batch_sync(wait_secs=wait_secs)
        log_task(f"embedding sync: {stats}")
    except Exception as e:
        log_task(f"embedding sync failed: {e}")


def run_media_sync(limit: int | None = None):
    """メディア画像の日次取り込みジョブ(docs/media-storage-rustfs-plan.md §2.6)。

    property_images の pending 行を rustfs クラスタ代表ストアへ格納する
    (実体は store.media.backfill_media)。embedding sync と同じく外部リソース
    (画像CDN・S3)を叩くが DB 書込は行単位の小更新のみのため TASK_STATUS の
    実行中排他には参加させない(失敗はログに残すだけ)。未設定 env なら
    backfill_media が disabled を返して no-op。
    """
    try:
        import os

        from store.media import backfill_media

        if limit is None:
            limit = int(os.environ.get("MEDIA_SYNC_LIMIT", "5000"))
        stats = backfill_media(limit=limit)
        log_task(f"media sync: {stats}")
    except Exception as e:
        log_task(f"media sync failed: {e}")


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

    # busy 事前チェックとモジュール import は acquire の前に置く (import 失敗時に
    # running にしない/エラーを設定しない、という現行挙動を保存するため)
    try:
        with acquire_task(f"rotation:{source_id}"):
            try:
                repo = Repository()
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
    except TaskBusyError:
        log_task("skipped: another task running")
