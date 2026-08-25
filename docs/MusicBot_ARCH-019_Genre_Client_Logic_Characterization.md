# MusicBot ARCH-019 — Genre Client Logic Characterization

**Status:** Phase 1 (Characterization) abgeschlossen. Keine
Produktionsänderung. Keine YAML-Änderung. Keine Vereinheitlichung.
Wartet auf ausdrückliche Freigabe für eine mögliche Phase 2.

---

## 1. Ausgangslage

Der POST-DUPLICATEENTRY-Audit (Abschnitt 5.2) hatte als P1-Befund
("architektonisch der klarste verbleibende Befund") notiert:
*"`lastfm_client.py` und `musicbrainz_client.py` enthalten fachliche
Genre-Bestimmungslogik (`GenreMapper.determine_genre()`-Aufrufe direkt
im Client) statt reiner API-Kommunikation"* — konkret mit Zeilenangaben
(`musicbrainz_client.py`, Zeile 96, 430, 436).

**Zentrales Ergebnis dieser Phase:** Diese Behauptung ist für den
**aktuellen Code nicht zutreffend**. Weder `musicbrainz_client.py` noch
`lastfm_client.py` rufen `GenreMapper.determine_genre()` oder
`get_genre_mapper()` an irgendeiner Stelle auf — beide Dateien
enthalten diese Symbole **ausschließlich in Kommentaren**, die
beschreiben, dass genau diese Logik bereits durch ARCH-012 (Phase 2 für
Last.fm, Phase 3B für MusicBrainz) entfernt wurde. Der POST-
DUPLICATEENTRY-Befund war zum Zeitpunkt seiner Erstellung für den
damaligen Code entweder bereits veraltet oder fehlerhaft — dies wird
hier nicht weiter untersucht (außerhalb des ARCH-019-Scopes), sondern
nur als Korrektur der Ausgangsannahme festgehalten.

---

## 2. MusicBrainz-Analyse (`services/clients/musicbrainz_client.py`)

| Funktion | Input | Output | API-Quelle | Transformation | Fachliche Entscheidung |
|---|---|---|---|---|---|
| `parse_search_terms()` | `title, artist: str` | optimierte `(title, artist)` | — | YouTube-Titel-Reparsing (`ArtistNormalizer.parse_youtube_title`), Artist-Normalisierung | **Artist-Namens-Normalisierung** (nicht Genre) |
| `fetch_metadata()` | `title, artist: str` | Dict (siehe unten) | `musicbrainzngs.search_recordings`/`search_releases`/`get_recording_by_id`/`get_release_by_id` | 3-stufige Fallback-Suche (Recording+Artist → Recording-only → Release) | **Recording-Auswahl** (welcher Treffer ist der richtige Track), nicht Genre |
| `_get_best_match()` | Kandidatenliste, `title, artist` | bester Treffer oder `None` | — | Ähnlichkeits-Scoring (`SequenceMatcher`, gewichtet 0.7 Titel/0.3 Artist, Normalisierungs-Bonus) | **Recording-Scoring**, keine Genre-Bezug |
| `_build_metadata()` | bester Treffer | vollständiges Metadaten-Dict | `get_recording_by_id` (Details) | extrahiert IDs, Tags, Album, Jahr, Track-Nummer | keine — reine Extraktion |

**Genre-bezogener Teil, exakt:**

```python
mb_tags = [t["name"] for t in release_group.get("tags", [])]  # rohe Tag-Namen, keine Verarbeitung
...
genre_value = "unknown"  # hartkodierter Platzhalter, ARCH-012 Phase 3B
...
return {..., "tags": mb_tags, "genre": genre_value, ...}
```

**Keine** Normalisierung, Aliasing, Filterung, Priorisierung oder
sonstige fachliche Genre-Entscheidung. `"genre"` ist ein reiner
Kompatibilitäts-Platzhalter (Rückgabestruktur unverändert, Wert immer
`"unknown"`).

**Nicht Genre-bezogene, aber echte fachliche Logik im Client:**
Artist-Namens-Normalisierung (`parse_search_terms`,
`_get_best_match`) und Recording-Auswahl/-Scoring
(`_get_best_match`) — beide gehören fachlich zur Aufgabe "den
richtigen Track bei MusicBrainz finden", nicht zur Aufgabe "das Genre
bestimmen". Release-Group-ID-Fallback-Abfrage
(`_fetch_release_group_id`) und Track-Nummer-Extraktion
(`_extract_track_number`, mit dokumentiertem Bugfix BUG-001) sind reine
API-/Datenextraktions-Logik.

---

## 3. Last.fm-Analyse (`services/clients/lastfm_client.py`)

| Funktion | Input | Output | API-Quelle | Transformation | Fachliche Entscheidung |
|---|---|---|---|---|---|
| `_get_lastfm_data()` | `title, artist: str` | `(track_info, tag_names)` | `pylast` (`get_artist`, `get_top_tags`, `get_track`) | Artist-Tags + Track-Tags kombiniert, dedupliziert, lowercased (Artist-Tags haben Vorrang in der Reihenfolge) | keine Genre-Entscheidung, nur Tag-Sammlung |
| `fetch_metadata()` | `title, artist, include_genre, mbid` | Dict (siehe unten) | — | Timeout-Wrapper, Fehlerbehandlung | keine |

**Genre-bezogener Teil, exakt:**

```python
return {
    "tags": tag_names,   # rohe, kombinierte Artist-/Track-Tags
    ...
    "genre": "unknown",  # hartkodierter Platzhalter, ARCH-012 Phase 2
}
```

Der Parameter `include_genre` bleibt Teil der Signatur (Rückwärts-
kompatibilität), **wird aber laut explizitem Codekommentar nicht mehr
ausgewertet** — ein Aufruf mit `include_genre=False` liefert dasselbe
Ergebnis wie `include_genre=True` (durch bestehenden Test
`test_include_genre_flag_no_longer_affects_result` bereits belegt).

`lastfm_client.py` enthält **keine** projektinternen Imports außer
`config`/`logger` (AST-verifiziert) — insbesondere kein
`utils.genre_map`, kein `services.metadata`. Es existiert **keine**
sonstige fachliche Logik außer der Tag-Sammlung/-Deduplizierung selbst.

---

## 4. Zentrale Genre-Pipeline (Referenz, nicht neu bewertet)

`services/metadata/genre_processor.py::_fetch_genre_from_musicbrainz()`
und `::_fetch_genre_from_lastfm()` (Zeilen 580–720) konsumieren **beide
identisch**:

```python
mb_data = await mb_client.fetch_metadata(search_title, artist_name)
tags = mb_data.get("tags", []) or []
...
primary_genre, secondary_genres = self.prioritize_genres(tags, artist_name=artist_name)
```

```python
lfm_data = await lfm_client.fetch_metadata(search_title, artist_name, include_genre=True)
tags = lfm_data.get("tags", [])
...  # Fallback: raw_lfm_genre nur gespalten, falls tags leer UND Komma enthalten (Legacy-Fallback)
primary_genre, secondary_genres = self.prioritize_genres(tags, artist_name=artist_name)
```

**Der `"genre"`-Schlüssel beider Clients wird nie als Entscheidungsgrundlage
gelesen** — nur `lfm_data.get("genre", "")` im Last.fm-Pfad, und selbst
dort ausschließlich als Notfall-Tag-Quelle (Komma-Split), falls `tags`
leer ist — nicht als vorberechnetes Genre. `GenreMapper`/`prioritize_genres()`
(bereits durch ARCH-013–016 vollständig charakterisiert und stabilisiert,
115/115 kanonische Werte idempotent) bleibt die **alleinige** Instanz,
die eine Genre-Entscheidung trifft — identisch für beide Quellen.

---

## 5. Vergleichsmatrix

| Funktion/Logik | MusicBrainz Client | Last.fm Client | GenreProcessor | GenreMapper | fachlich identisch? |
|---|---|---|---|---|---|
| Rohe Tag-Extraktion aus API-Antwort | ✓ (`release_group.tags`) | ✓ (Artist+Track-Tags kombiniert) | — | — | nein — unterschiedliche Datenquellen/-formen, aber strukturell äquivalente Rolle ("liefere rohe Tags") |
| Genre-Normalisierung/Alias-Auflösung | ✗ | ✗ | ✓ (`prioritize_genres` → `normalize_genre_name`) | ✓ (`GENRE_NORMALIZATION`) | n/a — nur an einer Stelle vorhanden |
| Genre-Priorisierung (Multi-Tag) | ✗ | ✗ | ✓ (`prioritize_genres`) | — (liefert nur die Prioritäts-Map) | n/a — nur an einer Stelle vorhanden |
| Genre-Kanonisierung (Spezifitätsregel, Self-Alias) | ✗ | ✗ | ✓ (ARCH-014/015/016) | — | n/a — nur an einer Stelle vorhanden |
| Artist-Namens-Normalisierung | ✓ (`ArtistNormalizer`, für Suchoptimierung) | ✗ | — | — | n/a — clientspezifisch, dient der API-Suche, nicht der Genre-Entscheidung |
| Recording-/Track-Matching (welcher Treffer ist korrekt) | ✓ (`_get_best_match`) | ✗ (kein Matching nötig, `get_artist`/`get_track` sind Direktzugriffe) | — | — | n/a — MusicBrainz-spezifisches Problem (Volltextsuche mit mehreren Kandidaten), bei Last.fm strukturell nicht vorhanden |
| `"genre"`-Rückgabefeld | `"unknown"` (Platzhalter) | `"unknown"` (Platzhalter) | wird nie gelesen (MB) / nur Notfall-Fallback (LFM) | — | ja — beide identisch wirkungslos |

**Bewertung:** Keine gleiche Eingabe führt in Client und
GenreProcessor zu einer unabhängig getroffenen, potenziell
widersprüchlichen Genre-Entscheidung — es gibt in den Clients schlicht
**keine** Genre-Entscheidung mehr. Alias-/Normalisierungs-/
Priorisierungs-/Filterregeln existieren ausschließlich in
`GenreProcessor`/`GenreMapper`. Die einzige "Duplikation" ist rein
strukturell und wirkungslos: beide Clients liefern einen ungenutzten
`"genre": "unknown"`-Platzhalter-Schlüssel aus Gründen der
Rückwärtskompatibilität der Rückgabestruktur.

---

## 6. Datenfluss

```text
MusicBrainz API                          Last.fm API
    ↓                                        ↓
musicbrainzngs.search_recordings/...    pylast get_artist/get_track
    ↓                                        ↓
MusicBrainzClient.fetch_metadata()      LastFMClient.fetch_metadata()
    ↓ {tags: [...], genre: "unknown",       ↓ {tags: [...], genre: "unknown",
    ↓  recording_id, artist_id, ...}        ↓  listeners, playcount, album, wiki}
    ↓                                        ↓
GenreProcessor._fetch_genre_from_*()  (liest AUSSCHLIESSLICH "tags", ignoriert "genre")
    ↓
self.prioritize_genres(tags, artist_name)  ← EINZIGE Genre-Entscheidung, für beide Quellen identisch
    ↓
GenreResult (primary, secondary, source="musicbrainz_prioritized"/"lastfm_prioritized", raw_tags, mb_ids)
    ↓
MetadataResult / track_metadata
```

Kein Client führt einen Teil dieser Pipeline selbst aus — beide enden
strikt vor `prioritize_genres()`.

---

## 7. Aufrufer/Verbraucher

Repo-weit ermittelt:

| Symbol | Aufrufer | Rolle |
|---|---|---|
| `MusicBrainzClient` | `services/metadata/genre_processor.py` (Genre-Pfad), `services/metadata/album_processor.py` (Album/Jahr-Pfad, DI-Frage bereits als P3 bekannt, POST-DUPLICATEENTRY 5.4, hier nicht erneut bewertet), `services/metadata/enhanced_metadata_processor.py` (Facade-Instanziierung) | produktiv |
| `LastFMClient` | `services/metadata/genre_processor.py` (Genre-Pfad), `services/metadata/enhanced_metadata_processor.py` (Facade-Instanziierung) | produktiv |
| Tests | `tests/test_musicbrainz_client.py` (25 Tests), `tests/test_lastfm_client.py` (12 Tests), `tests/test_genre_processor.py` | Charakterisierung/Regression |

Client-`"genre"`-Rückgabewerte werden **nirgends** direkt
weiterverarbeitet (repo-weit kein `.get("genre")`-Zugriff auf
Client-Ergebnisse außerhalb des dokumentierten Last.fm-Notfall-Fallbacks
in Abschnitt 4). Ein Entfernen des `"genre"`-Schlüssels aus beiden
Clients würde **keine reale Verhaltensänderung** verursachen — mit
einer Ausnahme: der Last.fm-Notfall-Fallback (`raw_lfm_genre.split(",")`)
liest `lfm_data.get("genre", "")`, dieser Pfad würde dann leer bleiben.
Da `"genre"` aber immer `"unknown"` ist (kein Komma enthalten), wird
dieser Fallback-Zweig unter der aktuellen Client-Implementierung **nie
ausgelöst** — er ist bereits heute toter Code innerhalb von
`genre_processor.py` (nicht Teil des ARCH-019-Scopes, nur als
Randbeobachtung dokumentiert).

---

## 8. Verhaltensexperimente

Keine neuen Characterization-Tests erforderlich — die exakt relevanten
Verhaltensfragen sind bereits durch bestehende, aktuelle Tests
belastbar beantwortet:

| Frage | Beantwortet durch (bestehender Test) | Ergebnis |
|---|---|---|
| Liefert MusicBrainz-Client rohe Tags ohne Genre-Berechnung? | `test_musicbrainz_client.py::test_release_group_tags_are_returned_raw_without_genre_determination` | bestätigt |
| Bleibt `"genre"` bei MusicBrainz immer `"unknown"`, auch ohne Tags? | `test_musicbrainz_client.py::test_no_tags_genre_stays_unknown_placeholder` | bestätigt |
| Bleibt `"genre"` bei Last.fm immer `"unknown"`, auch mit Tags? | `test_lastfm_client.py::test_tags_present_genre_field_stays_unknown_placeholder` | bestätigt |
| Hat `include_genre=False` einen Effekt? | `test_lastfm_client.py::test_include_genre_flag_no_longer_affects_result` | bestätigt: kein Effekt |
| Bleibt `"genre"` bei Last.fm ohne Tags `"unknown"`? | `test_lastfm_client.py::test_no_tags_genre_stays_unknown` | bestätigt |

Alle 5 Tests wurden real ausgeführt (Abschnitt „Regression") und sind
grün. Ergänzend belegt die vollständige ARCH-013–016-Testsuite (115/115
kanonische Werte idempotent), dass `prioritize_genres()` unabhängig von
der Tag-Quelle (MusicBrainz vs. Last.fm) identisch funktioniert — Single-
Tag, Multi-Tag, Alias, Mixed-Case, dekorierte Tags, generisch+spezifisch,
unbekannte/leere Tags sind dort bereits über die 5 Genre-Testdateien
(`test_genre_*.py`) systematisch abgedeckt. Eine Wiederholung dieser
Experimente speziell für Client-Daten wäre redundant, da beide Clients
nachweislich (Abschnitt 2/3) keine eigene Tag-Transformation vor der
Übergabe an `prioritize_genres()` vornehmen, die sich von der bereits
getesteten Eingabeform unterscheiden würde.

**Ergebnis der Frage "redundant oder andere Aufgabe?":** Die
verbleibende Client-Logik ist **fachlich notwendige API-/Matching-Logik**
(Artist-Normalisierung für die Suche, Recording-Auswahl bei MusicBrainz,
Tag-Sammlung bei beiden) — **keine** redundante Genre-Fachentscheidung.

---

## 9. Dependency-/Layer-Audit

AST-basiert (Import-Analyse beider Dateien):

```text
services/clients/musicbrainz_client.py:
    → asyncio, musicbrainzngs, cachetools, difflib, pathlib, typing (stdlib/3rd-party)
    → config.Config, async_timeout, logger.get_module_logger
    → utils.artist_map.get_artist_normalizer / ArtistNormalizer, ArtistConfig
    → services/metadata: 0 Treffer
    → handlers/: 0 Treffer

services/clients/lastfm_client.py:
    → asyncio, pylast, typing, logging (stdlib/3rd-party)
    → config.Config, async_timeout, logger.*
    → services/metadata: 0 Treffer
    → utils/: 0 Treffer
    → handlers/: 0 Treffer
```

**`services/clients → services/metadata`: 0 Treffer** (bestätigt keine
verbotene Aufwärtsabhängigkeit — Clients importieren nicht die
Fachlogik, die sie konsumiert). **`services/clients → handlers`: 0
Treffer.** **`services → handlers`: weiterhin 0** (repo-weit,
unverändert seit allen vorherigen Audits dieser Session). Keine
Reverse-Edge, kein Zyklus, keine versteckte Gegenabhängigkeit gefunden.

Der Client darf die zentrale Genre-Fachlogik nicht importieren (würde
`services/clients → services/metadata` erzeugen) — **er tut es auch
nicht**, weder für Genre noch für sonstige Zwecke.

---

## 10. Architekturvarianten

Da die Characterization ergab, dass **keine echte Duplikation mehr
vorliegt**, werden die Varianten entsprechend eingeordnet:

### Variante A — Clients liefern ausschließlich rohe Genre-Tags

**Bereits der aktuelle Zustand** für den Genre-Anteil. Einzige
Differenz zum Idealbild: der ungenutzte `"genre": "unknown"`-
Platzhalter-Schlüssel könnte entfernt werden.

- Architekturgewinn: gering (kosmetisch — ein totes Dict-Feld).
- Verhaltensrisiko: sehr gering (ein Consumer-Pfad in
  `genre_processor.py`, der Last.fm-Notfall-Fallback, liest ihn — aber
  nachweislich nie mit einem Nicht-"unknown"-Wert, s. Abschnitt 7).
- Scope: 2 Dateien (Clients) + ggf. `genre_processor.py`
  (Fallback-Zeile), falls der Schlüssel ganz entfällt.

### Variante B — Client-spezifische Transformation bleibt, zentrale Fachentscheidung ausschließlich im GenreProcessor

**Bereits der aktuelle Zustand**, vollständig. Keine Änderung
notwendig.

### Variante C — Gemeinsame Genre-Hilfslogik innerhalb `services/metadata/`

Nicht durch den Code nahegelegt — es gibt keine gemeinsame,
duplizierte Hilfslogik zwischen den Clients, die zentralisiert werden
müsste (die einzige gemeinsame Struktur ist der bereits zentrale
`prioritize_genres()`-Aufruf).

### Variante D — Bestehende Struktur bewusst beibehalten

- **Empfohlen.** Der Code entspricht bereits der in ARCH-012
  beschlossenen Zielarchitektur (`MusicBrainzClient`/`LastFMClient` =
  externe Adapter, `GenreProcessor` = Fachentscheidung). Keine
  Änderung erforderlich, um den ursprünglich vermuteten P1-Befund zu
  beheben — er besteht in der behaupteten Form nicht mehr.

---

## 11. Risiken

- **Kein Verhaltensrisiko** bei Nichtstun (Variante D) — der Zustand
  ist bereits korrekt.
- Bei einer rein kosmetischen Bereinigung des `"genre"`-Platzhalters
  (Teil von Variante A): minimales Risiko, da der einzige Leser
  (Last.fm-Notfall-Fallback in `genre_processor.py`) nachweislich nie
  mit einem verwertbaren Wert konfrontiert wird — dennoch außerhalb des
  ARCH-019-Scopes (`genre_processor.py` ist laut Aufgabenstellung
  ausdrücklich nicht zu ändern).
- Kein Datenverlust-Risiko identifiziert.

---

## 12. Empfehlung

**Keine Umsetzungsphase notwendig.** ARCH-012 (Phase 2/3B) hat die
ursprüngliche Genre-Logik-Duplikation bereits vollständig behoben. Der
im POST-DUPLICATEENTRY-Audit als P1 geführte Befund ist für den
aktuellen Code **nicht bestätigt** und sollte in künftigen Audits nicht
mehr als offener Punkt geführt werden.

Falls dennoch ein minimaler Aufräumschritt gewünscht ist: Entfernung
des ungenutzten `"genre": "unknown"`-Platzhalter-Rückgabefelds aus
beiden Clients (Variante A, Rest) — **kein architektonischer Gewinn,
rein kosmetisch**, nicht als eigene ARCH-Phase gerechtfertigt, allenfalls
als Teil einer ohnehin stattfindenden kleineren Aufräumarbeit.

Dies ist eine **Empfehlung, keine Entscheidung**.

---

## 13. Entscheidungsgate

**ARCH-019 Phase 1 — Characterization abgeschlossen.**
**Keine Produktionsänderung durchgeführt.**
**Keine YAML-Änderung durchgeführt.**
**Keine Vereinheitlichung der Clients durchgeführt.**
**ARCH-012 nicht rückgängig gemacht — als bestehende Entscheidung
bestätigt und durch aktuellen Code verifiziert.**
**STOPP.**
**Warte auf ausdrückliche Freigabe für eine mögliche Phase 2** (falls
überhaupt gewünscht — siehe Abschnitt 12, kein substanzieller Bedarf
identifiziert).
