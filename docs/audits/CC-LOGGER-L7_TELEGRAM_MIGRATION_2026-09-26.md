# CC-LOGGER-L7 — Telegram-Migration

**Datum:** 2026-09-26
**Auslöser:** `L7.txt` (Fortsetzung des Logger-Phasenplans L1–L7), Nutzerfreigabe.
**Vorgänger:**
- `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` (L2, gemergt #300)
- `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` (L3, gemergt #301)
- `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md` (L4, gemergt #302)
- `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md` (L5, gemergt #303)
- `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md` (L6, gemergt #304)
**Status:** abgeschlossen (Migrationsschritte 2–6). Schritt 7 (Kategorie-D-Follow-ups) ist reine Dokumentation, keine Implementierung.

---

## 1. Ausgangslage

L1–L6 hatten eine vollständige, Telegram-freie Logger-Fachlogik in `services/logger_admin.py` aufgebaut (Read-API, persistente Config, Runtime-Snapshot, kontrollierter Apply/Restart) und dafür in Control Center exponiert. Telegram (`handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler`) blieb in allen vier Phasen bewusst unverändert — die Migration war ausdrücklich auf L7 verschoben.

L7 hatte zwei Teile:

1. **Verbindlicher L1–L6-Preflight** gegen den tatsächlichen Repository-Stand (nicht nur die Audit-Dokumente).
2. **Migration Boundary** — für jede Telegram-Logger-Funktion feststellen, ob sie bereits Application-Layer-Funktionen nutzt (A), auf bestehende L4/L5-Funktionen umgestellt werden sollte (B), legitim Telegram-spezifisch bleibt (C), oder noch nicht durch L4/L5 abgedeckt ist (D).

Der Preflight ergab einen **dokumentierten Widerspruch**: `docs/FINDINGS_INDEX.md` führte zwei Einträge (CC-AC-10D-Logger-Teil, CC-AC-10A-Endpunkt-Granularität) noch als OPEN, obwohl beide durch L2–L6 sachlich beantwortet waren. Bereinigt in einem separaten Prep-Commit (`chore(findings): ...`), bewusst getrennt von diesem Migrationscommit, damit L7 sauber auf dem Migrations-Scope bleibt.

---

## 2. Modul-Taxonomie — verifizierter Kernbefund

Vor jeder Migrationsentscheidung wurde geprüft, ob Telegrams Persistenzfunktionen (`toggle_module`, `set_module_level`, `enable_all_modules`, `disable_all_modules`) verlustfrei auf `services/logger_admin.py::update_logger_config()`/`validate_logger_config_patch()` umstellbar sind. Diese Funktionen lehnen unbekannte Module strikt ab (`LOGGER_CONFIG_UNKNOWN_MODULE`, bewusste L4-Entscheidung — Control Center hat keine autoritative Quelle für real aktive Module).

**Verifizierter Abgleich** (statische Analyse von `get_module_logger()`/`setup_module_logging()`-Aufrufstellen im gesamten Produktionscode gegen `data/module_logger_config.json`):

- `data/module_logger_config.json`: 40 Modul-Einträge.
- Produktionscode: 75 statisch gefundene, tatsächlich verwendete Modulnamen.
- **54 davon fehlen in der JSON.** Nach vertiefter Prüfung (Prozesszugehörigkeit, tote Convenience-Wrapper in `logger.py`, Namens-Drift):
  - 3 sind ausschließlich in `scripts/*.py`-Einstiegspunkten registriert (eigener Prozess, nie im Bot-`_module_loggers`, für Telegram irrelevant).
  - 10 sind tote `logger.py`-Convenience-Wrapper ohne einen einzigen externen Aufrufer im gesamten Produktionscode (`log_duplicate_*`, `log_enhanced_*`, `log_downloader_*`, `log_button_*`, `log_organizer_*`, `log_genremap_*`, `log_debug_*`, `log_progress_*`, `log_reprocess_*`, `log_menu_*`→`metadata_utils`) — feuern nie, tauchen nie in `_module_loggers` auf.
  - **41 sind real aktiv und Bot-prozess-erreichbar**, mehrheitlich P0-relevant: `DuplicateCache`, `DuplicateRunner`, `DuplicateHandler_Telegram` (Duplicate Detection); `AlbumProcessor`, `ArtistIdentityResolver`, `LyricsProcessor`, `MetadataCacheHandler`, `ReprocessingRunner` (Metadata); `GenreRevalidation`, `GenreRevalidationRunner` (Genre); `RepairService`, `RepairRunTracking`, `LibraryHealthFindings`, `MaintenanceService` (Library); `DownloadHistoryStore`, `DownloadResultReporter`, `download_utils`, `errors`, `filename_fixer` (Download/File Processing); plus Admin-/Feature-Module (`SystemMonitor`, `SystemStatus`, `BotRestartHandler`, `MaintenanceModeStore`, `NavidromeRenderer`, `PlaylistProcessor`, `CookieHandler`, `main`, `telegram_bot`, vier `Family*`-Handler, drei Statistik-Module).
  - Zusätzlich: 13 von ursprünglich 19 scheinbar in der JSON „verwaisten" Einträgen sind tatsächlich real (Factory-Pattern `(self.logger_factory or get_module_logger)("Name")`, statischer Grep erfasst das nicht). Nur 6 sind echte Config-Leichen: `filenamefixer` (Tippfehler ggü. real `filename_fixer`), `MAIN`/`TELEGRAM_BOT` (Casing-Drift ggü. real `main`/`telegram_bot`), `PodcastRSSManager`/`SpotifyDownloader`/`StartHelpHandler` (keine zugehörige Klasse/Datei mehr im Repository auffindbar).

**Root Cause:** organisches Wachstum ohne Pflegepflicht (JSON wurde zu einem Zeitpunkt handkuratiert und seither nicht systematisch mit neuen `get_module_logger()`-Aufrufstellen synchronisiert) plus tote Altlast in `logger.py` (Convenience-Funktionen für inzwischen umbenannte/entfernte Module).

**Konsequenz:** eine naive 1:1-Migration von `toggle_module`/`set_module_level` auf `update_logger_config()` hätte für 41 der ~75 real aktiven Module (mehrheitlich P0) eine echte Funktionsregression bedeutet (`422 LOGGER_CONFIG_UNKNOWN_MODULE` bei jedem ersten Zugriff über ein bisher nie konfiguriertes Modul).

**Nutzerentscheidung:** interne, nicht per HTTP exponierte Auto-Register-Funktion (`services/logger_admin.py::ensure_module_config_entry()`), die dieselbe Lücke schließt, ohne die L4-Entscheidung für die öffentliche Control-Center-API aufzuweichen.

---

## 3. Migration-Matrix (Ergebnis)

| Kategorie | Funktionen | Status |
|---|---|---|
| **A** — bereits Application-Layer | — | keine gefunden (Telegram wurde in L2–L6 bewusst nicht angefasst) |
| **B** — migriert | `toggle_module`, `set_module_level`, `enable_all_modules`, `disable_all_modules`, `show_log_file_detail`, `show_log_files_list`, `show_log_files_stats` | **umgesetzt (dieser Bericht)** |
| **C** — Telegram-spezifisch, bleibt | Tastatur-/Menüaufbau, Paginierung, Callback-Parsing, `_safe_edit_message`/`_show_error_message`, Admin-Gate (`_ADMIN_ONLY_PREFIXES` → `is_admin_or_owner()`, bereits korrekt geteilt mit Control Center) | unverändert |
| **D** — nicht durch L4/L5 abgedeckt | globales Log-Level (kein Persistenz-Schema), Modul-/Fehler-Statistiken (Prozessspeicher, Cross-Process-Blocker unverändert), volle `loggerDict`-Introspektion, In-Process-Reload, Cleanup-Funktionen (inkl. kaputter Callback-Verdrahtung), tote `logger_search_module`-Route | **dokumentiert, nicht implementiert (Abschnitt 7)** |

---

## 4. Implementierung

### 4.1 Neue Application-Layer-Funktion — `ensure_module_config_entry()`

`services/logger_admin.py`, direkt nach `update_logger_config()`. Legt ein unbekanntes Modul mit denselben Default-Werten an, die `ModuleLoggerManager.get_module_config()` bereits für unbekannte Module zurückgibt (`enabled=True, level=INFO, file_handler=True, console_handler=True, custom_format=None`, Konstante `DEFAULT_NEW_MODULE_CONFIG`). Idempotent (bekanntes Modul → kein Schreibvorgang), atomarer Write über die bestehende `_atomic_write_json()`.

**Bewusst nicht über `PATCH /api/v1/admin/logger/config` erreichbar** — kein Router-Endpunkt dafür, keiner vorgesehen. Control Center bleibt bei der strikten L4-Semantik (kein Anlegen unbekannter Module über die öffentliche API). Nur In-Process-Aufrufer (Telegram/Bot), die die reale Modul-Existenz bereits über `_module_loggers` kennen, dürfen diese Lücke schließen.

### 4.2 Persistenzpfad-Migration — `toggle_module()`/`set_module_level()`

Beide rufen jetzt zuerst `ensure_module_config_entry()`, dann `update_logger_config()` (statt `ModuleLoggerManager.set_module_config()`s eigenem, nicht-atomarem `_save_module_configs()`). Der In-Memory-Cache (`module_manager.module_configs`) wird synchron aus der Rückgabe nachgezogen, damit der unveränderte Live-Apply-Schritt (`_apply_module_config()`, weiterhin Bot-lokal — Telegram ist der einzige Client, der das kann) mit dem aktuellen Stand arbeitet. Live-Verhalten für den Nutzer identisch zu vorher.

### 4.3 Batch-Persistenz — `enable_all_modules()`/`disable_all_modules()`

Neue private Methode `_patch_all_known_modules(enabled: bool)`: **ein** Multi-Modul-Patch über `update_logger_config()` statt N sequenzieller, nicht-atomarer Einzel-Writes. Beide Funktionen bekamen zusätzlich `try/except` mit Routing über `error_handler`/`_show_error_message()` — vorher konnten sie praktisch nie eine Exception werfen (die alten Save-Pfade schluckten Fehler intern mit `print()`); das war eine unbewusste Verhaltenslücke, die durch den neuen, validierenden Pfad sichtbar geworden wäre.

### 4.4 Datei-Detail — `show_log_file_detail()`

Liest jetzt über `services/logger_admin.py::get_log_file()` → `services/logs/reader.py::read_logs()` statt eigenem `open()`/`readlines()`/`Counter()`. Identischer SEC-003-Schutz wie Control Center (Whitelist + Containment-Check), kein zweiter Parser. Neuer privater Helper `_format_log_entry_preview()` rekonstruiert Vorschauzeilen aus den strukturierten `LogEntry`-Objekten.

### 4.5 Datei-Liste/-Statistik — `show_log_files_list()`/`show_log_files_stats()`

Nutzen jetzt `list_log_files()`/`get_log_file_stats()` (identisch zu Control Center) statt eigenem `log_dir.glob()`.

---

## 5. Bewusste, dokumentierte Verhaltensänderungen

Keine davon ist eine stille Drift — jede wurde vor der Umsetzung benannt (Nutzerfreigabe für Migrationsziel; einzelne Details während der Implementierung präzisiert):

1. **Level-Zählung korrekt statt naiv** (`show_log_file_detail`): vorher zählte `if level in line` eine Zeile unter dem ersten in fester Scan-Reihenfolge gefundenen Level-Wort, auch wenn es nur im Nachrichtentext vorkam (z. B. eine WARNING-Zeile mit dem Wort „DEBUG" im Text wurde als DEBUG gezählt). Jetzt wird das strukturiert geparste Level-Feld verwendet. Regressionstest pinnt das alte Fehlverhalten explizit als behoben.
2. **Fehlermeldung bei Datei-Traversal-Versuch**: vorher „Ungültiger Dateiname", jetzt „Log-Datei nicht gefunden: …" — identisch zur bereits bestehenden Control-Center-Formulierung (`InvalidLogFilenameError`). Die sicherheitskritische Eigenschaft (Dateiinhalt wird nie ausgeliefert) ist unverändert.
3. **Level-/Zeilenstatistik begrenzt auf die neuesten 2000 Zeilen** (`MAX_LIMIT` aus L2) statt unbegrenztem `readlines()` — bei realen Dateigrößen (siehe L2-F1) kein praktischer Unterschied.
4. **Sortierung der Log-Dateiliste** (`show_log_files_list`): von „nach Dateigröße absteigend" auf „nach mtime, neueste zuerst" (**explizite Nutzerentscheidung**), konsistent mit Control Center.
5. **Rotierte Logs jetzt sichtbar**: `list_log_files()` nutzt `*.log*` (identisch zu Control Center) statt vorher `*.log` ohne Rotationen.
6. **Erweiterte Datei-Statistik**: `show_log_files_stats()` zeigt zusätzlich größte/älteste Datei (vorher nicht verfügbar) — reine Ergänzung, keine Entfernung bestehender Felder.

---

## 6. Security

- **Kein neuer Endpunkt, keine neue Angriffsfläche.** `ensure_module_config_entry()` ist nicht über HTTP erreichbar.
- **Admin-Gate unverändert korrekt geschichtet:** `_ADMIN_ONLY_PREFIXES` in `rich_menu_system.py` delegiert an `is_admin_or_owner()` (`handlers/menu/permissions.py`), dieselbe Telegram-freie Funktion, die auch Control Center für Auth nutzt — kein Migrationsbedarf, war bereits korrekt.
- **Path-Traversal-Schutz konsolidiert, nicht geschwächt:** `show_log_file_detail()` nutzt jetzt dieselbe, bereits von Control Center genutzte und getestete Whitelist-plus-Containment-Logik statt einer zweiten, eigenen Implementierung.
- **Keine Secrets im Log:** `services/logs/reader.py`s bestehende Redaktionslogik greift jetzt auch für die Telegram-Vorschau (vorher nicht, da Telegram die Datei selbst gelesen hat) — eine zusätzliche, positive Nebenwirkung.

---

## 7. Kategorie D — nicht durch L4/L5 abgedeckt (dokumentiert, NICHT implementiert)

Diese Punkte bleiben als eigene, separat freizugebende Folge-Prompts offen. Siehe `docs/FINDINGS_INDEX.md` für die Einzeleinträge:

- **Globales Log-Level** (`set_global_log_level()`): `Config.LOG_LEVEL` ist kein Teil des persistierten Schemas (L4-Entscheidung, §5). Eine Persistenz wäre eine echte Schemaerweiterung, keine Migration.
- **Modul-/Fehler-Statistiken** (`show_comprehensive_statistics()`, `_collect_comprehensive_stats()`, Modul-Log-Counts in `show_modules_list()`): reine Prozessspeicher-Zähler (`EnhancedLogger.stats`, `ExceptionMonitor`) — unverändert Cross-Process-blockiert, identisch zum bestehenden CC-AC-10D-Error-Administration-Finding.
- **Volle `loggerDict`-Introspektion** (`configure_handlers()`, `handler_details()`, `manage_handlers_advanced()`): deckt *alle* Python-Logger ab, nicht nur die im Runtime-Snapshot erfassten `_module_loggers` — kein zentrales Äquivalent vorhanden oder sinnvoll konstruierbar ohne neue Infrastruktur.
- **In-Process-Reload** (`reload_handlers()`): funktional das Telegram-Pendant zu L5s Apply/Restart, aber ohne Restart, weil In-Process — strukturell an den Bot-Prozess gebunden, kein Migrationsziel.
- **Cleanup-Funktionen** (`show_cleanup_menu()`, `_get_cleanup_statistics()`): kein Control-Center-Pendant. **Zusatzbefund:** die Cleanup-Aktions-Buttons (`logger_cleanup_old`/`_large`/`_empty`/`_rotated`/`_all_confirm`/`_archive`) sind im Dispatcher (`handle_logger_callback()`) nicht verdrahtet — ein Klick landet im „Funktion nicht implementiert"-Zweig. Vorbestehender Defekt, außerhalb dieses Migrations-Scopes.
- **Tote Route** `logger_search_module` → `logger_handler.search_module(...)`: diese Methode existiert nicht auf `EnhancedLoggerMenuHandler`. Kein Button erzeugt aktuell diesen `callback_data`-Wert (im Normalbetrieb unerreichbar), bei manuell konstruiertem `callback_data` würde ein unbehandelter `AttributeError` durchschlagen. Vorbestehender Defekt, außerhalb dieses Migrations-Scopes.
- **Nachtrag 2026-09-27 (Findings #31/#32, Branch `fix/findings-31-32-logger-callbacks`):** beide Zusatzbefunde oben sind geschlossen — Cleanup über die neue Service-Funktion `services/logger_admin.py::cleanup_rotated_log_files()` (nur rotierte Backups `<name>.log.<N>`), Telegram-Vorschau → Bestätigung für „alte rotierte Logs (>30 Tage)" und „alle rotierten Logs"; nicht sicher definierbare Buttons (Große/Leere Dateien, Alle bereinigen, Archivieren, `logger_cleanup_all_files`) entfernt; tote Route `logger_search_module` entfernt. Kein Control-Center-Endpunkt (Architektur sieht keinen vor). Details: `docs/FINDINGS_INDEX.md`.

---

## 8. Tests

| Datei | Änderung |
|---|---|
| `tests/test_logger_config_service.py` | `TestEnsureModuleConfigEntry` (8 neue Tests) |
| `tests/test_enhanced_logger_menu_handler_module_toggle.py` | `FakeConfig` um `DATA_DIR` erweitert; `TestEnableDisableAllModules` (6 neu), `TestSetModuleLevelPersistsAndAppliesLive` (4 neu); `NavidromeHandler` in Cleanup-Fixture ergänzt |
| `tests/test_enhanced_logger_menu_handler_error_handler.py` | `FakeConfig`/`handler`-Fixture um `DATA_DIR` + `Path`-Patch erweitert (zweiter, unabhängig gefundener Pfad-Isolationsfehler behoben); Fehlerinjektion in `TestToggleModuleErrorHandling` von `get_module_config()` auf `_apply_module_config()` verschoben (Methode wird nicht mehr aufgerufen); `TestEnableAllModulesErrorHandling`/`TestDisableAllModulesErrorHandling` (4 neu) |
| `tests/test_logger_menu_path_traversal.py` | 3 Assertions an neue (weiterhin sichere) Fehlermeldung angepasst |
| `tests/test_enhanced_logger_menu_handler_file_detail.py` | **neu** (4 Tests): Level-Zählung, Charakterisierung der behobenen Fehlzählung, chronologische Vorschau-Reihenfolge, Rohtext-Fallback |
| `tests/test_enhanced_logger_menu_handler_files_list.py` | **neu** (6 Tests): Sortierung nach mtime, rotierte Logs, fehlendes vs. leeres Verzeichnis, größte/älteste Datei |

**Regressionsergebnis (thematisch, während der Implementierung):** `pytest tests/ -k "logger or logging or enhanced_logger"` → 245 passed (vorher 221 vor L7); `pytest tests/ -k rich_menu` → 336 passed. 0 Failures über alle Zwischenschritte.

**Vom Nutzer ausgeführte volle Suite (2026-09-26):** **5633 passed, 1 skipped, 11 subtests passed, 0 failed** (343,70 s).

---

## 9. Bekannte Einschränkungen (vorbestehend, durch L7 nicht verschärft)

- **Pfad-Divergenz** zwischen `services/logger_admin.py` (`Config.DATA_DIR`) und `ModuleLoggerManager` (`Path("data/module_logger_config.json")`) — dokumentiert seit L4 (§11). In Produktion identisch (beide zeigen auf `<repo>/data/`), in Tests explizit synchronisiert (Fixtures dieser Session).
- **Kein Reload im laufenden Prozess für CC-Änderungen** — unverändert die L3-Entscheidung. Ein CC-PATCH ohne Bot-Neustart hat weiterhin keinen Runtime-Effekt auf den Bot; Telegram-Änderungen wirken dagegen weiterhin sofort (In-Process).
- Die in Abschnitt 7 gelisteten Kategorie-D-Punkte bleiben bewusst ungelöst.

---

## 10. Definition of Done — Abgleich

| Punkt | Status |
|---|---|
| L1–L6-Preflight gegen tatsächlichen Code verifiziert | erledigt (Abschnitt 1) |
| Widerspruch Dokumentation/Code gemeldet, nicht eigenmächtig entschieden | erledigt (FINDINGS_INDEX-Prep-Commit, separat) |
| Modul-Taxonomie vollständig verifiziert (keine Grep-Heuristik ungeprüft übernommen) | erledigt (Abschnitt 2) |
| Migration Boundary A/B/C/D erstellt | erledigt (Abschnitt 3) |
| Architekturentscheidung für die Modul-Lücke vom Nutzer getroffen, nicht von Claude | erledigt (Auto-Register-Funktion, Option 1) |
| Kleinste sinnvolle Schritte, einzeln getestet und freigegeben | erledigt (Schritte 2–6, je mit gezielten + thematischen Tests) |
| Keine neue Runtime-/IPC-Infrastruktur | erledigt |
| Keine Änderung an L4/L5/L6/Restart-Infrastruktur/Repair-Lock | erledigt |
| Regressionstests für jede Verhaltensänderung | erledigt (Abschnitt 8) |
| Bewusste Verhaltensänderungen explizit benannt, nicht stillschweigend | erledigt (Abschnitt 5) |
| Kategorie-D-Punkte dokumentiert statt eigenmächtig neu abstrahiert | erledigt (Abschnitt 7) |
| Volle Testsuite vom Nutzer ausgeführt, nicht von Claude | erledigt (Abschnitt 8) |

---

## Verweise

- L2–L6-Dokumente: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` bis `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md`
- Architecture Overview: `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`
- Findings-Index: `docs/FINDINGS_INDEX.md`
- Baseline: `docs/MusicBot_ENGINEERING_BASELINE_v11.md`
