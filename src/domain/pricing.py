"""Pricing engine (SSOT for multi-source v2).

Stay total and effective rent live here. Frontend may mirror rules but BE is
authoritative for MCP / future estimate APIs.

Rules
-----
- stay_days = inclusive(check_in, check_out)
- plan selection: first available plan where
    stay_days >= duration_min_days
    and (duration_max_days is None or stay_days <= duration_max_days)
  ordered by duration_min_days ascending. Fallback: next longer band, then shorter.
- per_month amounts convert with MONTH_DAYS (30).
- total = (rent_per_day + mgmt_per_day + util_per_day) * stay_days
          + cleaning + contract_fee
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence, Union

from domain.models import Campaign, PricePlan

CONTRACT_FEE_YEN = 5500
MONTH_DAYS = 30

PresentationUnit = str  # "per_day" | "per_month"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_iso_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def calc_stay_days(check_in: str, check_out: str) -> int | None:
    """Inclusive day count: (check_out - check_in) + 1."""
    start = parse_iso_date(check_in)
    end = parse_iso_date(check_out)
    if start is None or end is None:
        return None
    delta = (end - start).days
    if delta < 0:
        return None
    return delta + 1


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def to_per_day(amount: int | None, unit: str, *, month_days: int = MONTH_DAYS) -> int | None:
    """Convert an amount in presentation unit to per-day yen (integer floor)."""
    if amount is None:
        return None
    try:
        n = int(amount)
    except (TypeError, ValueError):
        return None
    u = (unit or "per_day").lower().strip()
    if u in ("per_day", "daily", "day"):
        return n
    if u in ("per_month", "monthly", "month"):
        if month_days <= 0:
            return None
        return n // month_days
    # Unknown unit: treat as per_day
    return n


def plan_rent_per_day(plan: PricePlan | Mapping[str, Any], *, month_days: int = MONTH_DAYS) -> int | None:
    """Effective rent in per-day yen (resolved → current → original)."""
    unit = _plan_unit(plan)
    effective = _get(plan, "effective_rent_yen")
    if effective is not None:
        return to_per_day(int(effective), unit, month_days=month_days)
    current = _get(plan, "rent_current_yen")
    if current is not None:
        return to_per_day(int(current), unit, month_days=month_days)
    original = _get(plan, "rent_original_yen")
    if original is not None:
        return to_per_day(int(original), unit, month_days=month_days)
    return None


def plan_management_per_day(plan: PricePlan | Mapping[str, Any], *, month_days: int = MONTH_DAYS) -> int:
    unit = _plan_unit(plan)
    mgmt = _get(plan, "management_yen")
    if mgmt is None:
        return 0
    daily = to_per_day(int(mgmt), unit, month_days=month_days)
    return daily or 0


def plan_utilities_per_day(plan: PricePlan | Mapping[str, Any], *, month_days: int = MONTH_DAYS) -> int:
    if _get(plan, "utilities_included", True):
        return 0
    unit = _plan_unit(plan)
    util = _get(plan, "utilities_yen")
    if util is None:
        return 0
    daily = to_per_day(int(util), unit, month_days=month_days)
    return daily or 0


# ---------------------------------------------------------------------------
# Plan selection by duration
# ---------------------------------------------------------------------------

def plan_matches_duration(plan: PricePlan | Mapping[str, Any], stay_days: int) -> bool:
    if not _get(plan, "available", True):
        return False
    dmin = int(_get(plan, "duration_min_days") or 1)
    dmax = _get(plan, "duration_max_days")
    if stay_days < dmin:
        return False
    if dmax is not None and stay_days > int(dmax):
        return False
    return True


def is_plan_usable(plan: PricePlan | Mapping[str, Any]) -> bool:
    if not _get(plan, "available", True):
        return False
    daily = plan_rent_per_day(plan)
    return daily is not None and daily >= 0


def select_plan_for_stay(
    plans: Sequence[PricePlan | Mapping[str, Any]],
    stay_days: int,
) -> dict[str, Any] | None:
    """Pick a plan for stay_days using duration bands.

    Preference order:
    1. Exact duration match, lowest duration_min_days among matches
    2. Fallback to next longer available band (higher min)
    3. Fallback to shorter bands (lower min, descending)
    """
    usable = [p for p in plans if is_plan_usable(p)]
    if not usable:
        return None

    def sort_key(p: PricePlan | Mapping[str, Any]) -> int:
        return int(_get(p, "duration_min_days") or 0)

    ordered = sorted(usable, key=sort_key)
    matching = [p for p in ordered if plan_matches_duration(p, stay_days)]
    if matching:
        # Prefer tightest lower bound (already sorted); if multiple, first wins
        selected = matching[0]
        return {
            "selected": selected,
            "plan_key": _get(selected, "plan_key"),
            "used_fallback": False,
            "preferred_min_days": int(_get(selected, "duration_min_days") or 0),
        }

    # Longer bands first (min > stay or max < stay but higher min)
    longer = [p for p in ordered if int(_get(p, "duration_min_days") or 0) > stay_days]
    if longer:
        # For "longer", we want the smallest min still > stay among those that
        # could apply if we stretch — actually when no exact match, "longer band"
        # means plans with higher min (user upgrades duration tier), pick lowest
        # such min that still has rent.
        selected = longer[0]
        return {
            "selected": selected,
            "plan_key": _get(selected, "plan_key"),
            "used_fallback": True,
            "preferred_min_days": stay_days,
        }

    # Shorter bands: highest min among plans with min <= stay that failed max
    shorter = [p for p in reversed(ordered) if int(_get(p, "duration_min_days") or 0) <= stay_days]
    if shorter:
        selected = shorter[0]
        return {
            "selected": selected,
            "plan_key": _get(selected, "plan_key"),
            "used_fallback": True,
            "preferred_min_days": stay_days,
        }

    # Last resort: first usable
    selected = ordered[0]
    return {
        "selected": selected,
        "plan_key": _get(selected, "plan_key"),
        "used_fallback": True,
        "preferred_min_days": stay_days,
    }


# ---------------------------------------------------------------------------
# Effective rent (campaign-aware, presentation unit)
# ---------------------------------------------------------------------------

def campaign_targets_plan_key(campaign: Campaign | Mapping[str, Any], plan_key: str | None) -> bool:
    target = (_get(campaign, "target_plan_key") or _get(campaign, "target_plan_code") or "").strip().lower()
    if not target or target == "all":
        return True
    if not plan_key:
        return True
    return target == str(plan_key).strip().lower()


def campaign_is_active_on(
    campaign: Campaign | Mapping[str, Any],
    on_date: str | date,
) -> bool:
    if _get(campaign, "is_active") is False:
        return False
    d = parse_iso_date(on_date)
    if d is None:
        return True
    starts = parse_iso_date(_get(campaign, "starts_on"))
    ends = parse_iso_date(_get(campaign, "ends_on"))
    if starts and d < starts:
        return False
    if ends and d > ends:
        return False
    return True


def resolve_plan_effective(
    plan: PricePlan | Mapping[str, Any],
    campaigns: Sequence[Campaign | Mapping[str, Any]] | None = None,
    *,
    on_date: str | date | None = None,
) -> PricePlan:
    """Return a PricePlan with effective_rent_yen / campaign flags set.

    Logic (presentation unit amounts):
    - If rent_current != rent_original (or campaign_label set) and a matching
      active campaign exists → use rent_current, campaign_applied=True
    - If label/discount claimed but no active campaign → use rent_original,
      campaign_expired=True
    - Else → rent_current or rent_original
    """
    if isinstance(plan, PricePlan):
        out = replace(plan)
    else:
        out = _plan_from_mapping(plan)

    current = out.rent_current_yen
    original = out.rent_original_yen
    label = out.campaign_label
    plan_key = out.plan_key

    has_discount = (
        current is not None
        and original is not None
        and current != original
    ) or bool(label)

    on = on_date or date.today().isoformat()

    if has_discount and label and campaigns is not None:
        match = _find_matching_campaign(out, campaigns, on_date=on)
        if match is not None:
            out.campaign_applied = True
            out.campaign_expired = False
            out.effective_rent_yen = current if current is not None else original
            out.effective_campaign_label = label
            out.matched_campaign_type = _get(match, "campaign_type")
            out.expired_campaign_label = None
        else:
            out.campaign_applied = False
            out.campaign_expired = True
            out.effective_rent_yen = original if original is not None else current
            out.effective_campaign_label = None
            out.expired_campaign_label = label
            out.matched_campaign_type = None
    elif has_discount and label and not campaigns:
        out.campaign_applied = False
        out.effective_rent_yen = current if current is not None else original
        out.effective_campaign_label = label
    else:
        out.campaign_applied = False
        out.campaign_expired = False
        out.effective_rent_yen = current if current is not None else original
        out.effective_campaign_label = None

    return out


def resolve_plans_effective(
    plans: Sequence[PricePlan | Mapping[str, Any]] | None,
    campaigns: Sequence[Campaign | Mapping[str, Any]] | None = None,
    *,
    on_date: str | date | None = None,
) -> list[PricePlan]:
    if not plans:
        return []
    return [resolve_plan_effective(p, campaigns, on_date=on_date) for p in plans]


def compute_catalog_min_daily(
    plans: Sequence[PricePlan | Mapping[str, Any]] | None,
    *,
    month_days: int = MONTH_DAYS,
) -> dict[str, Any]:
    """Min effective rent/day among available plans (catalog mode)."""
    best_daily: int | None = None
    best_key: str | None = None
    best_name: str | None = None
    for p in plans or []:
        if not _get(p, "available", True):
            continue
        # Prefer already-resolved effective
        if isinstance(p, PricePlan) and p.effective_rent_yen is None:
            p = resolve_plan_effective(p)
        daily = plan_rent_per_day(p, month_days=month_days)
        if daily is None or daily <= 0:
            continue
        if best_daily is None or daily < best_daily:
            best_daily = daily
            best_key = _get(p, "plan_key")
            best_name = _get(p, "plan_name")
    return {
        "catalog_rent_per_day_yen": best_daily,
        "plan_key": best_key,
        "plan_name": best_name,
    }


# ---------------------------------------------------------------------------
# Stay total
# ---------------------------------------------------------------------------

@dataclass
class StayBreakdown:
    rent_daily: int
    management_daily: int
    utilities_daily: int
    rent_total: int
    management_total: int
    utilities_total: int
    cleaning_fee: int
    contract_fee: int


@dataclass
class StayCalcResult:
    ok: bool
    stay_days: int | None = None
    plan_key: str | None = None
    plan_name: str | None = None
    used_fallback: bool = False
    breakdown: StayBreakdown | None = None
    grand_total: int | None = None
    warnings: list[str] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


CalcError = StayCalcResult  # alias for callers expecting CalcOutcome naming
CalcOutcome = StayCalcResult


def calculate_stay_total(
    *,
    check_in: str,
    check_out: str,
    plans: Sequence[PricePlan | Mapping[str, Any]],
    campaigns: Sequence[Campaign | Mapping[str, Any]] | None = None,
    contract_fee_yen: int | None = None,
    use_structured_campaigns: bool = True,
    month_days: int = MONTH_DAYS,
    on_date: str | None = None,
) -> StayCalcResult:
    """Compute inclusive stay total for a property's plans."""
    stay_days = calc_stay_days(check_in, check_out)
    if stay_days is None:
        if not check_in or not check_out:
            return StayCalcResult(ok=False, error="入居日と退去日を入力してください。")
        if parse_iso_date(check_in) is None or parse_iso_date(check_out) is None:
            return StayCalcResult(ok=False, error="日付の形式が正しくありません。")
        return StayCalcResult(ok=False, error="退去日を入居日以降に設定してください。")
    if stay_days < 1:
        return StayCalcResult(ok=False, error="ご利用日数は1日以上である必要があります。")

    resolved = resolve_plans_effective(plans, campaigns, on_date=on_date or check_in)
    selection = select_plan_for_stay(resolved, stay_days)
    if selection is None:
        return StayCalcResult(ok=False, stay_days=stay_days, error="計算可能な料金プランがありません。")

    selected: PricePlan = selection["selected"]  # type: ignore[assignment]
    if not isinstance(selected, PricePlan):
        selected = resolve_plan_effective(selected, campaigns, on_date=on_date or check_in)

    base_contract = CONTRACT_FEE_YEN if contract_fee_yen is None else int(contract_fee_yen)
    warnings: list[str] = []

    rent_daily: int
    cleaning_fee: int
    contract_fee: int

    if use_structured_campaigns and campaigns:
        applied = _apply_structured_campaigns(
            selected,
            stay_days=stay_days,
            check_in=check_in,
            campaigns=campaigns,
            base_contract_fee=base_contract,
            month_days=month_days,
        )
        rent_daily = applied["rent_daily"]
        cleaning_fee = applied["cleaning_fee"]
        contract_fee = applied["contract_fee"]
        warnings.extend(applied["notes"])
    else:
        rd = plan_rent_per_day(selected, month_days=month_days)
        rent_daily = rd if rd is not None else 0
        cleaning_fee = int(selected.cleaning_yen or 0)
        contract_fee = base_contract

    management_daily = plan_management_per_day(selected, month_days=month_days)
    utilities_daily = plan_utilities_per_day(selected, month_days=month_days)

    rent_total = rent_daily * stay_days
    management_total = management_daily * stay_days
    utilities_total = utilities_daily * stay_days
    grand_total = rent_total + management_total + utilities_total + cleaning_fee + contract_fee

    if selection.get("used_fallback"):
        label = selected.plan_name or selected.plan_key
        warnings.append(
            f"滞在日数（{stay_days}日）に完全一致するプラン帯がないため、"
            f"「{label}」で試算しています。"
        )
    if selected.campaign_expired:
        warnings.append(
            f"期限切れの{selected.expired_campaign_label or 'キャンペーン'}は適用せず、定価ベースで試算しています。"
        )
    elif selected.campaign_applied and selected.effective_campaign_label:
        warnings.append(f"有効なキャンペーン（{selected.effective_campaign_label}）を反映しています。")

    return StayCalcResult(
        ok=True,
        stay_days=stay_days,
        plan_key=selected.plan_key,
        plan_name=selected.plan_name,
        used_fallback=bool(selection.get("used_fallback")),
        breakdown=StayBreakdown(
            rent_daily=rent_daily,
            management_daily=management_daily,
            utilities_daily=utilities_daily,
            rent_total=rent_total,
            management_total=management_total,
            utilities_total=utilities_total,
            cleaning_fee=cleaning_fee,
            contract_fee=contract_fee,
        ),
        grand_total=grand_total,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Structured campaign application (yen / percent / package)
# ---------------------------------------------------------------------------

def _apply_structured_campaigns(
    selected: PricePlan,
    *,
    stay_days: int,
    check_in: str,
    campaigns: Sequence[Campaign | Mapping[str, Any]],
    base_contract_fee: int,
    month_days: int,
) -> dict[str, Any]:
    unit = selected.presentation_unit
    original_pres = selected.rent_original_yen
    if original_pres is None:
        original_pres = selected.effective_rent_yen or selected.rent_current_yen or 0
    original_daily = to_per_day(int(original_pres), unit, month_days=month_days) or 0
    fallback_daily = plan_rent_per_day(selected, month_days=month_days) or original_daily

    cleaning_fee = int(selected.cleaning_yen or 0)
    contract_fee = base_contract_fee
    notes: list[str] = []

    applicable = [
        c
        for c in campaigns
        if campaign_is_active_on(c, check_in)
        and campaign_targets_plan_key(c, selected.plan_key)
        and _campaign_stay_ok(c, stay_days)
    ]
    if not applicable:
        return {
            "rent_daily": fallback_daily,
            "cleaning_fee": cleaning_fee,
            "contract_fee": contract_fee,
            "notes": notes,
        }

    yen_cams = [c for c in applicable if _get(c, "discount_unit") == "yen" and _get(c, "discount_value") is not None]
    pct_cams = [c for c in applicable if _get(c, "discount_unit") == "percent" and _get(c, "discount_value") is not None]
    pkg_cams = [c for c in applicable if _get(c, "discount_unit") == "package"]

    rent_daily = original_daily
    used = False

    if yen_cams:
        c = yen_cams[0]
        value = int(_get(c, "discount_value"))
        period_max = _get(c, "period_max_days")
        dmax = _get(c, "discount_max_yen")
        apply_days = stay_days if period_max is None else min(stay_days, int(period_max))
        total_off = value * apply_days
        if dmax is not None and total_off > int(dmax):
            total_off = int(dmax)
        rent_daily = max(0, original_daily - (total_off // stay_days)) if stay_days > 0 else original_daily
        label = _get(c, "campaign_type") or _get(c, "title") or "割引"
        notes.append(f"{label}: 日額{value:,}円×{apply_days}日分を反映")
        used = True
    elif pct_cams:
        c = pct_cams[0]
        pct = int(_get(c, "discount_value"))
        period_max = _get(c, "period_max_days")
        dmax = _get(c, "discount_max_yen")
        apply_days = stay_days if period_max is None else min(stay_days, int(period_max))
        daily_off = (original_daily * pct) // 100
        total_off = daily_off * apply_days
        if dmax is not None and total_off > int(dmax):
            total_off = int(dmax)
        rent_daily = max(0, original_daily - (total_off // stay_days)) if stay_days > 0 else original_daily
        label = _get(c, "campaign_type") or _get(c, "title") or "割引"
        notes.append(f"{label}: {pct}%OFF×{apply_days}日分を反映")
        used = True
    else:
        rent_daily = fallback_daily

    for c in pkg_cams:
        label = _get(c, "campaign_type") or _get(c, "title") or "パッケージ"
        rent_ben = int(_get(c, "package_rent_benefit_yen") or 0)
        clean_ben = int(_get(c, "package_cleaning_benefit_yen") or 0)
        fee_ben = int(_get(c, "package_fee_benefit_yen") or 0)
        if rent_ben and stay_days > 0:
            rent_daily = max(0, rent_daily - rent_ben // stay_days)
        if clean_ben:
            cleaning_fee = max(0, cleaning_fee - clean_ben)
        if fee_ben:
            contract_fee = max(0, contract_fee - fee_ben)
        notes.append(f"{label}: パッケージお得を反映")
        used = True

    if not used:
        rent_daily = fallback_daily

    return {
        "rent_daily": rent_daily,
        "cleaning_fee": cleaning_fee,
        "contract_fee": contract_fee,
        "notes": notes,
    }


def _campaign_stay_ok(campaign: Campaign | Mapping[str, Any], stay_days: int) -> bool:
    smin = _get(campaign, "stay_min_days")
    smax = _get(campaign, "stay_max_days")
    if smin is not None and stay_days < int(smin):
        return False
    if smax is not None and stay_days > int(smax):
        return False
    return True


def _find_matching_campaign(
    plan: PricePlan,
    campaigns: Sequence[Campaign | Mapping[str, Any]],
    *,
    on_date: str | date,
) -> Campaign | Mapping[str, Any] | None:
    label = (plan.campaign_label or "").strip()
    generic_labels = {
        "キャンペーン",
        "キャンペーン適用",
        "割引キャンペーン",
        "キャンペーン料金",
    }
    for c in campaigns:
        if not campaign_is_active_on(c, on_date):
            continue
        if not campaign_targets_plan_key(c, plan.plan_key):
            continue
        ctype = (_get(c, "campaign_type") or "").strip()
        if not label:
            return c
        if ctype and (ctype in label or label in ctype or label.replace("キャンペーン", "") == ctype):
            return c
        # Generic site-wide promo labels: any active campaign row justifies discounted price
        if label in generic_labels or "キャンペーン" in label:
            return c
    return None


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plan_unit(plan: PricePlan | Mapping[str, Any]) -> str:
    return str(_get(plan, "presentation_unit") or "per_day")


def _plan_from_mapping(m: Mapping[str, Any]) -> PricePlan:
    return PricePlan(
        plan_key=str(m.get("plan_key") or m.get("plan_code") or "unknown"),
        plan_name=m.get("plan_name"),
        duration_min_days=int(m.get("duration_min_days") or 1),
        duration_max_days=m.get("duration_max_days"),
        available=bool(m.get("available", True)),
        presentation_unit=m.get("presentation_unit") or "per_day",
        rent_original_yen=_opt_int(m.get("rent_original_yen", m.get("original_daily_rent_yen"))),
        rent_current_yen=_opt_int(m.get("rent_current_yen", m.get("discounted_daily_rent_yen"))),
        management_yen=_opt_int(m.get("management_yen", m.get("management_fee_daily_yen"))),
        utilities_yen=_opt_int(m.get("utilities_yen")),
        utilities_included=bool(m.get("utilities_included", True)),
        cleaning_yen=_opt_int(m.get("cleaning_yen", m.get("cleaning_fee_yen"))),
        campaign_label=m.get("campaign_label"),
        raw_text=m.get("raw_text"),
        effective_rent_yen=_opt_int(m.get("effective_rent_yen", m.get("effective_daily_rent_yen"))),
        campaign_applied=bool(m.get("campaign_applied", False)),
        campaign_expired=bool(m.get("campaign_expired", False)),
        effective_campaign_label=m.get("effective_campaign_label"),
        expired_campaign_label=m.get("expired_campaign_label"),
        matched_campaign_type=m.get("matched_campaign_type"),
    )


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# BraTTo / Union duration presets (helpers for adapters)
# ---------------------------------------------------------------------------

BRATTO_DURATION_BANDS: dict[str, tuple[int, int | None]] = {
    "s_short": (1, 29),
    "short": (30, 90),
    "middle": (91, 180),
    "long": (181, None),
}

# Union: 1–3 / 3–7 / 7–24 months (day approx, exclusive upper bound as max inclusive)
UNION_DURATION_BANDS: dict[str, tuple[int, int | None]] = {
    "short": (30, 89),
    "middle": (90, 209),
    "long": (210, 729),
}


def duration_for_plan_key(plan_key: str, source: str = "bratto") -> tuple[int, int | None]:
    key = plan_key.lower().strip()
    bands = UNION_DURATION_BANDS if source == "unionmonthly" else BRATTO_DURATION_BANDS
    return bands.get(key, (1, None))
