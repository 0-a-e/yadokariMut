"""Source adapters for multi-source ingestion."""

from sources.registry import SourceRegistry

# Side-effect registration
from sources.bratto import BrattoAdapter  # noqa: F401
from sources.unionmonthly import UnionMonthlyAdapter  # noqa: F401

__all__ = ["SourceRegistry", "BrattoAdapter", "UnionMonthlyAdapter"]
