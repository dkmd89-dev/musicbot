# MusicBot Phase 4 — Failure-Path Engineering Audit

## 1. Audit Scope

| Feld | Wert |
|---|---|
| Repository | `dkmd89-dev/musicbot` |
| HEAD Commit | `eea8cd824bcc4dcafc6b58109aca67541e90d9ec` (main) |
| Audit-Datum | 2026-08-25 |
| Baseline-Referenz | `docs/MusicBot_ENGINEERING_BASELINE_v3.md` (eingefroren) |
| Vorausgesetzter Teststand | 1063 passed, 0 failed |
| Verifizierter Teststand | **1063 passed, 0 failed** (eigener Lauf, siehe Abschnitt 2) — Repository entspricht v3, Audit wird fortgesetzt |
| Explizit ausgeschlossen (CLOSED/HISTORICAL) | Titel-Parsing-Bug, HTTP-Request-Logging, Spotify-Entfernung, AUTOLEARN-001, RETRY-COVERAGE, AUTOLEARN-002, CHANNEL-PATTERN, STALE-TEST, PYTEST-ASYNCIO, PODCAST-INDEX-KEY, LASTFM-COVER-DEAD, FINDING-1 (COVER-BLOCKING), FINDING-2 (PARTIAL-FAILURE-LIBRARY), FINDING-3 (NAVIDROME-PASSWORD-LOG-LEAK) — alle bereits gefixt/geschlossen |
| Modus | **Audit only** — keine Produktionscode-, Test-, Konfigurations- oder Mapping-Änderungen |

## 2. Repository / Baseline State

```text
git status               → clean (vor Audit-Beginn)
git branch --show-current → main
git rev-parse HEAD        → eea8cd824bcc4dcafc6b58109aca67541e90d9ec
python3 -m pytest tests/ -q
  → 1063 passed, 0 failed, 19 subtests passed, 1 Warning, ~47s
```

Repository entspricht exakt dem in v3 dokumentierten Zustand. Kein
Reinterpretations-Bedarf — Audit wird wie geplant fortgesetzt.

## 3. Methodology

Für jeden kritischen Workflow wird die tatsächliche Aufrufkette anhand des
aktuellen Codes (nicht historischer Dokumentation) nachvollzogen, für jede
Grenze (Downloader → Dateisystem → Metadaten → Bibliothek → Cache →
Reporting) das Verhalten bei Fehlschlag konkret am Code verifiziert. Jede
Behauptung ist mit Datei/Zeile belegt. Evidence-Klassifikation E0–E3 und
Severity CRITICAL–INFO wie in Abschnitt 13/15 des Auftrags definiert. Vor
jedem Finding wurde das False-Positive-Gate (Abschnitt 16 des Auftrags)
angewandt — mehrere zunächst vermutete Probleme wurden dabei explizit als
Non-Findings verworfen (siehe Abschnitt 20).

## 4. Critical Workflow Map

```text
Telegram-Update
   ↓
DownloadHandler.handle_url()          [_is_supported_download_url-Gate]
   ↓ (Semaphore: MAX_CONCURRENT_DOWNLOADS)
DownloadHandler.handle_youtube_links() [zentrale Orchestrierung, klassen/download_handler.py]
   ↓
_check_duplicates_before_download()   [DuplicateDetector.check_for_duplicates]
   ↓
YoutubeDownloader.download_audio()    [services/downloader/downloader.py, dünner Wrapper]
   ↓
enhanced_download_with_retry()        [REALER Orchestrator, download_utils.py — Retry-Loop]
   ↓
_process_single_download() / _process_playlist_download()
   ↓
EnhancedMetadataProcessor.process_single_track()
   [Cache-Check → Artist/Title/Genre/Lyrics → Cover (asyncio.to_thread)
    → Audio-Normalisierung → move_to_library() (shutil.move)
    → write_tags() (mit Cleanup-try/except seit FINDING-2)
    → MetadataResult → cache_handler.store() → Auto-Learning]
   ↓
DownloadHandler._process_single_download_result() [Guard/Pass-Through]
   ↓
DownloadHandler.handle_single_track_success() / handle_playlist_success()
   [DuplicateDetector.register_download() + build_final_summary_message()]
   ↓
_send_report_message() → Telegram
```

Diese Kette deckt sich strukturell mit ARCH-020 (historisch), wurde hier
aber gezielt auf Fehlerpfade statt auf den Happy Path geprüft.

## 5. W1 — Single Track Download

Jede Grenze wurde einzeln geprüft:

| Grenze | Verhalten bei Fehlschlag | Beleg |
|---|---|---|
| `handle_url()` / URL-Gate | Sauber: Telegram-Antwort "⚠️ Diese URL wird nicht unterstützt", kein Seiteneffekt | `klassen/download_handler.py:525-532` |
| Duplicate-Check | Sauber: `_handle_duplicate_found()` informiert Nutzer, kein Download gestartet | `klassen/download_handler.py:574-577` |
| Downloader (yt-dlp) | Retry-Loop mit exponentiellem Backoff (RETRY-COVERAGE, CLOSED), erschöpft → `{"success": False, "error": ...}` als **Rückgabewert, keine Exception** | `download_utils.py:357-387` |
| **`download_audio()` → `handle_youtube_links()` bei `success: False`** | **Siehe FINDING-4 unten — kein Telegram-Feedback** | `downloader.py:57-60`, `klassen/download_handler.py:643-645` |
| Metadata-Extraktion/-Übersetzung | Fehler propagiert als Exception zum äußeren `except` in `process_single_track()`, sauber als `MetadataResult(success=False, ...)` zurückgegeben | `enhanced_metadata_processor.py:1001-1020` |
| Cover-Retrieval/-Processing | Seit FINDING-1 non-blocking (`asyncio.to_thread`); `get_cover_art()` selbst fängt Fehler pro Quelle ab, liefert `(None, None)` bei Totalausfall — kein Crash | `cover_processor.py` (bereits in Phase-1-Triage verifiziert) |
| Tag-Schreiben nach Library-Move | Seit FINDING-2: lokales try/except, entfernt inkonsistente Datei, re-raised | `enhanced_metadata_processor.py:847-882` (siehe v3 §3) |
| **Library-Move (`shutil.move`)** | **Siehe FINDING-6 unten — nicht atomar über Mountpoints hinweg** | `utils/filenamefixer.py:330` |
| **Cache-Write (`cache_handler.store()`)** | Verifiziert: kompletter eigener try/except, schluckt JEDE Exception, re-raised nie — kann eine sonst erfolgreiche Verarbeitung NICHT zum Scheitern bringen (Non-Finding, siehe §20) | `services/metadata/cache.py:111-174` |
| **`video_id_index.json`-Schreiben** | **Siehe FINDING-5 unten — nicht atomar, im Gegensatz zum Haupt-Cache** | `services/metadata/cache.py:166-172` vs. `utils/metadata_cache.py:195-200` |
| Reporting | Siehe W5 | — |

## 6. W2 — Playlist / Multi-Track

- **Sequenziell, nicht konkurrent**: `for idx, track_info in enumerate(processed_tracks, 1):` — reine `for`-Schleife, kein `asyncio.gather`/`TaskGroup`. Verifiziert `download_utils.py:494`.
- **Track-N-Fehlschlag**: eigener try/except pro Track-Iteration (`download_utils.py:500-601`), fängt Exceptions ab, hängt `DownloadResult(success=False, ...)` an `results` an, `continue` — die Schleife läuft für alle weiteren Tracks unbeeinträchtigt weiter.
- **Tracks 1..N-1 bleiben**: verifiziert — kein Rollback-Mechanismus für bereits erfolgreich verarbeitete Tracks, wenn ein späterer Track scheitert (das ist beabsichtigtes, korrektes Verhalten für unabhängige Tracks, kein Finding).
- **Retry für einzelne Tracks**: NICHT vorhanden. Der äußere Retry-Loop in `enhanced_download_with_retry()` umschließt den GESAMTEN `_process_playlist_download()`-Aufruf; ein einzelner Track-Fehlschlag wird intern abgefangen (kein Exception-Bubble-Up), löst daher NIE einen erneuten Gesamt-Versuch aus. Ein fehlgeschlagener Einzeltrack wird nie automatisch erneut versucht.
- **Doppelte Verarbeitung desselben Tracks**: pro Track existiert ein Cache-Lookup (`cache_manager.lookup_playlist_track()`) vor dem eigentlichen Download — verhindert Doppelverarbeitung bei erneuter Playlist-Verarbeitung nach vorherigem Teilerfolg (Cache-Hit → `continue`, kein erneuter Download).
- **Playlist-Zustand partiell persistiert**: ja, korrekt — jeder erfolgreiche Track wird sofort in Library + Cache geschrieben, unabhängig vom Ausgang nachfolgender Tracks.
- **Reporting kann vom tatsächlichen Dateisystem-Zustand abweichen**: **JA — siehe FINDING-4 (0/N-Fall)**, siehe unten.

Klare Trennung bestätigt: Per-Track-Fehler werden isoliert behandelt (korrekt), Playlist-Level-Fehler (z. B. `PlaylistProcessor`-Ausnahme vor der Track-Schleife) propagieren als Exception zum Retry-Loop, Infrastruktur-Fehler (z. B. `_process_playlist_download` wirft `DownloadError("Playlist ist leer...")`) ebenfalls — beide Fälle korrekt vom bestehenden Retry-/Fehler-Mechanismus abgedeckt.

## 7. W3 — Duplicate / Already Processed

Übernommene, bereits in der Post-Baseline-Triage (Phase 1, Abschnitt „R3 — Concurrency") mit konkreter Evidenz belegte Beobachtung, hier nicht neu hergeleitet, sondern gegen den aktuellen Code erneut bestätigt (unverändert seit Phase 1, keine neue Ursache):

- `check_for_duplicates()` (früh, vor dem Download) und `register_download()` (nach vollständigem Erfolg) sind getrennte Aufrufe — klassisches Check-then-Act-Muster.
- Zwei zeitgleiche Downloads derselben URL (z. B. Doppel-Senden durch den Nutzer) können beide die Prüfung passieren, bevor der erste registriert ist.
- **Vorhandene Mitigation, verifiziert**: `move_to_library()`s Kollisions-Erkennung (`while final_target.exists(): ... umbenannt ...`) plus `handle_youtube_links()`s `renamed_due_to_conflict`-Behandlung (löscht die redundante Datei, meldet sie als `"file_conflict"`-Duplikat) — verhindert dauerhafte Datei-Duplizierung. Verbleibender Effekt: verschwendete Rechenzeit/Bandbreite im Rennfenster, keine Dateninkonsistenz.
- **Kein neuer, unabhängiger Failure-Mode gefunden** — daher hier nicht als neues Finding aufgenommen (Auftragsregel §0: nicht wiedereröffnen ohne neue Evidenz).

Zusätzlich geprüft: `DuplicateDetector.register_download()` fügt einen Eintrag ohne vorherige Existenzprüfung hinzu (`self.duplicate_cache.add_entry(entry)`, `services/duplicate/detector.py:228`) — bei zweifachem Aufruf für denselben Track würden zwei Cache-Einträge entstehen. Kein konkreter, erreichbarer Codepfad gefunden, der `register_download()` zweimal für denselben erfolgreichen Track aufruft (wird pro Erfolgsmeldung genau einmal aufgerufen). **Non-Finding** (siehe §20) — rein theoretisch, keine reproduzierbare Ausführung.

## 8. W4 — Cache / Persistence

Zwei Cache-Schreibpfade mit **unterschiedlicher Crash-Sicherheit** innerhalb *derselben* `MetadataCacheHandler.store()`-Methode identifiziert:

1. **Haupt-Metadaten-Cache** (`utils/metadata_cache.py:172-217`, `store()`): schreibt in eine temporäre Datei (`path.with_suffix(f".tmp_{...}")`), dann `tmp_path.replace(path)` — atomarer Rename auf POSIX-Systemen. **VERIFIED crash-sicher.**
2. **`video_id_index.json`** (`services/metadata/cache.py:166-172`, `_save_video_id_index()`): `with open(self._video_id_index_path, "w", ...) as f: json.dump(...)` — **kein** Tmp-Datei-Pattern, direktes Öffnen im Schreibmodus (truncated sofort beim Öffnen). **VERIFIED nicht crash-sicher** — siehe FINDING-5.
3. **Fehlerbehandlung**: beide Schreibvorgänge laufen innerhalb desselben äußeren try/except in `MetadataCacheHandler.store()` (`services/metadata/cache.py:113-174`), das JEDE Exception abfängt und nur loggt (`except Exception as e: self.logger.warning(...)`) — ein Schreibfehler in Pfad 1 oder 2 kann eine ansonsten erfolgreiche Track-Verarbeitung **nicht** zum Scheitern bringen. **Verifiziertes Non-Finding**, siehe §20.
4. **Widersprüchlicher Zustand Cache vs. Dateisystem**: `MetadataCacheHandler.check()` prüft zusätzlich `Path(library_path_str).exists()` (`services/metadata/cache.py:73-79`) — ein Cache-Eintrag, dessen referenzierte Datei nicht mehr existiert, wird korrekt als Miss behandelt statt eine tote Referenz zurückzugeben. **Verifiziertes Non-Finding.**

## 9. W5 — Telegram Error Path

Dies ist der Abschnitt mit der höchsten Finding-Dichte dieses Audits.

- **Kann der Nutzer "Erfolg" nach internem Fehlschlag erhalten?** JA — siehe **FINDING-4** (Playlist mit 0 erfolgreichen Tracks zeigt trotzdem den Erfolgs-Header).
- **Kann eine Exception verschluckt werden, ohne dass der Nutzer informiert wird?** JA — siehe **FINDING-4** (Single-Track-Fall: der "Erfolgsfall"-Rückgabewert `{"success": False}` aus dem Retry-Loop wird zu einem stillen `return` ohne jede Telegram-Nachricht, siehe unten).
- **Kann derselbe Fehler doppelt gemeldet werden?** Nicht gefunden — `handle_download_failure()` wird nur einmal pro `except`-Block aufgerufen, kein doppelter Versand nachweisbar.
- **Können interne Details/Credentials leaken?** Bereits in Phase 1 als FINDING-3 (Navidrome) behoben. Für den Haupt-Download-Pfad geprüft: `handle_download_failure()`s Nutzer-Text (`klassen/download_handler.py:676-683`) verwendet `str(error_message)` direkt — dieser stammt aus `last_error` im Retry-Loop, der wiederum aus `str(exception)` von yt-dlp-Fehlern gebildet wird. Keine Secrets in diesem Pfad identifiziert (yt-dlp-URLs enthalten keine MusicBot-eigenen Credentials). **Kein neuer Fund derselben Problemklasse wie FINDING-3.**

### FINDING-4 im Detail (siehe auch §19 für die formale Finding-Struktur)

Exakter Codepfad für den Single-Track-Fall:

```text
enhanced_download_with_retry() erschöpft alle Versuche
  → return {"success": False, "error": "..."}          (download_utils.py:365-368/384-387)
YoutubeDownloader.download_audio()
  → if not download_result.get("success"):
        return {"success": False, "error": error_message}   (downloader.py:57-60)
DownloadHandler.handle_youtube_links()
  → results_list = [download_result]                         (Zeile 592)
  → for res in results_list:
        if not res.get("success"): continue                  (Zeile 603-607)
  → processed_results bleibt LEER
  → if not processed_results:
        self.logger.warning(...)
        return                                                (Zeile 643-645)
```

**Kein Aufruf von `handle_download_failure()`.** Der Nutzer sieht nie eine
Fehlermeldung — die zuletzt per `_update_status()` editierte Telegram-
Statusnachricht bleibt auf ihrem letzten Zwischenstand (z. B. "📥 Schritt
3/6: Download läuft...") stehen und wird nie aktualisiert. Aus Nutzersicht
wirkt der Bot wie hängengeblieben, nicht wie fehlgeschlagen.

`handle_download_failure()` wird ausschließlich vom äußeren `except
Exception as e:`-Block erreicht (Zeile 660-664) — der jedoch bei einem
**normal zurückgegebenen** `{"success": False}` (der designierten,
häufigsten Fehlersignalisierung des Retry-Loops) nie greift, da keine
Exception geworfen wird.

## 10. W6 — Process Interruption

Ausschließlich aus Code, Dateisystem-Semantik und der tatsächlichen
Deployment-Konfiguration hergeleitet — keine erfundenen Crash-Garantien.

| Schritt | Verhalten bei SIGTERM/Crash |
|---|---|
| Download (yt-dlp) | yt-dlp schreibt selbst in `DOWNLOAD_DIR`; ein Abbruch hinterlässt bestenfalls eine unvollständige Datei dort. Nächster Prozessstart: keine dedizierte Startup-Bereinigung von `DOWNLOAD_DIR` gefunden (außerhalb des Scopes dieses Audits, nicht weiter verifiziert). |
| Metadata-Verarbeitung (vor Library-Move) | Betrifft nur `DOWNLOAD_DIR`-Datei — bei Abbruch bleibt die Rohdatei dort liegen, keine Library-Inkonsistenz. |
| Tag-Schreiben | Mutagen schreibt i. d. R. direkt in die Zieldatei — ein Abbruch mitten im Tag-Schreibvorgang kann eine beschädigte Audiodatei-Tag-Struktur hinterlassen (nicht im Detail durch Mutagen-interne Analyse verifiziert, außerhalb des Scopes; nur die Tatsache, dass FINDING-2s Exception-basierter Cleanup bei einem harten Prozessabbruch NICHT greifen kann, ist verifizierbar — try/except fängt keine SIGKILL-Beendigung ab). |
| **Library-Move** | **Siehe FINDING-6 — `shutil.move()` ist nicht durchgängig atomar; bei der tatsächlich konfigurierten Deployment-Topologie (siehe unten) nachweislich NICHT atomar.** |
| Cache-Persistierung | Haupt-Cache: atomarer Rename, crash-sicher (siehe W4). `video_id_index.json`: nicht crash-sicher (FINDING-5), aber mit gutmütigem Fallback beim nächsten Laden. |

### FINDING-6 im Detail

`utils/filenamefixer.py:330`: `shutil.move(str(source_path), str(final_target))`.

`shutil.move()` verwendet `os.rename()` (atomar) nur, wenn Quelle und Ziel
auf demselben Dateisystem liegen; andernfalls fällt Python intern auf
`copy2()` + `unlink()` zurück (dokumentiertes Standardverhalten der
Python-Stdlib, nicht MusicBot-spezifisch, aber hier direkt relevant, da
MusicBot sich nicht dagegen absichert).

**Tatsächliche, verifizierte Deployment-Konfiguration** (`config.py:76-81`):

```python
BASE_DIR = Path("/mnt/128ssd/musicbot")
LIBRARY_DIR = Path("/mnt/4tb/library")
DOWNLOAD_DIR = BASE_DIR / "import" / "downloads"   # = /mnt/128ssd/musicbot/import/downloads
```

`DOWNLOAD_DIR` (`/mnt/128ssd/...`) und `LIBRARY_DIR` (`/mnt/4tb/...`) liegen
auf **unterschiedlichen Mountpoints** — dies ist keine hypothetische
Deployment-Variante, sondern der tatsächlich konfigurierte Standardwert
dieses Repositories. `shutil.move()` fällt hier nachweislich auf
Copy+Delete zurück. Ein SIGTERM/Crash/OOM-Kill während dieses Copy-Vorgangs
kann eine unvollständige Datei im Library-Verzeichnis hinterlassen, während
die Quelldatei im `DOWNLOAD_DIR` je nach Abbruchzeitpunkt bereits gelöscht
oder noch vorhanden ist.

## 11. Failure Matrix

| Boundary | Failure | Side Effect Before Failure | Cleanup | Final State | User Result |
|---|---|---|---|---|---|
| Download (Retry erschöpft) | `enhanced_download_with_retry` → `success: False` | Keine Datei in DOWNLOAD_DIR bleibt (yt-dlp räumt bei komplettem Fehlschlag i. d. R. selbst auf — NOT VERIFIED im Detail für alle yt-dlp-Fehlerarten) | N/A | Kein Download | **Kein Feedback (FINDING-4)** — stille Stagnation der Statusnachricht |
| Metadata-Exception vor Library-Move | Beliebige Exception in Schritt 2–15 | Rohdatei in DOWNLOAD_DIR | `cleanup_single_download_artifact()` — VERIFIED (bestehender Test) | Datei entfernt | `handle_download_failure()`-Meldung — VERIFIED korrekt |
| Tag-Schreiben nach Move | `write_tags()` wirft | Datei in LIBRARY_DIR (unvollständig getaggt) | Lokales try/except — VERIFIED (FINDING-2) | Datei entfernt | `handle_download_failure()`-Meldung — VERIFIED korrekt |
| Cache-Write (beide Pfade) | Exception in `store()` | Datei vollständig in LIBRARY_DIR, korrekt getaggt | N/A (bewusst kein Cleanup nötig) | Datei bleibt korrekt bestehen | `MetadataResult(success=True)` — VERIFIED, Cache-Fehler kaskadiert nicht |
| Playlist: 0/N Tracks erfolgreich | Alle Track-Downloads scheitern einzeln | Keine Dateien in LIBRARY_DIR | N/A (pro Track bereits durch eigene Fehlerpfade behandelt) | Keine Dateien | **"✅ Playlist erfolgreich heruntergeladen!" (FINDING-4)** — widerspricht Tracks: 0/N |
| Library-Move | Prozessabbruch (SIGTERM/Crash) während `shutil.move()` über Mountpoints hinweg | Teilkopie in LIBRARY_DIR möglich | Kein Mechanismus (Prozess ist bereits beendet) | **NOT VERIFIED (nicht reproduzierbar ohne echten Crash-Test), aber Codepfad demonstriert fehlende Atomaritäts-Absicherung (FINDING-6)** | Kein Feedback möglich (Prozess tot) |
| `video_id_index.json`-Write | Prozessabbruch während `json.dump()` | Haupt-Cache-Eintrag ggf. bereits atomar geschrieben | Kein Mechanismus | Index-Datei potenziell korrupt, aber beim nächsten Laden gutmütig auf `{}` zurückgesetzt (VERIFIED via `except Exception` in `_load_video_id_index()`) | N/A — betrifft nur interne Performance-Optimierung, kein Nutzer-Feedback nötig |

## 12. State Consistency

Identifizierte, potenziell divergierende State-Stores:

1. **Dateisystem (LIBRARY_DIR) vs. Telegram-Nachricht**: FINDING-4 zeigt zwei Divergenz-Richtungen — (a) Datei existiert nicht, Nutzer erhält keine Meldung (stille Stagnation statt Fehlermeldung); (b) Dateien existieren teilweise (0/N), Nutzer erhält eine "erfolgreich"-Meldung. Autoritativ ist das Dateisystem; die Telegram-Nachricht ist in beiden Fällen NICHT verlässlich.
2. **Duplicate-Cache vs. Dateisystem**: `check_for_duplicates()`/`register_download()` sind vom eigentlichen Dateisystem-Zustand entkoppelt (kein automatischer Abgleich) — bereits in Phase 1 charakterisiert, hier bestätigt unverändert. Divergenz wird durch die File-Conflict-Fallback-Ebene beim nächsten Verarbeitungsversuch erkannt (siehe W3), nicht proaktiv.
3. **Metadata-Cache vs. Dateisystem**: `check()` verifiziert aktiv `library_path.exists()` vor einem Cache-Hit (siehe W4) — **Divergenz wird aktiv erkannt und korrekt als Miss behandelt.** Vorbildliches Muster.
4. **`video_id_index.json` vs. Haupt-Cache**: können nach einem Crash auseinanderlaufen (Index leer, Haupt-Cache vollständig) — Auswirkung: verpasste Cache-Hits (Performance), keine Dateninkonsistenz, da `check()` beim eigentlichen Lookup ohnehin zusätzlich verifiziert.

## 13. Cleanup / Rollback

| Ressource | Erzeugt von | Cleanup-Owner | Auslöser | Cleanup-Fehler-Verhalten | Doppel-Cleanup möglich? |
|---|---|---|---|---|---|
| Rohdatei in DOWNLOAD_DIR | yt-dlp / `download_executor.py` | `cleanup_single_download_artifact()` | Exception vor `move_to_library()` | Eigener try/except, loggt nur (verifiziert: „Fehler beim Löschen werden nur geloggt, nie weitergereicht") | Ja, aber harmlos — zweiter Aufruf trifft auf `not original_path.exists()` → No-op |
| Datei in LIBRARY_DIR (unvollständig getaggt) | `move_to_library()` | Lokales try/except um `write_tags()` (FINDING-2) | Exception bei `write_tags()` | Eigener `except OSError`, loggt nur | N/A — nur ein Aufrufpfad |
| Cache-Einträge (Haupt + Index) | `MetadataCacheHandler.store()` | Kein expliziter Owner nötig — Schreibfehler kaskadieren nicht (siehe W4) | N/A | N/A | N/A |
| Duplicate-Cache-Eintrag | `register_download()` | Kein automatisches Cleanup — bleibt bei einem späteren Datei-Löschen bestehen (potenzieller „Karteileiche"-Eintrag ohne existierende Datei); **NOT VERIFIED**, ob dies operativ jemals auftritt, da keine Lösch-Funktionalität für Library-Dateien außerhalb dieses Audits identifiziert wurde |
| Temporäre Kopie während `shutil.move()` bei Cross-Filesystem-Fallback | Python-Stdlib intern (`shutil.copy2`) | Python-Stdlib selbst (löscht Quelle nach erfolgreicher Kopie) | N/A — kein MusicBot-Code beteiligt | Bei Abbruch: kein Cleanup möglich (FINDING-6) | N/A |

## 14. Exception Propagation

| Ursprung | Gefangen in | Transformiert? | Geloggt? | Erneut geworfen? | Aufrufer informiert? |
|---|---|---|---|---|---|
| yt-dlp-Fehler im Retry-Loop | `enhanced_download_with_retry()` selbst | Ja — zu `{"success": False, "error": str}` | Ja | **Nein** — bewusstes Design (Rückgabewert statt Exception) | Ja, aber als Datenstruktur, nicht als Exception — siehe FINDING-4 für die Konsequenz beim Weiterreichen |
| `write_tags()`-Fehler | Lokal in `process_single_track()` (FINDING-2) | Nein | Ja | Ja (`raise`) | Ja, korrekt über äußeren `except` |
| `cache_handler.store()`-Fehler | Lokal in `store()` selbst | Nein | Ja (Warning) | **Nein** — bewusst geschluckt | Nein — korrekt, da nicht-kritischer Seitenkanal |
| Beliebige Exception in `process_single_track()` | Äußerer `except Exception as e` | Nein (Message übernommen) | Ja, mit `exc_info=True` | Nein — in `MetadataResult(success=False)` übersetzt | Ja, korrekt |
| Beliebige Exception in `handle_youtube_links()` | Äußerer `except Exception as e` | Nein | Ja, mit `exc_info=True` | Nein — `handle_download_failure()` aufgerufen | Ja, korrekt |

Kein Fall von doppelter Fehlermeldung oder fälschlich zu Erfolg
herabgestufter Exception gefunden. Der einzige echte Bruch in der Kette ist
kein Exception-Propagation-Fehler im engeren Sinne, sondern die
bewusste architektonische Entscheidung, Downloadfehler als Rückgabewert
statt als Exception zu signalisieren (FINDING-4) — an der Schnittstelle
zwischen `download_audio()` und `handle_youtube_links()` wird dieser
Rückgabewert nicht symmetrisch zum Exception-Pfad behandelt.

## 15. Retry Safety

- **Retryable Operation**: `enhanced_download_with_retry()`s Retry-Loop (Extraktion + Download + Verarbeitung).
- **Idempotenz**: Jeder Versuch beginnt bei `extract_info_async()` neu (kein State aus dem vorherigen Versuch wird wiederverwendet außer `last_error`) — verifiziert in `download_utils.py:283-387`.
- **Duplikate durch Retry?** Ein einzelner Retry-Versuch, der bis zum Library-Move gelangt und DANACH fehlschlägt (z. B. bei Tag-Schreibfehler), würde beim NÄCHSTEN Retry-Versuch erneut komplett von vorne starten (neuer Download, neue Metadatenverarbeitung) — FINDING-2s Cleanup entfernt die inkonsistente Datei zuverlässig VOR dem nächsten Versuch, daher **kein Duplikat-Risiko durch Retries** — verifiziert am aktuellen (bereits gefixten) Code.
- **Externe APIs bei Retry**: MusicBrainz/Last.fm/Genius werden bei jedem Retry-Versuch erneut angefragt (kein Zwischenspeichern über Versuche hinweg) — bei wiederholten Fehlschlägen entsteht mehrfacher Netzwerk-Traffic, aber keine Dateninkonsistenz. **Kein Finding** — dies ist normales, erwartetes Retry-Verhalten ohne schädliche Nebenwirkung.
- **Playlist-Track-Retries**: wie in W2 festgestellt, existieren keine — daher auch keine Retry-Sicherheitsfrage auf Track-Ebene.

## 16. Cancellation / Concurrency

- **Konkurrente Downloads**: `MAX_CONCURRENT_DOWNLOADS`-Semaphore erlaubt mehrere GLEICHZEITIGE `handle_youtube_links()`-Ausführungen für unterschiedliche Downloads — verifiziert `klassen/download_handler.py:534-537`.
- **Konkrete geteilte Zustände zwischen konkurrenten Downloads**: `EnhancedDownloadProcessor`/`EnhancedMetadataProcessor`/`GenreMapper`/`FilenameFixerTool` sind `SingletonMixin`-basiert — EINE gemeinsame Instanz für alle gleichzeitigen Downloads. Bereits in Phase 1 (Architecture A3) geprüft und als in Produktion nicht auslösbar bewertet (kein Config-Reload-Pfad) — hier zusätzlich auf **konkurrente Downloads statt nur Testverschmutzung** geprüft:
  - `self.processing_stats`/`self.processed_titles` (Instanzattribute von `EnhancedMetadataProcessor`) werden von JEDEM gleichzeitigen `process_single_track()`-Aufruf mutiert — z. B. `self.processing_stats.total_processed += 1`. Da `process_single_track()` eine Coroutine ist und Python-`int`-Inkrement innerhalb eines einzelnen Bytecode-Schritts ohne `await`-Unterbrechung läuft, ist ein klassischer Lost-Update hier **nicht demonstrierbar** — die Inkrement-Operation selbst ist nicht unterbrechbar. **Kein Finding** — konkrete Evidenz für tatsächliche Inkonsistenz fehlt (Auftragsregel §10: „theoretische Async-Bedenken nicht als Finding markieren").
  - `CoverProcessor.session` (gemeinsame `requests.Session`) wird seit FINDING-1 aus mehreren echten Executor-Threads gleichzeitig verwendet (vorher lief wegen der Event-Loop-Blockierung faktisch nie mehr als ein Cover-Abruf gleichzeitig). `requests.Session` mit `HTTPAdapter`-Connection-Pooling ist für nebenläufige GET-Anfragen aus mehreren Threads ein etabliertes, von der Bibliothek unterstütztes Muster — **kein konkreter, reproduzierbarer Fehlerpfad gefunden**, daher **kein Finding**, aber als Beobachtung festgehalten: dies ist ein direkter, bisher nicht existenter Nebeneffekt von FINDING-1s Fix und sollte bei künftigen CoverProcessor-Änderungen im Blick behalten werden.
- **Task Cancellation**: kein expliziter `asyncio.Task.cancel()`-Aufrufpfad im Repository gefunden, der einen laufenden Download gezielt abbricht (z. B. durch einen Nutzerbefehl "Abbrechen"). **NOT APPLICABLE** — Feature existiert nicht, daher keine Cancellation-Fehlerpfade zu prüfen.

## 17. Failure Reporting

Direkter Abgleich interner Zustand vs. Telegram-Nachricht, wie in Abschnitt 11 des Auftrags gefordert:

| Kombination | Gefunden? | Beleg |
|---|---|---|
| Interner Fehlschlag + Nutzer "Erfolg" | **JA** | FINDING-4 (Playlist 0/N) |
| Interner Fehlschlag + gar keine Nutzer-Meldung | **JA** | FINDING-4 (Single-Track `success: False`-Rückgabewert) |
| Interner Erfolg + Nutzer "Fehlschlag" | Nicht gefunden (die zunächst vermutete `cache_handler.store()`-Kaskade wurde als Non-Finding widerlegt, siehe §20) | — |
| Datei existiert + System meldet Fehlschlag | Nicht gefunden | — |
| Datei fehlt + System meldet Erfolg | Nicht gefunden (im Playlist-0/N-Fall wird korrekt "Tracks: 0/N" mitgeliefert — die Inkonsistenz liegt im widersprüchlichen Header, nicht in falschen Zahlen) | — |

## 18. Test Coverage Characterization

| Fehlerpfad | Status | Beleg |
|---|---|---|
| Happy Path (Single) | COVERED | `test_metadata_processor_happy_path.py`, `test_download_utils_metadata_translation.py` |
| Happy Path (Playlist) | PARTIALLY COVERED | `_process_playlist_download()`-Bausteine (Cache, Track-Metadata) einzeln getestet, kein End-to-End-Playlist-Test über `handle_youtube_links()` |
| Externe Fehlschläge (Genius/Last.fm/MusicBrainz/Navidrome) | COVERED | Je eigene Client-Testdatei, inkl. Timeout/Fehler-Fälle |
| Filesystem-Fehlschlag (Download→Metadata-Grenze) | COVERED | `test_error_after_move_to_library_cleans_up_orphaned_source_file` |
| Tag-Schreibfehler nach Move | COVERED | `test_tag_write_failure_after_move_removes_inconsistent_library_file` (FINDING-2-Fix) |
| Cache-Fehlschlag | PARTIALLY COVERED | `test_metadata_cache_handler.py` deckt Happy Path + einzelne Fehlerfälle der Cache-Klasse ab, aber nicht explizit „Cache-Fehler kaskadiert nicht zu Track-Fehlschlag" als End-to-End-Aussage |
| Library-Fehlschlag (move_to_library selbst wirft) | COVERED | `test_error_after_move_to_library_cleans_up_orphaned_source_file` |
| **Retry-Erschöpfung → Telegram-Reporting (`handle_youtube_links()`)** | **NOT COVERED** | Kein Test referenziert `handle_youtube_links`, `handle_playlist_success` oder `handle_single_track_success` überhaupt (repo-weiter Grep, 0 Treffer außer Docstring-Erwähnungen) |
| **Playlist mit 0 erfolgreichen Tracks (Reporting)** | **NOT COVERED** | `test_playlist_type_uses_playlist_header_and_track_counts` deckt nur den 2/3-Fall ab, kein 0/N-Test |
| Duplicate-Detection Race | NOT COVERED (bereits in Phase 1 als solches festgehalten) | — |
| Cancellation | NOT APPLICABLE | Feature existiert nicht |
| Process Interruption (SIGTERM/Crash) | NOT APPLICABLE (nicht sinnvoll unit-testbar) | — |

Die beiden NOT-COVERED-Punkte decken sich exakt mit FINDING-4 — die
fehlende Testabdeckung ist hier direkte Ursache dafür, dass das
Fehlverhalten bisher unentdeckt blieb, nicht nur eine allgemeine Lücke.

## 19. Findings

### FINDING-4 — Misleading/Missing Telegram-Reporting bei Download-Fehlschlag

- **Severity:** HIGH
- **Evidence Level:** E3 (demonstrated)
- **Affected Component:** `klassen/download_handler.py::handle_youtube_links()`, `handle_playlist_success()`, `handle_single_track_success()`; `services/downloader/downloader.py::download_audio()`
- **Exact Code Path:** siehe Abschnitt 9 (zwei Teilbefunde: Single-Track-Stille und Playlist-0/N-Erfolgsmeldung)
- **Trigger Condition:**
  - (a) `enhanced_download_with_retry()` erschöpft alle Retries für einen Single-Track-Download (z. B. Video nicht mehr verfügbar, dauerhafter Netzwerkfehler) → `{"success": False}`.
  - (b) Eine Playlist wird verarbeitet, bei der jeder einzelne Track individuell fehlschlägt (z. B. alle Videos privat/gelöscht) → `{"success": True, "type": "playlist", "tracks": [...alle success:False...]}`.
- **State Before Failure:** Kein Download begonnen bzw. kein Track erfolgreich verarbeitet.
- **Failure:** Downloader/Track-Verarbeitung schlägt fehl, aber ohne Exception zu werfen — Fehlersignalisierung erfolgt über Rückgabewerte (`success: False` auf Track-Ebene, `success: True` auf Playlist-Wrapper-Ebene).
- **State After Failure:** Keine Library-Datei(en). Kein Cache-Eintrag.
- **Expected State:** Nutzer erhält eine klare, unzweideutige Fehlermeldung.
- **Actual State:** (a) Telegram-Statusnachricht bleibt bei ihrem letzten Zwischenstand stehen, keine Aktualisierung — wirkt wie ein hängender/nicht reagierender Bot. (b) Nutzer erhält "✅ Playlist erfolgreich heruntergeladen! ... Tracks: 0/N" — ein direkter Widerspruch zwischen Erfolgs-Header und Zahlen in derselben Nachricht.
- **Impact:** Nutzer kann nicht zuverlässig erkennen, ob ein Download fehlgeschlagen ist. Führt operativ zu: unnötigen Wiederholungsversuchen durch den Nutzer (im Fall a), fälschlichem Vertrauen in ein Ergebnis, das tatsächlich leer ist (im Fall b), sowie zu Support-Aufwand ("Bot hängt" trotz technisch korrektem Abschluss).
- **Existing Mitigation:** `handle_download_failure()` existiert und funktioniert korrekt — aber nur für den Exception-Pfad, nicht für den (häufigeren) designierten Rückgabewert-Fehlerpfad.
- **Why Mitigation Is Insufficient:** Die beiden Fehlersignalisierungs-Mechanismen (Exception vs. Rückgabewert) werden an der Schnittstelle `download_audio()` → `handle_youtube_links()` nicht symmetrisch behandelt; nur der seltenere Exception-Pfad hat einen vollständigen User-Facing-Handler.
- **Reproduction / Proof:** Code-Pfad vollständig nachvollzogen (Abschnitt 9); für den Playlist-Fall zusätzlich durch den bestehenden Test `test_playlist_type_uses_playlist_header_and_track_counts` indirekt bestätigt (zeigt denselben unconditional-header-Mechanismus bereits für den 2/3-Fall, extrapoliert zwingend auf 0/N, da keine Sonderbehandlung im Code für `ok == 0` existiert).
- **Recommended Fix Scope:** Klein und lokal begrenzt — (a) `handle_youtube_links()` sollte den Fall "kein `processed_results`, aber `download_result` enthielt einen Fehlertext" von "gar keine Downloads angefordert" unterscheiden und `handle_download_failure()` mit dem tatsächlichen Fehlertext aufrufen; (b) `build_final_summary_message()`/`handle_single_track_success()` sollten bei `is_pl and ok == 0` einen Fehlschlags- statt Erfolgs-Header wählen. Kein Architekturumbau nötig — beide Fixes sind lokale Bedingungsprüfungen an bereits vorhandenen Werten (`ok`, `download_result.get("error")`).

### FINDING-5 — `video_id_index.json` nicht crash-sicher (im Gegensatz zum Haupt-Cache)

- **Severity:** LOW
- **Evidence Level:** E2 (plausible risk — Crash-Zeitpunkt exakt während des Schreibvorgangs ist ein enges Zeitfenster, Impact ist auf Performance begrenzt)
- **Affected Component:** `services/metadata/cache.py::MetadataCacheHandler._save_video_id_index()`
- **Exact Code Path:** `services/metadata/cache.py:166-172` (nicht-atomarer Write) vs. `utils/metadata_cache.py:195-200` (atomarer Write im selben Aufrufkontext, `store()`)
- **Trigger Condition:** Prozessabbruch (SIGTERM/Crash/OOM-Kill) exakt während `json.dump()` in `_save_video_id_index()`.
- **State Before Failure:** Haupt-Metadaten-Cache ggf. bereits atomar aktualisiert (läuft vorher in derselben `store()`-Methode).
- **Failure:** `video_id_index.json` wird durch den `open(mode="w")`-Aufruf sofort geleert (Truncate-on-Open), der Crash unterbricht den nachfolgenden `json.dump()` — Datei bleibt leer oder mit ungültigem JSON zurück.
- **State After Failure:** `video_id_index.json` korrupt oder leer.
- **Expected State:** Index bleibt konsistent zum Haupt-Cache.
- **Actual State:** Index inkonsistent — beim nächsten Prozessstart greift jedoch `_load_video_id_index()`s eigener `except Exception: return {}` (verifiziert, `services/metadata/cache.py`) und initialisiert einen leeren Index, statt mit einer Exception zu crashen.
- **Impact:** Verlust der Video-ID-basierten Fast-Path-Cache-Lookup-Optimierung für ALLE zuvor gecachten Einträge — führt zu vermehrten Cache-MISSES (unnötige Re-Verarbeitung bereits bekannter Tracks) bis der Index sich durch neue `store()`-Aufrufe wieder füllt. **Keine Datenintegritäts- oder Sicherheitsauswirkung**, keine doppelten Library-Dateien (der eigentliche Metadaten-Cache und die Duplicate-Detection sind von diesem Index unabhängig).
- **Existing Mitigation:** Gutmütiger Fallback beim Laden verhindert einen Crash beim nächsten Start — verifiziert.
- **Why Mitigation Is Insufficient:** Verhindert einen Folgefehler, behebt aber nicht den Datenverlust selbst — der Index muss sich über Zeit neu aufbauen.
- **Reproduction / Proof:** Code-Vergleich der beiden Schreibpfade in derselben Methode, direkt nachvollziehbar.
- **Recommended Fix Scope:** Minimal — dasselbe Tmp-Datei-plus-Rename-Muster wie im Haupt-Cache auf `_save_video_id_index()` übertragen (wenige Zeilen, kein Architektureingriff).

### FINDING-6 — `shutil.move()` nicht atomar zwischen den tatsächlich konfigurierten DOWNLOAD_DIR/LIBRARY_DIR-Mountpoints

- **Severity:** MEDIUM
- **Evidence Level:** E3 für den Code-Fakt (nicht-atomarer Move bei Cross-Filesystem), E2 für den tatsächlichen Eintritt eines Crashs im kritischen Zeitfenster (nicht reproduzierbar ohne echten Prozessabbruch-Test)
- **Affected Component:** `utils/filenamefixer.py::FilenameFixerTool.move_to_library()`
- **Exact Code Path:** `utils/filenamefixer.py:330` (`shutil.move(...)`), Konfiguration: `config.py:76-81`
- **Trigger Condition:** Prozessabbruch (SIGTERM/Crash/OOM-Kill) während des Kopiervorgangs von `DOWNLOAD_DIR` (`/mnt/128ssd/musicbot/import/downloads`) nach `LIBRARY_DIR` (`/mnt/4tb/library`) — verifiziert unterschiedliche Mountpoints in der tatsächlichen Konfiguration dieses Repositories.
- **State Before Failure:** Vollständige, fertig prozessierte Audiodatei im DOWNLOAD_DIR.
- **Failure:** Prozess wird während des internen `copy2()`-Fallbacks von `shutil.move()` beendet.
- **State After Failure:** Potenziell unvollständige/abgeschnittene Datei am Zielort in LIBRARY_DIR; Quelldatei in DOWNLOAD_DIR je nach exaktem Abbruchzeitpunkt noch vorhanden oder bereits gelöscht.
- **Expected State:** Entweder vollständige Datei am Ziel ODER Datei bleibt vollständig an der Quelle — nie ein unvollständiger Zwischenzustand.
- **Actual State:** NOT VERIFIED für den konkreten Wortlaut des Zwischenzustands (kein reproduzierbarer Crash-Test durchgeführt, wie vom Auftrag gefordert nicht erfunden) — aber der Codepfad selbst demonstriert nachweislich das Fehlen jeder Atomaritäts-Absicherung.
- **Impact:** Eine potenziell beschädigte/unvollständige Audiodatei könnte in der Musik-Bibliothek landen und von Navidrome gescannt werden, bevor der nächste Bot-Start eine Bereinigung vornehmen könnte (keine solche Startup-Bereinigung für LIBRARY_DIR identifiziert).
- **Existing Mitigation:** Keine gefunden.
- **Why Mitigation Is Insufficient:** N/A — keine Mitigation vorhanden.
- **Reproduction / Proof:** Konfigurationswerte direkt aus `config.py` gelesen, Python-Stdlib-Verhalten von `shutil.move()` bei Cross-Filesystem-Operationen ist dokumentiertes, öffentliches Verhalten (kein MusicBot-Code-Fehler, sondern fehlende Absicherung dagegen).
- **Recommended Fix Scope:** Klein — Copy-zu-temporärem-Namen-im-Zielverzeichnis, dann `Path.replace()` (garantiert atomar, sofern Temp-Datei bereits im Zielverzeichnis/-Dateisystem liegt) statt direktem `shutil.move()` über Mountpoints hinweg. Kein Architektureingriff, lokal auf `move_to_library()` begrenzt.

## 20. Explicit Non-Findings

- **`cache_handler.store()`-Fehler kaskadieren nicht zu einem fälschlich gemeldeten Download-Fehlschlag.** Zunächst als möglicher Kandidat für „interner Erfolg + Nutzer-Fehlschlag" vermutet — durch Code-Lektüre widerlegt: `MetadataCacheHandler.store()` fängt jede Exception intern ab und reicht sie nie weiter (`services/metadata/cache.py:113-174`). Explizit verifiziert, nicht nur angenommen.
- **Tagging-Fehler-Cleanup verifiziert korrekt** (FINDING-2, bereits gefixt) — hier im Rahmen von Phase 4 erneut gegen den aktuellen Code bestätigt, kein Rückschritt.
- **Cache-Write-Fehler löscht keine gültige Library-Datei** — verifiziert, da der Cache-Schreibpfad komplett nach dem Library-Move/Tag-Schreiben läuft und selbst bei Fehlschlag keine Datei anfasst.
- **Keine Duplikat-Verarbeitungs-Race mit tatsächlicher Datei-Duplizierung demonstrierbar** — die bereits in Phase 1 bekannte Race hat eine verifizierte, wirksame Fallback-Ebene (Datei-Konflikt-Erkennung); kein neuer, unabhängiger Failure-Mode in Phase 4 gefunden.
- **Exceptions propagieren durchgängig korrekt** entlang der Metadaten-Pipeline (W1) — kein Fall von fälschlich verschluckter oder doppelt gemeldeter Exception gefunden, mit der einzigen (bereits als FINDING-4 dokumentierten) Ausnahme des bewussten Rückgabewert-Musters im Retry-Loop.
- **Playlist-Track-Isolation funktioniert korrekt** — ein einzelner fehlgeschlagener Track in einer Playlist beeinträchtigt weder vorherige noch nachfolgende Tracks.
- **Konkurrente Downloads über den geteilten `EnhancedMetadataProcessor`-Singleton** — kein reproduzierbarer Inkonsistenz-Fall gefunden (Statistik-Inkremente sind nicht unterbrechbare Einzeloperationen; `CoverProcessor.session`-Nebenläufigkeit ist ein von der `requests`-Bibliothek unterstütztes Muster). Als Beobachtung (nicht Finding) festgehalten, da FINDING-1 diese Nebenläufigkeit neu ermöglicht hat.
- **`DuplicateDetector.register_download()`-Doppelaufruf** — kein konkreter, im aktuellen Code reproduzierbarer Aufrufpfad gefunden, der dieselbe Registrierung zweimal auslöst.
- **Task-Cancellation** — Funktionalität existiert nicht im Repository, daher keine zu prüfenden Fehlerpfade (NOT APPLICABLE, nicht „sicher").

## 21. Recommended Next Actions

Priorisiert nach Datenintegrität → Security → nutzersichtbare Korrektheit → Produktionszuverlässigkeit → operativer Impact → Wartungsimpact (Auftragsregel §20), nicht nach Implementierungsaufwand:

1. **FINDING-4 (HIGH)** — höchste Priorität: betrifft direkt die nutzersichtbare Korrektheit des zentralen Produktfeatures (Download-Feedback) und tritt bei jedem dauerhaft fehlschlagenden Download bzw. jeder komplett fehlschlagenden Playlist auf — kein Rand­fall.
2. **FINDING-6 (MEDIUM)** — Datenintegritätsrisiko für die Library bei Prozessabbruch, in der tatsächlichen Deployment-Konfiguration nachweislich relevant (unterschiedliche Mountpoints), aber seltener auslösbar als FINDING-4 (setzt einen Crash exakt im kritischen Zeitfenster voraus).
3. **FINDING-5 (LOW)** — reiner Performance-/Cache-Effizienz-Punkt, keine Daten- oder Sicherheitsauswirkung, kleinster Fix-Scope der drei.

Gemeinsame Grundursache zwischen FINDING-5 und FINDING-6: **inkonsistente Anwendung des bereits im Repository etablierten Tmp-Datei-plus-atomarer-Rename-Musters** (in `utils/metadata_cache.py` bereits korrekt vorhanden) — beide Fixes würden dasselbe, bereits bewährte Muster nur auf zwei weitere Schreibstellen übertragen, kein neues Konzept nötig.

Kein Finding aus diesem Audit erfordert einen Architekturumbau, neue Abstraktionen, verteilte Transaktionen oder ein Retry-Framework — alle drei empfohlenen Fixes sind lokal begrenzte, kleinstmögliche Eingriffe an bereits identifizierten, präzisen Stellen.

---

## Nachtrag (2026-08-25): FINDING-4, FINDING-5, FINDING-6 gefixt

**FINDING-4** separat per Forensic Deep Audit behandelt und gefixt — siehe
`docs/MusicBot_FINDING_4_FORENSIC_AUDIT.md` (eigenes Dokument, eigener
Nachtrag dort).

**FINDING-5** (`video_id_index.json` nicht crash-sicher): `services/metadata/cache.py::_save_video_id_index()`
nutzt jetzt dasselbe Write-Tmp-plus-atomarer-Rename-Muster wie der
Haupt-Cache (`utils/metadata_cache.py::store()`). 3 neue Tests in
`tests/test_metadata_cache_handler.py::TestVideoIdIndexAtomicWrite`, per
`git stash` verifiziert: der entscheidende Test (unterbrochener
zweiter Schreibvorgang darf den vorherigen gültigen Inhalt nicht
zerstören) schlägt am Vor-Fix-Stand nachweislich fehl (Datei wurde auf
leer trunkiert).

**FINDING-6** (`shutil.move()` nicht atomar über Mountpoints hinweg):
`utils/filenamefixer.py::move_to_library()` kopiert jetzt in eine
temporäre Datei IM Zielverzeichnis (`shutil.copy2()`), benennt sie per
`Path.replace()` atomar um, und entfernt die Quelldatei erst danach als
separaten, nicht-kritischen Aufräumschritt (ein Fehlschlag dort lässt die
bereits erfolgreiche Verschiebung nicht nachträglich scheitern). 3 neue
Tests in `tests/test_filenamefixer.py::TestMoveToLibraryAtomicity`, per
`git stash` verifiziert.

**Vollregression:** 1074 passed, 0 failed (+6 gegenüber dem
FINDING-4-Fix-Stand, keine neue Regression).

Damit sind alle sechs in dieser Session bearbeiteten Findings (FINDING-1
bis FINDING-6) abgeschlossen.
