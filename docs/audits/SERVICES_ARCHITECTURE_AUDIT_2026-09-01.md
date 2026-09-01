# SERVICES Architecture Audit

Read-only Ist-Zustand-Audit von `services/` gegen die dokumentierte
Zielarchitektur (CLAUDE.md Abschnitt 4, `docs/MusicBot_ARCHITECTURE_EVOLUTION.md`,
`docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md`). Analysephase vor einer
eigentlichen Migration — keine Code-/Test-/Config-Änderung in diesem Audit.

## 1. Executive Summary

`services/` ist strukturell deutlich sauberer als der Rest des Repos vermuten
lässt: **keine** Telegram-Typen, **keine** `handlers/`-Rückwärtsimporte,
**keine** `klassen/`-Rückwärtsimporte wurden im gesamten Baum gefunden. Die
Schichtgrenze `handlers/klassen → services → clients` (CLAUDE.md Abschnitt 4)
wird import-seitig eingehalten. Die meisten async/sync-Grenzübertritte, die
in früheren Audits (AE-12, COVER-BLOCKING, INV-02) gefunden wurden, sind
bereits per `asyncio.to_thread()` sauber gelöst und wurden hier gegengeprüft
(SAFE VIA to_thread bestätigt für `MusicBrainzClient`, `LastFMClient`,
`GeniusClient`, `NavidromeAPI`, `CoverProcessor.get_cover_art()`,
`TagWriter.write_tags()`, `normalize_loudness()`).

Die verbleibenden echten architektonischen Probleme sind bekannt, klein an
Zahl und bereits größtenteils dokumentiert:

1. **`services/duplicate/cache.py` INV-01** (P2, Architekturentscheidung
   nötig, bereits als Out-of-Scope in `TECHNICAL_DEBT_CLEANUP_2026-09-01.md`
   protokolliert) — hier mit vollständiger Caller-/Kaskaden-Analyse
   (Abschnitt 22) neu belegt.
2. **DL-03/DL-05 (keine Fehlerklassifikation bei Retries)** — neuer,
   konkreterer Befund als bisher dokumentiert: `services/downloader/errors.py`
   definiert bereits eine 6-stufige Exception-Taxonomie
   (`InvalidURLError`, `FormatNotAvailableError`, `MetadataError`,
   `FileProcessingError`, `NetworkError`, `PermissionError`), die **im
   gesamten Repository nirgends geworfen wird** (0 Aufrufer außerhalb der
   Definition). Die Retry-Schleife (`download_utils.py:398-422`) fängt nur
   die Basisklasse `DownloadError` und `Exception` und behandelt beide
   identisch — die Infrastruktur zur Behebung existiert bereits, ist nur
   nie verdrahtet worden.
3. **`MUSICBRAINZ_RETRIES` totes Config** (P2/P3, bestätigt: 0 Aufrufer
   repoweit außerhalb der Definition in `config.py:414`).
4. **`process_single_track()`** (`EnhancedMetadataProcessor`) ist mit 908
   Zeilen (Zeile 248–1156) die mit Abstand größte einzelne Methode im
   gesamten `services/`-Baum — nicht als eigenständiges God-Class-Problem
   auf Klassenebene (die Klasse delegiert sauber an 8 Kollaborator-Klassen),
   aber als Complexity-Hotspot innerhalb einer Methode dokumentierenswert.

Kein Finding in diesem Audit erreicht P0. Zwei Findings sind P1
(Async-Kaskade-Risiko bei unkontrollierter Fehlklassifikation im
Download-Retry, siehe Abschnitt 20). Der Rest ist P2/P3.

## 2. Audit Scope

- Vollständiger `services/`-Baum (45 Python-Dateien, 14.304 Zeilen laut `wc -l`).
- Layer-Grenzen zu `handlers/`, `klassen/`, `utils/`, `config.py`, `scripts/`.
- Async/Sync-Grenzen, Side-Effects, externe Clients, Config-Zugriff,
  Error-Handling, Retry/Resilience, State/Cache/Persistence, globaler
  Zustand/Singletons, Testarchitektur, kritische Call-Graphen,
  God-Class-Kandidaten, Service-zu-Service-Kopplung.
- Explizit **nicht** Scope: `handlers/`, `klassen/`, `utils/`, `scripts/`
  im Detail (nur als Aufrufer/Ziel von `services/`-Grenzen betrachtet).

## 3. Repository Baseline

| Feld | Wert |
|---|---|
| HEAD (Audit-Start) | `b90f8dc60b490d783cba21cba306a6a6a6220a96` |
| Branch | `main` |
| Working Tree | 1 vorbestehend geänderte Datei: `mapping/artist_overrides.json` (nicht durch dieses Audit verursacht — kein laufender Bot-Prozess zum Zeitpunkt der Prüfung gefunden, `mtime` vor Audit-Start; Ursache nicht Teil des Scopes, unverändert belassen) |
| Referenzierte Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md` (Freeze 2026-09-01) |
| Referenzierter Track-A-Report | `docs/audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md` (1652 passed, 1 skipped, 0 failed zum Zeitpunkt des Merges von PR #91) |
| Teststatus (dieses Audit, `python3 -m pytest tests/ -q` auf HEAD `b90f8dc`) | **1652 passed, 1 skipped, 0 failed** (19 Subtests, Laufzeit 162.51s) — identisch zum Stand nach PR #91, keine Regression seit dem letzten Merge |

## 4. Current Services Inventory

45 Dateien in 5 fachlichen Gruppen. Vollständige Import-Liste wurde
repoweit erhoben (siehe Abschnitt 6 für Konsolidierung). Größte Dateien
(Zeilen):

| Datei | Zeilen | Vermutete Responsibility |
|---|---:|---|
| `metadata/enhanced_metadata_processor.py` | 1343 | Metadata-Pipeline-Orchestrierung (Haupt-Use-Case) |
| `downloader/download_utils.py` | 1016 | Download-Retry/Playlist/Single-Track-Orchestrierung (Modulfunktionen, nicht Klassenmethoden) |
| `metadata/auto_learn.py` | 1049 | Auto-Learning für Artist-/Genre-Mapping |
| `metadata/cover_processor.py` | 950 | Cover-Art-Beschaffung (6 externe Quellen) + Scoring + Cache |
| `metadata/genre_processor.py` | 825 | Genre-Bestimmung/-Priorisierung |
| `downloader/playlist_processor.py` | 604 | Playlist-Vorverarbeitung (Dominant-Artist-Erkennung) |
| `duplicate/classification.py` | 557 | Klassifikations-Datenmodelle + reine Funktionen (Duplicate Resolution) |
| `clients/genius_client.py` | 550 | Lyrics-Beschaffung, 4-Tier-Fallback (API→Scrape→Library) |
| `clients/musicbrainz_client.py` | 499 | MusicBrainz-Metadaten-Client |
| `duplicate/detector.py` | 394 | Duplicate-Detection-Orchestrierung |
| `duplicate/execution.py` | 395 | Ausführungspläne für Duplicate-Resolution |
| `duplicate/resolution.py` | 391 | Entscheidungslogik Duplicate-Resolution |
| `downloader/download/download_executor.py` | 376 | yt-dlp-Kapselung (Extract/Download) |
| `duplicate/cache.py` | 300 | JSON-Persistenz für Duplicate-Cache |
| `downloader/download/channel_router.py` | 329 | Kanal-/Special-Content-Routing |
| `downloader/download_result_reporter.py` | 297 | Ergebnis-Aufbereitung für Telegram-Antworten |
| `metadata/tag_writer.py` | 276 | ID3/Tag-Schreiben |
| `clients/navidrome_api.py` | 254 | Navidrome-REST-Client |

Restliche 27 Dateien: 50–250 Zeilen, überwiegend fokussierte
Einzelverantwortlichkeit (siehe Abschnitt 5).

Alle Dateien wurden auf Imports, `async def`/`def`, Filesystem-/Netzwerk-/
Subprocess-Zugriffe, Config-Zugriffe, Singleton-Muster und
services→services-Kopplung geprüft (Ergebnisse in Abschnitt 6–14
konsolidiert statt hier redundant pro Datei aufgelistet).

## 5. Responsibility Map

| Komponente | Fachliche Verantwortung | Technische Verantwortung | Kategorie |
|---|---|---|---|
| `clients/*` | keine (reine Adapter) | HTTP/Library-Kapselung zu Last.fm/MusicBrainz/Genius/Navidrome | CLEAR |
| `duplicate/cache.py` | keine | JSON-Persistenz für Duplicate-Einträge | CLEAR |
| `duplicate/detector.py` | Duplicate-Erkennung (URL/Content/Library) | Orchestriert `DuplicateCache` + `ArtistNormalizer` | CLEAR |
| `duplicate/classification.py`, `resolution.py`, `execution.py` | Klassifikation/Entscheidung/Ausführung für Duplicate-Resolution (Batch-Tool) | reine Datenmodelle + freie Funktionen, keine eigenen Klassen mit `__init__` | CLEAR (funktionaler Stil) |
| `metadata/enhanced_metadata_processor.py` | Haupt-Pipeline: Artist→Title→Genre→Lyrics→MB→Cover→Album/Jahr→Tags | Orchestriert 8 Kollaboratoren, Singleton | LEGITIMATE ORCHESTRATOR (Klasse), aber `process_single_track()` selbst SUSPICIOUS (908 Zeilen, siehe Abschnitt 18) |
| `metadata/{artist,title,genre,album,lyrics}_processor.py`, `tag_writer.py`, `cache.py` | je eine fachliche Teilverantwortung der Pipeline | jeweils eigene, injizierte Klasse mit klarer `__init__`-Signatur | CLEAR |
| `metadata/cover_processor.py` | Cover-Beschaffung aus 6 Quellen + Scoring | vollständig synchron, nutzt intern `ThreadPoolExecutor` (eigene Parallelisierung statt asyncio) | ACCEPTABLE COUPLING (bewusst synchron gehalten, Aufrufer wrappt korrekt per `to_thread`) |
| `metadata/auto_learn.py` | Automatisches Lernen von Artist-/Genre-Zuordnungen aus Historie | Datei-basierte Persistenz (`threading.Lock`) | CLEAR |
| `downloader/download_utils.py` | Download-Retry-Orchestrierung, Playlist-/Single-Pipeline | Modulfunktionen statt Methoden von `EnhancedDownloadProcessor` (nur Config/Stats-Holder) | ACCEPTABLE COUPLING (Struktur ist dokumentiert, Docstring-Diagramm Zeile 7-21) |
| `downloader/download/download_executor.py` | yt-dlp Extract/Download kapseln | `build_ydl_opts`, `extract_info`, `download_single_track` | CLEAR |
| `downloader/download/{cache_manager,channel_router,year_resolver,formatters}.py` | je fokussierte Teilaufgabe der Download-Pipeline | injizierte Kollaboratoren, DI-Pattern | CLEAR |
| `downloader/download/interfaces.py` | keine (reine Verträge) | `Protocol`-Definitionen (`DownloadCoordinator`, `CacheProvider`, `MetadataEnricher`, `TrackResultCollector`) | CLEAR — vorbildliche DI-Grenze |
| `downloader/download_artifact_cleanup.py` | Aufräumen verwaister Download-Artefakte | Start-Sweep + gezielter Cleanup | CLEAR |
| `downloader/playlist_processor.py` | Dominant-Artist-Erkennung für Playlists | — | CLEAR |
| `downloader/errors.py` | Fehlertaxonomie für Downloads | 7 Exception-Klassen | SUSPICIOUS — Taxonomie existiert, wird aber nirgends genutzt (0 `raise` außerhalb der Definition, siehe Abschnitt 12) |
| `statistik/*`, `statistik_service.py` | Statistik-Berechnung/-Export/-Charts/-Polling | `StatisticsCalculator` reine Berechnung, `ChartRenderer` mit `threading.Lock` für Matplotlib | CLEAR |

## 6. Dependency Graph

Konsolidierte, tatsächlich beobachtete Importrichtungen (repoweiter Grep):

```
handlers/*  ──┐
klassen/*   ──┼──> services/*  ──> services/clients/*  ──> (externe Libraries)
              │         │
              │         └──> utils/*, config (siehe Abschnitt 10)
              │
scripts/*   ──┘ (nur scripts/resolve_duplicates.py -> services/duplicate/*)
```

- `handlers/` → `services`: 4 Dateien (`navidrome_menu_handler.py`,
  `mugge_statistik_handler.py`, `duplicate_handler.py`, `menu/rich_menu_handler.py`).
- `klassen/` → `services`: 1 Datei (`download_handler.py`, importiert
  `DuplicateDetector`).
- `scripts/` → `services`: `scripts/resolve_duplicates.py` (Wartungstool,
  laut CLAUDE.md Abschnitt 4 legitim — reprocessing/scripts dürfen
  Produktions-Unterprozessoren wiederverwenden).
- `services/` → `handlers/`: **0 Treffer** (repoweiter Grep, keine
  Rückwärtsabhängigkeit gefunden).
- `services/` → `klassen/`: **0 Treffer**.
- `services/` → `scripts/`: **0 Treffer**.

**Keine zyklischen Dependencies gefunden.** Die Richtung ist durchgängig
sauber: `handlers/klassen → services → clients`.

## 7. Layer Boundary Audit

### services → handlers

`grep -rn "from handlers\|import handlers" services/` → 0 Treffer. **CLEAN.**

### services → Telegram

`grep -rn "telegram\|Update\|CallbackQuery|ContextTypes|ParseMode|Bot\b|Application" services/`
→ 18 Treffer, **alle** False Positives (Kommentare/Docstrings/String-Literale
wie `"c": "telegram-bot"` als API-Client-Kennung, `"User-Agent":
"MusicLibraryBot/2.0"`, Wörter wie „Update-ID“/„Status-Update“ in
Log-Nachrichten). Kein einziger echter Telegram-Typ-Import. **CLEAN.**

### services → klassen/

0 Treffer. **CLEAN.**

### services → utils

Aktiv genutzt: `utils.singleton.SingletonMixin`,
`utils.artist_map.ArtistNormalizer`/`ArtistConfig`, `utils.genre_map.GenreMapper`,
`utils.youtube_parser.parse_youtube_title`, `utils.filenamefixer.*`,
`utils.metadata_cache.MetadataCache`, `utils.lyrics_cache.LyricsCache`.
Alle legitim laut CLAUDE.md Abschnitt 4 (utils = wiederverwendbare
technische Hilfskomponenten). **CLEAN.**

### services → scripts

0 Treffer. **CLEAN.**

### handlers → services

Sauber gerichtet (services exportiert öffentliche Klassen über
`services/__init__.py`-Submodul-`__init__.py`s, handlers importieren
gezielt einzelne Klassen wie `DuplicateDetector`, `NavidromeAPI`,
`StatistikService`). Keine Layer-Verletzung gefunden.

**Gesamtergebnis Boundary Audit: keine einzige Verletzung gefunden.** Die
in CLAUDE.md Abschnitt 4 dokumentierte Zielarchitektur wird auf
Import-Ebene bereits vollständig eingehalten.

## 8. Async / Sync Audit

| Komponente | Methode | Async/Sync | I/O-Art | Bewertung |
|---|---|---|---|---|
| `MusicBrainzClient` | alle öffentlichen Methoden | async | Network | SAFE VIA to_thread (`musicbrainzngs.*` durchgängig per `asyncio.to_thread` gewrappt, Zeilen 59-64, 128-129, 306-307, 397-398) |
| `LastFMClient.fetch_metadata` | async | Network | SAFE VIA to_thread (Zeile 138) |
| `GeniusClient` | `_fetch_via_genius_api`, `_scrape_genius_lyrics_html`, `_fetch_lyrics` | async | Network/CPU (BeautifulSoup) | SAFE VIA to_thread (zentral über `_fetch_with_retry()`, Zeile 544) |
| `NavidromeAPI.make_request` | sync (intern) | Network (`requests.get`, Timeout aus Config, Default 15s) | — | SAFE — nie direkt aus async-Kontext aufgerufen; alle 4 öffentlichen async-Methoden (`check_connection`, `get_artists`, `get_now_playing`, `search`) wrappen `make_request` explizit per `asyncio.to_thread` |
| `CoverProcessor.get_cover_art` | sync (komplette Klasse ohne `async def`) | Network (bis zu 6 Quellen sequenziell, `timeout=8` je Quelle) | — | SAFE VIA to_thread am einzigen produktiven Call-Site (`enhanced_metadata_processor.py:726`, mit explizitem Kommentar „FINDING-1/COVER-BLOCKING“) |
| `EnhancedMetadataProcessor._determine_genre_with_stats` u.a. | async | — | delegiert an synchrone `GenreProcessor`-Methoden | SAFE (kein blockierendes I/O, nur CPU-lokale Mapping-Logik) |
| `TagWriter.write_tags` | sync | Filesystem (mutagen) | — | SAFE VIA to_thread (Aufrufer `enhanced_metadata_processor.py:892`, AE-12) |
| `enhanced_metadata_processor.py::normalize_loudness`-Aufruf | — | Subprocess (FFmpeg) | — | SAFE VIA to_thread (Zeile 840, AE-12) |
| `download_executor.py::extract_info`/`download_single_track` | sync-Kern, async Wrapper vorhanden (`extract_info_async`) | Network (yt-dlp) | — | SAFE VIA to_thread — **Hinweis:** dieser Fix war laut Plandokument (`woolly-wishing-volcano.md`) offenbar bereits umgesetzt (Methode `extract_info_async` existiert bereits im Code, Zeile 171), abweichend vom dort dokumentierten Ist-Zustand „ungewrappt“. Nicht Teil des freigegebenen Plans erneut geprüft — siehe Abschnitt 26 (Divergenz dokumentiert). |
| `services/duplicate/cache.py::_save_caches`/`add_entry` | **sync**, aus **sync** `DuplicateDetector`-Methoden aufgerufen, die wiederum **sync** aus `async def`-Handlern/`klassen/download_handler.py` aufgerufen werden | Filesystem (JSON, atomar seit INV-02) | — | **CONFIRMED EVENT LOOP BLOCK** (klein, unkritisch bei aktueller Cache-Größe) / **ARCHITECTURAL DECISION REQUIRED** — vollständige Analyse in Abschnitt 22 |
| `StatisticsCalculator.export_stats_to_json` | sync | Filesystem (JSON, atomar seit P3-05) | — | Aufrufer laut Grep: 0 in `handlers/` — aktuell nicht über Telegram erreichbar, daher kein Event-Loop-Risiko in Produktion |
| `PlayHistoryPoller` | async (Hintergrund-Task) | — | — | nicht vertieft geprüft (außerhalb der in Abschnitt 16 geforderten kritischen Call-Graphen) |

**Kein einziger CONFIRMED EVENT LOOP BLOCK mit tatsächlich messbarer
Auswirkung** wurde neu gefunden — alle früher gefundenen (COVER-BLOCKING,
AE-12, INV-01 in `test_menu_handler.py`) sind bereits gefixt. Der einzige
verbleibende Fall (`duplicate/cache.py`) ist seit Langem bekannt und bewusst
zurückgestellt (siehe Abschnitt 22).

## 9. Side Effects

| Service | FS | Network | Cache | DB | Process | Telegram |
|---|---:|---:|---:|---:|---:|---:|
| `clients/lastfm_client.py` | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `clients/musicbrainz_client.py` | ✗ | ✓ | ✓ (`TTLCache` in-memory) | ✗ | ✗ | ✗ |
| `clients/genius_client.py` | ✓ (`LyricsCache`) | ✓ | ✓ | ✗ | ✗ | ✗ |
| `clients/navidrome_api.py` | ✗ | ✓ | ✓ (`@lru_cache` auf `_get_navidrome_config`) | ✗ | ✗ | ✗ |
| `duplicate/cache.py` | ✓ (JSON) | ✗ | ✓ | ✗ | ✗ | ✗ |
| `duplicate/detector.py` | ✓ (File-Hash-Berechnung) | ✗ | ✓ (via `DuplicateCache`) | ✗ | ✗ | ✗ |
| `metadata/enhanced_metadata_processor.py` | ✓ | ✓ (via Kollaboratoren) | ✓ | ✗ | ✓ (via `normalize_loudness`) | ✗ |
| `metadata/cover_processor.py` | ✓ (Cache-Dateien) | ✓ (6 Quellen) | ✓ | ✗ | ✗ | ✗ |
| `metadata/auto_learn.py` | ✓ (YAML) | ✗ | ✗ | ✗ | ✗ | ✗ |
| `metadata/tag_writer.py` | ✓ (Audio-Tags) | ✗ | ✗ | ✗ | ✗ | ✗ |
| `downloader/download_utils.py` | ✓ | ✓ (via `DownloadExecutor`) | ✓ (via `CacheManager`) | ✗ | ✗ | ✗ |
| `downloader/download/download_executor.py` | ✓ | ✓ (yt-dlp) | ✗ | ✗ | ✗ | ✗ |
| `downloader/download_artifact_cleanup.py` | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `statistik/play_history_repository.py` | ✓ (JSON) | ✗ | ✗ | ✗ | ✗ | ✗ |
| `statistik/statistics_calculator.py` | ✓ (Export) | ✗ | ✗ | ✗ | ✗ | ✗ |
| `statistik/chart_renderer.py` | ✓ (PNG) | ✗ | ✗ | ✗ | ✗ | ✗ |
| `statistik_service.py` | ✗ | ✓ (via `NavidromeAPI`) | ✗ | ✗ | ✗ | ✗ |

Kein `services/`-Modul führt eine Datenbank-Persistenz durch (kein DB-Treffer
im gesamten Baum — JSON-Dateien sind durchgängig die Persistenzform).
Keine Telegram-Seiteneffekte in `services/` gefunden (konsistent mit
Abschnitt 7).

## 10. External Clients

| Client | Ort | Legitim laut Zielarchitektur? |
|---|---|---|
| `pylast` (Last.fm) | `services/clients/lastfm_client.py` | ✓ korrekt in `services/clients/` |
| `musicbrainzngs` | `services/clients/musicbrainz_client.py` | ✓ |
| `lyricsgenius`, `aiohttp`, `BeautifulSoup` | `services/clients/genius_client.py` | ✓ |
| `requests` (Navidrome REST) | `services/clients/navidrome_api.py` | ✓ |
| `requests` (Cover-Quellen: CoverArtArchive, Fanart, Apple Music, Deezer, YouTube-Thumbnail) | `services/metadata/cover_processor.py` | **Abweichung**: `requests`-Session-Handling liegt in `services/metadata/`, nicht in `services/clients/`. Kein `CoverArtClient`/`FanartClient` existiert als eigener Adapter. |
| `yt_dlp` | `services/downloader/download/download_executor.py` | **Abweichung**: kein `services/clients/ytdlp_client.py` — yt-dlp-Kapselung liegt direkt im Downloader-Submodul. |

**Bewertung der zwei Abweichungen:** Beide sind **DOCUMENTATION GAP /
ACCEPTABLE LEGACY**, keine harte `ARCHITECTURAL VIOLATION`: CLAUDE.md
Abschnitt 4 listet `services/clients/` explizit nur mit den vier
tatsächlich dort vorhandenen Modulen (`genius_client.py`,
`lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py`) — die
Konvention wurde nie auf Cover-Quellen oder yt-dlp ausgeweitet. Beide
Stellen kapseln ihre externe Kommunikation bereits intern sauber
(`CoverProcessor._build_session()`/`_get()`/`_fetch_raw()`,
`DownloadExecutor.build_ydl_opts()`/`extract_info()`) — die Business-Logik
vermischt sich nicht mit rohen Requests, nur die Modul-**Platzierung**
weicht von der Konvention ab. Kein Credential-Leak-Risiko gefunden
(Navidrome-Credentials werden bereits maskiert geloggt, `_scrub_credentials()`
in `navidrome_api.py` und `cover_processor.py`).

Session/Retry-Handling: `CoverProcessor._build_session()` nutzt
`HTTPAdapter` + `urllib3.util.retry.Retry` — nur hier im gesamten
`services/`-Baum ist echte HTTP-Retry-Infrastruktur (Connection-Level)
verdrahtet, unabhängig von der Retry-Schleife in `download_utils.py`.

## 11. Config Boundary

| Muster | Vorkommen |
|---|---|
| `from config import Config` (Modul-Top-Level, direkter globaler Zugriff) | `clients/lastfm_client.py`, `clients/musicbrainz_client.py`, `clients/navidrome_api.py`, `clients/genius_client.py`, `metadata/enhanced_metadata_processor.py`, `downloader/downloader.py`, `downloader/download_utils.py`, `statistik_service.py` (8 Dateien) |
| `Config` als Konstruktor-Parameter (Dependency Injection) | `duplicate/detector.py::__init__(self, config: Config, ...)` |
| Kein direkter `config`-Zugriff, alles injiziert | `duplicate/classification.py`, `duplicate/resolution.py`, `duplicate/execution.py`, `metadata/{artist,title,lyrics,album}_processor.py`, `metadata/tag_writer.py`, `metadata/cache.py`, `downloader/download/*` (Kollaboratoren erhalten `config` als Parameter, kein globaler Import) |

**Bewertung:** Gemischtes Bild — der überwiegende Teil der kleineren,
gut testbaren Kollaboratoren (Abschnitt 5, „CLEAR“) erhält Config bereits
injiziert. Die 8 Dateien mit direktem `from config import Config` sind
überwiegend genau die Stellen, die laut CLAUDE.md Abschnitt 13 („`import
config` soll möglichst wenige Seiteneffekte haben“) das langfristige
Risiko tragen — jedoch **kein neuer Fund**: dies ist bereits als
projektweites Langfristziel dokumentiert, keine services-spezifische
Verschärfung.

**Tote Config, geprüft:**

| Wert | Status | Evidenz |
|---|---|---|
| `MUSICBRAINZ_RETRIES` (`config.py:414`) | **CONFIRMED DEAD** | 0 Treffer für `MUSICBRAINZ_RETRIES` im gesamten Repo außerhalb der Definitionszeile selbst (repoweiter Grep, `services/`, `handlers/`, `klassen/`, `utils/`, `scripts/`, `tests/`) |
| `DOWNLOAD_TIMEOUT`, `YTDL_BASE_OPTIONS` | bereits entfernt (PR #88, AE-05) | siehe `TECHNICAL_DEBT_CLEANUP_2026-09-01.md` |
| `DOWNLOAD_RETRY_COUNT`, `DOWNLOAD_RETRY_DELAY` (`config.py:354-355`) | **ACTIVE** (vermutet, nicht in diesem Audit bis zum Call-Site verifiziert — außerhalb des vertieften Scopes; `max_retries`/Backoff in `download_utils.py` scheinen eigene lokale Defaults statt dieser Config-Werte zu nutzen, siehe `2**attempt`-Hardcoding Zeile 411/422) | **UNKNOWN**, ob `DOWNLOAD_RETRY_COUNT` tatsächlich als `max_retries`-Quelle dient — nicht abschließend verifiziert, hier ehrlich als offene Frage markiert statt vermutet |

## 12. Error Boundary

**Kernbefund:** `services/downloader/errors.py` definiert eine vollständige
Fehlertaxonomie:

```
DownloadError (Basis)
├── InvalidURLError
├── FormatNotAvailableError
├── MetadataError
├── FileProcessingError
├── NetworkError
└── PermissionError
```

Evidenz für Nichtnutzung (repoweiter Grep nach `<Klasse>(` als
Konstruktor-Aufruf, außerhalb der Definitionsdatei und `tests/`):

```
InvalidURLError(       → 0 Treffer
FormatNotAvailableError( → 0 Treffer
MetadataError(          → 0 Treffer
FileProcessingError(    → 0 Treffer
NetworkError(           → 0 Treffer
PermissionError(        → 0 Treffer
```

Die Retry-Schleife in `download_utils.py:398-422` (`enhanced_download_with_retry`)
fängt:

```python
except DownloadError as e:      # Zeile 398 — nur Basisklasse
    ...
except Exception as e:          # Zeile 411 — alles andere
    ...
```

Beide Zweige loggen unterschiedlich ausführlich (der `Exception`-Zweig mit
`exc_info=True`, `DownloadError`-Zweig ohne), aber **beide retryen
identisch** (gleicher exponentieller Backoff `2**attempt`, gleiche
Abbruchbedingung `attempt == max_retries - 1`). Es gibt keinen Code-Pfad,
der z. B. bei einer (hypothetischen) `PermissionError` sofort abbricht statt
3× erfolglos zu retryen.

**Broad `except Exception`-Verteilung** (Abschnitt „Findings NOT to fix“,
Abschnitt 25): am dichtesten in `metadata/auto_learn.py` (13),
`metadata/cover_processor.py` (11), `metadata/enhanced_metadata_processor.py`
(9) — durchgängig mit Logging (kein stilles Verschlucken beobachtet,
Stichproben in `cover_processor.py`/`cache.py` bestätigen Log-Aufruf in
jedem `except`-Block). Keine tiefere Klassifikation der breiten
`except Exception`-Blöcke war im Rahmen dieses Audits (Zeitbudget) für alle
~90 Vorkommen einzeln möglich — als **UNKNOWN im Detail** markiert, wo nicht
stichprobenartig verifiziert.

## 13. Retry / Resilience

| Ort | Was wird retried | Klassifikation? | Backoff | Bewertung |
|---|---|---|---|---|
| `download_utils.py::enhanced_download_with_retry` (Zeile 256-424) | ganzer Download-Versuch (Extract+Download+Processing) | **Nein** — `DownloadError` und `Exception` identisch behandelt | `2**attempt` Sekunden, `max_retries` (Default aus Funktionssignatur, nicht in diesem Audit bis zur Aufrufstelle zurückverfolgt) | **DL-03**: keine Unterscheidung zwischen permanent (falsche URL, kein Format) und transient (Netzwerk-Timeout) — verschwendet Zeit/Ressourcen bei garantiert erfolglosen Wiederholungen |
| `clients/genius_client.py::_fetch_with_retry` (Zeile 518-544) | einzelne Genius-API-Calls | Nutzt `tenacity.AsyncRetrying` mit `wait_exponential`/`stop_after_attempt` — **Bibliotheks-Retry**, keine eigene Fehlklassifikation sichtbar in den gelesenen Zeilen | tenacity-gesteuert | Nicht vertieft geprüft (außerhalb des Fokus DL-03/DL-05) |
| `cover_processor.py::_build_session` | HTTP-Connection-Level-Retry via `urllib3.util.retry.Retry` | Ja — `urllib3.Retry` klassifiziert bereits nach HTTP-Status/Connection-Fehlern (Standardverhalten der Bibliothek) | urllib3-gesteuert | **SAFE** — dies ist die einzige Stelle im Baum mit bereits korrekt granularer Retry-Klassifikation |
| `services/duplicate/cache.py` | kein Retry (einmaliger synchroner Schreibversuch, atomar seit INV-02) | n/a | n/a | n/a |

**DL-05** (Metadata-Fehler wird unnötig retried) konnte in diesem Audit
**nicht eigenständig als separater Code-Pfad lokalisiert** werden — es
handelt sich vermutlich um denselben Mechanismus wie DL-03 (ein
`MetadataError` innerhalb von `process_single_track()` propagiert nach oben
und würde ebenfalls über den generischen `except Exception`-Zweig in
`enhanced_download_with_retry()` retried, da `MetadataError` selbst nie
geworfen wird und ein natürlicher Python-Fehler in der Metadaten-Pipeline
somit in den `Exception`-Zweig fällt). Als **UNKNOWN (nicht separat
verifiziert)** markiert statt geraten.

## 14. State / Cache / Persistence

| Service | State-Ort | Owner | Lifecycle | Source of Truth vs. Cache |
|---|---|---|---|---|
| `services/duplicate/cache.py` (`DuplicateCache`) | `self.url_cache`/`self.content_cache` (In-Memory-Dict, aus JSON geladen) | `DuplicateDetector`-Instanz | Lebt so lange wie die injizierende `DuplicateDetector`-Instanz (pro Handler-Konstruktion neu, siehe Abschnitt 15) | **Cache**, nicht Source of Truth — echte Quelle ist die Library selbst (`check_library_duplicate()` in `detector.py` prüft zusätzlich das Filesystem) |
| `utils.metadata_cache.MetadataCache` (via `metadata/cache.py::MetadataCacheHandler`) | Datei-basiert | injiziert | — | Cache (Source of Truth: erneute Pipeline-Ausführung) |
| `metadata/auto_learn.py` (`AutoLearnManager`) | YAML-Datei + `threading.Lock` | Singleton-artig (nicht `SingletonMixin`, aber Instanz meist einmalig konstruiert über `EnhancedMetadataProcessor`) | — | **Source of Truth** für gelernte Artist-/Genre-Zuordnungen (kein Fallback-Ursprung außer manueller Mapping-Pflege) |
| `statistik/play_history_repository.py` | JSON pro Nutzer | injiziert | — | Source of Truth für Play-History |
| `services/downloader/download_utils.py::EnhancedDownloadProcessor` | `SingletonMixin` | global (Prozess-weit) | siehe Abschnitt 15 | Reiner Stats-/Config-Holder, kein fachlicher State |
| `metadata/enhanced_metadata_processor.py::EnhancedMetadataProcessor` | `SingletonMixin` | global (Prozess-weit) | siehe Abschnitt 15 | Orchestriert zustandslose Pipeline-Aufrufe, `self.processing_stats` ist der einzige mutable State |

Cache-Invalidierung geprüft für `DuplicateCache`: `invalidate_entry()`
existiert in `DuplicateDetector` (Zeile 380 laut Grep), Details nicht
tiefer verifiziert (außerhalb Kernfokus dieses Audits, bereits in
CLAUDE.md Abschnitt 15 als P0-Bereich mit eigenem Testkatalog abgedeckt).

## 15. Global State

| Fund | Bewertung | Begründung |
|---|---|---|
| `EnhancedDownloadProcessor(SingletonMixin)` | **RISK** (bekannt, nicht neu) | Prozessweiter Singleton — Test-Isolation wird laut `tests/conftest.py::reset_singletons` bereits per Autouse-Fixture zwischen Tests zurückgesetzt (in dieser Session mehrfach als Ursache für reale Mapping-Datei-Korruption identifiziert, siehe `[[test-isolation-mapping-corruption]]`-Klasse von Bugs — hier nur als bestehendes, bereits mitigiertes Risiko bestätigt, kein neuer Fund) |
| `EnhancedMetadataProcessor(SingletonMixin)` | **RISK** (bekannt, mitigiert) | Gleiches Muster/gleiche Mitigation wie oben |
| `NavidromeAPI._get_navidrome_config` mit `@lru_cache(maxsize=1)` | **ACCEPTABLE** | Reine Config-Snapshot-Memoization, kein mutabler State, kein Test-Isolation-Risiko beobachtet (Config wird pro Prozess einmal gelesen, nicht zwischen Tests geteilt sofern `Config`-Klasse selbst gepatcht wird — **UNKNOWN**, ob `lru_cache` das `conftest.py`-Monkeypatching der `Config`-Klasse zwischen Tests unterlaufen kann, nicht verifiziert) |
| `services/statistik/chart_renderer.py::_render_lock = threading.Lock()` (Klassenebene) | **SAFE** | Bewusst gesetzter Lock für nicht-threadsicheren Matplotlib-Zugriff, `matplotlib.use("Agg")` explizit gesetzt |
| `metadata/auto_learn.py::Lock` (`threading.Lock`, Instanzebene laut Import `from threading import Lock`) | **ACCEPTABLE** | Schützt Datei-Schreibzugriff, adressiert laut Code-Kommentar (Zeile 156) explizit eine früher entdeckte Lost-Update-Race |

**Ein potenziell relevanter, nicht abschließend geklärter Punkt:**
`NavidromeAPI._get_navidrome_config` + `@lru_cache(maxsize=1)` — sollte in
einer künftigen, gezielten Prüfung verifiziert werden, ob dies mit dem in
`tests/conftest.py` etablierten Config-Patching-Muster kollidieren kann.
Als **UNKNOWN** markiert, kein bestätigter Fund.

## 16. Test Architecture

Grobe Testdatei-Zuordnung nach Namenskonvention (132 Testdateien gesamt in
`tests/`):

| Servicebereich | ungefähre Anzahl zugehöriger Testdateien |
|---|---:|
| Metadata (`metadata`, `genre`, `artist`, `cover`, `lyrics`, `album`, `tag_writer`) | 38 |
| Downloader (`download*`) | 17 |
| Duplicate (`duplicate*`) | 15 |
| Clients (`lastfm`, `musicbrainz`, `genius`, `navidrome`) | 10 |
| Statistik (`statistik`, `statistics`, `chart`, `play_history`) | 9 |

Dies ist eine **Heuristik über Dateinamen**, keine verifizierte
Coverage-Messung — als solche gekennzeichnet, nicht als exakte Zahl
missverständlich.

Beobachtete Testarten (Stichproben aus den in dieser Session zuvor
gelesenen Testdateien, nicht erneut vollständig durchgegangen):

- **Unit Tests**: durchgängig vorhanden für alle größeren Klassen.
- **Characterization Tests**: mehrfach explizit benannt (`*_characterization.py`
  existiert z. B. für `navidrome_api`, Genre-Alias-Verhalten).
- **Concurrency/Race-Tests**: mindestens 2 bekannte Beispiele aus dieser
  Session (`test_filenamefixer_move_to_library_toctou.py` mit echten
  `threading.Thread`s; `test_test_menu_handler_event_loop_blocking.py` mit
  Heartbeat-Test).
- **Boundary-Tests explizit für services→services-Kopplung**: nicht
  gefunden — kein Testname deutet auf einen dedizierten
  Architektur-/Import-Boundary-Test hin (z. B. „kein `services/` importiert
  `handlers/`“ ist aktuell nicht automatisiert abgesichert, nur durch
  dieses manuelle Audit bestätigt).

**Finding (P3):** Es existiert kein automatisierter Test, der die in
Abschnitt 7 bestätigte Layer-Grenze (`services` importiert nie
`handlers`/`klassen`) dauerhaft absichert — ein zukünftiger Import könnte
unbemerkt eingeführt werden. Empfehlung siehe Abschnitt 21/23.

## 17. Critical Call Graphs

### EnhancedMetadataProcessor

```
downloader/download_utils.py::_process_track_metadata()
  → EnhancedMetadataProcessor.process_single_track()   [async, 908 Zeilen]
      → cache_handler.check()                          [Cache-Hit-Pfad: Return]
      → artist_normalizer.normalize()                   [utils/]
      → parse_youtube_title()                            [utils/]
      → artist_processor / title_cleaner / genre_processor  [sync Kollaboratoren]
      → await asyncio.to_thread(cover_processor.get_cover_art)  [SAFE]
      → album_processor.determine_album_info()
      → await asyncio.to_thread(normalize_loudness)      [SAFE, AE-12]
      → await asyncio.to_thread(tag_writer.write_tags)    [SAFE, AE-12]
      → cache_handler.store()
  ← MetadataResult
```

Error-Pfad: `except asyncio.CancelledError` explizit behandelt (DL-01,
`library_path`/`original_path` vorab gebunden) — bestätigt bereits
dokumentiertes Verhalten, kein neuer Fund.

### DownloadExecutor

```
download_utils.py::enhanced_download_with_retry()
  → _process_playlist_download() / _process_single_download()
      → DownloadExecutor.extract_info() / extract_info_async()
      → DownloadExecutor.download_single_track()
          → yt_dlp.YoutubeDL(...).extract_info(download=True)
          → find_downloaded_file()
```

Retry-/Fallback-Pfad: siehe Abschnitt 13 (DL-03).

### DuplicateDetector

```
klassen/download_handler.py (async handle_url())
  → self.duplicate_detector.check_for_duplicates()   [SYNC, Zeile 333]
      → DuplicateCache.check_url_duplicate() / check_content_duplicate()  [SYNC]
      → check_library_duplicate()                     [SYNC, Filesystem]
  ...
  → self.duplicate_detector.register_download()      [SYNC, Zeile 515 + 595]
      → DuplicateCache.add_entry()
          → DuplicateCache._save_caches()              [SYNC, atomarer JSON-Write]
```

Vollständige Analyse der Async-Kaskade in Abschnitt 22.

### LastFM Client / Navidrome Client

Bereits in Abschnitt 8 (Async/Sync-Tabelle) als Call-Graph-Kurzform
abgedeckt — beide durchgängig SAFE VIA to_thread.

### StatisticsCalculator

```
(kein Aufrufer in handlers/ gefunden — export_stats_to_json() aktuell
 über Telegram nicht erreichbar)
statistik_service.py → StatisticsCalculator.generate_stats() [SYNC]
```

### CoverProcessor

Bereits in Abschnitt 8/17 (EnhancedMetadataProcessor-Graph) abgedeckt.

## 18. Orchestrator / God-Class Analysis

| Klasse | Responsibility Count | Dependency Count | Public Methods | Bewertung |
|---|---:|---:|---:|---|
| `EnhancedMetadataProcessor` | 1 (Pipeline-Orchestrierung), delegiert an 8 Kollaboratoren | 8 injizierte Kollaboratoren + `ArtistNormalizer`, `GenreMapper`, `MetadataCache` | ~7 öffentliche Methoden | **LEGITIMATE ORCHESTRATOR** auf Klassenebene. Aber: `process_single_track()` selbst ist mit 908 Zeilen (Zeile 248-1156) die größte Einzelmethode im gesamten `services/`-Baum, mit tief verschachtelter Fehlerbehandlung und ~16 nummerierten Pipeline-Schritten inline statt als eigene Methoden extrahiert. **SUSPICIOUS auf Methodenebene** — CLAUDE.md Abschnitt 19 verbietet automatisches Zerlegen ohne vorherige Tests/Dokumentation; hier explizit **nicht** als Migrationsempfehlung mit Umsetzung, sondern nur als dokumentierter Fund. |
| `DownloadExecutor` | 1 (yt-dlp-Kapselung) | gering (Logger, Config als Parameter) | ~5 | **HIGH COHESION SERVICE** — kein Finding. |
| `DuplicateDetector` | 1 (Duplicate-Erkennung), klar aufgeteilt in `check_for_duplicates`/`check_library_duplicate`/`register_download` | `DuplicateCache`, `ArtistNormalizer` | ~7 | **HIGH COHESION SERVICE** — kein Finding. |
| `EnhancedDownloadProcessor` (in `download_utils.py`) | Nominell Orchestrator, tatsächlich nur Config/Stats-Holder — die eigentliche Orchestrierung liegt in Modul-Funktionen außerhalb der Klasse | gering | 5 | **Kein God-Class-Problem**, aber ungewöhnliches Muster (Klasse ≠ Ort der Komplexität) — als architektonische Eigenheit dokumentiert, nicht als Fehler. |
| `CoverProcessor` | 1 (Cover-Beschaffung), aber 6 unabhängige externe Quellen als je eigene `_fetch_*`-Methode | mittel (`requests.Session`, 6 externe APIs) | ~3 öffentliche + viele private `_fetch_*`/`_log_*` | **ACCEPTABLE COUPLING** — die 6 Quellen sind eine einzige fachliche Verantwortung („bestes Cover finden“), keine Vermischung fremder Belange. |

## 19. Service Coupling Matrix

|            | Metadata | Downloader | Duplicate | Clients | Statistik |
|---|---:|---:|---:|---:|---:|
| Metadata   | – | 1 | 0 | 2 | 0 |
| Downloader | 3 | – | 0 | 0 | 0 |
| Duplicate  | 0 | 1 | – | 0 | 0 |
| Clients    | 0 | 0 | 0 | – | 0 |
| Statistik  | 0 | 0 | 0 | 1 | – |

Werte = Anzahl Dateien in Zeile-Gruppe, die Module aus Spalte-Gruppe
importieren (0 = keine Dependency, gemessen per Grep, nicht geschätzt).

**Begründung der Werte ≥1:**

- **Metadata → Downloader (1)**: `enhanced_metadata_processor.py` importiert
  `cleanup_single_download_artifact` aus
  `services/downloader/download_artifact_cleanup.py` (Zeile 40) — legitime
  Wiederverwendung der Cleanup-Logik nach fehlgeschlagener Verarbeitung.
- **Metadata → Clients (2)**: `album_processor.py` (lokaler Import
  `MusicBrainzClient` innerhalb einer Methode, Zeile 141) und
  `enhanced_metadata_processor.py` (`GeniusClient` modulweit, Zeile 22;
  `MusicBrainzClient`/`LastFMClient` lokal innerhalb von Methoden, Zeilen
  1168/1173) — beide erwartungsgemäß, da Metadata-Pipeline externe
  Anreicherung braucht. **Auffällig**: die lokalen (Methoden-internen statt
  Modul-Top-Level) Imports von `MusicBrainzClient`/`LastFMClient` weichen
  vom sonst durchgängigen Modul-Top-Level-Importstil ab — Grund nicht
  verifiziert (vermutlich zur Vermeidung von Kosten beim Modul-Import oder
  zyklischen Import-Risiken), als **UNKNOWN** markiert.
- **Downloader → Metadata (3)**: `metadata_result_translator.py`,
  `download_utils.py`, `download/interfaces.py` — `download_utils.py`
  orchestriert direkt `EnhancedMetadataProcessor`, `download/interfaces.py`
  referenziert `MetadataResult` im `MetadataEnricher`-Protocol. Höchster
  Kopplungswert im gesamten Baum, aber fachlich erwartbar (Download-Pipeline
  *braucht* die Metadata-Pipeline als nächsten Schritt) — **3 = stark**,
  aber **kein architektonisches Problem**, da die Richtung korrekt ist
  (Downloader kennt Metadata, nicht umgekehrt — Metadata bleibt
  eigenständig testbar).
- **Duplicate → Downloader (1)**: `detector.py` und `cache.py` importieren
  `DuplicateEntry` aus `services/downloader/models.py` — bewusst als
  neutrales, Telegram-freies Datenmodell dorthin verschoben
  (POST-ARCH-010/011, siehe Docstring in `downloader/models.py`).
  Strukturell eine reine Datenmodell-Abhängigkeit, kein Verhaltens-Kopplung.
- **Statistik → Clients (1)**: `statistik_service.py` → `NavidromeAPI`
  (erwartbar, Statistik braucht Now-Playing-Daten von Navidrome).

**Keine Dependency erreicht Wert 4 (kritisch).** Die stärkste Kopplung
(Downloader→Metadata, 3) ist fachlich begründet und unidirektional.

## 20. Target Architecture Gap Analysis

| Bereich | Soll (CLAUDE.md Abschnitt 4) | Ist | Gap | Priorität |
|---|---|---|---|---|
| Handler Boundary | `services` reicht nicht in Telegram-/Präsentationscode | vollständig eingehalten (Abschnitt 7) | keiner | – |
| Services-Struktur | fachliche/technische Orchestrierung | eingehalten, mit einer Methoden-Komplexität-Ausnahme (`process_single_track`) | TECHNICAL DEBT | P3 |
| Clients-Konvention | externe API-Kommunikation in `services/clients/` | Cover-Quellen und yt-dlp liegen außerhalb | DOCUMENTATION GAP / ACCEPTABLE LEGACY | P3 |
| Async-Grenzen | kein blockierendes I/O im Event-Loop | fast vollständig behoben, 1 bewusst zurückgestellter Fall (`duplicate/cache.py`) | ARCHITECTURAL VIOLATION (klein, bekannt) | P2 |
| Fehlerklassifikation | (nicht explizit in CLAUDE.md als Soll benannt, aber Abschnitt 17 „Fallbacks müssen erhalten bleiben“ impliziert bewusste Fehlerbehandlung) | Taxonomie existiert, ungenutzt | MIGRATION CANDIDATE | P1/P2 (siehe Abschnitt 21) |
| Persistence | atomare Writes bei kritischen Caches | seit Track-A-Cleanup (PR #85-#90) durchgängig atomar, wo geprüft | kein Gap mehr | – |
| Config-Zugriff | „möglichst wenige Seiteneffekte“ (Langfristziel, kein Hard-Constraint) | gemischt (8 Dateien direkter Import vs. Rest injiziert) | ACCEPTABLE LEGACY (projektweites Ziel, nicht services-spezifisch) | P3 |
| Test-Boundary-Absicherung | (nicht explizit in CLAUDE.md gefordert, aber implizit durch „Regressionen verhindern“) | keine automatisierte Absicherung der Layer-Grenze gefunden | TECHNICAL DEBT | P3 |

## 21. Migration Candidates

| ID | Component | Problem | Evidence | Impact | Risk | Effort | Priority |
|---|---|---|---|---|---|---|---|
| MIG-01 | `services/downloader/errors.py` + `download_utils.py::enhanced_download_with_retry` | Fehlertaxonomie existiert (6 Subtypen), wird nirgends geworfen; Retry-Schleife behandelt alle Fehler identisch | Abschnitt 12 (0 `raise`-Treffer repoweit), `download_utils.py:398-422` | Verschwendete Retry-Zyklen bei garantiert permanenten Fehlern (z. B. private/gelöschtes Video) — UX-Verzögerung für Nutzer, unnötige yt-dlp-Last | niedrig (additiv, keine bestehende Logik muss geändert werden, nur Fehler an den richtigen Stellen mit spezifischerem Typ werfen + Retry-Schleife um Typ-Check erweitern) | mittel (mehrere Wurfstellen in `download_executor.py`/`enhanced_metadata_processor.py` müssten identifiziert werden) | **P1** |
| MIG-02 | `services/duplicate/cache.py` INV-01 | Synchrone Filesystem-Persistenz im Event-Loop-Thread | Abschnitt 22 (vollständige Analyse) | aktuell klein (kleine Cache-Größen), aber strukturelles Risiko bei Wachstum | mittel (Async-Kaskade durch 3 Schichten) | hoch | **P2** |
| MIG-03 | `MUSICBRAINZ_RETRIES` (`config.py:414`) | Totes Config, keine Retry-Logik für MusicBrainz-Client verdrahtet trotz vorhandenem Wert | Abschnitt 11 | keiner (aktuell), aber verdeckt fehlende Resilience beim MB-Client | niedrig | niedrig (entweder entfernen oder in `musicbrainz_client.py`s bestehende Retry-Struktur einbauen) | **P2** |
| MIG-04 | `CoverProcessor`/`DownloadExecutor` Platzierung außerhalb `services/clients/` | Konvention nicht auf alle externen Integrationen ausgeweitet | Abschnitt 10 | rein struktureller Klarheitsgewinn, keine Funktionsänderung | niedrig | mittel (reine Verschiebung mit Re-Export, siehe CLAUDE.md „Legacy nicht ohne Beweis entfernen“ — hier eher „nicht ohne Grund verschieben“) | **P3** |
| MIG-05 | `process_single_track()` (908 Zeilen) | Ein Methoden-Umfang, der Testbarkeit/Lesbarkeit einzelner Pipeline-Schritte erschwert | Abschnitt 18 | mittel (Wartbarkeit), kein akutes Betriebsrisiko | hoch (CLAUDE.md Abschnitt 19: nicht ohne vorherige Tests/Dokumentation zerlegen) | hoch | **P3** |
| MIG-06 | fehlende automatisierte Layer-Boundary-Tests | Kein Test verhindert künftigen `services→handlers`-Import | Abschnitt 16 | gering aktuell (Boundary ist sauber), aber Regressionsrisiko bei künftigen Änderungen | niedrig | niedrig (ein einziger Grep-basierter Test) | **P3** |

Klassifikation `DO NOW` / `DO NEXT` / `DEFER` / `DO NOT MIGRATE`: siehe
Abschnitt 23 (Empfehlung), hier bewusst nicht vorweggenommen.

## 22. Explicit Deferred Decisions — `duplicate/cache.py` INV-01

### Aktuell (verifizierter Ist-Zustand)

```
klassen/download_handler.py (async def, z.B. handle_url())
    │  [SYNC Aufruf, kein await]
    ▼
DuplicateDetector.check_for_duplicates() / register_download()   [detector.py:109, 247]
    │  [SYNC Aufruf, kein await]
    ▼
DuplicateCache.check_url_duplicate() / check_content_duplicate() / add_entry()
    │  [SYNC Aufruf, kein await]
    ▼
DuplicateCache._save_caches() → _write_json_atomic()   [SYNC Filesystem I/O]
```

### 1. Alle Caller (verifiziert)

- `handlers/duplicate_handler.py`: 2 Konstruktions-Stellen (Zeile 259, 293)
  — eigener `DuplicateDetector` je Aufruf-Kontext.
- `handlers/menu/rich_menu_handler.py`: 1 Konstruktions-Stelle (Zeile 227,
  `self.duplicate_detector`).
- `klassen/download_handler.py`: erhält `DuplicateDetector` per
  Constructor-Injection (Zeile 186/203), ruft `check_for_duplicates()`
  (Zeile 333), `register_download()` (Zeilen 515 und 595, zwei separate
  Call-Sites — Playlist- und Single-Track-Pfad) und `get_statistics()`
  (Zeile 534) auf.

### 2. Alle betroffenen Methoden

`DuplicateDetector.check_for_duplicates`, `check_library_duplicate`,
`register_download`, `get_statistics`, `cleanup_cache`, `invalidate_entry`
(6 öffentliche Methoden, alle synchron) — alle rufen transitiv
`DuplicateCache`-Methoden auf, von denen `add_entry`/`cleanup_old_entries`
den (synchronen) Persistenz-Write auslösen.

### 3. Sync/Async-Grenze

Die Grenze liegt vollständig auf der Aufrufer-Seite: sowohl
`klassen/download_handler.py`s relevante Handler-Methoden als auch die
Telegram-Callback-Handler in `handlers/duplicate_handler.py` und
`handlers/menu/rich_menu_handler.py` sind bereits `async def` — der
Event-Loop-Thread ruft die komplett synchrone `DuplicateDetector`/
`DuplicateCache`-Kette direkt auf, ohne `await`/`to_thread` dazwischen.

### 4. Erforderliche API-Änderungen (Option A: vollständig async)

- `DuplicateCache`: `_load_url_cache`, `_load_content_cache`,
  `_save_caches`, `add_entry`, `check_url_duplicate`,
  `check_content_duplicate`, `cleanup_old_entries` → alle zu `async def`,
  Filesystem-I/O via `asyncio.to_thread` oder `aiofiles`.
- `DuplicateDetector`: alle 6 öffentlichen Methoden → `async def`,
  jeder interne Aufruf an `DuplicateCache` bekommt `await`.
- **3 Aufrufstellen in `klassen/download_handler.py`** (Zeilen 333, 515,
  595, plus 534 für Statistik) müssen `await` bekommen.
- **2 Konstruktions-/Aufrufstellen in `handlers/duplicate_handler.py`**
  und **1 in `handlers/menu/rich_menu_handler.py`** — alle dortigen
  Aufrufe der jetzt-async Methoden müssen ebenfalls `await` bekommen,
  inklusive aller Telegram-Callback-Handler-Methoden, die diese
  transitiv aufrufen (nicht einzeln nachverfolgt in diesem Audit —
  CLAUDE.md-Klassifikation als „mass conversion“ bereits in
  `MusicBrainzArchitectureEvolution.md` P0-B dokumentiert und hier durch
  die konkrete Zahl von mindestens 6 direkten Call-Sites in 3 Dateien
  bestätigt, mit unbekannter, aber laut Doku „kaskadierender“ Anzahl
  weiterer indirekter Aufrufer).

### 5.–7. Auswirkungen auf Handler / Downloader / Tests

- **Handler**: jede Telegram-Callback-Methode, die `DuplicateDetector`
  direkt oder indirekt aufruft, müsste zu `async def` migriert werden
  (bereits der Fall für die identifizierten Call-Sites, aber weitere
  Helper-Methoden innerhalb `duplicate_handler.py`/`rich_menu_handler.py`
  sind nicht einzeln verifiziert).
- **Downloader**: `klassen/download_handler.py`s Kern-Downloadpfad
  (bereits `async def`) müsste an 4 Stellen `await` ergänzen — technisch
  klein, aber jede Änderung an diesem P0-kritischen Pfad
  (CLAUDE.md Abschnitt 5) erfordert laut Projektregeln volle
  Regressionsprüfung.
- **Tests**: alle 17 auf `DuplicateDetector`/`DuplicateCache` bezogenen
  Testdateien (siehe Abschnitt 6, Grep-Treffer) müssten von synchronen
  auf `pytest-asyncio`-Testmuster umgestellt werden, sofern sie die
  öffentlichen Methoden direkt aufrufen.

### 8. Mögliche Alternativen

**OPTION A — vollständig async machen**
- Pros: strukturell konsistent mit dem Rest der async-Handler-Kette;
  behebt INV-01 vollständig.
- Cons: „mass conversion" (laut CLAUDE.md Abschnitt 18 unerwünscht ohne
  Sicherheitsnetz); mindestens 6 direkte + unbekannt viele indirekte
  Call-Sites betroffen; hohes Regressionsrisiko in einem P0-Bereich
  (Duplicate Detection).
- Risk: **hoch**.

**OPTION B — synchron lassen + kontrolliert offloaden**

D.h. nur `DuplicateCache._save_caches()`/`add_entry()` intern per
`asyncio.to_thread` aus einem **synchronen** Kontext heraus auslagern ist
nicht direkt möglich (kein `to_thread` ohne laufenden Event-Loop
verfügbar) — realistisch umsetzbar wäre stattdessen, nur an den 3-4
identifizierten Call-Sites in `klassen/download_handler.py`/Handlern die
jeweilige *aufrufende* Methode (sofern sie ohnehin bereits `async def`
ist) den kompletten `DuplicateDetector`-Aufruf selbst per
`await asyncio.to_thread(self.duplicate_detector.register_download, ...)`
zu wrappen, ohne `DuplicateDetector`/`DuplicateCache` selbst anzufassen.
- Pros: kein API-Bruch, keine Kaskade durch 3 Schichten, minimal-invasiv
  (Muster bereits etabliert für `CoverProcessor`/`TagWriter`).
- Cons: an jeder der mindestens 6 Call-Sites einzeln nachzuziehen; die im
  Code-Kommentar (`cache.py:123-127`) explizit erwähnte „zufällige
  Serialisierung zwischen gleichzeitigen Downloads“ durch die bisherige
  Event-Loop-Atomarität ginge verloren, sobald mehrere `to_thread`-Aufrufe
  parallel auf denselben In-Memory-Dict (`self.url_cache`/
  `self.content_cache`) zugreifen — **neues Race-Risiko**, das die
  bestehende, unautomatisierte Doku-Aussage in `cache.py` explizit
  entkräften würde. Müsste durch einen eigenen Lock (analog
  `chart_renderer.py`) abgesichert werden.
- Risk: **mittel** (neues Race-Risiko, aber lokal begrenzt und
  bekanntes Muster zur Absicherung vorhanden).

**OPTION C — Persistenz entkoppeln**

D.h. `DuplicateCache` bekäme eine reine In-Memory-API (bleibt synchron,
kein Risiko), während das eigentliche Schreiben auf Platte in einen
separaten, expliziten „Flush“-Schritt ausgelagert wird, der zentral
(z. B. periodisch oder beim Bot-Shutdown) async ausgeführt wird statt bei
jedem einzelnen `add_entry()`.
- Pros: entkoppelt das eigentliche I/O-Risiko komplett vom
  Request-Pfad; kein API-Bruch für Detector/Cache-Konsumenten.
- Cons: Datenverlust-Fenster zwischen `add_entry()` und dem nächsten
  Flush bei Prozessabsturz (Trade-off gegen die aktuelle
  Sofort-Persistenz); erfordert einen neuen Lifecycle-Hook (wo wird
  „geflusht“?).
- Risk: **mittel** (neues Datenverlust-Fenster statt Event-Loop-Risiko).

**OPTION D — andere Architektur** (z. B. SQLite statt JSON,
Message-Queue-basiert)

Nicht vertieft bewertet — außerhalb des Aufwand/Nutzen-Verhältnisses für
die tatsächlich gemessene Problemgröße (kleine Cache-Dateien, seltene
Schreibvorgänge relativ zu Telegram-Interaktionsraten).

### Empfehlung (nur Bewertung, keine Umsetzung)

Option B (kontrolliertes Offloading an den Call-Sites) hat das beste
Aufwand/Risiko-Verhältnis, **sofern** die Serialisierungs-Annahme aus dem
bestehenden Code-Kommentar durch einen expliziten Lock ersetzt wird.
Option A bleibt laut bereits bestehender Projektentscheidung
(`MusicBot_ARCHITECTURE_EVOLUTION.md` P0-B) explizit zurückgestellt. Diese
Empfehlung ist **keine Entscheidung** — sie erfordert laut CLAUDE.md
Abschnitt 21 (Regel 1) ein eigenes Sicherheitsnetz (Characterization
Tests für die aktuelle synchrone Serialisierung), bevor irgendeine Option
umgesetzt wird.

## 23. Recommended Migration Order

```
MIG-06 (Layer-Boundary-Test)
    │  Grund: Nullaufwand-Sicherheitsnetz, das VOR jeder weiteren
    │  Migration verhindert, dass neue Verletzungen unbemerkt entstehen.
    ▼
MIG-03 (MUSICBRAINZ_RETRIES entscheiden: entfernen oder verdrahten)
    │  Grund: eigenständig, ohne Abhängigkeit zu anderen Kandidaten,
    │  kleinstmöglicher nächster Schritt.
    ▼
MIG-01 (Fehlertaxonomie verdrahten, DL-03/DL-05)
    │  Grund: eigenständig von MIG-02, aber höherer Impact (P1) — sollte
    │  vor MIG-02 kommen, weil es die Retry-Schleife berührt, die auch
    │  von einer künftigen MIG-02-Lösung (Option B/C) mit betroffen wäre
    │  (Fehlerpfad-Änderungen sollten nicht doppelt an derselben Stelle
    │  passieren).
    ▼
MIG-02 (duplicate/cache.py INV-01 — Option A/B/C Entscheidung)
    │  Grund: höchster Aufwand/Risiko, braucht eigene
    │  Characterization-Test-Phase zuerst (siehe Abschnitt 22).
    ▼
MIG-04 (Client-Platzierung CoverProcessor/DownloadExecutor)
    │  Grund: rein kosmetisch, keine Funktionsabhängigkeit zu den anderen —
    │  kann jederzeit isoliert erfolgen, hier nur der Vollständigkeit
    │  halber ans Ende gestellt (P3, kein Zeitdruck).
    ▼
MIG-05 (process_single_track() Zerlegung)
    │  Grund: höchster Aufwand, laut CLAUDE.md Abschnitt 19 zwingend erst
    │  NACH ausreichender Testabdeckung — sollte letztes Element sein,
    │  nicht weil unwichtig, sondern weil die Reihenfolge
    │  „Characterize → Decide → Extract → Audit → Regression“ hier am
    │  meisten Vorarbeit braucht.
```

## 24. Explicit Deferred Decisions

- **`duplicate/cache.py` INV-01**: siehe vollständige Analyse Abschnitt 22
  — keine der 4 Optionen wurde umgesetzt oder vorentschieden.
- **DOWNLOAD_RETRY_COUNT/DELAY vs. hartcodiertes `2**attempt`**: nicht
  abschließend verifiziert, ob die Config-Werte tatsächlich als
  `max_retries`-Quelle für `enhanced_download_with_retry()` dienen — als
  offene Frage dokumentiert (Abschnitt 11), nicht als Entscheidung
  getroffen.
- **CoverProcessor/DownloadExecutor Platzierung** (MIG-04): keine
  Verschiebung vorgenommen oder empfohlen ohne separate Nutzer-Freigabe,
  da eine reine Struktur-/Konventions-Frage ohne funktionalen Nutzen.

## 25. Findings NOT To Fix

- **~90 `except Exception`-Blöcke** über `services/` verteilt: durchweg
  mit Logging versehen (Stichproben bestätigt), keine systematische
  Vertiefung aller Einzelfälle in diesem Audit-Zeitbudget — bewusst nicht
  als Einzel-Findings aufgeführt, da CLAUDE.md Abschnitt 25 verlangt,
  „nicht aus jedem Unterschied automatisch ein Finding zu machen“.
- **`services/clients/navidrome_api.py` `import subprocess`**: importiert,
  aber nirgends im Modul verwendet (toter Import) — geringste Priorität
  (P3, kosmetisch), hier nur der Vollständigkeit halber vermerkt, kein
  eigener MIG-Eintrag, da funktional folgenlos.
- **`tenacity`-Retry in `genius_client.py`**: nicht vertieft geprüft, da
  außerhalb des DL-03/DL-05-Kernfokus (YouTube-Download-Retry) und keine
  Auffälligkeit beim Überfliegen gefunden.

## 26. Conclusion

Der `services/`-Baum hält die in CLAUDE.md Abschnitt 4 dokumentierten
Schichtgrenzen **vollständig** ein — dies ist der wichtigste Einzelbefund
dieses Audits: keine der befürchteten Rückwärtsabhängigkeiten
(`services→handlers`, `services→klassen`, `services→Telegram`) wurde
gefunden. Die async/sync-Grenzen sind bis auf den einen, seit Langem
bekannten und bewusst zurückgestellten Fall (`duplicate/cache.py`)
vollständig sauber — mehrere frühere Funde (COVER-BLOCKING, AE-12) wurden
bei der Gegenprüfung als korrekt gefixt bestätigt.

Der bedeutsamste **neue** Fund dieses Audits ist MIG-01: eine bereits
vorhandene, aber vollständig ungenutzte Fehlertaxonomie in
`services/downloader/errors.py`, die DL-03/DL-05 mit deutlich geringerem
Aufwand lösbar macht als bisher angenommen — die Infrastruktur muss nur
verdrahtet, nicht neu gebaut werden.

**Divergenz-Hinweis (Abschnitt 26 der Aufgabenstellung, „keine
Halluzinationen“):** Der ursprünglich für dieses Audit mitgelieferte
Plan-Kontext (`woolly-wishing-volcano.md`) beschreibt
`download_executor.py::extract_info()`/`download_single_track()` als
„vollständig synchron, ohne `run_in_executor`" und damit als noch offenen
Blocking-Fund. Der tatsächliche Code-Zustand zum Audit-Zeitpunkt (HEAD
`b90f8dc`) zeigt bereits eine existierende `extract_info_async()`-Methode
(Zeile 171) sowie SAFE-VIA-to_thread-Aufrufe an den relevanten Call-Sites
(Abschnitt 8). Dieser Plan wurde offenbar in einer früheren, nicht in
diesem Audit nachvollziehbaren Session bereits umgesetzt — der Ist-Zustand
im Code hat hier gemäß CLAUDE.md Abschnitt 2 („Code als tatsächliche
Verhaltensquelle“) Vorrang vor dem älteren Plandokument.

## 27. Abschluss-Gate

Siehe Bash-Ausgaben in der Session; Zusammenfassung:

- `git status` vor und nach dem Audit: einzige Differenz ist die
  neu geschriebene Datei `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md`
  (plus die vorbestehende, nicht durch dieses Audit verursachte Änderung an
  `mapping/artist_overrides.json`, siehe Abschnitt 3).
- `git diff --stat` / `git diff` (Produktionscode): keine Änderungen.
- Testsuite (`python3 -m pytest tests/ -q`) während des Audits einmalig
  zur Teststatus-Dokumentation ausgeführt (reines Lesen/Ausführen, keine
  Code-/Testdatei geändert): 1652 passed, 1 skipped, 0 failed — siehe
  Abschnitt 3.
