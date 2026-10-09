"""reparse-floors CLI のテスト(docs/floor-number-ssot-plan.md §3.5: floor_number 整数化の遡及適用)。"""

import shutil
import types
import unittest
from pathlib import Path

from cli import cmd_reparse_floors

UNION_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures" / "union-monthly" / "unionmonthly_detail_fixture.html"
)

# bratto 詳細の最小模倣(規格表「階建」セルのみ。PoC で検証済みの実マークアップ形式)
BRATTO_HTML = """
<html><body><table>
<tr><th>住所</th><td>東京都渋谷区</td></tr>
<tr><th><h3>構造</h3></th><td>鉄筋コンクリート造（RC造）</td></tr>
<tr><th><h3>階建</h3></th><td>10階建7階</td></tr>
</table></body></html>
"""


def make_db(storage_path: str, source: str, detail_url: str) -> "ScopedDb":
    """隔離 PG DB(baseline スキーマ)に再パース母集団を投入。"""
    from helpers import ScopedDb
    from store.pg import open_connection

    scope = ScopedDb("reparse")
    with open_connection() as conn:
        conn.execute(
            "INSERT INTO properties (id, source_site, external_id, detail_url) "
            "VALUES (1, %s, 'p1', %s)",
            (source, detail_url),
        )
        conn.execute(
            "INSERT INTO raw_pages (source_site, url, page_type, fetched_at, storage_path) "
            "VALUES (%s, %s, 'detail', '2026-10-08T00:00:00', %s)",
            (source, detail_url, storage_path),
        )
        conn.commit()
    return scope


def floor_row() -> tuple:
    from store.pg import open_connection

    with open_connection() as conn:
        return conn.execute(
            "SELECT floors_text, floor_number, floor_number_max, building_floors "
            "FROM properties WHERE id = 1"
        ).fetchone()


@unittest.skipUnless(UNION_FIXTURE.exists(), "union detail fixture missing")
class TestReparseFloorsCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.storage_root = self.tmp / "raw_pages_v2"
        self.storage_root.mkdir()
        self.db = self.tmp / "t.db"

    def _run(self, source: str, detail_url: str, dry_run: bool):
        cmd_reparse_floors(
            types.SimpleNamespace(
                db=str(self.db),
                source=source,
                storage_root=str(self.storage_root),
                limit=None,
                dry_run=dry_run,
            )
        )

    def test_union_apply_fills_floor_number(self):
        shutil.copy(UNION_FIXTURE, self.storage_root / UNION_FIXTURE.name)
        self._scope = make_db(f"/app/data/raw_pages_v2/{UNION_FIXTURE.name}",
            "unionmonthly",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        self._run("unionmonthly", "https://www.unionmonthly.jp/tokyo/6575/", dry_run=False)
        # fixture の所在階=9階 → floor_number=9・floors_text に原文
        self.assertEqual(floor_row(), ("9階", 9, 9, None))

    def test_bratto_apply_splits_concat(self):
        html_path = self.storage_root / "bratto_detail_x.html"
        html_path.write_text(BRATTO_HTML, encoding="utf-8")
        self._scope = make_db(f"/app/data/raw_pages_v2/{html_path.name}",
            "bratto",
            "https://www.000area-weekly.com/tokyo/room/?room_id=x",
        )
        self._run("bratto", "https://www.000area-weekly.com/tokyo/room/?room_id=x", dry_run=False)
        # 連結「10階建7階」→ 建物10・所在階7 に分離
        self.assertEqual(floor_row(), ("10階建7階", 7, 7, 10))

    def test_dry_run_keeps_db(self):
        shutil.copy(UNION_FIXTURE, self.storage_root / UNION_FIXTURE.name)
        self._scope = make_db(f"/app/data/raw_pages_v2/{UNION_FIXTURE.name}",
            "unionmonthly",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        self._run("unionmonthly", "https://www.unionmonthly.jp/tokyo/6575/", dry_run=True)
        self.assertEqual(floor_row(), (None, None, None, None))

    def test_missing_html_is_reported_not_fatal(self):
        self._scope = make_db("/app/data/raw_pages_v2/absent.html",
            "unionmonthly",
            "https://www.unionmonthly.jp/tokyo/6575/",
        )
        empty = self.tmp / "empty"
        empty.mkdir()
        cmd_reparse_floors(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=str(empty),
                limit=None,
                dry_run=False,
            )
        )
        self.assertEqual(floor_row(), (None, None, None, None))  # 何も書き換わっていない
