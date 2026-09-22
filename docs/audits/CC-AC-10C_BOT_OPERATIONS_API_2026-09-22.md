# CC-AC-10C — Bot & Operations API

**Datum:** 2026-09-22
**Auftrag:** freigegebene Master-Prompt `CC-AC-10.md`, Slice **CC-AC-10C**
("Bot & Operations: Backup + Restart + Maintenance + Navidrome Scan").
Baut auf `docs/audits/CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md`
(Zeilen #7–#12) auf. Löst den dort offenen Bot-Neustart-Entscheidungspunkt
auf (Nutzer-Entscheidung 2026-09-22, siehe `docs/FINDINGS_INDEX.md`).

## Implementiert

Vollständige Write/Execute-Parität für vier Bereiche: Backup erstellen/
auflisten/löschen (Bot- und Library-Verzeichnis), Bot-Neustart, Wartungsmodus
anzeigen/umschalten, Navidrome-Scan auslösen.

## Application Layer

Unterschiedliche Strategie je Bereich, je nachdem ob bereits Telegram-freie
Logik existierte (CC-AC-10.md §24: „Suche zuerst nach vorhandener Logik"):

- **Backup:** neues `services/backup_admin.py` — `handlers/admin/
  backup_handler.py::BackupHandler` hält Telegram-Objekte und kann daher
  laut `tests/test_services_layer_boundary.py` nicht aus `services/`
  importiert werden. Eigenständige, aber verhaltensidentische
  Implementierung (Archiv-Erstellung, SEC-006-Path-Traversal-Schutz in
  `resolve_backup_path()`, Rotation). `BackupHandler` bleibt unverändert
  (Telegram-Migration ist CC-AC-10G, identische Begründung wie bei
  `services/user_admin.py` in CC-AC-10B).
- **Wartungsmodus:** **kein neuer Application-Layer** —
  `services/bot_maintenance.py::MaintenanceModeStore` war bereits
  vollständig Telegram-frei und wird vom neuen Router direkt
  instanziiert.
- **Bot-Neustart:** **kein neuer Application-Layer** —
  `utils/bot_restart_trigger.py::BotRestartTrigger.trigger_restart()`
  war bereits Telegram-frei, identisches `call_later()`-Timing wie
  `handlers/admin/bot_restart_handler.py::execute_restart()` im Router
  repliziert.
- **Navidrome-Scan:** **kein neuer Application-Layer** —
  `utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan()` war
  bereits Telegram-frei und async, direkt im Router aufgerufen.

## API

Neuer Router `control_center/routers/admin_operations.py` (Prefix
`/api/v1/admin`, ADMIN, schreibende Endpunkte CSRF-geschützt):

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/backups?backup_type=bot\|library` | Backups auflisten |
| POST | `/backups` | Backup erstellen — **als Job** (Dauer ~9,5s+, `services/jobs/job_registry.py`, identisches Muster wie `routers/jobs.py`) |
| DELETE | `/backups/{filename}` | Backup löschen (SEC-006-geschützt) |
| GET | `/maintenance` | Wartungsmodus-Status |
| POST | `/maintenance` | Wartungsmodus umschalten |
| POST | `/system/restart` | Bot-Neustart (Nutzer-Entscheidung, s. o.) |

Zusätzlich `POST /api/v1/navidrome/scan` in `control_center/routers/
navidrome.py` (bestehender Router, bisher nur `GET /status`) — eigene
ADMIN-Auth-Dependency auf Endpunkt-Ebene (Router-Default ist USER, da
`GET /status` bewusst niedrigschwelliger bleibt).

Fehler-Mapping: `InvalidBackupTypeError`/ungültiger Backup-Dateiname
(SEC-006)→422, `BackupNotFoundError`→404, Navidrome-Scan-Konfigurationsfehler
→422, `ScanTimeoutError`→504.

## Control Center UI

Noch offen — CC-AC-10F ("Control Center UI Parity"), nicht dieses Slices.

## Telegram

Unverändert (0 Zeilen an `BackupHandler`, `BotRestartHandler`,
`MaintenanceModeStore`, `NavidromeScanTrigger` geändert).

## CLI

Nicht Teil dieses Slices, kein CLI für diese vier Bereiche vorhanden
(CC-AC-10A-Befund, unverändert).

## Tests

- `tests/test_backup_admin_service.py` (neu, 16 Tests): reine Unit-Tests
  von `services/backup_admin.py`, inkl. SEC-006-Path-Traversal-
  Charakterisierung (relative und absolute Escape-Versuche) und
  Rotation.
- `tests/test_control_center_admin_operations_api.py` (neu, 14 Tests):
  HTTP-Ebene für Backup (inkl. echtem Job-Polling bis `SUCCEEDED`),
  Wartungsmodus, Neustart — inkl. CSRF-Ablehnung pro schreibendem
  Endpunkt. Der reale `sudo systemctl restart`-Aufruf ist über eine
  autouse-Fixture (`BotRestartTrigger.trigger_restart` gemockt)
  unbedingt verhindert.
- `tests/test_control_center_navidrome_api.py` (erweitert, +4 Tests):
  `POST /scan` — Erfolg, Konfigurationsfehler, Timeout, CSRF-Ablehnung.
  Externer Subprozess-Aufruf gemockt (CLAUDE.md §8).
- Gezielt: 96 passed (neue Testdateien + alle bestehenden Backup-/
  Restart-/Maintenance-Telegram-Tests — 0 Regressionen).
- Thematisch (`-k "control_center or backup or restart or maintenance
  or navidrome_scan or navidrome_api"`): 1076 passed, 19 vorbestehende,
  unabhängige Fehlschläge (siehe unten).
- `tests/test_services_layer_boundary.py`: 111 passed.
- Vollständige Suite: nicht selbst ausgeführt (CLAUDE.md §8.A) — dem
  Nutzer empfohlen.
- **Nicht durch diesen Slice verursacht, vorbestehend (identisch zu
  CC-AC-10B):** dieselben 19 Fehlschläge in
  `tests/test_control_center_ui.py`/`test_control_center_subpath_ui.py`
  (Sidebar-/Library-Template-Inhalte) — unverändert seit CC-AC-10B,
  betreffen keine der in diesem Slice geänderten Dateien.

## Security

- SEC-006-Path-Traversal-Schutz für Backup-Löschung 1:1 aus
  `BackupHandler._resolve_backup_path()` übernommen (`resolve_backup_path()`
  in `services/backup_admin.py`), per Unit- UND HTTP-Test verifiziert.
- Bot-Neustart: identische Admin-Gate + CSRF, keine zusätzliche
  Preview/Confirm-Stufe (bewusste Nutzer-Entscheidung, s. o.) — Web-UI
  kann bei Bedarf einen eigenen Client-seitigen Bestätigungsdialog
  zeigen, identisch zum bestehenden Telegram-Muster.
- Entdeckter und behobener Bug während der Implementierung: der erste
  Entwurf von `POST /system/restart` war eine synchrone Routenfunktion
  und rief `asyncio.get_event_loop()` auf — FastAPI führt synchrone
  Routen in einem Threadpool-Worker-Thread aus, der keine aktive
  Event-Loop hat (`RuntimeError: There is no current event loop in
  thread 'AnyIO worker thread'`), was den Neustart-Endpunkt bei jedem
  Aufruf mit 500 hätte scheitern lassen. Gefunden durch den eigenen
  HTTP-Test dieses Slices (nicht in Produktion aufgetreten). Fix: Route
  auf `async def` + `asyncio.get_running_loop()` umgestellt.

## Entfernte Duplikation

Keine — `BackupHandler` bleibt unverändert (siehe „Application Layer"),
daher entsteht wie bei CC-AC-10B eine kleine, dokumentierte Duplikation
der Backup-Archivlogik. Auflösung ist Gegenstand von CC-AC-10G.

## Noch offen

- CC-AC-10D (Diagnostics & Monitoring: System-Status, Logger,
  Error-Administration) — nächster Slice laut CC-AC-10A-Priorisierung.
- CC-AC-10E (Library Administration: nur noch Artist-Metadata-
  Reprocessing fehlt, Rest bereits vollständig).
- CC-AC-10F (Control Center UI Parity).
- CC-AC-10G (Telegram Migration) — `BackupHandler`/`UserManagementHandler`
  könnten künftig auf die jeweiligen Application-Layer-Module umgestellt
  werden.

## Read/Write-Parität

Backup + Bot-Neustart + Wartungsmodus + Navidrome-Scan: **6/6** Funktionen
(Backup erstellen/auflisten/löschen, Restart, Wartungsmodus, Scan-Trigger)
jetzt vollständig über die API erreichbar. Damit steigt der
CC-AC-10A-Gesamtstand von 17/26 auf **23/26** Admin-Funktionen mit
Web-Endpunkt. Verbleibende Lücke: nur noch Diagnostics/Logger/Error-
Administration (#13, #15–19) und Artist-Metadata-Reprocessing (#25).

## Regression

Gezielte + thematische Tests grün (s. o.), 0 durch diesen Slice
verursachte Fehlschläge (19 vorbestehende, unveränderte UI-Template-
Fehlschläge identisch zu CC-AC-10B). Volle Suite dem Nutzer zur
Ausführung empfohlen (CLAUDE.md §8.A).

---

## ADMIN PARITY MATRIX (Delta zu CC-AC-10A/B)

| Funktion | Telegram | CC API | CC UI | CLI | App Command/Query | Tests | Authorization | Status |
|---|---|---|---|---|---|---|---|---|
| Backup erstellen | ✅ | ✅ (POST, Job) | ❌ | ❌ | ✅ `backup_admin.create_backup` | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| Backup auflisten | ✅ | ✅ (GET) | ❌ | ❌ | ✅ `backup_admin.list_backups` | ✅ | ADMIN | 🟢 API fertig, UI offen (10F) |
| Backup löschen | ✅ | ✅ (DELETE) | ❌ | ❌ | ✅ `backup_admin.delete_backup` (SEC-006) | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| Bot-Neustart | ✅ | ✅ (POST) | ❌ | ❌ | — (direkter `BotRestartTrigger`-Aufruf) | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| Wartungsmodus | ✅ | ✅ (GET+POST) | ❌ | ❌ | — (direkter `MaintenanceModeStore`-Aufruf) | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |
| Navidrome-Scan-Trigger | ✅ | ✅ (POST) | ❌ | ❌ | — (direkter `NavidromeScanTrigger`-Aufruf) | ✅ | ADMIN + CSRF | 🟢 API fertig, UI offen (10F) |

Alle übrigen Zeilen der CC-AC-10A/B-ADMIN-PARITY-MATRIX unverändert.
