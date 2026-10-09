"""LangGraph チェックポイント (AsyncPostgresSaver) の共有管理。

SQLite→PG移行 (docs/sqlite-pg-migration-plan.md D4) により
AsyncSqliteSaver(aiosqlite)から AsyncPostgresSaver(psycopg 非同期)へ置換。
チャット履歴は移行せずリセット(空から開始)。チェックポイントは物件 DB と
同じ PostgreSQL クラスタ(``YADOKARIMUT_PG_DSN``)内の
checkpoints / checkpoint_blobs / checkpoint_writes テーブル(LangGraph 管理)に
格納される。障害時は従来どおり MemorySaver へフォールバック(揮発)。

- agent_service (graph 生成時に checkpointer を接続)
- chat_threads (スレッド一覧 / 履歴 / 削除)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_checkpointer_instance = None
_checkpoint_pool = None


async def get_checkpointer():
    """Return a long-lived async checkpointer (AsyncPostgresSaver or MemorySaver)."""
    global _checkpointer_instance, _checkpoint_pool
    if _checkpointer_instance is not None:
        return _checkpointer_instance

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        from store.pg import resolve_dsn

        # langgraph-checkpoint-postgres 3.x は psycopg の AsyncConnectionPool を受ける。
        # setup() が CREATE INDEX CONCURRENTLY を含むため autocommit 必須
        # (公式 AsyncPostgresSaver.from_conn_string と同構成)。
        _checkpoint_pool = AsyncConnectionPool(
            conninfo=resolve_dsn(),
            min_size=1,
            max_size=4,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        await _checkpoint_pool.open()
        saver = AsyncPostgresSaver(_checkpoint_pool)
        await saver.setup()
        _checkpointer_instance = saver
        logger.info("Using AsyncPostgresSaver checkpointer (PostgreSQL).")
        return _checkpointer_instance
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver

        logger.warning("AsyncPostgresSaver unavailable (%s); using MemorySaver", e)
        _checkpointer_instance = MemorySaver()
        return _checkpointer_instance


async def _cleanup_checkpointer():
    global _checkpointer_instance, _checkpoint_pool
    pool = _checkpoint_pool
    _checkpoint_pool = None
    _checkpointer_instance = None
    if pool is not None:
        try:
            await pool.close()
        except Exception as e:
            logger.warning("Failed to close checkpoint pool: %s", e)
