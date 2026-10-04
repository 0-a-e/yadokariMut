"""queries 共通レイヤ: 接続取得 / 物件 id 解決 / 行→契約モデル互換 dict 変換.

SQL 結果行を api_models の応答契約互換 dict へ写像する変換関数と、
検索・詳細・GeoJSON・エクスポート各モジュールで共用する部品を集約する。
表示名は store.source_catalog.SOURCE_DISPLAY を SSOT として import する
(queries → source_catalog の一方向依存)。
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Sequence

from domain.pricing import resolve_plans_effective, to_per_day
from store.repository import Repository
from store.source_catalog import SOURCE_DISPLAY


def _repo() -> Repository:
    # Re-read env each call so tests / CLI can override DB path
    return Repository(os.environ.get("YADOKARIMUT_V2_DB_PATH"))


class AmbiguousPropertyLookup(Exception):
    """external_id が複数ソースにまたがり、source 指定なしでは一意に決まらない。"""

    def __init__(self, key: str, candidates: list[dict[str, Any]]):
        self.key = key
        self.candidates = candidates
        sources = ", ".join(sorted({str(c.get("source_site") or "?") for c in candidates}))
        super().__init__(
            f"external_id '{key}' は複数ソース({sources})に存在します。"
            "source_site を指定してください。"
        )


def resolve_property_id(
    conn: sqlite3.Connection,
    key: int | str,
    *,
    by: str = "auto",
    source: str | None = None,
) -> int | None:
    """物件識別子を properties.id に解決する唯一の窓口.

    properties.id と external_id は値域が重なる(本番では external_id が全て数字)ため、
    単一の WHERE id = ? OR external_id = ? では意図した物件に決まらない。ここで
    名前空間を明示的に分け、結果をアクセスパスに依存させない。

    - by="id":       properties.id としてのみ解決(数字キーのみ)
    - by="external": external_id としてのみ解決(source 指定で一意化)
    - by="auto":     数字キーは id を優先し、該当が無ければ external_id にフォールバック

    external_id は (source_site, external_id) でのみ一意。source 未指定で複数
    ソースに一致した場合は推測せず AmbiguousPropertyLookup を送出する。
    """
    if by not in ("auto", "id", "external"):
        raise ValueError(f"unknown by={by!r} (expected 'auto' / 'id' / 'external')")
    text = str(key).strip()

    if by in ("auto", "id") and re.fullmatch(r"[0-9]+", text):
        row = conn.execute("SELECT id FROM properties WHERE id = ?", (int(text),)).fetchone()
        if row:
            return int(row["id"])
        if by == "id":
            return None
    if by == "id":
        return None

    sql = "SELECT id, source_site FROM properties WHERE external_id = ?"
    params: list[Any] = [text]
    if source:
        sql += " AND source_site = ?"
        params.append(source)
    # ORDER BY id で結果を一意化し、索引/列の選び方に左右されないようにする
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY id", params)]
    if not rows:
        return None
    if len(rows) > 1:
        raise AmbiguousPropertyLookup(text, rows)
    return int(rows[0]["id"])


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
        # 常にキーを set する(日額未確定は null)。一括 /api/geojson と
        # /api/geojson/stream で rent_plans のキー構成を一致させるため
        d["effective_total_yen"] = None
        if d.get("effective_daily_rent_yen") is not None:
            md = d.get("management_fee_daily_yen") or 0
            d["effective_total_yen"] = (d["effective_daily_rent_yen"] + md) * 30
        out.append(d)
    return out


# SQLite のプレースホルダ数上限に余裕を持たせるため、IN 句は分割して発行する
_CHILD_IN_CHUNK = 900


def _fetch_child_rows_by_property(
    conn: sqlite3.Connection,
    select_sql: str,
    pids: Sequence[int],
) -> dict[int, list[dict[str, Any]]]:
    """子テーブルを property_id IN (...) で一括取得し、property_id ごとに束ねる.

    select_sql は `{placeholders}` を含む SELECT 文で、property_id 列を選択すること。
    """
    grouped: dict[int, list[dict[str, Any]]] = {}
    pid_list = list(pids)
    for start in range(0, len(pid_list), _CHILD_IN_CHUNK):
        chunk = pid_list[start : start + _CHILD_IN_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(select_sql.format(placeholders=placeholders), chunk):
            grouped.setdefault(row["property_id"], []).append(dict(row))
    return grouped


def _property_list_sql(tail: str) -> str:
    """物件一覧系 (iter_search_properties / get_properties_by_ids) 共通の主問合せ.

    本体行 + ショートリスト状態 + min_walk_minutes / thumbnail_url の相関サブクエリ
    までが完全同一のためここに集約し、tail に WHERE / ORDER BY / LIMIT 節を渡す。
    """
    return f"""
        SELECT p.*, s.status as shortlist_status,
               (SELECT MIN(walk_minutes) FROM property_accesses
                WHERE property_id = p.id AND walk_minutes IS NOT NULL) as min_walk_minutes,
               (SELECT image_url FROM property_images
                WHERE property_id = p.id
                ORDER BY CASE image_type WHEN 'thumbnail' THEN 0 WHEN 'gallery' THEN 1 ELSE 2 END,
                         sort_order LIMIT 1) as thumbnail_url
        FROM properties p
        LEFT JOIN shortlists s ON s.property_id = p.id
        {tail}
    """


def _property_row_to_result(
    row: dict[str, Any],
    access_rows: list[dict[str, Any]],
    img_rows: list[dict[str, Any]],
    plan_rows: list[dict[str, Any]],
    cam_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """properties 行 + 子テーブル行を API/MCP 共通の物件辞書へ変換する.

    search_properties と get_properties_by_ids の共用。
    """
    pid = row["id"]

    access_summary = []
    for a in access_rows:
        if a["walk_minutes"] is not None:
            access_summary.append(
                f"{a['line_name'] or ''} {a['station_name'] or ''} 徒歩{a['walk_minutes']}分".strip()
            )
        else:
            access_summary.append(f"{a['line_name'] or ''} {a['station_name'] or ''}".strip())

    # alias target_plan_code for legacy-style consumers
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

    site = row.get("source_site") or ""
    return {
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
        "municipality": row.get("municipality"),
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
        "is_active": bool(row.get("is_active", True)),
        "last_seen_at": row.get("last_seen_at"),
        "access_summary": access_summary,
        "images": [
            {k: v for k, v in i.items() if k != "property_id"}
            for i in img_rows
        ],
        "rent_plans": rent_plans,
        "campaigns": cam_rows,
    }


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
