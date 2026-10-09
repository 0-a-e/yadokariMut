"""BraTTo のプラン語彙 (パーサ用・設計 §3.6)。

``domain/plan_catalog.py`` (表示語彙の SSOT) とは役割が異なり、本モジュールは
BraTTo のページ語彙を plan_key へ正規化するスクレイパ側の知識を持つ
(新サイト追加時に触る場所はサイトパッケージ — domain/pricing.py から移設)。
"""

from __future__ import annotations

# BraTTo の滞在帯プリセット (日数)。detail 由来の plan_code から
# duration_min_days/max_days を補完する際の既定値。
BRATTO_DURATION_BANDS: dict[str, tuple[int, int | None]] = {
    "s_short": (1, 29),
    "short": (30, 90),
    "middle": (91, 180),
    "long": (181, None),
}

# BraTTo プラン名の語彙 → plan_code。語彙は BRATTO_DURATION_BANDS と同一系。
# 「sショート」に「ショート」が部分一致するため、s_short を必ず先に判定する
# (辞書の挿入順がマッチ優先度を決める)。未一致はパーサ側で "other"。
BRATTO_PLAN_CODE_MAP: dict[str, tuple[str, ...]] = {
    "s_short": ("sショート", "s-short", "1ヶ月未満"),
    "short": ("ショート", "1ヶ月~3ヶ月", "1～3ヶ月"),
    "middle": ("ミドル", "3ヶ月～6ヶ月", "3～6ヶ月"),
    "long": ("ロング", "6ヶ月以上"),
}


def resolve_bratto_plan_code(plan_name: str) -> str:
    """BraTTo プラン表示名 → plan_code (未一致は "other")。"""
    name_lower = (plan_name or "").lower()
    for code, keywords in BRATTO_PLAN_CODE_MAP.items():
        if any(kw in name_lower for kw in keywords):
            return code
    return "other"
