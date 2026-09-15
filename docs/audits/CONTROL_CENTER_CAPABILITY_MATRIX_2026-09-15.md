# MUSICBOT CONTROL CENTER — CAPABILITY MATRIX (Phase 1)

**Datum:** 2026-09-15
**Auftrag:** MUSICBOT_CONTROL_CENTER.txt, Abschnitt 34 (Phase 1) / Abschnitt 22.
**Basis:** Konsolidierung der Inventories aus `docs/audits/CONTROL_CENTER_ARCHITECTURE_AUDIT_2026-09-15.md` (Abschnitte 3–5), keine neue Recherche. Web-Spalte ergänzt um konkrete Zielendpunkt-Vorschläge aus Abschnitt 8 des Audits.

**Legende Status:** 🟢 bereits serviceorientiert, direkt wiederverwendbar · 🟡 Service vorhanden, dünne API-Hülle nötig · 🟠 Service-Extraktion/Umbau nötig · ⚪ bewusst nicht für Web vorgesehen

---

## 1. Download

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Download starten | — | `dl:` | `klassen/download_handler.py` + `services/downloader/*` | `POST /api/v1/downloads` (als Job) | Mittel | 🟠 — Handler ist Orchestrator mit Telegram-Objekten (klassen/-Schicht laut CLAUDE.md §4 bewusst so), Web braucht eigene dünne Schicht darüber |
| Download-Status/Fortschritt | — | `dl:` Status-Callback | `services/downloader/active_downloads.py::ActiveDownloadRegistry` | `GET /api/v1/downloads`, `GET /api/v1/downloads/{id}` | Niedrig | 🟢 bereits Telegram-freies Registry-Objekt |
| Download-Verlauf | — | `dl:` Verlauf-Callback | `services/downloader/download_history.py::DownloadHistoryStore` | `GET /api/v1/downloads/history` | Niedrig | 🟢 |
| Download abbrechen (Hard-Cancel) | — | `dl:` Cancel-Callback | `ActiveDownloadRegistry` (`threading.Event`) | `POST /api/v1/downloads/{id}/cancel` | Niedrig | 🟢 |
| Download Retry | — | `dl:` Retry-Callback | über `klassen/download_handler.py` | `POST /api/v1/downloads/{id}/retry` | Mittel | 🟠 gleiche Einschränkung wie „Download starten" |

## 2. Metadata

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Metadata-Pipeline (Artist/Title/Genre/Lyrics/Cover/Album/Tags) | — | implizit bei jedem Download | `services/metadata/enhanced_metadata_processor.py::EnhancedMetadataProcessor` | keine direkte API — nur indirekt über Download-/Reprocessing-Jobs sichtbar | — | 🟢 als Service, ⚪ kein eigener Endpunkt geplant (kein direkter Nutzerinput im MVP-Scope) |
| Artist-Metadata-Reprocessing | `scripts/reprocess_artist_metadata.py` | `reprocess:` (OWNER-only) | `services/metadata/track_reprocessor.py` | `POST /api/v1/metadata/reprocess` (als Job, Subprozess-Modell aus `docs/METADATA_REPROCESSING.md` §2a beibehalten) | Mittel | 🟡 Service fertig, Job-Abstraktion (Audit Abschnitt 7.1) ist Voraussetzung |
| Genre-Revalidierung | `scripts/revalidate_genre.py` | Genre-Menü | `services/metadata/genre_processor.py` + Auto-Learn | `POST /api/v1/metadata/genre/revalidate` (als Job) | Mittel | 🟡 — Skript neu (Commit `63e4463`), vor Web-Anbindung eigene kurze Sichtung empfohlen (siehe Audit Abschnitt 3) |
| Fehlende Genres anzeigen/setzen | — | Genre-Menü, manuelle Eingabe | `services/metadata/genre_processor.py` | `GET/POST /api/v1/metadata/genre/missing` | Mittel | 🟠 aktuell nur als Telegram-Dialog modelliert, Web bräuchte strukturierte Liste+Formular |
| Loudness/ReplayGain (Test-Library) | `scripts/normalize_test_library_loudness.py` | — | `services/metadata/loudness_replaygain.py` | — | — | ⚪ bewusst CLI-only, arbeitet explizit gegen Test-Library, kein Produktionswerkzeug |

## 3. Duplicate Detection

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Duplicate-Erkennung (URL/ID/Artist-Titel/Parser/Library) | — | implizit bei jedem Download | `services/duplicate/*` | keine direkte API (Teil der Download-Pipeline) | — | 🟢 als Service |
| Duplicate-Resolution (manuell) | `scripts/resolve_duplicates.py` | — | `services/duplicate/resolution.py`, `execution.py`, `classification.py` | `POST /api/v1/duplicates/resolve` (Preview → Confirm → Execute, Master-Prompt Regel 21) | Mittel | 🟡 Service vorhanden, Preview/Confirm-API-Contract fehlt noch |
| Duplicate-Statistik | — | `dup:` | vermutlich `services/duplicate/*` (Cache-Stats) | `GET /api/v1/duplicates/stats` | Niedrig | 🟢 |
| Duplicate-Cache leeren | — | `dup:` (ADMIN) | `services/duplicate/*` | `POST /api/v1/duplicates/cache/clear` | Niedrig | 🟢 — destruktiv, braucht Confirm-Flow trotz einfacher Umsetzung |

## 4. Library Health / Repair

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Health-Scan (read-only) | `scripts/library_health_check.py` | `doctor:`, `review:` | `services/library_health/scanner.py::run_scan`, `report.py::build_report_dict` | `GET /api/v1/health/library` — **MVP-Kandidat #1** | Niedrig | 🟢 vollständig Telegram-frei, direkt aufrufbar |
| Findings anzeigen/filtern | `scripts/library_health_review.py` | `review:` | `services/library_health/findings.py::FindingsRegistry`, `group_open_findings_by_category` | `GET /api/v1/library/findings` — **MVP-Kandidat #2** | Niedrig | 🟢 |
| Finding akzeptieren/zurücknehmen | `scripts/library_health_review.py` | `review:` | `findings.py::accept_finding/unaccept_finding` | `POST /api/v1/library/findings/{id}/accept`, `.../unaccept` | Niedrig | 🟢 |
| Review-Summary | `scripts/library_health_review.py` | `review:` | `findings.py::get_review_summary` | `GET /api/v1/library/findings/summary` | Niedrig | 🟢 |
| Repair-Preview (Dry-Run) | `scripts/library_repair.py` | `repair:` | `services/library_repair/planner.py`, `executor.py` | `POST /api/v1/library/repairs/preview` | Mittel | 🟡 Service fertig (Dry-Run-Default bereits vorhanden), CLI-Orchestrierung selbst nicht 1:1 übertragbar |
| Repair-Ausführung | `scripts/library_repair.py` | `repair:` | `executor.py` (8 Executoren, Backup, Rollback, Journal) | `POST /api/v1/library/repairs` (als Job, Preview→Confirm→Execute→Verify Pflicht) | Mittel | 🟡 — Job-Abstraktion (Audit Abschnitt 7.1) Voraussetzung für async Ausführung |
| Verification nach Repair | `scripts/library_repair.py` | `repair:` | `services/library_repair/run_tracking.py` (`_verify_issue_resolved`) | `GET /api/v1/library/repairs/{id}/verification` | Niedrig | 🟢 |
| MusicBot Doctor (Scan+Auto-Repair kombiniert) | — | `doctor:` | `services/library_repair/doctor_runner.py` | `POST /api/v1/library/doctor` (als Job) | Mittel | 🟡 Subprozess-Muster bereits etabliert, als Job-Vorbild nutzbar |
| Library-Wartung (Artist-Casing/Genre) | — | `libmaint:` | `services/library_repair/artist.py`, `genre.py` | `POST /api/v1/library/maintenance/*` | Mittel | 🟡 |

## 5. Statistics

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Top Songs/Artists, Zeiträume | — | `menu:stats_*` | `services/statistik/`, `services/statistik_service.py` | `GET /api/v1/statistics/*` | Niedrig–Mittel | 🟢 Berechnungslogik vorhanden; für Web Rohdaten statt gerendertem Chart-Bild abgreifen (`statistics_calculator.py`, `play_history_repository.py`) |
| Family-Statistik | — | `menu:family_*` | `services/family/` | — | — | ⚪ laut Master-Prompt Abschnitt 23 eher Telegram-Stärke, kein MVP-Kandidat |

## 6. Navidrome

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| Scan/Status/Suche | — | `nav_` | `services/clients/navidrome_api.py` | `GET /api/v1/navidrome/status`, `GET /api/v1/navidrome/search` | Niedrig | 🟢 fertiger Subsonic-Adapter |
| Lokaler Scan-Trigger | — | intern (nach Doctor) | `utils/navidrome_scan_trigger.py` | `POST /api/v1/navidrome/scan` | Niedrig | 🟢 |

## 7. Admin / System

| Capability | CLI | Telegram | Service | Web (Ziel) | Aufwand | Status |
|---|---|---|---|---|---|---|
| System-Status (Dashboard) | — | `status_` | verteilt (kein einzelner Service) | `GET /api/v1/system/status` | Mittel | 🟠 — muss laut Audit Abschnitt 8 neu zusammengeführt werden (Bot/Navidrome/Library/Worker-Status als eine Antwort) |
| Backup (Bot/Library) | — | `backup_` | `handlers/admin/backup_handler.py` | `POST /api/v1/admin/backups` | Mittel | 🟠 Handler-gebunden, Service-Extraktion sinnvoll vor Web-Nutzung |
| Bot-Neustart | — | `restart:` | `utils/bot_restart_trigger.py` | — | — | ⚪ Lifecycle-Aktion, Web-Exposition laut Audit Abschnitt 4 bewusst vorerst nicht vorgesehen (Niedrig-Priorität, hohes Blast-Radius-Risiko) |
| Wartungsmodus | — | `maint:` | Flag-basiert (kein echter Prozess-Stop) | `POST /api/v1/admin/maintenance-mode` | Niedrig | 🟢 |
| Nutzerverwaltung | — | `usermgmt_` | `handlers/admin/user_management_handler.py` (JSON-Store) | `GET/POST /api/v1/admin/users` | Mittel | 🟠 Handler-gebunden, Service-Extraktion nötig (siehe Audit Abschnitt 5/10) |
| Logger-Verwaltung | — | `logger_` | `handlers/enhanced_logger_menu_handler.py` | `GET /api/v1/admin/logs` | Mittel | 🟠 Handler-gebunden — außerdem strikt gegen Secret-Exposure prüfen (CLAUDE.md §12) |
| Fehler-Administration | — | `erradmin:` | `handlers/enhanced_error_handler.py` | `GET /api/v1/admin/errors` | Mittel | 🟠 Handler-gebunden |
| Test-System (Unit/Integration/Performance) | — | `menu:test_*` | Subprozess-Aufruf, bis 900s | — | — | ⚪ **nicht für Web vorgesehen** — DoS-Risiko bereits einmal dokumentiert (TGPERM-001), Web-Exposition bräuchte eigene Rate-Begrenzung, kein MVP-Kandidat |

---

## Zusammenfassung nach Aufwand (für Roadmap-Priorisierung)

- **🟢 Niedrig, sofort webfähig (kein Umbau):** Library-Health-Scan, Findings-Browser (inkl. Accept/Unaccept/Summary), Download-Status/Verlauf/Cancel, Duplicate-Stats/Cache-Clear, Navidrome-Status/Suche/Scan-Trigger, Wartungsmodus-Toggle.
- **🟡 Mittel, Service fertig aber API-Hülle/Job-Abstraktion nötig:** Repair-Preview/-Ausführung, Doctor, Metadata-Reprocessing, Genre-Revalidierung, Duplicate-Resolution, Library-Wartung.
- **🟠 Umbau/Service-Extraktion vor Web-Nutzung sinnvoll:** Download-Start/Retry (klassen/-Orchestrierung), System-Status-Dashboard (Zusammenführung nötig), Backup, Nutzerverwaltung, Logger-Verwaltung, Fehler-Administration (alle vier: Handler-gebunden statt reiner Service).
- **⚪ Bewusst nicht für Web-MVP vorgesehen:** Bot-Neustart, Test-System-Ausführung, Loudness-Normalisierung (Test-Tooling), Family-Statistik (Telegram-Stärke).

Diese Einordnung deckt sich mit dem MVP-Vorschlag aus dem Phase-0-Audit (Abschnitt 9): Health-Scan und Findings-Browser sind die einzigen beiden Capabilities, die ohne Job-Abstraktion und ohne Service-Umbau sofort einen vollständigen vertikalen Web-Pfad ergeben.
