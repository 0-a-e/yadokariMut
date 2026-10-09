#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for GET /api/media/{id} (rustfs プロキシ配信・docs/media-storage-rustfs-plan.md §2.8)。

MediaStore は _load_store を差し替えて S3 往返なしで検証する(契約は
store.media.MediaStore.get_object が boto3 get_object 互換の
{Body: iterator} を返すことのみ)。
"""

import pytest


class _FakeStore:
    """boto3 get_object 互換の fake。キーごとに異なるバイトを返す。"""

    def __init__(self):
        self.requested_keys = []

    def get_object(self, key):
        self.requested_keys.append(key)
        payload = f"bytes-of:{key}".encode()
        return {"Body": iter([payload])}


@pytest.fixture()
def fake_store(monkeypatch):
    store = _FakeStore()
    import web.routers.media as media_router

    monkeypatch.setattr(media_router, "_load_store", lambda: store)
    return store


@pytest.fixture()
def disabled_store(monkeypatch):
    import web.routers.media as media_router

    monkeypatch.setattr(media_router, "_load_store", lambda: None)


def _insert_media(thumb_key=None, mime="image/jpeg") -> int:
    from store.pg import open_connection

    with open_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO media_assets
                (sha256, bucket, object_key, thumb_key, mime_type, size_bytes)
            VALUES (%s, 'yadokari-media', %s, %s, %s, 100)
            RETURNING id
            """,
            (
                "a" * 64,
                "sha256/aa/" + "a" * 60 + ".jpg",
                thumb_key,
                mime,
            ),
        ).fetchone()
        conn.commit()
        return int(row["id"])


def test_get_media_original(client, fake_store):
    media_id = _insert_media()
    resp = client.get(f"/api/media/{media_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resp.headers["etag"] == f'"{"a" * 64}"'
    assert resp.content.startswith(b"bytes-of:")


def test_get_media_thumb(client, fake_store):
    media_id = _insert_media(thumb_key="derived/640/" + "a" * 64 + ".webp")
    resp = client.get(f"/api/media/{media_id}?variant=thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/webp")
    assert "derived/640/" in fake_store.requested_keys[0]


def test_get_media_invalid_variant(client, fake_store):
    resp = client.get("/api/media/1?variant=large")
    assert resp.status_code == 400


def test_get_media_not_found(client, fake_store):
    resp = client.get("/api/media/99999")
    assert resp.status_code == 404


def test_get_media_thumb_missing(client, fake_store):
    # thumb_key が NULL の行へ ?variant=thumb は 404
    media_id = _insert_media(thumb_key=None)
    resp = client.get(f"/api/media/{media_id}?variant=thumb")
    assert resp.status_code == 404


def test_get_media_disabled(client, disabled_store):
    resp = client.get("/api/media/1")
    assert resp.status_code == 503
