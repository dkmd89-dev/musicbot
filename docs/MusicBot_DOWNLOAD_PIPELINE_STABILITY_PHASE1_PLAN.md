# MusicBot — Download Pipeline Stability Phase — PHASE 1 Plan

> Read-only Priorisierungs- und Fix-Plan-Phase gemäß
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`. Basis:
> `docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE0_AUDIT.md`
> (Commit `29ed994`). **Keine Codeänderungen in dieser Phase.**

---

## 1. Executive Summary

Der Phase-0-Audit ist vollständig analysiert. **Korrektur gegenüber Phase 0:**
die dortige Executive Summary nannte „P1: 7", tatsächlich sind in Abschnitt 30
des Phase-0-Dokuments nur **6** vollständig spezifizierte P1-Findings enthalten
(DUP-01, DL-01, DL-02, DUP-02, DUP-03, DUP-05) — ein Zähl-/Redaktionsfehler
aus Phase 0, hier korrigiert, nicht verschwiegen. Die Codeanalyse in dieser
Phase hat kein siebtes, bisher unbenanntes P1 zutage gefördert; sie hat aber
ein P2 (PL-01) zu einem **De-facto-Teil derselben Baustelle wie DL-02**
gemacht (siehe Abschnitt 4/6) und ein weiteres P2 (DUP-07) als direkt von
DUP-01/DUP-02 abhängig eingestuft.

Drei der sechs P1-Findings (DUP-01, DUP-02, DUP-05) betreffen denselben
funktionalen Bereich (Duplicate Registration/Matching) und wurden auf
Abhängigkeiten geprüft (Abschnitt 5). Zwei (DL-01, DL-02) betreffen denselben
Cleanup-Mechanismus, bleiben aber aus Gründen unterschiedlicher Fehlerklassen
(Cancellation vs. reguläre Exception) bewusst getrennte Fixes (Abschnitt 6).
DUP-03 ist unabhängig und semantisch eigenständig.

**Empfehlung für PHASE 2:** 5 von 6 P1-Findings sollten behoben werden
(DUP-01, DUP-02, DL-01, DL-02, DUP-03), in dieser Reihenfolge, plus zwei eng
verwandte P2 (PL-01 zusammen mit DL-02, DUP-07 wird durch DUP-01/DUP-02
automatisch mitbehoben — kein eigener Fix nötig). DUP-05 wird als bewusst
akzeptiertes Risiko vorgeschlagen (Begründung Abschnitt 3/13). Die übrigen
P2 werden zurückgestellt (Begründung Abschnitt 13). P3 wird nicht angefasst.

---

## 2. Ausgangslage

```
Baseline:        v5 (1123 passed / 0 failed, Freeze APPROVED)
Phase-0-Commit:  29ed994e55ae3786c9141d08c8e0029b9bf01823
Working Tree:    sauber (verifiziert nach Phase-0-Commit)
Findings:        0 P0 / 6 P1 (siehe Korrektur oben) / 8 P2 / 3 P3
```

Zusätzlich für diese Phase gegen den **aktuellen** Code neu verifiziert (nicht
nur aus Phase 0 übernommen):

- `services/downloader/download/models.py::DownloadResult` hat **kein
  `url`-Feld** — direkt relevant für den DUP-01-Fix (Abschnitt 8).
- `services/downloader/playlist_processor.py::process_playlist_metadata()`
  baut `processed_track = track.copy()` — die rohen yt-dlp-Playlist-Entry-Felder
  (u. a. `webpage_url`/`url`/`id`) bleiben bis `track_info` erhalten, gehen aber
  auf dem Weg zu `MetadataResult`/`DownloadResult` verloren (kein Mapping
  vorhanden) — direkt relevant für den DUP-01-Fix.
- `services/downloader/download/download_executor.py::find_downloaded_file()`
  existiert bereits (2-Strategien-Dateisuche: `requested_downloads[0].filepath`
  → Fallback Template-Rekonstruktion aus `ydl_opts["outtmpl"]`) — wiederverwendbar
  für DL-02, kein neuer Mechanismus nötig.
- `enhanced_metadata_processor.py`s cancellation-anfälliges Fenster reicht von
  Zeile ~844 (`move_to_library()`, danach nicht mehr abbrechbar) bis Zeile
  ~1043 (Ende Auto-Learning, `await self.auto_learn_manager.learn_genre(...)`
  bei ~995 ist ein weiterer Cancellation-Punkt NACH dem Move).
- `tests/test_duplicate_handler.py` ruft `register_download()` in >8 Tests
  direkt mit bereits einfachen Test-Strings auf — eine Normalisierung
  innerhalb `register_download()` ist auf diesen Strings ein No-op (keine
  Klammern/Sonderzeichen), Tests bleiben bei korrekter Umsetzung unberührt
  (muss in PHASE 2 trotzdem verifiziert werden, nicht nur angenommen).

---

## 3. Finding Overview (alle 17 Findings, neu bewertet)

| ID | Phase-0-Prio | Phase-1-Prio | Geändert? | Kurzbegründung |
|---|---|---|---|---|
| DUP-01 | P1 | **P1** | nein | Playlist-Tracks nie registriert — direkter, deterministischer Blindspot, hohe Nutzerwirkung (jede Playlist betroffen) |
| DL-01 | P1 | **P1** | nein | Cancellation-Cleanup fehlt komplett, Risiko permanent inkonsistenter Library-Dateien |
| DL-02 | P1 | **P1** | nein | Kein Cleanup bei yt-dlp/FFmpeg-internem Fehler, bestätigt kein Import vorhanden |
| DUP-02 | P1 | **P1** | nein | Untergräbt Finding 1 aus v5 strukturell, bestätigt an >1 Normalisierungs-Pfad |
| DUP-03 | P1 | **P1** | nein | Konkret konstruierbarer False Positive, Nutzer kann legitime Version nicht laden |
| DUP-05 | P1 | **P1 (aber: bewusst zurückgestellt, s. Abschnitt 13)** | Einstufung bleibt P1, Umsetzung wird verschoben | Vorbestehende Race, kein Datenverlust, `renamed_due_to_conflict`-Mechanismus fängt das Resultat bereits ab |
| DL-03 | P2 | **P2** | nein | Ressourcenverschwendung, keine Korrektheitsgefahr |
| DL-04 (.part/.ytdl) | P3 (DEFER, akzeptiert) | **P3, unverändert akzeptiert** | nein | Bewusste Alt-Entscheidung, kein neuer Befund |
| PL-01 | P2 | **P2, aber gekoppelt an DL-02-Fix-Gruppe** | Kopplung neu erkannt | Kein Track-Retry heißt: JEDER transiente Playlist-Track-Fehler landet im DL-02-Cleanup-Pfad — beide Fixes teilen denselben Codeabschnitt |
| DUP-04 (feat./ft.-Regex) | P2 | **P2** | nein | Kleinerer False-Negative-Fall, unabhängig fixbar |
| DUP-06 (Mix/Radio-Playlists) | P2 | **P2** | nein | Konsistentes (nicht kaputtes) Verhalten, nur eine Abdeckungslücke |
| DUP-07 (Library-Fallback abhängig vom Probe) | P2 | **P2 → wird durch DUP-01/DUP-02 automatisch mitbehoben** | Abhängigkeit neu erkannt | Kein eigener Fix nötig, siehe Abschnitt 5 |
| RES-01 (is_duplicate Singleton-Scope) | P2 | **P2** | nein | Verwirrungsrisiko, keine Korruption |
| RES-02 (Cover-Cache nicht atomar) | P2 | **P2** | nein | Außerhalb des Scopes dieser Phase (Cover = Metadata-Bereich), nur zur Vollständigkeit gelistet |
| DL-05 (Metadata-Fehler wird retried) | P2 | **P2** | nein | Ressourcenverschwendung, keine Korrektheitsgefahr |
| DOC-01 (inkonsistente Dict-Form) | P3 | **P3** | nein | Aktuell folgenlos |
| (Phase-0-Executive-Summary-P1-Zähler) | „7" | **6 (korrigiert)** | ja | Redaktionsfehler Phase 0, siehe Abschnitt 1 |

---

## 4. Abhängigkeiten

### Gruppe „Duplicate Registration/Matching" (DUP-01, DUP-02, DUP-05, DUP-07)

```text
DUP-01 (Playlist-Tracks werden nie registriert)
   │
   │  Fix für DUP-01 MUSS register_download() für Playlist-Tracks aufrufen
   │  → automatisch UNTER derselben Hash-Bildung wie beim Single-Pfad
   ▼
DUP-02 (inkonsistente Hash-Normalisierung Check vs. Register)
   │
   │  Wird DUP-01 VOR DUP-02 gefixt, registriert der neue Playlist-Code
   │  denselben inkonsistenten (un-normalisierten) Hash wie der bestehende
   │  Single-Pfad → verdoppelt das DUP-02-Problem statt es zu lösen.
   │  Wird DUP-02 VOR DUP-01 gefixt, registriert der (noch nicht existierende)
   │  Playlist-Code von Anfang an korrekt.
   ▼
   ⇒ REIHENFOLGE ZWINGEND: DUP-02 vor DUP-01.
```

- **DUP-05** (Race) ist von DUP-01/DUP-02 **unabhängig** — die Race betrifft den
  zeitlichen Abstand zwischen Check und Register, nicht die Korrektheit der
  Hash-Bildung selbst. Kann in beliebiger Reihenfolge relativ zu DUP-01/DUP-02
  behandelt werden (hier: zurückgestellt, siehe Abschnitt 13).
- **DUP-07** (Library-Fallback hängt vom Probe-Erfolg ab) ist **kein eigenständiger
  Fix** — es beschreibt denselben Datenfluss, den DUP-01 (Registrierung) und
  die bestehende Finding-1-Logik (Probe) bereits abdecken. Sobald DUP-01/DUP-02
  behoben sind, verbessert sich die Trefferquote des Library-Fallbacks als
  Nebeneffekt (mehr korrekt registrierte Einträge → weniger Abhängigkeit vom
  Dateisystem-Scan als letzte Instanz). Kein separater Regressionstest nötig,
  aber in DUP-01/DUP-02s Testplan mit abgedeckt.

### Gruppe „Cancellation/Cleanup" (DL-01, DL-02, PL-01, DL-04, DL-05)

```text
DL-01 (Cancellation, kein Cleanup) und DL-02 (regulärer Fehler innerhalb
yt-dlp/FFmpeg, kein Cleanup) betreffen ZWEI STRUKTURELL VERSCHIEDENE
Fehlerklassen (BaseException vs. Exception), aber denselben Werkzeugkasten
(cleanup_single_download_artifact(), find_downloaded_file()).

   DL-02 (Exception-Pfad)              DL-01 (Cancellation-Pfad)
        │                                      │
        │  beide nutzen/erweitern dieselbe     │
        │  Cleanup-Infrastruktur               │
        ▼                                      ▼
   gemeinsame technische Basis: download_artifact_cleanup.py
   (ggf. um eine LIBRARY_DIR-Variante erweitert, s. Abschnitt 8)

   Bewusst GETRENNTE Fixes (nicht zusammenlegen):
   - DL-02 braucht KEIN Wissen über move_to_library()-Zustand
     (Fehler passiert VOR jeder Metadatenverarbeitung).
   - DL-01 braucht Wissen darüber, OB move_to_library() bereits gelaufen ist
     (DOWNLOAD_DIR- vs. LIBRARY_DIR-Cleanup) — komplexere Fallunterscheidung.
   - Vermischung würde die "kleinste sinnvolle Änderung" pro Fix verletzen.
```

- **PL-01** (kein Playlist-Track-Retry) ist **kein eigenständiges P1**, aber
  faktisch an DL-02 gekoppelt: weil Playlist-Tracks nicht retried werden,
  landet JEDER transiente Fehler (Netzwerk-Hänger etc.) sofort im selben
  Code-Pfad, den DL-02 adressiert (`download_utils.py`s per-Track-`except`).
  Sollte DL-02s Cleanup-Fix dort ansetzen, deckt er automatisch auch die
  Playlist-Situation mit ab — PL-01 selbst (Retry-Fähigkeit hinzufügen)
  bleibt trotzdem ein separates, unabhängig entscheidbares P2 (siehe
  Abschnitt 13).
- **DL-04** (.part/.ytdl nie gelöscht) ist eine bewusste Alt-Entscheidung,
  von DL-01/DL-02 unberührt — kein Zusammenhang.
- **DL-05** (Metadata-Fehler wird retried) ist unabhängig von DL-01/DL-02 (andere
  Fehlerursache: Metadatenverarbeitung nach erfolgreichem Download, nicht
  der Download selbst).

### DUP-03 (False Positives bei Live/Version)

Unabhängig von allen anderen Findings — reine Normalisierungslogik innerhalb
`_clean_title_for_comparison()`. Berührt denselben Funktionsbereich wie DUP-02
(beide in `detector.py`), aber unterschiedliche Methoden/Codepfade — kann
parallel oder in beliebiger Reihenfolge relativ zu DUP-02 gefixt werden. Hier:
nach DUP-02, weil beide Fixes potenziell dieselbe Testdatei
(`tests/test_duplicate_handler.py`/neue Detector-Tests) berühren und eine
gemeinsame Regressionsbetrachtung sinnvoller ist als zwei getrennte Durchläufe.

---

## 5. Zusammenhang mit bereits geschlossenen Baseline-v5-Fixes

| Bereits geschlossener Fix (v5) | Wird durch neues Finding untergraben? | Erklärung |
|---|---|---|
| Finding 1 — Pre-Download Artist/Titel-Probe | **Teilweise, durch DUP-02** | Der Probe liefert korrekte, saubere Rohdaten an `check_for_duplicates()` — das Problem liegt NICHT im Probe selbst (der bleibt unverändert korrekt), sondern darin, dass `register_download()` (aufgerufen NACH dem Download, mit den vom Metadata-Prozessor bereits anders bereinigten Werten) eine andere Normalisierung durchläuft als der Check. **Der ursprüngliche Fix wird nicht neu implementiert** — nur `register_download()` erhält zusätzlich dieselbe Normalisierungsfunktion wie `check_for_duplicates()`, bevor der Hash gebildet wird. Der bestehende Regressionstest `test_download_handler_duplicate_check_artist_title_probe.py` bleibt unverändert gültig (er prüft den Probe-Aufruf, nicht die Registrierung) und muss nach dem DUP-02-Fix weiterhin grün sein. |
| Finding 2 — `renamed_due_to_conflict`-Signal | **Nicht untergraben, aber unvollständig** — bestätigt bereits in Phase 0 als für Playlists nie erreichbar (weil `results_list` für Playlists nur den Wrapper enthält). Das ist **kein neues Finding dieser Phase**, sondern eine in Phase 0 bereits dokumentierte Lücke, die im aktuellen Findings-Katalog jedoch **fehlt** — sie wurde im Cleanup-Kapitel (29.5) und in der Runtime-Flow-Beschreibung (29.2) erwähnt, aber nie als eigenständiges Finding mit ID versehen. **Nachtrag hier:** wird als **DUP-08** (neu vergebene ID, siehe Abschnitt 6) nachgetragen, da es denselben funktionalen Bereich wie DUP-01 betrifft und im selben Zug behoben werden sollte. |
| Finding 3 — Fanart-API-Key-Scrubbing | Nein | Unabhängiger Bereich (Security/Cover), von dieser Phase nicht berührt. |
| Enforcement Fix Phase (auto_learn.py, duplicate/cache.py INV-02, user_management_handler.py, backup/status INV-01) | Nein | Kein neues Finding widerspricht diesen Fixes. `duplicate/cache.py`s atomare Schreibweise bleibt unverändert korrekt (siehe Phase-0-Bestätigung „Confirmed fine"). |
| AE-10/AE-11/AE-12 | Nein | Außerhalb des Scopes dieser Phase, in Phase 0 direkt im Code re-verifiziert, unverändert intakt. |

### Nachtrag: DUP-08 (neue ID für die bereits in Phase 0 beschriebene, aber nicht separat benannte Playlist-`renamed_due_to_conflict`-Lücke)

Da Phase 0 diesen Punkt bereits inhaltlich vollständig beschrieben hat (Abschnitt
29.5 „PARTIAL PLAYLIST SUCCESS" und die Runtime-Flow-Beschreibung), aber ohne
eigene Finding-ID im Abschnitt 30, wird er hier zur Klarheit als **DUP-08 — P1**
nachgetragen (keine neue Codeanalyse nötig, vollständig durch Phase 0 belegt):
`klassen/download_handler.py::handle_youtube_links()` prüft
`res.get("renamed_due_to_conflict")` nur auf `results_list`-Elementen — für
Playlists ist `results_list` immer `[wrapper_dict]`, das Flag liegt aber nur in
`wrapper_dict["tracks"][i]`. **Das erklärt auch, warum in der Phase-0-Executive-
Summary „7 P1" stand — DUP-08 war vermutlich mitgezählt, aber nie als
eigener Abschnitt ausformuliert.** Diese Korrektur schließt die in Abschnitt 1
offene Zähldifferenz vollständig auf.

**DUP-08 wird technisch im selben Fix wie DUP-01 behoben** (siehe Abschnitt 8) —
beide erfordern denselben strukturellen Eingriff: `handle_playlist_success()`
muss die einzelnen Track-Dicts aus `playlist_result["tracks"]` iterieren statt
nur den Wrapper zu betrachten.

---

## 6. Fix-Gruppen (aus dem Code abgeleitet)

### GROUP A — Playlist-Track-Konsistenz (Duplicate Registration + Collision-Signal)
- DUP-02 (zuerst — siehe Abhängigkeit Abschnitt 4)
- DUP-01
- DUP-08 (technisch selber Eingriffspunkt wie DUP-01)

*Grund für Gruppierung:* alle drei Fixes ändern `handle_playlist_success()`/die
Playlist-Track-Iteration in `klassen/download_handler.py` und/oder
`register_download()`/`detector.py` — technisch überlappende Änderungsorte,
sinnvoll in einer zusammenhängenden Fix-Runde.

### GROUP B — Download-Fehler-Cleanup
- DL-02 (zuerst, einfacherer Fall)
- DL-01 (danach, komplexere Fallunterscheidung DOWNLOAD_DIR vs. LIBRARY_DIR)

*Grund für Gruppierung:* teilen dieselbe Cleanup-Infrastruktur
(`download_artifact_cleanup.py`), bleiben aber laut Abschnitt 4 bewusst
getrennte Commits/Fixes innerhalb der Gruppe.

### GROUP C — Duplicate Matching Semantik
- DUP-03 (eigenständig)

### GROUP D — Concurrency
- DUP-05 (zurückgestellt, siehe Abschnitt 13 — kein aktiver Fix in PHASE 2)

Die Gruppierung folgt damit **nicht** exakt dem ursprünglichen Beispiel aus dem
Auftrag (dort waren DUP-01/DUP-02 in Group A UND DL-01/DL-02 in Group B
vorgeschlagen) — sie deckt sich aber inhaltlich, ergänzt um DUP-08 (aus der
Codeanalyse neu hinzugekommen) und die Erkenntnis, dass DUP-05 keinen eigenen
Implementierungs-Slot in PHASE 2 braucht.

---

## 7. Fix-Reihenfolge

### 1. DUP-02 — Hash-Normalisierung Check/Register angleichen

**Begründung:** Muss vor DUP-01 erfolgen (Abschnitt 4) — sonst würde der neue
Playlist-Registrierungscode denselben Fehler wie der bestehende Single-Pfad
übernehmen, statt ihn zu vermeiden.
**Abhängigkeiten:** Keine eingehenden. Ausgehend: blockiert DUP-01/DUP-08.
**Betroffene Dateien:** `services/duplicate/detector.py` (`register_download()`).
**Regressionstest:** Content-Hash bei Check und Registrierung muss für
denselben (rohen) Artist/Titel identisch sein, auch wenn einer davon
Klammerzusätze enthält, die `_clean_title_for_comparison()` normalerweise
entfernt.

### 2. DUP-01 + DUP-08 — Playlist-Track-Registrierung + Collision-Signal

**Begründung:** Größte Nutzerwirkung (jede Playlist betroffen), technisch nach
DUP-02 sauber umsetzbar, beide Findings teilen denselben Eingriffspunkt.
**Abhängigkeiten:** Setzt DUP-02 voraus.
**Betroffene Dateien:** `klassen/download_handler.py`
(`handle_playlist_success()`), `services/metadata/models.py`
(`MetadataResult` — neues `url`-Feld), `services/downloader/download/models.py`
(`DownloadResult` — neues `url`-Feld), `services/downloader/metadata_result_translator.py`
(beide Builder-Funktionen), `services/metadata/enhanced_metadata_processor.py`
(Quelle für `url` beim `MetadataResult`-Aufbau, aus `track_metadata`/`track_info`).
**Regressionstest:** (a) Playlist mit 2 Tracks erfolgreich verarbeiten →
`DuplicateCache` enthält 2 neue, korrekt gehashte Einträge; erneuter
Einzel-Download desselben Tracks wird als Duplikat erkannt. (b) Playlist-Track
mit Zieldateinamens-Kollision → Datei wird korrekt bereinigt und als Duplikat
gemeldet (nicht mehr dead code).

### 3. DL-02 — Cleanup bei yt-dlp-/FFmpeg-internem Fehler

**Begründung:** Einfacherer, unabhängiger Fall (kein Zustand aus vorherigen
Schritten zu berücksichtigen), etablierte Infrastruktur wiederverwendbar.
**Abhängigkeiten:** Keine.
**Betroffene Dateien:** `services/downloader/download_utils.py`
(`_process_single_download()`, Import + Aufruf von
`cleanup_single_download_artifact`, ggf. Nutzung von
`download_executor.find_downloaded_file()` zur Pfadermittlung).
**Regressionstest:** yt-dlp-Aufruf gezielt mit Exception mocken (Netzwerk,
FFmpeg) → `DOWNLOAD_DIR` muss danach leer sein.

### 4. DL-01 — Cancellation-Cleanup (semantisch korrekt, kein Verschlucken)

**Begründung:** Komplexester Fix dieser Phase (Fallunterscheidung
DOWNLOAD_DIR/LIBRARY_DIR je nach Cancellation-Zeitpunkt), daher zuletzt unter
den P1, mit der meisten Zeit für sorgfältige Umsetzung.
**Abhängigkeiten:** Keine harte Abhängigkeit zu 1-3, aber sinnvoll danach, da
derselbe Cleanup-Baustein (`download_artifact_cleanup.py`) ggf. um eine
LIBRARY_DIR-fähige Variante erweitert wird — nach DL-02 ist dessen
DOWNLOAD_DIR-seitiges Verhalten bereits frisch verifiziert.
**Betroffene Dateien:** `services/metadata/enhanced_metadata_processor.py`
(gezielter `try/except asyncio.CancelledError`-Block um die Schritte 17-19b,
mit `raise` am Ende — niemals Verschlucken), ggf.
`services/downloader/download_artifact_cleanup.py` (neue, kleine
LIBRARY_DIR-Cleanup-Funktion, analog zu `cleanup_single_download_artifact`).
**Regressionstest:** `process_single_track()` per `task.cancel()` mitten in
einem gemockten `write_tags()`-Aufruf abbrechen (NACH erfolgreichem
`move_to_library()`) → LIBRARY_DIR darf keine unvollständig getaggte Datei
ohne Cleanup zurücklassen; `CancelledError` muss beim Aufrufer ankommen
(nicht verschluckt).

### 5. DUP-03 — False-Positive-Fix bei Live/Version-Titeln

**Begründung:** Unabhängig, kleinster Eingriff, sinnvoll am Ende, da er
dieselbe Testdatei wie DUP-02 berührt (gemeinsame Regressionsbetrachtung).
**Abhängigkeiten:** Keine harte, aber inhaltlich verwandt mit DUP-02
(gleiche Datei `detector.py`).
**Betroffene Dateien:** `services/duplicate/detector.py`
(`_clean_title_for_comparison()`).
**Regressionstest:** `"Hello (Live at Glastonbury 2016)"` gegen bereits
registriertes `"Hello"` prüfen → darf NICHT als Duplikat gelten;
gleichzeitig muss der ursprüngliche Positivfall (echtes Reupload, z. B.
`"Song (Official Video)"` vs. `"Song"`) weiterhin als Duplikat erkannt werden
(Regressionsschutz gegen Überkorrektur).

---

## 8. Konkrete Fix-Spezifikation (Minimal-Scope)

### DUP-02

- **Datei:** `services/duplicate/detector.py`
- **Funktion:** `register_download()`
- **Minimale Änderung:** vor dem Aufbau des `DuplicateEntry` die bereits
  vorhandenen `_normalize_artist_for_comparison(artist)`/
  `_clean_title_for_comparison(title, normalized_artist)` anwenden und die
  normalisierten Werte für die Hash-Bildung verwenden (nicht zwingend für die
  im Cache angezeigten `artist`/`title`-Felder selbst — Anzeige-Werte können
  die Originalform behalten, nur die Hash-Eingabe muss konsistent sein).
- **Erwartete Verhaltensänderung:** Content-Hash von Check und Registrierung
  stimmen für dieselbe Aufnahme überein, auch bei unterschiedlicher
  Rohformatierung.
- **Bewusst NICHT geändert:** `get_content_hash()`/`get_url_hash()` selbst,
  `check_for_duplicates()`, Cache-Dateiformat, bestehende Cache-Einträge
  (keine Migration — alte, inkonsistent gehashte Einträge bleiben bestehen,
  neue werden korrekt gehasht; Altbestand wird nicht rückwirkend bereinigt,
  da außerhalb des Scopes „minimaler Fix").

### DUP-01 + DUP-08

- **Dateien:** `services/metadata/models.py`, `services/downloader/download/models.py`,
  `services/downloader/metadata_result_translator.py`,
  `services/metadata/enhanced_metadata_processor.py`, `klassen/download_handler.py`.
- **Minimale Änderung:**
  1. `MetadataResult` und `DownloadResult` um ein optionales `url: Optional[str] = None`
     erweitern.
  2. `enhanced_metadata_processor.py` befüllt es aus `track_metadata.get("webpage_url")`
     (bereits vorhandenes Feld, siehe `tests/conftest.py::sample_track_metadata`) beim
     `MetadataResult(...)`-Aufbau.
  3. Beide Translator-Builder reichen `url=metadata_result.url` durch.
  4. `handle_playlist_success()`: statt nur `handle_single_track_success(playlist_result)`
     aufzurufen, zusätzlich über `playlist_result.get("tracks", [])` iterieren und für
     jeden `track` mit `track.get("success")` sowohl
     `self.duplicate_detector.register_download(...)` (mit `track.get("url")`,
     `track.get("artist")`, `track.get("title")`, `track.get("library_path")`) als
     auch die bestehende `renamed_due_to_conflict`-Prüfung (identischer Code-Block
     wie im Single-Pfad, siehe `download_handler.py:684-704`) ausführen.
- **Erwartete Verhaltensänderung:** Playlist-Tracks werden wie Single-Downloads
  im `DuplicateCache` registriert; Kollisionen bei Playlist-Tracks werden
  erkannt und bereinigt.
- **Bewusst NICHT geändert:** `handle_single_track_success()` selbst (bleibt
  für den Single-Pfad unverändert, wird für Playlists nicht mehr mit dem
  Wrapper aufgerufen, sondern durch die neue Iteration ersetzt) — Verhalten
  für Single-Downloads bleibt exakt gleich.

### DL-02

- **Datei:** `services/downloader/download_utils.py`
- **Funktion:** `_process_single_download()`
- **Minimale Änderung:** Import von `cleanup_single_download_artifact` ergänzen;
  im bestehenden `except Exception as e:`-Block (vor dem Re-Raise als
  `DownloadError`) den erwarteten Zielpfad über
  `download_executor.find_downloaded_file(...)` (bereits vorhanden,
  Best-Effort, `None` bei Fehlschlag ist bereits vorgesehenes Verhalten der
  Funktion) ermitteln und `cleanup_single_download_artifact()` aufrufen.
- **Erwartete Verhaltensänderung:** Nach einem Fehler innerhalb des
  yt-dlp-/FFmpeg-Aufrufs bleibt `DOWNLOAD_DIR` sauber, sofern die Datei
  über eine der beiden bestehenden Strategien lokalisierbar ist.
- **Bewusst NICHT geändert:** die Retry-Schleife selbst, `DownloadError`,
  keine neue Fehlerklassifikation (das wäre DL-03, separat/zurückgestellt).

### DL-01

- **Datei:** `services/metadata/enhanced_metadata_processor.py`
- **Funktion:** `process_single_track()`
- **Minimale Änderung:** gezielter `try/except asyncio.CancelledError`-Block
  um den Bereich ab `move_to_library()` (Schritt 16) bis zum Ende der
  Funktion. Im `except`-Zweig: falls `library_path` existiert, aber die
  Tag-Schreib-Bestätigung noch nicht erfolgt ist, Datei löschen (analog zum
  bestehenden FINDING-2-Cleanup-Muster, Zeilen ~891-920), dann **zwingend
  `raise`** (Cancellation niemals verschlucken — der aufrufende Task muss
  weiterhin als „cancelled" erkennbar bleiben).
- **Erwartete Verhaltensänderung:** Cancellation nach erfolgreichem Move
  hinterlässt keine dauerhaft unvollständige Library-Datei mehr; Cancellation
  selbst bleibt für den Rest der asyncio-Infrastruktur sichtbar
  (kooperatives Cancellation-Modell bleibt intakt).
- **Bewusst NICHT geändert:** Cancellation VOR `move_to_library()`
  (DOWNLOAD_DIR-Fall) — dieser Fall ist bereits durch den 24h-Start-Sweep
  (`cleanup_download_artifacts()`) abgedeckt, kein akutes Risiko, kein
  zusätzlicher Eingriff nötig, um den Fix klein zu halten. Kein globales
  `except CancelledError: pass` irgendwo in der Pipeline.

### DUP-03

- **Datei:** `services/duplicate/detector.py`
- **Funktion:** `_clean_title_for_comparison()`
- **Minimale Änderung:** die beiden Regex `r"\(Live.*?\)"` und
  `r"\(.*?Version\)"` NICHT mehr vollständig entfernen, sondern den Inhalt
  als Teil des Vergleichsschlüssels beibehalten (z. B. nur generische,
  bedeutungsfreie Zusätze wie „Official Video"/„Lyrics" weiterhin per
  Positivliste entfernen, alles andere in Klammern unverändert lassen).
- **Erwartete Verhaltensänderung:** „Song" und „Song (Live)"/„Song (Acoustic
  Version)" erhalten unterschiedliche Content-Hashes.
- **Bewusst NICHT geändert:** die generische Klammerentfernung für
  tatsächlich bedeutungsfreie Zusätze bleibt (kein Rückbau der ursprünglich
  gewollten Content-Matching-Fähigkeit für echte Reuploads).

---

## 9. Regression-Test-Plan (Übersicht, Details je Fix in Abschnitt 8/7)

| Finding | Testtyp | Neue Datei oder Erweiterung bestehender Datei | Reproduziert Fehler vor Fix? |
|---|---|---|---|
| DUP-02 | Unit | Erweiterung `tests/test_duplicate_handler.py` oder neue `tests/test_duplicate_detector_hash_consistency.py` | Ja — Test muss vor Fix fehlschlagen (unterschiedliche Hashes) |
| DUP-01/DUP-08 | Integration | Neue `tests/test_download_handler_playlist_duplicate_registration.py`, nutzt etablierte `object.__new__(DownloadHandler)`-Musterweise | Ja |
| DL-02 | Unit | Erweiterung `tests/test_download_utils_metadata_translation.py` oder neue Datei für `_process_single_download` Fehlerpfad | Ja |
| DL-01 | Integration (async, `task.cancel()`) | Neue `tests/test_enhanced_metadata_processor_cancellation.py` | Ja |
| DUP-03 | Unit | Erweiterung derselben Datei wie DUP-02 | Ja |

Jeder Test folgt dem etablierten Session-Standard: `git stash`-Diskriminierung
gegen den Vor-Fix-Stand in PHASE 2, keine Timing-basierten Tests wo
deterministisch möglich (insbesondere DL-01 nutzt `task.cancel()` statt
`asyncio.sleep`-Racing).

---

## 10. Test-Abhängigkeiten

Alle geplanten Tests können auf bestehender Infrastruktur aufbauen — **keine
neue Test-Infrastruktur nötig:**

- `object.__new__(DownloadHandler)`-Muster (bereits etabliert in
  `test_download_handler_youtube_pipeline_failure_reporting.py`,
  `test_download_handler_duplicate_check_artist_title_probe.py`) für DUP-01/DUP-08.
- `TagWriter`/`CoverProcessor`-Mocking-Muster aus
  `test_metadata_processor_happy_path.py` für DL-01 (Cancellation mitten in
  einem gemockten `write_tags()`).
- `monkeypatch`+`pytest.raises`-Muster aus `test_tag_writer_atomic_replace.py`
  für DL-02 (Exception-Injection in den yt-dlp-Aufruf).
- Reine Unit-Tests (kein Mock nötig) für DUP-02/DUP-03, direkt gegen
  `DuplicateDetector`/`DuplicateCache`-Instanzen mit `tmp_path`.
- Kein neues Test-Framework, kein neuer Fixture-Typ, keine neue CI-Integration
  nötig.

---

## 11. Risikoanalyse

| Finding | Regression Risk | Complexity | Scope | Testability |
|---|---|---|---|---|
| DUP-02 | LOW | LOW | SMALL (1 Funktion, 1 Datei) | HIGH |
| DUP-01/DUP-08 | MEDIUM | MEDIUM | MEDIUM (5 Dateien, aber additive Felder + eine neue Iterationsschleife) | HIGH |
| DL-02 | LOW | LOW | SMALL (1 Funktion, 1 Datei) | HIGH |
| DL-01 | MEDIUM | MEDIUM-HIGH | SMALL-MEDIUM (1 Funktion, aber async/Cancellation-Semantik erfordert Sorgfalt) | MEDIUM (Cancellation-Timing in Tests erfordert `task.cancel()` statt Sleep-Racing, aber etablierte Muster aus AE-10/AE-12 dieser Session sind übertragbar) |
| DUP-03 | LOW-MEDIUM | LOW | SMALL (1 Funktion, 1 Datei) | HIGH, aber Regressionsschutz gegen Überkorrektur (echte Reuploads dürfen weiter erkannt werden) nötig |

**Größtes Gesamtrisiko der Phase:** DL-01 — nicht wegen Umfang, sondern weil
eine falsch verstandene Cancellation-Behandlung (versehentliches Verschlucken)
das kooperative asyncio-Cancellation-Modell der gesamten Anwendung
beeinträchtigen könnte. Deshalb in PHASE 2 als letzter P1-Fix vorgesehen (nach
Erfahrung mit den einfacheren Fixes) und mit explizitem Re-Raise-Gebot.

---

## 12. PHASE-2-Scope

### PHASE 2 SHOULD IMPLEMENT

1. DUP-02 — Hash-Normalisierung angleichen
2. DUP-01 + DUP-08 — Playlist-Track-Registrierung + Collision-Signal
3. DL-02 — Cleanup bei yt-dlp-/FFmpeg-internem Fehler
4. DL-01 — Cancellation-Cleanup (semantisch korrekt)
5. DUP-03 — False-Positive-Fix Live/Version

### PHASE 2 SHOULD NOT IMPLEMENT

1. DUP-05 (Check-then-Register-Race) — kein Datenverlust, bereits durch
   `renamed_due_to_conflict` abgefedert, würde Lock-Scope-Entscheidungen
   erfordern, die über „minimaler Fix" hinausgehen.
2. PL-01 (Playlist-Track-Retry) — echte neue Fähigkeit (Retry-Logik
   hinzufügen), kein Bugfix eines bestehenden fehlerhaften Verhaltens; wird
   durch DL-02 in seiner Auswirkung entschärft, ohne selbst gefixt zu werden.
3. DUP-04 (feat./ft.-Regex) — kleinerer False-Negative, kein akuter
   Stabilitätsschaden, sinnvoller als eigener kleiner Folge-Fix nach
   Beobachtung der DUP-03-Auswirkung.
4. DUP-06 (Mix/Radio-Playlist-Bypass) — konsistentes, kein kaputtes
   Verhalten, reine Abdeckungslücke.
5. RES-01, RES-02, DL-03, DL-05 — siehe Abschnitt 13.

### DEFERRED

1. DUP-05, PL-01, DUP-04, DUP-06, RES-01, RES-02, DL-03, DL-05 (alle P2)
2. DL-04, DOC-01 und der dritte, in Phase 0 nicht einzeln benannte P3-Punkt
   (alle P3 — bewusst nicht angefasst, siehe Abschnitt 14)

---

## 13. Begründung der P2-Einstufungen (A/B/C/D je Finding)

| Finding | Einstufung | Begründung |
|---|---|---|
| DL-03 (keine Fehlerklassifikation) | **C** — bewusste technische Schuld | Ressourcenverschwendung, keine Korrektheitsgefahr; würde eine echte Fehlerklassifikations-Logik erfordern (String-Matching auf yt-dlp-Fehlermeldungen o. Ä.) — das ist mehr als „kleinster Fix", eigene künftige Entscheidung. |
| PL-01 (kein Playlist-Retry) | **B** — nach den P1 separat behandelbar, aber nicht in dieser Phase | Echte Fähigkeitserweiterung, kein Bugfix; durch DL-02 in der Auswirkung entschärft (Cleanup verhindert wenigstens Datei-Reste bei den durch fehlenden Retry häufigeren Fehlschlägen). |
| DUP-04 (feat./ft.-Regex) | **B** | Eigenständig, klein, aber bewusst NACH DUP-03 zu betrachten (gleiche Methode, um nicht zwei sich potenziell überschneidende Regex-Änderungen gleichzeitig zu machen und dadurch Regressionen schwerer zuordenbar zu machen). |
| DUP-06 (Mix/Radio-Playlists) | **C** | Konsistentes Verhalten (kein Fehlverhalten), reine Abdeckungslücke — akzeptabel als bekannte Grenze. |
| DUP-07 (Library-Fallback abhängig vom Probe) | **D** — automatisch durch DUP-01/DUP-02 mitgelöst | Siehe Abschnitt 4/5, kein eigener Fix nötig. |
| RES-01 (is_duplicate Singleton-Scope) | **C** | Verwirrungsrisiko, keine Korruption; Fix würde den Scope/Lifecycle des Singletons berühren — außerhalb „kleinster Fix" ohne weitere Untersuchung, die außerhalb dieser Phase liegt. |
| RES-02 (Cover-Cache nicht atomar) | **C** | Explizit Metadata/Cover-Bereich — außerhalb des Scopes dieser Phase per Definition (Abschnitt 3 des Phasendokuments). |
| DL-05 (Metadata-Fehler wird retried) | **C** | Ressourcenverschwendung, keine Korrektheitsgefahr; hängt mit DL-03 zusammen (beide bräuchten Fehlerklassifikation) — gemeinsam zurückgestellt. |

DUP-05 wird trotz P1-Einstufung wie ein bewusst akzeptiertes Risiko behandelt
(Sonderfall, siehe Abschnitt 1/12) — Begründung: kein Datenverlust, das
Resultat einer Race (zwei parallele Downloads derselben Aufnahme) wird bereits
durch die `renamed_due_to_conflict`-Kollisionsbehandlung sauber aufgefangen
(nach dem DUP-01/DUP-08-Fix sogar für Playlists). Ein Lock-basierter Fix
würde Scope/Lifetime/Deadlock-Analyse erfordern, die den Rahmen eines
„kleinsten sinnvollen Fixes" sprengt — als eigene, spätere Entscheidung
markiert, nicht in PHASE 2 umgesetzt.

---

## 14. Deferred Findings (P3, unverändert)

Alle 3 P3-Findings (DL-04, DOC-01, sowie das implizite dritte — bei
Durchsicht von Abschnitt 30 des Phase-0-Dokuments ist nur DOC-01 explizit als
P3 benannt; DL-04 wurde in Phase 0 als „P3 (DEFER, bereits akzeptiert)" in der
Kurzliste geführt. **Auch hier eine Zähl-Ungenauigkeit aus Phase 0**: die
Executive Summary nennt „P3: 3", die Kurzliste enthält aber nur 2 explizit
als P3 markierte Zeilen (DL-04, DOC-01) — der dritte P3 ist vermutlich die
bereits in Baseline v5 als DEFER geführte „`.info.json`-Reste"-Altlast, die
in Phase 0 nicht erneut mit eigener ID aufgeführt wurde, sondern implizit
Teil von DL-04 ist. Auch das wird hier transparent gemacht statt
stillschweigend übernommen.)

Keine P3-Fixes in PHASE 2. Alle bleiben aus den in Phase 0 bereits genannten
Gründen (bewusste Alt-Entscheidungen bzw. rein kosmetisch, keine
Funktionsauswirkung) zurückgestellt.

---

## 15. Erwartete Abschlusskriterien (für PHASE 2, zur Orientierung)

```
[ ] DUP-02 implementiert + Regressionstest grün
[ ] DUP-01 + DUP-08 implementiert + Regressionstests grün
[ ] DL-02 implementiert + Regressionstest grün
[ ] DL-01 implementiert + Regressionstest grün (inkl. Nachweis: CancelledError
    wird weiterhin korrekt propagiert, nicht verschluckt)
[ ] DUP-03 implementiert + Regressionstest grün (inkl. Nicht-Überkorrektur-Test)
[ ] Jeder Fix einzeln per git-stash-Diskriminierung gegen Vor-Fix-Stand verifiziert
[ ] Vollständige Testsuite grün (Basis: 1123 passed / 0 failed aus v5)
[ ] Keine Metadata-Qualitätsthemen angefasst
[ ] Architecture Freeze bleibt erhalten
[ ] Verbleibende P2/P3 explizit dokumentiert (nicht stillschweigend fallengelassen)
```

---

## Explicit Non-Actions (PHASE 1)

```
[x] Kein Produktionscode geändert
[x] Keine Tests geändert
[x] Keine Refactorings
[x] Keine Fixes implementiert
[x] Keine neuen Features
[x] Keine Metadata-Optimierungen
[x] Keine Architekturänderungen
[x] Kein Push
[x] Keine PR
```
