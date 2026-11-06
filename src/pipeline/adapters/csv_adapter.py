"""CSV adapter: URL, ZIP or local file; streamed, so multi-GB files (INKAR) work."""
from __future__ import annotations

import csv
import fnmatch
import io
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TextIO

import httpx

from .base import FetchStats, RawRecord


def _matches(row: dict[str, Any], flt: dict[str, Any]) -> bool:
    v = row.get(flt["field"])
    if v is None:
        return False
    if "equals" in flt:
        return v == str(flt["equals"])
    if "in" in flt:
        return v in {str(x) for x in flt["in"]}
    if "startswith" in flt:
        return v.startswith(str(flt["startswith"]))
    raise ValueError(f"unknown filter: {flt}")


class CsvAdapter:
    """Options: url | path, zip_member (glob), encoding, delimiter, decimal,
    numeric_fields, filters [{field, equals|in|startswith}]."""

    def __init__(self, options: dict[str, Any], client: httpx.Client | None = None) -> None:
        self.url = options.get("url")
        self.path = options.get("path")
        if not (self.url or self.path):
            raise ValueError("csv source needs 'url' or 'path'")
        self.zip_member = options.get("zip_member")
        self.encoding = options.get("encoding", "utf-8")
        self.delimiter = options.get("delimiter", ";")
        self.decimal = options.get("decimal", ",")
        self.numeric_fields = set(options.get("numeric_fields", []))
        self.filters = list(options.get("filters", []))
        self.client = client or httpx.Client(timeout=float(options.get("timeout_seconds", 600)),
                                             follow_redirects=True,
                                             headers={"User-Agent": "geo-import-pipeline/0.1"})
        self.stats = FetchStats()

    @contextmanager
    def _local_file(self) -> Iterator[Path]:
        if self.path:
            p = Path(self.path)
            if not p.exists():
                raise FileNotFoundError(f"CSV file not found: {p}")
            yield p
            return
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "download"
            try:
                with self.client.stream("GET", self.url) as r:
                    r.raise_for_status()
                    with target.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
            except httpx.HTTPError as e:
                raise RuntimeError(f"CSV source not reachable ({self.url}): {e}") from e
            yield target

    @contextmanager
    def _text(self, file: Path) -> Iterator[TextIO]:
        if zipfile.is_zipfile(file):
            with zipfile.ZipFile(file) as z:
                pattern = self.zip_member or "*.csv"
                names = [n for n in z.namelist() if fnmatch.fnmatch(n, pattern)]
                if len(names) != 1:
                    raise ValueError(f"expected exactly one ZIP member for '{pattern}', found {names}")
                with z.open(names[0]) as raw:
                    yield io.TextIOWrapper(raw, encoding=self.encoding, newline="")
        else:
            with file.open(encoding=self.encoding, newline="") as f:
                yield f

    def _convert(self, row: dict[str, Any]) -> dict[str, Any]:
        for k in self.numeric_fields:
            v = row.get(k)
            if v in (None, ""):
                row[k] = None
            elif self.decimal != ".":
                row[k] = v.replace(".", "").replace(self.decimal, ".") if self.decimal == "," else v
        return row

    def fetch(self) -> Iterator[RawRecord]:
        with self._local_file() as file, self._text(file) as text:
            reader = csv.DictReader(text, delimiter=self.delimiter)
            missing = [f["field"] for f in self.filters if f["field"] not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"filter columns not in CSV header: {missing}")
            for row in reader:
                if all(_matches(row, f) for f in self.filters):
                    yield RawRecord(fields=self._convert(dict(row)))
