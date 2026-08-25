# MusicBot ARCH-016 — Genre Canonical-Case / Acronym Characterization

**Status:** Phase 1 (Characterization) abgeschlossen. Keine Produktionsänderung.
Keine YAML-Änderung. Keine Lösungsvariante umgesetzt. Wartet auf ausdrückliche
Freigabe für eine mögliche Phase 2.

**Ausgangspunkt:** ARCH-015 Phase 2 (`docs/MusicBot_ARCH-015_Genre_Canonical_Idempotency_Characterization.md`,
Abschnitt „Phase 2 — Self-Alias-Implementierung") behob Klasse A1
(`New York Drill`, `Aggro Deutschrap`) durch Self-Alias-Keys, ließ aber
Klasse B (`NDW` → `Ndw`) bewusst unbehandelt — explizite Scope-Grenze
dieser Phase. Zentrale Frage: ist `NDW → Ndw` ein isolierter Datenfehler
oder Ausdruck eines allgemeineren Problems bei kanonischen Genre-Werten
mit besonderer Groß-/Kleinschreibung bzw. Akronymen?

---

## A. Ausgangsbefund

Verifiziert gegen den aktuellen Repository-Stand (`main`, Commit `24a5ff2`):

```
"NDW" → normalize() → "Ndw"
```

- 115 eindeutige kanonische Werte in `GenreProcessor.GENRE_NORMALIZATION`.
- Genau **1** instabil: `NDW` → `Ndw`.
- `New York Drill` und `Aggro Deutschrap` bestätigt idempotent
  (ARCH-015 Phase 2 hält).
- Keine unbeabsichtigten Produktionsänderungen seit ARCH-015 Phase 2
  (`git diff --stat -- services/ klassen/ utils/ mapping/` gegenüber
  dem letzten ARCH-015-Commit: leer, bis auf die für ARCH-016 neu
  hinzugefügte Testdatei).

Der Ausgangsstand entspricht vollständig den im Auftrag genannten
Annahmen — keine Abweichung, keine Arbeitsunterbrechung nötig.

---

## B. Vollständige Case-/Acronym-Matrix

Von 115 kanonischen Werten besitzen **10** eine besondere Case-Struktur
(Akronym, Bindestrich-Großbuchstabe oder `&`):

| Kanonischer Wert | Self-Alias-Key? | Substring-Kandidaten | 2. Lauf | Stabil | Mechanismus |
|---|---|---|---|---|---|
| `C-Pop` | ja | `pop`, `c-pop` | `C-Pop` | ja | Direkt-Match |
| `G-Funk` | ja | `g-funk`, `funk` | `G-Funk` | ja | Direkt-Match |
| `G-House` | ja | `house`, `g-house` | `G-House` | ja | Direkt-Match |
| `J-Pop` | ja | `pop`, `j-pop` | `J-Pop` | ja | Direkt-Match |
| `K-Pop` | ja | `pop`, `k-pop` | `K-Pop` | ja | Direkt-Match |
| `Lo-Fi` | ja | `lo-fi` | `Lo-Fi` | ja | Direkt-Match |
| `R&B` | ja | `r&b` | `R&B` | ja | Direkt-Match |
| `UK Drill` | ja | `drill`, `uk drill` | `UK Drill` | ja | Direkt-Match |
| `UK Rap` | ja | `rap`, `uk rap` | `UK Rap` | ja | Direkt-Match |
| **`NDW`** | **nein** | **keine** | **`Ndw`** | **nein** | **Fallback (`.capitalize()`)** |

Zusätzlich, außerhalb der reinen Case-/Akronym-Betrachtung, aber relevant
für die vollständige Idempotenz-Bilanz: **4** kanonische Werte insgesamt
besitzen keinen Self-Alias-Key (nicht auf Mehrwort-Werte beschränkt, wie
in ARCH-015 Phase 1 — dort wurde nur die 77-elementige Mehrwort-Teilmenge
geprüft):

| Kanonischer Wert | Substring-Kandidaten | 2. Lauf | Stabil |
|---|---|---|---|
| `Afro` | keine | `Afro` | ja |
| `Drum & Bass` | keine | `Drum & Bass` | ja |
| `Liquid Drum & Bass` | keine | `Liquid Drum & Bass` | ja |
| `NDW` | keine | `Ndw` | **nein** |

`Afro` wurde in ARCH-015 Phase 1 nicht erfasst, da dort ausschließlich
die 77 Mehrwort-Werte geprüft wurden — `Afro` ist ein Einwort-Wert. Der
Fund ist unkritisch (stabil), erweitert aber das Bild: das
„kein-Self-Key"-Muster ist nicht auf Mehrwort-Werte beschränkt.

---

## C. Klassifikation

| Klasse | Definition | Anzahl | Beispiele |
|---|---|---:|---|
| **A** | semantischer Genre-Wechsel beim 2. Durchlauf | **0** | (ARCH-015 Phase 2 hat die einzigen 2 bekannten Fälle behoben) |
| **B** | semantisch gleiches Genre, falsche Schreibweise | **1** | `NDW` → `Ndw` |
| **C** | stabil trotz fehlendem Self-Alias (anderer Pfad greift korrekt) | **3** | `Afro`, `Drum & Bass`, `Liquid Drum & Bass` |
| stabil (mit Self-Key) | — | 111 | u. a. alle 9 anderen Akronym-/Sonderfälle |

**Kernaussage:** Unter allen 115 kanonischen Werten ist `NDW` der
**einzige** Vertreter von Klasse B. Das ist keine Aussage über einen
einzigen geprüften Einzelfall, sondern das Ergebnis einer vollständigen
Prüfung aller 115 Werte — `NDW` ist damit durch exhaustive Prüfung
bestätigt als tatsächlich isolierter Fall, nicht bloß als das einzige
bisher zufällig entdeckte Beispiel.

---

## D. Root Cause

Kontrollfluss `GenreProcessor.normalize_genre_name("NDW")`
(`services/metadata/genre_processor.py:341-400`):

```text
1. genre_lower = "ndw"
2. "ndw" in GENRE_NORMALIZATION?                    → False (kein Self-Key)
3. Wortgrenzen-Substring-Kandidaten für "ndw"?        → [] (keine)
4. → Fallback (Zeile 393-400):
     words = "NDW".split() = ["NDW"]
     "ndw" in small_words?                            → False
     → "NDW".capitalize()                             → "Ndw"
5. Ergebnis: "Ndw"
```

Der Fallback-Mechanismus ist ein simpler Title-Case-Kapitalisierer ohne
jede Akronym-Sonderbehandlung — er nimmt an, dass jedes „Wort" ein
normales Wort ist, bei dem nur der erste Buchstabe großzuschreiben und
der Rest kleinzuschreiben ist. Für Akronyme (mehrere zusammenhängende
Großbuchstaben) ist diese Annahme falsch.

**Warum ist `NDW` der einzige betroffene Fall?** Weil alle anderen 9
Akronym-/Sonderfälle jeweils einen eigenen Self-Alias-Key besitzen
(z. B. `"k-pop": "K-Pop"`, `"r&b": "R&B"`) und dadurch den
Direkt-Match-Zweig (Zeile 356-357) erreichen, **bevor** der
Fallback-Pfad überhaupt relevant wird. `NDW` ist der einzige kanonische
Wert, der gleichzeitig (a) keinen Self-Key besitzt, (b) keine
Substring-Kandidaten hat, und (c) eine Case-Struktur besitzt, die vom
Fallback nicht korrekt reproduziert wird.

---

## E. GenreMapper-Vergleich

`utils/genre_map.py::GenreMapper.normalize_genre_name()` wurde
**separat** verifiziert, nicht als identisch zu `GenreProcessor`
angenommen:

```text
1. genre_lower = "ndw"
2. "ndw" in self.overrides?                          → False
3. "ndw" in self.genre_aliases?                       → False
4. → Fallback:
     words = "NDW".split() = ["NDW"]
     "NDW".upper() in ("EDM","R&B","UK","US","DJ","MC")? → False
     "-" in "NDW"?                                     → False
     → else-Zweig: "NDW".capitalize()                  → "Ndw"
5. Ergebnis: "Ndw"
```

**Wichtiger Unterschied:** `GenreMapper` besitzt bereits eine **explizite
Akronym-Erhaltungsliste** (`EDM`, `R&B`, `UK`, `US`, `DJ`, `MC`) im
Fallback-Pfad — eine Form von Variante C/D (siehe unten), die bereits
teilweise implementiert ist, aber hartkodiert statt datengetrieben und
unvollständig (deckt nur 6 Akronyme ab, `NDW` fehlt). Trotz dieser
zusätzlichen Infrastruktur liefert auch `GenreMapper` für `NDW` dasselbe
falsche Ergebnis (`Ndw`), da `NDW` schlicht nicht in der Liste steht.

Beide Implementierungen sind für `NDW` unabhängig voneinander betroffen
— **gleiches Symptom, zwei getrennte Codepfade**, wobei `GenreMapper`
bereits einen (unvollständigen) Lösungsansatz für einen Teil dieser
Fallklasse enthält.

Kein produktiver Nachweis für `NDW` in `genre_hierarchy.yaml`,
`artist_genre.yaml` oder `channel_genre.yaml` gefunden — anders als
`New York Drill` (das in ARCH-015 aktiv in `artist_genre.yaml` verwendet
wurde), ist `NDW` aktuell nicht produktiv als kuratierter Wert im
Einsatz. Geringeres reales Risiko als die ARCH-015-Klasse-A1-Fälle.

---

## F. Lösungsvarianten A–D

### Variante A — Self-Alias

```yaml
"ndw": "NDW"
```

- **Scope:** 1 YAML-Zeile.
- **Verhalten:** identisches, bereits 73+2-fach etabliertes Muster
  (ARCH-013/014/015).
- **Risiko:** sehr gering.
- **Nebenwirkungen:** keine erwartet.
- **Rückwärtskompatibilität:** vollständig — reiner Datenzusatz.
- **Testaufwand:** gering (Assertions invertieren, etabliertes Muster).
- **Löst `NDW`:** ja, direkt.
- **Löst weitere potenzielle Fälle automatisch:** **nein** — jeder
  künftige neue Akronym-Kanonwert ohne Self-Key bräuchte erneut einen
  manuellen Eintrag. Reine Symptombehandlung pro Einzelfall.

### Variante B — Case-preserving Fallback

Der Fallback bewahrt die Schreibweise des Eingabewerts, statt sie zu
verändern, wenn keine Normalisierungsregel greift (z. B.: wenn `genre`
bereits ausschließlich aus Großbuchstaben besteht oder keine
Kleinbuchstaben enthält, unverändert zurückgeben statt zu
kapitalisieren).

- **Scope:** kleine Code-Änderung im Fallback-Zweig beider
  Implementierungen (`genre_processor.py` UND `utils/genre_map.py`, da
  strukturell unabhängige Duplikate).
- **Verhalten:** würde `NDW` lösen, aber auch das Verhalten für JEDEN
  anderen unbekannten Eingabewert verändern, der zufällig komplett
  großgeschrieben ist (z. B. ein versehentlich in Versalien getaggter
  Rohwert von einer externen API) — Risiko einer unbeabsichtigten
  Verhaltensänderung außerhalb des Akronym-Sonderfalls.
- **Risiko:** mittel — verändert generelles Fallback-Verhalten, nicht
  nur den `NDW`-Fall.
- **Nebenwirkungen:** potenziell für beliebige zukünftige
  Roh-Genre-Strings mit ungewöhnlicher Schreibweise.
- **Rückwärtskompatibilität:** müsste gegen alle bestehenden
  Fallback-Testfälle (Title-Case-Erwartungen) geprüft werden.
- **Testaufwand:** mittel-hoch.
- **Löst `NDW`:** ja.
- **Löst weitere potenzielle Fälle automatisch:** ja, systematisch für
  jeden zukünftigen komplett-großgeschriebenen Kanonwert ohne Self-Key.

### Variante C — Generische Akronym-Erkennung

Ein allgemeiner Mechanismus erkennt Akronyme (z. B. Heuristik: Wort ist
komplett groß UND kurz, z. B. ≤ 4 Zeichen) und schließt sie von
`.capitalize()` aus.

- **Scope:** Code-Änderung im Fallback-Zweig, ggf. beidseitig
  (`GenreProcessor` + `GenreMapper`), oder Erweiterung/Vereinheitlichung
  der bereits in `GenreMapper` vorhandenen hartkodierten Liste zu einer
  generischen Heuristik.
- **Verhalten:** würde `NDW` lösen und wäre robuster gegen zukünftige,
  heute unbekannte Akronym-Kanonwerte.
- **Risiko:** mittel — eine Heuristik (z. B. „alles ≤ 4 Zeichen komplett
  groß ist ein Akronym") kann falsch-positive Treffer erzeugen (z. B.
  ein kurzes, zufällig komplett großgeschriebenes Nicht-Akronym-Wort).
- **Nebenwirkungen:** schwer vollständig vorherzusagen ohne konkrete
  Heuristik-Definition.
- **Rückwärtskompatibilität:** müsste sorgfältig gegen alle 115
  kanonischen Werte und alle Fallback-Testfälle geprüft werden.
- **Testaufwand:** hoch (Heuristik muss gegen viele Gegenbeispiele
  verifiziert werden).
- **Löst `NDW`:** ja.
- **Löst weitere potenzielle Fälle automatisch:** ja, am umfassendsten
  von allen vier Varianten — aber mit dem höchsten Risiko unbeabsichtigter
  Nebenwirkungen.

### Variante D — Bewusstes Datenmodell

Akronyme werden explizit als eigene, benannte Kategorie in den
Alias-/Mapping-Daten modelliert (z. B. eine dedizierte
`GENRE_ACRONYMS`-Liste in einer YAML-Datei, aus der sowohl der
Self-Alias-Mechanismus als auch eine etwaige Fallback-Erhaltung
gespeist werden).

- **Scope:** neue Datenstruktur — vom Auftrag in vorherigen Phasen
  wiederholt explizit ausgeschlossen ("keine neue gemeinsame
  Alias-Struktur"), hier nur analytisch bewertet, nicht empfohlen.
- **Verhalten:** würde `GenreMapper`s bereits vorhandene, aber
  hartkodierte Akronym-Liste (`EDM`, `R&B`, `UK`, `US`, `DJ`, `MC`)
  ablösen und vereinheitlichen.
- **Risiko:** gering-mittel — mehr Struktur, aber auch mehr
  Änderungsfläche und eine neue, zu pflegende Datenquelle.
- **Nebenwirkungen:** könnte `GenreMapper` und `GenreProcessor` enger
  koppeln (gemeinsame Datenquelle) — potenziell wünschenswert
  langfristig, aber ein größerer architektonischer Schritt.
- **Rückwärtskompatibilität:** unproblematisch, wenn rein additiv
  eingeführt.
- **Testaufwand:** hoch (neue Datenstruktur + beide Implementierungen
  müssten sie konsumieren).
- **Löst `NDW`:** ja, über explizite Modellierung.
- **Löst weitere potenzielle Fälle automatisch:** ja, sofern zukünftige
  Akronyme konsequent in die neue Struktur eingetragen werden — löst
  aber nicht automatisch, sondern erfordert weiterhin manuelle Pflege
  (wie Variante A, nur zentralisierter).

---

## G. Empfehlung

**Empfehlung für eine mögliche ARCH-016 Phase 2 (keine Umsetzung in
dieser Phase):** Variante A (Self-Alias `"ndw": "NDW"`) ist die
fachlich am wenigsten invasive Option — identisches, bereits 75-fach
(73 aus historischem Bestand + 2 aus ARCH-015 Phase 2) etabliertes
Muster, keine Code-Änderung, minimales Risiko, sofort testbar.

Da `NDW` durch die vollständige Prüfung in Abschnitt C als der
**einzige** aktuell betroffene Wert bestätigt ist (nicht nur der
einzige bisher gefundene), löst Variante A das gesamte aktuell bekannte
Problem vollständig — die in Variante B/C beschriebene „automatische
Absicherung gegen zukünftige Fälle" ist bei aktuell 0 weiteren
bekannten Kandidaten kein akuter Zusatznutzen, sondern vorbeugende
Architektur für ein noch nicht eingetretenes Problem.

Dies ist eine **Empfehlung, keine Entscheidung** — ob überhaupt
behoben werden soll (`NDW` ist aktuell nicht produktiv genutzt, siehe
Abschnitt E) und welche Variante gewählt wird, obliegt einer eigenen,
ausdrücklich freigegebenen ARCH-016 Phase 2.

---

## H. Tests

Neue Datei `tests/test_genre_canonical_case_acronym_characterization.py`
(22 Tests, 5 Klassen), ausschließlich aktuelles Verhalten dokumentierend:

- `TestNdwCurrentlyUnstable` (5 Tests) — Root-Cause-Rekonstruktion für
  `GenreProcessor`
- `TestGenreMapperSeparatelyVerifiedForNdw` (3 Tests) — unabhängige
  Gegenprobe an `GenreMapper`, inkl. Nachweis der vorhandenen, aber
  unvollständigen Akronym-Liste
- `TestSpecialCaseValuesStableViaSelfKey` (9 parametrisierte Tests) —
  alle 9 stabilen Akronym-/Sonderfälle
- `TestClassCStableWithoutSelfKey` (3 parametrisierte Tests) — `Afro`,
  `Drum & Bass`, `Liquid Drum & Bass`
- `TestFullCanonicalValueCaseInventory` (2 Tests) — Regressionswächter
  für „genau 1 instabiler Wert" und „genau 4 Werte ohne Self-Key"

**Ergebnis: 22/22 passed.**

---

## I. Regression

- Gezielt: neue Datei + beide ARCH-014/015-Testdateien → **73/73
  passed**.
- Vollständige Regression: `pytest tests/ -q` → **1114 passed** (1092 +
  22), 15 bekannte Vorbestandsfehler, identisch zu allen vorherigen
  Phasen.
- **Delta vollständig erklärt:** +22 entspricht exakt den neuen
  ARCH-016-Characterization-Tests, keine weiteren Verschiebungen.

---

## J. Diff-/Scope-Audit

- `git diff --stat -- services/ klassen/ utils/ mapping/` → **leer**,
  keine Produktions- oder YAML-Änderung.
- Einzige neue Datei:
  `tests/test_genre_canonical_case_acronym_characterization.py`.
- Keine neuen Python-Imports, keine neuen Dependency-Edges,
  `services/*→handlers/*` und `services/*→klassen/*` weiterhin 0.
- Kein bestehender Test verändert oder gelöscht.

---

## K. Commit / Branch / PR

- **Branch:** `arch-016/phase1-genre-canonical-case-acronym-characterization`
  (erstellt von `main`, da `main` nach dem Merge von ARCH-014
  Phase 2/ARCH-015 Phase 1+2 bereits den vollständigen Vorgänger-Stand
  enthält).
- Commit-Hash und PR-Nummer: siehe Abschlussbericht im Chat.

---

## L. Offene Befunde

Nur tatsächlich bestätigte Punkte:

1. `NDW` bleibt der einzige instabile kanonische Wert unter allen 115 —
   bestätigt durch vollständige Prüfung, kein Restrisiko unentdeckter
   weiterer Fälle innerhalb der aktuellen `genre_aliases.yaml`.
2. `GenreMapper` besitzt bereits eine unvollständige, hartkodierte
   Akronym-Erhaltungsliste (`EDM`, `R&B`, `UK`, `US`, `DJ`, `MC`) — ein
   bereits vorhandener, aber nie auf `NDW` ausgeweiteter Teillösungsansatz.
   Nicht bewertet, ob diese Liste selbst vollständig/korrekt ist
   (außerhalb des ARCH-016-Scopes).
3. `NDW` ist aktuell nicht produktiv in `genre_hierarchy.yaml`,
   `artist_genre.yaml` oder `channel_genre.yaml` referenziert — geringeres
   reales Risiko als die ARCH-015-Klasse-A1-Fälle.

---

## Entscheidungsgate

**ARCH-016 Phase 1 — Characterization abgeschlossen.**
**Keine Produktionsänderung durchgeführt.**
**Keine YAML-Änderung durchgeführt.**
**Keine Lösungsvariante umgesetzt.**
**STOPP.**
**Warte auf ausdrückliche Freigabe für eine mögliche Phase 2.**
