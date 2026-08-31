# ARCH-020 – Download Pipeline Characterization & Orchestration Boundary

**Typ:** Reine Characterization (keine Produktions-/Test-/Mapping-Änderungen, kein Commit, kein Push)
**Auftragsdatei:** `docs/ARCH-020_Phase.md` (bereits vor dieser Session committet, `6a450e0`)
**Basis:** `main` @ `3abeef7` (nach PR #48, TitleCleaner-Fixes)

> **Hinweis zur Nummerierung:** In dieser Session wurde zuvor irrtümlich eine andere,
> unabhängige Charakterisierung (Genre-Client-/Last.fm-Duplikation) ebenfalls als
> "ARCH-020" bezeichnet, ohne vorher zu prüfen, ob die Nummer bereits reserviert war. Diese
> Datei hier ist die tatsächliche, bereits vor Sessionbeginn geplante ARCH-020 (Download-
> Pipeline). Die Kollision wurde geklärt: die Genre-Client-Duplikations-Doku wurde auf
> ausdrücklichen Nutzerwunsch zu `docs/archive/arch/MusicBot_ARCH-021_Genre_Client_Duplication_Characterization.md`
> umbenannt (siehe Abschlussnotiz am Ende). Diese Kollision hat keinen Einfluss auf den Inhalt
> dieses Berichts.

---

## 1. Executive Summary

Die Download-Pipeline ist **bereits deutlich sauberer strukturiert als ihre Telegram-seitige
Fassade (`klassen/download_handler.py`) vermuten lässt**. Der überwiegende Teil der
fachlichen/technischen Orchestrierung – Cache-Lookup, Channel-Routing, Jahres-Bestimmung,
Metadaten-Anreicherung, Cover, Lyrics, Audio-Normalisierung, Library-Verschiebung – ist bereits
in klar abgegrenzte, Telegram-freie, Dependency-injizierte Komponenten unter
`services/downloader/` und `services/metadata/` extrahiert, jeweils mit eigenen
Characterization-/Unit-Tests (124 gezielt nachgewiesen grün).

Der zentrale Befund ist **kein Strukturproblem, sondern ein Label-/Dokumentations-Problem**:
`klassen/download_handler.py::handle_url()` meldet dem Nutzer sechs Telegram-Fortschritts-Schritte
("STEP 1/6" … "STEP 6/6"), von denen jedoch für YouTube-Downloads nur STEP 1, 2 und 6 tatsächlich
Arbeit in `DownloadHandler` selbst auslösen. STEP 3 delegiert vollständig an
`services/downloader/download_utils.py::enhanced_download_with_retry()`, welches **den gesamten
Download- UND Metadaten-Workflow** (inkl. Genre, Lyrics, Cover, Audio-Normalisierung,
Library-Verschiebung) bereits selbst ausführt, bevor die Kontrolle an `DownloadHandler`
zurückgeht. STEP 4 ("Metadaten anreichern") ist für YouTube-Ergebnisse dadurch ein **bewusst
geguardeter No-Op-Durchlauf** (`_process_single_download_result()`, Punkt B:
"Doppelverarbeitungs-Schutz"). Für **Spotify**-Ergebnisse hingegen ist genau derselbe Methodenaufruf
die **einzige, echte** Metadaten-Verarbeitung, da `SpotifyDownloader` selbst keinen
`EnhancedMetadataProcessor`-Aufruf enthält. `_process_single_download_result()` ist damit ein
bewusster, funktionierender Konvergenzpunkt für zwei strukturell unterschiedliche Herkunftspfade –
keine versehentliche doppelte Verarbeitung, aber eine nicht auf den ersten Blick erkennbare
Doppelrolle.

CLAUDE.md §4 zeichnet die Pipeline vereinfacht als `DownloadHandler → YouTube/Spotify → Metadata
Pipeline` (sequenziell, mit `DownloadHandler` als Klammer). Der tatsächliche Code zeigt: die
Metadata-Pipeline läuft für YouTube **innerhalb** des Download-Schritts (in `download_utils.py`,
nicht in `DownloadHandler`), nicht danach. Das ist eine dokumentierte Divergenz (Abschnitt 7),
keine Fehlfunktion.

**Wichtigstes Ergebnis (Abschnitt 17):** **C) Nein – aktuelle Struktur ist ausreichend.** Kein
großer Download-Refactor ist gerechtfertigt. Empfohlen wird ausschließlich eine **Dokumentations-
und Label-Korrektur** (kleinster sinnvoller Schritt, siehe Abschnitt 17/18).

---

## 2. Architekturhistorie

Relevante frühere Entscheidungen, die die Download-Pipeline betreffen:

| ARCH-Dokument | Relevanz |
|---|---|
| ARCH-004 P3 (`MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md`) | Extrahierte `metadata_result_translator.py` als gemeinsame Integrationsschicht aus drei unabhängig gewachsenen Metadaten-Aufrufstellen (YT-Playlist, YT-Single, Spotify). Diese Struktur ist **weiterhin aktiv und referenziert** (siehe Abschnitt 6). |
| ARCH-007 P2 | `services/` telegram-frei gemacht — `ProgressTracker` und `DownloadResultReporter` tragen das explizit im Docstring ("keine Telegram-Abhängigkeit mehr"). Bestätigt unverändert gültig. |
| ARCH-009 (mehrphasig) | Schichtgrenzen `handlers/services/klassen/utils` etabliert (CLAUDE.md §4). Bildet die Grundlage für den Dependency-Audit in Abschnitt 12. |
| ARCH-011 (`Downloader_Download_Analyse.md`) | Frühere Analyse von `services/downloader/download/` — die dort beschriebenen Module (`cache_manager.py`, `channel_router.py`, `year_resolver.py`, `download_executor.py`, `formatters.py`) existieren unverändert mit Single-Responsibility-Docstrings. |
| ARCH-017 | `utils/audio_enhancer.py` — nur `normalize_loudness()`/`get_target_lufs()` sind aktiv, kein Netzwerk. Bestätigt unverändert (Abschnitt 5, Komponente `AudioEnhancer`). |
| ARCH-018 | `services/duplicate/{cache,detector}.py` extrahiert, `klassen → handlers`-Reverse-Edge aufgelöst. **Wird als Referenzmuster behandelt, nicht zurückgebaut** (Auftragsvorgabe §12). |
| ARCH-019 / ARCH-020 (Genre) | `GenreProcessor` ist alleinige Genre-Entscheidungsinstanz, Clients liefern nur rohe Tags. Bestätigt unverändert (Abschnitt 5). |
| "AUTOLEARN-001" (Code-Kommentar, `download_utils.py`) | Bereits behobene, frühere Doppel-Verarbeitung (redundanter externer Auto-Learn-Aufruf entfernt, da `process_single_track()` dies intern erledigt) — historischer Beleg, dass diese Art Befund in diesem Projekt bereits einmal real war und korrekt behoben wurde. |

Kein Widerspruch zwischen diesen Dokumenten und dem aktuellen Code gefunden — mit der einen
Ausnahme CLAUDE.md §4 (siehe Abschnitt 7).

---

## 3. Aktuelle Download-Pipeline (End-to-End, YouTube-Single, aus echtem Produktionslog + Code verifiziert)

```
Telegram (User schickt YouTube-URL)
  ↓
RichMenuHandler.handle_url() → DownloadHandler.handle_url()
  ↓
[STEP 1/6] URL & Format prüfen           (DownloadHandler, echte Arbeit)
  ↓
[STEP 2/6] Duplikat-Check                (DownloadHandler → DuplicateDetector, echte Arbeit)
  ↓
[STEP 3/6] Audio-Download                (DownloadHandler → YoutubeDownloader.download_audio())
  │           ↓
  │         download_utils.py::enhanced_download_with_retry()   ◄── REALER ORCHESTRATOR
  │           ├─ DownloadExecutor.extract_info_async() (yt-dlp, download=False)
  │           ├─ Single erkannt → _process_single_download()
  │           │     ├─ CacheManager.lookup_single_track()
  │           │     ├─ DownloadExecutor.extract_info_async(download=True)  (yt-dlp Audio-DL)
  │           │     └─ call_process_single_track(EnhancedMetadataProcessor, ...)
  │           │           ├─ YouTube-Titel-Parsing (utils/youtube_parser.py)
  │           │           ├─ Artist-Bestimmung (ArtistNormalizer / ArtistProcessor)
  │           │           ├─ Titel-Bereinigung (TitleCleaner)
  │           │           ├─ Genre (GenreProcessor → MusicBrainzClient + LastFMClient)
  │           │           ├─ Lyrics (LyricsProcessor → GeniusClient)
  │           │           ├─ Cover (CoverProcessor, 9 Quellen, Early-Exit)
  │           │           ├─ Album/Jahr (AlbumProcessor → MusicBrainzClient)
  │           │           ├─ Audio-Normalisierung (AudioEnhancer.normalize_loudness, FFmpeg)
  │           │           ├─ Tags schreiben (TagWriter)
  │           │           └─ Library-Verschiebung (FilenameFixerTool) → library_path gesetzt
  │           └─ Rückgabe: dict mit library_path, KEIN filepath mehr
  ↓ (Kontrolle zurück an DownloadHandler)
[STEP 4/6] "Metadaten anreichern"        (DownloadHandler._process_single_download_result())
              → Punkt B "Doppelverarbeitungs-Schutz": library_path bereits gesetzt,
                filepath nicht mehr vorhanden → GUARD GREIFT → No-Op, gibt result unverändert zurück
  ↓
[STEP 5/6] "Bibliothek"                  (Label ohne eigene Arbeit — Library-Move geschah
                                           bereits innerhalb STEP 3)
  ↓
[STEP 6/6] "Zusammenfassung"             (DownloadHandler.handle_single_track_success():
                                           echte Arbeit — DuplicateDetector.register_download(),
                                           DownloadResultReporter.build_final_summary_message())
  ↓
Telegram-Ergebnis-Nachricht an User
```

**Für Spotify (`handle_spotify_url()`, strukturell parallel, Zeilen ~800–935):** identische
STEP-1-6-Struktur, aber `SpotifyDownloader` ruft `EnhancedMetadataProcessor` **nicht** selbst auf
(0 Treffer, Abschnitt 5/9). Für Spotify-Ergebnisse ist STEP 4
(`_process_single_download_result()`, Punkt G) daher die **tatsächliche, einzige** Stelle, an der
`EnhancedMetadataProcessor` aufgerufen wird — Punkt B greift hier nicht (kein `library_path`
vorab gesetzt).

**Für Playlists:** dieselbe Struktur wie Single, aber `download_utils.py::_process_playlist_download()`
verarbeitet jeden Track einzeln über `_process_track_metadata()` → ebenfalls
`call_process_single_track()` → ebenfalls `library_path` gesetzt vor Rückgabe. Der
Doppelverarbeitungs-Schutz greift somit auch hier für jeden einzelnen Playlist-Track.

---

## 4. Current Call Graph (tatsächliche Klassen/Methoden)

```
DownloadHandler.handle_url()
 ├─ DownloadHandler._check_duplicates_before_download()
 │   └─ DuplicateDetector.check_for_duplicates()                    [services/duplicate/detector.py]
 ├─ YoutubeDownloader.download_audio()                               [services/downloader/downloader.py]
 │   └─ download_utils.enhanced_download_with_retry()                [services/downloader/download_utils.py]
 │       ├─ EnhancedDownloadProcessor (Singleton, DI-Container)
 │       ├─ DownloadExecutor.build_ydl_opts() / extract_info_async() [services/downloader/download/download_executor.py]
 │       ├─ _process_single_download()  ODER  _process_playlist_download()
 │       │   ├─ CacheManager.lookup_single_track() / lookup_playlist_track() [.../cache_manager.py]
 │       │   ├─ PlaylistProcessor.process_playlist_metadata()        [services/downloader/playlist_processor.py] (nur Playlist)
 │       │   ├─ ChannelRouter.resolve_dominant_artist()               [.../channel_router.py] (nur Playlist)
 │       │   ├─ YearResolver.resolve_playlist_year()                  [.../year_resolver.py] (nur Playlist)
 │       │   ├─ DownloadExecutor.download_single_track()              [.../download_executor.py] (nur Playlist)
 │       │   └─ metadata_result_translator.call_process_single_track()
 │       │       └─ EnhancedMetadataProcessor.process_single_track()  [services/metadata/enhanced_metadata_processor.py]
 │       │           ├─ youtube_parser.parse_youtube_title()          [utils/youtube_parser.py]
 │       │           ├─ ArtistProcessor.determine_best_artist()       [services/metadata/artist_processor.py]
 │       │           ├─ TitleCleaner.clean_track_title_enhanced()     [services/metadata/title_cleaner.py]
 │       │           ├─ GenreProcessor.determine_genre_with_fallbacks() [services/metadata/genre_processor.py]
 │       │           │   ├─ MusicBrainzClient.fetch_metadata()        [services/clients/musicbrainz_client.py]
 │       │           │   └─ LastFMClient.fetch_metadata()             [services/clients/lastfm_client.py]
 │       │           ├─ LyricsProcessor.fetch_lyrics_with_fallback()  [services/metadata/lyrics_processor.py]
 │       │           │   └─ GeniusClient                              [services/clients/genius_client.py]
 │       │           ├─ CoverProcessor.get_cover_art()                [services/metadata/cover_processor.py]
 │       │           ├─ AlbumProcessor.fetch_album_from_musicbrainz() [services/metadata/album_processor.py]
 │       │           ├─ AudioEnhancer.normalize_loudness()            [utils/audio_enhancer.py]
 │       │           ├─ TagWriter                                    [services/metadata/tag_writer.py]
 │       │           ├─ AutoLearnManager.learn_artist()               [services/metadata/auto_learn.py]
 │       │           └─ FilenameFixerTool (Library-Verschiebung)      [utils/filenamefixer.py]
 ├─ DownloadHandler._process_single_download_result()   (Guard / für Spotify: echte Arbeit)
 └─ DownloadHandler.handle_single_track_success()
     ├─ DuplicateDetector.register_download()
     └─ DownloadResultReporter.build_final_summary_message()          [services/downloader/download_result_reporter.py]
```

---

## 5. Komponentenmatrix

| Komponente | Verantwortung | Aufgerufen von | Ruft auf | Fachlich/Technisch | Seiteneffekte | Zielrolle |
|---|---|---|---|---|---|---|
| `DownloadHandler` | Telegram-Dispatch, URL-Vortyp-Erkennung, Progress-UI, Post-hoc-Registrierung/Reporting | `RichMenuHandler` | `YoutubeDownloader`, `SpotifyDownloader`, `DuplicateDetector`, `_process_single_download_result` | Application/Presentation-Mix | Telegram-Status-Nachrichten | **Telegram-Orchestrator/Reporter** (nicht der Metadaten-Orchestrator) |
| `YoutubeDownloader` | Dünner Adapter zu `enhanced_download_with_retry()` | `DownloadHandler` | `download_utils.enhanced_download_with_retry` | Application (dünn) | keine eigenen | Acquisition-Adapter |
| `download_utils.py` (`enhanced_download_with_retry`, `_process_*`) | **Realer Orchestrator** des gesamten Download+Metadaten-Workflows pro Track | `YoutubeDownloader` | fast alle Sub-Komponenten | Application/Orchestration | Dateisystem (Download), Netzwerk (yt-dlp) | Application/Workflow (bereits korrekt positioniert) |
| `DownloadExecutor` | yt-dlp-Wrapper (Optionen, Extraktion, Download) | `download_utils.py` | `yt-dlp`, `filenamefixer` (Pfad-Sanitizing) | Infrastructure | Netzwerk, Dateisystem; läuft async korrekt via `run_in_executor` | Infrastructure-Adapter (bereits korrekt) |
| `EnhancedDownloadProcessor` | DI-Container/Singleton, hält alle Sub-Komponenten-Instanzen | `download_utils.py`-Funktionen | initialisiert alle unten stehenden | Application (Compositionsroot) | keine eigenen | bereits korrekt |
| `PlaylistProcessor` | Playlist-Metadaten-Vorverarbeitung (Album, Track-Liste) | `_process_playlist_download` | `utils.artist_map`, `utils.youtube_parser` | Domain (Playlist-Regeln) | keine | bereits korrekt |
| `ChannelRouter` | 5-stufige Artist/Channel-Entscheidung (P1–P5) | `_process_playlist_download` | `ArtistNormalizer`, Spezialkanal-YAML | Domain | keine | bereits korrekt |
| `YearResolver` | Jahres-Bestimmung (4 Quellen-Prioritäten) | `_process_playlist_download` | keine externen | Domain | keine | bereits korrekt |
| `CacheManager` | 2-stufiger Cache-Lookup (nur Lesen) | `_process_single/playlist_download` | `MetadataCache`, `ArtistNormalizer` | Infrastructure (Cache) | keine (read-only) | bereits korrekt |
| `ProgressFormatter` | ASCII-Log-Formatierung | `download_utils.py` | keine | Presentation (Log, nicht Telegram) | keine | bereits korrekt |
| `ProgressTracker` | Fortschritts-Text-Berechnung, sendet selbst nichts (Telegram-frei seit ARCH-007) | `download_utils.py` (indirekt) | keine | Application (reine Berechnung) | keine | bereits korrekt |
| `SpotifyDownloader` | Spotify-Embed-API + yt-dlp-Download; **kein** eigener Metadaten-Aufruf | `DownloadHandler.handle_spotify_url` | yt-dlp, Spotify-Embed-API | Application+Infrastructure-Mix | Netzwerk, Dateisystem | Acquisition-Adapter (asymmetrisch zu YT — siehe Abschnitt 14) |
| `DownloadResultReporter` | Formatiert Abschluss-/Duplikat-/Playlist-Nachrichten als reinen Text, kein Versand | `DownloadHandler` | keine | Application/Presentation-Vorbereitung | keine (reine Textausgabe) | bereits korrekt (Telegram-frei seit ARCH-007) |
| `metadata_result_translator.py` | Gemeinsame Integrationsschicht: ruft `process_single_track()`, übersetzt `MetadataResult` in 2 Zielformate | `download_utils.py` (2×), `download_handler.py` (1×) | `EnhancedMetadataProcessor` | Application (Übersetzungsschicht) | keine eigenen | bereits korrekt (ARCH-004 P3) |
| `DuplicateDetector` / `DuplicateCache` | Fachliche Duplicate-Entscheidung + Persistenz | `DownloadHandler`, `EnhancedDuplicateHandler` | Dateisystem (JSON-Cache) | Domain | Cache-Datei-I/O | bereits korrekt (ARCH-018) |
| `MusicBrainzClient` | reiner API-Adapter, liefert rohe Tags | `GenreProcessor`, `AlbumProcessor` | MusicBrainz-API | Infrastructure | Netzwerk | bereits korrekt (ARCH-019) |
| `GeniusClient` | reiner API-Adapter (Lyrics) | `LyricsProcessor` | Genius-API | Infrastructure | Netzwerk | bereits korrekt |
| `LastFMClient` | reiner API-Adapter, liefert rohe Tags | `GenreProcessor` | Last.fm-API | Infrastructure | Netzwerk | bereits korrekt (ARCH-019) |
| `GenreProcessor` | alleinige Genre-Entscheidung (`prioritize_genres`) | `EnhancedMetadataProcessor` | `GenreMapper`, MB-/LFM-Clients | Domain | keine eigenen | bereits korrekt |
| `GenreMapper` | YAML-Mapping-Logik (Alias/Hierarchie/Idempotenz) | `GenreProcessor` | Mapping-YAMLs | Domain | keine | bereits korrekt (ARCH-013–016) |
| `LyricsProcessor` | Lyrics-Fallback-Orchestrierung | `EnhancedMetadataProcessor` | `GeniusClient` | Domain (dünn) | keine eigenen | bereits korrekt |
| `CoverProcessor` | Multi-Source-Cover-Beschaffung + Scoring | `EnhancedMetadataProcessor` | 6 externe APIs (siehe ARCH-020-Genre-Doku) | Domain+Infrastructure-Mix | Netzwerk, lokaler Bild-Cache | überwiegend korrekt (bekannter Last.fm-Key-Befund separat dokumentiert) |
| `AudioEnhancer` | nur noch Loudness-Normalisierung (FFmpeg) | `EnhancedMetadataProcessor` | `ffmpeg` (Subprocess) | Infrastructure | Dateisystem, Subprocess | bereits korrekt (ARCH-017) |
| `TagWriter` | schreibt finale Audio-Tags | `EnhancedMetadataProcessor` | `mutagen` | Infrastructure | Dateisystem | bereits korrekt |
| `FilenameFixerTool` | Zielpfad-Bestimmung + Library-Verschiebung | `EnhancedMetadataProcessor`, `download_utils.py` | Dateisystem, Spezialkanal-YAML | Domain (Library-Regeln) + Infrastructure (I/O) | Dateisystem-Verschiebung | bereits korrekt |
| relevante Caches (`MetadataCache`, `DuplicateCache`, `LyricsCache`) | Persistenz | jeweilige Owner | Dateisystem (JSON) | Infrastructure | Datei-I/O | bereits korrekt |

---

## 6. Orchestrierungsanalyse — Wer orchestriert tatsächlich?

Beantwortung der Auftragsfragen direkt:

- **Wer startet den Workflow?** `DownloadHandler.handle_url()` / `handle_spotify_url()` (Telegram-Trigger).
- **Wer entscheidet über den nächsten Verarbeitungsschritt?** Für den Kern (Download → Metadaten
  → Library) entscheidet **`download_utils.py`** intern (Retry-Loop, Playlist-vs-Single-Verzweigung,
  Cache-Hit-vs-Miss). `DownloadHandler` entscheidet nur über die vorgelagerten Schritte
  (Duplikat-Precheck) und nachgelagerten Schritte (Registrierung, Reporting).
- **Wer besitzt Retry-Logik?** `download_utils.enhanced_download_with_retry()` (exponentielles
  Backoff, `max_retries`). `DownloadHandler` hat keine eigene Retry-Logik.
- **Wer besitzt Download-Logik?** `DownloadExecutor` (yt-dlp) bzw. `SpotifyDownloader`
  (Spotify-Embed-API + yt-dlp).
- **Wer besitzt Metadata-Orchestrierung?** `EnhancedMetadataProcessor.process_single_track()`
  (aufgerufen über `metadata_result_translator.call_process_single_track()`), für YouTube
  ausgelöst aus `download_utils.py`, für Spotify ausgelöst aus `DownloadHandler`.
- **Wer besitzt Library-Organisation?** `FilenameFixerTool`, aufgerufen **innerhalb**
  `EnhancedMetadataProcessor.process_single_track()` — nicht separat von `DownloadHandler`.
- **Wer besitzt Reporting?** `DownloadResultReporter` (Text-Formatierung) +
  `DownloadHandler` (tatsächlicher Telegram-Versand, bewusst getrennt seit ARCH-007).
- **Wer besitzt Persistence?** `DuplicateCache`/`MetadataCache`/`LyricsCache`, jeweils eigene
  Klassen unter `services/`/`utils/`.
- **Wo werden Ergebnisse zusammengeführt?** In `download_utils.py` (pro Track) und erneut
  (No-Op für YT, real für Spotify) in `DownloadHandler._process_single_download_result()`.

### CURRENT ORCHESTRATION GRAPH

```
┌─────────────────────┐
│   DownloadHandler    │  Telegram-Fassade: URL-Erkennung, Duplikat-Precheck,
│  (klassen/, async)   │  Progress-Labels, Post-hoc-Registrierung + Reporting
└─────────┬────────────┘
          │ delegiert Kernarbeit vollständig
          ▼
┌──────────────────────────────┐
│  download_utils.py           │  ECHTER Orchestrator: Retry, Cache-Entscheidung,
│  enhanced_download_with_retry│  Playlist-vs-Single, ruft Metadaten-Pipeline auf,
│  (services/downloader/)      │  Library-Verschiebung geschieht hier bereits
└─────────┬─────────────────────┘
          │ pro Track
          ▼
┌──────────────────────────────┐
│ EnhancedMetadataProcessor      │  Metadaten-Fachorchestrator: Genre/Lyrics/Cover/
│ .process_single_track()        │  Album/Audio/Tags/Library — 20 durchnummerierte
│ (services/metadata/)           │  interne Schritte (Log-Marker 1️⃣–2️⃣0️⃣)
└────────────────────────────────┘
```

**Fazit:** Es gibt **zwei** echte Orchestratoren (`download_utils.py` für Download+Verzweigung,
`EnhancedMetadataProcessor` für Metadaten), nicht einen. `DownloadHandler` ist trotz seiner
STEP-1-6-Struktur überwiegend ein **Telegram-Frontcontroller**, kein Pipeline-Orchestrator.

---

## 7. Fachlich vs. technisch + Produktionslog-Abgleich

### Kategorisierung

| Kategorie | Beispiele in dieser Pipeline |
|---|---|
| **Application/Orchestration** | `enhanced_download_with_retry`, `_process_single/playlist_download`, `metadata_result_translator`, `EnhancedMetadataProcessor.process_single_track` (Ablaufsteuerung) |
| **Domain/Fachlogik** | `GenreProcessor.prioritize_genres`, `ChannelRouter` (P1–P5), `YearResolver`, `ArtistProcessor.determine_best_artist`, `TitleCleaner`, `DuplicateDetector`, `FilenameFixerTool` (Library-Regeln) |
| **Infrastructure** | `DownloadExecutor` (yt-dlp), `MusicBrainzClient`/`GeniusClient`/`LastFMClient`/`CoverProcessor`-Quellen, `AudioEnhancer` (FFmpeg), `TagWriter` (mutagen), `MetadataCache`/`DuplicateCache`/`LyricsCache` |
| **Presentation** | `DownloadHandler._update_status` (Telegram-Progress), `DownloadResultReporter` (Text-Vorbereitung, kein Versand), `EnhancedDuplicateHandler` (Menüs) |

### Konkrete Vermischung (einzige gefundene, siehe Abschnitt 14 für Priorität)

- **Datei:** `klassen/download_handler.py`
- **Klasse/Methode:** `handle_url()` / `handle_spotify_url()`
- **Abhängigkeit:** direkte Telegram-Objekte (`Update`, `ContextTypes`) **und** Ablaufsteuerung
  (Retry existiert hier nicht, aber die 6-Schritt-Statusmeldungen sind eng mit dem tatsächlichen,
  in `download_utils.py` liegenden Ablauf verwoben, ohne dass `DownloadHandler` diesen Ablauf
  selbst kontrolliert)
- **Problem:** Presentation-Layer (Telegram-Progress-UI) bildet einen Ablauf ab, den es selbst
  nicht steuert — funktioniert korrekt, ist aber für neue Entwickler ohne Codelesen irreführend.
- **Priorität:** P3 (kosmetisch/Dokumentation, siehe Abschnitt 14)

### Produktionslog-Frage explizit beantwortet

> "Existiert tatsächlich eine doppelte Metadata-Verarbeitung?"

**Nein — für YouTube nicht.** Es handelt sich um:
- **Übergabe eines bereits erzeugten Ergebnisses** (STEP 4 für YT ist reiner Pass-Through) — bestätigt durch den expliziten Code-Kommentar/Guard "Doppelverarbeitungs-Schutz" in `_process_single_download_result()`, Punkt B.
- **Für Spotify** ist STEP 4 hingegen die **einzige reale** Verarbeitung (kein Pass-Through, kein Duplikat).
- Es handelt sich **nicht** um historische Kompatibilität oder reines Reporting — der Code-Pfad ist aktiv und wird für Spotify durchlaufen.

Dies wurde **nicht aus der Logausgabe spekuliert**, sondern durch Lesen von
`_process_single_download_result()` (Punkt A–G, `klassen/download_handler.py:383-548`),
`download_utils.py::_process_single_download()` (Zeile 762 ff.) und
`services/downloader/spotify_downloader.py` (0 Treffer für `EnhancedMetadataProcessor`) verifiziert.

### CLAUDE.md-Divergenz (Auftrag §2)

CLAUDE.md §4 zeigt:
```
DownloadHandler
   ├── YouTube
   └── Spotify
           ↓
   Metadata Pipeline
```
Dies suggeriert: Metadata-Pipeline läuft *nach* und *getrennt von* der YouTube/Spotify-Beschaffung,
mit `DownloadHandler` als übergeordnetem Taktgeber. Tatsächlich läuft die Metadata-Pipeline für
YouTube **innerhalb** des YouTube-Beschaffungsschritts (in `download_utils.py`, ausgelöst *bevor*
`DownloadHandler` die Kontrolle zurückerhält), für Spotify hingegen tatsächlich danach (in
`DownloadHandler` selbst). Das vereinfachte CLAUDE.md-Diagramm ist als **grobe Flussrichtung**
weiterhin korrekt (Download vor Metadaten, chronologisch), aber die Zuordnung "wer orchestriert
die Metadata Pipeline" ist ungenau. Empfehlung: siehe Abschnitt 17/18.

---

## 8. Telegram-Kopplung

| Bereich | Status |
|---|---|
| `services/downloader/*` (gesamtes Paket, inkl. `download/` Unterpaket) | 🟢 **0 Telegram-Importe** (repo-weit per Grep verifiziert) |
| `services/metadata/*` | 🟢 0 Telegram-Importe (bereits in ARCH-017/018/019/020 bestätigt) |
| `services/duplicate/*` | 🟢 0 Telegram-Importe (ARCH-018 bestätigt) |
| `klassen/download_handler.py` | 🔴 **fachlich abhängig von Telegram** — importiert `Update`, `ContextTypes`, sendet Status-Nachrichten direkt. Dies ist jedoch die **bewusste, dokumentierte Rolle** dieser Schicht (`klassen/` ist die Telegram-Interaktionsschicht laut CLAUDE.md §4) — keine Fehlklassifizierung. |
| `YoutubeDownloader` | 🟡 **teilweise gekoppelt** — hält `self.update` (für `chat_id`/`update_id`), reicht diese aber nur als reine IDs an `download_utils.py` durch, keine Telegram-Objekte tiefer in der Pipeline. |

**Antwort auf die Auftragsfrage:** Der fachliche Download-Workflow (`download_utils.py` +
`EnhancedMetadataProcessor` + alle Sub-Komponenten) **kann bereits heute ohne Telegram ausgeführt
werden** — `enhanced_download_with_retry(url, chat_id, update_id, ...)` erwartet nur einfache
Skalare (`int`/`str`), keine Telegram-Objekte. Ein CLI- oder Test-Aufruf ohne Telegram-Kontext ist
strukturell möglich und wird bereits so getestet (`tests/test_download_utils_metadata_translation.py`
u. a. instanziieren die Pipeline ohne echten Telegram-`Update`).

---

## 9. External-System Boundaries

| System | Adapter | Beginn/Ende des Adapters | Fachlogik im Client? | Rohdaten oder verarbeitet? |
|---|---|---|---|---|
| yt-dlp | `DownloadExecutor` (`services/downloader/download/download_executor.py`) | beginnt bei `build_ydl_opts()`, endet bei `extract_info_async()`/`download_single_track()`-Rückgabe (rohes yt-dlp-`info`-Dict) | Nein — nur Options-Bau (inkl. `match_filter` für `MAX_DURATION`, s. Abschnitt 13) und Pfad-Extraktion | Rohdaten (yt-dlp-Dict) |
| MusicBrainz | `MusicBrainzClient` | vollständiger Adapter, liefert `tags`, IDs, Album-Rohdaten | Nein (ARCH-012/019 bestätigt) | Rohdaten + IDs |
| Last.fm | `LastFMClient` (Genre) + `CoverProcessor._fetch_lastfm()` (Cover, separat) | je eigener Adapter, unterschiedliche Endpunkte | Nein | Rohdaten (Tags bzw. Bild-Bytes) |
| Genius | `GeniusClient` | vollständiger Adapter | Nein (nur Lyrics-Text-Rückgabe) | Verarbeitet (bereinigter Lyrics-Text, keine Fachentscheidung) |
| Cover Art Archive / Fanart / Apple / Deezer | `CoverProcessor`-interne `_fetch_*`-Methoden | jeweils eigene REST-Calls innerhalb derselben Klasse | Nein (nur Scoring/Ranking, keine Genre-/Artist-Entscheidung) | Rohdaten (Bild-Bytes) + technisches Scoring |
| FFmpeg | `AudioEnhancer.normalize_loudness()` (Subprocess) | vollständig gekapselt | Nein | N/A (Audio-Transformation) |
| Filesystem | `FilenameFixerTool`, `DownloadExecutor`, diverse Caches | jeweils lokal gekapselt | Domain-Regeln (Zielpfad-Struktur) liegen bewusst in `FilenameFixerTool`, nicht in den Cache-Klassen | N/A |
| Navidrome | außerhalb dieser Pipeline (separater Scan-Trigger, `utils/navidrome_scan_trigger.py`) | nicht Teil des Download-Pfads | — | — |
| Telegram | `DownloadHandler` direkt | Adapter = die gesamte Klasse | Duplikat-Precheck-*Aufruf* ja, Duplikat-*Entscheidung* nein (liegt in `DuplicateDetector`) | N/A |

**Bewertung:** Alle externen Adapter sind bereits sauber gekapselt, liefern überwiegend Rohdaten,
keine Fachentscheidung im Client-Code. Keine künstliche Abstraktion nötig — die bestehenden
Adapter-Grenzen sind bereits austauschbar-tauglich (z. B. wurde `LastFMClient` in ARCH-012
bereits einmal strukturell verändert, ohne `GenreProcessor` anzufassen).

---

## 10. Daten-/Domain-Modelle

| Modell | Ort | Gekoppelt an |
|---|---|---|
| `DownloadResult` / `PlaylistResult` | `services/downloader/download/models.py` | Nichts Externes — reine Dataclasses. Docstring stellt explizit klar: `MetadataResult` wird hier **nicht** dupliziert. |
| `MetadataResult` | `services/metadata/models.py` | Nichts Externes |
| `DuplicateEntry` | `services/downloader/models.py` | Nichts Externes (ARCH-018 bestätigt) |
| Zwischen-Dicts (`track_metadata`, `result`) | ad hoc in `download_utils.py`/`download_handler.py` | **Ja** — Dictionaries werden über mehrere Schichten weitergereicht (yt-dlp-Rohdaten → `track_metadata`-Dict → `MetadataResult` → wieder Dict via `merge_metadata_result_into_dict`/`build_*_result`) |

**Werden Dictionaries unstrukturiert über viele Schichten weitergereicht?** Ja, teilweise — der
Übergang yt-dlp-Rohdaten → internes `track_metadata`-Dict → `MetadataResult`-Dataclass →
zurück-zu-Dict (für Telegram-Reporting) ist ein wiederkehrendes Muster. Dies ist **bereits
bewusst durch `metadata_result_translator.py` zentralisiert** (ARCH-004 P3) und durch
Regressionstests abgesichert (`tests/test_download_utils_metadata_translation.py`,
`tests/test_download_handler_process_single_download_result.py`) — kein unkontrolliertes
Ad-hoc-Wachstum, sondern eine dokumentierte, getestete Konvertierungsschicht.

**Sind Modelle an Telegram/yt-dlp/konkrete APIs gekoppelt?** Nein — `DownloadResult`,
`PlaylistResult`, `MetadataResult`, `DuplicateEntry` sind reine Dataclasses ohne externe Typen.

**Welche Modelle sind bereits stabil / sollten NICHT verändert werden?** `MetadataResult`
(zentrale Schnittstelle zwischen Metadaten-Pipeline und drei Aufrufstellen, durch
Feld-für-Feld-Characterization in ARCH-004 P3 abgesichert), `DuplicateEntry` (ARCH-018-Referenz),
`DownloadResult`/`PlaylistResult` (frisch aus ARCH-011 extrahiert, gut getestet).

---

## 11. Test Coverage / Characterization

| Bereich | vorhandene Tests | Testart | abgesichertes Verhalten | Refactoring-Risiko |
|---|---|---|---|---|
| `DownloadExecutor` | `test_download_executor.py` | Unit | yt-dlp-Options-Bau, `match_filter`, Async-Wrapping | niedrig |
| `ChannelRouter` | `test_channel_router.py` | Unit/Characterization | P1–P5-Entscheidungsbaum | niedrig |
| `CacheManager` | `test_cache_manager.py` | Unit | 2-Stufen-Lookup | niedrig |
| `YearResolver` | `test_year_resolver.py` | Unit | Quellen-Priorität | niedrig |
| `PlaylistProcessor` | `test_playlist_processor.py` | Unit | Playlist-Metadaten-Aufbereitung | niedrig |
| `SpotifyDownloader` | `test_spotify_downloader.py` | Unit | URL-Typ-Erkennung, Sanitizing | mittel (kein Metadaten-Integrationstest) |
| `ProgressTracker` | `test_progress_tracker.py` | Unit | Fortschritts-Text-Berechnung | niedrig |
| `DownloadResultReporter` | `test_download_result_reporter.py` | Unit | Text-Formatierung | niedrig |
| `metadata_result_translator.py` | `test_metadata_result_translator.py`, `test_download_utils_metadata_translation.py`, `test_download_handler_process_single_download_result.py` | Characterization (explizit Feld-für-Feld, ARCH-004 P3) | **genau der in Abschnitt 3/7 beschriebene Guard/Doppelrolle-Mechanismus** | **niedrig** — der zentrale Befund dieses Berichts ist bereits regressionsgesichert |
| Ressourcen-Limits | `test_playlist_max_items.py`, `test_download_concurrency_semaphore.py`, `test_download_url_validation.py` | Unit | `MAX_PLAYLIST_ITEMS`, `MAX_CONCURRENT_DOWNLOADS`, URL-Allowlist | niedrig |
| Duplicate-Kaskade | `tests/test_duplicate_handler.py` | Characterization | 4-Schichten-Kaskade (ARCH-018) | niedrig |
| Genre-Pipeline | `tests/test_genre_*characterization.py` (mehrere) | Characterization | Idempotenz, Spezifität, Alias | niedrig |
| Audio-Enhancer | (ARCH-017-Regressionstests) | Characterization | `normalize_loudness` byte-identisch | niedrig |
| `EnhancedMetadataProcessor.process_single_track()` End-to-End | `tests/test_metadata_processor_happy_path.py` | Integration/Characterization | Happy-Path aller 20 internen Schritte | niedrig |

**124 gezielt nachgewiesene Tests grün** (`test_download_url_validation`,
`test_download_concurrency_semaphore`, `test_playlist_max_items`, `test_download_executor`,
`test_channel_router`, `test_cache_manager`, `test_year_resolver`,
`test_metadata_result_translator`, `test_download_utils_metadata_translation`,
`test_download_handler_process_single_download_result`).

**Welche Bereiche dürfen relativ sicher migriert werden?** Keine Migration wird in diesem Bericht
empfohlen (siehe Abschnitt 17). Falls künftig doch: `DownloadHandler`s Label-Text/Kommentare
(Abschnitt 18) sind gefahrlos änderbar, da rein kosmetisch und nicht testrelevant.

**Welche Bereiche benötigen zuerst zusätzliche Tests?** Ein expliziter Integrationstest, der
`SpotifyDownloader` → `_process_single_download_result()` End-to-End nachweist (aktuell nur indirekt
über `test_download_handler_process_single_download_result.py` mit synthetischen Inputs
abgedeckt) — falls dieser Pfad künftig verändert werden soll.

---

## 12. Dependency Violations

AST-basierter Scan über `services/`, `handlers/`, `klassen/`, `utils/`, `helfer/`, `mapping/`:

```
klassen  → handlers : 0 Treffer   🟢
services → handlers : 0 Treffer   🟢
services → klassen  : 0 Treffer   🟢
handlers → klassen  : 1 Treffer   🟡 (rich_menu_handler.py → klassen.download_handler,
                                       bekannte, seit ARCH-006/007 akzeptierte Orchestrator-
                                       Sonderrolle von RichMenuHandler — unverändert, außerhalb
                                       des heutigen Scopes)
```

Keine Importzyklen gefunden. Keine neuen Grenzverletzungen speziell im Download-Pfad. Innerhalb
`services/downloader/` selbst: saubere unidirektionale Abhängigkeit
`download_utils.py → download/*.py → utils/*` (keine Rückimporte von `download/*.py` zu
`download_utils.py` gefunden).

---

## 13. Bereits korrekte Architektur (ausdrücklich, nicht nur Probleme)

Dies ist **nicht** vollständig — es hebt hervor, was **nicht** angefasst werden sollte:

- **`services/downloader/download/` (ARCH-011-Extraktion):** `cache_manager.py`, `channel_router.py`,
  `year_resolver.py`, `formatters.py` tragen alle explizite "Single Responsibility"-Docstrings
  mit "KEIN Download, KEIN Caching, KEINE …"-Abgrenzungen. Bereits vorbildlich entkoppelt.
- **`metadata_result_translator.py` (ARCH-004 P3):** verhindert aktiv erneute Duplikation der
  Dict↔MetadataResult-Übersetzung, die vorher an drei Stellen unabhängig gewachsen war.
- **`ProgressTracker`/`DownloadResultReporter` (ARCH-007):** bereits vollständig Telegram-frei,
  eigene Docstrings dokumentieren das explizit.
- **Ressourcen-Limits bereits implementiert und getestet:** `MAX_PLAYLIST_ITEMS`
  (`download_utils.py:420-430`, mit explizitem Code-Kommentar zur vorherigen Lücke),
  `MAX_DURATION` via echtem yt-dlp-`match_filter`
  (`download_executor.py:74-141`, ebenfalls mit Vorher/Nachher-Kommentar), `run_in_executor`
  für alle blockierenden yt-dlp-Aufrufe (`download_executor.py:169-248`, mit explizitem
  "blockiert sonst"-Kommentar) sowie `MAX_CONCURRENT_DOWNLOADS`
  (`test_download_concurrency_semaphore.py`) und eine URL-Domain-Allowlist
  (`_is_supported_download_url()`, `test_download_url_validation.py`). **Alle vier Punkte, die in
  einer früheren, nicht abgeschlossenen Planungsnotiz dieser Session als offene Risiken geführt
  wurden, sind im aktuellen Code bereits umgesetzt und getestet** — vermutlich durch Ihre eigenen,
  parallel zu dieser Session laufenden Änderungen. Diese Planungsnotiz ist damit hinfällig.
- **`AUTOLEARN-001`-Fix:** dokumentiertes Beispiel, dass eine echte Doppel-Verarbeitung in der
  Vergangenheit bereits einmal identifiziert und sauber behoben wurde — Beleg für funktionierende
  Wartungsdisziplin in genau diesem Pipeline-Bereich.
- **`services/duplicate/` (ARCH-018):** ausdrücklich als Referenzmuster zu behandeln, nicht
  zurückzubauen (Auftragsvorgabe).
- **Genre-Architektur (ARCH-012–016, ARCH-019):** `GenreProcessor` bleibt alleinige
  Entscheidungsinstanz, Clients liefern nur Rohdaten — unverändert korrekt.
- **`AudioEnhancer` (ARCH-017):** nur Loudness-Normalisierung aktiv, kein Netzwerk — unverändert
  korrekt, nicht erneut als Netzwerkmodul fehlklassifiziert.

---

## 14. Architekturprobleme (P0–P3)

| # | Befund | Datei/Stelle | Priorität | Begründung |
|---|---|---|---|---|
| 1 | STEP-4/6-Label ("Metadaten anreichern") beschreibt für YouTube keinen tatsächlichen Arbeitsschritt (No-Op-Pass-Through), für Spotify hingegen schon — asymmetrische Doppelrolle ohne Dokumentation im Code selbst | `klassen/download_handler.py:716-718`, `_process_single_download_result()` Punkt B | **P3** (kosmetisch/Dokumentation — funktioniert korrekt, ist aber ohne Codelesen irreführend) | Kein Verhaltensfehler, keine Testlücke — reine Verständlichkeit |
| 2 | CLAUDE.md §4 stellt "Metadata Pipeline" als eigenen, von `DownloadHandler` orchestrierten Schritt *nach* YouTube/Spotify dar; tatsächlich läuft sie für YouTube *innerhalb* der YouTube-Beschaffung (`download_utils.py`) | `CLAUDE.md` §4 vs. `services/downloader/download_utils.py` | **P3** (Dokumentationsdivergenz, keine Architekturverletzung) | Betrifft nur die vereinfachte Übersichtsgrafik, nicht die detaillierten Abschnitte 5/16/17 von CLAUDE.md |
| 3 | `SpotifyDownloader` und die YouTube-Pipeline sind strukturell asymmetrisch (wer ruft `EnhancedMetadataProcessor` auf) ohne begleitenden Architektur-Kommentar, der diese bewusste Asymmetrie erklärt | `services/downloader/spotify_downloader.py`, `klassen/download_handler.py` | **P3** | Funktioniert korrekt (durch Tests abgesichert), aber ein künftiger Bearbeiter könnte versucht sein, "Konsistenz" herzustellen und dabei den funktionierenden Spotify-Pfad zu brechen |

**Keine P0/P1/P2-Befunde identifiziert.** Kein Befund blockiert die Zielarchitektur oder stellt
eine wichtige Architekturverletzung dar.

---

## 15. Zielarchitektur (Hypothese, nicht umgesetzt)

Die bestehende Struktur legt bereits folgende Schichtung nahe — sie muss **nicht neu geschaffen**
werden, sondern ist bereits weitgehend vorhanden:

```
Presentation
  DownloadHandler (Telegram-Dispatch, Progress-UI, Duplikat-Precheck, Post-hoc-Reporting)
        ↓
Application / Workflow
  download_utils.py (Retry, Playlist/Single-Verzweigung, Cache-Entscheidung)
  metadata_result_translator.py (Format-Übersetzung)
        ↓
Domain Services
  DuplicateDetector · GenreProcessor · ChannelRouter · YearResolver ·
  ArtistProcessor · TitleCleaner · FilenameFixerTool (Library-Regeln)
        ↓
Infrastructure
  DownloadExecutor (yt-dlp) · MusicBrainzClient · LastFMClient · GeniusClient ·
  CoverProcessor-Quellen · AudioEnhancer (FFmpeg) · TagWriter (mutagen) · Caches
```

Dies ist **keine generische Clean-Architecture-Schablone**, sondern beschreibt exakt die bereits
bestehende Verteilung — der einzige "Abweichungs"-Punkt ist, dass `EnhancedMetadataProcessor`
als Domain-Orchestrator eine eigene Zwischenebene zwischen Application und Domain Services bildet
(20 interne Schritte), was durch seine Größe gerechtfertigt ist und laut CLAUDE.md §19 ("Große
Klassen") nicht automatisch zerlegt werden soll.

---

## 16. Zielrollen der bestehenden Komponenten

| Komponente | Zielrolle |
|---|---|
| `DownloadHandler` | Telegram-Adapter / Presentation-Orchestrator (bereits korrekt, nur Label-Klarheit fehlt) |
| `YoutubeDownloader` | Acquisition-Adapter (dünn, bereits korrekt) |
| `download_utils.py` | Application/Workflow-Orchestrator (bereits korrekt positioniert) |
| `EnhancedMetadataProcessor` | Domain-Metadaten-Orchestrator (bereits korrekt, Größe durch CLAUDE.md §19 gedeckt) |
| `services/downloader/download/*` | Domain-/Infrastructure-Services (bereits korrekt extrahiert) |
| `services/clients/*` | Infrastructure-Adapter (bereits korrekt, ARCH-019 bestätigt) |
| `services/duplicate/*` | Domain Service (ARCH-018-Referenz) |

Nur bestätigt, keine neue Struktur vorgeschlagen.

---

## 17. Empfohlene Migration

### WICHTIGSTE ENTSCHEIDUNG

> **MUSS DIE DOWNLOAD-PIPELINE JETZT REFAKTORIERT WERDEN?**

**Antwort: C) Nein — aktuelle Struktur ist ausreichend.**

Begründung anhand konkreter Codebefunde:
- Alle in Abschnitt 5 gelisteten Komponenten sind bereits Single-Responsibility, DI-basiert,
  Telegram-frei (wo fachlich relevant) und durch 124+ gezielt verifizierte Tests abgesichert.
- Die einzige "doppelte Verarbeitung", die der Auftrag explizit zu prüfen bat, existiert **nicht**
  als Bug — sie ist ein bewusster, getesteter Guard-Mechanismus.
- Alle drei Ressourcen-/Sicherheitsrisiken, die eine frühere Planungsnotiz dieser Session als offen
  einstufte (Event-Loop-Blockierung, fehlende URL-Allowlist, fehlende Playlist-/Concurrency-Limits),
  sind bereits behoben und getestet.
- Die einzigen Befunde sind P3 (Label-/Dokumentations-Klarheit), keine P0/P1/P2.

**Ein kleiner notwendiger Dokumentations-/Kommentarfix ist hier tatsächlich besser als jeder
Code-Refactor.**

### Vorgeschlagener kleinster nächster Schritt (nur falls gewünscht, keine automatische Folgephase)

**ARCH-021 — Download-Pipeline-Label-Klarheit (rein dokumentarisch)**

- **Problem:** STEP-4/6-Telegram-Label und CLAUDE.md §4-Diagramm suggerieren einen anderen
  Ablauf als den tatsächlichen (Abschnitt 7/14).
- **Betroffene Dateien:** `klassen/download_handler.py` (Kommentare/Docstring an
  `_process_single_download_result()`, ggf. STEP-4-Label-Text), `CLAUDE.md` §4 (Diagramm-Fußnote).
- **Ziel:** Code-Kommentar und Nutzer-Dokumentation spiegeln den tatsächlichen Ablauf wider —
  keine Verhaltensänderung.
- **Risiko:** minimal (reine Text-/Kommentaränderung, keine Logik betroffen).
- **Benötigte Tests:** keine neuen — bestehende Tests bleiben unverändert grün.
- **Abhängigkeiten:** keine.
- **Erwartetes Ergebnis:** ein neuer Entwickler versteht beim Lesen von STEP 4 sofort, dass dies
  für YouTube ein Guard und für Spotify die reale Verarbeitung ist.

Kein ARCH-022/023 wird vorgeschlagen — die Analyse rechtfertigt keine weiteren Schritte.

---

## 18. Was NICHT migriert werden sollte

- **`services/downloader/download/*`-Modulzuschnitt** (Cache/Channel/Year/Executor/Formatter) —
  bereits optimal nach Single Responsibility getrennt (ARCH-011).
- **`metadata_result_translator.py`-Konvergenzpunkt** — verhindert aktiv erneute Duplikation,
  nicht auflösen.
- **`_process_single_download_result()`s Doppelrolle (Guard für YT / echte Arbeit für Spotify)**
  — NICHT durch zwei separate Methoden ersetzen, ohne vorherige explizite Entscheidung; die
  aktuelle Lösung ist minimal und funktioniert nachweislich korrekt für beide Herkunftspfade.
- **`services/duplicate/`** — ARCH-018-Referenzarchitektur, Auftragsvorgabe.
- **`GenreProcessor`/`GenreMapper`** — ARCH-012–016/019 abgeschlossen, keine erneute Umstrukturierung.
- **`AudioEnhancer`** — ARCH-017 abgeschlossen, keine erneute Netzwerk-Fehlklassifizierung.
- **Die bereits implementierten Ressourcen-Limits** (`MAX_PLAYLIST_ITEMS`, `MAX_DURATION`,
  `MAX_CONCURRENT_DOWNLOADS`, URL-Allowlist, `run_in_executor`) — nicht "verbessern", sie sind
  bereits vollständig und getestet.

---

## 19. Risiken

- **Risiko einer Fehlinterpretation ohne diese Dokumentation:** ein künftiger Bearbeiter könnte
  STEP 4 als "toten Code" missverstehen und versuchen, ihn zu entfernen — das würde den
  Spotify-Pfad brechen (keine Metadaten-Verarbeitung mehr). **Mitigation:** Abschnitt 17
  (Label-Klarheit) explizit als Empfehlung festgehalten.
- **Risiko bei künftiger "Konsistenz-Herstellung" zwischen YT- und Spotify-Pfad:** falls jemand
  `SpotifyDownloader` dazu bringt, ebenfalls selbst `EnhancedMetadataProcessor` aufzurufen, ohne
  den Guard in `_process_single_download_result()` entsprechend anzupassen, entstünde erstmals
  eine **echte** doppelte Verarbeitung für Spotify. Aktuell nicht der Fall — reines Zukunftsrisiko.
  **Mitigation:** in Abschnitt 18 explizit als "nicht migrieren ohne Entscheidung" vermerkt.
- **Kein Risiko durch diesen Bericht selbst** — keine Code-/Test-/Mapping-Änderung vorgenommen,
  Git-Working-Tree unverändert (siehe Abschnitt 20/Diff-Audit).

---

## 20. Final Decision

1. **Wer soll künftig orchestrieren?** Unverändert `download_utils.py` (Application/Workflow) und
   `EnhancedMetadataProcessor` (Domain-Metadaten) — keine Änderung nötig, diese Rollen sind bereits
   korrekt besetzt.
2. **Welche Komponenten gehören in Application?** `download_utils.py`, `metadata_result_translator.py`,
   `YoutubeDownloader` (dünn) — bereits so positioniert.
3. **Welche gehören in Domain?** `GenreProcessor`, `DuplicateDetector`, `ChannelRouter`,
   `YearResolver`, `ArtistProcessor`, `TitleCleaner`, `FilenameFixerTool` — bereits so positioniert.
4. **Welche gehören in Infrastructure?** `DownloadExecutor`, `MusicBrainzClient`, `LastFMClient`,
   `GeniusClient`, `CoverProcessor`-Quellen, `AudioEnhancer`, `TagWriter`, Caches — bereits so
   positioniert.
5. **Welche bleiben im Handler?** Telegram-Dispatch, Progress-Labels, Duplikat-Precheck,
   Post-hoc-Registrierung/Reporting — bereits so positioniert.
6. **Welche bestehenden Komponenten sind bereits korrekt?** Praktisch die gesamte Pipeline
   (Abschnitt 13) — mit Ausnahme der P3-Label-Klarheit.
7. **Muss die Download-Pipeline refaktoriert werden?** **Nein** (Ergebnis C, Abschnitt 17).
8. **Wenn ja: welcher kleinste sinnvolle nächste Schritt?** Nicht zutreffend — falls gewünscht,
   ausschließlich die in Abschnitt 17 skizzierte, rein dokumentarische ARCH-021.
9. **Welche Tests müssen vor diesem Schritt existieren?** Keine neuen — bestehende
   Characterization-Tests (Abschnitt 11) decken den beschriebenen Guard-Mechanismus bereits ab.
10. **Welche Teile dürfen ausdrücklich NICHT gleichzeitig angefasst werden?** Alle in Abschnitt 18
    gelisteten Punkte — insbesondere die Guard-Logik in `_process_single_download_result()` und
    die bereits implementierten Ressourcen-Limits.

---

## Diff-/Scope-Audit

```
git status --short  →  keine durch diesen Bericht verursachten Änderungen
```

- Produktionsänderungen: **0**
- Teständerungen: **0**
- Mapping-/YAML-Änderungen: **0**
- Commit: **keiner**
- Push: **keiner**
- Neue Dependency-Edges: **0** (AST-Scan identisch zum Vor-Zustand)

---

## Abschlussnotiz zur Nummerierungs-Kollision

Erledigt: `docs/MusicBot_ARCH-020_Genre_Client_Duplication_Characterization.md` (aus dieser
Session, vor Kenntnis der bereits reservierten ARCH-020) wurde auf ausdrücklichen Nutzerwunsch
zu `docs/archive/arch/MusicBot_ARCH-021_Genre_Client_Duplication_Characterization.md` umbenannt, inklusive
Anpassung der internen Selbstverweise ("ARCH-020 Phase 1" → "ARCH-021 Phase 1").

---

## Spotify-Entfernung (2026-08-25, Folgeauftrag)

**Spotify support was intentionally removed.**

Spotify wurde im produktiven Betrieb nicht genutzt und sollte laut ausdrücklichem
Nutzerauftrag bewusst nicht weiterentwickelt, getestet oder abgesichert werden. Diese
Charakterisierung (insbesondere Abschnitt 3 "Aktuelle Download-Pipeline" und Abschnitt 5
"Komponentenmatrix") beschrieb den damaligen Ist-Zustand **inklusive** des Spotify-Pfads —
dieser historische Befund bleibt oben unverändert stehen, da er den damals tatsächlichen
Code korrekt wiedergibt.

**Warum entfernt:** Spotify lief ausschließlich über eine inoffizielle Embed-API (kein
offizieller API-Zugang, keine Premium-Unterstützung) und wurde im laufenden Betrieb nicht
verwendet. Die Aufrechterhaltung eines ungenutzten, nicht offiziell unterstützten
Integrationspfads widersprach dem Ziel kontrollierter, sicherer Weiterentwicklung
(CLAUDE.md §3).

**Was entfernt wurde:**
- `services/downloader/spotify_downloader.py` (vollständig, inkl. `SpotifyDownloader`,
  URL-Erkennung/-Parsing)
- `utils/podcast_rss_manager.py`, `mapping/podcast_rss_feeds.yaml` — die Podcast-RSS-
  Download-Funktion war ausschließlich über Spotify-Podcast-URLs erreichbar (0 andere
  Aufrufer, siehe Removal Impact Report), damit entfiel mit Spotify auch diese Funktion
- `klassen/download_handler.py::handle_spotify_url()` sowie die Punkte D (Podcast-
  Episodennummer-Korrektur), E (playlist_metadata für Podcasts) und G
  (`EnhancedMetadataProcessor`-Aufruf) in `_process_single_download_result()` — Punkt G
  war nachweislich nur für Spotify real erreichbar (siehe Abschnitt 3 oben:
  "Für Spotify … ist STEP 4 hingegen die einzige reale Verarbeitung"); ohne Spotify
  existiert kein Aufrufer mehr, der diesen Codepfad mit `filepath` ohne `library_path`
  erreicht
- `services/downloader/metadata_result_translator.py::merge_metadata_result_into_dict()`
  (verlor mit Punkt G ihren einzigen Aufrufer)
- Spotify-Branches in `services/downloader/download_result_reporter.py`
  (Quelle-Label, Genre-Filterung für Spotify-Podcasts)
- `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`/`SPOTIFY_DOWNLOAD_DIR`/`SPOTIFY_ENABLED`
  in `config.py` — alle vier waren bereits vor der Entfernung funktionslos
  (`SpotifyDownloader` nutzte nie Credentials, `SPOTIFY_ENABLED` wurde nirgends
  gelesen, `SPOTIFY_DOWNLOAD_DIR` war laut eigenem Code-Kommentar "nie angebunden")
- Zugehörige Tests: `tests/test_spotify_downloader.py`,
  `tests/test_podcast_rss_manager.py` (vollständig); Spotify-/Podcast-spezifische
  Einzeltests in `tests/test_download_handler_process_single_download_result.py`,
  `tests/test_download_result_reporter.py`, `tests/test_metadata_result_translator.py`,
  `tests/test_rich_menu_handler.py`

**Welche Download-Pipeline übrig bleibt:** Exakt die in Abschnitt 3/4/16 oben
beschriebene YouTube-Pipeline, unverändert in ihrer internen Struktur
(`download_utils.py` bleibt der reale Orchestrator, `EnhancedMetadataProcessor` bleibt
der Metadaten-Orchestrator). `DownloadHandler` verliert die `handle_url()`-Verzweigung
und wird zu einem reinen YouTube-Dispatcher. `_process_single_download_result()`
bleibt als Guard/Pass-Through (Punkte A, B, C, F) bestehen, ruft aber `process_single_track()`
nicht mehr auf.

**Geprüfte Regression:** siehe Abschlussbericht der Spotify-Entfernung (separates Dokument
bzw. Chat-Zusammenfassung) — vollständige Testsuite vor/nach Entfernung verglichen, YouTube-
Downloadpfad (Single, Cache, Metadata, Duplicate, Library) funktional bestätigt.

---

## STOPP

Analyse abgeschlossen. Keine Codeänderungen, kein Commit, kein Push, keine sonstigen
Dateiänderungen. Wartet auf Ihre Entscheidung bezüglich Abschnitt 17 (ARCH-021-Empfehlung) und
der Nummerierungs-Kollision.
