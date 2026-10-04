"""Source adapters for multi-source ingestion.

アダプタの登録は遅延 import 化されている: ``sources.registry.SourceRegistry``
の get()/create()/get_all() が ``ensure_loaded()`` でアダプタモジュールを
import し、@register デコレータの副作用で登録される。
明示的な ``from sources.bratto import BrattoAdapter`` は不要になった。
"""

from sources.registry import SourceRegistry

__all__ = ["SourceRegistry"]
