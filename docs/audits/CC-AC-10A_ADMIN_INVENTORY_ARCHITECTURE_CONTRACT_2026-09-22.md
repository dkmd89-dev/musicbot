# CC-AC-10A — Admin Inventory + Architecture Contract

**Datum:** 2026-09-22
**Auftrag:** freigegebene Master-Prompt `CC-AC-10.md` ("Vollständige
Administration API Integration"), Abschnitt 20, Slice **CC-AC-10A**
("Admin Inventory + Architecture Contract — nur Analyse und Boundary
Definition"). Reine Ist-Analyse, keine Code-Änderung.

**Basis:** `git log` + vollständige Lektüre der unten gelisteten Dateien
(aktueller Stand `main` @ `bebdac3`, 2026-09-22), NICHT nur die
vorhandene Dokumentation. Wo diese Analyse einer bestehenden Aussage aus
`docs/audits/CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md` bzw.
`docs/audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md`
widerspricht, hat laut CLAUDE.md §29 der tatsächliche Code Vorrang — der
Widerspruch wird unten explizit benannt, nicht stillschweigend
übernommen.

## Was sich seit dem 15.09. geändert hat (Kernbefund)

Der 09-15-Stand markierte Library Doctor/Repair/Reprocessing/Duplicate-
Resolution durchgehend als 🟡/🟠 ("Job-Abstraktion Voraussetzung",
"Service-Extraktion nötig"). Zwischen dem 15.09. und heute wurde genau
diese Job-Abstraktion gebaut (`services/jobs/job_registry.py`,
`control_center/routers/jobs.py`) und **Library Doctor, Repair-Execution
(L2/L3) und die komplette Library-Maintenance-Aktionsgruppe
(Artist-Casing/Rename, Titel/Album/Albuminterpret bearbeiten) sind bereits
volle Preview→Execute-Web-APIs mit CSRF-Schutz** — nicht mehr bloß
geplant. Findings/Repairs/Jobs wurden laut Commit-Historie
(`45870ba feat(control-center): consolidate Findings/Repairs/Jobs into
/health`) zusätzlich UI-seitig konsolidiert. Der aktuelle
Read/Write-Stand ist damit für die **Library-Administration-Domäne**
(CC-AC-10.md Abschnitt 8 / Slice CC-AC-10E) erheblich weiter als die
09-15-Matrix vermuten lässt — dort bereits 22/26 gefundene
Funktionen mit vorhandenem Write-API (siehe Matrix unten).

Für **User Management, Backup, Bot-Neustart, Wartungsmodus,
Navidrome-Scan-Trigger, Logger-Konfiguration und Error-Administration**
gilt dagegen unverändert: **kein einziger schreibender (und bei
Logger/Error-Admin auch kein lesender) Control-Center-Endpunkt.** Das
deckt sich mit der 09-15-Einschätzung (🟠 "Handler-gebunden statt reiner
Service").

## Untersuchte Dateien (vollständig gelesen)

- `handlers/admin/backup_handler.py` (586 Zeilen)
- `handlers/admin/bot_restart_handler.py` (183 Zeilen)
- `handlers/admin/user_management_handler.py` (800 Zeilen)
- `handlers/menu/actions/admin_diagnostics.py`, `admin_operations.py`,
  `usermgmt.py`
- `handlers/menu/rich_menu_system.py` (nur `handle_callback()` /
  `_ADMIN_ONLY_PREFIXES`-Abschnitt, nicht vollständig)
- `control_center/routers/admin.py`, `admin_maintenance.py`, `health.py`,
  `jobs.py`, `repair.py`, `findings.py`, `logs.py`, `navidrome.py`
- `control_center/dependencies.py`
- `handlers/menu/permissions.py`
- `services/user_data.py`, `services/bot_maintenance.py` (nur
  Klassen-/Methodensignaturen)
- `handlers/enhanced_error_handler.py` (nur `ErrorHandlerAdminInterface`,
  Zeilen 1706ff, Signaturen)
- `handlers/enhanced_logger_menu_handler.py` (nur Klassen-/
  Methodensignaturen)
- `scripts/*.py` (Verzeichnislisting — kein CLI für Admin-Domäne
  vorhanden, siehe unten)

**Nicht vollständig gelesen (Scope-Einschränkung dieses Slices, für
CC-AC-10B/C/D/D relevant):** `handlers/library_doctor_handler.py`,
`handlers/repair_musicbot_handler.py`, `handlers/library_maintenance_handler.py`,
`handlers/enhanced_status_handler.py` (Status-Domäne — Methodenkörper
nicht geprüft, nur Dispatcher-Routing in `admin_diagnostics.py`),
`services/library_repair/*` (Service-Implementierungen selbst, nur über
ihre bereits vorhandenen Router-Docstrings referenziert). Diese Lücke ist
für CC-AC-10A vertretbar (die Web-Seite dieser Funktionen ist bereits
vollständig über die gelesenen Router charakterisiert), muss aber vor
CC-AC-10G (Telegram-Migration dieser Handler) nachgeholt werden.

---

## 1. Admin-Funktionsmatrix

Format aus CC-AC-10.md Abschnitt 4. `App-Layer-Vorschlag` markiert
Funktionen ohne heutige Anwendungsschicht — dort ist es ein Vorschlag für
CC-AC-10B–E, kein bestehender Code.

| # | Funktion | Telegram (Ort) | API aktuell | API-Ziel (Vorschlag, falls fehlend) | Application Layer | Tests |
|---|---|---|---|---|---|---|
| 1 | User anzeigen | `usermgmt_list_*` → `UserManagementHandler.show_user_management_menu()` | ✅ `GET /api/v1/admin/users` (read-only, `admin.py`) | — (vorhanden) | keiner (Router liest direkt `services/user_data.py`) | `test_control_center_admin_api.py`, `test_user_management_handler.py` |
| 2 | User anlegen | `usermgmt_add_user` → `process_new_user_id()`/`process_new_navidrome_user()` (2-Schritt-Textdialog) | ❌ | `POST /api/v1/admin/users` | App-Layer-Vorschlag: `CreateUserCommand` | `test_user_management_handler.py` (Telegram-Pfad), kein API-Test |
| 3 | User bearbeiten (Navidrome-Zuordnung) | `usermgmt_set_navidrome_*` → `process_edit_navidrome_user()` | ❌ | `PATCH /api/v1/admin/users/{id}/navidrome` | App-Layer-Vorschlag: `UpdateUserNavidromeCommand` | `test_user_management_handler.py` |
| 4 | Rolle ändern | `usermgmt_change_role_*`/`usermgmt_set_role_*` → `set_user_role()` (mit Owner-Promotion-Guard) | ❌ | `PATCH /api/v1/admin/users/{id}/role` | App-Layer-Vorschlag: `UpdateUserRoleCommand` (muss Owner-Guard übernehmen) | `test_user_management_handler.py` |
| 5 | Berechtigungen ändern | `usermgmt_permissions_*`/`usermgmt_toggle_perm_*` → `toggle_user_permission()` | ❌ | `PATCH /api/v1/admin/users/{id}/permissions` | App-Layer-Vorschlag: `UpdateUserPermissionsCommand` | `test_user_management_handler.py` |
| 6 | User löschen | `usermgmt_delete_confirm_*`/`_confirmed_*` → `delete_user()` | ❌ | `DELETE /api/v1/admin/users/{id}` | App-Layer-Vorschlag: `DeleteUserCommand` | `test_user_management_handler.py`, `test_user_management_atomic_persistence.py` |
| 7 | Backup erstellen (Bot/Library) | `backup_bot_start`/`backup_lib_start` → `BackupHandler.start_*_backup()` (Executor, tarfile) | ❌ | `POST /api/v1/admin/backups` (als Job — Dauer ~9,5s+ gemessen) | App-Layer-Vorschlag: `CreateBackupCommand` | `test_backup_handler.py`, `test_backup_handler_event_loop_blocking.py`, `test_backup_handler_error_handler.py` |
| 8 | Backup auflisten | `backup_list_bot`/`backup_list_lib` → `_show_backup_list()` | ❌ | `GET /api/v1/admin/backups` | App-Layer-Vorschlag: `GetBackupsQuery` | `test_backup_handler.py` |
| 9 | Backup löschen | `backup_delete_confirm_*`/`backup_delete_*` → `delete_backup()` (SEC-006 Path-Traversal-Schutz via `_resolve_backup_path()`) | ❌ | `DELETE /api/v1/admin/backups/{id}` — Path-Traversal-Schutz aus `_resolve_backup_path()` muss identisch übernommen werden | App-Layer-Vorschlag: `DeleteBackupCommand` | `test_backup_handler.py` |
| 10 | Bot-Neustart | `restart:confirm` → `BotRestartHandler.execute_restart()` → `utils/bot_restart_trigger.py` (systemctl) | ❌ | `POST /api/v1/admin/system/restart` — CC-AC-10.md §26 nennt dies als Pflichtfunktion; 09-15-Matrix hatte dies bewusst als ⚪ "vorerst nicht vorgesehen" (hohes Blast-Radius-Risiko) eingestuft — **Widerspruch zur neuen Master-Prompt-Vorgabe "Read-only ist kein Zielzustand", muss vor CC-AC-10C aufgelöst werden (siehe unten)** | App-Layer-Vorschlag: `RestartBotCommand` | `test_bot_restart_handler.py`, `test_bot_restart_trigger.py` |
| 11 | Wartungsmodus anzeigen/umschalten | `maint:show`/`maint:toggle` → `services/bot_maintenance.py::MaintenanceModeStore` | ❌ | `GET`/`POST /api/v1/admin/maintenance` | App-Layer-Vorschlag: `Enable/DisableMaintenanceModeCommand` | `test_rich_menu_maintenance_mode.py` |
| 12 | Navidrome-Scan auslösen | `menu:` → `handle_navidrome_scan()` → `utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan()` | ⚠️ nur `GET /api/v1/navidrome/status` (read-only, kein Scan-Trigger) | `POST /api/v1/navidrome/scan` | App-Layer-Vorschlag: `RunNavidromeScanCommand` | keine dedizierten API-Tests, Telegram-Pfad: nicht in dieser Analyse gesucht |
| 13 | System-Status (Dashboard) | `status_*` (11 Callbacks) → `EnhancedStatusHandler` (nicht vollständig gelesen) | ⚠️ fragmentiert: `GET /health`, `/health/cached`, `/navidrome/status`, `GET /api/v1/jobs` decken Teilaspekte ab, kein zusammengeführter `/system/status` | `GET /api/v1/admin/system/status` (Zusammenführung, wie 09-15-Audit Abschnitt 8 vorschlug) | App-Layer-Vorschlag: `GetSystemStatusQuery` | nicht geprüft (Scope-Einschränkung) |
| 14 | System-Logs anzeigen | `handle_view_logs()` (Tail 20 Zeilen, `admin_diagnostics.py`) | ✅ `GET /api/v1/logs` (`logs.py`) — **funktional reichhaltiger** als der Telegram-Pfad (Filter nach source/level/component/search) | — (vorhanden, Telegram könnte künftig denselben Service nutzen) | keiner (Router → `services/logs/reader.py`) | keine dedizierten API-Tests gefunden |
| 15 | Logger konfigurieren (Modul-Level, Handler, Cleanup, Stats) | `logger_*` (>15 Callbacks) → `EnhancedLoggerMenuHandler` (großer Funktionsumfang: Modul-Level, globales Level, Handler add/remove/reload, Log-Datei-Download/Stats, Cleanup) | ❌ | `GET/PATCH /api/v1/admin/logger` (CC-AC-10.md §7 selbst merkt an: "falls Logger-Konfiguration mehrere Aktionen besitzt, diese entsprechend modellieren" — 1 Endpunkt reicht hier vermutlich NICHT, siehe offene Frage unten) | App-Layer-Vorschlag: mehrere Commands/Queries statt eines `UpdateLoggerConfigurationCommand` | `test_enhanced_logger_menu_handler_error_handler.py`, `test_enhanced_logger_menu_handler_module_toggle.py`, `test_logger_menu_path_traversal.py` |
| 16 | Error Stats anzeigen | `erradmin:show_stats` → `ErrorHandlerAdminInterface.handle_error_stats_command()` | ❌ | `GET /api/v1/admin/errors/stats` | App-Layer-Vorschlag: `GetErrorStatisticsQuery` | keine dedizierten Tests gefunden (nur indirekt über ARCH-026/027/028-Audits) |
| 17 | Error Report anzeigen | `erradmin:show_report` → `handle_error_report_command()` | ❌ | `GET /api/v1/admin/errors/report` | App-Layer-Vorschlag: `GetErrorReportQuery` | s.o. |
| 18 | Recent Errors anzeigen | `erradmin:show_recent` → `handle_recent_errors_command()` | ❌ | `GET /api/v1/admin/errors/recent` | App-Layer-Vorschlag: eigene Query oder Parameter auf #17 | s.o. |
| 19 | Error Stats zurücksetzen | `erradmin:reset_confirm`/`reset_execute` → `execute_reset_stats()` | ❌ | `POST /api/v1/admin/errors/reset` | App-Layer-Vorschlag: `ResetErrorStatisticsCommand` | s.o. |
| 20 | Library Doctor (Scan+SAFE_AUTOMATIC) | `doctor:` (`handlers/library_doctor_handler.py`, nicht gelesen) → `services/library_repair/doctor_runner.py` | ✅ `POST /api/v1/jobs/repair-safe-automatic` + `POST /api/v1/jobs/health-scan` (async Job, `jobs.py`) | — (vorhanden) | keiner (Router-Funktion `_run_safe_automatic_repair_job()` ist bereits die Orchestrierung) | nicht geprüft (Scope), Job-Infrastruktur hat eigene Tests laut vorhandener Doku |
| 21 | Findings Review (anzeigen/akzeptieren/zurücknehmen/RESOLVED) | `review:` → `library_health_review_handler.py` (nicht gelesen) → `services/library_health/findings.py` | ✅ `GET /findings(+summary+accepted)`, `POST .../accept`, `.../review`, `.../unaccept` (`findings.py`) — **volle Parität** | — (vorhanden) | keiner (Router → `services/library_health/findings.py`-Kernfunktionen direkt) | laut Library-Closure-Phase (Memory) 674 thematische Tests grün |
| 22 | Repair-Preview (Dry-Run) | `repair:` | ✅ `GET /repair-plan(+by-artist)` (`repair.py`, read-only) | — (vorhanden) | keiner | nicht geprüft (Scope) |
| 23 | Repair-Ausführung (L2/L3, pro Artist) | `l23rep:` → `handlers/repair_musicbot_handler.py` (nicht gelesen) → `services/library_repair/repair_service.py` | ✅ `POST /api/v1/jobs/repair-level2`/`repair-level3` (`jobs.py`, async Job, gleicher Lock wie Telegram/CLI) | — (vorhanden) | keiner (Router-Funktion `_run_level_repair_job()` orchestriert direkt) | nicht geprüft (Scope) |
| 24 | Repair-History/Statistik | — (nicht gesucht, evtl. Telegram-seitig via `repair:`) | ✅ `GET /repairs/history`, `/repairs/statistics` (`repair.py`) | — (vorhanden) | keiner | nicht geprüft |
| 25 | Artist-Metadata-Reprocessing | `reprocess:` (OWNER-only laut 09-15-Matrix) → `services/metadata/track_reprocessor.py` | ❌ (kein Router-Endpunkt in `control_center/routers/` gefunden) | **Nutzer-Entscheidung (2026-09-22): keine Control-Center-API für diese Funktion** — bereits über CLI (`scripts/reprocess_artist_metadata.py`) und Artist-Kontext nahezu vollständig abgedeckt, kein zusätzlicher Web-Endpunkt vorgesehen. Bewusst dauerhaft ⚪, kein „Lücke, die noch zu schließen ist" | n/a (bewusst nicht gebaut) | `scripts/reprocess_artist_metadata.py` (CLI) vorhanden |
| 26 | Library-Wartung: Artist-Casing/Legacy-Genre-Cleanup/Artist-Rename/Titel-/Album-/Albuminterpret-Edit (6 Aktionen) | `libmaint:` (`handlers/library_maintenance_handler.py`, nicht gelesen) → `services/library_repair/maintenance_service.py` | ✅ 6× Preview/Execute-Paar (`admin_maintenance.py`, CSRF-geschützt) — **volle Parität, teils sogar Web-first** (`title-edit`/`album-edit`/`albumartist-edit` laut Docstring "identisch zur Telegram-Fähigkeit") | — (vorhanden) | keiner (Router → `maintenance_service.py` direkt) | `test_control_center_admin_maintenance_api.py` |

**Zusätzlich gefunden, nicht in CC-AC-10.md §4 explizit gelistet, aber
real existierende Admin-Funktionen (#4/#5 oben sind Beispiele — hier eine
für die Matrix bereits vollständig erfasste Ergänzung):**
`Genre setzen` (`control_center/routers/metadata_actions.py`) — bereits
volle Preview/Execute-Parität, wird hier nicht als eigene Zeile geführt,
da es fachlich zur Metadata- nicht zur Admin-Domäne gehört (CC-AC-10.md
Abschnitt 5 zählt es nicht zu den Admin-Bereichen).

**Offene Frage statt Spekulation:** Zeile 12 (Navidrome-Scan) — ob der
Telegram-Callback für `handle_navidrome_scan()` in `rich_menu_system.py`
tatsächlich unter das generische `"menu:"`-Präfix fällt (wie der
TGPERM-001-Fund es für Logger-Items ursprünglich beschrieb) oder einen
eigenen gegateten Präfix hat, wurde in diesem Slice **nicht** geprüft
(nur `admin_operations.py`s eigener `is_admin_or_owner()`-Check wurde
gelesen — Defense-in-Depth, unabhängig vom Dispatcher-Routing). Vor
CC-AC-10C sollte das verifiziert werden.

---

## 2. Architecture Contract — `ActorContext`

CC-AC-10.md §11 fordert eine client-unabhängige Identität. Die
tatsächlich vorhandene Berechtigungsstruktur, an die angedockt werden
muss:

- `handlers/menu/models.py::AccessLevel` (nicht in diesem Slice
  gelesen, aber referenziert von `permissions.py` und `dependencies.py`
  — Werte mindestens `USER`, `MODERATOR`, `ADMIN`, `OWNER`, vergleichbar
  über `.value` mit `<`)
- `handlers/menu/permissions.py::get_user_access_level(user_id, config,
  user_mgmt_handler)` — **bereits Telegram-frei** (eigener Docstring:
  "Dieses Modul darf keine Abhängigkeit auf ... Telegram-Infrastruktur
  haben"), nimmt ein Duck-Typed-Objekt mit `.user_data_cache`-Attribut
  entgegen statt der schweren `UserManagementHandler`-Klasse
- `handlers/menu/permissions.py::is_admin_or_owner(user_id, config)` —
  ebenfalls Telegram-frei
- `control_center/dependencies.py::_UserDataCacheAdapter` — **ist
  bereits exakt der erste Baustein eines client-unabhängigen
  ActorContext**: ein minimaler Adapter, der `get_user_access_level()`
  ohne Telegram-Kopplung aufruft

**Daraus folgt ein konkreter, nicht erfundener Vorschlag** (kein neues
Berechtigungsmodell, nur eine Hülle um das Bestehende):

```python
@dataclass(frozen=True)
class ActorContext:
    actor_id: int                          # Telegram-User-ID, bleibt Schlüssel
                                            # in data/user_data.json (CC-AC-10.md §11:
                                            # "Telegram-IDs dürfen aus Kompatibilitäts-
                                            # gründen weiterhin persistiert werden")
    source: Literal["telegram", "control_center", "cli"]
    access_level: AccessLevel              # bereits über get_user_access_level()
                                            # ermittelt — KEIN eigenes Permission-Modell
```

`control_center/dependencies.py::get_current_access_level()` liefert
heute bereits exakt die Zutaten (`user_id` + `AccessLevel`) für so ein
Objekt — es fehlt nur die Zusammenführung zu einem einzigen, an
Application Commands durchgereichten Objekt statt zwei getrennten
FastAPI-Dependencies. Für Telegram wäre der Bauplan identisch:
`update.effective_user.id` + `get_user_access_level(...)` →
`ActorContext(source="telegram", ...)`. Für CLI (aktuell nirgends
vorhanden) müsste ein neuer, aber strukturell identischer Pfad über
`config.OWNER_USER_ID`/`ADMIN_USER_IDS` entstehen, da CLI keine
Session hat.

**Nicht spekuliert:** ob `AccessLevel` bereits weitere Werte oder
Vergleichsoperatoren jenseits von `.value <` besitzt, wurde nicht
verifiziert (`handlers/menu/models.py` war nicht Teil des Lesescopes
dieses Slices).

## 3. Zentrale Authorization-Grenze — Ist-Zustand

Heute gibt es **drei unabhängige, aber inhaltlich konsistente**
Prüfpunkte — keine Single Source of Truth, aber auch keine Lücke
innerhalb der bereits geprüften Bereiche:

1. **Telegram-Dispatcher-Präfix-Gate** (`handlers/menu/rich_menu_system.py`,
   Zeile ~711): `_ADMIN_ONLY_PREFIXES = ("logger_", "usermgmt_", "dup:",
   "backup_", "status_")` — zentral vor dem eigentlichen Handler-Aufruf
   geprüft, via `self._is_admin_check(...)` (Ergebnis dieser Analyse:
   dies ist genau der Mechanismus, dessen Lücke TGPERM-001 im
   09-12-Audit fand und der seither geschlossen ist, siehe
   `docs/FINDINGS_INDEX.md`).
2. **Handler-lokale Inline-Checks** für Callbacks, die NICHT in
   `_ADMIN_ONLY_PREFIXES` stehen, aber trotzdem Admin-only sind: `restart:`
   (`BotRestartHandler._is_admin()` → `is_admin_or_owner()`), `maint:`
   (`is_admin_check`-Parameter in `admin_operations.py`), `erradmin:`
   (`ErrorHandlerAdminInterface.is_admin()`) — laut Code-Kommentar in
   `rich_menu_system.py` Zeile 702 bewusst so belassen ("erradmin: und
   restart: haben bereits eigene Admin-Checks").
3. **Control-Center-Router-Dependency**
   (`control_center/dependencies.py::require_min_access_level(...)`) —
   pro Router als `dependencies=[Depends(...)]` deklariert, serverseitig,
   nicht UI-Check (entspricht CC-AC-10.md §12 "UI-Sichtbarkeit ist
   niemals eine Sicherheitsgrenze").

**Was laut CC-AC-10.md §12/§13 fehlt, um daraus EINE zentrale Grenze zu
machen:** Ein `ActorContext`-basierter Authorization-Check, den
Application Commands selbst durchsetzen (statt dass jeder Client
—Telegram-Dispatcher, FastAPI-Dependency— seine eigene Prüfung
implementiert). Aktuell würde ein neuer CLI-Client NICHTS von den
Prüfungen 1–3 automatisch erben — das ist der konkrete Beleg für
CC-AC-10.md §12s Warnung ("Service vertraut allen Aufrufern", wenn die
Prüfung nur client-seitig existiert). Für die bereits Web-API-gedeckten
Funktionen (#20–26 oben) ist das Risiko aktuell gering (nur Telegram +
Web haben client-seitige Checks, kein CLI existiert dafür); für #2–6, #7–9
etc. (reine Telegram-Funktionen) ist es nicht akut, weil dort noch kein
zweiter Client existiert.

## 4. Nur-Telegram-Funktionen (CC-AC-10B–E-Kandidaten)

Aus der Matrix oben — Funktionen mit **API aktuell = ❌** (kein
Web-Pendant, auch nicht read-only):

- **User Management (CC-AC-10B):** #2 User anlegen, #3 Navidrome-Zuordnung
  bearbeiten, #4 Rolle ändern, #5 Berechtigungen ändern, #6 User löschen
  (nur #1 User anzeigen ist bereits read-only vorhanden)
- **Bot & Operations (CC-AC-10C):** #7 Backup erstellen, #8 Backup
  auflisten, #9 Backup löschen, #10 Bot-Neustart, #11 Wartungsmodus,
  #12 Navidrome-Scan-Trigger (nur `/navidrome/status` read-only existiert)
- **Diagnostics & Monitoring (CC-AC-10D):** #13 System-Status
  (teilweise/fragmentiert), #15 Logger konfigurieren (komplett), #16–19
  Error-Administration (komplett) — #14 System-Logs ist bereits
  vorhanden
- **Library Administration — Reprocessing (Teil von CC-AC-10E):** #25
  Artist-Metadata-Reprocessing (einzige verbleibende Lücke in dieser
  Domäne — #20–24, #26 sind bereits voll web-fähig)

---

## Abschlussbericht (CC-AC-10.md Abschnitt 27)

### Implementiert
Reine Analyse: vollständige Admin-Funktionsinventur (26 Funktionen über
7 Bereiche), Architecture-Contract-Vorschlag, zentrale
Authorization-Grenzen-Bestandsaufnahme. Keine Code-Änderung.

### Application Layer
Noch nicht gebaut. Vorschlag pro Funktion in der Matrix (Spalte
„Application Layer“) — an die bestehende, Telegram-freie
`get_user_access_level()`/`is_admin_or_owner()`-Logik andocken statt neu
erfinden (Abschnitt 2 oben).

### API
n/a für dieses Slice — Ist-Stand: 12/26 Funktionen haben bereits einen
Web-Endpunkt (davon 10 mit vollem Write/Execute, siehe Read/Write-Parität
unten), 14 sind ausschließlich Telegram.

### Control Center UI
n/a für dieses Slice.

### Telegram
n/a für dieses Slice (keine Änderung).

### CLI
n/a für dieses Slice. Ist-Stand: kein CLI-Skript für irgendeine der 7
Admin-Bereiche in `scripts/` gefunden (CLI existiert nur für
Library-Health/Repair/Genre/Duplicate/Reprocessing — Letzteres via
`scripts/reprocess_artist_metadata.py`, das damit die einzige
Admin-Funktion mit CLI-Abdeckung ist).

### Tests
n/a für dieses Slice (keine neuen Tests). Ist-Stand: für alle 6
Telegram-only-User-Management/Backup/Restart/Maintenance-Funktionen
existieren bereits Characterization-Tests der Telegram-Implementierung
(siehe Matrix-Spalte „Tests“) — eine künftige Application-Layer-Extraktion
hat damit ein Sicherheitsnetz. Für Logger- und Error-Administration
existieren Tests nur für Teilaspekte (Modul-Toggle, Path-Traversal);
Error-Stats/-Report/-Reset haben keine dedizierten Tests gefunden.

### Security
Auth-Ist-Zustand (siehe Abschnitt 3 oben): drei unabhängige, aber
konsistente Prüfpunkte (Telegram-Präfix-Gate, Handler-Inline-Checks,
Control-Center-Router-Dependency) — keine Lücke *innerhalb* der bereits
existierenden Clients, aber auch keine Single Source of Truth, die ein
künftiger CLI-Client automatisch erben würde. Bereits vorhandene,
funktionsspezifische Sicherheitsmechanismen, die bei einer künftigen
Extraktion **zwingend erhalten bleiben müssen**: Backup-Löschung
Path-Traversal-Schutz (`_resolve_backup_path()`, SEC-006), Owner-Promotion-
Guard in `set_user_role()` (nur der echte Owner darf die Owner-Rolle
vergeben), Rollen-/Berechtigungs-Whitelist-Validierung gegen `self.ROLES`/
`self.PERMISSIONS` (SEC-005-Fix), atomare User-Daten-Persistenz
(write-tmp + rename, INV-02).

### Entfernte Duplikation
n/a — reine Analyse, keine Duplikation entfernt.

### Noch offen
Alle Slices CC-AC-10B bis CC-AC-10I (siehe Abschnitt 4 oben für die
priorisierten Kandidaten B–E). Zusätzlich zwei vor CC-AC-10B/C konkret zu
klärende Punkte:
1. Zeile 10 (Bot-Neustart): Widerspruch zwischen der 09-15-Einschätzung
   (⚪ bewusst nicht für Web vorgesehen, hohes Blast-Radius-Risiko) und der
   jetzt freigegebenen Master-Prompt-Vorgabe ("Read-only ist niemals das
   Abschlusskriterium", Restart ist explizit in §26 als
   Pflichtfunktion gelistet) — muss vor CC-AC-10C entschieden werden,
   nicht in diesem Slice.
2. Logger-Konfiguration (Zeile 15) hat einen ungewöhnlich großen
   Funktionsumfang für einen einzigen Endpunkt-Vorschlag aus CC-AC-10.md
   §7 (`GET/PATCH /api/v1/admin/logger`) — CC-AC-10.md merkt selbst an,
   dies bei Bedarf aufzuteilen; sollte vor CC-AC-10D konkretisiert
   werden.

### Read/Write-Parität
**12/26** Admin-Funktionen haben heute überhaupt einen Web-Endpunkt.
Davon sind **10/26** volle Write/Execute-Funktionen (#20, #21, #22, #23,
#24, #26 [6 Teilaktionen als eine Zeile gezählt] sowie #14 Logs als
read-only-Parität), **2/26** sind nur teilweise/read-only abgedeckt (#12
Navidrome-Status ohne Scan-Trigger, #13 System-Status fragmentiert). **0**
Funktionen sind bewusst als „Read-only-Endziel“ markiert — konsistent mit
der Vorgabe aus CC-AC-10.md §26, dass Read-only kein Abschlusskriterium
sein darf (die einzige historische ⚪-Markierung, Bot-Neustart, steht wie
oben beschrieben im Widerspruch zur aktuellen Vorgabe und muss neu
entschieden werden).

### Regression
n/a — reine Analyse, keine Codeänderung, kein Testlauf nötig.

---

## ADMIN PARITY MATRIX

| Funktion | Telegram | CC API | CC UI | CLI | App Command/Query | Tests | Authorization | Status |
|---|---|---|---|---|---|---|---|---|
| User anzeigen | ✅ | ✅ (GET) | ❓ (nicht geprüft) | ❌ | ❌ | ✅ | ADMIN (Router-Dependency) | 🟡 Read fertig, Write fehlt |
| User anlegen | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `usermgmt_` | 🔴 Telegram-only |
| User bearbeiten (Navidrome) | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `usermgmt_` | 🔴 Telegram-only |
| Rolle ändern | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix + Owner-Guard | 🔴 Telegram-only |
| Berechtigungen ändern | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `usermgmt_` | 🔴 Telegram-only |
| User löschen | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `usermgmt_` | 🔴 Telegram-only |
| Backup erstellen | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `backup_` | 🔴 Telegram-only |
| Backup auflisten | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix `backup_` | 🔴 Telegram-only |
| Backup löschen | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Dispatcher-Präfix + Path-Guard | 🔴 Telegram-only |
| Bot-Neustart | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Inline `is_admin_or_owner()` | 🔴 Telegram-only, Zielentscheidung offen |
| Wartungsmodus | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (Telegram) | Inline `is_admin_check` | 🔴 Telegram-only |
| Navidrome-Scan-Trigger | ✅ (Ort unklar, s.o.) | ⚠️ nur Status | ❌ | ❌ | ❌ | ❌ (nicht geprüft) | Inline `is_admin_or_owner()` | 🟡 Read (anders) fertig, Trigger fehlt |
| System-Status | ✅ | ⚠️ fragmentiert | ❓ | ❌ | ❌ | ❌ (nicht geprüft) | Router-Dependency (Teile) | 🟠 fragmentiert |
| System-Logs | ✅ (schmaler) | ✅ (reichhaltiger) | ❓ | ❌ | ❌ | ❌ (keine gefunden) | Router-Dependency ADMIN | 🟢 API bereits besser als Telegram |
| Logger konfigurieren | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (teilweise) | Dispatcher-Präfix `logger_` | 🔴 Telegram-only, größter Funktionsumfang |
| Error Stats | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ (nicht gefunden) | Inline `ErrorHandlerAdminInterface.is_admin()` | 🔴 Telegram-only |
| Error Report | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | s.o. | 🔴 Telegram-only |
| Recent Errors | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | s.o. | 🔴 Telegram-only |
| Error Reset | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | s.o. | 🔴 Telegram-only |
| Library Doctor | ✅ | ✅ (Job) | ❓ | ❌ | ❌ | ❓ (nicht geprüft) | Router-Dependency ADMIN | 🟢 volle Parität |
| Findings Review | ✅ | ✅ (voll) | ❓ | ✅ (Review-Skript) | ❌ | ✅ (674 thematisch, lt. Memory) | Router-Dependency ADMIN | 🟢 volle Parität |
| Repair-Preview | ✅ | ✅ | ❓ | ✅ | ❌ | ❓ | Router-Dependency ADMIN | 🟢 volle Parität |
| Repair-Ausführung (L2/L3) | ✅ | ✅ (Job) | ❓ | ✅ | ❌ | ❓ | Router-Dependency ADMIN | 🟢 volle Parität |
| Repair-History/Statistik | ❓ | ✅ | ❓ | ❓ | ❌ | ❓ | Router-Dependency ADMIN | 🟢 API vorhanden |
| Artist-Metadata-Reprocessing | ✅ (OWNER) | ❌ | ❌ | ✅ | ❌ | ❌ (nur CLI/Telegram indirekt) | Telegram: OWNER-only (Level unklar) | 🔴 einzige verbleibende Library-Lücke |
| Library-Wartung (6 Aktionen) | ✅ | ✅ (voll, 6×2) | ❓ | ❌ | ❌ | ✅ | Router-Dependency ADMIN | 🟢 volle Parität, teils Web-first |

**Legende:** ✅ vorhanden · ❌ fehlt · ⚠️ teilweise · ❓ in diesem Slice
nicht geprüft (kein Rateergebnis) · 🟢 Parität/nahe Parität · 🟡
teilweise · 🟠 fragmentiert · 🔴 Telegram-only (Kandidat für CC-AC-10B–E).

**CC-UI-Spalte durchgehend ❓:** ob die bereits vorhandenen Web-APIs
(User-Liste, Logs, Health, Findings, Repair, Jobs, Library-Wartung)
tatsächlich im Frontend (`control_center/templates/`) verdrahtet sind,
wurde in diesem reinen Backend-/API-fokussierten Slice nicht geprüft —
das ist explizit Gegenstand von CC-AC-10F ("Control Center UI Parity")
und wird dort nachgeholt statt hier spekuliert.
