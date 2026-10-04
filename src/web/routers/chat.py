"""チャットスレッド管理 (チェックポイント DB-backed)。

チェックポイント管理の正本は agent.checkpointer (agent_service と共有)。
"""

from fastapi import APIRouter, HTTPException, Query

import api_models

router = APIRouter()


@router.get("/api/chat/threads", response_model=api_models.ChatThreadsResponse)
async def list_chat_threads(limit: int = Query(100, ge=1, le=500)):
    """List past chat sessions stored in the agent checkpoint DB."""
    from chat_threads import list_threads

    threads = await list_threads(limit=limit)
    return {"threads": threads}


@router.get(
    "/api/chat/threads/{thread_id}/messages",
    response_model=api_models.ChatThreadMessagesResponse,
)
async def get_chat_thread_messages(thread_id: str):
    """Return AG-UI-friendly messages for a checkpoint thread."""
    from chat_threads import get_thread_messages

    messages = await get_thread_messages(thread_id)
    return {"threadId": thread_id, "messages": messages}


@router.delete(
    "/api/chat/threads/{thread_id}",
    response_model=api_models.ChatThreadDeleteResponse,
)
async def delete_chat_thread(thread_id: str):
    """Delete a chat thread's checkpoints."""
    from chat_threads import delete_thread

    result = await delete_thread(thread_id)
    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message") or "delete failed")
    return result
