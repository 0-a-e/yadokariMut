"""queries 共通レイヤ: 接続取得 / 物件 id 解決 / 行→契約モデル互換 dict 変換.

SQL 結果行を api_models の応答契約互換 dict へ写像する変換関数と、
検索・詳細・GeoJSON・エクスポート各モジュールで共用する部品を集約する。
表示名は store.source_catalog.SOURCE_DISPLAY を SSOT として import する
(queries → source_catalog の一方向依存)。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, NamedTuple, Sequence

import psycopg

from domain.plan_catalog import plan_label, target_plan_label
from domain.pricing import (
    MONTH_DAYS,
    campaign_with_plan_code_alias,
    campaign_with_plan_key,
    resolve_plans_effective,
    to_per_day,
)
from store.repository import Repository
from store.source_catalog import SOURCE_DISPLAY, default_contract_fee_yen


def iso_jsonable(value: Any) -> Any:
    """datetime/date を isoformat 文字列へ再帰変換(配信 dict の直列化用)。

    timestamptz/DATE 化 (Phase 6c) で DB 行に datetime/date が混入するため、
    pydantic (response_model) を通らない json.dumps 経路(建物 geojson stream・
    MCP export)で使う。aware datetime は Asia/Tokyo セッション由来のため
    isoformat は "+09:00" 付きで API 契約 (D9-5) と一致する。
    """
    if isinstance(value, dict):
        return {k: iso_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [iso_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def resolve_contract_fee_yen(prop: dict[str, Any]) -> int | None:
    """物件行から契約事務手数料の実効値を解決する (API 埋め込みの唯一の窓口).

    解決順: 物件個別値 (properties.contract_fee_yen。パーサ未投入なら NULL)
    > サイト既定 (SOURCE_CATALOG)。どちらも無い場合は None = 算出不能を
    返し、根拠のない数値で補完しない。GeoJSON / 詳細 / MCP のいずれも本関数を
    通した値を返すため、FE 側は個別のサイト値テーブルを持たずこの値を
    そのまま使えばよい(None は UI 側で「不明」として明示表示する)。
    """
    fee = prop.get("contract_fee_yen")
    if fee is not None:
        return int(fee)
    return default_contract_fee_yen(prop.get("source_site"))


def campaign_row_to_api(c: dict[str, Any]) -> dict[str, Any]:
    """campaigns 行 → API 応答互換 dict (legacy alias + 表示ラベル) の唯一の変換窓口.

    campaign_with_plan_code_alias (domain.pricing 正本) の legacy 同義キー付与に、
    target_plan_label (domain.plan_catalog 辞書解決・all/空 = すべてのプラン)
    の追加をまとめたもの。_property_row_to_result と get_property_detail の
    2 経路がこの関数を通すことで応答キー構成が一致する。
    """
    out = campaign_with_plan_code_alias(c)
    out["target_plan_label"] = target_plan_label(out.get("target_plan_key"))
    return out


def _repo() -> Repository:
    # DSN 解決は store.pg.resolve_dsn (YADOKARIMUT_PG_DSN / 既定 compose DSN) が担う
    return Repository()


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
    conn: psycopg.Connection,
    key: int | str,
    *,
    by: str = "auto",
    source: str | None = None,
) -> int | None:
    """物件識別子を properties.id に解決する唯一の窓口.

    properties.id と external_id は値域が重なる(本番では external_id が全て数字)ため、
    単一の WHERE id = %s OR external_id = %s では意図した物件に決まらない。ここで
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
        row = conn.execute("SELECT id FROM properties WHERE id = %s", (int(text),)).fetchone()
        if row:
            return int(row["id"])
        if by == "id":
            return None
    if by == "id":
        return None

    sql = "SELECT id, source_site FROM properties WHERE external_id = %s"
    params: list[Any] = [text]
    if source:
        sql += " AND source_site = %s"
        params.append(source)
    # ORDER BY id で結果を一意化し、索引/列の選び方に左右されないようにする
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY id", params)]
    if not rows:
        return None
    if len(rows) > 1:
        raise AmbiguousPropertyLookup(text, rows)
    return int(rows[0]["id"])


def price_plan_row_to_rent_plan(row: dict[str, Any], *, on_date: str | None = None) -> dict[str, Any]:
    """Map v2 price_plans row → FE-compatible rent_plans dict (daily amounts).

    日額換算は domain.pricing.to_per_day (単位語彙は per_day/per_month の
    2 値のみ — 決定 11)。換算不能 (単位未知) は 0 円へ畳み込まず null を
    透過し、30 日総額も null とする (FE は CalculatorPlan 経由で ?? 0 を持つ)。
    """
    unit = row.get("presentation_unit") or "per_day"
    plan = {
        "plan_key": row.get("plan_key"),
        "plan_code": row.get("plan_key"),  # FE / legacy
        "plan_name": row.get("plan_name"),
        "plan_label": plan_label(row.get("plan_key"), row.get("plan_name")),
        "duration_text": row.get("plan_name"),
        "duration_min_days": row.get("duration_min_days"),
        "duration_max_days": row.get("duration_max_days"),
        "available": bool(row.get("available", True)),
        "campaign_label": row.get("campaign_label"),
        "presentation_unit": unit,
        "rent_original_yen": row.get("rent_original_yen"),
        "rent_current_yen": row.get("rent_current_yen"),
        "management_yen": row.get("management_yen"),
        "utilities_yen": row.get("utilities_yen"),
        "utilities_included": bool(row.get("utilities_included", True)),
        "cleaning_yen": row.get("cleaning_yen"),
        "original_daily_rent_yen": to_per_day(row.get("rent_original_yen"), unit),
        "discounted_daily_rent_yen": to_per_day(row.get("rent_current_yen"), unit),
        # 決定 11: 換算不能は null 透過 (旧実装の `or 0` 畳み込みは廃止)
        "management_fee_daily_yen": to_per_day(row.get("management_yen"), unit),
        "cleaning_fee_yen": row.get("cleaning_yen"),
        "raw_text": row.get("raw_text"),
        # totals: approx MONTH_DAYS (30) for catalog
        "original_total_yen": None,
        "discounted_total_yen": None,
        "total_period_days": MONTH_DAYS,
    }
    od = plan["original_daily_rent_yen"]
    dd = plan["discounted_daily_rent_yen"]
    md = plan["management_fee_daily_yen"]
    # 決定 11: 日額のいずれかが算出不能 (null) なら 30 日総額も null を透過
    if od is not None and md is not None:
        plan["original_total_yen"] = (od + md) * MONTH_DAYS
    if dd is not None and md is not None:
        plan["discounted_total_yen"] = (dd + md) * MONTH_DAYS
    return plan


def apply_effective_rent_plans(
    plans: list[dict[str, Any]],
    campaigns: list[dict[str, Any]],
    *,
    on_date: str | None = None,
) -> list[dict[str, Any]]:
    """Attach effective_daily_rent_yen using domain.pricing."""
    # Normalize campaign target_plan_code alias (SSOT: domain.pricing)
    cams = [campaign_with_plan_key(c) for c in campaigns]

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
        # 決定 11: 日額・共益費日額のいずれかが null なら 30 日総額も null を透過
        ed = d.get("effective_daily_rent_yen")
        md = d.get("management_fee_daily_yen")
        if ed is not None and md is not None:
            d["effective_total_yen"] = (ed + md) * MONTH_DAYS
        out.append(d)
    return out


# 1 発行あたりの IN リストサイズを一定に保つためのチャンク幅。
# PG はプレースホルダ上限が 65535 と大きく旧 SQLite(999)の上限対策は不要だが、
# 巨大 IN リストの抑止として分割発行を維持する
_CHILD_IN_CHUNK = 900


def _fetch_child_rows_by_property(
    conn: psycopg.Connection,
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
        placeholders = ",".join("%s" for _ in chunk)
        for row in conn.execute(select_sql.format(placeholders=placeholders), chunk):
            grouped.setdefault(row["property_id"], []).append(dict(row))
    return grouped


# 画像行 + メディア結合の正本 (docs/media-storage-rustfs-plan.md §2.8)。
# 検索子行取得 (_IMAGE_CHILD_SQL) と物件詳細 (queries/detail.py) で同一の
# SELECT を使うためここに集約する。dhash は 16進16桁へ整形して配信
# (FE lib/media.ts のハミング距離計算と対)。
_MEDIA_IMAGE_COLS = (
    "pi.image_url, pi.image_type, pi.sort_order, "
    "ma.id AS media_id, "
    "CASE WHEN ma.dhash IS NULL THEN NULL "
    "ELSE lpad(to_hex(ma.dhash), 16, '0') END AS dhash, "
    "(ma.thumb_key IS NOT NULL) AS has_thumb"
)
_MEDIA_IMAGE_JOIN = (
    "FROM property_images pi LEFT JOIN media_assets ma ON ma.id = pi.media_id"
)

# 標準4子テーブルの SELECT。property_id IN ({placeholders}) 形式で
# _fetch_child_rows_by_property に渡す。
_ACCESS_CHILD_SQL = (
    "SELECT property_id, line_name, station_name, walk_minutes "
    "FROM property_accesses WHERE property_id IN ({placeholders}) "
    "ORDER BY property_id, sort_order NULLS FIRST, id"
)
_IMAGE_CHILD_SQL = (
    f"SELECT pi.property_id, {_MEDIA_IMAGE_COLS} {_MEDIA_IMAGE_JOIN} "
    "WHERE pi.property_id IN ({placeholders}) "
    "ORDER BY pi.property_id, pi.sort_order NULLS FIRST, pi.id"
)
_PLAN_CHILD_SQL = (
    "SELECT * FROM price_plans WHERE property_id IN ({placeholders}) "
    "ORDER BY property_id, duration_min_days"
)
_CAMPAIGN_CHILD_SQL = (
    "SELECT * FROM campaigns WHERE property_id IN ({placeholders}) "
    "ORDER BY property_id, id"
)
_FEATURES_CHILD_SQL = (
    "SELECT property_id, feature_name, category FROM property_features "
    "WHERE property_id IN ({placeholders})"
)


class StandardChildMaps(NamedTuple):
    """fetch_standard_child_maps の戻り値 (property_id → 子行リスト)."""

    access: dict[int, list[dict[str, Any]]]
    image: dict[int, list[dict[str, Any]]]
    plan: dict[int, list[dict[str, Any]]]
    campaign: dict[int, list[dict[str, Any]]]


def fetch_standard_child_maps(
    conn: psycopg.Connection, pids: Sequence[int]
) -> StandardChildMaps:
    """_property_row_to_result が要求する標準4子テーブルを IN 一括取得する.

    search_properties (iter) / get_properties_by_ids 共用。SQL文字列の
    SSOT はこのモジュールの _*_CHILD_SQL 定数。
    """
    return StandardChildMaps(
        access=_fetch_child_rows_by_property(conn, _ACCESS_CHILD_SQL, pids),
        image=_fetch_child_rows_by_property(conn, _IMAGE_CHILD_SQL, pids),
        plan=_fetch_child_rows_by_property(conn, _PLAN_CHILD_SQL, pids),
        campaign=_fetch_child_rows_by_property(conn, _CAMPAIGN_CHILD_SQL, pids),
    )


# 最寄り駅徒歩分の相関サブクエリ式。_property_list_sql の SELECT 別名
# (min_walk_minutes)と、検索 SQL 化(決定 10)での max_walk 前段絞り込み
# (search.count_properties の derived table)で同一式を共用する SSOT。
MIN_WALK_SUBQUERY = (
    "(SELECT MIN(walk_minutes) FROM property_accesses "
    "WHERE property_id = p.id AND walk_minutes IS NOT NULL)"
)


def _property_list_sql(tail: str) -> str:
    """物件一覧系 (iter_search_properties / get_properties_by_ids) 共通の主問合せ.

    本体行 + ショートリスト状態(+最終更新時刻) + min_walk_minutes / thumbnail_url の
    相関サブクエリまでが完全同一のためここに集約し、tail に WHERE / ORDER BY / LIMIT 節を渡す。
    """
    return f"""
        SELECT p.*, s.status as shortlist_status,
               s.updated_at as shortlist_updated_at,
               {MIN_WALK_SUBQUERY} as min_walk_minutes,
               (SELECT image_url FROM property_images
                WHERE property_id = p.id
                ORDER BY CASE image_type WHEN 'thumbnail' THEN 0 WHEN 'gallery' THEN 1 ELSE 2 END,
                         sort_order NULLS FIRST, id LIMIT 1) as thumbnail_url
        FROM properties p
        LEFT JOIN property_shortlists s ON s.property_id = p.id
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

    # alias target_plan_code for legacy-style consumers + target_plan_label
    # (表示ラベル・SSOT: domain.plan_catalog) — API 応答への唯一の変換窓口
    cam_rows = [campaign_row_to_api(c) for c in cam_rows]

    rent_plans = [price_plan_row_to_rent_plan(p) for p in plan_rows]
    rent_plans = apply_effective_rent_plans(rent_plans, cam_rows)

    min_daily = None
    min_total = None
    min_name = None
    min_label = None
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
            min_label = p.get("plan_label")

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
        # 所在階・向きは整数列が正本 (docs/floor-number-ssot-plan.md /
        # docs/orientation-model-plan.md)。API は生値のみ配信し、表示・フィルタへの
        # 派生は消費側で行う (SSOT の二重化を避ける)
        "floor_number": row.get("floor_number"),
        "floor_number_max": row.get("floor_number_max"),
        "orientation_deg": row.get("orientation_deg"),
        "total_score": row.get("total_score") or 0,
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "point_text": row.get("point_text"),
        "min_walk_minutes": row.get("min_walk_minutes"),
        "min_daily_rent": min_daily if min_daily is not None else row.get("catalog_rent_per_day_yen"),
        "min_plan_total": min_total,
        "min_plan_name": min_name,
        "min_plan_label": min_label,
        "thumbnail_url": row.get("thumbnail_url"),
        "shortlist_status": row.get("shortlist_status"),
        "shortlist_updated_at": row.get("shortlist_updated_at"),
        "is_active": bool(row.get("is_active", True)),
        "last_seen_at": row.get("last_seen_at"),
        "contract_fee_yen": resolve_contract_fee_yen(row),
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
