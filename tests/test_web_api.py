#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web API の v2 データレイヤ疎通テスト (tmp v2 DB + Repository シード)."""

import os
import shutil
import tempfile
import unittest


from fastapi.testclient import TestClient

from domain.models import PricePlan, PropertyDraft
from store import api_queries
from store.repository import Repository

# web_server はインポート時にエンドポイントを定義するのみ。
# DB パスは setUpClass で env 経由で差し替える(api_queries / Repository は呼び出し毎に env を読む)
from web_server import app


def _draft(external_id: str, *, lat: float | None = None, lng: float | None = None) -> PropertyDraft:
    return PropertyDraft(
        source_site="fakesite",
        external_id=external_id,
        entity_type="room",
        title=f"物件 {external_id}",
        detail_url=f"https://example.test/{external_id}/",
        prefecture_name="東京都",
        prefecture_slug="tokyo",
        municipality="渋谷区",
        address="東京都渋谷区神宮前1-2-3",
        lat=lat,
        lng=lng,
        is_active=True,
        price_plans=[
            PricePlan(
                plan_key="short",
                plan_name="ショット",
                duration_min_days=30,
                duration_max_days=89,
                presentation_unit="per_day",
                rent_current_yen=5000,
            )
        ],
    )


class TestWebAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        cls._tmpdir = tempfile.mkdtemp(prefix="yadm-webapi-")
        os.environ["YADOKARIMUT_V2_DB_PATH"] = os.path.join(cls._tmpdir, "test_v2.db")

        repo = Repository()
        repo.init_db()
        # 座標あり 1 件(geojson に出る) + 座標なし 1 件(詳細/ショートリスト用)
        cls.prop_with_coords = repo.upsert_property(_draft("api-coords", lat=35.66, lng=139.70))
        cls.prop_no_coords = repo.upsert_property(_draft("api-nocoords"))

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls._old_db is None:
            os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
        else:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = cls._old_db
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_search_returns_seeded_property(self):
        rows = api_queries.search_properties({"limit": 10})
        ids = {r["external_id"] for r in rows}
        self.assertIn("api-coords", ids)
        self.assertIn("api-nocoords", ids)

    def test_geojson_api(self):
        """座標ありの物件が GeoJSON FeatureCollection として返る."""
        response = self.client.get("/api/geojson?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("type"), "FeatureCollection")
        features = data.get("features") or []
        self.assertGreaterEqual(len(features), 1)
        props = features[0].get("properties") or {}
        self.assertIn("prefecture_name", props)
        # 一括取得でも municipality(相場比較のピア比較用)を返す
        self.assertEqual(props["municipality"], "渋谷区")
        self.assertIn("room_id", props)

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
                "SELECT status, comment FROM shortlists WHERE property_id = ?", (prop_id,)
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
