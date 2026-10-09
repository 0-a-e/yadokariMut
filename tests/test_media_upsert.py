#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""property_images 差分同期アップサート (M1・docs/media-storage-rustfs-plan.md §2.4) のテスト.

Alembic 0006 は property_images に取得状態列(media_id / fetch_status /
fetch_error / fetched_at)を追加する。旧実装の DELETE→全件再INSERT では
再スクレイプのたびにこれらが消えるため、_upsert_property_conn を差分同期
(残存URLは行を温存・消失URLは DELETE・新規URLのみ INSERT)へ変更した。
本ファイルは行id・取得状態の温存、URL の増減、draft 内重複URLの畳み込み、
および 0006 のスキーマ(テーブル/列/索引/FK 挙動)を検証する。
"""

from __future__ import annotations

from datetime import datetime, timezone

from domain.models import PropertyImage
from helpers import make_draft
from store.pg import open_connection
from store.repository import Repository


# --- 共有ヘルパ -----------------------------------------------------------


def _images(*urls: str, image_type: str | None = "gallery") -> list[PropertyImage]:
    return [PropertyImage(image_url=u, image_type=image_type) for u in urls]


def _fetch_images(property_id: int) -> list[dict]:
    """property_images 行を id 順で取得(取得状態列を含む全列)。"""
    with open_connection() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, image_url, image_type, alt_text, sort_order, scraped_at,"
                " media_id, fetch_status, fetch_error, fetched_at"
                " FROM property_images WHERE property_id = %s ORDER BY id",
                (property_id,),
            )
        ]


def _exec(sql: str, params: tuple = ()) -> dict | None:
    """テストからの直 SQL(commit 付き)。RETURNING があれば 1 行返す。"""
    with open_connection() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone() if cur.description else None
        conn.commit()
        return dict(row) if row else None


def _insert_media_asset(sha256: str = "a" * 64) -> int:
    """FK 検証用の media_assets 行を 1 件作り id を返す。"""
    return int(
        _exec(
            "INSERT INTO media_assets (sha256, bucket, object_key, mime_type, size_bytes)"
            " VALUES (%s, 'test-bucket', %s, 'image/jpeg', 123) RETURNING id",
            (sha256, f"sha256/aa/{sha256}"),
        )["id"]
    )


def _set_fetch_state(image_id: int, media_id: int, status: str) -> None:
    """取得済み(stored)相当の状態を手動で作る(差分同期の温存検証用)。"""
    _exec(
        "UPDATE property_images SET media_id = %s, fetch_status = %s,"
        " fetched_at = now(), scraped_at = '2000-01-01T00:00:00+09:00' WHERE id = %s",
        (media_id, status, image_id),
    )


# --- 差分同期 -------------------------------------------------------------


class TestPropertyImageDiffSync:
    def test_initial_upsert_inserts_pending_rows(self, tmp_v2_db):
        pid = Repository().upsert_property(make_draft("img-init", images=_images("u1", "u2")))

        rows = _fetch_images(pid)
        assert [r["image_url"] for r in rows] == ["u1", "u2"]
        assert [r["fetch_status"] for r in rows] == ["pending", "pending"]
        assert [r["media_id"] for r in rows] == [None, None]
        assert [r["fetch_error"] for r in rows] == [None, None]
        assert [r["fetched_at"] for r in rows] == [None, None]
        assert [r["image_type"] for r in rows] == ["gallery", "gallery"]

    def test_reupsert_preserves_row_ids_and_fetch_state(self, tmp_v2_db):
        repo = Repository()
        draft = make_draft("img-re", images=_images("u1", "u2"))
        pid = repo.upsert_property(draft)
        before = _fetch_images(pid)

        media_id = _insert_media_asset()
        _set_fetch_state(before[0]["id"], media_id, "stored")
        _exec(
            "UPDATE property_images SET fetch_status = 'failed', fetch_error = 'boom'"
            " WHERE id = %s",
            (before[1]["id"],),
        )

        assert repo.upsert_property(draft) == pid

        after = _fetch_images(pid)
        # 行は DELETE→再INSERT されず、id がそのまま温存される
        assert [r["id"] for r in after] == [r["id"] for r in before]
        # media 取得状態は再スクレイプで消えない
        assert after[0]["media_id"] == media_id
        assert after[0]["fetch_status"] == "stored"
        assert after[0]["fetched_at"] is not None
        assert after[1]["media_id"] is None
        assert after[1]["fetch_status"] == "failed"
        assert after[1]["fetch_error"] == "boom"
        # scraped_at だけは再 upsert の now で更新される
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert after[0]["scraped_at"] > old
        assert after[1]["scraped_at"] > old

    def test_url_add_and_remove_syncs_rows(self, tmp_v2_db):
        repo = Repository()
        draft = make_draft("img-sync", images=_images("u1", "u2", "u3"))
        pid = repo.upsert_property(draft)
        before = {r["image_url"]: r for r in _fetch_images(pid)}

        media_id = _insert_media_asset()
        _set_fetch_state(before["u2"]["id"], media_id, "stored")

        draft.images = _images("u1", "u2", "u4")  # u3 除去・u4 追加
        repo.upsert_property(draft)

        after = {r["image_url"]: r for r in _fetch_images(pid)}
        assert set(after) == {"u1", "u2", "u4"}  # 消失URL(u3)の行だけ DELETE
        assert after["u2"]["id"] == before["u2"]["id"]  # 残存行は温存
        assert after["u2"]["media_id"] == media_id
        assert after["u2"]["fetch_status"] == "stored"
        assert after["u1"]["id"] == before["u1"]["id"]
        assert after["u1"]["media_id"] is None
        assert after["u4"]["fetch_status"] == "pending"  # 追加URLは pending
        assert after["u4"]["media_id"] is None

    def test_duplicate_urls_collapse_to_single_row(self, tmp_v2_db):
        repo = Repository()
        draft = make_draft(
            "img-dup",
            images=[
                PropertyImage(image_url="u1", image_type="thumbnail"),
                PropertyImage(image_url="u1", image_type="gallery"),
                PropertyImage(image_url="u2", sort_order=None),
            ],
        )
        pid = repo.upsert_property(draft)

        rows = _fetch_images(pid)
        assert [r["image_url"] for r in rows] == ["u1", "u2"]
        assert rows[0]["image_type"] == "thumbnail"  # 最初の出現を採用
        # sort_order=None の fallback は元 draft の index(従来挙動の維持)
        assert rows[1]["sort_order"] == 2

        repo.upsert_property(draft)  # 再 upsert でも増殖しない
        assert len(_fetch_images(pid)) == 2


# --- スキーマ (0006) -------------------------------------------------------


class TestMediaSchema:
    def test_tables_columns_indexes_and_default(self, tmp_v2_db):
        with open_connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                )
            }
            assert {"media_assets", "media_variants"} <= tables

            cols = {
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema='public' AND table_name='property_images'"
                )
            }
            assert {"media_id", "fetch_status", "fetch_error", "fetched_at"} <= cols

            default = conn.execute(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_name='property_images' AND column_name='fetch_status'"
            ).fetchone()[0]
            assert "'pending'" in default

            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT indexname FROM pg_indexes"
                    " WHERE tablename IN ('media_assets', 'media_variants')"
                )
            }
            assert {"ix_media_assets_object_key", "ix_media_variants_media"} <= indexes

    def test_media_fk_cascade_and_set_null(self, tmp_v2_db):
        repo = Repository()
        pid = repo.upsert_property(make_draft("img-fk", images=_images("u1")))
        image_id = _fetch_images(pid)[0]["id"]
        asset_id = _insert_media_asset()
        _exec("UPDATE property_images SET media_id = %s WHERE id = %s", (asset_id, image_id))
        _exec(
            "INSERT INTO media_variants (sha256, media_id) VALUES (%s, %s)",
            ("b" * 64, asset_id),
        )

        _exec("DELETE FROM media_assets WHERE id = %s", (asset_id,))

        with open_connection() as conn:
            # media_variants は ON DELETE CASCADE で消える
            assert conn.execute("SELECT COUNT(*) FROM media_variants").fetchone()[0] == 0
            # property_images.media_id は ON DELETE SET NULL で NULL に戻る
            assert (
                conn.execute(
                    "SELECT media_id FROM property_images WHERE id = %s", (image_id,)
                ).fetchone()[0]
                is None
            )
