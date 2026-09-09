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
| 2026-09-09 | Finding A (Download-Pipeline-Testlauf, live): Feature-Artists aus einem `feat.`/`ft.` **im Titel** gingen komplett verloren — `EnhancedMetadataProcessor` las `youtube_parsed["featuring"]` nie. Additiv zusammengeführt. E2E-Regressionstest (`test_metadata_processor_happy_path.py` +2), Pre-Fix-Diskriminierung bestätigt. | #180 | `-k "metadata or feat or … or youtube_parser"` 592 grün |
| 2026-09-09 | Finding F: deutscher Video-Marker (`(Offizielles Musikvideo)`) klebte am Feature-Namen — `_extract_features()` fängt jetzt nur bis zur ersten öffnenden Klammer. Durch PR #180 von P3 auf P1 gehoben (Wert landet seither sichtbar im Tag). `test_youtube_parser_feat_video_marker.py` (neu, 8). | #182 | `-k "youtube_parser or duplicate or metadata or feat or title_clean or artist"` 1133 grün |
| 2026-09-09 | Finding C: 8-Zeichen-All-Caps-Kanalname „MARTERIA" wurde als Akronym gelernt + nach `case_preserve.yaml` persistiert → jedes „Marteria" → „MARTERIA". RULE-2-Schwelle `<= 8` → `<= 6`. `test_artist_normalizer.py` +4. (black hat `utils/artist_map.py` beim selben Commit vollständig neu formatiert — Tabs→Spaces, keine Logikänderung, per Suite verifiziert.) | #183 | `-k "artist or normaliz or duplicate or metadata or case_preserve or genre"` 1247 grün |
| 2026-09-09 | Finding B: Fuzzy-Channel-Match (`WRatio`, Schwelle 75) matchte `Akon`→`kontor.tv` (77) und `Digster Pop Music`→`vibe music` (85) → falsches `channel_fuzzy`-Genre `Electronic`. Schwelle Channel-Fuzzy **75 → 90** (Artist-Fuzzy unverändert 85). `test_genre_map_channel_fuzzy_false_positive.py` (neu, 6). | #185 | `-k "genre or metadata or channel or auto_learn"` 638 grün |
| 2026-09-09 | Finding H (durch B-Fix sichtbar): Last.fm-User-Tags (`laut mitsing`/`eingedeutscht`/`radio`) wurden im `prioritize_genres()`-Fallback-Zweig blind zu `©gen: Laut Mitsing`. Fallback verlangt jetzt ein als Genre erkennbares Tag; sonst generisches Genre (`pop`) als Notnagel, sonst `Unknown`. `test_genre_processor.py` +3, 1 ARCH-022-Charakterisierungstest auf Sollverhalten umgestellt. | #187 | `-k "genre or musicbrainz or metadata or auto_learn or lastfm"` 651 grün |
| 2026-09-09 | **Download-Pipeline-Optimierung K1** — Loudness in Schritt 15b lief als voller AAC→AAC-Re-Encode (`AudioEnhancer.normalize_loudness()`, ~22 s = ~49 % der Pipeline). Ersetzt durch `services/metadata/loudness_replaygain.py::apply_replaygain_tags()`: EBU-R128-Scan (rsgain ~1,5 s / FFmpeg-Fallback) + verlustfreier `replaygain_track_gain`/`_peak`-Tag (Navidrome), Audio byte-identisch. Schließt das DEFER-Finding „Schritt 15b LUFS-Ziel verifizieren". `test_loudness_replaygain.py` (neu, 12), 8 EMP-Testdateien auf den neuen Hook umgestellt. | #188 | `-k "download or metadata or reprocess or duplicate or enhanced or loudness"` 1165 grün |
| 2026-09-09 | **Download-Pipeline-Optimierung H2** — `MusicBrainzClient.fetch_metadata()` wird pro Track ~2× aufgerufen (Genre + Album); die Suche war gecacht, der teure `get_recording_by_id()`-Detail-Call lief jedes Mal (~1 s + MB 1-req/s-Limit). Jetzt unter `recording_detail:<mbid>` im selben TTLCache. `test_musicbrainz_client.py` +1. | #189 | `-k "musicbrainz or genre or album or cover or metadata_processor or enhanced_metadata"` 579 grün |
| 2026-09-09 | **Download-Pipeline-Optimierung H1** — yt-dlp-Metadaten wurden pro Download 2× extrahiert (Duplicate-Vorab-Probe + Download-Pfad, je ~3-4 s). Prozessweiter Kurzzeit-Cache in `DownloadExecutor.extract_info_async(use_cache=True)` (TTL 120 s, nur `download=False`, Mix-URLs ausgenommen, Retry ≥ 1 holt frisch). `test_download_executor.py::TestExtractInfoCache` (+6). | #190 | `-k "download or duplicate or metadata_processor or enhanced_metadata or youtube"` 888 grün |
| 2026-09-09 | **Download-Pipeline-Optimierung H3** — Cover-Quellen-Suche lief sequenziell (allein Cover Art Archive ~6 s). Primär-Tier (Prio ≥ 50: CAA/Fanart Album/Apple/Deezer/Fanart Artist) jetzt parallel via `ThreadPoolExecutor`, danach einmal Early-Exit/Ranking; YouTube-Fallbacks (Prio 30) nur bei Bedarf, sequenziell. Gewinner-Auswahl unverändert. `test_cover_processor_validation.py` (Orchestrierung + Timing-Beweis). | #191 | `-k "cover or metadata_processor or enhanced_metadata or download"` 524 grün |
| 2026-09-09 | **Download-Pipeline-Optimierung M1** — Schritt 19d `ArtistIdentityResolver.refresh()` (Library-Disk-Walk + 3 YAML-Reloads) lief pauschal bei jedem `known=False`-Track. Jetzt nur bei tatsächlicher Änderung: neuer Artist-Ordner ODER AutoLearn-Schreibvorgang (`learn_artist()`-Bool / `LEARNED`/`UPDATED`-Feature-Entscheidung ausgewertet). `test_metadata_processor_happy_path.py` +2. | #192 | artist-identity/autolearn/EMP/playlist/reprocess 217 grün |
| 2026-09-09 | Finding E Folge-Fund (Fritz Kalkbrenner „Sky and Sand", Re-Download): Aufnahme existiert in MB nur auf Compilations/DJ-Mixen → `_select_primary_release()` liefert zwangsläufig eine Compilation, deren Datum (2018) wurde trotzdem das Jahr. Jetzt: bei „nur Compilations" kein `release_date` aus Release-/RG-Datum → `AlbumProcessor` fällt auf YouTube-/Upload-Jahr zurück; `release_id`/`album` unverändert vom frühesten Release. `first-release-date` am Recording bleibt maßgeblich. `TestSelectPrimaryReleaseFindingE` (+2, 1 umbenannt). | #197 | `test_musicbrainz_client.py` thematisch grün (volle Suite beim Nutzer) |
| 2026-09-09 | Finding E (Download-Pipeline-Log-Analyse): MusicBrainz-`release-list` einer Aufnahme ist unsortiert — `_build_metadata()` nahm blind `release_list[0]` für Album/Jahr/`release_id`, real oft eine Compilation/DJ-Mix (Akon „Smack That" → 2009 statt 2006). Neu: `_select_primary_release()` stellt Compilations zurück und wählt die früheste datierte Veröffentlichung; `release_date` fällt zusätzlich auf `first_release["date"]` zurück. `first-release-date` von Recording/Release-Group bleibt höher priorisiert. `test_musicbrainz_client.py::TestSelectPrimaryReleaseFindingE` (+4), Pre-Fix-Diskriminierung via `git stash` bestätigt. | #196 | `test_musicbrainz_client.py` + `test_album_processor.py` 52, `test_genre_processor.py` + happy path 54 grün (volle Suite beim Nutzer) |
| 2026-09-09 | Finding G (Download-Pipeline-Log-Analyse): MusicBrainz-`TimeoutError` in `fetch_metadata()` lief in den generischen `except Exception`-Zweig → `💥 Unerwarteter Fehler` + Stacktrace auf ERROR, obwohl der Last.fm-Fallback der Normalfall ist. Eigener `except asyncio.TimeoutError` vor dem generischen, WARNING ohne exc_info. `test_musicbrainz_client.py` +1, Pre-Fix-Diskriminierung via `git stash` bestätigt. | #195 | `test_musicbrainz_client.py` 31 grün (volle Suite beim Nutzer) |
| 2026-09-09 | Finding „Fritz & Paul Kalkbrenner" (Download-Pipeline-Testlauf, live): gemeinsamer Nachname — `_split_multi_artists()` zerlegt „Fritz & Paul Kalkbrenner" in `["Fritz", "Paul Kalkbrenner"]`, der abgeschnittene Primär „Fritz" ist eine andere, reale Band → Last.fm-Tags → Genre „Indie", Ordner „Fritz/". Generischer Split-Fix unsicher (echte Doppel-Primär-Acts) → gezielter Mapping-Override (8 Kollab-Schreibweisen + Self-Eintrag → „Fritz Kalkbrenner", Nutzer-Entscheid: Paul als Zweit-Artist) **plus** neuer `EnhancedMetadataProcessor`-Schritt 6a: der ungesplittete Roh-Artist-String (`raw_artist_string` / `", ".join(all_artists)`) wird gegen die Override-Stufe des `ArtistIdentityResolver` geprüft; greift ein Override, das den abgeschnittenen ersten Künstler erweitert, wird `all_artists[0]` ersetzt. Bare „Fritz" unberührt. `test_collab_artist_shared_surname_kalkbrenner.py` (neu, 10), Pre-Fix-Diskriminierung via `git stash` bestätigt. | #194 | `-k` artist/identity/override/youtube_parser/metadata_processor/genre/special_channel thematisch grün (volle Suite beim Nutzer) |
| 2026-09-09 | Nachprüf-Durchgang `requested_issue` im Telegram-Doctor-/Repair-MusicBot-Pfad: **kein Finding** — `apply_level2()`/`requested_issue` sind CLI-only, die Telegram-Pfade (`doctor_runner.py`, `repair_service.py`) laufen ausschliesslich `--level SAFE_AUTOMATIC` (L2 doppelt ausgeschlossen: Planner-Level-Filter + `l2_requested`-Gate), die „Reprocessing"-Ansicht ruft `process_file()` ohne den Parameter. Sicherheitsgrenze in `test_library_repair_cli_safe_automatic_scope.py` (2) gepinnt; `docs/LIBRARY_REPAIR.md` §6a um einen Reichweiten-Absatz ergänzt. Kein Produktionscode geändert. | #179 | `-k "library_repair or planner or doctor or repair_service or repair_integration or repair_musicbot"` 285 grün |

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
