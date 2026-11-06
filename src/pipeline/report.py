"""Writes the import report as JSON (machine) and Markdown (human)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def to_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"# Import-Bericht {r['lauf_id']}",
        "",
        f"- Start: {r['gestartet']} · Ende: {r['beendet']} · Laufzeit: {r['laufzeit_s']} s",
        f"- Status: **{r['status']}**" + (" (Testlauf, nichts geschrieben)" if r.get("testlauf_ohne_schreiben") else ""),
        "",
        "| Quelle | Ziel | Status | neu | geändert | gelöscht | unverändert | übersprungen | Laufzeit |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for q in r["quellen"]:
        if q["status"] == "ok":
            lines.append(f"| {q['quelle']} | {q['ziel']} | ok | {q['neu']} | {q['geaendert']} | "
                         f"{q['geloescht']} | {q['unveraendert']} | {q['uebersprungen']} | {q['laufzeit_s']} s |")
        else:
            lines.append(f"| {q['quelle']} | {q['ziel']} | **Fehler** | – | – | – | – | – | – |")
    errors = [q for q in r["quellen"] if q["status"] != "ok"]
    if errors:
        lines += ["", "## Fehler", ""] + [f"- **{q['quelle']}**: {q['fehler']}" for q in errors]
    warns = [(q["quelle"], w) for q in r["quellen"] for w in q.get("warnungen", [])]
    if warns:
        lines += ["", "## Warnungen", ""] + [f"- {s}: {w}" for s, w in warns[:100]]
        if len(warns) > 100:
            lines.append(f"- … {len(warns) - 100} weitere im JSON-Bericht")
    if r.get("unbekannte_quellen"):
        lines += ["", f"Unbekannte Quellen im Aufruf: {', '.join(r['unbekannte_quellen'])}"]
    return "\n".join(lines) + "\n"


def write(r: dict[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    j = reports_dir / f"{r['lauf_id']}.json"
    m = reports_dir / f"{r['lauf_id']}.md"
    j.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    m.write_text(to_markdown(r), encoding="utf-8")
    (reports_dir / "latest.md").write_text(to_markdown(r), encoding="utf-8")
    return j, m
