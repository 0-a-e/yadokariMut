#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scripts/migrations/migrate_unionmonthly_plans.py (unionmonthly plan migration)."""

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "migrations"
    / "migrate_unionmonthly_plans.py"
)
_spec = importlib.util.spec_from_file_location("migrate_unionmonthly_plans", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_migration = importlib.util.module_from_spec(_spec)
# スクリプト内の sys.path 調整(domain import 解決)も exec_module 経由で走る
_spec.loader.exec_module(_migration)

MigrationError = _migration.MigrationError
catalog_distribution = _migration.catalog_distribution
migrate = _migration.migrate

from store.repository import Repository

NOW = "2026-01-01T00:00:00"

# Old-format unionmonthly plans (as stored by the old parser)
UNION_PLANS = [
    # (plan_key, unit, dmin, dmax, rent_current, raw_text)
    ("s_short", "per_month", 1, None, 5390, "7日以上-15日未満"),
    ("セミショート", "per_month", 1, None, 4730, "15日以上-1ヶ月未満"),
    ("short", "per_month", 30, 89, 105600, "1ヶ月以上-3ヶ月未満"),
]
BRATTO_PLANS = [
    ("s_short", "per_day", 1, 29, 3000, "s_short"),
]


def _insert_property(cur, source_site, external_id, catalog):
    cur.execute(
        """
        INSERT INTO properties
            (source_site, external_id, title, first_seen_at, last_seen_at,
             is_active, catalog_rent_per_day_yen)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (source_site, external_id, f"物件 {external_id}", NOW, NOW, catalog),
    )
    return cur.lastrowid


def _insert_plan(cur, property_id, plan_key, unit, dmin, dmax, rent_current, raw_text):
    cur.execute(
        """
        INSERT INTO price_plans
            (property_id, plan_key, plan_name, duration_min_days, duration_max_days,
             available, presentation_unit, rent_original_yen, rent_current_yen,
             utilities_included, raw_text, scraped_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 1, ?, ?)
        """,
        (property_id, plan_key, plan_key, dmin, dmax, unit, rent_current, rent_current,
         raw_text, NOW),
    )


def build_db(path):
    """Create a v2 temp DB with old-format unionmonthly rows + one bratto row."""
    repo = Repository(path)
    repo.init_db()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    pids = {}
    pids["union"] = _insert_property(cur, "unionmonthly", "9001", catalog=179)  # 5390//30 (old bug)
    pids["bratto"] = _insert_property(cur, "bratto", "B-1", catalog=3000)
    for plan_key, unit, dmin, dmax, rent, raw in UNION_PLANS:
        _insert_plan(cur, pids["union"], plan_key, unit, dmin, dmax, rent, raw)
    for plan_key, unit, dmin, dmax, rent, raw in BRATTO_PLANS:
        _insert_plan(cur, pids["bratto"], plan_key, unit, dmin, dmax, rent, raw)
    conn.commit()
    return conn, pids


def snapshot(conn):
    """Full comparable snapshot of price_plans + catalog values."""
    plans = [
        tuple(r)
        for r in conn.execute("SELECT * FROM price_plans ORDER BY id").fetchall()
    ]
    catalog = [
        tuple(r)
        for r in conn.execute(
            "SELECT id, catalog_rent_per_day_yen FROM properties ORDER BY id"
        ).fetchall()
    ]
    return plans, catalog


def plans_by_key(conn, property_id):
    rows = conn.execute(
        "SELECT * FROM price_plans WHERE property_id = ?", (property_id,)
    ).fetchall()
    return {r["plan_key"]: dict(r) for r in rows}


class TestUnionmonthlyMigration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        self.addCleanup(os.unlink, self.db_path)
        self.conn, self.pids = build_db(self.db_path)
        self.addCleanup(self.conn.close)

    def tearDown(self):
        bak = self.db_path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    def test_migrate_fixes_rename_unit_duration_catalog(self):
        stats = migrate(self.conn)

        # --- step a: rename ---
        self.assertEqual(stats["renamed_semi_short"], 1)
        plans = plans_by_key(self.conn, self.pids["union"])
        self.assertEqual(set(plans), {"s_short", "semi_short", "short"})
        self.assertNotIn("セミショート", plans)

        # --- step b: presentation_unit ---
        self.assertEqual(stats["unit_updated"], 2)
        self.assertEqual(stats["unit_updated_per_day"], 2)
        self.assertEqual(stats["unit_updated_per_month"], 0)
        self.assertEqual(plans["s_short"]["presentation_unit"], "per_day")
        self.assertEqual(plans["semi_short"]["presentation_unit"], "per_day")
        self.assertEqual(plans["short"]["presentation_unit"], "per_month")

        # --- step c: duration bands from raw_text ---
        self.assertEqual(stats["duration_updated"], 2)
        self.assertEqual(stats["duration_parse_hits"], 3)
        self.assertEqual(plans["s_short"]["duration_min_days"], 7)
        self.assertEqual(plans["s_short"]["duration_max_days"], 14)
        self.assertEqual(plans["semi_short"]["duration_min_days"], 15)
        self.assertEqual(plans["semi_short"]["duration_max_days"], 29)
        self.assertEqual(plans["short"]["duration_min_days"], 30)
        self.assertEqual(plans["short"]["duration_max_days"], 89)
        self.assertEqual(plans["short"]["rent_current_yen"], 105600)

        # --- step d: catalog = min(5390, 4730, 105600//30=3520) ---
        self.assertEqual(stats["catalog_updated"], 1)
        self.assertEqual(stats["catalog_before"]["<=500"], 1)
        self.assertEqual(stats["catalog_after"]["2001-5000"], 1)
        prop = self.conn.execute(
            "SELECT catalog_rent_per_day_yen FROM properties WHERE id = ?",
            (self.pids["union"],),
        ).fetchone()
        self.assertEqual(prop["catalog_rent_per_day_yen"], 3520)

        # --- bratto untouched ---
        self.assertEqual(stats["properties_scanned"], 1)
        self.assertEqual(stats["plans_scanned"], 3)
        bratto = plans_by_key(self.conn, self.pids["bratto"])
        self.assertEqual(set(bratto), {"s_short"})
        self.assertEqual(bratto["s_short"]["presentation_unit"], "per_day")
        self.assertEqual(bratto["s_short"]["duration_min_days"], 1)
        self.assertEqual(bratto["s_short"]["duration_max_days"], 29)
        self.assertEqual(bratto["s_short"]["rent_current_yen"], 3000)
        bratto_cat = self.conn.execute(
            "SELECT catalog_rent_per_day_yen FROM properties WHERE id = ?",
            (self.pids["bratto"],),
        ).fetchone()
        self.assertEqual(bratto_cat["catalog_rent_per_day_yen"], 3000)
        self.assertFalse(stats["dry_run"])

    def test_dry_run_writes_nothing(self):
        before = snapshot(self.conn)
        stats = migrate(self.conn, dry_run=True)
        after = snapshot(self.conn)
        self.assertEqual(before, after)
        self.assertTrue(stats["dry_run"])
        # would-change counts match the real run
        self.assertEqual(stats["renamed_semi_short"], 1)
        self.assertEqual(stats["unit_updated"], 2)
        self.assertEqual(stats["duration_updated"], 2)
        self.assertEqual(stats["catalog_updated"], 1)

    def test_migrate_is_idempotent(self):
        migrate(self.conn)
        second = migrate(self.conn)
        self.assertEqual(second["renamed_semi_short"], 0)
        self.assertEqual(second["unit_updated"], 0)
        self.assertEqual(second["duration_updated"], 0)
        self.assertEqual(second["catalog_updated"], 0)

    def test_rename_conflict_aborts_without_changes(self):
        cur = self.conn.cursor()
        pid = _insert_property(cur, "unionmonthly", "9002", catalog=None)
        _insert_plan(cur, pid, "semi_short", "per_day", 15, 29, 4730, "15日以上-1ヶ月未満")
        _insert_plan(cur, pid, "セミショート", "per_month", 1, None, 4730, "15日以上-1ヶ月未満")
        self.conn.commit()
        before = snapshot(self.conn)

        with self.assertRaises(MigrationError):
            migrate(self.conn)

        self.assertEqual(before, snapshot(self.conn))


class TestCatalogDistribution(unittest.TestCase):
    def test_buckets(self):
        dist = catalog_distribution([100, 500, 501, 2000, 2001, 5000, 5001, None])
        self.assertEqual(dist["<=500"], 2)
        self.assertEqual(dist["501-2000"], 2)
        self.assertEqual(dist["2001-5000"], 2)
        self.assertEqual(dist[">5000"], 1)
        self.assertEqual(dist["NULL"], 1)
        self.assertEqual(sum(dist.values()), 8)


if __name__ == "__main__":
    unittest.main()
