"""メディアストレージ (rustfs/S3互換) のクラスタ代表ストア (docs/media-storage-rustfs-plan.md §2.5)。

設計 (同計画 §2.5/§2.7・確定 U2/U3):

- **クラスタ代表のみ保存**: sha256 (バイト完全一致) で既知クラスタへ短絡し、
  未知なら dHash 近重複 (hamming ≤ :data:`DHASH_THRESHOLD` = 8/64・§1.6 実測で
  変異 0〜2 vs 別写真 28 以上のため単一しきい値) を ``media_assets`` から探す。
  候補が無ければ新しい代表として original + 640px WebP サムネイルを PUT して
  ``media_assets`` に INSERT し、候補より品質が劣る近重複は実体を保存せず
  ``media_variants`` に記録だけする (§2.7 ユーザー要件: 重複保存しない)。
  品質順は ``(width*height, size_bytes)`` の辞書順 (:func:`quality_rank`) で、
  代表はより良いバリアントの到着で差し替わる (旧代表は media_variants へ退避)。
- オブジェクトキーは内容アドレス (§1.3/§2.5 shiquge と同一規約):
  ``sha256/xx/yy/<sha>.<ext>`` / ``derived/640/<sha>.webp``。全 PUT に
  ``Cache-Control: public, max-age=31536000, immutable``。bucket は private の
  まま (配信は BE プロキシ・§2.8)。
- **env 駆動 + graceful degradation** (§2.3): ACCESS/SECRET 未設定なら
  :func:`load_media_config` が None を返し、:func:`backfill_media` は何もせず
  即 return する (スクレイプ・検索は無影響。endpoint/bucket/region は既定値あり)。
- **取り込みはバッチのみ** (§2.6): upsert 同期パスではダウンロードせず、日次
  ジョブ / CLI から :func:`backfill_media` を呼ぶ (backfill-embeddings と同じ
  慣習: ``--limit``/``--dry-run``/``--source``・進捗 500 件・1 行失敗で止まらない)。

同期 (スレッド) 前提。``MediaStore`` は boto3 クライアントを DI 可能
(:class:`MediaStore` の ``s3`` 引数) とし、S3 接続なしで単体テストできる。
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image

from store.pg import open_connection

# --- env (設計 §2.3・graceful degradation) --------------------------------

MEDIA_ENDPOINT_ENV = "YADOKARIMUT_RUSTFS_ENDPOINT"
MEDIA_ACCESS_KEY_ENV = "YADOKARIMUT_RUSTFS_ACCESS_KEY"
MEDIA_SECRET_ENV = "YADOKARIMUT_RUSTFS_SECRET_KEY"
MEDIA_BUCKET_ENV = "YADOKARIMUT_RUSTFS_BUCKET"
MEDIA_REGION_ENV = "YADOKARIMUT_RUSTFS_REGION"

DEFAULT_ENDPOINT = "http://rustfs:9000"
DEFAULT_BUCKET = "yadokari-media"
DEFAULT_REGION = "us-east-1"

# --- 定数 (設計 §1.6 / §2.5) ----------------------------------------------

# 近重複しきい値 (M0 実測 §1.6: 再エンコード/リサイズ変異 = 距離 0〜2、
# 別写真 = 28 以上。マージンが大きいため単一しきい値 8 で確定・U3)。
DHASH_THRESHOLD = 8
# 1 枚の取得上限 (超過は取得打ち切り・Pillow 前に判定)。
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# サムネイルは長辺 640 の WebP (キー ``derived/640/...`` と対応)。
THUMB_SIZE = (640, 640)
THUMB_QUALITY = 80

# 内蔵 fetcher (§2.6) の定数。
_FETCH_TIMEOUT_S = 30
_HOST_DELAY_S = 0.3  # 同一 host への連続 GET の最小間隔 (単一スレッド直列)
_FETCH_CHUNK = 64 * 1024
_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_ERROR_MAX = 200  # fetch_error に残す最大文字数
_MASK64 = (1 << 64) - 1

# Pillow フォーマット → オブジェクトキー拡張子 (未知は bin・§2.5)。
_EXT_BY_FORMAT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
}


@dataclass(frozen=True)
class MediaConfig:
    """rustfs 接続設定 (env から :func:`load_media_config` が組み立てる)。"""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str


def load_media_config() -> MediaConfig | None:
    """env から構成を読む (§2.3)。access/secret が無ければ None = 機能無効。

    endpoint/bucket/region は既定値へフォールバックするため、鍵 2 つの有無が
    有効・無効の唯一の判定条件 (「3 項目揃わない場合は無効」の実装)。
    """
    access_key = os.environ.get(MEDIA_ACCESS_KEY_ENV)
    secret_key = os.environ.get(MEDIA_SECRET_ENV)
    if not access_key or not secret_key:
        return None
    return MediaConfig(
        endpoint=os.environ.get(MEDIA_ENDPOINT_ENV) or DEFAULT_ENDPOINT,
        access_key=access_key,
        secret_key=secret_key,
        bucket=os.environ.get(MEDIA_BUCKET_ENV) or DEFAULT_BUCKET,
        region=os.environ.get(MEDIA_REGION_ENV) or DEFAULT_REGION,
    )


def media_enabled() -> bool:
    """メディア機能が env で有効化されているか (鍵 2 つの有無)。"""
    return load_media_config() is not None


class MediaError(RuntimeError):
    """取得画像の恒久的な不採用 (非画像・デコード不能・容量超過)。

    呼び出し側 (backfill) はこの例外を ``skipped`` として扱う。ネットワーク断・
    HTTP エラー等の再試行可能な失敗とは区別する。
    """


def compute_dhash(im: Image.Image) -> int:
    """9x8 グレースケールの横隣接差分による 64bit dHash (§1.6 と同一アルゴリズム)。

    ``convert("L").resize((9, 8))`` (Pillow 既定フィルタ) で縮小し、各行の
    隣接 8 画素の大小を 1bit (左 > 右) として左上→右下の順に詰める。戻り値は
    **64bit 符号なし整数** (0〜2^64-1)。DB 格納時のみ :func:`_signed64` で
    BIGINT の符号付き two's complement に変換する (FE は ``to_hex`` で 16 進化。
    XOR + popcount による距離計算は SQL 側 = ``bit_count(int8send(dhash # %s))``)。
    """
    small = im.convert("L").resize((9, 8))
    px = small.load()
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def quality_rank(width: int | None, height: int | None, size_bytes: int | None) -> tuple:
    """代表選定の品質順キー ``(width*height, size_bytes)`` (§2.7・大きいほど良い)。

    辞書順比較 (高解像度優先・同解像度は高ビットレート優先)。NULL は 0 扱い。
    """
    return ((width or 0) * (height or 0), int(size_bytes or 0))


def object_key_for(sha256: str, ext: str) -> str:
    """内容アドレスの original キー ``sha256/xx/yy/<sha>.<ext>`` (§1.3/§2.5)。"""
    return f"sha256/{sha256[:2]}/{sha256[2:4]}/{sha256}.{ext}"


def thumb_key_for(sha256: str) -> str:
    """内容アドレスのサムネイルキー ``derived/640/<sha>.webp`` (§2.5)。"""
    return f"derived/640/{sha256}.webp"


def _ext_for(pil_format: str) -> str:
    """Pillow フォーマット名 → キー拡張子 (未知は ``bin``)。"""
    return _EXT_BY_FORMAT.get((pil_format or "").upper(), "bin")


def _signed64(value: int) -> int:
    """64bit 符号なし値 → PG BIGINT 用の符号付き two's complement 表現。

    psycopg は Python int をそのまま送るため、2^63 以上は BIGINT に収まらない。
    ビット列は不変のまま符号付きへ写すことで、PG 側の ``#`` (XOR) と
    ``bit_count(int8send(...))`` が 64bit として正しく動く
    (``to_hex`` も 16 桁になる = FE の 16 進表現と一致)。
    """
    return value - (1 << 64) if value > _MASK64 // 2 else value


def _sql_hamming(column: str = "dhash") -> str:
    """PG 側の 64bit ハミング距離式 (``column`` は bigint 列)。

    PG 17 の ``bit_count`` は bit/bytea のみで bigint 版が無いため、
    ``int8send`` で 8 バイト big-endian の bytea に写してから数える
    (17.7 実測で XOR 距離 0/64 を確認済み)。設計書 §2.5 の
    ``bit_count(dhash # %s)`` と同義。
    """
    return f"bit_count(int8send({column} # %s))"


def _probe_image(data: bytes) -> tuple[str, int, int, int]:
    """Pillow で画像を検証し ``(format, width, height, dhash)`` を返す (§2.5)。

    ``Image.open`` → ``verify()`` (破損・非画像の検出) → 再 open で本体を読む
    (verify 後はファイル位置が進むため Pillow の定石どおり 2 度開く)。
    非画像・デコード不能・DecompressionBomb は :class:`MediaError`。
    """
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
            dhash = compute_dhash(im)
    except MediaError:
        raise
    except Exception as e:  # UnidentifiedImageError / DecompressionBombError / 破損
        raise MediaError(f"not a decodable image: {e}") from e
    if not fmt:
        raise MediaError("image format could not be determined")
    return fmt, width, height, dhash


def _make_thumb(data: bytes) -> bytes | None:
    """長辺 :data:`THUMB_SIZE` の WebP サムネイルを生成する (失敗時 None)。

    元が 640px 以下なら拡大しない (:meth:`PIL.Image.Image.thumbnail`)。
    生成不能でも本体保存は継続する (thumb_key=NULL・§2.5)。
    """
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            im.thumbnail(THUMB_SIZE)
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=THUMB_QUALITY)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 - サムネ生成失敗で本体を落とさない
        print(f"  ! thumbnail generation failed: {e}", file=sys.stderr)
        return None


def _is_missing_bucket(exc: Exception) -> bool:
    """``head_bucket`` の「バケット無し」判定 (boto3 ClientError 互換の duck typing)。

    HEAD 応答は本文を持たないため botocore は Code="404" を返す。仮実装
    (テストの fake S3) も ``response["Error"]["Code"]`` だけ用意すれば判定できる。
    """
    resp = getattr(exc, "response", None) or {}
    code = str((resp.get("Error") or {}).get("Code") or "")
    return code in {"404", "NoSuchBucket", "NotFound"}


class MediaStore:
    """rustfs (S3 互換) への実体保存 + media_assets/media_variants のクラスタ管理。

    - ``s3`` は DI 点 (boto3 クライアント互換)。None なら初回利用時に boto3 で
      生成する — rustfs は virtual-host 非対応のため path-style が必須 (§1.4)。
    - バケットは初回 PUT 時に :meth:`ensure_bucket` が冪等作成する
      (head_bucket → 無ければ create_bucket・プロセス内 1 回キャッシュ = shiquge 流)。
      policy は private のまま (§2.5)。
    """

    def __init__(self, config: MediaConfig, s3: Any = None):
        self._config = config
        self._s3 = s3
        self._bucket_ready = False

    def _client(self) -> Any:
        """boto3 クライアントを遅延生成する (``s3`` DI 時はそのまま返す)。"""
        if self._s3 is None:
            import boto3
            from botocore.config import Config as BotoConfig

            self._s3 = boto3.client(
                "s3",
                endpoint_url=self._config.endpoint,
                aws_access_key_id=self._config.access_key,
                aws_secret_access_key=self._config.secret_key,
                region_name=self._config.region,
                config=BotoConfig(s3={"addressing_style": "path"}),
            )
        return self._s3

    def ensure_bucket(self) -> None:
        """バケット存在を保証する (プロセス内 1 回キャッシュの冪等実行)。

        作成・確認以外の失敗 (権限・接続) は例外をそのまま伝播させる。
        """
        if self._bucket_ready:
            return
        s3 = self._client()
        try:
            s3.head_bucket(Bucket=self._config.bucket)
        except Exception as e:
            if not _is_missing_bucket(e):
                raise
            s3.create_bucket(Bucket=self._config.bucket)
        self._bucket_ready = True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        """immutable キャッシュヘッダ付きで 1 オブジェクトを PUT する。"""
        self.ensure_bucket()
        self._client().put_object(
            Bucket=self._config.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=_IMMUTABLE_CACHE_CONTROL,
        )

    def get_object(self, key: str) -> Any:
        """boto3 ``get_object`` の生レスポンスを返す (Body はストリーム・§2.8)。

        読み取り経路では bucket 事前確認を行わない (HeadBucket 権限を要求せず、
        配信 API を最小権限で動かせるようにする)。
        """
        return self._client().get_object(Bucket=self._config.bucket, Key=key)

    def _put_thumb(self, sha256: str, data: bytes) -> str | None:
        """サムネイルを生成・PUT してキーを返す (失敗時 None で本体保存は継続)。"""
        try:
            thumb = _make_thumb(data)
            if thumb is None:
                return None
            key = thumb_key_for(sha256)
            self.put_object(key, thumb, "image/webp")
            return key
        except Exception as e:  # noqa: BLE001 - PUT 失敗でも thumb_key=NULL で続行
            print(f"  ! thumbnail put failed sha256={sha256}: {e}", file=sys.stderr)
            return None

    def store_image(
        self, conn, data: bytes, mime: str, source_url: str | None
    ) -> tuple[int, str]:
        """クラスタ代表ストアの本体。(media_assets.id = クラスタ ID, kind) を返す。

        ``kind`` は ``stored`` (新規クラスタ) / ``linked`` (sha256 既知) /
        ``variant`` (代表に劣る近重複) / ``replaced`` (代表差し替え)。

        手順 (§2.5):

        1. sha256 → ``media_assets`` / ``media_variants`` の既知 sha なら
           その ``media_id`` を ``linked`` で返す (アップロードなし)
        2. 容量 (:data:`MAX_IMAGE_BYTES`) → Content-Type → Pillow 検証 (verify →
           再 open) → 寸法・dHash。不正は :class:`MediaError`
        3. dHash 近重複候補を ``bit_count(int8send(dhash # %s)) <= DHASH_THRESHOLD``
           で検索し、hamming 距離最小 (同点は品質良) の 1 件をクラスタ代表とする
        4. 候補なし → original + サムネを PUT し ``media_assets`` に INSERT
        5. 候補あり → 品質が上回る場合のみ代表を差し替え (旧代表 sha は
           ``media_variants`` へ退避)、劣る場合は実体を破棄して
           ``media_variants`` に記録だけ行う

        **commit は行わない** (呼び出し側 = backfill が 1 行ごとに確定する)。
        """
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaError(f"image too large: {len(data)} bytes > {MAX_IMAGE_BYTES}")
        sha256 = hashlib.sha256(data).hexdigest()

        # 1. 既知クラスタへの短絡 (バイト完全一致・アップロードなし)
        row = conn.execute(
            "SELECT id FROM media_assets WHERE sha256 = %s", (sha256,)
        ).fetchone()
        if row is not None:
            return int(row["id"]), "linked"
        row = conn.execute(
            "SELECT media_id FROM media_variants WHERE sha256 = %s", (sha256,)
        ).fetchone()
        if row is not None:
            return int(row["media_id"]), "linked"

        # 2. 検証 (Pillow) と dHash。非画像 mime はデコード前に弾く。
        mime_type = (mime or "").split(";")[0].strip().lower()
        if mime_type and not mime_type.startswith("image/"):
            raise MediaError(f"non-image content-type: {mime_type!r}")
        fmt, width, height, dhash = _probe_image(data)
        if not mime_type:  # Content-Type 欠落時は Pillow 判定で補完
            mime_type = Image.MIME.get(fmt, "application/octet-stream")

        # 3. 近重複候補: 距離最小 → 品質良 (width*height, size_bytes) → id で安定化。
        #    sha256 は代表差し替え時に旧代表を media_variants へ退避するため取得する。
        sql_dhash = _signed64(dhash)
        best = conn.execute(
            f"""
            SELECT id, sha256, width, height, size_bytes
            FROM media_assets
            WHERE dhash IS NOT NULL AND {_sql_hamming()} <= %s
            ORDER BY {_sql_hamming()},
                     COALESCE(width, 0) * COALESCE(height, 0) DESC,
                     COALESCE(size_bytes, 0) DESC, id
            LIMIT 1
            """,
            (sql_dhash, DHASH_THRESHOLD, sql_dhash),
        ).fetchone()

        if best is None:
            # 4. 新クラスタ: original + サムネを PUT して代表行を作る。
            object_key = object_key_for(sha256, _ext_for(fmt))
            self.put_object(object_key, data, mime_type)
            thumb_key = self._put_thumb(sha256, data)
            media_id = int(
                conn.execute(
                    """
                    INSERT INTO media_assets
                        (sha256, dhash, bucket, object_key, thumb_key, mime_type,
                         size_bytes, width, height)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        sha256,
                        sql_dhash,
                        self._config.bucket,
                        object_key,
                        thumb_key,
                        mime_type,
                        len(data),
                        width,
                        height,
                    ),
                ).fetchone()["id"]
            )
            return media_id, "stored"

        # 5. 近重複クラスタあり (§2.7): 品質が上回る時だけ代表を差し替える。
        best_id = int(best["id"])
        new_rank = quality_rank(width, height, len(data))
        best_rank = quality_rank(best["width"], best["height"], best["size_bytes"])
        if new_rank > best_rank:
            object_key = object_key_for(sha256, _ext_for(fmt))
            self.put_object(object_key, data, mime_type)
            thumb_key = self._put_thumb(sha256, data)
            conn.execute(
                """
                UPDATE media_assets SET
                    sha256 = %s, dhash = %s, object_key = %s, thumb_key = %s,
                    mime_type = %s, size_bytes = %s, width = %s, height = %s,
                    stored_at = now()
                WHERE id = %s
                """,
                (
                    sha256,
                    sql_dhash,
                    object_key,
                    thumb_key,
                    mime_type,
                    len(data),
                    width,
                    height,
                    best_id,
                ),
            )
            # 旧代表の実体はどこからも参照されなくなる (GC 対象) が、sha256 短絡用の
            # 既知バリアントとして残す。旧 source_url は保持していないため NULL。
            conn.execute(
                """
                INSERT INTO media_variants
                    (sha256, media_id, width, height, size_bytes, source_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING
                """,
                (
                    best["sha256"],
                    best_id,
                    best["width"],
                    best["height"],
                    best["size_bytes"],
                    None,
                ),
            )
            return best_id, "replaced"

        # 代表に劣る近重複: バイトは破棄し、証跡と再取得短絡用の 1 行だけ残す。
        conn.execute(
            """
            INSERT INTO media_variants
                (sha256, media_id, width, height, size_bytes, source_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            """,
            (sha256, best_id, width, height, len(data), source_url),
        )
        return best_id, "variant"


def _default_fetcher() -> Callable[[str], tuple[bytes, str]]:
    """内蔵 fetcher: 共有 UA + per-host 0.3s 直列遅延の単純 GET (§2.6)。

    - ``sources.base.DEFAULT_HEADERS`` を付与 (ソースアダプタと同一 UA)。
    - ``stream`` 読みで :data:`MAX_IMAGE_BYTES` 超過の時点で打ち切り
      :class:`MediaError` (巨大レスポンスをメモリに載せ切らない)。
    - 単一スレッド直列前提で「同一 host への前回リクエスト開始から 0.3s」を守る。
      戻り値は ``(data, Content-Type)``。
    """
    # sources.* の重い依存 (bs4 等) をモジュール import に持ち込まない遅延 import。
    from sources.base import DEFAULT_HEADERS

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    last_start: dict[str, float] = {}

    def fetch(url: str) -> tuple[bytes, str]:
        host = (urlparse(url).hostname or "").lower()
        prev = last_start.get(host)
        if prev is not None:
            wait = _HOST_DELAY_S - (time.monotonic() - prev)
            if wait > 0:
                time.sleep(wait)
        last_start[host] = time.monotonic()

        with session.get(url, timeout=_FETCH_TIMEOUT_S, stream=True) as resp:
            resp.raise_for_status()
            content_type = (
                (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            )
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=_FETCH_CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise MediaError(f"image exceeds {MAX_IMAGE_BYTES} bytes: {url}")
                chunks.append(chunk)
        return b"".join(chunks), content_type

    return fetch


def _record_failure(conn, image_id: int, status: str, message: str) -> None:
    """1 行の失敗を property_images に記録する (中断トランザクションを回復してから)。"""
    conn.rollback()
    conn.execute(
        "UPDATE property_images SET fetch_status = %s, fetch_error = %s WHERE id = %s",
        (status, message[:_ERROR_MAX], image_id),
    )
    conn.commit()


def backfill_media(
    limit: int | None = None,
    dry_run: bool = False,
    source: str | None = None,
    retry_failed: bool = False,
    progress_every: int = 500,
    fetcher: Callable[[str], tuple[bytes, str]] | None = None,
    url_resolver: Callable[[str | None, str], str] | None = None,
    store: MediaStore | None = None,
) -> dict:
    """``property_images`` の未取得行を media へ取り込むバッチ本体 (§2.6)。

    対象行 (``p.is_active DESC, pi.id`` 順・``limit`` は先頭 N 件):

    ``pi.fetch_status = ANY(%s)`` — statuses = ``('pending',)``、``retry_failed``
    指定時は ``('pending', 'failed')``。``source`` 指定時は ``p.source_site`` で絞る。

    1 行ごとに 正規化 (:func:`sources.media_urls.resolve_media_url`) → 取得 →
    :meth:`MediaStore.store_image` → ``property_images`` を
    ``fetch_status='stored' / media_id / fetched_at=now() / fetch_error=NULL``
    へ更新して commit する。1 行の失敗で全体を止めず、:class:`MediaError` は
    ``skipped``、ネットワーク/HTTP 等のその他の失敗は ``failed`` として
    ``fetch_error`` を残す (backfill-embeddings と同じ慣習)。

    引数:

    - ``fetcher``: ``(url) -> (data, mime)`` の DI 点。None なら内蔵 fetcher
      (requests + 共有 UA + per-host 0.3s 遅延) を使う。
    - ``url_resolver``: ``(source_site, image_url) -> 取得 URL`` の DI 点。None なら
      ``sources.media_urls.resolve_media_url`` を遅延 import して使う (SSOT)。
    - ``store``: :class:`MediaStore` の DI 点 (テスト用・既定は config から生成)。
    - ``dry_run``: 対象件数を数えるだけで取得・保存・更新を行わない
      (``processed`` に対象件数を入れて返す)。

    ``load_media_config()`` が None (鍵未設定) の場合は ``disabled=True`` の
    stats を返して何もしない (§2.3 graceful degradation)。

    戻り値::

        {"processed": 試行行数, "stored"/"linked"/"variant"/"replaced": store_image の kind 別件数,
         "skipped": 恒久失敗, "failed": 一時失敗, "dry_run": bool, "disabled": bool}
    """
    stats = {
        "processed": 0,
        "stored": 0,
        "linked": 0,
        "variant": 0,
        "replaced": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": bool(dry_run),
        "disabled": False,
    }
    config = load_media_config()
    if config is None:
        stats["disabled"] = True
        return stats

    if url_resolver is None:
        from sources.media_urls import resolve_media_url  # サイト別知識の SSOT

        url_resolver = resolve_media_url
    if store is None and not dry_run:
        store = MediaStore(config)
    if fetcher is None and not dry_run:
        fetcher = _default_fetcher()

    statuses = ("pending", "failed") if retry_failed else ("pending",)
    sql = (
        "SELECT pi.id, pi.image_url, p.source_site "
        "FROM property_images pi JOIN properties p ON p.id = pi.property_id "
        "WHERE pi.fetch_status = ANY(%s)"
    )
    params: list[Any] = [list(statuses)]
    if source:
        sql += " AND p.source_site = %s"
        params.append(source)
    sql += " ORDER BY p.is_active DESC, pi.id"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))

    with open_connection() as conn:
        rows = list(conn.execute(sql, params))
        if dry_run:
            stats["processed"] = len(rows)
            return stats

        processed = 0
        for row in rows:
            processed += 1
            image_id = int(row["id"])
            try:
                url = url_resolver(row["source_site"], row["image_url"])
                data, mime = fetcher(url)
                # source_url は取得時正規化前の property_images.image_url (DB 正本)。
                media_id, kind = store.store_image(conn, data, mime, row["image_url"])
                conn.execute(
                    "UPDATE property_images SET media_id = %s, fetch_status = 'stored',"
                    " fetched_at = now(), fetch_error = NULL WHERE id = %s",
                    (media_id, image_id),
                )
                conn.commit()  # 1 行ごとに確定 (部分進捗を残す)
                stats[kind] += 1
            except MediaError as e:
                _record_failure(conn, image_id, "skipped", str(e))
                stats["skipped"] += 1
            except Exception as e:  # noqa: BLE001 - 1 行の失敗で全体を止めない
                _record_failure(conn, image_id, "failed", str(e))
                stats["failed"] += 1
                print(f"  ! media fetch failed image_id={image_id}: {e}", file=sys.stderr)
            if progress_every and processed % progress_every == 0:
                print(f"  ... {processed}/{len(rows)} images processed")

        stats["processed"] = processed
    return stats
