"""reparse-orientation CLI のテスト(docs/orientation-model-plan.md §6.2: 角度モデルの遡及適用)。"""

import shutil
import types
import unittest
from pathlib import Path

from cli import cmd_reparse_orientation

UNION_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures" / "union-monthly" / "unionmonthly_detail_fixture.html"
)


def make_db(storage_path: str) -> "ScopedDb":
    """隔離 PG DB(baseline スキーマ)に再パース母集団を投入。"""
    from helpers import ScopedDb
    from store.pg import open_connection

    scope = ScopedDb("reparse-orient")
    with open_connection() as conn:
        conn.execute(
            "INSERT INTO properties (id, source_site, external_id, detail_url) "
            "VALUES (1, 'unionmonthly', '6575', 'https://www.unionmonthly.jp/tokyo/6575/')"
        )
        conn.execute(
            "INSERT INTO raw_pages (source_site, url, page_type, fetched_at, storage_path) "
            "VALUES ('unionmonthly', 'https://www.unionmonthly.jp/tokyo/6575/', 'detail', "
            "'2026-10-08T00:00:00', %s)",
            (storage_path,),
        )
        conn.commit()
    return scope


def orientation_row() -> tuple:
    from store.pg import open_connection

    with open_connection() as conn:
        return conn.execute(
            "SELECT orientation_text, orientation_deg, orientation_source "
            "FROM properties WHERE id = 1"
        ).fetchone()



@unittest.skipUnless(UNION_FIXTURE.exists(), "union detail fixture missing")
class TestReparseOrientationCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(lambda: self._scope.close() if hasattr(self, "_scope") else None)
        self.storage_root = self.tmp / "raw_pages_v2"
        self.storage_root.mkdir()
        shutil.copy(UNION_FIXTURE, self.storage_root / UNION_FIXTURE.name)
        self.db = self.tmp / "t.db"
        self._scope = make_db(f"/app/data/raw_pages_v2/{UNION_FIXTURE.name}")

    def _run(self, dry_run: bool, source: str = "unionmonthly"):
        cmd_reparse_orientation(
            types.SimpleNamespace(
                db=str(self.db),
                source=source,
                storage_root=str(self.storage_root),
                limit=None,
                dry_run=dry_run,
            )
        )

    def test_apply_fills_orientation(self):
        # fixture の向き=南東 → deg 135・原文保持・source 設定
        self._run(dry_run=False)
        self.assertEqual(orientation_row(), ("南東", 135, "spec_parse"))

    def test_dry_run_keeps_db(self):
        self._run(dry_run=True)
        self.assertEqual(orientation_row(), (None, None, None))

    def test_missing_html_is_reported_not_fatal(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        cmd_reparse_orientation(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=str(empty),
                limit=None,
                dry_run=False,
            )
        )
        self.assertEqual(orientation_row(), (None, None, None))  # 何も書き換わっていない
