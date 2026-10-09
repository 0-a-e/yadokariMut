#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析系APIのテスト (価格履歴の品質ガード + /api/analysis/price-trend)."""

import unittest


from fastapi.testclient import TestClient

from helpers import ScopedDb, insert_snapshot, make_tokyo_draft
from store.repository import Repository

# web_server はインポート時にエンドポイントを定義するのみ。
# DB パスは setUpClass で env 経由で差し替える(api_queries / Repository は呼び出し毎に env を読む)
from web_server import app


def _draft(source_site: str, external_id: str, rent: int):
    """本テスト専用の既定 (lat/lng 固定・municipality 未設定) を helpers に委譲する."""
    return make_tokyo_draft(
        external_id,
        source_site=source_site,
        lat=35.66,
        lng=139.70,
        rent_current_yen=rent,
        municipality=None,
    )


class TestPriceHistoryGuard(unittest.TestCase):
    """詳細APIの price_history に適用される品質ガード(0.25x〜4x 参照値比)."""

    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("analysis")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        cls.prop_id = repo.upsert_property(_draft("bratto", "guard-1", 5000))
        # upsert 時に自動生成されるスナップショットを消し、検証用の系列を手で置く
        conn = repo.connect()
        conn.execute("DELETE FROM property_snapshots")
        cur = conn.cursor()
        insert_snapshot(conn, cls.prop_id, "2026-08-01T10:00:00", 5000)
        insert_snapshot(conn, cls.prop_id, "2026-08-02T10:00:00", 4500)
        insert_snapshot(conn, cls.prop_id, "2026-08-02T18:00:00", 4600)
        insert_snapshot(conn, cls.prop_id, "2026-08-03T10:00:00", 300)  # v1.0 低値破損相当
        conn.commit()
        conn.close()
        cls.client = TestClient(app)

    def test_guard_drops_corrupt_rows(self):
        res = self.client.get(f"/api/properties/{self.prop_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        hist = data["price_history"]
        self.assertEqual(
            [p["min_discounted_daily_rent_yen"] for p in hist],
            [5000, 4500, 4600],
        )
        meta = data["price_history_meta"]
        self.assertEqual(meta["total_count"], 4)
        self.assertEqual(meta["dropped_count"], 1)
        # timestamptz 化 (Phase 6c) で +09:00 付き isoformat (D9-5)
        self.assertEqual(meta["first_at"], "2026-08-01T10:00:00+09:00")
        self.assertEqual(meta["last_at"], "2026-08-02T18:00:00+09:00")

    def test_guard_ref_fallback_to_series_median(self):
        """現行値が無効な場合は系列自身の正値中央値にフォールバックする."""
        repo = Repository()
        conn = repo.connect()
        conn.execute(
            "UPDATE properties SET catalog_rent_per_day_yen = NULL WHERE id = %s",
            (self.prop_id,),
        )
        conn.commit()
        try:
            res = self.client.get(f"/api/properties/{self.prop_id}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["price_history_meta"]["dropped_count"], 1)
            self.assertEqual(len(data["price_history"]), 3)
        finally:
            conn.execute(
                "UPDATE properties SET catalog_rent_per_day_yen = 5000 WHERE id = %s",
                (self.prop_id,),
            )
            conn.commit()
            conn.close()

    def test_guard_all_invalid_ref_drops_all(self):
        """系列も現行値も無効(正値が1つも無い)なら全件除外(空配列)で壊れた系列を出さない."""
        repo = Repository()
        conn = repo.connect()
        conn.execute(
            "UPDATE properties SET catalog_rent_per_day_yen = NULL WHERE id = %s",
            (self.prop_id,),
        )
        conn.execute(
            "UPDATE property_snapshots SET catalog_rent_per_day_yen = -100 "
            "WHERE property_id = %s",
            (self.prop_id,),
        )
        conn.commit()
        try:
            res = self.client.get(f"/api/properties/{self.prop_id}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["price_history"], [])
            self.assertEqual(data["price_history_meta"]["dropped_count"], 4)
        finally:
            conn.execute(
                "UPDATE properties SET catalog_rent_per_day_yen = 5000 WHERE id = %s",
                (self.prop_id,),
            )
            conn.execute(
                "UPDATE property_snapshots SET catalog_rent_per_day_yen = CASE "
                "WHEN scraped_at = '2026-08-03T10:00:00' THEN 300 ELSE catalog_rent_per_day_yen END "
                "WHERE property_id = %s",
                (self.prop_id,),
            )
            # CASE で書き戻した負値 -100 を元の値へ戻す
            conn.execute(
                "UPDATE property_snapshots SET catalog_rent_per_day_yen = CASE "
                "WHEN scraped_at = '2026-08-01T10:00:00' THEN 5000 "
                "WHEN scraped_at = '2026-08-02T10:00:00' THEN 4500 "
                "ELSE 4600 END "
                "WHERE property_id = %s AND scraped_at != '2026-08-03T10:00:00'",
                (self.prop_id,),
            )
            conn.commit()
            conn.close()


class TestPriceTrendApi(unittest.TestCase):
    """GET /api/analysis/price-trend の日次集計(ガード/同日重複/変動検出)."""

    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("trend")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        cls.prop_a = repo.upsert_property(_draft("bratto", "trend-a", 5000))
        cls.prop_b = repo.upsert_property(_draft("unionmonthly", "trend-b", 4000))
        conn = repo.connect()
        conn.execute("DELETE FROM property_snapshots")
        # bratto: 08-02 に同日2回取得(最新の 4600 を代表値に)、08-03 は破損値で除外
        insert_snapshot(conn, cls.prop_a, "2026-08-01T10:00:00", 5000)
        insert_snapshot(conn, cls.prop_a, "2026-08-02T10:00:00", 4500)
        insert_snapshot(conn, cls.prop_a, "2026-08-02T18:00:00", 4600)
        insert_snapshot(conn, cls.prop_a, "2026-08-03T10:00:00", 300)
        # unionmonthly: 08-02 に値上げ
        insert_snapshot(conn, cls.prop_b, "2026-08-01T10:00:00", 4000)
        insert_snapshot(conn, cls.prop_b, "2026-08-02T10:00:00", 4400)
        insert_snapshot(conn, cls.prop_b, "2026-08-03T10:00:00", 4400)
        conn.commit()
        conn.close()
        cls.client = TestClient(app)

    def _get(self, **params):
        return self.client.get("/api/analysis/price-trend", params=params)

    def test_daily_aggregation(self):
        res = self._get(days=90)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(
            [p["id"] for p in data["providers"]], ["bratto", "unionmonthly"]
        )
        self.assertEqual(
            [p["display_name"] for p in data["providers"]],
            ["BraTTo", "ユニオンマンスリー"],
        )

        all_series = data["series"]["scraped"]["all"]
        self.assertEqual([p["date"] for p in all_series], [
            "2026-08-01", "2026-08-02", "2026-08-03",
        ])
        # 08-01: bratto 5000 + union 4000
        self.assertEqual(all_series[0], {
            "date": "2026-08-01", "median": 4500, "avg": 4500,
            "count": 2, "down": 0, "up": 0,
        })
        # 08-02: 同日重複は最新行(4600)が代表値 → bratto は値下げ、union は値上げ
        self.assertEqual(all_series[1], {
            "date": "2026-08-02", "median": 4500, "avg": 4500,
            "count": 2, "down": 1, "up": 1,
        })
        # 08-03: bratto は破損値(300)で除外、union の 4400 のみ(前回比 変動なし)
        self.assertEqual(all_series[2], {
            "date": "2026-08-03", "median": 4400, "avg": 4400,
            "count": 1, "down": 0, "up": 0,
        })

    def test_per_site_series(self):
        data = self._get(days=90).json()
        by_site = data["series"]["scraped"]["by_site"]

        bratto = by_site["bratto"]
        self.assertEqual([p["date"] for p in bratto], ["2026-08-01", "2026-08-02"])
        self.assertEqual(bratto[0]["median"], 5000)
        self.assertEqual(bratto[1]["median"], 4600)
        self.assertEqual(bratto[1]["down"], 1)

        union = by_site["unionmonthly"]
        self.assertEqual([p["date"] for p in union], [
            "2026-08-01", "2026-08-02", "2026-08-03",
        ])
        self.assertEqual(union[1]["up"], 1)
        self.assertEqual(union[2]["count"], 1)

    def test_carried_series(self):
        """前進補完推計: 各物件の直近7日以内の既知値が毎日続く系列になる.

        bratto(4600, src 08-02)は 08-02〜08-08、unionmonthly(4400, src 08-03)は
        08-03〜08-09 まで補間される(窓は取得日を含む7日間)。破損値(08-03の300)
        は除外済みのため bratto は 4600 が 08-03 以降も続く。
        """
        data = self._get(days=90).json()

        all_series = data["series"]["carried"]["all"]
        dates = [p["date"] for p in all_series]
        self.assertEqual(dates, [f"2026-08-{d:02d}" for d in range(1, 10)])
        self.assertEqual(all_series[0], {
            "date": "2026-08-01", "median": 4500, "avg": 4500,
            "count": 2, "down": 0, "up": 0,
        })
        # 変動件数は当日取得分モードと共通(08-02 に bratto 値下げ / union 値上げ)
        self.assertEqual(all_series[1], {
            "date": "2026-08-02", "median": 4500, "avg": 4500,
            "count": 2, "down": 1, "up": 1,
        })
        # 08-03: bratto は当日の破損値が除外され 08-02 の 4600 が補間される
        self.assertEqual(all_series[2], {
            "date": "2026-08-03", "median": 4500, "avg": 4500,
            "count": 2, "down": 0, "up": 0,
        })
        # 両者の窓が重なる 08-08 までは2件、bratto の窓切れ後(08-09)は union のみ
        self.assertEqual(all_series[-2], {
            "date": "2026-08-08", "median": 4500, "avg": 4500,
            "count": 2, "down": 0, "up": 0,
        })
        self.assertEqual(all_series[-1], {
            "date": "2026-08-09", "median": 4400, "avg": 4400,
            "count": 1, "down": 0, "up": 0,
        })

        by_site = data["series"]["carried"]["by_site"]
        bratto = by_site["bratto"]
        self.assertEqual([p["date"] for p in bratto], [
            f"2026-08-{d:02d}" for d in range(1, 9)
        ])
        self.assertEqual(bratto[0]["median"], 5000)
        self.assertEqual(bratto[1]["median"], 4600)
        self.assertEqual(bratto[1]["down"], 1)
        self.assertEqual(bratto[-1]["median"], 4600)

        union = by_site["unionmonthly"]
        self.assertEqual([p["date"] for p in union], [
            f"2026-08-{d:02d}" for d in range(1, 10)
        ])
        self.assertEqual(union[1]["median"], 4400)
        self.assertEqual(union[1]["up"], 1)
        self.assertEqual(union[-1]["median"], 4400)

    def test_guard_meta_disclosure(self):
        data = self._get(days=90).json()
        self.assertEqual(data["meta"]["snapshot_rows"], 7)
        self.assertEqual(data["meta"]["guarded_rows"], 6)
        self.assertEqual(data["meta"]["excluded_rows"], 1)
        self.assertEqual(data["carried_window_days"], 7)

    def test_days_validation(self):
        self.assertEqual(self._get(days=5).status_code, 422)
        self.assertEqual(self._get(days=1000).status_code, 422)


class TestPriceTrendPrefectureFilter(unittest.TestCase):
    """GET /api/analysis/price-trend?prefecture_name= の県絞り込み."""

    @classmethod
    def setUpClass(cls):
        cls._db = ScopedDb("trend-pref")
        cls.addClassCleanup(cls._db.close)

        repo = Repository()
        cls.prop_tokyo = repo.upsert_property(_draft("bratto", "pref-tokyo", 5000))
        cls.prop_osaka = repo.upsert_property(_draft("unionmonthly", "pref-osaka", 4000))
        conn = repo.connect()
        # unionmonthly 側は大阪府の物件として差し替える(_draft は東京都で生成するため)
        conn.execute(
            "UPDATE properties SET prefecture_name = '大阪府', prefecture_slug = 'osaka' "
            "WHERE id = %s",
            (cls.prop_osaka,),
        )
        conn.execute("DELETE FROM property_snapshots")
        insert_snapshot(conn, cls.prop_tokyo, "2026-08-01T10:00:00", 5000)
        insert_snapshot(conn, cls.prop_tokyo, "2026-08-02T10:00:00", 4600)
        insert_snapshot(conn, cls.prop_osaka, "2026-08-01T10:00:00", 4000)
        insert_snapshot(conn, cls.prop_osaka, "2026-08-02T10:00:00", 4400)
        conn.commit()
        conn.close()
        cls.client = TestClient(app)

    def _get(self, **params):
        return self.client.get("/api/analysis/price-trend", params=params)

    def test_filter_tokyo_series(self):
        """prefecture_name=東京都 で東京都の物件のみが集計される.

        大阪(4000/4400)が混ざらず、scraped/carried とも中央値・物件数が
        東京都側(5000/4600)の単独集計になることで検証する。
        """
        res = self._get(days=90, prefecture_name="東京都")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        all_series = data["series"]["scraped"]["all"]
        self.assertEqual([p["date"] for p in all_series], ["2026-08-01", "2026-08-02"])
        self.assertEqual(all_series[0]["median"], 5000)
        self.assertEqual(all_series[0]["count"], 1)
        self.assertEqual(all_series[1]["median"], 4600)
        self.assertEqual(all_series[1]["count"], 1)
        self.assertEqual(all_series[1]["down"], 1)
        self.assertEqual(all_series[1]["up"], 0)

        # carried も東京都のみ(08-02 の 4600 が窓内で前進補完される)
        carried = data["series"]["carried"]["all"]
        self.assertEqual(carried[0]["median"], 5000)
        self.assertEqual(carried[0]["count"], 1)
        self.assertEqual(carried[1]["median"], 4600)
        self.assertEqual(carried[-1]["median"], 4600)

        # counts 側のクエリにも県絞り込みが効いている
        self.assertEqual(data["meta"]["snapshot_rows"], 2)

    def test_no_filter_keeps_all_prefectures(self):
        """prefecture_name 無しは従来通り全県(東京都+大阪府)が集計される."""
        data = self._get(days=90).json()
        all_series = data["series"]["scraped"]["all"]
        self.assertEqual(all_series[0], {
            "date": "2026-08-01", "median": 4500, "avg": 4500,
            "count": 2, "down": 0, "up": 0,
        })
        self.assertEqual(all_series[1]["count"], 2)
        self.assertEqual(data["meta"]["snapshot_rows"], 4)

    def test_empty_prefecture_treated_as_all(self):
        """空文字列の prefecture_name は未指定(全県)と同じ結果になる."""
        with_empty = self._get(days=90, prefecture_name="").json()
        without = self._get(days=90).json()
        self.assertEqual(
            with_empty["series"]["scraped"]["all"],
            without["series"]["scraped"]["all"],
        )
        self.assertEqual(
            with_empty["series"]["carried"]["all"],
            without["series"]["carried"]["all"],
        )

    def test_invalid_prefecture_returns_empty(self):
        """該当0件の都道府県でも 200 で空 series を返す(エラーにしない)."""
        res = self._get(days=90, prefecture_name="北海道")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["series"]["scraped"]["all"], [])
        self.assertEqual(data["series"]["carried"]["all"], [])
        self.assertEqual(data["meta"]["snapshot_rows"], 0)


if __name__ == "__main__":
    unittest.main()
