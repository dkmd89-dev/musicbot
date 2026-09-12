# MUSICBOT — FULL PROJECT ARCHITECTURE AUDIT

**Datum:** 2026-09-12
**Repository:** dkmd89-dev/musicbot
**Commit:** `3e136b1` (main)
**Modus:** Read-only Vollaudit — keine Produktionsdateien, Tests, Konfigurationen oder Dokumentationen wurden verändert.
**Methodik:** Vier parallele, unabhängige Recherche-Durchläufe (Architektur/Dependencies/Handler/Services; Telegram-Menü-System; Metadata/Artist/Genre/ReplayGain/Duplicate/Cache/LibraryHealth; Concurrency/Tests/Security/DeadCode/Docs), anschließend zusammengeführt. Jeder Durchlauf nutzte Read/Grep/AST-Analyse sowie nicht-invasive Verifikationsbefehle (`pytest --collect-only`, `python -m compileall`, gezielte grep/AST-Suchen). Die volle Testsuite wurde bewusst **nicht** ausgeführt (CLAUDE.md §8.A — das bleibt dem Nutzer vorbehalten).

---

## Nachtrag (2026-09-12): TGPERM-001 behoben

Der einzige P1-Befund dieses Audits (**TGPERM-001**, Abschnitt 5/6/27) wurde noch am selben Tag im Anschluss an dieses Audit behoben. Die ursprüngliche Analyse unten bleibt unverändert als Ist-Zustand-Dokumentation zum Auditzeitpunkt stehen; dieser Nachtrag beschreibt den Fix.

**Änderungen:**
- `handlers/menu/rich_menu_system.py`: die 7 Logger-MenuItems (`logger_main_menu`, `logger_modules_list`, `logger_global_level`, `logger_files_list`, `logger_global_stats`, `logger_handlers_list`, `logger_cleanup_menu`) erhalten jetzt explizites `callback_data="logger_<id>"` statt der automatischen `"menu:<id>"`-Generierung — sie routen damit über den bereits vorhandenen, in `_ADMIN_ONLY_PREFIXES` gegateten `logger_`-Präfixpfad (`_handle_logger_callback()`s `routing_map` kannte dieselben IDs bereits, war aber durch die falsche `callback_data` unerreichbar). Die dadurch obsolet gewordenen 7 `_handle_logger_*`-Wrapper-Methoden wurden entfernt.
- `handlers/test_menu_handler.py`: `TestMenuHandler._execute_test_run()` (gemeinsamer Einstiegspunkt von `run_unit_tests`/`run_integration_tests`/`run_performance_tests`) prüft jetzt per neuer `_is_admin()`-Methode Admin-/Owner-Rechte, bevor ein Testlauf gestartet wird — Defense-in-Depth-Muster analog zu `RichMenuHandler._handle_user_management_wrapper`/`_handle_view_logs`/`_handle_navidrome_scan`, die aus demselben strukturellen Grund (kein gegateter Präfix für diese IDs) bereits einen eigenen Check besitzen.
- `tests/test_rich_menu_access_control.py`: `ADMIN_ONLY_CALLBACKS` um die restlichen 6 Logger-IDs erweitert; neue Klasse `TestPrivilegedMenuItemsAreGatedTGPERM001` iteriert die tatsächliche Menu-Registry und schlägt fehl, sobald ein zukünftiges Admin-/Owner-MenuItem mit Handler weder über einen gegateten Präfix noch über die explizite Ausnahmeliste (`_KNOWN_INTERNALLY_GATED_MENU_IDS`) abgesichert ist — verallgemeinert den Fund über die konkret gefundenen 10 Items hinaus.
- `tests/test_test_menu_handler.py`: neue Klasse `TestExecuteTestRunAdminPermissionTGPERM001` (Non-Admin wird abgelehnt/kein Testlauf startet; Owner/Admin werden durchgelassen).
- `tests/test_test_menu_handler_error_handler.py`, `tests/test_test_menu_handler_event_loop_blocking.py`: `make_handler()` macht den Standard-Test-Handler permissiv (`_is_admin` gepatcht), da diese Dateien andere Aspekte testen und durch den neuen Check sonst alle betroffenen Tests bei fehlender Admin-Konfiguration fehlschlagen würden.

**Verifikation:**
- Pre-Fix-Diskriminierung via `git stash` bestätigt: 3 neue Tests (`TestPrivilegedMenuItemsAreGatedTGPERM001::test_every_privileged_action_item_is_gated`, `TestExecuteTestRunAdminPermissionTGPERM001::test_non_admin_is_rejected_with_permission_denied`, `::test_non_admin_never_starts_a_test_run`) schlagen gegen den ungefixten Code fehl, wie erwartet.
- Gezielte Tests nach Fix: `tests/test_rich_menu_access_control.py` + `tests/test_test_menu_handler.py` — 67/67 grün.
- Thematische Suite: `tests/test_rich_menu*.py tests/test_test_menu_handler*.py tests/test_enhanced_logger_menu*.py tests/test_user_management_handler.py` — 324/324 grün. Erweitert um Navidrome/Maintenance/Family: 513/513 grün.
- `python3 -m compileall -q .` — keine Fehler.
- Vollständige Testsuite wurde bewusst **nicht** ausgeführt (CLAUDE.md §8.A) — dem Nutzer zur Verifikation empfohlen.
- `docs/FINDINGS_INDEX.md` als TGPERM-001 CLOSED (2026-09-12) nachgetragen.

Damit ändert sich das Gesamtverdikt in Abschnitt 32 von „NEEDS TARGETED FIXES" zu **„PRODUCTION READY WITH MINOR DEBT"** (nur noch P2/P3/Accepted-Risk-Punkte offen, siehe aktualisierte Abschnitte 27/31/32 unten).

---

## 1. Executive Summary

Das Projekt ist in den bereits mehrfach charakterisierten Kernbereichen (Metadata-Pipeline, Artist Identity, Genre, ReplayGain, Duplicate Detection, Library Health/Repair, Concurrency) **auffällig reif und diszipliniert**: durchgängig mit Regressionstests für historisch behobene Bugs abgesichert, saubere Schichtgrenzen (teils automatisiert per `test_services_layer_boundary.py` erzwungen), keine Shell-Injection-Risiken, korrektes Secrets-Handling, disziplinierte Concurrency-Behandlung mit sichtbarer Event-Loop-Blocking-Fix-Historie.

Der eine substanzielle Neufund liegt im **Telegram-Berechtigungssystem**: Ein systematischer Lücken-Typ (fehlendes `callback_data`-Override beim generischen Menü-Dispatch) macht 10 eigentlich admin-only Menüpunkte (7× Logger-Verwaltung, 3× Test-System) für jeden Bot-Nutzer ohne jede Berechtigungsprüfung erreichbar — inklusive eines potenziellen DoS-Vektors (bis zu 900s-Testlauf) auf einer laut Projekt-Memory bereits speicherbeschränkten Entwicklungsmaschine (7,7 GB RAM, oft volle 4 GB Swap). Der existierende Regressionstest für exakt diese Fehlerklasse (`test_rich_menu_access_control.py`, ursprünglich für SEC-003 geschrieben) testet einen falschen String und erzeugt dadurch ein falsches Sicherheitsgefühl.

Alle übrigen Funde sind P2/P3 oder als bereits akzeptierte/dokumentierte Ausnahmen bestätigt. Keine P0-Befunde.

---

## 2. Current Architecture

```text
Telegram Update
    ↓
bot.py (Entry Point, async_main, Signal-Handling)
    ↓
RichMenuHandler (handlers/menu/rich_menu_handler.py)
    ↓
RichMenuSystem.handle_callback() (handlers/menu/rich_menu_system.py)
    ↓
Prefix-Dispatch:
    ^dl: / ^backup_ / ^maint: / ^reprocess: / ^doctor: / ^review: / ^repair: /
    ^erradmin: / ^status_ / ^dup: / ^usermgmt_ / ^nav_  → jeweils eigener,
    dedizierter Dispatcher mit eigenem Berechtigungscheck (Defense-in-Depth)
    ODER
    ^menu:<id>  → generischer Fallback, ruft menu_item.handler(update, context)
                  OHNE zentrale Berechtigungsprüfung außerhalb der
                  _ADMIN_ONLY_PREFIXES-Liste
    ↓
Zielmethode (Handler-Klasse: EnhancedLoggerMenuHandler, TestMenuHandler,
    FamilyStatsHandler, FamilyChatHandler, FamilyChallengeHandler,
    NavidromeMenuHandler, UserManagementHandler, BackupHandler,
    BotRestartHandler, DownloadHandler (klassen/) u.a.)
    ↓
Services (services/*) → services/clients/* (externe APIs: MusicBrainz,
    Genius, Last.fm, Navidrome) | utils/* (lokale Subprozesse: ffmpeg,
    rsgain, Navidrome-Scan-Trigger)
    ↓
Filesystem / Library / Navidrome
```

Dies entspricht der in CLAUDE.md §4 und `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md` dokumentierten Architektur — **verifiziert, kein Architecture Drift auf Systemebene**. Die einzige Abweichung liegt nicht in der Architektur selbst, sondern in einer unvollständigen Instanz-Konfiguration innerhalb des sonst korrekten Musters (siehe TGPERM-001, Abschnitt 5/6).

---

## 3. Architecture Verdict

Die Schichtgrenzen aus CLAUDE.md §4 werden eingehalten:

- Kein `telegram`-Import in `services/` außer der dokumentierten `klassen/`-Ausnahme (repoweit verifiziert, 0 Treffer).
- `services/clients/` enthält ausschließlich echte externe Netzwerk-Adapter (`genius_client.py`, `lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py`).
- `utils/` enthält ausschließlich lokale Subprozess-/Cache-Module ohne Netzwerk-Bibliotheken.
- Automatisierter Regressionsschutz existiert bereits (`tests/test_services_layer_boundary.py`, AST-basiert).

Bekannte, dokumentierte Ausnahmen (`klassen/download_handler.py`, `dl:`-Präfix ohne zentrales Gate, `CoverProcessor` mit direkten HTTP-Calls statt `services/clients/`) sind sachlich weiterhin gerechtfertigt und wurden in diesem Audit erneut verifiziert statt blind übernommen.

Der einzige Bruch mit der dokumentierten Absicht ist **TGPERM-001** — eine Instanz derselben Fehlerklasse, die `SEC-003` bereits einmal für andere Präfixe behoben hat, hier aber unvollständig auf neue Menüpunkte (Logger, Test-System) angewendet wurde.

**Gesamtverdikt: NEEDS TARGETED FIXES** (nicht "production ready", aber auch keine strukturellen Architekturänderungen nötig — ein gezielter, klar umrissener Fix genügt).

---

## 4. Layer & Dependency Analysis

**Architekturkarte (verifiziert):** `bot.py` → `handlers/menu/rich_menu_handler.py` (`RichMenuHandler`) → `handlers/menu/rich_menu_system.py` (`RichMenuSystem`) + `klassen/download_handler.py` (`DownloadHandler`) → `services/*` (Orchestrierung) → `services/clients/*` (externe APIs) / `utils/*` (lokale Subprozesse).

**Schichtgrenzen-Verifikation (AST/grep-basiert):**
- Kein `telegram`-Import in `services/` außer der dokumentierten Ausnahme `klassen/` — bestätigt.
- Ein Treffer für den String `"telegram"` in `services/clients/navidrome_api.py:93` ist ein Subsonic-API-Client-Identifier (`"c": "telegram-bot"`), kein Import — kein Verstoß, False-Positive vermieden.
- `services/metadata/cover_processor.py` macht direkte `requests`-HTTP-Aufrufe (CoverArtArchive/Fanart/Apple/Deezer) statt über `services/clients/`. **Kein neuer Befund**: bereits geprüft und bewusst geschlossen unter `docs/FINDINGS_INDEX.md` (MIG-04, CLOSED 2026-09-02) — CoverProcessor ist kein „reiner Client" (Scoring+Cache+6-Quellen-Orchestrierung). **ACCEPTED ARCHITECTURAL EXCEPTION**, hier nur bestätigt.
- `services/metadata ↔ services/downloader` Kreuzimport besteht beidseitig, ist aber kein echter Zyklus (Laufzeit-Import erfolgreich, referenzierte Blätter zeigen nicht gegenseitig aufeinander). Bereits in `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md:539` dokumentiert. **Kein neuer Befund.**
- Automatisierter Regressionsschutz: `tests/test_services_layer_boundary.py` (AST-basiert, verhindert `services/` → `handlers`/`klassen`/`telegram`), siehe `docs/FINDINGS_INDEX.md` MIG-06 CLOSED.
- `utils/` enthält ausschließlich lokale Subprozess-/Cache-Module (`navidrome_scan_trigger.py`, `audio_enhancer.py`, `bot_restart_trigger.py`) ohne `requests`/`httpx`/`aiohttp` — korrekt gemäß §4.

**God-Module (Zeilenzahl, `wc -l`):** `handlers/menu/rich_menu_system.py` (3266), `handlers/enhanced_error_handler.py` (1995), `services/library_repair/executor.py` (1748), `handlers/enhanced_logger_menu_handler.py` (1711), `handlers/menu/rich_menu_handler.py` (1597), `klassen/download_handler.py` (1162). Alle vier größten sind **explizit in CLAUDE.md §19 als bekannte Risikobereiche gelistet** — kein neuer Befund, sondern bestätigte Ist-Aufnahme.

**Globaler State:** `SingletonMixin` (`utils/singleton.py`) wird von `EnhancedMetadataProcessor`, `EnhancedDownloadProcessor` genutzt — dokumentiert als bewusst. `ActiveDownloadRegistry` (`services/downloader/active_downloads.py`) ist die einzige echte prozessweite mutable Registry außerhalb von Caches — vorbildlich dokumentiert: `threading.Lock` schützt das Dict, `threading.Event` statt `asyncio.Event` bewusst gewählt wegen Executor-Thread-Callback von yt-dlp (ausführlich im Docstring begründet). Keine Race-Condition-Evidenz. Einziger loser Modul-Cache: `services/metadata/cover_processor.py:120` `_IMAGE_HASH_CACHE = {}` (unbounded, bereits in `MusicBot_ARCHITECTURE_EVOLUTION.md` als „REGENERABLE STATE" bewertet).

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| DEP-001 | P3 | Dependency | Ungenutzter `import requests` (kein weiterer Treffer im File) | `services/metadata/enhanced_metadata_processor.py:6` | Keiner (funktional folgenlos), leichte Verwirrung beim Lesen | Bei nächster Bearbeitung entfernen |
| DEP-002 | P3 | Naming | Nested Package `services/downloader/download/` unter `services/downloader/` — redundante Namensverschachtelung | `services/downloader/download/__init__.py` | Kein Funktionsrisiko, verwirrende Modulpfade | Kosmetisch, kein Handlungsbedarf ohne größeren Umbau |

---

## 5. Telegram Menu Audit

**Dokumentationsstatus:** `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md` ist **CURRENT/LIVING** und ungewöhnlich präzise — inklusive expliziter Bug-Historie (A–D). Der dokumentierte Architekturfluss stimmt **exakt** mit dem Code überein — verifiziert an `handlers/menu/rich_menu_handler.py::get_telegram_handlers()` (17 `CallbackQueryHandler` + 2 `CommandHandler` + 2 `MessageHandler`) und `RichMenuSystem.handle_callback()` (zentraler Präfix-Dispatch, `rich_menu_system.py:1990-2149`).

**Menübaum:** vollständig mit Doku deckungsgleich (Downloads, Statistiken inkl. Familien-Statistik, Familien-Chat, Familien-Challenge, Administration mit 5 Top-Level-Gruppen, Navidrome Mediathek, Test-System als eigenständiges Root-Menü). Keine dokumentierten-aber-fehlenden oder implementierten-aber-undokumentierten Zweige gefunden.

**`_ADMIN_ONLY_PREFIXES`/`dl:`-Ausnahme:** Doku-Aussage korrekt umgesetzt. `_ADMIN_ONLY_PREFIXES = ("logger_", "usermgmt_", "dup:", "backup_", "status_")` (`rich_menu_system.py:2037`). `erradmin:`/`restart:`/`maint:`/`reprocess:`/`doctor:`/`review:`/`repair:` haben nachweislich jeweils eigene Admin-/Owner-Checks in ihren Dispatchern (Defense-in-Depth, verifiziert für alle sieben). `dl:` ist tatsächlich ungegatet, aber korrekt und sicher: jede `dl:*`-Aktion skopiert ausschließlich über `chat_id = update.effective_chat.id` (serverseitig aus dem echten Update, nicht aus `callback_data`) — kein Cross-User-Zugriff auf fremde Downloads möglich. **ACCEPTED ARCHITECTURAL EXCEPTION, korrekt implementiert.**

**Family Hub (F1–F5):** Berechtigungsmodell wie dokumentiert — `family_id` wird nie aus Callback-Daten übernommen, jede öffentliche `handle_*`-Methode in allen drei Handlern prüft `FamilyService.is_active_family_member()` vor Datenzugriff; die beiden zweistufigen Text-Workflows (`process_pending_message`, `process_pending_answer`) verlassen sich zusätzlich auf einen zweiten Check auf Service-Ebene, nicht nur auf das `pending_*`-Set. **Korrekt, wie dokumentiert.**

### 🔴 Kritischer Befund: TGPERM-001 — Routing-Lücke bei automatisch generiertem `callback_data`

Die zentrale `_ADMIN_ONLY_PREFIXES`-Prüfung (`rich_menu_system.py:2038`) greift nur bei `callback_data.startswith(...)`. `MenuItem.__post_init__()` generiert `callback_data` automatisch als `f"menu:{id}"`, **außer** ein Menüpunkt setzt explizit ein eigenes `callback_data` (Muster, das `backup_main`, `status_menu`, `restart:show`, `doctor:scan` etc. korrekt nutzen, um in ihre jeweils gegateten Dispatcher zu routen). Für **10 Menüpunkte** wurde dieses Muster nicht angewendet — sie tragen `access_level=AccessLevel.ADMIN`, haben einen `handler=`, aber **kein** explizites `callback_data`:

- **Logger-Verwaltung (7):** `logger_main_menu`, `logger_modules_list`, `logger_global_level`, `logger_files_list`, `logger_global_stats`, `logger_handlers_list`, `logger_cleanup_menu` (`rich_menu_system.py:776-836`)
- **Test-System (3):** `test_unit`, `test_integration`, `test_performance` (`rich_menu_system.py:1017-1049`, Handler via `register_handler()` in `rich_menu_handler.py:568-580`)

Ihr tatsächliches `callback_data` ist `menu:logger_main_menu`, `menu:test_unit` usw. — beginnt mit `"menu:"`, nicht mit `"logger_"`/keinem Admin-Präfix. Der generische `menu:`-Zweig (`rich_menu_system.py:2126-2149`) ruft `menu_item.handler(update, context)` **ohne jede Zugriffsprüfung** auf. Die jeweiligen Zielmethoden (`_handle_logger_main_menu` etc. → `EnhancedLoggerMenuHandler.show_*`; `TestMenuHandler.run_unit_tests`/`run_integration_tests`/`run_performance_tests`) haben **keinen eigenen Admin-Check** (verifiziert per Volltext-Lesung beider Dateien).

**Konkreter, nicht-theoretischer Beweis für die Lücke:** Der existierende Regressionstest für genau diese Fund-Klasse (SEC-003, `tests/test_rich_menu_access_control.py`) testet `callback_data="logger_main_menu"` (Zeile 77) — die literale ID, **nicht** das tatsächlich vom Button gesendete `"menu:logger_main_menu"`. Der Test besteht deshalb, obwohl die reale Route ungeschützt ist — ein Fall von **Test verifiziert falschen String, erzeugt falsches Sicherheitsgefühl**.

**Auswirkung:** jeder Bot-Nutzer (kein Admin, kein Owner nötig) kann per manuell gesendetem `callback_data="menu:logger_main_menu"` (oder jede der anderen 9 IDs) auf: Logger-Übersicht, Modul-Liste (inkl. Toggle-fähiger Folgebuttons, die selbst korrekt mit `logger_`-Präfix gegatet sind — aber der Einstieg nicht), globales Log-Level ändern (hebelt denselben SEC-001-Schutz aus, den SEC-003 explizit für andere Wege bereits verhindert hat), Log-Dateien einsehen/herunterladen, Handler-Verwaltung, Bereinigung — sowie einen vollständigen Unit-/Integration-/Performance-Testlauf (bis zu 900 s Subprozess, `subprocess.run` via `asyncio.to_thread`) auslösen. Auf einer speicherbeschränkten Entwicklungsmaschine (siehe Projekt-Memory: 7,7 GB RAM + oft volle 4 GB Swap) ist Letzteres ein reales DoS-Risiko, nicht nur theoretisch.

**Klassifikation:** CODE BUG / ARCHITECTURE BUG (Wiederholung derselben Fehlerklasse, die SEC-003 bereits einmal für andere Präfixe behoben hat) — **kein** Documentation Drift, da die Doku diesen Fall nicht behauptet, und **keine** akzeptierte Ausnahme (im Gegensatz zu `dl:`/`nav_`, die bewusst und korrekt ungegatet sind).

---

## 6. Telegram Callback Matrix

Status-Legende: OK = korrekt geroutet + gegatet · GATED-OWN = kein zentrales Gate, aber korrekter eigener Check · **BROKEN-PERM** = erreichbar ohne Berechtigungsprüfung trotz ADMIN/OWNER-`access_level` · UNUSED = im Baum, UI-unerreichbar, aber harmlos.

| Menu | Label | callback_data | PTB pattern | Dispatcher | Target method | Permission | Tested | Status |
|---|---|---|---|---|---|---|---|---|
| Downloads | Download-Einstieg | `menu:download` | `^menu:` | `handle_callback`→handler | `_handle_download_menu` | USER | `test_rich_menu_download_control_center.py` (28) | OK |
| Downloads | Neuer/Aktiv/Details/Abbrechen/Verlauf/Retry | `dl:new/active/details/cancel/history/retry:<n>` | `^dl:` | `_handle_download_control_callback` | `_handle_download_*` | keine (bewusst, chat_id-skopiert) | s.o. + `test_active_download_registry.py`, `test_download_history_store.py` | OK (ACCEPTED EXCEPTION) |
| Downloads (legacy) | Einzelner Track/Playlist | `menu:download_single`/`download_playlist` | `^menu:` | generisch | `_handle_download_single_wrapper` etc. | USER | keine gezielten | UNUSED (dokumentiert, harmlos) |
| Statistik | Monat/Jahr/Top Songs/Top Artists/Timeline | `menu:stats_*` | `^menu:` | generisch | `_handle_*_stats_wrapper` | USER | `test_rich_menu_handler.py` | OK |
| Statistik | Library Übersicht | `menu:stats_library` | `^menu:` | generisch | (Navidrome-Handler-Delegation) | USER | ungeprüft | UNCERTAIN |
| Familien-Statistik | Top Songs/Artists/Person/Champion/Hörzeiten/Trend | `menu:family_stats_*` | `^menu:` | generisch | `_handle_family_stats_*`→`FamilyStatsHandler.handle_*` | USER + service-seitige `is_active_family_member()` | `test_family_stats_handler.py` (10) | OK |
| Familien-Chat | Senden/Letzte/Notifications | `menu:family_chat_*` | `^menu:` | generisch | `FamilyChatHandler.handle_*` | USER + Membership-Gate | `test_family_chat_handler.py` (13) | OK |
| Familien-Challenge | Heute/Antworten/Punktestand | `menu:family_challenge_*` | `^menu:` | generisch | `FamilyChallengeHandler.handle_*` | USER + Membership-Gate | `test_family_challenge_handler.py` (13) | OK |
| Admin | Benutzerverwaltung | `menu:admin_users` | `^menu:` | generisch | `_handle_user_management_wrapper` | ADMIN (eigener `_is_admin`-Check) | vorhanden | OK |
| Admin | System-Logs | `menu:admin_logs` | `^menu:` | generisch | `_handle_view_logs` | ADMIN (eigener Check) | vorhanden | OK |
| Admin | Navidrome Scan | `menu:admin_navidrome` | `^menu:` | generisch | `_handle_navidrome_scan` | ADMIN (eigener Check) | vorhanden | OK |
| Admin | System-Status | `status_menu` (explizit) | `^status_` | `_handle_status_callback` | `_handle_status_menu` | ADMIN zentral | `test_rich_menu_access_control.py` | OK |
| Admin | Duplikate (Stats/Cache leeren) | `dup:show_stats`/`dup:clear_cache_confirm` | `^dup:` | `_handle_duplicate_callback` | — | ADMIN zentral | vorhanden | OK |
| Admin | Error-Verwaltung (4 Aktionen) | `erradmin:*` | `^erradmin:` | `_handle_error_admin_callback` | `error_admin_interface.*` | ADMIN eigener Check | ungeprüft | OK (Pattern korrekt) |
| Admin | **Logger-Übersicht/Module/Level/Dateien/Stats/Handler/Bereinigung (7)** | `menu:logger_main_menu` u. 6 weitere | `^menu:` | generisch | `_handle_logger_*`→`EnhancedLoggerMenuHandler.show_*` | **KEINE** (ADMIN nur als Metadatum, nicht durchgesetzt) | `test_rich_menu_access_control.py` testet falschen String | **BROKEN-PERM** |
| Admin | Backup-Übersicht/Bot sichern/Lib sichern/Listen (5) | `backup_main` u.a. (explizit) | `^backup_` | `_handle_backup_callback` | `_handle_backup_*` | ADMIN zentral | vorhanden | OK |
| Admin | Bot neu starten | `restart:show` (explizit) | `^restart:` | `_handle_restart_callback` | `restart_handler.*` | ADMIN eigener Check | vorhanden | OK |
| Admin | Wartungsmodus | `maint:show`/`maint:toggle` | `^maint:` | `_handle_maintenance_callback` | `_handle_maintenance_*` | ADMIN eigener Check | `test_rich_menu_maintenance_mode.py` (11) | OK |
| Admin | Reprocessing | `reprocess:show/pick:<n>/live:<n>` | `^reprocess:` | `_handle_reprocessing_callback` | `reprocessing_handler.*` | **OWNER** eigener Check | `test_rich_menu_reprocessing.py` (8) | OK |
| Admin | MusicBot Doctor | `doctor:scan/apply_safe/apply_safe_confirm` | `^doctor:` | `_handle_doctor_callback` | `doctor_handler.*` | ADMIN eigener Check | ungeprüft | OK (Pattern korrekt) |
| Admin | Library Health Review (12 Sub-Aktionen) | `review:*` | `^review:` | `_handle_review_callback` | `review_handler.*` | ADMIN eigener Check | ungeprüft | OK (Pattern korrekt) |
| Admin | Repair MusicBot (8 Sub-Aktionen) | `repair:*` | `^repair:` | `_handle_repair_callback` | `repair_handler.*` | ADMIN eigener Check | ungeprüft | OK (Pattern korrekt) |
| Test-System | **Unit/Integration/Performance ausführen (3)** | `menu:test_unit`/`test_integration`/`test_performance` | `^menu:` | generisch | `TestMenuHandler.run_*_tests` | **KEINE** | keine (nicht in `ADMIN_ONLY_CALLBACKS` enthalten) | **BROKEN-PERM** |
| Navidrome | Browse/Suche/Playlists/Favoriten/Stats | `nav_*` | `^nav_` | `_handle_navidrome_callback` | `navidrome_handler.*` | bewusst ungegated (reines Browsing) | `test_rich_menu_access_control.py::NON_ADMIN_GATED_CALLBACKS` | OK (ACCEPTED EXCEPTION) |
| Benutzerverwaltung | Liste/Detail/Rolle/Löschen/Rechte/Bann | `usermgmt_*` | `^usermgmt_` | `_handle_usermgmt_callback` | `user_mgmt_handler.*` | ADMIN zentral | `test_rich_menu_access_control.py` (Self-Promotion-Regressionstest) | OK |

**Nicht abschließend geprüft (außerhalb des Zeitbudgets dieses Audits):** `nav_*`-Unterkommandos im Detail, `usermgmt_*`-Detailrouten jenseits des Self-Promotion-Regressionstests, `erradmin:`/`doctor:`/`review:`/`repair:`-Zielmethoden auf tiefer Method-Level (Dispatcher-Ebene verifiziert).

---

## 7. Method-Level Audit

| Module | Class | Method | Caller | Call Type | Production Reachable | Tested | Status |
|---|---|---|---|---|---|---|---|
| rich_menu_system.py | RichMenuSystem | `handle_callback` | PTB `CallbackQueryHandler` (10× registriert) | CALLBACK | Ja | breit | ACTIVE |
| rich_menu_system.py | RichMenuSystem | `_handle_logger_main_menu`/6 Geschwister | generischer `menu:`-Dispatch via `menu_item.handler` | DYNAMIC (Registry-Lookup) | **Ja, ungegatet** | falscher Test-String (s.o.) | ACTIVE, aber **BROKEN-PERM** |
| test_menu_handler.py | TestMenuHandler | `run_unit_tests`/`run_integration_tests`/`run_performance_tests` | `register_handler()` → `menu_item.handler` | DYNAMIC | **Ja, ungegatet** | keine Permission-Tests | ACTIVE, aber **BROKEN-PERM** |
| rich_menu_system.py | RichMenuSystem | `_handle_download_control_callback` + 7 `_handle_download_*` | `^dl:`-Dispatch | CALLBACK | Ja | 28+ Tests | ACTIVE |
| rich_menu_system.py | RichMenuSystem | `_handle_maintenance_callback`/`_handle_reprocessing_callback`/`_handle_doctor_callback`/`_handle_review_callback`/`_handle_repair_callback` | eigene `^prefix:`-Handler | CALLBACK | Ja, jeweils mit eigenem Admin/Owner-Check | größtenteils getestet | ACTIVE |
| rich_menu_handler.py | RichMenuHandler | `handle_text_message` | `MessageHandler` (Text, kein Command/URL) | DIRECT | Ja | vorhanden | ACTIVE |
| rich_menu_system.py | RichMenuSystem | `_handle_download_single_wrapper`/`_handle_download_playlist_wrapper` | Registry, nicht mehr über UI erreichbar | DYNAMIC, aber tot in der UI | technisch ja, praktisch nie | keine | UNUSED (dokumentiert, harmlos, USER-Level) |
| family_*_handler.py (3 Dateien) | FamilyStatsHandler/FamilyChatHandler/FamilyChallengeHandler | alle `handle_*` | `menu:family_*`-Leaves via `menu_item.handler` | DYNAMIC | Ja, mit korrektem Membership-Gate je Methode | 46 Tests gesamt | ACTIVE |
| maintenance_gate.py | — | `is_blocked_by_maintenance()` | 7 Einstiegspunkte | DIRECT, freie Funktion | Ja, alle 7 verifiziert | `test_maintenance_gate.py` (6) + `test_rich_menu_handler_maintenance_gate.py` (9) | ACTIVE |
| klassen/download_handler.py | DownloadHandler | `handle_url`/`handle_youtube_links` | `RichMenuHandler` | DIRECT | Ja | Ja | ACTIVE |
| services/downloader/active_downloads.py | ActiveDownloadRegistry | `register`/`unregister`/`get` | `DownloadHandler`, Telegram-Cancel-Callback | DIRECT (Cross-Thread) | Ja | vermutlich ja | ACTIVE |
| services/metadata/enhanced_metadata_processor.py | EnhancedMetadataProcessor | Singleton-Zugriff via `SingletonMixin` | mehrere Services/Downloader | DYNAMIC (Singleton) | Ja | Ja | ACTIVE |

Keine "dead code" Fehlklassifikationen — dynamischer Dispatch wurde durchgängig vor jedem Urteil geprüft (Registry-Lookup, `getattr`, Decorators). Die zwei `BROKEN-PERM`-Methodengruppen sind technisch `ACTIVE` (production reachable), aber ohne wirksame Berechtigungsprüfung.

---

## 8. Handler Audit

`RichMenuHandler` (1597 Zeilen) importiert und konstruiert ~15 Sub-Handler (`TestMenuHandler`, `NavidromeMenuHandler`, `ReprocessingMenuHandler`, `LibraryDoctorHandler`, `LibraryHealthReviewHandler`, `RepairMusicBotHandler`, `StatistikHandler`, `FamilyStatsHandler`, `FamilyChatHandler`, `FamilyChallengeHandler`, `UserManagementHandler`, `BackupHandler`, `BotRestartHandler`, `DownloadHandler` u.a.) — klassischer Composition-Root/God-Handler. Das ist eine **bereits akzeptierte, dokumentierte Ausnahme** (CLAUDE.md §19), keine neue Aufteilung ohne vorherige Characterization empfohlen.

`klassen/download_handler.py` (dokumentierte Ausnahme): Die Ausnahme ist weiterhin sachlich gerechtfertigt — die Klasse hält bewusst `Update`/`Message`-Objekte und sendet direkt Telegram-Nachrichten (granulare Live-Status-Updates als Kernfeature). Einziger Konstruktions-Call-Site: `handlers/menu/rich_menu_handler.py:1048`.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| HDL-001 | P3 | Handler | Stale Datei-Header-Kommentar verweist auf alten Pfad `services/downloader/download_handler.py`, obwohl Datei seit einer früheren ARCH-Phase unter `klassen/download_handler.py` liegt | `klassen/download_handler.py:1` | Kein Laufzeitrisiko; verwirrt bei Navigation | Kommentarzeile bei nächster Bearbeitung der Datei korrigieren |
| HDL-002 | ACCEPTED RISK | Handler | `RichMenuHandler` als Composition-Root mit ~15 Sub-Handler-Importen/Konstruktionen — God-Handler-Charakteristik | `handlers/menu/rich_menu_handler.py:27-53` | Hohe Kopplung, schwer isoliert testbar | Keine Aufteilung ohne explizite ARCH-Phase (CLAUDE.md §19); bereits akzeptiert |

---

## 9. Services Audit

| Service | Zweck | Telegram-Import? | Auffälligkeit |
|---|---|---|---|
| `services/downloader/active_downloads.py` | Prozessweite Download-Registry pro Chat | Nein | Vorbildlich dokumentiert |
| `services/downloader/downloader.py`, `download_utils.py` | yt-dlp-Orchestrierung | Nein | Cross-Import zu `services.metadata` (bereits dokumentiert, kein Zyklus) |
| `services/bot_maintenance.py` | Wartungsmodus-Flag-Store | Nein | Schlank, Single Responsibility |
| `services/family/*` (7 Module) | Familien-Hub (neu, PR #202) | Nein | Klar aufgeteilt, keine Überlappung |
| `services/statistik/*` + `services/statistik_service.py` | Statistik-Berechnung/Chart-Rendering | Nein | Zwei Namensräume, aber keine Doppel-Logik gefunden |

Keine Telegram-Objekte in den geprüften Services gefunden — Schichtgrenze hält. Keine God-Services oder doppelten Verantwortlichkeiten über bereits dokumentierte Punkte hinaus.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| SVC-001 | P3 | Services | `statistik_service.py` (Top-Level) neben `services/statistik/` (Package) — zwei Namensräume für dasselbe Fachgebiet | `services/statistik_service.py`, `services/statistik/*` | Rein kosmetisch, keine Funktionsüberlappung gefunden | Keine Aktion nötig, nur bei ohnehin anstehendem Umbau konsolidieren |

---

## 10. Metadata Pipeline Audit

Tatsächlicher Call-Flow (rekonstruiert aus `services/metadata/enhanced_metadata_processor.py::process_single_track()`), abweichend von der im Ausgangsauftrag skizzierten Annahme-Reihenfolge (dort explizit als nicht verbindlich markiert):

```
Cache-Check (Video-ID-Index)
 → Basisdaten/Channel-Erkennung (Podcast-Sonderfall)
 → YouTube-Titel-Parsing (+ Artist-Map-Fallback)
 → Spezialkanal-Pre-Check
 → Artist-Bestimmung (ArtistProcessor.determine_best_artist)
 → Artist-Identity-Resolution (ArtistIdentityResolver.resolve)
 → Feature-Artist-Zusammenführung
 → Titel-Bereinigung (TitleCleaner)
 → Genre (GenreProcessor: manuell > lokal/auto-learned > MusicBrainz[immer, für IDs] > Last.fm > Feature-Inferenz)
 → MB-IDs aus Genre-Pipeline übernehmen
 → Lyrics (Genius, mit Fallback-Artists)
 → Cover-Art (asyncio.to_thread, bis zu 6 Quellen)
 → Album/Jahr, Tracknummer
 → ReplayGain-Analyse + Tag (kein Re-Encode, asyncio.to_thread)
 → Datei in Library verschieben
 → Tags schreiben
 → MetadataResult / Cache speichern
 → Auto-Learning (Genre, Artist, Feature-Artists)
```

Genre läuft vor Lyrics/Cover/Album, nicht danach — reine dokumentarische Abweichung ohne Findings-Relevanz. Der zweite MusicBrainz-Call wird explizit übersprungen, wenn die Genre-Pipeline bereits IDs geliefert hat (`_ids_already_known`) — kein Doppel-Call. Kein Artist-/Feature-Artist-Verlust erkennbar. Der Code ist dicht mit Inline-Kommentaren zu bereits behobenen Findings durchsetzt (F-02, F-04, F-05, ARTIST-001, TAG-01, AUTOLEARN-001/GENRE-AGG, COVER-BLOCKING, PARTIAL-FAILURE-LIBRARY, DL-01) — bestätigt eine bereits vielfach durchlaufene Characterization/Fix-Historie ohne Halbfertiges.

Kein Finding in diesem Abschnitt oberhalb Informationsebene.

---

## 11. Artist Identity Audit

Architektur klar geschichtet (`services/metadata/artist_identity_resolver.py`): `ArtistNormalizer` (String) → `ArtistIdentityResolver` (Identität) → `AutoLearnManager` (Lernen). Prioritätskette:

```
artist_override > known_artist > auto_learned_alias > library_identity > musicbrainz_mbid > parser
```

`mapping/artist_overrides.json`, `mapping/auto_learned_artist_aliases.json`, `mapping/auto_learned_featured_artists.json` werden korrekt als Fachlogik behandelt — Schreibzugriffe laufen ausschließlich über `AutoLearnManager`.

**F-07 (MusicBrainz-Artist-MBID nicht als Identitätssignal): Bewertung CURRENTLY ACCEPTED/DEFERRED bestätigt.** Der Code belegt exakt den in `FINDINGS_INDEX.md` genannten Grund: die MBID entsteht in der Genre-Pipeline, *nachdem* `ArtistIdentityResolver.resolve()` bereits gelaufen ist. Vorziehen würde einen Umbau der Aufrufreihenfolge erzwingen — genau die Art "größerer Refactor ohne Sicherheitsnetz", die CLAUDE.md §21 Regel 1 ausschließt. Einstufung bleibt korrekt P3/DEFERRED.

Multi-Artist-Handling (Kollaborations-Override) ist explizit konservativ gehalten — bewusste Design-Entscheidung gegen False Positives, keine Lücke.

Keine neuen Findings.

---

## 12. Genre Audit

`GenreProcessor` (`services/metadata/genre_processor.py`) dokumentiert und hält die tatsächliche Fallback-Hierarchie ein:

1. Manuelles Genre (`artist_genre.yaml`, exakter Match)
2. Lokal (channel_map/auto_learned/fuzzy/raw_genre/Hierarchie)
3. MusicBrainz — **immer** aufgerufen (nicht nur bei fehlendem Genre), da MB-IDs unabhängig vom Genre-Ergebnis für Cover/Album gebraucht werden
4. Last.fm — nur falls noch kein Genre
5. Feature-Artist-Inferenz

Das "MusicBrainz immer aufrufen" ist bewusst zweckgebunden (MB-IDs), kein Performance-Finding. Priorisierung basiert auf `genre_hierarchy.yaml`-Tiefe mit Fallback-Priorität, falls YAML fehlt/fehlerhaft ist — robust gegen Config-Fehler.

Keine neuen Findings; Architektur entspricht der dokumentierten Absicht.

---

## 13. ReplayGain Audit

`services/metadata/loudness_replaygain.py` bestätigt vollständig die Migration weg vom verlustbehafteten Re-Encode:

- Primärpfad `rsgain custom -s i -t -L` (~1,5 s, schreibt RG-2.0-Tags direkt, kein Re-Encode).
- Fallback: reine FFmpeg-`loudnorm`-Analyse (kein Output-File) + `mutagen`-Tag-Write.
- Tag-Format: Freeform-Atome (m4a) bzw. `TXXX` (mp3) — deckungsgleich mit `replaygain_repairs.py` (Library-Repair-Pendant, gleiche Toleranz `_TOLERANCE_DB = 2.0`) → konsistent zwischen Download-Pipeline und nachträglichem Repair.
- Idempotenz: liegt der gemessene Wert innerhalb der Toleranz, wird kein Tag geschrieben.
- Navidrome-Kompatibilität: Byte-identischer Audio-Stream, Standard-RG-Freeform-Atome.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| RG-001 | P3 | ReplayGain | Tagging nur für `.m4a/.mp4/.m4v/.mp3`; FLAC/OGG/OPUS/WAV werden still übersprungen | `services/metadata/loudness_replaygain.py:41,192-194` | Gering, da Download-Pipeline primär m4a erzeugt; relevant nur bei Fremdformat-Reprocessing | Bei Bedarf gezielt erweitern (rsgain unterstützt weitere Formate nativ), nicht vorschnell |

Fehlerverhalten: bei Fehlschlag `(False, None)`, nur als Warnung geloggt — Download schlägt nicht fehl (korrekt, analog Cover/Lyrics).

---

## 14. Duplicate Architecture Audit

Kaskade in `services/duplicate/detector.py::check_for_duplicates()` folgt exakt der in CLAUDE.md §15 / `MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md` beschriebenen Reihenfolge: URL → In-Flight(URL) → Content-Hash (normalisiert) → In-Flight(Content) → Parsed-Content (Parser-Fallback) → Library-Fallback (physischer Datei-Scan). Jede Ebene eigenständig, keine Ebene als alleinige Wahrheit behandelt.

**DUP-05 (Check-then-Register-Race) korrekt geschlossen**: In-Memory-`_in_flight`-Dict mit TTL (900 s Default) schließt das Rennfenster. TTL-Ablauf statt zwingendem `try/finally` ist bewusste, nachvollziehbare Abwägung.

**INV-01 (`duplicate/cache.py`, synchrone Filesystem-Persistenz im Event-Loop-Thread): CLOSED/ACCEPTED RISK bestätigt.** `_save_caches()` läuft vollständig synchron im Event-Loop-Thread, mit explizitem Kommentar zur bewussten Nicht-Migration auf `to_thread()`. Da `add_entry()`/`_save_caches()` ohne `await` dazwischen laufen, entsteht keine neue Race Condition. Kapselung korrekt: kein Finding, keine Wiedereröffnung.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| DUP-001 | P3 | Duplicate/Cache | Toter Fallback-Zweig mit `NameError`-Risiko: `DUPLICATE_CACHE_DIR` referenziert, aber im Modul nicht definiert (nur lokal in `handlers/duplicate_handler.py:53` definiert) | `services/duplicate/cache.py:32` | Nur bei explizit leerem `cache_dir`-Argument auslösbar; aktuell kein Aufrufer tut das (`detector.py:93` übergibt stets nicht-leeren Default) | Zweig entfernen oder korrekten Fallback (Modul-Konstante/Config-Default) ergänzen; Regressionstest für leeren `cache_dir` |

Löschsicherheit: `resolve_playlist_single_conflict()` löscht physische Dateien nur bei exaktem Treffer im Ordner `Singles/` (case-insensitiv) — bewusst eng gefasst.

---

## 15. Cache Audit

| Cache | Owner | Key | Persistenz | Invalidierung | Thread-/Prozess-Safety | Fehlerverhalten |
|---|---|---|---|---|---|---|
| Metadata-Cache | `utils/metadata_cache.py::MetadataCache` | MD5(artist::title), 1 JSON/Track | Datei pro Key | `invalidate()`, `cleanup()` | atomar (tmp+rename), kein Lock, Single-Process-Annahme | korrupte/leere Datei wird beim Lesen automatisch gelöscht |
| Metadata-Cache Video-ID-Index | `services/metadata/cache.py::MetadataCacheHandler` | video_id → {artist,title} | 1 JSON-Datei gesamt | keine explizite Invalidierung (Store-Append) | atomar (tmp+rename) | Ladefehler → leeres Dict, kein Crash |
| Duplicate-Cache (URL/Content) | `services/duplicate/cache.py::DuplicateCache` | MD5(URL-normalisiert)/MD5(artist::title) | 2 JSON-Dateien gesamt | `invalidate_entry()`, `cleanup_old_entries()` | atomar (tmp+rename), INV-01 akzeptiert | Ladefehler → leeres Dict |
| Lyrics-Cache | kein dedizierter Store identifiziert | — | — | — | — | siehe CACHE-001 |

Keine TTL im klassischen Sinn bei Metadata-/Duplicate-Cache — Gültigkeit wird stattdessen über Existenzprüfung der referenzierten Library-Datei sichergestellt (funktional äquivalent zu Invalidierung bei Datei-Löschung) — schützt zuverlässig gegen "Cache sagt Erfolg, Datei ist aber weg".

| ID | Status | Area | Finding |
|---|---|---|---|
| CACHE-001 | UNCERTAIN | Cache | Kein dedizierter Lyrics-Cache-Store im untersuchten Scope gefunden — Lyrics werden pro Track neu abgefragt und erst im Gesamt-MetadataResult mitgespeichert. Bei Metadata-Cache-Miss würde Genius erneut abgefragt. Keine ausreichende Evidenz für ein eigenständiges Problem — als UNCERTAIN markiert. |

---

## 16. Library Health / Repair Audit

`services/library_repair/executor.py` bestätigt die dokumentierte Pipeline-Disziplin:

- **DRY-RUN ist Default** an allen vier geprüften Funktionssignaturen.
- **Safety-Check vor jeder Änderung**: `safety_check(path, library_root)` lehnt u. a. Symlinks ab und prüft `path.resolve(strict=True)` — verhindert Path-Traversal/Symlink-Escape außerhalb der Library.
- **Journal**: `RepairJournal` ist strikt Append-Only, jeder Eintrag trägt SHA-256 vorher/nachher sowie Backup-Pfad.
- **Determinismus**: Executor bearbeitet ausschließlich sechs klar benannte, deterministische Tag-Fixes; kein externer Dienst, kein Re-Encoding im L1-Pfad.
- **Atomarität**: Taggen auf temporärer Sibling-Kopie, erst bei erfolgreicher Verifikation atomar per `Path.replace()` übernommen.

Entspricht vollständig CLAUDE.md §17. Keine neuen Findings.

---

## 17. Concurrency / Async Audit

Überdurchschnittlich diszipliniert, mit sichtbarer Historie von Event-Loop-Blocking-Fixes und dedizierten Heartbeat-Regressionstests (`test_backup_handler_event_loop_blocking.py`, `test_enhanced_status_handler_event_loop_blocking.py`, `test_mugge_statistik_handler_event_loop_blocking.py`, `test_test_menu_handler_event_loop_blocking.py`, `test_enhanced_metadata_processor_*_blocking.py`).

- **`ActiveDownloadRegistry`**: korrekt thread-safe. `threading.Lock` schützt das Dict; `cancel_event` bewusst `threading.Event` (nicht `asyncio.Event`), da der Cancel-Check aus dem yt-dlp-`progress_hooks`-Callback im Executor-Thread erfolgt.
- **Hintergrund-Tasks** (`bot.py`, `family_challenge_scheduler.py`, `play_history_poller.py`, `library_doctor_handler.py`, `repair_musicbot_handler.py`, `reprocessing_menu_handler.py`, `rich_menu_handler.py::_process_url`): Lifecycle-Muster durchgängig konsistent — `start_polling()/stop_polling()` mit `cancel()` + `await task` + `except asyncio.CancelledError`, Fire-and-forget-Tasks tragen `add_done_callback()` als Sicherheitsnetz. `bot.py` verwaltet `_shutdown_event` sauber für Graceful Shutdown.
- **`run_in_executor`**-Nutzung konsequent dort, wo synchrone/blockierende Aufrufe sonst den Event-Loop blockieren würden.

**Kein neues Finding.** Bekannte akzeptierte Restrisiken (INV-01) bleiben ACCEPTED RISK.

---

## 18. Error Handling Audit

52 Stellen mit `except Exception:` gefunden (repoweit, ohne Tests) — keine mit reinem `pass`-Body. 7 bare `except:` gefunden, davon 4 unkritisch (Best-Effort-Fehlermeldungen/Cleanup):

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| ERR-001 | P2 | Error Handling | Bare `except:` (statt `except Exception:`) in der Artist-Normalisierung/Kollaborations-Fallback-Kaskade fängt auch `KeyboardInterrupt`/`SystemExit` und maskiert unerwartete Fehler ohne Log-Eintrag | `services/downloader/playlist_processor.py:264,286,306` | Ein echter Bug in der Normalisierungskette würde still zur nächsten Fallback-Stufe durchgereicht statt geloggt zu werden — erschwert Diagnose bei falschem Artist-Ergebnis | `except Exception as e:` mit Debug-Log, gemäß dem an anderen Stellen der Datei bereits etablierten Muster |

Übrige bare-except-Stellen (`enhanced_status_handler.py:767`, `enhanced_error_handler.py:981,986`, `audio_enhancer.py:229`) sind bewusste letzte Verteidigungslinien in Telegram-Fehlerpfaden bzw. Cleanup-Code — **FALSE POSITIVE** als eigenständiges Risiko.

---

## 19. Configuration Audit

`config.py` lädt `.env` über mehrere Kandidatenpfade mit `print()`-Seiteneffekten beim Modulimport — funktional unkritisch, aber Import-Seiteneffekt im Sinne von CLAUDE.md §13. Secrets (`BOT_TOKEN`, `GENIUS_ACCESS_TOKEN`, `LASTFM_API_KEY/SECRET`, `FANART_API_KEY`, Navidrome-Passwort) werden ausschließlich über `os.getenv()` gelesen, nie hartkodiert; `mask_sensitive()` wird für Logging/Anzeige verwendet — korrekt gemäß §12. Hardcodierte absolute Pfade sind für ein Single-Host-Hobbyprojekt plausibel.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| CFG-001 | P3 | Config | `print()`-Seiteneffekte beim `.env`-Laden direkt auf Modulebene (`import config` triggert Konsolenausgabe) | `config.py:31-36,46,54` | Kein Sicherheits-/Korrektheitsrisiko; erschwert Tests minimal (Stdout-Rauschen) | Kein Handlungsbedarf laut §13; bei zukünftiger Config-Characterization mit aufnehmen |

---

## 20. Scripts / Entrypoints

`scripts/` enthält 6 aktive, dokumentierte Wartungstools: `library_health_check.py`, `library_health_review.py`, `library_repair.py`, `resolve_duplicates.py`, `reprocess_artist_metadata.py`, `normalize_test_library_loudness.py`. Für `reprocess_artist_metadata.py` ist per `docs/FINDINGS_INDEX.md` (PR #148) bereits verifiziert, dass der fachliche Kern nach `services/metadata/track_reprocessor.py` ausgelagert wurde — entspricht §4 exakt. `library_repair.py` delegiert für Duplicate-Handling explizit an `scripts/resolve_duplicates.py` als Subprozess.

`bot.py` (531 Zeilen) hat einen klaren einzelnen Entry Point (`main()` → `async_main()`, Signal-Handler-Setup). Keine Auffälligkeiten. Keine Findings oberhalb P3 in diesem Abschnitt.

---

## 21. Test Architecture

3264 gesammelte Tests (`pytest --collect-only -q`, keine Collection-Fehler), 237 Testdateien, thematisch organisiert (`test_*_blocking.py`, `test_*_readonly_safety.py`, `test_*_cli_*.py`, `test_*_concurrency*.py`).

- **Kein Over-Mocking-Problem gefunden**: AST-Analyse über den gesamten Baum ergab **0 Testdateien**, die eine Klasse mit demselben Namen wie eine Produktionsklasse selbst definieren (das in CLAUDE.md §7 explizit verbotene Muster). 146 von 237 Testdateien nutzen `unittest.mock`/`patch`, plausibel angesichts vieler externer Abhängigkeiten.
- Blocking-Regressionstests messen echte Heartbeats parallel zu realen (nicht gemockten) blockierenden Aufrufen — genau das von CLAUDE.md §7/§8 geforderte Verhalten.
- Path-Traversal- und Token-Masking-Verhalten sind mit dedizierten Tests abgesichert.

**Kein Finding.** Die Testarchitektur erfüllt die in CLAUDE.md formulierten Ansprüche sichtbar gut.

---

## 22. Test Coverage Gaps

| Bereich | Implementiert | Getestet | Integration getestet | Risiko |
|---|---|---|---|---|
| Telegram Routing | Ja | Ja | Teilweise | Mittel (TGPERM-001) |
| Menu callbacks | Ja | Ja (umfangreich) | Teilweise | Mittel (TGPERM-001) |
| Permissions | Ja | Ja (`_is_admin` in mehreren Handlern getestet) | Nein (kein E2E-Telegram-Test) | Mittel — Testlücke bei generischem `menu:`-Dispatch nachgewiesen |
| Download | Ja | Ja (sehr umfangreich) | Teilweise (yt-dlp gemockt) | Niedrig |
| Metadata | Ja | Ja (Characterization, Cache Hit/Miss) | Teilweise | Niedrig |
| Artist Identity | Ja | Ja (dedizierte Migration + Resolver-Tests) | Teilweise | Niedrig (F-07 bewusst DEFERRED) |
| Genre | Ja | Ja | Teilweise (MusicBrainz gemockt) | Niedrig |
| Artwork | Ja | Ja (Stichprobe) | Nicht vertieft geprüft | Unklar |
| Lyrics | Ja | Teilweise | Nicht verifiziert | UNCERTAIN |
| ReplayGain | Ja | Ja (inkl. Blocking-Test) | Ja (real getestet) | Niedrig |
| Library Health | Ja | Ja (sehr umfangreich) | Ja (Readonly-Safety mit echtem subprocess) | Niedrig |
| Library Repair | Ja | Ja (Disposition-Matrix, Executor, CLI) | Ja (echte Pipeline getestet) | Niedrig |
| Duplicate | Ja | Ja | Teilweise | Niedrig (INV-01 ACCEPTED RISK) |
| Cache | Ja | Teilweise | Nicht vertieft geprüft | UNCERTAIN |
| Concurrency | Ja | Ja (Semaphore-, Blocking-, Race-Condition-Tests) | Ja | Niedrig |
| Error handling | Ja | Teilweise (in Fachtests mitgetestet) | Nein | Mittel (ERR-001) |

---

## 23. Dead Code / Dead Method Analysis

AST-basierte Heuristik (jedes Modul gegen alle Import-Statements im Repo abgeglichen) ergab **0 Kandidaten** für offensichtlich verwaiste Module — jede Datei wird mindestens irgendwo importiert. Method-Level-Dead-Code wurde nicht separat vertieft geprüft, aber keine Hinweise auf signifikanten Dead Code.

---

## 24. Security

**Telegram (siehe Abschnitt 5/6):** TGPERM-001 (P1) — einziger substanzieller Security-Fund des gesamten Audits.

**Nicht-Telegram:**
- **Shell-Injection**: 0 Treffer für `shell=True` im gesamten Baum. Alle `subprocess.run()`-Aufrufe (yt-dlp, ffmpeg, ffprobe, rsgain, Navidrome-Scan-Trigger) verwenden Listen-Argumente — strukturell gegen Shell-Injection abgesichert.
- **Path Traversal**: explizit adressiert und mit Regressionstests abgesichert (`test_backup_handler.py`, `test_logger_menu_path_traversal.py`). Scripts tragen dokumentierte Path-Safety-Guards.
- **Secrets-Logging**: keine Treffer bei gezielter Suche nach Token/Passwort/API-Key-Werten in Logger-Aufrufen der externen Clients. Dedizierter Regressionstest `test_run_test_bot_token_masking.py` vorhanden.

Kein neues Security-Finding außerhalb von TGPERM-001.

---

## 25. Performance

Keine tiefgreifende Performance-Analyse nötig; keine plausiblen Hinweise auf unnötige wiederholte Filesystem-Scans oder N+1-API-Call-Muster im geprüften Umfang.

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| PERF-001 | P3 (ACCEPTED) | Performance | Mehrere sehr große Dateien (`rich_menu_system.py` 3266 Zeilen, `enhanced_error_handler.py` 1995 Zeilen) implizieren potenziell viele synchrone Formatierungs-/Verzweigungsschritte pro Telegram-Update | `wc -l` s. Abschnitt 4 | Wartbarkeit eher als Laufzeit betroffen (Blocking-Operationen bereits konsequent in Executor-Threads ausgelagert) | Kein akuter Handlungsbedarf; bereits als bekannter Risikobereich in CLAUDE.md §19 dokumentiert — ACCEPTED |

---

## 26. Documentation Consistency

| Dokument | Kategorie | Befund |
|---|---|---|
| `docs/FINDINGS_INDEX.md` | **CURRENT / LIVING** | Aktiv gepflegt, letzter Eintrag 2026-09-13 (Family Hub F1–F5) — exakt wie CLAUDE.md §30 vorschreibt. |
| `docs/MusicBot_ENGINEERING_BASELINE_v9.md` | **CURRENT SNAPSHOT** (eingefroren 2026-09-07) | Wird laut Konvention nicht mehr editiert — korrekt eingehalten. |
| `docs/MusicBot_ENGINEERING_BASELINE_v10.md` | **CURRENT / LIVING (DRAFT)** | Wird laufend pro PR nachgezogen. |
| `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` | **HISTORICAL** | Endet mit „AE-12 CLOSED — GO"-Abschluss; kein Widerspruch zu aktuellem Code. |
| `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md` | **CURRENT / LIVING** | Deckt sich exakt mit Code-Architektur und Menübaum; einziger blinder Fleck ist die Detailtiefe für Logger-/Test-Menü (siehe TG-002). |
| `README.md` | **STALE (partiell)** | Nennt veraltete Testzahl (2920, Stand 2026-09-08) gegenüber aktuell 3264 gesammelten Tests. |

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| DOC-001 | P3 | Documentation | `README.md` nennt eine veraltete Testzahl gegenüber aktuell 3264 gesammelten Tests nach mehreren seither gemergten PRs | `README.md:68` vs. `pytest --collect-only -q` → 3264 Tests | Rein informativ, keine funktionale Auswirkung — STALE_DOC, kein CODE BUG | Beim nächsten v10-Freeze README-Zeile auf die dann aktuelle, vom Nutzer bestätigte Full-Suite-Zahl aktualisieren |
| TG-002 | ACCEPTED RISK | Telegram Doku | `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md` deckt laut eigenem Scope das Detailverhalten des Admin-/Test-Bereichs bewusst nicht ab — dadurch fehlt eine lebende Referenz, die TGPERM-001 früher sichtbar gemacht hätte | `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md` Abschnitt 2, Zeile 55-59 | Kein Codefehler, aber blinder Fleck in der Doku für genau den betroffenen Bereich | Bei Behebung von TGPERM-001 Abschnitt 2 um Hinweis auf `callback_data`-Override-Konvention ergänzen |

---

## 27. Findings (Gesamtübersicht, priorisiert)

| ID | Priority | Area | Finding | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|---|
| ~~**TGPERM-001**~~ | ~~**P1**~~ → **CLOSED (2026-09-12)** | Telegram Security | 10 ADMIN-Level-Menüpunkte (7× Logger-Verwaltung, 3× Test-System) waren über den generischen `menu:<id>`-Dispatch ohne jede Berechtigungsprüfung erreichbar | `handlers/menu/rich_menu_system.py:2037-2046,776-836,1017-1049`; `handlers/test_menu_handler.py:61-79`; `tests/test_rich_menu_access_control.py:77` (testete falschen String) | War: jeder Bot-Nutzer konnte globales Log-Level ändern (hebelt SEC-001-Audit-Schutz aus), Log-Dateien einsehen/herunterladen, Logger-Module/-Handler umschalten sowie einen vollständigen Testlauf (bis 900s Subprozess) auslösen | **Behoben** — siehe Nachtrag oben: `callback_data`-Overrides für die 7 Logger-Items + `_is_admin()`-Check in `TestMenuHandler._execute_test_run()`; Regressionstest um echten Registry-Sweep ergänzt |
| ERR-001 | P2 | Error Handling | Bare `except:` in Artist-Normalisierungs-Fallback schluckt jede Exception ohne Log | `services/downloader/playlist_processor.py:264,286,306` | Erschwert Diagnose bei falschem Artist-Ergebnis durch echten Bug in der Normalisierung | `except Exception as e:` mit Debug-Log |
| DUP-001 | P3 | Duplicate/Cache | Toter Fallback-Zweig mit `NameError`-Risiko bei leerem `cache_dir` | `services/duplicate/cache.py:32` | Aktuell nicht erreichbar (kein Aufrufer übergibt leeren Wert) | Zweig entfernen oder korrekten Fallback ergänzen |
| RG-001 | P3 | ReplayGain | Kein Tagging für FLAC/OGG/OPUS/WAV | `services/metadata/loudness_replaygain.py:41,192-194` | Gering (Download-Pipeline primär m4a) | Bei Bedarf gezielt erweitern |
| HDL-001 | P3 | Handler | Stale Pfad-Kommentar | `klassen/download_handler.py:1` | Kein Laufzeitrisiko | Bei nächster Bearbeitung korrigieren |
| DEP-001 | P3 | Dependency | Ungenutzter Import | `services/metadata/enhanced_metadata_processor.py:6` | Keiner | Entfernen |
| DEP-002 | P3 | Naming | Redundante Modulverschachtelung | `services/downloader/download/` | Kosmetisch | Keine Aktion |
| SVC-001 | P3 | Services | Zwei Namensräume für Statistik-Service | `services/statistik_service.py`, `services/statistik/*` | Kosmetisch | Bei Umbau konsolidieren |
| CFG-001 | P3 | Config | `print()`-Seiteneffekt beim Import | `config.py:31-36,46,54` | Kein Risiko | Kein Handlungsbedarf |
| DOC-001 | P3 | Docs | Veraltete Testzahl in README | `README.md:68` | Rein informativ | Beim nächsten Freeze aktualisieren |
| CACHE-001 | UNCERTAIN | Cache | Kein dedizierter Lyrics-Cache identifizierbar | `services/metadata/lyrics_processor.py` | Unklar | Gezielte Nachprüfung |
| TEST-001 | UNCERTAIN | Tests | Lyrics-/Cache-Coverage nicht vertieft geprüft | — | Unklar | Gezielte Nachprüfung in Folge-Audit |

---

## 28. Accepted Risks

- **F-07** — MusicBrainz-MBID nicht als Artist-Identitätssignal genutzt (Aufrufreihenfolge-bedingt); Refactor würde Sicherheitsnetz-Regel verletzen.
- **INV-01** — Synchrone Duplicate-Cache-Persistenz im Event-Loop-Thread; bewusst begründet, keine neue Race Condition.
- **`dl:`-Präfix ohne zentrales Gate** — bewusst und korrekt chat_id-skopiert, kein Cross-User-Zugriff möglich.
- **`klassen/download_handler.py`-Ausnahme** — Telegram-Objekte in Orchestrierungsschicht, sachlich weiterhin gerechtfertigt.
- **God-Handler (RichMenuSystem/RichMenuHandler)** — CLAUDE.md §19 explizit dokumentierte Ausnahme, keine Aufteilung ohne Characterization.
- **CoverProcessor-Direct-HTTP** — kein reiner Client (Scoring+Cache+6-Quellen-Orchestrierung), MIG-04 bereits geschlossen.
- **PERF-001** — Große Dateien als bekannter, akzeptierter Risikobereich.

Alle bestätigt weiterhin korrekt gekapselt/gerechtfertigt — keine neue Evidenz, die eine Neubewertung erfordert.

## 29. Deferred Findings

**F-07** bleibt DEFERRED (Begründung bestätigt, s. Abschnitt 11/28). Keine neuen Deferrals identifiziert.

---

## 30. Recommended Changes

1. ~~**TGPERM-001 beheben**~~ **CLOSED (2026-09-12)** — siehe Nachtrag oben.
2. **ERR-001 beheben** (P2, Phase 3): bare `except:` in `playlist_processor.py` auf `except Exception as e:` mit Log umstellen, analog zum bereits etablierten Muster in derselben Datei.
3. Übrige P3-Funde bei ohnehin anstehender Bearbeitung der jeweiligen Datei mitziehen — kein eigener Task erforderlich.

## 31. Priority Roadmap

**Phase 1 — Critical:**
- ~~TGPERM-001~~ **CLOSED (2026-09-12)** — Fix + korrigierter/erweiterter Regressionstest umgesetzt, siehe Nachtrag oben. Gezielte + thematische Tests gemäß §8.A grün (513/513); volle Suite bewusst nicht durch den Implementierungsprozess ausgeführt.

**Phase 2 — Architecture:**
- Keine strukturellen Änderungen erforderlich.

**Phase 3 — Quality:**
- ERR-001, DUP-001, RG-001, HDL-001.

**Phase 4 — Optional:**
- DEP-001/002, SVC-001, CFG-001, DOC-001, CACHE-001/TEST-001-Nachprüfung.

---

## 32. Final Architecture Verdict

| Bereich | Score |
|---|---|
| Architecture | 8/10 |
| Layer separation | 8/10 |
| Dependency direction | 8/10 |
| Telegram architecture | 8/10 (nach TGPERM-001-Fix, war 6/10) |
| Callback routing | 8/10 (nach TGPERM-001-Fix, war 6/10) |
| Handler design | 7/10 |
| Services design | 8/10 |
| Metadata pipeline | 8/10 |
| Artist identity | 7/10 |
| Genre | 8/10 |
| ReplayGain | 8/10 |
| Duplicate architecture | 8/10 |
| Library Health | 9/10 |
| Library Repair | 9/10 |
| Concurrency | 9/10 |
| Error handling | 7/10 |
| Security | 8/10 (nach TGPERM-001-Fix, war 6/10) |
| Testing | 8/10 |
| Documentation | 8/10 |
| Maintainability | 7/10 |

**Overall Architecture Score: 8,3/10** (war 7,5/10 vor dem TGPERM-001-Fix)

Nach Behebung von TGPERM-001 liegen alle Bereiche zwischen 7 und 9/10 — kein Bereich zieht den Gesamteindruck mehr signifikant herunter. Der Score begründet sich aus der Kombination aus sehr reifer Kernpipeline (Metadata/Duplicate/Concurrency/LibraryHealth), disziplinierter Testarchitektur und einem zügig geschlossenen, gut lokalisierten Security-Fund im Telegram-Layer.

```
ARCHITECTURE STATUS:

[x] PRODUCTION READY WITH MINOR DEBT
[ ] NEEDS TARGETED FIXES
[ ] NEEDS ARCHITECTURAL CHANGES
[ ] NOT SAFE FOR PRODUCTION
```

*(Stand zum ursprünglichen Auditzeitpunkt 2026-09-12, vor dem TGPERM-001-Fix: NEEDS TARGETED FIXES — siehe Nachtrag oben für den Verlauf.)*

### Was ist bereits sehr gut?
Metadata-/Artist-/Genre-/ReplayGain-Pipeline, Duplicate Detection, Library Health/Repair, Concurrency-Handling, Testarchitektur (echte Produktionsklassen, keine Scheintests), Schichtgrenzen-Disziplin, Secrets-Handling, Path-Traversal-Schutz, Shell-Injection-Freiheit.

### Was musste zwingend geändert werden?
TGPERM-001 (Permission-Bypass bei Logger-/Test-Menü) — einziger P1-Fund, noch am selben Tag behoben (siehe Nachtrag oben).

### Was sollte geändert werden?
ERR-001 (bare except in Artist-Normalisierung).

### Was kann bewusst so bleiben?
F-07, INV-01, `dl:`-Ausnahme, `klassen/download_handler.py`-Ausnahme, God-Handler-Struktur, CoverProcessor-Direct-HTTP — alle als ACCEPTED bestätigt.

### Was ist nur technische Schuld?
DEP-001/002, SVC-001, CFG-001, HDL-001, DOC-001, RG-001, DUP-001 — alle P3, keine akute Handlung nötig.

### Welche Punkte sind bewusst deferred?
F-07 (MBID-Identitätssignal) bleibt DEFERRED.

---

## AUDIT COMPLETE

```
Repository: dkmd89-dev/musicbot
Commit: 3e136b1 (main)
Files analyzed: gesamter Python-Baum (handlers/, services/, klassen/, utils/, scripts/, tests/, mapping/, docs/)
Tests collected: 3264 (python3 -m pytest --collect-only -q, 0 Collection-Fehler)
Tests executed: keine volle Suite (bewusst, CLAUDE.md §8.A) — gezielte Verifikationen (compileall, AST-Checks, grep) durchgeführt

P0: 0
P1: 0 (TGPERM-001 CLOSED 2026-09-12, siehe Nachtrag)
P2: 1 (ERR-001)
P3: 9 (DUP-001, RG-001, HDL-001, DEP-001, DEP-002, SVC-001, CFG-001, DOC-001, PERF-001)
Accepted Risk: 7 (F-07, INV-01, dl:-Ausnahme, klassen/download_handler.py, God-Handler, CoverProcessor-HTTP, PERF-001)
Deferred: 1 (F-07)
Uncertain: 2 (CACHE-001, TEST-001)
Closed nach Audit: 1 (TGPERM-001)

Architecture Score: 8,3/10 (war 7,5/10 vor dem TGPERM-001-Fix)

Final Verdict: PRODUCTION READY WITH MINOR DEBT (war NEEDS TARGETED FIXES vor dem TGPERM-001-Fix)

Top Actions (verbleibend nach TGPERM-001-Fix):
1. ERR-001: bare except in playlist_processor.py auf except Exception mit Log umstellen.
2. DUP-001: toten Fallback-Zweig in duplicate/cache.py bereinigen.
3. RG-001: bei Bedarf ReplayGain-Formatabdeckung erweitern (FLAC/OGG/OPUS/WAV).
4. HDL-001: stale Pfad-Kommentar in klassen/download_handler.py korrigieren.
5. CACHE-001/TEST-001: gezielte Nachprüfung des Lyrics-Cache-Verhaltens in Folge-Audit.
6. DEP-001/002, SVC-001, CFG-001, DOC-001: bei ohnehin anstehender Bearbeitung mitziehen.
7. Nutzer: volle Testsuite zur finalen Verifikation ausführen (CLAUDE.md §8.A).

Erledigt seit dem ursprünglichen Audit:
- TGPERM-001 behoben: callback_data-Overrides für 7 Logger-Items + _is_admin()-Check in TestMenuHandler._execute_test_run().
- tests/test_rich_menu_access_control.py um echten Registry-Sweep-Regressionstest erweitert (verallgemeinert über die 10 konkret gefundenen Items hinaus).
- docs/FINDINGS_INDEX.md um TGPERM-001 als CLOSED (2026-09-12) nachgetragen.
```
