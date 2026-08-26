# MusicBot — Download Pipeline Stability Phase — PHASE 2M: DUP-06

> Analyse-, Fix- und Abschluss-Dokumentation für DUP-06. Ursprünglich in
> PHASE 2F identifiziert (Audit-Dokument nicht als Datei im Repository
> erhalten — siehe `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2K_DL08_AUDIT.md`,
> Abschnitt 6, für den gleichen Sachverhalt bei DL-08), hier vollständig
> mit eigener Tiefenanalyse und Controlled Fix dokumentiert.

**Status: DUP-06 — TECHNISCH ABGESCHLOSSEN (uncommitted)**

---

## 1. Finding

**ID:** DUP-06 — P2 — YouTube-Mix-/Radio-Pseudo-Playlists (`list=RD...`)
werden wie echte Playlists behandelt.

**Betroffene Stellen:** zwei unabhängige Codestellen, beide über eigene
`entries`-Prüfung:

1. `klassen/download_handler.py::_probe_artist_title_for_duplicate_check()`
   (Zeile ~304): `if not info or info.get("entries"): return None, None` —
   überspringt die Content-/Parser-/Library-Duplicate-Ebene.
2. `services/downloader/download_utils.py::enhanced_download_with_retry()`
   (Zeile ~298 vor dem Fix): `entries = info.get("entries")` →
   `_process_playlist_download()` statt `_process_single_download()`.

**Root Cause:** verifiziert direkt gegen den installierten yt-dlp-Quellcode
(Version 2026.08.19): `extractor/youtube/_base.py::_PLAYLIST_ID_RE` führt
„RD" als eigenes, von „PL" unterschiedenes Präfix; `YoutubeIE.suitable()`
schließt jede URL mit `list=`-Parameter kategorisch vom Einzelvideo-Pfad
aus; `extractor/common.py::_yes_playlist()` (aufgerufen von
`YoutubeTabIE`) liest den `noplaylist`-Parameter — ohne diesen entsteht für
`list=RD...` **genauso** ein `entries`-tragendes Ergebnis wie für eine
echte Playlist (`list=PL...`). MusicBot setzte `noplaylist` nirgends.

---

## 2. Vor-Fix-Diskriminierung

Aufgrund einer Prozessabweichung wurde die Implementierung zunächst vor der
Vor-Fix-Diskriminierung vorgenommen; korrigiert durch gezielte,
vorübergehende Rücknahme der beiden Call-Site-Integrationen (nicht der
Helper-Funktion selbst) und erneute Testausführung. Ergebnis gegen den so
rekonstruierten ungefixten Stand: **6 failed, 12 passed**. Fehlgeschlagen
(diskriminierend): Tests 1-4 (RDMM/RD/Zusatzparameter/Parameterreihenfolge
→ `noplaylist` fehlte), Test 7 (bestehende `ydl_opts` blieben erhalten,
aber ohne `noplaylist`), Test 8 (Probe setzte `noplaylist` nicht).

---

## 3. Fix

Neue, zentrale und einzige Erkennungsfunktion
`services/downloader/download_utils.py::is_youtube_mix_url(url)`: parst den
`list`-Query-Parameter robust (`urllib.parse`, ordnungs- und
zusatzparameterunabhängig), prüft case-sensitiv auf das Präfix `"RD"`.

An beiden betroffenen Stellen, jeweils additiv vor dem jeweiligen
`extract_info_async()`-Aufruf:

```python
if is_youtube_mix_url(url):
    ydl_opts = {**ydl_opts, "noplaylist": True}
```

Die bestehende `entries`-Verzweigungslogik selbst wurde an keiner der
beiden Stellen verändert — für `list=RD...`-URLs entsteht durch
`noplaylist=True` schlicht kein `entries` mehr, die vorhandene Logik greift
dadurch automatisch korrekt. `klassen/download_handler.py` importiert die
Funktion aus `services/downloader/download_utils.py` (Services-Layer),
keine doppelte Implementierung.

**Geänderte Dateien:** `services/downloader/download_utils.py` (61 Zeilen,
inkl. neuer Funktion), `klassen/download_handler.py` (27 Zeilen, inkl.
Import). `build_ydl_opts()`, `download_single_track()`,
`_process_playlist_download()`, `_process_single_download()`,
`handle_playlist_success()`, `_register_playlist_track_duplicates()`
unverändert.

**Neue Tests:** `tests/test_download_utils_youtube_mix_url_detection.py` —
18 Tests: 8 auf `enhanced_download_with_retry()`-Ebene (tatsächlich
übergebene `ydl_opts` geprüft, nicht nur die isolierte Helper-Funktion), 3
auf `_probe_artist_title_for_duplicate_check()`-Ebene, 1 Identitätstest
(beide Produktionsstellen nutzen dieselbe Funktion), 6 parametrisierte
Helper-Edge-Cases.

---

## 4. Testergebnisse

```
tests/test_download_utils_youtube_mix_url_detection.py:                     18 passed
tests/test_download_utils_retry.py:                                         10 passed
tests/test_download_handler_playlist_duplicate_registration.py:              7 passed
tests/test_download*.py tests/test_playlist*.py (thematische Suite):       212 passed
```

Vollständige Suite bewusst NICHT ausgeführt (verbindliche Teststrategie,
CLAUDE.md Abschnitt 8.A).

---

## 5. Abgrenzung zu PL-01

Keine Berührung: `download_single_track()`, dessen Retry-Schleife und der
Default `max_retries=1` wurden nicht verändert. Für `list=RD...`-URLs wird
nach diesem Fix `_process_single_download()` (Top-Level-Retry über
`enhanced_download_with_retry()`) statt `_process_playlist_download()`/
`download_single_track()` durchlaufen — beabsichtigte Konsequenz der
korrekten Klassifikation, keine Retry-Konfigurationsänderung. PL-01 bleibt
eigenständig offen.

---

## 6. Scope-Bestätigung

Keine Änderung an DUP-01/DUP-02/DUP-03/DUP-04/DUP-08-Code, DL-01/DL-02/
DL-06/DL-08-Code (jeweils per Diff verifiziert — identische Diff-Statistiken
vor/nach diesem Fix für alle nicht direkt betroffenen Dateien).

---

## 7. Abschluss

DUP-06 gilt hiermit als **technisch abgeschlossen**, Tests grün,
Vor-Fix-Diskriminierung nachträglich, aber vollständig nachgewiesen. Kein
Commit, kein Push (Stand zum Zeitpunkt dieses Dokuments weiterhin
uncommitted im Working Tree). Der Gesamtstatus der übergeordneten
`docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md` bleibt **PLANNED**.
