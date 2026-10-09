#!/usr/bin/env python3
"""ソース表示名 SSOT (SOURCE_DISPLAY) とソース id 集合定数の契約テスト。

M2/M3 の SSOT 化で「表示名は SOURCE_DISPLAY」「id 列挙は SOURCE_IDS /
DEFAULT_ROTATION_SOURCES」に一本化したことを守るための包含・同値契約。
"""

from store.pref_master import PREF_DISPLAY_NAMES
from store.source_catalog import (
    SOURCE_CATALOG,
    SOURCE_DISPLAY,
    SOURCE_IDS,
    list_source_admin_info,
)
from sources.registry import SourceRegistry
from web.rotation_jobs import DEFAULT_ROTATION_SOURCES


class TestSourceDisplaySSOT:
    def test_catalog_ids_are_registered_in_source_display(self):
        """SOURCE_CATALOG の全 id が SOURCE_DISPLAY に登録されていること。

        新規ソースは catalog 追加時に必ず SOURCE_DISPLAY への表示名登録を
        要求する (包含契約)。
        """
        missing = [
            e["id"] for e in SOURCE_CATALOG if e["id"] not in SOURCE_DISPLAY
        ]
        assert missing == []

    def test_admin_info_resolves_display_name_not_id(self):
        """list_source_admin_info の全要素で display_name が id と異なること。

        id と同値は「解決が id フォールバックに落ちた」兆候であり、
        SSOT 解決経路が壊れたことを検出する。
        """
        for info in list_source_admin_info():
            sid = info["id"]
            assert info["display_name"] != sid, (
                f"source '{sid}' fell back to raw id as display_name"
            )

    def test_source_display_has_no_prefecture_junk(self):
        """SOURCE_DISPLAY に都道府県相当の蛇足キーが混入していないこと。"""
        overlap = set(SOURCE_DISPLAY) & set(PREF_DISPLAY_NAMES)
        assert overlap == set()

    def test_source_display_values_are_unique(self):
        """表示名 (値) が重複しないこと。"""
        values = list(SOURCE_DISPLAY.values())
        assert len(values) == len(set(values))


class TestSourceIdConstants:
    def test_registry_matches_source_ids(self):
        """実在アダプタ集合 (Registry) とカタログ id 集合 (SOURCE_IDS) の同値契約。

        将来「カタログ先行でアダプタ未登録ソースを unavailable 表示する」運用を
        許すなら、この契約は ``set(SourceRegistry.get_all()) <= set(SOURCE_IDS)``
        へ緩めてよい。
        """
        assert set(SourceRegistry.get_all()) == set(SOURCE_IDS)

    def test_default_rotation_sources_are_known(self):
        """rotation 既定ソースがカタログ id の部分集合であること。"""
        assert set(DEFAULT_ROTATION_SOURCES) <= set(SOURCE_IDS)

    def test_source_ids_are_in_source_display(self):
        """カタログ id 集合は表示名 SSOT に全て登録されていること。"""
        assert set(SOURCE_IDS) <= set(SOURCE_DISPLAY)
