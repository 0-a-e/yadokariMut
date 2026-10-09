"""required_features 値の解決器(設計 §3.2 — post filter と SQL 前段の両方が再利用)。

required の各値 r を「code 要件(feature 単位 code の集合)」へ解決する。解決順:

1. 単純 / 複合 code の直接指定       ``'washing_machine'`` / ``'bicycle_parking.fee_free'``
2. 親 code(束ね)→ 子 code 全体の OR  ``'bicycle_parking'``
3. 横断 code(修飾語・佃用可)         ``'fee_free'`` → その修飾語を持つ全複合 code
4. 旧 code → 現行 code(code_aliases・決定 19)
5. 寛容受入(label・include 生値 → 所属 code・両辺正規化)
6. 生名 fallback(辞書のいずれにも無い値 → 実値完全一致)

判定は feature 単位(物件レベルのタグ和集合判定は行わない — 決定 18)。
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.feature_categories import (
    CODE_ALIASES,
    FEATURE_CATEGORIES,
    PARENT_CODES,
    cross_codes,
    lookup_feature_category,
)

_UNIT_CODE_SET: frozenset[str] = frozenset(c.code for c in FEATURE_CATEGORIES)
_CROSS_CODE_SET: frozenset[str] = frozenset(cross_codes())


@dataclass(frozen=True)
class FeatureRequirement:
    """required_features の 1 要件の解決結果。"""

    raw: str                     # 呼び出し側が渡した元の値
    codes: frozenset[str]        # 解決された feature 単位 code 集合(空 = 生名 fallback)
    is_fallback: bool            # True = 辞書外生値として実値完全一致で判定


def resolve_requirement(raw: str) -> FeatureRequirement:
    """required 値 1 つを code 要件へ解決する。"""
    value = raw.strip()
    if not value:
        return FeatureRequirement(raw=raw, codes=frozenset(), is_fallback=True)

    if value in _UNIT_CODE_SET:
        return FeatureRequirement(raw=raw, codes=frozenset({value}), is_fallback=False)
    if value in PARENT_CODES:
        return FeatureRequirement(
            raw=raw, codes=frozenset(PARENT_CODES[value]), is_fallback=False
        )
    if value in _CROSS_CODE_SET:
        suffix = "." + value
        codes = frozenset(c for c in _UNIT_CODE_SET if c.endswith(suffix))
        return FeatureRequirement(raw=raw, codes=codes, is_fallback=False)

    alias = CODE_ALIASES.get(value)
    if alias and alias != value:
        resolved = resolve_requirement(alias)
        return FeatureRequirement(
            raw=raw, codes=resolved.codes, is_fallback=False
        )

    category = lookup_feature_category(value)  # 寛容受入(label・include 生値)
    if category is not None:
        return FeatureRequirement(
            raw=raw, codes=frozenset({category.code}), is_fallback=False
        )

    # 生名 fallback: 辞書外生値。DB 生値との完全一致(正規化しない — 設計 §3.1)
    return FeatureRequirement(raw=raw, codes=frozenset(), is_fallback=True)


def resolve_requirements(values: list[str] | None) -> list[FeatureRequirement]:
    """required_features 全要素を解決する(CSV 文字列は呼び出し層で分割済みとする)。"""
    if not values:
        return []
    return [resolve_requirement(v) for v in values]


def feature_codes_of(names: list[str]) -> frozenset[str]:
    """物件の feature_name 列から feature 単位 code 集合を導出する(未知語は無視)。"""
    codes: set[str] = set()
    for name in names:
        category = lookup_feature_category(name)
        if category is not None:
            codes.add(category.code)
    return frozenset(codes)


def satisfiable_codes(names: list[str]) -> list[str]:
    """物件の feature_names から充足可能 code 集合(設計 §3.3)を導出する(辞書順)。

    feature_name → 辞書 lookup の結果を satisfiable_codes_from_categories へ渡す
    薄いラッパ。category 直読み版と常に同一の出力になる(契約テスト:
    tests/test_feature_resolution.py)。
    """
    codes: list[str] = []
    for name in names:
        category = lookup_feature_category(name)
        if category is not None:
            codes.append(category.code)
    return satisfiable_codes_from_categories(codes)


def satisfiable_codes_from_categories(categories: list[str]) -> list[str]:
    """property_features.category 列(code)の直読みから充足可能 code 集合を導出する(辞書順)。

    各 feature の code(単純/複合)に加え、導出 code(親 code・横断 code)を含める
    (例: bicycle_parking.fee_free → + bicycle_parking / fee_free)。親/横断の導出は
    辞書正本(domain.feature_categories の PARENT_CODES と複合 code 接尾辞 = 横断 code
    集合)に照らして行い、未知の親・修飾語は載せない。単一配列の集合包含で任意の
    粒度の required 判定が feature 単位で完結する(設計 §3.3)。
    NULL / 空文字の category(辞書外語彙)は配列に載せない(差分検知 §5 の検出対象)。
    """
    codes: set[str] = set()
    for category in categories:
        if not category:
            continue
        codes.add(category)
        if "." in category:
            parent, _, modifier = category.partition(".")
            if parent in PARENT_CODES:
                codes.add(parent)
            if modifier in _CROSS_CODE_SET:
                codes.add(modifier)
    return sorted(codes)


def property_matches(
    feature_names: list[str] | set[str],
    requirements: list[FeatureRequirement],
) -> bool:
    """物件が全要件を満たすか(要件間 AND・code 集合内 OR・feature 単位・設計 §3.2)。"""
    if not requirements:
        return True
    names = set(feature_names)
    codes = feature_codes_of(names)
    for req in requirements:
        if req.is_fallback:
            if req.raw not in names:
                return False
        elif not (req.codes & codes):
            return False
    return True
