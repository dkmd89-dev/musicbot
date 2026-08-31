# POST-DUPLICATEENTRY Services Architecture Audit

## Status

**Audit abgeschlossen (2026-08-24). Kein Code geändert, keine Migration,
kein Refactoring, keine Umbenennung, kein Commit, kein PR.**
Entscheidungsgate am Ende, wartet auf Freigabe.

---

## 1. Audit-Ziel und Ausgangslage

ARCH-009/010/011 sind abgeschlossen. Zusätzlich wurde seither
`DuplicateEntry` aus `handlers/duplicate_handler.py` nach
`services/downloader/models.py` verschoben (PR #23, Merge-Commit `31bf700`)
— der im vorherigen Audit (`docs/archive/post-arch/MusicBot_POST-ARCH-010_011_Services_Zielarchitektur_Audit.md`)
empfohlene nächste Schritt.

Dieser Audit ist die Fortsetzung: ein erneuter, vollständiger, aber
fokussierter Blick auf den **jetzigen** Stand von `services/`, um zu
klären, ob die Zielarchitektur nach dieser Migration tatsächlich
schichtsauber ist, welche bewussten Ausnahmen weiterhin bestehen, welche
neuen Befunde es gibt, und — das eigentliche Ziel — **den einen
sinnvollsten nächsten Schritt** zu bestimmen, nicht die längste
Wunschliste.

Referenzierte, bereits etablierte Regelbasis (nicht neu erfunden):
`CLAUDE.md`, ARCH-009, ARCH-010, ARCH-011,
`docs/archive/MusicBot_SERVICES_Zielarchitektur_Audit.md`,
`docs/archive/post-arch/MusicBot_POST-ARCH-010_011_Services_Zielarchitektur_Audit.md`,
`docs/archive/post-arch/MusicBot_POST-ARCH-010_011_DuplicateEntry_Analyse.md`.

---

## 2. Aktuelle Services-Zielstruktur

```text
services/
├── __init__.py                      (leer)
├── statistik_service.py             143 LOC — dünne Fassade (ARCH-003 P-6)
├── clients/                         4 Dateien, 1388 LOC — externe Adapter
│   ├── genius_client.py             551 LOC
│   ├── lastfm_client.py             151 LOC
│   ├── musicbrainz_client.py        469 LOC
│   └── navidrome_api.py             217 LOC
├── downloader/                      10 Dateien (+ download/), 3750 LOC
│   ├── download_artifact_cleanup.py 168 LOC
│   ├── downloader.py                119 LOC
│   ├── download_result_reporter.py  309 LOC
│   ├── download_utils.py            908 LOC
│   ├── errors.py                     99 LOC
│   ├── metadata_result_translator.py 207 LOC
│   ├── models.py                     31 LOC  ← NEU seit DuplicateEntry-Migration
│   ├── playlist_processor.py        604 LOC
│   ├── progress_tracker.py          146 LOC
│   ├── spotify_downloader.py        942 LOC
│   └── download/                    7 Dateien, 1578 LOC (ARCH-011: bestätigt intern)
├── metadata/                        11 Dateien, 4699 LOC
│   ├── album_processor.py           159 LOC
│   ├── artist_processor.py          215 LOC
│   ├── auto_learn.py                458 LOC
│   ├── cache.py                     183 LOC
│   ├── cover_processor.py           955 LOC
│   ├── enhanced_metadata_processor.py 1203 LOC — Facade
│   ├── genre_processor.py           765 LOC
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

Kein neuer Top-Level-Bereich seit dem letzten Audit entstanden. Einzige
strukturelle Änderung: `services/downloader/models.py` (neu, aus der
DuplicateEntry-Migration).

---

## 3. Regelprüfung

### 3.1 `services/clients/`

Alle 4 Clients sind echte externe Integrationsadapter (`aiohttp`+
`lyricsgenius` für Genius, `pylast` für Last.fm, `musicbrainzngs` für
MusicBrainz, `requests` für Navidrome/Subsonic). Kein Telegram-/
Presentation-Code, keine Credentials im Klartext geloggt.

**Unverändert bestehender Befund (Regel-A-Verstoß):** `lastfm_client.py`
und `musicbrainz_client.py` enthalten fachliche Genre-Bestimmungslogik
(`GenreMapper.determine_genre()`-Aufrufe direkt im Client) statt reiner
API-Kommunikation — siehe Abschnitt 5.2 (Revalidierung).

**Neu geprüft — globaler Zustand in Clients:**
`musicbrainz_client.py` hält ein **modul-globales** `TTLCache`
(`_musicbrainz_result_cache = TTLCache(maxsize=200, ttl=3600)`, Zeile 33),
das über die freie Funktion `cached_musicbrainz_search()` von **allen**
`MusicBrainzClient`-Instanzen gemeinsam genutzt wird — unabhängig davon,
wie viele Instanzen im Prozess existieren. Das ist ein legitimer,
bewusster Adapter-interner Performance-Cache (reduziert reale API-Last),
**keine** verdeckte Fachlogik, daher **kein neuer Architekturbefund**.
Wichtig für Abschnitt 5.4: Diese Cache-Architektur bedeutet, dass die dort
diskutierte doppelte `MusicBrainzClient()`-Instanziierung **keine**
doppelte API-Ergebnis-Cache-Kopie erzeugt — der Effizienzverlust ist
kleiner als im Vorgänger-Audit angenommen.

`navidrome_api.py`: weiterhin ein toter `import subprocess` (Zeile 8,
keine Verwendung im File) — trivial, siehe 5.6.

### 3.2 `services/downloader/`

Intern weiterhin sauber. `services/downloader/download/` bleibt gemäß
ARCH-011 Phase 1 unverändert als interne technische Zerlegung von
`download_utils.py` bestehen — **kein neuer Consumer, kein neuer Befund**,
daher nicht erneut als Problem markiert.

Das neue `services/downloader/models.py` fügt sich sauber ein: reine
Dataclass (`DuplicateEntry`), 3 Konsumenten (`download_result_reporter.py`,
`klassen/download_handler.py`, `handlers/duplicate_handler.py` selbst als
Rückimporteur) — kein neuer Namenskonflikt mit
`services/downloader/download/models.py` (unterschiedliche Inhalte,
unterschiedliche Pfade, ARCH-011-P2-Frage bleibt separat und unverändert
zurückgestellt).

Keine Handler-/Telegram-Abhängigkeit mehr im gesamten `services/downloader/`-
Baum (siehe 3.6).

### 3.3 `services/metadata/`

Kohärente Domain, `enhanced_metadata_processor.py` bleibt die einzige
öffentliche Facade — repo-weit weiterhin **null** externe Direktimporte
der Unterprozessoren außerhalb von `services/metadata/` und den Tests.
ARCH-005-Reverse-Edge unverändert, exakt eine Aufrufstelle (siehe 5.1).

Besonders geprüft:
- `genre_processor.py` — verifiziert korrekte alleinige Entscheidungs-
  hoheit gegenüber den Clients, siehe 5.2.
- `cover_processor.py` — Last.fm-Duplikation unverändert vorhanden, siehe
  5.3.
- `album_processor.py` — DI-Musterfrage unverändert vorhanden, aber
  schwächerer Effekt als zuvor angenommen (siehe 3.1, 5.4).
- `lyrics_processor.py` — unverändert Pflicht-Injection, kein Fallback.

### 3.4 `services/statistik/`

ARCH-003/P-6 weiterhin eingehalten: `statistik_service.py` bleibt eine
143-Zeilen-Fassade mit genau einer Klasse (`StatistikService`), die vier
fokussierten Klassen in `services/statistik/` (Repository, Poller,
Calculator, Renderer) delegieren. Keine Telegram-/Handler-Kopplung, DI
über den etablierten „ARCH-003 P-8"-Musters
(`self.api = navidrome_api if navidrome_api is not None else NavidromeAPI()`).
**Kein neuer Befund, keine erneute Aufteilung nötig.**

### 3.5 Top-Level `utils/`

Keine neue fachliche Boundary gefunden, die eine Verschiebung nach
`services/` rechtfertigen würde. `utils/filenamefixer.py` und
`utils/genre_map.py` bleiben bewusst als querschnittliche, von mehreren
Services gemeinsam genutzte Bausteine eingeordnet (`GenreMapper` wird von
`services/metadata/genre_processor.py` **und** direkt von
`services/clients/lastfm_client.py`/`musicbrainz_client.py` verwendet —
das ist der Kern von Befund 5.2, nicht ein Grund, `genre_map.py` selbst zu
verschieben). `utils/bot_restart_trigger.py` und
`utils/navidrome_scan_trigger.py` bleiben korrekt als lokale Subprocess-/
Shell-Runner ohne echte Netzwerkkommunikation eingeordnet.

### 3.6 `handlers/`-/`klassen/`-Grenzen

**`services/* → handlers/*`: 0 funktionale Treffer.** Repo-weit erneut
geprüft (`grep -rn "^from handlers\|^import handlers" services/`) —
leer. Die letzte bekannte Verletzung (`download_result_reporter.py →
DuplicateEntry`) ist durch die Migration beseitigt.

**`services/* → klassen/*`: 0 Treffer.** Kein Service importiert aus
`klassen/`.

**`klassen/download_handler.py`** (einziges verbliebenes Modul in
`klassen/`) importiert sowohl aus `handlers/` (`EnhancedDuplicateHandler`)
als auch aus mehreren `services/`-Modulen, **und** hat selbst direkte
Telegram-Importe (`from telegram import Message, Update`,
`telegram.error.TelegramError`, `telegram.ext.ContextTypes`). Das ist
**keine Schichtverletzung**, sondern die erwartete Rolle dieser Datei:
`klassen/download_handler.py` ist laut CLAUDE.md-Architekturdiagramm der
Orchestrator zwischen `RichMenuHandler` und der Download-/Metadaten-
Pipeline — die einzige Stelle im Repo, die bewusst Handler-Objekte,
Services **und** Telegram-I/O zusammenführt. Die in CLAUDE.md §4
definierte Grenze („Services dürfen nicht von Telegram-/Handler-
Präsentation abhängen") gilt für `services/`, nicht für `klassen/`. Keine
automatische Migration vorgeschlagen.

---

## 4. Dependency-Audit

```text
handlers/
   │  (Telegram-Präsentation, MarkdownV2, Update/CallbackQuery)
   ▼
services/
   │
   ├── services/downloader/ ──► services/metadata/     [Zielrichtung, ARCH-010 bestätigt]
   │        ▲
   │        └── ARCH-005 Reverse-Edge (1 Aufrufstelle, bewusste Ausnahme, unverändert, 5.1)
   │
   ├── services/metadata/ ──► services/clients/  (genius_client, lastfm_client, musicbrainz_client)
   │        [normal, aber: lastfm_client.py + musicbrainz_client.py rufen selbst
   │         utils/genre_map.py auf und treffen Genre-Entscheidungen — 5.2]
   │
   ├── services/statistik/ + statistik_service.py ──► services/clients/navidrome_api.py  [normal]
   │
   ├── services/downloader/spotify_downloader.py ──► direkte HTTP-Aufrufe (urllib) an
   │        open.spotify.com  [kein Client-Bypass — nie ein spotify_client.py existiert, 5.5]
   │
   └── services/metadata/cover_processor.py ──► direkte HTTP-Aufrufe (requests) an
            Cover Art Archive, Fanart.tv, Apple Music, Deezer, Last.fm
            [Last.fm-Teil dupliziert services/clients/lastfm_client.py, 5.3;
             die übrigen 4 Quellen haben keinen eigenen Client — kein Bypass]

services/clients/  ──►  (keine Abhängigkeit zurück in services/downloader/ oder services/metadata/)
   [erneut bestätigt: 0 Treffer]

services/*  ──►  handlers/*   : 0 Treffer (DuplicateEntry-Migration abgeschlossen)
services/*  ──►  klassen/*    : 0 Treffer
klassen/download_handler.py ──► handlers/*, services/*, telegram   [Orchestrator-Rolle, erwartet]
```

Seit dem letzten Audit sind **keine neuen** Gegenabhängigkeiten
entstanden. Der einzige strukturelle Unterschied: die
`services→handlers`-Kante ist jetzt vollständig geschlossen.

---

## 5. Bekannte Folgepunkte — Revalidierung

### 5.1 ARCH-005 Reverse-Edge

```text
services/metadata/enhanced_metadata_processor.py:1002
    → cleanup_single_download_artifact()  (services/downloader/download_artifact_cleanup.py)
```

Unverändert, exakt dieselbe eine Aufrufstelle im Exception-Handler von
`process_single_track()`. **Bewusste, bestehende Ausnahme** — nicht als
neuer Fehler klassifiziert. Eine Auflösung wäre weiterhin eine echte
Verhaltensänderung an einem P0-kritischen Fehlerpfad, kein reiner
Struktur-Umzug.

### 5.2 Genre-Duplikation

Erneut am aktuellen Code verifiziert, **unverändert bestehend**:

- `services/clients/lastfm_client.py::fetch_metadata()` instanziiert einen
  eigenen `GenreMapper()` (Zeile 41) und ruft `determine_genre()` selbst
  auf (Zeile 130), um einen `"genre"`-Schlüssel im Rückgabe-Dict zu
  befüllen.
- `services/clients/musicbrainz_client.py` nutzt den Singleton-Getter
  `get_genre_mapper()` (Zeile 96) und ruft `determine_genre()` an zwei
  Stellen auf (Zeile 430, 436).
- `services/metadata/genre_processor.py::_fetch_genre_from_lastfm()`
  (Zeile 606ff.) verwendet das vom Client vorberechnete Genre **nicht**
  als Ergebnis — nur als Tag-Fallback, falls `tags` leer ist (Zeile 628).
  Die eigentliche Entscheidung trifft `genre_processor.py` erneut über
  `self.prioritize_genres(tags, ...)` mit einem eigenen, injizierten
  `GenreMapper`.

**Bewertung unverändert:** echter Regel-A-Verstoß (Fachlogik im Adapter)
und doppelte Berechnung in der P0-geschützten Genre-Domäne (CLAUDE.md §10,
§16). Architektonisch der klarste verbleibende Befund im gesamten Audit —
aber eine Änderung würde die Genre-Pipeline direkt berühren und erfordert
laut CLAUDE.md §6 vorherige Characterization-Tests für beide Pfade, bevor
irgendetwas geändert wird. Größerer, eigener Auftrag — kein sofortiger
Schritt.

### 5.3 Last.fm-Duplikation

Erneut verifiziert: `CoverProcessor._fetch_lastfm()`
(`services/metadata/cover_processor.py`, Zeile 802) baut eine eigene
`requests.Session`, eigene URL (`_LASTFM_BASE`), eigene Parameter —
vollständig unabhängig von `services/clients/lastfm_client.py`. Die
übrigen 5 Cover-Quellen (Cover Art Archive, Fanart.tv ×2, Apple Music,
Deezer, YouTube-Thumbnail) haben keinen entsprechenden Client — dort
liegt keine Duplikation vor.

**Neu geprüft — Aufwandseinschätzung präzisiert:** `services/clients/lastfm_client.py`
bietet aktuell **keine** Methode, die eine Cover-/Bild-URL liefert
(`fetch_metadata()` liefert Tags/Genre-Metadaten, kein Bild-Feld). Eine
Auflösung wäre damit **keine reine mechanische Verschiebung**, sondern
erfordert eine echte, neue Fähigkeit im Client (z. B. eine
`fetch_album_art_url()`-Methode) — größerer Scope als zunächst
eingeschätzt, kein „kleiner nächster Schritt".

### 5.4 DI-Inkonsistenz

`album_processor.py::__init__(self, logger=None, mb_client=None)` —
optional injizierbar, mit Lazy-Fallback (`MusicBrainzClient()`, Zeile
141–142) falls nicht gesetzt. `lyrics_processor.py::__init__(self,
genius_client, logger=None)` — Pflichtparameter, kein Fallback.

`enhanced_metadata_processor.py` konstruiert `AlbumProcessor` **ohne**
`mb_client` (Zeile 125–127); die Facade hat ihren eigenen, unabhängigen
lazy `self._mb_client` (für `genre_processor`, per Methodenparameter
injiziert, Zeile 1027–1045), der aber nie an `AlbumProcessor`
weitergereicht wird. Dadurch können zwei unabhängige
`MusicBrainzClient`-Objektinstanzen gleichzeitig existieren.

**Präzisierung gegenüber dem Vorgänger-Audit (siehe 3.1):** Da
`musicbrainz_client.py::cached_musicbrainz_search()` einen
**modul-globalen** `TTLCache` verwendet, teilen sich beide Instanzen
denselben API-Ergebnis-Cache — es entsteht **keine** doppelte
Cache-Kopie, nur eine zusätzliche, leichte Python-Objektinstanz
(`MusicBrainzClient.__init__` selbst ist günstig, keine eigene
Netzwerkverbindung wird beim Konstruieren aufgebaut). Der reale Effekt
ist damit **kleiner** als zuvor eingeschätzt: keine echte
Ressourcenverdopplung, nur eine unnötige zusätzliche Objektinstanz und
eine stilistische Inkonsistenz zwischen zwei DI-Mustern, die beide bereits
anderswo im Code Präzedenzfälle haben (optional+Fallback:
`statistik_service.py`, ARCH-003 P-8; Pflicht-Injection:
`lyrics_processor.py`). **Kein Regelbruch, lokale Konsistenzfrage** —
weiterhin niedrigste Priorität aller inhaltlich relevanten Befunde.

### 5.5 Spotify HTTP

Unverändert: `spotify_downloader.py` nutzt `urllib.request.urlopen()` für
Spotify Embed-/oEmbed-API. Es existiert weiterhin **kein**
`services/clients/spotify_client.py`, der hier umgangen würde — anders
als bei 5.3 (wo ein echter Client existiert und ignoriert wird) liegt
hier schlicht keine Adapter-Abstraktion vor, keine Duplikation.
**Architektonisch kein relevanter Kandidat** (kein Bypass, keine
Doppelarbeit) — bestätigt niedrigste Priorität.

### 5.6 Weitere relevante Befunde (aus vorherigem Audit, unverändert)

- `services/metadata/cache.py` vs. `utils/metadata_cache.py`: sauberes
  Decorator-/DI-Muster (`MetadataCacheHandler` wrappt `MetadataCache` per
  Injection), nur Namensnähe, kein funktionaler Konflikt.
- `services/downloader/download/models.py` (ARCH-011 P2): unverändert,
  ausdrücklich nicht priorisiert.
- Toter Import `import requests` in `enhanced_metadata_processor.py`
  (Zeile 6, 0 Aufrufe) — trivial, P3.
- Toter Import `import subprocess` in `navidrome_api.py` (Zeile 8, 0
  Aufrufe) — trivial, P3.

---

## 6. Neue Befunde

Über die Revalidierung hinaus wurde gezielt nach neuen Boundary-Problemen,
Duplikationen, Dependency-Problemen und toten Strukturen gesucht
(Abschnitt 5 der Aufgabenstellung). Ergebnis:

- **Keine neuen Boundary-Probleme.** Kein Service enthält
  Präsentationslogik, kein Client enthält Business-Logik über den
  bekannten Genre-Befund (5.2) hinaus.
- **Keine neuen Duplikationen.** Keine doppelten Formatter/Translator,
  keine doppelten Datenmodelle (`services/downloader/models.py` und
  `services/downloader/download/models.py` haben unterschiedliche,
  nicht überlappende Inhalte).
- **Keine neuen Dependency-Probleme.** Kein Import-Zyklus gefunden
  (Smoke-Tests bei der DuplicateEntry-Migration bereits verifiziert,
  hier zusätzlich per Grep über alle Cross-Boundary-Importe bestätigt).
  Der einzige module-globale Zustand (`musicbrainz_client.py`s
  `TTLCache`, 3.1) ist ein legitimer Performance-Cache, kein
  verdecktes Problem.
- **Keine neuen toten Strukturen** über die bereits in ARCH-011
  (`TrackResultCollector`, `DownloadCoordinator` in
  `download/interfaces.py`) und diesem Audit (5.6, tote Imports)
  bekannten hinaus. Kein leeres Paket ohne Zweck gefunden — die leeren
  `__init__.py`-Dateien (`services/__init__.py`,
  `services/downloader/__init__.py`, `services/statistik/__init__.py`)
  sind technisch notwendige, funktionslose Paket-Marker, kein Befund.

**Ergebnis: keine neuen substanziellen Architekturbefunde seit dem
vorherigen Audit** — nur die in Abschnitt 5.4 dokumentierte Präzisierung
eines bestehenden Befunds (kleinerer Effekt als angenommen).

---

## 7. Priorisierung

| Priorität | Kandidat | Nutzen | Risiko | Aufwand | Empfehlung |
|---|---|---|---|---|---|
| P1 (eigene Folge-Phase) | Genre-Logik in `lastfm_client.py`/`musicbrainz_client.py` (5.2) | hoch — räumt echte Fachlogik-Vermischung in P0-Domäne auf | mittel (P0-Bereich, Randfälle möglich) | mittel–hoch (2 Clients + `genre_processor.py`, Characterization-Tests zuerst) | Als eigener, dedizierter Auftrag empfohlen — **nicht** der nächste Schritt |
| P2 | Last.fm-Duplikation `cover_processor.py` (5.3) | mittel | niedrig–mittel | mittel (echte neue Client-Fähigkeit nötig, keine reine Verschiebung) | Guter Kandidat für eine spätere, eigene kleine Phase |
| P3 | DI-Inkonsistenz `album_processor.py` (5.4) | sehr niedrig (kein Ressourcen-Doppelverbrauch mehr, nur Stil) | sehr niedrig | sehr klein | Optional, jederzeit risikofrei nachholbar |
| P3 | `spotify_downloader.py` direkte HTTP-Aufrufe (5.5) | keins (kein Bypass, keine Duplikation) | — | — | Kein Kandidat |
| P3 | `metadata/cache.py`-Umbenennung (5.6) | niedrig | niedrig | klein | Kosmetisch, keine eigene Phase wert |
| P3 | tote Imports (5.6) | keins | keins | trivial | Kein eigener Kandidat |

Vollständige Tabelle im Vergleich zum vorherigen Audit unverändert bis auf
zwei Punkte: der frühere P1-Kandidat (`DuplicateEntry`) ist umgesetzt und
entfällt; die DI-Inkonsistenz (5.4) ist von P2 auf P3 herabgestuft (siehe
Präzisierung in 5.4).

---

## 8. Empfohlener nächster Schritt

**Kein Kandidat wird für eine sofortige Umsetzung vorgeschlagen — und das
ist ein bewusstes, begründetes Ergebnis dieses Audits, kein Ausweichen.**

### Warum keine sofortige Umsetzung?

Nach der `DuplicateEntry`-Migration ist die Liste der noch offenen
Kandidaten in zwei klar getrennte Gruppen zerfallen:

1. **Ein einziger architektonisch bedeutsamer Befund** (Genre-Logik-
   Duplikation, 5.2) — aber dieser ist laut eigener Bewertung **zu groß
   und zu risikobehaftet** für einen unmittelbaren, isolierten nächsten
   Schritt: er berührt aktive Entscheidungslogik in der am stärksten
   geschützten Domäne des Projekts (CLAUDE.md: „Besonders geschützt:
   Metadata, Artist, Genre") und erfordert vorab eigene
   Characterization-Tests für zwei Client-Dateien plus
   `genre_processor.py` — ein eigenständiger, mehrstufiger Auftrag, kein
   „kleiner nächster Schritt" im Sinne dieses Audits.
2. **Mehrere kleine Kandidaten (P2/P3)**, die aber bei genauer Prüfung
   entweder keinen echten Architekturgewinn mehr bieten (5.4, nach der
   Präzisierung in Abschnitt 5.4 nur noch eine stilistische Frage ohne
   Ressourcen-Konsequenz), keinen tatsächlichen Bypass darstellen (5.5),
   oder — der einzige davon mit noch etwas Substanz, 5.3 — bei genauerem
   Hinsehen **keine reine mechanische Verschiebung** ist, sondern eine
   echte, neue Client-Fähigkeit erfordert (Bild-URL-Methode in
   `lastfm_client.py` existiert nicht).

Es gibt damit aktuell **keinen Kandidaten**, der gleichzeitig (a) einen
spürbaren Architekturgewinn bietet und (b) mit dem in dieser Session
etablierten Sicherheitsniveau (mechanische Verschiebung, keine
Verhaltensänderung, trivialer Smoke-Test als Verifikation) umsetzbar wäre
— das war beim `DuplicateEntry`-Schritt noch der Fall, ist es jetzt nicht
mehr.

### Wenn dennoch ein Schritt gewünscht ist

Zwei ehrliche Alternativen, je nach Ziel:

- **Für höchsten Architekturgewinn:** Genre-Logik-Duplikation (5.2) als
  eigene, dedizierte Analyse-/Characterization-Phase beauftragen (Scope:
  `services/clients/lastfm_client.py`, `services/clients/musicbrainz_client.py`,
  `services/metadata/genre_processor.py` — echtes Refactoring, keine reine
  Migration, mittleres bis hohes Risiko).
- **Für einen weiteren risikofreien, aber architektonisch geringwertigen
  Schritt:** DI-Konsistenz in `album_processor.py` (5.4) — eine Zeile
  Änderung (`self._mb_client` der Facade an `AlbumProcessor` durchreichen),
  reine Migration, praktisch kein Risiko, aber auch kein nennenswerter
  Architekturgewinn mehr (siehe Präzisierung 5.4).

Diese Entscheidung liegt bewusst beim Nutzer — der Audit spricht keine
Empfehlung „irgendetwas jetzt tun" aus, wenn der ehrliche Befund lautet,
dass kein Kandidat das bisherige Sicherheits-/Nutzenverhältnis erreicht.

---

## 9. Nicht jetzt bearbeiten

- **Genre-Logik-Duplikation (5.2)** — architektonisch der wichtigste
  Befund, aber zu groß/riskant für einen isolierten nächsten Schritt;
  erfordert eigene Characterization-Phase.
- **Last.fm-Duplikation in `cover_processor.py` (5.3)** — erfordert eine
  neue Client-Fähigkeit, keine reine Verschiebung.
- **DI-Konsistenz `album_processor.py` (5.4)** — nach Präzisierung kaum
  noch architektonischer Nutzen, jederzeit risikofrei nachholbar, aber
  nicht dringend.
- **`spotify_downloader.py` direkte HTTP-Aufrufe (5.5)** — kein
  Duplikations-/Bypass-Risiko, kein echter Kandidat.
- **Namensfragen (`metadata/cache.py`), tote Imports (5.6)** — kosmetisch,
  keine eigene Phase wert.

---

## 10. Entscheidungsgate

**POST-DUPLICATEENTRY SERVICES ARCHITECTURE AUDIT —
ENTSCHEIDUNGSGATE ERREICHT**

Der Audit ist abgeschlossen.
Keine Codeänderungen wurden vorgenommen.

**Empfohlener nächster Kandidat: keiner zur sofortigen Umsetzung.**
Die Services-Zielarchitektur ist nach ARCH-009/010/011 und der
DuplicateEntry-Migration strukturell stabil — 0 funktionale
`services/*→handlers/*`- und `services/*→klassen/*`-Abhängigkeiten, keine
neuen Schichtverletzungen, keine neuen Duplikationen. Der einzige
verbleibende substanzielle Befund (Genre-Logik-Duplikation, 5.2) ist
architektonisch real, aber bewusst als eigener, größerer Folgeauftrag
zurückgestellt statt als „nächster kleiner Schritt" verkauft.

Umsetzung — falls gewünscht — erst nach ausdrücklicher Freigabe und mit
vorheriger Entscheidung, welche der beiden in Abschnitt 8 genannten
Alternativen (Genre-Phase vs. DI-Kleinstschritt) verfolgt werden soll.
