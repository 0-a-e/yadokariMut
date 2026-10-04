#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NDJSON ストリーム (/api/geojson/stream) とジェネレータ化した検索レイヤのテスト."""

import json
import os
import shutil
import tempfile
import unittest


from fastapi.testclient import TestClient

from domain.models import (
    Campaign,
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
)
from store import api_queries
from store.repository import Repository

# web_server はインポート時にエンドポイントを定義するのみ。
# DB パスは setUpClass で env 経由で差し替える(api_queries / Repository は呼び出し毎に env を読む)
from web_server import app


def _draft(
    external_id: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    rent_current_yen: int = 5000,
) -> PropertyDraft:
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
                rent_current_yen=rent_current_yen,
            )
        ],
    )


class TestGeojsonStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        cls._tmpdir = tempfile.mkdtemp(prefix="yadm-stream-")
        os.environ["YADOKARIMUT_V2_DB_PATH"] = os.path.join(cls._tmpdir, "test_v2.db")

        repo = Repository()
        repo.init_db()
        # 座標あり 3 件(うち 1 件は access/image/feature/campaign を持つ) + 座標なし 1 件
        # rich だけ最安値にして ORDER BY (catalog_rent_per_day_yen ASC) の 1 位を固定する
        # (同額だとソート順が不定になり limit=1 の対象が変わるため)
        rich = _draft("stream-rich", lat=35.66, lng=139.70, rent_current_yen=4000)
        rich.accesses = [
            PropertyAccess(line_name="JR", station_name="渋谷駅", walk_minutes=5, sort_order=0),
            PropertyAccess(line_name="東急", station_name="神泉駅", walk_minutes=8, sort_order=1),
        ]
        rich.images = [
            PropertyImage(image_url="https://img.test/rich-b.jpg", image_type="gallery", sort_order=1),
            PropertyImage(image_url="https://img.test/rich-a.jpg", image_type="thumbnail", sort_order=0),
        ]
        rich.features = [
            PropertyFeature(feature_name="オートロック", feature_category="building"),
            PropertyFeature(feature_name="エアコン", feature_category="room"),
        ]
        rich.campaigns = [Campaign(campaign_type="discount", title="初回割引")]
        rich.point_text = "POINT 日当たり良好"
        cls.id_rich = repo.upsert_property(rich)

        plain = _draft("stream-plain", lat=35.67, lng=139.71)
        plain.features = [PropertyFeature(feature_name="エアコン", feature_category="room")]
        cls.id_plain = repo.upsert_property(plain)

        cls.id_min = repo.upsert_property(_draft("stream-min", lat=35.68, lng=139.72))
        cls.id_nocoords = repo.upsert_property(_draft("stream-nocoords"))

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls._old_db is None:
            os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
        else:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = cls._old_db
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _stream_msgs(self, query: str = "") -> list[dict]:
        """ストリームを NDJSON 行ごとに読んで dict のリストで返す."""
        with self.client.stream("GET", f"/api/geojson/stream{query}") as r:
            self.assertEqual(r.status_code, 200)
            return [json.loads(line) for line in r.iter_lines() if line]

    def test_stream_meta_feature_end(self):
        """先頭 meta 行 → feature 行×N → 末尾 end 行の順で流れ、件数が一致する."""
        msgs = self._stream_msgs()
        self.assertEqual(msgs[0]["type"], "meta")
        self.assertGreaterEqual(msgs[0]["total"], 3)
        self.assertEqual(msgs[-1]["type"], "end")

        feature_msgs = [m for m in msgs if m["type"] == "feature"]
        self.assertGreaterEqual(len(feature_msgs), 3)
        self.assertEqual(msgs[-1]["count"], len(feature_msgs))
        for m in feature_msgs:
            self.assertEqual(m["feature"]["type"], "Feature")
            props = m["feature"]["properties"]
            self.assertIn("id", props)
            self.assertIn("room_id", props)

        # 移設した 1 物件分の組み立て(access/features/images/campaigns/point_text)
        rich = next(
            m["feature"] for m in feature_msgs if m["feature"]["properties"]["id"] == self.id_rich
        )
        props = rich["properties"]
        self.assertEqual(props["room_id"], "stream-rich")
        # 市区町村は相場比較(市区町村×間取りのピア比較)用に payload へ含める
        self.assertEqual(props["municipality"], "渋谷区")
        self.assertIn("オートロック", props["feature_summary"])
        self.assertIn("渋谷駅", props["station_summary"])
        self.assertEqual(
            props["images"],
            ["https://img.test/rich-a.jpg", "https://img.test/rich-b.jpg"],
        )
        self.assertEqual(len(props["campaigns"]), 1)
        # clean_point_text が「POINT 」見出しを落とす
        self.assertEqual(props["point_text"], "日当たり良好")
        self.assertEqual(
            rich["geometry"],
            {"type": "Point", "coordinates": [139.70, 35.66]},
        )

    def test_stream_parity_with_bulk(self):
        """ストリームの feature が一括 /api/geojson と完全一致する."""
        msgs = self._stream_msgs()
        stream_features = [m["feature"] for m in msgs if m["type"] == "feature"]
        stream_ids = {f["properties"]["id"] for f in stream_features}

        bulk = self.client.get("/api/geojson?limit=10")
        self.assertEqual(bulk.status_code, 200)
        bulk_features = bulk.json()["features"]
        bulk_ids = {f["properties"]["id"] for f in bulk_features}

        self.assertEqual(stream_ids, bulk_ids)
        # 順序・内容とも一致する
        self.assertEqual(stream_features, bulk_features)

    def test_stream_excludes_no_coords(self):
        """座標なしの物件はストリームに含まれない."""
        msgs = self._stream_msgs()
        room_ids = [m["feature"]["properties"]["room_id"] for m in msgs if m["type"] == "feature"]
        self.assertNotIn("stream-nocoords", room_ids)
        self.assertIn("stream-rich", room_ids)

    def test_stream_limit(self):
        """limit=1 で feature 行がちょうど 1 行、end.count も 1."""
        msgs = self._stream_msgs("?limit=1")
        feature_msgs = [m for m in msgs if m["type"] == "feature"]
        self.assertEqual(len(feature_msgs), 1)
        self.assertEqual(msgs[-1]["type"], "end")
        self.assertEqual(msgs[-1]["count"], 1)

    def test_stream_headers(self):
        """NDJSON 用の content-type とバッファリング無効ヘッダを返す."""
        with self.client.stream("GET", "/api/geojson/stream") as r:
            self.assertIn("x-ndjson", r.headers.get("content-type", ""))
            self.assertEqual(r.headers.get("x-accel-buffering"), "no")
            self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_iter_search_equivalence(self):
        """iter_search_properties が search_properties と順序・内容とも一致する."""
        for p in [{}, {"limit": 2}, {"required_features": ["オートロック"]}]:
            with self.subTest(params=p):
                self.assertEqual(
                    list(api_queries.iter_search_properties(p)),
                    api_queries.search_properties(p),
                )

    def test_count_properties(self):
        """count_properties が可視物件数(座標なしを含む)を返す."""
        # 全件 active + shortlist 無しでシードしたため 4 件
        self.assertEqual(api_queries.count_properties({}), 4)
        # required_features は post filter のため COUNT には反映されない
        self.assertEqual(api_queries.count_properties({"required_features": ["オートロック"]}), 4)
        rows = api_queries.search_properties({"required_features": ["オートロック"]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.id_rich)


if __name__ == "__main__":
    unittest.main()
