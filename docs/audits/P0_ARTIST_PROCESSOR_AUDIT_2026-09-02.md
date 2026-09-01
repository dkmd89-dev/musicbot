# P0-D: Artist fachlich vollständig auditieren (`services/metadata/artist_processor.py`)

**Datum:** 2026-09-02
**Phase:** P0-D der laufenden P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Reihe
(Branch `audit/p0-metadata-duplicate-detection`).
**Scope:** `services/metadata/artist_processor.py` (`ArtistProcessor`, 216 Zeilen,
vollständig gelesen und live geprüft). Vier öffentliche Methoden:
`determine_best_artist()`, `find_known_artist_from_list()`,
`clean_artist_before_normalization()`, `split_feature_artists()`.

## Zusammenfassung

Kernlogik (`determine_best_artist()`, `clean_artist_before_normalization()`)
verhält sich korrekt wie dokumentiert und ist bereits solide getestet
(`tests/test_metadata_modules.py::TestArtistProcessor`, ergänzt um P0-B/P0-C-
Regressionstests an anderer Stelle). Zwei Funde, beide **kein Bug**, keine
Produktionscode-Änderung in diesem Schritt:

1. Ein Public-Method (`find_known_artist_from_list()`) ist seit dem
   allerersten Commit dieses Repos ohne einen einzigen Aufrufer — totes
   Code (Dokumentationsfund, analog zum PR-#99-Muster).
2. Ein Redundanz-Check in der Prioritätskette von `determine_best_artist()`
   ist strukturell unerreichbar/tot (kein Bug — die Kette liefert exakt das
   dokumentierte Verhalten, die betroffene Vergleichsbedingung tut aber
   nachweislich nie etwas).

## 1. `determine_best_artist()` — Prioritätskette bestätigt korrekt

Dokumentierte und live verifizierte Priorität:
`dominant_artist > parsed_artist > raw_artist > channel_name`, jeder
Kandidat über `clean_artist_before_normalization()` bereinigt und über
`split_main_and_featuring()` (aus `.models`, ARTISTNORM-002-Wortgrenzen-Fix,
siehe P0-B) in Haupt-/Feature-Artist getrennt, **bevor** normalisiert wird
(ARTIST-001-Fix, verhindert das fälschliche Degradieren eines zusammen-
gesetzten Hauptartists wie „1986zig" zum Feature).

Bereits vorhandene Tests decken alle vier Prioritätsstufen einzeln sowie
den Haupt-/Feature-Split ab (`tests/test_metadata_modules.py`). Keine
Abweichung vom dokumentierten Verhalten gefunden.

### 1a. Fund: „Duplikat-Verhinderungs"-Vergleiche in den Fallback-Zweigen sind tot

Die Zweige für `raw_metadata` (Zeile 82-88) und `channel_fallback`
(Zeile 90-100) enthalten zusätzlich zur reinen Gültigkeitsprüfung
(`src_* in ["normalized", "cleaned_raw_fallback"]`) einen Vergleich gegen
die bereits verworfenen höherprioren Kandidaten
(`norm_raw != norm_parsed`, bzw. `norm_channel != norm_parsed and
norm_channel != norm_raw`). Das liest sich, als solle damit verhindert
werden, einen Fallback zu wählen, der zufällig mit einem bereits
abgelehnten Kandidaten identisch ist.

**Live und strukturell bewiesen, dass dieser Vergleich nie etwas bewirkt:**
Jeder Zweig, der erfolgreich normalisiert (`src_* in [...]` wahr), gibt
**sofort** zurück (`return ...` in derselben `if`). Ein späterer Zweig wird
also ausschließlich dann überhaupt erreicht, wenn der/die vorherigen
Kandidaten bereits gescheitert sind — und ein gescheiterter Kandidat hat
per Konstruktion von `_clean_and_normalize()` immer `None` als Ergebnis.
Ein Vergleich `neuer_kandidat != None` ist trivial wahr, solange der neue
Kandidat selbst gültig ist. Der Vergleich kann also strukturell **nie**
`False` ergeben und damit nie einen an sich gültigen Fallback blockieren.

Live-Beleg (nicht nur Code-Lesen): `raw_artist="Valid Raw Artist"`,
`channel_name="Valid Raw Artist"` (bewusst identisch) →
`determine_best_artist()` liefert sofort `source="raw_metadata"` — der
Channel-Vergleichszweig wird nicht einmal erreicht, weil `raw_metadata`
bereits vorher zurückgibt. Das ist der Beweis, dass der spätere Vergleich
niemals einen tatsächlich nicht-`None`-Wert zu Gesicht bekommt.

**Bewertung:** kein Bug — das beobachtbare Verhalten der Prioritätskette
ist exakt das dokumentierte und gewünschte. Der Fund ist rein strukturell:
totes Vergleichs-Fragment, vermutlich ein Überbleibsel aus einer früheren
Version der Kette (vor Einführung der Early-Returns) oder eine defensive
Prüfung, deren Autor die Unerreichbarkeit nicht bemerkt hat. Neuer
Characterization-Test (`test_priority_chain_duplicate_guards_never_block_a_
lower_priority_fallback`) hält das Verhalten fest, damit ein künftiger
Refactor (z. B. Entfernen der toten Vergleiche) nachweisbar nichts am
Ergebnis ändert.

## 2. Fund: `find_known_artist_from_list()` ist totes Public-API

`grep -rn "find_known_artist_from_list"` über das gesamte Repository
findet ausschließlich:
- die Definition in `services/metadata/artist_processor.py:107`,
- eine dünne Facade `EnhancedMetadataProcessor._find_known_artist_from_list()`
  (`enhanced_metadata_processor.py:1271-1272`), die nur durchreicht,
- keinen einzigen echten Aufrufer von einer der beiden Methoden.

`git log --all -S "find_known_artist_from_list(" -- .` zeigt: der einzige
Treffer außerhalb der beiden Definitionen selbst ist der allererste Commit
(`f000cc0`, „Initial commit: MusicBot") — die Methode war demnach von
Anfang an ohne Aufrufer vorhanden und wurde bei der ARCH-010-Migration
(`services/downloader/utils/metadata/` → `services/metadata/`)
unverändert mitgenommen, ohne dass ihr Aufruferstatus sich je geändert
hätte. Auch keine Testabdeckung vorhanden.

**Keine Löschung in diesem Schritt** (analog zum Vorgehen bei den 18 toten
Mapping-Einträgen in P0-A) — Legacy-Code wird laut CLAUDE.md Abschnitt 20
nicht ohne Beweis entfernt, aber hier liegt der Beweis (0 Aufrufer seit
Tag 1) bereits vor. Empfehlung: separater, expliziter Mini-Commit zur
Entfernung, falls gewünscht (analog zum PR-#99-Muster: dead-code Cleanup
mit Verweis auf 0-Aufrufer-Nachweis).

## 3. `clean_artist_before_normalization()` — keine neuen Funde

Bereits in P0-A/P0-B im Detail gegen die Genre-Lookup-Kette analysiert
(Suffix-Entfernung VEVO/Topic/Official/Music/Records, Multi-Artist-Komma-
Split, Episodennummer-Erkennung). Ein theoretisches Risiko wurde geprüft
und **nicht bestätigt**: der Komma-Split (`"Artist, Name"` → `"Artist"`)
könnte bei einem „Nachname, Vorname"-formatierten Künstlernamen den
falschen Teil als Hauptartist wählen. Grep über `mapping/artist_overrides.json`
und `mapping/known_artists.yaml` fand **keinen** einzigen Artist-Namen mit
Komma in der realen Datenbasis — kein Hinweis auf tatsächliche Auswirkung,
daher keine weitere Vertiefung (Regel 9: bei Unsicherheit analysieren,
nicht raten — analysiert, keine Evidenz für ein reales Problem gefunden).

## 4. `split_feature_artists()` — kein neuer Fund

Dünner Delegat zu `split_main_and_featuring()` (`.models`), bereits
umfassend über `tests/test_split_main_and_featuring.py` und die P0-B-
Regressionstests abgesichert.

## Verhältnis zu P0-E (Duplicate Detector)

Der eingangs identifizierte strukturelle Punkt „`ArtistProcessor` vs.
`DuplicateDetector` besitzen unabhängige, potenziell abweichende
Normalisierungslogik" wird bewusst **nicht** hier, sondern in P0-E
behandelt (dort mit direktem Vergleichstest gegen `DuplicateDetector`).

## Tests

- Gezielt: `tests/test_metadata_modules.py` — 16 passed, 11 subtests passed
  (1 neuer Test).
- Thematisch: `pytest tests/ -q -k "artist_processor or metadata_modules or
  artist_normalizer"` — 36 passed, 11 subtests passed, keine Regression.
- Keine Produktionscode-Änderung — reine Characterization + Dokumentation
  zweier Funde (toter Redundanz-Check, totes Public-API), beide zur
  Entscheidung vorgelegt statt eigenmächtig entfernt.
