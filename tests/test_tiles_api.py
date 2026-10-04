#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tiles router (PMTiles → ZXY 配信 API).

web_server 全体(langgraph / copilotkit 等の重依存)は import せず、
tiles ルータだけを素の FastAPI にマウントした lightweight 構成で検証する。
テスト用の極小 PMTiles は pmtiles.writer でその場で生成する
(最小 MVT 数バイトのタイルを 2 枚含むアーカイブ)。
"""

import os

import pytest


from fastapi import FastAPI
from fastapi.testclient import TestClient
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write

import tiles as tiles_mod
from tiles import router as tiles_router

# 最小構成の MVT(layer{name=...}, version=2)。サーバ側では不透過 bytes
MVT_A = b"\x0a\x01l\x78\x02"
MVT_B = b"\x0a\x01m\x78\x02"

CODE = "n03"


def _write_pmtiles(path, tiles, tile_compression=Compression.NONE):
    """{ (z, x, y): bytes } のタイルを含む極小 PMTiles を作る。

    tile_compression=GZIP を指定する場合は呼び出し側がタイル本体も
    gzip 済みで渡す(pmtiles.writer は生バイトをそのまま格納する)。
    """
    header = {
        "version": 3,
        "tile_compression": tile_compression,
        "tile_type": TileType.MVT,
        "min_zoom": min(z for z, _, _ in tiles),
        "max_zoom": max(z for z, _, _ in tiles),
        "min_lon_e7": 0,
        "min_lat_e7": 0,
        "max_lon_e7": 0,
        "max_lat_e7": 0,
        "center_zoom": 8,
        "center_lon_e7": 0,
        "center_lat_e7": 0,
    }
    with write(path) as w:
        for (z, x, y), data in tiles.items():
            w.write_tile(zxy_to_tileid(z, x, y), data)
        w.finalize(header, {"vector_layers": []})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """tiles ルータのみをマウントした TestClient(TILES_DIR は tmp_path)。"""
    monkeypatch.setenv("TILES_DIR", str(tmp_path))
    _write_pmtiles(
        os.path.join(str(tmp_path), f"{CODE}.pmtiles"),
        {(8, 136, 68): MVT_A, (8, 137, 68): MVT_B},
    )
    tiles_mod._READERS.clear()  # TILES_DIR 変更前にキャッシュを空にする
    app = FastAPI()
    app.include_router(tiles_router)
    yield TestClient(app)
    tiles_mod._READERS.clear()  # tmp_path の mmap をテスト間で持ち越さない


def test_existing_tile_returns_200_with_body(client):
    res = client.get(f"/api/tiles/{CODE}/8/136/68.pbf")
    assert res.status_code == 200
    assert res.content == MVT_A
    assert res.headers["content-type"] == "application/x-protobuf"
    assert res.headers["cache-control"] == "public, max-age=86400"

    # 2 枚目(Reader キャッシュ経由の 2 回目アクセス)
    res2 = client.get(f"/api/tiles/{CODE}/8/137/68.pbf")
    assert res2.status_code == 200
    assert res2.content == MVT_B


def test_gzip_tile_is_served_decompressed(tmp_path, monkeypatch):
    """tile_compression=GZIP のアーカイブ(tippecanole 生成物と同じ形式)は
    展開後の MVT を返す。tile 圧縮はタイル本体、internal はディレクトリ/
    メタデータの圧縮で、判定に使うのは前者。"""
    import gzip

    monkeypatch.setenv("TILES_DIR", str(tmp_path))
    _write_pmtiles(
        os.path.join(str(tmp_path), "gz.pmtiles"),
        {(8, 136, 68): gzip.compress(MVT_A)},
        tile_compression=Compression.GZIP,
    )
    tiles_mod._READERS.clear()
    app = FastAPI()
    app.include_router(tiles_router)
    try:
        res = TestClient(app).get("/api/tiles/gz/8/136/68.pbf")
        assert res.status_code == 200
        assert res.content == MVT_A  # gzip のままではなく展開済み
    finally:
        tiles_mod._READERS.clear()


def test_absent_tile_returns_204(client):
    res = client.get(f"/api/tiles/{CODE}/8/136/69.pbf")
    assert res.status_code == 204
    assert res.content == b""


def test_unknown_code_returns_404(client):
    res = client.get("/api/tiles/l01/8/136/68.pbf")
    assert res.status_code == 404


def test_invalid_code_is_rejected(client):
    # 大文字 / ドット等はコードとして不正 → ルート pattern 違反の 422
    for code in ["N03", "a.b", "..", "%2e%2e", "n03!"]:
        res = client.get(f"/api/tiles/{code}/8/0/0.pbf")
        assert res.status_code in (404, 422), f"code={code!r} -> {res.status_code}"


def test_path_traversal_is_rejected(client):
    for url in [
        "/api/tiles/..%2Fsecret/8/0/0.pbf",
        "/api/tiles/..%2F..%2Fetc/8/0/0.pbf",
        "/api/tiles/.%2Eyml/8/0/0.pbf",
    ]:
        res = client.get(url)
        assert res.status_code in (404, 422), f"url={url} -> {res.status_code}"


def test_zoom_out_of_range_returns_422(client):
    assert client.get(f"/api/tiles/{CODE}/17/0/0.pbf").status_code == 422
    assert client.get(f"/api/tiles/{CODE}/-1/0/0.pbf").status_code == 422


def test_xy_out_of_range_returns_404(client):
    # x / y は 0 <= x, y < 2^z。上限は z 依存のためハンドラ側で 404
    assert client.get(f"/api/tiles/{CODE}/1/2/0.pbf").status_code == 404
    assert client.get(f"/api/tiles/{CODE}/1/0/2.pbf").status_code == 404
    assert client.get(f"/api/tiles/{CODE}/8/256/0.pbf").status_code == 404
    assert client.get(f"/api/tiles/{CODE}/16/65536/0.pbf").status_code == 404
    # 負値はパスパラメタ制約違反の 422
    assert client.get(f"/api/tiles/{CODE}/8/-1/0.pbf").status_code == 422
    # 境界値そのものは妥当(タイルが無いので 204)
    assert client.get(f"/api/tiles/{CODE}/16/0/0.pbf").status_code == 204
    assert client.get(f"/api/tiles/{CODE}/16/65535/65535.pbf").status_code == 204


def test_non_pbf_suffix_is_not_matched(client):
    res = client.get(f"/api/tiles/{CODE}/8/136/68.json")
    assert res.status_code == 404
