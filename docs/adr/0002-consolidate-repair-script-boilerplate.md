---
status: PROPOSED (Nutzerentscheidung 2026-09-14, noch nicht implementiert)
---

# ADR-0002: Konsolidierung der Safety-/Backup-/Verify-Boilerplate

## Kontext

Characterization der drei Scripts (`fix_artist_casing.py`,
`remove_legacy_genre_atom.py`, `set_genre.py`) zeigt fast identischen Code:

| Funktion | fix_artist_casing.py | remove_legacy_genre_atom.py | set_genre.py | bereits in executor.py? |
|---|---|---|---|---|
| `safety_check(path, library_root)` | Zeile 103 | Zeile 48 | Zeile 61 | JA, Zeile 94 (identische Semantik: Symlink/Library-Grenze/`.m4a`/leer) |
| `essence_md5(path)` (ffmpeg-MD5) | Zeile 121 | Zeile 40 | Zeile 79 | JA, `_audio_essence_md5()` Zeile 134 |
| SHA-256 der Datei | Zeile 199 | Zeile 127 | Zeile 212 | JA, `_sha256()` Zeile 123 |
| `tags_fingerprint()` (Beweis: nur Ziel-Atome geaendert) | Zeile 129 | — (nur Legacy-Atom+©gen geprueft) | Zeile 87 | NICHT vorhanden — neu fuer executor.py |
| Backup nach `.library_repair_backups/` | Zeile 192-196 | Zeile 121-124 | Zeile 206-209 | JA, identisches Muster in allen `apply_*()` |
| Temp-Sibling-Schreiben + atomarer `replace()` | Zeile 202-247 | Zeile 129-157 | Zeile 215-249 | JA, identisches Muster |
| Journal (JSONL, append-only) | eigene Datei `/tmp/musicbot_test/fix_artist_casing_journal.jsonl` | eigene Datei `/tmp/musicbot_test/remove_legacy_genre_journal.jsonl` | eigene Datei `/tmp/musicbot_test/set_genre_journal.jsonl` | JA, `journal.py::RepairJournal` -> `<DATA_DIR>/library_repair_journal.jsonl` |
| `collect_targets()` (`--artist`/`--path`/`--all`) | Zeile 275 | Zeile 183 | Zeile 316 | in dieser Form nicht in executor.py (dort iteriert `RepairCandidate`-Listen aus dem Plan) |

**Kritischer Befund:** die drei Scripts schreiben ihre Journale nach
`/tmp/musicbot_test/*.jsonl` — nicht in die Produktions-Journal-Datei
`<DATA_DIR>/library_repair_journal.jsonl`. `/tmp` kann bei einem Neustart
geleert werden; ausserdem lesen `repair_service.py::load_repair_history()`
und `compute_repair_statistics()` ausschliesslich die Produktionsdatei —
bisherige Laeufe dieser drei Scripts sind dort **unsichtbar**.

## Entscheidung

1. `safety_check()`, `_sha256()`, `_audio_essence_md5()` aus `executor.py`
   werden **wiederverwendet** (importiert), nicht dupliziert. `executor.py`
   exportiert sie dafuer (bereits modulweit definiert, aktuell ohne
   `__all__`-Einschraenkung).
2. `tags_fingerprint()` wird **neu** nach `executor.py` uebernommen (existiert
   dort noch nicht) — es ist die praezisere Verifikation ("nur genau
   diese(s) Atom(e) geaendert") gegenueber dem bisherigen Level-1-Muster
   ("Ziel-Atome haben den erwarteten Wert"). Wird zukuenftig auch fuer L1
   nutzbar, ist hier aber nur fuer die drei neuen `apply_*()` erforderlich.
3. Backup/Temp-Sibling/atomarer-Replace/Journal-Ablauf wird als gemeinsames
   internes Hilfsmuster in `executor.py` extrahiert (kein neues Modul —
   die bestehenden `apply_level1()`/`apply_cover_repairs()` etc. haben
   dasselbe Muster leicht dupliziert; siehe Migrationsplan Schritt 4).
4. Journal-Ziel wird auf `journal.py::RepairJournal` +
   `<DATA_DIR>/library_repair_journal.jsonl` vereinheitlicht — die drei
   `apply_*()` erscheinen damit automatisch in Repair-Historie/-Statistik.
5. `load_casing_map()`/`normalize_values()` (aus `fix_artist_casing.py`)
   wandern nach `services/library_repair/artist.py` als reine Funktionen
   (kein Dateisystem-I/O ausser dem Mapping-Datei-Read).
6. `genre_from_mapping()`/`normalize_genre_input()`/`_known_artist_keys()`
   (aus `set_genre.py`) und die Legacy-Atom-Entfernungs-Entscheidung (aus
   `remove_legacy_genre_atom.py::fix_one()`, der reine Vergleichsteil ohne
   I/O) wandern nach `services/library_repair/genre.py`.
7. `collect_targets()` (Artist/Path/All-Aufloesung) bleibt **CLI-spezifisch**
   und wird nicht nach `services/library_repair/` verschoben — Telegram
   braucht nur den Artist-Fall (kein `--path`/`--all` von einem Chat aus),
   die CLI-Variante bleibt in den (ggf. weiterhin bestehenden) CLI-Wrappern.

## Konsequenzen

- Kein Verhalten aendert sich fuer bestehende Aufrufer von `executor.py`
  (rein additive Erweiterung: 3 neue `apply_*()`-Funktionen + 2 neue reine
  Module `artist.py`/`genre.py`).
- Die 3 Scripts werden in dieser Phase **nicht geloescht** (siehe
  Migrationsplan) — sie koennen nach der Migration entweder (a) duenne
  CLI-Wrapper um dieselben `apply_*()`/`artist.py`/`genre.py`-Funktionen
  werden (fuer `--all`/`--path`-Bulk-Läufe, die Telegram nicht anbietet)
  oder (b) vollstaendig entfallen, wenn sich zeigt, dass niemand mehr
  `--all`/`--path` braucht. Diese Entscheidung folgt NACH der Migration,
  mit Nutzungsbeobachtung, nicht vorab (CLAUDE.md §18 Refactoring-Regel,
  §20 Legacy-Code).
- Neuer Testbedarf: `tests/test_library_repair_artist.py` (Casing-Map,
  Normalisierung — reine Unit-Tests wie `tests/test_library_repair_planner.py`
  fuer `tag_repairs.py`), `tests/test_library_repair_genre.py` (Mapping-
  Lookup, Legacy-Atom-Entscheidung), Erweiterung von
  `tests/test_library_repair_executor.py` um `apply_artist_casing()`/
  `apply_legacy_genre_cleanup()`/`apply_set_genre()` (Safety/Backup/
  Verify/Rollback-Pfade, analog zu den bestehenden `apply_level1()`-Tests).
