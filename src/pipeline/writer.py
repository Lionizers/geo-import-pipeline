"""Writes one source in one transaction: delete changed/removed keys, insert new/changed rows."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from typing import Any

import psycopg
from psycopg import sql

from .config import Source
from .diff import Diff, key_values
from .transform import TargetRow


def ensure_meta_schema(conn: psycopg.Connection) -> None:
    ddl = resources.files("pipeline").joinpath("meta_schema.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def load_state(conn: psycopg.Connection, source: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT record_key, record_hash FROM pipeline_meta.record_state WHERE source = %s",
                    (source,))
        return dict(cur.fetchall())


def _key_condition(source: Source) -> sql.Composed:
    return sql.SQL(" AND ").join(
        sql.SQL("{}::text IS NOT DISTINCT FROM %s").format(sql.Identifier(c)) for c in source.key)


def apply(conn: psycopg.Connection, source: Source, rows: dict[str, TargetRow],
          hashes: dict[str, str], diff: Diff) -> None:
    t = source.target
    table = sql.Identifier(t.table)
    columns = list(next(iter(rows.values())).values.keys()) if rows else []
    with conn.transaction(), conn.cursor() as cur:
        # 1. remove rows whose key disappeared or changed; also clears rows with a new key
        #    that a former import (outside the pipeline) left behind, so nothing is duplicated
        to_remove = diff.deleted + diff.changed + diff.new
        if to_remove:
            stmt = sql.SQL("DELETE FROM {} WHERE {}").format(table, _key_condition(source))
            cur.executemany(stmt, [key_values(k) for k in to_remove])
        # 2. insert new and changed rows
        to_insert = diff.new + diff.changed
        if to_insert:
            cols = [sql.Identifier(c) for c in columns]
            vals: list[Any] = [sql.Placeholder()] * len(columns)
            if t.kind == "geometry":
                cols.append(sql.Identifier(t.geometry_column))
                vals.append(sql.SQL("ST_SetSRID(ST_GeomFromWKB(%s), 4326)"))
            stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                table, sql.SQL(", ").join(cols), sql.SQL(", ").join(vals))
            params = []
            for k in to_insert:
                r = rows[k]
                p = [r.values.get(c) for c in columns]
                if t.kind == "geometry":
                    p.append(r.geometry.wkb if r.geometry is not None else None)
                params.append(p)
            cur.executemany(stmt, params)
        # 3. remember the new state
        if diff.deleted:
            cur.executemany("DELETE FROM pipeline_meta.record_state WHERE source = %s AND record_key = %s",
                            [(source.name, k) for k in diff.deleted])
        if to_insert:
            cur.executemany(
                """INSERT INTO pipeline_meta.record_state (source, record_key, record_hash, updated_at)
                   VALUES (%s, %s, %s, now())
                   ON CONFLICT (source, record_key)
                   DO UPDATE SET record_hash = EXCLUDED.record_hash, updated_at = now()""",
                [(source.name, k, hashes[k]) for k in to_insert])
        _touch_table_metadata(cur, source, changed=bool(to_insert or diff.deleted))


def _touch_table_metadata(cur: psycopg.Cursor, source: Source, changed: bool) -> None:
    """Keeps the DCAT-AP metadata row of the target table current."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    m = source.metadata
    cur.execute(
        """INSERT INTO table_metadata (table_name, dct_title, dct_description, dct_accessurl, dct_license,
                                       dct_accrualperiodicity, dct_catalog_publisher, dct_issued, dct_modified,
                                       imported, details)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (table_name) DO UPDATE SET
             dct_title = COALESCE(EXCLUDED.dct_title, table_metadata.dct_title),
             dct_description = COALESCE(EXCLUDED.dct_description, table_metadata.dct_description),
             dct_accessurl = COALESCE(EXCLUDED.dct_accessurl, table_metadata.dct_accessurl),
             dct_license = COALESCE(EXCLUDED.dct_license, table_metadata.dct_license),
             dct_accrualperiodicity = COALESCE(EXCLUDED.dct_accrualperiodicity, table_metadata.dct_accrualperiodicity),
             dct_catalog_publisher = COALESCE(EXCLUDED.dct_catalog_publisher, table_metadata.dct_catalog_publisher),
             dct_modified = CASE WHEN %s THEN EXCLUDED.dct_modified ELSE table_metadata.dct_modified END,
             imported = EXCLUDED.imported,
             details = COALESCE(table_metadata.details, '{}'::jsonb) || EXCLUDED.details""",
        (source.target.table, m.get("title"), m.get("description"), m.get("access_url"), m.get("license"),
         m.get("accrual_periodicity"), m.get("publisher"), now, now, now,
         json.dumps({"pipeline_sources": {source.name: now.isoformat()}}), changed))
