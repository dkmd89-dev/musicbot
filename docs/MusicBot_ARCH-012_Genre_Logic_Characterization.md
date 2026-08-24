# ARCH-012 — Genre-Logik Characterization & Architektur-Analyse

## Status

**Phase 1 abgeschlossen (2026-08-24).** Reine Analyse, kein Code geändert.

**Phase 2 abgeschlossen (2026-08-24).** Last.fm-Client-Bereinigung
umgesetzt und verifiziert (Abschnitt 16). MusicBrainz-Doppelberechnung
bewusst unverändert, als Phase 3 zurückgestellt.

**Phase 3A abgeschlossen (2026-08-24).** Reine Characterization, kein
Produktionscode geändert (Abschnitt 17). Wichtigster Befund: Die
Arbeitshypothese aus Phase 1 ("zweiter Aufruf ist redundant/tot") ist
**präzisiert, nicht bestätigt** — bei echten Multi-Tag-Eingaben liegt
bereits im **ersten** `determine_genre()`-Aufruf (im Client) ein
Informations-/Korrektheits-Verlust vor, den der zweite Aufruf nur
unverändert durchreicht. Kein Refactoring in dieser Phase.

---

## 1. Ziel und Scope

Der `docs/MusicBot_POST-DUPLICATEENTRY_Services_Architecture_Audit.md`
identifizierte die Genre-Logik-Duplikation zwischen
`services/clients/lastfm_client.py`, `services/clients/musicbrainz_client.py`
und `services/metadata/genre_processor.py` als architektonisch wichtigsten,
aber zu großen/riskanten Befund für einen sofortigen Schritt (P0-geschützte
Domäne, CLAUDE.md §10/§16, §6 „Characterization First").

Ziel dieser Phase: **ausschließlich** ermitteln, wie die Genre-
Verantwortung tatsächlich verteilt ist, ob eine echte Redundanz vorliegt
oder nur eine oberflächliche Ähnlichkeit, welche Zielarchitektur die
Funktionalität sauber zentralisieren könnte, und welche Tests vor einer
etwaigen Änderung nötig wären. Keine Umsetzung, keine Bewertung „schön vs.
hässlich" — nur belegte Fakten aus dem tatsächlichen Code.

---

## 2. Ist-Architektur

```text
services/clients/lastfm_client.py       ──┐
services/clients/musicbrainz_client.py  ──┼──► rufen intern
                                            │    utils/genre_map.py::GenreMapper
                                            │    (SingletonMixin — eine einzige,
                                            │     geteilte Instanz über den
                                            │     gesamten Prozess)
                                            │
services/metadata/genre_processor.py    ──┘──► ruft dieselbe GenreMapper-
                                                Singleton-Instanz ZUSÄTZLICH
                                                selbst auf, UND besitzt eigene,
                                                separate Priorisierungslogik
                                                (prioritize_genres())
```

**Zentraler, per Code belegter Fakt:** `GenreMapper` (`utils/genre_map.py`,
Zeile 128: `class GenreMapper(SingletonMixin)`) ist ein Singleton
(`utils/singleton.py::SingletonMixin.__new__` gibt bei jeder Instanziierung
— egal ob per `GenreMapper()` direkt oder per Singleton-Getter
`get_genre_mapper()` — dieselbe Prozess-weite Instanz zurück). Das
bedeutet: `lastfm_client.py` (`self.genremapper = GenreMapper()`,
Zeile 41), `musicbrainz_client.py` (`self.genre_mapper = get_genre_mapper()`,
Zeile 96) und `genre_processor.py` (injizierter `genre_mapper`, konstruiert
in `enhanced_metadata_processor.py` letztlich ebenfalls über denselben
Singleton-Pfad) **verwenden alle exakt dasselbe Objekt**, dieselben
geladenen YAML-Daten (`mapping/genre_hierarchy.yaml`,
`mapping/genre_aliases.yaml`, Artist-/Channel-Maps, Regex-Regeln).

**Das ändert die Fragestellung fundamental:** Es geht **nicht** um zwei
konkurrierende, unabhängig gepflegte Datenquellen (wie z. B. bei der
Last.fm-Cover-Duplikation, wo zwei komplett getrennte HTTP-Clients
existieren). Es geht um **dieselbe zugrunde liegende Wissensbasis**, die
über **zwei unterschiedliche Python-Algorithmen** angesprochen wird:

- `GenreMapper.determine_genre(raw_genre: str, ...)` — erwartet **einen
  einzelnen String**, keine Liste. Prioritätsreihenfolge (Zeile 610–790):
  1. Spezialkanal-Mapping, 2. Artist-Mapping (exakt/fuzzy), 3. Channel-
  Mapping (exakt/fuzzy), 4. Regex-Regeln auf dem **gesamten** String
  (`_apply_rules`), 5. Normalisierung + **ein-stufiger** Parent-Lookup
  (`get_main_genre()`, Zeile 368–387: `self.hierarchy.get(key) or
  sub_genre` — genau **ein** Hierarchie-Schritt nach oben, keine
  rekursive Tiefenberechnung).
- `GenreProcessor.prioritize_genres(tags: List[str], ...)`
  (`genre_processor.py`, Zeile 208–320) — erwartet explizit **eine Liste**
  von Einzel-Tags. Filtert jeden Tag gegen `IGNORE_SECONDARY`
  (`genre_filters.yaml`), normalisiert jeden Tag einzeln über die
  **eigene** Methode `GenreProcessor.normalize_genre_name()` (Zeile
  322–352, eigene Implementierung, nicht dieselbe wie
  `GenreMapper.normalize_genre_name()`), ordnet dann nach
  **rekursiv berechneter Hierarchie-Tiefe** (`GENRE_PRIORITY`, aus
  `_calculate_genre_priority_from_hierarchy()`, Zeile 391–477 —
  vollständige Tiefenberechnung über die gesamte Baumstruktur) und wählt
  das spezifischste Tag.

Beide Algorithmen lesen aus denselben YAML-Quellen, sind aber
**strukturell unterschiedlich implementiert** — kein gemeinsamer
Code-Pfad, keine gemeinsame Basisklasse/Methode.

---

## 3. Last.fm-Analyse (`services/clients/lastfm_client.py`, 151 LOC)

### Genre-bezogene Methoden

| Methode | Eingabe | Ausgabe | Charakter |
|---|---|---|---|
| `_get_lastfm_data()` (Zeile 44–105) | `title`, `artist`, `mbid` | `(track_info: dict, all_tags: List[str])` | **Reine Adapterlogik.** Ruft `pylast`-API auf (Artist-Objekt, Artist-Top-Tags, Track-Top-Tags), kombiniert Artist- und Track-Tags dedupliziert (Artist-Tags zuerst), alles lowercased. Keine Genre-Entscheidung, keine Priorisierung — reine Rohdaten-Sammlung. |
| `fetch_metadata()` (Zeile 107–151) | `title`, `artist`, `include_genre`, `mbid` | `Dict[str, Any]` mit Keys `tags`, `listeners`, `playcount`, `album`, `wiki`, `genre` | **Enthält echte Genre-Fachlogik** (Zeile 128–135): ruft bei `include_genre and tag_names` `self.genremapper.determine_genre(raw_genre=", ".join(tag_names), artist_name=artist)` auf und speichert `genre_result.primary` als `"genre"`-Feld. Fällt auf `"unknown"` zurück, wenn keine Tags oder `include_genre=False`. |

### Produktions-Consumer

- `services/metadata/genre_processor.py::_fetch_genre_from_lastfm()`
  (einziger Consumer im gesamten Repo — verifiziert per
  `grep -rn "LastFMClient\|lastfm_client" --include="*.py"` außerhalb von
  Tests: nur `enhanced_metadata_processor.py` konstruiert/injiziert den
  Client, `genre_processor.py` ruft `fetch_metadata()` auf).

### Test-Consumer

`tests/test_lastfm_client.py` (218 LOC, 13 Tests) — mockt
`genremapper.determine_genre` durchgehend als `MagicMock` mit
kanonischem `MagicMock(primary="Hip Hop")`-Rückgabewert
(`test_tags_present_with_include_genre_determines_genre`, Zeile 118–134).
**Wichtig:** Kein einziger Test in diesem File ruft die echte
`GenreMapper.determine_genre()` mit einem realistischen, komma-
verketteten Multi-Tag-String auf — die Interaktion zwischen `", ".join(tags)`
und der echten `determine_genre()`-Implementierung ist **nicht getestet**
(siehe Abschnitt 9).

### Wird das Client-Genre-Ergebnis tatsächlich weiterverwendet?

**Nein, praktisch nie.** `genre_processor._fetch_genre_from_lastfm()`
(Zeile 606–660) liest `lfm_data.get("genre", "")` in `raw_lfm_genre`, nutzt
diesen Wert aber **nur** als Notfall-Rekonstruktion einer Tag-Liste, falls
`tags` leer wäre (Zeile 631–636: `if raw_lfm_genre and "," in raw_lfm_genre
and not tags: tags = [...]`). Da `lastfm_client.fetch_metadata()` das
`tags`-Feld praktisch immer mitliefert, sobald überhaupt Tags gefunden
wurden (`tags: tag_names` wird immer gesetzt, unabhängig von
`include_genre`), ist dieser Fallback-Zweig **faktisch unerreichbar** im
Normalfall. Die eigentliche Genre-Entscheidung trifft stattdessen
`self.prioritize_genres(tags, artist_name=artist_name)` — ein komplett
anderer Algorithmus (Abschnitt 2) auf den **rohen** Tags, nicht auf dem
vom Client vorberechneten `genre`-String.

**Konsequenz:** Der im Last.fm-Client berechnete `GenreMapper.determine_genre()`-
Aufruf (Zeile 130–134) ist für den einzigen Produktions-Consumer
**praktisch totes Gewicht** — das Ergebnis wird berechnet, im Dict
mitgeliefert, aber vom Aufrufer nicht verwendet.

---

## 4. MusicBrainz-Analyse (`services/clients/musicbrainz_client.py`, 469 LOC)

### Genre-/Tag-/Label-/Style-bezogene Funktionen

| Funktion | Kategorie | Beschreibung |
|---|---|---|
| `_build_metadata()` Zeile 414 (`mb_tags = [t["name"] for t in release_group.get("tags", [])]`) | (a) API-Response-Mapping | Extrahiert rohe Tag-Namen aus der MusicBrainz-`release-group`-Antwortstruktur. Reine Datenextraktion. |
| `_build_metadata()` Zeile 428–440 (`genre_value = ...`) | (d) echte Fachlogik | Ruft `self.genre_mapper.determine_genre(raw_genre=mb_tags_str, artist_name=original_artist)` auf (bzw. den leeren-Tags-Zweig mit `channel_name=original_artist`) — **identischer Mechanismus** wie im Last.fm-Client (Abschnitt 3), nur mit MusicBrainz-Tags statt Last.fm-Tags als Eingabe. |
| `_get_best_match()` Zeile 321–350 | (c) Ranking/Priorisierung | **Kein Genre-Ranking** — rankt Recording-**Kandidaten** (Titel-/Artist-Ähnlichkeit via `SequenceMatcher`), nicht Genres. Gehört zur Track-Identifikation, nicht zur Genre-Domäne. |
| `parse_search_terms()` Zeile 174–205 | (b) Normalisierung | Normalisiert Such-Artist/-Titel für die API-Anfrage (YouTube-Titel-Reparsing, Artist-Normalisierung über `ArtistNormalizer`) — **keine** Genre-Normalisierung, sondern Such-Query-Vorbereitung. |

Es gibt **keine** separate „Label"- oder „Style"-spezifische Funktion —
MusicBrainz liefert in diesem Client ausschließlich `release-group`-Tags
als Genre-Rohdaten.

### Produktions-Consumer von `fetch_metadata()`

**Zwei unabhängige Consumer**, nicht nur einer:

1. `services/metadata/genre_processor.py::_fetch_genre_from_musicbrainz()`
   — nutzt `mb_data["genre"]`, `mb_data["tags"]` und die MBID-Felder.
2. `services/metadata/album_processor.py::fetch_album_from_musicbrainz()`
   (Zeile 129–159) — nutzt **ausschließlich** `mb_data.get("album")` /
   `mb_data.get("release")` und `mb_data.get("year")` /
   `mb_data.get("release_year")`. Das `"genre"`-Feld wird hier **komplett
   ignoriert** — für diesen Consumer ist die im Client durchgeführte
   Genre-Berechnung (Zeile 428–440) reiner Overhead: Sie läuft bei jedem
   Aufruf mit, unabhängig davon, ob der Aufrufer das Ergebnis überhaupt
   braucht.

### Test-Consumer

`tests/test_musicbrainz_client.py` (436 LOC, 24 Tests). Zwei Tests
direkt auf das Genre-Verhalten:
- `test_genre_determined_from_release_group_tags` (Zeile 401–422):
  mockt `client.genre_mapper` als `MagicMock`, prüft
  `result["genre"] == "Jazz"` und dass `kwargs["raw_genre"]` die Tags
  enthält — **wieder Mock, keine echte `GenreMapper`-Instanz.**
- `test_no_tags_falls_back_to_artist_channel_genre_lookup` (Zeile 424–435):
  prüft den leeren-Tags-Zweig (`raw_genre == ""`).

### Werden Genre-Ergebnisse downstream tatsächlich genutzt?

**Teilweise, mit einem belegten Doppel-Aufruf.**
`genre_processor._fetch_genre_from_musicbrainz()` (Zeile 532–604) liest
`mb_data.get("genre", "")` in `raw_mb_genre`. Wenn dieser Wert vorhanden
und nicht `"unknown"` ist (`has_genre`, Zeile 574), ruft es
**erneut** `self.genre_mapper.determine_genre(raw_genre=raw_mb_genre,
artist_name=artist_name)` auf (Zeile 579–582) — diesmal jedoch mit dem
**bereits vom Client kollabierten Einzelgenre-String** (z. B. `"Deutschrap"`)
als Eingabe, **nicht** mit den ursprünglichen `mb_tags` (die als
`raw_tags` erst danach separat wieder angehängt werden, Zeile 585, ohne
selbst nochmal durch eine Priorisierung zu laufen).

**Das ist ein direkt im Code nachweisbarer, echter Doppel-Aufruf derselben
Methode** (`GenreMapper.determine_genre()`) mit unterschiedlichem, jeweils
degradiertem Eingabe-Kontext — kein hypothetischer Verdacht, siehe
Abschnitt 9 für den exakten Testbeleg (`test_musicbrainz_genre_hit_populates_mb_ids`,
`result.source == "normalized"`).

---

## 5. genre_processor-Analyse (`services/metadata/genre_processor.py`, 765 LOC)

### Fachlogik-Inventar

| Bereich | Methode | Quelle |
|---|---|---|
| Manuelles Genre | `genre_mapper.get_artist_entry()` (Schritt 1) | `mapping/artist_genre.yaml`, exakter Artist-Match, höchste Priorität |
| Lokales Genre | `genre_mapper.determine_genre()` (Schritt 2, Zeile 115–120) | Channel-/Artist-Mapping, Regex-Regeln, Hierarchie — **derselbe** Singleton-Aufruf wie in den Clients, hier aber mit `track_metadata.get("genre")` (YouTube-Rohdaten) als Eingabe, nicht mit externen API-Tags |
| MusicBrainz-Fallback | `_fetch_genre_from_musicbrainz()` (Schritt 3, immer für IDs aufgerufen) | s. Abschnitt 4 |
| Last.fm-Fallback | `_fetch_genre_from_lastfm()` + `prioritize_genres()` (Schritt 4, nur wenn noch kein Genre) | s. Abschnitt 3 |
| Feature-Artist-Inferenz | `_infer_genre_from_feat_artists()` (Schritt 5) | `mapping/artist_genre.yaml` über Feature-Artists, Mehrheitsvotum |
| Priorisierung (Last.fm-Pfad) | `prioritize_genres()` | `mapping/genre_hierarchy.yaml` (Tiefe), `mapping/genre_filters.yaml` (Ignore-Liste), eigene `normalize_genre_name()` |
| Normalisierung (eigen) | `normalize_genre_name()` (Zeile 322–352) | `mapping/genre_aliases.yaml`, geladen in `GENRE_NORMALIZATION` |
| Hierarchie-Prioritäten | `_calculate_genre_priority_from_hierarchy()` (Zeile 391–477) | `mapping/genre_hierarchy.yaml`, **vollständige rekursive Tiefenberechnung** |

### Eingangsquellen und Prioritätsreihenfolge (Docstring-bestätigt, Zeile 13–19)

```text
1. Manuelles Genre  – artist_genre.yaml (exakter Key-Match, höchste Priorität)
2. Lokales Genre    – channel_map / auto_learned / fuzzy / raw_genre / Hierarchie
3. MusicBrainz      – IMMER aufgerufen für MB-IDs (auch wenn Genre schon bekannt)
4. Last.fm          – nur wenn noch kein Genre bekannt
5. Feature-Inference – Genre aus bekannten Feature-Artists ableiten
```

**Wichtiges Detail (Zeile 141–164):** MusicBrainz wird bei bekanntem
Genre (Schritt 1/2 bereits erfolgreich) **trotzdem** aufgerufen — aber
ausschließlich, um `mb_ids` an das bereits feststehende Ergebnis
anzuhängen (Zeile 158–164). In diesem Fall wird zwar
`_fetch_genre_from_musicbrainz()` komplett durchlaufen (inkl. des in
Abschnitt 4 beschriebenen Doppel-`determine_genre()`-Aufrufs), aber das
dabei berechnete `_mb_result.primary` wird **verworfen** — nur
`_mb_result.mb_ids` wird übernommen. Das bedeutet: der MB-Client-interne
Genre-Berechnungsaufwand (inkl. dessen eigenem `determine_genre()`-Aufruf)
läuft in diesem Fall **doppelt unnötig** — einmal im Client, einmal in
`_fetch_genre_from_musicbrainz()` —, obwohl beide Ergebnisse am Ende
verworfen werden.

### Wo werden Client-Ergebnisse übernommen / transformiert / verworfen?

| Client-Feld | Verhalten in `genre_processor.py` |
|---|---|
| `mb_data["genre"]` | **Transformiert**: erneut durch `determine_genre()` geschickt (degradierte Eingabe, s. o.) |
| `mb_data["tags"]` | **Übernommen unverändert** als `raw_tags` am Ergebnis — aber nicht selbst nochmal priorisiert |
| `mb_data[mbid-Felder]` | **Übernommen** in `GenreResult.mb_ids` |
| `lfm_data["genre"]` | **Verworfen** (nur Notfall-Fallback, praktisch nie erreicht) |
| `lfm_data["tags"]` | **Übernommen und selbst neu priorisiert** über `prioritize_genres()` (eigener Algorithmus) |

---

## 6. Consumer-/Dependency-Graph

```text
services/metadata/enhanced_metadata_processor.py
    │  (Facade, konstruiert/lazy-initialisiert Clients + GenreProcessor)
    │
    ├──► self._mb_client: MusicBrainzClient   ──► genre_mapper: GenreMapper (Singleton)
    ├──► self._lfm_client: LastFMClient        ──► genremapper: GenreMapper (Singleton, dieselbe Instanz)
    ├──► self.album_processor: AlbumProcessor  ──► (eigener, ggf. zweiter) MusicBrainzClient
    │        └─ konsumiert NUR album/year, ignoriert genre-Feld (Abschnitt 4)
    └──► self.genre_processor: GenreProcessor  ──► self.genre_mapper: GenreMapper (Singleton, dieselbe Instanz)
             │
             ├──► _fetch_genre_from_musicbrainz(mb_client) ──► mb_client.fetch_metadata()
             │        └─ ruft genre_mapper.determine_genre() ERNEUT auf Client-Ergebnis (Abschnitt 4)
             │
             └──► _fetch_genre_from_lastfm(lfm_client) ──► lfm_client.fetch_metadata()
                      └─ verwirft lfm_data["genre"], nutzt eigenes prioritize_genres() (Abschnitt 3)
```

`services/clients/lastfm_client.py` und `services/clients/musicbrainz_client.py`
haben **keine** Abhängigkeit zurück auf `services/metadata/` (bestätigt,
Regel-A-konform bzgl. Import-Richtung — die Duplikation ist eine Logik-
Frage, keine Dependency-Richtungs-Verletzung). Die Dependency-Richtung
`services/metadata → services/clients` bleibt in jedem der geprüften
Varianten unverändert (siehe Abschnitt 11, Punkt E).

---

## 7. Genre-Datenfluss

### MusicBrainz-Pfad

```text
MusicBrainz API (release-group.tags)
   │  rohe Tag-Namen
   ▼
musicbrainz_client._build_metadata()
   │  mb_tags_str = ", ".join(mb_tags)
   │  ⚙ 1. determine_genre(raw_genre=mb_tags_str) → genre_value  [Berechnung #1]
   ▼
{"tags": mb_tags, "genre": genre_value, "mbid": ..., ...}  ← Client-Rückgabe
   │
   ▼
genre_processor._fetch_genre_from_musicbrainz()
   │  raw_mb_genre = mb_data["genre"]  (= genre_value von oben)
   │  ⚙ 2. determine_genre(raw_genre=raw_mb_genre) ERNEUT  [Berechnung #2, degradierte Eingabe]
   │  mb_data["tags"] wird unverändert als raw_tags übernommen (nicht neu priorisiert)
   ▼
GenreResult(primary=..., source="normalized"/"hierarchy"/..., raw_tags=mb_tags, mb_ids=...)
   │
   ▼
MetadataResult.genres / genre_source  (enhanced_metadata_processor.py)
   │
   ▼
Downloader/Consumer (Tags, Dateiname, Bibliotheks-Pfad)
```

**Verlust/Doppelberechnung an dieser Kante:** Berechnung #1 (im Client)
wird bei bekanntem Genre aus Schritt 1/2 (Abschnitt 5) komplett verworfen.
Wenn kein bekanntes Genre vorliegt, läuft Berechnung #2 auf einer bereits
verdichteten Einzelstring-Eingabe statt der originalen Tag-Liste — die in
`mb_tags` enthaltene Mehrfach-Tag-Information (z. B. `["deutschrap", "hip
hop", "trap"]`) geht für die **Genre-Entscheidung selbst** verloren
(nur als `raw_tags`-Metadatum am Endergebnis erhalten, nicht für die
Priorisierung genutzt) — anders als beim Last.fm-Pfad, wo die volle
Tag-Liste über `prioritize_genres()` tatsächlich ausgewertet wird.

### Last.fm-Pfad

```text
Last.fm API (Artist-Tags + Track-Tags)
   │  rohe Tag-Liste (dedupliziert, Artist-Tags zuerst)
   ▼
lastfm_client.fetch_metadata()
   │  ⚙ 1. determine_genre(raw_genre=", ".join(tags)) → genre  [Berechnung #1, praktisch ungenutzt]
   ▼
{"tags": tag_names, "genre": genre, ...}  ← Client-Rückgabe
   │
   ▼
genre_processor._fetch_genre_from_lastfm()
   │  lfm_data["genre"] wird gelesen, aber NICHT verwendet (nur Notfall-Fallback)
   │  ⚙ 2. prioritize_genres(tags) — ANDERER Algorithmus auf der vollen Original-Tag-Liste
   ▼
GenreResult(primary=..., source="lastfm_prioritized", raw_tags=tags)
   │
   ▼
MetadataResult.genres / genre_source
   │
   ▼
Downloader/Consumer
```

**Verlust/Doppelberechnung an dieser Kante:** Berechnung #1 (im Client)
ist für den Genre-Wert selbst komplett wirkungslos — nur Nebeneffekt
(Log-Ausgabe, Objekt im Rückgabe-Dict). Kein Datenverlust, aber
nachweisbare unnötige Arbeit bei **jedem** Last.fm-Aufruf mit Tags.

---

## 8. Duplikationsmatrix

| Logik | Last.fm Client | MusicBrainz Client | genre_processor | Bewertung |
|---|---|---|---|---|
| Genre-Bestimmung (Kernalgorithmus) | `GenreMapper.determine_genre()` (Einzelstring) | `GenreMapper.determine_genre()` (Einzelstring) | (Last.fm-Pfad) `prioritize_genres()` — **eigener** Algorithmus; (MB-Pfad, Manual/Lokal-Pfad) ebenfalls `GenreMapper.determine_genre()` | **Last.fm: unabhängig** (zwei verschiedene Algorithmen im Einsatz). **MusicBrainz: identisch, aber redundant aufgerufen** (dieselbe Methode zweimal, degradierte Eingabe beim zweiten Mal) |
| Genre-Normalisierung | über `GenreMapper.normalize_genre_name()` (intern in `determine_genre()`, Schritt 5) | über `GenreMapper.normalize_genre_name()` (intern, Schritt 5) | eigene `GenreProcessor.normalize_genre_name()` (andere Implementierung, gleiche YAML-Quelle `genre_aliases.yaml`) | **Ähnlich, nicht identisch** — zwei getrennte Implementierungen auf derselben Datenquelle |
| Synonyme/Aliases | `mapping/genre_aliases.yaml` (via `GenreMapper.genre_aliases`) | dieselbe Quelle | `mapping/genre_aliases.yaml` (via `GenreProcessor.GENRE_NORMALIZATION`, separat geladen) | **Identische Datenquelle, doppelt geladen/gehalten** (kein Cache-Sharing zwischen `GenreMapper.genre_aliases` und `GenreProcessor.GENRE_NORMALIZATION` — zwei In-Memory-Kopien derselben YAML) |
| Mapping (Artist/Channel) | `GenreMapper.artist_map`/`channel_map` (in `determine_genre()`, Schritt 2/3) | dieselbe Quelle | eigenes `genre_mapper.get_artist_entry()` (Schritt 1, exakt) + `determine_genre()` (Schritt 2, inkl. fuzzy) | **Identisch** — beide nutzen dieselbe Singleton-Instanz für diesen Teil |
| Priorisierung (Mehrfach-Tags) | keine (nur Einzelstring) | keine (nur Einzelstring) | `prioritize_genres()` — rekursive Hierarchie-Tiefe über `GENRE_PRIORITY` | **Nur in genre_processor vorhanden** — Clients haben dafür keinen Mechanismus |
| Fallbacks | `"unknown"` bei fehlenden Tags/`include_genre=False` | `"unknown"` bei fehlenden Tags | mehrstufige Fallback-Kette (Manuell→Lokal→MB→LFM→Feature) | **Nicht vergleichbar** — Clients liefern nur einen einzelnen Fallback-Wert, genre_processor orchestriert die gesamte Kette |
| Filter (Ignore-Liste) | keiner | keiner | `IGNORE_SECONDARY` aus `genre_filters.yaml`, nur in `prioritize_genres()` | **Nur in genre_processor vorhanden** |
| Deduplizierung | Tags (Artist+Track, `_get_lastfm_data()`) | keine (keine Mehrfach-Tag-Verarbeitung) | Sekundär-Genres (`seen`-Set in `prioritize_genres()`) | **Unabhängig, unterschiedliche Ebenen** (Rohdaten- vs. Ergebnis-Deduplizierung) |
| Ranking | Recording-Kandidaten-Score (`_get_best_match()`, **kein** Genre-Ranking) | — | Tag-Priorität nach Hierarchie-Tiefe | **Nicht vergleichbar** (unterschiedliche Ranking-Gegenstände) |
| Default-/Fallback-Genres | `"unknown"` | `"unknown"` | `"Unknown"` (in `prioritize_genres()`, `normalize_genre_name()`) bzw. `None` (`determine_genre_with_fallbacks()`) | Ähnlich, aber **nicht identisch geschrieben** (`"unknown"` vs. `"Unknown"` vs. `None`) — potenzielle Quelle für String-Vergleichsfehler an Schnittstellen, die den rohen Wert vergleichen |
| API-spezifische Transformationen | Artist-/Track-Tag-Kombination, `pylast`-Objektzugriff | Recording-/Release-Struktur-Extraktion, ISRC/MBIDs, Track-Nummer-Ermittlung | keine (bekommt bereits aufbereitete Dicts) | **Vollständig client-spezifisch, keine Überschneidung** — legitime Adapterlogik |

**Kernaussage der Matrix:** Es liegt **keine literale Code-Duplikation**
vor (kein copy-paste derselben Funktion). Es liegt eine **strukturelle
Doppelverantwortung** vor: (a) beim MusicBrainz-Pfad ein echter,
nachweisbarer Doppel-Aufruf derselben Methode mit degradierter Eingabe;
(b) beim Last.fm-Pfad zwei tatsächlich unterschiedliche Algorithmen auf
denselben Rohdaten, von denen nur einer (der in `genre_processor.py`)
das Ergebnis bestimmt; (c) bei den Datenquellen (Aliases, Hierarchie)
eine doppelte In-Memory-Repräsentation derselben YAML-Dateien.

---

## 9. Test-Coverage

| Testdatei | Umfang | Deckt echte `GenreMapper`-Interaktion ab? |
|---|---|---|
| `tests/test_genre_mapper_advanced.py` (161 LOC) | `GenreMapper`-eigene Logik direkt | Ja — testet `GenreMapper` isoliert |
| `tests/test_lastfm_client.py` (218 LOC, 13 Tests) | `LastFMClient.fetch_metadata()`/`_get_lastfm_data()` | **Nein** — `genremapper.determine_genre` durchgehend `MagicMock` |
| `tests/test_musicbrainz_client.py` (436 LOC, 24 Tests) | `MusicBrainzClient` vollständig | **Nein** — `genre_mapper` durchgehend `MagicMock` |
| `tests/test_genre_processor.py` (245 LOC) | `GenreProcessor` mit **echtem** `GenreMapper` gegen reale YAMLs, aber `mb_client`/`lfm_client` als selbstgebaute Fakes (`FakeMusicBrainzClient`, `FakeLastFmClient`) | **Teilweise** — echter `GenreMapper` ja, aber die Fakes liefern bereits fertige `"genre"`-/`"tags"`-Werte, nicht die Rohdaten, aus denen ein echter Client sie berechnen würde |

**Direkter Beleg für den in Abschnitt 4 beschriebenen Doppel-Aufruf:**
`tests/test_genre_processor.py::test_musicbrainz_genre_hit_populates_mb_ids`
(Zeile 185–200) — `FakeMusicBrainzClient` liefert
`{"genre": "deutschrap", "tags": ["hip hop", "rap"], ...}`. Ergebnis:
`result.primary == "Deutschrap"`, **`result.source == "normalized"`**.
`"normalized"` ist exakt der `source`-Wert, den `GenreMapper.determine_genre()`
zurückgibt, wenn es bis Schritt 5 (Normalisierung ohne Hierarchie-Aufstieg)
durchfällt (`utils/genre_map.py` Zeile 779) — dieser Test **beweist**,
dass `genre_processor` den bereits vom (Fake-)Client gelieferten
Genre-String erneut durch `determine_genre()` schickt, statt ihn direkt
zu übernehmen.

**Direkter Beleg für den Last.fm-Discard:**
`tests/test_genre_processor.py::test_lastfm_fallback_used_when_musicbrainz_has_no_client`
(Zeile 212–222) — `FakeLastFmClient({"tags": [...]})` setzt bewusst
**kein** `"genre"`-Feld. `result.source == "lastfm_prioritized"` beweist,
dass ausschließlich `prioritize_genres()` über die Tags entscheidet.

### Fehlende Tests / Lücken

1. **Kein Test verifiziert das Verhalten von `GenreMapper.determine_genre()`
   mit einem realistischen, komma-verketteten Multi-Tag-String** (wie ihn
   `lastfm_client.py`/`musicbrainz_client.py` tatsächlich in Produktion
   erzeugen, z. B. `"hip hop, rap, deutschrap, trap"`). `test_genre_mapper_advanced.py`
   müsste geprüft werden, ob es solche Fälle abdeckt — aktuell nicht
   nachgewiesen (out of scope für einen tieferen Reverse-Engineering-
   Vergleich in dieser Phase, siehe Abschnitt 14).
2. **Kein Integrationstest** verbindet einen (auch nur teilweise) echten
   `LastFMClient`/`MusicBrainzClient` mit einem echten `GenreProcessor`
   und einem echten `GenreMapper` end-to-end — jede Schicht wird isoliert
   mit Mocks/Fakes getestet. Die Interaktion zwischen den Schichten ist
   nur durch die (korrekten, aber lückenhaften) Fake-Rückgabewerte
   abgesichert.
3. **Kein Test** vergleicht das Ergebnis von
   `GenreMapper.determine_genre(raw_genre=", ".join(tags))` mit
   `GenreProcessor.prioritize_genres(tags)` für denselben Tag-Satz, um zu
   zeigen, ob/wann sie divergieren — das ist exakt die Frage, die eine
   spätere Vereinheitlichung beantworten müsste.

---

## 10. Verhaltensrisiken

- **Implizite Priorität, die brechen könnte:** Schritt 3 in
  `determine_genre_with_fallbacks()` ruft MusicBrainz **immer** auf (auch
  bei bereits bekanntem Genre) — allein für `mb_ids`. Jede Änderung, die
  diesen Aufruf „optimiert" (z. B. überspringt, wenn Genre schon bekannt),
  würde `mb_ids` verlieren, die downstream für „zweiten MB-Aufruf
  überspringen" verwendet werden (Kommentar Zeile 13–16 in
  `musicbrainz_client.py`). Nicht offensichtlich beim ersten Blick auf die
  Genre-Logik allein.
- **String-Werte `"unknown"` vs. `"Unknown"` vs. `None`:** uneinheitlich
  über die drei Module hinweg (Abschnitt 8) — jede Vereinheitlichung, die
  Vergleiche auf einen dieser exakten String-Werte einführt/entfernt,
  riskiert stille Verhaltensänderungen an Fallback-Pfaden.
- **Der MusicBrainz-Doppel-Aufruf ist nicht harmlos-neutral:** Da
  `determine_genre()` beim zweiten Aufruf mit einem bereits verdichteten
  Einzelstring arbeitet (nicht mit den originalen `mb_tags`), könnten in
  seltenen Fällen unterschiedliche `source`-Werte oder sogar
  unterschiedliche `primary`-Werte entstehen, je nachdem, ob
  `_apply_rules()`/`normalize_genre_name()` mit einem bereits normalisierten
  String anders reagieren als mit den Rohdaten. **Nicht verifiziert, ob
  dies in der Praxis tatsächlich abweicht** — nur als Risiko benannt, nicht
  als Fehler behauptet (siehe ausdrückliche Vorgabe in Abschnitt 7 der
  Aufgabenstellung).
- **Last.fm-Pfad-Änderung ist der risikoärmste der beiden:** Da das
  Last.fm-`genre`-Feld nachweislich (Abschnitt 9) nie den Ergebniswert
  beeinflusst, ist eine Entfernung der `determine_genre()`-Berechnung in
  `lastfm_client.py` aus reiner Verhaltenssicht risikoarm — **aber** der
  fast-nie-erreichte Fallback-Zweig (`tags` leer, `raw_lfm_genre` mit
  Kommas vorhanden) müsste explizit erhalten oder bewusst aufgegeben
  werden, nicht stillschweigend.
- **Historischer Sonderfall dokumentiert im Code selbst:** Der
  MusicBrainz-Client-Header (Zeile 6–16) beschreibt bereits eine frühere
  Änderung an genau dieser Schnittstelle (`GenreProcessor liest diese
  Felder und hängt sie an GenreResult.mb_ids, damit
  enhanced_metadata_processor den zweiten MB-Aufruf überspringen kann`)
  — ein Beleg dafür, dass diese Schnittstelle bereits mehrfach angepasst
  wurde und Änderungen hier historisch nicht folgenlos waren.
- **`GENRE_NORMALIZATION` (genre_processor) vs. `genre_aliases`
  (GenreMapper):** beide laden dieselbe YAML-Datei unabhängig voneinander
  beim jeweiligen Konstruktor-Aufruf — eine Änderung an
  `genre_aliases.yaml`-Ladelogik in einer der beiden Stellen (z. B.
  Fallback-Verhalten bei fehlender Datei) muss in beiden konsistent
  gehalten werden, sonst entsteht schleichende Divergenz.

**Ausdrücklich nicht behauptet:** Dass die beiden Algorithmen
(`GenreMapper.determine_genre()` und `GenreProcessor.prioritize_genres()`)
für denselben Tag-Satz tatsächlich unterschiedliche Ergebnisse liefern —
das wurde in dieser Phase **nicht** experimentell verifiziert (kein
Code-Run, nur statische Analyse). Nur die **strukturelle** Verschiedenheit
ist belegt (Abschnitt 2, 8).

---

## 11. Architekturbewertung

**A) Sollten Clients ausschließlich externe Daten adaptieren und die
Genre-Fachlogik vollständig an `genre_processor` übergeben?**
Grundsätzlich ja, im Sinne von CLAUDE.md §17 („Externe APIs und Tools
nicht mit Core-Logik vermischen") und Regel A aus dem vorherigen Audit.
Für den Last.fm-Pfad ist das bereits **faktisch fast erreicht** (das
Client-Genre wird ohnehin verworfen) — es fehlt nur die Bereinigung des
toten Codes. Für den MusicBrainz-Pfad ist es weniger eindeutig, weil der
Client auch für **nicht-Genre-Zwecke** (Album/Jahr über `album_processor.py`)
verwendet wird und die Genre-Berechnung dort unconditional mitläuft.

**B) Gibt es legitime API-spezifische Genre-Transformationen, die im
Client verbleiben müssen?**
Ja — die reine **Extraktion** der Tags aus der jeweiligen API-Antwort-
struktur (`release-group.tags` bei MusicBrainz, `get_top_tags()` bei
Last.fm) ist genuine Adapterlogik und sollte im Client bleiben. Was nicht
zwingend im Client bleiben muss, ist der Schritt **danach**: das Anwenden
von `GenreMapper.determine_genre()`/Priorisierung auf diese Tags.

**C) Gäbe es eine sinnvolle gemeinsame Genre-Domain-Komponente, oder wäre
das unnötige neue Architektur?**
`GenreMapper` (in `utils/genre_map.py`) **ist bereits** diese gemeinsame
Komponente — sie existiert seit Langem und wird von allen drei Stellen
über denselben Singleton verwendet. Eine **neue** Komponente wäre
unnötig (CLAUDE.md: „keine neue Zwischenarchitektur ohne konkreten
Bedarf"). Die eigentliche Frage ist nicht „brauchen wir eine gemeinsame
Komponente", sondern „sollte `GenreProcessor.prioritize_genres()`
(bisher rein `genre_processor`-intern) ebenfalls Teil von `GenreMapper`
werden, damit es EINE kanonische Multi-Tag-Priorisierungsfunktion gibt,
die auch die Clients bei Bedarf nutzen könnten" — das wäre eine
Erweiterung der bestehenden Komponente, keine neue Schicht.

**D) Welche Variante erzeugt die geringste zusätzliche Kopplung?**
Variante A (Abschnitt 12) — Clients liefern nur Rohdaten, `genre_processor`
bleibt alleiniger Entscheider — erzeugt **keine** neue Kopplung, sondern
entfernt bestehende (Clients müssten `GenreMapper` für Genre-Zwecke gar
nicht mehr importieren; der MBID-/Album-Zweck bleibt unberührt).

**E) Wie bleibt `services/metadata → services/clients` erhalten?**
In allen drei Varianten unverändert: Clients werden weiterhin von
`genre_processor.py`/`album_processor.py` konsumiert, nie umgekehrt. Selbst
bei Variante A (Genre-Logik-Entfernung aus den Clients) ändert sich nur
der **Inhalt** der Rückgabe-Dicts, nicht die Aufrufrichtung.

---

## 12. Zielvarianten

### Variante A — Client liefert nur rohe/API-spezifische Genre-Daten; `genre_processor` besitzt die Fachlogik

Entfernt die `determine_genre()`-Aufrufe aus `lastfm_client.fetch_metadata()`
(Zeile 128–135) und `musicbrainz_client._build_metadata()` (Zeile 428–440).
Clients liefern nur noch `tags`/`mb_tags` roh, kein `genre`-Feld mehr (oder
ein reduziertes `genre: None`/entferntes Feld). `genre_processor.py` müsste
für den MusicBrainz-Pfad **neu** eine Priorisierung über die rohen
`mb_tags` einführen (aktuell existiert dafür noch kein Äquivalent zu
`prioritize_genres()` für den MB-Pfad — dort wird bisher direkt
`determine_genre()` auf den bereits reduzierten Client-String angewendet).

### Variante B — Gemeinsame neutrale Genre-Domain-Komponente für tatsächlich geteilte Logik

`GenreMapper` (bereits vorhanden, Abschnitt 11 C) wird um eine
Multi-Tag-Priorisierungsfunktion erweitert (im Kern eine Verallgemeinerung
von `GenreProcessor.prioritize_genres()`), sodass sowohl Last.fm- als auch
MusicBrainz-Pfad dieselbe kanonische Priorisierung nutzen — Clients
könnten optional weiterhin ein Vorschlags-Genre liefern, `genre_processor`
entscheidet aber immer über die kanonische Methode.

### Variante C — Bestehende Aufteilung weitgehend beibehalten

Falls die tiefere Analyse (über diese Phase hinaus) zeigt, dass die
Divergenz zwischen `determine_genre()` und `prioritize_genres()`
tatsächlich beabsichtigte, unterschiedliche Zwecke erfüllt (Einzelstring-
Normalisierung vs. Multi-Tag-Ranking) und keine echte Redundanz vorliegt
— dann nur den **nachweislich toten** Last.fm-Client-Aufruf entfernen
(kleinstmögliche Änderung), MusicBrainz-Doppel-Aufruf unangetastet lassen
oder nur dokumentieren.

---

## 13. Variantenvergleich

| Kriterium | Variante A | Variante B | Variante C |
|---|---|---|---|
| Architektur | Klar (Clients = reine Adapter) | Klar, aber Erweiterung einer bestehenden Utility | Unverändert, nur punktuelle Bereinigung |
| Dependency-Richtung | unverändert (`metadata → clients`) | unverändert | unverändert |
| Verhaltensrisiko | **Mittel–hoch** — MB-Pfad braucht neue Priorisierungslogik, die es heute so nicht gibt; muss Verhalten für alle bisherigen `source`-Werte nachbilden | **Mittel** — Erweiterung von `GenreMapper`, alle drei Konsumenten müssten auf die neue Methode umgestellt werden, aber die Kernlogik existiert bereits (`prioritize_genres()` als Vorlage) | **Niedrig** — nur Entfernung eines nachweislich toten Aufrufs (Last.fm), keine neue Logik nötig |
| Testaufwand | Hoch — Characterization für MB-Pfad in beiden Richtungen (alt vs. neu) nötig | Hoch — neue Methode + Umstellung aller drei Konsumenten braucht eigene Tests | Niedrig — 1 Regressionstest für Last.fm-Client genügt (Genre-Feld entfernt, Tags unverändert) |
| Änderungsumfang | 2 Client-Dateien + `genre_processor.py` (neue MB-Priorisierung) | `utils/genre_map.py` + 3 Konsumenten | 1 Datei (`lastfm_client.py`), optional MB-Doppel-Aufruf dokumentieren |
| Erweiterbarkeit | Gut — klare Trennung erleichtert künftige neue Genre-Quellen | Sehr gut — eine kanonische Priorisierung für alle künftigen Quellen | Unverändert — künftige Quellen würden dasselbe Muster fortsetzen |
| Nutzen ggü. Ist-Zustand | Hoch (räumt Regel-A-Verstoß + MB-Doppel-Aufruf vollständig auf) | Hoch (zusätzlich: konsistente Priorisierung für alle Quellen, nicht nur Last.fm) | Niedrig–mittel (nur der unstrittig tote Teil verschwindet) |

---

## 14. Empfehlung

**Umsetzung sinnvoll, aber nicht als ein einziger großer Schritt.** Die
Analyse zeigt zwei klar unterschiedlich risikobehaftete Teilprobleme, die
**getrennt** behandelt werden sollten:

1. **Last.fm-Client-Bereinigung (aus Variante A/C):** risikoarm,
   nachweislich toter Code (Abschnitt 3, 9) — guter, kleiner erster
   ARCH-012-Phase-2-Kandidat für sich allein.
2. **MusicBrainz-Doppel-Aufruf + fehlende Multi-Tag-Priorisierung
   (Variante A oder B):** deutlich größerer Eingriff, da für den
   MB-Pfad aktuell **keine** Äquivalent-Priorisierung zur rohen Tag-Liste
   existiert — müsste zuerst charakterisiert und mit echten Beispielwerten
   verglichen werden (Abschnitt 9, Lücke 1 und 3), bevor irgendetwas
   geändert wird.

**Empfohlene Variante für Phase 2 (falls freigegeben): Variante A,
begrenzt auf den Last.fm-Teil zuerst**, mit der MusicBrainz-Frage als
separate, eigene Phase 3 danach (ggf. Richtung Variante B, falls sich
zeigt, dass eine gemeinsame Priorisierungsmethode für beide Quellen
sinnvoll ist).

**Nicht empfohlen:** Variante B sofort und vollständig umzusetzen — zu
groß für einen einzelnen Schritt, ohne dass zuerst der MusicBrainz-Pfad
separat charakterisiert wurde.

### Welche Characterization-Tests zuerst notwendig sind

Vor jeder Codeänderung, unabhängig von der gewählten Variante:

1. Ein Test, der `GenreMapper.determine_genre()` mit einem realistischen
   komma-verketteten Multi-Tag-String (echte YAML-Daten, kein Mock)
   aufruft und das Ergebnis mit `GenreProcessor.prioritize_genres()` auf
   denselben Tags vergleicht — beantwortet die zentrale offene Frage
   („divergieren beide Algorithmen tatsächlich, und wenn ja wann").
2. Ein Regressionstest, der das **aktuelle** `lastfm_client.fetch_metadata()`-
   Verhalten inklusive des toten `genre`-Feldes exakt festschreibt (bevor
   es entfernt wird) — Basis für einen sicheren Vorher/Nachher-Vergleich.
3. Ein Regressionstest für den MusicBrainz-Doppel-Aufruf, der exakt
   dokumentiert, welche `source`-Werte (`"normalized"`, `"hierarchy"`,
   `"artist_exact"` etc.) für eine repräsentative Menge realer
   Tag-Kombinationen aktuell entstehen — als Baseline für Variante A/B.

### Voraussichtlich betroffene Dateien (bei Umsetzung, nicht in dieser Phase)

- `services/clients/lastfm_client.py`
- `services/clients/musicbrainz_client.py`
- `services/metadata/genre_processor.py`
- ggf. `utils/genre_map.py` (nur bei Variante B)
- `tests/test_lastfm_client.py`, `tests/test_musicbrainz_client.py`,
  `tests/test_genre_processor.py`, `tests/test_genre_mapper_advanced.py`

### Ausdrücklich NICHT anzufassen

- `services/metadata/album_processor.py` — konsumiert `mb_data` nur für
  Album/Jahr, ist von der Genre-Frage inhaltlich unberührt (auch wenn es
  indirekt vom entfernten Overhead profitieren würde).
- `services/metadata/enhanced_metadata_processor.py` — Fassaden-Aufruf-
  struktur (`_determine_genre_with_stats()`) bleibt unverändert, unabhängig
  von der gewählten Variante.
- Mapping-Dateien selbst (`genre_hierarchy.yaml`, `genre_aliases.yaml`,
  `genre_filters.yaml`, `artist_genre.yaml`) — diese Phase betrifft nur
  den Code, der sie liest, nicht ihren Inhalt (CLAUDE.md §10/§28).
- `services/downloader/**` — kein Consumer der Genre-Logik direkt.

**Geschätztes Risiko:**
- Last.fm-Teilschritt: **niedrig**.
- MusicBrainz-Teilschritt: **mittel–hoch** (P0-Domäne, fehlende
  Vergleichsbasis, siehe Characterization-Test 1 oben).

### Empfohlene nächste Phase

**ARCH-012 Phase 2 (begrenzt): Last.fm-Client-Bereinigung** — Entfernung
des nachweislich toten `determine_genre()`-Aufrufs in
`lastfm_client.fetch_metadata()`, mit vorherigem Characterization-Test
(Punkt 2 oben). Die MusicBrainz-Frage (Doppel-Aufruf, fehlende
Multi-Tag-Priorisierung) wird als eigene, spätere Phase 3 vorgeschlagen,
nicht Teil von Phase 2.

---

## 15. Entscheidungsgate

> **ARCH-012 Phase 1 — Characterization abgeschlossen.**
> **Entscheidungsgate erreicht.**
> **Keine Codeänderungen durchgeführt.**
>
> **Zentrale Antwort:** Die Genre-Logik ist **nicht identisch dupliziert**
> (kein Copy-Paste), aber **strukturell doppelt verantwortet**:
> - Last.fm-Pfad: Client berechnet ein Genre, das **praktisch nie**
>   verwendet wird (`genre_processor` nutzt einen eigenen, anderen
>   Algorithmus auf denselben Rohdaten) — **nachweislich toter Code**,
>   belegt durch Codepfad-Analyse und bestehende Tests.
> - MusicBrainz-Pfad: Dieselbe `GenreMapper.determine_genre()`-Methode
>   wird **zweimal** aufgerufen — einmal im Client (auf rohen Tags), einmal
>   in `genre_processor` (auf dem bereits verdichteten Client-Ergebnis) —
>   **belegter, aber nicht in seiner Ergebnis-Auswirkung experimentell
>   verifizierter** Doppel-Aufruf.
> - Beide Client-Aufrufe verwenden dieselbe Singleton-`GenreMapper`-Instanz
>   wie `genre_processor` selbst — es handelt sich um **eine** gemeinsame
>   Wissensbasis (YAML-Dateien), nicht um zwei divergierende Datenquellen.
>
> **Empfehlung für Phase 2: Last.fm-Client-Bereinigung** (Entfernung des
> toten `determine_genre()`-Aufrufs in `lastfm_client.py`, kleinster,
> risikoärmster nächster Schritt) — mit vorherigem Characterization-Test
> für das aktuelle Last.fm-Client-Verhalten. Die MusicBrainz-Doppel-Aufruf-
> Frage bleibt als separate, größere Phase 3 zurückgestellt, bis eine
> eigene Multi-Tag-Priorisierung für den MB-Pfad entworfen und
> characterisiert ist.

---

## 16. Phase 2 — Last.fm-Bereinigung

### 16.1 Ausgangszustand

`services/clients/lastfm_client.py::fetch_metadata()` berechnete über
`self.genremapper.determine_genre(raw_genre=", ".join(tag_names),
artist_name=artist)` (vormals Zeile 130–134) ein `"genre"`-Feld im
Rückgabe-Dict. Laut Phase 1 (Abschnitt 3, 9) wurde dieser Wert vom
einzigen Produktions-Consumer (`genre_processor._fetch_genre_from_lastfm()`)
praktisch nie verwendet — nur als faktisch unerreichbarer Fallback, falls
`tags` leer wäre, was bei vorhandenen Last.fm-Tags nie eintritt, da
`fetch_metadata()` `tags` immer mitliefert.

### 16.2 Characterization-Test (vor der Änderung ergänzt und grün verifiziert)

Neuer Test `tests/test_genre_processor.py::TestLastFmGenreFieldIsIgnored::test_genre_field_value_does_not_affect_effective_result`:
ruft `genre_processor.determine_genre_with_fallbacks()` zweimal auf — einmal
mit einem `FakeLastFmClient`, dessen Antwort-Dict ein bewusst falsches
`"genre": "Totally Wrong Genre Value"` enthält, einmal mit einem
`FakeLastFmClient`, dessen Antwort-Dict **gar kein** `"genre"`-Feld besitzt
(exakt der Zustand nach der Bereinigung) — bei identischen `"tags"`. Beide
Aufrufe liefern ein **identisches** `GenreResult` (`primary`, `secondary`,
`source`, `raw_tags`).

Vor der Codeänderung ausgeführt (`pytest tests/test_genre_processor.py -q`):
**23 passed** — bestätigt, dass das `"genre"`-Feld schon vorher keinen
Einfluss auf das Ergebnis hatte (Beweis des toten Pfads), bevor
irgendetwas an `lastfm_client.py` geändert wurde.

### 16.3 Entfernter Codepfad

In `services/clients/lastfm_client.py`:

- `from utils.genre_map import GenreMapper` (Import) — entfernt, da nach
  Entfernung des Aufrufs ungenutzt.
- `self.genremapper = GenreMapper()` (`__init__`) — entfernt, da
  ausschließlich für den toten Pfad gehalten.
- Der bedingte Block `genre = "unknown"; if include_genre and tag_names:
  genre_result = self.genremapper.determine_genre(...); if genre_result
  and ...: genre = genre_result.primary` — ersetzt durch den festen
  Literal-Wert `"genre": "unknown"` in der Rückgabe.

**Erhalten:** Last.fm-API-Abfrage (`_get_lastfm_data()` unverändert),
Rohdaten-Sammlung/-Deduplizierung, vollständige Rückgabestruktur (alle
bisherigen Dict-Keys `tags`/`listeners`/`playcount`/`album`/`wiki`/`genre`
unverändert vorhanden), Fehlerbehandlung (`try`/`except`, Timeout-Pfad),
Logging, öffentliche Methodensignatur (`fetch_metadata(self, title, artist,
include_genre=True, mbid=None)` unverändert — `include_genre` wird
akzeptiert, aber nicht mehr ausgewertet).

### 16.4 Warum das Verhalten unverändert bleibt

`"genre"` war vor der Änderung für den einzigen Aufrufer bereits praktisch
immer `"unknown"`-äquivalent im Effekt (der berechnete Wert wurde
verworfen, s. 16.2). Nach der Änderung ist `"genre"` **immer** buchstäblich
`"unknown"` — für `genre_processor._fetch_genre_from_lastfm()` identisches
Verhalten: der `if raw_lfm_genre and "," in raw_lfm_genre and not tags`-
Fallback-Zweig (`genre_processor.py`, unverändert) greift so oder so nicht,
solange `tags` vorhanden ist; ist `tags` leer, greift ohnehin der
`if not tags: return None`-Pfad **davor**. Kein Szenario, in dem sich das
tatsächliche `GenreResult` ändert — bestätigt durch den in 16.2
beschriebenen Test, der vor **und** nach der Änderung grün bleibt.

### 16.5 Betroffene Dateien

**Produktionscode:**
- `services/clients/lastfm_client.py` (einzige geänderte Produktionsdatei)

**Tests:**
- `tests/test_genre_processor.py` — neue Klasse
  `TestLastFmGenreFieldIsIgnored` mit dem Characterization-Test aus 16.2
  ergänzt. Keine bestehenden Tests verändert.
- `tests/test_lastfm_client.py` — Modul-Docstring und `_make_client()`-
  Helper aktualisiert (kein `genremapper`-Parameter/Patch mehr nötig, da
  `GenreMapper` in `lastfm_client.py` nicht mehr referenziert wird); drei
  Tests angepasst:
  - `test_tags_present_with_include_genre_determines_genre` →
    `test_tags_present_genre_field_stays_unknown_placeholder` (prüft jetzt
    den festen Platzhalter statt eines berechneten Werts)
  - `test_include_genre_false_skips_genre_determination` →
    `test_include_genre_flag_no_longer_affects_result` (prüft, dass
    `include_genre=True`/`False` identische Ergebnisse liefern)
  - `test_no_tags_genre_stays_unknown` — Assertion auf den entfernten
    `genremapper.determine_genre.assert_not_called()` entfernt, Kernaussage
    (`result["genre"] == "unknown"`) unverändert

**Ausdrücklich nicht geändert:** `services/metadata/genre_processor.py`,
`services/clients/musicbrainz_client.py`, `utils/genre_map.py`
(`GenreMapper`), alle `mapping/genre_*.yaml`-Dateien,
`tests/test_musicbrainz_client.py`, `tests/test_genre_mapper_advanced.py`.

### 16.6 Tests vorher/nachher

| | Last.fm-Tests | Genre-Processor-Tests |
|---|---|---|
| Vorher | 13 Tests, 13 passed | 22 Tests, 22 passed |
| Nachher | 13 Tests (3 angepasst), 13 passed | 23 Tests (1 neu), 23 passed |

Gezielter Lauf nach der Änderung
(`pytest tests/test_lastfm_client.py tests/test_genre_processor.py -q`):
**35 passed.**

Zusätzlich zur Sicherheit mitgelaufen (unverändert, keine eigene
Codeänderung betroffen): `tests/test_musicbrainz_client.py`,
`tests/test_genre_mapper_advanced.py`, `tests/test_metadata_modules.py`,
`tests/test_enhanced_metadata_processor_aclose.py`,
`tests/test_metadata_processor_happy_path.py` — alle grün bis auf die
bekannten, unveränderten `TestTitleCleaner`-Vorbestand-Fehler (siehe 16.7).

### 16.7 Regressionsergebnis

`pytest tests/ -q`:

```text
1010 passed, 15 failed (bekannt, unverändert)
```

**1010 statt 1009** — Differenz von genau **+1**, entspricht exakt dem
neuen Characterization-Test aus 16.2. Alle 15 Fehlschläge sind
namensgleich mit der bekannten Baseline (`test_auto_learn.py` 5 inkl.
Subfails, `test_metadata_modules.py::TestTitleCleaner` 5 inkl. Subfails,
`test_suite.py` 4 wegen fehlendem `pytest-asyncio`) — **keine neue
Regression.**

### 16.8 Import-/Referenz-Audit

- `determine_genre` in `services/clients/lastfm_client.py`: 0 funktionale
  Treffer (nur noch im erklärenden Kommentar erwähnt).
- `.genremapper` (Attribut-Zugriff) repo-weit: 0 Treffer.
- `GenreMapper(` weiterhin korrekt funktionsfähig an allen tatsächlich
  benötigten Stellen: `services/metadata/enhanced_metadata_processor.py`,
  `utils/genre_map.py` selbst, `mapping/test_genre_map.py` — unverändert,
  `musicbrainz_client.py` nutzt weiterhin `get_genre_mapper()` unverändert.
- Import-Smoke-Test: `services.clients.lastfm_client`,
  `services.metadata.genre_processor`,
  `services.metadata.enhanced_metadata_processor`, `utils.genre_map` —
  alle vier importieren fehlerfrei, keine Zirkelimporte.

### 16.9 Diff-/Scope-Audit

`git diff --stat`: genau 1 Produktionsdatei
(`services/clients/lastfm_client.py`, 11 Zeilen hinzugefügt, 13 entfernt)
und 2 Testdateien (`tests/test_genre_processor.py` +50,
`tests/test_lastfm_client.py` +63/-26) geändert. Keine Änderung an
`genre_processor.py`, `musicbrainz_client.py`, `utils/genre_map.py`,
Mapping-YAMLs, README.md, CLAUDE.md oder
`docs/MusicBot_ENGINEERING_BASELINE.md` — kein konkreter, durch diese
Phase verursachter Dokumentationswiderspruch gefunden, daher keine dieser
Dateien angefasst. Keine unbeabsichtigten Änderungen außerhalb des
beschriebenen Scopes.

### 16.10 Verbleibender Folgepunkt

Die MusicBrainz-Doppelberechnung (Phase 1, Abschnitt 4, 9) — derselbe
`GenreMapper.determine_genre()`-Aufruf einmal im Client (auf rohen Tags)
und einmal in `genre_processor._fetch_genre_from_musicbrainz()` (auf dem
bereits verdichteten Client-Ergebnis) — bleibt **vollständig unangetastet**.
Diese Phase hat sie bewusst nicht verändert, da erstens explizit außerhalb
des Scopes, und zweitens laut Phase 1 (Abschnitt 9, Lücke 1 und 3) noch
keine ausreichende Vergleichsbasis (Test, der `determine_genre()` mit
Multi-Tag-String gegen die tatsächliche MB-Pipeline verifiziert) existiert.
Empfohlener Kandidat für eine eigene ARCH-012 Phase 3.

---

# Phase 3A — MusicBrainz Genre Characterization

## 17.1 Ziel und Scope

Reine Analyse/Characterization der genau in Phase 1 (Abschnitt 4, 9)
offen gelassenen Vergleichsbasis: Was passiert **tatsächlich**, mit
**echten** Multi-Tag-Eingaben, entlang des heutigen MusicBrainz-Genre-
Datenflusses? Kein Refactoring, keine Änderung an
`musicbrainz_client.py`, `genre_processor.py`, `GenreMapper` oder den
Genre-YAML-Dateien. Einzige Änderung dieser Phase: neue
Characterization-Tests (Abschnitt 17.10).

Methodik: alle Aussagen in diesem Abschnitt sind **empirisch verifiziert**
— gegen die echte `GenreMapper`-Instanz und echte `mapping/genre_*.yaml`-
Dateien ausgeführt (kein Mock für `determine_genre()`/`prioritize_genres()`
selbst), nicht nur aus dem Code hergeleitet. Die verwendeten Tag-Beispiele
sind, sofern nicht ausdrücklich als „synthetisch" gekennzeichnet, reale
Genre-Bezeichnungen aus `mapping/genre_hierarchy.yaml`/`genre_aliases.yaml`
(z. B. `"ruhrpott rap"`, `"hip hop"`) — keine erfundenen Werte, die die
reale Implementierung nicht stützt.

## 17.2 Rekonstruierter Ist-Datenfluss

```text
1. MusicBrainz API Response
   release-group.tags: [{"name": "Ruhrpott Rap"}, {"name": "Hip Hop"}, ...]
   ↓
2. musicbrainz_client.py::_build_metadata() (Zeile 414)
   mb_tags = [t["name"] for t in release_group.get("tags", [])]
   mb_tags_str = ", ".join(mb_tags)   # z.B. "ruhrpott rap, hip hop, trap"
   ↓
3. ERSTER Aufruf: genre_mapper.determine_genre(raw_genre=mb_tags_str, artist_name=X)
   → Ergebnis siehe 17.4 (kein einzelnes Genre bei >1 Tag!)
   ↓
4. Client-Rückgabefeld: {"tags": mb_tags, "genre": genre_value, "mbid": ..., ...}
   ↓
5. Übergabe an genre_processor._fetch_genre_from_musicbrainz()
   raw_mb_genre = mb_data.get("genre", "")
   ↓
6. ZWEITER Aufruf: genre_mapper.determine_genre(raw_genre=raw_mb_genre, artist_name=X)
   → Ergebnis siehe 17.5 (reproduziert i. d. R. denselben Wert)
   ↓
7. mb_genre_result.raw_tags = mb_data.get("tags", [])   # Original-Tags werden
   NUR als Metadatum anhängt, NICHT für primary/secondary neu ausgewertet
   ↓
8. finales GenreResult(primary=..., secondary=[], source="normalized"/..., raw_tags=mb_tags, mb_ids=...)
   ↓
9. Übergabe an MetadataResult.genres = {"primary": ..., "secondary": ...}
   ↓
10. services/metadata/tag_writer.py (Zeile 204) liest genres_result.primary/secondary
    direkt für das echte Datei-Tag (ID3/MP4 Genre-Feld)
```

Jede Stufe im Detail (Input/Output/Transformation/Consumer) ist bereits in
Phase 1, Abschnitt 4 und 5 dokumentiert und wird hier nicht wiederholt —
neu in Phase 3A ist die **empirische Auswertung** von Stufe 3 und 6.

## 17.3 MusicBrainz-Rohdaten

`release_group.get("tags", [])` liefert bei realen MusicBrainz-Releases
typischerweise **mehrere** Community-Tags pro Release-Group (0 bis oft
5–15 Stück, MusicBrainz-Tagging ist community-getrieben und nicht auf
einen einzelnen Tag begrenzt). Der Code selbst behandelt das als Liste
(`mb_tags: List[str]`) — die Mehrfach-Tag-Situation ist der **Normalfall**,
nicht ein Randfall.

## 17.4 Erster `determine_genre()`-Aufruf (im Client)

**Empirisch verifiziert** (echter `GenreMapper` gegen `mapping/`,
`artist_name` bewusst unbekannt gehalten, um Schritt 1–3 von
`determine_genre()` zu umgehen und ausschließlich Schritt 4/5 zu prüfen):

| Eingabe-Tags | `raw_genre` (joined) | `determine_genre()`-Ergebnis | `source` |
|---|---|---|---|
| `["hip hop"]` | `"hip hop"` | `primary="Hip Hop"` | `normalized` |
| `["ruhrpott rap", "hip hop", "trap"]` | `"ruhrpott rap, hip hop, trap"` | `primary="Ruhrpott Rap, Hip Hop, Trap"` | `normalized` |
| `["hip hop", "ruhrpott rap", "trap"]` (andere Reihenfolge) | `"hip hop, ruhrpott rap, trap"` | `primary="Hip Hop, Ruhrpott Rap, Trap"` | `normalized` |
| `["HIP HOP", "Ruhrpott Rap"]` (Groß-/Kleinschreibung) | `"HIP HOP, Ruhrpott Rap"` | `primary="Hip Hop, Ruhrpott Rap"` | `normalized` |
| `["german hip hop", "deutscher rap"]` (beide würden einzeln zu „Deutschrap" aliasen) | `"german hip hop, deutscher rap"` | `primary="German Hip Hop, Deutscher Rap"` | `normalized` |
| `[]` (keine Tags) | `""` | `None` (kein `GenreResult`) | — |

**Zentraler Befund — Root Cause:** `GenreMapper.normalize_genre_name()`
(`utils/genre_map.py`, Zeile 390–434, aufgerufen aus `determine_genre()`s
Schritt 5) ist für **einen einzelnen Genre-String** konzipiert:

1. Exakter Lookup in `self.overrides`/`self.genre_aliases` — erwartet den
   **gesamten** übergebenen String als **einen** Schlüssel. Ein
   kommagetrennter Multi-Tag-String wie `"ruhrpott rap, hip hop, trap"`
   ist als Ganzes in keiner YAML-Datei als Schlüssel hinterlegt (Aliase
   sind pro Einzel-Tag gepflegt) → kein Treffer.
2. Fallback (Zeile 417–434): `genre_name.split()` — **Whitespace-Split**,
   dann pro Wort `.capitalize()` (mit Sonderbehandlung für Abkürzungen/
   Bindestriche), wieder mit `" ".join()` zusammengesetzt. Ein Komma
   bleibt dabei am vorherigen Wort haften (`split()` trennt nur auf
   Leerzeichen) — das Ergebnis ist der **komplette Eingabestring,
   Wort-für-Wort title-gecast, Kommas erhalten**.

`get_main_genre()` (Hierarchie-Aufstieg, Zeile 368–387) wird danach
ebenfalls mit dem **gesamten** normalisierten String als Schlüssel
aufgerufen (`self.hierarchy.get(key)`) — auch das schlägt für einen
Multi-Tag-String fehl (Hierarchie-Schlüssel sind Einzelgenres), weshalb
`source` bei `"normalized"` bleibt, nie `"hierarchy"` erreicht wird.

**Zusatzbefund (Regex-Regel-Stufe, Schritt 4 vor Schritt 5):**
`_apply_rules()` (Zeile 580–604) hätte theoretisch die Chance, einen
Multi-Tag-String über `pattern.search()` (Teilstring-Suche, nicht
`fullmatch`) zu „retten". Empirisch feuerte in **keinem** der geprüften
Fälle eine Regel (`source` war nie `"rule"`). Grund (zusätzlich geprüft,
**nicht** Teil des ARCH-012-Scopes, nur zur Transparenz dokumentiert):
`GenreMapper._do_init()` lädt Regeln über
`rules_data.get("GENRE_RULES", [])` (Zeile 280) — die tatsächliche Datei
`mapping/genre_rules.yaml` verwendet jedoch die Top-Level-Schlüssel
`keyword_rules`/`artist_rules`, nicht `GENRE_RULES`. `self.rules` ist
dadurch **für alle Aufrufer, nicht nur MusicBrainz** strukturell leer —
`_apply_rules()` ist permanent ein No-op. Dies ist ein eigenständiger,
von der MusicBrainz-Frage unabhängiger Befund in `GenreMapper`/
`genre_rules.yaml` und **ausdrücklich nicht Gegenstand dieser Phase**
(„GenreMapper verändern"/„Genre-YAML verändern" sind laut Scope-Gate
verboten) — hier nur dokumentiert, weil er erklärt, warum Schritt 4 in
der Praxis nie eingreift und Schritt 5 (mit dem oben beschriebenen
Title-Case-Verhalten) für jeden nicht manuell gemappten Fall
entscheidend ist.

## 17.5 Übergabewert an `genre_processor` und zweite Genre-Verarbeitung

`genre_processor._fetch_genre_from_musicbrainz()` liest
`raw_mb_genre = mb_data.get("genre", "")` — das ist exakt der in 17.4
ermittelte, ggf. bereits title-gecaste Multi-Tag-String. Ist er nicht leer
und nicht `"unknown"` (`has_genre`), wird `determine_genre(raw_genre=raw_mb_genre,
artist_name=artist_name)` **erneut** aufgerufen — **empirisch verifiziert**:

| Client-Ergebnis (Stufe 1) | Zweiter Aufruf (Stufe 2, gleicher Artist) | Divergenz? |
|---|---|---|
| `"Hip Hop"` | `"Hip Hop"`, `source=normalized` | Nein |
| `"Ruhrpott Rap, Hip Hop, Trap"` | `"Ruhrpott Rap, Hip Hop, Trap"`, `source=normalized` | Nein |
| `"Hip Hop, Ruhrpott Rap, Trap"` | `"Hip Hop, Ruhrpott Rap, Trap"`, `source=normalized` | Nein |
| `"German Hip Hop, Deutscher Rap"` | `"German Hip Hop, Deutscher Rap"`, `source=normalized` | Nein |

**Der zweite Aufruf ist in allen geprüften Fällen idempotent** — ein
bereits title-gecaster String bleibt beim erneuten Title-Casing
unverändert (jedes Wort ist bereits großgeschrieben). Der zweite Aufruf
**korrigiert den Fehler aus Stufe 1 nicht**, **verschlimmert ihn aber auch
nicht weiter** — er reproduziert ihn unverändert.

`mb_genre_result.raw_tags = mb_data.get("tags", [])` (Zeile 585) hängt die
**ursprünglichen, sauberen** Einzel-Tags separat als Metadatum an das
Ergebnis an — diese werden aber an **keiner Stelle** genutzt, um
`primary`/`secondary` neu zu berechnen (kein Äquivalent zu
`prioritize_genres()` für den MusicBrainz-Pfad, siehe 17.6/17.9).

## 17.6 Vergleichsmatrix

| Eingabe | `determine_genre()` (1. Aufruf, Client) | `determine_genre()` (2. Aufruf, Processor) | `prioritize_genres()` (nur Last.fm-Pfad, zum Vergleich) |
|---|---|---|---|
| Single Tag (`["hip hop"]`) | `Hip Hop` (`normalized`) | `Hip Hop` (`normalized`) — identisch | `Unknown` (kein Priorität-Mapping-Treffer außerhalb Hierarchie-Tiefe 0 ohne Filterlogik-Sonderfall) |
| Multi Tag, Subgenre zuerst (`["ruhrpott rap", "hip hop", "trap"]`) | `Ruhrpott Rap, Hip Hop, Trap` (`normalized`) | identisch | `Ruhrpott Rap`, secondary=`[Hip Hop]` |
| Multi Tag, Hauptgenre zuerst (`["hip hop", "ruhrpott rap", "trap"]`) | `Hip Hop, Ruhrpott Rap, Trap` (`normalized`) | identisch | `Ruhrpott Rap`, secondary=`[Hip Hop]` (Reihenfolge-unabhängig, da nach Hierarchie-Tiefe sortiert) |
| bekannte + unbekannte Tags gemischt (`["hip hop", "xyz-unknown", "abc-unknown"]`, synthetisch) | `Hip Hop, Xyz-Unknown, Abc-Unknown` (`normalized`) | identisch | `Xyz-unknown`, secondary=`[Abc-unknown]` — **empirisch verifiziert**: `"hip hop"` steht in `mapping/genre_filters.yaml::IGNORE_SECONDARY` (Zeile 27) und wird von `prioritize_genres()` deshalb explizit herausgefiltert, bevor überhaupt priorisiert wird; die verbleibenden unbekannten Tags landen im Fallback-Zweig ohne `tag_priorities`-Treffer (erstes valides Tag = primary) |
| nur unbekannte Tags (synthetisch) | title-gecaster Gesamtstring (`normalized`) | identisch | erstes Tag als primary, Rest als secondary |
| leere Eingabe (`[]`) | `None` (kein `GenreResult`) | Sentinel `source="musicbrainz_ids_only"`, `primary=""` (nur falls `mb_ids` vorhanden) | `Unknown, []` |
| Groß-/Kleinschreibung gemischt (`["HIP HOP", "Ruhrpott Rap"]`) | `Hip Hop, Ruhrpott Rap` (`normalized`) | identisch | `Ruhrpott Rap` (case-insensitive durch `.lower()` in `prioritize_genres()`) |
| Aliase, die einzeln zusammenfallen würden (`["german hip hop", "deutscher rap"]`, beide → „Deutschrap") | `German Hip Hop, Deutscher Rap` (`normalized` — **Alias greift NICHT**, da der Gesamtstring kein Alias-Schlüssel ist) | identisch | `Deutschrap` (Alias greift korrekt PRO Tag) |
| Duplikate (`["ruhrpott rap", "ruhrpott rap", "berliner rap"]`) | `Ruhrpott Rap, Ruhrpott Rap, Berliner Rap` (`normalized`, Duplikat bleibt wörtlich erhalten) | identisch | `Berliner Rap`, secondary=`[Ruhrpott Rap]` — **empirisch verifiziert**: `"ruhrpott rap"` erscheint trotz doppelten Vorkommens nur einmal in `secondary` (`seen`-Set-Dedup korrekt), `"Berliner Rap"` gewinnt als primary gegenüber gleich priorisiertem `"Ruhrpott Rap"` durch den alphabetischen Sortier-Tiebreak (`sort(key=lambda x: (-x[1], x[0]))`) |

**Kernaussage der Matrix:** In **jedem** Fall mit mehr als einem Tag
liefert der aktuelle MusicBrainz-Pfad (`determine_genre()` ×2) ein
qualitativ anderes, schlechteres Ergebnis als das, was
`prioritize_genres()` (bereits vorhanden, aber nur für Last.fm verdrahtet)
auf denselben Rohdaten liefern würde. Bei genau einem Tag sind beide
Pfade gleichwertig.

## 17.7 Multi-Tag-Characterization (Zusammenfassung)

- **Reihenfolge-Sensitivität:** `determine_genre()` behält die
  MusicBrainz-Tag-Reihenfolge 1:1 im Ergebnis-String bei (kein Ranking).
  `prioritize_genres()` ist reihenfolge-**unabhängig** (sortiert nach
  Hierarchie-Tiefe).
- **Groß-/Kleinschreibung:** in beiden Pfaden korrekt normalisiert (kein
  Unterschied).
- **Aliase:** funktionieren in `determine_genre()` nur, wenn der
  **gesamte** Eingabestring exakt einem Alias-Schlüssel entspricht — bei
  mehreren Tags praktisch nie der Fall. `prioritize_genres()` wendet
  Aliase pro Einzel-Tag an — funktioniert wie vorgesehen.
- **Duplikate:** `determine_genre()` dedupliziert nicht.
  `prioritize_genres()` dedupliziert über `seen`.
- **Bekannt+unbekannt gemischt:** `determine_genre()` behandelt alle
  gleich (title-cast den ganzen String). `prioritize_genres()` filtert
  über `IGNORE_SECONDARY`, gewichtet bekannte Genres nach Hierarchie-
  Tiefe vor unbekannten (sofern ein `tag_priorities`-Treffer existiert).

## 17.8 Informationsverlustanalyse

**Ja, es wird Information verändert/degradiert — bereits beim ERSTEN
`determine_genre()`-Aufruf, nicht erst beim zweiten:**

- **Welche Information?** Die Fähigkeit, aus mehreren MusicBrainz-Tags
  das **spezifischste, hierarchisch korrekte** Einzelgenre auszuwählen
  (Subgenre vor Hauptgenre, wie `prioritize_genres()` es für Last.fm
  leistet) geht verloren — `determine_genre()` behandelt die
  Tag-**Liste** als undurchsichtigen String-**Blob**.
- **Ist sie rekonstruierbar?** Ja — die Original-Tags bleiben unter
  `GenreResult.raw_tags` erhalten (Zeile 585 in `genre_processor.py`).
  Eine künftige Änderung könnte sie dort abgreifen und nachträglich
  korrekt priorisieren. Aktuell tut das aber niemand.
- **Beeinflusst sie das finale Genre?** Ja, direkt: `GenreResult.primary`
  (und damit `MetadataResult.genres["primary"]`, und damit potenziell das
  tatsächliche Datei-Tag über `tag_writer.py`) enthält bei Multi-Tag-
  MusicBrainz-Treffern für unbekannte Artists/Kanäle **keinen** validen
  Einzelgenre-Namen, sondern eine kommagetrennte, title-gecaste Aufzählung
  aller Tags.
- **Gibt es Fälle, in denen das finale Ergebnis anders wäre, wenn
  `genre_processor.py` die Roh-Tags statt des Client-Ergebnisses
  erhalten und über `prioritize_genres()` verarbeitet hätte?** Ja, in
  **jedem** der in 17.6 geprüften Multi-Tag-Fälle (Abweichung `primary`
  UND `secondary`).

**Wichtige Einschränkung/Präzisierung:** Dieser Informationsverlust
**existiert unabhängig vom zweiten Aufruf** — er entsteht bereits im
Client (Stufe 1). Der zweite Aufruf ist nicht die Ursache, sondern
reproduziert (idempotent) das bereits degradierte Ergebnis unverändert
weiter (17.5). Diese Unterscheidung ist zentral für Abschnitt 17.9/17.11.

**Kein Verlust bei Artist-/Channel-Treffern:** Ist der Artist (oder
Kanal) manuell gemappt (`artist_genre.yaml`/`channel_genre.yaml`), greift
bereits `genre_processor`s eigener Schritt 1/2 (vor MusicBrainz) oder,
innerhalb von `determine_genre()` selbst, dessen Schritt 2/3 — **bevor**
die fehlerhafte Tag-String-Verarbeitung überhaupt erreicht wird
(empirisch verifiziert, 17.6-Test „bekannter Artist").

## 17.9 Bestehende Tests

| Testdatei | Deckt das in 17.4–17.8 beschriebene Verhalten ab? |
|---|---|
| `tests/test_musicbrainz_client.py::test_genre_determined_from_release_group_tags` | **Nein** — `genre_mapper` vollständig `MagicMock`, `determine_genre.return_value` ist ein fest verdrahteter Mock (`primary="Jazz"`). Prüft nur, dass der Client `determine_genre()` mit den erwarteten `raw_genre`-Kwargs **aufruft**, nicht was die echte Methode mit Multi-Tag-Input tatsächlich zurückgibt. |
| `tests/test_genre_processor.py::test_musicbrainz_genre_hit_populates_mb_ids` (vor Phase 3A) | **Teilweise** — nutzt echten `GenreMapper`, aber der `FakeMusicBrainzClient` liefert direkt `{"genre": "deutschrap", ...}` — ein **einzelnes, bereits kleingeschriebenes Wort**, kein realistischer Multi-Tag-String. Der `source == "normalized"`-Assert bewies zwar bereits den Doppel-Aufruf-Mechanismus (Phase 1, Abschnitt 9), aber **nicht** das Multi-Tag-spezifische Fehlverhalten aus 17.4. |
| `tests/test_genre_mapper_advanced.py` | Testet `GenreMapper` isoliert, aber (verifiziert per Durchsicht) ohne einen Fall, der `determine_genre()` mit einem kommagetrennten Multi-Tag-String aufruft. |

**Fazit:** Vor Phase 3A existierte **kein** Test im gesamten Repository,
der das in 17.4 beschriebene Multi-Tag-Verhalten der echten
`GenreMapper.determine_genre()`-Implementierung nachweist — exakt die in
Phase 1 (Abschnitt 9, Lücke 1) benannte fehlende Vergleichsbasis.

## 17.10 Neu ergänzte Characterization-Tests

In `tests/test_genre_processor.py`, neue Klasse
`TestMusicBrainzDoubleDetermineGenreCharacterization` (4 Tests, nutzt den
echten `GenreMapper` über die bestehende `genre_processor`-Fixture, faked
nur den netzwerkgebundenen `MusicBrainzClient` via `FakeMusicBrainzClient`,
Regel 7):

1. `test_multi_tag_client_value_is_the_entire_joined_tag_string` — belegt
   17.4: bei drei Tags ist der berechnete Client-Genre-Wert der komplette,
   title-gecaste Tag-String, kein Einzelgenre.
2. `test_second_call_reproduces_the_same_value_unchanged` — belegt 17.5:
   der zweite `determine_genre()`-Aufruf über die volle
   `determine_genre_with_fallbacks()`-Pipeline reproduziert denselben
   Wert unverändert, `source == "normalized"`, `raw_tags` bleiben als
   Metadatum erhalten, `mb_ids` unbeeinflusst.
3. `test_single_tag_is_not_affected` — Gegenprobe: ein einzelnes Tag wird
   korrekt zu einem sauberen Einzelgenre.
4. `test_known_artist_shields_against_the_multi_tag_value` — Gegenprobe:
   ein Artist mit manuellem Mapping-Eintrag erhält sein Genre bereits vor
   MusicBrainz, der fehlerhafte Multi-Tag-Wert wirkt sich nicht aus.

Keine bestehenden Tests wurden umgeschrieben. Ergebnis:
`pytest tests/test_genre_processor.py -q` → **27 passed** (23 vorher + 4
neu). Keine Produktionslogik geändert (siehe Diff-Audit, Abschnitt 17.14).

## 17.11 Bestätigte/widerlegte Hypothese

**Arbeitshypothese:** „MusicBrainz `determine_genre()` wird zweimal
aufgerufen, wobei der zweite Aufruf auf bereits verdichteten Daten
erfolgt."

**Ergebnis: B) präzisiert.**

- Der **Mechanismus** (zwei Aufrufe, zweiter auf dem Ergebnis des ersten)
  ist **bestätigt** — exakt wie in Phase 1 beschrieben.
- Die **implizite Schlussfolgerung**, die naheläge (aber von Phase 1
  bewusst *nicht* behauptet wurde) — „der erste Aufruf ist der
  wichtige/korrekte, der zweite ist der redundante/tote" — ist
  **widerlegt**. Es ist **nicht** wie beim Last.fm-Fall (Phase 2), wo der
  Client-Aufruf der überflüssige war und der Processor-Aufruf
  (`prioritize_genres()`) die tatsächlich korrekte, funktionierende
  Logik enthielt.
- Stattdessen: **Beide Aufrufe nutzen dieselbe, für Multi-Tag-Eingaben
  strukturell ungeeignete Methode.** Der Fehler (Informationsverlust,
  17.8) entsteht bereits beim **ersten** Aufruf (im Client). Der zweite
  Aufruf ist zwar im beobachteten Verhalten redundant (idempotent,
  ändert nichts mehr), aber **nicht**, weil er „tot" wäre wie beim
  Last.fm-Fall, sondern weil er auf einer bereits kaputten Eingabe
  operiert, die er nicht reparieren kann. Ein einfaches „zweiten Aufruf
  entfernen" (analog zur Last.fm-Bereinigung in Phase 2) würde den
  eigentlichen Fehler **nicht beheben** — er sitzt im ersten Aufruf bzw.
  strukturell in der Art, wie der Client seine Tags an `determine_genre()`
  übergibt.

## 17.12 Architekturvarianten (nur bewertet, nicht umgesetzt)

**Variante A — Client liefert nur rohe/API-spezifische Genredaten;
`genre_processor.py` besitzt die alleinige Fachlogik.**
Tatsächliches Verhalten nach Umsetzung: `musicbrainz_client.py` würde nur
noch `mb_tags` (rohe Liste) zurückgeben, kein vorberechnetes `"genre"`
mehr. `genre_processor.py` müsste eine **neue**, MB-spezifische
Priorisierung einführen (aktuell existiert dafür kein Äquivalent zu
`prioritize_genres()` im MB-Pfad — dieser müsste entweder `prioritize_genres()`
wiederverwenden oder eine eigene Variante erhalten).
Dependency-Richtung: unverändert (`metadata → clients`).
Informationsverlust: behoben (Multi-Tag-Priorisierung würde die
Original-Tags korrekt auswerten).
Verhaltensrisiko: **mittel–hoch** — neues Verhalten für alle
MB-Multi-Tag-Fälle, die bisher (fehlerhaft) den Title-Case-Blob
lieferten; jeder bestehende Consumer, der zufällig mit dem aktuellen
(kaputten) String-Format „lebt", könnte betroffen sein (kein bekannter
Fall gefunden, aber nicht ausgeschlossen).
Testaufwand: hoch (neue Priorisierungslogik + Umstellung).
Änderungsumfang: `musicbrainz_client.py`, `genre_processor.py`.
Wartbarkeit/Erweiterbarkeit: gut — vereinheitlicht MB- und Last.fm-Pfad
konzeptionell.
Komplexität: mittel.

**Variante B — Client liefert ein bewusst normalisiertes
Genre-Ergebnis, `genre_processor.py` übernimmt es als fachliche
Vorstufe.**
Tatsächliches Verhalten: entspricht in etwa dem **heutigen** Design-
Intent (Client normalisiert vor), scheitert aber aktuell an der
fehlenden Multi-Tag-Fähigkeit von `determine_genre()`. Eine korrekte
Umsetzung würde bedeuten: der Client müsste selbst schon
`prioritize_genres()`-artige Logik auf seine eigenen Tags anwenden,
bevor er `determine_genre()` aufruft (oder ganz auf `determine_genre()`
verzichten und direkt priorisieren). Der zweite Aufruf in
`genre_processor.py` würde dann tatsächlich redundant und könnte
entfernt werden (dann näher an der Last.fm-Lösung aus Phase 2).
Dependency-Richtung: unverändert.
Informationsverlust: behoben.
Verhaltensrisiko: **mittel** — ähnlich zu Variante A, aber die Änderung
konzentriert sich auf den Client statt auf `genre_processor.py`.
Testaufwand: hoch (Client bekäme neue Verantwortung).
Änderungsumfang: hauptsächlich `musicbrainz_client.py`.
Wartbarkeit/Erweiterbarkeit: mittel — verlagert Fachlogik in einen
Adapter, tendenziell im Widerspruch zu CLAUDE.md §17 („externe APIs
nicht mit Core-Logik vermischen") und der in POST-DUPLICATEENTRY-Audit
Regel A formulierten Erwartung an `services/clients/`.
Komplexität: mittel.

**Variante C — aktueller zweistufiger Prozess ist fachlich
gerechtfertigt und bleibt bestehen.**
Nach dieser Characterization **nicht mehr haltbar als „bewusst
gerechtfertigt"** — der empirische Befund (17.4–17.8) zeigt einen
nachweisbaren, unbeabsichtigten Informationsverlust für den
Mehrheitsfall (Multi-Tag-MusicBrainz-Treffer bei unbekannten
Artists/Kanälen), keinen fachlich begründeten Zwei-Stufen-Entwurf. Diese
Variante würde bedeuten, den Status quo trotz nachgewiesenem Fehler
bewusst zu akzeptieren — möglich als Entscheidung, aber nicht durch die
Analyse gestützt.

## 17.13 Risikobewertung

- **Was ändert sich bei Entfernung des ersten Aufrufs (im Client) ohne
  Ersatz?** `mb_data["genre"]` wäre immer `"unknown"` (analog zur
  Last.fm-Bereinigung) — `genre_processor.py`s `has_genre`-Check würde
  dann **immer** `False` sein, wodurch **jeder** MusicBrainz-Treffer nur
  noch den `"musicbrainz_ids_only"`-Sentinel liefert (kein Genre mehr aus
  MusicBrainz, nur noch IDs) — der Fallback auf Last.fm (Schritt 4 der
  Gesamt-Pipeline) würde dann **öfter** greifen als heute. Das wäre eine
  **echte Verhaltensänderung**, keine risikofreie Bereinigung wie bei
  Last.fm — dort blieb der Last.fm-**Fallback selbst** unverändert
  funktionsfähig (`prioritize_genres()` lief immer schon unabhängig vom
  Client-Genre); hier gibt es kein äquivalentes „unabhängig laufendes"
  Verfahren im MB-Pfad.
- **Was ändert sich bei einer Verschiebung der Logik (Variante A/B)?**
  Siehe 17.12 — abhängig von der genauen Umsetzung könnten sich
  `primary`/`secondary` für **alle** bisher Multi-Tag-betroffenen Tracks
  ändern (vermutlich zum Besseren, aber das ist eine bewusste
  Verhaltensänderung, kein reiner Strukturumzug).
- **Welche impliziten Fallbacks existieren?** Der
  `"musicbrainz_ids_only"`-Sentinel (Zeile 592–600 in
  `genre_processor.py`) — sorgt dafür, dass `mb_ids` auch ohne Genre-
  Treffer erhalten bleiben. Bleibt in allen Varianten unverändert
  relevant.
- **Welche Tests würden eine Regression erkennen?** Die vier neuen Tests
  aus 17.10 — sie schreiben exakt die Fälle fest, die sich bei einer
  Variante-A/B-Umsetzung ändern würden (insbesondere Test 1 und 2 würden
  bei einer echten Bereinigung bewusst fehlschlagen/angepasst werden
  müssen — das ist beabsichtigt, sie markieren die Ist-Grenze).
- **Welche Tests fehlen weiterhin?** Ein Test, der den kompletten Pfad
  **inklusive** der echten `MusicBrainzClient`-Klasse (mit gemocktem
  `musicbrainzngs`, nicht nur `FakeMusicBrainzClient`) end-to-end gegen
  eine realistische API-Response prüft — aktuell wird `_build_metadata()`
  selbst nirgends mit einem echten, ungemockten `GenreMapper` getestet
  (siehe 17.9, `test_musicbrainz_client.py` mockt `genre_mapper`
  komplett). Das wäre erst für eine tatsächliche Umsetzung (Phase 3B)
  nötig, nicht für diese Characterization.
- **Unterschied API-Mapping vs. echte Fachlogik?** Klar identifizierbar:
  `mb_tags`-Extraktion (Zeile 414) = reines API-Mapping. Der
  `determine_genre()`-Aufruf selbst (Zeile 428–440) = versuchte
  Fachlogik-Anwendung, aber strukturell fehlerhaft für den vorliegenden
  Datentyp (Liste statt Einzelwert).
- **`source == "normalized"` und `mb_ids` nachvollzogen:** `source` zeigt
  in allen Multi-Tag-Fällen `"normalized"` (nie `"hierarchy"`, nie
  `"rule"` — siehe 17.4) — ein **beobachtbares Signal**, dass in der
  Produktion echte MusicBrainz-Multi-Tag-Treffer für unbekannte
  Artists/Kanäle IMMER über diesen fehlerhaften Pfad laufen, nie über
  eine Hierarchie-Auflösung. `mb_ids` sind vom Genre-Ergebnis komplett
  entkoppelt (eigener Dict-Aufbau in `_build_metadata()`, Zeile 416–423,
  unabhängig von `genre_value`) — **kein** Risiko, dass eine künftige
  Genre-Korrektur die ID-Weitergabe beeinträchtigt.

## 17.14 Diff-/Scope-Audit dieser Phase

```text
git diff --stat
 tests/test_genre_processor.py | 132 +++++++++++++++++++++++++++++
 1 file changed, 132 insertions(+)
```

**Ausschließlich** `tests/test_genre_processor.py` geändert. Keine
Änderung an `services/clients/musicbrainz_client.py`,
`services/metadata/genre_processor.py`, `utils/genre_map.py`, Genre-YAML-
Dateien, `services/clients/lastfm_client.py` (Phase 2 bleibt unangetastet),
README.md, CLAUDE.md oder `docs/MusicBot_ENGINEERING_BASELINE.md` — kein
konkreter, durch diese Phase verursachter Dokumentationswiderspruch
gefunden.

## 17.15 Empfehlung für Phase 3B

**Nicht sofort umsetzen.** Diese Characterization zeigt einen echten,
nutzerseitig sichtbaren Befund (potenziell fehlerhafte Genre-Tags in
Musikdateien für MusicBrainz-Treffer ohne bekannten Artist/Kanal) — aber
im Gegensatz zu Phase 2 (Last.fm) ist hier **keine** risikofreie,
rein-strukturelle Bereinigung möglich: Der erste Aufruf kann nicht
ersatzlos entfernt werden, ohne dass entweder (a) MusicBrainz als
Genre-Quelle faktisch ausfällt (mehr Last.fm-Fallback-Nutzung, echte
Verhaltensänderung) oder (b) eine neue Multi-Tag-Priorisierung für den
MB-Pfad eingeführt wird (Variante A/B, jeweils mit eigenem Entwurfs- und
Testaufwand).

**Empfohlener nächster Schritt (Phase 3B, falls freigegeben):** Variante
A — MusicBrainz-Client liefert nur rohe Tags, `genre_processor.py`
erhält die alleinige Fachlogik, unter Wiederverwendung von
`prioritize_genres()` (bereits vorhanden, bewährt für Last.fm) statt
einer neuen Implementierung. Vor der Umsetzung: End-to-End-
Characterization-Test mit echter (gemockter API, aber ungemockter
`GenreMapper`) `MusicBrainzClient`-Instanz, um die aktuelle
Title-Case-Blob-Ausgabe für einen realistischen API-Response noch einmal
auf Client-Ebene direkt (nicht nur über `FakeMusicBrainzClient`)
festzuschreiben, bevor sie geändert wird.

## 17.16 Entscheidungsgate

> **ARCH-012 Phase 3A — MusicBrainz Genre Characterization abgeschlossen.**
> **Keine Produktions-Codeänderung durchgeführt.**
> **Characterization-/Testbasis dokumentiert.**
> **Entscheidungsgate erreicht.**
>
> **Kann der erste `determine_genre()`-Aufruf im MusicBrainz-Client sicher
> entfallen, ohne das aktuelle Verhalten zu verändern?** **Nein** — anders
> als beim Last.fm-Fall (Phase 2) ist der erste Aufruf nicht redundant zu
> einer bereits existierenden, unabhängig funktionierenden Priorisierung.
> Sein ersatzloses Entfernen würde MusicBrainz als Genre-Quelle für
> unbekannte Artists/Kanäle faktisch abschalten (mehr Last.fm-Fallback-
> Nutzung) — eine echte Verhaltensänderung, kein risikofreier
> Struktur-Umzug.
>
> **Welche fachliche Verantwortung muss wo verbleiben?** Die
> Multi-Tag-Priorisierung (aktuell nur für Last.fm über
> `prioritize_genres()` vorhanden) muss für den MusicBrainz-Pfad
> äquivalent bereitgestellt werden — entweder durch Wiederverwendung von
> `prioritize_genres()` in `genre_processor.py` (Variante A, empfohlen)
> oder durch eine neue, MB-spezifische Client-seitige Priorisierung
> (Variante B). Die reine Entfernung eines der beiden `determine_genre()`-
> Aufrufe ohne diesen Ersatz ist **nicht** empfohlen.
>
> **Empfehlung für Phase 3B: Variante A (Client liefert nur rohe Tags,
> `genre_processor.py` priorisiert über die bestehende
> `prioritize_genres()`), mit vorherigem End-to-End-Characterization-Test
> auf Client-Ebene vor jeder Codeänderung.** Umsetzung erst nach
> ausdrücklicher Freigabe.
