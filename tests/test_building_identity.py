"""建物名寄せ(割当・代表値集約・バッチ・merge/split)のテスト.

docs/building-aggregation-design.md §4/§5/§7 の契約を固定する。
"""

import unittest

from helpers import ScopedDb, make_tokyo_draft

from domain.building_identity import extract_building_name, normalize_address_key
from domain.models import PropertyFeature
from store.building_identity import (
    assign_building,
    merge_buildings,
    recompute_building,
    run_identity_batch,
    split_building,
)
from store.repository import Repository, open_connection


class TestNormalizeAddressKey(unittest.TestCase):
    def test_spaces_stripped_and_nfkc(self):
        # unionmonthly の「東京都 渋谷区 宇田川町6-15」(スペース挿入)と
        # bratto の同住所が同一キーへ畳まる(クロスソース名寄せの前提)
        self.assertEqual(
            normalize_address_key("東京都 渋谷区 宇田川町6-15"),
            normalize_address_key("東京都渋谷区宇田川町6-15"),
        )
        self.assertEqual(
            normalize_address_key("東京都中央区入船２-６-１"),  # 全角数字
            "東京都中央区入船2-6-1",
        )

    def test_none_and_empty(self):
        self.assertIsNone(normalize_address_key(None))
        self.assertIsNone(normalize_address_key(""))
        self.assertIsNone(normalize_address_key("   "))

    def test_chome_notation_unified(self):
        # bratto「8丁目-3-37」と unionmonthly「8-3-37」が同一キーへ畳まる
        # (2026-10-09 本番監査: ユニオンマンスリー西新宿駅前₁×BraTTo新宿新都心 等)
        self.assertEqual(
            normalize_address_key("東京都新宿区西新宿8丁目-3-37"),
            normalize_address_key("東京都 新宿区 西新宿8-3-37"),
        )
        # ハイフン無し形式「2丁目11-8」も畳まる
        self.assertEqual(
            normalize_address_key("千葉県浦安市北栄2丁目11-8"),
            normalize_address_key("千葉県 浦安市 北栄2-11-8"),
        )
        # 丁目の直後に区切りが無い「8丁目3-37」も同一形式へ
        self.assertEqual(
            normalize_address_key("神奈川県川崎市幸区南幸町3丁目1-1"),
            normalize_address_key("神奈川県 川崎市幸区 南幸町3-1-1"),
        )
        # 住所が丁目で終わる場合は末尾区切りを落とす
        self.assertEqual(normalize_address_key("東京都新宿区西新宿8丁目"), "東京都新宿区西新宿8")


class TestExtractBuildingName(unittest.TestCase):
    def test_unionmonthly_first_token(self):
        self.assertEqual(
            extract_building_name("unionmonthly", "ユニオンマンスリー渋谷カディナ１ 903 1LDK・セミダブル【清掃費無料】"),
            "ユニオンマンスリー渋谷カディナ１",
        )

    def test_bratto_suffix_stripped(self):
        self.assertEqual(
            extract_building_name("bratto", "BraTTo三ノ輪(1Rタイプ)(Bタイプ)【プラチナタイプ】"),
            "BraTTo三ノ輪",
        )
        self.assertEqual(
            extract_building_name("bratto", "BraTTo名古屋駅前プライムタワー"),
            "BraTTo名古屋駅前プライムタワー",
        )

    def test_none(self):
        self.assertIsNone(extract_building_name("bratto", None))
        self.assertIsNone(extract_building_name("unionmonthly", ""))


class TestAssignAndRecompute(unittest.TestCase):
    def setUp(self):
        self.db = ScopedDb("test.building.assign")
        self.repo = Repository()

    def tearDown(self):
        self.db.close()

    def _pid(self, external_id: str) -> int:
        with open_connection() as conn:
            row = conn.execute(
                "SELECT id FROM properties WHERE external_id = %s", (external_id,)
            ).fetchone()
            return int(row["id"])

    def test_same_address_rooms_share_building(self):
        self.repo.upsert_property(
            make_tokyo_draft("101", title="ユニオンマンスリーA 101", rent_current_yen=6000,
                             lat=35.0, lng=139.0)
        )
        self.repo.upsert_property(
            make_tokyo_draft("102", title="ユニオンマンスリーA 102", rent_current_yen=5000,
                             lat=35.0, lng=139.0)
        )
        with open_connection() as conn:
            ids = [
                int(r["building_id"])
                for r in conn.execute("SELECT building_id FROM properties ORDER BY id")
            ]
            self.assertEqual(ids[0], ids[1])
            self.assertIsNotNone(ids[0])
            building = dict(
                conn.execute("SELECT * FROM buildings WHERE id = %s", (ids[0],)).fetchone()
            )
            # §7: units_count / active_units_count / 代表値(最安 5000)/ 名称
            self.assertEqual(building["units_count"], 2)
            self.assertEqual(building["active_units_count"], 2)
            self.assertEqual(building["min_daily_rent_yen"], 5000)
            self.assertEqual(building["canonical_name"], "ユニオンマンスリーA")
            self.assertEqual(building["is_active"], 1)
            name_rows = conn.execute(
                "SELECT name FROM building_names WHERE building_id = %s", (ids[0],)
            ).fetchall()
            self.assertEqual([r["name"] for r in name_rows], ["ユニオンマンスリーA"])

    def test_address_null_leaves_unassigned(self):
        self.repo.upsert_property(make_tokyo_draft("201", address=None))
        with open_connection() as conn:
            row = conn.execute(
                "SELECT building_id FROM properties WHERE external_id = '201'"
            ).fetchone()
            self.assertIsNone(row["building_id"])

    def test_cross_source_same_address_merges(self):
        # スペース入り住所(unionmonthly 流)と無スペース(bratto 流)が同一建物へ
        self.repo.upsert_property(
            make_tokyo_draft("301", source_site="unionmonthly",
                             address="東京都 渋谷区 神宮前1-2-3",
                             title="ユニオンマンスリー神宮前 301")
        )
        # bratto 側は同住所に 2 部屋(代表名は部屋数の多いソース = bratto)
        self.repo.upsert_property(
            make_tokyo_draft("901", source_site="bratto", address="東京都渋谷区神宮前1-2-3",
                             title="BraTTo神宮前（Aタイプ）", rent_current_yen=7000)
        )
        self.repo.upsert_property(
            make_tokyo_draft("902", source_site="bratto", address="東京都渋谷区神宮前1-2-3",
                             title="BraTTo神宮前（Bタイプ）", rent_current_yen=6500)
        )
        with open_connection() as conn:
            ids = {
                int(r["building_id"])
                for r in conn.execute("SELECT building_id FROM properties")
            }
            self.assertEqual(len(ids), 1)
            building = dict(
                conn.execute("SELECT * FROM buildings WHERE id = %s", (list(ids)[0],)).fetchone()
            )
            # canonical_name は部屋数最多ソース(bratto 2 部屋)の代表名(接尾辞除去)
            self.assertEqual(building["canonical_name"], "BraTTo神宮前")
            names = {
                r["source_site"]: r["name"]
                for r in conn.execute(
                    "SELECT source_site, name FROM building_names WHERE building_id = %s",
                    (list(ids)[0],),
                )
            }
            self.assertEqual(names["bratto"], "BraTTo神宮前")
            self.assertEqual(names["unionmonthly"], "ユニオンマンスリー神宮前")

    def test_address_change_moves_building(self):
        self.repo.upsert_property(make_tokyo_draft("401", address="東京都渋谷区神宮前1-2-3"))
        self.repo.upsert_property(make_tokyo_draft("402", address="東京都渋谷区神宮前1-2-3"))
        # 401 の住所が変わる(再スクレイプで移転した場合)
        self.repo.upsert_property(
            make_tokyo_draft("401", address="東京都渋谷区神宮前9-9-9")
        )
        with open_connection() as conn:
            rows = {
                r["external_id"]: int(r["building_id"])
                for r in conn.execute(
                    "SELECT external_id, building_id FROM properties"
                )
            }
            self.assertNotEqual(rows["401"], rows["402"])
            old = dict(
                conn.execute(
                    "SELECT units_count FROM buildings WHERE id = %s", (rows["402"],)
                ).fetchone()
            )
            self.assertEqual(old["units_count"], 1)

    def test_majority_representatives(self):
        # 座標 2:1 の多数決・築年多数決
        self.repo.upsert_property(
            make_tokyo_draft("501", lat=35.1, lng=139.1, built_year=2015)
        )
        self.repo.upsert_property(
            make_tokyo_draft("502", lat=35.1, lng=139.1, built_year=2015)
        )
        self.repo.upsert_property(
            make_tokyo_draft("503", lat=35.9, lng=139.9, built_year=2018)
        )
        with open_connection() as conn:
            building = dict(
                conn.execute("SELECT * FROM buildings").fetchone()
            )
            self.assertEqual((building["lat"], building["lng"]), (35.1, 139.1))
            self.assertEqual(building["built_year"], 2015)

    def test_inactive_building_falls_back_to_inactive_rents(self):
        self.repo.upsert_property(
            make_tokyo_draft("601", rent_current_yen=5000, is_active=False)
        )
        self.repo.upsert_property(
            make_tokyo_draft("602", rent_current_yen=4000, is_active=True)
        )
        with open_connection() as conn:
            building = dict(conn.execute("SELECT * FROM buildings").fetchone())
            self.assertEqual(building["is_active"], 1)
            self.assertEqual(building["min_daily_rent_yen"], 4000)


class TestIdentityBatchAndOverrides(unittest.TestCase):
    def setUp(self):
        self.db = ScopedDb("test.building.batch")
        self.repo = Repository()

    def tearDown(self):
        self.db.close()

    def test_dry_run_writes_nothing(self):
        # フックを経由しない行(既存 DB で B1 未適用の状態を模倣)を直 INSERT
        with open_connection() as conn:
            conn.execute(
                """
                INSERT INTO properties (source_site, external_id, entity_type, title,
                    prefecture_name, prefecture_slug, municipality, address,
                    is_active, first_seen_at, last_seen_at)
                VALUES ('unionmonthly', '701', 'room', 'ユニオンマンスリーB 701',
                    '東京都', 'tokyo', '渋谷区', '東京都渋谷区神宮前1-2-3',
                    TRUE, '2026-10-08T00:00:00', '2026-10-08T00:00:00')
                """
            )
            conn.commit()
        with open_connection() as conn:
            report = run_identity_batch(conn, apply=False)
        self.assertEqual(report["building_groups"], 1)
        self.assertEqual(report["buildings_to_create"], 1)
        # 直 INSERT 行(building_id=NULL)も割当対象として move に記録される
        self.assertEqual(len(report["moves"]), 1)
        self.assertIsNone(report["moves"][0]["to"])
        # dry-run は書き込みゼロ
        with open_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
            self.assertEqual(count, 0)

    def test_apply_assigns_and_reports(self):
        with open_connection() as conn:
            conn.execute(
                """
                INSERT INTO properties (source_site, external_id, entity_type, title,
                    prefecture_name, prefecture_slug, municipality, address,
                    is_active, first_seen_at, last_seen_at)
                VALUES ('unionmonthly', '801', 'room', 'ユニオンマンスリーC 801',
                    '東京都', 'tokyo', '渋谷区', '東京都渋谷区神宮前1-2-3',
                    TRUE, '2026-10-08T00:00:00', '2026-10-08T00:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO properties (source_site, external_id, entity_type, title,
                    prefecture_name, prefecture_slug, municipality, address,
                    is_active, first_seen_at, last_seen_at)
                VALUES ('unionmonthly', '802', 'room', 'ユニオンマンスリーC 802',
                    '東京都', 'tokyo', '渋谷区', '東京都渋谷区神宮前1-2-3',
                    TRUE, '2026-10-08T00:00:00', '2026-10-08T00:00:00')
                """
            )
            conn.commit()
        with open_connection() as conn:
            report = run_identity_batch(conn, apply=True)
        self.assertEqual(report["buildings_after"], 1)
        self.assertEqual(report["assigned_properties"], 2)
        with open_connection() as conn:
            building = dict(conn.execute("SELECT * FROM buildings").fetchone())
            self.assertEqual(building["units_count"], 2)
            self.assertEqual(building["canonical_name"], "ユニオンマンスリーC")

    def test_apply_removes_empty_buildings(self):
        # 住所変更で部屋が移った旧キー建物(所属 0)はバッチ適用時に掃除される
        self.repo.upsert_property(
            make_tokyo_draft("850", address="東京都渋谷区神宮前1-2-3")
        )
        self.repo.upsert_property(
            make_tokyo_draft("850", address="東京都渋谷区神宮前9-9-9")
        )
        with open_connection() as conn:
            before = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
            self.assertEqual(before, 2)  # 旧(空)と新が共存
            report = run_identity_batch(conn, apply=True)
            after = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
        self.assertEqual(after, 1)
        self.assertEqual(report["buildings_removed_empty"], 1)
        self.assertEqual(report["buildings_after"], 1)

    def test_name_conflict_detected(self):
        # 同一住所に 2 名称(棟疑い)→ dry-run レポートの name_conflicts に出る
        self.repo.upsert_property(
            make_tokyo_draft("901", source_site="unionmonthly",
                             title="ユニオンマンスリーD１ 901")
        )
        self.repo.upsert_property(
            make_tokyo_draft("902", source_site="unionmonthly",
                             title="ユニオンマンスリーD２ 902")
        )
        with open_connection() as conn:
            report = run_identity_batch(conn, apply=False)
        self.assertEqual(len(report["name_conflicts"]), 1)
        conflict = report["name_conflicts"][0]
        self.assertIn("ユニオンマンスリーD１", conflict["names"]["unionmonthly"])
        self.assertIn("ユニオンマンスリーD２", conflict["names"]["unionmonthly"])

    def test_merge_and_split(self):
        self.repo.upsert_property(
            make_tokyo_draft("1001", address="東京都渋谷区神宮前1-2-3")
        )
        self.repo.upsert_property(
            make_tokyo_draft("1002", address="東京都渋谷区神宮前1-2-4")
        )
        with open_connection() as conn:
            ids = sorted(
                int(r["id"]) for r in conn.execute("SELECT id FROM buildings")
            )
            # merge: 2 → 1
            moved = merge_buildings(conn, ids[0], ids[1])
            self.assertEqual(moved, 2)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0], 1
            )
            # split: 片方を別建物へ(手動オーバーライド)
            pid = conn.execute(
                "SELECT id FROM properties ORDER BY id LIMIT 1"
            ).fetchone()[0]
            new_id = split_building(conn, ids[0], [int(pid)])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0], 2
            )
            base_key = conn.execute(
                "SELECT address_key FROM buildings WHERE id = %s", (ids[0],)
            ).fetchone()["address_key"]
            new_key = conn.execute(
                "SELECT address_key FROM buildings WHERE id = %s", (new_id,)
            ).fetchone()["address_key"]
            self.assertTrue(new_key.startswith(base_key + "#split"))


if __name__ == "__main__":
    unittest.main()
