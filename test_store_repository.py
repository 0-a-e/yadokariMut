#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for store.schema / store.repository (v2)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from domain.models import (
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
)
from domain.pricing import MONTH_DAYS, calculate_stay_total
from store.repository import Repository
from store.schema import SCHEMA_VERSION, get_schema_version, init_schema


class TestSchemaAndRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = self._tmp.name
        self.repo = Repository(self.db_path)
        self.repo.init_db()

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_schema_version(self):
        conn = self.repo.connect()
        try:
            self.assertEqual(get_schema_version(conn), SCHEMA_VERSION)
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("scrape_run_targets", tables)
        finally:
            conn.close()

    def test_scrape_run_targets_and_counts(self):
        draft = PropertyDraft(
            source_site="unionmonthly",
            external_id="r1",
            title="x",
            detail_url="https://example.test/r1",
            prefecture_slug="tokyo",
            prefecture_name="東京都",
            price_plans=[
                PricePlan(
                    plan_key="short",
                    duration_min_days=30,
                    duration_max_days=89,
                    presentation_unit="per_day",
                    rent_current_yen=3000,
                )
            ],
        )
        self.repo.upsert_property(draft)
        run_id = self.repo.start_scrape_run("unionmonthly", meta={"prefs": ["tokyo"]})
        tid = self.repo.start_scrape_run_target(run_id, "unionmonthly", "tokyo")
        self.repo.finish_scrape_run_target(
            tid, status="ok", list_pages=1, list_items=1, detail_ok=1
        )
        self.repo.finish_scrape_run(run_id, status="ok", list_pages=1, list_items=1, detail_ok=1)

        counts = self.repo.counts_by_prefecture("unionmonthly")
        self.assertEqual(counts["unionmonthly"]["tokyo"]["total"], 1)
        latest = self.repo.latest_scrape_runs_by_target("unionmonthly")
        self.assertEqual(latest["unionmonthly"]["tokyo"]["status"], "ok")
        self.assertEqual(latest["unionmonthly"]["tokyo"]["list_items"], 1)

    def test_upsert_and_get(self):
        draft = PropertyDraft(
            source_site="unionmonthly",
            external_id="6575",
            title="テスト物件",
            detail_url="https://www.unionmonthly.jp/tokyo/6575/",
            prefecture_slug="tokyo",
            prefecture_name="東京都",
            address="東京都 渋谷区 宇田川町6-15",
            layout="1LDK",
            area_m2=38.91,
            accesses=[
                PropertyAccess(
                    line_name="JR山手線",
                    station_name="渋谷駅",
                    walk_minutes=8,
                    raw_text="JR山手線　渋谷駅　徒歩8分",
                    sort_order=0,
                )
            ],
            images=[PropertyImage(image_url="https://example.com/a.jpg", image_type="thumbnail")],
            features=[PropertyFeature(feature_name="オートロック", feature_category="building")],
            price_plans=[
                PricePlan(
                    plan_key="long",
                    plan_name="ロング",
                    duration_min_days=210,
                    duration_max_days=729,
                    presentation_unit="per_month",
                    rent_original_yen=384000,
                    rent_current_yen=336000,
                    management_yen=28500,
                    cleaning_yen=0,
                    campaign_label="キャンペーン料金",
                ),
                PricePlan(
                    plan_key="short",
                    plan_name="ショート",
                    duration_min_days=30,
                    duration_max_days=89,
                    presentation_unit="per_month",
                    rent_original_yen=396000,
                    rent_current_yen=354000,
                    management_yen=28500,
                    cleaning_yen=0,
                ),
            ],
        )
        pid = self.repo.upsert_property(draft)
        self.assertIsInstance(pid, int)

        prop = self.repo.get_property(pid)
        self.assertIsNotNone(prop)
        self.assertEqual(prop["source_site"], "unionmonthly")
        self.assertEqual(prop["external_id"], "6575")
        self.assertEqual(len(prop["price_plans"]), 2)
        self.assertEqual(len(prop["accesses"]), 1)
        # catalog uses cheapest per-day among plans → long 336000/30
        self.assertEqual(prop["catalog_rent_per_day_yen"], 336000 // MONTH_DAYS)

        # upsert same identity
        draft.title = "更新タイトル"
        pid2 = self.repo.upsert_property(draft)
        self.assertEqual(pid, pid2)
        prop2 = self.repo.get_property(pid)
        self.assertEqual(prop2["title"], "更新タイトル")

    def test_search_by_source(self):
        self.repo.upsert_property(
            PropertyDraft(
                source_site="bratto",
                external_id="1",
                title="A",
                prefecture_name="東京都",
                price_plans=[
                    PricePlan(
                        plan_key="short",
                        duration_min_days=30,
                        duration_max_days=90,
                        presentation_unit="per_day",
                        rent_current_yen=3000,
                        rent_original_yen=3000,
                    )
                ],
            )
        )
        self.repo.upsert_property(
            PropertyDraft(
                source_site="unionmonthly",
                external_id="2",
                title="B",
                prefecture_name="東京都",
                price_plans=[
                    PricePlan(
                        plan_key="short",
                        duration_min_days=30,
                        duration_max_days=89,
                        presentation_unit="per_month",
                        rent_current_yen=300000,
                        rent_original_yen=300000,
                    )
                ],
            )
        )
        only_union = self.repo.search_properties(source_sites=["unionmonthly"])
        self.assertEqual(len(only_union), 1)
        self.assertEqual(only_union[0]["external_id"], "2")
        counts = self.repo.count_by_source()
        self.assertEqual(counts.get("bratto"), 1)
        self.assertEqual(counts.get("unionmonthly"), 1)

    def test_stay_from_loaded_plans(self):
        pid = self.repo.upsert_property(
            PropertyDraft(
                source_site="bratto",
                external_id="99",
                title="Stay test",
                price_plans=[
                    PricePlan(
                        plan_key="short",
                        plan_name="ショート",
                        duration_min_days=30,
                        duration_max_days=90,
                        presentation_unit="per_day",
                        rent_original_yen=4000,
                        rent_current_yen=3600,
                        management_yen=500,
                        cleaning_yen=20000,
                    )
                ],
            )
        )
        prop = self.repo.get_property(pid)
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=prop["price_plans"],
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.grand_total, (3600 + 500) * 30 + 20000 + 5500)

    def test_mark_inactive(self):
        self.repo.upsert_property(
            PropertyDraft(source_site="unionmonthly", external_id="a", title="A")
        )
        self.repo.upsert_property(
            PropertyDraft(source_site="unionmonthly", external_id="b", title="B")
        )
        n = self.repo.mark_inactive_missing("unionmonthly", {"a"})
        self.assertEqual(n, 1)
        rows = self.repo.search_properties(source_sites=["unionmonthly"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "a")


if __name__ == "__main__":
    unittest.main()
