#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web API の v2 データレイヤ疎通テスト (tmp v2 DB + Repository シード)."""

import unittest


from fastapi.testclient import TestClient

from helpers import ScopedDb, make_tokyo_draft
from store import api_queries
from store.repository import Repository

# web_server はインポート時にエンドポイントを定義するのみ。
# DB パスは setUpClass で env 経由で差し替える(api_queries / Repository は呼び出し毎に env を読む)
from web_server import app


class TestWebAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("webapi")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        # 座標あり 1 件(geojson に出る) + 座標なし 1 件(詳細/ショートリスト用)
        cls.prop_with_coords = repo.upsert_property(
            make_tokyo_draft("api-coords", lat=35.66, lng=139.70)
        )
        cls.prop_no_coords = repo.upsert_property(make_tokyo_draft("api-nocoords"))

        cls.client = TestClient(app)

    def test_search_returns_seeded_property(self):
        rows = api_queries.search_properties({"limit": 10})
        ids = {r["external_id"] for r in rows}
        self.assertIn("api-coords", ids)
        self.assertIn("api-nocoords", ids)

    def test_geojson_api_removed(self):
        """B2-ε: 旧部屋単位 /api/geojson 系エンドポイントは廃止(404)."""
        self.assertEqual(self.client.get("/api/geojson?limit=5").status_code, 404)
        self.assertEqual(self.client.get("/map.geojson").status_code, 404)
        self.assertEqual(
            self.client.get("/api/geojson/stream").status_code, 404
        )

    def test_admin_status_api(self):
        """status は DB 統計を返し、data_layer フィールドは廃止済み."""
        response = self.client.get("/api/admin/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("db_stats", data)
        self.assertIn("task_status", data)
        self.assertIn("total_properties", data["db_stats"])
        self.assertGreaterEqual(data["db_stats"]["total_properties"], 1)
        self.assertNotIn("data_layer", data)

    def test_admin_sources_api(self):
        """sources はカタログを返し、data_layer フィールドは廃止済み."""
        response = self.client.get("/api/admin/sources")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("sources", data)
        self.assertIsInstance(data["sources"], list)
        self.assertNotIn("data_layer", data)

    def test_shortlist_update_api(self):
        """shortlist 更新が 200 で成功し、DB に反映される."""
        prop_id = self.prop_no_coords

        response = self.client.post(
            f"/api/properties/{prop_id}/shortlist",
            json={"status": "saved", "comment": "API Test Comment"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("shortlist_status"), "saved")

        # Verify in DB
        repo = Repository()
        conn = repo.connect()
        try:
            row = conn.execute(
                "SELECT status, comment FROM property_shortlists WHERE property_id = %s", (prop_id,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "saved")
            self.assertEqual(row["comment"], "API Test Comment")
        finally:
            conn.close()

        # Cleanup: reset shortlist
        response = self.client.post(
            f"/api/properties/{prop_id}/shortlist",
            json={"status": "none"},
        )
        self.assertEqual(response.status_code, 200)

    def test_shortlist_update_unknown_property_400(self):
        response = self.client.post(
            "/api/properties/999999/shortlist",
            json={"status": "saved"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
