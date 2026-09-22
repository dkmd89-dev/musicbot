Ja. Ich würde den Prompt gegenüber der vorherigen Version ausdrücklich um vollständige Read/Write-Parität erweitern. Besonders wichtig ist die Vorgabe, dass Read-only nur ein Zwischenstand sein darf und kein Zielzustand.

Hier ist die aktualisierte Version für Claude Code:

CC-AC-10 – Vollständige Administration API Integration

Ziel

Analysiere und migriere die bestehende Administration des MusicBot schrittweise von einer primär Telegram-zentrierten Bedienung zu einer client-unabhängigen Application/API-Architektur.

WICHTIG

Das Ziel ist NICHT eine Read-only-Administration im Control Center.

Nach Abschluss von CC-AC-10 muss das Control Center die bestehende Administration funktional vollständig bedienen können:

- Read
- Create
- Update
- Delete
- Execute
- Repair
- Restart
- Maintenance
- Reset
- sonstige schreibende oder destruktive Admin-Aktionen

Die API muss am Ende funktionale Parität mit dem bestehenden Telegram-Admin-Menü besitzen.

Telegram, Control Center und CLI sollen dabei dieselbe Application-/Core-Logik verwenden.

---

1. Zielarchitektur

Ziel:

                       MUSICBOT APPLICATION / CORE
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                 │
                ▼                 ▼                 ▼
         Control Center        Telegram            CLI
             API               Handler           Commands
                │                 │                 │
                └─────────────────┼─────────────────┘
                                  │
                         Application Commands
                              / Queries
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                 Services      Repositories    Domain

Grundregel:

«Business-Logik gehört nicht in Telegram-Handler oder FastAPI-Router.»

Telegram, Control Center und CLI sind Clients/Adapter.

---

2. Was ausdrücklich NICHT gebaut werden soll

Keine parallele zweite Business-Logik.

Nicht:

Telegram Admin
   ↓
eigene Implementierung

Control Center Admin
   ↓
zweite Implementierung

Sondern:

Telegram ────────┐
                 │
Control Center ──┼──→ Application Command/Query
                 │
CLI ─────────────┘
                       ↓
                    Services

Keine unnötige Enterprise-Architektur.

Kein vollständiger Rewrite.

Kein erzwungenes CQRS/Event-Bus-System.

Keine unnötigen neuen Abstraktionsschichten, wenn bestehende Services bereits sauber wiederverwendbar sind.

Bevorzugt:

«leichte Application-Schicht über der vorhandenen Service-Architektur.»

---

3. Zuerst: vollständiges Ist-Audit

Bevor Code geändert wird:

Analysiere den aktuellen "main" vollständig.

Erstelle eine vollständige Übersicht aller Administration-Funktionen.

Insbesondere:

handlers/menu/actions/
handlers/menu/
handlers/admin/
control_center/
services/
utils/
tests/
docs/

Untersuche insbesondere:

- "admin_operations.py"
- "admin_diagnostics.py"
- "usermgmt.py"
- "library.py"
- "rich_menu_system.py"
- "rich_menu_handler.py"
- bestehende Control-Center-Router
- bestehende Admin-Services
- bestehende Tests
- bestehende Berechtigungsprüfungen
- bestehende Sicherheitsmechanismen

Nutze vorhandene Dokumentation und Architekturentscheidungen.

Nicht bereits gelöste Probleme erneut aufreißen, wenn sie für diese Migration nicht notwendig sind.

---

4. Erstelle eine Admin-Funktionsmatrix

Vor der Implementierung eine Matrix erstellen:

Funktion| Telegram| API aktuell| API Ziel| Application Layer| Tests
User anzeigen| ✓| ✓/–| ✓| | 
User anlegen| ✓| –| ✓| | 
User bearbeiten| ✓| –| ✓| | 
Rolle ändern| ✓| –| ✓| | 
User löschen| ✓| –| ✓| | 
Navidrome-Zuordnung| ✓| –| ✓| | 
Backup erstellen| ✓| –| ✓| | 
Backup löschen| ✓| –| ✓| | 
Bot restart| ✓| –| ✓| | 
Maintenance| ✓| –| ✓| | 
Navidrome Scan| ✓| –| ✓| | 
Status| ✓| ✓| ✓| | 
Logs| ✓| ✓/–| ✓| | 
Logger konfigurieren| ✓| –| ✓| | 
Error Stats| ✓| –| ✓| | 
Error Reset| ✓| –| ✓| | 
Library Doctor| ✓| –| ✓| | 
Review| ✓| –| ✓| | 
Repair| ✓| –| ✓| | 
Reprocessing| ✓| –| ✓| | 

Die Matrix ist während der gesamten Migration aktuell zu halten.

Keine Funktion darf am Ende unbewusst Read-only bleiben.

---

5. Admin-Bereiche

Die Migration soll mindestens folgende Bereiche abdecken.

5.1 User Management

Vollständige API-Funktionalität:

GET    /api/v1/admin/users
POST   /api/v1/admin/users
PATCH  /api/v1/admin/users/{id}
DELETE /api/v1/admin/users/{id}

Je nach bestehender Domänenlogik zusätzlich:

PATCH .../role
PATCH .../permissions
PATCH .../navidrome

Aber nicht blind diese Endpunkte erzwingen.

Zuerst bestehende Modelle und Services analysieren.

Unterstützen:

- User auflisten
- User anlegen
- User bearbeiten
- Rollen ändern
- Berechtigungen ändern
- Navidrome-Zuordnung
- Aktivierung/Deaktivierung, sofern vorhanden
- User löschen
- bestehende Sicherheits-/Bestätigungslogik

Bestehende "services/user_data.py"-Logik wiederverwenden.

---

6. Bot & Operations

Vollständig schreibend nutzbar.

Beispielsweise:

GET  /api/v1/admin/backups
POST /api/v1/admin/backups

DELETE /api/v1/admin/backups/{id}

POST /api/v1/admin/system/restart

GET  /api/v1/admin/maintenance
POST /api/v1/admin/maintenance
DELETE /api/v1/admin/maintenance

POST /api/v1/admin/navidrome/scan

Die tatsächlichen Endpunkte nach Analyse des bestehenden Codes festlegen.

Nicht nur Status anzeigen.

Operationen müssen tatsächlich ausführbar sein.

Bestehende sichere Restart-/Backup-Implementierungen wiederverwenden.

---

7. Diagnostics & Monitoring

API muss sowohl Lesen als auch relevante Änderungen unterstützen.

Beispielsweise:

GET /api/v1/admin/status

GET /api/v1/admin/logs
GET /api/v1/admin/logs/{filename}

GET /api/v1/admin/errors/stats
GET /api/v1/admin/errors/report
GET /api/v1/admin/errors/recent

POST /api/v1/admin/errors/reset

GET   /api/v1/admin/logger
PATCH /api/v1/admin/logger

Falls Logger-Konfiguration mehrere Aktionen besitzt, diese entsprechend modellieren.

Telegram-spezifische Darstellung darf nicht in die Application-Schicht wandern.

---

8. Library Administration

Alle bestehenden Library-Admin-Aktionen untersuchen.

Insbesondere:

- Reprocessing
- Doctor
- Review
- Repair
- Library Health
- Navidrome-bezogene Wartung
- sonstige bestehende Admin-Aktionen

Dabei ausdrücklich unterscheiden:

Read operation
Write operation
Destructive operation
Long-running operation

Beispiel:

GET  /api/v1/admin/library/review
POST /api/v1/admin/library/repair
POST /api/v1/admin/library/reprocess
POST /api/v1/admin/library/doctor

Die konkreten Endpunkte anhand der tatsächlichen Domänenlogik festlegen.

---

9. Application Commands

Für schreibende Aktionen bevorzugt Commands verwenden.

Beispiele:

CreateUserCommand
UpdateUserCommand
DeleteUserCommand
UpdateUserRoleCommand

CreateBackupCommand
DeleteBackupCommand

RestartBotCommand

EnableMaintenanceModeCommand
DisableMaintenanceModeCommand

RunNavidromeScanCommand

ResetErrorStatisticsCommand
UpdateLoggerConfigurationCommand

RepairLibraryCommand
ReprocessLibraryCommand
RunLibraryDoctorCommand

Diese Namen sind Beispiele.

Bestehende Services analysieren und keine künstlichen Commands erzeugen, wenn eine bessere vorhandene Abstraktion existiert.

---

10. Queries

Für reine Leseoperationen:

GetUsersQuery
GetSystemStatusQuery
GetBackupsQuery
GetLogsQuery
GetErrorStatisticsQuery
GetErrorReportQuery
GetLoggerConfigurationQuery
GetLibraryReviewQuery

Auch hier gilt:

Nicht zwanghaft CQRS implementieren.

Die Trennung dient primär der klaren Verantwortlichkeit.

---

11. ActorContext

Die Application-Schicht darf nicht von Telegram abhängen.

Beispiel:

ActorContext(
    actor_id=...,
    source="telegram" | "control_center" | "cli",
    permissions=...
)

Keine Business-Logik wie:

if telegram_user_id == ...

im Application Layer.

Bestehende Telegram-IDs dürfen aus Kompatibilitätsgründen weiterhin persistiert werden.

Die Application-Schicht soll jedoch eine client-unabhängige Identität verwenden.

---

12. Authorization

Berechtigungen müssen zentral geprüft werden.

Nicht:

Telegram prüft Admin
API prüft Admin
Service vertraut allen Aufrufern

Sondern:

Client
  ↓
Application Command
  ↓
Authorization
  ↓
Service

Dabei vorhandene "AccessLevel.ADMIN"-Mechanismen und Berechtigungsstrukturen untersuchen und sinnvoll wiederverwenden.

Wichtig:

«UI-Sichtbarkeit ist niemals eine Sicherheitsgrenze.»

Eine API-Anfrage darf nicht deshalb funktionieren, weil ein Benutzer den entsprechenden Button nicht sehen kann.

---

13. Security

Besonders kritisch:

- Privilege Escalation
- direkte API-Aufrufe
- CSRF / Same-Origin-Schutz
- User-Löschung
- Rollenänderung
- Backup-Löschung
- Dateipfade
- Log-Dateien
- Restart
- Maintenance
- Library Repair
- destruktive Operationen

Vorhandene Sicherheitsfixes dürfen nicht durch die Migration verloren gehen.

Insbesondere historische Security-Fixes aus der Engineering Baseline berücksichtigen.

Keine direkte unkontrollierte Dateisystem-Manipulation aus FastAPI-Routern.

Keine Telegram-Callback-Sicherheit als alleinige Schutzmaßnahme übernehmen.

---

14. Destruktive Aktionen

Destruktive Aktionen benötigen eine explizite und nachvollziehbare Sicherheitslogik.

Beispiele:

DELETE user
DELETE backup
library repair
reset errors
restart
maintenance changes

Falls die Telegram-Oberfläche bereits Bestätigungsmechanismen besitzt:

show
→ confirm
→ execute

diese Logik nicht einfach als Telegram-Callback übernehmen.

Stattdessen:

Application Command
    ↓
Authorization
    ↓
Validation / Confirmation requirement
    ↓
Execution

Das Control Center muss dieselbe fachliche Sicherheitslogik verwenden können.

---

15. Long-running Operations

Prüfe bei:

- Library Doctor
- Repair
- Reprocessing
- Navidrome Scan
- Backup
- sonstigen längeren Aktionen

ob sie synchron oder als Job ausgeführt werden sollten.

Nicht automatisch alles in Background Jobs verschieben.

Bestehende Job-Infrastruktur wiederverwenden, falls vorhanden.

Das API-Modell soll sauber darstellen können:

queued
running
completed
failed

falls die bestehende Architektur das bereits unterstützt oder dies für die konkrete Operation erforderlich ist.

---

16. Control Center Router

FastAPI-Router bleiben dünn.

Beispiel:

@router.post("/system/restart")
async def restart_system(actor: ActorContext = Depends(...)):
    result = await restart_bot.execute(
        RestartBotCommand(actor=actor)
    )

    return result

Keine umfangreiche Business-Logik im Router.

Keine direkten Telegram-Imports.

Keine direkte Wiederholung bestehender Handlerlogik.

---

17. Telegram Handler

Telegram soll nach der Migration ebenfalls den Application Layer verwenden.

Beispiel:

Telegram callback
      ↓
parse input
      ↓
Application Command
      ↓
Application result
      ↓
Telegram presentation

Der Handler ist anschließend hauptsächlich verantwortlich für:

- Telegram Input
- Callback Parsing
- Benutzerinteraktion
- Darstellung
- Bestätigungsdialoge
- Telegram-spezifische Navigation

Nicht für die eigentliche Business-Operation.

---

18. Control Center UI

Das Control Center muss die neuen Write-Funktionen auch tatsächlich anbieten.

Nicht nur API-Endpunkte bauen und anschließend behaupten, die Integration sei abgeschlossen.

Für jede relevante Admin-Funktion prüfen:

API vorhanden?
Application Command vorhanden?
Control Center UI vorhanden?
Telegram weiterhin funktional?
Berechtigung vorhanden?
Tests vorhanden?

Beispiele:

User
  → Create
  → Edit
  → Role
  → Delete

Backups
  → Create
  → List
  → Delete

System
  → Restart
  → Maintenance
  → Navidrome Scan

Diagnostics
  → Logs
  → Logger Configuration
  → Error Reset

Library
  → Review
  → Doctor
  → Repair
  → Reprocess

---

19. CLI

Falls bereits entsprechende CLI-Funktionen existieren:

CLI ebenfalls auf dieselben Application Commands umstellen.

Ziel:

Telegram ───────┐
Control Center ─┼──→ Application
CLI ────────────┘

Nicht drei Implementierungen.

---

20. Migration vertikal durchführen

Nicht zuerst sämtliche Telegram-Dateien umbauen.

Nicht zuerst eine riesige abstrakte Application-Schicht bauen.

Stattdessen vertikal:

CC-AC-10A

Admin Inventory + Architecture Contract

Nur Analyse und Boundary Definition.

CC-AC-10B

User Management

Read + Create + Update + Delete.

CC-AC-10C

Bot & Operations

Backup + Restart + Maintenance + Navidrome Scan.

CC-AC-10D

Diagnostics & Monitoring

Status + Logs + Logger + Error Administration.

CC-AC-10E

Library Administration

Review + Doctor + Repair + Reprocessing.

CC-AC-10F

Control Center UI Parity

Alle API-Funktionen tatsächlich im Web UI verfügbar machen.

CC-AC-10G

Telegram Migration

Telegram auf dieselben Application Commands umstellen.

CC-AC-10H

CLI Integration

Vorhandene CLI-Funktionen auf denselben Layer bringen.

CC-AC-10I

Parity & Architecture Audit

Prüfen:

Telegram == Control Center == CLI

hinsichtlich der fachlichen Operationen.

---

21. Tests

Jede neue Application-Funktion benötigt Tests.

Mindestens:

Application

test_admin_user_create
test_admin_user_update
test_admin_user_delete
test_admin_role_change
test_admin_permission_denied

API

test_admin_api_create_user
test_admin_api_update_user
test_admin_api_delete_user
test_admin_api_requires_admin

Security

test_non_admin_cannot_restart
test_non_admin_cannot_delete_user
test_non_admin_cannot_delete_backup
test_invalid_backup_path_rejected
test_unauthorized_library_repair_rejected

Telegram

test_telegram_admin_command_uses_application_service

Parity

Wo sinnvoll:

same command
same authorization
same result semantics

Keine API-Funktion ohne Tests abschließen.

---

22. Architektur-Guardrails

Nach Möglichkeit automatisierte Checks einführen.

Beispielsweise darf:

application/
services/
domain/

nicht von:

telegram
control_center

abhängen.

Control Center darf nicht Business-Logik aus Telegram importieren.

Telegram darf Application Commands verwenden.

Architekturverletzungen sollen durch Tests/Linting/Checks möglichst früh auffallen.

---

23. Dokumentation

Nach jedem abgeschlossenen Teilbereich dokumentieren:

- welche Telegram-Funktionen existierten
- welche Application Commands/Queries entstanden
- welche API-Endpunkte entstanden
- welche UI-Funktionen entstanden
- welche Telegram-Handler migriert wurden
- welche Tests entstanden
- welche Sicherheitsmaßnahmen relevant sind
- welche alten Funktionen entfernt/deprecated wurden
- welche offenen Punkte verbleiben

Die bestehende Architektur-Dokumentation erweitern, nicht unnötig neue Dokumentationssysteme erfinden.

---

24. Wichtige Regel für bestehende Services

Vor jeder neuen Implementierung:

«Suche zuerst nach vorhandener Logik.»

Prüfe:

services/
utils/
handlers/
jobs/
repositories/

Wenn bereits eine sichere und getestete Funktion existiert:

Application Command
        ↓
bestehender Service

statt:

Application Command
        ↓
neue zweite Implementierung

Duplikation vermeiden.

---

25. Keine Big-Bang-Migration

NICHT:

alle Telegram Admin Handler löschen
alle neuen API Router gleichzeitig bauen
anschließend hoffen, dass alles funktioniert

Stattdessen:

bestehende Funktion
      ↓
charakterisieren/testen
      ↓
Application Boundary
      ↓
API
      ↓
Control Center UI
      ↓
Telegram auf Application umstellen
      ↓
alte Business-Logik entfernen

Nach jedem vertikalen Slice muss der bestehende MusicBot weiterhin funktionieren.

---

26. Definition of Done

CC-AC-10 ist erst abgeschlossen, wenn:

Architecture

- [ ] Business-Logik ist client-unabhängig
- [ ] Application Layer existiert dort, wo er benötigt wird
- [ ] Control Center hängt nicht von Telegram ab
- [ ] Telegram hängt für Admin-Business-Logik nicht direkt von Implementierungsdetails ab
- [ ] CLI verwendet nach Möglichkeit denselben Application Layer

Functionality

- [ ] User Management vollständig
- [ ] Backup vollständig
- [ ] Restart verfügbar
- [ ] Maintenance verfügbar
- [ ] Navidrome Scan verfügbar
- [ ] Diagnostics verfügbar
- [ ] Logger-Konfiguration verfügbar
- [ ] Error Administration verfügbar
- [ ] Library Administration verfügbar
- [ ] Repair verfügbar
- [ ] Reprocessing verfügbar
- [ ] alle weiteren bestehenden Admin-Funktionen inventarisiert und migriert

Read/Write Parity

- [ ] Read-Funktionen verfügbar
- [ ] Create-Funktionen verfügbar
- [ ] Update-Funktionen verfügbar
- [ ] Delete-Funktionen verfügbar
- [ ] Execute-Funktionen verfügbar
- [ ] destruktive Aktionen verfügbar
- [ ] keine bewusst als Read-only zurückgelassene Admin-Funktion

Read-only ist nur ein Zwischenzustand, niemals das Abschlusskriterium.

Security

- [ ] zentrale Authorization
- [ ] ActorContext
- [ ] CSRF/Same-Origin bei Browser-Mutationen
- [ ] keine Privilege Escalation
- [ ] Path-Traversal-Schutz
- [ ] sichere Delete-Operationen
- [ ] sichere Restart-/Maintenance-Operationen
- [ ] sichere Library-Mutationen

Testing

- [ ] Application Tests
- [ ] API Tests
- [ ] Security Tests
- [ ] Telegram Adapter Tests
- [ ] bestehende Tests weiterhin grün
- [ ] Regressionstests für migrierte Funktionen

UI

- [ ] Control Center kann alle relevanten Admin-Aktionen tatsächlich ausführen
- [ ] keine „API vorhanden, UI fehlt“-Lücken
- [ ] Fehler werden verständlich dargestellt
- [ ] destructive actions besitzen geeignete Bestätigung
- [ ] laufende Jobs/Aktionen werden nachvollziehbar dargestellt

---

27. Abschlussbericht

Nach jedem CC-AC-Teil einen kurzen Bericht erstellen:

## CC-AC-10X

### Implementiert
- ...

### Application Layer
- ...

### API
- ...

### Control Center UI
- ...

### Telegram
- ...

### CLI
- ...

### Tests
- ...

### Security
- ...

### Entfernte Duplikation
- ...

### Noch offen
- ...

### Read/Write-Parität
- X/Y Admin-Funktionen vollständig

### Regression
- pytest: ...

Am Ende zusätzlich eine vollständige:

ADMIN PARITY MATRIX

mit:

Telegram
Control Center API
Control Center UI
CLI
Application Command/Query
Tests
Authorization
Status

---

28. Wichtigste Leitlinie

Die zentrale Frage bei jeder bestehenden Admin-Funktion lautet:

«„Wo befindet sich heute die eigentliche fachliche Operation und wie können Telegram, Control Center und CLI dieselbe Operation verwenden?“»

Nicht:

«„Wie kopiere ich diesen Telegram-Handler in FastAPI?“»

Das Endziel ist:

                  ┌────────────────────┐
                  │  Application/Core  │
                  │                    │
                  │ Commands / Queries │
                  │ Authorization      │
                  │ Services           │
                  └─────────┬──────────┘
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Control Center   Telegram         CLI
             │              │              │
          Web UI         Telegram UX     Terminal

Eine fachliche Administration – mehrere Clients.

Und nach Abschluss muss das Control Center nicht nur beobachten können, was der Bot macht, sondern die Administration tatsächlich durchführen können.Das würde ich jetzt als Master-Prompt für CC-AC-10 verwenden. Der entscheidende Unterschied zur vorherigen Version ist: Read-only-Parität ist ausdrücklich kein akzeptierter Endzustand.