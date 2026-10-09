#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geocode_missing_v2 の仕様テスト (docs/geocode-v2-batch-spec.md §3/§6).

tmp v2 DB + geocode_address のスタブでオフライン検証する。
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


from helpers import ScopedDb, make_draft, make_tokyo_draft  # noqa: E402
from store import geocode_v2  # noqa: E402
from store.geocode_v2 import geocode_missing_v2  # noqa: E402
from store.geocoder import GeocodingSystemError  # noqa: E402
from store.repository import Repository  # noqa: E402


def _repo() -> Repository:
    # env は都度読み(他テストモジュールと同一プロセスで走るため)
    return Repository()


def _seed(
    external_id: str,
    *,
    address: str | None = "東京都渋谷区神宮前1-2-3",
    lat: float | None = None,
    lng: float | None = None,
    source: str | None = None,
) -> int:
    """Insert a property row with explicit geocode columns. Returns property id."""
    repo = _repo()
    repo.upsert_property(make_draft(external_id))
    conn = repo.connect()
    try:
        conn.execute(
            """
            UPDATE properties
            SET address = %s, lat = %s, lng = %s, geocode_source = %s, geocode_confidence = NULL
            WHERE external_id = %s
            """,
            (address, lat, lng, source, external_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM properties WHERE external_id = %s", (external_id,)
        ).fetchone()
        return int(row["id"])
    finally:
        conn.close()


def _row(pid: int) -> dict:
    conn = _repo().connect()
    try:
        row = conn.execute(
            "SELECT * FROM properties WHERE id = %s", (pid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


class GeocodeMissingV2Test(unittest.TestCase):
    def setUp(self):
        # tmp DB を都度作り、他テストモジュールの env 変更と隔離する
        self._db = ScopedDb("geocode")
        self.addCleanup(self._db.close)

        conn = _repo().connect()
        try:
            conn.execute("DELETE FROM properties")
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # モード別 WHERE 対象選択 (§3.3)
    # ------------------------------------------------------------------

    def test_default_mode_selects_only_missing_unfailed(self):
        a = _seed("a")  # 座標なし・ソースなし → 対象
        b = _seed("b", lat=35.0, lng=139.0, source="detail_map")  # 座標あり → 対象外
        c = _seed("c", source="failed:nominatim")  # 失敗印 → 対象外

        stub = mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.0, 139.0, "google", 0.8),
        )
        slp = mock.patch("store.geocode_v2.time.sleep")
        with stub, slp:
            stats = geocode_missing_v2(limit=None)

        self.assertEqual(stats["total_found"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(_row(a)["geocode_source"], "google")
        # 対象外の行は無傷
        self.assertEqual(_row(b)["geocode_source"], "detail_map")
        self.assertEqual(_row(c)["geocode_source"], "failed:nominatim")
        self.assertIsNone(_row(c)["lat"])

    def test_force_mode_targets_all_rows_with_address(self):
        a = _seed("a", lat=35.0, lng=139.0, source="detail_map")
        b = _seed("b", source="failed:google")

        stub = mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.1, 139.1, "google", 1.0),
        )
        with stub, mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None, force=True)

        self.assertEqual(stats["total_found"], 2)
        self.assertEqual(stats["success"], 2)
        self.assertEqual(_row(a)["lat"], 35.1)
        self.assertEqual(_row(b)["geocode_source"], "google")

    def test_retry_only_targets_any_existing_source(self):
        a = _seed("a", lat=35.0, lng=139.0, source="detail_map")  # ingest 由来も対象
        b = _seed("b", source="failed:google")
        c = _seed("c")  # geocode_source NULL → 対象外

        stub = mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.2, 139.2, "nominatim", 0.9),
        )
        with stub, mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None, retry_only=True)

        self.assertEqual(stats["total_found"], 2)
        self.assertEqual(stats["success"], 2)

    # ------------------------------------------------------------------
    # 状態遷移 (§3.1)
    # ------------------------------------------------------------------

    def test_success_updates_coords_source_and_confidence(self):
        pid = _seed("s1")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.68, 139.76, "google", 0.8),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        row = _row(pid)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(row["lat"], 35.68)
        self.assertEqual(row["lng"], 139.76)
        self.assertEqual(row["geocode_source"], "google")
        self.assertEqual(row["geocode_confidence"], 0.8)

    def test_soft_failure_marks_failed_with_returned_source(self):
        pid = _seed("f1")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(None, None, "google", None),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        row = _row(pid)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(row["geocode_source"], "failed:google")
        # I1: 失敗印行は座標なし
        self.assertIsNone(row["lat"])
        self.assertIsNone(row["lng"])

    def test_failed_label_never_uses_default(self):
        """戻り値 source 欠落時は provider → 'nominatim' の順。'default' は禁止 (I4)。"""
        p1 = _seed("f2")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(None, None, None, None),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats_auto = geocode_missing_v2(limit=None)  # provider=None

        self.assertEqual(_row(p1)["geocode_source"], "failed:nominatim")
        p2 = _seed("f3")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(None, None, None, None),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats_google = geocode_missing_v2(limit=None, provider="google")

        self.assertEqual(_row(p2)["geocode_source"], "failed:google")
        for st in (stats_auto, stats_google):
            self.assertNotIn("failed:default", str(st))
        self.assertFalse(
            any((r["geocode_source"] or "") == "failed:default" for r in _all_rows())
        )

    def test_soft_failure_with_existing_coords_is_unchanged(self):
        """既存座標がある行のソフト失敗は無書き込み unchanged (I3)。"""
        pid = _seed("u1", lat=35.0, lng=139.0, source="detail_map")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(None, None, "nominatim", None),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None, force=True)

        row = _row(pid)
        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(row["lat"], 35.0)  # 座標は保持
        self.assertEqual(row["geocode_source"], "detail_map")  # 失敗印も付かない

    def test_system_error_skips_without_write(self):
        pid = _seed("e1")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            side_effect=GeocodingSystemError("429 rate limited"),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        row = _row(pid)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertIsNone(row["geocode_source"])  # I2: 痕跡なし
        self.assertNotIn("aborted", stats)  # 1 回では打ち切らない

    # ------------------------------------------------------------------
    # サーキットブレーカ (§3.5)
    # ------------------------------------------------------------------

    def test_circuit_breaker_aborts_after_three_consecutive_errors(self):
        pids = [_seed(f"cb{i}") for i in range(5)]
        calls = []

        def always_raise(address, provider=None):
            calls.append(address)
            raise GeocodingSystemError("network down")

        with mock.patch("store.geocode_v2.geocode_address", side_effect=always_raise), \
                mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        self.assertTrue(stats["aborted"])
        self.assertEqual(len(calls), 3)  # 3 連続で打ち切り、4/5 行目は試行しない
        self.assertEqual(stats["skipped"], 3)
        self.assertEqual(stats["processed"], 3)
        self.assertEqual(stats["remaining"], 2)
        for pid in pids[3:]:
            self.assertIsNone(_row(pid)["geocode_source"])

    def test_consecutive_counter_resets_on_success(self):
        """連続カウンタは成功でリセット → 途中成功があれば 3 連続にならない限り継続。"""
        _seed("r1")
        _seed("r2")
        p_ok = _seed("r3")
        _seed("r4")
        _seed("r5")

        outcomes = iter([
            GeocodingSystemError("err"),
            GeocodingSystemError("err"),
            (35.0, 139.0, "google", 1.0),
            GeocodingSystemError("err"),
            GeocodingSystemError("err"),
        ])

        def scripted(address, provider=None):
            out = next(outcomes)
            if isinstance(out, Exception):
                raise out
            return out

        with mock.patch("store.geocode_v2.geocode_address", side_effect=scripted), \
                mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        self.assertNotIn("aborted", stats)
        self.assertEqual(stats["processed"], 5)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["skipped"], 4)
        self.assertEqual(_row(p_ok)["geocode_source"], "google")

    def test_skipped_total_and_consecutive_are_distinct_on_abort(self):
        """打切り時は skipped(累計)と consecutive_system_errors(連続数)が別値になる。

        予期せぬ例外 1 件(連続カウンタをリセット)の後にシステムエラー 3 連続で
        打ち切る → skipped=4 / consecutive=3。警告文が skipped を連続数として
        表示する流用バグの退化防止(H6)。
        """
        for i in range(4):
            _seed(f"d{i}", address=f"addr-d{i}")

        outcomes = iter(
            [ValueError("program bug")] + [GeocodingSystemError("err")] * 3
        )

        def scripted(address, provider=None):
            out = next(outcomes)
            if isinstance(out, Exception):
                raise out
            return out

        with mock.patch("store.geocode_v2.geocode_address", side_effect=scripted), \
                mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        self.assertTrue(stats["aborted"])
        self.assertEqual(stats["skipped"], 4)
        self.assertEqual(stats["consecutive_system_errors"], 3)
        self.assertEqual(stats["processed"], 4)
        self.assertEqual(stats["remaining"], 0)

    def test_unexpected_exception_skips_without_write_and_continues(self):
        p1 = _seed("x1", address="addr-x1")
        p2 = _seed("x2", address="addr-x2")

        def scripted(address, provider=None):
            if address.endswith("x1"):
                raise ValueError("program bug")
            return (35.5, 139.5, "nominatim", 0.9)

        with mock.patch("store.geocode_v2.geocode_address", side_effect=scripted), \
                mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertIsNone(_row(p1)["geocode_source"])  # 失敗印は付けない
        self.assertIsNone(_row(p1)["lat"])
        self.assertEqual(_row(p2)["geocode_source"], "nominatim")

    # ------------------------------------------------------------------
    # 統計 (§3.4)
    # ------------------------------------------------------------------

    def test_stats_keys_complete(self):
        _seed("k1")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.0, 139.0, "google", 0.8),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=None)

        for key in (
            "total_found",
            "processed",
            "success",
            "failed",
            "skipped",
            "unchanged",
            "remaining",
        ):
            self.assertIn(key, stats)
        self.assertEqual(
            stats["processed"],
            stats["success"] + stats["failed"] + stats["skipped"] + stats["unchanged"],
        )
        self.assertEqual(
            stats["remaining"], max(0, stats["total_found"] - stats["processed"])
        )

    def test_stats_on_empty_selection(self):
        stats = geocode_missing_v2(limit=None)
        self.assertEqual(stats["total_found"], 0)
        self.assertEqual(stats["processed"], 0)
        self.assertEqual(stats["remaining"], 0)

    def test_limit_is_budget_over_selection(self):
        for i in range(5):
            _seed(f"l{i}")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.0, 139.0, "google", 0.8),
        ), mock.patch("store.geocode_v2.time.sleep"):
            stats = geocode_missing_v2(limit=2)

        self.assertEqual(stats["total_found"], 5)  # 選択行数は予算前
        self.assertEqual(stats["processed"], 2)  # 予算分のみ試行
        self.assertEqual(stats["remaining"], 3)
        self.assertEqual(stats["success"], 2)

    # ------------------------------------------------------------------
    # バリデーション (§3.7)
    # ------------------------------------------------------------------

    def test_invalid_provider_raises_value_error(self):
        for bad in ("bing", "default", "google "):
            with self.assertRaises(ValueError):
                geocode_missing_v2(provider=bad)
        # 境界値は通る(呼び出しは行われないので DB 影響なし)
        _seed("v1")
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(None, None, "nominatim", None),
        ), mock.patch("store.geocode_v2.time.sleep"):
            for ok_provider in (None, "nominatim", "google"):
                geocode_missing_v2(limit=1, provider=ok_provider)

    def test_force_and_retry_only_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            geocode_missing_v2(force=True, retry_only=True)


class GeocodeWarningsFormatterTest(unittest.TestCase):
    """警告文言の正本テスト (H6 / spec §3.5・§3.8)。

    cli / mcp_server / web tasks は geocode_result_warnings +
    format_geocode_warnings 経由でのみ文言を生成する。
    """

    # spec §3.8 契約文言: 一文字も変更禁止
    SKIPPED_SENTENCE = (
        "warn: 2 件はプロバイダ障害等のため記録なしスキップ。"
        "時間を置いて再実行してください"
    )

    def test_warnings_structure_skipped_only(self):
        warnings = geocode_v2.geocode_result_warnings({"skipped": 2})
        self.assertEqual(warnings, [{"code": "skipped", "count": 2}])

    def test_warnings_structure_aborted_with_consecutive(self):
        warnings = geocode_v2.geocode_result_warnings(
            {"skipped": 4, "aborted": True, "consecutive_system_errors": 3}
        )
        self.assertEqual(
            warnings,
            [
                {"code": "skipped", "count": 4},
                {"code": "aborted", "consecutive": 3},
            ],
        )

    def test_warnings_structure_aborted_without_consecutive_key(self):
        """打切り連続数キーの無い旧 stats は打切り条件値(_CONSECUTIVE_SYSTEM_ERROR_LIMIT)へ。"""
        warnings = geocode_v2.geocode_result_warnings({"skipped": 3, "aborted": True})
        self.assertEqual(
            warnings,
            [
                {"code": "skipped", "count": 3},
                {"code": "aborted", "consecutive": 3},
            ],
        )

    def test_warnings_structure_empty(self):
        self.assertEqual(geocode_v2.geocode_result_warnings({}), [])
        self.assertEqual(geocode_v2.geocode_result_warnings({"skipped": 0}), [])
        self.assertEqual(
            geocode_v2.geocode_result_warnings({"aborted": False, "skipped": 0}), []
        )

    def test_format_ja_and_en_snapshot(self):
        warnings = [
            {"code": "skipped", "count": 2},
            {"code": "aborted", "consecutive": 3},
        ]
        ja = geocode_v2.format_geocode_warnings(warnings, lang="ja")
        en = geocode_v2.format_geocode_warnings(warnings, lang="en")

        # skipped 行は spec §3.8 契約により ja/en とも同一の日本語
        self.assertEqual(ja[0], self.SKIPPED_SENTENCE)
        self.assertEqual(en[0], self.SKIPPED_SENTENCE)

        # aborted 行は言語別。連続数を正しく参照する
        # (旧 tasks.py の skipped 流用表示を禁止する退化防止)
        self.assertEqual(
            ja[1],
            "warn: 連続 3 回のプロバイダ障害のため"
            "サーキットブレーカにより打ち切りしました",
        )
        self.assertEqual(
            en[1],
            "warn: geocode aborted by circuit breaker "
            "after 3 consecutive provider system errors",
        )

    def test_format_default_lang_is_ja(self):
        warnings = [{"code": "aborted", "consecutive": 3}]
        self.assertEqual(
            geocode_v2.format_geocode_warnings(warnings),
            geocode_v2.format_geocode_warnings(warnings, lang="ja"),
        )

    def test_format_unknown_lang_falls_back_to_ja(self):
        self.assertEqual(
            geocode_v2.format_geocode_warnings(
                [{"code": "aborted", "consecutive": 3}], lang="xx"
            ),
            geocode_v2.format_geocode_warnings(
                [{"code": "aborted", "consecutive": 3}], lang="ja"
            ),
        )


def _all_rows() -> list[dict]:
    conn = _repo().connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM properties")]
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()


class GeocodeBuildingsTest(unittest.TestCase):
    """B2-ε 建物単位化: 座標欠落建物の geocode + 部屋への代表座標 backfill."""

    def setUp(self):
        self._db = ScopedDb("geocode-buildings")
        self.addCleanup(self._db.close)
        self.repo = Repository()
        # 同一住所・座標なしの 2 部屋 → 建物 1 つ(座標 NULL)へ集約される
        self.repo.upsert_property(
            make_tokyo_draft("bgeo-101", lat=None, lng=None)
        )
        self.repo.upsert_property(
            make_tokyo_draft("bgeo-102", lat=None, lng=None)
        )

    def test_building_geocode_backfills_rooms(self):
        """建物 geocode 成功時に所属部屋(座標 NULL 行)へ代表座標が伝播する."""
        with mock.patch(
            "store.geocode_v2.geocode_address",
            return_value=(35.66, 139.70, "google", 0.9),
        ):
            stats = geocode_v2.geocode_missing_v2()
        self.assertEqual(stats["success"], 1)
        with self.repo.connect() as conn:
            building = dict(conn.execute("SELECT * FROM buildings").fetchone())
            self.assertEqual((building["lat"], building["lng"]), (35.66, 139.70))
            self.assertEqual(building["geocode_source"], "google")
            rooms = list(
                conn.execute(
                    "SELECT external_id, lat, lng FROM properties ORDER BY id"
                )
            )
            for room in rooms:
                self.assertEqual((room["lat"], room["lng"]), (35.66, 139.70))
        # 内訳が targets に保持される(トップレベルは合計)
        self.assertEqual(stats["targets"]["buildings"]["success"], 1)
        self.assertEqual(stats["targets"]["rooms"]["total_found"], 0)
