# MusicBot — Smart Library Repair (Phase 2)

Leitet aus den Findings des [Library Health Scanners](LIBRARY_HEALTH.md)
konkrete, sichere, nachvollziehbare Reparaturaktionen ab.

```text
LIBRARY → Health Scanner → Health Report → Repair Planner
                                              │
                                       ┌──────┴──────┐
                                     SAFE FIX   MANUAL REVIEW
                                       │
                                  Repair Executor   ← alle 8 Executoren implementiert, gegen Produktion gelaufen
                                       │
                                  Verification Scan
                                       │
                                  Before / After Report
```

**Status** — alle Executors mit Per-Datei-Backup (außerhalb der Library),
Append-Only-Journal, Before/After, **Audio-Essenz-Verifikation** und
Verification-Scan; alle bereits gegen die Produktions-Library gelaufen.

> **Merge-Historie:** PR #145 hat per Squash nur Repair Planner + Level-1-
> Tag-Fixes auf `main` gebracht. Level-1-Renames, Cover, ALBUM_COVER_INCONSISTENT
> und Level 3 kamen per **PR #146** nach (dieselben Commits, die bereits gegen
> Produktion liefen — `main` war vorübergehend hinter dem realen Library-Stand).

| Executor | Zustand | Produktionslauf |
|---|---|---|
| Repair Planner | ✅ read-only | — |
| **Level 1 — Tag-Fixes** | ✅ | 12/12 SUCCESS |
| **Level 1 — Renames** | ✅ | 7/7 SUCCESS (`FILENAME_TITLE_MISMATCH 14→7`) |
| **Cover** (`CoverProcessor`, only-if-better) | ✅ | makko-Album 6× 300→3000px |
| **`ALBUM_COVER_INCONSISTENT`** (offline, best-existing) | ✅ | 198 SUCCESS, `19→0`, Health 97.9→98.0 |
| **Level 3 — MusicBrainz-IDs / ISRC** | ✅ | DRY-RUN 01099: 6 Nachträge; Prod-Lauf: 0 sichere Treffer (MB-Abdeckung für Deutschrap/2Pac-Bootlegs gering) |
| **Level 2 — volle Neuverarbeitung** (`track_reprocessor.process_file`) | ✅ | makko 19/19 SUCCESS (`META_TITLE_NOT_CLEAN 19→0`); Cover-Nebeneffekt via Album-Cover-Executor 4/4 |
| **Loudness** (`apply_replaygain`, verlustfreier RG-Tag) | ✅ | 133/133 SUCCESS (99 SET + 34 CLEAR), `LOUDNESS_OFF_TARGET 133→0`, Health 98.0 |
| **Duplicate** (`resolve_duplicates.py`, andockt) | ✅ | Prod-Scan: 388 Dateien, 2 Gruppen, 0 auto-resolvable (beide korrekt MANUAL_REVIEW) |

---

## 1. Nutzung

```bash
python scripts/library_repair.py                      # frischer read-only Scan → Plan
python scripts/library_repair.py --report r.json      # Plan aus vorhandenem Health-Report
python scripts/library_repair.py --json plan.json     # Plan als JSON

# gezielt (Prompt Abschnitt 19)
python scripts/library_repair.py --artist 01099
python scripts/library_repair.py --issue LOUDNESS_OFF_TARGET
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

Mit `--apply` führt der **Level-1-Executor** die deterministischen Tag-Fixes
(`L1_TAG_CODES`) **und** die Dateinamen-Renames (`L1_RENAME_CODES`:
`FILENAME_TITLE_MISMATCH`, `FILENAME_SUSPICIOUS`) aus — alle anderen
Kandidaten werden übersprungen. `--apply --dry-run` zeigt die konkreten
Before/After-Werte, ohne zu schreiben. `--allow-delete --artist <X>` ist ein
eigener, von `--apply` unabhängiger Pfad für Duplicate-Auflösung (§6d).

Ein `--apply`-Lauf mit mindestens einem echten `SUCCESS`-Outcome löst danach
automatisch einen Navidrome-Scan aus (`--no-navidrome-scan` unterdrückt das,
siehe §8).

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
tag_repairs.py    Level-1-Tag-Reparatur-Funktionen (pure): (alte Werte) -> (neue) | None
rename_repairs.py Level-1-Dateinamen-Funktionen (pure): (Name + Kontext) -> neuer Name | None
journal.py       RepairJournal — Append-Only JSONL, Before/After + Rollback-Info
executor.py      apply_level1() / apply_level1_rename() / apply_cover_repairs() /
                 apply_level2() / apply_replaygain() -> [ExecOutcome]
                 safety_check(path, library_root) -> Ablehnungsgrund | None
                 (Duplicate-Auflösung läuft NICHT über executor.py, sondern über
                 den eigenständigen Andock-Pfad `--allow-delete` → §6d)
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
| `METADATA_REPROCESSING` | volle Neuverarbeitung über die echte Pipeline | `services/metadata/track_reprocessor.py::process_file` (in-process, echte config.Config — **nicht** `scripts/reprocess_artist_metadata.py`, siehe Kasten unten) | ja | ja | nein |
| `EXTERNAL_METADATA` | fehlende MB-IDs / ISRC | `MusicBrainzClient` | ja | ja | nein |
| `COVER` | fehlendes / schlechtes / uneinheitliches Cover | `CoverProcessor` | ja | ja | nein |
| `LOUDNESS` | gemessene Lautheit > 2 dB neben −16 LUFS (`LOUDNESS_OFF_TARGET`) | `replaygain_repairs` — verlustfreier `replaygain_track_gain`-Tag | ja | ja | nein (Audio byte-identisch) |
| `DUPLICATE` | echte Duplikate | `scripts/resolve_duplicates.py` + `services/duplicate/*` (angedockt, Backup-vor-Delete) | ja | nein | **ja** |
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
| `META_ARTIST_MISSING` / `_TITLE_MISSING` / `_ALBUM_MISSING` | METADATA_REPROCESSING | `track_reprocessor.process_file()` |
| `META_TITLE_NOT_CLEAN` | METADATA_REPROCESSING | Titel über die reale Pipeline bereinigen (Anführungszeichen/`prod.`/Marketing-Suffix raus), Audio unverändert |
| `GENRE_INVALID` / `LYRICS_*` | METADATA_REPROCESSING | Genre/Lyrics neu bestimmen |
| `META_GENRE_MISSING` / `GENRE_EMPTY` | METADATA_REPROCESSING | GenreProcessor läuft bereits identisch zu `GENRE_INVALID` als Teil der vollen Pipeline (Production-Audit 2026-09-08: vorher fälschlich `EXTERNAL_METADATA` ohne Executor) |
| `META_MB_*_MISSING` / `META_ISRC_MISSING` | EXTERNAL_METADATA | MusicBrainz-Match (nur bei Eindeutigkeit) |
| `META_YEAR_MISSING` | MANUAL_REVIEW | keine Jahr-Fetch-Implementierung vorhanden (Production-Audit 2026-09-08: vorher fälschlich `EXTERNAL_METADATA` ohne Executor) |
| `ALBUM_RELEASE_ID_INCONSISTENT` | MANUAL_REVIEW | mehrere Release-IDs im Album — welche kanonisch ist, manuell entscheiden (würde bestehende Werte überschreiben müssen statt nur fehlende zu ergänzen; Production-Audit 2026-09-08: vorher fälschlich `EXTERNAL_METADATA` ohne Executor) |
| `ARTWORK_MISSING` / `_INVALID` / `_LOW_RESOLUTION` / `_NON_SQUARE` / `ALBUM_COVER_INCONSISTENT` | COVER | `CoverProcessor` — nur ersetzen bei eindeutig besserem Cover |
| `LOUDNESS_OFF_TARGET` | LOUDNESS | `replaygain_track_gain`-/`_peak`-Tag schreiben (Ziel −16 LUFS, **Audio byte-identisch**), Backup + Rollback |
| `LOUDNESS_TAG_MISSING` | NOT_REPAIRABLE | Legacy-ReplayGain-Tag; aktuelle Pipeline schreibt ihn bewusst nicht |
| `LOUDNESS_TAG_INVALID` / `_PARTIAL` | MANUAL_REVIEW | kaputter/unvollständiger Legacy-Tag — manuell prüfen |
| `DUPLICATE_EXACT` / `DUPLICATE_RECORDING` | DUPLICATE | `library_repair.py --allow-delete --artist <X>` → `resolve_duplicates.py` (Backup-vor-Delete, TOCTOU-Revalidierung) |

---

## 5. Level-1-Executor (implementiert)

`--apply` führt aus:
- **Tag-Fixes** (`GENRE_DELIMITER_INCONSISTENT`, `MULTI_ARTIST_*`,
  `META_ALBUM_ARTIST_MISSING`, `ALBUM_ARTIST_INCONSISTENT`)
- **Renames** (`FILENAME_TITLE_MISMATCH`, `FILENAME_SUSPICIOUS`) — nur im
  selben Verzeichnis, ersetzt **nur den Titel-Teil** und lässt den
  vorhandenen `NN - ` / `YYYY - `-Präfix unverändert (keine geratene
  Ordner-Konvention — realer Finalaudit-Fehler: `2025 - …` wäre sonst zu
  `01 - …` geworden). Nur wenn der Titel-Teil den Titel-Tag als Präfix
  enthält und sich nur durch abschließenden Zusatz (`prod./feat./(…)`)
  unterscheidet — schützt vor Tag-Tippfehlern; nicht-triviale Abweichung
  → `SKIPPED`. Zielname atomar per `O_EXCL` beansprucht (TOCTOU),
  Byte-Inhalt vorher==nachher verifiziert, kein Content-Backup
  (Rename ändert keine Bytes; Rollback = zurück-benennen via Journal).

Ablauf pro Tag-Fix-Datei (Prompt Abschnitt 13–17):

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

### Per-Repair-Verification je Datei (Library-Closure-Phase, 2026-09-09)

Zusätzlich zum aggregierten Verification-Scan (Schritt 7) prüft der
Executor nach **jedem echten `SUCCESS`** die betroffene Datei einzeln
erneut (`_verify_issue_resolved()` → frische
`services/library_health`-Einzeldatei-Analyse). Ist der auslösende
Issue-Code danach weiterhin da → `ExecOutcome.status = "UNRESOLVED"` statt
`SUCCESS` (im Journal ebenso). Rein additiv: `SUCCESS` wird nur
herabgestuft, nie etwas hochgestuft; ein strukturell unmöglicher Recheck
lässt `SUCCESS` unangetastet.

- Beteiligt: `apply_level1` (Tag), `apply_level1_rename`,
  `apply_cover_repairs`, `apply_external_metadata` — jeweils file-scope-Codes.
- **Nicht** beteiligt (im Code begründet): album-scope
  (`ALBUM_ARTIST_INCONSISTENT`, `ALBUM_COVER_INCONSISTENT` → Gruppen-Analyse
  des aggregierten Scans), `LOUDNESS_OFF_TARGET` (RG-Tag bringt die
  effektive Lautheit per Konstruktion aufs Ziel; Atom-/Audio-Verifikation
  deckt den Rest; LUFS-Ebene = `--measure-loudness`-Scan), `apply_level2`
  (hat die feinere `_l2_issue_resolved()`-Zielfeldbindung).
- `UNRESOLVED` zählt wie `SUCCESS` als „auf der Platte geändert" (Navidrome-
  Auto-Scan, `touched`-Set), aber **nie** als behoben —
  `repair_service.execute_safe_automatic_repair()` markiert ein solches
  Finding über sein eigenes Rescan-Gate weiterhin **nicht** als `RESOLVED`.

Die vollständige Code→Disposition→Executor→Verifikations-Abdeckung:
[`docs/audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md`](audits/LIBRARY_CLOSURE_COVERAGE_MATRIX_2026-09-09.md)
(maschinell gepinnt in `tests/test_library_repair_disposition_matrix.py`).

## 5a. Cover-Executor (implementiert)

`--level COVER` bzw. `--issue ARTWORK_*` (NIE im Default-`--apply` — Cover
ist extern/Netzwerk und langsam): `apply_cover_repairs()` für
`ARTWORK_MISSING` / `ARTWORK_INVALID` / `ARTWORK_LOW_RESOLUTION` /
`ARTWORK_NON_SQUARE`.

- Die Cover-Suche (`CoverProcessor.get_cover_art()`) wird **immer**
  ausgeführt, auch bei vorhandenem Cover (bestehende Projektregel).
- `cover_repairs.decide_cover_action()` (rein) entscheidet only-if-better
  (Prompt Abschnitt 9): Kandidat muss ≥ 400 px, quadratisch (5 %-Toleranz)
  sein; bei `LOW_RESOLUTION` mind. +200 px Kantenzuwachs; bei `NON_SQUARE`
  quadratisch **und** kein Auflösungsverlust. Sonst `SKIPPED` — **das
  vorhandene Cover wird nie durch ein gleich gutes/schlechteres ersetzt.**
- Schreibvorgang wie beim Tag-Executor: Backup außerhalb der Library →
  `covr`-Atom auf temp-Sibling → verifizieren (Cover-SHA + Audio-Essenz
  byte-identisch) → atomarer `replace`, sonst Rollback.
- **Album-Cache:** alle Tracks eines Album-Ordners bekommen dasselbe Cover
  (eine Suche pro Album) — verhindert, dass ein per-Track-Repair eine
  `ALBUM_COVER_INCONSISTENT` erst erzeugt. Singles werden per Track gesucht.
- `ALBUM_COVER_INCONSISTENT` (Vereinheitlichung eines bereits uneinheitlichen
  Albums) ist **nicht** dabei — folgt separat.

**Produktionsläufe (2026-09-04):**
- `--issue ARTWORK_MISSING`: 5/5 `SKIPPED` — `CoverProcessor` fand kein Cover
  (2Pac-Bonus/Visualizer, makko-Remix, alle ohne MB-IDs). Kein Overwrite.
- `--artist makko --issue ARTWORK_LOW_RESOLUTION --apply`: **6/6 `SUCCESS`** —
  `makko/2020 - Poesie gemischt mit Bier/` alle 6 Tracks 300×300 → **3000×3000**
  (Apple Music, dasselbe Cover via Album-Cache). Audio byte-identisch,
  Verification-Scan grün (`ARTWORK_LOW_RESOLUTION 19→13`, keine neuen Issues).
- Die übrigen 13 `LOW_RESOLUTION` (2Pac / Toobrokeforfiji): `SKIPPED` —
  `CoverProcessor` fand nur ≤300px, kein Downgrade.

## 6. Noch offen (Phase 2)

Keine offenen Executoren mehr — Phase 2 ist mit §6d (Duplicate) komplett.

## 6a. Level-2-Executor — volle Neuverarbeitung (implementiert)

`--level METADATA_REPROCESSING` bzw. `--issue META_TITLE_NOT_CLEAN` /
`GENRE_INVALID` / `LYRICS_*` / `META_{ARTIST,TITLE,ALBUM}_MISSING` /
`META_GENRE_MISSING` / `GENRE_EMPTY` (extern, langsam — **nie** im
Default-`--apply`): `apply_level2(reprocess)`.

> **Klarstellung (Production-Audit 2026-09-08):** `apply_level2()` ruft
> `services/metadata/track_reprocessor.py::process_file()` **direkt
> in-process** auf — **nie** `scripts/reprocess_artist_metadata.py` als
> Subprozess oder sonst wie. Das Skript ist ein davon unabhängiges,
> eigenständiges CLI-Testwerkzeug mit eigenem `ALLOWED_ROOT =
> /tmp/musicbot_test`-Guard, das denselben Kern importiert, aber
> strukturell nicht gegen die Produktionslibrary laufen kann (siehe unten)
> und ausschließlich manuell/per Telegram-„Reprocessing"-Menü
> (`reprocessing_runner.py`, §6a unten) ausgelöst wird — unabhängig vom
> Finding→Repair-Flow dieses Dokuments.

`apply_level2()` behandelt **je Issue-Code** einer Datei ein eigenes
`ExecOutcome` (Production-Audit 2026-09-08, Fix 2026-09-08): `SUCCESS`
gilt nur, wenn das für den jeweiligen Code relevante Zielfeld (z. B.
`lyrics_present` für `LYRICS_MISSING`) sich laut Pipeline-Diff tatsächlich
geändert hat — nicht schon, wenn irgendein anderes Feld der Datei sich
änderte (`process_file()` läuft immer als volle Pipeline, ändert daher oft
mehrere Felder gleichzeitig).

**Issue-spezifischer Hint (PR #177/#178):** betrifft genau **ein**
Issue-Code eine Datei, reicht `apply_level2()` diesen als
`process_file(requested_issue=…)` durch — in **beiden** Zweigen (DRY-RUN
*und* EXECUTE; die Execute-Durchreichung fehlte in PR #177 und wurde in
PR #178 nachgezogen, sonst wich die Vorschau vom `--apply`-Ergebnis ab).
Für `LYRICS_MISSING` / `GENRE_INVALID` unterdrückt `process_file()` dann
den Artist-`normalize()`-Nebeneffekt (bestehende, bereits kanonische
©ART-Tags bleiben unangetastet) und das „ReplayGain/Loudness fehlt"-
UNRESOLVED (für einen reinen Lyrics-/Genre-Fix nicht relevant). Bei
mehreren Codes pro Datei bleibt `requested_issue=None` → volles
Pipeline-Verhalten.

> **Reichweite (Nachprüf-Durchgang 2026-09-09):** `apply_level2()` und
> damit `requested_issue` sind **CLI-only** (`library_repair.py
> --level METADATA_REPROCESSING` bzw. `--issue <L2-Code>`). Die
> Telegram-Pfade — „MusicBot Doctor" (`doctor_runner.py`) und „Repair
> MusicBot" (`repair_service.py`) — rufen ausschliesslich
> `--level SAFE_AUTOMATIC --apply` auf; L2-Kandidaten werden dort doppelt
> ausgeschlossen (Planner-Level-Filter `filter_plan(level="SAFE_AUTOMATIC")`
> **und** das `l2_requested`-Gate in `main()`). Auch die Telegram-
> „Reprocessing"-Ansicht erreicht `requested_issue` nicht — sie ruft
> `process_file()` über `scripts/reprocess_artist_metadata.py` ohne den
> Parameter (immer `None` → volles Pipeline-Verhalten). Gepinnt in
> `tests/test_library_repair_cli_safe_automatic_scope.py`.

**Option 2a (Nutzer-Entscheidung 2026-09-04):** Der Kern von
`scripts/reprocess_artist_metadata.py` (`process_file()` + `snapshot()` +
alle Helfer, ~925 Zeilen) liegt jetzt in
`services/metadata/track_reprocessor.py` — **verhaltensgleich**, die
importlib-geladenen `tests/test_reprocess_artist_metadata*.py` (87) sind
die Charakterisierung. Das Script behält `ALLOWED_ROOT = /tmp/musicbot_test`,
seine Path-Safety, den `ReprocessLogger` und die Post-Run-Snapshots und
importiert den Kern nur noch. Das Telegram-Menü
(`services/metadata/reprocessing_runner.py`, Subprozess, test-only) ist
unberührt.

- Ein `reprocess()`-Lauf pro Datei (die L2-Codes treffen oft dieselbe
  Datei). `_build_reprocess()` im CLI konstruiert `EnhancedMetadataProcessor`
  + MB-/LastFM-Client **einmal** mit der echten `config.Config`.
- `process_file()` schreibt **in-place ohne eigenes Backup** → der Executor
  legt VOR dem Aufruf eine Per-Datei-Kopie außerhalb der Library an und
  prüft danach verbindlich, dass die **Audio-Essenz** (dekodierter Stream,
  container-unabhängig) byte-identisch ist. Jede Abweichung, ein
  Pipeline-`status == "error"` oder ein von der Pipeline selbst gemeldetes
  `audio_essence_changed` / `audio_stream_changed` → **Rollback** (inkl.
  Rücknahme eines evtl. schon erfolgten Renames).
- `unresolved`-Hinweise der Pipeline (z. B. „ReplayGain fehlt") werden in
  `ExecOutcome.reason` **durchgereicht**, nicht verschluckt.
- **Nebeneffekt, bewusst = echtes Pipeline-Verhalten:** im EXECUTE-Modus
  aktualisiert `process_file()` die Auto-Learn-Mappings
  (`mapping/auto_learned_*`) mit den beobachteten Feature-Artists/Genres —
  wie bei einem frischen Download. Das CLI weist im EXECUTE-Modus darauf hin.
- DRY-RUN: `process_file(dry_run=True)` schreibt nichts, liefert eine
  Vorhersage; `ExecOutcome` = `DRY_RUN` mit Before/After aus dieser
  Vorhersage.

> **Betriebs-Hinweis — Cover + Teil-Album-Läufe:** `process_file()` ersetzt
> das eingebettete Cover, **sobald** die Pipeline ein abweichendes Cover
> liefert — nicht „nur wenn besser" wie der Cover-Executor (§5a). Betrifft
> ein L2-Lauf nur *einen Teil* der Tracks eines Albums (z. B. `--issue
> META_TITLE_NOT_CLEAN` traf nur 5 von 20 Tracks), können danach im Album
> unterschiedliche Cover-Abmessungen stehen → neuer `ALBUM_COVER_INCONSISTENT`
> (INFO). Der Verification-Scan meldet das (Exit 1). **Nacharbeit:** direkt
> `library_repair.py --artist <A> --issue ALBUM_COVER_INCONSISTENT --apply`
> — der Album-Cover-Executor hebt alle Tracks offline auf das je vorhandene
> beste Cover (nie Downscale).

**Produktionslauf 2026-09-04 (`--artist makko --issue META_TITLE_NOT_CLEAN`):**
19/19 SUCCESS, Audio byte-identisch. Titel `"X"` / `"X" prod. Y` → `X` (alle
19), 2 Renames (`ADLIBS`, `WEIN`), 1 Rename korrekt blockiert (`Echt/Nie…`
mit `/` im Titel → unresolved), 7 Dateien MB-IDs ergänzt, 1× Lyrics,
`META_TITLE_NOT_CLEAN 19→0`, `LYRICS_MISSING 12→11`, Health 97,8→98,0.
Anschließend `ALBUM_COVER_INCONSISTENT` (Cover-Nebeneffekt, s. o.) mit dem
Album-Cover-Executor behoben: 4/4 SUCCESS, `2→0`, Verification grün.

## 6b. Loudness-Executor — verlustfreier ReplayGain-Tag (implementiert)

`--level LOUDNESS` bzw. `--issue LOUDNESS_OFF_TARGET` (nie im
Default-`--apply`): `apply_replaygain(measure_fn)`.

Setzt `LOUDNESS_OFF_TARGET` aus dem Health-Report voraus, d. h. der Report
muss mit `library_health_check.py --measure-loudness` erzeugt worden sein.

**Nutzer-Entscheidung 2026-09-04: kein Re-Encode.** Die Download-Pipeline
normalisiert frische Downloads bereits per FFmpeg-loudnorm (Schritt 15b,
`enhanced_metadata_processor.py`) und läuft konstant. Für den Altbestand
reicht ein **verlustfreier** ReplayGain-Tag — ein RG-fähiger Player
(Navidrome) bringt die Datei damit auf die Ziel-Lautheit, das Audio bleibt
**byte-identisch**. Der vollständige Re-Encode-Executor wurde bewusst nicht
gebaut; `scripts/normalize_test_library_loudness.py` bleibt test-only.

- **`replaygain_repairs.compute_replaygain(existing_gain_db=…)`** (rein) →
  `(SET, {atome})` / `(CLEAR, None)` / `(None, None)`:
  - `----:com.apple.iTunes:replaygain_track_gain` = `"{−16 − gemessen:.2f} dB"`
  - `----:com.apple.iTunes:replaygain_track_peak` = linearer Peak aus dem
    True Peak (`10^(dBTP/20)`)
  - **CLEAR** entfernt vorhandene RG-Atome, wenn die Datei bereits auf Ziel
    liegt, aber einen abweichenden Gain-Tag trägt (real: 34 Badchieff-/
    2Pac-Dateien mit einem RG-Tag aus einer früheren Quelle, der einen
    RG-Player auf ~−20 LUFS herunterregeln würde).
  - `(None, None)`, wenn keine Messung vorliegt oder der aktuelle Zustand
    (Datei-LUFS + evtl. Tag) bereits ≤ 2 dB neben −16 LUFS liegt.
- **Referenz = −16 LUFS**, NICHT die RG-2.0-Norm −18: so klingen die
  getaggten Altbestände in Navidrome genauso laut wie die frisch
  heruntergeladenen (ungetaggten) Dateien, die Navidrome auf Dateilautstärke
  (−16) spielt. Im Code + `_analyze_loudness_measurement` begründet.
- Sicherheitsmodell wie L1: `safety_check`, Backup außerhalb der Library,
  Schreiben auf temp-Sibling → Verifikation (Ziel-Atome gesetzt **und**
  Audio-Essenz-MD5 byte-identisch) → atomarer `replace`, Rollback bei Fehler,
  Journal. Verification-Scan läuft danach **mit** `--measure-loudness`.
- Der Health-Check `LOUDNESS_OFF_TARGET` berücksichtigt einen vorhandenen
  RG-Tag (`effective = gemessen + gain`) → nach `apply_replaygain` sinkt der
  Code sauber, Verification-Scan bleibt grün.
- DRY-RUN: nur Messung + berechneter Gain, kein Schreibvorgang.

**Realer Bestand 2026-09-04 (`--measure-loudness`):** 99/388 Dateien (26 %)
off-target, 97 zu laut (Median +5,2 dB, bis +7,9 dB; einige clippend mit
True Peak > 0 dBFS), fast ausschließlich der makko-Katalog (89) + Levin Liam
(8) + 2Pac (2). Produktionslauf ist ein eigener Freigabe-Schritt.

> **Folge-Analyse (nach dieser Phase):** `enhanced_metadata_processor.py`
> Schritt 15b — prüfen, ob die Loudness-Normalisierung der Download-Pipeline
> tatsächlich auf −16 LUFS schreibt (LUFS-Einstellungen /
> `AudioEnhancer.get_target_lufs`).

## 6d. Duplicate — `--allow-delete` (implementiert, dockt an)

`--allow-delete --artist <Name> [--dry-run]` — **kein eigener Lösch-Code**:
`library_repair.py` dockt als Subprozess an das bereits gehärtete
`scripts/resolve_duplicates.py` an (Klassifikation/Resolution-Matrix/
Zwei-Stufen-Execute-Sicherheit dort unverändert, siehe
`docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md`). Läuft **unabhängig**
vom Health-Report/Planner — `resolve_duplicates.py` führt seine eigene
Duplicate-Erkennung (normalisierter Artist+Titel, Album-vs-Single-Priorität
über die Pfadstruktur) durch, nicht die des Health-Scanners.

- **Erfordert `--artist`** — nie der gesamte Library-Root (spiegelt
  `resolve_duplicates.py`s eigene `--confirm-production-execute`-Zusatzsperre,
  die zwingend einen konkreten Unterordner verlangt).
- `--dry-run` (Default) → reiner Scan-Subprozess (`resolve_duplicates.py
  --path <root>/<Artist>`, read-only, kein `--execute`).
- Ohne `--dry-run` → `--execute --confirm-production-execute`: **echte
  Löschung** der revalidierten REMOVE-Kandidaten (Fingerprint-/TOCTOU-
  Pre-Delete-Revalidierung, Gruppen-Atomarität — siehe Architektur-Dokument).

**Neu — Backup-vor-Delete** (`services/duplicate/execution.py::
execute_group(backup_fn=…)`, optionaler DI-Parameter wie
`validate_file_within_root`/`build_candidate_from_path`): jede Datei wird
UNMITTELBAR vor `unlink()` nach `--backup-dir` (Default
`<root>/../.library_repair_backups`, identische Konvention zum übrigen
`library_repair`) kopiert; schlägt das Backup fehl, wird **nicht** gelöscht
(`FAILED` statt Delete ohne Sicherungskopie). Ohne `backup_fn` (Aufrufer, die
den Parameter nicht setzen) bleibt das Verhalten exakt wie zuvor — die
frühere, bewusste Architekturentscheidung „kein Rollback-Versprechen"
(Auftrag Abschnitt 17 des Architektur-Dokuments) gilt dort unverändert.
Audit-Log (`/tmp/musicbot_test/duplicate_execution_audit_log.jsonl`) trägt
jetzt zusätzlich `backup_path`.

**Read-only Dry-Run gegen Produktion (2026-09-04, `--path
/mnt/musik_bilder/library`, ohne Code-Änderung — bereits vorher production-
dry-run-fähig):** 388 Dateien gescannt, **2 Duplicate-Gruppen**, **0
auto-resolvable**, beide korrekt `MANUAL_REVIEW`:
- 2Pac „Changes" — Album-Version (2009 Immortal) vs. Single (2011), Δ11,3s
  Laufzeit → vermutlich unterschiedlicher Edit, kein MusicBrainz-Match.
- makko „Nachts wach" — zwei Tracks im selben `2022 - Nachts wach (Remix
  EP)`-Ordner (Track 02 + 04) → `album_context_risk: HIGH`, vermutlich
  Original + Remix, keine echten Duplikate.

Ein echter `--execute`-Produktionslauf ist damit aktuell nicht angezeigt —
die Library enthält keine sicher automatisch auflösbaren Duplikate.

## 7. Level-3 — MusicBrainz-IDs / ISRC nachtragen (implementiert)

`--level EXTERNAL_METADATA` bzw. `--issue META_MB_RECORDING_MISSING` /
`META_MB_RELEASE_MISSING` / `META_ISRC_MISSING` (extern/rate-limited — nie
im Default-`--apply`): `apply_external_metadata(mb_lookup)`.

- Ein Kandidat pro Datei (die 3 Issue-Codes betreffen oft dieselbe Datei).
- `mb_lookup(artist, title)` = `MusicBrainzClient.fetch_metadata()`. Die
  **Eindeutigkeit** des Matches prüft der Client selbst
  (`Config.MUSICBRAINZ_MIN_SIMILARITY` / `MIN_ARTIST_SIMILARITY`, MB-01) —
  kein sicherer Treffer → leeres Ergebnis → `SKIPPED`.
- Zusätzliche Leitplanken in `external_metadata.plan_id_writes()` (rein):
  - **`title_is_trustworthy()`** — unsaubere/geparste Titel (Produzenten-
    Credit, dateinamens-illegale Zeichen, absurde Länge) → gar keine
    externe Suche (der Nutzerwunsch „nur korrekt geparste Dateien").
  - MB-Titel muss zum Datei-Titel passen (Substring oder ≥ 60 % Token-Overlap).
  - Formatvalidierung: MBID muss UUID sein, ISRC dem ISRC-Muster entsprechen.
  - **Nur FEHLENDE** Felder werden ergänzt — vorhandene IDs nie überschrieben.
- Schreibvorgang: Backup → freeform-Atome auf temp-Sibling → Verifikation
  (Atome + Audio-Essenz byte-identisch) → atomarer `replace`, sonst Rollback.
- Atom-Namen deckungsgleich zu `services/metadata/tag_writer.py`.

## 8. Navidrome-Scan-Automation (Phase 3, P1.2, implementiert)

Nach einem `--apply`-Lauf löst `scripts/library_repair.py` automatisch
`NavidromeScanTrigger.run_scan()` aus (`utils/navidrome_scan_trigger.py`,
derselbe Subprozess-Pfad wie der manuelle „🔄 Scan"-Button im
Telegram-Menü) — **aber nur, wenn tatsächlich etwas geändert wurde.**

**Änderungs-Erkennung:** wiederverwendet exakt den bereits vorhandenen,
ungefilterten `tally = Counter(o.status for o in outcomes)`-Wert (Ausgabe
der `N success · M would-change · ...`-Zeile) — `tally.get("SUCCESS", 0) > 0`.
Keine neue/eigene Definition von „es gab eine Änderung"; `DRY_RUN` zählt
nicht als Änderung, ein Lauf ohne ausführbare Kandidaten (`"Keine
ausfuehrbaren Reparaturen..."`) erreicht diesen Codepfad gar nicht erst.

**Steuerung:**
- `--dry-run` (mit oder ohne `--apply`): nie ein Scan.
- `--no-navidrome-scan`: unterdrückt den Auto-Scan explizit, auch bei
  echten `SUCCESS`-Outcomes (z. B. für Testläufe gegen eine isolierte
  Test-Library ohne Seiteneffekt auf die echte Navidrome-Instanz).
- Ein fehlschlagender/nicht konfigurierter Scanversuch wird geloggt und
  ausgegeben, ändert aber **nie** den Exit-Code des Repair-Laufs — der
  Repair-Erfolg selbst ist davon unabhängig.

`--allow-delete` (Duplicate-Auflösung, §6d) ist ein eigener, unabhängiger
CLI-Pfad und **nicht** an diese Automatik angeschlossen.

## 9. MusicBot Doctor — Telegram-Integration (Phase 3, P1.3, implementiert)

Macht Health-Scan (`docs/LIBRARY_HEALTH.md`) und den `SAFE_AUTOMATIC`-Level
dieses Dokuments über einen Admin-only Telegram-Menüpunkt
(„🩺 MusicBot Doctor" unter „⚙️ Administration") nutzbar, statt nur per CLI.

```text
handlers/library_doctor_handler.py       Telegram-Handler (Admin-Gating,
                                          Nachrichten-Formatierung)
services/library_repair/doctor_runner.py reine Subprozess-Orchestrierung
                                          (kein Telegram-Import)
```

Ruft `scripts/library_health_check.py` bzw. `scripts/library_repair.py
--level SAFE_AUTOMATIC --apply` ausschließlich als eigenständige
Subprozesse auf (`asyncio.create_subprocess_exec`) — importiert sie nie,
exakt dasselbe Muster wie `services/metadata/reprocessing_runner.py` für
`scripts/reprocess_artist_metadata.py`. Jeder Lauf läuft als
Hintergrund-Task (`asyncio.create_task`), damit ein mehrminütiger Scan
nicht die gesamte Telegram-Application blockiert (die läuft ohne
`concurrent_updates=True`).

**Ablauf:** Scan-Button → Health-Zusammenfassung (Tracks/Albums/Artists/
Health-Score/häufigste Issues) + „🔧 SAFE_AUTOMATIC anwenden"-Button →
Bestätigung → Apply-Lauf → Ergebnis.

Die Zusammenfassung trennt Issues nach Score-Relevanz statt sie als rohe
Issue-Codes aufzulisten: ein „⚠️ Wirkt sich auf den Score aus"-Block
(WARNING/ERROR/CRITICAL) und ein separater „ℹ️ Nur Beobachtung, kein
Mangel"-Block (INFO — beeinflusst den Score laut `LIBRARY_HEALTH.md` §4
nicht). Labels kommen aus der Beschreibung in
`services/library_health/issues.py::REGISTRY` (Single Source of Truth,
dieselbe Quelle wie der Health-Score selbst), gekürzt auf den ersten
Satz/110 Zeichen für die Chat-Anzeige (`_short_issue_label()`), plus
Prozentanteil an der Library bei datei-bezogenen Codes.

**Bewusst nur `SAFE_AUTOMATIC` über diesen Weg erreichbar** — alle
externen/destruktiven Level (`COVER`/`EXTERNAL_METADATA`/
`METADATA_REPROCESSING`/`LOUDNESS`/`DUPLICATE`) bleiben CLI-only, exakt
dieselbe Grenze wie beim Default-`--apply` auf der Kommandozeile (§3).
Profitiert automatisch von der Navidrome-Auto-Scan-Automatik aus §8, da
beide denselben `scripts/library_repair.py`-Subprozess aufrufen.

**Berechtigung:** Admin-Level (`Config.OWNER_USER_ID`/`ADMIN_USER_IDS`),
eigener Check sowohl im Handler als auch im Callback-Dispatcher
(Defense-in-Depth gegen manuell konstruierte `callback_data`, SEC-003-Muster).

**DRY-RUN gegen Produktion (`--artist 01099`):** 6 would-change (Recording-/
Release-ID für die Weihnachtslied-Singles), 10 `SKIPPED` (MB kein sicherer
Match für die Album-Tracks). Kein Raten.

**Report-Persistenz (Phase 3, Doctor-Report-Persistence, implementiert):**
`doctor_runner.py::run_health_scan()` übergibt dem Subprozess denselben
`--json`-Pfad, den auch die CLI selbst standardmäßig verwendet und den
`handlers/mugge_statistik_handler.py::handle_library_overview()` bereits
liest: `Config.DATA_DIR / "library_health_report.json"`. Kein zweiter
Report-Mechanismus — Telegram bekommt weiterhin nur die gekürzte
Zusammenfassung, die vollständige JSON-Datei bleibt danach unter diesem
Pfad für Statistics-Ansicht/forensische Auswertung erhalten (vorher wurde
sie in ein sich selbst löschendes Temp-Verzeichnis geschrieben und ging
nach jedem Lauf verloren). Der gesamte Ablauf (START → SCAN → REPORT →
SAVE → SUMMARY) wird unter dem Log-Präfix `🏥 [DOCTOR]` in `bot.log`
protokolliert — u. a. „Health-Scan gestartet", „Health-Scan abgeschlossen",
„Report gespeichert: <Pfad>", „Score: X | Files: Y | Issues: Z". Bei einem
Fehler (Exit-Code ≠ 0, Timeout, fehlende/kaputte JSON-Datei) wird
ausschließlich der jeweilige Fehler geloggt, nie eine der Erfolgsmeldungen.

---

## 10. Repair MusicBot — Telegram-Integration (implementiert)

**Abgrenzung der drei Verantwortlichkeiten** (bewusst getrennt gehalten,
siehe auch `docs/LIBRARY_HEALTH.md` §1a):

```text
Library Health           = erkennt und bewertet Probleme
                            (Detect → Analyze → Score → Report → Findings)
Library Health Review    = beurteilt Findings
                            (OPEN → RESOLVED / FALSE_POSITIVE, nie Repair)
Repair MusicBot           = führt zulässige Reparaturen aus
                            (Plan → Preview → Confirm → Execute → Verify → Resolve)
```

`services/library_repair/repair_service.py` orchestriert dabei
ausschließlich BEREITS BESTEHENDE Komponenten — keine zweite Repair-
Engine, kein zweiter Safety-/Rollback-Mechanismus:

```text
Findings (services/library_health/findings.py, nur OPEN)
   ↓
plan_repairs() / filter_plan()      (services/library_repair/planner.py,
                                      unverändert)
   ↓
Repair Plan → SAFE_AUTOMATIC-Kandidaten (get_safe_automatic_candidates())
   ↓
Preview (build_preview(), rein lesend)
   ↓
[Telegram: explizite Bestätigung "JA, REPARIEREN"]
   ↓
run_safe_automatic_repair()          (services/library_repair/doctor_runner.py,
                                       identischer Subprozess-Pfad wie
                                       MusicBot Doctor §9 - apply_level1 +
                                       apply_level1_rename, Backup +
                                       Verification + Rollback bereits
                                       darin enthalten)
   ↓
Verification: erneuter run_health_scan()
   ↓
Finding → RESOLVED   NUR für tatsächlich nicht mehr erkannte Findings
                      (niemals automatisch FALSE_POSITIVE)
   ↓
Repair History (library_repair_runs.json + bestehendes Journal)
```

**Sicherheitsgrenze, erweitert seit ARCH-033:** ohne Vorschau-Umweg
direkt ausführbar bleibt nur `SAFE_AUTOMATIC` (verlustfrei, kein
Netzwerk, kein Re-Encode). `METADATA_REPROCESSING` (L2) und
`EXTERNAL_METADATA` (L3) sind seit ARCH-033 zusätzlich über Telegram
erreichbar, aber ausschließlich pro Artist mit eigener Vorschau und
eigener Bestätigung (siehe §12) — nie als globaler Batch wie
SAFE_AUTOMATIC. `COVER`/`LOUDNESS`/`DUPLICATE` werden im Plan/in den
Reparaturvorschlägen weiterhin nur angezeigt (🟡 REVIEW, zur
Transparenz) und bleiben CLI-only. Repair MusicBot ist keine Ausweitung
der ursprünglichen SAFE_AUTOMATIC-only-Grenze auf beliebige Level,
sondern eine gezielt erweiterte, aber weiterhin klar begrenzte
Oberfläche für bereits etablierte Ausführungspfade.

**Stale-Plan-Schutz:** `execute_safe_automatic_repair()` baut IMMER
unmittelbar vor der Ausführung einen komplett frischen Plan (neuer
Health-Scan) — ein an anderer Stelle (z. B. in der Preview) zuvor
erzeugter Plan wird nie wiederverwendet und kann daher strukturell nicht
veraltet sein.

**Concurrency-Schutz:** eine atomare Lock-Datei
(`<DATA_DIR>/library_repair.lock`, `O_CREAT|O_EXCL`) verhindert, dass ein
zweiter Telegram-Tap oder ein parallel von der Kommandozeile gestarteter
`scripts/library_repair.py --apply`-Lauf gleichzeitig dieselbe Library
verändert — zuvor gab es dafür keinen Schutz.

**Repair History:** das bestehende Journal
(`<DATA_DIR>/library_repair_journal.jsonl`, siehe §5) bleibt die einzige
Quelle für Datei-Fakten. Da es keine Lauf-Gruppierung kennt (welche
Einträge zu einem Telegram-Tap gehören), ergänzt ein kleiner
Zusatzindex (`<DATA_DIR>/library_repair_runs.json`) genau diese fehlende
Gruppierung per Byte-Offset-Fenster in das Journal — ohne dessen Inhalt
zu duplizieren. Repair-Statistiken werden ausschließlich aus diesem
Index berechnet (keine hartkodierten Werte).

**Navigation:** `Hauptmenü → Administration → Bibliothek & Navidrome →
🛠️ Repair MusicBot` — Startseite (Reparaturen analysieren, Offene
Reparaturen, Reparaturvorschläge, Reparaturhistorie, Repair-Statistik),
danach Reparaturvorschläge → Preview → explizite Bestätigung → Ausführung
→ Ergebnis. Öffnen des Menüs oder der Reparaturvorschläge startet
niemals automatisch eine Reparatur. Berechtigung (Admin) wird am
tatsächlichen Ausführungs-Handler erneut geprüft, nicht nur beim
Navigieren.

**Tests:**

| Datei | Deckt ab |
|---|---|
| `tests/test_repair_service.py` | Plan-Filterung auf OPEN-Findings, SAFE_AUTOMATIC-Auswahl, read-only Preview, Concurrency-Lock, Execute (SUCCESS/FAILED/SKIPPED), Verification-gate für RESOLVED, niemals FALSE_POSITIVE, stale-Plan-Schutz, Journal-Fenster-Lesen, History/Statistik, Unicode |
| `tests/test_repair_musicbot_handler.py` | Telegram-Repair-Handler (Start/Analyze/Proposals/Preview/Confirm/Execute/History/Statistik), Berechtigungs-Re-Check bei Execute, kein Auto-Start |
| `tests/test_rich_menu_repair.py` | Menüpunkt-Registrierung + Admin-Gating/Dispatch-Ebene für `repair:*` |
| `tests/test_repair_integration.py` | Vollständiger End-to-End-Fluss (Scan → Finding → Plan → Preview → Executor → Verification → Resolve → Re-Scan) mit dem echten `apply_level1()`-Executor gegen eine isolierte Test-Library |
| `tests/test_review_repair_readonly_safety.py` | Repair-Preview gegen eine isolierte Test-Library, SHA-256-Vergleich vorher==nachher |

---

## 11. Library-Maintenance-Actions (ARCH-032, implementiert)

**Zweite, eigenständige Flow-Kategorie neben dem Finding-getriebenen
Repair-Flow (§10) — bewusst NICHT Health-Finding-getrieben (ADR-0001):**

```text
Finding Repair (§10)                Library-Maintenance-Actions (§11)
    Health-Scan                         Artist wählen
       ↓                                    ↓
    Findings                            Aktion wählen
       ↓                                    ↓
    Plan → Preview → Confirm            Preview (dry_run=True, derselbe
       ↓                                Executor-Pfad wie Execute)
    Executor → Verification                 ↓
       ↓                                Confirm
    Finding RESOLVED                        ↓
                                         Executor → Ergebnis
                                         (KEIN Finding, KEIN Re-Scan)
```

Drei Aktionen, jede löst eines der drei ehemals eigenständigen
Wartungsskripte ab (Commit `6037abf`, entfernt in ARCH-032):

| Aktion | ersetzt | Was passiert |
|---|---|---|
| `artist-casing` | `scripts/fix_artist_casing.py` | ©ART/ARTISTS-Casing gegen `mapping/artist_overrides.json`/`case_preserve.yaml` normalisieren (reine Casing-Mappings, keine Namens-Erweiterung) |
| `legacy-genre-cleanup` | `scripts/remove_legacy_genre_atom.py` | Legacy-Freeform-Atom `----:com.apple.iTunes:GENRE` entfernen, NUR wenn `©gen` bereits vorhanden ist |
| `set-genre` | `scripts/set_genre.py` | `©gen` setzen (manuell oder aus `mapping/artist_genre.yaml`), entfernt Legacy-Atom als Nebeneffekt |

**Warum kein Health-Finding:** alle drei Aktionen sind gezielte
Nutzeraktionen, keine Reparatur eines vom Health-Scanner erkannten
Defekts — `services/library_health/` (P0, read-only) bleibt vollständig
unangetastet, kein neuer Issue-Code (ARCH-031 B.1, siehe
`docs/adr/0001-library-maintenance-actions-not-finding-driven.md`).

### 11.1 Architektur

```text
services/library_repair/
    artist.py               Domain (rein): load_casing_map(), normalize_values()
    genre.py                Domain (rein): genre_from_mapping(),
                             normalize_genre_input(), decide_legacy_genre_removal()
    executor.py              + apply_artist_casing() / apply_legacy_genre_cleanup() /
                             apply_set_genre() / tags_fingerprint() — nutzt
                             dieselbe Safety-/Backup-/Verify-Infrastruktur
                             wie apply_level1() (safety_check, _sha256,
                             _audio_essence_md5, _read_atoms/_write_atoms/
                             _delete_atoms)
    run_tracking.py         Lock/Journal-Fenster/Run-Index/History/
                             Statistik — GETEILT mit dem Finding-Flow
                             (ADR-0004), EIN Journal/Lock für beide Flows
    maintenance_service.py  Orchestrierung: preview_*()/execute_*()
    library_artists.py      list_library_artist_dirs()/resolve_artist_by_index()
                             — index-basierte Artist-Auswahl (ARCH-031 B.8)

handlers/
    library_maintenance_handler.py  Telegram ("🧹 Library-Wartung"),
                                     Callback-Präfix libmaint: (bewusst
                                     NICHT maint: — bereits durch den
                                     Bot-Wartungsmodus belegt)

scripts/
    library_repair.py       + --maintenance-action {artist-casing,
                             legacy-genre-cleanup,set-genre} — zentraler
                             CLI-Einstiegspunkt statt drei separater Scripts
```

**Verifikation:** `tags_fingerprint()` (SHA-256 über alle Nicht-Ziel-Atome)
beweist zusätzlich zu Ziel-Atom-Werten und Audio-Essenz-MD5, dass NUR die
beabsichtigten Atome verändert wurden — strenger als das bisherige
L1-Muster. Bewusst NICHT rückwirkend auf `apply_level1()` angewendet
(Regressionsrisiko, ARCH-031 Follow-up).

### 11.2 CLI

```bash
python scripts/library_repair.py --maintenance-action artist-casing --artist X [--apply]
python scripts/library_repair.py --maintenance-action legacy-genre-cleanup --artist X [--apply]
python scripts/library_repair.py --maintenance-action set-genre --artist X --genre "A; B" [--apply]
python scripts/library_repair.py --maintenance-action set-genre --artist X --from-mapping [--apply]
python scripts/library_repair.py --maintenance-action set-genre --artist X --from-mapping \
    --only-if-missing --apply
python scripts/library_repair.py --maintenance-action artist-casing --all [--apply]   # ganze Library
python scripts/library_repair.py --maintenance-action artist-casing --path <Datei/Verzeichnis>
```

Dry-Run ist Standard (identisch zum Rest dieses Scripts), `--apply`
erforderlich für echtes Schreiben. `--update-manual-mapping` (nur mit
`set-genre --artist --genre`) trägt den Wert zusätzlich in
`mapping/artist_genre.yaml` ein — bleibt CLI-only, kein Telegram-Trigger
(ARCH-031 A.4). `--path`/`--all`/`--update-manual-mapping`/
`--only-if-missing` sind CLI-only, `--artist` funktioniert CLI + Telegram.

**Breaking Change:** die drei alten Scripts existieren nicht mehr:

```text
scripts/fix_artist_casing.py --artist X
    → scripts/library_repair.py --maintenance-action artist-casing --artist X

scripts/remove_legacy_genre_atom.py --artist X
    → scripts/library_repair.py --maintenance-action legacy-genre-cleanup --artist X

scripts/set_genre.py --artist X --genre "Y"
    → scripts/library_repair.py --maintenance-action set-genre --artist X --genre "Y"
```

Repository-weites Removal-Audit (ARCH-032) fand keine funktionalen
Aufrufer (kein CI/Cron/Shell-Skript) — kein dokumentierter
Produktionslauf der drei Scripts existierte (ARCH-031 E).

### 11.3 Telegram

`Hauptmenü → Administration → Bibliothek & Navidrome → 🧹 Library-Wartung`:

```text
Artist wählen (index-basierter Picker, wie beim Reprocessing-Menü)
   ↓
Aktion wählen (🎤 Artist Casing / 🧹 Legacy Genre / 🎼 Genre setzen)
   ↓
Preview (read-only, ruft denselben Executor-Pfad mit dry_run=True auf)
   ↓
explizite Bestätigung ("✅ JA, AUSFÜHREN")
   ↓
Execute (Lock-Status vorab geprüft, Doppelklick-Schutz) → Ergebnis
```

`set-genre` erreicht man aus der Aktions-Auswahl über den Zwischenschritt
„🎭 Genre-Verwaltung" (`libmaint:genremenu:<idx>`) — dort inzwischen
sowohl mit Mapping- als auch mit manueller Freitext-Eingabe nutzbar
(siehe §14, Library Genre Management v2, löst die hier ursprünglich
dokumentierte `--from-mapping`-only-Einschränkung ab). Öffnen des
Menüs/der Artist-Liste/der Aktions-Auswahl startet niemals automatisch
eine Aktion. Berechtigung (Admin) wird am tatsächlichen
Ausführungs-Handler erneut geprüft (Defense-in-Depth, identisches
Muster wie `repair:`/`doctor:`/`review:`).

**Gemeinsame Infrastruktur mit dem Finding-Flow (ADR-0004):** ein
gemeinsamer Lock (`library_repair.lock`), ein gemeinsames Journal
(`library_repair_journal.jsonl`), ein gemeinsamer Run-Index
(`library_repair_runs.json`, Run-Records tragen `"kind":
"repair"|"maintenance"`) — ein Maintenance-Lauf und ein Finding-Repair-
Lauf können sich nicht überlappen.

**Tests:**

| Datei | Deckt ab |
|---|---|
| `tests/test_library_repair_artist.py` / `_genre.py` | Domain-Funktionen (rein), Cross-Consistency-Test genre.py vs. GenreMapper |
| `tests/test_library_repair_executor.py` (Maintenance-Klassen) | Safety/Backup/Rollback/Audio-Essenz/Target-Non-Target für alle drei `apply_*()`, `tags_fingerprint()` |
| `tests/test_library_repair_run_tracking.py` | Extraktions-Regressionstest (Lock/Journal-Fenster/Run-Index/Statistik/`kind`-Feld) |
| `tests/test_library_repair_maintenance_service.py` | Preview read-only, Execute, Partial Success, Lock-Sharing mit Repair-Flow |
| `tests/test_library_repair_library_artists.py` | Artist-Listing, Index-Auflösung, Anti-Injection |
| `tests/test_library_repair_cli_maintenance.py` | CLI `--maintenance-action` End-to-End gegen isolierte Test-Library |
| `tests/test_library_maintenance_handler.py` | Telegram-Handler (Start/Artist-Liste/Aktions-Auswahl/Preview/Confirm/Execute), kein Auto-Start, Doppelklick-Schutz |
| `tests/test_rich_menu_library_maintenance.py` | Menüpunkt-Registrierung + Admin-Gating/Dispatch-Ebene für `libmaint:*` |

### 11.4 Offene Follow-ups (ARCH-031, bewusst nicht Teil von ARCH-032)

Drei der vier ursprünglich hier gelisteten Punkte sind mit Library Genre
Management v2 (§14, Chat-Charakterisierung 2026-09-15) geschlossen:

- ~~`GENRE_EMPTY`/`META_GENRE_MISSING` künftig über den leichteren
  `set-genre --from-mapping`-Pfad statt voller `METADATA_REPROCESSING`?~~
  **CLOSED (§14):** Planner-Routing selbst bleibt bewusst unverändert
  (weiterhin `METADATA_REPROCESSING`) — zusätzlich dazu findet der neue
  Telegram-Einstieg „🧹 Fehlende Genres" (`libmaint:missing`) betroffene
  Artists read-only über den bestehenden Health-Scan/Planner und führt
  in den leichteren `set-genre`-Flow (§14.1), ohne den Finding-Status
  selbst zu berühren.
- `tags_fingerprint()` rückwirkend auch für `apply_level1()`? **weiterhin
  DEFERRED** — Regressionsrisiko gegen 55 bestehende Executor-Tests,
  bewusst nicht Teil von Library Genre Management v2.
- ~~`--update-manual-mapping` als künftige, review-pflichtige
  Telegram-Admin-Funktion?~~ **CLOSED (§14):** Kernlogik nach
  `services/library_repair/genre.py::save_manual_genre_mapping()`
  extrahiert (CLI-Wrapper bleibt verhaltensgleich), im Telegram-`gs:*`-
  Flow als „Mapping speichern?"-Schritt nach expliziter Preview/
  Bestätigung nutzbar — kein direkter Dateisystemzugriff aus dem
  Handler (CLAUDE.md §4).
- ~~`--only-if-missing` als Telegram-Option?~~ **CLOSED (§14):** als
  Modus-Wahl im `gs:*`-Flow (`libmaint:gs:mode:onlymissing`), im
  „Fehlende Genres"-Flow als empfohlener Default markiert.

---

## 12. Telegram Level-2/Level-3-Reparatur (Pro-Artist, ARCH-033, implementiert)

**Erweitert §10 (Repair MusicBot) um zwei weitere, tatsächlich
ausführbare Level** — bewusst NICHT als globale Batch-Aktion wie
SAFE_AUTOMATIC, sondern ausschließlich pro Artist mit eigener Vorschau
und eigener Bestätigung (`docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md`):

```text
Findings (wie §10, nur OPEN)
   ↓
plan_repairs() / group_candidates_by_artist()   (services/library_repair/planner.py)
   ↓
Artist-Liste (L2-/L3-Kandidatenzahl je Artist, index-basiert, paginiert,
              pro Telegram-Session gecacht — kein Health-Scan bei jedem
              Button-Tap)
   ↓
Artist wählen → Aktion wählen (L2 und/oder L3, je nach Kandidatenzahl)
   ↓
Preview (read-only, filter_plan(artist=, level=) + build_preview(),
         level-spezifischer Warnhinweis)
   ↓
[Telegram: explizite Bestätigung "✅ Jetzt ausführen"]
   ↓
execute_level2_repair()/execute_level3_repair()   (services/library_repair/
                                                    repair_service.py)
   ↓
run_level2_repair()/run_level3_repair()            (services/library_repair/
                                                     doctor_runner.py, Subprozess:
                                                     scripts/library_repair.py
                                                     --artist X --level <L> --apply)
   ↓
Verification: erneuter run_health_scan() (nur wenn mind. 1 Erfolg)
   ↓
Finding → RESOLVED   NUR für tatsächlich nicht mehr erkannte Findings
   ↓
Repair History (dasselbe library_repair_runs.json wie §10/§11, "kind": "repair")
```

**L2 (`METADATA_REPROCESSING`) vs. L3 (`EXTERNAL_METADATA`):** beide
laufen als eigener Subprozess (siehe unten), unterscheiden sich nur in
`--level` und im Warnhinweis vor der Bestätigung — L2 durchläuft die
volle Metadaten-Pipeline erneut (auch Genre/Lyrics/Cover-Logik,
möglicherweise geänderte Auto-Learn-Mappings), L3 ruft zusätzlich
MusicBrainz auf und macht Netzwerk-/Rate-Limit-Fehler je Datei als
FEHLGESCHLAGEN sichtbar statt sie still zu überspringen.

**Bewusste Abweichung von der ursprünglichen Implementierungsvorgabe
(Subprozess statt in-process, nutzerbestätigt):** der ursprüngliche
Auftrag sah vor, `apply_level2()`/`apply_external_metadata()` in-process
über `asyncio.to_thread()` aufzurufen. `EnhancedMetadataProcessor`
(`SingletonMixin`) wird jedoch bereits beim Bot-Start
(`handlers/menu/rich_menu_handler.py`) für die Live-Download-Pipeline
konstruiert — ein `asyncio.to_thread()`-Aufruf hätte denselben Singleton
gleichzeitig aus einem separaten OS-Thread heraus verwendet, während der
Event-Loop des Bots (potenziell während eines laufenden Downloads durch
dieselbe Instanz) weiterläuft. Genau diese Klasse von Risiko begründet
bereits den bestehenden Subprozess-Pfad von `reprocessing_runner.py`.
Nach Rücksprache mit dem Nutzer laufen `execute_level2_repair()`/
`execute_level3_repair()` deshalb identisch zu
`execute_safe_automatic_repair()` als Subprozess
(`doctor_runner.run_level2_repair()`/`run_level3_repair()`) —
`apply_level2()`/`apply_external_metadata()` selbst bleiben dabei
unverändert.

**Bewusst NIE global:** anders als bei SAFE_AUTOMATIC gibt es für L2/L3
keinen "alle Artists auf einmal"-Button — jede Ausführung ist an genau
einen zuvor über den Index-Picker gewählten Artist gebunden (ADR-0003).

**Navigation:** `🛠️ Repair MusicBot → Reparaturvorschläge` zeigt einen
zusätzlichen Button „🛠️ L2/L3-Reparaturen (nach Artist)“, sobald der
aktuelle Plan L2- oder L3-Kandidaten enthält (zusätzlich zum
bestehenden SAFE-Preview-Button, nicht anstelle). Callback-Präfix
`l23rep:` — lebt auf demselben `RepairMusicBotHandler` wie `repair:*`
(kein eigener Handler, da L2/L3 wie SAFE_AUTOMATIC Findings-getrieben
sind, ADR-0001). Öffnen des Menüs, der Artist-Liste oder der
Aktions-Auswahl startet niemals automatisch eine Reparatur. Berechtigung
(Admin) wird am tatsächlichen Ausführungs-Handler erneut geprüft.

**COVER/LOUDNESS/DUPLICATE bleiben CLI-only** — ARCH-033 deckt
ausdrücklich nur L2/L3 ab (Scope-Option A). Ein Erweiterungspunkt für
künftige, eigene ARCH-Phasen (ARCH-034/035) ist in
`handlers/repair_musicbot_handler.py` neben den `_L23REP_*`-Dicts
dokumentiert (Phase 4, reine Vorbereitung, kein aktiver Code).

**Tests:**

| Datei | Deckt ab |
|---|---|
| `tests/test_library_repair_planner.py` | `group_candidates_by_artist()` — L2/L3 getrennt gezählt, andere Level ignoriert, Sortierung (Gesamtzahl absteigend, dann alphabetisch), Determinismus, Pfad-Präfix-Fallback |
| `tests/test_doctor_runner.py` | `run_level2_repair()`/`run_level3_repair()` — Subprozess-Aufruf, Timeout, Fehlerfälle |
| `tests/test_repair_service_level23.py` | `execute_level2_repair()`/`execute_level3_repair()` — Stale-Plan-Schutz, Verification-Gate, Lock-Sharing mit §10/§11, Run-Record `kind: "repair"` |
| `tests/test_repair_handler_level23.py` | Telegram-Sub-Flow (Start/Artist-Liste inkl. Pagination-Cache/Aktions-Auswahl/Preview/Confirm/Execute), Admin-Re-Check je Schritt, Index-basierte Artist-Auswahl (kein Rohname in `callback_data`), kein Auto-Start, Lock-Konflikt-Anzeige, Teilerfolg-Anzeige |

---

## 13. Duplikat-Check — höher-bitratige Duplikate (Chat-Charakterisierung 2026-09-15)

**Herkunft der Idee:** Nutzer-Vorschlag „wenn `DuplicateDetector` ein
höher-bitratiges Duplikat findet, automatisch das schlechtere ersetzen
statt nur zu melden". Im Chat bewusst auf **Erkennung + Vorschlag, KEINE
automatische Ausführung** reduziert — „automatisch ersetzen" hätte als
einzige vollautomatische, destruktive Library-Mutation im gesamten
Projekt die überall sonst etablierte Sicherheitsphilosophie durchbrochen
(jede andere Mutation: Plan → Preview → explizite Bestätigung → Execute,
nie automatisch). Zusätzlicher Befund während der Charakterisierung:
`DuplicateDetector` (`services/duplicate/detector.py`, Live-Download-
Dublettenprüfung) hat **kein** Bitrate-/Qualitäts-Feld — die bereits
bestehende, tatsächlich bitrate-vergleichende Engine ist eine völlig
andere, bereits vorhandene Komponente:
`scripts/resolve_duplicates.py`/`services/duplicate/{classification,
resolution,execution}.py`
(`docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md`) — inkl. eigenem
Safety-Gate (Dauer-/MusicBrainz-/ISRC-Konsistenz, Album-Context-Risiko).
Diese Phase baut **keine neue Erkennung**, sondern macht die bereits
gehärtete Engine über Telegram sichtbar.

### 13.1 Umfang

Nur **read-only Dry-Run-Scan pro Artist** über Telegram
(`services/library_repair/duplicate_runner.py::run_duplicate_scan()` →
Subprozess `scripts/resolve_duplicates.py --path <Config.LIBRARY_DIR>/<Artist>`,
kein `--execute`). Zeigt pro gefundener Duplikat-Gruppe: welche Version
behalten werden sollte (`keep`) und welche als Lösch-Vorschlag markiert
ist (`remove_proposal`), inkl. Bitrate-Vergleich — oder bei
`MANUAL_REVIEW`/`KEEP_BOTH` den Grund. **Kein Execute/Delete über
Telegram** — das tatsächliche Löschen bleibt CLI-only:

```bash
scripts/library_repair.py --allow-delete --artist <Name> --apply
```

(dockt bereits an dasselbe `resolve_duplicates.py` an, siehe §6d.)

### 13.2 Architektur-Falle, während der Charakterisierung entdeckt

`scripts/resolve_duplicates.py` kennt zwei komplett verschiedene
Scan-Roots:

```text
--artist <Name>   löst IMMER gegen ALLOWED_ROOT auf
                  (/tmp/musicbot_test/library, reine Testbibliothek) -
                  NIEMALS gegen die Produktionslibrary, unabhängig von
                  --execute.
--path <Pfad>     ist der einzige Weg, die echte Produktionslibrary
                  (Config.LIBRARY_DIR, dort als "Read-Only-Produktions-
                  Root" registriert) zu adressieren.
```

`duplicate_runner.py::run_duplicate_scan()` ruft deshalb **immer**
`--path <Config.LIBRARY_DIR>/<Artist>`, nie `--artist` — ein leicht zu
übersehender Stolperstein für jeden künftigen Aufrufer dieses Skripts.

**Zusätzlich entdeckter Dokumentations-Widerspruch (noch offen, nicht
Teil dieser Phase):** der Datei-Kopf-Kommentar von
`scripts/resolve_duplicates.py` (`ALLOWED_READONLY_ROOTS`-Definition)
behauptet „es gibt keinen Codepfad, der Mutation gegen einen
ALLOWED_READONLY_ROOTS-Eintrag zulässt" — `validate_scan_root()` selbst
erlaubt das aber sehr wohl, sofern `--execute --confirm-production-execute`
UND ein konkretes Unterverzeichnis (z. B. `--path .../EinArtist`)
angegeben werden (vermutlich ein bei „Freigabe Schritt 3" nachgezogenes
Feature, dessen Kopf-Kommentar seither nicht aktualisiert wurde). Reine
Doku-Korrektur, siehe `docs/FINDINGS_INDEX.md`.

### 13.3 Telegram

`Hauptmenü → Administration → Bibliothek & Navidrome → 🔁 Duplikat-Check`:

```text
Artist wählen (index-basierter Picker, wie bei Library-Wartung)
   ↓
Scan läuft (Hintergrund-Task, Subprozess, geteilter Repair-Lock — ADR-0004)
   ↓
Ergebnis: pro Gruppe Keep/Remove-Vorschlag + Bitrate, oder Manual-Review-Grund
   ↓
Hinweis auf den CLI-Befehl für das tatsächliche Löschen
```

Öffnen des Menüs oder der Artist-Liste löst niemals einen Scan aus - nur
die explizite Artist-Auswahl. Berechtigung (Admin) wird am tatsächlichen
Scan-Auslöser (`handle_pick_artist()`) erneut geprüft (Defense-in-Depth,
identisches Muster wie `doctor:`/`repair:`/`libmaint:`).

**Geteilter Lock (ADR-0004-Prinzip):** `run_duplicate_scan()` nutzt
denselben globalen Repair-Lock wie Finding-Repair/Library-Wartung/L2/L3 -
nicht weil der Dry-Run selbst die Library verändert (tut er nicht),
sondern weil `REPORT_JSON_PATH` eine einzige, feste Datei ist (kein
`Config.DATA_DIR`-Bezug) und zwei gleichzeitige Scans sich sonst
gegenseitig die Report-Datei überschreiben könnten.

### 13.4 Tests

| Datei | Deckt ab |
|---|---|
| `tests/test_duplicate_runner.py` | `run_duplicate_scan()` — `--path` statt `--artist`, nie `--execute`, Report-Parsing, Exit-Code-3-Safety-Violation, Lock-Sharing/-Release, Timeout/Start-Fehler (17 Tests) |
| `tests/test_duplicate_check_handler.py` | Telegram-Handler (Start/Artist-Liste/Pick/Ergebnis-Formatierung), Admin-Re-Check je Schritt, Index-basierte Artist-Auswahl, kein Auto-Start, Lock-Konflikt-Anzeige, Safety-Violation-Anzeige, nie ein Delete-Button (20 Tests) |
| `tests/test_menu_actions_library.py` | Dispatcher-Routing `dupcheck:*` (Admin-Gate, Start/Artists/Pick, unbekannter Callback) |

---

## 14. Library Genre Management v2 (Chat-Charakterisierung 2026-09-15)

**Herkunft:** Nutzerauftrag „🎭 Genre-Verwaltung" — erweitert das
bestehende `set-genre` (§11) um manuelle Telegram-Freitext-Eingabe,
`--only-if-missing` als Telegram-Option, einen leichteren Einstieg für
offene `GENRE_EMPTY`/`META_GENRE_MISSING`-Befunde und eine neue,
eigenständige Funktion: **kontrollierte Genre-Revalidierung**
(Last.fm erneut befragen, bestehende Auto-Learn-Overturn-Regel
unverändert wiederverwendet, NIEMALS der automatische Download-Pfad).
Schließt drei der vier in §11.4 offen gelisteten ARCH-031-Follow-ups;
`tags_fingerprint()` rückwirkend auf `apply_level1()` (der vierte Punkt)
bleibt bewusst außerhalb des Scopes.

### 14.1 ✏️ Genre setzen — erweiterter `gs:*`-Flow

Ersetzt den in §11.3 ursprünglich dokumentierten `--from-mapping`-only-
Telegram-Zugang durch einen mehrstufigen, aber weiterhin komplett
Preview→Bestätigung→Execute-basierten Flow (`handlers/
library_maintenance_handler.py`, Callback-Unterpräfix `libmaint:gs:`):

```text
🎭 Genre-Verwaltung (libmaint:genremenu:<idx>)
   ↓
Quelle: 📚 Aus Mapping | ✏️ Manuell eingeben (libmaint:gs:mapping / gs:manual)
   ↓ (bei manuell: Freitext-Eingabe über das bestehende
   ↓  context.user_data["libmaint_awaiting_genre_text"]-Muster,
   ↓  identisch zu Family-Chat/-Challenge — KEIN neuer
   ↓  ConversationHandler, siehe handle_text_message())
Modus: Überschreiben erlaubt | Nur wenn Genre fehlt (libmaint:gs:mode:*)
   ↓ (nur bei manuell)
Mapping speichern? Ja/Nein (libmaint:gs:save:*)
   ↓
Preview (read-only, preview_set_genre()) → explizite Bestätigung
   ↓
Execute (execute_set_genre(), Lock-Status vorab geprüft) → Ergebnis
   ↓ (nur wenn "Mapping speichern" gewählt UND success_count > 0)
save_manual_genre_mapping() → mapping/artist_genre.yaml
```

**Manuelle Eingabe-Validierung**
(`_validate_manual_genre_input()`): leer/nur Whitespace, Zeilenumbrüche,
> 200 Zeichen werden mit einer Fehlermeldung abgelehnt, die Sitzung
bleibt dabei im `awaiting`-Zustand (erneuter Versuch möglich, `/cancel`
bricht ab). Die normalisierte Eingabe läuft durch die bestehende zentrale
Normalisierung (`services/library_repair/genre.py::
normalize_genre_input()`, Trenner `;`/`,`/`/` → `"; "`) — **keine neue,
parallele Normalisierung**.

**Mapping speichern** (löst das ARCH-031-Follow-up „`--update-manual-
mapping` als Telegram-Funktion" — §11.4): die bisher CLI-only
`_update_manual_genre_mapping()`-Logik aus `scripts/library_repair.py`
wurde nach `services/library_repair/genre.py::
save_manual_genre_mapping()` extrahiert (atomarer Schreibvorgang,
Tmp+Replace, case-insensitiver Key, bestehendes `description`-Feld
bleibt erhalten) — der CLI-Wrapper ruft dieselbe Funktion auf
(verhaltensgleich, durch die bestehende CLI-Testsuite abgesichert). Der
Handler selbst greift **niemals** direkt auf das Dateisystem zu
(CLAUDE.md §4) — er ruft ausschließlich diese eine Service-Funktion.
Gilt nur bei manueller Quelle (bei „Aus Mapping" wäre das Mapping mit
sich selbst identisch).

### 14.2 🧹 Fehlende Genres (löst ARCH-031-Follow-up F1, §11.4)

`libmaint:missing` führt **keinen eigenen Scan** aus, sondern
liest den bestehenden, read-only Health-Scan/Planner erneut
(`services/library_repair/repair_service.py::build_repair_plan()` +
`planner.py::filter_plan(issue_code=...)`, zweimal aufgerufen für
`GENRE_EMPTY` und `META_GENRE_MISSING`, Artists dedupliziert und
alphabetisch sortiert) und zeigt eine index-basierte Artist-Liste. Die
Auswahl eines Artists führt direkt in §14.1s `gs:*`-Flow, mit
„🆕 Nur wenn Genre fehlt" dort als **empfohlener** (nicht erzwungener)
Default markiert. Der Planner selbst — inkl. der Entscheidung, dass
diese beiden Issue-Codes weiterhin nach `RepairLevel.METADATA_
REPROCESSING` routen — bleibt bewusst unverändert; dieser Flow ist ein
**zusätzlicher**, leichterer Einstiegspunkt, kein Ersatz.

### 14.3 🔄 Genre revalidieren

**Neue Funktion**, kein Ersatz für Auto-Learning: prüft für einen
einzelnen Artist erneut gegen Last.fm, ob das aktuell gelockte Genre
noch Bestand haben sollte, und wendet — nur nach expliziter Telegram-
Bestätigung — exakt dieselbe, bereits bestehende Auto-Learn-Overturn-
Regel an wie der normale Lern-Loop.

```text
services/library_repair/genre_revalidation.py
    run_genre_revalidation(artist, apply=False|True)
    — baut EIGENE, frische GenreMapper/ArtistNormalizer/GenreProcessor/
      AutoLearnManager-Instanzen (NICHT die Bot-Singletons, siehe unten),
      fragt genre_processor._fetch_genre_from_lastfm() ab, vergleicht
      gegen auto_learn.preview_genre_learning() — UNVERÄNDERTE
      Entscheidungsfunktion, keine eigene Overturn-Logik.
    — Manuelle Mappings (artist_genre.yaml) sind ABSOLUT geschützt:
      wird zuerst geprüft, blockiert bei Treffer jede weitere Aktion
      (OUTCOME_BLOCKED_MANUAL) — Revalidierung überschreibt niemals
      artist_genre.yaml.
    — Nur bei apply=True UND outcome == OVERTURN_ALLOWED wird tatsächlich
      geschrieben (auto_learn.learn_genre(), identischer Pfad wie der
      normale Lern-Loop) — jeder andere Outcome (SAME_GENRE,
      OVERTURN_REJECTED, NO_CANDIDATE, BLOCKED_MANUAL) ist ein
      vollständiger No-Op, auch kein stiller Zähler-Increment.

scripts/revalidate_genre.py
    CLI-Wrapper (echtes config.Config, wie --update-manual-mapping) —
    --artist (required), --dry-run (Default), --apply,
    --json <Pfad> (Ergebnis als JSON, atomar geschrieben).
    --fix/--repair/--force/--execute werden explizit mit Exit-Code 2
    abgelehnt (Verwechslungsschutz mit anderen Scripts dieses Projekts).

services/library_repair/genre_revalidation_runner.py
    run_genre_revalidation_subprocess(artist, apply=False|True)
    — läuft die CLI IMMER als Subprozess (asyncio, Timeout), NIE
      in-process. Grund: GenreMapper/ArtistNormalizer sind SingletonMixin
      — ein in-process-Aufruf würde dieselben, beim Bot-Start für die
      Live-Download-Pipeline konstruierten Instanzen treffen (identisches
      Risiko/identische Lösung wie ARCH-033 L2/L3, siehe
      repair_musicbot_handler.py-Docstring). Der normale Download-Pfad
      (GenreProcessor.determine_genre_with_fallbacks()) bleibt davon
      vollständig unberührt — kein automatischer Trigger irgendwo.
    — wrappt den GESAMTEN Subprozess-Aufruf im geteilten Repair-Lock
      (ADR-0004-Prinzip, identisch zu duplicate_runner.py) — Grund:
      REPORT_JSON_PATH ist eine feste Datei unter Config.DATA_DIR, zwei
      gleichzeitige Taps würden sich sonst überschreiben.
```

Telegram (`libmaint:gr:*`, identisches Preview→Bestätigung→Execute-Muster
wie §14.1):

```text
🔄 Genre revalidieren (libmaint:gr:preview)
   ↓
Subprozess-Vorschau: aktuelles Genre, ermitteltes Kandidaten-Genre,
Quelle, Learning-Status, Entscheidung (dry_run — keine Mutation)
   ↓ (NUR bei outcome == OVERTURN_ALLOWED — bei SAME_GENRE/
   ↓  OVERTURN_REJECTED/NO_CANDIDATE/BLOCKED_MANUAL gibt es KEINEN
   ↓  "Änderung anwenden"-Button)
explizite Bestätigung ("✅ Änderung anwenden", libmaint:gr:confirm)
   ↓
Execute (libmaint:gr:execute, Lock-Status vorab geprüft) → Ergebnis
```

**Bekannter, vorbestehender Fund während der Implementierung entdeckt
(nicht durch diese Phase verursacht, siehe `docs/FINDINGS_INDEX.md`):**
`GenreMapper.reload()` lädt über einen hartkodierten String
(`self._find_mapping_dir("mapping")`) statt über das tatsächlich
konfigurierte `mapping_dir` der Instanz — `_build_dependencies()` in
`genre_revalidation.py` ruft `.reload()` deshalb bewusst NICHT auf
(jeder Subprozess erhält ohnehin frische Singleton-Instanzen über den
normalen `_do_init()`-Pfad, der das korrekt konfigurierte `mapping_dir`
respektiert).

### 14.4 Tests

| Datei | Deckt ab |
|---|---|
| `tests/test_library_repair_genre.py` | `save_manual_genre_mapping()` — fehlende Datei, Dry-Run, Neuanlage, case-insensitiver Key, unverändert/kein Schreiben, `description`-Erhalt, Update, Isolation zwischen Artists (8 neue Tests, 30 gesamt in der Datei) |
| `tests/test_genre_revalidation.py` | `run_genre_revalidation()` — Manueller-Mapping-Schutz, No-Candidate, Same-Genre, Overturn-Rejected, Overturn-Allowed, aktuelles Genre in der Anzeige, Run-Tracking (14 Tests) |
| `tests/test_genre_revalidation_runner.py` | `run_genre_revalidation_subprocess()` — Kommando-Aufbau (`--artist`/`--json`/`--apply`), Erfolg/Fehler-Parsing, Lock-Acquire/-Release (9 Tests) |
| `tests/test_library_maintenance_genre_management.py` | Telegram-Handler-Ebene: `genremenu`/`missing`/`missingpick`, kompletter `gs:*`-Zustandsautomat inkl. Freitext-Validierung, `gr:*` für alle fünf Outcomes, kein Auto-Start an jedem Zwischenschritt, Lock-Konflikt-Anzeige (58 Tests) |
| `tests/test_rich_menu_library_maintenance.py` (`TestGenreManagementDispatchRouting`) | Dispatcher-Routing für alle neuen `libmaint:genremenu/missing/missingpick/gs:*/gr:*`-Callback-Muster (Admin-Gate, korrekte Handler-Methode, korrekt durchgereichte Argumente, unbekannte Sub-Callbacks, Regressionstest für den behobenen `set-genre`-KeyError) |

**Bewusst nicht umgesetzt (Auftrag §24.E, „nur wenn trivial"):** Genre-
Analyse/Explainability (z. B. „warum wurde dieses Genre gewählt") wurde
geprüft und als **nicht trivial** eingestuft — würde eine neue
Präsentationsschicht über die interne Entscheidungslogik von
`GenreProcessor`/`AutoLearnManager` benötigen (mehrstufige Fallback-Kette,
siehe `docs/GENRE_SYSTEM.md`), die aktuell nirgends strukturiert
exponiert ist. Bewusst als offener, unpriorisierter Punkt dokumentiert
statt erzwungen umgesetzt.

---

## 15. Manual Metadata Editing v1 (Chat-Charakterisierung 2026-09-20)

**Herkunft:** Nutzerauftrag „Manual Metadata Editing v1" — erweitert die
Library-Wartung-Aktions-Auswahl um „📝 Metadaten bearbeiten" mit zwei
neuen, expliziten Bearbeitungsfunktionen (🎤 Artist bearbeiten, 🎵 Titel
bearbeiten) und macht die bestehende Genre-Verwaltung (§14) zusätzlich
darunter erreichbar (Verweis, keine Duplizierung).

**Bewusst KEINE neue Schreib-Pipeline** (Auftrag §1/§13): beide neuen
Aktionen laufen über exakt dieselbe Safety-/Backup-/Journal-/
Verifikations-Infrastruktur wie Artist Casing/Legacy Genre/Set Genre
(`executor.py::safety_check()`/`_sha256()`/`_audio_essence_md5()`/
`tags_fingerprint()`, `RepairJournal`, geteilter Lock/Run-Index aus
`run_tracking.py`, ADR-0004).

### 15.1 🎤 Artist bearbeiten

Explizite, vom Nutzer eingegebene Zielwerte für ©ART/ARTISTS-Freeform —
**KEINE** Artist-Casing-Korrektur, Normalisierung oder Identity-Resolution
(Auftrag §6). Scope ist Artist-weit (identische Zielmenge wie Artist
Casing, `maintenance_service.py::artist_targets()`), die tatsächliche
Änderung bleibt **tag-wert-getrieben** (ARCH-031 B.8):
`executor.py::apply_artist_rename()` wendet
`artist_domain.build_manual_rename_map(alter_wert, neuer_wert)` +
`artist_domain.normalize_values()` **unverändert wieder** (dieselbe
Multi-Artist-Tag-Semantik wie `apply_artist_casing()`) — eine Datei ändert
sich nur, wenn ihr tatsächlicher Tag-Wert (casefold) dem gewählten
Ausgangswert entspricht. Eigene `issue_code`/`action`-Labels
(`ARTIST_MANUAL_RENAME`) halten Journal/History getrennt von echten
Casing-Fixes.

```text
🎤 Artist bearbeiten (libmaint:meta:artist:<idx>)
   ↓
Freitext-Eingabe (neuer Artist-Name, context.user_data-Muster wie
Genre setzen, libmaint_awaiting_artist_text)
   ↓
Preview (read-only, preview_artist_rename() — identischer Wert wie
der Ausgangs-Artist ⇒ 0 Änderungen ⇒ eigene Rückmeldung, keine
künstliche Reparatur, Auftrag §14)
   ↓
explizite Bestätigung (libmaint:meta:artist:confirm)
   ↓
Execute (execute_artist_rename(), Lock-Status vorab geprüft) → Ergebnis
```

### 15.2 🎵 Titel bearbeiten

**Immer track-spezifisch** (Auftrag §8) — eigener, index-basierter
Track-Picker (`libmaint:meta:title:<idx>` → `libmaint:meta:title:pick:
<idx>:<track_idx>`, `maintenance_service.py::resolve_track_by_index()`,
identische Zielmenge/Anti-Injection-Muster wie
`library_artists.py::resolve_artist_by_index()` — kein Rohpfad in
`callback_data`). `executor.py::apply_title_edit()` schreibt **nur**
©nam — **kein automatischer TitleCleaner** (Auftrag §8/9): der manuell
eingegebene Zielwert wird unverändert übernommen, die automatische
Title-Cleanup-/Reprocessing-Pipeline
(`services/metadata/track_reprocessor.py`, `META_TITLE_NOT_CLEAN` →
`METADATA_REPROCESSING`, §6a) bleibt vollständig unberührt — beide Pfade
sind bewusst getrennt.

```text
🎵 Titel bearbeiten (libmaint:meta:title:<idx>)
   ↓
Track wählen (index-basiert, libmaint:meta:title:pick:<idx>:<track_idx>)
   ↓
Freitext-Eingabe (neuer Titel, libmaint_awaiting_title_text)
   ↓
Preview (read-only, preview_title_edit())
   ↓
explizite Bestätigung (libmaint:meta:title:confirm)
   ↓
Execute (execute_title_edit(), Lock-Status vorab geprüft) → Ergebnis
```

### 15.3 🎭 Genre-Verwaltung

Keine zweite Genre-Schreib-/Preview-/Confirmation-/Mapping-Logik: der
Button unter „📝 Metadaten bearbeiten" (`libmaint:meta:<idx>` →
„🎭 Genre-Verwaltung") führt in denselben, bereits bestehenden
`genremenu:*`-Flow (§14.1) wie der weiterhin unveränderte direkte Button
auf dem Aktions-Auswahl-Bildschirm — beide Zugänge bleiben nebeneinander
erreichbar.

### 15.4 Validierung

Format-Validierung (leer/Whitespace-only/Zeilenumbrüche/max. 200 Zeichen)
in `handlers/library_maintenance_handler.py::_validate_manual_meta_input()`
(Retry-freundlich, identisches Prinzip wie
`_validate_manual_genre_input()`), zusätzlich Defense-in-Depth in
`maintenance_service.py::_validate_manual_value()` (wirft
`MaintenanceServiceError`). Identischer alter/neuer Wert erzeugt **keine**
künstliche Reparatur — die Preview zeigt stattdessen „Der neue Wert
entspricht bereits dem aktuellen Wert." (0 tatsächlich geänderte
Dateien laut Executor-Diff, kein Sonderfall im Domain-Code nötig).

### 15.5 Tests

| Datei | Deckt ab |
|---|---|
| `tests/test_library_repair_artist.py` | `build_manual_rename_map()` — Single-Entry-Map, Zusammenspiel mit `normalize_values()` (voller Rename vs. identischer Wert) |
| `tests/test_library_repair_executor.py` (`TestApplyArtistRename`/`TestApplyTitleEdit`/`TestReadCurrentTitle`) | Dry-Run/Success/Skipped (tag-wert-getrieben bzw. bereits korrekt)/Safety/Audio-Essenz/Fingerprint/Journal/Rollback, kein automatischer TitleCleaner |
| `tests/test_library_repair_maintenance_service.py` | `resolve_track_by_index()`, `current_title()`, `_validate_manual_value()`, Preview/Execute für beide Flows, Lock-Sharing mit dem übrigen Repair-/Maintenance-Flow |
| `tests/test_library_maintenance_metadata_edit.py` | Telegram-Handler-Ebene: `meta`-Menü, kompletter Artist-/Titel-Zustandsautomat inkl. Freitext-Validierung, Track-Picker (Index-basiert, kein Rohpfad), kein Auto-Start an jedem Zwischenschritt, Lock-Konflikt-Anzeige |
| `tests/test_rich_menu_library_maintenance.py` (`TestMetadataEditDispatchRouting`) | Dispatcher-Routing für alle `libmaint:meta:*`-Callback-Muster (Admin-Gate, korrekte Handler-Methode, korrekt durchgereichte Argumente, unbekannte Sub-Callbacks) |

---

## 16. Manual Metadata Editing v2 — Album + Album Artist (2026-09-20)

**Herkunft:** Folgeauftrag zu §15 — erweitert „📝 Metadaten bearbeiten" um
💿 Album bearbeiten und 👤 Albuminterpret bearbeiten. Baut vollständig auf
§15s Architektur auf (Handler → Service → Executor, Preview → explizite
Bestätigung → Execute, dieselbe Backup-/Journal-/Audio-Essenz-/
Fingerprint-Infrastruktur) — **keine neue Schreib-Pipeline**.

### 16.1 Album-Scope — verzeichnisbasiert, nicht ©alb-tag-basiert

Der Album-Kontext wird **exakt wie im bestehenden Health-Scanner**
bestimmt (`services/library_health/discovery.py::
_classify_section_and_dirs()` / `group_analysis.py`s
`(artist_directory, album_directory)`-Gruppierung, wiederverwendet statt
neu erfunden): jedes direkte Unterverzeichnis eines Artist-Ordners AUSSER
„Singles" (case-insensitiv) ist ein Album-Kontext
(`library_artists.py::list_artist_albums()`/`resolve_album_by_index()`,
identisches Index-Picker-Muster wie die Artist-Auswahl).
`maintenance_service.py::album_targets()` listet die `.m4a`-Dateien genau
dieses Verzeichnisses (identisches Muster wie `artist_targets()`, eine
Ebene tiefer).

Bewusst **nicht** über `©alb == angefragter Wert`: zwei Ordner mit
identischem sichtbaren Albumnamen (z. B. `2024 - Album X` vs.
`2025 - Album X`) bleiben unabhängige, getrennt bearbeitbare Scopes; ein
Ordner mit bereits inkonsistenten `©alb`-Werten bleibt vollständig im
Scope — genau diese Vereinheitlichung ist der Zweck von Album Editing.

### 16.2 💿 Album bearbeiten / 👤 Albuminterpret bearbeiten

`executor.py::apply_album_edit()`/`apply_album_artist_edit()` schreiben
**unbedingt pro Datei** im (bereits server-seitig aufgelösten) Scope —
anders als `apply_artist_rename()` (tag-wert-gefiltert, Artist-weiter
Scope kann mehrere Album-Kontexte enthalten) gibt es innerhalb eines
Album-Ordners keine analoge „gehört nicht dazu"-Mehrdeutigkeit; jede
Datei im Ordner wird individuell verglichen und nur bei Abweichung
geschrieben (Idempotenz-Skip, identisches Prinzip wie
`apply_set_genre()`).

`apply_album_edit()` setzt ausschließlich `©alb`. `apply_album_artist_edit()`
setzt ausschließlich `aART` — `©ART`/`©alb`/`©nam`/`©gen`/`©day` bleiben
garantiert unverändert (Fingerprint-Diff-Prüfung erzwingt das, identisches
Prinzip wie bei `apply_title_edit()`). Keine automatische Synchronisierung
zwischen Artist/Album-Artist/Album (Auftrag §12) — jede der vier manuellen
Operationen (Artist/Titel/Album/Albuminterpret) bleibt unabhängig.

```text
💿 Album bearbeiten (libmaint:meta:album:<idx>)
   ↓
Album wählen (index-basiert, libmaint:meta:album:pick:<idx>:<album_idx>)
   ↓
Freitext-Eingabe (neuer Albumname, libmaint_awaiting_album_text)
   ↓
Preview (read-only, preview_album_edit())
   ↓
explizite Bestätigung (libmaint:meta:album:confirm)
   ↓
Execute (execute_album_edit()) → Ergebnis

👤 Albuminterpret bearbeiten (libmaint:meta:albumartist:<idx>)
   ↓ (identischer Album-Picker wie oben, eigene Callback-Route)
Album wählen (libmaint:meta:albumartist:pick:<idx>:<album_idx>)
   ↓
Freitext-Eingabe (neuer Albuminterpret, libmaint_awaiting_albumartist_text)
   ↓
Preview (read-only, preview_album_artist_edit())
   ↓
explizite Bestätigung (libmaint:meta:albumartist:confirm)
   ↓
Execute (execute_album_artist_edit()) → Ergebnis
```

### 16.3 State Cleanup (Review-Fund aus v1)

Beim Review von v1 fiel auf, dass jeder Flow-Einstiegspunkt bisher nur
sein **eigenes** `awaiting_*_text`-Flag setzte, ohne die Flags/temporären
Werte der jeweils anderen Flows zu löschen — ein abgebrochener Artist-
Edit konnte so sein Flag an einen später gestarteten Titel-Edit
„vererben". Mit v2 (vier statt zwei Flows) wurde das behoben:
`LibraryMaintenanceHandler._reset_meta_edit_state()` löscht an JEDEM
neuen Flow-Einstiegspunkt (Artist/Titel/Album/Albuminterpret) alle vier
`awaiting_*_text`-Flags sowie die temporären Anzeige-/Zielwerte, bevor
der jeweilige Flow sein eigenes Flag setzt — rückwirkend auch für die
bestehenden v1-Flows angewendet (Auftrag v2 §27, keine funktionale
Änderung an Artist-/Titel-Editing selbst, nur an der Flag-Hygiene).

Zusätzlich wurde die `changed_count == 0`-Meldung beim Artist-Rename
präzisiert: da dieser Flow tag-wert-gefiltert ist, konnte „keine
Änderung" zuvor fälschlich pauschal als „bereits korrekt" dargestellt
werden, obwohl der eigentliche Grund „kein Datei-Tag entspricht dem
gewählten Ausgangswert" sein kann — die Meldung deckt jetzt beide Fälle
ehrlich ab, zusätzlich getrennt vom Fall „Dateien nicht mehr
verfügbar" (Safety-Skip), identisch zum bereits bestehenden Muster bei
Titel-/Album-/Albuminterpret-Editing.

### 16.4 Tests

| Datei | Deckt ab |
|---|---|
| `tests/test_library_repair_library_artists.py` | `list_artist_albums()`/`resolve_album_by_index()` — Sortierung, Singles-Ausschluss (case-insensitiv), gleicher Albumname in unterschiedlichen Verzeichnissen bleibt getrennt, versteckte/symlink-Verzeichnisse ausgeschlossen |
| `tests/test_library_repair_executor.py` (`TestApplyAlbumEdit`/`TestApplyAlbumArtistEdit`/`TestReadCurrentAlbumAndAlbumArtist`) | Dry-Run/Success/Skipped/Safety/Audio-Essenz/Fingerprint/Journal/Rollback, inkonsistente `©alb`-Werte im Ordner werden alle vereinheitlicht, `©ART` bleibt bei Album-Artist-Edit garantiert unverändert |
| `tests/test_library_repair_maintenance_service.py` | `album_targets()` (inkl. Scope-Trennung gleicher Albumnamen), `current_album()`/`current_album_artist()`, `_resolve_within_library()` (Pfad-Containment-Härtung), Preview/Execute für beide Flows |
| `tests/test_library_maintenance_metadata_edit.py` | Vollständiger Album-/Albuminterpret-Zustandsautomat (Picker/Eingabe/Preview/Confirm/Execute), `TestCrossFlowStateReset` (Regressionstest für den v1-Review-Fund) |
| `tests/test_rich_menu_library_maintenance.py` (`TestAlbumMetadataEditDispatchRouting`) | Dispatcher-Routing für `libmaint:meta:album:*`/`libmaint:meta:albumartist:*` |
