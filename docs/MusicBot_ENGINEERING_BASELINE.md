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

Die README beschrieb das Projekt ursprünglich nur als „Musikdownloader mit Telegram funktion und Navidrome“ (siehe DOC-001) — mittlerweile behoben, README dokumentiert jetzt Architektur, Projektstruktur, Setup und Testausführung.

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
| BUG-003 | `CoverProcessor` (`services/downloader/utils/metadata/cover_processor.py`): `ScoreThreshold.EARLY_EXIT` war auf `170` gesetzt, aber `_calculate_score()` deckelt den Score strukturell auf maximal `150` (`min(150, ...)`). Die Early-Exit-Optimierung in `get_cover_art()` (sofortiger Abbruch der Quellen-Suche, sobald ein exzellentes Cover mit ausreichender Auflösung gefunden wurde) konnte dadurch NIE greifen — jede Cover-Suche durchlief immer alle konfigurierten Quellen (Fanart.tv, Apple Music, Deezer, Last.fm, YouTube-Thumbnails), auch wenn bereits das bestmögliche Ergebnis vorlag. Reiner Effizienzverlust (unnötige API-Aufrufe/Rate-Limit-Verbrauch, langsamere Verarbeitung), keine falschen Cover-Auswahlen, da die finale `max(candidates, ...)`-Auswahl unverändert korrekt blieb | P2 | **behoben** — `EARLY_EXIT` auf `140` gesetzt: rechnerisch von den vier zuverlässigsten Quellen (`coverartarchive`/`fanart_album`/`apple_music`/`deezer`) bereits bei der ohnehin geforderten Mindestauflösung (`_EARLY_EXIT_MIN_DIM` = 1400px, quadratisch) erreichbar, von schwächeren Quellen (`fanart_artist`/`lastfm`/YouTube) nur bei deutlich höherer Auflösung bzw. praktisch nie (YouTube hat einen `-10`-Malus). 4 neue Tests in `tests/test_cover_processor_validation.py::TestBug003EarlyExitThresholdWasUnreachable` (inkl. direktem Beweis, dass `get_cover_art()` niedriger priorisierte Quellen nach einem Early-Exit-Treffer gar nicht erst aufruft), am unfixierten Code als fehlschlagend verifiziert. Zusätzlich 6 neue Charakterisierungstests für `_build_priority_task_list()` (`TestBuildPriorityTaskList`) |
| BUG-004 | `SpotifyDownloader._download_via_ytdlp_safe()` (`services/downloader/spotify_downloader.py`) ermittelte die heruntergeladene Datei über "neueste Datei im gesamten `download_dir`" (glob + mtime-Sortierung). `self.download_dir` ist identisch mit `Config.DOWNLOAD_DIR`, das AUCH von der regulären YouTube-Download-Pipeline genutzt wird (`Config.SPOTIFY_DOWNLOAD_DIR` existiert in `config.py`, wurde aber nie angebunden — komplett unbenutztes totes Config-Feld). Bei mehreren gleichzeitigen Downloads (seit REL-005 explizit bis zu `MAX_CONCURRENT_DOWNLOADS` erlaubt) konnte die Datei eines PARALLEL laufenden, fremden Downloads fälschlich als "die eigene" erkannt werden — falscher Audio-Inhalt landet unter falschen Metadaten in der Library. Live gegen den yt-dlp-Quellcode verifiziert (`FFmpegExtractAudioPP.run()` in `postprocessor/ffmpeg.py`), dass `info_dict["filepath"]` nach Postprocessing zuverlässig den finalen, korrekt konvertierten Pfad enthält | P0 | **behoben** — liest jetzt `download_info.get("filepath")`/`.get("_filename")` statt das Verzeichnis zu scannen; alte Methode bleibt als defensiver Fallback erhalten, falls yt-dlp ausnahmsweise keinen Pfad liefert. 2 Regressionstests in `tests/test_spotify_downloader.py::TestDownloadedFileDetectionBug004`, direkter Beweis am unfixierten Code: bei einer künstlich "neueren" Fremd-Datei im selben Verzeichnis wählte der alte Code nachweislich die falsche Datei |
| TEST-008 | `services/downloader/spotify_downloader.py` (`SpotifyDownloader`) hatte 914 Zeilen und 0 Tests, trotz P1-Status ("externe Adapter") | P1 | **behoben** — 21 Characterization-Tests in `tests/test_spotify_downloader.py` für die vier reinen Hilfsfunktionen (`_is_spotify_url`, `_spotify_url_type`, `_extract_spotify_id` inkl. `/intl-de/`-Robustheit, `_sanitize_spotify_url`) sowie `_download_via_ytdlp_safe()` (inkl. BUG-004). Nebenbefund charakterisiert, nicht gefixt: `_download_from_rss_feed()` matcht Episodennamen gegen RSS-Feed-Titel per Substring (`episode_name_lower in title.lower()`), nimmt den ERSTEN Treffer in Feed-Reihenfolge — bei kurzen/generischen Episodennamen (z.B. "Intro", "Bonus") könnte das eine andere, falsche Episode treffen. Kein mechanischer Fix ohne Entscheidung über eine bessere Match-Strategie (exakt/fuzzy/datumsbasiert), ähnlich GENRE-002 — daher nur dokumentiert |
| SEC-005 | Beim Charakterisieren von `handlers/admin/user_management_handler.py` gefunden — direkte Fortsetzung von SEC-003: `RichMenuSystem._is_admin_check()` (der SEC-003-Fix) behandelt "ist Owner" und "ist in `ADMIN_USER_IDS`" als gleichwertig für den Zugriff auf ALLE `usermgmt_`-Callbacks. `ADMIN_USER_IDS` ist in `config.py` aber explizit als eigene, vom Owner GETRENNTE Liste vorgesehen (`ADMIN_USER_IDS`-Env-Var, fällt nur auf `[OWNER_USER_ID]` zurück, wenn leer). Ohne zusätzliche Sperre konnte **jeder konfigurierte Admin (nicht nur der Owner) sich selbst oder andere per `usermgmt_set_role_<id>_owner` zum Owner befördern** — "Owner" ist aber die höchste, eigentlich einmalig vergebene Autorität (`permissions=["all"]`). Zusätzlich validierte `set_user_role()` `new_role` nicht gegen `self.ROLES` (im Gegensatz zur Schwester-Methode `toggle_user_permission()`, die das für Permissions bereits tat) | P0 | **behoben, nach Nutzer-Entscheidung** (Owner-Vergabe ist sicherheitsrelevant genug für eine bewusste Bestätigung statt eigenmächtiger Annahme) — `set_user_role()` prüft jetzt zusätzlich: wird `new_role=="owner"` gesetzt, muss der handelnde User `== Config.OWNER_USER_ID` sein, sonst Ablehnung mit Log-Warnung. Admins dürfen weiterhin user/moderator/admin vergeben. Plus: `new_role not in self.ROLES` wird jetzt abgelehnt. 7 Regressionstests in `tests/test_user_management_handler.py::TestSetUserRoleSec005OwnerEscalation`/`TestSetUserRoleValidation`, am unfixierten Code als fehlschlagend verifiziert (konkreter Beweis: `assert 'owner' == 'user'` schlägt fehl, ein Admin hat sich tatsächlich befördert) |
| TEST-009 | `handlers/admin/user_management_handler.py` (`UserManagementHandler`) hatte 769 Zeilen und 0 dedizierte Tests (nur indirekt über `tests/test_rich_menu_access_control.py` auf Dispatcher-Ebene abgedeckt) | P1 | **behoben** — 27 Characterization-Tests in `tests/test_user_management_handler.py` (inkl. SEC-005). Deckt Rollenvergabe, Permission-Toggle (inkl. "all"-Sonderfall), User-Löschung, den zweistufigen "Neuer Benutzer + Navidrome-Username"-Workflow und Menü-Pagination ab. Wichtiger Testinfrastruktur-Hinweis: `UserManagementHandler.__init__()` liest/schreibt `data/user_data.json` über einen **hartcodierten, nicht injizierbaren Path** — diese Datei enthält echte, laufende Bot-Nutzerdaten (u. a. den echten Owner). Tests patchen `Path()` während der Konstruktion auf ein `tmp_path`-Verzeichnis (analog zur ArtistNormalizer-Inzidenz aus einer früheren Session), inkl. eines expliziten Sanity-Checks, dass die reale Datei nie berührt wird |
| SEC-006 | **Kritisch — Arbiträre Datei-Löschung.** `BackupHandler.delete_backup()`/`confirm_delete()` (`handlers/admin/backup_handler.py`) bauten `filepath = self.dest_dir / filename`, wobei `filename` unvalidiert aus `callback_data` kommt (`backup_delete_<filename>`/`backup_delete_confirm_<filename>` — Telegram-`callback_data` ist ein von jedem Client frei sendbarer String, siehe SEC-003/SEC-005). `pathlib.Path.__truediv__` hat zwei ausnutzbare Eigenschaften, beide live verifiziert: (1) `".."`-Traversal wird beim tatsächlichen Dateizugriff aufgelöst und verlässt `dest_dir`; (2) ein ABSOLUTER rechter Operand verwirft den linken Teil komplett — `Path("/a/b") / "/etc/passwd" == Path("/etc/passwd")`. `delete_backup()` rief `filepath.unlink()` auf diesem unvalidierten Pfad auf — jeder Admin (nicht nur der Owner, siehe SEC-005-Kontext) hätte so **beliebige, vom Bot-Prozess beschreibbare Dateien löschen können**, nicht nur Backups (z. B. `config.py`, `.env`, Musikdateien, Logs). Empirisch reproduziert: unfixierter Code löschte tatsächlich eine Test-Datei außerhalb des Backup-Verzeichnisses via `../`-Traversal UND via absolutem Pfad | P0 | **behoben** — neue `_resolve_backup_path()` validiert per `.resolve()` + `is_relative_to()`, exakt analog zum bereits bestehenden SEC-003-Fix in `handlers/enhanced_logger_menu_handler.py::show_log_file_detail()`. `confirm_delete()` und `delete_backup()` nutzen sie jetzt beide. 7 dedizierte Regressionstests in `tests/test_backup_handler.py::TestResolveBackupPathSec006`/`TestDeleteBackupSec006Regression`, am unfixierten Code als tatsächlich fehlschlagend verifiziert (die Zieldatei existierte danach nachweislich nicht mehr) |
| TEST-010 | `handlers/admin/backup_handler.py` (`BackupHandler`) hatte 509 Zeilen und 0 Tests | P1 | **behoben** — 18 Characterization-Tests in `tests/test_backup_handler.py` (inkl. SEC-006). Deckt Backup-Rotation (`_rotate_backups`, älteste zuerst entfernt), Auflistung nach Typ/Datum, `_human_size()`-Einheitenwahl und `_create_archive()`-Exclude-Pattern (Fragment- und Wildcard-Matching) ab |
| TEST-011 | `handlers/menu/rich_menu_system.py` (`RichMenuSystem`, 1942 Zeilen) war über den in `tests/test_rich_menu_access_control.py` (SEC-003) abgedeckten Admin-Gate-Ausschnitt hinaus nicht charakterisiert — `MenuItem`/`MenuSession`-Datenklassen, Access-Level-Ermittlung, Session-Verwaltung, Menü-Rendering waren ungetestet | P1 | **behoben** — 29 Characterization-Tests in `tests/test_rich_menu_system.py`. Zwei Nebenbefunde dokumentiert, bewusst nicht gefixt (beide niedrige Priorität, keine Sicherheitswirkung): (1) `_get_user_access_level()`s Cache-basierte Rollenprüfung erkennt `"ADMIN"`/`"MODERATOR"`/`"USER"`, aber nicht `"OWNER"` — ein per `set_user_role()` (seit SEC-005 nur vom echten Owner vergebbar) mit `role="owner"` markierter, aber nicht zusätzlich in `Config.OWNER_USER_ID`/`ADMIN_USER_IDS` stehender Nutzer fällt auf `AccessLevel.USER` zurück; folgenlos, da `AccessLevel` laut SEC-003-Fund nur Button-Rendering steuert, nicht die tatsächliche Autorisierung (`_is_admin_check()`, unabhängig). (2) Der in `enhanced_status_handler.py` gerenderte `"🗑️ Cleanup"`-Button (`callback_data="status_storage_cleanup"`) ist in `_handle_status_callback()`s `routing_map` nicht verdrahtet — fällt auf "Funktion nicht implementiert" zurück; die in der SEC-003-Doku erwähnte "destruktive Cleanup-Aktion" ist dadurch aktuell inert (kein Sicherheitsrisiko, im Gegenteil) |
| BUG-005 | `handlers/enhanced_error_handler.py` (mit 2508 Zeilen die größte Datei im gesamten `handlers/`-Verzeichnis, vorher 0 Tests) — zwei Funde: **(a)** `EnhancedErrorHandler` hatte ZWEI `__init__`-Definitionen im Klassenkörper; Python überschreibt bei doppelten Methodennamen still mit der letzten — die erste (unvollständig, Körper nur `...`) wurde nie ausgeführt, war aber totes Code-Fragment ohne jede Funktion (vermutlich ein Refactoring-Rest). **(b)** `ErrorHandlerAdminInterface._reply_or_edit()` rief im dritten Fallback-Zweig (kein `callback_query`, kein `update.message`, aber `update.effective_chat` vorhanden) `context.bot.send_message(...)` auf — `context` war aber gar kein Parameter der Methode. Dieser Zweig hätte bei tatsächlichem Erreichen (z. B. bei Update-Typen ohne `message`-Objekt) einen `NameError` geworfen statt die Nachricht zu senden — betrifft alle 5 Admin-Befehle des Error-Handler-Menüs (`erradmin:*`) | P1 | **behoben** — (a) doppelte `__init__` entfernt, keine Verhaltensänderung (die zweite war schon vorher die einzig wirksame). (b) `context` als Parameter ergänzt, alle 15 Aufrufstellen angepasst. 22 neue Tests in `tests/test_enhanced_error_handler.py`, direkter Live-Beweis für (b): unfixierter Code wirft nachweislich `NameError: name 'context' is not defined`. Nebenbefund charakterisiert, nicht gefixt: `ConnectionError`/`TimeoutError` erben in Python von `OSError`; da `"file_system"` (das ebenfalls `OSError` listet) im `categories`-Dict vor `"network"` steht, werden Netzwerkfehler in `ExceptionMonitor.categorize_exception()` durchgängig als `"file_system"` statt `"network"` einsortiert — reine Diagnose-/Statistik-Verzerrung ohne Funktionsauswirkung |
| BUG-006 | `RichMenuHandler.handle_text_message()` (`handlers/menu/rich_menu_handler.py`, zentraler Orchestrator, 1302 Zeilen, vorher 0 Tests) prüfte den Abbruch-Befehl (`/cancel`/`cancel`/`abbrechen`) erst NACH dem Workflow-Dispatch-Block. Bei aktivem Multi-Step-Workflow (`context.user_data["workflow"]` gesetzt, z. B. „Neuen Benutzer hinzufügen") `return`t der Dispatch-Block aber immer vorher — `/cancel` wurde dadurch NIE als Abbruch erkannt, solange ein Workflow aktiv war, sondern wortwörtlich als Eingabe an den Workflow-Handler durchgereicht (z. B. `process_new_user_id(..., "/cancel")` → „'/cancel' ist keine gültige Telegram User-ID"). Das widersprach direkt der eigenen Bot-Nachricht, die dem Nutzer explizit „Du kannst /cancel eingeben, um abzubrechen" anbietet. Betraf ebenso den Navidrome-Suchpfad (`/cancel` wäre als wörtlicher Suchbegriff an Navidrome weitergereicht worden) | P1 | **behoben** — Abbruch-Prüfung an den Anfang der Methode verschoben, vor Navidrome-Suche und Workflow-Dispatch. 5 neue Regressionstests in `tests/test_rich_menu_handler.py::TestHandleTextMessageWorkflow`, am unfixierten Code als fehlschlagend verifiziert (Workflow-Handler wurde nachweislich mit `"/cancel"` als Eingabe aufgerufen). 28 Characterization-Tests insgesamt, inkl. Rollen-/Feature-Auflösung (`_get_user_role()` erkennt „owner" hier korrekt, im Gegensatz zu `RichMenuSystem._get_user_access_level()`, siehe TEST-011) und `_create_download_handler()`. Gleiche Testinfrastruktur-Vorsicht wie TEST-009: `user_data_file` wird während der Konstruktion auf `tmp_path` gepatcht |
| BUG-007 | `handlers/navidrome_menu_handler.py` (`NavidromeMenuHandler`, 1116 Zeilen, vorher 0 Tests) — zwei Funde: **(a)** `_initialize_api()` prüfte `hasattr(self.config, "NAVIDROME_URL") and hasattr(self.config, "NAVIDROME_USER")`. Beide sind `@property` auf `Config` und liefern bei fehlender `.env`-Variable `""` statt eine Exception — `hasattr()` prüft nur, ob die Property EXISTIERT (immer der Fall), nicht ob sie einen echten Wert hat. `connection_status` war dadurch unabhängig von der tatsächlichen Konfiguration IMMER `True`; der im Code-Kommentar versprochene spätere asynchrone Verbindungstest existiert nirgends im Code. **(b)** `handle_artist_detail()`/`handle_genre_detail()` fügten `artist_name`/`genre_name` ungeschützt in einen mit `parse_mode="MarkdownV2"` gesendeten Nachrichtentext ein — andere Methoden im selben File (`process_search_query`, `handle_stats`) escapen dynamische Inhalte bereits korrekt mit `escape_md_v2()`, diese zwei nicht. Jedes MarkdownV2-Sonderzeichen im Namen (Punkt, Bindestrich, Klammern, Ausrufezeichen — in echten Künstler-/Genre-Namen wie „Lo-Fi" oder „Vol. 2!" keine Seltenheit) hätte zu einem von Telegram abgelehnten „can't parse entities"-Fehler geführt, aufgefangen als generische Fehlermeldung statt der eigentlichen Details | P1 | **behoben** — (a) prüft jetzt echte (nicht-leere) Werte statt reiner Property-Existenz; ein vollständiger asynchroner Verbindungstest (`NavidromeAPI.check_connection()`) wäre ein größerer Umbau und bewusst nicht Teil dieses Fixes. (b) `escape_md_v2()` in beiden Methoden ergänzt. 9 Tests in `tests/test_navidrome_menu_handler.py`, 6 davon Regressionstests, am unfixierten Code als fehlschlagend verifiziert (u. a. direkter Beweis: unfixierter Text enthält den rohen, unescapten Namen wortwörtlich) |
| TEST-012 | `handlers/enhanced_status_handler.py` (`EnhancedStatusHandler`, 870 Zeilen) und `handlers/mugge_statistik_handler.py` (`StatistikHandler`, 570 Zeilen) hatten 0 Tests — letzte beiden offenen Punkte der Telegram-Handler-Layer-Charakterisierung | P1 | **behoben** — 14 Tests in `tests/test_enhanced_status_handler.py` (`SystemMonitor`/`BotStatusTracker`, `format_bytes()`, `show_storage_status()`) und 14 Tests in `tests/test_mugge_statistik_handler.py` (`_get_navidrome_user_for_request()`s 3-stufige Priorität: UserManagementHandler-Cache → direktes Laden von `user_data.json` → `Config.NAVIDROME_USER`-Fallback; `handle_top_songs()`/`handle_last_played()`). Kein neuer Bug, aber ein systemisches Unvollständigkeits-Muster dokumentiert: von 18 im Status-Menü gerenderten `status_*`-Callbacks sind in `RichMenuSystem._handle_status_callback()` nur 7 tatsächlich verdrahtet — 11 (u. a. `status_users`, `status_trends`, `status_system_detail`, `status_performance_reset`) fallen auf „Funktion nicht implementiert" zurück (kein Sicherheitsrisiko, unfertige Feature-Entwicklung, bewusst nicht mit 11 neuen Handler-Methoden „gefixt"). `_escape_text()` in `StatistikHandler` gegengeprüft: der Name ist irreführend (escaped keine Markdown-Sonderzeichen), aber harmlos, da kein einziger Aufrufer im File `parse_mode` setzt (reines Plain-Text-Handling) — anders als das strukturell identische, aber tatsächlich reachable Problem in BUG-007b |
| DATA-003 | Nach DATA-001/DATA-002 (nur 4 von 14 `mapping/*.yaml`/`*.json`-Dateien geprüft) verbleibende 9 YAML- + 1 JSON-Mapping-Datei nie auf dasselbe stille „letzter Key gewinnt"-Problem geprüft (`genre_filters.yaml`, `channel_genre.yaml`, `case_preserve.yaml`, `auto_learned_artists.yaml`, `auto_learned_genre.yaml`, `known_artists.yaml`, `special_channel.yaml`, `podcast_rss_feeds.yaml`, `genre_rules.yaml`, `artist_overrides.json`) | P1 | **geprüft, keine Duplikate gefunden** — `tests/test_mapping_yaml_integrity.py` generisch erweitert: `MAPPING_FILES_TO_CHECK` iteriert jetzt automatisch über alle `mapping/*.yaml`-Dateien (per `glob`) statt einer hartcodierten 4er-Liste, plus neue `TestNoDuplicateKeysInMappingJsonFiles` für `mapping/*.json` (`json.load()` hat dasselbe stille Duplikat-Verhalten wie PyYAML). Damit ist jede aktuelle UND jede künftig neu hinzukommende Mapping-Datei automatisch gegen dieses Muster abgesichert, ohne dass man sich an manuelles Nachtragen erinnern muss. 22 Tests insgesamt in der Datei (vorher 15) |
| ARCH-001-STEP-3 | Dritter Extraktionskandidat aus ARCH-001: Workflow-Dispatch/State-Machine in `RichMenuHandler` (Cancel-Erkennung + `workflow_handlers`-Dispatch-Block in `handle_text_message()`, ~55 Zeilen) — genau die Stelle, an der BUG-006 saß (Cancel-Check-Reihenfolge) | P2 | **umgesetzt** — neue Klasse `TextWorkflowDispatcher` (`handlers/menu/text_workflow_dispatcher.py`) mit `is_cancel_command()` und `try_dispatch()`. Bewusst NICHT mit extrahiert: `user_states` (URL-Erwartungs-Dict, wird auch von `handle_url_message()`/den Download-Wrappern genutzt, keine reine Workflow-Dispatch-Logik) und die Navidrome-Suchlogik (bleibt `NavidromeMenuHandler`s Sache). Wichtige Design-Entscheidung: `user_mgmt_handler` wird bei jedem `try_dispatch()`-Aufruf frisch übergeben statt einmalig injiziert — Grund: `RichMenuHandler.initialize()` setzt `self.user_mgmt_handler` teils per Direktzuweisung, teils über `set_user_mgmt_handler()`; eine einmalige Registrierung zum Setter-Zeitpunkt hätte den Direktzuweisungs-Pfad verpasst und den Workflow-Dispatch für echte User-Management-Workflows heimlich kaputt gemacht (bei der Analyse entdeckt, bevor es zum Bug wurde). In `RichMenuHandler.handle_text_message()` bleibt die kritische Cancel-vor-Dispatch-Reihenfolge (der BUG-006-Fix) unverändert an derselben Stelle erhalten. 17 neue Unit-Tests in `tests/test_text_workflow_dispatcher.py` (Cancel-Varianten case-insensitive, alle 3 Workflow-Namen, fehlender Handler, Handler ohne die erwartete Methode), per `git stash -u` gegen den Vor-Extraktions-Stand als fehlschlagend (ModuleNotFoundError) verifiziert. Alle 28 bestehenden `RichMenuHandler`-Tests weiterhin grün, **inklusive** `test_cancel_works_even_with_active_workflow_bug006_regression` — der BUG-006-Regressionsschutz bleibt über die Extraktion hinweg intakt. Voller Regressionslauf: 585 bestanden (vorher 568), unverändert 15 Vorbestand-Fehler |
| ENCAP-001 | Zwei der drei in ARCH-001 als "weiterhin offen" dokumentierten Kapselungsverletzungen: (1) `RichMenuHandler._register_system_handlers()` griff direkt auf `RichMenuSystem.menu_registry` (eigentlich intern) zu, um den dynamisch erzeugten "Navidrome Scan"-Menüpunkt anzuhängen; (2) `bot.py._async_cleanup_components()` griff über zwei Ebenen (`rich_menu_handler.metadata_processor.genius_client`) durch, um eine mehrstufige Async-Cleanup-Fallback-Kette (async_close → Session-Fallback → sync close) direkt in `bot.py` auszuführen, statt dass `EnhancedMetadataProcessor` selbst einen async-fähigen Cleanup anbietet. Dabei nebenbei gefunden: `EnhancedMetadataProcessor.cleanup()` (die synchrone Variante inkl. `metadata_cache_obj.cleanup()`) wird an keiner Stelle im Shutdown-Pfad aufgerufen — `RichMenuHandler.cleanup()` bereinigt nur Menü-Sessions, nicht den MetadataProcessor. Bewusst NICHT im selben Schritt "gefixt" (wäre eine unbeabsichtigte Verhaltensänderung: `metadata_cache_obj.cleanup()` würde erstmals live laufen) — nur dokumentiert | P2 | **teilweise behoben** — (1) neue öffentliche Methode `RichMenuSystem.add_child_menu_item(parent_id, item)`, `_register_system_handlers()` nutzt sie jetzt statt der Registry direkt zu mutieren. (2) neue öffentliche Methode `EnhancedMetadataProcessor.aclose()`, enthält 1:1 dieselbe Fallback-Kette, die vorher in `bot.py` lebte; `bot.py._async_cleanup_components()` ruft jetzt nur noch `await proc.aclose()`. Der dritte dokumentierte Fall (`download_utils.py` → `auto_learn_manager.learn_artist()`) bewusst NICHT angefasst, siehe AUTOLEARN-001. 9 neue Tests (`tests/test_rich_menu_system.py::TestAddChildMenuItem`, `tests/test_enhanced_metadata_processor_aclose.py`), per `git stash -u` gegen den Vor-Fix-Stand als fehlschlagend verifiziert. Zusätzlich verwaiste Backup-Datei `services/downloader/utils/metadata/genre_processor.py.blak` entfernt (seit Initial-Commit im Repo, nie importierbar — `.blak` ist keine gültige Python-Extension —, veraltete Vorversion des echten `genre_processor.py` vor dessen v2.1-Rewrite). Voller Regressionslauf: 594 bestanden (vorher 585), unverändert 15 Vorbestand-Fehler |
| AUTOLEARN-001 | Bei ENCAP-001 gefunden: `download_utils.py` rief nach jedem erfolgreichen `EnhancedMetadataProcessor.process_single_track()`-Aufruf zusätzlich `auto_learn_manager.learn_artist(...)` auf (zwei Call-Sites, Playlist- und Single-Track-Pfad) — obwohl `process_single_track()` selbst bereits intern denselben `learn_artist()`-Aufruf für jeden Track macht (Schritt "19b. Auto-Learning"). Vertiefte Untersuchung ergab den eigentlichen Grund für den Unterschied: die externe Prüfung nutzte `get_special_category()`/`load_special_channels_merged()` — die **vollständige, YAML-konfigurierte** Sonderkanal-Liste (`mapping/special_channel.yaml`) —, während die interne Prüfung (`_is_podcast_channel`) nur eine **hartcodierte 2-Kanal-Liste** (`{"backstage boxengasse", "sky sport formel 1"}`) kannte. Für Sonderkanäle außerhalb dieser 2 Namen (z. B. "Gemischtes Hack", "Mordlust" — beide echte Einträge in `special_channel.yaml`) lernte der interne Aufruf trotzdem fälschlich einen Artist-Alias; der externe Aufruf verhinderte nur seinen *eigenen* zweiten Fehlversuch, behob aber nicht die interne Lücke | P1 | **behoben** — `EnhancedMetadataProcessor.process_single_track()`s Auto-Learning-Gate (Schritt 19b) prüft jetzt zusätzlich zu `_is_podcast_channel` auch über `get_special_category()`/`load_special_channels_merged()` (rein additiv/einschränkend: `_is_special_channel_for_learning = _is_podcast_channel or bool(get_special_category(...))` — kann Auto-Learning nur zusätzlich verhindern, nie zusätzlich erlauben). Die beiden jetzt echt redundanten externen `learn_artist()`-Aufrufe in `download_utils.py` entfernt. 4 neue Tests in `tests/test_autolearn_special_channel_gate.py` (2 reale Sonderkanal-Namen aus der YAML werden jetzt korrekt ausgeschlossen, der ursprüngliche hartcodierte Fall bleibt ausgeschlossen, ein normaler Kanal löst weiterhin normal Auto-Learning aus), per `git stash` gegen den Vor-Fix-Stand als fehlschlagend verifiziert. Nebenbefund beim Testen entdeckt, NICHT behoben (eigenständiges Problem, siehe ARTISTNORM-001): `ArtistNormalizer.normalize("Hardenacke trifft")` mangelt zu `"Hardenacke Trif"` — die Collaboration-Split-Logik erkennt das "ft" in "tri**ft**t" fälschlich als Featuring-Marker. Voller Regressionslauf: 598 bestanden (vorher 594), unverändert 15 Vorbestand-Fehler |
| ARTISTNORM-001 | `ArtistNormalizer.normalize()` (`utils/artist_map.py`) mangelte Namen, die die Zeichenfolge "ft" nur als Teilstring enthalten — konkrete Vorher/Nachher-Beispiele: `normalize("Hardenacke trifft")` → `"Hardenacke Trif"`, `normalize("Kraftklub")` → `"Kra, klub"`, `normalize("Draft")` → `"Dra, "`, `normalize("Wefts")` → `"We, s"`, `normalize("Softi")` → `"So, i"`. Ursache gefunden: das Featuring-Pattern `r"\s*(?:feat\.?|ft\.?)\s*"` (Zeile 473) matchte "ft"/"feat" als reinen Teilstring ohne Wortgrenzen — traf daher auch mitten in Wörtern wie „tri**ft**t", „Kra**ft**klub", „Dra**ft**". Identisches Pattern doppelt vorhanden: `_normalize_collaboration()` (Zeile 619) prüft nach demselben Muster erneut, als Sicherheitsnetz für Trenner (z. B. "x"), die die erste Regel nicht kennt. Betrifft real existierende Kanalnamen (`"Hardenacke trifft"` steht in `mapping/special_channel.yaml`) | P1 | **behoben** — beide Stellen in `utils/artist_map.py` auf `r"\s*\b(?:feat|ft)\b\.?\s*"` bzw. `r"\s*(?:\bfeat\b\.?|\bft\b\.?|x|&|vs\.?|/|;)\s*"` umgestellt: `\b` unmittelbar nach den Buchstaben "feat"/"ft" (nicht nach dem optionalen Punkt, da zwischen "." und einem folgenden Leerzeichen — beides Nicht-Wortzeichen — keine Wortgrenze existiert). Rein einschränkend: kann vorher fälschlich gematchte Teilstring-Treffer verhindern, ändert nichts an echten "Artist feat./ft. Other"-Fällen (durch bestehende + 6 neue Tests in `tests/test_artist_normalizer.py::TestArtistnorm001FeatFtWordBoundaryFix` verifiziert, u. a. Groß-/Kleinschreibung und mit/ohne Punkt). Per `git stash` gegen den Vor-Fix-Stand als fehlschlagend verifiziert. Voller Regressionslauf: 604 bestanden (vorher 598), unverändert 15 Vorbestand-Fehler. Bewusst NICHT im selben Schritt behoben: dieselbe fehlerhafte Musterklasse existiert noch in 3 weiteren Dateien, siehe ARTISTNORM-002 |
| ARTISTNORM-002 | Beim Beheben von ARTISTNORM-001 gefunden: dieselbe fehlerhafte "ft"/"feat"-Teilstring-Matching-Musterklasse (ohne Wortgrenzen) existiert unabhängig noch in 3 weiteren Dateien: (1) `services/downloader/utils/metadata/title_cleaner.py:300` — am schwerwiegendsten, da der nachfolgende Teil `\s+[^(\[\n]+` gierig alles bis zum Zeilenende konsumiert: `"Hardenacke trifft - Irgendein Titel"` wurde zu `"Hardenacke trif"` gekürzt, der komplette Rest des Titels ging verloren. (2) `services/downloader/utils/metadata/models.py:36` (`split_main_and_featuring()`) — live verifiziert: `split_main_and_featuring("Hardenacke trifft Jemand")` lieferte fälschlich `("Hardenacke trif", ["Jemand"])` statt eines unsplitteten Namens; diese Funktion wird von `ArtistProcessor.determine_best_artist()` genutzt, dem zentralen Fixpunkt von ARTIST-001 aus einer früheren Session. (3) `utils/youtube_parser.py` (4 Fundstellen, Zeilen 192/194/196/254) — bei genauerer Prüfung als SICHER bestätigt: alle 4 Patterns verlangen zwingendes `\s+` (mindestens ein Leerzeichen) unmittelbar vor der `feat`/`ft`-Alternation statt `\s*` (optional) wie bei den 2 gefixten Stellen — ein Teilstring mitten im Wort (z. B. das "ft" in "tri**ft**t") ist strukturell nie von echtem Leerzeichen umgeben, kann diese Patterns daher nie treffen. Empirisch mit denselben Testfällen wie bei den anderen Fundstellen bestätigt (kein Match). `services/organizer.py:421` ebenfalls bestätigt SICHER (verlangt zwingend Punkt UND Leerzeichen auf beiden Seiten) | P2 | **behoben (2 von 2 tatsächlich betroffenen Stellen)** — `title_cleaner.py` und `models.py::split_main_and_featuring()` auf `\b`-Wortgrenzen umgestellt (identisches Fix-Muster wie ARTISTNORM-001), `youtube_parser.py` und `organizer.py` brauchten keine Änderung (strukturell sicher). 14 neue Tests: `tests/test_split_main_and_featuring.py` (13 Tests, vorher komplett ungetestete Funktion) + 1 Regressionstest in `tests/test_metadata_modules.py::TestTitleCleaner`. Beide Fixes per `git stash` gegen den Vor-Fix-Stand als fehlschlagend verifiziert. Voller Regressionslauf: 618 bestanden (vorher 604), unverändert 15 Vorbestand-Fehler |
| LEGACY-007 | Systematische Ungetestet-Prüfung (alle `.py`-Dateien unter `services/`, `handlers/`, `klassen/`, `utils/`, `api/` gegen `tests/`-Referenzen abgeglichen) fand ein weiteres, verstecktes totes Verzeichnis: `handlers/.buttons/` (Punkt-Präfix, 4 Dateien + `__init__.py`) — null Aufrufer im gesamten Repo. Der Datei-Header-Kommentar in `button_router.py` lautet `# handlers/buttons/ button_router.py` (OHNE Punkt) — das Verzeichnis wurde vermutlich versehentlich mit führendem Punkt anstatt am beabsichtigten Pfad `handlers/buttons/` angelegt, wodurch es als Python-Package (`handlers.buttons`) nie importierbar war. `handlers/.buttons/navigation.py` importierte zusätzlich `services/commands_services.py`, dessen einziger Aufrufer wiederum nur dieses tote Verzeichnis war (dessen eigener Docstring auf `command_handler.py`/`button_handler.py` verweist — Dateien, die es im Repo nicht mehr gibt, derselbe abgelöste Command-System-Cluster wie LEGACY-005) | P2 | **entfernt** — alle 5 Dateien gelöscht (`handlers/.buttons/` komplett + `services/commands_services.py`), frisch verifiziert: keine Aufrufer, keine echten Testreferenzen (zwei zufällige Namensübereinstimmungen mit dem Wort „navigation" in `test_suite.py`/`test_rich_menu_access_control.py` geprüft und als unrelated bestätigt). Voller Regressionslauf: unverändert 15 Vorbestand-Fehler, 618 bestanden |
| SEC-001 | Sensible Daten in Request-Logs möglich | P0 | **behoben** (Phase 1) — `api/navidrome_api.py` maskiert `u`/`p` jetzt via `Config.mask_sensitive()` vor dem Log-Call; Regressionstest `tests/test_navidrome_api_logging.py` simuliert das reale Auslöse-Szenario (Admin hebt Modul-Log-Level über die Telegram-Logger-Verwaltung an) |
| TEST-001 | Teile der Tests testen nicht direkt Produktionsimplementierungen | P0 | **teilweise behoben** (Phase 1) — `tests/test_genre_processor.py` importiert jetzt die echte `GenreProcessor`-Produktionsklasse (vorher: eigene Nachimplementierung, wurde von pytest wegen `__init__`-Konstruktor der Testklasse zudem gar nicht eingesammelt). Weitere Bereiche (siehe TEST-002/TEST-003) außerhalb dieses Fixes |
| TEST-002 | `handlers/duplicate_handler.py` hatte vor Phase 1 keinerlei Testabdeckung; dabei wurde ein aktiver Bug gefunden: `check_library_duplicate()` (Duplicate-Detection Layer 4) rief `re.sub()` ohne `import re` auf → `NameError`, von `except Exception` verschluckt, Layer 4 lieferte in Produktion immer `None` | P0 | **behoben** (Phase 1) — `import re` ergänzt, 12 Charakterisierungstests in `tests/test_duplicate_handler.py`, inkl. Regressionstest für den Bugfix |
| TEST-003 | `MetadataCacheHandler.check()` und `_normalize_cache_title()` (`services/downloader/utils/metadata/cache.py`) waren seit dem Initial-Commit reine Stubs (Body nur `...`, lieferten immer `None`). `EnhancedMetadataProcessor.process_single_track()` nutzt `check()` als Cache-Hit-Prüfung → der Cache-Hit-Pfad der Metadata-Pipeline war in Produktion vollständig wirkungslos, jeder Track durchlief immer die volle Pipeline inkl. externer API-Calls | P0 | **behoben** (nach TEST-003-Freigabe) — `check()` wird VOR, `store()` NACH der Artist-/Titel-Bereinigung aufgerufen, ein direkter Artist::Titel-Lookup aus rohen Daten würde daher praktisch nie treffen. Lösung: zusätzlicher Video-ID-Index (`video_id_index.json`, analog zum bestehenden `DuplicateCache`-Muster) — `track_metadata["id"]` ist bei YouTube- wie Spotify-Downloads bereits vor der Bereinigung stabil vorhanden. `check()` validiert zusätzlich, dass die referenzierte `library_path`-Datei noch existiert (Orphan-Schutz), bevor ein Treffer zurückgegeben wird. `_normalize_cache_title()`/`invalidate()` bewusst unangetastet (bestätigt toter Aufrufer bzw. ausreichender bestehender Fallback). 6 neue/aktualisierte Tests in `tests/test_metadata_cache_handler.py` + ein End-to-End-Beweis in `tests/test_metadata_processor_happy_path.py` (zweiter Aufruf mit gleicher Video-ID ist `from_cache=True` UND ruft externe Clients nicht erneut auf — ohne Fix crasht der zweite Aufruf sogar mit `FileNotFoundError`, da die Quelldatei vom ersten Durchlauf bereits verschoben wurde). Alle Tests am unfixierten Stub als fehlschlagend verifiziert |
| E2E-001 | Hauptpfad nicht ausreichend Ende-zu-Ende abgesichert | P0 | **behoben** — `tests/test_metadata_processor_happy_path.py`: echter End-to-End-Lauf `EnhancedDuplicateHandler.check_for_duplicates` → `EnhancedMetadataProcessor.process_single_track` → `FilenameFixerTool.move_to_library` → erneuter Duplicate-Check (erkennt jetzt Duplikat), inkl. Negativtest für den globalen `try/except`-Sicherheitsnetz-Charakter der Pipeline. Nur externe Dienste (MusicBrainz/Last.fm/Genius/Cover-Netzwerk/FFmpeg) gefakt, alle Sub-Prozessoren real inkl. echter YAML-Genre-/Artist-Regeln aus einer tmp-Kopie von `mapping/` |
| CFG-001 | `config.py` führt beim reinen `import config` bereits mehrere Seiteneffekte aus (nicht erst bei expliziter Initialisierung): `.env`-Datei-Suche über mehrere Pfade, `print()`-Ausgaben statt `logging`, optionale Abhängigkeits-Importe (`lyricsgenius`/`musicbrainzngs`) mit `print()`-Fallback-Warnungen. Konkret gefunden: `env_paths` enthielt einen dritten, hartcodierten, maschinenspezifischen Absolutpfad (`Path("/mnt/128ssd/musicbot/.env")`) — komplett redundant zum ersten, portablen Pfad (`Path(__file__).parent / ".env"`), da `config.py` selbst in diesem Verzeichnis liegt; konnte nur greifen, wenn `config.py` auf genau dieser Maschine verschoben würde, `.env` aber am alten Pfad bliebe | P1 | **teilweise behoben** — redundanter hartcodierter Pfad entfernt (keine Verhaltensänderung, der erste Pfad deckt exakt denselben Fall ab, live via Subprocess-Test verifiziert). Die übrigen Seiteneffekte (`print()` statt `logging`, `.env`-Multi-Pfad-Suche an sich) bewusst NICHT verändert — kein großer Refactor als erste Reaktion (Regel 18), `config.py` nicht nebenbei großflächig umbauen. 8 Characterization-Tests in `tests/test_config_import_side_effects.py`, über `subprocess` in frischem Interpreter (Modul-Level-Code läuft nur beim ersten Import pro Prozess) |
| LEGACY-004 | `Config.init()`, `Config.create_directory_structure()` und `Config.validate_config()` (`config.py`) haben keinen einzigen Aufrufer im gesamten Repo — weder `bot.py` noch irgendein Handler ruft sie auf. Die dort gebündelte Logik (Verzeichnisse anlegen, Genius/MusicBrainz initialisieren, Logger-Level für Drittanbieter-Bibliotheken wie `musicbrainzngs`/`httpx`/`urllib3` reduzieren) läuft in Produktion daher nie | P2 | dokumentiert, nicht entfernt (Regel: Legacy-Code nicht ohne Beweis löschen) — nötige Verzeichnisse existieren offenbar bereits auf der Produktionsmaschine bzw. werden von einzelnen Komponenten lazy angelegt, sonst wäre der laufende Bot längst an fehlenden Verzeichnissen gescheitert. 3 Existenz-Charakterisierungstests in `tests/test_config_import_side_effects.py::TestDeadInitializationMethods` |
| ARCH-001 | Große Orchestrator-Klassen | P1 | **siehe ausführlichen ARCH-001-Eintrag weiter unten** — vollständig dokumentiert und teilweise extrahiert (ARCH-001-STEP-1/2/3) |
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
| TEST-007 | `klassen/lastfm_client.py` (`LastFMClient`) — Teil der Genre-Fallback-Kette (MusicBrainz → Last.fm → Feature-Inferenz, siehe GENRE-003) — hatte 151 Zeilen und 0 Tests | P1 | **behoben** — 12 Characterization-Tests in `tests/test_lastfm_client.py` für `_get_lastfm_data()` (Artist-/Track-Tag-Kombination inkl. Deduplizierung, Artist-Tags haben Vorrang, Track-Tag-Fehler bricht Lookup nicht ab) und `fetch_metadata()` (Genre-Bestimmung nur bei `include_genre=True` UND vorhandenen Tags, echter Timeout-Beweis über `async_timeout.timeout()`). Nebenbefund charakterisiert (kein Bug, da folgenlos): `_get_lastfm_data()` liefert `listeners`/`playcount`/`album`/`wiki` immer als `None` zurück (Kommentar im Code: "Simuliere track_info für minimalen Fallback") — pylast liefert diese Felder trotz vorhandener API nie tatsächlich ab, aber kein Aufrufer liest sie aktuell. `GenreMapper()`-Direktinstanziierung in `__init__` (statt `get_genre_mapper()`) geprüft und als unproblematisch bestätigt: `GenreMapper` erbt von `SingletonMixin`, `GenreMapper()` liefert bei bereits initialisierter Instanz ohnehin dieselbe Singleton-Instanz zurück |
| BUG-001 | `MusicBrainzClient._build_metadata()` setzte `"track_number"` auf `first_release.get("medium-track-count")`. Laut musicbrainzngs-Quellcode (`mbxml.py`) ist das die GESAMTANZAHL der Tracks auf dem Medium (`ws2:track-count`), nicht die Position des gefundenen Recordings — jeder Track desselben Albums hätte denselben falschen Wert bekommen (z.B. immer „17“ bei einem 17-Track-Album) | P1 | **behoben** — live gegen die echte musicbrainz.org-API verifiziert (`search_recordings` für "Bohemian Rhapsody"/Queen liefert `release-list[0]["medium-list"][0]["track-list"][0]["number"] == "8"`, während `medium-track-count == 17` war). Neue `_extract_track_number()`: liest zuerst `match["_source_track_number"]` (Release-Fallback-Pfad, aus dem echten Track-Objekt in `_extract_recordings_from_releases()` mitgeführt), sonst die echte Position aus `release_list → medium-list → track-list → number/position`. 3 Regressionstests in `tests/test_musicbrainz_client.py::TestBuildMetadataFieldExtraction`, am unfixierten Code als fehlschlagend verifiziert. War zuvor folgenlos (kein Aufrufer las das Feld), ist aber jetzt korrekt für den Fall, dass ein künftiger Aufrufer es nutzt |
| BUG-002 | Bei der Untersuchung von BUG-001 gefunden: `_build_metadata()` überschrieb `release_list` (und damit `release_group`) immer mit der Antwort der zweiten `get_recording_by_id()`-Abfrage. Diese unterstützt für die Entity `"recording"` aber KEINEN `"release-groups"`-Include (bestätigt über `musicbrainzngs.VALID_INCLUDES["recording"]` — der Include-Token existiert dort schlicht nicht), ihr `release-list` enthält daher NIE `release-group`-Daten. Der ursprüngliche Suchtreffer (`match`, aus `search_recordings()`) hatte diese Daten (Titel, Tags) bereits vorliegen, wurde aber verworfen — live verifiziert an "Bohemian Rhapsody": Such-Ergebnis enthält `release-group` vollständig (inkl. Tags), die Detail-Antwort hat den Key gar nicht. Effekt: `mb_tags` war dadurch in der Praxis IMMER leer → der komplette „MusicBrainz-Tags → Genre“-Fallback-Pfad war faktisch tot, und `"album"` nutzte nie den (oft korrekteren) Release-Group-Titel | P1 | **behoben** — `release_list` bevorzugt jetzt `match.get("release-list")` (reichhaltiger, aus dem Suchtreffer) vor `recording_info.get("release-list")` (aus der Detail-Abfrage). 1 Regressionstest (`test_release_group_tags_survive_the_detail_lookup`), am unfixierten Code als fehlschlagend verifiziert (`album` liefert vorher `"Release Title"` statt `"Release Group Title"`) |
| LEGACY-003 | `NavidromeAPI` enthält 8 Methoden ohne jeden Aufrufer im Repo (`count_songs_recursive`, `get_last_played`, `get_top_songs`, `get_top_artists`, `get_period_review_data`, `get_album_list`, `get_indexes`, `get_genres`) — vermutlich Reste einer älteren Statistik-/Browsing-Oberfläche, die zwischenzeitlich durch direkte `make_request()`-Aufrufe in den Handlern ersetzt wurde (Kommentar in `navidrome_menu_handler.py:315`: "KORRIGIERT: Direkte API-Anfrage statt get_genres()") | P2 | **entfernt** — nach frischer Re-Verifikation (auch dynamische Aufrufe via `getattr()`, Test-Referenzen und String-Referenzen in YAML/JSON/Docs geprüft, keine gefunden) alle 8 Methoden gelöscht. `get_period_review_data` rief intern `get_top_songs`/`get_top_artists` auf — die drei bildeten einen isolierten toten Teilbaum ohne externen Einstiegspunkt, gemeinsam entfernt. Voller Regressionslauf danach: unverändert 15 Vorbestand-Fehler, 520 bestanden |
| DATA-001 | Beim Migrieren der GENRE-002-Artist-Einträge gefunden: `mapping/artist_genre.yaml` hatte 12 doppelte Top-Level-Keys (`dominic fike`, `eminem`, `herzchen`, `majan`, `dasha`, `sarah engels`, `taylor swift`, `calvin harris`, `riton`, `one-t`, `fayan`, `"The Weeknd"`) — u.a. ein zusammenhängender 9-Einträge-Block (Zeilen 691–734), der wie ein versehentlich doppelt eingefügter Batch aussah. PyYAML behält beim Laden nur den JEWEILS LETZTEN Wert pro Key — die erste Definition wurde still verworfen, ohne Fehler oder Warnung | P1 | **behoben** — Zeile für Zeile geprüft: in allen 12 Fällen war `primary` identisch (kein Klassifizierungs-Widerspruch), meist auch `secondary` identisch; unterschied sich nur die `description` (immer eine der beiden Versionen gekürzt) bzw. bei "calvin harris" `secondary` (eine Version fehlte „Progressive House"). `description` wird laut `utils/genre_map.py` nirgends in der Matching-Logik gelesen, ist reine Dokumentation (`GenreMapping.to_dict()`) — Risiko der Bereinigung daher minimal. Jeweils die vollständigere Version behalten, die gekürzte entfernt. 2 neue Guard-Rail-Tests in `tests/test_mapping_yaml_integrity.py` (custom PyYAML-Loader, der doppelte Keys aktiv erkennt statt sie stillschweigend zu überschreiben), verhindert ein unbemerktes Wiederauftreten |
| DATA-002 | `mapping/genre_hierarchy.yaml` (1 doppelter Key: `Metal`), `mapping/genre_overrides.yaml` (8 doppelte Keys) und `mapping/genre_aliases.yaml` (13 doppelte Keys) hatten doppelte Keys — dieselbe stille PyYAML-Überschreib-Falle wie DATA-001, aber diesmal mit **echten Klassifizierungs-Konflikten** statt nur gekürzter `description`: (1) `Metal` war sowohl Top-Level-Genre (Zeile 20, explizite ROOT-LEVEL-Sektion neben Rock/Pop/Hip Hop) als auch Rock-Subgenre (Zeile 175, inmitten eines sonst nur „X: Metal"-Eintrag enthaltenden Subgenre-Blocks — wirkte wie ein Tippfehler); (2) `tech house`/`progressive house`/`hardstyle`/`electropop` waren sowohl grob in Oberkategorien (House/Dance/Pop) zusammengefasst als auch granular als eigenes Genre definiert, beide Varianten in jeweils thematisch klar organisierten Blöcken; (3) Alias `indie rock` war sowohl „Rock" (im Rock-Themenblock) als auch „Indie" (im Indie-Themenblock) definiert. Die übrigen 20 Duplikate waren wie bei DATA-001 reine Text-Duplikate (identischer Wert) | P1 | **behoben, nach expliziter Nutzer-Entscheidung pro Konflikt** (Regel 29 — Widersprüche nicht raten): Metal → Top-Level (ändert Verhalten: `get_main_genre("metal")` liefert jetzt `"metal"`/„Metal" statt vorher „rock"/„Rock", live verifiziert). EDM-Subgenres → granular behalten (= bereits aktives Verhalten, keine Änderung). `indie rock` → Indie (= bereits aktives Verhalten, keine Änderung). Die 20 reinen Text-Duplikate risikofrei entfernt, u.a. ein weiterer zusammenhängender 9-Einträge-Batch-Block in `genre_aliases.yaml` (Zeilen 391–399, exakt dasselbe Muster wie der Block in DATA-001). 12 neue/erweiterte Tests in `tests/test_mapping_yaml_integrity.py` (`TestNoDuplicateKeysInGenreMappingFiles`, `TestGenreClassificationDecisions`) |
| DOC-001 | README dokumentierte System kaum (2 Zeilen: Projektname + eine Satz-Beschreibung) | P1 | **behoben** — README neu geschrieben: Was der Bot macht, vereinfachte Architektur, Projektstruktur-Tabelle, Setup (`.env`-Variablen), Start-/Testbefehle, Hinweis auf Mapping-Dateien als Fachlogik, Verweis auf `CLAUDE.md`/Engineering-Baseline für Details. Fehlende `requirements.txt` als Folgepunkt identifiziert und inzwischen behoben (siehe unten) |
| LEGACY-001 | Ursprünglich als generischer Platzhalter „Legacy-/Kompatibilitätsschichten" angelegt, nie mit einem konkreten Fund gefüllt | P2 | **geprüft, kein konkretes Ziel gefunden** — kein Legacy-/Kompatibilitäts-Shim im Repo identifiziert, der nicht bereits unter einer eigenen ID (LEGACY-002/003/004) erfasst ist. Als reiner Sammel-Platzhalter ohne eigenen Befund geschlossen |
| LEGACY-002 | `FilenameFixerTool.organize_file`/`process_directory`/`fix_and_move_file` (`utils/filenamefixer.py`) haben bestätigt null Aufrufer in Produktionscode (nur `build_final_path`/`move_to_library` werden von `enhanced_metadata_processor.py` genutzt) — vermutlich Rest einer älteren, abgelösten Pipeline | P2 | **entfernt** — nach frischer Re-Verifikation (`getattr()`, Tests, String-Referenzen geprüft) alle 3 Methoden gelöscht. Dabei zusätzlich 3 Hilfsmethoden entfernt, die dadurch ihren einzigen Aufrufer verloren hatten: `_log_processing_stats()`, `_clean_directories()` und `_get_supported_audio_extensions()` (alle drei nur von `process_directory()` genutzt), sowie die dadurch verwaiste `FixerStats`-Dataclass und den ungenutzten `dataclass`-Import. Voller Regressionslauf danach: unverändert 15 Vorbestand-Fehler, 520 bestanden. Bei dieser Gelegenheit gefunden, aber bewusst nicht Teil dieses Fixes: `services/downloader/utils/metadata_utils.py` und die versteckte Datei `utils/.artist_if.py` haben seit dem Initial-Commit kaputte Imports (`from metadata import ...`, `from enhanced_logging import ...` — beide Module existieren nirgends im Repo) und werden selbst nirgends importiert; da nie geladen, kein aktives Risiko, aber totes/kaputtes Gepäck — als eigener Punkt für eine spätere Session vorgemerkt |
| LEGACY-005 | Bei LEGACY-002 und ARCH-001 nebenbei gefunden: 6 komplett tote/kaputte Dateien seit dem Initial-Commit, keine davon je importiert. `services/downloader/utils/metadata_utils.py` und `utils/.artist_if.py` (versteckt) hatten kaputte Imports (`from metadata import ...`, `from enhanced_logging import ...` — beide Module existieren nirgends). `handlers/command_integration.py` wurde nur von `handlers/legacy_handler_integration.py` importiert, das selbst 16 Zeilen lang und **syntaktisch ungültiges Python** ist (endet mit einem literalen Markdown-Codefence ` ``` `, vermutlich ein KI-generiertes Zwischenergebnis, das nie bereinigt wurde) und zusätzlich `handlers/statistik_handler.py` importiert — eine Datei, die es nie gab (der reale Name ist `handlers/mugge_statistik_handler.py`). `handlers/migration_system.py` und `scripts/migration_system.py` sind inhaltsgleiche (`diff` leer) einmalige Migrations-Skripte für die historische Umstellung auf `RichMenuSystem` — diese Migration ist in Produktion längst abgeschlossen (`bot.py` verdrahtet `RichMenuSystem`/`RichMenuHandler` heute direkt), ein erneuter Lauf würde mit veralteten Annahmen Dateien überschreiben (u. a. generierten die Skripte ursprünglich genau das jetzt gelöschte `command_integration.py`) | P2 | **entfernt** — alle 6 Dateien gelöscht (frisch re-verifiziert: keine Aufrufer, keine Tests, git-log zeigt „nie verändert seit Initial-Commit" für alle sechs). Zusätzlich einen dadurch verwaisten Import entfernt: `handlers/admin/user_management_handler.py:168` importierte `RichMenuSystem`/`MenuState` innerhalb `process_new_user_id()`, ohne sie zu benutzen. Voller Regressionslauf danach: unverändert 15 Vorbestand-Fehler, 520 bestanden |
| ARCH-001 | `DownloadHandler`, `RichMenuHandler`, `RichMenuSystem`, `EnhancedMetadataProcessor` sind laut CLAUDE.md §19 die vier großen Orchestrator-Risikobereiche (1251/1310/1942/1327 Zeilen) — vor jeder Aufteilung müssen erst Verantwortlichkeiten, öffentliche Schnittstellen und Aufrufer dokumentiert werden (Schritte 1–3) | P2 | **dokumentiert** — vollständige Analyse aller vier Klassen in [`docs/MusicBot_ARCH-001_Orchestrators.md`](MusicBot_ARCH-001_Orchestrators.md) (reine Analyse, kein Codeumbau). Kernergebnisse: alle vier haben bereits Testabdeckung (Schritt 4 erfüllt), sind im Kern Orchestratoren mit klar benannten Extraktionskandidaten (u. a. Telegram-Ergebnisformatierung in `DownloadHandler`, Workflow-State-Machine in `RichMenuHandler`, ein achtfach wiederholtes Präfix-Routing-Muster in `RichMenuSystem`, Tag-Schreiben in `EnhancedMetadataProcessor`) — Schritt 5 (tatsächliche Extraktion) bewusst nicht Teil dieses Punkts, jede Extraktion wäre ein eigener, einzeln zu genehmigender Schritt. Dabei mehrere neue Nebenbefunde dokumentiert (kaputte/tote Imports, tote Duplikate — siehe LEGACY-005, mehrere Kapselungsverletzungen zwischen den Orchestratoren und ihren Sub-Komponenten, weiterhin offen). Erster Extraktionsschritt umgesetzt: siehe ARCH-001-STEP-1 |
| ARCH-001-STEP-1 | Erster, risikoärmster Extraktionskandidat aus ARCH-001: Tag-Schreiben in `EnhancedMetadataProcessor` (`_write_metadata_to_file_with_lyrics`/`_write_genres_m4a`/`_write_genres_mp3`/`_extract_genre_parts`, ~188 Zeilen) war die einzige nicht in einen Sub-Prozessor ausgelagerte Fachlogik der Klasse | P2 | **umgesetzt** — neue Klasse `TagWriter` (`services/downloader/utils/metadata/tag_writer.py`), 1:1 identischer Code, nach dem etablierten Sub-Prozessor-Muster (siehe `AlbumProcessor`). In `EnhancedMetadataProcessor._do_init()` als `self.tag_writer` verdrahtet (Logger + `artist_normalizer` injiziert), einzige Aufrufstelle (`process_single_track`, Schritt 17) auf `self.tag_writer.write_tags(...)` umgestellt. Bewusste kleine Anpassung beim Extrahieren: `hasattr(self, "artist_normalizer")` (im Original strukturell immer `True`, da `artist_normalizer` in `_do_init` unbedingt gesetzt wird — totes Defensiv-Pattern) wurde zu `self.artist_normalizer is not None` (jetzt ein echter, aussagekräftiger Konstruktor-Parameter-Check), Verhalten in Produktion identisch. Verwaister `MP4Cover`-Import in `enhanced_metadata_processor.py` entfernt. 21 neue Unit-Tests in `tests/test_tag_writer.py` (Titel/Artist/Album/Jahr/Tracknummer, Genre-Kombination inkl. 3er-Cap, Feature-Artist-Normalisierung, Lyrics, Cover, fehlende Datei, unbekannte Extension, M4A-Graceful-Failure, `_extract_genre_parts` für Objekt/Dict/None), per `git stash -u` gegen den Vor-Extraktions-Stand als fehlschlagend (ModuleNotFoundError) verifiziert. Bestehender E2E-Test (`test_metadata_processor_happy_path.py`) weiterhin grün — deckt den Tag-Writer-Pfad jetzt indirekt UND direkt ab. Voller Regressionslauf: 541 bestanden (vorher 520), unverändert 15 Vorbestand-Fehler |
| ARCH-001-STEP-2 | Zweiter Extraktionskandidat aus ARCH-001: Telegram-Ergebnisformatierung in `DownloadHandler` (`_build_duplicate_message`, `_extract_genres_from_data`, `_collect_playlist_genres`, `_extract_stats_from_result`, `_send_final_summary`, Teil von `handle_playlist_success`, ~250 Zeilen) — weitgehend zustandslos, kaum `self`-Zugriff außer `status_msg`/`update` | P2 | **umgesetzt, mit einer bewussten Abweichung vom ursprünglichen ARCH-001-Vorschlag**: `handle_playlist_success()` wurde NICHT wortwörtlich komplett verschoben, weil sein erster Codepfad (`if results[0].get("type") == "playlist": await self.handle_single_track_success(...)`) auf eine echte Seiteneffekt-Methode delegiert (Duplikat-Cache-Registrierung via `self.duplicate_handler`) — das ist eine Business-Entscheidung, keine reine Formatierung, und wäre in einer separaten Reporter-Klasse nur ein Rückruf in die andere Richtung gewesen (mehr Kopplung statt weniger). Stattdessen: neue Klasse `DownloadResultReporter` (`services/downloader/utils/download_result_reporter.py`) enthält nur die reinen Formatierungs-/Versand-Methoden (`build_duplicate_message`, `extract_genres_from_data`, `collect_playlist_genres`, `extract_stats_from_result`, `send_final_summary`, `send_playlist_direct_summary` — Letztere ist der zweite, direkte Codepfad von `handle_playlist_success`, parametrisiert mit `update`/`status_msg` statt sie aus `self` zu lesen, da beide während der Pipeline mehrfach neu gesetzt werden). In `DownloadHandler.__init__` als `self.result_reporter` verdrahtet. `handle_playlist_success`/`handle_single_track_success` bleiben in `DownloadHandler`, delegieren aber jetzt an `self.result_reporter` statt eigene private Methoden zu haben — Duplikat-Registrierung und Kontrollfluss-Entscheidung (welcher Pfad?) bleiben dort. Verwaister `Counter`-Import entfernt. 27 neue Unit-Tests in `tests/test_download_result_reporter.py` (Genre-Extraktion aus allen Formaten, Playlist-Genre-Häufigkeit inkl. 4er-Cap, 3-stufiger Stats-Fallback, Duplikat-Nachricht pro Typ inkl. Pfad-Suffix-Bereinigung, Playlist-/Einzeltrack-Zusammenfassung inkl. Spotify-Podcast-Genre-Filterung und fehlendem `library_path`), per `git stash -u` gegen den Vor-Extraktions-Stand als fehlschlagend (ModuleNotFoundError) verifiziert. Bestehende Download-Tests (`test_download_url_validation.py` u. a.) weiterhin grün. Voller Regressionslauf: 568 bestanden (vorher 541), unverändert 15 Vorbestand-Fehler |

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
- [x] Legacy-Pfade in `FilenameFixerTool` dokumentiert, später entfernt (LEGACY-002)
- [x] GENRE-003 behoben (Hierarchie-Case-Bug + davon verdeckter None-Fallback-Bug in `get_main_genre`)
- [x] CACHE-001 behoben (`get_url_hash` auf YouTube-bewusste Normalisierung umgestellt)
- [x] GENRE-002 entschieden — keyword_rules/artist_rules als redundant zu genre_aliases.yaml/artist_genre.yaml identifiziert, 3 fehlende Artists migriert, title_rules bewusst nicht aktiviert (siehe Risikotabelle). Dabei DATA-001 gefunden (12 doppelte Keys in artist_genre.yaml) — offen, eigener Punkt
- [x] ARTIST-001 behoben — Schnittstellenänderung umgesetzt (`determine_best_artist` gibt Haupt-/Feature-Artist getrennt zurück), verifizierter Blast-Radius war ein einziger echter Aufrufer
- [x] TEST-003 behoben — Video-ID-Index als stabiler Zwischenschlüssel zwischen Check (roh) und Store (bereinigt), siehe Risikotabelle

### Phase 3 — Download-Pipeline (Event-Loop, URL-Allowlist, Ressourcen-Limits)
- [x] REL-004 behoben — Event-Loop-Blockierung durch synchrone `extract_info()`-Aufrufe in `async def`-Funktionen, neue `extract_info_async()` via `run_in_executor`
- [x] SEC-004 behoben — Domain-Allowlist (`_is_supported_download_url()`) vor yt-dlp-Weiterleitung, schützt gegen SSRF-artiges Risiko und Domain-Confusion
- [x] REL-005 behoben — `MAX_PLAYLIST_ITEMS`/`MAX_CONCURRENT_DOWNLOADS`/`MAX_DURATION` erstmals tatsächlich durchgesetzt (Playlist-Trunkierung, Modul-Level-Semaphore, echter yt-dlp-`match_filter` mit Podcast-Ausnahme)
- [x] TEST-005 behoben — 18 Characterization-Tests für alle produktiv genutzten `NavidromeAPI`-Methoden, 8 tote Methoden als LEGACY-003 dokumentiert, später entfernt
- [x] TEST-006 behoben — 25 Characterization-Tests für `MusicBrainzClient` (P0, vorher 0 Tests)
- [x] BUG-001 behoben — echte Track-Position statt Medium-Gesamtanzahl, live gegen musicbrainz.org verifiziert
- [x] BUG-002 behoben — release-group-Daten (Tags/Titel) überlebten die zweite `get_recording_by_id()`-Abfrage nicht mehr, MusicBrainz-Tag-basierte Genre-Erkennung war dadurch faktisch tot
- [x] DATA-001 behoben — 12 doppelte Keys in `artist_genre.yaml` bereinigt
- [x] DATA-002 behoben — 22 doppelte Keys in `genre_hierarchy.yaml`/`genre_overrides.yaml`/`genre_aliases.yaml` bereinigt, 3 echte Klassifizierungskonflikte per Nutzer-Entscheidung aufgelöst
- [x] TEST-007 behoben — 12 Characterization-Tests für `LastFMClient` (P1, vorher 0 Tests)
- [x] BUG-003 behoben — `CoverProcessor`-Early-Exit-Schwelle war unerreichbar (170 > max. möglichem Score 150)
- [x] BUG-004 behoben — `SpotifyDownloader` wählte bei parallelen Downloads potenziell die falsche Datei (P0, geteiltes Download-Verzeichnis mit der YouTube-Pipeline)
- [x] TEST-008 behoben — 21 Characterization-Tests für `SpotifyDownloader` (P1, vorher 0 Tests)
- [x] CFG-001 behoben (teilweise) — redundanter hartcodierter `.env`-Pfad entfernt, LEGACY-004 dokumentiert
- [x] DOC-001 behoben — README neu geschrieben
- [x] SEC-005 behoben — Admin-zu-Owner-Eskalation in `set_user_role()`, direkte Fortsetzung von SEC-003
- [x] TEST-009 behoben — 27 Characterization-Tests für `UserManagementHandler` (P1, vorher 0 dedizierte Tests)

### P1
- [x] Config Side Effects untersucht — CFG-001 teilweise behoben (redundanter hartcodierter Pfad entfernt), LEGACY-004 (drei tote Init-Methoden) dokumentiert
- [x] Cache-Verträge dokumentieren — Metadata-/Duplicate-/Lyrics-/History-Cache jetzt alle charakterisiert (siehe TEST-003/TEST-004/`test_statistik_service.py`)
- [x] externe Adapter inventarisieren — Navidrome (TEST-005), Genius (REL-002), MusicBrainz (TEST-006), Last.fm (TEST-007), Cover-Netzwerk/Fanart (BUG-003), Spotify-Downloader (TEST-008/BUG-004) jetzt alle charakterisiert
- [x] Download-Pipelines testen — Event-Loop-Blockierung, URL-Allowlist, Ressourcen-Limits (siehe Phase 3 oben)
- [x] Navidrome Integration testen — siehe TEST-005
- [x] Telegram-Handler-Layer testen — vollständig: `UserManagementHandler` (TEST-009/SEC-005), `BackupHandler` (TEST-010/SEC-006), `rich_menu_system.py` (TEST-011), `enhanced_error_handler.py` (BUG-005), `rich_menu_handler.py` (BUG-006), `navidrome_menu_handler.py` (BUG-007), `enhanced_status_handler.py`/`mugge_statistik_handler.py` (TEST-012)
- [x] DATA-003 behoben — verbleibende 10 Mapping-Dateien auf Duplikate geprüft (keine gefunden), Duplicate-Key-Guard generisch auf alle `mapping/*.yaml`/`*.json`-Dateien ausgeweitet (automatisch, auch für künftige neue Dateien)
- [x] LEGACY-001 geprüft — reiner Sammel-Platzhalter ohne eigenen Befund, geschlossen
- [x] LEGACY-002 behoben — 3 tote `FilenameFixerTool`-Methoden entfernt, inkl. 3 dadurch verwaister Hilfsmethoden und `FixerStats`
- [x] LEGACY-003 behoben — 8 tote `NavidromeAPI`-Methoden entfernt
- [x] requirements.txt angelegt — 22 Third-Party-Pakete aus tatsächlichen Produktionscode-Imports ermittelt (Agent-gestützte Analyse, gegen `pip freeze` verifiziert), README-Setup-Abschnitt entsprechend aktualisiert

### P2
- [x] Legacy reduzieren — LEGACY-001/002/003 abgeschlossen (siehe P1-Block oben), LEGACY-004 (`Config`) bewusst weiterhin nur dokumentiert (siehe eigener Eintrag: Verzeichnis-Anlage-Logik dort, Entfernen wäre riskanter als bei den reinen Lesefunktionen in LEGACY-002/003)
- [x] ARCH-001 behoben (Analyse-Teil) — alle vier großen Orchestratoren dokumentiert (Verantwortlichkeiten/Schnittstellen/Aufrufer), siehe [`docs/MusicBot_ARCH-001_Orchestrators.md`](MusicBot_ARCH-001_Orchestrators.md)
- [x] LEGACY-005 behoben — 6 tote/kaputte Dateien entfernt, die bei LEGACY-002/ARCH-001 nebenbei gefunden wurden (`metadata_utils.py`, `.artist_if.py`, `command_integration.py`, `legacy_handler_integration.py`, 2× `migration_system.py`)
- [x] ARCH-001-STEP-1 behoben — Tag-Schreiben aus `EnhancedMetadataProcessor` in eigene `TagWriter`-Klasse extrahiert, 21 neue Tests
- [x] ARCH-001-STEP-2 behoben — Telegram-Ergebnisformatierung aus `DownloadHandler` in eigene `DownloadResultReporter`-Klasse extrahiert, 27 neue Tests
- [x] ARCH-001-STEP-3 behoben — Workflow-Dispatch/Cancel-Erkennung aus `RichMenuHandler` in eigene `TextWorkflowDispatcher`-Klasse extrahiert, 17 neue Tests, BUG-006-Regressionsschutz bestätigt intakt
- [x] `CallbackRouter`-Abstraktion für `RichMenuSystem` bewusst NICHT umgesetzt (explizite Nutzer-Entscheidung) — anders als STEP-1/2/3 wäre das keine 1:1-Verschiebung, sondern eine neue Architektur-Entscheidung in der sicherheitskritischsten Datei des Projekts (SEC-003/SEC-005/SEC-006) ohne konkreten Treiber; bleibt in `docs/MusicBot_ARCH-001_Orchestrators.md` als Vorschlag dokumentiert
- [x] ENCAP-001 behoben (2 von 3 Fällen) — `RichMenuSystem.add_child_menu_item()` und `EnhancedMetadataProcessor.aclose()` ersetzen zwei der drei dokumentierten Kapselungsverletzungen, 9 neue Tests; verwaiste `genre_processor.py.blak` entfernt
- [x] AUTOLEARN-001 behoben — Auto-Learning-Gate erkennt jetzt die vollständige `special_channel.yaml`-Konfiguration statt nur 2 hartcodierter Kanalnamen; echter Fehl-Lern-Fall für Sonderkanäle behoben, nicht nur die Doppelung entfernt. 4 neue Tests
- [x] ARTISTNORM-001 behoben — `ArtistNormalizer.normalize()`/`_normalize_collaboration()` matchen "feat"/"ft" jetzt nur noch mit Wortgrenzen, 6 neue Tests
- [x] ARTISTNORM-002 behoben — `title_cleaner.py`/`models.py::split_main_and_featuring` auf Wortgrenzen umgestellt, `youtube_parser.py`/`organizer.py` als strukturell sicher bestätigt (kein Fix nötig), 14 neue Tests
- [x] LEGACY-007 behoben — verstecktes totes Verzeichnis `handlers/.buttons/` + `services/commands_services.py` entfernt (systematische Ungetestet-Prüfung aller Quelldateien gegen Testreferenzen)
- [ ] Zielarchitektur schrittweise umsetzen

---

## Leitprinzip

> **Erst verstehen → dann testen → dann verbessern.**

Der MusicBot wird nicht neu geschrieben.

Er wird kontrolliert weiterentwickelt.
