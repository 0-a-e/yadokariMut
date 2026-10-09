"""建物単位検索・組立(queries.buildings)のテスト.

docs/building-aggregation-design.md §6.1/§8 の契約(建物ヒット意味論・units の
載せ方・可視性・代表値)を固定する。
"""

import unittest

from helpers import ScopedDb, make_tokyo_draft

from domain.models import PropertyFeature
from store.queries.buildings import (
    building_geojson_feature,
    count_buildings,
    get_building_detail,
    iter_search_buildings,
    search_buildings,
)
from store.repository import Repository


def _room(eid, *, rent=5000, address="東京都渋谷区神宮前1-2-3", lat=35.65, lng=139.7,
          features=(), is_active=True, source_site="unionmonthly", title=None):
    draft = make_tokyo_draft(
        eid,
        source_site=source_site,
        address=address,
        lat=lat,
        lng=lng,
        rent_current_yen=rent,
        is_active=is_active,
        title=title,
        features=list(features),
    )
    # 30日総額(min_plan_total)は管理費日額が確定しないと None になるため
    # テストでは 0 円を明示する(決定 11 の None 透過仕様)
    draft.price_plans[0].management_yen = 0
    return draft


class TestBuildingSearch(unittest.TestCase):
    def setUp(self):
        self.db = ScopedDb("test.buildings.query")
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
                  features=[PropertyFeature("エレベーター", "elevator")])
        )

    def tearDown(self):
        self.db.close()

    def test_grouping_and_representatives(self):
        results = search_buildings({"limit": 10})
        self.assertEqual(len(results), 2)
        # 並び順: 最安日額の安い建物 B(4000) → A(5000)
        self.assertEqual(results[0]["units"][0]["external_id"], "901")
        building_a = results[1]
        self.assertEqual(building_a["kind"], "building")
        self.assertEqual(building_a["name"], "ユニオンマンスリーA")
        self.assertEqual(building_a["units_count"], 2)
        self.assertEqual(len(building_a["units"]), 2)
        self.assertEqual(building_a["min_daily_rent"], 5000)
        self.assertEqual(building_a["max_daily_rent"], 6000)
        self.assertEqual(building_a["min_plan_total"], 5000 * 30)
        # 建物レベル feature_categories = sub='building' 語彙の導出(elevator/auto_lock)
        self.assertIn("elevator", building_a["feature_categories"])
        self.assertIn("auto_lock", building_a["feature_categories"])
        # 建物 B のみの units に洗濯機系は無い(検証: 部屋 101/102 由来のcodeはA側)
        self.assertNotIn("auto_lock", results[0]["feature_categories"])
        self.assertEqual(count_buildings({}), 2)

    def test_required_features_building_semantics(self):
        # 「エレベーター」= 両建物がヒット(建物 A は 101 のみ保有でも建物単位で成立)
        results = search_buildings({"required_features": ["elevator"], "limit": 10})
        self.assertEqual(len(results), 2)
        self.assertEqual(count_buildings({"required_features": ["elevator"]}), 2)
        # units="matching": 条件を満たす部屋のみ載る(建物 A は 101 のみ)
        matching = search_buildings(
            {"required_features": ["auto_lock"], "limit": 10}, units="matching"
        )
        self.assertEqual(len(matching), 1)
        self.assertEqual([u["external_id"] for u in matching[0]["units"]], ["101"])
        # units="all"(既定): 建物の可視部屋全て
        all_units = search_buildings(
            {"required_features": ["auto_lock"], "limit": 10}, units="all"
        )
        self.assertEqual(
            sorted(u["external_id"] for u in all_units[0]["units"]), ["101", "102"]
        )
        self.assertEqual(count_buildings({"required_features": ["auto_lock"]}), 1)

    def test_limit_counts_buildings(self):
        self.assertEqual(len(search_buildings({"limit": 1})), 1)
        state = {}
        it = iter_search_buildings({"limit": 1}, state=state)
        results = list(it)
        self.assertEqual(len(results), 1)
        self.assertFalse(state["candidates_exhausted"])
        state2 = {}
        list(iter_search_buildings({"limit": 10}, state=state2))
        self.assertTrue(state2["candidates_exhausted"])

    def test_visibility_inactive_room(self):
        # 102 が非掲載(ショートリスト無し)→ units から除外、建物は 101 で存続
        self.repo.upsert_property(_room("102", rent=5000, is_active=False))
        results = search_buildings({"limit": 10})
        building_a = [b for b in results if b["name"] == "ユニオンマンスリーA"][0]
        self.assertEqual([u["external_id"] for u in building_a["units"]], ["101"])
        # 全部屋非掲載の建物 B は可視性を通過する部屋が無く出ない
        self.repo.upsert_property(
            _room("901", rent=4000, address="東京都渋谷区神宮前9-9-9", is_active=False)
        )
        results2 = search_buildings({"limit": 10})
        names = [b["name"] for b in results2]
        self.assertNotIn(None, names)  # B は非掲載で代表名 null 化される前に出ない

    def test_geojson_feature_and_detail(self):
        feature = None
        for b in iter_search_buildings({"limit": 10}):
            f = building_geojson_feature(b)
            if f is not None and f["properties"]["name"] == "ユニオンマンスリーA":
                feature = f
                break
        self.assertIsNotNone(feature)
        self.assertEqual(feature["geometry"]["coordinates"], [139.7, 35.65])
        self.assertEqual(feature["properties"]["kind"], "building")
        self.assertNotIn("lat", feature["properties"])

        detail = get_building_detail(1)
        self.assertIsNotNone(detail)
        self.assertIn("units", detail)
        self.assertIn("building_names", detail)


if __name__ == "__main__":
    unittest.main()
