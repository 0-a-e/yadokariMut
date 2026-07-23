"""HTTP fetch / proxy settings from env (+ optional config.json http block)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

HttpMode = Literal["off", "fallback", "always_proxy"]

DEFAULT_BLOCK_PATTERNS = (
    "Just a moment",
    "cf-browser-verification",
    "Access Denied",
    "アクセスが集中",
    "しばらくしてから",
)


@dataclass
class HttpFetchSettings:
    """Runtime HTTP policy.

    Proxy providers are intentionally not wired yet — ``mode=off`` is the safe
    default. When enabled later, only skeleton provider hooks exist.
    """

    mode: HttpMode = "off"
    max_retries: int = 2
    timeout_seconds: float = 45.0
    cooldown_seconds: float = 600.0
    restriction_status_codes: tuple[int, ...] = (403, 429, 503)
    body_block_patterns: tuple[str, ...] = DEFAULT_BLOCK_PATTERNS
    min_body_bytes: int = 500
    # Reserved for future providers (not used while mode=off)
    proxy_enabled: bool = False
    http_proxy_url: str | None = None
    provider_ids: list[str] = field(default_factory=list)


def load_http_settings(config: dict[str, Any] | None = None) -> HttpFetchSettings:
    """Load settings. Env overrides config.json ``http`` block."""
    cfg_http: dict[str, Any] = {}
    if config and isinstance(config.get("http"), dict):
        cfg_http = config["http"]
    else:
        cfg_http = _load_config_http_block()

    mode_raw = (
        os.environ.get("SCRAPE_HTTP_MODE")
        or os.environ.get("YADOKARIMUT_SCRAPE_HTTP_MODE")
        or cfg_http.get("mode")
        or "off"
    )
    mode = str(mode_raw).strip().lower()
    if mode not in ("off", "fallback", "always_proxy"):
        mode = "off"

    max_retries = int(
        os.environ.get("SCRAPE_HTTP_MAX_RETRIES")
        or cfg_http.get("max_retries")
        or 2
    )
    timeout = float(
        os.environ.get("SCRAPE_HTTP_TIMEOUT_SECONDS")
        or cfg_http.get("timeout_seconds")
        or 45
    )
    cooldown = float(
        os.environ.get("SCRAPE_PROXY_COOLDOWN_SECONDS")
        or cfg_http.get("cooldown_seconds")
        or 600
    )

    restriction = cfg_http.get("restriction") or {}
    status_codes = restriction.get("status_codes") or [403, 429, 503]
    patterns = restriction.get("body_block_patterns") or list(DEFAULT_BLOCK_PATTERNS)
    min_body = int(restriction.get("min_body_bytes") or 500)

    http_proxy = (
        os.environ.get("SCRAPE_HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or None
    )
    if http_proxy is not None:
        http_proxy = http_proxy.strip() or None

    # Providers remain disabled until a real implementation is added.
    # mode != off alone does not enable proxy without a configured transport.
    proxy_enabled = mode in ("fallback", "always_proxy") and bool(http_proxy)

    return HttpFetchSettings(
        mode=mode,  # type: ignore[arg-type]
        max_retries=max(0, max_retries),
        timeout_seconds=timeout,
        cooldown_seconds=cooldown,
        restriction_status_codes=tuple(int(c) for c in status_codes),
        body_block_patterns=tuple(str(p) for p in patterns),
        min_body_bytes=min_body,
        proxy_enabled=proxy_enabled,
        http_proxy_url=http_proxy,
        provider_ids=[],  # skeleton: no SaaS providers registered
    )


def _load_config_http_block() -> dict[str, Any]:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.json")
    path = os.path.abspath(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        block = data.get("http")
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}
