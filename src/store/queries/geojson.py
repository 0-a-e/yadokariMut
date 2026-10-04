"""GeoJSON Feature 組み立て / ストリーム / 一括エクスポート."""

from __future__ import annotations

import os
from typing import Any

from store.queries._common import (
    _CHILD_IN_CHUNK,
    _fetch_child_rows_by_property,
    _repo,
    clean_point_text,
)
from store.queries.search import iter_search_properties, search_properties


def _geojson_feature_from_prop(
    prop: dict[str, Any],
    feature_names: list[str],
) -> dict[str, Any]:
    """search 結果 1 物件 + 設備名リストから GeoJSON Feature dict を組み立てる.

    旧 web_server.get_geojson_data 内の 1 物件分の組み立て (access_summary 文字列化 /
    station_list 抽出 / clean_point_text / images の URL への映射 / campaigns) を
    そのまま移設したもの。キー構成は既存 /api/geojson と完全一致させ、
    一括取得とストリーム配信で同じ payload を返す。
    """
    lat = prop["lat"]
    lng = prop["lng"]

    access_raw = prop.get("access_summary") or []
    if isinstance(access_raw, str):
        access_str = access_raw
        access_list = [x.strip() for x in access_raw.split(",") if x.strip()]
    else:
        access_list = list(access_raw)
        access_str = ", ".join(access_list)

    station_list = []
    for a in access_list:
        parts = str(a).split(" ")
        if len(parts) > 1:
            station_list.append(parts[1])
    station_summary = ", ".join(station_list)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lng, lat],
        },
        "properties": {
            "id": prop["id"],
            "room_id": prop.get("source_property_id") or prop.get("external_id"),
            "source_site": prop.get("source_site"),
            "source_display_name": prop.get("source_display_name"),
            "title": prop["title"],
            "detail_url": prop["detail_url"],
            "address": prop["address"],
            "prefecture_name": prop.get("prefecture_name"),
            "municipality": prop.get("municipality"),
            "layout": prop["layout"],
            "area_m2": prop["area_m2"],
            "min_daily_rent": prop["min_daily_rent"],
            "min_plan_total": prop["min_plan_total"],
            "min_plan_name": prop["min_plan_name"],
            "min_walk_minutes": prop["min_walk_minutes"],
            "thumbnail_url": prop.get("thumbnail_url"),
            "images": [
                (img["image_url"] if isinstance(img, dict) else img)
                for img in prop.get("images", [])
            ],
            "total_score": prop["total_score"],
            "shortlist_status": prop["shortlist_status"] or "none",
            "is_active": bool(prop.get("is_active", True)),
            "last_seen_at": prop.get("last_seen_at"),
            "access_summary": access_str,
            "feature_summary": ", ".join(feature_names),
            "station_summary": station_summary,
            "point_text": clean_point_text(prop.get("point_text")),
            "rent_plans": prop.get("rent_plans", []),
            # campaigns_map 経由の旧代入は prop["campaigns"] があればそれを使う
            # 挙動と等価なので、単純に or [] で置き換え
            "campaigns": prop.get("campaigns") or [],
        },
    }


def iter_geojson_features(params: dict[str, Any] | None = None):
    """検索結果を GeoJSON Feature として 1 物件ずつ yield するジェネレータ.

    NDJSON ストリーム (/api/geojson/stream) 用。lat/lng が欠けている物件は
    get_geojson_data と同一挙動でスキップする。feature_summary 用の
    property_features は巨大な IN を避けるため 900 件ずつバッファして一括取得する。
    接続はジェネレータ内で開き、finally で閉じる。
    """
    params = params or {}

    def _features_for(props: list[dict[str, Any]]) -> dict[int, list[str]]:
        """バッファ中の物件の property_features を IN 一括取得して束ねる."""
        if not props:
            return {}
        rows = _fetch_child_rows_by_property(
            conn,
            "SELECT property_id, feature_name FROM property_features "
            "WHERE property_id IN ({placeholders})",
            [p["id"] for p in props],
        )
        return {
            p["id"]: [r["feature_name"] for r in rows.get(p["id"], [])]
            for p in props
        }

    repo = _repo()
    conn = repo.connect()
    try:
        buffer: list[dict[str, Any]] = []
        for prop in iter_search_properties(params):
            lat = prop.get("lat")
            lng = prop.get("lng")
            if lat is None or lng is None:
                continue
            buffer.append(prop)
            if len(buffer) < _CHILD_IN_CHUNK:
                continue
            names_map = _features_for(buffer)
            for p in buffer:
                yield _geojson_feature_from_prop(p, names_map[p["id"]])
            buffer = []
        # 端数チャンク
        names_map = _features_for(buffer)
        for p in buffer:
            yield _geojson_feature_from_prop(p, names_map[p["id"]])
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

    # /api/geojson と同一ビルダーで組み立てる (is_active / last_seen_at /
    # clean_point_text 適用済み point_text を含む)。lat/lng 欠落物件はスキップ。
    features = [
        _geojson_feature_from_prop(prop, features_map.get(prop["id"], []))
        for prop in properties
        if prop.get("lat") is not None and prop.get("lng") is not None
    ]

    geojson = {"type": "FeatureCollection", "features": features}
    if file_path is None:
        # 既定出力先はリポジトリルート直下ではなく data/exports/ (永続領域・デプロイ同期外)
        # 本ファイルは src/store/queries/ 配下のためルートへは 3 つ上へ辿る
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "data",
            "exports",
            "map.geojson",
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    return {"status": "success", "file_path": file_path, "feature_count": len(features)}
