#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""サイト別契約事務手数料: 実効値解決 (物件値 > サイト既定、不明は None)."""

from __future__ import annotations

import unittest


from helpers import ScopedDb, make_draft  # noqa: E402
from store import api_queries  # noqa: E402
from store.queries._common import resolve_contract_fee_yen  # noqa: E402
from store.repository import Repository  # noqa: E402
from store.source_catalog import (  # noqa: E402
    SOURCE_CATALOG,
    default_contract_fee_yen,
)


class CatalogContractFeeTest(unittest.TestCase):
    """SOURCE_CATALOG の手数料必須化 (新サイト追加時の書き忘れを検出)."""

    def test_every_catalog_entry_declares_fee(self):
        for entry in SOURCE_CATALOG:
            fee = entry.get("contract_fee_yen")
            self.assertIsInstance(
                fee,
                int,
                f"{entry.get('id')}: contract_fee_yen が未宣言(0円でも明示必須)",
            )
            self.assertGreaterEqual(fee, 0, f"{entry.get('id')}: 手数料は 0 円以上")

    def test_catalog_values(self):
        self.assertEqual(default_contract_fee_yen("bratto"), 5500)
        self.assertEqual(default_contract_fee_yen("unionmonthly"), 0)

    def test_unknown_or_missing_site_returns_none(self):
        self.assertIsNone(default_contract_fee_yen("fakesite"))
        self.assertIsNone(default_contract_fee_yen(None))


class ResolveContractFeeTest(unittest.TestCase):
    """resolve_contract_fee_yen の 2 層解決 + 算出不能は None."""

    def test_property_value_wins(self):
        self.assertEqual(
            resolve_contract_fee_yen(
                {"source_site": "bratto", "contract_fee_yen": 9900}
            ),
            9900,
        )
        # unionmonthly 既定が 0 でも物件値が優先
        self.assertEqual(
            resolve_contract_fee_yen(
                {"source_site": "unionmonthly", "contract_fee_yen": 3300}
            ),
            3300,
        )

    def test_site_default_when_property_value_missing(self):
        self.assertEqual(
            resolve_contract_fee_yen({"source_site": "bratto", "contract_fee_yen": None}),
            5500,
        )
        self.assertEqual(
            resolve_contract_fee_yen({"source_site": "unionmonthly", "contract_fee_yen": None}),
            0,
        )
        self.assertEqual(resolve_contract_fee_yen({"source_site": "bratto"}), 5500)

    def test_unknown_site_resolves_to_none(self):
        self.assertIsNone(
            resolve_contract_fee_yen({"source_site": "fakesite", "contract_fee_yen": None})
        )
        self.assertIsNone(resolve_contract_fee_yen({}))


class ApiEmissionTest(unittest.TestCase):
    """search / GeoJSON / 詳細 API が解決済み実効値(None 含む)を埋め込むこと."""

    def setUp(self):
        self._db = ScopedDb("fee")
        self.addCleanup(self._db.close)
        self.repo = Repository()
        conn = self.repo.connect()
        try:
            conn.execute("DELETE FROM property_shortlists")
            conn.execute("DELETE FROM properties")
            conn.commit()
        finally:
            conn.close()
        # bratto (サイト既定 5500) / unionmonthly (サイト既定 0) /
        # bratto 物件個別値あり (6600 が優先) / 未登録サイト (None = 算出不能)
        self.repo.upsert_property(
            make_draft("b1", source_site="bratto", lat=35.68, lng=139.77,
                       address="東京都渋谷区神宮前1-2-3")
        )
        self.repo.upsert_property(
            make_draft("u1", source_site="unionmonthly", lat=35.68, lng=139.77,
                       address="東京都渋谷区神宮前1-2-3")
        )
        self.repo.upsert_property(
            make_draft(
                "b2", source_site="bratto", lat=35.68, lng=139.77,
                contract_fee_yen=6600,
                address="東京都渋谷区神宮前1-2-3",
            )
        )
        self.repo.upsert_property(
            make_draft("x1", source_site="fakesite", lat=35.68, lng=139.77,
                       address="東京都渋谷区神宮前1-2-3")
        )

    def _by_external(self, rows, external_id: str) -> dict:
        return next(r for r in rows if r["external_id"] == external_id)

    def test_search_properties_include_resolved_fee(self):
        rows = api_queries.search_properties({"limit": 10})
        self.assertEqual(self._by_external(rows, "b1")["contract_fee_yen"], 5500)
        self.assertEqual(self._by_external(rows, "u1")["contract_fee_yen"], 0)
        self.assertEqual(self._by_external(rows, "b2")["contract_fee_yen"], 6600)
        self.assertIsNone(self._by_external(rows, "x1")["contract_fee_yen"])

    def test_building_units_include_resolved_fee(self):
        """建物 units(配信契約の部屋表現)にも解決済み手数料が乗る(B2-ε 移行)."""
        from store.queries.buildings import search_buildings

        fees = {}
        for building in search_buildings({"limit": 10}):
            for unit in building["units"]:
                fees[unit["external_id"]] = unit["contract_fee_yen"]
        self.assertEqual(fees["u1"], 0)
        self.assertEqual(fees["b2"], 6600)
        self.assertEqual(fees["b1"], 5500)
        self.assertIsNone(fees["x1"])

    def test_property_detail_includes_resolved_fee(self):
        conn = self.repo.connect()
        try:
            ids = {
                row["external_id"]: row["id"]
                for row in conn.execute("SELECT id, external_id FROM properties")
            }
        finally:
            conn.close()
        detail_u = api_queries.get_property_detail(ids["u1"], by="id")
        detail_b2 = api_queries.get_property_detail(ids["b2"], by="id")
        detail_x = api_queries.get_property_detail(ids["x1"], by="id")
        self.assertEqual(detail_u["contract_fee_yen"], 0)
        self.assertEqual(detail_b2["contract_fee_yen"], 6600)
        self.assertIsNone(detail_x["contract_fee_yen"])


class ApiModelContractTest(unittest.TestCase):
    """OpenAPI 正本の GeoJSON / 詳細モデルが手数料フィールドを持つこと."""

    def test_geojson_properties_model_has_fee_field(self):
        import api_models

        self.assertIn(
            "contract_fee_yen", api_models.BuildingUnitProperties.model_fields
        )
        self.assertIn("contract_fee_yen", api_models.PropertyDetailResponse.model_fields)


if __name__ == "__main__":
    unittest.main()
