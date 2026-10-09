"""マップビューア配信(アプリケーション HTML)。

物件 GeoJSON 系エンドポイントは建物単位へ集約され routers/buildings_geojson.py
へ移行済み(B2-ε で旧部屋単位の /map.geojson・/api/geojson・/api/geojson/stream
を廃止 — docs/building-aggregation-design.md §6.1)。
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from web import REPO_ROOT

router = APIRouter()


@router.get("/")
def get_map_viewer():
    """Serves the main map viewer application HTML (React index.html)."""
    viewer_path = os.path.join(REPO_ROOT, "frontend", "dist", "index.html")
    if os.path.exists(viewer_path):
        return FileResponse(viewer_path)

    raise HTTPException(
        status_code=404,
        detail="Frontend build not found. Please run 'pnpm build' in the frontend directory.",
    )
