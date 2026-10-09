#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store.media (rustfs クラスタ代表ストア・docs/media-storage-rustfs-plan.md §2.5) のテスト.

- MediaConfig/load_media_config: 鍵未設定 → 無効 (graceful degradation §2.3)・
  endpoint/bucket/region の既定値と env 上書き
- compute_dhash: 9x8 横隣接差分の 64bit 表現 (縮小不変・左右反転で全ビット反転)
- quality_rank / object_key_for / thumb_key_for / _ext_for: 代表選定キーと
  内容アドレスキー規約 (§1.3/§2.5)
- MediaStore (fake S3 + 隔離 DB): stored/linked/variant/replaced の 4 経路・
  非画像/容量超過/非画像 Content-Type の MediaError・サムネ WebP 生成・
  ensure_bucket の 404→create とプロセス内キャッシュ・get_object の生レスポンス
- backfill_media (fake fetcher + 実 ``sources.media_urls.resolve_media_url``):
  statuses 更新・img_out.php の unwrap 取得・1 行失敗で止まらない
  (MediaError→skipped / ネットワーク→failed)・retry_failed/source/limit/dry_run・
  鍵未設定時の disabled

S3 は FakeS3 (dict 記録)、DB は tmp_v2_db (conftest: テンプレート複製の隔離 DB)。
実 rustfs・実サイトへの通信は行わない。
"""

from __future__ import annotations

import hashlib
import io

import pytest
import requests
from PIL import Image, ImageOps

import store.media as media
from domain.models import PropertyImage
from helpers import make_draft
from sources.media_urls import resolve_media_url
from store.media import (
    DHASH_THRESHOLD,
    MAX_IMAGE_BYTES,
    MediaConfig,
    MediaError,
    MediaStore,
    backfill_media,
    compute_dhash,
    load_media_config,
    media_enabled,
    object_key_for,
    quality_rank,
    thumb_key_for,
)
from store.pg import open_connection

# --- 合成画像ヘルパ (決定論的・実フィクスチャ不要) -------------------------


def _gradient_bytes(width: int, height: int, *, invert: bool = False, quality: int = 90) -> bytes:
    """左黒→右白の線形グラデーション JPEG (``invert=True`` で左白→右黒)。

    大域的な単調勾配なので dHash は全ビットが同一になり、縮小・再エンコードで
    距離 0・左右反転で距離 64 という M0 実測 (§1.6) の性質を合成画像で再現する。
    """
    # linear_gradient は縦方向 (上黒→下白) なので 90 度回して横勾配にする。
    base = Image.linear_gradient("L").transpose(Image.Transpose.ROTATE_90)
    im = base.resize((width, height), Image.Resampling.BILINEAR)
    if invert:
        im = ImageOps.invert(im)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _dhash_of(data: bytes) -> int:
    with Image.open(io.BytesIO(data)) as im:
        return compute_dhash(im)


def _distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _config(**overrides) -> MediaConfig:
    values = {
        "endpoint": "http://rustfs.test:9000",
        "access_key": "ak",
        "secret_key": "sk",
        "bucket": "yadokari-media",
        "region": "us-east-1",
    }
    values.update(overrides)
    return MediaConfig(**values)


class _FakeClientError(Exception):
    """botocore ClientError 互換 (``response["Error"]["Code"]`` だけ参照される)。"""

    def __init__(self, code, status=404):
        super().__init__(str(code))
        self.response = {"Error": {"Code": str(code)}, "ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3:
    """boto3 S3 クライアントの最小フェイク (put を dict に記録・head 呼び数を数える)。"""

    def __init__(self, bucket_exists: bool = True):
        self.objects: dict[str, dict] = {}
        self.head_calls = 0
        self.created: list[str] = []
        self._bucket_exists = bucket_exists

    def head_bucket(self, Bucket):
        self.head_calls += 1
        if not self._bucket_exists:
            raise _FakeClientError("404")
        return {}

    def create_bucket(self, Bucket):
        self.created.append(Bucket)
        self._bucket_exists = True
        return {}

    def put_object(self, Bucket, Key, Body, ContentType=None, CacheControl=None):
        self.objects[Key] = {
            "Bucket": Bucket,
            "Body": Body,
            "ContentType": ContentType,
            "CacheControl": CacheControl,
        }

    def get_object(self, Bucket, Key):
        entry = self.objects[Key]
        return {
            "Body": io.BytesIO(entry["Body"]),
            "ContentType": entry["ContentType"],
            "ContentLength": len(entry["Body"]),
            "ETag": '"%s"' % hashlib.sha256(entry["Body"]).hexdigest(),
        }


# --- env / 定数 -----------------------------------------------------------


class TestMediaConfigEnv:
    def test_disabled_without_credentials(self, monkeypatch):
        monkeypatch.delenv(media.MEDIA_ACCESS_KEY_ENV, raising=False)
        monkeypatch.delenv(media.MEDIA_SECRET_ENV, raising=False)

        assert load_media_config() is None
        assert media_enabled() is False

    def test_defaults_and_env_overrides(self, monkeypatch):
        monkeypatch.setenv(media.MEDIA_ACCESS_KEY_ENV, "ak")
        monkeypatch.setenv(media.MEDIA_SECRET_ENV, "sk")
        for name in (media.MEDIA_ENDPOINT_ENV, media.MEDIA_BUCKET_ENV, media.MEDIA_REGION_ENV):
            monkeypatch.delenv(name, raising=False)

        assert load_media_config() == MediaConfig(
            "http://rustfs:9000", "ak", "sk", "yadokari-media", "us-east-1"
        )
        assert media_enabled() is True

        monkeypatch.setenv(media.MEDIA_ENDPOINT_ENV, "http://127.0.0.1:19000")
        monkeypatch.setenv(media.MEDIA_BUCKET_ENV, "other-bucket")
        monkeypatch.setenv(media.MEDIA_REGION_ENV, "ap-northeast-1")
        assert load_media_config() == MediaConfig(
            "http://127.0.0.1:19000", "ak", "sk", "other-bucket", "ap-northeast-1"
        )


class TestComputeDhash:
    def test_half_resize_is_distance_zero(self):
        big = _gradient_bytes(800, 600)
        half = _gradient_bytes(400, 300)

        assert _distance(_dhash_of(big), _dhash_of(half)) == 0

    def test_left_black_right_white_vs_inverse(self):
        normal = _dhash_of(_gradient_bytes(256, 128))
        inverted = _dhash_of(_gradient_bytes(256, 128, invert=True))

        assert _distance(normal, inverted) == 64  # 全ビット反転 = 最大距離
        assert _distance(normal, inverted) > DHASH_THRESHOLD

    def test_bit_convention_on_9x8_ramp(self):
        # 「左 > 右」を 1 とする規約: 増加 = 全 0 / 減少 = 全 1
        increasing = Image.new("L", (9, 8))
        decreasing = Image.new("L", (9, 8))
        for y in range(8):
            for x in range(9):
                increasing.putpixel((x, y), x * 30)
                decreasing.putpixel((x, y), 240 - x * 30)

        assert compute_dhash(increasing) == 0
        assert compute_dhash(decreasing) == (1 << 64) - 1
        assert 0 <= compute_dhash(increasing) < (1 << 64)


class TestKeysAndRank:
    def test_object_and_thumb_key_format(self):
        sha = "0123456789abcdef" * 4

        assert object_key_for(sha, "jpg") == f"sha256/01/23/{sha}.jpg"
        assert thumb_key_for(sha) == f"derived/640/{sha}.webp"

    def test_quality_rank_pixels_then_bytes(self):
        # 高解像度優先・同解像度は高ビットレート優先 (§2.7)
        assert quality_rank(800, 600, 10) > quality_rank(400, 300, 10**9)
        assert quality_rank(400, 300, 200) > quality_rank(400, 300, 100)
        assert quality_rank(None, None, None) == (0, 0)

    def test_ext_for_known_formats(self):
        assert [
            media._ext_for(f) for f in ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "")
        ] == ["jpg", "png", "webp", "gif", "bmp", "bin", "bin"]


# --- MediaStore (fake S3 + 隔離 DB) ---------------------------------------


class TestMediaStoreBucket:
    def test_ensure_bucket_creates_when_missing_and_caches(self):
        s3 = FakeS3(bucket_exists=False)
        store = MediaStore(_config(), s3=s3)

        store.ensure_bucket()
        store.ensure_bucket()

        assert s3.created == ["yadokari-media"]
        assert s3.head_calls == 1  # 2 回目はプロセス内キャッシュで head しない

    def test_put_object_sets_immutable_cache_control(self):
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        store.put_object("k/1.bin", b"abc", "application/octet-stream")

        entry = s3.objects["k/1.bin"]
        assert entry["Bucket"] == "yadokari-media"
        assert entry["Body"] == b"abc"
        assert entry["ContentType"] == "application/octet-stream"
        assert entry["CacheControl"] == "public, max-age=31536000, immutable"
        assert s3.head_calls == 1  # PUT ごとに head しない

    def test_get_object_returns_raw_response(self):
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)
        store.put_object("k/1.bin", b"abc", "image/jpeg")

        resp = store.get_object("k/1.bin")

        assert resp["Body"].read() == b"abc"
        assert resp["ContentType"] == "image/jpeg"
        assert s3.head_calls == 1  # 読み取り経路は bucket 事前確認しない


class TestStoreImage:
    def test_new_cluster_puts_original_and_thumb(self, tmp_v2_db):
        data = _gradient_bytes(800, 600)
        sha = _sha(data)
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            media_id, kind = store.store_image(conn, data, "image/jpeg", "https://example.test/a.jpg")
            conn.commit()
            assert kind == "stored"
            row = conn.execute("SELECT * FROM media_assets").fetchone()

        assert int(row["id"]) == media_id
        assert row["sha256"] == sha
        assert row["dhash"] & ((1 << 64) - 1) == _dhash_of(data)
        assert row["bucket"] == "yadokari-media"
        assert row["object_key"] == object_key_for(sha, "jpg")
        assert row["thumb_key"] == thumb_key_for(sha)
        assert row["mime_type"] == "image/jpeg"
        assert row["size_bytes"] == len(data)
        assert (row["width"], row["height"]) == (800, 600)

        # original + サムネの 2 キーだけを PUT
        assert set(s3.objects) == {object_key_for(sha, "jpg"), thumb_key_for(sha)}
        original = s3.objects[object_key_for(sha, "jpg")]
        assert original["Body"] == data
        assert original["ContentType"] == "image/jpeg"
        assert original["CacheControl"] == "public, max-age=31536000, immutable"
        thumb = s3.objects[thumb_key_for(sha)]
        assert thumb["ContentType"] == "image/webp"
        with Image.open(io.BytesIO(thumb["Body"])) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= 640
        assert s3.head_calls == 1  # ensure_bucket はキャッシュされ 1 回だけ

        resp = store.get_object(thumb_key_for(sha))
        assert resp["Body"].read() == thumb["Body"]

    def test_known_sha_links_without_upload(self, tmp_v2_db):
        data = _gradient_bytes(800, 600)
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            first_id, first_kind = store.store_image(
                conn, data, "image/jpeg", "https://example.test/a.jpg"
            )
            conn.commit()
            puts = len(s3.objects)

            again_id, again_kind = store.store_image(
                conn, data, "image/jpeg", "https://example.test/b.jpg"
            )
            conn.commit()

            assert first_kind == "stored"
            assert (again_id, again_kind) == (first_id, "linked")
            assert len(s3.objects) == puts  # アップロードなし
            assert int(conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]) == 1
            assert int(conn.execute("SELECT COUNT(*) FROM media_variants").fetchone()[0]) == 0

    def test_near_duplicate_worse_is_recorded_as_variant(self, tmp_v2_db):
        big = _gradient_bytes(800, 600, quality=90)
        small = _gradient_bytes(400, 300, quality=80)
        url_small = "https://example.test/small.jpg"
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            rep_id, kind = store.store_image(
                conn, big, "image/jpeg", "https://example.test/big.jpg"
            )
            conn.commit()
            puts = len(s3.objects)

            var_id, var_kind = store.store_image(conn, small, "image/jpeg", url_small)
            conn.commit()

            assert kind == "stored"
            assert (var_id, var_kind) == (rep_id, "variant")
            assert len(s3.objects) == puts  # 劣るバリアントの実体は保存しない
            assert int(conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]) == 1

            vrow = conn.execute(
                "SELECT * FROM media_variants WHERE sha256 = %s", (_sha(small),)
            ).fetchone()
            assert int(vrow["media_id"]) == rep_id
            assert (vrow["width"], vrow["height"]) == (400, 300)
            assert vrow["size_bytes"] == len(small)
            assert vrow["source_url"] == url_small

            # media_variants の sha も再投入は linked (実体なしのまま)
            again = store.store_image(conn, small, "image/jpeg", url_small)
            assert again == (rep_id, "linked")
            assert len(s3.objects) == puts

    def test_near_duplicate_better_replaces_representative(self, tmp_v2_db):
        small = _gradient_bytes(400, 300, quality=80)
        big = _gradient_bytes(800, 600, quality=90)
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            rep_id, kind = store.store_image(
                conn, small, "image/jpeg", "https://example.test/small.jpg"
            )
            conn.commit()

            new_id, new_kind = store.store_image(
                conn, big, "image/jpeg", "https://example.test/big.jpg"
            )
            conn.commit()

            assert kind == "stored"
            assert (new_id, new_kind) == (rep_id, "replaced")
            # クラスタ行は不変のまま代表 (sha256/object_key/寸法) が差し替わる
            row = conn.execute("SELECT * FROM media_assets WHERE id = %s", (rep_id,)).fetchone()
            assert row["sha256"] == _sha(big)
            assert row["dhash"] & ((1 << 64) - 1) == _dhash_of(big)
            assert row["object_key"] == object_key_for(_sha(big), "jpg")
            assert row["thumb_key"] == thumb_key_for(_sha(big))
            assert row["size_bytes"] == len(big)
            assert (row["width"], row["height"]) == (800, 600)
            assert int(conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]) == 1

            # 旧代表は実体なしの既知バリアントとして退避 (旧寸法/size 付き)
            old = conn.execute(
                "SELECT * FROM media_variants WHERE sha256 = %s", (_sha(small),)
            ).fetchone()
            assert int(old["media_id"]) == rep_id
            assert (old["width"], old["height"]) == (400, 300)
            assert old["size_bytes"] == len(small)
            assert old["source_url"] is None

        assert len(s3.objects) == 4  # 旧代表 original+thumb / 新代表 original+thumb

    def test_distinct_photo_is_a_new_cluster(self, tmp_v2_db):
        normal = _gradient_bytes(800, 600)
        inverted = _gradient_bytes(800, 600, invert=True)
        assert _distance(_dhash_of(normal), _dhash_of(inverted)) == 64 > DHASH_THRESHOLD
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            id1, kind1 = store.store_image(conn, normal, "image/jpeg", None)
            conn.commit()
            id2, kind2 = store.store_image(conn, inverted, "image/jpeg", None)
            conn.commit()

            assert (kind1, kind2) == ("stored", "stored")
            assert id1 != id2
            assert int(conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]) == 2
            # 2^63 以上 (反転 = 全ビット 1) は符号付き BIGINT として格納される
            inv_row = conn.execute(
                "SELECT dhash FROM media_assets WHERE id = %s", (id2,)
            ).fetchone()
            assert inv_row["dhash"] < 0
            assert inv_row["dhash"] & ((1 << 64) - 1) == _dhash_of(inverted)

    def test_non_image_oversize_and_bad_mime_raise_media_error(self, tmp_v2_db):
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        with open_connection() as conn:
            with pytest.raises(MediaError):  # 非画像バイト (Pillow デコード不能)
                store.store_image(conn, b"not an image at all", "image/jpeg", None)
            with pytest.raises(MediaError):  # 非画像 Content-Type
                store.store_image(conn, _gradient_bytes(64, 48), "text/html", None)
            with pytest.raises(MediaError):  # 容量超過 (Pillow の前に打ち切り)
                store.store_image(conn, b"\x00" * (MAX_IMAGE_BYTES + 1), "image/jpeg", None)
            conn.rollback()

            assert int(conn.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0]) == 0

        assert s3.objects == {}


# --- backfill_media -------------------------------------------------------

_GRADIENT_800 = _gradient_bytes(800, 600)


def _enable_media_env(monkeypatch) -> None:
    """env 経由でメディア機能を有効化する (endpoint/bucket/region は既定値)。"""
    monkeypatch.setenv(media.MEDIA_ACCESS_KEY_ENV, "test-ak")
    monkeypatch.setenv(media.MEDIA_SECRET_ENV, "test-sk")
    for name in (media.MEDIA_ENDPOINT_ENV, media.MEDIA_BUCKET_ENV, media.MEDIA_REGION_ENV):
        monkeypatch.delenv(name, raising=False)


class _FakeFetcher:
    """``url -> (bytes, mime)`` を返す fetcher フェイク (呼び出し URL を記録)。"""

    def __init__(self, payloads=None, error_urls=()):
        self.payloads = dict(payloads or {})
        self.error_urls = set(error_urls)
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        if url in self.error_urls:
            raise requests.ConnectionError(f"boom: {url}")
        return self.payloads[url]


def _upsert_with_images(source_site: str, images: list, *, is_active: bool = True) -> int:
    """make_draft + Repository.upsert_property で物件と property_images 行を作る。"""
    from store.repository import Repository

    draft = make_draft(
        f"{source_site}-{hashlib.sha1(str(images).encode()).hexdigest()[:8]}",
        source_site=source_site,
        is_active=is_active,
        images=images,
    )
    return int(Repository().upsert_property(draft))


def _image_rows() -> dict:
    with open_connection() as conn:
        return {
            r["image_url"]: dict(r)
            for r in conn.execute("SELECT * FROM property_images ORDER BY id")
        }


class TestBackfillMedia:
    def test_stores_links_and_unwraps_and_updates_status(self, tmp_v2_db, monkeypatch):
        _enable_media_env(monkeypatch)
        data_a = _gradient_bytes(800, 600, quality=90)
        # unwrap 先の実体は別画像 (左右反転 = dHash 距離 64 → 別クラスタ)
        data_b = _gradient_bytes(400, 300, invert=True)
        url_a1 = "https://example.test/a1.jpg"
        url_a2 = "https://example.test/a2.jpg"
        inner = "http://unionmonthly-img.jp/img/room/1/r1.jpg"
        wrapper = f"https://www.unionmonthly.jp/img_out.php?img_data={inner}"

        _upsert_with_images(
            "fakesite", [PropertyImage(image_url=url_a1), PropertyImage(image_url=url_a2)]
        )
        _upsert_with_images("unionmonthly", [PropertyImage(image_url=wrapper)], is_active=False)

        fetcher = _FakeFetcher(
            {
                url_a1: (data_a, "image/jpeg"),
                url_a2: (data_a, "image/jpeg"),  # 同一バイト → sha256 短絡 (linked)
                inner: (data_b, "image/jpeg"),  # img_out.php は unwrap した実体URLで取得
            }
        )
        s3 = FakeS3()
        stats = backfill_media(
            fetcher=fetcher, url_resolver=resolve_media_url, store=MediaStore(_config(), s3=s3)
        )

        assert stats == {
            "processed": 3,
            "stored": 2,
            "linked": 1,
            "variant": 0,
            "replaced": 0,
            "skipped": 0,
            "failed": 0,
            "dry_run": False,
            "disabled": False,
        }
        # 取得は正規化後の実体URLのみ (ラッパーURLは fetch されない)
        assert fetcher.urls == [url_a1, url_a2, inner]

        rows = _image_rows()
        assert set(rows) == {url_a1, url_a2, wrapper}
        assert all(r["fetch_status"] == "stored" for r in rows.values())
        assert all(r["media_id"] is not None for r in rows.values())
        assert all(r["fetched_at"] is not None for r in rows.values())
        assert all(r["fetch_error"] is None for r in rows.values())
        # 同一バイトの 2 枚は同一クラスタ・unwrap 先は別クラスタ
        assert rows[url_a1]["media_id"] == rows[url_a2]["media_id"]
        assert rows[wrapper]["media_id"] != rows[url_a1]["media_id"]
        assert len(s3.objects) == 4  # original 2 + thumb 2

    def test_media_error_skipped_network_error_failed_without_stopping(self, tmp_v2_db, monkeypatch):
        _enable_media_env(monkeypatch)
        url_bad = "https://example.test/bad.jpg"
        url_net = "https://example.test/net.jpg"
        url_ok = "https://example.test/ok.jpg"
        _upsert_with_images(
            "fakesite",
            [
                PropertyImage(image_url=url_bad),
                PropertyImage(image_url=url_net),
                PropertyImage(image_url=url_ok),
            ],
        )
        fetcher = _FakeFetcher(
            {url_bad: (b"<html>not an image</html>", "text/html"), url_ok: (_GRADIENT_800, "image/jpeg")},
            error_urls={url_net},
        )
        stats = backfill_media(
            fetcher=fetcher,
            url_resolver=resolve_media_url,
            store=MediaStore(_config(), s3=FakeS3()),
        )

        assert (stats["processed"], stats["stored"], stats["skipped"], stats["failed"]) == (
            3,
            1,
            1,
            1,
        )
        rows = _image_rows()
        assert rows[url_bad]["fetch_status"] == "skipped"  # MediaError
        assert rows[url_bad]["fetch_error"]
        assert rows[url_bad]["media_id"] is None
        assert rows[url_net]["fetch_status"] == "failed"  # ネットワーク例外
        assert "boom" in rows[url_net]["fetch_error"]
        assert len(rows[url_net]["fetch_error"]) <= 200
        assert rows[url_ok]["fetch_status"] == "stored"  # 1 行失敗でも後続は処理される

    def test_source_filter_and_retry_failed(self, tmp_v2_db, monkeypatch):
        _enable_media_env(monkeypatch)
        keep_url = "https://example.test/keep.jpg"
        url_new = "https://example.test/retry-new.jpg"
        url_failed = "https://example.test/retry-failed.jpg"
        _upsert_with_images("fakesite", [PropertyImage(image_url=keep_url)])
        _upsert_with_images(
            "unionmonthly",
            [PropertyImage(image_url=url_new), PropertyImage(image_url=url_failed)],
        )
        with open_connection() as conn:
            conn.execute(
                "UPDATE property_images SET fetch_status = 'failed', fetch_error = 'old error'"
                " WHERE image_url = %s",
                (url_failed,),
            )
            conn.commit()

        data = _gradient_bytes(400, 300, quality=80)
        data_distinct = _gradient_bytes(800, 600, invert=True)  # 距離 64 = 別クラスタ
        fetcher = _FakeFetcher(
            {url_new: (data, "image/jpeg"), url_failed: (data_distinct, "image/jpeg")}
        )
        stats = backfill_media(
            source="unionmonthly",
            retry_failed=True,
            fetcher=fetcher,
            url_resolver=resolve_media_url,
            store=MediaStore(_config(), s3=FakeS3()),
        )

        assert stats["processed"] == 2
        assert stats["stored"] == 2
        rows = _image_rows()
        assert rows[keep_url]["fetch_status"] == "pending"  # source 外は未処理
        assert rows[url_new]["fetch_status"] == "stored"
        assert rows[url_failed]["fetch_status"] == "stored"
        assert rows[url_failed]["fetch_error"] is None  # 再試行成功でクリア

    def test_limit_and_dry_run(self, tmp_v2_db, monkeypatch):
        _enable_media_env(monkeypatch)
        urls = [f"https://example.test/img-{i}.jpg" for i in range(3)]
        _upsert_with_images("fakesite", [PropertyImage(image_url=u) for u in urls])
        data = _gradient_bytes(400, 300, quality=80)
        fetcher = _FakeFetcher({u: (data, "image/jpeg") for u in urls})
        s3 = FakeS3()
        store = MediaStore(_config(), s3=s3)

        # dry_run: 対象件数のみ・取得/保存/更新なし
        dry = backfill_media(dry_run=True, fetcher=fetcher, store=store)
        assert dry["dry_run"] is True
        assert dry["processed"] == 3
        assert dry["stored"] == 0
        assert fetcher.urls == []
        assert s3.objects == {}
        assert all(r["fetch_status"] == "pending" for r in _image_rows().values())

        # limit: is_active DESC, id 順の先頭 N 件だけ処理
        res = backfill_media(limit=2, fetcher=fetcher, store=store)
        assert res["processed"] == 2
        statuses = [r["fetch_status"] for r in _image_rows().values()]
        assert statuses == ["stored", "stored", "pending"]

    def test_disabled_without_credentials_does_nothing(self, tmp_v2_db, monkeypatch):
        monkeypatch.delenv(media.MEDIA_ACCESS_KEY_ENV, raising=False)
        monkeypatch.delenv(media.MEDIA_SECRET_ENV, raising=False)
        url = "https://example.test/disabled.jpg"
        _upsert_with_images("fakesite", [PropertyImage(image_url=url)])
        fetcher = _FakeFetcher({url: (_GRADIENT_800, "image/jpeg")})

        stats = backfill_media(fetcher=fetcher)

        assert stats["disabled"] is True
        assert stats["processed"] == 0
        assert fetcher.urls == []
        assert _image_rows()[url]["fetch_status"] == "pending"
