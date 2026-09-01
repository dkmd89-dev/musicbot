# DL-03 / DL-05 Retry Classification — Audit & Fix

Gezielter Correctness-/Resilience-Fix: Verdrahtung der bereits vorhandenen
Download-Exception-Taxonomie (`services/downloader/errors.py`) mit dem
tatsächlichen Download-/Retry-Flow, sodass permanente Fehler nicht mehr
unnötig wiederholt werden. Kein allgemeines Downloader-Refactoring.

## Baseline

| Feld | Wert |
|---|---|
| HEAD (Start) | `bb9b0525e9df77205e0d91b1327c96e80b8c596e` |
| Branch | `fix/dl03-dl05-retry-error-classification` (von `main`) |
| Tests (Start) | 1652 passed, 1 skipped, 0 failed |
| Referenzierte Docs | `docs/MusicBot_ENGINEERING_BASELINE_v6.md`, `docs/MusicBot_ARCHITECTURE_EVOLUTION.md`, `docs/audits/SERVICES_ARCHITECTURE_AUDIT_2026-09-01.md`, `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`, `docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE1_PLAN.md` |

Bereits getroffene, hier respektierte Vorentscheidungen: Phase1-Plan
klassifizierte DL-03/DL-05 explizit als „bewusste technische Schuld"
(Kategorie C) — kein kleinster Fix, sondern echte Fehlerklassifikation
nötig, „String-Matching auf yt-dlp-Fehlermeldungen o. Ä." wurde dort bereits
als erwarteter Lösungsweg benannt. Dieser Task setzt genau das um, ohne
eine der beiden Findings erneut aufzurollen oder neu zu bewerten.

## Tatsächlicher Runtime-Flow

```
klassen/download_handler.py::handle_url() (async)
   ↓
services/downloader/download_utils.py::enhanced_download_with_retry()  [max_retries=3, Retry-Loop]
   │
   ├─ extract_info_async(url, ydl_opts, download=False)   [DownloadExecutor, yt-dlp Info-Extraktion]
   │     → bei Fehler: rohe yt_dlp.utils.YoutubeDLError-Exception propagiert DIREKT
   │       in den Retry-Loop (VORHER: nur generisches "except Exception" -> Retry)
   │
   ├─ entries vorhanden? → _process_playlist_download()
   │     └─ pro Track: except Exception LOKAL abgefangen, Loop laeuft weiter
   │        (KEIN Retry auf Playlist-Track-Ebene fuer Metadaten-Fehler,
   │        DL-05 betrifft NUR den Single-Track-Pfad, siehe unten)
   │
   └─ sonst → _process_single_download()
         ├─ extract_info_async(url, ydl_opts, download=True)
         │     → rohe yt_dlp-Exception (VORHER: except Exception ganz unten
         │       -> IMMER generisches DownloadError, Klassifikation verloren)
         ├─ enhanced_result = process_single_track()  [EnhancedMetadataProcessor]
         │     └─ enhanced_result.success == False
         │           → raise DownloadError("Processing failed: ...")  [VORHER]
         └─ except Exception as e: raise DownloadError(f"Single-Download fehlgeschlagen: {e}")
               [VORHER: wrappte AUSNAHMSLOS alles, auch bereits geworfene
               DownloadError-Subtypen, in ein frisches generisches DownloadError]
   ↓ (Exception propagiert zurueck in den Retry-Loop)
enhanced_download_with_retry() Retry-Entscheidung:
   except DownloadError as e:  → IMMER Retry bis max_retries (VORHER)
   except Exception as e:      → IMMER Retry bis max_retries (VORHER)
```

**Datei/Funktion/Caller/Callee/Exception-Grenze/Retry-Entscheidung:**

| # | Datei | Funktion | Caller | Callee | Exception-Grenze | Retry-Entscheidung (vorher) |
|---|---|---|---|---|---|---|
| 1 | `download_utils.py:420-540` (nach Fix; vorher 330-424) | `enhanced_download_with_retry()` | `downloader.py::download_audio()` | `extract_info_async()`, `_process_playlist_download()`, `_process_single_download()` | einzige Retry-Entscheidungsstelle | `except DownloadError`/`except Exception` — identisch, immer Retry |
| 2 | `download.download_executor.py:171-188` | `extract_info_async()` | `enhanced_download_with_retry()`, `_process_single_download()` | `yt_dlp.YoutubeDL.extract_info()` | wirft rohe yt-dlp-Exceptions **unverändert** weiter (laut eigenem Docstring) | keine — Boundary lag bisher ungenutzt beim Aufrufer |
| 3 | `download_utils.py:~1000-1070` (nach Fix) | `_process_single_download()` | `enhanced_download_with_retry()` | `extract_info_async()`, `call_process_single_track()` | fing ALLES in einem `except Exception` | wrappte alles in generisches `DownloadError` |
| 4 | `services/metadata/enhanced_metadata_processor.py:1128` | `process_single_track()` | `call_process_single_track()` | 8 interne Kollaboratoren (Artist/Title/Genre/Lyrics/MB/Cover/Album/Tags) | `except Exception as e: return MetadataResult(success=False, ..., error=str(e))` | kein Exception-Typ verlässt diese Funktion — nur ein String |

## Exception-Taxonomie-Matrix

| Exception | Wo entsteht sie? | Wird sie tatsächlich raised (vor Fix)? | Wird sie gefangen? | Retry vorher | Retry sinnvoll? |
|---|---|---:|---|---:|---:|
| `InvalidURLError` | — | **NEIN** (0 Aufrufer im gesamten Repo, verifiziert per Grep) | — | n/a | NO |
| `FormatNotAvailableError` | — | **NEIN** (0 Aufrufer) | — | n/a | NO |
| `MetadataError` | — | **NEIN** (0 Aufrufer) | — | n/a | NO |
| `FileProcessingError` | — | **NEIN** (0 Aufrufer) | — | n/a | UNKNOWN (siehe unten) |
| `NetworkError` | — | **NEIN** (0 Aufrufer) | — | n/a | YES |
| `PermissionError` (eigene Klasse, verdeckt Python-Builtin) | — | **NEIN** (0 Aufrufer) | — | n/a | NO |
| `DownloadError` (Basisklasse) | `download_utils.py` (5 Stellen: Zeile 337/460/912/950/956 vor Fix) | **JA**, aber ausschließlich die unspezifische Basisklasse | `except DownloadError` in der Retry-Loop | JA, immer | UNKNOWN je nach Ursache |
| `yt_dlp.utils.YoutubeDLError`/`ExtractorError`/`GeoRestrictedError`/`UnsupportedError` | yt-dlp intern, propagiert unverändert aus `extract_info_async()` | JA (fremde Bibliothek) | vor Fix: nur generisches `except Exception` | JA, immer | teils YES (Netzwerk), teils NO (privat/geo/unsupported) |

**Kritischer Befund (bereits im Services-Audit vorhergesagt, hier verifiziert):**
die komplette Exception-Taxonomie in `services/downloader/errors.py` war vor
diesem Fix vollständig **definiert, aber nirgends verwendet** — 0 `raise
InvalidURLError(...)`/`FormatNotAvailableError(...)`/`MetadataError(...)`/
`NetworkError(...)`/`PermissionError(...)` im gesamten Repository außerhalb
der Klassendefinitionen selbst.

## Retry Decision Matrix

### Permanent / nicht retriable (implementiert)

| Fehler | MusicBot-Klasse | Quelle |
|---|---|---|
| Nicht unterstützte/ungültige URL | `InvalidURLError` | `yt_dlp.utils.UnsupportedError` (typsicher) |
| Geo-Sperre | `InvalidURLError` | `yt_dlp.utils.GeoRestrictedError` (typsicher) |
| Privates/gelöschtes/altersbeschränktes Video, Login-Pflicht, Copyright | `InvalidURLError` | `yt_dlp.utils.ExtractorError` mit `expected=True` + bekanntem Nachrichten-Marker (String-Match, siehe unten) |
| Metadata-Pipeline-Fehler (`enhanced_result.success == False`) | `MetadataError` | `_process_single_download()`, direkt |
| Format nicht verfügbar | `FormatNotAvailableError` | bereits Teil der Non-Retryable-Menge (Klasse existiert, wird aber aktuell nirgends geworfen — siehe „Remaining Issues") |
| Lokaler Berechtigungsfehler | `PermissionError` (Downloader-eigene Klasse) | bereits Teil der Non-Retryable-Menge (Klasse existiert, wird aber aktuell nirgends geworfen) |

### Transient / retriable (unverändert)

| Fehler | Verhalten |
|---|---|
| `NetworkError` | unverändert retried (bewusst NICHT in die Non-Retryable-Menge aufgenommen) |
| unklassifizierte `yt_dlp.utils.YoutubeDLError` (kein bekannter Marker, `expected=False`) | unverändert retried — Klassifikation greift nur bei eindeutiger Evidenz |
| generisches `DownloadError` (Basisklasse, z. B. "yt-dlp lieferte kein Ergebnis") | unverändert retried |
| jede sonstige `Exception` | unverändert retried |

### Metadata — differenzierte Betrachtung (DL-05)

`enhanced_metadata_processor.py::process_single_track()` fängt am Ende
selbst **jede** Exception aus der 16-stufigen Pipeline (Artist/Title/Genre/
Lyrics/MusicBrainz/Cover/Album/Loudness/Tags/Cache/Auto-Learn) mit einem
einzigen `except Exception` ab und gibt `MetadataResult(success=False,
error=str(e))` zurück — der ursprüngliche Exception-**Typ** geht dabei
verloren, nur die Nachricht bleibt. Optionale externe Dienste (Genius,
MusicBrainz, Last.fm, Cover-Quellen) sind bereits **einzeln** mit
Fallback/graceful-degradation abgesichert (bestätigt in
`MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`, Abschnitt 29.3:
"Metadata-Failure (optionaler Service) → Wird abgefangen, Track läuft mit
degradierten Metadaten normal weiter → success=True) — ein tatsächliches
`success=False` kommt damit fast ausschließlich aus einem **deterministischen**
Fehler in einem nicht-optionalen Kernschritt (z. B. Tag-Schreiben,
Bibliotheks-Move, ein Logik-Bug). Ein erneuter kompletter YouTube-Download
(dieselbe Quelldatei, dieselbe Pipeline, dieselben Eingabedaten) ändert an
einem solchen Fehler nichts — daher: **`MetadataError` ⇒ nicht retriable**.

Eine feinere Unterscheidung "Metadata permanent invalid" vs. "Metadata
transiently unavailable" ist von außerhalb von `process_single_track()`
**nicht zuverlässig möglich**, weil die Funktion den ursprünglichen
Exception-Typ nicht nach außen durchreicht (nur `str(e)`). Diese
Einschränkung wird hier ausdrücklich dokumentiert statt durch Raten
überbrückt (Abschnitt 6/10 der Aufgabenstellung).

**DL-05 ist damit — wie in Abschnitt 8 der Aufgabenstellung vermutet — eine
direkte Folge von DL-03/derselben fehlenden Klassifikation**, nicht ein
strukturell eigenständiges Problem: Der einzige Unterschied ist die
Fehlerquelle (Metadata-Pipeline statt yt-dlp), der Mechanismus (blindes
Retry-bis-max_retries über den kompletten `DownloadError`/`Exception`-Fang)
ist identisch. Ein einziger Fix (Klassifikation + Non-Retryable-Prüfung in
der Retry-Loop) behebt beide Findings gemeinsam.

### Unknown Errors

Bewusst konservativ: alles, was nicht eindeutig einem bekannten
Permanent-Marker oder einem typsicheren yt-dlp-Exception-Typ zugeordnet
werden kann, bleibt beim bisherigen Verhalten (Retry mit vollem Backoff bis
`max_retries`) — keine pauschale Einordnung als "permanent" oder
"transient" ohne Beleg.

## Implemented Fix

**Datei:** `services/downloader/download_utils.py` (einzige geänderte
Produktionsdatei).

1. **Neuer Klassifikations-Helfer** `_classify_ytdlp_error(exc)`: übersetzt
   eine rohe `yt_dlp.utils.YoutubeDLError` an der Boundary in die
   bestehende MusicBot-Taxonomie:
   - `UnsupportedError`/`GeoRestrictedError` → `InvalidURLError` (typsicher,
     kein String-Matching nötig).
   - `ExtractorError` (bzw. jede `YoutubeDLError`) mit `expected=True` UND
     einer Nachricht, die einen von 9 aus dem realen yt-dlp-Quellcode
     belegten Permanent-Markern enthält (z. B. "private video", "video
     unavailable", "sign in to confirm your age", "copyright") →
     `InvalidURLError`.
   - explizit ausgenommen: yt-dlps eigener Rate-Limit-Hinweis ("isn't
     available, try again later") — ausdrücklich transient, bleibt
     unklassifiziert.
   - alles andere → generisches `DownloadError` (unverändertes Verhalten).
2. **`_NON_RETRYABLE_ERROR_TYPES`**-Tupel: `InvalidURLError`,
   `FormatNotAvailableError`, `PermissionError` (Downloader-eigene Klasse,
   importiert als `DownloadPermissionError` um den Python-Builtin nicht zu
   verdecken), `MetadataError`. `NetworkError` und die unklassifizierte
   Basisklasse `DownloadError` bewusst NICHT enthalten (siehe Retry Decision
   Matrix oben). `FileProcessingError` bewusst NICHT enthalten (siehe
   Remaining Issues).
3. **`enhanced_download_with_retry()`**: `except DownloadError` und ein neu
   hinzugefügtes `except YoutubeDLError` zu einem gemeinsamen
   `except (YoutubeDLError, DownloadError) as e:` zusammengeführt. Vor der
   bisherigen (unveränderten) Retry-/Backoff-Logik wird geprüft, ob der
   (ggf. klassifizierte) Fehler in `_NON_RETRYABLE_ERROR_TYPES` liegt — wenn
   ja: sofortiger Return mit `success=False`, KEIN weiterer Versuch, kein
   `asyncio.sleep()`. Alles andere durchläuft exakt die bisherige Logik
   unverändert (gleicher Backoff `2**attempt`, gleiche
   `max_retries`-Grenze, gleiches Log-Format).
4. **`_process_single_download()`**:
   - `enhanced_result.success == False` wirft jetzt `MetadataError` statt
     generischem `DownloadError`.
   - der abschließende Fang wurde von einem einzigen `except Exception` in
     drei Zweige aufgeteilt: `except DownloadError: raise` (bereits
     klassifizierte Typen unverändert durchreichen), `except YoutubeDLError
     as e: raise _classify_ytdlp_error(e) from e` (rohe yt-dlp-Fehler an der
     Boundary klassifizieren), `except Exception as e: raise
     DownloadError(f"Single-Download fehlgeschlagen: {e}")` (unverändert für
     alles Übrige). Cleanup-Aufruf (`cleanup_single_download_artifact`) in
     allen drei Zweigen identisch erhalten.

Keine neue Retry-Engine, keine neue Exception-Klasse, keine Änderung an
`max_retries`/Backoff/Cleanup/Playlist-Pfad/Logging-Format außerhalb der
neu hinzugekommenen Zweige.

## Tests

### Pre-Fix-Diskriminierung

`git stash push -- services/downloader/download_utils.py`, alle 11 neuen
Tests erneut ausgeführt: **7 schlugen erwartungsgemäß fehl** (genau die
Tests, die die neue Klassifikation/Non-Retry-Entscheidung prüfen), die
übrigen 4 (Regressionstests für unverändertes Verhalten: Rate-Limit-Hinweis
bleibt unklassifiziert, unbekannte Exceptions bleiben generisch gewrappt,
`NetworkError`/unklassifizierter yt-dlp-Fehler bleiben retriable) waren
bereits vor dem Fix grün — korrekt, da sie unverändertes Verhalten
absichern. `git stash pop` — Fix wiederhergestellt, alle 11 Tests grün.

### Gezielte Tests

```
python3 -m pytest tests/test_download_utils_retry.py tests/test_download_utils_metadata_translation.py -q
40 passed
```

### Thematische Suite

```
python3 -m pytest tests/ -q -k "download or ytdlp or yt_dlp or retry or metadata"
338 passed, 1326 deselected
```

### Finale Full Suite (einziger Lauf)

```
python3 -m pytest tests/ -q
1663 passed, 1 skipped, 0 failed  (Baseline: 1652 passed, 1 skipped → +11 neue Tests, exakt reproduziert)
```

Keine Regression, keine bereits vorbestehenden Fehler betroffen.

## Behavioral Impact

- Ein permanenter yt-dlp-Fehler (privates/gesperrtes/geo-blockiertes/nicht
  unterstütztes Video) löst jetzt **genau einen** Versuch statt bis zu 3
  aus — spart bis zu 2 komplette, garantiert erfolglose Download-Versuche
  inkl. Backoff-Wartezeit (bisher bis zu `1s + 2s = 3s` zusätzliche
  Wartezeit plus doppelte yt-dlp-Netzwerklast).
- Ein deterministischer Metadata-Pipeline-Fehler löst jetzt **genau einen**
  Versuch statt bis zu 3 aus — spart bis zu 2 komplette, unnötige
  YouTube-Neu-Downloads derselben Datei.
- Die zurückgegebene Fehlermeldung bei permanenten Fehlern beginnt neu mit
  `"Download dauerhaft fehlgeschlagen (kein Retry sinnvoll): ..."` statt
  `"Download nach N Versuchen fehlgeschlagen: ..."` — sichtbare, aber
  bewusste und korrekte Änderung der Nutzer-Fehlermeldung (spiegelt jetzt
  akkurat wider, dass kein weiterer Versuch stattfand).

## Behavioral Guarantees (unverändert)

- Transiente Fehler (`NetworkError`, unklassifizierte yt-dlp-Fehler,
  generisches `DownloadError`, jede sonstige `Exception`) durchlaufen
  weiterhin exakt die bisherige Retry-Logik: gleicher exponentieller
  Backoff (`2**attempt`), gleiche `max_retries`-Grenze (Default 3), gleiches
  Log-Format.
- Playlist-Pfad (`_process_playlist_download()`/`_process_track_metadata()`)
  unverändert — dort wurden Metadata-Fehler bereits vor diesem Fix lokal
  pro Track abgefangen (kein Retry, Loop läuft weiter) und sind nicht Teil
  von DL-05 (DL-05 betraf ausschließlich den Single-Track-Pfad, siehe
  Root-Cause-Abschnitt).
- Cleanup-Verhalten (`cleanup_single_download_artifact` bei
  `raw_downloaded_path`) unverändert in allen drei Except-Zweigen von
  `_process_single_download()` erhalten.
- Erfolgreiche Downloads (Single und Playlist) vollständig unverändert.
- Keine Änderung an `services/`-Architektur, Client-Architektur, Dependency
  Injection, Async-Architektur, Handlern, Telegram-Schicht,
  Duplicate-System oder allgemeiner Metadata-Architektur.

## Out of Scope

- `services/duplicate/cache.py` INV-01 — nicht angefasst.
- `MUSICBRAINZ_RETRIES` — nicht angefasst.
- `EnhancedMetadataProcessor`/`process_single_track()`-Komplexität (908
  Zeilen) — nicht angefasst, insbesondere wurde der interne
  `except Exception`-Fang in `process_single_track()` selbst NICHT
  aufgebrochen (das wäre eine Metadata-Architekturänderung, außerhalb des
  Scopes).
- `download_executor.py::download_single_track()` Cancellation-Cleanup —
  nicht angefasst.
- Client-Architektur, Dependency Injection, Async-Architektur, Handler,
  Telegram-Schicht, Duplicate-System — nicht angefasst.
- `tenacity`-Retry in `services/clients/genius_client.py` — separater,
  unabhängiger Retry-Mechanismus, nicht Teil von DL-03/DL-05.

## Remaining Issues

- **`FormatNotAvailableError`/`PermissionError` (Downloader-eigene Klasse)**
  sind zwar bereits in `_NON_RETRYABLE_ERROR_TYPES` enthalten (korrekte
  Retry-Entscheidung, falls sie künftig geworfen werden), werden aber
  aktuell **von keiner Stelle im Code tatsächlich geworfen** — die
  Klassifikations-Infrastruktur ist für sie vorbereitet, aber nicht
  aktiv genutzt. Kein Fix-Bedarf innerhalb dieses Tasks (kein konkreter
  Fehlerfluss dafür identifiziert), hier nur zur Transparenz vermerkt.
- **`FileProcessingError`** bewusst NICHT in die Non-Retryable-Menge
  aufgenommen — die Klasse wird aktuell nirgends geworfen, ihre
  tatsächlichen Fehlerursachen in dieser Pipeline sind nicht bekannt/belegt
  (könnten transient wie permanent sein). Sollte sie künftig verwendet
  werden, muss die Retry-Einordnung anhand des dann konkreten Fehlerflusses
  neu bewertet werden.
- **`DOWNLOAD_RETRY_COUNT`/`DOWNLOAD_RETRY_DELAY`** (Config) — bereits im
  Services-Audit als ungeklärt dokumentiert, ob sie tatsächlich als
  `max_retries`-Quelle dienen (der Call-Site übergibt aktuell keinen
  expliziten Wert, `enhanced_download_with_retry()`s Funktions-Default
  `max_retries=3` bleibt maßgeblich). Nicht Teil dieses Fixes.
- **`_YTDLP_PERMANENT_MESSAGE_MARKERS`** ist eine bewusst kleine,
  evidenzbasierte Liste (aus dem realen yt-dlp-Quellcode, Version
  2026.08.19, belegt). Künftige yt-dlp-Versionen können Formulierungen
  ändern — die Liste degradiert dann sicher (fällt auf die bisherige
  Retry-Behandlung zurück, kein neues Fehlverhalten), sollte aber bei
  auffälligen künftigen DL-03-Wiederholungen als Erstes geprüft werden.
