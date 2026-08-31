# MusicBot Engineering Baseline v3

> Nächster verifizierter Engineering-Referenzzustand nach Abschluss der
> Kette TRIAGE → DEEP AUDIT → FIX → REGRESSION → VERIFICATION
> (`docs/archive/MusicBot_POST_BASELINE_TRIAGE.md`). Kein reiner Finding-Report —
> siehe Abschnitt 1 für die Herleitung. `docs/archive/MusicBot_ENGINEERING_BASELINE_v2.md`
> bleibt als eingefrorene, historische Referenz unverändert bestehen.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-08-25 |
| Git Commit (main) | `c332e05a4df5423299f6bbda9abaeaabe46f726c` |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v2.md` (Closure-Stand 2026-08-25, 1057 passed / 0 failed, eingefroren — Abschnitt „Diese Datei ist mit der Closure abgeschlossen“) |
| Herleitung | `docs/archive/MusicBot_POST_BASELINE_TRIAGE.md` (Phase 1, sechs Dimensionen) → 3 Deep-Audit-Kandidaten (E3/HIGH) → alle 3 verifiziert, gefixt, regressionsgetestet → 1 weiterer Fund per Nutzerentscheidung als PLANNED/NOT INTEGRATED reklassifiziert (kein Fix) |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1063 passed, 0 failed**, 19 subtests passed, 1 Warning (Pytest-Collection-Warning, harmlos, siehe v2 §8), Laufzeit ~55–75s |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen Baseline v2 (Closure: 1057 passed/0 failed) und diesem Stand wurden
drei in der Post-Baseline-Triage identifizierte, mit konkreter Evidenz
belegte Risiken behoben — ein Event-Loop-Blocking-Bug im Cover-Art-Pfad
(betraf jeden einzelnen Track-Download), ein Klartext-Passwort-Leak in den
Navidrome-API-Logs (admin-einsehbar über den Telegram-Log-Viewer), und ein
Datenintegritätsrisiko, bei dem ein Tag-Schreibfehler nach erfolgreichem
Bibliotheks-Move eine dauerhaft inkonsistente Datei in der Library
hinterlassen konnte. Alle drei Fixes sind mit dedizierten Regressionstests
abgesichert, die jeweils per `git stash` gegen den Vor-Fix-Stand als
fehlschlagend verifiziert wurden — kein Fix beruht auf bloßer Annahme. Ein
vierter Triage-Fund (~450 Zeilen ungenutzter Code in
`handlers/enhanced_error_handler.py`) wurde nicht behoben, sondern nach
ausdrücklicher Nutzerentscheidung als bewusst zurückgehaltene,
für eine spätere RichMenu-Integration vorgesehene Komponente umklassifiziert
(PLANNED/NOT INTEGRATED, keine Technical Debt). Die Testsuite steht bei
**1063 passed, 0 failed** — es existiert aktuell kein einziger bekannter
Testfehlschlag im Repository.

---

## 3. Geschlossene Findings (seit v2)

| Finding | Dimension | Fix-Commit | Kernaussage |
|---|---|---|---|
| FINDING-3 (NAVIDROME-PASSWORD-LOG-LEAK) | Security | `988c1cf` | `navidrome_api.py::make_request()` scrubbt Credentials jetzt in allen drei Except-Zweigen; wirft `RuntimeError(safe_msg) from None` statt des Original-Exception-Objekts, damit weder nachgelagertes `str(e)`-Logging bei Aufrufern noch `exc_info=True`-Traceback-Chaining das Passwort re-leaken kann. |
| FINDING-1 (COVER-BLOCKING) | Performance/Robustness | `cc4535d` | `CoverProcessor.get_cover_art()`-Aufruf in `enhanced_metadata_processor.py` läuft jetzt über `asyncio.to_thread()`, exakt nach dem bereits etablierten yt-dlp-Muster (`download_executor.py::extract_info_async()`). Blockierte vorher den gesamten Bot für alle Telegram-Nutzer bei jedem Track. |
| FINDING-2 (PARTIAL-FAILURE-LIBRARY) | Robustness | `c332e05` | `write_tags()` ist jetzt lokal in try/except gekapselt; schlägt es NACH erfolgreichem `move_to_library()` fehl, wird die inkonsistente Datei gezielt aus der Library entfernt, bevor die Exception unverändert weitergereicht wird. |

Alle drei: eigener Regressionstest, per `git stash` gegen den Vor-Fix-Stand
als fehlschlagend verifiziert, volle Regressionssuite nach jedem Fix grün.
Details je Fund in `docs/archive/MusicBot_POST_BASELINE_TRIAGE.md`, Abschnitt 11
und den zugehörigen Nachträgen am Dateiende.

---

## 4. Bewusst akzeptierte Risiken / Entscheidungen

### ENHANCED-ERROR-HANDLER — Status: PLANNED / NOT INTEGRATED

**Fund (Triage, Abschnitt 9/M3):** `ErrorHandlerIntegration` (Klasse),
`create_complete_error_handling_system()`, `install_global_exception_handler()`
und `try_catch_decorator()` in `handlers/enhanced_error_handler.py` haben
0 Aufrufer außerhalb ihrer eigenen Definitionsdatei und 0 Testabdeckung
(repo-weit verifiziert).

**Entscheidung des Nutzers:** nicht löschen, nicht als Dead Code
klassifizieren, aktuell nicht implementieren/integrieren. Bewusst als
zukünftige Error-Handling-Komponente im Repository gehalten — spätere
Integration in das RichMenu-System als eigener,
künftiger Architektur-/Implementierungsschritt.

**Einordnung gegenüber der übrigen Datei:** `EnhancedErrorHandler`,
`ExceptionMonitor`, `DebugTracker` und `ErrorHandlerAdminInterface` bleiben
wie in der Triage verifiziert **aktiv und produktiv integriert**
(`create_enhanced_error_handler()`/`ErrorHandlerAdminInterface(...)` in
`bot.py` und `handlers/menu/rich_menu_handler.py`) — die Entscheidung
betrifft ausschließlich die vier oben genannten, unintegrierten Elemente.

**Keine Code-Änderung.** Dieser Zustand ist ab sofort der gültige,
begründete Referenzpunkt — nicht erneut als offenes Maintainability-Finding
zu werten, solange keine neue Evidenz (z. B. Bitrot, Bugs im ungetesteten
Code) auftritt.

---

## 5. Aktueller Architekturzustand

Unverändert gegenüber Baseline v2 (Abschnitt 4/12 dort) — keiner der drei
Fixes dieser Runde hat Layer-Grenzen, Verantwortlichkeiten oder den
Orchestrierungsfluss verändert:

```text
Telegram → ExtendedBot → RichMenuHandler → DownloadHandler
    → download_utils.py (realer Pipeline-Orchestrator, siehe ARCH-020)
    → EnhancedMetadataProcessor.process_single_track()
        → Artist / Title / Genre / Lyrics
        → Cover-Art (jetzt via asyncio.to_thread(), nicht mehr blockierend)
        → Audio (FFmpeg) → Library-Move → Tags (jetzt mit Fehler-Rollback)
    → Navidrome
```

Layer-Grenzen (0 Reverse-Dependencies, 0 Zyklen, AST-verifiziert in der
Triage) und die vier Blocking-I/O-freien externen Clients
(Genius/Last.fm/MusicBrainz/Navidrome, alle via `asyncio.to_thread`) sind
unverändert intakt — CoverProcessor reiht sich mit FINDING-1 jetzt in
dieselbe Kategorie ein.

---

## 6. Aktuelle Security-Baseline

Gegenüber v2 (Abschnitt 13 dort, dort noch keine Navidrome-spezifische
Detailprüfung) neu abgesichert:

| Thema | Bewertung | Beleg |
|---|---|---|
| Navidrome-Credential-Handling (Erfolgsfall) | PASS | Bereits seit SEC-001 (historisch) maskiert, unverändert |
| Navidrome-Credential-Handling (Fehlerfall: HTTP-Error/Connection-Error/generische Exception) | **PASS (neu gefixt)** | `_scrub_credentials()` + `RuntimeError(...) from None`, 3 dedizierte Tests in `tests/test_navidrome_api_logging.py` |
| Alle übrigen S1–S3-Punkte aus v2 (Path Traversal, Shell-Injection, URL-Allowlist, Secrets in Config) | PASS, unverändert | Keine neue Evidenz gegen diese Bewertungen in der Triage gefunden |

---

## 7. Aktuelle Performance-Evidenz

| Thema | Bewertung | Beleg |
|---|---|---|
| Event-Loop-Blocking in der Metadata-Pipeline | **PASS (neu gefixt)** | Alle bekannten synchronen Blocking-Aufrufe (yt-dlp, Genius, Last.fm, MusicBrainz, Navidrome, jetzt auch CoverProcessor) laufen über `asyncio.to_thread()`/`run_in_executor`. Deterministischer Nachweis für CoverProcessor in `tests/test_enhanced_metadata_processor_cover_blocking.py`. |
| Externe Request-Vervielfachung / wiederholte teure Arbeit | NO EVIDENCE OF MATERIAL RISK | Unverändert seit Triage (Abschnitt 7 dort) — MusicBrainz-Cache vorhanden, keine unnötigen Wiederholungen gefunden. |

Keine Benchmarks, keine erfundenen Werte — konsistent mit der in der Triage
etablierten Methodik.

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| ENHANCED-ERROR-HANDLER | Ungenutzte Integration-Helper-Klasse + 3 Factory-Funktionen in `enhanced_error_handler.py` | **PLANNED / NOT INTEGRATED** (kein Debt, siehe Abschnitt 4) | — |
| RETRY-COVERAGE, AUTOLEARN-002, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO, PODCAST-INDEX-KEY, LASTFM-COVER-DEAD | (siehe v2) | Alle bereits in v2/Nachträgen **CLOSED** | — |

Keine neuen offenen Technical-Debt-Punkte durch diese Runde entstanden.

---

## 9. Neue offene Risiken

Keine neuen Risiken durch die drei Fixes dieser Runde eingeführt (jeweils
minimal-invasiv, lokal begrenzt, mit Regressionstest abgesichert). Aus der
Triage weiterhin ohne Deep Audit (bewusst nicht vertieft, da E1/E2 mit
begrenztem Impact oder bereits mitigiert — siehe
`MusicBot_POST_BASELINE_TRIAGE.md` Abschnitt 6/12):

- Fehlende dedizierte Testabdeckung der Retry-/Backoff-Schleife in
  `enhanced_download_with_retry()` — bereits als RETRY-COVERAGE in v2
  geschlossen (Characterization-Test vorhanden), hier nur zur
  Vollständigkeit erwähnt, kein neuer Punkt.
- DUPLICATE-RACE-WINDOW (Triage R3, E2/MEDIUM): Check-then-Act-Fenster bei
  gleichzeitigen Downloads derselben URL, durch vorhandenen
  File-Conflict-Fallback in der Auswirkung auf verschwendete Arbeit
  begrenzt (keine dauerhafte Dateiduplizierung). Nicht behoben, da als
  MEDIUM/begrenzter Impact eingestuft — bewusst nicht Teil dieser
  Fix-Runde.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1063 passed, 0 failed, 19 subtests passed, 1 Warning
```

Entwicklung seit Baseline v2 (Closure-Stand):

| Stand | passed | failed |
|---|---|---|
| v2 Closure | 1057 | 0 |
| + FINDING-3-Fix (3 neue Tests) | 1060 | 0 |
| + FINDING-1-Fix (2 neue Tests) | 1062 | 0 |
| + FINDING-2-Fix (1 neuer Test) | **1063** | **0** |

Kein einziger Regressionsschritt hat einen vorher bestandenen Test zum
Fehlschlagen gebracht — jede Erhöhung der `passed`-Zahl entspricht exakt
den neu hinzugefügten Regressionstests.

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach vollständigem Abschluss der
> Post-Baseline-Triage (Phase 1) und aller daraus resultierenden Deep Audits.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v2.md` bleibt als eingefrorene,
historische Referenz (Closure-Stand 1057/0) unverändert bestehen und wird
durch dieses Dokument **abgelöst**, nicht ersetzt, als aktueller
Referenzpunkt. `docs/archive/MusicBot_POST_BASELINE_TRIAGE.md` bleibt als
Analyseartefakt/Herleitung dieser Baseline ebenfalls unverändert bestehen.

---

## Baseline Frozen (2026-08-25)

Analog zur Closure von v2: dieses Dokument ist mit Erstellung bereits
vollständig (alle drei Deep-Audit-Findings der Post-Baseline-Triage gefixt,
ENHANCED-ERROR-HANDLER bewusst als PLANNED/NOT INTEGRATED eingeordnet,
1063 passed / 0 failed) und wird ab sofort **eingefroren**.

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v4.md`, nicht mehr hierher — exakt dasselbe
Prinzip, mit dem v2 nach ihrer Closure abgelöst wurde.
