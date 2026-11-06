import zipfile
import xml.etree.ElementTree as ET

import pytest
from shapely.geometry import Polygon

from pipeline import diff, transform
from pipeline.adapters.base import RawRecord
from pipeline.adapters.csv_adapter import CsvAdapter
from pipeline.adapters.wfs import WfsAdapter, parse_gml_geometry
from pipeline.config import ConfigError, parse_source

GML = """<gml:MultiSurface xmlns:gml="http://www.opengis.net/gml/3.2" srsName="urn:ogc:def:crs:EPSG::25833">
<gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing>
<gml:posList>368000 5820000 369000 5820000 369000 5821000 368000 5821000 368000 5820000</gml:posList>
</gml:LinearRing></gml:exterior></gml:Polygon></gml:surfaceMember></gml:MultiSurface>"""


def test_diff_new_changed_deleted_unchanged():
    d = diff.compute({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "x", "z": "9"})
    assert d.new == ["c"] and d.changed == ["b"] and d.deleted == ["z"] and d.unchanged == 1


def test_record_key_is_safe_for_separators():
    k = diff.record_key({"a": "x|y", "b": None}, ["a", "b"])
    assert diff.key_values(k) == ["x|y", None]


def test_gml_multisurface_and_reprojection_to_4326():
    geom = parse_gml_geometry(ET.fromstring(GML))
    assert geom.geom_type == "MultiPolygon" and geom.area == 1_000_000
    wgs = WfsAdapter({"url": "x", "typename": "t"})._reproject(geom, "urn:ogc:def:crs:EPSG::25833")
    lon, lat = wgs.centroid.x, wgs.centroid.y
    assert 13.0 < lon < 13.2 and 52.5 < lat < 52.6  # near Potsdam, lon/lat order


def _source(**over):
    raw = {"name": "s", "type": "csv", "options": {"path": "x"},
           "target": {"table": "t", "kind": "geometry", "geometry_type": "MULTIPOLYGON", "required": ["name"]},
           "key": ["id"], "mapping": {"id": "ID", "name": "NAME"}}
    raw.update(over)
    return parse_source(raw)


def test_transform_repairs_invalid_geometry_and_skips_incomplete_records():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])  # self-intersecting
    src = _source()
    recs = [RawRecord({"ID": "1", "NAME": "a"}, bowtie), RawRecord({"ID": None, "NAME": "b"}, bowtie),
            RawRecord({"ID": "3", "NAME": ""}, bowtie)]
    res = transform.apply(src, recs, lambda r: diff.record_key(r, src.key))
    assert len(res.rows) == 1 and res.skipped == 2 and res.repaired_geometries == 1
    row = next(iter(res.rows.values()))
    assert row.geometry.is_valid and row.geometry.geom_type == "MultiPolygon"


def test_config_rejects_unmapped_key():
    with pytest.raises(ConfigError):
        _source(key=["missing"])


def test_csv_adapter_streams_zip_filters_and_converts_decimals(tmp_path):
    csv_text = ("Bereich;Raumbezug;Kennziffer;Wert\n"
                "LRB;Gemeinden;12051000;1.234,50\n"
                "LRB;Kreise;12051;7,0\n"
                "LRB;Gemeinden;01001000;3,0\n")
    z = tmp_path / "data.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("inkar_2025.csv", csv_text)
        zf.writestr("Readme.txt", "x")
    a = CsvAdapter({"path": str(z), "zip_member": "inkar_*.csv", "numeric_fields": ["Wert"],
                    "filters": [{"field": "Raumbezug", "equals": "Gemeinden"},
                                {"field": "Kennziffer", "startswith": "12"}]})
    rows = [r.fields for r in a.fetch()]
    assert rows == [{"Bereich": "LRB", "Raumbezug": "Gemeinden", "Kennziffer": "12051000", "Wert": "1234.50"}]


def test_csv_adapter_reports_missing_filter_column(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="filter columns"):
        list(CsvAdapter({"path": str(f), "filters": [{"field": "nope", "equals": "1"}]}).fetch())
