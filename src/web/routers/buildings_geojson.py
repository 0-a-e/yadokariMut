"""建物単位 GeoJSON 配信 (一括 / NDJSON ストリーム) + 建物ショートリスト更新。

建物単位集約モデル Phase B1 (docs/building-aggregation-design.md §6.1)。
1 Feature = 1 建物 + units 配列で、limit・meta.total の単位は建物数。
既存の部屋単位 /api/geojson (web/routers/geojson.py) は無変更で B2 まで併存する。
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import api_models
from store.queries.buildings import (
    count_buildings,
    iter_geojson_building_features,
    update_building_shortlist,
)

router = APIRouter()


# Request schema for updating building shortlist (status は当面 saved/none のみ)
class BuildingShortlistUpdateRequest(BaseModel):
    status: str
    comment: Optional[str] = None


# Dynamic GeoJSON Builder Helper
def get_buildings_geojson_data(params: dict) -> dict:
    """建物 FeatureCollection 全体を組み立てて返す (MCP / agent 等の呼び出し側がある).

    /api/buildings/geojson/stream と同一の iter_geojson_building_features を
    消費するため、一括取得とストリームで payload が一致する。
    """
    return {
        "type": "FeatureCollection",
        "features": list(iter_geojson_building_features(params)),
    }


@router.get("/api/buildings/geojson", response_model=api_models.BuildingGeoJSON)
def get_buildings_geojson_api(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[str] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    natural_query: Optional[str] = None,
    limit: int = 10000,
):
    """
    建物単位の検索結果を GeoJSON FeatureCollection (1 Feature = 1 建物 + units) で返す。

    部屋条件 (required_features / max_monthly / max_walk / min_area 等) は
    「条件を満たす部屋を 1 つ以上持つ建物」がヒットし、units には建物の
    可視部屋全てを載せる (client-side worker が部屋単位で再フィルタする)。
    limit の単位は建物数。契約の正本は docs/building-aggregation-design.md §6.1。

    natural_query (PG移行 Phase 7): 自然文意味検索 (pgvector + gemini-embedding-2)。
    指定時は意味距離の昇順に建物がソートされ、embedding 未カバー物件は除外される。
    """
    # params dict の組立正本は api_models.SearchFilters (H2)。
    # QUERY STRING の受付形式 (required_features はカンマ区切り文字列) と
    # CSV 正規化の所在は部屋単位 web/routers/geojson.py と同一。
    params = api_models.SearchFilters(
        prefecture_name=prefecture_name,
        max_monthly_total_yen=max_monthly_total_yen,
        max_walk_minutes=max_walk_minutes,
        min_area_m2=min_area_m2,
        required_features=required_features,
        saved_only=saved_only,
        exclude_hidden=exclude_hidden,
        natural_query=natural_query,
        limit=limit,
    ).to_query_params()
    return get_buildings_geojson_data(params)


@router.get("/api/buildings/geojson/stream")
def get_buildings_geojson_stream_api(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[str] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    natural_query: Optional[str] = None,
    limit: int = 10000,
):
    """建物GeoJSONを1行ずつ流すNDJSONストリーム (1行 = 1建物Feature)。初期ロード進捗表示用。

    行契約 (StreamingResponse のため response_model は持たない):
    - 1行目: {"type": "meta", "total": <int 建物数>}
    - 中間行: {"type": "feature", "feature": <BuildingFeature>}
    - 末尾行: {"type": "end", "count": <int 建物数>}
    feature の型は GET /api/buildings/geojson (BuildingGeoJSON) と同一。

    注意: meta.total は上限概算値。max_monthly_total_yen は post filter のため
    未反映。加えて建物代表座標が欠落した建物をスキップするため end.count と
    一致する保証がない (limit は建物数に効くため end.count ≤ meta.total)。
    natural_query (PG移行 Phase 7・意味検索) の意味論は一括版と同一。
    """
    # params dict の組立正本は get_buildings_geojson_api と同一
    # (api_models.SearchFilters)。required_features は生 CSV 文字列のまま渡し、
    # 正規化は queries 層の正本。
    params = api_models.SearchFilters(
        prefecture_name=prefecture_name,
        max_monthly_total_yen=max_monthly_total_yen,
        max_walk_minutes=max_walk_minutes,
        min_area_m2=min_area_m2,
        required_features=required_features,
        saved_only=saved_only,
        exclude_hidden=exclude_hidden,
        natural_query=natural_query,
        limit=limit,
    ).to_query_params()

    def _gen():
        yield json.dumps({"type": "meta", "total": count_buildings(params)}, ensure_ascii=False) + "\n"
        n = 0
        for feat in iter_geojson_building_features(params):
            n += 1
            yield json.dumps({"type": "feature", "feature": feat}, ensure_ascii=False, separators=(",", ":")) + "\n"
        yield json.dumps({"type": "end", "count": n}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/api/buildings/{building_id}/shortlist",
    response_model=api_models.BuildingShortlistUpdateResponse,
)
def update_building_shortlist_api(building_id: int, data: BuildingShortlistUpdateRequest):
    """建物ショートリスト状態を更新する (status: saved / none)。

    部屋の POST /api/properties/{id}/shortlist と対称。建物側は当面
    saved(+メモ)のみ運用のため、hide/reject は 422 で拒否する。
    buildings.id は数値一意のため by/source 解決は不要(未検出は 404)。
    """
    if data.status not in ("saved", "none"):
        raise HTTPException(
            status_code=422,
            detail="status must be 'saved' or 'none' for buildings",
        )
    res = update_building_shortlist(building_id, data.status, data.comment)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail="Building not found")
    return {
        "status": "success",
        "building_id": res["building_id"],
        "shortlist_status": data.status,
    }
