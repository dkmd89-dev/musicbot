# P0-E: Duplicate Detector (`services/duplicate/detector.py`)

**Datum:** 2026-09-02
**Phase:** P0-E der laufenden P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Reihe
(Branch `audit/p0-metadata-duplicate-detection`).
**Scope:** `services/duplicate/detector.py` (`DuplicateDetector`, 395 Zeilen,
vollständig gelesen), im direkten Vergleich mit
`services/metadata/artist_processor.py` (`ArtistProcessor`) — der seit
Beginn der P0-Phase zurückgestellte strukturelle Punkt.

## Zusammenfassung

**Konkreter, live reproduzierter Bug gefunden:** ein False Negative in der
Duplicate-Detection, verursacht durch eine unvollständige, unabhängige
Artist-Normalisierung in `DuplicateDetector`. Noch **kein Fix** in diesem
Schritt umgesetzt (Commit 4 des vereinbarten P0-Plans: „test: compare
artist normalization with duplicate normalization“) — Fix folgt gemäß Plan
nur nach expliziter Freigabe als eigener Commit 5.

## 1. Grundursache: `DuplicateDetector.artist_normalizer` ist in Produktion immer `None`

```python
self.artist_normalizer = (
    ArtistNormalizer(artist_config=getattr(self.config, "artist_config", None))
    if hasattr(self.config, "artist_config")
    else None
)
```

- `config.Config` (die echte, produktiv verwendete Konfigurationsklasse)
  besitzt **nirgends im Repository** ein `artist_config`-Attribut
  (verifiziert per repoweitem `grep`) — `hasattr(self.config,
  "artist_config")` ist in der Produktion immer `False`.
- **Folge:** `self.artist_normalizer` ist in jeder real laufenden
  `DuplicateDetector`-Instanz immer `None`. Das war bereits vor P0-E
  bekannt und dokumentiert (`tests/test_duplicate_detector_hash_
  consistency.py`, Docstring-Verweis „kein artist_config -> self.
  artist_normalizer bleibt None, reine String-basierte Normalisierung wird
  charakterisiert“) — P0-E bestätigt das erneut live und zieht die bisher
  nicht gezogene Konsequenz für die eigentliche Normalisierungsqualität.
- **Bonus-Fund (aktuell nicht erreichbar, aber real defekt):** selbst wenn
  `artist_config` gesetzt würde, wäre der Konstruktor-Aufruf selbst
  fehlerhaft — `ArtistNormalizer._do_init()` erwartet das Keyword `config`,
  nicht `artist_config` (`utils/artist_map.py:182`). Das fällt aktuell nie
  auf, weil (a) der Zweig nie erreicht wird und (b) `ArtistNormalizer` ein
  `SingletonMixin` ist — ein späterer Fehlaufruf mit falschem Keyword auf
  eine bereits andernorts korrekt konstruierte Instanz wird von
  `SingletonMixin.__init__()` stillschweigend ignoriert (nur der *erste*
  Konstruktions-Aufruf führt `_do_init()` überhaupt aus). Nicht Teil des
  vorgeschlagenen Fixes unten (separates, unabhängiges Detail), aber der
  Vollständigkeit halber dokumentiert.

## 2. Praktische Konsequenz: eigene, unvollständige Fallback-Normalisierung

Weil `self.artist_normalizer` immer `None` ist, verwendet
`_normalize_artist_for_comparison()` **immer** ihren eigenen, kurzen
String-Fallback:

```python
cleaned = artist.strip()
for suffix in [" - Topic", " VEVO", " Official"]:
    if cleaned.endswith(suffix):
        cleaned = cleaned[: -len(suffix)].strip()
return cleaned if cleaned else "Unknown"
```

Verglichen mit dem, was `ArtistProcessor.clean_artist_before_
normalization()` (der von der Metadaten-Pipeline für denselben Rohwert
verwendete, kanonische Pfad) für denselben Rohwert liefert:

| Rohwert | `DuplicateDetector` | `ArtistProcessor`-Pfad | Übereinstimmung |
|---|---|---|---|
| `"Kygo - Topic"` | `Kygo` | `Kygo` | ✅ |
| `"Kygo VEVO"` | `Kygo` | `Kygo` | ✅ |
| `"Kygo Official"` | `Kygo` | `Kygo` | ✅ |
| `"SomeArtist Music"` | `SomeArtist Music` (unverändert) | `Someartist` | ❌ **Divergenz** |
| `"SomeArtist Records"` | `SomeArtist Records` (unverändert) | `Someartist` | ❌ **Divergenz** |
| `"Artist One, Artist Two"` | `Artist One, Artist Two` (unverändert) | `Artist One` | ❌ **Divergenz** |

Ursache der Divergenzen: `ArtistProcessor.clean_artist_before_
normalization()` entfernt zusätzlich die Suffixe „Music“/„Records“ (Regex)
und nimmt bei kommagetrennten Multi-Artist-Strings nur den ersten Namen
— beides fehlt in `DuplicateDetector`s eigener, kurzer Liste vollständig.

## 3. Live reproduzierter End-to-End-Bug: False Negative

Realistischer Ablauf (entspricht exakt dem echten Aufrufmuster in
`klassen/download_handler.py`):

1. `register_download()` wird nach einem erfolgreichen Download mit dem
   bereits durch die Metadaten-Pipeline bereinigten Artist aufgerufen
   (`handle_single_track_success()`: `artist = result.get("artist")` —
   das ist `MetadataResult.artist`, also bereits das Ergebnis von
   `ArtistProcessor.determine_best_artist()`). Beispiel: `"Someartist"`.
2. Ein späterer Re-Upload/erneuter Download-Versuch desselben Songs läuft
   zunächst durch den **Pre-Download-Check**
   (`_probe_artist_title_for_duplicate_check()` → `check_for_duplicates()`),
   der den **rohen** YouTube-Uploader-/Channel-Namen verwendet — noch
   *bevor* die Metadaten-Pipeline überhaupt läuft. Beispiel:
   `"SomeArtist Music"` (ein plausibler, realer YouTube-Kanalname-Stil für
   Label-/Artist-Kanäle).

Live reproduziert (`tests/test_artist_normalization_duplicate_detector_
comparison.py::TestEndToEndFalseNegative`): der Content-Hash für
`"someartist music"::"cool song"` stimmt nicht mit dem gespeicherten Hash
für `"someartist"::"cool song"` überein → `check_for_duplicates()` liefert
`is_dup=False, reason="none"` — der Re-Upload wird **nicht** als Duplikat
erkannt, obwohl es sich um exakt denselben Song handelt.

## 4. Vorgeschlagener Fix (noch NICHT umgesetzt — wartet auf Freigabe)

Minimal-invasiv, im Sinne von CLAUDE.md Regel 1/18 (kein großer Refactor,
kleinster sinnvoller Schritt): `DuplicateDetector._normalize_artist_for_
comparison()`s eigene Fallback-Liste um die fehlenden Fälle erweitern,
**ohne** die tiefere Architekturfrage (soll `DuplicateDetector` stattdessen
den echten, geteilten `ArtistNormalizer`/`ArtistProcessor`-Pfad nutzen?) in
diesem Schritt anzufassen:

- Suffixe `" Music"` und `" Records"` zur bestehenden Liste hinzufügen
  (analog zu `clean_artist_before_normalization()`s Regex-Patterns).
- Komma-Split für kommagetrennte Multi-Artist-Strings ergänzen (erster
  Name gewinnt, analog zu `clean_artist_before_normalization()`).

**Nicht vorgeschlagen** (bewusst außerhalb des Scopes dieses Fixes): die
`artist_config`/`ArtistNormalizer`-Verdrahtung reparieren, damit
`DuplicateDetector` den echten geteilten Normalizer nutzt. Das wäre die
architektonisch sauberere Lösung (eliminiert die parallele Logik
vollständig statt sie nur nachzuziehen), aber ein größerer, risikoreicherer
Eingriff (Konstruktor-Verhalten, Singleton-Interaktion, Config-Erweiterung)
— passend für eine spätere, eigene Entscheidung, nicht für den
„kleinsten sinnvollen Schritt“ dieses P0-Fixes.

**Umgesetzt** (Freigabe erteilt, separater Folge-Commit „fix: resolve
duplicate detector artist normalization gap (P0-E)“): `_normalize_artist_
for_comparison()` um den Komma-Split (1:1 aus `clean_artist_before_
normalization()` übernommen) sowie die Suffixe `" Music"`/`" Records"`
erweitert — exakt der oben vorgeschlagene Minimal-Fix, keine
Architekturänderung an der `artist_config`/`ArtistNormalizer`-Verdrahtung.

**Pre-Fix-Diskriminierung:** die 3 divergenten Vergleichstests und der
End-to-End-Test wurden vor dem Fix auf die gewünschte (korrekte)
Erwartung umgestellt und liefen damit nachweislich gegen den ungefixten
Code fehl (4 failed) — danach mit dem Fix erneut ausgeführt: alle 9 Tests
grün.

## Tests

- Neu: `tests/test_artist_normalization_duplicate_detector_comparison.py`
  (9 Tests: Grundlagen-Beweis `artist_normalizer is None` in Produktion,
  3 übereinstimmende Suffix-Fälle als Gegenprobe, 3 Divergenz-/jetzt-
  Übereinstimmungs-Fälle, 1 End-to-End-False-Negative-Regressionstest).
  Vor dem Fix charakterisierten 4 dieser Tests bewusst den fehlerhaften
  Zustand; nach Freigabe auf die korrekte Erwartung umgestellt und als
  Pre-Fix-Diskriminierung gegen den ungefixten Code laufen lassen (4
  failed, wie erwartet) — nach dem Fix: 9 passed.
- Gezielt (direkte Regression): `tests/test_duplicate_detector_hash_
  consistency.py` + `tests/test_duplicate_handler.py` — 19 passed.
- Thematisch: `pytest tests/ -q -k duplicate` — 298 passed, 1 skipped
  (umgebungsbedingt, vorbestehend), keine Regression (identische Zahl vor
  und nach dem Fix).
- Produktionscode-Änderung: `services/duplicate/detector.py::
  _normalize_artist_for_comparison()` (siehe Abschnitt 4).

## Sonstige Beobachtungen (keine weiteren Funde)

- `check_for_duplicates()`-Kaskade (URL → Content → Parsed-Content →
  Library-Fallback) verhält sich exakt wie im Modul-Docstring/CLAUDE.md
  Abschnitt 5 beschrieben — keine Abweichung gefunden.
- `_clean_title_for_comparison()` (Phase-2.2-Anführungszeichen-Parität,
  DUP-04-Featuring-Erkennung) bereits gründlich in früheren Phasen
  charakterisiert — keine neuen Funde in diesem Schritt.
- `register_download()`/`check_for_duplicates()`-Hash-Konsistenz (DUP-02)
  bereits gefixt und getestet (`tests/test_duplicate_detector_hash_
  consistency.py`) — durch P0-E nicht berührt.
