# MusicBot Engineering Baseline

**Repository:** `dkmd89-dev/musicbot`  
**Branch:** `main`  
**Baseline-Datum:** 2026-08-16

## Zweck

Diese Baseline hält den aktuellen technischen Ausgangszustand fest, bevor weitere Optimierungen oder Refactorings erfolgen.

Grundregel:

> Erst verstehen → dann testen → dann verbessern.

---

## 1. Projektstatus

Die README beschreibt das Projekt aktuell nur als „Musikdownloader mit Telegram funktion und Navidrome“. fileciteturn31file0L2-L2

Die Repository-Struktur zeigt jedoch ein deutlich größeres gewachsenes System mit:

- Telegram-Bot und RichMenu
- YouTube- und Spotify-Verarbeitung
- Metadaten-Pipeline
- Artist- und Genre-System
- Lyrics und Cover-Art
- MusicBrainz / Last.fm
- Caches
- Duplikaterkennung
- Library-Organisation
- FFmpeg/Audioverarbeitung
- Navidrome
- Statistiken
- Administration
- Backup/Restart
- Error Handling und Logging
- Migrationen
- Tests
- YAML-/JSON-basierter Fachlogik

**Einordnung:** Das Projekt ist inzwischen ein echtes Softwaresystem, auch wenn es ursprünglich als Hobbyprojekt gewachsen ist.

---

# 2. Architektur-Baseline

```text
Telegram
   │
   ▼
ExtendedBot / bot.py
   │
   ▼
RichMenuHandler
   │
   ├── Menü / Admin / Statistik
   │
   └── DownloadHandler
          │
          ├── YouTube
          └── Spotify
                  │
                  ▼
        Metadata Pipeline
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Artist    Genre     Lyrics
        │         │         │
        └─────────┼─────────┘
                  ▼
        MusicBrainz / Cover
                  │
                  ▼
          Audio / FFmpeg
                  │
                  ▼
        Library / Metadata
                  │
                  ▼
              Navidrome
```

`bot.py` zeigt die zentrale Initialisierung von Telegram Application, Error Handler, RichMenuHandler und Telegram Handlern. fileciteturn33file0L2-L2

---

# 3. Kritische Geschäftsabläufe

## P0 – Download

```text
URL
 ↓
Erkennung
 ↓
Download
 ↓
Metadaten
 ↓
Library
```

## P0 – Metadata

```text
Track
 ↓
Cache
 ↓
Parsing
 ↓
Artist
 ↓
Title
 ↓
Genre
 ↓
Lyrics
 ↓
MusicBrainz
 ↓
Cover
 ↓
Album/Jahr
 ↓
Audio
 ↓
Tags
```

## P0 – Duplicate Detection

```text
URL
 ↓
Normalisierung
 ↓
URL-Duplikat
 ↓
Artist/Titel
 ↓
Parser
 ↓
Library-Fallback
```

## P1 – Telegram

```text
Update
 ↓
Handler
 ↓
Menu/Command
 ↓
Service
 ↓
Response
```

---

# 4. Risikobaseline

| ID | Risiko | Priorität | Status |
|---|---|---:|---|
| SEC-001 | Sensible Daten in Request-Logs möglich | P0 | **behoben** (Phase 1) — `api/navidrome_api.py` maskiert `u`/`p` jetzt via `Config.mask_sensitive()` vor dem Log-Call; Regressionstest `tests/test_navidrome_api_logging.py` simuliert das reale Auslöse-Szenario (Admin hebt Modul-Log-Level über die Telegram-Logger-Verwaltung an) |
| TEST-001 | Teile der Tests testen nicht direkt Produktionsimplementierungen | P0 | **teilweise behoben** (Phase 1) — `tests/test_genre_processor.py` importiert jetzt die echte `GenreProcessor`-Produktionsklasse (vorher: eigene Nachimplementierung, wurde von pytest wegen `__init__`-Konstruktor der Testklasse zudem gar nicht eingesammelt). Weitere Bereiche (siehe TEST-002/TEST-003) außerhalb dieses Fixes |
| TEST-002 | `handlers/duplicate_handler.py` hatte vor Phase 1 keinerlei Testabdeckung; dabei wurde ein aktiver Bug gefunden: `check_library_duplicate()` (Duplicate-Detection Layer 4) rief `re.sub()` ohne `import re` auf → `NameError`, von `except Exception` verschluckt, Layer 4 lieferte in Produktion immer `None` | P0 | **behoben** (Phase 1) — `import re` ergänzt, 12 Charakterisierungstests in `tests/test_duplicate_handler.py`, inkl. Regressionstest für den Bugfix |
| TEST-003 | `MetadataCacheHandler.check()` und `_normalize_cache_title()` (`services/downloader/utils/metadata/cache.py`) waren seit dem Initial-Commit reine Stubs (Body nur `...`, lieferten immer `None`). `EnhancedMetadataProcessor.process_single_track()` nutzt `check()` als Cache-Hit-Prüfung → der Cache-Hit-Pfad der Metadata-Pipeline war in Produktion vollständig wirkungslos, jeder Track durchlief immer die volle Pipeline inkl. externer API-Calls | P0 | **behoben** (nach TEST-003-Freigabe) — `check()` wird VOR, `store()` NACH der Artist-/Titel-Bereinigung aufgerufen, ein direkter Artist::Titel-Lookup aus rohen Daten würde daher praktisch nie treffen. Lösung: zusätzlicher Video-ID-Index (`video_id_index.json`, analog zum bestehenden `DuplicateCache`-Muster) — `track_metadata["id"]` ist bei YouTube- wie Spotify-Downloads bereits vor der Bereinigung stabil vorhanden. `check()` validiert zusätzlich, dass die referenzierte `library_path`-Datei noch existiert (Orphan-Schutz), bevor ein Treffer zurückgegeben wird. `_normalize_cache_title()`/`invalidate()` bewusst unangetastet (bestätigt toter Aufrufer bzw. ausreichender bestehender Fallback). 6 neue/aktualisierte Tests in `tests/test_metadata_cache_handler.py` + ein End-to-End-Beweis in `tests/test_metadata_processor_happy_path.py` (zweiter Aufruf mit gleicher Video-ID ist `from_cache=True` UND ruft externe Clients nicht erneut auf — ohne Fix crasht der zweite Aufruf sogar mit `FileNotFoundError`, da die Quelldatei vom ersten Durchlauf bereits verschoben wurde). Alle Tests am unfixierten Stub als fehlschlagend verifiziert |
| E2E-001 | Hauptpfad nicht ausreichend Ende-zu-Ende abgesichert | P0 | **behoben** — `tests/test_metadata_processor_happy_path.py`: echter End-to-End-Lauf `EnhancedDuplicateHandler.check_for_duplicates` → `EnhancedMetadataProcessor.process_single_track` → `FilenameFixerTool.move_to_library` → erneuter Duplicate-Check (erkennt jetzt Duplikat), inkl. Negativtest für den globalen `try/except`-Sicherheitsnetz-Charakter der Pipeline. Nur externe Dienste (MusicBrainz/Last.fm/Genius/Cover-Netzwerk/FFmpeg) gefakt, alle Sub-Prozessoren real inkl. echter YAML-Genre-/Artist-Regeln aus einer tmp-Kopie von `mapping/` |
| CFG-001 | Config enthält Import-/Initialisierungslogik | P1 | offen (bewusst außerhalb Phase-1-Scope, siehe Abschnitt 12) |
| ARCH-001 | Große Orchestrator-Klassen | P1 | offen — `process_single_track` bei der Phase-1-Exploration als noch größer bestätigt als angenommen (~750 Zeilen) |
| CACHE-001 | Mehrere Cache-/Normalisierungswege (`get_url_hash` vs. `_normalize_url_for_cache` in `DuplicateCache`) — `add_entry()`/`invalidate_entry()` nutzten den groben `get_url_hash()` als Dict-Key, `check_url_duplicate()` die YouTube-bewusste `_normalize_url_for_cache()`; `invalidate_entry(url=...)` konnte dadurch bei einer anders formatierten, aber aequivalenten URL still fehlschlagen | P1 | **behoben** (Phase 2, Fortsetzung) — `get_url_hash()` nutzt jetzt dieselbe Normalisierung wie `check_url_duplicate()`. 2 Tests in `tests/test_duplicate_handler.py::TestUrlHashConsistencyCache001Fix`, am unfixierten Code als fehlschlagend verifiziert |
| SEC-002 | Path Traversal über `sanitize_filename()` (`utils/helpers.py`): `ILLEGAL_CHARS_PATTERN` entfernte Schrägstriche u.a., aber keine literalen Punkte. Ein Artist-/Album-/Titel-Tag mit Wert `".."` (z.B. aus YouTube-Metadaten) überstand die Bereinigung unverändert und ließ `FilenameFixerTool.build_final_path()` das Zielverzeichnis verlassen — empirisch reproduziert (Datei landete eine Ebene über `library_dir`). Traf den Live-Pfad `move_to_library`, der bei jedem Download durchlaufen wird | P0 | **behoben** (Phase 2) — zwei Ebenen: (1) `sanitize_filename()` neutralisiert Ergebnisse, die nur aus Punkten bestehen; (2) `FilenameFixerTool._ensure_within_roots()` prüft den finalen Zielpfad defensiv gegen `library_dir`/`_podcast_dir`, bevor er zurückgegeben wird. 7 Tests in `tests/test_helpers_sanitize_filename.py` + 4 in `tests/test_filenamefixer.py::TestBuildFinalPathTraversalSecurity`, alle am unfixierten Code als tatsächlich fehlschlagend verifiziert |
| TEST-004 | `LyricsCache.cleanup()` (`utils/lyrics_cache.py`) war seit jeher ein No-Op-Stub (loggte nur Erfolg, löschte nichts) und wurde zudem nirgends aufgerufen — abgelaufene/korrupte/leere Lyrics-Cache-Dateien wuchsen unbegrenzt auf Disk | P1 | **behoben** (Phase 2) — echte Implementierung analog zu `MetadataCache.cleanup()` (löscht leere/korrupte/TTL-abgelaufene Dateien, gibt Stats-Dict zurück), angebunden über `GeniusClient.close()`. 6 Tests in `tests/test_lyrics_cache.py`, am unfixierten Stub als fehlschlagend verifiziert |
| ARTIST-001 | `ArtistNormalizer.normalize()` (`utils/artist_map.py`) wird in `ArtistProcessor.determine_best_artist` auf unaufgeteilte Collaboration-Strings angewendet (statt vorher `split_main_and_featuring` anzuwenden). Bei gemischten Trennzeichen (z.B. `"GReeeN & 1986zig feat. Bausa"`) werden alle Teile zu gleichrangigen Peers reduziert — der eigentliche Haupt-Artist-Anteil (`"1986zig"`) wird fälschlich zum Feature degradiert. Zusätzlich gehen stilisierte Schreibweisen verloren (`"GReeeN"` → `"Green"`) | P1 | **offen, bewusst nur charakterisiert** — ändert reale Artist-Zuordnungen (Regel 3), braucht repo-weite Prüfung aller `.normalize()`-Aufrufer vor einem Fix. 2 Tests in `tests/test_artist_normalizer.py::TestCollaborationArchitectureCharacterization` frieren das aktuelle Verhalten ein |
| GENRE-002 | `GenreMapper._compile_rules`/`_apply_rules` (`utils/genre_map.py`) erwartet einen Top-Level-Key `GENRE_RULES` in `mapping/genre_rules.yaml`, die echte Datei hat aber `keyword_rules`/`artist_rules`/`title_rules` — Schema-Mismatch. `self.rules` ist mit der echten Datei immer leer, die komplette Regex-Regel-Funktion für Genre-Erkennung ist seit jeher wirkungslos | P1 | **offen, bewusst nur charakterisiert** — Aktivierung würde reale Genre-Zuordnungen ändern (Regel 3), unklar ob Loader oder YAML die "richtige" Seite ist. 3 Tests in `tests/test_genre_mapper_advanced.py::TestRegexRulesSchemaMismatch` frieren das aktuelle Verhalten ein |
| GENRE-003 | `GenreMapper.get_main_genre()` (`utils/genre_map.py`) lowercased den Such-Key, aber `self.hierarchy`-Keys wurden aus `genre_hierarchy.yaml` unverändert (Title-Case) geladen → der Hierarchie-Fallback (`source="hierarchy"`) griff mit den echten Mapping-Daten praktisch nie, alles landete bei `source="normalized"` | P1 | **behoben** (Phase 2, Fortsetzung) — Hierarchie-Keys werden beim Laden jetzt lowercased (analog zu artist_map/channel_map). Dabei einen zweiten, durch den Case-Fix erst sichtbar gewordenen Bug mitgefixt: Top-Level-Genres liegen im Hierarchie-Dict als Key mit Wert `None` vor (kein Parent) — `.get(key, sub_genre)` hätte dafür faelschlich `None` statt des Fallbacks zurückgegeben; jetzt `.get(key) or sub_genre`. 4 Tests in `tests/test_genre_mapper_advanced.py::TestHierarchyCaseFix`, am unfixierten Code als fehlschlagend verifiziert |
| ARTIST-001-DEEP | Vertiefte Analyse zeigte: ein enger Fix nur in `ArtistProcessor._clean_and_normalize` reicht für ARTIST-001 NICHT aus. `enhanced_metadata_processor.py:401` splittet das Ergebnis von `determine_best_artist` ein zweites Mal via `split_main_and_featuring()` — diese zweite Stelle kann einen bereits korrekt behandelten zusammengesetzten Haupt-Artist (z.B. "GReeeN & 1986zig") nicht von echten Features unterscheiden und würde ihn erneut zerlegen. Ein isolierter Fix hätte zudem bei einfachen Faellen (z.B. "1986zig feat. GReeeN") den Feature-Artist komplett aus der Pipeline verschwinden lassen statt ihn nur falsch einzuordnen — eine neue, schlimmere Regression | P1 | **offen, bewusst zurückgestellt** — echte Lösung braucht eine Schnittstellenänderung (`determine_best_artist` müsste Haupt-/Feature-Artist getrennt zurückgeben, alle Aufrufer entlang der Pipeline anpassen), kein Nebenbei-Fix. Siehe ARTIST-001 für die bestehende Charakterisierung |
| DOC-001 | README dokumentiert System kaum | P1 | offen |
| LEGACY-001 | Legacy-/Kompatibilitätsschichten | P2 | offen |
| LEGACY-002 | `FilenameFixerTool.organize_file`/`process_directory`/`fix_and_move_file` (`utils/filenamefixer.py`) haben bestätigt null Aufrufer in Produktionscode (nur `build_final_path`/`move_to_library` werden von `enhanced_metadata_processor.py` genutzt) — vermutlich Rest einer älteren, abgelösten Pipeline | P2 | dokumentiert, nicht entfernt (Regel: Legacy-Code nicht ohne Beweis löschen) — keine Tests, da toter Code |

---

# 5. Sicherheits-Baseline

`config.py` lädt sensible Werte über `.env` bzw. Umgebungsvariablen. Das ist grundsätzlich die richtige Richtung. fileciteturn32file0L2-L2

### SEC-001

Bei der Navidrome-API muss geprüft werden, ob Request-Parameter mit Credentials vollständig geloggt werden.

**Ziel:**

```text
Passwort / Token
      ↓
niemals normaler Log-Output
```

Geplanter Regressionstest:

```python
def test_navidrome_credentials_are_not_logged():
    ...
```

---

# 6. Test-Baseline

Es existiert bereits ein `tests/`-Bereich. Die vorhandene `conftest.py` stellt beispielsweise eine `Config`-Fixture bereit. fileciteturn34file0L2-L2

Das bedeutet: Wir starten nicht bei null.

### Aber

`tests/test_genre_processor.py` enthält eine eigene `GenreProcessor`-Implementierung sowie Mock-Module. fileciteturn35file0L2-L2

Damit muss dieser Testbereich überprüft werden, bevor daraus echte Produktionsabdeckung abgeleitet wird.

---

# 7. Teststrategie

## Stufe 1 – Characterization Tests

Zuerst wird das aktuelle Verhalten eingefroren.

Beispiele:

```python
def test_artist_parser_current_behavior():
    ...

def test_genre_mapping_current_behavior():
    ...

def test_duplicate_detection_current_behavior():
    ...

def test_filename_generation_current_behavior():
    ...
```

Ziel:

> Der Test beschreibt, was das System heute tatsächlich macht.

Nicht:

> Der Test beschreibt, was wir glauben, dass es machen sollte.

---

# 8. P0-Testumfang

### Metadata

- Artist Extraction
- Title Extraction
- Genre Selection
- MetadataResult
- Cache Hit
- Cache Miss

### Duplicate

- gleiche URL
- gleiche YouTube-ID
- gleicher Artist/Titel
- Parser-Fallback
- vorhandene Library-Datei

### Files

- Filename
- Directory
- Extension
- Metadata Writing
- fehlende Datei
- bereits vorhandene Datei

### Security

- Credentials niemals im Log

---

# 9. P1-Testumfang

- YouTube Download
- Spotify Download
- Lyrics Fallback
- MusicBrainz Fallback
- Cover Fallback
- Loudness Failure
- Navidrome API
- Telegram Handler Routing

# 10. P2-Testumfang

- Admin
- Backup
- Restart
- Statistik
- Logging UI
- Migrationen

---

# 11. Testpyramide

```text
                 /\
                /E2E\
               /----\
              /Integration\
             /------------\
            /  Unit Tests  \
           /----------------\
```

Der Großteil der Tests soll schnell und isoliert sein.

Externe Dienste werden in Unit-Tests nicht real angesprochen.

Stattdessen:

```text
Core Logic
    │
    ├── External Adapter
    │
    └── Fake / Mock
```

---

# 12. Konfigurations-Baseline

`config.py` enthält unter anderem:

- Library
- Downloads
- Processing
- Fail
- Archive
- Metadata Cache
- Duplicate Cache
- Lyrics Cache
- Logs
- History
- Statistics
- Mapping
- Spotify
- Backups
- Secrets
- Feature Flags

Die Konfiguration ist damit ein zentraler Bestandteil des Systems. fileciteturn32file0L2-L2

Langfristiges Ziel:

```text
import config
```

soll möglichst wenige Seiteneffekte verursachen.

**Aber:** Das ist kein erster Refactoring-Schritt.

---

# 13. Mapping-Baseline

Artist- und Genre-YAML/JSON-Dateien beeinflussen das fachliche Verhalten.

Daher behandeln wir Mapping-Änderungen künftig wie Codeänderungen:

```text
Mapping ändern
     ↓
Test
     ↓
Review
```

Besonders relevant:

- Genre Aliases
- Genre Filters
- Genre Hierarchy
- Genre Rules
- Genre Overrides
- Artist Overrides
- Known Artists
- Channel Rules
- Auto-Learning

---

# 14. Cache-Baseline

Wichtige getrennte Cache-Bereiche:

```text
Metadata
Duplicate
Lyrics
History / Stats
```

Bei zukünftigen Änderungen müssen insbesondere diese Fälle getestet werden:

```text
Cache Hit
Cache Miss
Cache Invalid
Cache Stale
Cache Write Failure
```

---

# 15. Observability-Baseline

Das Projekt besitzt bereits umfangreiches Logging.

Das ist ein großer Vorteil für die weitere Entwicklung.

Ziel für kritische Abläufe:

```text
Input
 ↓
Decision
 ↓
Transformation
 ↓
External Call
 ↓
Fallback
 ↓
Output
```

Dabei dürfen keine Secrets in Logs gelangen.

---

# 16. Änderungsregeln

### Regel 1

Kein größerer Refactor ohne vorherige Tests.

### Regel 2

Bestehendes Verhalten nicht „nebenbei“ ändern.

### Regel 3

Mapping-Änderungen sind fachliche Änderungen.

### Regel 4

Fehler möglichst zuerst reproduzieren, dann beheben.

### Regel 5

Jeder kritische Bug-Fix bekommt einen Regressionstest.

### Regel 6

Dokumentation wird aktualisiert, wenn sich beobachtbares Verhalten oder öffentliche Schnittstellen ändern.

---

# 17. Empfohlene Reihenfolge

## Phase 0 – Baseline

**Jetzt abgeschlossen.**

- Architektur
- kritische Abläufe
- Risiken
- Teststrategie
- Dokumentationsgrundlage

## Phase 1 – Sicherheitsnetz

1. Logging-Secrets prüfen/entfernen
2. Produktionslogik-Tests herstellen
3. Metadata Characterization Tests
4. Duplicate Characterization Tests
5. File/Library Characterization Tests
6. erster reproduzierbarer Happy Path

## Phase 2 – Kernsystem

```text
Metadata
Duplicate
Filename
Cache
Genre
Artist
```

## Phase 3 – Integrationen

```text
YouTube
Spotify
MusicBrainz
Lyrics
Cover
Navidrome
Telegram
```

## Phase 4 – Refactoring

Erst danach:

```text
große Klassen
 ↓
kleinere Services
 ↓
klare Schnittstellen
 ↓
weniger Kopplung
```

---

# 18. Definition of Done

Eine Änderung ist grundsätzlich abgeschlossen, wenn:

```text
[ ] Verhalten verstanden
[ ] Änderung implementiert
[ ] Regressionstest vorhanden
[ ] relevante Tests grün
[ ] Logs geprüft
[ ] keine Secrets im Log
[ ] Dokumentation aktualisiert, falls nötig
```

---

# 19. Erfolgsdefinition

Das Ziel ist **nicht** blind 100 % Test-Coverage.

Das Ziel ist:

> **Vertrauen in die kritischen Geschäftsabläufe.**

Wir wollen letztlich sicher ändern können:

```text
Metadata
Genre
Artist
Duplicate Detection
Download
Library
```

ohne befürchten zu müssen, unbemerkt an einer anderen Stelle Funktionalität zu zerstören.

---

# 20. Baseline-Status

**MusicBot Engineering Baseline: ANGELEGT**

### P0
- [x] SEC-001 geprüft und behoben (Passwort-Masking in `api/navidrome_api.py` + Regressionstest)
- [x] TEST-001 teilweise behoben (`test_genre_processor.py` nutzt jetzt echte Produktionsklasse)
- [x] Metadata Characterization Tests — `AlbumProcessor` (14 Tests), `MetadataCacheHandler` (11 Tests, TEST-003 behoben), `EnhancedMetadataProcessor.process_single_track` (3 Tests, siehe E2E-001)
- [x] Duplicate Characterization Tests — 12 Tests, inkl. Fix + Regressionstest für den TEST-002-Bug (Library-Fallback war wirkungslos)
- [x] File/Library Characterization Tests — `FilenameFixerTool` (12 Tests: Single/Album/Podcast/Compilation-Pfade, fehlende Quelle, Kollisions-Umbenennung)
- [x] erster reproduzierbarer End-to-End-Happy-Path — siehe E2E-001

### Phase 2 — Kernsystem (Metadata/Duplicate/Filename/Cache/Genre/Artist)
- [x] SEC-002 gefunden und behoben (Path Traversal in `sanitize_filename()` + `FilenameFixerTool._ensure_within_roots()`, 11 Tests)
- [x] TEST-004 behoben (`LyricsCache.cleanup()`-Stub, 6 Tests)
- [x] Genre-Charakterisierung erweitert — Fuzzy-Matching, Regex-Regeln (GENRE-002), Hierarchie-Fallback (GENRE-003), MusicBrainz/Last.fm/Feature-Inferenz-Fallbacks (13 Tests in `test_genre_mapper_advanced.py` + `test_genre_processor.py`)
- [x] `ArtistNormalizer.normalize()` direkt charakterisiert, inkl. ARTIST-001 (11 Tests)
- [x] `StatistikService` (History/Stats-Cache) erstmals charakterisiert (15 Tests, vorher 0)
- [x] Legacy-Pfade in `FilenameFixerTool` dokumentiert statt getestet (LEGACY-002)
- [x] GENRE-003 behoben (Hierarchie-Case-Bug + davon verdeckter None-Fallback-Bug in `get_main_genre`)
- [x] CACHE-001 behoben (`get_url_hash` auf YouTube-bewusste Normalisierung umgestellt)
- [ ] GENRE-002 bewusst zurückgestellt — braucht Produktentscheidung (Rule-Engine bauen vs. YAML vereinfachen vs. tot lassen), kein mechanischer Fix
- [ ] ARTIST-001 bewusst zurückgestellt — vertiefte Analyse zeigte, dass ein enger Fix nicht ausreicht (siehe ARTIST-001-DEEP); braucht Schnittstellenänderung über mehrere Dateien
- [x] TEST-003 behoben — Video-ID-Index als stabiler Zwischenschlüssel zwischen Check (roh) und Store (bereinigt), siehe Risikotabelle

### P1
- [ ] Config Side Effects untersuchen
- [x] Cache-Verträge dokumentieren — Metadata-/Duplicate-/Lyrics-/History-Cache jetzt alle charakterisiert (siehe TEST-003/TEST-004/`test_statistik_service.py`)
- [ ] externe Adapter inventarisieren
- [ ] Download-Pipelines testen
- [ ] Navidrome Integration testen

### P2
- [ ] Legacy reduzieren
- [ ] große Orchestratoren refactoren
- [ ] Zielarchitektur schrittweise umsetzen

---

## Leitprinzip

> **Erst verstehen → dann testen → dann verbessern.**

Der MusicBot wird nicht neu geschrieben.

Er wird kontrolliert weiterentwickelt.
