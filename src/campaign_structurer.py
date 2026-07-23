#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mechanical campaign structuring for BraTTo campaigns.

Primary path is type rules + regex (no LLM required). Optional merge of
official detail-page ``cam_*`` JS objects when available.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# campaign_type → default target plan
TYPE_TO_PLAN: dict[str, str] = {
    "早割": "all",
    "ミドル割": "middle",
    "ロング割": "long",
    "特別割引": "s_short",
    "ポッキリ割": "short",
    "500円割": "all",  # stay band overrides via stay_min/max when present
}

CAM_LABEL_TO_TYPE = {
    "早割": "早割",
    "特別割引": "特別割引",
    "ミドル割": "ミドル割",
    "ロング割": "ロング割",
    "500円割": "500円割",
    "ポッキリ割": "ポッキリ割",
    "短期割": "特別割引",
}

DISCOUNT_UNITS = frozenset({
    "yen", "percent", "package", "pokkiri", "free_first_week", "unknown",
})

# Official cam_* object in detail HTML
CAM_JS_RE = re.compile(
    r"var\s+cam_(\d+)\s*=\s*\{([^}]*)\}",
    re.MULTILINE,
)
CAM_FIELD_RE = re.compile(
    r"cam_([a-z_]+)\s*:\s*(?:\"([^\"]*)\"|'([^']*)'|([0-9.]+))",
)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _empty_structure() -> dict[str, Any]:
    return {
        "target_plan_code": None,
        "discount_unit": None,
        "discount_value": None,
        "discount_max_yen": None,
        "period_max_days": None,
        "stay_min_days": None,
        "stay_max_days": None,
        "contract_within_days": None,
        "package_rent_benefit_yen": None,
        "package_cleaning_benefit_yen": None,
        "package_fee_benefit_yen": None,
        "package_total_benefit_yen": None,
        "structure_source": "unknown",
        "parse_ok": 0,
        "parse_warnings": [],
    }


def extract_cam_js_objects(html: str | None) -> list[dict[str, Any]]:
    """Parse official ``var cam_N = {...}`` blocks from detail HTML."""
    if not html:
        return []
    results: list[dict[str, Any]] = []
    for _idx, body in CAM_JS_RE.findall(html):
        obj: dict[str, Any] = {}
        for key, s1, s2, num in CAM_FIELD_RE.findall(body):
            if s1 != "":
                obj[key] = s1
            elif s2 != "":
                obj[key] = s2
            else:
                # int if whole number else float
                if "." in num:
                    obj[key] = float(num)
                else:
                    obj[key] = int(num)
        if obj.get("label"):
            results.append(obj)
    return results


def match_cam_js(
    campaign_type: str | None,
    title: str | None,
    cam_objects: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Match a scraped campaign box to a cam_* object by label."""
    if not cam_objects:
        return None
    label_hint = (campaign_type or "").strip()
    title_text = title or ""

    for cam in cam_objects:
        lab = str(cam.get("label") or "").strip()
        if not lab:
            continue
        if label_hint and (lab == label_hint or lab in label_hint or label_hint in lab):
            return cam
        if lab and lab in title_text:
            return cam
    return None


def structure_from_cam_js(cam: dict[str, Any], campaign_type: str | None = None) -> dict[str, Any]:
    """Map official cam_* fields into our structured schema."""
    out = _empty_structure()
    out["structure_source"] = "cam_js"
    out["parse_ok"] = 1

    label = str(cam.get("label") or campaign_type or "").strip()
    ctype = CAM_LABEL_TO_TYPE.get(label, campaign_type)
    out["target_plan_code"] = TYPE_TO_PLAN.get(ctype or "", None)

    unit = str(cam.get("discount_unit") or "").lower()
    if unit in ("yen", "percent"):
        out["discount_unit"] = unit
    else:
        out["discount_unit"] = "unknown"
        out["parse_warnings"].append(f"unknown cam_discount_unit={unit}")

    out["discount_value"] = _to_int(cam.get("discount"))
    dmax = _to_int(cam.get("discount_max"))
    # official uses 0 for "no max"
    out["discount_max_yen"] = dmax if dmax and dmax > 0 else None
    out["period_max_days"] = _to_int(cam.get("period_max"))
    out["stay_min_days"] = _to_int(cam.get("conditions_period"))
    stay_max = _to_int(cam.get("conditions_period_max"))
    # 9999 means unbounded in official JS
    out["stay_max_days"] = stay_max if stay_max and stay_max < 9000 else None

    # 特別割引 with percent + short stay band
    if (ctype == "特別割引" or label == "特別割引") and not out["target_plan_code"]:
        out["target_plan_code"] = "s_short"
    if ctype == "早割" or label == "早割":
        out["target_plan_code"] = "all"

    if out["discount_value"] is None:
        out["parse_ok"] = 0
        out["parse_warnings"].append("cam_js missing discount")

    return out


def _extract_contract_within_days(text: str) -> int | None:
    # 本日より3日以内にご契約 / 本日より14日間以内にご入居
    m = re.search(r"本日より\s*(\d+)\s*日(?:間)?以内", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*日以内にご契約", text)
    if m:
        return int(m.group(1))
    return None


def _extract_common_discount_fields(text: str, out: dict[str, Any]) -> None:
    # Prefer explicit daily-yen discount over %OFF (titles sometimes append garbage like "1000%OFF!")
    m_yen = re.search(r"1日(?:あたり)?\s*([0-9,]+)\s*円\s*割引", text)
    m_pct = re.search(r"(\d+)\s*%\s*OFF", text, re.I)
    if m_yen:
        out["discount_value"] = int(m_yen.group(1).replace(",", ""))
        out["discount_unit"] = "yen"
    elif m_pct:
        pct = int(m_pct.group(1))
        if 1 <= pct <= 100:
            out["discount_value"] = pct
            out["discount_unit"] = "percent"

    # Lump-sum OFF: 1万円OFF / 10000円OFF
    if out.get("discount_unit") is None:
        m = re.search(r"([0-9,]+)\s*万円\s*OFF", text, re.I)
        if m:
            out["discount_value"] = int(m.group(1).replace(",", "")) * 10000
            out["discount_unit"] = "yen"
            out["discount_max_yen"] = out["discount_value"]
        else:
            m = re.search(r"賃料から\s*([0-9,]+)\s*円\s*OFF", text, re.I)
            if m:
                out["discount_value"] = int(m.group(1).replace(",", ""))
                out["discount_unit"] = "yen"

    m = re.search(r"最大\s*([0-9,]+)\s*円\s*割引", text)
    if m:
        out["discount_max_yen"] = int(m.group(1).replace(",", ""))
    else:
        m = re.search(r"最大\s*([0-9,]+)\s*割引", text)
        if m and "日" not in m.group(0):
            out["discount_max_yen"] = int(m.group(1).replace(",", ""))

    m = re.search(r"最大\s*(\d+)\s*日間?\s*適用", text)
    if m:
        out["period_max_days"] = int(m.group(1))

    # 60日間以上 / 7日間以上のご利用
    m = re.search(r"(\d+)\s*日間?以上", text)
    if m:
        out["stay_min_days"] = int(m.group(1))

    # 最大180日間 1日500円
    m = re.search(r"最大\s*(\d+)\s*日間", text)
    if m and out.get("period_max_days") is None:
        out["period_max_days"] = int(m.group(1))


def _parse_package_middle(text: str, out: dict[str, Any]) -> bool:
    # 最大12万円+清掃費27,500円の半額＝133,750円
    m = re.search(
        r"最大?\s*([0-9.]+)\s*万円\s*\+\s*清掃費\s*([0-9,]+)\s*円(?:の半額)?\s*＝\s*([0-9,]+)\s*円",
        text,
    )
    if not m:
        return False
    man = float(m.group(1))
    cleaning = int(m.group(2).replace(",", ""))
    total = int(m.group(3).replace(",", ""))
    out["discount_unit"] = "package"
    out["package_rent_benefit_yen"] = int(man * 10000)
    # 「半額」→ cleaning benefit is half of listed fee when phrase present
    if "半額" in text:
        out["package_cleaning_benefit_yen"] = cleaning // 2 if cleaning % 2 == 0 else int(cleaning * 0.5)
    else:
        out["package_cleaning_benefit_yen"] = cleaning
    out["package_total_benefit_yen"] = total
    out["discount_value"] = total  # total package benefit as summary
    return True


def _parse_package_long(text: str, out: dict[str, Any]) -> bool:
    # 12万円+清掃費38,500円+契約事務手数料5,500円＝164,000円
    m = re.search(
        r"([0-9.]+)\s*万円\s*\+\s*清掃費\s*([0-9,]+)\s*円\s*\+\s*契約事務手数料\s*([0-9,]+)\s*円\s*＝\s*([0-9,]+)\s*円",
        text,
    )
    if not m:
        return False
    man = float(m.group(1))
    cleaning = int(m.group(2).replace(",", ""))
    fee = int(m.group(3).replace(",", ""))
    total = int(m.group(4).replace(",", ""))
    out["discount_unit"] = "package"
    out["package_rent_benefit_yen"] = int(man * 10000)
    out["package_cleaning_benefit_yen"] = cleaning
    out["package_fee_benefit_yen"] = fee
    out["package_total_benefit_yen"] = total
    out["discount_value"] = total
    return True


def _parse_pokkiri(text: str, out: dict[str, Any]) -> bool:
    m = re.search(r"1ヶ月\s*([0-9,]+)\s*万円", text)
    if not m:
        m = re.search(r"一ヶ月\s*([0-9,]+)\s*万円", text)
    if not m:
        return False
    man = int(m.group(1).replace(",", ""))
    out["discount_unit"] = "pokkiri"
    out["discount_value"] = man * 10000  # monthly fixed yen
    if out.get("stay_min_days") is None:
        m2 = re.search(r"(\d+)\s*日以上", text)
        out["stay_min_days"] = int(m2.group(1)) if m2 else 30
    return True


def structure_mechanically(
    campaign_type: str | None,
    title: str | None,
    content: str | None,
    period_text: str | None = None,
    condition_text: str | None = None,
) -> dict[str, Any]:
    """Structure a campaign from scraped text fields only."""
    out = _empty_structure()
    out["structure_source"] = "mechanical"
    ctype = (campaign_type or "").strip()
    text = " ".join(
        x for x in [title or "", content or "", period_text or "", condition_text or ""] if x
    )

    # Plan from type table first
    if ctype in TYPE_TO_PLAN:
        out["target_plan_code"] = TYPE_TO_PLAN[ctype]
    else:
        # keyword fallback
        lower = text.lower()
        if re.search(r"ミドル", lower):
            out["target_plan_code"] = "middle"
        elif re.search(r"ロング", lower):
            out["target_plan_code"] = "long"
        elif re.search(r"sショート|1ヶ月未満|短期", lower):
            out["target_plan_code"] = "s_short"
        elif re.search(r"ショート|1ヶ月", lower):
            out["target_plan_code"] = "short"
        elif re.search(r"ご紹介|お友達|全員", lower):
            out["target_plan_code"] = "all"

    out["contract_within_days"] = _extract_contract_within_days(text)
    _extract_common_discount_fields(text, out)

    if "初週" in text and "無料" in text:
        out["discount_unit"] = "free_first_week"
        out["period_max_days"] = out.get("period_max_days") or 7
        out["parse_ok"] = 1

    if ctype == "ミドル割" or (not ctype and "ミドルプラン" in text):
        out["target_plan_code"] = "middle"
        if _parse_package_middle(text, out):
            out["parse_ok"] = 1
        else:
            out["parse_warnings"].append("middle package parse failed")
            out["discount_unit"] = out.get("discount_unit") or "package"

    elif ctype == "ロング割" or (not ctype and "ロングプラン" in text):
        out["target_plan_code"] = "long"
        if _parse_package_long(text, out):
            out["parse_ok"] = 1
        else:
            out["parse_warnings"].append("long package parse failed")
            out["discount_unit"] = out.get("discount_unit") or "package"

    elif ctype == "ポッキリ割" or "ポッキリ" in text:
        out["target_plan_code"] = out.get("target_plan_code") or "short"
        if _parse_pokkiri(text, out):
            out["parse_ok"] = 1
        else:
            out["parse_warnings"].append("pokkiri parse failed")

    elif ctype == "早割":
        out["target_plan_code"] = "all"
        if out.get("discount_unit") == "yen" and out.get("discount_value"):
            out["parse_ok"] = 1
            # defaults from dominant template
            out["period_max_days"] = out.get("period_max_days") or 120
            out["discount_max_yen"] = out.get("discount_max_yen") or (
                out["discount_value"] * out["period_max_days"]
                if out.get("discount_value") and out.get("period_max_days")
                else None
            )
        else:
            out["parse_warnings"].append("hayawari discount not found")

    elif ctype == "特別割引":
        out["target_plan_code"] = "s_short"
        if out.get("discount_unit") == "percent" and out.get("discount_value") is not None:
            out["parse_ok"] = 1
            out["period_max_days"] = out.get("period_max_days") or 14
            out["stay_min_days"] = out.get("stay_min_days") or 1
            out["stay_max_days"] = out.get("stay_max_days") or 29
        elif out.get("discount_unit") == "yen" and out.get("discount_value") is not None:
            # e.g. 1日500円割引 / 1万円OFF
            out["parse_ok"] = 1
            if out.get("period_max_days") is None and "1日" not in text:
                # lump-sum OFF: treat as one-shot max
                out["discount_max_yen"] = out.get("discount_max_yen") or out["discount_value"]
        elif out.get("discount_unit") == "free_first_week":
            out["parse_ok"] = 1
        else:
            out["parse_warnings"].append("special discount percent not found")

    elif ctype == "500円割":
        out["discount_unit"] = "yen"
        out["discount_value"] = out.get("discount_value") or 500
        # stay_min from 60日間以上 / 7日間以上
        if out.get("stay_min_days") and out.get("period_max_days"):
            out["parse_ok"] = 1
            out["target_plan_code"] = "all"
        elif out.get("discount_value"):
            out["parse_ok"] = 1
            out["parse_warnings"].append("500yen partial stay bounds")
        else:
            out["parse_warnings"].append("500yen parse incomplete")

    else:
        # generic: accept if we got a unit+value
        if out.get("discount_unit") in ("yen", "percent") and out.get("discount_value") is not None:
            out["parse_ok"] = 1
        elif out.get("target_plan_code"):
            out["parse_warnings"].append("plan only; discount shape unknown")
        else:
            out["parse_warnings"].append("unclassified campaign")

    if out.get("discount_unit") is None:
        out["discount_unit"] = "unknown"

    if out["parse_ok"] and out.get("target_plan_code") is None:
        out["target_plan_code"] = "UNKNOWN"

    return out


def merge_structures(
    mechanical: dict[str, Any],
    cam_js: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer cam_js numeric fields when present; keep mechanical package fields."""
    if not cam_js:
        return mechanical

    merged = dict(mechanical)
    warnings = list(mechanical.get("parse_warnings") or [])

    # cam_js wins for daily/percent style discounts
    if cam_js.get("discount_unit") in ("yen", "percent"):
        for key in (
            "discount_unit",
            "discount_value",
            "discount_max_yen",
            "period_max_days",
            "stay_min_days",
            "stay_max_days",
        ):
            if cam_js.get(key) is not None:
                merged[key] = cam_js[key]
        merged["structure_source"] = "cam_js+mechanical"
        merged["parse_ok"] = 1 if cam_js.get("parse_ok") else merged.get("parse_ok", 0)

    # plan: cam_js type mapping if mechanical missing
    if not merged.get("target_plan_code") and cam_js.get("target_plan_code"):
        merged["target_plan_code"] = cam_js["target_plan_code"]

    # early bird always all
    if mechanical.get("target_plan_code") == "all" or cam_js.get("target_plan_code") == "all":
        if (mechanical.get("structure_source") == "mechanical" and
                any(w for w in [])):
            pass
        # Prefer explicit all for 早割
        if merged.get("discount_unit") == "yen" and merged.get("discount_value") == 1000:
            # keep plan from mechanical if all
            if mechanical.get("target_plan_code") == "all":
                merged["target_plan_code"] = "all"

    if cam_js.get("parse_warnings"):
        warnings.extend(cam_js["parse_warnings"])
    merged["parse_warnings"] = warnings
    return merged


def structure_campaign(
    campaign_type: str | None = None,
    title: str | None = None,
    content: str | None = None,
    period_text: str | None = None,
    condition_text: str | None = None,
    cam_objects: list[dict[str, Any]] | None = None,
    starts_on: str | None = None,
    ends_on: str | None = None,
) -> dict[str, Any]:
    """Full structure pipeline for one campaign."""
    # Import here to avoid circular imports at module load in some contexts
    from parser import parse_dates_from_text

    mechanical = structure_mechanically(
        campaign_type, title, content, period_text, condition_text
    )

    cam_match = match_cam_js(campaign_type, title, cam_objects)
    cam_struct = structure_from_cam_js(cam_match, campaign_type) if cam_match else None
    structured = merge_structures(mechanical, cam_struct)

    # Dates: keep provided, else parse period text with improved helper
    s_on, e_on = starts_on, ends_on
    if (not s_on or not e_on) and period_text:
        ps, pe = parse_dates_from_text(period_text)
        s_on = s_on or ps
        e_on = e_on or pe

    structured["starts_on"] = s_on
    structured["ends_on"] = e_on
    structured["parse_warnings_json"] = json.dumps(
        structured.get("parse_warnings") or [], ensure_ascii=False
    )
    return structured


def warnings_list(structured: dict[str, Any]) -> list[str]:
    w = structured.get("parse_warnings")
    if isinstance(w, list):
        return w
    raw = structured.get("parse_warnings_json")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return [str(raw)]
    return []
