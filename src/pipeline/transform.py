"""Maps raw source records onto target rows and validates them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from shapely import make_valid
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry

from .adapters.base import RawRecord
from .config import Source

_MULTI = {"POLYGON": MultiPolygon, "LINESTRING": MultiLineString, "POINT": MultiPoint}


@dataclass
class TargetRow:
    values: dict[str, Any]
    geometry: BaseGeometry | None = None


@dataclass
class TransformResult:
    rows: dict[str, TargetRow] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0
    repaired_geometries: int = 0


def _fit_geometry(geom: BaseGeometry, geometry_type: str) -> tuple[BaseGeometry | None, bool]:
    """Repairs invalid geometries (like ST_MakeValid) and casts to the target type."""
    repaired = False
    if not geom.is_valid:
        geom = make_valid(geom)
        repaired = True
    base = geometry_type.replace("MULTI", "")
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type.upper().replace("MULTI", "") == base]
    flat: list[BaseGeometry] = []
    for p in parts:
        flat.extend(getattr(p, "geoms", [p]))
    if not flat:
        return None, repaired
    if geometry_type.startswith("MULTI"):
        return _MULTI[base](flat), repaired
    return flat[0], repaired


def apply(source: Source, records: Iterable[RawRecord], key_of) -> TransformResult:
    res = TransformResult()
    t = source.target
    for i, rec in enumerate(records, start=1):
        row = {col: rec.fields.get(src) for col, src in source.mapping.items()}
        row.update(source.constants)
        row = {k: (None if v == "" else v) for k, v in row.items()}
        key = key_of(row)
        missing = [c for c in source.key + t.required if row.get(c) is None]
        if missing:
            res.skipped += 1
            if len(res.warnings) < 50:
                res.warnings.append(f"record {i}: missing {missing}, skipped")
            continue
        geom = None
        if t.kind == "geometry":
            if rec.geometry is None:
                res.skipped += 1
                res.warnings.append(f"record {key}: no geometry, skipped")
                continue
            geom, repaired = _fit_geometry(rec.geometry, t.geometry_type)
            if repaired:
                res.repaired_geometries += 1
            if geom is None:
                res.skipped += 1
                res.warnings.append(f"record {key}: geometry not of type {t.geometry_type}, skipped")
                continue
        if key in res.rows:
            res.warnings.append(f"duplicate key {key}: last record wins")
        res.rows[key] = TargetRow(values=row, geometry=geom)
    if res.repaired_geometries:
        res.warnings.append(f"{res.repaired_geometries} invalid geometries repaired (make_valid)")
    return res
