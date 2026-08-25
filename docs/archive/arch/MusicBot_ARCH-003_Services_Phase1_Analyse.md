# ARCH-003 — Zielarchitektur `services/`: Phase 1 (Analyse)

> Dieses Dokument ist die vollständige Analyse-Grundlage für die geplante
> Migration von `services/` auf eine saubere Zielarchitektur (Auftrag vom
> 2026-08-20). Phase 1 (Analyse) hat keinen Code geändert.

**Umfang:** `services/` — 30 Python-Dateien, 11.429 Zeilen (`services/downloader/**` + `services/statistik_service.py`).

---

## Phase 2/3 — Status der Umsetzung (Branch `arch/services-migration`)

Nutzer-Entscheidung: **nur risikoarmer Kern**, ausschließlich innerhalb
`services/`, keine Consumer-Änderungen außerhalb des Verzeichnisses.

**Umgesetzt:**

- P-4: `error_handler.py` in `errors.py` umbenannt, Teil B (tote,
  Telegram-gekoppelte Handler-Funktionen, ~190 Zeilen, 0 Aufrufer) entfernt.
  Teil A (Fehler-Taxonomie: `DownloadError` + 6 Subklassen) bleibt
  unverändert erhalten.
- P-5: kaputte, tote Methode `YoutubeDownloader.format_download_result_for_log()`
  entfernt (fehlendes `self`, referenzierte eine nie definierte Variable
  `lines` — hätte bei jedem Aufruf `NameError` geworfen; 0 Aufrufer).
- P-12: `services/downloader/interfaces.py` (`IDownloaderConfig`,
  `IDownloader` — 0 Implementierer/Verwendungen) entfernt.
- P-13: `download_utils.py::download_with_retry()` (Legacy-Wrapper, 0
  Aufrufer) und `download_utils.py::_determine_dominant_year_from_playlist()`
  (zweite, unabhängige tote Legacy-Funktion desselben Namens, ebenfalls 0
  Aufrufer — nicht zu verwechseln mit der bereits in TEST-018/LEGACY-012
  entfernten Variante in `playlist_processor.py`) sowie
  `TrackDownloadState` (Datenklasse, 0 Aufrufer) aus `download/models.py`
  entfernt.
- P-8: `PlaylistProcessor.__init__` und `SpotifyDownloader.__init__` nehmen
  jetzt optional `config` bzw. `rss_manager` injiziert entgegen, statt sie
  zwingend selbst zu konstruieren. Default-Verhalten (kein Parameter
  übergeben) bleibt exakt unverändert.
- P-9: `DownloadExecutor.build_ydl_opts()` liest den Cookie-Datei-Pfad jetzt
  aus dem bereits injizierten `config`-Parameter (`Config.COOKIES_FILE`,
  existierte bereits, wurde vorher nicht genutzt) statt einem hartkodierten,
  CWD-relativen `Path("cookies.txt")`.

**Bewusst nicht umgesetzt in diesem ersten Schritt** (siehe Abschnitt 5 unten
— STOP CONDITIONS, Nutzerentscheidung war „nur risikoarmer Kern“):

- P-1 (`FileUtils` totes Gewicht), P-2 (Telegram-Kopplung entfernen), P-3
  (doppelte Spotify/YouTube-Orchestrierung), P-11 (Import aus `klassen/`),
  P-14 (`advanced_podcast_finder.py`) bleiben unverändert und sind
  Kandidaten für eine spätere, dedizierte Migrationsphase.

**Tests:** 6 neue/erweiterte Tests (`test_download_executor.py`,
`test_playlist_processor.py`, `test_spotify_downloader.py`) für die neuen
Dependency-Injection-Punkte. Voller Regressionslauf: 920 bestanden (vorher
914), unverändert 15 vorbestehende Fehler. Kein Type-Checker/Linter im
Repository konfiguriert (kein `mypy`/`ruff`/`pyproject.toml` gefunden) —
`python -m py_compile`/Import-Smoke-Test über alle `services/`-Submodule
als Ersatz-Gate genutzt.

## Phase 2/3 (Fortsetzung) — P-6: `StatistikService` aufgeteilt

Nutzer-Entscheidung: nach dem risikoarmen Kern direkt mit P-6 weitermachen.

`services/statistik_service.py` (573 Zeilen, God-Service: Persistenz +
externer API-Client + Business-Statistik + matplotlib-Rendering +
Hintergrund-Scheduling) in 4 fokussierte, einzeln injizierbare/testbare
Klassen unter dem neuen Paket `services/statistik/` aufgeteilt:

- `play_history_repository.py::PlayHistoryRepository` — Lesen/Schreiben/
  Bereinigen der JSON-Verlaufsdateien (reine Datei-I/O)
- `play_history_poller.py::PlayHistoryPoller` — Hintergrund-Polling gegen
  `NavidromeAPI` (injiziert statt selbst konstruiert), schreibt über das
  injizierte `PlayHistoryRepository`
- `statistics_calculator.py::StatisticsCalculator` — reine Business-Logik
  (Top-Artists/Songs/Albums, letzter Song, Play-Count, JSON-Export), liest
  über das injizierte `PlayHistoryRepository`
- `chart_renderer.py::ChartRenderer` — matplotlib-Balkendiagramme, einziger
  Ort im gesamten Repository mit dieser Abhängigkeit

`services/statistik_service.py` selbst ist jetzt eine **bewusst dünne,
temporäre Fassade** (Abschnitt 14 der Aufgabe: Migrations-Brücke, klar als
solche gekennzeichnet): exakt dieselbe öffentliche API wie vorher — inkl.
der als „privat" markierten, aber von `tests/test_statistik_service.py`
direkt getesteten Methoden `_load_history`/`_save_history`/
`_cleanup_old_entries` und der Klassenattribute `CHARTS_DIR`/
`USER_HISTORY_DIR` (weiterhin vor Konstruktion monkeypatchbar) —
`bot.py`/`handlers/mugge_statistik_handler.py` bleiben **unverändert**.
Zusätzlich `navidrome_api` optional injizierbar gemacht (P-8-Muster),
Default-Verhalten (kein Parameter) unverändert.

**Wichtige Verhaltens-Nuance bewusst erhalten:** `cleanup_old_entries()`
liest `Config.PLAY_HISTORY_RETENTION_DAYS` weiterhin zum Aufrufzeitpunkt
(nicht beim Konstruieren) — ein bestehender Test verändert diesen
Config-Wert erst NACH der Service-Konstruktion und erwartet trotzdem
Wirkung.

**Tests:** 40 neue, isolierte Tests für die 4 neuen Klassen (direkt
konstruiert, ohne Umweg über die Fassade) + alle 29 bestehenden
`test_statistik_service.py`/`test_mugge_statistik_handler.py`-Tests
unverändert grün. Voller Regressionslauf: 960 bestanden (vorher 920),
unverändert 15 vorbestehende Fehler.

**Verbleibend offen:** P-1, P-2, P-3, P-11, P-14 (siehe Abschnitt 5).

---

## Phase 2/3 (Fortsetzung) — P-11: externe API-Clients nach `services/clients/`

Nutzer-Freigabe: P-11 analysieren und schrittweise umsetzen.

Ursprünglicher Befund (Abschnitt 3, Zeile 559) betraf nur
`klassen.genius_client.GeniusClient`. Vertiefte Analyse zeigte: die
Geschwisterdateien `klassen/lastfm_client.py` und
`klassen/musicbrainz_client.py` sind strukturell identisch — reine
externe-API-Adapter, ausschließlich von
`services/downloader/utils/enhanced_metadata_processor.py` (bzw. zusätzlich
`services/downloader/utils/metadata/album_processor.py` für MusicBrainz)
und Tests konsumiert, kein Handler-/Telegram-Bezug. Nur `genius_client` zu
verschieben hätte eine neue Inkonsistenz mit den beiden Geschwistern
geschaffen. Nutzer-Entscheidung: alle drei Clients gemeinsam verschieben,
neues Verzeichnis `services/clients/`.

**Neue Architekturregel:** `services/clients/` enthält ausschließlich
externe Integrationsadapter (Genius, Last.fm, MusicBrainz). Fachliche
Logik bleibt außerhalb der Clients.

Durchgeführt in drei Einzelschritten (je eigener Commit, reine
Verschiebung + Import-Updates, keine Verhaltensänderung):

- `klassen/genius_client.py` → `services/clients/genius_client.py`
  (Commits `b57a13a`/`7d68d91`)
- `klassen/lastfm_client.py` → `services/clients/lastfm_client.py`
  (Commits `31abf2e`/`8108f62`)
- `klassen/musicbrainz_client.py` → `services/clients/musicbrainz_client.py`
  (Commit `f3de0f1`)

Alle Import-Stellen (Produktionscode + Tests inkl. `mock.patch(...)`-Ziele)
aktualisiert. `klassen/` enthält jetzt nur noch `download_handler.py`
(Orchestrator) — die ursprüngliche Fehlplatzierung ist vollständig
behoben.

**Tests:** alle direkt betroffenen Testdateien unverändert grün
(25 + 12 + 28 = 65 Tests). Voller Regressionslauf: 1008 bestanden,
unverändert 15 vorbestehende Fehler.

**P-11 damit abgeschlossen.** Verbleibend offen: P-1, P-2, P-3-DEFER-Punkte
(ARCH-004 Abschnitt 7), P-14.

---

## Phase 2/3 (Fortsetzung) — P-1: `FileUtils` entfernt (totes Gewicht)

Nutzer-Freigabe: P-1 umsetzen, Richtung „nur entfernen" (nicht
reaktivieren) — drei Optionen vorgelegt, Nutzer wählte die risikoärmste:
reine Bereinigung ohne neues Verhalten. Das Temp-Wachstums-Risiko
(`clean_temp_files()` lief nie) bleibt bewusst als eigene, zurückgestellte
Folgeentscheidung offen — Aktivierung wäre eine echte
Verhaltensänderung der Produktions-Pipeline und war nicht Teil dieser
Freigabe.

`services/downloader/utils/file_utils.py` (`FileUtils`, `SingletonMixin`)
komplett gelöscht, ebenso `tests/test_file_utils.py` (23 Charakterisierungs-
Tests für die jetzt entfernte Klasse). Der `file_utils`-Parameter war ein
reiner Pass-Through ohne jede Verwendung im Zielort
(`EnhancedMetadataProcessor.process_single_track()` referenzierte ihn im
gesamten Methodenkörper nicht) — daher durch die komplette Kette entfernt:

- `enhanced_metadata_processor.py::process_single_track()` — Parameter +
  toter Import entfernt
- `metadata_result_translator.py::call_process_single_track()` — Parameter
  + Weiterreichung entfernt
- `download_utils.py` — Konstruktion (`EnhancedDownloadProcessor.__init__`),
  Attribut-Zugriff, alle drei Pipeline-Funktionssignaturen
  (`_process_playlist_download`/`_process_track_metadata`/
  `_process_single_download`) + deren Aufrufstellen, toter Import entfernt
- `klassen/download_handler.py` — Konstruktion, Aufrufstelle, Icon-Mapping-
  Eintrag, toter Import entfernt
- `services/downloader/downloader.py` (`YoutubeDownloader`) — optionaler
  Parameter + Fallback-Konstruktion + Attribut entfernt (wurde im Rest der
  Klasse nie gelesen)
- `services/downloader/download/interfaces.py` — `MetadataEnricher`-
  Protocol-Signatur konsistent nachgezogen (rein deklarativ, kein
  Laufzeit-Effekt)

**Tests:** 6 Testdateien angepasst (Parameter aus Aufrufen entfernt:
`test_metadata_result_translator.py`, `test_download_utils_metadata_translation.py`,
`test_download_handler_process_single_download_result.py`,
`test_metadata_processor_happy_path.py`,
`test_autolearn_special_channel_gate.py`, `test_playlist_max_items.py`),
alle unverändert grün. `tests/test_file_utils.py` gelöscht (Klasse existiert
nicht mehr). Regressionslauf: 985 bestanden (vorher 1008 — Differenz von 23
entspricht exakt der gelöschten Testdatei), unverändert 15
Vorbestand-Fehler.

**P-1 damit abgeschlossen.** Verbleibend offen: P-2, P-14, P-3-DEFER-Punkte
(ARCH-004 Abschnitt 7) sowie die zurückgestellte Folgeentscheidung
„Temp-Verzeichnis-Bereinigung reaktivieren?" (eigenständiges Cleanup-Problem,
unabhängig von der jetzt entfernten `FileUtils`-Klasse) — umgesetzt als
ARCH-005, siehe `docs/MusicBot_ARCH-005_TempCleanup.md`.

---

## Phase 2/3 (Fortsetzung) — P-14: `advanced_podcast_finder.py` entfernt

Nutzer-Freigabe: vor jeder Umsetzung vollständig auf aktive Consumer,
Imports, Tests, Runtime-Nutzung und Dokumentationsreferenzen prüfen; nur
bei nachgewiesener Nichtnutzung entfernen (nicht migrieren) — analog zum
Präzedenzfall LEGACY-011 (`services/organizer.py`), wo dieselbe
Fragestellung bereits einmal auftrat.

Vollständige Prüfung ergab in jeder überprüfbaren Kategorie 0 Treffer:
keine Python-Importe/Aufrufer (repo-weit), keine Tests, keine
Shell-Skripte/Cron-Jobs/systemd-Units/Docker-Dateien (existieren im
gesamten Repo ohnehin nicht), keine README-/Setup-Doku-Referenzen (nur die
eigenen ARCH-003-Analysedokumente erwähnen den Namen). Einziger indirekter
Hinweis auf frühere manuelle Nutzung: der Default-Podcast-Name im
interaktiven Demo-Modus (`if __name__ == "__main__"`) entsprach exakt dem
einen Eintrag in `mapping/podcast_rss_feeds.yaml` — die repo-seitige
Analyse konnte die verbleibende Frage nach aktueller *manueller*
Terminal-Nutzung technisch nicht klären (ein interaktives CLI-Tool
hinterlässt dafür keine Spuren im Repo). Nutzer bestätigte auf explizite
Nachfrage: nicht mehr in Gebrauch.

`services/downloader/advanced_podcast_finder.py` (833 Zeilen) komplett
entfernt — keine Migration nach `tools/`, keine Testdatei zu löschen (gab
es nie). Import-Smoke-Test über die drei nächstgelegenen Module
(`downloader.py`, `spotify_downloader.py`, `download_handler.py`) sowie
voller Regressionslauf: 1005 bestanden, unverändert 15 Vorbestand-Fehler
— exakt unverändert gegenüber dem Stand vor der Entfernung, wie für ein
komplett unverdrahtetes Modul erwartet.

**P-14 damit abgeschlossen.** Verbleibend offen: P-2, P-3-DEFER-Punkte
(ARCH-004 Abschnitt 7).

---

## 0. Wichtigster Gesamtbefund

`services/` ist **kein einheitlich geschichtetes System**, sondern zwei sehr unterschiedliche Zonen:

1. **Der YouTube-Download-Kern** (`services/downloader/download/*.py`, `services/downloader/utils/metadata/*.py`, `download_utils.py`) ist — vor allem durch die in dieser Session bereits durchgeführten ARCH-001/BUG-Fixes — überraschend **sauber**: kleine Single-Responsibility-Klassen, explizite Dependency Injection, ein bereits existierendes Protocol-basiertes Port-System (`download/interfaces.py`: `CacheProvider`, `MetadataEnricher`), klare Fehlerklassen. Das ist die **Referenz**, an der sich die Zielarchitektur orientieren sollte — nicht neu erfunden werden muss.
2. **Der Rest** (`statistik_service.py`, `spotify_downloader.py`, `downloader.py`, `error_handler.py`, `progress_tracker.py`, `download_result_reporter.py`, `interfaces.py`, `advanced_podcast_finder.py`) enthält die eigentlichen Architekturprobleme: Telegram-Kopplung in "services", ein God-Service, eine zweite parallele Orchestrierung für Spotify, tote Interfaces und mehrere **komplett unbenutzte, aber breit verdrahtete Komponenten** ("wired but inert" — Konstruktion suggeriert Nutzung, tatsächlich passiert nichts).

Der zweite Punkt ist die eigentliche Arbeit dieser Migration. Der erste Punkt soll **bewahrt und als Vorbild verwendet** werden.

---

## 1. Service Inventory

Format pro Service: `Verantwortung (aktuell) → Verantwortung (Ziel)`, Abhängigkeiten, Consumer, Side Effects, Probleme.

### 1.1 YouTube-Download-Kern (Referenzarchitektur — geringe Änderung nötig)

```text
Service: EnhancedDownloadProcessor (services/downloader/utils/download_utils.py)
Current responsibility: Composition Root + Orchestrierung der gesamten Download-Pipeline
  (Retry-Loop, Playlist-/Single-Track-Verzweigung, Session-Stats)
Actual responsibility: identisch — sauber
Current dependencies: FileUtils, FilenameFixerTool, PlaylistProcessor,
  EnhancedMetadataProcessor (als MetadataEnricher-Protocol), MetadataCache
  (als CacheProvider-Protocol), ArtistNormalizer, CacheManager, YearResolver,
  ChannelRouter, DownloadExecutor, ProgressFormatter — alles per Dependency
  Injection in _do_init() konstruiert (kein externer Composition Root, aber
  explizit und nachvollziehbar)
Required dependencies: unverändert
Consumers: services/downloader/downloader.py (YoutubeDownloader),
  klassen/download_handler.py (indirekt über YoutubeDownloader)
Side effects: Datei-Downloads, Cache-Schreibzugriffe, Logging
Problems: SingletonMixin — bei Tests/parallelen Chats potenziell geteilter
  State (bereits bekanntes, nicht neues Risiko); enthält eine tote
  Legacy-Wrapper-Funktion (download_with_retry(), 0 Aufrufer) und eine tote
  Modul-Funktion (_determine_dominant_year_from_playlist() – Duplikat/
  Delegation, aber selbst nie aufgerufen, siehe Problem P-6)
Target responsibility: unverändert (Referenz-Orchestrator)
Target dependencies: unverändert
Migration complexity: NIEDRIG (nur Leichen entfernen)
```

```text
Service: CacheManager (services/downloader/download/cache_manager.py)
Current/Target responsibility: 2-stufiger Cache-Lookup für Playlist-Tracks
  + einfacher Cache-Lookup für Single-Downloads (reines Lesen, kein Schreiben)
Dependencies: MetadataCache (injiziert), ArtistNormalizer (injiziert, optional)
Consumers: EnhancedDownloadProcessor
Side effects: keine (Lesen + ggf. Datei-Existenzprüfung)
Problems: keine (bereits BUG-011 in dieser Session behoben)
Migration complexity: KEINE
```

```text
Service: YearResolver (services/downloader/download/year_resolver.py)
Current/Target responsibility: Jahr-Bestimmung aus 4 Quellen (Track-Einträge,
  PlaylistProcessor-Ergebnis, playlist_info.upload_date, Fallback)
Dependencies: keine (reine Logik)
Consumers: EnhancedDownloadProcessor (_process_playlist_download)
Side effects: keine
Problems: ARTISTNORM-003 (dokumentiert, nicht kritisch: YEAR_PATTERN deckt
  nur bis 2029, YEAR_MAX=2035)
Migration complexity: KEINE
```

```text
Service: ChannelRouter (services/downloader/download/channel_router.py)
Current/Target responsibility: 5-stufiges Artist/Channel-Routing (P1–P5)
  für dominant_artist-Erkennung inkl. Sonderkanal-Erkennung
Dependencies: ArtistNormalizer (injiziert), Config (injiziert),
  utils.filenamefixer (get_special_channel_info, load_special_channels_merged)
Consumers: EnhancedDownloadProcessor
Side effects: keine
Problems: keine
Migration complexity: KEINE
```

```text
Service: DownloadExecutor (services/downloader/download/download_executor.py)
Current/Target responsibility: reine yt-dlp-Kapselung (Optionen, Extraktion,
  Einzel-Track-Download, Datei-Suche) — der einzige echte "Provider"/Adapter
  für die externe Download-Infrastruktur
Dependencies: yt_dlp (extern), utils.filenamefixer (nur für Podcast-Erkennung
  im Duration-Filter)
Consumers: EnhancedDownloadProcessor
Side effects: Netzwerk-I/O, Datei-Schreiben (via yt-dlp)
Problems: hartkodierter Pfad Path("cookies.txt") statt Config/Injection
  (P-9, klein); async-Grenzen bereits sauber (REL-004 in dieser Session
  behoben)
Migration complexity: KEINE (P-9 optional)
```

```text
Service: ProgressFormatter (services/downloader/download/formatters.py)
Current/Target responsibility: reine ASCII-Log-Formatierung (keine Telegram-
  Kopplung — nur ins Logging, nicht an Telegram gesendet)
Dependencies: keine
Consumers: EnhancedDownloadProcessor (Logging)
Side effects: keine
Problems: 2 Methoden ohne aktuelle Aufrufer (playlist_start/
  single_track_header — bereits dokumentiert, bewusst nicht entfernt)
Migration complexity: KEINE
```

```text
Service: PlaylistProcessor (services/downloader/playlist_processor.py)
Current/Target responsibility: dominanten Artist + Titel-Bereinigung pro
  Playlist bestimmen (Vorstufe zu ChannelRouter/YearResolver)
Dependencies: ArtistNormalizer, utils.youtube_parser (beide direkt
  konstruiert/importiert, nicht injiziert — einzige Ausnahme im Kern:
  __init__ baut sich sein artist_normalizer selbst via echtes Config())
Consumers: EnhancedDownloadProcessor
Side effects: keine
Problems: P-9-artig — Config-Zugriff direkt im Service statt injiziert
  (siehe unten P-8); tote Standalone-Funktion bereits in dieser Session
  entfernt (LEGACY-012)
Migration complexity: NIEDRIG (Config-Injection nachziehen, siehe P-8)
```

```text
Service: MetadataEnricher-Subsystem (services/downloader/utils/metadata/*.py:
  ArtistProcessor, TitleCleaner, GenreProcessor, AlbumProcessor,
  LyricsProcessor, CoverProcessor, AutoLearnManager, TagWriter,
  MetadataCacheHandler)
Current/Target responsibility: je EINE fachliche Verantwortung pro Klasse
  (Artist-Auswahl, Titel-Bereinigung, Genre-Bestimmung, Album/Jahr,
  Lyrics-Fetch, Cover-Fetch+Scoring, Auto-Learning, ID3/MP4-Tags schreiben,
  Cache-Check) — bereits vorbildlich zerlegt
Dependencies: jeweils explizit per Konstruktor injiziert (artist_normalizer,
  genre_mapper, genius_client, mb_client, config, logger) — GUTES DI-Muster
Consumers: EnhancedMetadataProcessor (Composition Root dieser Ebene)
Side effects: GenreProcessor/CoverProcessor/LyricsProcessor rufen externe
  APIs auf (MusicBrainz, Last.fm, Fanart.tv, CoverArtArchive, Apple Music,
  Deezer, Genius); TagWriter schreibt Dateien; AutoLearnManager schreibt
  YAML/JSON-Mappings
Problems: CoverProcessor/GenreProcessor mischen externen API-Zugriff UND
  Bewertungs-/Entscheidungslogik in derselben Klasse (P-10, geringe
  Priorität — echte Trennung in Provider+Scorer wäre eine "künstliche
  Interface-Flut" ohne akuten Bedarf, da beide Klassen bereits isoliert
  testbar und einzeln verantwortlich sind)
Migration complexity: KEINE bis NIEDRIG
```

```text
Service: EnhancedMetadataProcessor (services/downloader/utils/enhanced_metadata_processor.py)
Current/Target responsibility: Composition Root + Orchestrierung der
  Metadaten-Pipeline (Cache-Check → Artist → Titel → Genre → Lyrics →
  Cover → Album/Jahr → Auto-Learn → Tags schreiben → Datei verschieben)
Dependencies: alle 9 Sub-Prozessoren (siehe oben, alle selbst konstruiert,
  nicht von außen injiziert — siehe P-7), klassen.genius_client.GeniusClient
  (P-11, siehe unten), utils.filenamefixer, utils.metadata_cache,
  utils.genre_map, utils.artist_map, utils.youtube_parser
Consumers: download_utils.py (als MetadataEnricher-Protocol),
  klassen/download_handler.py (_process_single_download_result für Spotify,
  siehe P-3)
Side effects: alle Side Effects der Sub-Prozessoren gebündelt
Problems: P-7 (kein externer Composition Root — akzeptabel, siehe unten),
  P-11 (Import aus klassen/, siehe unten)
Migration complexity: NIEDRIG
```

### 1.2 Problematische Zone (eigentlicher Migrationsschwerpunkt)

```text
Service: FileUtils (services/downloader/utils/file_utils.py)
Current responsibility (behauptet): Datei-Verifikation, sicheres
  Umbenennen, Temp-Cleanup, Verzeichniserstellung, Dateinamen-Sanitisierung
Actual responsibility: KEINE — bereits in dieser Session (ARCH-002)
  verifiziert: wird an 3 Stellen konstruiert und durch die gesamte
  Download-Pipeline als Parameter durchgereicht, aber REPO-WEIT ruft
  niemand eine ihrer 5 öffentlichen Methoden auf. Reale Datei-Sanitisierung
  läuft über utils/helpers.py (genutzt von FilenameFixerTool)
Consumers (nur Konstruktion, keine Methodenaufrufe): downloader.py,
  download_utils.py, klassen/download_handler.py
Side effects: keine (weil nie aufgerufen)
Problems: P-1 (totes Gewicht — insbesondere clean_temp_files() läuft nie,
  potenzielles Temp-Verzeichnis-Wachstum)
Target: entfernen ODER reaktivieren (Nutzerentscheidung nötig, siehe unten)
Migration complexity: NIEDRIG (Entfernen) / MITTEL (Reaktivieren, da
  Verhaltensänderung der laufenden Pipeline)
```

```text
Service: ProgressTracker (services/downloader/utils/progress_tracker.py)
Current responsibility (behauptet): Fortschritts-Updates an Telegram senden
Actual responsibility: teilweise tot — konstruiert in
  klassen/download_handler.py UND (unreachable) in download_utils.py
  init_tracker(); .update_progress()/.set_current_item() werden aber
  NIRGENDS aufgerufen (nur .status_message wird 3× direkt neu zugewiesen).
  progress_hook()/track_performance() (Modulfunktionen) haben 0 Aufrufer
  (bereits in TEST-015/BUG-009-Nachbarschaft dieser Session dokumentiert)
Dependencies: telegram.Update (harte Kopplung)
Consumers: klassen/download_handler.py (nur Konstruktion + .status_message)
Side effects: keine (weil update_progress() nie aufgerufen wird)
Problems: P-2 (Telegram-Kopplung in "services/"), P-2b (totes Gewicht wie
  FileUtils)
Target: Falls behalten — gehört NICHT in services/ (Telegram-Presentation),
  sondern zu handlers/. Funktionalität aktuell nicht genutzt — gleiche
  Entscheidung wie FileUtils nötig
Migration complexity: NIEDRIG (Entfernen aus services/) / MITTEL
  (Reaktivieren+Verschieben)
```

```text
Service: error_handler.py — GEMISCHT, zwei völlig verschiedene Teile
  (services/downloader/utils/error_handler.py)

  Teil A — DownloadError + Subklassen (InvalidURLError,
  FormatNotAvailableError, MetadataError, FileProcessingError, NetworkError,
  PermissionError):
    Actual responsibility: saubere, ECHT GENUTZTE Fehler-Taxonomie
    (genau das, was Abschnitt 7 der Aufgabe fordert)
    Consumers: download_utils.py, file_utils.py, playlist_processor.py
      (indirekt über andere Module), etc.
    Problems: keine
    Target: bleibt, ideal sogar als eigenes Modul (errors.py)

  Teil B — handle_error(), handle_exception(), handle_network_error(),
  handle_permission_error(), handle_invalid_url_error(), log_error_event(),
  log_warning_event(), get_error_stats():
    Actual responsibility: Telegram-Fehlermeldungen senden
    (update.message.reply_text(...))
    Dependencies: telegram.Update, telegram.constants.ParseMode,
      helfer.markdown_helfer
    Consumers: NIEMAND — 0 Aufrufer im gesamten Repo (verifiziert per Grep).
      Die tatsächlich genutzte Fehlerbehandlung ist eine komplett andere,
      unabhängige Implementierung: handlers/enhanced_error_handler.py
    Problems: P-4 (komplett tote, Telegram-gekoppelte Parallel-
      Implementierung — ~190 Zeilen)
    Target: entfernen (hohe Konfidenz — nicht nur unbenutzt, sondern durch
      ein vollständig anderes, aktives System ersetzt)
    Migration complexity: NIEDRIG
```

```text
Service: DownloadResultReporter (services/downloader/utils/download_result_reporter.py)
Current responsibility: Formatieren + Senden von Download-Abschluss-
  Telegram-Nachrichten (Duplikat-Meldung, Playlist-Summary, Final-Summary)
Actual responsibility: identisch — echte, saubere Presentation-Logik,
  aber komplett Telegram-spezifisch
Dependencies: telegram.error.TelegramError, handlers.duplicate_handler.
  DuplicateEntry (services/ importiert aus handlers/ — falsche Richtung)
Consumers: klassen/download_handler.py
Side effects: sendet Telegram-Nachrichten
Problems: P-2 (Telegram-Kopplung + Import aus höherer Schicht in services/)
Target: gehört NICHT in services/ — Verschiebung nach handlers/ (z. B.
  handlers/download_result_reporter.py) ist der sauberste Schnitt
Migration complexity: NIEDRIG (reine Verschiebung, keine Logikänderung
  nötig — Klasse ist bereits gut isoliert) — ABER: Verschiebung liegt
  AUSSERHALB von services/, siehe STOP-CONDITION unten
```

```text
Service: YoutubeDownloader (services/downloader/downloader.py)
Current responsibility: dünner Wrapper um enhanced_download_with_retry(),
  übersetzt Telegram-Update in chat_id/update_id, baut das finale
  Ergebnis-Dict für DownloadHandler
Actual responsibility: identisch, PLUS: nimmt ein rohes Telegram Update
  im Konstruktor entgegen UND einen CookieHandler, der nie verwendet wird
  (echte Cookie-Datei-Erkennung passiert hartkodiert in
  download_executor.py über Path("cookies.txt"))
Dependencies: telegram Update (Konstruktor), CookieHandler (ungenutzt),
  enhanced_download_with_retry, EnhancedDownloadProcessor, FileUtils,
  FilenameFixerTool
Consumers: klassen/download_handler.py
Side effects: delegiert an enhanced_download_with_retry()
Problems: P-2 (Telegram-Kopplung im Konstruktor — enhanced_download_with_
  retry() selbst braucht nur chat_id: int/update_id: int, die Kopplung ist
  vermeidbar), P-5 (toter format_download_result_for_log(): fehlendes
  self, referenziert eine nie definierte Variable lines — würde bei jedem
  Aufruf NameError werfen; 0 Aufrufer gefunden), P-9 (CookieHandler
  injiziert aber ungenutzt)
Target: Update-Objekt durch (chat_id: int, update_id: int) ersetzen
  (Signatur bereits kompatibel mit dem darunterliegenden Aufruf); tote
  Methode entfernen; CookieHandler-Parameter entfernen ODER tatsächlich
  verdrahten (Nutzerentscheidung)
Migration complexity: NIEDRIG (Telegram-Entkopplung, toter Code) / MITTEL
  (Cookie-Handling vereinheitlichen)
```

```text
Service: SpotifyDownloader (services/downloader/spotify_downloader.py)
Current responsibility: vollständige, EIGENSTÄNDIGE Spotify-Download-
  Pipeline (Embed-API-Metadaten ohne Spotify-Key, RSS-Feed-Fallback für
  Podcasts, yt-dlp-Fallback für Musik) — parallel zur YouTube-Pipeline
Actual responsibility: identisch. Teilt NICHTS mit dem YouTube-Kern (kein
  ArtistNormalizer, kein GenreProcessor, kein CoverProcessor, kein
  TagWriter, kein CacheManager/ChannelRouter/YearResolver) — die
  Metadaten-Anreicherung (Genre/Cover/Lyrics/Tags) passiert erst NACH
  SpotifyDownloader.download(), orchestriert von einer KOMPLETT SEPARATEN,
  zweiten Implementierung in klassen/download_handler.py
  (_process_single_download_result()), NICHT von download_utils.py
Dependencies: PodcastRSSManager (selbst konstruiert, nicht injiziert),
  urllib (Kurzlink-Auflösung), yt_dlp (indirekt über eigene
  _download_via_ytdlp_safe())
Consumers: klassen/download_handler.py
Side effects: Netzwerk-I/O (Spotify Embed-API, RSS, yt-dlp), Datei-Downloads
Problems: P-3 (doppelte, unabhängig gewachsene Orchestrierungs-Pipeline —
  die eigentliche "route raw download → EnhancedMetadataProcessor →
  DownloadResult"-Logik existiert zweimal: einmal sauber in
  download_utils.py [_process_track_metadata/_process_single_download],
  einmal in klassen/download_handler.py
  [_process_single_download_result] — das ist der größte strukturelle
  Befund dieser Analyse)
Target: langfristig sollte SpotifyDownloader NUR noch Metadaten/Audio
  BESCHAFFEN (analog DownloadExecutor) und die eigentliche Orchestrierung
  (Cache→Download→Metadaten→Ergebnis) durch dieselbe
  EnhancedDownloadProcessor-Pipeline laufen wie YouTube — das ist aber
  eine GROSSE, funktional riskante Änderung (siehe STOP-CONDITION)
Migration complexity: HOCH (nicht Teil des risikoarmen ersten Schritts)
```

```text
Service: StatistikService (services/statistik_service.py)
Current responsibility: Wiedergabeverlauf erfassen (Polling gegen
  Navidrome), persistieren (JSON pro Nutzer), Statistiken berechnen,
  Balkendiagramme rendern (matplotlib), JSON-Export
Actual responsibility: identisch — ein klassischer "God Service"
Dependencies: api.navidrome_api.NavidromeAPI (SELBST konstruiert im
  Konstruktor — self.api = NavidromeAPI() — genau das in Abschnitt 6 der
  Aufgabe als "nicht bevorzugt" benannte Muster), matplotlib.pyplot,
  Config (Klassen-Attribute direkt, kein Injection)
Consumers: bot.py, handlers/mugge_statistik_handler.py
Side effects: Datei-I/O (JSON-Verlauf, PNG-Charts), Navidrome-API-Polling
  (Hintergrund-Task via asyncio.create_task), Datei-Umbenennung bei
  korrupten Dateien
Problems: P-6 (vermischt 5 Verantwortlichkeiten: Persistenz, externer
  API-Client-Aufruf, Business-Statistik-Berechnung, Chart-Rendering,
  Hintergrund-Scheduling — direkt gegen Abschnitt 4 der Aufgabe),
  keine Dependency Injection für NavidromeAPI
Target: Aufteilen in mindestens: PlayHistoryRepository (Datei-Lesen/
  Schreiben/Cleanup), PlayHistoryPoller (Hintergrund-Task, ruft
  NavidromeAPI — injiziert statt selbst konstruiert), StatisticsCalculator
  (generate_stats/get_play_count_by_artist — reine Business-Logik, gut
  isoliert testbar), ChartRenderer (create_chart — matplotlib, einziger
  Ort mit dieser Abhängigkeit im ganzen Repo)
Migration complexity: MITTEL (kein Cross-Package-Problem, komplett
  innerhalb services/, aber 4 Consumer-Call-Sites in bot.py/
  mugge_statistik_handler.py müssen mitgezogen werden — de-facto ein
  Facade-Pattern in der Übergangsphase nötig)
```

```text
Service: IDownloaderConfig / IDownloader (services/downloader/interfaces.py)
Current responsibility (behauptet): abstrakte Config-/Downloader-Ports
Actual responsibility: KEINE — 0 Implementierer, 0 Verwendungen im
  gesamten Repo (verifiziert per Grep)
Problems: P-12 (Fake-Architektur — Interfaces ohne jede reale Bindung,
  im Gegensatz zu den echten, genutzten Protocols in
  download/interfaces.py)
Target: entfernen
Migration complexity: NIEDRIG
```

```text
Service: advanced_podcast_finder.py (services/downloader/advanced_podcast_finder.py)
Current responsibility: eigenständiges CLI-Recherche-Tool (Podcast-RSS-
  Feed-Suche über mehrere Quellen: requests, BeautifulSoup, ElementTree)
Actual responsibility: identisch — KEIN Service im Sinne der Aufgabe,
  kein Bot-Aufrufer, keine Service-zu-Service-Abhängigkeit
Dependencies: nur externe Bibliotheken (requests, bs4, yaml)
Consumers: keine (manuelles Tool)
Problems: liegt strukturell falsch unter services/downloader/ (kein
  Service, sondern ein Skript) — bereits in einer früheren Session-Phase
  bewusst nicht angefasst, da unklar ob der Nutzer es manuell noch
  verwendet
Target: NICHT Teil der Service-Architektur — Kandidat für einen
  eigenen tools/-Ordner AUSSERHALB von services/ (siehe STOP-CONDITION),
  oder Löschung nach Rückfrage
Migration complexity: N/A (keine Änderung ohne Nutzerentscheidung)
```

---

## 2. Dependency-Graph

### 2.1 Aktueller Zustand (nur services/-interne + wichtigste externe Kanten)

```text
downloader.py (YoutubeDownloader)
  ├─→ download_utils.py (enhanced_download_with_retry, EnhancedDownloadProcessor)
  ├─→ progress_tracker.py [ungenutzt konstruiert]
  ├─→ file_utils.py [ungenutzt konstruiert]
  ├─→ utils.filenamefixer (extern)
  └─→ cookie_handler.py (extern) [injiziert, ungenutzt]

download_utils.py (EnhancedDownloadProcessor)
  ├─→ enhanced_metadata_processor.py  (als MetadataEnricher-Protocol)
  ├─→ metadata/models.py
  ├─→ error_handler.py                (nur DownloadError-Klassen)
  ├─→ file_utils.py                   [ungenutzt konstruiert]
  ├─→ progress_tracker.py             [nur via init_tracker(), unreachable]
  ├─→ playlist_processor.py
  ├─→ download/{models,interfaces,cache_manager,year_resolver,
  │              channel_router,download_executor,formatters}.py
  └─→ utils.{artist_map,filenamefixer,metadata_cache} (extern zu services/)

enhanced_metadata_processor.py (Composition Root Metadaten-Pipeline)
  ├─→ metadata/{models,cache,artist_processor,title_cleaner,genre_processor,
  │              album_processor,lyrics_processor,cover_processor,
  │              auto_learn,tag_writer}.py
  ├─→ file_utils.py                   [Parameter durchgereicht, ungenutzt]
  ├─→ klassen.genius_client.GeniusClient   ⚠️ services → klassen (siehe P-11)
  └─→ utils.{artist_map,genre_map,youtube_parser,filenamefixer,
             metadata_cache,singleton} (extern zu services/)

download_result_reporter.py
  └─→ handlers.duplicate_handler.DuplicateEntry   ⚠️ services → handlers (P-2)

spotify_downloader.py
  └─→ utils.podcast_rss_manager.PodcastRSSManager (extern zu services/)
      (KEINE Verbindung zu enhanced_metadata_processor.py / download_utils.py
       innerhalb von services/ — die Verbindung existiert erst außerhalb,
       in klassen/download_handler.py — siehe P-3)

statistik_service.py
  └─→ api.navidrome_api.NavidromeAPI   (extern zu services/, selbst
                                         konstruiert statt injiziert)

interfaces.py (top-level)               [isoliert, 0 Kanten — toter Code]
advanced_podcast_finder.py              [isoliert, 0 Kanten zu services/]
```

**Keine Zyklen gefunden** innerhalb von `services/`. Die einzigen "falsch gerichteten" Kanten sind die beiden markierten (`services → handlers`, `services → klassen` für einen reinen API-Client).

### 2.2 Wer importiert `services/` von außen (Consumer-Seite)

```text
klassen/download_handler.py  → YoutubeDownloader, SpotifyDownloader,
                                 EnhancedMetadataProcessor (Typ-Referenz),
                                 DownloadResultReporter, FileUtils,
                                 ProgressTracker
bot.py                       → StatistikService
handlers/mugge_statistik_handler.py → StatistikService
utils/filenamefixer.py       → (keine Rückimporte gefunden — sauber)
```

---

## 3. Problem List (priorisiert)

| # | Problem | Schweregrad | Kategorie |
|---|---|---|---|
| P-1 | `FileUtils` komplett unbenutzt, aber breit durchgereicht (`clean_temp_files()` läuft nie) | **Hoch** (operationelles Risiko: unbegrenztes Temp-Wachstum) | Totes Gewicht / Side-Effect-Lücke |
| P-2 | Telegram-Kopplung in `services/`: `progress_tracker.py`, `download_result_reporter.py` (+ `error_handler.py` Teil B, + `downloader.py`-Konstruktor) | **Hoch** (Kernverstoß gegen Abschnitt 3 der Aufgabe) | Schichtenvermischung |
| P-3 | Zwei unabhängige Orchestrierungs-Implementierungen (YouTube in `download_utils.py`, Spotify in `klassen/download_handler.py`) für dieselbe fachliche Aufgabe | **Hoch** (Wartungsrisiko, Verhaltensdrift zwischen beiden Pfaden) | Duplikation / fehlende gemeinsame Abstraktion |
| P-4 | `error_handler.py` Teil B (Telegram-Handler-Funktionen) komplett tot, ersetzt durch `handlers/enhanced_error_handler.py` | Mittel | Totes Gewicht |
| P-5 | `downloader.py::format_download_result_for_log()` syntaktisch/logisch kaputt (fehlendes `self`, undefinierte Variable `lines`), 0 Aufrufer | Niedrig (nie ausgeführt) | Toter/kaputter Code |
| P-6 | `StatistikService` — God Service (5 vermischte Verantwortlichkeiten) | Mittel (funktioniert, aber schwer isoliert testbar/änderbar) | Schichtenvermischung |
| P-7 | Kein externer Composition Root — jede Orchestrator-Klasse konstruiert ihre eigenen Kinder in `_do_init()` statt sie injiziert zu bekommen | Niedrig (bewusst notiert, siehe Bewertung unten) | Dependency Injection |
| P-8 | Einzelne Services lesen `Config`/erstellen ihre Sub-Dependencies direkt statt injiziert zu bekommen (`PlaylistProcessor.__init__` importiert `config.Config` selbst; `StatistikService.__init__` konstruiert `NavidromeAPI()` selbst; `SpotifyDownloader.__init__` konstruiert `PodcastRSSManager` selbst) | Niedrig–Mittel | Dependency Injection |
| P-9 | Cookie-Handling doppelt/inkonsistent: `CookieHandler`-Klasse injiziert aber nie benutzt, echte Erkennung hartkodiert (`Path("cookies.txt")`) in `download_executor.py` | Niedrig | Duplikation / totes DI |
| P-10 | `CoverProcessor`/`GenreProcessor` mischen externen API-Zugriff mit Bewertungs-/Scoring-Logik | Niedrig (funktioniert, testbar, aber kein Provider/Port-Schnitt) | Schichtenvermischung (mild) |
| P-11 | `enhanced_metadata_processor.py` importiert `klassen.genius_client.GeniusClient` — ein reiner API-Client, der strukturell besser neben `api/navidrome_api.py` läge, aber unter `klassen/` liegt | Niedrig (kein echter Zyklus, aber unsaubere Grenzlinie) | Cross-Package-Abhängigkeit außerhalb `services/` |
| P-12 | `services/downloader/interfaces.py` (`IDownloaderConfig`, `IDownloader`) — Fake-Architektur, 0 Implementierer/Verwendungen | Niedrig | Toter Code |
| P-13 | `download_utils.py::download_with_retry()` (Legacy-Wrapper) und `TrackDownloadState` (Modell) — 0 Aufrufer | Niedrig | Toter Code |
| P-14 | `advanced_podcast_finder.py` liegt strukturell unter `services/downloader/`, ist aber kein Service | Niedrig | Fehlplatzierung |

---

## 4. Zielstruktur (Vorschlag — siehe offene Entscheidungen in Abschnitt 5)

```text
services/
├── downloader/
│   ├── youtube/                        # (Rename von services/downloader/download/)
│   │   ├── models.py                   # DownloadResult, PlaylistResult
│   │   ├── interfaces.py               # CacheProvider, MetadataEnricher (bereits gut)
│   │   ├── cache_manager.py
│   │   ├── year_resolver.py
│   │   ├── channel_router.py
│   │   ├── download_executor.py        # einziger echter Infra-Adapter (yt-dlp)
│   │   └── formatters.py
│   ├── metadata/                       # unverändert (bereits vorbildlich)
│   │   ├── models.py
│   │   ├── cache.py
│   │   ├── artist_processor.py
│   │   ├── title_cleaner.py
│   │   ├── genre_processor.py
│   │   ├── album_processor.py
│   │   ├── lyrics_processor.py
│   │   ├── cover_processor.py
│   │   ├── auto_learn.py
│   │   └── tag_writer.py
│   ├── playlist_processor.py
│   ├── enhanced_metadata_processor.py  # Composition Root Metadaten-Pipeline
│   ├── download_orchestrator.py        # (Rename von download_utils.py —
│   │                                      reine Orchestrierung, keine
│   │                                      Telegram-/Presentation-Reste mehr)
│   ├── spotify_downloader.py           # unverändert im ersten Schritt
│   │                                      (P-3-Fix ist Phase 2/3, siehe unten)
│   └── errors.py                       # (Rename von error_handler.py,
│                                          NUR Teil A: DownloadError+Subklassen)
├── statistik/                          # (Aufteilung von statistik_service.py)
│   ├── play_history_repository.py
│   ├── play_history_poller.py
│   ├── statistics_calculator.py
│   └── chart_renderer.py
└── (services/downloader/utils/file_utils.py — ENTFERNT oder nach P-1-
     Entscheidung reaktiviert; verbleibt sonst nirgends)

ENTFERNT aus services/ (nach Migration in handlers/ bzw. Löschung):
  - progress_tracker.py           → handlers/ (falls reaktiviert) oder gelöscht
  - download_result_reporter.py   → handlers/ (reine Verschiebung)
  - error_handler.py Teil B       → gelöscht (tot, ersetzt)
  - interfaces.py (IDownloaderConfig/IDownloader) → gelöscht
  - advanced_podcast_finder.py    → tools/ (außerhalb services/) oder gelöscht,
                                     nur nach Nutzerentscheidung
```

---

## 5. Offene Entscheidungen (STOP CONDITIONS — Abschnitt 21 des Auftrags)

Diese Punkte kann ich nicht ohne Rückfrage entscheiden, weil sie entweder
(a) eine Wahl zwischen grundsätzlich verschiedenen Architekturmodellen sind,
(b) eine Verhaltensänderung der laufenden Produktions-Pipeline bedeuten würden, oder
(c) zwingend Änderungen außerhalb von `services/` erfordern:

1. **P-1 (`FileUtils`)**: entfernen (totes Gewicht beseitigen) oder reaktivieren
   (`clean_temp_files()` tatsächlich periodisch aufrufen)? Reaktivieren ändert
   reales Laufzeitverhalten (neue, bisher nie ausgeführte Datei-Löschungen).
   → Bereits einmal gefragt in dieser Session, Antwort war „vorerst nichts tun“.
   Für DIESE Migration heißt das: Code bleibt bestehen, wird aber laut
   Zielarchitektur als klar isolierter, expliziter „ungenutzter Baustein“
   markiert statt in jede Pipeline-Funktion durchgereicht.

2. **P-2 (Telegram-Kopplung entfernen)**: `progress_tracker.py` und
   `download_result_reporter.py` gehören laut Aufgabe NICHT in `services/`.
   Sie zu verschieben heißt zwangsläufig, `klassen/download_handler.py`
   (Consumer, liegt außerhalb `services/`) anzupassen — das verstößt gegen
   „keine großflächigen Änderungen außerhalb von services/“, ist aber ohne
   Consumer-Anpassung nicht sauber möglich. **Optionen:**
   - (a) Nur innerhalb von `services/` grundlegend aufräumen (P-1/P-4/P-5/P-12/P-13
     entfernen, P-8 nachziehen) und die Telegram-gekoppelten Klassen VORERST
     an Ort und Stelle lassen, aber klar als „Migrations-Kandidat für
     handlers/“ markieren (Doku, keine Verschiebung) — **risikoärmster erster
     Schritt**.
   - (b) Verschieben nach `handlers/`, inkl. der nötigen (kleinen, mechanischen)
     Import-Anpassung in `klassen/download_handler.py` — sauberer, aber
     verletzt „keine parallele Komplettmigration außerhalb von services/“
     im Wortsinn.

3. **P-3 (doppelte Spotify/YouTube-Orchestrierung)**: der größte einzelne
   Befund, aber eine Vereinheitlichung wäre ein **substanzieller
   Verhaltens-Eingriff** in den produktiven Spotify-Downloadpfad (P0-Bereich
   laut CLAUDE.md) — nicht ohne dedizierte Planung/Tests machbar. Empfehlung:
   **nicht Teil dieses ersten Schritts**, sondern als eigene, spätere
   Migrationsphase dokumentieren.

4. **P-6 (`StatistikService` aufteilen)**: komplett innerhalb `services/`
   möglich, aber `bot.py`/`handlers/mugge_statistik_handler.py` (außerhalb
   `services/`) müssten für den neuen API-Schnitt angepasst werden, wenn die
   öffentliche Schnittstelle sich ändert. **Kompromiss:** intern aufteilen,
   aber eine `StatistikService`-Fassade behalten, die die 4 neuen Klassen
   zusammenführt und exakt dieselbe öffentliche API wie heute anbietet
   (Consumer bleiben unverändert) — als „temporäre Migrations-Brücke“
   markiert, siehe Abschnitt 14 der Aufgabe.

5. **P-11 (`klassen.genius_client` Import)**: strukturell falsch, aber die
   Datei liegt außerhalb `services/` — kann in diesem Schritt nur
   dokumentiert, nicht verschoben werden.

6. **P-14 (`advanced_podcast_finder.py`)**: wie in einer früheren Session-Phase
   bereits festgehalten — eigenständiges CLI-Tool, unklar ob vom Nutzer noch
   manuell verwendet. Nicht ohne Rückfrage löschen oder verschieben.

---

## 6. Empfehlung für den konkreten nächsten Schritt

Gegeben die Menge an echten STOP CONDITIONS oben, empfehle ich, den
**risikoarmen Kern zuerst** umzusetzen (Phase 2/3 dieser Migration,
ausschließlich innerhalb `services/`, keine Consumer-Änderungen nötig):

- P-4 entfernen (tote Telegram-Funktionen in `error_handler.py`)
- P-5 entfernen (kaputte tote Methode in `downloader.py`)
- P-12 entfernen (`interfaces.py` — tote Fake-Interfaces)
- P-13 entfernen (`download_with_retry()`, `TrackDownloadState`)
- P-8 nachziehen für `PlaylistProcessor`/`SpotifyDownloader` (Config bzw.
  `PodcastRSSManager` injizierbar machen, Default-Verhalten unverändert)
- `error_handler.py` → `errors.py` umbenennen (nur Teil A bleibt übrig)
- P-9 optional: `cookies.txt`-Pfad aus Config statt hartkodiert

Alles, was Consumer außerhalb von `services/` berührt (P-1-Entscheidung,
P-2, P-3, P-6-Fassade), sollte **erst nach deiner Entscheidung zu Abschnitt 5**
angegangen werden.

**Diese Empfehlung ist eine Vorschlagsliste, keine bereits getroffene
Entscheidung.** Bevor ich Code ändere, brauche ich dein Go für: den Umfang
(nur risikoarmer Kern vs. auch P-2/P-6-Fassade) und die Antworten zu P-1/P-2/P-3.
