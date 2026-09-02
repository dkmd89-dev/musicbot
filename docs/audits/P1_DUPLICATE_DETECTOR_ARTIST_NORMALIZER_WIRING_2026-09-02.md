# P1: DuplicateDetector ↔ ArtistNormalizer-Verdrahtung

**Datum:** 2026-09-02
**Branch:** `p1/duplicate-detector-artist-normalizer-wiring`
**Vorgeschichte:** P0-E (`docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md`)
fand, dass `DuplicateDetector.artist_normalizer` in Produktion immer `None`
ist, und fixte das Symptom (eigene Fallback-Liste erweitert). Dieses
Dokument behandelt die zurückgestellte Ursache: `DuplicateDetector` sollte
den echten, geteilten `ArtistNormalizer`/`ArtistProcessor`-Pfad nutzen statt
einer parallelen Normalisierungslogik.

Methodik: Characterize → Decide → Extract → Audit → Regression
(CLAUDE.md Abschnitt 3.A).

## 1. Characterize

- Der defekte `hasattr(config, "artist_config")`-Zweig existiert
  unverändert seit dem **allerersten Commit** dieses Repos (`f000cc0`,
  damals in `handlers/duplicate_handler.py::EnhancedDuplicateHandler`, per
  ARCH-018 Phase 2 wortgleich verschoben) — keine ursprüngliche Absicht
  aus der Historie rekonstruierbar.
- **Entscheidender Fund zur Konstruktionsreihenfolge:**
  `handlers/menu/rich_menu_handler.py` konstruiert `DuplicateDetector`
  (Schritt 7, Zeile 227) **vor** `EnhancedMetadataProcessor` (Schritt 11,
  Zeile 270). Da `ArtistNormalizer` ein `SingletonMixin` ist, bedeutet das:
  `DuplicateDetector` ist im echten Bot-Start der **erste** Konstruktions-
  versuch des Singletons — nicht `EnhancedMetadataProcessor`, wie zunächst
  angenommen.
- Damit war auch klar: eine reine `config.artist_config`-Ergänzung ohne
  Behebung des Keyword-Bugs (`artist_config=` statt `config=`) hätte einen
  **sofortigen Absturz beim Bot-Start** verursacht, nicht nur eine
  Normalisierungslücke — `DuplicateDetector` wäre der erste (und damit
  einzige `_do_init()`-ausführende) Aufrufer gewesen.

## 2. Decide

Weil `ArtistNormalizer` ein Singleton ist, ist die Konstruktionsreihenfolge
für das Endergebnis irrelevant, solange **irgendein** Aufrufer ihn korrekt
konstruiert. Zielbild: `DuplicateDetector.__init__()` spiegelt denselben
`ArtistConfig`-Aufbau wie `EnhancedMetadataProcessor.__init__()`
(`LIBRARY_DIR`/`ARTIST_OVERRIDE_FILE`/`GENRE_MAPPING_DIR`), unconditional
statt über das `hasattr`-Gate.

## 3. Extract

### 3a. Erster Fix-Versuch — unvollständig

Reine Verdrahtung von `ArtistNormalizer` (Konstruktion wie oben) legte
sofort zwei weitere Probleme offen:

**Pfad-Typ-Inkonsistenz:** `ArtistConfig.library_dir` muss ein echtes
`Path`-Objekt sein (`ArtistNormalizer._load_library_artists()` ruft
`.exists()` auf). Die reale `config.Config.LIBRARY_DIR` ist bereits ein
`Path` (deshalb fiel das bei `EnhancedMetadataProcessor` nie auf), aber
mehrere `FakeConfig`-Testfixtures in `services/duplicate/`-Tests verwenden
bewusst Strings (`str(tmp_path / "library")`) — bislang unproblematisch,
weil `DuplicateDetector`/`DuplicateCache` Pfadwerte immer selbst über
`Path(...)` wrappen. 60 Test-Errors als direkte Folge. Fix: `Path(...)`
explizit um alle drei `ArtistConfig`-Felder — konsistent zur bereits
etablierten defensiven Konvention dieser Klasse, keine Änderung an den
Testfixtures nötig.

**Der eigentlich wichtige Fund:** selbst mit korrektem `Path`-Wrapping
blieben 10 Tests rot. Ursache: `ArtistNormalizer.normalize()` entfernt
Channel-Suffixe wie `"- Topic"`/`"VEVO"`/`"Official"` **nicht**
selbstständig — das übernimmt ausschließlich das vorgeschaltete
`ArtistProcessor.clean_artist_before_normalization()` (Leerzeichen-
Separator-Split, z. B. `"Kygo - Topic"` → `"Kygo"`, **bevor**
`normalize()` überhaupt aufgerufen wird). Live bestätigt:
`ArtistNormalizer.normalize("Kygo - Topic")` liefert unverändert
`"Kygo - Topic"`. Reine `ArtistNormalizer`-Verdrahtung ohne die
vorgeschaltete Bereinigung hätte die ursprüngliche P0-E-Lücke nur
**verschoben**, nicht geschlossen — die in P0-E ergänzte eigene
Fallback-Liste in `_normalize_artist_for_comparison()` wäre durch den
jetzt immer erfolgreichen `artist_normalizer`-Zweig unerreichbar
geworden, ohne dass „- Topic" tatsächlich erkannt wird.

### 3b. Vollständiger Fix

`DuplicateDetector.__init__()` konstruiert jetzt zusätzlich einen echten
`ArtistProcessor` (denselben, den auch `EnhancedMetadataProcessor` nutzt —
gleiche Klasse, eigene Instanz mit demselben `ArtistNormalizer`).
`_normalize_artist_for_comparison()` ruft `ArtistProcessor.
clean_artist_before_normalization()` **vor** `ArtistNormalizer.normalize()`
— identisch zur Reihenfolge, die `ArtistProcessor.determine_best_artist()`
für die Metadaten-Pipeline verwendet. Die alte, in P0-E erweiterte
Fallback-Liste (Komma-Split + Suffix-Liste) bleibt als Notfall-Pfad
bestehen (nur erreichbar, falls `artist_processor` fehlt oder die
Normalisierung ausnahmsweise fehlschlägt) — bewusst nicht entfernt, um die
bisherige Fehlerresilienz nicht zu verlieren.

## 4. Audit

Alle `DuplicateDetector(...)`-Konstruktionsstellen im Repository geprüft:

| Datei | Kontext | Ergebnis |
|---|---|---|
| `handlers/menu/rich_menu_handler.py:227` | Echter Bot-Start | Funktioniert (reale `Config` liefert bereits `Path`-Objekte) |
| `handlers/duplicate_handler.py:259,293` | Tote Kompatibilitätsfunktionen (`find_duplicates`/`clear_duplicate_cache`, seit ARCH-018 Phase 2 bekannt unbenutzt) | Unverändert außerhalb des Scopes — nicht Teil dieses Fixes |
| 11 Test-Fixtures (`tests/test_duplicate_*.py`, `test_metadata_processor_happy_path.py`, `test_download_utils_playlist_cancellation.py`, `test_download_handler_playlist_duplicate_registration.py`) | Verschiedene `FakeConfig`-Varianten | Alle funktionieren nach dem `Path(...)`-Fix ohne Fixture-Änderung |

## 4a. Nachtrag während der Regression: Testisolations-Lücke live aufgetreten

Beim ersten vollständigen `-k duplicate`-Testlauf nach dem Fix schrieb ein
**bereits bestehender** Test (`test_duplicate_handler.py`, `raw_artist="A
Totally Different Artist"`) unbeabsichtigt einen neuen Eintrag in die
**echte** `mapping/case_preserve.yaml` (`git diff` zeigte eine zusätzliche
Zeile `a totally different artist: A Totally Different Artist`). Ursache:
alle neun `FakeConfig`-Testklassen, die `DuplicateDetector` konstruieren,
setzen kein `GENRE_MAPPING_DIR` — bislang folgenlos, weil
`DuplicateDetector.artist_normalizer` vor diesem Fix nie konstruiert
wurde. Jetzt fällt `ArtistNormalizer` bei `mapping_dir=None` intern auf das
echte, relative `mapping/`-Verzeichnis zurück (bekanntes ISOLATION-001-
Muster, siehe `conftest.py`) und kann darüber die echten Mapping-Dateien
beschreiben (z. B. den `case_preserve.yaml`-Auto-Save-Mechanismus für
kurze/All-Caps-Artist-Namen).

**Sofort behoben, bevor dieser Fund weiterverfolgt wurde:** versehentliche
Schreibung per `git checkout -- mapping/case_preserve.yaml` zurückgesetzt,
danach alle neun betroffenen `FakeConfig`-Klassen
(`tests/test_duplicate_detector_feat_ft_normalization.py`,
`tests/test_duplicate_detector_live_version_false_positive.py`,
`tests/test_duplicate_handler_telegram.py`, `tests/test_duplicate_handler.py`,
`tests/test_download_utils_playlist_cancellation.py`,
`tests/test_duplicate_title_quote_normalization.py`,
`tests/test_download_handler_playlist_duplicate_registration.py`,
`tests/test_duplicate_detector_hash_consistency.py`,
`tests/test_artist_normalization_duplicate_detector_comparison.py`) um
eine isolierte `GENRE_MAPPING_DIR`-Kopie ergänzt (analog zur bereits
etablierten `mapping_dir_copy`-Fixture in `conftest.py`, hier lokal
implementiert, um bestehende Fixture-Signaturen nicht anzufassen). Danach
verifiziert: `git status --short mapping/` bleibt nach jedem Testlauf leer.

## 5. Regression

- Vollständige Neubewertung von `tests/test_artist_normalization_
  duplicate_detector_comparison.py`: von „dokumentiert die Divergenz"
  (P0-E-Fassung) zu „beweist strukturelle Parität" (P1-Fassung) umgeschrieben
  — zwei unabhängig konstruierte `ArtistProcessor`-Instanzen (kein
  gemeinsamer Zustand) werden für dieselben Rohwerte verglichen, plus ein
  neuer Test, der die reale Bot-Start-Konstruktionsreihenfolge
  (`DuplicateDetector` zuerst) explizit nachbildet.
- Docstring-Korrekturen in `tests/test_duplicate_handler.py` und
  `tests/test_duplicate_detector_hash_consistency.py` (veraltete „self.
  artist_normalizer bleibt None"-Annahme entfernt) — keine
  Assertion-Änderung nötig, diese Tests waren bereits vorher unabhängig
  vom Normalisierungspfad korrekt.
- 2 neue End-to-End-Regressionstests (`TestEndToEndRegression`): der
  ursprüngliche P0-E-Music-Suffix-Fall sowie ein neuer Topic-Suffix-Fall
  (der Fall, an dem die Unvollständigkeit des ersten Fix-Versuchs konkret
  auffiel).

### Tests

- Gezielt: `tests/test_artist_normalization_duplicate_detector_comparison.py`
  — 11 passed (vorher 9).
- Direkte Regression: `tests/test_duplicate_handler.py` +
  `tests/test_duplicate_detector_hash_consistency.py` +
  `tests/test_metadata_processor_happy_path.py` +
  `tests/test_download_utils_playlist_cancellation.py` +
  `tests/test_download_handler_playlist_duplicate_registration.py` — alle
  grün.
- Thematisch: `pytest tests/ -q -k duplicate` — 303 passed, 1 skipped,
  `mapping/` nachweislich unverändert (`git status --short mapping/` leer).
- Vollständige Suite: **1698 passed, 0 failed, 1 skipped (umgebungsbedingt),
  19 subtests passed** — +2 gegenüber dem Stand nach P0-G (exakt die
  Nettozahl neuer Tests in der überarbeiteten Vergleichsdatei), keine
  Regression, `mapping/` erneut nachweislich unverändert.

## Ergebnis

Der in P0-E dokumentierte strukturelle Punkt „`ArtistProcessor` und
`DuplicateDetector` besitzen unabhängige Normalisierungslogik" ist damit
vollständig aufgelöst — beide nutzen jetzt denselben `ArtistProcessor`-Pfad
(`clean_artist_before_normalization()` + `ArtistNormalizer.normalize()`),
nicht nur zufällig übereinstimmende Einzelfälle. Die P0-E-Fallback-Liste
bleibt als zusätzliches Sicherheitsnetz bestehen, ist im Normalfall aber
nicht mehr der wirksame Pfad.
