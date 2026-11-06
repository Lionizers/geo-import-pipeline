"""Loads and validates the source configuration (config/sources.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ADAPTER_TYPES = {"wfs", "csv"}
TARGET_KINDS = {"geometry", "attribute"}


class ConfigError(ValueError):
    pass


@dataclass
class Target:
    table: str
    kind: str
    geometry_column: str = "geom"
    geometry_type: str = "MULTIPOLYGON"
    required: list[str] = field(default_factory=list)


@dataclass
class Source:
    name: str
    type: str
    target: Target
    key: list[str]
    mapping: dict[str, str]
    options: dict[str, Any] = field(default_factory=dict)
    constants: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schedule: str | None = None
    enabled: bool = True
    max_delete_ratio: float = 0.5


@dataclass
class Config:
    sources: list[Source]
    reports_dir: Path


def _require(d: dict, k: str, where: str) -> Any:
    if k not in d or d[k] in (None, "", []):
        raise ConfigError(f"{where}: field '{k}' is missing")
    return d[k]


def _expand_env(value: Any) -> Any:
    """Allows ${VAR} in string values so that credentials stay out of the file."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def parse_source(raw: dict) -> Source:
    name = _require(raw, "name", "source")
    where = f"source '{name}'"
    typ = _require(raw, "type", where)
    if typ not in ADAPTER_TYPES:
        raise ConfigError(f"{where}: unknown type '{typ}', allowed: {sorted(ADAPTER_TYPES)}")
    t = _require(raw, "target", where)
    kind = _require(t, "kind", where + ".target")
    if kind not in TARGET_KINDS:
        raise ConfigError(f"{where}: unknown target.kind '{kind}'")
    target = Target(
        table=_require(t, "table", where + ".target"),
        kind=kind,
        geometry_column=t.get("geometry_column", "geom"),
        geometry_type=str(t.get("geometry_type", "MULTIPOLYGON")).upper(),
        required=list(t.get("required", [])),
    )
    key = list(_require(raw, "key", where))
    mapping = dict(_require(raw, "mapping", where))
    constants = dict(raw.get("constants", {}))
    missing = [k for k in key if k not in mapping and k not in constants]
    if missing:
        raise ConfigError(f"{where}: key columns {missing} are neither mapped nor constant")
    return Source(
        name=name,
        type=typ,
        target=target,
        key=key,
        mapping=mapping,
        options=_expand_env(dict(raw.get("options", {}))),
        constants=constants,
        metadata=dict(raw.get("metadata", {})),
        schedule=raw.get("schedule"),
        enabled=bool(raw.get("enabled", True)),
        max_delete_ratio=float(raw.get("max_delete_ratio", 0.5)),
    )


def load(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = [parse_source(s) for s in raw.get("sources", [])]
    names = [s.name for s in sources]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ConfigError(f"duplicate source names: {sorted(dupes)}")
    reports_dir = Path(raw.get("reports_dir", os.getenv("PIPELINE_REPORTS_DIR", "reports")))
    return Config(sources=sources, reports_dir=reports_dir)


def dsn_from_env() -> str:
    """Same variables as the MOSIDI backend, so the service drops into its compose file."""
    if os.getenv("PIPELINE_DSN"):
        return os.environ["PIPELINE_DSN"]
    return (
        f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'brandenburg')} "
        f"user={os.getenv('POSTGRES_USER', 'postgres')} "
        f"password={os.getenv('POSTGRES_PASSWORD', '')}"
    )
