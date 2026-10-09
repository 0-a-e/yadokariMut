"""JSON 列 TEXT → jsonb 化 + scrape_runs.is_rotation 別カラム化 (PG移行 Phase 6b・D9-2/3)。

docs/sqlite-pg-migration-plan.md §4 Phase 6b。

- campaigns.raw_json / scrape_runs.meta_json / app_settings.value_json を
  jsonb 化(全データが json.dumps 出力のため形式保証付き。不正行があれば
  ALTER が失敗しロールバックされる)
- property_snapshots.raw_list_json / raw_detail_json は **DROP COLUMN**
  (本番 141,162 行すべて NULL・現行コードも未書込の死に列・D9-3)
- meta_json LIKE での rotation 抽出(dumps separators への偶然依存)を廃止し
  ``scrape_runs.is_rotation BOOLEAN NOT NULL DEFAULT FALSE`` へ正本化。
  既存行は ``meta_json @> '{"rotation": true}'`` でバックフィル。
  meta_json 内の rotation キーは履歴値として残す

Revision ID: jsonbize
Revises: booleanize
Create Date: 2026-10-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "jsonbize"
down_revision: Union[str, None] = "booleanize"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE campaigns ALTER COLUMN raw_json "
        "TYPE JSONB USING raw_json::jsonb"
    )
    op.execute(
        "ALTER TABLE scrape_runs ALTER COLUMN meta_json "
        "TYPE JSONB USING meta_json::jsonb"
    )
    op.execute(
        "ALTER TABLE app_settings ALTER COLUMN value_json "
        "TYPE JSONB USING value_json::jsonb"
    )
    op.execute("ALTER TABLE property_snapshots DROP COLUMN raw_list_json")
    op.execute("ALTER TABLE property_snapshots DROP COLUMN raw_detail_json")
    op.execute(
        "ALTER TABLE scrape_runs ADD COLUMN is_rotation BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "UPDATE scrape_runs SET is_rotation = TRUE "
        "WHERE meta_json @> '{\"rotation\": true}'::jsonb"
    )


def downgrade() -> None:
    # is_rotation の情報を meta_json へ戻してから列除去・型をもとの text へ
    op.execute(
        "UPDATE scrape_runs SET meta_json = meta_json || '{\"rotation\": true}'::jsonb "
        "WHERE is_rotation"
    )
    op.execute("ALTER TABLE scrape_runs DROP COLUMN is_rotation")
    op.execute(
        "ALTER TABLE campaigns ALTER COLUMN raw_json TYPE TEXT USING raw_json::text"
    )
    op.execute(
        "ALTER TABLE scrape_runs ALTER COLUMN meta_json TYPE TEXT USING meta_json::text"
    )
    op.execute(
        "ALTER TABLE app_settings ALTER COLUMN value_json "
        "TYPE TEXT USING value_json::text"
    )
    op.execute(
        "ALTER TABLE property_snapshots "
        "ADD COLUMN raw_list_json TEXT, ADD COLUMN raw_detail_json TEXT"
    )
