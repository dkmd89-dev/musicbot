# MusicBot Engineering Baseline v7

> Nächster verifizierter Engineering-Referenzzustand nach einer
> zusammenhängenden Serie von 13 PRs (#85–#97), die gezielt die in
> Baseline v6 gelistete Technical Debt sowie die dort und in
> `MusicBot_ARCHITECTURE_EVOLUTION.md` als offen dokumentierten
> Evolution-Kandidaten (AE-04) abgearbeitet haben: Track-A-Cleanup (6
> P2/P3-Fixes), ein vollständiger read-only Services-Architecture-Audit,
> die DL-03/DL-05-Fehlerklassifikation im Download-Retry, ein
> Characterization-Audit von `process_single_track()` (Ergebnis: kein
> Refactor gerechtfertigt, zwei kleine Aufräum-Fixes umgesetzt), die
> Auflösung der einzigen verbliebenen echten Telegram-Kopplung in
> `services/`, sowie die Fachentscheidung zu `MUSICBRAINZ_RETRIES`
> (REMOVE). `docs/MusicBot_ENGINEERING_BASELINE_v6.md` wird durch dieses
> Dokument abgelöst und liegt jetzt unter
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md`.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-09-01 |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md` (1634 passed / 0 failed, eingefroren 2026-09-01, PR #84) |
| Herleitung | 13 PRs (#85–#97), siehe Abschnitt 4 |
| HEAD | `9b1ad838a2a118136988a036be4b981e2938b641` |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1673 passed, 1 skipped, 0 failed**, 19 subtests passed |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen dem v6-Freeze (PR #84) und heute wurden **13 PRs gemergt**
(#85–#97), die Testsuite wuchs von 1634 auf **1673 passed** (+39, +2,4 %),
durchgehend 0 failed. Anders als frühere Baseline-Zyklen (breite
PR-Durchsicht) war diese Serie eine **gezielte Abarbeitung bereits
bekannter, in v6/AE dokumentierter Findings** plus zwei eigenständige
read-only Audits (Services-Architecture, Telegram-Kopplung), die neue,
vorher unentdeckte Findings zutage förderten und in derselben Phase
gleich mitbehoben haben, wo risikoarm möglich.

**6 von 7 in v6 als offen gelisteten P2/P3-Findings wurden geschlossen**
(move_to_library() TOCTOU, TestMenuHandler INV-01, pylast-Secret-Leak,
tote Config-Werte inkl. tag_writer-Kommentar, CoverProcessor-Atomarität,
statistics_calculator-Atomarität). Der bereits vor v6 als AE-04
dokumentierte `MUSICBRAINZ_RETRIES`-Fund wurde nach vollständigem
Fachentscheidungs-Audit ebenfalls geschlossen (REMOVE). Das
`process_single_track()`-Characterization-Audit (Baseline-v6-Fund
MIG-05/SUSPICIOUS) kam zum begründeten Ergebnis „kein Refactor
gerechtfertigt" — **große Methode war kein Architekturproblem**, nur
zwei kleine, konkret belegte Aufräum-Fixes wurden umgesetzt. Der neu
entdeckte DL-03/DL-05-Fund (Fehlerklassifikation bei Download-/
Metadata-Retries, zweimal zuvor zurückgestellt) wurde mit der bereits
vorhandenen, aber ungenutzten Exception-Taxonomie gelöst — kleinerer
Aufwand als ursprünglich angenommen.

**3 Findings bleiben bewusst offen** (`duplicate/cache.py` INV-01,
`download_executor.py` Cancellation-Cleanup, `mugge_statistik_handler.py`
ohne `error_handler`) — alle drei sind Design-Entscheidungen, keine
kleinen Fixes, und wurden in dieser Serie erneut geprüft und bewusst
zurückgestellt (nicht übersehen). Ein neuer, kleiner Fund kam während
des Telegram-Kopplungs-Audits hinzu: `YoutubeDownloader.download_audio()`
wirft `AttributeError` statt eines sauberen Fehler-Dicts bei
`download_result=None` — kein akutes Risiko, dokumentiert, nicht
behoben (außerhalb des jeweiligen Auftrags-Scopes).

Kein P0/P1-Finding in dieser gesamten Serie.

---

## 3. Geschlossene Findings (seit v6)

| Finding | PR | Kernaussage |
|---|---|---|
| TestMenuHandler INV-01 | #85 | 5× `subprocess.run()` blockierten den Event-Loop (worst case bis 900s bei Performance-Tests) — alle 5 Aufrufstellen mit `asyncio.to_thread()` gewrappt. |
| `pylast.LastFMNetwork.__repr__()` Secret-Leak | #86 | Bettete `api_key`/`api_secret`/`session_key`/`password_hash` im Klartext ein; jedes abhängige `pylast`-Objekt erbte das Risiko. Klassenweiter Monkeypatch auf redigierte Fassung. |
| `move_to_library()` TOCTOU | #87 | Check-then-Act-Fenster bei der Zieldateinamensvergabe, prozessübergreifend ausnutzbar. Jetzt atomare Beanspruchung via `os.O_CREAT \| O_EXCL`. |
| Tote Config-Werte (AE-05) + `tag_writer.py`-Kommentar | #88 | `DOWNLOAD_TIMEOUT`/`YTDL_BASE_OPTIONS` entfernt (0 Aufrufer). `tag_writer.py`-fsync-Kommentar korrigiert (behauptete fälschlich noch synchrone Event-Loop-Ausführung, obwohl seit AE-12 bereits `asyncio.to_thread`-gewrappt). |
| `CoverProcessor._cache_best_cover()` Atomarität (AE-03) | #89 | Metadaten-JSON-Sidecar-Write jetzt atomar (write-tmp + `os.replace()`), analog zu `_cache_set()`. |
| `StatisticsCalculator.export_stats_to_json()` Atomarität | #90 | Export-Datei-Write jetzt atomar, identisches Muster. |
| **DL-03/DL-05** Fehlerklassifikation bei Download-/Metadata-Retries | #94 | Zweimal zuvor zurückgestellt („bräuchte echte Fehlerklassifikation"). Der Services-Audit (#92) fand: die nötige Exception-Taxonomie existierte bereits (`services/downloader/errors.py`, 6 Subtypen), wurde aber nirgends geworfen. Retry-Schleife behandelte `DownloadError`/`Exception` identisch. Jetzt: yt-dlp-Fehler werden an der Boundary klassifiziert (typsicher via `GeoRestrictedError`/`UnsupportedError`, sonst per belegtem Message-Marker), `MetadataError` für deterministische Pipeline-Fehler — beide lösen nur noch einen Versuch statt bis zu drei aus. |
| `EnhancedMetadataProcessor.process_single_track()` Characterization | #95 | Vollständiger Control-Flow-/Responsibility-/Dependency-/State-/Error-/Async-Audit der 908-Zeilen-Methode. Ergebnis: **kein Refactor gerechtfertigt** — jede fachliche Verantwortung ist bereits an 8 Kollaboratoren delegiert, verbleibender Code ist legitime Verdrahtungslogik. 2 kleine, belegte Fixes: redundanter `load_special_channels_merged()`-Aufruf (2× pro Track dieselbe YAML gelesen) dedupliziert, Debug-Log-Reste (`[DEBUG 9]` u. Ä.) entfernt. |
| Telegram-Kopplung `YoutubeDownloader` | #96 | Einzige noch bestehende echte Telegram-Kopplung in `services/`: `YoutubeDownloader.__init__` hielt das komplette Telegram-`Update`-Objekt für 2 benötigte Werte. Konstruktor nimmt jetzt `chat_id: int, update_id: int` entgegen — exakt das bereits in derselben Modulfamilie etablierte Muster (`enhanced_download_with_retry()`, `DownloadCoordinator`-Protocol). |
| `MUSICBRAINZ_RETRIES` (AE-04) | #97 | Fachentscheidungs-Audit: Wert seit dem allerersten getrackten Commit vorhanden, nie mit einer Implementierung verbunden, 0 Runtime-Referenzen, keine Retry-Logik existiert für MusicBrainz an irgendeiner Ebene. RECOMMENDATION REMOVE, vom Nutzer freigegeben und umgesetzt. |

Vollständige Analyse je Fund: siehe die referenzierten Audit-Dokumente
in `docs/audits/` (Abschnitt 4) sowie die jeweiligen PR-Beschreibungen.

---

## 4. Seit v6 gemergte PRs (#85–#97)

| PR | Datum (2026-09-01) | Titel | Audit-Dokument |
|---|---|---|---|
| #85 | 11:01 | TestMenuHandler INV-01 | — |
| #86 | 12:23 | pylast Secret-Leak | — |
| #87 | 13:11 | move_to_library() TOCTOU | — |
| #88 | 14:33 | Tote Config-Werte (AE-05) + tag_writer-Kommentar | — |
| #89 | 14:39 | CoverProcessor-Atomarität (AE-03) | — |
| #90 | 15:11 | statistics_calculator-Atomarität | — |
| #91 | 15:58 | Audit-Report: Technical Debt Cleanup (Track A) | `docs/audits/TECHNICAL_DEBT_CLEANUP_2026-09-01.md` |
| #92 | 16:41 | Services Architecture Audit (read-only) | `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md` |
| #93 | 16:42 | `artist_overrides.json` Auto-Learn-Sync (Mapping-Daten, kein Code) | — |
| #94 | 17:30 | DL-03/DL-05 Fehlerklassifikation | `docs/audits/DL_RETRY_CLASSIFICATION_2026-09-01.md` |
| #95 | 18:20 | `process_single_track()` Characterization + Minimal-Refactor | `docs/audits/ENHANCED_METADATA_PROCESSOR_PROCESS_SINGLE_TRACK_2026-09-01.md` |
| #96 | 20:03 | Telegram-Kopplung entkoppelt (`YoutubeDownloader`) | `docs/audits/SERVICES_TELEGRAM_COUPLING_2026-09-01.md` |
| #97 | 20:50 | `MUSICBRAINZ_RETRIES` entfernt (AE-04) | `docs/audits/MUSICBRAINZ_RETRIES_DECISION_AUDIT_2026-09-01.md` |

Testzuwachs je Phase: 1634 (v6) → 1652 (+18, Track A #85–#90) → 1663
(+11, DL-03/DL-05) → 1664 (+1, `process_single_track()`-Dedup-Test) →
1673 (+9, Telegram-Entkopplung) → 1673 (±0, `MUSICBRAINZ_RETRIES`,
keine Testanpassung nötig) = **1673**, exakt reproduziert.

---

## 5. Aktueller Architekturzustand

Unverändert gegenüber v6 in Bezug auf Layer-Grenzen und
Grund-Orchestrierungsfluss — **erstmals in dieser Session vollständig
verifiziert statt nur angenommen**: der Services-Architecture-Audit
(#92) bestätigte repoweit **0** Verletzungen der Schichtgrenze
`handlers/klassen → services → clients` (keine
`services→handlers`/`services→klassen`/`services→Telegram`-Importe),
sowie **0** verbliebene echte Telegram-Typ-Kopplung nach #96. Alle
zuvor bereits als async-sicher dokumentierten Boundary-Fixes (Cover,
Loudness, Tag-Writing, MusicBrainz-Client, LastFM-Client, Genius-Client,
Navidrome-API) wurden im selben Audit gegengeprüft und bestätigt.

Keine neue ARCH-Phase begonnen. Die Architektur selbst wurde in dieser
Serie **nicht umgebaut** — jede Änderung war eine gezielte, kleine
Korrektur innerhalb bestehender Grenzen (Fehlerklassifikation
verdrahtet, ein Konstruktor-Parameter geändert, tote Werte entfernt,
Redundanz dedupliziert). Konsistent mit dem in `MusicBot_ARCHITECTURE_EVOLUTION.md`
etablierten Anti-Overengineering-Gate: keiner der 13 PRs führte eine
neue Abstraktionsschicht, ein neues Framework oder eine neue generische
Pipeline ein.

---

## 6. Bewusst akzeptierte Risiken / Entscheidungen (bestätigt seit v6)

- **`services/duplicate/cache.py` INV-01** (synchrone Filesystem-Persistenz
  im Event-Loop-Thread) — im Services-Architecture-Audit (#92,
  Abschnitt 22) mit vollständiger Caller-/Kaskaden-Analyse neu belegt
  (mindestens 6 direkte Call-Sites in 3 Dateien) und 3 Lösungsoptionen
  (A: vollständig async, B: kontrolliertes Offloading an Call-Sites, C:
  Persistenz entkoppeln) bewertet, aber bewusst **nicht umgesetzt** — 
  „mass conversion of synchronous functions to async" bleibt laut
  `MusicBot_ARCHITECTURE_EVOLUTION.md` (P0-B) für diese Art Phase
  verboten. Eigene, künftige Architekturentscheidung nötig.
- **`download_executor.py::download_single_track()` Cancellation-Cleanup**
  — im DL-03/DL-05-Audit (#94) erneut bestätigt: laut DL-01-Audit
  bewusst unbehandelt gelassen (verwaiste Datei landet nur in
  `DOWNLOAD_DIR`, wird vom bereits laufenden 24h-Start-Sweep erfasst,
  kein akutes Risiko). In dieser Serie kein zweites Mal in Frage
  gestellt.
- **`mugge_statistik_handler.py`** ohne `error_handler`-Integration —
  unverändert seit v6, struktureller UX-Konflikt, bewusste
  Nutzer-Entscheidung (nicht Teil dieser Serie berührt).
- **`YoutubeDownloader.download_audio(None)` → `AttributeError`** (neuer
  Fund, #96) — beim Telegram-Kopplungs-Audit entdeckt, charakterisiert
  (eigener Test), aber bewusst nicht gefixt: `enhanced_download_with_retry()`
  liefert laut eigenem, im DL-03/DL-05-Audit dokumentierten Vertrag nie
  `None`, daher kein akutes Produktionsrisiko. Außerhalb des
  Telegram-Kopplungs-Scopes.
- **`FormatNotAvailableError`/`PermissionError` (Downloader-Fehlertaxonomie)**
  — seit #94 korrekt als „nicht retry-würdig" verdrahtet, werden aber
  aktuell von keiner Stelle im Code tatsächlich geworfen (Infrastruktur
  vorbereitet, ungenutzt). Kein Fix-Bedarf ohne konkreten Fehlerfluss.
- **`FileProcessingError`** — bewusst nicht in die Non-Retryable-Menge
  aufgenommen (#94): Klasse wird nirgends geworfen, tatsächliche
  Fehlerursachen nicht belegt, keine Klassifikation ohne Beleg.
- **15 „Delegate-Methoden (für Abwärtskompatibilität)"**
  (`EnhancedMetadataProcessor`, 0 Aufrufer repoweit) — im
  `process_single_track()`-Audit (#95) gefunden und explizit
  dokumentiert, aber laut CLAUDE.md Abschnitt 20 nicht ohne dedizierten
  Auftrag entfernt (Kompatibilitätsschicht).
- **`CoverProcessor`/`DownloadExecutor` außerhalb `services/clients/`**
  (MIG-04, #92) — rein struktureller Klarheitsgewinn ohne
  Funktionsänderung, P3, nicht umgesetzt.
- **Fehlende automatisierte Layer-Boundary-Tests** (MIG-06, #92) — der
  Services-Audit fand die Schichtgrenze aktuell vollständig sauber
  (Abschnitt 5), aber keinen Test, der eine künftige Verletzung
  automatisch verhindern würde. P3, nicht umgesetzt.
- **DUP-05** (Check-then-Register-Race ohne Lock) — unverändert seit v6,
  bewusst akzeptiertes Risiko, in dieser Serie nicht berührt.

---

## 7. Aktuelle Security-Baseline

Der in v6 als „latent (aktuell nirgends geloggt)" eingestufte
`pylast.LastFMNetwork.__repr__()`-Fund ist **geschlossen** (#86) —
damit keine offenen Security-Findings in dieser Baseline. Keine neuen
Security-Findings in dieser Serie entdeckt (Fokus lag auf
Architektur-/Retry-/Config-Fragen, nicht auf einer erneuten
Security-Durchsicht).

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| `duplicate/cache.py` INV-01 | Bewusst nicht async, 3 Optionen bewertet | DEFER, re-bestätigt mit vollständiger Analyse (#92) | P2 |
| `download_executor.py::download_single_track()` Cancellation-Cleanup | Verwaiste Teildatei bei Task-Cancellation | DEFER, re-bestätigt (#94) | P2 |
| `mugge_statistik_handler.py` | Kein `error_handler` (struktureller UX-Konflikt) | zurückgestellt, eigene Design-Entscheidung nötig, unverändert | — |
| `YoutubeDownloader.download_audio(None)` | `AttributeError` statt sauberem Fehler-Dict | neuer Fund (#96), charakterisiert, nicht gefixt, kein akutes Risiko | P3 |
| `FormatNotAvailableError`/`PermissionError` (Downloader) | Korrekt verdrahtet, aber ungenutzt | Infrastruktur bereit, kein Fehlerfluss belegt | — |
| `FileProcessingError` (Downloader) | Nicht klassifiziert | bewusst zurückgestellt mangels Beleg | — |
| 15 Delegate-Methoden (`EnhancedMetadataProcessor`) | 0 Aufrufer repoweit | dokumentierte Kompatibilitätsschicht, nicht entfernt ohne Auftrag | P3 |
| `CoverProcessor`/`DownloadExecutor` außerhalb `services/clients/` | Konventions-Inkonsistenz (MIG-04) | nicht umgesetzt, rein strukturell | P3 |
| Fehlende Layer-Boundary-Tests (MIG-06) | Boundary aktuell sauber, aber ungeschützt gegen Regression | nicht umgesetzt | P3 |
| DUP-05 | Check-then-Register-Race ohne Lock | bewusst akzeptiertes Risiko (unverändert) | P1 (akzeptiert) |

---

## 9. Neue offene Risiken

Ein neuer, kleiner Fund (`YoutubeDownloader.download_audio(None)` →
`AttributeError`, siehe Abschnitt 8) wurde während des
Telegram-Kopplungs-Audits (#96) entdeckt und dokumentiert. Kein
Produktionsrisiko, da der auslösende Zustand (`enhanced_download_with_retry()`
liefert `None`) laut eigenem Vertrag nie eintritt. Alle übrigen in
dieser Serie geschlossenen Findings wurden mit Pre-Fix-Diskriminierung
verifiziert; die volle Testsuite lief nach jedem funktional relevanten
Fix grün.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1673 passed, 1 skipped, 19 subtests passed
```

1634 (v6) + 39 = 1673 — Zuwachs vollständig durch die 13 gemergten PRs
seit v6 erklärt (siehe Abschnitt 4 für die Aufschlüsselung je Phase),
keine unerklärte Differenz. Der eine Skip ist weiterhin umgebungsbedingt
(`tests/test_resolve_duplicates.py`, reale Badchieff-Testdaten nicht
vorhanden) — unverändert seit v5/v6, kein neuer Skip.

Kein einziger Schritt dieser Serie hat einen vorher bestandenen Test
zum Fehlschlagen gebracht.

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach einer gezielten
> Abarbeitung der in Baseline v6 und `MusicBot_ARCHITECTURE_EVOLUTION.md`
> dokumentierten offenen P2/P3-Findings, ergänzt um zwei eigenständige
> read-only Audits (Services-Architecture, Telegram-Kopplung) und deren
> jeweils daraus resultierende, risikoarme Fixes.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md` wird durch dieses
Dokument **abgelöst**, nicht ersetzt, als aktueller Referenzpunkt, und
wurde nach Archivierungs-Konvention bereits nach `docs/archive/`
verschoben.

---

## 12. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (unverändert)
```

Diese Serie hat den bestehenden Freeze nicht neu geöffnet — alle 13 PRs
waren eng umrissene Einzel-Fixes/Audits nach bereits etablierten
Mustern, keiner davon katastrophal (kein Crash, keine Korruption, kein
Datenverlust, kein Lockout). Der Freeze bleibt APPROVED.

---

## Baseline Frozen (2026-09-01)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v8.md`, nicht mehr hierher.
