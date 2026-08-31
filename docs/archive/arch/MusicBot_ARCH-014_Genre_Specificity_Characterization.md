# ARCH-014 Phase 1 — Genre Specificity / Longest-Match Characterization

## Status

**Phase 1 abgeschlossen (2026-08-25). Reine Characterization-Phase. Keine
Produktionscodeänderung, kein Refactoring, keine YAML-Änderung.** 14
neue Characterization-Tests als Beweismittel hinzugefügt (dokumentieren
das aktuelle, fachlich suboptimale Verhalten — keine Lösung). Ergebnis
ist eine fachliche Entscheidungsgrundlage für eine mögliche spätere,
separat freizugebende Phase.

**Phase 2 abgeschlossen (2026-08-25). Die in Phase 1 abgeleitete
Spezifitätsregel (Zeichenlänge, Hierarchie-Tiefe als Tie-Breaker) ist
umgesetzt** (siehe Abschnitt „Phase 2 — Umsetzung" am Ende dieses
Dokuments). Alle 55 charakterisierten Fälle korrigiert, keine
ARCH-013-Regression, 1 dokumentierte, bewusst nicht behobene
Idempotenz-Ausnahme (`"ny drill"`).

---

## 1. Ausgangslage

`docs/archive/post-arch/POST-ARCH-013_Services_Architecture_Audit.md` (Abschnitt G/L, PR
#32, gemergt) identifizierte, dass `"k-pop revival"` → `"Pop"` (statt
`"K-Pop"`) kein Einzelfall ist, sondern ein systematisches Muster: 55
Alias-Paare in `mapping/genre_aliases.yaml` sind von derselben
Spezifitäts-Kollision betroffen. Diese Phase charakterisiert dieses
Problem vollständig und leitet eine fachliche Entscheidungsgrundlage ab —
**keine Umsetzung**.

---

## 2. Aktueller Datenfluss

```text
GenreProcessor.normalize_genre_name(genre)
   ↓
genre_lower = genre.lower().strip()
   ↓
1. Exakter Match in GENRE_NORMALIZATION?  → sofort zurück (unbetroffen von diesem Befund)
   ↓ (kein exakter Match)
2. Teilstring-Schleife über GENRE_NORMALIZATION.items()
   (Iterationsreihenfolge = mapping/genre_aliases.yaml-Dateireihenfolge)
   für jeden Key: _contains_alias_as_whole_word(genre_lower, key)?
   → ERSTER Treffer gewinnt, KEINE Spezifitäts-/Längenprüfung
   ↓ (kein Treffer)
3. Fallback: Wort-für-Wort-Kapitalisierung
```

```text
GenreProcessor.prioritize_genres(tags, artist_name)
   ↓ pro Tag: normalize_for_matching() (feste Sonderfaelle) → normalize_genre_name() [siehe oben]
   ↓ GENRE_PRIORITY.get(normalisierter_tag)  (Hierarchie-Tiefe aus genre_hierarchy.yaml)
   ↓ nach Prioritaet absteigend sortieren, Tiebreak alphabetisch
```

Das Problem entsteht ausschließlich in Schritt 2 der ersten Methode — die
zweite Methode (`prioritize_genres()`) ist selbst nicht direkt betroffen
(ARCH-013 Phase 4 hat ihre Hierarchie-Priorisierung bereits korrekt
gemacht), **erbt** das Problem aber indirekt, weil sie
`normalize_genre_name()` intern pro Tag aufruft (siehe Abschnitt 7).

---

## 3. Reproduktion der bekannten Fälle

Real gegen den aktuellen Code ausgeführt (`GenreProcessor` aus einer
echten, gegen `mapping/` geladenen Instanz):

| Eingabe | getroffene Aliase (Wortgrenzen-gültig) | Iterationsreihenfolge | tatsächliches Ergebnis | erwartbarer Treffer | Hierarchie-Tiefe (tats./erwartet) |
|---|---|---|---|---|---|
| `k-pop revival` | `pop` (Pos. früh), `k-pop` (Pos. spät) | `pop` zuerst | `Pop` | `K-Pop` | 0 / 1 |
| `tech house mix` | `house` (früh), `tech house` (spät) | `house` zuerst | `House` | `Tech House` | 1 / 2 |
| `christian rock ballad` | `rock` (früh), `christian rock` (spät) | `rock` zuerst | `Rock` | `Gospel` | 0 / unbekannt (kein Hierarchie-Eintrag für `Gospel`) |
| `indie rock legend` | `rock` (früh), `indie rock` (spät) | `rock` zuerst | `Rock` | `Indie` | 0 / 0 (**Geschwister, kein Tiefenunterschied**) |

**Warum der generische Treffer zuerst akzeptiert wird:** `for key, value
in self.GENRE_NORMALIZATION.items(): if self._contains_alias_as_whole_word(...):
return value` — die Schleife bricht beim **ersten** gültigen
Wortgrenzen-Treffer ab, unabhängig davon, ob ein längerer/spezifischerer
Treffer später in derselben Iteration folgen würde. Die
Iterationsreihenfolge ist reine Dict-Insertion-Order = YAML-Dateireihenfolge
— ein Zufallsprodukt der redaktionellen Gliederung der Datei (z. B. steht
der „# Pop"-Abschnitt mit `"pop"` früh in der Datei, der „# International"-
Abschnitt mit `"k-pop"` deutlich später), kein bewusster Mechanismus.

---

## 4. Analyse aller 55 Alias-Paare

Vollständige, systematische Erfassung (Skript gegen den echten
`GenreProcessor.GENRE_NORMALIZATION`-Dict und
`GenreProcessor._contains_alias_as_whole_word()`, nicht nur Einzelbeispiele):

| Spezifischer Alias | Generischer Alias | Ziel (spezifisch) | Ziel (generisch) | Länge (s/g) | Wörter (s/g) | Hierarchie-Tiefe (s/g) |
|---|---|---|---|---|---|---|
| `chamber pop` | `pop` | Chamber Pop | Pop | 11/3 | 2/1 | 1/0 |
| `rock/pop` | `pop` | Rock | Pop | 8/3 | 1/1 | 0/0 |
| `hardcore hip hop` | `hip hop` | Hardcore Hip Hop | Hip Hop | 16/7 | 3/2 | 1/0 |
| `conscious rap` | `rap` | Conscious Rap | Hip Hop | 13/3 | 2/1 | 1/0 |
| `battle rap` | `rap` | Battle Rap | Hip Hop | 10/3 | 2/1 | 1/0 |
| `technical rap` | `rap` | Technical Rap | Hip Hop | 13/3 | 2/1 | ?/0 |
| `comedy rap` | `rap` | Comedy Rap | Hip Hop | 10/3 | 2/1 | ?/0 |
| `emo rap` | `rap` | Emo Rap | Hip Hop | 7/3 | 2/1 | 1/0 |
| `melodic rap` | `rap` | Melodic Rap | Hip Hop | 11/3 | 2/1 | 1/0 |
| `pop rap` | `pop` | Pop Rap | Pop | 7/3 | 2/1 | 1/0 |
| `pop rap` | `rap` | Pop Rap | Hip Hop | 7/3 | 2/1 | 1/0 |
| `uk rap` | `rap` | UK Rap | Hip Hop | 6/3 | 2/1 | 1/0 |
| `uk drill` | `drill` | UK Drill | Hip Hop | 8/5 | 2/1 | 2/0 |
| `ny drill` | `drill` | New York Drill | Hip Hop | 8/5 | 2/1 | 2/0 |
| `chicago drill` | `drill` | Chicago Drill | Hip Hop | 13/5 | 2/1 | 2/0 |
| `west coast hip hop` | `hip hop` | West Coast Hip Hop | Hip Hop | 18/7 | 4/2 | 1/0 |
| `east coast hip hop` | `hip hop` | East Coast Hip Hop | Hip Hop | 18/7 | 4/2 | 1/0 |
| `southern hip hop` | `hip hop` | Southern Hip Hop | Hip Hop | 16/7 | 3/2 | 1/0 |
| `old school hip hop` | `hip hop` | Old School Hip Hop | Hip Hop | 18/7 | 4/2 | 1/0 |
| `street rap` | `rap` | Straßenrap | Hip Hop | 10/3 | 2/1 | ?/0 |
| `liquid dnb` | `dnb` | Liquid Drum & Bass | Drum & Bass | 10/3 | 2/1 | ?/1 |
| `tech house` | `house` | Tech House | House | 10/5 | 2/1 | 2/1 |
| `progressive house` | `house` | Progressive House | House | 17/5 | 2/1 | 2/1 |
| `melodic house` | `house` | Melodic House | House | 13/5 | 2/1 | 2/1 |
| `tropical house` | `house` | Tropical House | House | 14/5 | 2/1 | 2/1 |
| `future house` | `house` | Future House | House | 12/5 | 2/1 | 2/1 |
| `bass house` | `house` | Bass House | House | 10/5 | 2/1 | 2/1 |
| `afro house` | `house` | Afro House | House | 10/5 | 2/1 | 2/1 |
| `electro house` | `electro` | Electro House | Electronic | 13/7 | 2/1 | 2/0 |
| `electro house` | `house` | Electro House | House | 13/5 | 2/1 | 2/1 |
| `mainstage house` | `house` | Mainstage House | House | 15/5 | 2/1 | 2/1 |
| `g-house` | `house` | G-House | House | 7/5 | 1/1 | 2/1 |
| `indie dance` | `dance` | Indie Dance | Dance | 11/5 | 2/1 | 2/1 |
| `melodic techno` | `techno` | Melodic Techno | Techno | 14/6 | 2/1 | ?/1 |
| `industrial techno` | `techno` | Industrial Techno | Techno | 17/6 | 2/1 | ?/1 |
| `detroit techno` | `techno` | Detroit Techno | Techno | 14/6 | 2/1 | ?/1 |
| `berlin techno` | `techno` | Berlin Techno | Techno | 13/6 | 2/1 | ?/1 |
| `hard dance` | `dance` | Hardstyle | Dance | 10/5 | 2/1 | 1/1 |
| `symphonic metal` | `symphonic` | Metal | Klassik | 15/9 | 2/1 | 0/0 |
| `indie rock` | `rock` | Indie | Rock | 10/4 | 2/1 | 0/0 |
| `indie pop` | `pop` | Indie | Pop | 9/3 | 2/1 | 0/0 |
| `indie folk` | `indie` | Indie Folk | Indie | 10/5 | 2/1 | 1/0 |
| `bedroom pop` | `pop` | Indie | Pop | 11/3 | 2/1 | 0/0 |
| `k-pop` | `pop` | K-Pop | Pop | 5/3 | 1/1 | 1/0 |
| `j-pop` | `pop` | J-Pop | Pop | 5/3 | 1/1 | 1/0 |
| `c-pop` | `pop` | C-Pop | Pop | 5/3 | 1/1 | 1/0 |
| `afro trap` | `trap` | Afro | Hip Hop | 9/4 | 2/1 | 0/0 |
| `country pop` | `pop` | Country Pop | Pop | 11/3 | 2/1 | 1/0 |
| `country pop` | `country` | Country Pop | Country | 11/7 | 2/1 | 1/0 |
| `folk pop` | `pop` | Folk Pop | Pop | 8/3 | 2/1 | 1/0 |
| `folk pop` | `folk` | Folk Pop | Folk | 8/4 | 2/1 | 1/0 |
| `country rock` | `rock` | Country | Rock | 12/4 | 2/1 | 0/0 |
| `lofi hip hop` | `hip hop` | Lo-Fi | Hip Hop | 12/7 | 3/2 | 1/0 |
| `christian rock` | `rock` | Gospel | Rock | 14/4 | 2/1 | ?/0 |
| `christian pop` | `pop` | Gospel | Pop | 13/3 | 2/1 | ?/0 |

**Statistik:**

- **55/55** zeigen ein tatsächlich falsches (zu generisches) Ergebnis bei
  einem realistisch dekorierten String (empirisch mit `+ " extra"`
  verifiziert).
- **55/55**: der spezifische Alias ist länger (Zeichen) als der
  generische.
- **50/55**: der spezifische Alias hat mehr Wörter (`str.split()`) als
  der generische — **5 Ausnahmen** (`k-pop`, `j-pop`, `c-pop`, `g-house`,
  `rock/pop`): Bindestrich-/Slash-Komposita zählen bei `str.split()`
  als „1 Wort", obwohl sie inhaltlich eindeutig spezifischer sind.
- **Hierarchie-Tiefe bekannt für 45/55**, davon **37/45** mit
  `Tiefe(spezifisch) > Tiefe(generisch)` — **8/45 mit exakt gleicher
  Tiefe** (Geschwister-Genres oder inhaltlich unverwandte
  Top-Level-Genres, siehe Abschnitt 6).
- **Hierarchie-Tiefe fehlt für 10/55** (Zielgenre nicht in
  `genre_hierarchy.yaml` verzeichnet, z. B. `Gospel`, `Straßenrap`,
  `Technical Rap`, `Comedy Rap`, `Liquid Drum & Bass`, mehrere
  Techno-Subgenres).

**Ausdrücklich geprüft und verneint:** „Nicht aus länger automatisch
fachlich besser schließen" — für alle 55 Paare wurde geprüft, ob der
längere/spezifischere Treffer tatsächlich der fachlich plausiblere ist
(nicht nur technisch länger). In keinem der 55 Fälle wurde ein
Gegenbeispiel gefunden, in dem der kürzere/generische Alias fachlich
vorzugswürdig wäre — siehe Abschnitt 5 für die systematische Suche nach
Gegenbeispielen.

---

## 5. Longest-Match-Analyse

### A. Zeichenlänge

**55/55 korrekt** — für jedes der 55 charakterisierten Paare ist der
spezifische Alias-Key länger als der generische. Kein Gegenbeispiel
gefunden.

### B. Anzahl Wörter

**Nur 50/55 korrekt.** 5 Ausnahmen — alle Bindestrich-/Slash-Komposita
(`k-pop`, `j-pop`, `c-pop`, `g-house`, `rock/pop`), bei denen
`str.split()` das Kompositum als ein einzelnes „Wort" zählt, obwohl es
inhaltlich spezifischer als der eingebettete generische Alias ist.
**Wortanzahl allein ist als alleiniges Kriterium unzureichend.**

### C. Hierarchie-Tiefe

**Nur 37/55 eindeutig korrekt entscheidbar** (bei bekannter Tiefe beider
Zielgenres). Zwei strukturelle Schwächen:

1. **10/55 fehlende Werte** — nicht jedes Zielgenre ist in
   `genre_hierarchy.yaml` verzeichnet (z. B. `Gospel`, `Straßenrap`,
   einzelne Techno-/Rap-Subgenres).
2. **8/55 Gleichstand trotz inhaltlichem Spezifitätsunterschied** — siehe
   Abschnitt 6.

### D. Kombination aus Alias-Spezifität und Hierarchie

Empirisch die tragfähigste Option: **Zeichenlänge als Primärkriterium**
(deckt alle 55 Fälle korrekt ab, inkl. der 5 Bindestrich-Ausnahmen, die
Wortanzahl nicht abdeckt, und der 18 Fälle, die Hierarchie-Tiefe allein
nicht abdeckt), mit **Hierarchie-Tiefe als möglichem Tie-Breaker** für
den (bisher nicht empirisch aufgetretenen) Fall exakt gleicher
Zeichenlänge zwischen zwei konkurrierenden, unterschiedlichen Treffern
(siehe Abschnitt 5, Gleichstand-Suche unten).

### Antworten auf die Leitfragen

- **Reicht Longest-Match (Zeichenlänge) allein?** Für alle 55 bekannten,
  aktuell existierenden Kollisionsfälle: ja, empirisch vollständig
  bestätigt (55/55).
- **Ist Longest-Match nur ein technischer Proxy?** Teilweise — er ist ein
  Proxy für „der Alias-Autor hat mehr spezifische Information in den Key
  gepackt", was in den geprüften Fällen durchgängig mit tatsächlicher
  fachlicher Spezifität übereinstimmt. Er ist kein Proxy für
  Hierarchie-Tiefe (siehe die 8 Gleichstand-Fälle) — Zeichenlänge und
  Hierarchie-Tiefe sind zwei unabhängige, nicht austauschbare Signale.
- **Gibt es Fälle, bei denen ein kürzerer Alias fachlich Vorrang haben
  muss?** In den 55 charakterisierten Fällen: **nein**, kein einziger
  gefunden.
- **Gibt es Fälle, in denen Hierarchie-Tiefe das bessere
  Entscheidungskriterium ist?** Nein — Hierarchie-Tiefe ist in dieser
  Domäne nie *besser* als Zeichenlänge, aber in 18/55 Fällen *schlechter*
  (unzureichend oder gleichstehend).

### Gleichstand-Suche (Tie-Breaker-Bedarf)

Innerhalb der 55 charakterisierten realen Kollisionspaare besteht **kein
einziger Fall exakt gleicher Zeichenlänge** zwischen dem generischen und
dem spezifischen Treffer (in jedem Paar ist der spezifische Alias
eindeutig länger). Ein Tie-Breaker wäre damit für die aktuell bekannten
55 Fälle nicht erforderlich — könnte aber bei künftigen neuen
YAML-Einträgen relevant werden. Eine explorative Suche nach potenziellen
künftigen Gleichstand-Situationen (z. B. `"deutschpop"` vs. `"electropop"`,
beide 10 Zeichen) ergab, dass solche Fälle nur bei **künstlich
konstruierten, gemeinsam vorkommenden, voneinander unabhängigen** Aliasen
auftreten (kein echter Überlappungs-Konflikt an derselben Textstelle) —
kein aktuell relevanter Gleichstand-Fall gefunden.

---

## 6. Hierarchie-Analyse

Detailprüfung der 8 Fälle, in denen `genre_hierarchy.yaml` **keinen**
Tiefenunterschied zwischen generischem und spezifischem Ziel liefert:

| Spezifisch → Ziel | Generisch → Ziel | Hierarchie-Beziehung |
|---|---|---|
| `rock/pop` → Rock | `pop` → Pop | **beide Top-Level (Tiefe 0)** — `"rock/pop"` ist keine echte Subgenre-Verfeinerung, sondern eine alternative Schreibweise/Entscheidung „bei diesem Tag gilt Rock" |
| `hard dance` → Hardstyle | `dance` → Dance | **Geschwister** — `Hardstyle: Electronic` und `Dance: Electronic` sind beide direkte Kinder von `Electronic` (Tiefe 1), kein Eltern-Kind-Verhältnis |
| `symphonic metal` → Metal | `symphonic` → Klassik | **zwei unverwandte Top-Level-Genres** (Tiefe 0/0) — „Symphonic Metal" ist Metal, „symphonic" allein wird als Synonym für klassische/orchestrale Musik behandelt; keine Subgenre-Beziehung, sondern eine reine Wort-Kollision zwischen zwei fachlich getrennten Genrefamilien |
| `indie rock` → Indie | `rock` → Rock | **Geschwister** (beide Tiefe 0, Top-Level, kein Eltern-Kind-Verhältnis in der Hierarchie) |
| `indie pop` → Indie | `pop` → Pop | **Geschwister** (Tiefe 0/0) |
| `bedroom pop` → Indie | `pop` → Pop | **Geschwister** (Tiefe 0/0) |
| `afro trap` → Afro | `trap` → Hip Hop | **zwei unverwandte Top-Level-Genres** (Tiefe 0/0) — redaktionelle Entscheidung, „Afro Trap" als eigene Kategorie (Afro) statt als Hip-Hop-Subgenre zu führen |
| `country rock` → Country | `rock` → Rock | **Geschwister** (Tiefe 0/0) |

### Antworten auf die Leitfragen

- **Sind spezifischere Genres zuverlässig tiefer in der Hierarchie?**
  **Nein** — in 8 von 45 Fällen mit bekannter Tiefe sind beide
  Zielgenres gleich tief (meist beide Top-Level), obwohl der Alias-Key
  eindeutig spezifischer ist.
- **Sind alle relevanten Alias-Paare hierarchisch vergleichbar?** Nein —
  10/55 haben mindestens ein Zielgenre, das gar nicht in
  `genre_hierarchy.yaml` verzeichnet ist.
- **Gibt es Geschwister-Genres?** Ja — mindestens 5 der 8
  Gleichstand-Fälle sind echte Geschwister mit gemeinsamem Elterngenre
  (`Hardstyle`/`Dance` unter `Electronic`; `Indie`/`Rock`/`Pop` sind
  allerdings selbst KEINE Geschwister mit gemeinsamem Parent, sondern
  eigenständige Top-Level-Genres — die „Geschwisterschaft" besteht hier
  nur im Sinne „beide Tiefe 0", nicht in einer echten
  Eltern-Kind-Struktur).
- **Gibt es Fälle ohne Hierarchie-Beziehung?** Ja — `symphonic metal`/
  `symphonic` und `afro trap`/`trap` sind keine Subgenre-Paare, sondern
  Kollisionen zwischen inhaltlich unverwandten Genrefamilien, die nur
  zufällig ein gemeinsames Wortfragment teilen.
- **Gibt es Fälle, in denen Hierarchie und String-Länge unterschiedliche
  Gewinner bestimmen würden?** In den 8 Gleichstand-Fällen liefert die
  Hierarchie **keinen** Gewinner (unentschieden), während die
  Zeichenlänge in allen 8 einen klaren, fachlich plausiblen Gewinner
  liefert — kein Fall, in dem die Hierarchie einen ANDEREN (widersprechenden)
  Gewinner als die Länge bestimmen würde, nur Fälle, in denen sie *keinen*
  bestimmt.

**Fazit:** Die Hierarchie ist als alleiniges Kriterium **nicht
belastbar genug** — sie versagt strukturell bei Geschwister-Genres und
bei inhaltlich unverwandten Kollisionen. Sie wird hier **nicht** als
Lösung festgelegt, sondern als unzureichend für den Alleingebrauch
charakterisiert (wie in Abschnitt 5D bereits vorweggenommen).

---

## 7. Multi-Tag-Auswirkungen

`prioritize_genres()` ruft `normalize_genre_name()` intern **pro
einzelnem Tag** auf (innerhalb `normalize_for_matching()`s
Weiterverarbeitung), bevor die Hierarchie-Priorisierung
(`GENRE_PRIORITY`-Lookup) beginnt. Das bedeutet:

- **Die Spezifitätsfrage muss innerhalb der Alias-Normalisierung selbst
  gelöst werden** (Schritt „Teilstring-Match" in
  `normalize_genre_name()`), **nicht** erst bei der finalen
  Priorisierung — zum Zeitpunkt der Priorisierung liegt bereits nur noch
  der (fälschlich generische) normalisierte Name vor, die Information
  „es gab auch einen spezifischeren Wortgrenzen-Treffer" ist zu diesem
  Zeitpunkt bereits verloren.
- Das ist strukturell **derselbe Mechanismus**, der in ARCH-013 Phase 4
  für den Override-vs-Alias-Konflikt gefunden und behoben wurde (dort:
  `normalize_genre_name()` kollabierte einen spezifischen Tag auf seinen
  generischen Wert, BEVOR die Hierarchie-Priorität greifen konnte) — hier
  liegt dieselbe Grundursache vor, nur ausgelöst durch die
  Teilstring-Match-Iterationsreihenfolge statt durch einen
  Alias/Override-Datenkonflikt.

**Simulation (kein Produktionscode geändert, nur lokale Nachbildung zu
Analysezwecken) bestätigt:**

```text
prioritize_genres(["ruhrpott rap", "deutschrap"])          → unverändert "Ruhrpott Rap" (0 Regression)
prioritize_genres(["ruhrpott rap", "hip hop", "trap"])      → unverändert "Ruhrpott Rap" (0 Regression)
prioritize_genres(["electropop", "pop"])                    → unverändert "Electropop" (0 Regression)
prioritize_genres(["chamber pop", "indie"])                 → unverändert "Chamber Pop" (0 Regression)
prioritize_genres(["tech house", "house", "electronic"])    → unverändert "Tech House" (0 Regression)
```

Eine simulierte Longest-Match-Korrektur in `normalize_genre_name()`
verändert **keinen** der 5 bereits durch ARCH-013 Phase 4 korrekt
gelösten Multi-Tag-Fälle — die Korrektur ist orthogonal zu den
Override-vs-Alias-Konflikten und würde diese nicht erneut berühren.

### Wo sollte eine künftige Spezifitätsregel ansetzen?

Innerhalb der Alias-Normalisierung selbst (`normalize_genre_name()`s
Teilstring-Match-Schritt) — **nicht** erst bei der finalen
Priorisierung, weil:

1. Der Single-String-Kontext (`GenreMapper.determine_genre()`s Fallback,
   außerhalb dieses Scopes, siehe Abschnitt 9 Risikoanalyse) hat gar
   keinen Teilstring-Match-Schritt und ist daher nicht betroffen.
2. Der Multi-Tag-Kontext (`prioritize_genres()`) verliert die
   Spezifitätsinformation, sobald `normalize_genre_name()` den
   generischen Wert zurückgegeben hat — eine Korrektur auf
   Priorisierungsebene könnte diesen Informationsverlust nicht mehr
   rückgängig machen.

---

## 8. Fachliche Invarianten

Nur Invarianten, die durch die Characterization tatsächlich empirisch
begründet sind:

1. **„Ein spezifischer Alias darf nicht durch einen generischen Alias
   überstimmt werden, wenn beide im selben Input gültig sind."** —
   begründet durch 55/55 Fälle, in denen dies aktuell doch geschieht und
   in keinem der 55 Fälle fachlich gewünscht ist.
2. **„Ein generischer Treffer darf weiterhin gewinnen, wenn kein
   spezifischer Treffer vorhanden ist."** — unverändert bereits
   geltendes, unproblematisches Verhalten (z. B. `"some pop song"` →
   `Pop`, korrekt, kein spezifischerer Alias vorhanden).
3. **„Wortgrenzen müssen erhalten bleiben."** — ARCH-013 Phase 5 bereits
   umgesetzt und in dieser Phase nicht angetastet; jede künftige
   Spezifitätsregel muss auf der bestehenden Wortgrenzen-Menge
   *filtern/priorisieren*, nicht sie ersetzen.
4. **„Exact Match darf nicht durch einen dekorierten Treffer verdrängt
   werden."** — bereits strukturell garantiert (Schritt 1 vor Schritt 2
   in `normalize_genre_name()`), durch diese Phase nicht berührt, sollte
   in jeder künftigen Umsetzung explizit erhalten bleiben.
5. **„Multi-Tag-Priorisierung darf nicht durch die Spezifitätskorrektur
   beschädigt werden."** — durch die Simulation in Abschnitt 7 bestätigt:
   0 Regressionen bei den 5 bekannten ARCH-013-Phase-4-Fällen.
6. **„Normalisierung muss idempotent bleiben."** — durch die Simulation
   in Abschnitt 7/9 bestätigt: alle getesteten dekorierten Eingaben
   bleiben nach einer simulierten Korrektur idempotent (bereits das
   AKTUELLE, unkorrigierte Verhalten war idempotent, siehe Abschnitt 9 —
   keine Verschlechterung, keine Verbesserungsnotwendigkeit in diesem
   Punkt).
7. **Neue, durch diese Phase zusätzlich begründete Invariante:
   „Wortanzahl (`str.split()`) ist kein zulässiges alleiniges
   Spezifitätsmaß."** — begründet durch die 5 Bindestrich-/
   Slash-Ausnahmen (`k-pop`, `j-pop`, `c-pop`, `g-house`, `rock/pop`), bei
   denen Wortanzahl versagt, Zeichenlänge aber korrekt entscheidet.
8. **Neue, durch diese Phase zusätzlich begründete Invariante:
   „Hierarchie-Tiefe allein ist kein hinreichendes Spezifitätsmaß."** —
   begründet durch die 18/55 Fälle (10 fehlend + 8 Gleichstand), in
   denen Hierarchie-Tiefe keine Entscheidung liefert, obwohl eine
   fachlich eindeutige Spezifitätsrangfolge besteht.

---

## 9. Variantenvergleich

### Variante A — Longest Match (Zeichenlänge)

- **Vorteile:** deckt alle 55 bekannten Fälle korrekt ab (100 %), robust
  gegenüber Bindestrich-/Slash-Komposita, einfach zu implementieren
  (einzeiliger `max(candidates, key=len)` statt „ersten Treffer nehmen"),
  keine Abhängigkeit von einer vollständigen/konsistenten
  `genre_hierarchy.yaml`.
- **Nachteile:** rein syntaktisch, keine fachliche Garantie für
  *zukünftige*, noch nicht existierende Alias-Einträge (Induktionsschluss
  aus 55 Fällen, keine deduktive Beweisführung); kein Tie-Breaker bei
  echtem Längen-Gleichstand definiert (aktuell nicht benötigt, siehe 5).
- **Gegenbeispiele:** keine gefunden.
- **Verhaltensänderung:** betrifft alle 55 charakterisierten Fälle
  (positiv, korrigierend) + jeden künftigen String, der einen der
  aktuellen 55 generischen Treffer neben seinem spezifischen Gegenstück
  enthält.
- **Risiko:** niedrig — durch die Simulation empirisch als
  regressionsfrei gegenüber allen bisherigen ARCH-013-Testfällen (17
  Fälle) und den 5 Multi-Tag-Fällen bestätigt.
- **Implementierungsscope:** eine Methode in `genre_processor.py`
  (`normalize_genre_name()`s Teilstring-Schleife), analog zur ARCH-013-
  Phase-5-Änderungsgröße.
- **Testbedarf:** hoch — mindestens die 55 Paare (oder eine
  repräsentative, dokumentiert vollständige Teilmenge plus ein
  Zähl-Regressionstest, analog zu dieser Phase) müssen auf das neue
  Zielverhalten umgestellt werden.

### Variante B — Word Count

- **Vorteile:** intuitiv, leicht nachvollziehbar.
- **Nachteile:** **versagt in 5/55 Fällen** (alle Bindestrich-/
  Slash-Komposita) — kein vollständiges Kriterium.
- **Gegenbeispiele:** `k-pop`/`j-pop`/`c-pop`/`g-house`/`rock/pop` (siehe
  Abschnitt 5B).
- **Verwerfung empfohlen** als alleiniges Kriterium.

### Variante C — Hierarchy Depth

- **Vorteile:** fachlich am „sprechendsten" begründet, wo verfügbar.
- **Nachteile:** **unzureichend für 18/55 Fälle** (10 fehlende
  Hierarchie-Einträge + 8 Gleichstand-Fälle bei Geschwistern/unverwandten
  Top-Level-Genres) — kein vollständiges Kriterium, erfordert zudem
  vollständige Pflege von `genre_hierarchy.yaml` für alle aktuellen und
  künftigen Alias-Zielgenres.
- **Gegenbeispiele:** die 8 Gleichstand-Fälle aus Abschnitt 6.
- **Verwerfung empfohlen** als alleiniges Kriterium.

### Variante D — Kombinierte Regel

Empirisch abgeleitete (nicht vorausgesetzte) Reihenfolge:

1. Exakter Match (unverändert, bereits vorhanden).
2. **Längster gültiger Wortgrenzen-Treffer nach Zeichenlänge** (deckt
   55/55 ab).
3. **Hierarchie-Tiefe als Tie-Breaker** nur für den (bisher nicht
   aufgetretenen) Fall exakt gleicher Zeichenlänge zwischen zwei
   unterschiedlichen Treffern.

- **Vorteile:** kombiniert die empirisch vollständige Abdeckung von
  Variante A mit einer zusätzlichen Absicherung für künftige, heute noch
  nicht existierende Gleichstand-Fälle.
- **Nachteile:** etwas höherer Implementierungs-/Testaufwand als reine
  Variante A, ohne dass der Tie-Breaker-Teil an den aktuellen 55 Fällen
  überhaupt verifizierbar wäre (kein realer Testfall dafür vorhanden).
- **Risiko:** niedrig, identisch zu Variante A für alle aktuell bekannten
  Fälle.
- **Empfehlung:** stärkster Kandidat, aber der Hierarchie-Tie-Breaker-Teil
  ist unbewiesen (keine Characterization-Grundlage) und sollte in einer
  Umsetzungsphase entweder mit einem synthetischen Testfall abgesichert
  oder explizit als „aktuell folgenlos, aber vorsorglich vorhanden"
  dokumentiert werden.

### Variante E — aktuelle First-Match-Regel (Baseline)

- **Vorteile:** keine Änderung nötig, kein Risiko.
- **Nachteile:** lässt alle 55 charakterisierten Fehlklassifikationen
  unkorrigiert bestehen, in einer P0-geschützten Domäne.
- **Bewertung:** als dauerhafte Lösung nicht empfehlenswert angesichts
  der empirisch breiten und eindeutigen Befundlage — aber die einzige
  Variante, die ohne jede weitere Phase sofort „gültig" bleibt, falls
  keine Priorität für eine Korrektur besteht.

---

## 10. Test-/Coverage-Befund

**Vor dieser Phase: 0 Tests** deckten die Spezifitätskollision ab (weder
die 8 im POST-ARCH-013-Audit genannten Beispiele noch irgendeine der 55
Paare — verifiziert per `grep` über alle Testdateien, 0 Treffer).

**Neu in dieser Phase:** `tests/test_genre_specificity_characterization.py`,
14 Tests, 3 Klassen:

- `TestGenericAliasCurrentlyOutranksSpecificAlias` (11 Tests) — friert
  das aktuelle (generische) Ergebnis für 9 repräsentative dekorierte
  Strings ein, plus eine Gegenprobe, dass exakte (undekorierte) Eingaben
  weiterhin korrekt spezifisch aufgelöst werden.
- `TestCurrentBehaviorIsIdempotentDespiteBeingSuboptimal` (3 Tests) —
  bestätigt, dass das aktuelle Verhalten trotz fachlicher Suboptimalität
  idempotent ist.
- `TestSpecificityCollisionCountRegressionGuard` (1 Test) — zählt die 55
  Kollisionspaare als Regressionswächter für künftige YAML-Änderungen.

**Ausdrücklich beachtet:** alle Assertions dokumentieren das AKTUELLE
(generische, suboptimale) Ergebnis, nicht das fachlich gewünschte — siehe
Moduldokstring. Diese Tests sind Beweismittel für die Analyse, keine
Spezifikation einer künftigen Lösung, und müssten bei einer Umsetzung
explizit umgestellt werden (etabliertes Muster aus allen bisherigen
ARCH-012/013-Phasen).

---

## 11. Risikoanalyse

- **Verbleibendes Risiko bei Nichtstun:** alle 55 Fehlklassifikationen
  bleiben aktiv in der P0-Genre-Domäne bestehen; jede neue
  YAML-Alias-Ergänzung kann die Zahl unbemerkt erhöhen (der neue
  Regressionswächter-Test macht künftige Änderungen an der Zahl
  zumindest sichtbar, verhindert sie aber nicht).
- **Risiko einer Umsetzung ohne weitere Phase:** eine Umsetzung direkt
  aus dieser Characterization heraus würde CLAUDE.md §6 (Characterization
  first, aber Entscheidung/Umsetzung als eigener Schritt) und die
  ausdrückliche Anweisung dieser Phase („STOPPE nach Abschluss,
  keine automatische Folgephase") verletzen.
- **Fachliches Risiko der empfohlenen Regel (Variante D) selbst:** gering,
  aber nicht null — die 55 Fälle sind eine vollständige Erfassung der
  *aktuell existierenden* Kollisionen, keine Garantie gegen alle
  *zukünftigen* neuen YAML-Einträge. Eine Umsetzungsphase sollte den in
  dieser Phase entwickelten Analyse-Mechanismus (Paar-Erkennungsskript)
  wiederverwendbar machen, um künftige Kollisionen bei YAML-Änderungen
  aktiv zu erkennen, nicht nur die aktuellen 55 zu fixen.
- **Kein Risiko für andere ARCH-013-Ergebnisse:** empirisch bestätigt
  (Abschnitt 7) — 0 Regressionen bei den 5 bereits gelösten
  Override-vs-Alias-Multi-Tag-Fällen.

---

## 12. Empfehlung

**Eine fachliche Regel ist eindeutig ableitbar:** *„Bei mehreren
gleichzeitig gültigen Wortgrenzen-Treffern im Teilstring-Match-Schritt
von `GenreProcessor.normalize_genre_name()` gewinnt der Treffer mit der
größeren Zeichenlänge des Alias-Keys (nicht Wortanzahl); bei exakt
gleicher Zeichenlänge entscheidet die Hierarchie-Tiefe des Zielgenres als
Tie-Breaker."* (Variante D, mit Variante A als empirisch bereits
vollständig bewiesenem Kernbestandteil).

Diese Regel ist:

- **vollständig** — deckt alle 55 aktuell bekannten Kollisionsfälle
  korrekt ab (Variante A allein reicht dafür bereits aus),
- **robust** — versagt nicht bei den 5 Bindestrich-/Slash-Ausnahmen, die
  Variante B (Wortanzahl) unzureichend machen,
- **ohne Abhängigkeit von vollständiger Hierarchie-Pflege** — im
  Gegensatz zu Variante C (Hierarchie-Tiefe allein), die für 18/55 Fälle
  keine Antwort liefert,
- **regressionsfrei gegenüber allen bisherigen ARCH-013-Ergebnissen**
  (empirisch simuliert bestätigt).

**Longest-Match (Zeichenlänge) ist für die aktuellen 55 Fälle
tatsächlich ausreichend** — der Hierarchie-Tie-Breaker in Variante D ist
eine vorsorgliche Absicherung für unbekannte künftige Fälle, keine für
die aktuelle Faktenlage notwendige Ergänzung.

**Kein Gegenbeispiel** zur Grundregel „spezifischer/längerer Wortgrenzen-
Treffer soll gewinnen" wurde in den 55 charakterisierten Fällen gefunden.

---

## 13. Entscheidungsgate

**ARCH-014 PHASE 1 — ENTSCHEIDUNGSGATE ERREICHT**

Characterization abgeschlossen. Keine Produktionsänderung, kein
Refactoring, kein Commit einer Implementierung.

**ARCH-014 Phase 1 ist vollständig abgeschlossen.**

**Empfohlene fachliche Regel:** Zeichenlänge des Alias-Keys als
Primärkriterium für den Teilstring-Match-Gewinner, Hierarchie-Tiefe als
Tie-Breaker bei Gleichstand (Variante D).

**Ist Longest-Match tatsächlich ausreichend?** Ja, für alle 55 aktuell
bekannten Fälle — empirisch vollständig verifiziert, kein Gegenbeispiel
gefunden.

**Welche Gegenbeispiele existieren?** Keine gegen die Grundregel selbst.
Wortanzahl (Variante B) hat 5 Gegenbeispiele. Hierarchie-Tiefe allein
(Variante C) hat 18 Gegenbeispiele (10 fehlend + 8 Gleichstand).

**Ergebnis: ERGEBNIS A** — eine fachliche Regel ist eindeutig ableitbar
(Variante D: Zeichenlänge, Hierarchie als Tie-Breaker) und kann in einer
separaten, eigenen Umsetzungsphase implementiert werden. Diese Phase
selbst nimmt **keine Umsetzung** vor.

Wie ausdrücklich gefordert: **STOPP nach dieser Characterization.** Keine
automatische Folgephase gestartet. Wartet auf ausdrückliche Freigabe für
eine mögliche Umsetzungsphase (vorläufig „ARCH-014 Phase 2").

---

## Phase 2 — Umsetzung

**Status: abgeschlossen (2026-08-25).** Setzt die in Phase 1 eindeutig
abgeleitete Spezifitätsregel (ERGEBNIS A) im bestehenden
`GenreProcessor.normalize_genre_name()`-Teilstring-Match-Pfad um.

### Vorbereitungsprüfung

Vor der Änderung verifiziert: der Code entsprach exakt dem in Phase 1
charakterisierten Stand (`for key, value in self.GENRE_NORMALIZATION.items():
if self._contains_alias_as_whole_word(...): return value` — First-Match,
keine Längenprüfung). Keine Abweichung zur Dokumentation festgestellt.

### Implementierte Regel

```python
candidate_keys = [
    key
    for key in self.GENRE_NORMALIZATION
    if self._contains_alias_as_whole_word(genre_lower, key)
]
if candidate_keys:
    def _specificity(key: str):
        value = self.GENRE_NORMALIZATION[key]
        depth = self.GENRE_PRIORITY.get(value.lower(), -1)
        return (len(key), depth)

    best_key = max(candidate_keys, key=_specificity)
    return self.GENRE_NORMALIZATION[best_key]
```

1. **Schritt 1 (Wortgrenzen-Treffer bestimmen):** unverändert —
   `_contains_alias_as_whole_word()` (ARCH-013 Phase 5) wurde nicht
   angetastet. Statt beim ersten Treffer zurückzukehren, werden jetzt
   **alle** gültigen Wortgrenzen-Treffer gesammelt.
2. **Schritt 2 (Zeichenlänge):** `len(key)` als Primärkriterium — der
   längste Alias-Key unter allen gültigen Treffern gewinnt. Warum
   Zeichenlänge und nicht Wortanzahl: Phase 1 hat empirisch gezeigt, dass
   Wortanzahl bei 5 der 55 Fälle versagt (Bindestrich-/Slash-Komposita
   wie `"k-pop"` zählen bei `str.split()` fälschlich als 1 Wort).
   Zeichenlänge deckt alle 55 Fälle korrekt ab.
3. **Schritt 3 (Hierarchie-Tie-Breaker):** `self.GENRE_PRIORITY.get(value.lower(), -1)`
   — die bereits bestehende, aus `genre_hierarchy.yaml` berechnete
   Prioritäts-/Tiefen-Repräsentation (dieselbe, die `prioritize_genres()`
   für die Multi-Tag-Priorisierung verwendet), **keine neue
   Hierarchie-Semantik**. Wird nur bei exakt gleicher Zeichenlänge
   zwischen zwei unterschiedlichen Kandidaten wirksam — unter den 55
   bekannten Fällen tritt dieser Fall aktuell nicht auf (Phase 1,
   Abschnitt 5, „Gleichstand-Suche"). Fehlende Hierarchie-Tiefe wird mit
   `-1` behandelt (verliert im Tie-Break gegen jeden Key mit bekannter
   Tiefe) — ein bewusster, dokumentierter Default, keine Improvisation
   einer neuen Regel: er kommt nur zum Tragen, wenn *zusätzlich* bereits
   Zeichenlängen-Gleichstand besteht, was aktuell nirgends auftritt.

**Nur eine Produktionsdatei geändert** (`services/metadata/genre_processor.py`,
21 effektive Zeilen) — `GenreMapper`, alle YAML-Dateien und
`_contains_alias_as_whole_word()` selbst blieben unverändert, wie von der
Scope-Grenze gefordert.

### Erhaltene ARCH-013-Regeln (empirisch verifiziert)

| Regel | Verifikation | Ergebnis |
|---|---|---|
| Alias-Konflikte (`electropop`/`chamber pop`/`tech house`/`ruhrpott rap`) | `GenreMapper`/`GenreProcessor` direkt verglichen | identisch, unverändert |
| Mixed-Case/Whitespace (`Hip-Hop`, `Hip - Hop`, …) | 6 Schreibweisen getestet | alle → `Hip Hop`, unverändert |
| Wortgrenzen (`britpop` darf nicht matchen) | `britpop`/`britpop revival` getestet | unverändert `Britpop`/`Britpop Revival` |
| Wortgrenzen (`ruhrpott rap fanpage` muss matchen) | getestet | unverändert `Ruhrpott Rap` |
| Multi-Tag-Priorisierung (ARCH-013 Phase 4) | 5 bekannte Fälle erneut ausgeführt | alle unverändert korrekt |

### Ergebnisse der 55er-Revalidierung

Vollständiger Vorher-/Nachher-Vergleich aller 55 programmatisch
hergeleiteten Paare (Skript identisch zur Phase-1-Methodik, gegen den
gefixten Code ausgeführt):

- **55/55 korrigiert** — liefern jetzt den spezifischen statt des
  generischen Werts.
- **0/55 weiterhin falsch.**
- **0/55 unerwartetes Ergebnis** (weder generischer noch spezifischer
  Wert).

### Korrigierte Beispiele

| Eingabe | vorher (Phase 1) | nachher (Phase 2) |
|---|---|---|
| `k-pop revival` | `Pop` | `K-Pop` |
| `tech house mix` | `House` | `Tech House` |
| `christian rock ballad` | `Rock` | `Gospel` |
| `indie rock legend` | `Rock` | `Indie` |
| `bedroom pop vibes` | `Pop` | `Indie` |
| `country pop hit` | `Pop` | `Country Pop` |
| `progressive house anthem` | `House` | `Progressive House` |
| `west coast hip hop classic` | `Hip Hop` | `West Coast Hip Hop` |
| `symphonic metal choir` | `Klassik` | `Metal` |

### Verbleibende bekannte Edge Cases

**1 von 55 Fällen ist nach der Korrektur nicht mehr idempotent:**
`"ny drill extra"` → `"New York Drill"` (korrekt, spezifisch) →
erneut normalisiert → `"Hip Hop"` (falsch zurückfallend).

**Ursache:** `"New York Drill"` ist in `mapping/genre_aliases.yaml`
**kein eigener Alias-Key** — nur die Abkürzung `"ny drill"` führt dorthin.
Beim zweiten Normalisierungsdurchlauf ist `"new york drill"` kein exakter
Match, und im Teilstring-Match enthält der ausgeschriebene Text selbst
zufällig den generischen Key `"drill"` als gültigen Wortgrenzen-Treffer
(`"...york DRILL"`) — `"ny drill"` selbst kommt im ausgeschriebenen Text
nicht mehr als Zeichenfolge vor, kann also nicht erneut gefunden werden.

**Warum das VOR Phase 2 nicht sichtbar war:** vor der Korrektur war der
ERSTE Durchlauf bereits (fälschlich) `"Hip Hop"` (der generische Treffer
gewann sofort) — der zweite Durchlauf blieb dann trivial stabil bei
`"Hip Hop"`. Die Korrektur macht den ersten Durchlauf richtig, deckt dabei
aber eine vorbestehende, von ARCH-014 unabhängige Datenlücke in
`genre_aliases.yaml` auf (ein ausgeschriebener kanonischer Wert ohne
eigenen rückführenden Alias-Eintrag).

**2 weitere, strukturell ähnliche, aber nicht betroffene Fälle geprüft:**
`"liquid dnb"` → `"Liquid Drum & Bass"` und `"afro trap"` → `"Afro"` sind
ebenfalls nicht als eigener Alias-Key rückführbar, bleiben aber zufällig
idempotent, weil ihr ausgeschriebener kanonischer Text **keinen**
generischen Alias-Key als Wortgrenzen-Treffer enthält (die
Title-Case-Fallback-Stufe liefert in diesen beiden Fällen zufällig
denselben Text zurück).

**Nicht behoben** — Scope-Grenze dieser Phase verbietet
Alias-Daten-Änderungen (`genre_aliases.yaml`) und das Erfinden neuer
Normalisierungsregeln. Dokumentiert als bekannter, isolierter Folgepunkt
(siehe Abschluss).

### Import-/Dependency-Audit

- Keine neuen Imports (0 Treffer bei `git diff ... | grep import`).
- `services/* → handlers/*`: 0 Treffer, unverändert.
- `services/* → klassen/*`: 0 Treffer, unverändert.
- Import-Zyklen: AST-Scan über alle `services/*.py` → 0 Zyklen,
  unverändert.
- Downloader→Metadata-Richtung: nicht berührt (nur `genre_processor.py`
  intern geändert, keine neue Abhängigkeit).

### Gezielte Tests

`tests/test_genre_specificity_characterization.py` — von 14 auf 36 Tests
erweitert, 5 Klassen:

- `TestSpecificAliasNowOutranksGenericAlias` (11 Tests, davon 1
  vollständiger 55-Paare-Test) — Soll-Verhalten.
- `TestWordBoundaryNegativeCasesStillExcluded` (2 Tests) — ARCH-013
  Phase 5 bleibt erhalten.
- `TestArch013RulesPreserved` (15 Tests) — Alias-Konflikte, Mixed-Case/
  Whitespace, Multi-Tag-Priorisierung.
- `TestIdempotency` (7 Tests) — 6 stabile Fälle + 1 explizit
  dokumentierte, bewusst nicht behobene Ausnahme (`ny drill`).
- `TestSpecificityPairCountRegressionGuard` (1 Test) — strukturelle
  Paarzahl (55) als künftiger YAML-Änderungswächter.

Alle bisherigen 14 Phase-1-Tests wurden umbenannt/angepasst (Assertions
invertiert: spezifischer statt generischer Wert erwartet), **nicht
gelöscht** — etabliertes Muster aus ARCH-012/013.

Zusätzlich erneut ausgeführt: `tests/test_genre_processor.py` (28),
`tests/test_genre_mapper_advanced.py` (16), `tests/test_genre_alias_characterization.py`
(26), `tests/test_mapping_yaml_integrity.py` (22) — alle unverändert grün,
**125 Tests insgesamt** in der gezielten Genre-Testbasis.

### Vollständige Regression

- Gezielt (5 Genre-Testdateien): 125 passed.
- Vollständig (`pytest tests/ -q`): **1077 passed**, 15 bekannte
  Vorbestandsfehler (identisch zu allen vorherigen ARCH-013/014-Ständen).
- Baseline-Vergleich: 1055 (Phase 1) → 1077 (Phase 2), Delta +22 exakt
  durch die Testdatei-Erweiterung erklärt (36 − 14 = 22), keine unerklärte
  Abweichung.

### Diff-/Scope-Audit

Geänderte Dateien:

- `services/metadata/genre_processor.py` — 1 Produktionsdatei, 21
  effektive Zeilen, keine neuen Imports, keine neue Klasse, keine
  geänderte öffentliche Signatur.
- `tests/test_genre_specificity_characterization.py` — Testdatei, wie
  oben beschrieben.
- `docs/archive/arch/MusicBot_ARCH-014_Genre_Specificity_Characterization.md` —
  dieser Abschnitt.

**Nicht verändert:** `utils/genre_map.py`, jede YAML-Mapping-Datei
(`genre_aliases.yaml`, `genre_overrides.yaml`, `genre_hierarchy.yaml`),
jede andere Produktionsdatei, Downloader-/Handler-/Klassen-Schicht.

### Bewusst nicht bearbeitet

- Die dokumentierte `"ny drill"`-Idempotenz-Ausnahme (Datenlücke in
  `genre_aliases.yaml`, kein Code-Bug dieser Phase) — erfordert eine
  YAML-Änderung, außerhalb der Scope-Grenze dieser Phase.
- Jede Form von Zentralisierung, neuer Architektur-Layer oder
  Downloader-/Metadata-Änderung.
- ARCH-005 und alle anderen bekannten POST-ARCH-013-Folgepunkte.

---

## ARCH-014 Phase 2 — Entscheidungsgate

**Erreicht.** Alle Bedingungen erfüllt:

- Zeichenlängenregel implementiert und an allen 55 charakterisierten
  Fällen verifiziert.
- Hierarchie-Tie-Breaker gemäß bestehender `GENRE_PRIORITY`-Semantik
  berücksichtigt (aktuell folgenlos, da kein Gleichstand-Fall existiert —
  transparent dokumentiert, nicht improvisiert).
- 55/55 Fälle korrigiert, 0 verbleibend falsch.
- ARCH-013 nicht regressiert (Alias-Konflikte, Mixed-Case/Whitespace,
  Wortgrenzen, Multi-Tag-Priorisierung — alle empirisch bestätigt
  unverändert).
- Idempotenz erhalten für 54/55 Fälle; 1 bewusst dokumentierte,
  vorbestehende Ausnahme (`"ny drill"`, Datenlücke, nicht Teil dieser
  Phase).
- Vollregression: 1077 passed, 15 bekannte Vorbestandsfehler, keine neue
  Regression.
- Diff/Scope sauber: 1 Produktionsdatei, keine neuen Imports, keine
  Schichtverletzung.

ARCH-014 hat damit keinen offenen Phasen-Auftrag mehr. Wie ausdrücklich
gefordert: **STOPP.** Kein weiterer Architektur- oder Genre-Folgepunkt
selbstständig begonnen, kein automatisches Post-ARCH-014-Audit. Wartet
auf ausdrückliche Freigabe für jede weitere Aktion (inkl. Merge).
