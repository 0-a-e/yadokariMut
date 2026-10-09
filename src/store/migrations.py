"""Alembic のプログラム実行入口 (db-init CLI / テスト基盤から利用)。

スキーマ変更の正本は src/alembic/versions/ 配下のリビジョン。Alembic 実行は
``alembic -c src/alembic.ini upgrade head`` と同等だが、CLI・テストからは
本モジュール経由で呼ぶ(DSN は store.pg.resolve_dsn を共用)。
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


def upgrade_head() -> None:
    """ベースラインから最新リビジョンまで適用(未適用分のみ・冪等)。"""
    command.upgrade(_config(), "head")


def current() -> str | None:
    """現在適用済みのリビジョン(未適用時 None)。"""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    from store.pg import resolve_dsn

    url = resolve_dsn().replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
