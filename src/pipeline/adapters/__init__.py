from __future__ import annotations

from typing import Any

from .base import Adapter, FetchStats, RawRecord
from .csv_adapter import CsvAdapter
from .wfs import WfsAdapter

# A new source type is one adapter class plus one entry here.
REGISTRY = {"wfs": WfsAdapter, "csv": CsvAdapter}


def build(source_type: str, options: dict[str, Any]) -> Adapter:
    return REGISTRY[source_type](options)


__all__ = ["Adapter", "FetchStats", "RawRecord", "build", "REGISTRY"]
