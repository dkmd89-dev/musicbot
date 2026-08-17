# ARCH-001 — Große Orchestrator-Klassen

Dokumentation gemäß CLAUDE.md §19 ("Große Klassen"): vor jeder Aufteilung
zuerst Verantwortlichkeiten, öffentliche Schnittstellen und Aufrufer
dokumentieren. Dieses Dokument ist **reine Analyse** — keiner der vier
untersuchten Klassen wurde im Zuge dieser Untersuchung Code geändert.

Untersucht wurden die vier laut CLAUDE.md §19 explizit genannten
Risikobereiche:

| Klasse | Datei | Zeilen | Tests | Charakterisiert in |
|---|---|---|---|---|
| `DownloadHandler` | `klassen/download_handler.py` | 1251 | ja (indirekt, über SEC-004/REL-005/ARTIST-001-Tests) | diverse `tests/test_download_*.py` |
| `RichMenuHandler` | `handlers/menu/rich_menu_handler.py` | 1310 | ja, 28 Tests | `tests/test_rich_menu_handler.py` (BUG-006) |
| `RichMenuSystem` | `handlers/menu/rich_menu_system.py` | 1942 | ja, 29 Tests | `tests/test_rich_menu_system.py` (TEST-011) |
| `EnhancedMetadataProcessor` | `services/downloader/utils/enhanced_metadata_processor.py` | 1327 | ja, End-to-End | `tests/test_metadata_processor_happy_path.py` (E2E-001) |

Alle vier Klassen haben bereits Testabdeckung aus früheren Fixes/Sessions —
kein Fall von "Refactoring auf ungeschütztem Code" laut Regel 1.

---

## 1. `DownloadHandler`

### Verantwortlichkeiten
- **URL-Erkennung/Routing** — `_is_supported_download_url()`, `handle_url()`
- **Ressourcen-Limit/Concurrency** — modulweites `_download_semaphore` (Singleton, bewusst NICHT Instanzattribut, da pro Telegram-Update neu instanziiert)
- **YouTube-Pipeline** — `handle_youtube_links()`
- **Spotify-Pipeline** — `handle_spotify_url()` (inkl. Podcast-Spezialkanal-Routing)
- **Duplikat-Handling** — `_check_duplicates_before_download()`, `_handle_duplicate_found()`
- **Metadaten-Anreicherung** — `_process_single_download_result()` (7-stufig: Playlist-Wrapper-Schutz, Doppelverarbeitungs-Schutz, filepath-Fallback, Podcast-Episodennummer, playlist_metadata, Cover-Art, Delegation an `EnhancedMetadataProcessor`)
- **Genre/Stats-Aufbereitung** — zustandslose Helfer
- **Erfolgs-/Abschluss-Handling & Telegram-Antworten** — `handle_single_track_success()`, `handle_playlist_success()`, `_send_final_summary()` (~150 Zeilen), `handle_download_failure()`
- **Statusanzeige/Progress** — `_update_status()`

### Öffentliche Schnittstelle
`handle_url()` ist der einzige Haupteinstiegspunkt. `handle_youtube_links`, `handle_spotify_url`, `handle_single_track_success`, `handle_playlist_success`, `handle_download_failure` existieren als public Methoden, werden aber **nirgends von außen direkt aufgerufen** — nur intern voneinander bzw. von `handle_url()`.

### Aufrufer
Einziger produktiver Instanziierungspunkt: `handlers/menu/rich_menu_handler.py:837` (`_create_download_handler()`, pro Telegram-Update neu erzeugt, kein Singleton). Einzige extern aufgerufene öffentliche Methode: `handle_url()`, via `RichMenuHandler._process_url()` (`rich_menu_handler.py:1200/1210`). Zwei Legacy-Wrapper (`_initiate_download`, `_handle_regular_url`) sind reine Rückwärtskompatibilitäts-Aliase ohne eigene Logik.

### Bereits gefixte Bugs, strukturell verortet
- **SEC-004** (URL-Allowlist): `_is_supported_download_url()` + Gate in `handle_url()`
- **REL-005** (Ressourcen-Limits/Concurrency): `_get_download_semaphore()` als Modul-Singleton
- **REL-004** (Event-Loop-Blockierung): betrifft primär `download_utils.py`/`download_executor.py`, nicht direkt diese Klasse

### Extraktionskandidat
`_send_final_summary()` + `handle_playlist_success()` + `_build_duplicate_message()` + Genre/Stats-Helfer (~350 Zeilen, weitgehend zustandslos, kaum `self`-Zugriff außer `status_msg`/`update`/`duplicate_handler`) — Kandidat für eine eigene `DownloadResultReporter`-Klasse. Kernpipeline (`handle_url`/`handle_youtube_links`/`handle_spotify_url`/`_process_single_download_result`) bliebe unangetastet. **Status: umgesetzt (ARCH-001-STEP-2)**, mit einer bewussten Abweichung: `handle_playlist_success()`/`handle_single_track_success()` selbst bleiben in `DownloadHandler` (sie enthalten die Duplikat-Cache-Registrierung, ein echter Seiteneffekt, keine reine Formatierung), delegieren aber an `self.result_reporter` für alles Formatierungs-/Versand-bezogene. Siehe ARCH-001-STEP-2-Eintrag in der Baseline.

---

## 2. `RichMenuHandler`

### Verantwortlichkeiten
- **Composition Root** — `__init__`/`initialize()`/`_register_*_handlers()`/13+ `set_*()`-Setter: erzeugt und verdrahtet alle Sub-Handler
- **Telegram-Handler-Registrierung** — `get_telegram_handlers()`
- **Command-Einstiegspunkte** — `handle_start_command`, `handle_menu_command`, `handle_help`/`handle_help_callback`
- **Workflow-State-Machine** — `handle_text_message()`, `self.user_states`, `context.user_data["workflow"]`-Dispatch, zentrales `/cancel`-Handling (hier sitzt der BUG-006-Fix: Cancel-Check bewusst VOR Workflow-Dispatch)
- **Rollen-/Feature-Auflösung** — `_is_admin`, `_get_user_role`, `_get_available_features`, `_is_new_user`
- **Fachliche Callback-Wrapper** — dünne Adapter zwischen `RichMenuSystem`-Callbacks und Fach-Handlern

### Öffentliche Schnittstelle
23 public Methoden, davon 13 reine Setter (Dependency Injection). Zentrale Einstiegspunkte: `get_telegram_handlers()`, `handle_url_message()`, `handle_text_message()`.

### Verhältnis zu `RichMenuSystem`
Klare Trennung, aber enge Kopplung: `RichMenuSystem` besitzt Menübaum/Rendering/Sessions/generischen Callback-Dispatch. `RichMenuHandler` ist die Integrationsschicht — Commands, Text-/URL-Nachrichten, Workflow-Dispatch (alles was NICHT über das Callback-Menü läuft). Überlappung: Setter-Methoden sind fast 1:1-Duplikate; beide Klassen halten eigenen User-State (`RichMenuHandler.user_states` vs. `RichMenuSystem`-Sessions).

### Aufrufer
Einziger lebender Produktionspfad: `bot.py:108`. Zwei tote Nebenpfade gefunden: `handlers/command_integration.py` wird von `bot.py` nicht importiert (kein Aufrufer außer dem selbst kaputten `handlers/legacy_handler_integration.py`, das eine nicht existierende Klasse `CommandIntegration` importiert); `handlers/migration_system.py`/`scripts/migration_system.py` (inhaltsgleiche Duplikate) instanziieren `RichMenuHandler` nur in einer nirgends importierten Codegenerator-Funktion.

### Interner State
`self.user_states` (Download-URL-Erwartung) — **kein TTL/Cleanup-Mechanismus**, verwaist bei Prozessabbruch ohne expliziten Cancel. `context.user_data["workflow"]` (PTB-Bordmittel).

### Extraktionskandidaten
1. Workflow-Dispatch/State-Machine (hat mit BUG-006 bereits gezeigt, dass die Reihenfolge fehleranfällig ist). **Status: umgesetzt (ARCH-001-STEP-3)** — jetzt `handlers/menu/text_workflow_dispatcher.py` (`TextWorkflowDispatcher`), 17 eigene Unit-Tests in `tests/test_text_workflow_dispatcher.py`. Bewusst nicht mit extrahiert: `user_states` (URL-Erwartung) und Navidrome-Suchlogik. Siehe ARCH-001-STEP-3-Eintrag in der Baseline für die Design-Entscheidung zur `user_mgmt_handler`-Übergabe.
2. Rollen-/Feature-Resolver (zustandsarm, Telegram-unabhängig, geringes Risiko). **Status: noch nicht umgesetzt.**
3. (sekundär) Help-Text-Provider. **Status: noch nicht umgesetzt.**

---

## 3. `RichMenuSystem`

Größte Klasse im Projekt (1942 Zeilen).

### Verantwortlichkeiten
- **Menü-Strukturaufbau** — `initialize_menu_structure()` (~540 Zeilen, rein deklarativ)
- **Session-/State-Verwaltung** — `get_session()`, `cleanup_expired_sessions()`
- **Rendering** — `render_menu()`, `get_menu_text()`, `show_menu()`
- **Zugriffsebenen-Auflösung** — `_get_user_access_level()` (bekannter Bug: erkennt "OWNER" nicht, nur ADMIN/MODERATOR/USER — kosmetisch, siehe TEST-011) und `_is_admin_check()` (separate, einfachere Owner/Admin-Prüfung — **zwei parallele, leicht inkonsistente Autorisierungspfade**)
- **Zentrales Callback-Routing** — `handle_callback()` als Single Entry Point, Präfix-Dispatch an 8 Bereichs-Dispatcher (logger/navidrome/usermgmt/duplicate/erradmin/status/backup/restart)
- **Handler-Wrapper/Adapterschicht** — ~30 `_handle_*`-Methoden

### Öffentliche Schnittstelle
`handle_callback()` ist der zentrale Einstiegspunkt. Daneben: 10 Setter, `initialize_menu_structure()`, `get_session()`, `render_menu()`, `get_menu_text()`, `show_menu()`, `register_handler()`, `cleanup_expired_sessions()`.

### Routing-Mechanismus
Zweistufig: Präfix-basiertes Top-Level-Routing (`startswith`-Kette) inkl. zentraler Admin-Gate-Prüfung über `_ADMIN_ONLY_PREFIXES` (SEC-003-Nachtrag), dann pro Bereich entweder dict-`routing_map` oder weitere String-Präfix-Ketten für parametrisierte Callbacks. **Dieses Muster wiederholt sich achtmal nahezu identisch** — Kandidat für eine generische `CallbackRouter`-Komponente.

### Ist sie reiner Dispatcher?
Überwiegend ja — instanziiert selbst keine Handler, hält nur injizierte Referenzen. Eigene fachliche Logik an drei Stellen: (a) die Menü-Baum-Definition, (b) Zugriffsebenen-Auflösung, (c) einige inline "wird gerade entwickelt"-Platzhalter direkt in den Dispatchern statt Delegation an einen Handler.

### Aufrufer
Nur `RichMenuHandler` (`rich_menu_handler.py:84`) instanziiert sie produktiv. Ein toter/vorbereitender Import in `handlers/admin/user_management_handler.py:168` (Import wird im gezeigten Codepfad nicht genutzt). Kapselungsbruch gefunden: `rich_menu_handler.py:382-385` greift direkt auf `menu_registry` (eigentlich intern) zu, um ein MenuItem dynamisch anzuhängen.

### Extraktionskandidaten
1. Die acht `_handle_*_callback`-Dispatcher als eigene, kleine Router-Klassen pro Bereich (z.B. `LoggerCallbackRouter`) — `handle_callback()` würde dann nur noch Präfix→Router-Objekt mappen
2. Menü-Baum-Definition als separate Factory/Builder-Funktion (rein deklarativ, keine Laufzeit-Abhängigkeiten zu den übrigen Verantwortlichkeiten)

**Status: noch nicht umgesetzt.**

---

## 4. `EnhancedMetadataProcessor`

Die P0-Metadaten-Pipeline (Track → Cache → Parsing → Artist → Title → Genre → Lyrics → MusicBrainz → Cover → Album/Jahr → Audio → Tags), gespiegelt in nummerierten Kommentarblöcken innerhalb von `process_single_track()`.

### Verantwortlichkeiten (Pipeline-Stufen)
Init/Wiring → Cache-Check → Rohdaten-Extraktion → YouTube-Titel-Parsing → Spezialkanal-Erkennung → Artist-Bestimmung (delegiert an `ArtistProcessor`, siehe ARTIST-001-Fix) → Titel-Bereinigung (`TitleCleaner`) → In-Memory-Duplikaterkennung → Genre-Bestimmung (`GenreProcessor`) → Lyrics (`LyricsProcessor`) → MusicBrainz-Prefetch → Cover-Art (`CoverProcessor`) → Album/Jahr/Tracknummer (`AlbumProcessor`) → Dateisystem-Validierung → Spezialkanal-Postprocessing → Audio-Loudness (`AudioEnhancer`) → Datei verschieben (`filename_fixer.move_to_library`) → **Tag-Schreiben (eigene, nicht ausgelagerte Mutagen-Logik)** → Ergebnis/Cache-Write/Auto-Learning.

### Öffentliche Schnittstelle
`process_single_track()` ist der zentrale Einstiegspunkt (gibt `MetadataResult` zurück). Daneben: `get_processing_statistics()`, `reset_statistics()`, `cleanup()`, `invalidate_cache_entry()`. Zusätzlich ein Block "Delegate-Methoden für Abwärtskompatibilität" (~120 Zeilen, reine 1:1-Weiterleitungen an Sub-Prozessoren) — vermutlich Altlast einer früheren, monolithischeren Version.

### Ist sie reiner Orchestrator?
Überwiegend ja — die fachliche Kernlogik ist bereits in Sub-Prozessoren ausgelagert (`ArtistNormalizer`/`ArtistProcessor`, `GenreMapper`/`GenreProcessor`, `GeniusClient`/`LyricsProcessor`, `CoverProcessor`, `AlbumProcessor`, `AutoLearnManager`, lazy: `MusicBrainzClient`/`LastFMClient`). Nicht delegierte Eigenlogik verbleibt bei: Podcast-/Spezialkanal-Fallunterscheidungen, Feature-Artist-Merging, MB-ID-Übernahme, Single-Album-Templating, und komplett eigenständig das **Tag-Schreiben** (`_write_metadata_to_file_with_lyrics`, `_write_genres_m4a`, `_write_genres_mp3`, ~180 Zeilen).

### Aufrufer
Da `SingletonMixin`: `download_utils.py`, `rich_menu_handler.py:298` und `services/downloader/utils/metadata_utils.py:27` referenzieren de facto dieselbe Instanz. `process_single_track()` wird aufgerufen von `klassen/download_handler.py:515` sowie zweimal in `download_utils.py` (Playlist- und Single-Kontext). **Kapselungsverletzungen gefunden**: `download_utils.py:739/934` ruft `auto_learn_manager.learn_artist()` direkt auf einem internen Sub-Prozessor auf (unter Umgehung der öffentlichen API); `bot.py:287-296` greift für den async-Cleanup direkt auf `.genius_client` durch statt über `cleanup()`.

`services/downloader/utils/metadata_utils.py` ist die Datei mit den seit dem Initial-Commit kaputten Imports (siehe LEGACY-002-Eintrag in der Baseline) — sie enthält eine separate Klasse `MetadataProcessor`, die intern ebenfalls `EnhancedMetadataProcessor` instanziiert, aber selbst nirgends importiert wird (toter Wrapper um eine lebende Klasse).

### Cache-Interaktion
Vollständig delegiert an `MetadataCacheHandler`. Hit-Check primär über stabile YouTube-Video-ID (nicht Artist/Titel, siehe TEST-003-Begründung), beendet Pipeline bei Treffer frühzeitig. Miss zählt Statistik und durchläuft volle Pipeline. Write nach vollständiger Verarbeitung inkl. `cover_source`.

### Extraktionskandidaten
1. **Tag-Schreiben** (`_write_metadata_to_file_with_lyrics`, `_write_genres_m4a`, `_write_genres_mp3`, `_extract_genre_parts`, ~180 Zeilen) — einzige, wohldefinierte Aufgabe, kein `self`-Zugriff außer Logger, folgt exakt dem Muster der übrigen Sub-Prozessoren (`TagWriter`-Klasse analog zu `AlbumProcessor`/`CoverProcessor`). **Status: umgesetzt (ARCH-001-STEP-1)** — jetzt `services/downloader/utils/metadata/tag_writer.py`, verdrahtet als `self.tag_writer` in `EnhancedMetadataProcessor._do_init()`, 21 eigene Unit-Tests in `tests/test_tag_writer.py`.
2. Der "Delegate-Methoden"-Block — reine Weiterleitungen, vermutlich ersatzlos entfernbar, sobald geklärt ist, dass sie nirgends (auch nicht in Tests) mehr direkt aufgerufen werden (eigene kleine Nachfolge-Untersuchung, nicht Teil dieser Analyse). **Status: noch nicht umgesetzt.**

---

## Übergreifende Beobachtungen

- **Kein Fall rechtfertigt einen sofortigen Refactor.** Alle vier Klassen sind bereits getestet (Regel 1: "Kein größerer Refactor ohne Sicherheitsnetz" ist erfüllt), aber keine akute Notwendigkeit (Bug/Sicherheitsproblem) treibt eine Aufteilung — reine Struktur-Verbesserung wäre laut CLAUDE.md §18/§21 (Regel 1) kein ausreichender Grund für sich allein.
- **Wiederkehrendes Muster:** Alle vier Klassen sind im Kern Orchestratoren, die fachliche Arbeit an Sub-Komponenten delegieren — die extrahierbaren Reste sind fast immer entweder (a) Telegram-Antwort-/Formatierungscode oder (b) ein sich wiederholendes Dispatch-/Routing-Muster.
- **Nebenbefunde:**
  - **Inzwischen behoben (LEGACY-005):** `handlers/command_integration.py`, `handlers/legacy_handler_integration.py` (syntaktisch ungültiges Python, importierte zudem eine nie existierende `handlers/statistik_handler.py`), `handlers/migration_system.py`/`scripts/migration_system.py` (identische tote Duplikate), `services/downloader/utils/metadata_utils.py`, `utils/.artist_if.py` sowie der dadurch verwaiste `RichMenuSystem`/`MenuState`-Import in `handlers/admin/user_management_handler.py:168` — alle 6 Dateien gelöscht, siehe LEGACY-005-Eintrag in der Baseline.
  - **Weiterhin offen, für spätere Sessions vorgemerkt** (Kapselungsverletzungen, keine toten Dateien): `rich_menu_handler.py:382-385` durchbricht die Kapselung von `RichMenuSystem.menu_registry`; `download_utils.py:739/934` und `bot.py:287-296` durchbrechen die Kapselung von `EnhancedMetadataProcessor`s internen Sub-Prozessoren.

## Nächste Schritte (nicht Teil dieser Analyse, zur Entscheidung)

Diese Dokumentation erfüllt CLAUDE.md §19 Schritte 1–3 (Verantwortlichkeiten, Schnittstellen, Aufrufer). Schritt 4 (Tests) ist für alle vier Klassen bereits erfüllt. Schritt 5 (kleinster sinnvoller Extraktionsschritt) ist explizit **nicht** Teil dieses Dokuments — jede der oben genannten Extraktionen wäre ein eigener, einzeln zu genehmigender Schritt mit eigenem Vorher/Nachher-Test.
