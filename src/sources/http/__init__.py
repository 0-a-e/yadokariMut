"""Shared HTTP fetch layer for scrapers (direct + optional proxy fallback)."""

from sources.http.client import FetchError, HttpFetchClient
from sources.http.metrics import TransferMetrics, get_transfer_metrics
from sources.http.settings import HttpFetchSettings, load_http_settings

__all__ = [
    "FetchError",
    "HttpFetchClient",
    "HttpFetchSettings",
    "TransferMetrics",
    "get_transfer_metrics",
    "load_http_settings",
]
