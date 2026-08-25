# MusicBot Post-Baseline Engineering Triage

## 1. Scope

| Feld | Wert |
|---|---|
| Repository | `dkmd89-dev/musicbot` |
| HEAD Commit | `33fae211ca8af3d981ef16da98dd022be48a86a3` (main) |
| Audit-Datum | 2026-08-25 |
| Baseline-Referenz | `docs/MusicBot_ENGINEERING_BASELINE_v2.md` (eingefroren, Closure-Stand: 1057 passed / 0 failed) |
| Aktueller Teststand (verifiziert) | 1057 passed, 0 failed, 19 subtests passed, 75.6s Laufzeit — bestätigt via `python3 -m pytest tests/ -q` |
| Explizit ausgeschlossen | Titel-Parsing-Bug (CLOSED), HTTP-Request-Logging (CLOSED), AUTOLEARN-001/002, RETRY-COVERAGE, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO, PODCAST-INDEX-KEY, LASTFM-COVER-DEAD (alle CLOSED), Spotify (REMOVED, kein offenes Finding) |

Diese Triage ist **keine Fix-Phase**. Es wurden keine Produktionscode-, Test- oder Mapping-Änderungen vorgenommen (siehe Abschnitt „Change Discipline" am Ende).

---

## 2. Methodology

Jede geprüfte Auffälligkeit wird nach zwei unabhängigen Achsen klassifiziert:

**Evidence:** E0 (keine Auffälligkeit) · E1 (Observation, kein nachweisbares Risiko) · E2 (plausibles Risiko mit konkreter Code-Evidence, Impact nicht vollständig bewiesen) · E3 (demonstrierter, nachvollziehbarer Codepfad)

**Risk:** LOW · MEDIUM · HIGH · CRITICAL

Nur E2/E3 rechtfertigen einen Deep Audit. Vor jedem Finding wurde die False-Positive-Kontrolle aus Abschnitt 15 des Auftrags angewandt (Erreichbarkeit, tatsächliche Nutzung, vorhandener Schutz, vorhandener Test, historisch/bereits behoben, reine Stilfrage).

Alle Aussagen basieren auf direkter Code-Lektüre, `grep`/AST-Analyse und — wo möglich — Reproduktion (z. B. exakte Nachstellung eines Exception-String-Formats). Es wurden keine Werte erfunden oder Benchmarks simuliert.

---

## 3. Executive Summary

Der Kernpfad (Layer-Grenzen, zirkuläre Imports, Client-seitiges Blocking-I/O für Genius/Last.fm/MusicBrainz/Navidrome, Shell-Injection-Vektoren, Path-Traversal) ist überwiegend sauber und teils bereits vorbildlich abgesichert (durchgängig `asyncio.to_thread` in allen vier externen Clients). Drei konkrete, gut belegte Risiken wurden jedoch identifiziert, die noch nicht Teil von Baseline v2 waren: (1) `CoverProcessor.get_cover_art()` blockiert den gesamten asyncio-Event-Loop für die gesamte Bot-Instanz bei **jedem** Track-Download — bis zu mehreren Sequential-HTTP-Timeouts à 8s; (2) ein Metadaten-Schreibfehler NACH dem Bibliotheks-Move hinterlässt eine unvollständig getaggte Datei permanent in der Library, während der Download als fehlgeschlagen gemeldet wird — der vorhandene Cleanup-Mechanismus deckt diesen Fall nachweislich nicht ab; (3) das Navidrome-API-Passwort leckt im Klartext in die Logdatei (und damit in den Telegram-Log-Viewer für Admins), sobald ein HTTP-Fehler auftritt — trotz vorhandener, korrekter Maskierung im Erfolgsfall. Ein vierter, geringerer Fund betrifft ~400 Zeilen nachweislich toten Codes in der größten Datei des Repositories. Kein Finding wurde in den Bereichen Architektur-Layering, zirkuläre Imports oder klassische Shell-/Path-Traversal-Angriffsflächen erhoben.

---

## 4. Dimension Matrix

| Dimension | Evidence | Risk | Deep Audit | Priority |
|---|---|---|---|---|
| Architecture | E1 | LOW | NO | — |
| Robustness | E3 | HIGH | YES | P1 |
| Performance | E3 | HIGH | YES | P1 |
| Security | E3 | HIGH | YES | P1 |
| Maintainability | E3 | LOW–MEDIUM | NO (dokumentiert, kein Deep Audit gerechtfertigt) | P3 (optional) |
| Features / Product | E1 | LOW | NO | — |

Anmerkung: Robustness, Performance und Security enthalten je eines der drei Top-Findings (Abschnitt 11) — sie werden dort gebündelt behandelt, da Finding 1 (Cover-Blocking) gleichzeitig Robustness- und Performance-relevant ist.

---

## 5. Architecture Triage

### A1 — Layer Boundaries

**Prüfung:** Reverse-Dependency-Scan (`services/`, `klassen/`, `utils/` → `handlers/`), Telegram-Objekt-Leckage in `services/`/`utils/`, AST-basierter Zyklen-Scan über alle 92 Produktionsmodule.

**Evidence:**
- 0 Treffer für `services/`/`klassen/`/`utils/` → `handlers/`-Importe.
- 0 Treffer für `services/clients/` → `services/metadata|duplicate|downloader`-Importe (Clients bleiben reine Transport-Adapter).
- 0 Treffer für `utils/` → `services/`|`klassen/`-Importe.
- 0 direkte Import-Zyklen (AST-Scan, 92 Module).
- `klassen/download_handler.py` importiert `telegram.Update`/`telegram.error.TelegramError`/`telegram.ext.ContextTypes` — einziger Treffer für Telegram-Leckage außerhalb `handlers/`. `klassen/` ist jedoch nicht Teil der in CLAUDE.md §4 explizit geregelten `services/`-Schicht, sondern die dokumentierte Application-Boundary zwischen `RichMenuHandler` und der YouTube-Pipeline (empfängt `Update` direkt vom Dispatcher, versendet Status-/Report-Nachrichten selbst — siehe ARCH-007/P-2, `_send_report_message()`). `services/downloader/` selbst ist nachweislich frei von Telegram-Importen.

**Ergebnis:** E1/OBSERVATION — keine Verletzung der tatsächlich etablierten Grenzen. Die einzige Telegram-Kopplung außerhalb `handlers/` liegt in `klassen/`, das laut Architekturdiagramm (CLAUDE.md §4) und ARCH-007 bewusst als dünne, Telegram-empfangende Orchestrierungsschicht positioniert ist — kein neuer Fund.

### A2 — Responsibility Concentration

**Prüfung:** Größte Module (`handlers/enhanced_error_handler.py`, 2506 Zeilen) auf tatsächliche Verantwortungsvermischung + Kopplung + Auswirkung untersucht (nicht nur Dateigröße).

**Evidence:** 5 Klassen in einer Datei (`ExceptionMonitor`, `DebugTracker`, `EnhancedErrorHandler`, `ErrorHandlerIntegration`, `ErrorHandlerAdminInterface`) plus 4 modulweite Factory-/Decorator-Funktionen. `EnhancedErrorHandler` instanziiert `ExceptionMonitor`/`DebugTracker` direkt (nicht injiziert) und ruft beide durchgängig auf (>15 Aufrufstellen) — echte, enge Kopplung nachweisbar. Konkrete Auswirkung: siehe Finding DEAD-CODE-ERRHANDLER unten (Abschnitt 9, Maintainability) — zwei der fünf Klassen plus alle Modulfunktionen sind nachweislich unerreichbar.

**Ergebnis:** E2 für die Kopplung selbst, aber die einzige *konkrete* nachweisbare Auswirkung ist Maintainability-bezogen (totes Gewicht, nicht Fehleranfälligkeit des aktiven Codes) — siehe Abschnitt 9. Kein eigenständiger Architecture-Deep-Audit gerechtfertigt.

### A3 — Hidden Coupling

**Prüfung:** `SingletonMixin`-Nutzung (`utils/singleton.py`) repo-weit.

**Evidence:** 4 Subklassen: `EnhancedMetadataProcessor`, `EnhancedDownloadProcessor` (`download_utils.py`), `ArtistNormalizer`/`ArtistConfig` (`artist_map.py`), `GenreMapper` (`genre_map.py`), `FilenameFixerTool` (`filenamefixer.py`). Klassenweiter `_instances`-Dict, „erster Konstruktor-Aufruf gewinnt" — nachfolgende `__init__`-Aufrufe mit anderen Argumenten werden stillschweigend ignoriert. Kein Config-Reload-Pfad im Repository gefunden (`Config` wird pro Prozess einmalig aus `.env` gelesen, keine Laufzeit-Änderung) — das Risiko ist in Produktion strukturell nicht auslösbar. In Tests bereits bekannt und über `tests/conftest.py::reset_singletons` (autouse-Fixture) explizit mitigiert — das Vorhandensein dieser Fixture selbst ist Beleg dafür, dass das Muster real zu Testverschmutzung geführt hat.

**Ergebnis:** E1/OBSERVATION — reales, aber in Produktion nicht erreichbares Muster (kein Reload-Pfad), in Tests bereits mitigiert. Kein neues Finding.

---

## 6. Robustness Triage

### R1 — External Failure Handling

**Prüfung:** Timeout-/Exception-Handling in allen vier externen Clients (`genius_client.py`, `lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py`) sowie `cover_processor.py`.

**Evidence (positiv):** Alle vier Clients wrappen ihre blockierenden Bibliotheksaufrufe (`requests`, `pylast`, `musicbrainzngs`) konsistent in `asyncio.to_thread()` — inkl. expliziter Code-Kommentare, die das bewusst begründen. `MusicBrainzClient` nutzt zusätzlich `async_timeout.timeout(Config.MUSICBRAINZ_TIMEOUT)`. `NavidromeAPI` hat einen konfigurierbaren `NAVIDROME_REQUEST_TIMEOUT`. `GeniusClient` setzt `timeout=10` auf direkten `requests`-Aufrufen.

**Evidence (Finding — siehe FINDING-1 in Abschnitt 11):** `CoverProcessor.get_cover_art()` ist eine reine `def` (nicht `async def`), die pro Track sequenziell bis zu 6 Quellen abfragt (Cover Art Archive, Fanart Album, Apple Music, Deezer, Fanart Artist, 4× YouTube-Varianten), jede über denselben `_get()`-Helper mit `timeout=8`. Sie wird **direkt, unverpackt** aus `EnhancedMetadataProcessor.process_single_track()` (`async def`) aufgerufen — kein `asyncio.to_thread`/`run_in_executor`. `process_single_track()` läuft ohne Executor-Wrapping auf dem Haupt-Event-Loop (Aufrufkette: `download_utils.py::_process_single_download/_process_track_metadata` → `await call_process_single_track()` → `await enhanced_metadata_processor.process_single_track()`).

**Ergebnis:** E3/DEMONSTRATED — reproduzierbarer Codepfad. **HIGH.**

### R2 — Partial Failure

**Prüfung:** Reihenfolge Datei-Verschiebung vs. Tag-Schreiben in `process_single_track()`, sowie das vorhandene Cleanup (`cleanup_single_download_artifact`, ARCH-005 Strategie C).

**Evidence (siehe FINDING-2 in Abschnitt 11):** `filename_fixer.move_to_library()` (Schritt 16, Zeile 828) läuft VOR `tag_writer.write_tags()` (Schritt 17, Zeile 841), ohne lokalen try/except. Schlägt `write_tags()` fehl, greift der äußere `except Exception` (Zeile 993) und ruft `cleanup_single_download_artifact(original_path, ...)` auf — dessen eigener Docstring bestätigt: „No-op, wenn ... `original_path` nicht (mehr) existiert" — nach `move_to_library()` ist das immer der Fall (`original_path.exists()` == False, da physisch verschoben). Ergebnis: Datei bleibt am finalen Library-Pfad mit unvollständigen/rohen Tags liegen, `MetadataResult(success=False, ...)` wird zurückgegeben, Nutzer erhält eine „Download fehlgeschlagen"-Meldung trotz existierender, von Navidrome scannbarer Datei.

**Ergebnis:** E3/DEMONSTRATED — der Codekommentar selbst grenzt den No-Op-Fall exakt so ab, wie er hier eintritt. **HIGH** (Datenintegrität der Library, P0-Bereich laut CLAUDE.md §5/§15).

### R3 — Concurrency

**Prüfung:** Check-then-Act-Muster in der URL-Duplikat-Prüfung (`DuplicateDetector.check_for_duplicates()` vs. `register_download()`) unter `MAX_CONCURRENT_DOWNLOADS`-Semaphore (mehrere parallele Downloads möglich).

**Evidence:** `check_for_duplicates()` läuft früh (Schritt 2, vor dem eigentlichen Download); `register_download()` erst nach vollständigem Erfolg. Zwei zeitgleiche Anfragen derselben URL (z. B. durch versehentliches Doppel-Senden) können beide die Prüfung passieren, bevor die erste registriert ist — beide durchlaufen die vollständige Download-/Metadaten-Pipeline redundant. **Vorhandene Teil-Mitigation gefunden:** `move_to_library()` erkennt Datei-Namenskollisionen und liefert `renamed_due_to_conflict=True`; `handle_youtube_links()` löscht die redundante Datei dann aktiv und meldet sie als `"file_conflict"`-Duplikat (Zeilen 609–630). Der Race verursacht damit **keine dauerhafte Datei-Duplizierung**, sondern nachweisbar nur verschwendete Arbeit (redundanter Download, redundante externe API-Aufrufe) im Rennfenster.

**Ergebnis:** E2/PLAUSIBLE RISK, durch vorhandenen Fallback in der Auswirkung begrenzt. **MEDIUM.** Kein Top-3-Kandidat (siehe Abschnitt 11), aber dokumentiert.

---

## 7. Performance Triage

Keine Benchmarks, keine erfundenen Werte.

### P1 — External Request Multiplication

**Evidence:** `MusicBrainzClient` cacht Suchergebnisse in einem Modul-Dict (`_musicbrainz_result_cache`) innerhalb `cached_musicbrainz_search()`. Kein Hinweis auf unnötige Wiederholungsanfragen in Genius-/Last.fm-Pfaden gefunden (jeweils ein Aufruf pro Track).

**Ergebnis:** E0 — **NO EVIDENCE OF MATERIAL PERFORMANCE RISK** für P1.

### P2 — Repeated Expensive Work

**Evidence:** Keine wiederholte teure Arbeit innerhalb eines einzelnen Track-Workflows identifiziert; die Metadaten-Pipeline durchläuft ihre Schritte einmalig pro Track.

**Ergebnis:** E0 — **NO EVIDENCE OF MATERIAL PERFORMANCE RISK** für P2.

### P3 — Blocking / Serialization

**Evidence:** Identisch zu R1 — `CoverProcessor.get_cover_art()` führt bis zu 6 sequenzielle (nicht parallele — `ThreadPoolExecutor`/`as_completed` sind in `cover_processor.py` importiert, aber nachweislich **nirgends verwendet**, reine `for`-Schleife) blockierende HTTP-Aufrufe à `timeout=8` direkt im Event-Loop aus. Worst Case (kein Early-Exit-Treffer): bis zu ~48s Event-Loop-Blockierung für die gesamte Bot-Instanz, für **jeden einzelnen Track**.

**Ergebnis:** E3/DEMONSTRATED. **HIGH.** (= FINDING-1, siehe Abschnitt 11)

---

## 8. Security Triage

### S1 — Secrets Exposure

**Prüfung:** `.env`/`config.py`-Properties, Logging-Aufrufe, Exception-Handling in allen Clients, Debug-/Admin-Pfade (Telegram-Log-Viewer).

**Evidence (siehe FINDING-3 in Abschnitt 11):** `navidrome_api.py::make_request()` maskiert `u`/`p` korrekt für die INFO-Log-Zeile (`Config.mask_sensitive()`). In den `except HTTPError`/`except Exception`-Zweigen wird jedoch das rohe Exception-Objekt geloggt (`f"...{http_err}..."`/`log_handler_error(err, ...)`). `requests.Response.raise_for_status()` formatiert Fehlermeldungen nachweislich als `"{status} ... for url: {response.url}"`, und `response.url` enthält die vollständigen Query-Parameter inkl. `p=<Klartext-Passwort>` (reproduziert, siehe Abschnitt 11). Diese Logs landen über `EnhancedRotatingFileHandler` in `logs/` und sind über `handlers/enhanced_logger_menu_handler.py` (`show_log_file_detail()`) für Telegram-Admins direkt einsehbar.

**Weitere geprüfte Bereiche ohne Befund:** `GENIUS_ACCESS_TOKEN` wird als Bibliotheksparameter an `lyricsgenius` übergeben, nicht als URL-Query-Parameter im eigenen Code konstruiert — keine analoge Konstruktion gefunden. `LASTFM_API_KEY`/`FANART_API_KEY` werden nach der LASTFM-COVER-DEAD-Entfernung nur noch je einmal verwendet (Last.fm: `lastfm_client.py`, ausschließlich über `pylast`; Fanart: `cover_processor.py`, als URL-Parameter, aber ohne vergleichbares ungefiltertes Exception-Logging-Muster gefunden). Kein weiteres Modul konstruiert Credential-tragende URLs auf die gleiche Weise wie `navidrome_api.py` (repo-weiter Grep, 0 zusätzliche Treffer).

**Ergebnis:** E3/DEMONSTRATED (reproduziert). **HIGH** (echtes Systemzugriffs-Credential, Admin-Telegram-einsehbar; nicht CRITICAL, da Auslösung einen tatsächlichen HTTP-Fehler voraussetzt und die Sichtbarkeit auf Admin-User beschränkt ist).

### S2 — User Input → Downloader

**Prüfung:** Vollständige Call-Chain `Update.message.text` → `_is_supported_download_url()` → `handle_youtube_links()` → `download_audio()` → yt-dlp/Dateisystem.

**Evidence:** `_is_supported_download_url()` (Allowlist auf `youtube.com`/`youtu.be`/`music.youtube.com`-Domains) greift vor jeder weiteren Verarbeitung (`handle_url()`, Zeile 525). Dateinamen laufen durchgängig durch `sanitize_filename()`/sind über `_ensure_within_roots()` gegen Path Traversal abgesichert (bereits in Baseline v2 §13 als PASS bewertet, hier repo-weit erneut gegengeprüft — keine neuen ungeschützten Konstruktionsstellen von Dateipfaden aus Nutzereingaben gefunden).

**Ergebnis:** E0 — **NO MATERIAL SECURITY RISK** für S2 (bereits etablierter, weiterhin intakter Schutz).

### S3 — Filesystem / Command Boundaries

**Prüfung:** Repo-weiter Scan auf `shell=True`, `os.system`, `eval`/`exec`, `tempfile`-Nutzung (Symlink-/Race-Risiken).

**Evidence:** 0 Treffer für `shell=True`, `os.system`, `eval(`, `exec(` im gesamten Produktionscode. Keine `tempfile`-Modul-Nutzung gefunden — Downloads laufen über feste, konfigurierte Verzeichnisse (`DOWNLOAD_DIR`) statt über Python-`tempfile`, wodurch klassische `tempfile`-Race-/Symlink-Fallstricke strukturell nicht auftreten können.

**Ergebnis:** E0 — **NO MATERIAL SECURITY RISK** für S3.

---

## 9. Maintainability Triage

### M1 — Duplicate Behavior

**Prüfung:** Suche nach mehreren Implementierungen derselben Fachlogik mit unterschiedlichem Verhalten (Artist-/Titel-Normalisierung als wahrscheinlichste Kandidaten).

**Evidence:** Nur je eine `normalize_artist`/`clean_artist`-artige Funktion pro Verantwortungsbereich gefunden (`utils/helpers.py`, `services/metadata/artist_processor.py`) — unterschiedliche Namen, unterschiedliche Zwecke (generische String-Bereinigung vs. fachliche Artist-Bestimmung), keine Evidenz für konkurrierende Implementierungen derselben Entscheidung. Genre-Logik wurde bereits in ARCH-012/019/021 als NICHT dupliziert charakterisiert (Clients = Transport, `GenreProcessor` = alleinige Entscheidung) — hier nur gegengeprüft, kein neuer Fund.

**Ergebnis:** E1/OBSERVATION — keine belastbare Evidenz für M1.

### M2 — Ambiguous Ownership

**Prüfung:** Mehrere Mutationspunkte für denselben Zustand.

**Evidence:** Keine über die bereits in Abschnitt 5 (A3, Singletons) und Abschnitt 6 (R2, Library-Move-vs-Tag-Write) dokumentierten Punkte hinausgehende Evidenz gefunden.

**Ergebnis:** E0 — kein eigenständiges M2-Finding (deckt sich mit bereits erfassten A3/R2-Punkten).

### M3 — Change Risk (DEAD-CODE-ERRHANDLER)

**Prüfung:** Aufbauend auf A2 — tatsächliche Erreichbarkeit aller Klassen/Funktionen in `handlers/enhanced_error_handler.py` (2506 Zeilen, größte Datei des Repos) repo-weit verifiziert.

**Evidence:** `ExceptionMonitor`, `DebugTracker`, `EnhancedErrorHandler`, `ErrorHandlerAdminInterface` sind aktiv (Konstruktion in `bot.py`/`handlers/menu/rich_menu_handler.py` nachgewiesen, jeweils mit Tests). Dagegen: `ErrorHandlerIntegration` (Klasse, ~150 Zeilen), `create_complete_error_handling_system()`, `install_global_exception_handler()`, `try_catch_decorator()` (weitere ~300 Zeilen) haben **0 Aufrufer außerhalb ihrer eigenen Definitionsdatei** (repo-weiter Grep) und **0 Testabdeckung**. Zusammen ~450 der 2506 Zeilen (≈18 %) der größten Datei des Repos sind damit nachweislich unerreichbarer, ungetesteter Code.

**Ergebnis:** E3/DEMONSTRATED. **LOW–MEDIUM** (kein Laufzeit-/Sicherheitsrisiko, da unerreichbar; aber realer Wartungs-/Verständnis-Overhead in der ohnehin größten und am wenigsten übersichtlichen Datei — erschwert z. B. Coverage-Bewertungen und Refactoring-Entscheidungen für die aktiven 82 %). Kein Deep Audit nötig — Fund ist bereits vollständig durch Grep/AST belegt, nächster Schritt wäre eine reine Lösch-Entscheidung, kein weiterer Untersuchungsbedarf.

---

## 10. Feature / Product Triage

### F1 — Docs vs Reality

**Evidence:** README.md und CLAUDE.md wurden im Rahmen der vorangegangenen Session-Arbeit (P3-Cleanup, PR #51) bereits aktuell gehalten (Testzahlen, Spotify-Entfernung, tote `.env`-Variablen). Die in ARCH-020 dokumentierte Divergenz zwischen CLAUDE.md §4 (vereinfachtes Pipeline-Diagramm) und dem tatsächlichen Orchestrator (`download_utils.py` statt `DownloadHandler`) ist ein bereits erfasster, historischer Befund (ARCH-020) — kein neues Finding, wird hier nicht wiedereröffnet.

**Ergebnis:** E1/OBSERVATION, bereits historisch erfasst — kein neues Finding.

### F2 — Critical User Journey

**Prüfung:** Telegram → URL → Download → Metadata → Audio → Library, Nachvollziehbarkeit via Code + Tests.

**Evidence:** Durchgängig nachvollziehbar (siehe Baseline v2 §11, dort als ACCEPTABLE bewertet — hier keine neue Gegenevidenz gefunden, die diese Bewertung ändern würde). Die in dieser Triage gefundenen Robustness-/Performance-Findings (Abschnitt 11) beeinträchtigen NICHT die Nachvollziehbarkeit des Ablaufs selbst, sondern dessen Robustheit unter Fehlerbedingungen — das ist bereits unter R1/R2/P3 erfasst, keine Doppelzählung hier.

**Ergebnis:** E1 — kein eigenständiges F2-Finding über die bereits erfassten Robustness-Punkte hinaus.

### F3 — Dead Active Features

**Prüfung:** Erreichbar aussehende, aber tatsächlich nicht (mehr) funktionsfähige Feature-Pfade (Spotify explizit ausgenommen).

**Evidence:** Keine gefunden über den bereits unter M3 (DEAD-CODE-ERRHANDLER) erfassten Fund hinaus — dieser ist jedoch kein „Feature", sondern reine Error-Handling-Infrastruktur, daher unter Maintainability geführt, nicht hier.

**Ergebnis:** E0 — **NO MATERIAL PRODUCT RISK** für F3.

---

## 11. Candidate Deep Audits

### FINDING-1 — COVER-BLOCKING

- **Dimension:** Performance (P3) + Robustness (R1)
- **Evidence:** `services/metadata/cover_processor.py::get_cover_art()` ist synchron (`def`, nicht `async def`), durchläuft sequenziell bis zu 6 Quellen mit je `timeout=8`s über einen gemeinsamen `_get()`-Helper, `ThreadPoolExecutor`/`as_completed` sind importiert aber unbenutzt (reine `for`-Schleife). Aufruf erfolgt ungewrappt aus `services/metadata/enhanced_metadata_processor.py::process_single_track()` (Zeile 697, `async def`), das direkt (kein `asyncio.to_thread`) auf dem Haupt-Event-Loop läuft.
- **Risk:** HIGH
- **Impact:** Der gesamte Telegram-Bot wird für ALLE Nutzer für die Dauer der Cover-Suche unresponsive — bei jedem einzelnen Track-Download, nicht nur im Fehlerfall. Worst Case (kein Early-Exit-Treffer, mehrere Quellen liefern langsam/keine Antwort): bis zu ~48s Blockierung pro Track. Strukturell identisch zum bereits behobenen yt-dlp-Event-Loop-Blocking-Fund aus einer früheren Session-Phase — dort wurde exakt dieses Muster als P0 behandelt.
- **Why Deep Audit?** Der Fund selbst ist bereits demonstriert (E3); ein Deep Audit ist nötig, um den korrekten Fix-Ansatz zu bestimmen (z. B. `asyncio.to_thread()`-Wrapping am Aufrufpunkt vs. echte Parallelisierung der Quellen vs. Reduktion der Sequential-Timeouts) und die Auswirkung auf Early-Exit-Verhalten/Bestehende Tests zu prüfen, bevor ein Fix implementiert wird.
- **Suggested Audit Scope:** `cover_processor.py::get_cover_art()` + alle Aufrufer, Test-Coverage-Lücke für den blockierenden Charakter (bestehende Tests mocken die Fetch-Methoden direkt, decken das Executor-Wrapping-Verhalten nicht ab), Wechselwirkung mit `MAX_CONCURRENT_DOWNLOADS`-Semaphore.

### FINDING-2 — PARTIAL-FAILURE-LIBRARY

- **Dimension:** Robustness (R2)
- **Evidence:** `enhanced_metadata_processor.py::process_single_track()`, Schritt 16 (`move_to_library()`, Zeile 828) vor Schritt 17 (`tag_writer.write_tags()`, Zeile 841), kein lokales Error-Handling dazwischen. Äußerer Catch-Block (Zeile 993) ruft `cleanup_single_download_artifact()` auf, dessen eigener Docstring den No-Op-Fall exakt für „`move_to_library()` bereits gelaufen" beschreibt.
- **Risk:** HIGH
- **Impact:** Eine unvollständig getaggte Datei (kein Artist/Album/Genre/Lyrics/Cover, nur rohe yt-dlp-Metadaten) verbleibt permanent im finalen Library-Pfad, obwohl der Download dem Nutzer als fehlgeschlagen gemeldet wird. Von Navidrome scannbar. Erschwert zudem künftige Re-Download-Versuche (Library-Fallback-Duplicate-Detection könnte die fehlerhafte Datei als „bereits vorhanden" werten).
- **Why Deep Audit?** Nötig, um zu bestimmen, ob ein Rollback (Datei zurück/löschen bei Tag-Schreib-Fehler), ein Retry-Mechanismus für `write_tags()`, oder eine Erweiterung von `cleanup_single_download_artifact()` auf den Post-Move-Fall der richtige Ansatz ist — sowie um zu prüfen, wie oft `write_tags()` in der Praxis tatsächlich fehlschlägt (aktuell keine Metrik/kein Log-Auswertungs-Ansatz vorhanden).
- **Suggested Audit Scope:** `process_single_track()` Schritte 16–18, `TagWriter.write_tags()` Fehlerquellen, `cleanup_single_download_artifact()` Erweiterbarkeit, Interaktion mit Duplicate-Detection (Library-Fallback-Ebene).

### FINDING-3 — NAVIDROME-PASSWORD-LOG-LEAK

- **Dimension:** Security (S1)
- **Evidence:** `services/clients/navidrome_api.py::make_request()`, `except HTTPError`/`except Exception`-Zweige loggen das rohe Exception-Objekt (`{http_err}`/`err`). `requests.Response.raise_for_status()` formatiert Fehlermeldungen nachweislich als `"{status} Client/Server Error: {reason} for url: {response.url}"`, `response.url` enthält `p=<NAVIDROME_PASS im Klartext>` (reproduziert, siehe Abschnitt 8/S1). Landet in `logs/` (`EnhancedRotatingFileHandler`) und ist über den Telegram-Log-Viewer (`enhanced_logger_menu_handler.py::show_log_file_detail()`) für Admin-User einsehbar.
- **Risk:** HIGH
- **Impact:** Ein reales Systemzugriffs-Credential (Zugang zum Nutzer-eigenen Navidrome/Musikserver) landet im Klartext in einer Datei, die absichtlich für Admin-Einsicht via Telegram konzipiert ist — trotz vorhandener, korrekter Maskierung im Erfolgsfall (Inkonsistenz zwischen Happy-Path- und Error-Path-Logging).
- **Why Deep Audit?** Nötig, um den korrekten Fix zu bestimmen (Exception vor dem Loggen selbst maskieren vs. `response.url` aus der Fehlermeldung entfernen vs. eigene, sichere Fehlerformatierung statt `str(exception)`) und zu prüfen, ob dasselbe Muster bei künftigen Client-Erweiterungen wiederkehren könnte (Coding-Guideline-Bedarf).
- **Suggested Audit Scope:** `navidrome_api.py::make_request()` alle Except-Zweige, `Config.mask_sensitive()` Wiederverwendbarkeit für Exception-Objekte, Log-Rotation/Retention (wie lange bleibt ein bereits geleaktes Passwort im Log bestehen), stichprobenartige Prüfung anderer Module auf denselben Anti-Pattern (in dieser Triage bereits repo-weit negativ geprüft, sollte im Deep Audit nochmals bestätigt werden).

---

## 12. Explicit Non-Findings

Bewusst geprüfte Bereiche ohne belastbare Findings (E0/E1, NO MATERIAL RISK):

- **Layer-Grenzen / zirkuläre Imports** (A1) — 0 Reverse-Dependencies, 0 Zyklen, AST-verifiziert über 92 Module.
- **Blocking I/O in Genius-/Last.fm-/MusicBrainz-/Navidrome-Clients** (R1/P3, außerhalb CoverProcessor) — alle vier konsistent über `asyncio.to_thread()` entkoppelt.
- **Externe Request-Vervielfachung** (P1) — MusicBrainz-Cache vorhanden, keine unnötigen Wiederholungen gefunden.
- **Wiederholte teure Arbeit pro Workflow** (P2) — keine gefunden.
- **User-Input → Downloader-Validierung** (S2) — Allowlist + Path-Traversal-Schutz intakt, repo-weit erneut gegengeprüft.
- **Shell-/Command-Injection, `eval`/`exec`, `tempfile`-Race/Symlink-Risiken** (S3) — 0 Treffer repo-weit.
- **Duplicate Behavior in Artist-/Genre-Logik** (M1) — keine konkurrierenden Implementierungen gefunden, deckt sich mit ARCH-012/019/021.
- **Docs-vs-Reality abgesehen von bereits historisch erfasstem ARCH-020-Befund** (F1) — README/CLAUDE.md aktuell.
- **Dead Active Features (Produkt-Ebene, Spotify ausgenommen)** (F3) — keine gefunden.

---

## 13. Closed / Historical Items

Nur zur Abgrenzung — **nicht** als aktuelle Technical Debt dargestellt:

- Titel-Parsing-Bug — **CLOSED**
- HTTP-Request-Logging — **CLOSED**
- Spotify-Unterstützung — **REMOVED** (bewusst, kein offenes Finding)
- AUTOLEARN-001, RETRY-COVERAGE, AUTOLEARN-002, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO, PODCAST-INDEX-KEY, LASTFM-COVER-DEAD — **CLOSED** (Baseline v2, alle mit Regressionsnachweis)
- ARCH-020 CLAUDE.md-§4-Diagramm-Divergenz (`download_utils.py` als realer Orchestrator statt `DownloadHandler`) — **HISTORICAL**, bereits in ARCH-020 dokumentiert, hier nicht wiedereröffnet

---

## 14. Recommended Next Phase

Priorisiert nach Impact, Evidence, Likelihood, Engineering Value — nicht nach Präferenz. Maximal drei Kandidaten, wie gefordert:

1. **FINDING-1 (COVER-BLOCKING)** — höchste Likelihood (tritt bei JEDEM Track auf, nicht nur im Fehlerfall) kombiniert mit hohem Impact (Bot-weite Unresponsiveness). Strukturell identisch zu einem bereits als P0 behandelten, behobenen Muster (yt-dlp) — die Engineering-Baseline für „was ist bereits gelöst" existiert damit schon im selben Repository.
2. **FINDING-3 (NAVIDROME-PASSWORD-LOG-LEAK)** — höchste Security-Kritikalität (echtes Systemzugriffs-Credential, admin-einsehbar), reproduziert und zweifelsfrei belegt, vergleichsweise kleiner, gut eingegrenzter Fix-Scope (eine Datei, zwei Except-Zweige).
3. **FINDING-2 (PARTIAL-FAILURE-LIBRARY)** — Datenintegritäts-Risiko im P0-Bereich „File/Library Processing" laut CLAUDE.md §5. Etwas geringere Likelihood als FINDING-1 (setzt einen tatsächlichen `write_tags()`-Fehler voraus), aber hoher Impact bei Eintritt (dauerhaft falsche Datei in der Library, keine Telemetrie über tatsächliche Häufigkeit vorhanden — genau das sollte der Deep Audit klären).

DEAD-CODE-ERRHANDLER (Maintainability) wird bewusst **nicht** als Deep-Audit-Kandidat vorgeschlagen — der Fund ist bereits vollständig belegt (kein weiterer Untersuchungsbedarf), die Entscheidung ist eine reine Lösch-Frage außerhalb der Kette TRIAGE → DEEP AUDIT.

---

## Nachtrag (2026-08-25): FINDING-3 (NAVIDROME-PASSWORD-LOG-LEAK) — Deep Audit abgeschlossen, behoben

Freigabe für Empfehlung Nr. 2 aus Abschnitt 14. Deep Audit deckte auf, dass eine
naive Fix-Variante (nur die Log-Zeile in `make_request()` selbst maskieren)
**nicht ausgereicht** hätte:

1. `raise` reicht das Original-Exception-Objekt unverändert weiter — jeder
   Aufrufer, der `str(e)` selbst loggt (repo-weit gefunden: 13 `except
   Exception`-Blöcke allein in `handlers/navidrome_menu_handler.py`), hätte
   das Passwort erneut geleakt, unabhängig von der Maskierung an der
   Ursprungsstelle.
2. `exc_info=True` haengt bei Python-Logging den vollstaendigen Traceback
   inkl. der letzten Zeile `ExceptionType: <str(exception)>` an — reproduziert
   belegt, dass selbst eine bereits maskierte Log-*Nachricht* das Passwort via
   Traceback erneut offenlegt, wenn `exc_info=True` gesetzt ist.

**Fix:** `services/clients/navidrome_api.py::make_request()` — neue
`_scrub_credentials()`-Hilfsfunktion (Regex auf `u=`/`p=`-Query-Parameter),
angewandt auf alle drei Except-Zweige (`HTTPError`, `ConnectionError`,
generisches `Exception`). Statt das Original-Objekt weiterzureichen, wird ein
neues `RuntimeError(safe_msg)` **mit `from None`** geworfen (unterdrückt
Exception-Chaining, damit kein späteres `exc_info=True` bei einem Aufrufer
das Original-Objekt doch noch ausgibt) — verifiziert per Reproduktion (siehe
unten). `exc_info=True` im generischen Zweig entfernt (hätte denselben
Leak-Mechanismus erneut ausgelöst). Kein Aufrufer im Repository unterscheidet
nach Exception-Typ (repo-weit geprüft) — der Typwechsel zu `RuntimeError` ist
funktional unkritisch.

**Test:** 3 neue Regressionstests in `tests/test_navidrome_api_logging.py`
(HTTPError-, ConnectionError-, genereller-Exception-Zweig), reproduzieren
exakt das `requests`-Fehlermeldungsformat. Per `git stash` gegen den
Vor-Fix-Stand verifiziert: alle 3 schlagen ohne den Fix fehl (Passwort im
`caplog`-Text nachweisbar), mit Fix grün. Ein bestehender Test
(`test_navidrome_api_timeout.py::test_requests_timeout_is_not_silently_swallowed`)
prüfte bislang den konkreten Exception-*Typ* (`requests.exceptions.Timeout`)
— an das neue, bewusst geänderte Verhalten angepasst (`RuntimeError`
propagiert weiterhin sicher, kein Erfolg wird maskiert — der eigentliche
Testzweck bleibt erhalten).

**Vollregression:** 1060 passed, 0 failed (+3 gegenüber vorherigem Stand,
keine neue Regression).

FINDING-3 gilt damit als **FIXED**. FINDING-1 (COVER-BLOCKING) und FINDING-2
(PARTIAL-FAILURE-LIBRARY) sind weiterhin offen.
