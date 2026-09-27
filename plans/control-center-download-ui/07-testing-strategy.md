# Testing Strategy: Control Center Download UI (D.11)

> **Document**: 07-testing-strategy.md
> **Parent**: [Index](00-index.md)

## Testing Overview

### Coverage Goals

| Code type | Target |
| --------- | ------ |
| Backend (Job-/History-Endpunkte) | **unverändert** — bereits 100 % der neuen UI-relevanten Pfade durch `tests/test_control_center_download_jobs.py` (9 Tests) + `tests/test_control_center_auth.py` (3 Tests) abgedeckt, keine neuen Backend-Tests nötig (keine Backend-Änderung) |
| Frontend (HTML/JS) | String-Matching gegen ausgelieferte Templates/JS-Quelltexte — identisches, im gesamten Control Center einzig verfügbares Testverfahren (kein Browser-Runtime verfügbar, bestehende, dokumentierte Einschränkung, siehe `02-current-state.md`) |

- Test-Dateikonvention: **kein** `[feature].spec.test.py`/`.impl.test.py` (AR #6) — Tests werden in `tests/test_control_center_ui.py` ergänzt, mit klar benannten Testfunktionen (`test_*_spec_*` für spezifikationsableitende, `test_*` ohne `_spec_`-Marker für Implementierungs-/Edge-Case-Tests), damit die spezifikationsableitenden Tests im Code eindeutig als „vor der Implementierung geschrieben, aus 07 abgeleitet" erkennbar sind, ohne die pytest-Discovery oder CLAUDE.md §8.A zu brechen.
- Alle String-Matching-Assertions folgen dem bestehenden Muster (`assert 'id="..."' in html`, `assert "funktionsname" in js_source`) — siehe `tests/test_control_center_ui.py::test_downloads_page_has_history_panel` und die `health.js`/`logger.js`-Tests in derselben Datei als Vorlage.

## 🚨 Specification Test Cases (MANDATORY — NON-NEGOTIABLE)

> Abgeleitet ausschließlich aus `01-requirements.md` (Acceptance Criteria), `03-01-frontend-html.md`, `03-02-frontend-js.md` und `00-ambiguity-register.md`. **IMMUTABLE ORACLE RULE:** Schlägt ein ST-Case nach der Implementierung fehl, ist die Implementierung falsch — nicht der Test.

### Downloads-Seite (`GET /downloads`)

| #    | Input / Scenario | Expected Output / Behavior | Source |
|------|-------------------|------------------------------|--------|
| ST-1 | `GET /downloads` (authentifiziert) | HTML enthält `id="download-url-input"` | AC1 / 03-01 §Markup Start |
| ST-2 | `GET /downloads` | HTML enthält `id="download-start-btn"` | AC1 / 03-01 §Markup Start |
| ST-3 | `GET /downloads` | HTML enthält `id="download-status-content"` | AC3 / 03-01 §Markup Start |
| ST-4 | `GET /downloads` | HTML enthält `<script src="` gefolgt von `static/pages/downloads.js` | AR #1 / 03-01 §Integration Points |
| ST-5 | `GET /downloads` | HTML enthält **nicht** mehr `function loadDownloads` (Definition ist ausgelagert, nur noch der Endpunkt-String `/api/v1/downloads/history` darf noch referenziert sein, falls überhaupt, sonst gar nicht) | AR #1 / 02-current-state §Gap 1 |
| ST-6 | `GET /downloads` | HTML enthält `id="download-start-form"` | 03-01 §Markup Start |

### `downloads.js` (`GET /static/pages/downloads.js`)

| #    | Input / Scenario | Expected Output / Behavior | Source |
|------|-------------------|------------------------------|--------|
| ST-7  | `GET /static/pages/downloads.js` | Quelltext enthält `function loadDownloads` UND `function renderDownloads` (aus dem Inline-Script übernommen) | AC1 / 02-current-state §Gap 1 |
| ST-8  | `GET /static/pages/downloads.js` | Quelltext enthält `startDownload` | AC1 / 03-02 §Neue Funktionen |
| ST-9  | `GET /static/pages/downloads.js` | Quelltext enthält `cancelDownload` | AC4 / 03-02 §Neue Funktionen |
| ST-10 | `GET /static/pages/downloads.js` | Quelltext enthält `/api/v1/jobs/download/` (Polling-/Cancel-URL-Baustein) | AC3 / 03-02 §_pollDownloadJob |
| ST-11 | `GET /static/pages/downloads.js` | Quelltext enthält `_escapeHtml` (mindestens 3 Vorkommen — Job-Message, Verlaufs-Titel/Artist, Fehlermeldung) | AR #10 / 03-02 §Error Handling |
| ST-12 | `GET /static/pages/downloads.js` | Quelltext enthält `genre_ok` UND `lyrics_ok` UND `cover_ok` UND `mb_ok` UND `loudness_ok` | AR #4 / 03-02 §_tierBadge |
| ST-13 | `GET /static/pages/downloads.js` | Quelltext enthält `download-retry-btn` UND `dataset.url` (Retry-Wiring) | AR #11 / 03-02 §Event-Delegation |
| ST-14 | `GET /static/pages/downloads.js` | Quelltext enthält **nicht** `is_supported_download_url` (keine Duplizierung der serverseitigen Domain-Allowlist-Funktion im Frontend) | 01-requirements §Security / 03-02 §Initialisierung |
| ST-15 | `GET /static/pages/downloads.js` | Quelltext enthält `setInterval` mit `1000` (Job-Polling-Intervall) | AC3 / 01-requirements §Performance |

> **⚠️ AUTHORING RULE:** ST-1 bis ST-15 werden VOR der Implementierung als fehlschlagende Tests geschrieben (Red-Phase — `downloads.js` existiert noch nicht, die neuen IDs existieren noch nicht in `downloads.html`).

## Test Categories

### Specification Tests (aus den ST-Cases oben)
> Geschrieben VOR der Implementierung, ergänzt in der bestehenden `tests/test_control_center_ui.py` (Begründung AR #6).

| Test-Funktion(en) | ST Cases Covered | Component |
| -------------------- | ----------------- | ------------- |
| `test_downloads_page_has_start_form` | ST-1, ST-2, ST-3, ST-6 | 03-01 |
| `test_downloads_page_has_history_panel` (angepasst) | ST-4, ST-5 | 03-01 |
| `test_downloads_js_has_history_functions` | ST-7 | 03-02 |
| `test_downloads_js_has_job_functions` | ST-8, ST-9, ST-10, ST-15 | 03-02 |
| `test_downloads_js_escapes_dynamic_values` | ST-11 | 03-02 |
| `test_downloads_js_has_metadata_checklist` | ST-12 | 03-02 |
| `test_downloads_js_has_retry_wiring` | ST-13 | 03-02 |
| `test_downloads_js_does_not_duplicate_url_validation` | ST-14 | 03-02 |

### Implementation Tests (Edge Cases, nach der Implementierung)

| Test-Funktion(en) | Description | Priority |
| --------------------- | -------------------------------------------------- | ------------ |
| `test_downloads_page_start_form_requires_auth` | `GET /downloads` ohne Session → Redirect/401 gemäß bestehendem Auth-Wiring (Regressionstest, kein neues Verhalten) | Medium |
| `test_downloads_js_requires_auth_like_other_pages` | `GET /static/pages/downloads.js` folgt demselben Auth-/Static-Serving-Verhalten wie `health.js` (Konsistenz-Check) | Low |
| `test_downloads_js_progress_bar_uses_job_progress_field` | Quelltext bindet den Fortschrittsbalken an `job.progress` (nicht an einen erfundenen Feldnamen) | Medium |

### Integration Tests

| Test | Components | Description |
| ----------- | ------------ | ------------- |
| _(keine neuen)_ | — | Der End-to-End-Pfad (Job erstellen → pollen → Ergebnis) ist bereits vollständig durch `tests/test_control_center_download_jobs.py` abgedeckt (Backend unverändert). Ein echter Browser-E2E-Test für die UI-Interaktion selbst ist mangels Browser-Runtime in diesem Repo nicht möglich (bestehende Einschränkung). |

### End-to-End Tests

| Scenario | Steps | Expected Result |
| ---------- | ------- | ---------------- |
| Manueller Smoke-Test (durch den Nutzer, kein automatisiertes Browser-Tooling in dieser Session verbunden) | `/downloads` öffnen → URL eingeben → Download starten → Fortschritt beobachten → Abschluss/Ergebnis prüfen → Verlauf mit Badges prüfen → Retry-Button klicken | Alle in `01-requirements.md` §Acceptance Criteria beschriebenen Verhalten sichtbar korrekt |

## Test Data

### Fixtures Needed
- Keine neuen Backend-Fixtures — bestehende `client`-Fixture aus `tests/test_control_center_ui.py` genügt (reiner HTTP-Response-Text-Abruf).

### Mock Requirements
- Keine — es werden ausschließlich bereits ausgelieferte statische Inhalte (Template-HTML, JS-Quelltext) per echtem HTTP-Request geprüft, kein Mocking von Downloadern/Detektoren nötig (Backend unverändert, dort bereits vollständig gemockt in `tests/test_control_center_download_jobs.py`).

## Verification Checklist
- [ ] Alle ST-Cases (ST-1 bis ST-15) mit konkreten Input/Output-Paaren definiert
- [ ] Jeder ST-Case referenziert ein Requirement/AR/03-Dokument
- [ ] Spezifikationstests VOR der Implementierung geschrieben
- [ ] Spezifikationstests vor der Implementierung als fehlschlagend verifiziert (Red-Phase)
- [ ] Alle Spezifikationstests nach der Implementierung grün (Green-Phase)
- [ ] Implementierungstests für Edge Cases ergänzt
- [ ] `tests/test_control_center_ui.py` vollständig grün
- [ ] `tests/test_control_center_download_jobs.py` weiterhin grün (Regressionscheck, unverändertes Backend)
- [ ] Keine Regression in `tests/test_control_center_auth.py`
