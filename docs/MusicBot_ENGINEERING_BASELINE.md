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
| SEC-003 | **Kritisch — Privilege Escalation.** `RichMenuSystem.handle_callback()` (`handlers/menu/rich_menu_system.py`) dispatchte `callback_data` rein nach String-Präfix (`usermgmt_`, `backup_`, `logger_`, `dup:`) an die jeweiligen Handler — ohne jede Berechtigungsprüfung. Telegram-`callback_data` ist ein von jedem Client frei sendbarer String, nicht an tatsächlich gerenderte Buttons gebunden (`is_accessible()` in `render_menu()` blendet Buttons nur clientseitig aus, autorisiert nichts). `UserManagementHandler.set_user_role()` hatte selbst ebenfalls keinerlei Admin-Check. **Jeder Nutzer, der den Bot anschreiben konnte, konnte sich per `usermgmt_set_role_<eigene_id>_owner` selbst zum Owner machen**, Backups löschen, das globale Log-Level ändern (hebelt den SEC-001-Schutz aus) oder den Duplicate-Cache leeren. Zusätzlich: `EnhancedLoggerMenuHandler.show_log_file_detail()` baute `file_path = log_dir / filename` aus unvalidiertem `callback_data`-Inhalt — Path Traversal/beliebiger Datei-Lesezugriff, kombiniert mit der fehlenden Admin-Prüfung ohne jede Berechtigung erreichbar | P0 | **behoben** (Phase 3, sofort) — zentrale Admin-Prüfung in `handle_callback()` vor dem Präfix-Dispatch ergänzt (`erradmin:`/`restart:` hatten bereits korrekte eigene Checks, als Vorbild genutzt). Nachträglich um `status_` erweitert (`show_storage_status()` etc. geben reale Server-Dateisystempfade preis und bieten eine destruktive Cleanup-Aktion) — `nav_` bleibt bewusst öffentlich (reines Bibliotheks-Browsing/Suche, keine destruktiven Aktionen, keine Pfad-Offenlegung). Path-Traversal-Fix im Log-Viewer via `.resolve()` + `is_relative_to()`-Containment-Check. 20 Tests in `tests/test_rich_menu_access_control.py` (inkl. direktem Beweis, dass der Self-Promotion-Angriff am unfixierten Code tatsächlich gelingt) + 4 in `tests/test_logger_menu_path_traversal.py`, alle relevanten Fälle am unfixierten Code als fehlschlagend verifiziert |
| REL-001 | `NavidromeAPI.make_request()` (`api/navidrome_api.py`) rief `requests.get()` ohne `timeout` auf. Ein nicht abgestürzter, aber langsam/nicht antwortender Navidrome-Server hätte den Aufruf unbegrenzt blockiert — da `make_request` über `asyncio.to_thread` mit dem geteilten Default-Executor läuft (`check_connection`, `get_scan_status`, `get_full_server_info` u.a.), hätte das bei wiederholten Aufrufen den gesamten Thread-Pool erschöpfen und damit den ganzen Bot lahmlegen können, nicht nur die Navidrome-Funktionen | P1 | **behoben** (Phase 3) — `timeout=Config.NAVIDROME_REQUEST_TIMEOUT` (Default 15s, neue Config-Konstante) ergänzt. 3 Tests in `tests/test_navidrome_api_timeout.py` (Timeout wird übergeben, konfigurierbar, `requests.exceptions.Timeout` wird weiterhin korrekt propagiert statt verschluckt) |
| REL-002 | `GeniusClient._fetch_lyrics()` (`klassen/genius_client.py`) hatte Tier 2 (Genius-REST-API) und Tiers 3+4 (HTML-Scraping, lyricsgenius-Bibliothek) in EINEM gemeinsamen try-Block. Scheiterte Tier 2 (kein `GENIUS_ACCESS_TOKEN` konfiguriert → `self.genius_api is None` → `AttributeError`; Netzwerkfehler; kein Suchtreffer — dort sogar mit explizitem frühem `return {}`), brach die gesamte Methode sofort ab, obwohl Tier 3/4 als unabhängige Fallbacks gedacht sind. Zusätzlich las Tier 4 (`_fallback_with_lyricsgenius`) `Config.GENIUS_CONFIG["access_token"]`, einen Key, der in `GENIUS_CONFIG` gar nicht existiert — jeder Aufruf löste einen lokal verschluckten `KeyError` aus, Tier 4 war dadurch unabhängig von jeder Token-Konfiguration IMMER tot | P1 | **behoben** (Phase 3) — Tier 2 in eigene Methode `_fetch_via_genius_api()` mit eigenem try/except extrahiert, die bei jedem Fehlschlag `("", "", {})` zurückgibt statt zu propagieren/früh zurückzukehren. Tier 4 nutzt jetzt `self.genius_access_token` (= `Config.GENIUS_ACCESS_TOKEN`, derselbe Token wie Tier 2) statt des nicht existierenden Config-Keys. 6 Tests in `tests/test_genius_client_fallback_chain.py`, 5/6 am unfixierten Code als fehlschlagend verifiziert (1 Test ist auf beiden Ständen richtig grün, da er einen bereits korrekten Nebeneffekt des alten KeyError-Pfads dokumentiert) |
| REL-003 | `CoverProcessor._validate_and_score()` (`services/downloader/utils/metadata/cover_processor.py`): `_analyze_image_quality()` fängt PIL-Parse-Fehler ab und liefert dann `width=0, height=0` zurück. Die alte Bedingung `if w > 0 and (w < 100 or h < 100)` übersprang den Auflösungs-Check komplett, wenn `w == 0` war — ein Nicht-Bild-Blob (z.B. eine mit HTTP 200 zurückgegebene HTML-Fehlerseite), der nur die Mindestgröße (`_MIN_IMAGE_BYTES` = 5000 Bytes) erfüllte, rutschte dadurch durch und hätte als Cover-Art in eine Audiodatei eingebettet werden können — empirisch reproduziert (`CoverCandidate` mit `total_score=50` für eine HTML-Fehlerseite am unfixierten Code) | P2 | **behoben** (Phase 3) — expliziter Check `if w <= 0 or h <= 0: ignorieren`, bevor die Auflösungsprüfung erfolgt. 4 Tests in `tests/test_cover_processor_validation.py`, 2/4 am unfixierten Code als fehlschlagend verifiziert (echte, valide Bilder bleiben unverändert akzeptiert/abgelehnt) |
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
| ARTIST-001 | `ArtistNormalizer.normalize()` (`utils/artist_map.py`) wurde in `ArtistProcessor.determine_best_artist` auf unaufgeteilte Collaboration-Strings angewendet (statt vorher `split_main_and_featuring` anzuwenden). Bei gemischten Trennzeichen (z.B. `"GReeeN & 1986zig feat. Bausa"`) wurden alle Teile zu gleichrangigen Peers reduziert — der eigentliche Haupt-Artist-Anteil (`"1986zig"`) wurde fälschlich zum Feature degradiert | P1 | **behoben** — `determine_best_artist()` trennt Haupt-/Feature-Artist jetzt VOR dem `normalize()`-Aufruf (`split_main_and_featuring` in der internen `_clean_and_normalize`-Closure), normalisiert nur den Hauptteil, und gibt die Feature-Liste als drittes Rückgabeelement zurück (`Tuple[str, str, List[str]]`, vorher `Tuple[str, str]`). Der redundante zweite Split in `enhanced_metadata_processor.py:401` (der die bereits normalisierte, abgeflachte Ausgabe erneut zerlegte — genau das war der Kern von ARTIST-001-DEEP) wurde entfernt; die Feature-Liste kommt jetzt direkt aus `determine_best_artist()`. Verifizierter Blast-Radius: `determine_best_artist` hatte nur einen einzigen echten Aufrufer (`enhanced_metadata_processor.py:382`); die 13+ anderen `.normalize()`-Aufrufer im Repo sind unabhängig und unberührt. `ArtistNormalizer.normalize()`/`_normalize_collaboration()` selbst bewusst nicht verändert — Verlust stilisierter Schreibweisen (`"GReeeN"` → `"Green"`) bleibt bestehendes, hier nicht behobenes Verhalten, weiterhin charakterisiert in `tests/test_artist_normalizer.py::TestCollaborationArchitectureCharacterization`. 2 neue Regressionstests in `tests/test_metadata_modules.py` (Einzel-Feature-Fall und der ursprüngliche gemischte-Trennzeichen-Bug-Fall) |
| GENRE-002 | `GenreMapper._compile_rules`/`_apply_rules` (`utils/genre_map.py`) erwartet einen Top-Level-Key `GENRE_RULES` in `mapping/genre_rules.yaml`, die echte Datei hat aber `keyword_rules`/`artist_rules`/`title_rules` — Schema-Mismatch. `self.rules` ist mit der echten Datei immer leer, die komplette Regex-Regel-Funktion für Genre-Erkennung ist seit jeher wirkungslos | P1 | **entschieden, kein Loader-Fix** — Inhaltsabgleich (nicht nur Schema-Vergleich) zeigt: `keyword_rules` ist 1:1 redundant mit dem bereits aktiven `genre_aliases.yaml` (dieselben Begriffe — "deutschpop", "schlager", "german rap" etc. — laufen bereits über `normalize_genre_name()`, Schritt 5 der Pipeline). `artist_rules` ist redundant mit dem bereits aktiven `artist_genre.yaml` (Schritt 1–2, höhere Priorität als der tote Regel-Schritt) — "Helene Fischer" stand dort bereits, nur "Mark Forster"/"Cro"/"Florian Künstler" fehlten tatsächlich und wurden nach `artist_genre.yaml` migriert (nutzt den bestehenden, bewährten Mechanismus statt einer zweiten parallelen Artist-Regel-Engine, siehe Regel 27). `title_rules` (Genre aus Titel-Keywords wie "party"/"liebe"/"herz" raten) ist die einzige nicht-redundante, aber bewusst NICHT aktivierte Regel — reines Einzelwort-Substring-Matching ohne weitere Absicherung wäre fehleranfällig (z.B. ein Deutschrap-Track mit "Herz" im Titel würde fälschlich "Pop"). Der tote Regex-Regel-Schritt (Schritt 4 in `determine_genre`) bleibt unverändert bestehen, wird aber realistisch nie mehr befüllt. 3 neue Tests in `tests/test_genre_mapper_advanced.py::TestGenreRulesArtistMigration`, alle 3 Migrations-Charakterisierungstests in `TestRegexRulesSchemaMismatch` unverändert grün |
| GENRE-003 | `GenreMapper.get_main_genre()` (`utils/genre_map.py`) lowercased den Such-Key, aber `self.hierarchy`-Keys wurden aus `genre_hierarchy.yaml` unverändert (Title-Case) geladen → der Hierarchie-Fallback (`source="hierarchy"`) griff mit den echten Mapping-Daten praktisch nie, alles landete bei `source="normalized"` | P1 | **behoben** (Phase 2, Fortsetzung) — Hierarchie-Keys werden beim Laden jetzt lowercased (analog zu artist_map/channel_map). Dabei einen zweiten, durch den Case-Fix erst sichtbar gewordenen Bug mitgefixt: Top-Level-Genres liegen im Hierarchie-Dict als Key mit Wert `None` vor (kein Parent) — `.get(key, sub_genre)` hätte dafür faelschlich `None` statt des Fallbacks zurückgegeben; jetzt `.get(key) or sub_genre`. 4 Tests in `tests/test_genre_mapper_advanced.py::TestHierarchyCaseFix`, am unfixierten Code als fehlschlagend verifiziert |
| ARTIST-001-DEEP | Vertiefte Analyse zeigte: ein enger Fix nur in `ArtistProcessor._clean_and_normalize` reicht für ARTIST-001 NICHT aus, weil `enhanced_metadata_processor.py:401` das Ergebnis von `determine_best_artist` ein zweites Mal via `split_main_and_featuring()` splittete — diese zweite Stelle konnte einen bereits korrekt behandelten zusammengesetzten Haupt-Artist nicht von echten Features unterscheiden | P1 | **behoben** — als Teil des ARTIST-001-Fixes: die Schnittstellenänderung (`determine_best_artist` gibt Haupt-/Feature-Artist jetzt getrennt zurück) wurde umgesetzt und der redundante zweite Split entfernt, statt eines Nebenbei-Fixes. Verifizierter, tatsächlich kleiner Blast-Radius (ein einziger echter Aufrufer) machte die zunächst befürchtete große Änderung überschaubar |
| REL-004 | `enhanced_download_with_retry()`/`_process_single_download()` (`services/downloader/utils/download_utils.py`) und `download_single_track()` (`services/downloader/download/download_executor.py`) — alle `async def` — riefen die synchrone, blockierende yt-dlp-Methode `extract_info()`/`ydl.extract_info()` direkt auf, ohne `run_in_executor`. Während jedes einzelnen Downloads fror dadurch der komplette asyncio-Event-Loop ein — der Bot wurde für ALLE Telegram-Nutzer unresponsive, nicht nur für den gerade downloadenden. `spotify_downloader.py` löste dasselbe Problem an vergleichbaren Stellen bereits korrekt über `loop.run_in_executor` | P0 | **behoben** — neue `DownloadExecutor.extract_info_async()` wrapt die bestehende synchrone `extract_info()` via `asyncio.get_running_loop().run_in_executor(None, ...)`; alle drei blockierenden Call-Sites umgestellt (zwei direkte Aufrufe von `extract_info_async`, `download_single_track` über eine lokale Closure). Kein Verhaltensunterschied im Ergebnis (gleiche yt-dlp-Aufrufe/Exceptions/Rückgabewerte), nur die Event-Loop-Blockierung entfällt. 2 Tests in `tests/test_download_executor.py::TestExtractInfoAsyncDoesNotBlockEventLoop`, u.a. direkter Beweis via parallel laufender Coroutine, dass der Event-Loop während des Aufrufs weiterläuft |
| SEC-004 | `DownloadHandler.handle_url()` (`klassen/download_handler.py`) prüfte nur auf Spotify-URLs (`_is_spotify_url`); jede andere `http(s)://`-URL wurde ungeprüft an yt-dlp durchgereicht. yt-dlp unterstützt hunderte Extractors und macht serverseitige HTTP-Requests — ohne Domain-Allowlist konnte jeder Telegram-Nutzer, der den Bot anschreiben kann, den Server beliebige URLs abrufen lassen (SSRF-artiges Risiko, u.a. gegen interne Adressen/Cloud-Metadata-Endpunkte wie `169.254.169.254`) | P0 | **behoben** — neue `_is_supported_download_url()` prüft explizit auf unterstützte YouTube-Domains (`youtube.com`, `youtu.be`, `music.youtube.com`) über `urlparse().netloc` (nicht String-Substring-Suche, dadurch robust gegen Domain-Confusion wie `youtube.com.evil.com` oder `notyoutube.com`). `handle_url()` weist nicht unterstützte URLs jetzt mit einer normalen Telegram-Fehlermeldung ab, statt sie stillschweigend an yt-dlp weiterzureichen. 10 Tests in `tests/test_download_url_validation.py`, inkl. dedizierter Domain-Confusion-Testklasse |
| REL-005 | Drei in `config.py` definierte Ressourcen-Limits wurden in der Download-Pipeline nirgends durchgesetzt: `MAX_PLAYLIST_ITEMS` (Playlists mit tausenden Einträgen liefen unbegrenzt durch — unbegrenzter Speicher-/Bandbreiten-/Zeitverbrauch pro Anfrage), `MAX_CONCURRENT_DOWNLOADS` (keine Begrenzung gleichzeitiger Downloads über alle Chats/Nutzer hinweg) und `MAX_DURATION` (wurde nur in der toten `Config.YTDL_BASE_OPTIONS`-Property unter dem Key `"max_duration"` gesetzt — kein echter yt-dlp-Options-Key, wird von yt-dlp stillschweigend ignoriert; `build_ydl_opts()`, die tatsächlich genutzte Methode, kannte `MAX_DURATION` gar nicht) | P1 | **behoben** — `_process_playlist_download()` kürzt `entries` jetzt direkt nach dem Laden auf `MAX_PLAYLIST_ITEMS`. `_get_download_semaphore()` in `download_handler.py` ist ein Modul-weiter `asyncio.Semaphore`-Singleton (bewusst NICHT Instanzattribut, da `DownloadHandler` pro Telegram-Update neu instanziiert wird — siehe `RichMenuHandler._create_download_handler`), um `handle_url()` gelegt. `DownloadExecutor._build_duration_match_filter()` implementiert `MAX_DURATION` als echten yt-dlp-`match_filter`-Callback, mit expliziter Ausnahme für als Podcast erkannte Kanäle (`utils/filenamefixer.py`'s `load_special_channels_merged`/`get_special_channel_info`), da Podcast-Episoden legitim deutlich länger als das Musik-Limit sind. 3 Tests in `tests/test_playlist_max_items.py`, 5 in `tests/test_download_concurrency_semaphore.py` (inkl. echtem Beweis der Nebenläufigkeitsbegrenzung via `asyncio.gather`), 5 in `tests/test_download_executor.py::TestDurationMatchFilter` — alle relevanten Fälle am unfixierten Code als fehlschlagend verifiziert |
| TEST-005 | `api/navidrome_api.py` (`NavidromeAPI`) hatte außer SEC-001 (Credential-Masking) und REL-001 (Timeout) keinerlei Testabdeckung für die eigentliche Geschäftslogik, trotz P1-Status ("externe Adapter", Navidrome) | P1 | **behoben** — 18 Characterization-Tests in `tests/test_navidrome_api_characterization.py` für alle produktiv genutzten Methoden (`check_connection`, `get_scan_status`, `get_full_server_info`, `get_artists`, `get_now_playing`, `search`, `execute_scan`), inkl. Subsonic-API-Eigenheit (Einzel-Objekt statt Liste bei genau einem `nowPlaying`-Eintrag) und einer dokumentierten Inkonsistenz: `check_connection()`/`get_scan_status()`/`get_full_server_info()` fangen Exceptions aus `make_request()` ab und liefern sichere Defaults, während `get_artists()`/`search()`/`get_now_playing()` Exceptions unverändert propagieren lassen — in Produktion unauffällig, da alle drei echten Aufrufer (`navidrome_menu_handler.py`, `statistik_service.py`) selbst try/except um den Aufruf legen; bewusst nicht als Bug behandelt, da keine reale Absturzstelle gefunden wurde |
| TEST-006 | `klassen/musicbrainz_client.py` (`MusicBrainzClient`) — explizit Teil des P0-Metadata-Flows ("MusicBrainz") — hatte 426 Zeilen und 0 Tests | P0 | **behoben** — 25 Characterization-Tests in `tests/test_musicbrainz_client.py` für `parse_search_terms()`, `fetch_metadata()` (kompletter 3-stufiger Fallback: kombinierte Suche → Titel-only → Release-Suche), `_get_best_match()` (Scoring/Schwelle), `_build_metadata()` (ID-/ISRC-/Genre-Extraktion) und `cached_musicbrainz_search()` (Cache-Hit/-Miss, `NetworkError`/generische Exceptions). GenreMapper/ArtistNormalizer werden dabei bewusst gemockt statt real instanziiert — `MusicBrainzClient.__init__()` fällt ohne `get_artist_normalizer()`-Singleton auf eine eigene Instanz mit dem ECHTEN `Config.LIBRARY_DIR`/`ARTIST_OVERRIDE_FILE` zurück, exakt das Szenario, das in `tests/test_artist_normalizer.py` bereits einmal zu einem versehentlichen Schreibzugriff auf die reale `mapping/case_preserve.yaml` geführt hat |
| BUG-001 | `MusicBrainzClient._build_metadata()` setzte `"track_number"` auf `first_release.get("medium-track-count")`. Laut musicbrainzngs-Quellcode (`mbxml.py`) ist das die GESAMTANZAHL der Tracks auf dem Medium (`ws2:track-count`), nicht die Position des gefundenen Recordings — jeder Track desselben Albums hätte denselben falschen Wert bekommen (z.B. immer „17“ bei einem 17-Track-Album) | P1 | **behoben** — live gegen die echte musicbrainz.org-API verifiziert (`search_recordings` für "Bohemian Rhapsody"/Queen liefert `release-list[0]["medium-list"][0]["track-list"][0]["number"] == "8"`, während `medium-track-count == 17` war). Neue `_extract_track_number()`: liest zuerst `match["_source_track_number"]` (Release-Fallback-Pfad, aus dem echten Track-Objekt in `_extract_recordings_from_releases()` mitgeführt), sonst die echte Position aus `release_list → medium-list → track-list → number/position`. 3 Regressionstests in `tests/test_musicbrainz_client.py::TestBuildMetadataFieldExtraction`, am unfixierten Code als fehlschlagend verifiziert. War zuvor folgenlos (kein Aufrufer las das Feld), ist aber jetzt korrekt für den Fall, dass ein künftiger Aufrufer es nutzt |
| BUG-002 | Bei der Untersuchung von BUG-001 gefunden: `_build_metadata()` überschrieb `release_list` (und damit `release_group`) immer mit der Antwort der zweiten `get_recording_by_id()`-Abfrage. Diese unterstützt für die Entity `"recording"` aber KEINEN `"release-groups"`-Include (bestätigt über `musicbrainzngs.VALID_INCLUDES["recording"]` — der Include-Token existiert dort schlicht nicht), ihr `release-list` enthält daher NIE `release-group`-Daten. Der ursprüngliche Suchtreffer (`match`, aus `search_recordings()`) hatte diese Daten (Titel, Tags) bereits vorliegen, wurde aber verworfen — live verifiziert an "Bohemian Rhapsody": Such-Ergebnis enthält `release-group` vollständig (inkl. Tags), die Detail-Antwort hat den Key gar nicht. Effekt: `mb_tags` war dadurch in der Praxis IMMER leer → der komplette „MusicBrainz-Tags → Genre“-Fallback-Pfad war faktisch tot, und `"album"` nutzte nie den (oft korrekteren) Release-Group-Titel | P1 | **behoben** — `release_list` bevorzugt jetzt `match.get("release-list")` (reichhaltiger, aus dem Suchtreffer) vor `recording_info.get("release-list")` (aus der Detail-Abfrage). 1 Regressionstest (`test_release_group_tags_survive_the_detail_lookup`), am unfixierten Code als fehlschlagend verifiziert (`album` liefert vorher `"Release Title"` statt `"Release Group Title"`) |
| LEGACY-003 | `NavidromeAPI` enthält 8 Methoden ohne jeden Aufrufer im Repo (`count_songs_recursive`, `get_last_played`, `get_top_songs`, `get_top_artists`, `get_period_review_data`, `get_album_list`, `get_indexes`, `get_genres`) — vermutlich Reste einer älteren Statistik-/Browsing-Oberfläche, die zwischenzeitlich durch direkte `make_request()`-Aufrufe in den Handlern ersetzt wurde (Kommentar in `navidrome_menu_handler.py:315`: "KORRIGIERT: Direkte API-Anfrage statt get_genres()") | P2 | dokumentiert, nicht entfernt (Regel: Legacy-Code nicht ohne Beweis löschen) — keine Tests, da toter Code |
| DATA-001 | Beim Migrieren der GENRE-002-Artist-Einträge gefunden: `mapping/artist_genre.yaml` hatte 12 doppelte Top-Level-Keys (`dominic fike`, `eminem`, `herzchen`, `majan`, `dasha`, `sarah engels`, `taylor swift`, `calvin harris`, `riton`, `one-t`, `fayan`, `"The Weeknd"`) — u.a. ein zusammenhängender 9-Einträge-Block (Zeilen 691–734), der wie ein versehentlich doppelt eingefügter Batch aussah. PyYAML behält beim Laden nur den JEWEILS LETZTEN Wert pro Key — die erste Definition wurde still verworfen, ohne Fehler oder Warnung | P1 | **behoben** — Zeile für Zeile geprüft: in allen 12 Fällen war `primary` identisch (kein Klassifizierungs-Widerspruch), meist auch `secondary` identisch; unterschied sich nur die `description` (immer eine der beiden Versionen gekürzt) bzw. bei "calvin harris" `secondary` (eine Version fehlte „Progressive House"). `description` wird laut `utils/genre_map.py` nirgends in der Matching-Logik gelesen, ist reine Dokumentation (`GenreMapping.to_dict()`) — Risiko der Bereinigung daher minimal. Jeweils die vollständigere Version behalten, die gekürzte entfernt. 2 neue Guard-Rail-Tests in `tests/test_mapping_yaml_integrity.py` (custom PyYAML-Loader, der doppelte Keys aktiv erkennt statt sie stillschweigend zu überschreiben), verhindert ein unbemerktes Wiederauftreten |
| DATA-002 | Beim Bau des generischen Duplicate-Key-Checks für DATA-001 zusätzlich gefunden: `mapping/genre_hierarchy.yaml` (1 doppelter Key: `Metal`), `mapping/genre_overrides.yaml` (8 doppelte Keys: `hiphop`, `hip hop`, `edm`, `tech house`, `progressive house`, `hardstyle`, `electro house`, `electropop`) und `mapping/genre_aliases.yaml` (13 doppelte Keys, u.a. `ruhrpott rap`, `techno`, `house`) haben ebenfalls doppelte Keys — dieselbe stille PyYAML-Überschreib-Falle wie DATA-001 | P1 | **offen, bewusst nicht Teil dieser Änderung** — andere Semantik pro Datei (Overrides/Aliases sind reine String→String-Ersetzungen ohne „description"-Feld, ein Konflikt zwischen zwei Werten für denselben Key wäre hier nicht automatisch harmlos wie bei DATA-001) und deutlich zentraler in der Genre-Pipeline (Schritt 1 bzw. früher als Artist-Mapping). Braucht dieselbe Zeile-für-Zeile-Prüfung wie DATA-001, aber als eigener, bewusster Schritt statt Scope-Creep innerhalb der DATA-001-Freigabe |
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
- [x] GENRE-002 entschieden — keyword_rules/artist_rules als redundant zu genre_aliases.yaml/artist_genre.yaml identifiziert, 3 fehlende Artists migriert, title_rules bewusst nicht aktiviert (siehe Risikotabelle). Dabei DATA-001 gefunden (12 doppelte Keys in artist_genre.yaml) — offen, eigener Punkt
- [x] ARTIST-001 behoben — Schnittstellenänderung umgesetzt (`determine_best_artist` gibt Haupt-/Feature-Artist getrennt zurück), verifizierter Blast-Radius war ein einziger echter Aufrufer
- [x] TEST-003 behoben — Video-ID-Index als stabiler Zwischenschlüssel zwischen Check (roh) und Store (bereinigt), siehe Risikotabelle

### Phase 3 — Download-Pipeline (Event-Loop, URL-Allowlist, Ressourcen-Limits)
- [x] REL-004 behoben — Event-Loop-Blockierung durch synchrone `extract_info()`-Aufrufe in `async def`-Funktionen, neue `extract_info_async()` via `run_in_executor`
- [x] SEC-004 behoben — Domain-Allowlist (`_is_supported_download_url()`) vor yt-dlp-Weiterleitung, schützt gegen SSRF-artiges Risiko und Domain-Confusion
- [x] REL-005 behoben — `MAX_PLAYLIST_ITEMS`/`MAX_CONCURRENT_DOWNLOADS`/`MAX_DURATION` erstmals tatsächlich durchgesetzt (Playlist-Trunkierung, Modul-Level-Semaphore, echter yt-dlp-`match_filter` mit Podcast-Ausnahme)
- [x] TEST-005 behoben — 18 Characterization-Tests für alle produktiv genutzten `NavidromeAPI`-Methoden, 8 tote Methoden als LEGACY-003 dokumentiert
- [x] TEST-006 behoben — 25 Characterization-Tests für `MusicBrainzClient` (P0, vorher 0 Tests)
- [x] BUG-001 behoben — echte Track-Position statt Medium-Gesamtanzahl, live gegen musicbrainz.org verifiziert
- [x] BUG-002 behoben — release-group-Daten (Tags/Titel) überlebten die zweite `get_recording_by_id()`-Abfrage nicht mehr, MusicBrainz-Tag-basierte Genre-Erkennung war dadurch faktisch tot

### P1
- [ ] Config Side Effects untersuchen
- [x] Cache-Verträge dokumentieren — Metadata-/Duplicate-/Lyrics-/History-Cache jetzt alle charakterisiert (siehe TEST-003/TEST-004/`test_statistik_service.py`)
- [ ] externe Adapter inventarisieren — Navidrome (TEST-005), Genius (REL-002), MusicBrainz (TEST-006) jetzt charakterisiert; Last.fm/Fanart/Cover-Netzwerk/Spotify-Downloader noch offen
- [x] Download-Pipelines testen — Event-Loop-Blockierung, URL-Allowlist, Ressourcen-Limits (siehe Phase 3 oben)
- [x] Navidrome Integration testen — siehe TEST-005

### P2
- [ ] Legacy reduzieren
- [ ] große Orchestratoren refactoren
- [ ] Zielarchitektur schrittweise umsetzen

---

## Leitprinzip

> **Erst verstehen → dann testen → dann verbessern.**

Der MusicBot wird nicht neu geschrieben.

Er wird kontrolliert weiterentwickelt.
