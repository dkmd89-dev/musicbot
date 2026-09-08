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

**Bewusst identische Sicherheitsgrenze wie MusicBot Doctor:** nur
`SAFE_AUTOMATIC` ist über Telegram tatsächlich ausführbar (verlustfrei,
kein Netzwerk, kein Re-Encode). Alle externen/destruktiven Level
(`COVER`/`EXTERNAL_METADATA`/`METADATA_REPROCESSING`/`LOUDNESS`/
`DUPLICATE`) werden im Plan/in den Reparaturvorschlägen zwar angezeigt
(🟡 REVIEW, zur Transparenz), bleiben aber CLI-only. Repair MusicBot ist
keine Ausweitung dieser Grenze, sondern eine reichhaltigere Oberfläche
(Plan/Preview/Historie/Statistik) für denselben, bereits etablierten
Ausführungspfad.

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
