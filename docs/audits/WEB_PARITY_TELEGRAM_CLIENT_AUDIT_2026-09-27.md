# Web-Parität und „Telegram als Client" — Audit

**Datum:** 2026-09-27
**Status:** 🟡 ANALYSIS COMPLETE — DECISION PENDING (keine Implementierung, reines Dokument)
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
| 🔧 Reprocessing (nur OWNER) | Subprozess `scripts/reprocess_artist_metadata.py` über `services/metadata/reprocessing_runner.py`, arbeitet auf einer Test-Sandbox | nur lesende Metadata-Seite (L2-Job ist ein anderes Werkzeug) | ⚪ |
| 🩺 MusicBot Doctor | `services/library_repair/doctor_runner.py` | Jobs `health-scan`, `repair-safe-automatic` | ✅ |
| 🔎 Library Health Review | `services/library_health/findings.py` | `library/findings*` (inkl. accept/unaccept/review/details) | ✅ |
| 🛠️ Repair MusicBot (Plan, L2/L3, Statistik, History) | `services/library_repair/*` | `repair-plan`, Jobs `repair-level2/3`, `repairs/*` | ✅ |
| 🧹 Library-Wartung (Artist/Titel/Album/Albuminterpret, Casing, Legacy-Genre, Genre setzen, Genre-Mapping, Revalidierung) | `services/library_repair/maintenance_service.py`, `genre*.py` | `admin/maintenance/*`, `library/artists/{a}/genre-*`, Jobs `genre-revalidation-*` (seit 2026-09-27) | ✅ 🟡 („Fehlende Genres" nicht verifiziert) |
| 🔁 Duplikat-Check (read-only Vorschläge) | `services/library_repair/duplicate_runner.py` (Subprozess, wie die Genre-Revalidierung) + `services/duplicate/*` | keine Route | 🔴 |
| ♻️ Duplikat-Verwaltung (Statistik, Cache leeren) | `DuplicateDetector` mit In-Memory-Cache im Bot-Prozess; `handlers/duplicate_handler.py` löscht die Cache-Dateien (`url_cache`/`content_cache`) selbst und leert den Speicher | keine Route | 🔴 🟣 🟠 |
| 💾 Backup-Verwaltung | `services/backup_admin.py` (nur CC); `handlers/admin/backup_handler.py` hat **eigene** tar-/Rotations-Logik | `admin/backups*` | 🟠 |
| 🔄 Bot neu starten | `utils/bot_restart_trigger.py` | `admin/system/restart` | ✅ |
| 🛠️ Wartungsmodus | `services/bot_maintenance.py` (geteilt) | `admin/maintenance` | ✅ (wirksam seit #313) |
| 👥 Benutzerverwaltung | `services/user_admin.py` + `services/user_data.py::save_user_data` (nur CC); `handlers/admin/user_management_handler.py` hat **eigene** Mutations-/Owner-Guard-/Schreiblogik (`_save_users`) | `admin/users*` | 🟠 |
| 📊 System-Status | `services/system_status.py` (beide) | `admin/system/status` | ✅ |
| 📄 System-Logs | `services/logs/*` | `logs`, `admin/logger/files*` | ✅ |
| 📈 Logger-Verwaltung | `services/logger_admin.py` (seit CC-LOGGER-L7 teilweise geteilt); `enhanced_logger_menu_handler.py` schreibt `module_logger_config.json` noch selbst (`_save_module_configs`) | `admin/logger/config`, `runtime-status`, `apply`, `files*` | ✅ 🟠; globales Level, Modul-Statistiken, Handler-Verwaltung 🟣 (DEFER) |
| 🚨 Error-Verwaltung | `handlers/enhanced_error_handler.py` (2190 Z., **kein** `services/`-Import; `ExceptionMonitor` im Bot-Speicher) | keine | 🔴 🟣 🟠 |
| 🧪 Test-System (Unit/Integration/Performance per Telegram) | `handlers/test_menu_handler.py` | keine | ⚪ |
| 🎵 Navidrome (Durchsuchen, Suche, Playlists, Favoriten, Zuletzt gespielt, Entdecken, Link-Stats) | `services/clients/navidrome_api.py` (geteilt) | `navidrome/*` (20 Routen: Browse, Suche, Playlists-CRUD, Favoriten, Random, Newest, Scan, Cover) | ✅ 🟡 („Zuletzt gespielt", „Link-Stats" nicht verifiziert) |
| 🔐 Identität/Login | `services/user_data.py` (Telegram-ID als Schlüssel); `handlers/menu/permissions.py` | Login nur über das **Telegram-Login-Widget** (`auth/telegram-callback`) | ⚪ (siehe 2.3 D) |

### 2.2 Korrektur früherer Aussagen
- „User-Verwaltung, Backups, Neustart/Maintenance sind Telegram-only" (CC-AC-10A, 22.09.) ist **überholt**: alle vier existieren im CC. Das Problem hat sich verschoben — nicht „fehlt im Web", sondern „zwei Implementierungen" (🟠).
- „Route existiert" ≠ „Parität": bei Wartungsmodus existierte die Route, war aber wirkungslos (P2, behoben in #313).

### 2.3 Vier Arten von Lücken

**A — Funktion fehlt im Web (Fachlogik ist schon in `services/`)**
Familie (`services/family/*`) und Duplikat-Check (read-only Subprozess `duplicate_runner`, gleiches Muster wie die Genre-Revalidierung als Job). Reine CC-Anbindung nach dem etablierten Muster (dünner Router + Seite), kein Architekturproblem.

**B — Telegram hat Fachlogik selbst (Doppelimplementierung, Drift-Risiko)**
Sicherheitsrelevant und der wichtigste Punkt für „Telegram nur noch Client":
1. **Benutzerverwaltung:** Owner-Guard, Rollen-/Rechteänderung und der atomare Schreibvorgang auf `data/user_data.json` existieren zweimal (`services/user_admin.py` + `save_user_data` für das CC, `_save_users` im Telegram-Handler). Beide schreiben atomar (tmp + rename), aber als read-modify-write ohne gegenseitigen Schutz (kein gemeinsames Lock in `services/user_data.py`).
2. **Backups:** `services/backup_admin.py` (CC) vs. eigene tar-/Rotationslogik in `backup_handler.py`.
3. **Logger-Konfiguration:** `enhanced_logger_menu_handler.py` liest/schreibt `module_logger_config.json` in Teilen weiterhin selbst.
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
5. **Test-System (Unit/Integration/Performance per Telegram) und Reprocessing (OWNER, Sandbox):** bewusst Telegram-only/entfallen lassen oder ins Web?

---

## 5. Backlog (nach Priorität, jeweils kleinster Schritt)

| # | Thema | Art | Prio | Kleinster Schritt | Abhängigkeit |
|---|---|---|---|---|---|
| 1 | User-Verwaltung: Telegram nutzt `services/user_admin` + `save_user_data` | B | P2 | Characterization der Telegram-Rollen-/Owner-Guard-Tests prüfen, dann Handler delegiert; ein Schreibpfad | — |
| 2 | Backups: Telegram nutzt `services/backup_admin` | B | P3 | analog 1 | — |
| 3 | Logger: verbleibende Datei-I/O im Telegram-Handler auf `logger_admin` | B | P3 | `_load/_save_module_configs` ersetzen | — |
| 4a | Duplikat-Check im CC (read-only Job über `run_duplicate_scan`) | A | P2 | dünner Job-Router + Ergebnisdarstellung, Muster wie `genre-revalidation-preview` | — |
| 4b | Duplikat-Verwaltung (Statistik, Cache leeren) | B + C | P3 | Cache-Löschlogik aus dem Handler nach `services/duplicate`; CC erst nach Entscheidung 1 | Entscheidung 1 |
| 5 | Cross-Prozess-Snapshot (Error-Verwaltung E1, Logger-Zähler) | C | P2 | nach Entscheidung 1: `ExceptionMonitor` schreibt Snapshot, CC liest | Entscheidung 1 |
| 6 | Downloads aus dem Web | B + C | P1 (groß) | ARCH-Phase: Ist-Analyse `klassen/download_handler.py`, Zielgrenzen, Extraktion | Entscheidungen 1, 2 |
| 7 | Familie im Web | A | P3 | nach Entscheidung 4 | Entscheidung 4 |
| 8 | `AccessLevel`/`permissions` aus `handlers/menu/` nach `services/` verschieben | D | P3 | reiner Move + Re-Export, keine Verhaltensänderung | — |
| 9 | Login ohne Telegram | D | offen | nach Entscheidung 3 | Entscheidung 3 |
| 10 | Test-System / Reprocessing | ⚪ | offen | nach Entscheidung 5 | Entscheidung 5 |

**Empfohlene Reihenfolge:** 1 → 2 → 3 (Doppelimplementierungen, kein neues Feature, bestehende Tests als Netz) → 4a (schnell, risikoarm) → Entscheidung 1 → 5 → 4b → 8; 6 erst nach Entscheidungen 1 und 2. Layout B der Health-Seite ist davon unabhängig (reine UI).

---

## 6. Referenzen
- `docs/audits/CC-AC-10A…10D_*_2026-09-22.md` (historisch), `CONTROL_CENTER_CAPABILITY_MATRIX_2026-09-15.md`
- `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` (Snapshot-Präzedenz)
- `docs/audits/ERROR_ADMINISTRATION_ARCHITECTURE_ANALYSIS_2026-09-27.md` (Varianten A–E)
- `docs/LIBRARY_REPAIR.md` §17 (Genre-Mapping im CC), §18 (Genre revalidieren im CC)
- `docs/FINDINGS_INDEX.md`
