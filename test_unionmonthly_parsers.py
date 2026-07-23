#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Union Monthly list/detail parser tests (fixture + synthetic list)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import sources  # noqa: F401
from domain.pricing import MONTH_DAYS, calculate_stay_total, resolve_plans_effective
from ingest.pipeline import IngestPipeline
from sources.registry import SourceRegistry
from sources.unionmonthly.detail_parser import parse_detail_html
from sources.unionmonthly.list_parser import extract_total_count, parse_list_html
from store.repository import Repository

FIXTURE_DIR = Path(__file__).resolve().parent / "refs" / "sites" / "union-monthly"
DETAIL_FIXTURE = next(FIXTURE_DIR.glob("*.html"), None)

SYNTHETIC_LIST = """
<html><body>
<p class="now">2,897 件</p>
<div class="list_item" data-troom_id="6575">
  <h2 class="gArticle_name">ユニオンマンスリー渋谷カディナ１ 903</h2>
  <div class="gArticle_image"><img data-original-src="/img/a.jpg" src="/img/a.jpg"></div>
  <p class="gArticle_price"><b>336,000</b>円</p>
  <ul class="gArticle_infoList">
    <li><i class="icon-marker"></i>東京都 渋谷区 宇田川町</li>
    <li>JR山手線　渋谷駅　徒歩8分</li>
  </ul>
  <a class="u-btn01" href="/tokyo/6575/">詳細</a>
</div>
<div class="list_item" data-troom_id="1500">
  <h2 class="gArticle_name">テスト物件</h2>
  <p class="gArticle_price"><b>100,000</b></p>
  <a class="u-btn01" href="/tokyo/1500/">詳細</a>
</div>
</body></html>
"""


class TestListParser(unittest.TestCase):
    def test_parse_synthetic(self):
        cards = parse_list_html(SYNTHETIC_LIST, prefecture_slug="tokyo", prefecture_name="東京都")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].external_id, "6575")
        self.assertEqual(cards[0].list_price_yen, 336000)
        self.assertIn("渋谷", cards[0].address or "")
        self.assertTrue(cards[0].detail_url.endswith("/tokyo/6575/"))
        self.assertEqual(extract_total_count(SYNTHETIC_LIST), 2897)


@unittest.skipUnless(DETAIL_FIXTURE and DETAIL_FIXTURE.exists(), "union detail fixture missing")
class TestDetailParserFixture(unittest.TestCase):
    def setUp(self):
        self.html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")

    def test_core_fields(self):
        draft = parse_detail_html(
            self.html,
            detail_url="https://www.unionmonthly.jp/tokyo/6575/",
        )
        self.assertEqual(draft.source_site, "unionmonthly")
        self.assertEqual(draft.external_id, "6575")
        self.assertIn("カディナ", draft.title or "")
        self.assertIn("渋谷区", draft.address or "")
        self.assertEqual(draft.prefecture_name, "東京都")
        self.assertEqual(draft.layout, "1LDK")
        self.assertAlmostEqual(draft.area_m2 or 0, 38.91, places=2)
        self.assertEqual(draft.built_year, 2024)
        self.assertEqual(draft.structure, "鉄筋コンクリート造")
        self.assertIsNotNone(draft.lat)
        self.assertIsNotNone(draft.lng)
        self.assertTrue(any(a.walk_minutes == 8 for a in draft.accesses))
        self.assertGreaterEqual(len(draft.features), 5)
        self.assertEqual(len(draft.price_plans), 3)

    def test_price_plans_monthly(self):
        draft = parse_detail_html(self.html, detail_url="https://www.unionmonthly.jp/tokyo/6575/")
        by_key = {p.plan_key: p for p in draft.price_plans}
        self.assertIn("short", by_key)
        self.assertIn("middle", by_key)
        self.assertIn("long", by_key)
        long_p = by_key["long"]
        self.assertEqual(long_p.presentation_unit, "per_month")
        self.assertEqual(long_p.rent_original_yen, 384000)
        self.assertEqual(long_p.rent_current_yen, 336000)
        self.assertEqual(long_p.management_yen, 28500)
        self.assertEqual(long_p.cleaning_yen, 0)
        self.assertEqual(long_p.duration_min_days, 210)

    def test_stay_total_from_fixture(self):
        draft = parse_detail_html(self.html, detail_url="https://www.unionmonthly.jp/tokyo/6575/")
        plans = resolve_plans_effective(
            draft.price_plans,
            draft.campaigns,
            on_date="2026-08-01",
        )
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-09-15",  # 46 days → short
            plans=plans,
            campaigns=draft.campaigns,
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.plan_key, "short")
        rent_d = 354000 // MONTH_DAYS
        mgmt_d = 28500 // MONTH_DAYS
        self.assertEqual(result.breakdown.rent_daily, rent_d)
        self.assertEqual(result.breakdown.management_daily, mgmt_d)


class TestRegistryAndPipelineFixture(unittest.TestCase):
    def test_registry(self):
        self.assertIsNotNone(SourceRegistry.get("unionmonthly"))
        adapter = SourceRegistry.create("unionmonthly", {"delay_seconds": 0})
        self.assertEqual(adapter.source_id, "unionmonthly")
        targets = adapter.discover_list_targets()
        self.assertGreaterEqual(len(targets), 1)

    @unittest.skipUnless(DETAIL_FIXTURE and DETAIL_FIXTURE.exists(), "union detail fixture missing")
    def test_pipeline_fixture_upsert(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            repo = Repository(tmp.name)
            repo.init_db()
            adapter = SourceRegistry.create("unionmonthly", {"delay_seconds": 0})
            pipeline = IngestPipeline(adapter, repo, save_raw=False)
            html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")
            pid = pipeline.ingest_detail_html(
                html,
                detail_url="https://www.unionmonthly.jp/tokyo/6575/",
                external_id="6575",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            )
            prop = repo.get_property(pid)
            self.assertEqual(prop["source_site"], "unionmonthly")
            self.assertEqual(prop["external_id"], "6575")
            self.assertEqual(len(prop["price_plans"]), 3)
            self.assertEqual(prop["catalog_rent_per_day_yen"], 336000 // MONTH_DAYS)
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
