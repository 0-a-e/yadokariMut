#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix rent_plans total amounts corrupted by parse_money concatenating period days.

Background:
  Texts like ``(月 75,000円/30日)`` were parsed by stripping all non-digits,
  producing 7500030 instead of 75000. Same for 7-day totals
  (``(週 14,350円/7日)`` -> 143507).

This migration:
  1. Backs up the database
  2. Re-extracts original/discounted totals from rent_plans.raw_text
  3. Falls back to stripping a trailing period-days suffix when it recovers
     daily_rent * period_days
  4. Recomputes property_snapshots.min_discounted_monthly_total_yen from
     the corrected rent_plans
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from database import DB_PATH, get_db_connection

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# e.g. (月 75,000円/30日), (週 14,350円/7日), (月 -1,080,000円/30日)
TOTAL_PERIOD_RE = re.compile(
    r"[（(]\s*[週月]?\s*(-?[\d,]+)\s*円\s*/\s*(\d+)\s*日\s*[)）]"
)


def extract_totals_from_raw(raw_text: str | None) -> tuple[int | None, int | None]:
    """Return (original_total, discounted_total) from rent cell raw_text."""
    if not raw_text:
        return None, None
    matches = TOTAL_PERIOD_RE.findall(raw_text)
    if not matches:
        return None, None
    amounts = [int(m[0].replace(",", "")) for m in matches]
    if len(amounts) == 1:
        return amounts[0], amounts[0]
    return amounts[0], amounts[-1]


def recover_from_period_suffix(
    total: int | None, daily: int | None, days: int | None
) -> int | None:
    """If total looks like daily*days with days digits appended, recover daily*days."""
    if total is None or daily is None or days is None or days <= 0:
        return None
    expected = daily * days
    if total == expected:
        return total
    s = str(abs(total))
    ds = str(days)
    if not s.endswith(ds) or len(s) <= len(ds):
        return None
    fixed = int(s[: -len(ds)])
    if total < 0:
        fixed = -fixed
    if fixed == expected:
        return fixed
    return None


def fix_total(
    stored: int | None,
    raw_amount: int | None,
    daily: int | None,
    days: int | None,
) -> int | None:
    """Choose the best corrected total for a single field."""
    if raw_amount is not None:
        return raw_amount
    recovered = recover_from_period_suffix(stored, daily, days)
    if recovered is not None:
        return recovered
    return stored


def recompute_min_monthly(cursor: sqlite3.Cursor, property_id: int) -> int | None:
    cursor.execute(
        """
        SELECT discounted_total_yen, total_period_days
        FROM rent_plans
        WHERE property_id = ? AND available = 1
          AND discounted_total_yen IS NOT NULL AND total_period_days IS NOT NULL
          AND total_period_days > 0
        """,
        (property_id,),
    )
    min_monthly = None
    for total, days in cursor.fetchall():
        monthly_est = int((total / days) * 30)
        if min_monthly is None or monthly_est < min_monthly:
            min_monthly = monthly_est
    return min_monthly


def migrate(db_path: str | None = None) -> dict:
    target = db_path or DB_PATH
    logger.info(f"Target database path: {target}")

    if not os.path.exists(target):
        logger.warning("Database file does not exist. Nothing to migrate.")
        return {"updated_plans": 0, "updated_snapshots": 0}

    # Matches *.db.bak in .gitignore (same pattern as migrate_campaigns.py)
    backup_path = f"{target}.bak"
    shutil.copy2(target, backup_path)
    logger.info(f"Created database backup at: {backup_path}")

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    stats = {
        "updated_plans": 0,
        "updated_original": 0,
        "updated_discounted": 0,
        "updated_snapshots": 0,
        "skipped": 0,
        "raw_parse_hits": 0,
        "suffix_recoveries": 0,
    }

    try:
        cursor.execute(
            """
            SELECT id, property_id,
                   original_daily_rent_yen, discounted_daily_rent_yen,
                   original_total_yen, discounted_total_yen,
                   total_period_days, raw_text
            FROM rent_plans
            WHERE original_total_yen IS NOT NULL OR discounted_total_yen IS NOT NULL
            """
        )
        rows = cursor.fetchall()
        touched_properties: set[int] = set()

        for row in rows:
            plan_id = row["id"]
            property_id = row["property_id"]
            days = row["total_period_days"]
            od = row["original_daily_rent_yen"]
            dd = row["discounted_daily_rent_yen"]
            ot = row["original_total_yen"]
            dt = row["discounted_total_yen"]
            raw = row["raw_text"]

            raw_orig, raw_disc = extract_totals_from_raw(raw)
            if raw_orig is not None or raw_disc is not None:
                stats["raw_parse_hits"] += 1

            new_ot = fix_total(ot, raw_orig, od, days)
            new_dt = fix_total(dt, raw_disc, dd, days)

            if raw_orig is None and new_ot is not None and new_ot != ot:
                stats["suffix_recoveries"] += 1
            if raw_disc is None and new_dt is not None and new_dt != dt:
                stats["suffix_recoveries"] += 1

            if new_ot == ot and new_dt == dt:
                stats["skipped"] += 1
                continue

            cursor.execute(
                """
                UPDATE rent_plans
                SET original_total_yen = ?, discounted_total_yen = ?
                WHERE id = ?
                """,
                (new_ot, new_dt, plan_id),
            )
            stats["updated_plans"] += 1
            if new_ot != ot:
                stats["updated_original"] += 1
            if new_dt != dt:
                stats["updated_discounted"] += 1
            touched_properties.add(property_id)

        # Recompute snapshot monthly totals from corrected plans
        for property_id in touched_properties:
            min_monthly = recompute_min_monthly(cursor, property_id)
            if min_monthly is None:
                continue
            cursor.execute(
                """
                UPDATE property_snapshots
                SET min_discounted_monthly_total_yen = ?
                WHERE property_id = ?
                """,
                (min_monthly, property_id),
            )
            stats["updated_snapshots"] += cursor.rowcount

        conn.commit()
        logger.info(
            "Migration complete: plans=%s (orig=%s disc=%s) snapshots=%s "
            "raw_hits=%s suffix_recoveries=%s skipped=%s",
            stats["updated_plans"],
            stats["updated_original"],
            stats["updated_discounted"],
            stats["updated_snapshots"],
            stats["raw_parse_hits"],
            stats["suffix_recoveries"],
            stats["skipped"],
        )
        return stats
    except Exception:
        conn.rollback()
        logger.exception("Migration failed; restoring backup")
        conn.close()
        shutil.copy2(backup_path, target)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    migrate()
