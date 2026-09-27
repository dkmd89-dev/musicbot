Execution Plan: Control Center Download UI (D.11)
Document: 99-execution-plan.md Parent: Index Last Updated: 2026-09-28 00:50 Progress: 0/12 tasks (0%) CodeOps Skills Version: 3.20.0

Overview
Reine Frontend-Erweiterung (kein Backend-/Service-/Schema-Change): control_center/templates/downloads.html erweitern, control_center/static/pages/downloads.js neu anlegen, tests/test_control_center_ui.py anpassen/erweitern. Client Consolidation Phase D.11 (letzter offener Schritt aus docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md Abschnitt 6).

🚨 Update this document after EACH completed task!

Implementation Phases
Phase    Title    Tasks
1    Downloads-UI (Spec Tests → Implementierung → Impl Tests)    10
2    Dokumentation nachziehen + gezielte Regression    2
Total: 12 tasks across 2 phases (keine Stundenschätzung — Umfang durch die Task-Größenkriterien in quality-checklist.md begrenzt)

⚠️ EXECUTION RULE — APPLIES TO EVERY AGENT EXECUTING THIS PLAN:

Die Task-Checkboxen in den Phasenabschnitten unten sind die einzige Quelle der Wahrheit für den Fortschritt. Jede Task-Zeile erscheint in diesem Dokument genau einmal.

Bei Implementierung: Task auf [~] mit Zeitstempel setzen — - [~] 1.1.1 Task ⏳ (implemented: YYYY-MM-DD HH:MM)
Bei bestandener Verifikation: auf [x] heben — - [x] 1.1.1 Task ✅ (completed: YYYY-MM-DD HH:MM)
Progress-Header und Last-Updated-Stempel nach JEDER Task aktualisieren — nie sammeln. Nur [x] zählt als erledigt.
Fortsetzen: Phasenabschnitte von oben nach unten scannen — die erste [~]-Task zuerst fortsetzen, sonst die erste [ ]-Task.
Zeitstempel kommen aus date '+%Y-%m-%d %H:%M' — nie erfunden.

Phase 1: Downloads-UI (Spec Tests → Implementierung → Impl Tests)
Phase ref: (wird vom exec_plan-Skill bei Phasenstart per git rev-parse HEAD erfasst)

Step 1.1: Spezifikationstests (VOR der Implementierung)
Reference: 07-testing-strategy.md ST-1..ST-15 Objective: Alle 15 ST-Cases als fehlschlagende Tests in tests/test_control_center_ui.py anlegen (Red-Phase) — die geprüften IDs/Funktionen/Strings existieren noch nicht.

nicht erledigt
1.1.1 Spezifikationstests für ST-1..ST-6 (Downloads-Seiten-Markup: Start-Formular, download-status-content, downloads.js-Einbindung, alte Inline-loadDownloads-Definition entfernt) ergänzen — tests/test_control_center_ui.py
nicht erledigt
1.1.2 Spezifikationstests für ST-7..ST-15 (downloads.js-Quelltext: History-Funktionen, Job-Start/Cancel/Poll, Escaping, Metadaten-Checkliste, Retry-Wiring, keine URL-Validierungs-Duplizierung, 1s-Polling) ergänzen — tests/test_control_center_ui.py
nicht erledigt
1.1.3 Red-Phase verifizieren: python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q — alle neuen Tests schlagen erwartungsgemäß fehl (Datei/IDs existieren noch nicht); Ergebnis dokumentieren
Deliverables:

nicht erledigt
15 neue/angepasste Testfälle in tests/test_control_center_ui.py, nachweislich rot
Verify: python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q (erwartetes Ergebnis: FAILs, dokumentiert)

Step 1.2: Implementierung
Reference: 03-01-frontend-html.md · 03-02-frontend-js.md Objective: downloads.html erweitern, downloads.js neu anlegen — bis ST-1..ST-15 grün sind.

nicht erledigt
1.2.1 control_center/templates/downloads.html: Start-Formular-Card + download-status-content ergänzen, Inline-<script> entfernen, <script src=".../downloads.js"> einbinden — per 03-01-frontend-html.md §Markup
nicht erledigt
1.2.2 control_center/static/pages/downloads.js neu anlegen, Verlaufs-Teil: loadDownloads/renderDownloads aus dem bisherigen Inline-Script übernehmen + um _tierBadge()-Metadaten-Badges (AR #4) und Retry-Button-Wiring inkl. Event-Delegation (AR #11) erweitern — per 03-02-frontend-js.md §renderDownloads/§Event-Delegation
nicht erledigt
1.2.3 control_center/static/pages/downloads.js ergänzen, Job-Teil: startDownload/_pollDownloadJob/_renderDownloadJob/_renderDownloadResult/cancelDownload/_setDownloadFormBusy/_stopDownloadPolling implementieren + initDownloadsPage() verdrahten — per 03-02-frontend-js.md §Neue Funktionen/§Initialisierung
nicht erledigt
1.2.4 Green-Phase verifizieren: python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q — alle ST-1..ST-15 grün; bei einem fehlschlagenden Spec-Test die Implementierung korrigieren, NICHT die Testerwartung (Immutable-Oracle-Regel)
Deliverables:

nicht erledigt
downloads.html + downloads.js gemäß 03-01/03-02 vollständig umgesetzt
nicht erledigt
Alle Spezifikationstests grün
Verify: python3 -m pytest tests/test_control_center_ui.py -k "downloads" -q

Step 1.3: Implementierungstests & Regression
Reference: 07-testing-strategy.md §Implementation Tests Objective: Edge-Case-Tests ergänzen, direkt betroffene Regressionstests + thematische Suite grün.

nicht erledigt
1.3.1 Implementierungstests ergänzen (test_downloads_page_start_form_requires_auth, test_downloads_js_requires_auth_like_other_pages, test_downloads_js_progress_bar_uses_job_progress_field) — tests/test_control_center_ui.py
nicht erledigt
1.3.2 Direkt relevante Regressionstests: python3 -m pytest tests/test_control_center_download_jobs.py tests/test_control_center_auth.py -q (Backend unverändert — reiner Regressionsnachweis, keine Anpassung erwartet)
nicht erledigt
1.3.3 Thematische Suite: python3 -m pytest -k "control_center or download" -q
Deliverables:

nicht erledigt
Implementierungstests grün
nicht erledigt
Keine Regression in Job-/Auth-Tests
nicht erledigt
Thematische Suite grün
Verify: python3 -m pytest -k "control_center or download" -q

Phase 2: Dokumentation nachziehen + gezielte Regression
Phase ref: (wird vom exec_plan-Skill bei Phasenstart per git rev-parse HEAD erfasst)

Step 2.1: Dokumentation
Reference: 01-requirements.md Acceptance Criterion 10 Objective: CLAUDE.md §22 Definition of Done — Doku aktualisieren, da sich Verhalten/UI ändert.

nicht erledigt
2.1.1 docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md Abschnitt 1/6 nachziehen: D.11 von 🔲 OPEN auf ✅ IMPLEMENTED, Cross-Process-Risiko (Abschnitt 5.6) bleibt explizit unverändert offen
nicht erledigt
2.1.2 docs/FINDINGS_INDEX.md-Zeile „Downloads nicht aus dem Control Center startbar" auf vollständig geschlossen aktualisieren (nur den D.11-UI-Teil; Cross-Process-Risiko separat referenzieren)
Deliverables:

nicht erledigt
Beide Dokumente konsistent mit dem tatsächlichen Implementierungsstand
Verify: manuelle Diff-Prüfung (reine Markdown-Änderung, kein Testlauf nötig)

Dependencies
Phase 1 (Downloads-UI: Spec Tests → Implementierung → Impl Tests)
    ↓
Phase 2 (Dokumentation)
Success Criteria
Feature ist abgeschlossen, wenn:

✅ Beide Phasen abgeschlossen
✅ python3 -m pytest -k "control_center or download" -q grün (thematische Suite, Schritt 3 der CLAUDE.md-§8.A-Staffelung)
✅ Keine Warnings/Errors
✅ Kein toter Code — keine ungenutzten Parameter/Funktionen (insbesondere: kein Rest der alten Inline-Script-Logik in downloads.html)
✅ Security gehärtet — _escapeHtml() ausnahmslos auf dynamische Werte angewendet (AR #10), keine Duplizierung der SSRF-Domain-Allowlist im Frontend
✅ Dokumentation aktualisiert (Phase 2)
✅ Volle Testsuite (pytest tests/ -q) wird NICHT von diesem Ausführungsprozess ausgeführt (CLAUDE.md §8.A) — dem Nutzer am Ende explizit empfohlen
✅ Post-Completion-Reanalyse (durch das exec_plan-Skill)

> Detaillierte Session-für-Session-Ausführungsmechanik (Commit-Modi, Echtzeit-Fortschritts-Updates, Post-Completion-Reanalyse) gehört zum **exec_plan-Skill**, nicht hierher.

---

## Specification-First Task Ordering

Phase 1 folgt der dreistufigen Spec-First-Ordnung (`spec tests → red phase → implement → green phase → impl tests → verify`), definiert in `../../_shared/spec-first-ordering.md` — Step 1.1 (Spec Tests + Red-Phase), Step 1.2 (Implementierung + Green-Phase), Step 1.3 (Impl Tests + volle thematische Verifikation).
