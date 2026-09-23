# CC-LOGGER-L3 — Runtime-Control Architecture Decision

**Datum:** 2026-09-23
**Auslöser:** `logge.txt` (Phasenplan Logger-API L1–L7), Nutzerfreigabe
für L3.
**Vorgänger:** L1-Charakterisierung (Function-Matrix), L2-Read-API
(`docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`).
**Status:** ARCHITECTURE DECISION RECORD — verbindlich für L4–L6.
**Keine Implementierung in L3:** dieses Dokument entscheidet, es
implementiert nicht. Umsetzung beginnt mit L4.

---

## 1. Executive Summary

Für Logger-Runtime-Control im MusicBot existiert heute **keine**
Cross-Process-Infrastruktur: keine IPC, kein Unix-Socket, kein
Localhost-Kanal, kein File-Watcher, kein Reload-Trigger. Der einzige
vorhandene Steuerungs-Mechanismus ist `sudo systemctl restart bot` über
`utils/bot_restart_trigger.py`.

Gleichzeitig hat die Analyse einen **bestehenden Architektur-Bug**
offengelegt: `ModuleLoggerManager._load_module_configs()` liest die
persistente Konfiguration beim Bot-Start, wendet sie aber nicht auf die
Runtime an. Die Datei ist damit **keine Runtime-Wahrheit**.

Die L3-Entscheidung lautet: **kein neuer permanenter IPC-Kanal in L4**.
Stattdessen ein inkrementeller Pfad über einen persistenten Config-Write
(Stufe 1), einen Runtime-Snapshot (Stufe 2) und einen **kontrollierten
Apply/Restart mit Preflight** (Stufe 3). Ein Unix-Socket als echte
Live-Runtime-Write-Infrastruktur bleibt **explizit deferred** (Stufe 4),
mit klarem Re-Evaluierungs-Trigger — nicht, weil er technisch falsch
wäre, sondern weil sein Nutzen für den realen MusicBot-Betrieb nicht
belegt ist.

---

## 2. Ausgangslage

### 2.1 L1/L2 — bereits abgeschlossene Vorbedingungen

Aus L2 (`CC_LOGGER_L2_READ_API_2026-09-23.md`):

- `services/logger_admin.py` (Application Layer, Telegram-frei,
  FastAPI-frei).
- `GET /api/v1/admin/logger/files` (Logdatei-Liste)
- `GET /api/v1/admin/logger/files/stats` (Aggregat)
- `GET /api/v1/admin/logger/files/{name}` (Detail + Filter + Limit)
- Wiederverwendung von `services/logs/reader.py` — kein zweiter Parser.
- ADMIN-Auth, Path-Traversal-Schutz, Limit-Grenzen server-seitig.
- `/api/v1/logs` bleibt unverändert (zeilen-orientierte Live-Ansicht).
- Telegram bleibt unverändert.

### 2.2 Kompakte Logger-Funktionsklassen (aus L1)

**Class A — Filesystem-backed Operations** (shared filesystem, im
CC-Prozess unverändert lesbar):
Log-Dateiliste, Datei-Detail, Datei-Statistiken, Cleanup-Menü
(Anzeige).

**Class B — Runtime Logger Control** (process-local im Bot-Prozess):
Modul-Level setzen, Modul aktivieren/deaktivieren, Globales Level
ändern, File-/Console-Handler manipulieren, Handler-Reload,
Process-lokale Logger-/Handler-Statusabfragen, ExceptionMonitor-State.

**Class C — Advanced/Placeholder Operations** (heute unvollständig,
nicht Teil von L3):
`add_handler` / `remove_handler` / `add_module` / `download_log_file`
sind im bestehenden Telegram-Handler selbst nur Platzhalter ohne
Funktion.

Die **vollständige Function-Matrix** und L2-Implementierungsdetails
bleiben in den jeweiligen Audit-Dokumenten
(`CC_LOGGER_L2_READ_API_2026-09-23.md`, L1-Analyse im Vorfeld).

### 2.3 L3-Analysebefunde (nicht GitHub-verifiziert)

Alle im Folgenden als „Analysebefund" bezeichneten Punkte sind aus dem
Arbeitsstand des Repositorys abgeleitet, nicht aus einem zum
Dokumentationszeitpunkt extern abgeglichenen Commit. Sie sind als
Grundlage dieser Entscheidung ausreichend belastbar, aber im Einzelfall
nur so aktuell wie der Arbeitsstand.

---

## 3. Tatsächliches Process Model (L3.1)

| Dimension | Analysebefund |
|---|---|
| Host | Ein einzelner Server |
| User | `robin` — beide Services |
| Bot-Service | systemd-Unit `bot.service`, `Restart=always`, `RestartSec=10` |
| CC-Service | systemd-Unit `control-center.service`, `Restart=on-failure`, `RestartSec=3` |
| Deployment | Kein Docker, kein Container, kein Multi-Worker. Zwei Prozesse, eine systemd-Instanz, dieselbe UID |
| CC-Exposure | `127.0.0.1:8420` + nginx Reverse-Proxy davor |

**IPC-Bestand im Repo:** kein AF_UNIX, keine Named Pipes, kein
localhost-Listener im Bot, keine Queue, kein Redis, keine DB, kein
File-Watcher. **Signal-Handling:** nur `SIGINT`/`SIGTERM` in
`bot.py::setup_signal_handlers`, kein Runtime-Reload-Signal.

**Bestehende Control-Infrastruktur:** `BotRestartTrigger.trigger_restart()`
→ `sudo systemctl restart <service>`, synchron, 15 s Timeout,
NOPASSWD-Sudo-Recht. Aus CC-AC-10C über
`POST /api/v1/admin/system/restart` erreichbar.

**Konsequenz:** Jeder Runtime-Kanal müsste **von Null** gebaut werden.
Das ist ein Analysebefund, keine Meinung.

---

## 4. Logger Lifecycle (L3.2)

### 4.1 `_module_loggers`

Ein reines Dict `Dict[str, logging.Logger]` in `logger.py`. Wird
prozesslokal befüllt, wenn Module `get_module_logger()` /
`setup_module_logging()` aufrufen. Kein Singleton, keine Persistenz,
keine Synchronisierung. Stirbt mit dem Bot-Prozess.

### 4.2 `ModuleLoggerManager`

Kein Singleton. Wird in `EnhancedLoggerMenuHandler.__init__` erzeugt.
Wird in `RichMenuHandler.initialize()` erzeugt. Wird in `bot.py` einmal
beim Bot-Start erzeugt. **Lebt genau einen Bot-Prozess lang.**

### 4.3 `_load_module_configs()` — der bestehende Architektur-Bug

Der Body liest die JSON in `self.module_configs`. Er **ruft
`_apply_module_config()` nicht auf**. Konsequenz:

- Nach jedem Bot-Neustart laufen alle Module mit den Code-Defaults aus
  `logger.py` — nicht mit den Leveln aus der JSON.
- Die Datei ist eine **Absichtserklärung ohne Wirkung** für den
  Startzeitpunkt.
- Einzige Ausnahme: nach einem Telegram-Klick auf einen Logger-Button
  ruft `set_module_config()` sowohl `_save_module_configs()` als auch
  `_apply_module_config()` auf. Für **genau dieses eine Modul** sind
  Datei und Runtime dann konsistent.

**Dieser Bug ist eine harte Voraussetzung für jede Runtime-Option**
(siehe §6 State Ownership, §15 Zielarchitektur Stufe 0).

### 4.4 `set_global_log_level()`

Setzt `root_logger.setLevel(...)` und iteriert über
`_module_loggers`. **Keine Persistenz.** Nach Bot-Restart → Level
zurück auf Config-Default.

### 4.5 `get_active_modules()`

Liest zwei Quellen: `logging.Logger.manager.loggerDict` (prozesslokal)
und `self.module_configs` (eingefrorene Kopie der JSON zum
Startzeitpunkt). Aus dem CC-Prozess ist beides nicht identisch lesbar.

---

## 5. Control Center Lifecycle (L3.1)

`create_app()` baut die FastAPI-App. Zustand liegt in `app.state`.
Kein Modul-Level-Singleton außer der App-Instanz. Kein Startup-Hook,
kein Shutdown-Hook. Kein Hintergrund-Task. Der CC-Prozess ist ein
reiner Request-Response-Server.

---

## 6. State Ownership (L3.4)

Drei Ebenen, getrennt:

```
① Persistente Konfiguration  data/module_logger_config.json
auf Platte, von beiden Prozessen lesbar

② Desired Runtime State
existiert heute NICHT als eigene Entität
(implizit angenommen = Dateiinhalt)

③ Actual Runtime State
_module_loggers, loggerDict, Logger.handlers,
Logger.level, Logger.disabled, root_logger.level
lebt und stirbt mit dem Bot-Prozess
```


Zwischen ① und ② existiert kein Kanal. Zwischen ② und ③ gibt es einen
unidirektionalen In-Process-Pfad, aber nur wenn jemand ihn auslöst.

**Zuordnung Property → Ebene:**

| Property | ① Persistiert in | ② Desired | ③ Actual |
|---|---|---|---|
| Globales Log-Level | nicht persistiert | `Config.LOG_LEVEL` | `logging.getLogger().level` |
| Modul-Level | JSON: `"level": "INFO"` | = JSON-Wert | `_module_loggers[name].logger.level` |
| Modul enabled/disabled | JSON: `"enabled": true` | = JSON-Wert | `logger.disabled` |
| File-Handler an/aus | JSON: `"file_handler": true` | = JSON-Wert | Präsenz `FileHandler` in `logger.handlers` |
| Console-Handler an/aus | JSON: `"console_handler": true` | = JSON-Wert | Präsenz `StreamHandler` |
| Handler-Reload | n/a | n/a | `_apply_module_config()` je Modul |

---

## 7. Cross-Process Problem

Aus §3, §4, §6 folgt zwingend:

- Runtime-Zustand ist zu 100 % prozesslokal.
- Persistenter Zustand ist zu 100 % in der JSON.
- Es gibt **keine** Brücke zwischen beiden.

Ohne einen expliziten Kanal (Signal, Socket, HTTP, File-Watcher,
Neustart) gibt es keine Möglichkeit, dass CC den Bot-Logger-Zustand
liest oder schreibt.

**Konsequenz für jede API, die Runtime-Control behauptet:** sie muss
entweder
(a) den Kanal ehrlich benennen (Restart, Socket, HTTP), **oder**
(b) ausdrücklich als „persistent für nächsten Start" deklariert sein.

Eine API, die nur die JSON schreibt und „Erfolg" meldet, während der
Bot weiterläuft, wäre eine **Fake-Live-API**. Verboten nach `logge.txt`
§4/§15.

**Wichtige Trennung:** *Runtime-Read* (Observability: „was tut der Bot
gerade?") und *Runtime-Write* (Steuerung) sind eigenständige Probleme.
Read ist strukturell billiger und sicherer als Write. Sie werden im
Folgenden getrennt bewertet.

---

## 8. Untersuchte Optionen (L3.5)

### A — Persistence + File-Watcher-Reload

Neuer File-Watcher im Bot (watchdog/inotify). CC schreibt JSON, Bot
erkennt Änderung, ruft Reload.

**Analysebefund:** Kein Rückkanal → CC kann keinen echten Erfolg
bestätigen. Race-Risiko auf `logger.handlers`-Mutation. Neuer
Hintergrund-Thread im Bot. Löst das Bestätigungsproblem nicht.

### B — Unix Domain Socket

Bot bindet AF_UNIX-Socket, CC sendet strukturierte Commands,
Bot antwortet mit Actual State.

**Analysebefund:** Technisch korrekt, einzige Option mit echter
Bestätigung ohne Restart. Kostet einen dauerhaften Kontroll-Kanal im
Bot (Listener, Protocol, Command-Handler, Tests). Auth über
Socket-Permissions ist begrenzt, weil CC und Bot als derselbe User
`robin` laufen — der Socket schützt strukturell nicht gegen eine
kompromittierte CC-Instanz; die Admin-Auth im CC-Router bleibt die
eigentliche Schicht.

**Nicht automatisch der einzige ehrliche Weg** für Live-Control — sie
ist eine von mehreren möglichen Runtime-Write-Architekturen. Die
entscheidende Frage ist nicht „wie", sondern „ob der permanente
Kanal-Aufwand seinen Nutzen rechtfertigt".

### C — Localhost HTTP Control Endpoint

Wie B, aber über HTTP auf 127.0.0.1.

**Analysebefund:** Alle Nachteile von B plus größerer Stack im Bot
(neue Bot-Dependency HTTP-Framework), Token-Persistenz nötig,
Port-Kollisionen, SSRF-Fläche bei Container-/SSH-Forward-Szenarien.
`127.0.0.1` ist **nicht automatisch sicher**. Überdimensioniert
gegenüber B.

### D — Controlled Restart

CC schreibt JSON, ruft `BotRestartTrigger.trigger_restart("bot")`,
systemd startet Bot neu, Bot liest JSON (mit Bugfix) und wendet an.

**Analysebefund:** Nutzt bestehende Infrastruktur. Minimale neue
Angriffsfläche. Kompatibel mit bestehender ADMIN-Auth und CSRF.
Bestätigung **indirekt** (RC=0 von systemctl ≠ „Bot läuft mit
Config") — mit Snapshot (siehe D+) aber echt nachweisbar.

**Job-Verlust-Risiko** (siehe §10 Failure Analysis):
Laufende `repair_safe_automatic`/L2/L3-Repairs und laufende
Repair-Subprozesse sterben mit dem Bot-Prozess. `asyncio.CancelledError`
fängt laufende Downloads sauber ab, aber **laufende Jobs sind
verloren**. Restart darf daher **nicht als triviale Logger-Änderung**
dargestellt werden.

### D+ — Restart + Runtime Snapshot

Wie D, plus: Bot schreibt unmittelbar nach `_apply_module_config()`
einen Snapshot seines effektiven Runtime-Zustands nach
`data/logger_runtime_snapshot.json`. CC liest die Datei und kann
**echten Actual State** belegen.

**Analysebefund:** Gleiche Korrektheit wie B, gleiche Ehrlichkeit wie
B — nur der Weg (Datei-Polling vs. Socket-Response) unterscheidet sich.
Kein neuer Kanal, keine neue Infrastruktur im Bot außer einem
Datei-Write beim Start.

**D+ ist nicht „die Endarchitektur", sondern die aktuelle
Zielarchitektur für L3/L4–L6.** Runtime-Write über IPC bleibt bewusst
deferred. Ein Restart-Wrapper mit Snapshot löst das Problem des
Job-Verlusts bei aktivem Bot-Betrieb nicht grundsätzlich — der Restart
darf deshalb nicht als normale Logger-Änderung dargestellt werden,
sondern als expliziter administrativer Betriebsvorgang mit Preflight.

### E1 — Strikte Read-only

CC liest JSON. Write nur via SSH.

**Analysebefund:** Ehrlich, minimal, aber weniger CC-Mehrwert als E2.

### E2 — CC darf persistente Konfiguration ändern

Write-Endpoint in CC mit klarer Semantik „wirksam beim nächsten
Start". Kein Fake-Live-Versprechen.

**Analysebefund:** Bestehende Auth/CSRF-Schicht reicht. Eine Quelle
der Wahrheit (JSON). Kein neuer Kanal. Für die meisten derzeit
identifizierten Use-Cases ausreichend.

**E2 könnte bereits einen großen Teil des gewünschten
Control-Center-Mehrwerts liefern, ohne Runtime-Control
vorzutäuschen.** Wichtig: „kein Runtime-Control" bedeutet nicht
„Logger-Funktionalität aufgeben". Ein sauberes Zielbild ist:

Control Center
├── Logger Files              ← L2, live
├── Logger Configuration      ← persistent
├── Runtime Status            ← später read-only
└── Runtime Control           ← nur falls tatsächlich erforderlich


---

## 9. Security Analysis

### 9.1 Für E2 + D + D+ (empfohlener Pfad)

- **Auth:** bestehende `AccessLevel.ADMIN`-Schicht (CC-AC-10) —
  wiederverwendet, keine parallele Architektur.
- **CSRF:** bestehendes `verify_same_origin()` für schreibende
  Endpunkte — wiederverwendet.
- **Keine neue Angriffsfläche im Bot** — kein neuer Socket, kein neuer
  Port, kein neuer Listener.
- **Kein neues Secret** — kein Token, kein Shared Secret.
- **Command Injection:** keiner. `systemctl restart bot` mit fest
  verdrahtetem Service-Argument.
- **Path Traversal:** JSON-Pfad ist fest verdrahtet, kein Nutzer-Input.
- **JSON-Validation:** Pydantic-Schema im CC-Router vor dem Write;
  Bot-Fallback auf Defaults bei korruptem JSON (heute schon im Code).
- **Privilege Escalation:** `sudo systemctl restart bot` ist das
  einzige verwendete Sudo-Recht — kein Wildcard, kein Shell-Zugriff.
- **DoS:** wiederholte Restart-Requests brauchen ein **Rate-Limit**
  (z.B. max. 1 Apply pro 60 s) und einen **Preflight** (siehe §15).

### 9.2 Verworfene Security-Punkte

- **Replay:** kein Kanal ohne Authentifizierung → keine Replay-Fläche.
- **MitM lokal:** kein Transport ohne Auth → keine Sniffing-Fläche.
- **Unauthorized Runtime Control:** durch bestehende ADMIN-Auth +
  CSRF abgedeckt; zusätzlich verhindert Preflight (Stufe 3) versehentliche
  Ausführung während aktiver Jobs.

### 9.3 Für B / C (nicht gewählt, aber dokumentiert)

- **Auth über Socket-Permissions** reicht strukturell nicht, wenn
  CC und Bot als derselbe User laufen — die eigentliche Autorisierung
  bleibt in der Application-Layer-Schicht.
- **Größere Angriffsfläche im Bot-Prozess** (Socket-Listener oder
  HTTP-Stack; mehr Code, mehr Parser, mehr CVEs).
- **Command-Flooding** auf dem Socket braucht Rate-Limit.
- **Stale-Socket-Handling** muss explizit getestet sein.

---

## 10. Failure Analysis

### 10.1 Für D / D+ (Restart-Pfad)

| Szenario | Verhalten |
|---|---|
| Bot nicht gestartet | `systemctl restart` startet ihn — kein Fehler |
| Bot im Restart | systemd serialisiert |
| **Laufende Jobs (Repairs, L2/L3)** | **verloren.** Subprozesse laufen weiter (systemd-unabhängig) aber verwaist, kein Ergebnis-Empfang |
| Laufende Downloads | `CancelledError`-Handler greift, `.part`-Cleanup läuft |
| Telegram-Polling-Fenster | `drop_pending_updates=True` — eingehende Nachrichten während des Fensters entfallen |
| JSON korrupt geschrieben | Bot-Fallback auf Defaults; CC sollte Preflight-Validation nutzen |
| systemctl schlägt fehl | CC liest `CalledProcessError` (RC + stderr) |
| Bot crasht beim Neustart | systemd `Restart=always` → Dauerschleife; CC müsste Health pollen |

### 10.2 Für E2 (nur Config-Write)

| Szenario | Verhalten |
|---|---|
| Bot läuft | Dateiänderung ohne Wirkung — **dokumentiert** |
| Bot nicht gestartet | gleiche Semantik |
| Race zwischen CC-Write und Bot-Start | letzter Write gewinnt |
| Korrupte JSON | Bot-Fallback auf Defaults |

### 10.3 Für B / C (nicht gewählt, aber dokumentiert)

| Szenario | Verhalten |
|---|---|
| Bot nicht gestartet | `connect()` → `FileNotFoundError`/`ConnectionRefused` |
| Stale Socket | `ECONNREFUSED` → CC kann Warnung melden |
| Bot beendet sich während Command | `read()` liefert EOF → CC erkennt Verbindungsverlust |
| Race auf Logger-State | nur wenn Handler nicht atomar ist — Design-Aufgabe |

---

## 11. State Model (aus §6 verdichtet)

```
① Persistente Konfiguration
data/module_logger_config.json
· auf Platte, von beiden Prozessen lesbar
· mit Startup-Bugfix (Stufe 0) erstmals authoritative Quelle

② Desired Runtime State
· wird durch Stufe 1 (E2) zur expliziten Entität
· Soll-Werte werden aus ① abgeleitet

③ Actual Runtime State
· Bot-RAM
· wird durch Stufe 2 (Snapshot) erstmals von außen lesbar
· Snapshot ist „Zustand nach letztem Start", ehrlich gelabelt
```

**Die zentrale Frage** — „Wie erkennt CC, ob der gewünschte Zustand
aktiv ist?" — wird beantwortet durch:
- **Stufe 1** liefert Desired State (was soll sein).
- **Stufe 2** liefert Actual State (was ist nach letztem Start).
- **Stufe 3** verbindet: Änderung → Restart → neuer Actual State.

**Ohne Stufe 3** bleibt die Frage offen — der Desired State kann vom
Actual State abweichen, und CC kann das nur durch Vergleich der beiden
Datenquellen erkennen (ehrlich, aber nicht sofort wirksam).

---

## 12. Application-Layer Boundary

Für L4 verbindlich:

**Router (`control_center/routers/logger.py`) darf NICHT direkt:**
`logging.getLogger()`, `_module_loggers`, `ModuleLoggerManager`,
`subprocess`, `socket` manipulieren.

**Der Router ruft ausschließlich Application-Layer-Funktionen auf.**
Die Runtime-Control-Grenze wird als konzeptioneller Port definiert:

```
Control Center
│
▼
Application Layer  (services/logger_admin.py erweitert)
│
▼
RuntimeLoggerPort  (konzeptionell — Name erst nach L4-Analyse)
│
├── PersistentConfigBackend   (Stufe 1)
├── SnapshotReadBackend       (Stufe 2)
└── ControlledRestartBackend  (Stufe 3)
```

**Keine unnötige Abstraktionsschicht.** Der Port existiert in L4 nur,
wenn mehr als ein Backend gebraucht wird; sonst reicht eine direkte
Funktion im Application Layer. Die Entscheidung darüber fällt in L4,
nicht hier.

Für die spätere Wiederverwendung durch Telegram und CLI (siehe L7)
gilt: dieselbe Application-Layer-Funktion, keine Telegram-spezifische
Runtime-Funktion.

```
Telegram ───────┐
│
Control Center ─┼──> Application Layer ──> Runtime Control
│
CLI ────────────┘
```

---

## 13. Vergleichsmatrix (L3.6, verdichtet)

| Kriterium | E1 | E2 | D | D+ | A | B | C |
|---|---|---|---|---|---|---|---|
| Korrektheit | 🔴 | 🔴 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |
| Konsistenz | ⚪ | 🟡 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |
| Sicherheit | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 | 🔴 |
| Authorization | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 | 🟡 |
| Isolation | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 | 🔴 |
| Fehlertoleranz | ⚪ | 🟢 | 🟡 | 🟢 | 🔴 | 🟢 | 🟢 |
| Bestätigung | ⚪ | ⚪ | 🟡 | 🟢 | 🔴 | 🟢 | 🟢 |
| Race Conditions | ⚪ | 🟡 | 🟢 | 🟢 | 🔴 | 🟢 | 🟢 |
| Restart-Verhalten | ⚪ | 🟢 | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 |
| Auditierbarkeit | 🟡 | 🟡 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |
| Wartbarkeit | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 | 🟡 | 🔴 |
| Testbarkeit | 🟢 | 🟢 | 🟡 | 🟡 | 🔴 | 🟡 | 🟡 |
| Deployment | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 | 🔴 |
| Performance | 🟢 | 🟢 | 🔴 | 🔴 | 🟢 | 🟢 | 🟢 |
| Erweiterbarkeit | 🟢 | 🟢 | 🟡 | 🟡 | 🟡 | 🟢 | 🟢 |
| Telegram reuse | ⚪ | ⚪ | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |
| CLI reuse | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |
| CC-Integration | 🟢 | 🟢 | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 |

Legende: 🟢 voll erfüllt · 🟡 teilweise · 🔴 nicht erfüllt · ⚪ nicht
anwendbar.

**Runtime-Read** (Observability) wird separat betrachtet — sie ist mit
jedem Modell kombinierbar und liefert eigenständigen Nutzen.

---

## 14. Verworfene Optionen + Begründung

### Verworfen: Option A — File-Watcher als dauerhafte Runtime-Infrastruktur

Kein Rückkanal → keine echte Bestätigung. Race-Risiko auf
`logger.handlers`-Mutation. Neuer Hintergrund-Thread im Bot. Löst das
Kernproblem nicht („hat der Bot den neuen Zustand übernommen?").

### Verworfen: Option C — Localhost-HTTP-Control-Server

Größerer Stack im Bot (neue Dependency), Token-Persistenz nötig,
Port-Kollisionen, SSRF-Fläche, `127.0.0.1` nicht automatisch sicher.
Alle Nachteile von B ohne strukturellen Vorteil.

### Verworfen in L4: jeder unnötige neue IPC-Stack

Solange kein **belegter** Live-Runtime-Write-Bedarf existiert, wird
kein dauerhafter Cross-Process-Kanal gebaut. Die Beweislast liegt beim
Bedarf, nicht bei der Technik.

### Nicht verworfen, aber deferred: Option B — Unix-Socket

Technisch die sauberste Lösung für echten Live-Runtime-Write ohne
Restart. **Deferred**, weil der reale Bedarf nicht belegt ist und der
Preis hoch ist (neuer permanenter Kanal, neuer Listener bei jedem
Bot-Start, zusätzlicher Code im Bot-Prozess).

**Re-Evaluierungs-Trigger:**
- Falls sich in der Praxis zeigt, dass Debug-Toggle-Loops häufiger
  vorkommen als durch gelegentlichen Restart vertretbar, **oder**
- falls weitere Runtime-Domänen (nicht nur Logger) einen Live-Kanal
  benötigen würden.

---

## 15. Empfohlene Zielarchitektur

**Kurzform:** E2 + Runtime Snapshot + kontrollierter Restart mit
Preflight = aktuelle Zielarchitektur für L3/L4–L6. Runtime-Write über
IPC bleibt bewusst deferred.

### Entwicklungs-Pfad (verbindlich)

```

```
Stufe 0  Startup-Bugfix
↓
Stufe 1  E2 — Persistent Configuration über CC
↓
Stufe 2  Runtime Snapshot / Observability
↓
Stufe 3  kontrollierter Apply/Restart mit Preflight
↓
Stufe 4  Unix-Socket Runtime Write   [DEFERRED, nur bei belegtem Bedarf]
```

```

Der Pfad ist bewusst inkrementell und nicht als Big-Bang-Entscheidung
formuliert: jede Stufe ist für sich testbar und liefert eigenständigen
Nutzen. Stufe 1 + 2 decken den wesentlichen administrativen Nutzen ab,
ohne einen neuen Cross-Process-Runtime-Kanal einzuführen.

### Stufe 0 — Startup-Apply korrigieren (harte Vorbedingung)

`ModuleLoggerManager._load_module_configs()` ruft nach dem Laden
`_apply_module_config()` für jedes Modul auf. Danach ist die JSON
erstmals **tatsächlich** die Basis des Runtime-Zustands nach dem
Bot-Start. Ohne diesen Fix ist jede weitere Stufe wirkungslos.

**Achtung — reale Verhaltensänderung am laufenden Bot:** Bestehende
Module, deren JSON-Level von den Code-Defaults aus `logger.py`
abweichen, laufen nach dem ersten Neustart mit dem JSON-Level. Das ist
gewollt, aber es ist eine Verhaltensänderung, die kommuniziert werden
muss (siehe §16 Offene Risiken).

### Stufe 1 — E2 Persistent Configuration

Neue Endpunkte im CC (L4):

- `GET /api/v1/admin/logger/config` — persistente Konfiguration
  (JSON-Inhalt), read-only.
- `PATCH /api/v1/admin/logger/config` — Partial-Update mit
  Pydantic-Validierung, `AccessLevel.ADMIN`, CSRF.

**Semantik eindeutig: wirksam beim nächsten Bot-Start.** Kein
Fake-Live-Versprechen.

### Stufe 2 — Runtime Snapshot / Observability

Bot schreibt beim Start (nach `_apply_module_config()`) einen Snapshot
nach `data/logger_runtime_snapshot.json`:

```json
{
  "timestamp": "2026-09-23T…",
  "root_level": "INFO",
  "effective_levels": { "CoverProcessor": "DEBUG", "NavidromeAPI": "INFO" },
  "handlers": { "CoverProcessor": ["FileHandler", "StreamHandler"] },
  "disabled": ["SomeModule"]
}
```

CC-Endpoint (L4): GET /api/v1/admin/logger/runtime-status —
read-only, ehrlich gelabelt „Zustand nach letztem Start".

Ehrlichkeitshinweis: Der Snapshot ist ein Zustand nach dem
letzten Start, nicht „Live". Das UI muss das labeln. Es ist echtes
Actual State (kein aus der JSON geratener Wert), aber eben historisch —
deshalb klar kommunizieren.

Stufe 3 — Kontrollierter Apply/Restart mit Preflight

Neuer CC-Endpoint (L5):

```
POST /api/v1/admin/logger/apply
        │
        ├── Config validieren (Pydantic-Schema)
        │
        ├── Preflight: aktive Jobs prüfen
        │       │
        │       ├── kritische Jobs aktiv → 409 restart_blocked
        │       │
        │       └── keine kritischen Jobs → weiter
        │
        ├── Config persistent speichern
        │
        └── kontrollierten Bot-Restart auslösen
                (bestehender BotRestartTrigger)
```

Zusätzlich:

· Rate-Limit (z.B. max. 1 Apply pro 60 s).
· Klarer UI-Text: „Admin-Vorgang — startet den Bot neu".
· Kein Fake-Live — die Semantik ist „Anwenden durch kontrollierten
  Neustart".

Preflight ist architektonisch wichtiger als die reale
Restart-Dauer. Ein Restart darf nicht als triviale Logger-Änderung
dargestellt werden, sondern als expliziter administrativer
Betriebsvorgang mit Preflight-Bedingung. Das verhindert den
problematischen Fall:

„Ich wollte nur CoverProcessor = DEBUG setzen und dabei wurde ein
30-Minuten-Repair abgeschossen."

Der Preflight selbst ist eine L5-Designaufgabe (welche Jobs gelten als
kritisch? welche dürfen laufen? welche müssen aktiv abgelehnt werden?).
L3 legt nur die Architektur-Anforderung fest, nicht die
Job-Klassifizierung.

Stufe 4 — Unix-Socket Runtime Write (deferred)

Nicht Teil von L4–L6. Nur bei belegtem Bedarf. Vorgesehen als eigener
Architekturentscheid zu einem späteren Zeitpunkt, mit dann
aktualisierter Security-/Failure-Analyse.

---

## 16. Offene Risiken und Unsicherheiten

· Restart-Dauer: [UNBEKANNT] — nicht gemessen. Für die
  Architektur nicht entscheidend (Preflight ist wichtiger als Dauer),
  aber für UX-Kommunikation relevant. Nachmessbar, sobald Stufe 3
  in L5 existiert.
· Realer Debug-Toggle-Bedarf: [UNBEKANNT] — nicht belegt. Wenn
  selten, bleibt Stufe 4 dauerhaft deferred. Wenn häufig, könnte
  Stufe 4 neu bewertet werden. Re-Evaluierungs-Trigger ist in §14
  dokumentiert.
· Häufigkeit aktiver Jobs während gewünschter Logger-Änderungen:
  [UNBEKANNT] — nicht gemessen. Bei hoher Häufigkeit wird Stufe 3 in
  der Praxis häufig durch den Preflight blockiert; das wäre ein Signal,
  Stufe 4 doch zu bauen.
· Startup-Bugfix ist eine reale Verhaltensänderung am laufenden
  Bot. Siehe §15 Stufe 0. Die betroffenen Module (JSON-Level ≠
  Code-Default) müssen vor dem Rollout identifiziert und kommuniziert
  werden.
· Job-Verlust-Risiko bleibt bestehen in Stufe 3. Preflight
  reduziert, aber verhindert es nicht vollständig (kleine Race-Fenster
  zwischen Preflight und Restart). Kein absolutes Sicherheitsversprechen.
· Snapshot-Aktualität in Stufe 2. Der Snapshot wird nur beim
  Bot-Start geschrieben. Wenn ein Runtime-Control-Pfad später doch
  eingeführt wird (Stufe 4), muss der Snapshot zusätzlich bei jeder
  Runtime-Änderung aktualisiert werden — sonst driftet er vom Actual
  State ab.

---

## 17. L4–L8 Abhängigkeiten

Phase Inhalt Abhängig von
L4 Stufe 0 (Startup-Bugfix) + Stufe 1 (Config-Endpunkte) dieses Dokument
L4 Stufe 2 (Snapshot-Write im Bot + Read-Endpoint im CC) Stufe 0
L5 Stufe 3 (Apply-Endpoint + Preflight + Rate-Limit) Stufe 1 + 2 + JobRegistry-Zugriff
L6 Control Center UI für Logger-Konfiguration + Snapshot + Apply L4 + L5
L7 Telegram auf Application Layer migrieren L4 + L5
L8 Parity Audit L4 + L5 + L6 + L7
Stufe 4 Unix-Socket Runtime Write eigenständige, später zu treffende Entscheidung

Testanforderungen für L4 (in L3 nur dokumentiert, nicht
implementiert):

· unauthorized runtime command
· authorized runtime command
· bot unavailable
· timeout
· stale IPC endpoint (nur relevant für Stufe 4)
· runtime state confirmation (Stufe 2 — Snapshot-Read)
· concurrent changes (Config-Write-Race)
· restart during command (Stufe 3 — Preflight-Reaktion)
· invalid logger level
· invalid module
· repeated command (Rate-Limit)
· audit log
· Telegram/API parity (L7)

---

## 18. Konkrete nächste Schritte

L3 ist eine Architecture Decision, keine Implementierung. Die
Umsetzung beginnt mit L4.

1. L3-Dokument committen (docs-only, kein Code).
2. L4-Prompt erstellen (durch Nutzer), der Stufe 0 + Stufe 1
   beschreibt.
3. Stufe 0 in L4 umsetzen: _load_module_configs() ruft
   _apply_module_config() auf. Characterization-Tests für das
   bestehende Verhalten, neue Tests für das gefixte Verhalten.
4. Stufe 1 in L4 umsetzen: Config-Read-Endpoint + Config-Write-
   Endpoint mit klarer Semantik „nächster Start".
5. Stufe 2 und 3 in L5/L6 umsetzen gemäß §17.

Kein Runtime-Control, keine IPC, kein Socket in L4. Falls L4/L5
einen Bedarf zeigen, der Stufe 4 rechtfertigt, wird L3 erneut
aufgerufen und mit den dann verfügbaren Messdaten neu bewertet.

---

## Definition of Done — L3

☑ Tatsächliches Process Model analysiert (§3)
☑ Bot Lifecycle analysiert (§3)
☑ Control Center Lifecycle analysiert (§5)
☑ Logger Lifecycle analysiert (§4)
☑ ModuleLoggerManager analysiert (§4.2, §4.3)
☑ Bestehende Restart-/Control-Infrastruktur analysiert (§3)
☑ Vorhandene IPC-Mechanismen geprüft (§3 — keine)
☑ Persistence + Reload analysiert (§8 Option A)
☑ Unix Socket analysiert (§8 Option B)
☑ Localhost HTTP analysiert (§8 Option C)
☑ Controlled Restart analysiert (§8 Option D, D+)
☑ No Runtime-Control analysiert (§8 Option E1, E2)
☑ Security Threat Model erstellt (§9)
☑ State Model definiert (§6, §11)
☑ Application-Layer Boundary definiert (§12)
☑ Telegram/CLI-Wiederverwendung berücksichtigt (§12)
☑ Failure Modes dokumentiert (§10)
☑ Vergleichsmatrix erstellt (§13)
☑ Architekturentscheidung begründet (§1, §15)
☑ Verworfene Alternativen dokumentiert (§14)
☑ L4–L8 Abhängigkeiten dokumentiert (§17)
☑ Keine Runtime-Implementierung durchgeführt
☑ Keine Telegram-Migration durchgeführt
☑ Keine UI-Änderung durchgeführt
☑ Keine bestehenden L2-Endpunkte verändert
☑ Audit-Dokument erstellt (diese Datei)

---

## Verweise

· L2-Dokument: docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md
· Architecture Overview: docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
· Phasenplan: logge.txt
· Baseline: docs/MusicBot_ENGINEERING_BASELINE_v11.md
· Findings-Index: docs/FINDINGS_INDEX.md
