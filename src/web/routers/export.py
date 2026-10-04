"""Google Earth 用 KML エクスポート。"""

from datetime import datetime
from typing import List

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from store.api_queries import get_properties_by_ids
from store.kml_export import build_kml_document

router = APIRouter()


class KmlExportRequest(BaseModel):
    """Body for KML export (/api/export/kml)."""

    ids: List[int]


# レスポンスサイズ爆発のガード。全物件(約8千件)でも十分余裕のある上限
KML_EXPORT_MAX_IDS = 20000


@router.post("/api/export/kml")
def export_kml_api(body: KmlExportRequest):
    """指定物件 ID 群を Google Earth 用 KML としてダウンロードさせる.

    FE の表示中リスト(フィルタ適用済み)をそのまま出力する想定のため、
    is_active や shortlist 状態による絞り込みは行わない。
    """
    ids = list(dict.fromkeys(body.ids))  # 重複除去(順序維持)
    if not ids:
        raise HTTPException(status_code=400, detail="ids is empty")
    if len(ids) > KML_EXPORT_MAX_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many ids: {len(ids)} (max {KML_EXPORT_MAX_IDS})",
        )
    properties = get_properties_by_ids(ids)
    if not properties:
        raise HTTPException(status_code=404, detail="No properties found for the given ids")
    kml = build_kml_document(properties)
    filename = f"yadokari_{datetime.now().strftime('%Y%m%d_%H%M')}.kml"
    return Response(
        content=kml,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
