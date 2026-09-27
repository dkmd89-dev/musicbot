# Control Center Download UI (Client Consolidation Phase D.11) Implementation Plan

> **Feature**: Downloads-Web-UI im MusicBot Control Center — Download starten, Live-Jobstatus/Fortschritt, Cancel, erweiterte Verlaufsanzeige mit Metadaten-Checkliste
> **Status**: Planning Complete
> **Created**: 2026-09-28
> **CodeOps Skills Version**: 3.20.0

## Overview

Client Consolidation Phase D.10 hat den Backend-Weg für Web-Downloads bereits vollständig implementiert und committed (PR #332): ein `AccessLevel.USER`-Router (`control_center/routers/jobs.py::user_router`) mit `POST /api/v1/jobs/download`, `GET /api/v1/jobs/download/{job_id}` und `POST /api/v1/jobs/download/{job_id}/cancel`, der ausschließlich die bereits Telegram-freie Fachlogik (`YoutubeDownloader`, `DuplicateDetector`, `services/downloader/download_pipeline_core.py`, `DownloadResultReporter`) aufruft — keine zweite Download-Implementierung. Offen ist laut `docs/audits/CLIENT_CONSOLIDATION_PHASE_D_DOWNLOAD_RUNTIME_2026-09-27.md` Abschnitt 6 ausdrücklich nur noch **D.11: die Control-Center-Downloads-UI** (Dashboard/Downloads → Download starten → Jobstatus → Fortschritt/Ergebnis → Cancel).

Dieser Plan deckt ausschließlich D.11 ab. Die zentrale Analyse-Erkenntnis: **es ist keine einzige Backend-/Service-/Schema-Änderung nötig.** Alle benötigten Endpunkte, Felder und sogar die Metadaten-Checkliste (`genre_ok`/`lyrics_ok`/`cover_ok`/`mb_ok`/`loudness_ok`) existieren bereits vollständig und getestet im Backend — dieser Plan erweitert ausschließlich `control_center/templates/downloads.html` und legt neu `control_center/static/pages/downloads.js` an, nach dem bereits etablierten Job-Start→Polling→Render-Muster von `health.js` (Repair/Health-Scan) und der Duplikat-Check-Verdrahtung in `library_artist_detail.html`.

Das offene, in Abschnitt 5.6 des Audit-Dokuments explizit als NICHT geschlossen markierte Cross-Process-Schreibzugriffs-Risiko (`DuplicateCache`/`DownloadHistoryStore`, gleichzeitig aus Bot- und CC-Prozess beschreibbar) bleibt unabhängig davon offen und wird durch diese UI-Phase nicht mitgelöst (siehe `02-current-state.md` Risiken).

## Document Index

| #   | Document                                              | Description                                                          |
| --- | ------------------------------------------------------ | ---------------------------------------------------------------------- |
| AR  | [Ambiguity Register](00-ambiguity-register.md)        | Zero-Ambiguity Gate — 10 Entscheidungen, alle aufgelöst              |
| 00  | [Index](00-index.md)                                  | Dieses Dokument — Übersicht und Navigation                           |
| 01  | [Requirements](01-requirements.md)                    | Anforderungen, Scope, Telegram-Paritätsmatrix                         |
| 02  | [Current State](02-current-state.md)                  | Analyse des bestehenden Codes (Backend vollständig, UI-Lücke)         |
| 03-01 | [Frontend: HTML](03-01-frontend-html.md)            | `downloads.html`-Struktur (Cards, States, Interaktionen)               |
| 03-02 | [Frontend: JavaScript](03-02-frontend-js.md)        | `downloads.js`-Implementierung (State-Machine, Funktionen, APIs)       |
| 07  | [Testing Strategy](07-testing-strategy.md)            | Spec-Testfälle und Verifikation                                       |
| 99  | [Execution Plan](99-execution-plan.md)                | Phasen, Aufgaben-Checkliste                                            |

## Quick Reference

### Usage Examples

Nutzer öffnet `/downloads` im Control Center → gibt eine YouTube-URL in das neue Start-Formular ein → Klick auf "Download starten" → `POST /api/v1/jobs/download` erstellt einen Job → `downloads.js` pollt `GET /api/v1/jobs/download/{job_id}` alle 1000ms → Fortschrittsbalken + Statustext aktualisieren sich anhand der Job-Meilensteine → bei Abschluss erscheint das Ergebnis (Erfolg/Duplikat/Fehlschlag/Abbruch, 1:1 aus `result.message`/`error`) → der neue Eintrag erscheint beim nächsten 30s-Refresh in der bestehenden, um die Metadaten-Checkliste erweiterten Verlaufstabelle. Ein "Abbrechen"-Button ist während `PENDING`/`RUNNING` aktiv und ruft `POST /api/v1/jobs/download/{job_id}/cancel`.

### Key Decisions

| Decision     | Outcome   |
| ------------ | --------- |
| Eigene `downloads.js` anlegen | Ja (AR #1) |
| Mehrere gleichzeitige eigene Downloads im UI | Nein, nur ein aktiver Job (AR #2) |
| Fortschrittsanzeige | Numerischer Progress-Bar mit groben Meilensteinwerten (AR #3) |
| Metadaten-Checkliste in Verlaufstabelle | In Scope (AR #4) |
| Ergebnis-Darstellung | `result.message` 1:1 als vorformatierter, escapeter Block (AR #5) |
| „🔁 Erneut versuchen"-Button in der Verlaufstabelle | Ja, in Scope (AR #11) |
| Backend-/Service-/Schema-Änderungen | Keine — alle Endpunkte/Felder existieren bereits |

## Related Files

**Geändert:**
- `control_center/templates/downloads.html` — Start-Formular + Aktiver-Job-Card ergänzt, Inline-`<script>` entfernt, Verlaufstabelle um Metadaten-Checkliste erweitert
- `tests/test_control_center_ui.py` — bestehenden Test `test_downloads_page_has_history_panel` angepasst + neue Tests ergänzt

**Neu angelegt:**
- `control_center/static/pages/downloads.js`

**Unverändert (bewusst, siehe `02-current-state.md`):**
- `control_center/routers/jobs.py`, `control_center/routers/downloads.py`, `control_center/schemas/jobs.py`, `control_center/schemas/downloads.py`
- `services/downloader/*`, `services/jobs/*`, `klassen/download_handler.py`
- `control_center/routers/ui.py` (Route bleibt ein reiner Template-Render ohne zusätzlichen Kontext)
