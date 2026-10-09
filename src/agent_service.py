import sys
import os
import logging
from typing import Optional, List, Any, Type
from pydantic import BaseModel, create_model, Field

from mcp import Client, StdioServerParameters

from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_deepseek import ChatDeepSeek
from copilotkit import CopilotKitMiddleware

from agent.checkpointer import (  # noqa: F401 — 再輸出 (テストや既存参照の互換用)
    _cleanup_checkpointer,
    get_checkpointer,
)
from agent.patches import apply_agent_patches

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """あなたはYadokariMutの優秀な物件検索アシスタントです。
MCPツールでローカルDBを検索・詳細取得・比較し、フロントエンドツールで地図UIを操作します。

【役割分担】
- 画面の絞り込み・見え方 → 必ず applyFilters（地図サイドバーのフィルタを変更。期間・priceMode 含む）
- DB上の根拠付き候補出し → search_properties / get_property_detail / compare_properties
- 曖昧な希望（雰囲気・立地の質・「静かなところ」等の構造フィルタで表現できない条件）→ search_properties の natural_query（自然文意味検索・結果は意味的な近さ順。構造フィルタと併用可）
- ショートリストのUI同期 → 必ず updateShortlist（MCP の update_shortlist は使わない）
- 建物のブックマークUI同期 → 必ず updateBuildingShortlist（MCP の update_building_shortlist は使わない・建物側は saved/none のみ）
- 一覧カード → showProperties / 比較表 → showComparison（Markdown表は禁止）。比較時は stayTotalYen と catalogDailyYen を可能な限り埋める

【価格・単位】
- maxPrice は円単位（例: 15万円 → 150000）。300000 は制限なし。

【掲載状態（is_active）】
- is_active=false の物件はサイトの掲載が終了しています。ユーザーには必ず「掲載終了」である旨を伝えること
- 掲載終了物件の価格・キャンペーンは最終取得時点の参考値。比較や提案に含める場合はその旨を添える
- 保存済み(saved)の掲載終了物件は検索結果・地図に表示が維持される（ユーザーの判断履歴として意図した挙動）

【フロントエンドツール】
- applyFilters: 地図フィルタの部分更新。priceMode=stay|catalog、checkIn/checkOut（YYYY-MM-DD）、maxPrice（stay=期間総額上限/1000000=制限なし）。reset=true で初期化。fitMap=true でフィット。
- updateShortlist: saved/hide/reject/none をDBとUIに反映
- updateBuildingShortlist: 建物の saved/none をDBとUIに反映
- focusMap / selectProperty / fitMapToFiltered / setMapProvider（dark/pale/std/satellite）
- レイヤ操作: addMapLayer / removeMapLayer / setMapLayerVisibility / setMapLayerOpacity / setMapLayerOrder。物件の災害リスク確認には flood_l2（洪水浸水想定）や dosekiryu（土石流警戒区域）等を addMapLayer で重ね、確認後は removeMapLayer で戻す
- setMapLayerOrder の layerIds は現在有効な全レイヤIDを過不足なく指定する（先頭=最前面。context の地図レイヤ構成を参照）
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
# グローバル graph インスタンス + MCPセッション管理
# ============================================================
_graph_instance = None
_mcp_client = None


async def _build_graph():
    global _graph_instance, _mcp_client
    if _graph_instance is not None:
        return _graph_instance

    # reasoning_content 連携の monkey-patch は web.app.create_app() で適用済み
    # だが、web 層を経由しない利用 (CLI / テスト等) でも欠落しないよう冪等に
    # 再適用する (import 副作用ではなく graph 生成時の明示適用)
    apply_agent_patches()

    server_params = StdioServerParameters(
        command=sys.executable,
        # mcp_server.py は本モジュールと同階層 (src/)。cwd に依存しない絶対パスで起動する
        args=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")],
        env=os.environ.copy(),
    )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

    if not api_key or "your_deepseek_api_key" in api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        temperature=0.1,
    )

    # 永続的なMCP接続を開く(v2 Client はプロトコル交渉を内包する)
    _mcp_client = Client(server_params)
    await _mcp_client.__aenter__()

    mcp_tools_resp = await _mcp_client.list_tools()
    mcp_tools = mcp_tools_resp.tools

    # MCPツールをLangChainツールに変換
    langchain_mcp_tools = []
    for t in mcp_tools:
        def make_tool_call(tool_name):
            def _sync_dummy(*args, **kwargs):
                raise NotImplementedError("This tool is async-only")

            async def _call_mcp_tool(**kwargs):
                try:
                    res = await _mcp_client.call_tool(tool_name, kwargs)
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
        if t.input_schema:
            try:
                args_schema = json_schema_to_pydantic(t.input_schema)
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


async def _cleanup_mcp():
    global _mcp_client
    if _mcp_client:
        await _mcp_client.__aexit__(None, None, None)
        _mcp_client = None
    await _cleanup_checkpointer()
