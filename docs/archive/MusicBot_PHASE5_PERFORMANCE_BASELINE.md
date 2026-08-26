# MusicBot Phase 5 — Performance Baseline

**Datum:** 2026-08-25
**HEAD zu Beginn:** `ea01c62ebba616d8349cb37e70cc711fccfc4dca` (main)
**Vorausgehend:** ENGINEERING BASELINE v3 → PHASE 4 Failure-Path Audit → FINDING-1…6 (alle CLOSED)
**Art dieses Dokuments:** Charakterisierung/Messung. Keine Optimierung, keine Produktionscode-Änderung.

---

## Nachtrag (2026-08-25): FINDING-7 gefixt, verifiziert

Nach Freigabe wurde FINDING-7 behoben — **mit vorheriger Prüfung der
Ausführungsumgebungs-Fragen** (nicht blind `asyncio.to_thread()` eingebaut,
wie explizit gefordert):

| Frage | Ergebnis |
|---|---|
| Benötigte Argumente | `@staticmethod normalize_loudness(filepath: str, target_lufs: float)` — reine Werte, kein `self` |
| Rückgabewert | `bool`, wird durch `await asyncio.to_thread(...)` unverändert durchgereicht |
| Exceptions | Fängt intern alles selbst (`TimeoutExpired`, `Exception`), gibt immer `bool` zurück — raised nie nach außen |
| Gemeinsamer State | Keiner — nur modulweiter `logger` (thread-safe), keine `self.`-Zugriffe im ganzen Modul (verifiziert per Grep) |
| Thread-Safety | `subprocess.run()` ist thread-safe; Temp-Dateiname enthält den eindeutigen Quelldateinamen → keine Kollision zwischen den max. 3 gleichzeitigen Downloads |
| Nachfolgende Verarbeitung | `await` blockiert die Coroutine bis Thread-Ende — Reihenfolge zu Schritt 16 (Move) bleibt garantiert erhalten |

**Fix:** `services/metadata/enhanced_metadata_processor.py:811-817` — Aufruf mit
`await asyncio.to_thread(AudioEnhancer.normalize_loudness, str(original_path),
target_lufs=_target_lufs)` gewrappt, exakt nach dem bereits bewährten Muster von
FINDING-1 (Cover-Blocking).

**Regressionstests** (`tests/test_enhanced_metadata_processor_loudness_blocking.py`,
3 Tests):
1. Deterministischer Beweis, dass `normalize_loudness()` tatsächlich über
   `asyncio.to_thread()` geroutet wird (Patch am Modulpfad, Aufzeichnung).
2. Rückgabewert bleibt bei Fehlschlag korrekt durchgereicht (kein stiller
   Verhaltensunterschied durch das Wrapping).
3. **Der eigentliche Regressionstest für FINDING-7:** Heartbeat-Coroutine läuft
   parallel zu einem kontrollierten `time.sleep(0.3)`-Stand-in für den echten
   FFmpeg-Call — beweist direkt, dass der Event-Loop währenddessen responsiv bleibt.

**`git stash`-Verifikation:** gegen den ungefixten Code schlugen exakt die
erwarteten 2 von 3 Tests fehl — insbesondere der Heartbeat-Test mit
`assert 0 >= 7.5` (0 Ticks während der Blockierung, Event-Loop komplett
eingefroren). Nach `git stash pop` wieder alle 3 grün.

**Empirische Bestätigung mit dem echten FFmpeg-Aufruf** (nicht gemockt, exakter
Aufrufstil wie im Fix): `normalize_loudness()` über `asyncio.to_thread()` gegen den
synthetischen 3-Minuten-Track, 14,73 s Laufzeit — **146 von erwarteten ~147
Heartbeat-Ticks** (100ms-Intervall) liefen während der gesamten realen
FFmpeg-Blockierung normal durch. Die 14,5-s-Blockierung ist damit nachweisbar aus
dem Event-Loop verschwunden — nicht nur laut grüner Test-Suite, sondern direkt
gegen den echten, unveränderten `AudioEnhancer.normalize_loudness()`-Call gemessen.

**Regression:** `pytest tests/ -q` → **1077 passed, 0 failed** (1074 + 3 neue Tests).

Damit ist FINDING-7 CLOSED.

---

## 1. Scope

Diese Phase misst und charakterisiert, wo MusicBot tatsächlich Zeit, CPU, I/O und
Nebenläufigkeit verbraucht — entlang des in Abschnitt 3 definierten Pipeline-Modells.
Ziel ist **kein** "MusicBot schneller machen", sondern eine belegte Antwort auf:
Wo ist eine Kosten meaningful, wo ist sie erwartete externe Latenz, und wo ist sie
irrelevant?

Nicht in Scope: Implementierung von Fixes. Ein gefundenes P0/P1-Item wird hier nur
spezifiziert, nicht behoben (analog zum Vorgehen bei FINDING-4).

---

## 2. Repository State

```
Branch: main
HEAD:   ea01c62ebba616d8349cb37e70cc711fccfc4dca
Status: clean (keine uncommitted changes vor Beginn)
```

**Testverifikation — Diskrepanz und Auflösung:**

Der Auftrag erwartete `1074 passed, 0 failed` für einen bloßen `pytest`-Lauf. Der
tatsächliche Lauf ergab **`7 failed, 1075 passed`**. Untersuchung (`git log`,
`git merge-base --is-ancestor`):

- `pytest tests/ -q` (das in dieser Session seit FINDING-1 durchgängig verwendete
  Verifikationskommando) liefert exakt **`1074 passed, 0 failed`** — die Baseline
  ist damit bestätigt korrekt für den etablierten Scope.
- Der bloße `pytest`-Aufruf über das gesamte Repo sammelt zusätzlich
  `mapping/test_genre_map.py` ein (7 Failures). Diese Datei ist seit dem
  Initial-Commit (`f000cc0`) unverändert und vergleicht
  `GenreMapper.determine_genre()` gegen einen reinen String
  (`assert genre == "Pop"`), obwohl die Funktion bereits seit vor der
  Baseline-v2-Closure (Commit `bc74383`, Vorfahre von `97e11e8`) ein
  `GenreResult`-Dataclass-Objekt zurückgibt. Diese Legacy-Testdatei war also
  bereits vor Beginn dieser Session strukturell inkompatibel zur Implementierung —
  keine Regression aus FINDING-1…6, keine Auswirkung von Mapping-Datenänderungen.
- Zusätzlich erzeugt der volle `pytest`-Lauf eine `PytestCollectionWarning` für
  `handlers/test_menu_handler.py` (Doppel-Collection durch `tests/test_test_menu_handler.py`),
  ebenfalls vorbestehend, keine Auswirkung auf Testergebnisse.

**Schlussfolgerung:** Repository-Zustand verstanden. Die 7 Failures sind ein
orthogonales, bereits vor dieser Session bestehendes Scope-Artefakt (Test läuft nur
mit, wenn `pytest` ohne Pfad-Einschränkung aufgerufen wird) und werden hier nicht
weiterverfolgt — das gehört, falls gewünscht, in eine eigene Korrektur außerhalb von
Phase 5. Für den Rest dieses Dokuments gilt `pytest tests/ -q` → **1074 passed, 0
failed** als verifizierte Baseline.

---

## 3. Methodology

Drei parallele Code-Charakterisierungen (Explore-Agenten, ausschließlich Lesen, mit
Datei:Zeile-Beleg) für Download/Retry, Metadata/externe Clients, Cover/Filesystem/Cache.
Ergänzend lokale, deterministische Benchmarks gegen die **echten Produktionsklassen**
(`utils.metadata_cache.MetadataCache`, `services.metadata.cache.MetadataCacheHandler`,
`utils.audio_enhancer.AudioEnhancer`, `services.metadata.tag_writer.TagWriter`,
`utils.youtube_parser.parse_youtube_title`, `services.metadata.title_cleaner.TitleCleaner`,
`utils.genre_map.GenreMapper`) — mit synthetischen Daten in isolierten tmp-Verzeichnissen,
kein Netzwerk, keine Produktionsdaten/-bibliothek berührt. Filesystem-Move wurde bewusst
gegen die echten Mountpoints `/mnt/128ssd` (DOWNLOAD_DIR) und `/mnt/4tb`
(LIBRARY_DIR) gemessen, aber in isolierten Scratch-Unterordnern, sofort bereinigt.

Externe Services (YouTube/yt-dlp, MusicBrainz, Genius, Last.fm, Fanart, Apple Music,
Deezer) wurden **nicht** live angesprochen — Sicherheitsregel (Abschnitt 29 des
Auftrags). Deren Kosten werden ausschließlich strukturell (Timeout-/Retry-Konfiguration,
Call-Anzahl, sequenziell/parallel) charakterisiert, nicht als Live-Latenzmessung.

---

## 4. Workloads

| Workload | Status |
|---|---|
| W1 Single Track Download | strukturell charakterisiert (Code) |
| W2 Kleine Playlist | strukturell charakterisiert (sequenzielle Schleife bestätigt) |
| W3 Große Playlist (bis MAX_PLAYLIST_ITEMS=50) | strukturell + hochgerechnet (Abschnitt 6) |
| W4 Duplicate/Already-Processed | strukturell charakterisiert (Cache-Check-Platzierung, Abschnitt 13) |
| W5 Metadata-Heavy Track | lokal gemessen (Regex/Parsing, Abschnitt 13) |
| W6 Cover-Heavy Track | strukturell charakterisiert (Abschnitt 14), keine Live-Messung (Sicherheitsregel) |
| W7 Failure/Retry-Pfad | strukturell charakterisiert, exakte Delay-Werte aus Code (Abschnitt 15) |
| W8 Concurrent Downloads | strukturell charakterisiert (Abschnitt 9) |

Es wurden keine Produktionsverteilungen erfunden — wo keine reale Messung möglich
war (externe API-Latenz, echte yt-dlp-Downloadzeit), ist der Wert explizit als
`EXTERNAL` / `NOT MEASURED` markiert, nicht geschätzt.

---

## 5. Single-Track Timing

Ein vollständiger Live-Download+Metadata-Durchlauf wurde **nicht** gemessen
(würde reale YouTube-/MusicBrainz-/Genius-/Cover-API-Aufrufe erfordern —
Sicherheitsregel Abschnitt 29 verbietet unkontrollierte externe Aufrufe im Rahmen
dieses Audits). Stattdessen: Zerlegung nach Stufe, jede Stufe einzeln bewertet
(lokal gemessen wo möglich, sonst strukturell/EXTERNAL):

| Stufe | Wert | Evidenz | Quelle |
|---|---|---|---|
| Telegram-Handling | NOT MEASURED | E0 | — |
| URL-Validierung | NOT MEASURED (kein Live-Test) | E0 | — |
| yt-dlp Download | EXTERNAL (variabel, netzabhängig) | E0 | — |
| MusicBrainz-Call | EXTERNAL, Timeout 30s (`config.py:413`), Cache TTL 3600s | E1 | Agent-Charakterisierung |
| Genius-Call | EXTERNAL, Timeout 10s, 3 Retries mit Exponential-Backoff (2–10s) | E1 | Agent-Charakterisierung |
| Last.fm-Call | EXTERNAL, Timeout 10s, kein Retry | E1 | Agent-Charakterisierung |
| Cover-Fetch (worst case, alle Quellen) | EXTERNAL, bis zu 8 sequenzielle Requests × (8s Timeout + 2 Retries) | E1 | Agent-Charakterisierung |
| **Titel-Parsing (`parse_youtube_title`, 6 realistische Titel)** | **⌀ 1,42 ms (0,24 ms/Titel)** | **E3 (lokal gemessen)** | Abschnitt 13 |
| **Titelbereinigung (`light_title_cleanup`, 6 Titel)** | **⌀ 0,19 ms (0,03 ms/Titel)** | **E3** | Abschnitt 13 |
| **Genre-Bestimmung (`determine_genre`, 5 Artists, In-Memory)** | **⌀ 0,084 ms (0,017 ms/Artist)** | **E3** | Abschnitt 13 |
| **Loudness-Normalisierung (FFmpeg, 3-Min-Track)** | **14,528 s** | **E3 (lokal gemessen, synthetischer Track)** | Abschnitt 8/19, FINDING-7 |
| **Tag-Schreiben (mutagen, m4a)** | **⌀ 2,04 ms (Median 0,92 ms)** | **E3** | Abschnitt 12 |
| **Filesystem-Move (copy2+rename, 8 MB, cross-fs)** | **⌀ 6,07 ms** | **E3** | Abschnitt 11 |
| **video_id_index-Schreiben (1000 Einträge)** | **⌀ 4,10 ms** | **E3** | Abschnitt 12 |
| Telegram-Reporting | NOT MEASURED | E0 | — |

**Kein erfundener Gesamtwert.** Die einzige Stufe mit demonstriertem, signifikantem
MusicBot-eigenem Kostenanteil ist die Loudness-Normalisierung (14,5 s) — alle anderen
lokal gemessenen MusicBot-Stufen liegen im niedrigen einstelligen bis niedrigen
zweistelligen Millisekundenbereich und sind gegenüber externer API-Latenz (Sekunden
bis zweistellige Sekunden im Fehlerfall) vernachlässigbar.

---

## 6. Playlist Scaling

**Strukturell bestätigt (Agent-Charakterisierung, `services/downloader/download_utils.py:494`):**
Playlist-Tracks werden in einer einfachen `for idx, track_info in enumerate(...)`-Schleife
**sequenziell** verarbeitet — kein `asyncio.gather`, kein Semaphore innerhalb der
Playlist-Verarbeitung selbst. Pro Track: ein kombinierter yt-dlp-Call
(`extract_info(..., download=True)`) plus die volle Metadata-Pipeline.

**MAX_PLAYLIST_ITEMS = 50** wird durchgesetzt (`download_utils.py:424-430`,
Listen-Slicing `entries = entries[:max_playlist_items]`) — verhindert unbegrenztes
Wachstum.

**Skalierungscharakter:** strukturell **linear** (kein Hinweis auf superlineares
Wachstum, keine gemeinsame Playlist-weite Initialisierung, die pro Track wiederholt
würde außer dem einen initialen Playlist-`extract_info`-Call). Bestätigt durch die
lokal gemessene Linearität der video_id_index-Schreibkosten (Abschnitt 12: 0,19 ms
bei 10 → 20,0 ms bei 5000 Einträgen, sauber proportional zur Indexgröße).

**Hochrechnung (nicht gemessen, nur strukturelle Konsequenz aus E3-Einzelmessung):**
Bei einer vollen 50-Track-Playlist trägt allein die MusicBot-eigene,
blockierende Loudness-Normalisierung (Abschnitt 8, FINDING-7) strukturell
**50 × ~14,5 s ≈ 12 Minuten kumulative Event-Loop-Blockierung** bei — unabhängig
von externer Download-/API-Latenz, die zusätzlich sequenziell obendrauf kommt.
Diese Hochrechnung ist eine direkte arithmetische Konsequenz aus einer E3-Messung
und der bestätigten sequenziellen Schleife, keine Schätzung eines unbekannten Werts.

---

## 7. External I/O

| Service | Client | Sync/Async | Timeout | Retry | Cache |
|---|---|---|---|---|---|
| YouTube/yt-dlp | `download_executor.py` | sync-in-Executor (`run_in_executor`) | kein `socket_timeout` im genutzten Pfad (`YTDL_BASE_OPTIONS` mit `socket_timeout=30` ist toter Code, kein Aufrufer) | 3 Versuche, exponentiell `2**attempt`s (Abschnitt 15) | — |
| MusicBrainz | `musicbrainzngs` via `asyncio.to_thread` | entkoppelt | 30s (`config.py:413`) | kein aktives Retry im Client (Config-Wert `MUSICBRAINZ_RETRIES=4` ungenutzt) | `TTLCache(200, ttl=3600s)` |
| Genius | `aiohttp` (Scraping) + `lyricsgenius` via `to_thread` | teils echtes async, teils entkoppelt | 10s | 3 Versuche, `wait_exponential(2,10)` (tenacity) | kein separater Cache im Client |
| Last.fm | `pylast` via `to_thread` | entkoppelt | 10s | keins | kein separater Cache im Client |
| Cover-Provider (bis zu 6 Quellen, 8 Requests worst case) | `requests.Session` mit `urllib3.Retry` | **sync, aber gesamte `get_cover_art()` via `to_thread`** (FINDING-1, bereits CLOSED) | 8s/Request | 2/Request, Backoff 0,5 | dateibasiert, MD5-Key |

**Nicht-Finding:** Alle externen synchronen Client-Bibliotheken (`musicbrainzngs`,
`pylast`, `lyricsgenius`, Cover-`requests`) sind konsistent über `asyncio.to_thread`
bzw. bereits per Fix (FINDING-1) vom Event-Loop entkoppelt. Das strukturelle Muster
ist repo-weit einheitlich angewendet — keine Regression, keine Lücke gefunden.

**DOWNLOAD_TIMEOUT (config.py:356, Wert 300)** ist definiert, hat aber **keinen
Aufrufer** im Repo (bestätigt per Grep durch Agent) — strukturell totes Konfigurations-Item,
gleiche Kategorie wie bereits in Phase 1 gefundene tote Configs. Kein aktives
Zeitrisiko dadurch (yt-dlp hat kein explizites Timeout, aber auch keinen bekannten
Hänger-Bugreport in den Logs dieser Session) — als **Beobachtung**, nicht als
P0/P1-Finding erfasst (keine demonstrierte Auswirkung, nur ein ungenutzter Wert).

---

## 8. Event Loop / Blocking Analysis

**Bereits korrekt entkoppelt (verifiziert, Vorbild-Muster):**
- yt-dlp `extract_info` (`download_executor.py:169-186`, `:229-249`) via `run_in_executor`.
- MusicBrainz/Genius/Last.fm-Clients via `asyncio.to_thread`.
- Cover-Pipeline `get_cover_art()` komplett via `asyncio.to_thread`
  (`enhanced_metadata_processor.py:704-712`) — FINDING-1, CLOSED.

**FINDING-7 (NEU) — siehe Detailblock unten:** `AudioEnhancer.normalize_loudness()`
läuft **direkt, synchron, ungewrappt** im Event-Loop-Thread von
`async def process_single_track()`.

**Weitere direkte (nicht-`to_thread`) synchrone Aufrufe im selben `async def`-Kontext,
gemessen und als Nicht-Finding eingestuft (Kosten zu gering für meaningful impact):**
- `filename_fixer.move_to_library()` → `shutil.copy2` (`enhanced_metadata_processor.py:836-845`):
  gemessen ⌀ 2,2–11,8 ms für 3–15 MB, cross-fs wie same-fs (Abschnitt 11). Sub-15ms-Blockierung
  ist gegenüber Sekunden-Latenzen anderer Stufen nicht signifikant.
- `tag_writer.write_tags()` (mutagen): gemessen ⌀ 2,0 ms (Median 0,92 ms) — vernachlässigbar.
- `services/metadata/cache.py::_save_video_id_index()`: gemessen bis 20 ms bei 5000
  Einträgen (Abschnitt 12) — vernachlässigbar bei realistischer Bibliotheksgröße,
  aber siehe Abschnitt 12 für die Wachstumscharakteristik als Beobachtung.

### FINDING-7 — Loudness-Normalisierung blockiert den Event-Loop pro Track für ~14,5 s

| Feld | Wert |
|---|---|
| Severity | **P1 — HIGH** |
| Evidence Level | **E3** (reproduzierbar lokal gemessen + Code direkt verifiziert) |
| Workload | W1 (Single Track), verstärkt bei W3 (Playlist) |
| Messung | `AudioEnhancer.normalize_loudness()` gegen synthetischen 3-Minuten-Track (AAC, 192kbit, 2,9 MB): **14,528 s** Laufzeit, `subprocess.run()` × 2 (Analyse-Pass + Apply-Pass), beide mit `capture_output=True` (blockierend bis Prozessende) |
| Affected Component | `utils/audio_enhancer.py::AudioEnhancer.normalize_loudness()` |
| Exact Code Path | Aufruf `services/metadata/enhanced_metadata_processor.py:811-814` — direkt (kein `asyncio.to_thread`/`run_in_executor`) innerhalb `async def process_single_track` (Zeile 231). Die Methode selbst: `utils/audio_enhancer.py:47-142`, zwei `subprocess.run(..., timeout=60)` (Zeile 81) und `subprocess.run(..., timeout=120)` (Zeile 107/123). |
| Root Cause | `normalize_loudness()` ist als `@staticmethod` mit synchronem `subprocess.run()` implementiert und wird direkt aus einer `async def`-Methode aufgerufen, ohne Executor-Wrapping — im Unterschied zum bereits korrekt behobenen Cover-Pfad (FINDING-1), der exakt dieses Muster für `get_cover_art()` bereits anwendet. |
| User/Operational Impact | Für jeden erfolgreich heruntergeladenen `.m4a`/`.mp4`/`.mp3`-Track (Podcasts nutzen denselben Pfad, andere LUFS) friert der komplette Bot für ~14,5 s ein — alle Telegram-Chats, alle Nutzer, jede Interaktion (auch Status-Abfragen, Abbrüche, neue Befehle) blockiert für diese Zeitspanne. Bei einer 50-Track-Playlist (MAX_PLAYLIST_ITEMS-Cap) kumuliert sich das strukturell auf ~12 Minuten Blockierung, verteilt auf 50 Einzelfreezes. |
| Existing Mitigation | Keine. |
| Why It Is Insufficient | — (keine Mitigation vorhanden) |
| Recommended Fix Scope | Analog zu FINDING-1: Aufrufstelle `enhanced_metadata_processor.py:811-814` mit `await asyncio.to_thread(AudioEnhancer.normalize_loudness, str(original_path), _target_lufs)` wrappen. Kein Eingriff in `audio_enhancer.py` selbst notwendig (bleibt synchron, wie von `to_thread` erwartet). |
| Expected Benefit | Eliminiert die ~14,5-s-Blockierung pro Track vollständig aus dem Event-Loop; Gesamtlaufzeit pro Track bleibt gleich (kein Geschwindigkeitsgewinn), aber der Bot bleibt für andere Nutzer/Chats währenddessen responsiv. |
| Regression Risk | Niedrig — identisches, bereits im Repo bewährtes Muster (FINDING-1). `normalize_loudness()` ist bereits fehlertolerant (try/except/finally, Rückgabewert `bool`), Verhalten bei Erfolg/Fehler ändert sich durch Executor-Wrapping nicht. |
| Verification Method | Test analog zu den FINDING-1-Regressionstests: Zeitmessung/Mock, dass `process_single_track()` während der Normalisierung andere `await`-Punkte im Event-Loop nicht blockiert (z. B. paralleler `asyncio.sleep(0)`-Heartbeat-Test), plus bestehender Erfolg/Fehler-Rückgabewert-Test unverändert grün. |

Dieses Finding wird hier **nur spezifiziert, nicht implementiert** — Fix-Phase
erfordert explizite Freigabe, analog zum Vorgehen bei FINDING-4.

---

## 9. Concurrency

**Korrektur einer veralteten Annahme:** Ein aus einer früheren, nicht abgeschlossenen
Plan-Sitzung stammendes Dokument in diesem Environment ging davon aus,
`MAX_CONCURRENT_DOWNLOADS`/`MAX_PLAYLIST_ITEMS`/`MAX_DURATION` seien tote Config-Werte
und yt-dlp-Calls liefen ungewrappt im Event-Loop. Die frische, mit Datei:Zeile
belegte Prüfung in dieser Phase widerlegt das für den aktuellen HEAD vollständig:

- **`MAX_CONCURRENT_DOWNLOADS = 3`** wird durchgesetzt via Modul-Level
  `asyncio.Semaphore` (`klassen/download_handler.py:96-104`), angewendet in
  `handle_url()` (`async with semaphore:`, Zeile 552-555). Kommentar an Zeile 89-95
  erklärt explizit, warum ein Instanz-Attribut nicht ausreichen würde.
- **`MAX_PLAYLIST_ITEMS = 50`** wird durchgesetzt via Slicing (`download_utils.py:424-430`).
- **`MAX_DURATION = 600`** wird durchgesetzt via yt-dlp `match_filter`
  (`download_executor.py:74-78`, `_build_duration_match_filter` Zeile 104-145,
  mit Podcast-Ausnahme).
- Alle yt-dlp-`extract_info`-Aufrufe laufen über `run_in_executor` (Abschnitt 8).

**Beantwortung der Leitfragen (Abschnitt 9 des Auftrags):**

| Frage | Antwort | Beleg |
|---|---|---|
| Kann ein Nutzer alle Worker belegen? | Nein — globaler Semaphore(3) gilt chat-übergreifend | `download_handler.py:96-104,552-555` |
| Können mehrere Nutzer parallel downloaden? | Ja, bis zu 3 gleichzeitig (global, nicht per-User) | s.o. |
| Ist Concurrency begrenzt? | Ja | s.o. |
| Wo wirkt Backpressure? | `async with semaphore:` blockiert wartende Requests, bis ein Slot frei wird — kein explizites Queueing/Feedback an den Nutzer über Wartezeit (nicht geprüft in diesem Audit, siehe Abschnitt 10) | `download_handler.py:552-555` |
| Kann eine übergroße Playlist zu vielen Tasks führen? | Nein, hart auf 50 Einträge gekappt | `download_utils.py:424-430` |
| Können sich externe Requests mit Concurrency multiplizieren? | Ja, strukturell: bis zu 3 gleichzeitige Tracks × (bis zu 8 Cover-Requests + MB + Genius + Last.fm) — aber jeweils in eigenem `to_thread`, kein gemeinsames Rate-Limiting über die 3 Slots hinweg geprüft | Abschnitt 7 |

**Wichtig für die Bewertung von FINDING-7:** Der Concurrency-Semaphore(3) begrenzt
gleichzeitige **Downloads**, aber die Loudness-Normalisierung blockiert den
**einen gemeinsamen Event-Loop-Thread** des gesamten Prozesses — das betrifft alle
3 Slots gleichermaßen und alle anderen Chats, unabhängig vom Semaphore-Wert. Der
Semaphore mindert dieses Finding nicht.

---

## 10. Queueing

Kein explizites Queueing-System (`asyncio.Queue`) im Downloadpfad gefunden (bestätigt
per Agent-Grep). Wartezeit entsteht implizit durch den blockierenden `async with
semaphore:` in `handle_url()` — ein vierter gleichzeitiger Request wartet, bis einer
der 3 Slots frei wird. Keine Messung der tatsächlichen Wartezeit möglich ohne reale
Downloads (Sicherheitsregel). **NOT MEASURED**, strukturell plausibel vorhanden markiert.

---

## 11. Filesystem

Reale Mountpoint-Verifikation: `/mnt/128ssd` (`/dev/sdb1`, 117G) und `/mnt/4tb`
(`/dev/sde1`, 3,6T) sind bestätigt unterschiedliche Blockgeräte — FINDING-6s
Prämisse (DOWNLOAD_DIR ≠ LIBRARY_DIR Filesystem) war korrekt.

**Lokal gemessen (echte `shutil.copy2`, Produktionscode-Pfad wie in
`move_to_library()`, Abschnitt 3 der Methodik):**

| Dateigröße | Same-FS (128ssd→128ssd) | Cross-FS (128ssd→4tb, wie Produktion) |
|---|---|---|
| 3 MB | ⌀ 2,60 ms | ⌀ 2,21 ms |
| 8 MB | ⌀ 6,16 ms | ⌀ 6,07 ms |
| 15 MB | ⌀ 11,49 ms | ⌀ 11,78 ms |

**Explizites Non-Finding:** Der durch FINDING-6 eingeführte atomare Copy+Rename-Move
ist auf diesem System **nicht** meaningful langsamer als ein hypothetischer
Same-Filesystem-`rename()` gewesen wäre — beide Messreihen liegen im selben
Millisekundenbereich (beide SSDs, keine spürbare Cross-Device-Strafe). Die
Korrektheits-Verbesserung aus FINDING-6 hat keinen messbar negativen
Performance-Effekt. Kein Anlass, den Fix aus Performance-Gründen zu hinterfragen.

---

## 12. Cache / Index

**`utils/metadata_cache.py` (Haupt-Cache):** ein JSON-File pro Track
(`_cache_file()`, MD5(artist::title)-Key, Zeile 100-102), kein monolithischer
RAM-Cache, kein Preload beim Start (`get()` liest lazy pro Key). `store()` schreibt
atomar (tmp+rename) — aber jeweils **nur die eine betroffene Datei**, nicht den
gesamten Cache. Lokal gemessen (echte Klasse, `tempfile`):

| Vorbefüllte Einträge im Cache-Verzeichnis | `store()`-Kosten für einen weiteren Eintrag |
|---|---|
| 10 | ⌀ 0,221 ms |
| 100 | ⌀ 0,189 ms |
| 1000 | ⌀ 0,507 ms (Median 0,251 ms) |

**Nicht-Finding:** `store()` skaliert **nicht** mit der Cache-Gesamtgröße (erwartbar,
da Ein-Datei-pro-Eintrag-Design) — der leichte Anstieg bei 1000 Einträgen liegt im
Bereich von Dateisystem-Rauschen (viele kleine Dateien im selben Verzeichnis), nicht
in einem strukturellen O(n)-Muster.

**`services/metadata/cache.py::_save_video_id_index()` (video_id-Index):**
im Gegensatz zum Haupt-Cache **ein einziges** JSON-File für den kompletten Index,
das bei **jedem** `store()`-Aufruf mit vorhandener `video_id` komplett neu
serialisiert und atomar geschrieben wird (`_save_video_id_index()`, Zeile 36-57,
aufgerufen aus `store()` Zeile 189). Lokal gemessen (echte Klasse):

| Einträge im Index | Datei-Größe | Schreibkosten pro `store()`-Aufruf |
|---|---|---|
| 10 | 692 B | ⌀ 0,194 ms |
| 100 | 7,1 KB | ⌀ 0,565 ms |
| 1000 | 72,8 KB | ⌀ 4,10 ms |
| 5000 | 372,8 KB | ⌀ 20,00 ms |

**Beobachtung (P3, kein akuter Fix-Bedarf):** Dies ist strukturell **O(n)** mit der
Anzahl gecachter Video-IDs — im Gegensatz zum Haupt-Cache. Bei 5000 Tracks kostet
jeder einzelne weitere Cache-Store bereits 20 ms zusätzliche synchrone
Event-Loop-Blockierung (dieser Call läuft, wie in Abschnitt 8 vermerkt, ebenfalls
direkt im `async def`-Kontext). Bei aktueller und mittelfristig absehbarer
Bibliotheksgröße (deutlich unter 5000 Tracks) ist der Effekt nicht meaningful
(20 ms gegenüber der 14,5-s-FINDING-7-Blockierung vernachlässigbar). Wird explizit
**nicht** als eigenständiges FINDING erfasst — False-Positive-Gate: Kosten aktuell zu
gering, kein demonstrierter Nutzerimpact. Für eine zukünftige Prüfung vermerkt, falls
die Library deutlich wächst.

---

## 13. Metadata

Pipeline-Reihenfolge bestätigt (`enhanced_metadata_processor.py::process_single_track`,
Zeile 231-1051): Cache-Check (Schritt 2, Zeile 261) **vor** allen teuren externen
Calls — bei Cache-Hit echter früher Return vor Genre/MusicBrainz/Lyrics/Cover
(Zeile 262-265). Kein unnötiger externer Call bei Cache-Hit.

Reihenfolge danach: Artist → Titel → Genre (inkl. MusicBrainz) → Lyrics (Genius) →
MB-Album-Prefetch → Cover → Album/Jahr → Move → Tags → Cache-Store. Alles sequenziell
awaited, **kein `asyncio.gather`** irgendwo in der Pipeline gefunden (Grep über alle
geprüften Dateien: 0 Treffer).

**Lokal gemessen — Regex-/Parsing-Kosten (echte Produktionsfunktionen, 6 realistische
YouTube-Titel aus den tatsächlich im Repo vorhandenen `import/downloads/*.info.json`-Dateinamen):**

| Funktion | ⌀ Zeit für 6 Titel | Pro Titel |
|---|---|---|
| `parse_youtube_title()` | 1,42 ms | 0,24 ms |
| `TitleCleaner.light_title_cleanup()` | 0,19 ms | 0,03 ms |
| `TitleCleaner.build_search_title()` | 0,26 ms | 0,04 ms |
| `GenreMapper.determine_genre()` (In-Memory nach Singleton-Init) | 0,084 ms/5 Artists | 0,017 ms |

**Explizites Non-Finding:** Trotz der von den Agenten dokumentierten hohen Anzahl an
Regex-Operationen (21+18+30+... Pattern über mehrere Module) ist die tatsächliche
CPU-Zeit pro Track für den gesamten Text-Verarbeitungsanteil (Parsing + Cleanup +
Genre-Matching) **unter 2 ms** — vollständig vernachlässigbar gegenüber jeder
externen API-Latenz oder der FINDING-7-Blockierung. "Viele Regex-Pattern" ist hier
demonstriert **kein** Performance-Problem (Abgleich mit False-Positive-Gate,
Abschnitt 23 des Auftrags: gemessen, aber Impact nicht meaningful).

`GenreMapper` lädt alle YAML-Mapping-Dateien einmalig im Singleton-Konstruktor
(`utils/genre_map.py::_do_init` → `_load_all_mappings`), kein Reload pro Aufruf —
bestätigt korrekt implementiert.

---

## 14. Cover Pipeline

Bereits korrekt vom Event-Loop entkoppelt (FINDING-1, CLOSED, `to_thread`).
Reine Performance-Charakterisierung des jetzt schon korrekten Zustands:

- Bis zu 6 Provider (CAA, Fanart Album, Apple Music, Deezer, Fanart Artist, YouTube
  ×4 Varianten), Priorität-sortiert, **sequenziell** in einer `for`-Schleife
  (`cover_processor.py:211-282`) — trotz Docstring-Hinweis "paralleler Download"
  (Zeile 7) und importiertem, aber ungenutztem `ThreadPoolExecutor` (Zeile 23,89).
- Worst Case: bis zu 8 externe Requests × (8s Timeout + 2 Retries à 0,5s Backoff)
  sequenziell, bevor aufgegeben wird — das findet aber bereits **innerhalb** des
  einen `to_thread`-Worker-Threads statt, blockiert also **nicht** den Haupt-Event-Loop
  für andere Chats, verlängert aber die Verarbeitungszeit dieses einen Tracks.
- Bildanalyse (`_analyze_image_quality`, PIL + numpy-Gradient) dient nur der
  Score-Berechnung, kein Resize/Save — `_TARGET_SIZE=1200` ist deklariert, aber im
  gesamten Modul nirgends referenziert (totes Konfigurationsfeld, gleiche Kategorie
  wie andere in dieser Session gefundene tote Configs).
- Cover-Cache: dateibasiert (MD5-Key), Hit-Pfad liest nur von Platte (kein HTTP).
  Miss-Pfad schreibt **nicht atomar** (`open(path,"wb")` direkt) — im Gegensatz zum
  längst korrigierten Muster bei Metadata-Cache/video_id_index/Library-Move. Das ist
  strukturell dieselbe Kategorie wie FINDING-5, aber hier nicht als eigenständiges
  Finding vertieft (Cover-Cache-Dateien sind reine Bytes, bei Korruption einfach neu
  heruntergeladen — geringerer Blast-Radius als der video_id_index/Move-Fall). Wird
  als **Beobachtung** für eine mögliche künftige Korrektur vermerkt, nicht als
  P0–P3-Performance-Finding (das wäre ein Correctness-, kein Performance-Thema).

**Beobachtung, kein Finding (sequenziell statt parallel trotz Docstring):**
Da die gesamte Kette bereits in einem einzelnen Hintergrund-Thread läuft und Cover
Art Archive (Prio 100) in der Praxis meist zuerst erfolgreich matcht, ist der
Unterschied zwischen sequenziellem und parallelem Provider-Abfragen nur im
Worst-Case (alle Quellen scheitern) spürbar — dafür liegt keine E2/E3-Messung vor
(würde Live-API-Aufrufe erfordern, gegen Sicherheitsregel). Als **NOT MEASURED /
Docstring-Code-Diskrepanz** vermerkt, kein Fix-Vorschlag.

---

## 15. Retry Performance

**`enhanced_download_with_retry()`** (`services/downloader/download_utils.py:224-387`):
`max_retries=3` (Default, Zeile 229), Schleife `for attempt in range(max_retries)`
(Zeile 283). Delay bei Fehler: `await asyncio.sleep(2**attempt)` (Zeile 369, 382) —
**exponentiell, hart codiert**. Bei vollständigem Scheitern (3 Versuche): Sleeps nach
Versuch 1 und 2 (`2**0=1s`, `2**1=2s`), letzter Versuch bricht ohne weiteren Sleep ab
→ **3 s kumulative Sleep-Zeit** (reine Wartezeit, exklusive der eigentlichen
yt-dlp-Laufzeit pro Versuch, die EXTERNAL/variabel ist).

Separates, unabhängiges Retry in `download_single_track()`: `max_retries=1` (Default,
Zeile 198) — bei diesem Default findet de facto **kein** Retry statt, da der einzige
Aufrufer (`download_utils.py:538-543`) keinen abweichenden Wert übergibt.

**Nicht-Finding:** 3 s kumulative Sleep-Zeit im Worst-Case-Retry-Pfad ist gegenüber
jeder realistischen yt-dlp- oder externen API-Latenz nicht meaningful. Keine
Empfehlung, Retry-Anzahl oder Backoff aus Performance-Gründen zu reduzieren
(Reliability-Anforderung bleibt unangetastet, wie vom Auftrag Abschnitt 16 gefordert).

---

## 16. Memory

**NOT MEASURED.** Eine belastbare Memory-Charakterisierung (RSS-Baseline, Peak,
Wachstum über mehrere Downloads) würde entweder echte Downloads über mehrere Minuten
(gegen Sicherheitsregel, Abschnitt 29) oder einen laufenden Produktionsprozess
erfordern, der in diesem Audit nicht gestartet wurde. Aus der Code-Charakterisierung
ergibt sich kein Hinweis auf unbegrenzt wachsende In-Memory-Collections im
Downloadpfad (Playlist-Cap bei 50, kein Akkumulieren über mehrere Playlists hinweg
in gemeinsamem State gefunden) — das ist aber eine strukturelle Beobachtung, **keine
Messung**, und wird entsprechend nicht als Non-Finding mit Evidenzgrad deklariert.

---

## 17. CPU

Einzige demonstriert CPU-intensive Stufe: **FFmpeg Loudness-Normalisierung**
(2 volle Encode/Decode-Pässe pro Track, siehe FINDING-7) — 14,5 s Wandzeit für einen
3-Minuten-Track auf diesem 4-Core-System. Alle anderen lokal gemessenen Stufen
(Regex-Parsing, Genre-Matching, JSON-Serialisierung, mutagen-Tag-Writing) liegen im
Sub-20-ms-Bereich und sind nicht CPU-limitierend.

---

## 18. Baseline Metrics

| Metric | Baseline |
|---|---|
| Single-track total latency | NOT MEASURED (externe Anteile dominieren, Sicherheitsregel) |
| Download latency | EXTERNAL |
| Metadata-Textverarbeitung (Parsing+Cleanup+Genre) | **< 2 ms** (E3) |
| MusicBrainz/Genius/Last.fm | EXTERNAL, Timeouts 10–30s |
| Cover-Fetch | EXTERNAL (worst case bis 8× (8s+Retries), off-event-loop) |
| Loudness-Normalisierung | **14,528 s** (E3, blockierend, FINDING-7) |
| Tag-Schreiben (mutagen) | **⌀ 2,0 ms** (E3) |
| Filesystem-Move (8 MB, cross-fs) | **⌀ 6,07 ms** (E3) |
| Cache/index write (Haupt-Cache) | **⌀ 0,2–0,5 ms**, unabhängig von Cache-Größe (E3) |
| Cache/index write (video_id_index) | **⌀ 0,2–20 ms**, linear mit Index-Größe (E3) |
| Playlist throughput | strukturell linear (E1, arithmetisch aus E3-Einzelwerten hochgerechnet) |
| Maximum concurrency | **3 gleichzeitige Downloads** (durchgesetzt, `asyncio.Semaphore`) |
| Peak memory | NOT MEASURED |
| CPU-heavy stage | **FFmpeg Loudness-Normalisierung** (einzige demonstrierte) |

---

## 19. Performance Findings

Nur **ein** Finding erreicht die Schwelle aus dem False-Positive-Gate (Abschnitt 23
des Auftrags: gemessen, reproduzierbar, realistischer Workload, MusicBot-verursacht,
auf dem kritischen Pfad, meaningful Impact, keine bestehende Mitigation):

- **FINDING-7** — Loudness-Normalisierung blockiert den Event-Loop ~14,5 s pro
  Track (Details siehe Abschnitt 8). **P1 — HIGH.**

Alle anderen geprüften Kandidaten (video_id_index-Wachstum, Cover-Cache
Nicht-Atomarität, totes `DOWNLOAD_TIMEOUT`/`_TARGET_SIZE`, sequenzielle statt
parallele Cover-Provider-Abfrage) wurden geprüft und **nicht** als Finding
klassifiziert — Begründung jeweils in Abschnitt 20.

---

## 20. Explicit Non-Findings

1. **Metadata-Textverarbeitung (Regex/Parsing/Genre-Matching):** < 2 ms/Track
   gemessen trotz hoher Pattern-Anzahl — kein Performance-Problem.
2. **Haupt-Metadata-Cache (`utils/metadata_cache.py`):** `store()`-Kosten skalieren
   nicht mit Cache-Gesamtgröße (Ein-Datei-pro-Eintrag-Design) — kein Finding.
3. **Cross-Filesystem-Copy (FINDING-6-Fix):** messbar, aber nicht meaningful
   langsamer als Same-Filesystem-Copy auf diesem System (beide SSD-Klasse) —
   Correctness-Fix hat keinen relevanten Performance-Preis.
4. **video_id_index-Schreibkosten:** linear wachsend, aber bei aktueller/mittelfristiger
   Bibliotheksgröße (< 5000 Tracks) mit max. ~20 ms nicht meaningful. Beobachtung für
   künftiges Wachstum vermerkt, kein aktuelles Finding.
5. **MusicBrainz/Genius/Last.fm-Clients:** alle korrekt via `asyncio.to_thread` vom
   Event-Loop entkoppelt — bestätigt konsistent umgesetzt, keine Lücke gefunden.
6. **Concurrency-/Ressourcen-Limits (`MAX_CONCURRENT_DOWNLOADS`,
   `MAX_PLAYLIST_ITEMS`, `MAX_DURATION`):** entgegen einer veralteten Annahme aus
   einer früheren, nicht abgeschlossenen Planungs-Sitzung sind alle drei tatsächlich
   durchgesetzt (Abschnitt 9) — kein Finding, keine weitere Aktion nötig.
7. **Retry-Backoff (3 s Worst-Case-Sleep):** vernachlässigbar gegenüber externer
   Latenz, keine Empfehlung zur Reduktion (Reliability geht vor).
8. **Filesystem-Move und Tag-Writing sind synchron im Event-Loop, aber unter 20 ms** —
   bewusst nicht als Finding erfasst trotz technisch fehlendem Executor-Wrapping,
   da der demonstrierte Impact die Meaningful-Schwelle nicht erreicht (im Gegensatz
   zu FINDING-7).

---

## 21. Recommended Optimizations

Gemäß Abschnitt 24 des Auftrags („No Premature Optimization") wird hier **nur** eine
Empfehlung ausgesprochen, die direkt aus einem gemessenen Problem folgt:

> **FINDING-7 beheben:** `enhanced_metadata_processor.py:811-814` mit
> `await asyncio.to_thread(...)` wrappen — identisches, bereits bewährtes Muster wie
> FINDING-1. Erwarteter Nutzen: Bot bleibt während Loudness-Normalisierung für andere
> Chats responsiv; keine Änderung der Gesamtverarbeitungszeit pro Track.

Keine weiteren Optimierungsempfehlungen (Caching, Batching, Parallelisierung,
Worker-Pools, Architektur-Refactoring) — kein gemessener Befund rechtfertigt das
aktuell.

---

## 22. Verification Plan

Für eine spätere, separat freizugebende Fix-Phase zu FINDING-7:

1. Regressionstest, der beweist, dass `process_single_track()` während der
   (gemockten, kurz gehaltenen) Normalisierungsphase andere Event-Loop-Tasks nicht
   blockiert (Beobachtbares Verhalten, nicht Implementierungsdetail — konsistent mit
   dem in FINDING-4 etablierten Testprinzip).
2. Bestehendes Erfolg-/Fehlerverhalten von `normalize_loudness()` (Rückgabewert
   `bool`, Timeout-Handling, Cleanup der `.tmp`-Datei) muss nach dem Fix unverändert
   grün bleiben — vorhandene Tests (falls vorhanden) bzw. neue Characterization-Tests
   vor dem Fix.
3. `git stash`-Verifikation (etabliertes Vorgehen dieser Session): neuer Test muss
   gegen den ungefixten Code fehlschlagen.
4. Volle Regression (`pytest tests/ -q`) muss weiterhin grün bleiben.

---

## Selbst-Check (Abschnitt 32 des Auftrags)

- [x] HEAD erfasst (`ea01c62e`)
- [x] Testbaseline verifiziert (`pytest tests/ -q` → 1074/0; Diskrepanz zum
      bloßen `pytest` untersucht und erklärt)
- [x] Keine Produktionscode-Änderung
- [x] Keine Test-Änderung
- [x] Workloads definiert
- [x] Single-Track-Latenz stufenweise charakterisiert
- [x] Playlist-Skalierung charakterisiert (strukturell + Hochrechnung)
- [x] External I/O charakterisiert
- [x] Event-Loop-Verhalten geprüft (1 Finding: FINDING-7)
- [x] Concurrency charakterisiert (veraltete Annahme widerlegt)
- [x] Queueing betrachtet (NOT MEASURED, strukturell vermerkt)
- [x] Filesystem charakterisiert (real gemessen, cross-fs vs. same-fs)
- [x] Cache/Index charakterisiert (2 unterschiedliche Skalierungscharaktere gefunden)
- [x] Metadata charakterisiert (Regex-Kosten widerlegt als Problem)
- [x] Cover-Pipeline charakterisiert (bereits korrekt, 1 Beobachtung ohne Finding-Status)
- [x] Retry-Kosten charakterisiert (nicht meaningful)
- [x] Memory betrachtet (NOT MEASURED, explizit so deklariert)
- [x] CPU betrachtet (FFmpeg als einzige demonstrierte Last)
- [x] FINDING-1…6-Fixes auf Performance-Regression geprüft (FINDING-6: kein
      relevanter Effekt; FINDING-5 video_id_index-Wachstum separat als Beobachtung
      vermerkt, keine Regression durch den Fix selbst — der Fix änderte nur
      write-Semantik, nicht die O(n)-Charakteristik, die bereits vorher bestand)
- [x] Messungen unterscheiden extern vs. MusicBot-verursacht
- [x] Findings mit reproduzierbarer Evidenz (E3 für alle numerischen Werte)
- [x] False Positives eliminiert (8 Kandidaten geprüft, 7 als Non-Finding klassifiziert)
- [x] Non-Findings dokumentiert (Abschnitt 20)
- [x] Keine vorschnelle Optimierung (nur 1 Empfehlung, direkt aus 1 Finding)
- [x] Keine v4-Baseline erstellt
- [x] Git diff enthält ausschließlich dieses Dokument

---

## Definition of Done — Beantwortung der 11 Leitfragen (Abschnitt 33)

1. **Wo verbringt MusicBot tatsächlich Zeit?** Dominant: externe API-/Download-Latenz
   (nicht gemessen, außerhalb Kontrolle) und die FFmpeg-Loudness-Normalisierung
   (14,5 s/Track, gemessen, im Kontrolle von MusicBot).
2. **Welche Kosten sind extern/unvermeidbar?** yt-dlp-Download, MusicBrainz, Genius,
   Last.fm, Cover-Provider-Requests.
3. **Welche Kosten verursacht MusicBot selbst?** FFmpeg-Normalisierung (groß,
   FINDING-7), Filesystem-Move/Tag-Write/Cache-Writes (klein, keine Findings).
4. **Wo begrenzt Concurrency den Durchsatz?** `asyncio.Semaphore(3)` global — bewusst
   und korrekt konfiguriert, kein gemessenes Problem.
5. **Wo beeinflusst synchrone Arbeit die async-Ausführung?** FINDING-7 (groß, 14,5 s),
   drei kleinere Stellen unter 20 ms (kein Finding).
6. **Skaliert Playlist-Verarbeitung akzeptabel?** Strukturell linear, durch
   `MAX_PLAYLIST_ITEMS=50` gedeckelt — aber jeder zusätzliche Track addiert
   strukturell ~14,5 s garantierte Blockierung on top (FINDING-7-Konsequenz).
7. **Bleibt Memory stabil?** NOT MEASURED — keine Aussage möglich.
8. **Sind Filesystem-/Cache-Operationen meaningful Bottlenecks?** Nein (alle < 20 ms,
   mit einer vermerkten Wachstumsbeobachtung beim video_id_index).
9. **Haben FINDING-1…6 messbare Performance-Regressionen eingeführt?** Nein
   (FINDING-6 explizit gemessen und verglichen, kein relevanter Effekt).
10. **Welche Performance-Probleme rechtfertigen Engineering-Arbeit?** Nur FINDING-7.
11. **Welche scheinbaren Probleme sind es nicht wert?** Die 8 in Abschnitt 20
    gelisteten Non-Findings.

**Ergebnis:** Ein gemessenes, signifikantes, mit demselben bereits bewährten Muster
behebbares Finding (FINDING-7). Alle übrigen geprüften Bereiche sind entweder bereits
korrekt (Concurrency-Limits, externe Client-Entkopplung, FINDING-1-Fix) oder liegen
gemessen unterhalb einer meaningful-Schwelle. Kein Grund, weitere Optimierungsarbeit
ohne zusätzliche Messung zu beginnen.

---

## Technical Freeze Point — Phase 5

**Status:** 🟢 TECHNICAL FREEZE

**Commit:** `b26166d`

**Verified Regression:**
- `pytest tests/ -q`
- **1077 passed**
- **0 failed**

### Closed Findings

- FINDING-1 — COVER-BLOCKING
- FINDING-2 — PARTIAL-FAILURE-LIBRARY
- FINDING-3 — NAVIDROME-PASSWORD-LOG-LEAK
- FINDING-4 — DOWNLOAD FAILURE REPORTING
- FINDING-5 — VIDEO-ID-INDEX ATOMIC PERSISTENCE
- FINDING-6 — CROSS-FILESYSTEM LIBRARY FINALIZATION
- FINDING-7 — AUDIO NORMALIZATION EVENT-LOOP BLOCKING

### Freeze Meaning

This commit represents the verified technical state after completion
of the Post-Baseline Triage, Failure-Path Audit and Performance
Baseline phases.

At this point:

- all seven findings from this engineering cycle are closed;
- the full regression suite passes with 1077/1077 tests;
- the performance finding has been empirically verified after fixing;
- no open findings from the completed audit cycle remain;
- the repository is considered technically stable;
- `b26166d` is the controlled starting point for the Architecture
  Evolution phase.

### Important

This is a **Technical Freeze Point**, not an Engineering Baseline.

`MusicBot_ENGINEERING_BASELINE_v4.md` MUST NOT be created from this
state yet.

The next phase is:

**FORENSIC ARCHITECTURE DECISION & EVOLUTION AUDIT**

Architecture changes, if any, must be analyzed and explicitly
approved before implementation.

Only after approved architecture evolution has been implemented,
regression-tested and verified will the repository receive the
**Engineering Baseline v4** freeze.
