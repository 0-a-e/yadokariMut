"""物件詳細 / 比較 / ショートリスト更新クエリ."""

from __future__ import annotations

from typing import Any

from store.queries._common import (
    SOURCE_DISPLAY,
    _repo,
    apply_effective_rent_plans,
    price_plan_row_to_rent_plan,
    resolve_property_id,
)
from store.queries.price_history import _guard_price_history


def get_property_detail(
    property_id: int | str,
    *,
    by: str = "auto",
    source: str | None = None,
) -> dict[str, Any] | None:
    """物件詳細を取得する.

    by / source の意味は resolve_property_id を参照。解決した id で本体を取得し、
    子テーブルはその id にのみ紐づける(external_id が複数ソースにまたがる場合は
    AmbiguousPropertyLookup)。
    """
    repo = _repo()
    conn = repo.connect()
    try:
        pid = resolve_property_id(conn, property_id, by=by, source=source)
        if pid is None:
            return None
        row = conn.execute("SELECT * FROM properties WHERE id = ?", (pid,)).fetchone()
        if not row:
            return None
        prop = dict(row)
        # SELECT * の INTEGER(0/1) を API 契約上の bool へ正規化する
        # (_geojson_feature_from_prop の is_active bool 化と同一規約)
        prop["is_active"] = bool(prop.get("is_active", 1))
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

        prop["price_history"], prop["price_history_meta"] = _guard_price_history(
            [
                dict(r)
                for r in conn.execute(
                    "SELECT scraped_at, catalog_rent_per_day_yen, min_discounted_monthly_total_yen "
                    "FROM property_snapshots WHERE property_id = ? ORDER BY scraped_at ASC",
                    (pid,),
                )
            ],
            prop.get("catalog_rent_per_day_yen"),
        )
        return prop
    finally:
        conn.close()


def compare_properties(
    property_ids,
    *,
    by: str = "auto",
    source: str | None = None,
) -> dict[str, Any]:
    """Compares details across a list of property IDs or source room_ids side-by-side."""
    comparison = []
    for p_id in property_ids:
        detail = get_property_detail(p_id, by=by, source=source)
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

    summary: dict[str, Any] = {}
    for key in keys_to_compare:
        summary[key] = {prop["source_property_id"]: prop.get(key) for prop in comparison}

    # Format plans (effective rent when available)
    plans_comparison: dict[str, dict[str, str]] = {}
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
    walks: dict[str, str] = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        w_list = [a["walk_minutes"] for a in prop["accesses"] if a["walk_minutes"] is not None]
        walks[r_id] = f"徒歩 {min(w_list)}分" if w_list else "不明"
    summary["cheapest_walk_minutes"] = walks

    # Campaign titles summary
    camps: dict[str, str] = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        c_list = [c["title"] for c in prop["campaigns"] if c.get("is_active", True)]
        camps[r_id] = ", ".join(c_list) if c_list else "無し"
    summary["campaigns_active"] = camps

    # Shortlist status
    sh: dict[str, Any] = {}
    for prop in comparison:
        r_id = prop["source_property_id"]
        sh[r_id] = prop["shortlist"]["status"] if prop["shortlist"] else "未選択"
    summary["shortlist_status"] = sh

    return summary


def update_shortlist(
    property_id: int | str,
    status: str,
    comment: str | None = None,
    *,
    by: str = "auto",
    source: str | None = None,
) -> dict[str, Any]:
    """ショートリスト状態を更新する.

    by / source の意味は resolve_property_id を参照。詳細取得と同じ解決ロジックを
    通すため、表示した物件と更新対象が一致する。書込本体 (DELETE /
    INSERT..ON CONFLICT + commit) は Repository.update_shortlist (store.repository)。
    """
    repo = _repo()
    conn = repo.connect()
    try:
        pid = resolve_property_id(conn, property_id, by=by, source=source)
    finally:
        conn.close()
    if pid is None:
        return {"ok": False, "error": "not found"}
    repo.update_shortlist(pid, status, comment)
    return {"ok": True, "property_id": pid, "status": status}
