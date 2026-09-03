# MusicBot — Genre-System

Das Genre-System bestimmt für jeden Track ein primäres und bis zu fünf
sekundäre Genres, aus mehreren Quellen mit fester Priorität, und lernt
dabei selbstständig aus wiederkehrenden Beobachtungen dazu. Dieses
Dokument beschreibt Datenfluss, Dateien und bekannte Grenzen — das
tatsächliche Verhalten steht in den referenzierten Tests, nicht hier in
Prosa dupliziert (CLAUDE.md Abschnitt 6/7).

---

## 1. Zweck

Drei zusammenwirkende Komponenten unter `services/metadata/`:

- **`genre_processor.py::GenreProcessor`** — die eigentliche
  Fallback-Kette (Abschnitt 2), rein synchron außer den externen
  API-Aufrufen.
- **`auto_learn.py::AutoLearnManager`** — beobachtet Downloads und
  schreibt zunehmend vertrauenswürdige Genre-/Artist-Zuordnungen in die
  Auto-Learn-Dateien (Abschnitt 3/4).
- **`utils/genre_map.py::GenreMapper`** — lädt und mergt alle
  Mapping-Dateien (manuell + auto-gelernt) zu einer einzigen
  `artist_map`/`channel_map`, gegen die `GenreProcessor` nachschlägt.

## 2. Architektur/Datenfluss

Fallback-Reihenfolge in `GenreProcessor.determine_genre_with_fallbacks()`
(`services/metadata/genre_processor.py:67`):

```text
Track (artist_name, track_metadata, channel_name)
    ↓
1. Manuelles Genre    (artist_genre.yaml, exakter Match)      Zeile 99
    ↓ (nur falls kein Treffer)
2. Lokales Genre      (channel/fuzzy/raw/Hierarchie)          Zeile 112
    ↓
   known_result = manuelles ODER lokales Ergebnis
    ↓
3. MusicBrainz        (IMMER erreicht — auch bei bekanntem     Zeile 141
                        Genre, aber NUR für IDs; das MB-Genre
                        selbst wird verworfen falls
                        known_result bereits gesetzt ist)
    ↓
   Bekanntes Genre + MB-IDs → fertig, RETURN                  Zeile 164
    ↓ (nur falls KEIN known_result)
4. Last.fm             (Tags → prioritize_genres())            Zeile 174
    ↓
5. Feature-Artist-Inferenz (aus bereits bekannten Feature-      Zeile 196
    Artist-Genres, letzter Ausweg)
```

**Wichtig:** Schritt 3 (MusicBrainz) läuft *immer*, Schritt 4 (Last.fm)
dagegen *nur*, wenn weder Schritt 1 noch Schritt 2 ein Ergebnis
lieferten. Das ist die Ursache für den in Abschnitt 6 beschriebenen
Revalidierungs-Bug.

`prioritize_genres()` (`genre_processor.py:208`) verarbeitet eine
Tag-Liste (aus MusicBrainz oder Last.fm) zu `(primary, secondary[:5])`:
Tags werden normalisiert, gegen `GENRE_PRIORITY` (aus
`genre_hierarchy.yaml` berechnet) gewichtet, und nur Tags mit einem
tatsächlichen Treffer in der Hierarchie fließen ins Ergebnis ein — ein
unbekanntes Last.fm-Tag wird stillschweigend übergangen, nicht als
Fehler behandelt.

## 3. Mapping-Dateien im Überblick

| Datei | Format | Pflege | Gelesen von | Geschrieben von |
|---|---|---|---|---|
| `artist_genre.yaml` | YAML | manuell | `GenreMapper` | — |
| `channel_genre.yaml` | YAML | manuell | `GenreMapper` | — |
| `genre_hierarchy.yaml` | YAML | manuell | `GenreProcessor` (`GENRE_PRIORITY`) | — |
| `genre_aliases.yaml` | YAML | manuell | `GenreProcessor` (`normalize_genre_name()`) | — |
| `genre_filters.yaml` | YAML | manuell | `GenreProcessor` (`IGNORE_SECONDARY`) | — |
| `genre_overrides.yaml` | YAML | manuell | `GenreMapper` | — |
| `genre_rules.yaml` | YAML | manuell | `GenreMapper` | — |
| `known_artists.yaml` | YAML | auto (bestätigte Identität) | `AutoLearnManager` | `AutoLearnManager` |
| `auto_learned_genre.json` | **JSON** | auto | `GenreMapper` (Merge in `artist_map`) | `AutoLearnManager` |
| `auto_learned_artist_aliases.json` | **JSON** | auto | `ArtistNormalizer` | `AutoLearnManager`, `ArtistNormalizer` |
| `auto_learned_featured_artists.json` | **JSON** | auto | `AutoLearnManager` (nur intern) | `AutoLearnManager` |

Die drei JSON-Dateien wurden in ARCH-022 von YAML migriert — sie werden
nie von Hand editiert, YAML brachte dort keinen Vorteil (siehe
`docs/FINDINGS_INDEX.md`, ARCH-022-Eintrag). Alle übrigen
Mapping-Dateien bleiben bewusst YAML.

`auto_learned_artist_aliases.json` und `auto_learned_featured_artists.json`
waren bis ARCH-022 eine einzige Datei (`auto_learned_artists.yaml`) mit
zwei Top-Level-Keys — inzwischen physisch getrennt, da beide Namespaces
komplett unabhängig sind (`ArtistNormalizer` liest nur den
`auto_learned`-Key, nie `featured_artists`).

## 4. Auto-Learn-Konfidenz-Stufen

Eine einzige, für Genre- **und** Feature-Artist-Beobachtungen
gemeinsam genutzte Funktion (`services/metadata/auto_learn.py:44`,
`_confidence_tier()`):

```text
1 Beobachtung                        → OBSERVED
_LEARNED_THRESHOLD (2) .. <4         → LEARNED
_CONFIRMED_THRESHOLD (4)+            → CONFIRMED
```

`GenreMapper` merged beim Laden nur Einträge ab `LEARNED` in die aktive
`artist_map` (`utils/genre_map.py:240-259`, "AUTOLEARN-GENRE-TRUST") —
eine einzelne `OBSERVED`-Beobachtung beeinflusst noch keine künftige
Genre-Bestimmung. Primary/Secondary werden — solange kein Lock aktiv ist
(4.a) — bei jeder neuen Beobachtung per Mehrheitsvotum über die letzten
10 Beobachtungen neu abgeleitet (`_aggregate_genre_observations()`,
`auto_learn.py:96`) — explizit **kein** "last value wins".

Channel-Alias-Learning (`auto_learned_artist_aliases.json`) hat dagegen
**kein** Konfidenzkonzept: ein Alias wird beim ersten Mal geschrieben
und danach nie erneut bewertet.

### 4.a Lock-in-Mechanismus (seit 2026-09-03)

Reines Mehrheitsvotum über nur die letzten 10 Beobachtungen berechnet
`primary` bei *jeder* neuen Beobachtung neu — bei Artists mit vielen
Tracks und wechselnden Last.fm-Tags (Live-Fund: „Toobrokeforfiji") führt
das nie zu einem stabilen, artist-weiten Genre-Mapping. Zusätzlich zum
Mehrheitsvotum gilt seit dieser Phase eine Lock-in-Regel
(`_compute_genre_lock_decision()`/`_derive_genre_primary_secondary()`,
`services/metadata/auto_learn.py:138-260`):

```text
Vorlock-Phase (kein Genre hat 3 Beobachtungen erreicht):
    Verhalten unveraendert - reines Mehrheitsvotum wie oben.

Lock aktiv (ein Genre erreicht _GENRE_LOCK_THRESHOLD=3 Beobachtungen):
    primary bleibt dauerhaft dieser Wert, unabhaengig von neuen,
    abweichenden Beobachtungen.

Overturn (Herausforderer erreicht/uebersteigt
_GENRE_LOCK_OVERTURN_MULTIPLIER=3 mal die LIVE Beobachtungszahl des
aktuell gelockten Werts):
    Lock wechselt auf den Herausforderer.
```

Ein durch den Lock abgelehnter/überstimmter Wert erscheint **explizit**
in `secondary` (nicht nur implizit über das neue, ungedeckelte
`genre_counts`-Feld) — Nutzerentscheidung, damit der abgelehnte Wert
sichtbar bleibt statt zu verschwinden.

Zwei neue, additive Felder je Auto-Learn-Genre-Eintrag:

| Feld | Kappung | Zweck |
|---|---|---|
| `observation_log` | letzte 10 (`_MAX_OBSERVATION_LOG`) | Rohhistorie für das Mehrheitsvotum in der Vorlock-Phase |
| `genre_counts` | **ungekappt** | vollständige Beobachtungszahl je Genre — bleibt auch dann korrekt, wenn `observation_log` die auslösende Beobachtung längst herausgekappt hat |

Beispiel (Deutschrap/Pop, aus dem Pflicht-Testpaar): 3x „Deutschrap"
(Lock), danach 8x „Pop" — `observation_log` (Cap 10) enthält davon nur
noch 2x „Deutschrap" + 8x „Pop", `genre_counts` zeigt trotzdem korrekt
`{"Deutschrap": 3, "Pop": 8}`. Da 8 < 3×3=9, bleibt „Deutschrap"
gelockt; erst eine 9. „Pop"-Beobachtung überholt.

`_parse_genre_mappings()` (`utils/genre_map.py:329`) liest weiterhin nur
`primary`/`secondary`/`description` — `locked_primary`/`genre_counts`
sind für bestehende Konsumenten transparent, keine Breaking Change.

## 5. Bekannte Schutzmechanismen

| Mechanismus | Zweck | Verifizierender Test |
|---|---|---|
| Manuelles Mapping hat immer Vorrang | `artist_genre.yaml`-Eintrag blockiert Auto-Learn dauerhaft | `tests/test_auto_learn_genre_confidence_audit.py::TestManualMappingAddedAfterGenreAutoLearn` |
| `_is_artist_known()`-Gate | verhindert Neu-Lernen für bereits bekannte Artists | `tests/test_auto_learn_featured_artists_and_genre_aggregation.py` |
| Feature-Artist erbt nie ein Genre | verhindert falsche Genre-Übertragung von Primary auf Feature | `tests/test_auto_learn_genre_confidence_audit.py::TestNoahRegression` |
| Mehrheitsvotum statt "last value wins" | ein einzelner Ausreißer überschreibt nicht sofort | `tests/test_auto_learn_genre_confidence_audit.py::TestControlledObservationAggregation` |
| `OBSERVED` wird nicht aktiv genutzt | ein einzelner Last.fm-Treffer verfälscht nicht sofort dauerhaft | `tests/test_auto_learn_genre_confidence_audit.py::TestConfidenceTransitionControlled::test_only_learned_and_above_is_used_for_resolution` |
| Atomares Schreiben (tmp+replace) | keine korrupte Datei bei Absturz mitten im Schreiben | `tests/test_auto_learn_invariant_fix.py::TestAtomicWrite`, `tests/test_artist_normalizer.py::TestSaveAutoLearnedEntryAtomicWrite` |
| Namespace-Trennung (ARCH-022) | Channel-Alias- und Feature-Artist-Schreibpfade beeinflussen sich nie gegenseitig | `tests/test_auto_learn_featured_artists_and_genre_aggregation.py::TestAutoLearnedArtistsNamespaceSeparation` |
| Lock-in ab 3 Beobachtungen (4.a) | ein einzelnes Genre bleibt artist-weit stabil statt bei jeder Beobachtung neu bewertet zu werden | `tests/test_auto_learn_genre_lock_in.py` |
| Genre-Learning unabhängig vom Namens-Override | `artist_overrides.json` (Artist-**Namens**-Normalisierung) blockiert seit 2026-09-03 nicht mehr das Genre-Lernen — beide Mechanismen sind unabhängig | `tests/test_auto_learn_genre_learning_independent_of_name_override.py` |

## 6. Revalidierung von CONFIRMED-Einträgen

**Nutzer-Entscheidung (ARCH-022):** kein automatisches Revalidieren im
Download-Pfad. Sobald ein Genre-Eintrag `LEARNED` wird, überspringt
Schritt 1/2 der Fallback-Kette (Abschnitt 2) endgültig Schritt 4
(Last.fm) für diesen Artist — auch wenn Last.fm inzwischen mehr/andere
Tags liefern würde. Live verifiziert am Artist „Toobrokeforfiji": 8
reale Last.fm-Tags, aus denen der heutige `prioritize_genres()`-Code
bereits `secondary=[Hip Hop]` ableiten würde, wurden nie übernommen,
weil der Eintrag bereits `LEARNED`/`CONFIRMED` war.

Charakterisiert (bewusst nicht gefixt, siehe Abschnitt 7) in
`tests/test_genre_processor_revalidation_gap.py`. Wer einen konkreten
Artist neu bewerten lassen möchte, nutzt stattdessen gezielt
`scripts/reprocess_artist_metadata.py` (siehe
`docs/METADATA_REPROCESSING.md`) — das ruft dieselben
`learn_genre()`/`preview_genre_learning()`-Methoden manuell auf einen
einzelnen Artist an.

## 7. Bekannte Grenzen

Aus dem Docstring von `_confidence_tier()`
(`services/metadata/auto_learn.py:62`, "WICHTIGE EINSCHRÄNKUNG"):
Confidence-Gating schützt nur vor einer *einzelnen* fehlerhaften
Beobachtung — nicht davor, dass eine externe Quelle *konsistent*
denselben falschen Wert liefert (z. B. bei einer Namenskollision mit
einem gleichnamigen, anderen Künstler). Für einen echten
Identitätsabgleich wäre ein MusicBrainz-ID-basierter Vergleich nötig —
nicht Teil dieser Implementierung.

**Migrations-Backfill-Lücke (4.a):** ein Alt-Eintrag, der vor Einführung
des Lock-in geschrieben wurde, hat kein `genre_counts`-Feld —
`_derive_genre_primary_secondary()` rekonstruiert es beim ersten
Zugriff danach aus `observation_log[:-1]` (bis zu 9 der ursprünglich
tatsächlich beobachteten Werte, da `observation_log` bereits vorher auf
10 gekappt war). Bei einem Alt-Artist mit mehr als 10 echten historischen
Beobachtungen ist dieser Backfill unvollständig — die davor gekappten
Beobachtungen sind nicht mehr rekonstruierbar. Bewusst kein rückwirkender
Neuaufbau aus `observation_log`-Historie älterer Backups.

`observations`/`confidence` (Konfidenz-Stufen, Abschnitt 4) basieren
weiterhin auf der Länge des gekappten `observation_log`, nicht auf
`sum(genre_counts.values())` — ein Artist mit lange gelocktem Genre und
vielen Beobachtungen zeigt also weiterhin höchstens `CONFIRMED`, nicht
eine noch höhere, an die tatsächliche (ggf. weit über 10 liegende)
Gesamtzahl gekoppelte Stufe. Bewusst nicht umgestellt — außerhalb des
Scopes dieser Phase.

## 8. Testverfahren

Relevante Testdateien (echte Produktionsklassen, keine Nachbauten —
CLAUDE.md Abschnitt 7):

- `tests/test_genre_processor.py` — `normalize_genre_name()`,
  `prioritize_genres()`, die volle Fallback-Kette (Schritte 1–5
  einzeln, inkl. Cap-Verhalten mit echten und ausschließlich unbekannten
  Tags).
- `tests/test_genre_processor_revalidation_gap.py` — der in Abschnitt 6
  beschriebene, bewusst beibehaltene Revalidierungs-Bug.
- `tests/test_auto_learn.py`, `tests/test_auto_learn_genre_confidence_audit.py`,
  `tests/test_auto_learn_featured_artists_and_genre_aggregation.py`,
  `tests/test_auto_learn_invariant_fix.py` — Konfidenz-Eskalation,
  Mehrheitsvotum, NOAH-Regression, Concurrency/Atomarität,
  Namespace-Trennung.
- `tests/test_auto_learn_genre_lock_in.py` — Lock-in-Regel (4.a):
  isolierte Lock-Entscheidung inkl. Grenzfälle, Pflicht-Testpaar für die
  `observation_log`-Kappung, Legacy-Backfill, Dry-Run/Live-Konsistenz.
- `tests/test_auto_learn_genre_learning_independent_of_name_override.py` —
  beweist (Pre-Fix-Diskriminierung), dass ein Artist-Namens-Override
  allein das Genre-Lernen nicht mehr blockiert.
- `tests/test_artist_normalizer.py::TestSaveAutoLearnedEntryAtomicWrite` —
  atomares Schreiben in `auto_learned_artist_aliases.json`.
- `tests/test_artist_overrides_orphan_cleanup.py`,
  `tests/test_artist_overrides_makko_case_preserve.py`,
  `tests/test_artist_overrides_miksu_macloud_duo.py`,
  `tests/test_artist_overrides_t_low_case_preserve.py` —
  Daten-Integritätstests gegen die echte `mapping/artist_overrides.json`
  (Whitelist-Bereinigung + gezielt geschützte Normalisierungs-Fixes).
- `tests/test_mapping_yaml_integrity.py` — Duplicate-Key-Schutz für
  *alle* `mapping/*.yaml`- und `mapping/*.json`-Dateien, format-agnostisch.

```bash
python3 -m pytest tests/test_genre_processor*.py tests/test_auto_learn*.py tests/test_artist_normalizer.py tests/test_artist_overrides*.py tests/test_mapping_yaml_integrity.py -q
```

## 9. Migrationshistorie

**ARCH-022** (2026-09-03): Charakterisierung des Revalidierungs-Bugs
(Abschnitt 6), Namespace-Trennung von `auto_learned_artists.yaml` in
zwei Dateien, atomarer Schreibfix in `ArtistNormalizer`, YAML→JSON-
Migration der drei Auto-Learn-Dateien, Reset der fehlerhaften/
unvollständigen Bestandsdaten (32 Genre-Einträge, 16 Artist-Aliase —
alle Migrations-Artefakte aus der Zeit vor Einführung des
Konfidenz-Gatings, siehe `docs/FINDINGS_INDEX.md`). Auslöser: Live-Fund
beim Artist „Toobrokeforfiji" (Last.fm liefert heute mehr Tags als der
alte, eingefrorene Bestandseintrag je hatte).

**Genre-Lock-in + Override-Entkopplung** (2026-09-03, Folgephase zu
ARCH-022): Auslöser — derselbe Live-Fund bei „Toobrokeforfiji" zeigte
zwei zusätzliche, unabhängige Probleme: (1) reines Mehrheitsvotum
berechnet `primary` bei *jeder* Beobachtung neu, führt bei vielen Tracks
nie zu einem stabilen artist-weiten Mapping — behoben durch die
Lock-in-Regel (4.a). (2) `learn_genre()` blockierte das Schreiben
vollständig für jeden in `mapping/artist_overrides.json` gelisteten
Artist (Artist-**Namens**-Normalisierung, kein Genre-Bezug) — verifiziert
betraf das 78 von 174 Override-Artists ohne manuelles Genre. Der
Override-Block wurde entfernt (Genre-Learning und Namens-Normalisierung
sind jetzt unabhängig); der separate Feature-Artist-Override-Check
(`_is_artist_known()`/`_compute_featured_artist_decision()`) blieb
unverändert. Zusätzlich wurde `artist_overrides.json` von 174 auf 19
Einträge bereinigt (Whitelist: 12 aktuelle Library-Artists + Werte, die
von den bestehenden Daten-Integritätstests
`test_artist_overrides_t_low_case_preserve.py`/
`test_artist_overrides_miksu_macloud_duo.py` geschützt sind — nicht
strikt auf den Library-Stand reduziert, um bereits live bestätigte
Normalisierungs-Fixes nicht zu verlieren). Siehe
`tests/test_auto_learn_genre_lock_in.py`,
`tests/test_auto_learn_genre_learning_independent_of_name_override.py`,
`tests/test_artist_overrides_orphan_cleanup.py`.
