#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0: partial-pref mark_inactive must not deactivate other prefectures."""

from __future__ import annotations

import os
import tempfile
import unittest
import json


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
        self._page_no = 1

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
        cards = list(self.cards_by_pref.get(target.prefecture_slug or target.key, []))
        size = self.page_size()
        start = (self._page_no - 1) * size
        return cards[start:start + size]

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
        self._page_no = page
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


class TestListCompletedGate(unittest.TestCase):
    """max_pages 打ち切り時は list_completed=False となり mark_inactive が走らないこと。"""

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

    @staticmethod
    def _cards(prefix: str, slug: str, name: str, n: int):
        return [
            ListCard(
                external_id=f"{prefix}-{i}",
                detail_url=f"https://example.test/{slug}/{prefix}-{i}",
                prefecture_slug=slug,
                prefecture_name=name,
            )
            for i in range(n)
        ]

    def _active_flags(self) -> dict[str, int]:
        conn = self.repo.connect()
        try:
            rows = {
                r["external_id"]: r["is_active"]
                for r in conn.execute(
                    "SELECT external_id, is_active FROM properties WHERE source_site=?",
                    ("fakesource",),
                )
            }
            return rows
        finally:
            conn.close()

    def _target_list_completed(self, target_key: str) -> int | None:
        conn = self.repo.connect()
        try:
            row = conn.execute(
                """
                SELECT list_completed FROM scrape_run_targets
                WHERE target_key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (target_key,),
            ).fetchone()
            return None if row is None else row["list_completed"]
        finally:
            conn.close()

    def test_max_pages_truncation_skips_mark_inactive(self):
        _seed(self.repo, "fakesource", "tokyo", "東京都", "t-vanish")
        adapter = _FakeAdapter(
            {"pref_filter": ["tokyo"], "page_size": 1},
            cards_by_pref={"tokyo": self._cards("tk", "tokyo", "東京都", 2)},
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=1, mark_inactive=True)

        tr = result.by_target["tokyo"]
        self.assertFalse(tr.list_completed)
        self.assertEqual(self._target_list_completed("tokyo"), 0)
        # 打ち切りなので見えなかった t-vanish は非アクティブ化されない
        rows = self._active_flags()
        self.assertEqual(rows["t-vanish"], 1)

    def test_full_crawl_runs_mark_inactive(self):
        _seed(self.repo, "fakesource", "tokyo", "東京都", "t-vanish")
        adapter = _FakeAdapter(
            {"pref_filter": ["tokyo"], "page_size": 1},
            cards_by_pref={"tokyo": self._cards("tk", "tokyo", "東京都", 2)},
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=10, mark_inactive=True)

        tr = result.by_target["tokyo"]
        self.assertTrue(tr.list_completed)
        self.assertEqual(self._target_list_completed("tokyo"), 1)
        # 全ページ取得できているので不在物件は非アクティブ化される
        rows = self._active_flags()
        self.assertEqual(rows["t-vanish"], 0)

    def test_extra_run_meta_recorded(self):
        adapter = _FakeAdapter(
            {"pref_filter": ["tokyo"]},
            cards_by_pref={"tokyo": self._cards("tk", "tokyo", "東京都", 1)},
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        pipeline.run(
            max_pages=1,
            extra_run_meta={"rotation": True, "pref_budget_detail_ok": 50},
        )

        conn = self.repo.connect()
        try:
            row = conn.execute(
                "SELECT meta_json FROM scrape_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        meta = json.loads(row["meta_json"])
        self.assertIs(meta["rotation"], True)
        self.assertEqual(meta["pref_budget_detail_ok"], 50)
        # 既存キーは維持される
        self.assertEqual(meta["prefs"], ["tokyo"])
        # rotation_usage_today の LIKE パターンに一致する形式
        self.assertIn('"rotation": true', row["meta_json"])


class _FailingListAdapter(_FakeAdapter):
    """fetch_list_page raises for prefectures listed in fail_prefs."""

    def __init__(self, config=None, *, fail_prefs=None, **kwargs):
        super().__init__(config, **kwargs)
        self.fail_prefs = set(fail_prefs or [])

    def fetch_list_page(self, target, page: int):
        slug = target.prefecture_slug or target.key
        if slug in self.fail_prefs:
            raise RuntimeError(f"simulated connection failure for {slug}")
        return super().fetch_list_page(target, page)


class TestRunStatusSummary(unittest.TestCase):
    """run全体ステータス確定: 全県error→error / 一部失敗→partial / 全成功→ok。"""

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

    def _last_run_row(self) -> dict:
        conn = self.repo.connect()
        try:
            row = conn.execute(
                """
                SELECT status, list_items, error_summary FROM scrape_runs
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def test_all_targets_error_means_run_error(self):
        # 42県全滅(IPブロック相当): run は例外を投げず error として記録される
        adapter = _FailingListAdapter(fail_prefs=["tokyo", "osaka"])
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=1, mark_inactive=False)

        self.assertEqual(result.status, "error")
        self.assertEqual(
            {tr.status for tr in result.by_target.values()}, {"error"}
        )
        row = self._last_run_row()
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["list_items"], 0)
        self.assertIn("simulated connection failure", row["error_summary"])

    def test_one_target_error_means_partial(self):
        adapter = _FailingListAdapter(
            fail_prefs=["osaka"],
            cards_by_pref={
                "tokyo": [
                    ListCard(
                        external_id="t1",
                        detail_url="https://example.test/tokyo/t1",
                        prefecture_slug="tokyo",
                        prefecture_name="東京都",
                    )
                ],
            },
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=1, mark_inactive=False)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.by_target["tokyo"].status, "ok")
        self.assertEqual(result.by_target["osaka"].status, "error")
        self.assertEqual(self._last_run_row()["status"], "partial")

    def test_all_ok_means_ok(self):
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
            },
        )
        pipeline = IngestPipeline(adapter, self.repo, save_raw=False)
        result = pipeline.run(max_pages=1, mark_inactive=False)

        self.assertEqual(result.status, "ok")
        self.assertEqual(self._last_run_row()["status"], "ok")

    def test_recent_scrape_runs_returns_newest_first(self):
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
            },
        )
        IngestPipeline(adapter, self.repo, save_raw=False).run(max_pages=1)
        failing = _FailingListAdapter({"pref_filter": ["tokyo"]}, fail_prefs=["tokyo"])
        IngestPipeline(failing, self.repo, save_raw=False).run(max_pages=1)

        runs = self.repo.recent_scrape_runs(limit=5)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["status"], "error")
        self.assertEqual(runs[1]["status"], "ok")
        self.assertEqual(
            list(runs[0].keys()),
            [
                "id", "source_site", "started_at", "finished_at", "status",
                "list_pages", "list_items", "detail_ok", "detail_fail",
                "error_summary",
            ],
        )


if __name__ == "__main__":
    unittest.main()
