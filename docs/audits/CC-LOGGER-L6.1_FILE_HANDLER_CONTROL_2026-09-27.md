# CC-LOGGER-L6.1 — File Handler Control

**Datum:** 2026-09-27
**Typ:** UI-only-Nachtrag zu CC-LOGGER-L6 (keine Backend-Änderung, kein neuer Endpoint, keine neue Page)
**Bezeichnung:** bewusst L6.1, nicht L8 — L8 bleibt laut L6 §7 für den Parity-Audit reserviert.

---

## 1. Ausgangslage (Analyse vor Implementierung)

„Logdatei aktivieren/deaktivieren" bedeutet im bestehenden Code: die **dedizierte Log-Datei eines Moduls** über das Config-Feld `file_handler` ein-/ausschalten.

- Telegram: `EnhancedLoggerMenuHandler.toggle_module()` → `ensure_module_config_entry()` + `update_logger_config({mod: {file_handler, enabled: True}})` → `ModuleLoggerManager._apply_module_config()` fügt einen `logging.FileHandler` für `LOG_DIR/<modul>.log` hinzu bzw. entfernt alle `FileHandler` (live, In-Process).
- `bot.log` (Root-Logger, `EnhancedRotatingFileHandler`) ist nicht schaltbar und davon unberührt.
- Backend für die Web-Steuerung war vollständig vorhanden: `file_handler` ist in `ALLOWED_PATCHABLE_FIELDS`, `PATCH /api/v1/admin/logger/config` (L4) persistiert, `POST /api/v1/admin/logger/apply` (L5) wendet per Bot-Neustart an, Panel 3 (L6) vergleicht `file_handler` Desired vs. Actual.
- Einzige Lücke: `logger.js` rief PATCH nirgends auf (bewusste L6-Scope-Grenze „Kein Config-PATCH-UI").

Ergebnis der Analyse: **Fall A — Backend existiert, nur UI fehlt.** Keine offene L7-Migrationslücke.

## 2. Nutzerentscheidungen

1. Nur `file_handler` in diesem Schritt (nicht `console_handler`, nicht `level`, nicht `enabled`).
2. Nur Module schaltbar, die bereits in `module_logger_config.json` stehen.
3. Keine Änderung an `ensure_module_config_entry()` — bleibt In-Process-/Telegram-exklusiv (L7-Entscheidung unverändert).
4. Bestehende `/logger`-Page erweitern, kein neuer Endpoint, keine neue Page.

## 3. Umsetzung

| Datei | Änderung |
|---|---|
| `control_center/static/pages/logger.js` | Spalte „File" in Panel 2 ist ein Schalter (`.logger-file-toggle`, `data-module`). Change-Handler per Event-Delegation auf `#logger-config-content` → `PATCH /api/v1/admin/logger/config` mit `{"modules": {"<Modul>": {"file_handler": <bool>}}}`. Danach `loadConfig()` → Panel 2 + Panel 3 (Diff) neu. `_loggerRenderAlert()` delegiert jetzt an das neue, generische `_loggerRenderAlertInto(elementId, …)`. |
| `control_center/templates/logger.html` | Panel 2: Status-Container `#logger-config-status`, Untertitel nennt Schaltbarkeit und „laufender Bot wird nicht verändert". |

Verhalten:

- **Expliziter Zielwert statt Toggle** (idempotent, HTTP-gerecht). `enabled` wird — anders als in Telegrams `toggle_module()` — **nicht** mitgesetzt (bewusste, dokumentierte Abweichung; Web hat keine Live-Runtime-Grundwahrheit, der Nutzer setzt nur die persistierte Absicht).
- **Kein Live-Control (L3):** Erfolgsmeldung sagt ausdrücklich „Gespeichert — noch nicht aktiv", wirksam erst nach „Konfiguration anwenden (Bot-Neustart)".
- Während eines Requests sind alle File-Schalter gesperrt (keine konkurrierenden Writes).
- Fehler (403 CSRF/Auth, 409 `LOGGER_CONFIG_MISSING`, 422 `LOGGER_CONFIG_UNKNOWN_MODULE`/`INVALID_TYPE`, 5xx, Netzwerk): Schalter wird zurückgesetzt, Meldung in `#logger-config-status`; bei HTTP-Fehlern Tabelle neu geladen (Abgleich mit echtem Dateistand). 401 → Login-View.

## 4. Security

- Kein neuer Endpoint, keine neue Angriffsfläche. Wiederverwendet: ADMIN-Router-Dependency, `verify_same_origin` (CSRF/Origin), Whitelist-Validierung in `validate_logger_config_patch()`, atomarer Write.
- Der Client liefert **nie einen Pfad**, nur einen Modulnamen, der gegen die bereits persistierten Module validiert wird. Der Dateipfad `LOG_DIR/<modul>.log` wird ausschließlich serverseitig im Bot-Prozess beim Start gebildet.
- `data-module`/`aria-label` werden über `_escapeHtml()` ausgegeben (Attribut-Kontext, inkl. `"`/`'`).
- PATCH hat kein Rate-Limit (nur Apply, 60 s) — für ein reines Config-Datei-Update unkritisch; unverändert gegenüber L4.

## 5. Tests

- `tests/test_control_center_logger_api.py` (+9, Abschnitt „CC-LOGGER-L6.1"): exakter UI-Body setzt nur `file_handler` (andere Felder inkl. `enabled` und anderes Modul unverändert), Idempotenz, keine Runtime-Handler-Änderung im Prozess, unbekanntes Modul → 422 ohne Datei-Änderung, Nicht-Bool → 422, fremder Origin → 403.
- `tests/test_control_center_ui.py` (+2): Template-Marker; `logger.js` nutzt `PATCH` auf `/api/v1/admin/logger/config` mit `{ file_handler: wanted }` und spricht ausschließlich die bestehenden Endpunkte `runtime-status`/`config`/`apply` an.

Regression (thematisch): `tests/test_control_center*.py tests/test_enhanced_logger_menu_handler*.py tests/test_logger*.py` → **680 passed**. Volle Suite bewusst nicht ausgeführt (CLAUDE.md §8.A) — Empfehlung an den Nutzer.

Browser-Runtime-Test: nicht durchgeführt (kein Headless-Browser, identisch zu L6). Manuelle Prüfung beim Nutzer: Schalter umlegen → grüne Meldung → Panel 3 zeigt `file_handler: … → …` → „Konfiguration anwenden".

## 6. Bewusst NICHT in L6.1

| Nicht umgesetzt | Warum |
|---|---|
| `console_handler`/`level`/`enabled` im Web | Nutzerentscheidung: nur `file_handler` |
| Schalten nicht-persistierter Module | L4/L7: kein Anlegen über HTTP, `ensure_module_config_entry()` unverändert |
| Live-Anwendung | L3: kein Cross-Process-Kanal, kein Fake-Live |
| Korrektur der Diff-Handler-Erkennung | vorbestehender L6-Defekt, siehe §7 — als separater P3-Fix nachgezogen (§8) |

## 7. Neuer Befund (vorbestehend, nicht behoben)

`logger.js::renderDiff()` erkennt eine Runtime-Log-Datei nur am exakten Typnamen `"FileHandler"` (`handlerList.indexOf("FileHandler")`). Module, die über `logger.py::setup_module_logging()` eine eigene Datei bekommen, tragen im Snapshot `EnhancedRotatingFileHandler` (Unterklasse von `FileHandler`; `_apply_module_config()` erkennt sie per `isinstance` korrekt). Panel 3 hält solche Module deshalb für „ohne Log-Datei":

- Config `file_handler=true` → falsche Abweichung `aus → an` (False Positive).
- Config `file_handler=false` → echte Abweichung wird verschluckt (False Negative).

Verifiziert am realen Stand (Snapshot 2026-09-26T21:50Z): `EnhancedMetadataProcessor` hat zur Laufzeit `EnhancedRotatingFileHandler`, die Config sagt `file_handler=false` — Panel 3 zeigt **keine** Abweichung, obwohl die Datei aktiv ist (False Negative). Ob `setup_module_logging()` den Handler nach dem Startup-Apply wieder anlegt (Reihenfolge-Frage), ist nicht Teil dieser Analyse.

Seit L6 vorhanden, durch L6.1 relevanter geworden (der Nutzer prüft die Wirkung eines Schalters über Panel 3). Eingetragen in `docs/FINDINGS_INDEX.md` als OPEN (P3); nach Nutzerfreigabe behoben, siehe §8.

## 8. Nachtrag 2026-09-27 — P3-Fix Diff-Handler-Erkennung

**Freigabe:** Nutzer („Freigabe P3-Fix").

**Reproduktion:** Neuer Test `tests/test_logger_js_diff_file_handler_detection.py` führt `logger.js` real mit node aus (Muster wie `tests/test_control_center_subpath_ui.py`, Skip ohne node) und setzt `_loggerState` direkt. Am ungefixten Stand: 4 von 5 rot (Handler-Klassifikation, False Positive, False Negative, Rotations-Handler fälschlich als „kein Console, keine Datei"); der Regressionsfall für einfachen `FileHandler` grün.

**Fix** (`control_center/static/pages/logger.js`, 2 Stellen):

- `_loggerHandlerKind()`: `/FileHandler$/` → `"file"` statt `=== "FileHandler"`. Der Snapshot enthält nur `type(h).__name__`; alle `logging.FileHandler`-Unterklassen der Stdlib und `EnhancedRotatingFileHandler` folgen dieser Namenskonvention — Pendant zur `isinstance`-Prüfung in `_apply_module_config()`. Der Datei-Zweig steht vor dem `StreamHandler`-Zweig.
- `renderDiff()`: `rtHasFile` nutzt `_loggerHandlerKind(h) === "file"` statt `indexOf("FileHandler")`.

Nicht geändert: Snapshot-Format, Backend, Panel 1 (zeigt Handler-Namen roh an).

**Tests:** gezielt 5 passed; thematisch `tests/test_control_center*.py tests/test_enhanced_logger_menu_handler*.py tests/test_logger*.py` → 685 passed. Volle Suite beim Nutzer.

**Folgebefund (neu, OPEN P3, nicht behoben):** Die jetzt korrekt angezeigte Abweichung bei `EnhancedMetadataProcessor` (`file_handler: an → aus`) lässt sich per „Konfiguration anwenden" nicht auflösen. `EnhancedMetadataProcessor.__init__` (`services/metadata/enhanced_metadata_processor.py:70`) ruft `setup_module_logging()`, das alle Handler entfernt und bedingungslos eine rotierende Datei installiert — die persistierte Config wird damit übersteuert (belegt durch den nach dem Startup geschriebenen Snapshot). Gleiches Muster in `EnhancedLoggerMenuHandler.__init__` (`EnhancedLoggerHandler`). Ein Fix wäre eine Verhaltensänderung am Logger-Core bzw. P0-Metadata-Code und braucht eine eigene Entscheidung.
