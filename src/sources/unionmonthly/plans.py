"""Union Monthly のプラン語彙 (パーサ用・設計 §3.6)。

``domain/plan_catalog.py`` (表示語彙の SSOT) とは役割が異なり、本モジュールは
Union Monthly のタブ語彙・期間表記を plan_key / duration 帯へ正規化する
スクレイパ側の知識を持つ (domain/pricing.py から移設)。
stdlib + domain のみに依存するため、マイグレーション script からも
bs4 無しで import 可能。
"""

from __future__ import annotations

import re

from domain.pricing import MONTH_DAYS

# Union: 7–15日 / 15日–1ヶ月 / 1–3 / 3–7 / 7–24 months
# (day approx, exclusive upper bound as max inclusive; 月=30日, 年=365日)
UNION_DURATION_BANDS: dict[str, tuple[int, int | None]] = {
    "s_short": (7, 14),
    "semi_short": (15, 29),
    "short": (30, 89),
    "middle": (90, 209),
    "long": (210, 729),
}

# Union Monthly のプランタブ表示名 → plan_key。語彙は UNION_DURATION_BANDS と同一系。
# タブ名が未知のときのフォールバック(key 正規化)はパーサ側で行う。
UNION_PLAN_CODE_MAP: dict[str, str] = {
    "ショート": "short",
    "ミドル": "middle",
    "ロング": "long",
    "スーパーショート": "s_short",
    "sショート": "s_short",
    "セミショート": "semi_short",
}

_DURATION_TEXT_PATTERNS: tuple[tuple[str, int], ...] = (
    # (pattern, days-per-unit): 以上 → min, 未満 → unit_days - 1 (inclusive max)
    (r"(\d+)\s*日以上", 1),
    (r"(\d+)\s*日未満", 1),
    (r"(\d+)\s*[かヶヵカ]月以上", MONTH_DAYS),
    (r"(\d+)\s*[かヶヵカ]月未満", MONTH_DAYS),
    (r"(\d+)\s*年以上", 365),
    (r"(\d+)\s*年未満", 365),
)


def parse_union_duration_text(text: str | None) -> tuple[int | None, int | None]:
    """Parse a Union Monthly duration label into (min_days, max_days).

    Examples: '7日以上-15日未満' → (7, 14), '15日以上-1ヶ月未満' → (15, 29),
    '1ヶ月以上-3ヶ月未満' → (30, 89), '7ヶ月以上-2年未満' → (210, 729).
    Returns (None, None) when no duration range is found.
    """
    if not text:
        return None, None
    t = str(text)
    dmin: int | None = None
    dmax: int | None = None
    for pat, unit_days in _DURATION_TEXT_PATTERNS:
        m = re.search(pat, t)
        if not m:
            continue
        n = int(m.group(1))
        if pat.endswith("以上"):
            dmin = n * unit_days
        else:
            dmax = n * unit_days - 1
    return dmin, dmax
