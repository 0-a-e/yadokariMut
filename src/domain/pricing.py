"""Pricing engine (SSOT for multi-source v2).

Stay total and effective rent live here. Frontend may mirror rules but BE is
authoritative for MCP / future estimate APIs. FE (lib/rentCalculator.ts) との
数値・プラン選択・警告文言の一致は contracts/stay_calc_cases.json の
parity テスト(tests/test_pricing_parity.py / rentCalculator.parity.test.ts)が保証する。

Rules
-----
- stay_days = inclusive(check_in, check_out)
- plan selection: first available plan where
    stay_days >= duration_min_days
    and (duration_max_days is None or stay_days <= duration_max_days)
  ordered by duration_min_days ascending. Fallback: next longer band, then shorter.
- per_month amounts convert with MONTH_DAYS (30).
- presentation_unit は per_day / per_month の 2 値のみ (正本:
  domain.models.PresentationUnit・DB は CHECK 制約で同一集合 — 決定 11)。
  未知単位は黙認換算せず None を返し、呼び出し側へ伝播する
  (算出不能プランは明示的な欠落として UI から除外)。
- total = (rent_per_day + mgmt_per_day + util_per_day) * stay_days
          + cleaning + (contract_fee or 0)
- contract_fee: 物件個別値 > サイト既定 (store.source_catalog.SOURCE_CATALOG
  の contract_fee_yen)。どちらも無い場合は None = 算出不能として総額から除外し
  warnings で明示する(根拠のない数値での補完は行わない)。API 応答への実効値の
  埋め込みは store.queries._common.resolve_contract_fee_yen が行う。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from typing import Any, Mapping, Sequence, Union

from domain.models import Campaign, PresentationUnit, PricePlan

MONTH_DAYS = 30
# 正式単位語彙の正本は domain.models.PresentationUnit
# (Literal["per_day", "per_month"]・DB は CHECK 制約で同一集合に限定 — 決定 11)。
# 旧来の同名言語 (PresentationUnit = str) は削除し型参照を統一した。


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
    """Convert an amount in presentation unit to per-day yen (integer floor).

    unit は正式語彙 per_day / per_month のみを受容する (正本:
    domain.models.PresentationUnit・決定 11)。daily/day/monthly/month などの
    エイリアスは解決しない (エイリアス解決はパーサ/正規化層の責務)。
    未知単位は黙認 per_day 換算せず None を返し、呼び出し側へ伝播する
    (「約 7 倍過大」や「0 円」の無声失敗を禁止)。
    """
    if amount is None:
        return None
    try:
        n = int(amount)
    except (TypeError, ValueError):
        return None
    u = (unit or "").lower().strip()
    if u == "per_day":
        return n
    if u == "per_month":
        if month_days <= 0:
            return None
        return n // month_days
    # 未知単位: 換算不能として None (決定 11)
    return None


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


def plan_management_per_day(
    plan: PricePlan | Mapping[str, Any], *, month_days: int = MONTH_DAYS
) -> int | None:
    """共益費の日額 (未記載は 0 円。単位未知など換算不能なら None — 決定 11).

    None (算出不能) を 0 円へ畳み込まない。畳み込みは日額合計を無声的に
    誤表示するため、呼び出し側は None を「明示的な欠落」として扱う。
    """
    unit = _plan_unit(plan)
    mgmt = _get(plan, "management_yen")
    if mgmt is None:
        return 0
    return to_per_day(int(mgmt), unit, month_days=month_days)


def plan_utilities_per_day(
    plan: PricePlan | Mapping[str, Any], *, month_days: int = MONTH_DAYS
) -> int | None:
    """水光熱費の日額 (込み or 未記載は 0 円。換算不能なら None — 決定 11)."""
    if _get(plan, "utilities_included", True):
        return 0
    unit = _plan_unit(plan)
    util = _get(plan, "utilities_yen")
    if util is None:
        return 0
    return to_per_day(int(util), unit, month_days=month_days)


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

def _campaign_as_dict(campaign: Campaign | Mapping[str, Any]) -> dict[str, Any]:
    """Campaign dataclass / mapping を浅い dict コピーへ正規化する内部ヘルパ."""
    if isinstance(campaign, Mapping):
        return dict(campaign)
    return {f.name: getattr(campaign, f.name) for f in fields(campaign)}


def campaign_with_plan_key(campaign: Campaign | Mapping[str, Any]) -> dict[str, Any]:
    """target_plan_code (legacy) を target_plan_key へ正規化したコピーを返す (key 優先).

    DB 列は target_plan_key のみを正本とする (store.schema)。bratto normalize 等
    が legacy の target_plan_code のみを生成するため、domain 側計算に渡す前に
    本関数で key へ寄せる。target_plan_key が既にある (空でない) 場合は key を
    優先し code で上書きしない。入力は変更しない (純関数)。
    """
    c = _campaign_as_dict(campaign)
    if not c.get("target_plan_key") and c.get("target_plan_code"):
        c["target_plan_key"] = c["target_plan_code"]
    return c


def campaign_with_plan_code_alias(campaign: Campaign | Mapping[str, Any]) -> dict[str, Any]:
    """target_plan_key を target_plan_code (legacy alias) へ写像したコピーを返す (API 出力用).

    API / MCP 応答は legacy 同義キー target_plan_code を継続して載せる
    (api_models.Campaign 契約)。DB 列は target_plan_key のみのため、行を応答
    辞書へ変換する際に本関数でエイリアスを付与する。入力は変更しない (純関数)。
    """
    c = _campaign_as_dict(campaign)
    c["target_plan_code"] = c.get("target_plan_key")
    return c


def campaign_targets_plan_key(campaign: Campaign | Mapping[str, Any], plan_key: str | None) -> bool:
    # キー選択ロジックの SSOT は campaign_with_plan_key (key 優先・code は legacy)
    target = (campaign_with_plan_key(campaign).get("target_plan_key") or "").strip().lower()
    if not target or target == "all":
        return True
    if not plan_key:
        # 対象プランキーが特定できないプランには適用しない(割引の意図しない全局適用を防ぐ)
        return False
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
    contract_fee: int | None


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

    # None = 物件値・サイト既定ともに無く算出不能。総額から除外し warnings で明示
    base_contract = None if contract_fee_yen is None else int(contract_fee_yen)
    warnings: list[str] = []
    notes: list[str] = []

    rent_daily: int | None
    cleaning_fee: int
    contract_fee: int | None

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
        notes = applied["notes"]
    else:
        # 算出不能 (None) は 0 円へ畳み込まず、後段で欠落扱い (決定 11)
        rent_daily = plan_rent_per_day(selected, month_days=month_days)
        cleaning_fee = int(selected.cleaning_yen or 0)
        contract_fee = base_contract

    management_daily = plan_management_per_day(selected, month_days=month_days)
    utilities_daily = plan_utilities_per_day(selected, month_days=month_days)

    # 決定 11: 日額のいずれかが算出不能 (単位未知等) ならそのプランは
    # 明示的な欠落として計算しない (0 円畳み込みによる無声失敗を禁止)。
    # calculate_stay_total の本番呼び出しは無いため契約影響なし (テスト専用)。
    if rent_daily is None or management_daily is None or utilities_daily is None:
        return StayCalcResult(
            ok=False,
            stay_days=stay_days,
            plan_key=selected.plan_key,
            plan_name=selected.plan_name,
            error="料金プランの金額が算出できないため、滞在合計を計算できません。",
        )

    rent_total = rent_daily * stay_days
    management_total = management_daily * stay_days
    utilities_total = utilities_daily * stay_days
    grand_total = (
        rent_total + management_total + utilities_total + cleaning_fee + (contract_fee or 0)
    )

    # 警告の順序・文言は FE rentCalculator.calculateRentTotalByDays と同一に保つ。
    # contracts/stay_calc_cases.json の parity テストが文言レベルの一致を保証する。
    if selection.get("used_fallback"):
        plan_name = selected.plan_name or ""
        warnings.append(
            f"この物件に{stay_days}日の滞在に対応する料金プラン帯がないため、"
            f"{plan_name}の料金で試算しています。"
        )
    if contract_fee is None:
        warnings.append(
            "契約事務手数料が不明(取得元サイトの既定が未登録)のため、総額から除外しています。"
        )
    if utilities_daily > 0:
        unit_label = "月" if (selected.presentation_unit or "per_day") == "per_month" else "日"
        warnings.append(
            f"光熱費（{selected.utilities_yen:,}円/{unit_label}）を"
            f"日額{utilities_daily:,}円で加算しています。"
        )
    if selected.campaign_expired:
        warnings.append(
            f"期限切れの{selected.expired_campaign_label or 'キャンペーン'}は適用せず、定価ベースで試算しています。"
        )
    elif selected.campaign_applied and selected.effective_campaign_label:
        warnings.append(f"有効なキャンペーン（{selected.effective_campaign_label}）を反映しています。")
    elif selected.campaign_label and selected.campaign_applied:
        warnings.append(f"表示中の賃料（{selected.campaign_label}）を使用しています。")
    warnings.extend(notes)

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
    base_contract_fee: int | None,
    month_days: int,
) -> dict[str, Any]:
    unit = selected.presentation_unit
    original_pres = selected.rent_original_yen
    if original_pres is None:
        original_pres = selected.effective_rent_yen or selected.rent_current_yen or 0
    # 換算不能 (単位未知) は None を保持し 0 円へ畳み込まない (決定 11)
    original_daily = to_per_day(int(original_pres), unit, month_days=month_days)
    fallback_daily = plan_rent_per_day(selected, month_days=month_days)
    if fallback_daily is None:
        fallback_daily = original_daily

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

    # 割引の基準となる original_daily が算出不能なら該当適用をスキップし
    # fallback (= plan_rent_per_day ベース) を使う。それも不能なら None が
    # calculate_stay_total へ伝播し、プランは明示的な欠落として扱われる (決定 11)。
    if yen_cams and original_daily is not None:
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
    elif pct_cams and original_daily is not None:
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
        # rent_daily が算出不能 (None) の場合は減額適用も不能のためスキップ
        if rent_ben and stay_days > 0 and rent_daily is not None:
            rent_daily = max(0, rent_daily - rent_ben // stay_days)
        if clean_ben:
            cleaning_fee = max(0, cleaning_fee - clean_ben)
        # 手数料が不明のまま減額すると誤表示になるため、None は None を維持
        if fee_ben and contract_fee is not None:
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


def _plan_unit(plan: PricePlan | Mapping[str, Any]) -> PresentationUnit:
    """プランの提示単位 (NULL/空は per_day 既定。語彙正本: domain.models.PresentationUnit)。"""
    return str(_get(plan, "presentation_unit") or "per_day")  # type: ignore[return-value]


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
