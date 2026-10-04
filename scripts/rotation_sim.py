#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ローテーションプランナーの飽和/偏り検証シミュレーション (Q2調査用).

実 RotationPlanner + Fake リポジトリで複数日のスロット(12時間おき×2/日)を回し、
- 全県が周期内に取得されるか (liveness)
- 超過県のみが取得され続けないか (逆飽和)
- 複数の超過県がある場合の挙動
- 先頭県が連続失敗した場合の挙動
を確認する。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ingest.pipeline import TargetIngestResult
from ingest.rotation import RotationPlanner

SRC = "sim"


class SimRepo:
    def __init__(self, actual_counts):
        self._states = {}
        self._usage = {}  # (date_str) -> items
        self.actual = dict(actual_counts)

    def _new_row(self, slug):
        return {"prefecture_slug": slug, "known_total": None,
                "last_full_ok_at": None, "last_run_at": None,
                "consecutive_failures": 0, "updated_at": None}

    def seed_rotation_state(self, source_site, pref_catalog):
        for slug in pref_catalog:
            self._states.setdefault((source_site, slug), self._new_row(slug))

    def load_rotation_states(self, source_site):
        return [dict(v) for k, v in sorted(self._states.items()) if k[0] == source_site]

    def rotation_usage_today(self, source_site, now=None):
        return self._usage.get((source_site, now.strftime("%Y-%m-%d")), 0)

    def bump_rotation_failures(self, source_site, slug, *, last_run_at=None):
        row = self._states.setdefault((source_site, slug), self._new_row(slug))
        row["consecutive_failures"] = int(row.get("consecutive_failures") or 0) + 1
        if last_run_at is not None:
            row["last_run_at"] = last_run_at

    def upsert_rotation_state(self, source_site, slug, *, known_total=None,
                              last_full_ok_at=None, last_run_at=None,
                              consecutive_failures=None):
        row = self._states.setdefault((source_site, slug), self._new_row(slug))
        if known_total is not None:
            row["known_total"] = known_total
        if last_full_ok_at is not None:
            row["last_full_ok_at"] = last_full_ok_at
        if last_run_at is not None:
            row["last_run_at"] = last_run_at
        if consecutive_failures is not None:
            row["consecutive_failures"] = consecutive_failures

    def add_usage(self, now, items):
        k = (SRC, now.strftime("%Y-%m-%d"))
        self._usage[k] = self._usage.get(k, 0) + items


def run_sim(name, catalog, actual_counts, *, daily_limit=500, days=10,
            fail_prefs=(), initial_fresh=None, verbose=True):
    """スロットごとに plan → 実行(成功 or 失敗) → record を模擬。"""
    repo = SimRepo(actual_counts)
    planner = RotationPlanner(repo)
    t0 = datetime(2026, 9, 7, 5, 0, 0)
    if initial_fresh:
        for slug in initial_fresh:
            repo.upsert_rotation_state(SRC, slug, known_total=actual_counts[slug],
                                       last_full_ok_at=t0.isoformat(),
                                       last_run_at=t0.isoformat())
    history = {slug: [] for slug in catalog}
    log = []

    for slot in range(days * 2):
        now = t0 + timedelta(hours=12 * slot)
        batch = planner.plan(SRC, pref_catalog=catalog, daily_limit=daily_limit,
                             default_est=60, now=now)
        if not batch.prefs:
            log.append(f"{now:%m-%d %H:%M} slot{slot}: SKIP ({batch.reason})")
            continue
        tag = "SOLO(上限無視)" if batch.unlimited else "pack"
        log.append(f"{now:%m-%d %H:%M} slot{slot}: {tag} {batch.prefs} est={batch.est_items}")
        by_target = {}
        fetched = 0
        for slug in batch.prefs:
            if slug in fail_prefs:
                tr = TargetIngestResult(target_key=slug, prefecture_slug=slug,
                                        list_items=0, list_completed=False,
                                        status="error")
            else:
                n = repo.actual.get(slug, 0)
                fetched += n
                tr = TargetIngestResult(target_key=slug, prefecture_slug=slug,
                                        list_items=n, list_completed=True,
                                        status="ok")
                history[slug].append(now)
            by_target[slug] = tr
        # usage は rotation 実行の実績件数を全額計上
        repo.add_usage(now, fetched)
        planner.record_result(SRC, by_target, now=now)

    if verbose:
        print(f"=== {name} (daily_limit={daily_limit}, days={days}) ===")
        for line in log:
            print(" ", line)
    print("  取得履歴(回数, 初回, 最終):")
    for slug in catalog:
        h = history[slug]
        if h:
            print(f"    {slug:12s} {len(h)}回  初回={h[0]:%m-%d %H:%M}  最終={h[-1]:%m-%d %H:%M}")
        else:
            print(f"    {slug:12s} 0回  ★一度も取得されず")
    print()
    return history


# --- A: unionmonthly型 (複数の超過県 + 小県) --------------------------------
hist_a = run_sim(
    "A: unionmonthly型 (saitama539/chiba692/kanagawa1199/tokyo2891 が上限500超過 + ibaraki2)",
    catalog=["tokyo", "kanagawa", "chiba", "saitama", "ibaraki"],
    actual_counts={"tokyo": 2891, "kanagawa": 1199, "chiba": 692,
                   "saitama": 539, "ibaraki": 2},
    initial_fresh=["ibaraki"],
    days=12,
)

# --- B: 全県未取得・全県が上限超過の極端ケース ------------------------------
hist_b = run_sim(
    "B: 全県未取得・全県超過 (3県とも600〜900 > 上限500)",
    catalog=["a600", "b700", "c900"],
    actual_counts={"a600": 600, "b700": 700, "c900": 900},
    days=8,
)

# --- C: bratto型 (47県混在・tokyoのみ超過) ----------------------------------
bratto_counts = {}
slugs = ["hokkaido", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima",
         "ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa",
         "niigata", "toyama", "ishikawa", "fukui", "yamanashi", "nagano", "gifu",
         "shizuoka", "aichi", "mie", "shiga", "kyoto", "osaka", "hyogo", "nara",
         "wakayama", "tottori", "shimane", "okayama", "hiroshima", "yamaguchi",
         "tokushima", "kagawa", "ehime", "kochi", "fukuoka", "saga", "nagasaki",
         "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa"]
sizes = [16, 7, 7, 13, 4, 2, 2, 3, 2, 4, 12, 46, 800, 116, 2, 2, 7, 4, 2, 4, 13,
         16, 295, 8, 12, 53, 118, 51, 12, 21, 2, 1, 18, 8, 2, 2, 3, 1, 2, 52, 2,
         2, 5, 7, 3, 5, 1]
for s, n in zip(slugs, sizes):
    bratto_counts[s] = n
hist_c = run_sim(
    "C: bratto型47県 (tokyo800のみ上限超過・実勢に近い分布)",
    catalog=slugs, actual_counts=bratto_counts, days=7, verbose=False,
)

# --- D: 先頭県が連続失敗する場合 --------------------------------------------
hist_d = run_sim(
    "D: 先頭(saitama539)が恒常失敗するケース (fail=saitama)",
    catalog=["tokyo", "kanagawa", "chiba", "saitama", "ibaraki"],
    actual_counts={"tokyo": 2891, "kanagawa": 1199, "chiba": 692,
                   "saitama": 539, "ibaraki": 2},
    fail_prefs=("saitama",),
    days=6,
)

# --- 検証サマリ --------------------------------------------------------------
print("=== 検証サマリ ===")
for name, hist, days in [("A", hist_a, 12), ("B", hist_b, 8), ("C", hist_c, 7), ("D", hist_d, 6)]:
    never = [s for s, h in hist.items() if not h]
    once = sum(1 for h in hist.values() if h)
    print(f"  {name}: {days}日間で取得済み県 {once}/{len(hist)}"
          + (f"  ★未取得: {never}" if never else ""))
