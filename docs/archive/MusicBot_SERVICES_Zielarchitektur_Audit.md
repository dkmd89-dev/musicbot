# MusicBot — Services-Zielarchitektur Audit

**Stand:** 2026-08-24
**Status:** Analyse abgeschlossen, keine Umsetzung
**Methode:** Direkte Repository-Inspektion (Datei-für-Datei-Klassifikation,
repo-weite Greps, gezielte Code-Lektüre). Kein Rückgriff auf bestehende
Dokumentation als primäre Quelle für den Ist-Zustand.

---

## 1. Ausgangslage

ARCH-009 und P-1 sind abgeschlossen und gemergt (`81df5be`). Die Navidrome-
Struktur ist bereinigt (`services/clients/navidrome_api.py`,
`utils/navidrome_scan_trigger.py`, `utils/bot_restart_trigger.py`, `api/`
entfernt). Der vorherige Post-ARCH-009-Audit (`docs/archive/post-arch/MusicBot_POST-ARCH-009_Audit.md`)
hatte `services/downloader/spotify_downloader.py` als möglichen Kandidaten
für externe Kommunikation außerhalb `services/clients/` benannt, aber noch
nicht vertieft geprüft. Dieser Audit erweitert die Prüfung auf die gesamte
`services/`-Struktur (42 Python-Dateien, ~11.940 Zeilen) und vergleicht sie
mit `utils/` (16 Dateien, ~5.667 Zeilen).

---

## 2. Aktueller `services/`-Bestand — vollständige Klassifikation

| Modul | Aktuelle Aufgabe | Consumer | Telegram | HTTP/API | Subprocess | DI | Kategorie |
|---|---|---|---|---|---|---|---|
| `services/clients/genius_client.py` | Lyrics-Abruf (Genius, mehrstufiger Fallback) | `enhanced_metadata_processor.py` | nein | ja (`aiohttp`, `lyricsgenius`) | nein | teilweise (Logger injizierbar, Config global via `get_config()`) | **B** |
| `services/clients/lastfm_client.py` | Last.fm-Metadaten (Tags/Ähnliche Künstler) | `enhanced_metadata_processor.py` (indirekt) | nein | ja (`pylast`-SDK) | nein | nein (`Config()` fest im `__init__`) | **B** |
| `services/clients/musicbrainz_client.py` | MusicBrainz-Recording-/Release-Auflösung | `enhanced_metadata_processor.py`, `album_processor.py` | nein | ja (`musicbrainzngs`-SDK) | nein | nein (`Config` global, Singleton-Referenzen für `GenreMapper`/`ArtistNormalizer`) | **B** |
| `services/clients/navidrome_api.py` | Subsonic-API-Adapter | `handlers/navidrome_menu_handler.py`, `services/statistik_service.py` | nein (1 Falsch-Positiv: String `"c":"telegram-bot"`) | ja (`requests`) | **totes `import subprocess`** (Zeile 8, nirgends verwendet) | ja (`__init__(config=None)`, seit Phase 7) | **B**, 1 Fund |
| `services/downloader/downloader.py` | `YoutubeDownloader`-Orchestrator | `bot.py`, Tests | nein | nein (delegiert an `download_executor.py`) | nein | ja | **A** |
| `services/downloader/spotify_downloader.py` | Spotify→YouTube-Download + RSS-Podcasts | `klassen/download_handler.py` | nein | **ja, 6 direkte `urlopen`/`urlretrieve`-Aufrufe** (Spotify-oEmbed/Embed-Scraping, Cover, RSS, Redirect) | nein | ja (`config` injiziert) | **E** (A+B gemischt) |
| `services/downloader/playlist_processor.py` | Playlist-Verarbeitung/Trunkierung | `download_utils.py`, Tests | nein | nein | nein | ja | **A** |
| `services/downloader/download/download_executor.py` | yt-dlp-Ausführung, `run_in_executor`-Wrapping | `download_utils.py`, `klassen/download_handler.py` | nein | nein (yt-dlp intern) | nein | ja | **A** |
| `services/downloader/download/channel_router.py` | Kanal-/Sonderkanal-Routing | Download-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/download/cache_manager.py` | Metadata-Cache-Zugriff (Stufe 1/2) | Download-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/download/year_resolver.py` | Jahres-Auflösung (Playlist/Upload-Date) | Download-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/download/formatters.py` | Ergebnis-Formatierung (Text, kein Telegram) | Download-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/download/interfaces.py` | `Protocol`-Ports (`DownloadCoordinator`, `CacheProvider`, `MetadataEnricher`, `TrackResultCollector`) | strukturelle Referenz | nein | nein | nein | — (reine Schnittstellen) | **A** (Referenz-Präzedenzfall) |
| `services/downloader/download/models.py` | Datenmodelle | Download-Pipeline | nein | nein | nein | — | **A** |
| `services/downloader/utils/enhanced_metadata_processor.py` | Metadata-Pipeline-Orchestrator (1203 Zeilen) | `klassen/download_handler.py`, `download_utils.py` | nein | **totes `import requests`** (Zeile 6, nirgends verwendet) | nein | ja | **A**, 1 Fund |
| `services/downloader/utils/download_utils.py` | YouTube-Download-Orchestrierung | `klassen/download_handler.py`, `bot.py` | nein | nein | nein | ja | **A** |
| `services/downloader/utils/download_result_reporter.py` | Baut Telegram-Ergebnistexte (String, kein Versand) | `klassen/download_handler.py`, `download_utils.py` | nein (kein `telegram`-Import, nur Text-Erzeugung) | nein | nein | ja | **A**, aber **`from handlers.duplicate_handler import DuplicateEntry`** (Service→Handler-Import, bereits als offener DEFER-Punkt in `docs/archive/MusicBot_ENGINEERING_BASELINE.md` dokumentiert) |
| `services/downloader/utils/download_artifact_cleanup.py` | Aufräumen verwaister Download-Artefakte | `enhanced_metadata_processor.py`, `bot.py` | nein | nein | nein | ja | **A** |
| `services/downloader/utils/progress_tracker.py` | Fortschritts-Text-Berechnung (kein Versand) | Download-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata_result_translator.py` | Integrationsschicht Metadata↔Pipeline-Ergebnis | `download_utils.py`, `klassen/download_handler.py` | nein | nein | nein | ja | **A** |
| `services/downloader/utils/errors.py` | Exception-Hierarchie | Download-Pipeline | nein | nein | nein | — | **A** |
| `services/downloader/utils/metadata/album_processor.py` | Album-/Jahr-Auflösung | Metadata-Pipeline | nein | nein (nutzt `MusicBrainzClient`) | nein | ja | **A** |
| `services/downloader/utils/metadata/artist_processor.py` | Artist-Bestimmung (Haupt/Feature) | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata/auto_learn.py` | Auto-Learning für Artist/Genre | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata/cache.py` | Metadata-Cache-Handling | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata/cover_processor.py` | Cover-Art-Fallback-Kette mit Scoring (955 Zeilen) | `enhanced_metadata_processor.py` | nein | **ja, 5 externe Quellen direkt** (Cover Art Archive, Fanart.tv Album/Artist, Apple Music, Deezer, Last.fm — eigene `requests.Session`) | nein | ja (`fanart_api_key`/`lastfm_api_key` injiziert) | **E** (A+B gemischt), **doppelte Last.fm-Logik** ggü. `services/clients/lastfm_client.py` (dort `pylast`-SDK, hier rohe REST-Calls) |
| `services/downloader/utils/metadata/genre_processor.py` | Genre-Bestimmung (Fuzzy/Hierarchie/Fallback) | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata/lyrics_processor.py` | Lyrics-Orchestrierung | Metadata-Pipeline | nein | nein (nutzt `GeniusClient`) | nein | ja | **A** |
| `services/downloader/utils/metadata/models.py` | Datenmodelle (`MetadataResult` etc.) | Metadata-Pipeline | nein | nein | nein | — | **A** |
| `services/downloader/utils/metadata/tag_writer.py` | ID3/MP4-Tag-Schreiben | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/downloader/utils/metadata/title_cleaner.py` | Titel-Normalisierung | Metadata-Pipeline | nein | nein | nein | ja | **A** |
| `services/statistik_service.py` | Dünne Fassade (seit ARCH-003 P-6) | `bot.py`, `handlers/mugge_statistik_handler.py`, `handlers/navidrome_menu_handler.py` | nein | nein (delegiert an `NavidromeAPI`) | nein | ja (`navidrome_api=None`) | **A** |
| `services/statistik/play_history_repository.py` | Datei-Persistenz (JSON) | `statistik_service.py`, `play_history_poller.py` | nein | nein | nein | ja | **A** |
| `services/statistik/play_history_poller.py` | Navidrome-Hintergrund-Polling | `statistik_service.py` | nein | nein (nutzt injizierte `NavidromeAPI`) | nein | ja (`navidrome_api`, `repository` injiziert) | **A** |
| `services/statistik/statistics_calculator.py` | Statistik-Berechnung (reine Business-Logik) | `statistik_service.py` | nein | nein | nein | ja | **A** |
| `services/statistik/chart_renderer.py` | matplotlib-Chart-Erzeugung | `statistik_service.py` | nein | nein | nein | ja | **A/C-Grenzfall** (technische Rendering-Aufgabe, aber fachlich an Statistik gebunden — kein eigenständiger Kandidat) |

**Kategorien-Legende:** A = Fachlicher Service, B = Externer Integrationsadapter, C = Technischer Runner, D = Präsentationslogik, E = Mischverantwortlichkeit.

**Ergebnis:** Kein Modul in `services/` fällt in Kategorie D (Präsentationslogik) oder enthält echten Subprocess-Code. Zwei Module fallen in Kategorie E (`spotify_downloader.py`, `cover_processor.py`) — beide durch echte externe HTTP-Kommunikation, die mit fachlicher Orchestrierung verwoben ist.

---

## 3. `services/clients/` Audit

| Client | Externe Schnittstelle | Reiner Adapter? | Fachliche Orchestrierung? | Telegram/UI? | Import-Seiteneffekt | DI | Modul-Config | Doppelte Logik? |
|---|---|---|---|---|---|---|---|---|
| `GeniusClient` | Genius (Lyrics), `lyricsgenius`+`aiohttp` | ja (funktional) | nein | nein | nein | Logger injizierbar, Config via `get_config()` im `__init__` (nicht injizierbar) | keine | nein |
| `LastFMClient` | Last.fm (`pylast`-SDK) | ja (funktional) | nein | nein | nein | nein (`Config()` fest konstruiert) | keine | **ja** — `cover_processor.py::_fetch_lastfm()` dupliziert Last.fm-Zugriff über rohe REST-Calls statt über diesen Client |
| `MusicBrainzClient` | MusicBrainz (`musicbrainzngs`-SDK) | ja (funktional) | nein | nein | nein (aber `musicbrainzngs.set_useragent()` bei jeder Instanziierung — globaler SDK-Seiteneffekt der Drittbibliothek) | nein (`Config` global, `GenreMapper`/`ArtistNormalizer` als Singleton referenziert) | keine | nein |
| `NavidromeAPI` | Navidrome/Subsonic (`requests`) | ja (funktional), aber **totes `import subprocess`** (Zeile 8) — Überbleibsel aus der Zeit vor ARCH-009 Phase 8/9, nirgends mehr verwendet | nein | nein (Falsch-Positiv-String) | nein | ja (`config=None`, Phase 7) | `_get_navidrome_config()` (`@lru_cache`, bereits in Phase 7 bewusst entschieden) | nein |

**Antwort auf die Kernfrage aus dem Auftrag:** Die Regel „`services/clients/` =
externe Integrationsadapter" **hält funktional** — alle vier Module
kommunizieren tatsächlich nur mit dem jeweiligen externen System, keines
enthält Telegram-Logik oder echte Subprocess-Steuerung. **Aber:** die Regel
ist bei DI/Konfiguration **nicht einheitlich umgesetzt** — nur `NavidromeAPI`
akzeptiert eine injizierbare Config (aus Phase 7), die anderen drei
konstruieren `Config`/`get_config()` fest im `__init__`. Das ist kein neuer
Bruch (war schon vor ARCH-009 so), aber eine Inkonsistenz innerhalb der
eigenen Konvention.

---

## 4. Direkte externe Kommunikation außerhalb `services/clients/`

| Datei | Externe Kommunikation | Zielsystem | Aktuelle Schicht | Architektonisch auffällig? | Kandidat |
|---|---|---|---|---|---|
| `services/downloader/spotify_downloader.py` | `urlopen`/`urlretrieve` (6 Stellen) | Spotify-oEmbed, Spotify-Embed-HTML (Scraping), Cover-Art, RSS-Episode-Download, URL-Redirect-Resolution | `services/downloader/` (Fachlicher Service) | ja, aber differenziert (siehe unten) | ja (P-2, bereits bekannt) |
| `services/downloader/utils/metadata/cover_processor.py` | `requests.Session` + eigener `_get()`-Wrapper (5 Quellen) | Cover Art Archive, Fanart.tv (Album+Artist), Apple Music, Deezer, Last.fm | `services/downloader/utils/metadata/` (Fachlicher Service) | **ja, stärker als spotify_downloader** — inkl. duplizierter Last.fm-Zugriffslogik ggü. `services/clients/lastfm_client.py` | ja (P-2) |
| `services/downloader/utils/enhanced_metadata_processor.py` | `import requests` (Zeile 6) | — | `services/downloader/utils/` | **totes Import**, keine tatsächliche Kommunikation | trivial, kein Architektur-Kandidat |
| `services/clients/navidrome_api.py` | `import subprocess` (Zeile 8) | — | `services/clients/` | **totes Import**, keine tatsächliche Ausführung | trivial, kein Architektur-Kandidat |
| `utils/audio_enhancer.py` | `requests.Session` | Last.fm, MusicBrainz, Cover Art Archive (Künstlerbilder) | `utils/` | ja — widerspricht der in `CLAUDE.md` (Abschnitt 4, „Schichtgrenzen") definierten `utils/`-Regel „ohne externe Netzwerkkommunikation" | siehe Abschnitt 9 |

**Bewertung `spotify_downloader.py` (wie im Auftrag gefordert, nicht automatisch als Verstoß):**
Die HTTP-Aufrufe dort sind **fachlich eng an den Spotify-No-API-Download-Weg
gebunden** (oEmbed/Embed-Scraping liefert die Metadaten, die den No-API-
Ansatz überhaupt erst ermöglichen; RSS-Download ist ein alternativer,
fachlich zusammengehöriger Pfad für Podcasts). Es handelt sich nicht um
einen austauschbaren externen Adapter wie Genius/Last.fm/MusicBrainz,
sondern um Kernlogik des Spotify-Downloaders selbst. Eine Extraktion nach
`services/clients/` wäre möglich, aber kein einfacher „Verschieben"-Schritt
— eher eine Frage, ob ein neuer `SpotifyMetadataClient` sinnvoll wäre.

**Bewertung `cover_processor.py` (neu, nicht im vorherigen Audit geprüft):**
Anders als bei `spotify_downloader.py` gibt es hier einen **konkreten,
objektiven Doppel-Fund**: Last.fm wird bereits über `services/clients/lastfm_client.py`
(`pylast`-SDK) abstrahiert, aber `cover_processor.py::_fetch_lastfm()` greift
unabhängig davon mit rohen REST-Calls erneut auf Last.fm zu. Das ist kein
reiner Verschiebe-Kandidat, sondern ein Konsolidierungs-Kandidat.

---

## 5. Telegram-Kopplung innerhalb von `services/`

| Datei | Telegram-Nutzung | Warum? | Schichtverletzung? | Empfehlung |
|---|---|---|---|---|
| `services/clients/navidrome_api.py` | String-Literal `"c": "telegram-bot"` (Subsonic-Client-Kennung) | Subsonic-API verlangt einen Client-Identifier-String, kein Telegram-Framework-Bezug | nein (Falsch-Positiv) | keine |

Kein weiteres Modul unter `services/**/*.py` enthält `telegram`, `ParseMode`,
`CallbackQuery`, `ContextTypes`, `InlineKeyboard` o. ä. `klassen/download_handler.py`
liegt außerhalb von `services/` und ist gemäß `CLAUDE.md` Abschnitt 4 als
Orchestrator explizit mit Telegram gekoppelt — nicht erneut geprüft, wie im
Auftrag vorgegeben.

**Ergebnis: `services/` ist vollständig frei von Telegram-Kopplung.**

---

## 6. Subprocess-/System-Aufrufe in `services/`

Repo-weiter Grep auf `subprocess`, `create_subprocess`, `Popen`, `systemctl`
in `services/**/*.py`: **0 Treffer mit tatsächlicher Ausführung.**

Die einzigen zwei Fundstellen sind tote Imports (siehe Abschnitt 4):
`services/clients/navidrome_api.py:8` und indirekt keine weiteren. Es gibt
in `services/` keinen Fall, der strukturell `utils/navidrome_scan_trigger.py`
oder `utils/bot_restart_trigger.py` ähnelt — beide Runner liegen bereits
korrekt in `utils/`, und kein weiterer Kandidat wurde in `services/`
gefunden.

---

## 7. DI-/Global-State-Audit innerhalb von `services/`

| Muster | Fundstellen | Einordnung |
|---|---|---|
| `Config`/`get_config()` fest im `__init__` (nicht injizierbar) | `GeniusClient`, `LastFMClient`, `MusicBrainzClient` | **Problematisch (leicht)** — konsistent mit dem Vor-Phase-7-Zustand von `NavidromeAPI`, aber seither nicht nachgezogen. Kein akutes Problem (funktioniert, ist aber schwerer isoliert zu testen als `NavidromeAPI` seit Phase 7). |
| `@lru_cache` auf `_get_navidrome_config()` | `services/clients/navidrome_api.py` | **Bewusstes Caching** — bereits in Phase 7 entschieden, kein neuer Fund. |
| Singleton-Referenzen (`get_genre_mapper()`, `_get_artist_normalizer()`) | `MusicBrainzClient.__init__` | **Bewusstes Caching/Singleton** — dokumentierter Kommentar im Code („Singleton-Referenzen statt eigener Instanzen"), keine versteckte Kopplung. |
| `musicbrainzngs.set_useragent(...)` bei jeder Instanziierung | `MusicBrainzClient.__init__` | **Geringfügig** — globaler Seiteneffekt einer Drittbibliothek, wird bei jeder neuen Instanz wiederholt (keine Fehlerquelle, da idempotent), kein Testbarkeitsproblem. |
| `@lru_cache` auf Instanzmethoden | keine Treffer in `services/` (nur in `utils/artist_map.py`/`genre_map.py`, dort bereits im Post-ARCH-009-Audit als unproblematisch bewertet) | — |
| Injizierbare Konstruktoren (`config`, `navidrome_api`, `repository`, `logger_factory`) | `SpotifyDownloader`, `PlaylistProcessor`, `DownloadExecutor`, `StatistikService`, `PlayHistoryPoller`, `CoverProcessor` (`fanart_api_key`/`lastfm_api_key`) | **Bereits sauber** — bestätigt den ARCH-003-Phase-1-Befund, dass der Download-/Statistik-Kern bereits DI-konsistent ist. |

**Kein neues, bisher unbekanntes DI-Problem gefunden.** Die einzige
nennenswerte Beobachtung ist die Inkonsistenz zwischen `NavidromeAPI`
(injizierbare Config seit Phase 7) und den übrigen drei Clients (nicht
injizierbare Config) — siehe Abschnitt 3.

---

## 8. Consumer-/Abhängigkeitsanalyse

| Richtung | Fund | Bewertung |
|---|---|---|
| `handlers/` → `services/` | `handlers/navidrome_menu_handler.py` → `NavidromeAPI`; `handlers/mugge_statistik_handler.py`/`handlers/navidrome_menu_handler.py` → `StatistikService`; `handlers/menu/rich_menu_handler.py` → `services/downloader/*` | **normal, erwartbar** |
| `services/` → `handlers/` | `services/downloader/utils/download_result_reporter.py:8` → `from handlers.duplicate_handler import DuplicateEntry` | **potenzielle Schichtverletzung** — bereits als offener DEFER-Punkt in `docs/archive/MusicBot_ENGINEERING_BASELINE.md` (Abschnitt 20) dokumentiert, kein neuer Fund, aber hier erstmals im Kontext eines vollständigen `services/`-Audits eingeordnet. `DuplicateEntry` selbst ist ein reines `@dataclass`-Datenmodell ohne Telegram-Bezug — die Verletzung ist eine Frage der Modul-Zugehörigkeit/Importrichtung, keine Präsentationskopplung. |
| `services/` → `Telegram` | keine Treffer (siehe Abschnitt 5) | — |
| `utils/` → `services/` | keine Treffer | **sauber** |
| `services/` → `klassen/` | keine Treffer | **sauber**, bestätigt den ARCH-006-Befund erneut |
| `services/` → `services/clients/` | `enhanced_metadata_processor.py`/`album_processor.py` → `GeniusClient`/`MusicBrainzClient`/`LastFMClient`; `navidrome_menu_handler.py`/`statistik_service.py` → `NavidromeAPI` | **normal, erwartbare Richtung** |
| Tests → `services/` | breite, direkte Importe der Produktionsklassen (keine Duplikate) | konsistent mit `CLAUDE.md` Abschnitt 7 |

---

## 9. `utils/` gegen `services/` abgrenzen

`utils/` (16 Dateien, ~5.667 Zeilen) enthält aktuell:

- **Reine Mapping-/Fachlogik-Helfer:** `artist_map.py`, `genre_map.py` (Cache-
  /Normalisierungslogik, per Post-ARCH-009-Audit bereits als unproblematisch
  bewertet)
- **Reine technische Utilities:** `filenamefixer.py`, `helpers.py`, `regex.py`,
  `file_ops.py`, `singleton.py`, `cache.py`, `metadata_cache.py`,
  `lyrics_cache.py`, `youtube_parser.py`, `podcast_rss_manager.py`
- **Technische Runner (lokal, kein Netzwerk):** `navidrome_scan_trigger.py`,
  `bot_restart_trigger.py` — entsprechen exakt der in `CLAUDE.md` Abschnitt 4
  definierten Regel
- **Ausreißer:** `audio_enhancer.py` — kombiniert `ffmpeg`-Subprocess-Aufrufe
  **mit echter externer HTTP-Kommunikation** (Last.fm/MusicBrainz/Cover Art
  Archive für Künstlerbilder). Damit verletzt dieses eine Modul die in
  `CLAUDE.md` (aus dem letzten Audit übernommene) Formulierung „lokale
  Subprocess-/Shell-Wrapper **ohne externe Netzwerkkommunikation**" wörtlich.

**Antwort auf die Kernfrage:** `utils/` ist überwiegend kohärent (14 von 16
Dateien passen sauber in „Mapping-Helfer" oder „reiner technischer Runner").
`audio_enhancer.py` ist der einzige Ausreißer — es ist weder ein reiner
`services/clients/`-Adapter (macht auch Subprocess/Dateisystem) noch ein
reiner `utils/`-Runner (macht auch Netzwerk-I/O), sondern strukturell näher
an einer Mischung aus Kategorie B und C. Keine Verschiebung wird hier
vorgeschlagen (ausdrücklich nicht Teil dieses Auftrags) — nur die
Inkonsistenz wird benannt.

**Kein Modul in `utils/` ist eigentlich ein „Service"** (keine fachliche
Orchestrierung mit mehreren Collaborators) oder ein „Client im Verkleidung"
außer der genannten Einschränkung bei `audio_enhancer.py`.

---

## 10. Abgleich: dokumentierte Architekturregeln vs. tatsächlicher Code

| Regel | Dokumentierte Vorgabe | Tatsächlicher Zustand | Abweichung |
|---|---|---|---|
| `services/clients/` = externe Integrationsadapter (`CLAUDE.md` Abschnitt 4/17, `docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`) | Ausschließlich externe API-/HTTP-Kommunikation, keine Telegram-Präsentation, keine Fachlogik | Funktional erfüllt (4/4 Module) | keine funktionale Abweichung; totes `import subprocess` in `navidrome_api.py` ist kosmetisch |
| `utils/` = technische Hilfs-/Runner-Komponenten „ohne externe Netzwerkkommunikation" (`CLAUDE.md` Abschnitt 4, aus Post-ARCH-009-Audit übernommen) | kein Netzwerk-I/O in `utils/` | `audio_enhancer.py` kommuniziert extern (Last.fm/MusicBrainz/Cover Art Archive) | **echte Abweichung** — Regel war zum Zeitpunkt ihrer Formulierung nicht gegen `audio_enhancer.py` geprüft worden |
| `services/` → `handlers/` sollte nicht vorkommen (Schichtgrenzen, `CLAUDE.md` Abschnitt 4) | keine Importe aus `handlers/` in `services/` | `download_result_reporter.py` importiert `DuplicateEntry` aus `handlers/duplicate_handler.py` | **bekannte, bereits dokumentierte Abweichung** (ARCH-007 Abschnitt 4, ENGINEERING_BASELINE DEFER-Punkt) |
| „Der YouTube-Download-Kern ist bereits sauber geschichtet (echte DI, funktionierendes Protocol-Port-System)" (`docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`) | DI-Konsistenz im Download-Kern | bestätigt (`interfaces.py`-Protocols, injizierbare Konstruktoren in `download/`, `downloader.py`, `playlist_processor.py`) | keine Abweichung |
| `klassen/download_handler.py`s Telegram-Kopplung ist architektonisch vorgesehen (`CLAUDE.md` Abschnitt 4/19) | Telegram-Kopplung dort erwartet, kein Fehler | bestätigt, nicht erneut geprüft (außerhalb `services/`) | keine Abweichung |
| „`services/clients/` enthält ausschließlich externe Integrationsadapter, keine Fachlogik" (`docs/archive/post-arch/MusicBot_POST-ARCH-009_Audit.md`) | keine Fachlogik in `services/clients/` | bestätigt, aber DI-Musterinkonsistenz zwischen den 4 Clients war dort nicht geprüft | Ergänzung, keine Korrektur |

**Keine bestehende Regel wird durch diesen Audit geändert** — die Tabelle
dokumentiert ausschließlich Ist-Zustand gegen bereits formulierte Vorgaben.

---

## 11. Zielarchitektur

Auf Basis des tatsächlichen Codes wird die bestehende, bereits in `CLAUDE.md`
verankerte Schichtaufteilung **bestätigt** — es wird keine neue Schicht
vorgeschlagen:

```text
handlers/
    → Benutzerinteraktion / Telegram-Präsentation
      (bestätigt: 0 Telegram-Funde in services/)

services/
    → fachliche Services / Orchestrierung
      (bestätigt für 33 von 35 inhaltstragenden Dateien; 2 Ausnahmen:
       spotify_downloader.py, cover_processor.py — Kategorie E)

services/clients/
    → externe Integrationsadapter
      (bestätigt funktional für alle 4 Module; DI-Konvention nicht
       einheitlich umgesetzt)

utils/
    → technische, wiederverwendbare Hilfs-/Runner-Komponenten
      (bestätigt für 14 von 16 Dateien; audio_enhancer.py als Ausreißer
       benannt, keine Umsetzung vorgeschlagen)

klassen/
    → bestehende projektinterne Komponenten (download_handler.py)
      (unverändert, außerhalb dieses Audits)
```

Kein Bedarf für eine neue Schicht (z. B. „services/media_sources/" für
Cover/Spotify-HTTP-Zugriffe) wurde nachgewiesen — die beiden Kategorie-E-
Fälle sind fachlich zu eng an ihre jeweilige Pipeline gebunden, um sie
pauschal in eine neue generische Schicht zu verschieben; jeder Fall braucht
eine eigene, kleinteilige Entscheidung.

---

## 12. Priorisierung

| Priorität | Kandidat | Problem | Ziel | Nutzen | Risiko | Aufwand | Empfehlung |
|---|---|---|---|---|---|---|---|
| P-1 | `services/downloader/utils/download_result_reporter.py` → `DuplicateEntry`-Import | Service→Handler-Abhängigkeit (`from handlers.duplicate_handler import DuplicateEntry`) | `DuplicateEntry` an neutralen Ort verschieben (z. B. `utils/` oder gemeinsames Datenmodell-Modul), `services/` von `handlers/` entkoppeln | mittel (löst die einzige bekannte Service→Handler-Abhängigkeit) | niedrig (reines `@dataclass`, 1 Importzeile, 1 Verwendungsstelle) | klein | **jetzt untersuchen** |
| P-2 | `services/downloader/utils/metadata/cover_processor.py` | 5 direkte externe HTTP-Aufrufe, davon 1 (Last.fm) dupliziert `services/clients/lastfm_client.py` | Last.fm-Zugriff konsolidieren (`CoverProcessor` nutzt `LastFMClient` statt eigener REST-Calls); übrige 4 Quellen bewusst prüfen | mittel-hoch (löst konkrete Code-Duplikation) | mittel (955 Zeilen, viele Aufrufer/Tests, Scoring-Logik hängt an Rohdaten-Shape) | mittel-groß | später (eigene Analyse nötig) |
| P-2 | `services/downloader/spotify_downloader.py` | 6 direkte HTTP-Aufrufe außerhalb `services/clients/` | prüfen, ob ein `SpotifyMetadataClient` sinnvoll wäre | mittel (strukturelle Klarheit) | mittel (942 Zeilen, komplex) | groß | später (bereits aus vorigem Audit bekannt) |
| P-3 | `services/clients/`-DI-Inkonsistenz (Genius/LastFM/MusicBrainz ohne injizierbare Config) | 3 von 4 Clients konstruieren Config fest | injizierbare `config`-Parameter analog `NavidromeAPI` Phase 7 | niedrig-mittel (Testbarkeit) | niedrig | mittel (3 Dateien + Tests) | beobachten |
| P-3 | tote Imports (`navidrome_api.py:8` `subprocess`, `enhanced_metadata_processor.py:6` `requests`) | kosmetisch, 0 funktionale Wirkung | entfernen | niedrig | keins | trivial | optional, kein eigener Untersuchungsschritt nötig |
| P-3 | `utils/audio_enhancer.py` als Ausreißer der `utils/`-Regel | mischt Subprocess + externe HTTP | ggf. dokumentierte Ausnahme oder spätere Aufteilung | niedrig (funktioniert, ist aktiv verdrahtet) | mittel (Aufteilung würde 3 Verantwortlichkeiten trennen müssen) | mittel | beobachten |

---

## 13. Kategorisierung

### 🔴 Muss untersucht werden
- `services/downloader/utils/download_result_reporter.py`: `DuplicateEntry`-Import aus `handlers/` — einzige echte Schichtverletzung (Service→Handler) im gesamten `services/`-Baum.

### 🟡 Kann verbessert werden
- `services/downloader/utils/metadata/cover_processor.py`: duplizierte Last.fm-Zugriffslogik, 5 direkte externe HTTP-Aufrufe.
- `services/downloader/spotify_downloader.py`: 6 direkte externe HTTP-Aufrufe (bereits bekannt, weiterhin gültig).
- `services/clients/` DI-Inkonsistenz (3 von 4 Clients ohne injizierbare Config).
- `utils/audio_enhancer.py` als einziger Ausreißer der `utils/`-Netzwerk-Regel.
- 2 tote Imports (kosmetisch, kein Architekturrisiko).

### 🟢 Bewusst beibehalten
- `services/downloader/download/` (Protocol-Ports, DI-Kern) — Referenzimplementierung, kein Handlungsbedarf.
- `services/statistik/` — seit ARCH-003 P-6 bereits sauber aufgeteilt, DI-konsistent.
- `services/clients/navidrome_api.py`s funktionale Adapter-Rolle — Regel erfüllt.
- `klassen/download_handler.py`s Telegram-Kopplung — architektonisch vorgesehen, nicht erneut zur Diskussion gestellt.
- `services/statistik/chart_renderer.py` — technische Rendering-Aufgabe, aber fachlich untrennbar an Statistik gebunden, kein eigenständiger Kandidat.

---

## 14. Empfohlener nächster Kandidat

**P-1 — `services/downloader/utils/download_result_reporter.py`: `DuplicateEntry`-Import aus `handlers/duplicate_handler.py` auflösen.**

**Warum dieser Kandidat, nicht `spotify_downloader.py` oder `cover_processor.py`:**

- Es ist die **einzige tatsächliche Schichtverletzung** im gesamten
  `services/`-Baum (Service → Handler) — die HTTP-Kandidaten
  (`spotify_downloader.py`, `cover_processor.py`) sind funktional korrekt
  platziert (echte externe Kommunikation gehört grundsätzlich nicht zwingend
  aus `services/` heraus, nur idealerweise nach `services/clients/`); die
  `DuplicateEntry`-Abhängigkeit verletzt dagegen die Grundregel „`services/`
  hängt nicht von `handlers/` ab" direkt und eindeutig.
- **Kleinster möglicher Schritt:** eine Importzeile, eine Verwendungsstelle
  (`build_duplicate_message()`), ein reines `@dataclass`-Datenmodell ohne
  Telegram-Bezug — strukturell vergleichbar mit der Größe des bereits
  erfolgreich umgesetzten `bot_restart_trigger.py`-Schritts.
- **Bereits bekannt und wartend:** in `docs/archive/MusicBot_ENGINEERING_BASELINE.md`
  (Abschnitt 20) seit ARCH-007 als offener DEFER-Punkt dokumentiert — dieser
  Audit ordnet ihn erstmals in einen vollständigen Architekturkontext ein.
- **Warum nicht `cover_processor.py`/`spotify_downloader.py` jetzt:** beide
  sind wertvolle Funde, aber groß (942/955 Zeilen), mit komplexer,
  eingebetteter Fachlogik (Scoring-Kette bzw. No-API-Download-Strategie) —
  eine Extraktion wäre kein einfacher „Verschieben"-Schritt, sondern
  bräuchte eine eigene, tiefere Analyse (Regel 19: „Verantwortlichkeiten
  zuerst dokumentieren, nicht automatisch zerlegen"). Sie werden als P-2
  zurückgestellt, nicht verworfen.

**Zielschicht:** Neutraler Ort außerhalb von `handlers/` — Kandidaten wären
`utils/` (falls `DuplicateEntry` als reines, wiederverwendbares Datenmodell
verstanden wird) oder ein gemeinsames Modell-Modul; die genaue Zielposition
ist Gegenstand einer eigenen kurzen Analyse, nicht dieses Audits.

**Risiko:** niedrig — 1 Consumer (`download_result_reporter.py`), reines
Datenmodell ohne Verhalten, keine Telegram-Kopplung im Datentyp selbst.

**Bestehende Tests:** `tests/test_download_result_reporter.py` existiert
bereits (laut `docs/archive/MusicBot_ENGINEERING_BASELINE.md` ARCH-003 P-2, 6 neue
Tests für `build_final_summary_message()`/`build_playlist_summary_message()`).
Ob `DuplicateEntry` selbst dediziert getestet ist, wäre Teil einer
Folgeanalyse.

**Noch keine Umsetzung.**

---

## 15. Entscheidungsgate

1. **Ist die vorgeschlagene `services/`-Zielarchitektur sinnvoll?** Sie
   bestätigt im Wesentlichen die bestehende, bereits in `CLAUDE.md`
   dokumentierte Schichtaufteilung — keine neue Schicht wird vorgeschlagen.
2. **Welche Architekturregeln sollten bestätigt werden?** „`services/`
   importiert nicht aus `handlers/`" (aktuell 1 Ausnahme) und „`utils/`
   enthält keine externe Netzwerkkommunikation" (aktuell 1 Ausnahme,
   `audio_enhancer.py`) — beide Regeln bereits dokumentiert, aber noch nicht
   vollständig durchgesetzt.
3. **Welcher Kandidat soll als Nächstes untersucht werden?** Empfehlung:
   P-1 — `DuplicateEntry`-Import in `download_result_reporter.py`.
4. **Soll dieser Kandidat zunächst nur analysiert werden?** Empfehlung: ja,
   konsistent mit dem bisherigen Vorgehen dieser Session (Analyse vor
   Umsetzung).
5. **Kandidaten, die bewusst nicht weiter verfolgt werden sollen:** keiner
   der gefundenen Kandidaten wird als „kein Handlungsbedarf" vollständig
   verworfen — `spotify_downloader.py` und `cover_processor.py` bleiben als
   P-2 im Blick, die DI-Inkonsistenz in `services/clients/` und
   `audio_enhancer.py` als P-3/Beobachtung.

**Keine Codeänderungen wurden vorgenommen. Wartet auf nächste Anweisung.**
