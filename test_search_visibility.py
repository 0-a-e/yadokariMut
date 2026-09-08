#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""掲載状態可視化: shortlist判定済み物件はinactiveでも検索に出ること."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

os.environ["YADOKARIMUT_DATA_LAYER"] = "v2"
_TMPDIR = tempfile.mkdtemp(prefix="yadm-vis-")
os.environ["YADOKARIMUT_V2_DB_PATH"] = os.path.join(_TMPDIR, "test_v2.db")


from domain.models import PropertyDraft  # noqa: E402
from store import api_queries  # noqa: E402
from store.repository import Repository  # noqa: E402


def _draft(external_id: str, *, active: bool = True, pref: str = "東京都") -> PropertyDraft:
    return PropertyDraft(
        source_site="fakesite",
        external_id=external_id,
        entity_type="room",
        title=f"物件 {external_id}",
        detail_url=f"https://example.test/{external_id}/",
        prefecture_name=pref,
        prefecture_slug="tokyo",
        is_active=active,
        price_plans=[],
    )


class SearchVisibilityTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        self.repo.init_db()
        conn = self.repo.connect()
        try:
            conn.execute("DELETE FROM shortlists")
            conn.execute("DELETE FROM properties")
            conn.commit()
        finally:
            conn.close()
        # active1(保存), active2(無判定), inactive1(保存), inactive2(見送り), inactive3(無判定)
        for eid, active in [("active1", True), ("active2", True),
                            ("inactive1", False), ("inactive2", False),
                            ("inactive3", False)]:
            self.repo.upsert_property(_draft(eid, active=active))
        conn = self.repo.connect()
        try:
            for eid, st in [("active1", "saved"), ("inactive1", "saved"),
                            ("inactive2", "reject")]:
                pid = conn.execute(
                    "SELECT id FROM properties WHERE external_id = ?", (eid,)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO shortlists (property_id, status, updated_at) VALUES (?, ?, ?)",
                    (pid, st, "2026-09-07T00:00:00"),
                )
            conn.commit()
        finally:
            conn.close()

    def _ids(self, params=None):
        rows = api_queries.search_properties(params or {})
        return [r["external_id"] for r in rows]

    def test_default_search_keeps_inactive_shortlisted(self):
        """既定検索(exclude_hidden=True)に inactive+保存 は含まれ、無判定inactiveは含まれない."""
        ids = self._ids()
        self.assertIn("inactive1", ids)
        self.assertNotIn("inactive3", ids)
        self.assertIn("active1", ids)
        self.assertIn("active2", ids)
        # hide/reject は既定で除外
        self.assertNotIn("inactive2", ids)

    def test_saved_only_includes_inactive(self):
        ids = self._ids({"saved_only": True})
        self.assertIn("inactive1", ids)
        self.assertIn("active1", ids)
        self.assertNotIn("inactive3", ids)

    def test_exclude_hidden_false_shows_rejected_inactive(self):
        ids = self._ids({"exclude_hidden": False})
        self.assertIn("inactive2", ids)

    def test_inactive_sorted_last(self):
        rows = api_queries.search_properties({"exclude_hidden": False})
        ext_ids = [r["external_id"] for r in rows]
        actives = [i for i in ext_ids if i.startswith("active")]
        inactives = [i for i in ext_ids if i.startswith("inactive")]
        self.assertEqual(ext_ids, actives + inactives)

    def test_rows_carry_is_active_flag(self):
        rows = api_queries.search_properties({"exclude_hidden": False})
        flag = {r["external_id"]: r["is_active"] for r in rows}
        self.assertTrue(flag["active1"])
        self.assertFalse(flag["inactive1"])


if __name__ == "__main__":
    unittest.main()
