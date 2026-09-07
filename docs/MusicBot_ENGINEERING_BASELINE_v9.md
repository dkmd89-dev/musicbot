# MusicBot Engineering Baseline v9

> Nächster verifizierter Engineering-Referenzzustand nach 61 PRs (#104–#164)
> seit dem v8-Freeze. Drei abgeschlossene Phasen dominieren diese Serie:
> Phase 1 „Library Health Scanner" (PR #145–#147), Phase 2 „Smart Library
> Repair" (PR #146, #148–#156, inkl. Loudness/ReplayGain-Produktionslauf
> 133/133 SUCCESS) und Phase 3 „Music Quality & Library Intelligence"
> (PR #157–#164, MusicBot Doctor Telegram-Integration, Library Statistics,
> Navidrome-Automation, Import-History-Checkliste, Bad Download Detector
> Stufe A). Daneben ein umfangreicher Findings-/Cleanup-Vorlauf (PR #104–
> #144: Genre-System/ARCH-022, Reprocessing-Tool-Härtung, Telegram-
> Download-Control-Center-Erweiterungen, Dead-Code-Audits). Von den 12 in
> v8 Abschnitt 8 gelisteten akzeptierten Risiken/Tech-Debt-Punkten wurden
> **10 seither geschlossen** — nur `INV-01` bleibt unverändert offen.
> `docs/MusicBot_ENGINEERING_BASELINE_v8.md` wird durch dieses Dokument
> abgelöst und liegt jetzt unter
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v8.md`.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-09-07 |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v8.md` — Freeze 2026-09-02 (1698 passed/0 failed, PR #102/HEAD `7ae014d…`), darin bereits ein Nachtrag vom 2026-09-03 mit Zwischenstand 1982 passed (PR #120, ARCH-022). Dieses Dokument (v9) löst **beides** vollständig ab — nicht nur die ARCH-022-Lücke. |
| Herleitung | 61 PRs (#104–#164), siehe Abschnitt 4. Hinweis: PR #104–#120 wurden in v8 nur als knapper Nachtrag erwähnt (ARCH-022), hier erstmals vollständig dokumentiert. |
| HEAD | `4a257802bf92940542ccd1440fe373b32f4df505` |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **2580 passed, 1 skipped, 0 failed**, 19 subtests passed |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen dem v8-Freeze (PR #102, 1698 passed) und heute (PR #164, 2580
passed) wuchs die Testsuite um **+882 Tests (+52 %)**, durchgehend 0
failed am jeweiligen Merge-Zeitpunkt. Die Serie gliedert sich in vier
klar abgrenzbare Blöcke:

**Block 1 — Findings-/Cleanup-Vorlauf (PR #104–#144, ~41 PRs).**
Fortsetzung der P0-Härtung aus v8: Security-Fix (BOT_TOKEN-Leak in
`run_test_bot.py`, P0), YTPARSE-01 (P0, YouTube-Parser), umfangreiche
Genre-System-Arbeit (ARCH-022: Auto-Learn-Namespace-Trennung, YAML→JSON-
Migration, Lock-in-Regel), Telegram Download-Control-Center (Live-Status,
Hard-Cancel, Download-Verlauf, Wartungsmodus), Reprocessing-Tool-Härtung
vor dessen Telegram-Integration (Singleton-Bleeding-Fix), sowie zwei
große Dead-Code-Audits (Handler-Methoden-Sweep: 22 bestätigt tote
Funktionen entfernt). Zwischenstand laut v8-Nachtrag nach PR #120: 1982
passed.

**Block 2 — Phase 1 „Library Health Scanner" (PR #145–#147).** Neuer,
vollständig read-only Library-Scanner (`services/library_health/`):
Discovery + Per-Datei-Analyse (Metadata/Artwork/Lyrics/Audio/Loudness-
Tag/Genre/Multi-Artist/Struktur) + Group-Analyse (Album-/Artist-
Konsistenz, Duplicate-Klassen) + deterministischer Health-Score.
Read-only technisch nachgewiesen (SHA256/mtime/size/Pfade + Import-Graph
frei von Schreib-Modulen). Finalaudit gegen die reale 388-Datei-
Produktionslibrary: Health-Score 97.9/EXCELLENT.

**Block 3 — Phase 2 „Smart Library Repair" (PR #146, #148–#156).** Aus
dem Health-Report abgeleitete Reparaturaktionen: Planner + 8 Executoren
(Tag-Fixes, Renames, Cover, Album-Cover-Vereinheitlichung, MusicBrainz-
IDs/ISRC, volle Neuverarbeitung, ReplayGain, Duplicate-Andockung). Alle
gegen die Produktions-Library gelaufen, u. a. **Loudness-Executor:
133/133 SUCCESS (99 SET + 34 CLEAR), `LOUDNESS_OFF_TARGET` 133→0,
Health-Score 98.0**, bewusste Entfernung veralteter ReplayGain-Tags
(34 CLEAR-Fälle) und kein unnötiges Audio-Re-Encoding (verlustfreier Tag
statt Re-Encode, Audio-Essenz-MD5-verifiziert byte-identisch). Closure-
Audit (PR #155) unabhängig verifiziert: Journal-/Backup-Abgleich exakt
(976 Journal-Zeilen, 407 Backups/2.2 GB).

**Block 4 — Phase 3 „Music Quality & Library Intelligence" (PR #157–#164).**
Nach Research + Research-Review gegen einen externen Ideenkatalog
(„Musicbot.md") umgesetzt: Library-Statistics-Ansicht (P1.1),
Navidrome-Scan-Automation nach `--apply` (P1.2), MusicBot-Doctor-
Telegram-Integration inkl. Lesbarkeits-Nachtrag (P1.3, PR #159+#163),
Import-History-Metadata-Checkliste (P2.2), Bad-Download-Detector Stufe A
(P2.3). Zwei ursprünglich geplante Kandidaten (Audio Quality Analyzer,
Cover-Dateigrößen-Plausibilität) nach Schritt-0-Kalibrierung gegen die
reale Library bewusst **nicht** umgesetzt (kein Bedarf belegt). Docs-
Konsolidierung (PR #162, #164) sorgte für durchgängige CURRENT/HISTORICAL/
BASELINE/LIVING-Statusklarheit in `docs/**`.

**Live gefundene und gefixte konkrete Bugs in dieser Serie** (nicht nur
Feature-Arbeit):
1. **BOT_TOKEN-Log-Leak** (P0, PR #106) — Secret-Sweep in `run_test_bot.py`.
2. **YTPARSE-01** (P0, PR #107) — YouTube-Parser-Bug.
3. **`.part`-Datei-Leaks bei Hard-Cancel/Task-Cancellation** (P2, PR
   #112/#113) — zwei separate Cancellation-Zeitfenster gefunden und
   gefixt; ein drittes, sehr schmales Zeitfenster (Hard-Cancel während
   FFmpeg-Postprocessing) bewusst als akzeptiertes Restrisiko
   dokumentiert (siehe Abschnitt 9).
4. **`duplicate_count`-Statistik-Asymmetrie** (P3, aus v8 übernommen) —
   konsistent gezählt (PR #124).
5. **`YoutubeDownloader.download_audio(None)`** — `AttributeError` durch
   sauberen Error-Dict-Guard ersetzt (PR #105).
6. **Genre-Tag-Filter-Bypass, Visualizer-Suffix, Kanalname-als-Artist-Alias**
   (PR #123) — drei unabhängige Metadata-Parsing-Bugs.
7. **Modul-Aktivierung schaltete Logger stumm** statt Log-Datei
   einzurichten (PR #140).
8. **Stale ReplayGain-Tags** wurden überschrieben statt entfernt (PR #152,
   Phase-2-Nachbesserung noch vor Produktionslauf).

Kein offenes P0/P1-Finding am Ende dieser Serie (siehe Abschnitt 9).

---

## 3. Geschlossene Findings (seit v8)

Vollständige Einzelbegründungen stehen in `docs/FINDINGS_INDEX.md`
(primäre Quelle) und den referenzierten PR-Titeln/Audit-Dokumenten. Diese
Tabelle fasst zusammen, was zwischen PR #104 und #164 geschlossen wurde
(60 Einträge in `FINDINGS_INDEX.md`, hier nach Themenblock gruppiert
statt einzeln — vollständige Liste dort):

| Themenblock | Anzahl geschlossener Findings | Beispiele |
|---|---|---|
| Security/Parser-P0 | 2 | BOT_TOKEN-Leak, YTPARSE-01 |
| Duplicate Detection | 5 | DUP-05, `duplicate_count`-Asymmetrie, embed/live-URL-Normalisierung, Playlist-Pro-Track-Duplikatprüfung, Miksu & Macloud-Bereinigung |
| Download-Pipeline/Cancellation | 6 | `.part`-Datei-Cleanup (2 Varianten), Bot-Blockade während Downloads, fehlender `^dl:`-Handler, Download-Verlauf |
| Metadata/TitleCleaner | 12 | Produzenten-Credits, Anführungszeichen, hängende Klammern, Marketing-Suffixe, MusicBrainz-Suchtitel |
| Genre-System | 4 | ARCH-022 (won't-fix, dokumentiert), Mehrheitsvotum-Stabilisierung, Override-Genre-Blockade |
| Reprocessing-Tool | 8 | Fehlerisolierung, Singleton-Bleeding, Titel-/Album-Konsistenz vor Telegram-Integration |
| Dead-Code/Cleanup | 4 | 14 Delegate-Methoden, MIG-04, MIG-06, Handler-Sweep (22 Funktionen) |
| **Aus v8 Abschnitt 8 übernommen und jetzt geschlossen** | **10 von 11** | siehe Abschnitt 6 — nur `INV-01` bleibt offen |
| Phase 1/2/3-Abschluss (Sammeleinträge) | 3 | Library Health Scanner (PR #145), Smart Library Repair (PR #146–#156), Music Quality & Library Intelligence (PR #157–#164) |

---

## 4. Seit v8 gemergte PRs (#104–#164)

| PR-Range | Themenblock | Test-Zwischenstand |
|---|---|---|
| #104–#118 | Findings-Fixes (P0–P3): Security, Duplicate, TitleCleaner, Reprocessing-Vorlauf | nicht einzeln rekonstruiert (siehe Hinweis unten) |
| #119–#120 | ARCH-022 (Genre-Auto-Learn-Namespace-Trennung, YAML→JSON) | **1982 passed** (bereits in v8-Nachtrag dokumentiert) |
| #121–#144 | Genre-Lock-in, Telegram-Erweiterungen (Wartungsmodus, Reprocessing-Menü, Download-Verlauf), Dead-Code-Sweep (24 Funktionen) | nicht einzeln rekonstruiert |
| #145–#147 | **Phase 1** — Library Health Scanner | **2326 passed** (Finalaudit-Suite laut PR #145-Dokumentation) |
| #146, #148–#156 | **Phase 2** — Smart Library Repair (8 Executoren, Loudness-Produktionslauf) | **2499 passed** (Closure-Audit PR #155) |
| #157–#161 | **Phase 3** — Music Quality & Library Intelligence | **2573 passed** |
| #162 | Docs: Phase-3-Sync FINDINGS_INDEX/README | 2573 passed (reine Doku) |
| #163 | Doctor-Health-Scan-Lesbarkeit | **2580 passed** |
| #164 | Docs: docs/**-Konsolidierung | 2580 passed (reine Doku) |

**Hinweis zur Genauigkeit:** Anders als in v8 (4 PRs, Test-Zuwachs pro PR
einzeln rekonstruierbar) ist bei 61 PRs eine PR-genaue Zwischenstand-
Rekonstruktion ohne Neuausführung jedes historischen Commits nicht mit
vertretbarem Aufwand möglich. Die oben genannten Zwischenstände sind
echte, an den jeweiligen PRs dokumentierte Messpunkte (aus
`docs/FINDINGS_INDEX.md`, `docs/LIBRARY_HEALTH.md`,
`docs/LIBRARY_REPAIR.md`, `docs/MusicBot_PHASE3_MUSIC_QUALITY_LIBRARY_INTELLIGENCE.md`),
keine Schätzung. Für #104–#118 und #121–#144 liegt kein dokumentierter
Zwischenstand vor — nur der End-zu-End-Zuwachs 1698→1982→2326 ist belegt.

---

## 5. Aktueller Architekturzustand

**Zwei neue Schichten seit v8**, beide nach dem etablierten Muster von
`services/duplicate/` aufgebaut:

- **`services/library_health/`** (Phase 1): read-only Scanner.
  Discovery → Tag-Reader → File-Analysis (reine Funktionen) →
  Group-Analysis → Scoring → Report. Wiederverwendet
  `services/duplicate/classification.py` für Duplicate-Erkennung
  (read-only) — horizontale Peer-Abhängigkeit innerhalb `services/`,
  keine Schichtgrenzen-Verletzung.
- **`services/library_repair/`** (Phase 2, erweitert in Phase 3): Planner
  + 8 Executoren, dockt für Duplicate-Auflösung als Subprozess an das
  bereits gehärtete `scripts/resolve_duplicates.py` an (kein neuer
  Lösch-Code). `services/duplicate/execution.py::execute_group()` bekam
  dafür einen additiven, optionalen `backup_fn`-DI-Parameter (Default
  `None` = Verhalten für bestehende Aufrufer unverändert). In Phase 3 um
  `doctor_runner.py` erweitert (reine Subprozess-Orchestrierung für die
  Telegram-Doctor-Integration, kein Telegram-Import).

**Ein neues Modul in einer bestehenden Schicht** (Phase 3, P2.3):
`services/downloader/download_quality_guard.py` — bewusst **ohne**
Import von `services/library_health`, um den P0-Downloadpfad nicht an
das read-only Library-Diagnose-Paket zu koppeln (unterschiedliche Fragen:
Datei-Diagnose vs. Download-Akzeptanz).

**Ein neuer Handler** (Phase 3, P1.3): `handlers/library_doctor_handler.py`
— Admin-Gating im Handler und im Callback-Dispatcher (Defense-in-Depth,
SEC-003-Muster wiederverwendet), Hintergrund-Task-Pattern von
`rich_menu_handler.py::_process_url()` übernommen.

Keine neue ARCH-Phase im Sinne von CLAUDE.md Abschnitt 3.A begonnen —
beide neuen Schichten entstanden aus Phase-1/2/3-Feature-Arbeit
(Characterize→Decide→Extract→Audit→Regression je Executor), nicht aus
einem eigenständigen Architektur-Migrationsauftrag.

---

## 6. Bewusst akzeptierte Risiken / Entscheidungen (bestätigt seit v8)

**Nur ein Punkt aus v8 Abschnitt 8 bleibt unverändert offen:**

- **`duplicate/cache.py` INV-01** — synchrone Filesystem-Persistenz im
  Event-Loop-Thread. Weiterhin DEFER, P2. „Mass conversion to async"
  bleibt laut Architecture-Evolution-Gate verboten (siehe
  `docs/MusicBot_ARCHITECTURE_EVOLUTION.md`, seit 2026-09-07 mit
  Kopf-Hinweis zur historischen Einordnung des dortigen Freeze-Status).

**Die übrigen 10 v8-Punkte wurden seither geschlossen** (siehe Abschnitt
3 für Details): `download_executor.py`-Cancellation-Cleanup,
`mugge_statistik_handler.py` ohne `error_handler` (won't-fix
finalisiert), `YoutubeDownloader.download_audio(None)`,
`FormatNotAvailableError`/`PermissionError` (Charakterisierung
bestätigt, kein Fix nötig), `FileProcessingError` (dito), 14 Delegate-
Methoden (alle entfernt), MIG-04 (bewusst nicht umgesetzt, geschlossen),
MIG-06 (Layer-Boundary-Test ergänzt), DUP-05, `duplicate_count`-
Asymmetrie, `/embed/`/`/live/`-URL-Normalisierung.

---

## 7. Aktuelle Security-Baseline

**Ein P0-Security-Fund seit v8, gefixt:** BOT_TOKEN-Log-Leak in
`run_test_bot.py` (PR #106) + begleitender repoweiter Secrets-Sweep.

**Neue sicherheitsrelevante Muster seit v8** (keine Findings, sondern
neue schützende Mechanismen):
- **Backup-vor-Delete** für Duplicate-Auflösung (`execute_group(backup_fn=…)`,
  Phase 2) — jede Datei wird vor `unlink()` gesichert, fehlgeschlagenes
  Backup verhindert das Löschen.
- **Admin-Gating für MusicBot Doctor** (Phase 3, P1.3) — eigener Check
  sowohl im Handler als auch im Callback-Dispatcher (SEC-003-Muster),
  da `callback_data` frei sendbar ist. `--apply`-Zweig nur für
  `SAFE_AUTOMATIC` erreichbar, keine externen/destruktiven Level über
  Telegram.
- Alle Repair-Executoren (Phase 2) verifizieren vor jedem Schreibvorgang
  Audio-Essenz-Byte-Identität und haben Per-Datei-Rollback bei
  Verifikationsfehler.

Keine offenen Security-Findings am Ende dieser Serie.

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| `duplicate/cache.py` INV-01 | Synchrone Filesystem-Persistenz im Event-Loop-Thread | DEFER (unverändert seit v8) | P2 |
| Hard-Cancel während FFmpeg-Postprocessing | Cancel-Check-Hook nur in `progress_hooks`, nicht in `postprocessor_hooks` verdrahtet | akzeptiertes Restrisiko (neu seit v8, PR #112/#113-Nebenfund) | P3 |
| `enhanced_metadata_processor.py` Schritt 15b | LUFS-Ziel der Download-Pipeline noch nicht verifiziert (reine Verifikation, kein Fehlerverdacht) | DEFER (neu seit v8, Phase-2-Folge-Analyse) | P3 |
| P2.3 Stufe B (Bad Download Detector Reject-Gate) | Braucht reale Beobachtungsperiode + explizites Go, bevor ein Reject-Gate gebaut wird | DEFER (neu seit v8, Phase 3) | P2 |
| Metadata Confidence Score | Entscheidung aussstehend: bestehenden Health-Score wiederverwenden vs. separaten Score bauen | DEFER (neu seit v8, Phase 3) | — |

Alle übrigen v8-Tech-Debt-Punkte wurden geschlossen (Abschnitt 6). Die
Liste ist damit **kürzer** als in v8 (5 vs. 12 Punkte), nicht durch
Weglassen, sondern durch echte Schließung plus vier neue, bewusst kleine
und klar begründete Nachfolgepunkte.

---

## 9. Neue offene Risiken

**Keine neuen P0/P1-Risiken** am Ende dieser Serie. Die vier neuen
Punkte in Abschnitt 8 sind P2/P3 bzw. unpriorisiert (Confidence-Score-
Designfrage) und jeweils bewusst mit einer klaren Vorbedingung für die
nächste Bearbeitung versehen (reale Beobachtungsdaten, explizites
Nutzer-Go bzw. reine Verifikation ohne Fehlerverdacht) — kein
„vergessenes" Risiko, sondern jeweils eine bewusste, begründete
Zurückstellung.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
2580 passed, 1 skipped, 0 failed, 19 subtests passed
Laufzeit: 186.57s (0:03:06)
```

1698 (v8-Freeze) → 1982 (v8-Nachtrag, ARCH-022) → 2580 (v9) = **+882
gesamt seit dem reinen Freeze, +598 seit dem v8-Nachtrag**. Der eine
Skip ist weiterhin umgebungsbedingt (`tests/test_resolve_duplicates.py`,
reale Testdaten nicht vorhanden) — unverändert seit v5–v8, kein neuer
Skip.

**Ein Testfehler wurde während dieses Baseline-Laufs gefunden und
behoben** (nicht Teil der Phase-3-Arbeit, sondern Datendrift durch
regulären Live-Betrieb): `tests/test_artist_overrides_orphan_cleanup.py`
hatte einen hartkodierten Snapshot von `mapping/artist_overrides.json`
(20 Keys), der durch einen echten Download („Christina Stürmer") auf 21
Keys anwuchs. Whitelist + erwarteter Count aktualisiert, analog zum
bereits bestehenden Präzedenzfall („Toobrokeforfiji"). Kein
Produktionscode betroffen.

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach Abschluss dreier
> aufeinander aufbauender Phasen (Library Health Scanner, Smart Library
> Repair, Music Quality & Library Intelligence) sowie einem umfangreichen
> Findings-/Cleanup-Vorlauf, der 10 von 11 in v8 als akzeptiert
> gelisteten Risiken schloss.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation (`docs/FINDINGS_INDEX.md` als lebendes Register)
> historische Dokumentation. `docs/archive/MusicBot_ENGINEERING_BASELINE_v8.md`
wird durch dieses Dokument **abgelöst**, nicht ersetzt, als aktuellen
Referenzpunkt, und wird nach Freigabe nach `docs/archive/` verschoben.

---

## 12. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (unverändert)
```

Diese Serie hat den bestehenden Freeze nicht neu geöffnet. Zwei neue
Schichten (`services/library_health/`, `services/library_repair/`)
entstanden, beide additiv und innerhalb der bestehenden Schichtgrenzen
(CLAUDE.md Abschnitt 4) — keine Schichtgrenzen-Verletzung, kein Zyklus,
kein Bruch mit dem `services/`-Muster. Kein Crash, keine Korruption,
kein Datenverlust in Produktion während dieser gesamten Serie
(Loudness-/Duplicate-Executoren liefen alle mit Backup-vor-Schreiben und
Byte-Identitäts-Verifikation gegen die reale Produktions-Library). Der
Freeze bleibt APPROVED.

---

## Baseline Frozen (2026-09-07)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v10.md`, nicht mehr hierher.
