# MUSICBOT CONTROL CENTER — ARCHITECTURE AUDIT (Phase 0)

**Datum:** 2026-09-15
**Repository:** dkmd89-dev/musicbot
**Auftrag:** MUSICBOT_CONTROL_CENTER.txt (Master-Prompt), Abschnitt 43/44 — Phase 0: vollständiger Repository-Audit vor jeder Implementierung.
**Modus:** Read-only. Keine Code-/Config-/Mapping-Änderungen, keine neuen Dependencies, keine Commits.
**Methodik:** Lesen von CLAUDE.md, README.md, bot.py, config.py, vollständige Verzeichnisstruktur von handlers/, services/ (inkl. clients/), klassen/, helfer/, mapping/, scripts/, utils/, requirements*.txt; gezielte Greps über Auth-/Permission-Code, Job-/Task-Muster, Web-Framework-Abhängigkeiten; Auswertung bestehender Architektur-Dokumentation (docs/INDEX.md, docs/FINDINGS_INDEX.md, docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md, docs/MusicBot_ENGINEERING_BASELINE_v10/v11.md, docs/MusicBot_TELEGRAM_MENU_SYSTEM.md, docs/LIBRARY_HEALTH.md, docs/LIBRARY_REPAIR.md, docs/GENRE_SYSTEM.md). Volle Testsuite wurde **nicht** ausgeführt (CLAUDE.md §8.A — bleibt dem Nutzer vorbehalten); `pytest --collect-only` bereits durch das referenzierte Audit vom 2026-09-12 mit 3264 gesammelten Tests bestätigt, aktueller Teststand laut docs/INDEX.md (v11-DRAFT): 4310 passed / 1 skipped / 11 subtests passed / 0 failed.

**Wichtiger Hinweis zur Methodik:** Ein sehr aktuelles, vollständiges Read-only-Architektur-Audit des Gesamtprojekts existiert bereits (`docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md`, Commit `3e136b1`, drei Tage alt). Dieses Dokument dupliziert dessen Tiefenanalyse nicht, sondern baut explizit darauf auf und ergänzt nur die für das Control Center spezifische Perspektive (CLI/Telegram/Admin-Inventory, Reuse-Bewertung, API-Vorschlag, MVP). Wo das Referenz-Audit bereits ein Urteil gefällt hat (z. B. Schichtgrenzen, God-Handler, Security-Score), wird es zitiert statt neu hergeleitet.

---

## 1. Current Architecture

```text
Telegram Update
    ↓
bot.py (Entry Point, async_main, Signal-Handling)
    ↓
RichMenuHandler (handlers/menu/rich_menu_handler.py)
    ↓
RichMenuSystem.handle_callback() (handlers/menu/rich_menu_system.py)
    ↓
Prefix-Dispatch (dl:/backup_/maint:/reprocess:/doctor:/review:/repair:/
    erradmin:/status_/dup:/usermgmt_/nav_/libmaint:) → dedizierter
    Dispatcher pro Bereich, jeweils eigener Berechtigungscheck
    ODER generischer menu:<id>-Fallback → menu_item.handler(update, context)
    ↓
Zielmethode (Handler-Klasse in handlers/, handlers/admin/,
    handlers/menu/actions/, oder klassen/download_handler.py)
    ↓
Services (services/*) → services/clients/* (externe APIs) |
    utils/* (lokale Subprozesse)
    ↓
Filesystem / Library / Navidrome
```

Es existiert **eine einzige Bedienoberfläche**: Telegram. Es gibt **keine** CLI im Sinne eines interaktiven, für Endnutzer gedachten Kommandozeilen-Interfaces zum Bot selbst — `scripts/` enthält stattdessen sieben eigenständige, manuell gestartete Wartungstools mit `argparse`-Parsern (siehe Abschnitt 3), die laut CLAUDE.md §4 ausdrücklich **keine Laufzeit-Schicht** sind. Es existiert **keine Web-Technologie** im Repository — kein Treffer für FastAPI/Flask/aiohttp-Server/Starlette/Django/uvicorn/gunicorn/Sanic/Bottle in `requirements.txt` oder `requirements-dev.txt`. `aiohttp` ist vorhanden, aber ausschließlich als HTTP-**Client** in zwei Modulen (`services/clients/genius_client.py`, `services/metadata/enhanced_metadata_processor.py`), nicht als Server-Framework.

Die Schichtgrenzen aus CLAUDE.md §4 sind aktuell (bestätigt durch das Referenz-Audit vom 2026-09-12, dort Abschnitt 3/4): `services/` ist frei von Telegram-Importen bis auf die dokumentierte `klassen/`-Ausnahme; `services/clients/` enthält ausschließlich externe Netzwerkadapter; `utils/` ausschließlich lokale Subprozess-/Cache-Module. Ein automatisierter Regressionstest (`tests/test_services_layer_boundary.py`, AST-basiert) erzwingt das bereits.

**Auth-/Permission-Modell (für das Control Center zentral relevant):** Vollständig Telegram-User-ID-basiert, in `config.py` verankert (`OWNER_USER_ID`, `ADMIN_USER_IDS` aus `.env`) und in `handlers/menu/permissions.py` zu zwei reinen, Telegram-freien Funktionen konsolidiert:
- `is_admin_or_owner(user_id: int, config) -> bool`
- `get_user_access_level(user_id: int, config, user_mgmt_handler) -> AccessLevel`

`AccessLevel` ist ein einfaches 5-stufiges Enum (`handlers/menu/models.py`): `PUBLIC=0, USER=1, MODERATOR=2, ADMIN=3, OWNER=4`. Es existiert **kein** granulares Permission-System (keine einzelnen Capabilities/Scopes), sondern eine feste Rollenhierarchie. Rollen jenseits von Owner/Admin (Moderator, User) werden zusätzlich in einem JSON-Userdaten-Store gepflegt (`handlers/admin/user_management_handler.py`, `user_data_cache`).

---

## 2. Existing Capabilities

Aus dem Referenz-Audit (2026-09-12) und der aktuellen Verzeichnisstruktur zusammengefasst — vollständige Details siehe README.md und `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md`:

- **Download:** YouTube-Download (Einzeltrack/Playlist) über `klassen/download_handler.py` + `services/downloader/*`, Live-Status/Fortschritt, Hard-Cancel, persistenter Verlauf mit Metadata-Checkliste (`DownloadHistoryStore`), prozessweite `ActiveDownloadRegistry` (thread-safe, Cancel via `threading.Event`).
- **Metadata-Pipeline:** `EnhancedMetadataProcessor` als Facade über Artist/Title/Genre/Lyrics/Cover/Album/ReplayGain/Tags — vollständig charakterisiert, siehe Referenz-Audit Abschnitt 10–13.
- **Duplicate Detection:** mehrstufige Kaskade (URL → In-Flight → Content-Hash → Parser-Fallback → Library-Fallback), `services/duplicate/*`.
- **Library Health:** read-only Scanner (`services/library_health/`, `scripts/library_health_check.py`) mit deterministischem Health-Score und JSON+Text-Report.
- **Library Repair:** Planner + 8 Executoren mit Per-Datei-Backup, Rollback, Append-Only-Journal, Disposition-Matrix (AUTO_REPAIR/MANUAL_REVIEW/UNREPAIRABLE) für alle 53 Health-Codes (`services/library_repair/`, `docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md`). Vollständig auch über Telegram bedienbar (ARCH-031/032/033: Level 1–3, Pro-Artist, Library-Wartung).
- **MusicBot Doctor:** kombinierter Health-Scan + SAFE_AUTOMATIC-Repair als Subprozess-Orchestrierung (`services/library_repair/doctor_runner.py`), triggert automatisch Navidrome-Scan danach.
- **Genre-Management:** manuelle Eingabe, `--only-if-missing`-Reprocessing, „Fehlende Genres"-Einstieg, kontrollierte Revalidierung (`scripts/revalidate_genre.py`, neuester Commit `63e4463`).
- **Statistik:** `services/statistik/` + `services/statistik_service.py` (Top Songs/Artists, Zeiträume, Charts als Bild), Family-Statistik als eigene Erweiterung, die dieselbe Infrastruktur wiederverwendet.
- **Navidrome-Integration:** `services/clients/navidrome_api.py` (Subsonic-API: Scan, Status, Suche), `utils/navidrome_scan_trigger.py` (lokaler Subprozess-Trigger).
- **Admin/Maintenance:** Backup (Bot+Library), Bot-Neustart, Wartungsmodus (Flag-basiert, kein echter Prozess-Stop), Logger-Verwaltung (Modul-Level, Dateien, Bereinigung), Fehler-Administration (`erradmin:`), Nutzerverwaltung (Rollen/Rechte/Bann), Test-System (Unit/Integration/Performance-Testläufe als Subprozess, bis 900s).
- **Family Hub:** Statistik/Chat/Challenge für explizit konfigurierte Familienmitglieder, eigene Service-Schicht (`services/family/`), Telegram-frei.
- **Job-/Task-System:** **existiert nicht als eigenständige Abstraktion.** Lange Operationen laufen entweder als synchrone `asyncio.to_thread`/`asyncio.create_subprocess_exec`-Aufrufe direkt im Telegram-Callback (z. B. `doctor_runner.py`, Testläufe) oder als vom Nutzer manuell gestartete `scripts/*.py`-Subprozesse. Es gibt keinen zentralen Job-Store mit ID/Status/Progress/Initiator/Cancellation außerhalb des sehr spezifischen `ActiveDownloadRegistry`/`DownloadHistoryStore`-Musters für Downloads. Siehe Abschnitt 7 (Missing Abstractions).

---

## 3. CLI Inventory

| CLI-Funktion | Datei | Service/Command dahinter | Web möglich | Aufwand | Status |
|---|---|---|---|---|---|
| `library_health_check.py` | `scripts/library_health_check.py` | `services/library_health/*` (bereits reiner Service, keine Telegram-Kopplung) | Ja, direkt | Niedrig | bereits serviceorientiert, direkt wiederverwendbar |
| `library_health_review.py` | `scripts/library_health_review.py` | `services/library_repair/findings.py` (`accept/unaccept/get_review_summary`) | Ja, direkt | Niedrig | bereits serviceorientiert |
| `library_repair.py` | `scripts/library_repair.py` | `services/library_repair/executor.py`, `planner.py`, `run_tracking.py`, `artist.py`, `genre.py` (7 Executoren + Maintenance-Actions) | Teilweise — Executor-Aufrufe ja; Skript selbst hat CLI-spezifische Orchestrierung (Dry-Run-Default, Confirm-Flags) die für eine Web-API neu modelliert werden müsste | Mittel | Kern bereits serviceorientiert, CLI-Layer selbst nicht 1:1 übertragbar |
| `resolve_duplicates.py` | `scripts/resolve_duplicates.py` | `services/duplicate/resolution.py`, `execution.py`, `classification.py` | Ja, mit API-Schicht für Preview/Confirm | Mittel | Service vorhanden, destruktive Aktion braucht Preview/Confirm-Contract (siehe Regel 21 Master-Prompt) |
| `reprocess_artist_metadata.py` | `scripts/reprocess_artist_metadata.py` | `services/metadata/track_reprocessor.py` (laut FINDINGS_INDEX/PR #148 bereits ausgelagert) | Ja, als Job | Niedrig–Mittel | bereits serviceorientiert; Ausführung selbst läuft laut `docs/METADATA_REPROCESSING.md` §2a bewusst als **Subprozess** (SingletonMixin-Risiko bei In-Process-Aufruf) — dieses Modell muss für eine Web-API übernommen werden, nicht umgangen |
| `revalidate_genre.py` | `scripts/revalidate_genre.py` | Genre-Pipeline (`services/metadata/genre_processor.py` + Auto-Learn) | Ja, als Job | Mittel | neu (letzter Commit `63e4463`), noch nicht im Referenz-Audit erfasst — vor Wiederverwendung eigene kurze Sichtung empfohlen |
| `normalize_test_library_loudness.py` | `scripts/normalize_test_library_loudness.py` | `services/metadata/loudness_replaygain.py` | Nein (arbeitet laut Namen explizit gegen eine **Test-Library**, kein Produktionswerkzeug) | — | bewusst CLI-only / Test-Tooling, kein Control-Center-Kandidat |

**Wichtige Randbedingung für alle Web-Integrationen dieser Skripte:** Mehrere Skripte tragen dokumentierte Path-Safety-Guards und strikte Read-Only-Regeln gegen die Produktion (CLAUDE.md §4 „scripts/"). Eine Web-API darf diese Guards nicht umgehen, sondern muss denselben Sicherheitsstandard (Preview → Confirm → Execution → Verification, Master-Prompt Abschnitt 21) mindestens einhalten.

---

## 4. Telegram Inventory

Vollständige Menü-/Callback-Matrix bereits erschöpfend dokumentiert in `docs/audits/FULL_PROJECT_ARCHITECTURE_AUDIT_2026-09-12.md` Abschnitt 6 (Telegram Callback Matrix, ~25 Zeilen) und `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md`. Zusammengefasst nach Funktionsbereich, mit Bezug zur RBAC-Ebene:

| Bereich | Access Level | Beispiel-Präfix | Web-Eignung |
|---|---|---|---|
| Downloads (Start/Status/Cancel/Retry/Verlauf) | USER, chat_id-skopiert | `dl:` | Hoch — klassischer Kandidat für Download Center |
| Statistik (Monat/Jahr/Top/Timeline) | USER | `menu:stats_*` | Hoch |
| Family Hub (Statistik/Chat/Challenge) | USER + Membership-Gate | `menu:family_*` | Mittel (eher Telegram-Stärke laut Master-Prompt Abschnitt 23) |
| Navidrome Browse/Suche/Playlists | bewusst ungegated (reines Browsing) | `nav_` | Hoch |
| Nutzerverwaltung | ADMIN zentral | `usermgmt_` | Hoch — klassischer Admin-Center-Kandidat |
| System-Status | ADMIN zentral | `status_` | Hoch — Dashboard-Kandidat |
| Duplikate (Stats/Cache leeren) | ADMIN zentral | `dup:` | Hoch |
| Error-Verwaltung | ADMIN eigener Check | `erradmin:` | Hoch |
| Logger-Verwaltung | ADMIN (seit TGPERM-001-Fix korrekt gegated) | `logger_` (jetzt explizites `callback_data`) | Hoch — klassischer Logs/Diagnostics-Kandidat |
| Backup | ADMIN zentral | `backup_` | Mittel (destruktiv-nah, Bulk) |
| Bot-Neustart | ADMIN eigener Check | `restart:` | Niedrig — Lifecycle-Aktion, Web-Exposition sorgfältig prüfen |
| Wartungsmodus | ADMIN eigener Check | `maint:` | Mittel |
| Reprocessing | **OWNER** eigener Check | `reprocess:` | Mittel — Owner-only beibehalten |
| MusicBot Doctor | ADMIN eigener Check | `doctor:` | Hoch — Health/Repair-Kandidat |
| Library Health Review | ADMIN eigener Check | `review:` | Hoch |
| Repair MusicBot | ADMIN eigener Check | `repair:` | Hoch — zentraler Library-Repair-Kandidat |
| Library-Wartung (Artist-Casing/Genre) | ADMIN (`libmaint:`) | `libmaint:` | Hoch |
| Test-System | ADMIN (seit TGPERM-001-Fix korrekt gegated) | `menu:test_*` | Niedrig/Vorsicht — DoS-Risiko bereits einmal dokumentiert (TGPERM-001), Web-Exposition braucht eigene Rate-Begrenzung |

**Wichtig:** Jeder Bereich hat bereits einen etablierten, getesteten Berechtigungscheck auf Dispatcher- oder Methodenebene. Eine Web-API MUSS dieselbe Rollenlogik (`is_admin_or_owner`/`get_user_access_level`) aufrufen, nicht neu erfinden (Master-Prompt Regel 51 „Common Core").

---

## 5. Admin Inventory

Deckt sich mit den ADMIN/OWNER-Zeilen aus Abschnitt 4, hier nach Funktionsklasse:

- **Konfiguration:** kein dediziertes Admin-UI für `.env`/`config.py` vorhanden — Konfiguration erfolgt ausschließlich über die `.env`-Datei auf dem Host. Kein Telegram- oder CLI-Weg, Config zur Laufzeit zu ändern (außer Wartungsmodus-Flag).
- **Backups:** Bot-Backup, Library-Backup, Listen-Anzeige — `handlers/admin/backup_handler.py`.
- **Bot-Neustart:** `handlers/admin/bot_restart_handler.py` + `utils/bot_restart_trigger.py`.
- **Nutzerverwaltung:** Liste/Detail/Rolle/Löschen/Rechte/Bann — `handlers/admin/user_management_handler.py`, JSON-Datei-Store.
- **Logs:** Modul-Level, Dateien einsehen/herunterladen, Bereinigung — `handlers/enhanced_logger_menu_handler.py`.
- **Fehler-Administration:** Statistiken/Reports/Reset — `erradmin:`-Dispatcher, `handlers/enhanced_error_handler.py`.
- **Health/Diagnostics/Maintenance:** Doctor, Review, Repair, Library-Wartung, Duplicate-Stats/Cache — siehe Abschnitt 4.
- **Test-System:** Unit/Integration/Performance-Testläufe direkt aus Telegram (Owner/Admin-only seit TGPERM-001-Fix).

**Kein Audit-Log im Sinne des Master-Prompts (Abschnitt 30/31) vorhanden.** Admin-Aktionen (Repair, Delete, Bulk-Operationen) erzeugen zwar fachliche Journale (`RepairJournal`, Append-Only, SHA-256), aber kein generisches, bereichsübergreifendes „Who/What/When/Result"-Audit-Log über alle Admin-Aktionen hinweg. Für das Control Center (Master-Prompt Abschnitt 29–31) wäre das eine neue, bereichsübergreifende Abstraktion.

---

## 6. Reuse Opportunities

Direkt wiederverwendbar, ohne Umbau:

1. **Permission-Kern** (`handlers/menu/permissions.py::is_admin_or_owner`, `get_user_access_level`) — bereits Telegram-frei, reine Funktionen von `user_id`/`config`. Ideal als gemeinsame Autorisierungsbasis für Web-API-Middleware.
2. **`AccessLevel`-Enum** (`handlers/menu/models.py`) — direkt für API-Rollenprüfung nutzbar.
3. **Library-Health-Service** (`services/library_health/`) — vollständig Telegram-frei, read-only, bereits mit klarer Report-Struktur (JSON + Health-Score). Idealer erster Vertical-Slice-Kandidat (Master-Prompt Abschnitt 34, Phase 3 „Minimal Vertical Slice").
4. **Library-Repair-Findings-API** (`services/library_repair/findings.py`) — bereits mit `accept/unaccept/get_review_summary`-Core-API und Disposition-Matrix für alle 53 Codes (siehe `docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md`) — praktisch fertiger Service-Layer für einen Web-Findings-Browser.
5. **Statistik-Layer** (`services/statistik/`, `services/statistik_service.py`) — bestehende Berechnung, `chart_renderer.py` erzeugt bereits Bilder; für eine Web-Ansicht könnten stattdessen die Rohdaten aus `statistics_calculator.py`/`play_history_repository.py` abgegriffen werden, ohne die Berechnungslogik zu duplizieren.
6. **`ActiveDownloadRegistry` + `DownloadHistoryStore`** (`services/downloader/active_downloads.py`, `download_history.py`) — bereits das einzige echte, prozessweite Status-Tracking-Muster im Projekt; nächstliegendes Vorbild für einen generischen Job-Store (siehe Abschnitt 7).
7. **`doctor_runner.py`-Subprozess-Muster** (`services/library_repair/doctor_runner.py`) — zeigt bereits das für lange Operationen etablierte Muster (`asyncio.create_subprocess_exec` mit Timeout, kein `asyncio.to_thread` wegen dokumentierter Begründung) — Vorlage für einen künftigen generischen Job-Runner.
8. **`services/clients/navidrome_api.py`** — fertiger Subsonic-API-Adapter für ein künftiges Navidrome-Control-Modul.
9. **Library-Repair-Executor + Planner** — bereits vollständige Preview→Execute→Verify-Pipeline (Dry-Run-Default, Safety-Check, Journal, Rollback) — exakt das Muster, das Master-Prompt Abschnitt 21 für destruktive Web-Aktionen fordert. Kein neuer Sicherheitsmechanismus nötig, nur eine dünne API-Hülle.

---

## 7. Missing Abstractions

Nach dem in Abschnitt 45 des Master-Prompts geforderten Schema (Current/Desired/Why/Risk/Migration Strategy) — **rein dokumentiert, keine Umsetzung ohne separate Freigabe.**

### 7.1 Job-/Task-Abstraktion

- **Current:** Keine generische Job-Abstraktion. Lange Operationen laufen als direkter `asyncio.create_subprocess_exec`/`asyncio.to_thread`-Aufruf im Telegram-Callback (`doctor_runner.py`, Testläufe) oder als vom Nutzer manuell gestartetes CLI-Skript. Downloads haben mit `ActiveDownloadRegistry`/`DownloadHistoryStore` ein eigenes, funktionierendes, aber download-spezifisches Status-Tracking.
- **Desired:** Ein generischer Job-Store (ID, Status, Progress, Start/Ende, Initiator, Fehler, Ergebnis, optional Cancellation) für alle asynchronen Control-Center-Operationen (Repair, Reprocessing, Duplicate-Scan, Health-Scan), analog zum Muster aus Master-Prompt Abschnitt 9/18/28.
- **Why:** Eine Web-API darf laut Master-Prompt Regel 27 lange Operationen nicht synchron im HTTP-Request blockieren. Ohne Job-Abstraktion würde jede neue lange Web-Operation entweder eine eigene Ad-hoc-Lösung erfinden (Duplikation) oder synchron blockieren (Verstoß gegen Regel 27).
- **Risk:** Ohne saubere Abgrenzung könnte ein neuer Job-Store zur zweiten, parallelen Statusverwaltung neben `ActiveDownloadRegistry` werden, statt sie zu verallgemeinern — Duplikations-Risiko, das Master-Prompt Regel 7/51 explizit ausschließt.
- **Migration Strategy:** `ActiveDownloadRegistry` und `doctor_runner.py`-Subprozess-Muster als Vorbild nehmen, keine eigenständige Neuerfindung. Kleinster sinnvoller Schritt: ein generischer `JobRegistry`-Service (services-Ebene, Telegram-frei), der Downloads NICHT sofort migriert (Regel 5: kleine Pakete), sondern zunächst nur für neue Control-Center-Jobs (z. B. Health-Scan-Trigger über Web) verwendet wird. Migration von Downloads auf denselben Store wäre ein eigener, späterer Schritt mit eigener Characterization.

### 7.2 Web-Authentifizierung

- **Current:** Ausschließlich Telegram-User-ID-basierte Autorisierung. Keine Session-/Token-/Password-Mechanik im Projekt vorhanden.
- **Desired:** Eine für ein Web-Interface geeignete Authentifizierung (Master-Prompt Abschnitt 20), die auf demselben Autorisierungs-Kern (`is_admin_or_owner`, `AccessLevel`) aufsetzt.
- **Why:** Web-Zugriff kann nicht wie Telegram implizit über eine `chat_id`/`user_id` aus dem Update-Objekt authentifiziert werden — es braucht einen eigenen Login-/Session-Mechanismus.
- **Risk:** Dies ist der einzige Bereich, in dem eine **komplett neue** Sicherheitsschicht entstehen muss (kein bestehendes Muster im Projekt wiederverwendbar) — höchstes Risiko im gesamten Vorhaben, siehe BLOCKER in Abschnitt 10.
- **Migration Strategy:** Nicht Teil dieses Audits zu entscheiden (siehe BLOCKER-1 unten) — braucht explizite Nutzerentscheidung vor jeder Implementierung.

### 7.3 Generisches Admin-Audit-Log

- **Current:** Kein bereichsübergreifendes Audit-Log; nur fachspezifische Journale (`RepairJournal` u. a.).
- **Desired:** Ein leichtgewichtiges, bereichsübergreifendes „Who/What/When/Result"-Log für Web-Admin-Aktionen (Master-Prompt Abschnitt 29–31).
- **Why:** Destruktive/administrative Web-Aktionen sollen laut Master-Prompt Regel 31 auditierbar sein; das existiert heute nur punktuell.
- **Risk:** Gering — additive, nicht-invasive Ergänzung. Bei falscher Platzierung Gefahr, sensible Daten (Regel 32) mitzuloggen.
- **Migration Strategy:** Kleinster sinnvoller Schritt: dünnes Append-Only-Log (analog `RepairJournal`-Muster) ausschließlich für neue Web-API-Schreibaktionen, keine Rückwirkung auf bestehende Telegram-Pfade nötig.

### 7.4 API-Schicht als eigene Architekturschicht

- **Current:** Keine `api/`-Schicht existiert mehr (laut CLAUDE.md §4 vollständig entfernt, siehe ARCH-009 Roadmap). Keine formalen Request-/Response-Contracts irgendwo im Projekt.
- **Desired:** Eine neue, dünne API-Schicht (Master-Prompt Regel 9/10), die Services orchestriert, aber keine eigene Fachlogik enthält.
- **Why:** Voraussetzung für jede Web-Anbindung gemäß Zielarchitektur (Web → API → Command/Service → Domain).
- **Risk:** Gering bis mittel — Neuanlage, keine Migration bestehenden Codes nötig. Risiko liegt in der Versuchung, Fachlogik direkt in API-Handler zu schreiben (Regel 8).
- **Migration Strategy:** Neues Package (Name/Ort noch offen, siehe BLOCKER-2), beginnend mit dem in Abschnitt 9 vorgeschlagenen MVP-Slice.

---

## 8. API Proposal (grober Vorschlag, kein fertiger Contract)

Nur als Diskussionsgrundlage, nicht bindend — Contract-First-Definition (Master-Prompt Regel 10) erfolgt pro Endpunkt erst bei tatsächlicher Implementierung.

```text
/api/v1/health          GET   → services/library_health (+ System/Telegram/Navidrome-Status)
/api/v1/library/findings GET  → services/library_repair/findings.py (Review-Liste)
/api/v1/library/repairs POST  → services/library_repair/executor.py (Preview/Dry-Run zuerst)
/api/v1/jobs/{id}        GET  → neue JobRegistry (Abschnitt 7.1)
/api/v1/downloads        GET  → services/downloader/active_downloads.py, download_history.py
/api/v1/statistics       GET  → services/statistik/*
/api/v1/admin/users      GET  → handlers/admin/user_management_handler.py (Service-Extraktion nötig — aktuell Handler-gebunden)
/api/v1/navidrome/*      GET  → services/clients/navidrome_api.py
```

Auth-Mechanismus bewusst nicht vorgeschlagen — abhängig von BLOCKER-1 (Abschnitt 10).

---

## 9. Control Center MVP

Angepasst an das Audit-Ergebnis (Abweichung von der in Master-Prompt Abschnitt 35 vorgeschlagenen Reihenfolge, dort ausdrücklich als anpassbar markiert):

1. **Health/Dashboard-Slice zuerst** (wie Master-Prompt Abschnitt 35 vorschlägt) — begründet durch: `services/library_health/` ist bereits vollständig Telegram-frei, read-only, ohne Job-Abstraktion nutzbar (kein Preview/Confirm nötig, da lesend) und liefert sofort sichtbaren Nutzen (Dashboard-Kacheln analog Master-Prompt Abschnitt 5). Kleinstmöglicher vollständiger vertikaler Pfad: Web → API → `LibraryHealthService` → Response → Dashboard.
2. **Library-Findings-Browser** direkt danach — `services/library_repair/findings.py` ist ebenfalls bereits fertig (Accept/Unaccept/Summary), keine neue Job-Abstraktion für die reine Anzeige nötig.
3. **Erst danach** Job-Center (Abschnitt 7.1) als Voraussetzung für alles, was schreibt/lange läuft (Repair-Ausführung, Reprocessing, Duplicate-Scan).
4. Web-Auth (BLOCKER-1) muss **vor** jedem Schritt geklärt sein, der über einen reinen lokalen/vertrauenswürdigen Zugriff hinausgeht — spätestens vor Schritt 3.

---

## 10. Risks

### BLOCKER-1 — Web-Authentifizierung — ✅ ENTSCHIEDEN (2026-09-15)

**Entscheidung:** Option (a) — Telegram-Login-Widget, aufsetzend auf dem bestehenden Auth-Kern (`is_admin_or_owner`/`AccessLevel`). Begründung des Nutzers: gemeinsames Authorization-Modell für Telegram, CLI und Web (Master-Prompt Regel 51 „Common Core"), kein neues Credential-System. Details des Auth-Flows siehe `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md` Abschnitt „Auth-Konzept".

**Problem (Ausgangslage, zur Nachvollziehbarkeit erhalten):** Es existiert keinerlei Web-Auth-Mechanismus im Projekt (Abschnitt 7.2). Der Master-Prompt fordert in Abschnitt 20/Regel 13/14 „Deny by Default" und eine an die bestehende Auth-Struktur angelehnte Lösung, macht aber keine konkrete technische Vorgabe (Passwort? Telegram-Login-Widget? IP-Whitelist? Reverse-Proxy-Auth?).
**Auswirkung:** Ohne diese Entscheidung kann kein einziger schreibender oder Admin-Endpunkt sicher exponiert werden — betrifft direkt Schritt 3+ des MVP.
**Optionen:**
  a) Telegram-Login-Widget / Telegram-OAuth (nutzt bestehende User-IDs 1:1, kein neues Credential-System) — passt am besten zu „Common Core"/Regel 51, aber zusätzliche externe Abhängigkeit (Telegram-Bot-Domain-Verifikation).
  b) Einfaches Passwort/Session-Cookie nur für den/die bekannten Owner/Admin(s) (Single-Host-Hobbyprojekt, siehe CLAUDE.md-Philosophie „keine Enterprise-Komplexität") — am einfachsten, aber neues Credential-Handling nötig (Regel 15/16 beachten).
  c) Reverse-Proxy mit Basic-Auth/Client-Zertifikat vor dem Control Center, Bot selbst bleibt „vertraut Anfragen vom Proxy" — verlagert die Security-Entscheidung aus dem Python-Code, aber abhängig von der (noch unbekannten) Deployment-Umgebung.
**Empfehlung:** Option (a), da sie den bestehenden Auth-Kern (`is_admin_or_owner`) 1:1 weiterverwendet und keine neue Credential-Verwaltung einführt — aber dies ist eine bewusste Empfehlung, keine Entscheidung.
**Benötigte Entscheidung:** Nutzer muss vor Implementierung von Schritt 3+ (Abschnitt 9) festlegen, welche Option verfolgt wird — inkl. Klärung, ob das Control Center überhaupt außerhalb von `localhost`/VPN erreichbar sein soll (Netzwerk-Exposition, siehe Master-Prompt Abschnitt 32/52).

### BLOCKER-2 — Tech-Stack für Backend/Frontend — ✅ ENTSCHIEDEN (2026-09-15)

**Entscheidung:** Option (a) — FastAPI. Begründung des Nutzers: async-nativ (passt zum bestehenden `asyncio`-lastigen Code), automatische OpenAPI-Doku (deckt Master-Prompt Regel 43 ab), neue Kern-Dependency bewusst akzeptiert. Frontend-Ansatz für den MVP siehe `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md` Abschnitt „Frontend".

**Problem (Ausgangslage, zur Nachvollziehbarkeit erhalten):** Keine Web-Technologie im Repository vorhanden (Abschnitt 1). Der Master-Prompt verlangt in Abschnitt 25 „ZUERST REPOSITORY ANALYSIEREN", bevor ein Stack gewählt wird — das Ergebnis dieser Analyse ist: es gibt nichts Bestehendes, an das angeknüpft werden könnte. Die Wahl (z. B. FastAPI vs. aiohttp.web vs. Flask; React vs. serverseitiges Templating) hat große Auswirkung auf Dependencies, Deployment und Wartbarkeit.
**Auswirkung:** Ohne diese Entscheidung kann kein einziger API-Endpunkt implementiert werden.
**Optionen:**
  a) **FastAPI** — verbreitet, automatische OpenAPI-Doku (passt zu Master-Prompt Regel 43 „API-Dokumentation als Single Source of Truth"), async-nativ (passt zu bestehendem `asyncio`-lastigem Code), aber neue Dependency-Familie (fastapi, uvicorn, pydantic).
  b) **aiohttp.web** — `aiohttp` ist bereits Dependency (aktuell nur als Client genutzt), kein neues Kern-Framework nötig, aber weniger Komfort (keine eingebaute OpenAPI-Doku, mehr Boilerplate).
  c) Minimal-Ansatz ohne Framework (z. B. `http.server` + eigenes Routing) — passt zu „keine Überarchitektur" (Master-Prompt Abschnitt 33), aber widerspricht „kein Rad neu erfinden" bei wachsendem Funktionsumfang.
**Empfehlung:** Keine — das ist laut Master-Prompt Regel 24 „Keine ungefragten Technologie-Wechsel" explizit eine Entscheidung, die dokumentiert und vom Nutzer bestätigt werden muss, nicht vom Implementierungsprozess vorweggenommen werden darf.
**Benötigte Entscheidung:** Nutzer wählt Backend-Framework (und implizit Frontend-Ansatz: serverseitig gerendert vs. SPA) vor Beginn von Phase 3 (Master-Prompt Abschnitt 34).

### Weitere Risiken (nicht BLOCKER-Niveau)

- **God-Handler/God-Module** (`rich_menu_system.py`, `enhanced_error_handler.py`, `library_repair/executor.py`, `enhanced_logger_menu_handler.py`, `rich_menu_handler.py`, `download_handler.py`) — bereits in CLAUDE.md §19 als bekannter, akzeptierter Risikobereich dokumentiert. Für das Control Center relevant, weil Web-Wiederverwendung an genau diesen Dateien ansetzen würde — **keine Aufteilung ohne separate Characterization** (CLAUDE.md §19, Master-Prompt Regel 4).
- **`user_management_handler.py` ist Handler-gebunden, kein reiner Service** — für einen `/api/v1/admin/users`-Endpunkt bräuchte es entweder eine Service-Extraktion (kleiner Umbau, vorher dokumentieren) oder der Handler wird direkt (aber sauber entkoppelt von Telegram-Objekten) wiederverwendet.
- **Offene P2-Findings aus dem Referenz-Audit** (ERR-001 bare `except:` in `playlist_processor.py`) — nicht Control-Center-spezifisch, aber laut Master-Prompt Abschnitt 38 nicht zu ignorieren; unabhängig vom Control-Center-Vorhaben zu behandeln.
- **Bekannte akzeptierte Risiken** (F-07 MBID-Identitätssignal, INV-01 synchrone Duplicate-Cache-Persistenz, `dl:`-Präfix ohne zentrales Gate, CoverProcessor-Direct-HTTP) — alle laut Referenz-Audit bestätigt korrekt gekapselt, keine neue Bewertung nötig, aber bei Web-Exposition derselben Bereiche im Hinterkopf zu behalten.
- **Speicherbeschränkte Entwicklungsmaschine** (Projekt-Memory: 7,7 GB RAM + oft volle 4 GB Swap) — ein neuer Web-Server-Prozess neben dem Telegram-Bot-Prozess erhöht den Speicherdruck; bei der Stack-Wahl (BLOCKER-2) relevant.

---

## 11. Test Strategy

Angelehnt an CLAUDE.md §6–8 und Master-Prompt Abschnitt 26/27:

- **Unit Tests:** für jeden neuen Service/Command (Job-Registry, ggf. neue API-Auth-Middleware) — echte Produktionsklassen importieren, keine Nachbau-Klassen in Testdateien (CLAUDE.md §7).
- **API Tests:** HTTP-Status, Request-Validation, Authentication/Authorization, Fehlerbehandlung — pro neuem Endpunkt, sobald BLOCKER-1/2 geklärt sind.
- **Integration Tests:** API → Service → bestehende Domain-Logik (z. B. API-Health-Endpunkt → `services/library_health/` → echter Report), mit gemockten externen Diensten (Navidrome, MusicBrainz etc., analog bestehendem Muster).
- **Security Tests:** unauthorized access, privilege escalation, admin-only endpoints, destruktive Aktionen ohne Preview/Confirm — insbesondere ein Regressionstest nach dem Vorbild von `TestPrivilegedMenuItemsAreGatedTGPERM001` (generalisierter Registry-Sweep), der verhindert, dass ein künftiger Admin-Web-Endpunkt ungegatet bleibt — genau der Fehlerklasse, die TGPERM-001 im Telegram-Layer bereits einmal verursacht hat.
- **Regressionsschutz für Schichtgrenzen:** `tests/test_services_layer_boundary.py` als Vorbild — ein analoger Test könnte sicherstellen, dass eine künftige `api/`- oder `web/`-Schicht keine direkte Business-Logik enthält (Master-Prompt Regel 22).
- Vollständige Testsuite wird weiterhin **nicht** vom Implementierungsprozess ausgeführt (CLAUDE.md §8.A) — dem Nutzer nach jeder Phase zur Verifikation empfohlen.

---

## 12. Implementation Roadmap

**Phase 0 (dieses Dokument):** Repository-Audit — ABGESCHLOSSEN, wartet auf Freigabe für Phase 1.

**Phase 1 — Capability Matrix:** ✅ `docs/audits/CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md` — erstellt nach Freigabe vom 2026-09-15.

**Phase 2 — Architecture Proposal:** ✅ `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md` — erstellt nach Klärung von BLOCKER-1 (Web-Auth) und BLOCKER-2 (Tech-Stack) am 2026-09-15.

**Phase 3 — Minimal Vertical Slice:** Health-Dashboard-Slice (Abschnitt 9, Punkt 1) — Web → API → `LibraryHealthService` → Response → Dashboard. Kleinster vollständiger, getesteter, dokumentierter Pfad.

**Phase 4+ — Schrittweise Erweiterung:** gemäß Abschnitt 9 (Findings-Browser → Job-Center → Repair-Ausführung → Metadata → Downloads → Statistics → Admin → Logs/Diagnostics → Navidrome-Control → später Player), mit jeweils eigener Characterization/Tests/Dokumentation pro Slice (Master-Prompt Regel 5/6).

---

## Konflikte / Widersprüche

Keine echten Widersprüche zwischen Master-Prompt und Repository-Realität gefunden — die im Master-Prompt (Abschnitt 22) skizzierte CLI-Matrix-Erwartung trifft nur teilweise zu: es gibt **keine** in dem Sinne "produktive Bot-CLI", die der Master-Prompt implizit anzunehmen scheint ("library health", "library repair", "metadata reprocess" als CLI-**Befehle**), sondern eigenständige Wartungsskripte mit jeweils eigenem `argparse`-Parser, die laut CLAUDE.md §4 ausdrücklich **keine Laufzeit-Schicht** des Bots sind. Das ist kein Widerspruch, sondern eine Präzisierung: Abschnitt 22 des Master-Prompts selbst sagt "Analysiere zunächst, welche dieser Funktionen bereits vorhanden sind" — dieses Audit tut das, und das Ergebnis ist eine andere Realität als das Beispiel im Master-Prompt suggeriert (dort z. B. `library health → LibraryHealthService` als wäre es ein einheitliches CLI-Subcommand-System; tatsächlich sind es sieben unabhängige Skripte). Kein Handlungsbedarf, nur zur Kenntnisnahme dokumentiert (Master-Prompt Regel 2: Repository-Realität hat Vorrang vor Prompt-Annahmen).

Ein zweiter, kleinerer Punkt: Der Master-Prompt (Abschnitt 17) schlägt `/api/v1/repairs` als eigene Kategorie vor, während die bestehende Domäne diese Funktion bereits unter „Library" führt (`services/library_repair/`). Der API-Vorschlag in Abschnitt 8 dieses Dokuments folgt deshalb der bestehenden Domänen-Benennung (`/api/v1/library/repairs`) statt der Prompt-Beispielstruktur — reine Namensfrage, keine Architekturentscheidung, bei Bedarf in Phase 2 korrigierbar.

---

**AUDIT ENDE.** Phase 1 (Capability Matrix) und Phase 2 (Architecture Proposal) sind erstellt — siehe oben. Phase 3 (Implementierung des Vertical Slice) wartet weiterhin auf explizite Nutzer-Freigabe.
