"""Chat thread listing / history / deletion against the LangGraph checkpoint DB."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

_CHECKPOINT_DB = os.environ.get(
    "YADOKARIMUT_CHECKPOINT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "agent_checkpoints.db"),
)


def _checkpoint_db_path() -> str:
    return os.path.abspath(_CHECKPOINT_DB)


async def list_threads(limit: int = 100) -> List[Dict[str, Any]]:
    """List distinct thread_ids from the checkpoints table (newest first)."""
    path = _checkpoint_db_path()
    if not os.path.exists(path):
        return []

    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        # checkpoint_id is UUID-ish but also time-ordered in LangGraph (uuid7-like prefixes).
        # Use MAX(rowid) as a practical recency signal.
        cur = await conn.execute(
            """
            SELECT thread_id,
                   COUNT(*) AS checkpoint_count,
                   MAX(rowid) AS last_rowid
            FROM checkpoints
            WHERE checkpoint_ns = '' OR checkpoint_ns IS NULL
            GROUP BY thread_id
            ORDER BY last_rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    threads: List[Dict[str, Any]] = []
    for row in rows:
        thread_id = row["thread_id"]
        preview = await _preview_for_thread(thread_id)
        threads.append(
            {
                "id": thread_id,
                "checkpointCount": row["checkpoint_count"],
                "title": preview.get("title") or f"会話 {thread_id[:8]}",
                "preview": preview.get("preview") or "",
                "updatedAt": preview.get("updatedAt"),
                "messageCount": preview.get("messageCount") or 0,
            }
        )
    return threads


async def _preview_for_thread(thread_id: str) -> Dict[str, Any]:
    messages = await get_thread_messages(thread_id)
    if not messages:
        return {"title": None, "preview": "", "messageCount": 0, "updatedAt": None}

    first_user = next((m for m in messages if m.get("role") == "user"), None)
    last = messages[-1]
    title = None
    if first_user and isinstance(first_user.get("content"), str):
        text = first_user["content"].strip().replace("\n", " ")
        title = (text[:40] + "…") if len(text) > 40 else text
    preview = ""
    if isinstance(last.get("content"), str):
        preview = last["content"].strip().replace("\n", " ")[:80]

    return {
        "title": title,
        "preview": preview,
        "messageCount": len(messages),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _message_to_dict(msg: Any) -> Optional[Dict[str, Any]]:
    """Convert LangChain message-like objects to AG-UI-friendly dicts."""
    msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
    content = getattr(msg, "content", None)
    msg_id = getattr(msg, "id", None) or f"msg-{id(msg)}"

    # Skip system / tool noise for UI history
    if msg_type in ("system", "tool", "ToolMessage"):
        return None

    role = "assistant"
    if msg_type in ("human", "user", "HumanMessage"):
        role = "user"
    elif msg_type in ("ai", "assistant", "AIMessage"):
        role = "assistant"
    elif msg_type in ("reasoning",):
        return None
    else:
        # Unknown — try class name
        name = type(msg).__name__
        if "Human" in name:
            role = "user"
        elif "AI" in name or "Assistant" in name:
            role = "assistant"
        else:
            return None

    if content is None:
        return None
    if isinstance(content, list):
        # Multimodal blocks → join text parts
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif hasattr(block, "get"):
                parts.append(str(block.get("text") or ""))
        content = "".join(parts)
    if not isinstance(content, str):
        content = str(content)
    if not content.strip():
        return None

    return {"id": str(msg_id), "role": role, "content": content}


async def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    """Load messages for a thread from the latest checkpoint via AsyncSqliteSaver."""
    try:
        from agent_service import get_checkpointer

        cp = await get_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}
        tup = await cp.aget_tuple(config)
        if not tup or not tup.checkpoint:
            return []
        values = tup.checkpoint.get("channel_values") or {}
        raw_messages = values.get("messages") or []
        out: List[Dict[str, Any]] = []
        for m in raw_messages:
            d = _message_to_dict(m)
            if d:
                out.append(d)
        return out
    except Exception as e:
        logger.warning("Failed to load messages for thread %s: %s", thread_id, e)
        return []


async def delete_thread(thread_id: str) -> Dict[str, Any]:
    """Delete all checkpoints for a thread."""
    try:
        from agent_service import get_checkpointer

        cp = await get_checkpointer()
        if hasattr(cp, "adelete_thread"):
            await cp.adelete_thread(thread_id)
        elif hasattr(cp, "delete_thread"):
            cp.delete_thread(thread_id)
        else:
            # Fallback: raw SQL
            path = _checkpoint_db_path()
            if os.path.exists(path):
                async with aiosqlite.connect(path) as conn:
                    await conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
                    await conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
                    await conn.commit()
        return {"status": "success", "thread_id": thread_id}
    except Exception as e:
        logger.exception("Failed to delete thread %s", thread_id)
        return {"status": "error", "message": str(e), "thread_id": thread_id}
