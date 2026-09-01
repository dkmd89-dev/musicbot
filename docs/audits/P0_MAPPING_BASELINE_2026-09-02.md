# P0-A: Mapping-Baseline für `mapping/artist_genre.yaml`

**Datum:** 2026-09-02
**Phase:** P0-A der laufenden P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Reihe
(Branch `audit/p0-metadata-duplicate-detection`, siehe `docs/audits/` für P0-B ff.)
**Scope:** `mapping/artist_genre.yaml` (172 manuelle Einträge) im Zusammenspiel mit
`mapping/auto_learned_genre.yaml` (32 Einträge) und der Lade-/Merge-/Lookup-Logik
in `utils/genre_map.py`.

## Zusammenfassung

Baseline ist strukturell und inhaltlich sauber. Ein einziger Fund (18 tote,
aber harmlose Mapping-Einträge) — kein P0/P1-Bug, keine fehlerhafte
Genre-Zuordnung. Keine Code- oder Mapping-Änderung in diesem Schritt
vorgenommen (siehe Abschnitt „Offene Entscheidung" unten).

## 1. Case-insensitive Key-Kollision (`artist_genre.yaml` vs. `auto_learned_genre.yaml`)

**Ausgangsverdacht:** `artist_genre.yaml`-Keys sind durchgängig lowercase,
`auto_learned_genre.yaml`-Keys sind gemischt-case (z. B. `BHZ`, `Bebe Rexha`).
Ohne Normalisierung könnte ein auto-gelernter Eintrag einen manuellen Eintrag
unbemerkt überschreiben oder umgekehrt maskiert werden.

**Befund:** Kein Risiko. `GenreMapper._parse_genre_mappings()`
(`utils/genre_map.py:316-355`) lowercased jeden Key bereits beim Parsen
(`mappings[key.lower().strip()] = mapping`), **bevor** der Merge-Check
`if key not in self.artist_map` (`utils/genre_map.py:266-269`) läuft. Manuelle
Einträge haben damit unabhängig von der Schreibweise im Rohformat immer
Vorrang — genau wie im Code-Kommentar dokumentiert („manual hat immer
Vorrang!").

Empirisch verifiziert: 0 tatsächliche case-insensitive Kollisionen zwischen
den 172 manuellen und 32 auto-gelernten Einträgen im aktuellen Datenstand.
Keine internen Lowercase-Duplikate innerhalb einer der beiden Dateien.

## 2. Strukturelle Konsistenzprüfung (alle 172 manuellen Einträge)

Automatisiert geprüft:
- fehlendes `primary`
- fehlende `description`
- `primary` zusätzlich in `secondary` enthalten (redundant/inkonsistent)
- Duplikate innerhalb von `secondary`
- Schreibweisen-Varianten desselben Genres über verschiedene `primary`-Werte
  hinweg (z. B. „Hip-Hop“ vs. „Hip Hop“)

**Befund:** 0 Auffälligkeiten. 29 distinkte `primary`-Genres, keine
Schreibweisen-Varianten.

## 3. Inhaltliche Stichprobe (18 Einträge, gleichmäßig über die Datei verteilt)

18 Einträge quer über alle Genre-Cluster (Hip Hop, Pop, Electronic,
Alternative, Indie, Sonderfälle wie Label-Compilations, YouTube-Topic-/VEVO-
Kanäle, Podcast-Kanäle) manuell auf fachliche Plausibilität geprüft
(Artist/Genre-Zuordnung gegen bekannte Fakten).

**Befund:** 0 Fehlzuordnungen. Alle 18 Stichproben korrekt.

## 4. Bonus-Fund: tote Channel-Suffix-Einträge (nicht ursprünglich geplant)

Bei der Stichprobe fielen zwei Einträge mit YouTube-Kanalsuffix im Key auf
(`kygo - topic`, `eminem vevo`). Das warf die Frage auf, ob solche Keys über
den echten Lookup-Pfad überhaupt erreichbar sind — `ArtistProcessor.
clean_artist_before_normalization()` entfernt genau diese Suffixe
(`- Topic`, `VEVO`, `Official`, `Music`, `Records`), **bevor** der
gereinigte Artist-Name an die Genre-Lookup-Kette
(`GenreProcessor.determine_genre_with_fallbacks()` →
`GenreMapper.get_artist_entry()` / `.determine_genre()`) übergeben wird.

**Vollständiger Scan über die ganze Datei:** 19 Keys mit Suffix-Muster
(`- Topic`, `VEVO`, `Official`, case-insensitive) gefunden:

| Kategorie | Anzahl | Erreichbarkeit |
|---|---|---|
| Suffix-Key, Basis-Key existiert ebenfalls (z. B. `kygo - topic` + `kygo`) | 18 | **Tot** — der exakte Match auf den Basis-Key (Schritt 1, `get_artist_entry`) greift immer zuerst, bevor der Fuzzy-Fallback (Schritt 2, `determine_genre()`, Threshold 85) die Suffix-Variante erreichen könnte. Verifiziert per `git`-Datenanalyse und Fuzzy-Score-Berechnung (`rapidfuzz.fuzz.WRatio`, z. B. `"kygo"` vs. `"kygo - topic"` = 90.0 — über der Schwelle, aber nie erreicht). |
| Suffix-Key, **kein** Basis-Key vorhanden (`glasperlenspiel - topic`) | 1 | **Aktiv/load-bearing** — `clean_artist_before_normalization()` liefert „Glasperlenspiel“, wofür kein exakter Match existiert; der Fuzzy-Fallback (Score 90) matcht dann korrekt auf `glasperlenspiel - topic`. Dieser Eintrag wird tatsächlich gebraucht. |

**Datenqualität der 18 toten Einträge:** in allen 18 Fällen stimmt `primary`
mit dem jeweiligen Basis-Key exakt überein (nur `secondary` ist bei den
Suffix-Varianten teils kürzer/älter). Selbst falls der Erreichbarkeits-
Mechanismus sich künftig ändern sollte, würden diese 18 Einträge **keine
falsche Genre-Zuordnung** produzieren — sie sind redundant, nicht
fehlerhaft.

## Offene Entscheidung (bewusst nicht in diesem Schritt entschieden)

Die 18 toten Einträge sind ein reiner Aufräum-Kandidat, kein Bug. Gemäß
CLAUDE.md Abschnitt 10/28 (Mapping-Änderungen wie Code behandeln, keine
unkontrollierten Bulk-Änderungen) wird hier **keine** Löschung vorgenommen,
ohne dass das explizit angefragt wird — auch wenn es sich um 18 gleichartige
Fälle handelt. Empfehlung: separater, expliziter Mini-Schritt („mapping:
remove 18 dead channel-suffix entries from artist_genre.yaml“) mit den
konkreten Vorher/Nachher-Beispielen aus dieser Tabelle, falls gewünscht.

## Tests

Keine Code-Änderung in diesem Schritt → keine neuen/geänderten Tests nötig.
Alle Aussagen oben sind über Live-Ausführung der Produktionslogik
(`GenreMapper._parse_genre_mappings`, `rapidfuzz.fuzz.WRatio`,
`ArtistProcessor.clean_artist_before_normalization`) verifiziert, nicht nur
durch Lesen des Codes angenommen.
