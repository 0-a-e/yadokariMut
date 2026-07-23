#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import sources  # noqa: F401
from domain.models import PricePlan, PropertyDraft
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
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = tmp.name
        old = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        old_layer = os.environ.get("YADOKARIMUT_DATA_LAYER")
        try:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = db_path
            os.environ["YADOKARIMUT_DATA_LAYER"] = "v2"
            repo = Repository(db_path)
            repo.init_db()
            repo.upsert_property(
                PropertyDraft(
                    source_site="unionmonthly",
                    external_id="u1",
                    title="t",
                    detail_url="https://example.test/u1",
                    prefecture_slug="tokyo",
                    prefecture_name="東京都",
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
        finally:
            if old is None:
                os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
            else:
                os.environ["YADOKARIMUT_V2_DB_PATH"] = old
            if old_layer is None:
                os.environ.pop("YADOKARIMUT_DATA_LAYER", None)
            else:
                os.environ["YADOKARIMUT_DATA_LAYER"] = old_layer
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
