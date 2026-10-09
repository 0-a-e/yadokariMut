#!/usr/bin/env python3
import unittest


import sources  # noqa: F401
from domain.models import PricePlan
from helpers import isolated_db, make_draft
from store.repository import Repository
from store.source_catalog import list_source_admin_info, resolve_scrape_sources


class TestSourceCatalog(unittest.TestCase):
    def test_list_includes_registered(self):
        infos = list_source_admin_info()
        ids = {s["id"] for s in infos}
        self.assertIn("bratto", ids)
        self.assertIn("unionmonthly", ids)
        for s in infos:
            if s["id"] in ("bratto", "unionmonthly"):
                self.assertTrue(s["registered"])
                self.assertTrue(s["available"])
                self.assertIsInstance(s.get("targets"), list)
                self.assertGreater(len(s["targets"]), 0)
                t0 = s["targets"][0]
                for key in (
                    "key",
                    "slug",
                    "name",
                    "counts",
                    "has_data",
                ):
                    self.assertIn(key, t0)

    def test_union_targets_include_tokyo(self):
        infos = {s["id"]: s for s in list_source_admin_info()}
        union = infos["unionmonthly"]
        slugs = {t["slug"] for t in union["targets"]}
        self.assertIn("tokyo", slugs)
        self.assertIn("kanagawa", slugs)

    def test_resolve_all(self):
        resolved = resolve_scrape_sources(["all"])
        self.assertIn("bratto", resolved)
        self.assertIn("unionmonthly", resolved)

    def test_resolve_single(self):
        self.assertEqual(resolve_scrape_sources(["unionmonthly"]), ["unionmonthly"])

    def test_resolve_unknown(self):
        with self.assertRaises(ValueError):
            resolve_scrape_sources(["nope"])

    def test_targets_merge_db_counts(self):
        """When v2 DB has properties, targets should reflect has_data / counts."""
        with isolated_db("admin-sources") as db_path:
            repo = Repository()
            repo.upsert_property(
                make_draft(
                    "u1",
                    source_site="unionmonthly",
                    title="t",
                    detail_url="https://example.test/u1",
                    price_plans=[
                        PricePlan(
                            plan_key="short",
                            duration_min_days=30,
                            duration_max_days=89,
                            presentation_unit="per_day",
                            rent_current_yen=5000,
                        )
                    ],
                )
            )
            # list_source_admin_info constructs Repository() without path — set env
            infos = {s["id"]: s for s in list_source_admin_info()}
            union = infos["unionmonthly"]
            tokyo = next(t for t in union["targets"] if t["slug"] == "tokyo")
            self.assertTrue(tokyo["has_data"])
            self.assertGreaterEqual(tokyo["counts"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
