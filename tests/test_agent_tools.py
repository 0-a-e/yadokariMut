"""Unit tests for the agent system prompt contract and checkpointer setup."""
import unittest


class TestAgentTools(unittest.TestCase):
    def test_system_prompt_mentions_frontend_tools(self):
        """SYSTEM_PROMPT がフロントエンドツール(CopilotKit 経由で FE 実行)の
        使い分けを規定し続けていること。

        注: サーバ側の FRONTEND_TOOLS スタブ一覧は実行経路が
        CopilotKitMiddleware (useFrontendTool) に一本化されたため削除済み。
        ツールスキーマ自体は FE 側が提示するため、BE の契約は SYSTEM_PROMPT
        の記載のみ。
        """
        from agent_service import SYSTEM_PROMPT

        self.assertIn("applyFilters", SYSTEM_PROMPT)
        self.assertIn("updateShortlist", SYSTEM_PROMPT)
        self.assertIn("updateBuildingShortlist", SYSTEM_PROMPT)
        self.assertIn("showComparison", SYSTEM_PROMPT)
        # レイヤ操作ツール群が SYSTEM_PROMPT に記載されていること
        for layer_tool in (
            "addMapLayer",
            "removeMapLayer",
            "setMapLayerVisibility",
            "setMapLayerOpacity",
            "setMapLayerOrder",
        ):
            self.assertIn(layer_tool, SYSTEM_PROMPT)
        self.assertIn("flood_l2", SYSTEM_PROMPT)

    def test_checkpointer_type(self):
        import asyncio
        from agent_service import get_checkpointer, _cleanup_checkpointer

        async def _run():
            cp = await get_checkpointer()
            name = type(cp).__name__
            await _cleanup_checkpointer()
            return name

        name = asyncio.run(_run())
        # Prefer AsyncPostgresSaver; MemorySaver is acceptable fallback
        self.assertIn(name, ("AsyncPostgresSaver", "MemorySaver"))


if __name__ == "__main__":
    unittest.main()
