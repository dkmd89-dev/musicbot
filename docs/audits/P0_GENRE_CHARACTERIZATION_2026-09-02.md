# P0-C: Genre fachlich charakterisieren (`services/metadata/genre_processor.py`)

**Datum:** 2026-09-02
**Phase:** P0-C der laufenden P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Reihe
(Branch `audit/p0-metadata-duplicate-detection`).
**Scope:** `services/metadata/genre_processor.py` (`GenreProcessor`), im
Zusammenspiel mit `utils/genre_map.py` (`GenreMapper`).

## Ausgangslage

`genre_processor.py` ist bereits einer der am gründlichsten durch frühere
ARCH-Phasen (ARCH-012 Genre-Logik, ARCH-013 Genre-Alias-Entscheidung,
ARCH-014 Genre-Spezifitäts-Charakterisierung) untersuchten Module — die
Fallback-Kaskade selbst, `prioritize_genres()` und `normalize_genre_name()`
(inkl. Wortgrenzen-Matching und Längster-Alias-gewinnt-Tie-Breaking bei
Kollisionen) waren bereits umfassend mit Characterization-Tests
(`tests/test_genre_processor.py`, `tests/test_genre_alias_characterization.py`)
abgesichert.

Statt diese bereits gute Abdeckung zu duplizieren, wurde gezielt nach
**echten Lücken** gesucht: Codepfade, die zwar in Kommentaren/Docstrings
behauptetes Verhalten beschreiben, aber durch keinen bestehenden Test
end-to-end verifiziert waren.

## Gefundene Lücken (alle live gegen die echte Produktionsklasse
`GenreProcessor` + echten `GenreMapper` gegen die realen `mapping/`-Dateien
verifiziert, bevor ein Test geschrieben wurde)

### 1. Schritt 2 der Pipeline (lokales/Channel-Genre) — nie End-to-End getestet

`determine_genre_with_fallbacks()` hat fünf Schritte (siehe Modul-Docstring).
Schritt 1 (manuell) und Schritte 3–5 (MusicBrainz/Last.fm/Feature-Inferenz)
waren bereits durch `TestDetermineGenreWithFallbacksManualMapping` und
`TestDetermineGenreWithFallbacksExternalSteps` abgedeckt. **Schritt 2**
(`GenreMapper.determine_genre()` — Channel-Mapping/Fuzzy/Hierarchie) wurde
nur indirekt über `GenreMapper`-eigene Tests geprüft, nie durch die
komplette `determine_genre_with_fallbacks()`-Pipeline selbst.

Neuer Test: `TestDetermineGenreWithFallbacksLocalChannelPath` — ein Artist
ohne manuellen Mapping-Eintrag, Channel `kontor.tv` (exakter Treffer in
`channel_genre.yaml`) → Ergebnis `primary=Electronic, source=channel_exact`,
ohne dass externe Services aufgerufen werden.

### 2. mb_ids-Anhängung an ein bereits bekanntes (manuelles) Genre — behauptet, aber nicht geprüft

Der Code-Kommentar bei Schritt 3a (`# 3a. Bekanntes Genre + MB-IDs → fertig`)
behauptet, dass MusicBrainz-IDs auch dann angehängt werden, wenn das Genre
bereits aus Schritt 1 (manuell) feststeht. Der bestehende Test
`test_known_artist_shields_against_musicbrainz_tags` prüft zwar, dass die
MusicBrainz-**Tags** das manuelle Genre nicht überschreiben, prüft aber
`result.mb_ids` an keiner Stelle.

Live-Verifikation bestätigte die Behauptung: ein bekannter Artist mit
MusicBrainz-Antwort (`tags=["ruhrpott rap"], recording_id="abc-123",
release_id="rel-456"`) liefert `source=artist_exact_manual`,
`primary`/`secondary` unverändert aus dem manuellen Mapping, **und**
`mb_ids={"recording_id": "abc-123", "release_id": "rel-456", ...}` korrekt
angehängt.

Neuer Test: `TestDetermineGenreWithFallbacksMbIdsAttachToKnownResult::
test_manual_result_still_receives_mb_ids`.

### 3. Feature-Artist-Inferenz: Stimmengleichheits-Tie-Breaking (echter, nicht-trivialer Fund)

`_infer_genre_from_feat_artists()` nutzt `collections.Counter(feat_genres).
most_common(1)`. Der bestehende Test deckte nur den Ein-Feature-Artist-Fall
ab (kein Gleichstand möglich).

Bei mehreren Feature-Artists mit **unterschiedlichen** bekannten Genres und
gleicher Stimmenzahl (z. B. genau ein Treffer je Genre) entscheidet
`Counter.most_common()` **nicht** alphabetisch und **nicht** nach
Hierarchie-Tiefe, sondern nach der **Reihenfolge des ersten Auftretens** in
der übergebenen `feat_artists`-Liste (Implementierungsdetail von Python
`Counter`). Live verifiziert mit `"Bausa"` (Hip Hop) und `"Aurora"`
(Alternative Pop):

| Eingabe-Reihenfolge | Ergebnis |
|---|---|
| `["Bausa", "Aurora"]` | `Hip Hop` |
| `["Aurora", "Bausa"]` | `Alternative Pop` |

Da `feat_artists` aus der Reihenfolge stammt, in der Feature-Artists im
Titel/Metadaten-String erscheinen (nicht aus einer bewussten Priorisierung),
ist dieses Verhalten funktional plausibel (der zuerst genannte Feature-
Artist gilt tendenziell als "wichtiger"), aber **nicht dokumentiert** und
bislang **nicht gegen versehentliche Änderung abgesichert** gewesen. Kein
Bug — aber ein Verhalten, das ein künftiger Refactor (z. B. Wechsel auf ein
`dict` oder eine andere Zählmethode) unbemerkt hätte umkehren können.

Neue Tests: `TestFeatureArtistInferenceTieBreaking` (Mehrheits-Fall als
Gegenprobe + expliziter Gleichstand-Fall in beiden Reihenfolgen).

## Nicht als Lücke bestätigt / bewusst nicht vertieft

- `prioritize_genres()`, `normalize_genre_name()`, Wortgrenzen-Matching,
  Längster-Alias-Tie-Breaking: bereits umfassend durch ARCH-013/ARCH-014
  charakterisiert, keine neuen Lücken gefunden.
- `_prepare_search_title()` (Titel-Bereinigung vor API-Suche): rein
  syntaktische Regex-Bereinigung ohne Fachlogik-Verzweigung, geringes
  Risiko — nicht vertieft, da P0-Fokus auf Entscheidungslogik liegt, nicht
  auf String-Formatierung.
- `_calculate_genre_priority_from_hierarchy()`: Struktur-/Ladelogik, nicht
  Bestandteil der eigentlichen Genre-Entscheidung pro Track — außerhalb des
  P0-C-Scopes.

## Tests

- Gezielt: `tests/test_genre_processor.py` — 37 passed (4 neu).
- Thematisch: `pytest tests/ -q -k genre` — 252 passed, keine Regression.
- Keine Produktionscode-Änderung in diesem Schritt — reine
  Characterization, alle Assertions aus Live-Verifikation gegen die echte
  Produktionsklasse abgeleitet (Regel 7).
