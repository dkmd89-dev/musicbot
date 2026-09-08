# Artist Identity Resolution & Mapping Separation — Migration (Phase A–F)

**Datum:** 2026-09-08
**Typ:** kontrollierte Architekturmigration (CLAUDE.md §3.A), phasenweise
`Characterize → Decide → Extract → Audit → Regression`.
**Ausgangsbasis:** P0/P1-Audit „Artist Identity Resolution & Mapping
Integration" (Findings F-01…F-08).
**Branch/PR:** `arch/artist-identity-phase-a-characterization`.

---

## 1. Problemstellung (Audit-Ergebnis)

Vor der Migration wurde ein Artist-Name von der Pipeline **bestimmt**, aber
nie gegen die vorhandenen Mapping-Quellen als **bekannte Identität**
aufgelöst:

- `artist_overrides.json` / `auto_learned_artist_aliases.json` wurden nur
  als **Nebeneffekt** von `ArtistNormalizer.normalize()` konsultiert
  (`_check_overrides`), ohne Identitäts-/Quellensignal — für den Aufrufer
  nicht erkennbar, ob ein Mapping gegriffen hatte (F-01).
- `artist_source` wurde in `EnhancedMetadataProcessor` bedingungslos mit
  `"first_artist_from_title"` überschrieben — Mapping-Wirkung nicht
  nachweisbar (F-02).
- `known_artists.yaml` wurde im Entscheidungspfad **nie** gelesen — nur als
  nachgelagertes AutoLearn-Dedup-Gate (`_is_artist_known`) (F-03).
- Die einzige „Identitäts"-Aktion war eine **uncommittete** Kompensation im
  AutoLearn-Zweig: der bestimmte Artist wurde selbst in `known_artists.yaml`
  registriert — Identity Registration im Lern-Subsystem statt Resolution
  (F-04).
- `ArtistNormalizer` spiegelte Library-Ordnernamen beim Start **persistent**
  in `artist_overrides.json` — Vermischung von manueller Fachdatei und
  abgeleitetem Zustand, Git-Rauschen (F-05).
- Toter/leerer Alias-Code in `artist_map.py` (F-06).
- MusicBrainz-Artist-MBID wird geladen, aber nie als Identitätssignal
  konsumiert (F-07).

## 2. Zielarchitektur

```
youtube_parser            → Kandidaten (Titel-Split, kein Mapping)
        ▼
ArtistProcessor.determine_best_artist()   → _candidate_source
        ▼
ArtistNormalizer.normalize()              = NUR String-Normalisierung
        ▼
ArtistIdentityResolver.resolve(name, ctx) = Identität bestimmen
        ├─ 1. artist_overrides.json              → source="artist_override"
        ├─ 2. known_artists.yaml                 → source="known_artist"
        ├─ 3. auto_learned_artist_aliases.json   → source="auto_learned_alias"
        ├─ 4. Library-Artist-Index (in-memory)   → source="library_identity"
        ├─ 5. musicbrainz_mbid  (DEFERRED — F-07, Stub → None)
        └─    sonst                              → source="parser", known=False
        ▼
ArtistIdentity { canonical, source, known }
        ▼
final_artist = identity.canonical
artist_source = identity.source
artist_known = identity.known
        ▼
AutoLearn — NUR wenn  identity.known == False
        ▼
MetadataResult { artist, artist_source, artist_known }
```

### Verbindliche Priorität

```
artist_override > known_artist > auto_learned_alias > library_identity > musicbrainz_mbid > parser
```

Ein niedriger priorisiertes Signal überschreibt **niemals** einen höher
priorisierten autoritativen Eintrag. Insbesondere: Library / AutoLearn /
MBID überschreiben **nie** einen manuellen `artist_overrides.json`-Eintrag.

### `known`-Semantik

| `known` | Bedeutung | AutoLearn |
|---|---|---|
| `True` | Identität aus autoritativer Quelle bestätigt (override / known_artist / alias / library_identity / mbid) | **kein** Artist-AutoLearn |
| `False` | nur der (string-normalisierte) Parser-Kandidat übernommen (`source="parser"`) | AutoLearn darf eine neue Beziehung lernen |
| `None` | nicht aufgelöst (Podcast/Fallback; Alt-Aufrufer; Cache-Eintrag ohne Feld) | — |

`ArtistIdentity(source="parser", known=True)` ist per `__post_init__`
unzulässig.

### Konfliktregeln (deterministisch, Schritt 14)

- Alle Lookups laufen über normalisierte Schlüssel (`_normalize_key`,
  case-/akzent-insensitiv) + strikte Tier-Reihenfolge — unabhängig von
  Dict-/Datei-/Filesystem-Reihenfolge.
- Beide Formen (Rohname + string-normalisierter Name) werden je Tier
  geprüft, Tiers streng sequenziell.
- Self-Aliase (`"X" → "X"` in `auto_learned_artist_aliases.json`) werden
  verworfen — eine Identität gehört nach `known_artists.yaml`, kein Alias.
- Ein Library-Ordner **ohne** Eintrag in `artist_overrides.json` →
  `source="library_identity"`. Bereits früher automatisch erzeugte
  Self-Mapping-Einträge in `artist_overrides.json` bleiben unangetastet
  (bewusste Nutzerentscheidung, siehe Abschnitt 6) und melden weiterhin
  `source="artist_override"` (beide `known=True`, Gate identisch).

## 3. Phasen

| Phase | Inhalt | Kernänderungen |
|---|---|---|
| **A** | Characterization-Sicherheitsnetz | `tests/test_artist_identity_characterization_phase_a.py` — friert den Ist-Zustand ein (kein Produktionscode) |
| **B** | Resolver einführen + verdrahten | `models.py`: `ArtistIdentity`, `ARTIST_IDENTITY_SOURCES`, `MetadataResult.artist_known`. Neu: `services/metadata/artist_identity_resolver.py`. EMP: Schritt 6b `resolver.resolve()` nach `determine_best_artist()`; `first_artist_from_title`-Überschreibung **entfernt** (F-02); AutoLearn-Gate → `not artist_known` (F-04); uncommitteter Self-Registration-Fallback **entfernt** (F-04). `cache.py`: `artist_known`-Roundtrip. |
| **C** | Library → `artist_overrides.json`-Persistenz stoppen (F-05) | `artist_map.py`: `library_index` (refreshbar via `refresh_library_index()`); `_update_overrides_from_library_async()` → in-memory-Spiegel ohne Persistenz. Resolver-Tier 4 nutzt `library_index`. EMP Schritt 19d: `resolver.refresh()` nach `known=False`-Download. |
| **D** | `normalize()` = reine String-Normalisierung (F-01) | `artist_map.py`: `_check_overrides`-Aufruf + in-memory-Spiegel aus `normalize()` entfernt. `services/duplicate/detector.py`: `_normalize_artist_for_comparison()` nutzt jetzt den Resolver (sonst Alias-False-Negatives im Content-Hash). `track_reprocessor.py`: bewusst weiter `normalize()` (©ART-Tags sind bereits kanonisch). |
| **E** | Cleanup + Known/Alias-Trennung (F-06, Schritt 11/19) | `artist_map.py`: `_check_overrides` / `_mirror_library_artists_in_overrides` / `_save_overrides` / `learn_from_feedback` **entfernt** (0 Aufrufer). `add_auto_learned_alias` / `_save_auto_learned_entry` **deprecatet** (getestet → F-08). `auto_learn.py`: `ALLOWED_ARTIST_SOURCES` = `{"youtube_parsed"}`; `_is_non_artist_channel` deprecatet; `AutoLearnManager` bekommt optionalen `artist_identity_resolver` → Feature-Artist-Kanonikalisierung + Known-Check über den Resolver. EMP `_learn_sources` = `{"youtube_parsed", "raw_metadata"}`. |
| **F** | MusicBrainz-MBID: Zeitpunkt untersuchen | **Entscheidung B** — MBID entsteht in der Genre-Pipeline (EMP Schritt 9), **nach** `resolve()` (Schritt 6b). Keine Vorverlagerung. F-07 bleibt DEFERRED, Resolver-Tier-Slot #5 reserviert (`_resolve_mbid()` → `None`). Kein Code geändert. |

## 4. Geänderte Dateien

**Produktionscode**
- `services/metadata/artist_identity_resolver.py` — **neu**
- `services/metadata/models.py`, `enhanced_metadata_processor.py`,
  `auto_learn.py`, `cache.py`, `track_reprocessor.py` (nur Kommentar)
- `services/duplicate/detector.py`
- `utils/artist_map.py`

**Tests**
- **neu:** `test_artist_identity_characterization_phase_a.py`,
  `test_artist_identity_resolver_phase_b.py`,
  `test_artist_identity_autolearn_gate_phase_b.py`,
  `test_artist_identity_autolearn_feature_phase_e.py`
- **angepasst (bewusste Verhaltensänderung):** `conftest.py` (Kommentar),
  `test_artist_normalizer.py`, `test_artist_overrides_miksu_macloud_duo.py`,
  `test_artist_overrides_makko_case_preserve.py`,
  `test_artist_overrides_t_low_case_preserve.py`

**Nebenläufig (Testinfra):** `handlers/test_menu_handler.py` —
`__test__ = False` (pytest-Collection-Sperre für die Handler-Klasse
`TestMenuHandler`, beseitigt 3 Collection-Warnings).

## 5. Was beim Refactoring nicht kaputtgehen darf

- **Manuelle Overrides sind unantastbar** — kein automatischer Schreibpfad
  in `artist_map.py` mehr; nichts überschreibt `artist_override`.
- **`mapping/artist_overrides.json` / `known_artists.yaml` /
  `auto_learned_artist_aliases.json` bleiben inhaltlich unverändert** —
  keine Bereinigung im Rahmen dieser Migration.
- **Prioritätsreihenfolge** ist verbindlich (Abschnitt 2).
- **DuplicateDetector-Content-Hash** muss denselben kanonischen Artist
  verwenden wie die Metadaten-Pipeline (deshalb Resolver, nicht `normalize()`).
- **`normalize()` bleibt reine String-Normalisierung** — kein
  Wieder-Einbau von Identity-Lookups.

## 6. Bewusst nicht Bestandteil / offen

- **F-07 (MBID-Tier):** DEFERRED — erfordert separaten Architekturentscheid
  (Pipeline-Zeitpunkt, Match-Zuverlässigkeit, Verhalten bei abweichendem
  MusicBrainz-Artist; MB-01-Kontext + `WEICHT AB`-Characterization im
  `MusicBrainzClient`).
- **F-08 (deprecated Code):** DEFERRED/P3 — `add_auto_learned_alias`,
  `_save_auto_learned_entry`, `_is_non_artist_channel` samt Tests bleiben;
  Entfernung = separater Cleanup nach erneuter Referenzprüfung.
- **Review der bestehenden auto-generierten `artist_overrides.json`-Einträge**
  (manuell vs. Library-Altlast) — separate inhaltliche Entscheidung, kein
  Code-Thema.
- **`services/downloader/download_result_reporter.py`** leitet
  `youtube_parser_used` / `artist_map_parsing_fallback` aus per-Track-
  `artist_source`-Strings ab → zählt seit Phase B anders (kosmetische
  Telegram-Zusammenfassung, keine Fachlogik).

## 7. Regression

Vollständige Suite nach Phase F (Nutzer-Lauf, 2026-09-08):
**2920 passed, 1 skipped, 19 subtests passed** (197 s), 0 Regressionen.
Gezielte/thematische Läufe je Phase dokumentiert in den jeweiligen
Phasen-Abschlussberichten (Artist/Identity/Duplicate/Reprocess/MusicBrainz/
AutoLearn/Genre/Happy-Path/Cache/Translator/FilenameFixer/Playlist).

## 8. Findings-Status

| ID | Vorher | Nachher |
|---|---|---|
| F-01 keine dedizierte Identity Resolution | P1 OPEN | **CLOSED** (Phase B/D) |
| F-02 `artist_source`-Überschreibung | P1 OPEN | **CLOSED** (Phase B) |
| F-03 `known_artists.yaml` nicht im Entscheidungspfad | P2 OPEN | **CLOSED** (Phase B) |
| F-04 AutoLearn kompensiert (Self-Registration) | P2 OPEN | **CLOSED** (Phase B) |
| F-05 Library → `artist_overrides.json` | P2 OPEN | **CLOSED** (Phase C/E) |
| F-06 leere Aliases-Datei + toter Alias-Code | P3 OPEN | **CLOSED** (Phase E) |
| F-07 MBID nicht als Identitätssignal | P3 OPEN | **DEFERRED** (Phase F, Entscheidung B) |
| F-08 deprecated Artist-Code | — | **DEFERRED/P3** (neuer offener Cleanup-Punkt) |
