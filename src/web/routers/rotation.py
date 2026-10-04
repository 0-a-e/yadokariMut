"""県ローテーション管理 API (status / run / settings)。"""

from datetime import datetime
from typing import List

from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, HTTPException

import api_models
from web.rotation_jobs import (
    _rotation_failure_policy,
    _rotation_pref_catalog,
    _rotation_queue_key,
    _rotation_source_config,
)
from web.tasks import TASK_STATUS, run_rotation_job

router = APIRouter()


@router.get("/api/admin/rotation", response_model=api_models.RotationStatusResponse)
def get_rotation_status():
    """県ローテーション・スケジュールの状態（admin UI 用・読み取り専用）."""
    from store.pref_master import pref_display_name
    from store.source_catalog import SOURCE_CATALOG

    from rotation_settings import resolve_effective_limits

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
        limits = resolve_effective_limits(sid)
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
                    daily_limit=limits["daily_limit"],
                    default_est=limits["default_est"],
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
                "daily_limit": limits["daily_limit"],
                "used_today": used_today,
                "default_est": limits["default_est"],
                "next_batch": next_batch,
                "prefs": prefs_out,
            }
        )

    return {"sources": sources_out}


class RotationRunRequest(BaseModel):
    """Body for manual rotation run."""

    source: str


@router.post(
    "/api/admin/rotation/run",
    response_model=api_models.RotationRunStartResponse,
)
def trigger_rotation_run(background_tasks: BackgroundTasks, body: RotationRunRequest):
    """手動で県ローテーション・スクレイプを1ソース分実行する.

    daily_limit / default_est はジョブ側で実行時に解決する。
    """
    if TASK_STATUS["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Another task is already running: {TASK_STATUS['current_task']}",
        )

    cfg_ids = [c["id"] for c in _rotation_source_config()]
    if body.source not in cfg_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown rotation source: {body.source}. "
            f"Available: {sorted(cfg_ids)}",
        )

    background_tasks.add_task(run_rotation_job, body.source)
    return {"status": "started", "task": "rotation", "source": body.source}


@router.get(
    "/api/admin/rotation-settings", response_model=api_models.RotationSettingsResponse
)
def get_admin_rotation_settings():
    """ソース別ローテーション設定(日次上限/既定1県件数)の実効値を返す。"""
    from rotation_settings import effective_rotation_settings

    return effective_rotation_settings()


@router.post(
    "/api/admin/rotation-settings", response_model=api_models.RotationSettingsResponse
)
def save_admin_rotation_settings(update: dict):
    """ソース別ローテーション設定の部分マージ保存(null で該当キーを既定へ戻す)。

    ボディは意図的に pydantic モデル化しない (update: dict)。null = 保存済み
    キーの削除 (既定へ戻す) という部分マージ契約を保持するためで、値の
    バリデーションは rotation_settings 側で行い、違反は 400 で返す。
    返り値は部分マージ後の保存値全体 (defaults / saved は null)。
    """
    from rotation_settings import save_rotation_settings

    try:
        return save_rotation_settings(update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
