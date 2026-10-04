"""DeepSeek reasoning_content 連携のための monkey-patch 群。

旧 agent_service.py は import 副作用として 3 つのパッチを適用していたため、
agent_service を import しただけで LangChain / ag-ui / copilotkit スタック
全体がロードされ、パッチ適用も暗黙だった。web 層のパッケージ化に合わせて
本モジュールへ分離し、`apply_agent_patches()` の明示適用に変更した。

- web.app.create_app() が起動時に呼び出す
- agent_service._build_graph() も防御的に呼び出す (graph 生成後の実行時に
  パッチが効いていないと reasoning_content が失われるため。冪等)

パッチ内容 (挙動は旧実装から変更なし):
1. langchain_openai の messages 変換に reasoning_content を伝播
   (DeepSeek の thinking 出力を API リクエストへ載せ替える)
2. ag-ui の messages 変換で reasoning メッセージを AIMessage.additional_kwargs
   へ復元 (近傍フォールバック含む)
3. CopilotKitMiddleware の after_model / after_agent で additional_kwargs を
   state の元メッセージから復元
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, List, Literal

from langchain_core.messages import AIMessage, BaseMessage

import ag_ui_langgraph.agent as _agui_agent
import ag_ui_langgraph.utils as _agui_utils
import langchain_openai.chat_models.base as _lc_openai_base
from copilotkit.copilotkit_lg_middleware import CopilotKitMiddleware

_applied = False

# ---------------------------------------------------------------------------
# DeepSeek thinking mode patch
# ---------------------------------------------------------------------------
_original_convert_message_to_dict = _lc_openai_base._convert_message_to_dict


def _convert_message_to_dict_with_reasoning(
    message: BaseMessage,
    api: Literal["chat/completions", "responses"] = "chat/completions",
) -> dict:
    message_dict = _original_convert_message_to_dict(message, api=api)
    if isinstance(message, AIMessage):
        rc = message.additional_kwargs.get("reasoning_content")
        if rc is not None:
            message_dict["reasoning_content"] = rc
    return message_dict


# ---------------------------------------------------------------------------
# ag-ui reasoning patch
# ---------------------------------------------------------------------------
_original_agui_messages_to_langchain = _agui_utils.agui_messages_to_langchain


def _agui_messages_to_langchain_with_reasoning(messages: List[Any]) -> List[BaseMessage]:
    reasoning_by_id = {}
    reasoning_list = []
    for idx, msg in enumerate(messages):
        role = getattr(msg, "role", None)
        if role == "reasoning":
            content = getattr(msg, "content", "")
            msg_id = getattr(msg, "id", None)
            if content and msg_id:
                reasoning_by_id[msg_id] = content
                reasoning_list.append((idx, content))

    langchain_messages = _original_agui_messages_to_langchain(messages)

    for msg in langchain_messages:
        if isinstance(msg, AIMessage):
            if msg.id in reasoning_by_id:
                msg.additional_kwargs["reasoning_content"] = reasoning_by_id[msg.id]
                continue

            orig_msg = next(
                (m for m in messages if getattr(m, "id", None) == msg.id and getattr(m, "role", None) == "assistant"),
                None,
            )
            if orig_msg:
                rc = None
                if hasattr(orig_msg, "reasoning_content"):
                    rc = orig_msg.reasoning_content
                elif hasattr(orig_msg, "reasoning"):
                    rc = orig_msg.reasoning
                elif hasattr(orig_msg, "model_extra") and orig_msg.model_extra:
                    rc = orig_msg.model_extra.get("reasoning_content") or orig_msg.model_extra.get("reasoning")
                if rc:
                    msg.additional_kwargs["reasoning_content"] = rc
                    continue

            orig_idx = None
            for idx, orig_msg in enumerate(messages):
                if getattr(orig_msg, "id", None) == msg.id and getattr(orig_msg, "role", None) == "assistant":
                    orig_idx = idx
                    break

            if orig_idx is not None:
                best_content = None
                min_dist = float("inf")
                for r_idx, r_content in reasoning_list:
                    dist = abs(orig_idx - r_idx)
                    if dist < min_dist:
                        min_dist = dist
                        best_content = r_content
                if best_content and min_dist <= 2:
                    msg.additional_kwargs["reasoning_content"] = best_content

    return langchain_messages


# ---------------------------------------------------------------------------
# copilotkit additional_kwargs (reasoning) patch
# ---------------------------------------------------------------------------
_original_after_model = CopilotKitMiddleware.after_model
_original_after_agent = CopilotKitMiddleware.after_agent


def _after_model_with_reasoning(self, state, runtime):
    res = _original_after_model(self, state, runtime)
    if res and "messages" in res:
        # Restore additional_kwargs of the last message (AIMessage) from state
        orig_msg = state.get("messages", [])[-1]
        res["messages"][-1].additional_kwargs = deepcopy(orig_msg.additional_kwargs)
    return res


def _after_agent_with_reasoning(self, state, runtime):
    res = _original_after_agent(self, state, runtime)
    if res and "messages" in res:
        # Restore additional_kwargs of AIMessages from original state messages
        orig_messages = state.get("messages", [])
        orig_by_id = {m.id: m for m in orig_messages if m.id}
        for msg in res["messages"]:
            if isinstance(msg, AIMessage) and msg.id in orig_by_id:
                msg.additional_kwargs = deepcopy(orig_by_id[msg.id].additional_kwargs)
    return res


def apply_agent_patches() -> None:
    """3 つの monkey-patch を適用する (冪等)。

    create_app() / _build_graph() から明示呼び出しされる。二重適用すると
    after_model / after_agent が自己ラップして無限再帰するためガードする。
    """
    global _applied
    if _applied:
        return
    _lc_openai_base._convert_message_to_dict = _convert_message_to_dict_with_reasoning
    _agui_utils.agui_messages_to_langchain = _agui_messages_to_langchain_with_reasoning
    _agui_agent.agui_messages_to_langchain = _agui_messages_to_langchain_with_reasoning
    CopilotKitMiddleware.after_model = _after_model_with_reasoning
    CopilotKitMiddleware.after_agent = _after_agent_with_reasoning
    _applied = True
