"""マップビューア配信と物件 GeoJSON (一括 / NDJSON ストリーム)。"""

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

import api_models
from store.api_queries import count_properties, iter_geojson_features
from web import REPO_ROOT

router = APIRouter()


# Dynamic GeoJSON Builder Helper
def get_geojson_data(params: dict) -> dict:
    """FeatureCollection 全体を組み立てて返す (MCP / agent 等の呼び出し側がある).

    1 物件分の Feature 組み立ては store.api_queries._geojson_feature_from_prop へ
    移設済み。/api/geojson/stream と同一の iter_geojson_features を消費するため、
    一括取得とストリームで payload が一致する。
    """
    return {"type": "FeatureCollection", "features": list(iter_geojson_features(params))}


@router.get("/")
def get_map_viewer():
    """Serves the main map viewer application HTML (React index.html or fallback map_viewer.html)."""
    viewer_path = os.path.join(REPO_ROOT, "frontend", "dist", "index.html")
    if os.path.exists(viewer_path):
        return FileResponse(viewer_path)

    fallback_path = os.path.join(REPO_ROOT, "map_viewer.html")
    if os.path.exists(fallback_path):
        return FileResponse(fallback_path)

    raise HTTPException(
        status_code=404,
        detail="Frontend build not found. Please run 'pnpm build' in the frontend directory."
    )


@router.get("/map.geojson", response_model=api_models.PropertyGeoJSON)
@router.get("/api/geojson", response_model=api_models.PropertyGeoJSON)
def get_geojson_api(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[str] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    limit: int = 10000,
):
    """
    Returns property search results directly formatted as a GeoJSON FeatureCollection.
    If map_viewer.html falls back to map.geojson, this serves the same endpoint.

    このフィルタパラメータは CLI / MCP 用。FE は /api/geojson/stream で全件を
    取得し client-side worker で完全フィルタする。
    """
    features_list = None
    if required_features:
        features_list = [f.strip() for f in required_features.split(",") if f.strip()]

    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": features_list,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
        "limit": limit
    }
    return get_geojson_data(params)


@router.get("/api/geojson/stream")
def get_geojson_stream_api(
    prefecture_name: Optional[str] = None,
    max_monthly_total_yen: Optional[int] = None,
    max_walk_minutes: Optional[int] = None,
    min_area_m2: Optional[float] = None,
    required_features: Optional[str] = None,
    saved_only: bool = False,
    exclude_hidden: bool = True,
    limit: int = 10000,
):
    """物件GeoJSONを1行ずつ流すNDJSONストリーム。初期ロード進捗表示用。

    行契約 (StreamingResponse のため response_model は持たない):
    - 1行目: {"type": "meta", "total": <int>}
    - 中間行: {"type": "feature", "feature": <PropertyFeature>}
    - 末尾行: {"type": "end", "count": <int>}
    feature の型は GET /api/geojson (PropertyGeoJSON) と同一。

    注意: meta.total は上限概算値。post filter (max_walk_minutes /
    required_features / max_monthly_total_yen) が未反映な上、座標欠落物件を
    スキップするため end.count と一致する保証がない。
    """
    features_list = None
    if required_features:
        features_list = [f.strip() for f in required_features.split(",") if f.strip()]

    # params dict の組み立ては get_geojson_api と同一
    params = {
        "prefecture_name": prefecture_name,
        "max_monthly_total_yen": max_monthly_total_yen,
        "max_walk_minutes": max_walk_minutes,
        "min_area_m2": min_area_m2,
        "required_features": features_list,
        "saved_only": saved_only,
        "exclude_hidden": exclude_hidden,
        "limit": limit
    }

    def _gen():
        yield json.dumps({"type": "meta", "total": count_properties(params)}, ensure_ascii=False) + "\n"
        n = 0
        for feat in iter_geojson_features(params):
            n += 1
            yield json.dumps({"type": "feature", "feature": feat}, ensure_ascii=False, separators=(",", ":")) + "\n"
        yield json.dumps({"type": "end", "count": n}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
