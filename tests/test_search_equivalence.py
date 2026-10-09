#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""検索レイヤの iter/generator 一貫性テスト.

B2-ε で旧 /api/geojson 系エンドポイントは廃止され、ストリームは建物単位の
/api/buildings/geojson/stream(test_buildings_api.py)へ移行した。ここには
エンドポイント廃止後も残る検索レイヤ自体のテストのみを保持する。
"""

import unittest

from domain.feature_categories import lookup_feature_category
from domain.models import PropertyFeature
from helpers import ScopedDb, make_tokyo_draft
from store import api_queries
from store.repository import Repository


class TestSearchLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("search-equiv")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        rich = make_tokyo_draft("stream-rich", lat=35.66, lng=139.70, rent_current_yen=4000)
        rich.features = [
            PropertyFeature(
                feature_name="オートロック",
                category=lookup_feature_category("オートロック").code,
            ),
            PropertyFeature(
                feature_name="エアコン",
                category=lookup_feature_category("エアコン").code,
            ),
        ]
        cls.id_rich = repo.upsert_property(rich)
        repo.upsert_property(make_tokyo_draft("stream-plain", lat=35.67, lng=139.71))
        repo.upsert_property(make_tokyo_draft("stream-min", lat=35.68, lng=139.72))
        repo.upsert_property(make_tokyo_draft("stream-nocoords"))

    def test_iter_search_equivalence(self):
        """iter_search_properties が search_properties と順序・内容とも一致する."""
        for p in [{}, {"limit": 2}, {"required_features": ["オートロック"]}]:
            with self.subTest(params=p):
                self.assertEqual(
                    list(api_queries.iter_search_properties(p)),
                    api_queries.search_properties(p),
                )


if __name__ == "__main__":
    unittest.main()
