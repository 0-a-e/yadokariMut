"""PMTiles → ZXY ベクタタイル配信ルータ(map-layer-system-v2).

scripts/ksj/ パイプラインで生成した国土数値情報由来の PMTiles
(data/tiles/{code}.pmtiles)を、MapLibre がそのまま要求できる通常の
ZXY エンドポイント GET /api/tiles/{code}/{z}/{x}/{y}.pbf として配信する。

- maplibre v6 は Web Worker 内での PMTiles プロトコル登録に問題があるため、
  サーバ側で PMTiles を ZXY に展開して返す方式を採る
- code は小文字のデータセットコード(n03 / l01 / a31b 等)。
  ^[a-z0-9_-]+$ のみ受理し、パストラバーサルを構造的に排除する
- 読み取りは pmtiles.reader.Reader + MmapSource。オープン済み Reader は
  code → Reader の dict で単純な遅延初期化キャッシュする
  (PMTiles の差し替えはサーバ再起動で反映)

レスポンス仕様:
- ファイルが無い code        → 404
- アーカイブ内にタイルが無い → 204 No Content
  (MapLibre は 204 を「このタイルは空」として正しく扱う)
- 存在する                   → 200 / application/x-protobuf /
                               Cache-Control: public, max-age=86400
"""

from __future__ import annotations

import gzip
import os
import re
import threading
from typing import IO, Optional, Tuple

from fastapi import APIRouter, HTTPException, Path, Response
from pmtiles.reader import Compression, MmapSource, Reader

router = APIRouter(tags=["tiles"])

# code は小英数字・ハイフン・アンダースコアのみ(相対パス断片を拒否)
_CODE_PATTERN = r"^[a-z0-9_-]+$"
_CODE_RE = re.compile(_CODE_PATTERN)
_MAX_ZOOM = 16

# code → (ファイルオブジェクト, Reader)。遅延初期化の単純キャッシュ
_READERS: dict[str, Tuple[IO[bytes], Reader]] = {}
_READERS_LOCK = threading.Lock()


def _tiles_dir() -> str:
    """タイル格納ディレクトリ(TILES_DIR、未設定時は data/tiles)。"""
    return os.environ.get("TILES_DIR") or os.path.join("data", "tiles")


def _get_reader(code: str) -> Optional[Reader]:
    """code の PMTiles Reader を遅延初期化付きで返す(ファイル無しは None)。

    一度開いたファイルはプロセス寿命まで開き続ける(mmap 参照のため)。
    """
    cached = _READERS.get(code)
    if cached is not None:
        return cached[1]
    path = os.path.join(_tiles_dir(), f"{code}.pmtiles")
    if not os.path.isfile(path):
        return None
    f = open(path, "rb")
    reader = Reader(MmapSource(f))
    with _READERS_LOCK:
        _READERS[code] = (f, reader)
    return reader


@router.get("/api/tiles/{code}/{z}/{x}/{y}.pbf")
def get_tile(
    code: str = Path(pattern=_CODE_PATTERN),
    z: int = Path(ge=0, le=_MAX_ZOOM),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    """PMTiles から指定 ZXY タイルを取り出して返す."""
    # x/y の上限は z 依存のためパターンで表現できず、ここで検証する
    if not _CODE_RE.match(code) or x >= (1 << z) or y >= (1 << z):
        raise HTTPException(status_code=404, detail="tile coordinates out of range")

    reader = _get_reader(code)
    if reader is None:
        raise HTTPException(status_code=404, detail=f"unknown tileset: {code}")

    data = reader.get(z, x, y)
    if not data:
        # MapLibre は 204 を「空タイル」として正しく扱う
        return Response(status_code=204)
    # tippecanoe 生成の PMTiles はタイル本体が gzip 圧縮(tile_compression)。
    # Reader.get() は生バイトを返すため、MapLibre に渡す前に展開する
    # (internal_compression はディレクトリ/メタデータの圧縮なので判定に使わない)
    if reader.header()["tile_compression"] == Compression.GZIP:
        data = gzip.decompress(data)
    return Response(
        content=data,
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=86400"},
    )
