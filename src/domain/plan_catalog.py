"""プラン表示語彙辞書 (SSOT・設計 §3.6 / 第 1.7 段)。

設計正本: ``docs/feature-category-unification-design.md`` §3.6 / §4.3。
機能カテゴリ辞書 (``domain/feature_categories.py``) と同じパターン
(BE 辞書・BE 展開配信・FE 辞書なし) の第二適用。責務は「表示」のみで、
滞在帯の解決は ``price_plans.duration_min_days/max_days`` が正本
(parity 契約 ``contracts/stay_calc_cases.json`` が品質保証)。

- **開集合 + 生名フォールバック**: 辞書に無い ``plan_key`` は
  ``plan_label()`` が ``plan_name`` (生値) へフォールバックして配信する。
  新コードは ``unknown_plan_codes()`` 差分検知 (§5-5) で検知した上で
  (a) 意味的に同型の帯なら正規コードへ map (b) 構造が異なれば新コードを
  mint (c) フォールバックのまま許容 — の三択。force-map (語義汚染) は禁止。
- **サイト固有の語彙は置かない**: パーサ用 label→code マップや滞在帯
  プリセット (BRATTO/UNION の ``*_PLAN_CODE_MAP`` / ``*_DURATION_BANDS``)
  は新サイト追加時に触るもののため ``src/sources/<site>/`` に置く
  (domain → sources の import は依存逆転のため禁止)。
- **``all`` は campaign target 固有の擬似コード**: プラン語彙ではなく
  「全プラン対象」の意味のため辞書に入れず、``target_plan_label()`` で
  「すべてのプラン」に解決する (差分検知の母集団からも除外)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PlanCatalogEntry:
    """プラン語彙辞書の 1 エントリ。

    ``label`` は名称のみ。帯レンジ (「1ヶ月未満」等) は含めない —
    レンジは各プランの wire データ (``duration_text`` /
    ``duration_min_days/max_days``) から UI 側で合成する (サイト別実態が
    異なる帯レンジの恒久的な誤表示を避けるため・2026-10-08 承認)。
    """

    label: str


# code → entry。code は price_plans.plan_key / campaigns.target_plan_key の
# 正規コード (2026-10-08 本番実測: 実語彙は bratto 4 コード + unionmonthly
# 5 コード (semi_short 追加) のみで閉じている)。
PLAN_CATALOG: dict[str, PlanCatalogEntry] = {
    "s_short": PlanCatalogEntry(label="Sショート"),
    "semi_short": PlanCatalogEntry(label="セミショート"),
    "short": PlanCatalogEntry(label="ショート"),
    "middle": PlanCatalogEntry(label="ミドル"),
    "long": PlanCatalogEntry(label="ロング"),
}

# campaigns.target_plan_key 専用の擬似コード (プラン語彙ではない)。
CAMPAIGN_TARGET_PSEUDO_CODES: frozenset[str] = frozenset({"all"})

# target が全プランを指す場合 (all / 空 / NULL) の表示ラベル。
ALL_PLANS_LABEL = "すべてのプラン"


def plan_label(code: str | None, plan_name: str | None) -> str:
    """plan_key → 表示ラベル (辞書解決・未知コードは plan_name 生値フォールバック)。

    表示の正はレンジ無しの辞書ラベル。``plan_name`` は未知コードの
    フォールバック専用 (unionmonthly はレンジ付き plan_name を書くため、
    既知コードではレンジ無しラベルを優先する)。どちらも無ければ空文字。
    """
    if code:
        entry = PLAN_CATALOG.get(str(code).strip().lower())
        if entry is not None:
            return entry.label
    return plan_name or ""


def target_plan_label(code: str | None) -> str:
    """campaigns.target_plan_key → 表示ラベル。

    ``all`` / 空 / NULL は「すべてのプラン」(``domain.pricing.campaign_targets_plan_key``
    の全プラン判定と同じ語彙)。既知コードは辞書ラベル、未知コードは生値
    (差分検知で仕分けるまでの一時表示)。
    """
    key = str(code or "").strip().lower()
    if not key or key in CAMPAIGN_TARGET_PSEUDO_CODES:
        return ALL_PLANS_LABEL
    entry = PLAN_CATALOG.get(key)
    if entry is not None:
        return entry.label
    return code or ""


def plan_catalog_codes() -> frozenset[str]:
    """辞書コード集合 (差分検知の右辺)。"""
    return frozenset(PLAN_CATALOG)


def unknown_plan_codes(observed: Iterable[str | None]) -> list[str]:
    """観測語彙集合から辞書未収録の plan_key を検知する (差分検知・§5-5)。

    ``observed`` は ``SELECT DISTINCT plan_key`` ∪
    ``SELECT DISTINCT campaigns.target_plan_key`` に相当する語彙集合。
    ``all`` (campaign 擬似コード) と空値は母集団から除外する。
    戻り値は正規化 (strip + lower) 済みのソート済みリスト (決定的)。
    """
    known = plan_catalog_codes() | CAMPAIGN_TARGET_PSEUDO_CODES
    observed_keys = {
        str(c).strip().lower()
        for c in observed
        if c is not None and str(c).strip()
    }
    return sorted(observed_keys - known)
