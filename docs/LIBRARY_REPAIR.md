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
| Duplicate | ⏳ offen (`--allow-delete` abgelehnt) | — |

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
Before/After-Werte, ohne zu schreiben. `--allow-delete` wird abgelehnt.

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
executor.py      apply_level1() / apply_level1_rename() -> [ExecOutcome]
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
| `METADATA_REPROCESSING` | volle Neuverarbeitung über die echte Pipeline | `services/metadata/track_reprocessor.py::process_file` (in-process, echte config.Config) | ja | ja | nein |
| `EXTERNAL_METADATA` | fehlende MB-IDs / ISRC / Jahr / Genre | `MusicBrainzClient` / `GenreProcessor` | ja | ja | nein |
| `COVER` | fehlendes / schlechtes / uneinheitliches Cover | `CoverProcessor` | ja | ja | nein |
| `LOUDNESS` | gemessene Lautheit > 2 dB neben −16 LUFS (`LOUDNESS_OFF_TARGET`) | `replaygain_repairs` — verlustfreier `replaygain_track_gain`-Tag | ja | ja | nein (Audio byte-identisch) |
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
| `META_TITLE_NOT_CLEAN` | METADATA_REPROCESSING | Titel über die reale Pipeline bereinigen (Anführungszeichen/`prod.`/Marketing-Suffix raus), Audio unverändert |
| `GENRE_INVALID` / `LYRICS_*` | METADATA_REPROCESSING | Genre/Lyrics neu bestimmen |
| `META_MB_*_MISSING` / `META_ISRC_MISSING` / `META_YEAR_MISSING` | EXTERNAL_METADATA | MusicBrainz-Match (nur bei Eindeutigkeit) |
| `META_GENRE_MISSING` / `GENRE_EMPTY` | EXTERNAL_METADATA | GenreProcessor-Fallback-Kette |
| `ALBUM_RELEASE_ID_INCONSISTENT` | EXTERNAL_METADATA | alle Tracks auf DIE Release-ID mappen |
| `ARTWORK_MISSING` / `_INVALID` / `_LOW_RESOLUTION` / `_NON_SQUARE` / `ALBUM_COVER_INCONSISTENT` | COVER | `CoverProcessor` — nur ersetzen bei eindeutig besserem Cover |
| `LOUDNESS_OFF_TARGET` | LOUDNESS | `replaygain_track_gain`-/`_peak`-Tag schreiben (Ziel −16 LUFS, **Audio byte-identisch**), Backup + Rollback |
| `LOUDNESS_TAG_MISSING` | NOT_REPAIRABLE | Legacy-ReplayGain-Tag; aktuelle Pipeline schreibt ihn bewusst nicht |
| `LOUDNESS_TAG_INVALID` / `_PARTIAL` | MANUAL_REVIEW | kaputter/unvollständiger Legacy-Tag — manuell prüfen |
| `DUPLICATE_EXACT` / `DUPLICATE_RECORDING` | DUPLICATE | `resolve_duplicates.py` — nur mit `--allow-delete` + Freigabe |

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

- **Duplicate** (`resolve_duplicates.py` — destruktiv, `--allow-delete`).

## 6a. Level-2-Executor — volle Neuverarbeitung (implementiert)

`--level METADATA_REPROCESSING` bzw. `--issue META_TITLE_NOT_CLEAN` /
`GENRE_INVALID` / `LYRICS_*` / `META_{ARTIST,TITLE,ALBUM}_MISSING` (extern,
langsam — **nie** im Default-`--apply`): `apply_level2(reprocess)`.

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

**DRY-RUN gegen Produktion (`--artist 01099`):** 6 would-change (Recording-/
Release-ID für die Weihnachtslied-Singles), 10 `SKIPPED` (MB kein sicherer
Match für die Album-Tracks). Kein Raten.
