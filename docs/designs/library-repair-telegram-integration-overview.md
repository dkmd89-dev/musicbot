---
system: library-repair-telegram-integration
related-diagrams:
  - ../diagrams/c4-context-library-repair-telegram.puml
  - ../diagrams/c4-container-library-repair-telegram.puml
  - ../diagrams/seq-library-maintenance-action.puml
  - ../diagrams/seq-level2-level3-telegram-per-artist.puml
related-adrs:
  - ../adr/0001-library-maintenance-actions-not-finding-driven.md
  - ../adr/0002-consolidate-repair-script-boilerplate.md
  - ../adr/0003-telegram-level2-level3-per-artist-confirmation.md
status: SUPERSEDED durch docs/MusicBot_ARCH-031_Library_Repair_Telegram_Integration_Characterization.md (vertieft Characterization, trifft die hier offen gelassenen Architekturentscheidungen verbindlich, ergänzt docs/adr/0004). Dieses Dokument bleibt als Ausgangspunkt/erster Entwurf erhalten, ist aber nicht mehr die aktuelle Quelle.
---

# Library Repair — Vollständige Telegram-Integration (Level 1–3) + Konsolidierung der drei neuen Wartungsskripte

> **Hinweis:** Die verbindliche Fassung ist jetzt
> [`docs/MusicBot_ARCH-031_Library_Repair_Telegram_Integration_Characterization.md`](../MusicBot_ARCH-031_Library_Repair_Telegram_Integration_Characterization.md).
> Dieses Dokument diente ihr als Ausgangspunkt (Vorphase, 2026-09-14).

## 0. Auftrag & Grenzen dieser Phase

Ziel: `library_repair` soll vollständig über den Telegram-Handler
ausführbar sein (Executor Level 1–3), ohne CLI/Terminal. Zusätzlich sollen
die drei neuen, eigenständigen Scripts (`fix_artist_casing.py`,
`remove_legacy_genre_atom.py`, `set_genre.py`, Commit `6037abf`, 2026-09-14)
in die `services/library_repair/`-Domäne konsolidiert werden.

**Diese Phase liefert ausschließlich Analyse + Zielarchitektur +
Migrationsplan.** Es wurden in dieser Phase keine Dateien gelöscht, kein
CLI entfernt, keine Produktionslibrary verändert (Auftragsvorgabe). Die
Umsetzung selbst ist eine eigene ARCH-Phase (CLAUDE.md §3.A: Characterize
→ Decide → Extract → Audit → Regression).

## 1. Aktueller Projektstand (Kontext, 2026-09-14)

- `main` @ `6037abf` (drei neue Scripts, noch ohne Tests/Doku-Anbindung).
- Baseline: `docs/MusicBot_ENGINEERING_BASELINE_v10.md` (DRAFT), letzter
  dokumentierter Vollsuite-Stand 4000 passed (Stand PR #236-238, vor den
  drei neuen Scripts — die drei Scripts selbst haben noch **keine Tests**).
- Library Repair Phase 2/3 CLOSED (`docs/LIBRARY_REPAIR.md`): alle 8
  Executoren (L1-Tags, L1-Renames, Cover, Album-Cover, L3, L2, Loudness,
  Duplicate) implementiert und gegen Produktion gelaufen.
- Telegram-Integration bereits vorhanden, aber **bewusst auf
  SAFE_AUTOMATIC begrenzt**: `handlers/repair_musicbot_handler.py` (Finding-
  Flow: Analyze → Proposals → Preview → Confirm → Execute → History/Stats)
  und `handlers/library_doctor_handler.py` (Kurzweg: Scan + SAFE_AUTOMATIC).
  Beide rufen letztlich `doctor_runner.run_safe_automatic_repair()`, das
  `--level SAFE_AUTOMATIC` fest verdrahtet.
- Die drei neuen Scripts sind **komplett eigenständig**: kein Import von
  `services/library_repair/`, kein Bezug zu `services/library_health/`
  Issue-Codes, eigene Journale unter `/tmp/musicbot_test/*.jsonl`.

## 2. Characterization — die drei neuen Scripts

| Script | Zweck | Eingabe-Modi | Schreibt | Health-Issue-Code? |
|---|---|---|---|---|
| `fix_artist_casing.py` | `©ART`/`ARTISTS`-Casing gegen `artist_overrides.json`/`case_preserve.yaml` normalisieren (NUR `key.casefold()==value.casefold()`, keine Namenserweiterung) | `--artist` / `--path` / `--all` | `©ART`, `----:com.apple.iTunes:ARTISTS` | **keiner** (ADR-0001) |
| `remove_legacy_genre_atom.py` | Legacy-Freeform `----:com.apple.iTunes:GENRE` entfernen, NUR wenn `©gen` existiert | `--artist` / `--path` / `--all` | entfernt `----:com.apple.iTunes:GENRE` | **keiner** (ADR-0001) |
| `set_genre.py` | `©gen` setzen: manuell (`--genre`) oder aus `artist_genre.yaml` (`--from-mapping`); entfernt Legacy-Atom als Nebeneffekt; optional `--update-manual-mapping` | `--artist`/`--path`/`--all` × `--genre`/`--from-mapping` | `©gen`, entfernt Legacy-Atom, optional `mapping/artist_genre.yaml` | **keiner** — strukturell auch keiner sinnvoll (manuelle Aktion, ADR-0001) |

Alle drei: Dry-Run-Default, Backup außerhalb der Library
(`<library>/../.library_repair_backups/`), Audio-Essenz-MD5-Verifikation,
Append-Only-Journal (aber **falscher Pfad**, siehe ADR-0002), Safety-Check
(Symlink/Library-Grenze/`.m4a`/leer).

### Duplikate zwischen den drei Scripts und `services/library_repair/`

Siehe ADR-0002 für die vollständige Zeile-für-Zeile-Gegenüberstellung.
Kurzfassung: `safety_check()`, `essence_md5()`/`_audio_essence_md5()`,
SHA-256-Berechnung, Backup-Pfad-Konvention und das
Temp-Sibling→Verify→atomarer-`replace()`-Muster existieren in `executor.py`
bereits **fast identisch** — die drei Scripts haben sie unabhängig neu
geschrieben statt zu importieren. `tags_fingerprint()` (Beweis: nur die
Ziel-Atome wurden verändert) existiert in `executor.py` dagegen noch
**nicht** und ist eine echte Verbesserung wert, die auch L1 zugutekommen
könnte (aber außerhalb des jetzigen Scopes).

### Abgleich gegen Health-Scanner-Issue-Codes

Kein Code in `services/library_health/issues.py` (`ALL_CODES`, siehe
`docs/LIBRARY_HEALTH.md` §5) deckt "Artist-Casing weicht vom Mapping ab"
oder "Legacy-GENRE-Atom trotz vorhandenem `©gen`" ab. Am nächsten liegen
`GENRE_EMPTY`/`META_GENRE_MISSING` (→ aktuell `METADATA_REPROCESSING`,
volle Pipeline) — `set_genre.py --from-mapping` wäre dafür ein **leichterer**
Fix-Pfad (nur `©gen`, keine Titel/Cover/Lyrics-Seiteneffekte, kein
Auto-Learn-Update), aber das Umbiegen dieser beiden bestehenden Issue-Codes
auf einen neuen, leichteren Executor ist eine **eigene, hier bewusst nicht
getroffene Entscheidung** (würde bestehendes, bereits gegen Produktion
gelaufenes Planner-Verhalten ändern — Kandidat für eine spätere,
eigenständige ARCH-Phase, siehe §6 „Offene Folgefragen“).

## 3. Zielarchitektur (siehe C4-Diagramme)

Zwei parallele, klar getrennte Flows innerhalb von `services/library_repair/`:

```text
Flow A — Finding-getrieben (bestehend, erweitert um L2/L3-Telegram-Pfad)
  Health-Scan -> planner.py -> RepairPlan -> Preview -> Confirm
  -> executor.py (apply_level1/apply_level2/apply_external_metadata)
  -> Verification-Rescan -> Finding RESOLVED

Flow B — Command-getrieben (NEU, "Library-Maintenance-Actions")
  Artist waehlen -> Aktion waehlen (Casing/Legacy-Genre/Genre setzen)
  -> Preview (reine Funktion, kein Health-Report)
  -> Confirm -> executor.py (apply_artist_casing/apply_legacy_genre_cleanup/
     apply_set_genre, NEU) -> Datei-Verifikation (kein Rescan, kein Finding)
```

Beide Flows teilen sich: `executor.py`s Safety-/Backup-/Verify-Kern,
`journal.py::RepairJournal` → **eine** Produktions-Journal-Datei,
`repair_service.py`s Lock-Datei (`library_repair.lock`) und Run-Index
(`library_repair_runs.json`) für Historie/Statistik.

## 4. Migrationsplan — Datei → Funktion → Zielmodul → Tests

| Quelle (Datei::Funktion) | Zielmodul | Aktion | Migrationsschritt | Neue/erweiterte Tests |
|---|---|---|---|---|
| `fix_artist_casing.py::load_casing_map()` | `services/library_repair/artist.py` (NEU) | MOVE (rein, kein I/O außer Mapping-Read) | 1 | `tests/test_library_repair_artist.py::test_load_casing_map_*` |
| `fix_artist_casing.py::normalize_values()` / `_to_str()` | `services/library_repair/artist.py` | MOVE (rein) | 1 | `tests/test_library_repair_artist.py::test_normalize_values_*` |
| `fix_artist_casing.py::safety_check()` | — | ENTFÄLLT, `executor.safety_check()` wiederverwenden | 2 | bestehend (`tests/test_library_repair_executor.py`) |
| `fix_artist_casing.py::essence_md5()` | — | ENTFÄLLT, `executor._audio_essence_md5()` wiederverwenden | 2 | bestehend |
| `fix_artist_casing.py::tags_fingerprint()` | `services/library_repair/executor.py` (NEU, modulweit) | MOVE + generalisieren (auch für `genre.py`-Pfad nutzbar) | 3 | `tests/test_library_repair_executor.py::test_tags_fingerprint_*` |
| `fix_artist_casing.py::fix_one()` (I/O-Ablauf) | `services/library_repair/executor.py::apply_artist_casing()` (NEU) | MOVE + ADAPT auf `apply_level1()`-Muster (ExecOutcome, RepairJournal statt eigenem JSONL) | 4 | `tests/test_library_repair_executor.py::TestApplyArtistCasing` |
| `remove_legacy_genre_atom.py::fix_one()` (Vergleichsteil) | `services/library_repair/genre.py` (NEU) | MOVE (rein: Legacy-vs-kanonisch-Entscheidung) | 1 | `tests/test_library_repair_genre.py::test_legacy_atom_removal_decision_*` |
| `remove_legacy_genre_atom.py::fix_one()` (I/O-Ablauf) | `services/library_repair/executor.py::apply_legacy_genre_cleanup()` (NEU) | MOVE + ADAPT | 4 | `tests/test_library_repair_executor.py::TestApplyLegacyGenreCleanup` |
| `set_genre.py::normalize_genre_input()` | `services/library_repair/genre.py` | MOVE (rein) | 1 | `tests/test_library_repair_genre.py::test_normalize_genre_input_*` |
| `set_genre.py::genre_from_mapping()` / `_known_artist_keys()` | `services/library_repair/genre.py` | MOVE (rein) | 1 | `tests/test_library_repair_genre.py::test_genre_from_mapping_*` |
| `set_genre.py::set_one()` (I/O-Ablauf) | `services/library_repair/executor.py::apply_set_genre()` (NEU) | MOVE + ADAPT | 4 | `tests/test_library_repair_executor.py::TestApplySetGenre` |
| `set_genre.py::update_manual_mapping()` | `services/library_repair/genre.py` (Schreibpfad bleibt gesondert, da es `mapping/artist_genre.yaml` selbst ändert — CLAUDE.md §10) | MOVE + ADAPT (explizite Opt-in-Aktion, nicht Teil von `apply_set_genre()` selbst) | 5 | `tests/test_library_repair_genre.py::test_update_manual_mapping_*` |
| — (NEU) | `services/library_repair/maintenance_service.py` (NEU) | NEU: `preview_artist_casing()`, `execute_artist_casing_fix()`, `preview_legacy_genre_cleanup()`, `execute_legacy_genre_cleanup()`, `preview_set_genre()`, `execute_set_genre()` — spiegeln `repair_service.py`s Lock/Journal-Fenster/Run-Index-Muster, aber ohne Health-Report-Bezug (ADR-0001) | 6 | `tests/test_library_repair_maintenance_service.py` (NEU) |
| — (NEU) | `handlers/library_maintenance_handler.py` (NEU) | NEU: `🧹 Library-Wartung`-Menü (Artist wählen → Aktion wählen → Preview → Confirm → Execute), Admin-Gating wie `repair_musicbot_handler.py` | 7 | `tests/test_library_maintenance_handler.py` (NEU) |
| `handlers/menu/definitions.py` | — | ERWEITERN: neuer Menüpunkt unter „Administration → Bibliothek & Navidrome“ | 7 | `tests/test_rich_menu_repair.py`-Äquivalent für `maint:*` |
| `repair_service.py` | `repair_service.py` (bestehend) | ERWEITERN: `execute_level2_repair(artist)`, `execute_level3_repair(artist)`, analog zu `execute_safe_automatic_repair()` aber mit `filter_plan(artist=...)`-Scope (ADR-0003) | 8 | `tests/test_repair_service.py::TestExecuteLevel2Repair`, `TestExecuteLevel3Repair` |
| `handlers/repair_musicbot_handler.py` | `handlers/repair_musicbot_handler.py` (bestehend) | ERWEITERN: Level-2/3-Kandidaten nach Artist gruppieren, Artist-Auswahl + Preview + Pro-Artist-Confirm (ADR-0003) statt reiner „🟡 REVIEW (CLI-only)“-Anzeige | 8 | `tests/test_repair_musicbot_handler.py::TestLevel2Level3TelegramFlow` |
| `services/library_repair/doctor_runner.py` | unverändert | KEINE Änderung — bleibt der reine SAFE_AUTOMATIC-Kurzweg für „🩺 MusicBot Doctor“ | — | — |
| `scripts/fix_artist_casing.py` / `remove_legacy_genre_atom.py` / `set_genre.py` | offen (siehe §5) | NACH Schritt 1–5 zu dünnen CLI-Wrappern um `artist.py`/`genre.py`/`executor.py::apply_*()` umbauen ODER entfernen | 9 (eigene Entscheidung) | bestehende Skript-Tests (aktuell **keine** vorhanden — Lücke, siehe §6) |

**Reihenfolge-Begründung:** 1 (reine Funktionen extrahieren, isoliert
testbar, kein Risiko) → 2/3 (Wiederverwendung statt Duplikat, additiv) →
4 (I/O-Pfade in `executor.py`, mit vollem Safety-/Rollback-Test analog zu
`apply_level1()`) → 5 (Mapping-Schreibpfad separat, da fachlich sensibel,
CLAUDE.md §10) → 6/7 (Orchestrierung + Telegram, erst wenn 1–5 grün) →
8 (L2/L3-Telegram-Erweiterung, unabhängig von 1–7) → 9 (Script-Zukunft,
erst nach Produktionslauf-Erfahrung mit dem neuen Weg).

## 5. Welche CLI-Funktionen bleiben nötig? (CLAUDE.md §4: `scripts/` = eigenständige Wartungstools)

Telegram deckt nach dieser Migration **artist-skalierte** Aktionen ab
(ein Artist pro Confirm, siehe ADR-0003 für L2/L3 und analog für die
Maintenance-Actions). Folgende CLI-Fähigkeiten der drei Scripts hat
Telegram **nicht** vor und sollten CLI-only bleiben, falls weiter benötigt:

- `--all` (ganze Library in einem Lauf) — bewusst kein Telegram-Äquivalent
  (Blast-Radius), bleibt CLI-Anwendungsfall.
- `--path` (einzelne Datei/Verzeichnis außerhalb der Artist-Struktur) —
  Telegram bietet nur Artist-Auswahl, kein Datei-Browser.
- `set_genre.py --update-manual-mapping` als eigenständiger Bulk-Schritt
  ohne gleichzeitigen Tag-Write — falls das je gebraucht wird (aktuell
  kein bekannter Anwendungsfall).

**Offene Entscheidung (nicht Teil dieser Phase):** ob die drei Scripts
nach der Migration (a) dünne Wrapper um die neuen `services/library_repair/`-
Funktionen bleiben (nur für `--all`/`--path`) oder (b) vollständig entfallen,
weil bislang **kein einziger Produktionslauf** dieser drei Scripts
dokumentiert ist (anders als z. B. bei `reprocess_artist_metadata.py`, das
vor der Service-Extraktion bereits mehrfach gegen Produktion validiert war,
siehe `docs/METADATA_REPROCESSING.md`). Empfehlung: Entscheidung nach dem
ersten Telegram-Produktionslauf treffen, nicht vorab (CLAUDE.md §18/§20).

## 6. Offene Folgefragen (bewusst nicht in dieser Phase entschieden)

1. Sollen `GENRE_EMPTY`/`META_GENRE_MISSING` künftig `set_genre.py
   --from-mapping`-Semantik (leichter Fix, kein Auto-Learn-Nebeneffekt)
   statt der vollen `METADATA_REPROCESSING`-Pipeline nutzen? Würde
   bestehendes, gegen Produktion verifiziertes Planner-Verhalten ändern —
   eigene Characterization + Entscheidung nötig.
2. Lohnt sich `tags_fingerprint()` (ADR-0002, Schritt 3) auch rückwirkend
   für `apply_level1()` (L1-Tags), um dessen Verifikation zu verschärfen?
   Optionale Verbesserung, nicht Teil des jetzigen Scopes.
3. Zukunft der drei Original-Scripts (§5) — nach Produktionserfahrung
   entscheiden.

## 7. Definition of Done für die spätere Umsetzungsphase

```text
[ ] artist.py / genre.py mit reinen Unit-Tests (Schritt 1)
[ ] executor.py::apply_artist_casing/apply_legacy_genre_cleanup/apply_set_genre
    inkl. Safety-/Backup-/Rollback-Tests (Schritt 4)
[ ] maintenance_service.py + Telegram-Handler (Schritt 6/7)
[ ] repair_service.py::execute_level2_repair/execute_level3_repair (Schritt 8)
[ ] repair_musicbot_handler.py Artist-Gruppierung + Pro-Artist-Confirm (Schritt 8)
[ ] Journal-Vereinheitlichung verifiziert (ein Produktionslauf je neuer
    Aktion erscheint in library_repair_runs.json / Telegram-Statistik)
[ ] docs/LIBRARY_REPAIR.md um §11 "Library-Maintenance-Actions" ergänzt
[ ] docs/FINDINGS_INDEX.md: offene Folgefragen aus §6 eingetragen
[ ] gezielte + thematische Tests grün (CLAUDE.md §8.A) — KEINE Vollsuite
    durch den Implementierungsprozess, Empfehlung an den Nutzer am Ende
[ ] Entscheidung zu den drei Original-Scripts (§5) explizit dokumentiert
```
