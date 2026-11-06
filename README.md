# geo-import-pipeline

Automatisierter Import von Geodaten und Kennzahlen aus **WFS-Diensten und CSV-Dateien** in **PostgreSQL/PostGIS**, gebaut für das Datenmodell der Plattform [MOSIDI](https://github.com/MOSIDI-ORG/MOSIDI).

Die Pipeline holt jede Quelle ab, prüft und transformiert die Daten, vergleicht sie über einen fachlichen Schlüssel mit dem letzten Stand und schreibt nur die Änderungen. Nach jedem Lauf liegt ein Import-Bericht vor: was neu ist, was sich geändert hat, was entfernt wurde und welche Quelle nicht erreichbar war.

> Stand: 06.11.2026 · Demonstrator von [Lionizers](https://lionizers.com) · Lizenz Apache-2.0

## Was der Demonstrator zeigt

| Quelle | Typ | Ziel in MOSIDI |
|---|---|---|
| Gemeinden Brandenburg, WFS der LGB (`isk.geobasis-bb.de/ows/vg_wfs`, Feature-Typ `app:gem`) | WFS 2.0, GML 3.2, EPSG:25833 | `"Kommunale Gebiete Deutschland"` (Geometrie, EPSG:4326) |
| INKAR-Indikatoren des BBSR auf Gemeindeebene, Brandenburg | CSV (Stichprobe; produktiv der ZIP-Jahresstand) | `dashboard_data_de` (Kennzahlen) |

Alle Zieltabellen sind ein unveränderter Auszug aus dem MOSIDI-Schema (`db/init/01_mosidi_schema.sql`). Die Pipeline ändert keine Tabellenstruktur. Für Laufsteuerung und Änderungsprotokoll nutzt sie ein eigenes Schema `pipeline_meta` in derselben Datenbank.

## Schnellstart

Voraussetzung: Docker.

```bash
docker compose up -d db                 # PostGIS mit dem MOSIDI-Tabellenauszug
docker compose run --rm pipeline run    # ein Lauf über alle Quellen
docker compose run --rm pipeline run    # zweiter Lauf: 0 neu / 0 geändert / 0 gelöscht
cat reports/latest.md                   # Import-Bericht
```

Einzelne Quelle, oder nur prüfen ohne zu schreiben:

```bash
docker compose run --rm pipeline run --source gemeinden_bb_wfs
docker compose run --rm pipeline run --dry-run
```

Dauerbetrieb mit Zeitplan je Quelle (Cron-Ausdruck in der Konfiguration):

```bash
docker compose run -d pipeline schedule
```

## Ablauf eines Laufs

```
config/sources.yaml ─► je Quelle:  abrufen ─► prüfen/transformieren ─► Diff ─► schreiben ─► Bericht
                                  (Adapter)   (Mapping, Reprojektion,   (fachl.    (eine        (JSON + MD,
                                               Geometrie reparieren)    Schlüssel)  Transaktion) pipeline_meta.runs)
                     Fehler einer Quelle ─► im Bericht vermerkt, die nächste Quelle läuft weiter
```

- **Ein Adapter je Quelltyp** (`src/pipeline/adapters/`): WFS (1.1/2.0, GML 2/3, Paginierung, moderate Abrufe) und CSV (URL, ZIP oder Datei, gestreamt, auch mehrere GB).
- **Reprojektion** aller Geometrien nach EPSG:4326, ungültige Geometrien werden repariert (`make_valid`) und im Bericht gezählt.
- **Diff vor dem Schreiben:** Schlüssel neu = *neu*, Schlüssel vorhanden mit anderem Inhalt = *geändert*, Schlüssel fehlt im neuen, vollständigen Abruf = *gelöscht*.
- **Eine Transaktion je Quelle:** bricht etwas ab, bleibt der alte Stand vollständig erhalten.
- **Schutz vor Teilabrufen:** würde ein Lauf mehr als die Hälfte der Datensätze einer Quelle löschen (`max_delete_ratio`), bricht die Quelle ab und lässt den Bestand unverändert.
- **Nur eigene Zeilen:** der Schlüssel enthält die Quelle; Zeilen anderer Importe bleiben unberührt.
- **Metadaten:** der DCAT-Eintrag der Zieltabelle in `table_metadata` wird nach jedem Lauf aktualisiert (`imported`, `dct_modified` bei Änderungen).

## Konfiguration

Eine Quelle ist ein Eintrag in `config/sources.yaml`:

```yaml
- name: gemeinden_bb_wfs
  type: wfs                       # oder csv
  schedule: "0 3 1 * *"           # monatlich
  options: { url: ..., typename: app:gem, page_size: 100 }
  target: { table: Kommunale Gebiete Deutschland, kind: geometry, geometry_type: MULTIPOLYGON }
  key: [ags_0]                    # fachlicher Schlüssel (Zielspalten)
  mapping: { ags_0: ags, name: gem_name, ... }   # Zielspalte: Quellfeld
  constants: { sn_l: "12" }
```

Zugangsdaten stehen nie in der Datei: `${VAR}` wird aus der Umgebung gelesen. Die Datenbankverbindung nutzt dieselben Variablen wie das MOSIDI-Backend (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`).

**Neue Quelle anbinden:** siehe [docs/neue-quelle.md](docs/neue-quelle.md). Für eine weitere WFS- oder CSV-Quelle reicht ein Konfigurationseintrag.

## Import-Bericht

Jeder Lauf schreibt `reports/<lauf-id>.json`, `reports/<lauf-id>.md` und `reports/latest.md` und speichert den Bericht in `pipeline_meta.runs`. Inhalt: Zeitstempel, Quellen, nicht erreichbare Quellen mit Ursache, neu/geändert/gelöscht/unverändert je Quelle, übersprungene Datensätze, Laufzeit, Warnungen.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest                                   # Unit-Tests
docker compose up -d db
PIPELINE_TEST_DSN="host=127.0.0.1 port=55432 dbname=brandenburg user=postgres password=postgres" .venv/bin/pytest
```

Die Integrationstests laufen gegen eine echte PostGIS-Instanz und prüfen unter anderem: zweiter Lauf ohne Änderung meldet null Änderungen; Änderungen und Löschungen werden erkannt; Zeilen anderer Quellen bleiben unberührt; eine ausgefallene Quelle stoppt die anderen nicht und rollt deren Schreibvorgänge nicht zurück; ein unvollständiger Abruf löscht nichts.

## Dokumentation

- [docs/neue-quelle.md](docs/neue-quelle.md): neue Quelle anbinden
- [docs/datenmodell.md](docs/datenmodell.md): Zieltabellen, Schlüssel, `pipeline_meta`
- [docs/lizenzen.md](docs/lizenzen.md): verwendete Komponenten und Datenlizenzen

## Datenquellen und Lizenzen der Daten

- Verwaltungsgrenzen: © GeoBasis-DE/LGB, Datenlizenz Deutschland – Namensnennung – Version 2.0
- INKAR: © BBSR Bonn, Datenlizenz Deutschland – Namensnennung – Version 2.0. `samples/` enthält einen Auszug aus INKAR 2025 (Brandenburg, Gemeinden, fünf Indikatoren, 2021–2023).
