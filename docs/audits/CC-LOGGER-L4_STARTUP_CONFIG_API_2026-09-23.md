# CC-LOGGER-L4 — Startup Apply + Persistent Logger Configuration

**Datum:** 2026-09-23
**Auslöser:** `L4.txt` (Fortsetzung des Logger-Phasenplans L1–L7).
**Vorgänger:**
- `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` (L2, gemergt #300)
- `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`
  (L3, gemergt #301) — verbindliche Architekturentscheidung.
**Status:** abgeschlossen (Stufe 0 + Stufe 1).

---

## 1. Ausgangslage

L3 hatte zwei zusammenhängende Befunde festgehalten:

1. **Es existiert heute keine Cross-Process-Runtime-Infrastruktur** —
   kein IPC-Kanal, kein Socket, kein File-Watcher, kein Reload-Trigger.
2. **Ein bestehender Architektur-Bug:**
   `ModuleLoggerManager._load_module_configs()` liest die persistente
   Konfiguration beim Bot-Start, ruft aber `_apply_module_config()`
   **nicht** auf. Die persistierte JSON ist damit keine
   Runtime-Wahrheit — nach einem Neustart galten die Code-Defaults aus
   `logger.py`, nicht die Werte aus der Datei.

L3 hat daraus einen inkrementellen Pfad für L4–L6 abgeleitet
(Stufe 0 → Stufe 1 → Stufe 2 → Stufe 3). **L4 setzt ausschließlich
Stufe 0 und Stufe 1 um.** Runtime-Snapshot (Stufe 2), kontrollierter
Restart (Stufe 3) und Unix-Socket (Stufe 4) sind nicht Teil dieses
Slices.

---

## 2. Startup-Bug — Ursache

Der relevante Code in
`handlers/enhanced_logger_menu_handler.py::ModuleLoggerManager`:

```python
def _load_module_configs(self):
    if self.config_file.exists():
        with open(self.config_file, "r", encoding="utf-8") as f:
            self.module_configs = json.load(f)
    else:
        self.module_configs = { ...defaults... }
        self._save_module_configs()
    # ← hier fehlte der Aufruf von _apply_module_config()
```

`self.module_configs` wurde befüllt, aber **kein** Aufruf von
`_apply_module_config()` folgte. Der einzige Pfad, über den die
Konfiguration tatsächlich auf die Logger angewendet wurde, war
`set_module_config()` (ausgelöst durch einen Telegram-Klick auf einen
Logger-Button).

Konsequenz: persistierte Level/Handler waren für den laufenden Prozess
wirkungslos. `Config.LOG_LEVEL` wurde dagegen separat von
`setup_enhanced_logging()` auf den Root-Logger angewendet — das ist
kein Modul-Eintrag und von diesem Bug nicht betroffen.

---

## 3. Implementierter Fix (Stufe 0)

In `_load_module_configs()` direkt nach dem erfolgreichen Laden (bzw.
Generieren) der Konfiguration:

```python
for module_name in self.module_configs:
    self._apply_module_config(module_name)
```

Bewusste Design-Entscheidungen:

- **Der Loop liegt INNERHALB des bestehenden `try`-Blocks.**
  Einzelne Modul-Fehler fängt `_apply_module_config()` bereits intern
  ab; ein problematisches Modul kann den Loop daher nicht sprengen.
  Fehler, die außerhalb dieses Moduls auftreten, landen weiterhin im
  bestehenden `except Exception`-Zweig.
- **Kein zweiter Apply-Pfad.** `set_module_config()` bleibt unverändert
  der Ort, an dem ab dann Änderungen aus dem Telegram-Menü angewendet
  werden.
- **Keine Änderung an `_apply_module_config()` selbst.** Der Fix
  korrigiert ausschließlich den Aufrufpfad.

---

## 4. Verhaltensänderung

**Das ist eine bewusste Verhaltensänderung.** Ab dem ersten Neustart
nach dem Fix werden die persistierten Werte tatsächlich angewendet.

**Quantifizierung der Nebenwirkung** (gegen die echte
`data/module_logger_config.json` zum Zeitpunkt dieses PRs):

| Größe | Wert |
|---|---|
| Module in der Konfiguration | 40 |
| davon mit `file_handler=true` | 40 |
| davon mit `console_handler=true` | 40 |
| davon mit `level=DEBUG` | 18 |

**Konkrete Folge:**

- **40 neue Log-Dateien** in `Config.LOG_DIR` (je `"<modulname>.log"`).
- **18 Module** schreiben ab dann tatsächlich auf DEBUG-Level.

Das ist nicht rückgängig zu machen, ohne die JSON zu ändern — gewollt,
aber explizit im Audit festgehalten. Falls die Log-Flut zu groß wird,
ist die Daten-Bereinigung ein separater, eigener Vorgang (nicht Teil
von L4).

---

## 5. Config-Schema

Die persistierte Konfiguration bleibt strukturell unverändert:

```json
{
  "<module_name>": {
    "enabled": true,
    "level": "INFO",
    "file_handler": true,
    "console_handler": true,
    "custom_format": null
  }
}
```

**Bewusst unverändert, um Rückwärtskompatibilität zu wahren.** Kein
neues Schema, keine Schemaerweiterung.

Nicht Teil der persistenten Konfiguration:

- **Globales Root-Log-Level.** Liegt in `Config.LOG_LEVEL` und wird
  ausschließlich von `setup_enhanced_logging()` auf den Root-Logger
  angewendet. Es gibt keinen Modul-Eintrag dafür. Eine globale
  Level-Änderung über die Config-API wäre eine echte Schemaerweiterung
  (z.B. `{"global": {...}, "modules": {...}}`) und nicht Teil von L4.

---

## 6. Application Layer

Neue Funktionen in `services/logger_admin.py` (Erweiterung aus L2,
kein neues Modul):

| Funktion | Zweck |
|---|---|
| `read_logger_config(config)` | liest die JSON, mappt auf dict |
| `validate_logger_config_patch(patch, existing_modules)` | strikte Validierung |
| `update_logger_config(config, patch)` | Merge + atomarer Write |
| `LoggerConfigError(message, code=...)` | Fehlerklasse mit stabilem `code` |

**Pfad-Konvention:** `Config.DATA_DIR / "module_logger_config.json"` —
identisch zu den bestehenden App-Layern (`services/user_data.py`,
`services/backup_admin.py`). Der `ModuleLoggerManager` behält seinen
relativen Pfad `Path("data/module_logger_config.json")`. **Die
Divergenz ist bewusst und wird nicht in L4 aufgelöst** (wäre ein
eigener Refactor-Scope). Solange `Config.DATA_DIR` == `<repo>/data`
ist (Standard), zeigen beide auf dieselbe Datei.

**Atomares Schreiben:** `_atomic_write_json()` schreibt über
`.tmp`-Sibling + `Path.replace()`. Der bestehende
`ModuleLoggerManager._save_module_configs()` schreibt weiterhin direkt
(nicht-atomar) — wird in L4 nicht angefasst, siehe §9.

**Was der Application Layer nicht tut:**

- Keine Telegram-Abhängigkeit.
- Keine FastAPI-Abhängigkeit.
- Keine Manipulation von `logging.getLogger()`, `_module_loggers`,
  `subprocess`, `socket`.

---

## 7. GET API

```
GET /api/v1/admin/logger/config
```

- **Auth:** `AccessLevel.ADMIN` (identisch zum L2-Router-Level).
- **Datenquelle:** `services/logger_admin.py::read_logger_config()`
  (ausschließlich die persistente JSON).
- **Response-Schema:** `control_center/schemas/logger.py::LoggerConfigResponse`
  mit `modules` (dict) + `total`.
- **Fehlende Datei:** liefert `{"modules": {}, "total": 0}` — kein
  Fehler.
- **Korrupte Datei / Nicht-Objekt:** HTTP 500 mit
  `code="LOGGER_CONFIG_CORRUPT"` — kein Fake-Empty-Response, sondern
  ehrlicher Fehler.
- **Semantik-Doku im Docstring:** die Antwort ist der persistierte
  **Desired State**, **nicht** der Actual Runtime State des Bots.

**Wichtiger Vertrag:** GET führt keine Runtime-Änderung aus. Auch wenn
die Antwort Werte zeigt, die vom laufenden Bot abweichen — das ist
beabsichtigt und wird im Response/UI/Client als „persistierte Absicht"
kommuniziert.

---

## 8. PATCH API

```
PATCH /api/v1/admin/logger/config
```

- **Auth:** `AccessLevel.ADMIN` (Router-Level).
- **CSRF:** `verify_same_origin()` als Route-Dependency (identisches
  Muster zu allen anderen schreibenden Endpunkten in CC).
- **Request-Body:** `{"modules": {"<module>": {<partial fields>}}}`.
  Top-Level strikt (nur `modules` erlaubt, `extra="forbid"`).
- **Response:** `LoggerConfigPatchResponse` mit
  `success=True`, explizitem `message`-Text („gespeichert und beim
  nächsten Bot-Start wirksam. Der laufende Bot-Prozess wurde NICHT
  verändert."), `modules_updated` (Liste der tatsächlich geänderten
  Modulnamen) und `total` (Gesamtzahl nach dem Patch).

### PATCH-Semantik

**Merge-by-module, merge-by-field.**

- Nur die im Body genannten Module werden angefasst.
- Innerhalb eines Moduls nur die genannten Felder.
- Andere Felder bleiben unverändert.

### Validierungsregeln (strikt)

| Regel | Fehler-Code | HTTP |
|---|---|---|
| Keine persistente Config vorhanden | `LOGGER_CONFIG_MISSING` | 409 |
| Top-Level-Body nicht `{"modules": {...}}` | Pydantic-Validation | 422 |
| Modul nicht in der Config | `LOGGER_CONFIG_UNKNOWN_MODULE` | 422 |
| Modul-Body leer | `LOGGER_CONFIG_PATCH_INVALID` | 422 |
| Feld nicht in `{enabled, level, file_handler, console_handler}` | `LOGGER_CONFIG_UNKNOWN_FIELD` | 422 |
| `level` nicht in `{DEBUG, INFO, WARNING, ERROR, CRITICAL}` | `LOGGER_CONFIG_INVALID_LEVEL` | 422 |
| `enabled`/`file_handler`/`console_handler` nicht bool | `LOGGER_CONFIG_INVALID_TYPE` | 422 |
| JSON korrupt | `LOGGER_CONFIG_CORRUPT` | 500 |
| Schreiben fehlgeschlagen | `LOGGER_CONFIG_WRITE_FAILED` | 500 |

**Kein stilles Erweitern des Schemas.** Neue Module können über diese
API **nicht** angelegt werden — das bräuchte eine eigene Diskussion
(Default-Level? Pflichtfelder?) und ist nicht Teil von L4.

`custom_format` ist bewusst **nicht patchbar**, weil es nirgends im
Code ausgewertet wird — ein Write würde eine Wirkung vortäuschen, die
nicht existiert.

### Garantie „Datei bei invaliden Requests unverändert"

Die Validierung läuft **vor** dem Schreiben. Bei jedem Validierungs-
fehler wird die Datei nicht angefasst. Zwei Tests pinnen den sha256
der Datei vor und nach einem invaliden Request — siehe §10.

---

## 9. Security

- **Auth:** bestehende `AccessLevel.ADMIN`-Schicht, keine parallele
  Architektur.
- **CSRF:** `verify_same_origin()` (Route-Dependency), identisches
  Muster zu allen anderen schreibenden Endpunkten.
- **Kein Nutzer-Input für Pfade.** `_resolve_config_path()` löst über
  `Config.DATA_DIR` auf; Path Traversal ist strukturell ausgeschlossen.
- **Kein neues Secret.** Kein Token, kein Shared Secret.
- **Kein `subprocess`.** Kein Bot-Restart, kein Signal, kein Socket.
- **Keine Datei-I/O im Router.** Alle File-Operationen laufen über den
  Application Layer.
- **Keine Runtime-Manipulation.** Der laufende Bot-Prozess wird nicht
  beeinflusst. Zwei Tests pinnen das (App-Layer-Level und HTTP-Level).
- **Atomares Schreiben.** `.tmp` + `replace()`. Ein abgebrochener
  Write hinterlässt keine halb-fertige Konfiguration.

**Bestehendes Verhalten unverändert:**

- `ModuleLoggerManager._save_module_configs()` schreibt weiterhin
  nicht-atomar. Nicht in L4 gefixt (wäre ein Modul-lokaler Refactor,
  außerhalb des Scopes).
- `_module_loggers`/`logging.Logger.manager.loggerDict` werden vom
  Application Layer nicht angefasst.

---

## 10. Tests

### 10.1 Stufe 0 — Startup Apply

`tests/test_module_logger_startup_apply.py` (12 Tests):

- Level wird angewendet (DEBUG, INFO, WARNING).
- Ungültiger Level → Fallback auf INFO (bestehendes Verhalten).
- FileHandler wird angehängt, wenn `file_handler=true` (bzw. nicht,
  wenn `false`).
- ConsoleHandler analog.
- Modul mit `enabled=false` → `logger.disabled=True`.
- Mehrere Module gleichzeitig.
- Fehlerhaftes Modul-Body (unvollständige Keys) blockiert andere
  Module nicht.
- Idempotenz: erneuter Init verdoppelt FileHandler nicht.
- Fehlende Datei → Default-Config wird geschrieben UND angewendet.
- Leere JSON, korrupte JSON: Manager bleibt konstruierbar.

**Zusätzlich:** Die Characterization-Tests aus Phase B wurden auf das
Post-Fix-Verhalten invertiert (vorher wurde das Fehlen der Anwendung
gepinnt).

### 10.2 Stufe 1 — Persistent Config

`tests/test_logger_config_service.py` (35 Tests, App-Layer):

- Lesen: fehlende Datei, valide Config, korrupte JSON, Nicht-Objekt.
- Validierung: unbekanntes Modul, unbekanntes Feld, `custom_format`
  wird abgelehnt, ungültige Levels, alle Whitelist-Levels akzeptiert,
  Nicht-Bool für Handler-Felder, leerer Modul-Body, Nicht-Dict-Patch.
- Update: fehlende Datei → Fehler, Einzelfeld-Merge, Multi-Modul,
  unveränderte Module bleiben, atomarer Write (kein `.tmp`),
  Persistenz-Roundtrip, invalid Patch → Datei unverändert (sha256),
  unknown module → Datei unverändert (sha256).

`tests/test_control_center_logger_api.py` (HTTP, 22 Tests in diesem
Slice zusätzlich zu den bestehenden L2-Tests):

- GET liefert die Module + `total`.
- GET führt keine Runtime-Änderung aus.
- PATCH merged und persistiert (ModA geändert, ModB unverändert).
- PATCH lehnt unbekanntes Modul / invaliden Level / unbekanntes Feld
  / Extra-Top-Level-Key mit 422 ab.
- PATCH verlangt CSRF-Origin (403 ohne).
- PATCH bei fehlender Datei → 409.
- PATCH ändert Datei nicht bei invalidem Request (sha256).
- PATCH führt keine Runtime-Änderung aus (Logger-Level unverändert).

### 10.3 Regressionsergebnis

| Suite | Ergebnis |
|---|---|
| Logger-Suiten + L4-Tests | **131 passed** |
| `pytest -k control_center` | **540 passed** |
| `pytest -k "logger or logging or enhanced_logger"` | **168 passed** |

0 Failures, 0 Regressionen.

---

## 11. Bekannte Einschränkungen

- **Pfad-Divergenz** zwischen `services/logger_admin.py`
  (`Config.DATA_DIR`) und `ModuleLoggerManager`
  (`Path("data/module_logger_config.json")`). In Produktion identisch,
  in Tests isolierbar. Bewusst nicht in L4 aufgelöst.
- **`ModuleLoggerManager._save_module_configs()` bleibt nicht-atomar.**
  Nur die neue App-Layer-Funktion `update_logger_config()` schreibt
  atomar. Ein paralleler Telegram-Klick und ein CC-PATCH können
  theoretisch kollidieren; das ist ein vorbestehendes Risiko.
- **Konfiguration wird nur beim Bot-Start angewendet.** Kein Reload im
  laufenden Prozess — genau die L3-Entscheidung. Ein CC-PATCH ohne
  Bot-Neustart hat keinen Runtime-Effekt; das ist im API-Response-Text
  explizit benannt.
- **`Config.LOG_LEVEL`** (globales Root-Level) ist nicht Teil dieser
  API.

---

## 12. Bewusst nicht implementierte Runtime-Control

Explizit **nicht** in L4:

- **Kein** Runtime-Snapshot (`data/logger_runtime_snapshot.json`).
- **Kein** `GET /api/v1/admin/logger/runtime-status`.
- **Kein** `POST /api/v1/admin/logger/apply`.
- **Kein** Bot-Restart-Trigger.
- **Keine** IPC-Infrastruktur (kein Socket, kein HTTP-Listener,
  kein File-Watcher).
- **Keine** Preflight-/Rate-Limit-Logik.
- **Keine** Control-Center-UI für Logger.
- **Keine** Telegram-Migration.

Diese Punkte gehören zu L5/L6/L7 (siehe L3-Entscheidung, §17).

---

## 13. Was L4 ist — und was nicht

**Klarstellung, damit spätere Phasen und Reviews nicht in die Falle
laufen:**

| L4 ist | L4 ist NICHT |
|---|---|
| Persistent Desired State | Runtime Control |
| Startup-Apply-Fix | Runtime Snapshot |
| Persistent Config API | Restart |
| | IPC |
| | Live-Wirkung im laufenden Bot-Prozess |

Die Config-API liefert eine ehrliche Semantik: **„gespeichert, wirksam
beim nächsten Bot-Start"**. Die API behauptet nirgends eine Anwendung
im laufenden Prozess.

---

## 14. Übergang zu L5

L4 hat zwei Bausteine geliefert:

1. **Startup-Apply** — persistierte Config wird beim Bot-Start
   tatsächlich angewendet.
2. **Persistent-Config-API** — CC kann die persistierte Config lesen
   und ändern, mit ehrlicher „nächster Start"-Semantik.

Der nächste Schritt gemäß L3-Entscheidung:

- **Stufe 2 (L5): Runtime Snapshot.**
  - Bot schreibt nach `_apply_module_config()` einen Snapshot des
    effektiven Runtime-Zustands nach
    `data/logger_runtime_snapshot.json`.
  - CC bekommt `GET /api/v1/admin/logger/runtime-status` (read-only,
    ehrlich gelabelt als „Zustand nach letztem Start").
  - Damit lässt sich erstmals Desired (Config) vs. Actual (Snapshot)
    vergleichen — ohne IPC, ohne Socket.

- **Stufe 3 (L5): Kontrollierter Apply/Restart mit Preflight.**
  - `POST /api/v1/admin/logger/apply` — Config validieren, Preflight
    auf aktive Jobs, Config speichern, Restart auslösen.
  - Rate-Limit (z.B. 1 pro 60 s).

**L4 ist nicht die Runtime-Control.** Es ist die Grundlage dafür —
zusammen mit L3 hat es die Voraussetzungen geschaffen, dass ein
späteres L5 mit ehrlicher Semantik bauen kann.

