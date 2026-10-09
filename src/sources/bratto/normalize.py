"""BraTTo 一覧+詳細抽出結果の正規化 (normalize_property)。

県スラッグ集合は config.json の sources.bratto.prefectures 由来。
県名は config の name を優先し、未設定分は store.pref_master で補完する。
"""

from __future__ import annotations

import json
import logging
import re

from store.pref_master import pref_display_name
from store.source_catalog import load_app_config

from sources.bratto.campaign_structurer import structure_campaign
from sources.bratto.plans import resolve_bratto_plan_code
from sources.parsing import (
    parse_access_parts,
    parse_area,
    parse_dates_from_text,
    parse_floor_text,
    parse_japanese_era,
    parse_money,
)

logger = logging.getLogger(__name__)

_prefecture_name_to_slug = None
_prefecture_slug_to_name = None


def _load_prefecture_map():
    """config.json sources.bratto.prefectures の県名 ↔ スラッグマップ。

    パスは load_app_config() (store.source_catalog) に一元化。
    県名は config の name、未設定分は store.pref_master.pref_display_name
    で補完するため config 側の name 削除でも 0 件化しない。
    単一HTML取り込み(ingest_detail_html)経路の県フォールバックが
    このマップに依存するため、読み込み結果はモジュール内でキャッシュする。
    """
    global _prefecture_name_to_slug, _prefecture_slug_to_name
    if _prefecture_name_to_slug is not None:
        return _prefecture_name_to_slug, _prefecture_slug_to_name

    name_to_slug = {}
    slug_to_name = {}
    try:
        config = load_app_config()
        prefs = config.get("sources", {}).get("bratto", {}).get("prefectures", {})
        for slug, val in prefs.items():
            # name 未設定の slug は pref_master 正本から補完する
            # (config 側の name 削除でマップが空になる事故を防ぐ)
            name = val.get("name") or pref_display_name(slug)
            if name:
                name_to_slug[name] = slug
                slug_to_name[slug] = name
    except Exception:
        logger.warning("bratto prefecture map load failed", exc_info=True)
    _prefecture_name_to_slug = name_to_slug
    _prefecture_slug_to_name = slug_to_name
    return name_to_slug, slug_to_name


def normalize_property(list_data, detail_data):
    """
    Combines and normalizes property list data and detail data.
    """
    normalized = {}
    
    # 1. Base property info
    normalized["source_site"] = "bratto"
    normalized["source_property_id"] = list_data.get("room_id")
    normalized["title"] = detail_data.get("json_ld", {}).get("name") or list_data.get("title")
    normalized["detail_url"] = list_data.get("detail_url")
    
    # Load prefecture maps from config.json
    name_to_slug, slug_to_name = _load_prefecture_map()

    # Address, Lat/Lng from JSON-LD or spec table or list data
    address = list_data.get("address")
    if not address and "specs" in detail_data and "住所" in detail_data["specs"]:
        address = detail_data["specs"]["住所"]

    # Precedence for prefecture_name:
    # 1. JSON-LD addressRegion (if available)
    # 2. list_data's prefecture_name (scraped from list page or input json)
    # 3. Parsed from address prefix
    # 4. Fallback default based on list_data's prefecture_slug
    # 5. Default "東京都"
    prefecture_name = None
    json_ld_addr = detail_data.get("json_ld", {}).get("address", {})
    if json_ld_addr:
        prefecture_name = json_ld_addr.get("addressRegion")
        municipality = json_ld_addr.get("addressLocality")
        street = json_ld_addr.get("streetAddress")
        if prefecture_name and municipality and street:
            address = f"{prefecture_name}{municipality}{street}"
    else:
        municipality = None

    if not prefecture_name:
        prefecture_name = list_data.get("prefecture_name")

    if not prefecture_name and address:
        for name in name_to_slug.keys():
            if address.startswith(name):
                prefecture_name = name
                break

    if not prefecture_name:
        pref_slug = list_data.get("prefecture_slug")
        if pref_slug:
            prefecture_name = slug_to_name.get(pref_slug)

    if not prefecture_name:
        prefecture_name = "東京都" # Default fallback

    # Precedence for prefecture_slug:
    # 1. list_data's prefecture_slug
    # 2. Map from prefecture_name
    # 3. Default "tokyo" (for "東京都" fallback)
    prefecture_slug = list_data.get("prefecture_slug")
    if not prefecture_slug:
        prefecture_slug = name_to_slug.get(prefecture_name)
    if not prefecture_slug:
        prefecture_slug = "tokyo"

    normalized["address"] = address
    normalized["prefecture_slug"] = prefecture_slug
    normalized["prefecture_name"] = prefecture_name
    normalized["municipality"] = municipality
    
    # Geocoding from JSON-LD
    lat = None
    lng = None
    geocode_source = None
    geocode_confidence = None
    
    json_ld_geo = detail_data.get("json_ld", {}).get("geo", {})
    if json_ld_geo:
        lat = float(json_ld_geo.get("latitude")) if json_ld_geo.get("latitude") else None
        lng = float(json_ld_geo.get("longitude")) if json_ld_geo.get("longitude") else None
        if lat and lng:
            geocode_source = "json-ld"
            geocode_confidence = 1.0
            
    normalized["lat"] = lat
    normalized["lng"] = lng
    normalized["geocode_source"] = geocode_source
    normalized["geocode_confidence"] = geocode_confidence
    
    # Layout and Area
    layout = list_data.get("room_layout")
    if "specs" in detail_data and "間取り" in detail_data["specs"]:
        layout = detail_data["specs"]["間取り"]
    normalized["layout"] = layout
    
    area_text = list_data.get("area_size")
    if "specs" in detail_data and "広さ" in detail_data["specs"]:
        area_text = detail_data["specs"]["広さ"]
    normalized["area_m2"] = parse_area(area_text)
    
    # Construction Year
    const_year_text = list_data.get("construction_year")
    if "specs" in detail_data and "築年数" in detail_data["specs"]:
        const_year_text = detail_data["specs"]["築年数"]
    normalized["construction_year_text"] = const_year_text
    
    built_year, built_month = parse_japanese_era(const_year_text)
    normalized["built_year"] = built_year
    normalized["built_month"] = built_month
    
    # Other specs
    specs = detail_data.get("specs", {})
    normalized["capacity_text"] = specs.get("入居可能人数")
    normalized["structure"] = specs.get("構造")
    kaidate_text = specs.get("階建")
    normalized["floors_text"] = kaidate_text
    floor_spec = parse_floor_text(kaidate_text)
    normalized["floor_number"] = floor_spec.floor_min
    normalized["floor_number_max"] = floor_spec.floor_max
    normalized["building_floors"] = floor_spec.building_floors
    normalized["point_text"] = detail_data.get("point_text")
    normalized["availability_text"] = list_data.get("availability_text") # often empty in list, can be updated later
    
    # 2. Accesses
    normalized["accesses"] = []
    raw_access_list = specs.get("交通") or list_data.get("access", [])
    for idx, raw_access in enumerate(raw_access_list):
        # Parse access string (e.g. "京成本線 千住大橋駅 徒歩 4分")
        line_name, station_name, walk_minutes = parse_access_parts(raw_access)

        normalized["accesses"].append({
            "line_name": line_name,
            "station_name": station_name,
            "walk_minutes": walk_minutes,
            "raw_text": raw_access,
            "sort_order": idx
        })
        
    # 3. Images
    normalized["images"] = []
    # Representative thumbnail and floorplan from list data
    if list_data.get("thumbnail_url"):
        normalized["images"].append({
            "image_url": list_data["thumbnail_url"],
            "image_type": "thumbnail",
            "alt_text": "代表画像",
            "sort_order": -2
        })
    if list_data.get("floorplan_url"):
        normalized["images"].append({
            "image_url": list_data["floorplan_url"],
            "image_type": "floorplan",
            "alt_text": "間取り図",
            "sort_order": -1
        })
    # Lightbox detail images
    for img in detail_data.get("images", []):
        normalized["images"].append({
            "image_url": img["image_url"],
            "image_type": "gallery",
            "alt_text": None,
            "sort_order": img["sort_order"]
        })
        
    # 4. Links
    normalized["links"] = []
    for link in detail_data.get("youtube_links", []):
        # Prevent official channels or other non-video links if needed, but keeping for now
        normalized["links"].append({
            "link_type": "youtube",
            "url": link["url"],
            "label": link["label"]
        })
        
    # 5. Rent Plans
    normalized["rent_plans"] = []
    detail_plans = detail_data.get("rent_plans", [])

    if detail_plans:
        for plan in detail_plans:
            # Determine plan code
            plan_code = resolve_bratto_plan_code(plan["plan_name"])

            original_daily = parse_money(plan["original_daily_rent"])
            discounted_daily = parse_money(plan["discounted_daily_rent"])
            
            # If no discounted but original exists, duplicate to discounted
            if original_daily and not discounted_daily:
                discounted_daily = original_daily
            elif discounted_daily and not original_daily:
                original_daily = discounted_daily
                
            original_tot = parse_money(plan["original_total"])
            discounted_tot = parse_money(plan["discounted_total"])
            
            if original_tot and not discounted_tot:
                discounted_tot = original_tot
            elif discounted_tot and not original_tot:
                original_tot = discounted_tot
                
            management = parse_money(plan["management_fee_daily"])
            cleaning = parse_money(plan["cleaning_fee"])
            
            normalized["rent_plans"].append({
                "plan_code": plan_code,
                "plan_name": plan["plan_name"],
                "duration_text": plan["plan_name"].split()[-1] if len(plan["plan_name"].split()) > 1 else plan["plan_name"],
                "available": bool(plan["available"]),
                "campaign_label": plan["campaign_label"],
                "original_daily_rent_yen": original_daily,
                "discounted_daily_rent_yen": discounted_daily,
                "original_total_yen": original_tot,
                "discounted_total_yen": discounted_tot,
                "total_period_days": plan["total_period_days"],
                "management_fee_daily_yen": management,
                "cleaning_fee_yen": cleaning,
                "raw_text": plan["raw_text"]
            })
    else:
        # Fallback to list page rent plans
        for p_name, p_val in list_data.get("rent_plans", {}).items():
            plan_code = resolve_bratto_plan_code(p_name)

            if p_val.get("available"):
                orig_daily = parse_money(p_val.get("original_daily_rent"))
                disc_daily = parse_money(p_val.get("discounted_daily_rent"))
                orig_tot = parse_money(p_val.get("original_monthly_total"))
                disc_tot = parse_money(p_val.get("discounted_monthly_total"))
                
                # Determine period from total text e.g. "月 111,000円/30日" or "週 34,300円/7日"
                period = None
                tot_text = p_val.get("discounted_monthly_total") or p_val.get("original_monthly_total") or ""
                period_match = re.search(r'/(\d+)\s*日', tot_text)
                if period_match:
                    period = int(period_match.group(1))
                
                normalized["rent_plans"].append({
                    "plan_code": plan_code,
                    "plan_name": p_name,
                    "duration_text": p_name.split()[-1] if len(p_name.split()) > 1 else p_name,
                    "available": 1,
                    "campaign_label": p_val.get("discount_campaign_name"),
                    "original_daily_rent_yen": orig_daily or disc_daily,
                    "discounted_daily_rent_yen": disc_daily or orig_daily,
                    "original_total_yen": orig_tot or disc_tot,
                    "discounted_total_yen": disc_tot or orig_tot,
                    "total_period_days": period,
                    "management_fee_daily_yen": None,
                    "cleaning_fee_yen": None,
                    "raw_text": json.dumps(p_val)
                })
            else:
                normalized["rent_plans"].append({
                    "plan_code": plan_code,
                    "plan_name": p_name,
                    "duration_text": p_name.split()[-1] if len(p_name.split()) > 1 else p_name,
                    "available": 0,
                    "campaign_label": None,
                    "original_daily_rent_yen": None,
                    "discounted_daily_rent_yen": None,
                    "original_total_yen": None,
                    "discounted_total_yen": None,
                    "total_period_days": None,
                    "management_fee_daily_yen": None,
                    "cleaning_fee_yen": None,
                    "raw_text": p_val.get("message", "Unavailable")
                })
                
    # 6. Features — サイト見出しは解決に使わず、生値+辞書ルックアップの category
    #    のみを書く(設計 §4.2・決定 1)。未知語は category=None。
    from domain.feature_categories import lookup_feature_category

    def _feature(tag: str) -> dict:
        cat = lookup_feature_category(tag)
        return {"feature_name": tag, "category": cat.code if cat else None}

    normalized["features"] = []
    detail_features = specs.get("基本設備", {})
    if detail_features:
        for _cat, list_tags in detail_features.items():
            for tag in list_tags:
                normalized["features"].append(_feature(tag))
    else:
        for tag in list_data.get("features", []):
            normalized["features"].append(_feature(tag))
            
    # 7. Campaigns (structured mechanically; merge official cam_* when present)
    normalized["campaigns"] = []
    cams = detail_data.get("campaigns") or list_data.get("campaigns", [])
    cam_js_objects = detail_data.get("cam_js_objects") or []
    for cam in cams:
        period_text = cam.get("details", {}).get("対象期間", "") if "details" in cam else ""
        condition_text = cam.get("details", {}).get("対象条件") if "details" in cam else None
        content = (
            cam.get("details", {}).get("内容") or cam.get("title")
            if "details" in cam
            else cam.get("title")
        )
        starts_on, ends_on = parse_dates_from_text(period_text)
        structured = structure_campaign(
            campaign_type=cam.get("type"),
            title=cam.get("title"),
            content=content,
            period_text=period_text,
            condition_text=condition_text,
            cam_objects=cam_js_objects,
            starts_on=starts_on,
            ends_on=ends_on,
        )
        entry = {
            "campaign_type": cam.get("type"),
            "title": cam.get("title"),
            "content": content,
            "target_period_text": period_text,
            "target_condition_text": condition_text,
            "starts_on": structured.get("starts_on"),
            "ends_on": structured.get("ends_on"),
            "raw_json": json.dumps(cam, ensure_ascii=False),
            "target_plan_code": structured.get("target_plan_code"),
            "discount_unit": structured.get("discount_unit"),
            "discount_value": structured.get("discount_value"),
            "discount_max_yen": structured.get("discount_max_yen"),
            "period_max_days": structured.get("period_max_days"),
            "stay_min_days": structured.get("stay_min_days"),
            "stay_max_days": structured.get("stay_max_days"),
            "contract_within_days": structured.get("contract_within_days"),
            "package_rent_benefit_yen": structured.get("package_rent_benefit_yen"),
            "package_cleaning_benefit_yen": structured.get("package_cleaning_benefit_yen"),
            "package_fee_benefit_yen": structured.get("package_fee_benefit_yen"),
            "package_total_benefit_yen": structured.get("package_total_benefit_yen"),
            "structure_source": structured.get("structure_source"),
            "parse_ok": structured.get("parse_ok"),
            "parse_warnings": structured.get("parse_warnings_json"),
        }
        normalized["campaigns"].append(entry)
        
    return normalized
