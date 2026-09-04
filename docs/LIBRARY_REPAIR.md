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

**Status:**
- **Repair Planner** — vollständig, read-only.
- **Repair Executor — Level 1 (Tag-Fixes)** — vollständig, mit Per-Datei-Backup
  (außerhalb der Library), Journal, Before/After, Audio-Essenz-Verifikation
  und Verification-Scan. Bereits gegen die Produktions-Library gelaufen
  (12 Tag-Fixes, 12/12 SUCCESS, Ton byte-identisch, 0 neue Issues).
- **Level 2 / 3 / Cover / Loudness / Duplicate Executor** — noch offen,
  `--allow-delete` wird abgelehnt.

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

# Level-1-Tag-Fixes ausführen
python scripts/library_repair.py --level SAFE_AUTOMATIC --apply --dry-run   # Before/After-Vorschau
python scripts/library_repair.py --level SAFE_AUTOMATIC --apply             # tatsächlich + Verification-Scan
```

**DRY-RUN ist Standard.** Ohne `--apply` erzeugt das Script nur einen Plan —
es verändert nichts, verschiebt nichts, löscht nichts, ruft keinen externen
Dienst. Der Health-Scan (`--report` weggelassen) ist selbst vollständig
read-only.

Mit `--apply` führt der **Level-1-Executor** ausschließlich die vier
deterministischen Tag-Fixes aus (`L1_TAG_CODES`) — alle anderen Kandidaten
werden übersprungen. `--apply --dry-run` zeigt die konkreten Before/After-
Werte, ohne zu schreiben. `--allow-delete` wird abgelehnt (keine
destruktive Reparatur implementiert).

---

## 2. Architektur

`services/library_repair/` (Muster wie `services/library_health/` /
`services/duplicate/`):

```text
models.py      RepairLevel / RepairAction / RepairSpec / RepairCandidate / RepairPlan
planner.py     plan_repairs(report_dict) -> RepairPlan  (reine Funktion, kein I/O)
               + REGISTRY: genau ein Repair-Mapping pro Health-Issue-Code
               + filter_plan(plan, artist=/issue_code=/severity=/level=)
report.py      render_plan_text(plan)
tag_repairs.py Level-1-Reparatur-Funktionen (pure): (alte Tag-Werte) -> (neue) | None
journal.py     RepairJournal — Append-Only JSONL, Before/After + Rollback-Info
executor.py    apply_level1(candidates, library_root, journal, dry_run=) -> [ExecOutcome]
               safety_check(path, library_root) -> Ablehnungsgrund | None
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

## 5. Level-1-Executor (implementiert)

`--apply` führt **nur** die vier verlustfreien, deterministischen Tag-Fixes
aus (`GENRE_DELIMITER_INCONSISTENT`, `MULTI_ARTIST_*`,
`META_ALBUM_ARTIST_MISSING`, `ALBUM_ARTIST_INCONSISTENT`) — Rename-basierte
L1-Fixes (`FILENAME_*`) sind bewusst noch nicht dabei.

Ablauf pro Datei (Prompt Abschnitt 13–17):

1. **Safety-Prüfung** (`safety_check`): kein Symlink, Pfad real innerhalb der
   Library, reguläre `.m4a`-Datei, nicht leer. Bei Verletzung → `SKIPPED`.
2. Betroffene Atome lesen → Reparaturwert via `tag_repairs.*` berechnen.
   Nicht eindeutig / nichts zu tun → `SKIPPED`.
3. `--dry-run`: Before/After ins Journal, kein Schreibvorgang.
4. Echter Lauf: SHA-256 + **Audio-Essenz-MD5** (`ffmpeg -map 0:a -f md5`)
   der Datei, dann **Backup** nach `<library>/../.library_repair_backups/…`
   (außerhalb der Library — stört weder Scan noch Navidrome).
5. Auf einer **temporären Sibling-Kopie** taggen; verifizieren, dass genau
   die Ziel-Atome den erwarteten Wert haben **und die Audio-Essenz
   byte-identisch** ist; erst dann atomar per `Path.replace()` übernehmen.
   Schlägt die Verifikation fehl → Backup zurückspielen, `FAILED`.
6. **Journal** (`library_repair_journal.jsonl`, Append-Only): Zeit, Datei,
   Issue, Aktion, Status, Before/After, SHA-256 + Audio-MD5 vorher/nachher,
   Backup-Pfad. Rollback = Backup-Datei zurückkopieren.
7. **Verification-Scan** nach der Gruppe: Library erneut scannen, Health
   vorher/nachher, Ziel-Issue-Codes müssen sinken, **keine neuen oder
   gestiegenen Issue-Codes** (sonst Exit 1 — ein Repair darf nichts
   verstecken, Prompt Abschnitt 16).

**Erster Produktionslauf (2026-09-04):** 12 Kandidaten (3× Genre-Delimiter,
9× Multi-Artist-Split), 12/12 `SUCCESS`, Audio byte-identisch, Health
97.9 → 97.9 (waren INFO), `GENRE_DELIMITER_INCONSISTENT 3→0`,
`MULTI_ARTIST_INCONSISTENT 9→0`, keine neuen Issues. Backups unter
`/mnt/musik_bilder/.library_repair_backups/`.

## 6. Noch offen (Phase 2)

- **Level-1-Rename** (`FILENAME_TITLE_MISMATCH` / `FILENAME_SUSPICIOUS`) —
  braucht die Rename-Safety-Maschinerie (TOCTOU, Kollision, nur im selben
  Verzeichnis).
- **Level 2** (`reprocess_artist_metadata.py` als Subprozess orchestrieren).
- **Level 3** (MusicBrainz-/Genre-Nachträge, nur bei eindeutigem Match).
- **Cover** (`CoverProcessor` — nur ersetzen bei eindeutig besserem Cover).
- **Loudness** (`normalize_test_library_loudness.py` — kein Doppel-Encoding).
- **Duplicate** (`resolve_duplicates.py` — destruktiv, `--allow-delete`).
