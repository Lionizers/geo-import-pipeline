"""WFS 2.0 / 1.1 adapter: paged GetFeature, GML 3.x parsing, reprojection to EPSG:4326."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any, Iterator

import httpx
from pyproj import CRS, Transformer
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry
import numpy as np
import shapely

from .base import FetchStats, RawRecord

GML_NAMESPACES = {
    "http://www.opengis.net/gml",
    "http://www.opengis.net/gml/3.2",
}
WFS_NAMESPACES = {
    "http://www.opengis.net/wfs",
    "http://www.opengis.net/wfs/2.0",
}


def _ns(tag: str) -> str:
    return tag[1:].split("}")[0] if tag.startswith("{") else ""


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _is_gml(el: ET.Element) -> bool:
    return _ns(el.tag) in GML_NAMESPACES


def _coords(el: ET.Element, dim: int) -> list[tuple[float, ...]]:
    """Reads gml:posList, a sequence of gml:pos or gml:coordinates (GML 2)."""
    for child in el.iter():
        name = _local(child.tag)
        if name == "posList":
            d = int(child.get("srsDimension", dim))
            nums = [float(v) for v in (child.text or "").split()]
            return [tuple(nums[i:i + d][:2]) for i in range(0, len(nums), d)]
        if name == "coordinates":
            pairs = (child.text or "").split()
            return [tuple(float(v) for v in p.split(",")[:2]) for p in pairs]
    return [tuple(float(v) for v in (p.text or "").split()[:2]) for p in el.iter() if _local(p.tag) == "pos"]


def _ring(el: ET.Element, dim: int) -> list[tuple[float, ...]]:
    return _coords(el, dim)


def _polygon(el: ET.Element, dim: int) -> Polygon:
    shell: list = []
    holes: list = []
    for child in el:
        name = _local(child.tag)
        if name in ("exterior", "outerBoundaryIs"):
            shell = _ring(child, dim)
        elif name in ("interior", "innerBoundaryIs"):
            holes.append(_ring(child, dim))
        elif name == "patches":  # gml:Surface with PolygonPatch
            for patch in child:
                return _polygon(patch, dim)
    return Polygon(shell, holes)


def parse_gml_geometry(el: ET.Element, dim: int = 2) -> BaseGeometry:
    name = _local(el.tag)
    if name == "Point":
        return Point(_coords(el, dim)[0])
    if name in ("LineString", "Curve", "LineStringSegment"):
        return LineString(_coords(el, dim))
    if name in ("Polygon", "Surface"):
        return _polygon(el, dim)
    if name in ("MultiSurface", "MultiPolygon"):
        polys = []
        for member in el:
            for g in member:
                if _is_gml(g):
                    geom = parse_gml_geometry(g, dim)
                    polys.extend(geom.geoms if isinstance(geom, MultiPolygon) else [geom])
        return MultiPolygon(polys)
    if name in ("MultiCurve", "MultiLineString"):
        return MultiLineString([parse_gml_geometry(g, dim) for m in el for g in m if _is_gml(g)])
    if name == "MultiPoint":
        return MultiPoint([parse_gml_geometry(g, dim) for m in el for g in m if _is_gml(g)])
    raise ValueError(f"unsupported GML geometry: {name}")


def _srs(el: ET.Element) -> str | None:
    for child in el.iter():
        if child.get("srsName"):
            return child.get("srsName")
    return None


class _Reprojector:
    """Transforms from any source CRS to EPSG:4326 lon/lat; caches transformers."""

    def __init__(self) -> None:
        self._cache: dict[str, Transformer] = {}
        self._target = CRS.from_epsg(4326)

    def __call__(self, geom: BaseGeometry, srs: str) -> BaseGeometry:
        if srs not in self._cache:
            # authority axis order on both sides; EPSG:4326 then returns lat/lon
            self._cache[srs] = Transformer.from_crs(CRS.from_user_input(srs), self._target)
        tr = self._cache[srs]

        def fn(coords: np.ndarray) -> np.ndarray:
            lat, lon = tr.transform(coords[:, 0], coords[:, 1])
            return np.column_stack([lon, lat])

        return shapely.transform(geom, fn)


class WfsAdapter:
    """Options: url, typename, namespaces, version, page_size, pause_seconds,
    source_srs (fallback if the response carries none), max_features (demo)."""

    def __init__(self, options: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.url = options["url"]
        self.typename = options["typename"]
        self.namespaces: dict[str, str] = options.get("namespaces", {})
        self.version = str(options.get("version", "2.0.0"))
        self.page_size = int(options.get("page_size", 100))
        self.pause = float(options.get("pause_seconds", 0.5))
        self.source_srs = options.get("source_srs")
        self.max_features = options.get("max_features")
        self.timeout = float(options.get("timeout_seconds", 120))
        self.client = client or httpx.Client(timeout=self.timeout, follow_redirects=True,
                                             headers={"User-Agent": "geo-import-pipeline/0.1"})
        self.stats = FetchStats()
        self._reproject = _Reprojector()

    def _params(self, start: int) -> dict[str, str]:
        two = self.version.startswith("2")
        p = {
            "SERVICE": "WFS",
            "VERSION": self.version,
            "REQUEST": "GetFeature",
            ("TYPENAMES" if two else "TYPENAME"): self.typename,
            ("COUNT" if two else "MAXFEATURES"): str(self.page_size),
            "STARTINDEX": str(start),
        }
        if self.namespaces:
            ns = ",".join(f"xmlns({k},{v})" for k, v in self.namespaces.items())
            p["NAMESPACES" if two else "NAMESPACE"] = ns
        return p

    def _get(self, start: int) -> bytes:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.get(self.url, params=self._params(start))
                r.raise_for_status()
                if b"ExceptionReport" in r.content[:2000]:
                    raise RuntimeError(f"WFS exception: {r.text[:500]}")
                return r.content
            except (httpx.HTTPError, RuntimeError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"WFS not reachable ({self.url}): {last}")

    def _features(self, xml: bytes) -> list[ET.Element]:
        root = ET.fromstring(xml)
        feats: list[ET.Element] = []
        for member in root:
            if _local(member.tag) in ("member", "featureMember", "featureMembers"):
                feats.extend(list(member))
        return feats

    def _record(self, feat: ET.Element) -> RawRecord:
        fields: dict[str, Any] = {"gml_id": feat.get("{http://www.opengis.net/gml/3.2}id")
                                  or feat.get("{http://www.opengis.net/gml}id")}
        geom: BaseGeometry | None = None
        for prop in feat:
            name = _local(prop.tag)
            if name == "boundedBy":
                continue
            gml_children = [c for c in prop if _is_gml(c)]
            if gml_children:
                g = gml_children[0]
                srs = _srs(g) or self.source_srs
                if not srs:
                    raise ValueError("geometry without srsName and no source_srs configured")
                geom = self._reproject(parse_gml_geometry(g), srs)
            else:
                fields[name] = (prop.text or "").strip() or None
        return RawRecord(fields=fields, geometry=geom)

    def fetch(self) -> Iterator[RawRecord]:
        start = 0
        while True:
            feats = self._features(self._get(start))
            self.stats.pages += 1
            for f in feats:
                yield self._record(f)
                start += 1
                if self.max_features and start >= int(self.max_features):
                    return
            if len(feats) < self.page_size:
                return
            time.sleep(self.pause)  # moderate load on the provider (no parallel requests)
