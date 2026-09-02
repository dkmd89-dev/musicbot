# P0-Gesamt-Audit: Metadata / Genre / Artist-Mapping / Duplicate Detection

**Datum:** 2026-09-02
**Branch:** `audit/p0-metadata-duplicate-detection` (8 Commits, ein PR gegen
`main`, Merge erst nach diesem Gesamt-Audit)
**Scope:** die kompletten P0-Kernbereiche laut CLAUDE.md Abschnitt 3/5/15/16 —
`services/metadata/artist_processor.py`, `services/metadata/genre_processor.py`,
`mapping/artist_genre.yaml`, `services/duplicate/detector.py`,
`services/duplicate/cache.py`.

Dieses Dokument fasst die sechs Teilphasen (P0-A bis P0-F) zusammen und
trifft die Freeze-analoge Abschlussentscheidung für diesen Arbeitsblock.
Die einzelnen Teilaudits bleiben als Detail-Referenz bestehen:

- `docs/audits/P0_MAPPING_BASELINE_2026-09-02.md` (P0-A)
- P0-B: dokumentiert direkt in `tests/test_autolearn_special_channel_gate.py`
  (kein eigenes Audit-Dokument, siehe Commit `14f40b3`)
- `docs/audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md` (P0-C)
- `docs/audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md` (P0-D)
- `docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md` (P0-E)
- `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md` (P0-F)

## Zusammenfassung pro Phase

| Phase | Bereich | Ergebnis |
|---|---|---|
| P0-B | ARTISTNORM-001 (Artist-Mapping-Historie) | Kein offener Bug — bereits am 2026-08-18 gefixt (Commit `c47faed`), nur eine Testdokumentation war veraltet. Korrigiert + neuer E2E-Regressions-Tripwire. |
| P0-A | `artist_genre.yaml`-Baseline | Strukturell/inhaltlich sauber (0 Kollisionen, 0 Inkonsistenzen, 0 Fehlzuordnungen in 18 Stichproben). Bonus-Fund: 18 tote Channel-Suffix-Einträge identifiziert, dokumentiert und (nach Freigabe) entfernt. |
| P0-C | `genre_processor.py` | Bereits durch ARCH-012/013/014 gründlich abgesichert. Drei echte Testlücken geschlossen (Channel-Pfad E2E, mb_ids-Anhängung an manuelles Genre, Feature-Artist-Tie-Breaking-Reihenfolge). Keine Produktionscode-Änderung. |
| P0-D | `artist_processor.py` | Kernlogik korrekt wie dokumentiert. Zwei Funde (totes Public-API `find_known_artist_from_list()`, struktureller toter Redundanz-Check in der Prioritätskette) — beide dokumentiert, bewusst nicht gefixt (kein Bug, kein Verhaltensrisiko). |
| P0-E | `detector.py` (Artist-Normalisierungs-Vergleich) | **Konkreter, bewiesener Bug**: False Negative in der Duplicate-Detection durch unvollständige, unabhängige Artist-Normalisierung (`DuplicateDetector.artist_normalizer` in Produktion immer `None`). Gefixt: Komma-Split + „Music“/„Records“-Suffixe ergänzt. |
| P0-F | `cache.py` (URL-Normalisierung) | **Konkreter, bewiesener Bug**: `youtube.com/shorts/<id>` wurde nicht als dieselbe Video-ID wie `watch?v=<id>` erkannt. Gefixt. Zwei kleinere Statistik-Inkonsistenzen (`duplicate_count`) dokumentiert, nicht gefixt. |

## Bilanz

- **2 konkrete, live reproduzierte P0-Bugs gefunden und gefixt** (P0-E, P0-F)
  — beide mit Pre-Fix-Diskriminierung (Test schlägt nachweislich am
  ungefixten Code fehl, danach grün).
- **1 historischer Bug bestätigt bereits behoben** (P0-B) — Dokumentation
  korrigiert, damit er in künftigen Audits nicht erneut fälschlich als
  offen auftaucht.
- **1 Mapping-Aufräumfund umgesetzt** (P0-A, 18 tote Einträge, nach
  expliziter Freigabe).
- **3 Dokumentations-/Struktur-Funde ohne Code-Änderung** (P0-C-Testlücken
  geschlossen; P0-D totes API + toter Redundanz-Check dokumentiert, bewusst
  nicht angefasst; P0-F Statistik-Inkonsistenzen dokumentiert).
- **0 unentdeckte Regressionen**: jede Phase einzeln mit gezielten +
  direkten Regressionstests abgesichert, dieser Gesamtlauf bestätigt es
  über die volle Suite.

Der ursprünglich als „interessantester struktureller Punkt“ vermutete
Befund — unabhängige Normalisierungslogik zwischen `ArtistProcessor` und
`DuplicateDetector` — hat sich in P0-E als der **schwerwiegendste
tatsächliche Fund der gesamten P0-Phase** bestätigt: ein echter,
reproduzierbarer False Negative in einem P0-Kernbereich (Duplicate
Detection), nicht nur eine theoretische Doppelstruktur.

## Testergebnis (Abschlusslauf, Abschnitt 8.A Punkt 4)

```
python3 -m pytest tests/ -q
1696 passed, 1 skipped, 3 warnings, 19 subtests passed in 110.71s
```

- **0 failed.**
- 1 skipped: umgebungsbedingt, identisch zum eingefrorenen Stand in
  `docs/MusicBot_ENGINEERING_BASELINE_v7.md` (1673 passed / 0 failed / 1
  skipped, 2026-09-01) — kein neuer Skip durch diese Phase.
- 1696 − 1673 = 23 neue/geänderte Tests über die gesamte P0-Phase (P0-B: 1,
  P0-C: 4, P0-D: 1, P0-E: 9, P0-F: 3 — Rest durch kleinere Ergänzungen
  innerhalb bestehender Testklassen).
- Keine durch diese Phase verursachten, keine unabhängigen, keine
  vorbestehenden Fehlschläge im Abschlusslauf.

## Geänderte Produktionsdateien (Gesamtdiff dieses Branches)

```
mapping/artist_genre.yaml                    (P0-A, 18 tote Eintraege entfernt)
services/duplicate/detector.py               (P0-E, Normalisierungs-Fix)
services/duplicate/cache.py                  (P0-F, Shorts-URL-Fix)
```

Keine Änderung an `services/metadata/genre_processor.py` oder
`services/metadata/artist_processor.py` selbst — beide waren bei
genauerer Prüfung bereits korrekt; nur ihre Testabdeckung wurde erweitert.

## Freeze-analoge Abschlussentscheidung

**🟢 Dieser P0-Arbeitsblock ist abgeschlossen und bereit für Merge.**

Begründung:
- Beide gefundenen Bugs sind gefixt, mit Pre-Fix-Diskriminierung belegt
  und regressionsgetestet.
- Kein offener P0/P1-Befund aus dieser Phase — alle dokumentierten
  Nebenfunde (totes API, toter Redundanz-Check, Statistik-Inkonsistenzen)
  sind explizit als „kein Korrektheitsrisiko“ eingestuft und bewusst
  zurückgestellt, nicht übersehen.
- Vollständige Testsuite grün, keine Regression gegenüber der
  eingefrorenen Baseline v7.
- Mapping-Änderung (P0-A) erfolgte nach CLAUDE.md Abschnitt 10/28 mit
  konkreten Vorher/Nachher-Beispielen und expliziter Freigabe.

## Offene Punkte für spätere, separate Entscheidungen (nicht Teil dieses PRs)

- `find_known_artist_from_list()` (P0-D): totes Public-API, Löschung als
  eigener Cleanup-Commit möglich.
- Toter Redundanz-Check in `determine_best_artist()` (P0-D): Entfernung
  als eigener Refactor-Schritt möglich (kein funktionales Risiko).
- `artist_config`/`ArtistNormalizer`-Verdrahtung in `DuplicateDetector`
  (P0-E): architektonisch sauberere Lösung wäre die Wiederverwendung des
  echten, geteilten `ArtistNormalizer` statt der parallelen String-Liste —
  größerer, eigener Migrationsschritt.
- `duplicate_count`-Statistik-Inkonsistenzen (P0-F): Vereinheitlichung
  möglich, falls die Genauigkeit dieser Zahl für den Nutzer relevant wird.
- `/embed/`, `/live/`-URL-Normalisierung (P0-F): nur bei nachgewiesenem
  Bedarf nachziehen.
