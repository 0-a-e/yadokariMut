"""Base types and HTTP helpers for source adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from domain.models import PropertyDraft
from sources.http.client import FetchError, HttpFetchClient
from sources.http.metrics import get_transfer_metrics
from sources.http.settings import load_http_settings

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
}


@dataclass
class ListTarget:
    """One crawl unit (e.g. a prefecture list)."""

    key: str
    list_url: str
    prefecture_slug: str | None = None
    prefecture_name: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchedPage:
    url: str
    html: str
    status_code: int
    page_type: str  # list | detail | city
    transport: str = "direct"
    attempts: int = 1
    restricted_before_proxy: bool = False
    bytes_downloaded: int = 0
    bytes_uploaded: int = 0


@dataclass
class ListCard:
    """Minimal listing card before detail scrape."""

    external_id: str
    detail_url: str
    title: str | None = None
    address: str | None = None
    list_price_yen: int | None = None
    thumbnail_url: str | None = None
    prefecture_slug: str | None = None
    prefecture_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    source_id: str = "base"
    display_name: str = "Base"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.delay = float(self.config.get("delay_seconds", 2.0))
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        # Per-adapter HTTP client (shares process-wide transfer metrics)
        self.http = HttpFetchClient(
            source_id=self.source_id,
            settings=load_http_settings(),
            session=self.session,
            metrics=get_transfer_metrics(),
            default_headers=DEFAULT_HEADERS,
        )

    def rate_limit(self) -> None:
        # delay is applied inside HttpFetchClient.request via delay_seconds
        pass

    def fetch(self, url: str, *, page_type: str = "list", method: str = "GET", **kwargs) -> FetchedPage:
        logger.info("Fetching %s %s", method, url)
        data = kwargs.pop("data", None)
        headers = kwargs.pop("headers", None)
        try:
            result = self.http.request(
                url,
                method=method,
                page_type=page_type,
                headers=headers,
                data=data,
                delay_seconds=self.delay,
                **kwargs,
            )
        except FetchError:
            raise
        # Non-2xx that was not classified as restriction still surfaces as error
        if result.status_code >= 400:
            raise FetchError(
                f"HTTP {result.status_code} for {url}",
                status_code=result.status_code,
            )
        return FetchedPage(
            url=result.url,
            html=result.html,
            status_code=result.status_code,
            page_type=page_type,
            transport=result.transport,
            attempts=result.attempts,
            restricted_before_proxy=result.restricted_before_proxy,
            bytes_downloaded=result.bytes_downloaded,
            bytes_uploaded=result.bytes_uploaded,
        )

    def soup(self, page: FetchedPage) -> BeautifulSoup:
        return BeautifulSoup(page.html, "html.parser")

    @abstractmethod
    def discover_list_targets(self) -> list[ListTarget]:
        ...

    @abstractmethod
    def build_list_page_url(self, target: ListTarget, page: int) -> str:
        ...

    @abstractmethod
    def parse_list(self, page: FetchedPage, target: ListTarget) -> list[ListCard]:
        ...

    @abstractmethod
    def parse_detail(self, page: FetchedPage, card: ListCard) -> PropertyDraft:
        ...

    def list_total_count(self, page: FetchedPage) -> int | None:
        """Optional: extract 'N 件' from list HTML."""
        return None

    def page_size(self) -> int:
        return int(self.config.get("page_size", 30))

    def fetch_list_page(self, target: ListTarget, page: int) -> FetchedPage:
        """GET list page. Override for POST-based scrapers."""
        url = self.build_list_page_url(target, page)
        return self.fetch(url, page_type="list")

    def fetch_detail_page(self, card: ListCard) -> FetchedPage:
        """GET detail page for a list card."""
        return self.fetch(card.detail_url, page_type="detail")
