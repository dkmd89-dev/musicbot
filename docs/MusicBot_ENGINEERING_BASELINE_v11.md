# MusicBot Engineering Baseline v11

> **Status: 🟡 DRAFT (noch nicht eingefroren).**
>
> Laufender Zwischenstand seit dem v10-Freeze (2026-09-14). Hier werden
> pro ARCH-Phase/PR „ARCH Status", „Recent Major Changes" und Testzahlen
> mitgeschrieben (CLAUDE.md „Baseline-Pflege"). Die Abschnitte 4–6
> (Technical Debt / Security-Baseline / Architecture Freeze) bleiben
> Platzhalter bis zum v11-Freeze — bis dahin ist
> `docs/MusicBot_ENGINEERING_BASELINE_v10.md` der zitierbare eingefrorene
> Referenzpunkt, `docs/FINDINGS_INDEX.md` die laufend gepflegte
> Findings-Quelle.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v11 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v10.md` (Freeze 2026-09-14, 4250 passed / 1 skipped / 0 failed / 11 subtests passed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl (aktuell, nach CC-LOGGER-L7 „Telegram-Migration") | **5633 passed, 1 skipped, 11 subtests passed, 0 failed, 6 warnings** (343,70 s), 2026-09-26. +160 gegenüber der zuletzt hier dokumentierten Zahl (5473, 2026-09-22) — deckt `control-center-navidrome` und CC-LOGGER-L2–L7 ab (Einzelergebnisse je Phase in `docs/FINDINGS_INDEX.md`). Unverändertes Skip-/Subtest-Muster (1/11) seit v9 durchgehend. Backlog-Runde 2 (2026-09-27, PR #333/#334/#335): reine Refactorings und additive CC-Jobs, keine neuen Testzahlen an dieser Stelle. Neue volle Suite steht beim Nutzer aus. |
| Zuwachs seit letztem hier dokumentiertem Stand | +160 passed (5473 → 5633), 0 failed |

---

## 2. ARCH Status seit v10-Freeze

| ARCH-Änderung | Commits | Ergebnis |
|---|---|---|
| **ARCH-033 „Telegram Level-2/Level-3 Repair (Pro-Artist)"** — letzte in ARCH-031 beschlossene, bis v10 noch offene Phase. Macht `METADATA_REPROCESSING` (L2) und `EXTERNAL_METADATA` (L3) über Telegram ausführbar, bewusst NUR pro Artist mit eigener Vorschau/Bestätigung (ADR-0003), nie als globaler Batch. Vier Phasen: (1) Service-Layer `execute_level2_repair()`/`execute_level3_repair()` in `repair_service.py` + Subprozess-Runner `run_level2_repair()`/`run_level3_repair()` in `doctor_runner.py`; (2) `group_candidates_by_artist()`/`ArtistCandidateSummary` in `planner.py`; (3) Telegram-Sub-Flow `l23rep:*` in `repair_musicbot_handler.py` inkl. Dispatcher-Verdrahtung; (4) dokumentierter, inaktiver Erweiterungspunkt für künftige COVER/LOUDNESS/DUPLICATE-Phasen (ARCH-034/035). Details: `docs/LIBRARY_REPAIR.md` §12, `docs/adr/0003` (IMPLEMENTED). | `64a7321`, `d4b1841`, `4e55801`, `d9436ba`, `f01ac9f` | 60 neue Tests, thematische Suite (`-k "repair or maintenance or menu or level or library_repair"`, 1305 Tests) grün, 0 Regressionen |

**Bewusste, nutzerbestätigte Abweichung von der ursprünglichen
Implementierungsvorgabe:** `execute_level2_repair()`/
`execute_level3_repair()` rufen `apply_level2()`/
`apply_external_metadata()` NICHT in-process über `asyncio.to_thread()`
auf (wie ursprünglich spezifiziert), sondern als eigenen Subprozess —
identisch zu `execute_safe_automatic_repair()`. Grund: `Enhanced-
MetadataProcessor` (`SingletonMixin`) wird bereits beim Bot-Start für
die Live-Download-Pipeline konstruiert; ein `asyncio.to_thread()`-Aufruf
hätte denselben Singleton potenziell gleichzeitig aus einem separaten
Thread heraus verwendet, während der Bot-Event-Loop weiterläuft — exakt
das Risiko, das den bestehenden Subprozess-Pfad von
`reprocessing_runner.py` ursprünglich begründet. Per `AskUserQuestion`
geklärt, Nutzer bestätigte „Subprozess statt in-process". Details:
`docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md`,
Abschnitt „Implementierung".

| **CC-AC-10A–D „Control Center Admin API Integration"** — Migration der bestehenden, bisher rein Telegram-basierten Administration auf client-unabhängige Application-Layer-Funktionen + Control-Center-API, gemäß freigegebener Master-Prompt `CC-AC-10.md`. 10A: vollständiges Admin-Inventar (26 Funktionen) + Architecture Contract (`ActorContext`-Vorschlag andockt an bereits Telegram-freie `permissions.py`-Logik). 10B: User Management (Create/Update/Delete) über neuen `services/user_admin.py`. 10C: Backup/Bot-Neustart/Wartungsmodus/Navidrome-Scan über `services/backup_admin.py` + Direktnutzung bereits Telegram-freier Bausteine (`bot_maintenance.py`, `bot_restart_trigger.py`, `navidrome_scan_trigger.py`). 10D: nur System-Status (`services/system_status.py`) — Logger-Konfiguration und Error-Administration bewusst zurückgestellt (Cross-Prozess-Blocker: beide Daten leben nur im Bot-Prozess-Speicher, Control Center läuft separat; Logger-Configs werden zusätzlich nur einmal beim Bot-Start geladen). Telegram-Seite in allen vier Phasen bewusst unverändert (Migration darauf ist eigener, späterer Slice CC-AC-10G). Admin-Web-Parität laut CC-AC-10A-Matrix: von 12/26 auf 24/26 (Artist-Metadata-Reprocessing #25 laut Nutzer-Entscheidung dauerhaft ⚪ ausgeschlossen, keine offene Lücke). Details: `docs/audits/CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md` bis `CC-AC-10D_DIAGNOSTICS_MONITORING_API_2026-09-22.md`. | siehe Einzel-PRs dieser Session | 87 neue/erweiterte Tests über die vier Phasen (Application-Layer-Unit-Tests + HTTP-API-Tests), 0 Regressionen, thematische Suiten je Phase grün |
| **`control-center-navidrome` (Navidrome Full Integration im Control Center)** — Erweiterung der bisherigen Navidrome-Status-Anbindung (2026-09-15) zur vollständigen REST-Parität mit dem Telegram-`NavidromeMenuHandler`. 18 neue Endpunkte (Browse/Detail/Suche/Entdecken/Playlist-CRUD/Cover-Proxy) in `control_center/routers/navidrome.py` (20 gesamt), ~25 neue Pydantic-Schemas in `control_center/schemas/navidrome.py`, neuer `fetch_cover_art()`-Helper in `services/clients/navidrome_api.py` (Subsonic `getCoverArt` liefert Bytes, nicht JSON). Frontend: 7 Tabs, Modal-Stack-Navigation mit Breadcrumb, Cover-Art-Cards. Telegram-Seite bewusst unverändert; beide Consumer teilen weiterhin nur den `NavidromeAPI`-Adapter, keinen gemeinsamen Zustand, keine Business-Logik, keine wechselseitigen Imports. Details: `docs/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`. Volle Suite auf dem Branch: 5445 passed / 1 skipped / 6 warnings / 11 subtests passed (322,78 s, 2026-09-23). | siehe Branch `control-center-navidrome` | 20 Endpunkte (2 → 20), ~25 Schemas (2 → ~25), Frontend-Rewrite mit Modal-Stack; 0 Regressionen (bestehende Navidrome-Status-Tests unverändert grün) |
| **CC-LOGGER-L2 (Logger Read API)** — erster Schritt aus dem Phasenplan `logge.txt` (L1–L7). Reine Read-API für die Klasse-A-Logger-Funktionen (shared filesystem). Neuer Application-Layer `services/logger_admin.py` (Telegram-frei, FastAPI-frei), neuer Router `control_center/routers/logger.py` unter `/api/v1/admin/logger/*`, ADMIN-gated, 3 Endpunkte (Dateiliste/Statistiken/Detail). **Klasse B (Runtime-Control) bewusst DEFERRED** — L1-Analyse ergab prozesslokalen Bot-Zustand ohne Inbound-Kanal (einziger Mechanismus: `systemctl restart`). `module_logger_config.json` bewusst nicht exponiert — L1-Fund: `ModuleLoggerManager._load_module_configs()` wendet die JSON beim Bot-Start nicht an. Route-Reihenfolge kritisch (`/files/stats` vor `/files/{name}`). Limit-Grenzen server-seitig (Default 200, Min 1, Max 2000, HTTP 422 bei Verletzung — kein stilles Clamping; zusätzlich defensiv im App-Layer). Details: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`. Testergebnis: 86 passed (Log-Suiten) + 529 passed (`control_center`-Suite). | `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` | 3 Endpunkte, 1 neuer Application Layer, 1 neuer Router, 2 neue Schemas; 0 Regressionen (`/api/v1/logs` unverändert) |
| **CC-LOGGER-L3 (Runtime-Control Architecture Decision)** — Analyse-Phase, kein Code. Architektur-Entscheidung für Logger-Runtime-Control im MusicBot. Kernbefund: es existiert heute KEIN Cross-Process-Runtime-Kanal (keine IPC, kein Socket, kein File-Watcher, kein Reload-Trigger); einziger Steuerungs-Mechanismus ist `systemctl restart bot`. Zusätzlich: `ModuleLoggerManager._load_module_configs()` wendet die JSON beim Bot-Start nicht an — persistente Config ist keine Runtime-Wahrheit. Empfohlener Pfad (verbindlich für L4–L6): Stufe 0 (Startup-Apply-Bugfix) → Stufe 1 (E2 Persistent Config über CC, Semantik „nächster Start“) → Stufe 2 (Runtime Snapshot, read-only Observability) → Stufe 3 (kontrollierter Apply/Restart mit Preflight + Rate-Limit). Stufe 4 (Unix-Socket Runtime Write) explizit DEFERRED, nur bei belegtem Bedarf. Verworfen: File-Watcher als dauerhafte Runtime-Infrastruktur, Localhost-HTTP, jeder unnötige neue IPC-Stack. Details: `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`. | `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` | Docs-only, 0 Code-Änderungen, 0 Regressionen |
| **CC-LOGGER-L4 (Startup Apply + Persistent Logger Configuration)** — erster Umsetzungsschritt nach der L3-Entscheidung. Behebt den Startup-Apply-Bug in `ModuleLoggerManager._load_module_configs()` (JSON wurde geladen, aber nicht angewendet — persistierte Level/Handler waren fuer den laufenden Prozess wirkungslos). Neue Application-Layer-Funktionen in `services/logger_admin.py`: `read_logger_config()`, `validate_logger_config_patch()`, `update_logger_config()` (atomarer Write via .tmp+replace), `LoggerConfigError`. Neue Endpunkte unter `/api/v1/admin/logger/config`: `GET` (persistierte Konfiguration, ADMIN) + `PATCH` (merge-by-module + merge-by-field, ADMIN + CSRF, strikte Validierung). **Semantik ehrlich: „wirksam beim naechsten Bot-Start" — kein Runtime-Control, kein IPC, kein Restart.** Kein Schema-Bruch, keine neue Abhaengigkeit. **Verhaltensaenderung:** ab dem ersten Neustart nach dem Fix werden 40 Module je eine Log-Datei anlegen, 18 davon auf DEBUG. Details: `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`. | `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md` | 2 Endpunkte (GET/PATCH), 1 Bug-Fix, 47 neue Tests (12 Startup-Apply + 35 App-Layer-/HTTP-Config); 131/540/168 passed ueber die drei Regressionssuiten, 0 Regressionen |
| **CC-LOGGER-L5 (Runtime Snapshot + Controlled Apply/Restart)** — Stufe 2 + Stufe 3 aus der L3-Entscheidung. **Stufe 2 (Snapshot):** Bot schreibt beim erfolgreichen Startup `data/logger_runtime_snapshot.json` (atomic write, aus dem tatsaechlichen `logging.getLogger(name).level/handlers/disabled` — NICHT aus der Config). Neuer Endpoint `GET /api/v1/admin/logger/runtime-status` (ADMIN, read-only, 3 Zustaende: available/missing/corrupt, Semantik explizit "state_after_last_successful_bot_start"). **Stufe 3 (Apply):** Neuer Endpoint `POST /api/v1/admin/logger/apply` (ADMIN + CSRF + Rate-Limit 60s, Single-Flight via threading.Lock). Dreistufige Preflight-Semantik: `blocked` (Repair-Lock aktiv → HTTP 409, keine Mutation, kein Restart), `unverified` (Lock frei, aber Downloads/Backups unpruefbar → Restart mit strukturierter Warnung), `clear` (aktuell unerreichbar, da UNVERIFIABLE_ACTIVITY_CATEGORIES nicht leer). Restart ueber bestehenden `BotRestartTrigger.trigger_restart("bot")`, unveraendert. **Kein IPC, kein Socket, keine neue State-Registry.** Bugfix am globalen HTTPException-Handler in `control_center/app.py` (reicht jetzt `exc.headers` durch, betrifft `Retry-After` bei 429). Details: `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md`. | `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md` | 2 neue Endpunkte (runtime-status, apply), 2 neue App-Layer-Funktionen (write_runtime_snapshot/read_runtime_snapshot + evaluate_apply_preflight + LoggerApplyRateLimiter), 35 neue Tests; 103 + 552 + (Logger-Suite) passed, 0 Regressionen |
| **CC-LOGGER-L6 (Logger-Verwaltungs-UI)** — UI-only, keine Backend-Aenderung. Neue Seite `/logger` (eigenes Template + eigene JS-Datei, Stack-Pattern wie /statistics) mit vier Panels: Runtime-Status (KPI + Tabelle, Zustaende available/missing/corrupt), Persistierte Konfiguration (Tabelle, Semantik "wirksam beim naechsten Start"), Desired-vs-Actual-Diff (berechnet aus State, kein neuer API-Call), Apply (einziger POST /api/v1/admin/logger/apply-Call, Antwort bestimmt die Darstellung: unverified/clear/blocked/config_missing/429/403). Rate-Limit-Countdown aus Retry-After-Header. Wiederverwendet: common.js-Helper (apiUrl/checkAuth/_loadInto/_escapeHtml/showOnly), common.css-Klassen, Tabler-Komponenten. Keine Aenderung an common.js/common.css. Kein Config-PATCH-UI (bewusst ausserhalb L6). Details: `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md`. | `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md` | 1 neue Seite, 1 neue JS-Datei, 4 Panels, 6 neue UI-Tests; 218 + 560 passed, 0 Regressionen |
| **CC-LOGGER-L7.1 (Setup-Module-Logging Config-Respekt)** — behebt einen Folgebefund aus dem L6.1/L6.2-Browser-Test. `logger.py::setup_module_logging()` hat `level` hart gesetzt und IMMER einen FileHandler + ConsoleHandler angehaengt, unabhaengig von der Config. Zwei Aufrufer (`EnhancedMetadataProcessor`, `EnhancedLoggerMenuHandler`) haben dadurch die Config-Werte ueberschrieben, wenn sie NACH dem `_load_module_configs()`-Lauf konstruiert wurden. Fix: zwei additive Parameter (`enable_file_handler`, `enable_console_handler`, Default True); Config-Aufloesung in beiden Aufrufern ueber `read_logger_config()`; Fallback-Werte identisch zum bisherigen harten Aufruf. Rotation (EnhancedRotatingFileHandler, 2 MB x 3) bleibt unveraendert. 9 neue Tests. Details: `docs/audits/CC-LOGGER-L7.1_SETUP_MODULE_LOGGING_CONFIG_2026-09-27.md`. | `docs/audits/CC-LOGGER-L7.1_SETUP_MODULE_LOGGING_CONFIG_2026-09-27.md` | 1 Kernfunktion + 2 Aufrufer + 9 neue Tests, 0 Regressionen |
| **CC-LOGGER-L7 (Telegram-Migration)** — migriert `EnhancedLoggerMenuHandler` (Telegram) auf dieselbe Fachlogik wie Control Center statt eigener Parallelimplementierung. `toggle_module`/`set_module_level`/`enable_all_modules`/`disable_all_modules` nutzen jetzt `services/logger_admin.py::update_logger_config()` (statt eigenem, nicht-atomarem Save-Pfad); `show_log_file_detail`/`show_log_files_list`/`show_log_files_stats` nutzen `get_log_file()`/`list_log_files()`/`get_log_file_stats()`. **Verifizierter Vorbefund:** 54 von 75 real aktiven Modulnamen fehlten in `data/module_logger_config.json` (41 real reaktivierbar, mehrheitlich P0). **Nutzerentscheidung:** neue, nicht per HTTP exponierte `ensure_module_config_entry()` schließt die Lücke, ohne die L4-Entscheidung für die öffentliche API aufzuweichen. Bewusste Verhaltensänderungen: korrekte statt naive Level-Zählung, konsolidierte Traversal-Fehlermeldung, Sortierung nach mtime statt Größe, rotierte Logs jetzt sichtbar, erweiterte Datei-Statistik. Kategorie-D-Funktionen (globales Log-Level, Modul-/Fehler-Statistiken, volle loggerDict-Introspektion, In-Process-Reload, Cleanup) bewusst nicht migriert, als OPEN-Findings dokumentiert. 2 vorbestehende Defekte gefunden (kaputte Cleanup-Callback-Verdrahtung, tote `logger_search_module`-Route). Details: `docs/audits/CC-LOGGER-L7_TELEGRAM_MIGRATION_2026-09-26.md`. | `docs/audits/CC-LOGGER-L7_TELEGRAM_MIGRATION_2026-09-26.md` | 1 neue App-Layer-Funktion (`ensure_module_config_entry`), 7 migrierte Telegram-Funktionen, 22 neue Tests über 4 Testdateien (2 davon neu); 245 + 336 passed (thematisch), volle Suite 5633 passed / 0 failed |
| **CC-LOGGER-L6.1 (File Handler Control)** — UI-only-Nachtrag zu L6 (nicht L8, das bleibt Parity-Audit). Spalte „File" in Panel 2 von `/logger` schaltet `file_handler` bereits persistierter Module über das bestehende `PATCH /api/v1/admin/logger/config`; wirksam erst nach Apply/Restart (L5), kein Live-Control. Kein neuer Endpoint, keine Backend-Änderung, `ensure_module_config_entry()` unverändert. | PR #307 (`dc2886e`, Branch `feat/cc-logger-l6-1-file-handler-control`) | 11 neue Tests; 680 passed (thematisch), volle Suite steht beim Nutzer aus. Nachgezogener P3-Fix: Diff-Panel erkennt `EnhancedRotatingFileHandler` jetzt als Log-Datei (+5 node-Tests, 685 passed thematisch). Neuer Befund (P3): `setup_module_logging()` übersteuert persistiertes `file_handler` — inzwischen durch L7.1 (PR #308) geschlossen |
| **CC-LOGGER-L6.2 (Level Control)** — UI-only-Nachtrag zu L6/L6.1. Spalte „Level" in Panel 2 von `/logger` ist eine Auswahl mit exakt `ALLOWED_LOG_LEVELS` (Reihenfolge wie Telegram), sendet über das bestehende `PATCH /api/v1/admin/logger/config` nur `{level}`; wirksam erst nach Apply/Restart. Kein neuer Endpoint, keine Backend-Änderung. PATCH-Ablauf mit L6.1 gemeinsam (`_loggerPatchModuleConfig()`). | PR #307 (`dc2886e`, Branch `feat/cc-logger-l6-1-file-handler-control`) | 27 neue Tests; 712 passed (thematisch), volle Suite steht beim Nutzer aus. Bestehender Befund `setup_module_logging()`-Übersteuerung um `level` ergänzt — inzwischen durch L7.1 (PR #308) geschlossen |
| **Backlog-Punkt 2 (Backups)** — Telegram-Handler delegiert an `services/backup_admin.py`; keine eigene tar-/Rotationslogik mehr; `_archive_filter` → öffentlich `archive_filter`; Pfad-/Limit-Konstruktion über `BackupPaths.from_config()`. Verhaltensänderung: `delete_backup()` intern jetzt `BackupNotFoundError` (Nutzertext unverändert). 40 + 114 + 74 + 68 thematische Tests grün. | PR #333 | Backlog 2 → CLOSED |
| **Backlog-Punkt 4a (Duplikat-Check im CC)** — neuer Job-Typ `duplicate_check` (`POST /api/v1/jobs/duplicate-check`); dünner Router um `services/library_repair/duplicate_runner.py::run_duplicate_scan()`; UI-Panel in `library_artist_detail.html`. Bewusst read-only, kein `-apply`-Gegenstück. 10 + 10 + 326 + 463 thematische Tests grün. | PR #334 | Backlog 4a → CLOSED |
| **Backlog-Punkt 8 (AccessLevel/permissions-Move)** — neue kanonische `services/access_control.py`; `handlers/menu/models.py`/`permissions.py` werden Re-Export-Shims; 18 CC-Dateien auf direkten `services/`-Import umgestellt; `CLAUDE.md` §4 Ausnahme entfernt (bewusster Eingriff). Reiner Move, 0 Verhaltensänderung (per Identitätscheck bestätigt). 136 + 195 + 1519 thematische Tests grün. | PR #335 | Backlog 8 → CLOSED |
| **Client Consolidation Phase C (Web-Parity Audit, reine Doku)** — Matrix aus Abschnitt 2.1 des Audits gegen den aktuellen Code neu verifiziert; Zeilen „Benutzerverwaltung“ und „Logger-Verwaltung“ von 🟠 auf ✅; Backlog und Doppelimplementierungs-Liste bereinigt; neuer Abschnitt 9 „Verifikation nach Phase C“ im Audit; Findings-Index-Kopfzeile aktualisiert. Kein Code-Change, kein Testlauf erforderlich. | `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` §9, `docs/FINDINGS_INDEX.md` | Docs-only, 0 Code-Änderungen, 0 Regressionen |
| **Findings-Closure (#17, #4/#5/#6, #31/#32) + Doku-Konsistenz-Audit** — atomare Persistenz Lyrics/Play-History; einheitliche Repair-Ergebnissemantik (Core/Telegram/CC-Job/UI, neuer Run-Status `UNRESOLVED`, Exit-Code ≠ 0 nie mehr SUCCESS); Logger-Cleanup (nur rotierte Backups) + tote Route entfernt; ADR-0001/0002-Status, `resolve_duplicates.py`-Kommentar, Findings-Index-Lifecycle bereinigt. Details: `docs/FINDINGS_INDEX.md`, `docs/LIBRARY_REPAIR.md` („Einheitliche Ergebnissemantik"). | Branches `fix/findings-17-atomic-persistence`, `fix/findings-4-5-6-repair-result-semantics`, `fix/findings-31-32-logger-callbacks`, `docs/findings-consistency-audit` (noch nicht gemergt) | 3 neue Testdateien (12 + 56 + 37 Tests); thematisch 293 / 1387 / 641 passed; volle Suite steht beim Nutzer aus |
| **Client Consolidation D.12a (Control-Center-Prozess-Logging)** — `control_center/app.py::setup_control_center_logging()` ruft beim Startup-Event (nur unter uvicorn, nicht bei `httpx.ASGITransport` in Tests) das bestehende `setup_enhanced_logging()` mit eigener Datei `LOG_DIR/control_center.log` auf (nicht `bot.log`, kein Zwei-Prozess-Rotieren). Vorher hatte der CC-Prozess keinen Root-Handler: INFO von `YoutubeDownloader`/`pipeline_core`/`JobRegistry` usw. ging bei Web-Downloads verloren. Keine neue Logging-Infrastruktur, kein Log-Format geändert. | D.12a (Branch `optimieren`) | neu `tests/test_control_center_logging_startup.py` (4 Tests, Vor-Fix 4 failed); thematisch `-k "control_center or logs_reader or logger_admin or logging_startup"` 673 passed / 58 skipped / 4 errors (umgebungsbedingt: `ffmpeg` fehlt, identisch zur Baseline vor der Änderung); `-k "logger or logging or logs"` 455 passed. Volle Suite: durch Nutzer. |
| **Client Consolidation D.12b (Schritt-Verlauf pro Job)** — additives `Job.events` (`JobEvent`, max. 100, älteste zuerst) in `services/jobs/`, befüllt von `JobRegistry` bei Status-/Fortschrittswechseln (deduplizierte Meldungen), je Eintrag INFO `🧩 [JOB <id8>] …` in `control_center.log`; `JobSchema.events` additiv; Downloads-UI zeigt Verlauf laufend und im Ergebnis („Verlauf“). `_run_download_job()`, Download-/Metadaten-/Duplikat-Logik unverändert. | D.12b (Branch `optimieren`) | +12 Tests (Vor-Fix 11 failed, 1 Characterization-Test für `job.message` vorher/nachher grün); thematisch `-k "job or control_center or download"` 1104 passed / 60 skipped / 4 errors (umgebungsbedingt `ffmpeg`, identisch vor der Änderung). Volle Suite: durch Nutzer. |
| **Client Consolidation D.12c (feine Metadaten-Schritte im Job-Verlauf)** — neu `services/jobs/step_context.py` (task-lokaler Schritt-Melder über `contextvars`, isoliert pro asyncio-Task trotz Singleton-Processor und paralleler Jobs; ohne Melder No-op, Melder-Fehler geschluckt). `EnhancedMetadataProcessor.process_single_track()`: 11 additive `report_step()`-Aufrufe neben bestehenden INFO-Logs (Reihenfolge/Rückgabe/Fallbacks unverändert). `_run_download_job()` setzt den Melder nur bei Single-Downloads (Präfix „Metadaten: “). | D.12c (Branch `optimieren`) | +11 Tests (`test_step_context.py` 5, `test_enhanced_metadata_processor_step_reporting.py` 4 inkl. Characterization „Ergebnis mit/ohne Melder identisch“, `test_control_center_download_jobs.py` +2); Vor-Fix (Processor/Router alt) 3 failed = genau die Feature-Tests; thematisch `-k "metadata or download or job or control_center or step"` 1415 passed / 68 skipped / 4 errors (umgebungsbedingt `ffmpeg`); alle Processor-nutzenden Testdateien 325 passed / 6 skipped. Volle Suite: durch Nutzer. |
| **Client Consolidation D.13 (Cross-Process-Persistenz Download-Verlauf + Duplikat-Cache)** — reproduziertes Lost Update (Bot-Instanz langlebig, CC-Instanz pro Job, beide schreiben ihren kompletten Stand) geschlossen: `utils/file_lock.py::cross_process_lock()` (verschoben aus `services/user_data.py`, dort per Alias unverändert genutzt); `DownloadHistoryStore.add_entry()` und alle `DuplicateCache`-Operationen als Lock → Neu laden bei Dateiänderung → Operation → atomar schreiben, Lesezugriffe laden bei Änderung neu; `DuplicateDetector.invalidate_entry()` über `DuplicateCache.transaction()`. Duplikat-Logik/Ebenen/Format/Signaturen unverändert. | D.13 (Branch `optimieren`) | `tests/test_cross_process_persistence.py` 10 Tests (ohne Fix 8 failed, 3× reproduzierbar; 2 Schutztests für unlesbare Dateien vorher/nachher grün); thematisch `-k "duplicate or history or download or user_data or cross_process or file_lock or playlist or control_center or metadata or job"` 2036 passed / 89 skipped / 2 failed + 4 errors (alle umgebungsbedingt `ffmpeg`, identisch auf `main`). Volle Suite: durch Nutzer. |
| **Web-Parität Backlog 4b (Duplikat-Cache-Verwaltung im Web)** — neu `services/duplicate/admin.py` über `DuplicateCache.entry_stats()`/`clear()` unter dem D.13-Lock; Telegram `execute_clear_cache()` delegiert (Verhalten per Characterization unverändert); CC `GET/POST /api/v1/admin/duplicates/{stats,clear}` (ADMIN, Same-Origin, confirm) + Admin-Karte. Sitzungszähler folgen mit E1. | 4b (Branch `optimieren`) | +17 Tests (`test_duplicate_admin_service.py` 7, `test_control_center_admin_duplicates_api.py` 7, Telegram-Characterization +2, UI +1); thematisch `-k "duplicate or control_center or admin or cross_process or layer or boundary or menu"` 2193 passed / 81 skipped / 2 failed + 4 errors (umgebungsbedingt `ffmpeg`, identisch auf `main`). Volle Suite: durch Nutzer. |
| **Web-Parität Backlog 5 / E1 (Bot-Runtime-Snapshot)** — neu `services/bot_runtime_snapshot.py` (atomarer Write, Read mit available/stale/missing/corrupt, `sanitize_exception_record()`); `EnhancedErrorHandler.export_snapshot_section()`, `DuplicateDetector.snapshot_section()`; `bot.py::_periodic_runtime_snapshot()` (60 s + Start/Shutdown); CC `GET /api/v1/admin/runtime-snapshot` (ADMIN, read-only) + Admin-Karte „Fehlerstatistik (Bot)“; Datenschutz streng (kein Kontext/Stacktrace, redigierte Message). `services/logs/reader.py::redact_secrets` als öffentlicher Alias. | E1 (Branch `optimieren`) | +28 Tests (`test_bot_runtime_snapshot.py` 12, `test_runtime_snapshot_sections.py` 4, `test_bot_runtime_snapshot_task.py` 5, `test_control_center_runtime_snapshot_api.py` 6, UI +1); thematisch `-k "error or control_center or duplicate or runtime or snapshot or admin or logs or logger or layer or boundary"` 2134 passed / 85 skipped / 2 failed + 4 errors (umgebungsbedingt `ffmpeg`, identisch auf `main`). Volle Suite: durch Nutzer. |
| **Web-Parität Backlog 9 (Login mit Navidrome-Benutzer, auch ohne Telegram)** — `verify_navidrome_credentials()` (Navidrome `POST /auth/login`), neu `services/web_auth.py` (Zuordnung, einheitliches invalid, Rate-Limit, Obergrenze ADMIN), `create_web_user()` (negative IDs), Session-Cookie mit `auth` (alte Cookies gültig), `POST /api/v1/auth/navidrome-login`, `POST /api/v1/admin/web-users`, UI-Formulare; nginx braucht `X-Forwarded-For`. | Backlog 9 (Branch `optimieren`) | +35 Tests (`test_web_auth.py` 19, `test_control_center_navidrome_login.py` 9, Admin-API +5, UI +2); bestehende Auth-Tests unverändert grün; thematisch `-k "auth or control_center or user or admin or navidrome or access or permission or menu or web_auth or session or layer or boundary"` 2090 passed / 64 skipped / 4 errors (umgebungsbedingt `ffmpeg`, identisch auf `main`). Volle Suite: durch Nutzer. |
---

## 3. Recent Major Changes (seit v10-Freeze)

- **Web-Parität Backlog 9 (Navidrome-Login, 2026-09-28):** Das Control Center ist jetzt auch ohne Telegram-Konto nutzbar — Anmeldung mit vom Admin freigeschaltetem Navidrome-Benutzer (Rolle höchstens ADMIN), abgesichert gegen Passwort-Leaks und Durchprobieren.

- **Web-Parität Backlog 5 / E1 (Bot-Runtime-Snapshot, 2026-09-28):** Fehlerstatistik des Bots und Duplikat-Sitzungszähler jetzt read-only im Control Center (Stand alle 60 s, streng bereinigt); Zurücksetzen bleibt Telegram.

- **Web-Parität Backlog 4b (Duplikat-Cache-Verwaltung, 2026-09-28):** Statistik und „Cache leeren“ jetzt auch im Control Center (Admin-Seite), gemeinsame Service-Implementierung mit Telegram, Leeren läuft unter dem D.13-Lock.

- **Client Consolidation D.13 (Cross-Process-Persistenz, 2026-09-28):** Download-Verlauf und Duplikat-Cache verlieren keine Einträge mehr, wenn Bot und Control Center abwechselnd oder parallel herunterladen (vorher überschrieb jeder Telegram-Download die Web-Einträge). `flock`-Muster aus Phase A nach `utils/file_lock.py` gezogen und wiederverwendet. Restlücke `_in_flight` nur pro Prozess (P3) im Findings-Index.

- **Client Consolidation D.12c (feine Metadaten-Schritte, 2026-09-28):** Single-Downloads zeigen im Job-Verlauf zusätzlich „Metadaten: Cache prüfen… / Künstler / Titel / Genre / Lyrics / Cover / Album & Jahr / ReplayGain / Bibliothek / Tags“. Task-lokaler Melder (`contextvars`), Telegram-Pfad und `scripts/` unverändert.

- **Client Consolidation D.12b (Schritt-Verlauf pro Job, 2026-09-28):** jeder CC-Job führt einen begrenzten Verlauf (`events`), sichtbar in der Downloads-UI und per Job-ID-Präfix in `control_center.log`. Grob (Pipeline-Meilensteine); feine Metadaten-Schritte bewusst nicht enthalten.

- **Client Consolidation D.12a (Control-Center-Prozess-Logging, 2026-09-28):** der CC-Prozess initialisiert beim Startup das bestehende `setup_enhanced_logging()` mit eigener Datei `logs/control_center.log`. Web-Download-Logs (`YoutubeDownloader`, `pipeline_core`, `DuplicateDetector`, `JobRegistry`, `control_center.jobs`) sind damit erstmals im Logger-Dashboard sichtbar (Datei-Discovery `*.log*` unverändert). Job-Zuordnung/Timeline (D.12b) und das Zwei-Prozess-Rotieren von `enhanced_metadata_processor.log` bleiben offen (`docs/FINDINGS_INDEX.md`).

- **Backlog-Runde 2 (Backups, Duplikat-Check-CC, AccessLevel-Move, 2026-09-27):** drei weitere Punkte aus dem Web-Parity-Audit §2.3 B/D geschlossen.
  - **Backups** (Backlog 2, PR #333): Telegram-Handler delegiert an `services/backup_admin.py` — analog Phase A/B.
  - **Duplikat-Check im CC** (Backlog 4a, PR #334): neuer Job-Typ `duplicate_check` (`POST /api/v1/jobs/duplicate-check`), UI-Panel in `library_artist_detail.html`, read-only.
  - **AccessLevel/permissions-Move** (Backlog 8, PR #335): neue kanonische `services/access_control.py`; Shims in `handlers/menu/`; 18 CC-Dateien umgestellt; `CLAUDE.md` §4 Ausnahme entfernt.
  - Doku-Angleichung: PR #336 (Matrix, Backlog, Findings-Index, §12).

- **Client Consolidation Phase C (Web-Parity Audit, 2026-09-28):** reine Dokumentations-Phase ohne Code-Change. `docs/audits/WEB_PARITY_TELEGRAM_CLIENT_AUDIT_2026-09-27.md` wurde um Abschnitt 9 ergänzt: die Paritätsmatrix aus 2.1 wurde gegen den aktuellen Code (nicht aus PR-Beschreibungen übernommen) verifiziert; „Benutzerverwaltung“ und „Logger-Verwaltung“ sind von 🟠 auf ✅ umgestellt (Belege: `services/user_data.py::update_user_data()` mit `fcntl.flock`; `services/logger_admin.py::atomic_write_json()` + `read_logger_config()` in `enhanced_logger_menu_handler.py`); Backlog und Doppelimplementierungs-Liste bereinigt; Gesamtstatus bleibt DECISION PENDING. `docs/FINDINGS_INDEX.md` Kopfzeile entsprechend aktualisiert. Kein Testlauf erforderlich (reine Doku).

- **ARCH-033 Phase 1 (Service-Layer):** `LevelRepairResult`-Dataclass,
  `_execute_level_repair()` (gemeinsame Implementierung für L2/L3,
  Stale-Plan-Schutz identisch zu `execute_safe_automatic_repair()`,
  Verification-Scan nur bei mind. 1 Erfolg, Finding-Resolution nur für
  tatsächlich verifiziert behobene Findings). Während der Umsetzung ein
  echter Architektur-Konflikt entdeckt und per Rückfrage geklärt (siehe
  oben). Dabei zusätzlich ein Late-Binding-Bug gefunden und behoben: ein
  beim Import gebautes `{"l2": run_level2_repair, ...}`-Dict hätte
  `patch.object()` in Tests ignoriert und einen echten Subprozess gegen
  die Produktionslibrary gestartet (in einem Testlauf tatsächlich
  passiert, verifiziert folgenlos — kein Treffer, da der Test-Artist
  nicht real existierte — und sofort gefixt: Namens-Lookup über
  `globals()[...]` zur Aufrufzeit statt eines früh gebundenen Dicts).
  Dasselbe Prinzip wurde in Phase 3 für den Telegram-Handler
  übernommen.
- **ARCH-033 Phase 2 (Artist-Gruppierung):** `group_candidates_by_artist()`
  gruppiert einen `RepairPlan` nach Artist mit getrennten L2-/L3-Zählern,
  sortiert nach Gesamtzahl absteigend, dann alphabetisch, deterministisch.
- **ARCH-033 Phase 3 (Telegram-Flow):** neuer `l23rep:*`-Sub-Flow auf
  `RepairMusicBotHandler` (kein neuer Handler — L2/L3 sind wie
  SAFE_AUTOMATIC Findings-getrieben, ADR-0001): Artist-Liste
  (index-basiert, paginiert, pro Telegram-Session in `context.user_data`
  gecacht, um nicht bei jedem Button-Tap einen vollen Health-Scan
  auszulösen) → Aktionsauswahl → read-only Preview mit
  levelspezifischem Warnhinweis → explizite Bestätigung → Ausführung →
  Ergebnis. Neuer Button „🛠️ L2/L3-Reparaturen (nach Artist)" in den
  bestehenden Reparaturvorschlägen, sichtbar sobald L2/L3-Kandidaten
  vorhanden sind.
- **ARCH-033 Phase 4 (Registry-Vorbereitung):** rein dokumentarischer,
  inaktiver Erweiterungspunkt neben den `_L23REP_*`-Dicts in
  `repair_musicbot_handler.py` — zeigt, wie eine künftige ARCH-034/035
  COVER/LOUDNESS/DUPLICATE an denselben generischen Flow anschließen
  würde, ohne neuen Callback-Namensraum. Kein aktiver Code.
- Dokumentation: `docs/LIBRARY_REPAIR.md` §12 (neu), `docs/adr/0003`
  PROPOSED → IMPLEMENTED (inkl. der zwei dokumentierten Abweichungen —
  Subprozess statt in-process, sowie Verification-Scan library-weit statt
  artist-gescoped, da kein artist-gescopter Scan-Modus existiert und
  ADR-0004 einen zweiten Scan-Mechanismus ausschließt), `docs/FINDINGS_INDEX.md`
  (ARCH-033 CLOSED, neuer OPEN-Eintrag für ARCH-034/035, P3), `docs/INDEX.md`.
- **`control-center-navidrome` (Navidrome Full Integration):** der
  `NavidromeMenuHandler` des Telegram-Bots ist jetzt vollständig auch
  über die Web-API abgebildet — 20 Endpunkte in
  `control_center/routers/navidrome.py`, ~25 Pydantic-Schemas in
  `control_center/schemas/navidrome.py`, ein `fetch_cover_art()`-Helper
  in `services/clients/navidrome_api.py`. Bewusste Architektur-Abgrenzung:
  kein gemeinsamer Zustand, keine gemeinsame Business-Logik, keine
  wechselseitigen Imports zwischen Telegram-Handler und Control-Center-
  Router; beide Consumer teilen weiterhin denselben `NavidromeAPI`-Adapter
  (`services/clients/navidrome_api.py`), wie durch `ARCH-009 Phase 8`
  etabliert. Neue Frontend-Seite mit 7 Tabs und Modal-Stack-Navigation
  (Breadcrumb, Back-Button, ESC). Behebt einen konkreten Navigationsbug
  im Artist-Detail (Root-Cause: `d-none` auf dem Back-Button bei
  Stack-Tiefe 1 plus unsichtbarer `.btn-close` im Dark-Theme).
  Details: `docs/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`.

- **CC-LOGGER-L2 (Logger Read API):** erster Schritt aus dem Phasenplan
  `logge.txt` (L1–L7). Neuer Application-Layer
  `services/logger_admin.py` (Telegram-frei, FastAPI-frei) + neuer
  Router `control_center/routers/logger.py` unter
  `/api/v1/admin/logger/*` (ADMIN-gated). Drei Endpunkte:
  `/files` (Dateiliste nach mtime), `/files/stats` (Aggregat),
  `/files/{name}` (Detail + Filter + Limit). Ruft ausschließlich
  `services/logs/reader.py` auf — kein zweiter Parser.

  **Klasse B (Runtime-Control: Modul-/Global-Level, Enable/Disable,
  Handler-Manipulation) bewusst DEFERRED.** L1-Analyse ergab:
  `_module_loggers`/`loggerDict`/`Logger.handlers` sind ausschließlich
  prozesslokal im Bot-Prozess; der einzige vorhandene
  Steuerungs-Mechanismus ist `systemctl restart` (voller Neustart,
  kein Skalpell). Kein Inbound-Kanal → keine ehrliche Write-API in L2
  möglich (`logge.txt` §4/§15: keine Runtime-Control vortäuschen).

  **`module_logger_config.json` bewusst nicht exponiert** — L1-Fund:
  `ModuleLoggerManager._load_module_configs()` liest die JSON beim
  Bot-Start, ruft aber `_apply_module_config()` **nicht** auf; die
  Datei ist keine Runtime-Wahrheit. Ein Read-Endpoint würde eine
  Genauigkeit vortäuschen, die die Datenquelle nicht hat.

  **Limit-Grenzen server-seitig** — Default 200, Min 1, Max 2000.
  FastAPI lehnt Werte außerhalb mit HTTP 422 ab (kein stilles
  Clamping); `logger_admin.get_log_file()` validiert denselben Bereich
  defensiv ein zweites Mal, damit direkte Aufrufer ohne HTTP-Durchlauf
  nicht umgangen werden.

  **Route-Reihenfolge kritisch** — `/files/stats` vor `/files/{name}`
  (Starlette-Matching in Deklarations-Reihenfolge).

  Tests: 86 passed (4 Log-Suiten: `test_logger_admin.py`,
  `test_control_center_logger_api.py`, `test_logs_reader.py`,
  `test_logger_menu_path_traversal.py`) + 529 passed (`pytest tests/
  -k control_center`). Keine Telegram-Änderung.
  Details: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`.
- **CC-LOGGER-L3 (Runtime-Control Architecture Decision):** reine
  Analyse-Phase, kein Code. Erstes echtes Architecture Decision Record
  für das Control Center. Zentrale Befunde: (1) es existiert heute
  keine Runtime-Control-Infrastruktur für den Bot (keine IPC, kein
  Socket, kein File-Watcher, kein Reload-Trigger); (2) die persistente
  Logger-Config (`data/module_logger_config.json`) ist keine
  Runtime-Wahrheit, weil `_load_module_configs()` die Werte beim
  Bot-Start nicht über `_apply_module_config()` anwendet.

  Empfohlener Pfad (verbindlich für L4–L6): **Stufe 0** (Startup-Apply-
  Bugfix) → **Stufe 1** (E2: CC darf persistente Config schreiben,
  Semantik „wirksam beim nächsten Bot-Start") → **Stufe 2** (Runtime
  Snapshot, read-only Observability) → **Stufe 3** (kontrollierter
  Apply/Restart mit Preflight + Rate-Limit). **Stufe 4** (Unix-Socket
  Runtime Write) explizit deferred — nur bei belegtem Bedarf, sonst
  kein dauerhafter IPC-Kanal.

  Verworfen: File-Watcher als dauerhafte Runtime-Infrastruktur
  (Race-Risiko, kein Rückkanal), Localhost-HTTP-Control-Server
  (überdimensioniert), jeder unnötige neue IPC-Stack.

  DoD erfüllt (alle Punkte aus `logge.txt` §16 abgehakt). Keine
  Runtime-Implementierung, keine Telegram-Migration, keine UI-Änderung,
  keine L2-Endpunkt-Änderung. Details:
  `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`.

- **CC-LOGGER-L4 (Startup Apply + Persistent Logger Configuration):**
  erster Umsetzungsschritt nach der L3-Entscheidung. Zwei Bausteine:

  **Stufe 0 — Startup-Apply-Bugfix.** `ModuleLoggerManager._load_module_configs()`
  liest die persistente Konfiguration jetzt und wendet sie per
  `_apply_module_config()` auf die realen Logger an. Vor dem Fix galten
  nach jedem Bot-Neustart die Code-Defaults aus `logger.py` — die
  persistierte JSON war wirkungslos für den laufenden Prozess.

  **Stufe 1 — Persistent Config API.** Neue Application-Layer-Funktionen
  in `services/logger_admin.py` (`read_logger_config()`,
  `validate_logger_config_patch()`, `update_logger_config()` mit
  atomarem Write über `.tmp`+`replace()`, `LoggerConfigError` mit
  stabilem `code`). Zwei Endpunkte unter
  `/api/v1/admin/logger/config`:
  - `GET` — persistierte Konfiguration, ADMIN, read-only.
  - `PATCH` — Merge-by-module + merge-by-field, ADMIN + CSRF,
    strikte Validierung (unbekannte Module → 422, unbekannte Felder
    → 422, invalide Level → 422, Nicht-Bool → 422, fehlende Config
    → 409). Kein stilles Schema-Anlegen.

  **Ehrliche Semantik ohne Fake-Live:** die PATCH-Response bestätigt
  ausschließlich „gespeichert, wirksam beim nächsten Bot-Start". Der
  laufende Bot-Prozess wird nicht angefasst — zwei Tests pinnen das
  explizit (App-Layer-Level und HTTP-Level).

  **Verhaltensänderung (quantifiziert im Audit):** ab dem ersten
  Neustart nach dem Fix legen 40 Module je eine Log-Datei an, 18 davon
  schreiben tatsächlich auf DEBUG. Gewollt, im Audit-Dokument
  dokumentiert, kein verstecktes Verhalten.

  **Bewusst NICHT implementiert:** kein Runtime-Snapshot (Stufe 2),
  kein kontrollierter Restart (Stufe 3), kein IPC, keine Socket, keine
  UI, keine Telegram-Migration. Die bleiben L5/L6/L7.

  **Keine Schema-Änderung**, keine neue Abhängigkeit, keine Migration.
  Details:
  `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`.


- **CC-LOGGER-L5 (Runtime Snapshot + Controlled Apply/Restart):**
  Stufe 2 + Stufe 3 aus der L3-Architekturentscheidung.

  **Stufe 2 — Runtime Snapshot.** Bot schreibt beim erfolgreichen
  Startup `data/logger_runtime_snapshot.json` (atomic write via
  `Path.replace`). Der Snapshot wird aus dem tatsaechlichen
  Python-Logger-Zustand gelesen (`logging.getLogger(name).level`,
  `.handlers`, `.disabled`) — NICHT aus der persistenten Config.
  Neuer Endpoint `GET /api/v1/admin/logger/runtime-status` (ADMIN,
  read-only) mit drei Response-Zustaenden: `available` / `missing` /
  `corrupt`. Semantik explizit: `state_after_last_successful_bot_start`
  — kein Live-State, kein Fake-State bei fehlendem Snapshot.

  **Stufe 3 — Controlled Apply/Restart.** Neuer Endpoint
  `POST /api/v1/admin/logger/apply` (ADMIN + CSRF + Rate-Limit).
  Dreistufige Preflight-Semantik:

  - `blocked` — Repair-Lock aktiv → HTTP 409, keine Config-Mutation,
    kein Restart.
  - `unverified` — Lock frei, aber Downloads/Backups sind aus dem
    CC-Prozess strukturell nicht pruefbar → Restart mit strukturierter
    Warnung (`preflight.unverified=["downloads", "backups"]`).
  - `clear` — aktuell nicht erreichbar, da
    `UNVERIFIABLE_ACTIVITY_CATEGORIES` nicht leer ist. Als Status
    definiert, damit Clients sauber differenzieren koennen.

  Restart ueber den bestehenden `BotRestartTrigger.trigger_restart("bot")`
  — unveraendert, fest verdrahteter Service-Name, Response-before-restart
  via `call_later(2.0, ...)` wie `/system/restart`.

  **Rate-Limit:** `LoggerApplyRateLimiter` (in `app.state`, pro
  `create_app()`-Instanz isoliert), 60 s, mit Single-Flight-Semantik
  ueber `threading.Lock` (20 parallele Threads → genau 1 Acquire).

  **Kein IPC, kein Socket, keine neue State-Registry.** Der Preflight
  nutzt ausschliesslich die bestehende, cross-process sichtbare
  `library_repair.lock`.

  **Bugfix am bestehenden globalen HTTPException-Handler**
  (`control_center/app.py`): reicht jetzt `exc.headers` durch. Betrifft
  konkret den neuen `Retry-After`-Header bei HTTP 429, war aber ein
  bestehender Bug (Header wurden bei JEDER HTTPException verworfen).
  Eine Zeile, keine Verhaltensaenderung fuer andere Endpunkte.

  **Bekannte Einschraenkungen** (im Audit-Dokument als §13/§14):
  Race-Fenster zwischen Preflight und Restart (~2s), Stale-Lock nach
  Crash, Restart-Erfolg nicht verifizierbar (BotRestartTrigger
  schluckt Exceptions), laufende Downloads/Backups unpruefbar.
  Alle als Findings dokumentiert, nicht in L5 gefixt.

  Tests: 103 passed (L5-Suiten + Logger-Suiten) + 552 passed
  (`pytest -k control_center`). Details:
  `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md`.


- **CC-LOGGER-L6 (Logger-Verwaltungs-UI):** reine UI-Arbeit auf den
  bestehenden L4/L5-Endpunkten. Neue Seite `/logger` (Template +
  eigene JS-Datei, Stack-Pattern analog `statistics.html`) mit vier
  Panels:

  1. **Runtime-Status** — KPI-Kacheln (Root-Level, Modul-Anzahl, letzter
     Startup) + Tabelle aus `GET /runtime-status`, Zustaende
     available/missing/corrupt klar unterschieden. Semantik im UI
     explizit: "Zustand nach letztem Bot-Start".
  2. **Persistierte Konfiguration** — Tabelle aus `GET /config`,
     Semantik "wirksam beim naechsten Bot-Start".
  3. **Desired vs. Actual** — Diff aus den beiden Panels berechnet,
     kein neuer API-Call. Sonderfaelle (nur in Config / nur im Snapshot /
     kein Snapshot) ehrlich benannt. Kein Fake-Diff.
  4. **Apply / Controlled Restart** — einziger Call `POST /apply`,
     Antwort bestimmt Darstellung: unverified (gelb, unverifizierbare
     Kategorien explizit), clear (gruen), blocked (rot, kein Restart),
     config_missing (rot), 429 (orange mit Live-Countdown aus
     `Retry-After`), 403/401 wie bestehende Patterns.

  **Wiederverwendung:** `common.js`-Helper
  (`apiUrl/checkAuth/_loadInto/_escapeHtml/showOnly`),
  `common.css`-Klassen, Tabler-Komponenten. Keine Aenderung an
  `common.js`, `common.css` oder anderen Page-Dateien.
  Kein Config-PATCH-UI — der PATCH-Endpoint bleibt bewusst nicht
  exponiert.

  Tests: 6 neue UI-Tests in `tests/test_control_center_ui.py`.
  Regressionsergebnis: 218 + 560 passed. Details:
  `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md`.


- **CC-LOGGER-L7 (Telegram-Migration):** migriert
  `handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler`
  auf dieselbe Fachlogik wie Control Center, statt weiterhin eine
  eigene Parallelimplementierung zu pflegen (L2–L6 hatten Telegram in
  allen vier Phasen bewusst unverändert gelassen).

  **Verifizierter Preflight-Befund vor der Migration:** ein naiver
  Wechsel von `toggle_module()`/`set_module_level()` auf
  `services/logger_admin.py::update_logger_config()` hätte diese
  Funktion für die Mehrheit der real aktiven Module unbrauchbar
  gemacht — `update_logger_config()` lehnt unbekannte Module strikt ab
  (bewusste L4-Entscheidung), aber statische Analyse aller
  `get_module_logger()`/`setup_module_logging()`-Aufrufstellen im
  gesamten Produktionscode gegen `data/module_logger_config.json` ergab:
  75 real verwendete Modulnamen, 40 JSON-Einträge, **54 fehlend**. Nach
  vertiefter Prüfung (Prozesszugehörigkeit, tote Convenience-Wrapper in
  `logger.py`, Namens-Drift): 3 nur in `scripts/*.py` (eigener Prozess,
  für Telegram irrelevant), 10 tote `logger.py`-Wrapper ohne einen
  einzigen externen Aufrufer, **41 real aktiv und mehrheitlich
  P0-relevant** (Duplicate Detection: `DuplicateCache`,
  `DuplicateRunner`; Metadata: `AlbumProcessor`,
  `ArtistIdentityResolver`, `LyricsProcessor`, `MetadataCacheHandler`,
  `ReprocessingRunner`; Genre: `GenreRevalidation`,
  `GenreRevalidationRunner`; Library: `RepairService`,
  `LibraryHealthFindings`, `MaintenanceService`; Download/File:
  `DownloadHistoryStore`, `DownloadResultReporter`, `filename_fixer`).

  **Nutzerentscheidung:** neue Application-Layer-Funktion
  `services/logger_admin.py::ensure_module_config_entry()` — legt ein
  unbekanntes Modul mit denselben Defaults an, die
  `ModuleLoggerManager.get_module_config()` bereits für unbekannte
  Module liefert. **Bewusst nicht über `PATCH /api/v1/admin/logger/config`
  erreichbar** — kein Router-Endpunkt, Control Center bleibt bei der
  strikten L4-Semantik. Nur In-Process-Aufrufer (Telegram/Bot), die die
  reale Modul-Existenz über `_module_loggers` kennen, dürfen die Lücke
  schließen.

  **Migrierte Funktionen:**

  - `toggle_module()`/`set_module_level()`: `ensure_module_config_entry()`
    + `update_logger_config()` statt `ModuleLoggerManager`s eigenem,
    nicht-atomarem `_save_module_configs()`. Live-Apply
    (`_apply_module_config()`, Bot-lokal) unverändert.
  - `enable_all_modules()`/`disable_all_modules()`: neue private
    `_patch_all_known_modules()` — **ein** Multi-Modul-Patch statt N
    sequenzieller Einzel-Writes. Beide Funktionen bekamen zusätzlich
    `try/except`-Fehlerbehandlung (vorher praktisch nie eine Exception
    möglich, da die alten Save-Pfade Fehler intern schluckten).
  - `show_log_file_detail()`: liest jetzt über
    `services/logger_admin.py::get_log_file()` →
    `services/logs/reader.py::read_logs()` statt eigenem
    `open()`/`readlines()`/`Counter()`. Neuer Helper
    `_format_log_entry_preview()`.
  - `show_log_files_list()`/`show_log_files_stats()`: nutzen
    `list_log_files()`/`get_log_file_stats()`.

  **Bewusste, dokumentierte Verhaltensänderungen** (keine stille
  Drift):

  1. Level-Zählung korrekt statt naiv — vorher zählte
     `if level in line` eine Zeile unter dem ersten in fester
     Scan-Reihenfolge gefundenen Level-Wort, auch wenn es nur im
     Nachrichtentext vorkam. Jetzt strukturiertes Level-Feld aus
     `reader.py`.
  2. Traversal-Fehlermeldung vereinheitlicht: „Ungültiger Dateiname" →
     „Log-Datei nicht gefunden: …" (identisch zu Control Center). Die
     sicherheitskritische Eigenschaft (kein Datei-Inhalt wird je
     ausgeliefert) ist unverändert.
  3. Level-/Zeilenstatistik auf die neuesten 2000 Zeilen begrenzt
     (`MAX_LIMIT` aus L2) statt unbegrenztem `readlines()`.
  4. Sortierung der Log-Dateiliste: von „nach Dateigröße absteigend"
     auf „nach mtime, neueste zuerst" (**explizite Nutzerentscheidung**),
     konsistent mit Control Center.
  5. Rotierte Logs (`*.log.1`, …) jetzt sichtbar (`list_log_files()`
     nutzt `*.log*` statt vorher `*.log`).
  6. Erweiterte Datei-Statistik: zusätzlich größte/älteste Datei.

  **Zwei vorbestehende Defekte gefunden** (nicht in L7-Scope behoben,
  als eigene Findings dokumentiert): die Cleanup-Aktions-Buttons
  (`logger_cleanup_old`/`_large`/`_empty`/`_rotated`/`_all_confirm`/
  `_archive`) sind im Dispatcher nicht verdrahtet; die Route
  `logger_search_module` verweist auf eine nicht existierende Methode.

  **Kategorie D (dokumentiert, nicht migriert):** globales Log-Level
  (kein Persistenz-Schema), Modul-/Fehler-Statistiken (Prozessspeicher,
  unveränderter Cross-Process-Blocker), volle `loggerDict`-
  Introspektion, In-Process-Reload, Cleanup-Funktionen. Siehe
  `docs/FINDINGS_INDEX.md` für die Einzeleinträge.

  Tests: 22 neue Tests über 4 Testdateien (2 neue Dateien:
  `test_enhanced_logger_menu_handler_file_detail.py`,
  `test_enhanced_logger_menu_handler_files_list.py`; 2 erweiterte:
  `test_logger_config_service.py`,
  `test_enhanced_logger_menu_handler_module_toggle.py`), 3
  Assertions in `test_logger_menu_path_traversal.py` an die neue
  Fehlermeldung angepasst, Fehlerinjektion in
  `test_enhanced_logger_menu_handler_error_handler.py` an den
  geänderten internen Aufrufpfad angepasst. Regressionsergebnis
  (thematisch, während der Implementierung): 245 + 336 passed, 0
  Regressionen. Volle Suite (Nutzer, 2026-09-26): 5633 passed / 1
  skipped / 11 subtests passed / 0 failed. Details:
  `docs/audits/CC-LOGGER-L7_TELEGRAM_MIGRATION_2026-09-26.md`.

- **CC-LOGGER-L6.1 (File Handler Control):** UI-only-Nachtrag zu L6.
  Die Spalte „File" in Panel 2 („Persistierte Konfiguration") der
  `/logger`-Seite ist ein Schalter. `logger.js` sendet
  `PATCH /api/v1/admin/logger/config` mit
  `{"modules": {"<Modul>": {"file_handler": <bool>}}}` — nur dieses
  Feld, expliziter Zielwert, `enabled` bewusst nicht mitgesetzt
  (Abweichung zu Telegrams `toggle_module()`). Nur bereits in
  `module_logger_config.json` stehende Module sind schaltbar (L4);
  `ensure_module_config_entry()` bleibt In-Process-exklusiv (L7).
  Wirksam erst nach „Konfiguration anwenden" (L5-Restart), kein
  Live-Control (L3). Kein neuer Endpoint, keine neue Page, keine
  Backend-Änderung. Tests: +9 API-Vertragstests
  (`test_control_center_logger_api.py`), +2 UI-Marker-Tests
  (`test_control_center_ui.py`). Regressionsergebnis (thematisch):
  680 passed. Volle Suite: steht beim Nutzer aus. Vorbestehender
  L6-Defekt nachgezogen (P3-Fix, Nutzerfreigabe): `renderDiff()`
  erkannte `EnhancedRotatingFileHandler` nicht als Log-Datei;
  `_loggerHandlerKind()` klassifiziert jetzt jedes `*FileHandler` als
  Datei (+5 Tests, `logger.js` real per node ausgeführt; thematisch 685
  passed). Neuer OPEN-Befund (P3): `setup_module_logging()` (u. a. in
  `EnhancedMetadataProcessor.__init__`) übersteuert das persistierte
  `file_handler` — für solche Module ist der L6.1-Schalter wirkungslos.
  Details:
  `docs/audits/CC-LOGGER-L6.1_FILE_HANDLER_CONTROL_2026-09-27.md`.

- **CC-LOGGER-L6.2 (Level Control):** UI-only-Nachtrag zu L6/L6.1.
  Die Spalte „Level" in Panel 2 der `/logger`-Seite ist eine
  Auswahl mit exakt `services/logger_admin.py::ALLOWED_LOG_LEVELS`
  (DEBUG/INFO/WARNING/ERROR/CRITICAL, Reihenfolge wie Telegrams
  `log_levels`; Gleichlauf per Test gepinnt, da `GET /config` die
  Liste nicht liefert). Änderung sendet über das bestehende
  `PATCH /api/v1/admin/logger/config` ausschließlich `{level}`.
  Nur persistierte Module, wirksam erst nach „Konfiguration anwenden"
  (L5-Restart), kein Live-Control (L3). Der PATCH-Ablauf aus L6.1 ist
  jetzt gemeinsam (`_loggerPatchModuleConfig()`), L6.1-Verhalten
  unverändert (per node-Regressionstest belegt). Tests: +17 API,
  +2 UI-Marker, +8 node-Ausführungstests
  (`tests/test_logger_js_config_controls.py`); thematisch 712 passed.
  Einschränkung: für Module mit `setup_module_logging()` im Konstruktor
  wirkungslos (bestehender OPEN-Befund ergänzt). Details:
  `docs/audits/CC-LOGGER-L6.2_LEVEL_CONTROL_2026-09-27.md`.

- **Findings-Closure + Dokumentations-Konsistenz-Audit (2026-09-27):**
  alle 32 zu diesem Zeitpunkt offenen Zeilen des Findings-Index einzeln
  gegen den Code geprüft (Details und Einzelbelege ausschließlich in
  `docs/FINDINGS_INDEX.md`). Code-Fixes: atomare Persistenz für
  `LyricsCache.store()`/`PlayHistoryRepository.save()` (INV-02);
  einheitliche Repair-Ergebnissemantik SUCCESS/UNRESOLVED/SKIPPED/FAILED
  über Core (`repair_service._overall_status()`/`_changed_files()`,
  Exit-Code wird nicht mehr durch Journal-Einträge verdeckt, neuer
  Run-Status `UNRESOLVED`), Telegram (`_result_headline()` für
  SAFE_AUTOMATIC und L2/L3), Control-Center-Job-Ergebnis und UI
  („geändert" nur noch aus `changed_files`); Logger-Cleanup über neue
  `services/logger_admin.py::cleanup_rotated_log_files()` (nur rotierte
  Backups, Vorschau → Bestätigung), tote Route `logger_search_module`
  entfernt. Doku: ADR-0001/0002 → IMPLEMENTED, veralteter
  `resolve_duplicates.py`-Kommentar korrigiert, `setup_module_logging()`-
  Zeile als durch L7.1 geschlossen markiert, Status-Vokabular
  vereinheitlicht. Error-Administration (CC-AC-10D) als separate
  Architekturphase analysiert: `docs/audits/ERROR_ADMINISTRATION_ARCHITECTURE_ANALYSIS_2026-09-27.md`
  (DECISION PENDING). Neue Tests: 12 + 56 + 37 (alle mit
  Vor-Fix-Diskriminierung). Volle Suite: steht beim Nutzer aus.

---

## 4. Technical Debt — Snapshot

*(Platzhalter — wird beim v11-Freeze befüllt. Laufender Stand aller
offenen/zurückgestellten Punkte: `docs/FINDINGS_INDEX.md`.)*

---

## 5. Security-Baseline

*(Platzhalter — wird beim v11-Freeze befüllt.)*

---

## 6. Architecture Freeze

*(Platzhalter — Freeze-Gate-Audit noch nicht durchgeführt, kein
GO/NO-GO-Verdikt für v11.)*
