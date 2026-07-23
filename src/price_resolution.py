#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Price snapshot validation + mechanical list-daily resolution.

Used by ``campaign_active.resolve_plan_effective_rent`` (production) and
``poc_price_resolution.py`` (CLI audit).

Does **not** special-case package campaigns for list daily (ミドル割 etc. stay
in stay-simulator / apply_structured_discount). Titles are never used as
discount evidence — only structured yen/percent fields.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

# Plausible catalog daily band for monthly mansions (yen)
PLAUSIBLE_DAILY_MIN = 800
PLAUSIBLE_DAILY_MAX = 25000

NEG_DAILY_IN_RAW = re.compile(r"-\s*[\d,]+円\s*/\s*日")
NEG_TOTAL_IN_RAW = re.compile(r"[（(]\s*[週月]?\s*-\s*[\d,]+円")


@dataclass
class Issue:
    code: str
    severity: str  # critical | high | medium | info
    detail: str


@dataclass
class PlanResolution:
    property_id: int
    plan_id: int | None
    plan_code: str | None
    plan_name: str | None
    campaign_label: str | None
    original_daily_rent_yen: int | None
    source_discounted_daily_rent_yen: int | None
    source_discounted_total_yen: int | None
    legacy_effective_daily_yen: int | None
    resolved_daily_rent_yen: int | None
    resolution_status: str
    resolution_method: str
    resolution_notes: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["issues"] = [asdict(i) for i in self.issues]
        return d


@dataclass
class PropertyResolutionSummary:
    property_id: int
    title: str
    plan_results: list[PlanResolution]
    property_status: str
    min_resolved_daily: int | None
    min_legacy_effective_daily: int | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "title": self.title,
            "property_status": self.property_status,
            "min_resolved_daily": self.min_resolved_daily,
            "min_legacy_effective_daily": self.min_legacy_effective_daily,
            "notes": self.notes,
            "plans": [p.to_dict() for p in self.plan_results],
        }


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def detect_plan_issues(plan: Mapping[str, Any]) -> list[Issue]:
    """Mechanical anomaly flags for one rent_plans row."""
    issues: list[Issue] = []
    od = _as_int(plan.get("original_daily_rent_yen"))
    dd = _as_int(plan.get("discounted_daily_rent_yen"))
    dt = _as_int(plan.get("discounted_total_yen"))
    ot = _as_int(plan.get("original_total_yen"))
    raw = plan.get("raw_text") or ""

    if dd is not None and dd < 0:
        issues.append(Issue("NEG_DAILY", "critical", f"discounted_daily={dd}"))
    if od is not None and od < 0:
        issues.append(Issue("NEG_ORIG_DAILY", "critical", f"original_daily={od}"))
    if dt is not None and dt < 0:
        issues.append(Issue("NEG_TOTAL", "critical", f"discounted_total={dt}"))
    if ot is not None and ot < 0:
        issues.append(Issue("NEG_ORIG_TOTAL", "high", f"original_total={ot}"))

    if NEG_DAILY_IN_RAW.search(raw):
        issues.append(Issue("NEG_DAILY_IN_RAW", "critical", "raw_text has negative daily"))
    if NEG_TOTAL_IN_RAW.search(raw):
        issues.append(Issue("NEG_TOTAL_IN_RAW", "critical", "raw_text has negative period total"))

    if od is not None and od <= 0 and (plan.get("campaign_label") or dd not in (None, 0)):
        issues.append(Issue("ZERO_ORIG", "critical", f"original_daily={od}"))

    if od is not None and dd is not None and od > 0 and dd > od:
        issues.append(
            Issue("DISC_GT_ORIG", "critical", f"discounted={dd} > original={od}")
        )
        if dd == od * 9:
            issues.append(
                Issue(
                    "DISC_EQ_9X",
                    "critical",
                    "discounted == 9×original (likely 1000%OFF site bug)",
                )
            )

    if (
        od
        and od > 0
        and dd
        and dd == od * 9
        and NEG_DAILY_IN_RAW.search(raw)
    ):
        issues.append(
            Issue(
                "ABS_OF_NEG_NINE_X",
                "critical",
                "DB stores |−9×orig| while raw shows negative 9×",
            )
        )

    if dd is not None and dd > 0 and not (PLAUSIBLE_DAILY_MIN <= dd <= PLAUSIBLE_DAILY_MAX):
        if dd > PLAUSIBLE_DAILY_MAX or dd < PLAUSIBLE_DAILY_MIN:
            issues.append(
                Issue(
                    "IMPLAUSIBLE_DAILY",
                    "medium",
                    f"discounted_daily={dd} outside [{PLAUSIBLE_DAILY_MIN},{PLAUSIBLE_DAILY_MAX}]",
                )
            )

    if od is not None and od > 0 and dd is not None and dd == od and dt is not None and dt < 0:
        issues.append(
            Issue(
                "TOTAL_NEG_DAILY_OK",
                "high",
                "total negative while daily non-negative (inconsistent columns)",
            )
        )

    return issues


def snapshot_is_trustworthy(
    original: int | None,
    discounted: int | None,
    issues: Sequence[Issue],
    *,
    campaign_label: str | None = None,
    campaign_applied: bool = False,
) -> bool:
    """Whether discounted snapshot may be used as effective list price."""
    critical = {i.code for i in issues if i.severity == "critical"}
    if critical & {
        "NEG_DAILY",
        "NEG_ORIG_DAILY",
        "NEG_TOTAL",
        "NEG_DAILY_IN_RAW",
        "NEG_TOTAL_IN_RAW",
        "DISC_GT_ORIG",
        "DISC_EQ_9X",
        "ABS_OF_NEG_NINE_X",
        "ZERO_ORIG",
    }:
        return False
    if discounted is not None and discounted <= 0:
        return False
    if (
        original is not None
        and discounted is not None
        and original > 0
        and discounted > original
    ):
        return False
    if discounted is not None and (
        discounted < 500 or discounted > PLAUSIBLE_DAILY_MAX
    ):
        return False

    has_label = bool(campaign_label and str(campaign_label).strip())
    has_discount = (
        original is not None
        and discounted is not None
        and original > 0
        and discounted != original
    )
    if has_label and has_discount and not campaign_applied:
        return False
    return True


def _target_specificity(campaign: Mapping[str, Any]) -> int:
    target = (campaign.get("target_plan_code") or "").strip().lower() or "all"
    if target in ("", "all"):
        return 0
    return 1


def _list_daily_from_campaign(
    original: int, campaign: Mapping[str, Any]
) -> tuple[int, str] | None:
    unit = (campaign.get("discount_unit") or "").strip().lower()
    value = _as_int(campaign.get("discount_value"))
    label = campaign.get("campaign_type") or campaign.get("title") or unit

    if unit == "yen" and value is not None and value > 0:
        daily = max(0, original - value)
        return daily, f"{label}: 日額{value}円引 → {daily}円/日"

    if unit == "percent" and value is not None and 0 < value <= 100:
        daily = max(0, original * (100 - value) // 100)
        return daily, f"{label}: {value}%OFF → {daily}円/日"

    return None


def resolve_list_daily_structured(
    original: int,
    plan_code: str | None,
    campaigns: Sequence[Mapping[str, Any]],
    *,
    on_date: date | str | None = None,
) -> tuple[int | None, str | None, list[str]]:
    """Prefer plan-specific yen/percent over target=all. Packages ignored for list daily."""
    # Lazy import avoids circular import with campaign_active
    from campaign_active import filter_applicable_campaigns

    applicable = filter_applicable_campaigns(
        campaigns,
        plan_code=plan_code,
        stay_days=None,
        on_date=on_date,
    )
    rent_cams = [
        c
        for c in applicable
        if (c.get("discount_unit") or "") in ("yen", "percent")
        and c.get("discount_value") is not None
    ]
    if not rent_cams:
        return None, None, []

    rent_cams = sorted(rent_cams, key=_target_specificity, reverse=True)
    best_tier = _target_specificity(rent_cams[0])
    tier = [c for c in rent_cams if _target_specificity(c) == best_tier]

    best_daily: int | None = None
    best_note: str | None = None
    best_method: str | None = None

    for c in tier:
        got = _list_daily_from_campaign(original, c)
        if not got:
            continue
        daily, note = got
        if best_daily is None or daily < best_daily:
            best_daily = daily
            best_note = note
            unit = c.get("discount_unit")
            best_method = (
                f"structured_{unit}_specific" if best_tier else f"structured_{unit}"
            )

    if best_daily is None:
        return None, None, []
    return best_daily, best_method, [best_note] if best_note else []


def estimate_total_from_daily(
    daily: int | None,
    *,
    period_days: int | None,
    original_daily: int | None,
    original_total: int | None,
) -> int | None:
    """Best-effort period total aligned with a resolved list daily."""
    if daily is None:
        return None
    if period_days is not None and period_days > 0:
        return int(daily) * int(period_days)
    if (
        original_daily is not None
        and original_daily > 0
        and original_total is not None
        and original_total > 0
    ):
        return int(original_total * daily / original_daily)
    return None


def apply_snapshot_quality_gate(
    plan: Mapping[str, Any],
    *,
    proposed_daily: int | None,
    proposed_total: int | None,
    campaign_applied: bool,
    campaigns: Sequence[Mapping[str, Any]] | None,
    on_date: date | str | None = None,
) -> dict[str, Any]:
    """If proposed snapshot daily is corrupt, recompute via structured or original.

    Returns keys: effective_daily, effective_total, price_resolution_status,
    price_resolution_method, price_resolution_notes, price_issues (codes).
    """
    issues = detect_plan_issues(plan)
    od = _as_int(plan.get("original_daily_rent_yen"))
    dd = _as_int(plan.get("discounted_daily_rent_yen"))
    notes: list[str] = []
    issue_codes = [i.code for i in issues]

    trust = snapshot_is_trustworthy(
        od,
        proposed_daily if proposed_daily is not None else dd,
        issues,
        campaign_label=plan.get("campaign_label"),
        campaign_applied=campaign_applied,
    )
    # Also reject if proposed daily itself is non-positive / over original when labelled
    if proposed_daily is not None and proposed_daily <= 0:
        trust = False
        notes.append(f"proposed daily non-positive ({proposed_daily})")
    if (
        od
        and proposed_daily is not None
        and od > 0
        and proposed_daily > od
    ):
        trust = False
        notes.append(f"proposed daily {proposed_daily} > original {od}")

    if trust and proposed_daily is not None:
        return {
            "effective_daily": proposed_daily,
            "effective_total": proposed_total,
            "price_resolution_status": "ok",
            "price_resolution_method": "snapshot",
            "price_resolution_notes": notes
            or ["snapshot trusted"],
            "price_issues": issue_codes,
            "price_corrected": False,
        }

    if issue_codes:
        notes.append(
            "snapshot rejected: "
            + ", ".join(sorted({c for c in issue_codes if c}))
        )
    elif plan.get("campaign_label") and not campaign_applied:
        notes.append("snapshot rejected: inactive/unmatched campaign label")
    else:
        notes.append("snapshot rejected: quality gate")

    plan_code = plan.get("plan_code")
    if plan_code is not None:
        plan_code = str(plan_code)

    resolved: int | None = None
    method = "none"
    status = "unusable"

    if od is not None and od > 0 and campaigns is not None:
        s_daily, s_method, s_notes = resolve_list_daily_structured(
            od, plan_code, campaigns, on_date=on_date
        )
        notes.extend(s_notes)
        if s_daily is not None and PLAUSIBLE_DAILY_MIN <= s_daily <= PLAUSIBLE_DAILY_MAX:
            resolved = s_daily
            status = "corrected"
            method = s_method or "structured"
        elif s_daily is not None and s_daily <= 0:
            notes.append(f"structured daily {s_daily} rejected (non-positive)")
        elif s_daily is not None:
            notes.append(f"structured daily {s_daily} outside typical band")

    if resolved is None and od is not None and od > 0:
        resolved = od
        status = "fallback_original"
        method = "original"
        notes.append("fallback to original list daily")

    total = estimate_total_from_daily(
        resolved,
        period_days=_as_int(plan.get("total_period_days")),
        original_daily=od,
        original_total=_as_int(plan.get("original_total_yen")),
    )
    if resolved is None:
        return {
            "effective_daily": None,
            "effective_total": None,
            "price_resolution_status": "unusable",
            "price_resolution_method": "none",
            "price_resolution_notes": notes,
            "price_issues": issue_codes,
            "price_corrected": True,
        }

    return {
        "effective_daily": resolved,
        "effective_total": total,
        "price_resolution_status": status,
        "price_resolution_method": method,
        "price_resolution_notes": notes,
        "price_issues": issue_codes,
        "price_corrected": status != "ok",
    }


def scan_db_for_suspicious_property_ids(conn) -> list[int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT property_id FROM rent_plans
        WHERE available = 1 AND (
            discounted_daily_rent_yen < 0
            OR original_daily_rent_yen < 0
            OR discounted_total_yen < 0
            OR original_total_yen < 0
            OR (
                original_daily_rent_yen > 0
                AND discounted_daily_rent_yen > original_daily_rent_yen
            )
            OR (
                original_daily_rent_yen > 0
                AND discounted_daily_rent_yen = original_daily_rent_yen * 9
            )
            OR raw_text LIKE '%-%円/日%'
            OR raw_text LIKE '%(月 -%'
            OR raw_text LIKE '%(週 -%'
        )
        ORDER BY property_id
        """
    )
    return [int(r[0]) for r in cur.fetchall()]


def resolve_property(
    property_id: int,
    title: str,
    plans: Sequence[Mapping[str, Any]],
    campaigns: Sequence[Mapping[str, Any]] | None,
    *,
    on_date: date | str | None = None,
) -> PropertyResolutionSummary:
    """Audit helper used by PoC CLI (production path is resolve_plan_effective_rent)."""
    from campaign_active import annotate_campaigns, resolve_plan_effective_rent

    ann = annotate_campaigns(campaigns, on_date=on_date) if campaigns else []
    results: list[PlanResolution] = []
    for p in plans:
        if p.get("available") not in (1, True, None) and p.get("available") != 1:
            if p.get("available") in (0, False):
                continue
        out = resolve_plan_effective_rent(p, ann, on_date=on_date)
        issues = detect_plan_issues(p)
        results.append(
            PlanResolution(
                property_id=property_id,
                plan_id=_as_int(p.get("id")),
                plan_code=str(p["plan_code"]) if p.get("plan_code") is not None else None,
                plan_name=p.get("plan_name"),
                campaign_label=p.get("campaign_label"),
                original_daily_rent_yen=_as_int(p.get("original_daily_rent_yen")),
                source_discounted_daily_rent_yen=_as_int(
                    p.get("discounted_daily_rent_yen")
                ),
                source_discounted_total_yen=_as_int(p.get("discounted_total_yen")),
                legacy_effective_daily_yen=_as_int(out.get("effective_daily_rent_yen")),
                resolved_daily_rent_yen=_as_int(out.get("effective_daily_rent_yen")),
                resolution_status=str(out.get("price_resolution_status") or "ok"),
                resolution_method=str(out.get("price_resolution_method") or "snapshot"),
                resolution_notes=list(out.get("price_resolution_notes") or []),
                issues=issues,
            )
        )

    statuses = {r.resolution_status for r in results}
    if all(s == "ok" for s in statuses) and results:
        prop_status = "ok"
    elif any(r.resolved_daily_rent_yen is not None for r in results):
        prop_status = "partial"
    else:
        prop_status = "bad"

    def _min_daily(vals: list[int | None]) -> int | None:
        nums = [v for v in vals if v is not None and v > 0]
        return min(nums) if nums else None

    notes: list[str] = []
    n_corr = sum(1 for r in results if r.resolution_status in ("corrected", "fallback_original"))
    if n_corr:
        notes.append(f"{n_corr} plan(s) non-snapshot resolution")

    return PropertyResolutionSummary(
        property_id=property_id,
        title=title,
        plan_results=results,
        property_status=prop_status,
        min_resolved_daily=_min_daily([r.resolved_daily_rent_yen for r in results]),
        min_legacy_effective_daily=_min_daily(
            [r.legacy_effective_daily_yen for r in results]
        ),
        notes=notes,
    )
