"""Registry mapping source_id -> SourceAdapter class (lazy import)."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Optional, Type

if TYPE_CHECKING:
    from sources.base import SourceAdapter


class SourceRegistry:
    _adapters: dict[str, Type["SourceAdapter"]] = {}

    # source_id → アダプタモジュール。get()/create()/get_all() 呼び出し時に
    # ensure_loaded() が importlib で遅延 import し、@register の副作用登録を
    # 走らせる。新ソース追加時はここにモジュールパスを追記する
    # (明示 import しなくても Registry 経由で解決できるようにするため)。
    _adapter_modules: dict[str, str] = {
        "bratto": "sources.bratto.adapter",
        "unionmonthly": "sources.unionmonthly.adapter",
    }

    @classmethod
    def register(cls, source_id: str):
        def decorator(adapter_cls: Type["SourceAdapter"]):
            cls._adapters[source_id.lower()] = adapter_cls
            return adapter_cls

        return decorator

    @classmethod
    def ensure_loaded(cls) -> None:
        """アダプタモジュールを遅延 import して登録を保証する。

        ``import sources`` 単独では副作用登録が走らないため、
        Registry 経由の参照(get/create/get_all)がこの地点で
        アダプタを解決できるようにする。
        """
        for source_id, module_name in cls._adapter_modules.items():
            if source_id in cls._adapters:
                continue
            importlib.import_module(module_name)

    @classmethod
    def get(cls, source_id: str) -> Optional[Type["SourceAdapter"]]:
        cls.ensure_loaded()
        return cls._adapters.get(source_id.lower())

    @classmethod
    def get_all(cls) -> dict[str, Type["SourceAdapter"]]:
        cls.ensure_loaded()
        return dict(cls._adapters)

    @classmethod
    def create(cls, source_id: str, config: dict | None = None) -> "SourceAdapter":
        adapter_cls = cls.get(source_id)
        if adapter_cls is None:
            known = ", ".join(sorted(cls._adapters)) or "(none)"
            raise KeyError(f"Unknown source '{source_id}'. Registered: {known}")
        return adapter_cls(config or {})
