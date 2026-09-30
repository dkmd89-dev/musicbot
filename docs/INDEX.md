# docs/ – Index

Einstiegspunkt für die Dokumentation. Drei Ebenen:

- **README.md** – Was ist MusicBot? (für Menschen)
- **`docs/MusicBot_ENGINEERING_BASELINE_v13.md`** – Wie war der eingefrorene technische Zustand? (für Wartung/Entwicklung)
- **`docs/FINDINGS_INDEX.md`** – Was ist gerade offen, was ist geschlossen? (lebendes Register)

**Regel:** Im direkten `docs/`-Root liegen ausschließlich **CURRENT**, **LIVING** oder **BASELINE**-Dokumente. Historische Dokumente (Baselines, ARCH-Protokolle, abgeschlossene Phasen, archivierte Audits) liegen unter `docs/archive/`, `docs/archive/arch/` oder `docs/archive/post-arch/`.

**Status-Legende:** **CURRENT** = aktuell gültig, statischer Inhalt · **LIVING** = aktuell gültig, fortlaufend aktualisiert · **BASELINE** = bewusst eingefrorener technischer Referenzpunkt zu einem Freeze-Zeitpunkt · **HISTORICAL** = abgeschlossenes Entscheidungs-/Analyseprotokoll, nicht mehr verändert · **SUPERSEDED** = durch neuere Version abgelöst · **REMOVED** = Funktion entfernt, Dokument als historische Referenz erhalten.

**Ist Finding X gerade offen oder geschlossen?** → [`FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — **die einzige lebende Quelle** für den aktuellen Finding-Stand (Status `OPEN`, `DEFER`, `ACCEPTED RISK`, `CLOSED` sowie sonstige laufende Zustände). Historische Baselines und Audits dokumentieren den Zustand zu ihrem jeweiligen Analyse-/Freeze-Zeitpunkt — sie definieren **nicht** den heutigen Status. Die Tech-Debt-Tabelle in jeder Baseline bleibt ein eingefrorener Schnappschuss zum Freeze-Zeitpunkt.

---

## Aktueller eingefrorener Referenzzustand

| Datei | Status | Kurzthema |
|---|---|---|
| [MusicBot_ENGINEERING_BASELINE_v13.md](MusicBot_ENGINEERING_BASELINE_v13.md) | **BASELINE — FROZEN 2026-09-30, Freeze-Gate APPROVED** | Eingefrorener technischer Referenzpunkt nach v13-Freeze. Umfasst: Mapping-Administration im Control Center (M1–M7, UI 5.0–5.4, Backup/Restore, Runtime-Status, YAML-Editor, Genre-Hierarchie-Editor), Artist Resolution Phase A/B (AR-1/AR-2/AR-3 CLOSED, AR-5/AR-6 DEFER, AR-4 offene Architekturentscheidung), HIER-1. Vollsuite: 7217 passed / 1 skipped / 11 subtests passed / 0 failed. Der laufende Finding-Stand steht ausschließlich in `FINDINGS_INDEX.md`. |
| [archive/MusicBot_ENGINEERING_BASELINE_v12.md](archive/MusicBot_ENGINEERING_BASELINE_v12.md) | BASELINE — FROZEN 2026-09-29 (archiviert) | Vorgänger von v13. Vollsuite (Freeze-Stand): 6576 passed / 1 skipped / 11 subtests passed / 0 failed. |

---

## Aktuelle Root-Dokumente

Alle hier gelisteten Dokumente sind heute gültig und liegen deshalb direkt unter `docs/`.

| Datei | Status | Kurzthema |
|---|---|---|
| [FINDINGS_INDEX.md](FINDINGS_INDEX.md) | **LIVING** | Einzige lebende Quelle für den aktuellen Finding-Stand (OPEN / DEFER / ACCEPTED RISK / CLOSED). Fortlaufend gepflegt, kein Snapshot. Trennt Freeze-Zeitpunkte (historisch) vom aktuellen Finding-Stand. |
| [MusicBot_ARCHITECTURE_EVOLUTION.md](MusicBot_ARCHITECTURE_EVOLUTION.md) | CURRENT (historisches Analyseprotokoll) | Architektur-Invarianten (INV-01–04), Evolution-Kandidaten, ADRs, Closure-Verifikation der Enforcement-Fix-Phase sowie AE-10/AE-11/AE-12 (Abschnitt 29) — Herleitung von v4. **Nicht als Baseline zu lesen** — die darin dokumentierten historischen „NOT READY"-Zustände sind durch AE-10/11/12 geschlossen. |
| [MusicBot_TELEGRAM_MENU_SYSTEM.md](MusicBot_TELEGRAM_MENU_SYSTEM.md) | CURRENT (lebendes Dokument) | Zentrale Referenz für das Telegram-Inline-Menü-System: Zwei-Ebenen-Routing, Menübaum, Download-Control-Center (Live-Status, Hard-Cancel, Verlauf), Bot-Wartungsmodus, Family Hub, Metadata-Reprocessing-Telegram-Anbindung, Muster für künftige Menü-Erweiterungen. |
| [MusicBot_NAVIDROME_MENU_ARCHITECTURE.md](MusicBot_NAVIDROME_MENU_ARCHITECTURE.md) | CURRENT | Navidrome-Menü-System — API-Capability-Matrix, Callback-Matrix, Zielarchitektur. |
| [MusicBot_STATUS_MENU_CLOSURE.md](MusicBot_STATUS_MENU_CLOSURE.md) | CURRENT | Telegram-System-Status-Menü — Closure des `EnhancedStatusHandler`-Routings; wird aktiv aus `handlers/enhanced_status_handler.py`, `handlers/menu/actions/admin_diagnostics.py` und den zugehörigen Tests referenziert und bleibt deshalb im Root. |
| [MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md](MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md) | CURRENT (Architekturentscheidung) | Forensischer Architecture Decision Audit für die zentrale Duplicate-Resolution-Komponente. Wird weiterhin direkt von `services/duplicate/`, `scripts/resolve_duplicates.py` und Tests referenziert und deshalb bewusst im Root belassen. Die dokumentierte „kein Rollback-Versprechen"-Entscheidung (Abschnitt 17) wurde additiv um einen optionalen `backup_fn`-DI-Parameter erweitert (Default `None` = Verhalten unverändert). |
| [LIBRARY_HEALTH.md](LIBRARY_HEALTH.md) | CURRENT | `scripts/library_health_check.py` — vollständig read-only Health-Analyse der Music-Library, versionierter Report (JSON + Text) mit deterministischem Score. Domain in `services/library_health/`. |
| [LIBRARY_REPAIR.md](LIBRARY_REPAIR.md) | CURRENT | `scripts/library_repair.py` / `services/library_repair/` — leitet Reparaturaktionen aus dem Health-Report ab; alle 8 Executoren implementiert; Backup/Rollback-Modell; §10 Telegram-Integration, §11 Library-Maintenance-Consolidation (ARCH-032), §12 Level-2/3-Repair (ARCH-033). |
| [METADATA_REPROCESSING.md](METADATA_REPROCESSING.md) | REMOVED (CC-LIB-FINAL, 2026-09-27) | `scripts/reprocess_artist_metadata.py` und der zugehörige Repair-Level 2 wurden vollständig entfernt — hätten manuell gesetzte Tags überschreiben können. Dokument als historische Referenz erhalten. |
| [GENRE_SYSTEM.md](GENRE_SYSTEM.md) | CURRENT | Genre-Fallback-Kette, Auto-Learn-Konfidenz-Stufen, Lock-in-Mechanismus, Mapping-Dateien-Übersicht, Genre-Learning, bekannte Revalidierungs-Grenze. |
| [CONTROL_CENTER_UI_STANDARD.md](CONTROL_CENTER_UI_STANDARD.md) | CURRENT | Verbindlicher UI-Standard des Control Centers (dunkel + Türkis, Tabler-Icons, Shell, Seitenaufbau, Komponenten, Zustände, Status-Farben, Modal/Toast, Jobs/Pipeline, Logs-Stil, JS-Helfer, DoD je Seiten-PR). |
| [CONTROL_CENTER_REVERSE_PROXY.md](CONTROL_CENTER_REVERSE_PROXY.md) | CURRENT | Betrieb des Control Centers hinter nginx unter dem Subpath `/controlcenter/`. |
| [INDEX.md](INDEX.md) | CURRENT | Diese Datei. |

---

## Aktuelle Audits (`docs/audits/`)

Audits dokumentieren den Zustand zu ihrem Erstellungszeitpunkt. Für den laufenden Finding-Stand ist **immer** `FINDINGS_INDEX.md` maßgeblich — nicht der älteste oder auffälligste Status-Begriff in einem Audit.

### Control Center
- [audits/MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md](audits/MAPPING_ADMIN_CHARACTERIZATION_AND_PROPOSAL_2026-09-29.md) — Mapping-Administration: Inventur, Persistenz-/Reload-Befund, Architekturvorschlag (M1).
- [audits/MAPPING_COMPLETION_PLAN_2026-09-30.md](audits/MAPPING_COMPLETION_PLAN_2026-09-30.md) — Abschlussplan der Mapping-Administration (Schritte 5.0–5.4, B1–B4, Gates G1–G6, Abgleich mit UI-Standard).
- [audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md](audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md) — Architekturvorschlag `control_center/` (FastAPI), API-Design, Auth-Flow, Deployment.
- [audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md](audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md) — Phase-0-Snapshot (bestehende Architektur, Reuse-Kandidaten, Roadmap).
- [audits/CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md](audits/CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md) — CLI/Telegram/Service/Web-Status-Mapping.
- [audits/CONTROL_CENTER_UI_INVENTORY_2026-09-28.md](audits/CONTROL_CENTER_UI_INVENTORY_2026-09-28.md) — CC-UI-0-Snapshot (Seiten-Matrix, U1–U18, offene Entscheidungen).
- [designs/control-center-ui/](designs/control-center-ui/) — Layout-Mockups A/B/C (DRAFT, statische HTML-Mockups, keine Produktionsdateien).

### Library Health & Repair
- [audits/PHASE2_LIBRARY_REPAIR_CLOSURE_AUDIT_2026-09-04.md](audits/PHASE2_LIBRARY_REPAIR_CLOSURE_AUDIT_2026-09-04.md) — Phase-2-Closure (E1–E4-Evidenzstandard, Verdikt 🟡 CONDITIONALLY APPROVED, inzwischen vollständig erfüllt).
- [audits/LIBRARY_REPAIR_P1_P2_P3_CLOSURE_AUDIT_2026-09-08.md](audits/LIBRARY_REPAIR_P1_P2_P3_CLOSURE_AUDIT_2026-09-08.md) — P1–P3-Closure (Verdikt 🟢 APPROVED).
- [audits/ARCH-031_032_LIBRARY_MAINTENANCE_CONSOLIDATION_CLOSURE_2026-09-14.md](audits/ARCH-031_032_LIBRARY_MAINTENANCE_CONSOLIDATION_CLOSURE_2026-09-14.md) — Abschlussbericht ARCH-031/032, Verdikt 🟢 CLOSED.
- [audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md](audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md) — Health-Code → Disposition → Executor → Verifikation für alle 53 Codes.
- [audits/LIBRARY_CLOSURE_AUDIT_2026-09-09.md](audits/LIBRARY_CLOSURE_AUDIT_2026-09-09.md) — Library-Closure-Phase (7 Lücken in 7 PRs geschlossen).
- [audits/CC-LIB-FINAL_PHASE_C_SERVICE_LAYER_AUDIT_2026-09-27.md](audits/CC-LIB-FINAL_PHASE_C_SERVICE_LAYER_AUDIT_2026-09-27.md) — Service-Layer-Funktionsmatrix aller Library-/Metadata-Aktionen.

### Artist-Identity / P0-/P1-Audits
- [audits/P0_MAPPING_BASELINE_2026-09-02.md](audits/P0_MAPPING_BASELINE_2026-09-02.md) — P0-A (`artist_genre.yaml`-Baseline).
- [audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md](audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md) — P0-C (`genre_processor.py`).
- [audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md](audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md) — P0-D (`artist_processor.py`).
- [audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md](audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md) — P0-E (`detector.py`).
- [audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md](audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md) — P0-F (`cache.py`).
- [audits/P0_METADATA_DUPLICATE_GESAMTAUDIT_2026-09-02.md](audits/P0_METADATA_DUPLICATE_GESAMTAUDIT_2026-09-02.md) — Gesamtaudit über P0-A–F.
- [audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md](audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md) — P1 (Ursache P0-E).
- [audits/ARTIST_IDENTITY_RESOLUTION_MIGRATION_2026-09-08.md](audits/ARTIST_IDENTITY_RESOLUTION_MIGRATION_2026-09-08.md) — Artist-Identity-Resolution-Migration (Phase A–F).
- [audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md](audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md) — Vollprojekt-Audit, P1-Fund TGPERM-001 (am selben Tag behoben).

### Technical Debt / Services
- [audits/MAIN_CODEBASE_HEALTH_CHECK_2026-09-03.md](audits/MAIN_CODEBASE_HEALTH_CHECK_2026-09-03.md) — Aufräum-/Konsistenz-Check `main/`.
- [audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md](audits/HANDLER_METHOD_LEVEL_SWEEP_2026-09-03.md) — Funktions-/Methoden-Sweep der Handler/Adapter.
- [audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md](audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md) — Behebung P2/P3-Findings aus v6 + `MusicBot_ARCHITECTURE_EVOLUTION.md`.
- [audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md](audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md) — `services/`-Architektur-Audit.
- [audits/DL_RETRY_CLASSIFICATION_2026-09-01.md](audits/DL_RETRY_CLASSIFICATION_2026-09-01.md) — DL-03/DL-05 Fehlerklassifikation.
- [audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md](audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md) — Characterization `process_single_track()`.
- [audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md](audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md) — Telegram-Kopplungs-Audit `services/`.
- [audits/MUSICBRAINZ_RETRIES_DECISION_AUDIT_2026-09-01.md](audits/MUSICBRAINZ_RETRIES_DECISION_AUDIT_2026-09-01.md) — AE-04 Fachentscheidung.

---

## Historische Baselines (ausschließlich in `docs/archive/`)

Alle vor-v13-Baselines sind eingefroren und abgelöst. Sie liegen unter `docs/archive/` und sind **nicht** als aktueller Zustandsbericht zu lesen — maßgeblich sind `MusicBot_ENGINEERING_BASELINE_v13.md` und für Findings `FINDINGS_INDEX.md`.

- `docs/archive/MusicBot_ENGINEERING_BASELINE_v12.md` — Freeze 2026-09-29, 6576 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v11.md` — Freeze 2026-09-28, 6160 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v10.md` — Freeze 2026-09-14, 4250 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v9.md` — Freeze 2026-09-07, 2580 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v8.md` — Freeze 2026-09-02, 1698 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md` — Freeze 2026-09-01, 1673 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md` — Freeze 2026-09-01, 1634 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md` — Freeze 2026-08-26, 1123 passed.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v4.md` — Freeze 2026-08-26.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` — Freeze 2026-08-25.
- `docs/archive/MusicBot_ENGINEERING_BASELINE_v2.md` — Freeze 2026-08-25.
- `docs/archive/MusicBot_ENGINEERING_BASELINE.md` — v1.

Begleitende historische Analyseartefakte:
- `docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md` — read-only Audit nach v4 (Herleitung v5).
- `docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md` — Freeze-Gate-Audit (initial BLOCKED, nach AE-12-Schließung APPROVED).
- `docs/archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md`, `docs/archive/AE-12_Closure_Audit.md` — Design-/Safety-Audit und Closure-Matrix für AE-12.
- `docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md` — Performance-Charakterisierung nach v3/Phase-4.
- `docs/archive/MusicBot_POST_BASELINE_TRIAGE.md` — Triage vor v3.

---

## Historische Architekturphasen

- **`docs/archive/arch/`** — ARCH-001 bis ARCH-031 (Migrationsprotokolle, Charakterisierungen, Analysepapiere). Einzelauflistung entfällt; die Dateien liegen vollständig erhalten im Verzeichnis. Für die **aktuell gültige** Zielarchitektur der Library-Repair-/Maintenance-Telegram-Integration (ARCH-031/032/033) siehe stattdessen:
  - [docs/LIBRARY_REPAIR.md](LIBRARY_REPAIR.md) §11/§12 — Maintenance-Consolidation + Level-2/3-Repair.
  - `docs/adr/` — Architektur-Entscheidungen Library Repair:
    [0001-library-maintenance-actions-not-finding-driven.md](adr/0001-library-maintenance-actions-not-finding-driven.md),
    [0002-consolidate-repair-script-boilerplate.md](adr/0002-consolidate-repair-script-boilerplate.md),
    [0003-telegram-level2-level3-per-artist-confirmation.md](adr/0003-telegram-level2-level3-per-artist-confirmation.md),
    [0004-shared-run-tracking-module.md](adr/0004-shared-run-tracking-module.md).
  - [docs/audits/ARCH-031_032_LIBRARY_MAINTENANCE_CONSOLIDATION_CLOSURE_2026-09-14.md](audits/ARCH-031_032_LIBRARY_MAINTENANCE_CONSOLIDATION_CLOSURE_2026-09-14.md) — Abschlussbericht.
  - [docs/FINDINGS_INDEX.md](FINDINGS_INDEX.md) — lebender Stand (z. B. ARCH-034/035 noch offen).

  Einzelne ARCH-Phasen (021/023/024/025/026–030) werden in den aktuellen technischen Referenzen nur noch indirekt erwähnt; ihre **aktuellen** Ergebnisse sind in den Modulen `handlers/menu/*` und `handlers/enhanced_error_handler.py` (Code) sowie in `MusicBot_TELEGRAM_MENU_SYSTEM.md` (Verhalten) dokumentiert.

- **`docs/archive/post-arch/`** — POST-ARCH-009 bis POST-ARCH-018 (Revalidierungs-Audits).

---

## Historische Phasen (in `docs/archive/`)

- `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md` — Umbrella-Phase (Download-Pipeline- und Duplicate-Detection-Stabilität). Der einzige dort noch als akzeptiertes Risiko offene Punkt (Hard-Cancel während FFmpeg-Postprocessing, P3) steht in [FINDINGS_INDEX.md](FINDINGS_INDEX.md).
- `docs/archive/MusicBot_PHASE3_MUSIC_QUALITY_LIBRARY_INTELLIGENCE.md` — Phase 3 (Library Statistics, Navidrome-Scan-Automation, MusicBot Doctor, Import-History-Checkliste, Bad-Download-Detector Stufe A; Abgleich gegen externen „Musicbot.md"-Ideenkatalog).
- `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md` … `...PHASE2N_RES01_AUDIT.md` — Audits der Download-Pipeline-Stabilitätsphase, in Code-Kommentaren referenziert.
- `docs/archive/MusicBot_METADATA_QUALITY_PHASE0_AUDIT.md` … `...PHASE4_META11_AUDIT.md` — Metadata-Quality-Phase (META-01–META-04, META-11).
- `docs/archive/MusicBot_MB01_ARTIST_MISMATCH_AUDIT.md`, `docs/archive/MusicBot_TAG01_MULTI_ARTIST_TAG_AUDIT.md`, `docs/archive/MusicBot_TESTENV01_ISOLATION_AUDIT.md` — Einzelfund-Audits.
- `docs/archive/MusicBot_SERVICES_Zielarchitektur_Audit.md`, `docs/archive/POST-SERVICES_PROJECT-WIDE_ARCHITECTURE_AUDIT.md`, `docs/archive/musicbot_REVERSE_ENGINEERED_DOCUMENTATION.md`, `docs/archive/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md`, `docs/archive/MusicBot_FINDING_4_FORENSIC_AUDIT.md` — Sonstiges.
- `docs/archive/METADATA_REPROCESSING_TEST_CHAPO102.md`, `docs/archive/METADATA_REPROCESSING_TEST_NINA_CHUBA.md` — Validierungsprotokolle Metadata-Reprocessing-Tool.
- `docs/prompts/Claude-Code-Production-Prompt v2.md` — historischer, phasenspezifischer Produktionsprompt für den Library Health Scanner (Phase 1). Kein aktueller/genereller Arbeitsauftrag.

---

## Zur Traceability in Code-/Test-Kommentaren referenzierte Dateien

Die Pfade der Download-Pipeline-Stability-, Metadata-Quality- und Einzelfund-Audits werden aus Code-Kommentaren und Testdatei-Docstrings zitiert (z. B. `# DL-01 (docs/archive/MusicBot_..._AUDIT.md): ...`). Beim Verschieben nach `docs/archive/` wurden alle betroffenen Referenzen in Code-Kommentaren, Test-Docstrings und Cross-References zwischen den Dokumenten selbst mit umgezogen.
