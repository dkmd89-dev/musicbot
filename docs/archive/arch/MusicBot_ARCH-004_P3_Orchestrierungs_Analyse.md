# ARCH-004 — P-3: Doppelte Spotify/YouTube-Orchestrierung (Analyse)

> Reine Analyse, kein Code geändert. Vertiefung von P-3 aus
> `docs/MusicBot_ARCH-003_Services_Phase1_Analyse.md` — dort nur grob
> charakterisiert, hier vollständig end-to-end nachvollzogen.

## 0. Ergebnis in einem Satz

P-3 ist **kein doppelter Download/Orchestrierungs-Pfad im groben Sinne**
(beide Pipelines laufen durch denselben Dispatcher, dieselbe
Duplicate-Detection, dieselbe `EnhancedMetadataProcessor`-Singleton-Instanz
und dieselben `handle_playlist_success`/`handle_single_track_success`-Methoden)
— sondern **zwei unabhängig gewachsene Implementierungen genau einer
einzigen, schmalen Integrationsschicht**: „nimm ein rohes Download-Ergebnis-
Dict entgegen, bereite es zu `track_metadata` auf, rufe
`EnhancedMetadataProcessor.process_single_track()` auf, übersetze das
`MetadataResult` zurück in ein flaches Dict". Diese Integrationsschicht
existiert einmal sauber in `services/` (für YouTube) und einmal in `klassen/`
(für Spotify, faktisch der einzige Ort, an dem sie für Spotify-Tracks
überhaupt läuft).

---

## 1. End-to-End-Nachvollzug beider Pipelines

### YouTube

```text
klassen/download_handler.py::handle_url()
  → handle_youtube_links()
      → self.downloader.download_audio(url)          [services/downloader/downloader.py]
          → enhanced_download_with_retry()             [services/downloader/utils/download_utils.py]
              → _process_playlist_download() / _process_single_download()
                  → _process_track_metadata()           ← ECHTE Metadaten-Orchestrierung,
                      → enhanced_metadata_processor        vollständig innerhalb services/
                          .process_single_track()
                  → DownloadResult(...).to_dict()         [KEIN "filepath"-Feld im Schema!]
      → pro Ergebnis: self._process_single_download_result(res)
          → Schritt B "Doppelverarbeitungs-Schutz":
            library_path gesetzt UND filepath NICHT gesetzt
            → gilt als "bereits verarbeitet" → return result (No-Op)
      → handle_playlist_success() / handle_single_track_success()
```

### Spotify

```text
klassen/download_handler.py::handle_url()
  → handle_spotify_url()
      → self.spotify_downloader.download(url)          [services/downloader/spotify_downloader.py]
          → NUR Metadaten (Spotify-Embed-API) + Audio-Beschaffung
            (RSS-Feed ODER yt-dlp-Fallback) - KEIN Aufruf von
            EnhancedMetadataProcessor, kein ArtistNormalizer/GenreProcessor/
            CoverProcessor/TagWriter innerhalb von services/downloader/
            spotify_downloader.py (verifiziert: 0 Treffer für mutagen/
            TagWriter/GenreProcessor/CoverProcessor/LyricsProcessor/
            ArtistNormalizer/AlbumProcessor in dieser Datei)
          → Rohes Dict mit u.a. "filepath" (aus yt-dlp) UND OHNE
            "library_path" - sowie Spotify-spezifischen Zusatzfeldern
            is_podcast/podcast_name
      → pro Ergebnis: self._process_single_download_result(res)
          → Schritt B: library_path fehlt → NICHT "bereits verarbeitet"
          → Schritt C: filepath-Fallback-Suche (eigene Logik, ~15 Zeilen)
          → Schritt D: Podcast-Episodennummer-Korrektur (Spotify-spezifisch)
          → Schritt E: playlist_metadata-Aufbau aus is_podcast/podcast_name
            (Spotify-spezifisch — YouTube kennt diese Felder nicht)
          → Schritt F: Cover-Art-Transparenz-Logging
          → Schritt G: ECHTER Aufruf von
            self.enhanced_metadata_processor.process_single_track(...)
            — hier, und NUR hier, findet für Spotify-Tracks die eigentliche
            Metadaten-Anreicherung statt
      → handle_playlist_success() / handle_single_track_success()
```

**Gemeinsam genutzt (kein Duplikat):** Dispatcher (`handle_url`), Duplicate-
Detection (`_check_duplicates_before_download`), die
`EnhancedMetadataProcessor`-Instanz selbst (Singleton — beide Pipelines
teilen sich denselben Cache/dieselben Stats), `handle_playlist_success()`/
`handle_single_track_success()`, `_process_single_download_result()` als
Funktion (wird von beiden Pipelines aufgerufen — nur mit unterschiedlichem
Ergebnis, je nachdem ob der YouTube-Pfad schon vorverarbeitet hat).

---

## 2. Was ist echtes Duplikat, was ist legitime Divergenz?

| Teil | YouTube (`download_utils.py::_process_track_metadata`) | Spotify (`download_handler.py::_process_single_download_result`, Schritt G) | Bewertung |
|---|---|---|---|
| `track_metadata`-Dict aufbauen | eigene, YouTube-Feld-Namen (`uploader`, `playlist_channel`, …) | eigene, Spotify-Feld-Namen (`is_podcast`, `podcast_name`, …) | **Legitime Divergenz** — unterschiedliche Rohdaten-Schemas (yt-dlp-Playlist-Entry vs. Spotify-Embed-API-Antwort) |
| `process_single_track()`-Aufruf + `MetadataResult`→Dict-Rückübersetzung | vorhanden, ~50 Zeilen | vorhanden, ~50 Zeilen (Schritt G) | **Echtes Duplikat** — dieselbe Übersetzungslogik zweimal unabhängig gepflegt |
| Podcast-Spezialkanal-Erkennung | passiert INTERN in `EnhancedMetadataProcessor` über Channel-Namen-Matching (`_is_podcast_channel`) | passiert VORGELAGERT in `klassen/` über explizite `is_podcast`/`podcast_name`-Felder, baut `playlist_metadata` selbst | **Legitime Divergenz**, aber zwei verschiedene Erkennungsmechanismen für dasselbe Konzept ("ist das ein Podcast?") an zwei verschiedenen Stellen der Pipeline |
| „Bereits verarbeitet"-Erkennung (Schritt B) | n/a (läuft nie zweimal) | `library_path gesetzt AND filepath NICHT gesetzt` | **Fragil**: impliziter Vertrag zwischen zwei Schema-Formen, kein expliziter Typ/Flag. Funktioniert nur, weil `DownloadResult` (services/downloader/download/models.py) strukturell nie ein `filepath`-Feld besitzt — nirgends dokumentiert, nirgends typgeprüft |
| `filepath`-Fallback-Suche (Schritt C) | eigene, einfachere Logik in `download_utils.py` (`find_downloaded_file()`, 2 Strategien) | eigene, andere Fallback-Kette (`filename`/`file_path`/`_filename`/`requested_downloads`/`library_path`) | **Teilweises Duplikat** — ähnliches Problem ("wo liegt die Datei wirklich"), unabhängig gelöst |

---

## 3. Konkrete Risiken

1. **Verhaltensdrift**: Ein neues Feld in `MetadataResult` (z. B. ein
   zukünftiges `mb_isrc`-Tag-Feld, das existiert bereits, wird aber aktuell
   nur in `download_utils.py::_process_track_metadata()` in ein
   `DownloadResult` übersetzt, NICHT im äquivalenten Rückgabe-Dict von
   `_process_single_download_result()`) — wird künftig leicht in nur einer
   der beiden Stellen nachgezogen. Bereits heute leicht unterschiedliche
   Feld-Sets in den beiden Rückgabe-Dicts (siehe Abschnitt 2).
2. **Fragiler impliziter „Already-Processed"-Vertrag** (Schritt B): Ändert
   sich das `DownloadResult`-Schema jemals so, dass es ein `filepath`-Feld
   bekommt (z. B. für Debug-Zwecke), würde JEDER YouTube-Track ein zweites
   Mal durch `EnhancedMetadataProcessor.process_single_track()` laufen —
   doppelte externe API-Calls (MusicBrainz/Last.fm/Genius/Fanart), doppeltes
   Tag-Schreiben, im schlimmsten Fall ein Fehler beim erneuten
   Datei-Verschieben (Datei liegt schon im Zielpfad). Kein Test schützt
   aktuell explizit gegen dieses Szenario.
3. **Layer-Verletzung**: `_process_single_download_result()` (~180 Zeilen,
   `klassen/download_handler.py:366-560`) enthält substantielle
   Domain-Adaptionslogik (Schritte A–G), die inhaltlich eher zu `services/`
   gehört als zur Handler-Schicht — passend zu CLAUDE.md §19s Warnung vor
   großen, Verantwortlichkeiten-vermischenden Orchestrator-Klassen.
4. **Zwei Podcast-Erkennungsmechanismen** (Kanal-Name-Matching intern vs.
   explizite Felder von außen) könnten für denselben fachlichen Fall
   (Podcast-Inhalt) zu unterschiedlichen Ergebnissen kommen, falls z. B.
   ein Podcast sowohl über YouTube als auch über Spotify bezogen wird und
   in `special_channel.yaml` nur unter einem der beiden Namensschemata
   hinterlegt ist. Nicht verifiziert ob das aktuell tatsächlich vorkommt —
   markiert als offene Frage, nicht als bestätigter Bug.

---

## 4. Mögliche Zielarchitektur-Richtungen (nicht entschieden, nur skizziert)

**Option A — Spotify-Ergebnis wie ein "vorverarbeitetes" YouTube-Ergebnis
behandeln:** `SpotifyDownloader` ruft `EnhancedMetadataProcessor` selbst auf
(analog zum YouTube-Pfad), liefert bereits ein fertiges `DownloadResult`-
kompatibles Dict. `_process_single_download_result()` würde dann für BEIDE
Pipelines zum reinen No-Op-Passthrough (Schritt B greift immer) und könnte
langfristig komplett entfallen. **Größter Eingriff**, verschiebt reale
Business-Logik (Podcast-Erkennung, Cover-Handling) von `klassen/` nach
`services/downloader/spotify_downloader.py` — genau der P0-kritische
Spotify-Downloadpfad, den CLAUDE.md §15 explizit als besonders geschützt
nennt.

**Option B — Gemeinsame Integrationsfunktion extrahieren:** eine neue,
gemeinsam genutzte Funktion/Klasse (z. B.
`services/downloader/utils/metadata_integration.py::enrich_track_result()`),
die Schritte C/G (generischer Teil: filepath-Fallback,
process_single_track-Aufruf, Rückübersetzung) einmal implementiert und von
BEIDEN Pipellinien aufgerufen wird — Podcast-spezifische Schritte D/E/F
blieben als optionaler, expliziter Parameter/Hook bestehen, statt implizit
über Dict-Keys erkannt zu werden. **Mittlerer Eingriff**, behält die
Pfad-Trennung bei, vereinheitlicht nur den duplizierten Kern.

**Option C — Nur die fragile „Already-Processed"-Erkennung härten**, ohne
die restliche Duplikation anzutasten: explizites `already_processed: bool`-
Feld statt der impliziten `library_path`/`filepath`-Heuristik. **Kleinster
Eingriff**, behebt Risiko 2 gezielt, lässt Risiken 1/3/4 unverändert.

Keine dieser Optionen ist hier entschieden — das ist ausdrücklich eine
spätere Entscheidung, sobald Umsetzung ansteht.

---

## 5. Einordnung nach den Stop-Conditions (Abschnitt 21 des
   ARCH-003-Auftrags)

Eine Umsetzung von P-3 (jede der drei Optionen) würde mindestens eine
dieser Bedingungen auslösen:

- Änderung an `klassen/download_handler.py` — **außerhalb** von `services/`
  (Option A/B in Teilen, Option C vollständig dort).
- Verhaltensänderung eines als P0 eingestuften Bereichs (Spotify-Download,
  CLAUDE.md §15/§17) — jede der drei Optionen berührt den tatsächlichen
  Verarbeitungspfad für Spotify-Tracks.
- Entscheidung zwischen grundsätzlich verschiedenen Architekturmodellen
  (Option A vs. B vs. C).

Entsprechend: **keine Umsetzung ohne explizite Nutzerentscheidung**, wie im
Auftrag vorgesehen.

---

## 6. Umsetzung Option B — Schritt 1: exakte Feld-für-Feld-Charakterisierung

Nutzer-Entscheidung: Option B. Vor jeder Änderung hier die drei (nicht nur
zwei!) bestehenden Übersetzungsstellen exakt verglichen.

**Wichtiger Fund, der über die Analyse in Abschnitt 1–5 hinausgeht:** Es
gibt nicht nur eine YouTube- und eine Spotify-Übersetzungsstelle, sondern
**drei** unabhängige Stellen, die alle `MetadataResult` → flaches
Ergebnis-Dict übersetzen — und sie stimmen bereits **untereinander nicht
konsistent** überein, auch die beiden YouTube-Stellen nicht:

| `MetadataResult`-Feld | `download_utils.py::_process_track_metadata()` (YT-Playlist) | `download_utils.py::_process_single_download()` (YT-Single) | `download_handler.py::_process_single_download_result()` (Spotify) |
|---|---|---|---|
| `title`/`artist`/`album`/`album_artist` | ✓ direkt übernommen | ✓ direkt übernommen | ✓ direkt übernommen (mit `or result.get(...)`-Fallback) |
| `year` | **NICHT** aus `enhanced_result.year` — nutzt stattdessen den vorab bestimmten `playlist_year` (bewusst: einheitliches Playlist-Jahr) | ✓ aus `enhanced_result.year` | ✓ aus `enhanced_result.year` (mit Fallback auf `result.get("year")`) |
| `track_number` | **NICHT** aus `enhanced_result` — nutzt den Schleifen-Index `track_idx` | Dataclass-Default `None` — `DownloadResult(...)`-Aufruf setzt es nie explizit, `to_dict()` liefert also immer `"track_number": None`, nie den echten Wert aus `enhanced_result.track_number` | ✓ aus `enhanced_result.track_number` |
| `playlist_album` | ✓ gesetzt (`= album_name`) | Dataclass-Default `None` — immer `"playlist_album": None` im Ergebnis-Dict | **echt fehlend** (Spotify-Dict ist kein `DownloadResult`, der Key existiert nur wenn `result` ihn vorher schon hatte — hat er nie) |
| `is_duplicate` | ✓ aus `enhanced_result.is_duplicate` | Dataclass-Default `False` — immer `"is_duplicate": False` im Ergebnis-Dict, nie der echte Wert aus `enhanced_result.is_duplicate` | **echt fehlend** — wird im Rückgabe-Dict nie gesetzt (weder aus `metadata_result` noch als Default) und war auch nie Teil des rohen Spotify-`track_info`-Dicts |
| `from_cache` | ✓ aus `enhanced_result.from_cache` | ✓ aus `enhanced_result.from_cache` | ✓ aus `metadata_result.from_cache` (verifiziert, Zeile 538 — **korrigiert gegenüber einer früheren, fehlerhaften Fassung dieser Tabelle**) |
| `lyrics` (Rohtext) | **echt fehlend** — `DownloadResult` kennt nur `lyrics_available` | **echt fehlend** — dito | ✓ gesetzt (Spotify-Ergebnis-Dict ist kein `DownloadResult`, sondern ein freies `{**result, ...}`-Dict, das den Rohtext behält) |
| `filepath` | **echt fehlend** — `DownloadResult` hat kein `filepath`-Feld | **echt fehlend** — dito | ✓ gesetzt (wichtig für den „Already-Processed"-Vertrag, s. Abschnitt 3.2) |
| `enhanced_processor_ref` | ✓ gesetzt (für spätere `get_processing_statistics()`-Abfrage) | ✓ gesetzt | **echt fehlend** — Spotify-Ergebnisse tragen diese Referenz nie (weder als Schlüssel noch als Default) |
| Rückgabetyp | `DownloadResult(...).to_dict()` (fester Felder-Satz, unbekannte Felder werden NICHT erhalten) | `DownloadResult(...).to_dict()` (dito) | freies `{**result, "title": ..., ...}`-Dict (beliebige Zusatzfelder aus `result`, z. B. `is_podcast`/`podcast_name`/`source`, bleiben erhalten) |
| `library_path`-Stringifizierung bei `None` | **unbedingt** `str(enhanced_result.library_path)` — bei `None` entsteht der literale String `"None"`, nicht der Wert `None` (verifiziert per Regressionstest) | bedingt: `str(...) if enhanced_result.library_path else None` — `None` bleibt `None` | bedingt: `str(...) if metadata_result.library_path else result.get("library_path")` |

*(Hinweis: „Dataclass-Default" bedeutet: der Schlüssel ist im Ergebnis-Dict
vorhanden, weil `DownloadResult` dafür einen Default-Wert definiert —
NICHT weil der echte Wert aus `enhanced_result` übernommen wurde. „echt
fehlend" bedeutet: der Schlüssel taucht im Ergebnis-Dict überhaupt nicht
auf.)*

**Einordnung:** Einige Unterschiede sind eindeutig **bewusstes Verhalten**
(z. B. `year`/`playlist_album`/`track_number` im Playlist-Fall — eine
Playlist hat ein einheitliches Jahr und eine feste Track-Reihenfolge, das
ist fachlich korrekt so gewollt). Andere wirken wie **unbeabsichtigte
Inkonsistenzen**, die durch die getrennte Pflege entstanden sind — allen
voran: `is_duplicate`/`track_number`/`playlist_album` werden im
Single-Track-YouTube-Pfad nie aus `enhanced_result` übernommen (nur
Dataclass-Defaults), und `enhanced_processor_ref`/`is_duplicate` fehlen im
Spotify-Pfad komplett. Ob das echte Bugs mit sichtbarer Auswirkung sind,
wurde hier **nicht geprüft** — das würde eine eigene Ursachenanalyse
erfordern (welche Konsumenten lesen `is_duplicate`/`enhanced_processor_ref`
aus dem Ergebnis-Dict, und was passiert, wenn das Feld fehlt statt
`False`/`None` zu sein?).

**Konsequenz für die Umsetzung (bindend für Schritt 3–5):**

1. Die gemeinsame Integrationsschicht wird **so gebaut, dass alle drei
   Aufrufstellen ihr jeweiliges aktuelles Ergebnis exakt reproduzieren** —
   über explizite Parameter für die oben identifizierten
   Divergenzpunkte (`year`-Override, `track_number`-Quelle,
   `playlist_album`, `is_duplicate`, `from_cache`, `enhanced_processor_ref`,
   Rückgabetyp `DownloadResult` vs. freies Dict). Keine der gefundenen
   Inkonsistenzen wird im Rahmen dieser Extraktion angeglichen oder
   behoben.
2. Die gefundenen, möglicherweise unbeabsichtigten Inkonsistenzen
   (`is_duplicate` im YT-Single-Pfad, `enhanced_processor_ref` im
   Spotify-Pfad) werden **separat als Folgeentscheidung dokumentiert**
   (Abschnitt 7) statt stillschweigend geändert — analog zum Umgang mit
   dem „Already-Processed"-Vertrag aus Abschnitt 3.2.
3. „Rohdaten → `track_metadata`" bleibt bewusst **je Aufrufer** bestehen
   (YT-Playlist, YT-Single und Spotify haben strukturell verschiedene
   Rohdaten-Schemas — das zusammenzuführen wäre keine Deduplizierung,
   sondern eine künstliche Abstraktion ohne Mehrwert). Geteilt wird der
   Teil, der tatsächlich identisch ist: der `process_single_track()`-Aufruf
   selbst plus die `MetadataResult`→Ergebnis-Übersetzung.

---

## 7. Zurückgestellte Folgeentscheidungen (nicht Teil dieser Extraktion)

Bewertet am 2026-08-23 per Entscheidungsbericht FIX NOW / DEFER, jeweils
anhand tatsächlicher Downstream-Konsumenten (nicht nur Vermutung):

- **Already-Processed-Vertrag** (Abschnitt 3, Risiko 2) — Option C aus
  Abschnitt 4. **DEFER**: struktureller, impliziter Vertrag ohne isolierte
  Codestelle; eine Härtung wäre ein eigenständiges Refactoring mit eigenem
  Risiko, kein kleiner Fix. In Schritt 3 bewusst NICHT angetastet: Schritte
  A–F von `_process_single_download_result()` (inkl. des
  Already-Processed-Schutzes in Schritt B) blieben unverändert, nur
  Schritt G (Aufruf + Ergebnis-Übersetzung) wurde durch die neue
  Integrationsschicht ersetzt.
- **`is_duplicate` wird im YT-Single-Pfad nie aus `enhanced_result`
  übernommen** — **FIX NOW, umgesetzt.** Fließt in den Telegram-Report
  (`download_handler.py:173`) und zeigte bei jedem YT-Einzeldownload
  fälschlich „kein Duplikat" an. `build_single_track_result()` übernimmt
  jetzt den echten Wert; Regressionstests aktualisiert.
- **`enhanced_processor_ref` fehlt im Spotify-Ergebnis-Dict** — **DEFER**:
  ist nur Fallback-Quelle 2 von 3 für `get_processing_statistics()`
  (`download_result_reporter.py:72`), mit `try/except` abgesichert, fällt
  sonst auf Quelle 3 (Track-Flag-Aggregation) zurück — kein Crash, nur
  potenziell ungenauere Statistik.
- **`library_path` wird im YT-Playlist-Pfad bei `None` zum String `"None"`**
  — **FIX NOW, umgesetzt.** `"None"` ist als String truthy und konnte den
  Already-Processed-Vertrag (`download_handler.py:400`) fälschlich
  auslösen sowie in `cache_manager.py:82-83` einen ungültigen
  `Path("None")` erzeugen. `build_playlist_track_result()` stringifiziert
  jetzt bedingt wie der Single-Pfad; Regressionstests aktualisiert.
- **Zwei unabhängige Podcast-Erkennungsmechanismen** (Abschnitt 3,
  Risiko 4) — **DEFER**: YouTube-Seite erkennt Podcasts über
  Kanal-Namens-Matching gegen `special_channel.yaml`
  (`enhanced_metadata_processor.py`, `_is_podcast_channel`), Spotify-Seite
  über den API-Content-Typ `meta.get("type") == "episode"`
  (`spotify_downloader.py:640`) — konzeptionell grundverschiedene
  Mechanismen. Eine Vereinheitlichung wäre eine Architekturentscheidung
  (welcher Mechanismus führt, oder werden beide kombiniert?), kein
  isolierter Fix. Divergenz weiterhin nicht verifiziert, ob sie in der
  Praxis tatsächlich auftritt.

Umsetzung siehe Commit `7ecc276` (fix(services): ARCH-004 P-3
Folgeentscheidungen).

---

## 8. Umsetzung Option B — Schritt 3: gemeinsame Integrationsschicht

Neue Datei `services/downloader/utils/metadata_result_translator.py` mit
vier Funktionen:

- `call_process_single_track(...)` — der `process_single_track()`-Aufruf
  selbst, an allen drei Stellen 1:1 identisch.
- `build_playlist_track_result(...)` — reproduziert exakt
  `_process_track_metadata()`s (YT-Playlist) `DownloadResult`-Aufbau,
  inkl. `year`-Override, `track_number`=Schleifenindex,
  `playlist_album`, unbedingter `library_path`-Stringifizierung.
- `build_single_track_result(...)` — reproduziert exakt
  `_process_single_download()`s (YT-Single) `DownloadResult`-Aufbau, inkl.
  der Dataclass-Defaults für `track_number`/`playlist_album`/
  `is_duplicate` und bedingter `library_path`-Stringifizierung.
- `merge_metadata_result_into_dict(...)` — reproduziert exakt
  `_process_single_download_result()`s (Spotify) freien
  `{**result, ...}`-Dict-Aufbau, inkl. `lyrics`/`filepath`-Erhalt und
  fehlendem `enhanced_processor_ref`/`is_duplicate`.

**Eingebaut in alle drei Aufrufstellen**, jeweils NUR der
Aufruf-plus-Übersetzungs-Teil ersetzt — `track_metadata`-Aufbau (Rohdaten
→ track_metadata) sowie alle podcast-/playlist-spezifischen
Vorbereitungsschritte (A–F bei Spotify) bleiben unverändert je Aufrufer
bestehen, wie in Abschnitt 6 begründet. `EnhancedMetadataProcessor` selbst
wurde nicht verändert.

**Verifikation:** 16 neue, isolierte Tests für die Integrationsschicht
selbst (`tests/test_metadata_result_translator.py`) plus die 31 aus
Schritt 2 bereits bestehenden Regressionstests für die drei
Aufrufstellen liefen nach dem Einbau unverändert grün — kein einziger
Test musste angepasst werden. YouTube- und Spotify-relevante Tests wurden
zusätzlich separat ausgeführt (136 bzw. 39 bestanden). Voller
Regressionslauf: 1007 bestanden (vorher 989), unverändert 15
vorbestehende Fehler.
