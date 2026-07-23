"""Domain models for multi-source v2 (source-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

PresentationUnit = Literal["per_day", "per_month"]
EntityType = Literal["room", "building", "plan"]


@dataclass
class PropertyAccess:
    line_name: Optional[str] = None
    station_name: Optional[str] = None
    walk_minutes: Optional[int] = None
    raw_text: Optional[str] = None
    sort_order: int = 0


@dataclass
class PropertyImage:
    image_url: str
    image_type: Optional[str] = None  # thumbnail, floorplan, gallery, panorama, jsonld
    alt_text: Optional[str] = None
    sort_order: int = 0


@dataclass
class PropertyLink:
    link_type: str  # youtube, contact, map, panorama, option_guide, other
    url: str
    label: Optional[str] = None


@dataclass
class PropertyFeature:
    feature_name: str
    feature_category: Optional[str] = None
    raw_text: Optional[str] = None


@dataclass
class PricePlan:
    """Duration-banded price plan (source-agnostic).

    Amounts are stored in ``presentation_unit`` (per_day or per_month).
    Stay totals convert via ``domain.pricing.to_per_day``.
    """

    plan_key: str
    plan_name: Optional[str] = None
    duration_min_days: int = 1
    duration_max_days: Optional[int] = None  # None = no upper bound
    available: bool = True
    presentation_unit: PresentationUnit = "per_day"
    rent_original_yen: Optional[int] = None
    rent_current_yen: Optional[int] = None
    management_yen: Optional[int] = None
    utilities_yen: Optional[int] = None
    utilities_included: bool = True
    cleaning_yen: Optional[int] = None  # usually per-stay
    campaign_label: Optional[str] = None
    raw_text: Optional[str] = None
    # Resolved (not necessarily persisted as-is)
    effective_rent_yen: Optional[int] = None  # presentation unit
    campaign_applied: bool = False
    campaign_expired: bool = False
    effective_campaign_label: Optional[str] = None
    expired_campaign_label: Optional[str] = None
    matched_campaign_type: Optional[str] = None


@dataclass
class Campaign:
    campaign_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    target_period_text: Optional[str] = None
    target_condition_text: Optional[str] = None
    starts_on: Optional[str] = None
    ends_on: Optional[str] = None
    target_plan_key: Optional[str] = None  # None / "all" = all plans
    discount_unit: Optional[str] = None  # yen | percent | package | ...
    discount_value: Optional[int] = None
    discount_max_yen: Optional[int] = None
    period_max_days: Optional[int] = None
    stay_min_days: Optional[int] = None
    stay_max_days: Optional[int] = None
    contract_within_days: Optional[int] = None
    package_rent_benefit_yen: Optional[int] = None
    package_cleaning_benefit_yen: Optional[int] = None
    package_fee_benefit_yen: Optional[int] = None
    package_total_benefit_yen: Optional[int] = None
    structure_source: Optional[str] = None
    parse_ok: int = 0
    parse_warnings: Optional[str] = None
    raw_json: Optional[str] = None
    is_active: Optional[bool] = None


@dataclass
class PropertyDraft:
    """Normalized property ready for repository upsert."""

    source_site: str
    external_id: str
    entity_type: EntityType = "room"
    parent_external_id: Optional[str] = None
    title: Optional[str] = None
    detail_url: Optional[str] = None
    prefecture_slug: Optional[str] = None
    prefecture_name: Optional[str] = None
    municipality: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_source: Optional[str] = None
    geocode_confidence: Optional[float] = None
    layout: Optional[str] = None
    area_m2: Optional[float] = None
    area_m2_max: Optional[float] = None
    built_year: Optional[int] = None
    built_month: Optional[int] = None
    construction_year_text: Optional[str] = None
    capacity_text: Optional[str] = None
    structure: Optional[str] = None
    floors_text: Optional[str] = None
    floor_number: Optional[str] = None
    point_text: Optional[str] = None
    availability_text: Optional[str] = None
    min_stay_days: Optional[int] = None
    contract_fee_yen: Optional[int] = None
    is_active: bool = True
    detail_scraped_at: Optional[str] = None
    accesses: list[PropertyAccess] = field(default_factory=list)
    images: list[PropertyImage] = field(default_factory=list)
    links: list[PropertyLink] = field(default_factory=list)
    features: list[PropertyFeature] = field(default_factory=list)
    price_plans: list[PricePlan] = field(default_factory=list)
    campaigns: list[Campaign] = field(default_factory=list)
    raw_list_json: Optional[str] = None
    raw_detail_json: Optional[str] = None
    raw_html_path: Optional[str] = None
    parser_version: Optional[str] = None
