"""物件詳細取得とショートリスト更新。

shortlist を `router` と別の `shortlist_router` に分離しているのは挙動上の
理由ではなく、旧 web_server.py の登録順 (detail → price-trend → shortlist)
を web.app.create_app() で再現し、frontend/openapi.json を byte 同値に保つ
ため (登録順が OpenAPI paths の並びになるため)。
"""

from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query

import api_models
from store.api_queries import (
    AmbiguousPropertyLookup,
    get_property_detail,
    update_shortlist,
)

router = APIRouter()
shortlist_router = APIRouter()


# Request schema for updating shortlist
class ShortlistUpdateRequest(BaseModel):
    status: str
    comment: Optional[str] = None


@router.get(
    "/api/properties/{property_id}",
    response_model=api_models.PropertyDetailResponse,
)
def get_property_detail_api(
    property_id: str,
    by: str = Query("auto", pattern="^(auto|id|external)$"),
    source: Optional[str] = None,
):
    """Gets detailed information for a single property.

    by=auto(既定) は数字キーを properties.id として優先解決する。room_id
    (external_id) で引く場合は by=external を指定し、複数ソースに存在する
    room_id では source(=source_site) も指定する。
    """
    try:
        detail = get_property_detail(property_id, by=by, source=source)
    except AmbiguousPropertyLookup as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not detail:
        raise HTTPException(status_code=404, detail="Property not found")
    return detail


@shortlist_router.post(
    "/api/properties/{property_id}/shortlist",
    response_model=api_models.ShortlistUpdateResponse,
)
def update_shortlist_api(
    property_id: str,
    data: ShortlistUpdateRequest,
    by: str = Query("auto", pattern="^(auto|id|external)$"),
    source: Optional[str] = None,
):
    """Updates shortlist status (saved, hide, reject, or None).

    解決ロジックは詳細取得と共通(id 優先)。external_id が複数ソースにまたがる
    場合は 409 を返し、推測で更新しない。
    """
    try:
        res = update_shortlist(property_id, data.status, data.comment, by=by, source=source)
    except AmbiguousPropertyLookup as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail="Property not found")
    return {
        "status": "success",
        "property_id": res.get("property_id"),
        "shortlist_status": data.status,
    }
