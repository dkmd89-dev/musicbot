# MusicBot — Download Pipeline Stability Phase — PHASE 2C: DL-02 Audit

> Strikt read-only Analyse gemäß Auftrag PHASE 2C. Basis:
> `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`,
> `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md`. Aufbauend auf
> Commit `754979d` (DUP-01+DUP-08). **Keine Codeänderungen in dieser Phase.**
> Zusätzlich zur reinen Repository-Analyse wurde der installierte
> `yt-dlp`-Quellcode (`/home/robin/python/lib/python3.12/site-packages/yt_dlp/`)
> direkt inspiziert, um die Root Cause nicht zu vermuten, sondern zu belegen
> — analog zur bereits in AE-11 etablierten Methodik (mutagen-Quellcode-Prüfung
> statt Annahme).

---

## 1. Executive Summary

DL-02 ist bestätigt: `services/downloader/download_utils.py::_process_single_download()`
importiert `cleanup_single_download_artifact()` nicht und ruft es auch sonst
nirgends im Fehlerpfad auf. Anders als zunächst vermutet ist die Root Cause
aber **nicht** primär "Cleanup-Aufruf fehlt", sondern **"kein sicher
bekannter Pfad ist zum Zeitpunkt des Fehlers verfügbar"**: wenn der
FFmpeg-Postprocessing-Schritt fehlschlägt, wirft yt-dlp die Exception
**bevor** es der aufrufenden Python-Ebene irgendein `download_info`-Dict
zurückgibt — beide vorhandenen Datei-Lokalisierungsstrategien
(`find_downloaded_file()`) benötigen genau dieses Dict und sind in diesem
Fehlerfall grundsätzlich nicht anwendbar.

Durch direkte Quellcode-Prüfung von `yt_dlp/postprocessor/ffmpeg.py` konnte
jedoch ein sicherer, eindeutiger Mechanismus identifiziert werden: yt-dlps
eigene `progress_hooks` liefern den exakten Pfad der rohen (noch nicht
konvertierten) heruntergeladenen Datei bereits **bevor** die
FFmpeg-Postprocessing beginnt — unabhängig davon, ob diese später erfolgreich
ist oder fehlschlägt. Damit existiert eine belastbare, eindeutige
Dateizuordnung, ohne raten oder breite Muster verwenden zu müssen.

Ein sicherer minimaler Fix ist möglich, erfordert aber (anders als
ursprünglich angenommen) **mehr als nur einen Cleanup-Aufruf im
`except`-Block** — er benötigt einen `progress_hook`, der den bekannten
Pfad VOR dem eigentlichen yt-dlp-Aufruf einhängt.

---

## 2. Exakte Root Cause

`_process_single_download()` (`services/downloader/download_utils.py:769-916`)
umschließt sowohl den Download-Aufruf als auch die Metadatenverarbeitung in
einem einzigen `try`/`except Exception as e: raise DownloadError(...)`
(Zeilen 808-915). Es gibt **keinen** `finally`-Block und **keinen** Import
von `cleanup_single_download_artifact` in dieser Datei (verifiziert per
Grep: kein Treffer).

Der eigentliche Grund, warum das *nicht* trivial nachrüstbar ist:

1. `download_info = await enhanced_processor.download_executor.extract_info_async(url, ydl_opts, download=True)` (Zeile 809) — schlägt dieser Aufruf fehl (Netzwerk, yt-dlp-Extraktionsfehler, **FFmpeg-Postprocessing-Fehler**), wird `download_info` **nie zugewiesen** — die Zeile selbst wirft.
2. `find_downloaded_file()` (`download_executor.py:290-345`) — beide Strategien (`requested_downloads[0]["filepath"]` bzw. Template-Rekonstruktion aus `download_info.get("title"/"ext"/"id")`) benötigen zwingend das `download_info`-Dict. Ohne dieses Dict ist **keine** der beiden bestehenden Strategien anwendbar.
3. Damit ist die bereits existierende, wiederverwendbare Funktion `cleanup_single_download_artifact(original_path, download_dir, logger)` zwar technisch einsetzbar (sie erwartet nur einen `Path`), aber es fehlt an einer sicheren Methode, **diesen Pfad überhaupt zu ermitteln**, wenn `extract_info_async()` selbst wirft.

---

## 3. Tatsächlicher Download-/Fehler-Datenfluss

Direkt im aktuellen Code nachvollzogen (`download_executor.py`, `download_utils.py`, sowie `yt_dlp/YoutubeDL.py`/`yt_dlp/postprocessor/ffmpeg.py`):

```text
_process_single_download()
    ↓
extract_info_async(url, ydl_opts, download=True)
    ↓ (run_in_executor)
yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True)
    ↓
[1] Formatauswahl + Download der Rohdatei (z.B. Song.webm)
    ↓ yt-dlp intern: progress_hook({'filename': <Rohdatei>, 'status':'finished'})
    ↓
[2] run_all_pps('video', info) → FFmpegExtractAudioPP.run(info)
    │   path = information['filepath']            # = Rohdatei, z.B. Song.webm
    │   temp_path = prepend_extension(path,'temp') # z.B. Song.temp.webm  (oder analog)
    │   self.run_ffmpeg(path, temp_path, ...)      # FFmpeg-Subprocess
    │       ├── SUCCESS:
    │       │     os.replace(path, orig_path)      # Rohdatei -> .orig
    │       │     os.replace(temp_path, new_path)  # temp -> finale Datei (z.B. Song.m4a)
    │       │     → download_info wird an extract_info_async() zurückgegeben
    │       │
    │       └── FAILURE (returncode != 0):
    │             raise FFmpegPostProcessorError(...)
    │             → gefangen in FFmpegExtractAudioPP.run_ffmpeg(),
    │               re-raised als PostProcessingError
    │             → NICHT gefangen in run_pp() (ignoreerrors=False in
    │               build_ydl_opts()) → raise
    │             → propagiert durch extract_info() nach oben
    │             → extract_info_async() wirft
    │             → _process_single_download()s except Exception (Zeile 913)
    │               fängt es, wirft DownloadError weiter
    │
    │   WICHTIG: os.replace(path, orig_path) UND os.replace(temp_path, new_path)
    │   werden NIE erreicht, wenn self.run_ffmpeg(...) wirft - path (Rohdatei)
    │   bleibt an seinem URSPRÜNGLICHEN Ort liegen, temp_path KANN als
    │   unvollständige FFmpeg-Teilausgabe existieren (abhängig davon, wie weit
    │   FFmpeg selbst gekommen ist, bevor es fehlschlug).
    ↓
enhanced_processor.session_stats["failed_downloads"] += 1
raise DownloadError(f"Single-Download fehlgeschlagen: {e}")
```

Quellcode-Beleg (`yt_dlp/postprocessor/ffmpeg.py`, `FFmpegExtractAudioPP.run()`):
```python
temp_path = new_path = replace_extension(path, extension, information['ext'])
if new_path == path:
    orig_path = prepend_extension(path, 'orig')
    temp_path = prepend_extension(path, 'temp')
...
self.run_ffmpeg(path, temp_path, acodec, more_opts)   # <- wirft PostProcessingError bei Fehler
os.replace(path, orig_path)                            # <- NIE erreicht bei Fehler
os.replace(temp_path, new_path)                        # <- NIE erreicht bei Fehler
```

Und in `YoutubeDL.run_pp()`:
```python
files_to_delete = []
try:
    files_to_delete, infodict = pp.run(infodict)
except PostProcessingError as e:
    if self.params.get('ignoreerrors') is True:
        self.report_error(e); return infodict
    raise   # <- build_ydl_opts() setzt ignoreerrors=False -> immer dieser Zweig
```

→ yt-dlp selbst führt **kein eigenes Cleanup** der Rohdatei durch, wenn der
Postprocessing-Schritt fehlschlägt (`_delete_downloaded_files()` wird nur
erreicht, wenn `pp.run()` erfolgreich zurückkehrt).

---

## 4. Temporäre/intermediäre Dateien

| Datei | Entsteht durch | Zustand bei FFmpeg-Fehler | Eindeutig zuordenbar? |
|---|---|---|---|
| Rohe Downloaddatei (`path`, z. B. `Song.webm`) | yt-dlp Downloader (vor Postprocessing) | Bleibt unverändert an ihrem Ort liegen (kein `os.replace` erreicht) | **JA** — via `progress_hooks`-Callback mit `status='finished'` deterministisch bekannt (siehe Abschnitt 7) |
| FFmpeg-Temp-Ausgabe (`temp_path`, z. B. `Song.temp.webm`/analog per `prepend_extension`) | `FFmpegExtractAudioPP.run_ffmpeg()` | Kann als unvollständige Teilausgabe existieren, abhängig vom FFmpeg-Fehlerzeitpunkt | **JA, ableitbar** — `temp_path` ist eine deterministische Funktion von `path` (`prepend_extension(path, 'temp')`, dieselbe yt-dlp-Utility-Funktion, nicht neu erfunden) |
| `.part`/`.ytdl` (Downloader-eigene Partial-Marker) | yt-dlp Downloader bei Netzwerkabbruch VOR vollständigem Rohdatei-Download | Kann liegen bleiben | Bereits bewusst außerhalb des Scopes (DL-04, DEFER, siehe Abschnitt 12) |
| `.info.json` | yt-dlp (`writeinfojson: True`) | Wird i. d. R. VOR dem Postprocessing-Schritt geschrieben, bleibt bei einem Postprocessing-Fehler liegen | **JA** — Standard-Namenskonvention (`<Basisname>.info.json`), bereits von `cleanup_single_download_artifact()` mitbehandelt |
| Finale Zieldatei (`new_path`, z. B. `Song.m4a`) | Nur bei ERFOLG | Existiert bei einem Postprocessing-Fehler **nicht** — kein Risiko, sie fälschlich zu löschen | n/a |

**Was bedeutet "temporär" konkret in dieser Pipeline?** Es gibt keinen
dedizierten Temp-Ordner und kein `tempfile`/`TemporaryDirectory` — alle
Artefakte landen direkt in `Config.DOWNLOAD_DIR`, unterscheidbar nur durch
Dateinamen-Konvention (Endung, `.temp`-Infix, `.info.json`-Suffix).

---

## 5. Bestehende Cleanup-Mechanismen

Repositoryweite Suche (Grep nach `unlink`, `os.remove`, `TemporaryDirectory`,
`tempfile`) bestätigt genau zwei relevante, bereits vorhandene Mechanismen
(beide bereits aus Phase 0 bekannt, hier erneut am aktuellen Code
verifiziert):

- `services/downloader/download_artifact_cleanup.py::cleanup_single_download_artifact(original_path, download_dir, logger)` — Strategie C, punktgenauer Cleanup EINER bekannten Datei + zugehöriger `.info.json`. Sicherheitsregeln bereits vorhanden: No-op bei `None`, No-op wenn Datei nicht existiert, No-op wenn Datei außerhalb `download_dir` liegt (`_is_within_directory()`), Fehler beim Löschen werden nur geloggt, nie weitergereicht. **Aktuell aufgerufen ausschließlich aus** `enhanced_metadata_processor.py:1065` (Metadatenverarbeitungs-Fehlerpfad, NICHT der hier betrachtete yt-dlp/FFmpeg-Fehlerpfad).
- `services/downloader/download_artifact_cleanup.py::cleanup_download_artifacts(download_dir, logger, max_age_hours=24.0)` — Strategie A, konservativer Sweep beim Bot-Start (`bot.py:446`, vor `start_polling()`), nur bekannte Endungen, `.part`/`.ytdl` bewusst ausgenommen.

**Warum sie DL-02 aktuell nicht ausreichend lösen:** Strategie C wird im
betrachteten Fehlerpfad nie aufgerufen (kein Import, kein Call-Site in
`download_utils.py`). Strategie A greift zwar irgendwann (nach bis zu 24h),
ist aber kein Ersatz für sofortiges, gezieltes Cleanup und deckt nur Dateien
mit bekannten, in `_KNOWN_ARTIFACT_SUFFIXES` gelisteten Endungen ab — eine
`.temp`-Zwischendatei mit ungewöhnlicher Doppel-Endung (z. B.
`Song.temp.webm`) ist davon **nicht notwendig erfasst**, je nach exakter
`prepend_extension()`-Namensbildung.

Keine neue Cleanup-Abstraktion nötig — `cleanup_single_download_artifact()`
ist für den Rohdatei-Fall direkt wiederverwendbar, sobald ein sicherer Pfad
vorliegt.

---

## 6. Sicherheits-/Concurrency-Analyse

**Gibt es einen eindeutigen erwarteten Pfad?** Nicht *vorab* (das
`outtmpl` = `DOWNLOAD_DIR/"%(title)s.%(ext)s"` enthält unaufgelöste
Platzhalter). Aber *zur Laufzeit*, sobald yt-dlp den Download tatsächlich
beginnt, ist der Pfad exakt bekannt — und zwar **beweisbar**, nicht geraten,
über einen `progress_hooks`-Callback (siehe Quellcode-Beleg unten).

**Kann yt-dlp den Dateinamen verändern?** Ja (abhängig vom tatsächlich
gewählten Format/Codec) — genau deshalb ist Raten (Template-Rekonstruktion
ohne `download_info`) unsicher, ein `progress_hooks`-Callback dagegen nicht,
da er den von yt-dlp selbst **tatsächlich verwendeten** Namen liefert.

**Können mehrere Downloads gleichzeitig laufen?** Ja — `klassen/download_handler.py`
begrenzt gleichzeitige Downloads nur über ein Semaphore
(`_download_semaphore`, Default `MAX_CONCURRENT_DOWNLOADS=3`, siehe
`_get_download_semaphore()`), erlaubt also bis zu 3 parallele Single-Downloads.

**Können zwei Downloads ähnliche/identische Dateinamen besitzen?** Ja,
theoretisch — `build_ydl_opts()`s `outtmpl` für Single-Downloads ist
`"%(title)s.%(ext)s"`, **ohne** eindeutigen Suffix (anders als der
Playlist-Pfad, der `Track_{idx:02d}_{id}.%(ext)s` verwendet, siehe
`download_executor.py:222-225`). Zwei gleichzeitige Single-Downloads mit
identischem Video-Titel **könnten** kollidieren. **Das ist ein
vorbestehendes Charakteristikum der Pipeline, nicht durch einen DL-02-Fix
verursacht oder verschlimmert** — es existiert bereits heute unabhängig von
jeglichem Cleanup (yt-dlps eigenes `overwrites`-Standardverhalten wäre
bereits ohne jeden Cleanup-Fix betroffen). Ein `progress_hooks`-Callback
selbst führt **keine neue Race Condition** ein: jeder `yt_dlp.YoutubeDL(...)`-Aufruf
erzeugt eine eigene Instanz mit eigenem `ydl_opts`-Dict und damit einem
eigenen, in einem Funktions-Closure gebundenen Hook — der erfasste Pfad
gehört nachweisbar zu genau diesem einen Aufruf, nicht zu einem fremden
parallelen Download. Das Risiko, das bestehen bleibt, ist ausschließlich das
vorbestehende `outtmpl`-Kollisionsrisiko selbst (zwei Downloads schreiben
faktisch in dieselbe Datei) — das liegt außerhalb des DL-02-Scopes (würde
eine `outtmpl`-Eindeutigkeits-Änderung erfordern, keine Cleanup-Frage).

**Kann ein Fehler nach Erstellung der finalen Datei auftreten?** Nein, laut
Quellcode-Beleg nicht für den FFmpeg-Postprocessing-Fehlerfall — `new_path`
wird ausschließlich nach erfolgreichem `run_ffmpeg()`-Aufruf erzeugt (siehe
Abschnitt 3). Ein Fehler NACH erfolgreicher finaler Datei würde bedeuten,
dass `extract_info_async()` selbst gar nicht mehr wirft (Rückgabe an
`_process_single_download()` erfolgt) — dieser Fall ist kein DL-02-Fall
mehr, sondern gehört zu späteren Pipeline-Schritten (Metadatenverarbeitung,
bereits durch die bestehende Strategie-C-Cleanup abgedeckt, oder DL-01
[Cancellation], NICHT hier vorweggenommen).

**Quellcode-Beleg für den `progress_hooks`-Mechanismus**
(`yt_dlp/downloader/common.py`, Zeilen 449-453):
```python
self._hook_progress({
    'filename': filename,
    'status': 'finished',
    'total_bytes': os.path.getsize(filename),
}, info_dict)
```
Ein vor dem Aufruf registrierter `progress_hooks`-Callback erhält dieses
Dict zuverlässig, sobald der Rohdownload abgeschlossen ist — **bevor** die
Postprocessing-Kette beginnt und unabhängig davon, ob diese später
erfolgreich ist.

---

## 7. Fehlerfälle einzeln (Fall A-E)

**Fall A — yt-dlp schlägt vor Erstellung des Outputs fehl** (z. B.
Netzwerkfehler während der initialen Extraktion/des Downloads selbst):
Kein `progress_hooks`-Callback mit `status='finished'` wurde ausgelöst → kein
bekannter Pfad → nichts zu bereinigen (korrektes No-op). Ein evtl.
entstandenes `.part`-Fragment bleibt unangetastet (bewusst, DL-04/DEFER,
nicht Teil dieser Phase).

**Fall B — yt-dlp erstellt Rohdatei, FFmpeg/Postprocessing schlägt fehl:**
Exakt der in Abschnitt 3 nachvollzogene Fall. Der `progress_hooks`-Callback
hat bereits gefeuert (`status='finished'`, Rohdatei liegt vor) → Pfad bekannt
→ `cleanup_single_download_artifact()` kann sicher mit diesem Pfad
aufgerufen werden. Die ursprüngliche Exception (`PostProcessingError` →
`DownloadError`) bleibt unverändert erhalten und wird weiterhin geworfen —
Cleanup läuft NUR als Nebeneffekt im `except`-Zweig, ändert nichts am
Fehler-Ergebnis.

**Fall C — FFmpeg erstellt bereits einen Output und schlägt danach fehl:**
Laut Quellcode-Beleg (Abschnitt 3) nicht möglich für den finalen `new_path` —
`os.replace(temp_path, new_path)` wird nur nach erfolgreichem
`run_ffmpeg()`-Aufruf erreicht. Ein FFmpeg-*Subprozess*-Fehlschlag (Exit-Code
≠ 0) hinterlässt höchstens die o. g. `temp_path`-Teilausgabe, niemals die
finale, bereits "erfolgreich" wirkende Datei.

**Fall D — Fehler nach erfolgreichem Download, aber vor `move_to_library()`:**
Das ist strukturell derselbe Fall wie Fall B/C (der yt-dlp-Aufruf selbst ist
noch nicht zurückgekehrt, `move_to_library()` wird erst in
`enhanced_metadata_processor.py` — deutlich später in der Pipeline — erreicht,
lange nach `extract_info_async()`s Rückkehr). Ein Fehler hier wird weiterhin
korrekt als `DownloadError` gemeldet, Cleanup erfasst nur die Rohdatei/
Temp-Ausgabe, nicht mehr.

**Fall E — Fehler nach `move_to_library()`:** Liegt außerhalb dieser
Funktion (`_process_single_download()` endet lange vor `move_to_library()`,
das erst innerhalb von `process_single_track()` in
`enhanced_metadata_processor.py` aufgerufen wird). Bereits identifiziert als
Teil von **DL-01** (Cancellation-Fund) bzw. des bereits bestehenden
FINDING-2-Cleanups für reguläre Exceptions nach erfolgreichem Move. **Wird
hier ausdrücklich NICHT vorweggenommen.**

---

## 8. Betroffene Dateien/Funktionen (für einen künftigen Fix, NICHT umgesetzt)

- `services/downloader/download/download_executor.py` — `extract_info`/`extract_info_async` müssten einen optionalen Hook-Mechanismus erhalten (oder `ydl_opts["progress_hooks"]` wird direkt am Call-Site in `download_utils.py` vor dem Aufruf gesetzt — beide Varianten technisch möglich, siehe Abschnitt 9).
- `services/downloader/download_utils.py` — `_process_single_download()`: Import von `cleanup_single_download_artifact`, Hook-Registrierung vor dem Aufruf, Cleanup-Aufruf im `except`-Zweig.
- `services/downloader/download_artifact_cleanup.py` — **keine Änderung nötig**, `cleanup_single_download_artifact()` ist bereits generisch genug (nimmt einen beliebigen `Path`).

---

## 9. Minimaler Fix-Vorschlag (NICHT umgesetzt, nur zur Freigabe vorgeschlagen)

```python
# services/downloader/download_utils.py, _process_single_download()

raw_downloaded_path = None

def _capture_raw_path(status: dict) -> None:
    nonlocal raw_downloaded_path
    if status.get("status") == "finished" and status.get("filename"):
        raw_downloaded_path = status["filename"]

hooked_opts = {**ydl_opts, "progress_hooks": [
    *ydl_opts.get("progress_hooks", []), _capture_raw_path
]}

try:
    download_info = await enhanced_processor.download_executor.extract_info_async(
        url, hooked_opts, download=True
    )
    ...
except Exception as e:
    enhanced_processor.session_stats["failed_downloads"] += 1
    if raw_downloaded_path:
        cleanup_single_download_artifact(
            Path(raw_downloaded_path),
            getattr(enhanced_processor.config, "DOWNLOAD_DIR", None),
            logger,
        )
    raise DownloadError(f"Single-Download fehlgeschlagen: {e}")
```

Eigenschaften, die den Anforderungen aus Abschnitt 4/9 des Auftrags genügen:

- **Kein `finally` verwendet** — bewusst, da `finally` unterschiedslos auch
  im ERFOLGSFALL laufen würde; im Erfolgsfall existiert die Rohdatei evtl.
  gar nicht mehr (bereits durch `os.replace()` in `orig_path`/`new_path`
  umbenannt) — ein unbedingter `finally`-Cleanup-Versuch auf
  `raw_downloaded_path` wäre dort ein harmloses No-op (Pfad existiert nicht
  mehr → `cleanup_single_download_artifact()`s eigener `.exists()`-Guard
  greift), aber semantisch unnötig und potenziell verwirrend. Der Cleanup
  gehört ausschließlich in den Fehlerpfad.
- **Kein Verschlucken der Exception** — `raise DownloadError(...)` bleibt
  unverändert die letzte Zeile.
- **Keine neue Cleanup-Abstraktion** — reine Wiederverwendung der
  bestehenden `cleanup_single_download_artifact()`.
- **Nur eindeutig zuordenbare Artefakte** — der Pfad stammt direkt aus
  yt-dlps eigenem, für DIESEN Aufruf spezifischen Hook, nicht aus Raten/Glob.
  `cleanup_single_download_artifact()`s bereits vorhandene
  `_is_within_directory()`-Prüfung bleibt zusätzlich als zweite
  Sicherheitsebene aktiv.

**Offene Frage für die Implementierungsphase (nicht hier zu entscheiden):**
soll auch der von `temp_path = prepend_extension(path, 'temp')` abgeleitete
FFmpeg-Zwischenpfad (Fall B/C) gezielt bereinigt werden? Das wäre technisch
möglich (`prepend_extension` ist eine öffentliche yt-dlp-Utility,
`from yt_dlp.utils import prepend_extension`), würde den Fix aber um eine
zweite abgeleitete Pfad-Berechnung erweitern. **Empfehlung:** in der
Implementierungsphase zunächst nur die Rohdatei behandeln (deckt den
größeren, sicheren Fall ab) und den `.temp`-Zwischenstand als optionale
Erweiterung separat bewerten, um den Fix minimal zu halten.

---

## 10. Regressionstest-Plan (NICHT umgesetzt)

| Test | Szenario | Prüft |
|---|---|---|
| Test 1 | `extract_info_async` wirft eine Exception, NACHDEM der injizierte `progress_hooks`-Callback mit `status='finished'` und einer in `tmp_path` real existierenden Datei aufgerufen wurde | Exception propagiert weiterhin als `DownloadError`; die Datei existiert nach dem Aufruf nicht mehr; kein fremdes Artefakt (zweite, unbeteiligte Datei in `tmp_path`) wird entfernt |
| Test 2 | Wie Test 1, aber der Hook wird NICHT aufgerufen (Fehler VOR Fertigstellung des Rohdownloads, Fall A) | Exception propagiert; kein Cleanup-Aufruf erfolgt (da kein Pfad bekannt) — kein Fehler durch `None`-Pfad |
| Test 3 (Success-Regression) | `extract_info_async` liefert erfolgreich ein `download_info`-Dict, Hook wurde ebenfalls mit `status='finished'` aufgerufen | Bestehendes Erfolgsverhalten bleibt unverändert (kein Cleanup-Aufruf im Erfolgspfad, Datei bleibt erhalten, `build_single_track_result()` wird wie bisher aufgerufen) — Abgleich mit bestehenden Tests in `test_download_utils_metadata_translation.py::TestProcessSingleDownloadCacheMiss` |
| Test 4 (finaler Pfad geschützt) | Zwei Dateien in `tmp_path` vorhanden: die vom Hook gemeldete Rohdatei UND eine zweite, unbeteiligte Datei (simuliert eine bereits erfolgreich verschobene/andere Datei) | Nur die vom Hook gemeldete Datei wird gelöscht, die zweite bleibt unangetastet |
| Test 5 (parallele Downloads) | Zwei unabhängige `_process_single_download()`-Aufrufe (unterschiedliche `tmp_path`-Unterordner oder unterschiedliche Dateinamen) laufen mit jeweils eigenem Hook-Closure; einer schlägt fehl | Nur das Artefakt des fehlgeschlagenen Downloads wird entfernt, das Artefakt des anderen (erfolgreichen oder noch laufenden) bleibt erhalten — bestätigt Closure-Isolation aus Abschnitt 6 |

Testmethodik: reale Dateien in `tmp_path` (kein reines
`assert_called_once()`), Wiederverwendung des bereits etablierten
Mocking-Musters aus `test_download_utils_metadata_translation.py`
(`make_enhanced_processor_for_single`) — dort müsste `extract_info_async`
so gemockt werden, dass es selbst den übergebenen `hooked_opts["progress_hooks"]`-Callback
aufruft, bevor es die konfigurierte Exception wirft (Simulation von yt-dlps
eigenem Verhalten), statt ihn nur zu ignorieren.

---

## 11. Risiken

- **Mittleres Komplexitätsrisiko:** der Fix ist kein reiner
  Ein-Zeilen-`except`-Zusatz, sondern erfordert eine Hook-Registrierung vor
  dem eigentlichen Aufruf — etwas mehr Angriffsfläche für einen
  Implementierungsfehler als ursprünglich angenommen.
- **Test-Aufwand für das Simulieren des Hook-Aufrufs:** bestehende Tests
  mocken `extract_info_async` komplett und rufen dabei nie in `ydl_opts`
  übergebene Hooks auf — die neuen Tests müssen das Mock so gestalten, dass
  es den Hook selbst aufruft, bevor es fehlschlägt (Mehraufwand ggü. reinem
  `side_effect=Exception(...)`).
  - **Kein Datenverlust-/Korruptionsrisiko** identifiziert — der Cleanup
  betrifft ausschließlich Artefakte, die VOR der finalen, erfolgreichen
  Zieldatei liegen; die finale Datei existiert im Fehlerfall nachweislich
  nicht (Abschnitt 3/7 Fall C).
- **Restrisiko (vorbestehend, nicht durch diesen Fix verursacht):**
  `outtmpl`-Namenskollision zwischen zwei parallelen Single-Downloads mit
  identischem Video-Titel (Abschnitt 6) — bleibt nach diesem Fix in exakt
  demselben Zustand wie vorher, wird weder verbessert noch verschlechtert.
- **`.temp`-FFmpeg-Zwischendatei (Fall B/C) bleibt bei der minimalen
  Fix-Variante zunächst unbereinigt** (siehe offene Frage, Abschnitt 9) —
  bewusste Scope-Entscheidung zur Fix-Zeit, nicht Teil dieser Analyse-Phase.

---

## 12. Scope-Abgrenzung

```
DL-02: JA

DUP-01: NEIN
DUP-08: NEIN
DUP-02: NEIN
DUP-03: NEIN
DUP-05: NEIN
DL-01: NEIN
P2: NEIN
P3: NEIN
Metadata: NEIN
Architecture: NEIN
```

Während der Analyse identifizierter Zusammenhang mit **DL-01**: Fall E
(Fehler nach `move_to_library()`) ist ausdrücklich DL-01s Zuständigkeit,
nicht hier behandelt oder vorweggenommen. Kein weiterer Zusammenhang mit
anderen Findings gefunden. `.part`/`.ytdl`-Handling bleibt bei der
bestehenden DL-04-DEFER-Entscheidung.

---

## 13. Entscheidungsempfehlung

Ein sicherer, eindeutig zuordenbarer Cleanup-Mechanismus für DL-02 ist
**möglich** (nicht "nicht sicher lösbar") — die ursprünglich in Phase 0/1
angenommene "einfach `cleanup_single_download_artifact()` im `except`-Block
aufrufen"-Lösung ist jedoch **nicht ausreichend**, da zum Zeitpunkt des
typischen DL-02-Fehlers (FFmpeg-Postprocessing schlägt fehl) kein
`download_info`-Dict existiert, aus dem sich ein Pfad ableiten ließe. Der
belastbare Weg ist ein `progress_hooks`-basierter Pfad-Capture, direkt am
yt-dlp-Quellcode verifiziert.

**Empfehlung:** DL-02 zur Implementierung freigeben, mit dem in Abschnitt 9
skizzierten Fix (Hook-Capture + bestehende `cleanup_single_download_artifact()`),
begrenzt auf die Rohdatei (nicht die abgeleitete `.temp`-FFmpeg-Zwischendatei,
die als optionale Erweiterung offen bleibt). Vor Implementierungsbeginn sollte
entschieden werden, ob die `.temp`-Zwischendatei in den Fix-Scope
aufgenommen wird oder als separater, kleinerer Folge-Punkt zurückgestellt
wird.
