#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BraTTo adapter + convert tests (offline fixtures)."""

import os
import tempfile
import unittest
from pathlib import Path


import sources  # noqa: F401
from sources.bratto.convert import draft_from_normalized
from sources.base import FetchedPage, ListTarget
from sources.registry import SourceRegistry
from store.repository import Repository
from ingest.pipeline import IngestPipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIST_FIXTURE = FIXTURES / "bratto_search_list.html"
DETAIL_FIXTURE = FIXTURES / "bratto_detail.html"


class TestBrattoRegistry(unittest.TestCase):
    def test_registered(self):
        self.assertIsNotNone(SourceRegistry.get("bratto"))
        adapter = SourceRegistry.create(
            "bratto",
            {
                "delay_seconds": 0,
                "prefectures": {"tokyo": {"name": "東京都", "list_path": "/tokyo/search_list/"}},
            },
        )
        self.assertEqual(adapter.source_id, "bratto")
        targets = adapter.discover_list_targets()
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].prefecture_slug, "tokyo")


@unittest.skipUnless(LIST_FIXTURE.exists(), "list fixture missing")
class TestBrattoListParse(unittest.TestCase):
    def test_list_fixture(self):
        adapter = SourceRegistry.create(
            "bratto",
            {
                "delay_seconds": 0,
                "prefectures": {"tokyo": {"name": "東京都", "list_path": "/tokyo/search_list/"}},
            },
        )
        html = LIST_FIXTURE.read_text(encoding="utf-8", errors="replace")
        page = FetchedPage(
            url="https://www.000area-weekly.com/tokyo/search_list/?pn=3",
            html=html,
            status_code=200,
            page_type="list",
        )
        target = ListTarget(
            key="tokyo",
            list_url="https://www.000area-weekly.com/tokyo/search_list/",
            prefecture_slug="tokyo",
            prefecture_name="東京都",
        )
        cards = adapter.parse_list(page, target)
        self.assertGreater(len(cards), 0)
        self.assertTrue(all(c.external_id for c in cards))
        self.assertTrue(all(c.detail_url for c in cards))
        # _has_next ハックは廃止: raw に継続フラグを埋め込まない
        self.assertTrue(all("_has_next" not in c.raw for c in cards))
        # 継続判定は基底 API has_next が担う(フィクスチャは「次へ」リンクあり)
        self.assertIs(adapter.has_next(page, cards), True)

    def test_has_next_false_without_next_link(self):
        from sources.bratto.adapter import BrattoAdapter

        adapter = BrattoAdapter({"delay_seconds": 0})
        page = FetchedPage(
            url="https://www.000area-weekly.com/tokyo/search_list/?pn=99",
            html="<html><body><p>最終ページ</p></body></html>",
            status_code=200,
            page_type="list",
        )
        self.assertIs(adapter.has_next(page, []), False)


@unittest.skipUnless(DETAIL_FIXTURE.exists(), "detail fixture missing")
class TestBrattoDetailConvert(unittest.TestCase):
    def test_detail_to_draft(self):
        from sources.bratto.parser import parse_detail_page, normalize_property

        html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")
        detail = parse_detail_page(html)
        list_data = {
            "room_id": "fixture-sendagaya",
            "title": "BraTTo千駄ヶ谷ドール",
            "detail_url": "https://www.000area-weekly.com/tokyo/room/?room_id=1",
            "prefecture_slug": "tokyo",
            "prefecture_name": "東京都",
            "address": "東京都渋谷区千駄ヶ谷",
        }
        normalized = normalize_property(list_data, detail)
        draft = draft_from_normalized(normalized)
        self.assertEqual(draft.source_site, "bratto")
        self.assertEqual(draft.external_id, "fixture-sendagaya")
        self.assertTrue(draft.title)
        self.assertGreaterEqual(len(draft.price_plans), 1)
        for p in draft.price_plans:
            self.assertEqual(p.presentation_unit, "per_day")
            self.assertIn(p.plan_key, ("s_short", "short", "middle", "long", "other"))

    def test_pipeline_fixture_upsert(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        old_db = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        try:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = tmp.name
            repo = Repository(tmp.name)
            repo.init_db()
            adapter = SourceRegistry.create("bratto", {"delay_seconds": 0})
            pipeline = IngestPipeline(adapter, repo, save_raw=False)
            html = DETAIL_FIXTURE.read_text(encoding="utf-8", errors="replace")
            pid = pipeline.ingest_detail_html(
                html,
                detail_url="https://www.000area-weekly.com/tokyo/room/?room_id=fixture-sendagaya",
                external_id="fixture-sendagaya",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            )
            # parse_detail uses normalize which needs room_id from card — external_id override on draft
            prop = repo.get_property(pid)
            self.assertEqual(prop["source_site"], "bratto")
            self.assertTrue(prop["external_id"])
            self.assertGreaterEqual(len(prop["price_plans"]), 1)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            if old_db is None:
                os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
            else:
                os.environ["YADOKARIMUT_V2_DB_PATH"] = old_db


class TestApiQueriesShape(unittest.TestCase):
    def test_search_empty_db(self):
        from store.api_queries import search_properties

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        old_db = os.environ.get("YADOKARIMUT_V2_DB_PATH")
        try:
            os.environ["YADOKARIMUT_V2_DB_PATH"] = tmp.name
            repo = Repository(tmp.name)
            repo.init_db()
            rows = search_properties({"limit": 10})
            self.assertEqual(rows, [])
        finally:
            os.unlink(tmp.name)
            if old_db is None:
                os.environ.pop("YADOKARIMUT_V2_DB_PATH", None)
            else:
                os.environ["YADOKARIMUT_V2_DB_PATH"] = old_db


if __name__ == "__main__":
    unittest.main()
