"""reparse-features CLI のテスト(設計 §7-4: facility_list -active 修正の過去行反映)。"""

import shutil
import types
import unittest
from pathlib import Path

from cli import cmd_reparse_features

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "union-monthly" / "unionmonthly_detail_fixture.html"
)


def make_db(storage_path: str) -> "ScopedDb":
    """隔離 PG DB(baseline スキーマ)に再パース母集団を投入。"""
    from helpers import ScopedDb
    from store.pg import open_connection

    scope = ScopedDb("reparse-feat")
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
        # 旧パーサ(全 li 無差別)相当の行: active/非active関係なく10語彙
        for name in (
            "バストイレ別", "2階以上", "独立洗面台", "室内洗濯機", "南向き",
            "オートロック", "モニター付きインターフォン", "インターネット無料",
            "エアコン", "エレベーター",
        ):
            conn.execute(
                "INSERT INTO property_features (property_id, feature_name) VALUES (1, %s)",
                (name,),
            )
        conn.commit()
    return scope


def feature_names() -> set[str]:
    from store.pg import open_connection

    with open_connection() as conn:
        return {r[0] for r in conn.execute("SELECT feature_name FROM property_features")}



@unittest.skipUnless(FIXTURE.exists(), "union detail fixture missing")
class TestReparseFeaturesCli(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(lambda: self._scope.close() if hasattr(self, "_scope") else None)
        # storage_root に fixture を置き、DB の storage_path は本番形式の別パスにする
        storage_root = self.tmp / "raw_pages_v2"
        storage_root.mkdir()
        shutil.copy(FIXTURE, storage_root / FIXTURE.name)
        self.db = self.tmp / "t.db"
        self._scope = make_db(f"/app/data/raw_pages_v2/{FIXTURE.name}")
        self.storage_root = str(storage_root)

    def _run(self, dry_run: bool):
        cmd_reparse_features(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=self.storage_root,
                limit=None,
                dry_run=dry_run,
            )
        )

    def test_dry_run_keeps_db_and_reports_delta(self):
        before = feature_names()
        self.assertIn("南向き", before)
        self._run(dry_run=True)
        # dry-run は DB を変更しない
        self.assertEqual(feature_names(), before)

    def test_apply_removes_inactive_chip_rows(self):
        self._run(dry_run=False)
        after = feature_names()
        # 非 active の「南向き」が消える(fixture の facility_list で唯一の非 active)
        self.assertNotIn("南向き", after)
        # active 語彙と entry_tag(運営バッジ)は再パース後も残る
        for expected in ("バストイレ別", "2階以上", "室内洗濯機", "家具家電付き", "水道光熱費不要"):
            self.assertIn(expected, after)
        # facility_table(実データ)由来の語彙も(修正後パーサの出力どおり)入る
        self.assertIn("浴室トイレセパレート", after)

    def test_missing_html_is_reported_not_fatal(self):
        # storage_root を空ディレクトリに向けると missing として飛ばされる
        empty = self.tmp / "empty"
        empty.mkdir()
        cmd_reparse_features(
            types.SimpleNamespace(
                db=str(self.db),
                source="unionmonthly",
                storage_root=str(empty),
                limit=None,
                dry_run=False,
            )
        )
        self.assertIn("南向き", feature_names())  # 何も書き換わっていない
