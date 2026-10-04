#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物件識別子の解決: properties.id と external_id の衝突で誤解決しないこと.

本番では external_id が全て数字で properties.id と値域が重なるため、
単一の `WHERE id = ? OR external_id = ?` では意図した物件に決まらない
(旧実装は約半数を別物件に解決していた)。解決ロジックを共通化した上で、
id 優先・決定性・曖昧さの明示を検証する。
"""

import os
import shutil
import tempfile
import unittest


from fastapi.testclient import TestClient

from domain.models import PropertyDraft
from store import api_queries
from store.repository import Repository

from web_server import app


def _draft(source_site: str, external_id: str) -> PropertyDraft:
    return PropertyDraft(
        source_site=source_site,
        external_id=external_id,
        entity_type="room",
        title=f"{source_site} {external_id}",
        detail_url=f"https://example.test/{source_site}/{external_id}/",
        prefecture_name="東京都",
        prefecture_slug="tokyo",
        is_active=True,
    )


class PropertyLookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        cls._tmpdir = tempfile.mkdtemp(prefix="yadm-lookup-")
        os.environ["YADOKARIMUT_V2_DB_PATH"] = os.path.join(cls._tmpdir, "test_v2.db")

        repo = Repository()
        repo.init_db()
        # 衝突を作る: id=1 の物件の external_id を "2" にして、id=2 より小さくする。
        # 旧実装(テーブルスキャン=rowid 昇順)は key="2" で id=1 を返していた。
        cls.b_id = repo.upsert_property(_draft("unionmonthly", "2"))   # id=1
        cls.a_id = repo.upsert_property(_draft("bratto", "999"))       # id=2
        cls.c_id = repo.upsert_property(_draft("fakesite", "2"))       # id=3 (同一 external_id 別ソース)
        # 存在する id と衝突しない外部 id を 2 ソースに持たせる(曖昧解決の検証用)
        cls.d_id = repo.upsert_property(_draft("fakesite", "5555"))
        cls.e_id = repo.upsert_property(_draft("bratto", "5555"))

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls._old_db is None:
            os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
        else:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = cls._old_db
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ---- 解決ロジック ----

    def test_id_lookup_wins_over_colliding_external_id(self):
        """id 指定は external_id が衝突していても id の物件を返す(旧実装の主症状)."""
        detail = api_queries.get_property_detail(str(self.a_id))
        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], self.a_id)
        self.assertEqual(detail["source_site"], "bratto")

    def test_by_external_resolves_room_id(self):
        detail = api_queries.get_property_detail(
            "2", by="external", source="unionmonthly"
        )
        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], self.b_id)

    def test_by_external_without_source_is_ambiguous(self):
        """external_id は (source_site, external_id) でのみ一意。推測しない."""
        with self.assertRaises(api_queries.AmbiguousPropertyLookup):
            api_queries.get_property_detail("2", by="external")

    def test_by_id_does_not_fall_back_to_external(self):
        # "999" は bratto の external_id だが properties.id ではない
        self.assertIsNone(api_queries.get_property_detail("999", by="id"))

    def test_auto_falls_back_to_external_when_id_missing(self):
        detail = api_queries.get_property_detail("999")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], self.a_id)

    def test_auto_reports_ambiguity_for_shared_external_id(self):
        with self.assertRaises(api_queries.AmbiguousPropertyLookup):
            api_queries.get_property_detail("5555")

    def test_unknown_key_returns_none(self):
        self.assertIsNone(api_queries.get_property_detail("100000"))

    def test_invalid_by_raises(self):
        with self.assertRaises(ValueError):
            api_queries.get_property_detail("2", by="bogus")

    # ---- shortlist 書き込み ----

    def test_shortlist_updates_requested_id_only(self):
        res = api_queries.update_shortlist(str(self.a_id), "saved", "メモ")
        self.assertTrue(res["ok"])
        self.assertEqual(res["property_id"], self.a_id)

        conn = Repository().connect()
        try:
            saved = conn.execute(
                "SELECT property_id FROM shortlists ORDER BY property_id"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([r["property_id"] for r in saved], [self.a_id])

    def test_shortlist_unknown_property(self):
        res = api_queries.update_shortlist("100000", "saved")
        self.assertFalse(res["ok"])

    # ---- HTTP ----

    def test_api_detail_returns_requested_id(self):
        res = self.client.get(f"/api/properties/{self.a_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], self.a_id)

    def test_api_detail_by_external_with_source(self):
        res = self.client.get(
            f"/api/properties/{self.a_id}?by=external&source=unionmonthly"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["id"], self.b_id)

    def test_api_detail_by_id_does_not_fall_back(self):
        res = self.client.get("/api/properties/999?by=id")
        self.assertEqual(res.status_code, 404)

    def test_api_detail_ambiguous_returns_409(self):
        res = self.client.get("/api/properties/5555")
        self.assertEqual(res.status_code, 409)

    def test_api_detail_invalid_by_returns_422(self):
        res = self.client.get(f"/api/properties/{self.a_id}?by=bogus")
        self.assertEqual(res.status_code, 422)

    def test_api_shortlist_writes_requested_id(self):
        res = self.client.post(
            f"/api/properties/{self.a_id}/shortlist",
            json={"status": "saved", "comment": "http"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["property_id"], self.a_id)

        conn = Repository().connect()
        try:
            rows = conn.execute("SELECT property_id FROM shortlists").fetchall()
            self.assertEqual([r["property_id"] for r in rows], [self.a_id])
        finally:
            conn.close()

        # cleanup
        self.client.post(
            f"/api/properties/{self.a_id}/shortlist", json={"status": "none"}
        )

    def test_api_shortlist_ambiguous_returns_409(self):
        res = self.client.post(
            "/api/properties/5555/shortlist", json={"status": "saved"}
        )
        self.assertEqual(res.status_code, 409)


if __name__ == "__main__":
    unittest.main()
