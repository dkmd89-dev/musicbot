# ARCH-013 Phase 2 — Fachliche Entscheidung Genre-Alias-Konflikte

## Status

**Phase 2 abgeschlossen (2026-08-24). Reine fachliche Entscheidungsphase.
Keine Produktionscodeänderung, kein Refactoring, keine YAML-Änderung,
keine Zentralisierung.** Ergebnis ist eine Soll-Spezifikation für eine
spätere, separat freizugebende Umsetzungsphase.

---

## 1. Ausgangslage

ARCH-013 Phase 1 (`docs/MusicBot_ARCH-013_Genre_Alias_Characterization.md`,
PR #28, nicht gemergt) hat empirisch nachgewiesen, dass `GenreMapper` und
`GenreProcessor` für dieselben rohen Genre-Eingaben in mindestens 3
unabhängigen Fällen unterschiedliche Ergebnisse liefern: 4 Wertkonflikte
zwischen `genre_aliases.yaml` und `genre_overrides.yaml`, ein struktureller
Mixed-Case-Alias-Bug, ein Teilstring-Match-Unterschied.

Diese Phase beantwortet die fachliche Frage dahinter — **nicht**, wie die
Implementierungen technisch vereinheitlicht werden, sondern **welches
Ergebnis fachlich richtig sein soll**.

**Neue, in dieser Phase hinzugekommene Erkenntnisquellen** (nicht Teil von
Phase 1, für die Entscheidung aber ausschlaggebend):

- `mapping/genre_hierarchy.yaml` definiert alle 4 Konflikt-Genres explizit
  als eigenständige Subgenres (`Ruhrpott Rap: Deutschrap`,
  `Tech House: House`, `Electropop: Pop`, `Chamber Pop: Pop`) — eine
  **dritte**, bisher nicht im Konflikt betrachtete Quelle mit einer
  eigenen, strukturell verankerten Meinung.
- `docs/MusicBot_ENGINEERING_BASELINE.md` (DATA-002) und
  `tests/test_mapping_yaml_integrity.py::TestGenreClassificationDecisions`
  dokumentieren, dass **innerhalb** von `genre_overrides.yaml` selbst
  bereits einmal ein fast identischer Konflikt aufgetreten und per
  expliziter Nutzer-Entscheidung aufgelöst wurde: „EDM-Subgenres →
  granular behalten" — mit `tech house` und `electropop` als zwei der vier
  dort explizit benannten und seither testgeschützten Fälle.
- `mapping/artist_genre.yaml` und `mapping/channel_genre.yaml` (die
  manuell kuratierte, in `determine_genre_with_fallbacks()` höchstpriore
  Genre-Quelle) verwenden `Tech House`, `Electropop` und `Chamber Pop`
  bereits produktiv und wiederholt als reale Primär-/Sekundärgenres für
  konkrete Künstler/Channels (u. a. `channel_genre.yaml` mit
  `primary: Tech House` für zwei Channels, `artist_genre.yaml` mit
  `primary: Tech House` für einen Künstler und `Electropop`/`Chamber Pop`
  in Dutzenden Secondary-Genre-Listen).
- Für `ruhrpott rap` existiert **keine** entsprechende Verwendung in
  `artist_genre.yaml`/`channel_genre.yaml`, **kein** DATA-002-Präzedenzfall,
  und **kein** anderes der 17 Geschwister-Einträge
  (Berliner Rap, Hamburger Rap, Kölsch Rap, …) hat einen
  `genre_overrides.yaml`-Eintrag — `ruhrpott rap` ist der einzige.

Diese vier Zusatzbefunde sind der Kern der folgenden Entscheidungen.

---

## 2. Entscheidungsfragen

1. Soll `genre_overrides.yaml` grundsätzlich Vorrang vor
   `genre_aliases.yaml` haben, oder gilt eine fallspezifische Regel?
2. Soll Teilstring-Matching (nur in `GenreProcessor`) beibehalten,
   verboten, oder nur bedingt erlaubt werden?
3. Was ist das kanonische Ergebnis für die beiden Mixed-Case-YAML-Einträge?
4. Gilt dieselbe Alias-Semantik für Single-String- und Multi-Tag-Kontexte?

---

## 3. Konfliktanalyse

### 3.1 `electropop`

1. Alias (`genre_aliases.yaml`): `Pop`
2. Override (`genre_overrides.yaml`): `Electropop`
3. `GenreMapper`-Ergebnis: `Electropop` (Override gewinnt)
4. `GenreProcessor`-Ergebnis: `Pop` (kennt Override nicht)
5. Bedeutung: eigenständiges, in der Musikwelt fest etabliertes Subgenre
   von Pop (Synthesizer-lastiger Pop, z. B. CHVRCHES, Robyn) — keine bloße
   Stilvariante von generischem Pop.
6. Fachliche Plausibilität: hoch — `genre_hierarchy.yaml` selbst führt
   `Electropop` als eigenständiges Tiefe-1-Subgenre von `Pop`.
7. Auswirkung auf bestehende Tags: `Electropop` wird bereits in
   `artist_genre.yaml` fünffach als Secondary-Genre verwendet (u. a. für
   mindestens 5 verschiedene Künstler) — eine Kollabierung auf `Pop` würde
   bestehende, bereits als korrekt etablierte Klassifikationen fachlich
   entwerten.
8. Vorhandene Tests: `tests/test_mapping_yaml_integrity.py::TestGenreClassificationDecisions::test_edm_subgenres_stay_granular["electropop"]` — sichert bereits `genre_overrides.yaml["electropop"] == "Electropop"` als bewusste, per Nutzer-Entscheidung getroffene Festlegung ab (DATA-002).
9. Reale Consumer: `artist_genre.yaml` (5× als Secondary), keine direkte
   Verwendung als `primary`.
10. **Empfehlung: Override gewinnt (Modell A).** Deckt sich mit einer
    bereits getroffenen, testgeschützten Entscheidung (DATA-002) und mit
    der Hierarchie-Datei.

### 3.2 `chamber pop`

1. Alias: `Pop`
2. Override: `Chamber Pop`
3. `GenreMapper`-Ergebnis: `Chamber Pop`
4. `GenreProcessor`-Ergebnis: `Pop`
5. Bedeutung: eigenständiges Subgenre (orchestral/kammermusikalisch
   instrumentierter Pop, z. B. Sufjan Stevens, Belle & Sebastian).
6. Fachliche Plausibilität: hoch — ebenfalls explizit als Tiefe-1-Subgenre
   von `Pop` in `genre_hierarchy.yaml` verankert.
7. Auswirkung: `Chamber Pop` wird bereits 4× als Secondary-Genre in
   `artist_genre.yaml` verwendet.
8. Vorhandene Tests: **kein** direkter DATA-002-Präzedenzfall (anders als
   `electropop`/`tech house` nicht Teil der ursprünglichen 4
   parametrisierten `test_edm_subgenres_stay_granular`-Fälle) — aber
   strukturell identisch (Pop-Subgenre, Override vs. Alias-Konflikt,
   reale Verwendung in `artist_genre.yaml`).
9. Reale Consumer: `artist_genre.yaml` (4× als Secondary).
10. **Empfehlung: Override gewinnt (Modell A), per Analogieschluss zu 3.1.**
    Kein expliziter Präzedenzfall, aber dieselbe Beweislage (Hierarchie +
    reale Verwendung) wie bei `electropop`. Sollte in einer
    Umsetzungsphase denselben Testschutz erhalten wie `electropop`/
    `tech house`.

### 3.3 `tech house`

1. Alias: `House`
2. Override: `Tech House`
3. `GenreMapper`-Ergebnis: `Tech House`
4. `GenreProcessor`-Ergebnis: `House`
5. Bedeutung: etabliertes, eigenständiges House-Subgenre (technoide
   Percussion-Ästhetik, z. B. Fisher, Chris Lake).
6. Fachliche Plausibilität: hoch — Tiefe-2-Subgenre in
   `genre_hierarchy.yaml` (`Tech House: House`, `House: Electronic`) —
   die tiefste Hierarchieebene aller 4 Konflikte.
7. Auswirkung: **stärkste reale Auswirkung aller 4 Fälle** —
   `channel_genre.yaml` setzt `primary: Tech House` für zwei Channels,
   `artist_genre.yaml` setzt `primary: Tech House` für einen Künstler und
   verwendet es zusätzlich 5× als Secondary-Genre. Eine Kollabierung auf
   `House` würde mehrere bereits als `primary` klassifizierte Einträge
   fachlich falsch machen.
8. Vorhandene Tests: `test_edm_subgenres_stay_granular["tech house"]`
   (DATA-002-Präzedenzfall, wie bei `electropop`).
9. Reale Consumer: `channel_genre.yaml` (2× `primary`), `artist_genre.yaml`
   (1× `primary`, 5× Secondary) — die mit Abstand am häufigsten
   referenzierte der 4 Konflikt-Genres.
10. **Empfehlung: Override gewinnt (Modell A).** Stärkster Fall aller vier
    — bereits getroffene, testgeschützte Entscheidung UND die meisten
    realen `primary`-Verwendungen.

### 3.4 `ruhrpott rap`

1. Alias: `Ruhrpott Rap`
2. Override: `Deutschrap`
3. `GenreMapper`-Ergebnis: `Deutschrap` (Override gewinnt)
4. `GenreProcessor`-Ergebnis: `Ruhrpott Rap` (kennt Override nicht)
5. Bedeutung: regionales Deutschrap-Subgenre (Ruhrgebiet-Szene, z. B.
   frühe Bushido/Sido-Ära, aktuell u. a. Regional-Acts) — eine von 18
   strukturell gleichartigen Regional-Subgenre-Definitionen
   (Berliner Rap, Hamburger Rap, Kölsch Rap, …).
6. Fachliche Plausibilität: **hoch für den Alias-Wert, nicht für den
   Override.** `genre_hierarchy.yaml` definiert `Ruhrpott Rap: Deutschrap`
   exakt wie alle 17 Geschwister-Subgenres — es gibt in der Hierarchie
   keinen strukturellen Unterschied zwischen `Ruhrpott Rap` und
   `Berliner Rap`. Der Override kollabiert **nur** `Ruhrpott Rap` auf den
   Elterngenre — kein anderes Regional-Subgenre hat einen entsprechenden
   Override-Eintrag.
7. Auswirkung: `Ruhrpott Rap` wird in `artist_genre.yaml`/
   `channel_genre.yaml` **nicht** verwendet — keine reale Klassifikation
   hängt aktuell direkt davon ab.
8. Vorhandene Tests: `tests/test_genre_mapper_advanced.py::test_ruhrpott_rap_still_resolves_via_override` — charakterisiert das aktuelle `GenreMapper`-Verhalten (Override gewinnt), OHNE dabei zu bewerten, ob der Override selbst fachlich korrekt ist (der Test entstand im Rahmen der GENRE-003-Hierarchie-Fix-Arbeit, nicht im Rahmen einer DATA-002-artigen fachlichen Konfliktprüfung). `tests/test_genre_processor.py` und die Phase-1-Characterization-Tests testen konsistent den Alias-Wert (`"Ruhrpott Rap"`).
9. Reale Consumer: keine (`artist_genre.yaml`/`channel_genre.yaml`
   enthalten keinen Eintrag mit diesem Genre).
10. **Empfehlung: Alias gewinnt (Modell B) — Gegenteil der aktuellen
    `GenreMapper`-Priorität.** Anders als bei 3.1–3.3 gibt es hier
    **keine** Evidenz, dass der Override eine bewusste fachliche
    Entscheidung war — im Gegenteil: er ist strukturell inkonsistent zu
    allen 17 Geschwister-Einträgen, widerspricht der Hierarchie-Datei, und
    hat keinen realen Consumer, der von ihm abhängt. Die naheliegendste
    Erklärung ist ein isolierter Dateneingabefehler, kein Designentscheid.
    **Diese Einschätzung ist eine Empfehlung, keine Gewissheit** — sie
    sollte vor einer Umsetzung durch den Repository-Eigentümer bestätigt
    werden (siehe Abschnitt 9).

---

## 4. Override-vs-Alias-Entscheidung

**Keine globale Prioritätsregel.** Weder „Override gewinnt immer" noch
„Alias gewinnt immer" ist durch die Konfliktanalyse gedeckt — 3 von 4
Fällen sprechen für Override, 1 von 4 für Alias, mit jeweils
unterschiedlicher, konkret benennbarer Begründung.

**Erkannte, in der Konfliktanalyse durchgängig tragfähige Regel:**

> Bei einem Konflikt zwischen `genre_aliases.yaml` und
> `genre_overrides.yaml` gewinnt der Wert, der mit der in
> `genre_hierarchy.yaml` definierten Subgenre-Struktur übereinstimmt.

Diese Regel ist **fachlich begründet, nicht mechanisch**: Sie bevorzugt
nicht grundsätzlich eine Datei, sondern die Datei, deren Wert durch die
strukturell verankerte Genre-Taxonomie gedeckt ist. Für 3.1–3.3 ist das
der Override-Wert (weil `genre_aliases.yaml`s Flachklassifikation der
Hierarchie widerspricht), für 3.4 ist es der Alias-Wert (weil
`genre_overrides.yaml`s Flachklassifikation der Hierarchie widerspricht).

**Frage „ist diese Priorität für alle 4 Fälle sinnvoll?" (Aufgabe
Abschnitt 2):** Nein — genau deshalb wird hier **keine** pauschale
Dateipriorität empfohlen, sondern eine hierarchie-basierte Einzelfallregel
(Modell **C — Spezialregel**, nicht A oder B als globale Antwort).

---

## 5. Teilstring-Match-Entscheidung

**Empirische Grundlage** (real ausgeführt):

| Fall | Eingabe | Ergebnis (GenreProcessor) | Bewertung |
|---|---|---|---|
| A — exakter Match | `britpop` | — (kein Alias vorhanden) | n/a, siehe C |
| B — Teilstring, falscher Treffer | `britpop revival` | `Pop` | **fachlich falsch** — Britpop ist ein eigenständiges 90er-UK-Genre, keine Pop-Variante |
| B — Teilstring, falscher Treffer | `k-pop revival` | `Pop` | **fachlich falsch** — K-Pop ist in der Hierarchie ein eigenständiges Root-Level-Genre |
| B — Teilstring, korrekter Treffer | `ruhrpott rap fanpage` | `Ruhrpott Rap` | fachlich korrekt — genau der Anwendungsfall, für den Teilstring-Matching in `prioritize_genres()` vermutlich gedacht ist |
| B — Teilstring, korrekter Treffer | `deutschrap only` | `Deutschrap` | fachlich korrekt |
| C — falscher Treffer durch kurzen generischen Alias | `britpop` | `Pop` | **fachlich falsch**, wie oben — `"pop"` ist als Alias ohne Wortgrenze in `"britpop"` enthalten |

**Muster:** Teilstring-Matching funktioniert fachlich korrekt, wenn der
getroffene Alias durch eine Wortgrenze vom Rest des Strings getrennt ist
(`"ruhrpott rap fanpage"` → `"ruhrpott rap"` ist ein eigenständiges Wort im
String). Es produziert Fehlklassifikationen, wenn der Alias ohne
Wortgrenze in einem längeren Einzelwort eingebettet ist (`"pop"` in
`"britpop"`) — dort existiert keine Wortgrenze, der Treffer ist zufällig.

**Entscheidung: Modell C — nur unter definierten Bedingungen erlauben.**

> Ein Alias darf als Teilstring eines längeren Strings matchen, wenn er
> darin als eigenständiges Wort bzw. eigenständige Wortfolge vorkommt
> (durch Wortgrenzen — Leerzeichen, Satzzeichen, Stringanfang/-ende —
> begrenzt), aber **nicht**, wenn er nur als Zeichenfolge innerhalb eines
> längeren Einzelworts auftritt.

Diese Bedingung ist eine fachliche Anforderung, keine Implementierung —
wie sie technisch umgesetzt wird (Wortgrenzen-Regex, Tokenisierung o. Ä.),
ist Gegenstand einer möglichen Umsetzungsphase, nicht dieser Entscheidung.

**Modell B (verbieten) wurde geprüft und verworfen:** ein komplettes
Verbot würde auch die fachlich korrekten Treffer (`"ruhrpott rap
fanpage"` → `"Ruhrpott Rap"`) verhindern, für die `prioritize_genres()`
im Multi-Tag-Kontext (Abschnitt 6) einen echten Nutzen hat, da externe
Tags von MusicBrainz/Last.fm häufig unspezifisch dekoriert oder
zusammengesetzt sind.

---

## 6. Multi-Tag-Regeln

**Neuer empirischer Befund dieser Phase, über die Teilstring-Frage
hinaus:** Die Override-vs-Alias-Divergenz wirkt sich im Multi-Tag-Kontext
(`prioritize_genres()`) nicht nur auf das *Ergebnis-Label* aus, sondern
**bricht aktiv die dokumentierte Kernfunktion der Methode** — die
Priorisierung spezifischerer Subgenres gegenüber ihren Elterngenres
(Modul-Docstring von `genre_processor.py`: „Subgenres werden ihren Eltern
vorgezogen").

Real ausgeführt:

```text
prioritize_genres(["electropop", "pop"])         → ("Pop", [])
prioritize_genres(["tech house", "house", "electronic"]) → ("House", [])
prioritize_genres(["chamber pop", "indie"])       → ("Pop", [])
```

Ursache: `prioritize_genres()` normalisiert jeden Tag zuerst über
`GenreProcessor.normalize_genre_name()` (verwendet nur
`genre_aliases.yaml`) und schlägt danach dessen Priorität in
`GENRE_PRIORITY` (berechnet aus `genre_hierarchy.yaml`) nach. Da
`normalize_genre_name("electropop")` bereits zu `"pop"` kollabiert, bevor
die Prioritäts-Nachschlage überhaupt stattfindet, wird die in
`genre_hierarchy.yaml` korrekt hinterlegte Tiefe von `electropop` (1,
gegenüber `pop`s Tiefe 0) nie wirksam — der Tag verliert seine
Spezifität, bevor der eigentliche Priorisierungsmechanismus ihn sehen
kann. Für `ruhrpott rap` tritt dieses Problem NICHT auf, weil
`genre_aliases.yaml` dort bereits den spezifischen Wert liefert.

**Das ist kein separates neues Problem, sondern eine direkte Konsequenz
der in Abschnitt 4 identifizierten Konflikte** — die dort empfohlene
Hierarchie-basierte Regel löst dieses Multi-Tag-Symptom automatisch mit,
ohne dass eine eigene Multi-Tag-spezifische Regel nötig wäre.

**Kontext-Unterscheidung (Aufgabe Abschnitt 4):**

| Kontext | Regel |
|---|---|
| Einzelner Genre-String (`GenreMapper.determine_genre()`, Schritt 5, z. B. `raw_genre` aus einer YouTube-Beschreibung) | Exakter Match + Hierarchie-Fallback, **kein** Teilstring-Match — das bereits aktive `GenreMapper`-Verhalten ist für diesen Kontext angemessen: ein einzelnes, bereits halbwegs kuratiertes Feld profitiert nicht von Teilstring-Toleranz, trägt aber deren Fehlklassifikationsrisiko. |
| Mehrere Roh-Tags (`GenreProcessor.prioritize_genres()`, MusicBrainz/Last.fm) | Teilstring-Match unter der in Abschnitt 5 definierten Wortgrenzen-Bedingung erlaubt — UND muss die Hierarchie-Priorität (Abschnitt 4) korrekt anwenden, auch für die 4 Konflikt-Genres. |
| Bereits normalisiertes Genre (z. B. ein bereits kanonisches `"Hip Hop"`, das erneut durch `normalize_genre_name()` läuft) | Muss idempotent bleiben: `normalize(normalize(x)) == normalize(x)`. Aktuell durch beide Implementierungen für alle bekannten Aliase erfüllt (nicht Teil der in Phase 1 gefundenen Divergenzen) — als Invariante für eine Umsetzungsphase festgehalten, nicht neu getestet. |
| Ein Alias selbst als Eingabe (z. B. `"pop"`) | Exakter Match, Schritt 1 in beiden Implementierungen — unverändert korrekt in beiden. |

**Es gilt also NICHT dieselbe Regel für alle Kontexte** — der
Single-String- und der Multi-Tag-Kontext benötigen unterschiedliche
Teilstring-Politik, aber **dieselbe** Override-vs-Alias-Hierarchieregel.

---

## 7. Mixed-Case-/Whitespace-Entscheidung

- **Gewünschtes kanonisches Genre:** `"Hip Hop"` (ein Leerzeichen) — für
  beide YAML-Einträge (`"Hip-Hop"`, `"Hip - Hop"`). Unstrittig: dies ist
  bereits der Zielwert, den beide Einträge im YAML selbst tragen, und der
  Wert, den `GenreProcessor` bereits korrekt liefert. Keine
  Ermessensfrage.
- **Whitespace normalisieren:** ja — das aktuelle `GenreMapper`-Ergebnis
  `"Hip  Hop"` (doppeltes Leerzeichen) ist ein reiner
  Implementierungsdefekt (Tokenisierung erzeugt ein leeres Token für den
  isolierten Bindestrich), kein fachlich vertretbares Alternativergebnis.
- **Alias-Matching grundsätzlich case-insensitive:** ja, das ist bereits
  durchgängige Design-Absicht in beiden Implementierungen (beide
  lowercasen die Lookup-Eingabe) — die beiden Mixed-Case-YAML-Keys sind
  ein Datenfehler, keine beabsichtigte Case-Sensitivity.
- **Soll die YAML-Datei selbst korrigiert werden:** ja, empfohlen —
  `"Hip-Hop"` ist ohnehin redundant zum bereits vorhandenen
  `"hip-hop"`-Eintrag; `"Hip - Hop"` sollte zu `"hip - hop"` (lowercase)
  normalisiert werden, damit beide Implementierungen ihn erreichen können.
  **Nicht Teil dieser Phase** — reine Empfehlung für eine Umsetzungsphase.

Dies ist die einzige der vier untersuchten Fragen ohne echten fachlichen
Dissens — die Antwort ist eindeutig, nur die Umsetzung steht noch aus.

---

## 8. Kanonische Ergebnis-Tabelle

| Input | gewünschtes Ergebnis | Begründung |
|---|---|---|
| `electropop` | `Electropop` | Hierarchie-Subgenre von Pop, DATA-002-Präzedenzfall, 5× realer Consumer in `artist_genre.yaml` |
| `chamber pop` | `Chamber Pop` | Hierarchie-Subgenre von Pop, analog zu `electropop`, 4× realer Consumer |
| `tech house` | `Tech House` | Hierarchie-Subgenre (Tiefe 2) von House, DATA-002-Präzedenzfall, stärkste reale Nutzung (2× `primary` in `channel_genre.yaml`, 1× `primary` + 5× Secondary in `artist_genre.yaml`) |
| `ruhrpott rap` | `Ruhrpott Rap` | Hierarchie-Subgenre von Deutschrap wie alle 17 Geschwister-Regionalgenres; der abweichende Override ist strukturell isoliert, ohne realen Consumer, vermutlich ein Dateneingabefehler (Empfehlung, keine Gewissheit — siehe 3.4/9) |
| `Hip-Hop` | `Hip Hop` | bereits der YAML-Zielwert, unstrittig |
| `Hip - Hop` | `Hip Hop` | bereits der YAML-Zielwert; Whitespace-Bug beheben, nicht neu interpretieren |
| `britpop` | `Britpop` (Title-Case-Fallback, **kein** Alias-Treffer) | `"pop"` ohne Wortgrenze in `"britpop"` enthalten → nach Abschnitt 5 kein gültiger Teilstring-Treffer |
| `britpop revival` | `Britpop Revival` (Title-Case-Fallback, **kein** Alias-Treffer) | dieselbe Begründung — `"pop"` hat auch hier keine Wortgrenze zu `"britpop"` |
| Multi-Tag `["ruhrpott rap", "hip hop", "trap"]` | primary=`Ruhrpott Rap`, secondary=`[Hip Hop]` | bereits aktuelles `GenreProcessor`-Verhalten, unverändert korrekt |
| Multi-Tag `["electropop", "pop"]` | primary=`Electropop`, secondary=`[Pop]` | **weicht vom aktuellen Verhalten ab** (aktuell: primary=`Pop`) — Konsequenz aus Abschnitt 4/6: Hierarchie-Tiefe 1 muss vor Tiefe 0 gewinnen |

---

## 9. Fachliche Soll-Spezifikation

Zusammenfassend für eine mögliche spätere Umsetzungsphase:

1. **Konfliktregel:** bei Divergenz zwischen `genre_aliases.yaml` und
   `genre_overrides.yaml` gewinnt der mit `genre_hierarchy.yaml`
   konsistente Wert (Abschnitt 4). Für die 4 bekannten Fälle konkret:
   Override gewinnt bei `electropop`/`chamber pop`/`tech house`, Alias
   gewinnt bei `ruhrpott rap`.
2. **Teilstring-Match:** nur mit Wortgrenzen-Bedingung erlaubt
   (Abschnitt 5), fachlich unterschiedlich angewendet je Kontext
   (Abschnitt 6): nicht im Single-String-Fallback von
   `GenreMapper.determine_genre()`, wohl aber in
   `GenreProcessor.prioritize_genres()`s Multi-Tag-Pfad.
3. **Hierarchie-Priorität im Multi-Tag-Kontext:** muss auch für die 4
   Konflikt-Genres korrekt greifen (Abschnitt 6) — aktuell verhindert die
   Alias-Kollabierung dies für 3 der 4 Fälle.
4. **Mixed-Case-/Whitespace:** kanonisch `"Hip Hop"`, YAML-Korrektur
   empfohlen (Abschnitt 7).
5. **Idempotenz:** `normalize(normalize(x)) == normalize(x)` muss für jede
   künftige Implementierung gelten (Abschnitt 6).

Diese 5 Punkte bilden zusammen die fachliche Spezifikation, gegen die eine
künftige technische Umsetzung (Variante A oder B aus Phase 1) geprüft
werden kann.

---

## 10. Bewusst nicht entschiedene Architekturfragen

Wie von der Aufgabenstellung verlangt, **nicht** Gegenstand dieser Phase:

- gemeinsamer Alias-Loader/-Service
- Zusammenführung von `genre_aliases.yaml` und `genre_overrides.yaml` zu
  einer Datei
- Abschaffung von `GenreMapper` oder `GenreProcessor`
- neue Alias-Service-Klasse
- technische Umsetzung des Wortgrenzen-Kriteriums aus Abschnitt 5
- technische Umsetzung der Hierarchie-Prioritätsregel aus Abschnitt 4/6

Diese Fragen gehören in eine spätere, separat freizugebende
Umsetzungsphase (ARCH-013 Phase 3, falls gewünscht).

---

## 11. Risiken

- **`ruhrpott rap`-Empfehlung ist die unsicherste der vier** (Abschnitt
  3.4) — sie beruht auf Indizien (fehlende Konsistenz zu 17
  Geschwister-Einträgen, fehlender realer Consumer, fehlender
  Präzedenzfall), nicht auf einer bereits dokumentierten
  Nutzer-Entscheidung wie bei `electropop`/`tech house` (DATA-002). Sollte
  vor einer Umsetzung ausdrücklich bestätigt werden, da hier — anders als
  bei den anderen 3 — eine bereits **aktiv genutzte** `GenreMapper`-
  Override-Regel geändert würde.
- **Multi-Tag-Hierarchiekorrektur (Abschnitt 6, Punkt 3) ändert reales
  Verhalten** für jeden MusicBrainz-/Last.fm-Tag-Satz, der `electropop`,
  `chamber pop` oder `tech house` neben ihrem jeweiligen Elterngenre
  enthält — nicht nur eine Meinungsverschiedenheit zwischen zwei
  Implementierungen, sondern eine tatsächliche Ergebnisänderung gegenüber
  dem aktuellen `GenreProcessor`-Verhalten. Erfordert bei einer Umsetzung
  eigene Vorher-/Nachher-Beispiele und Regressionstests (CLAUDE.md §15/16).
- **Wortgrenzen-Kriterium (Abschnitt 5) ist noch nicht technisch
  spezifiziert** — je nach konkreter Umsetzung (z. B. Umgang mit
  Bindestrichen, die in mehreren echten Aliasen selbst vorkommen, etwa
  `"tech-house"` vs. `"tech house"`) können Randfälle entstehen, die in
  dieser Phase nicht geprüft wurden, da das eine technische, keine
  fachliche Frage ist.
- **Ohne Umsetzung bleibt der Ist-Zustand unverändert** — alle in Phase 1
  gefundenen Divergenzen (inkl. der hier neu gefundenen
  Multi-Tag-Hierarchie-Verletzung) bleiben bestehen, bis eine
  Umsetzungsphase freigegeben wird.

---

## 12. Empfehlung für eine spätere Umsetzungsphase

Falls eine Umsetzung gewünscht ist, wird folgender Zuschnitt empfohlen
(nicht Teil dieser Freigabe):

- **ARCH-013 Phase 3 — kleinster Schritt:** nur der Mixed-Case-/
  Whitespace-Fix aus Abschnitt 7 — unstrittig, kein Dissens, minimaler
  Scope, betrifft nur `genre_aliases.yaml` (2 Zeilen) + ggf.
  `GenreMapper`s Tokenisierung.
- **ARCH-013 Phase 4 — mittlerer Schritt, nach Bestätigung von 3.4:** die
  4 Konfliktregeln aus Abschnitt 4/9 umsetzen — vermutlich am saubersten
  direkt in `genre_overrides.yaml`/`genre_aliases.yaml` (Korrektur der
  Werte, sodass beide Dateien wieder übereinstimmen), nicht zwingend als
  Code-Zentralisierung.
- **ARCH-013 Phase 5 — größter Schritt, separat zu bewerten:** die
  Wortgrenzen-Bedingung für Teilstring-Matching technisch umsetzen
  (Abschnitt 5) — dies berührt aktives Matching-Verhalten in
  `prioritize_genres()` und sollte eigene Characterization-Tests vor jeder
  Änderung bekommen, analog zum in dieser Session etablierten Muster.

Diese Reihenfolge (kleinster/unstrittigster Schritt zuerst) ist eine
Empfehlung, keine Festlegung — die Entscheidung liegt beim Nutzer.

---

## 13. Entscheidungsgate

**ARCH-013 PHASE 2 — ENTSCHEIDUNGSGATE ERREICHT**

Fachliche Entscheidung abgeschlossen. Keine Produktionsänderung, kein
Refactoring, keine YAML-Änderung, keine Zentralisierung, kein Merge.

**Ergebnis:**

- Override-vs-Alias: **Modell C (Spezialregel)** — hierarchie-basiert,
  nicht dateibasiert. 3 von 4 Konflikten zugunsten Override, 1 von 4
  (`ruhrpott rap`) zugunsten Alias, mit unterschiedlicher Beweisstärke
  (siehe Risiken, Abschnitt 11).
- Teilstring-Matching: **Modell C (bedingt erlauben)** — nur mit
  Wortgrenzen-Bedingung, nur im Multi-Tag-Kontext.
- Mixed-Case/Whitespace: eindeutig, `"Hip Hop"`, kein Dissens.

Freigabe für eine Umsetzungsphase (Abschnitt 12) liegt beim Nutzer — diese
Phase selbst nimmt keine Umsetzung vor.
