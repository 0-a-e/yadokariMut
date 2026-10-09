#!/usr/bin/env python3
"""本番 SQLite(v5) → PostgreSQL 移行ツール (docs/sqlite-pg-migration-plan.md Phase 5・E4)。

- SQLite を行単位で読み、psycopg の COPY で PG へ投入(IDENTITY 列は明示 id 挿入)
- 投入後に IDENTITY シーケンスを setval(次回採番が最大 id+1 になるよう)
- 検証: 全テーブルの行数 + 主キー順正規化チェックサムの一致(データ完全性)、
  代表クエリの件数レポート(geojson / 検索 / 価格トレンド)
- schema_meta は移行対象外(版管理は alembic_version・feature_dict_hash は起動時同期)

使用例:
    python3 scripts/migrations/migrate_sqlite_to_pg.py \
        --sqlite /app/yadokari_mut_v2.db --dbname property
    # 再検証のみ:
    python3 scripts/migrations/migrate_sqlite_to_pg.py \
        --sqlite /app/yadokari_mut_v2.db --dbname property --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# FK 参照順(親が先)。schema_meta は対象外(モジュール docstring参照)。
TABLES = [
    "buildings",
    "properties",
    "property_accesses",
    "property_images",
    "property_links",
    "property_features",
    "price_plans",
    "campaigns",
    "property_snapshots",
    "raw_pages",
    "property_shortlists",
    "scrape_runs",
    "scrape_run_targets",
    "rotation_state",
    "app_settings",
    "building_names",
    "building_shortlists",
]

IDENTITY_TABLES = [
    t
    for t in TABLES
    if t not in ("rotation_state", "app_settings", "building_names")
]


def _sqlite_side(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pg_side(dbname: str):
    import psycopg

    return psycopg.connect(_pg_dsn(dbname))


def _pg_dsn(dbname: str) -> str:
    import os
    from urllib.parse import urlsplit, urlunsplit

    from store.pg import resolve_dsn

    base = os.environ.get("YADOKARIMUT_PG_DSN") or resolve_dsn()
    parts = urlsplit(base)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _columns(sconn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in sconn.execute(f"PRAGMA table_info({table})")]


def migrate(sconn: sqlite3.Connection, pg, dbname: str) -> dict[str, int]:
    rows_migrated: dict[str, int] = {}
    with pg.cursor() as cur:
        for table in TABLES:
            cols = _columns(sconn, table)
            col_list = ", ".join(f'"{c}"' for c in cols)
            rows = sconn.execute(f"SELECT {col_list} FROM {table}").fetchall()
            if rows:
                with cur.copy(f'COPY "{table}" ({col_list}) FROM STDIN') as cp:
                    for row in rows:
                        cp.write_row(tuple(row))
            rows_migrated[table] = len(rows)
        # IDENTITY シーケンス同期(明示 id 挿入に追随)
        for table in IDENTITY_TABLES:
            cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'),"
                " COALESCE((SELECT MAX(id) FROM " + f'"{table}"' + "), 1))",
                (table,),
            )
    pg.commit()
    return rows_migrated


def _canonical_checksum(rows: list) -> str:
    """PK 順に並べた行の正規化チェックサム(移行元/先で同一であることの証明)。"""
    h = hashlib.sha256()
    for row in rows:
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]



def verify(sconn: sqlite3.Connection, pg) -> dict:
    """行数 + 正規化チェックサムの一致検証。

    - 列順は PG 側 information_schema の ordinal_position を正とし両側で同一列順で
      取得する(SQLite の ALTER 追加列は物理末尾に位置し列順が変わるため)
    - 行の並びは Python 側で repr ソート(両 DB の照合順序差を排除した決定論順)
    """
    report: dict = {}
    with pg.cursor() as cur:
        for table in TABLES:
            cols = [
                r[0]
                for r in cur.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema='public' AND table_name=%s"
                    " ORDER BY ordinal_position",
                    (table,),
                )
            ]
            col_list = ", ".join(f'"{c}"' for c in cols)
            s_rows = sorted(
                (tuple(r) for r in sconn.execute(f"SELECT {col_list} FROM {table}")),
                key=repr,
            )
            p_rows = sorted(
                (tuple(r) for r in cur.execute(f'SELECT {col_list} FROM "{table}"')),
                key=repr,
            )
            s_sum = _canonical_checksum(s_rows)
            p_sum = _canonical_checksum(p_rows)
            report[table] = {
                "sqlite_rows": len(s_rows),
                "pg_rows": len(p_rows),
                "checksum_match": s_sum == p_sum and len(s_rows) == len(p_rows),
            }
    return report


def semantic_report(dbname: str) -> dict:
    """移行後 PG に対する代表クエリの件数レポート(受け入れ記録用)。"""
    import os

    old = os.environ.get("YADOKARIMUT_PG_DSN")
    os.environ["YADOKARIMUT_PG_DSN"] = _pg_dsn(dbname)
    try:
        from store.queries.buildings import iter_geojson_building_features
        from store.queries.price_history import get_price_trend
        from store.queries.search import iter_search_properties

        geo = sum(1 for _ in iter_geojson_building_features())
        search = sum(1 for _ in iter_search_properties({"limit": 10000}))
        trend = get_price_trend(days=90)
        return {
            "geojson_features": geo,
            "search_rows": search,
            "trend_meta": trend["meta"],
            "trend_carried_days": len(trend["series"]["carried"]["all"]),
        }
    finally:
        if old is None:
            os.environ.pop("YADOKARIMUT_PG_DSN", None)
        else:
            os.environ["YADOKARIMUT_PG_DSN"] = old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", required=True, help="移行元 SQLite(v5)のパス")
    ap.add_argument("--dbname", default="property", help="移行先 PG database 名")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="データ投入をスキップし検証だけ実行(投入済み DB 向け)",
    )
    args = ap.parse_args()

    sconn = _sqlite_side(args.sqlite)
    pg = _pg_side(args.dbname)

    if not args.verify_only:
        counts = migrate(sconn, pg, args.dbname)
        print("[MIGRATED]", json.dumps(counts, ensure_ascii=False))

    report = verify(sconn, pg)
    ok = True
    for table, r in report.items():
        mark = "OK " if r["checksum_match"] else "NG!"
        if not r["checksum_match"]:
            ok = False
        print(f"  {mark} {table}: sqlite={r['sqlite_rows']} pg={r['pg_rows']}")
    print("[SEMANTIC]", json.dumps(semantic_report(args.dbname), ensure_ascii=False))

    if not ok:
        print("VERIFICATION FAILED — チェックサム不一致のテーブルがあります", file=sys.stderr)
        return 1
    print("VERIFICATION PASSED — 全テーブルの行数・チェックサムが一致しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
