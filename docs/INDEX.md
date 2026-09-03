# docs/ – Index

Einstiegspunkt für die Dokumentation. Drei Ebenen (siehe README.md für Details):

- **README.md** – Was ist MusicBot? (für Menschen)
- **ENGINEERING_BASELINE** – Wie ist der aktuelle technische Zustand? (für Wartung/Entwicklung)
- **archive/arch/ARCH-xxx / archive/post-arch/POST-ARCH-xxx** – Warum wurde eine Architekturentscheidung getroffen? (Historie, unverändert)

**Ist Finding X gerade offen oder geschlossen?** → [`FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — lebendes, fortlaufend gepflegtes Register aller aktuell offenen/zurückgestellten Punkte, statt durch Baseline-Dokumente blättern zu müssen. Die Tech-Debt-Tabelle in jeder Baseline bleibt ein eingefrorener Schnappschuss zum Freeze-Zeitpunkt.

Status-Legende: **CURRENT** = aktuell gültig · **HISTORICAL** = abgeschlossenes Entscheidungsprotokoll, nicht mehr verändert · **SUPERSEDED** = durch neuere Version abgelöst

Alle HISTORICAL/SUPERSEDED-Dokumente liegen vollständig erhalten unter [`docs/archive/`](archive/) — nur nicht mehr im direkten Sichtfeld von `docs/`, sodass dort ausschließlich die aktuell gültigen (CURRENT) Dokumente stehen. Die Pfade der Findings-Audits (Download Pipeline Stability, Metadata Quality, Einzelfund-Audits) werden aus Code-Kommentaren und Testdatei-Docstrings zur Traceability zitiert (z. B. `# DL-01 (docs/archive/MusicBot_..._AUDIT.md): ...`); beim Verschieben nach `docs/archive/` wurden alle ca. 30 betroffenen Referenzen in Code-Kommentaren, Test-Docstrings und Cross-References zwischen den Dokumenten selbst mit umgezogen.

## Baseline

| Datei | Status | Kurzthema |
|---|---|---|
| [MusicBot_ENGINEERING_BASELINE_v8.md](MusicBot_ENGINEERING_BASELINE_v8.md) | CURRENT (eingefroren nach Freeze 2026-09-02) | Erster vollständiger P0-Kernbereichs-Audit dieser Baseline-Serie (Metadata/Genre/Artist-Mapping/Duplicate Detection, PR #100, sechs Teilphasen P0-A–F + Gesamtaudit) mit zwei gefundenen und gefixten P0-Bugs (Duplicate-Detection-Artist-Normalisierung, YouTube-Shorts-URL-Erkennung), einem P1-Architekturprojekt zur Ursachenbehebung (PR #102, `DuplicateDetector`↔`ArtistNormalizer`-Verdrahtung), sowie zwei kleinen Cleanup-PRs (#99, #101), 1698 passed / 0 failed (1 umgebungsbedingt skipped) — neue Findings → MusicBot_ENGINEERING_BASELINE_v9.md |
| [archive/MusicBot_ENGINEERING_BASELINE_v7.md](archive/MusicBot_ENGINEERING_BASELINE_v7.md) | SUPERSEDED (eingefroren nach Freeze 2026-09-01) | Gezielte Abarbeitung der in v6 + `MusicBot_ARCHITECTURE_EVOLUTION.md` (AE-04) offen gelisteten P2/P3-Findings (13 PRs, #85–#97): Track-A-Cleanup (6 Fixes), Services-Architecture-Audit, DL-03/DL-05-Fehlerklassifikation, `process_single_track()`-Characterization (kein Refactor gerechtfertigt), Telegram-Kopplungs-Entkopplung, `MUSICBRAINZ_RETRIES`-Entscheidung (REMOVE), 1673 passed / 0 failed (1 umgebungsbedingt skipped) — abgelöst durch v8 |
| [archive/MusicBot_ENGINEERING_BASELINE_v6.md](archive/MusicBot_ENGINEERING_BASELINE_v6.md) | SUPERSEDED (eingefroren nach Freeze 2026-09-01) | Post-Baseline-v5 Health & Risk Audit: Re-Verifikation aller 9 v5-DEFER-Punkte + Durchsicht der 28 seit v5 gemergten PRs + Behebung von DOC-01 (Download-Pipeline) und einer Test-Isolation-Lücke (reale Mapping-Writes), 1634 passed / 0 failed (1 umgebungsbedingt skipped) — abgelöst durch v7, v7 wiederum durch v8 |
| [archive/MusicBot_ENGINEERING_BASELINE_v5.md](archive/MusicBot_ENGINEERING_BASELINE_v5.md) | SUPERSEDED (eingefroren nach Freeze 2026-08-26) | Nächster verifizierter Referenzzustand nach Post-Baseline-v4 Health & Risk Audit + Behebung von 3 P1-Findings (Duplicate-Detection-Artist/Titel-Ebene, renamed_due_to_conflict-Signal, Fanart-API-Key-Log-Leak) + Doku-Korrektur (enhanced_error_handler.py), 1123 passed / 0 failed — abgelöst durch v6, v6 durch v7, v7 wiederum durch v8 |
| [archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md](archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md) | HISTORICAL (Analyseartefakt) | Strikt read-only Audit nach v4, Re-Verifikation AE-10/11/12 + 3 neue P1-Findings — Herleitung von v5 |
| [MusicBot_ARCHITECTURE_EVOLUTION.md](MusicBot_ARCHITECTURE_EVOLUTION.md) | CURRENT | Architektur-Invarianten (INV-01–04), Evolution-Kandidaten, ADRs, Closure-Verifikation der Enforcement Fix Phase sowie AE-10/AE-11/AE-12 (Abschnitt 29) — Herleitung von v4 |
| [archive/MusicBot_ENGINEERING_BASELINE_v4.md](archive/MusicBot_ENGINEERING_BASELINE_v4.md) | SUPERSEDED (eingefroren nach Freeze 2026-08-26) | Abgelöst durch v5, v5 durch v6, v6 durch v7, v7 wiederum durch v8 |
| [archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md](archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md) | HISTORICAL (Analyseartefakt) | Freeze-Gate-Audit — initial BLOCKED durch AE-12, nach dessen Schließung per Nachtrag auf APPROVED aktualisiert |
| [archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md](archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md) | HISTORICAL (Analyseartefakt) | Forensischer Design-/Safety-Audit vor der AE-12-Implementierung |
| [archive/AE-12_Closure_Audit.md](archive/AE-12_Closure_Audit.md) | HISTORICAL (Analyseartefakt) | Unabhängig gegengeprüfte Closure-Kriterien-Matrix für den AE-12-Fix (7/7 PASS) |
| [archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md](archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md) | HISTORICAL (Analyseartefakt) | Performance-Charakterisierung nach v3/Phase-4, inkl. FINDING-7-Fix (Event-Loop-Blocking in `normalize_loudness()`) |
| [archive/MusicBot_ENGINEERING_BASELINE_v3.md](archive/MusicBot_ENGINEERING_BASELINE_v3.md) | SUPERSEDED (eingefroren nach Freeze 2026-08-25) | Abgelöst durch v4, v4 durch v5, v5 durch v6, v6 durch v7, v7 wiederum durch v8 |
| [archive/MusicBot_POST_BASELINE_TRIAGE.md](archive/MusicBot_POST_BASELINE_TRIAGE.md) | HISTORICAL (Analyseartefakt) | Herleitung von v3 — sechs-Dimensionen-Triage + Deep-Audit-Nachträge, nicht selbst Baseline |
| [archive/MusicBot_ENGINEERING_BASELINE_v2.md](archive/MusicBot_ENGINEERING_BASELINE_v2.md) | SUPERSEDED (eingefroren nach Closure 2026-08-25) | Abgelöst durch v3 |
| [archive/MusicBot_ENGINEERING_BASELINE.md](archive/MusicBot_ENGINEERING_BASELINE.md) | SUPERSEDED | v1, abgelöst durch v2 |

## Reprocessing Tool

| Datei | Status | Kurzthema |
|---|---|---|
| [METADATA_REPROCESSING.md](METADATA_REPROCESSING.md) | CURRENT | `scripts/reprocess_artist_metadata.py` — bestehende Library-Tracks erneut durch die Metadaten-Pipeline laufen lassen (Tags/Cover/Lyrics/Genre/Multi-Artist/MusicBrainz), ohne Download, ohne Produktionszugriff (read-only), ohne Audio-Reencoding |
| [archive/METADATA_REPROCESSING_TEST_CHAPO102.md](archive/METADATA_REPROCESSING_TEST_CHAPO102.md) | HISTORICAL (Validierungsprotokoll) | Erster Live-Validierungslauf des Tools gegen echten Artist-Bestand (CHAPO102), inkl. Post-Run Safety Check |
| [archive/METADATA_REPROCESSING_TEST_NINA_CHUBA.md](archive/METADATA_REPROCESSING_TEST_NINA_CHUBA.md) | HISTORICAL (Validierungsprotokoll) | Zweiter Validierungslauf (Nina Chuba) + Final-Audit-Nachtrag zu Genre-Mapping-Konsistenz und UNRESOLVED-Praezisierung |

## Genre-System

| Datei | Status | Kurzthema |
|---|---|---|
| [GENRE_SYSTEM.md](GENRE_SYSTEM.md) | CURRENT | Genre-Fallback-Kette (Manuell → Lokal → MusicBrainz → Last.fm → Feature-Artist-Inferenz), Auto-Learn-Konfidenz-Stufen, Lock-in-Mechanismus ab 3 Beobachtungen, Mapping-Dateien-Übersicht (inkl. ARCH-022 YAML→JSON-Migration der drei Auto-Learn-Dateien), Genre-Learning unabhängig vom Artist-Namens-Override, bekannte Revalidierungs-Grenze |

## Download Pipeline Stability Phase

| Datei | Status | Kurzthema |
|---|---|---|
| [MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md](MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md) | CURRENT (Status: PLANNED, noch offen) | Umbrella-Phase: Download-Pipeline- und Duplicate-Detection-Stabilität (Fehlerpfade, Retries, Cancellation, Cleanup) — Metadaten-Qualität explizit out of scope |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md) | HISTORICAL (Analyseartefakt, in Code-Kommentaren referenziert) | Read-Only Deep Audit — Ursprung der Findings DUP-01/02/04/06, PL-01, RES-01/02 |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md) | HISTORICAL (Analyseartefakt, in Code-Kommentaren referenziert) | Priorisierung/Fix-Reihenfolge der PHASE-0-Findings |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2C_DL02_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2C_DL02_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DL-02 — Cleanup verwaister Datei bei fehlgeschlagenem Single-Download |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2D_DL01_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2D_DL01_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DL-01 — Library-Artefakt-Cleanup bei Task-Cancellation |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2G_DL06_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DL-06 — Playlist-Track-Cleanup bei yt-dlp/FFmpeg-Fehler |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2I_TEST_ENVIRONMENT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2I_TEST_ENVIRONMENT.md) | HISTORICAL | Test-Environment-Diagnose (Bot-Account-Mismatch) — Grundlage für TESTENV-01 |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2J_DUP03_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2J_DUP03_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DUP-03 — Live-Version-False-Positive bei Duplicate Detection |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2K_DL08_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2K_DL08_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DL-08 — Playlist-Cancellation-Results erhalten, Mix/Radio-Routing, Track-Retry |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2L_DUP04_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2L_DUP04_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DUP-04 — Feat/ft-Normalisierung im Duplicate-Titel-Vergleich |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2M_DUP06_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2M_DUP06_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | DUP-06 — YouTube-Mix/Radio-URL-Erkennung |
| [archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2N_RES01_AUDIT.md](archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2N_RES01_AUDIT.md) | HISTORICAL | RES-01 — analysiert, bewusst nicht behoben (akzeptiertes Risiko) |

## Telegram Menü-System

| Datei | Status | Kurzthema |
|---|---|---|
| [MusicBot_TELEGRAM_MENU_SYSTEM.md](MusicBot_TELEGRAM_MENU_SYSTEM.md) | CURRENT (lebendes Dokument) | Zentrale Referenz für das Telegram-Inline-Menü-System: Zwei-Ebenen-Routing (PTB-`CallbackQueryHandler`-Pattern + interner `handle_callback()`-Dispatch), bestehender Menübaum, Download-Control-Center (Live-Status, Hard-Cancel, Details) inkl. vier live gefundener/gefixter Bugs, offene Punkte (Download-Verlauf), Muster für künftige Menü-Erweiterungen |

## Metadata Quality Phase

| Datei | Status | Kurzthema |
|---|---|---|
| [archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md](archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md) | HISTORICAL (in Code-Kommentaren referenziert) | Read-Only-Audit — Ursprung der Findings META-01–META-04, META-11 |
| [archive/MusicBot_METADATA_QUALITY_PHASE1_META01_META02_AUDIT.md](archive/MusicBot_METADATA_QUALITY_PHASE1_META01_META02_AUDIT.md) | HISTORICAL (committed) | META-01 + META-02 — `feat.`/`ft.` ohne Leerzeichen nach Punkt wird erkannt |
| [archive/MusicBot_METADATA_QUALITY_PHASE2_META03_AUDIT.md](archive/MusicBot_METADATA_QUALITY_PHASE2_META03_AUDIT.md) | HISTORICAL (committed) | META-03 — hängende schließende Klammer nach Marketing-Suffix-Cleanup entfernt |
| [archive/MusicBot_METADATA_QUALITY_PHASE3_META04_AUDIT.md](archive/MusicBot_METADATA_QUALITY_PHASE3_META04_AUDIT.md) | HISTORICAL (committed) | META-04 — Einzelfall war Tippfehler, kein Bug; ohne Codeänderung geschlossen |
| [archive/MusicBot_METADATA_QUALITY_PHASE4_META11_AUDIT.md](archive/MusicBot_METADATA_QUALITY_PHASE4_META11_AUDIT.md) | HISTORICAL (committed, in Code-Kommentaren referenziert) | META-11 — "video"/"audio" in Klammern kombiniert mit anderen Wörtern wird erkannt |

## Technical Debt Cleanup Reports

| Datei | Status | Kurzthema |
|---|---|---|
| [audits/MAIN_CODEBASE_HEALTH_CHECK_2026-09-03.md](audits/MAIN_CODEBASE_HEALTH_CHECK_2026-09-03.md) | HISTORICAL (committed) | Systematischer Aufräum-/Konsistenz-Check von `main/` (keine Bugsuche): ungenutzte Handler/Adapter/tote APIs, verwaiste Dateien, ungenutzte Scripts, leere Verzeichnisse, historische Artefakte — sauber bis auf 2 nachgetragene Doku-Verweise (PR #130) + 4 entfernte, unreferenzierte Cache-/Import-Platzhalterverzeichnisse |
| [audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md](audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md) | CURRENT (PAUSIERT, siehe `docs/FINDINGS_INDEX.md`) | Fortsetzung des Health Checks auf Funktions-/Methoden-Ebene der 17 Handler/Adapter-Module: 22 bestätigt tote Funktionen/Klassen, 2 UNCERTAIN, 2 echte Funktionslücken (Dashboard-Daten werden nie geschrieben) gefunden — read-only, keine Löschung, pausiert zugunsten des Download-Verlauf-Features |
| [audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md](audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md) | HISTORICAL (committed) | Behebung der in Baseline v6 + `MusicBot_ARCHITECTURE_EVOLUTION.md` (AE-Punkte) offen gelisteten P2/P3-Findings (PR #85–#90): TestMenuHandler INV-01, move_to_library() TOCTOU, pylast-Repr-Secret-Leak, tote Config-Werte (AE-05), CoverProcessor-Metadaten-Atomarität (AE-03), statistics_calculator-Export-Atomarität |
| [audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md](audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md) | HISTORICAL (committed, read-only Audit) | Vollständiger `services/`-Architektur-Audit gegen die Zielarchitektur (PR #92): Schichtgrenzen vollständig sauber verifiziert, 6 priorisierte Migration-Kandidaten (MIG-01–06), vollständige Options-Analyse zu `duplicate/cache.py` INV-01 |
| [audits/DL_RETRY_CLASSIFICATION_2026-09-01.md](audits/DL_RETRY_CLASSIFICATION_2026-09-01.md) | HISTORICAL (committed) | DL-03/DL-05 — Fehlerklassifikation bei Download-/Metadata-Retries verdrahtet (PR #94), nutzt die bereits vorhandene, bis dahin ungenutzte Downloader-Fehlertaxonomie |
| [audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md](audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md) | HISTORICAL (committed) | Characterization-Audit von `process_single_track()` (908 Zeilen, PR #95) — Ergebnis: kein Refactor gerechtfertigt, 2 kleine Aufräum-Fixes umgesetzt |
| [audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md](audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md) | HISTORICAL (committed) | Telegram-Kopplungs-Audit in `services/` (PR #96) — `YoutubeDownloader` hielt das komplette Telegram-`Update`-Objekt, jetzt `chat_id`/`update_id` als einfache Werte |
| [audits/MUSICBRAINZ_RETRIES_DECISION_AUDIT_2026-09-01.md](audits/MUSICBRAINZ_RETRIES_DECISION_AUDIT_2026-09-01.md) | HISTORICAL (committed) | AE-04 — Fachentscheidungs-Audit zu `MUSICBRAINZ_RETRIES` (PR #97), RECOMMENDATION REMOVE, umgesetzt |

## P0 Metadata/Genre/Artist-Mapping/Duplicate-Detection-Audit + P1-Nachfolgeprojekt

| Datei | Status | Kurzthema |
|---|---|---|
| [audits/P0_MAPPING_BASELINE_2026-09-02.md](audits/P0_MAPPING_BASELINE_2026-09-02.md) | HISTORICAL (committed) | P0-A — `mapping/artist_genre.yaml`-Baseline (PR #100): strukturell/inhaltlich sauber, 18 tote Channel-Suffix-Einträge entfernt (172→154) |
| [audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md](audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md) | HISTORICAL (committed) | P0-C — `genre_processor.py` (PR #100): 3 echte Testlücken geschlossen (Channel-Pfad, mb_ids-Anhängung, Feature-Artist-Tie-Breaking), keine Code-Änderung |
| [audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md](audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md) | HISTORICAL (committed) | P0-D — `artist_processor.py` (PR #100): Kernlogik korrekt, 2 Dead-Code-Funde dokumentiert (entfernt in P0-G, PR #101) |
| [audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md](audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md) | HISTORICAL (committed) | P0-E — `detector.py` (PR #100): False-Negative-Bug in der Artist-Normalisierung gefunden und gefixt; architektonische Ursache siehe P1 |
| [audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md](audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md) | HISTORICAL (committed) | P0-F — `cache.py` (PR #100): YouTube-Shorts-URL-Erkennung gefixt |
| [audits/P0_METADATA_DUPLICATE_GESAMTAUDIT_2026-09-02.md](audits/P0_METADATA_DUPLICATE_GESAMTAUDIT_2026-09-02.md) | HISTORICAL (committed) | Gesamtaudit über P0-A–F (PR #100), Freeze-analoge Abschlussentscheidung |
| [audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md](audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md) | HISTORICAL (committed) | P1 — Ursache von P0-E behoben (PR #102): `DuplicateDetector` nutzt jetzt denselben `ArtistProcessor`/`ArtistNormalizer`-Pfad wie die Metadaten-Pipeline; Characterize→Decide→Extract→Audit→Regression |

P0-B (ARTISTNORM-001, bereits behoben bestätigt) hat kein eigenes
Audit-Dokument — direkt in `tests/test_autolearn_special_channel_gate.py`
dokumentiert (Commit `14f40b3`).

## Weitere Einzelfund-Audits

| Datei | Status | Kurzthema |
|---|---|---|
| [MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md](MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md) | CURRENT | Forensischer Architecture Decision Audit für eine zentrale Duplicate-Resolution-Komponente (Pre-Download-Prevention + Post-Download-/Library-Resolution, Album-vs-Single-Priorität) — ARCHITECTURE CONDITIONALLY APPROVED, Grundlage für `services/duplicate/resolution.py`/`classification.py`/`scripts/resolve_duplicates.py` |
| [archive/MusicBot_MB01_ARTIST_MISMATCH_AUDIT.md](archive/MusicBot_MB01_ARTIST_MISMATCH_AUDIT.md) | HISTORICAL (committed) | MB-01 — MusicBrainz-Artist-Mismatch durch Titel-dominierte Gewichtung |
| [archive/MusicBot_TAG01_MULTI_ARTIST_TAG_AUDIT.md](archive/MusicBot_TAG01_MULTI_ARTIST_TAG_AUDIT.md) | HISTORICAL (committed, in Code-Kommentaren referenziert) | TAG-01 — Multi-Artist-`ARTISTS`-Tag wird als separate Werte statt als String geschrieben |
| [archive/MusicBot_TESTENV01_ISOLATION_AUDIT.md](archive/MusicBot_TESTENV01_ISOLATION_AUDIT.md) | HISTORICAL (committed, in Code-Kommentaren referenziert) | TESTENV-01 — `config_test.py` vollständig von Produktionspfaden isoliert |

## ARCH – Architektur-Entscheidungsprotokoll (Historie, in [`docs/archive/arch/`](archive/arch/))

| Datei | Status | Kurzthema |
|---|---|---|
| MusicBot_ARCH-001_Orchestrators.md | HISTORICAL | Große Orchestrator-Klassen |
| MusicBot_ARCH-003_Services_Phase1_Analyse.md | HISTORICAL | Zielarchitektur `services/`, Phase 1 Analyse |
| MusicBot_ARCH-004_P3_Orchestrierungs_Analyse.md | HISTORICAL | Doppelte Spotify/YouTube-Orchestrierung |
| MusicBot_ARCH-005_TempCleanup.md | HISTORICAL | Temp-Cleanup: Analyse, Strategie, Umsetzung |
| MusicBot_ARCH-006_P2_Dependency_Graph.md | HISTORICAL | Import-/Dependency-Graph `services/` |
| MusicBot_ARCH-007_P2_Entkopplungsvorschlag.md | HISTORICAL | Telegram-Entkopplung von `services/` |
| MusicBot_ARCH-008_Navidrome_Adapter_Analyse.md | HISTORICAL | `navidrome_api.py` als Integrationsadapter |
| MusicBot_ARCH-009_Phase1_Bestandsaufnahme.md | HISTORICAL | Ungenutzte `NavidromeAPI`-Methoden |
| MusicBot_ARCH-009_Navidrome_Migrationsplanung.md | HISTORICAL | `NavidromeAPI` Entflechtungs-/Migrationsplanung |
| MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md | HISTORICAL | Navidrome Migration Roadmap |
| MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md | HISTORICAL | `execute_scan()` / Subprocess-Verantwortung |
| MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md | HISTORICAL | Verbleibende Telegram-Präsentationsverantwortlichkeiten |
| MusicBot_ARCH-009_Phase6_Zielposition_DI_Analyse.md | HISTORICAL | Zielposition und DI von `NavidromeAPI` |
| MusicBot_ARCH-009_Phase7_NavidromeAPI_DI.md | HISTORICAL | `NavidromeAPI` auf DI umgestellt |
| MusicBot_ARCH-009_Phase8_Zielverschiebung_ServicesClients_Analyse.md | HISTORICAL | Zielverschiebung `NavidromeAPI` nach `services/clients/` |
| MusicBot_ARCH-009_Phase9_Finaler_Migrationsabschluss_Analyse.md | HISTORICAL | Finaler Migrationsabschluss Navidrome |
| MusicBot_ARCH-009_NavidromeScanTrigger_Zielort_Analyse.md | HISTORICAL | Zielort von `NavidromeScanTrigger` |
| MusicBot_ARCH-010_Downloader_Utils_Migration.md | HISTORICAL | Downloader Utils Migration |
| MusicBot_ARCH-011_Downloader_Download_Analyse.md | HISTORICAL | Architektur-Audit `services/downloader/download/` |
| MusicBot_ARCH-012_Genre_Logic_Characterization.md | HISTORICAL | Genre-Logik Characterization |
| MusicBot_ARCH-013_Genre_Alias_Characterization.md | HISTORICAL | Genre Alias Characterization (Phase 1) |
| MusicBot_ARCH-013_Genre_Alias_Decision.md | HISTORICAL | Fachliche Entscheidung Genre-Alias-Konflikte (Phase 2) |
| MusicBot_ARCH-014_Genre_Specificity_Characterization.md | HISTORICAL | Genre Specificity / Longest-Match |
| MusicBot_ARCH-015_Genre_Canonical_Idempotency_Characterization.md | HISTORICAL | Genre Canonical-Value / Idempotency |
| MusicBot_ARCH-016_Genre_Canonical_Case_Acronym_Characterization.md | HISTORICAL | Genre Canonical-Case / Acronym |
| MusicBot_ARCH-017_Download_Audio_Enhancement_Characterization.md | HISTORICAL | Download-/Audio-Enhancement |
| MusicBot_ARCH-018_Duplicate_Handler_Characterization.md | HISTORICAL | Duplicate Handler |
| MusicBot_ARCH-019_Genre_Client_Logic_Characterization.md | HISTORICAL | Genre Client Logic |
| MusicBot_ARCH-020_Download_Pipeline_Characterization.md | HISTORICAL | Download-Pipeline & Orchestration Boundary |
| MusicBot_ARCH-021_Genre_Client_Duplication_Characterization.md | HISTORICAL | Genre-Client-Duplikation / Last.fm-Cover |

## POST-ARCH – Revalidierungs-Audits (Historie, in [`docs/archive/post-arch/`](archive/post-arch/) bzw. [`docs/archive/`](archive/))

| Datei | Status | Kurzthema |
|---|---|---|
| post-arch/MusicBot_POST-ARCH-009_Audit.md | HISTORICAL | Architektur-Audit nach ARCH-009 |
| post-arch/MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md | HISTORICAL | `bot_restart_handler` Verantwortlichkeitsanalyse |
| post-arch/MusicBot_POST-ARCH-010_011_DuplicateEntry_Analyse.md | HISTORICAL | `DuplicateEntry`-Boundary Folgeanalyse |
| post-arch/MusicBot_POST-ARCH-010_011_Services_Zielarchitektur_Audit.md | HISTORICAL | Services-Zielarchitektur-Audit nach ARCH-010/011 |
| post-arch/MusicBot_POST-DUPLICATEENTRY_Services_Architecture_Audit.md | HISTORICAL | Services Architecture Audit nach DuplicateEntry-Fix |
| MusicBot_SERVICES_Zielarchitektur_Audit.md | HISTORICAL | Services-Zielarchitektur Audit |
| post-arch/POST-ARCH-012_Services_Architecture_Audit.md | HISTORICAL | Services Architecture Audit nach ARCH-012 |
| post-arch/POST-ARCH-013_Services_Architecture_Audit.md | HISTORICAL | Services/Genre Architecture Audit nach ARCH-013 |
| post-arch/POST-ARCH-018_Services_Architecture_Audit.md | HISTORICAL | Services/Architecture Audit nach ARCH-018 |
| POST-SERVICES_PROJECT-WIDE_ARCHITECTURE_AUDIT.md | HISTORICAL | Projektweites Architecture Audit |

## Sonstiges (in [`docs/archive/`](archive/))

| Datei | Status | Kurzthema |
|---|---|---|
| musicbot_REVERSE_ENGINEERED_DOCUMENTATION.md | SUPERSEDED | Reverse-Engineered Projektdokumentation (überschneidet sich mit Baseline) |
| MusicBot_FINDING_4_FORENSIC_AUDIT.md | HISTORICAL | Forensischer Audit zu Finding 4 |
| MusicBot_PHASE4_FAILURE_PATH_AUDIT.md | HISTORICAL | Failure-Path-Audit Phase 4 |
