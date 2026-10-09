"""MCP ツールの建物単位構造化テスト (docs/building-aggregation-design.md §6.2).

mcp_server のツール関数を直接呼ぶ形式 (@mcp.tool() は関数を無変更で返すため
サーバ起動なしで検証できる)。DB は ScopedDb で隔離し、Repository.upsert_property
のスクレイプ時 building 割当フック (assign_building) 経由で建物を作る。
"""

import json
import os
import tempfile
import unittest

from helpers import ScopedDb, make_tokyo_draft

from domain.models import PropertyFeature
from store.repository import Repository


def _room(eid, *, rent=5000, address="東京都渋谷区神宮前1-2-3", lat=35.65, lng=139.7,
          features=(), is_active=True, title=None):
    draft = make_tokyo_draft(
        eid,
        source_site="unionmonthly",
        address=address,
        lat=lat,
        lng=lng,
        rent_current_yen=rent,
        is_active=is_active,
        title=title,
        features=list(features),
    )
    # 30日総額 (min_plan_total) は管理費日額が確定しないと None になるため
    # テストでは 0 円を明示する (決定 11 の None 透過仕様)
    draft.price_plans[0].management_yen = 0
    return draft


class TestMcpBuildingSearch(unittest.TestCase):
    def setUp(self):
        self.db = ScopedDb("test.mcp.buildings")
        self.repo = Repository()
        # 建物 A(神宮前1-2-3): 2 部屋(101 = エレベーター+オートロック / 102 = 無設備)
        self.repo.upsert_property(
            _room("101", rent=6000, features=[
                PropertyFeature("エレベーター", "elevator"),
                PropertyFeature("オートロック", "auto_lock"),
            ], title="ユニオンマンスリーA 101")
        )
        self.repo.upsert_property(_room("102", rent=5000, title="ユニオンマンスリーA 102"))
        # 建物 B(神宮前9-9-9): 1 部屋(901 = 安い)
        self.repo.upsert_property(
            _room("901", rent=4000, address="東京都渋谷区神宮前9-9-9",
                  features=[PropertyFeature("エレベーター", "elevator")],
                  title="ユニオンマンスリーB 901")
        )

    def tearDown(self):
        self.db.close()

    def _building_a(self):
        from mcp_server import search_properties

        res = search_properties(limit=10)
        return next(b for b in res["results"] if b["name"] == "ユニオンマンスリーA")

    def test_search_returns_building_structure_and_meta(self):
        from mcp_server import search_properties

        res = search_properties()
        meta = res["meta"]
        self.assertEqual(meta["count"], 2)
        self.assertEqual(meta["total_buildings"], 2)
        self.assertEqual(meta["total_units"], 3)
        self.assertTrue(meta["candidates_exhausted"])

        buildings = res["results"]
        # 1 要素 = 1 建物 (kind="building")・並び順は最安日額: B(4000) → A(5000)
        self.assertEqual([b["kind"] for b in buildings], ["building", "building"])
        self.assertEqual(buildings[0]["units"][0]["external_id"], "901")
        a = buildings[1]
        self.assertEqual(a["name"], "ユニオンマンスリーA")
        self.assertEqual(a["units_count"], 2)
        self.assertEqual(a["active_units_count"], 2)
        self.assertEqual(a["min_daily_rent"], 5000)
        self.assertEqual(a["max_daily_rent"], 6000)
        self.assertEqual(a["min_plan_total"], 5000 * 30)
        # units は部屋 dict 一式 (建物フィールドの is_active も区分)
        self.assertEqual(
            sorted(u["external_id"] for u in a["units"]), ["101", "102"]
        )
        for key in ("rent_plans", "feature_categories", "is_active", "detail_url"):
            self.assertIn(key, a["units"][0])
        self.assertTrue(a["is_active"])

    def test_search_limit_counts_buildings(self):
        from mcp_server import search_properties

        res = search_properties(limit=1)
        # limit の単位は建物数 (部屋数ではない)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["meta"]["count"], 1)
        # total_buildings は limit 適用前のヒット建物総数
        self.assertEqual(res["meta"]["total_buildings"], 2)
        self.assertFalse(res["meta"]["candidates_exhausted"])

    def test_required_features_matching_units_only(self):
        from mcp_server import search_properties

        res = search_properties(required_features=["auto_lock"])
        # 建物ヒット意味論: 条件部屋を持つ建物のみ・候補単位は建物
        self.assertEqual(res["meta"]["total_buildings"], 1)
        self.assertEqual(len(res["results"]), 1)
        b = res["results"][0]
        self.assertEqual(b["name"], "ユニオンマンスリーA")
        # units="matching": 条件一致部屋のみ (無設備の 102 は載らない)
        self.assertEqual([u["external_id"] for u in b["units"]], ["101"])
        self.assertEqual(res["meta"]["total_units"], 1)
        # required_resolved は維持
        resolved = res["meta"]["required_resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["codes"], ["auto_lock"])
        self.assertFalse(resolved[0]["is_fallback"])

    def test_get_building_detail_with_units_and_missing_error(self):
        from mcp_server import get_building_detail

        bid = self._building_a()["id"]
        detail = get_building_detail(bid)
        self.assertEqual(detail["kind"], "building")
        self.assertEqual(detail["name"], "ユニオンマンスリーA")
        self.assertEqual(detail["units_count"], 2)
        # units は可視部屋全件 (掲載終了部屋を含む区別は is_active)
        self.assertEqual(
            sorted(u["external_id"] for u in detail["units"]), ["101", "102"]
        )
        self.assertIn("min_daily_rent", detail)
        self.assertIn("building_names", detail)

        missing = get_building_detail(999999)
        self.assertEqual(missing["status"], "error")
        self.assertIn("999999", missing["message"])

    def test_get_property_detail_building_section(self):
        from mcp_server import get_property_detail

        a = self._building_a()
        unit = a["units"][0]
        detail = get_property_detail(str(unit["id"]))
        self.assertEqual(detail["building"]["building_id"], a["id"])
        self.assertEqual(detail["building"]["name"], a["name"])
        self.assertEqual(detail["building"]["address"], a["address"])

        # 未割当 (住所欠損 → building_id NULL) 部屋は building=null
        orphan_id = self.repo.upsert_property(_room("orphan", address=None))
        orphan = get_property_detail(str(orphan_id))
        self.assertIsNone(orphan["building"])

    def test_export_geojson_building_features(self):
        from mcp_server import export_geojson

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "map.geojson")
            r = export_geojson(file_path=out)
            self.assertEqual(r["status"], "success")
            # feature_count の単位は建物数
            self.assertEqual(r["feature_count"], 2)
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["features"]), 2)
            first = data["features"][0]["properties"]
            self.assertEqual(first["kind"], "building")
            self.assertEqual(first["name"], "ユニオンマンスリーB")
            # export は units="all" 相当: 建物の可視部屋全て
            self.assertEqual(len(first["units"]), 1)
            self.assertEqual(first["units"][0]["external_id"], "901")

    def test_kml_carries_building_name_via_get_properties_by_ids(self):
        from store import api_queries
        from store.kml_export import build_kml_document

        a = self._building_a()
        unit = a["units"][0]
        rows = api_queries.get_properties_by_ids([unit["id"]])
        self.assertEqual(rows[0]["building_id"], a["id"])
        self.assertEqual(rows[0]["building_name"], "ユニオンマンスリーA")

        kml = build_kml_document(rows)
        self.assertIn('name="building_id"', kml)
        self.assertIn('name="building_name"', kml)
        self.assertIn("ユニオンマンスリーA", kml)

    def test_kml_omits_building_rows_for_unassigned_room(self):
        """未割当 (building_id NULL) 部屋の Placemark に建物 Data 行を出さない."""
        from store import api_queries
        from store.kml_export import build_kml_document

        orphan_id = self.repo.upsert_property(_room("kml-orphan", address=None))
        rows = api_queries.get_properties_by_ids([orphan_id])
        self.assertIsNone(rows[0]["building_id"])
        self.assertIsNone(rows[0]["building_name"])
        kml = build_kml_document(rows)
        self.assertNotIn('name="building_id"', kml)
        self.assertNotIn('name="building_name"', kml)


if __name__ == "__main__":
    unittest.main()
