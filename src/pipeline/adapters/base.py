"""Common adapter interface: every source type yields raw records."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from shapely.geometry.base import BaseGeometry


@dataclass
class RawRecord:
    """Fields as named by the source, plus an optional geometry in EPSG:4326."""
    fields: dict[str, Any]
    geometry: BaseGeometry | None = None


@dataclass
class FetchStats:
    warnings: list[str] = field(default_factory=list)
    pages: int = 0


class Adapter(Protocol):
    stats: FetchStats

    def fetch(self) -> Iterator[RawRecord]:
        ...
