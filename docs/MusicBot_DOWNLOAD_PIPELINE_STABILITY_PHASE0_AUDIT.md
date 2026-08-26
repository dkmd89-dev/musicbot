# MusicBot — Download Pipeline Stability Phase — PHASE 0 Audit Report

> Strikt read-only Deep Audit gemäß `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`.
> Basis: `docs/MusicBot_ENGINEERING_BASELINE_v5.md` (1123 passed/0 failed, Freeze APPROVED).
> Scope: Download Pipeline + Duplicate Detection Integrity. Metadata Quality
> explizit OUT OF SCOPE (außer wo sie unmittelbar die Pipeline-Stabilität
> beeinträchtigt). **Keine Codeänderungen in dieser Phase.**

---

## 29.1 Executive Summary

**Ist die Download-Pipeline grundsätzlich stabil?** Für den Single-Track-Happy-Path: ja. Fehlerpfade (Retry-Erschöpfung, Library-Move-Fehler, Tag-Write-Fehler) sind größtenteils sauber behandelt und mit Cleanup abgesichert. Zwei strukturelle Lücken bestehen: (1) Cancellation wird nirgends in der gesamten Kette behandelt (`CancelledError` ist seit Python 3.8 eine `BaseException`, kein `except Exception` fängt sie), (2) Fehler *innerhalb* des eigentlichen yt-dlp-Download-/Postprocessor-Aufrufs selbst lösen keinen Cleanup aus.

**Ist Duplicate Detection grundsätzlich stabil?** Für Single-Track-Downloads: die kürzlich hinzugefügte Content-/Parser-/Library-Ebene (Finding 1 aus Baseline v5) funktioniert wie dokumentiert, hat aber eine bisher nicht erkannte Schwachstelle (inkonsistente Hash-Normalisierung zwischen Check und Registrierung). **Für Playlist-Tracks funktioniert DuplicateDetector überhaupt nicht** — das ist der schwerwiegendste Einzelfund dieses Audits.

**P0:** keiner gefunden (kein Datenverlust, keine Korruption, keine falschen Überschreibungen bestätigt).

**P1:** 7 (siehe Abschnitt 30).

**P2:** 8.

**P3:** 3 (rein kosmetisch/Doku, hier nicht vertieft, siehe Abschnitt 30 Kurzliste).

**Bereits korrekt gelöst (verifiziert, keine neue Evidenz gegen frühere Funde):** FINDING-4 (Playlist-0-von-N-Erfolg wird korrekt als Fehler gemeldet), FINDING-2 (Tag-Write-Fehler nach erfolgreichem Move räumt korrekt auf, keine doppelte/maskierende Exception), MAX_PLAYLIST_ITEMS-Trunkierung, AE-10/11/12 (unverändert, nicht erneut vertieft geprüft, siehe Baseline v5), atomare Cache-Persistenz (`_write_json_atomic`, kein Korruptionsrisiko bei Absturz während des Schreibens), `move_to_library()`-Fehlerpfade (kein Doppel-Cleanup, kein Verwaisen der tmp-Datei), `download=False`-Probe (Finding 1 aus v5) ist tatsächlich seiteneffektfrei (gegen yt-dlp-Quellcode verifiziert), Start-Sweep `cleanup_download_artifacts()` korrekt vor `start_polling()` verankert.

---

## 29.2 Tatsächlicher Runtime Flow (rekonstruiert, nicht die erwartete Architektur)

```text
Telegram
   ↓
RichMenuHandler (erzeugt EINEN geteilten DuplicateDetector für alle Requests)
   ↓
DownloadHandler (pro Update NEU instanziiert, erhält den geteilten DuplicateDetector)
   ↓
handle_url() — URL-Allowlist + Concurrency-Semaphore (Modul-Level, prozessweit)
   ↓
handle_youtube_links()
   ↓
_check_duplicates_before_download(url)
   → _probe_artist_title_for_duplicate_check(url)   [NEU seit Finding 1, v5]
       yt-dlp extract_info(download=False), volle build_ydl_opts() (verifiziert
       seiteneffektfrei bei download=False)
   → DuplicateDetector.check_for_duplicates(url, raw_artist, raw_title)
       URL-Cache → Content-Cache (nur wenn raw_artist+raw_title vorhanden UND
       KEINE Playlist) → Parsed-Content → Library-Fallback
   ↓ (kein Duplikat)
downloader.download_audio(url)
   ↓
enhanced_download_with_retry()  [max_retries=3, Backoff 2**attempt]
   ├─ SINGLE: _process_single_download()
   │    → download_executor.extract_info_async(download=True) [via run_in_executor]
   │    → EnhancedMetadataProcessor.process_single_track() via
   │      metadata_result_translator.call_process_single_track()
   └─ PLAYLIST: _process_playlist_download()
        → MAX_PLAYLIST_ITEMS-Trunkierung (vor jeder weiteren Verarbeitung)
        → pro Track: cache_manager.lookup_playlist_track() [MetadataCache,
          NICHT DuplicateCache!] → bei Miss: download_executor.download_single_track()
          [max_retries=1, KEIN Top-Level-Retry pro Track] → _process_track_metadata()
          → EnhancedMetadataProcessor.process_single_track() (derselbe Kern wie Single)
        → jeder Track-Fehler wird lokal per except Exception abgefangen,
          Loop läuft weiter (kein Abbruch der restlichen Playlist)
   ↓
EnhancedMetadataProcessor.process_single_track() (gemeinsamer Kern):
   Cache-Check → Artist → Title → Genre → Lyrics → MB-Album-Prefetch (bedingt)
   → Cover → Album/Jahr → Loudness-Normalisierung (asyncio.to_thread, undokumentiert)
   → move_to_library() [sync, kein await intern → NICHT cancellation-anfällig]
   → TagWriter.write_tags() [await asyncio.to_thread, AE-11/12]
   → cache_handler.store() [MetadataCache — läuft für Single UND Playlist]
   → Auto-Learn
   ↓
metadata_result_translator.build_single_track_result() /
build_playlist_track_result() → DownloadResult.to_dict()
   ↓
klassen/download_handler.py::handle_youtube_links()
   results_list = download_result if isinstance(download_result, list) else [download_result]
   → download_result ist für Playlists NIEMALS eine Liste (immer ein Wrapper-Dict
     mit "tracks"-Schlüssel) → results_list = [wrapper] (EIN Element!)
   → Schleife über results_list prüft renamed_due_to_conflict NUR auf dem
     Wrapper, nie auf einzelnen Playlist-Tracks (siehe Finding DL-01)
   ↓
handle_single_track_success() [Single: registriert im DuplicateDetector]
  ODER
handle_playlist_success() [Playlist: ruft handle_single_track_success(playlist_result)
  auf — dessen artist="?" (Wrapper hat kein "artist"-Feld) → register_download()
  wird NIE aufgerufen für Playlist-Tracks, siehe Finding DUP-01]
   ↓
Navidrome (außerhalb des Scopes dieser Phase)
```

**Wichtigste Abweichung von der im Phase-Dokument angenommenen Architektur:** es gibt **zwei unabhängige, nicht koordinierte Cache-/Dedup-Systeme** — `DuplicateCache` (URL/Content-Hash, in `services/duplicate/`) und `MetadataCache` (Artist+Titel, in `utils/metadata_cache.py`, über `CacheManager`). Playlist-Tracks durchlaufen ausschließlich Letzteres.

---

## 29.3 Download Failure Matrix

| Szenario | Aktuelles Verhalten | Cleanup | Result | Risiko |
|---|---|---|---|---|
| Netzwerkfehler (Single) | Kein Error-Type-Unterscheidung — wie jeder andere Fehler 3x retried mit 1s/2s-Backoff | Nur wenn Fehler in `process_single_track()` auftritt (nach erfolgreichem yt-dlp-Download) — Fehler *innerhalb* des yt-dlp-Calls selbst: **kein Cleanup** (`download_utils.py` importiert `cleanup_single_download_artifact` nicht) | `{"success": False, "error": ...}`, sauber bis zum Nutzer propagiert | **P1 (DL-02)** |
| yt-dlp-Fehler (privat/altersbeschränkt/geoblockt) | Identisch retried wie transiente Fehler — keine Erkennung permanenter Fehler | s. o. | s. o. | P2 (DL-03, Ressourcenverschwendung, keine Korrektheitsgefahr) |
| FFmpeg-Fehler | Läuft intern im yt-dlp-Postprocessor, gleiche except-Kette wie oben | Kein spezifischer Cleanup, s. DL-02 | s. o. | P1 (Teil von DL-02) |
| Timeout | Kein explizites `socket_timeout` gesetzt, yt-dlp-Default greift, wie jeder andere Fehler behandelt | s. o. | s. o. | P2 (Teil von DL-03) |
| Cancellation | Nirgends in der Kette behandelt (`CancelledError` = `BaseException`, kein `except Exception` fängt sie); Executor-Thread (yt-dlp/FFmpeg) läuft nach Cancellation trotzdem bis zum Ende weiter (asyncio unterbricht den Worker-Thread nicht) | Kein Cleanup — weder in `DOWNLOAD_DIR` noch (schlimmer) in `LIBRARY_DIR`, falls Cancellation nach `move_to_library()` aber vor Tag-Write/Cache-Store erfolgt | Kein `MetadataResult`, kein Nutzer-Feedback | **P1 (DL-01/CANCEL)** |
| Metadata-Failure (optionaler Service) | Wird abgefangen, Track läuft mit degradierten Metadaten normal weiter | n/a | `success=True`, kein Stabilitätsproblem | Confirmed fine |
| Library-Move-Failure | Sauber: `move_to_library()` räumt eigene tmp-Datei auf, Exception propagiert, `cleanup_single_download_artifact()` greift (Quelle existiert noch) | Sauber | `success=False`, akkurate Fehlermeldung | Confirmed fine |

---

## 29.4 Duplicate Detection Matrix

| Szenario | Erwartung | Ist-Verhalten | Ergebnis | Risiko |
|---|---|---|---|---|
| Gleiche URL (Single) | Erkannt | Erkannt (URL-Cache, normalisiert: youtu.be/watch?v=/Query-Params) | Korrekt | Confirmed fine |
| Gleiche Video-ID, andere URL-Form | Erkannt | Erkannt (`_normalize_url_for_cache`) | Korrekt | Confirmed fine |
| Gleiche Aufnahme, andere URL (Reupload) | Erkannt (Content-Ebene) | Erkannt **nur wenn** Registrierungs- und Prüf-Hash übereinstimmen — tun sie strukturell oft nicht (s. DUP-02) | Unzuverlässig | **P1 (DUP-02)** |
| Artist+Titel identisch, aber „(Live …)“/„(… Version)“-Suffix | Sollte NICHT als Duplikat gelten (andere Version) | Wird als Duplikat erkannt (Regex entfernt Klammerinhalt komplett) | False Positive | **P1 (DUP-03)** |
| „feat.“/„Featuring“/„ft.“ ohne exakt passendes Regex-Muster | Sollte als Duplikat erkannt werden | Wird bei Abweichung (kein Leerzeichen, „Featuring“ statt „feat.“) nicht erkannt | False Negative | P2 (DUP-04) |
| Library-Duplikat (Datei bereits vorhanden) | Erkannt | Erkannt, sofern Probe erfolgreich war und Artist/Titel zum Dateinamen passen | Korrekt, aber kontingent | Confirmed fine (mit Einschränkung) |
| Playlist-Duplikat (ganze Playlist erneut) | Playlist-URL-Ebene erkannt | Nur die exakte Playlist-URL wird erkannt (URL-Cache) — einzelne Tracks NIE gegen DuplicateCache geprüft | Grob funktionierend nur für 1:1-Wiederholung derselben Playlist-URL | P2 (Rest von DUP-01) |
| Gleicher Track: einmal einzeln, einmal in Playlist enthalten | Sollte als Duplikat erkannt werden | **Wird nie erkannt** — Playlist-Tracks landen nie im DuplicateCache | Kompletter Blindspot | **P1 (DUP-01)** |
| Cache Hit (MetadataCache, Playlist-Redundanz) | Track wird nicht erneut heruntergeladen | Funktioniert (Stufe 1/2 Lookup), aber nur solange `library_path` noch existiert | Korrekt | Confirmed fine |
| Cache Failure (Datei korrupt/gelöscht) | Fallback auf Download | `cached_path.exists()`-Check fängt das ab, fällt sauber auf Miss zurück | Korrekt | Confirmed fine |
| Paralleler Request (2 Nutzer, gleicher Track, fast gleichzeitig) | Einer sollte Duplikat erkennen | Kein Lock — Check-then-Register-Race über die gesamte Download-Dauer, beide können parallel herunterladen | Race, vorbestehend, durch Finding 1 nicht signifikant verschlimmert | **P1 (DUP-05)** |

---

## 29.5 Cleanup Matrix

| Exit Path | Artefakte | Cleanup korrekt? | Risiko |
|---|---|---|---|
| SUCCESS | alle | Ja | Confirmed fine |
| FAILURE (Exception nach yt-dlp-Erfolg) | DOWNLOAD_DIR-Datei + `.info.json` | Ja (`cleanup_single_download_artifact`) | Confirmed fine |
| FAILURE (Exception innerhalb yt-dlp/FFmpeg) | DOWNLOAD_DIR-Datei + `.info.json` | **Nein** (kein Cleanup-Call in `download_utils.py`) | **P1 (DL-02)** |
| RETRY | — | Kein Leak über `outtmpl`-Kollision hinaus verifiziert | P2 (DL-03, s. o.) |
| CANCELLATION vor `move_to_library()` | DOWNLOAD_DIR-Datei + `.info.json` | Nein | **P1 (DL-01)** |
| CANCELLATION nach `move_to_library()`, vor Tag-Write/Cache-Store | LIBRARY_DIR-Datei (unvollständig getaggt, nicht im Cache) | Nein — Datei bleibt dauerhaft, nicht nachverfolgt | **P1 (DL-01)** |
| EXCEPTION (regulär, nicht Cancellation) | — | Ja, s. o. | Confirmed fine |
| DUPLICATE | — | n/a, kein Download gestartet | Confirmed fine |
| PARTIAL PLAYLIST SUCCESS | pro fehlgeschlagenem Track wie FAILURE oben | Gemischt (abhängig davon, wo der Fehler auftrat) | Siehe DL-01/DL-02 |
| LIBRARY MOVE FAILURE | tmp-Datei in LIBRARY_DIR | Ja (`move_to_library()` räumt selbst auf) | Confirmed fine |
| RESTART | `.part`/`.ytdl`/DOWNLOAD_DIR-Reste älter als 24h | Ja, via `cleanup_download_artifacts()` (Strategie A, korrekt vor `start_polling()` verankert); `.part`/`.ytdl` bewusst nie gelöscht | Confirmed fine (bewusste Design-Entscheidung, kein neuer Fund) |

---

## 30. Findings

### DUP-01 — P1 — Duplicate Detection — Playlist-Tracks komplett ungeschützt

**Datei/Funktion:** `klassen/download_handler.py::handle_playlist_success()` (Zeile ~535-557), `handle_single_track_success()` (Zeile ~495-533).

**Ursache:** Playlists laufen immer über `handle_playlist_success()`, die bei erfolgreicher Playlist `handle_single_track_success(playlist_result)` aufruft — aber `playlist_result` ist der Wrapper-Dict (`{"success": True, "type": "playlist", "tracks": [...]}`), nicht ein einzelner Track. `handle_single_track_success()` liest `artist = result.get("artist", "?")` → immer `"?"` beim Wrapper → die Bedingung `artist not in ("?", "Unbekannt", "Unknown Artist")` ist `False` → `self.duplicate_detector.register_download(...)` wird **nie** aufgerufen für Playlist-Tracks.

**Tatsächliches Verhalten:** Kein einziger Playlist-Track wird jemals in `DuplicateCache` registriert. Zusätzlich läuft der Pre-Download-Check (`_check_duplicates_before_download`) nur einmal für die gesamte Playlist-URL, nie pro Track.

**Erwartetes Verhalten:** Jeder erfolgreich verarbeitete Playlist-Track sollte wie ein Single-Download im `DuplicateCache` registriert werden (URL + Artist/Titel).

**Reproduzierbarkeit:** Deterministisch, aus dem Code ableitbar (kein Zufall/Timing nötig) — 100% reproduzierbar durch Lesen des Codepfads, bestätigt durch direkte Nachverfolgung von `artist="?"`.

**Auswirkung:** Song X in Playlist A heruntergeladen → später Song X einzeln oder in Playlist B erneut angefragt → wird nicht als Duplikat erkannt (außer zufällig über den separaten `MetadataCache`, der eine andere Funktion hat und nicht dafür ausgelegt ist). Einzige verbleibende Bremse: `check_library_duplicate()` (Dateisystem-Scan), aber nur wirksam, wenn der Pre-Flight-Probe für den NEUEN Request erfolgreich ist und Artist/Titel zum tatsächlichen Dateinamen passen.

**Minimaler Fix (Vorschlag, noch nicht umgesetzt):** In der Playlist-Track-Schleife (`download_utils.py`, `_process_playlist_download()`) nach erfolgreichem `_process_track_metadata()` `duplicate_detector.register_download()` pro Track aufrufen — dafür muss `duplicate_detector` bis dorthin durchgereicht werden (aktuell nicht injiziert in `download_utils.py`).

**Benötigter Regressionstest:** Playlist mit 2 Tracks erfolgreich verarbeiten → `DuplicateCache` muss 2 neue Einträge enthalten (aktuell: 0).

---

### DL-01 — P1 — Cancellation — Kein Cleanup, potenziell dauerhaft unvollständige Library-Datei

**Datei/Funktion:** projektweit — kein `except asyncio.CancelledError`/`except BaseException` in `download_utils.py`, `download_executor.py`, `enhanced_metadata_processor.py`, `klassen/download_handler.py`.

**Ursache:** `asyncio.CancelledError` ist seit Python 3.8 eine `BaseException`-Subklasse, kein `except Exception` in der gesamten Kette fängt sie ab. Zusätzlich: `run_in_executor`/`asyncio.to_thread`-Worker-Threads werden durch Task-Cancellation NICHT unterbrochen — sie laufen im Hintergrund weiter, ihr Ergebnis wird aber nirgends mehr abgeholt.

**Tatsächliches Verhalten:** Cancellation vor `move_to_library()` hinterlässt eine Datei in `DOWNLOAD_DIR` (wird erst nach 24h vom Start-Sweep erfasst). Cancellation NACH erfolgreichem `move_to_library()`, aber vor/während Tag-Write oder Cache-Store, hinterlässt eine **unvollständig getaggte Datei dauerhaft in `LIBRARY_DIR`** — ohne Cache-Eintrag, ohne dass der nächste Versuch sie als „schon vorhanden" erkennt (führt potenziell zu einer zweiten, kollidierenden Datei via `move_to_library()`s Umbenennungslogik).

**Erwartetes Verhalten:** Bei Cancellation sollte zumindest der `DOWNLOAD_DIR`-Anteil bereinigt werden; eine bereits nach `LIBRARY_DIR` verschobene, aber nicht fertig getaggte Datei sollte nicht unbemerkt liegen bleiben.

**Reproduzierbarkeit:** Deterministisch nachvollziehbar aus der Exception-Hierarchie (`BaseException` vs. `Exception`); praktisch ausgelöst z. B. durch Bot-Shutdown/Neustart während eines laufenden Downloads.

**Auswirkung:** Silent-Duplicate-Risiko in der Library, kein Datenverlust (Original bleibt in `DOWNLOAD_DIR` oder `LIBRARY_DIR` bestehen), aber inkonsistenter, unbereinigter Zustand.

**Minimaler Fix (Vorschlag):** in `process_single_track()`s äußerem Except-Block zusätzlich `except (Exception, asyncio.CancelledError)` (oder separater `except asyncio.CancelledError`-Zweig mit Cleanup + `raise`) ergänzen; Cleanup-Aufruf muss zwischen `DOWNLOAD_DIR`- und `LIBRARY_DIR`-Fall unterscheiden (je nachdem ob `move_to_library()` schon gelaufen ist).

**Benötigter Regressionstest:** `process_single_track()` per `task.cancel()` mitten in einem gemockten Tag-Write abbrechen → LIBRARY_DIR darf danach keine Datei ohne zugehörigen Cache-Eintrag enthalten (bzw. Cleanup muss nachweislich laufen).

---

### DL-02 — P1 — Kein Cleanup bei Fehlern innerhalb des yt-dlp-/FFmpeg-Aufrufs selbst

**Datei/Funktion:** `services/downloader/download_utils.py::_process_single_download()` (Zeile ~906-908), kein Import von `cleanup_single_download_artifact`.

**Ursache:** `cleanup_single_download_artifact()` wird ausschließlich aus `enhanced_metadata_processor.py`s äußerem Except-Block aufgerufen — dieser greift nur bei Fehlern NACH einem bereits erfolgreichen yt-dlp-Download. Scheitert yt-dlp selbst (Netzwerk, Extraktion, FFmpeg-Postprocessing) innerhalb von `_process_single_download()`, wird die Exception zu `DownloadError` umgewandelt und weitergereicht — ohne dass irgendein Cleanup-Aufruf in `download_utils.py` existiert.

**Tatsächliches Verhalten:** Ein teilweise heruntergeladener/konvertierter Rest kann in `DOWNLOAD_DIR` verbleiben, ohne dass die Pipeline ihn kennt oder aufräumt — bis zum nächsten 24h-Start-Sweep.

**Erwartetes Verhalten:** Auch dieser Fehlerpfad sollte den bekannten, konkreten Dateinamen (aus `ydl_opts`/`track_info`) aufräumen, sofern ermittelbar.

**Reproduzierbarkeit:** Deterministisch aus dem Code ableitbar (fehlender Import + fehlender Call).

**Auswirkung:** Kein Datenverlust, aber unnötig lange liegenbleibende Reste (bis zu 24h), potenziell Namenskollisionen bei erneutem Versuch (abhängig von yt-dlps eigenem Overwrite-Verhalten, nicht weiter verifiziert — Metadata-Quality-Scope ausgenommen).

**Minimaler Fix (Vorschlag):** In `_process_single_download()`s Except-Block `cleanup_single_download_artifact()` mit dem erwarteten Zielpfad (aus `ydl_opts["outtmpl"]`/`track_info`) aufrufen, analog zum bereits etablierten Muster in `enhanced_metadata_processor.py`.

**Benötigter Regressionstest:** yt-dlp-Aufruf gezielt mit Exception mocken → `DOWNLOAD_DIR` muss danach leer sein.

---

### DUP-02 — P1 — Inkonsistente Hash-Normalisierung zwischen Check und Registrierung

**Datei/Funktion:** `services/duplicate/detector.py::check_for_duplicates()` (Zeile ~90-97, nutzt `_normalize_artist_for_comparison`/`_clean_title_for_comparison`) vs. `register_download()` (Zeile ~209-230, keine Normalisierung) vs. `services/duplicate/cache.py::get_content_hash()` (Zeile ~190-192, nur `strip().lower()`).

**Ursache:** Beim Registrieren (`klassen/download_handler.py::handle_single_track_success()`, Zeile ~508) werden die vom Metadata-Prozessor bereits „geglätteten" `artist`/`title`-Werte direkt an `register_download()` übergeben — OHNE die detector-eigene `_clean_title_for_comparison()`/`_normalize_artist_for_comparison()`-Logik zu durchlaufen. Beim Prüfen (`check_for_duplicates()`) wird dieselbe Logik dagegen angewendet. Da beide Normalisierungen unterschiedliche Regeln haben, führen strukturell unterschiedliche Eingaben zu unterschiedlichen Hashes für dieselbe Aufnahme.

**Tatsächliches Verhalten:** Die durch Finding 1 (Baseline v5) neu aktivierte Content-Ebene kann strukturell versagen — nicht durch fehlende Daten, sondern durch inkonsistente Hash-Bildung.

**Erwartetes Verhalten:** Registrierung und Prüfung sollten dieselbe Normalisierungsfunktion auf denselben Rohdaten anwenden.

**Reproduzierbarkeit:** Konzeptionell aus dem Code ableitbar; exaktes Reproduzieren erfordert einen konkreten Titel mit einem Klammerzusatz, den `_clean_title_for_comparison()` entfernt, den der Metadata-Prozessor aber unverändert lässt (oder umgekehrt) — im Rahmen dieses Audits nicht durch einen Live-Lauf verifiziert (Metadata-Pipeline-Interna sind Out-of-Scope für Vertiefung), aber die strukturelle Diskrepanz selbst ist zweifelsfrei im Code belegt.

**Auswirkung:** Untergräbt den Zweck von Finding 1 (Baseline v5) teilweise.

**Minimaler Fix (Vorschlag):** `register_download()` dieselbe Normalisierung wie `check_for_duplicates()` auf `artist`/`title` anwenden lassen, bevor der Content-Hash gebildet wird.

**Benötigter Regressionstest:** Track mit „(feat. X)"-Titel registrieren, dann mit leicht abweichender Formatierung erneut prüfen → muss als Duplikat erkannt werden.

---

### DUP-03 — P1 — Normalisierungs-False-Positive bei „(Live …)"/„(… Version)"

**Datei/Funktion:** `services/duplicate/detector.py::_clean_title_for_comparison()`, Regex `r"\(Live.*?\)"` und `r"\(.*?Version\)"`.

**Ursache:** Beide Regex entfernen den GESAMTEN Klammerinhalt unabhängig von seiner Spezifität.

**Tatsächliches Verhalten:** `"Hello (Live at Glastonbury 2016)"` und `"Hello"` (Studio-Original) ergeben nach Bereinigung identisch `"Hello"` → gleicher Content-Hash → die Live-Version wird fälschlich als Duplikat blockiert und nie heruntergeladen. Ebenso `"Song (Radio Version)"` vs. `"Song (Acoustic Version)"`.

**Erwartetes Verhalten:** Unterschiedliche Versionen (Live/Studio, Radio/Acoustic) sollten nicht kollidieren.

**Reproduzierbarkeit:** Deterministisch, per Konstruktion der beiden Beispieltitel exakt nachvollziehbar.

**Auswirkung:** Nutzer kann eine gewünschte, tatsächlich andere Version nicht herunterladen, ohne dass ihm ein klarer Grund („bereits vorhanden") wirklich zutrifft.

**Minimaler Fix (Vorschlag):** Live-/Version-Suffixe nicht vollständig entfernen, sondern in den Vergleich einbeziehen (z. B. als Teil des Hash-Schlüssels statt sie zu strippen), oder nur eine definierte Positivliste generischer Zusätze („Official Video", „Lyrics" o. Ä.) entfernen statt aller „(Live…)"/„(…Version)"-Inhalte.

**Benötigter Regressionstest:** `"Hello (Live at Glastonbury 2016)"` gegen bereits registriertes `"Hello"` prüfen → darf NICHT als Duplikat gelten.

---

### DUP-05 — P1 — Check-then-Register-Race ohne Lock (parallele Downloads)

**Datei/Funktion:** `services/duplicate/cache.py` (kein Lock), `klassen/download_handler.py::_check_duplicates_before_download()` (Zeile ~324) vs. `register_download()` (Zeile ~508).

**Ursache:** Zwischen einem „kein Duplikat"-Ergebnis und der tatsächlichen Registrierung liegt die komplette Download+Verarbeitungsdauer (mehrere Sekunden bis Minuten). In dieser Zeit kann ein zweiter, paralleler Request (begrenzt durch `_download_semaphore`, Default 3) für denselben Content ebenfalls „kein Duplikat" sehen.

**Tatsächliches Verhalten:** Zwei gleichzeitige Downloads derselben Aufnahme sind möglich, resultieren aber wegen der `move_to_library()`-Kollisionslogik in zwei Dateien (Original + „(1)"-Suffix) statt in einer stillen Doppelverarbeitung.

**Erwartetes Verhalten:** Bewusste Design-Entscheidung nötig, ob dieses Risiko akzeptiert bleibt (bereits vor Finding 1 vorhanden, laut `cache.py`-Kommentar bewusst nicht behoben) oder ob ein leichter In-Flight-Lock (z. B. Set aktiver Content-Hashes) eingeführt wird.

**Reproduzierbarkeit:** Deterministisch aus der Codestruktur ableitbar (kein Lock vorhanden), praktisches Timing nicht in diesem Audit reproduziert (kein Codechange erlaubt).

**Auswirkung:** Ressourcenverschwendung (doppelter Download), keine Korruption — die bereits vorhandene `renamed_due_to_conflict`-Logik (für Single-Downloads, siehe Finding DL-01/Playlist-Lücke oben) fängt das Resultat sauber ab.

**Minimaler Fix (Vorschlag, nur falls gewünscht):** In-Memory-Set „aktuell in Bearbeitung befindlicher" Content-Hashes in `DuplicateDetector`, geprüft zusätzlich zum Cache. Nicht zwingend — bewusste Alt-Entscheidung, evtl. als ACCEPTED belassen.

**Benötigter Regressionstest:** Nur falls Fix gewählt wird.

---

### Kurzliste weiterer P2/P3-Funde (nicht einzeln vertieft, da geringere Priorität)

| ID | Kurzbeschreibung | Prio |
|---|---|---|
| DL-03 | Keine Fehlerklassifikation — permanente Fehler (privates/gesperrtes Video) werden wie transiente Fehler 3x retried | P2 |
| DL-04 | `.part`/`.ytdl` werden nie aufgeräumt (bewusste Design-Entscheidung, dokumentiert, kein neuer Fund, hier nur zur Vollständigkeit gelistet) | P3 (DEFER, bereits akzeptiert) |
| PL-01 | Playlist-Tracks haben kein Track-Level-Retry (`max_retries=1` hartkodiert am Call-Site) — transiente Fehler lassen den Track sofort scheitern | P2 |
| DUP-04 | „feat."/„ft."-Regex zu eng (kein Match bei „Featuring" oder fehlendem Leerzeichen) — False-Negative-Risiko | P2 |
| DUP-06 | `watch?v=X&list=RDxxx` (Mix/Radio-Pseudo-Playlists) lösen dieselbe Playlist-Klassifizierung aus wie echte Playlists — Content-/Parser-/Library-Ebene wird für diese eigentlich-Einzelvideos übersprungen | P2 |
| DUP-07 | Library-Fallback-Sicherheitsnetz nach Neustart ist vollständig abhängig vom Erfolg des Pre-Flight-Probes für den NEUEN Request — schlägt der Probe fehl, greift kein Fallback | P2 |
| RES-01 | `is_duplicate`-Flag ist prozesslebensdauer-gebunden (Singleton `processed_titles`), nicht session-/batch-begrenzt — potenziell verwirrende Flags über unabhängige Downloads hinweg | P2 |
| RES-02 | Cover-Art-Cache-Writes (`cover_processor.py`) haben keine tmp+rename-Atomarität (im Gegensatz zu den beiden anderen etablierten Mustern) | P2 |
| DL-05 | Single-Track-Metadata-Fehler werden zu `DownloadError` und vom Top-Level-Retry bis zu 3x wiederholt — erneuter YouTube-Download für einen nicht-transienten Metadata-Bug | P2 |
| DOC-01 | Playlist- und Single-Ergebnis-Dicts sind bewusst inkonsistent geformt (`playlist_album`/`track_number` nur im Playlist-Pfad gesetzt) — aktuell folgenlos, aber fragil für zukünftigen Code | P3 |

---

## 31. Out-of-Scope Findings (Metadata Quality, nicht bearbeitet)

Keine neuen Metadata-Qualitätsprobleme im Rahmen dieses Audits aktiv gesucht (außerhalb des Scopes). Die bereits in Baseline v5 dokumentierten DEFERRED-Punkte (Loudness-Schritt undokumentiert, Debug-Log-Rauschen, `pylast`-Repr-Risiko) bleiben unverändert bestehen und sind nicht Teil dieser Phase.

---

## Explicit Non-Actions (PHASE 0)

```
[x] Kein Produktionscode geändert
[x] Keine Tests geändert
[x] Keine Mapping-Dateien geändert
[x] Keine Konfiguration geändert
[x] Keine Architekturänderung
[x] Keine P2/P3-Probleme vorsorglich behoben
[x] Kein Commit
[x] Kein Push
[x] Kein PR
```

**Status:** PHASE 0 abgeschlossen. Wartet auf Freigabe für PHASE 1 (Findings priorisieren, Fix-Reihenfolge festlegen) gemäß `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`.
