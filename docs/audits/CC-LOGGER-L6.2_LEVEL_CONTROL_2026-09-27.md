# CC-LOGGER-L6.2 — Level Control

**Datum:** 2026-09-27
**Typ:** UI-only-Nachtrag zu CC-LOGGER-L6 / L6.1 (keine Backend-Änderung, kein neuer Endpoint, keine neue Page)

---

## 1. Ziel

Das persistierte Logger-Level eines Moduls ist in Panel 2 („Persistierte Konfiguration") der `/logger`-Seite neben dem L6.1-File-Schalter auswählbar. Architektur L1–L7 und L6.1 bleiben unverändert.

## 2. Analyse

- **Erlaubte Level (autoritativ):** `services/logger_admin.py::ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}` — geprüft in `validate_logger_config_patch()` (exakter String-Vergleich, kein Case-Folding, keine numerischen Werte → sonst `422 LOGGER_CONFIG_INVALID_LEVEL`).
- **Reihenfolge (Projektkonvention):** `EnhancedLoggerMenuHandler.log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]` (Telegram), aufsteigende Schwere.
- `GET /api/v1/admin/logger/config` liefert die erlaubten Level **nicht** mit. Eine Erweiterung des Response-Modells wäre eine API-Änderung und ist nicht Teil dieses Schritts → die Liste steht als Konstante `LOGGER_LEVELS` in `logger.js`; ein Test pinnt den Gleichlauf mit `ALLOWED_LOG_LEVELS` und der Reihenfolge.
- Real persistierte Level (Stand 2026-09-27): 24× INFO, 18× DEBUG — alle innerhalb der Whitelist.
- `update_logger_config()` merged by field → ein Body `{"modules": {"X": {"level": "…"}}}` ändert ausschließlich `level`.

## 3. Umsetzung

| Datei | Änderung |
|---|---|
| `control_center/static/pages/logger.js` | Spalte „Level" in Panel 2 ist ein `<select class="form-select form-select-sm">` mit genau `LOGGER_LEVELS`, aktueller Wert vorausgewählt (`data-current`). Änderung → `PATCH /api/v1/admin/logger/config` mit `{ level: wanted }`. Der PATCH-Ablauf aus L6.1 wurde in `_loggerPatchModuleConfig()` herausgezogen; File-Schalter und Level-Auswahl nutzen ihn gemeinsam (Sperre aller Controls während des Requests über `.logger-config-control`, Revert bei Fehler, Reload + Diff bei Erfolg/HTTP-Fehler). `_loggerInitFileToggles()` → `_loggerInitConfigControls()`. Veralteter Kopfkommentar („L6.2/L6.3" als L6-Teilschritte, „Apply kommt noch") bereinigt, damit „L6.2" eindeutig ist. |
| `control_center/templates/logger.html` | Untertitel Panel 2 nennt Level und File als änderbar. |

Verhalten:

- Es wird **nur `level`** gesendet — kein `enabled`, `file_handler`, `console_handler`.
- Gleicher Wert wie gespeichert → kein Request.
- Wert außerhalb `LOGGER_LEVELS` wird clientseitig nie gesendet (Revert); Backend-Validierung bleibt trotzdem autoritativ.
- Persistierter Wert außerhalb der Whitelist (z. B. handeditiert): wird als nicht auswählbare Option „<Wert> (ungueltig)" angezeigt, angeboten werden weiterhin nur die fünf erlaubten Level.
- Fehler → Auswahl springt auf den vorherigen Wert, Meldung in `#logger-config-status` (inkl. eigenem Titel für `LOGGER_CONFIG_INVALID_LEVEL`).
- Wirksam erst nach „Konfiguration anwenden (Bot-Neustart)", kein Live-Control (L3). Panel 3 zeigt die Abweichung `level: X → Y` bereits (seit L6).

## 4. Security

Unverändert gegenüber L6.1: kein neuer Endpoint, ADMIN-Dependency, `verify_same_origin` (CSRF), Whitelist-Validierung im Application Layer, atomarer Write. Werte in HTML-Attributen über `_escapeHtml()`. Kein Pfad vom Client.

## 5. Tests

- `tests/test_control_center_logger_api.py` (+17, Abschnitt „CC-LOGGER-L6.2"): alle 5 Level setzen nur `level`; `debug`/`TRACE`/`OFF`/`ALL`/`NOTSET`/`WARN`/`FATAL`/`10`/`""`/`null` → 422 `LOGGER_CONFIG_INVALID_LEVEL`, Datei unverändert; kein Runtime-Level-Wechsel; unbekanntes Modul → 422 ohne Anlegen.
- `tests/test_control_center_ui.py` (+2): `LOGGER_LEVELS` == `ALLOWED_LOG_LEVELS` (Menge, Anzahl, Reihenfolge nach Schwere, == Telegram-Reihenfolge); `{ level: wanted }` / `{ file_handler: wanted }` im JS.
- `tests/test_logger_js_config_controls.py` (neu, 8, `logger.js` real per node): gerenderte Optionen exakt, Vorauswahl, ungültiger Wert nicht auswählbar, PATCH-Body genau `{"modules": {"ModA": {"level": "DEBUG"}}}`, Revert bei 422, kein Request bei Nicht-Whitelist-Wert bzw. unverändertem Wert; L6.1-Regression (Body nur `file_handler`, Revert bei unbekanntem Modul).

Thematisch (`tests/test_control_center*.py tests/test_enhanced_logger_menu_handler*.py tests/test_logger*.py`): **712 passed**. Volle Suite beim Nutzer. Browser-Runtime-Test nicht durchgeführt (kein Headless-Browser).

## 6. Bekannte Einschränkung

Für Module, die `logger.py::setup_module_logging()` im Konstruktor aufrufen (`EnhancedMetadataProcessor`, `EnhancedLoggerHandler`), wird nicht nur `file_handler`, sondern auch das **Level** bedingungslos übersteuert (`logger.setLevel(level)` mit dem hart codierten Aufrufwert, z. B. `"DEBUG"`). Die Level-Auswahl ist für diese Module daher ebenso wirkungslos wie der L6.1-Schalter. Bestehender OPEN-Befund in `docs/FINDINGS_INDEX.md` („`setup_module_logging()` übersteuert persistierte …-Config") um das Level ergänzt, nicht behoben.

## 7. Bewusst NICHT in L6.2

| Nicht umgesetzt | Warum |
|---|---|
| `console_handler`/`enabled` im Web | nicht Teil des Auftrags |
| Level-Liste aus der API | wäre API-/Schema-Änderung |
| Globales Level | kein Persistenz-Schema (OPEN seit L7) |
| Fix `setup_module_logging()`-Übersteuerung | Logger-Core/P0-Metadata, eigene Entscheidung |
