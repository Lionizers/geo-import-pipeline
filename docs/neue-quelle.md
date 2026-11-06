# Neue Quelle anbinden

Stand: 06.11.2026

## Fall 1: weitere WFS- oder CSV-Quelle (kein Code)

1. **Quelle ansehen.** WFS: `GetCapabilities` aufrufen, Feature-Typ und Namensraum notieren, ein `GetFeature` mit `COUNT=2` ansehen. CSV: Kopfzeile, Trennzeichen, Dezimaltrennzeichen, Kodierung.
2. **Eintrag in `config/sources.yaml` anlegen:** `name`, `type`, `options`, `target` (Tabelle, `kind: geometry` oder `attribute`), `key` (fachlicher Schlüssel als Zielspalten), `mapping` (Zielspalte: Quellfeld), optional `constants`, `schedule`, `metadata`.
3. **Prüflauf:** `pipeline run --source <name> --dry-run` zeigt im Bericht, wie viele Datensätze neu wären und welche übersprungen werden. Danach ohne `--dry-run`.

### Optionen WFS

| Option | Bedeutung | Standard |
|---|---|---|
| `url` | Dienst-URL ohne Parameter | – |
| `typename` | Feature-Typ, z. B. `app:gem` | – |
| `namespaces` | Präfix → Namensraum-URI | – |
| `version` | `2.0.0` oder `1.1.0` | `2.0.0` |
| `page_size` | Features je Abruf | 100 |
| `pause_seconds` | Pause zwischen Seiten | 0.5 |
| `source_srs` | Koordinatensystem, falls die Antwort keins nennt | – |
| `max_features` | Obergrenze (Tests) | – |

### Optionen CSV

| Option | Bedeutung | Standard |
|---|---|---|
| `url` oder `path` | Abruf per HTTP(S) oder lokale Datei | – |
| `zip_member` | Dateimuster im ZIP, z. B. `inkar_*.csv` | `*.csv` |
| `encoding`, `delimiter`, `decimal` | Dateiformat | `utf-8`, `;`, `,` |
| `numeric_fields` | Felder mit Dezimalkomma | – |
| `filters` | `{field, equals \| in \| startswith}` | – |

## Fall 2: neues Format (z. B. JSON-API, GeoPackage)

1. Neue Klasse in `src/pipeline/adapters/` mit Methode `fetch()`, die `RawRecord(fields, geometry)` liefert. Geometrien kommen in EPSG:4326.
2. Klasse in `adapters/__init__.py` unter einem Typnamen registrieren.
3. Unit-Test in `tests/` ergänzen.

Diff, Schreiben, Bericht und Zeitplan bleiben unverändert.
