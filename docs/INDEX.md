# docs/ – Index

Einstiegspunkt für die Dokumentation. Drei Ebenen (siehe README.md für Details):

- **README.md** – Was ist MusicBot? (für Menschen)
- **ENGINEERING_BASELINE** – Wie ist der aktuelle technische Zustand? (für Wartung/Entwicklung)
- **ARCH-xxx / POST-ARCH-xxx** – Warum wurde eine Architekturentscheidung getroffen? (Historie, unverändert)

Status-Legende: **CURRENT** = aktuell gültig · **HISTORICAL** = abgeschlossenes Entscheidungsprotokoll, nicht mehr verändert · **SUPERSEDED** = durch neuere Version abgelöst

## Baseline

| Datei | Status | Kurzthema |
|---|---|---|
| MusicBot_ENGINEERING_BASELINE_v2.md | CURRENT (eingefroren nach Closure 2026-08-25) | Aktueller technischer Gesamtzustand — neue Findings → MusicBot_ENGINEERING_BASELINE_v3.md |
| MusicBot_ENGINEERING_BASELINE.md | SUPERSEDED | v1, abgelöst durch v2 |

## ARCH – Architektur-Entscheidungsprotokoll (Historie)

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

## POST-ARCH – Revalidierungs-Audits (Historie)

| Datei | Status | Kurzthema |
|---|---|---|
| MusicBot_POST-ARCH-009_Audit.md | HISTORICAL | Architektur-Audit nach ARCH-009 |
| MusicBot_POST-ARCH-009_P1_BotRestart_Analyse.md | HISTORICAL | `bot_restart_handler` Verantwortlichkeitsanalyse |
| MusicBot_POST-ARCH-010_011_DuplicateEntry_Analyse.md | HISTORICAL | `DuplicateEntry`-Boundary Folgeanalyse |
| MusicBot_POST-ARCH-010_011_Services_Zielarchitektur_Audit.md | HISTORICAL | Services-Zielarchitektur-Audit nach ARCH-010/011 |
| MusicBot_POST-DUPLICATEENTRY_Services_Architecture_Audit.md | HISTORICAL | Services Architecture Audit nach DuplicateEntry-Fix |
| MusicBot_SERVICES_Zielarchitektur_Audit.md | HISTORICAL | Services-Zielarchitektur Audit |
| POST-ARCH-012_Services_Architecture_Audit.md | HISTORICAL | Services Architecture Audit nach ARCH-012 |
| POST-ARCH-013_Services_Architecture_Audit.md | HISTORICAL | Services/Genre Architecture Audit nach ARCH-013 |
| POST-ARCH-018_Services_Architecture_Audit.md | HISTORICAL | Services/Architecture Audit nach ARCH-018 |
| POST-SERVICES_PROJECT-WIDE_ARCHITECTURE_AUDIT.md | HISTORICAL | Projektweites Architecture Audit |

## Sonstiges

| Datei | Status | Kurzthema |
|---|---|---|
| musicbot_REVERSE_ENGINEERED_DOCUMENTATION.md | SUPERSEDED | Reverse-Engineered Projektdokumentation (überschneidet sich mit Baseline) |
