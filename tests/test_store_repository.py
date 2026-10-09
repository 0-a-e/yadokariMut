#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for store.schema / store.repository (v2)."""

import json
import unittest
from datetime import datetime


from domain.models import (
    PricePlan,
    PropertyAccess,
    PropertyDraft,
    PropertyFeature,
    PropertyImage,
)
from domain.pricing import MONTH_DAYS, calculate_stay_total
from store.repository import Repository
from helpers import fetch_child_rows, fetch_property_row


class TestSchemaAndRepository(unittest.TestCase):
    def setUp(self):
        from helpers import ScopedDb

        self._scope = ScopedDb("repo")
        self.repo = Repository()
        self.addCleanup(self._scope.close)

    def test_schema_version(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        from store.migrations import ALEMBIC_INI, current

        head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
        self.assertEqual(current(), head)
        conn = self.repo.connect()
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
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
            features=[PropertyFeature(feature_name="オートロック", category=None)],
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

        prop = fetch_property_row(self.repo, pid)
        self.assertIsNotNone(prop)
        self.assertEqual(prop["source_site"], "unionmonthly")
        self.assertEqual(prop["external_id"], "6575")
        self.assertEqual(len(fetch_child_rows(self.repo, pid, "price_plans")), 2)
        self.assertEqual(len(fetch_child_rows(self.repo, pid, "property_accesses")), 1)
        # catalog uses cheapest per-day among plans → long 336000/30
        self.assertEqual(prop["catalog_rent_per_day_yen"], 336000 // MONTH_DAYS)

        # upsert same identity
        draft.title = "更新タイトル"
        pid2 = self.repo.upsert_property(draft)
        self.assertEqual(pid, pid2)
        self.assertEqual(fetch_property_row(self.repo, pid)["title"], "更新タイトル")

    def test_source_counts_and_prefecture_stats(self):
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
        counts = self.repo.count_by_source()
        self.assertEqual(counts.get("bratto"), 1)
        self.assertEqual(counts.get("unionmonthly"), 1)
        # 県別統計 (管理 UI 用) でも 2 ソース分の行が active 1 件ずつ見えていること
        prefs = self.repo.counts_by_prefecture()
        self.assertEqual(prefs["bratto"][""]["total"], 1)
        self.assertEqual(prefs["unionmonthly"][""]["total"], 1)
        self.assertEqual(prefs["unionmonthly"][""]["active"], 1)
        self.assertEqual(prefs["unionmonthly"][""]["missing_coords"], 1)

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
        result = calculate_stay_total(
            check_in="2026-08-01",
            check_out="2026-08-30",
            plans=fetch_child_rows(
                self.repo, pid, "price_plans", " ORDER BY duration_min_days"
            ),
            use_structured_campaigns=False,
        )
        self.assertTrue(result.ok)
        # contract_fee_yen 未指定 = 算出不能 → 総額から除外(warnings で明示)
        self.assertEqual(result.grand_total, (3600 + 500) * 30 + 20000)
        self.assertIsNone(result.breakdown.contract_fee)

    def test_mark_inactive(self):
        pid_a = self.repo.upsert_property(
            PropertyDraft(source_site="unionmonthly", external_id="a", title="A")
        )
        pid_b = self.repo.upsert_property(
            PropertyDraft(source_site="unionmonthly", external_id="b", title="B")
        )
        n = self.repo.mark_inactive_missing("unionmonthly", {"a"})
        self.assertEqual(n, 1)
        # count_by_source は is_active=1 の行のみ数えるため 2 → 1 に減る
        self.assertEqual(self.repo.count_by_source().get("unionmonthly"), 1)
        # seen セット外の "b" だけが非活性化され、"a" は活性のまま
        self.assertEqual(fetch_property_row(self.repo, pid_a)["is_active"], 1)
        self.assertEqual(fetch_property_row(self.repo, pid_b)["is_active"], 0)

    def test_finish_scrape_run_target_persists_list_completed(self):
        run_id = self.repo.start_scrape_run("unionmonthly")
        tid = self.repo.start_scrape_run_target(run_id, "unionmonthly", "tokyo")
        self.repo.finish_scrape_run_target(tid, status="ok", list_completed=True)
        tid2 = self.repo.start_scrape_run_target(run_id, "unionmonthly", "osaka")
        self.repo.finish_scrape_run_target(tid2, status="ok")

        conn = self.repo.connect()
        try:
            rows = {
                r["target_key"]: r["list_completed"]
                for r in conn.execute(
                    "SELECT target_key, list_completed FROM scrape_run_targets"
                )
            }
        finally:
            conn.close()
        self.assertEqual(rows["tokyo"], 1)
        self.assertEqual(rows["osaka"], 0)


class TestRotationState(unittest.TestCase):

    def test_alembic_revision_is_pinned(self):
        """PG移行後の版ゲート相当: alembic_version が最新 head まで適用済み."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        from store.migrations import ALEMBIC_INI, current

        head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
        self.assertEqual(current(), head)

    def setUp(self):
        from helpers import ScopedDb

        self._scope = ScopedDb("repo")
        self.repo = Repository()
        self.addCleanup(self._scope.close)

    def _seed_property(self, source_site: str, external_id: str, slug: str) -> None:
        self.repo.upsert_property(
            PropertyDraft(
                source_site=source_site,
                external_id=external_id,
                title=f"{slug}-{external_id}",
                prefecture_slug=slug,
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
        )

    def test_seed_is_idempotent_and_counts_known_total(self):
        self._seed_property("unionmonthly", "p1", "tokyo")
        self._seed_property("unionmonthly", "p2", "tokyo")

        inserted = self.repo.seed_rotation_state(
            "unionmonthly", ["tokyo", "osaka", "kyoto"]
        )
        self.assertEqual(inserted, 3)
        # 2回目は冪等で 0 件
        self.assertEqual(
            self.repo.seed_rotation_state("unionmonthly", ["tokyo", "osaka", "kyoto"]), 0
        )

        states = self.repo.load_rotation_states("unionmonthly")
        self.assertEqual(
            [s["prefecture_slug"] for s in states], ["kyoto", "osaka", "tokyo"]
        )
        by_slug = {s["prefecture_slug"]: s for s in states}
        self.assertEqual(by_slug["tokyo"]["known_total"], 2)
        self.assertEqual(by_slug["osaka"]["known_total"], 0)
        self.assertIsNone(by_slug["tokyo"]["last_full_ok_at"])
        self.assertIsNone(by_slug["tokyo"]["last_run_at"])
        self.assertIsNotNone(by_slug["tokyo"]["updated_at"])

        # source_site が違えば別枠でシードされる
        self.assertEqual(self.repo.seed_rotation_state("bratto", ["tokyo"]), 1)
        self.assertEqual(len(self.repo.load_rotation_states("bratto")), 1)
        self.assertEqual(len(self.repo.load_rotation_states("unionmonthly")), 3)

    def test_upsert_rotation_state_partial_update(self):
        # 新規行(全フィールド指定)
        self.repo.upsert_rotation_state(
            "unionmonthly",
            "tokyo",
            known_total=10,
            last_full_ok_at="2026-09-01T03:00:00",
            last_run_at="2026-09-01T03:00:00",
        )
        # 部分更新: known_total は触らない
        self.repo.upsert_rotation_state(
            "unionmonthly", "tokyo", last_run_at="2026-09-07T04:00:00"
        )
        states = self.repo.load_rotation_states("unionmonthly")
        self.assertEqual(len(states), 1)
        row = states[0]
        self.assertEqual(row["known_total"], 10)
        # timestamptz 化 (Phase 6c) で aware JST datetime が返る
        self.assertEqual(row["last_full_ok_at"].isoformat(), "2026-09-01T03:00:00+09:00")
        self.assertEqual(row["last_run_at"].isoformat(), "2026-09-07T04:00:00+09:00")

        # NULL-only での新規挿入も可能
        self.repo.upsert_rotation_state("unionmonthly", "gunma")
        by_slug = {
            s["prefecture_slug"]: s for s in self.repo.load_rotation_states("unionmonthly")
        }
        self.assertIsNone(by_slug["gunma"]["known_total"])
        self.assertIsNone(by_slug["gunma"]["last_full_ok_at"])
        self.assertIsNone(by_slug["gunma"]["last_run_at"])
        self.assertIsNotNone(by_slug["gunma"]["updated_at"])

    def test_rotation_usage_today_counts_only_rotation_runs(self):
        now = datetime(2026, 9, 7, 15, 0, 0)
        rows = [
            # (source_site, started_at, detail_ok, is_rotation)
            ("unionmonthly", "2026-09-07T01:00:00", 7, True),
            ("unionmonthly", "2026-09-07T02:00:00", 5, False),
            ("unionmonthly", "2026-09-06T23:00:00", 100, True),
            ("unionmonthly", "2026-09-07T04:00:00", 2, False),
            ("bratto", "2026-09-07T03:00:00", 3, True),
        ]
        conn = self.repo.connect()
        try:
            for source, started_at, detail_ok, is_rotation in rows:
                conn.execute(
                    """
                    INSERT INTO scrape_runs
                        (source_site, started_at, status, detail_ok, is_rotation)
                    VALUES (%s, %s, 'ok', %s, %s)
                    """,
                    (source, started_at, detail_ok, is_rotation),
                )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(self.repo.rotation_usage_today("unionmonthly", now=now), 7)
        self.assertEqual(self.repo.rotation_usage_today("bratto", now=now), 3)
        self.assertEqual(self.repo.rotation_usage_today("nosuch", now=now), 0)



    def test_running_scrape_targets_filters_finished_and_stale(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        # 稼働中 run(bratto): aichi=実行中, chiba=完了
        run_id = self.repo.start_scrape_run("bratto", meta={})
        t_aichi = self.repo.start_scrape_run_target(run_id, "bratto", "aichi")
        t_chiba = self.repo.start_scrape_run_target(run_id, "bratto", "chiba")
        self.repo.finish_scrape_run_target(t_chiba, status="ok", list_completed=True)

        # 完了済み run(unionmonthly): tokyo の target は unfinished でも親が完了 → 対象外
        done_run = self.repo.start_scrape_run("unionmonthly", meta={})
        t_tokyo = self.repo.start_scrape_run_target(done_run, "unionmonthly", "tokyo")
        self.repo.finish_scrape_run(done_run, status="ok")

        # クラッシュ放置の stale run(bratto, 13時間前に開始) → 時間窓で除外
        stale_run = self.repo.start_scrape_run("bratto", meta={})
        t_stale = self.repo.start_scrape_run_target(stale_run, "bratto", "saitama")
        old = (now - timedelta(hours=13)).isoformat()
        conn = self.repo.connect()
        try:
            conn.execute(
                "UPDATE scrape_run_targets SET started_at = %s WHERE id = %s", (old, t_stale)
            )
            conn.execute(
                "UPDATE scrape_runs SET started_at = %s WHERE id = %s", (old, stale_run)
            )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(self.repo.running_scrape_targets("bratto"), {"aichi"})
        self.assertEqual(self.repo.running_scrape_targets("unionmonthly"), set())
        self.assertEqual(self.repo.running_scrape_targets("nosuch"), set())

        # aichi が完了すれば running は空になる
        self.repo.finish_scrape_run_target(t_aichi, status="ok", list_completed=True)
        self.assertEqual(self.repo.running_scrape_targets("bratto"), set())
        self.repo.finish_scrape_run(run_id, status="ok")

    def test_fail_stale_running_runs_closes_interrupted_rows(self):
        # プロセス再起動の残骸(running + finished_at NULL)を aborted に打ち切る
        stale_run = self.repo.start_scrape_run("unionmonthly", meta={})
        t_stale = self.repo.start_scrape_run_target(stale_run, "unionmonthly", "saitama")
        # 同一 run 内で完了済みの target は触らない
        t_done = self.repo.start_scrape_run_target(stale_run, "unionmonthly", "tokyo")
        self.repo.finish_scrape_run_target(t_done, status="ok", list_completed=True)

        # 戻り値は aborted 行の合算 (scrape_run_targets 1件 + scrape_runs 1件)
        aborted_rows = self.repo.fail_stale_running_runs()
        self.assertEqual(aborted_rows, 2)

        # 残骸行は finished_at が入って aborted になり、is_running の元も消える
        self.assertEqual(self.repo.running_scrape_targets("unionmonthly"), set())
        conn = self.repo.connect()
        try:
            run = conn.execute(
                "SELECT status, finished_at, error_summary FROM scrape_runs WHERE id = %s",
                (stale_run,),
            ).fetchone()
            self.assertEqual(run["status"], "aborted")
            self.assertIsNotNone(run["finished_at"])
            self.assertIn("aborted", run["error_summary"])
            tgt = conn.execute(
                "SELECT status, finished_at FROM scrape_run_targets WHERE id = %s",
                (t_stale,),
            ).fetchone()
            self.assertEqual(tgt["status"], "aborted")
            self.assertIsNotNone(tgt["finished_at"])
            done = conn.execute(
                "SELECT status, finished_at FROM scrape_run_targets WHERE id = %s",
                (t_done,),
            ).fetchone()
            self.assertEqual(done["status"], "ok")
        finally:
            conn.close()

        # 再実行しても何もしない(冪等)
        self.assertEqual(self.repo.fail_stale_running_runs(), 0)

    def test_bump_rotation_failures_inserts_and_increments(self):
        # 行が無い状態からの bump は挿入して1
        self.repo.bump_rotation_failures(
            "unionmonthly", "saitama", last_run_at="2026-09-07T05:00:00"
        )
        self.repo.bump_rotation_failures(
            "unionmonthly", "saitama", last_run_at="2026-09-07T17:00:00"
        )
        self.repo.bump_rotation_failures(
            "unionmonthly", "saitama", last_run_at="2026-09-08T05:00:00"
        )
        row = {
            s["prefecture_slug"]: s
            for s in self.repo.load_rotation_states("unionmonthly")
        }["saitama"]
        self.assertEqual(row["consecutive_failures"], 3)
        self.assertEqual(row["last_run_at"].isoformat(), "2026-09-08T05:00:00+09:00")
        self.assertIsNone(row["last_full_ok_at"])

        # 成功時の upsert で連続失敗は0にリセットされる
        self.repo.upsert_rotation_state(
            "unionmonthly",
            "saitama",
            known_total=539,
            last_full_ok_at="2026-09-08T17:30:00",
            last_run_at="2026-09-08T17:30:00",
            consecutive_failures=0,
        )
        row = {
            s["prefecture_slug"]: s
            for s in self.repo.load_rotation_states("unionmonthly")
        }["saitama"]
        self.assertEqual(row["consecutive_failures"], 0)
        self.assertEqual(row["known_total"], 539)

