#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0: partial-pref mark_inactive must not deactivate other prefectures."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from domain.models import PricePlan, PropertyDraft
from ingest.pipeline import IngestPipeline
from sources.base import FetchedPage, ListCard, ListTarget, SourceAdapter
from store.repository import Repository


class _FakeAdapter(SourceAdapter):
    source_id = "fakesource"
    display_name = "Fake"

    def __init__(self, config=None, *, cards_by_pref=None):
        super().__init__(config or {})
        self.cards_by_pref = cards_by_pref or {}

    def discover_list_targets(self):
        only = self.config.get("pref_filter")
        all_t = [
            ListTarget(
                key="tokyo",
                list_url="https://example.test/tokyo/",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            ),
            ListTarget(
                key="osaka",
                list_url="https://example.test/osaka/",
                prefecture_slug="osaka",
                prefecture_name="大阪府",
            ),
        ]
        if only:
            return [t for t in all_t if t.prefecture_slug in only]
        return all_t

    def build_list_page_url(self, target, page: int) -> str:
        return target.list_url

    def parse_list(self, page, target):
        return list(self.cards_by_pref.get(target.prefecture_slug or target.key, []))

    def parse_detail(self, page, card):
        return PropertyDraft(
            source_site=self.source_id,
            external_id=card.external_id,
            title=card.title or card.external_id,
            detail_url=card.detail_url,
            prefecture_slug=card.prefecture_slug,
            prefecture_name=card.prefecture_name,
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

    def fetch_list_page(self, target, page: int):
        return FetchedPage(
            url=target.list_url,
            html=f"<html>{target.key}</html>",
            status_code=200,
            page_type="list",
        )

    def fetch_detail_page(self, card):
        return FetchedPage(
            url=card.detail_url,
            html=f"<html>{card.external_id}</html>",
            status_code=200,
            page_type="detail",
        )


def _seed(repo: Repository, source: str, slug: str, name: str, ext_id: str) -> None:
    repo.upsert_property(
        PropertyDraft(
            source_site=source,
            external_id=ext_id,
            title=f"{slug}-{ext_id}",
            detail_url=f"https://example.test/{slug}/{ext_id}",
            prefecture_slug=slug,
            prefecture_name=name,
            is_active=True,
            price_plans=[
                PricePlan(
                    plan_key="short",
                    duration_min_days=30,
                    duration_max_days=89,
                    presentation_unit="per_day",
                    rent_current_yen=4000,
                )
            ],
        )
    )


class TestPrefScopedMarkInactive(unittest.TestCase):
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

    def test_partial_pref_does_not_deactivate_other_pref(self):
        # Existing data in tokyo + osaka
        _seed(self.repo, "fakesource", "tokyo", "東京都", "t-old")
        _seed(self.repo, "fakesource", "osaka", "大阪府", "o-old")
        _seed(self.repo, "fakesource", "tokyo", "東京都", "t-keep")

        adapter = _FakeAdapter(
            {"pref_filter": ["tokyo"]},
            cards_by_pref={
                "tokyo": [
                    ListCard(
                        external_id="t-keep",
                        detail_url="https://example.test/tokyo/t-keep",
                        title="keep",
                        prefecture_slug="tokyo",
                        prefecture_name="東京都",
                    ),
                    ListCard(
                        external_id="t-new",
                        detail_url="https://example.test/tokyo/t-new",
                        title="new",
                        prefecture_slug="tokyo",
                        prefecture_name="東京都",
                    ),
                ],
            },
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=1, mark_inactive=True)

        self.assertIn("tokyo", result.by_target)
        self.assertNotIn("osaka", result.by_target)

        conn = self.repo.connect()
        try:
            rows = {
                r["external_id"]: r["is_active"]
                for r in conn.execute(
                    "SELECT external_id, is_active FROM properties WHERE source_site=?",
                    ("fakesource",),
                )
            }
        finally:
            conn.close()

        # tokyo old gone → inactive; keep + new active; osaka untouched
        self.assertEqual(rows["t-old"], 0)
        self.assertEqual(rows["t-keep"], 1)
        self.assertEqual(rows["t-new"], 1)
        self.assertEqual(rows["o-old"], 1)

    def test_scrape_run_targets_recorded(self):
        adapter = _FakeAdapter(
            cards_by_pref={
                "tokyo": [
                    ListCard(
                        external_id="t1",
                        detail_url="https://example.test/tokyo/t1",
                        prefecture_slug="tokyo",
                        prefecture_name="東京都",
                    )
                ],
                "osaka": [
                    ListCard(
                        external_id="o1",
                        detail_url="https://example.test/osaka/o1",
                        prefecture_slug="osaka",
                        prefecture_name="大阪府",
                    )
                ],
            },
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        pipeline.run(max_pages=1, mark_inactive=False)

        latest = self.repo.latest_scrape_runs_by_target("fakesource")
        self.assertIn("tokyo", latest.get("fakesource", {}))
        self.assertIn("osaka", latest.get("fakesource", {}))
        self.assertEqual(latest["fakesource"]["tokyo"]["status"], "ok")
        self.assertEqual(latest["fakesource"]["tokyo"]["list_items"], 1)

        counts = self.repo.counts_by_prefecture("fakesource")
        self.assertEqual(counts["fakesource"]["tokyo"]["active"], 1)
        self.assertEqual(counts["fakesource"]["osaka"]["active"], 1)


if __name__ == "__main__":
    unittest.main()
