# ARCH-013 Phase 1 — Genre Alias Characterization

## Status

**Phase 1 abgeschlossen (2026-08-24). Nur Characterization-Tests
hinzugefügt (22 Tests, `tests/test_genre_alias_characterization.py`).
Keine Produktionscodeänderung, kein Refactoring, keine Umbenennung.**
Entscheidungsgate am Ende, wartet auf Freigabe für Phase 2.

---

## 1. Ausgangslage

Der `POST-ARCH-012 SERVICES ARCHITECTURE AUDIT`
(`docs/archive/post-arch/POST-ARCH-012_Services_Architecture_Audit.md`, Abschnitt E.6)
identifizierte, dass `mapping/genre_aliases.yaml` von zwei unabhängigen
Klassen geladen und normalisiert wird:

- `utils.genre_map.GenreMapper` (`self.genre_aliases`)
- `services.metadata.genre_processor.GenreProcessor` (`self.GENRE_NORMALIZATION`)

Diese Phase prüft belastbar, ob beide Implementierungen dieselbe fachliche
Semantik besitzen, wo sie divergieren, und ob eine Zentralisierung
sinnvoll wäre. Reine Analysephase — keine Umsetzung.

**Wichtiger Befund vorab, der die Ausgangslage präzisiert:** Die
tatsächliche Divergenz ist größer als der ursprüngliche E.6-Befund
vermuten ließ. Es sind nicht zwei Implementierungen derselben einen Datei,
sondern `GenreMapper` konsultiert zusätzlich eine **zweite** YAML-Datei
(`mapping/genre_overrides.yaml`) mit Vorrang vor den Aliasen — eine Datei,
die `GenreProcessor` überhaupt nicht kennt. Details in Abschnitt 5/8.

---

## 2. YAML-Struktur

### 2.1 `mapping/genre_aliases.yaml`

- 322 Einträge, ein Top-Level-Key `GENRE_ALIASES`, flaches `Dict[str, str]`.
- 112 eindeutige Zielwerte (canonical genres).
- 320/322 Keys sind vollständig lowercase geschrieben. **2 Ausnahmen:**
  `"Hip-Hop"` und `"Hip - Hop"` (beide → `"Hip Hop"`) — beide stehen
  inmitten eines sonst durchgängig lowercase geschriebenen Blocks, offenbar
  Copy-Paste-Reste aus einer anderen Schreibweisen-Quelle.
- Werte sind durchgängig Title-Case-Strings, teils mit Sonderzeichen
  (`R&B`, `K-Pop`, `Lo-Fi`) oder Ampersand-Konstruktion (`Drum & Bass`).

**Repräsentative Beispiele:**

| Kategorie | Beispiel |
|---|---|
| 1. Einfacher Alias | `"pop": "Pop"` |
| 2. Groß-/Kleinschreibung | `"Hip-Hop": "Hip Hop"` (Ausnahme von der sonst durchgängigen lowercase-Konvention) |
| 3. Mehrwort-Alias | `"ruhrpott rap": "Ruhrpott Rap"` |
| 4. Sonderzeichen | `"r'n'b": "R&B"`, `"r & b": "R&B"` |
| 5. Mehrere Aliase → ein Genre | 18 Einträge → `"Rock"`; 30 Einträge → `"Hip Hop"` |
| 6. Kollisionskandidat (unterschiedliche Werte trotz Nähe) | `"synth-pop": "Pop"` vs. `"synthpop": "Electronic"` |
| 7. Divergent behandelbar | `"Hip - Hop"` (Leerzeichen um Bindestrich + Großschreibung) |

### 2.2 `mapping/genre_overrides.yaml` (neu in den Scope einbezogen, siehe 1.)

- 156 Einträge, Top-Level-Key `GENRE_OVERRIDES`, ebenfalls flaches
  `Dict[str, str]`, thematisch stark überlappend mit `genre_aliases.yaml`
  (155 gemeinsame, lowercased Keys).
- **Nur von `GenreMapper` geladen** (`utils/genre_map.py:269-271`), mit
  **höherer Priorität** als `genre_aliases.yaml` in
  `normalize_genre_name()` (Schritt 1 vor Schritt 2).
- **4 direkte Wertkonflikte** zu `genre_aliases.yaml` bei identischem
  (lowercased) Schlüssel — empirisch verifiziert (siehe Abschnitt 6):

  | Key | `genre_aliases.yaml` | `genre_overrides.yaml` |
  |---|---|---|
  | `electropop` | `Pop` | `Electropop` |
  | `chamber pop` | `Pop` | `Chamber Pop` |
  | `tech house` | `House` | `Tech House` |
  | `ruhrpott rap` | `Ruhrpott Rap` | `Deutschrap` |

  Da `GenreMapper` Overrides vor Aliasen prüft, gewinnt für diese 4
  Eingaben immer der Override-Wert — `genre_aliases.yaml`s eigener Eintrag
  ist für diese 4 Schlüssel in `GenreMapper` faktisch **unerreichbar** (tot,
  analog zum Mixed-Case-Befund in 2.1, aber mit einer anderen Ursache).

---

## 3. GenreMapper-Datenfluss

```text
mapping/genre_aliases.yaml
   ↓  load_yaml_data() (utils/genre_map.py:274-275)
   ↓  KEINE Normalisierung der Keys beim Laden — Keys bleiben exakt wie im YAML
self.genre_aliases: Dict[str, str]   (322 Einträge, 2 davon mixed-case)

mapping/genre_overrides.yaml
   ↓  load_yaml_data() (utils/genre_map.py:269-270)
   ↓  KEINE Normalisierung der Keys beim Laden
self.overrides: Dict[str, str]        (156 Einträge)

normalize_genre_name(genre_name):
   genre_lower = genre_name.strip().lower()      # IMMER lowercase
   1. if genre_lower in self.overrides:  return self.overrides[genre_lower]
   2. if genre_lower in self.genre_aliases:  return self.genre_aliases[genre_lower]
   3. sonst: Wort-für-Wort-Capitalize-Fallback (Sonderfälle: EDM/R&B/UK/US/DJ/MC
      bleiben komplett groß, Bindestrich-Wörter werden pro Teilwort capitalized)
```

**Wichtige Eigenschaften:**

- `@lru_cache(maxsize=2048)` auf `normalize_genre_name()` — Instanzmethode,
  gecached pro `(self, genre_name)`-Paar.
- Case-Sensitivity: Lookup-Key ist immer lowercase, aber die
  **gespeicherten Dict-Keys sind es nicht zwingend** (siehe 2.1) — daraus
  entsteht die Mixed-Case-Divergenz.
- Kein Teilstring-/Fuzzy-Matching in `normalize_genre_name()` selbst
  (Fuzzy-Matching existiert in der Klasse, aber nur für Artist-/
  Channel-Namen in `determine_genre()`, nicht für Genre-Strings).
- Tokenisierung im Fallback-Pfad (Schritt 3) erfolgt über
  `genre_name.split()` auf dem **Original-String** (nicht auf
  `genre_lower`) — führt bei Eingaben wie `"Hip - Hop"` zu einem
  Leer-Token (siehe Abschnitt 6).
- `normalize_genre_name()` ist nur EIN Baustein von `determine_genre()`
  (Schritt 5 von 5) — Artist-/Channel-Mapping (Schritt 1-3) und
  Regex-Regeln (Schritt 4, strukturell tot, siehe Abschnitt 9) haben
  Vorrang und werden hier nicht erneut behandelt (außerhalb des Scopes
  dieser Phase).

---

## 4. GenreProcessor-Datenfluss

```text
mapping/genre_aliases.yaml
   ↓  eigener, unabhängiger Loader: _load_genre_normalization_from_yaml()
   ↓  (services/metadata/genre_processor.py:741-767)
   ↓  Keys werden explizit lowercased: {alias.lower(): canonical for alias, canonical in aliases.items()}
self.GENRE_NORMALIZATION: Dict[str, str]   (321 Einträge — 322 YAML-Einträge,
                                             aber "Hip-Hop"->"hip-hop" kollabiert
                                             mit dem bereits vorhandenen Key
                                             "hip-hop", daher 1 Eintrag weniger)

normalize_genre_name(genre):
   genre_lower = genre.lower().strip()
   1. if genre_lower in self.GENRE_NORMALIZATION:  return [...]          # exakter Match
   2. for key, value in self.GENRE_NORMALIZATION.items():
          if key in genre_lower:  return value                           # TEILSTRING-Match
   3. sonst: Wort-für-Wort-Capitalize mit small_words-Ausnahmeliste
      ("and", "of", "the", "a", "an", "in", "to", "for", "with", "on", "at", "by")
```

**Wichtige Eigenschaften:**

- **Kein** `lru_cache` auf dieser Methode (im Gegensatz zu `GenreMapper`).
- **Kein** Zugriff auf `mapping/genre_overrides.yaml` — diese Datei ist für
  `GenreProcessor` nicht sichtbar.
- **Zusätzlicher Teilstring-Match-Schritt** (Schritt 2), den `GenreMapper`
  nicht besitzt — jeder String, der einen bekannten Alias als Teilstring
  enthält, wird darüber aufgelöst, unabhängig davon, ob der String selbst
  ein gültiger Alias ist.
- Die Teilstring-Suche iteriert `self.GENRE_NORMALIZATION` in
  Insertion-Order (== YAML-Dateireihenfolge) und gibt beim **ersten**
  Treffer zurück — kein Longest-Match, keine Priorisierung nach
  Spezifität. Dass mehrwortige, speziellere Aliase (z. B.
  `"ruhrpott rap"`) in der YAML-Datei VOR den generischeren Kurzformen
  (z. B. `"rap"`) stehen, ist reiner Zufall der Datei-Reihenfolge, kein
  gesicherter Mechanismus.
- Wird intern von `prioritize_genres()` verwendet (Multi-Tag-Priorisierung
  für MusicBrainz-/Last.fm-Rohtags, siehe ARCH-012), nicht nur direkt
  aufrufbar.
- Fallback bei leerem Input: `"Unknown"` (nicht `""` wie bei `GenreMapper`)
  — eine reine Signatur-/Konventionsdivergenz, keine Alias-Frage.

---

## 5. Normalisierungsvergleich

| Kriterium | `GenreMapper.normalize_genre_name()` | `GenreProcessor.normalize_genre_name()` |
|---|---|---|
| Quelle(n) | `genre_aliases.yaml` **+ `genre_overrides.yaml`** (Vorrang) | nur `genre_aliases.yaml` |
| Key-Case beim Laden | unverändert (2 Mixed-Case-Keys bleiben bestehen) | immer lowercased |
| Lookup-Modus | nur exakter Match | exakter Match, dann Teilstring-Match |
| Caching | `lru_cache(2048)` | kein Cache |
| Fallback bei unbekanntem Genre | Wort-Capitalize auf Original-String | Wort-Capitalize mit Ausnahmewörtern (small_words) |
| Leerer Input | `""` | `"Unknown"` |
| Aufrufkontext | Schritt 5 von 5 in `determine_genre()`, Single-String | innerhalb `prioritize_genres()`, pro Tag in einer Multi-Tag-Liste |

---

## 6. Alias-Vergleichsmatrix

Alle Werte real ausgeführt (kein hypothetisches Beispiel), siehe
`tests/test_genre_alias_characterization.py` für die dauerhaft
eingefrorene Fassung.

| Eingabe | GenreMapper | GenreProcessor | identisch? | Ursache bei Abweichung |
|---|---|---|---|---|
| `deutschrap` (einfacher Alias) | `Deutschrap` | `Deutschrap` | ✅ | — |
| `DEUTSCHRAP` (Großschreibung) | `Deutschrap` | `Deutschrap` | ✅ | — |
| `hip-hop` (Kleinschreibung) | `Hip Hop` | `Hip Hop` | ✅ | — |
| `ruhrpott rap` (Mehrwort-Alias) | `Deutschrap` | `Ruhrpott Rap` | ❌ | Override-Konflikt (Abschnitt 2.2) |
| `Hip - Hop` (Sonderzeichen + Case) | `Hip  Hop` (doppeltes Leerzeichen!) | `Hip Hop` | ❌ | Mixed-Case-Key unerreichbar (Abschnitt 2.1) |
| `Hip-Hop` (Case, aber ohne Leerzeichen) | `Hip Hop` | `Hip Hop` | ✅ | zufällig identisch — trifft in GenreMapper NICHT den Mixed-Case-Alias, sondern den separaten lowercase-Key `"hip-hop"` |
| `r&b` (Alias-Kollision, mehrere Schreibweisen) | `R&B` | `R&B` | ✅ | — |
| `k-pop` (exakter Alias) | `K-Pop` | `K-Pop` | ✅ | — |
| `britpop` (unbekannter Wert, enthält Alias als Teilstring) | `Britpop` | `Pop` | ❌ | Teilstring-Match nur in GenreProcessor |
| `` (leerer Wert) | `` | `Unknown` | ❌ | Signatur-Konvention, keine Alias-Frage |

**7 von 10 getesteten Fällen identisch, 3 divergieren — alle 3 Divergenzen
sind auf konkrete, benannte Ursachen zurückführbar, keine zufällige
Instabilität.**

---

## 7. Characterization-Tests

Neu: `tests/test_genre_alias_characterization.py`, 22 Tests, 5
Testklassen:

- `TestAliasLoadingDivergence` (4 Tests) — Mixed-Case-Key-Erreichbarkeit.
- `TestOverrideLayerOnlyAffectsGenreMapper` (5 Tests, parametrisiert über
  alle 4 bekannten Konflikte) — Override-Vorrang nur in `GenreMapper`.
- `TestSubstringMatchingOnlyInGenreProcessor` (2 Tests) — Teilstring-Match
  nur in `GenreProcessor`.
- `TestBothImplementationsAgreeOnUnambiguousAliases` (9 Tests,
  parametrisiert) — Gegenprobe: für unambige Aliase liefern beide
  Implementierungen identische Ergebnisse.
- `TestYamlSourceCollisions` (2 Tests) — Konflikte, die bereits in den
  YAML-Quelldateien selbst angelegt sind, unabhängig vom Ladecode.

Alle 22 Tests grün gegen den aktuellen (unveränderten) Produktionscode.

---

## 8. Konkrete Divergenzen

Drei unabhängige, empirisch verifizierte Divergenzquellen:

1. **Override-Konflikt (4 Genres):** `electropop`, `chamber pop`,
   `tech house`, `ruhrpott rap` — `GenreMapper` und `GenreProcessor`
   liefern für denselben rohen Eingabestring unterschiedliche kanonische
   Genres. Betrifft `determine_genre()`s Schritt 5 (GenreMapper-Pfad)
   gegenüber `prioritize_genres()` (GenreProcessor-Pfad).
2. **Mixed-Case-Alias-Unerreichbarkeit:** `"Hip - Hop"` liefert in
   `GenreMapper` das fehlerhafte `"Hip  Hop"` (doppeltes Leerzeichen)
   statt des im YAML hinterlegten `"Hip Hop"`; `GenreProcessor` liefert
   korrekt `"Hip Hop"`.
3. **Teilstring-Match:** jeder String, der einen bekannten Alias als
   Teilstring enthält (z. B. `"britpop"`, `"some hip hop music"`), wird in
   `GenreProcessor` über diesen Alias aufgelöst, in `GenreMapper` nicht.

---

## 9. Fachliche Auswirkungen

- **Override-Konflikt:** direkt P0-relevant. `ruhrpott rap` ist der
  gravierendste Fall — abhängig davon, ob ein Track über
  `determine_genre_with_fallbacks()`s lokalen Pfad (GenreMapper,
  `"Deutschrap"`) oder über `prioritize_genres()` aus MusicBrainz-/Last.fm-
  Rohtags (GenreProcessor, `"Ruhrpott Rap"`) klassifiziert wird, erhält
  derselbe fachliche Sachverhalt zwei unterschiedliche, sich
  widersprechende Genre-Werte im selben System. Das ist keine
  hypothetische Randfall-Inkonsistenz, sondern ein aktiver, nicht
  dokumentierter Widerspruch zwischen zwei parallel gepflegten
  YAML-Dateien.
- **Mixed-Case-Alias:** geringe praktische Auswirkung (nur 1 konkreter,
  unwahrscheinlich formatierter Input-String betroffen: `"Hip - Hop"` mit
  Leerzeichen um den Bindestrich), aber ein klares Beispiel dafür, dass
  ein YAML-Eintrag in `GenreMapper` seit dessen Erstellung nie wirksam
  war.
- **Teilstring-Match:** zweischneidig. Für `prioritize_genres()`s
  eigentlichen Zweck (freie, oft mehrwortige externe Tags von MusicBrainz/
  Last.fm normalisieren) ist ein gewisses Maß an Teilstring-Toleranz
  vermutlich beabsichtigt bzw. hilfreich — aber die Implementierung hat
  keine Absicherung gegen falsche Treffer (kein Longest-Match, keine
  Wortgrenzenprüfung) und hängt von der zufälligen YAML-Reihenfolge ab.
  Ob dies eine bewusste Design-Entscheidung oder ein unbeabsichtigter
  Nebeneffekt ist, lässt sich aus dem Code allein nicht feststellen.

---

## 10. Varianten A/B/C

### Variante A — Gemeinsamer zentraler Alias-Loader/Service

- Fachliche Kohäsion: hoch (ein Ort für "was bedeutet dieser Alias").
- Duplikationsreduktion: hoch (1 Loader statt 2, potenziell auch
  `genre_overrides.yaml`-Konsolidierung).
- Verhaltensrisiko: **hoch** — erfordert eine explizite Entscheidung für
  alle 4 Override-Konflikte plus eine Entscheidung über Teilstring-Matching
  (aktivieren, deaktivieren, oder kontextabhängig), bevor überhaupt eine
  Migration beginnen kann.
- Testaufwand: hoch (beide Aufrufkontexte — Single-String in
  `determine_genre()`, Multi-Tag in `prioritize_genres()` — müssen weiter
  funktionieren).
- Migrationsaufwand: hoch (beide Klassen, evtl. neue Abstraktion).
- Dependency-Auswirkungen: neuer gemeinsamer Baustein zwischen `utils/`
  und `services/metadata/` — siehe Abschnitt 8 der Aufgabenstellung
  (Architektur-Grenzen).
- P0-Risiko: hoch (Genre-Domäne).
- Langfristige Wartbarkeit: **die beste** aller drei Varianten, aber nur
  erreichbar nach vorheriger fachlicher Klärung der 4 Konflikte.

### Variante B — Eine Implementierung wird alleinige Quelle

- Fachliche Kohäsion: mittel-hoch.
- Duplikationsreduktion: hoch.
- Verhaltensrisiko: **hoch** — welche der beiden wird "Gewinner"?
  `GenreProcessor` hätte dann keinen Zugriff mehr auf
  `genre_overrides.yaml`s 156 Einträge (Verlust von Overrides, die für
  151 von 156 Fällen mit den Aliasen übereinstimmen, aber eben für 4 nicht
  — der "Gewinn" für diese 4 Fälle wäre eine bewusste Entscheidung, kein
  Nebenprodukt). Umgekehrt würde `GenreMapper` den Teilstring-Match neu
  bekommen, was dessen bisher exaktes Lookup-Verhalten für Artist-/
  Channel-Namen (die dieselbe `_find_best_match`-Fuzzy-Logik nutzen,
  aber NICHT `normalize_genre_name()`) nicht direkt betrifft, aber
  `determine_genre()`s Schritt 5 grundlegend verändern würde.
- Testaufwand: hoch.
- Migrationsaufwand: mittel (weniger Code als Variante A, aber gleiche
  Entscheidungslast).
- Dependency-Auswirkungen: die verlierende Klasse bekäme eine neue
  Abhängigkeit auf die gewinnende (`services/metadata/` → `utils/` oder
  umgekehrt, je nach Wahl — beide Richtungen existieren im Repo bereits an
  anderer Stelle, siehe ARCH-Dependency-Audits).
- P0-Risiko: hoch.
- Langfristige Wartbarkeit: gut, aber schwächer als Variante A, da eine
  der beiden fachlichen "Perspektiven" (Single-String-Priorisierung vs.
  Multi-Tag-Priorisierung) untergeordnet würde.

### Variante C — Trennung bleibt bestehen

- Fachliche Kohäsion: aktuell **nicht gegeben** — die beiden
  Implementierungen sind keine bewusst getrennten, unterschiedlichen
  Verantwortungen, sondern eine historisch gewachsene Doppelimplementierung
  derselben Kernfrage ("was ist der kanonische Name für diesen
  Genre-String"), die zufällig an zwei Stellen unterschiedlich beantwortet
  wird.
- Duplikationsreduktion: keine (Status quo).
- Verhaltensrisiko: **keins durch diese Variante selbst** — aber die 4
  Override-Konflikte bleiben als aktiver, unbeabsichtigter Widerspruch im
  System bestehen (siehe Abschnitt 9).
- Testaufwand: keiner zusätzlich (Characterization-Tests aus Phase 1
  bleiben als Dokumentation bestehen).
- Migrationsaufwand: keiner.
- Dependency-Auswirkungen: keine.
- P0-Risiko: **das aktuelle, bereits bestehende Risiko bleibt
  unverändert** — nicht erhöht, aber auch nicht reduziert.
- Langfristige Wartbarkeit: schlechtest von allen drei Varianten auf
  lange Sicht (die 322+156 Einträge in zwei YAML-Dateien müssen weiterhin
  von Hand synchron gehalten werden, ohne dass ein Mechanismus
  Abweichungen erkennt).

**Bewertung:** Variante C wäre nur gerechtfertigt, wenn die beiden
Implementierungen tatsächlich unterschiedliche fachliche Verantwortungen
hätten (Single-String-Fallback vs. Multi-Tag-Priorisierung — das ist ein
echter Unterschied im Aufrufkontext, siehe Abschnitt 5). Diese
unterschiedlichen Aufrufkontexte rechtfertigen aber nicht, dass **derselbe
Alias-String** ("ruhrpott rap") zwei unterschiedliche, sich
widersprechende Zielgenres bekommt — das ist keine Frage der
Verantwortungstrennung, sondern eine Dateninkonsistenz zwischen
`genre_aliases.yaml` und `genre_overrides.yaml`. Variante A und B
scheitern beide daran, dass sie eine sofortige Entscheidung über diese 4
Konflikte erzwingen würden — und das ist laut Aufgabenstellung
ausdrücklich NICHT Teil dieser Phase.

---

## 11. Empfehlung

**Ergebnis B — Verhalten unterscheidet sich, fachlich relevant.**

Die beiden Implementierungen sind **nicht** durchgängig äquivalent — 3 von
10 in der Vergleichsmatrix getesteten repräsentativen Fällen weichen ab,
mit einer konkreten, empirisch verifizierten Ursache in jedem Fall. Der
schwerwiegendste Befund (4 direkte Wertkonflikte zwischen
`genre_aliases.yaml` und `genre_overrides.yaml`) ist **keine
Implementierungsfrage**, sondern eine **Dateninkonsistenz zwischen zwei
Mapping-Dateien**, die unabhängig von einer Code-Zentralisierung gelöst
werden müsste.

**Keine Zentralisierung jetzt.** Stattdessen wird folgende gezielte
fachliche Entscheidung als Voraussetzung für jede spätere ARCH-013 Phase 2
empfohlen:

1. Für jeden der 4 Konflikte (`electropop`, `chamber pop`, `tech house`,
   `ruhrpott rap`) muss eine bewusste Entscheidung getroffen werden, welcher
   Zielwert korrekt ist — vermutlich `genre_overrides.yaml`, da diese
   Datei laut Namenskonvention explizit für bewusste Sonderfälle gedacht
   ist (das aktuelle Verhalten von `GenreMapper`), aber das ist eine
   fachliche, keine technische Entscheidung.
2. Eine Entscheidung, ob der Teilstring-Match in
   `GenreProcessor.normalize_genre_name()` beabsichtigtes Verhalten ist
   (dann müsste er ggf. abgesichert werden — Wortgrenzen, Longest-Match)
   oder ein unbeabsichtigter Nebeneffekt (dann wäre er ein eigener,
   separater Bugfix-Kandidat, kein Architekturthema).
3. Der Mixed-Case-Alias-Bug (`"Hip - Hop"`) ist trivial und unabhängig von
   1./2. behebbar, aber nicht Teil dieser Phase (siehe Regel 3, keine
   Umsetzung).

Erst nach dieser fachlichen Klärung ergibt eine Empfehlung für Variante A
oder B Sinn. Eine ARCH-013 Phase 2 sollte daher **nicht** direkt als
"Architekturentscheidung" (Migrationsvariante wählen), sondern als
**"fachliche Entscheidung Genre-Alias-Konflikte"** aufgesetzt werden —
kleiner Scope, keine Code-Migration, nur eine Entscheidungstabelle für die
4 (+ potenziell weitere, noch nicht gefundene) Konfliktfälle.

---

## 12. Risiken

- **Wenn nichts unternommen wird:** die 4 Konflikte bleiben als stille,
  nicht dokumentierte Inkonsistenz bestehen. Neue Einträge in einer der
  beiden YAML-Dateien können jederzeit neue, unbemerkte Konflikte
  erzeugen — es gibt aktuell keinen automatisierten Vergleich zwischen
  `genre_aliases.yaml` und `genre_overrides.yaml` (die neuen
  Characterization-Tests in dieser Phase frieren nur die 4 BEKANNTEN
  Konflikte ein — ein 5. neuer Konflikt würde nicht automatisch auffallen,
  außer über `TestYamlSourceCollisions`, die bei Änderung an einer der
  Dateien neu ausgeführt werden muss).
- **Wenn vorschnell zentralisiert wird (Variante A/B ohne 1./2. aus
  Abschnitt 11):** stille Verhaltensänderung für mindestens 4 reale Genres
  in der P0-Domäne, ohne dass eine bewusste fachliche Entscheidung dahinter
  steht — genau das, was CLAUDE.md §15/§16/Regel 2 verhindern soll.
- **Bei einer künftigen Migration:** `prioritize_genres()`s
  Multi-Tag-Kontext (Teilstring-Match) und `determine_genre()`s
  Single-String-Kontext (kein Teilstring-Match) haben unterschiedliche
  Fehlertoleranzanforderungen — eine einheitliche Implementierung müsste
  beide Anforderungen weiterhin erfüllen können, nicht nur eine.

---

## 13. Entscheidungsgate

**ARCH-013 PHASE 1 — ENTSCHEIDUNGSGATE ERREICHT**

Charakterisierung abgeschlossen. Keine Produktionsänderung, kein
Refactoring, keine Variante A/B/C umgesetzt.

**Ergebnis: B — Verhalten unterscheidet sich, fachlich relevant.** Keine
Zentralisierung empfohlen. Stattdessen wird eine gezielte, kleine
Folgephase vorgeschlagen: eine fachliche Entscheidungstabelle für die 4
bekannten Override-Konflikte plus eine bewusste Entscheidung über das
Teilstring-Match-Verhalten — beides Voraussetzung für jede spätere
Code-Migration, aber selbst noch keine Code-Migration.

Freigabe für eine Folgephase liegt beim Nutzer.
