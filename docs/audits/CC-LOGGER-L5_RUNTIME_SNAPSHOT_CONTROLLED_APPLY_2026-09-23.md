# CC-LOGGER-L5 — Runtime Snapshot + Controlled Apply/Restart

**Datum:** 2026-09-23
**Ausloeser:** `L5.txt` (Fortsetzung des Logger-Phasenplans L1–L7).
**Vorgaenger:**
- `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` (L2, gemergt #300)
- `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` (L3, gemergt #301)
- `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md` (L4, gemergt #302)
**Status:** abgeschlossen (Stufe 2 Runtime Snapshot + Stufe 3 Controlled Apply).

---

## 1. Ausgangslage

Aus L3 und L4:

- **L3** hatte festgehalten, dass es heute keine Cross-Process-Runtime-Infrastruktur gibt. Der einzige Steuerungs-Mechanismus ist der bestehende systemd-Restart (`utils/bot_restart_trigger.py`).
- **L4** hat Stufe 0 (Startup-Apply-Bugfix) und Stufe 1 (Persistent Config API, `GET/PATCH /logger/config`) geliefert. L4 war kein Runtime-Control, sondern die persistente Absicht.

L5 setzt die in L3 beschlossenen Stufen 2 und 3 um:

- **Stufe 2 — Runtime Snapshot:** der Bot schreibt beim Startup den effektiven Logger-Zustand nach `data/logger_runtime_snapshot.json`. CC kann den Snapshot lesen, mit klarer Semantik "state after last startup".
- **Stufe 3 — Controlled Apply/Restart:** `POST /logger/apply` validiert die persistierte Konfiguration, prueft Preflight, plant einen kontrollierten Bot-Neustart ueber die bestehende Infrastruktur.

**Kein IPC, kein Socket, keine neue State-Registry, keine Aenderung an L2/L4-Endpunkten.**

---

## 2. Prozessgrenzen

| Zustand | Prozess | Cross-Process sichtbar? |
|---|---|---|
| `_module_loggers` | Bot | nein (in-process) |
| `logging.Logger.manager.loggerDict` | beide, jeweils eigener | nein |
| `ActiveDownloadRegistry` | Bot | nein (in-process) |
| `JobRegistry` | CC | nein (in-process) |
| `MaintenanceModeStore` (`data/maintenance_mode.json`) | beide, persistent | ja |
| **`library_repair.lock`** (`data/library_repair.lock`) | beide, persistent | ja |
| `library_repair_runs.json` / `library_repair_journal.jsonl` | persistent | ja |
| `DownloadHistoryStore` | persistent (nur abgeschlossene) | teilweise |

**Konsequenz:** L5 prueft ehrlich gegen den Repair-Lock. Downloads und Backups sind aus dem CC-Prozess nicht sichtbar — die Luecke wird durch die dreistufige Preflight-Semantik ehrlich benannt.

---

## 3. Job-Preflight-Analyse

**Der Repair-Lock (`library_repair.lock`):**

- Atomarer Erwerb: `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` — Dateisystem-Level, cross-process-tauglich.
- Inhalt: `<pid>|<iso-timestamp>` — wird geschrieben, aber nie ausgelesen.
- Freigabe: `lock_path().unlink(missing_ok=True)` — kein PID-Check, kein Stale-Cleanup.
- Alle Nutzer mit try/finally: `repair_service.py` (2 Funktionen), `maintenance_service.py` (7 Funktionen), `genre_revalidation.py`, `genre_revalidation_runner.py`, `duplicate_runner.py`.

**Bewertung: LIMITED** — atomarer Erwerb und konsistente Nutzung, aber kein PID-Check und kein Stale-Cleanup: nach einem Crash bleibt der Lock liegen.

---

## 4. Job-Klassifizierung

| Aktivitaet | Prozess | Cross-Process-Quelle | Ehrlich pruefbar | Blockiert? |
|---|---|---|---|---|
| Repair / Doctor / L2 / L3 | Bot | `library_repair.lock` | LIMITED | ja (blocked) |
| Maintenance-Actions | Bot | `library_repair.lock` | LIMITED | ja (blocked) |
| Genre-Revalidation | Bot | `library_repair.lock` | LIMITED | ja (blocked) |
| Duplicate-Runner | Bot | `library_repair.lock` | LIMITED | ja (blocked) |
| Health-Scan | Bot | (kein Lock) | nein | nein |
| **Downloads** | Bot | `ActiveDownloadRegistry` (in-process) | nein | nein — unverifizierbar |
| **Backups** | Bot | (keine persistente Spur) | nein | nein — unverifizierbar |
| CC-Jobs | CC | `JobRegistry` | nein | irrelevant |

**Unverifizierbar:** `downloads`, `backups` (Konstante `UNVERIFIABLE_ACTIVITY_CATEGORIES`).

Der Preflight blockiert nur, wenn der Repair-Lock aktiv ist. Bei freiem Lock + existierenden unverifizierbaren Kategorien lautet der Status `unverified`, nicht `clear`.

---

## 5. Snapshot-Design

**Schreibort:** `data/logger_runtime_snapshot.json` (via `Config.DATA_DIR`).

**Schreibzeitpunkt:** am Ende von `ExtendedBot.initialize()`, nachdem alle Logger konfiguriert und alle Handler registriert sind.

**Schema:**

```json
{
  "schema_version": 1,
  "startup_id": "<uuid4 hex>",
  "runtime_applied_at": "<iso8601 UTC>",
  "root_level": "INFO",
  "effective_levels": {"CoverProcessor": "DEBUG"},
  "handlers": {"CoverProcessor": ["FileHandler", "StreamHandler"]},
  "disabled": []
}
```

**Nicht im Snapshot:** `config_hash`, `config_updated_at` (gehoeren zur Config, nicht zum Runtime-State), `bot_started_at` (lebt in systemd).

**Reflektiert:** nur `_module_loggers`-Module, `effective_levels` aus `logging.getLogger(name).level`, `handlers` aus `[type(h).__name__ ...]`, `disabled` aus `logger.disabled == True`. Keine Rekonstruktion aus der Config.

**Atomic Write:** `services/logger_admin.py::_atomic_write_json()` (aus L4).

**Fehlersemantik:** Schreib-/Sammelfehler werden geloggt, nicht propagiert — der Bot laeuft auch ohne Snapshot weiter.

---

## 6. Desired-vs-Actual-Modell

```
Desired State                    Actual State
data/                            data/
  module_logger_config.json        logger_runtime_snapshot.json
       ^                                ^
       | PATCH /logger/config           | GET /logger/runtime-status
       | (L4)                           | (L5)
   CC-Prozess                      CC-Prozess
   write only                      read only

Writer:    CC (PATCH-Endpoint)    Writer:    Bot (Startup)
Konsument: Bot (beim Start)       Konsument: CC (Runtime-Status)
```

Die beiden Dateien koennen divergieren. Der Runtime-Status-Endpoint zeigt den Actual State, nicht die Desired-Config. Kein Config-Hash im Snapshot, weil ein solcher nur durch Config-Read ermittelbar waere.


---

## 7. Apply-Ablauf

`POST /api/v1/admin/logger/apply` folgt dieser Reihenfolge:

```
POST /apply
    |
Auth (Router-Dependency, ADMIN)
    |
CSRF (verify_same_origin)
    |
Rate-Limit (LoggerApplyRateLimiter, 60s)
    |
Config validieren (persistierte Config muss lesbar + nicht leer sein)
    |
Preflight (Repair-Lock)
    |
    +-- blocked -> HTTP 409, KEINE Mutation, KEIN Restart
    |
    +-- unverified -> Restart planen, Response 200 mit unverified-Flag
    |
    +-- clear      -> (aktuell nicht erreichbar) analog unverified
    |
    v
loop.call_later(2.0, BotRestartTrigger.trigger_restart, "bot")
    |
    v
Response 200 (BEVOR der Restart tatsaechlich laeuft)
```

**Wichtige Eigenschaften:**

- Rate-Limit wird VOR der Config-Validierung konsumiert. Ein wiederholter Request mit invalider Config verbraucht also einen Slot — schuetzt gegen Flooding. (Anmerkung: bewusst konservativ; bei Bedarf verschiebbar hinter den Preflight.)
- Config-Re-Read, aber KEIN Config-Write. Der Apply-Endpoint mutiert die persistierte Konfiguration nicht — das ist Aufgabe von `PATCH /logger/config`.
- Bei `blocked` wird KEIN Timer geplant, KEIN Restart ausgeloest, KEINE Konfiguration angefasst.
- Bei `unverified` wird der Restart ausgeloest, aber die Response weist `preflight.status="unverified"` und die konkreten unverifizierbaren Kategorien aus.
- Response geht VOR dem Restart zurueck (`call_later` mit 2s Delay), identisch zum bestehenden `POST /system/restart`-Muster.

**Response-Form (Erfolg):**

```json
{
  "status": "applied",
  "message": "Konfiguration validiert, Preflight freigegeben. Bot-Neustart wird in Kuerze ausgeloest.",
  "preflight": {
    "status": "unverified",
    "checked": {"repair_lock": true},
    "active": {"repair": false},
    "unverified": ["downloads", "backups"],
    "message": "..."
  }
}
```

---

## 8. Restart-Semantik

Der Apply-Endpoint ist ein **administrativer Bot-Neustart**, keine "Logger live anwenden"-Aktion. Die persistierte Logger-Konfiguration ist der Anlass, der Restart ist der Vorgang.

**Bestehende Infrastruktur, unveraendert:**

- `utils/bot_restart_trigger.py::BotRestartTrigger.trigger_restart(service_name)` — synchroner `subprocess.run` mit `sudo systemctl restart <service>`, 15s Timeout.
- `_RESTART_SERVICE_NAME = "bot"` — fest verdrahtet, kein User-Input.
- `_PRE_RESTART_DELAY_SECONDS = 2.0` — identisch zu `admin_operations.py`, damit die HTTP-Response zugestellt wird, bevor systemd den Bot-Prozess beendet.

**Keine Aenderung an `BotRestartTrigger`.** Insbesondere wurden NICHT angefasst:

- swallowed exceptions im Trigger (dokumentiertes Finding, nicht L5-Scope)
- Restart-Trigger-Return-Value (gibt weiterhin nichts zurueck)
- systemd-Konfiguration
- sudo-Regeln

**Bekannte Einschraenkung:** der Aufrufer kann NICHT verifizieren, ob der Restart tatsaechlich erfolgreich war. Die Response bestaetigt nur, dass der Trigger geplant wurde. Ein tatsaechlicher Erfolgsnachweis waere erst durch einen spaeteren Runtime-Status-Read nach dem Neustart moeglich (siehe §11 Failure Modes).

---

## 9. Rate-Limit und Concurrency

**Ziel:** maximal 1 Apply pro 60 Sekunden. Parallele Apply-Anfragen duerfen nicht beide einen Restart ausloesen.

**Implementierung:** `services/logger_admin.py::LoggerApplyRateLimiter`

- `threading.Lock` schuetzt den Zeitstempel.
- `try_acquire()` ist atomar: prueft Fenster UND setzt Zeitstempel in einem kritischen Abschnitt.
- Zwei gleichzeitig eintreffende Aufrufe: nur einer erhaelt `(True, 0.0)`, der andere `(False, retry_after)`.
- Bei Ablehnung: HTTP `429` mit `Retry-After`-Header (Sekunden) und `detail.code="LOGGER_APPLY_RATE_LIMITED"`.

**Instanz-Ownership:** `app.state.logger_apply_limiter` (in `control_center/app.py` neben `app.state.job_registry`). Kein Modul-Level-Singleton — jeder `create_app()`-Aufruf bekommt eine frische Instanz (Test-Isolation).

**Prozesslokal.** Der Limiter ueberlebt keinen CC-Neustart. Das ist bewusst: der einzige Weg, ihn ohne neue persistente Infrastruktur sauber zu halten. Nach einem CC-Neustart kann der naechste Apply sofort passieren — das ist akzeptabel, weil ein CC-Neustart selbst schon ein administrativer Vorgang ist.

**Wichtige Design-Entscheidung — Konsumzeitpunkt:** der Limiter-Slot wird konsumiert, BEVOR der Preflight laeuft. Ein blockierter Preflight verbraucht den Slot. Vorteil: konservativer gegen DoS-Flooding. Nachteil: ein blockierter Nutzer muss 60s warten, auch wenn der Block klar war. (Anmerkung: alternativ verschiebbar hinter den Preflight — im aktuellen Design bewusst konservativ.)

**Nicht verwechseln:** das Rate-Limit ersetzt weder den Preflight noch die Single-Flight-Semantik:

- Preflight: schuetzt vor Datenverlust (laufender Repair).
- Rate-Limit: schuetzt vor DoS / versehentlichen Doppel-Klicks.
- Single-Flight: die atomare `try_acquire`-Implementierung stellt sicher, dass zwei gleichzeitige Requests nicht beide den Restart ausloesen.

---

## 10. Security

**Auth:**

- Router-Ebene: `require_min_access_level(AccessLevel.ADMIN)` — identisch zu allen anderen `/api/v1/admin/logger/*`-Routen.
- Kein UI-only-Check. Die API selbst prueft.

**CSRF:**

- `POST /logger/apply` hat `dependencies=[Depends(verify_same_origin)]`.
- Der Header-Check ergaenzt das bereits `samesite=strict`-Session-Cookie, identisch zu allen anderen schreibenden Endpunkten.

**Kein neues Secret, kein neuer Kanal:**

- Kein Token, kein Shared Secret.
- Kein Socket, kein Listener im Bot, kein HTTP-Control-Kanal.
- Kein `subprocess` im Router — Restart laeuft ueber den bestehenden `BotRestartTrigger`.
- Service-Name fest verdrahtet (`"bot"`), kein User-Input fliesst ein.

**Kein Path Traversal:**

- Snapshot-Pfad: `Config.DATA_DIR / "logger_runtime_snapshot.json"`.
- Kein Nutzer-Input, kein relatives Pfad-Segment.

**DoS-Schutz:**

- Rate-Limit (siehe §9) — schuetzt vor wiederholten Restarts.
- `blocked`-Preflight liefert `409` ohne jede Mutation — kein Ressourcenverbrauch ausser einem Lock-Check.
- Unverifizierbare Kategorien werden als solche benannt — die API verspricht keine Sicherheit, die sie nicht hat.

**Kein Fake-Live:**

- Die Response bestaetigt NICHT "Logger wurde angewendet" — sie bestaetigt "Restart wird geplant".
- Der Snapshot beschreibt NICHT den Live-Zustand — er beschreibt "state after last successful bot startup".
- Die Preflight-Antwort unterscheidet explizit zwischen `clear` und `unverified`.

**Finding (dokumentiert, nicht in L5 gefixt):** `BotRestartTrigger.trigger_restart()` schluckt intern `CalledProcessError`, `FileNotFoundError` und generische Exceptions. Ein fehlgeschlagener Restart wird also vom Apply-Endpoint als "erfolgreich geplant" gemeldet. Das ist konsistent mit der bestehenden `/system/restart`-Semantik, aber ein bekannter Monitoring-Blindspot. Als eigenes Hardening-Thema markiert (nicht L5-Scope).

**Finding (dokumentiert, in L5 gefixt):** der globale `HTTPException`-Handler in `control_center/app.py` reichte `exc.headers` nicht durch. Das ist ein bestehender Bug (nicht durch L5 eingefuehrt), der aber L5 konkret betrifft (`Retry-After` bei `429`). Fix ist eine Zeile: `headers=exc.headers if getattr(exc, "headers", None) else None` im `JSONResponse`. Kein Verhalten anderer Endpunkte aendert sich — die Header waren vorher `None`, jetzt werden sie nur dann durchgereicht, wenn eine Exception sie setzt.


---

## 11. Failure Modes

### Snapshot-Schreibfehler (Bot-Startup)

| Szenario | Verhalten |
|---|---|
| `_collect_runtime_state()` wirft | `print()`-Warnung, `return None`, Bot laeuft weiter |
| `_atomic_write_json()` wirft (Disk voll, Permission) | `print()`-Warnung, `return None`, Bot laeuft weiter |
| Snapshot-Datei existiert, aber ist korrupt | Bot-Startup unberuehrt. CC liest `status="corrupt"` |
| Snapshot-Datei fehlt | CC liest `status="missing"` |

**Wichtig:** der Snapshot ist Observability, kein Lifecycle-Bestandteil. Der Bot startet in allen Faellen vollstaendig.

### Runtime-Status-Read

| Szenario | HTTP | Body |
|---|---|---|
| Snapshot vorhanden und valide | 200 | `status="available"`, `snapshot={...}` |
| Snapshot fehlt | 200 | `status="missing"`, `snapshot=null` |
| Snapshot korrupt (kein JSON) | 200 | `status="corrupt"`, `snapshot=null` |
| Snapshot korrupt (kein Objekt) | 200 | `status="corrupt"`, `snapshot=null` |
| Snapshot unvollstaendig (Pflichtfelder fehlen) | 200 | `status="corrupt"`, `snapshot=null` |

Bewusst IMMER HTTP 200 — der Endpoint unterscheidet semantisch im Body, nicht ueber Statuscodes. Der Konsument muss die drei Zustaende lesen, nicht nur auf HTTP 200 vertrauen.

### Apply

| Szenario | HTTP | Mutation? | Restart? |
|---|---|---|---|
| Auth fehlt (401/403) | 403 | nein | nein |
| CSRF fehlt | 403 | nein | nein |
| Rate-Limit aktiv | 429 + Retry-After | nein | nein |
| Config fehlt | 409 `LOGGER_CONFIG_MISSING` | nein | nein |
| Config korrupt | 500 `LOGGER_CONFIG_CORRUPT` | nein | nein |
| Preflight `blocked` | 409 `LOGGER_APPLY_BLOCKED` | nein | nein |
| Preflight `unverified` | 200 `status="applied"` | nein (Config unveraendert) | ja (geplant) |
| Preflight `clear` | 200 `status="applied"` | nein | ja (geplant) |
| Restart-Trigger wirft | **NICHT sichtbar fuer CC** | — | Trigger-Exception wird von BotRestartTrigger geschluckt (Finding §10) |

**Wichtig:** die Config wird bei KEINEM Pfad des Apply-Endpoints mutiert. Wenn Config-Writes gewuenscht sind, laufen sie ueber `PATCH /logger/config` (L4). Der Apply-Endpoint ist read-only gegenueber der Config und write-only gegenueber systemd (via Trigger).

### Bot waehrend Restart

| Szenario | Verhalten |
|---|---|
| Restart verzoegert sich (systemd busy) | Response kommt bereits zurueck, Bot laeuft unveraendert bis systemctl greift |
| Bot im shutdown (SIGTERM) | `asyncio.CancelledError`-Pfade greifen (bestehend, unveraendert) |
| Bot restartet sauber | neuer Startup schreibt neuen Snapshot mit neuer `startup_id` |
| Bot crasht beim Startup | kein neuer Snapshot; vorheriger bleibt erhalten — CC sieht weiterhin den alten |

---

## 12. Tests

**Snapshot (`tests/test_logger_runtime_snapshot.py`, 13 Tests):**

- Datei wird mit erwarteten Pflichtfeldern geschrieben.
- `effective_levels` reflektieren den Runtime-Zustand.
- `effective_levels` reflektieren NICHT die Config (Runtime-Read-Beweis).
- `handlers` reflektieren den Runtime-Zustand.
- `disabled`-Module werden aufgelistet.
- Atomic-Write hinterlaesst keine `.tmp`-Datei.
- Schreibfehler → `None`, keine Exception.
- Read: `missing` / `available` / `corrupt` / `unvollstaendig` / `kein Fake-State`.

**Preflight + Rate-Limiter (`tests/test_logger_apply_preflight.py`, 10 Tests):**

- `blocked` bei aktivem Lock.
- `unverified` bei freiem Lock + existierenden unverifizierbaren Kategorien.
- `blocked` bei Lock-Check-Exception (fail-safe).
- `unverified != clear` (Kernvertrag).
- `clear` nur wenn keine unverifizierbaren Kategorien existieren.
- Rate-Limit: erster Acquire ok, zweiter abgelehnt, nach Fenster ok, Reset wirkt.
- **Single-Flight:** 20 parallele Threads → genau 1 Acquire erfolgreich.

**Runtime-Status HTTP (`tests/test_control_center_logger_api.py`, 5 Tests):**

- `missing` / `available` / `corrupt` / `incomplete=corrupt`.
- `state_semantics="state_after_last_successful_bot_start"` explizit gepinnt.
- Kein Feld, das Live-State suggeriert.

**Apply HTTP (`tests/test_control_center_logger_api.py`, 7 Tests):**

- `unverified` Happy Path mit strukturierter Preflight-Payload.
- Restart-Trigger wird geplant (BotRestartTrigger gemockt).
- `blocked` bei aktivem Lock → 409, kein Restart.
- `blocked` mutiert die Config-Datei NICHT (sha256-Vergleich).
- Config fehlt → 409, kein Restart.
- CSRF fehlt → 403.
- Rate-Limit → zweiter Call 429 mit `Retry-After`-Header.

**Regressionsergebnis:**

| Suite | Ergebnis |
|---|---|
| Neue L5-Suiten + Logger-Suiten | **103 passed** (7.15s) |
| `pytest -k control_center` | **552 passed**, 5040 deselected (92.57s) |

**Kein Live-Smoke-Test mit echtem Restart.** Alle Apply-Tests mocken `BotRestartTrigger.trigger_restart` — ein echter `sudo systemctl restart bot` wird in Tests NIE ausgeloest.

---

## 13. Bekannte Race Windows

Ehrlich benannte Grenzen der L5-Implementierung:

**Race 1 — Preflight vs. gleichzeitig startender Repair**

Zwischen dem Moment, in dem der Preflight `is_repair_running() == False` sieht, und dem Moment, in dem der Restart-Trigger feuert (~2 s Delay + systemd-Latenz), kann ein anderer Prozess (z. B. Telegram-Klick) einen Repair starten. Der Restart wuerde diesen Repair dann abschneiden.

**Auswirkung:** der Preflight ist kein Lock im strengen Sinn, sondern eine **Momentaufnahme**. Er verhindert den offensichtlichen Fall "Repair laeuft schon, Nutzer drueckt Apply" — nicht den seltenen Fall "Repair startet zwischen Preflight und Restart".

**Milderung:** das Repo hat keinen Weg, das ohne einen echten Advisory-Lock ueber den Apply-Zeitraum zu schliessen (was einen CC-seitigen Repair-Lock-Vorbehalt erfordern wuerde). Nicht L5-Scope.

**Race 2 — Preflight vs. gleichzeitig feuerndem anderen Apply**

Zwei CC-Prozesse (aktuell nicht moeglich) oder zwei gleichzeitige Requests an dieselbe CC-Instanz: der `LoggerApplyRateLimiter` schuetzt mit `threading.Lock`. Single-Flight ist damit sicher innerhalb einer Prozessinstanz. Ein zweiter CC-Prozess wuerde einen zweiten Limiter haben — kann aktuell nicht auftreten (ein Service, eine Instanz).

**Race 3 — Snapshot vs. gleichzeitiger Startup**

Wenn zwei Bot-Prozesse aus irgendeinem Grund parallel starten wuerden, wuerden beide `_atomic_write_json` auf dieselbe Datei aufrufen. `Path.replace` ist atomar auf POSIX, also gewinnt der letzte — kein korruptes JSON. `startup_id` ist UUID4, jede Instanz schreibt ihre eigene. Kann aktuell nicht auftreten (systemd startet einen Prozess pro Service).

**Race 4 — Snapshot-Write vs. CC-Read**

Waehrend der Bot schreibt, kann CC lesen. Die atomare `Path.replace`-Semantik sorgt dafuer, dass CC entweder die alte oder die neue Datei sieht — niemals eine halbgeschriebene. Alle CC-Read-Pfade sind damit sicher gegen diesen Race.

**Nicht-Race — Stale-Lock nach Crash**

Ein nach Bot-Crash liegengebliebener Repair-Lock ist **kein** Race, sondern ein dauerhafter Zustand. Er fuehrt zu `blocked` bis manuelle Bereinigung (`rm data/library_repair.lock`). Das ist bewusst konservativ und in §4 als LIMITED-Bewertung dokumentiert.

**Nicht-Race — Restart-Trigger-Exception**

`BotRestartTrigger.trigger_restart()` schluckt Exceptions intern. Der Apply-Endpoint sieht sie nicht. Das ist kein Race, sondern ein bewusster Blindspot (Finding §10).


---

## 14. Nicht geloeste Cross-Process-Probleme

Explizit als **ungeloest** markiert — L5 baut keine Infrastruktur, die diese Probleme aufloest.

**14.1 — Laufende Downloads aus dem CC-Prozess nicht sichtbar**

`ActiveDownloadRegistry` lebt ausschliesslich im Bot-Prozess (in-memory). Ein laufender Download ist aus dem CC-Prozess nicht feststellbar, ohne einen neuen Cross-Process-Kanal (IPC, Socket, persistente Registry im Bot) einzufuehren. L5 fuehrt keinen solchen Kanal ein. Der Preflight deklariert `downloads` daher als `unverified`.

**Auswirkung:** ein Apply waehrend eines laufenden Downloads unterbricht den Download. Der Bot-CancelledError-Handler faengt den Abbruch sauber ab, die .part-Datei wird aufgeraeumt, aber der Nutzer muss den Download neu triggern.

**14.2 — Laufende Backups aus dem CC-Prozess nicht sichtbar**

`handlers/admin/backup_handler.py` und `services/backup_admin.py::create_backup()` hinterlassen keine persistente Spur waehrend eines laufenden Backups. Die resultierende `.tar.gz` erscheint erst nach Abschluss. L5 deklariert `backups` daher als `unverified`.

**Auswirkung:** ein Apply waehrend eines laufenden Backups schneidet das Backup ab. Die angefangene `.tar.gz`-Datei bleibt liegen und muss manuell entfernt werden. Kein Datenverlust (die Quellverzeichnisse sind unberuehrt), aber ein verwundener Artefakt.

**14.3 — Stale-Lock nach Crash**

Der Repair-Lock wird durch `O_CREAT | O_EXCL` atomar erworben, aber nach einem Prozessabbruch nicht automatisch freigegeben. Ein liegengebliebener Lock verursacht dauerhaft `blocked` bis zur manuellen Bereinigung (`rm data/library_repair.lock`). L5 fixt das nicht (§B.7-Scope-Guard in L5.txt). Als separater Hardening-Bedarf dokumentiert.

**14.4 — Restart-Erfolg nicht verifizierbar**

`BotRestartTrigger.trigger_restart()` schluckt Exceptions intern. Der Apply-Endpoint kann nicht bestaetigen, ob der Restart tatsaechlich erfolgreich war. Ein tatsaechlicher Erfolgsnachweis waere erst durch einen spaeteren `GET /logger/runtime-status` nach dem Neustart moeglich (neue `startup_id`, neuer `runtime_applied_at`). Der Client muss das selbst tun. Als Finding dokumentiert, nicht in L5 gefixt.

**14.5 — Zwei Apply-Endpoints (L5 und der bestehende /system/restart)**

CC hat zwei Wege, einen Restart auszuloesen:

- `POST /api/v1/admin/system/restart` (bestehend, CC-AC-10C) — ohne Preflight, ohne Rate-Limit.
- `POST /api/v1/admin/logger/apply` (neu, L5) — mit Preflight und Rate-Limit.

Beide nutzen denselben `BotRestartTrigger`. Der bestehende Endpoint bleibt unveraendert (L5-Scope-Guard). Ein Nutzer, der `/system/restart` direkt aufruft, umgeht den Preflight. Das ist bewusst — der Endpoint hat eine andere Semantik (generischer Bot-Neustart, kein Logger-Apply). Als Finding dokumentiert.

---

## 15. L6-Abhaengigkeiten

L5 liefert die Bausteine, die L6 (Control-Center-UI) braucht:

**15.1 — Runtime-Status fuer ein "Was laeuft gerade?"-Panel**

`GET /api/v1/admin/logger/runtime-status` liefert den Snapshot. Ein L6-Panel kann damit anzeigen:

- Root-Level
- Effektive Modul-Level (sortierbar, filterbar)
- Aktive Handler pro Modul
- Deaktivierte Module
- Wann der letzte erfolgreiche Startup stattfand (`runtime_applied_at`)

**Wichtig fuer L6:** der Status ist "Zustand nach letztem Start", nicht Live. Das UI muss das labeln — sonst suggeriert es eine Live-Sicht, die L5 nicht liefert.

**15.2 — Desired-vs-Actual fuer ein Config-Sicht-Panel**

L4 liefert `GET /api/v1/admin/logger/config` (Desired). L5 liefert `GET /api/v1/admin/logger/runtime-status` (Actual). L6 kann beide nebeneinander darstellen und Diffs hervorheben — z. B. "Modul X hat Desired=DEBUG, Actual=INFO, kein Restart seit letzter Aenderung".

Das ist der wertvollste L6-Use-Case dieser Kombination.

**15.3 — Apply-Button mit Preflight-Anzeige**

`POST /api/v1/admin/logger/apply` liefert eine strukturierte Preflight-Payload. L6 kann daraus ableiten:

- Bei `blocked`: Button deaktivieren, Grund anzeigen, ggf. Link zum Repair-Panel.
- Bei `unverified`: Button aktiv mit Warnung ("Nicht pruefbare Aktivitaeten koennten unterbrochen werden: downloads, backups").
- Bei `clear`: Button normal aktiv. (Aktuell nicht erreichbar — UI sollte diesen Fall dennoch korrekt behandeln, falls UNVERIFIABLE_ACTIVITY_CATEGORIES spaeter leer wird.)

**15.4 — Rate-Limit-Feedback**

Der `Retry-After`-Header (HTTP 429) erlaubt L6, einen Countdown anzuzeigen. Nicht zwingend, aber machbar ohne zusaetzliche API.

**15.5 — Kein zusaetzlicher API-Bedarf aus L6-Sicht**

L5 liefert bereits alle benoetigten Endpunkte. L6 ist reine UI-Arbeit — kein neuer Application-Layer-Bedarf.

---

## 16. Definition of Done — Abgleich

Aus `L5.txt` §"Definition of Done":

| Punkt | Status |
|---|---|
| Runtime Snapshot implementiert | erledigt |
| Snapshot repraesentiert tatsaechlichen Runtime-State | erledigt (Runtime-Read aus `logging.getLogger`) |
| Snapshot atomar geschrieben | erledigt (`_atomic_write_json`) |
| Snapshot-Fehler stoppen Bot nicht | erledigt (`return None`, kein Raise) |
| Runtime Status API implementiert | erledigt |
| Desired/Actual sauber getrennt | erledigt (zwei Dateien, kein Config-Read im Snapshot) |
| Job-Preflight auf reale Datenquelle gestuetzt | erledigt (Repair-Lock) |
| JobRegistry nicht faelschlich als Bot-Statusquelle verwendet | erledigt (nicht importiert, nicht genutzt) |
| Kritische Jobs explizit klassifiziert | erledigt (Matrix §4) |
| Apply Endpoint implementiert | erledigt |
| Config vor Apply validiert | erledigt (Re-Read vor Preflight) |
| Blockierter Preflight persistiert keine Config | erledigt (Apply schreibt keine Config) |
| Kontrollierter Restart ueber bestehende Infrastruktur | erledigt (`BotRestartTrigger`, unveraendert) |
| Rate-Limit | erledigt (60s, `LoggerApplyRateLimiter`) |
| Concurrent Apply geschuetzt | erledigt (`threading.Lock` im Limiter) |
| Auth | erledigt (Router-Dependency ADMIN) |
| CSRF | erledigt (`verify_same_origin`) |
| Restart-/Config-Fehler behandelt | erledigt (`blocked`/`LOGGER_CONFIG_MISSING`/`LOGGER_CONFIG_CORRUPT`) |
| L2/L4 Regressionstests bestanden | erledigt (552 passed `-k control_center`) |
| Audit-Dokument erstellt | diese Datei |
| `git diff --check` sauber | offen (Phase E) |
| Keine UI-Aenderung | erledigt |
| Keine Telegram-Migration | erledigt |
| Kein IPC | erledigt |
| Kein automatischer Commit/Push | erledigt |

---

## 17. Ausblick — Uebergang zu L6

**L5 ist abgeschlossen.** Die Logger-Phasen L1–L5 liefern:

- L1/L2: Read-API fuer Log-Dateien.
- L3: Architecture Decision (Runtime-Control-Pfad).
- L4: Persistent Config API + Startup-Apply-Bugfix.
- L5: Runtime Snapshot (Observability) + Controlled Apply/Restart mit Preflight.

**Naechste Phase — L6:** Control-Center-UI fuer Logger-Verwaltung. Vier Bausteine (§15):

1. Runtime-Status-Panel (read-only, Snapshot-Anzeige).
2. Desired-vs-Actual-Diff-Panel (Config vs. Snapshot).
3. Apply-Button mit Preflight-Anzeige (blocked/unverified/clear).
4. Rate-Limit-Feedback (`Retry-After`-Countdown).

**Kein neuer Application-Layer-Bedarf fuer L6.** Alle Endpunkte existieren.

**Nicht Teil von L6** (bleiben fuer spaetere Phasen):

- L7: Telegram-Migration auf die Application Layer.
- L8: Parity Audit.
- Hardening-Themen (nicht in L5-Scope): Stale-Lock-Cleanup, Restart-Erfolgsverifikation, Backup-/Download-Visibility per IPC.

**Re-Evaluierungs-Trigger fuer Stufe 4 (Unix-Socket):** falls der `unverified`-Status in der Praxis zu haeufig auftritt (z. B. weil laufende Downloads tatsaechlich regelmaessig abgebrochen werden und das schmerzt), kann L3 mit den dann verfuegbaren Messdaten neu bewertet werden. Das ist explizit nicht Teil von L5/L6.

---

## Verweise

- L2-Dokument: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`
- L3-Dokument: `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`
- L4-Dokument: `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`
- Architecture-Overview: `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`
- Phasenplan: `L5.txt`
- Baseline: `docs/MusicBot_ENGINEERING_BASELINE_v11.md`
- Findings-Index: `docs/FINDINGS_INDEX.md`
