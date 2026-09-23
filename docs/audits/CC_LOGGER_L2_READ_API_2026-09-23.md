# CC-LOGGER-L2 — Logger Read API

**Datum:** 2026-09-23
**Auslöser:** `logge.txt` (Phasenplan Logger-API L1–L7), Nutzerfreigabe
für L2.
**Vorgänger:** L1-Charakterisierung (Function-Matrix, Cross-Process-
Befund), in diesem Dokument zusammengefasst.
**Status:** L2 abgeschlossen. L3 (Runtime-Control) ist ein separater,
noch nicht begonnener Architekturentscheid.

---

## 1. Ausgangszustand (L1-Analyse, aus dem Repo, nicht angenommen)

`handlers/enhanced_logger_menu_handler.py::EnhancedLoggerMenuHandler`
(1711 Zeilen) bietet dem Telegram-Bot eine breite Logger-Verwaltung.
Aufteilung nach Datenquelle:

- **Klasse A — shared filesystem** (aus CC-Prozess unverändert
  lesbar): Logdateien unter `Config.LOG_DIR`, `stat()`-Metadaten,
  Datei-Inhalt.
- **Klasse B — process-local** (nur im Bot-Prozess): `_module_loggers`
  (`logger.py`), `logging.Logger.manager.loggerDict`, `Logger.handlers`,
  `Logger.disabled`, `EnhancedLogger.stats`, `ExceptionMonitor`.
- **Klasse C — nicht implementiert**: `add_handler`/`remove_handler`/
  `add_module`/`download_log_file` sind im Telegram-Handler selbst nur
  Platzhalter ohne Funktion.

### Kritischer L1-Fund — `module_logger_config.json` ist keine
### verlässliche Runtime-Quelle

`ModuleLoggerManager._load_module_configs()` liest die JSON beim
Bot-Start, ruft aber **nicht** `_apply_module_config()` auf. Eine
Änderung der Datei beeinflusst den laufenden Bot nicht. Der einzige
Anwendungspfad ist `set_module_config()` → ausgelöst durch einen
Telegram-Button-Klick.

Folge für die API: die Datei darf in L2 nicht als "aktuelle
Logger-Konfiguration" exponiert werden — ein Read-Endpoint würde eine
Genauigkeit vortäuschen, die die Datenquelle nicht hat.

### Cross-Process-Befund

Der Bot besitzt **keinen Inbound-Runtime-Kanal**. Der einzige
vorhandene Steuerungs-Mechanismus ist
`utils/bot_restart_trigger.py` → `subprocess.run(["sudo", "systemctl",
"restart", <service>])` — ein voller Neustart, kein Skalpell. Kein
Unix-Socket, kein HTTP-Inbound, kein File-Watcher.

Konsequenz für Klasse B: **DEFERRED**. L2 baut keine IPC-Lösung.

---

## 2. Vollständige Logger-Funktion-Matrix (L1-Ergebnis)

| Telegram-Funktion | Klasse | Begründung |
|---|---|---|
| Hauptmenü | A | nur Anzeige |
| Log-Dateien-Liste | A | Filesystem |
| Log-Datei-Detail | A | Filesystem |
| Log-Datei-Statistiken | A | Filesystem — `oldest_file` = **älteste Datei nach mtime**, NICHT „älteste Logmeldung" (Logzeilen tragen im Root-Format kein Datum) |
| Cleanup-Menü (Anzeige) | A | Filesystem |
| Cleanup ausführen | A (schreibend, **nicht in L2**) | Datei-Löschung |
| Modul-Liste | B | `_module_loggers` |
| Modul-Detail | B | `_module_loggers` |
| Statistiken (Comprehensive) | B | Stats + Runtime |
| Modul-Toggle (File-Handler) | B | `Logger.handlers` |
| Modul-Level setzen | B | `Logger.level` |
| Globales Level setzen | B | Root-Logger + Modul-Logger |
| Alle aktivieren/deaktivieren | B | `Logger.disabled` |
| Handler-Reload | B | `_apply_module_config()` |
| Handler-Übersicht | B | `loggerDict` |
| Handler add/remove | C | Platzhalter |
| Modul hinzufügen | C | Platzhalter |
| Log-Datei-Download | C | Platzhalter |

---

## 3. Architekturentscheidungen L2

- **Application Layer: `services/logger_admin.py`** — Telegram-frei,
  FastAPI-frei. Ruft ausschließlich `services/logs/reader.py` auf (kein
  zweiter Parser, keine zweite Redaktions-/Filterlogik).
- **Route-Prefix `/api/v1/admin/logger`** — parallel zu `/api/v1/logs`,
  keine Migration der bestehenden Route.
- **Route-Reihenfolge** — `/files/stats` VOR `/files/{name}`
  deklariert. Kritisch (siehe Tests).
- **Read-only.** Keine Writes.
- **Keine Config-Exposition.** `module_logger_config.json` wird NICHT
  exponiert (siehe L1-Fund).
- **Auth: AccessLevel.ADMIN** auf Router-Ebene (identisch `/api/v1/logs`).
- **Kein CSRF** — reine GET-Endpunkte ohne Seiteneffekt.

---

## 4. API-Routen

| Route | Response | Datenquelle |
|---|---|---|
| `GET /api/v1/admin/logger/files` | `LogFileListResponse` | `list_log_files()` |
| `GET /api/v1/admin/logger/files/stats` | `LogFileStatsResponse` | `get_log_file_stats()` |
| `GET /api/v1/admin/logger/files/{name}` | `LogFileDetailResponse` | `get_log_file()` → `reader.read_logs()` |

Filter auf `/files/{name}`: `level`, `component`, `search`, `limit`
(Default 200, Min 1, Max 2000).

---

## 5. Klasse B — DEFERRED (`LOGGER-RUNTIME-CONTROL`)

Explizit **nicht** in L2 angeboten:

- Modul auf DEBUG/INFO/WARNING/ERROR stellen
- Modul aktivieren/deaktivieren
- Globales Log-Level ändern
- File-/Console-Handler aktivieren/deaktivieren
- Handler-Reload
- Process-local Logger-/Handler-Status
- ExceptionMonitor-Runtime-State

Begründung: prozesslokal im Bot-Prozess. Ohne Inbound-Kanal aus dem
CC-Prozess nicht erreichbar. Ein Write-Endpoint, der nur
`module_logger_config.json` verändert, würde die L1-Fund-Falle
verschärfen (JSON ändern, Bot ignoriert). Verboten nach
`logge.txt` §4/§15.

**Voraussetzung für L3** (separater Architekturentscheid):
- Persistenz der Statistiken auf Platte **UND** Reload-Trigger im
  Bot-Prozess, **ODER**
- ein Runtime-Kanal (Unix-Socket / HTTP-Inbound / gesteuerter
  Bot-Neustart), **ODER**
- eine dokumentierte Nutzer-Entscheidung, Runtime-Control endgültig zu
  streichen.

Keine dieser Varianten wird in L2 vorbereitet.

---

## 6. Klasse C — nicht implementiert

`add_handler`, `remove_handler`, `add_module`, `download_log_file`
existieren im Telegram-Handler als Platzhalter ohne Funktion. L2 baut
sie nicht neu — weder in Telegram noch in CC.

---

## 7. Security

- **Path Traversal** — Whitelist gegen `list_log_sources()` PLUS
  Containment-Check `resolve().is_relative_to(log_dir)` (identisch zum
  SEC-003-Fix in `EnhancedLoggerMenuHandler.show_log_file_detail()` und
  `reader.py`). Beide Verteidigungslinien in L2 getestet.
- **Symlink-Ausbruch** — Whitelist erfasst Symlinks nur, wenn sie auf
  `*.log*` enden; Containment-Check als zweite Linie.
- **Absolute Pfade** — fallen schon am Whitelist-Check durch.
- **Secret-Redaktion** — läuft unverändert in
  `services/logs/reader.py` vor jeder Auslieferung (ergänzt die
  P0-Regel, ersetzt sie nicht).
- **Limit-Grenzen (server-seitig, nicht verhandelbar)** — Default 200,
  Minimum 1, Maximum 2000. FastAPI lehnt Werte außerhalb mit HTTP 422
  ab (`Query(ge=1, le=2000)`, kein stilles Clamping).
  `services/logger_admin.py::get_log_file()` validiert denselben
  Bereich defensiv ein zweites Mal (`InvalidLimitError`), damit direkte
  Aufrufer (Skripte, künftige Consumer ohne HTTP-Durchlauf) ebenfalls
  nicht stillschweigend übergroße Limits durchreichen. Ein
  „Clamp auf 2000 und Erfolg melden"-Verhalten wäre irreführend — der
  Aufrufer würde eine unvollständige Antwort als vollständig
  präsentiert bekommen. Bekannter Kompromiss: `reader.py` liest die
  Datei intern vollständig in den Speicher; bei realen Dateigrößen
  unkritisch. Nicht in L2 angefasst (würde `/api/v1/logs` berühren).

---

## 8. Tests

- `tests/test_logger_admin.py` — Application-Layer (Liste, Stats,
  Get-Detail, Traversal, Symlink, Limit-Validierung).
- `tests/test_control_center_logger_api.py` — HTTP (Happy Path,
  Route-Reihenfolge, Traversal, Limit-Grenzen, Auth, Regression
  `/api/v1/logs`).

Testergebnis (2026-09-23):
- `tests/test_logger_admin.py` + `tests/test_control_center_logger_api.py`
  + `tests/test_logs_reader.py` + `tests/test_logger_menu_path_traversal.py`
  → **86 passed** in 4,19 s.
- Gesamte Control-Center-Themensuite (`pytest tests/ -k control_center`)
  → **529 passed**, 4972 deselected in 81,28 s.

---

## 9. Verbleibende Findings

- **L2-F1** (niedrig): `reader.py::read_logs()` liest die Datei via
  `read_text()` vollständig in den Speicher. Bei extrem großen
  Logdateien (>>100 MB) wäre ein streaming-Tail wünschenswert. Nicht
  in L2 angefasst.
- **L2-F2** (niedrig): `ModuleLoggerManager._load_module_configs()`
  wendet die geladene Konfiguration beim Bot-Start nicht an. Bestehendes
  Verhalten, dokumentiert, nicht durch L2 verschlimmert — aber ein
  Kandidat für L3.

---

## 10. Nächste Phase

**L3 — Runtime-Control Architecture** (separat freizugeben, noch nicht
begonnen): Entscheidung, ob ein Runtime-Kanal gebaut wird oder ob
Runtime-Control endgültig gestrichen wird. In L3 muss explizit
dokumentiert werden:

- benötigte Befehle
- Sicherheitsmodell
- erwartete Runtime-Semantik
- mögliche IPC-Varianten
- Vor-/Nachteile
- warum kein Fake-Reload implementiert wurde

Bis L3 abgeschlossen ist: keine Runtime-Logger-Änderungen, kein
`module_logger_config.json`-Exposure, keine IPC.
