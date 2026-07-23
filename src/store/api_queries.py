"""Read-path queries for v2 schema, shaped for FE/API compatibility."""

from __future__ import annotations

import os
from typing import Any, Optional, Sequence

from domain.pricing import (
    MONTH_DAYS,
    compute_catalog_min_daily,
    plan_management_per_day,
    plan_rent_per_day,
    resolve_plans_effective,
    to_per_day,
)
from store.repository import Repository, get_connection

SOURCE_DISPLAY = {
    "bratto": "BraTTo",
    "unionmonthly": "ユニオンマンスリー",
    "tokyomonthly": "東京マンスリー",
    "tm21": "東京マンスリー21",
    "goodmonthly": "グッドマンスリー",
    "shintoshin": "マンスリー新都心",
    "weeklymonthly": "ウィークリー＆マンスリー",
}


def use_v2_data_layer() -> bool:
    """Select v2 read path.

    - ``YADOKARIMUT_DATA_LAYER=v2`` → force v2
    - ``YADOKARIMUT_DATA_LAYER=v1`` → force v1
    - unset → v2 if ``YADOKARIMUT_V2_DB_PATH`` is set, else v2 if default
      ``yadokari_mut_v2.db`` exists on disk, otherwise v1 (legacy).
    """
    val = os.environ.get("YADOKARIMUT_DATA_LAYER", "").strip().lower()
    if val in ("v2", "2", "true", "yes"):
        return True
    if val in ("v1", "1", "false", "no"):
        return False
    if os.environ.get("YADOKARIMUT_V2_DB_PATH"):
        return True
    from store.repository import default_db_path

    return os.path.isfile(default_db_path())


def _repo() -> Repository:
    # Re-read env each call so tests / CLI can override DB path
    return Repository(os.environ.get("YADOKARIMUT_V2_DB_PATH"))


def price_plan_row_to_rent_plan(row: dict[str, Any], *, on_date: str | None = None) -> dict[str, Any]:
    """Map v2 price_plans row → FE-compatible rent_plans dict (daily amounts)."""
    unit = row.get("presentation_unit") or "per_day"
    plan = {
        "plan_key": row.get("plan_key"),
        "plan_code": row.get("plan_key"),  # FE / legacy
        "plan_name": row.get("plan_name"),
        "duration_text": row.get("plan_name"),
        "duration_min_days": row.get("duration_min_days"),
        "duration_max_days": row.get("duration_max_days"),
        "available": bool(row.get("available", 1)),
        "campaign_label": row.get("campaign_label"),
        "presentation_unit": unit,
        "rent_original_yen": row.get("rent_original_yen"),
        "rent_current_yen": row.get("rent_current_yen"),
        "management_yen": row.get("management_yen"),
        "utilities_yen": row.get("utilities_yen"),
        "utilities_included": bool(row.get("utilities_included", 1)),
        "cleaning_yen": row.get("cleaning_yen"),
        "original_daily_rent_yen": to_per_day(row.get("rent_original_yen"), unit),
        "discounted_daily_rent_yen": to_per_day(row.get("rent_current_yen"), unit),
        "management_fee_daily_yen": to_per_day(row.get("management_yen"), unit) or 0,
        "cleaning_fee_yen": row.get("cleaning_yen"),
        "raw_text": row.get("raw_text"),
        # totals: approx 30-day for catalog
        "original_total_yen": None,
        "discounted_total_yen": None,
        "total_period_days": 30,
    }
    od = plan["original_daily_rent_yen"]
    dd = plan["discounted_daily_rent_yen"]
    md = plan["management_fee_daily_yen"] or 0
    if od is not None:
        plan["original_total_yen"] = (od + md) * 30
    if dd is not None:
        plan["discounted_total_yen"] = (dd + md) * 30
    return plan


def apply_effective_rent_plans(
    plans: list[dict[str, Any]],
    campaigns: list[dict[str, Any]],
    *,
    on_date: str | None = None,
) -> list[dict[str, Any]]:
    """Attach effective_daily_rent_yen using domain.pricing."""
    # Normalize campaign target_plan_code alias
    cams = []
    for c in campaigns:
        cc = dict(c)
        if not cc.get("target_plan_key") and cc.get("target_plan_code"):
            cc["target_plan_key"] = cc["target_plan_code"]
        cams.append(cc)

    resolved = resolve_plans_effective(plans, cams, on_date=on_date)
    out: list[dict[str, Any]] = []
    for p, r in zip(plans, resolved):
        d = dict(p)
        unit = d.get("presentation_unit") or "per_day"
        eff_pres = r.effective_rent_yen
        d["effective_rent_yen"] = eff_pres
        d["effective_daily_rent_yen"] = to_per_day(eff_pres, unit)
        d["campaign_applied"] = r.campaign_applied
        d["campaign_expired"] = r.campaign_expired
        d["effective_campaign_label"] = r.effective_campaign_label
        d["expired_campaign_label"] = r.expired_campaign_label
        d["matched_campaign_type"] = r.matched_campaign_type
        if d.get("effective_daily_rent_yen") is not None:
            md = d.get("management_fee_daily_yen") or 0
            d["effective_total_yen"] = (d["effective_daily_rent_yen"] + md) * 30
        out.append(d)
    return out


def search_properties(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    params = params or {}
    prefecture_name = params.get("prefecture_name")
    source_sites = params.get("source_sites")
    if isinstance(source_sites, str):
        source_sites = [s.strip() for s in source_sites.split(",") if s.strip()]
    max_walk = params.get("max_walk_minutes")
    min_area = params.get("min_area_m2")
    required_features = params.get("required_features")
    if isinstance(required_features, str):
        required_features = [x.strip() for x in required_features.split(",") if x.strip()]
    saved_only = params.get("saved_only", False)
    exclude_hidden = params.get("exclude_hidden", True)
    limit = int(params.get("limit") or 50)
    max_monthly = params.get("max_monthly_total_yen")

    repo = _repo()
    conn = repo.connect()
    try:
        clauses = ["p.is_active = 1"]
        qparams: list[Any] = []
        if prefecture_name:
            clauses.append("p.prefecture_name = ?")
            qparams.append(prefecture_name)
        if source_sites:
            ph = ",".join("?" for _ in source_sites)
            clauses.append(f"p.source_site IN ({ph})")
            qparams.extend(source_sites)
        if min_area is not None:
            clauses.append("p.area_m2 >= ?")
            qparams.append(min_area)
        if saved_only:
            clauses.append("s.status = 'saved'")
        elif exclude_hidden:
            clauses.append("(s.status IS NULL OR s.status NOT IN ('hide', 'reject'))")

        sql = f"""
            SELECT p.*, s.status as shortlist_status,
                   (SELECT MIN(walk_minutes) FROM property_accesses
                    WHERE property_id = p.id AND walk_minutes IS NOT NULL) as min_walk_minutes,
                   (SELECT image_url FROM property_images
                    WHERE property_id = p.id
                    ORDER BY CASE image_type WHEN 'thumbnail' THEN 0 WHEN 'gallery' THEN 1 ELSE 2 END,
                             sort_order LIMIT 1) as thumbnail_url
            FROM properties p
            LEFT JOIN shortlists s ON s.property_id = p.id
            WHERE {' AND '.join(clauses)}
            ORDER BY p.catalog_rent_per_day_yen IS NULL, p.catalog_rent_per_day_yen ASC
            LIMIT ?
        """
        # over-fetch for post filters
        fetch_limit = max(limit * 20, 500) if (max_walk or required_features or max_monthly) else limit
        qparams.append(fetch_limit)
        rows = [dict(r) for r in conn.execute(sql, qparams)]
        results: list[dict[str, Any]] = []
        for row in rows:
            pid = row["id"]
            if max_walk is not None and row.get("min_walk_minutes") is not None:
                if row["min_walk_minutes"] > max_walk:
                    continue
            if required_features:
                feats = {
                    r["feature_name"]
                    for r in conn.execute(
                        "SELECT feature_name FROM property_features WHERE property_id = ?",
                        (pid,),
                    )
                }
                if not all(f in feats for f in required_features):
                    continue

            access_rows = list(
                conn.execute(
                    "SELECT line_name, station_name, walk_minutes FROM property_accesses "
                    "WHERE property_id = ? ORDER BY sort_order",
                    (pid,),
                )
            )
            access_summary = []
            for a in access_rows:
                if a["walk_minutes"] is not None:
                    access_summary.append(
                        f"{a['line_name'] or ''} {a['station_name'] or ''} 徒歩{a['walk_minutes']}分".strip()
                    )
                else:
                    access_summary.append(f"{a['line_name'] or ''} {a['station_name'] or ''}".strip())

            img_rows = list(
                conn.execute(
                    "SELECT image_url, image_type, sort_order FROM property_images "
                    "WHERE property_id = ? ORDER BY sort_order",
                    (pid,),
                )
            )
            plan_rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM price_plans WHERE property_id = ? ORDER BY duration_min_days",
                    (pid,),
                )
            ]
            cam_rows = [
                dict(r)
                for r in conn.execute("SELECT * FROM campaigns WHERE property_id = ?", (pid,))
            ]
            # alias target_plan_code for campaign_active-style consumers
            for c in cam_rows:
                c["target_plan_code"] = c.get("target_plan_key")

            rent_plans = [price_plan_row_to_rent_plan(p) for p in plan_rows]
            rent_plans = apply_effective_rent_plans(rent_plans, cam_rows)

            min_daily = None
            min_total = None
            min_name = None
            for p in rent_plans:
                if not p.get("available"):
                    continue
                d = p.get("effective_daily_rent_yen")
                if d is None:
                    d = p.get("discounted_daily_rent_yen")
                if d is None or d <= 0:
                    continue
                if min_daily is None or d < min_daily:
                    min_daily = d
                    min_total = p.get("effective_total_yen") or p.get("discounted_total_yen")
                    min_name = p.get("plan_name")

            if max_monthly is not None and min_total is not None and min_total > max_monthly:
                continue

            site = row.get("source_site") or ""
            results.append(
                {
                    "id": pid,
                    "source_site": site,
                    "source_display_name": SOURCE_DISPLAY.get(site, site),
                    "source_property_id": row.get("external_id"),
                    "external_id": row.get("external_id"),
                    "title": row.get("title"),
                    "detail_url": row.get("detail_url"),
                    "address": row.get("address"),
                    "prefecture_name": row.get("prefecture_name"),
                    "prefecture_slug": row.get("prefecture_slug"),
                    "layout": row.get("layout"),
                    "area_m2": row.get("area_m2"),
                    "built_year": row.get("built_year"),
                    "built_month": row.get("built_month"),
                    "total_score": row.get("total_score") or 0,
                    "lat": row.get("lat"),
                    "lng": row.get("lng"),
                    "point_text": row.get("point_text"),
                    "min_walk_minutes": row.get("min_walk_minutes"),
                    "min_daily_rent": min_daily if min_daily is not None else row.get("catalog_rent_per_day_yen"),
                    "min_plan_total": min_total,
                    "min_plan_name": min_name,
                    "thumbnail_url": row.get("thumbnail_url"),
                    "shortlist_status": row.get("shortlist_status"),
                    "access_summary": access_summary,
                    "images": [dict(i) for i in img_rows],
                    "rent_plans": rent_plans,
                    "campaigns": cam_rows,
                }
            )
            if len(results) >= limit:
                break
        return results
    finally:
        conn.close()


def get_property_detail(property_id: int | str) -> dict[str, Any] | None:
    repo = _repo()
    conn = repo.connect()
    try:
        row = conn.execute(
            "SELECT * FROM properties WHERE id = ? OR external_id = ?",
            (property_id, str(property_id)),
        ).fetchone()
        if not row:
            return None
        prop = dict(row)
        pid = prop["id"]
        site = prop.get("source_site") or ""
        prop["source_property_id"] = prop.get("external_id")
        prop["source_display_name"] = SOURCE_DISPLAY.get(site, site)

        prop["accesses"] = [
            dict(r)
            for r in conn.execute(
                "SELECT line_name, station_name, walk_minutes, raw_text FROM property_accesses "
                "WHERE property_id = ? ORDER BY sort_order",
                (pid,),
            )
        ]
        prop["images"] = [
            dict(r)
            for r in conn.execute(
                "SELECT image_url, image_type, alt_text, sort_order FROM property_images "
                "WHERE property_id = ? ORDER BY sort_order",
                (pid,),
            )
        ]
        prop["links"] = [
            dict(r)
            for r in conn.execute(
                "SELECT link_type, url, label FROM property_links WHERE property_id = ?",
                (pid,),
            )
        ]
        prop["features"] = [
            dict(r)
            for r in conn.execute(
                "SELECT feature_name, feature_category FROM property_features WHERE property_id = ?",
                (pid,),
            )
        ]
        plan_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM price_plans WHERE property_id = ? ORDER BY duration_min_days",
                (pid,),
            )
        ]
        cam_rows = [
            dict(r)
            for r in conn.execute("SELECT * FROM campaigns WHERE property_id = ?", (pid,))
        ]
        for c in cam_rows:
            c["target_plan_code"] = c.get("target_plan_key")
        prop["campaigns"] = cam_rows
        rent_plans = [price_plan_row_to_rent_plan(p) for p in plan_rows]
        prop["rent_plans"] = apply_effective_rent_plans(rent_plans, cam_rows)

        sl = conn.execute(
            "SELECT status, comment, updated_at FROM shortlists WHERE property_id = ?",
            (pid,),
        ).fetchone()
        prop["shortlist"] = dict(sl) if sl else None

        prop["price_history"] = [
            {
                "scraped_at": r["scraped_at"],
                "min_discounted_daily_rent_yen": r["catalog_rent_per_day_yen"],
                "min_discounted_monthly_total_yen": r["min_discounted_monthly_total_yen"],
            }
            for r in conn.execute(
                "SELECT scraped_at, catalog_rent_per_day_yen, min_discounted_monthly_total_yen "
                "FROM property_snapshots WHERE property_id = ? ORDER BY scraped_at ASC",
                (pid,),
            )
        ]
        prop["anomalies"] = []
        return prop
    finally:
        conn.close()


def export_geojson(params: dict[str, Any] | None = None, file_path: str | None = None) -> dict[str, Any]:
    import json

    export_params = dict(params or {})
    export_params.setdefault("limit", 10000)
    properties = search_properties(export_params)

    # features map
    property_ids = [p["id"] for p in properties]
    features_map: dict[int, list[str]] = {}
    if property_ids:
        repo = _repo()
        conn = repo.connect()
        try:
            ph = ",".join("?" for _ in property_ids)
            for row in conn.execute(
                f"SELECT property_id, feature_name FROM property_features WHERE property_id IN ({ph})",
                property_ids,
            ):
                features_map.setdefault(row["property_id"], []).append(row["feature_name"])
        finally:
            conn.close()

    features = []
    for prop in properties:
        lat, lng = prop.get("lat"), prop.get("lng")
        if lat is None or lng is None:
            continue
        pid = prop["id"]
        feat_names = features_map.get(pid, [])
        station_list = []
        for a in prop.get("access_summary") or []:
            parts = str(a).split()
            if len(parts) > 1:
                station_list.append(parts[1])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "id": prop["id"],
                    "room_id": prop.get("source_property_id") or prop.get("external_id"),
                    "source_site": prop.get("source_site"),
                    "source_display_name": prop.get("source_display_name"),
                    "title": prop.get("title"),
                    "detail_url": prop.get("detail_url"),
                    "address": prop.get("address"),
                    "prefecture_name": prop.get("prefecture_name"),
                    "layout": prop.get("layout"),
                    "area_m2": prop.get("area_m2"),
                    "min_daily_rent": prop.get("min_daily_rent"),
                    "min_plan_total": prop.get("min_plan_total"),
                    "min_plan_name": prop.get("min_plan_name"),
                    "min_walk_minutes": prop.get("min_walk_minutes"),
                    "thumbnail_url": prop.get("thumbnail_url"),
                    "images": [
                        img["image_url"] if isinstance(img, dict) else img
                        for img in prop.get("images") or []
                    ],
                    "total_score": prop.get("total_score") or 0,
                    "shortlist_status": prop.get("shortlist_status") or "none",
                    "access_summary": ", ".join(prop.get("access_summary") or []),
                    "feature_summary": ", ".join(feat_names),
                    "station_summary": ", ".join(station_list),
                    "point_text": prop.get("point_text"),
                    "rent_plans": prop.get("rent_plans") or [],
                    "campaigns": prop.get("campaigns") or [],
                },
            }
        )

    geojson = {"type": "FeatureCollection", "features": features}
    if file_path is None:
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "map.geojson"
        )
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    return {"status": "success", "file_path": file_path, "feature_count": len(features)}


def update_shortlist(property_id: int | str, status: str, comment: str | None = None) -> dict[str, Any]:
    from datetime import datetime

    repo = _repo()
    conn = repo.connect()
    try:
        row = conn.execute(
            "SELECT id FROM properties WHERE id = ? OR external_id = ?",
            (property_id, str(property_id)),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "not found"}
        pid = row["id"]
        now = datetime.now().isoformat()
        if status in (None, "", "none"):
            conn.execute("DELETE FROM shortlists WHERE property_id = ?", (pid,))
        else:
            conn.execute(
                """
                INSERT INTO shortlists (property_id, status, comment, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(property_id) DO UPDATE SET
                    status = excluded.status,
                    comment = COALESCE(excluded.comment, shortlists.comment),
                    updated_at = excluded.updated_at
                """,
                (pid, status, comment, now),
            )
        conn.commit()
        return {"ok": True, "property_id": pid, "status": status}
    finally:
        conn.close()
