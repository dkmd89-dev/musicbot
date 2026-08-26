# MusicBot — Metadata Quality Phase — PHASE 4: META-11

> Analyse-, Fix- und Abschluss-Dokumentation für META-11. Anders als
> META-01 bis META-04: **nicht** aus dem PHASE-0-Read-Only-Audit,
> sondern live entdeckt bei einem vom Nutzer initiierten Test-Download
> in der isolierten Testumgebung (`run_test_bot.py`, `@dkmd_test_bot`,
> `/tmp/musicbot_test/`) am 2026-08-26, nach Abschluss von META-04.

**Status: META-11 — ABGESCHLOSSEN (committed), live end-to-end
re-verifiziert. META-11-Nachtrag (Abschnitt 7) — ABGESCHLOSSEN (committed).**

---

## 1. Finding

**ID:** META-11 — P0 — Title/Album/Filename — Deutsches Kompositum
„Musikvideo" (kein Leerzeichen) wird nur teilweise entfernt, Titel bleibt
mitten im Wort abgeschnitten mit hängender öffnender Klammer stehen.

**Datei/Funktionen:**
`services/metadata/title_cleaner.py::TitleCleaner.light_title_cleanup()`
(produziert den tatsächlichen Title-Tag) und
`::TitleCleaner.build_search_title()` (Such-Titel für MusicBrainz/Last.fm).

**Wie entdeckt:** realer Test-Download über die isolierte Testumgebung —
Marius Müller-Westernhagen, YouTube-Titel „Westernhagen - Weil ich dich
liebe (Offizielles Musikvideo)". Ergebnis in Telegram-Erfolgsmeldung,
Title-Tag, Album-Tag UND Dateiname übereinstimmend korrumpiert:

```
🎵 Titel : Weil ich dich liebe (Offizielles Musik
💿 Album : Weil ich dich liebe (Offizielles Musik
📄 Datei : 2023 - Weil ich dich liebe (Offizielles Musik.m4a
```

**Root Cause:** beide Funktionen enthielten ein Pattern zum Entfernen des
englischen YouTube-Suffixes „(Official Music Video)":

```
r"\s*\(?\s*(?:official\s+)?(?:music\s+)?video\s*\)?\s*$"
```

Ohne Wortgrenze (`\b`) vor „video" matcht dieses Pattern auch als reinen
**Teilstring** innerhalb eines längeren Wortes. Deutsche YouTube-Titel
verwenden sehr häufig das zusammengesetzte Wort „Musikvideo" (kein
Leerzeichen, im Gegensatz zum englischen „Music Video") — das Pattern
matchte dabei nur das Suffix „video)" (beginnend mitten im Wort
„Musikvideo"), das Fragment „Musik" blieb mit einer nun unbalancierten
öffnenden Klammer im Ergebnis stehen.

`services/metadata/title_cleaner.py::apply_title_cleanup_rules()` (der
DRITTE, umfangreichere Titel-Cleanup-Pfad in derselben Datei) hatte dieses
Problem bereits durch ein spezifisches deutsches Pattern
(`offiziell(?:es|er|em|en)?\s*(?:musik\s*)?video`) gelöst — `light_title_cleanup()`
und `build_search_title()` (die beiden schlankeren, für den Normalfall
genutzten Pfade) hatten dieses Pattern jedoch nie erhalten.

---

## 2. Vor-Fix-Charakterisierung

```python
light_title_cleanup("Weil ich dich liebe (Offizielles Musikvideo)", "Westernhagen")
-> "Weil ich dich liebe (Offizielles Musik"

build_search_title(parsed_title="Weil ich dich liebe (Offizielles Musikvideo)", ...)
-> "Weil ich dich liebe (Offizielles Musik"
```

`tests/test_title_cleaner_german_compound_video_suffix.py` gegen den
ungefixten Stand: **3 failed, 4 passed**. Fehlgeschlagen (diskriminierend):
die beiden Kernfälle (`light_title_cleanup`, `build_search_title`) sowie
der zusammenfassende „keine hängende Klammer/kein Wortfragment"-Test.
Bereits vorher grün: die Überkorrektur-Schutz-Tests (englischer Fall mit
echtem Leerzeichen, bare „Video"-Suffix, „Musikvideo" NICHT am Titelende).

---

## 3. Fix

Zweistufig, je Funktion:

**Schritt 1 — `\b` vor „video"/„audio"** (verhindert die Korruption,
lässt „Musikvideo" aber unangetastet stehen statt es zu entfernen):

```diff
-r"\s*\(?\s*(?:official\s+)?(?:music\s+)?video\s*\)?\s*$"
+r"\s*\(?\s*(?:official\s+)?(?:music\s+)?\bvideo\b\s*\)?\s*$"
```

**Schritt 2 — explizites deutsches Kompositum-Pattern ergänzt** (erreicht
dieselbe Ergebnisqualität wie beim englischen Fall, statt „Musikvideo"
nur unkorrumpiert stehen zu lassen — übernimmt das bereits in
`apply_title_cleanup_rules()` bewährte Pattern):

```diff
+r"\s*\(?\s*offiziell(?:es|er|em|en)?\s*(?:musik\s*)?video\s*\)?\s*$"
```

Angewendet in beiden betroffenen Funktionen. Zusätzlich `\b` bei den
strukturell identischen „audio"-Suffix-Patterns ergänzt (gleiche
Schwachstellen-Form, kein konkreter Live-Fall bekannt, aber risikofreie
Konsistenz-Korrektur).

**Geänderte Datei:** ausschließlich `services/metadata/title_cleaner.py`.

**Neue Tests:** `tests/test_title_cleaner_german_compound_video_suffix.py`
— 7 Tests: 3 Kernfälle (beide Funktionen + „keine Korruption"-
Zusammenfassung), 3 Überkorrektur-Schutz-Tests (englischer Fall,
bare-Video-Suffix, „Musikvideo" nicht am Titelende), 1 Regressionstest
für die „audio"-Pattern-Parität.

---

## 4. Testergebnisse

```
STUFE 1 (gezielt):
tests/test_title_cleaner_german_compound_video_suffix.py:  7 passed

STUFE 2 (direkte Regression):
tests/test_metadata_modules.py, test_youtube_parser.py,
test_title_cleaner_feat_ft_no_space.py,
test_title_cleaner_marketing_suffix_bracket.py:            73 passed (11 subtests)

STUFE 3 (thematische Suite):
359 passed, 11 subtests passed

STUFE 4 (vollständige Suite, am Ende der Arbeitsphase):
1245 passed, 1 warning (vorbestehend, unabhängig), 19 subtests passed
(Baseline vor diesem Fix: 1238 passed → +7 neue Tests, 0 Regressionen)
```

**Zusätzlich: Live End-to-End-Reverifikation** in der isolierten
Testumgebung — Test-Library zurückgesetzt (`run_test_bot.py --clean`),
identischer YouTube-Link erneut vom Nutzer gesendet:

```
🎵 Titel : Weil ich dich liebe
💿 Album : Weil ich dich liebe
📄 Datei : /tmp/musicbot_test/library/Westernhagen/Singles/2023 - Weil ich dich liebe.m4a
```

Vollständig korrekt, keine hängende Klammer, kein abgeschnittenes
Fragment mehr.

---

## 5. Scope-Bestätigung

Einzige Produktionscode-Änderung: `services/metadata/title_cleaner.py`
(zwei Funktionen, Ergänzungen zu bereits bestehenden Pattern-Listen).
Keine Änderung an `genre_processor.py::_prepare_search_title()` (dessen
Patterns sind strukturell bereits sicher — Klammer-Vollmatch statt
Teilstring-Suffix, siehe Analyse) oder anderen Metadata-Modulen.

---

## 6. Abschluss

META-11 gilt hiermit als **abgeschlossen**. Root Cause vollständig
identifiziert, Vor-Fix-Charakterisierung erfolgreich, Fix zweistufig
(Korruption verhindert UND Ergebnisqualität auf Niveau des englischen
Falls gehoben), vollständige Suite grün (1245 passed, 0 failed, 0
errors), zusätzlich live end-to-end re-verifiziert über die isolierte
Testumgebung. Dieser Fund zeigt den Wert des vom Nutzer vorgeschlagenen
Test-Downloads: ein im PHASE-0-Audit (Code-Lesen) nicht entdeckter,
aber uber einen echten deutschen Titel sofort reproduzierbarer Bug mit
Auswirkung auf Title-, Album-Tag UND Dateiname gleichzeitig. Commit/
Push/PR/Merge auf explizite Nutzerfreigabe hin durchgeführt (siehe
Git-Historie).

---

## 7. Nachtrag — unvollständige Wortkombinationsabdeckung

**Entdeckt:** zweiter Live-Test-Download (Cyndi Lauper - „Time After
Time (Official HD Video)"), direkt im Anschluss an MB-01.

**Finding:** der ursprüngliche META-11-Fix (Abschnitt 3) deckte nur die
exakten Wortfolgen `(official [music] video)` bzw. `(audio)` ab. Reale
YouTube-Titel kombinieren diese Schlüsselwörter jedoch mit weiteren
Wörtern:

```
"Time After Time (Official HD Video)"  -> "Time After Time (Official HD"
"Song (Official Audio)"                -> "Song (Official"
"Song (HD Audio)"                      -> "Song (HD"
"Song (Official Lyric Video)"          -> "Song (Official Lyric"
```

Live reproduziert: `Cyndi Lauper/Singles/2009 - Time After Time
(Official HD.m4a` — dieselbe hängende-Klammer-Korruption wie im
ursprünglichen META-11-Fall, nur mit anderem Zusatzwort. Diese Datei
existiert weiterhin unverändert in der isolierten Test-Library (Alt-
Stand, vor diesem Nachtrags-Fix heruntergeladen).

**Fix:** die geklammerte Form wird jetzt zuerst und robust behandelt —
jede schließende Klammer, deren Inhalt „video" oder „audio" als
eigenständiges Wort enthält, wird komplett entfernt, unabhängig von
sonstigen Wörtern davor (analog zum bereits bewährten Muster in
`apply_title_cleanup_rules()`, META-03):

```diff
-            r"\s*\(?\s*(?:official\s+)?(?:music\s+)?\bvideo\b\s*\)?\s*$",
-            r"\s*\(?\s*\baudio\b\s*\)?\s*$",
+            r"\s*\([^()]*\b(?:video|audio)\b[^()]*\)\s*$",
+            r"\s*(?:official\s+)?(?:music\s+)?\b(?:video|audio)\b\s*$",
```

(analog in `build_search_title()`'s `version_patterns`-Liste).

**Geänderte Datei:** ausschließlich `services/metadata/title_cleaner.py`
(dieselben zwei Funktionen wie beim ursprünglichen META-11-Fix).

**Neue Tests:**
`tests/test_title_cleaner_video_audio_bracket_combinations.py` — 12
Tests: 5 Kernfälle je Funktion (HD+Video, Official Audio, HD+Audio,
Official+Lyric+Video, „keine hängende Klammer"-Zusammenfassung), 5
Regressionstests (deckungsgleich mit bestehenden META-11/META-03-Fällen),
2 direkt für `build_search_title()`.

**Testergebnisse:**

```
STUFE 1 (gezielt): 12 passed
STUFE 2 (direkte Regression): 92 passed (11 subtests)
STUFE 3 (thematische Suite): 407 passed (11 subtests)
STUFE 4 (vollständige Suite): 1270 passed, 0 failed, 0 errors
(Baseline vor diesem Nachtrag: 1258 passed → +12 neue Tests, 0 Regressionen)
```

Vierter unabhängiger Fund aus der vom Nutzer initiierten Test-Download-
Serie (nach META-11, TESTENV-01, MB-01) — bestätigt erneut den Wert
mehrerer, unterschiedlicher Test-Downloads statt nur eines Einzelfalls.
