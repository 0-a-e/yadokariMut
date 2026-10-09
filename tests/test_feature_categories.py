"""機能カテゴリ辞書の構造不変条件テスト(設計 §5-2)+ルックアップ動作。

辞書正本: src/domain/feature_categories.py(設計 docs/feature-category-unification-design.md)。
"""

import types

from cli import cmd_report_unmapped_features
from domain.feature_categories import (
    CODE_ALIASES,
    FEATURE_CATEGORIES,
    NON_FILTER_FEATURES,
    PARENT_CODES,
    cross_codes,
    feature_unit_codes,
    is_non_filter,
    lookup_feature_category,
    normalize_feature_name,
)


class TestStructureInvariants:
    """設計 §5-2 の構造不変条件(a)〜(d)+決定 14・18 の一意性。"""

    def test_no_code_duplicates(self):
        """(a) code 重複なし — feature単位・親・横断・alias key の全空間。"""
        all_codes = (
            list(feature_unit_codes()) + list(PARENT_CODES) + list(cross_codes()) + list(CODE_ALIASES)
        )
        assert len(all_codes) == len(set(all_codes))

    def test_composite_prefix_matches_parent(self):
        """(b) 複合 code の接頭辞は実在する親 code と一致し、親テーブルに登録済み。"""
        for code in feature_unit_codes():
            if "." in code:
                parent = code.split(".", 1)[0]
                assert parent in PARENT_CODES, f"親が未定義: {code}"
                assert code in PARENT_CODES[parent], f"親テーブルに未登録: {code}"

    def test_parent_and_cross_have_no_include(self):
        """(c) 親・横断 code は FeatureCategory(include)を持たない。"""
        unit = set(feature_unit_codes())
        assert not (set(PARENT_CODES) & unit)
        assert not (set(cross_codes()) & unit)

    def test_cross_codes_equal_modifiers(self):
        """(d) 横断 code 集合 = 複合 code の修飾語集合。"""
        modifiers = {c.split(".", 1)[1] for c in feature_unit_codes() if "." in c}
        assert set(cross_codes()) == modifiers

    def test_label_in_include(self):
        """決定 14: label ∈ include(全 feature 単位 code)。"""
        for cat in FEATURE_CATEGORIES:
            assert cat.label in cat.include, f"{cat.code}: label が include に無い"

    def test_raw_name_to_code_unique(self):
        """決定 18: 生名→code 一意(正規化空間で検証)。"""
        seen: dict[str, str] = {}
        for cat in FEATURE_CATEGORIES:
            for name in cat.include:
                key = normalize_feature_name(name)
                assert key not in seen, f"{name!r} が {seen[key]} と {cat.code} に重複割当"
                seen[key] = cat.code

    def test_non_filter_disjoint_from_include(self):
        """ignore セットと include は排反(正規化突合)。"""
        for name in NON_FILTER_FEATURES:
            assert lookup_feature_category(name) is None, f"NON_FILTER が辞書と重複: {name!r}"

    def test_parent_table_children_are_composite(self):
        """親テーブルの子はすべて「親.修飾語」形式。"""
        for parent, children in PARENT_CODES.items():
            for child in children:
                prefix, _, modifier = child.partition(".")
                assert prefix == parent and modifier, f"子の形式が不正: {child}"

    def test_initial_catalog_scale(self):
        """初期仕分け(2026-10-08)の規模下限 — 語彙追加で増える分には壊れない。"""
        assert len(feature_unit_codes()) >= 80
        assert len(PARENT_CODES) >= 5
        assert len(NON_FILTER_FEATURES) >= 4
        # 初期語彙 160 = include 156 + NON_FILTER 4(母集団の全数)
        assert sum(len(c.include) for c in FEATURE_CATEGORIES) >= 156


class TestLookup:
    """ルックアップ・正規化の動作(§7-7: 両辺正規化・生値保持)。"""

    def test_orthographic_variants_share_code(self):
        # §1.2 の解決事例: 表記ゆれを同一カテゴリに吸収
        assert lookup_feature_category("宅配ボックス").code == "delivery_box"
        assert lookup_feature_category("宅配ＢＯＸ").code == "delivery_box"  # 全角英数
        assert lookup_feature_category("モニター付きインターフォン").code == "video_intercom"
        assert lookup_feature_category("モニター付きインターホン").code == "video_intercom"  # bratto 旧仮名
        assert lookup_feature_category("洗濯機").code == "washing_machine"
        assert lookup_feature_category("室内洗濯機").code == "washing_machine"

    def test_nfkc_fullwidth_digits(self):
        assert lookup_feature_category("２口ガスコンロ").code == "gas_stove"
        assert lookup_feature_category("ガスコンロ（2口）").code == "gas_stove"

    def test_composite_codes(self):
        assert lookup_feature_category("駐輪可（無料）").code == "bicycle_parking.fee_free"
        assert lookup_feature_category("駐輪場 無料").code == "bicycle_parking.fee_free"
        assert lookup_feature_category("Wi-Fiレンタル").code == "wifi_rental.fee_paid"
        assert lookup_feature_category("モバイルWi-Fiルーター（有料）").code == "wifi_rental.fee_paid"

    def test_strip_and_casefold(self):
        assert lookup_feature_category("  エアコン ").code == "aircon"
        assert normalize_feature_name("　ABC abc　") == "abc abc"

    def test_unknown_returns_none(self):
        assert lookup_feature_category("存在しない設備xyz") is None

    def test_normalize_idempotent(self):
        for cat in FEATURE_CATEGORIES:
            for name in cat.include:
                once = normalize_feature_name(name)
                assert normalize_feature_name(once) == once

    def test_non_filter_membership(self):
        assert is_non_filter("360度パノラマ画像")
        assert is_non_filter(" くつろぎstyle ")
        long_mistake = next(n for n in NON_FILTER_FEATURES if n.startswith("ハンガーラック　"))
        assert is_non_filter(long_mistake)  # bratto サイト入力ミスの実例(パーサ故障ではない)
        assert not is_non_filter("エアコン")


class TestReportUnmappedCli:
    """report-unmapped-features CLI の母集団分類動作。"""

    @staticmethod
    def _db_with_names(names):
        from contextlib import contextmanager

        @contextmanager
        def _scope():
            from helpers import ScopedDb
            from store.pg import open_connection

            scope = ScopedDb("unmapped-features")
            try:
                with open_connection() as conn:
                    conn.execute(
                        "INSERT INTO properties (id, source_site, external_id, detail_url) "
                        "VALUES (1, 'unionmonthly', 'x1', 'https://example.com/1/')"
                    )
                    for name in names:
                        conn.execute(
                            "INSERT INTO property_features (property_id, feature_name) VALUES (1, %s)",
                            (name,),
                        )
                    conn.commit()
                yield
            finally:
                scope.close()

        return _scope()

    def test_reports_unmapped_vocabulary(self, capsys):
        with self._db_with_names(
            ["エアコン", "360度パノラマ画像", "新語サンプル"],  # mapped / non_filter / unmapped
        ):
            cmd_report_unmapped_features(types.SimpleNamespace(strict=False))
        out = capsys.readouterr().out
        assert "vocabularies: 3" in out
        assert "mapped: 1" in out
        assert "non_filter: 1" in out
        assert "unmapped: 1" in out
        assert "新語サンプル" in out

    def test_strict_exits_nonzero_on_unmapped(self, capsys):
        with self._db_with_names(["エアコン", "新語サンプル"]):
            try:
                cmd_report_unmapped_features(types.SimpleNamespace(strict=True))
            except SystemExit as e:
                assert e.code == 1
            else:
                raise AssertionError("strict モードで SystemExit しなかった")
        assert "unmapped: 1" in capsys.readouterr().out

    def test_strict_exits_zero_when_clean(self, capsys):
        with self._db_with_names(["エアコン", "バストイレ別", "Luxury style"]):
            cmd_report_unmapped_features(types.SimpleNamespace(strict=True))
        out = capsys.readouterr().out
        assert "unmapped: 0" in out
