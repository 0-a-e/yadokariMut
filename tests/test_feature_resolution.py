"""required_features 解決器の単体テスト(設計 §3.2・§4.1)。

複合 code 判定(駐輪場無料・親/横断 code の展開・横断併用)と、
物件和集合判定の偽陽性が構造的に出ないことを固定する。
"""

from domain.feature_categories import lookup_feature_category
from domain.feature_resolution import (
    feature_codes_of,
    property_matches,
    resolve_requirement,
    resolve_requirements,
    satisfiable_codes,
    satisfiable_codes_from_categories,
)


class TestResolveRequirement:
    def test_simple_code_direct(self):
        r = resolve_requirement("auto_lock")
        assert r.codes == frozenset({"auto_lock"}) and not r.is_fallback

    def test_composite_code_direct(self):
        r = resolve_requirement("bicycle_parking.fee_free")
        assert r.codes == frozenset({"bicycle_parking.fee_free"}) and not r.is_fallback

    def test_parent_code_expands_children(self):
        r = resolve_requirement("bicycle_parking")
        assert r.codes == frozenset(
            {"bicycle_parking.fee_free", "bicycle_parking.fee_negotiable", "bicycle_parking.fee_paid"}
        )

    def test_cross_code_expands_all_families(self):
        r = resolve_requirement("fee_free")
        assert "bicycle_parking.fee_free" in r.codes
        assert "parking.fee_free" in r.codes
        assert "internet.fee_free" in r.codes
        # fee_free 以外の修飾語を持つ複合 code は含まれない
        assert "bicycle_parking.fee_paid" not in r.codes
        assert "wifi_rental.fee_paid" not in r.codes

    def test_lenient_acceptance_of_include_raw(self):
        # include 生値 → 所属 code(表記ゆれ・全角も両辺正規化で吸収)
        assert resolve_requirement("室内洗濯機").codes == frozenset({"washing_machine"})
        assert resolve_requirement("ドラム式洗濯機").codes == frozenset({"washing_machine"})
        assert resolve_requirement("宅配ＢＯＸ").codes == frozenset({"delivery_box"})
        assert resolve_requirement("モニター付きインターホン").codes == frozenset({"video_intercom"})

    def test_label_acceptance(self):
        # label ∈ include(決定 14)によりラベルも寛容受入される
        assert resolve_requirement("洗濯機").codes == frozenset({"washing_machine"})

    def test_unknown_value_falls_back_to_raw(self):
        r = resolve_requirement("架空の設備XYZ")
        assert r.is_fallback and r.codes == frozenset() and r.raw == "架空の設備XYZ"

    def test_blank_value_falls_back(self):
        assert resolve_requirement("  ").is_fallback

    def test_resolve_requirements_list(self):
        reqs = resolve_requirements(["auto_lock", "fee_free"])
        assert [x.raw for x in reqs] == ["auto_lock", "fee_free"]
        assert all(not x.is_fallback for x in reqs)


class TestPropertyMatches:
    """feature 単位判定(物件和集合判定の偽陽性構造的不発生 — 決定 18)。"""

    def test_bicycle_parking_free(self):
        # 「駐輪場無料」= bicycle_parking.fee_free のみ(実測 1,737 物件相当)
        assert property_matches(["駐輪可（無料）"], resolve_requirements(["bicycle_parking.fee_free"]))
        assert property_matches(["駐輪場 無料"], resolve_requirements(["bicycle_parking.fee_free"]))
        assert not property_matches(
            ["駐輪場 要相談"], resolve_requirements(["bicycle_parking.fee_free"])
        )

    def test_parent_code_matches_any_fee_axis(self):
        reqs = resolve_requirements(["bicycle_parking"])
        assert property_matches(["駐輪可（無料）"], reqs)
        assert property_matches(["駐輪場 要相談"], reqs)
        assert not property_matches(["オートロック"], reqs)

    def test_cross_code_combined_use_is_feature_unit_accurate(self):
        # 併用 ['fee_free','auto_lock'] = 「何か無料の設備 AND オートロック」(feature 単位)
        reqs = resolve_requirements(["fee_free", "auto_lock"])
        assert property_matches(["駐輪可（無料）", "オートロック"], reqs)
        assert not property_matches(["駐輪可（無料）"], reqs)  # オートロック無し
        # feature 単位判定: fee_free は internet.fee_free で成立するが、
        # オートロックを保有しない物件は AND の結果落ちる
        assert not property_matches(
            ["駐輪場 要相談", "インターネット無料"], reqs
        )

    def test_cross_code_satisfied_by_any_family_member(self):
        assert property_matches(
            ["インターネット無料"], resolve_requirements(["fee_free"])
        )
        assert not property_matches(
            ["駐輪場 有料", "Wi-Fiレンタル"], resolve_requirements(["fee_free"])
        )

    def test_requirements_are_anded(self):
        reqs = resolve_requirements(["washing_machine", "auto_lock"])
        assert property_matches(["室内洗濯機", "オートロック"], reqs)
        assert not property_matches(["室内洗濯機"], reqs)

    def test_lenient_raw_and_code_mixed(self):
        # 生値指定と code 指定の混在も同じ判定に落ちる
        reqs = resolve_requirements(["洗濯機", "auto_lock"])
        assert property_matches(["室内洗濯機", "オートロック"], reqs)

    def test_fallback_exact_match_only(self):
        reqs = resolve_requirements(["架空の設備XYZ"])
        assert property_matches(["架空の設備XYZ", "オートロック"], reqs)
        assert not property_matches(["オートロック"], reqs)

    def test_empty_requirements_match_all(self):
        assert property_matches([], [])
        assert property_matches(["オートロック"], [])


class TestFeatureCodesOf:
    def test_known_and_unknown_names(self):
        codes = feature_codes_of(["オートロック", "駐輪可（無料）", "未知の設備"])
        assert codes == frozenset({"auto_lock", "bicycle_parking.fee_free"})


class TestSatisfiableCodesFromCategories:
    """category 列直読み版と feature_name lookup 版の同一出力契約(決定 4・10)。

    検索 SQL 化後の feature_categories 配信は satisfiable_codes_from_categories
    (category 直読み)に一本化されるため、第 1 段の satisfiable_codes
    (feature_name → 辞書 lookup)と常に同一の出力になることを既知語彙で固定する。
    """

    def test_same_output_as_satisfiable_codes(self):
        # 単純 code / 複合 code(親・横断の導出あり)/ 未知語 / 重複を含む既知語彙
        names = [
            "オートロック",
            "駐輪可（無料）",
            "エアコン",
            "室内洗濯機",
            "駐輪場 無料",       # 駐輪可（無料）と同一 code へ畳まる別表記
            "未知の設備XYZ",     # 辞書外 → 両関数とも無視
            "オートロック",      # 重複
        ]
        categories = [
            c.code for n in names if (c := lookup_feature_category(n)) is not None
        ]
        assert satisfiable_codes_from_categories(categories) == satisfiable_codes(names)

    def test_composite_code_derives_parent_and_cross(self):
        assert satisfiable_codes_from_categories(["bicycle_parking.fee_free"]) == [
            "bicycle_parking",
            "bicycle_parking.fee_free",
            "fee_free",
        ]
        assert satisfiable_codes_from_categories(["internet.fee_free"]) == [
            "fee_free",
            "internet",
            "internet.fee_free",
        ]

    def test_simple_code_has_no_derived_codes(self):
        assert satisfiable_codes_from_categories(["auto_lock", "aircon"]) == [
            "aircon",
            "auto_lock",
        ]

    def test_null_and_empty_categories_are_ignored(self):
        # category NULL 行(辞書外語彙)は配信に寄与しない(設計 §4.2)
        assert satisfiable_codes_from_categories([None, "", "auto_lock"]) == ["auto_lock"]
        assert satisfiable_codes_from_categories([]) == []

    def test_malformed_composite_parent_is_not_derived(self):
        # 親 code が PARENT_CODES に無い不正 category は、生の値と横断 code
        # (接尾辞が実在修飾語の場合)のみで親 code は導出しない
        result = satisfiable_codes_from_categories(["unknown_parent.fee_free"])
        assert result == ["fee_free", "unknown_parent.fee_free"]
