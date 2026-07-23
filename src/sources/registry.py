"""Registry mapping source_id -> SourceAdapter class."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Type

if TYPE_CHECKING:
    from sources.base import SourceAdapter


class SourceRegistry:
    _adapters: dict[str, Type["SourceAdapter"]] = {}

    @classmethod
    def register(cls, source_id: str):
        def decorator(adapter_cls: Type["SourceAdapter"]):
            cls._adapters[source_id.lower()] = adapter_cls
            return adapter_cls

        return decorator

    @classmethod
    def get(cls, source_id: str) -> Optional[Type["SourceAdapter"]]:
        return cls._adapters.get(source_id.lower())

    @classmethod
    def get_all(cls) -> dict[str, Type["SourceAdapter"]]:
        return dict(cls._adapters)

    @classmethod
    def create(cls, source_id: str, config: dict | None = None) -> "SourceAdapter":
        adapter_cls = cls.get(source_id)
        if adapter_cls is None:
            known = ", ".join(sorted(cls._adapters)) or "(none)"
            raise KeyError(f"Unknown source '{source_id}'. Registered: {known}")
        return adapter_cls(config or {})
