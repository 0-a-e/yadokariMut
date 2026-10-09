"""Alembic 環境 (PostgreSQL・生SQLリビジョン方式)。

DSN は store.pg.resolve_dsn (YADOKARIMUT_PG_DSN) を共用する。
autogenerate は使わない(リビジョンは手書きSQL・op.execute ベース)。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# src/ を import パスへ(standalone 実行時)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store.pg import resolve_dsn  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    # SQLAlchemy は postgresql:// を psycopg2 と解釈するため psycopg3 を明示
    resolve_dsn().replace("postgresql://", "postgresql+psycopg://", 1),
)

target_metadata = None


def run_migrations_offline() -> None:
    """offline モード (SQL ダンプのみ・未使用だが既定挙動として維持)。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online モード (実際に PG へ接続して実行)。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
