"""Alembic PG ベースラインと辞書同期のテスト(PG移行後の正本)。

旧 SQLite db-migrate チェイン(v3→v4→v5)は PG 移行で廃止
(docs/sqlite-pg-migration-plan.md D2・後継は src/alembic/versions/0001_pg_baseline.py)。
本ファイルは後継の検証として:

- alembic upgrade head が v5 相当の全テーブル/制約を作ること
- CHECK / UNIQUE / IDENTITY(自動採番)/ FK(ON DELETE SET NULL) の実効性
- sync_feature_dictionary の辞書修復とハッシュ記録

をカバーする(旧テストの実効要件対応は commit 履歴参照)。
"""

import unittest
import uuid

import psycopg

from helpers import ScopedDb
from store.schema import feature_dict_hash, sync_feature_dictionary

_ALL_TABLES = {
    "schema_meta", "properties", "property_accesses", "property_images",
    "property_links", "property_features", "price_plans", "campaigns",
    "property_snapshots", "raw_pages", "property_shortlists", "scrape_runs",
    "scrape_run_targets", "rotation_state", "app_settings", "buildings",
    "building_names", "building_shortlists",
}


class TestPGBaseline(unittest.TestCase):
    def setUp(self):
        self.scope = ScopedDb("schema_pg")
        self.addCleanup(self.scope.close)

    def _conn(self) -> psycopg.Connection:
        import psycopg as _p

        return _p.connect(self.scope.dsn)

    def test_baseline_creates_all_tables_and_revision(self):
        with self._conn() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                )
            }
            self.assertTrue(_ALL_TABLES <= tables, _ALL_TABLES - tables)
            # 旧テーブル名(shortlists)は存在しない(v5 相当)
            self.assertNotIn("shortlists", tables)
            # revision は最新 head まで到達していること(Phase 6a 以降も追従)
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            from store.migrations import ALEMBIC_INI

            head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
            rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            self.assertEqual(rev[0], head)

    def test_presentation_unit_check_rejects_unknown_unit(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO properties (source_site, external_id)"
                    " VALUES ('t', 'chk-1')"
                )
                pid = cur.execute("SELECT id FROM properties WHERE external_id='chk-1'").fetchone()[0]
                with self.assertRaises(psycopg.errors.CheckViolation):
                    cur.execute(
                        "INSERT INTO price_plans (property_id, plan_key, presentation_unit)"
                        " VALUES (%s, 'x', 'per_week')",
                        (pid,),
                    )
            conn.rollback()

    def test_features_unique_rejects_duplicate(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO properties (source_site, external_id)"
                    " VALUES ('t', 'uq-1')"
                )
                pid = cur.execute("SELECT id FROM properties WHERE external_id='uq-1'").fetchone()[0]
                cur.execute(
                    "INSERT INTO property_features (property_id, feature_name)"
                    " VALUES (%s, 'オートロック')",
                    (pid,),
                )
                with self.assertRaises(psycopg.errors.UniqueViolation):
                    cur.execute(
                        "INSERT INTO property_features (property_id, feature_name)"
                        " VALUES (%s, 'オートロック')",
                        (pid,),
                    )
            conn.rollback()

    def test_identity_columns_generate_ids(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                ids = []
                for _ in range(2):
                    cur.execute(
                        "INSERT INTO properties (source_site, external_id)"
                        " VALUES ('t', %s) RETURNING id",
                        (uuid.uuid4().hex[:8],),
                    )
                    ids.append(cur.fetchone()[0])
                self.assertIsInstance(ids[0], int)
                self.assertNotEqual(ids[0], ids[1])
            conn.rollback()

    def test_building_fk_nulls_properties_on_delete(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO buildings (address_key) VALUES ('fk-key-1') RETURNING id"
                )
                bid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO properties (source_site, external_id, building_id)"
                    " VALUES ('t', 'fk-1', %s)",
                    (bid,),
                )
                cur.execute("DELETE FROM buildings WHERE id = %s", (bid,))
                row = cur.execute(
                    "SELECT building_id FROM properties WHERE external_id='fk-1'"
                ).fetchone()
                self.assertIsNone(row[0])
            conn.rollback()


class TestDictionarySync(unittest.TestCase):
    def setUp(self):
        self.scope = ScopedDb("dict_sync")
        self.addCleanup(self.scope.close)
        self.conn = psycopg.connect(self.scope.dsn)
        self.addCleanup(self.conn.close)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO properties (source_site, external_id) VALUES ('t', 'dict-1')"
            )
            self.pid = cur.execute(
                "SELECT id FROM properties WHERE external_id='dict-1'"
            ).fetchone()[0]
            cur.executemany(
                "INSERT INTO property_features (property_id, feature_name) VALUES (%s, %s)",
                [
                    (self.pid, "オートロック"),
                    (self.pid, "室内洗濯機"),
                    (self.pid, "未知の設備"),
                ],
            )
        self.conn.commit()

    def test_sync_applies_dictionary_and_records_hash(self):
        sync_feature_dictionary(self.conn)
        rows = dict(
            self.conn.execute(
                "SELECT feature_name, category FROM property_features WHERE property_id=%s",
                (self.pid,),
            )
        )
        self.assertEqual(rows["オートロック"], "auto_lock")
        self.assertEqual(rows["室内洗濯機"], "washing_machine")
        self.assertIsNone(rows["未知の設備"])
        h = self.conn.execute(
            "SELECT value FROM schema_meta WHERE key='feature_dict_hash'"
        ).fetchone()
        self.assertEqual(h[0], feature_dict_hash())

    def test_sync_repairs_broken_categories(self):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE property_features SET category = NULL")
            cur.execute(
                "UPDATE property_features SET category = 'stale_code'"
                " WHERE feature_name='室内洗濯機'"
            )
        self.conn.commit()
        sync_feature_dictionary(self.conn)
        rows = dict(
            self.conn.execute(
                "SELECT feature_name, category FROM property_features WHERE property_id=%s",
                (self.pid,),
            )
        )
        self.assertEqual(rows["オートロック"], "auto_lock")
        self.assertEqual(rows["室内洗濯機"], "washing_machine")
        self.assertIsNone(rows["未知の設備"])

    def test_sync_skips_when_hash_unchanged(self):
        sync_feature_dictionary(self.conn)
        # ハッシュ記録済みの状態で category を壊しても再同期は走らない(スキップ則)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE property_features SET category = NULL")
        self.conn.commit()
        sync_feature_dictionary(self.conn)
        cat = self.conn.execute(
            "SELECT category FROM property_features WHERE property_id=%s"
            " AND feature_name='オートロック'",
            (self.pid,),
        ).fetchone()
        self.assertIsNone(cat[0])


if __name__ == "__main__":
    unittest.main()
