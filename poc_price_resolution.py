#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PoC CLI: detect corrupted rent snapshots and show mechanical resolution.

Read-only against the DB by default (no writes).

Examples:
  PYTHONPATH=src .venv/bin/python3 poc_price_resolution.py --demo
  PYTHONPATH=src .venv/bin/python3 poc_price_resolution.py --property-id 2437
  PYTHONPATH=src .venv/bin/python3 poc_price_resolution.py --scan --on-date 2026-07-20
  PYTHONPATH=src .venv/bin/python3 poc_price_resolution.py --scan --json out/price_resolution_poc.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Allow running from repo root without installing the package
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from database import DB_PATH  # noqa: E402
from price_resolution import (  # noqa: E402
    resolve_property,
    scan_db_for_suspicious_property_ids,
    today_jst,
)

# Well-known samples from investigation
DEMO_PROPERTY_IDS = [2437, 124, 2446, 1154, 1155, 1158, 1159]


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise SystemExit(f"DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_property(conn: sqlite3.Connection, property_id: int) -> tuple[str, list[dict], list[dict]]:
    row = conn.execute(
        "SELECT id, title FROM properties WHERE id = ?", (property_id,)
    ).fetchone()
    if not row:
        raise SystemExit(f"property id={property_id} not found")
    title = row["title"] or f"id={property_id}"
    plans = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, property_id, plan_code, plan_name, available, campaign_label,
                   original_daily_rent_yen, discounted_daily_rent_yen,
                   original_total_yen, discounted_total_yen, total_period_days,
                   management_fee_daily_yen, cleaning_fee_yen, raw_text
            FROM rent_plans WHERE property_id = ? ORDER BY id
            """,
            (property_id,),
        )
    ]
    cams = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM campaigns WHERE property_id = ?", (property_id,)
        )
    ]
    return title, plans, cams


def _fmt_yen(v: int | None) -> str:
    if v is None:
        return "—"
    return f"{v:,}"


def print_property_report(summary, *, verbose: bool = True) -> None:
    bar = "=" * 72
    print(bar)
    print(
        f"#{summary.property_id} {summary.title}  "
        f"status={summary.property_status}  "
        f"min_resolved={_fmt_yen(summary.min_resolved_daily)}  "
        f"min_legacy_eff={_fmt_yen(summary.min_legacy_effective_daily)}"
    )
    if summary.notes:
        for n in summary.notes:
            print(f"  note: {n}")
    print(
        f"{'plan':<10} {'src_disc':>10} {'legacy_eff':>10} {'resolved':>10} "
        f"{'status':<18} method"
    )
    print("-" * 72)
    for p in summary.plan_results:
        code = (p.plan_code or "?")[:10]
        print(
            f"{code:<10} {_fmt_yen(p.source_discounted_daily_rent_yen):>10} "
            f"{_fmt_yen(p.legacy_effective_daily_yen):>10} "
            f"{_fmt_yen(p.resolved_daily_rent_yen):>10} "
            f"{p.resolution_status:<18} {p.resolution_method}"
        )
        if verbose:
            if p.issues:
                codes = ", ".join(f"{i.code}" for i in p.issues)
                print(f"           issues: {codes}")
            for note in p.resolution_notes:
                print(f"           → {note}")
            if p.campaign_label:
                print(
                    f"           label={p.campaign_label}  "
                    f"orig={_fmt_yen(p.original_daily_rent_yen)}"
                )
    print()


def parse_on_date(text: str | None) -> date | None:
    if not text:
        return None
    if text.lower() in ("today", "jst", "now"):
        return today_jst()
    return date.fromisoformat(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PoC: rent plan corruption detection + mechanical resolution (read-only)"
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("YADOKARIMUT_DB_PATH", DB_PATH),
        help="SQLite path (default: project yadokari_mut.db)",
    )
    parser.add_argument("--property-id", type=int, action="append", dest="property_ids")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run known broken samples from investigation",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan entire DB for suspicious plans",
    )
    parser.add_argument(
        "--on-date",
        default=None,
        help="Campaign activity date YYYY-MM-DD (default: today JST). "
        "Use 2026-07-20 to simulate while 早割 still active.",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Write full JSON report to PATH",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less per-plan detail",
    )
    args = parser.parse_args(argv)

    on_date = parse_on_date(args.on_date)
    conn = _connect(args.db)

    ids: list[int] = []
    if args.demo:
        ids.extend(DEMO_PROPERTY_IDS)
    if args.property_ids:
        ids.extend(args.property_ids)
    if args.scan:
        found = scan_db_for_suspicious_property_ids(conn)
        print(f"scan: {len(found)} suspicious property_id(s) in {args.db}")
        ids.extend(found)
    if not ids:
        parser.print_help()
        print("\nHint: try --demo or --scan or --property-id 2437")
        return 2

    # unique preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            ordered.append(i)

    print(f"DB: {args.db}")
    print(f"on_date: {on_date or today_jst()} (campaign activity)")
    print(f"properties: {len(ordered)}")
    print()

    summaries = []
    status_counts: dict[str, int] = {}
    plan_status_counts: dict[str, int] = {}
    corrected_plans = 0

    for pid in ordered:
        try:
            title, plans, cams = _load_property(conn, pid)
        except SystemExit as e:
            print(e)
            continue
        summary = resolve_property(
            pid, title, plans, cams, on_date=on_date
        )
        summaries.append(summary)
        status_counts[summary.property_status] = (
            status_counts.get(summary.property_status, 0) + 1
        )
        for p in summary.plan_results:
            plan_status_counts[p.resolution_status] = (
                plan_status_counts.get(p.resolution_status, 0) + 1
            )
            if p.resolution_status == "corrected":
                corrected_plans += 1
        print_property_report(summary, verbose=not args.quiet)

    print("=" * 72)
    print("SUMMARY")
    print(f"  properties: {len(summaries)}  {status_counts}")
    print(f"  plan statuses: {plan_status_counts}")
    print(f"  corrected plans: {corrected_plans}")
    print()
    print("Legend:")
    print("  src_disc     = rent_plans.discounted_daily_rent_yen (raw snapshot)")
    print("  legacy_eff   = same as resolved (production resolve_plan_effective_rent)")
    print("  resolved     = effective after snapshot quality gate")
    print("  status       = ok | corrected | fallback_original | unusable | uncertain")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "db": args.db,
            "on_date": str(on_date or today_jst()),
            "property_status_counts": status_counts,
            "plan_status_counts": plan_status_counts,
            "properties": [s.to_dict() for s in summaries],
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON written: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
