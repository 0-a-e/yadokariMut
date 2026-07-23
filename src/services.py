import os
import json
import re
from datetime import datetime
from database import get_db_connection
from anomaly_detector import detect_anomalies
from campaign_active import (
    annotate_campaigns,
    apply_effective_to_property,
    compute_min_rent_from_plans,
    resolve_plans_effective_rent,
)

try:
    from store.api_queries import (
        export_geojson as v2_export_geojson,
        get_property_detail as v2_get_property_detail,
        search_properties as v2_search_properties,
        update_shortlist as v2_update_shortlist,
        use_v2_data_layer,
    )
except ImportError:  # pragma: no cover
    def use_v2_data_layer():
        return False



_CAMPAIGN_SELECT = """
    campaign_type, title, content, target_period_text, target_condition_text,
    starts_on, ends_on, target_plan_code,
    discount_unit, discount_value, discount_max_yen, period_max_days,
    stay_min_days, stay_max_days, contract_within_days,
    package_rent_benefit_yen, package_cleaning_benefit_yen,
    package_fee_benefit_yen, package_total_benefit_yen,
    structure_source, parse_ok
"""


def clean_point_text(text):
    """Normalize scraped POINT intro: strip title label and empty-only values."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    cleaned = text.strip()
    # Remove leading "POINT" heading leftover from whole-container scrape
    cleaned = re.sub(r"^POINT\s*", "", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    return cleaned or None


def _fetch_campaigns_for_properties(cursor, property_ids):
    """Bulk-load campaigns keyed by property_id."""
    if not property_ids:
        return {}
    placeholders = ",".join(["?"] * len(property_ids))
    cursor.execute(
        f"SELECT property_id, {_CAMPAIGN_SELECT} FROM campaigns WHERE property_id IN ({placeholders})",
        list(property_ids),
    )
    out = {}
    for row in cursor.fetchall():
        pid = row["property_id"]
        c_dict = {k: row[k] for k in row.keys() if k != "property_id"}
        out.setdefault(pid, []).append(c_dict)
    return out


def db_search_properties(params):
    """
    Core search logic for properties in the SQLite database.
    """
    if use_v2_data_layer():
        return v2_search_properties(params)

    prefecture_name = params.get("prefecture_name")
    max_monthly_total_yen = params.get("max_monthly_total_yen")
    plan_code = params.get("plan_code")
    station_names = params.get("station_names")
    max_walk_minutes = params.get("max_walk_minutes")
    min_area_m2 = params.get("min_area_m2")
    required_features = params.get("required_features")
    saved_only = params.get("saved_only", False)
    exclude_hidden = params.get("exclude_hidden", True)
    limit = params.get("limit", 50)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query
    # We want to select properties and their cheapest active daily rent, station, layout, area, score, and image
    query = """
        SELECT DISTINCT p.id, p.source_property_id, p.title, p.detail_url, p.address, p.prefecture_name,
               p.layout, p.area_m2, p.built_year, p.built_month, p.total_score, p.lat, p.lng,
               p.point_text,
               (
                   SELECT MIN(walk_minutes) 
                   FROM property_accesses 
                   WHERE property_id = p.id AND walk_minutes IS NOT NULL
               ) as min_walk_minutes,
               (
                   SELECT MIN(discounted_daily_rent_yen) 
                   FROM rent_plans 
                   WHERE property_id = p.id AND available = 1 AND discounted_daily_rent_yen IS NOT NULL
               ) as min_daily_rent,
               (
                   SELECT discounted_total_yen 
                   FROM rent_plans 
                   WHERE property_id = p.id AND available = 1 
                   ORDER BY discounted_daily_rent_yen ASC LIMIT 1
               ) as min_plan_total,
               (
                   SELECT plan_name 
                   FROM rent_plans 
                   WHERE property_id = p.id AND available = 1 
                   ORDER BY discounted_daily_rent_yen ASC LIMIT 1
               ) as min_plan_name,
               COALESCE(
                   (
                       SELECT image_url 
                       FROM property_images 
                       WHERE property_id = p.id AND image_type = 'thumbnail' LIMIT 1
                   ),
                   (
                       SELECT image_url 
                       FROM property_images 
                       WHERE property_id = p.id AND image_type = 'gallery' ORDER BY sort_order ASC LIMIT 1
                   ),
                   (
                       SELECT image_url 
                       FROM property_images 
                       WHERE property_id = p.id ORDER BY sort_order ASC LIMIT 1
                   )
               ) as thumbnail_url,
               s.status as shortlist_status
         FROM properties p
         LEFT JOIN shortlists s ON s.property_id = p.id
         WHERE p.is_active = 1
    """
    
    conditions = []
    query_params = []
    
    if prefecture_name:
        conditions.append("p.prefecture_name = ?")
        query_params.append(prefecture_name)
        
    if min_area_m2:
        conditions.append("p.area_m2 >= ?")
        query_params.append(min_area_m2)
        
    if saved_only:
        conditions.append("s.status = 'saved'")
    elif exclude_hidden:
        conditions.append("(s.status IS NULL OR s.status NOT IN ('hide', 'reject'))")
        
    # Filter by required features
    if required_features:
        for feat in required_features:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM property_features 
                    WHERE property_id = p.id AND feature_name = ?
                )
            """)
            query_params.append(feat)
            
    # Filter by max walk minutes
    if max_walk_minutes is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM property_accesses 
                WHERE property_id = p.id AND walk_minutes <= ?
            )
        """)
        query_params.append(max_walk_minutes)
        
    # Filter by station names
    if station_names:
        placeholders = ",".join(["?"] * len(station_names))
        conditions.append(f"""
            EXISTS (
                SELECT 1 FROM property_accesses 
                WHERE property_id = p.id AND (station_name IN ({placeholders}) OR (station_name LIKE '%駅' AND SUBSTR(station_name, 1, LENGTH(station_name)-1) IN ({placeholders})))
            )
        """)
        # Append parameters for both IN clauses
        for st in station_names:
            query_params.append(st)
        for st in station_names:
            query_params.append(st)
            
    # Price filter: soft SQL prefilter only (discounted OR original may pass).
    # Exact cut uses effective totals after campaign resolution (see post-filter below).
    price_filter_active = max_monthly_total_yen is not None
    if price_filter_active:
        if plan_code:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM rent_plans
                    WHERE property_id = p.id AND available = 1 AND plan_code = ?
                      AND (
                        (original_total_yen IS NOT NULL AND original_total_yen <= ?)
                        OR (discounted_total_yen IS NOT NULL AND discounted_total_yen <= ?)
                      )
                )
            """)
            query_params.extend([plan_code, max_monthly_total_yen, max_monthly_total_yen])
        else:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM rent_plans
                    WHERE property_id = p.id AND available = 1
                      AND (
                        (original_total_yen IS NOT NULL AND original_total_yen <= ?)
                        OR (discounted_total_yen IS NOT NULL AND discounted_total_yen <= ?)
                      )
                )
            """)
            query_params.extend([max_monthly_total_yen, max_monthly_total_yen])
    elif plan_code:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM rent_plans
                WHERE property_id = p.id AND available = 1 AND plan_code = ?
            )
        """)
        query_params.append(plan_code)

    if conditions:
        query += " AND " + " AND ".join(conditions)

    # With price filter, over-fetch then trim after effective resolution so LIMIT is correct.
    query += " ORDER BY p.total_score DESC"
    if price_filter_active:
        query += " LIMIT ?"
        query_params.append(max(int(limit) * 50, 5000))
    else:
        query += " LIMIT ?"
        query_params.append(limit)

    cursor.execute(query, query_params)
    rows = cursor.fetchall()

    property_ids = [row["id"] for row in rows]
    campaigns_by_pid = _fetch_campaigns_for_properties(cursor, property_ids)

    results = []
    for row in rows:
        r_dict = dict(row)
        # Fetch stations summary
        cursor.execute("SELECT line_name, station_name, walk_minutes FROM property_accesses WHERE property_id = ? ORDER BY sort_order", (row["id"],))
        access_rows = cursor.fetchall()
        r_dict["access_summary"] = [f"{a['line_name']} {a['station_name']} 徒歩{a['walk_minutes']}分" if a['walk_minutes'] else f"{a['line_name']} {a['station_name']}" for a in access_rows]

        # Fetch all images
        cursor.execute("SELECT image_url, image_type, sort_order FROM property_images WHERE property_id = ? ORDER BY sort_order", (row["id"],))
        image_rows = cursor.fetchall()
        r_dict["images"] = [dict(img) for img in image_rows]

        # Fetch all rent plans
        cursor.execute("""
            SELECT plan_code, plan_name, duration_text, available, campaign_label,
                   original_daily_rent_yen, discounted_daily_rent_yen,
                   original_total_yen, discounted_total_yen, total_period_days,
                   management_fee_daily_yen, cleaning_fee_yen, raw_text
            FROM rent_plans
            WHERE property_id = ?
        """, (row["id"],))
        plan_rows = cursor.fetchall()
        raw_plans = [dict(p) for p in plan_rows]
        raw_cams = campaigns_by_pid.get(row["id"], [])
        annotated_cams = annotate_campaigns(raw_cams)
        effective_plans = resolve_plans_effective_rent(raw_plans, annotated_cams)
        r_dict["rent_plans"] = effective_plans
        r_dict["campaigns"] = annotated_cams
        # min_* は SQL の discounted 基準から effective 基準へ差し替え
        mins = compute_min_rent_from_plans(effective_plans)
        if mins["min_daily_rent"] is not None:
            r_dict["min_daily_rent"] = mins["min_daily_rent"]
            r_dict["min_plan_total"] = mins["min_plan_total"]
            r_dict["min_plan_name"] = mins["min_plan_name"]
        r_dict["point_text"] = clean_point_text(r_dict.get("point_text"))

        # Exact price filter on effective totals (MCP/CLI/API)
        if price_filter_active:
            if not _passes_effective_price_filter(
                effective_plans,
                max_monthly_total_yen=max_monthly_total_yen,
                plan_code=plan_code,
                min_plan_total=r_dict.get("min_plan_total"),
            ):
                continue

        results.append(r_dict)
        if len(results) >= limit:
            break

    conn.close()
    return results


def _passes_effective_price_filter(
    plans,
    *,
    max_monthly_total_yen,
    plan_code=None,
    min_plan_total=None,
) -> bool:
    """True if property qualifies under effective (campaign-aware) plan totals."""
    if max_monthly_total_yen is None:
        return True
    if plan_code:
        for p in plans or []:
            if not p.get("available"):
                continue
            if (p.get("plan_code") or "") != plan_code:
                continue
            total = p.get("effective_total_yen")
            if total is None:
                total = p.get("discounted_total_yen")
            if total is not None and total <= max_monthly_total_yen:
                return True
        return False
    if min_plan_total is not None:
        return min_plan_total <= max_monthly_total_yen
    # Fallback: any available plan under the cap
    for p in plans or []:
        if not p.get("available"):
            continue
        total = p.get("effective_total_yen")
        if total is None:
            total = p.get("discounted_total_yen")
        if total is not None and total <= max_monthly_total_yen:
            return True
    return False

def db_get_property_detail(property_id):
    """
    Gets detailed information for a single property by internal ID or source room_id.
    """
    if use_v2_data_layer():
        return v2_get_property_detail(property_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Try query by internal ID first, fallback to room_id
    cursor.execute("SELECT * FROM properties WHERE id = ? OR source_property_id = ?", (property_id, str(property_id)))
    prop_row = cursor.fetchone()
    if not prop_row:
        conn.close()
        return None
        
    prop = dict(prop_row)
    p_id = prop["id"]
    
    # Fetch accesses
    cursor.execute("SELECT line_name, station_name, walk_minutes, raw_text FROM property_accesses WHERE property_id = ? ORDER BY sort_order", (p_id,))
    prop["accesses"] = [dict(r) for r in cursor.fetchall()]
    
    # Fetch images
    cursor.execute("SELECT image_url, image_type, alt_text, sort_order FROM property_images WHERE property_id = ? ORDER BY sort_order", (p_id,))
    prop["images"] = [dict(r) for r in cursor.fetchall()]
    
    # Fetch links
    cursor.execute("SELECT link_type, url, label FROM property_links WHERE property_id = ?", (p_id,))
    prop["links"] = [dict(r) for r in cursor.fetchall()]
    
    # Fetch rent plans
    cursor.execute("SELECT plan_code, plan_name, duration_text, available, campaign_label, original_daily_rent_yen, discounted_daily_rent_yen, original_total_yen, discounted_total_yen, total_period_days, management_fee_daily_yen, cleaning_fee_yen, raw_text FROM rent_plans WHERE property_id = ?", (p_id,))
    prop["rent_plans"] = [dict(r) for r in cursor.fetchall()]
    
    # Fetch features
    cursor.execute("SELECT feature_name, feature_category FROM property_features WHERE property_id = ?", (p_id,))
    prop["features"] = [dict(r) for r in cursor.fetchall()]
    
    # Fetch campaigns (structured discount fields)
    cursor.execute(
        f"SELECT {_CAMPAIGN_SELECT} FROM campaigns WHERE property_id = ?",
        (p_id,),
    )
    prop["campaigns"] = [dict(r) for r in cursor.fetchall()]

    # Effective rent + is_active (JST / shared rules)
    apply_effective_to_property(prop)
    
    # Fetch shortlist status
    cursor.execute("SELECT status, comment, updated_at FROM shortlists WHERE property_id = ?", (p_id,))
    shortlist_row = cursor.fetchone()
    prop["shortlist"] = dict(shortlist_row) if shortlist_row else None
    
    # Run anomaly detector for this property
    anom_dict = detect_anomalies(p_id)
    prop["anomalies"] = anom_dict.get(p_id, {}).get("anomalies", [])
    
    # Fetch price history (snapshots)
    cursor.execute("SELECT scraped_at, min_discounted_daily_rent_yen, min_discounted_monthly_total_yen FROM property_snapshots WHERE property_id = ? ORDER BY scraped_at ASC", (p_id,))
    prop["price_history"] = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return prop

def db_compare_properties(property_ids):
    """
    Compares details across a list of property IDs or room IDs side-by-side.
    """
    comparison = []
    for p_id in property_ids:
        detail = db_get_property_detail(p_id)
        if detail:
            comparison.append(detail)
            
    if not comparison:
        return {"message": "No properties found for comparison"}
        
    # Build comparison summary
    keys_to_compare = [
        "id", "source_property_id", "title", "prefecture_name", "address", "layout", "area_m2",
        "built_year", "built_month", "total_score", "rent_score", "walk_score", "area_score",
        "age_score", "commute_score"
    ]
    
    summary = {}
    for key in keys_to_compare:
        summary[key] = {prop["source_property_id"]: prop.get(key) for prop in comparison}
        
    # Format plans (effective rent when available)
    plans_comparison = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        for plan in prop["rent_plans"]:
            p_code = plan["plan_code"]
            if plan["available"]:
                daily = plan.get("effective_daily_rent_yen")
                if daily is None:
                    daily = plan.get("discounted_daily_rent_yen")
                total = plan.get("effective_total_yen")
                if total is None:
                    total = plan.get("discounted_total_yen")
                val = f"{daily}円/日 (総額:{total}円)"
            else:
                val = "取扱無"
            plans_comparison.setdefault(p_code, {})[r_id] = val
            
    summary["plans"] = plans_comparison
    
    # Walk minutes summary
    walks = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        w_list = [a["walk_minutes"] for a in prop["accesses"] if a["walk_minutes"] is not None]
        walks[r_id] = f"徒歩 {min(w_list)}分" if w_list else "不明"
    summary["cheapest_walk_minutes"] = walks
    
    # Campaign titles summary
    camps = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        c_list = [c["title"] for c in prop["campaigns"] if c.get("is_active", True)]
        camps[r_id] = ", ".join(c_list) if c_list else "無し"
    summary["campaigns_active"] = camps
    
    # Shortlist status
    sh = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        sh[r_id] = prop["shortlist"]["status"] if prop["shortlist"] else "未選択"
    summary["shortlist_status"] = sh
    
    return summary

def db_update_shortlist(property_id, status, comment=None):
    """
    Inserts or updates the shortlist status of a property.
    """
    if use_v2_data_layer():
        res = v2_update_shortlist(property_id, status, comment)
        if not res.get("ok"):
            return {"status": "error", "message": f"Property with ID/room_id '{property_id}' not found"}
        return {"status": "success", "property_id": res.get("property_id"), "shortlist_status": status}

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Resolve property ID
    cursor.execute("SELECT id FROM properties WHERE id = ? OR source_property_id = ?", (property_id, str(property_id)))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"status": "error", "message": f"Property with ID/room_id '{property_id}' not found"}
        
    p_id = row["id"]
    
    # Validate status
    if status not in ["saved", "hide", "reject", "none"]:
        conn.close()
        return {"status": "error", "message": "Invalid status. Must be 'saved', 'hide', 'reject', or 'none'."}

    if status == "none":
        cursor.execute("DELETE FROM shortlists WHERE property_id = ?", (p_id,))
    else:
        cursor.execute("""
            INSERT INTO shortlists (property_id, status, comment, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(property_id) DO UPDATE SET
                status = excluded.status,
                comment = COALESCE(excluded.comment, shortlists.comment),
                updated_at = excluded.updated_at
        """, (p_id, status, comment, datetime.now().isoformat()))

    conn.commit()
    conn.close()
    return {"status": "success", "property_id": p_id, "shortlist_status": status, "comment": comment}

def db_export_geojson(params, file_path=None):
    """
    Searches properties and exports them as a GeoJSON file.
    """
    if use_v2_data_layer():
        return v2_export_geojson(params, file_path)

    export_params = params.copy() if params else {}
    if "limit" not in export_params:
        export_params["limit"] = 10000
    properties = db_search_properties(export_params)
    
    # Bulk fetch features to prevent N+1 queries
    property_ids = [prop["id"] for prop in properties]
    features_map = {}
    if property_ids:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(property_ids))
        cursor.execute(
            f"SELECT property_id, feature_name FROM property_features WHERE property_id IN ({placeholders})",
            property_ids
        )
        for row in cursor.fetchall():
            pid = row["property_id"]
            fname = row["feature_name"]
            features_map.setdefault(pid, []).append(fname)
        conn.close()
        
    features = []
    for prop in properties:
        lat = prop["lat"]
        lng = prop["lng"]
        if lat is None or lng is None:
            continue
            
        pid = prop["id"]
        prop_features = features_map.get(pid, [])
        feature_summary = ", ".join(prop_features)
        
        # Build station summary from access_summary
        station_list = []
        for a in prop.get("access_summary", []):
            parts = a.split(" ")
            if len(parts) > 1:
                station_list.append(parts[1])
        station_summary = ", ".join(station_list)
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lng, lat]
            },
            "properties": {
                "id": prop["id"],
                "room_id": prop["source_property_id"],
                "title": prop["title"],
                "detail_url": prop["detail_url"],
                "address": prop["address"],
                "prefecture_name": prop.get("prefecture_name"),
                "layout": prop["layout"],
                "area_m2": prop["area_m2"],
                "min_daily_rent": prop["min_daily_rent"],
                "min_plan_total": prop["min_plan_total"],
                "min_plan_name": prop["min_plan_name"],
                "min_walk_minutes": prop["min_walk_minutes"],
                "thumbnail_url": prop["thumbnail_url"],
                "images": [img["image_url"] for img in prop.get("images", [])],
                "total_score": prop["total_score"],
                "shortlist_status": prop["shortlist_status"] or "none",
                "access_summary": ", ".join(prop["access_summary"]),
                "feature_summary": feature_summary,
                "station_summary": station_summary,
                "point_text": clean_point_text(prop.get("point_text")),
                "rent_plans": prop.get("rent_plans", [])
            }
        })
        
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    if not file_path:
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "map.geojson")
        
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
        
    return {"status": "success", "file_path": file_path, "feature_count": len(features)}

def db_export_kml(params, file_path=None):
    """
    Searches properties and exports them as a KML file.
    """
    export_params = params.copy() if params else {}
    if "limit" not in export_params:
        export_params["limit"] = 10000
    properties = db_search_properties(export_params)
    
    kml_str = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>YadokariMutプロパティマップ</name>
    <description>Monthly Mansion properties filtered and scored.</description>
    
    <Style id="hideLabel">
      <LabelStyle>
        <color>00ffffff</color>
        <scale>0</scale>
      </LabelStyle>
    </Style>
"""
    
    for prop in properties:
        lat = prop["lat"]
        lng = prop["lng"]
        if lat is None or lng is None:
            continue
            
        # Build HTML table for rent plans
        plans_html = ""
        if prop.get("rent_plans"):
            plans_html = """
          <table border="1" style="border-collapse: collapse; width: 100%; font-size: 11px; margin-top: 10px; border-color: #ddd;">
            <tr style="background-color: #f2f2f2;">
              <th style="padding: 5px;">プラン</th>
              <th style="padding: 5px;">賃料</th>
              <th style="padding: 5px;">管理費</th>
              <th style="padding: 5px;">清掃費</th>
            </tr>
            """
            for plan in prop["rent_plans"]:
                if plan["available"]:
                    eff_daily = plan.get("effective_daily_rent_yen")
                    if eff_daily is None:
                        eff_daily = plan.get("discounted_daily_rent_yen")
                    daily = f"{eff_daily:,}円/日" if eff_daily is not None else "—"
                    label = plan.get("effective_campaign_label") or (
                        plan.get("campaign_label") if plan.get("campaign_applied") else None
                    )
                    if label:
                        daily += f" ({label})"
                    if (
                        plan.get("original_daily_rent_yen")
                        and eff_daily is not None
                        and plan["original_daily_rent_yen"] != eff_daily
                    ):
                        daily = (
                            f"<del style='color: #888;'>{plan['original_daily_rent_yen']:,}円/日</del><br/>"
                            + daily
                        )
                    if plan.get("campaign_expired"):
                        daily += " <span style='color:#888;'>(キャンペーン終了)</span>"

                    total = ""
                    eff_total = plan.get("effective_total_yen")
                    if eff_total is None:
                        eff_total = plan.get("discounted_total_yen")
                    if eff_total and plan.get("total_period_days"):
                        total = f"<br/><span style='color: #555;'>({plan['total_period_days']}日総額: {eff_total:,}円)</span>"
                    rent_text = f"{daily}{total}"
                    
                    mng = f"{plan['management_fee_daily_yen']:,}円/日" if plan['management_fee_daily_yen'] is not None else "0円/日"
                    cln = f"{plan['cleaning_fee_yen']:,}円" if plan['cleaning_fee_yen'] is not None else "0円"
                else:
                    rent_text = "<span style='color: #888;'>取扱無</span>"
                    mng = "-"
                    cln = "-"
                    
                plans_html += f"""
            <tr>
              <td style="padding: 5px; font-weight: bold;">{plan['plan_name']}</td>
              <td style="padding: 5px;">{rent_text}</td>
              <td style="padding: 5px;">{mng}</td>
              <td style="padding: 5px;">{cln}</td>
            </tr>
            """
            plans_html += "          </table>"
            
        desc = f"""<![CDATA[
          <h3>{prop['title']}</h3>
          <p><b>Score:</b> {prop['total_score']}</p>
          <p><b>Cheapest Rent:</b> {prop['min_daily_rent']} yen/day ({prop['min_plan_name']})</p>
          <p><b>Access:</b> {", ".join(prop['access_summary'])}</p>
          <p><b>Size/Layout:</b> {prop['area_m2']}㎡ / {prop['layout']}</p>
          <p><a href="{prop['detail_url']}" target="_blank">View details on site</a></p>
          {plans_html}
        ]]>"""
        
        # 変更点2: <Placemark>内に <styleUrl>#hideLabel</styleUrl> を追加
        kml_str += f"""    <Placemark>
      <name>{prop['title']}</name>
      <styleUrl>#hideLabel</styleUrl>
      <description>{desc.strip()}</description>
      <Point>
        <coordinates>{lng},{lat},0</coordinates>
      </Point>
    </Placemark>
"""
        
    kml_str += """  </Document>
</kml>
"""
    
    if not file_path:
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "map.kml")
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(kml_str)
        
    return {"status": "success", "file_path": file_path, "placemark_count": len(properties)}
