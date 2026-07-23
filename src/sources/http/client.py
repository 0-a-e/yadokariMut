"""HttpFetchClient: direct fetch + optional proxy fallback skeleton."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from sources.http.metrics import TransferMetrics, get_transfer_metrics
from sources.http.providers.base import UnconfiguredProxyProvider
from sources.http.restriction import is_restricted
from sources.http.settings import HttpFetchSettings, load_http_settings

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """All transports failed or hard error."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    page_type: str
    transport: str = "direct"
    attempts: int = 1
    restricted_before_proxy: bool = False
    bytes_downloaded: int = 0
    bytes_uploaded: int = 0


class HttpFetchClient:
    """Shared HTTP client for all SourceAdapters.

    Proxy path is a skeleton: enabled only when ``mode`` is fallback/always_proxy
    **and** ``SCRAPE_HTTP_PROXY`` (or HTTP_PROXY) is set. No SaaS providers yet.
    Default ``SCRAPE_HTTP_MODE=off`` keeps behavior equivalent to direct-only.
    """

    def __init__(
        self,
        *,
        source_id: str = "unknown",
        settings: HttpFetchSettings | None = None,
        session: requests.Session | None = None,
        metrics: TransferMetrics | None = None,
        default_headers: dict[str, str] | None = None,
    ):
        self.source_id = source_id
        self.settings = settings or load_http_settings()
        self.session = session or requests.Session()
        if default_headers:
            self.session.headers.update(default_headers)
        self.metrics = metrics or get_transfer_metrics()
        self._cooldown_until: dict[str, float] = {}

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        page_type: str = "list",
        headers: dict[str, str] | None = None,
        data: Any = None,
        timeout: float | None = None,
        delay_seconds: float = 0,
        **kwargs: Any,
    ) -> FetchResult:
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        timeout = timeout if timeout is not None else self.settings.timeout_seconds
        transports = self._transport_order()
        last_err: Exception | None = None
        restricted_before_proxy = False
        attempts = 0

        for transport in transports:
            for retry in range(self.settings.max_retries + 1):
                attempts += 1
                try:
                    if transport == "direct":
                        result = self._direct(
                            url,
                            method=method,
                            headers=headers,
                            data=data,
                            timeout=timeout,
                            **kwargs,
                        )
                    elif transport == "proxy":
                        result = self._proxy(
                            url,
                            method=method,
                            headers=headers,
                            data=data,
                            timeout=timeout,
                            **kwargs,
                        )
                    else:
                        raise FetchError(f"Unknown transport: {transport}")
                except Exception as e:
                    last_err = e
                    self.metrics.record(
                        self.source_id,
                        transport="proxy" if transport == "proxy" else "direct",
                        error=True,
                    )
                    logger.warning(
                        "fetch error source=%s transport=%s retry=%s url=%s err=%s",
                        self.source_id,
                        transport,
                        retry,
                        url,
                        e,
                    )
                    if retry < self.settings.max_retries:
                        time.sleep(min(30.0, 1.5 * (2**retry)))
                        continue
                    break

                body = result["text"]
                status = int(result["status_code"])
                bytes_down = len(body.encode("utf-8", errors="replace"))
                bytes_up = _estimate_upload_bytes(data)

                restricted, reason = is_restricted(
                    status_code=status,
                    body=body,
                    settings=self.settings,
                )
                self.metrics.record(
                    self.source_id,
                    bytes_down=bytes_down,
                    bytes_up=bytes_up,
                    transport="proxy" if transport == "proxy" else "direct",
                    restricted=restricted,
                )

                if restricted:
                    logger.warning(
                        "restriction detected source=%s transport=%s reason=%s status=%s url=%s",
                        self.source_id,
                        transport,
                        reason,
                        status,
                        url,
                    )
                    if transport == "direct":
                        restricted_before_proxy = True
                        self._mark_cooldown()
                    break

                return FetchResult(
                    url=result["final_url"],
                    html=body,
                    status_code=status,
                    page_type=page_type,
                    transport=transport,
                    attempts=attempts,
                    restricted_before_proxy=restricted_before_proxy,
                    bytes_downloaded=bytes_down,
                    bytes_uploaded=bytes_up,
                )

        msg = f"All transports failed for {url}"
        if last_err:
            msg = f"{msg}: {last_err}"
        raise FetchError(msg)

    def _transport_order(self) -> list[str]:
        mode = self.settings.mode
        if mode == "off" or not self.settings.proxy_enabled:
            return ["direct"]
        if mode == "always_proxy":
            return ["proxy"]
        if self._in_cooldown():
            return ["proxy", "direct"]
        return ["direct", "proxy"]

    def _in_cooldown(self) -> bool:
        until = self._cooldown_until.get(self.source_id, 0.0)
        return time.monotonic() < until

    def _mark_cooldown(self) -> None:
        self._cooldown_until[self.source_id] = time.monotonic() + float(
            self.settings.cooldown_seconds
        )

    def _direct(
        self,
        url: str,
        *,
        method: str,
        headers: dict | None,
        data: Any,
        timeout: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        method_u = method.upper()
        req_headers = dict(headers or {})
        if method_u == "POST":
            resp = self.session.post(
                url, headers=req_headers or None, data=data, timeout=timeout, **kwargs
            )
        else:
            resp = self.session.get(
                url, headers=req_headers or None, timeout=timeout, **kwargs
            )
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return {
            "status_code": resp.status_code,
            "text": resp.text,
            "final_url": str(resp.url),
        }

    def _proxy(
        self,
        url: str,
        *,
        method: str,
        headers: dict | None,
        data: Any,
        timeout: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.settings.http_proxy_url:
            UnconfiguredProxyProvider().fetch(url)

        proxies = {
            "http": self.settings.http_proxy_url,
            "https": self.settings.http_proxy_url,
        }
        method_u = method.upper()
        req_headers = dict(headers or {})
        if method_u == "POST":
            resp = self.session.post(
                url,
                headers=req_headers or None,
                data=data,
                timeout=timeout,
                proxies=proxies,
                **kwargs,
            )
        else:
            resp = self.session.get(
                url,
                headers=req_headers or None,
                timeout=timeout,
                proxies=proxies,
                **kwargs,
            )
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return {
            "status_code": resp.status_code,
            "text": resp.text,
            "final_url": str(resp.url),
        }


def _estimate_upload_bytes(data: Any) -> int:
    if data is None:
        return 0
    if isinstance(data, (bytes, bytearray)):
        return len(data)
    if isinstance(data, str):
        return len(data.encode("utf-8", errors="replace"))
    try:
        return len(str(data).encode("utf-8", errors="replace"))
    except Exception:
        return 0
