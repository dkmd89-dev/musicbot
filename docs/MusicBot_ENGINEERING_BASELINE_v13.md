# MusicBot Engineering Baseline v13

> **Status: 🟡 DRAFT (angelegt 2026-09-30) — noch nicht eingefroren.**
>
> Laufender Zwischenstand nach dem v12-Freeze (2026-09-29). Inhalt bisher:
> die vollständige **Mapping-Administration im Control Center** (M1–M5, UI
> 5.0–5.4, Backup/Restore, Runtime-Status, YAML-Editor) samt zwei dabei
> gefundenen Laufzeitfehlern. Die eingefrorene Baseline bleibt
> `docs/MusicBot_ENGINEERING_BASELINE_v12.md`; der laufende Finding-Stand
> steht in `docs/FINDINGS_INDEX.md`.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v13 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v12.md` (Freeze 2026-09-29, 6576 passed / 1 skipped / 11 subtests passed / 0 failed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl | **6576 passed** (Freeze-Stand v12). Seit v12 ist **kein neuer Full-Suite-Lauf gemeldet**; die Vollsuite führt ausschließlich der Nutzer aus (CLAUDE.md §8.A). |
| Neue Tests seit v12 (nur gezielte/thematische Läufe, keine Full-Suite) | 473 gesammelte Tests in 23 neuen Testdateien (`pytest --collect-only`), dazu Ergänzungen in `test_bot_runtime_snapshot_task.py` und den UI-Seitenlisten-Tests |
| ARCH-Phasen | keine (die Arbeit ist ein Control-Center-Feature, kein ARCH-Schritt) |
| Freeze-Status | offen — G3 (Produktion), G4 (Browser) und G6 (Vollsuite) stehen beim Nutzer, siehe `docs/audits/MAPPING_COMPLETION_PLAN_2026-09-30.md` §5 |

---

## 2. Recent Major Changes (seit v12-Freeze, 2026-09-29)

| Bereich | PR | Inhalt |
|---|---|---|
| **Mapping-Administration M1–M5** | #378 u. a. | Channel-Genre, Genre-Aliase, Genre-Overrides, Genre-Filter, Spezialkanäle über `services/mapping_admin.py` und `/api/v1/admin/mappings/{mapping_id}` (Allowlist, ADMIN, Vorschau, Etag, Kommentar-Hinweis) |
| **Mapping-UI 5.0–5.4** | #381, #384, #386, #388, #391, #392 | Seite `/mappings` (Kacheln als Tabs, Tabellen mit Suche/Paging, Chip-Listen, Prioritäts-Karten), Offcanvas-Editor (Formular, Listen, Vorschau/Diff, Konflikt-Dialog), Versionen |
| **B2 Schreib-Härtung** | #389 | eindeutiges tmp-Sibling, `fsync`, Aufräumen bei Fehler, Rechte bleiben, `fcntl`-Lock gegen gleichzeitige Schreiber aus Bot- und Control-Center-Prozess (Risiko R1 geschlossen) |
| **B1 Backup/Restore** | #390 | Version der Vorgängerdatei vor jedem Schreiben (`<DATA_DIR>/mapping_backups/…`, letzte 20), Restore als Etag-geschützter Write, Backup-Fehler bricht den Write ab |
| **B3 Runtime-Status** | #393 | Bot meldet beim Start die Datei-Hashes im Laufzeit-Snapshot; Control Center zeigt „Angewendet“ / „Neustart nötig“ / „Runtime unbekannt“ / „Bot läuft nicht“ (einzige Änderung am Bot) |
| **B4 YAML-Editor** | #394 | Rohtext mit strenger Prüfung (ein Dokument, keine Anker/Aliase/Tags/Merge-Keys/doppelten Keys, Tiefe ≤ 6, ≤ 512 KB), Text unverändert geschrieben (Kommentare bleiben) |
| **Fix: Spezialkanal-Priorität zufällig** | #379 | `set()`-Merge machte die Kategorie-Reihenfolge vom Hash-Seed abhängig; gemeinsamer Helfer behält die YAML-Reihenfolge |
| **Fix: Umordnen der Kategorien wurde nie geschrieben** | #390 | `plan_special_channels_update()` bewertete eine reine Umordnung als `unchanged`; der lockere Test verdeckte es |
| **Override-Key-Warnung** | #383 | `GenreMapper` sucht Overrides kleingeschrieben; ein Key mit Großbuchstaben greift zur Laufzeit nie — die Vorschau warnt |

---

## 3. Technical Debt — Mapping-Bereich (Stand 2026-09-30)

Schnappschuss der offenen Punkte dieses Themas; maßgeblich bleibt `docs/FINDINGS_INDEX.md`.

| Punkt | Prio | Anmerkung |
|---|---|---|
| `genre_hierarchy.yaml`, `genre_rules.yaml` nicht im Control Center bearbeitbar (M6/M7) | P3 | eigener Plan, braucht Hierarchie-/Regex-Validierung |
| `known_artists.yaml`, `case_preserve.yaml`, Auto-Learned-JSON, `artist_overrides.json` | P3 DEFER | Hybrid-/Auto-Learned-Dateien: Hybrid-Konflikt (R3) fachlich offen; R1 ist durch B2 geschlossen |
| Kein Löschen von Einträgen bei Channel-Genre/Aliasen/Overrides | P3 | kein DELETE-Endpunkt; Entfernen nur bei Filtern und Spezialkanälen |
| Override-Keys mit Großbuchstaben wirken zur Laufzeit nicht | P3 (akzeptiert) | Warnung umgesetzt; Runtime-Angleichung wäre eigener ARCH-Schritt |
| `bot_reload_required` bei `special-channels` konservativ | P3 | Teile der Prüfung lesen die Datei je Aufruf; in der UI als Hinweis sichtbar |
| Keine Server-Paginierung der Mapping-Listen | P3 | clientseitig (386 Aliase, 600 Filter); neuer Endpunkt wäre nötig |
| Kein Reload-Pfad im Bot („Anwenden“ ohne Neustart) | P3 | `GenreMapper.reload()` existiert, wird nicht aufgerufen; die UI zeigt den Zustand nur an |

---

## 4. Security- und Datensicherheits-Baseline (Stand 2026-09-30)

Kein neuer dokumentierter Datensicherheits-Vorfall seit v12-Freeze.

**Neue schützende Mechanismen:**

- **Allowlist statt Pfade:** der Client übergibt nur `mapping_id` (fünf feste Werte)
  und eine `version_id` aus der Liste; Dateipfade entstehen ausschließlich
  serverseitig. Versions-IDs werden nur gegen vorhandene Dateien aufgelöst.
- **ADMIN auf jedem Endpunkt** (serverseitig, `require_min_access_level`), schreibende
  Endpunkte zusätzlich Same-Origin; ein Test deckt alle 17 Routen für PUBLIC/USER/MODERATOR
  (403), ADMIN/OWNER (erlaubt) und ohne Session (401) ab.
- **Rohtext (YAML-Editor):** nie ein unsicherer Loader; Event-Scan vor dem Laden; harte
  Grenzen (512 KB, Tiefe, Knotenzahl); früher `Content-Length`-Schutz (413); der Text
  wird nie geloggt.
- **Schreiben:** Etag gegen Lost Updates, Datei-Lock, atomarer Write mit `fsync`, Backup
  vor jedem Schreiben.
- **Snapshot:** der Abschnitt `mapping_files` enthält nur Dateinamen aus der Allowlist und
  Hashes — keine Pfade, keine Inhalte.

---

## 5. Freeze-Voraussetzungen (offen)

- [ ] G3: echte Änderung je Typ in der Produktion, Bot-Neustart, Restore (Nutzer)
- [ ] G4: Browser-Durchlauf hell/dunkel, Desktop + Handy, Subpath (Nutzer)
- [ ] G6: Vollsuite `python3 -m pytest tests/ -q` (Nutzer); Fehler nach §8.A einordnen
- [ ] Zahlen in Abschnitt 1 aus dem gemeldeten Lauf eintragen, danach Status auf FROZEN
