"""CopilotKit / AG-UI 直結エンドポイント。

Agent 実体は lifespan (web.app) が app.state.agent へ格納する
LangGraphAGUIAgent。本ルータは SSE で AG-UI イベントをストリーミングする。
"""

import logging

from ag_ui.core.types import RunAgentInput
from ag_ui_langgraph.endpoint import EventEncoder
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import api_models

router = APIRouter()


@router.post("/api/copilotkit")
async def copilotkit_agent_endpoint(input_data: RunAgentInput, request: Request):
    """AG-UI direct agent endpoint for CopilotKit frontend."""
    logger = logging.getLogger(__name__)
    try:
        logger.info(f"Received copilotkit request: thread_id={input_data.thread_id}, run_id={input_data.run_id}")
        logger.info(f"Input messages: {input_data.messages}")
    except Exception as e:
        logger.error(f"Failed to log request meta: {e}")

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized yet")

    encoder = EventEncoder(accept=request.headers.get("accept"))
    request_agent = agent.clone()

    async def event_generator():
        try:
            async for event in request_agent.run(input_data):
                yield encoder.encode(event)
        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)
            try:
                # Attempt to retrieve current messages in state for debugging
                from langchain_core.runnables import ensure_config
                config = ensure_config(request_agent.config.copy() if request_agent.config else {})
                config["configurable"] = {**(config.get('configurable', {})), "thread_id": input_data.thread_id}
                state = await request_agent.graph.aget_state(config)
                logger.error(f"Messages count in state: {len(state.values.get('messages', []))}")
                for i, msg in enumerate(state.values.get('messages', [])):
                    logger.error(f"Msg {i}: type={type(msg).__name__}, content={str(msg.content)[:200]}, additional_kwargs={msg.additional_kwargs if hasattr(msg, 'additional_kwargs') else None}")
            except Exception as ex:
                logger.error(f"Failed to dump messages for debug: {ex}")
            # AG-UI RunErrorEvent requires `message` (not `error`)
            from ag_ui.core import EventType, RunErrorEvent
            try:
                yield encoder.encode(
                    RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code="agent_execution_error")
                )
            except Exception:
                import json
                yield f'data: {json.dumps({"type": "RUN_ERROR", "message": str(e), "code": "agent_execution_error"})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type=encoder.get_content_type(),
    )


@router.get("/api/copilotkit/health", response_model=api_models.HealthResponse)
def copilotkit_health():
    """Health check for CopilotKit agent endpoint."""
    return {"status": "ok"}
