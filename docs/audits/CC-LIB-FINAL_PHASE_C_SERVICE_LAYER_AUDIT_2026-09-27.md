# CC-LIB-FINAL Phase C — Service-Layer-Vollständigkeit (Audit)

Read-only Audit, keine Code-Änderung. Prüft die Zielarchitektur aus dem
CC-LIB-FINAL-Auftrag:

```text
Control Center → Router/API → Service → Domain/Executor → Library/File
```

gegen den tatsächlichen Ist-Zustand von `control_center/routers/`,
`handlers/` (Telegram) und den zugehörigen Templates/JS, für alle
Library-/Metadata-Funktionen. Vorgängerarbeit: Phase A/B
(`docs/FINDINGS_INDEX.md`, PR #317/#318 — Metadata-Reprocessing/L2
entfernt).

## 1. Funktionsmatrix

| Funktion | Service | Domain/Executor | Telegram | CC-API | Preview | Execute | UI | Tests | Status |
|---|---|---|---|---|---|---|---|---|---|
| Artist Rename | `maintenance_service.py::preview_artist_rename/execute_artist_rename` | `executor.py::apply_artist_rename()` | ✅ (`library_maintenance_handler.py`) | ✅ `POST /admin/maintenance/artist-rename/{preview,execute}` | ✅ | ✅ | ✅ Artist-Detail-Panel | ✅ `test_control_center_admin_maintenance_api.py`, `test_library_maintenance_handler.py` | COMPLETE |
| Title Edit | `maintenance_service.py::preview_title_edit/execute_title_edit` | `executor.py::apply_title_edit()` | ✅ | ✅ `POST /admin/maintenance/title-edit/{preview,execute}` | ✅ | ✅ | ✅ (Track-Drawer füllt `rel_path` automatisch; Direktzugriff im Panel verlangt weiterhin manuellen Pfad) | ✅ | PARTIAL (UX, siehe §3 — Phase-D-Scope) |
| Album Edit | `maintenance_service.py::preview_album_edit/execute_album_edit` | `executor.py::apply_album_edit()` | ✅ | ✅ `POST /admin/maintenance/album-edit/{preview,execute}` | ✅ | ✅ | ✅ Album-Picker (`<select>`, kein Freitext) | ✅ `test_library_maintenance_metadata_edit.py` | COMPLETE |
| Album Artist Edit | `maintenance_service.py::preview_album_artist_edit/execute_album_artist_edit` | `executor.py::apply_album_artist_edit()` | ✅ | ✅ `POST /admin/maintenance/albumartist-edit/{preview,execute}` | ✅ | ✅ | ✅ Album-Picker | ✅ | COMPLETE |
| Genre setzen (aus Mapping) | `maintenance_service.py::preview_set_genre/execute_set_genre` | `executor.py::apply_set_genre()` | ✅ (`libmaint:genremenu:*`) | ✅ `GET .../genre-preview`, `POST .../set-genre` | ✅ | ✅ | ✅ | ✅ `test_control_center_metadata_actions_api.py` | COMPLETE |
| Genre Mapping (Primary/Secondary) | `services/library_repair/genre.py::get_genre_mapping/plan_manual_genre_mapping/apply_manual_genre_mapping` | YAML-Domain (`genre.py`), kein Audio-Executor (Tags nur über „Genre setzen") | ✅ (Telegram-Mapping-Editor) | ✅ `GET/POST/PUT .../genre-mapping` | ✅ | ✅ (Etag-Konfliktschutz, 409) | ✅ Mapping-Editor im Artist-Detail | ✅ `test_control_center_genre_mapping_api.py`, `test_artist_genre_mapping_ui.py` | COMPLETE |
| Artist Casing | `maintenance_service.py::preview_artist_casing/execute_artist_casing_fix` | `executor.py::apply_artist_casing()` | ✅ | ✅ `POST /admin/maintenance/artist-casing/{preview,execute}` | ✅ | ✅ | ✅ Library-Wartung-Panel | ✅ | COMPLETE |
| Legacy Genre Cleanup | `maintenance_service.py::preview_legacy_genre_cleanup/execute_legacy_genre_cleanup` | `executor.py::apply_legacy_genre_cleanup()` | ✅ | ✅ `POST /admin/maintenance/legacy-genre-cleanup/{preview,execute}` | ✅ | ✅ | ✅ | ✅ | COMPLETE |
| Genre Revalidierung (Last.fm) | `genre_revalidation.py` + `genre_revalidation_runner.py` | Subprozess (`scripts/revalidate_genre.py`) | ✅ | ✅ Job (`POST /jobs/genre-revalidation-{preview,apply}`) | ✅ | ✅ | ✅ | ✅ `test_genre_revalidation.py`, `test_artist_genre_revalidation_ui.py` | COMPLETE |
| Library Maintenance (Übersicht/Status) | `run_tracking.py`, `maintenance_service.py` | — | ✅ | ✅ (`GET /repairs/history`, `/repairs/statistics`) | — | — | ✅ | ✅ | COMPLETE |
| Library Repair (SAFE_AUTOMATIC) | `repair_service.py::execute_safe_automatic_repair` | `executor.py::apply_level1*` | ✅ (MusicBot Doctor) | ✅ Job (`POST /jobs/repair-safe-automatic`) | ✅ (`GET /repair-plan`) | ✅ | ✅ | ✅ | COMPLETE |
| Library Repair (L3, MusicBrainz-IDs/ISRC) | `repair_service.py::execute_level3_repair` | `executor.py::apply_external_metadata()` | ✅ (`l23rep:*`) | ✅ Job (`POST /jobs/repair-level3`) | ✅ | ✅ | ✅ | ✅ | COMPLETE |
| Library Health (Scan/Findings) | `library_health/*` | Scanner (read-only) | ✅ | ✅ | — | — | ✅ | ✅ | COMPLETE |

**Metadata-Reprocessing (L2):** entfernt (Phase B, PR #317) — kein Eintrag
mehr, siehe `docs/LIBRARY_REPAIR.md` §6a.

## 2. Service-Layer-Compliance — Belege

**Kein Router/Handler mit direktem Datei-/Mutagen-/Shell-Zugriff:**

```text
grep -rln "mutagen" control_center/ handlers/   → 0 Treffer
grep -rn "open(\|write_text(\|write_bytes(\|shutil\.\|subprocess" control_center/routers/*.py
  → nur services.library_repair.genre_revalidation_runner-Import/Docstring-Erwähnungen
    in jobs.py, kein eigener Aufruf
```

**Jeder Metadata-mutierende Router importiert ausschließlich Service-Funktionen:**

- `admin_maintenance.py` → `services.library_repair.maintenance_service` (ausschließlich)
- `metadata_actions.py` → `services.library_repair.{genre,maintenance_service}` (ausschließlich)
- `jobs.py` → `services.library_repair.{doctor_runner,genre_revalidation_runner,repair_service}`, `services.jobs.job_registry`
- `repair.py` (read-only) → `services.library_repair.{planner,run_tracking}`
- `library_overview.py`/`metadata.py` (read-only) → `control_center/_library_scan.py` (wrappt `services/library_health`)

**Telegram-Handler rufen `executor.py` nie direkt auf:**

```text
grep -rl "from services.library_repair.executor import" handlers/   → 0 Treffer
grep -rl "maintenance_service" handlers/
  → handlers/library_maintenance_handler.py
  → handlers/menu/actions/library.py
  → handlers/menu/rich_menu_handler.py (nur Konstruktor-Verdrahtung)
```

**Frontend (JS/Templates) trifft keine Fachentscheidungen:**

`library_artist_detail.html`s JS-Funktionen (`_diffSummary()`,
`renderMetadataEditPreview()`, `renderGenreMappingPreview()`,
`_genreMappingAdd()` u. a.) formatieren ausschließlich bereits vom Server
gelieferte Preview-/Diff-Daten bzw. verwalten einen lokalen Formular-
Zwischenzustand vor dem Absenden (z. B. Duplikat-Chip-Check beim
Hinzufügen eines Secondary-Genres) — jede tatsächliche Entscheidung
(was sich ändert, ob ein Konflikt vorliegt, ob der Wert gültig ist)
kommt aus der Preview-/Execute-Antwort des Servers (`plan_manual_genre_mapping()`/
`apply_manual_genre_mapping()`/`apply_*()`). Kein `MP4(`/Tag-Zugriff, keine
YAML-Schreiblogik im JS.

**Bekannte, bewusst unveränderte Ausnahme:** `klassen/download_handler.py`
verwendet Mutagen direkt — das ist die Download-Pipeline (Telegram-Objekte
haltende Orchestrierungsschicht, CLAUDE.md §4), nicht Teil der manuellen
Metadata-Edit-Funktionen dieses Audits und laut CLAUDE.md/Auftrag §22
ausdrücklich außerhalb des CC-LIB-FINAL-Scope („keine unnötigen Änderungen
an Downloads … außer eine direkte technische Abhängigkeit wird gefunden" —
hier: keine).

## 3. Ergebnis

**Kein Service-Layer-Gap gefunden.** Alle elf geprüften Library-/Metadata-
Funktionen haben bereits eine vollständige Service-Heimat
(Router → Service → Domain/Executor), inklusive Preview/Execute-Symmetrie,
Etag-/Lock-Konfliktbehandlung und Tests. Phase C erfordert daher **keine
Code-Änderung** — die im Auftrag beschriebene Zielarchitektur ist für den
Metadata-Bereich bereits erreicht.

Eine funktionale Lücke wurde identifiziert, gehört aber zu **Phase D**
(„Metadata-Funktionen vollständig funktionsfähig", nicht Service-Layer):
„Titel bearbeiten" verlangt bei direktem Öffnen des Metadaten-Panels
(nicht über den Track-Drawer) weiterhin einen manuell einzutippenden
relativen Dateipfad (`title-edit-rel-path`, freies Textfeld) — der
Track-Drawer-Weg (`_trackDrawerEditTitle()`) füllt das Feld zwar bereits
automatisch, das Feld selbst bleibt aber sichtbares, direkt editierbares
Freitext-Element. Das widerspricht dem Auftrag §6.2 („Ein Benutzer darf
NICHT gezwungen werden, einen technischen relativen Dateipfad manuell
einzugeben"), sofern der Panel-Eintrittspunkt ohne Drawer benutzt wird.
Serverseitig ist das bereits vollständig abgesichert
(`maintenance_service.py::_title_edit_targets()`, Containment-Prüfung
gegen den Artist-Scope) — es ist ein UX-, kein Sicherheits- oder
Architekturbefund. Wird in Phase D behoben.

## 4. Geprüfte Dateien

`control_center/routers/{admin_maintenance,metadata_actions,jobs,repair,
metadata,library_overview}.py`, `handlers/library_maintenance_handler.py`,
`handlers/menu/actions/library.py`, `handlers/menu/rich_menu_handler.py`,
`control_center/templates/library_artist_detail.html` (JS-Block),
`services/library_repair/{maintenance_service,genre,executor}.py`.
