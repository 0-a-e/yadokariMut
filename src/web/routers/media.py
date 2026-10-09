"""メディア配信 API (GET /api/media/{id}・docs/media-storage-rustfs-plan.md §2.8)。

rustfs (S3) の private バケットから BE プロキシで配信する。内容アドレス =
不変のため長期キャッシュヘッダを付ける(ETag=sha256・immutable)。認証は他
``/api/*`` と同じく前方の Cloudflare Access が効く前提で、個別の認証は持たない。

レスポンスはバイナリストリームのため response_model を持たない
(契約テストの UNTYPED_EXEMPT_PATHS 対象・stream 系と同じ扱い)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from store.pg import open_connection

router = APIRouter()

_VALID_VARIANTS = ("thumb",)


def _load_store():
    """設定済みなら MediaStore を返す。未設定(None)は graceful degradation。"""
    from store.media import MediaStore, load_media_config

    config = load_media_config()
    if config is None:
        return None
    return MediaStore(config)


@router.get("/api/media/{media_id}")
def get_media(media_id: int, variant: str | None = Query(default=None)):
    """保存済みメディア 1 件を配信する (?variant=thumb で 640px WebP)。"""
    if variant is not None and variant not in _VALID_VARIANTS:
        raise HTTPException(status_code=400, detail="invalid variant")

    store = _load_store()
    if store is None:
        raise HTTPException(status_code=503, detail="media storage disabled")

    with open_connection() as conn:
        row = conn.execute(
            "SELECT sha256, mime_type, object_key, thumb_key FROM media_assets WHERE id = %s",
            (media_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="media not found")

    key = row["thumb_key"] if variant == "thumb" else row["object_key"]
    if not key:
        raise HTTPException(status_code=404, detail="variant not available")

    try:
        obj = store.get_object(key)
    except Exception:
        raise HTTPException(status_code=502, detail="object storage error")

    media_type = (
        "image/webp" if variant == "thumb" else (row["mime_type"] or "application/octet-stream")
    )
    return StreamingResponse(
        obj["Body"],
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{row["sha256"]}"',
        },
    )
