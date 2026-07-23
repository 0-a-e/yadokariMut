"""Convert legacy bratto normalize_property() dict → PropertyDraft."""

from __future__ import annotations

from typing import Any

from domain.models import (
    Campaign,
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
    PropertyLink,
)
from domain.pricing import BRATTO_DURATION_BANDS


def draft_from_normalized(normalized: dict[str, Any]) -> PropertyDraft:
    """Map v1 normalized property dict into multi-source v2 PropertyDraft."""
    plans: list[PricePlan] = []
    for rp in normalized.get("rent_plans") or []:
        key = (rp.get("plan_code") or "other").strip() or "other"
        dmin, dmax = BRATTO_DURATION_BANDS.get(key, (1, None))
        available = rp.get("available", 1)
        if isinstance(available, bool):
            available_b = available
        else:
            available_b = bool(int(available)) if available is not None else True
        plans.append(
            PricePlan(
                plan_key=key,
                plan_name=rp.get("plan_name"),
                duration_min_days=dmin,
                duration_max_days=dmax,
                available=available_b,
                presentation_unit="per_day",
                rent_original_yen=_i(rp.get("original_daily_rent_yen")),
                rent_current_yen=_i(rp.get("discounted_daily_rent_yen")),
                management_yen=_i(rp.get("management_fee_daily_yen")),
                utilities_included=True,
                cleaning_yen=_i(rp.get("cleaning_fee_yen")),
                campaign_label=rp.get("campaign_label"),
                raw_text=rp.get("raw_text"),
            )
        )

    campaigns: list[Campaign] = []
    for c in normalized.get("campaigns") or []:
        campaigns.append(
            Campaign(
                campaign_type=c.get("campaign_type") or c.get("type"),
                title=c.get("title"),
                content=c.get("content"),
                target_period_text=c.get("target_period_text"),
                target_condition_text=c.get("target_condition_text"),
                starts_on=c.get("starts_on"),
                ends_on=c.get("ends_on"),
                target_plan_key=c.get("target_plan_code") or c.get("target_plan_key"),
                discount_unit=c.get("discount_unit"),
                discount_value=_i(c.get("discount_value")),
                discount_max_yen=_i(c.get("discount_max_yen")),
                period_max_days=_i(c.get("period_max_days")),
                stay_min_days=_i(c.get("stay_min_days")),
                stay_max_days=_i(c.get("stay_max_days")),
                contract_within_days=_i(c.get("contract_within_days")),
                package_rent_benefit_yen=_i(c.get("package_rent_benefit_yen")),
                package_cleaning_benefit_yen=_i(c.get("package_cleaning_benefit_yen")),
                package_fee_benefit_yen=_i(c.get("package_fee_benefit_yen")),
                package_total_benefit_yen=_i(c.get("package_total_benefit_yen")),
                structure_source=c.get("structure_source"),
                parse_ok=int(c.get("parse_ok") or 0),
                parse_warnings=c.get("parse_warnings"),
                raw_json=c.get("raw_json"),
            )
        )

    accesses = [
        PropertyAccess(
            line_name=a.get("line_name"),
            station_name=a.get("station_name"),
            walk_minutes=_i(a.get("walk_minutes")),
            raw_text=a.get("raw_text"),
            sort_order=int(a.get("sort_order") or 0),
        )
        for a in (normalized.get("accesses") or [])
    ]
    images = [
        PropertyImage(
            image_url=img["image_url"],
            image_type=img.get("image_type"),
            alt_text=img.get("alt_text"),
            sort_order=int(img.get("sort_order") or 0),
        )
        for img in (normalized.get("images") or [])
        if img.get("image_url")
    ]
    links = [
        PropertyLink(
            link_type=lk.get("link_type") or "other",
            url=lk["url"],
            label=lk.get("label"),
        )
        for lk in (normalized.get("links") or [])
        if lk.get("url")
    ]
    features = [
        PropertyFeature(
            feature_name=f["feature_name"],
            feature_category=f.get("feature_category"),
            raw_text=f.get("raw_text"),
        )
        for f in (normalized.get("features") or [])
        if f.get("feature_name")
    ]

    return PropertyDraft(
        source_site=normalized.get("source_site") or "bratto",
        external_id=str(normalized.get("source_property_id") or normalized.get("external_id") or ""),
        entity_type="room",
        title=normalized.get("title"),
        detail_url=normalized.get("detail_url"),
        prefecture_slug=normalized.get("prefecture_slug"),
        prefecture_name=normalized.get("prefecture_name"),
        municipality=normalized.get("municipality"),
        address=normalized.get("address"),
        lat=normalized.get("lat"),
        lng=normalized.get("lng"),
        geocode_source=normalized.get("geocode_source"),
        geocode_confidence=normalized.get("geocode_confidence"),
        layout=normalized.get("layout"),
        area_m2=normalized.get("area_m2"),
        built_year=_i(normalized.get("built_year")),
        built_month=_i(normalized.get("built_month")),
        construction_year_text=normalized.get("construction_year_text"),
        capacity_text=normalized.get("capacity_text"),
        structure=normalized.get("structure"),
        floors_text=normalized.get("floors_text"),
        point_text=normalized.get("point_text"),
        availability_text=normalized.get("availability_text"),
        detail_scraped_at=normalized.get("detail_scraped_at"),
        accesses=accesses,
        images=images,
        links=links,
        features=features,
        price_plans=plans,
        campaigns=campaigns,
        parser_version="bratto-normalize-v2",
    )


def _i(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
