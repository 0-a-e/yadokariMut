"""Union Monthly source adapter."""

from __future__ import annotations

import logging
from typing import Optional

from sources.base import FetchedPage, ListCard, ListTarget, SourceAdapter
from sources.registry import SourceRegistry
from sources.unionmonthly.detail_parser import PARSER_VERSION, parse_detail_html
from sources.unionmonthly.list_parser import extract_total_count, parse_list_html
from store.pref_master import pref_display_name

logger = logging.getLogger(__name__)

# config.json sources.unionmonthly.prefectures 欠落時のみ使うフォールバック。
# 県名は pref_master 正本から派生(pref_id はサイト固有値のまま残す)。
DEFAULT_PREFS = {
    slug: {"name": pref_display_name(slug), "pref_id": pref_id}
    for slug, pref_id in {
        "tokyo": "PF13",
        "kanagawa": "PF14",
        "chiba": "PF12",
        "saitama": "PF11",
        "ibaraki": "PF08",
    }.items()
}


@SourceRegistry.register("unionmonthly")
class UnionMonthlyAdapter(SourceAdapter):
    source_id = "unionmonthly"
    display_name = "ユニオンマンスリー"
    parser_version = PARSER_VERSION

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.base_url = (self.config.get("base_url") or "https://www.unionmonthly.jp").rstrip("/")
        self.prefs = self.config.get("prefectures") or DEFAULT_PREFS
        self.list_mode = self.config.get("list_mode") or "pref_get"

    def discover_list_targets(self) -> list[ListTarget]:
        only = self.config.get("pref_filter")  # optional list of slugs
        targets: list[ListTarget] = []
        for slug, meta in self.prefs.items():
            if only and slug not in only:
                continue
            name = meta.get("name") if isinstance(meta, dict) else str(meta)
            pref_id = meta.get("pref_id") if isinstance(meta, dict) else None
            list_url = f"{self.base_url}/{slug}/room/"
            targets.append(
                ListTarget(
                    key=slug,
                    list_url=list_url,
                    prefecture_slug=slug,
                    prefecture_name=name,
                    meta={"pref_id": pref_id},
                )
            )
        return targets

    def build_list_page_url(self, target: ListTarget, page: int) -> str:
        if page <= 1:
            return target.list_url
        sep = "&" if "?" in target.list_url else "?"
        return f"{target.list_url}{sep}p={page}"

    def parse_list(self, page: FetchedPage, target: ListTarget) -> list[ListCard]:
        return parse_list_html(
            page.html,
            base_url=self.base_url,
            prefecture_slug=target.prefecture_slug,
            prefecture_name=target.prefecture_name,
        )

    def list_total_count(self, page: FetchedPage) -> Optional[int]:
        return extract_total_count(page.html)

    def parse_detail(self, page: FetchedPage, card: ListCard):
        return parse_detail_html(
            page.html,
            card=card,
            base_url=self.base_url,
            detail_url=page.url or card.detail_url,
        )

    def fetch_list_page(self, target: ListTarget, page: int) -> FetchedPage:
        url = self.build_list_page_url(target, page)
        return self.fetch(url, page_type="list")

    def fetch_detail_page(self, card: ListCard) -> FetchedPage:
        return self.fetch(card.detail_url, page_type="detail")

    def fetch_city_codes(self, pref_slug: str) -> list[str]:
        """Optional: GET /{pref}/city/ for city_post mode."""
        url = f"{self.base_url}/{pref_slug}/city/"
        page = self.fetch(url, page_type="city")
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page.html, "html.parser")
        return [i.get("value") for i in soup.select('input[name="city[]"]') if i.get("value")]
