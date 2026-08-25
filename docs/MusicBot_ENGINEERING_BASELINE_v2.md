# MusicBot Engineering Baseline v2

> Diese Baseline ist eine **Momentaufnahme**, kein Architekturaufsatz. Sie dient als
> Vergleichspunkt für zukünftige Änderungen: jeder größere Umbau muss erkennen lassen,
> ob er den hier festgehaltenen Zustand verbessert, verschlechtert oder unverändert lässt.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-08-25 |
| Git Commit (main) | `1dff4f2a8eec065a651a17c24faa892652910ec8` |
| Git Branch | `main` (lokal = `origin/main`) |
| Python-Version (Runtime) | 3.12.3 |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testlaufzeit | 76.02s |
| Vorherige Baseline | `docs/MusicBot_ENGINEERING_BASELINE.md` (2026-08-16, historisch, bleibt unverändert) |
| Zweck dieser Baseline | Referenzpunkt NACH vollständiger Spotify-Entfernung |

Es gibt kein `pyproject.toml`, kein `pytest.ini`/`setup.cfg`, kein Dockerfile,
kein `docker-compose.yml` und keine `.github/workflows/`. MusicBot läuft als
direkt gestarteter Python-Prozess (`python3 bot.py`), Dependencies werden über
`requirements.txt` (pip) verwaltet. Es existiert keine CI/CD-Pipeline — Tests
werden manuell/durch den Entwickler bzw. durch Claude Code ausgeführt.

---

## 2. Executive Summary

MusicBot ist ein Telegram-gesteuerter YouTube-Download- und Musikbibliotheks-Bot
mit Metadaten-Anreicherung (Artist/Genre/Lyrics/Cover/Tags) und Navidrome-Anbindung.

Der aktuelle Zustand ist **strukturell gesund**: die zentrale Download-Pipeline
wurde in ARCH-020 charakterisiert und für ausreichend gut entkoppelt befunden
(Ergebnis C — kein Refactor notwendig). Spotify wurde vollständig und sauber
entfernt (0 aktive Referenzen, keine Regression). Die Test-Suite ist mit 1039
bestandenen Tests breit, wenn auch mit ungleicher Tiefe je Bereich (siehe
Abschnitt 10). Es existieren 10 bekannte, im Detail verifizierte Testfehler
(Abschnitt 9) — keiner davon ist ein produktionskritisches P0/P1-Risiko.

Die größte reale Erkenntnis dieser Baseline-Erstellung: zwei genuine, bisher
unbekannte Logikfehler in `services/metadata/auto_learn.py` (Abschnitt 9,
AUTOLEARN-001/002) wurden beim Nachvollziehen der bekannten Testfehler
aufgedeckt — beide sind dokumentiert, keiner wurde im Rahmen dieser Baseline
behoben (Scope-Regel: dokumentieren, nicht beheben).

---

## 3. Current Product Scope

MusicBot unterstützt **aktuell ausschließlich YouTube** als Download-Quelle.

- Download: YouTube-Links (Single-Video und Playlist) über `yt-dlp`.
- Kein Spotify-Support mehr (vollständig entfernt, siehe Abschnitt 16).
- Kein Spotify-Podcast-RSS-Feature mehr (mit entfernt, da nur über Spotify-URLs
  erreichbar).
- YouTube-native Podcast-Erkennung bleibt bestehen: Kanäle aus bekannten
  Podcast-Kategorien werden über `PODCAST_DIR`-Routing (`utils/filenamefixer.py`)
  in einen eigenen Library-Ordner einsortiert — das ist unabhängig von der
  entfernten Spotify-RSS-Funktion und weiterhin aktiv.
- Metadatenanreicherung: Artist-Erkennung (YouTube-Parser + ArtistNormalizer +
  Auto-Learning), Genre (GenreProcessor mit MusicBrainz/Last.fm als Signalquellen,
  keine eigene Entscheidungsautorität der Clients), Lyrics (Genius), Cover
  (eingebettet, Last.fm-Pfad im Cover-Prozessor derzeit tot — siehe ARCH-021),
  Jahr/Album, Audio-Lautheitsnormalisierung (ffmpeg).
- Duplicate Detection über mehrere Ebenen (URL, YouTube-ID, Artist+Titel, Library-
  Fallback), extrahiert nach `services/duplicate/` (ARCH-018).
- Library-Organisation (Zielpfad/Dateiname/Tags) und Navidrome-Scan-Trigger.
- Telegram-Steuerung über RichMenu-System, Admin-Funktionen (Backup, User-
  Management, Bot-Restart), Statistik/Charts.

---

## 4. Current Architecture

Rekonstruiert aus tatsächlichen Imports/Call-Sites (nicht aus älteren Diagrammen
übernommen):

```text
Telegram
   ↓
ExtendedBot / bot.py
   ↓
RichMenuHandler (handlers/menu/)
   ↓
DownloadHandler (klassen/download_handler.py)
   ↓ handle_url() → _is_supported_download_url()-Allowlist (youtube.com/youtu.be/music.youtube.com)
services/downloader/download_utils.py
   ↓ enhanced_download_with_retry() — DER TATSÄCHLICHE ORCHESTRATOR
DownloadExecutor (services/downloader/download/download_executor.py)
   ↓ extract_info_async() — run_in_executor-gewrappt (kein Event-Loop-Block mehr)
yt-dlp
   ↓
Metadata Pipeline (läuft INNERHALB download_utils.py, nicht in DownloadHandler)
   ↓
EnhancedMetadataProcessor → Artist / Title / Genre / Lyrics / Cover / Album / Jahr
   ↓
Audio (ffmpeg, utils/audio_enhancer.py)
   ↓
Tags (TagWriter) / Filename (FilenameFixer) / Library
   ↓
DownloadHandler._process_single_download_result() — reiner Guard/Pass-Through (siehe Abschnitt 16)
   ↓
Navidrome (navidrome_scan_trigger.py)
```

**Wichtigste Abweichung vom in CLAUDE.md §4 dargestellten vereinfachten Fluss**
(bereits in ARCH-020 dokumentiert, dort nicht "repariert", da reine
Characterization-Aufgabe): `download_utils.py`, nicht `DownloadHandler`, ist der
reale Orchestrator der Metadata-Pipeline für YouTube. `DownloadHandler` ist eine
Application-Boundary (Telegram-Entgegennahme, Dispatch, Report-Versand), keine
Pipeline-Orchestrierungsinstanz.

---

## 5. Download Pipeline

YouTube-only, siehe Abschnitt 4. Ressourcen-Limits sind durchgesetzt (verifiziert
im aktuellen Code, nicht nur in Doku):

| Limit | Durchsetzung | Fundstelle |
|---|---|---|
| `MAX_CONCURRENT_DOWNLOADS` | `asyncio.Semaphore` um `handle_url()` | `klassen/download_handler.py:96-103` |
| `MAX_DURATION` | echter yt-dlp `match_filter`-Callback | `services/downloader/download/download_executor.py:74-141` |
| `MAX_PLAYLIST_ITEMS` | Trunkierung der `entries`-Liste | `services/downloader/download_utils.py:420-428` |
| Event-Loop-Blockierung | `run_in_executor` um alle blockierenden `extract_info`-Aufrufe | `download_executor.py:183-184, 244-247` |
| URL-Allowlist | `_is_supported_download_url()` (YouTube-Domains) | `klassen/download_handler.py:74, 525` |

Diese fünf Punkte waren Gegenstand eines früheren Sicherheits-/Stabilitäts-Plans
dieser Session (siehe `woolly-wishing-volcano`-Plan) und sind **vollständig
umgesetzt und getestet** (`test_download_url_validation.py`,
`test_download_concurrency_semaphore.py`, `test_playlist_max_items.py`,
`test_download_executor.py`). Der Plan ist damit erledigt/obsolet.

Retry-Mechanik existiert (`enhanced_download_with_retry()`,
`download_utils.py:283`, `for attempt in range(max_retries)`), hat aber **keine
dedizierte Testabdeckung** der eigentlichen Retry-/Backoff-Schleife (siehe
Abschnitt 10).

---

## 6. Metadata Pipeline

Reihenfolge (unverändert seit ARCH-020, nicht ohne Tests verändert):
Cache-Check → Parsing → Artist → Title → Genre → Lyrics → MusicBrainz → Cover →
Album/Jahr → Audio → Tags.

- Genre-Entscheidung liegt ausschließlich beim `GenreProcessor`; MusicBrainz-/
  Last.fm-/Genius-Clients sind reine Transport-Adapter ohne eigene
  Entscheidungsautorität (bestätigt in ARCH-012/019/021 — keine "Duplikation").
- `CoverProcessor._fetch_lastfm()` ist in Produktion **tot**, da
  `enhanced_metadata_processor.py:112` `CoverProcessor` ohne `lastfm_api_key`
  instanziiert (ARCH-021-Fund, dokumentiert, nicht behoben — außerhalb des
  Spotify-Removal-Scopes).
- Auto-Learning (`services/metadata/auto_learn.py`) hat zwei verifizierte
  Logikfehler, siehe Abschnitt 9 (AUTOLEARN-001/002).

---

## 7. Library Pipeline

`utils/filenamefixer.py` baut den Zielpfad (`build_final_path()`), inkl.
Sonderpfad für Podcast-Kanäle (`PODCAST_DIR`) und Kollisions-Suffixe. Path-
Traversal-Schutz über `_ensure_within_roots()` (Zeilen 339, 471, 488, 530) und
`sanitize_filename()` (`utils/helpers.py`). Duplicate Detection läuft über
`services/duplicate/` (`DuplicateDetector`, `DuplicateCache`), seit ARCH-018
sauber aus `klassen/` extrahiert (0 Reverse-Edges zu `handlers/`/`klassen/`,
AST-verifiziert in `docs/POST-ARCH-018_Services_Architecture_Audit.md`).

---

## 8. Test Baseline

Tatsächlich ausgeführt (nicht aus Dokumentation übernommen):

```text
python3 -m pytest tests/ -q
1039 passed, 10 failed, 5 warnings, 17 subtests passed
Laufzeit: 76.02s (0:01:16)
```

Kein `skipped`, kein `xfailed`/`xpassed`. Die 5 Warnings sind
`PytestUnknownMarkWarning` (unregistrierter `@pytest.mark.asyncio`-Marker, siehe
AUTOLEARN/RICHMENU-Infra-Befund unten) plus eine `PytestCollectionWarning`
(`handlers/test_menu_handler.py` enthält eine Klasse `TestMenuHandler` mit
`__init__`, die pytest fälschlich als Testklasse zu sammeln versucht — harmlos,
da eine separate `tests/test_test_menu_handler.py` existiert).

Referenzwert aus dem Auftrag (1039 passed / 10 failed / 0 neue Fehler) ist
**exakt bestätigt** durch eigene Ausführung.

---

## 9. Known Failures

Alle 10 Fehler wurden einzeln nachvollzogen (Code gelesen, isoliert ausgeführt,
Ursache verifiziert — nicht geraten).

| # | Test | Datei | Ursache | Klasse | Prod.-relevant | Priorität |
|---|---|---|---|---|---|---|
| 1 | `test_is_artist_known_from_auto_learned` | `test_auto_learn.py` | `_is_artist_known()` (`auto_learn.py:319`) prüft nur `auto_learned.values()` (kanonische Namen), nie `.keys()` (Roh-Aliase) → ein bereits gelernter Roh-Alias wird nicht als "bekannt" erkannt | Echter Logikfehler (neu identifiziert, AUTOLEARN-001) | Gering — Duplikat-Schutz beim Auto-Learning könnte denselben Alias erneut versuchen zu lernen, kein Datenverlust | P2 |
| 2 | `test_is_non_artist_channel[Music Channel]` | `test_auto_learn.py` | Regex `r"music$"` verlangt Endung "…music", trifft nicht auf "Music Channel" (endet auf "channel") | Test-/Implementierungs-Diskrepanz (Muster-Reihenfolge) | Gering — reale YouTube-Auto-Kanalnamen folgen "<Artist> - Topic"-Muster, das bereits separat abgedeckt ist | P3 |
| 3 | `test_is_non_artist_channel[Topic Channel]` | `test_auto_learn.py` | Gleiche Ursache wie #2 (`r"topic$"` vs. "Topic Channel") | Test-/Implementierungs-Diskrepanz | Gering | P3 |
| 4 | `test_load_auto_learned_artists_with_data` | `test_auto_learn.py` | `_load_auto_learned_artists()` (`auto_learn.py:429`) referenziert `self.mapping_dir` — dieses Attribut wird in `AutoLearnManager.__init__` **nie gesetzt**; `AttributeError` wird von einem breiten `except Exception` verschluckt, Methode liefert immer `{}` | Echter Logikfehler (AUTOLEARN-002), aber **0 Aufrufer im Produktionscode** (nur vom Test direkt aufgerufen) | Keine — toter Code-Pfad, alle anderen Methoden der Klasse berechnen `mapping_dir` korrekt lokal | P3 |
| 5 | `test_load_auto_learned_genres_with_data` | `test_auto_learn.py` | Identische Ursache wie #4, `_load_auto_learned_genres()` (`auto_learn.py:447`), ebenfalls 0 Aufrufer | Echter Logikfehler, toter Code | Keine | P3 |
| 6 | `test_learn_artist_same_as_canonical` | `test_auto_learn.py` | `learn_artist()` routet Identitäts-Mappings (raw==canonical) absichtlich nach `known_artists.yaml` und liefert bei erfolgreichem Schreiben `True` (Docstring bestätigt dieses Verhalten); Test erwartet `False`/No-Op | Veraltete Testerwartung (Design wurde nach Testerstellung geändert) | Keine — aktuelles Verhalten ist beabsichtigt laut Docstring | P3 |
| 7 | `TestRichMenuSystem::test_show_menu` | `test_suite.py` | `pytest-asyncio` ist nicht installiert (`requirements.txt` enthält es nicht); Testklasse ist eine einfache Klasse mit bloßen `async def`-Methoden + `@pytest.mark.asyncio`, kein `IsolatedAsyncioTestCase` | Infrastructure/Test Environment | Keine — `RichMenuSystem` hat anderweitige, laufende Sync-Testabdeckung (`test_rich_menu_system.py`, `test_rich_menu_handler.py`, `test_rich_menu_access_control.py`) | P3 |
| 8 | `TestRichMenuSystem::test_handle_callback_close` | `test_suite.py` | Gleiche Ursache wie #7 | Infrastructure/Test Environment | Keine | P3 |
| 9 | `TestRichMenuSystem::test_handle_callback_back` | `test_suite.py` | Gleiche Ursache wie #7 | Infrastructure/Test Environment | Keine | P3 |
| 10 | `TestMenuIntegration::test_full_navigation_flow` | `test_suite.py` | Gleiche Ursache wie #7 | Infrastructure/Test Environment | Keine | P3 |

**Seit wann bekannt:** Alle 10 waren bereits vor Beginn der Spotify-Entfernung
in dieser Session als "15 vorbestehende Fehler" bzw. nach vorherigen Fixes
(TitleCleaner-Fixes, PR #48) als "10 vorbestehende Fehler" stabil und
unverändert über mehrere volle Regressionsläufe hinweg (siehe
`docs/POST-ARCH-018_Services_Architecture_Audit.md` und die Spotify-Removal-
Regressionsläufe). Kein exaktes Einführungsdatum/-commit ermittelbar ohne
`git bisect` — außerhalb des Scopes dieser Baseline.

**Wichtig:** Keiner der 10 Fehler wurde im Rahmen dieser Baseline-Erstellung
behoben (Auftrag: dokumentieren, nicht reparieren). AUTOLEARN-001 und
AUTOLEARN-002 sind neue Erkenntnisse dieser Baseline und sollten als eigene,
kleine P2/P3-Tickets separat behandelt werden (siehe Abschnitt 14).

---

## 10. Critical Path Coverage

Bewertung nach tatsächlich vorhandenen Tests, keine erfundenen Prozentzahlen.

### Download

| Pfad | Status | Beleg |
|---|---|---|
| YouTube Single | COVERED | `test_download_executor.py`, `test_download_url_validation.py` |
| Download Failure | PARTIALLY COVERED | Fehlerpfade in `test_download_handler_process_single_download_result.py`, `test_download_result_reporter.py`; kein dedizierter Test für yt-dlp-Exception-Eskalation in `enhanced_download_with_retry()` |
| Retry | NOT COVERED | `for attempt in range(max_retries)` (`download_utils.py:283`) hat keine dedizierte Test-Datei/-Klasse; nur indirekt über `DownloadExecutor`-Einzelaufrufe berührt |
| Cache | COVERED | `test_metadata_cache_handler.py`, `test_download_utils_metadata_translation.py` (Hit/Miss, Video-ID-Index) |
| Concurrency | COVERED | `test_download_concurrency_semaphore.py` |

### Metadata

| Bereich | Status | Beleg |
|---|---|---|
| Artist | COVERED | `test_metadata_modules.py::TestArtistProcessor`, `test_artist_normalizer.py`, `test_split_main_and_featuring.py` |
| Title | COVERED | `test_metadata_modules.py::TestTitleCleaner`, `test_youtube_parser.py` |
| Genre | COVERED | `test_genre_processor.py`, `test_genre_mapper_advanced.py`, `test_genre_alias_characterization.py`, `test_genre_canonical_*` (3 Dateien), `test_genre_specificity_characterization.py` |
| Year | COVERED | `test_year_resolver.py` |
| Album | COVERED | `test_album_processor.py` |
| Cover | PARTIALLY COVERED | `test_cover_processor_validation.py` deckt Validierung ab; toter Last.fm-Pfad (Abschnitt 6) ist naturgemäß nicht funktional getestet |
| Lyrics | COVERED | `test_lyrics_processor.py`, `test_lyrics_cache.py`, `test_genius_client_fallback_chain.py` |
| Tags | COVERED | `test_tag_writer.py` |

### Library

| Bereich | Status | Beleg |
|---|---|---|
| Zielpfad | COVERED | `test_filenamefixer.py` |
| Dateiname | COVERED | `test_helpers_sanitize_filename.py` |
| Metadata Write | COVERED | `test_tag_writer.py` |
| Duplicate Detection | COVERED | `test_duplicate_handler.py` |
| Library Integrity | PARTIALLY COVERED | `test_mapping_yaml_integrity.py` prüft Mapping-Dateien, kein expliziter End-to-End-Integritätstest über echte Library-Verzeichnisstrukturen |

### Telegram

| Bereich | Status | Beleg |
|---|---|---|
| Commands | COVERED | `test_rich_menu_handler.py`, `test_test_menu_handler.py`, `test_text_workflow_dispatcher.py`, `test_channel_router.py` |
| Handler | COVERED | `test_rich_menu_system.py`, `test_rich_menu_access_control.py`, `test_navidrome_menu_handler.py`, `test_user_management_handler.py`, `test_backup_handler.py`, `test_bot_restart_handler.py`, `test_mugge_statistik_handler.py`, `test_enhanced_status_handler.py` |
| Error Handling | PARTIALLY COVERED | `test_enhanced_error_handler.py` deckt den Error-Handler ab; die 4 async-Testfälle in `test_suite.py` (RichMenuSystem) laufen wegen fehlendem `pytest-asyncio` nicht (siehe Abschnitt 9) |

### Infrastruktur

| Bereich | Status | Beleg |
|---|---|---|
| Config | COVERED | `test_config_import_side_effects.py` |
| External APIs | COVERED | `test_lastfm_client.py`, `test_musicbrainz_client.py`, `test_genius_client_fallback_chain.py`, `test_navidrome_api_characterization.py` |
| Timeouts | COVERED | `test_navidrome_api_timeout.py` |
| Security-sensitive Boundaries | COVERED | `test_download_url_validation.py` (URL-Allowlist), `test_logger_menu_path_traversal.py` (Path Traversal), `test_helpers_sanitize_filename.py` |

---

## 11. End-to-End-Reifegrad

```text
YouTube URL → Download → Metadata → Audio → Tags → Library
```

**Bewertung: ACCEPTABLE.**

Begründung: Jeder einzelne Pipeline-Schritt hat solide Unit-/Characterization-
Testabdeckung (siehe Abschnitt 10), und die Übersetzungsschicht zwischen
`MetadataResult` und den beiden verbleibenden YouTube-Aufrufstellen ist explizit
getestet (`test_metadata_result_translator.py`,
`test_download_utils_metadata_translation.py`). Es existiert jedoch **kein
echter End-to-End-Test**, der einen kompletten Durchlauf URL→Library mit
gefakten externen Diensten simuliert — die Absicherung entsteht aus der Summe
gut getesteter Einzelteile, nicht aus einem geschlossenen Integrationstest.
Zusätzlich ist die Retry-Schleife (Abschnitt 10) eine echte Lücke. Kein neuer
E2E-Test wurde hier ergänzt (außerhalb des Baseline-Scopes).

---

## 12. Architecture Health

**Bereits korrekte, aktuell gültige Architekturentscheidungen:**

| Grenze | Verantwortung | Owner | Konsumenten | Status |
|---|---|---|---|---|
| `handlers/` | Telegram-Präsentation, MarkdownV2, Callback-Handling | `RichMenuHandler` u.a. | Telegram-Update-Loop | Etabliert (ARCH-009), eingehalten |
| `services/` | Fachliche/technische Orchestrierung | `EnhancedMetadataProcessor`, `download_utils.py` | `handlers/`, `klassen/` | Etabliert, `download_utils.py` als realer Pipeline-Orchestrator bestätigt (ARCH-020) |
| `services/clients/` | Reine externe API-/HTTP-Adapter | `genius_client.py`, `lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py` | `services/metadata/` | Sauber eingehalten, keine Telegram-/Fachlogik-Vermischung (ARCH-021 bestätigt) |
| `services/duplicate/` | Duplicate-Detection-Kern | `DuplicateDetector`, `DuplicateCache` | `klassen/download_handler.py` | Sauber extrahiert (ARCH-018), 0 Reverse-Edges (AST-verifiziert) |
| `utils/` | Lokale Subprocess-/Shell-Wrapper ohne Netzwerk | `navidrome_scan_trigger.py`, `audio_enhancer.py`, `filenamefixer.py` | `services/`, `klassen/` | Eingehalten |
| Async-Isolation | Blockierende yt-dlp-Aufrufe laufen in Executor-Threads | `download_executor.py` | `download_utils.py` | Umgesetzt (Abschnitt 5) |
| Concurrency-Limits | `MAX_CONCURRENT_DOWNLOADS`/`MAX_PLAYLIST_ITEMS`/`MAX_DURATION` | `klassen/download_handler.py`, `download_executor.py`, `download_utils.py` | — | Umgesetzt und getestet (Abschnitt 5) |

**Größte Module** (reine Beobachtung, keine automatische Bewertung als Problem):

`handlers/enhanced_error_handler.py` (2506 Zeilen), `handlers/menu/rich_menu_system.py`
(1957), `handlers/enhanced_logger_menu_handler.py` (1753), `utils/artist_map.py`
(1219), `handlers/menu/rich_menu_handler.py` (1215), `services/metadata/enhanced_metadata_processor.py`
(1205). CLAUDE.md §19 nennt `DownloadHandler`, `RichMenuHandler`,
`RichMenuSystem`, `EnhancedMetadataProcessor` bereits explizit als bekannte
große Orchestratoren, die nicht ohne vorherige Verantwortlichkeits-Dokumentation
zerlegt werden sollen — das gilt unverändert. `enhanced_error_handler.py` ist
größer als alle vier, aber bislang nicht als Risikobereich dokumentiert; keine
konkreten technischen Auswirkungen (Kopplung, Bugs) identifiziert, daher hier
nur als Beobachtung, kein P-Eintrag.

**Import-/Dependency-Check:** alle in dieser Session (ARCH-018/020/021 und
Spotify-Entfernung) veränderten Module wurden per `import`-Ausführung und
AST-Scan auf zyklische/falsche Importe geprüft — keine gefunden. Kein
repo-weiter automatisierter Circular-Import-Checker (z. B. `pydeps`) ist im
Projekt eingerichtet; ein vollständiger Scan aller ~30k Zeilen Produktionscode
war außerhalb des Scopes dieser Baseline.

---

## 13. Security Baseline

Nur bereits bekannte Themen erneut geprüft, keine neuen Refactorings.

| Thema | Bewertung | Beleg |
|---|---|---|
| Path Traversal | PASS | `_ensure_within_roots()` (`filenamefixer.py`), `sanitize_filename()` (`helpers.py`), dediziert getestet (`test_logger_menu_path_traversal.py`, `test_helpers_sanitize_filename.py`) |
| URL Validation / Allowlist | PASS | `_is_supported_download_url()` seit dieser Session umgesetzt, getestet |
| Privilege Boundaries | ACCEPTABLE | Admin-Handler (`handlers/admin/`) nutzen eigene Access-Control (`test_rich_menu_access_control.py`), kein systemweites Rollenmodell — für ein Hobby-/Single-User-Projekt angemessen |
| Command Execution | PASS | Kein `shell=True` im gesamten Repo gefunden (repo-weiter Grep) |
| FFmpeg Invocation | PASS | Listen-Args statt Shell-String, `timeout=` bei allen `subprocess.run`-Aufrufen (`utils/audio_enhancer.py`) |
| External HTTP Calls | ACCEPTABLE | Über dedizierte Clients (`services/clients/`), Timeouts vorhanden (`test_navidrome_api_timeout.py`); kein repo-weiter systematischer Timeout-Audit aller HTTP-Aufrufe durchgeführt |
| Secrets / Credentials | PASS | Alle Secrets über `@property` aus `os.getenv()` in `config.py`, kein Secret-Logging gefunden (repo-weiter Grep nach `logger.*password/token/api_key/secret` ohne Redaction — keine Treffer) |
| Temporary Files | NEEDS REVIEW | Nicht im Detail neu geprüft in dieser Baseline (außerhalb des ursprünglich freigegebenen Scopes); frühere Session-Funde zu verwaisten Dateien bei fehlgeschlagener Playlist-Verarbeitung sind bekannt, aber nicht behoben (siehe `woolly-wishing-volcano`-Plan, "Nicht in Scope") |
| User-controlled filenames | PASS | Durchgängig über `sanitize_filename()`/`_ensure_within_roots()` |

Keine neuen Security-Refactors durchgeführt.

---

## 14. Technical Debt

### P0 — kritisch
Keine identifiziert.

### P1 — hoch
Keine identifiziert.

### P2 — mittel

| ID | Problem | Evidence | Impact | Nächster Schritt |
|---|---|---|---|---|
| AUTOLEARN-001 | `_is_artist_known()` prüft nur Alias-Ziele, nie Alias-Quellen | `auto_learn.py:371`, `test_auto_learn.py::test_is_artist_known_from_auto_learned` | Schwächerer Duplikat-Schutz beim Auto-Learning (kein Datenverlust, ggf. redundante Lernversuche) | Fix + Regressionstest (kleiner, isolierter Bugfix gemäß CLAUDE.md Regel 4/5) |
| RETRY-COVERAGE | `enhanced_download_with_retry()`s Backoff-Schleife hat keine dedizierte Testdatei | `download_utils.py:283`, Abschnitt 10 | Verhalten bei wiederholten yt-dlp-Fehlern ist nicht regressionsgesichert | Characterization-Test vor jeder künftigen Änderung an der Retry-Logik |

### P3 — niedrig

| ID | Problem | Evidence | Impact | Nächster Schritt |
|---|---|---|---|---|
| AUTOLEARN-002 | `_load_auto_learned_artists()`/`_load_auto_learned_genres()` referenzieren nicht existierendes `self.mapping_dir`, immer `{}`, aber 0 Produktions-Aufrufer | `auto_learn.py:429,447` | Keiner (toter Code) | Bei Gelegenheit entfernen oder korrekt anbinden — kein Zeitdruck |
| CHANNEL-PATTERN | `_is_non_artist_channel()`-Regex erkennt "Music Channel"/"Topic Channel" nicht (Musterreihenfolge) | `auto_learn.py:387-403`, Testfehler #2/#3 | Minimal (unrealistische Kanalnamen) | Test und/oder Regex bei Gelegenheit angleichen |
| STALE-TEST | `test_learn_artist_same_as_canonical` erwartet veraltetes Verhalten | `test_auto_learn.py:240`, `auto_learn.py:188-189` | Falsch-negativer Testfehler, kein Produktionsrisiko | Testerwartung an aktuelles (beabsichtigtes) Verhalten anpassen |
| PYTEST-ASYNCIO | `pytest-asyncio` fehlt, 4 Tests in `test_suite.py` können nicht laufen | Abschnitt 9, #7-#10 | Kein Produktionsrisiko, aber blinde Stelle in der Testausführung | `pytest-asyncio` zu `requirements.txt` (Dev-Dependency) hinzufügen oder Tests auf `IsolatedAsyncioTestCase` umstellen |
| PODCAST-INDEX-KEY | `Config.PODCAST_INDEX_API_KEY` hat seit der Spotify-/Podcast-RSS-Entfernung keinen Konsumenten mehr | Repo-weiter Grep, 0 Treffer außer der `@property`-Definition selbst | Keiner (totes Config-Feld) | Bei nächster Config-Bereinigung entfernen |
| LASTFM-COVER-DEAD | `CoverProcessor._fetch_lastfm()` ist tot (kein `lastfm_api_key` übergeben) | `enhanced_metadata_processor.py:112`, ARCH-021 | Keiner (Fallback-Pfad ungenutzt) | Bereits in ARCH-021 dokumentiert, bewusst nicht behoben |

---

## 15. ARCH Status

| ARCH | Thema | Status |
|---|---|---|
| ARCH-001 | Orchestrators-Extraktion | HISTORICAL |
| ARCH-003 | Services Phase 1 | HISTORICAL |
| ARCH-004 | P3 Orchestrierung | HISTORICAL |
| ARCH-005 | Temp Cleanup | HISTORICAL |
| ARCH-006–009 | Navidrome-Migration (mehrphasig) | HISTORICAL / COMPLETE (Navidrome aktiv im Einsatz) |
| ARCH-010 | Downloader Utils Migration | HISTORICAL |
| ARCH-011 | Downloader/Download-Analyse | HISTORICAL |
| ARCH-012–016 | Genre-Logik-Characterization (Alias/Specificity/Canonical) | HISTORICAL / COMPLETE |
| ARCH-017 | Download Audio Enhancement Characterization | HISTORICAL |
| ARCH-018 | Duplicate Detection Extraction | COMPLETE (verifiziert per `POST-ARCH-018_Services_Architecture_Audit.md`) |
| ARCH-019 | Genre Client Logic Characterization | HISTORICAL |
| ARCH-020 | Download Pipeline Characterization | CHARACTERIZED / COMPLETE (Ergebnis C, kein Refactor nötig), **erweitert** um Spotify-Entfernungs-Nachtrag |
| ARCH-021 | Genre-Client-Duplication Characterization (vormals versehentlich "ARCH-020", umbenannt) | COMPLETE |
| Spotify Removal | Vollständige Spotify-Elimination | COMPLETE |

Frühere Phasen (ARCH-001 bis ARCH-019) wurden für diese Baseline **nicht erneut
inhaltlich verifiziert** — ihr Status ist aus den vorhandenen Dokumenten
übernommen und als HISTORICAL markiert, sofern kein expliziter POST-Audit
("COMPLETE") vorliegt. Es gibt keinen ARCH-002-Dokument (Lücke in der
Nummerierung, nicht weiter untersucht — außerhalb des Scopes).

---

## 16. Recent Major Changes

### Spotify Removal (2026-08-25, PR #50)

**Entfernt:** `services/downloader/spotify_downloader.py`, `utils/podcast_rss_manager.py`,
`mapping/podcast_rss_feeds.yaml`, zugehörige Tests (`test_spotify_downloader.py`,
`test_podcast_rss_manager.py`), `handle_spotify_url()` in `DownloadHandler`,
Punkte D/E/G in `_process_single_download_result()`, `merge_metadata_result_into_dict()`,
Spotify-Config-Felder (`SPOTIFY_DOWNLOAD_DIR`, `SPOTIFY_CLIENT_ID/SECRET`,
`SPOTIFY_ENABLED`), Spotify-Erwähnungen in `CLAUDE.md`/`README.md`.

**Ergebnis:** 0 aktive Spotify-Referenzen (repo-weit erneut verifiziert für
diese Baseline, siehe Abschnitt 3-Prüfung), YouTube-Pipeline strukturell
unverändert, 1039 passed/10 failed (0 neue Fehler gegenüber Vor-Removal-Stand),
keine neuen Importzyklen. Details: `docs/MusicBot_ARCH-020_Download_Pipeline_Characterization.md`,
Abschnitt "Spotify-Entfernung".

### ARCH-018 — Duplicate Detection Extraction (PR #47)

Duplicate-Detection-Kern nach `services/duplicate/` extrahiert, 0 Reverse-Edges
zu `handlers/`/`klassen/`. Verifiziert in `docs/POST-ARCH-018_Services_Architecture_Audit.md`.

### ARCH-020 — Download Pipeline Characterization

`download_utils.py` als realer Pipeline-Orchestrator identifiziert (nicht
`DownloadHandler`). Ergebnis C: kein Refactor notwendig, aktuelle Struktur ist
bereits gut entkoppelt.

### Sicherheits-/Stabilitäts-Fixes (Event-Loop, URL-Allowlist, Ressourcen-Limits)

Vollständig umgesetzt und getestet, siehe Abschnitt 5.

### TitleCleaner-Fixes (PR #48)

4 Bugfixes in `services/metadata/title_cleaner.py` (Marketing-Tag-Regex,
Trennzeichen-Trim, "- Topic"-Suffix, Fallback-Reihenfolge bei zu kurzem
Ergebnis).

---

## 17. Current Risks

1. **Retry-Logik ungetestet** (Abschnitt 10/14, RETRY-COVERAGE) — künftige
   Änderungen an `enhanced_download_with_retry()` haben kein Sicherheitsnetz.
2. **Zwei echte Logikfehler in Auto-Learning** (AUTOLEARN-001/002) — geringes,
   aber reales Risiko für die Qualität der Artist-Erkennung über Zeit.
3. **Kein E2E-Test der Gesamtpipeline** — Vertrauen basiert auf der Summe von
   Unit-/Characterization-Tests, nicht auf einem geschlossenen Integrationstest.
4. **Keine CI/CD** — Regressionen werden nur bei manueller/durch Claude Code
   ausgelöster Testausführung sichtbar, nicht automatisch bei jedem Commit/Push.

---

## 18. Recommended Next Steps

Maximal 5, nach tatsächlichem Nutzen priorisiert — keine künstliche Roadmap.

1. **P2 — AUTOLEARN-001 beheben** (`_is_artist_known()` auch gegen Alias-Keys
   prüfen) + Regressionstest. Kleiner, isolierter Fix mit klarem Nutzen für die
   Datenqualität des Auto-Learnings.
2. **P2 — Characterization-Test für die Retry-Schleife** in
   `enhanced_download_with_retry()` ergänzen, bevor diese Logik das nächste Mal
   angefasst wird.
3. **P3 — `pytest-asyncio` einbinden** (Dev-Dependency), um die 4 derzeit
   nicht ausführbaren Tests in `test_suite.py` wieder nutzbar zu machen.

Keine weiteren Punkte werden hier empfohlen — die übrigen P3-Funde in
Abschnitt 14 sind bewusst niedrig priorisiert (totes Konfigurations-/
Codefeld, veraltete Testerwartung) und rechtfertigen aktuell keinen
eigenen Arbeitsschritt.

---

## 19. Definition of Baseline

> This document represents the known-good engineering state of MusicBot after
> the complete removal of Spotify support.

Bei Widersprüchen zwischen dieser Baseline und älteren Dokumenten gilt die in
diesem Dokument angewandte Priorität: aktueller Code > tatsächlich ausgeführte
Tests > aktuelle technische Dokumentation > historische Dokumentation.
`docs/MusicBot_ENGINEERING_BASELINE.md` (v1) bleibt als historische
Momentaufnahme vom 2026-08-16 unverändert bestehen und wird durch dieses
Dokument **nicht ersetzt, sondern abgelöst** als aktueller Referenzpunkt.

---

## Nachtrag (2026-08-25): AUTOLEARN-001 behoben

Direkt im Anschluss an die Baseline-Erstellung wurde der unter Abschnitt 9/14
dokumentierte Fund AUTOLEARN-001 behoben (explizite Freigabe für genau diesen
einen Punkt): `_is_artist_known()` (`services/metadata/auto_learn.py`) prüfte
in Schritt 4 nur `auto_learned.values()` (kanonische Namen), nie `.keys()`
(Roh-Aliase). Fix: Iteration über `auto_learned.items()`, Vergleich sowohl
gegen `raw_alias` als auch `canonical`. Der bereits vorhandene Test
`tests/test_auto_learn.py::TestAutoLearnManager::test_is_artist_known_from_auto_learned`
deckte den Fall bereits ab und dient als Regressionstest — kein neuer Test
nötig. Vollregression danach: **1040 passed, 9 failed** (genau die verbleibenden,
in Abschnitt 9 dokumentierten Punkte #2–#10, keine neue Regression).

Die Zahlen in Abschnitt 8/9 oben bleiben als Momentaufnahme zum
Baseline-Erstellungszeitpunkt unverändert stehen; dieser Nachtrag ist die
aktuelle Wahrheit. Alle übrigen P2/P3-Punkte aus Abschnitt 14 (RETRY-COVERAGE,
AUTOLEARN-002, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO, PODCAST-INDEX-KEY,
LASTFM-COVER-DEAD) waren zu diesem Zeitpunkt weiterhin offen.

## Nachtrag (2026-08-25): RETRY-COVERAGE geschlossen (Characterization-Test)

Freigabe für Empfehlung Nr. 2 aus Abschnitt 18: Characterization-Test für die
Retry-Schleife in `enhanced_download_with_retry()`
(`services/downloader/download_utils.py:224`) ergänzt —
`tests/test_download_utils_retry.py` (10 Tests). Reine
Verhaltens-Dokumentation, keine Code-Änderung an `download_utils.py`.

Dokumentiertes, dabei neu sichtbar gewordenes Detail: `DownloadError.__str__()`
formatiert als `"Download-Fehler [CODE]: details"`
(`services/downloader/errors.py`) — dieser Präfix landet unverändert in der
finalen `"Download nach N Versuchen fehlgeschlagen: …"`-Fehlermeldung. Der
generische-`Exception`-Zweig nennt im Gegensatz dazu die Versuchsanzahl gar
nicht in der Meldung ("Unerwarteter Fehler: …") — eine bestehende
Formatierungs-Inkonsistenz zwischen beiden Fehlerzweigen, dokumentiert, nicht
behoben (außerhalb des Scopes dieses Auftrags).

Abgedeckt: Erfolg im ersten Versuch (Single/Playlist), leere `entries`-Liste
fällt auf den Single-Pfad zurück, Retry nach `info=None`, Retry auch bei
Exceptions aus `_process_playlist_download()` (nicht nur aus
`extract_info_async()`), exponentielles Backoff (`2**attempt`), beide
Fehlermeldungsformate bei Erschöpfung aller Versuche, Default `max_retries=3`,
sowie der Randfall `max_retries=0` (kein einziger Versuch, sofortiger
Fehl-Return).

Vollregression danach: **1050 passed, 9 failed** (+10 gegenüber vorherigem
Stand, exakt die neuen Tests; die 9 bekannten Fehler unverändert, keine neue
Regression). RETRY-COVERAGE ist damit aus der offenen P2-Liste in Abschnitt 14
zu entfernen. AUTOLEARN-002, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO,
PODCAST-INDEX-KEY und LASTFM-COVER-DEAD waren zu diesem Zeitpunkt weiterhin
offen.

## Nachtrag (2026-08-25): PYTEST-ASYNCIO geschlossen

Freigabe für Empfehlung Nr. 3 aus Abschnitt 18: `pytest-asyncio` (1.4.0)
installiert und als Test-/Dev-Abhängigkeit in neuer Datei
`requirements-dev.txt` festgehalten (`requirements.txt` bleibt laut eigenem
Header-Kommentar ausdrücklich auf Produktionscode-Imports beschränkt, daher
eine separate Datei statt Vermischung). Kein Code-Umbau der betroffenen
Tests nötig — `TestRichMenuSystem`/`TestMenuIntegration` in `tests/test_suite.py`
nutzten bereits das Standard-`@pytest.mark.asyncio`-Muster, das ist mit
installiertem Plugin ohne weitere Konfiguration (kein `asyncio_mode` in
`pytest.ini` nötig) lauffähig. Die 4 zuvor blockierten Tests laufen jetzt
grün, die vorher 4 auftretenden `PytestUnknownMarkWarning` sind ebenfalls
verschwunden (Marker wird vom Plugin selbst registriert).

`README.md` korrigiert: der jetzt falsche Satz ("pytest-asyncio nicht
installiert") entfernt, Setup-Hinweis auf `requirements-dev.txt` ergänzt.
Die dort separat vorhandenen veralteten Test-Zahlen (359/15) wurden bewusst
NICHT angefasst — das ist eine vorbestehende, von diesem Auftrag unabhängige
Staleness, außerhalb des Scopes dieser Freigabe.

Vollregression danach: **1054 passed, 5 failed** (+4 gegenüber vorherigem
Stand, exakt die 4 vormals blockierten async-Tests; die verbleibenden 5
Fehler — AUTOLEARN-002 (×2 Subtests), CHANNEL-PATTERN (×2 Subtests),
STALE-TEST — unverändert, keine neue Regression). PYTEST-ASYNCIO ist damit
aus der offenen P3-Liste in Abschnitt 14 zu entfernen. AUTOLEARN-002,
CHANNEL-PATTERN, STALE-TEST, PODCAST-INDEX-KEY und LASTFM-COVER-DEAD sind
weiterhin offen und unverändert.

## Baseline Closure (2026-08-25)

The baseline initially recorded:

1039 passed
10 failed

All baseline-known failures and technical debt items were subsequently
resolved.

Final full regression:

1057 passed
0 failed

Resolved items:

- AUTOLEARN-001
- RETRY-COVERAGE
- AUTOLEARN-002
- CHANNEL-PATTERN
- STALE-TEST
- PYTEST-ASYNCIO
- PODCAST-INDEX-KEY
- LASTFM-COVER-DEAD

No new regression detected.

The repository is now considered a clean regression baseline.
