"""Provider protocol for future external proxy APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    status_code: int
    text: str
    final_url: str
    headers: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def content_bytes(self) -> int:
        return len(self.text.encode("utf-8", errors="replace"))


@runtime_checkable
class ProxyProvider(Protocol):
    """External fetch backend.

    Concrete SaaS providers are intentionally not implemented yet.
    Register implementations here when a vendor is chosen.
    """

    id: str

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: Any = None,
        timeout: float = 45,
    ) -> ProviderResponse: ...


class UnconfiguredProxyProvider:
    """Placeholder that always fails — used when mode requests proxy but none configured."""

    id = "unconfigured"

    def fetch(self, url: str, **kwargs) -> ProviderResponse:
        raise RuntimeError(
            "Proxy transport requested but no provider is configured. "
            "Set SCRAPE_HTTP_PROXY or implement a ProxyProvider, "
            "or keep SCRAPE_HTTP_MODE=off."
        )
