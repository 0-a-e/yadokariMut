import os
import sys
import json
import time
import hashlib
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from database import get_db_connection
from parser import parse_list_page, parse_detail_page, normalize_property

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

RAW_PAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "raw_pages")

def save_raw_html(url, page_type, html_content, status_code=200):
    """
    Saves raw HTML content to a local file and logs it in the raw_pages table.
    Returns the file path.
    """
    os.makedirs(RAW_PAGES_DIR, exist_ok=True)
    
    content_hash = hashlib.sha256(html_content.encode("utf-8")).hexdigest()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{page_type}_{content_hash[:10]}_{timestamp}.html"
    filepath = os.path.join(RAW_PAGES_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO raw_pages (source_site, url, page_type, fetched_at, status_code, content_hash, storage_path, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "bratto",
        url,
        page_type,
        datetime.now().isoformat(),
        status_code,
        content_hash,
        filepath,
        "1.0"
    ))
    conn.commit()
    conn.close()
    
    return filepath

def upsert_normalized_property(normalized_data, raw_list_json=None, raw_detail_json=None, raw_html_path=None):
    """
    Upserts a normalized property and its child entities into the SQLite database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    # Check if property already exists to preserve first_seen_at
    cursor.execute("""
        SELECT id, first_seen_at FROM properties 
        WHERE source_site = ? AND source_property_id = ?
    """, (normalized_data["source_site"], normalized_data["source_property_id"]))
    row = cursor.fetchone()
    
    if row:
        property_id = row["id"]
        first_seen_at = row["first_seen_at"]
    else:
        property_id = None
        first_seen_at = now_str
        
    # Upsert properties table
    cursor.execute("""
        INSERT INTO properties (
            id, source_site, source_property_id, prefecture_slug, prefecture_name, municipality,
            title, detail_url, address, lat, lng, geocode_source, geocode_confidence,
            layout, area_m2, construction_year_text, built_year, built_month,
            capacity_text, structure, floors_text, point_text, availability_text,
            first_seen_at, last_seen_at, detail_scraped_at, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source_site, source_property_id) DO UPDATE SET
            prefecture_slug = excluded.prefecture_slug,
            prefecture_name = excluded.prefecture_name,
            municipality = excluded.municipality,
            title = excluded.title,
            detail_url = excluded.detail_url,
            address = excluded.address,
            lat = excluded.lat,
            lng = excluded.lng,
            geocode_source = excluded.geocode_source,
            geocode_confidence = excluded.geocode_confidence,
            layout = excluded.layout,
            area_m2 = excluded.area_m2,
            construction_year_text = excluded.construction_year_text,
            built_year = excluded.built_year,
            built_month = excluded.built_month,
            capacity_text = excluded.capacity_text,
            structure = excluded.structure,
            floors_text = excluded.floors_text,
            point_text = excluded.point_text,
            availability_text = excluded.availability_text,
            last_seen_at = excluded.last_seen_at,
            detail_scraped_at = COALESCE(excluded.detail_scraped_at, properties.detail_scraped_at)
    """, (
        property_id,
        normalized_data["source_site"],
        normalized_data["source_property_id"],
        normalized_data.get("prefecture_slug"),
        normalized_data.get("prefecture_name"),
        normalized_data.get("municipality"),
        normalized_data.get("title"),
        normalized_data.get("detail_url"),
        normalized_data.get("address"),
        normalized_data.get("lat"),
        normalized_data.get("lng"),
        normalized_data.get("geocode_source"),
        normalized_data.get("geocode_confidence"),
        normalized_data.get("layout"),
        normalized_data.get("area_m2"),
        normalized_data.get("construction_year_text"),
        normalized_data.get("built_year"),
        normalized_data.get("built_month"),
        normalized_data.get("capacity_text"),
        normalized_data.get("structure"),
        normalized_data.get("floors_text"),
        normalized_data.get("point_text"),
        normalized_data.get("availability_text"),
        first_seen_at,
        now_str,
        normalized_data.get("detail_scraped_at"),
    ))
    
    if not property_id:
        property_id = cursor.lastrowid
        
    # Clear and insert accesses
    cursor.execute("DELETE FROM property_accesses WHERE property_id = ?", (property_id,))
    for access in normalized_data.get("accesses", []):
        cursor.execute("""
            INSERT INTO property_accesses (property_id, line_name, station_name, walk_minutes, raw_text, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (property_id, access["line_name"], access["station_name"], access["walk_minutes"], access["raw_text"], access["sort_order"]))
        
    # Clear and insert images
    cursor.execute("DELETE FROM property_images WHERE property_id = ?", (property_id,))
    for img in normalized_data.get("images", []):
        cursor.execute("""
            INSERT INTO property_images (property_id, image_url, image_type, alt_text, sort_order, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(property_id, image_url) DO UPDATE SET
                image_type = excluded.image_type,
                alt_text = excluded.alt_text,
                sort_order = excluded.sort_order
        """, (property_id, img["image_url"], img.get("image_type"), img.get("alt_text"), img["sort_order"], now_str))
        
    # Clear and insert links
    cursor.execute("DELETE FROM property_links WHERE property_id = ?", (property_id,))
    for link in normalized_data.get("links", []):
        cursor.execute("""
            INSERT INTO property_links (property_id, link_type, url, label, scraped_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(property_id, link_type, url) DO UPDATE SET
                label = excluded.label
        """, (property_id, link["link_type"], link["url"], link.get("label"), now_str))
        
    # Clear and insert rent plans
    cursor.execute("DELETE FROM rent_plans WHERE property_id = ?", (property_id,))
    min_discounted_daily = None
    min_discounted_monthly = None
    
    for plan in normalized_data.get("rent_plans", []):
        cursor.execute("""
            INSERT INTO rent_plans (
                property_id, plan_code, plan_name, duration_text, available, campaign_label,
                original_daily_rent_yen, discounted_daily_rent_yen, original_total_yen, discounted_total_yen,
                total_period_days, management_fee_daily_yen, cleaning_fee_yen, raw_text, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            property_id,
            plan["plan_code"],
            plan["plan_name"],
            plan["duration_text"],
            plan["available"],
            plan["campaign_label"],
            plan["original_daily_rent_yen"],
            plan["discounted_daily_rent_yen"],
            plan["original_total_yen"],
            plan["discounted_total_yen"],
            plan["total_period_days"],
            plan["management_fee_daily_yen"],
            plan["cleaning_fee_yen"],
            plan["raw_text"],
            now_str
        ))
        
        # Track minimum rates for snapshot
        if plan["available"] and plan["discounted_daily_rent_yen"]:
            if min_discounted_daily is None or plan["discounted_daily_rent_yen"] < min_discounted_daily:
                min_discounted_daily = plan["discounted_daily_rent_yen"]
            
            # Estimate monthly total if 30 days or calculate
            if plan["discounted_total_yen"] and plan["total_period_days"]:
                # Normalize total to 30 days
                monthly_est = int((plan["discounted_total_yen"] / plan["total_period_days"]) * 30)
                if min_discounted_monthly is None or monthly_est < min_discounted_monthly:
                    min_discounted_monthly = monthly_est
                    
    # Clear and insert features
    cursor.execute("DELETE FROM property_features WHERE property_id = ?", (property_id,))
    for feature in normalized_data.get("features", []):
        cursor.execute("""
            INSERT INTO property_features (property_id, feature_name, feature_category, raw_text)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(property_id, feature_category, feature_name) DO NOTHING
        """, (property_id, feature["feature_name"], feature.get("feature_category"), feature["raw_text"]))
        
    # Clear and insert campaigns (including structured discount fields)
    cursor.execute("DELETE FROM campaigns WHERE property_id = ?", (property_id,))
    for cam in normalized_data.get("campaigns", []):
        cursor.execute("""
            INSERT INTO campaigns (
                property_id, campaign_type, title, content, target_period_text,
                target_condition_text, starts_on, ends_on, target_plan_code,
                discount_unit, discount_value, discount_max_yen, period_max_days,
                stay_min_days, stay_max_days, contract_within_days,
                package_rent_benefit_yen, package_cleaning_benefit_yen,
                package_fee_benefit_yen, package_total_benefit_yen,
                structure_source, parse_ok, parse_warnings,
                raw_json, scraped_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            property_id,
            cam.get("campaign_type"),
            cam.get("title"),
            cam.get("content"),
            cam.get("target_period_text"),
            cam.get("target_condition_text"),
            cam.get("starts_on"),
            cam.get("ends_on"),
            cam.get("target_plan_code"),
            cam.get("discount_unit"),
            cam.get("discount_value"),
            cam.get("discount_max_yen"),
            cam.get("period_max_days"),
            cam.get("stay_min_days"),
            cam.get("stay_max_days"),
            cam.get("contract_within_days"),
            cam.get("package_rent_benefit_yen"),
            cam.get("package_cleaning_benefit_yen"),
            cam.get("package_fee_benefit_yen"),
            cam.get("package_total_benefit_yen"),
            cam.get("structure_source"),
            cam.get("parse_ok") if cam.get("parse_ok") is not None else 0,
            cam.get("parse_warnings"),
            cam.get("raw_json"),
            now_str
        ))
        
    # Add snapshot
    cursor.execute("""
        INSERT INTO property_snapshots (
            property_id, scraped_at, is_active, min_discounted_daily_rent_yen,
            min_discounted_monthly_total_yen, raw_list_json, raw_detail_json, raw_html_path, parser_version
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
    """, (
        property_id,
        now_str,
        min_discounted_daily,
        min_discounted_monthly,
        json.dumps(raw_list_json) if raw_list_json else None,
        json.dumps(raw_detail_json) if raw_detail_json else None,
        raw_html_path,
        "1.0"
    ))
    
    conn.commit()
    conn.close()
    return property_id

def scrape_list_pages(prefecture_slug, config, max_pages=10, delay=1.5):
    """
    Crawls list pages for a given prefecture and returns lists of crawled room links and room data.
    """
    source_cfg = config["sources"]["bratto"]
    base_url = source_cfg["base_url"]
    pref_cfg = source_cfg["prefectures"][prefecture_slug]
    
    list_url_base = f"{base_url}{pref_cfg['list_path']}"
    
    crawled_properties = []
    page = 1
    
    print(f"Starting crawl for {pref_cfg['name']} (max pages: {max_pages})")
    
    while page <= max_pages:
        url = f"{list_url_base}?pn={page}"
        print(f"Fetching list page {page}... URL: {url}")
        
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            if res.status_code == 404:
                print(f"List page {page} not found (404). Ending crawl.")
                break
            res.raise_for_status()
        except Exception as e:
            print(f"HTTP request error: {e}", file=sys.stderr)
            break
            
        save_raw_html(url, "list", res.text, res.status_code)
        
        properties, page_info, has_next, next_url = parse_list_page(res.text, target_url=list_url_base)
        print(f"Parsed {len(properties)} properties from page {page} ({page_info})")
        
        if not properties:
            print("No properties found. Ending crawl.")
            break
            
        for p in properties:
            p["prefecture_slug"] = prefecture_slug
            p["prefecture_name"] = pref_cfg["name"]
            crawled_properties.append(p)
            
        if not has_next:
            print("No next page link found. Ending crawl.")
            break
            
        page += 1
        time.sleep(delay)
        
    return crawled_properties

def scrape_detail_pages(properties_list, delay=1.5):
    """
    Crawls detailed pages for a given list of properties, normalizes them, and stores them in the database.
    Only crawls if detail page scraper scheduling dictates (needs update).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build dictionary of existing scraped times & list attributes to check update eligibility
    cursor.execute("SELECT source_property_id, detail_scraped_at, title FROM properties WHERE source_site = 'bratto'")
    existing_map = {row["source_property_id"]: dict(row) for row in cursor.fetchall()}
    conn.close()
    
    total = len(properties_list)
    print(f"Scraping detail pages: checking {total} properties...")
    
    for idx, prop in enumerate(properties_list):
        room_id = prop["room_id"]
        detail_url = prop["detail_url"]
        
        if not detail_url:
            continue
            
        # Determine if we need to scrape details
        should_scrape = True
        existing = existing_map.get(room_id)
        
        if existing:
            last_scraped = existing["detail_scraped_at"]
            if last_scraped:
                # Scraped within last 3 days?
                try:
                    dt = datetime.fromisoformat(last_scraped)
                    delta = datetime.now() - dt
                    if delta.days < 3:
                        # Scrape anyway if title changed
                        if existing["title"] == prop["title"]:
                            should_scrape = False
                except ValueError:
                    pass
                    
        if not should_scrape:
            # Still upsert the basic list properties to keep last_seen_at current
            # Read detailed data from database if available to prevent wiping it out
            # We can merge it by fetching existing details and normalizing
            # But let's print and skip detail request to save bandwidth
            print(f"[{idx+1}/{total}] Skip detail crawl for room_id={room_id} (already fresh)")
            
            # Simple upsert of list data
            detail_data = {"json_ld": {}, "specs": {}, "rent_plans": [], "campaigns": [], "youtube_links": [], "images": []}
            # Fetch existing specs & images from DB if they exist to avoid wiping them out
            detail_data = fetch_existing_detail_data(room_id)
            normalized = normalize_property(prop, detail_data)
            upsert_normalized_property(normalized, raw_list_json=prop)
            continue
            
        print(f"[{idx+1}/{total}] Scraping details for room_id={room_id} from {detail_url}")
        
        try:
            res = requests.get(detail_url, headers=DEFAULT_HEADERS, timeout=15)
            res.raise_for_status()
        except Exception as e:
            print(f"Error fetching detail page for room_id={room_id}: {e}", file=sys.stderr)
            time.sleep(delay)
            continue
            
        # Save raw detail html
        raw_html_path = save_raw_html(detail_url, "detail", res.text, res.status_code)
        
        # Parse detail
        detail_data = parse_detail_page(res.text, base_url="https://www.000area-weekly.com")
        
        # Merge and normalize
        normalized = normalize_property(prop, detail_data)
        normalized["detail_scraped_at"] = datetime.now().isoformat()
        
        # Upsert
        upsert_normalized_property(normalized, raw_list_json=prop, raw_detail_json=detail_data, raw_html_path=raw_html_path)
        
        time.sleep(delay)

def fetch_existing_detail_data(room_id):
    """
    Helper to fetch existing detail fields from database to avoid wiping them out when skipping detail fetch.
    """
    detail = {"json_ld": {}, "specs": {}, "rent_plans": [], "campaigns": [], "youtube_links": [], "images": []}
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, lat, lng, structure, floors_text, point_text, capacity_text, layout, area_m2 FROM properties WHERE source_property_id = ?", (room_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return detail
        
    prop_id = row["id"]
    
    # Mock JSON-LD
    detail["json_ld"] = {
        "name": None,
        "geo": {"latitude": row["lat"], "longitude": row["lng"]} if row["lat"] and row["lng"] else {}
    }
    
    specs = {
        "入居可能人数": row["capacity_text"],
        "構造": row["structure"],
        "階建": row["floors_text"]
    }
    
    # Fetch accesses
    cursor.execute("SELECT raw_text FROM property_accesses WHERE property_id = ? ORDER BY sort_order", (prop_id,))
    specs["交通"] = [r["raw_text"] for r in cursor.fetchall()]
    
    # Fetch features
    cursor.execute("SELECT feature_name, feature_category FROM property_features WHERE property_id = ?", (prop_id,))
    features = {}
    for r in cursor.fetchall():
        features.setdefault(r["feature_category"], []).append(r["feature_name"])
    specs["基本設備"] = features
    
    detail["specs"] = specs
    detail["point_text"] = row["point_text"]
    
    # Fetch plans
    cursor.execute("SELECT * FROM rent_plans WHERE property_id = ?", (prop_id,))
    for r in cursor.fetchall():
        detail["rent_plans"].append({
            "plan_name": r["plan_name"],
            "available": r["available"] == 1,
            "campaign_label": r["campaign_label"],
            "original_daily_rent": f"{r['original_daily_rent_yen']}円" if r["original_daily_rent_yen"] else None,
            "discounted_daily_rent": f"{r['discounted_daily_rent_yen']}円" if r["discounted_daily_rent_yen"] else None,
            "original_total": f"{r['original_total_yen']}円" if r["original_total_yen"] else None,
            "discounted_total": f"{r['discounted_total_yen']}円" if r["discounted_total_yen"] else None,
            "total_period_days": r["total_period_days"],
            "management_fee_daily": f"{r['management_fee_daily_yen']}円" if r["management_fee_daily_yen"] else None,
            "cleaning_fee": f"{r['cleaning_fee_yen']}円" if r["cleaning_fee_yen"] else None,
            "raw_text": r["raw_text"]
        })
        
    # Fetch images
    cursor.execute("SELECT image_url, sort_order FROM property_images WHERE property_id = ? AND image_type = 'gallery' ORDER BY sort_order", (prop_id,))
    for r in cursor.fetchall():
        detail["images"].append({
            "image_url": r["image_url"],
            "sort_order": r["sort_order"]
        })
        
    # Fetch campaigns
    cursor.execute("SELECT raw_json FROM campaigns WHERE property_id = ?", (prop_id,))
    for r in cursor.fetchall():
        try:
            detail["campaigns"].append(json.loads(r["raw_json"]))
        except Exception:
            pass
            
    # Fetch links
    cursor.execute("SELECT url, label FROM property_links WHERE property_id = ? AND link_type = 'youtube'", (prop_id,))
    for r in cursor.fetchall():
        detail["youtube_links"].append({
            "url": r["url"],
            "label": r["label"]
        })
        
    conn.close()
    return detail
