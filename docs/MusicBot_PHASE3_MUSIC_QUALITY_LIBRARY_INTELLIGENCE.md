# MusicBot — Phase 3: Music Quality & Library Intelligence

**Status: CLOSED (2026-09-07)**

**Dokument-Charakter:** CURRENT — technischer Abschlussbericht der bereits
gemergten Phase-3-Arbeit. Kein Plan, keine Ankündigung. Alle hier
dokumentierten Ergebnisse sind auf `main` gemergt (PR #157–#163) und durch
eine volle Testsuite verifiziert.

Quellen für den aktuellen Gesamtstand: [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md)
(lebendes Register), [`README.md`](../README.md). Dieses Dokument ergänzt beide
um die vollständige technische Herleitung von Phase 3, ohne sie zu ersetzen.

---

## 1. Ausgangslage

### 1.1 Ursprüngliche Zielsetzung

Phase 1 (Library Health Scanner, read-only) und Phase 2 (Smart Library
Repair, 8 Executoren) waren zum Start von Phase 3 vollständig abgeschlossen
und production-proven (Health-Score 98.0, siehe
[`docs/LIBRARY_HEALTH.md`](LIBRARY_HEALTH.md) und
[`docs/LIBRARY_REPAIR.md`](LIBRARY_REPAIR.md)). Ein externer Ideenkatalog
(„Musicbot.md", außerhalb des Repositories) schlug eine Reihe von
Erweiterungen unter dem Leitgedanken „Music Library Intelligence" vor: eine
dauerhaft hochwertige, selbstprüfende und selbstreparierende Library.

### 1.2 Abgleich mit den „Musicbot.md"-Ideen

Vor jeglicher Implementierung wurde ein zweistufiger Research-Prozess
durchgeführt (Research → Research-Review), der alle 15 vorgeschlagenen
Ideen einzeln gegen den tatsächlichen Repository-Zustand klassifizierte:
`ALREADY IMPLEMENTED`, `PARTIALLY IMPLEMENTED`, `SUPERSEDED`, `STILL VALID`
oder `NOT RECOMMENDED`.

**Sinnvolle, tatsächlich umgesetzte Ideen** (siehe Abschnitt 2):
Library-Statistik-Ansicht, automatischer Navidrome-Scan nach Reparaturen,
Telegram-Zugang zum bestehenden Health-Scanner/Repair-Planner ("MusicBot
Doctor"), erweiterte Download-Historie, sowie eine erste, rein beobachtende
Stufe eines "Bad Download Detectors".

**Bewusst verworfen:**
- **Audio-Fingerprinting** für die Duplicate-Erkennung — bereits vorher im
  Anti-Overengineering-Gate von
  [`docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md`](MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md)
  §16 explizit als `NOT JUSTIFIED` eingestuft — kein neuer Bedarf durch
  Phase-3-Research belegt (die real gescannte Produktionslibrary zeigt keinen
  Duplicate-Fall, den ein Fingerprint zusätzlich lösen würde).
- **Symfonium-Optimierung** als eigener Punkt — keine eigenständige
  Funktion, sondern nur die Summe der ohnehin umgesetzten Bestandteile.

**Nach Schritt-0-Kalibrierung gegen die reale Produktionslibrary (388
Dateien) zurückgestellt, nicht implementiert:**
- **Audio Quality Analyzer** (Sample-Rate/Channels-Prüfung, ursprünglich
  als „P2.1" geplant): Kalibrierung zeigte 100 % identische Kanalzahl (2,
  Stereo) ohne jede Varianz sowie drei legitime, real vorkommende
  Sample-Raten (44100/48000/96000 Hz — 96 kHz ist dabei kein Ausreißer,
  sondern der vollständige Katalog eines einzelnen Artists). Kein
  belegbarer Bedarf für einen neuen Issue-Code.
- **Cover-Dateigrößen-Plausibilität** (ursprünglich als „P3.1" geplant):
  Bytes-pro-Pixel-Kalibrierung über 387 Cover zeigte keinen Fall, der nicht
  entweder bereits über die bestehende Auflösungsprüfung
  (`ARTWORK_LOW_RESOLUTION`) erfasst oder schlicht eine legitime, echte
  Datei mit schwächerer Kompression war.
- **Metadata Confidence Score**: als eigenständige, feld-gewichtete Metrik
  zurückgestellt — würde der bestehenden Phase-1-Entscheidung widersprechen,
  fehlende MusicBrainz-IDs/Lyrics als `INFO` (kein Score-Abzug) zu werten,
  und zwei unterschiedliche Zahlen für dieselbe Datei erzeugen. Siehe
  Abschnitt 4 (Deferred/Open).

---

## 2. Umgesetzte Bestandteile

### P1.1 — Library Statistics

**Ziel:** Eine Telegram-Ansicht der Library-*Zusammensetzung*
(Tracks/Albums/Artists/Genre-Verteilung/Health-Score), ergänzend zur
bereits bestehenden Play-History-Statistik.

**Technische Umsetzung:**
- `services/library_health/report.py::build_statistics()` — neues Feld
  `genre_distribution` (reine Aggregation über bereits vorhandene
  `FileHealth.genre`-Werte, wiederverwendet `file_analysis._split_genres()`
  — keine neue I/O, keine parallele Genre-Splitting-Logik).
- `handlers/mugge_statistik_handler.py::handle_library_overview()` +
  `_format_report_age()` — liest den zuletzt erzeugten
  `library_health_report.json`, zeigt Bestand + sichtbaren Scan-Zeitstempel
  (der Report ist eine Momentaufnahme, kein Live-Wert).
- `handlers/menu/rich_menu_system.py` — neuer Menüpunkt
  `stats_library_overview` ("📚 Library Übersicht") unter Statistiken.

**Tests:** `tests/test_library_health_report.py`, `tests/test_mugge_statistik_handler.py`,
`tests/test_rich_menu_system.py` (60 gezielte Tests, alle bestanden).

**Produktions-/Live-Verifikation:** über die reale Produktionslibrary
verifiziert (Genre-Distribution-Berechnung lief gegen den echten
388-Datei-Bestand ohne Fehler).

**Ergebnis / Status:** ✅ implementiert, gemergt (PR #157).

---

### P1.2 — Navidrome Scan Automation

**Ziel:** Nach einem erfolgreichen `library_repair.py --apply`-Lauf soll
automatisch ein Navidrome-Scan ausgelöst werden, ohne den Nutzer daran
erinnern zu müssen — aber nur, wenn tatsächlich etwas geändert wurde.

**Technische Umsetzung:**
- `scripts/library_repair.py` — neue Funktion `_trigger_navidrome_scan()`,
  aufgerufen wenn `tally.get("SUCCESS", 0) > 0` (wiederverwendet exakt den
  bereits vorhandenen, ungefilterten `tally = Counter(o.status for o in
  outcomes)`-Wert — **keine neue/eigene Definition** von „es gab eine
  Änderung"). Nutzt den bestehenden `utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan()`.
- Neues `--no-navidrome-scan`-Opt-out-Flag.
- Nie ausgelöst bei `--dry-run`. Ein fehlschlagender/nicht konfigurierter
  Scanversuch wird geloggt, ändert aber nie den Exit-Code des Repair-Laufs.

**Tests:** `tests/test_library_repair_navidrome_automation.py` (7 Tests,
inkl. echtem ffmpeg-Fixture-End-to-End-Pfad über `main()`).

**Ergebnis / Status:** ✅ implementiert, gemergt (PR #158).

---

### P1.3 — MusicBot Doctor

**Ziel:** Den bestehenden Health-Scanner und den `SAFE_AUTOMATIC`-Repair-Level
über einen Admin-only Telegram-Menüpunkt nutzbar machen, statt nur per CLI.

**Technische Umsetzung:**
- `services/library_repair/doctor_runner.py` — reine Subprozess-
  Orchestrierung (kein Telegram-Import, keine Fachlogik-Duplizierung),
  ruft `scripts/library_health_check.py` bzw. `scripts/library_repair.py
  --level SAFE_AUTOMATIC --apply` als eigenständige Subprozesse auf —
  exakt dasselbe Muster wie `services/metadata/reprocessing_runner.py`.
- `handlers/library_doctor_handler.py` — Admin-Gating im Handler **und**
  im Callback-Dispatcher (Defense-in-Depth, SEC-003-Muster), Hintergrund-Task
  (`asyncio.create_task`, analog `rich_menu_handler.py::_process_url()`)
  gegen Blockieren der gesamten Telegram-Application.
- `handlers/menu/rich_menu_system.py` / `handlers/menu/rich_menu_handler.py`
  — neuer Menüpunkt „🩺 MusicBot Doctor" unter „⚙️ Administration",
  eigenes `doctor:`-Callback-Präfix.
- Bewusst **nur** `SAFE_AUTOMATIC` über diesen Weg erreichbar — alle
  externen/destruktiven Level (`COVER`/`EXTERNAL_METADATA`/
  `METADATA_REPROCESSING`/`LOUDNESS`/`DUPLICATE`) bleiben CLI-only.
- **Nachtrag (PR #163, 2026-09-07):** Health-Scan-Ausgabe überarbeitet —
  Issue-Codes werden nicht mehr als rohe `SNAKE_CASE`-Codes angezeigt,
  sondern über `services/library_health/issues.py::REGISTRY` (Single
  Source of Truth) in Klartext übersetzt und nach Score-Relevanz getrennt
  (⚠️ wirkt sich auf den Score aus vs. ℹ️ nur Beobachtung/INFO, letzteres
  gemäß der bestehenden Phase-1-Konvention "Observation ≠ Defect").

**Tests:** `tests/test_library_doctor_handler.py` (25 Tests),
`tests/test_doctor_runner.py`, `tests/test_rich_menu_doctor.py`,
`tests/test_rich_menu_handler_activity_tracking.py` (insgesamt 343
thematische Tests inkl. Regressionsschutz).

**Ergebnis / Status:** ✅ implementiert, gemergt (PR #159, Lesbarkeits-Nachtrag PR #163).

---

### P2.2 — Import History (Metadata-Checkliste pro Download)

**Ziel:** Pro Download nachvollziehbar machen, welche Metadaten-Schritte
erfolgreich waren, statt nur Erfolg/Fehlschlag pauschal zu vermerken.

**Technische Umsetzung:**
- `services/downloader/download/models.py::DownloadResult` — neues Feld
  `mb_ids_present: bool` (nur das Vorhandensein, nicht die IDs selbst).
- `services/downloader/metadata_result_translator.py` — befüllt
  `mb_ids_present` aus `MetadataResult.mb_recording_id`/`mb_release_id`.
- `services/downloader/download_history.py::DownloadHistoryEntry` — fünf
  neue, **dreiwertige** `Optional[bool]`-Felder (`genre_ok`, `lyrics_ok`,
  `cover_ok`, `mb_ok`, `loudness_ok`): `True`/`False` bei aktiv
  durchlaufener Pipeline, `None` („keine Aussage möglich") ausschließlich
  bei den beiden Fehlerpfaden (`cancelled`/`failed`) ohne `DownloadResult`.
  **„Unbekannt" wird nie stillschweigend als `False` gespeichert.**
  Rückwärtskompatibel: ältere Verlaufseinträge ohne diese Felder laden als
  `None`.
- `klassen/download_handler.py` — befüllt die Checkliste an beiden
  Erfolgspfaden aus dem echten `DownloadResult.to_dict()`.

**Tests:** `tests/test_download_history_store.py`,
`tests/test_download_handler_history_recording.py` (37 Tests inkl.
Legacy-Kompatibilitäts- und Tri-State-Tests).

**Ergebnis / Status:** ✅ implementiert, gemergt (PR #160).

---

### P2.3 — Bad Download Detector, Stufe A (Observe-Only)

**Ziel:** Unerwartet kurze/verstümmelte Downloads erkennbar machen, ohne
in die Download-Pipeline einzugreifen (Stufe A = reine Beobachtung).

**Technische Umsetzung:**
- Neues, eigenständiges Modul `services/downloader/download_quality_guard.py`
  — prüft Dauer/Bitrate/Abweichung von der vom Quell-Anbieter gemeldeten
  Dauer der fertigen Rohdatei, direkt nach dem Download, **vor** der
  Metadaten-Pipeline (spart bei auffälligen Dateien unnötige externe
  Aufrufe).
- **Rein beobachtend:** nur Logging, kein Reject, keine
  Pipeline-Änderung — die Datei durchläuft in jedem Fall die volle
  Verarbeitung wie bisher.
- Bewusst **ohne** Import von `services/library_health`: der P0-Download-Pfad
  soll nicht an das read-only Diagnose-Paket der Library gekoppelt werden
  (unterschiedliche Fragen: „ist diese Library-Datei diagnostisch
  auffällig?" vs. „sollte dieser Download angenommen werden?"). Die
  verwendeten Schwellenwerte sind deshalb eigenständig benannt und
  explizit als unverbindlicher Ausgangspunkt für die Beobachtungsphase
  markiert — keine Vorwegnahme eines künftigen Stufe-B-Reject-Schwellenwerts.

**Tests:** `tests/test_download_quality_guard.py` (12 Tests, inkl. echtem
ffmpeg-Fixture-Happy-Path), Regressionstests `test_download_utils*.py`/
`test_download_executor*.py` (112 Tests, kein Pipeline-Verhalten geändert).

**Ergebnis / Status:** ✅ implementiert (Stufe A), gemergt (PR #161).
**Stufe B (echter Reject-Gate) ist explizit NICHT Teil dieser Phase** —
siehe Abschnitt 4.

---

## 3. Verwandte, bereits vorher abgeschlossene Arbeit: Loudness/ReplayGain (Phase 2)

> **Hinweis zur Einordnung:** Die folgenden Zahlen gehören technisch zu
> **Phase 2** (Smart Library Repair, Loudness-Executor,
> [`docs/LIBRARY_REPAIR.md`](LIBRARY_REPAIR.md) §6b), **nicht zu Phase 3**.
> Sie werden hier dokumentiert, weil sie thematisch zur „Music Quality"-Linie
> gehören und im Rahmen dieser Konsolidierung explizit angefragt wurden —
> nicht, um sie rückwirkend als Phase-3-Ergebnis umzudeklarieren. Phase 3
> selbst hat keinen eigenen Loudness-Bestandteil; der reale Repository-Stand
> kennt kein „Phase-3-P2.2-Loudness" — Phase 3s P2.2 ist Import History
> (Abschnitt 2).

**Loudness-Executor (`apply_replaygain`, verlustfreier ReplayGain-Tag),
Produktionslauf 2026-09-04, belegt in `docs/LIBRARY_REPAIR.md` §6b:**

- **133/133 SUCCESS**, 0 failed (`99 SET` + `34 CLEAR`)
- `LOUDNESS_OFF_TARGET 133 → 0`
- Health-Score danach: **98.0**
- **Bewusste Entfernung veralteter ReplayGain-Tags:** die 34 `CLEAR`-Fälle
  entfernen vorhandene RG-Atome an Dateien, die bereits auf Ziel-Lautheit
  liegen, aber einen abweichenden, veralteten Gain-Tag aus einer früheren
  Quelle trugen (real: 33 Badchieff- + 1 2Pac-Datei) — ein RG-fähiger
  Player hätte diese sonst fälschlich heruntergeregelt.
- **Kein unnötiges Audio-Re-Encoding:** Nutzer-Entscheidung 2026-09-04, nur
  einen verlustfreien `replaygain_track_gain`/`_peak`-Tag zu schreiben statt
  die Datei neu zu encodieren — Audio bleibt byte-identisch (verifiziert
  über Audio-Essenz-MD5 vor/nach jedem Schreibvorgang). Referenz-Ausgangslage:
  99/388 Dateien (26 %) off-target, 97 zu laut (Median +5,2 dB, bis +7,9 dB).

---

## 4. Tests

**Aktueller Teststand (Repository, nach Merge von PR #157–#163):**
2580 passed, 1 skipped (umgebungsbedingt, unverändert seit vorherigen
Ständen), 0 failed.

Dieser Stand ist **nicht** mit historischen Teststand-Angaben in anderen
Dokumenten zu vermischen — insbesondere nicht mit Baseline v8s eingefrorenem
Snapshot (1698 passed, Freeze 2026-09-02) oder dem Phase-2-Closure-Stand
(2499 passed, 2026-09-04). Für den jeweils aktuellen Stand siehe
[`README.md`](../README.md) bzw. [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md).

Testebenen pro Bestandteil siehe Abschnitt 2 (jeweils eigener Absatz
„Tests"). Volle Regressionssuite nach jedem einzelnen PR sowie erneut nach
Abschluss der gesamten Phase ausgeführt (CLAUDE.md §8.A) — 0 Regressionen
in jedem Lauf.

---

## 5. Deferred / Open

| Punkt | Status | Prio | Erklärung |
|---|---|---|---|
| **INV-01** (`services/duplicate/cache.py`) | **OPEN / DEFER** | **P2** | Synchrone Filesystem-Persistenz im Event-Loop-Thread. Nicht Teil von Phase 3, aus einem früheren Architektur-Audit ([`docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md`](audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md) §22, ursprünglich [`docs/archive/MusicBot_ENGINEERING_BASELINE_v8.md`](archive/MusicBot_ENGINEERING_BASELINE_v8.md) §6/8, bestätigt weiterhin offen in [`docs/MusicBot_ENGINEERING_BASELINE_v9.md`](MusicBot_ENGINEERING_BASELINE_v9.md) §6) — hier zur Vollständigkeit referenziert, da im Repository weiterhin unverändert offen. „Mass conversion to async" bleibt laut Architecture-Evolution-Gate verboten. |
| **P2.3 Stufe B** (Bad Download Detector Reject-Gate) | **OPEN / DEFER** | **P2** | Stufe A (siehe Abschnitt 2) ist rein beobachtend/produktiv. Ein echter Reject vor der Metadaten-Pipeline erfordert zuerst eine reale Beobachtungsperiode mit den jetzt aktiven Log-Hinweisen aus `download_quality_guard.py`, daraus abgeleitete (nicht von den Health-Scanner-Werten übernommene) Reject-Schwellen, und ein separates, explizites Nutzer-Go. Bewusst zurückgestellt, solange reale Beobachtungsdaten fehlen — noch nicht begonnen. |
| Metadata Confidence Score | **OPEN / DEFER** | — | Entscheidung aussstehend: bestehenden `file_/album_/artist_/library_health_score` (`services/library_health/scoring.py`) wiederverwenden (Option A, kein neuer Code) vs. separaten, feld-gewichteten Score bauen (Option B). Option B würde der Phase-1-Entscheidung widersprechen, fehlende MusicBrainz-IDs/Lyrics als `INFO` zu werten, und zwei unterschiedliche Zahlen für dieselbe Datei erzeugen. Keine Implementierung ohne diese Entscheidung. |
| Enhanced-Metadata-Processor Schritt 15b (LUFS-Ziel verifizieren) | **OPEN / DEFER** | **P3** | Aus der Phase-2-Loudness-Arbeit übernommener, weiterhin unveränderter Punkt (siehe Abschnitt 3) — reine Verifikation, kein akuter Fehlerverdacht, noch nicht begonnen. |

Vollständige, laufend gepflegte Liste inkl. aller Status-Details:
[`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md).

---

## 6. Abschluss

**Phase 3 — Music Quality & Library Intelligence: CLOSED (2026-09-07).**

Alle geplanten und tatsächlich gerechtfertigten Bestandteile (P1.1, P1.2,
P1.3, P2.2, P2.3 Stufe A) sind implementiert, getestet und auf `main`
gemergt (PR #157, #158, #159, #160, #161, #163). Zwei ursprünglich geplante
Bestandteile (P2.1 Audio Quality Analyzer, P3.1 Cover-Dateigrößen-
Plausibilität) wurden nach evidenzbasierter Kalibrierung gegen die reale
Produktionslibrary bewusst **nicht** umgesetzt (kein Bedarf belegt,
Abschnitt 1.2). Drei Punkte bleiben bewusst offen/zurückgestellt
(Abschnitt 5) — keiner davon blockiert den Abschluss dieser Phase, da alle
drei entweder außerhalb des Phase-3-Scopes liegen (INV-01, Schritt 15b)
oder explizit ein eigenes, künftiges Go voraussetzen (P2.3 Stufe B,
Confidence-Score-Entscheidung).

**Weiterführende Referenzen:**
- [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — aktueller, lebender Stand
  aller offenen/zurückgestellten Punkte
- [`README.md`](../README.md) — Nutzer-facing Feature-Übersicht,
  Projektstruktur, aktueller Teststand
- [`docs/LIBRARY_HEALTH.md`](LIBRARY_HEALTH.md) — Health-Scanner (Phase 1),
  Grundlage für P1.1/P1.3
- [`docs/LIBRARY_REPAIR.md`](LIBRARY_REPAIR.md) — Repair-Planner/-Executoren
  (Phase 2) inkl. §8 (Navidrome-Automation, P1.2) und §9 (MusicBot Doctor,
  P1.3), sowie §6b (Loudness, Abschnitt 3 dieses Dokuments)
