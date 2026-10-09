"""natural_query 意味検索統合(queries.buildings)のテスト(PG移行 Phase 7b).

固定ベクトルを property_embeddings へ直接投入し、
- 意味距離の昇順ソート(建物代表 = 建物内条件一致部屋の距離最小値)
- embedding 未カバー物件の除外(全部屋未カバーの建物は非ヒット)
- natural_query 無指定時の従来順序(価格順)の無回帰
を検証する。クエリ embedding は store.embeddings.embed_query_cached を
モックする(実 API を呼ばない)。
"""

import unittest

import store.queries.buildings as buildings_mod
from helpers import ScopedDb, make_tokyo_draft

from domain.models import PropertyFeature
from store.embeddings import EMBEDDING_DIM, upsert_embedding
from store.pg import open_connection
from store.queries.buildings import count_buildings, search_buildings
from store.repository import Repository

# 意味空間の見立て: クエリ = [1.0]*3072。101 は同一方向(距離 0)、
# 901 は近い方向、102 は逆向き(距離最大付近)。
_VEC_SAME = [1.0] * EMBEDDING_DIM
_VEC_NEAR = [0.6] + [1.0] * (EMBEDDING_DIM - 1)
_VEC_OPP = [-1.0] * EMBEDDING_DIM


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
    draft.price_plans[0].management_yen = 0  # min_plan_total 確定用(test_buildings_query と同一)
    return draft


class TestSemanticSearch(unittest.TestCase):
    def setUp(self):
        self.db = ScopedDb("test.semantic.search")
        self.repo = Repository()
        # 建物 A(神宮前1-2-3): 101 / 102 — 建物 B(神宮前9-9-9): 901
        self.id_101 = self.repo.upsert_property(
            _room("101", rent=6000, features=[
                PropertyFeature("エレベーター", "elevator"),
            ], title="ユニオンマンスリーA 101")
        )
        self.id_102 = self.repo.upsert_property(_room("102", rent=5000, title="ユニオンマンスリーA 102"))
        self.id_901 = self.repo.upsert_property(
            _room("901", rent=4000, address="東京都渋谷区神宮前9-9-9")
        )
        with open_connection() as conn:
            upsert_embedding(conn, self.id_101, "テスト文 101", _VEC_SAME)
            upsert_embedding(conn, self.id_102, "テスト文 102", _VEC_OPP)
            upsert_embedding(conn, self.id_901, "テスト文 901", _VEC_NEAR)
            conn.commit()

        # クエリ embedding をモック(常に _VEC_SAME 方向へのクエリ)
        self._orig_embed = buildings_mod.embed_query_cached
        buildings_mod.embed_query_cached = lambda text: list(_VEC_SAME)

    def tearDown(self):
        buildings_mod.embed_query_cached = self._orig_embed
        self.db.close()

    def test_semantic_order_overrides_default(self):
        # 既定(価格順)は B(4000) → A(5000)。意味順は A(代表 101 距離 0)→ B(901 距離小)。
        # min_daily_rent で順序の反転を検証する(建物 B の代表名は名寄せ結果に依存しない)。
        results = search_buildings({"natural_query": "テスト", "limit": 10})
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "ユニオンマンスリーA")
        self.assertEqual(results[0]["min_daily_rent"], 5000)
        self.assertEqual(results[1]["min_daily_rent"], 4000)

    def test_uncovered_room_excluded_from_matching_units(self):
        # 102 は embedding 行を持つが _VEC_OPP。ここを削除すると未カバー扱い:
        with open_connection() as conn:
            conn.execute(
                "DELETE FROM property_embeddings WHERE property_id = %s", (self.id_102,)
            )
            conn.commit()
        matching = search_buildings(
            {"natural_query": "テスト", "limit": 10}, units="matching"
        )
        building_a = [b for b in matching if b["name"] == "ユニオンマンスリーA"][0]
        # 建物 A は 101 の coverage でヒットするが、units から未カバーの 102 は消える
        self.assertEqual([u["external_id"] for u in building_a["units"]], ["101"])

    def test_fully_uncovered_building_not_hit(self):
        with open_connection() as conn:
            conn.execute(
                "DELETE FROM property_embeddings WHERE property_id = %s", (self.id_901,)
            )
            conn.commit()
        results = search_buildings({"natural_query": "テスト", "limit": 10})
        names = [b["name"] for b in results]
        self.assertEqual(len(results), 1)
        self.assertEqual(names[0], "ユニオンマンスリーA")
        # count も同一意味論(iter と count の一致)
        self.assertEqual(count_buildings({"natural_query": "テスト"}), 1)

    def test_building_representative_is_min_distance_room(self):
        # 建物 A の代表距離 = min(101 距離 0, 102 距離 ~2)。102 が逆向きでも
        # 建物 A の代表は 101 になる(= A が先頭)。
        results = search_buildings({"natural_query": "テスト", "limit": 10})
        self.assertEqual(results[0]["name"], "ユニオンマンスリーA")

    def test_no_natural_query_keeps_default_order(self):
        # natural_query 無指定: 従来どおり最安日額順(B → A)・全建物ヒット
        results = search_buildings({"limit": 10})
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["min_daily_rent"], 4000)
        self.assertEqual(results[1]["min_daily_rent"], 5000)
        self.assertEqual(count_buildings({}), 2)


if __name__ == "__main__":
    unittest.main()
