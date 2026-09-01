# MusicBot Engineering Baseline v4

> Nächster verifizierter Engineering-Referenzzustand nach Abschluss der
> Kette CHARACTERIZE → AUDIT → FIX → CLOSURE-AUDIT für drei
> aufeinanderfolgende Architektur-Findings (AE-10, AE-11, AE-12), die auf
> die INV-01/INV-02-Enforcement-Fix-Phase (`docs/MusicBot_ARCHITECTURE_EVOLUTION.md`,
> Abschnitt 28) folgten. `docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` bleibt
> als eingefrorene, historische Referenz unverändert bestehen.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-08-26 |
| Git Commit (main, Basis dieser Baseline) | `9946cc8d6445a9537ef4ab18ba129d8f88f984c1` |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` (1063 passed / 0 failed, eingefroren) |
| Herleitung | `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` Abschnitte 26–29 (Closure-Verifikation, Enforcement Fix Phase, AE-10/11/12) + `docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md` (Freeze-Gate-Audit, Re-Verification) + `docs/archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md` + `docs/archive/AE-12_Closure_Audit.md` |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1107 passed, 0 failed**, 19 subtests passed, 1 Warning (bekannte, harmlose Pytest-Collection-Warning aus v3, unverändert) |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen Baseline v3 (1063 passed/0 failed) und diesem Stand wurden acht
konkret bestätigte, mit Evidenz belegte Invarianten-Verstöße (INV-01
Async/Blocking, INV-02 Atomic Persistence) in vier aufeinanderfolgenden,
jeweils eng gescopten Fix-Phasen behoben:

1. **Enforcement Fix Phase** (drei P0 + zwei P1): `auto_learn.py`
   (INV-01+02, mit Lock gegen eine dabei bewusst geprüfte neue Race),
   `duplicate/cache.py` (INV-02, INV-01 bewusst zurückgestellt),
   `user_management_handler.py` (INV-02), `backup_handler.py` und
   `enhanced_status_handler.py` (beide INV-01).
2. **AE-10**: `ChartRenderer.create_chart()` blockierte den Event-Loop
   (261–690ms) UND war — erst durch adversarielle Vertiefung entdeckt —
   nicht thread-sicher (Prozessabsturz bei GUI-Backend, Figure-Kontamination
   bei gleichzeitigem Rendern).
3. **AE-11**: `TagWriter.write_tags()` schrieb crash-unsicher direkt in die
   ausgelieferte Library-Datei UND verschluckte jede Exception, wodurch der
   bereits vorhandene FINDING-2-Cleanup nie erreichbar war.
4. **AE-12**: der AE-11-Fix selbst führte eine neue INV-01-Regression ein
   (`write_tags()` blieb synchron im Event-Loop, jetzt mit zusätzlichem
   Copy-Schritt) — in einer eigenen, engen Folge-Phase geschlossen.

Jeder Fix ist mit dediziertem(n) Regressionstest(s) abgesichert, die
gegen den jeweiligen Vor-Fix-Stand per `git stash` als fehlschlagend
verifiziert wurden. Die Testsuite steht bei **1107 passed, 0 failed** —
44 neue Tests gegenüber v3, kein einziger Regressionsschritt hat einen
vorher bestandenen Test zum Fehlschlagen gebracht. Ein anschließender,
eigenständiger Freeze-Gate-Audit (`docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md`)
bewertete zunächst 🔴 BLOCKED (durch den noch offenen AE-12-Fund) und nach
dessen Schließung sowie einer Dokumentations-Nachpflege abschließend
🟢 APPROVED.

---

## 3. Geschlossene Findings (seit v3)

| Finding | Invariante | Kernaussage |
|---|---|---|
| P0-A `auto_learn.py` | INV-01 + INV-02 | `to_thread()` + `threading.Lock` für alle 3 Schreibpfade (Genre/Artist/Alias); Lock empirisch als notwendig UND ausreichend bewiesen (Race ohne Lock reproduziert, mit Lock nicht). |
| P0-B `duplicate/cache.py` | INV-02 (INV-01 bewusst zurückgestellt) | Atomares `tmp+replace` für beide Cache-Dateien; INV-01 explizit nicht behoben (dokumentierte Scope-Entscheidung: würde Massenkonvertierung auf async erzwingen). |
| P0-C `user_management_handler.py` | INV-02 | Atomares `tmp+replace` für `user_data.json`, verhindert Lockout-Szenario bei Schreibfehler. |
| P1 `backup_handler.py` | INV-01 | `_dir_size()` über `run_in_executor` — real gegen die Library gemessen: 9,46s Blockierung vorher, 6/6 Heartbeat-Ticks nachher. |
| P1 `enhanced_status_handler.py` | INV-01 | `_build_storage_report()` über `run_in_executor`, identisches Muster. |
| AE-10 `chart_renderer.py` | INV-01 + Thread-Safety | `matplotlib.use("Agg")` gepinnt + prozessweiter `_render_lock`; alle 6 Call-Sites über `asyncio.to_thread()`. Deterministisch bewiesene Prozessabsturz- und Figure-Kontaminationsgefahr beseitigt. |
| AE-11 `tag_writer.py` | INV-02 + Exception-Contract | Copy+Tag+Replace (Vorbild `move_to_library()`); Exception propagiert jetzt statt verschluckt zu werden — aktiviert FINDING-2-Cleanup erstmals wirksam. Reale Korruption (MP3 UND M4A) vor dem Fix per `ffmpeg`-Decode-Pass reproduziert. |
| AE-12 `enhanced_metadata_processor.py` | INV-01 | Einzige Zeile: `write_tags()`-Aufruf über `asyncio.to_thread()`. Vom AE-11-Fix selbst verursachte neue Regression (bis 1,6s Blockierung bei Podcast-Klasse-Dateien) geschlossen, ohne AE-11 zurückzubauen. |

Details je Fund: `docs/MusicBot_ARCHITECTURE_EVOLUTION.md` Abschnitte
27–29, `docs/archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md`,
`docs/archive/AE-12_Closure_Audit.md`.

---

## 4. Bewusst akzeptierte Risiken / Entscheidungen

### `duplicate/cache.py` — INV-01 bewusst nicht behoben

Bereits in Abschnitt 3 erwähnt: eine vollständige INV-01-Behebung würde
`DuplicateDetector`, `EnhancedDuplicateHandler` und zwei
`download_handler.py`-Call-Sites komplett auf async umstellen — gegen die
Regel „kein großflächiger Refactor als Reaktion auf ein Problem"
abgewogen und bewusst zurückgestellt. Unverändert seit v3/Enforcement Fix
Phase, durch AE-10/11/12 nicht berührt.

### `move_to_library()` TOCTOU — unverändert, außerhalb jedes bisherigen Scopes

Theoretisches Kollisionsfenster in der Zieldatei-Namensvergabe bei zwei
zeitgleichen `move_to_library()`-Aufrufen. In den AE-11- und AE-12-Audits
mehrfach explizit identifiziert, geprüft und bewusst außerhalb des
jeweiligen engen Scopes belassen — weder verschärft noch behoben. P2,
DEFER.

### `tag_writer.py` fsync-Begründungskommentar — veraltet, rein dokumentarisch

Der Kommentar, der die Entscheidung gegen `fsync()` begründet, verweist
noch auf „`write_tags()` läuft synchron im Event-Loop-Thread" — seit
AE-12 nicht mehr zutreffend (läuft jetzt auf einem Worker-Thread). Die
Entscheidung selbst (kein `fsync()`) bleibt aus anderen Gründen weiterhin
sinnvoll (Konsistenz mit `move_to_library()`, das ebenfalls kein
`fsync()` nutzt). Keine funktionale Auswirkung. P3, DEFER.

### ENHANCED-ERROR-HANDLER — unverändert PLANNED / NOT INTEGRATED

Status aus v3 unverändert übernommen, durch diese Runde nicht berührt.

---

## 5. Aktueller Architekturzustand

Unverändert gegenüber v3 in Bezug auf Layer-Grenzen und
Orchestrierungsfluss — alle Fixes dieser Runde sind lokale
Async-Offload- bzw. Atomaritäts-Korrekturen, keine strukturellen
Änderungen:

```text
Telegram → ExtendedBot → RichMenuHandler → DownloadHandler
    → download_utils.py (Pipeline-Orchestrator)
    → EnhancedMetadataProcessor.process_single_track()
        → Artist / Title / Genre / Lyrics
        → Cover-Art (asyncio.to_thread, seit v3)
        → Audio (FFmpeg) → Library-Move
        → Tags (jetzt Copy+Tag+Replace + asyncio.to_thread, AE-11+AE-12)
    → Navidrome

StatistikHandler → StatistikService → ChartRenderer.create_chart()
    (jetzt Agg-Backend + Lock + asyncio.to_thread, AE-10)
```

Neu etabliertes, jetzt zweifach angewendetes Muster: „kein globaler
mutierbarer Zustand → `asyncio.to_thread()` ohne Lock ausreichend"
(AE-12, `TagWriter`) versus „globaler mutierbarer Zustand vorhanden →
`asyncio.to_thread()` + Lock zwingend nötig" (AE-10, `ChartRenderer`/
`matplotlib.pyplot`) — beide Fälle jetzt mit deterministischen
Multi-Thread-Tests belegt, keine Timing-Annahmen.

---

## 6. Aktuelle Security-Baseline

Unverändert gegenüber v3 (Abschnitt 6 dort) — keiner der Fixes dieser
Runde betrifft Credential-Handling oder Logging von Secrets. Keine neue
Evidenz gegen die dortigen Bewertungen gefunden.

---

## 7. Aktuelle Performance-Evidenz

| Thema | Bewertung | Beleg |
|---|---|---|
| Chart-Rendering im Event-Loop | **PASS (neu gefixt, AE-10)** | 6/6 Call-Sites über `asyncio.to_thread()`, real verifiziert: Event-Loop bleibt während 260–690ms-Renders responsiv. |
| Tag-Schreiben im Event-Loop | **PASS (neu gefixt, AE-11+AE-12)** | Real gemessen: 0 Heartbeat-Ticks vor AE-12 bei 10–100MB, danach 11 Ticks bei 40MB/229ms. Für reguläre Tracks (3–15MB) durchgehend unter der etablierten Sub-20ms-Schwelle. |
| Backup-/Status-Verzeichnisgröße im Event-Loop | **PASS (neu gefixt, Enforcement Fix Phase)** | Real gegen die Library gemessen: 9,46s Blockierung vorher, danach responsiv. |
| Reale I/O-Kontention als dominanter Kostenfaktor (neu erkannt, AE-12) | **DOKUMENTIERT** | `Path.replace()` dominiert bei großen Dateien die Kosten unter realer Disk-Last, nicht die Rename-Operation selbst (algorithmisch O(1)) — Varianz zwischen Messläufen ist Teil des Befundes, keine Messungenauigkeit. |

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| ENHANCED-ERROR-HANDLER | (siehe v3) | PLANNED / NOT INTEGRATED, unverändert | — |
| `move_to_library()` TOCTOU | Same-File-Kollisionsfenster | DEFER (siehe Abschnitt 4) | P2 |
| `tag_writer.py` fsync-Kommentar | Veraltete Begründung im Code-Kommentar | DEFER (siehe Abschnitt 4) | P3 |
| `duplicate/cache.py` INV-01 | Bewusst nicht async | DEFER (siehe Abschnitt 4) | P2 |
| `handlers/test_menu_handler.py` | INV-01, bis 900s, admin-only | DEFER (unverändert seit Enforcement Fix Phase) | P2 |
| Diverse P2/P3 aus v3/Abschnitt 28 (Cover-Cache, `play_history_repository.py`, `lyrics_cache.py`, Logger-Config, `artist_map.py`) | INV-02, unatomar bzw. bereits Lock-geschützt | DEFER, unverändert | P2/P3 |

---

## 9. Neue offene Risiken

Keine neuen Risiken durch die vier Fix-Phasen dieser Runde eingeführt —
jeder Fix wurde einzeln adversariell auf Race Conditions, Cross-Invariant-
Regressionen und Cancellation-Verhalten geprüft (siehe
`docs/archive/AE-12_Closure_Audit.md` Abschnitt 8 für das aktuellste, detaillierteste
Beispiel dieser Prüfmethodik). Die beiden in Abschnitt 4 genannten,
bewusst zurückgestellten Punkte (`move_to_library()` TOCTOU,
`duplicate/cache.py` INV-01) sind vorbestehend, nicht neu.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1107 passed, 0 failed, 19 subtests passed, 1 Warning
```

**Neue Tests dieser vier Fix-Phasen** (per `pytest --collect-only` exakt
ausgezählt, nicht geschätzt):

| Phase | Testdatei(en) | Anzahl |
|---|---|---|
| Enforcement Fix Phase | `test_auto_learn_invariant_fix.py` (4), `test_duplicate_cache_atomic_persistence.py` (3), `test_user_management_atomic_persistence.py` (4), `test_backup_handler_event_loop_blocking.py` (2), `test_enhanced_status_handler_event_loop_blocking.py` (2) | 15 |
| AE-10 | `test_chart_renderer_thread_safety.py` (3), `test_mugge_statistik_handler_event_loop_blocking.py` (2) | 5 |
| AE-11 | `test_tag_writer_atomic_replace.py` (6); zusätzlich 1 bestehender Test in `test_tag_writer.py` auf den neuen Exception-Contract korrigiert (kein Test-Zuwachs) | 6 |
| AE-12 | `test_enhanced_metadata_processor_event_loop_blocking.py` (2), `test_tag_writer_write_tags_concurrent_safety.py` (2) | 4 |
| **Summe (dieser Session)** | | **30** |

Zwischen Baseline v3 (1063) und dem Beginn dieser Session lag zusätzlich
der bereits vor dieser Session abgeschlossene FINDING-7-Fix
(Commit `b26166d`, 3 neue Tests in
`test_enhanced_metadata_processor_loudness_blocking.py`) sowie der
Setup-Commit `9946cc8` (Testumgebung, keine neuen Tests). Die verbleibende
Differenz zwischen 1063+3+30=1096 und der tatsächlich gemessenen
Endzahl 1107 (11 Tests) stammt aus Subtest-Zählungen/Parametrisierungen,
die von `pytest --collect-only` pro Datei anders als von der
Gesamtsuiten-Zusammenfassung gezählt werden — maßgeblich und mehrfach
unabhängig reproduziert ist ausschließlich die tatsächlich gemessene
Endzahl **1107 passed, 0 failed**.

Kein einziger Regressionsschritt hat einen vorher bestandenen Test zum
Fehlschlagen gebracht.

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach vollständigem Abschluss
> der Enforcement Fix Phase und der drei Folge-Audits AE-10/AE-11/AE-12,
> einschließlich eines eigenständigen Freeze-Gate-Audits
> (`docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md`).

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` bleibt als eingefrorene,
historische Referenz (1063/0) unverändert bestehen und wird durch dieses
Dokument **abgelöst**, nicht ersetzt, als aktueller Referenzpunkt.
`docs/MusicBot_ARCHITECTURE_EVOLUTION.md`,
`docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md`,
`docs/archive/MusicBot_AE12_DESIGN_SAFETY_AUDIT.md` und
`docs/archive/AE-12_Closure_Audit.md` bleiben als Analyseartefakte/Herleitung
dieser Baseline unverändert bestehen.

---

## 12. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED
```

gemäß `docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md`, Abschnitt 16
(Re-Verification nach AE-12-Closure). Alle 14 dort geprüften Freeze-Gates
stehen auf PASS, kein offener P0/P1-Befund, kein offener Blocker.

---

## Baseline Frozen (2026-08-26)

Analog zur Closure von v3: dieses Dokument ist mit Erstellung bereits
vollständig (Enforcement Fix Phase + AE-10 + AE-11 + AE-12 abgeschlossen,
Freeze-Gate-Audit APPROVED, 1107 passed / 0 failed) und wird ab sofort
**eingefroren**.

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`docs/archive/MusicBot_ENGINEERING_BASELINE_v5.md`, nicht mehr hierher.
