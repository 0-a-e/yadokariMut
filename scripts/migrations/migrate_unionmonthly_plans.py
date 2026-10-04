#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot migration for unionmonthly price_plans written by the old parser.

Old-parser defects fixed here (target-source rows only; bratto untouched):
  1. plan_key 'セミショート' was left un-normalized (2,187 rows) -> 'semi_short'
  2. s_short / semi_short are 円/日 on the site but were stored with
     presentation_unit='per_month'
  3. duration_min_days / duration_max_days stayed (1, NULL) even though
     raw_text holds e.g. '7日以上-15日未満'
  4. properties.catalog_rent_per_day_yen divided the day-rate plans by 30
     (about 1/30 of reality) -> recomputed from the corrected plans via
     domain.pricing (resolve_plans_effective + compute_catalog_min_daily).

Runs on a bare python3 (stdlib + local src only; no bs4 etc.).

Usage:
    python3 scripts/migrations/migrate_unionmonthly_plans.py --db /path/to.db [--dry-run]
                                              [--source unionmonthly]
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys

# Ensure src/ is on path when run as a script (no-op when imported as module).
# scripts/migrations/ からリポジトリ直下の src/ を解決するため2階層遡る
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "src")
)

from domain.pricing import (  # noqa: E402
    UNION_DURATION_BANDS,
    compute_catalog_min_daily,
    parse_union_duration_text,
    resolve_plans_effective,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SEMISHORT_JA = "セミショート"
SEMISHORT_KEY = "semi_short"
DAY_PLAN_KEYS = ("s_short", SEMISHORT_KEY)

CATALOG_BUCKETS = ("<=500", "501-2000", "2001-5000", ">5000", "NULL")

_PLAN_SELECT = """
    SELECT pp.id, pp.property_id, pp.plan_key, pp.plan_name,
           pp.duration_min_days, pp.duration_max_days, pp.available,
           pp.presentation_unit, pp.rent_original_yen, pp.rent_current_yen,
           pp.management_yen, pp.utilities_yen, pp.utilities_included,
           pp.cleaning_yen, pp.campaign_label, pp.raw_text
    FROM price_plans AS pp
    JOIN properties AS p ON p.id = pp.property_id
    WHERE p.source_site = ?
    ORDER BY pp.property_id, pp.id
"""

_PLAN_FIELDS = (
    "id", "property_id", "plan_key", "plan_name",
    "duration_min_days", "duration_max_days", "available",
    "presentation_unit", "rent_original_yen", "rent_current_yen",
    "management_yen", "utilities_yen", "utilities_included",
    "cleaning_yen", "campaign_label", "raw_text",
)


class MigrationError(RuntimeError):
    """Fatal migration condition (e.g. plan_key rename collision)."""


def catalog_distribution(values) -> dict[str, int]:
    """Bucket catalog per-day values: <=500 / 501-2000 / 2001-5000 / >5000 / NULL."""
    dist = {bucket: 0 for bucket in CATALOG_BUCKETS}
    for v in values:
        if v is None:
            dist["NULL"] += 1
        elif v <= 500:
            dist["<=500"] += 1
        elif v <= 2000:
            dist["501-2000"] += 1
        elif v <= 5000:
            dist["2001-5000"] += 1
        else:
            dist[">5000"] += 1
    return dist


def _load_target_plans(cur: sqlite3.Cursor, source: str) -> list[dict]:
    cur.execute(_PLAN_SELECT, (source,))
    rows = cur.fetchall()  # materialize before any UPDATE on the same connection
    return [dict(zip(_PLAN_FIELDS, row)) for row in rows]


def _load_target_catalog(cur: sqlite3.Cursor, source: str) -> dict[int, int | None]:
    cur.execute("SELECT id, catalog_rent_per_day_yen FROM properties WHERE source_site = ?", (source,))
    return {row[0]: row[1] for row in cur.fetchall()}


def _normalize_plan_key(plan_key: str | None) -> str:
    return SEMISHORT_KEY if plan_key == SEMISHORT_JA else str(plan_key or "")


def _check_rename_collision(plans: list[dict]) -> None:
    """Abort if a property holds both 'semi_short' and 'セミショート'."""
    by_prop: dict[int, set[str]] = {}
    for row in plans:
        by_prop.setdefault(row["property_id"], set()).add(row["plan_key"])
    conflicts = sorted(
        pid
        for pid, keys in by_prop.items()
        if SEMISHORT_JA in keys and SEMISHORT_KEY in keys
    )
    if conflicts:
        raise MigrationError(
            "plan_key rename collision: property_id(s) %s hold both "
            "'semi_short' and 'セミショート'. Resolve manually before migrating."
            % conflicts
        )


def _compute_plan_fixes(plans: list[dict]) -> dict:
    """Compute per-row corrections from the DB snapshot (no writes)."""
    rename_rows: list[tuple[int]] = []
    unit_rows: list[tuple[str, int]] = []
    duration_rows: list[tuple[int, int | None, int]] = []
    unit_per_day = unit_per_month = 0
    parse_hits = fallback_min = fallback_max = 0

    corrected: list[dict] = []
    for row in plans:
        fixed = dict(row)
        key = _normalize_plan_key(row["plan_key"])
        if key != row["plan_key"]:
            rename_rows.append((row["id"],))
            fixed["plan_key"] = key

        wanted_unit = "per_day" if key in DAY_PLAN_KEYS else "per_month"
        if (row["presentation_unit"] or "") != wanted_unit:
            unit_rows.append((wanted_unit, row["id"]))
            if wanted_unit == "per_day":
                unit_per_day += 1
            else:
                unit_per_month += 1
            fixed["presentation_unit"] = wanted_unit

        cur_min = int(row["duration_min_days"] or 1)
        cur_max = row["duration_max_days"]
        parsed_min, parsed_max = parse_union_duration_text(row["raw_text"])
        if parsed_min is not None or parsed_max is not None:
            parse_hits += 1
        band = UNION_DURATION_BANDS.get(key, (cur_min, cur_max))
        new_min = parsed_min if parsed_min is not None else band[0]
        new_max = parsed_max if parsed_max is not None else band[1]
        if parsed_min is None and band[0] != cur_min:
            fallback_min += 1
        if parsed_max is None and band[1] != cur_max:
            fallback_max += 1
        if (new_min, new_max) != (cur_min, cur_max):
            duration_rows.append((new_min, new_max, row["id"]))
            fixed["duration_min_days"] = new_min
            fixed["duration_max_days"] = new_max

        corrected.append(fixed)

    return {
        "rename_rows": rename_rows,
        "unit_rows": unit_rows,
        "unit_per_day": unit_per_day,
        "unit_per_month": unit_per_month,
        "duration_rows": duration_rows,
        "parse_hits": parse_hits,
        "fallback_min": fallback_min,
        "fallback_max": fallback_max,
        "corrected_plans": corrected,
    }


def _compute_catalog_updates(
    corrected_plans: list[dict], current_catalog: dict[int, int | None]
) -> tuple[list[tuple[int | None, int]], dict[int, int | None]]:
    """Recompute catalog_rent_per_day_yen per target property from corrected plans."""
    by_prop: dict[int, list[dict]] = {}
    for row in corrected_plans:
        by_prop.setdefault(row["property_id"], []).append(row)

    new_catalog: dict[int, int | None] = {pid: None for pid in current_catalog}
    for pid, rows in by_prop.items():
        resolved = resolve_plans_effective(rows)
        new_catalog[pid] = compute_catalog_min_daily(resolved).get("catalog_rent_per_day_yen")

    updates = [
        (value, pid)
        for pid, value in new_catalog.items()
        if value != current_catalog.get(pid)
    ]
    return updates, new_catalog


def _print_report(stats: dict) -> None:
    logger.info(
        "unionmonthly plan migration report: source=%s dry_run=%s",
        stats["source"],
        stats["dry_run"],
    )
    logger.info(
        "scanned: plans=%d properties=%d",
        stats["plans_scanned"],
        stats["properties_scanned"],
    )
    logger.info(
        "step a rename '%s'->'%s': %d row(s)",
        SEMISHORT_JA,
        SEMISHORT_KEY,
        stats["renamed_semi_short"],
    )
    logger.info(
        "step b presentation_unit updated: %d row(s) (per_day=%d, per_month=%d)",
        stats["unit_updated"],
        stats["unit_updated_per_day"],
        stats["unit_updated_per_month"],
    )
    logger.info(
        "step c duration bands updated: %d row(s) (raw_parse_hits=%d, band_fallback_min=%d, band_fallback_max=%d)",
        stats["duration_updated"],
        stats["duration_parse_hits"],
        stats["duration_band_fallback_min"],
        stats["duration_band_fallback_max"],
    )
    logger.info(
        "step d catalog_rent_per_day_yen updated: %d property(ies)",
        stats["catalog_updated"],
    )
    logger.info("catalog distribution before: %s", stats["catalog_before"])
    logger.info("catalog distribution after:  %s", stats["catalog_after"])
    if stats["dry_run"]:
        logger.info("DRY-RUN: no changes were written to the database.")


def migrate(conn: sqlite3.Connection, source: str = "unionmonthly", dry_run: bool = False) -> dict:
    """Migrate unionmonthly price_plans / catalog values on an open connection.

    Single BEGIN IMMEDIATE transaction; on --dry-run nothing is written
    (would-change counts are returned instead) and the transaction is rolled
    back. Returns per-step statistics.
    """
    stats: dict = {
        "source": source,
        "dry_run": dry_run,
        "plans_scanned": 0,
        "properties_scanned": 0,
        "renamed_semi_short": 0,
        "unit_updated": 0,
        "unit_updated_per_day": 0,
        "unit_updated_per_month": 0,
        "duration_updated": 0,
        "duration_parse_hits": 0,
        "duration_band_fallback_min": 0,
        "duration_band_fallback_max": 0,
        "catalog_updated": 0,
        "catalog_before": {},
        "catalog_after": {},
    }

    cur = conn.cursor()
    owned_txn = not conn.in_transaction
    if owned_txn:
        cur.execute("BEGIN IMMEDIATE")

    try:
        plans = _load_target_plans(cur, source)
        current_catalog = _load_target_catalog(cur, source)
        stats["plans_scanned"] = len(plans)
        stats["properties_scanned"] = len(current_catalog)
        stats["catalog_before"] = catalog_distribution(current_catalog.values())

        # Safety check before any write: 'セミショート' + 'semi_short' on one property
        _check_rename_collision(plans)

        fixes = _compute_plan_fixes(plans)
        catalog_updates, new_catalog = _compute_catalog_updates(
            fixes["corrected_plans"], current_catalog
        )

        stats["renamed_semi_short"] = len(fixes["rename_rows"])
        stats["unit_updated"] = len(fixes["unit_rows"])
        stats["unit_updated_per_day"] = fixes["unit_per_day"]
        stats["unit_updated_per_month"] = fixes["unit_per_month"]
        stats["duration_updated"] = len(fixes["duration_rows"])
        stats["duration_parse_hits"] = fixes["parse_hits"]
        stats["duration_band_fallback_min"] = fixes["fallback_min"]
        stats["duration_band_fallback_max"] = fixes["fallback_max"]
        stats["catalog_updated"] = len(catalog_updates)
        stats["catalog_after"] = catalog_distribution(new_catalog.values())

        if not dry_run:
            # a. plan_key rename
            cur.executemany(
                "UPDATE price_plans SET plan_key = ? WHERE id = ?",
                [(SEMISHORT_KEY, row_id) for (row_id,) in fixes["rename_rows"]],
            )
            # b. presentation_unit
            cur.executemany(
                "UPDATE price_plans SET presentation_unit = ? WHERE id = ?",
                fixes["unit_rows"],
            )
            # c. duration bands
            cur.executemany(
                "UPDATE price_plans SET duration_min_days = ?, duration_max_days = ? WHERE id = ?",
                fixes["duration_rows"],
            )
            # d. catalog recompute
            cur.executemany(
                "UPDATE properties SET catalog_rent_per_day_yen = ? WHERE id = ?",
                catalog_updates,
            )

        if owned_txn:
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
    except Exception:
        if owned_txn:
            conn.rollback()
        raise

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate unionmonthly price_plans (plan_key normalization, "
            "presentation_unit, duration bands, catalog recompute)."
        )
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite (v2) database file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report would-change counts without writing"
    )
    parser.add_argument(
        "--source", default="unionmonthly", help="Target source_site (default: unionmonthly)"
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        logger.error("Database file does not exist: %s", args.db)
        return 2

    if not args.dry_run:
        backup_path = f"{args.db}.bak"
        shutil.copy2(args.db, backup_path)
        logger.info("Created database backup at: %s", backup_path)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        stats = migrate(conn, source=args.source, dry_run=args.dry_run)
    except MigrationError as exc:
        logger.error("Migration aborted: %s", exc)
        return 1
    finally:
        conn.close()

    _print_report(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
