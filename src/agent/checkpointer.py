"""LangGraph チェックポイント (AsyncSqliteSaver) の共有管理。

旧来は agent_service.py と chat_threads.py の双方にチェックポイント DB
パスと checkpointer 管理が重複していた (層跨ぎ: chat_threads → agent_service
の Function 内 import)。本モジュールへの一本化で菱形の共有点とする。

- agent_service (graph 生成時に checkpointer を接続)
- chat_threads (スレッド一覧 / 履歴 / 削除)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Checkpoint DB path. Agent runs are async → must use AsyncSqliteSaver (not sync SqliteSaver).
_CHECKPOINT_DB = os.environ.get(
    "YADOKARIMUT_CHECKPOINT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "agent_checkpoints.db"),
)

_checkpointer_instance = None
_checkpoint_conn = None


def checkpoint_db_path() -> str:
    """チェックポイント DB の絶対パス (存在確認 / 直 SQL フォールバック用)。"""
    return os.path.abspath(_CHECKPOINT_DB)


async def get_checkpointer():
    """Return a long-lived async checkpointer (AsyncSqliteSaver or MemorySaver)."""
    global _checkpointer_instance, _checkpoint_conn
    if _checkpointer_instance is not None:
        return _checkpointer_instance

    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        os.makedirs(os.path.dirname(os.path.abspath(_CHECKPOINT_DB)), exist_ok=True)
        _checkpoint_conn = await aiosqlite.connect(_CHECKPOINT_DB)
        saver = AsyncSqliteSaver(_checkpoint_conn)
        await saver.setup()
        _checkpointer_instance = saver
        logger.info("Using AsyncSqliteSaver checkpointer at %s", _CHECKPOINT_DB)
        return _checkpointer_instance
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver

        logger.warning("AsyncSqliteSaver unavailable (%s); using MemorySaver", e)
        _checkpointer_instance = MemorySaver()
        return _checkpointer_instance


async def _cleanup_checkpointer():
    global _checkpointer_instance, _checkpoint_conn
    conn = _checkpoint_conn
    _checkpoint_conn = None
    _checkpointer_instance = None
    if conn is not None:
        try:
            await conn.close()
        except Exception as e:
            logger.warning("Failed to close checkpoint DB: %s", e)
