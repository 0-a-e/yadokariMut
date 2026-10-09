#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物件識別子の解決: properties.id と external_id の衝突で誤解決しないこと.

本番では external_id が全て数字で properties.id と値域が重なるため、
単一の `WHERE id = ? OR external_id = ?` では意図した物件に決まらない
(旧実装は約半数を別物件に解決していた)。解決ロジックを共通化した上で、
id 優先・決定性・曖昧さの明示を検証する。
"""

import unittest

from fastapi.testclient import TestClient

from helpers import ScopedDb, make_draft
from store import api_queries
from store.repository import Repository

from web_server import app


class PropertyLookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("lookup")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        # 衝突を作る: id=1 の物件の external_id を "2" にして、id=2 より小さくする。
        # 旧実装(テーブルスキャン=rowid 昇順)は key="2" で id=1 を返していた。
        cls.b_id = repo.upsert_property(  # id=1
            make_draft(
                "2",
                source_site="unionmonthly",
                title="unionmonthly 2",
                detail_url="https://example.test/unionmonthly/2/",
            )
        )
        cls.a_id = repo.upsert_property(  # id=2
            make_draft(
                "999",
                source_site="bratto",
                title="bratto 999",
                detail_url="https://example.test/bratto/999/",
            )
        )
        cls.c_id = repo.upsert_property(  # id=3 (同一 external_id 別ソース)
            make_draft(
                "2",
                source_site="fakesite",
                title="fakesite 2",
                detail_url="https://example.test/fakesite/2/",
            )
        )
        # 存在する id と衝突しない外部 id を 2 ソースに持たせる(曖昧解決の検証用)
        cls.d_id = repo.upsert_property(
            make_draft(
                "5555",
                source_site="fakesite",
                title="fakesite 5555",
                detail_url="https://example.test/fakesite/5555/",
            )
        )
        cls.e_id = repo.upsert_property(
            make_draft(
                "5555",
                source_site="bratto",
                title="bratto 5555",
                detail_url="https://example.test/bratto/5555/",
            )
        )

        cls.client = TestClient(app)

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
                "SELECT property_id FROM property_shortlists ORDER BY property_id"
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
            rows = conn.execute("SELECT property_id FROM property_shortlists").fetchall()
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
