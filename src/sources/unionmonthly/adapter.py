"""Union Monthly source adapter."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

from sources.base import FetchedPage, ListCard, ListTarget, SourceAdapter
from sources.registry import SourceRegistry
from sources.unionmonthly.detail_parser import parse_detail_html
from sources.unionmonthly.list_parser import extract_total_count, parse_list_html

logger = logging.getLogger(__name__)

DEFAULT_PREFS = {
    "tokyo": {"name": "東京都", "pref_id": "PF13"},
    "kanagawa": {"name": "神奈川県", "pref_id": "PF14"},
    "chiba": {"name": "千葉県", "pref_id": "PF12"},
    "saitama": {"name": "埼玉県", "pref_id": "PF11"},
    "ibaraki": {"name": "茨城県", "pref_id": "PF08"},
}


@SourceRegistry.register("unionmonthly")
class UnionMonthlyAdapter(SourceAdapter):
    source_id = "unionmonthly"
    display_name = "ユニオンマンスリー"

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
