#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""価格履歴破損値ガードのSSOT化を検証する.

- 帯域定数 (0.25x〜4x): Python 側 _guard_price_history と SQL 側 _trend_ctes の
  guarded CTE が同一の PRICE_GUARD_MIN_RATIO / PRICE_GUARD_MAX_RATIO を参照する
- ref フォールバック (参照値無効時 = 系列の正値中央値): 規則の唯一実装は
  Python 側 fallback_ref() で、SQL 側は temp table 経由で値を受け取るだけ。
  詳細API (Python) とトレンドAPI (SQL) の保持/除外が同一物件系列で一致する
  parity を契約として固定する
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from helpers import ScopedDb, insert_snapshot, make_draft
from store.queries import price_history  # noqa: E402
from store.repository import Repository, open_connection


def _snap(v, scraped_at="2026-01-01T00:00:00", monthly=30000):
    """_guard_price_history の入力契約どおりのスナップ行を組み立てる."""
    return {
        "scraped_at": scraped_at,
        "catalog_rent_per_day_yen": v,
        "min_discounted_monthly_total_yen": monthly,
    }


class GuardBandConstantsTest(unittest.TestCase):
    """帯域定数と guarded CTE への反映."""

    def test_band_values(self):
        self.assertEqual(price_history.PRICE_GUARD_MIN_RATIO, 0.25)
        self.assertEqual(price_history.PRICE_GUARD_MAX_RATIO, 4.0)

    def test_trend_ctes_embeds_band_values(self):
        # _trend_ctes の生成 SQL が SSOT 定数の値を埋め込むこと
        # (Python / SQL 双方が同じ定数を参照する保証)
        for prefecture in (False, True):
            with self.subTest(prefecture=prefecture):
                sql = price_history._trend_ctes(prefecture)
                self.assertIn(str(price_history.PRICE_GUARD_MIN_RATIO), sql)  # "0.25"
                self.assertIn(str(price_history.PRICE_GUARD_MAX_RATIO), sql)  # "4.0"

    def test_trend_ctes_guard_condition_structure(self):
        # guarded CTE の WHERE が「参照値 IS NOT NULL / v > 0 / 下限 / 上限」
        # の 4 条件を保つ (リテラル手写し時代と同一条件)
        sql = price_history._trend_ctes(False)
        guarded = sql.split("guarded AS (", 1)[1]
        self.assertIn("COALESCE(NULLIF(b.ref, 0), fb.ref) IS NOT NULL", guarded)
        self.assertIn("b.v > 0", guarded)
        self.assertIn("b.v >= 0.25 * COALESCE(NULLIF(b.ref, 0), fb.ref)", guarded)
        self.assertIn("b.v <= 4.0 * COALESCE(NULLIF(b.ref, 0), fb.ref)", guarded)
        # フォールバック値は temp table 経由でのみ受け取り、SQL 側に中央値 /
        # 平均の計算式を持たない (規則の SSOT は Python fallback_ref)
        self.assertIn("LEFT JOIN guard_fallback fb ON fb.property_id = b.property_id", guarded)
        self.assertNotIn("own_avg", sql)


class FallbackRefTest(unittest.TestCase):
    """fallback_ref: 参照値無効時の代替参照値 = 系列正値の中央値."""

    def test_odd_count_returns_middle_value(self):
        self.assertEqual(price_history.fallback_ref([300, 100, 200]), 200)

    def test_even_count_returns_mean_of_middle_two(self):
        # statistics.median と同じ (偶数件は中央2件の平均)
        self.assertEqual(price_history.fallback_ref([50, 400, 400, 2000]), 400)

    def test_no_positive_returns_none(self):
        self.assertIsNone(price_history.fallback_ref([0, None, -10]))

    def test_ignores_non_positive_values(self):
        # 破損低値 (0 / 負) は母集団から除外される
        self.assertEqual(price_history.fallback_ref([0, 100, 300]), 200)


class GuardBandBoundaryTest(unittest.TestCase):
    """_guard_price_history の帯域端挙動 (ref=100)."""

    REF = 100

    def test_boundary_values(self):
        cases = [
            (24, False),  # 下限未満 → 除外
            (25, True),  # 下限ちょうど → 保持
            (399, True),  # 上限以内 → 保持
            (401, False),  # 上限超過 → 除外
            (0, False),  # 0 → 除外
            (-10, False),  # 負値 → 除外
            (None, False),  # 欠損 → 除外
        ]
        for v, keep in cases:
            with self.subTest(v=v):
                guarded, meta = price_history._guard_price_history([_snap(v)], self.REF)
                if keep:
                    self.assertEqual(len(guarded), 1)
                    self.assertEqual(meta["dropped_count"], 0)
                else:
                    self.assertEqual(guarded, [])
                    self.assertEqual(meta["dropped_count"], 1)

    def test_boundary_exact_upper_limit(self):
        # 上限ちょうど (4.0 * 100 = 400) も保持
        guarded, meta = price_history._guard_price_history([_snap(400)], self.REF)
        self.assertEqual(len(guarded), 1)
        self.assertEqual(meta["dropped_count"], 0)


class GuardMetaTest(unittest.TestCase):
    """メタ情報と出力行の形."""

    def test_dropped_count_and_meta(self):
        rows = [
            _snap(50, scraped_at="2026-01-01T00:00:00"),
            _snap(100, scraped_at="2026-01-02T00:00:00"),
            _snap(1, scraped_at="2026-01-03T00:00:00"),  # 低値破損
            _snap(99999, scraped_at="2026-01-04T00:00:00"),  # 高値破損
        ]
        guarded, meta = price_history._guard_price_history(rows, 100)
        self.assertEqual(len(guarded), 2)
        self.assertEqual(meta["total_count"], 4)
        self.assertEqual(meta["dropped_count"], 2)
        self.assertEqual(meta["first_at"], "2026-01-01T00:00:00")
        self.assertEqual(meta["last_at"], "2026-01-02T00:00:00")

    def test_output_row_shape(self):
        # 出力行は入力契約どおり 3 キー (scraped_at / 日額 / 月額合計)
        guarded, _meta = price_history._guard_price_history(
            [_snap(100, monthly=25000)], 100
        )
        self.assertEqual(
            list(guarded[0].keys()),
            [
                "scraped_at",
                "min_discounted_daily_rent_yen",
                "min_discounted_monthly_total_yen",
            ],
        )
        self.assertEqual(guarded[0]["min_discounted_daily_rent_yen"], 100)
        self.assertEqual(guarded[0]["min_discounted_monthly_total_yen"], 25000)


class GuardFallbackParityTest(unittest.TestCase):
    """詳細API (Python) とトレンドAPI (SQL) のガード parity 契約.

    ref フォールバックの規則 (系列正値の中央値) は Python fallback_ref() のみに
    存在し、SQL 側は temp table 経由で値を受け取る。同一フィクスチャで双方の
    保持/除外判定が一致すること (配線と NULL 処理の正しさ) を固定する。
    """

    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("price-guard-parity")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        # ref 有効 (フォールバック不使用) と、無効の3形態:
        # NULL (プラン無し draft) / 0 (NULLIF 経路) / NULL かつ正値スナップ無し
        cls.ok_id = repo.upsert_property(make_draft("guard-ok"))
        cls.fb1_id = repo.upsert_property(make_draft("guard-fb-null"))
        cls.fb2_id = repo.upsert_property(make_draft("guard-fb-zero"))
        cls.empty_id = repo.upsert_property(make_draft("guard-fb-empty"))

        conn = repo.connect()
        try:
            # upsert 時に自動生成されるスナップショットを消して検証用系列を置く
            conn.execute("DELETE FROM property_snapshots")
            conn.execute(
                "UPDATE properties SET catalog_rent_per_day_yen = 300 WHERE id = %s",
                (cls.ok_id,),
            )
            conn.execute(
                "UPDATE properties SET catalog_rent_per_day_yen = 0 WHERE id = %s",
                (cls.fb2_id,),
            )
            base = datetime.now()
            hours = iter(range(3, 1000, 3))

            def _snap(pid: int, value):
                scraped_at = (base - timedelta(hours=next(hours))).isoformat(
                    timespec="seconds"
                )
                insert_snapshot(conn, pid, scraped_at, value)

            # ok-1: ref=300, 帯域 [75, 1200] → 50 / 2000 は破損として除外 (2件保持)
            for v in (50, 300, 300, 2000):
                _snap(cls.ok_id, v)
            # fb-1: ref NULL → 系列中央値 400, 帯域 [100, 1600] (2件保持)。
            # 旧 own_avg 規則 (平均 712.5, 帯域 [178, 2850]) だと 2000 が残るため
            # 中央値統一を pin するフィクスチャ
            for v in (50, 400, 400, 2000):
                _snap(cls.fb1_id, v)
            # fb-2: ref=0 → 系列中央値 200 (奇数件), 帯域 [50, 800] (3件保持)
            for v in (100, 200, 300):
                _snap(cls.fb2_id, v)
            # fb-empty: ref NULL かつ正値スナップ無し → 代替参照値なしで全除外
            for v in (0, None):
                _snap(cls.empty_id, v)
            conn.commit()
        finally:
            conn.close()

    def _python_kept_by_property(self, conn):
        """詳細APIと同一手順 (_guard_price_history) での保持集合を物件別に返す."""
        kept = {}
        for pid in (self.ok_id, self.fb1_id, self.fb2_id, self.empty_id):
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT scraped_at, catalog_rent_per_day_yen, "
                    "min_discounted_monthly_total_yen "
                    "FROM property_snapshots WHERE property_id = %s "
                    "ORDER BY scraped_at ASC",
                    (pid,),
                )
            ]
            ref = conn.execute(
                "SELECT catalog_rent_per_day_yen FROM properties WHERE id = %s",
                (pid,),
            ).fetchone()[0]
            guarded, _meta = price_history._guard_price_history(rows, ref)
            kept[pid] = {(pid, g["scraped_at"]) for g in guarded}
        return kept

    def test_guarded_cte_matches_python_guard_per_row(self):
        cutoff = (datetime.now() - timedelta(days=90)).date().isoformat()
        with open_connection() as conn:
            price_history._load_guard_fallbacks(conn)
            sql_rows = conn.execute(
                price_history._trend_ctes(False)
                + "\nSELECT property_id, scraped_at FROM guarded "
                "ORDER BY property_id, scraped_at",
                (cutoff,),
            ).fetchall()
        sql_kept = {(r["property_id"], r["scraped_at"]) for r in sql_rows}

        with open_connection() as conn:
            expected = self._python_kept_by_property(conn)
        union = set().union(*expected.values())

        self.assertEqual(sql_kept, union)
        # フィクスチャの内訳 (旧 own_avg 規則では fb-1 が 3 件になり不一致)
        self.assertEqual(len(expected[self.ok_id]), 2)
        self.assertEqual(len(expected[self.fb1_id]), 2)
        self.assertEqual(len(expected[self.fb2_id]), 3)
        self.assertEqual(len(expected[self.empty_id]), 0)

    def test_get_price_trend_meta_matches_python_guard(self):
        # 公開入口経由でも temp table の配線 (接続内生成 → guarded CTE 参照)
        # が崩れていないことを meta 集計で検証する
        result = price_history.get_price_trend(days=90)
        cutoff = (datetime.now() - timedelta(days=90)).date().isoformat()
        with open_connection() as conn:
            expected = self._python_kept_by_property(conn)
            base_count = conn.execute(
                "SELECT COUNT(*) FROM property_snapshots WHERE scraped_at >= %s",
                (cutoff,),
            ).fetchone()[0]

        total = sum(len(v) for v in expected.values())
        self.assertEqual(result["meta"]["snapshot_rows"], base_count)
        self.assertEqual(result["meta"]["guarded_rows"], total)
        self.assertEqual(result["meta"]["excluded_rows"], base_count - total)


if __name__ == "__main__":
    unittest.main()
