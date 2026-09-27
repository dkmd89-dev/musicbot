# Execution Plan: Control Center Download UI (D.11)

> **Document**: 99-execution-plan.md
> **Parent**: [Index](00-index.md)
> **Last Updated**: 2026-09-28 01:08
> **Progress**: 12/12 tasks (100%)
> **CodeOps Skills Version**: 3.20.0

## Overview

Reine Frontend-Erweiterung (kein Backend-/Service-/Schema-Change): `control_center/templates/downloads.html` erweitern, `control_center/static/pages/downloads.js` neu anlegen, `tests/test_control_center_ui.py` anpassen/erweitern. Client Consolidation Phase D.11 (letzter offener Schritt aus `docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md` Abschnitt 6).

**🚨 Update this document after EACH completed task!**

---

## Implementation Phases

| Phase | Title | Tasks |
| ----- | ------------------------------------------------ | ----- |
| 1 | Downloads-UI (Spec Tests → Implementierung → Impl Tests) | 10 |
| 2 | Dokumentation nachziehen + gezielte Regression | 2 |

**Total: 12 tasks across 2 phases** (keine Stundenschätzung — Umfang durch die Task-Größenkriterien in `quality-checklist.md` begrenzt)

> **⚠️ EXECUTION RULE — APPLIES TO EVERY AGENT EXECUTING THIS PLAN:**
>
> Die Task-Checkboxen in den Phasenabschnitten unten sind die **einzige Quelle der Wahrheit** für den Fortschritt. Jede Task-Zeile erscheint in diesem Dokument genau einmal.
>
> 1. **Bei Implementierung:** Task auf `[~]` mit Zeitstempel setzen — `- [~] 1.1.1 Task ⏳ (implemented: YYYY-MM-DD HH:MM)`
> 2. **Bei bestandener Verifikation:** auf `[x]` heben — `- [x] 1.1.1 Task ✅ (completed: YYYY-MM-DD HH:MM)`
> 3. **Progress-Header und Last-Updated-Stempel nach JEDER Task aktualisieren** — nie sammeln. Nur `[x]` zählt als erledigt.
> 4. **Fortsetzen:** Phasenabschnitte von oben nach unten scannen — die erste `[~]`-Task zuerst fortsetzen, sonst die erste `[ ]`-Task.
>
> Zeitstempel kommen aus `date '+%Y-%m-%d %H:%M'` — nie erfunden.

---

## Phase 1: Downloads-UI (Spec Tests → Implementierung → Impl Tests)

> **Phase ref**: `fcca4b979533acb16be7fdb8b0b9c74382e67447`

### Step 1.1: Spezifikationstests (VOR der Implementierung)

**Reference**: [07-testing-strategy.md](07-testing-strategy.md) ST-1..ST-15
**Objective**: Alle 15 ST-Cases als fehlschlagende Tests in `tests/test_control_center_ui.py` anlegen (Red-Phase) — die geprüften IDs/Funktionen/Strings existieren noch nicht.

- [x] 1.1.1 Spezifikationstests für ST-1..ST-6 (Downloads-Seiten-Markup: Start-Formular, `download-status-content`, `downloads.js`-Einbindung, alte Inline-`loadDownloads`-Definition entfernt) ergänzen — `tests/test_control_center_ui.py` ✅ (completed: 2026-09-28 00:43)
- [x] 1.1.2 Spezifikationstests für ST-7..ST-15 (`downloads.js`-Quelltext: History-Funktionen, Job-Start/Cancel/Poll, Escaping, Metadaten-Checkliste, Retry-Wiring, keine URL-Validierungs-Duplizierung, 1s-Polling) ergänzen — `tests/test_control_center_ui.py` ✅ (completed: 2026-09-28 00:43)
- [x] 1.1.3 Red-Phase verifizieren: `python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q` — 6/7 neue Tests schlagen erwartungsgemäß fehl (`downloads.js` existiert noch nicht → 404); `test_downloads_js_does_not_duplicate_url_validation` besteht trivial (Negativ-Assertion gegen die 404-Fehlermeldung), wird in der Green-Phase gegen die echte Datei erneut geprüft ✅ (completed: 2026-09-28 00:43)

**Deliverables**:
- [x] 15 neue/angepasste Testfälle (7 Testfunktionen) in `tests/test_control_center_ui.py`, nachweislich rot ✅ (completed: 2026-09-28 00:43)

**Verify**: `python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q` (erwartetes Ergebnis: FAILs, dokumentiert)

---

### Step 1.2: Implementierung

**Reference**: [03-01-frontend-html.md](03-01-frontend-html.md) · [03-02-frontend-js.md](03-02-frontend-js.md)
**Objective**: `downloads.html` erweitern, `downloads.js` neu anlegen — bis ST-1..ST-15 grün sind.

- [x] 1.2.1 `control_center/templates/downloads.html`: Start-Formular-Card + `download-status-content` ergänzt, Inline-`<script>` durch `{% block scripts %}<script src="{{ base_path }}/static/pages/downloads.js"></script>{% endblock %}` ersetzt (exaktes Einbindungsmuster aus `statistics.html`/`health.html` übernommen, kein `defer`-Attribut — mechanische Korrektur ggü. 03-01-Entwurf) ✅ (completed: 2026-09-28 00:48)
- [x] 1.2.2 `control_center/static/pages/downloads.js` neu angelegt, Verlaufs-Teil: `loadDownloads`/`renderDownloads` aus dem bisherigen Inline-Script übernommen + um `_tierBadgeHtml()`-Metadaten-Badges (AR #4) und Retry-Button-Wiring inkl. Event-Delegation (AR #11) erweitert ✅ (completed: 2026-09-28 00:54)
- [x] 1.2.3 `control_center/static/pages/downloads.js` ergänzt, Job-Teil: `startDownload`/`_pollDownloadJob`/`_renderDownloadJob`/`_renderDownloadResult`/`cancelDownload`/`_setDownloadFormBusy`/`_stopDownloadPolling` implementiert + `initPage()` verdrahtet (Funktionsname `initPage()` statt `initDownloadsPage()` — 1:1 aus dem bisherigen Inline-Script übernommen inkl. `checkAuth()`-Gating vor dem ersten Laden, mechanische Korrektur ggü. 03-02-Entwurf, der dieses Gating nicht erwähnte) ✅ (completed: 2026-09-28 00:54)
- [x] 1.2.4 Green-Phase verifizieren: `python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q` — 11 passed, alle ST-1..ST-15 grün ✅ (completed: 2026-09-28 00:54)

**Deliverables**:
- [x] `downloads.html` + `downloads.js` gemäß 03-01/03-02 vollständig umgesetzt (mit dokumentierten mechanischen Korrekturen)
- [x] Alle Spezifikationstests grün

**Verify**: `python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q`

---

### Step 1.3: Implementierungstests & Regression

**Reference**: [07-testing-strategy.md](07-testing-strategy.md) §Implementation Tests
**Objective**: Edge-Case-Tests ergänzen, direkt betroffene Regressionstests + thematische Suite grün.

- [x] 1.3.1 Implementierungstests ergänzt — **mechanisch korrigiert gegenüber 07/99-Entwurf:** `test_downloads_page_start_form_requires_auth` war falsch geplant (alle Seiten-Routen sind laut `control_center/routers/ui.py`-Docstring bewusst unauthentifiziert, siehe bestehender `test_page_renders_without_any_authentication`) → ersetzt durch `test_downloads_page_stays_public_like_other_pages` (Regressionsschutz in die richtige Richtung); `test_downloads_js_requires_auth_like_other_pages` war redundant (bereits durch alle ST-Tests implizit bewiesen, da sie `/static/pages/downloads.js` ohne Auth erfolgreich abrufen) → entfallen; `test_downloads_js_progress_bar_uses_job_progress_field` unverändert übernommen + `test_downloads_js_cancel_button_only_for_active_states` ergänzt — `tests/test_control_center_ui.py` ✅ (completed: 2026-09-28 00:59)
- [x] 1.3.2 Direkt relevante Regressionstests: `python3 -m pytest tests/test_control_center_download_jobs.py tests/test_control_center_auth.py -q` — 70 passed, keine Regression ✅ (completed: 2026-09-28 01:01)
- [x] 1.3.3 Thematische Suite: `python3 -m pytest -k "control_center or download" -q` — 1115 passed, keine Regression ✅ (completed: 2026-09-28 01:05)

**Deliverables**:
- [x] Implementierungstests grün
- [x] Keine Regression in Job-/Auth-Tests
- [x] Thematische Suite grün

**Verify**: `python3 -m pytest -k "control_center or download" -q`

---

## Phase 2: Dokumentation nachziehen + gezielte Regression

> **Phase ref**: `fcca4b979533acb16be7fdb8b0b9c74382e67447`

### Step 2.1: Dokumentation

**Reference**: [01-requirements.md](01-requirements.md) Acceptance Criterion 10
**Objective**: CLAUDE.md §22 Definition of Done — Doku aktualisieren, da sich Verhalten/UI ändert.

- [x] 2.1.1 `docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md` Abschnitt 1/6 nachgezogen: D.11 von 🔲 OPEN auf ✅ IMPLEMENTED (Status-Tabelle + Abschnitt 6 komplett neu gefasst mit Umsetzungsdetails), Cross-Process-Risiko (Abschnitt 5.6) explizit unverändert offen belassen ✅ (completed: 2026-09-28 01:08)
- [x] 2.1.2 `docs/FINDINGS_INDEX.md`-Zeile „Downloads nicht aus dem Control Center startbar" aktualisiert: D.11-UI-Teil als implementiert dokumentiert, Priorität von P1 auf P2 gesenkt, Cross-Process-Risiko bleibt explizit als offen referenziert (Zeile bewusst nicht auf CLOSED gesetzt, da ein Teilrisiko offen bleibt) ✅ (completed: 2026-09-28 01:08)

**Deliverables**:
- [x] Beide Dokumente konsistent mit dem tatsächlichen Implementierungsstand

**Verify**: manuelle Diff-Prüfung (reine Markdown-Änderung, kein Testlauf nötig) — `git diff --check` sauber ✅ (completed: 2026-09-28 01:08)

---

## Dependencies

```
Phase 1 (Downloads-UI: Spec Tests → Implementierung → Impl Tests)
    ↓
Phase 2 (Dokumentation)
```

---

## Success Criteria

**Feature ist abgeschlossen, wenn:**

1. ✅ Beide Phasen abgeschlossen
2. ✅ `python3 -m pytest -k "control_center or download" -q` grün (thematische Suite, Schritt 3 der CLAUDE.md-§8.A-Staffelung)
3. ✅ Keine Warnings/Errors
4. ✅ Kein toter Code — keine ungenutzten Parameter/Funktionen (insbesondere: kein Rest der alten Inline-Script-Logik in `downloads.html`)
5. ✅ Security gehärtet — `_escapeHtml()` ausnahmslos auf dynamische Werte angewendet (AR #10), keine Duplizierung der SSRF-Domain-Allowlist im Frontend
6. ✅ Dokumentation aktualisiert (Phase 2)
7. ✅ **Volle Testsuite (`pytest tests/ -q`) wird NICHT von diesem Ausführungsprozess ausgeführt** (CLAUDE.md §8.A) — dem Nutzer am Ende explizit empfohlen
8. ✅ Post-Completion-Reanalyse (durch das exec_plan-Skill)
```

> Detaillierte Session-für-Session-Ausführungsmechanik (Commit-Modi, Echtzeit-Fortschritts-Updates, Post-Completion-Reanalyse) gehört zum **exec_plan-Skill**, nicht hierher.

---

## Specification-First Task Ordering

Phase 1 folgt der dreistufigen Spec-First-Ordnung (`spec tests → red phase → implement → green phase → impl tests → verify`), definiert in `../../_shared/spec-first-ordering.md` — Step 1.1 (Spec Tests + Red-Phase), Step 1.2 (Implementierung + Green-Phase), Step 1.3 (Impl Tests + volle thematische Verifikation).
