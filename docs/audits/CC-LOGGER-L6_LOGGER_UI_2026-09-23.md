# CC-LOGGER-L6 — Logger-Verwaltungs-UI

**Datum:** 2026-09-23
**Ausloeser:** L6-Spezifikation (Analyse freigegeben).
**Vorgaenger:** L2 (#300), L3 (#301), L4 (#302), L5 (#303)
**Status:** abgeschlossen (UI-only).

---

## 1. Ausgangslage

L2-L5 lieferten die komplette Backend-Infrastruktur fuer die Logger-Verwaltung:

- **L2**: Log-Datei-Read-API unter `/api/v1/admin/logger/files`.
- **L4**: persistierte Konfiguration (`GET/PATCH /api/v1/admin/logger/config`).
- **L5**: Runtime-Snapshot (`GET /runtime-status`) + Controlled Apply/Restart (`POST /apply`).

Alle Endpunkte waren bereits ADMIN-geschuetzt und boten strukturierte Response-Schemas. Was fehlte: eine UI, die sie einem Menschen zugaenglich macht.

L6 ist reine Frontend-Arbeit auf bestehenden Endpunkten — **keine neue API, keine Backend-Aenderung, keine neue State-Infrastruktur.**

---

## 2. Verortung

**Eigene Seite `/logger`, Sidebar-Kategorie SYSTEM, direkt unter Logs.**

Begruendung:

- Nicht `/logs` (reiner Diagnose-Viewer, andere Semantik).
- Nicht `/admin` (buendelt bereits Nutzer/Backups/Maintenance).
- Eigenstaendiger Bereich mit vier thematischen Panels — eigene Seite folgt der etablierten Konvention (siehe `/navidrome`, `/statistics`, `/admin`).

**Dateien (neu):**

- `control_center/templates/logger.html`
- `control_center/static/pages/logger.js`

**Dateien (geaendert):**

- `control_center/routers/ui.py` — neue `@router.get('/logger')`-Route.
- `control_center/templates/_base.html` — neuer Sidebar-Eintrag.
- `tests/test_control_center_ui.py` — 6 neue Tests.

---

## 3. Panels

Vier Panels untereinander (Stack-Pattern analog `health.html`/`statistics.html`, kein Tab-Muster).

### Panel 1 — Runtime-Status

**Daten:** `GET /api/v1/admin/logger/runtime-status`

**KPI-Header (3 Kacheln):** Root-Level, Modul-Anzahl, letzter Startup (relativ formatiert via `_loggerTimeAgo`).

**Body:** Tabelle mit Modul / Level / Handler / Status.

**Zustandsbehandlung:**

- `available` → KPI + Tabelle.
- `missing` → Empty-Note "Noch kein Runtime-Snapshot vorhanden. Er wird beim naechsten erfolgreichen Bot-Start geschrieben."
- `corrupt` → Alert-Warning mit `message` aus der Response.

**Klare Semantik:** "Zustand nach letztem Bot-Start" — nirgends Live-State suggeriert. Die Response traegt `state_semantics="state_after_last_successful_bot_start"` aus dem Backend; das UI zeigt es im Untertitel.

### Panel 2 — Persistierte Konfiguration

**Daten:** `GET /api/v1/admin/logger/config`

**Body:** Tabelle mit Modul / Level / File-Handler / Console-Handler / enabled-Status.

**Semantik:** "Wirksam beim naechsten Bot-Start" — im Panel-Untertitel und im Body-Header.

**Keine Editier-Felder.** Der PATCH-Endpoint aus L4 wird in L6 bewusst nicht als Formular exponiert (Scope-Grenze, siehe §7).

### Panel 3 — Desired vs. Actual

**Daten:** berechnet aus State (Panel 1 + Panel 2), kein neuer API-Call.

**Logik:** Pro Modul Vergleich von `effective_levels` (actual) vs. `modules[name].level` (desired), plus Handler-Flags und enabled-Status.

**Sonderfaelle:**

- Snapshot `missing`/`corrupt` → Hinweis "Kein Vergleich moeglich" statt Fake-Diff.
- Modul nur im Runtime-Snapshot → "Keine persistierte Konfiguration (Code-Default aktiv)".
- Modul nur in der Config → "Nicht im Runtime-Snapshot (Modul wird vom Bot nicht verwendet)".
- Keine Abweichungen → `.empty-note-ok` "Persistierte Konfiguration und Runtime-Zustand sind identisch."

### Panel 4 — Apply / Controlled Restart

**Daten:** `POST /api/v1/admin/logger/apply` (mit CSRF-Header `X-Requested-With`).

**UI:**

- Klarer Text: "**Administrativer Vorgang:** startet den Bot neu. Die persistierte Logger-Konfiguration wird beim Neustart angewendet."
- Button `btn-outline-danger` mit `window.confirm()`-Dialog.
- Button initial `disabled`, aktiviert sich nach Config-Load.

**Antwortbehandlung (einziger API-Call, kein separater Preflight-Schritt):**

| HTTP | Fall | Darstellung |
|---|---|---|
| 200 | preflight=`unverified` | Gelber Alert mit "Restart wurde geplant — mit Vorbehalt" + Liste der unverifizierbaren Kategorien |
| 200 | preflight=`clear` | Gruener Alert |
| 409 | `LOGGER_APPLY_BLOCKED` | Roter Alert mit `preflight.message`, kein Restart |
| 409 | `LOGGER_CONFIG_MISSING` | Roter Alert |
| 429 | Rate-Limit | Oranger Alert mit **Live-Countdown** aus `Retry-After`-Header |
| 403 | CSRF/Auth | Roter Alert "Zugriff verweigert" |
| 401 | nicht eingeloggt | Login-View |

**Rate-Limit-Countdown:** `setInterval` 1s, Element `#logger-rate-limit-countdown`. Wird beim naechsten Apply-Klick wieder gestoppt.

---

## 4. Wiederverwendung

**Aus `common.js`:** `apiUrl()`, `checkAuth()`, `_loadInto()`, `_escapeHtml()`, `showOnly()`.

**Aus `common.css`:** `.kpi-card`, `.kpi-value`, `.kpi-label`, `.empty-note`, `.empty-note-ok`, `.status-*`.

**Aus Tabler:** `.card`, `.card-header`, `.card-body`, `.table`, `.table-vcenter`, `.alert-*`, `.alert-title`, `.btn-*`, `.badge`, `.metrics-grid`.

**Keine Aenderung** an `common.js`, `common.css` oder anderen Page-Dateien.

**Nur neu:** `logger.js` mit eigenen Helpern `_loggerTimeAgo`, `_loggerHandlerKind`, `_loggerState`, `_loggerRateLimit`.

---

## 5. Tests

`tests/test_control_center_ui.py` — 6 neue Tests:

- `/logger` rendert mit Titel und Marker "MusicBot Control Center".
- Alle Panel-IDs vorhanden (`logger-runtime-kpi`, `-content`, `-refresh-btn`, `logger-config-content`, `logger-diff-content`, `logger-apply-btn`, `logger-apply-status`).
- `logger.js`-Referenz im Template.
- Sidebar-Eintrag `/logger` auf `/`, `/logs`, `/admin`, `/navidrome` sichtbar.
- Sidebar-Eintrag ist `active` nur auf `/logger`, nicht auf `/logs`.
- Warnung "startet den Bot neu" auf der Seite; kein "Logger live".

Ergebnis: **115 passed** in `tests/test_control_center_ui.py`.

Regressionslauf: siehe §9.

---

## 6. Was L6 leistet — und was nicht

**L6 liefert:**

- Volle Sicht auf Runtime-Zustand (Zustand nach letztem Start).
- Volle Sicht auf persistierte Konfiguration.
- Diff-Vergleich beider.
- Apply-Knopf mit klarer Semantik (Restart, nicht Live-Control).

**L6 ist nicht:**

- Kein Logger-Konfigurator (PATCH-Endpoint bleibt nicht exponiert).
- Kein Live-Control (existiert nicht, siehe L3).
- Keine neue API-Flaeche.
- Keine Backend-Aenderung.

---

## 7. Bewusst NICHT in L6

| Nicht implementiert | Warum |
|---|---|
| Config-PATCH-UI | Separater Scope; wuerde Validierungs-/Preview-Flow erfordern |
| Log-Reader | Ist L2 (`/logs`) |
| Neue CSS-Datei | common.css + Tabler reichen |
| common.js-Aenderungen | Nur logger.js nutzt bestehende Helper |
| Backend-Aenderungen | Keine |
| Neue APIs | Keine |
| IPC / Socket | Keine |
| Telegram-Migration | L7 |
| Parity-Audit | L8 |

---

## 8. Bekannte Einschraenkungen

**Browser-Runtime-Test:** Nicht durchgefuehrt — kein Headless-Browser in dieser Umgebung verfuegbar. Verifikation per HTTP-Response und Template-Marker. Manuelle Browser-Pruefung steht beim Nutzer aus.

**Snapshot-Abhaengigkeit:** Ohne neu geschriebenen Snapshot (Bot seit L5-Merge nicht gestartet) zeigt Panel 1/3 nur `missing`-Hinweise. Das ist korrekt — der Snapshot wird erst beim naechsten Startup geschrieben.

**Rate-Limit-Countdown:** Reiner Client-Countdown aus `Retry-After`. Der echte Limiter sitzt serverseitig (L5), der Countdown ist rein informativ.

---

## 9. Regressionsergebnis

Wird nach dem Regression-Lauf eingetragen.

---

## 10. Verweise

- L2-Dokument: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`
- L3-Dokument: `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`
- L4-Dokument: `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`
- L5-Dokument: `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md`
