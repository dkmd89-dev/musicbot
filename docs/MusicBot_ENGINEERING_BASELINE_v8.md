# MusicBot Engineering Baseline v8

> Nächster verifizierter Engineering-Referenzzustand nach 4 PRs (#99–#102):
> ein kleiner P3-Dead-Code-Cleanup (#99), gefolgt vom ersten vollständigen
> P0-Kernbereichs-Audit dieser Baseline-Serie — Metadata/Genre/Artist-
> Mapping/Duplicate-Detection (#100, sechs Teilphasen P0-A–F + Gesamtaudit),
> ein kleiner Follow-up-Cleanup (#101, P0-G) sowie ein eigenständiges
> P1-Architekturprojekt, das die Ursache eines in P0-E gefundenen Bugs
> behob (#102). Anders als die überwiegend bereits bekannten Findings in
> v7 war dies die erste Serie dieser Baseline-Linie, die gezielt bisher
> **nie im Detail geprüfte** fachliche Kernlogik (Genre-Fallback-Kaskade,
> Artist-Prioritätskette, Duplicate-Detection-Normalisierung) untersuchte
> und dabei zwei konkrete, live reproduzierte P0-Bugs fand und behob.
> `docs/MusicBot_ENGINEERING_BASELINE_v7.md` wird durch dieses Dokument
> abgelöst und liegt jetzt unter
> `docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md`.

---

## 1. Baseline Metadata

| Feld | Wert |
|---|---|
| Datum | 2026-09-02 |
| Vorherige Baseline | `docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md` (1673 passed / 0 failed, eingefroren 2026-09-01, PR #98) |
| Herleitung | 4 PRs (#99–#102), siehe Abschnitt 4 |
| HEAD | `7ae014d94665f8f3a0e570053d51fe7a22daff28` |
| Test-Kommando | `python3 -m pytest tests/ -q` |
| Testergebnis | **1698 passed, 1 skipped, 0 failed**, 19 subtests passed |
| Python-Version | 3.12.3 |

---

## 2. Executive Summary

Zwischen dem v7-Freeze (PR #98) und heute wurden **4 PRs gemergt**
(#99–#102), die Testsuite wuchs von 1673 auf **1698 passed** (+25, +1,5 %),
durchgehend 0 failed. Der eigentliche Schwerpunkt dieser Serie war ein
vollständiger P0-Kernbereichs-Audit (CLAUDE.md Abschnitt 3: „Metadata,
Artist, Genre, Duplicate Detection … besonders geschützt") in sechs
Teilphasen (P0-A Mapping-Baseline, P0-B ARTISTNORM-001-Verifikation,
P0-C Genre-Charakterisierung, P0-D Artist-Prioritätsketten-Audit, P0-E
Duplicate-Detector-Normalisierungsvergleich, P0-F Duplicate-Cache-
URL-Normalisierung), plus ein kleiner P0-G-Nachtrag und ein eigenständiges
P1-Architekturprojekt.

**Zwei konkrete, live reproduzierte P0-Bugs gefunden und gefixt:**

1. **False Negative in der Duplicate-Detection** (P0-E): `DuplicateDetector`
   normalisierte Artist-Namen über eine eigene, unvollständige String-Liste
   statt über den echten, von der Metadaten-Pipeline genutzten
   `ArtistNormalizer`/`ArtistProcessor`-Pfad — ein Re-Upload desselben
   Songs über einen Kanal wie „Artist Music" wurde nicht als Duplikat
   erkannt.
2. **YouTube-Shorts-URLs wurden nicht als Duplikat erkannt** (P0-F):
   `DuplicateCache._normalize_url_for_cache()` kannte `watch?v=<id>` und
   `youtu.be/<id>`, aber nicht `youtube.com/shorts/<id>` als dieselbe
   Video-ID.

**Ein historischer Bug bestätigt bereits behoben** (P0-B): das oft
zitierte „ARTISTNORM-001" existierte nicht mehr im Code (Fix bereits am
2026-08-18 gelandet), nur eine Testdokumentation war veraltet — korrigiert,
damit er in künftigen Audits nicht erneut fälschlich als offen auftaucht.

**Ein eigenständiges P1-Architekturprojekt** (#102) behob die in P0-E
zurückgestellte Ursache vollständig: `DuplicateDetector` konstruiert jetzt
denselben `ArtistConfig`/`ArtistNormalizer` wie `EnhancedMetadataProcessor`
und hält zusätzlich einen echten `ArtistProcessor`, dessen
`clean_artist_before_normalization()` vor jeder Normalisierung läuft —
beide Aufrufer nutzen jetzt strukturell denselben Pfad, nicht nur
zufällig übereinstimmende Einzelfälle. Während der Extract-Phase wurde
außerdem ein bislang unbekannter Fakt zur echten Bot-Start-Reihenfolge
aufgedeckt: `DuplicateDetector` wird **vor** `EnhancedMetadataProcessor`
konstruiert, ist also der tatsächliche „First Mover" des
`ArtistNormalizer`-Singletons.

**Zusätzlich P3-Dead-Code-Cleanup** (#99, vor dem P0-Audit): 283 Zeilen
totes `ErrorHandlerIntegration`-Muster entfernt (0 Aufrufer), `klassen/`-
Schicht in `CLAUDE.md` dokumentiert. Und **P0-G**: zwei weitere,
vollständig bewiesene Dead-Code-Funde aus dem P0-D-Audit entfernt
(`find_known_artist_from_list()`, toter Redundanz-Check in
`determine_best_artist()`).

**Ein Nebenfund während der P1-Regression** ist bemerkenswert genug für
eine eigene Erwähnung: ein bereits bestehender Test schrieb — erst durch
den P1-Fix überhaupt reaktiviert — unbeabsichtigt einen Testartefakt in
die echte `mapping/case_preserve.yaml` (Testisolationslücke, bekanntes
ISOLATION-001-Muster). Sofort erkannt, zurückgesetzt und in allen neun
betroffenen Testdateien behoben, bevor der PR gemergt wurde.

Kein offenes P0/P1-Finding am Ende dieser Serie.

---

## 3. Geschlossene Findings (seit v7)

| Finding | PR | Kernaussage |
|---|---|---|
| Totes `ErrorHandlerIntegration`-Muster | #99 | 283 Zeilen (`ErrorHandlerIntegration`-Klasse + 2 Factory-Funktionen) in `handlers/enhanced_error_handler.py`, 0 Aufrufer/0 Tests verifiziert, entfernt. `klassen/`-Schicht (bisher undokumentierte historisch gewachsene Ausnahme) in `CLAUDE.md` Abschnitt 4 ergänzt. Ergebnis eines vorausgehenden forensischen Architektur-Status-Audits: „Architektur ist stabil genug". |
| **P0-A** Mapping-Baseline `artist_genre.yaml` | #100 | 172 manuelle Einträge strukturell/inhaltlich sauber (0 Kollisionen mit `auto_learned_genre.yaml`, 0 Inkonsistenzen, 0 Fehlzuordnungen in 18 Stichproben). Bonus-Fund: 18 tote YouTube-Kanal-Suffix-Einträge (`kygo - topic`, `eminem vevo` u. Ä.) identifiziert und entfernt (172→154) — strukturell unerreichbar, da bereits der exakte Match auf den jeweiligen Basis-Key vor dem Fuzzy-Fallback greift. |
| **P0-B** ARTISTNORM-001 | #100 | Kein offener Bug — live reproduziert und bestätigt bereits am 2026-08-18 gefixt (Commit `c47faed`, 20 Minuten nach dem ursprünglichen Fund). Nur ein Testkommentar war veraltet, jetzt korrigiert mit „HISTORISCHER BEFUND – BEREITS BEHOBEN"-Vermerk + neuem E2E-Regressions-Tripwire. |
| **P0-C** Genre-Fallback-Charakterisierung | #100 | `genre_processor.py` bereits durch frühere ARCH-Phasen (012/013/014) gründlich abgesichert. 3 echte Testlücken geschlossen (Channel-Pfad nie End-to-End getestet, MB-IDs-Anhängung an manuelles Genre nie geprüft, Feature-Artist-Tie-Breaking-Reihenfolge ungetestet) — keine Produktionscode-Änderung, alles bereits korrekt. |
| **P0-D** Artist-Prioritätsketten-Audit | #100 | `artist_processor.py` Kernlogik korrekt wie dokumentiert. Zwei Funde dokumentiert (totes Public-API `find_known_artist_from_list()`, struktureller toter Redundanz-Check in der Prioritätskette) — in diesem Schritt bewusst nicht gefixt, siehe P0-G. |
| **P0-E** Duplicate-Detector-Normalisierungslücke | #100 | **Konkreter False-Negative-Bug**: `DuplicateDetector.artist_normalizer` war in Produktion immer `None` (defekte `hasattr(config, "artist_config")`-Prüfung seit dem allerersten Commit) — eigene String-Fallback-Liste unvollständig gegenüber `ArtistProcessor` (fehlender Komma-Split, fehlende „Music"/„Records"-Suffixe). Sofortmaßnahme: Fallback-Liste erweitert. Architektonische Ursache siehe P1 (#102). |
| **P0-F** Duplicate-Cache-URL-Normalisierung | #100 | **Konkreter Bug**: `youtube.com/shorts/<id>` wurde nicht als dieselbe Video-ID wie `watch?v=<id>` erkannt — neuer `elif`-Zweig ergänzt. `/embed/`, `/live/` bewusst nicht mitgefixt (keine Evidenz für reale Nutzung). |
| **P0-Gesamtaudit** | #100 | Zusammenfassung aller sechs Teilphasen, Freeze-analoge Abschlussentscheidung „bereit für Merge", vollständige Suite grün. |
| **P0-G** Dead-Code-Cleanup (`artist_processor.py`) | #101 | `find_known_artist_from_list()` (+ Facade-Wrapper) entfernt (0 Aufrufer seit Tag 1). Toter Redundanz-Check in `determine_best_artist()` entfernt (strukturell nie erreichbar, siehe P0-D) — reine Vereinfachung, abgesichert durch bestehenden Characterization-Test. |
| **P1** `DuplicateDetector` ↔ `ArtistNormalizer`-Verdrahtung | #102 | Architektonische Ursache von P0-E vollständig behoben. Methodik Characterize→Decide→Extract→Audit→Regression. Charakterisierungs-Fund: `DuplicateDetector` wird im echten Bot-Start **vor** `EnhancedMetadataProcessor` konstruiert. Fix: echter `ArtistProcessor` (nicht nur `ArtistNormalizer`) verdrahtet, `clean_artist_before_normalization()` läuft vor `normalize()`. Nebenfund während der Regression: Testisolationslücke (9 Testdateien) live entdeckt und behoben, bevor gemergt wurde. |

Vollständige Analyse je Fund: siehe die referenzierten Audit-Dokumente
in `docs/audits/` (Abschnitt 4) sowie die jeweiligen PR-Beschreibungen.

---

## 4. Seit v7 gemergte PRs (#99–#102)

| PR | Datum (2026-09-02) | Titel | Audit-Dokument(e) |
|---|---|---|---|
| #99 | 00:19 | Totes `ErrorHandlerIntegration`-Muster entfernt, `klassen/`-Schicht dokumentiert | — |
| #100 | 02:17 | P0-Metadata/Genre/Artist-Mapping/Duplicate-Detection-Audit (P0-A–F + Gesamtaudit) | `docs/audits/P0_MAPPING_BASELINE_2026-09-02.md`, `docs/audits/P0_GENRE_CHARACTERIZATION_2026-09-02.md`, `docs/audits/P0_ARTIST_PROCESSOR_AUDIT_2026-09-02.md`, `docs/audits/P0_DUPLICATE_DETECTOR_AUDIT_2026-09-02.md`, `docs/audits/P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md`, `docs/audits/P0_METADATA_DUPLICATE_GESAMTAUDIT_2026-09-02.md` (P0-B ohne eigenes Dokument, direkt in `tests/test_autolearn_special_channel_gate.py` dokumentiert) |
| #101 | 02:37 | P0-G Dead-Code-Cleanup (`artist_processor.py`) | — (Befund bereits in P0-D-Audit dokumentiert) |
| #102 | 03:10 | P1 `DuplicateDetector`/`ArtistNormalizer`-Verdrahtung | `docs/audits/P1_DUPLICATE_DETECTOR_ARTIST_NORMALIZER_WIRING_2026-09-02.md` |

Testzuwachs je Phase: 1673 (v7) → 1674 (+1, P0-B E2E-Tripwire) → 1678
(+4, P0-C) → 1679 (+1, P0-D) → 1688 (+9, P0-E) → 1691 (+3, P0-F) = 1696
nach PR #100 → 1696 (±0, P0-G — reine Löschung, kein neuer Test) nach
PR #101 → 1698 (+2, P1-Vergleichsdatei erweitert) nach PR #102 = **1698**,
exakt reproduziert.

---

## 5. Aktueller Architekturzustand

Unverändert gegenüber v7 in Bezug auf Layer-Grenzen — **eine neue,
verifizierte Abhängigkeit innerhalb von `services/`**: `services/duplicate/
detector.py` importiert jetzt `services/metadata/artist_processor.py`
(P1, #102). Beide Module liegen unter `services/` (horizontale
Peer-Beziehung, keine Schichtgrenzen-Verletzung laut `CLAUDE.md`
Abschnitt 4); Zyklus-Check bestätigt 0 Treffer für den Rückweg
(`services/metadata/` importiert nirgends aus `services/duplicate/`).

Keine neue ARCH-Phase begonnen. Diese Serie war fachlicher Natur
(P0-Kernbereichs-Audit), nicht strukturell — die einzige strukturelle
Änderung (P1) ist eine gezielte, kleine Dependency-Injection-Korrektur
innerhalb bestehender Grenzen, keine neue Abstraktionsschicht.

---

## 6. Bewusst akzeptierte Risiken / Entscheidungen (bestätigt seit v7)

Alle in v7 (Abschnitt 6) gelisteten Punkte bleiben unverändert und wurden
in dieser Serie nicht berührt: `duplicate/cache.py` INV-01 (synchrone
Filesystem-Persistenz), `download_executor.py`-Cancellation-Cleanup,
`mugge_statistik_handler.py` ohne `error_handler`,
`YoutubeDownloader.download_audio(None)` → `AttributeError`,
`FormatNotAvailableError`/`PermissionError` unbenutzt,
`FileProcessingError` unklassifiziert, `CoverProcessor`/`DownloadExecutor`
außerhalb `services/clients/` (MIG-04), fehlende Layer-Boundary-Tests
(MIG-06), DUP-05 (Check-then-Register-Race).

**Eine Zeile der v7-Liste ist jetzt teilweise überholt:** die „15
Delegate-Methoden (`EnhancedMetadataProcessor`, 0 Aufrufer repoweit)"
enthielten `_find_known_artist_from_list()` — dieser einzelne Delegat
wurde im P0-D-Audit unabhängig neu gefunden (nicht aus der v7-Liste
übernommen) und in P0-G entfernt. Die übrigen 14 bleiben unverändert
bestehen (dokumentierte Kompatibilitätsschicht, nicht ohne dedizierten
Auftrag entfernt).

**Zwei neue, bewusst zurückgestellte Punkte** (P0-F, `docs/audits/
P0_DUPLICATE_CACHE_AUDIT_2026-09-02.md`):

- **`duplicate_count`-Statistik-Asymmetrie**: `check_url_duplicate()`
  erhöht den Zähler ohne anschließendes `_save_caches()`,
  `check_content_duplicate()` erhöht ihn gar nicht. Betrifft nur die
  Genauigkeit einer intern gehaltenen Zahl (nirgends im Code gelesen/
  angezeigt, verifiziert) — kein Korrektheitsrisiko, kein Fix ohne
  belegten Verwendungszweck.
- **`/embed/`, `/live/`-URL-Normalisierung** in `DuplicateCache`: analog
  zum P0-F-Shorts-Fix denkbar, aber ohne Evidenz für reale Nutzung als
  manuell geteilter Telegram-Link — nur bei Bedarf nachziehen.

---

## 7. Aktuelle Security-Baseline

Unverändert seit v7 — keine neuen Security-Findings in dieser Serie
(Fokus lag auf Metadata-/Duplicate-Detection-Fachlogik, nicht auf
Credentials/Logging).

---

## 8. Aktuelle Technical Debt

| ID | Problem | Status | Priorität |
|---|---|---|---|
| `duplicate/cache.py` INV-01 | Bewusst nicht async, 3 Optionen bewertet | DEFER (unverändert seit v7) | P2 |
| `download_executor.py::download_single_track()` Cancellation-Cleanup | Verwaiste Teildatei bei Task-Cancellation | DEFER (unverändert seit v7) | P2 |
| `mugge_statistik_handler.py` | Kein `error_handler` (struktureller UX-Konflikt) | zurückgestellt (unverändert seit v7) | — |
| `YoutubeDownloader.download_audio(None)` | `AttributeError` statt sauberem Fehler-Dict | charakterisiert, nicht gefixt (unverändert seit v7) | P3 |
| `FormatNotAvailableError`/`PermissionError` (Downloader) | Korrekt verdrahtet, aber ungenutzt | kein Fehlerfluss belegt (unverändert seit v7) | — |
| `FileProcessingError` (Downloader) | Nicht klassifiziert | mangels Beleg zurückgestellt (unverändert seit v7) | — |
| 14 Delegate-Methoden (`EnhancedMetadataProcessor`) | 0 Aufrufer repoweit | dokumentierte Kompatibilitätsschicht (15→14, siehe Abschnitt 6) | P3 |
| `CoverProcessor`/`DownloadExecutor` außerhalb `services/clients/` | Konventions-Inkonsistenz (MIG-04) | nicht umgesetzt (unverändert seit v7) | P3 |
| Fehlende Layer-Boundary-Tests (MIG-06) | Boundary aktuell sauber, aber ungeschützt gegen Regression | nicht umgesetzt (unverändert seit v7) | P3 |
| DUP-05 | Check-then-Register-Race ohne Lock | bewusst akzeptiertes Risiko (unverändert seit v7) | P1 (akzeptiert) |
| `duplicate_count`-Statistik-Asymmetrie | Zähler inkonsistent erhöht/gespeichert | neu (P0-F), kein Korrektheitsrisiko, kein Konsument | P3 |
| `/embed/`/`/live/`-URL-Normalisierung (`DuplicateCache`) | Nicht auf dieselbe Video-ID normalisiert | neu (P0-F), keine Nutzungsevidenz | P3 |

---

## 9. Neue offene Risiken

Keine neuen P0/P1-Risiken am Ende dieser Serie — beide gefundenen P0-Bugs
(P0-E, P0-F) sind gefixt und mit Pre-Fix-Diskriminierung belegt. Die zwei
neuen P3-Funde (Abschnitt 8) sind bewusst zurückgestellte
Statistik-/Randfall-Themen ohne belegte reale Auswirkung.

---

## 10. Regressionsergebnis

```text
python3 -m pytest tests/ -q
1698 passed, 1 skipped, 19 subtests passed
```

1673 (v7) + 25 = 1698 — Zuwachs vollständig durch die 4 gemergten PRs
seit v7 erklärt (siehe Abschnitt 4 für die Aufschlüsselung je Phase),
keine unerklärte Differenz. Der eine Skip ist weiterhin umgebungsbedingt
(`tests/test_resolve_duplicates.py`, reale Badchieff-Testdaten nicht
vorhanden) — unverändert seit v5/v6/v7, kein neuer Skip.

Kein einziger Schritt dieser Serie hat einen vorher bestandenen Test
zum Fehlschlagen gebracht (abgesehen von bewusster Pre-Fix-
Diskriminierung während P0-E/P0-F/P1, jeweils vor dem zugehörigen Fix
dokumentiert und danach grün).

---

## 11. Definition of Baseline

> Dieses Dokument repräsentiert den nächsten verifizierten
> Engineering-Referenzzustand von MusicBot nach dem ersten vollständigen
> P0-Kernbereichs-Audit dieser Baseline-Serie (Metadata/Genre/Artist-
> Mapping/Duplicate Detection) inklusive eines eigenständigen
> P1-Architekturprojekts zur Behebung der dabei gefundenen Ursache.

Bei Widersprüchen zwischen diesem Dokument und älteren Dokumenten gilt
weiterhin: aktueller Code > tatsächlich ausgeführte Tests > aktuelle
technische Dokumentation > historische Dokumentation.
`docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md` wird durch dieses
Dokument **abgelöst**, nicht ersetzt, als aktueller Referenzpunkt, und
wurde nach Archivierungs-Konvention bereits nach `docs/archive/`
verschoben.

---

## 12. Architecture Freeze

```
🟢 ARCHITECTURE FREEZE — APPROVED (unverändert)
```

Diese Serie hat den bestehenden Freeze nicht neu geöffnet — die vier PRs
waren ein fachlicher P0-Audit, ein kleiner P3-Dead-Code-Cleanup und eine
eng umrissene P1-Dependency-Injection-Korrektur, keiner davon
katastrophal (kein Crash, keine Korruption, kein Datenverlust, kein
Lockout — der während P1 live aufgetretene Testisolations-Fund wurde vor
dem Merge vollständig behoben und betraf nie den echten Produktionsstand
von `mapping/`). Der Freeze bleibt APPROVED.

---

## Baseline Frozen (2026-09-02)

**Diese Datei ist damit abgeschlossen.** Neue Findings, Nachträge oder
technische Schulden gehören ab jetzt in eine neue Datei
`MusicBot_ENGINEERING_BASELINE_v9.md`, nicht mehr hierher.
