"""時刻列 TEXT ISO8601 → timestamptz 化 + campaigns 日付列 DATE 化 (PG移行 Phase 6c・D8/D9-4/5)。

docs/sqlite-pg-migration-plan.md §4 Phase 6c。

- 全時刻列(21 列)を timestamptz へ。既存値は naive JST 文字列のため
  ``USING col::timestamp AT TIME ZONE 'Asia/Tokyo'`` で JST 解釈した絶対時刻へ
  (text 直接の AT TIME ZONE は不可・二段キャスト必須)。NULL は NULL のまま
- campaigns.starts_on / ends_on は日付のみ(YYYY-MM-DD)のため timestamptz
  対象外とし DATE 型化(``USING col::date``)
- セッション TZ=Asia/Tokyo はアプリ側(src/store/pg.py の接続 options)で
  固定済み。リビジョン自体は TZ 非依存(絶対変換を明示)

変換量の実績値(Phase 0 記録): snapshots 141,162 / images 166,348 /
features 系は対象外。ALTER は ACCESS EXCLUSIVE ロック下で数秒〜数十秒。

Revision ID: timestamptz
Revises: jsonbize
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "timestamptz"
down_revision: Union[str, None] = "jsonbize"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column)
_TS_COLUMNS = [
    ("buildings", "first_seen_at"),
    ("buildings", "last_seen_at"),
    ("building_shortlists", "updated_at"),
    ("property_shortlists", "updated_at"),
    ("properties", "first_seen_at"),
    ("properties", "last_seen_at"),
    ("properties", "detail_scraped_at"),
    ("property_images", "scraped_at"),
    ("property_links", "scraped_at"),
    ("price_plans", "scraped_at"),
    ("campaigns", "scraped_at"),
    ("property_snapshots", "scraped_at"),
    ("raw_pages", "fetched_at"),
    ("scrape_runs", "started_at"),
    ("scrape_runs", "finished_at"),
    ("scrape_run_targets", "started_at"),
    ("scrape_run_targets", "finished_at"),
    ("rotation_state", "last_full_ok_at"),
    ("rotation_state", "last_run_at"),
    ("rotation_state", "updated_at"),
    ("app_settings", "updated_at"),
]


def upgrade() -> None:
    for table, column in _TS_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE TIMESTAMPTZ USING {column}::timestamp AT TIME ZONE 'Asia/Tokyo'"
        )
    for column in ("starts_on", "ends_on"):
        op.execute(
            f"ALTER TABLE campaigns ALTER COLUMN {column} "
            f"TYPE DATE USING {column}::date"
        )


def downgrade() -> None:
    for column in ("starts_on", "ends_on"):
        op.execute(
            f"ALTER TABLE campaigns ALTER COLUMN {column} "
            f"TYPE TEXT USING {column}::text"
        )
    for table, column in _TS_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE TEXT USING ({column} AT TIME ZONE 'Asia/Tokyo')::text"
        )
