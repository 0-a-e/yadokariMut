"""Prefecture rotation planner for scheduled scraping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from domain.tz import JST
from ingest.pipeline import TargetIngestResult

# A prefecture with this many consecutive failures (or more) is excluded from
# batch selection until its cooldown window has elapsed since the last attempt.
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_FAILURE_COOLDOWN_HOURS = 48


def _as_naive_jst(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(JST).replace(tzinfo=None)
    return dt


@dataclass
class RotationBatch:
    """Planned scrape batch for a single source-site run."""

    prefs: list[str] = field(default_factory=list)
    est_items: int = 0
    unlimited: bool = False
    reason: str = ""


def is_suppressed(
    state: Mapping | None,
    *,
    now: datetime,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    failure_cooldown_hours: int = DEFAULT_FAILURE_COOLDOWN_HOURS,
) -> bool:
    """True if the prefecture is in failure cooldown (excluded from selection).

    Suppression requires BOTH: failures >= threshold AND the last attempt is
    more recent than the cooldown window. Once the cooldown elapses the
    prefecture becomes eligible again and is re-probed on its next turn.
    """
    st = state or {}
    try:
        failures = int(st.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        return False
    if failures < max_consecutive_failures:
        return False
    last_run = st.get("last_run_at")
    if not last_run:
        return False
    try:
        last_run_dt = _as_naive_jst(datetime.fromisoformat(str(last_run)))
    except (TypeError, ValueError):
        return False
    age_hours = (_as_naive_jst(now) - last_run_dt).total_seconds() / 3600.0
    return age_hours < failure_cooldown_hours


class RotationPlanner:
    """Selects the prefecture subset to scrape so all prefs cycle weekly.

    The daily per-source item limit is a planning-time soft budget only:
    small prefectures are packed greedily first, and a prefecture that
    alone exceeds the remaining budget is fetched whole on its own run
    (limit ignored).
    """

    def __init__(self, repo) -> None:  # Repository (duck-typed)
        self.repo = repo

    def plan(
        self,
        source_id: str,
        *,
        pref_catalog: list[str],
        daily_limit: int,
        default_est: int = 60,
        now: datetime | None = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        failure_cooldown_hours: int = DEFAULT_FAILURE_COOLDOWN_HOURS,
    ) -> RotationBatch:
        now = now or datetime.now()

        # Idempotent: registers prefectures newly added to the catalog.
        self.repo.seed_rotation_state(source_id, list(pref_catalog))

        remaining = daily_limit - self.repo.rotation_usage_today(source_id, now)
        if remaining <= 0:
            return RotationBatch(prefs=[], reason="daily_budget_exhausted")

        states = {
            row["prefecture_slug"]: row
            for row in self.repo.load_rotation_states(source_id)
        }
        queue = [
            p
            for p in sorted(pref_catalog, key=lambda p: self.sort_key(p, states))
            if not is_suppressed(
                states.get(p),
                now=now,
                max_consecutive_failures=max_consecutive_failures,
                failure_cooldown_hours=failure_cooldown_hours,
            )
        ]
        if not queue:
            return RotationBatch(prefs=[], reason="all_prefs_in_failure_cooldown")

        def cost_of(p: str) -> int:
            return (states.get(p) or {}).get("known_total") or default_est

        # The queue head (most stale prefecture) must always make progress:
        # if it does not fit the remaining budget, it is fetched whole on its
        # own with the limit ignored (over-limit exception) — smaller
        # prefectures must not starve it by always fitting into the leftover
        # budget.
        if cost_of(queue[0]) > remaining:
            return RotationBatch(
                prefs=[queue[0]], unlimited=True, reason="single_pref_over_limit"
            )

        selected: list[str] = []
        est = 0
        for p in queue:
            cost = cost_of(p)
            if est + cost <= remaining:
                selected.append(p)
                est += cost
            # Prefectures that do not fit are skipped; smaller ones are
            # still considered afterwards.
        return RotationBatch(prefs=selected, est_items=est)

    @staticmethod
    def sort_key(p: str, states: Mapping[str, dict]) -> tuple:
        """Queue sort key (public: web 層の admin queue 表示と共有).

        旧 web_server.py の _rotation_queue_key に手写しされていた順序と
        同一。NULLS FIRST, then oldest last_full_ok_at / known_total
        昇順 (None は最大) / slug 昇順。
        """
        row = states.get(p) or {}
        lfo = row.get("last_full_ok_at")
        known = row.get("known_total")
        # NULLS FIRST, then oldest last_full_ok_at.
        lfo_key = (0, 0) if lfo is None else (1, lfo)
        # known_total ascending; None counts as the largest.
        known_key = known if known is not None else float("inf")
        return (lfo_key, known_key, p)

    def record_result(
        self,
        source_id: str,
        by_target: Mapping[str, TargetIngestResult],
        *,
        now: datetime | None = None,
    ) -> None:
        now = (now or datetime.now()).isoformat()
        for tr in by_target.values():
            slug = tr.prefecture_slug or tr.target_key
            if tr.status == "ok" and tr.list_completed:
                self.repo.upsert_rotation_state(
                    source_id,
                    slug,
                    known_total=tr.list_items,
                    last_full_ok_at=now,
                    last_run_at=now,
                    consecutive_failures=0,
                )
            else:
                self.repo.bump_rotation_failures(source_id, slug, last_run_at=now)
