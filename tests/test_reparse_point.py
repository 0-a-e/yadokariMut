"""reparse-point CLI のテスト(unionmonthly スタッフコメント point_text の遡及適用・2026-10-09)。"""

import shutil
import types
import unittest
from pathlib import Path

from cli import cmd_reparse_point

UNION_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures" / "union-monthly" / "unionmonthly_detail_fixture.html"
)


def make_db(storage_path: str, detail_url: str) -> "ScopedDb":
    """隔離 PG DB(baseline スキーマ)に再パース母集団を投入。"""
    from helpers import ScopedDb
    from store.pg import open_connection

    scope = ScopedDb("reparse")
    with open_connection() as conn:
        conn.execute(
            "INSERT INTO properties (id, source_site, external_id, detail_url) "
            "VALUES (1, 'unionmonthly', 'p1', %s)",
            (detail_url,),
        )
        conn.execute(
            "INSERT INTO raw_pages (source_site, url, page_type, fetched_at, storage_path) "
            "VALUES ('unionmonthly', %s, 'detail', '2026-10-08T00:00:00', %s)",
            (detail_url, storage_path),
        )
        conn.commit()
    return scope


def point_row() -> tuple:
    from store.pg import open_connection

    with open_connection() as conn:
        return conn.execute(
            "SELECT point_text FROM properties WHERE id = 1"
        ).fetchone()


@unittest.skipUnless(UNION_FIXTURE.exists(), "union detail fixture missing")
class TestReparsePointCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.storage_root = self.tmp / "raw_pages_v2"
        self.storage_root.mkdir()
        self.db = self.tmp / "t.db"

    def _run(self, detail_url: str, dry_run: bool):
        cmd_reparse_point(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=str(self.storage_root),
                limit=None,
                dry_run=dry_run,
            )
        )

    def test_apply_fills_point_text(self):
        shutil.copy(UNION_FIXTURE, self.storage_root / UNION_FIXTURE.name)
        self._scope = make_db(
            f"/app/data/raw_pages_v2/{UNION_FIXTURE.name}",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        self._run("https://www.unionmonthly.jp/tokyo/6575/", dry_run=False)
        pt = point_row()["point_text"]
        self.assertIsNotNone(pt)
        # 先頭ボイラープレート(県市テンプレ行・建物名行)は除去され、
        # ブロック見出し以降がそのまま入る
        self.assertTrue(pt.startswith("■路線情報(最寄駅→主要駅)"))
        self.assertIn("■周辺情報", pt)
        self.assertIn("■おすすめコメント", pt)

    def test_dry_run_keeps_db(self):
        shutil.copy(UNION_FIXTURE, self.storage_root / UNION_FIXTURE.name)
        self._scope = make_db(
            f"/app/data/raw_pages_v2/{UNION_FIXTURE.name}",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        self._run("https://www.unionmonthly.jp/tokyo/6575/", dry_run=True)
        self.assertIsNone(point_row()["point_text"])

    def test_missing_html_is_reported_not_fatal(self):
        self._scope = make_db(
            "/app/data/raw_pages_v2/absent.html",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        empty = self.tmp / "empty"
        empty.mkdir()
        cmd_reparse_point(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=str(empty),
                limit=None,
                dry_run=False,
            )
        )
        self.assertIsNone(point_row()["point_text"])  # 何も書き換わっていない


if __name__ == "__main__":
    unittest.main()
