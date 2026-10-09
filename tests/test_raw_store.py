#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""raw_pages.parser_version 記録の検証(引数化 + アダプタからの伝播)。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from domain.models import PropertyDraft
from ingest.pipeline import IngestPipeline
from ingest.raw_store import save_raw_page
from sources.base import FetchedPage, ListCard, ListTarget, SourceAdapter
from store.repository import Repository


class _StubAdapter(SourceAdapter):
    source_id = "stubsource"
    display_name = "Stub"
    parser_version = "stub-parser-v9"

    def discover_list_targets(self):
        return [
            ListTarget(
                key="tokyo",
                list_url="https://example.test/tokyo/",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            )
        ]

    def build_list_page_url(self, target, page: int) -> str:
        return target.list_url

    def parse_list(self, page, target):
        return [
            ListCard(
                external_id="s1",
                detail_url="https://example.test/tokyo/s1",
                prefecture_slug="tokyo",
                prefecture_name="東京都",
            )
        ]

    def parse_detail(self, page, card):
        return PropertyDraft(
            source_site=self.source_id,
            external_id=card.external_id,
            title=card.external_id,
            detail_url=card.detail_url,
            prefecture_slug=card.prefecture_slug,
        )

    def fetch_list_page(self, target, page: int):
        return FetchedPage(url=target.list_url, html="<html>list</html>", status_code=200, page_type="list")

    def fetch_detail_page(self, card):
        return FetchedPage(url=card.detail_url, html="<html>detail</html>", status_code=200, page_type="detail")


class TestSaveRawPageParserVersion(unittest.TestCase):
    def setUp(self):
        from helpers import ScopedDb

        self._db = ScopedDb("raw-store")
        self.addCleanup(self._db.close)
        self.repo = Repository()
        self._raw_dirs = tempfile.TemporaryDirectory()
        self.addCleanup(self._raw_dirs.cleanup)

    def _parser_versions(self) -> list[str]:
        conn = self.repo.connect()
        try:
            return [
                r["parser_version"]
                for r in conn.execute("SELECT parser_version FROM raw_pages ORDER BY id")
            ]
        finally:
            conn.close()

    def test_explicit_and_default_parser_version(self):
        page = FetchedPage(url="https://example.test/a", html="<html>a</html>", status_code=200, page_type="detail")
        with patch("ingest.raw_store.RAW_DIR", self._raw_dirs.name):
            save_raw_page(page, source_site="stubsource", repo=self.repo, parser_version="custom-1.2")
            save_raw_page(page, source_site="stubsource", repo=self.repo)

        self.assertEqual(self._parser_versions(), ["custom-1.2", "1.0"])

    def test_pipeline_propagates_adapter_parser_version(self):
        # save_raw=True の通常フロー(list + detail)でアダプタの版が記録されること
        adapter = _StubAdapter()
        with patch("ingest.raw_store.RAW_DIR", self._raw_dirs.name):
            IngestPipeline(adapter, self.repo, save_raw=True).run(max_pages=1)

        self.assertEqual(self._parser_versions(), ["stub-parser-v9", "stub-parser-v9"])


if __name__ == "__main__":
    unittest.main()
