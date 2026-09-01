# Technical Debt Cleanup — 2026-09-01

Read-only-Ausgangspunkt: Post-Baseline-v5 Health & Risk Audit
(`docs/MusicBot_ENGINEERING_BASELINE_v6.md`) + Durchsicht von
`docs/MusicBot_ARCHITECTURE_EVOLUTION.md` (AE-Punkte). Dieser Report
dokumentiert die anschließend tatsächlich umgesetzte Behebung der dabei
identifizierten, noch offenen P2/P3-Findings ("Track A").

## Baseline

| Feld | Wert |
|---|---|
| Baseline-Dokument | `docs/MusicBot_ENGINEERING_BASELINE_v6.md` (Freeze 2026-09-01) |
| Baseline-Testergebnis | 1634 passed, 1 skipped, 0 failed |

## HEAD

| Feld | Wert |
|---|---|
| Commit | `f7eb2eb3dd0a5a934f341c41728756bd67d73f27` |
| Branch | `main` |

## Testanzahl

| | Anzahl |
|---|---|
| Vorher (Baseline v6) | 1634 passed, 1 skipped |
| Nachher (aktueller HEAD) | 1652 passed, 1 skipped |
| Differenz | +18 neue Tests |

## Teststatus

```
python3 -m pytest tests/ -q
1652 passed, 1 skipped, 19 subtests passed, 0 failed
```

0 failed, keine Regression. Der eine Skip ist umgebungsbedingt
(`tests/test_resolve_duplicates.py::...`, reale Badchieff-Testdaten nicht
vorhanden) und unverändert seit vor dieser Session.

---

## Findings

| ID | Finding | Status | Änderung | Tests |
|---|---|---|---|---|
| P2-01 | `handlers/test_menu_handler.py` INV-01 — 5× `subprocess.run()` blockierten den Event-Loop, im schlimmsten Fall (Performance-Tests) bis zu 900s für alle Telegram-Nutzer | **FIXED** | Alle 5 Aufrufstellen mit `asyncio.to_thread()` gewrappt (PR #85) | 5 neu, Pre-Fix-Diskriminierung verifiziert |
| P2-02 | `utils/filenamefixer.py::move_to_library()` — TOCTOU-Race bei der Zieldateinamensvergabe (prozessübergreifend ausnutzbar, z. B. Bot + gleichzeitig laufendes `reprocess_artist_metadata.py`) | **FIXED** | `final_target` wird jetzt per `os.O_CREAT \| O_EXCL` atomar beansprucht statt nur per `.exists()` geprüft (PR #87) | 1 neu (2 echte Threads, `threading.Barrier`), Pre-Fix-Diskriminierung verifiziert |
| P2-03 | `.info.json`-Reste in `import/downloads/` (= `Config.DOWNLOAD_DIR`) | **ALREADY FIXED** | Keine Code-Änderung — verifiziert, dass `download_artifact_cleanup.py` (Strategie A: Start-Sweep, Strategie C: gezielter Cleanup bei 4 Fehlerpfaden) `.info.json` bereits vollständig abdeckt. Baseline-Charakterisierung war veraltet, nie gegen den bereits bestehenden Code re-verifiziert | — |
| P3-01 | `pylast.LastFMNetwork.__repr__()` — bettet `api_key`/`api_secret`/`session_key`/`password_hash` im Klartext ein; jedes abhängige pylast-Objekt (`Artist`, `Track`, …) erbt das Risiko über `repr(self.network)` | **FIXED** | `services/clients/lastfm_client.py` patcht `pylast.LastFMNetwork.__repr__` beim Modul-Import auf eine redigierte Fassung (PR #86) | 6 neu, Pre-Fix-Diskriminierung verifiziert |
| P3-02 | `Config.DOWNLOAD_TIMEOUT`/`Config.YTDL_BASE_OPTIONS` — tote Config-Werte, 0 Aufrufer (AE-05) | **FIXED** | Beide entfernt, referenzierende "toter Code"-Kommentare aktualisiert (PR #88) | keine neuen nötig (reine Entfernung) |
| P3-03 | `services/metadata/tag_writer.py` — fsync-Begründungskommentar behauptete noch synchrone Event-Loop-Ausführung, obwohl seit AE-12 längst über `asyncio.to_thread` gewrappt | **FIXED** | Kommentar korrigiert (PR #88, gebündelt mit P3-02) | — (reine Doku-Korrektur) |
| P3-04 | `CoverProcessor._cache_best_cover()` — Metadaten-JSON-Sidecar nicht atomar geschrieben (AE-03) | **FIXED** | Write-tmp + atomarer `os.replace()`, analog zu `_cache_set()`/RES-02 (PR #89) | 3 neu, Pre-Fix-Diskriminierung verifiziert |
| P3-05 | `StatisticsCalculator.export_stats_to_json()` — Export-Datei nicht atomar geschrieben | **FIXED** | Write-tmp + atomarer `os.replace()` (PR #90) | 3 neu, Pre-Fix-Diskriminierung verifiziert |

---

## Änderungen

Ausschließlich tatsächlich gemergte PRs (`main`, in dieser Reihenfolge):

- **PR #85** — `fix/test-menu-handler-event-loop-blocking`: `handlers/test_menu_handler.py`, `tests/test_test_menu_handler_event_loop_blocking.py` (neu)
- **PR #86** — `fix/pylast-network-repr-secret-leak`: `services/clients/lastfm_client.py`, `tests/test_lastfm_client_network_repr_scrubbing.py` (neu)
- **PR #87** — `fix/move-to-library-toctou`: `utils/filenamefixer.py`, `tests/test_filenamefixer_move_to_library_toctou.py` (neu)
- **PR #88** — `chore/config-dead-values-cleanup`: `config.py`, `services/metadata/tag_writer.py`, `services/downloader/download/download_executor.py`, `tests/test_download_executor.py`
- **PR #89** — `fix/cover-processor-best-cover-meta-atomic`: `services/metadata/cover_processor.py`, `tests/test_cover_processor_best_cover_meta_atomic_write.py` (neu)
- **PR #90** — `fix/statistics-calculator-export-atomic`: `services/statistik/statistics_calculator.py`, `tests/test_statistics_calculator_export_atomic_write.py` (neu)

Jeder PR einzeln: gezielte Tests → direkte Regression → thematische Suite
→ eigene Merge-Freigabe. Volle Suite nach jedem PR grün, keine
Zwischen-Regression.

---

## Tests

| | Vorher | Nachher |
|---|---|---|
| Testanzahl | 1634 passed, 1 skipped | 1652 passed, 1 skipped |
| Fehlschläge | 0 | 0 |

Neue Tests je Finding wie in der Findings-Tabelle vermerkt (P2-01: 5,
P2-02: 1, P3-01: 6, P3-04: 3, P3-05: 3 — Summe 18, exakt reproduziert).
Jeder mit einem funktionalen Code-Fix verbundene Test wurde per
Pre-Fix-Diskriminierung (`git stash` auf die Produktionsänderung, Test
muss dort fehlschlagen) gegen den ungefixten Stand verifiziert.

---

## Out of Scope

Bewusst untersucht, aber **nicht** verändert:

- **`services/duplicate/cache.py` INV-01** (synchrone Persistenz) — laut
  `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` (P0-B) explizit als „mass
  conversion of synchronous functions to async" eingestuft und für diese
  Art Phase verboten; würde eine Async-Kaskade durch `DuplicateDetector`
  (5 Methoden), die Telegram-Präsentationsschicht und 2 Aufrufstellen in
  `download_handler.py` erzwingen. Dauerhaft zurückgestellt, keine
  Umsetzung ohne eigene Architektur-Entscheidung.
- **`download_executor.py::download_single_track()` Cancellation-Cleanup**
  — laut DL-01-Audit (`docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2D_DL01_AUDIT.md`)
  bewusst unbehandelt gelassen: eine verwaiste Datei landet nur in
  `DOWNLOAD_DIR`, wird vom bereits laufenden 24h-Start-Sweep
  (`cleanup_download_artifacts()`) automatisch erfasst — kein akutes
  Risiko. In dieser Session erneut bestätigt, bewusst nicht gefixt.
- **AE-04 `MUSICBRAINZ_RETRIES`** — totes Config (0 Aufrufer), braucht
  aber erst eine fachliche Entscheidung (Retry-Logik wirklich verdrahten,
  oder als toten Wert entfernen), kein reiner Klein-Fix.
- **DL-03/DL-05** (keine Fehlerklassifikation bei Download-/
  Metadata-Retries) — zweimal zuvor zurückgestellt, würde eine echte
  Fehlerklassifikations-Logik erfordern, eigene künftige Entscheidung
  nötig.
- **`mugge_statistik_handler.py`** ohne `error_handler`-Integration —
  struktureller UX-Konflikt (separat versendete Zwischennachricht statt
  `callback_query`-Nachricht), bewusste Nutzer-Entscheidung, nicht
  mechanisch nachzurüsten.

---

## Remaining Technical Debt

Tatsächlich noch offene, relevante Findings nach Abschluss dieses Reports:

| ID | Finding | Priorität | Grund für Zurückstellung |
|---|---|---|---|
| — | `duplicate/cache.py` INV-01 | P2 | Architektur-Entscheidung nötig (siehe Out of Scope) |
| AE-04 | `MUSICBRAINZ_RETRIES` totes Config | P2 | Fachliche Entscheidung nötig (verdrahten oder entfernen) |
| DL-03 | Keine Fehlerklassifikation bei Download-Retries | P2 | Design-Entscheidung nötig |
| DL-05 | Metadata-Fehler wird unnötig retried | P2 | Design-Entscheidung nötig (hängt mit DL-03 zusammen) |
| — | `download_executor.py` Cancellation-Cleanup | P2 | Bereits durch 24h-Start-Sweep abgedeckt, kein akutes Risiko |
| — | `mugge_statistik_handler.py` ohne `error_handler` | — | Struktureller UX-Konflikt, bewusste Nutzer-Entscheidung |

Keine offenen P0/P1-Findings.
