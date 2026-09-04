# MusicBot — Music Library Health Scanner

`scripts/library_health_check.py` analysiert die konfigurierte Music-Library
**vollständig read-only** und erzeugt einen strukturierten Health-Report
(JSON + human-readable Text).

> Frage, die der Scanner beantwortet: *„Wie gesund ist meine Musikbibliothek
> und welche Dateien/Alben/Artists brauchen Aufmerksamkeit?"*

Der Scanner ist **ausschließlich diagnostisch**. Er repariert nichts, er
schlägt keine Auflösung vor, er fasst keine Library-Datei schreibend an.

Status: **Phase 1 vollständig** (PR 1 Discovery + Per-Datei-Analyse, PR 2
Group-Analyse, PR 3 deterministischer Health-Score). `scan.pending_analyses`
ist jetzt `[]`.

---

## 1. Nutzung

```bash
# gegen die konfigurierte Produktions-Library (config.Config.LIBRARY_DIR)
python scripts/library_health_check.py

# gegen eine beliebige Library-Wurzel
python scripts/library_health_check.py --library /pfad/zur/library

# Report-Ziele explizit
python scripts/library_health_check.py \
    --json  /pfad/report.json \
    --output /pfad/report.txt

python scripts/library_health_check.py --verbose        # Pro-Datei-DEBUG-Log
python scripts/library_health_check.py --fail-on-error   # Exit 1 bei ERROR/CRITICAL
```

**Default-Report-Pfade:** `<BASE_DIR>/cache/data/library_health_report.json`
und `…/library_health_report.txt` (beide außerhalb der Library, `cache/` ist
git-ignoriert).

Es gibt **keine** Mutations-Optionen. `--fix` / `--repair` / `--delete` /
`--execute` / `--apply` werden mit Fehler und Exit-Code 2 abgelehnt.

### Exit-Codes

| Code | Bedeutung |
|---|---|
| 0 | Scan abgeschlossen (Findings sind kein Fehler) |
| 1 | nur mit `--fail-on-error`: ERROR-/CRITICAL-Issues gefunden |
| 2 | ungültige Argumente / Library nicht gefunden / Mutations-Flag |
| 3 | schwerer Fehler während des Scans |

---

## 2. Read-only-Garantie (Prompt Abschnitt 2/33)

| Schutz | Umsetzung |
|---|---|
| Kein Schreib-Import | `services/library_health/` importiert **keinen** Schreib-Pfad — kein `TagWriter`, `FilenameFixerTool`, `AudioEnhancer`, `EnhancedMetadataProcessor`, `services/duplicate/execution.py`. `tests/test_library_health_readonly_safety.py::test_scanner_import_graph_has_no_writer_modules` prüft das in einem frischen Interpreter. |
| Kein `ArtistNormalizer` | `ArtistNormalizer` scannt bei erster Konstruktion `LIBRARY_DIR` und **schreibt** neu gefundene Artists in `mapping/artist_overrides.json` (siehe `tests/conftest.py`). Der Scanner nutzt deshalb — wie `scripts/resolve_duplicates.py` — nur den simplen Suffix-Strip-Fallback aus `services/duplicate/classification.py`. |
| `GenreMapper` nur lesend | nur `validate_genre()` wird aufgerufen (reiner `open(…, "r")`-Pfad), niemals `auto_learn`. Als CLI-Subprozess ist das SingletonMixin-Verhalten unkritisch (First Mover, frischer Prozess). |
| Reine Reader | `mutagen.MP4(path)` ohne `.save()`, `ffprobe` (kein Output-File), `PIL.Image.open(BytesIO(...))`. |
| Symlinks | Discovery folgt keinem Symlink (Datei oder Zwischenverzeichnis). |
| Technischer Nachweis | `test_run_scan_does_not_mutate_library` / `test_cli_subprocess_does_not_mutate_library`: SHA256 + `mtime_ns` + Größe + relative Pfade **vorher == nachher**, inkl. einer bewusst defekten Datei. |

---

## 3. Architektur

Spiegelt das etablierte Muster `services/duplicate/` ↔ `scripts/resolve_duplicates.py`:

```text
services/library_health/
    models.py         Enums + Datencontainer (AnalysisState, Severity, Issue, FileRecord, FileHealth)
    issues.py         stabiles Issue-Code-Register (Default-Severity + Scope + Beschreibung)
    discovery.py      rekursives Auffinden + Pfad-/Struktur-Fakten (nutzt classification.classify_by_path)
    tag_reader.py     read-only I/O-Adapter: Tags (m4a/mp3), ffprobe-Stream, eingebettetes Artwork
    file_analysis.py  reine Funktion (FileRecord, TagData, StreamData, ArtworkData) -> FileHealth
    group_analysis.py reine Funktion (list[FileHealth], file_sha256) -> list[Issue]  (Album/Artist/Duplicate)
    scoring.py        reine Funktion (list[FileHealth], group_issues) -> Health-Section (file/album/artist/library-Score)
    report.py         stabile, versionierte JSON-Struktur + Text-Report (deterministisch sortiert)
    scanner.py        Orchestrierung DISCOVERY -> READ -> ANALYSE -> GROUP-ANALYSE -> SCORING -> REPORT

scripts/library_health_check.py   dünner CLI-Wrapper (CLI -> Config -> Scanner -> Report), keine Fachlogik
```

`file_analysis.py` ist frei von I/O und von einem `GenreMapper`-Import
(Validator wird als Callable injiziert) → vollständig deterministisch und
ohne Fixtures unit-testbar.

### Wiederverwendete bestehende Bausteine

| Zweck | Quelle | Art |
|---|---|---|
| Single/Album-Erkennung am Pfad | `services/duplicate/classification.classify_by_path()` | REUSE |
| Formate | `config.Config.SUPPORTED_FORMATS` / `AUDIO_FORMAT` | REUSE |
| Library-Schema | `utils/filenamefixer.py::build_final_path()` (nur als Referenz gelesen) | REFERENCE |
| MP4-Atom-Namen | deckungsgleich zu `services/metadata/tag_writer.py` (dokumentiert nachgebildet, nicht importiert) | MIRROR |
| Genre-Konvention | `utils/genre_map.GenreMapper.validate_genre()` | REUSE (read-only) |
| Duplicate-Identität | `services/duplicate/classification.py` (`build_candidate`, `group_candidates_by_identity`, MB-ID-/ISRC-Vergleich, `has_album_context_risk`) — dieselbe Normalisierung wie `DuplicateDetector`, inkl. DUP-03 (Remix/Live/Version nicht zusammengeworfen) | REUSE (Domain) |
| Logger | `logger.get_module_logger("library_health")` | REUSE |
| Pillow | bereits Projekt-Dependency (`CoverProcessor`) | REUSE |

`resolution.py` / `execution.py` (KEEP/REMOVE-Entscheidung, Löschung)
werden **nicht** importiert — der Scanner erkennt Duplicate-Kandidaten und
löst sie nie auf (Prompt Abschnitt 17).

---

## 4. Analyse-Dimensionen & Zustände (PR 1)

Pro Datei wird je Dimension ein `AnalysisState` bestimmt — **strikt getrennt**
(Prompt Abschnitt 9): `PRESENT` / `MISSING` / `INVALID` / `PARTIAL` /
`NOT_ANALYZABLE`. *Nicht analysierbar ≠ nicht vorhanden.*

| Dimension | Prüft |
|---|---|
| `metadata` | Artist, Titel, Album, Album-Artist, Jahr (+ Plausibilität), Tracknummer (Kontext!), MB-Recording-/Release-ID, ISRC |
| `genre` | vorhanden / leer / Separator-Konvention (`"; "` vs. `" / "`) / vom `GenreMapper` erkannt |
| `artwork` | eingebettet? dekodierbar? Auflösung ≥ 500 px Kante? quadratisch? |
| `lyrics` | vorhanden / leer / Platzhalter-Text |
| `audio` | ffprobe: Stream vorhanden? Codec/Bitrate/Dauer, Korruptions-Marker |
| `loudness` | **nur** ReplayGain-/Loudness-**Tag**-Existenz/-Format — **keine** Messung/Berechnung (Prompt Abschnitt 16) |
| Struktur/Dateiname | in erwarteter `<Artist>/(Singles\|Jahr - Album)/`-Hierarchie? Dateiname-Stamm ↔ Titel-Tag, verdächtige Zeichen, Endung |
| Multi-Artist | `';'` im Einzelwert, `feat.` im `©ART` statt separatem `ARTISTS`, Duplikate, `©ART` ↔ `ARTISTS`-Freeform ↔ Album-Artist |

### Group-Analyse (PR 2, `group_analysis.py`)

| Ebene | Prüft |
|---|---|
| **Album** (`<Artist>/<Jahr - Album>/`, ≥ 2 Tracks) | Tracknummern-Lücke, doppelte Tracknummer (pro Disc), abweichende Album-/Album-Artist-/Jahr-/Genre-/Release-ID-Tags, unterschiedliche eingebettete Cover |
| **Artist** | Verzeichnisname ↔ dominanter Artist-Tag; mehrere Verzeichnisse, die auf denselben normalisierten Namen abbilden (Schreibvarianten) |
| **Duplicate** | `DUPLICATE_EXACT` (SHA-256 byte-identisch, Größen-Vorfilter), `DUPLICATE_RECORDING` (gleiche MB Recording ID / ISRC), `DUPLICATE_SUSPECTED` (gleicher normalisierter Artist+Titel — Remix/Live/Version bleiben getrennt). Ein Kandidat wird nur in der stärksten Kategorie gemeldet. |

`DUPLICATE_SUSPECTED` ist `INFO`/Observation und trägt `details.album_context_risk`
(Remix-/Live-/Versions-Hinweis im Albumnamen). `ALBUM_GENRE_INCONSISTENT` /
`ALBUM_YEAR_INCONSISTENT` / `ALBUM_RELEASE_ID_INCONSISTENT` sind `INFO`
(können legitim sein). `ALBUM_DUPLICATE_TRACK_NUMBER` ist `ERROR`.

### Wichtig: Observation ≠ Defect (Prompt Abschnitt 22)

Fehlende **optionale** Felder sind `INFO`, kein Qualitätsmangel:

- `LOUDNESS_TAG_MISSING` → **INFO** (die aktuelle Pipeline schreibt bewusst
  keinen ReplayGain-Tag — sie normalisiert die Lautheit vor dem Taggen per
  FFmpeg-loudnorm ohne Nachweis-Tag).
- `META_MB_*_MISSING`, `META_ISRC_MISSING`, `LYRICS_MISSING` → **INFO**.
- `META_TRACK_NUMBER_MISSING` → **INFO** bei einer Single, **WARNING** nur im
  Album-Kontext.
- Album-Artist ≠ Artist wird bei Compilation/Playlist **nicht** gemeldet.

---

## 5. Issue-Codes

Stabile, maschinenlesbare Codes; zentral registriert in
`services/library_health/issues.py` (Default-Severity + Scope + Beschreibung).
`tests/test_library_health_issues.py` verifiziert, dass jeder vom Analyzer
erzeugte Code registriert ist und kein registrierter Code tot ist.

`INFO` / `WARNING` / `ERROR` / `CRITICAL` — `INFO` beeinflusst später den
Health-Score **nicht** (PR 3).

**Datei-Ebene:** `META_NOT_ANALYZABLE`, `META_ARTIST_MISSING`,
`META_TITLE_MISSING`, `META_ALBUM_MISSING`, `META_ALBUM_ARTIST_MISSING`,
`META_YEAR_MISSING`, `META_YEAR_INVALID`, `META_GENRE_MISSING`,
`META_TRACK_NUMBER_MISSING`, `META_MB_RECORDING_MISSING`,
`META_MB_RELEASE_MISSING`, `META_ISRC_MISSING`, `ARTWORK_MISSING`,
`ARTWORK_INVALID`, `ARTWORK_LOW_RESOLUTION`, `ARTWORK_NON_SQUARE`,
`LYRICS_MISSING`, `LYRICS_EMPTY`, `LYRICS_INVALID`, `AUDIO_NOT_ANALYZABLE`,
`AUDIO_NO_STREAM`, `AUDIO_CORRUPT`, `AUDIO_LOW_BITRATE`, `AUDIO_VERY_SHORT`,
`LOUDNESS_TAG_MISSING`, `LOUDNESS_TAG_INVALID`, `LOUDNESS_TAG_PARTIAL`,
`STRUCTURE_INVALID_PATH`, `STRUCTURE_FILE_OUTSIDE_HIERARCHY`,
`FILENAME_TITLE_MISMATCH`, `FILENAME_SUSPICIOUS`,
`FILENAME_EXTENSION_UNEXPECTED`, `MULTI_ARTIST_SUSPICIOUS`,
`MULTI_ARTIST_INCONSISTENT`, `MULTI_ARTIST_DUPLICATE`, `GENRE_EMPTY`,
`GENRE_INVALID`, `GENRE_DELIMITER_INCONSISTENT`.

**Album-Ebene:** `ALBUM_TRACK_GAP`, `ALBUM_DUPLICATE_TRACK_NUMBER`,
`ALBUM_NAME_INCONSISTENT`, `ALBUM_ARTIST_INCONSISTENT`,
`ALBUM_YEAR_INCONSISTENT`, `ALBUM_GENRE_INCONSISTENT`,
`ALBUM_RELEASE_ID_INCONSISTENT`, `ALBUM_COVER_INCONSISTENT`.

**Artist-Ebene:** `ARTIST_DIR_TAG_MISMATCH`, `ARTIST_NAME_VARIANTS`.

**Library-Ebene:** `DUPLICATE_EXACT`, `DUPLICATE_RECORDING`, `DUPLICATE_SUSPECTED`.

---

## 5a. Health-Score (PR 3, `scoring.py`)

**Deterministisch, reproduzierbar, dokumentiert** — dieselbe Library im
selben Zustand ergibt denselben Score. Keine versteckten/dynamischen
Gewichte (Prompt Abschnitt 23).

Jeder Score startet bei 100 und wird um eine **feste Strafe pro Issue**
reduziert, ausschließlich nach dessen Severity:

| Severity | Strafe |
|---|---|
| `CRITICAL` | −40 |
| `ERROR` | −15 |
| `WARNING` | −4 |
| `INFO` | **0** (Beobachtung, kein Defekt) |

```text
file_health_score    = clamp(100 − Σ Strafe(Datei-Issues))
album_health_score   = clamp(Ø file_health_score der Album-Tracks − Σ Strafe(Album-Issues))
artist_health_score  = clamp(Ø file_health_score der Artist-Dateien − Σ Strafe(Artist-Issues))
library_health_score = clamp(Ø aller file_health_scores − min(15, 0.5 · Σ Strafe(Library-Issues)))
clamp(x) = auf [0, 100] begrenzt, 1 Nachkommastelle
```

Der Library-Issue-Abzug (Duplicate-Gruppen) ist bei −15 gedeckelt — viele
`SUSPECTED`-Kandidaten (INFO, Strafe 0) oder einige `EXACT`-Dubletten sollen
die Library nicht auf 0 ziehen (Aufräum-Kandidaten, kein Totalschaden).

Status-Bänder (nur Darstellung): `≥ 90 EXCELLENT` · `≥ 75 GOOD` · `≥ 50 FAIR` · `≥ 25 POOR` · `< 25 CRITICAL`.
Die exakte Gewichts-Tabelle steht zusätzlich im Report unter `health.weights`.

## 6. JSON-Report-Schema (`schema_version` 1.0)

```jsonc
{
  "schema_version": "1.0",
  "scanner_version": "1.0",
  "scan":   { "started_at": "...", "completed_at": "...", "duration_seconds": 0,
              "pending_analyses": [] },
  "library":{ "root": "...", "files": 0, "artists": 0, "albums": 0 },
  "health": { "score": 0.0, "status": "EXCELLENT|GOOD|FAIR|POOR|CRITICAL",
              "weights": { "severity_penalty": {...}, "library_issue_factor": 0.5,
                           "library_issue_max_deduction": 15.0, "status_bands": {...} } },
  "statistics": {
     "total_files": 0, "total_artists": 0, "total_albums": 0,
     "healthy_files": 0, "files_with_warnings": 0, "files_with_errors": 0,
     "files_not_analyzable": 0,
     "missing_metadata": 0, "missing_artwork": 0, "missing_lyrics": 0,
     "missing_loudness": 0, "structure_problems": 0, "audio_problems": 0,
     "duplicate_groups": 0,
     "duplicate_groups_by_kind": { "exact": 0, "recording": 0, "suspected": 0 },
     "album_inconsistencies": 0, "artist_inconsistencies": 0,
     "issues_by_code": { "...": 0 }, "issues_by_severity": { "...": 0 }
  },
  "issues": [ { "issue_code": "...", "severity": "...", "scope": "file|album|artist|library",
               "path": "...", "artist": "...", "album": "...", "title": "...",
               "message": "...", "details": {}, "confidence": null,
               "related_files": [] } ],
  "artists": [ { "artist": "...", "file_count": 0, "album_count": 0,
                 "health_score": 0.0, "issue_codes": [...] } ],
  "albums":  [ { "artist": "...", "album": "...", "file_count": 0,
                 "health_score": 0.0, "issue_codes": [...] } ],
  "files":   [ { "relative_path": "...", "states": {...}, "issue_codes": [...],
                 "file_health_score": 0.0, "artist": "...", "album": "...", "...": "..." } ]
}
```

**Determinismus (Prompt Abschnitt 35):** Dateien nach `relative_path`,
Issues nach (Severity absteigend, Code, Pfad). Nur die Zeitstempel variieren.

---

## 7. Bekannte Grenzen (bewusst)

- **Kein Deep-Audio-Decode** im Standardlauf — `AUDIO_CORRUPT` wird nur bei
  eindeutigen ffprobe-Fehlermarkern gemeldet (Performance, Prompt Abschnitt 27).
- **SHA-256** wird nur für Dateien mit **identischer Größe** berechnet
  (byte-identische Dateien haben zwingend dieselbe Größe — vollständiger,
  billiger Vorfilter, Prompt Abschnitt 27).
- **Kein Navidrome-Abgleich** — nicht Teil dieser Phase (Prompt Abschnitt 30).
- Nur `.m4a/.mp4` (voll) und `.mp3` (best-effort); `.ogg/.opus` werden
  gefunden, aber ohne Tag-/Artwork-Detailanalyse (die Produktions-Pipeline
  schreibt ausschließlich `.m4a`).

---

## 8. Tests

| Datei | Deckt ab |
|---|---|
| `tests/test_library_health_discovery.py` | Formate, Sortierung, Section/Single/Album, Symlink-Skip |
| `tests/test_library_health_tag_reader.py` | echte m4a: Tags/Artwork/ffprobe, defekte Datei |
| `tests/test_library_health_file_analysis.py` | jede Dimension als pure Unit (synthetische Eingaben) |
| `tests/test_library_health_group_analysis.py` | Album-Gap/Dublette/Disc, Artist-Varianten, Duplicate EXACT/RECORDING/SUSPECTED, DUP-03 (Remix ≠ Duplikat) |
| `tests/test_library_health_scoring.py` | feste Gewichts-Tabelle, INFO ohne Wirkung, Clamp, Determinismus, Album-/Artist-/Library-Aggregation, Deckelung, Status-Bänder |
| `tests/test_library_health_issues.py` | Register-Vollständigkeit/-Stabilität |
| `tests/test_library_health_report.py` | Schema, Sortierung, Determinismus, Statistik-Buckets |
| `tests/test_library_health_readonly_safety.py` | **SHA256/mtime/size/Pfade vorher==nachher**, CLI-Subprozess, Import-Graph, abgelehnte Mutations-Flags |
