# Library Closure — Health-Code → Disposition → Executor Coverage-Matrix

**Typ:** Referenz-/Audit-Snapshot (Library-Closure-Phase, PR A — keine Verhaltensänderung)
**Datum:** 2026-09-09
**Auftrag:** Abschnitt 4/5/32 — vollständige, eindeutige Abdeckung jedes
`services.library_health.issues.ALL_CODES`-Eintrags.

Maschinell gepinnt in `tests/test_library_repair_disposition_matrix.py`
(ergänzt `tests/test_library_repair_planner.py`). Ändert sich die
Klassifikation, schlägt der Test fehl und dieses Dokument wird im selben PR
nachgezogen.

---

## 1. Modell

```text
Health-Issue (issues.py)
      ↓  services/library_repair/planner.py::REGISTRY  (genau 1 RepairSpec pro Code)
RepairSpec.level  (8 interne Stufen)
      ↓  planner.py::disposition_for_level()  (reiner Roll-up, keine zweite Pflege)
Disposition  (AUTO_REPAIR | MANUAL_REVIEW | UNREPAIRABLE)
      ↓
AUTO_REPAIR → genau 1 ausführende Komponente
             (ein executor.py-Codeset ODER resolve_duplicates.py --allow-delete)
      ↓
Post-Repair-Verifikation  (siehe Spalte „Verifikation")
```

**Disposition-Roll-up:**

| RepairLevel | Disposition | Telegram-ausführbar? |
|---|---|---|
| `SAFE_AUTOMATIC` | AUTO_REPAIR | **ja** (`repair_service` / MusicBot Doctor) |
| `METADATA_REPROCESSING` | AUTO_REPAIR | nein — CLI-only |
| `EXTERNAL_METADATA` | AUTO_REPAIR | nein — CLI-only |
| `COVER` | AUTO_REPAIR | nein — CLI-only |
| `LOUDNESS` | AUTO_REPAIR | nein — CLI-only |
| `DUPLICATE` | AUTO_REPAIR | nein — CLI-only, destruktiv, `--allow-delete --artist` |
| `MANUAL_REVIEW` | MANUAL_REVIEW | — |
| `NOT_REPAIRABLE` | UNREPAIRABLE | — |

> „AUTO_REPAIR" heißt **es gibt einen Executor**, nicht „läuft ohne
> Freigabe". Ob ein Code über Telegram erreichbar ist, entscheidet allein
> `filter_plan(level="SAFE_AUTOMATIC")` / `get_safe_automatic_candidates()` —
> identische Grenze wie `scripts/library_repair.py --apply` auf der CLI
> (`docs/LIBRARY_REPAIR.md` §3/§9/§10).

**Verteilung (Snapshot 2026-09-09):** 53 Codes — **29 AUTO_REPAIR**,
**22 MANUAL_REVIEW**, **2 UNREPAIRABLE**.

---

## 2. AUTO_REPAIR (29)

| Health-Code | Level | Ausführende Komponente | Verifikation |
|---|---|---|---|
| `GENRE_DELIMITER_INCONSISTENT` | SAFE_AUTOMATIC | `executor.apply_level1` (`L1_TAG_CODES`) | Ziel-Atom == erwarteter Wert **und** Audio-Essenz-MD5 byte-identisch vor `replace`; + Einzeldatei-Recheck (PR E); + aggregierter Verification-Scan |
| `MULTI_ARTIST_SUSPICIOUS` | SAFE_AUTOMATIC | `executor.apply_level1` | wie oben |
| `MULTI_ARTIST_INCONSISTENT` | SAFE_AUTOMATIC | `executor.apply_level1` | wie oben |
| `MULTI_ARTIST_DUPLICATE` | SAFE_AUTOMATIC | `executor.apply_level1` | wie oben |
| `META_ALBUM_ARTIST_MISSING` | SAFE_AUTOMATIC | `executor.apply_level1` | wie oben |
| `ALBUM_ARTIST_INCONSISTENT` | SAFE_AUTOMATIC | `executor.apply_level1` | Ziel-Atom + Audio-Essenz; **album-scope** → nur aggregierter Verification-Scan (kein Einzeldatei-Recheck, PR E) |
| `FILENAME_TITLE_MISMATCH` | SAFE_AUTOMATIC | `executor.apply_level1_rename` (`L1_RENAME_CODES`) | Byte-Inhalt vorher == nachher, MP4 nach Rename lesbar, `O_EXCL`-Claim (TOCTOU); + Einzeldatei-Recheck (PR E); real hohe SKIP-Rate (nur additive Abweichung) |
| `FILENAME_SUSPICIOUS` | SAFE_AUTOMATIC | `executor.apply_level1_rename` | wie oben |
| `META_ARTIST_MISSING` | METADATA_REPROCESSING | `executor.apply_level2` → `track_reprocessor.process_file()` (`L2_CODES`) | `_l2_issue_resolved("META_ARTIST_MISSING", changes)` — SUCCESS nur wenn Feld `artist` laut Pipeline-Diff geändert; + Audio-Essenz; + aggregierter Scan |
| `META_TITLE_MISSING` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `title` |
| `META_TITLE_NOT_CLEAN` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `title` |
| `META_ALBUM_MISSING` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `album` |
| `META_GENRE_MISSING` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `genre_tag`/`genre_freeform` (Production-Audit 2026-09-08: vorher toter `EXTERNAL_METADATA`) |
| `GENRE_EMPTY` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `genre_tag`/`genre_freeform` |
| `GENRE_INVALID` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `genre_tag`/`genre_freeform` |
| `LYRICS_MISSING` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `lyrics_present` |
| `LYRICS_EMPTY` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `lyrics_present` |
| `LYRICS_INVALID` | METADATA_REPROCESSING | `executor.apply_level2` | Zielfeld `lyrics_present` |
| `META_MB_RECORDING_MISSING` | EXTERNAL_METADATA | `executor.apply_external_metadata` → `MusicBrainzClient` (`EXTERNAL_MB_CODES`) | nur FEHLENDE Felder ergänzt; Atom-Verifikation + Audio-Essenz; + Einzeldatei-Recheck (PR E); Eindeutigkeit prüft der Client (MB-01) |
| `META_MB_RELEASE_MISSING` | EXTERNAL_METADATA | `executor.apply_external_metadata` | wie oben |
| `META_ISRC_MISSING` | EXTERNAL_METADATA | `executor.apply_external_metadata` | wie oben |
| `ARTWORK_MISSING` | COVER | `executor.apply_cover_repairs` → `CoverProcessor` (`COVER_ISSUE_CODES`) | `cover_repairs.decide_cover_action()` only-if-better; Cover-SHA + Audio-Essenz; + Einzeldatei-Recheck (PR E) |
| `ARTWORK_INVALID` | COVER | `executor.apply_cover_repairs` | wie oben |
| `ARTWORK_LOW_RESOLUTION` | COVER | `executor.apply_cover_repairs` | wie oben (mind. +200 px) |
| `ARTWORK_NON_SQUARE` | COVER | `executor.apply_cover_repairs` | wie oben (quadratisch, kein Auflösungsverlust) |
| `ALBUM_COVER_INCONSISTENT` | COVER | `executor.apply_album_cover_unify` (`ALBUM_COVER_CODES`) | offline, bestes vorhandenes Album-Cover; Cover-SHA + Audio-Essenz; **album-scope** → nur aggregierter Verification-Scan |
| `LOUDNESS_OFF_TARGET` | LOUDNESS | `executor.apply_replaygain` → `replaygain_repairs` (`LOUDNESS_ISSUE_CODES`) | verlustfreier `replaygain_track_gain`/`_peak`-Tag, **Audio byte-identisch**; Atom-Verifikation; + Einzeldatei-Recheck (PR E, `--measure-loudness`); aggregierter Scan mit `--measure-loudness` |
| `DUPLICATE_EXACT` | DUPLICATE | `scripts/resolve_duplicates.py` (`library_repair.py --allow-delete --artist`) | Fingerprint-/TOCTOU-Pre-Delete-Revalidierung, Gruppen-Atomarität, **Backup vor jedem `unlink()`** (`docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md`) |
| `DUPLICATE_RECORDING` | DUPLICATE | `scripts/resolve_duplicates.py` | wie oben, zusätzlich ISRC-Mismatch-Safety-Gate |

---

## 3. MANUAL_REVIEW (22)

Kein sicherer automatischer Pfad — Nutzer entscheidet. `expected_change`
(Spalte „Begründung") ist in `planner.py::_SPECS` dokumentiert und
per Test als nicht-leer gepinnt.

| Health-Code | Begründung (Kurz) |
|---|---|
| `META_NOT_ANALYZABLE` | Tag-Container defekt — manuell prüfen / neu laden |
| `META_YEAR_MISSING` | keine Jahr-Fetch-Implementierung vorhanden (Production-Audit 2026-09-08) |
| `META_YEAR_INVALID` | unplausibles Jahr — korrekter Wert nicht eindeutig |
| `META_TRACK_NUMBER_MISSING` | Tracknummer nicht sicher ableitbar |
| `AUDIO_NOT_ANALYZABLE` | Datei nicht analysierbar — manuell prüfen / neu laden |
| `AUDIO_NO_STREAM` | kein Audio-Stream — Neu-Download ist Nutzerentscheidung |
| `AUDIO_CORRUPT` | beschädigte Datei — Neu-Download ist Nutzerentscheidung |
| `AUDIO_LOW_BITRATE` | ggf. in besserer Qualität neu laden — Nutzerentscheidung |
| `AUDIO_VERY_SHORT` | Skit/Intro oder abgeschnitten? nicht sicher unterscheidbar |
| `LOUDNESS_TAG_INVALID` | kaputter Legacy-ReplayGain-Tag — manuell entfernen/prüfen |
| `LOUDNESS_TAG_PARTIAL` | unvollständige Legacy-Tag-Familie — manuell prüfen |
| `STRUCTURE_INVALID_PATH` | außerhalb der Library-Struktur — kein Auto-Move (Auftrag §7) |
| `STRUCTURE_FILE_OUTSIDE_HIERARCHY` | Datei im falschen Ordner — kein Auto-Move |
| `FILENAME_EXTENSION_UNEXPECTED` | Format-Konvertierung ist keine sichere Auto-Reparatur |
| `ALBUM_TRACK_GAP` | fehlende Tracks — Nutzer entscheidet, ob nachladen |
| `ALBUM_DUPLICATE_TRACK_NUMBER` | korrekte Zuordnung nicht eindeutig |
| `ALBUM_NAME_INCONSISTENT` | korrekter Album-Name nicht eindeutig |
| `ALBUM_YEAR_INCONSISTENT` | korrektes Jahr nicht eindeutig |
| `ALBUM_RELEASE_ID_INCONSISTENT` | mehrere vorhandene Release-IDs — welche kanonisch ist, manuell (würde bestehende Werte überschreiben; Production-Audit 2026-09-08) |
| `ARTIST_DIR_TAG_MISMATCH` | Verzeichnis-Umbenennung ist keine sichere Auto-Reparatur |
| `ARTIST_NAME_VARIANTS` | Ordner zusammenführen ist eine Strukturänderung |
| `DUPLICATE_SUSPECTED` | Remix/Live möglich — immer manuelle Prüfung (DUP-03) |

---

## 4. UNREPAIRABLE (2)

Legitime Beobachtung, es gibt bewusst nichts zu tun (`NOT_REPAIRABLE`).

| Health-Code | Begründung |
|---|---|
| `LOUDNESS_TAG_MISSING` | Legacy-ReplayGain-Tag; die aktuelle Download-Pipeline schreibt ihn bewusst nicht (normalisiert vorher per loudnorm) — INFO, kein Defekt |
| `ALBUM_GENRE_INCONSISTENT` | unterschiedliche Genres im Album können legitim sein — reine Beobachtung |

---

## 5. Konsistenz-Nachweise (Test)

`tests/test_library_repair_disposition_matrix.py`:

- `test_every_health_code_has_exactly_one_known_disposition`
- `test_disposition_is_pure_rollup_of_the_planner_level`
- `test_every_repair_level_is_classified`
- `test_disposition_partition_sizes_snapshot` (53 / 29 / 22 / 2)
- `test_every_auto_repair_code_has_exactly_one_executor`
- `test_executor_code_sets_are_pairwise_disjoint`
- `test_no_executor_code_set_contains_a_non_auto_repair_code`
- `test_union_of_all_executors_covers_exactly_the_auto_repair_codes`
- `test_duplicate_docked_codes_route_to_the_duplicate_level`
- `test_manual_review_and_unrepairable_codes_document_a_reason`
- `test_unrepairable_codes_have_no_executor`

Ergänzend `tests/test_library_repair_planner.py`:
`test_every_health_code_has_a_repair_mapping` /
`test_registry_has_no_stale_codes`.
