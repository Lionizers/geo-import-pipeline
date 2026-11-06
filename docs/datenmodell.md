# Datenmodell

Stand: 06.11.2026

## Zieltabellen (MOSIDI, unverändert)

| Tabelle | Inhalt | geschrieben von |
|---|---|---|
| `"Kommunale Gebiete Deutschland"` | Gemeindegeometrien, `geom` MULTIPOLYGON EPSG:4326 | Quelle `gemeinden_bb_wfs` (Schlüssel `ags_0`) |
| `dashboard_data_de` | Kennzahlen je Gebiet und Jahr | Quelle `inkar_gemeinden_bb` (Schlüssel `source, indikator, kennziffer, zeitbezug`) |
| `table_metadata` | DCAT-AP-Metadaten je Tabelle | jeder Lauf: `imported`, bei Änderungen `dct_modified` |

Kennzahlen und Geometrien sind über die Gebietskennziffer verbunden (`kennziffer` = `ags_0`), nicht über Fremdschlüssel zwischen Quellen. Ein Kennzahlen-Import ersetzt nur Kennzahlen seiner Quelle; Geometrien bleiben, weil andere Quellen sie mitnutzen.

## Schema `pipeline_meta` (eigen)

| Tabelle | Inhalt |
|---|---|
| `runs` | ein Eintrag je Lauf mit Status und vollständigem Bericht (JSONB) |
| `record_state` | je Quelle und fachlichem Schlüssel der Inhalts-Hash des letzten Imports; Grundlage des Diffs |

Der Hash umfasst alle gemappten Spalten und die Geometrie (WKB). Ein Datensatz gilt als geändert, wenn sich der Hash ändert.

## Schreiben einer Quelle (eine Transaktion)

1. Zeilen mit Schlüssel aus *gelöscht*, *geändert* und *neu* aus der Zieltabelle entfernen. Das letzte räumt auch Altbestände früherer Importe mit gleichem Schlüssel ab, damit nichts doppelt vorkommt.
2. *Neu* und *geändert* einfügen.
3. `record_state` und `table_metadata` aktualisieren.
