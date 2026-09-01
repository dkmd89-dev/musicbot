# MusicBot Engineering Baseline v6

> Nächster verifizierter Engineering-Referenzzustand nach einem strikt
> read-only Post-Baseline-v5 Health & Risk Audit: Re-Verifikation aller 9
> in Baseline v5 als DEFER gelisteten Technical-Debt-Punkte gegen den
> aktuellen Code sowie eine systematische Durchsicht der 28 seit dem
> v5-Freeze gemergten PRs auf neue, bisher undokumentierte Findings.
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md` bleibt als eingefrorene,
> historische Referenz unverändert bestehen (nach Archivierungs-Konvention
> nach `docs/archive/` verschoben).

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-09-01 |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md` (1123 passed / 0 failed, eingefroren 2026-08-26) |
| Herleitung | Dieses Dokument selbst (Post-Baseline-v5 Health & Risk Audit, read-only, kein separates Audit-Dokument) |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1634 passed, 1 skipped, 0 failed**, 19 subtests passed, 2 bekannte harmlose Pytest-Collection-Warnings (unverändert seit mehreren Baselines) |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen dem v5-Freeze (2026-08-26) und heute wurden **28 PRs gemergt**
(#56–#83), die Testsuite wuchs von 1123 auf **1634 passed** (+511, +45 %),
durchgehend 0 failed. Dieser Audit fand **keine neue Regression und keinen
neuen P0/P1-Befund** — die Codebasis ist ungewöhnlich diszipliniert
gepflegt (keine TODO/FIXME-Kommentare im gesamten Produktionscode, jede
ARCH-/Metadata-Quality-/Einzelfund-Phase sauber nach `docs/archive/`
geschlossen).

Kernergebnis der Re-Verifikation der 9 v5-DEFER-Punkte: **5 weiterhin
offen** (unverändert, mit Codebeleg re-bestätigt), **2 vermutlich durch
Nebeneffekt anderer PRs erledigt** (Loudness-Doku, tag_writer-Kommentar),
**2 strukturell unverändert** (siehe Abschnitt 5). Keiner der 9 Punkte ist
P0/P1 — alle bleiben bewusste, dokumentierte Risiken oder werden hier neu
als erledigt markiert.

Zusätzlich wurden während der Arbeit an dieser Session zwei eigenständige
Findings entdeckt und bereits behoben (PR #82, #83) — siehe Abschnitt 3.

---

## 3. Geschlossene Findings (seit v5, diese Session)

| Finding | Bereich | Kernaussage |
|---|---|---|
| DOC-01 `track_number` im YT-Single-Pfad | Download Pipeline | `build_single_track_result()` ließ `track_number` immer beim `DownloadResult`-Dataclass-Default `None`, obwohl `MetadataResult` einen echten, von `album_processor.determine_track_number()` ermittelten Wert trug. Zweimal zuvor identifiziert (ARCH-004 P-3, Download Pipeline Stability Phase 0), aber mangels Downstream-Konsumenten-Analyse zurückgestellt — diese wurde jetzt nachgeholt (kein Konsument betroffen) und der Fix umgesetzt. `playlist_album` bleibt bewusst `None` (kein Bug, korrekt für Singles). PR #82. |
| Test-Isolation: reale Mapping-Writes | Security/Duplicate-Detection (Testinfrastruktur) | Beim vollen Testsuite-Lauf real `mapping/artist_overrides.json` verändert (zwei neue Artist-Einträge aus der echten Produktionsbibliothek) — drittes Auftreten desselben Mechanismus (zweimal zuvor `case_preserve.yaml` betroffen, siehe `ISOLATION-001`). Root Cause: mehrere Produktionsklassen (`PlaylistProcessor`, `MusicBrainzClient._get_artist_normalizer()`, `EnhancedDownloadProcessor`) fallen bei fehlendem Config auf die echte `config.Config()` zurück; `ArtistNormalizer` (Singleton) scannt bei erster Konstruktion synchron die echte Library und schreibt in die echte Override-Datei. Fix: zentrale session-weite `conftest.py`-Fixture patcht `Config.LIBRARY_DIR`/`ARTIST_OVERRIDE_FILE`/`GENRE_MAPPING_DIR` auf sichere tmp-Pfade (GENRE_MAPPING_DIR als Kopie, damit lesende Tests unverändert funktionieren). PR #83. |
| EnhancedErrorHandler-Integration | Telegram-Handler (Robustheit) | 6 Handler (`NavidromeMenuHandler`, `EnhancedDuplicateHandler`, `EnhancedLoggerMenuHandler`, `TestMenuHandler`, `UserManagementHandler`, `BackupHandler`) erhielten `error_handler` injiziert, riefen ihn aber nie auf (63 tote except-Blöcke identifiziert, 24 gezielt verdrahtet, Rest bewusst ausgenommen — private Helfer ohne Update/Context, absichtlich fehlertolerante Schleifen, oder — bei `mugge_statistik_handler.py` — ein struktureller UX-Konflikt, siehe Abschnitt 8). PRs #79–#81. |

Details je Fund: siehe die jeweiligen PR-Beschreibungen (`gh pr view 79..83`) sowie die Commit-Historie; kein separates Audit-Dokument, da jeder Fund einzeln klein genug für eine direkte PR-Beschreibung war.

---

## 4. Seit v5 gemergte PRs (Überblick, #56–#83)

28 PRs, davon bereits vor dieser Session in Arbeit/abgeschlossen (Metadata
Quality Phase, Download Pipeline Stability Phase, Duplicate Resolution
Engine — alle in `docs/INDEX.md` als HISTORICAL/CURRENT nachgewiesen) und
6 in dieser Session (#78–#83, siehe Abschnitt 3):

| Bereich | PRs | Kurzthema |
|---|---|---|
| Download Pipeline Stability Phase 2 | #56 | Release-Merge der Phase-2-Findings (DL-01/DL-02/DUP-03 u. a.) |
| Metadata Quality | #57, #58, #64 | feat./ft.-Erkennung ohne Leerzeichen, Marketing-Suffix-Klammer, video/audio-Wortkombinationen |
| Artist Overrides | #59, #60 | Case-Korrektur makko, t-low |
| Title Cleaner | #61 | Deutsche Video-Compound-Wörter |
| Test-Infrastruktur | #62 | `config_test.py` vollständige Isolation |
| MusicBrainz | #63 | Artist-Similarity-Floor (MB-01) |
| Tag Writer | #65 | Multi-Value-`ARTISTS`-Tag (TAG-01) |
| Reprocessing-Tool | #66 | `scripts/reprocess_artist_metadata.py` |
| Dokumentation | #67, #68, #69 | Projekt-Status-Sync, Findings-Archivierung, ARCH-Referenzkorrektur |
| Auto-Learning | #70 | Confidence-Gating + Featured-Artist-Beobachtung |
| Genre-Mapping | #71, #72 | Non-Genre-Tag-Filter, Semikolon-Separator |
| Audio/Loudness | #73, #74 | Isoliertes LUFS-Reprocessing-Tool, Cover-Korruptions-Fix |
| Client-Refactor | #75 | LastFM/MusicBrainz auf instanzgebundenen Logger |
| Duplicate Resolution | #76, #77, #78 | Classification/Safety-Gates/Execute-Engine, Production-Read-Only-Dry-Run, bestätigter Production-Execute-Pilot (real gegen 3 Artists ausgeführt, 15 Dateien entfernt) |
| EnhancedErrorHandler | #79, #80, #81 | 6 Handler verdrahtet (siehe Abschnitt 3) |
| Download Pipeline Stability | #82 | DOC-01 |
| Test-Infrastruktur | #83 | Sichere Config-Defaults gegen reale Mapping-Writes |

---

## 5. Re-Verifikation der v5-DEFER-Punkte

| ID / Ort | v5-Status | Jetziger Befund | Neuer Status |
|---|---|---|---|
| `move_to_library()` TOCTOU (`utils/filenamefixer.py`) | DEFER P2 | Check-then-Act-Fenster zwischen `while final_target.exists()` und `tmp_target.replace(final_target)` im Code bestätigt weiterhin vorhanden (verifiziert, Zeile ~324–353) | **weiterhin offen, P2** |
| `services/metadata/tag_writer.py` fsync-Kommentar | DEFER P3 | Aktueller Kommentar ist inhaltlich stimmig und referenziert aktuelle Invarianten (INV-01, AE-11) — liest sich nicht mehr „veraltet". Datei wurde seit v5 zweimal für andere Fixes berührt (Genre-Separator, TAG-01), Kommentarinhalt dabei ggf. mit aktualisiert. Nicht durch expliziten Vorher/Nachher-Diff bestätigt | **vermutlich erledigt (Nebeneffekt), nicht mit letzter Sicherheit verifiziert** |
| `duplicate/cache.py` INV-01 | DEFER P2 | Seit v5 nur eine reine Docs-Pfad-Referenzänderung (`569f574`), keine funktionale Änderung | **weiterhin offen, P2** |
| `handlers/test_menu_handler.py` INV-01 (bis 900s, admin-only) | DEFER P2 | 5 unveränderte `subprocess.run()`-Aufrufe ohne `asyncio.to_thread()`/`run_in_executor()` bestätigt (diese Session hat nur `error_handler`-Wiring ergänzt, INV-01 selbst nicht angefasst) | **weiterhin offen, P2** |
| `download_executor.py::download_single_track()` Cancellation-Cleanup | DEFER P2 | Kein `except asyncio.CancelledError`-Handling in der Datei gefunden (verifiziert). DL-06 (seit v5 gefixt) deckt einen anderen Trigger ab (yt-dlp/FFmpeg-**Fehler**, nicht Task-**Cancellation**) | **weiterhin offen, P2 — unverändert, nicht durch DL-06 mitbehoben** |
| `statistics_calculator.py::export_stats_to_json()` nicht-atomarer Write | DEFER P3 | Datei seit v5 unverändert (kein Commit) | **weiterhin offen, P3** |
| Loudness-Schritt undokumentiert + Debug-Log-Rauschen | DEFER P3 | Pipeline-Schritt jetzt klar als „15b. Loudness-Normalisierung" beschriftet, INFO-Level-Log mit klarem Erfolg/Fehlschlag-Ergebnis (`enhanced_metadata_processor.py:821-854`), `utils/audio_enhancer.py` enthält nur 3 Log-Aufrufe insgesamt — kein Rauschen erkennbar. Vermutlich Nebeneffekt von PR #73/#74 (LUFS-Reprocessing-Tool, Cover-Korruptions-Fix) | **erledigt (Nebeneffekt), verifiziert** |
| `pylast.LastFMNetwork.__repr__()` latentes Secret-Leak-Risiko | DEFER P3 | Kein `__repr__`-Override, kein Scrubbing in `services/clients/lastfm_client.py` (verifiziert nach dem Logger-Refactor PR #75, der einen anderen Fokus hatte) | **weiterhin offen, P3 (latent, aktuell nirgends geloggt)** |
| `.info.json`-Reste in `import/downloads/` u. Ä. | unverändert seit v3/v4 | `download_artifact_cleanup.py` existiert bereits seit ARCH-005 (vor v5) und deckt einen Teilfall ab; v5 listete den Punkt trotzdem weiterhin als offen — seither keine weitere Änderung an dieser Datei | **weiterhin offen, P2/P3 (Teilabdeckung, nicht vollständig)** |

**Fazit:** 6 von 9 Punkten weiterhin offen (unverändert seit v5, aktiv re-bestätigt), 2 vermutlich als Nebeneffekt anderer Arbeit erledigt, 1 davon vollständig verifiziert (Loudness). Keiner davon P0/P1.

---

## 6. Bewusst akzeptierte Risiken / Entscheidungen (neu seit v5)

- **DUP-05** (Check-then-Register-Race ohne Lock bei parallelen Downloads) — im Download Pipeline Stability Phase 1 Plan trotz P1-Einstufung bewusst wie ein akzeptiertes Risiko behandelt: kein Datenverlust, das Ergebnis einer Race wird bereits durch die `renamed_due_to_conflict`-Kollisionsbehandlung sauber aufgefangen (nach dem DUP-01/DUP-02-Fix auch für Playlists). Ein Lock-basierter Fix würde Scope/Lifetime/Deadlock-Analyse erfordern, die über den Rahmen eines „kleinsten sinnvollen Fixes" hinausgeht.
- **DL-03/DL-05** (keine Fehlerklassifikation bei Download-/Metadata-Retries) — zweimal zurückgestellt (ARCH-004, Download Pipeline Stability Phase 1): würde eine echte Fehlerklassifikations-Logik erfordern (String-Matching auf yt-dlp-Fehlermeldungen), mehr als ein kleinster Fix — eigene künftige Design-Entscheidung nötig, in dieser Session nach Rücksprache bewusst nicht begonnen.
- **`mugge_statistik_handler.py`** ohne `error_handler`-Integration — dessen `except`-Blöcke editieren eine separat versendete Zwischennachricht (`msg.edit_text`), nicht die `callback_query`-Nachricht selbst. Mechanisches Verdrahten würde die falsche Nachricht editieren und die „läuft..."-Nachricht dauerhaft hängen lassen. Nutzer-Entscheidung: nicht verdrahten, keine UX-Regression in Kauf genommen.

---

## 7. Aktueller Architekturzustand

Unverändert gegenüber v5 in Bezug auf Layer-Grenzen und Grund-Orchestrierungsfluss.
Alle 21 ARCH-Phasen (ARCH-001 bis ARCH-021) sind HISTORICAL/abgeschlossen,
keine neue ARCH-Phase seit v5 begonnen. Neu hinzugekommen ist ausschließlich
fachliche/robustheitsbezogene Weiterentwicklung innerhalb bestehender
Grenzen (Duplicate Resolution Engine als eigenständiges `services/duplicate/`-
Submodul, EnhancedErrorHandler-Verdrahtung innerhalb `handlers/`).

---

## 8. Aktuelle Security-Baseline

Keine neuen Security-Findings in dieser Runde. Der in Abschnitt 5 erneut
bestätigte `pylast.LastFMNetwork.__repr__()`-Punkt bleibt latent (aktuell
nirgends geloggt, daher kein aktives Leck) — unverändert gegenüber v5.

---

## 9. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| `move_to_library()` TOCTOU | Same-File-Kollisionsfenster | DEFER, re-bestätigt | P2 |
| `duplicate/cache.py` INV-01 | Bewusst nicht async | DEFER, re-bestätigt | P2 |
| `handlers/test_menu_handler.py` | INV-01, bis 900s, admin-only | DEFER, re-bestätigt | P2 |
| `download_executor.py::download_single_track()` Cancellation-Cleanup | Verwaiste Teildatei bei Task-Cancellation | DEFER, re-bestätigt (nicht durch DL-06 mitbehoben) | P2 |
| `statistics_calculator.py::export_stats_to_json()` | Nicht-atomarer Write | DEFER, re-bestätigt | P3 |
| `pylast.LastFMNetwork.__repr__()` | Latentes Secret-Leak-Risiko | DEFER, re-bestätigt | P3 |
| `.info.json`-Reste in `import/downloads/` u. Ä. | Teilabdeckung durch `download_artifact_cleanup.py` | DEFER, re-bestätigt | P2/P3 |
| `tag_writer.py` fsync-Kommentar | Ursprünglich „veraltete Begründung" | vermutlich erledigt (Nebeneffekt, nicht mit letzter Sicherheit verifiziert) | — |
| Loudness-Schritt undokumentiert + Log-Rauschen | Kosmetisch | **erledigt, verifiziert** | — |
| DUP-05 | Check-then-Register-Race ohne Lock | bewusst akzeptiertes Risiko (unverändert) | P1 (akzeptiert) |
| DL-03/DL-05 | Keine Fehlerklassifikation bei Retries | zurückgestellt, eigene Design-Entscheidung nötig | P2 |
| `mugge_statistik_handler.py` | Kein `error_handler` (struktureller UX-Konflikt) | zurückgestellt, eigene Design-Entscheidung nötig | — |

---

## 10. Neue offene Risiken

Keine. Alle in dieser Runde geschlossenen Findings (DOC-01, Test-Isolation)
wurden mit Pre-Fix-Diskriminierung verifiziert; die volle Testsuite lief
nach jedem Fix und am Ende erneut grün. Die systematische Durchsicht der
28 seit v5 gemergten PRs ergab keinen neuen, bisher undokumentierten Fund
(keine unarchivierten „Nebenbefund"/„DEFER"-Marker in Produktionscode
gefunden, die nicht bereits im selben Commit behoben oder bereits vor v5
bekannt waren).

---

## 11. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1634 passed, 1 skipped, 2 warnings, 19 subtests passed in 118.42s
```

1123 (v5) + 511 = 1634 — Zuwachs vollständig durch die 28 gemergten PRs
seit v5 erklärt (neue Tests je Fix/Feature), keine unerklärte Differenz.
Der eine Skip ist umgebungsbedingt (`tests/test_resolve_duplicates.py:491`,
reale Badchieff-Testdaten nicht vorhanden) — unverändert seit der
Duplicate-Resolution-Arbeit, kein neuer Skip.

Kein einziger Schritt dieser Session hat einen vorher bestandenen Test zum
Fehlschlagen gebracht.

---

## 12. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach dem Post-Baseline-v5
> Health & Risk Audit: Re-Verifikation aller offenen Technical-Debt-Punkte,
> Durchsicht aller seit v5 gemergten PRs, sowie der in dieser Session
> gefundenen und behobenen Findings DOC-01 und Test-Isolation.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md` wird durch dieses Dokument
**abgelöst**, nicht ersetzt, als aktueller Referenzpunkt, und wurde nach
Archivierungs-Konvention bereits nach `docs/archive/` verschoben.

---

## 13. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (unverändert)
```

Dieser Audit hat den bestehenden Freeze nicht neu geöffnet — alle
Änderungen seit v5 waren eng umrissene Einzel-Fixes/Features nach bereits
etablierten Mustern, keine davon katastrophal (kein Crash, keine
Korruption, kein Datenverlust, kein Lockout). Der Freeze bleibt APPROVED.

---

## Baseline Frozen (2026-09-01)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v7.md`, nicht mehr hierher.
