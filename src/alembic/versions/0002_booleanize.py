"""ブール列 INTEGER 0/1 → BOOLEAN 化 (PG移行 Phase 6a・D9-1)。

docs/sqlite-pg-migration-plan.md §4 Phase 6a。対象 7 列:

- buildings.is_active / properties.is_active / property_snapshots.is_active
- price_plans.available / price_plans.utilities_included
- campaigns.parse_ok / scrape_run_targets.list_completed

`USING col::boolean`(NULL は NULL のまま維持)。DEFAULT 1/0 → true/false
(整数 DEFAULT は boolean へ自動 cast できないため DROP DEFAULT → TYPE 変更 →
SET DEFAULT の順で実行)。idx_v2_properties_active は ALTER TYPE で PG が
自動再構築する。

Revision ID: booleanize
Revises: pg_baseline
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "booleanize"
down_revision: Union[str, None] = "pg_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, new_default | None=DEFAULTなし)
_COLUMNS = [
    ("buildings", "is_active", "true"),
    ("properties", "is_active", "true"),
    ("property_snapshots", "is_active", None),
    ("price_plans", "available", "true"),
    ("price_plans", "utilities_included", "true"),
    ("campaigns", "parse_ok", "false"),
    ("scrape_run_targets", "list_completed", "false"),
]


def _convert(defaults: dict[tuple[str, str], str | None], using: str) -> None:
    for table, column, _default in _COLUMNS:
        new_default = defaults[(table, column)]
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE BOOLEAN USING {column}{using}"
        )
        if new_default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"SET DEFAULT {new_default}"
            )


def upgrade() -> None:
    _convert({(t, c): d for t, c, d in _COLUMNS}, "::boolean")


def downgrade() -> None:
    _convert(
        {
            ("buildings", "is_active"): "1",
            ("properties", "is_active"): "1",
            ("property_snapshots", "is_active"): None,
            ("price_plans", "available"): "1",
            ("price_plans", "utilities_included"): "1",
            ("campaigns", "parse_ok"): "0",
            ("scrape_run_targets", "list_completed"): "0",
        },
        "::int",
    )
