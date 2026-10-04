#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for store.schema / store.repository (v2)."""

import json
import os
import sqlite3
import tempfile
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
        self.assertEqual(self.repo.get_property(pid_a)["is_active"], 1)
        self.assertEqual(self.repo.get_property(pid_b)["is_active"], 0)

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
    _OLD_SRT_DDL = """
        CREATE TABLE scrape_run_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            source_site TEXT NOT NULL,
            target_key TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            list_pages INTEGER DEFAULT 0,
            list_items INTEGER DEFAULT 0,
            detail_ok INTEGER DEFAULT 0,
            detail_fail INTEGER DEFAULT 0,
            error_summary TEXT,
            FOREIGN KEY(run_id) REFERENCES scrape_runs(id) ON DELETE CASCADE
        );
    """

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
        self.assertEqual(row["last_full_ok_at"], "2026-09-01T03:00:00")
        self.assertEqual(row["last_run_at"], "2026-09-07T04:00:00")

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
            # (source_site, started_at, detail_ok, meta_json)
            ("unionmonthly", "2026-09-07T01:00:00", 7, json.dumps({"rotation": True})),
            ("unionmonthly", "2026-09-07T02:00:00", 5, json.dumps({"rotation": False})),
            ("unionmonthly", "2026-09-06T23:00:00", 100, json.dumps({"rotation": True})),
            ("unionmonthly", "2026-09-07T04:00:00", 2, None),
            ("bratto", "2026-09-07T03:00:00", 3, '{"rotation": true}'),
        ]
        conn = self.repo.connect()
        try:
            for source, started_at, detail_ok, meta in rows:
                conn.execute(
                    """
                    INSERT INTO scrape_runs (source_site, started_at, status, detail_ok, meta_json)
                    VALUES (?, ?, 'ok', ?, ?)
                    """,
                    (source, started_at, detail_ok, meta),
                )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(self.repo.rotation_usage_today("unionmonthly", now=now), 7)
        self.assertEqual(self.repo.rotation_usage_today("bratto", now=now), 3)
        self.assertEqual(self.repo.rotation_usage_today("nosuch", now=now), 0)

    def test_init_schema_migrates_list_completed(self):
        # 旧スキーマ(list_completed 列なし)で DB を作る
        conn = self.repo.connect()
        try:
            conn.execute("DROP TABLE scrape_run_targets")
            conn.execute(self._OLD_SRT_DDL)
            conn.commit()
        finally:
            conn.close()

        # init_schema で列が追加される
        self.repo.init_db()
        conn = self.repo.connect()
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(scrape_run_targets)")]
        finally:
            conn.close()
        self.assertIn("list_completed", cols)

        # 冪等: 2回実行してもエラーにならず列は1つのまま
        self.repo.init_db()
        conn = self.repo.connect()
        try:
            cols2 = [r[1] for r in conn.execute("PRAGMA table_info(scrape_run_targets)")]
        finally:
            conn.close()
        self.assertEqual(cols2.count("list_completed"), 1)

        # 追加された列で finish が動く
        run_id = self.repo.start_scrape_run("unionmonthly")
        tid = self.repo.start_scrape_run_target(run_id, "unionmonthly", "tokyo")
        self.repo.finish_scrape_run_target(tid, status="ok", list_completed=True)

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
                "UPDATE scrape_run_targets SET started_at = ? WHERE id = ?", (old, t_stale)
            )
            conn.execute(
                "UPDATE scrape_runs SET started_at = ? WHERE id = ?", (old, stale_run)
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

        aborted_runs = self.repo.fail_stale_running_runs()
        self.assertEqual(aborted_runs, 1)

        # 残骸行は finished_at が入って aborted になり、is_running の元も消える
        self.assertEqual(self.repo.running_scrape_targets("unionmonthly"), set())
        conn = self.repo.connect()
        try:
            run = conn.execute(
                "SELECT status, finished_at, error_summary FROM scrape_runs WHERE id = ?",
                (stale_run,),
            ).fetchone()
            self.assertEqual(run["status"], "aborted")
            self.assertIsNotNone(run["finished_at"])
            self.assertIn("aborted", run["error_summary"])
            tgt = conn.execute(
                "SELECT status, finished_at FROM scrape_run_targets WHERE id = ?",
                (t_stale,),
            ).fetchone()
            self.assertEqual(tgt["status"], "aborted")
            self.assertIsNotNone(tgt["finished_at"])
            done = conn.execute(
                "SELECT status, finished_at FROM scrape_run_targets WHERE id = ?",
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
        self.assertEqual(row["last_run_at"], "2026-09-08T05:00:00")
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

    def test_init_schema_migrates_consecutive_failures(self):
        # 旧スキーマ(consecutive_failures 列なし)の rotation_state を作る
        conn = self.repo.connect()
        try:
            conn.execute("DROP TABLE rotation_state")
            conn.execute(
                """
                CREATE TABLE rotation_state (
                    source_site TEXT NOT NULL,
                    prefecture_slug TEXT NOT NULL,
                    known_total INTEGER,
                    last_full_ok_at TEXT,
                    last_run_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_site, prefecture_slug)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO rotation_state
                    (source_site, prefecture_slug, known_total, updated_at)
                VALUES ('bratto', 'tokyo', 464, '2026-09-07T00:00:00')
                """
            )
            conn.commit()
        finally:
            conn.close()

        # init_schema で列が追加され、既存行はデフォルト0
        self.repo.init_db()
        conn = self.repo.connect()
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(rotation_state)")]
            rows = conn.execute(
                "SELECT consecutive_failures FROM rotation_state"
                " WHERE source_site='bratto' AND prefecture_slug='tokyo'"
            ).fetchall()
        finally:
            conn.close()
        self.assertIn("consecutive_failures", cols)
        self.assertEqual([r[0] for r in rows], [0])

        # 追加された列で bump が動く
        self.repo.bump_rotation_failures("bratto", "tokyo", last_run_at="2026-09-07T05:00:00")
        row = {
            s["prefecture_slug"]: s for s in self.repo.load_rotation_states("bratto")
        }["tokyo"]
        self.assertEqual(row["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
