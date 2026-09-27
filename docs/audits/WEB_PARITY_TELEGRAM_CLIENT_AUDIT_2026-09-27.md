# Web-Parität und „Telegram als Client" — Audit

**Datum:** 2026-09-27 (Ersterstellung 08:00 Uhr, PR #316; verifiziert und ergänzt 2026-09-27 nachmittags nach CC-LIB-FINAL, siehe Abschnitt 7; erneut aktualisiert 2026-09-27 abends nach Client-Consolidation-Phase A/B, siehe Abschnitt 8)
**Status:** 🟡 ANALYSIS COMPLETE — DECISION PENDING (keine Implementierung, reines Dokument; zwei zuvor offene Doppelimplementierungs-Punkte inzwischen umgesetzt, siehe Abschnitt 8)
**Auftrag (Nutzer, 2026-09-27):** Das Control Center (CC) soll vollständig unabhängig von Telegram werden; Telegram ist am Ende nur noch ein Client neben dem Web.
**Vorgehen:** CLAUDE.md §3.A — Ist-Zustand → Verantwortlichkeiten → Zielgrenzen → kleinster Schritt.
**Ablösung:** Die Matrix in `CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md` („🔴 Telegram-only" für User-Verwaltung, Backups, Restart, Maintenance) ist durch CC-AC-10B/C/D überholt; dieses Dokument hat Vorrang.

---

## 1. Methode und Grenzen

**Geprüft (am Code, nicht aus alten Audits):**
- Telegram-Funktionsumfang: der vollständige Menübaum aus `handlers/menu/definitions.py::build_menu_tree()` (alle Punkte, Zugriffsstufen) plus die Slash-Commands (`/start`, `/menu`, `/help`, `error_*`).
- CC-Umfang: `create_app().routes` — **96 API-Routen** (`library` 25, `admin` 32, `navidrome` 20, `jobs` 10, `statistics` 5, `downloads` 1, `logs` 1, `auth` 2) und 11 Seiten (`/`, `/downloads`, `/library`, `/library/{artist}`, `/metadata`, `/statistics`, `/health`, `/navidrome`, `/logs`, `/logger`, `/admin`).
- Wer ruft welchen Service auf: Importgraph `handlers/`, `klassen/`, `control_center/` → `services/`.
- Direkter Datei-/Prozess-Zugriff in Handlern (`open(`, `json.dump`, `yaml`, `tarfile`, `unlink`, `subprocess`).

**Nicht geprüft:** Feature-Parität *innerhalb* einer Ansicht (z. B. jede einzelne Statistik-Ansicht, jeder Telegram-Unterdialog), UI-Abdeckung im Detail, Verhalten im Produktivbetrieb. „✅" heißt hier: die Fachlogik ist geteilt und im CC erreichbar — nicht: jede Telegram-Aktion ist 1:1 abgebildet.

---

## 2. Ist-Zustand

### 2.1 Paritätsmatrix (Telegram-Menü → Fachlogik → Control Center)

Legende: ✅ geteilte `services/`-Logik, im CC erreichbar · 🟠 im CC vorhanden, aber **Telegram hat eine eigene Parallel-Implementierung** · 🔴 im CC nicht vorhanden · 🟣 Cross-Prozess-Blocker (Zustand im Bot-Speicher) · ⚪ Entscheidung offen (evtl. bewusst Telegram-only) · 🟡 nur teilweise geprüft

| Telegram-Bereich | Fachlogik liegt in | Control Center | Status |
|---|---|---|---|
| 📥 Downloads (Track, Playlist) | `klassen/download_handler.py` (1183 Z., hält Telegram-Objekte) + `services/downloader/*`; `ActiveDownloadRegistry` im Bot-Speicher | nur `GET /downloads/history` (Verlauf) — kein Start, kein Live-Status | 🔴 🟣 |
| 📊 Statistiken (Rückblicke, Rankings, Timeline, Music DNA, Meine Library) | `services/statistik*` | `/statistics/me`, `/me/genres`, `/me/music-dna`, `/me/timeline`, `/statistics/{user}`, Library-Übersicht | ✅ 🟡 |
| 👨‍👩‍👧‍👦 Familie (Statistik, Chat, Challenge) | `services/family/*` (Services existieren) | keine Route, keine Seite | 🔴 |
| 🔧 Reprocessing (Level 2, nur OWNER) | **entfernt** (siehe Abschnitt 7): `scripts/reprocess_artist_metadata.py`, `services/metadata/reprocessing_runner.py`/`track_reprocessor.py`, Telegram-Menü „🔧 Reprocessing" | nie vorhanden; L3 (`EXTERNAL_METADATA`) bleibt unverändert unter `repair-plan`/Jobs `repair-level3` | OBSOLETE |
| 🩺 MusicBot Doctor | `services/library_repair/doctor_runner.py` | Jobs `health-scan`, `repair-safe-automatic` | ✅ |
| 🔎 Library Health Review | `services/library_health/findings.py` | `library/findings*` (inkl. accept/unaccept/review/details) | ✅ |
| 🛠️ Repair MusicBot (Plan, L2/L3, Statistik, History) | `services/library_repair/*` | `repair-plan`, Jobs `repair-level2/3`, `repairs/*` | ✅ |
| 🧹 Library-Wartung (Artist/Titel/Album/Albuminterpret, Casing, Legacy-Genre, Genre setzen, Genre-Mapping, Revalidierung) | `services/library_repair/maintenance_service.py`, `genre*.py` | `admin/maintenance/*`, `library/artists/{a}/genre-*`, Jobs `genre-revalidation-*` (seit 2026-09-27) | ✅ 🟡 („Fehlende Genres" nicht verifiziert) |
| 🔁 Duplikat-Check (read-only Vorschläge) | `services/library_repair/duplicate_runner.py` (Subprozess, wie die Genre-Revalidierung) + `services/duplicate/*` | keine Route | 🔴 |
| ♻️ Duplikat-Verwaltung (Statistik, Cache leeren) | `DuplicateDetector` mit In-Memory-Cache im Bot-Prozess; `handlers/duplicate_handler.py` löscht die Cache-Dateien (`url_cache`/`content_cache`) selbst und leert den Speicher | keine Route | 🔴 🟣 🟠 |
| 💾 Backup-Verwaltung | `services/backup_admin.py` (nur CC); `handlers/admin/backup_handler.py` hat **eigene** tar-/Rotations-Logik | `admin/backups*` | 🟠 |
| 🔄 Bot neu starten | `utils/bot_restart_trigger.py` | `admin/system/restart` | ✅ |
| 🛠️ Wartungsmodus | `services/bot_maintenance.py` (geteilt) | `admin/maintenance` | ✅ (wirksam seit #313) |
| 👥 Benutzerverwaltung | `services/user_admin.py` + `services/user_data.py::update_user_data()` (prozessübergreifend `fcntl.flock`-gesperrter Read-Modify-Write-Zyklus); Telegram (`UserManagementHandler._update_users()`) und CC (`admin.py`, alle 5 mutierenden Endpunkte) nutzen ausschließlich diesen Zyklus, keine eigene Mutations-/Owner-Guard-/Schreiblogik mehr | `admin/users*` | ✅ (seit Phase A, PR #326, siehe Abschnitt 8) |
| 📊 System-Status | `services/system_status.py` (beide) | `admin/system/status` | ✅ |
| 📄 System-Logs | `services/logs/*` | `logs`, `admin/logger/files*` | ✅ |
| 📈 Logger-Verwaltung | `services/logger_admin.py` (seit CC-LOGGER-L7/Phase B vollständig geteilt); `enhanced_logger_menu_handler.py` liest/schreibt `module_logger_config.json` seit Phase B (PR #327) nur noch über `read_logger_config()`/`atomic_write_json()`, keine eigene Datei-I/O mehr | `admin/logger/config`, `runtime-status`, `apply`, `files*` | ✅; globales Level, Modul-Statistiken, Handler-Verwaltung weiterhin 🟣 (DEFER, Findings 435/436 unverändert, kein Doppelimplementierungsthema) |
| 🚨 Error-Verwaltung | `handlers/enhanced_error_handler.py` (2190 Z., **kein** `services/`-Import; `ExceptionMonitor` im Bot-Speicher) | keine | 🔴 🟣 🟠 |
| 🧪 Test-System (Unit/Integration/Performance per Telegram) | `handlers/test_menu_handler.py` | keine | ⚪ |
| 🎵 Navidrome (Durchsuchen, Suche, Playlists, Favoriten, Zuletzt gespielt, Entdecken, Link-Stats) | `services/clients/navidrome_api.py` (geteilt) | `navidrome/*` (20 Routen: Browse, Suche, Playlists-CRUD, Favoriten, Random, Newest, Scan, Cover) | ✅ 🟡 („Zuletzt gespielt", „Link-Stats" nicht verifiziert) |
| 🔐 Identität/Login | `services/user_data.py` (Telegram-ID als Schlüssel); `handlers/menu/permissions.py` | Login nur über das **Telegram-Login-Widget** (`auth/telegram-callback`) | ⚪ (siehe 2.3 D) |

### 2.2 Korrektur früherer Aussagen
- „User-Verwaltung, Backups, Neustart/Maintenance sind Telegram-only" (CC-AC-10A, 22.09.) ist **überholt**: alle vier existieren im CC. Das Problem hat sich verschoben — nicht „fehlt im Web", sondern „zwei Implementierungen" (🟠).
- „Route existiert" ≠ „Parität": bei Wartungsmodus existierte die Route, war aber wirkungslos (P2, behoben in #313).
- Von den in 2.3 B gelisteten „zwei Implementierungen"-Fällen (🟠) sind Benutzerverwaltung und Logger-Konfiguration seit Phase A/B geschlossen (→ ✅, Abschnitt 8); Backups bleibt 🟠.

### 2.3 Vier Arten von Lücken

**A — Funktion fehlt im Web (Fachlogik ist schon in `services/`)**
Familie (`services/family/*`) und Duplikat-Check (read-only Subprozess `duplicate_runner`, gleiches Muster wie die Genre-Revalidierung als Job). Reine CC-Anbindung nach dem etablierten Muster (dünner Router + Seite), kein Architekturproblem.

**B — Telegram hat Fachlogik selbst (Doppelimplementierung, Drift-Risiko)**
Sicherheitsrelevant und der wichtigste Punkt für „Telegram nur noch Client". Von ursprünglich sechs Punkten sind zwei seit Phase A/B geschlossen (Abschnitt 8):
1. ~~**Benutzerverwaltung**~~ — **CLOSED (Phase A, PR #326):** Owner-Guard, Rollen-/Rechteänderung und der Schreibvorgang auf `data/user_data.json` laufen jetzt ausschließlich über `services/user_data.py::update_user_data()`, das den kompletten Read-Modify-Write-Zyklus prozessübergreifend per `fcntl.flock` sperrt. Kein separater Telegram-Schreibpfad mehr.
2. **Backups:** `services/backup_admin.py` (CC) vs. eigene tar-/Rotationslogik in `backup_handler.py`. Weiterhin offen (Backlog 2).
3. ~~**Logger-Konfiguration**~~ — **CLOSED (Phase B, PR #327):** `enhanced_logger_menu_handler.py` liest/schreibt `module_logger_config.json` nur noch über `services/logger_admin.py::read_logger_config()`/`atomic_write_json()`. Kein gemeinsames Lock ergänzt (bewusst — kein hochfrequenter, konkurrierender Schreibpfad identifiziert); globales Log-Level und Modul-Statistiken/Introspektion bleiben ein separates Cross-Prozess-/Schema-Thema (Findings 435/436, unverändert 🟣 DEFER).
4. **Duplikat-Cache leeren:** `duplicate_handler.py` löscht die Cache-Dateien selbst (`unlink()`) und leert den In-Memory-Cache — Fachlogik im Handler und zugleich Cross-Prozess-Zustand (ein Löschen der Dateien aus dem CC ließe den Speicher des Bots unberührt). Betrifft **keine Audio-Dateien**; das Löschen echter Duplikate ist weiterhin nur per CLI (`--execute --confirm-production-execute`), die Telegram-Anbindung ist ein bewusst zurückgestellter Punkt (FINDINGS_INDEX).
5. **Error-Verwaltung:** 2190 Zeilen Fachlogik + Zustand in `handlers/`.
6. **Downloads:** die gesamte Orchestrierung liegt in `klassen/download_handler.py`, das bewusst Telegram-Objekte hält (CLAUDE.md §4, „Sonderfall").

**C — Cross-Prozess-Blocker (Zustand nur im Bot-Speicher)**
`ExceptionMonitor` (Fehlerstatistik), Logger-Log-Zähler, `ActiveDownloadRegistry` (Live-Downloads), der In-Memory-Cache des `DuplicateDetector` (Duplikat-Verwaltung). Das CC ist ein separater Prozess und kann diesen Zustand nicht lesen. **Eine** Architekturentscheidung (Abschnitt 4, Entscheidung 1) schaltet alle drei frei; die Präzedenz ist CC-LOGGER-L3 („Snapshot statt Live-Behauptung", `docs/audits/ERROR_ADMINISTRATION_ARCHITECTURE_ANALYSIS_2026-09-27.md`, Empfehlung E1). Der Wartungsmodus war derselbe Mechanismus, ist aber inzwischen gelöst (Datei + `stat()`-Neulesen).

**D — Identität und Paketstruktur**
- Das CC meldet ausschließlich über das Telegram-Login-Widget an; Nutzer werden über die Telegram-ID identifiziert. „Unabhängig von Telegram" schließt damit den Login *nicht* ein.
- Die CC-Router importieren `handlers.menu.models.AccessLevel` (12+ Module) und `handlers.menu.permissions`. Beide Module sind Telegram-frei (`handlers/menu/__init__.py` ist leer), liegen aber im „falschen" Paket — eine Struktur-, keine Laufzeitabhängigkeit.

---

## 3. Verantwortlichkeiten und Zielgrenzen

```text
services/            → einzige Heimat für Fachlogik UND geteilten Zustand
                       (inkl. Cross-Prozess-Schnittstellen: Snapshot-Dateien, Request-Dateien)
handlers/ (Telegram) → Client: Präsentation, Callback-Routing, Nachrichtenversand
control_center/      → Client: Präsentation, Web-Auth, dünne Router
klassen/             → heute Sonderfall (Downloads); Ziel: aufgelöst
Bot-Prozess          → Ausführer für alles, was im Bot-Prozess leben muss
                       (Telegram-Polling, laufende Downloads, solange nicht ausgelagert)
```

Leitregeln (aus den bisherigen Entscheidungen abgeleitet, nicht neu erfunden):
1. **Kein Client schreibt Fachdaten selbst.** Jede Mutation läuft über eine `services/`-Funktion (Muster: CC-LOGGER-L7, `genre.py`-Edit, `finding_explain`).
2. **Ehrlichkeit vor Live-Optik:** Ein Client zeigt nur, was er wirklich wissen kann. Zustand im Bot-Speicher wird als Snapshot mit Zeitstempel gezeigt, nie als Live-Wert (L3-Entscheidung).
3. **Aktionen über Prozessgrenzen** brauchen einen benannten Mechanismus (Datei-Request, Neustart), keine stille Annahme.
4. **Kleinster Schritt vor großem Umbau** (CLAUDE.md §18/§21): erst Doppelimplementierungen zusammenführen (bestehende Tests als Netz), dann neue Fähigkeiten.

---

## 4. Entscheidungen (Nutzer)

1. **Cross-Prozess-Mechanismus** (schaltet Error-Verwaltung, Logger-Zähler, Live-Downloads frei): E1 (Bot schreibt Snapshot-Datei, CC liest read-only; Reset bleibt Telegram/Neustart) — empfohlen, **oder** zusätzlich eine Request-Datei, die der Bot pollt (Aktionen aus dem Web), **oder** ein IPC (nicht empfohlen, L3-Präzedenz).
2. **Downloads aus dem Web starten?** Ja/Nein. Ja bedeutet: Extraktion der Orchestrierung aus `klassen/download_handler.py` in `services/` plus ein Ausführungsweg im Bot-Prozess (Entscheidung 1 ist Voraussetzung). Größter Einzelposten, eigene ARCH-Phase.
3. **Login ohne Telegram?** Nur relevant, wenn Telegram komplett entfallen darf. Sonst bleibt Telegram der Identitätsanbieter des Web (dann ist „Client" fachlich erreicht, der Login nicht).
4. **Familie (Statistik, Chat, Challenge) ins Web?** Fachlogik ist da; die Frage ist Nutzen.
5. **Test-System (Unit/Integration/Performance per Telegram):** bewusst Telegram-only/entfallen lassen oder ins Web? (Reprocessing ist durch CC-LIB-FINAL erledigt, siehe Abschnitt 7 — keine offene Entscheidung mehr.)

---

## 5. Backlog (nach Priorität, jeweils kleinster Schritt)

| # | Thema | Art | Prio | Kleinster Schritt | Abhängigkeit |
|---|---|---|---|---|---|
| 1 | ~~User-Verwaltung: Telegram nutzt `services/user_admin` + `save_user_data`~~ | B | — | ✅ **DONE (Phase A, PR #326)** — siehe Abschnitt 8 | — |
| 2 | Backups: Telegram nutzt `services/backup_admin` | B | P3 | analog 1 (jetzt: analog dem in Abschnitt 8 dokumentierten Muster) | — |
| 3 | ~~Logger: verbleibende Datei-I/O im Telegram-Handler auf `logger_admin`~~ | B | — | ✅ **DONE (Phase B, PR #327)** — siehe Abschnitt 8 | — |
| 4a | Duplikat-Check im CC (read-only Job über `run_duplicate_scan`) | A | P2 | dünner Job-Router + Ergebnisdarstellung, Muster wie `genre-revalidation-preview` | — |
| 4b | Duplikat-Verwaltung (Statistik, Cache leeren) | B + C | P3 | Cache-Löschlogik aus dem Handler nach `services/duplicate`; CC erst nach Entscheidung 1 | Entscheidung 1 |
| 5 | Cross-Prozess-Snapshot (Error-Verwaltung E1, Logger-Zähler) | C | P2 | nach Entscheidung 1: `ExceptionMonitor` schreibt Snapshot, CC liest | Entscheidung 1 |
| 6 | Downloads aus dem Web | B + C | P1 (groß) | ARCH-Phase: Ist-Analyse `klassen/download_handler.py`, Zielgrenzen, Extraktion | Entscheidungen 1, 2 |
| 7 | Familie im Web | A | P3 | nach Entscheidung 4 | Entscheidung 4 |
| 8 | `AccessLevel`/`permissions` aus `handlers/menu/` nach `services/` verschieben | D | P3 | reiner Move + Re-Export, keine Verhaltensänderung | — |
| 9 | Login ohne Telegram | D | offen | nach Entscheidung 3 | Entscheidung 3 |
| 10 | Test-System | ⚪ | offen | nach Entscheidung 5 | Entscheidung 5 |

**Empfohlene Reihenfolge:** 1 und 3 sind erledigt (Phase A/B, siehe Abschnitt 8); verbleibend: 2 (Backups, analoge Doppelimplementierung, kein neues Feature, bestehende Tests als Netz) → 4a (schnell, risikoarm) → Entscheidung 1 → 5 → 4b → 8; 6 erst nach Entscheidungen 1 und 2. Layout B der Health-Seite ist davon unabhängig (reine UI).

Reprocessing (früher Punkt 10 hier) ist seit CC-LIB-FINAL kein Backlog-Punkt mehr — L2 wurde vollständig entfernt, siehe Abschnitt 7.

---

## 7. Verifikation nach CC-LIB-FINAL (2026-09-27, nachmittags)

Dieses Audit (PR #316) wurde um 08:00 Uhr gemergt. Direkt danach liefen fünf
weitere PRs auf `main`, alle im Library-/Metadata-Bereich, den Abschnitt 2.1
bereits als ✅ geführt hatte:

| PR | Inhalt | Wirkung auf dieses Audit |
|---|---|---|
| #317 CC-LIB-FINAL Phase A/B | Level 2 (`METADATA_REPROCESSING`) **vollständig entfernt**: `services/metadata/track_reprocessor.py`, `reprocessing_runner.py`, `scripts/reprocess_artist_metadata.py`, Telegram-Menü „🔧 Reprocessing", CC-Job `repair-level2` | löst die bisher offene ⚪-Zeile „Reprocessing" auf → **OBSOLETE** (Zeile in 2.1 aktualisiert). Die zehn zuvor auf L2 zeigenden Health-Issue-Codes (`META_ARTIST/TITLE/ALBUM/GENRE_MISSING`, `META_TITLE_NOT_CLEAN`, `GENRE_EMPTY/INVALID`, `LYRICS_MISSING/EMPTY/INVALID`) sind jetzt `MANUAL_REVIEW` statt einer automatischen Neuverarbeitung |
| #319 Phase C | Service-Layer-Audit (nur Dokumentation): prüfte alle elf Metadata-Funktionen im CC gegen `services/`, fand **einen** Gap (Titel-Bearbeiten verlangte einen manuellen Dateipfad) | bestätigt unabhängig die ✅-Einstufung „Library-Wartung" aus 2.1 |
| #320 Phase D | Der Gap aus Phase C behoben: Freitext-Pfad durch `<select>` (nach Album gruppiert) ersetzt | reine UI, keine neue Route — Parität unverändert, jetzt lückenlos |
| #321 Phase E | Library-Home-Dashboard + Artist-Detail neu gestaltet | laut Commit-Message „reine Frontend-Änderung, keine neue API" — verifiziert, keine Matrix-Änderung |
| #322/#323 | UI-Text-/Datenbindungs-Fixes im Artist-Detail | keine Matrix-Änderung |
| #324 Polish | Metadaten-Workspace als Tabs (Artist/Titel/Album/Albuminterpret/Genre), „Attention-Card", zentrale Issue-Label-Tabelle in `common.js` | reine DOM-Umsortierung + Labels laut Commit; **eine Diskrepanz gefunden**, siehe unten |

**Befund — Lyrics-Findings ohne Editor: entschieden und behoben (2026-09-27).**
Der Auftrag zu diesem Audit ging davon aus, dass Lyrics-Issue-Codes auf
`NOT_REPAIRABLE` stehen sollen, „solange kein Lyrics-Editor existiert".
Tatsächlich standen `LYRICS_MISSING`/`LYRICS_EMPTY`/`LYRICS_INVALID` seit
PR #317 auf `MANUAL_REVIEW`, gemeinsam mit den anderen neun ehemaligen
L2-Codes — der Metadaten-Workspace (PR #324) hat aber nur Tabs für
Artist/Titel/Album/Albuminterpret/Genre, keinen Lyrics-Tab. Ein Nutzer
hätte einen als „manuell behebbar" markierten Fund gesehen, für den es im
CC keine Handlungsmöglichkeit gab — Widerspruch zur Konvention, dass
`MANUAL_REVIEW` = „behebbar über eine bestehende Edit-Aktion" bedeutet.

**Nutzer-Entscheidung (2026-09-27):** `LYRICS_MISSING`/`_EMPTY`/`_INVALID`
zurück auf `NOT_REPAIRABLE`. Kein Lyrics-Editor, keine neue Lyrics-UI/
-Fachlogik im Rahmen dieser Entscheidung. Lyrics bleiben bewusst
`NOT_REPAIRABLE`, bis ein eigener Lyrics-Editor als zukünftige Funktion
beschlossen wird.

Umgesetzt: `services/library_repair/planner.py` (drei Specs auf
`RepairAction.NONE`/`RepairLevel.NOT_REPAIRABLE`, `approval=False`,
analog zu `ALBUM_GENRE_INCONSISTENT`), `docs/LIBRARY_REPAIR.md` §4/§6a,
`docs/FINDINGS_INDEX.md` (Zeile „Manual Metadata Editing v1/v2"). Von den
zehn ehemaligen L2-Codes sind damit sieben `MANUAL_REVIEW` und drei
(Lyrics) `NOT_REPAIRABLE`. Tests: `tests/test_library_repair_planner.py`
(`_FORMER_L2_CODES` auf sieben Codes reduziert, neuer Test
`test_lyrics_codes_are_not_repairable_without_editor`),
`tests/test_library_repair_disposition_matrix.py::test_disposition_partition_sizes_snapshot`
(Snapshot 19/29/5 statt 19/32/2), `tests/test_library_repair_cli_safe_automatic_scope.py`
und `tests/test_control_center_repair_api.py` (Kommentare korrigiert, keine
Assertion hing am konkreten Level). Alle vier Dateien + die thematische
Suite (`tests/test_library_repair*.py tests/test_library_health*.py`,
753 Tests) grün. **Nicht angefasst:** `docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md`
— dieser eingefrorene Snapshot vom 09.09. war bereits durch PR #317 (L2
komplett entfernt) veraltet, unabhängig von dieser Lyrics-Korrektur; das
Nachziehen dieses historischen Dokuments ist ein eigener, hier nicht
angeforderter Schritt (CLAUDE.md §8.A: bereits bestehende, unabhängige
Abweichungen werden nicht ungefragt mitbehoben).

**Ergebnis:** Keine der fünf Nach-Audit-PRs ändert etwas an den bereits als
🔴/🟠/🟣 geführten Bereichen (Downloads, Familie, Duplicate, Backup,
User-Verwaltung, Error-Verwaltung, Logger-Reste, Test-System, Identität) —
alle betrafen ausschließlich Library/Metadata, das bereits ✅ war. Backlog
(Abschnitt 5) und Priorisierung bleiben unverändert gültig, bis auf den
entfallenen Reprocessing-Punkt und den neuen Lyrics-Befund oben.

---

## 8. Verifikation nach Client Consolidation Phase A/B (2026-09-27, abends)

Nach Freigabe von Phase A und Phase B (`/mnt/128ssd/client_consolidation.txt`)
wurde diese Matrix gegen den **aktuellen Code** neu geprüft (nicht aus den
PR-Beschreibungen übernommen), wie in Abschnitt 1 gefordert.

| PR | Inhalt | Verifikation | Wirkung auf dieses Audit |
|---|---|---|---|
| #326 Phase A | `services/user_data.py::update_user_data(mutator)` neu: sperrt Load→Mutator→Save prozessübergreifend per `fcntl.flock` auf `<path>.lock`. `handlers/admin/user_management_handler.py::_save_users()`/`_update_users()` delegieren vollständig; `control_center/routers/admin.py` nutzt für alle 5 mutierenden Endpunkte ausschließlich `update_user_data()` (nur GET liest weiterhin per `load_user_data()`, unlocked, wie in Abschnitt 3 Leitregel 1 vorgesehen). | Code gelesen: `handlers/admin/user_management_handler.py:56-97` (Delegation bestätigt), `services/user_data.py` (`update_user_data`, `fcntl.flock`, `LOCK_EX` bestätigt), `control_center/routers/admin.py` (`update_user_data`-Import + 5 Aufrufstellen bestätigt, `load_user_data` nur bei einem reinen GET). | Zeile „👥 Benutzerverwaltung" in 2.1: 🟠 → ✅. Abschnitt 2.3 B Punkt 1 CLOSED. Backlog Punkt 1 DONE. |
| #327 Phase B | `services/logger_admin.py::atomic_write_json()` öffentlich gemacht. `handlers/enhanced_logger_menu_handler.py::ModuleLoggerManager._load_module_configs()`/`_save_module_configs()` nutzen jetzt `read_logger_config()`/`atomic_write_json()` statt eigenem `json.load`/`json.dump`. `data/module_logger_config.json`: 42 → 113 Module (71 zuvor fehlende Module nachgetragen, u. a. alle 11 `control_center.*`-Module). | Code gelesen: `handlers/enhanced_logger_menu_handler.py:64-161` (`read_logger_config`/`atomic_write_json`-Aufrufe bestätigt, kein `json.load`/`json.dump` mehr). Datei geprüft: `data/module_logger_config.json` enthält aktuell 113 Einträge (bestätigt per Skript). | Zeile „📈 Logger-Verwaltung" in 2.1: 🟠-Anteil entfällt → ✅ (🟣 DEFER für globales Level/Introspektion bleibt unverändert, siehe Findings 435/436). Abschnitt 2.3 B Punkt 3 CLOSED. Backlog Punkt 3 DONE. |

**Bewusste Verhaltensänderung durch Phase A** (dokumentiert in PR #326 und
`docs/FINDINGS_INDEX.md`): `process_new_navidrome_user()` überschreibt einen
zwischen Telegram-Schritt 1 und 2 parallel angelegten User nicht mehr still,
sondern lehnt ihn über `UserAlreadyExistsError` ab. Betrifft nur den
Telegram-eigenen Zwei-Schritt-Dialog, keine CC-Route — keine Matrixänderung
über die Zeile selbst hinaus.

**Nicht durch Phase A/B verändert (verifiziert, nicht nur angenommen):**
Backups (`backup_handler.py` hat weiterhin eigene tar-/Rotationslogik, war
nicht Teil von Phase A/B), Duplikat-Cache, Error-Verwaltung, Downloads,
Familie, Test-System, Identität — alle Zeilen aus 2.1 mit 🔴/🟣/⚪ außerhalb
User-Verwaltung/Logger sind unverändert gültig. Findings 435/436 (globales
Log-Level, Modul-Statistiken/Introspektion) wurden gegen den Code erneut
geprüft und bleiben unverändert OPEN (DEFER) — Phase B hat ausschließlich die
Datei-I/O migriert, keine neue Cross-Prozess-Fähigkeit geschaffen.

**Ergebnis:** Zwei der sechs unter 2.3 B geführten Doppelimplementierungen
sind geschlossen. Die übrigen vier (Backups, Duplikat-Cache, Error-
Verwaltung, Downloads) sowie alle fünf Nutzerentscheidungen aus Abschnitt 4
bleiben unverändert offen — der Gesamtstatus des Dokuments bleibt daher
🟡 ANALYSIS COMPLETE — DECISION PENDING.

---

## 9. Verifikation nach Client Consolidation Phase C (2026-09-28)

Phase C (`/mnt/128ssd/client_consolidation.txt`) ist eine **reine
Dokumentations-Phase** — kein Code-Change. Sie hat die Matrix in
Abschnitt 2.1 gegen den **aktuellen Code** (nicht aus PR-Beschreibungen)
neu verifiziert.

| Zeile in 2.1 | Vorher | Nachher | Beleg |
|---|---|---|---|
| 👥 Benutzerverwaltung | 🟠 | ✅ | `handlers/admin/user_management_handler.py::_save_users()`/`_update_users()` delegieren vollständig; `services/user_data.py::update_user_data()` sperrt per `fcntl.flock` (LOCK_EX); `control_center/routers/admin.py` nutzt sie an allen 5 mutierenden Endpunkten |
| 📈 Logger-Verwaltung | 🟠 | ✅ | `handlers/enhanced_logger_menu_handler.py::ModuleLoggerManager._load/_save_module_configs()` nutzen `read_logger_config()`/`atomic_write_json()`; `data/module_logger_config.json` enthält 113 Module (Backfill aus Phase B bestätigt) |

**Nicht betroffen:** Backups, Duplikat-Cache, Error-Verwaltung, Downloads
bleiben in Abschnitt 2.3 B und im Backlog unverändert offen. Alle fünf
Nutzerentscheidungen aus Abschnitt 4 bleiben unverändert offen.

**Ergebnis:** Der Gesamtstatus des Audits bleibt
🟡 ANALYSIS COMPLETE — DECISION PENDING, da zwei weitere
Doppelimplementierungen aus der ursprünglichen Sechs-Liste (Backups,
Duplikat-Cache, Error-Verwaltung, Downloads) noch nicht abgearbeitet sind
und keine der fünf Nutzerentscheidungen getroffen wurde.

---

## 11. Nachtrag — Client Consolidation Phase D (2026-09-28, Architekturentscheidung Downloads)

Phase D (`/mnt/128ssd/client_consolidation.txt`) war eine **reine
Analyse-/Architekturphase — kein Code-Change**. Sie beantwortet
Entscheidung 2 (Abschnitt 4) und **präzisiert** Entscheidung 1 speziell
für Downloads — Entscheidung 1 selbst (Snapshot-Mechanismus für
Error-Verwaltung/Logger-Zähler/Live-Downloads-Anzeige) bleibt für die
übrigen betroffenen Bereiche unverändert offen.

**Entscheidung 2 (Downloads aus dem Web starten?): JA.**

**Wichtige Präzisierung von Entscheidung 1 für Downloads:** Die
ursprüngliche Annahme in Abschnitt 3 (Zeile 73) war, dass Live-Downloads
denselben Cross-Prozess-Snapshot-Mechanismus wie Error-Verwaltung/
Logger-Zähler brauchen. Der Code-Befund in Phase D widerlegt das für den
Anwendungsfall „CC startet eigene Downloads": `services/downloader/
downloader.py::YoutubeDownloader`, `services/duplicate/detector.py::
DuplicateDetector` und `services/metadata/enhanced_metadata_processor.py`
sind bereits vollständig Telegram-frei und nehmen Fortschritt über einen
injizierbaren `status_callback` entgegen (`services/downloader/download/
interfaces.py::DownloadCoordinator`-Protocol) — `klassen/
download_handler.py` ist nur der Telegram-Orchestrator darüber. Ein vom
CC selbst gestarteter Download kann diese Services direkt im CC-Prozess
aufrufen, ohne den Bot-Prozess-Zustand (`ActiveDownloadRegistry`) lesen zu
müssen. Entscheidung 1 bleibt daher **nur noch** Voraussetzung für den
separaten, unverändert offenen Anwendungsfall „CC sieht Telegram-
initiierte Live-Downloads" — nicht mehr für Downloads-Start aus dem Web.

**Beschlossene Architektur:**

- CC-lokaler Job-Typ über das bestehende `services/jobs/job_registry.py::
  JobRegistry`-Muster (identisch zu `repair_safe_automatic`/
  `repair_level3`, `control_center/routers/jobs.py`) statt eines neuen
  IPC-Mechanismus.
- Direkter Aufruf von `YoutubeDownloader`/`DuplicateDetector`/
  `EnhancedMetadataProcessor` im CC-Prozess — keine neue
  Download-Implementierung, keine Duplizierung der Telegram-Pipeline.
- Fortschritt über `JobRegistry.update_progress()` statt
  Telegram-spezifischer Anzeige.
- Persistenz ausschließlich über den bestehenden
  `services/downloader/download_history.py::DownloadHistoryStore` — kein
  neuer Persistenzpfad, keine zweite History-Datenquelle.
- `JobStatus`-Semantik unverändert (`PENDING/RUNNING/SUCCEEDED/FAILED/
  CANCELLED`), kein Fake-Erfolg vor tatsächlichem Abschluss.
- `klassen/download_handler.py` und Telegram-Verhalten bleiben
  unangetastet, sofern technisch nicht zwingend erforderlich.

**Concurrency-Entscheidung (globale Download-Grenze über beide
Prozesse):** `MAX_CONCURRENT_DOWNLOADS` wird heute durch ein
modulglobales `asyncio.Semaphore` in `klassen/download_handler.py`
durchgesetzt — faktisch prozessglobal, weil bisher nur ein
downloadfähiger Prozess existiert. Mit einem CC-eigenen Download-Pfad
entstehen zwei unabhängige Prozesse; ohne Gegenmaßnahme könnte die Summe
der parallelen Downloads die konfigurierte Grenze überschreiten.
Beschlossen: **Option B** — N Slot-Dateien (`N = MAX_CONCURRENT_DOWNLOADS`)
unter `Config.DATA_DIR`, atomar belegt/freigegeben per
`os.open(O_CREAT|O_EXCL|O_WRONLY)` — Erweiterung des bereits produktiven
Mutex-Musters aus `services/library_repair/run_tracking.py::
acquire_repair_lock()` von 1 Slot auf N Slots, von Bot- und CC-Prozess
gemeinsam genutzt. Verwaiste Slots nach einem Prozessabsturz: **nur
Diagnose** (PID+Timestamp im Slot-Inhalt, wie beim bestehenden
Repair-Lock), **kein** automatisches Freigeben — identisches Verhalten
zum bestehenden Repair-Lock, keine neue Fehlerklasse (PID-Wiederverwendung,
falsches TTL-Timing) eingeführt. Aufräumen eines verwaisten Slots bleibt
eine manuelle/Admin-Aufgabe.

**Status:** Architektur vollständig entschieden, **keine Implementierung
in Phase D**. Die Implementierung (neuer Job-Typ, Slot-Helfer, Tests) ist
eine separat freizugebende Folgephase.

---

## 12. Referenzen
- `docs/audits/CC-AC-10A…10D_*_2026-09-22.md` (historisch), `CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md`
- `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` (Snapshot-Präzedenz)
- `docs/audits/ERROR_ADMINISTRATION_ARCHITECTURE_ANALYSIS_2026-09-27.md` (Varianten A–E)
- `docs/audits/CC-LIB-FINAL_PHASE_C_SERVICE_LAYER_AUDIT_2026-09-27.md` (Service-Layer-Vollständigkeit Library/Metadata)
- `docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md` (Download-Center-Nachtrag, Scope-Entscheidung Verlauf statt Live-Status)
- `docs/LIBRARY_REPAIR.md` §17 (Genre-Mapping im CC), §18 (Genre revalidieren im CC)
- `docs/FINDINGS_INDEX.md` (Zeile zu „Manual Metadata Editing v1/v2" bereits als OBSOLETE durch CC-LIB-FINAL geführt; Zeilen „User-Verwaltung: Doppelimplementierung" und „Logger: verbleibende Datei-I/O im Telegram-Handler" seit Phase A/B CLOSED, siehe Abschnitt 8; Zeile „Downloads nicht aus dem Control Center startbar" seit Phase D mit Architekturentscheidung versehen, siehe Abschnitt 11)
- `/mnt/128ssd/client_consolidation.txt` (Auftrag Phase A–D), PR #326 (Phase A), PR #327 (Phase B), PR #328 (Phase C)
