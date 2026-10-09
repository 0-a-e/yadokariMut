"""県ローテーション・スクレイプのスケジュール / ポリシ解決。

run_rotation_job (web.tasks)・lifespan のスケジューラ登録・rotation ルータの
双方から参照される純粋な設定解決層。DB アクセスは行わない (実行時に
rotation_settings / Repository を解決するのは呼び出し側)。
"""

import os
from typing import List

# 県ローテーション既定のソース集合 (env ROTATION_SOURCES 未指定時の既定)。
# 実在アダプタの正本は sources.registry の _adapter_modules / カタログは
# store.source_catalog.SOURCE_IDS を参照。ここでの再定義は「rotation を
# 回す既定ソース」というスケジューラ側の選択のみを表す。
DEFAULT_ROTATION_SOURCES: tuple[str, ...] = ("bratto", "unionmonthly")

# ソース別既定 cron。キー集合は DEFAULT_ROTATION_SOURCES と一致させ、
# 未記載の id は汎用 cron "0 8,20 * * *" にフォールバックする。
DEFAULT_ROTATION_CRONS: dict[str, str] = dict(
    zip(
        DEFAULT_ROTATION_SOURCES,
        (
            "0 2,14 * * *",  #bratto
            "0 5,17 * * *",  #unionmonthly
        ),
    )
)


def _rotation_source_config() -> List[dict]:
    """Resolve rotation schedule config from env.

    Returns [{id, cron}] in ROTATION_SOURCES order.
    daily_limit / default_est は rotation_settings の実効値をジョブ実行時に
    解決するため、ここでは扱わない。
    - ROTATION_SOURCES: comma separated source ids
      (default ",".join(DEFAULT_ROTATION_SOURCES))
    - ROTATION_CRON_{SID}: per-source cron (DEFAULT_ROTATION_CRONS / "0 8,20 * * *")
    """
    raw = os.environ.get(
        "ROTATION_SOURCES", ",".join(DEFAULT_ROTATION_SOURCES)
    )
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    out: List[dict] = []
    for sid in ids:
        upper = sid.upper()
        cron = os.environ.get(
            f"ROTATION_CRON_{upper}"
        ) or DEFAULT_ROTATION_CRONS.get(sid, "0 8,20 * * *")
        out.append({"id": sid, "cron": cron})
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
        from sources.registry import SourceRegistry

        clean = {k: v for k, v in (cfg or {}).items() if k != "pref_filter"}
        adapter = SourceRegistry.create(source_id, clean)
        pref_catalog = [
            t.prefecture_slug or t.key for t in adapter.discover_list_targets()
        ]
    except Exception as e:
        # 遅延 import: rotation_jobs → tasks の依存は循環を避けるため関数内のみ
        from web.tasks import log_task

        log_task(f"rotation[{source_id}]: pref catalog discovery failed: {e}")
        pref_catalog = []
    return pref_catalog


def _rotation_queue_key(slug: str, states_by_slug: dict) -> tuple:
    """Sort key for the admin rotation queue (= RotationPlanner.sort_key).

    旧 web_server.py に planner のキュー順序が手写しされていたのを廃し、
    RotationPlanner 側に public 化した sort_key へ一本化した。
    rotation.py 仕様: last_full_ok_at NULLS FIRST → 昇順、
    known_total 昇順（None は最大）、slug 昇順。
    """
    from ingest.rotation import RotationPlanner

    return RotationPlanner.sort_key(slug, states_by_slug)
