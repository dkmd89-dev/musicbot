# POST-ARCH-013 Services / Genre Architecture Audit

## Status

**Audit abgeschlossen (2026-08-25). Kein Code geändert, kein Refactoring,
keine Tests geändert, kein Commit, kein PR, keine eigenständige Behebung
von Befunden.** Bestehende Architekturentscheidungen aus
ARCH-009/010/011/012/013 werden als getroffen respektiert, nicht erneut
aufgerollt. Entscheidungsgate am Ende, wartet auf Freigabe.

---

## A. ARCH-013-Endstatus

ARCH-013 (Phasen 1–5, PRs #28–#31, alle gemergt) ist vollständig
abgeschlossen. Alle vier in Phase 1 identifizierten Divergenzursachen
zwischen `GenreMapper` und `GenreProcessor` wurden bearbeitet:

1. Mixed-Case-/Whitespace-Bug (Phase 3) — behoben.
2. Override-vs-Alias-Konflikte für `electropop`/`chamber pop`/
   `tech house`/`ruhrpott rap` (Phase 4) — behoben.
3. Teilstring-Matching ohne Wortgrenzen (Phase 5) — auf Wortgrenzen
   eingeschränkt.
4. Multi-Tag-Hierarchie-Priorisierungsdefekt (als Konsequenz von Phase 4
   miterledigt) — behoben.

Regressionsstand real neu ausgeführt (nicht aus Dokumentation
übernommen): `pytest tests/ -q` → **1041 passed, 15 bekannte
Vorbestandsfehler** (identisch zu den seit ARCH-012 dokumentierten 15
Fehlern: `test_auto_learn.py` ×5 inkl. Subfails, `test_metadata_modules.py::TestTitleCleaner`
×5 inkl. Subfails, `test_suite.py` ×4, alle durch fehlendes
`pytest-asyncio`).

**Dieses Audit hat einen neuen, über den bekannten `k-pop revival`-
Einzelfall deutlich hinausgehenden Befund identifiziert** — siehe G und L.
ARCH-013s eigene Phase-2-Spezifikation deckte diesen Befund nicht ab (sie
behandelte ausdrücklich nur Wortgrenzen, nicht Spezifität/Priorität
mehrerer gültiger Treffer) — kein Verstoß gegen ARCH-013, aber eine
Lücke, die erst durch die systematische Prüfung in diesem Audit sichtbar
wurde.

---

## B. Verifikation der Alias-Regeln

Real gegen den aktuellen Code ausgeführt (`GenreMapper`/`GenreProcessor`
aus einer echten, gegen `mapping/` geladenen Instanz):

| Eingabe | `GenreMapper` | `GenreProcessor` | Status |
|---|---|---|---|
| `electropop` | `Electropop` | `Electropop` | ✅ identisch |
| `chamber pop` | `Chamber Pop` | `Chamber Pop` | ✅ identisch |
| `tech house` | `Tech House` | `Tech House` | ✅ identisch |
| `ruhrpott rap` | `Ruhrpott Rap` | `Ruhrpott Rap` | ✅ identisch |

Alle 4 Konfliktregeln aus ARCH-013 Phase 4 sind im aktuellen Code korrekt
umgesetzt und stabil.

---

## C. Verifikation der Multi-Tag-Priorisierung

```text
prioritize_genres(["electropop", "pop"])                 → ("Electropop", [])
prioritize_genres(["chamber pop", "indie"])               → ("Chamber Pop", [])
prioritize_genres(["tech house", "house", "electronic"])  → ("Tech House", ["House"])
prioritize_genres(["ruhrpott rap", "hip hop", "trap"])     → ("Ruhrpott Rap", ["Hip Hop"])
```

Der in ARCH-013 Phase 2 dokumentierte Hierarchie-Kollabierungsdefekt
(spezifischere Tags verloren ihre Priorität, weil sie vor der
`GENRE_PRIORITY`-Nachschlage bereits auf ihr Elterngenre normalisiert
wurden) ist **vollständig behoben** — alle 4 Beispiele liefern das
spezifischere Genre als `primary`, exakt wie in der Phase-2-Soll-
Spezifikation gefordert. Kein Restbefund für diese 4 konkreten Fälle.

**Aber:** Abschnitt G/L zeigt, dass dieselbe Klasse von Problem
(generischer Tag gewinnt vor spezifischerem) für **weitere, nicht in
ARCH-013 behandelte Alias-Paare** weiterhin besteht — nur über einen
anderen Mechanismus (Wortgrenzen-Teilstring-Iterationsreihenfolge statt
Hierarchie-Kollabierung).

---

## D. Verifikation der Idempotenz

```text
GenreMapper:    normalize("Hip - Hop")      = "Hip Hop"       → normalize("Hip Hop")       = "Hip Hop"       ✅
GenreMapper:    normalize("electropop")     = "Electropop"    → normalize("Electropop")    = "Electropop"    ✅
GenreMapper:    normalize("britpop")        = "Britpop"       → normalize("Britpop")       = "Britpop"       ✅
GenreMapper:    normalize("k-pop revival")  = "K-Pop Revival" → normalize("K-Pop Revival") = "K-Pop Revival" ✅
GenreProcessor: normalize("k-pop revival")  = "Pop"           → normalize("Pop")           = "Pop"           ✅
GenreProcessor: normalize("ruhrpott rap fanpage") = "Ruhrpott Rap" → normalize("Ruhrpott Rap") = "Ruhrpott Rap" ✅
```

**Idempotenz ist in allen getesteten Fällen gegeben — auch für die in
Abschnitt G beschriebenen Spezifitäts-Kollisionsfälle.** Wichtig: Die
Kollisionsproblematik ist ein **Korrektheitsproblem** (falsches, zu
generisches Ergebnis), **kein Idempotenz-Problem** (das falsche Ergebnis
ist stabil reproduzierbar, ändert sich nicht bei wiederholter
Normalisierung). Kein Gegenbeispiel zur Idempotenz-Invariante gefunden.

---

## E. GenreMapper-vs-GenreProcessor-Befund

| Aspekt | Befund | Kategorie |
|---|---|---|
| Alias-Quellen | `GenreMapper` konsultiert weiterhin 2 Dateien (`genre_overrides.yaml` mit Vorrang, dann `genre_aliases.yaml`); `GenreProcessor` weiterhin nur 1 (`genre_aliases.yaml`) | **D** — bewusst bestehend, seit ARCH-013 Phase 4 inhaltlich konsistent (0 Wertkonflikte), nur strukturell weiterhin getrennt |
| Lookup-Semantik | `GenreMapper`: nur exakter Match. `GenreProcessor`: exakter Match + wortgrenzen-beschränkter Teilstring-Match (seit Phase 5) | **B** — fachlich unterschiedliche Aufrufkontexte (Single-String-Fallback vs. Multi-Tag-Normalisierung roher externer Tags), in ARCH-013 Phase 2 explizit als notwendig begründet, nicht neu |
| Caching | `GenreMapper.normalize_genre_name()`: `lru_cache(2048)`. `GenreProcessor.normalize_genre_name()`: kein Cache | **D** — unverändert seit vor ARCH-013, nicht Teil des Scopes, kein beobachtetes Performanceproblem |
| Doppelte Normalisierungsimplementierung | Beide Klassen haben eine eigene `normalize_genre_name()`-Methode mit eigenem Fallback-Kapitalisierungscode | **D** — bewusst bestehend (ARCH-013 Phase 1/2 hat Zentralisierung geprüft und wegen der unterschiedlichen Aufrufkontexte nicht empfohlen) |
| Neue Divergenz durch ARCH-013 | Keine gefunden — beide Implementierungen liefern für alle 4 Konfliktgenres identische Ergebnisse, keine neue Abweichung eingeführt | — |

**Es gibt keine echte Architekturverletzung (Kategorie A) mehr zwischen
`GenreMapper` und `GenreProcessor`.** Die verbleibenden strukturellen
Unterschiede sind entweder fachlich begründet (B) oder bewusst
akzeptiertes, bereits mehrfach geprüftes Verhalten (D). Eine
Zentralisierung wird **nicht** vorgeschlagen — die Ähnlichkeit beider
`normalize_genre_name()`-Methoden ist oberflächlich (unterschiedliche
Datenquellen, unterschiedliche Lookup-Semantik, unterschiedlicher
Aufrufkontext), keine echte Duplikation im CLAUDE.md-Sinn.

---

## F. YAML-Konsistenz

Real gegen die aktuellen Dateien geprüft (nicht aus Dokumentation
übernommen):

- `genre_aliases.yaml` vs. `genre_overrides.yaml`: **0 Wertkonflikte**
  (vollständiger Scan aller 321/156 Einträge, `TestYamlSourceCollisions::test_genre_aliases_and_genre_overrides_have_no_known_conflicts`
  grün).
- `mapping/test_mapping_yaml_integrity.py`: **22/22 Tests grün** — keine
  doppelten Keys in irgendeiner `mapping/*.yaml`/`*.json`-Datei, DATA-001/
  DATA-002-Regressionsschutz weiterhin aktiv.
- `genre_aliases.yaml` enthält weiterhin 2 Mixed-Case-Keys
  (`"Hip-Hop"`, `"Hip - Hop"`) — **unschädlich**, da `GenreMapper` sie
  seit Phase 3 beim Laden lowercased; die YAML-Bereinigung selbst wurde
  in Phase 3 bewusst nicht vorgenommen (technisch nicht nötig, siehe
  Phase-3-Dokumentation). Kein neuer Befund.
- `artist_genre.yaml`/`channel_genre.yaml`: unverändert seit vor
  ARCH-013 (`git log` bestätigt keine Commits seit DATA-001/DATA-002) —
  weiterhin konsistent mit den in Phase 4 korrigierten
  `genre_aliases.yaml`/`genre_overrides.yaml`-Werten.
- `ruhrpott rap` bleibt fachlich plausibel: `genre_hierarchy.yaml`
  definiert es weiterhin als eigenständiges Deutschrap-Subgenre, `Alias`
  und `Override` stimmen jetzt überein (`"Ruhrpott Rap"`), kein neuer
  Widerspruch seit der in Phase 4 vom Nutzer bestätigten Entscheidung.

**Keine neuen Konflikte seit ARCH-013.** Die 4 ursprünglich analysierten
Konflikte sind konsistent abgebildet.

---

## G. `k-pop revival`-Analyse

### Charakterisierung

`"k-pop revival"` → `"Pop"` ist **kein isolierter Einzelfall**, sondern
ein **repräsentatives Beispiel einer systematischen Kategorie**: überall
dort, wo ein generischerer Alias-Key (z. B. `"pop"`, `"rock"`, `"house"`,
`"rap"`, `"techno"`, `"dance"`, `"hip hop"`, `"drill"`, `"indie"`,
`"folk"`, `"country"`, `"trap"`, `"symphonic"`, `"electro"`) **vor** einem
spezifischeren Key, der ihn als wortgrenzen-konformen Teilstring enthält
(z. B. `"k-pop"`, `"indie rock"`, `"tech house"`, `"conscious rap"`,
`"melodic techno"`, `"indie dance"`, `"lofi hip hop"`, `"uk drill"`,
`"indie folk"`, `"country pop"`, `"afro trap"`, `"symphonic metal"`,
`"electro house"`), in der Iterationsreihenfolge von
`GENRE_NORMALIZATION` steht, gewinnt der generische Key — nicht, weil er
fachlich richtiger wäre, sondern weil `normalize_genre_name()`s
Teilstring-Schleife beim **ersten** gültigen Wortgrenzen-Treffer
zurückkehrt, ohne Spezifität oder Länge zu berücksichtigen.

**Systematische Suche (Skript gegen den echten `GENRE_NORMALIZATION`-Dict,
nicht nur Einzelbeispiele):** 321 Keys paarweise auf „Key B enthält
früher iterierten Key A als Wortgrenzen-Teilstring, mit unterschiedlichem
Zielwert" geprüft → **55 betroffene Alias-Paare gefunden.** Stichprobe von
8 empirisch gegen den echten `GenreProcessor` getesteten, realistischen
dekorierten Strings — **8 von 8 zeigen die Fehlklassifikation:**

| Eingabe | tatsächliches Ergebnis | fachlich erwartetes Ergebnis |
|---|---|---|
| `tech house mix` | `House` | `Tech House` |
| `indie rock legend` | `Rock` | `Indie` |
| `christian rock ballad` | `Rock` | `Gospel` |
| `k-pop revival` | `Pop` | `K-Pop` |
| `bedroom pop vibes` | `Pop` | `Indie` |
| `country pop hit` | `Pop` | `Country Pop` |
| `progressive house anthem` | `House` | `Progressive House` |
| `west coast hip hop classic` | `Hip Hop` | `West Coast Hip Hop` |

### Bewertung der Aufgabenfragen

- **Ist dies lediglich ein kleiner verbleibender Edge Case?** Nein — 55
  betroffene Alias-Paare bei 321 Gesamteinträgen (~17 %) sind kein
  Rand-, sondern ein strukturelles Muster.
- **Ist es ein Verstoß gegen die ARCH-013-Spezifikation?** Nein.
  ARCH-013 Phase 2 spezifizierte ausdrücklich nur die Wortgrenzen-Bedingung
  („matcht als eigenständiges Wort"), nicht die Priorität mehrerer
  gleichzeitig gültiger Wortgrenzen-Treffer. Phase 5 hat exakt das
  umgesetzt, was spezifiziert war — dieser Befund liegt aber außerhalb
  dessen, was spezifiziert wurde, nicht im Widerspruch dazu.
- **Ist die Ursache eine fehlende Spezifitäts-/Longest-Match-Regel?** Ja,
  eindeutig — verifiziert durch die 55-Fälle-Analyse und die 8/8-Stichprobe.
- **Gibt es weitere vergleichbare Fälle?** Ja, 55 (siehe oben) — deutlich
  mehr als der einzelne dokumentierte `k-pop revival`-Fall vermuten ließ.
- **Würde eine Behebung fachliches Verhalten verändern?** Ja, für
  potenziell viele reale MusicBrainz-/Last.fm-Tag-Kombinationen im
  `prioritize_genres()`-Pfad (dem aktiven ARCH-012-Produktionspfad) —
  jede Behebung ist eine echte P0-Verhaltensänderung, keine reine
  Code-Bereinigung.
- **Ist daraus ein eigenständiger sinnvoller Folgeauftrag ableitbar?**
  Ja — siehe Priorisierung (L) und Empfehlung (M).

---

## H. Test-/Coverage-Befund

| ARCH-013-Regel | direkt getestet? | Testklasse |
|---|---|---|
| Mixed-Case/Whitespace | ✅ ja | `TestAliasLoadingDivergence` (5 Tests) |
| Override-vs-Alias-Konflikte (4 Genres) | ✅ ja | `TestOverrideAliasConflictsResolvedInPhase4` (5 Tests) |
| Wortgrenzen-Matching (Basisfälle) | ✅ ja | `TestSubstringMatchingOnlyInGenreProcessor` (4 Tests) |
| Multi-Tag-Priorisierung (die 4 Konfliktgenres) | ✅ indirekt über `prioritize_genres()` in `test_genre_processor.py` | `TestPrioritizeGenres` |
| Idempotenz | ✅ ja (2 Fälle) | `TestAliasLoadingDivergence::test_normalize_genre_name_is_idempotent_for_the_fixed_alias` |
| **Spezifitäts-/Longest-Match bei mehreren gültigen Wortgrenzen-Treffern** | **❌ nein — 0 Tests** | — |
| `k-pop revival` bzw. vergleichbare Fälle | **❌ nein — nur in Dokumentation erwähnt, nie als Test** | — |

**Konkret verifiziert:** `grep` über alle Testdateien nach den 8 oben
genannten Beispielstrings (`"tech house mix"`, `"indie rock legend"`,
`"k-pop revival"` etc.) → **0 Treffer**. Diese Verhaltensklasse ist
vollständig ungetestet.

**Risikoeinschätzung dieser Lücke:** mittel-hoch — nicht, weil das
aktuelle Verhalten akut falsch im Sinne eines Rückschritts wäre (es war
nie anders), sondern weil es sich um einen aktiven, unbemerkten
Freiheitsgrad im P0-geschützten Genre-Pfad handelt, der bei künftigen
YAML-Änderungen (neue Aliase) jederzeit neue, unbemerkte Kollisionen
erzeugen kann, ohne dass ein Test dies auffängt.

Sonstige Coverage: keine weiteren Lücken zu den in ARCH-013 tatsächlich
bearbeiteten Regeln gefunden — alle real umgesetzten Regeln sind
angemessen getestet.

---

## I. Services-Schicht-Audit

Repo-weit erneut geprüft (nicht aus Dokumentation übernommen):

- **`services/* → handlers/*`**: 0 Treffer.
- **`services/* → klassen/*`**: 0 Treffer.
- **Import-Zyklen**: AST-basierter Scan über alle `services/*.py`-Module
  (10 Module mit `services→services`-Kanten) → **0 Zyklen**.
- **Dependency-Richtung**: unverändert seit POST-ARCH-012-Audit —
  `downloader → metadata` (Zielrichtung), `metadata → clients` (normal),
  `statistik → clients/navidrome_api.py` (normal), keine neuen
  Gegenabhängigkeiten.
- **Genre-Fachlogik in Adapter-/Client-Schicht**: weiterhin **0
  Treffer** in `lastfm_client.py`/`musicbrainz_client.py` — nur
  historische Docstring-Kommentare referenzieren `GenreMapper`, kein
  funktionaler Import mehr (ARCH-012 weiterhin intakt, durch ARCH-013
  nicht berührt oder beeinträchtigt).
- **ARCH-005 Reverse-Edge**: unverändert, exakt dieselbe eine
  Aufrufstelle (`enhanced_metadata_processor.py:1002` →
  `cleanup_single_download_artifact()`). Bewusste, bestehende Ausnahme,
  nicht erneut aufgerollt.

**Ergebnis: `services/` ist architektonisch unverändert stabil.** Kein
neuer Architektur- oder Schichtbefund seit dem POST-ARCH-012-Audit.

---

## J. Bekannte Folgepunkte — Revalidierung

| Punkt | Status | Einordnung |
|---|---|---|
| ARCH-005 Reverse-Edge | weiterhin vorhanden, unverändert | bewusst akzeptierte Ausnahme (D) |
| Last.fm-Duplikation `cover_processor.py` | weiterhin vorhanden (`_fetch_lastfm()`, eigene `requests.Session`), unverändert seit POST-ARCH-012-Audit | Optimierung (C), P2, kein Bug |
| DI-Inkonsistenz `album_processor.py` | weiterhin vorhanden (`AlbumProcessor(logger=...)` ohne `mb_client`), unverändert | Stilfrage (C/D), P3, kein Ressourcenschaden (modul-globaler MusicBrainz-Cache greift weiterhin) |
| `metadata/cache.py`-Namensnähe zu `utils/metadata_cache.py` | weiterhin bestehend, sauberes Decorator-Muster, kein funktionaler Konflikt | kosmetisch (D), P3 |
| tote Imports (`requests` in `enhanced_metadata_processor.py`, `subprocess` in `navidrome_api.py`) | beide weiterhin vorhanden, 0 Verwendungen | trivial (D), P3 |
| `genre_rules.yaml`/GENRE-002 | bereits entschieden (nicht erneut geprüft, wie von der Aufgabe verlangt) | abgeschlossen |
| doppelte Alias-In-Memory-Repräsentation (ehem. E.6) | durch ARCH-013 vollständig bearbeitet | **abgeschlossen** |

Keiner der bekannten Folgepunkte hat sich durch ARCH-013 verändert (weder
verschlechtert noch zufällig mitbehoben) — ARCH-013 war scope-sauber auf
die Genre-Alias-Frage begrenzt, wie in allen 5 Phasen dokumentiert.

---

## K. Neue Befunde

Über die Revalidierung hinaus wurde gezielt nach neuen Boundary-Problemen,
Duplikationen und Dependency-Problemen gesucht (analog Abschnitt 6 der
POST-ARCH-012-Methodik). Ergebnis:

- **Kein neuer Architektur-/Boundary-Befund in `services/`.**
- **Ein neuer, substanzieller Fachlogik-Befund in der Genre-Domäne**:
  das in Abschnitt G/L beschriebene Spezifitäts-/Longest-Match-Problem
  (55 betroffene Alias-Paare) — dies ist der einzige neue Befund dieses
  Audits.

---

## L. Priorisierung

| Prio | Kandidat | Problem | Betroffene Dateien | Ursache | Risiko | Nutzen | Scope | Warum (nicht) jetzt | Characterization nötig? |
|---|---|---|---|---|---|---|---|---|---|
| **P1** | Spezifitäts-/Longest-Match bei Wortgrenzen-Teilstring-Matching | 55 Alias-Paare liefern bei dekorierten/zusammengesetzten Rohtags (MusicBrainz/Last.fm) das generische statt des spezifischeren Genres | `services/metadata/genre_processor.py::normalize_genre_name()` | Teilstring-Schleife kehrt beim ersten gültigen Wortgrenzen-Treffer zurück, ohne Spezifität/Länge zu vergleichen (Iterationsreihenfolge = YAML-Dateireihenfolge, kein gesicherter Mechanismus) | mittel-hoch — aktiver P0-Pfad (`prioritize_genres()`, ARCH-012-Produktionscode), aber nur bei nicht-exakten, dekorierten Tag-Strings; keine Regression, sondern bereits lange bestehendes, jetzt erst systematisch sichtbares Verhalten | hoch — korrigiert potenziell viele reale Fehlklassifikationen in der P0-Genre-Domäne | mittel (Regelentscheidung + Implementierung + Characterization für mind. 55 Fälle) | jetzt: Umfang und reale Häufigkeit unbekannt, keine fachliche Entscheidung getroffen, welche Regel gelten soll (Longest-Match? Hierarchie-Tiefe? Reihenfolge nach YAML-Position bewusst beibehalten?) | **ja, unbedingt** — eigene Analyse-/Entscheidungsphase vor jeder Umsetzung |
| P2 | Last.fm-Duplikation `cover_processor.py` | eigener `requests.Session`-Aufruf statt `services/clients/lastfm_client.py` | `services/metadata/cover_processor.py` | historisch, kein Adapter-Bypass eines existierenden Features (Client bietet keine Bild-URL-Methode) | niedrig-mittel | mittel | mittel (neue Client-Fähigkeit nötig) | unverändert seit POST-ARCH-012-Audit, kein akuter Anlass | ja, kleiner Umfang |
| P3 | DI-Inkonsistenz `album_processor.py` | zwei potenzielle `MusicBrainzClient`-Instanzen | `services/metadata/album_processor.py`, `enhanced_metadata_processor.py` | historisch gewachsen | sehr niedrig | sehr niedrig | trivial | jederzeit risikofrei nachholbar, kein Architekturgewinn | nein |
| P3 | `metadata/cache.py`-Namensnähe | Namensverwechslungsgefahr | `services/metadata/cache.py` | historisch | keins | niedrig | klein | kosmetisch | nein |
| P3 | tote Imports | 2 ungenutzte Imports | `enhanced_metadata_processor.py`, `navidrome_api.py` | historisch | keins | keins | trivial | kosmetisch | nein |

**Wichtig:** P2/P3-Punkte werden hier nur revalidiert (wie von der
Aufgabe gefordert), nicht neu vorgeschlagen — sie sind identisch zum
POST-ARCH-012-Audit und werden bewusst nicht künstlich aufgewertet.

---

## M. Empfohlener nächster Schritt

### ERGEBNIS B — Ein relevanter Kandidat existiert, benötigt aber zunächst eine eigene Characterization-/Entscheidungsphase.

Der Spezifitäts-/Longest-Match-Befund (Abschnitt G/L) ist real,
substanziell (55 betroffene Alias-Paare, nicht nur der eine dokumentierte
`k-pop revival`-Fall) und liegt in der P0-geschützten Genre-Domäne im
aktiven ARCH-012-Produktionspfad. Er erfüllt damit die in der
Aufgabenstellung genannte Bedingung für einen `k-pop revival`-artigen
Folgeauftrag: „nur, wenn die Analyse zeigt, dass daraus tatsächlich eine
allgemeinere Spezifitätsregel ableitbar ist" — das ist hier eindeutig der
Fall, und der Umfang ist sogar deutlich größer als der ursprüngliche
Einzelfall vermuten ließ.

**Kein direkter Umsetzungsschritt (kein ERGEBNIS A)**, weil:

1. Die fachliche Regel selbst noch nicht entschieden ist (Longest-Match?
   Hierarchie-Tiefen-Priorität wie bei `GENRE_PRIORITY`? Bewusste
   YAML-Reihenfolge-Sortierung?) — genau die Art fachlicher Entscheidung,
   die laut CLAUDE.md §6/§15/§16 vor jeder Codeänderung in der Genre-
   Domäne zuerst getroffen werden muss.
2. Der volle Umfang (55 Paare) muss einzeln oder gruppenweise bewertet
   werden, bevor eine einzelne globale Regel als sicher gelten kann —
   analog zur in ARCH-013 Phase 2 etablierten Methodik (jeder Konflikt
   einzeln analysiert, nicht pauschal entschieden).
3. Eine Umsetzung ohne vorherige Characterization würde bestehendes
   Produktionsverhalten in der P0-Domäne ändern, ohne dass zuvor
   Vorher-Tests existieren, die das aktuelle (fehlerhafte) Verhalten
   festhalten — Regel 4/5 aus CLAUDE.md (Bug zuerst reproduzieren, dann
   Regressionstest).

**Empfehlung:** ein neuer, eigener Auftrag — vorläufig „ARCH-014" oder
„ARCH-013 Phase 6" (Benennung liegt beim Nutzer) — mit Scope:
Characterization der 55 betroffenen Alias-Paare, Analyse einer
allgemeinen Spezifitätsregel (z. B. „längster Wortgrenzen-Treffer
gewinnt" oder „höchste Hierarchie-Tiefe gewinnt"), fachliche
Entscheidungstabelle analog ARCH-013 Phase 2 — **keine Umsetzung in
derselben Phase**.

---

## N. Bewusst zurückgestellte Themen

- P2/P3-Folgepunkte aus Abschnitt J — unverändert, kein akuter Anlass.
- Zentralisierung von `GenreMapper`/`GenreProcessor` — in ARCH-013
  bereits geprüft und verworfen (fachlich unterschiedliche
  Aufrufkontexte), hier nicht erneut aufgerollt.
- `GenreMapper.determine_genre(raw_genre=X)`s Hierarchie-Rollup
  (`get_main_genre()`) — außerhalb des Genre-Alias-Scopes, GENRE-003,
  unverändert.
- GENRE-002 (`genre_rules.yaml`) — bereits entschieden, wie von der
  Aufgabe verlangt nicht erneut untersucht.

---

## O. Entscheidungsgate

**POST-ARCH-013 SERVICES / GENRE ARCHITECTURE AUDIT —
ENTSCHEIDUNGSGATE ERREICHT**

Der Audit ist abgeschlossen. Keine Codeänderungen wurden vorgenommen.

**ARCH-013 ist vollständig abgeschlossen** — alle 4 in Phase 1
identifizierten Divergenzursachen zwischen `GenreMapper` und
`GenreProcessor` sind behoben und real gegen den aktuellen Code
verifiziert (Regression: 1041 passed, 15 bekannte Vorbestandsfehler,
unverändert).

**Ein neuer Architekturauftrag ist sinnvoll — aber als eigene
Characterization-/Entscheidungsphase, nicht als sofortige Umsetzung
(ERGEBNIS B):** das Spezifitäts-/Longest-Match-Problem beim
Wortgrenzen-Teilstring-Matching in `GenreProcessor.normalize_genre_name()`,
mit 55 empirisch identifizierten betroffenen Alias-Paaren (deutlich mehr
als der ursprüngliche `k-pop revival`-Einzelfall).

`services/` selbst bleibt architektonisch stabil — kein neuer
Schicht-/Dependency-Befund. Für die reine Services-Architektur gilt
unverändert **ERGEBNIS C** (kein sofortiger Architekturkandidat); der
einzige substanzielle neue Befund dieses Audits liegt in der
Fachlogik-Domäne Genre, nicht in der Services-Schichtarchitektur.

Keine Umsetzung eines Folgepunktes in diesem Schritt. Wartet auf
ausdrückliche Freigabe für die nächste Phase.
