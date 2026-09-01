# EnhancedMetadataProcessor.process_single_track() — Characterization Audit & Minimal Refactor

Ziel: den tatsächlichen Control Flow, die Verantwortlichkeiten, Side
Effects, Fehlergrenzen und Abhängigkeiten von `process_single_track()`
vollständig charakterisieren und nur dann minimal refactoren, wenn die
Analyse eine echte, risikoarme Verbesserung rechtfertigt. Kein
pauschales Zerlegen der Methode.

## Baseline

| Feld | Wert |
|---|---|
| HEAD (Start) | `b8edd1d816a59b4b4e8757266c324e79a41084cc` (main, nach DL-03/DL-05-Merge PR #94) |
| Branch | `refactor/enhanced-metadata-processor-process-single-track` |
| Teststatus (Start) | 1663 passed, 1 skipped, 0 failed |
| Referenzierte Docs | `docs/MusicBot_ENGINEERING_BASELINE_v6.md`, `docs/MusicBot_ARCHITECTURE_EVOLUTION.md`, `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md`, `docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md` |

Bereits getroffene, hier respektierte Vorentscheidungen: der
Services-Audit hatte `process_single_track()` bereits als „LEGITIMATE
ORCHESTRATOR auf Klassenebene, aber SUSPICIOUS auf Methodenebene (908
Zeilen)" eingestuft und explizit keine Umsetzung empfohlen (MIG-05, P3,
„hoher Aufwand, CLAUDE.md Abschnitt 19: nicht ohne vorherige
Tests/Dokumentation zerlegen"). Der DL-Retry-Audit hatte den internen
`except Exception`-Fang der Methode bereits analysiert (verlorener
Exception-Typ) und bewusst nicht angefasst. Beide Punkte werden hier
nicht neu bewertet.

## Method Characterization

### Aktuelle Größe

`process_single_track()`: Zeile 248–1150 (vor diesem Refactor: 908
Zeilen inkl. Docstring/Leerzeilen; nach Debug-Log-Bereinigung: 875
Zeilen). Größte Einzelmethode im gesamten `services/`-Baum (bestätigt
gegen Services-Audit).

### EnhancedMetadataProcessor — Übersicht

```
EnhancedMetadataProcessor (SingletonMixin)
│
├── process_single_track()                    [async, Hauptmethode]
│
├── private helper methods
│   ├── _determine_genre_with_stats()           [async, ECHT genutzt — 1 Aufruf in process_single_track()]
│   ├── _fetch_album_info_from_musicbrainz()     [async, 0 Aufrufer — reiner Delegate]
│   └── 15× "Delegate-Methoden (für Abwärtskompatibilität)"
│       (_clean_track_title_enhanced, _build_search_title,
│        _should_remove_leading_fragment, _apply_title_cleanup_rules,
│        _remove_artist_from_title, _check_metadata_cache,
│        _store_in_metadata_cache, _determine_best_artist_corrected,
│        _find_known_artist_from_list, _clean_artist_before_normalization,
│        _prioritize_genres, _normalize_genre_name, _determine_album_info,
│        _determine_track_number, _extract_year_from_string)
│       — alle 0 Aufrufer repoweit (siehe Findings, DUPLICATED/DEAD LOGIC)
│
├── injected collaborators (_do_init, Constructor-Injection)
│   ├── ArtistNormalizer (utils.artist_map)      — direkt UND via ArtistProcessor
│   ├── ArtistProcessor
│   ├── GenreMapper (utils.genre_map)            — nur via GenreProcessor
│   ├── GenreProcessor
│   ├── GeniusClient (services.clients)          — nur via LyricsProcessor
│   ├── LyricsProcessor
│   ├── CoverProcessor
│   ├── MetadataCache (utils.metadata_cache)     — nur via MetadataCacheHandler
│   ├── MetadataCacheHandler
│   ├── TitleCleaner
│   ├── AlbumProcessor
│   ├── AutoLearnManager
│   └── TagWriter
│
├── state/configuration
│   ├── self.config                              — einmalig in _do_init gesetzt, danach nie neu zugewiesen
│   ├── self.processing_stats (EnhancedProcessingStats) — 12 Zähler, += pro Track, prozesslebensdauer-gebunden
│   ├── self.processed_titles (set)              — In-Memory-Duplikaterkennung, prozesslebensdauer-gebunden
│   ├── self._mb_client / self._lfm_client       — Lazy-Init beim ersten Genre-Aufruf, danach wiederverwendet
│   └── self.logger / self.logger_factory / self.genius_logger / self.cache_logger
│
└── external side effects (siehe Side-Effect-Übersicht unten)
```

### Side Effects (repoweit verifiziert)

| Art | Fundstelle in process_single_track() | Bewertung |
|---|---|---|
| Filesystem (Lesen) | `load_special_channels_merged()` (special_channel.yaml), `original_path.exists()` | synchron, siehe Async-Abschnitt |
| Filesystem (Schreiben) | `filename_fixer.move_to_library()`, `tag_writer.write_tags()` (via `asyncio.to_thread`) | move_to_library() synchron, siehe Async-Abschnitt |
| Netzwerk | MusicBrainz/Last.fm (via `_determine_genre_with_stats()`→GenreProcessor), Genius (via LyricsProcessor), Cover-Quellen (via CoverProcessor, `asyncio.to_thread`) | alle bereits an Kollaboratoren delegiert |
| Subprocess | FFmpeg (via `AudioEnhancer.normalize_loudness`, `asyncio.to_thread`) | delegiert an utils/ |
| Cache | `self.cache_handler.check()`/`.store()` (Schritt 2/19) | delegiert an MetadataCacheHandler |
| Persistenz (Auto-Learn) | `self.auto_learn_manager.learn_genre()/learn_artist()/observe_featured_artists()` (Schritt 19b/19c) | delegiert, YAML-Schreiben |
| Logging | durchgängig, `self.logger` | siehe Findings (Debug-Reste) |

## Control Flow (tatsächlich, aus dem Code rekonstruiert)

```
process_single_track(track_metadata, filename_fixer, playlist_metadata=None, dominant_artist=None)
│
├─ 1. track_metadata is None?  → early return MetadataResult(success=False)
│
├─ [try-Block beginnt, original_path/library_path vorab auf None gebunden
│   (ARCH-005/DL-01: müssen im except-Zweig immer definiert sein)]
│
├─ 2. Cache-Check (cache_handler.check)  → bei Hit: early return (cache_result)
├─ 3. Basis-Daten extrahieren (raw_title/raw_artist/video_id/channel_name)
│      + Channel-Normalisierung (try/except, Fehler wird NUR geloggt, nie propagiert)
│      + Podcast-Channel-Erkennung (hartcodierte 2-Namen-Liste)
├─ 4. YouTube-Titel parsen (parse_youtube_title) — übersprungen bei Podcast
├─ 5. Artist-Map-Fallback-Parsing — nur wenn YT-Parser kein song_title lieferte
├─ 5.5 Spezialkanal-Pre-Check (load_special_channels_merged + get_special_channel_info)
│      → bestimmt _is_special_channel_pre, _pre_category, _canonical_channel_name
│      → bei Spezialkanal: dominant_artist wird NICHT übernommen
├─ 5.6 Raw-Artist-Bereinigung (raw_artist == Kanal/Uploader? → verwerfen)
├─ 6. Artist-Bestimmung
│      → Feature-Split auf all_artists/artist (split_main_and_featuring, inline)
│      → artist_processor.determine_best_artist() (Kollaborator)
│      → Feature-Artists-Liste konsolidieren (inline, dedupliziert)
├─ 7. Titel-Bereinigung (title_cleaner.light_title_cleanup / build_search_title)
├─ 8. Duplikat-Erkennung (In-Memory, self.processed_titles) — NUR Statistik/Log,
│      kein Abbruch (is_duplicate landet im Result, Verarbeitung läuft weiter)
├─ 9. Genre (_determine_genre_with_stats → genre_processor.determine_genre_with_fallbacks)
├─ 9b. MusicBrainz-IDs aus Genre-Pipeline in track_metadata übernehmen (inline)
├─ 10. Lyrics (lyrics_processor.fetch_lyrics_with_fallback)
├─ 11a. MB-IDs vorab holen für Cover (album_processor.fetch_album_from_musicbrainz),
│       übersprungen wenn IDs schon aus Schritt 9b bekannt oder Spezialkanal
├─ 11b. Cover-Art (cover_processor.get_cover_art, via asyncio.to_thread — SAFE)
├─ 12. Album/Jahr (album_processor.determine_album_info)
├─ 13. Track-Nummer (album_processor.determine_track_number)
├─ 14. Dateipfad-Prüfung → raise ValueError/FileNotFoundError bei fehlendem Pfad
├─ 15. Spezialkanal-Logik (Album/Artist-Overrides für Podcast) ODER
│       Single-Download-Logik (Album-Template, ggf. zweiter MB-Call)
├─ 15b. Loudness-Normalisierung (AudioEnhancer.normalize_loudness, asyncio.to_thread
│        — SAFE; Fehler NUR geloggt, nie kritisch/propagiert)
├─ 16. Datei verschieben (filename_fixer.move_to_library — SYNCHRON, kein to_thread,
│        siehe Async-Abschnitt)
├─ 17. Tags schreiben (tag_writer.write_tags, asyncio.to_thread — SAFE)
│        → bei Fehler: inkonsistente Library-Datei wird gezielt gelöscht,
│          Exception wird weitergereicht (FINDING-2/PARTIAL-FAILURE-LIBRARY)
├─ 18. MetadataResult(success=True, ...) erstellen
├─ 19. Cache speichern (cache_handler.store)
├─ 19b. Genre-Auto-Learning (auto_learn_manager.learn_genre) — bedingt, eigenes
│        try/except, Fehler NUR geloggt
├─ 19c. Artist-/Feature-Auto-Learning (learn_artist, observe_featured_artists)
│        — bedingt, eigene try/except, Fehler NUR geloggt
├─ 20. return result
│
├─ except asyncio.CancelledError: Cleanup einer bereits verschobenen,
│      aber nicht registrierten Library-Datei (DL-01), dann re-raise
│
└─ except Exception as e: Cleanup der Download-Datei (ARCH-005 Strategie C),
       return MetadataResult(success=False, error=str(e))
```

Kein Schritt wurde umbenannt oder umgeordnet — dies ist der reale,
aus dem Code gelesene Ablauf.

## Responsibility Matrix

| Bereich | Aktuelle Funktion/Methode | Responsibility | Side Effect | Abhängigkeiten | Kandidat für Extraktion? |
|---|---|---|---|---|---|
| Input | Schritt 1 (None-Check) | Validierung | keiner | keine | **NO** — trivialer Guard, jede Extraktion wäre reines Overhead |
| Basis-Daten/Channel | Schritt 3, 5.5, 5.6 (inline) | Track-spezifische Vorverarbeitung (Podcast-/Spezialkanal-Erkennung, Artist-Bereinigung) | keiner | `artist_normalizer`, `load_special_channels_merged` | **NO** — echte Orchestrierungs-/Entscheidungslogik, die die nachfolgenden Schritte steuert; keine bestehende Komponente besitzt diese Verantwortung, keine klare eigenständige fachliche Grenze ohne Umbau mehrerer Folge-Schritte |
| Artist | Schritt 6 (inline Feature-Split + `artist_processor.determine_best_artist`) | Künstlerbestimmung | keiner | `ArtistProcessor` (bereits extrahiert) | **NO** für den Kollaborator-Aufruf selbst (bereits delegiert); inline Feature-Split/-Konsolidierung ist Ergebnis-Nachbearbeitung, eng an Schritt 9b/17 gekoppelt — Extraktion würde Datenfluss zerreißen ohne Komplexitätsgewinn |
| Title | Schritt 7 (`title_cleaner.light_title_cleanup`/`build_search_title`) | Titelbereinigung | keiner | `TitleCleaner` (bereits extrahiert) | **NO** — bereits delegiert |
| Duplicate (in-memory) | Schritt 8 | Prozess-lebenslange Duplikaterkennung (nur Statistik) | `self.processed_titles` | keine | **NO** — 4 Zeilen, kein eigenständiger Bereich |
| Genre | Schritt 9 (`_determine_genre_with_stats`) | Genre-Bestimmung + Lazy-Client-Init | `self._mb_client`/`self._lfm_client` | `GenreProcessor` (bereits extrahiert) | **NO** — bereits eigene Methode, bereits delegiert |
| MB-ID-Reconciliation | Schritt 9b, 11a | MusicBrainz-IDs zwischen zwei Pipeline-Zweigen (Genre vs. Album-Prefetch) synchron halten | `track_metadata`-Mutation | keine externe | **NO** — reine Datenfluss-Verdrahtung zwischen bereits delegierten Ergebnissen, kein eigenständiges fachliches Konzept |
| Lyrics | Schritt 10 | Lyrics-Suche | keiner | `LyricsProcessor` (bereits extrahiert) | **NO** — bereits delegiert |
| Cover | Schritt 11a/11b | Cover-Art-Beschaffung | keiner (async-safe) | `CoverProcessor` (bereits extrahiert) | **NO** — bereits delegiert, bereits async-sicher |
| Album/Jahr | Schritt 12/13/15 | Album-/Jahr-/Track-Nummer-Bestimmung + Spezialkanal-/Single-Override | keiner | `AlbumProcessor` (bereits extrahiert) | **NO** — Kern bereits delegiert; die Override-Logik in Schritt 15 ist track-spezifische Entscheidungslogik (Podcast vs. Single vs. Playlist), nicht eigenständig fachlich, sondern Verdrahtung zwischen Album-Ergebnis und Kontext |
| Tags | Schritt 17 (`tag_writer.write_tags`) | Tag-Schreiben | Filesystem (async-safe) | `TagWriter` (bereits extrahiert) | **NO** — bereits delegiert, bereits async-sicher |
| Loudness | Schritt 15b | Audio-Normalisierung | Subprocess (async-safe) | `AudioEnhancer` (utils/) | **NO** — bereits ausgelagert, bereits async-sicher |
| Library-Move | Schritt 16 | Datei in Bibliothek verschieben | Filesystem (synchron) | `filename_fixer` (Parameter, nicht Konstruktor-Injection) | **NO** — bereits delegiert; Sync-Charakter bereits in Phase 5 gemessen/akzeptiert (<20ms), keine Neubewertung in diesem Scope |
| Errors | try/except-Rahmen (Anfang bis Ende) | Fehlerbehandlung/Cleanup | Filesystem-Cleanup | `cleanup_single_download_artifact` | **NO** — siehe Error-Handling-Abschnitt; ein `except Exception`-Catch-all ist hier bewusst (Contract: Methode wirft nie, gibt immer `MetadataResult` zurück) |
| Auto-Learn | Schritt 19b/19c | Genre-/Artist-/Feature-Learning-Aufrufe + Spezialkanal-Ausschluss | Filesystem (YAML, via AutoLearnManager) | `AutoLearnManager` (bereits extrahiert) | **NO** für die Aufrufe selbst; **JA (umgesetzt, siehe Implementation)** für die redundante `load_special_channels_merged()`-Neuberechnung |
| Result | Schritt 18 | Ergebnis-Konstruktion | keiner | `MetadataResult` (Datenmodell) | **NO** — reine Datenklassen-Konstruktion aus bereits berechneten Werten |
| Debug-Logging | Schritt 9/9b/11a (vor Fix) | keine (Debug-Reste) | Logging-Rauschen | keine | **JA (umgesetzt, siehe Implementation)** — kein Business-Wert, reine Aufräumarbeit |

## Orchestrator vs. Business Logic

Die überwiegende Mehrheit der ~875 Zeilen ist **Orchestrierung**
(Aufrufe an bereits extrahierte Kollaboratoren) oder **track-lokale
Entscheidungslogik**, die die Reihenfolge/Bedingungen zwischen diesen
Aufrufen steuert (z. B. „ist das ein Spezialkanal", „wurden MB-IDs schon
aus der Genre-Pipeline geliefert", „ist das ein Single- oder
Playlist-Download"). Diese Entscheidungslogik hat keine sinnvolle
eigene Heimat außerhalb der Methode: sie verbindet die Ergebnisse
mehrerer Kollaboratoren miteinander und steuert direkt die
Reihenfolge der nächsten Schritte — genau das, was CLAUDE.md/Abschnitt
6 der Aufgabenstellung als legitime Orchestrierung beschreibt.

**Keine Infrastruktur landet direkt im Orchestrator, ohne dass ein
Kollaborator existiert** — jeder Filesystem-/Netzwerk-/Subprocess-Zugriff
läuft durch eine bereits extrahierte Klasse (`CoverProcessor`,
`TagWriter`, `AudioEnhancer`, `AlbumProcessor` usw.). Die einzige direkte
Infrastruktur-Berührung im Orchestrator selbst ist
`load_special_channels_merged()` (Datei-Lesen) und
`original_path.exists()`/`filename_fixer.move_to_library()` — beide
bereits als eigene, fokussierte Funktionen/Methoden in `utils/`
vorhanden, hier nur aufgerufen, nicht neu implementiert.

## Dependency Map

| Abhängigkeit | Warum benötigt? | Nur delegiert? | Eigene Logik drumherum? | Bereits geeignete Abstraktion? | Versteckte Kopplung? |
|---|---|---|---|---|---|
| `ArtistProcessor` | Künstlerbestimmung | Ja | Feature-Split-Vor-/Nachbereitung (inline) | Ja | Nein |
| `TitleCleaner` | Titelbereinigung | Ja | Nein | Ja | Nein |
| `GenreProcessor` | Genre-Bestimmung | Ja (via `_determine_genre_with_stats`) | Lazy-Client-Init | Ja | Nein |
| `LyricsProcessor` | Lyrics-Suche | Ja | Nein | Ja | Nein |
| `CoverProcessor` | Cover-Beschaffung | Ja | MB-ID-Aufbereitung vor dem Aufruf (inline) | Ja | Nein |
| `AlbumProcessor` | Album/Jahr/Track-Nummer | Ja | Spezialkanal-/Single-Override (inline) | Ja | Nein |
| `TagWriter` | Tag-Schreiben | Ja | Nein | Ja | Nein |
| `AutoLearnManager` | Auto-Learning | Ja | Spezialkanal-Ausschlussprüfung (inline) | Ja | **Ja (klein)** — `self.auto_learn_manager._is_genre_manually_defined(...)` wird als "privat" markierte Methode von außerhalb der Klasse aufgerufen (Abschnitt „Findings", HIDDEN COUPLING) |
| `MetadataCacheHandler` | Cache-Check/-Store | Ja | Nein | Ja | Nein |
| `ArtistNormalizer` | Channel-Normalisierung, YouTube-Titel-Fallback-Parsing | Teils (auch direkt genutzt, nicht nur über `ArtistProcessor`) | Nein | Ja | Nein — bewusst doppelte Nutzung (Channel-Ebene vs. Artist-Ebene sind unterschiedliche fachliche Fragen) |
| `filename_fixer` (Parameter) | Datei-Verschieben | Ja | Nein | Ja | **Ja (klein)** — als Methodenparameter statt Konstruktor-Injection übergeben, einzige Abhängigkeit dieser Methode mit diesem Muster; historisch bedingt (Playlist-/Single-Pfad teilen sich eine Instanz aus `download_utils.py`), nicht neu bewertet, da Vertragsänderung außerhalb des Scopes (Section 16: „Parameter nicht ohne zwingenden Grund ändern") |
| `AudioEnhancer` (utils, lokaler Import) | Loudness-Normalisierung | Ja | Content-Type-Bestimmung (inline) | Ja | Nein |
| `cleanup_single_download_artifact` | Aufräumen bei Fehler | Ja | Nein | Ja | Nein |
| `load_special_channels_merged`/`get_special_channel_info`/`get_special_category` (utils, Modulfunktionen) | Spezialkanal-Erkennung | Ja | Nein | Ja | **War (behoben)** — redundanter zweiter Aufruf, siehe Implementation |

## State Analysis

`process_single_track()` mutiert Objektzustand an genau 3 Stellen:

1. `self.processing_stats.<feld> += 1` (12 Stellen) — kumulative
   Prozess-Statistik über die Lebensdauer der (Singleton-)Instanz, kein
   Reset pro Track. Zweck: `get_processing_statistics()`. Konsistent mit
   dem dokumentierten Zweck des Feldes.
2. `self.processed_titles.add(title_key)` (1 Stelle, Set) — In-Memory-
   Duplikaterkennung über die Prozesslebensdauer, kein Reset pro Track
   außer via `reset_statistics()`.
3. `self._mb_client`/`self._lfm_client` (in `_determine_genre_with_stats`,
   nicht direkt in `process_single_track()`) — Lazy-Init einmalig,
   danach wiederverwendet.

**Concurrency-Bewertung:** Alle drei Stellen werden ausschließlich
synchron (kein `await` zwischen Lesen und Schreiben) mutiert — innerhalb
der kooperativen Single-Thread-Ausführung von asyncio sind sie damit
atomar gegenüber Interleaving durch andere Coroutinen, selbst wenn zwei
Telegram-Nutzer gleichzeitig einen Download auslösen (dieselbe Analyse-
Methodik wie in früheren Audits dieser Session, z. B. TOCTOU-Bewertung
in `move_to_library()`). Kein neuer Race-Fund. Der State wird für seinen
dokumentierten Zweck tatsächlich benötigt — keine State-Refaktorierung
durchgeführt (Abschnitt 8 der Aufgabenstellung: nicht erforderlich).

## Error Handling Analysis

```
Exception
   ↓
try-Block umschließt Schritte 2-19c (Cache-Check bis Auto-Learn)
   ↓
except asyncio.CancelledError (DL-01):
   → Cleanup einer ggf. bereits verschobenen, aber nicht registrierten
     Library-Datei
   → re-raise (Cancellation wird NICHT unterdrückt)
   ↓
except Exception as e (catch-all):
   → cleanup_single_download_artifact() (Download-Datei-Cleanup)
   → return MetadataResult(success=False, error=str(e))
   → urspruenglicher Exception-TYP geht verloren, nur str(e) bleibt
     (bereits im DL-Retry-Audit dokumentiert, hier bestätigt, nicht
     erneut behoben — außerhalb des Scopes dieses Tasks)
```

Zusätzlich 4 lokale, engere try/except-Blöcke innerhalb der Methode:

| Ort | Fängt | Verhalten |
|---|---|---|
| Schritt 3 (Channel-Normalisierung) | `Exception` | nur geloggt (`debug`), Verarbeitung läuft mit unnormalisiertem Kanalnamen weiter — **optionaler, fachlich unkritischer Fehler** |
| Schritt 15b (Loudness) | `ImportError`, `Exception` | nur geloggt (`debug`/`warning`), nie kritisch — **optionaler externer Fehler** (dokumentiert im Code selbst) |
| Schritt 17 (Tag-Schreiben) | `Exception` als `tag_err` | inkonsistente Library-Datei wird gezielt gelöscht, Exception wird **weitergereicht** an den äußeren Catch-all — **kritischer, lokaler Filesystem-Fehler** |
| Schritt 19b/19c (Auto-Learn, 3× ähnlich) | `Exception` als `_learn_err` | nur geloggt (`warning`), nie kritisch — **optionaler Fehler**, Track gilt trotzdem als erfolgreich verarbeitet |

**Bewertung:** Die Unterscheidung erwartbar-fachlich (Channel-Normalisierung,
Loudness, Auto-Learn — alle optional, degradieren graceful) vs. kritisch
(Tag-Schreiben, alles vor Schritt 14 inkl. Dateipfad-Prüfung) ist bereits
sauber im Code umgesetzt und durch bestehende Tests abgesichert
(`test_metadata_processor_happy_path.py`,
`test_enhanced_metadata_processor_cancellation.py`). Der äußere
Catch-all-`except Exception` ist **kein unbeabsichtigter Fehler**,
sondern der bewusste Vertrag der Methode: sie wirft nie eine Exception
nach außen (außer `CancelledError`), sondern gibt immer ein
`MetadataResult` zurück — bestätigt durch die Aufrufer-Seite
(`_process_single_download()` in `download_utils.py`, DL-Retry-Audit).
Kein allgemeines Error-Handling-Refactoring durchgeführt (außerhalb des
Scopes, Abschnitt 9 der Aufgabenstellung).

## Async / Event Loop

| Aufruf | await? | Blockierend? | Absicherung |
|---|---|---|---|
| `cache_handler.check/store` | nein (sync-Aufruf, kein `await`) | lokal, kein Filesystem/Netzwerk (In-Memory + kleine JSON-Dateien) | nicht vertieft geprüft, außerhalb des Scopes |
| `genre_processor.determine_genre_with_fallbacks` | ja | delegiert intern (Netzwerk) | bereits async, nicht Teil dieses Audits |
| `lyrics_processor.fetch_lyrics_with_fallback` | ja | delegiert intern (Netzwerk) | bereits async |
| `album_processor.fetch_album_from_musicbrainz` | ja | delegiert intern (Netzwerk) | bereits async |
| `cover_processor.get_cover_art` | ja, via `asyncio.to_thread` | ja (bis zu 6 Quellen sequenziell) | **SAFE VIA to_thread** (FINDING-1/COVER-BLOCKING, bereits gefixt, hier bestätigt) |
| `AudioEnhancer.normalize_loudness` | ja, via `asyncio.to_thread` | ja (2× FFmpeg-Subprocess) | **SAFE VIA to_thread** (FINDING-7, bereits gefixt, hier bestätigt) |
| `filename_fixer.move_to_library` | **nein** | ja (Filesystem-Copy/Move), aber gemessen <20ms | **SAFE (bereits akzeptiert, Phase 5 Performance Baseline)** — keine Neubewertung |
| `tag_writer.write_tags` | ja, via `asyncio.to_thread` | ja (mutagen I/O) | **SAFE VIA to_thread** (AE-12, bereits gefixt, hier bestätigt) |
| `auto_learn_manager.learn_genre/learn_artist/observe_featured_artists` | ja (`async def`), aber **intern synchrones Datei-I/O ungewrappt** | ja | **BEKANNTE, BEREITS DOKUMENTIERTE INV-01-VERLETZUNG** (`docs/MusicBot_ARCHITECTURE_EVOLUTION.md`, Abschnitt „Auto-Learn (Genre+Artist)") — nicht Teil dieses Tasks, nicht angefasst |
| `load_special_channels_merged` (Schritt 5.5) | nein | ja (synchrones Datei-Lesen, kein `to_thread`) | klein (YAML-Datei), nicht als eigener Blocking-Fund eingestuft; die in diesem Audit behobene Redundanz halbiert zumindest die Häufigkeit dieses synchronen Lesens pro Track |

**Kein Refactor verschlechtert eine bestehende Async-Garantie** — die
Dedup-Änderung entfernt lediglich einen zweiten, identischen
synchronen Lesevorgang; sie fügt keinen neuen `await`/keine neue
Blockierung hinzu und ändert an keiner bestehenden `to_thread`-Stelle
etwas.

## Findings

| Finding | Klassifikation |
|---|---|
| Delegation an 8 Kollaboratoren (Artist/Title/Genre/Lyrics/Cover/Album/Tags/AutoLearn) | **LEGITIMATE ORCHESTRATION** |
| Track-lokale Entscheidungslogik (Spezialkanal-/Podcast-/Single-vs-Playlist-Verzweigungen, MB-ID-Reconciliation, Feature-Artist-Konsolidierung) | **BUSINESS LOGIC**, aber ohne klare eigenständige, servicewürdige Grenze — bleibt Orchestrator-lokal |
| Alle Filesystem-/Netzwerk-/Subprocess-Zugriffe laufen durch bereits extrahierte Klassen | **INFRASTRUCTURE bereits korrekt ausgelagert** |
| `load_special_channels_merged(self.config)` zweimal mit identischem Ergebnis aufgerufen | **TRUE (kleiner) ARCHITECTURAL DEBT** — behoben (siehe Implementation) |
| `[DEBUG 9]`/`[DEBUG 9b]`/`[DEBUG ALBUM PREFETCH]`-Logging bei `INFO`-Level | **TECHNICAL DEBT (Logging-Reste)** — behoben (siehe Implementation) |
| 15 „Delegate-Methoden (für Abwärtskompatibilität)" (Zeile ~1170–1300), 0 Aufrufer repoweit | **DUPLICATED/DEAD LOGIC** (explizit als Kompatibilitätsschicht dokumentiert) — **nicht behoben**, siehe Out of Scope |
| `self.auto_learn_manager._is_genre_manually_defined(...)` — Zugriff auf "privat" markierte Methode einer anderen Klasse | **HIDDEN COUPLING (klein)** — nicht behoben, siehe Out of Scope |
| `filename_fixer` als Methodenparameter statt Konstruktor-Injection | **ACCEPTABLE COUPLING** (historisch, funktional folgenlos) — nicht behoben |
| Auto-Learn-Aufrufe mit intern ungewrapptem synchronem Datei-I/O | **BEKANNTE INV-01-VERLETZUNG** (bereits dokumentiert, `MusicBot_ARCHITECTURE_EVOLUTION.md`) — nicht behoben, außerhalb des Scopes |

## Refactor Decision

**MINIMAL REFACTOR**

Begründung: `process_single_track()` ist trotz ihrer Größe **kein
Architekturproblem** — die Analyse fand **keine** klar abgegrenzte
fachliche Verantwortung, die noch nicht bereits in einen der 8
Kollaboratoren extrahiert ist, und **keine** Infrastruktur, die direkt
(ohne Kollaborator) im Orchestrator läuft. „Große Methode" ist hier
tatsächlich „legitimer Orchestrator + Verdrahtungslogik zwischen
bereits extrahierten Komponenten", nicht „versteckte Verantwortung,
die extrahiert werden sollte" (Abschnitt 13-A wäre für die
Extraktions-Frage korrekt gewesen). Es wurden jedoch zwei konkrete,
eng abgegrenzte, risikoarme Fixes identifiziert, die unter „Verbesserung
der lokalen Lesbarkeit/Orchestrierung" fallen (Abschnitt 0, erlaubter
Scope) und umgesetzt wurden — keine neue Methode, keine neue
Komponente, keine Verhaltensänderung.

## Implementation

Einzige geänderte Produktionsdatei:
`services/metadata/enhanced_metadata_processor.py`.

1. **Redundanten `load_special_channels_merged()`-Aufruf entfernt**
   (Schritt 19b): das bei Schritt 5.5 bereits berechnete
   `_special_channels_cfg` wird wiederverwendet statt ein zweites Mal
   dieselbe YAML-Datei zu lesen und zu parsen. `self.config` wird
   innerhalb der Methode nirgends neu zugewiesen — beide Aufrufe hätten
   immer identische Ergebnisse geliefert.
2. **Debug-Log-Reste entfernt** (`[DEBUG 9]`, `[DEBUG 9b]`,
   `[DEBUG ALBUM PREFETCH]`, 8 `logger.info()`-Aufrufe): reine
   Instrumentierungs-Reste ohne fachlichen Wert, bei `INFO`-Level (nicht
   einmal `DEBUG`), dumpten volle Objekt-`__dict__`s/Dicts auf jeden
   verarbeiteten Track. Kein Test und keine andere Codestelle war auf
   diese Log-Zeilen angewiesen (repoweit verifiziert).

## Behavioral Guarantees

Unverändert geblieben:

- Öffentliche Signatur von `process_single_track()` (Parameter,
  Rückgabetyp `MetadataResult`, Exceptions).
- Reihenfolge und Bedingungen aller 20 Verarbeitungsschritte.
- `MetadataResult`-Feldbelegung (identische Werte für identische Eingaben).
- Retry-/Cancellation-/Error-Verhalten (DL-01, FINDING-2, ARCH-005).
- Alle bestehenden `to_thread`-Absicherungen (Cover, Loudness, Tags).
- Auto-Learn-Aufrufbedingungen (`_is_special_channel_for_learning`
  liefert für jeden Input exakt denselben Wert wie vorher — nur die
  Berechnung des zugrunde liegenden Konfigurations-Dicts wurde
  dedupliziert, nicht seine Semantik).
- Alle Log-Marker außer den entfernten Debug-Resten (Emojis,
  Schritt-Nummerierung, Formatierung).

## Tests

### Characterization

Bestehende Testabdeckung für `process_single_track()` vor diesem Task
bereits umfangreich (11 Testdateien, u. a. Happy Path, Cache-Hit,
fehlender Filepath, Cleanup nach Tag-Fehler, 9 Cancellation-Szenarien,
Cover-/Loudness-/Write-Tags-Event-Loop-Blocking, Spezialkanal-Auto-Learn-
Gate) — ausreichend, um das bisherige Verhalten bereits abzusichern.
Keine zusätzlichen Characterization-Tests für unveränderte Pfade nötig.

### Gezielt (neu)

1 neuer Test, `tests/test_enhanced_metadata_processor_special_channel_lookup_dedup.py`:
verifiziert `load_special_channels_merged()` wird genau 1× statt 2× pro
Track aufgerufen. Pre-Fix-Diskriminierung verifiziert (Test schlägt am
ungefixten Code mit `2 == 1`-AssertionError fehl).

```
python3 -m pytest tests/test_metadata_processor_happy_path.py tests/test_autolearn_special_channel_gate.py tests/test_enhanced_metadata_processor_cancellation.py tests/test_enhanced_metadata_processor_cover_blocking.py tests/test_enhanced_metadata_processor_event_loop_blocking.py tests/test_enhanced_metadata_processor_loudness_blocking.py tests/test_enhanced_metadata_processor_special_channel_lookup_dedup.py tests/test_download_utils_metadata_translation.py tests/test_download_utils_single_download_cleanup.py tests/test_download_handler_process_single_download_result.py tests/test_metadata_result_translator.py tests/test_genius_client_fallback_chain.py -q
82 passed
```

### Thematisch

```
python3 -m pytest tests/ -q -k "metadata or genre or artist or cover or lyrics or album or tag_writer"
703 passed, 1 skipped, 961 deselected
```

### Finale Full Suite

```
python3 -m pytest tests/ -q
1664 passed, 1 skipped, 0 failed  (Baseline: 1663 passed, 1 skipped → +1 neuer Test)
```

Keine Regression.

## Remaining Complexity

`process_single_track()` bleibt mit ~875 Zeilen weiterhin die größte
Methode im `services/`-Baum. Dies wird hier **ausdrücklich als
architektonisch akzeptabel** dokumentiert:

- Jede fachlich klar abgegrenzte Verantwortung (Artist/Title/Genre/
  Lyrics/Cover/Album/Tags/Auto-Learn) ist bereits in eine eigene,
  fokussierte, einzeln testbare Klasse extrahiert (8 Kollaboratoren).
- Was in der Methode verbleibt, ist **Verdrahtungslogik**: Reihenfolge,
  Bedingungen und Datenfluss zwischen diesen 8 Kollaboratoren
  (z. B. „welche MB-IDs kamen aus welcher Pipeline", „ist das ein
  Spezialkanal, der Album-Overrides braucht", „lohnt sich ein zweiter
  MusicBrainz-Call"). Diese Logik hat keine natürliche eigene fachliche
  Identität außerhalb des Tracks, den sie gerade verarbeitet — jede
  künstliche Extraktion (z. B. „TrackProcessingContext" oder
  "MetadataPipelineCoordinator") würde laut Abschnitt 15 der
  Aufgabenstellung genau die verbotene zusätzliche Architektur-Ebene
  einführen, ohne die Komplexität tatsächlich zu senken (die
  Bedingungen und der Datenfluss blieben identisch, nur hinter einem
  zusätzlichen Objekt versteckt).
- Die einzigen zwei konkreten, mit Beweis belegten Verbesserungen
  (redundanter Datei-Read, Debug-Log-Reste) wurden umgesetzt.
- Verbleibende, bewusst nicht angefasste kleinere Funde (Delegate-
  Kompatibilitätsschicht, `_is_genre_manually_defined()`-Zugriff,
  `filename_fixer`-Parameter-Muster, Auto-Learn-INV-01) sind alle klein,
  bereits einzeln dokumentiert und für sich genommen keine
  Rechtfertigung für eine Struktur-Änderung von
  `process_single_track()` selbst.

**Fazit: Große Methode ≠ Architekturverletzung.** Das war das erwartete,
in Abschnitt 23 der Aufgabenstellung explizit als Erfolg gewertete
Ergebnis für den überwiegenden Teil der Methode — ergänzt um zwei
kleine, konkret belegte Aufräum-Fixes.

## Out of Scope

Bewusst untersucht, aber **nicht** verändert:

- **15 „Delegate-Methoden (für Abwärtskompatibilität)"** (0 Aufrufer
  repoweit) — laut CLAUDE.md Abschnitt 20 wird eine explizit als
  Kompatibilitätsschicht dokumentierte Methode nicht ohne dedizierten
  Auftrag entfernt, auch wenn aktuell kein Aufrufer gefunden wurde. Hier
  nur dokumentiert (siehe Findings), keine Löschung.
- **`self.auto_learn_manager._is_genre_manually_defined(...)`** — Zugriff
  auf eine als privat markierte Methode einer anderen Klasse. Eine
  saubere Lösung (öffentliche Methode auf `AutoLearnManager` ergänzen)
  wäre eine API-Änderung an einer anderen Klasse — außerhalb des in
  Abschnitt 0 erlaubten Scopes („Analyse der direkt beteiligten privaten
  Methoden" bezieht sich auf `EnhancedMetadataProcessor`, nicht auf
  Änderungen an fremden Kollaboratoren).
- **`filename_fixer`-Parameter-Muster** — funktional folgenlos, eine
  Änderung würde die öffentliche Signatur von `process_single_track()`
  anfassen (Abschnitt 16: „nicht ohne zwingenden Grund ändern").
- **Auto-Learn INV-01** (`services/metadata/auto_learn.py`, ungewrapptes
  synchrones Datei-I/O in `async def`-Methoden) — bereits in
  `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` dokumentiert, eigene
  künftige Entscheidung nötig, keine Umsetzung in diesem Task
  (Abschnitt 0: „Async-Architektur" ausdrücklich verboten).
- **`services/`-Architektur allgemein, Handler, Telegram-Schicht,
  Clients, Dependency-Injection-Architektur, Downloader-Retry-System,
  `duplicate/cache.py`, `MUSICBRAINZ_RETRIES`, Cancellation-Cleanup** —
  wie in Abschnitt 0 vorgegeben, nicht angefasst.

## Git Hygiene

- `git status`/`git diff --stat`: ausschließlich
  `services/metadata/enhanced_metadata_processor.py` (Produktionscode,
  46 Zeilen: 12 Insertions, 34 Deletions), 1 neue Testdatei, dieser
  Report.
- Keine Debug-Dateien, keine temporären Dateien, keine Testmanipulation,
  keine unbeabsichtigten Formatierungsänderungen, keine Änderungen an
  anderen Technical-Debt-Themen.
