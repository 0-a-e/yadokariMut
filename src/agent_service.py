import sys
import os
import logging
from typing import Optional, List, Dict, Any, Type, Literal
from pydantic import BaseModel, create_model, Field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_core.tools import StructuredTool
from langchain_core.messages import AIMessage, BaseMessage
from langchain_deepseek import ChatDeepSeek
from langchain.agents import create_agent
from copilotkit import CopilotKitMiddleware
from langgraph.checkpoint.memory import MemorySaver

import langchain_openai.chat_models.base as _lc_openai_base

logger = logging.getLogger(__name__)

# Checkpoint DB path. Agent runs are async → must use AsyncSqliteSaver (not sync SqliteSaver).
_CHECKPOINT_DB = os.environ.get(
    "YADOKARIMUT_CHECKPOINT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "agent_checkpoints.db"),
)

_checkpointer_instance = None
_checkpoint_conn = None


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


_lc_openai_base._convert_message_to_dict = _convert_message_to_dict_with_reasoning

# ---------------------------------------------------------------------------
# ag-ui reasoning patch
# ---------------------------------------------------------------------------
import ag_ui_langgraph.utils as _agui_utils
import ag_ui_langgraph.agent as _agui_agent

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


_agui_utils.agui_messages_to_langchain = _agui_messages_to_langchain_with_reasoning
_agui_agent.agui_messages_to_langchain = _agui_messages_to_langchain_with_reasoning


# ---------------------------------------------------------------------------
# copilotkit additional_kwargs (reasoning) patch
# ---------------------------------------------------------------------------
from copy import deepcopy
from copilotkit.copilotkit_lg_middleware import CopilotKitMiddleware

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

CopilotKitMiddleware.after_model = _after_model_with_reasoning
CopilotKitMiddleware.after_agent = _after_agent_with_reasoning


SYSTEM_PROMPT = """あなたはYadokariMutの優秀な物件検索アシスタントです。
MCPツールでローカルDBを検索・詳細取得・比較し、フロントエンドツールで地図UIを操作します。

【役割分担】
- 画面の絞り込み・見え方 → 必ず applyFilters（地図サイドバーのフィルタを変更。期間・priceMode 含む）
- DB上の根拠付き候補出し → search_properties / get_property_detail / compare_properties
- ショートリストのUI同期 → 必ず updateShortlist（MCP の update_shortlist は使わない）
- 一覧カード → showProperties / 比較表 → showComparison（Markdown表は禁止）。比較時は stayTotalYen と catalogDailyYen を可能な限り埋める

【価格・単位】
- maxPrice は円単位（例: 15万円 → 150000）。300000 は制限なし。

【フロントエンドツール】
- applyFilters: 地図フィルタの部分更新。priceMode=stay|catalog、checkIn/checkOut（YYYY-MM-DD）、maxPrice（stay=期間総額上限/1000000=制限なし）。reset=true で初期化。fitMap=true でフィット。
- updateShortlist: saved/hide/reject/none をDBとUIに反映
- focusMap / selectProperty / fitMapToFiltered / setMapProvider
- showProperties / showComparison
- openOfficialSite / openGoogleEarth

【推奨フロー：絞り込み】
1. applyFilters(...) → 地図とリストを更新
2. 必要なら fitMap（applyFilters の fitMap=true でも可）
3. 上位を showProperties で提示

【推奨フロー：提案1件】
1. search_properties または現在フィルタ結果の context を参照
2. showProperties
3. focusMap + selectProperty

【推奨フロー：比較】
1. compare_properties または保存済みIDを収集
2. showComparison で表表示
3. 必要なら focusMap / selectProperty

フィルタ後0件なら条件を緩めて applyFilters を再実行すること。
"""


def json_schema_to_pydantic(schema_dict: dict) -> Type[BaseModel]:
    properties = schema_dict.get("properties", {})
    required_fields = schema_dict.get("required", [])

    fields = {}
    for name, prop in properties.items():
        prop_type = prop.get("type")
        description = prop.get("description", "")

        py_type = Any
        if prop_type == "string":
            py_type = str
        elif prop_type == "integer":
            py_type = int
        elif prop_type == "number":
            py_type = float
        elif prop_type == "boolean":
            py_type = bool
        elif prop_type == "array":
            items_type = prop.get("items", {}).get("type")
            if items_type == "string":
                py_type = List[str]
            elif items_type == "integer":
                py_type = List[int]
            else:
                py_type = List[Any]

        if name not in required_fields:
            py_type = Optional[py_type]
            default = None
        else:
            default = ...

        fields[name] = (py_type, Field(default=default, description=description))

    return create_model("DynamicMcpToolModel", **fields)


# ============================================================
# フロントエンドツールのスキーマ定義
# エージェント（LLM）に渡すためのダミー実装付きLangChainツール
# 実際の実行はフロントエンド側の onFrontendToolCall で行われる
# ============================================================

class FocusMapArgs(BaseModel):
    lat: float = Field(..., description="緯度（例: 35.6812）")
    lng: float = Field(..., description="経度（例: 139.7671）")
    zoom: Optional[int] = Field(None, description="ズームレベル（1〜20、デフォルト15）")


class SelectPropertyArgs(BaseModel):
    id: int = Field(..., description="物件のID（properties.id）")


class FitMapToFilteredArgs(BaseModel):
    pass


class PropertyInfo(BaseModel):
    id: int = Field(..., description="物件のID")
    title: str = Field(..., description="物件のタイトル/名称")
    rent: int = Field(..., description="家賃（円）")
    layout: str = Field(..., description="間取り（例: 1K, 1DK）")
    area: float = Field(..., description="専有面積（㎡）")
    address: str = Field(..., description="住所")
    score: Optional[float] = Field(None, description="物件のスコア（例: 82.5）")
    station_walk: Optional[str] = Field(None, description="最寄り駅と徒歩分数（例: 心斎橋駅 徒歩10分）")


class ShowPropertiesArgs(BaseModel):
    properties: List[PropertyInfo] = Field(..., description="提示する物件のリスト")
    title: Optional[str] = Field("物件一覧", description="表示するセクションのタイトル")


class SetMapProviderArgs(BaseModel):
    provider: Literal["dark", "pale", "satellite"] = Field(
        ...,
        description="地図プロバイダの種類。'dark' (ダークテーマ)、'pale' (淡色日本語地図)、'satellite' (航空写真)のいずれか。"
    )


class ApplyFiltersArgs(BaseModel):
    reset: Optional[bool] = Field(None, description="trueなら全フィルターを初期値に戻してから適用")
    priceMode: Optional[Literal["stay", "catalog"]] = Field(
        None,
        description="stay=期間総額比較（既定）/ catalog=カタログ価格",
    )
    checkIn: Optional[str] = Field(None, description="入居日 YYYY-MM-DD（stay で使用）")
    checkOut: Optional[str] = Field(None, description="退去日 YYYY-MM-DD（stay で使用）")
    maxPrice: Optional[int] = Field(
        None,
        description=(
            "価格上限（円）。stay 時は期間総額（1000000=制限なし）、"
            "catalog 時は月額相当（300000=制限なし）"
        ),
    )
    minArea: Optional[float] = Field(None, description="面積下限㎡")
    maxArea: Optional[float] = Field(None, description="面積上限㎡")
    layout: Optional[str] = Field(None, description="間取り。'all'|'1R'|'1K'|'1DK'|'1LDK' 等")
    status: Optional[Literal["all", "saved", "unsaved", "hide", "reject"]] = Field(
        None, description="ショートリスト状態フィルタ"
    )
    searchQuery: Optional[str] = Field(None, description="フリーワード")
    maxWalkMinutes: Optional[int] = Field(None, description="徒歩分上限")
    minScore: Optional[float] = Field(None, description="スコア下限")
    prefecture: Optional[str] = Field(None, description="都道府県名（例: 東京都）")
    requiredFeatures: Optional[List[str]] = Field(None, description="必須設備（部分一致AND）")
    sortBy: Optional[Literal["score", "price_asc", "price_desc", "area_desc"]] = None
    boundsEnabled: Optional[bool] = Field(None, description="地図表示範囲で絞り込むか")
    fitMap: Optional[bool] = Field(None, description="適用後に地図をフィット")


class UpdateShortlistArgs(BaseModel):
    id: int = Field(..., description="物件ID")
    status: Literal["saved", "hide", "reject", "none"] = Field(..., description="ショートリスト状態")
    comment: Optional[str] = Field(None, description="任意コメント")


class OpenByIdArgs(BaseModel):
    id: int = Field(..., description="物件のID（properties.id）")


class ComparisonProperty(BaseModel):
    id: int
    title: str
    rent: Optional[int] = Field(None, description="レガシー: カタログ日額など（円）")
    catalogDailyYen: Optional[int] = Field(None, description="カタログ有効日額（円/日）")
    stayTotalYen: Optional[int] = Field(None, description="現在の期間での試算総額（円）")
    stayDays: Optional[int] = Field(None, description="滞在日数")
    layout: Optional[str] = None
    area: Optional[float] = None
    walkMinutes: Optional[float] = None
    score: Optional[float] = None
    address: Optional[str] = None
    features: Optional[str] = None
    shortlistStatus: Optional[str] = None


class ShowComparisonArgs(BaseModel):
    properties: List[ComparisonProperty] = Field(..., description="比較する物件リスト")
    title: Optional[str] = Field("物件比較", description="見出し")


def _frontend_tool_stub(*args: Any, **kwargs: Any) -> str:
    """フロントエンドツールのサーバー側スタブ。実行はフロントエンドで行われる。"""
    return "This tool is executed on the frontend."


FRONTEND_TOOLS: List[StructuredTool] = [
    StructuredTool(
        name="focusMap",
        description=(
            "地図を指定された緯度経度に移動し、ズームレベルを変更する。"
            "物件をユーザーに見せたい時は必ずこのツールを呼び出すこと。"
        ),
        func=_frontend_tool_stub,
        args_schema=FocusMapArgs,
    ),
    StructuredTool(
        name="selectProperty",
        description=(
            "指定されたIDの物件を選択状態にし、詳細パネルを表示する。"
            "フィルタ外でも選択可能。focusMap と組み合わせて使用すること。"
        ),
        func=_frontend_tool_stub,
        args_schema=SelectPropertyArgs,
    ),
    StructuredTool(
        name="fitMapToFiltered",
        description="現在フィルタリングされている全物件が収まるように地図の表示範囲を自動調整する。",
        func=_frontend_tool_stub,
        args_schema=FitMapToFilteredArgs,
    ),
    StructuredTool(
        name="showProperties",
        description=(
            "検索された物件の一覧をチャットUI上にカードで表示する。"
            "Markdownリストの代わりに必ずこのツールを呼ぶこと。"
        ),
        func=_frontend_tool_stub,
        args_schema=ShowPropertiesArgs,
    ),
    StructuredTool(
        name="showComparison",
        description=(
            "複数物件を表形式で比較表示する。compare_properties の結果や保存済み比較時に使う。"
            "Markdown表の代わりに必ずこのツールを呼ぶこと。"
            "期間総額は stayTotalYen、カタログ日額は catalogDailyYen（または rent）に載せる。"
        ),
        func=_frontend_tool_stub,
        args_schema=ShowComparisonArgs,
    ),
    StructuredTool(
        name="setMapProvider",
        description="地図レイヤーを dark / pale / satellite に切り替える。",
        func=_frontend_tool_stub,
        args_schema=SetMapProviderArgs,
    ),
    StructuredTool(
        name="applyFilters",
        description=(
            "地図UIのフィルターを部分更新する。期間・価格モード含む。"
            "priceMode=stay（期間総額）/ catalog。checkIn/checkOut は YYYY-MM-DD。"
            "stay の maxPrice は期間総額上限（1000000=制限なし）。"
            "省略フィールドは変更しない。reset=true で初期化。"
        ),
        func=_frontend_tool_stub,
        args_schema=ApplyFiltersArgs,
    ),
    StructuredTool(
        name="updateShortlist",
        description=(
            "物件のショートリスト状態を更新しUIとDBを同期する。"
            "保存・見送り等では MCP update_shortlist ではなく必ずこのツールを使う。"
        ),
        func=_frontend_tool_stub,
        args_schema=UpdateShortlistArgs,
    ),
    StructuredTool(
        name="openOfficialSite",
        description="指定物件の公式サイトを新しいタブで開く。",
        func=_frontend_tool_stub,
        args_schema=OpenByIdArgs,
    ),
    StructuredTool(
        name="openGoogleEarth",
        description="指定物件の位置をGoogle Earthで新しいタブで開く。",
        func=_frontend_tool_stub,
        args_schema=OpenByIdArgs,
    ),
]



# ============================================================
# グローバル graph インスタンス + MCPセッション管理
# ============================================================
_graph_instance = None
_mcp_session = None
_mcp_context = None


async def _build_graph():
    global _graph_instance, _mcp_session, _mcp_context
    if _graph_instance is not None:
        return _graph_instance

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        env=os.environ.copy(),
    )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key or "your_deepseek_api_key" in api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        temperature=0.1,
    )

    # 永続的なMCP接続を開く
    stdio_ctx = stdio_client(server_params)
    read_stream, write_stream = await stdio_ctx.__aenter__()
    _mcp_context = stdio_ctx

    session_ctx = ClientSession(read_stream, write_stream)
    session = await session_ctx.__aenter__()
    _mcp_session = (session_ctx, session)

    await session.initialize()

    mcp_tools_resp = await session.list_tools()
    mcp_tools = mcp_tools_resp.tools

    # MCPツールをLangChainツールに変換
    langchain_mcp_tools = []
    for t in mcp_tools:
        def make_tool_call(tool_name):
            def _sync_dummy(*args, **kwargs):
                raise NotImplementedError("This tool is async-only")

            async def _call_mcp_tool(**kwargs):
                try:
                    res = await session.call_tool(tool_name, kwargs)
                    text_blocks = []
                    for block in res.content:
                        if block.type == "text":
                            text_blocks.append(block.text)
                    return "\n".join(text_blocks)
                except Exception as e:
                    logger.error(f"Error calling MCP tool {tool_name}: {e}")
                    return f"Error executing tool: {str(e)}"

            return _sync_dummy, _call_mcp_tool

        args_schema = None
        if t.inputSchema:
            try:
                args_schema = json_schema_to_pydantic(t.inputSchema)
            except Exception as e:
                logger.warning(f"Failed to generate pydantic schema for tool {t.name}: {e}")

        sync_func, async_func = make_tool_call(t.name)
        langchain_mcp_tools.append(
            StructuredTool(
                name=t.name,
                description=t.description,
                func=sync_func,
                coroutine=async_func,
                args_schema=args_schema,
            )
        )

    # MCPツールのみを graph に渡す。
    # フロントエンドツールは useFrontendTool → AG-UI / CopilotKitMiddleware 経由。
    all_tools = langchain_mcp_tools
    checkpointer = await get_checkpointer()

    agent = create_agent(
        model=llm,
        tools=all_tools,
        checkpointer=checkpointer,
        system_prompt=SYSTEM_PROMPT,
        middleware=[CopilotKitMiddleware()],
    )
    _graph_instance = agent
    return _graph_instance


def get_graph():
    return _graph_instance


async def _cleanup_mcp():
    global _mcp_session, _mcp_context
    if _mcp_session:
        session_ctx, _ = _mcp_session
        await session_ctx.__aexit__(None, None, None)
        _mcp_session = None
    if _mcp_context:
        await _mcp_context.__aexit__(None, None, None)
        _mcp_context = None
    await _cleanup_checkpointer()


async def run_agent_message(message: str, thread_id: str) -> Dict[str, Any]:
    """Connects to the local mcp_server.py as a subprocess, loads tools, and runs the LangGraph agent."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        env=os.environ.copy(),
    )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key or "your_deepseek_api_key" in api_key:
        return {
            "response": "エラー: DEEPSEEK_API_KEY が環境変数または .env ファイルに設定されていません。",
            "steps": [],
        }

    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        temperature=0.1,
    )

    steps = []

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            mcp_tools_resp = await session.list_tools()
            mcp_tools = mcp_tools_resp.tools

            langchain_tools = []
            for t in mcp_tools:
                def make_tool_call(tool_name):
                    def _sync_dummy(*args, **kwargs):
                        raise NotImplementedError("This tool is async-only")

                    async def _call_mcp_tool(**kwargs):
                        steps.append({"tool": tool_name, "arguments": kwargs})
                        try:
                            res = await session.call_tool(tool_name, kwargs)
                            text_blocks = []
                            for block in res.content:
                                if block.type == "text":
                                    text_blocks.append(block.text)
                            return "\n".join(text_blocks)
                        except Exception as e:
                            logger.error(f"Error calling MCP tool {tool_name}: {e}")
                            return f"Error executing tool: {str(e)}"

                    return _sync_dummy, _call_mcp_tool

                args_schema = None
                if t.inputSchema:
                    try:
                        args_schema = json_schema_to_pydantic(t.inputSchema)
                    except Exception as e:
                        logger.warning(f"Failed to generate pydantic schema for tool {t.name}: {e}")

                sync_func, async_func = make_tool_call(t.name)
                langchain_tools.append(
                    StructuredTool(
                        name=t.name,
                        description=t.description,
                        func=sync_func,
                        coroutine=async_func,
                        args_schema=args_schema,
                    )
                )

            # run_agent_message でもフロントエンドツールを追加
            all_tools = langchain_tools + FRONTEND_TOOLS
            checkpointer = await get_checkpointer()

            agent = create_agent(
                model=llm,
                tools=all_tools,
                checkpointer=checkpointer,
                system_prompt=SYSTEM_PROMPT,
            )

            config = {"configurable": {"thread_id": thread_id}}
            result = await agent.ainvoke(
                {"messages": [("user", message)]},
                config=config,
            )

            final_message = result["messages"][-1]
            response_text = final_message.content

            return {"response": response_text, "steps": steps}