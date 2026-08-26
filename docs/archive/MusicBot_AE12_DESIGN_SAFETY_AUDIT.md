# AE-12 — Forensic Deep Design & Safety Audit

Status: **Audit-Report. Kein Fix implementiert. Keine Tests geändert. Kein Freeze. Keine Baseline v4.**

---

## 1. Executive Verdict

```
AE-12 = CONFIRMED
```

`write_tags()` läuft nachweislich (nicht vermutet) auf dem Haupt-Event-Loop-Thread des Bots, ohne jeden `await`-Punkt, und blockiert für Dateien oberhalb von ca. 15-20 MB reproduzierbar den gesamten Bot für **die volle Wall-Time der Operation** (0 von 0 möglichen Heartbeat-Ticks bei jeder getesteten Größe 10-100 MB). Der zuvor vom Closure-Audit vermutete Root Cause ("`copy2()` ist der dominante Kostenfaktor") wurde bei der Nachprüfung **widerlegt und korrigiert**: tatsächlich dominiert `Path.replace()` die Kosten, nicht `shutil.copy2()` — beide Phasen sind aber gleichermaßen synchron und blockierend, sodass die Kernaussage (Event-Loop-Blockierung) bestehen bleibt, nur die interne Attribution ändert sich.

## 2. Repository State

**VERIFIED** vor Beginn des Audits:
```
HEAD: 9946cc8 (unveraendert)
git status --short: identisch zum Stand nach AE-11 (siehe vorheriger Report)
git diff -- services/metadata/tag_writer.py: identisch zum AE-11-Fix, keine
  weiteren Aenderungen seither
```
Keine Abweichung vom erwarteten Ausgangszustand.

## 3. Call-Graph Evidence

Repo-weite Suche (`grep -rn "write_tags(" `, `"TagWriter("`, `"\.write_tags\b"`), keine Einschränkung auf bekannte Dateien:

```
Instanziierung: services/metadata/enhanced_metadata_processor.py:136 (einzige)
Aufruf:         services/metadata/enhanced_metadata_processor.py:858 (einzige)
```

**Keine zweite, versteckte Call-Site.**

Vollständige Kette bis zum Telegram-Handler zurückverfolgt, jede Stufe direkt am Code verifiziert:

```
services/downloader/download_utils.py:701 / :838
    await call_process_single_track(...)          # kein to_thread
        ↓
services/downloader/metadata_result_translator.py:60
    await enhanced_metadata_processor.process_single_track(...)   # kein to_thread
        ↓
services/metadata/enhanced_metadata_processor.py:231 (async def process_single_track)
        ↓ Zeile 858
    self.tag_writer.write_tags(...)                # SYNCHRON, kein await, kein to_thread
```

**GATE bestanden:** Kein `to_thread()`/`run_in_executor()` an irgendeiner Stelle dieser Kette. `write_tags()` läuft nachweislich auf demselben Thread, der auch alle Telegram-Updates aller Nutzer verarbeitet.

## 4. AE-11 Change Impact — Korrigierte Attribution

Instrumentierte Messung (echte `TagWriter`, gepatchte `shutil.copy2`/`Path.replace` zur Phasenmessung, 5 Läufe je Größe, echte `ffmpeg`-MP3-Dateien, `/tmp` auf ext4-Root-Filesystem):

| Größe | Gesamt (median) | `copy2()` (median) | `mutagen` (median, errechnet) | `replace()` (median) |
|---|---|---|---|---|
| 3 MB | 6,3 ms | 1,8 ms | 3,1 ms | 1,1 ms |
| 5 MB | 7,2 ms | 2,5 ms | 3,3 ms | 1,4 ms |
| 10 MB | 14,5 ms | 5,2 ms | 4,9 ms | 3,1 ms |
| 20 MB | 103,0 ms | 10,4 ms | 7,3 ms | **86,5 ms** |
| 40 MB | 176,8 ms | 18,6 ms | 11,0 ms | **145,9 ms** |
| 60 MB | 324,1 ms | 27,7 ms | 15,7 ms | **275,7 ms** |
| 100 MB | 363,1 ms (max 1612,1 ms!) | 47,2 ms | 23,0 ms | **287,5 ms (max 1542,7 ms)** |

**Korrigierter Befund:** Ab ~20 MB dominiert **`Path.replace()`**, nicht `shutil.copy2()`, wie der vorherige Closure-Audit implizit annahm (dieser hatte die Phasen nicht einzeln gemessen). `Path.replace()` ruft intern `os.replace()`/`rename()` auf — algorithmisch ein O(1)-Metadaten-Vorgang auf ext4, unabhängig von der Dateigröße. Die beobachtete, mit der Dateigröße stark skalierende Kostensteigerung ist damit **nicht** durch die Rename-Operation selbst erklärbar, sondern durch **reale Disk-I/O-Kontention**: die unmittelbar vorangegangenen großen `write()`-Operationen (`copy2()` + mutagens interne Schreibvorgänge) erzeugen Dirty Pages, deren asynchrones Zurückschreiben durch den Kernel mit der nachfolgenden `replace()`-Operation um Warteschlangen-/I/O-Ressourcen konkurriert.

**Konsequenz für die Bewertung:** Die Blockierungsdauer ist **nicht** deterministisch/algorithmisch begrenzt, sondern **last-/kontentionsabhängig** — das erklärt auch die zwischen den beiden unabhängigen Messläufen dieser Session beobachtete erhebliche Varianz (Closure-Audit: 40 MB median 53,2 ms/max 226,2 ms; dieser Audit: 40 MB median 176,8 ms, 100 MB max 1612,1 ms). Das ist keine widersprüchliche Messung, sondern ein **Beleg für unbegrenzte Worst-Case-Varianz unter realer I/O-Last** — eine eher verschärfende als abschwächende Erkenntnis.

## 5. Performance Measurements

Siehe Tabelle in Abschnitt 4 (Gesamt-Spalte) für 3/5/10/20/40/60/100 MB, je 5 Läufe, Median/Min/Max erfasst. Rohdaten in `/tmp/musicbot_ae12_measure/` erzeugt und nach Gebrauch vollständig entfernt (`rm -rf`, verifiziert).

## 6. Event-Loop Evidence

Realer Async-Heartbeat, 20-ms-Intervall, **kein** `to_thread()` verwendet (Ziel: den bestehenden Fehler beweisen, nicht kaschieren), 3 Läufe je Größe, 10-100 MB:

| Größe | Wall-Time-Bereich (3 Läufe) | Erwartete Ticks (bei 20ms) | Tatsächliche Ticks | Max. Tick-Lücke |
|---|---|---|---|---|
| 10 MB | 11,1–19,9 ms | 0,6–1,0 | **0** | = Wall-Time |
| 20 MB | 22,5–72,4 ms | 1,1–3,6 | **0** | = Wall-Time |
| 40 MB | 40,0–153,7 ms | 2,0–7,7 | **0** | = Wall-Time |
| 60 MB | 181,6–320,3 ms | 9,1–16,0 | **0** | = Wall-Time |
| 100 MB | 358,4–991,5 ms | 17,9–49,6 | **0** | = Wall-Time |

**PROVEN, nicht nur gemessen:** bei **jedem einzelnen** der 15 Läufe (alle Größen) wurden **exakt null** Heartbeat-Ticks registriert — unabhängig von der absoluten Wall-Time. Das ist kein Grenzwertphänomen, sondern eine direkte Konsequenz der Code-Struktur: `write_tags()` enthält keinen einzigen `await`-Punkt, wodurch der Event-Loop in keinem Moment der Operation die Kontrolle zurückerhalten kann. Die maximale Tick-Lücke ist bei jeder Größe identisch mit der vollen Wall-Time der Operation.

**Objektive Schwelle** (vor dieser Messreihe bereits in dieser Session etabliert, nicht nachträglich gewählt): Sub-20-ms gilt als Nichtbefund (mehrfach in AE-10/AE-11-Audits angewendet). Regulär e Musik-Tracks (3-15 MB) bleiben mit 6,3-19,9 ms **knapp innerhalb bis an der Grenze** dieser Schwelle. Ab 20 MB (Podcast-Klasse) wird die Schwelle **konsistent und reproduzierbar** überschritten, bis in dieselbe Größenordnung wie der bereits als P1 eingestuften AE-10-Befund (261-690 ms) und darüber hinaus (max. 1612 ms bei 100 MB in Abschnitt 4).

## 7. Concurrency Analysis

### A. Shared Mutable State — GEPRÜFT, KEIN GEFUNDEN

`TagWriter.__init__` setzt ausschließlich `self.logger` (Python-`logging`, dokumentiert thread-safe) und `self.artist_normalizer` (read-only während `write_tags()`, keine mutierten Attribute beobachtet). **Kein** Klassenattribut, kein Cache, kein Zähler, kein Analogon zu AE-10s `matplotlib.pyplot`-Problem. `tmp_path` ist in jedem Aufruf eine rein lokale Variable.

### B. Concurrent Track Processing — VERIFIED

`Config.MAX_CONCURRENT_DOWNLOADS = 3` (`config.py:353`), durchgesetzt via `asyncio.Semaphore` in `klassen/download_handler.py` (bereits im Repository-HEAD vorhanden, nicht Teil dieser Session). **Bis zu 3 Tracks können gleichzeitig verarbeitet werden**, jeder mit eigenem `process_single_track()`-Aufruf auf demselben, gemeinsam genutzten (Singleton-)`EnhancedMetadataProcessor`/`TagWriter`.

### C. Same-File Collision — außerhalb des AE-12-Scopes, unverändert

Bereits im AE-11-Design-Audit dokumentiert: `move_to_library()`s Kollisionsvermeidungs-Schleife hat ein theoretisches TOCTOU-Fenster, das zwei parallele Verarbeitungen theoretisch auf denselben `library_path` lenken könnte. Das ist ein `filenamefixer.py`-Defekt, nicht `tag_writer.py`. **Durch einen AE-12-Fix weder verschärft noch behoben** — unverändertes Restrisiko.

### D. Different-File Safety — PROVEN (deterministischer Test, kein Timing)

5 echte, mittels `threading.Barrier` synchron gestartete OS-Threads, **eine gemeinsam genutzte `TagWriter`-Instanz** (exakt wie im echten Singleton-Prozessor), 5 unterschiedliche Zieldateien, je unterschiedliche Tags: **0 Fehler, 0 vertauschte Tags, 0 verwaiste Tmp-Dateien.** Im Gegensatz zu AE-10 (wo dieselbe Testmethodik nachweislich Kontamination durch `matplotlib.pyplot`s globalen Zustand aufdeckte) zeigt `TagWriter` **kein** analoges Verhalten — konsistent mit Punkt A (kein gemeinsamer mutierbarer Zustand).

### E. Temporary Filename Collision — GEPRÜFT, Restrisiko identifiziert, unverändert vorbestehend

`tmp_path = target_path.with_name(f".{target_path.name}.tmp_{int(time.time()*1000)}")` — Millisekunden-Auflösung. Für **unterschiedliche** `target_path`-Werte (der Normalfall, durch Punkt D bewiesen sicher) ist das irrelevant, da bereits der Basisname unterschiedlich ist. Für den in Punkt C beschriebenen (bereits out-of-scope) Fall, dass zwei Aufrufe zufällig denselben `target_path` erhalten, böte die Millisekunden-Auflösung **keinen zusätzlichen Schutz** gegen eine Kollision innerhalb derselben Millisekunde — dieses Risiko ist aber bereits durch Punkt C vollständig eingehegt (kein neues, AE-12-spezifisches Risiko).

## 8. FINDING-2 Interaction — Control-Flow-Beweis (kein Test geschrieben, wie gefordert)

```
await asyncio.to_thread(self.tag_writer.write_tags, ...)
    ↓ (Exception im Worker-Thread)
asyncio.to_thread() propagiert die Exception unveraendert an die
awaitende Coroutine (dokumentiertes, in dieser Session bereits mehrfach
verifiziertes Kernverhalten von asyncio.to_thread()/run_in_executor -
identischer Mechanismus wie bei den bereits abgeschlossenen Fixes fuer
FINDING-1/7, AE-10, backup_handler.py, enhanced_status_handler.py)
    ↓
enhanced_metadata_processor.py:878 except Exception as tag_err:
    (unveraendert - der Block reagiert auf JEDE Exception an dieser
    Stelle, unabhaengig davon, ob sie synchron oder ueber eine
    Thread-Grenze hinweg propagiert wurde)
    ↓
Cleanup + raise (unveraendert, siehe vorheriger Report Abschnitt 5)
```

**VERIFIED durch etabliertes, mehrfach bereits bewiesenes Muster + direkte Control-Flow-Analyse.** Kein neues Risiko — `except Exception:` in Python unterscheidet nicht zwischen synchron und über `to_thread()` propagierten Exceptions.

## 9. Atomicity Preservation

Ein `to_thread()`-Fix an der Call-Site verändert `write_tags()`s internen Ablauf **nicht** — die AE-11-Atomaritätsgarantie (`tmp_path`-Mutation, `target_path` unangetastet bis zum finalen `replace()`) bleibt vollständig erhalten, da sie unabhängig davon ist, auf welchem Thread die Funktion läuft. Keine der in Abschnitt 12 des Auftrags verbotenen Regressionen (direktes Öffnen von `target_path`, Exception-Swallowing, Cleanup-Entfernung) wäre durch die vorgeschlagene minimale Fix-Variante erforderlich oder nahegelegt.

## 10. Fix Options

| Option | Event-Loop-Safety | Race-Risiko | Mutagen-Thread-Safety | Dateipfad-Thread-Safety | Cache-State | Exception-Propagation | FINDING-2 | Locking nötig? | Performance | Komplexität | Scope | Regressionsrisiko |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A — `await asyncio.to_thread(write_tags, ...)`** | Sicher | Keines (Abschnitt 7D bewiesen) | Sicher (kein globaler mutagen-Zustand analog AE-10) | Sicher (lokale `tmp_path` pro Aufruf) | Unberührt (Cache-Store bleibt außerhalb, Abschnitt 8) | Sicher (etabliertes Muster) | Intakt | **Nein** | Event-Loop frei; reale Thread-Ausführung dauert gleich lang, läuft aber parallel zu anderen Coroutinen | Minimal (1 Zeile Call-Site) | Exakt auf `enhanced_metadata_processor.py:858` beschränkt | Sehr gering |
| B — gesamten `process_single_track()`-Schritt in Worker verschieben | Sicher | Höher (mehr Code im Worker, mehr Interaktion mit async-only APIs wie MusicBrainz-Client-Aufrufen weiter oben in derselben Methode) | N/A | N/A | Riskant (Cache-Handler-Aufrufe evtl. nicht threadsicher, ungeprüft) | Komplexer | Ungeprüft, höheres Risiko | Ungeklärt | Schlechter (viel mehr blockiert im Worker als nötig) | Hoch | Weit über AE-12 hinaus | Hoch — verboten laut Minimality Gate |
| C — nur den Dateisystem-/Mutagen-Teil isoliert in Worker verschieben | Identisch zu A, da `write_tags()` bereits exakt dieser isolierte Teil ist | Identisch zu A | Identisch zu A | Identisch zu A | Identisch zu A | Identisch zu A | Identisch zu A | Nein | Identisch zu A | Identisch zu A (deckungsgleich mit A) | Identisch zu A | Identisch zu A |
| D — eigener dedizierter Executor/Worker-Pool nur für `TagWriter` | Sicher | Keines | Sicher | Sicher | Unberührt | Sicher | Intakt | Nein | Marginal anders als A (eigener Pool statt Default-Pool) | Höher (neue Infrastruktur, Pool-Lifecycle-Management) | Über AE-12 hinaus (neue Abstraktion) | Mittel — verboten laut Minimality Gate (Abschnitt 14: „keine globalen Thread-Pools") |
| E — anderes bereits etabliertes Repository-Muster | — | — | — | — | — | — | — | — | — | — | — | Bereits durch A abgedeckt: A **ist** das etablierte Muster (identisch zu FINDING-1/7, `backup_handler.py`, `enhanced_status_handler.py`, AE-10) |

**Option C fällt strukturell mit Option A zusammen** — `write_tags()` ist bereits exakt der isolierte, rein synchrone, dateisystem-/mutagen-lastige Teil; es gibt in der aktuellen Architektur keinen kleineren sinnvollen Ausschnitt, den man separat verschieben könnte, ohne die Funktion selbst aufzuteilen (was eine unnötige Zusatzkomplexität wäre, siehe Minimality Gate).

## 11. Recommended Minimal Fix

**Nur Spezifikation — kein Code geändert in dieser Phase.**

Genau eine Änderung an genau einer Stelle:

`services/metadata/enhanced_metadata_processor.py:858`

```python
# vorher:
self.tag_writer.write_tags(
    target_path=library_path,
    ...
)

# nachher (Spezifikation, nicht implementiert):
await asyncio.to_thread(
    self.tag_writer.write_tags,
    target_path=library_path,
    ...
)
```

`import asyncio` ist in `enhanced_metadata_processor.py` bereits vorhanden (siehe FINDING-7-Fix im selben File, `await asyncio.to_thread(AudioEnhancer.normalize_loudness, ...)`, Zeile 818). **Kein neuer Import nötig.**

Kein Lock erforderlich (Abschnitt 7A/D). Keine Änderung an `tag_writer.py` selbst nötig — die AE-11-Atomaritätsgarantie ist bereits vollständig thread-kompatibel.

## 12. Race/Thread-Safety Assessment

Zusammenfassend: **sicher**, mit hoher Evidenzqualität (PROVEN via deterministischem Multi-Thread-Test, nicht nur argumentiert). Einziges Restrisiko (Same-File-Kollision, Abschnitt 7C/E) ist vollständig vorbestehend, unabhängig von einem AE-12-Fix, bereits an anderer Stelle dokumentiert und explizit außerhalb des Scopes dieses Audits.

## 13. Required Regression Tests (Spezifikation, nicht implementiert)

- **Test A (Event-Loop):** Heartbeat-Test analog zu `test_backup_handler_event_loop_blocking.py`/`test_mugge_statistik_handler_event_loop_blocking.py` — `write_tags()` durch einen kontrollierten synchronen `time.sleep()`-Stand-in ersetzt (`monkeypatch`), paralleler Heartbeat-Task muss während der simulierten Blockierung weiterhin Ticks erhalten.
- **Test B (Routing):** deterministischer Beweis, dass `asyncio.to_thread` mit `self.tag_writer.write_tags` als Zielfunktion aufgerufen wird (Patch + Aufzeichnung, Muster wie in allen bisherigen AE-10-Tests dieser Session).
- **Test C (Atomic Failure):** bereits durch die bestehenden AE-11-Tests (`test_tag_writer_atomic_replace.py`) abgedeckt — unverändert gültig, da `write_tags()` selbst nicht verändert wird.
- **Test D (Exception Propagation über Thread-Grenze):** `write_tags()` per `monkeypatch` zum Werfen bringen, `await asyncio.to_thread(...)`-Aufruf in einer Test-Coroutine, `pytest.raises(...)` bestätigt dieselbe Exception-Klasse/Nachricht wie im Worker geworfen.
- **Test E (FINDING-2 über Thread-Grenze):** Nachbau des Cleanup-Blocks (wie in `test_tag_writer_atomic_replace.py::TestHigherLevelFinding2CleanupIntegration`), diesmal mit dem Aufruf über `await asyncio.to_thread(...)` statt synchron — beweist, dass Abschnitt 8 dieses Reports auch tatsächlich (nicht nur konzeptionell) zutrifft.
- **Test F (Concurrent Safety):** deterministischer `threading.Barrier`-Test wie in Abschnitt 7D dieses Reports, als dauerhafter Regressionstest verankert (nicht nur einmaliges Audit-Experiment) — mehrere gleichzeitige `write_tags()`-Aufrufe auf unterschiedlichen Dateien über echte `to_thread()`-Dispatches, keine Kontamination.
- **Test G (Success Contract):** bereits durch bestehende `test_tag_writer.py`/`test_tag_writer_atomic_replace.py`-Tests abgedeckt, zusätzlich einmal explizit über den neuen `to_thread()`-Pfad wiederholt, um Contract-Erhalt (Tags, Cover, Rückgabewert `None`, keine Tmp-Reste) auch im neuen Aufrufkontext zu bestätigen.

## 14. Pre-Fix Discrimination Strategy (Spezifikation)

Für Test A: `git stash` auf die künftige Call-Site-Änderung, Heartbeat-Test muss gegen den aktuellen (AE-11-, aber nicht AE-12-gefixten) Code mit 0 Ticks fehlschlagen — exakt reproduzierbar mit den in Abschnitt 6 dieses Audits bereits gewonnenen Rohdaten (0 Ticks bei jeder Größe).
Für Test B/D/E/F: deterministisch per Konstruktion (Mock/Patch/Barrier), kein Timing als alleiniger Beweis — konsistent mit der in dieser gesamten Session etablierten Teststrategie.

## 15. Scope Integrity

```
Kein Produktionscode geaendert.
Keine Tests geaendert oder hinzugefuegt.
Keine Konfiguration geaendert.
AE-10 nicht angefasst.
P2/P3-Findings nicht angefasst.
docs/MusicBot_ARCHITECTURE_EVOLUTION.md nicht editiert.
Kein Commit, kein Push.
Alle temporaeren Audit-Artefakte (/tmp/musicbot_ae12_measure/) restlos entfernt.
```

Verifiziert: `git status --short` nach Abschluss identisch zum Stand vor Beginn dieses Audits (bis auf diese neue Report-Datei, wie durch den Auftrag gefordert). `pytest tests/ -q` weiterhin **1103 passed, 0 failed**.

## 16. Final AE-12 Verdict

```
CONFIRMED
```

- Call-Graph bestätigt: genau eine, ungewrappte, synchrone Call-Site auf dem Haupt-Event-Loop-Thread.
- Event-Loop tatsächlich betroffen: PROVEN, 0 von 0 möglichen Heartbeat-Ticks bei jeder getesteten Größe.
- Messung reproduzierbar: zwei unabhängige Messläufe (Closure-Audit + dieser Audit) zeigen dieselbe qualitative Aussage (deutliche, größenabhängige Verschlechterung), auch wenn die exakten Zahlen aufgrund realer I/O-Kontention variieren — diese Varianz selbst ist Teil des Befundes, keine Widerlegung.
- Impact meaningful: ab ~20 MB (Podcast-Klasse, real unterstützter Content-Typ) reproduzierbar in derselben Größenordnung wie der bereits als P1 eingestufte AE-10-Befund, mit Ausreißern bis 1,6 Sekunden unter realer Last.
- Fix-Design sicher bestimmbar: Option A (`asyncio.to_thread`) ist evidenzbasiert (nicht nur angenommen) sicher, ohne Lock, ohne neue Abstraktion, kleinstmöglicher Change-Scope.

**Korrektur gegenüber dem vorherigen Closure-Report:** die dortige Root-Cause-Zuschreibung an `shutil.copy2()` war unvollständig — tatsächlich dominiert `Path.replace()` unter realer I/O-Last. Diese Korrektur ändert die Schlussfolgerung (CONFIRMED, Freeze blockiert) nicht, sondern präzisiert sie.

## 17. Explicit Freeze Readiness Impact

```
ARCHITECTURE FREEZE = BLOCKED
```

gemäß Vorgabe (Abschnitt 19 des Auftrags): AE-12 = CONFIRMED erzwingt zwingend Freeze-Blockierung. Kein Fix in dieser Phase durchgeführt. Eine separate, eng gescopte **AE-12 CONTROLLED FIX PHASE** (Umfang: ausschließlich die in Abschnitt 11 spezifizierte Ein-Zeilen-Änderung plus die in Abschnitt 13 spezifizierten Tests) ist der nächste sinnvolle Schritt, vorbehaltlich expliziter Freigabe.
