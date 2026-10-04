"""BraTTo パーサ互換シム。

実装は責務ごとに分割済み:
  - sources.bratto.list_parser   一覧ページ抽出 (parse_list_page / parse_pagination)
  - sources.bratto.detail_parser 詳細ページ抽出 (parse_detail_page)
  - sources.bratto.normalize     正規化 (normalize_property / _load_prefecture_map)
  - sources.parsing              スカラー値テキストパース共通層

このモジュールは旧 import 経路 (``sources.bratto.parser.parse_money`` 等、
tests / 外部から参照される) のための再輸出のみを行う。新規コードは
各実装モジュールから直接 import すること。
"""

from __future__ import annotations

from sources.parsing import (  # noqa: F401
    parse_access_parts,
    parse_area,
    parse_dates_from_text,
    parse_japanese_era,
    parse_money,
    parse_walk_minutes,
)
from sources.bratto.detail_parser import parse_detail_page  # noqa: F401
from sources.bratto.list_parser import (  # noqa: F401
    parse_list_page,
    parse_pagination,
)
from sources.bratto.normalize import (  # noqa: F401
    _load_prefecture_map,
    normalize_property,
)

__all__ = [
    "parse_money",
    "parse_area",
    "parse_walk_minutes",
    "parse_dates_from_text",
    "parse_japanese_era",
    "parse_access_parts",
    "parse_list_page",
    "parse_pagination",
    "parse_detail_page",
    "normalize_property",
    "_load_prefecture_map",
]
