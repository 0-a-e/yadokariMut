#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rotation planner: batch selection and result recording."""

from __future__ import annotations

import unittest
from datetime import datetime


from ingest.pipeline import TargetIngestResult
from ingest.rotation import RotationPlanner


class FakeRepository:
    """Dict-based stand-in for the Repository rotation-state API."""

    def __init__(self, usage=None):
        self._states = {}
        self._usage = dict(usage or {})
        self.seeded = []

    def seed_rotation_state(self, source_site, pref_catalog):
        self.seeded.append((source_site, list(pref_catalog)))
        for slug in pref_catalog:
            self._states.setdefault(
                (source_site, slug),
                {
                    "prefecture_slug": slug,
                    "known_total": None,
                    "last_full_ok_at": None,
                    "last_run_at": None,
                    "consecutive_failures": 0,
                    "updated_at": None,
                },
            )

    def load_rotation_states(self, source_site):
        return [
            dict(row)
            for (site, _slug), row in sorted(self._states.items())
            if site == source_site
        ]

    def rotation_usage_today(self, source_site, now=None):
        return self._usage.get(source_site, 0)

    def bump_rotation_failures(self, source_site, prefecture_slug, *, last_run_at=None):
        row = self._states.setdefault(
            (source_site, prefecture_slug),
            {
                "prefecture_slug": prefecture_slug,
                "known_total": None,
                "last_full_ok_at": None,
                "last_run_at": None,
                "consecutive_failures": 0,
                "updated_at": None,
            },
        )
        row["consecutive_failures"] = int(row.get("consecutive_failures") or 0) + 1
        if last_run_at is not None:
            row["last_run_at"] = last_run_at
        row["updated_at"] = last_run_at

    def upsert_rotation_state(
        self,
        source_site,
        prefecture_slug,
        *,
        known_total=None,
        last_full_ok_at=None,
        last_run_at=None,
        consecutive_failures=None,
    ):
        key = (source_site, prefecture_slug)
        row = self._states.setdefault(
            key,
            {
                "prefecture_slug": prefecture_slug,
                "known_total": None,
                "last_full_ok_at": None,
                "last_run_at": None,
                "consecutive_failures": 0,
                "updated_at": None,
            },
        )
        if known_total is not None:
            row["known_total"] = known_total
        if last_full_ok_at is not None:
            row["last_full_ok_at"] = last_full_ok_at
        if last_run_at is not None:
            row["last_run_at"] = last_run_at
        if consecutive_failures is not None:
            row["consecutive_failures"] = consecutive_failures
        row["updated_at"] = last_run_at

    # -- test helpers ------------------------------------------------------

    def set_state(
        self,
        source_site,
        prefecture_slug,
        *,
        known_total=None,
        last_full_ok_at=None,
        last_run_at=None,
        consecutive_failures=0,
    ):
        self._states[(source_site, prefecture_slug)] = {
            "prefecture_slug": prefecture_slug,
            "known_total": known_total,
            "last_full_ok_at": last_full_ok_at,
            "last_run_at": last_run_at,
            "consecutive_failures": consecutive_failures,
            "updated_at": None,
        }

    def get_state(self, source_site, prefecture_slug):
        return self._states.get((source_site, prefecture_slug))


class RotationPlannerPlanTest(unittest.TestCase):
    SOURCE = "bratto"

    def _plan(self, repo, catalog, daily_limit=500, default_est=60, now=None):
        planner = RotationPlanner(repo)
        return planner.plan(
            self.SOURCE,
            pref_catalog=catalog,
            daily_limit=daily_limit,
            default_est=default_est,
            now=now,
        )

    def test_small_prefs_packed_first(self):
        """1. 全県未取得状態で小さい県から詰め込まれる。"""
        repo = FakeRepository()
        for slug, known in [
            ("tokyo", 300),
            ("osaka", 100),
            ("chiba", 50),
            ("saitama", 80),
            ("kanagawa", 200),
        ]:
            repo.set_state(self.SOURCE, slug, known_total=known)

        batch = self._plan(
            repo, ["tokyo", "osaka", "chiba", "saitama", "kanagawa"], daily_limit=500
        )

        self.assertEqual(batch.prefs, ["chiba", "saitama", "osaka", "kanagawa"])
        self.assertEqual(batch.est_items, 430)
        self.assertFalse(batch.unlimited)
        self.assertEqual(batch.reason, "")

    def test_too_large_pref_skipped_smaller_selected(self):
        """2. 予算に収まらない県はスキップされ、後続の小さい県が選ばれる。"""
        repo = FakeRepository()
        repo.set_state(self.SOURCE, "a", known_total=100)
        repo.set_state(self.SOURCE, "big", known_total=250)
        repo.set_state(self.SOURCE, "c", known_total=150)

        batch = self._plan(repo, ["a", "big", "c"], daily_limit=300)

        self.assertNotIn("big", batch.prefs)
        self.assertEqual(batch.prefs, ["a", "c"])
        self.assertEqual(batch.est_items, 250)

    def test_single_pref_over_limit(self):
        """3. 先頭県が単体で予算超過なら1県だけ unlimited で選ばれる。"""
        repo = FakeRepository()
        repo.set_state(self.SOURCE, "tokyo", known_total=800)
        repo.set_state(self.SOURCE, "osaka", known_total=900)

        batch = self._plan(repo, ["osaka", "tokyo"], daily_limit=500)

        self.assertEqual(batch.prefs, ["tokyo"])
        self.assertTrue(batch.unlimited)
        self.assertEqual(batch.reason, "single_pref_over_limit")
        self.assertEqual(batch.est_items, 0)

    def test_head_over_limit_not_starved_by_small_pref(self):
        """3b. 先頭県が予算超過のとき、収まる小さい県があっても先頭を単独優先(飽和防止)。

        旧実装は「収まらない県はスキップして小さい県を詰め込む」だけだったため、
        常に予算に収まる小県(例: 茨城2件)が再取得され続け、大きい県が永遠に
        選ばれない飽和(starvation)が起き得た。
        """
        repo = FakeRepository()
        repo.set_state(self.SOURCE, "saitama", known_total=539, last_full_ok_at=None)
        repo.set_state(
            self.SOURCE,
            "ibaraki",
            known_total=2,
            last_full_ok_at=datetime(2026, 9, 7, 8, 45),
        )

        batch = self._plan(repo, ["saitama", "ibaraki"], daily_limit=500)

        self.assertEqual(batch.prefs, ["saitama"])
        self.assertTrue(batch.unlimited)
        self.assertEqual(batch.reason, "single_pref_over_limit")
        self.assertNotIn("ibaraki", batch.prefs)


class RotationPlannerFailureBackoffTest(unittest.TestCase):
    """連続失敗した県のクールダウン抑止(恒常失敗による停滞の緩和)."""

    SOURCE = "unionmonthly"

    def _plan(self, repo, catalog, **kw):
        return RotationPlanner(repo).plan(
            self.SOURCE, pref_catalog=catalog, daily_limit=kw.pop("daily_limit", 500),
            **kw,
        )

    def test_failing_pref_suppressed_and_others_progress(self):
        """8a. 連続失敗3回+直近試行の県は選択から除外され、他県が前進する。"""
        now = datetime(2026, 9, 7, 17, 0, 0)
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "saitama", known_total=539, last_full_ok_at=None,
            last_run_at=datetime(2026, 9, 7, 16, 0, 0), consecutive_failures=3,
        )
        repo.set_state(self.SOURCE, "chiba", known_total=692)
        repo.set_state(self.SOURCE, "ibaraki", known_total=2)

        batch = self._plan(repo, ["saitama", "chiba", "ibaraki"], now=now)

        self.assertNotIn("saitama", batch.prefs)
        self.assertIn("ibaraki", batch.prefs)
        self.assertNotIn("chiba", batch.prefs)  # 692 > 残予算なので単独扱いは chiba が先頭でなく ibaraki を詰め込み
        self.assertFalse(batch.unlimited)

    def test_suppressed_over_limit_head_defers_to_next_eligible(self):
        """8b. 抑止県が予算超過の先頭でも、次の適格県が単独取得される。"""
        now = datetime(2026, 9, 7, 17, 0, 0)
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "tokyo", known_total=2891,
            last_run_at=datetime(2026, 9, 7, 16, 0, 0), consecutive_failures=5,
        )
        repo.set_state(self.SOURCE, "saitama", known_total=539)

        batch = self._plan(repo, ["tokyo", "saitama"], now=now)

        self.assertEqual(batch.prefs, ["saitama"])
        self.assertTrue(batch.unlimited)
        self.assertEqual(batch.reason, "single_pref_over_limit")

    def test_cooldown_elapsed_pref_is_eligible_again(self):
        """8c. クールダウン(48h)経過後は再試行対象に戻る。"""
        now = datetime(2026, 9, 10, 17, 0, 0)
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "saitama", known_total=539,
            last_run_at=datetime(2026, 9, 8, 16, 0, 0),  # 49時間前
            consecutive_failures=3,
        )

        batch = self._plan(repo, ["saitama"], now=now)

        self.assertEqual(batch.prefs, ["saitama"])
        self.assertTrue(batch.unlimited)

    def test_all_prefs_suppressed_returns_empty(self):
        """8d. 全県が抑止中の場合は空バッチ+reason。"""
        now = datetime(2026, 9, 7, 17, 0, 0)
        repo = FakeRepository()
        for slug in ("tokyo", "saitama"):
            repo.set_state(
                self.SOURCE, slug, known_total=100,
                last_run_at=datetime(2026, 9, 7, 16, 0, 0), consecutive_failures=3,
            )

        batch = self._plan(repo, ["tokyo", "saitama"], now=now)

        self.assertEqual(batch.prefs, [])
        self.assertEqual(batch.reason, "all_prefs_in_failure_cooldown")

    def test_record_failure_increments_and_success_resets(self):
        """8e. 失敗は連続失敗カウンタを増やし、成功は0に戻す。"""
        repo = FakeRepository()
        repo.set_state(self.SOURCE, "saitama", known_total=539, consecutive_failures=2)
        planner = RotationPlanner(repo)

        planner.record_result(
            self.SOURCE,
            {"saitama": TargetIngestResult(
                target_key="saitama", prefecture_slug="saitama",
                list_items=0, list_completed=False, status="error")},
        )
        self.assertEqual(repo.get_state(self.SOURCE, "saitama")["consecutive_failures"], 3)

        planner.record_result(
            self.SOURCE,
            {"saitama": TargetIngestResult(
                target_key="saitama", prefecture_slug="saitama",
                list_items=539, list_completed=True, status="ok")},
        )
        self.assertEqual(repo.get_state(self.SOURCE, "saitama")["consecutive_failures"], 0)

    def test_daily_budget_exhausted(self):
        """4. 当日使用済みが上限以上なら空バッチ+reason。"""
        repo = FakeRepository(usage={self.SOURCE: 500})
        repo.set_state(self.SOURCE, "chiba", known_total=50)

        batch = self._plan(repo, ["chiba"], daily_limit=500)
        self.assertEqual(batch.prefs, [])
        self.assertEqual(batch.reason, "daily_budget_exhausted")
        self.assertFalse(batch.unlimited)

        repo = FakeRepository(usage={self.SOURCE: 600})
        batch = self._plan(repo, ["chiba"], daily_limit=500)
        self.assertEqual(batch.prefs, [])
        self.assertEqual(batch.reason, "daily_budget_exhausted")

    def test_stale_and_nulls_first_priority(self):
        """5. last_full_ok_at が古い/未取得(NULL)の県が優先される。"""
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "never", known_total=100, last_full_ok_at=None
        )
        repo.set_state(
            self.SOURCE, "old", known_total=100, last_full_ok_at=datetime(2026, 8, 1)
        )
        repo.set_state(
            self.SOURCE, "tie_b", known_total=100, last_full_ok_at=datetime(2026, 8, 15)
        )
        repo.set_state(
            self.SOURCE, "tie_a", known_total=200, last_full_ok_at=datetime(2026, 8, 15)
        )
        repo.set_state(
            self.SOURCE, "new", known_total=100, last_full_ok_at=datetime(2026, 9, 1)
        )

        batch = self._plan(
            repo,
            ["new", "tie_a", "old", "tie_b", "never"],
            daily_limit=10000,
        )

        # NULLS FIRST → 古い順 → 同一時刻は known_total 昇順
        self.assertEqual(batch.prefs, ["never", "old", "tie_b", "tie_a", "new"])


class RotationPlannerRecordTest(unittest.TestCase):
    SOURCE = "bratto"

    def test_record_result_updates_states(self):
        """6. ok+list_completed は全更新、それ以外は last_run_at のみ。"""
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "osaka", known_total=40, last_full_ok_at=datetime(2026, 1, 1)
        )
        planner = RotationPlanner(repo)

        by_target = {
            "tokyo": TargetIngestResult(
                target_key="tokyo",
                prefecture_slug="tokyo",
                list_items=320,
                list_completed=True,
                status="ok",
            ),
            "osaka": TargetIngestResult(
                target_key="osaka",
                prefecture_slug="osaka",
                list_items=50,
                list_completed=False,
                status="ok",
            ),
            "chiba": TargetIngestResult(
                target_key="chiba",
                prefecture_slug="chiba",
                list_items=70,
                list_completed=True,
                status="error",
            ),
            "kyoto": TargetIngestResult(
                target_key="kyoto",
                prefecture_slug=None,
                list_items=10,
                list_completed=False,
                status="ok",
            ),
        }
        planner.record_result(self.SOURCE, by_target)

        # ok & list_completed → known_total / last_full_ok_at / last_run_at 更新
        tokyo = repo.get_state(self.SOURCE, "tokyo")
        self.assertEqual(tokyo["known_total"], 320)
        self.assertTrue(tokyo["last_full_ok_at"])
        self.assertEqual(tokyo["last_full_ok_at"], tokyo["last_run_at"])

        # list_completed=False → last_run_at のみ
        osaka = repo.get_state(self.SOURCE, "osaka")
        self.assertEqual(osaka["known_total"], 40)
        self.assertEqual(osaka["last_full_ok_at"], datetime(2026, 1, 1))
        self.assertTrue(osaka["last_run_at"])

        # status=error → last_run_at のみ
        chiba = repo.get_state(self.SOURCE, "chiba")
        self.assertIsNone(chiba["known_total"])
        self.assertIsNone(chiba["last_full_ok_at"])
        self.assertTrue(chiba["last_run_at"])

        # prefecture_slug 未設定 → target_key を slug 代わりに使う
        kyoto = repo.get_state(self.SOURCE, "kyoto")
        self.assertIsNotNone(kyoto)
        self.assertTrue(kyoto["last_run_at"])

    def test_seed_adds_new_catalog_prefs(self):
        """7. seed で追加された新県が plan の対象に含まれる。"""
        repo = FakeRepository()
        repo.set_state(
            self.SOURCE, "a", known_total=100, last_full_ok_at=datetime(2026, 9, 1)
        )

        batch = RotationPlanner(repo).plan(
            self.SOURCE,
            pref_catalog=["a", "b_new"],
            daily_limit=500,
        )

        self.assertIn("b_new", batch.prefs)
        # 新県は NULL 状態なので最優先(default_est コスト)
        self.assertEqual(batch.prefs[0], "b_new")
        self.assertEqual(repo.seeded, [(self.SOURCE, ["a", "b_new"])])
        self.assertIsNotNone(repo.get_state(self.SOURCE, "b_new"))


if __name__ == "__main__":
    unittest.main()
