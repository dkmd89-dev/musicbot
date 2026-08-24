# MusicBot ARCH-010 – Downloader Utils Migration

## Status

PHASE 3C – METADATA-MODELLE MIGRIERT (2026-08-24). Phase 3D–3H noch offen,
Entscheidungsgate vor Phase 3D erreicht. Siehe Abschnitt 27 „Ergebnisse"
(Phase 1), Abschnitt 35 „Phase 2 — Architekturentscheidung", Abschnitt 36
„Phase 3A/3B — Metadata-Unterprozessoren migriert" und Abschnitt 37
„Phase 3C — Metadata-Modelle migriert".

## Typ

Architektur-Analyse und kontrollierte Migration

## Ziel

ARCH-010 untersucht und migriert die historisch gewachsene Struktur unter:

services/downloader/utils/
services/downloader/utils/metadata/

in eine fachlich und architektonisch klarere Zielstruktur.

Dabei darf die aktuelle Verzeichnisverschachtelung **nicht automatisch als Zielarchitektur übernommen werden**.

Insbesondere ist zu prüfen, ob Komponenten aus:

services/downloader/utils/
services/downloader/utils/metadata/

langfristig in eigenständige Top-Level-Bereiche unter `services/` gehören.

Ziel ist nicht lediglich, das bestehende Verzeichnis "aufzuräumen".

Ziel ist:

> Die Komponenten sollen dort liegen, wo ihre tatsächliche fachliche bzw. architektonische Verantwortung liegt.

Dadurch soll verhindert werden, dass zunächst eine vermeintlich saubere Zwischenstruktur geschaffen wird, die später erneut vollständig verschoben werden muss.

---

# 1. Ausgangslage

Die aktuelle Struktur ist historisch gewachsen:

services/
└── downloader/
    └── utils/
        └── metadata/

Diese Verschachtelung darf nicht automatisch als finale Architektur betrachtet werden.

Der aktuelle POST-ARCH-009-Stand strukturiert `services/` zunehmend nach Verantwortlichkeiten und nicht ausschließlich nach historischer Dateihierarchie.

ARCH-010 setzt diese Richtung fort.

---

# 2. Grundprinzip der Zielarchitektur

## Top-Level Service Boundaries

Top-Level-Verzeichnisse unter `services/` sollen echte fachliche oder architektonische Boundaries repräsentieren.

Grundregel:

> Historische Verzeichnisverschachtelung darf nicht als Architekturgrenze übernommen werden.

Daher ist insbesondere zu prüfen, ob Komponenten aus:

services/downloader/utils/
services/downloader/utils/metadata/

eigentlich eigenständige Verantwortungsbereiche darstellen.

---

# 3. Zielarchitektur-Kandidat

Als langfristige Zielarchitektur soll insbesondere folgende Struktur untersucht werden:

services/
├── downloader/
│   ├── downloader.py
│   ├── spotify_downloader.py
│   ├── playlist_processor.py
│   └── ...
│
├── metadata/
│   ├── metadata_service.py
│   ├── album_processor.py
│   ├── track_processor.py
│   ├── result_translator.py
│   └── ...
│
├── library/
│   ├── organizer.py
│   ├── filename_service.py
│   └── ...
│
├── clients/
│   ├── genius_client.py
│   ├── lastfm_client.py
│   ├── musicbrainz_client.py
│   └── navidrome_api.py
│
├── statistics/
│   ├── play_history_repository.py
│   ├── play_history_poller.py
│   ├── statistics_calculator.py
│   └── chart_renderer.py
│
└── utils/
    └── wirklich allgemeine technische Utilities

Diese Struktur ist ausdrücklich:

> ein Zielarchitektur-Kandidat und keine blind vorgegebene Lösung.

Die endgültige Entscheidung muss anhand der tatsächlichen:

- Verantwortlichkeiten
- Dependencies
- Consumer
- Abhängigkeiten zwischen Komponenten
- fachlichen Boundaries

getroffen werden.

---

# 4. Verantwortungsbereiche

## 4.1 services/downloader/

Verantwortung:

> Musik von externen Quellen beschaffen.

Hier soll ausschließlich Logik verbleiben, die tatsächlich Downloader-spezifisch ist.

Beispiele:

services/downloader/
├── downloader.py
├── spotify_downloader.py
├── playlist_processor.py
└── ...

Mögliche Downloader-spezifische Komponenten sind beispielsweise:

- Download-Orchestrierung
- YouTube-Download
- Spotify-Download
- Playlist-Verarbeitung
- Download-spezifische Verarbeitung
- Download-spezifische Status-/Progress-Logik
- Download-spezifische Hilfsfunktionen

Die konkrete Zuordnung muss jedoch durch die Analyse bestätigt werden.

---

# 5. services/metadata/

Verantwortung:

> Musik-Metadaten ermitteln, anreichern, normalisieren und verarbeiten.

Komponenten, die fachlich unabhängig vom eigentlichen Download sind, sollen ausdrücklich auf eine mögliche Verschiebung nach:

services/metadata/

geprüft werden.

Beispielsweise:

services/downloader/utils/metadata/album_processor.py

könnte langfristig zu:

services/metadata/album_processor.py

werden.

Ebenso:

services/downloader/utils/metadata_result_translator.py

könnte langfristig zu:

services/metadata/result_translator.py

werden.

Diese Positionen sind Beispiele.

Die endgültige Zuordnung muss anhand der tatsächlichen Implementierung und Consumer entschieden werden.

---

# 6. services/library/

Verantwortung:

Bibliotheksbezogene Verarbeitung.

Beispielsweise könnten Komponenten wie:

- Library Organizer
- Filename Service
- Dateinamensverarbeitung
- Bibliotheksstruktur
- Pfad-/Dateiverarbeitung mit Library-Fachbezug

hierhin gehören.

Beispiel:

sanitize_filename()

soll nicht automatisch unter `utils/` landen.

Wenn die Funktion fachlich zur Library-/Dateinamensverarbeitung gehört, ist zu prüfen, ob sie beispielsweise nach:

services/library/filename_service.py

gehört.

---

# 7. services/clients/

Verantwortung:

Technische Adapter für externe Dienste.

Beispiele:

services/clients/
├── genius_client.py
├── lastfm_client.py
├── musicbrainz_client.py
└── navidrome_api.py

Die bestehende Architekturentscheidung aus den vorherigen ARCH-Phasen ist hierbei zu berücksichtigen.

ARCH-010 darf bereits abgeschlossene Entscheidungen nicht stillschweigend verändern.

---

# 8. services/statistics/

Verantwortung:

Statistik- und Play-History-bezogene Komponenten.

Beispielsweise:

services/statistics/
├── play_history_repository.py
├── play_history_poller.py
├── statistics_calculator.py
└── chart_renderer.py

Auch hier gilt:

Die konkrete Zuordnung erfolgt anhand der tatsächlichen Verantwortung und Dependencies.

---

# 9. services/utils/

## Wichtig: kleinste Kategorie

Ein allgemeines:

services/utils/

darf nicht zum neuen Sammelbecken für alle Komponenten werden, deren Position unklar ist.

Die Regel lautet:

> `utils/` ist die kleinste Kategorie.

Nicht:

services/utils/
├── metadata_utils.py
├── downloader_utils.py
├── library_utils.py
└── random_helpers.py

sondern ausschließlich:

services/utils/
└── wirklich querschnittliche technische Hilfsfunktionen

Eine Komponente soll nicht nach `utils/` verschoben werden, nur weil keine unmittelbar passende andere Position gefunden wurde.

---

# 10. Beispiele für die Verantwortungsprüfung

## sanitize_filename()

Nicht automatisch:

services/utils/

Prüfen:

> Ist die Funktion fachlich Bestandteil der Library-/Filename-Verarbeitung?

Wenn ja, ist beispielsweise zu prüfen:

services/library/filename_service.py

---

## MetadataNormalizer

Nicht:

services/utils/

Sondern prüfen:

services/metadata/

---

## DownloadProgressTracker

Prüfen:

services/downloader/

oder gegebenenfalls eine klar definierte Application-Komponente.

Die Entscheidung muss anhand der tatsächlichen Consumer und Verantwortlichkeiten getroffen werden.

---

## NavidromeScanTrigger

Die bestehende Architekturentscheidung ist zu berücksichtigen.

Eine technische Infrastrukturkomponente kann weiterhin unter `utils/` liegen, sofern die bereits dokumentierte Architektur dies begründet.

Nicht jede Komponente muss in einen Top-Level-Servicebereich verschoben werden.

---

# 11. Was ausdrücklich vermieden werden soll

Nicht automatisch diese Struktur erzeugen:

services/
├── downloader/
│   ├── metadata/
│   ├── utils/
│   └── download/

nur weil die Dateien momentan so zusammenliegen.

Ebenso soll nicht entstehen:

services/
└── downloader/
    └── utils/
        └── metadata/
            └── providers/
                └── ...

wenn die enthaltenen Komponenten tatsächlich eigenständige fachliche Boundaries bilden.

Die Verzeichnisstruktur soll die Architektur verständlich machen.

---

# 12. Architekturziel

Wenn jemand das Repository öffnet, soll die Struktur möglichst schnell erkennen lassen:

> Das sind die Hauptbereiche des Systems.

Beispielsweise:

services/
├── downloader
├── metadata
├── library
├── clients
├── statistics
└── utils

Die Top-Level-Struktur soll damit fachliche und architektonische Grenzen sichtbar machen.

---

# 13. Scope

ARCH-010 umfasst zunächst insbesondere:

services/downloader/utils/

und:

services/downloader/utils/metadata/

Zusätzlich müssen jedoch die tatsächlichen Consumer repo-weit analysiert werden.

Die Analyse darf deshalb nicht auf diese beiden Verzeichnisse beschränkt bleiben.

---

# 14. Phase 1 – Analyse

In Phase 1 wird ausschließlich analysiert.

Zu untersuchen sind:

### Dateien

- alle Dateien unter `services/downloader/utils/`
- alle Dateien unter `services/downloader/utils/metadata/`

### Consumer

Repo-weite Consumer sämtlicher betroffener Komponenten.

### Dependencies

Für jede Komponente:

- Imports
- Abhängigkeiten
- verwendete Services
- verwendete Clients
- verwendete Config
- verwendete Utilities
- fachliche Abhängigkeiten

### Verantwortlichkeiten

Für jede Komponente:

> Was ist ihre tatsächliche fachliche Verantwortung?

### Consumer

Für jede Komponente:

> Wer verwendet sie tatsächlich?

### Architektur

Für jede Komponente:

> Welche Top-Level-Boundary passt fachlich am besten?

---

# 15. Phase-1-Regel

Während Phase 1 darf kein Code geändert werden.

Insbesondere:

- keine Dateien verschieben
- keine Dateien umbenennen
- keine Imports ändern
- keine Funktionen ändern
- keine Tests verändern
- keine Architekturentscheidungen vorwegnehmen

Phase 1 dient ausschließlich der Analyse.

---

# 16. Phase-1-Ergebnis

Für jede relevante Komponente soll eine Analyse erstellt werden.

Beispiel:

| Komponente | aktuelle Position | Verantwortung | Consumer | Dependencies | möglicher Zielbereich | Begründung | Risiko |
|---|---|---|---|---|---|---|---|

Dabei muss klar zwischen:

- tatsächlicher Feststellung
- Architekturvorschlag
- offener Frage

unterschieden werden.

---

# 17. Phase 2 – Architekturentscheidung

Erst nach Abschluss der Analyse wird entschieden, welche Komponenten tatsächlich wohin gehören.

Mögliche Zielpositionen sind beispielsweise:

services/downloader/
services/metadata/
services/library/
services/clients/
services/statistics/
services/utils/

Diese Struktur ist weiterhin ein Kandidat und keine automatische Vorgabe.

Die Entscheidung muss sich auf:

- Verantwortlichkeiten
- Dependencies
- Consumer
- fachliche Boundaries
- bestehende Architekturentscheidungen

stützen.

---

# 18. Phase-2-Regel

Eine Komponente wird nicht verschoben, nur weil ihr aktueller Pfad "unschön" ist.

Es muss eine fachliche oder architektonische Begründung geben.

Beispiel:

services/downloader/utils/metadata/

→ services/metadata/

nur wenn die Analyse zeigt:

> Die Komponente verarbeitet Metadata unabhängig vom Downloader und bildet damit einen eigenständigen fachlichen Bereich.

---

# 19. Phase 3 – Migration

Die Migration erfolgt erst nach Abschluss und Prüfung der Architekturentscheidung.

Nicht:

> Analyse und Migration gleichzeitig.

Sondern:

Analyse

↓

Architekturentscheidung

↓

Migration

↓

Audit

---

# 20. Migrationsprinzip

Die Migration erfolgt schrittweise.

Für jede Komponente:

1. Zielposition bestimmen
2. Consumer erfassen
3. Tests erfassen
4. Datei verschieben
5. Imports anpassen
6. Tests anpassen
7. relevante Regressionstests ausführen
8. Consumer erneut prüfen
9. Legacy-Referenzen prüfen

Keine unnötige Big-Bang-Migration.

---

# 21. Keine automatische Zwischenarchitektur

Es soll nicht zunächst dauerhaft eine Struktur wie:

services/downloader/
└── utils/
    └── metadata/

"aufgeräumt" werden, wenn bereits absehbar ist, dass die Komponenten fachlich nach:

services/metadata/

gehören könnten.

ARCH-010 soll gerade verhindern, dass eine solche Zwischenarchitektur geschaffen wird.

---

# 22. Dokumentationsregel

`docs/` bildet zunehmend eine nachvollziehbare Architekturhistorie.

ARCH-010 darf deshalb keine bereits abgeschlossenen Architekturentscheidungen überschreiben oder rückwirkend umdeuten.

Wenn während ARCH-010 festgestellt wird, dass eine bestehende Architekturentscheidung tatsächlich revidiert werden müsste, muss dies ausdrücklich als:

> ARCHITECTURE DECISION CHANGE

dokumentiert und begründet werden.

Historische Entscheidungen bleiben nachvollziehbar.

---

# 23. Architekturhistorie

ARCH-010 ist als Fortsetzung der bisherigen Architekturarbeit einzuordnen.

Insbesondere sind die vorhandenen:

- ARCH-Dokumente
- POST-ARCH-009
- bereits abgeschlossenen Architekturentscheidungen

vor Beginn der Analyse zu lesen und zu berücksichtigen.

Die historische Entwicklung darf nicht verloren gehen.

Ziel ist:

ARCH-009
Navidrome Migration
       ↓
POST-ARCH-009
Audit
       ↓
ARCH-010
Downloader Utils
       ↓
Analyse
       ↓
Architekturentscheidung
       ↓
Migration
       ↓
Audit

---

# 24. Claude-Arbeitsauftrag – Phase 1

Claude soll zunächst alle relevanten Architektur-Dokumente lesen.

Danach:

> Führe ausschließlich PHASE 1 – Analyse durch.

Analysiere dabei:

services/downloader/utils/

und:

services/downloader/utils/metadata/

sowie deren tatsächliche Consumer repo-weit.

Ermittle:

- alle betroffenen Dateien
- alle tatsächlichen Consumer
- alle relevanten Imports
- alle Dependencies
- alle fachlichen Verantwortlichkeiten
- mögliche Top-Level-Boundaries
- Risiken
- Migrationseinschätzungen
- offene Fragen

Ändere noch keinen Code.

Stoppe nach Abschluss der Analyse.

---

# 25. Phase-1-Abschluss

Nach Abschluss von Phase 1 muss Claude:

1. die Analyse in dieser ARCH-010-Datei dokumentieren,
2. die tatsächlichen Findings von Annahmen trennen,
3. mögliche Zielpositionen begründen,
4. offene Architekturfragen dokumentieren,
5. noch keine Migration durchführen.

Erst danach erfolgt die gemeinsame Prüfung der Zielstruktur.

---

# 26. Qualitäts-Gates

ARCH-010 darf nicht von Phase zu Phase übergehen, wenn die jeweilige Grundlage fehlt.

## Gate 1 – Analyse

Erforderlich:

- vollständiger Scope
- repo-weite Consumer
- Dependencies
- Verantwortlichkeiten

---

## Gate 2 – Architekturentscheidung

Erforderlich:

- begründete Zielposition
- keine Konflikte mit bestehenden Entscheidungen
- dokumentierte offene Punkte
- klare Boundary-Zuordnung

---

## Gate 3 – Migration

Erforderlich:

- Tests vorhanden bzw. angepasst
- Consumer bekannt
- Migration planbar
- Rollback möglich

---

## Gate 4 – Abschluss

Erforderlich:

- alle Consumer migriert
- Tests grün
- alte Imports geprüft
- alte Struktur geprüft
- keine unbeabsichtigten Legacy-Abhängigkeiten
- Architektur dokumentiert

---

# 27. Ergebnisse

Dieser Abschnitt wird während der Arbeit ausschließlich mit tatsächlich festgestellten Ergebnissen gefüllt.

Nicht:

- ungeprüfte Annahmen
- hypothetische Architektur
- aus anderen Projekten übernommene Strukturen

Sondern ausschließlich:

- tatsächliche Analyseergebnisse
- tatsächliche Migrationsergebnisse
- tatsächliche Tests
- tatsächliche Architekturentscheidungen

## 27.1 Phase 1 – Analyseergebnisse (2026-08-24)

**Methode:** Direkte Repository-Inspektion (Datei-für-Datei-Lektüre,
repo-weite Import-/Consumer-Greps, Verifikation gegen Falsch-Positive).
Vor Beginn gelesen: `CLAUDE.md` (Abschnitt 4 „Schichtgrenzen"),
`docs/MusicBot_POST-ARCH-009_Audit.md`,
`docs/MusicBot_SERVICES_Zielarchitektur_Audit.md` (deckt denselben
Verzeichnisbaum bereits auf Datei-Ebene ab, hier vertieft um
komponentengenaue Consumer-/Dependency-Ketten),
`docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`,
`docs/MusicBot_ENGINEERING_BASELINE.md`,
`docs/MusicBot_ARCH-003_Services_Phase1_Analyse.md`,
`docs/MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md`,
`docs/MusicBot_ARCH-006_P2_Dependency_Graph.md`.

### Scope-Bestandsaufnahme

17 Python-Dateien (ohne `__init__.py`), 6.516 Zeilen:

```text
services/downloader/utils/                      (7 Dateien, 3.040 Zeilen)
├── download_utils.py                (908)
├── download_result_reporter.py      (309)
├── download_artifact_cleanup.py     (168)
├── progress_tracker.py              (146)
├── errors.py                        (99)
├── metadata_result_translator.py    (207)
└── enhanced_metadata_processor.py   (1203)

services/downloader/utils/metadata/              (10 Dateien, 3.476 Zeilen)
├── cover_processor.py               (955)
├── genre_processor.py               (765)
├── auto_learn.py                    (458)
├── title_cleaner.py                 (333)
├── artist_processor.py              (215)
├── tag_writer.py                    (210)
├── cache.py                         (183)
├── album_processor.py               (159)
├── models.py                        (123)
└── lyrics_processor.py              (75)
```

### Komponententabelle

| Komponente | aktuelle Position | Verantwortung (tatsächlich festgestellt) | Consumer (repo-weit, verifiziert) | Dependencies | möglicher Zielbereich | Begründung | Risiko |
|---|---|---|---|---|---|---|---|
| `download_utils.py` (`EnhancedDownloadProcessor`, `enhanced_download_with_retry`) | `services/downloader/utils/` | Orchestriert die YouTube-Download-Pipeline (Retry, Playlist-/Single-Track-Flow); delegiert Metadaten-Verarbeitung vollständig an `metadata_result_translator.py` — enthält selbst keine Metadaten-Feldlogik | `services/downloader/downloader.py` (direkt), `klassen/download_handler.py` (indirekt über `YoutubeDownloader`), 3 Testdateien | `services/downloader/download/*` (Cache/Year/Channel/Executor/Formatters), `services/downloader/playlist_processor.py`, `utils/artist_map.py`, `utils/filenamefixer.py`, `utils/metadata_cache.py`, `utils/singleton.py` | `services/downloader/` | Selbst-dokumentiert als „NUR noch Orchestrierung" der Download-Pipeline (Moduldocstring); 0 Metadaten-Fachlogik im Code selbst | niedrig (Position bereits korrekt für den Vorschlag) |
| `download_result_reporter.py` (`DownloadResultReporter`) | `services/downloader/utils/` | Formatiert Download-Ergebnistexte (Duplikat/Playlist-Summary/Final-Summary) für Telegram — reiner Text, kein Versand | `klassen/download_handler.py`, 1 Testdatei | `handlers.duplicate_handler.DuplicateEntry` (**bekannte Schichtverletzung**, siehe unten) | `services/downloader/` | Fachlich Download-Ergebnis-spezifisch, nicht Metadaten-spezifisch | niedrig für die Positionierung selbst; die `DuplicateEntry`-Abhängigkeit ist ein separater, bereits in `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md` als P-1 empfohlener Punkt — **nicht Teil dieser Migration**, bleibt unverändert bestehen, wohin auch immer die Datei physisch wandert |
| `download_artifact_cleanup.py` | `services/downloader/utils/` | Löscht verwaiste Download-Artefakte in `Config.DOWNLOAD_DIR` (2 Strategien: gezielt im Fehlerpfad, Sweep beim Bot-Start) | `bot.py`, `enhanced_metadata_processor.py`, 1 Testdatei | keine internen (nur `pathlib`, `time`) | `services/downloader/` | Explizit auf `DOWNLOAD_DIR` bezogen (Download-Artefakte), nicht auf die organisierte Library — Moduldocstring grenzt dies bewusst ab | niedrig |
| `progress_tracker.py` (`ProgressTracker`) | `services/downloader/utils/` | Berechnet Fortschritts-Text für langlaufende Aufgaben, sendet selbst nichts (ARCH-007/P-2) | `download_utils.py`, `klassen/download_handler.py`, 1 Testdatei | keine internen | `services/downloader/` | Aktuell ausschließlich vom Download-Pfad konsumiert; generischer Name könnte künftige Wiederverwendung suggerieren, dafür gibt es aber **keinen Beleg im aktuellen Code** | niedrig |
| `errors.py` (`DownloadError` + 6 Subklassen) | `services/downloader/utils/` | Fehler-Taxonomie, selbst-dokumentiert als „für die Download-Pipeline (services/downloader/**)" (Moduldocstring) | `download_utils.py`, 1 Testdatei (alle anderen Treffer für „NetworkError"/„PermissionError" sind verifizierte Falsch-Positive: `musicbrainzngs.NetworkError`, `telegram.error.NetworkError`, Python-Builtin `PermissionError`) | keine internen | `services/downloader/` | Name und Docstring sind bereits eindeutig download-spezifisch | niedrig |
| `metadata_result_translator.py` (`build_playlist_track_result`, `build_single_track_result`, `merge_metadata_result_into_dict`) | `services/downloader/utils/` | „Gemeinsame Integrationsschicht" (Moduldocstring) — übersetzt `MetadataResult` (Metadata-Domäne) in die von `DownloadResult`/Dict-Konsumenten erwartete Form | `download_utils.py`, `klassen/download_handler.py`, 3 Testdateien | `services/downloader/download/models.py::DownloadResult`, `services/downloader/utils/metadata/models.py::MetadataResult` | **offene Frage**, siehe Abschnitt 27.3 | Grenzkomponente zwischen Downloader und Metadata — liest primär Metadata-Typen, schreibt primär Download-Typen | mittel — Verschiebung in eine der beiden Richtungen ändert die Importrichtung zwischen den künftigen Top-Level-Bereichen `downloader/` und `metadata/` |
| `enhanced_metadata_processor.py` (`EnhancedMetadataProcessor`) | `services/downloader/utils/` | Facade/Orchestrator der gesamten Metadaten-Pipeline (Artist/Title/Genre/Lyrics/Cover/Tags/Auto-Learn/Cache); einziger Konsument aller 9 `metadata/`-Unterprozessoren | `download_utils.py`, `klassen/download_handler.py`, **`handlers/menu/rich_menu_handler.py` (direkt instanziiert)**, 3 Testdateien | `services/clients/genius_client.py`, `utils/artist_map.py`, `utils/genre_map.py`, `utils/youtube_parser.py`, `utils/filenamefixer.py`, `utils/metadata_cache.py`, `utils/singleton.py`, alle 9 `metadata/`-Unterprozessoren, `download_artifact_cleanup.py` | `services/metadata/` | Trotz aktueller Lage unter `.../downloader/utils/` fachlich klar die Metadaten-Pipeline selbst, nicht Download-Orchestrierung; wird zudem von einem Handler direkt konsumiert (nicht nur vom Downloader) — Indiz für einen eigenständigen fachlichen Bereich, keinen reinen Downloader-internen Helfer | mittel-hoch (1203 Zeilen, 3 externe Produktions-Consumer + 9 interne Collaborators, viele Tests) |
| `metadata/album_processor.py` (`AlbumProcessor`) | `services/downloader/utils/metadata/` | Album-/Jahr-Auflösung für Tracks | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `services.clients.musicbrainz_client.MusicBrainzClient` (selbst konstruiert, nicht injiziert) | `services/metadata/` | Reine Metadaten-Fachlogik, kein Download-Bezug | niedrig (1 Consumer) |
| `metadata/artist_processor.py` (`ArtistProcessor`) | `services/downloader/utils/metadata/` | Bestimmt Haupt-/Feature-Artist aus Rohdaten | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `metadata/models.py::split_main_and_featuring` | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |
| `metadata/auto_learn.py` (`AutoLearnManager`) | `services/downloader/utils/metadata/` | Auto-Learning für Artist/Genre-Mappings | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `TYPE_CHECKING`-Referenzen auf `utils.artist_map.ArtistNormalizer`/`utils.genre_map.GenreMapper` | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |
| `metadata/cache.py` (`MetadataCacheHandler`) | `services/downloader/utils/metadata/` | Metadaten-Cache-Zugriff (wrapt `utils/metadata_cache.py::MetadataCache`) | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `utils.metadata_cache.MetadataCache`, `metadata/models.py` | `services/metadata/` | Reine Metadaten-Fachlogik; **Namensrisiko** siehe Abschnitt 27.3 | niedrig |
| `metadata/cover_processor.py` (`CoverProcessor`) | `services/downloader/utils/metadata/` | Cover-Art-Fallback-Kette mit Scoring (5 externe Quellen: Cover Art Archive, Fanart.tv Album/Artist, Apple Music, Deezer, Last.fm) | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | eigener `requests.Session`; **dupliziert Last.fm-Zugriffslogik ggü. `services/clients/lastfm_client.py`** (bereits in `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md` als P-2 dokumentiert) | `services/metadata/` | Reine Metadaten-Fachlogik (Cover-Ermittlung ist Teil der Metadaten-Anreicherung); die externe-HTTP-Frage ist ein separater, bereits dokumentierter Punkt, unabhängig vom Verzeichnis-Zielort | niedrig für die Positionierung; die Last.fm-Duplikation bleibt unabhängig davon offen (nicht Teil von ARCH-010) |
| `metadata/genre_processor.py` (`GenreProcessor`) | `services/downloader/utils/metadata/` | Genre-Bestimmung (Fuzzy/Hierarchie/Fallback) | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `TYPE_CHECKING`-Referenz auf `utils.genre_map.GenreMapper` | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |
| `metadata/lyrics_processor.py` (`LyricsProcessor`) | `services/downloader/utils/metadata/` | Lyrics-Abruf über injizierten `genius_client` | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | `services.clients.genius_client.GeniusClient` (injiziert, DI-konsistent) | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |
| `metadata/models.py` (`MetadataResult`, `EnhancedProcessingStats`, `split_main_and_featuring`) | `services/downloader/utils/metadata/` | Zentrale Datenmodelle der Metadaten-Domäne | breiter als alle anderen `metadata/`-Dateien: `enhanced_metadata_processor.py`, `metadata_result_translator.py`, `download_utils.py`, `metadata/artist_processor.py`, `metadata/cache.py`, `services/downloader/download/interfaces.py`, `services/downloader/download/models.py` (Docstring-Referenz), 5 Testdateien | keine internen | `services/metadata/` | `MetadataResult` ist der Namensgeber und das zentrale Ergebnis-Objekt der Metadaten-Domäne; wird bereits jetzt von `services/downloader/download/` konsumiert — eine Verschiebung nach `services/metadata/` würde diese Abhängigkeit lediglich explizit machen (Service→Service, erwartbare Richtung) | mittel (meistkonsumierte Datei im Scope, 7 Produktions-Consumer) |
| `metadata/tag_writer.py` (`TagWriter`) | `services/downloader/utils/metadata/` | Schreibt ID3/MP4-Tags | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | keine internen | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |
| `metadata/title_cleaner.py` (`TitleCleaner`) | `services/downloader/utils/metadata/` | Titel-Normalisierung | ausschließlich `enhanced_metadata_processor.py` (+ 1 Testdatei) | keine internen | `services/metadata/` | Reine Metadaten-Fachlogik | niedrig |

### 27.2 Zusammenfassende Feststellungen

1. **Der Scope zerfällt sauber in zwei Gruppen.** 6 der 7 Top-Level-Dateien
   unter `services/downloader/utils/` (`download_utils.py`,
   `download_result_reporter.py`, `download_artifact_cleanup.py`,
   `progress_tracker.py`, `errors.py`) sind — durch eigene Moduldocstrings
   bereits selbst-dokumentiert — genuine Downloader-Pipeline-Logik. Die
   siebte (`enhanced_metadata_processor.py`) sowie alle 10 Dateien unter
   `metadata/` bilden eine fachlich geschlossene Metadaten-Domäne.
2. **`metadata/` ist bereits heute eine kohärente Einheit**, nur unter dem
   falschen Pfad. 9 von 10 Dateien dort haben genau **einen** Produktions-
   Consumer: `enhanced_metadata_processor.py`. Keine davon wird von
   `download_utils.py` oder einem anderen Downloader-Modul direkt
   konsumiert — der gesamte Zugriff läuft ausschließlich über die Facade.
   Das ist ein starkes strukturelles Indiz dafür, dass diese 10 Dateien
   plus die Facade selbst einen eigenständigen fachlichen Bereich bilden
   (These aus ARCH-010 Abschnitt 5 wird durch die Consumer-Daten bestätigt,
   nicht nur durch die Verzeichnisbenennung).
3. **`enhanced_metadata_processor.py` hat einen Consumer außerhalb des
   Downloads:** `handlers/menu/rich_menu_handler.py` instanziiert die
   Klasse direkt. Das ist ein zusätzliches, unabhängiges Argument dafür,
   dass die Metadaten-Pipeline kein reiner Downloader-interner
   Implementierungsdetail ist, sondern ein eigenständiger Service.
4. **Keine der 17 Dateien passt zu `services/library/`, `services/clients/`
   oder `services/statistics/`.** Die in ARCH-010 Abschnitt 6/10 als
   Beispiel genannte `sanitize_filename()` liegt **nicht** im analysierten
   Scope, sondern in `utils/filenamefixer.py` (Top-Level-`utils/`,
   außerhalb von `services/downloader/utils/`) — sie wird von
   `download_utils.py` und `enhanced_metadata_processor.py` importiert,
   aber nicht dort definiert. Eine Bewertung dieser Funktion wäre ein
   eigener, in Abschnitt 13 des Auftrags nicht eingeschlossener Schritt
   (siehe offene Frage in 27.3).
5. **Zwei bereits bekannte, nicht neu gefundene Punkte bleiben unverändert
   außerhalb des Scopes:** die `DuplicateEntry`-Schichtverletzung in
   `download_result_reporter.py` (`docs/MusicBot_SERVICES_Zielarchitektur_Audit.md`,
   dortiges P-1) und die duplizierte Last.fm-Logik in `cover_processor.py`
   (dortiges P-2). Beide werden hier nur als Kontext mitgeführt, nicht neu
   bewertet — ihre Lösung ist unabhängig vom physischen Verzeichnis, in dem
   die jeweilige Datei künftig liegt.
6. **Keine ARCHITECTURE DECISION CHANGE erforderlich.** Die bestehende
   `services/clients/`-Konvention aus ARCH-009 wird durch diese Analyse
   nicht berührt — keine der 17 Dateien enthält externe API-Kommunikation,
   die eine Neubewertung der Client-Schicht nötig machen würde (die bereits
   bekannte Cover/Last.fm-Duplikation betrifft die Positionierung von
   `cover_processor.py` innerhalb `metadata/`, nicht die Client-Schicht
   selbst).

### 27.3 Offene Fragen (noch keine Entscheidung)

- **`metadata_result_translator.py`:** gehört strukturell an die Grenze
  zwischen `services/downloader/` und `services/metadata/`. Drei Optionen
  wurden identifiziert, aber nicht bewertet/entschieden: (a) verbleibt bei
  `downloader/` (schreibt Download-Result-Form), (b) wandert nach
  `metadata/` (liest primär Metadata-Typen), (c) bleibt als eigenständige
  Integrationsdatei außerhalb beider Bereiche bestehen. Diese Entscheidung
  ist Teil von Phase 2.
- **Namensrisiko `metadata/cache.py`:** Der Name `MetadataCacheHandler`
  (in `services/downloader/utils/metadata/cache.py`) und die davon
  gewrappte `MetadataCache` (in Top-Level-`utils/metadata_cache.py`) sind
  bereits heute zwei unterschiedliche Module mit ähnlichem Namen. Bei einer
  Verschiebung nach `services/metadata/cache.py` bliebe diese Nähe
  bestehen — zu klären, ob das umbenannt werden sollte (außerhalb des
  Scopes von ARCH-010 Abschnitt 13, da `utils/metadata_cache.py` nicht Teil
  des Scopes ist).
- **`utils/filenamefixer.py`/`sanitize_filename()`:** liegt außerhalb des
  ARCH-010-Scopes (Top-Level-`utils/`, nicht `services/downloader/utils/`),
  wird aber vom Zielarchitektur-Kandidaten (Abschnitt 6/10 dieses
  Dokuments) als mögliches `services/library/`-Beispiel genannt. Ob dieser
  Bereich untersucht wird, ist eine separate, hier nicht getroffene
  Entscheidung — `services/library/` hat nach dieser Analyse aktuell noch
  **keinen** Kandidaten aus dem tatsächlich geprüften Scope.
- **DI-Inkonsistenz `album_processor.py`:** konstruiert `MusicBrainzClient()`
  selbst statt sie injiziert zu bekommen (anders als `lyrics_processor.py`s
  injizierter `genius_client`). Keine Blockade für eine Verschiebung, aber
  eine bereits jetzt sichtbare Inkonsistenz innerhalb der Metadaten-Domäne,
  die bei einer künftigen Migration mit betrachtet werden könnte.
- **Migrationsrisiko/-umfang wurde nicht im Detail beziffert** (keine
  vollständige Testdatei-Liste pro Komponente erstellt) — das ist
  ausdrücklich Aufgabe von Phase 2/3 („Consumer erfassen", „Tests
  erfassen" laut Abschnitt 20), nicht von Phase 1.

### 27.4 Vorläufige Boundary-Zuordnung (Zusammenfassung, keine Entscheidung)

```text
services/downloader/  (Vorschlag, 5 Dateien unverändert fachlich passend)
    download_utils.py
    download_result_reporter.py
    download_artifact_cleanup.py
    progress_tracker.py
    errors.py

services/metadata/    (Vorschlag, 11 Dateien)
    enhanced_metadata_processor.py   (Facade)
    album_processor.py
    artist_processor.py
    auto_learn.py
    cache.py
    cover_processor.py
    genre_processor.py
    lyrics_processor.py
    models.py
    tag_writer.py
    title_cleaner.py

offen / Grenzfall
    metadata_result_translator.py    (downloader/ vs. metadata/, siehe 27.3)
```

Dies ist ein **Analyseergebnis mit begründetem Vorschlag**, keine
Architekturentscheidung — Phase 2 (Abschnitt 17) trifft die tatsächliche
Entscheidung unter Einbeziehung von Test-/Migrationsaufwand.

---

# 28. Offene Punkte

Alle während ARCH-010 entdeckten, aber nicht für die aktuelle Migration notwendigen Themen werden hier dokumentiert.

Sie werden nicht automatisch Teil des Scopes.

Beispielsweise:

- weitere mögliche Boundary-Verschiebungen
- spätere Refactorings
- technische Schulden
- mögliche Folge-ARCHs

## 28.1 Aus Phase 1 mitgeführte, nicht neue Punkte (aus früheren Audits)

- `download_result_reporter.py` importiert `DuplicateEntry` aus
  `handlers/duplicate_handler.py` (Service→Handler-Schichtverletzung).
  Bereits als P-1-Kandidat in `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md`
  dokumentiert. Unabhängig von ARCH-010 — bleibt bestehen, unabhängig davon,
  in welchen Top-Level-Bereich die Datei am Ende wandert.
- `metadata/cover_processor.py` dupliziert Last.fm-Zugriffslogik gegenüber
  `services/clients/lastfm_client.py`. Bereits als P-2-Kandidat in
  `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md` dokumentiert. Ebenfalls
  unabhängig von der Verzeichnis-Zielposition.

## 28.2 Neu in Phase 1 identifiziert, außerhalb des ARCH-010-Scopes

- **`services/library/` hat aktuell keinen Kandidaten** aus dem tatsächlich
  analysierten Scope (`services/downloader/utils/` +
  `services/downloader/utils/metadata/`). Das in ARCH-010 Abschnitt 6/10
  genannte Beispiel `sanitize_filename()` liegt in Top-Level-`utils/filenamefixer.py`,
  außerhalb dieses Scopes. Ob `services/library/` als eigener Bereich
  entsteht, hängt von einer separaten, hier nicht durchgeführten Analyse
  von Top-Level-`utils/` ab.
- **`services/statistics/`** ist durch diesen Scope ebenfalls nicht
  berührt — `services/statistik/` (bereits DI-konsistent, siehe
  `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md`) liegt außerhalb von
  `services/downloader/`.
- DI-Inkonsistenz zwischen `metadata/lyrics_processor.py` (injizierter
  `genius_client`) und `metadata/album_processor.py` (selbst konstruierter
  `MusicBrainzClient`) — kein Blocker für Phase 2/3, aber eine
  Beobachtung für eine mögliche spätere Vereinheitlichung.
- Mögliches Namensrisiko zwischen `services/downloader/utils/metadata/cache.py`
  (`MetadataCacheHandler`) und Top-Level-`utils/metadata_cache.py`
  (`MetadataCache`) bei einer künftigen Umbenennung nach
  `services/metadata/cache.py` — siehe Abschnitt 27.3.

---

# 29. Abschlusskriterien

ARCH-010 gilt erst als abgeschlossen, wenn:

- [ ] `services/downloader/utils/` vollständig analysiert wurde
- [ ] `services/downloader/utils/metadata/` vollständig analysiert wurde
- [ ] tatsächliche Consumer repo-weit ermittelt wurden
- [ ] Dependencies analysiert wurden
- [ ] Verantwortlichkeiten bestimmt wurden
- [ ] Ziel-Boundaries entschieden wurden
- [ ] bestehende Architekturentscheidungen berücksichtigt wurden
- [ ] notwendige Architecture Decision Changes dokumentiert wurden
- [ ] Migration durchgeführt wurde
- [ ] relevante Tests angepasst wurden
- [ ] Regressionstests erfolgreich sind
- [ ] alte Importpfade geprüft wurden
- [ ] Legacy-Strukturen geprüft wurden
- [ ] keine unbeabsichtigten Abhängigkeiten zurückbleiben
- [ ] Dokumentation aktualisiert wurde

---

# 30. Zentrale Architekturregel

Die wichtigste Regel von ARCH-010 lautet:

> **Top-Level-Verzeichnisse in `services/` repräsentieren echte fachliche oder architektonische Boundaries.**

Daraus folgt:

> **Historische Verzeichnisverschachtelung darf nicht als Architekturgrenze übernommen werden.**

Und insbesondere:

> **`services/downloader/utils/metadata/` ist keine automatisch gültige Zielarchitektur.**

Jede Komponente muss anhand ihrer tatsächlichen Verantwortung eingeordnet werden.

---

# 31. Zweite zentrale Regel

Ebenso gilt:

> **`services/utils/` darf kein Sammelbecken werden.**

`utils/` ist die kleinste Kategorie und enthält ausschließlich wirklich querschnittliche technische Hilfsfunktionen.

Wenn eine Komponente eine erkennbare fachliche Verantwortung besitzt, soll sie nach Möglichkeit dort liegen, wo diese Verantwortung architektonisch hingehört.

---

# 32. Endziel

Das langfristige Ziel ist eine verständliche, fachlich orientierte Struktur:

services/
├── downloader/
├── metadata/
├── library/
├── clients/
├── statistics/
└── utils/

Dabei gilt:

- `downloader/` → Musik von externen Quellen beschaffen
- `metadata/` → Metadaten ermitteln, anreichern, normalisieren und verarbeiten
- `library/` → Bibliotheksorganisation und bibliotheksbezogene Dateiverarbeitung
- `clients/` → externe technische Dienste
- `statistics/` → Statistik und Play-History
- `utils/` → nur wirklich querschnittliche technische Utilities

Diese Struktur ist das **langfristige Architekturziel**, aber die konkrete Migration wird erst nach der repo-weiten Analyse entschieden.

---

# 33. Verbindliche Reihenfolge

ARCH-010 wird in folgender Reihenfolge durchgeführt:

```text
Phase 1
Analyse
    ↓
Phase 2
Architekturentscheidung
    ↓
Phase 3
Migration
    ↓
Tests
    ↓
Finaler Audit
    ↓
ARCH-010 Abschluss

34. Aktueller Startpunkt

Status: PHASE 1 – ANALYSE ABGESCHLOSSEN (2026-08-24)

Aktueller Schritt: Entscheidungsgate vor PHASE 2 – ARCHITEKTURENTSCHEIDUNG

Ergebnis von Phase 1 (Details: Abschnitt 27):

- 17 Dateien vollständig analysiert (Verantwortung, Consumer, Dependencies)
- Vorläufiger, unentschiedener Vorschlag: 5 Dateien → `services/downloader/`,
  11 Dateien → `services/metadata/`, 1 Datei (`metadata_result_translator.py`)
  als offene Grenzfrage
- keine ARCHITECTURE DECISION CHANGE nötig
- kein Kandidat für `services/library/` oder `services/statistics/` im
  geprüften Scope gefunden
- zwei bereits bekannte, unabhängige Punkte (DuplicateEntry-Import,
  Last.fm-Duplikation) bestätigt, nicht neu bewertet
- kein Code geändert

Der nächste konkrete Arbeitsauftrag (Phase 2, noch nicht begonnen) wäre:
gemeinsame Prüfung der in 27.4 vorgeschlagenen Boundary-Zuordnung, Klärung
der offenen Frage zu `metadata_result_translator.py`, danach erst
Migrationsplanung (Phase 3).

---

# 35. Phase 2 — Architekturentscheidung (2026-08-24)

**Methode:** Repo-weite Re-Verifikation aller Phase-1-Feststellungen
(Dateiliste, Imports, Consumer, Tests, `mock.patch`-Ziele) gegen den
aktuellen Code-Stand. `git log -- services/downloader/utils/` bestätigt:
letzte inhaltliche Änderung war ARCH-003 P-2, lange vor dieser Session —
der Scope ist seit Phase 1 unverändert.

## 35.1 Verifiziertes Phase-1-Ergebnis

Keine Abweichung zu Phase 1 festgestellt. Alle 17 Dateien, Klassen,
Consumer und Dependencies aus Abschnitt 27 sind unverändert gültig. Neu in
Phase 2 hinzugekommen (in Phase 1 nicht erhoben, jetzt nachgeholt):
vollständige Test-Consumer-Liste inkl. `mock.patch`-Ziel-Prüfung (siehe
35.7) und die exakte Tiefenanalyse von `metadata_result_translator.py`
(siehe 35.4).

| Datei | aktuelle Position | Verantwortung | Consumer (Produktion) | wichtige Dependencies | vorgeschlagene Zielposition |
|---|---|---|---|---|---|
| `download_utils.py` | `services/downloader/utils/` | Download-Pipeline-Orchestrierung (Retry/Playlist/Single) | `services/downloader/downloader.py` (direkt), `klassen/download_handler.py` (indirekt via `YoutubeDownloader`) | `services/downloader/download/*`, `playlist_processor.py`, `enhanced_metadata_processor.py` (via Translator), `utils/*` | `services/downloader/download_utils.py` |
| `download_result_reporter.py` | `services/downloader/utils/` | Download-Ergebnistext-Formatierung | `klassen/download_handler.py` | `handlers.duplicate_handler.DuplicateEntry` (bekannt, separat) | `services/downloader/download_result_reporter.py` |
| `download_artifact_cleanup.py` | `services/downloader/utils/` | Cleanup verwaister Download-Artefakte (`Config.DOWNLOAD_DIR`) | `bot.py`, **`enhanced_metadata_processor.py`** (Reverse-Edge, siehe 35.5) | keine internen | `services/downloader/download_artifact_cleanup.py` |
| `progress_tracker.py` | `services/downloader/utils/` | Fortschritts-Text-Berechnung | `download_utils.py`, `klassen/download_handler.py` | keine internen | `services/downloader/progress_tracker.py` |
| `errors.py` | `services/downloader/utils/` | Fehler-Taxonomie Download-Pipeline | `download_utils.py` | keine internen | `services/downloader/errors.py` |
| `metadata_result_translator.py` | `services/downloader/utils/` | Übersetzt `MetadataResult` → `DownloadResult`/Dict für 3 Aufrufstellen | `download_utils.py`, `klassen/download_handler.py` | `download/models.py::DownloadResult`, `metadata/models.py::MetadataResult` | `services/downloader/metadata_result_translator.py` — **entschieden, siehe 35.4** |
| `enhanced_metadata_processor.py` | `services/downloader/utils/` | Metadata-Pipeline-Facade | `download_utils.py`, `klassen/download_handler.py`, `handlers/menu/rich_menu_handler.py` | alle 9 `metadata/`-Prozessoren, `services/clients/genius_client.py`, `download_artifact_cleanup.py` (Reverse-Edge) | `services/metadata/enhanced_metadata_processor.py` |
| `metadata/album_processor.py` | `services/downloader/utils/metadata/` | Album-/Jahr-Auflösung | ausschließlich `enhanced_metadata_processor.py` | `services/clients/musicbrainz_client.py` (selbst konstruiert) | `services/metadata/album_processor.py` |
| `metadata/artist_processor.py` | „ | Haupt-/Feature-Artist-Bestimmung | ausschließlich `enhanced_metadata_processor.py` | `metadata/models.py` | `services/metadata/artist_processor.py` |
| `metadata/auto_learn.py` | „ | Auto-Learning Artist/Genre | ausschließlich `enhanced_metadata_processor.py` | `TYPE_CHECKING` → `utils/artist_map.py`, `utils/genre_map.py` | `services/metadata/auto_learn.py` |
| `metadata/cache.py` | „ | Metadata-Cache-Zugriff | ausschließlich `enhanced_metadata_processor.py` | `utils/metadata_cache.py` (Namensrisiko, siehe 27.3) | `services/metadata/cache.py` |
| `metadata/cover_processor.py` | „ | Cover-Art-Fallback-Kette | ausschließlich `enhanced_metadata_processor.py` | eigener `requests.Session` (Last.fm-Duplikation, bekannt, separat) | `services/metadata/cover_processor.py` |
| `metadata/genre_processor.py` | „ | Genre-Bestimmung | ausschließlich `enhanced_metadata_processor.py` | `TYPE_CHECKING` → `utils/genre_map.py` | `services/metadata/genre_processor.py` |
| `metadata/lyrics_processor.py` | „ | Lyrics-Abruf | ausschließlich `enhanced_metadata_processor.py` | `services/clients/genius_client.py` (injiziert) | `services/metadata/lyrics_processor.py` |
| `metadata/models.py` | „ | zentrale Datenmodelle (`MetadataResult` u. a.) | 7 Produktions-Consumer, u. a. `download/interfaces.py` | keine internen | `services/metadata/models.py` |
| `metadata/tag_writer.py` | „ | ID3/MP4-Tag-Schreiben | ausschließlich `enhanced_metadata_processor.py` | keine internen | `services/metadata/tag_writer.py` |
| `metadata/title_cleaner.py` | „ | Titel-Normalisierung | ausschließlich `enhanced_metadata_processor.py` | keine internen | `services/metadata/title_cleaner.py` |

## 35.2 Downloader-Boundary — finale Bewertung

Für alle 5 ursprünglich vorgeschlagenen Dateien (`download_utils.py`,
`download_result_reporter.py`, `download_artifact_cleanup.py`,
`progress_tracker.py`, `errors.py`) gilt einheitlich:

- **Primäre Verantwortung ist tatsächlich Download** — bestätigt durch
  eigene Moduldocstrings (keine Interpretation nötig, die Dateien
  beschreiben sich selbst so).
- **Verwendung durch Downloader-Code:** bestätigt für alle 5 (direkt oder
  über `download_utils.py`/`klassen/download_handler.py`).
- **Dependency auf Metadata:** nur `download_utils.py`, und zwar
  ausschließlich über die Facade (`enhanced_metadata_processor.py`) und den
  Translator — keine direkte Dependency auf einen einzelnen
  `metadata/`-Unterprozessor. Die anderen 4 haben **keine**
  Metadata-Dependency.
- **Dependency auf Handler/Telegram:** nur `download_result_reporter.py`
  (via `DuplicateEntry`, bekannt, siehe 35.9) — sonst keine.
- **Dependency auf andere Services:** `download_utils.py` auf
  `services/downloader/download/*` und `playlist_processor.py` (beide
  bleiben unverändert in `services/downloader/`).
- **Eigenständig vs. Teil der gemeinsamen Pipeline:** alle 5 sind
  Collaborators derselben Download-Pipeline, keine isolierten
  Fremdkörper.

**Entscheidung:** Alle 5 Dateien bestätigt für `services/downloader/`.
Vorschlag: flache Struktur (`services/downloader/<datei>.py` statt weiterhin
`services/downloader/utils/<datei>.py`) — die `utils/`-Zwischenebene
entfällt, da sie keine eigene fachliche Bedeutung trägt (ARCH-010
Abschnitt 21 „keine automatische Zwischenarchitektur").

## 35.3 Metadata-Boundary — finale Bewertung

Für die 11 vorgeschlagenen Dateien (Facade + 9 Unterprozessoren +
`models.py`):

- **Primäre fachliche Verantwortung:** bei allen 11 eindeutig
  Metadaten-Ermittlung/-Anreicherung/-Normalisierung — keine enthält
  Download-Orchestrierungslogik.
- **Interne Dependencies:** 9 der 10 Unterprozessoren hängen ausschließlich
  von `logger`, `metadata/models.py` und (in 2 Fällen) `TYPE_CHECKING`-
  Referenzen auf `utils/artist_map.py`/`utils/genre_map.py` ab — keine
  Kopplung untereinander außer über die Facade.
- **Externe Dependencies:** `album_processor.py` →
  `services/clients/musicbrainz_client.py`, `lyrics_processor.py` →
  `services/clients/genius_client.py` (injiziert), `cover_processor.py` →
  eigener `requests`-Zugriff (bekannte Last.fm-Duplikation, separat). Das
  ist die erwartete Richtung Metadata → Clients (wie in ARCH-009
  etabliert).
- **Consumer:** 9 von 10 Unterprozessoren haben **exakt einen**
  Produktions-Consumer (`enhanced_metadata_processor.py`). `models.py` ist
  die einzige breiter konsumierte Datei (7 Consumer, siehe 35.1).
- **Beziehung zur Facade:** `enhanced_metadata_processor.py` ist der
  alleinige Orchestrator — kein Unterprozessor wird von außerhalb der
  Facade direkt instanziiert.
- **Beziehung zu Downloader-Komponenten:** keine der 10
  `metadata/`-Dateien hat eine Dependency auf `services/downloader/`.
  Einzige Ausnahme ist die Facade selbst (`download_artifact_cleanup.py`,
  siehe 35.5).

**Entscheidung:** Alle 11 Dateien bestätigt für `services/metadata/`.
`services/metadata/` bildet damit tatsächlich eine kohärente Domain und
kein Sammelbecken — jede Datei hat eine erkennbare, eigenständige
Metadaten-Verantwortung, nicht nur „lag vorher im selben Ordner".

## 35.4 KRITISCHER ENTSCHEIDUNGSPUNKT — `metadata_result_translator.py`

Vollständige Lektüre der Datei (207 Zeilen, 3 Funktionen:
`build_playlist_track_result`, `build_single_track_result`,
`merge_metadata_result_into_dict`, plus `call_process_single_track`).

**Tatsächliche Feststellung:** Die Datei ist keine dünne Pass-Through-
Übersetzung, sondern enthält echte, bewusst erhaltene Feldabbildungs-
Entscheidungen (z. B. `year` kommt im Playlist-Pfad aus `playlist_year`,
nicht aus `metadata_result.year`; `track_number` wird im Single-Pfad nie
gesetzt; zwei am 2026-08-23 bewusst gefixte Inkonsistenzen). Sie wurde in
ARCH-004 P-3 explizit geschaffen, um **drei unabhängig gewachsene
Downloader-seitige** Implementierungen zu vereinheitlichen
(`download_utils.py` ×2, `klassen/download_handler.py` ×1).

**A — Gehört sie zu Metadata?**
Dagegen: Kein einziger `metadata/`-Unterprozessor oder
`enhanced_metadata_processor.py` importiert oder nutzt diese Datei. Ihr
Input (`MetadataResult`) ist zwar ein Metadata-Typ, aber Metadata-Code
selbst braucht die Übersetzung nicht — nur die Downloader-Seite.

**B — Gehört sie zu Downloader?**
Dafür: **Beide** Produktions-Consumer (`download_utils.py`,
`klassen/download_handler.py`) sind Downloader-seitig. Ihr Output-Typ
(`DownloadResult`) ist ein Downloader-Typ. Ihr historischer Zweck (ARCH-004
P-3) war explizit, dreifach duplizierte **Downloader**-Aufrufstellen zu
vereinheitlichen. Eine Platzierung in `services/downloader/` entspricht
exakt dem etablierten Muster „Downloader konsumiert den öffentlichen
Ergebnistyp von Metadata" — dieselbe Richtung wie
`services/downloader/download/interfaces.py`, das bereits heute
`MetadataResult` importiert.

**C — Eigene Boundary-Komponente?**
Geprüft und verworfen: 207 Zeilen, 1 Datei, keine weiteren Geschwister —
ein eigenes Top-Level-Verzeichnis nur für diese eine Datei würde ARCH-010
Abschnitt 9/31 widersprechen (keine neue Kategorie ohne konkreten Bedarf
für mehr als eine Komponente).

**D — Verantwortlichkeit anders schneiden (MetadataResult/DownloadResult
verändern)?**
Ausdrücklich nicht geprüft im Sinne einer Umsetzung — das wäre eine
Verhaltensänderung an zentralen Datenverträgen und explizit außerhalb des
Phase-2-Rahmens („keine Codeänderung"). Als hypothetische Option zur
Kenntnis genommen, aber nicht bewertet, da kein konkreter Treiber dafür
vorliegt.

**Entscheidung: Option B — `metadata_result_translator.py` gehört zu
`services/downloader/`.** Begründung: beide Consumer, der Output-Typ und
der historische Entstehungszweck sind Downloader-seitig; die
Metadata-Domain hat keinerlei Berührungspunkt mit dieser Datei. Die
Platzierung dort erzeugt **keine** neue Metadata→Downloader-Kante (siehe
35.5) — im Gegenteil, sie hält die Downloader→Metadata-Richtung sauber
ein (Downloader liest `MetadataResult`, produziert eigene Typen daraus).

## 35.5 Abhängigkeitsrichtung Downloader ↔ Metadata

Repo-weit ermittelter tatsächlicher Dependency-Graph (nach den unter 35.2
und 35.3 bestätigten Zuordnungen):

```text
services/downloader/  →  services/metadata/
  download_utils.py            → enhanced_metadata_processor.py (Facade)
  metadata_result_translator.py → metadata/models.py (MetadataResult)
  download/interfaces.py        → metadata/models.py (MetadataResult)
```

```text
services/metadata/  →  services/downloader/   (EINZIGE Kante, Gegenrichtung)
  enhanced_metadata_processor.py → download_artifact_cleanup.py
      (cleanup_single_download_artifact(), ARCH-005 Strategie C:
       räumt im Fehlerpfad von process_single_track() die bereits
       heruntergeladene Datei auf — process_single_track() ist der
       eine garantierte Durchlaufpunkt aller drei Pipelines)
```

**Bewertung:** Der Graph ist **überwiegend unidirektional**
(Downloader → Metadata), mit **genau einer** dokumentierten
Gegenrichtungs-Kante. Das ist eine echte bidirektionale Abhängigkeit im
strikten Sinne und wird hier ausdrücklich als solche benannt.

**Diese Kante wird NICHT im Rahmen von ARCH-010 aufgelöst:**

1. Sie ist keine versehentliche Kopplung, sondern eine 2026 bewusst
   getroffene, in `docs/MusicBot_ENGINEERING_BASELINE.md` dokumentierte
   Entscheidung (ARCH-005, Strategie C — genau der eine garantierte
   Durchlaufpunkt für zuverlässigen Cleanup).
2. Eine Auflösung (z. B. Cleanup stattdessen downloader-seitig nach einem
   fehlgeschlagenen `process_single_track()`-Aufruf auslösen) wäre eine
   echte Verhaltens-/Kontrollfluss-Änderung, keine reine Verschiebung —
   ausdrücklich außerhalb der Phase-2-Regel „keine Codeänderung" und ohne
   eigene Nutzerentscheidung nicht zulässig.
3. Es handelt sich nicht um eine ARCHITECTURE DECISION CHANGE im Sinne von
   Abschnitt 22, da keine bestehende Entscheidung revidiert wird — ARCH-005
   bleibt unverändert gültig, es wird nur explizit sichtbar gemacht, dass
   sie eine Cross-Domain-Kante erzeugt.

**Zielrichtung (dokumentiert, mit einer Ausnahme):**

```text
Downloader
    ↓
Metadata
    ↑ (eine dokumentierte Ausnahme: Cleanup-Aufruf, ARCH-005)
```

Diese eine Ausnahme wird in Phase 3 unverändert mitgeführt: nach der
Migration importiert `services/metadata/enhanced_metadata_processor.py`
weiterhin `services/downloader/download_artifact_cleanup.py` — technisch
unvermeidbar, ohne die zugrunde liegende Entscheidung zu ändern.

## 35.6 `enhanced_metadata_processor.py` als Facade/Boundary

- **Wer verwendet sie:** 3 unabhängige Produktions-Consumer aus 3
  verschiedenen Bereichen — `download_utils.py` (Downloader),
  `klassen/download_handler.py` (Orchestrator), `handlers/menu/rich_menu_handler.py`
  (Handler/Presentation). Dass ein Handler die Facade **direkt**
  instanziiert (nicht nur über den Downloader), ist ein eigenständiges,
  starkes Indiz dafür, dass die Metadaten-Pipeline ein eigenständiger
  Service ist, kein Downloader-internes Detail.
- **Welche Metadata-Komponenten hängen daran:** alle 9 Unterprozessoren
  ausschließlich über diese Facade.
- **Downloader-Abhängigkeiten:** genau eine, siehe 35.5
  (`download_artifact_cleanup.py`).
- **Handler-Abhängigkeiten:** keine (wird von einem Handler konsumiert,
  hängt aber selbst nicht von `handlers/` ab — korrekte Richtung).
- **Echte Facade?** Ja — bündelt Config, Genius-Client, alle 9
  Unterprozessoren, eigenes Singleton-Verhalten (`SingletonMixin`) und
  bietet `process_single_track()` als zentralen öffentlichen
  Einstiegspunkt.
- **Öffentliche Eintrittsstelle von `services/metadata/`?** Ja — sie sollte
  diese Rolle in der Zielarchitektur explizit einnehmen. Eine Umbenennung
  (z. B. zu `metadata_service.py`, wie im ARCH-010-Struktur-Beispiel in
  Abschnitt 3 genannt) wird hier **nicht empfohlen und nicht entschieden**
  — der Dateiname trägt keine falsche Aussage, und eine Umbenennung ohne
  konkreten Treiber widerspricht Regel 18/20 aus `CLAUDE.md`. Empfehlung:
  Datei behält ihren Namen, wandert nur das Verzeichnis.

## 35.7 Consumer- und Import-Auswirkungen

**`mock.patch`-Ziel-Prüfung (vollständig, repo-weit):** Es existiert **kein
einziges** `mock.patch("services.downloader.utils...")`-Ziel im gesamten
Testbaum (verifiziert per Grep über alle 19 betroffenen Testdateien). Alle
Tests im Scope konstruieren die Klassen direkt (echter DI-Stil,
konsistent mit dem in `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md`
bestätigten Befund für `services/downloader/`). Das reduziert das
Migrationsrisiko erheblich gegenüber der ARCH-009-Navidrome-Migration
(dort mussten String-Patch-Ziele mitgezogen werden — hier entfällt dieser
Schritt vollständig).

Keine Re-Exports (`__init__.py` in beiden Scope-Verzeichnissen sind leer),
keine dynamischen Imports (`importlib`), keine String-Referenzen in
Config-/YAML-/JSON-Dateien gefunden.

| Consumer | aktuelle Dependency | Ziel-Dependency (Vorschlag) | Migration nötig? | Risiko |
|---|---|---|---|---|
| `bot.py` | `download_artifact_cleanup` | `services.downloader.download_artifact_cleanup` | ja (1 Importzeile) | niedrig |
| `services/downloader/downloader.py` | `download_utils` | `services.downloader.download_utils` | ja (1 Importzeile) | niedrig |
| `services/downloader/download/interfaces.py` | `metadata.models.MetadataResult` | `services.metadata.models.MetadataResult` | ja (1 Importzeile) | niedrig |
| `klassen/download_handler.py` | 4 Module (`enhanced_metadata_processor`, `download_result_reporter`, `progress_tracker`, `metadata_result_translator`) | je 2 nach `services.downloader.*` und `services.metadata.*` aufgeteilt | ja (4 Importzeilen) | **mittel** — höchste Anzahl betroffener Importe in einer einzigen Datei |
| `handlers/menu/rich_menu_handler.py` | `enhanced_metadata_processor` | `services.metadata.enhanced_metadata_processor` | ja (1 Importzeile) | niedrig |
| 19 Testdateien (siehe 35.1/27.1) | diverse, nur Importzeilen, **keine Patch-Ziele** | entsprechend neue Pfade | ja (je 1–2 Importzeilen) | niedrig einzeln, **mittel in Summe** (Volumen/Vollständigkeit) |
| interne Cross-Refs im Scope selbst (z. B. `metadata/artist_processor.py` → `metadata/models.py`, `enhanced_metadata_processor.py` → 9 Unterprozessoren + `download_artifact_cleanup.py`) | relative/absolute Importe innerhalb des Scopes | bleiben strukturell gleich, nur Pfad-Präfix ändert sich | ja (viele Zeilen, aber mechanisch) | niedrig (keine Logikänderung, reines Pfad-Update) |

## 35.8 `services/utils/` ausdrücklich geprüft

Für alle 17 Dateien wurde geprüft, ob eine von ihnen tatsächlich
querschnittlich/fachlich neutral ist. **Ergebnis: keine.** Jede der 17
Dateien hat eine klar erkennbare Downloader- oder Metadata-Verantwortung
(siehe 35.1–35.3). `services/utils/` erhält aus diesem Scope **keinen**
Kandidaten — die ARCH-010-Regel „utils/ ist die kleinste Kategorie" wird
dadurch nicht getestet, aber auch nicht verletzt.

## 35.9 Bereits bekannte, nicht ARCH-010-relevante Themen

| Thema | ARCH-010 relevant? | Begründung |
|---|---|---|
| `download_result_reporter.py` importiert `DuplicateEntry` aus `handlers/duplicate_handler.py` | **nein** | Schichtverletzung Service→Handler, unabhängig vom Zielverzeichnis der Datei; bereits als P-1 in `docs/MusicBot_SERVICES_Zielarchitektur_Audit.md` dokumentiert → bleibt eigener Folgepunkt |
| `metadata/cover_processor.py` dupliziert Last.fm-Zugriff ggü. `services/clients/lastfm_client.py` | **nein** | Externe-Kommunikations-Frage, unabhängig vom Zielverzeichnis; bereits als P-2 dort dokumentiert → bleibt eigener Folgepunkt |
| `utils/filenamefixer.py`/`sanitize_filename()` | **nein** | Liegt außerhalb des ARCH-010-Scopes (Top-Level-`utils/`, nicht `services/downloader/utils/`); `services/library/` bleibt ohne Kandidaten aus dieser Analyse |
| DI-Inkonsistenz `album_processor.py` (selbst konstruierter `MusicBrainzClient`) vs. `lyrics_processor.py` (injizierter `genius_client`) | **nein** | Testbarkeits-/Konsistenz-Detail, keine Boundary-Frage; kann bei der Migration unverändert mitgezogen werden |
| Namensnähe `services/downloader/utils/metadata/cache.py` vs. `utils/metadata_cache.py` | **teilweise** | Wird durch die Verschiebung nach `services/metadata/cache.py` nicht gelöst, aber auch nicht verschärft — bleibt als Beobachtung bestehen, keine Umbenennung entschieden |

Keine Scope-Erweiterung. Alle vier Themen bleiben unabhängige, separat zu
entscheidende Folgepunkte.

## 35.10 Zielarchitektur

```text
services/
├── downloader/
│   ├── downloader.py                  (unverändert)
│   ├── spotify_downloader.py          (unverändert)
│   ├── playlist_processor.py          (unverändert)
│   ├── download/                      (unverändert: cache_manager.py,
│   │                                    channel_router.py, download_executor.py,
│   │                                    formatters.py, interfaces.py, models.py,
│   │                                    year_resolver.py)
│   ├── download_utils.py              (neu hierher, aus utils/)
│   ├── download_result_reporter.py    (neu hierher, aus utils/)
│   ├── download_artifact_cleanup.py   (neu hierher, aus utils/)
│   ├── progress_tracker.py            (neu hierher, aus utils/)
│   ├── errors.py                      (neu hierher, aus utils/)
│   └── metadata_result_translator.py  (neu hierher, aus utils/)
│
├── metadata/                          (neu)
│   ├── enhanced_metadata_processor.py (Facade/öffentliche Eintrittsstelle)
│   ├── album_processor.py
│   ├── artist_processor.py
│   ├── auto_learn.py
│   ├── cache.py
│   ├── cover_processor.py
│   ├── genre_processor.py
│   ├── lyrics_processor.py
│   ├── models.py
│   ├── tag_writer.py
│   └── title_cleaner.py
│
├── clients/                           (unverändert, ARCH-009)
├── statistik/                         (unverändert, ARCH-003 P-6)
└── (kein neuer services/utils/-Kandidat aus diesem Scope)
```

**Begründung je Kriterium:**

- **Fachliche Verantwortlichkeit:** beide neuen/bestätigten Bereiche sind
  durch Consumer-Daten belegt, nicht nur durch Verzeichnisnähe (35.2/35.3).
- **Dependency-Richtung:** überwiegend unidirektional Downloader→Metadata,
  eine dokumentierte, bewusst nicht aufgelöste Ausnahme (35.5).
- **Wartbarkeit:** `services/metadata/` wird zu einem in sich
  geschlossenen, von außen nur über die Facade angesprochenen Bereich —
  genau das in ARCH-010 Abschnitt 12 beschriebene Ziel („Hauptbereiche auf
  einen Blick erkennbar").
- **Testbarkeit:** keine Patch-Ziel-Migration nötig (35.7) — reduziert das
  technische Risiko gegenüber früheren Migrationen in dieser Session
  erheblich.
- **Erweiterbarkeit:** neue Metadata-Unterprozessoren hätten künftig einen
  klaren Ort, ohne implizit als „Downloader-Utility" zu gelten.
- **Konsistenz mit ARCH-009:** folgt demselben Muster (fachliche Trennung
  vor Verzeichnisbequemlichkeit, kein Big-Bang, Entscheidung vor
  Umsetzung).
- **Konsistenz mit `CLAUDE.md`:** ergänzt die dort in Abschnitt 4
  verankerten Schichtgrenzen um eine feinere Unterteilung innerhalb von
  `services/`, ohne die Grundregeln (`services/clients/`, `handlers/`,
  `utils/`) zu verändern.
- **Konsistenz mit bestehenden `services/`-Boundaries:** `services/clients/`
  und `services/statistik/` bleiben unangetastet — die Struktur fügt sich
  als weitere Geschwister-Domain ein, keine Kollision.

## 35.11 Variantenvergleich

| Variante | Architektur | Komplexität | Dependency-Risiko | Testaufwand | Zukunftssicherheit | Empfehlung |
|---|---|---|---|---|---|---|
| **A** — 5→downloader/, 11→metadata/, Translator→downloader/ | sauber, Translator folgt seinen tatsächlichen Consumern | mittel (2 Zielverzeichnisse, 1 Grenzfall entschieden) | niedrig (Downloader→Metadata dominant, 1 dokumentierte Ausnahme bleibt unverändert bestehen) | mittel (19 Testdateien, aber nur Importzeilen, 0 Patch-Ziele) | hoch — Translator liegt bei seinen echten Konsumenten, keine künstliche Trennung | **empfohlen** |
| B — 5→downloader/, 11→metadata/, Translator→metadata/ | Translator würde in einem Bereich liegen, den keiner seiner Consumer bewohnt | mittel | **höher** — `services/downloader/` müsste dann für jeden Translator-Aufruf nach `services/metadata/` importieren, obwohl der Translator selbst reine Downloader-Ergebnistypen produziert; erzeugt eine zusätzliche, unnötige Downloader→Metadata-Kante ohne fachlichen Gewinn | gleich wie A | niedriger — Platzierung folgt der Eingabedaten, nicht den tatsächlichen Verantwortlichkeiten/Consumern | nicht empfohlen |
| C — Translator als eigene Boundary-Komponente (z. B. `services/integration/`) | neue dritte Top-Level-Kategorie für 1 Datei | höher (neues Verzeichnis, neue Konvention) | neutral | gleich wie A | niedriger — verstößt gegen ARCH-010 Abschnitt 9/31 (keine neue Kategorie ohne mehrere Bewohner) | nicht empfohlen |
| D — abweichende Gesamtstruktur | durch die Analyse nicht begründet — die 5/11-Aufteilung ist bereits durch Consumer-Daten vollständig gedeckt, kein Hinweis auf eine bessere Alternative gefunden | — | — | — | — | nicht erforderlich |

**Empfehlung: Variante A.**

## 35.12 Migrationsreihenfolge (Planung für Phase 3, keine Umsetzung)

Abgeleitet aus dem Dependency-Graph (35.5): Die 9 einzelconsumer-Unterprozessoren
sind am risikoärmsten (nur von der Facade abhängig), die Facade selbst am
consumer-reichsten — daher zuerst die Blätter, dann die Facade zusammen mit
ihrer einen Downloader-seitigen Gegenkante, danach die übrigen
Downloader-Dateien, danach die Konsumenten, zuletzt Tests und Aufräumen.

```text
Phase 3A — Zielverzeichnisse vorbereiten
    services/metadata/ anlegen (leeres Paket)
    services/downloader/utils/ bleibt bis 3G als Übergang bestehen

Phase 3B — Metadata-Unterprozessoren migrieren (9 Dateien, risikoarm)
    album_processor.py, artist_processor.py, auto_learn.py, cache.py,
    cover_processor.py, genre_processor.py, lyrics_processor.py,
    tag_writer.py, title_cleaner.py
    → services/metadata/, jeweils mit ihrer 1 Testdatei im selben Schritt

Phase 3C — models.py migrieren (meistkonsumierte Datei im Scope)
    → services/metadata/models.py, ALLE 7 Produktions-Consumer +
    5 Testdateien in demselben Commit aktualisieren (atomar, keine
    Zwischenphase mit doppeltem Pfad)

Phase 3D — Facade + Downloader-Gegenkante gemeinsam migrieren
    enhanced_metadata_processor.py → services/metadata/
    download_artifact_cleanup.py → services/downloader/
    (im selben Commit, wegen der dokumentierten Reverse-Edge aus 35.5 —
    sonst zwischenzeitlich kaputter Import)

Phase 3E — übrige Downloader-Dateien migrieren
    download_utils.py, download_result_reporter.py, progress_tracker.py,
    errors.py, metadata_result_translator.py → services/downloader/

Phase 3F — externe Consumer migrieren
    bot.py, services/downloader/downloader.py,
    services/downloader/download/interfaces.py,
    klassen/download_handler.py, handlers/menu/rich_menu_handler.py

Phase 3G — alte Struktur entfernen
    services/downloader/utils/ (inkl. metadata/-Unterverzeichnis und
    beider leerer __init__.py) vollständig entfernen; Repo-weiter Grep auf
    0 verbleibende Referenzen bestätigen (Muster aus ARCH-009 Folgeumsetzung)

Phase 3H — vollständiger Regressionstest + Import-Smoke-Test
    pytest tests/ -q gegen bekannten Vorbestand vergleichen;
    python3 -c "import services.metadata...; import services.downloader...."
```

## 35.13 Migrationsrisiko je Block

| Block | Risiko | Begründung |
|---|---|---|
| 3B (9 Unterprozessoren) | **niedrig** | je 1 Produktions-Consumer, je 1 Testdatei, 0 Patch-Ziele |
| 3C (`models.py`) | **mittel** | meistkonsumierte Datei (7 Produktions- + 5 Testdateien), muss atomar mit allen Konsumenten zusammen migriert werden |
| 3D (Facade + Reverse-Edge) | **mittel-hoch** | 1203 Zeilen, 3 externe Produktions-Consumer, 1 Cross-Domain-Kante, 3 Testdateien — größter Einzelblock |
| 3E (übrige Downloader-Dateien) | **niedrig-mittel** | überwiegend wenige Consumer, gut getestet; `metadata_result_translator.py` jetzt mit entschiedener Zielposition |
| 3F (externe Consumer) | **mittel** | `klassen/download_handler.py` mit 4 betroffenen Importzeilen ist die komplexeste Einzeldatei; alle Änderungen mechanisch (kein Verhaltenscode) |
| 3G (alte Struktur entfernen) | **niedrig** | reine Löschung nach verifizierter 0-Referenzen-Prüfung, etabliertes Muster aus ARCH-009 |
| 3H (Regression) | **niedrig** | reine Verifikation, kein Codeeingriff |

**Gesamtrisiko: mittel.** Deutlich geringer als ARCH-009 (keine
Patch-Ziel-Migration nötig), aber größer als der einzelne P-1-Schritt
(`bot_restart_trigger.py`) — höheres Dateivolumen (17 statt 1) und P0-Status
(Metadata/Download laut `CLAUDE.md` Abschnitt 23). Empfehlung für Phase 3
(falls freigegeben): in mehreren kleinen, unabhängig testbaren PRs
entlang der obigen Phasen 3B–3G, nicht als einzelner Big-Bang-Commit —
konsistent mit `CLAUDE.md` Regel 18/8.

## 35.14 ARCH-010 Architecture Decision Record

### ADR-ARCH-010

**Problem:** `services/downloader/utils/` und
`services/downloader/utils/metadata/` sind eine historisch gewachsene
Verzeichnisverschachtelung ohne eigene fachliche Bedeutung. Sie
vermischen im Namen zwei tatsächlich unabhängige Domänen (Download-
Orchestrierung und Metadaten-Verarbeitung), obwohl die Consumer-Daten
zeigen, dass die Metadaten-Pipeline bereits heute ein eigenständiger,
auch von `handlers/` direkt konsumierter Service ist.

**Entscheidung:** `services/` erhält zwei bestätigte Top-Level-Domains:
`services/downloader/` (6 migrierte + 3 unveränderte Dateien/Verzeichnisse)
und `services/metadata/` (11 Dateien, neu). `metadata_result_translator.py`
gehört zu `services/downloader/` (Variante A, siehe 35.4/35.11).

**Begründung:** Jede der 17 Dateien wurde einzeln anhand tatsächlicher
Consumer und Dependencies bewertet, nicht anhand ihres bisherigen Pfades
(35.1–35.3). 9 von 10 `metadata/`-Unterprozessoren haben exakt einen
Consumer (die Facade) — ein starker struktureller Beleg für Kohäsion. Die
5 Downloader-Dateien sind bereits in ihren eigenen Docstrings als
download-spezifisch dokumentiert.

**Abhängigkeitsrichtung:** Downloader → Metadata als Zielrichtung, mit
genau einer dokumentierten, bewusst nicht aufgelösten Ausnahme
(`enhanced_metadata_processor.py` → `download_artifact_cleanup.py`,
ARCH-005 Strategie C — siehe 35.5).

**Translator:** `metadata_result_translator.py` → `services/downloader/`,
weil beide Consumer, der Output-Typ und der historische Entstehungszweck
(ARCH-004 P-3) Downloader-seitig sind (siehe 35.4).

**Nicht-Entscheidungen (bewusst außerhalb von ARCH-010):**
- Auflösung der `download_artifact_cleanup`-Reverse-Edge (wäre
  Verhaltensänderung, eigene Entscheidung nötig)
- `DuplicateEntry`-Schichtverletzung in `download_result_reporter.py`
  (separater, bereits dokumentierter P-1-Punkt)
- Last.fm-Duplikation in `cover_processor.py` (separater P-2-Punkt)
- `services/library/`-Frage rund um `utils/filenamefixer.py` (außerhalb
  des Scopes, keine Analyse durchgeführt)
- Umbenennung von `enhanced_metadata_processor.py` (kein Treiber, nicht
  entschieden)
- Umgang mit dem Namensrisiko `metadata/cache.py` vs.
  `utils/metadata_cache.py` (Beobachtung, keine Entscheidung)

**Konsequenzen:**
- Vorteil: `services/` bekommt zwei klar erkennbare, unabhängig testbare
  Domains; künftige Metadata-Erweiterungen haben einen eindeutigen Ort;
  0 Patch-Ziel-Migrationsrisiko.
- Kosten: 17 Dateien + 5 externe Consumer + 19 Testdateien müssen in
  Phase 3 angefasst werden (reine Importpfad-Änderungen, aber hohes
  Volumen); die eine Reverse-Edge bleibt als dauerhaft sichtbarer, nicht
  aufgelöster Architektur-Kompromiss bestehen.

## 35.15 Entscheidungsgate

Beantwortet in dieser Phase 2:

1. Zielposition aller 17 Dateien — siehe 35.1/35.10.
2. Entscheidung für `metadata_result_translator.py` — `services/downloader/`
   (35.4).
3. Dependency-Richtung — Downloader → Metadata, 1 dokumentierte Ausnahme
   (35.5).
4. Rolle von `enhanced_metadata_processor.py` — öffentliche Eintrittsstelle
   von `services/metadata/`, Name unverändert (35.6).
5. Consumer-Migrationsumfang — 5 externe Produktionsdateien (35.7).
6. Test-/Patch-Migrationsumfang — 19 Testdateien, 0 Patch-Ziele (35.7).
7. Zielstruktur — 35.10.
8. Migrationsreihenfolge — 35.12 (Phase 3A–3H).
9. Migrationsrisiken — 35.13, Gesamtrisiko mittel.
10. offene Folgefragen — 35.9 (4 Punkte, alle als „nicht ARCH-010-relevant"
    eingeordnet).
11. Empfehlung für Phase 3 — Variante A umsetzen, in mehreren kleinen PRs
    entlang 3B–3G, nach expliziter Freigabe.

---

> **ARCH-010 Phase 2 — Entscheidungsgate erreicht.**
>
> Die Migration darf erst nach ausdrücklicher Nutzerfreigabe der
> vorgeschlagenen Zielarchitektur beginnen.

Keine Codeänderungen wurden in Phase 2 vorgenommen.

---

# 36. Phase 3A/3B — Metadata-Unterprozessoren migriert (2026-08-24)

Nutzerfreigabe der in Phase 2 vorgeschlagenen Zielarchitektur (Variante A)
erhalten. Umsetzung auf Branch `arch/arch-010-phase3ab-metadata-processors`.

## 36.1 Pre-Migration-Audit

`git status` vor Beginn: Branch `main` sauber bis auf sessionsfremde,
bereits vor dieser Aufgabe bestehende Arbeitsverzeichnis-Änderungen
(gelöschte `.info.json`-Dateien unter `import/downloads/`,
`mapping/artist_overrides.json`) — nicht angefasst, nicht Teil dieses
Commits.

Verifikation der Phase-2-Feststellung „9 von 10 Unterprozessoren haben
genau einen Produktions-Consumer": repo-weit per Grep bestätigt — alle 9
Module (`album_processor`, `artist_processor`, `auto_learn`, `cache`,
`cover_processor`, `genre_processor`, `lyrics_processor`, `tag_writer`,
`title_cleaner`) haben ausschließlich `enhanced_metadata_processor.py` als
Produktions-Consumer und je eine Testdatei (`artist_processor`/
`title_cleaner` teilen sich `test_metadata_modules.py`). Interne
Cross-Importe der 9 Dateien untereinander: keine gefunden. `mock.patch`-
Ziele auf einen der 9 Modulpfade: keine gefunden (bestätigt Phase-2-Befund
aus 35.7).

Interne `models.py`-Abhängigkeit vor der Migration geprüft:
`artist_processor.py` importierte bereits absolut
(`from services.downloader.utils.metadata.models import
split_main_and_featuring`) — unverändert gültig, da `models.py` nicht
migriert wird. `cache.py` importierte relativ (`from .models import
MetadataResult`) — dieser Import wäre nach der Verschiebung nach
`services/metadata/` ins Leere gelaufen (kein `services/metadata/models.py`
vorhanden) und wurde auf den technisch notwendigen absoluten Pfad zum
unveränderten Altort umgestellt (siehe 36.2).

## 36.2 Umsetzung

**Verschoben (`git mv`, 9 Dateien, Verhalten unverändert):**

```text
services/downloader/utils/metadata/album_processor.py  → services/metadata/album_processor.py
services/downloader/utils/metadata/artist_processor.py → services/metadata/artist_processor.py
services/downloader/utils/metadata/auto_learn.py       → services/metadata/auto_learn.py
services/downloader/utils/metadata/cache.py            → services/metadata/cache.py
services/downloader/utils/metadata/cover_processor.py  → services/metadata/cover_processor.py
services/downloader/utils/metadata/genre_processor.py  → services/metadata/genre_processor.py
services/downloader/utils/metadata/lyrics_processor.py → services/metadata/lyrics_processor.py
services/downloader/utils/metadata/tag_writer.py       → services/metadata/tag_writer.py
services/downloader/utils/metadata/title_cleaner.py    → services/metadata/title_cleaner.py
```

**Neu angelegt und nachträglich aktualisiert:** `services/metadata/__init__.py`
— exportiert die 9 öffentlichen Klassen der verschobenen Module
(`AlbumProcessor`, `ArtistProcessor`, `AutoLearnManager`,
`MetadataCacheHandler`, `CoverProcessor`, `GenreProcessor`,
`LyricsProcessor`, `TagWriter`, `TitleCleaner`) über relative Importe +
`__all__`, nach Nutzerentscheidung analog zur bereits etablierten
Konvention von `services/clients/__init__.py`. Damit weicht
`services/metadata/` bewusst von der leeren
`services/downloader/utils/metadata/__init__.py`/`services/statistik/__init__.py`-
Konvention ab — `services/metadata/` ist wie `services/clients/` eine neue,
von außen konsumierbare Top-Level-Domain, kein internes Utility-Paket.
Import-Smoke-Test (`from services.metadata import ...`, alle 9 Klassen)
und volle Regression nach der Ergänzung erneut verifiziert (1009 bestanden,
unverändert 15 Vorbestand-Fehler).

**Technisch notwendige Änderungen an den 9 verschobenen Dateien (durch den
neuen Pfad erzwungen, keine Verhaltensänderung):**
- Pfad-Kopfzeilen-Kommentar (`# services/downloader/utils/metadata/X.py` →
  `# services/metadata/X.py`) in allen 9 Dateien — folgt demselben Muster
  wie bei der `NavidromeScanTrigger`-Migration in ARCH-009.
- `cache.py`: relativer Import `from .models import MetadataResult` →
  `from services.downloader.utils.metadata.models import MetadataResult`
  (models.py bleibt bewusst am alten Ort, siehe Auftrag Abschnitt 5B).
- `artist_processor.py`: keine Änderung nötig (Import war bereits absolut
  und zeigt weiterhin korrekt auf den unveränderten Ort von `models.py`).

**Keine Klassen-, Methoden-, Signatur-, Logging-, Cache- oder
Netzwerkverhaltensänderung** an einer der 9 Dateien — verifiziert per
`git diff` (nur Kopfzeile + der eine relative Import in `cache.py`
geändert, sonst 0 Zeilenänderungen je Datei).

**Angepasster Consumer:** ausschließlich
`services/downloader/utils/enhanced_metadata_processor.py` (einziger
Produktions-Consumer, wie in 36.1 verifiziert) — 9 Importzeilen von
`services.downloader.utils.metadata.<modul>` auf `services.metadata.<modul>`
umgestellt. Der `models.py`-Import in derselben Datei blieb unverändert
(`services.downloader.utils.metadata.models`), ebenso der Import von
`download_artifact_cleanup` — beide nicht Teil dieser Phase. Kein weiterer
Produktions-Consumer betroffen (`bot.py`,
`services/downloader/downloader.py`, `services/downloader/download/interfaces.py`,
`klassen/download_handler.py`, `handlers/menu/rich_menu_handler.py`
importieren keinen der 9 Unterprozessoren direkt — bestätigt per Audit,
unverändert gelassen).

**Angepasste Tests (8 Dateien, nur Importzeilen/Docstring-Pfadangaben,
keine Testlogik geändert):**
`tests/test_album_processor.py`, `tests/test_metadata_modules.py`
(`ArtistProcessor` + `TitleCleaner`), `tests/test_auto_learn.py`,
`tests/test_metadata_cache_handler.py` (Import von `MetadataCacheHandler`
umgestellt, Import von `MetadataResult` bewusst unverändert gelassen, da
`models.py` nicht migriert wurde), `tests/test_cover_processor_validation.py`
(2 Importstellen, inkl. eines lokalen Imports in einer Testmethode),
`tests/test_genre_processor.py` (Import + Docstring-Pfadangabe),
`tests/test_lyrics_processor.py` (Import + Docstring-Pfadangabe),
`tests/test_tag_writer.py` (Import + Docstring-Pfadangabe). Zusätzlich in
`test_cover_processor_validation.py` eine weitere Docstring-Pfadangabe
korrigiert (beschreibt den aktuellen Speicherort der getesteten
Produktionsklasse, keine historische Aussage).

**Nicht angefasst (wie vorgeschrieben):** `enhanced_metadata_processor.py`
(nur Importzeilen geändert, Datei selbst bleibt am alten Ort),
`models.py`, `download_utils.py`, `download_result_reporter.py`,
`download_artifact_cleanup.py`, `progress_tracker.py`, `errors.py`,
`metadata_result_translator.py`, `services/downloader/utils/` (Verzeichnis
bleibt bestehen). Keine der in Phase 2 als „nicht ARCH-010-relevant"
markierten Nebenbaustellen (ARCH-005-Cleanup, DI-Konsistenz
`album_processor.py`, Last.fm-Duplikation, `DuplicateEntry`,
`utils/metadata_cache.py`) wurde angefasst.

## 36.3 Verifikation

**Import-Audit:** repo-weiter Grep auf
`services.downloader.utils.metadata.<modul>` (dotted) und
`services/downloader/utils/metadata/<modul>.py` (slash) für alle 9 Module
— 0 verbleibende funktionale Referenzen in `.py`-Dateien außerhalb von
`docs/`. In `docs/` bewusst unverändert gelassen: alle Vorkommen in den
historischen ARCH-Phasendokumenten (`ARCH-003`, `ARCH-009 Phase 8`,
`ARCH-001`) sowie in `docs/MusicBot_ENGINEERING_BASELINE.md` — sie
beschreiben korrekt den jeweils damaligen Zustand.

**Import-Smoke-Test:**

```text
import services.metadata.album_processor    → OK
import services.metadata.artist_processor   → OK
import services.metadata.auto_learn         → OK
import services.metadata.cache              → OK
import services.metadata.cover_processor    → OK
import services.metadata.genre_processor    → OK
import services.metadata.lyrics_processor   → OK
import services.metadata.tag_writer         → OK
import services.metadata.title_cleaner      → OK
import services.downloader.utils.enhanced_metadata_processor → OK
```

Kein `ImportError`, kein `ModuleNotFoundError`, kein Zirkelimport. Alter
Pfad korrekt nicht mehr auffindbar:
`python3 -c "import services.downloader.utils.metadata.cache"` →
`ModuleNotFoundError` (erwartet).

**Gezielte Tests** (12 Dateien: 8 direkt migrierte + 4 weitere Consumer-
/Grenztests der Facade):

```text
tests/test_album_processor.py
tests/test_metadata_modules.py
tests/test_auto_learn.py
tests/test_metadata_cache_handler.py
tests/test_cover_processor_validation.py
tests/test_genre_processor.py
tests/test_lyrics_processor.py
tests/test_tag_writer.py
tests/test_autolearn_special_channel_gate.py
tests/test_enhanced_metadata_processor_aclose.py
tests/test_metadata_processor_happy_path.py
tests/test_split_main_and_featuring.py
```

Ergebnis: 11 failed, 147 passed, 14 subtests passed. Alle 11
Fehlschläge sind exakt die bekannten Vorbestand-Fehler aus
`test_auto_learn.py` (5) und `test_metadata_modules.py::TestTitleCleaner`
(3, davon 3 als Subtests), unverändert gegenüber dem dokumentierten
Bestand (siehe `docs/MusicBot_ENGINEERING_BASELINE.md`) — keine neue
Regression.

**Vollständige Regression:**

```text
vorher (Baseline, Stand nach PR #13):  1009 passed, 15 known failures
nachher (nach Phase 3A/3B):            1009 passed, 15 known failures
```

`pytest tests/ -q` liefert identisch: `15 failed, 1009 passed, 5 warnings,
14 subtests passed`. Die 15 Fehlschläge sind zeilengenau dieselben wie vor
der Migration (`test_auto_learn.py` ×5, `test_metadata_modules.py` ×3,
`test_suite.py::TestRichMenuSystem`/`TestMenuIntegration` ×4 — letztere
beide Gruppen unberührt von dieser Migration, da außerhalb des Scopes).
**Keine neuen Fehler.**

## 36.4 Strukturprüfung (Ist-Zustand nach Phase 3A/3B)

```text
services/
├── metadata/
│   ├── __init__.py                  (neu, leer)
│   ├── album_processor.py
│   ├── artist_processor.py
│   ├── auto_learn.py
│   ├── cache.py
│   ├── cover_processor.py
│   ├── genre_processor.py
│   ├── lyrics_processor.py
│   ├── tag_writer.py
│   └── title_cleaner.py
│
└── downloader/
    └── utils/
        ├── enhanced_metadata_processor.py   (unverändert am alten Ort)
        ├── download_utils.py                (unverändert)
        ├── download_result_reporter.py      (unverändert)
        ├── download_artifact_cleanup.py     (unverändert)
        ├── progress_tracker.py              (unverändert)
        ├── errors.py                        (unverändert)
        ├── metadata_result_translator.py    (unverändert)
        └── metadata/
            ├── __init__.py                  (unverändert, leer)
            └── models.py                    (unverändert)
```

Entspricht exakt der in Abschnitt 12 des Arbeitsauftrags geforderten
Zwischenstruktur.

## 36.5 Git

- Branch: `arch/arch-010-phase3ab-metadata-processors`
- Commit: siehe unten (wird nach Dokumentation erstellt)
- PR: wird erstellt, **nicht gemergt** (keine Merge-Freigabe erteilt)

## 36.6 Verbleibende Phase-3-Arbeiten

```text
Phase 3C — services/downloader/utils/metadata/models.py migrieren
Phase 3D — enhanced_metadata_processor.py migrieren
            + download_artifact_cleanup.py (gemeinsam, wegen der in
            35.5 dokumentierten Reverse-Edge)
Phase 3E — übrige Downloader-Dateien migrieren (download_utils.py,
            download_result_reporter.py, progress_tracker.py, errors.py,
            metadata_result_translator.py)
Phase 3F — externe Consumer migrieren (bot.py, downloader.py,
            download/interfaces.py, klassen/download_handler.py,
            handlers/menu/rich_menu_handler.py)
Phase 3G — alte services/downloader/utils/-Struktur entfernen
Phase 3H — finale Regression
```

**STOPP nach Phase 3A/3B. Keine automatische Fortsetzung mit Phase 3C.
Wartet auf ausdrückliche Freigabe.**

---

# 37. Phase 3C — Metadata-Modelle migriert (2026-08-24)

Nutzerfreigabe für Phase 3C erhalten. Umsetzung auf Branch
`arch/arch-010-phase3c-metadata-models`.

## 37.1 Vor-Migration-Verifikation

Ausgangspunkt geprüft und bestätigt deckungsgleich mit dem erwarteten
Phase-3A/3B-Endzustand: `services/metadata/` enthält die 9 bereits
migrierten Unterprozessoren, `services/downloader/utils/metadata/`
enthält nur noch `__init__.py` und `models.py`,
`enhanced_metadata_processor.py` liegt unverändert unter
`services/downloader/utils/`. Branch `main` sauber bis auf dieselben
sessionsfremden Arbeitsverzeichnis-Änderungen wie in Phase 3A/3B (nicht
angefasst).

**Einzige Abweichung von der im Auftrag angenommenen Ausgangslage:**
`services/metadata/__init__.py` ist entgegen der Auftragsbeschreibung
(„bleibt leer") **nicht leer** — es exportiert seit einem separaten,
ausdrücklichen Nutzerauftrag nach Phase 3A/3B die 9 öffentlichen Klassen
(analog `services/clients/__init__.py`, siehe Abschnitt 36.2). Dies wurde
als bekannte, bewusste Abweichung gewertet, nicht als defekter
Repository-Zustand — `__init__.py` wurde in Phase 3C **nicht** angefasst
(weder auf „leer" zurückgesetzt noch um `models.py`-Exporte erweitert),
wie in Auftrag Abschnitt 7 gefordert.

## 37.2 Consumer-Audit `models.py` (vor der Migration)

Repo-weit verifiziert (dotted, relativ, slash, `TYPE_CHECKING`,
`mock.patch`, dynamische Imports) — keine Annahmen aus Phase 2
übernommen, alle Treffer einzeln geprüft:

| Consumer | aktueller Import | Zielimport | Typ |
|---|---|---|---|
| `services/downloader/utils/enhanced_metadata_processor.py` | `from services.downloader.utils.metadata.models import (MetadataResult, EnhancedProcessingStats, split_main_and_featuring)` | `from services.metadata.models import (...)` | Produktion |
| `services/downloader/download/interfaces.py` | `from services.downloader.utils.metadata.models import MetadataResult` | `from services.metadata.models import MetadataResult` | Produktion |
| `services/downloader/utils/metadata_result_translator.py` | „ | „ | Produktion |
| `services/downloader/utils/download_utils.py` | „ | „ | Produktion |
| `services/metadata/artist_processor.py` (bereits migriert, jetzt Geschwisterdatei) | `from services.downloader.utils.metadata.models import split_main_and_featuring` | `from .models import split_main_and_featuring` (relativ, etablierter Stil wie `services/clients/`) | Produktion |
| `services/metadata/cache.py` (bereits migriert, jetzt Geschwisterdatei) | `from services.downloader.utils.metadata.models import MetadataResult` | `from .models import MetadataResult` (relativ) | Produktion |
| `tests/test_download_utils_metadata_translation.py` | `from services.downloader.utils.metadata.models import MetadataResult` | `from services.metadata.models import MetadataResult` | Test |
| `tests/test_metadata_result_translator.py` | „ | „ | Test |
| `tests/test_metadata_cache_handler.py` | „ | „ | Test |
| `tests/test_download_handler_process_single_download_result.py` | „ | „ | Test |
| `tests/test_split_main_and_featuring.py` | `from services.downloader.utils.metadata.models import split_main_and_featuring` (+ Docstring-Pfadangabe) | `from services.metadata.models import split_main_and_featuring` | Test |

Keine `TYPE_CHECKING`-Referenzen, keine `mock.patch`-Ziele, keine
dynamischen Imports auf `models.py` gefunden (repo-weit verifiziert).

**Zusätzlich als aktuelle Zustandsbeschreibung korrigiert** (keine
historische Doku): Docstring-Kommentar in
`services/downloader/download/models.py` („`MetadataResult` ... lebt
weiterhin in `services.downloader.utils.metadata.models`") — beschreibt
den tatsächlichen, jetzt veralteten Ist-Zustand, nicht eine historische
Entscheidung, daher aktualisiert.

## 37.3 Migration

`git mv services/downloader/utils/metadata/models.py services/metadata/models.py`.
Implementierung byte-identisch bis auf die technisch erforderliche
Pfad-Kopfzeile (`# services/downloader/utils/metadata/models.py` →
`# services/metadata/models.py`, gleiches Muster wie bei allen bisherigen
Verschiebungen in ARCH-009/ARCH-010). Keine Klassen-, Feld-, Default-,
Typannotations-, Methoden- oder API-Änderung.

**11 Consumer atomar in diesem Commit mitgezogen** (6 Produktion, 5 Test —
siehe 37.2). `services/metadata/__init__.py` unverändert gelassen (siehe
37.1).

## 37.4 Verifikation

**Import-Audit:** repo-weiter Grep auf
`services.downloader.utils.metadata.models` (dotted) und
`services/downloader/utils/metadata/models` (slash) — 0 verbleibende
funktionale Referenzen in `.py`-Dateien. `docs/` bewusst unverändert
gelassen (historische ARCH-Dokumente beschreiben korrekt den jeweils
damaligen Zustand).

**Import-Smoke-Test:** `services.metadata.models` sowie alle 9 bereits
migrierten `services.metadata.*`-Module, `enhanced_metadata_processor.py`,
`download/interfaces.py`, `metadata_result_translator.py`,
`download_utils.py` — alle importierbar, kein `ImportError`, kein
`ModuleNotFoundError`, kein Zirkelimport. Alter Pfad korrekt nicht mehr
auffindbar (`ModuleNotFoundError` bei
`import services.downloader.utils.metadata.models`).

**Gezielte Tests** (15 Dateien: 5 direkt migrierte Consumer-Tests + 9
bereits migrierte Metadata-Prozessor-Tests + 3 Facade-Grenztests, teils
überlappend): 11 failed, 195 passed, 14 subtests passed — alle 11
Fehlschläge exakt die bekannten Vorbestand-Fehler aus `test_auto_learn.py`
(5) und `test_metadata_modules.py::TestTitleCleaner` (3, teils Subtests).

**Vollständige Regression:**

```text
vorher (Baseline, Stand nach PR #15):  1009 passed, 15 known failures
nachher (nach Phase 3C):               1009 passed, 15 known failures
```

`pytest tests/ -q` → `15 failed, 1009 passed, 5 warnings, 14 subtests
passed`, zeilengenau identische Fehlschläge wie vor der Migration. **Keine
neuen Fehler.**

## 37.5 Strukturprüfung (Ist-Zustand nach Phase 3C)

```text
services/
├── metadata/
│   ├── __init__.py                  (Exporte, unverändert seit Nachtrag zu 3A/3B)
│   ├── models.py                    (neu hier)
│   ├── album_processor.py
│   ├── artist_processor.py
│   ├── auto_learn.py
│   ├── cache.py
│   ├── cover_processor.py
│   ├── genre_processor.py
│   ├── lyrics_processor.py
│   ├── tag_writer.py
│   └── title_cleaner.py
│
└── downloader/
    └── utils/
        ├── enhanced_metadata_processor.py   (unverändert am alten Ort)
        ├── download_utils.py                (unverändert)
        ├── download_result_reporter.py      (unverändert)
        ├── download_artifact_cleanup.py     (unverändert)
        ├── progress_tracker.py              (unverändert)
        ├── errors.py                        (unverändert)
        ├── metadata_result_translator.py    (unverändert)
        └── metadata/
            └── __init__.py                  (einziger verbleibender Inhalt, leer)
```

Entspricht exakt der im Arbeitsauftrag geforderten Reststruktur.

## 37.6 Git

- Branch: `arch/arch-010-phase3c-metadata-models`
- Commit: siehe unten
- PR: wird erstellt, **nicht gemergt**

## 37.7 Verbleibende Phase-3-Arbeiten

```text
Phase 3D — enhanced_metadata_processor.py migrieren
            + download_artifact_cleanup.py (gemeinsam, wegen der in
            35.5 dokumentierten Reverse-Edge)
Phase 3E — übrige Downloader-Dateien migrieren (download_utils.py,
            download_result_reporter.py, progress_tracker.py, errors.py,
            metadata_result_translator.py)
Phase 3F — externe Consumer migrieren (bot.py, downloader.py,
            download/interfaces.py, klassen/download_handler.py,
            handlers/menu/rich_menu_handler.py)
Phase 3G — alte services/downloader/utils/-Struktur entfernen
Phase 3H — finale Regression
```

**STOPP nach Phase 3C. Keine automatische Fortsetzung mit Phase 3D.
Wartet auf ausdrückliche Freigabe.**
