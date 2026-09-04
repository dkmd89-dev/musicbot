# MusicBot — Smart Library Repair (Phase 2)

Leitet aus den Findings des [Library Health Scanners](LIBRARY_HEALTH.md)
konkrete, sichere, nachvollziehbare Reparaturaktionen ab.

```text
LIBRARY → Health Scanner → Health Report → Repair Planner
                                              │
                                       ┌──────┴──────┐
                                     SAFE FIX   MANUAL REVIEW
                                       │
                                  Repair Executor   ← (Phase 2 PR 2+, noch nicht implementiert)
                                       │
                                  Verification Scan
                                       │
                                  Before / After Report
```

**Status: Phase 2 PR 1 — Repair Planner (read-only).**
Der Executor (der tatsächlich Tags schreibt / Cover holt / Loudness
normalisiert / Duplikate löscht) folgt als eigener, explizit geschützter
Schritt. `--apply` / `--allow-delete` werden aktuell abgelehnt.

---

## 1. Nutzung

```bash
python scripts/library_repair.py                      # frischer read-only Scan → Plan
python scripts/library_repair.py --report r.json      # Plan aus vorhandenem Health-Report
python scripts/library_repair.py --json plan.json     # Plan als JSON

# gezielt (Prompt Abschnitt 19)
python scripts/library_repair.py --artist 01099
python scripts/library_repair.py --issue LOUDNESS_TAG_MISSING
python scripts/library_repair.py --severity ERROR
python scripts/library_repair.py --level SAFE_AUTOMATIC
```

**DRY-RUN ist Standard.** Ohne Executor verändert das Script nichts,
verschiebt nichts, löscht nichts und ruft keinen externen Dienst. Der
Health-Scan (`--report` weggelassen) ist selbst vollständig read-only.

---

## 2. Architektur

`services/library_repair/` (Muster wie `services/library_health/` /
`services/duplicate/`):

```text
models.py    RepairLevel / RepairAction / RepairSpec / RepairCandidate / RepairPlan
planner.py   plan_repairs(report_dict) -> RepairPlan  (reine Funktion, kein I/O)
             + REGISTRY: genau ein Repair-Mapping pro Health-Issue-Code
             + filter_plan(plan, artist=/issue_code=/severity=/level=)
report.py    render_plan_text(plan)
```

`scripts/library_repair.py` — dünner CLI-Wrapper (CLI → Health-Report →
Plan → Ausgabe), keine Fachlogik.

**Kein neuer Reparatur-Code in diesem Layer** (Prompt Abschnitt 21): jeder
Registry-Eintrag benennt die *bestehende* Komponente, die die Reparatur
später ausführt.

---

## 3. Repair-Levels (Prompt Abschnitt 6–11)

| Level | Bedeutung | Ausführende Komponente | Freigabe | Extern | Destruktiv |
|---|---|---|---|---|---|
| `SAFE_AUTOMATIC` | Ergebnis deterministisch aus vorhandenen Daten | `TagWriter` (atomar) + `split_main_and_featuring` + `sanitize_filename` | nein (nur `--apply`) | nein | nein |
| `METADATA_REPROCESSING` | komplexere Tag-Neubestimmung | `scripts/reprocess_artist_metadata.py` (Subprozess) | ja | ja | nein |
| `EXTERNAL_METADATA` | fehlende MB-IDs / ISRC / Jahr / Genre | `MusicBrainzClient` / `GenreProcessor` | ja | ja | nein |
| `COVER` | fehlendes / schlechtes / uneinheitliches Cover | `CoverProcessor` | ja | ja | nein |
| `LOUDNESS` | fehlende / falsche ReplayGain-Tags | `scripts/normalize_test_library_loudness.py` | nein | nein | (Re-Encode) |
| `DUPLICATE` | echte Duplikate | `scripts/resolve_duplicates.py` + `services/duplicate/*` | ja | nein | **ja** |
| `MANUAL_REVIEW` | kein sicherer automatischer Pfad | — | — | — | — |
| `NOT_REPAIRABLE` | legitime Beobachtung, nichts zu tun | — | — | — | — |

### Was NICHT automatisch repariert wird

- **Struktur:** Artist-/Album-Verzeichnisse umbenennen, Dateien verschieben,
  Ordner zusammenführen → immer `MANUAL_REVIEW` (Prompt Abschnitt 7/14).
- **Fehlende Tracks / doppelte Tracknummern / uneinheitliches Album-Jahr**
  → `MANUAL_REVIEW` (korrekter Wert ist nicht eindeutig).
- **`DUPLICATE_SUSPECTED`** (Remix/Live möglich) → immer `MANUAL_REVIEW`.
- **`AUDIO_*`** (korrupt / kein Stream / niedrige Bitrate / sehr kurz)
  → `MANUAL_REVIEW` (Neu-Download ist Nutzerentscheidung).
- **Format-Konvertierung** (`FILENAME_EXTENSION_UNEXPECTED`) → `MANUAL_REVIEW`.

`tests/test_library_repair_planner.py` verifiziert, dass jeder
Health-Issue-Code genau ein Mapping hat und kein Mapping veraltet ist.

---

## 4. Issue-Code → Repair-Mapping (Auszug)

| Health-Issue | Level | Aktion |
|---|---|---|
| `GENRE_DELIMITER_INCONSISTENT` | SAFE_AUTOMATIC | `' / '` → `'; '` im Genre-Tag |
| `MULTI_ARTIST_SUSPICIOUS` / `_INCONSISTENT` / `_DUPLICATE` | SAFE_AUTOMATIC | Multi-Artist-Tag korrekt splitten / angleichen |
| `META_ALBUM_ARTIST_MISSING` | SAFE_AUTOMATIC | Album-Artist = Haupt-Artist |
| `ALBUM_ARTIST_INCONSISTENT` | SAFE_AUTOMATIC | Album-Artist aller Tracks vereinheitlichen |
| `FILENAME_TITLE_MISMATCH` / `FILENAME_SUSPICIOUS` | SAFE_AUTOMATIC | Dateiname im selben Verzeichnis neu bilden |
| `META_ARTIST_MISSING` / `_TITLE_MISSING` / `_ALBUM_MISSING` | METADATA_REPROCESSING | `reprocess_artist_metadata.py` |
| `GENRE_INVALID` / `LYRICS_*` | METADATA_REPROCESSING | Genre/Lyrics neu bestimmen |
| `META_MB_*_MISSING` / `META_ISRC_MISSING` / `META_YEAR_MISSING` | EXTERNAL_METADATA | MusicBrainz-Match (nur bei Eindeutigkeit) |
| `META_GENRE_MISSING` / `GENRE_EMPTY` | EXTERNAL_METADATA | GenreProcessor-Fallback-Kette |
| `ALBUM_RELEASE_ID_INCONSISTENT` | EXTERNAL_METADATA | alle Tracks auf DIE Release-ID mappen |
| `ARTWORK_MISSING` / `_INVALID` / `_LOW_RESOLUTION` / `_NON_SQUARE` / `ALBUM_COVER_INCONSISTENT` | COVER | `CoverProcessor` — nur ersetzen bei eindeutig besserem Cover |
| `LOUDNESS_TAG_MISSING` / `_INVALID` / `_PARTIAL` | LOUDNESS | LUFS prüfen, nur bei Abweichung normalisieren (kein Doppel-Encoding) |
| `DUPLICATE_EXACT` / `DUPLICATE_RECORDING` | DUPLICATE | `resolve_duplicates.py` — nur mit `--allow-delete` + Freigabe |

---

## 5. Geplant (Phase 2 PR 2+, noch nicht implementiert)

- **Repair Executor** mit `--apply` (Standard bleibt DRY-RUN) und
  separatem `--allow-delete` für destruktive Aktionen.
- **Safety-Prüfung** vor jeder Änderung (Prompt Abschnitt 14): Datei
  existiert, Pfad in erlaubter Library, erwarteter Typ, kein Symlink-Escape,
  Hash/mtime bekannt, Änderung erwartungsgemäß. Keine globalen
  `rename()`/`move()`/`unlink()` ohne Prüfung.
- **Before/After-Dokumentation** pro Reparatur (Prompt Abschnitt 15).
- **Repair Journal** (Prompt Abschnitt 17): Datei, alte/neue Werte, Aktion,
  Zeit, Status, Fehler, Rollback-Info. Bestehende Projektmechanismen
  bevorzugen.
- **Verification Scan** nach jeder Reparaturgruppe (Prompt Abschnitt 16):
  erneut scannen, Health vorher/nachher, „Resolved" / „Remaining". Ein
  Repair darf den Score nicht verbessern, indem er Probleme versteckt.
