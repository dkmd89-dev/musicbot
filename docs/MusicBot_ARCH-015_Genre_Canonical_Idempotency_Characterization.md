# MusicBot ARCH-015 — Genre Canonical-Value / Idempotency Characterization

**Status:** Phase 1 (Characterization) abgeschlossen. Keine Produktionsänderung.
Keine Lösungsvariante umgesetzt. Wartet auf ausdrückliche Freigabe für eine
mögliche Phase 2.

**Ausgangspunkt:** POST-ARCH-014 Services/Genre Architecture Audit (Abschnitt
D "Systematische Idempotenzanalyse", Abschnitt I "Neue Befunde") identifizierte
3 von 115 aktuell erreichbaren kanonischen Genre-Werten in
`GenreProcessor.GENRE_NORMALIZATION` als nicht idempotent:
`normalize(normalize(x)) != normalize(x)`.

---

## A. Ausgangsbefund

```
"ny drill"   → normalize() → "New York Drill" → normalize() → "Hip Hop"
"aggro rap"  → normalize() → "Aggro Deutschrap" → normalize() → "Deutschrap"
"NDW"        →                                     normalize() → "Ndw"
```

Alle drei betreffen `GenreProcessor.normalize_genre_name()`
(`services/metadata/genre_processor.py`). Die ARCH-014-Spezifitätsregel
(Zeichenlänge + Hierarchie-Tiefe-Tie-Breaker) ist in allen drei Fällen
korrekt gemäß ihrer eigenen Spezifikation angewendet — der Fehler liegt
nicht in der Spezifitätsregel selbst, sondern **vor** ihr.

---

## B. Klasse-A-Rekonstruktion

### `ny drill` → `New York Drill` → `Hip Hop`

1. Alias-Key: `"ny drill"` (`mapping/genre_aliases.yaml`)
2. Alias-Zielwert: `"New York Drill"`
3. Zweiter Normalisierungslauf: `normalize_genre_name("New York Drill")`
4. Auslösender generischer Alias: `"drill"` (→ `"Hip Hop"`)
5. Finaler falscher Wert: `"Hip Hop"`
6. Stelle im Produktionscode: `genre_processor.py:341-391`
   (`normalize_genre_name()`) — kein direkter Key-Match (`"new york
   drill"` ist kein registrierter Alias-Key, Zeile 356), daher greift
   der Wortgrenzen-Substring-Match (Zeile 379-391). `"drill"` ist der
   **einzige** Wortgrenzen-Kandidat in `"new york drill"`.
7. `New York Drill` wird nicht als Fixpunkt erkannt, weil kein
   Alias-Key `"new york drill": "New York Drill"` existiert — der
   direkte Match-Zweig (Zeile 356-357) greift nur bei einer exakten
   Key-Übereinstimmung, nicht bei struktureller Gleichheit mit dem
   eigenen Ausgabewert.

### `aggro rap` → `Aggro Deutschrap` → `Deutschrap`

Identischer Mechanismus:

1. Alias-Key: `"aggro rap"`
2. Alias-Zielwert: `"Aggro Deutschrap"`
3. Zweiter Lauf: `normalize_genre_name("Aggro Deutschrap")`
4. Auslösender generischer Alias: `"deutschrap"` (→ `"Deutschrap"`,
   Top-Level-Genre)
5. Finaler falscher Wert: `"Deutschrap"`
6. Gleiche Codestelle wie oben.
7. Gleicher Grund: kein Alias-Key `"aggro deutschrap": "Aggro
   Deutschrap"`.

Beide Zielwerte sind **produktiv als eigenständige Subgenres modelliert**,
nicht bloße Alias-Nebenprodukte:

```yaml
# mapping/genre_hierarchy.yaml
Aggro Deutschrap: Deutschrap    # Zeile 40, Tiefe 1
Drill: Hip Hop                  # Zeile 53, Tiefe 1
New York Drill: Drill           # Zeile 75, Tiefe 2
```

`New York Drill` wird zudem bereits aktiv in `mapping/artist_genre.yaml`
als kuratierter Sekundär-Genre-Wert für mindestens 3 Künstler verwendet
(`secondary: [Drill, New York Drill, ...]`).

---

## C. Vollständige Kandidatenprüfung

Systematischer Scan aller 115 eindeutigen kanonischen Werte in
`GENRE_NORMALIZATION`:

- **77** sind Mehrwort-/Komposit-Werte (Leerzeichen, Bindestrich oder `&`)
- **73** davon besitzen einen eigenen Self-Alias-Key (der lowercased
  kanonische Wert ist selbst ein registrierter Alias-Key) — meist nicht
  bewusst als "Idempotenz-Fix" eingefügt, sondern weil die natürliche
  Haupteingabeform (z. B. `"tech house"`) ohnehin als Alias-Key benötigt
  wird und zufällig mit dem lowercased Zielwert übereinstimmt.
- **4** besitzen **keinen** Self-Alias-Key:
  - `New York Drill` — instabil (Klasse A1)
  - `Aggro Deutschrap` — instabil (Klasse A1)
  - `Drum & Bass` — **stabil** (Gegenbeispiel, siehe E)
  - `Liquid Drum & Bass` — **stabil** (Gegenbeispiel, siehe E)

Kein A2-Fall (Mehrwort-Kanonwert → anderer *spezifischer* Alias statt
generischem) wurde gefunden. Alle Instabilitäten sind Klasse A1 oder
Klasse B.

---

## D. Instabilitätsmatrix

| Input/Kanonwert | 1. Lauf | 2. Lauf | Klasse | Ursache |
|---|---|---|---|---|
| `ny drill` | `New York Drill` | `Hip Hop` | A1 | generischer Teilwort-Alias `drill`, kein Self-Key |
| `aggro rap` | `Aggro Deutschrap` | `Deutschrap` | A1 | generischer Teilwort-Alias `deutschrap`, kein Self-Key |
| `New York Drill` (direkt) | `New York Drill` | `Hip Hop` | A1 | s. o. |
| `Aggro Deutschrap` (direkt) | `Aggro Deutschrap` | `Deutschrap` | A1 | s. o. |
| `NDW` | `NDW` | `Ndw` | B | kein Self-Key, keine Substring-Kandidaten, Title-Case-Fallback (`str.capitalize()`) |
| `Drum & Bass` | `Drum & Bass` | `Drum & Bass` | stabil | kein Self-Key, aber auch keine Substring-Kandidaten — Fallback reproduziert korrekt |
| `Liquid Drum & Bass` | `Liquid Drum & Bass` | `Liquid Drum & Bass` | stabil | s. o. |
| alle übrigen 111 kanonischen Werte | — | — | stabil | Self-Alias-Key vorhanden → Direkt-Match-Kurzschluss (Zeile 356) |

**Ergebnis: 112/115 stabil, 3/115 instabil (2× Klasse A1, 1× Klasse B).**

---

## E. Self-Alias-Analyse

Zentrale Hypothese: *"Ein kanonischer Alias-Zielwert sollte selbst ein
stabiler Fixpunkt der Normalisierung sein."*

Prüfergebnisse gegen den tatsächlichen Datenbestand:

- **Stabile Kanonwerte ohne Self-Alias-Key existieren:** ja —
  `Drum & Bass`, `Liquid Drum & Bass`. Die Hypothese "kein Self-Key ⇒
  instabil" ist damit **widerlegt** als notwendige Bedingung. Der
  tatsächliche Auslöser ist feiner: instabil wird ein Mehrwort-Kanonwert
  ohne Self-Key nur dann, wenn **mindestens einer seiner
  Wortbestandteile selbst ein registrierter, kürzerer Alias-Key ist**
  (`drill`, `deutschrap` sind beide selbst Top-Level- bzw.
  Subgenre-Aliases; `drum`, `bass`, `liquid` sind es nicht).
- **Instabile Kanonwerte MIT Self-Alias-Key:** keine gefunden (0/73).
  Der Direkt-Match-Zweig (Zeile 356) ist ein wirksamer Kurzschluss,
  sobald ein Self-Key existiert — er wird nie vom nachfolgenden
  Substring-Matching überstimmt.
- **Self-Alias-Keys, die durch Case/Whitespace trotzdem instabil
  bleiben:** keine gefunden. Alle 73 vorhandenen Self-Keys sind exakt
  `wert.lower()` und liefern exakt `wert` zurück.
- **Self-Alias-Key stabilisiert, verändert aber die
  Multi-Tag-Priorisierung:** nicht geprüft im Sinne einer
  hypothetischen Ergänzung (außerhalb des Scopes, da keine YAML-Änderung
  vorgenommen werden darf) — analytisch aber plausibel unkritisch, da
  ein Self-Key strukturell identisch zu den 73 bestehenden wäre und
  `GENRE_PRIORITY` unabhängig aus `genre_hierarchy.yaml` berechnet wird,
  nicht aus `genre_aliases.yaml`.
- **Bewusste Gründe für fehlende Self-Alias-Keys:** keine Evidenz
  gefunden. Der direkt benachbarte Eintrag in `genre_aliases.yaml`
  (Zeile 8: `"deutscher pop": "Deutscher Pop"`, unmittelbar neben Zeile
  7 `"neue deutsche welle": "NDW"`) zeigt, dass das Self-Alias-Muster im
  selben Abschnitt der Datei aktiv verwendet wird — das Fehlen bei
  `NDW`/`New York Drill`/`Aggro Deutschrap`/`Drum & Bass`/`Liquid Drum &
  Bass` liest sich als historische Lücke, nicht als Design-Entscheidung.

---

## F. Kanonische Genre-/YAML-Konsistenz

| Wert | in `genre_hierarchy.yaml`? | in `artist_genre.yaml` verwendet? | Bewertung |
|---|---|---|---|
| `New York Drill` | ja, Tiefe 2 (`Drill` → `Hip Hop`) | ja, 3× als `secondary` | echtes, produktiv genutztes Subgenre |
| `Aggro Deutschrap` | ja, Tiefe 1 (`Deutschrap`) | nicht gefunden | echtes Subgenre laut Hierarchie |
| `NDW` | nicht als eigener Hierarchie-Knoten gefunden | nicht gefunden | Alias-Ziel, kein Hierarchie-Eintrag |
| `Drum & Bass` | ja, Tiefe 1 (`Electronic`) | — | stabil, kein Handlungsbedarf |
| `Liquid Drum & Bass` | nicht in Hierarchie gefunden | — | stabil, kein Handlungsbedarf |

Zusätzlicher, nicht scope-relevanter Nebenbefund (nur dokumentiert, nicht
bewertet): `mapping/genre_overrides.yaml` enthält teilweise dieselben
Keys wie `genre_aliases.yaml` (`dnb`, `drum and bass`, `jungle`, `d&b`,
`drum n bass` → jeweils `"Drum & Bass"` in beiden Dateien). Dies betrifft
ausschließlich `GenreMapper` (das `overrides` UND `genre_aliases`
getrennt lädt, Overrides zuerst) — `GenreProcessor.GENRE_NORMALIZATION`
lädt ausschließlich `genre_aliases.yaml` und ist von dieser Dopplung
nicht betroffen. Keine Bewertung, keine Empfehlung — außerhalb des
ARCH-015-Scopes.

Kein Geschwister-Genre-Muster mit identischer Struktur gefunden, das auf
einen bestehenden fachlichen Präzedenzfall für "immer Self-Alias
ergänzen" hindeuten würde — die 73 bestehenden Self-Keys sind
Nebenprodukt der Haupteingabeform, kein bewusst angewandtes
Idempotenz-Prinzip.

---

## G. Klasse-B-Analyse (`NDW`)

`NDW` ist **strukturell unabhängig** von Klasse A: für `"ndw"` existieren
weder ein Self-Alias-Key noch irgendwelche Wortgrenzen-Substring-Kandidaten
(leere Kandidatenliste). Der Wert durchläuft daher vollständig bis zum
Title-Case-Fallback (`genre_processor.py:393-400`):

```python
capitalized = " ".join(
    w if w.lower() in small_words else w.capitalize()
    for w in words
)
```

`"ndw".capitalize()` → `"Ndw"` (Python kapitalisiert nur den ersten
Buchstaben, senkt den Rest ab — es gibt keine Sonderbehandlung für
Akronyme in diesem Fallback).

1. Kein stabiler kanonischer Wert existiert, weil kein Self-Key
   registriert ist.
2. Der Fallback greift, weil die Kandidatenliste für `"ndw"` leer ist —
   kein anderer Alias-Key ist als Wortgrenzen-Substring in `"ndw"`
   enthalten.
3. **Vollständige Prüfung ergab: `NDW` ist der einzige betroffene Fall**
   in `GenreProcessor`. Alle anderen potenziellen Akronym-/
   Sonderschreibweise-Kandidaten (`C-Pop`, `G-Funk`, `G-House`, `J-Pop`,
   `K-Pop`, `Lo-Fi`, `R&B`, `UK Drill`, `UK Rap`) besitzen jeweils einen
   eigenen Self-Alias-Key und erreichen den Fallback-Pfad nie.
4. Ja, isoliert bestätigt (regressionsgesichert per
   `TestClassBFallbackCapitalization::test_ndw_is_the_only_affected_value_in_genre_processor`).
5. Keine weiteren kanonischen Werte, die durch `.capitalize()` verändert
   würden — vollständig geprüft (Abgleich `title_fallback(v) != v` gegen
   alle 115 Werte, s. Anhang-Skript).

**Wichtiger Zusatzbefund:** `utils/genre_map.py::GenreMapper` besitzt
eine strukturell **unabhängige zweite** `normalize_genre_name()`-
Implementierung (kein Substring-Matching, nur exakter Dict-Lookup gegen
`overrides` + `genre_aliases`, danach ein eigener Title-Case-Fallback mit
Sonderbehandlung für `EDM`/`R&B`/`UK`/`US`/`DJ`/`MC`). Diese
Implementierung reproduziert denselben `.capitalize()`-Fallback für
unbekannte Wörter — `GenreMapper.normalize_genre_name("NDW")` liefert
ebenfalls `"Ndw"`. Klasse B ist somit ein **in beiden unabhängigen
Implementierungen dupliziertes** Verhalten, während Klasse A1
ausschließlich `GenreProcessor` betrifft (siehe I).

---

## H. Idempotenz-Invariante

Geprüft: `normalize(normalize(x)) == normalize(x)` für

- alle 321 Alias-Keys in `GENRE_NORMALIZATION` (direkt und dekoriert,
  `key + " extra"`) → **3/321 instabil** (`neue deutsche welle` → NDW,
  `aggro rap` → Aggro Deutschrap, `ny drill` → New York Drill — jeweils
  die Alias-Keys, deren Zielwert selbst instabil ist)
- alle 115 eindeutigen kanonischen Zielwerte, direkt erneut normalisiert
  → **3/115 instabil**
- `GenreMapper.normalize_genre_name()` für die 3 betroffenen Werte
  separat → **1/3 instabil** (`NDW`; `New York Drill` und `Aggro
  Deutschrap` sind hier stabil, da kein Substring-Matching existiert)

Vollständigkeit: Alle 115 kanonischen Werte und alle 321 Alias-Keys
wurden erschöpfend geprüft (kein Sampling) — technisch uneingeschränkt
möglich, da beide Mengen endlich und klein sind. Multi-Tag-Szenarien
(`prioritize_genres()` mit mehreren Tags) wurden stichprobenartig für
die 3 betroffenen Werte nicht gesondert geprüft, da `prioritize_genres()`
`normalize_genre_name()` pro Tag einzeln aufruft und keine zusätzliche
Fehlerquelle einführt (siehe I).

---

## I. Multi-Pass-Risiko

`GenreProcessor.normalize_genre_name()` (die betroffene Implementierung)
wird ausschließlich aus `prioritize_genres()` heraus aufgerufen (Zeile
259, 275, 277, 279), welches wiederum ausschließlich aus
`_fetch_genre_from_musicbrainz()` und `_fetch_genre_from_lastfm()`
aufgerufen wird — beide erhalten **frische, rohe externe API-Tag-Listen**
(`mb_data.get("tags")`, `lfm_data.get("tags")`) als Eingabe, niemals den
bereits produzierten `GenreResult.primary`-Wert des eigenen Tracks
zurückgespeist.

Es existiert **kein direkter Code-Pfad**, der den Ausgabewert von
`normalize_genre_name()` innerhalb derselben Aufrufkette erneut als
Eingabe verwendet — die Instabilität ist rein mathematisch (die Funktion
ist nicht idempotent), löst sich aber nicht automatisch bei jedem
Aufruf aus.

Das reale Risiko liegt auf einer anderen Ebene: **Reprocessing über
unabhängige Aufrufe hinweg.** Wenn ein Track einmal (bei Ersterfassung)
über MusicBrainz/Last.fm-Tags korrekt `"New York Drill"` erhält, und
derselbe Track zu einem späteren Zeitpunkt erneut durch die
Metadaten-Pipeline läuft (z. B. erneuter Download, manuelles Retagging,
Cache-Invalidierung) — dann hängt das Ergebnis von den zu diesem
Zeitpunkt gelieferten *rohen* API-Tags ab. Enthalten diese rohen Tags
irgendwann direkt den Text `"New York Drill"` (statt z. B. `"drill"`
oder `"ny drill"` als separatem Tag), würde `prioritize_genres()` diesen
Wert direkt normalisieren und `"Hip Hop"` erhalten — ein scheinbar
"spontaner" Genre-Wechsel für denselben Track, ausschließlich abhängig
von der exakten Tag-Formulierung der externen API zum Abfragezeitpunkt,
nicht von einer echten Genre-Änderung.

Die "lokale Genre"-Pipeline (`determine_genre()` via `GenreMapper`, die
das *embedded* Genre-Tag der Datei selbst als `raw_genre` verwendet, s.
`genre_processor.py:115-116`) ist von Klasse A1 **nicht** betroffen, da
sie `GenreMapper.normalize_genre_name()` nutzt — die nachweislich stabile
zweite Implementierung (siehe G, H). Ein re-embeddetes `"New York
Drill"`-Tag würde über diesen Pfad korrekt stabil bleiben.

Klasse B (`NDW`) betrifft dagegen **beide** Implementierungen
gleichermaßen — hier besteht das Multi-Pass-Risiko unabhängig vom
gewählten Pfad, ist aber auf einen einzigen, seltenen kanonischen Wert
begrenzt.

**Fazit:** Das Risiko ist real, aber eng begrenzt — es erfordert eine
spezifische Tag-Formulierung durch eine externe API bei einem erneuten,
unabhängigen Pipeline-Durchlauf, betrifft nur 2 (Klasse A1) bzw. 1
(Klasse B) von 115 kanonischen Werten, und die primäre "lokale"
Genre-Pipeline ist strukturell gegen Klasse A1 immun.

Nebenbefund: `enhanced_metadata_processor.py::_normalize_genre_name()`
und `::_prioritize_genres()` (dünne Wrapper um die betroffenen Methoden)
werden projektweit an keiner Stelle außerhalb ihrer eigenen Definition
aufgerufen — vermutlich toter Code, nicht weiter untersucht (außerhalb
des Scopes).

---

## J. Neue Characterization-Tests

Neue Datei `tests/test_genre_canonical_idempotency_characterization.py`
(15 Tests, 5 Klassen), ausschließlich das aktuelle (fehlerhafte)
Verhalten dokumentierend:

- `TestClassA1GenericSubstringInstability` (6 Tests) — `ny drill`/`aggro
  rap` inkl. direktem Re-Entry und exaktem Kandidaten-Mechanismus
- `TestClassA1CounterExamplesStableWithoutSelfKey` (2 Tests) — `Drum &
  Bass`, `Liquid Drum & Bass` als Gegenbeispiele zur reinen
  Self-Alias-Hypothese
- `TestClassBFallbackCapitalization` (3 Tests) — `NDW`-Mechanismus und
  Vollständigkeitsnachweis (einziger Fallback-Fall)
- `TestGenreMapperNotAffectedByClassA1` (3 Tests) — Gegenprobe an der
  zweiten, unabhängigen `GenreMapper`-Implementierung
- `TestFullCanonicalValueIdempotencyInventory` (1 Test) — Regressionswächter
  über exakt 3 instabile Werte

Keine bestehenden Tests verändert. Keine Assertion beschreibt
Wunschverhalten — alle assertieren explizit das aktuelle, dokumentiert
fehlerhafte Verhalten.

---

## K. Lösungsvarianten A–D

### Variante A — Self-Alias-Keys ergänzen

`"new york drill": "New York Drill"`, `"aggro deutschrap": "Aggro
Deutschrap"` (und optional `"ndw": "NDW"`) in `genre_aliases.yaml`
ergänzen.

- **Verhalten:** Direkter Match-Kurzschritt (Zeile 356) greift künftig
  vor dem Substring-Matching — exakt das Muster, das bereits 73/77
  Mehrwort-Werte stabilisiert.
- **Scope:** reine YAML-Datenänderung, 2-3 neue Zeilen.
- **Risiko:** sehr gering — identisches, bereits 73-fach bewährtes
  Muster. Kein neuer Code-Pfad.
- **Nebenwirkungen:** keine erwartet, da der Self-Key nur einen
  zusätzlichen Eintrag im bereits genutzten Dict darstellt.
- **Testaufwand:** gering — bestehende Characterization-Tests müssten
  in Assertions invertiert werden (etabliertes Muster ARCH-012/013/014).
- **YAML vs. Code:** ausschließlich YAML.
- **Kompatibilität ARCH-013/014:** vollständig kompatibel — verändert
  weder Wortgrenzen-Logik noch Spezifitätsregel, nutzt nur den bereits
  vorrangigen Direkt-Match-Zweig.
- **Deckt NDW nicht automatisch ab** in `GenreMapper`, da dort der
  gleiche Fallback-Mechanismus separat existiert — müsste dort
  ebenfalls (oder stattdessen) behoben werden, falls gewünscht.

### Variante B — Bereits-kanonische Werte vor Substring-Matching als Fixpunkte behandeln

Vor dem Substring-Match prüfen, ob der Eingabewert bereits **exakt**
(case-insensitive) einem der `GENRE_NORMALIZATION`-*Werte* (nicht nur
Keys) entspricht, und in diesem Fall sofort zurückgeben.

- **Verhalten:** würde alle aktuellen und zukünftigen kanonischen Werte
  ohne Self-Key automatisch stabilisieren, auch `Drum & Bass`-artige
  Fälle (die bereits stabil sind, aber jetzt auch strukturell
  garantiert).
- **Scope:** Code-Änderung in `normalize_genre_name()`, ca. 3-5 Zeilen
  (neue Menge `set(GENRE_NORMALIZATION.values())`, Vorab-Check).
- **Risiko:** gering-mittel — neuer Code-Pfad, muss gegen alle 55
  ARCH-014-Fälle und alle ARCH-013-Regeln erneut verifiziert werden.
- **Nebenwirkungen:** löst das Problem systematisch für alle künftigen
  YAML-Änderungen, nicht nur die 2 aktuell bekannten Fälle — reduziert
  laufenden Pflegeaufwand.
- **Testaufwand:** mittel — vollständige Regression + neue
  Positiv-/Negativ-Tests nötig.
- **YAML vs. Code:** Produktionscode.
- **Kompatibilität ARCH-013/014:** verträgt sich, da diese Prüfung
  logisch VOR dem bestehenden Substring-Matching ansetzt und dessen
  Verhalten für alle Nicht-Fixpunkt-Eingaben unverändert lässt.

### Variante C — Substring-Matching nur auf Roh-/Alias-Eingaben, nicht auf bereits kanonische Werte

Ähnlich zu B, aber konzeptionell als expliziter Architektur-Unterschied
zwischen "rohe/externe Eingabe normalisieren" und "bereits normalisierten
Wert erneut normalisieren" (z. B. über ein separates Flag/eine separate
Methode `normalize_genre_name(genre, already_canonical=False)`).

- **Verhalten:** wie B, aber explizit als zwei unterscheidbare
  Aufruf-Modi statt impliziter Fixpunkt-Erkennung.
- **Scope:** größer als B — neue Methodensignatur, alle 4 Aufrufstellen
  müssten ggf. angepasst werden, um den richtigen Modus zu wählen.
- **Risiko:** mittel — mehr Änderungsfläche, Gefahr, dass ein Aufrufer
  den falschen Modus wählt.
- **Nebenwirkungen:** verändert die öffentliche Methodensignatur.
- **Testaufwand:** höher als B.
- **YAML vs. Code:** Produktionscode, größerer Eingriff.
- **Kompatibilität ARCH-013/014:** verträgt sich prinzipiell, aber
  deutlich invasiver ohne erkennbaren zusätzlichen Nutzen gegenüber B.

### Variante D — andere Datenmodell-/Normalisierungsregel

Z. B. ein separates `GENRE_CANONICAL_VALUES`-Set explizit in einer eigenen
YAML-Sektion pflegen, oder Klasse B (`NDW`) durch eine
Akronym-Sonderliste im Fallback beheben (analog zu `GenreMapper`s
bestehender `EDM/R&B/UK/US/DJ/MC`-Liste).

- **Verhalten:** würde Klasse B gezielt adressieren, ohne Klasse A zu
  berühren — beide Klassen haben unterschiedliche Root Causes und
  könnten unabhängig behandelt werden.
- **Scope:** klein für Klasse B allein (Akronymliste erweitern/angleichen
  zwischen `GenreProcessor`-Fallback und `GenreMapper`-Fallback).
- **Risiko:** gering für die Akronym-Teillösung; die
  "separates Canonical-Set"-Variante wäre eine neue Datenstruktur (vom
  Auftrag explizit ausgeschlossen: "KEINE neue gemeinsame
  Alias-Struktur").
- **Nebenwirkungen:** löst Klasse A nicht.
- **Testaufwand:** gering für die Akronym-Teillösung.
- **YAML vs. Code:** Produktionscode (Fallback-Logik).
- **Kompatibilität ARCH-013/014:** unproblematisch, da Fallback-Pfad
  von ARCH-013/014 nicht berührt wird.

---

## L. Risikoanalyse

| Variante | Code-Risiko | Scope | Deckt Klasse A1 | Deckt Klasse B |
|---|---|---|---|---|
| A (Self-Alias-Keys) | sehr gering | 2 YAML-Zeilen | ja (2/2) | nein (separat) |
| B (Fixpunkt-Vorabprüfung) | gering-mittel | ~5 Code-Zeilen | ja, systematisch | ja, falls NDW-Self-Key ergänzt wird (kombinierbar mit A) |
| C (expliziter Modus) | mittel | Signaturänderung | ja, systematisch | ja, kombinierbar |
| D (Akronymliste) | gering (Teillösung) | Fallback-Erweiterung | nein | ja |

**Geringstes Risiko bei geringster Verhaltensänderung:** Variante A für
Klasse A1 (identisches, 73-fach bewährtes Muster, reine Daten). Für
Klasse B wäre eine Kombination aus A (`"ndw": "NDW"` ergänzen) ebenso
minimal-invasiv und würde denselben bewährten Mechanismus nutzen — eine
Fallback-Akronymliste (D) wäre nur nötig, falls künftig *weitere*,
heute noch nicht existierende Akronym-Kanonwerte ohne Self-Key
hinzukommen sollten.

---

## M. Empfehlung für Phase 2

Sofern eine Korrektur gewünscht wird: **Variante A** (Self-Alias-Keys für
`New York Drill`, `Aggro Deutschrap` und `NDW` in `genre_aliases.yaml`
ergänzen) ist die fachlich am wenigsten invasive Option — sie nutzt exakt
das bereits 73-fach etablierte, bewährte Muster, erfordert keine
Code-Änderung an `GenreProcessor`/`GenreMapper`, und ist vollständig mit
ARCH-013/014 kompatibel, da sie ausschließlich den bereits höchstpriorisierten
Direkt-Match-Zweig nutzt.

Dies ist eine **Empfehlung, keine Entscheidung** — die eigentliche
fachliche Entscheidung (Variante A vs. B vs. Kombination, sowie ob Klasse
B mitbehoben werden soll) obliegt einer eigenen, ausdrücklich freigegebenen
ARCH-015 Phase 2.

---

## N. Offene Entscheidungen

1. Soll Klasse A1 überhaupt behoben werden, oder ist das dokumentierte
   Restrisiko (siehe I) tragbar?
2. Soll Klasse B (`NDW`) in derselben Phase mitbehoben werden, oder
   separat?
3. Falls Variante A gewählt wird: soll der Self-Key auch für
   `GenreMapper` (`genre_overrides.yaml`/`genre_aliases.yaml`-Dopplung,
   s. F) konsistent nachgezogen werden, oder bleibt `GenreMapper`
   unverändert (da dort ohnehin stabil)?
4. Soll die in F dokumentierte, nicht bewertete Alias-/Override-Dopplung
   für `Drum & Bass`-Synonyme als eigener, separater Befund
   weiterverfolgt werden (außerhalb ARCH-015)?

---

## O. Regression / Verifikation

- **Gezielte Tests:** `tests/test_genre_canonical_idempotency_characterization.py`
  → 15/15 passed.
- **Vollständige Regression:** `pytest tests/ -q` → **1092 passed**, 15
  bekannte Vorbestandsfehler (identisch zu allen vorherigen Phasen),
  0 neue Fehlschläge.
- **Baseline-Vergleich:** 1077 (POST-ARCH-014-Stand) → 1092 (+15, exakt
  die neuen Characterization-Tests).
- **Diff-/Scope-Audit:** `git diff --stat -- services/ klassen/ utils/
  mapping/` → **0 Zeilen Produktionscode geändert**. Einzige neue Datei:
  der Testfile. Keine YAML-Datei verändert.

---

## P. Commit / Branch / PR

- **Branch:** `arch-015/phase1-genre-canonical-idempotency-characterization`
  (gestapelt auf `arch-014/phase2-genre-specificity-implementation`, PR
  #34, da die Tests den ARCH-014-Phase-2-Fix voraussetzen — analog zum
  etablierten Stacking-Muster dieser Session).
- Commit-Hash und PR-Nummer: siehe Abschlussbericht im Chat (nach
  `git commit`/`git push`/`gh pr create`).

---

## Q. Entscheidungsgate

**ARCH-015 Phase 1 — Characterization abgeschlossen.**
**Keine Produktionsänderung durchgeführt.**
**Keine Lösungsvariante umgesetzt.**
**STOPP.**
**Warte auf ausdrückliche Freigabe für eine mögliche Phase 2.**
