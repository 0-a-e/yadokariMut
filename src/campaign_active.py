#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Campaign activity + effective rent resolution.

Single source of truth for:
- is_active (JST, starts_on/ends_on, contract_within_days, ends_on NULL)
- rent_plans.campaign_label ↔ campaigns.campaign_type matching
- effective_daily_rent_yen / campaign_applied on each plan
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, MutableMapping, Sequence
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

# rent_plans.campaign_label → campaigns.campaign_type
LABEL_TO_CAMPAIGN_TYPE: dict[str, str] = {
    "早割キャンペーン": "早割",
    "早割": "早割",
    "短期割キャンペーン": "特別割引",
    "短期割": "特別割引",
    "特別割引": "特別割引",
    "特別割引キャンペーン": "特別割引",
    "ミドル割キャンペーン": "ミドル割",
    "ミドル割": "ミドル割",
    "ロング割キャンペーン": "ロング割",
    "ロング割": "ロング割",
    "500円割": "500円割",
    "500円割キャンペーン": "500円割",
    "ポッキリ割": "ポッキリ割",
    "ポッキリ割キャンペーン": "ポッキリ割",
}

# Labels too vague to map to a single type (match by plan target only)
AMBIGUOUS_LABELS = frozenset({"キャンペーン", "キャンペーン適用", "割引キャンペーン"})

PLAN_CODES = frozenset({"s_short", "short", "middle", "long", "all"})


def today_jst(now: datetime | None = None) -> date:
    """Return today's calendar date in Asia/Tokyo."""
    if now is None:
        now = datetime.now(tz=JST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(JST)
    else:
        now = now.astimezone(JST)
    return now.date()


def _parse_iso_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    # YYYY-MM-DD (optionally with time)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_campaign_label(label: str | None) -> str | None:
    """Map rent_plans.campaign_label to campaigns.campaign_type, or None if unknown/ambiguous."""
    if not label:
        return None
    text = str(label).strip()
    if not text:
        return None
    if text in AMBIGUOUS_LABELS:
        return None
    if text in LABEL_TO_CAMPAIGN_TYPE:
        return LABEL_TO_CAMPAIGN_TYPE[text]
    # Soft match: strip trailing キャンペーン
    stripped = text.replace("キャンペーン", "").strip()
    if stripped in LABEL_TO_CAMPAIGN_TYPE:
        return LABEL_TO_CAMPAIGN_TYPE[stripped]
    if stripped in ("早割", "ミドル割", "ロング割", "特別割引", "短期割", "500円割", "ポッキリ割"):
        return "特別割引" if stripped == "短期割" else stripped
    return None


def campaign_targets_plan(campaign: Mapping[str, Any], plan_code: str | None) -> bool:
    """True if campaign may apply to the given plan_code."""
    target = (campaign.get("target_plan_code") or "").strip().lower() or None
    if target in (None, "", "all"):
        return True
    if not plan_code:
        return True  # cannot exclude without a code
    code = str(plan_code).strip().lower()
    return target == code


def campaign_is_active(
    campaign: Mapping[str, Any],
    *,
    on_date: date | str | None = None,
    as_of: date | str | None = None,
    require_known_end: bool = False,
    check_contract_within: bool = True,
) -> bool:
    """Whether a campaign is currently applicable.

    Parameters
    ----------
    on_date:
        Date used for starts_on / ends_on comparison (default: today JST).
        For 早割 this is typically the intended move-in date; for listing
        display we use today.
    as_of:
        "Today" for contract_within_days (default: today JST).
    require_known_end:
        If True, campaigns with ends_on NULL are treated as inactive
        (conservative pricing). Default False so ongoing 500円割 etc. stay on.
    check_contract_within:
        If True and contract_within_days is set, require that ``as_of`` is
        still within the contract window. When starts_on is set, the window
        is interpreted relative to as_of only (「本日よりN日以内」): always
        true when as_of is "now" for immediate contract, so we treat it as:
        the user must contract by as_of + 0 (i.e. decision day is as_of),
        which is always satisfied for as_of=today. We only fail when a
        future as_of is intentionally far — practically this flag is a no-op
        for default listing. Kept for API completeness / future contract-date UI.

        Practical rule used here:
        - contract_within_days alone does not deactivate when as_of == on_date
          default path.
        - When on_date is in the past relative to ends_on etc., period rules win.
    """
    today = today_jst()
    d = _parse_iso_date(on_date) if on_date is not None else today
    if d is None:
        d = today
    as_of_d = _parse_iso_date(as_of) if as_of is not None else today
    if as_of_d is None:
        as_of_d = today

    starts = _parse_iso_date(campaign.get("starts_on"))
    ends = _parse_iso_date(campaign.get("ends_on"))

    if starts and d < starts:
        return False
    if ends and d > ends:
        return False
    if ends is None and require_known_end:
        return False

    if check_contract_within:
        within = campaign.get("contract_within_days")
        if within is not None:
            try:
                n = int(within)
            except (TypeError, ValueError):
                n = None
            if n is not None and n >= 0:
                # 「本日よりN日以内にご契約」— decision day is as_of.
                # Always OK when contracting "now" (as_of). If a future
                # contract date is supplied as as_of, still OK (user plans
                # to contract on that day). No deactivation here; the
                # period bounds above are the real gate for expired cams.
                # Reserved hook: if campaign stored a scraped_at reference
                # we could compare — currently unused.
                pass

    return True


def annotate_campaign_activity(
    campaign: MutableMapping[str, Any] | Mapping[str, Any],
    *,
    on_date: date | str | None = None,
    as_of: date | str | None = None,
) -> dict[str, Any]:
    """Return a copy with is_active and date_end_unknown flags."""
    c = dict(campaign)
    ends = _parse_iso_date(c.get("ends_on"))
    c["date_end_unknown"] = ends is None
    c["is_active"] = campaign_is_active(c, on_date=on_date, as_of=as_of)
    return c


def annotate_campaigns(
    campaigns: Sequence[Mapping[str, Any]] | None,
    *,
    on_date: date | str | None = None,
    as_of: date | str | None = None,
) -> list[dict[str, Any]]:
    if not campaigns:
        return []
    return [annotate_campaign_activity(c, on_date=on_date, as_of=as_of) for c in campaigns]


def _find_matching_active_campaign(
    plan: Mapping[str, Any],
    campaigns: Sequence[Mapping[str, Any]],
    *,
    on_date: date | str | None = None,
) -> dict[str, Any] | None:
    """Find an active campaign that explains this plan's campaign_label (if any)."""
    label = plan.get("campaign_label")
    plan_code = plan.get("plan_code")
    mapped_type = normalize_campaign_label(label) if label else None
    ambiguous = bool(label) and str(label).strip() in AMBIGUOUS_LABELS

    active = [
        c if isinstance(c, dict) and "is_active" in c else annotate_campaign_activity(c, on_date=on_date)
        for c in campaigns
    ]
    active = [c for c in active if c.get("is_active")]

    candidates: list[dict[str, Any]] = []
    for c in active:
        if not campaign_targets_plan(c, plan_code):
            continue
        ctype = (c.get("campaign_type") or "").strip()
        if mapped_type:
            if ctype == mapped_type:
                candidates.append(c)
        elif ambiguous or not label:
            # Ambiguous label: any active plan-targeting campaign may justify discount
            if ambiguous:
                candidates.append(c)
            # No label: do not require a campaign (handled by caller)
        else:
            # Unknown label text: try soft containment
            if ctype and (ctype in str(label) or str(label) in ctype):
                candidates.append(c)

    if not candidates:
        return None
    # Prefer exact type match order already filtered; first is fine
    return candidates[0]


def resolve_plan_effective_rent(
    plan: Mapping[str, Any],
    campaigns: Sequence[Mapping[str, Any]] | None,
    *,
    on_date: date | str | None = None,
) -> dict[str, Any]:
    """Attach effective_* and campaign_applied to a rent plan dict.

    Rules:
    - No campaign_label, or discounted == original → use discounted as candidate
    - campaign_label present + matching active campaign → discounted snapshot candidate
    - campaign_label present + no matching active → fall back to original candidate
    - **Quality gate** (price_resolution): reject corrupt snapshots (negative,
      disc>orig, 9×「1000%OFF」pattern, stale promo after expiry) and recompute
      via structured yen/percent (plan-specific preferred) or original.
    - Package campaigns are not used for list daily (stay simulator only).
    """
    # Lazy import: price_resolution imports filter_applicable_campaigns from here
    from price_resolution import apply_snapshot_quality_gate

    out = dict(plan)
    discounted = out.get("discounted_daily_rent_yen")
    original = out.get("original_daily_rent_yen")
    disc_total = out.get("discounted_total_yen")
    orig_total = out.get("original_total_yen")
    label = out.get("campaign_label")

    # Default candidate: discounted snapshot
    effective_daily = discounted
    effective_total = disc_total
    campaign_applied = False
    matched_type = None
    display_label = label

    has_discount = (
        discounted is not None
        and original is not None
        and discounted != original
    ) or bool(label)

    if has_discount and label and campaigns is not None:
        match = _find_matching_active_campaign(out, campaigns, on_date=on_date)
        if match is not None:
            campaign_applied = True
            matched_type = match.get("campaign_type")
            effective_daily = discounted
            effective_total = disc_total
        else:
            # Expired / no match → list at original (list price)
            campaign_applied = False
            effective_daily = original if original is not None else discounted
            effective_total = orig_total if orig_total is not None else disc_total
            display_label = None  # do not show expired badge as active
            out["campaign_expired"] = True
            out["expired_campaign_label"] = label
    elif has_discount and label and not campaigns:
        # No campaign rows: cannot verify → keep discounted but flag uncertain
        campaign_applied = False
        out["campaign_uncertain"] = True
        effective_daily = discounted
        effective_total = disc_total
    else:
        # No claimed campaign discount
        campaign_applied = False
        effective_daily = discounted if discounted is not None else original
        effective_total = disc_total if disc_total is not None else orig_total

    # Snapshot quality gate + structured / original recovery
    gated = apply_snapshot_quality_gate(
        out,
        proposed_daily=effective_daily if isinstance(effective_daily, int) else (
            int(effective_daily) if effective_daily is not None else None
        ),
        proposed_total=effective_total if isinstance(effective_total, int) or effective_total is None else int(effective_total),
        campaign_applied=campaign_applied,
        campaigns=campaigns,
        on_date=on_date,
    )
    effective_daily = gated["effective_daily"]
    effective_total = gated["effective_total"]

    # If we replaced a corrupt active-campaign snapshot, still mark applied when
    # structured recompute used the matching promo — else clear applied flag when
    # we fell back to bare original due to corruption.
    if gated.get("price_corrected") and campaign_applied:
        method = gated.get("price_resolution_method") or ""
        if method.startswith("structured"):
            # Recomputed from structured fields of active campaigns
            pass
        elif method == "original":
            campaign_applied = False
            display_label = None
            out["price_snapshot_rejected"] = True

    out["effective_daily_rent_yen"] = effective_daily
    out["effective_total_yen"] = effective_total
    out["campaign_applied"] = campaign_applied
    out["matched_campaign_type"] = matched_type
    out["effective_campaign_label"] = display_label if campaign_applied else (
        None if out.get("campaign_expired") else (label if not gated.get("price_corrected") else None)
    )
    out["price_resolution_status"] = gated.get("price_resolution_status")
    out["price_resolution_method"] = gated.get("price_resolution_method")
    out["price_resolution_notes"] = gated.get("price_resolution_notes")
    out["price_issues"] = gated.get("price_issues")
    out["price_corrected"] = bool(gated.get("price_corrected"))
    return out


def resolve_plans_effective_rent(
    plans: Sequence[Mapping[str, Any]] | None,
    campaigns: Sequence[Mapping[str, Any]] | None,
    *,
    on_date: date | str | None = None,
) -> list[dict[str, Any]]:
    if not plans:
        return []
    annotated_cams = annotate_campaigns(campaigns, on_date=on_date)
    return [
        resolve_plan_effective_rent(p, annotated_cams, on_date=on_date)
        for p in plans
    ]


def compute_min_rent_from_plans(
    plans: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """min_daily_rent / min_plan_total / min_plan_name from effective rates.

    Skips non-positive dailies so corrupt negative snapshots cannot win min.
    """
    best_daily = None
    best_total = None
    best_name = None
    for p in plans or []:
        if not p.get("available"):
            continue
        daily = p.get("effective_daily_rent_yen")
        if daily is None:
            daily = p.get("discounted_daily_rent_yen")
        if daily is None:
            continue
        try:
            daily_i = int(daily)
        except (TypeError, ValueError):
            continue
        if daily_i <= 0:
            continue
        if best_daily is None or daily_i < best_daily:
            best_daily = daily_i
            total = p.get("effective_total_yen")
            if total is None:
                total = p.get("discounted_total_yen")
            # ignore non-positive totals for min_plan_total pairing
            if total is not None:
                try:
                    if int(total) <= 0:
                        total = None
                except (TypeError, ValueError):
                    total = None
            best_total = total
            best_name = p.get("plan_name")
    return {
        "min_daily_rent": best_daily,
        "min_plan_total": best_total,
        "min_plan_name": best_name,
    }


def apply_effective_to_property(
    prop: MutableMapping[str, Any],
    *,
    on_date: date | str | None = None,
) -> dict[str, Any]:
    """In-place: annotate campaigns, resolve plan effective rents, recompute min_*."""
    cams = annotate_campaigns(prop.get("campaigns"), on_date=on_date)
    prop["campaigns"] = cams
    plans = resolve_plans_effective_rent(prop.get("rent_plans"), cams, on_date=on_date)
    prop["rent_plans"] = plans
    mins = compute_min_rent_from_plans(plans)
    if mins["min_daily_rent"] is not None:
        prop["min_daily_rent"] = mins["min_daily_rent"]
        prop["min_plan_total"] = mins["min_plan_total"]
        prop["min_plan_name"] = mins["min_plan_name"]
    return prop


# --- Step 2 helpers: structured discount application for simulator ---

def filter_applicable_campaigns(
    campaigns: Sequence[Mapping[str, Any]] | None,
    *,
    plan_code: str | None,
    stay_days: int | None = None,
    on_date: date | str | None = None,
) -> list[dict[str, Any]]:
    """Active campaigns targeting plan and stay band."""
    result = []
    for c in annotate_campaigns(campaigns, on_date=on_date):
        if not c.get("is_active"):
            continue
        if not campaign_targets_plan(c, plan_code):
            continue
        if stay_days is not None:
            smin = c.get("stay_min_days")
            smax = c.get("stay_max_days")
            if smin is not None and stay_days < int(smin):
                continue
            if smax is not None and stay_days > int(smax):
                continue
        result.append(c)
    return result


def apply_structured_discount(
    *,
    original_daily: int,
    stay_days: int,
    cleaning_fee: int,
    contract_fee: int,
    campaigns: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply structured campaign fields to produce adjusted totals (Phase 2).

    Returns dict with rent_daily_effective, cleaning_fee, contract_fee,
    discount_notes, applied_campaigns.
    """
    rent_daily = original_daily
    clean = cleaning_fee
    fee = contract_fee
    notes: list[str] = []
    applied: list[str] = []

    # Prefer yen/percent daily adjustments; packages adjust fees
    yen_cams = [c for c in campaigns if c.get("discount_unit") == "yen" and c.get("discount_value")]
    pct_cams = [c for c in campaigns if c.get("discount_unit") == "percent" and c.get("discount_value")]
    pkg_cams = [c for c in campaigns if c.get("discount_unit") == "package"]

    if yen_cams:
        c = yen_cams[0]
        value = int(c["discount_value"])
        period_max = c.get("period_max_days")
        dmax = c.get("discount_max_yen")
        apply_days = stay_days
        if period_max is not None:
            apply_days = min(stay_days, int(period_max))
        total_off = value * apply_days
        if dmax is not None and total_off > int(dmax):
            total_off = int(dmax)
        # Convert total discount to effective daily for the stay
        if stay_days > 0:
            rent_daily = max(0, original_daily - (total_off // stay_days))
        label = c.get("campaign_type") or c.get("title") or "yen"
        notes.append(f"{label}: 日額{value}円×{apply_days}日" + (f"（上限{dmax}円）" if dmax else ""))
        applied.append(str(label))

    elif pct_cams:
        c = pct_cams[0]
        pct = int(c["discount_value"])
        period_max = c.get("period_max_days")
        dmax = c.get("discount_max_yen")
        apply_days = stay_days
        if period_max is not None:
            apply_days = min(stay_days, int(period_max))
        daily_off = original_daily * pct // 100
        total_off = daily_off * apply_days
        if dmax is not None and total_off > int(dmax):
            total_off = int(dmax)
            daily_off = total_off // stay_days if stay_days else 0
        if stay_days > 0:
            # effective daily accounts for partial-period percent off
            rent_daily = max(0, original_daily - (total_off // stay_days))
        label = c.get("campaign_type") or c.get("title") or "percent"
        notes.append(f"{label}: {pct}%OFF×{apply_days}日")
        applied.append(str(label))

    for c in pkg_cams:
        label = c.get("campaign_type") or c.get("title") or "package"
        rent_ben = c.get("package_rent_benefit_yen") or 0
        clean_ben = c.get("package_cleaning_benefit_yen") or 0
        fee_ben = c.get("package_fee_benefit_yen") or 0
        if rent_ben and stay_days > 0:
            rent_daily = max(0, rent_daily - int(rent_ben) // stay_days)
        if clean_ben:
            clean = max(0, clean - int(clean_ben))
        if fee_ben:
            fee = max(0, fee - int(fee_ben))
        notes.append(f"{label}: パッケージお得適用")
        applied.append(str(label))

    return {
        "rent_daily_effective": rent_daily,
        "cleaning_fee": clean,
        "contract_fee": fee,
        "discount_notes": notes,
        "applied_campaigns": applied,
    }
