# POST-ARCH-012 Services Architecture Audit

## Status

**Audit abgeschlossen (2026-08-24). Kein Code geändert, kein Refactoring,
kein Commit, kein PR, keine eigenmächtige Umsetzung eines gefundenen
Kandidaten.** Entscheidungsgate am Ende, wartet auf Freigabe.

---

## A. Architekturstatus

ARCH-009/010/011 sind abgeschlossen. ARCH-012 (Phase 1/2/3A/3B) ist
abgeschlossen und in `main` gemergt (PR #24 Phase 2, PR #25 Phase 3A,
PR #26 Phase 3B). Damit ist der im vorherigen Audit
(`docs/MusicBot_POST-DUPLICATEENTRY_Services_Architecture_Audit.md`,
Abschnitt 5.2/8) als architektonisch wichtigster offener Befund
identifizierte Punkt — Genre-Fachlogik in `services/clients/`
(`lastfm_client.py`, `musicbrainz_client.py`) — vollständig aufgelöst:

- Beide Clients enthalten keinen `GenreMapper`/`get_genre_mapper()`-Import
  mehr und rufen `determine_genre()` nicht mehr auf (verifiziert per Grep,
  siehe Abschnitt D).
- `services/metadata/genre_processor.py` ist alleiniger Ort der
  Genre-Priorisierung für beide Quellen (Last.fm: Tags direkt über
  `prioritize_genres()`; MusicBrainz seit Phase 3B ebenso, statt vorher
  über einen client-seitig vorberechneten, bei Multi-Tag-Eingaben
  nachweislich fehlerhaften Einzelwert).

Regressionsstand zum Zeitpunkt dieses Audits erneut verifiziert (nicht nur
aus Dokumentation übernommen): `pytest tests/ -q` → **1015 passed, 15
bekannte Vorbestandsfehler** (identisch zu den in
`MusicBot_ARCH-012_Genre_Logic_Characterization.md`, Phase 3B dokumentierten
15 Fehlern: `test_auto_learn.py` ×5, `test_metadata_modules.py::TestTitleCleaner`
×5, `test_suite.py` ×4 — alle durch fehlendes `pytest-asyncio`, unverändert
über die gesamte ARCH-012-Serie).

**Ergebnis dieses Audits vorweggenommen (Details in G–N):** Nach
ARCH-009/010/011/012 gibt es aktuell **keinen** Kandidaten, der gleichzeitig
einen spürbaren Architekturgewinn bietet und mit dem in dieser Serie
etablierten Sicherheitsniveau (Characterization zuerst, mechanischer Scope,
kein Verhaltensrisiko) umsetzbar wäre. `services/` ist architektonisch
stabil.

---

## B. services/-Struktur (aktueller Stand)

```text
services/
├── __init__.py                        0 LOC — leer
├── statistik_service.py             143 LOC — Fassade (ARCH-003 P-6)
├── clients/                         4 Dateien, 1388 LOC — externe Adapter
│   ├── genius_client.py             551 LOC
│   ├── lastfm_client.py             149 LOC   (-2 ggü. Vorauf., ARCH-012 P2)
│   ├── musicbrainz_client.py        471 LOC   (+2 ggü. Vorauf., ARCH-012 P3B)
│   └── navidrome_api.py             217 LOC
├── downloader/                      10 Dateien (+ download/), 3752 LOC
│   ├── download_artifact_cleanup.py 168 LOC
│   ├── downloader.py                119 LOC
│   ├── download_result_reporter.py  309 LOC
│   ├── download_utils.py            908 LOC
│   ├── errors.py                     99 LOC
│   ├── metadata_result_translator.py 207 LOC
│   ├── models.py                     31 LOC  (DuplicateEntry)
│   ├── playlist_processor.py        604 LOC
│   ├── progress_tracker.py          146 LOC
│   ├── spotify_downloader.py        942 LOC
│   └── download/                    7 Dateien, 1578 LOC (ARCH-011, unverändert)
├── metadata/                        11 Dateien, 4711 LOC
│   ├── album_processor.py           159 LOC
│   ├── artist_processor.py          215 LOC
│   ├── auto_learn.py                458 LOC
│   ├── cache.py                     183 LOC
│   ├── cover_processor.py           955 LOC
│   ├── enhanced_metadata_processor.py 1203 LOC — Facade
│   ├── genre_processor.py           777 LOC   (+12 ggü. Vorauf., ARCH-012 P3B)
│   ├── lyrics_processor.py           75 LOC
│   ├── models.py                    123 LOC
│   ├── tag_writer.py                210 LOC
│   └── title_cleaner.py             333 LOC
└── statistik/                       4 Dateien, 639 LOC
    ├── chart_renderer.py            105 LOC
    ├── play_history_poller.py       170 LOC
    ├── play_history_repository.py   134 LOC
    └── statistics_calculator.py     230 LOC
```

Kein neuer Top-Level-Bereich seit dem letzten Audit. Einzige
Größenänderungen: `lastfm_client.py` (-2 LOC, GenreMapper-Entfernung),
`musicbrainz_client.py` (+2 LOC, Doku-Kommentar statt Determine-Genre-Block),
`genre_processor.py` (+12 LOC, neue MusicBrainz-Priorisierungslogik) — exakt
die von ARCH-012 dokumentierten Änderungen, keine unerwarteten Abweichungen.

---

## C. Schichtverletzungen

Repo-weit erneut geprüft:

- **`services/* → handlers/*`**: 0 funktionale Treffer
  (`grep -rn "^from handlers\|^import handlers" services/`).
- **`services/* → klassen/*`**: 0 Treffer.
- **`services/* → telegram`**: 1 String-Treffer
  (`services/clients/navidrome_api.py:72`, `"c": "telegram-bot"` — ein
  Subsonic-API-Client-Identifier-Parameter, keine Telegram-Kopplung, false
  positive).
- **`TYPE_CHECKING`-Importe** in `services/metadata/genre_processor.py` und
  `auto_learn.py`: ausschließlich `utils.genre_map`/`utils.artist_map`
  (Typannotationen für injizierte Utils), keine Handler-/Klassen-Typen.

**Ergebnis: keine Schichtverletzungen.** Unverändert zum Vorgänger-Audit.

`klassen/download_handler.py` bleibt einziges Modul in `klassen/` mit
Telegram-Import + Services-Import + Handler-Import — weiterhin bewusst als
Orchestrator-Rolle eingeordnet (CLAUDE.md §4-Grenze gilt für `services/`,
nicht für `klassen/`), kein neuer Befund.

---

## D. Dependency-Richtung

```text
services/downloader/  ──►  services/metadata/     [Zielrichtung, bestätigt]
        ▲
        └── ARCH-005 Reverse-Edge (1 Aufrufstelle, bewusste Ausnahme, siehe E.1)

services/metadata/album_processor.py          ──► services/clients/musicbrainz_client.py (lazy, method-lokal)
services/metadata/enhanced_metadata_processor.py ──► services/clients/{genius,musicbrainz,lastfm}_client.py
services/metadata/genre_processor.py          ──► KEIN Client-Import mehr (Injection über Parameter, ARCH-012)
services/metadata/cover_processor.py          ──► KEIN Client-Import (eigene requests.Session, siehe E.2)

services/statistik/ + statistik_service.py    ──► services/clients/navidrome_api.py  [normal]

services/downloader/spotify_downloader.py     ──► direkte urllib-Aufrufe an Spotify oEmbed/Embed  [kein Client-Bypass, siehe E.4]

services/clients/  ──►  (keine Rückabhängigkeit zu services/downloader/ oder services/metadata/) — 0 Treffer
services/*  ──►  handlers/*   : 0 Treffer
services/*  ──►  klassen/*    : 0 Treffer

services/clients/lastfm_client.py     ──► KEIN utils.genre_map mehr (ARCH-012 Phase 2)
services/clients/musicbrainz_client.py ──► KEIN utils.genre_map mehr (ARCH-012 Phase 3B)
```

**Import-Zyklus-Prüfung:** eigenständiger AST-basierter Scan über alle
`services/*.py`-Module (nicht nur Grep) — **0 Zyklen** gefunden, 10 Module
mit `services→services`-Kanten gescannt.

**Domain-Zyklen laut Aufgabenstellung (downloader↔metadata,
metadata↔clients, downloader↔clients, statistik↔andere):**

| Kante | Ergebnis |
|---|---|
| downloader → metadata | vorhanden (Zielrichtung) |
| metadata → downloader | 1 Treffer, ARCH-005-Ausnahme (E.1) |
| metadata → clients | vorhanden (normal, Adapter-Nutzung) |
| clients → metadata | 0 Treffer |
| downloader → clients | 0 Treffer |
| clients → downloader | 0 Treffer |
| statistik → clients (navidrome_api) | vorhanden (normal) |
| statistik → metadata/downloader | 0 Treffer |

Kein neuer Zyklus, keine neue Gegenabhängigkeit seit dem letzten Audit.

---

## E. Revalidierte Folgepunkte

### E.1 ARCH-005 Reverse-Edge

```text
services/metadata/enhanced_metadata_processor.py:41
    → cleanup_single_download_artifact()  (services/downloader/download_artifact_cleanup.py)
    Aufrufstelle: Zeile 1002, Exception-Handler in process_single_track()
```

Unverändert, exakt dieselbe eine Aufrufstelle. Bewusste, dokumentierte
Ausnahme (ARCH-005). Eine Auflösung wäre eine echte Verhaltensänderung an
einem P0-kritischen Fehlerpfad — nicht Gegenstand dieses Audits, weiterhin
nicht priorisiert.

### E.2 Last.fm-Duplikation in `cover_processor.py`

```text
services/metadata/cover_processor.py:88   _LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"
services/metadata/cover_processor.py:802  def _fetch_lastfm(self, artist)
```

Unverändert bestehend: `CoverProcessor._fetch_lastfm()` baut weiterhin eine
eigene `requests.Session`/URL/Parameter, komplett unabhängig von
`services/clients/lastfm_client.py`. `services/clients/lastfm_client.py`
bietet weiterhin **keine** Methode, die eine Cover-/Bild-URL liefert
(`fetch_metadata()` liefert nach ARCH-012 nur noch Tags + Platzhalter-Genre,
kein Bildfeld) — eine Auflösung wäre also weiterhin **keine reine
mechanische Verschiebung**, sondern erfordert eine neue Client-Fähigkeit.
Einschätzung unverändert zum Vorgänger-Audit: P2, kein sofortiger
Kandidat.

### E.3 DI-Inkonsistenz `album_processor.py`

```text
services/metadata/album_processor.py:18   def __init__(self, logger=None, mb_client=None)
services/metadata/enhanced_metadata_processor.py:125-127  AlbumProcessor(logger=...) — ohne mb_client
services/metadata/enhanced_metadata_processor.py:145,1027-1045  eigener, unabhängiger self._mb_client (lazy)
```

Unverändert bestehend, exakt am selben Code verifiziert: zwei unabhängige
`MusicBrainzClient`-Instanzen können gleichzeitig existieren, da die Facade
ihren lazy `_mb_client` nicht an `AlbumProcessor` durchreicht. Da
`musicbrainz_client.py::cached_musicbrainz_search()` weiterhin einen
modul-globalen `TTLCache` verwendet (verifiziert, Zeile 43, unverändert),
bleibt der reale Effekt gering: kein doppelter API-Cache, nur eine
zusätzliche, günstige Objektinstanz. **Kein Regelbruch, weiterhin
niedrigste Priorität aller inhaltlich relevanten Befunde.**

### E.4 Spotify-HTTP-Aufrufe

```text
services/downloader/spotify_downloader.py  — urllib.request.urlopen() an 5 Stellen
```

Unverändert: kein `services/clients/spotify_client.py` existiert, der hier
umgangen würde — anders als bei E.2 liegt hier kein Bypass eines
existierenden Adapters vor, keine Duplikation. **Architektonisch kein
Kandidat**, bestätigt niedrigste Priorität.

### E.5 `genre_rules.yaml`-Schlüssel-Mismatch

```text
utils/genre_map.py:280   self.rules = self._compile_rules(rules_data.get("GENRE_RULES", []))
mapping/genre_rules.yaml — Top-Level-Keys: keyword_rules / artist_rules / title_rules
```

**Erneut empirisch bestätigt (nicht nur aus ARCH-012-Doku übernommen):**
`rules_data.get("GENRE_RULES", [])` sucht einen Schlüssel, der in der
YAML-Datei nicht existiert — die Datei verwendet `keyword_rules`,
`artist_rules`, `title_rules`. Damit ist `self.rules` bei jedem
`GenreMapper`-Start leer und `_apply_rules()` (Schritt 4 der
5-stufigen `determine_genre()`-Priorisierungskette) strukturell dead code
für **alle** verbleibenden `GenreMapper`-Aufrufer (`genre_processor.py`s
eigene Schritte 1/2 in `determine_genre_with_fallbacks()`,
`_infer_genre_from_feat_artists()`).

**Bewertung:** echter, reproduzierbarer Bug (fachlich: eine ganze
Priorisierungsstufe wird nie ausgeführt) — aber **außerhalb** des
ARCH-012-Scopes (betrifft `GenreMapper` selbst, nicht die
Client/Prozessor-Verantwortungsgrenze, die ARCH-012 bereinigt hat). P1 nach
fachlicher Relevanz (Genre ist P0-Domäne laut CLAUDE.md §3), aber ein reiner
**Bugfix**, kein Architektur-/Boundary-Thema — passt nicht in den Rahmen
dieses Architektur-Audits. Empfehlung: eigener, kleiner, dedizierter
Bug-Auftrag (Reproduktion → Test → Fix → Regressionstest, CLAUDE.md §26),
keine Architekturphase.

### E.6 Doppelte Alias-In-Memory-Repräsentation

```text
utils/genre_map.py:274-276              self.genre_aliases  ← mapping/genre_aliases.yaml
services/metadata/genre_processor.py:54,746  self.GENRE_NORMALIZATION ← selbe Datei, eigener Loader
```

**Erneut bestätigt:** `mapping/genre_aliases.yaml` wird von zwei
unabhängigen Klassen (`GenreMapper`, `GenreProcessor`) jeweils eigenständig
eingelesen und in zwei separate Dicts gehalten (`genre_aliases` bzw.
`GENRE_NORMALIZATION`). Beide Normalisierungsmethoden
(`GenreMapper.normalize_genre_name()` vs.
`GenreProcessor.normalize_genre_name()`) sind zudem **unterschiedliche
Implementierungen** desselben fachlichen Konzepts (bereits in ARCH-012
Phase 3A als Ursache für ein überraschendes Testergebnis dokumentiert:
`"trap"` löst über `GenreProcessor` korrekt zu `"Hip Hop"` auf).

**Bewertung:** reale Duplikation (zwei Ladevorgänge, zwei
Speicherrepräsentationen, zwei leicht unterschiedliche Algorithmen für
denselben fachlichen Zweck) — aber eine Konsolidierung würde direkt in die
P0-geschützte Genre-Domäne eingreifen und **beide** Klassen gleichzeitig
berühren (`utils/genre_map.py` ist laut ARCH-012-Grenzen ausdrücklich nicht
Teil des dortigen Scopes). Kein kleiner, isolierter Schritt — P2, eigener
Auftrag falls gewünscht, kein Bugfix wie E.5 (aktuelles Verhalten ist nicht
nachweislich falsch, nur doppelt).

### E.7 `services/metadata/cache.py` vs. `utils/metadata_cache.py`

Unverändert: sauberes Decorator-/DI-Muster
(`MetadataCacheHandler(BaseMetadataCache, logger)` wrappt die aus
`utils/metadata_cache.py` importierte `MetadataCache`) — reine
Namensnähe, kein funktionaler Konflikt, keine Duplikation. Kein
Architekturbefund, P3.

### E.8 Sonstige tote Imports / Naming-Themen

Beide bereits bekannten toten Imports erneut verifiziert, unverändert
vorhanden:

- `services/metadata/enhanced_metadata_processor.py:6` — `import requests`,
  0 Verwendungen im Modul.
- `services/clients/navidrome_api.py:8` — `import subprocess`, 0
  Verwendungen im Modul.

Trivial, P3, keine eigene Phase wert.

### E.9 ARCH-011 P2 (`download/models.py` vs. `downloader/models.py`)

Zusätzlich erneut geprüft (nicht Teil der 8 explizit gelisteten Punkte,
aber offener ARCH-011-Folgepunkt): `services/downloader/download/models.py`
(160 LOC, `DownloadResult`/`PlaylistResult`) und
`services/downloader/models.py` (31 LOC, `DuplicateEntry`) haben weiterhin
**keinen** inhaltlichen Überlappungspunkt — reine Namensnähe zweier
gleichnamiger Dateien in verschachtelten Verzeichnissen. Unverändert nicht
priorisiert.

---

## F. Neue Befunde

Gezielte Suche über die Revalidierung hinaus (Boundary-Verletzungen,
Business Logic in Clients/Orchestratoren, Presentation Logic in Services,
Duplikationen, fehlender DI, Singletons/globaler State, tote Pakete,
God-Services, unnötige Utility-Sammelstellen):

- **Clients → Business Logic (Genius, Navidrome):** `genius_client.py`
  enthält `_is_valid_lyrics()` (Platzhalter-/Leertext-Filter) und
  `_find_best_match_dynamic()` (Kandidaten-Scoring) — strukturell analog zu
  `musicbrainz_client.py`s bereits akzeptiertem `_get_best_match()`/
  `similarity()`-Muster: adapter-interne Auswahl des richtigen
  Suchergebnisses aus der eigenen Domäne, keine fachliche Entscheidung, die
  domänenübergreifend wirkt (anders als die jetzt entfernte
  Genre-Priorisierung). **Kein neuer Befund**, konsistent mit dem bereits
  etablierten Bewertungsmaßstab.
- **Singletons in `services/`:** `EnhancedMetadataProcessor` und
  `EnhancedDownloadProcessor` sind beide `SingletonMixin`-basiert (analog zu
  `GenreMapper`/`ArtistNormalizer` in `utils/`). Etabliertes,
  durchgängiges Muster für teure, einmalig zu konstruierende Facades — keine
  neue Beobachtung, keine erkennbare negative Auswirkung (kein
  Test-Isolationsproblem beobachtet, bestehende Tests grün). Kein Befund.
- **Modul-globaler State außerhalb Singletons:** nur der bereits bekannte
  `_musicbrainz_result_cache` (E.3-Kontext). Keine weiteren modul-globalen
  Caches/Dicts in `services/` gefunden.
- **Tote Pakete / leere `__init__.py`:** `services/__init__.py`,
  `services/downloader/__init__.py`, `services/statistik/__init__.py` sind
  weiterhin funktionslose, aber technisch notwendige Paket-Marker. Kein
  Befund.
- **Business Logic in Downloader-Orchestratoren:** kein neuer Fund über die
  in CLAUDE.md §19 bereits bekannten großen Klassen
  (`DownloadHandler`/`RichMenuHandler` in `klassen/`/`handlers/`,
  `EnhancedMetadataProcessor` in `services/`) hinaus.
- **Presentation Logic in Services:** 0 Treffer (siehe Abschnitt C).
- **Duplikationen zwischen Services:** keine neuen über E.2/E.6 hinaus
  gefunden. Insbesondere `download_result_reporter.py`,
  `metadata_result_translator.py`, `formatters.py` (in `download/`) wurden
  auf Überlappung geprüft — unterschiedliche, nicht redundante
  Verantwortlichkeiten (Reporter: Telegram-Statusmeldungen zusammenbauen;
  Translator: Dict↔Dataclass-Übersetzung; Formatters: String-Formatierung
  innerhalb der Download-Pipeline).

**Ergebnis: keine neuen substanziellen Architekturbefunde seit dem
POST-DUPLICATEENTRY-Audit**, abgesehen von den beiden bereits durch
ARCH-012 selbst dokumentierten Nebenbefunden E.5/E.6, die hier erstmals
formal in die Priorisierung dieses Audits aufgenommen werden.

---

## G. Priorisierung

| Prio | Befund | Typ | Nutzen | Risiko | Aufwand | Charakt. nötig? |
|---|---|---|---|---|---|---|
| P1 | E.5 `genre_rules.yaml`-Key-Mismatch | Bugfix (kein Architekturthema) | hoch (ganze Regelstufe tot) | niedrig (Fix ist mechanisch: Key korrigieren + Test) | klein | ja, aber klein (1 Test: Regel greift nach Fix) |
| P2 | E.6 doppelte Alias-Repräsentation | Architektur (Duplikation) | mittel | mittel (P0-Domäne, 2 Klassen gleichzeitig) | mittel | ja, eigene Phase |
| P2 | E.2 Last.fm-Duplikation `cover_processor.py` | Architektur (Adapter-Bypass) | mittel | niedrig–mittel | mittel (neue Client-Fähigkeit nötig) | ja, kleiner Umfang |
| P3 | E.3 DI-Inkonsistenz `album_processor.py` | Stil | sehr niedrig | sehr niedrig | trivial | nein |
| P3 | E.4 Spotify direkte HTTP-Aufrufe | — | keins (kein Bypass) | — | — | nein, kein Kandidat |
| P3 | E.7 `metadata/cache.py`-Namensnähe | Stil | niedrig | niedrig | klein | nein |
| P3 | E.8 tote Imports | Stil | keins | keins | trivial | nein |
| P3 | E.9 `models.py`-Namensnähe (ARCH-011 P2) | Stil | niedrig | niedrig | klein | nein |

Wichtig zur Einordnung von E.5: die Tabelle in Abschnitt 6 der
Aufgabenstellung fragt nach Architektur-Prioritäten — E.5 ist fachlich P0/P1
relevant (Genre-Domäne, CLAUDE.md §3), aber **kein Architekturkandidat**
im Sinne dieses Audits (keine Schicht-/Boundary-Frage, sondern ein simpler
Konfigurationsfehler in einer bestehenden Klasse). Es wird hier dennoch
aufgeführt, weil es die einzige der acht revalidierten Fragen mit einer
klaren, isolierten, praktisch risikofreien Lösung ist — siehe H.

---

## H. Empfohlener nächster Schritt

**Kein Architektur-Kandidat wird für eine sofortige architektonische
Umsetzung vorgeschlagen (Ergebnis C der Aufgabenstellung für
Architektur-Kandidaten) — mit einer expliziten Ausnahme außerhalb des
Architektur-Rahmens: E.5 als eigenständiger Bugfix.**

`services/` ist architektonisch stabil genug; weitere strukturelle
Änderungen an Schichtgrenzen, Dependency-Richtung oder Verantwortungsteilung
würden aktuell überwiegend Optimierung statt notwendiger
Zielarchitekturarbeit darstellen — Ergebnis C laut Aufgabenstellung, für
alle in Abschnitt G als „Architektur" typisierten Befunde.

**Wenn dennoch gehandelt werden soll:**

- **Kleinster sinnvoller, isolierter nächster Schritt insgesamt:** E.5
  (`genre_rules.yaml`-Key-Mismatch) — kein Architekturauftrag, sondern ein
  klassischer CLAUDE.md-§26-Bugfix (Reproduktion vorhanden, minimaler Test,
  Ursache bekannt, Fix ist eine Zeile: `"GENRE_RULES"` → korrekten
  Top-Level-Schlüssel bzw. Zusammenführung von `keyword_rules`/
  `artist_rules`/`title_rules`). Erfordert vorab eine bewusste
  Verhaltensentscheidung (welche der drei YAML-Regelgruppen soll
  `_apply_rules()` tatsächlich konsumieren, und mit welcher Priorität
  gegenüber Schritt 1-3/5 der Kette?) — daher **kein automatischer
  Freifahrtschein**, sondern ein eigener, kleiner, dedizierter Auftrag mit
  eigenem Characterization-Test zuerst (CLAUDE.md §6).
- **Größter Architektur-Kandidat mit noch echtem Gewinn, falls eine
  Architekturphase gewünscht ist:** E.6 (doppelte Alias-Repräsentation) —
  Ergebnis B der Aufgabenstellung: **keine Umsetzung empfehlen**, sondern
  zunächst eine eigene Analyse-/Characterization-Phase (Vergleich beider
  `normalize_genre_name()`-Implementierungen über den vollständigen
  `genre_aliases.yaml`-Datensatz, wie in ARCH-012 Phase 3A für MusicBrainz
  bereits vorgemacht), bevor über Konsolidierung entschieden wird.

Keiner dieser beiden Punkte wird hiermit als „nächste Aufgabe" beauftragt —
die Entscheidung, ob und welcher davon verfolgt wird, liegt beim Nutzer.

---

## I. Alternativen

- E.2 (Last.fm-Duplikation `cover_processor.py`) bleibt ein legitimer,
  aber kleinerer Kandidat als E.6 — echter Architekturgewinn (ein Adapter
  weniger dupliziert), aber erfordert eine neue Client-Fähigkeit
  (`fetch_album_art_url()` o. ä.), kein reiner Strukturumzug.
- E.3 (DI-Konsistenz `album_processor.py`) bleibt jederzeit risikofrei
  nachholbar (eine Zeile: `mb_client=self._mb_client` durchreichen), aber
  ohne den in E.3 dokumentierten Ressourcen-Nutzen — rein kosmetisch.

---

## J. Bewusst zurückgestellt

- **E.2** — erfordert neue Client-Fähigkeit, kein reiner Migrationsschritt.
- **E.3** — nach Präzisierung kaum noch architektonischer Nutzen.
- **E.4** — kein Duplikations-/Bypass-Risiko, kein echter Kandidat.
- **E.6** — architektonisch real, aber P0-Domäne, erfordert eigene
  Characterization-Phase vor jeder Entscheidung.
- **E.7, E.8, E.9** — kosmetisch, keine eigene Phase wert.
- **E.5** — fachlich relevant, aber bewusst nicht als Teil dieses
  Architektur-Audits vorangetrieben (siehe G); als eigener Bugfix-Auftrag
  offen, falls gewünscht.

---

## K. Erwarteter Scope (falls E.5 oder E.6 beauftragt werden)

- **E.5 (Bugfix):** `utils/genre_map.py` (Loader-Fix), `mapping/genre_rules.yaml`
  (ggf. Struktur-Entscheidung), 1 neuer Characterization-Test vor dem Fix,
  Regressionstest danach. Betrifft **nicht** `services/clients/` (dort ist
  `GenreMapper` seit ARCH-012 nicht mehr verankert) — nur noch
  `genre_processor.py`s eigene Schritte 1/2 und `_infer_genre_from_feat_artists()`
  sind betroffen.
- **E.6 (Analysephase, keine Umsetzung):** `utils/genre_map.py`,
  `services/metadata/genre_processor.py`, `mapping/genre_aliases.yaml` —
  Vergleich beider Normalisierungsalgorithmen, keine Codeänderung in dieser
  Phase.

---

## L. Risiko

- **E.5:** niedrig bei korrektem Vorgehen (Characterization zuerst), aber
  **nicht null** — `_apply_rules()` war seit jeher (nicht erst seit
  ARCH-012) dead code; sein Aktivieren ändert das reale Genre-Ergebnis für
  potenziell viele Tracks zum ersten Mal in der Projekthistorie. Erfordert
  laut CLAUDE.md §15/§16 konkrete Vorher/Nachher-Beispiele, nicht nur einen
  Unit-Test.
- **E.6:** mittel — beide betroffenen Klassen liegen in der P0-Domäne,
  Konsolidierung könnte Genre-Ergebnisse in Randfällen verändern (wie schon
  bei ARCH-012 Phase 3A/3B mehrfach empirisch beobachtet, z. B. der
  `"trap"`→`"Hip Hop"`-Alias-Fall).

---

## M. Dokumentationsänderungen

Dieses Dokument (`docs/POST-ARCH-012_Services_Architecture_Audit.md`) neu
erstellt. Keine Änderung an bestehenden Dokumenten — insbesondere
`docs/MusicBot_ARCH-012_Genre_Logic_Characterization.md` bleibt
unverändert (historische Dokumentation, nicht rückwirkend umgeschrieben).

---

## N. Entscheidungsgate

**POST-ARCH-012 SERVICES ARCHITECTURE AUDIT — ENTSCHEIDUNGSGATE ERREICHT**

Der Audit ist abgeschlossen. Keine Codeänderungen wurden vorgenommen.

**Architektonisch (Schichtgrenzen, Dependency-Richtung, Boundary-Fragen):
Ergebnis C.** `services/` ist nach ARCH-009/010/011/012 architektonisch
stabil genug — 0 funktionale `services/*→handlers/*`- und
`services/*→klassen/*`-Abhängigkeiten, 0 Import-Zyklen, keine neuen
Schichtverletzungen, keine neuen Duplikationen über die bereits bekannten
E.2/E.6 hinaus. Weitere Änderungen an Schichtgrenzen oder
Verantwortungsteilung wären aktuell überwiegend Optimierung statt
notwendiger Zielarchitekturarbeit.

**Fachlich (außerhalb des Architektur-Scopes): ein einzelner, klar
isolierter Bugfix-Kandidat (E.5) existiert** — kein Architekturauftrag,
sondern ein eigenständiger, kleiner Bug in `utils/genre_map.py`
(`genre_rules.yaml`-Schlüssel-Mismatch), der eine ganze
Priorisierungsstufe der Genre-Erkennung strukturell außer Kraft setzt.

**Empfehlung:** kein Architektur-Kandidat zur sofortigen Umsetzung. Falls
Handlungsbedarf gewünscht ist, zwei getrennte, unabhängige Wege:

1. E.5 als eigener, kleiner Bugfix-Auftrag (CLAUDE.md §26-Muster), oder
2. E.6 als eigene Analyse-/Characterization-Phase (kein Umsetzungsauftrag).

Beide erfordern eine explizite, separate Freigabe — keiner wird durch
dieses Audit selbst beauftragt.
