"""Change detection over the business key, done before anything is replaced."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class Diff:
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0

    def counts(self) -> dict[str, int]:
        return {"neu": len(self.new), "geaendert": len(self.changed),
                "geloescht": len(self.deleted), "unveraendert": self.unchanged}


def record_key(row: Mapping[str, Any], key_columns: list[str]) -> str:
    """JSON list of the key values as text; safe for any character in the values."""
    return json.dumps([None if row.get(c) is None else str(row[c]) for c in key_columns], ensure_ascii=False)


def key_values(key: str) -> list[str | None]:
    return json.loads(key)


def record_hash(row: Mapping[str, Any], geometry_wkb: bytes | None) -> str:
    payload = json.dumps({k: (None if v is None else str(v)) for k, v in sorted(row.items())},
                         ensure_ascii=False, sort_keys=True).encode()
    h = hashlib.sha256(payload)
    if geometry_wkb is not None:
        h.update(geometry_wkb)
    return h.hexdigest()


def compute(incoming: Mapping[str, str], existing: Mapping[str, str]) -> Diff:
    """incoming/existing: business key -> content hash."""
    d = Diff()
    for k, h in incoming.items():
        old = existing.get(k)
        if old is None:
            d.new.append(k)
        elif old != h:
            d.changed.append(k)
        else:
            d.unchanged += 1
    d.deleted = [k for k in existing if k not in incoming]
    return d
