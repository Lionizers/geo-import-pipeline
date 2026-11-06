"""Runs against a real PostGIS (docker compose up db). Skipped without PIPELINE_TEST_DSN."""
import os
from pathlib import Path

import psycopg
import pytest

from pipeline import config, core

DSN = os.getenv("PIPELINE_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PIPELINE_TEST_DSN not set")

SCHEMA = (Path(__file__).parents[1] / "db/init/01_mosidi_schema.sql").read_text()


@pytest.fixture()
def db():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS pipeline_meta CASCADE")
        c.execute('DROP TABLE IF EXISTS "Kommunale Gebiete Deutschland", dashboard_data_de, table_metadata')
        c.execute(SCHEMA)
    yield DSN


def _cfg(tmp_path, csv_rows, extra_sources=""):
    data = tmp_path / "data.csv"
    data.write_text("Indikator;Kennziffer;Zeitbezug;Wert\n" + "\n".join(csv_rows) + "\n", encoding="utf-8")
    yml = tmp_path / "sources.yaml"
    yml.write_text(f"""
reports_dir: {tmp_path / 'reports'}
sources:
  - name: kennzahlen
    type: csv
    options: {{path: {data}, numeric_fields: [Wert]}}
    target: {{table: dashboard_data_de, kind: attribute, required: [wert]}}
    key: [source, indikator, kennziffer, zeitbezug]
    mapping: {{indikator: Indikator, kennziffer: Kennziffer, zeitbezug: Zeitbezug, wert: Wert}}
    constants: {{source: test}}
{extra_sources}
""", encoding="utf-8")
    return config.load(yml)


def _count(dsn, where="TRUE"):
    with psycopg.connect(dsn) as c:
        return c.execute(f"SELECT count(*) FROM dashboard_data_de WHERE {where}").fetchone()[0]


def _q(report, name="kennzahlen"):
    return next(q for q in report["quellen"] if q["quelle"] == name)


def test_second_run_without_changes_reports_zero(db, tmp_path):
    cfg = _cfg(tmp_path, ["A;12051000;2023;1,5", "A;12052000;2023;2,5"])
    r1 = core.run(cfg, db)
    assert (_q(r1)["neu"], _q(r1)["geaendert"], _q(r1)["geloescht"]) == (2, 0, 0)
    r2 = core.run(cfg, db)
    assert (_q(r2)["neu"], _q(r2)["geaendert"], _q(r2)["geloescht"], _q(r2)["unveraendert"]) == (0, 0, 0, 2)
    assert _count(db) == 2


def test_changes_and_deletions_are_detected(db, tmp_path):
    core.run(_cfg(tmp_path, ["A;1;2023;1", "A;2;2023;2", "A;3;2023;3"]), db)
    r = core.run(_cfg(tmp_path, ["A;1;2023;1", "A;2;2023;9", "A;4;2023;4"]), db)
    assert (_q(r)["neu"], _q(r)["geaendert"], _q(r)["geloescht"]) == (1, 1, 1)
    assert _count(db, "kennziffer='2' AND wert=9") == 1 and _count(db) == 3


def test_foreign_rows_are_not_touched(db, tmp_path):
    with psycopg.connect(db, autocommit=True) as c:
        c.execute("INSERT INTO dashboard_data_de (indikator, kennziffer, wert, zeitbezug, source) "
                  "VALUES ('A', '1', 42, 2023, 'other source')")
    core.run(_cfg(tmp_path, ["A;1;2023;1"]), db)
    assert _count(db, "source='other source' AND wert=42") == 1


def test_broken_source_does_not_stop_the_others(db, tmp_path):
    broken = """
  - name: kaputt
    type: csv
    options: {url: "http://127.0.0.1:9/nothing.csv", timeout_seconds: 2}
    target: {table: dashboard_data_de, kind: attribute}
    key: [source]
    mapping: {}
    constants: {source: kaputt}
"""
    r = core.run(_cfg(tmp_path, ["A;1;2023;1"], broken), db)
    assert r["status"] == "teilweise_fehler"
    assert _q(r, "kaputt")["status"] == "fehler" and "not reachable" in _q(r, "kaputt")["fehler"]
    assert _q(r)["status"] == "ok" and _count(db) == 1


def test_delete_guard_protects_against_incomplete_fetch(db, tmp_path):
    core.run(_cfg(tmp_path, [f"A;{i};2023;1" for i in range(10)]), db)
    r = core.run(_cfg(tmp_path, ["A;0;2023;1"]), db)
    assert _q(r)["status"] == "fehler" and "would be deleted" in _q(r)["fehler"]
    assert _count(db) == 10
