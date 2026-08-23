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
