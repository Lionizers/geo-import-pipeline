"""One pipeline run: per source fetch -> transform -> diff -> write; errors stay per source."""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import adapters, diff, transform, writer
from .config import Config, Source

log = logging.getLogger("pipeline")


class DeleteGuardError(RuntimeError):
    pass


def _run_source(conn: psycopg.Connection, source: Source, dry_run: bool) -> dict[str, Any]:
    t0 = time.monotonic()
    adapter = adapters.build(source.type, source.options)
    key_of = lambda row: diff.record_key(row, source.key)  # noqa: E731
    result = transform.apply(source, adapter.fetch(), key_of)
    hashes = {k: diff.record_hash(r.values, r.geometry.wkb if r.geometry is not None else None)
              for k, r in result.rows.items()}
    existing = writer.load_state(conn, source.name)
    d = diff.compute(hashes, existing)
    # an incomplete fetch must never wipe the table: deletions above the limit stop the source
    if existing and len(d.deleted) > source.max_delete_ratio * len(existing):
        raise DeleteGuardError(
            f"{len(d.deleted)} of {len(existing)} records would be deleted "
            f"(limit {source.max_delete_ratio:.0%}); source left unchanged")
    if not dry_run:
        writer.apply(conn, source, result.rows, hashes, d)
    return {
        "quelle": source.name,
        "typ": source.type,
        "ziel": source.target.table,
        "status": "ok",
        "datensaetze": len(result.rows),
        **d.counts(),
        "uebersprungen": result.skipped,
        "seiten": adapter.stats.pages,
        "laufzeit_s": round(time.monotonic() - t0, 2),
        "warnungen": result.warnings + adapter.stats.warnings,
    }


def run(cfg: Config, dsn: str, only: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    selected = [s for s in cfg.sources if s.enabled and (not only or s.name in only)]
    unknown = sorted(set(only or []) - {s.name for s in cfg.sources})
    results: list[dict[str, Any]] = []
    # autocommit: each source commits its own transaction (writer.apply); a later
    # failing source can therefore never roll back an earlier, successful one
    with psycopg.connect(dsn, autocommit=True) as conn:
        writer.ensure_meta_schema(conn)
        for source in selected:
            log.info("source %s: start", source.name)
            try:
                res = _run_source(conn, source, dry_run)
                log.info("source %s: %s", source.name,
                         {k: res[k] for k in ("neu", "geaendert", "geloescht", "unveraendert")})
            except Exception as e:  # one broken source must not stop the others
                log.error("source %s failed: %s", source.name, e)
                res = {"quelle": source.name, "typ": source.type, "ziel": source.target.table,
                       "status": "fehler", "fehler": f"{type(e).__name__}: {e}",
                       "detail": traceback.format_exc(limit=3)}
            results.append(res)
        status = "ok" if all(r["status"] == "ok" for r in results) else "teilweise_fehler"
        report = {
            "lauf_id": run_id,
            "gestartet": started.isoformat(timespec="seconds"),
            "beendet": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "laufzeit_s": round(time.monotonic() - t0, 2),
            "status": status,
            "testlauf_ohne_schreiben": dry_run,
            "quellen": results,
            "unbekannte_quellen": unknown,
        }
        if not dry_run:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pipeline_meta.runs (run_id, started_at, finished_at, status, report) "
                    "VALUES (%s, %s, now(), %s, %s)",
                    (run_id, started, status, Jsonb(report)))
            conn.commit()
    return report
