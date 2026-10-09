"""BraTTo (000area-weekly.com) source adapter — wraps legacy parser."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from store.pref_master import pref_display_name
from store.source_catalog import load_app_config

from sources.base import FetchedPage, ListCard, ListTarget, SourceAdapter
from sources.bratto.convert import PARSER_VERSION, draft_from_normalized
from sources.bratto.detail_parser import parse_detail_page
from sources.bratto.list_parser import parse_list_page, parse_pagination
from sources.bratto.normalize import normalize_property
from sources.parsing import parse_money
from sources.registry import SourceRegistry

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://www.000area-weekly.com"


def _load_bratto_config() -> dict:
    """config.json の sources.bratto ブロック(load_app_config 経由の唯一の入口)。

    呼び出し元(cli 等)が渡す config とマージして使うため、
    旧実装のようなアダプタ内 config.json 直読み(二重読み)はしない。
    """
    return ((load_app_config().get("sources") or {}).get("bratto")) or {}


@SourceRegistry.register("bratto")
class BrattoAdapter(SourceAdapter):
    source_id = "bratto"
    display_name = "BraTTo"
    parser_version = PARSER_VERSION

    def __init__(self, config: dict | None = None):
        file_cfg = _load_bratto_config()
        merged = {**file_cfg, **(config or {})}
        super().__init__(merged)
        self.base_url = (self.config.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.prefs: dict[str, Any] = self.config.get("prefectures") or {}

    def discover_list_targets(self) -> list[ListTarget]:
        only = self.config.get("pref_filter")
        targets: list[ListTarget] = []
        for slug, meta in self.prefs.items():
            if only and slug not in only:
                continue
            if isinstance(meta, dict):
                name = meta.get("name") or pref_display_name(slug)
                list_path = meta.get("list_path") or f"/{slug}/search_list/"
            else:
                name = str(meta)
                list_path = f"/{slug}/search_list/"
            list_url = f"{self.base_url}{list_path}"
            targets.append(
                ListTarget(
                    key=slug,
                    list_url=list_url,
                    prefecture_slug=slug,
                    prefecture_name=name,
                    meta={"list_path": list_path},
                )
            )
        return targets

    def build_list_page_url(self, target: ListTarget, page: int) -> str:
        base = target.list_url
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}pn={page}"

    def page_size(self) -> int:
        return int(self.config.get("page_size", 20))

    def parse_list(self, page: FetchedPage, target: ListTarget) -> list[ListCard]:
        props, _info, _has_next, _next = parse_list_page(page.html, target_url=target.list_url)
        cards: list[ListCard] = []
        for p in props:
            rid = p.get("room_id")
            if not rid:
                continue
            p = dict(p)
            p["prefecture_slug"] = target.prefecture_slug
            p["prefecture_name"] = target.prefecture_name
            # list price: cheapest available daily if present
            list_price = None
            for _name, pv in (p.get("rent_plans") or {}).items():
                if isinstance(pv, dict) and pv.get("available"):
                    list_price = parse_money(
                        pv.get("discounted_daily_rent") or pv.get("original_daily_rent")
                    )
                    if list_price:
                        break
            cards.append(
                ListCard(
                    external_id=str(rid),
                    detail_url=p.get("detail_url") or "",
                    title=p.get("title"),
                    address=p.get("address"),
                    list_price_yen=list_price,
                    thumbnail_url=p.get("thumbnail_url"),
                    prefecture_slug=target.prefecture_slug,
                    prefecture_name=target.prefecture_name,
                    raw=p,
                )
            )
        return cards

    def has_next(self, page: FetchedPage, cards: list[ListCard]) -> bool | None:
        """検索結果の「次へ」リンク有無で終端を判定する。"""
        _info, has_next, _next_url = parse_pagination(self.soup(page), page.url)
        return has_next

    def parse_detail(self, page: FetchedPage, card: ListCard):
        detail = parse_detail_page(page.html, base_url=self.base_url)
        list_data = dict(card.raw) if card.raw else {
            "room_id": card.external_id,
            "title": card.title,
            "detail_url": card.detail_url,
            "address": card.address,
            "thumbnail_url": card.thumbnail_url,
            "prefecture_slug": card.prefecture_slug,
            "prefecture_name": card.prefecture_name,
        }
        if not list_data.get("room_id"):
            list_data["room_id"] = card.external_id
        if not list_data.get("detail_url"):
            list_data["detail_url"] = page.url or card.detail_url
        normalized = normalize_property(list_data, detail)
        normalized["detail_scraped_at"] = datetime.now().isoformat()
        draft = draft_from_normalized(normalized)
        if not draft.external_id:
            draft.external_id = card.external_id
        return draft
