# MusicBot Engineering Baseline v10

> **Status: DRAFT / IN PROGRESS — NICHT eingefroren.**
>
> Dieses Dokument ist der **laufende Zwischenstand** seit dem v9-Freeze
> (2026-09-07). Es wird pro ARCH-Phase / PR mit *ARCH Status*, *Recent Major
> Changes* und *Testzahlen* aktualisiert (CLAUDE.md §30) und erst zu einem
> ausdrücklichen Freeze-Zeitpunkt (nach 🟢-APPROVED-Freeze-Gate-Audit) zum
> eingefrorenen Referenzpunkt gemacht — dann werden die Platzhalter-
> Abschnitte 4–6 befüllt.
>
> **Bis zum v10-Freeze gilt:**
> - Eingefrorener technischer Referenzpunkt = `docs/MusicBot_ENGINEERING_BASELINE_v9.md`.
> - Aktueller Stand aller offenen/zurückgestellten Findings = `docs/FINDINGS_INDEX.md`.
> - Dieses Dokument dupliziert **keine** Findings — es listet nur die
>   Änderungshistorie seit v9 und die rollende Testzahl.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v10 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v9.md` (Freeze 2026-09-07, 2580 passed / 1 skipped / 0 failed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl | **2920 passed, 1 skipped, 0 failed, 19 subtests passed** (Stand PR #176, 2026-09-08) |
| Seither (PR #177/#178) | nur gezielte + thematische Suiten durch den Implementierungsprozess (CLAUDE.md §8.A); PR #178 fügt 3 Regressionstests hinzu (`test_mapping_additions_2026_09_08.py` = 14, `test_library_repair_executor_l2_real_pipeline.py` +2). Volle Suite steht beim Nutzer aus. |
| Zuwachs seit v9-Freeze | +340 passed (Stand PR #176) |
| Freeze-Status | offen — kein Freeze-Gate-Audit durchgeführt |

---

## 2. ARCH Status seit v9-Freeze

| ARCH-Änderung | PR | Ergebnis |
|---|---|---|
| **Artist Identity Resolution & Mapping Separation** (Phase A–F) — dedizierte `ArtistIdentityResolver`-Komponente als alleinige Identitäts-Auflösung; `ArtistNormalizer.normalize()` wird reine String-Normalisierung; `known`-Flag steuert AutoLearn; Library→`artist_overrides.json`-Persistenz entfernt. F-01…F-06 CLOSED, F-07 DEFERRED. Vollständiges Protokoll: `docs/audits/ARTIST_IDENTITY_RESOLUTION_MIGRATION_2026-09-08.md`. | #176 | 2920 passed / 1 skipped / 0 Regressionen |
| **INV-01 / F-08 Closure + mitgelaufene Fixes** — `INV-01` (`duplicate/cache.py` synchrone Event-Loop-Persistenz) als akzeptiertes Restrisiko geschlossen (analog DUP-05); toter Artist-/AutoLearn-Code entfernt (F-08). Im selben PR (als „chore" betitelt): deutsche „(MIT Artist)"-Feature-Credit-Regel in `light_title_cleanup()`; `FILENAME_TITLE_MISMATCH`-Normalisierung (`_normalize_for_compare()`: NFC/casefold/Klammer-Äquivalenz) im Health-Scanner; L2 `process_file(requested_issue=…)` für issue-spezifisches Reprocessing; manuelle Mapping-Ergänzungen. | #177 | thematische Suiten grün (volle Suite beim Nutzer) |
| **Doku-Nachzug + L2-Execute-Fix** — die vier in #177 als „chore" mitgelaufenen Änderungen mit eigener Findings-Zeile + Testbezug nachdokumentiert (`docs/FINDINGS_INDEX.md`). Dabei gefundener Bug: `apply_level2()` reichte `requested_issue` nur im DRY-RUN, nicht im EXECUTE durch (Vorschau ≠ `--apply`) — behoben, Regressionstest ergänzt. Charakterisierungstest für die manuellen Mapping-Ergänzungen. | #178 | gezielte + thematische Suiten grün (`-k "library_repair or library_health"` 431, `-k "title_clean or genre or mapping or artist"` 834; volle Suite beim Nutzer) |

---

## 3. Recent Major Changes (seit v9-Freeze)

| Datum | Änderung | PR | Testzahl danach |
|---|---|---|---|
| 2026-09-08 | Artist-Identity-Resolution-Migration (Phase A–F): `services/metadata/artist_identity_resolver.py` neu; Priorität `artist_override > known_artist > auto_learned_alias > library_identity > musicbrainz_mbid > parser`; `MetadataResult.artist_known`; `EnhancedMetadataProcessor`/`AutoLearnManager`/`DuplicateDetector`/`utils/artist_map.py` umgestellt; toter Alias-Code entfernt. `mapping/`-Dateien inhaltlich unverändert. | #176 | 2920 passed |
| 2026-09-08 | Testinfra: `handlers/test_menu_handler.py::TestMenuHandler.__test__ = False` (pytest-Collection-Sperre, beseitigt 3 Collection-Warnings). | #176 | 2920 passed |
| 2026-09-08 | INV-01 (akzeptiertes Risiko) + F-08 (toter Code) CLOSED. Mitgelaufen: `light_title_cleanup()` deutsche „(MIT Artist)"-Regel; `_normalize_for_compare()` NFC/casefold/Klammer-Äquivalenz gegen `FILENAME_TITLE_MISMATCH`-False-Positives; `process_file(requested_issue=…)` + `apply_level2()`-Durchreichung (DRY-RUN); manuelle Mapping-Ergänzungen (new wave→Pop, Piano Pop→Pop, lea→LEA, +4 known_artists). | #177 | thematische Suiten grün |
| 2026-09-08 | `FINDINGS_INDEX.md`: 4 Nachzugs-Zeilen für die #177-„chore"-Änderungen. Bugfix: `apply_level2()` EXECUTE-Zweig reicht `requested_issue` jetzt ebenfalls durch (war nur DRY-RUN → Vorschau ≠ `--apply`). Neu: `test_mapping_additions_2026_09_08.py` (14), 2 Regressionstests in `test_library_repair_executor_l2_real_pipeline.py`, 3 lokale Reprocess-Stubs auf reale Signatur nachgezogen. | #178 | gezielte + thematische Suiten grün |

---

## 4. Technical Debt — Snapshot

> Platzhalter — wird beim v10-Freeze als Schnappschuss befüllt (Vergleichswert
> zum v9-Stand, CLAUDE.md §30). **Bis dahin maßgeblich:**
> [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md).
>
> Seit v9 neu zurückgestellt: **F-07** (MusicBrainz-Artist-MBID nicht als
> Identitätssignal, P3) — in `FINDINGS_INDEX.md`. **F-08** (deprecated
> Artist-Code) und **INV-01** (`duplicate/cache.py`) sind seit 2026-09-08
> CLOSED (F-08 Cleanup PR #177, INV-01 akzeptiertes Risiko). Kein offener
> P0/P1.

---

## 5. Security-Baseline

> Platzhalter — wird beim v10-Freeze befüllt. Keine sicherheitsrelevante
> Änderung seit v9 im Rahmen der bisher gelisteten PRs.

---

## 6. Architecture Freeze

> Platzhalter — Freeze-Entscheidung (GO/NO-GO mit Evidenz) ist ein
> ausdrücklicher, eigenständiger Prüfschritt (CLAUDE.md §30) und noch nicht
> erfolgt.

---

## Freeze-Checkliste (beim v10-Freeze abzuarbeiten)

- [ ] Freeze-Gate-Audit → 🟢 APPROVED (alle Kriterien PASS, kein offener P0/P1)
- [ ] Abschnitte 4–6 als Schnappschuss befüllen
- [ ] „Baseline Frozen (JJJJ-MM-TT)"-Footer setzen, DRAFT-Kopf entfernen
- [ ] Referenzen umstellen: `README.md`, `docs/INDEX.md`, `CLAUDE.md` §30
- [ ] `docs/MusicBot_ENGINEERING_BASELINE_v9.md` → `docs/archive/`
