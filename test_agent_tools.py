"""Unit tests for agent frontend tool stubs and checkpointer setup."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


class TestAgentTools(unittest.TestCase):
    def test_frontend_tools_include_phase_tools(self):
        from agent_service import FRONTEND_TOOLS, SYSTEM_PROMPT

        names = {t.name for t in FRONTEND_TOOLS}
        for required in (
            "applyFilters",
            "updateShortlist",
            "showComparison",
            "focusMap",
            "selectProperty",
            "showProperties",
            "openOfficialSite",
            "openGoogleEarth",
        ):
            self.assertIn(required, names)

        self.assertIn("applyFilters", SYSTEM_PROMPT)
        self.assertIn("updateShortlist", SYSTEM_PROMPT)
        self.assertIn("showComparison", SYSTEM_PROMPT)

    def test_checkpointer_type(self):
        import asyncio
        from agent_service import get_checkpointer, _cleanup_checkpointer

        async def _run():
            cp = await get_checkpointer()
            name = type(cp).__name__
            await _cleanup_checkpointer()
            return name

        name = asyncio.run(_run())
        # Prefer AsyncSqliteSaver; MemorySaver is acceptable fallback
        self.assertIn(name, ("AsyncSqliteSaver", "MemorySaver", "SqliteSaver"))


if __name__ == "__main__":
    unittest.main()
