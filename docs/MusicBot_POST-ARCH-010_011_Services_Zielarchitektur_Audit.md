# POST-ARCH-010/011 — Services-Zielarchitektur-Audit

## Status

**Analyse abgeschlossen (2026-08-24). Kein Code geändert, keine Migration,
keine automatische Umsetzung.** Entscheidungsgate am Ende, wartet auf
Freigabe.

---

## 1. Ausgangslage

ARCH-010 hat `services/downloader/utils/` vollständig in `services/downloader/`
und `services/metadata/` aufgelöst und ist abgeschlossen (PR #14–#21).
ARCH-011 Phase 1 hat `services/downloader/download/` untersucht und
ausdrücklich entschieden, dass diese Struktur als interne technische
Zerlegung von `download_utils.py` bestehen bleibt — keine Migration (PR #22).

Dieses Dokument ist der nächste, übergeordnete Schritt: ein repo-weiter
Audit des **gesamten aktuellen** `services/`-Stands gegen die durch
ARCH-009/010/011 bereits etablierte Zielarchitektur. Ziel ist **nicht**,
möglichst viele neue Baustellen zu finden, sondern zu klären, ob die
Zielarchitektur tatsächlich erfüllt ist und — falls nicht vollständig —
welcher **einzige** nächste Kandidat den größten Nutzen bei kleinstem
Risiko bietet.

---

## 2. ARCH-010/011 — aktueller Stand

| Phase | Ergebnis |
|---|---|
| ARCH-009 | Schichtgrenzen etabliert: `handlers/` (Telegram-Präsentation), `services/` (Orchestrierung), `services/clients/` (reine externe Adapter), `utils/` (technische Querschnitts-Helfer) |
| ARCH-010 | `services/downloader/utils/` (17 Dateien, 2 vermischte Domänen) vollständig in `services/downloader/` (5 Dateien) + `services/metadata/` (11 Dateien) aufgelöst. Alte Struktur physisch entfernt. Baseline: 1009 passed / 15 bekannte Vorbestand-Fehler, unverändert über alle Phasen |
| ARCH-011 Phase 1 | `services/downloader/download/` (7 Dateien) untersucht — Ergebnis: interne Zerlegung von `download_utils.py`, kein externer Multi-Consumer, keine Migration empfohlen. Paket bleibt bestehen |

Beide Migrationen sind auf `main` gemerged. Dieser Audit baut direkt darauf
auf und ändert keine der dort getroffenen Entscheidungen.

---

## 3. Services-Bestandsaufnahme (aktueller Stand)

```text
services/
├── __init__.py                      (leer)
├── statistik_service.py             143 LOC — dünne Fassade
├── clients/                         4 Dateien, 1388 LOC — externe Adapter
│   ├── genius_client.py             551 LOC
│   ├── lastfm_client.py             151 LOC
│   ├── musicbrainz_client.py        469 LOC
│   └── navidrome_api.py             217 LOC
├── downloader/                      10 Dateien (+ download/), 3719 LOC
│   ├── download_artifact_cleanup.py 168 LOC
│   ├── downloader.py                119 LOC
│   ├── download_result_reporter.py  309 LOC
│   ├── download_utils.py            908 LOC
│   ├── errors.py                     99 LOC
│   ├── metadata_result_translator.py 207 LOC
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

Kein `services/library/` vorhanden — Datei-/Verzeichnis-/Tag-Organisation
liegt vollständig und bewusst in `utils/filenamefixer.py` (technischer
Querschnitts-Helfer, keine Service-Domäne). Kein neuer Top-Level-Bereich
seit ARCH-010/011 entstanden.

---

## 4. Schichtgrenzenprüfung

### Regel A — `services/clients/`

Alle 4 Clients sind echte externe Integrationsadapter (jeweils eine reale
externe Bibliothek/API: `aiohttp`+`lyricsgenius` (Genius), `pylast`
(Last.fm), `musicbrainzngs` (MusicBrainz), `requests` (Navidrome/Subsonic)).
Keiner enthält Telegram-/Presentation-Code. Kein Service außerhalb von
`clients/` verwendet `requests`/`httpx`/`urllib` **ohne** dass es bereits
bekannt/dokumentiert wäre (siehe Abschnitt 6, Punkte 2 und 3).

**Konkreter Regel-A-Befund (neu, siehe Abschnitt 7.1):**
`lastfm_client.py` und `musicbrainz_client.py` enthalten **fachliche
Genre-Bestimmungslogik** (`GenreMapper.determine_genre()`-Aufrufe direkt im
Client), nicht nur reine API-Kommunikation. `services/metadata/genre_processor.py`
verwirft bzw. wiederholt diese Berechnung größtenteils selbst — echte
Doppelarbeit in einer P0-geschützten Domäne (CLAUDE.md §10 „Mapping-Dateien
sind Fachlogik", §16 „Metadata").

`navidrome_api.py` enthält einen ungenutzten `import subprocess` (keine
tatsächliche Subprocess-Nutzung im Code — vermutlich Rest einer früheren
Implementierung). Trivial, aber der Vollständigkeit halber erfasst.

### Regel B — `services/metadata/`

`services/metadata/` ist eine kohärente Domain. `enhanced_metadata_processor.py`
wird korrekt als **einzige** öffentliche Facade konsumiert — repo-weite
Prüfung ergab **null** externe Direktimporte der Unterprozessoren
(`album_processor.py`, `artist_processor.py`, `auto_learn.py`,
`cover_processor.py`, `genre_processor.py`, `lyrics_processor.py`,
`tag_writer.py`, `title_cleaner.py`) außerhalb von `services/metadata/`
selbst und außerhalb der Testdateien. Keine neuen Cross-Domain-
Abhängigkeiten seit ARCH-010 entstanden.

Die ARCH-005-Reverse-Edge (`enhanced_metadata_processor.py` →
`download_artifact_cleanup.py::cleanup_single_download_artifact()`) ist
exakt unverändert — dieselbe eine Aufrufstelle, dieselbe bewusste Ausnahme.

### Regel C — `services/downloader/`

Intern sauber strukturiert, wie in ARCH-011 Phase 1 im Detail geprüft.
Keine neuen Schichtverletzungen seit ARCH-011 gefunden. Kein
Downloader-Code trägt Metadata- oder Client-Verantwortung — die einzige
Cross-Boundary-Abhängigkeit (`download/interfaces.py → services.metadata.models`)
ist unverändert und folgt der etablierten Zielrichtung.

### Regel D — `handlers/`

Repo-weite Prüfung `services/* → handlers/*`:

```text
services/downloader/download_result_reporter.py
    → from handlers.duplicate_handler import DuplicateEntry
```

**Einziger** Treffer im gesamten `services/`-Baum. Bereits bekannt (siehe
Abschnitt 6, Punkt 1), unverändert seit der letzten Prüfung. Keine weitere
`services/* → handlers/*`-Abhängigkeit gefunden. Kein `services/*` importiert
`telegram`/`ParseMode`/`CallbackQuery` direkt.

### Regel E — `utils/`

`utils/bot_restart_trigger.py` und `utils/navidrome_scan_trigger.py` sind
weiterhin korrekt als lokale Subprocess-/Shell-Runner ohne echte
Netzwerkkommunikation in `utils/` eingeordnet (Konvention seit
ARCH-009/POST-ARCH-009). `utils/filenamefixer.py` und `utils/genre_map.py`
enthalten zwar fachliche Regeln (Mapping-Logik), sind aber als
querschnittliche, von mehreren Services gemeinsam genutzte Bausteine
etabliert (`GenreMapper` wird sowohl von `services/metadata/genre_processor.py`
als auch — s. o. — direkt von `services/clients/lastfm_client.py` und
`services/clients/musicbrainz_client.py` verwendet). Keine neue
Fehlplatzierung gefunden; die bestehende Einordnung wird nicht in Frage
gestellt.

### Regel F — Dependency Injection

- `album_processor.py`: `mb_client` optional injizierbar, lazy
  Selbstkonstruktion (`MusicBrainzClient()`) falls nicht gesetzt. Wird in
  `enhanced_metadata_processor.py` **ohne** `mb_client` konstruiert (Zeile
  125–127) — die Fassade hat selbst einen eigenen, unabhängigen lazy
  `self._mb_client` (für `genre_processor`, per Methodenparameter injiziert),
  der aber **nie** an `AlbumProcessor` weitergereicht wird. Ergebnis: zwei
  unabhängige `MusicBrainzClient`-Instanzen (mit je eigenem TTL-Cache)
  können gleichzeitig in derselben `EnhancedMetadataProcessor`-Instanz
  existieren.
- `lyrics_processor.py`: `genius_client` ist Pflichtparameter, keine
  Fallback-Konstruktion — striktere DI als `album_processor.py`.
- **Bewertung:** Das optional-inject-mit-lazy-Fallback-Muster selbst ist
  **kein** Regelbruch — es ist ein bereits etabliertes, dokumentiertes
  Muster (`statistik_service.py`, Kommentar „ARCH-003, P-8-Muster":
  `self.api = navidrome_api if navidrome_api is not None else NavidromeAPI()`).
  Die Inkonsistenz zwischen `album_processor.py` (optional) und
  `lyrics_processor.py` (Pflicht) ist damit eine **lokale
  Konsistenzfrage**, kein Verstoß gegen eine etablierte Regel. Die
  doppelte `MusicBrainzClient`-Instanziierung ist real, aber ein reiner
  Ressourcen-/Cache-Effizienzpunkt ohne Korrektheitsrisiko — kein P0/P1.

---

## 5. Dependency-Graph (aktuell)

```text
handlers/
   │  (Telegram-Präsentation, MarkdownV2, Update/CallbackQuery)
   ▼
services/
   │
   ├── services/downloader/  ──►  services/metadata/        [Zielrichtung, ARCH-010 bestätigt]
   │        ▲                          │
   │        └──── ARCH-005 Reverse-Edge (1 Aufrufstelle, bewusste Ausnahme, unverändert)
   │
   ├── services/downloader/download_result_reporter.py ──► handlers/duplicate_handler.py
   │        [Schichtverletzung — bekannt, unverändert, siehe 6.1]
   │
   ├── services/metadata/ ──► services/clients/  (genius_client, lastfm_client, musicbrainz_client)
   │        [normal, aber: services/clients/lastfm_client.py + musicbrainz_client.py
   │         rufen selbst utils/genre_map.py (GenreMapper) auf — fachliche Logik
   │         in der Adapter-Schicht, siehe 7.1]
   │
   ├── services/statistik/ + statistik_service.py ──► services/clients/navidrome_api.py  [normal]
   │
   ├── services/downloader/spotify_downloader.py ──► direkte HTTP-Aufrufe (urllib) an
   │        open.spotify.com  [kein Client-Bypass, da nie ein spotify_client.py existierte —
   │         siehe 6.3]
   │
   └── services/metadata/cover_processor.py ──► direkte HTTP-Aufrufe (requests) an
            Cover Art Archive, Fanart.tv, Apple Music, Deezer, Last.fm
            [Last.fm-Teil dupliziert services/clients/lastfm_client.py — bekannt, siehe 6.2;
             die übrigen 4 Quellen haben keinen eigenen Client, kein Bypass]

services/clients/  ──►  (keine Abhängigkeiten zurück in services/downloader/ oder services/metadata/)
   [bestätigt: keine Gegenrichtung]
```

Seit ARCH-010 sind **keine neuen** Gegenabhängigkeiten entstanden. Alle
gefundenen Cross-Boundary-Fälle sind entweder bereits bekannt (Abschnitt 6)
oder neu, aber lokal begrenzt (Abschnitt 7).

---

## 6. Re-Verifikation bekannter Folgepunkte

### 6.1 `download_result_reporter.py` → `handlers/duplicate_handler.py`

**Existiert weiterhin, unverändert.** `DuplicateEntry` ist ein reines
`@dataclass` (keine eigene Telegram-Abhängigkeit), liegt aber in
`handlers/duplicate_handler.py`, das selbst `from telegram import Update, ...`
importiert — der Import zieht damit transitiv ein Telegram-gekoppeltes
Modul in `services/downloader/` hinein. Einziger Verwendungsort:
`build_duplicate_message()` (Zeile 104). Risiko einer Verschiebung: niedrig
(reine Datenklasse, kein Verhalten). Präzedenzfall: identisches Muster
bereits mehrfach in ARCH-010 gelöst (`DownloadResult`, `PlaylistResult`,
`MetadataResult` — jeweils reine Dataclasses an neutrale Stelle verschoben).

### 6.2 `cover_processor.py` → direkter Last.fm-Zugriff

**Existiert weiterhin, unverändert.** `CoverProcessor._fetch_lastfm()`
baut eigene Requests-Session, eigene URL (`_LASTFM_BASE`), eigene
Parameter — komplett unabhängig von `services/clients/lastfm_client.py`.
Die anderen 5 Cover-Quellen (Cover Art Archive, Fanart.tv ×2, Apple Music,
Deezer, YouTube-Thumbnail) haben keinen entsprechenden Client — dort liegt
keine Duplikation vor, nur bei Last.fm. Größerer Aufwand als 6.1: würde
eine neue Methode in `lastfm_client.py` erfordern (Bild-URL statt
Metadaten/Tags), da der bestehende Client nur `fetch_metadata()` anbietet.

### 6.3 `spotify_downloader.py` → direkte HTTP-Aufrufe

**Existiert weiterhin, unverändert.** Nutzt `urllib.request.urlopen()`
für Spotify Embed-/oEmbed-API (kein offizieller API-Key-Pfad, siehe
README „ohne Premium/API-Key kein direkter Spotify-Download möglich").
**Wichtige Präzisierung gegenüber der ursprünglichen Formulierung:** Es
existiert **kein** `services/clients/spotify_client.py`, der hier umgangen
würde — anders als bei 6.2 (wo ein echter Client existiert und ignoriert
wird) liegt hier schlicht **keine Adapter-Abstraktion** vor, keine
Duplikation. Architektonisch schwächerer Befund als 6.2.

### 6.4 DI-Inkonsistenz `album_processor.py` vs. `lyrics_processor.py`

Re-verifiziert in Abschnitt 4, Regel F. **Lokale Konsistenzfrage**, kein
Regelbruch — beide Muster (Pflicht-Injection und optional-mit-Fallback)
haben eigene Präzedenzfälle im Code. Reales, aber kleines Nebenprodukt:
doppelte `MusicBrainzClient`-Instanziierung pro `EnhancedMetadataProcessor`-
Lebenszyklus.

### 6.5 `services/library/`-Frage / verbleibende Top-Level-`utils/`

**Kein Befund.** Es gibt keine „fehlende" `services/library/`-Schicht —
Datei-/Verzeichnis-/Tag-Organisation liegt bewusst und konsistent in
`utils/filenamefixer.py`, dokumentiert als technischer Querschnitts-Helfer.
Kein Hinweis, dass dies fachlich in `services/` gehören müsste (keine
Multi-Consumer-Fan-out-Situation, kein Präzedenzfall aus ARCH-010/011, der
dafür sprechen würde).

### 6.6 `metadata/cache.py` vs. `utils/metadata_cache.py`

**Kein funktionaler Konflikt, nur Namensnähe.** `services/metadata/cache.py::MetadataCacheHandler`
wrappt `utils/metadata_cache.py::MetadataCache` per Dependency Injection
(`BaseMetadataCache`-Alias beim Import) — sauberes Decorator-Muster, keine
Duplikation. Bereits in ARCH-010 als reine Umbenennungs-Idee dokumentiert
(nicht als funktionaler Fehler). Bei einer künftigen Umbenennung: zusätzlich
gegen `services/downloader/download/cache_manager.py::CacheManager`
(ARCH-011, Abschnitt 5) abgleichen, um keine dritte Namensnähe zu erzeugen.

### 6.7 `services/downloader/download/models.py` (ARCH-011 P2)

Unverändert, ausdrücklich **nicht** priorisiert — wie in ARCH-011 Phase 1
festgelegt. Kein neuer Befund, keine Neubewertung in diesem Audit.

### 6.8 ARCH-005 Reverse-Edge

Unverändert, exakt dieselbe eine Aufrufstelle
(`enhanced_metadata_processor.py:1002` → `cleanup_single_download_artifact()`).
Bleibt eine bewusst dokumentierte Ausnahme, hier nicht neu bewertet.

---

## 7. Neue Befunde

### 7.1 Genre-Bestimmungslogik dupliziert zwischen `services/clients/` und `services/metadata/genre_processor.py`

**Der bedeutendste neue Befund dieses Audits.**

`services/clients/lastfm_client.py::fetch_metadata()` instanziiert einen
eigenen `GenreMapper()` (Zeile 41) und ruft `determine_genre()` selbst auf
(Zeile 130–134), um einen `"genre"`-Schlüssel im Rückgabe-Dict zu befüllen.
`services/metadata/genre_processor.py::_fetch_genre_from_lastfm()` (Zeile
606–644) verwendet diesen vorberechneten `"genre"`-Wert jedoch **nicht** als
Ergebnis — er wird nur als Tag-Fallback herangezogen, falls `tags` leer ist
(Zeile 628–636). Die eigentliche Genre-Entscheidung trifft
`genre_processor.py` erneut, selbst, über `self.prioritize_genres(tags, ...)`
mit einem eigenen, separat injizierten `GenreMapper`.

Dasselbe Muster bei `services/clients/musicbrainz_client.py` (Zeile 430,
436: `self.genre_mapper.determine_genre(...)`, über Singleton-Getter
`get_genre_mapper()` statt eigener Instanz) — auch hier nimmt
`genre_processor.py` (Zeile 573–589) den bereits von MusicBrainz
bestimmten Genre-*String* und führt ihn **noch einmal** durch
`self.genre_mapper.determine_genre()`.

**Konsequenz:**
1. Regel-A-Verstoß: fachliche Genre-Entscheidungslogik (CLAUDE.md §10, P0)
   liegt in `services/clients/` statt ausschließlich in
   `services/metadata/genre_processor.py`.
2. Doppelte Berechnung: Last.fm-Pfad berechnet ein Genre, das fast immer
   verworfen wird; MusicBrainz-Pfad durchläuft `determine_genre()` zweimal
   in Folge für dieselben Daten.
3. `lastfm_client.py` instanziiert zusätzlich einen **eigenen**
   `GenreMapper()` (nicht über Singleton, anders als bereits bei
   `musicbrainz_client.py` per Kommentar dokumentiert korrigiert — „GenreMapper
   und ArtistNormalizer werden nicht mehr selbst instanziiert" gilt dort,
   aber nicht für `lastfm_client.py`).

**Risikoeinschätzung:** Testabdeckung vorhanden (`tests/test_lastfm_client.py`,
`tests/test_genre_processor.py`), aber eine Änderung betrifft die
P0-geschützte Genre-Pipeline direkt — erfordert nach CLAUDE.md §6
("Characterization First") vor jeder Änderung eigene Characterization-Tests
für beide Pfade, da nicht auf den ersten Blick auszuschließen ist, dass ein
Randfall (z. B. der Tags-leer-aber-`raw_lfm_genre`-vorhanden-Fallback in
Zeile 631) auf das aktuell berechnete, dann verworfene Client-Genre
angewiesen ist. **Kein P0/P1 für sofortige Umsetzung**, aber der
architektonisch klarste "echte" Regel-A-Befund dieses Audits — empfohlen
als eigener, dedizierter Folge-Phase-Kandidat (P1 für eine *künftige*
ARCH-Phase, nicht für den unmittelbar nächsten Schritt, siehe Abschnitt 10).

### 7.2 Toter/ungenutzter Import: `import requests` in `enhanced_metadata_processor.py`

Zeile 6, kein einziger `requests.`-Aufruf im gesamten 1203-Zeilen-File.
Trivial, keine Architekturwirkung. P3 — nur der Vollständigkeit halber
erfasst, kein eigener Kandidat.

### 7.3 Toter/ungenutzter Import: `import subprocess` in `navidrome_api.py`

Zeile 8, keine `subprocess.`-Aufrufe im File. Trivial. P3 — kein eigener
Kandidat, aber bemerkenswert, da `navidrome_api.py` sonst als reiner
HTTP-Client (Regel A, Abschnitt 4) korrekt eingeordnet ist; der tote Import
deutet auf einen früheren, entfernten Code-Pfad hin (keine funktionale
Relevanz mehr).

Keine weiteren neuen Befunde mit konkretem Consumer-/Dependency-Beleg
gefunden. Insbesondere: keine versteckten zyklischen Abhängigkeiten, keine
übermäßig breit konsumierten Services (`EnhancedMetadataProcessor` ist
breit konsumiert, aber das ist die *gewollte* Facade-Rolle), keine weiteren
Service→Handler- oder Service→Telegram-Kopplungen außer der bekannten aus
6.1.

---

## 8. Priorisierung

| Kandidat | Problem | Ziel | Nutzen | Aufwand | Risiko | Priorität |
|---|---|---|---|---|---|---|
| `download_result_reporter.py` → `DuplicateEntry` | Schichtverletzung `services/ → handlers/` | `DuplicateEntry` an neutrale Stelle verschieben (analog `DownloadResult` u. a.) | mittel (schließt einzige verbliebene harte Schichtverletzung) | sehr klein (1 Dataclass, 1 Importzeile am Verwendungsort) | sehr niedrig | **P1** |
| Genre-Logik in `lastfm_client.py`/`musicbrainz_client.py` (7.1) | Regel-A-Verstoß + Doppelberechnung in P0-Domäne | Genre-Entscheidung ausschließlich in `genre_processor.py`, Clients liefern nur Rohdaten | hoch (räumt echte Fachlogik-Vermischung in geschützter Domäne auf) | mittel–hoch (2 Client-Dateien + genre_processor.py, Characterization-Tests zuerst nötig) | mittel (P0-Bereich, Randfälle möglich) | **P1** (für dedizierte Folge-Phase, nicht sofort) |
| `cover_processor.py` Last.fm-Duplikation (6.2) | Duplizierter externer Zugriff | Last.fm-Bildabruf über `lastfm_client.py` (neue Methode nötig) | mittel | mittel (Client-Erweiterung nötig) | niedrig–mittel | P2 |
| DI-Inkonsistenz `album_processor.py` (6.4) | Doppelte `MusicBrainzClient`-Instanz | Facade-`_mb_client` an `AlbumProcessor` injizieren | niedrig (reiner Effizienzgewinn) | klein | niedrig | P2 |
| `spotify_downloader.py` direkte HTTP-Aufrufe (6.3) | Kein Client-Wrapper, aber auch keine Duplikation | ggf. `spotify_embed_client.py` | niedrig (kein akutes Problem) | mittel | niedrig | P3 |
| `metadata/cache.py`-Umbenennung (6.6) | Namensnähe zu `utils/metadata_cache.py` und `download/cache_manager.py` | Umbenennung | niedrig | klein | niedrig | P3 |
| tote Imports (7.2, 7.3) | Kosmetisch | entfernen | sehr niedrig | trivial | keins | P3 |

### Warum `download_result_reporter.py` sinnvoller ist als die Genre-Client-Frage

Beide sind echte P1-Befunde, aber unterschiedlicher Natur:

- **Kleinster sinnvoller Schritt:** `DuplicateEntry` ist eine reine
  Datenklasse ohne Verhalten — die Verschiebung ändert nichts an der
  Laufzeitlogik, nur am Importpfad. Die Genre-Client-Frage berührt aktive
  Entscheidungslogik in der am stärksten geschützten Domäne des gesamten
  Projekts (CLAUDE.md: „Besonders geschützt: Metadata, Artist, Genre").
- **Vorhandener Präzedenzfall:** exakt dasselbe Muster (Dataclass aus
  gekoppeltem Modul an neutrale Stelle verschieben) wurde in ARCH-010
  bereits dreimal (`DownloadResult`, `PlaylistResult`, `MetadataResult`)
  demonstriert erfolgreich durchgeführt. Für die Genre-Client-Frage gibt es
  keinen vergleichbar direkten Präzedenzfall.
- **Keine gleichzeitige Verhaltensänderung:** Der `DuplicateEntry`-Umzug
  hat strukturell keinen Effekt auf die Duplicate-Detection-Logik selbst
  (P0-Bereich laut CLAUDE.md §15, aber hier nur der *Typ*, nicht die
  *Logik* betroffen). Eine Änderung an der Genre-Client-Logik hätte
  zwangsläufig das Potenzial, Randfall-Verhalten zu verändern und erfordert
  vorab eigene Characterization-Tests (CLAUDE.md §6) — das ist ein größerer,
  eigenständiger Auftrag, kein "kleiner nächster Schritt".
- **Testbarkeit:** Für `download_result_reporter.py` genügt eine einzelne,
  triviale Regressionsprüfung des Imports. Für die Genre-Client-Frage
  müssten mehrere bestehende Tests (`test_lastfm_client.py`,
  `test_genre_processor.py`, ggf. `test_musicbrainz_client.py`) sorgfältig
  gegen das *aktuelle* Verhalten abgesichert werden, bevor irgendetwas
  geändert wird.

---

## 9. Aktuelle Zielarchitektur — Momentaufnahme

```text
services/
├── clients/                         ✅ architektonisch sauber (reine Adapter),
│                                        ⚠️ mit einer Ausnahme (Genre-Logik in
│                                        lastfm_client.py/musicbrainz_client.py, 7.1)
│   ├── genius_client.py             ✅
│   ├── lastfm_client.py             🔴 Genre-Determination-Logik im Adapter
│   ├── musicbrainz_client.py        ⚠️ dieselbe Musterfrage, aber bereits
│   │                                    teilweise adressiert (Singleton statt
│   │                                    eigener Instanz)
│   └── navidrome_api.py             ✅ (bis auf toten `subprocess`-Import, 7.3)
│
├── downloader/                      ✅ architektonisch sauber (ARCH-010/011 bestätigt)
│   ├── download_result_reporter.py  🔴 Import aus handlers/duplicate_handler.py (6.1)
│   ├── (übrige 8 Dateien)           ✅
│   └── download/                    ✅ bestätigt interne Zerlegung (ARCH-011)
│
├── metadata/                        ✅ kohärente Domain, Facade korrekt genutzt
│   ├── enhanced_metadata_processor.py ✅ einzige öffentliche Eintrittsstelle
│   ├── cover_processor.py           ⚠️ direkter Last.fm-HTTP-Zugriff statt
│   │                                    lastfm_client.py (6.2, bekannt) —
│   │                                    bewusst als Folgepunkt akzeptiert,
│   │                                    kein neuer Fund
│   ├── album_processor.py           ⚠️ doppelte MusicBrainzClient-Instanz
│   │                                    möglich (6.4) — lokale Konsistenzfrage
│   └── (übrige 8 Dateien)           ✅
│
├── statistik/ + statistik_service.py ✅ architektonisch sauber, etablierte
│                                        DI-Konvention (ARCH-003 P-8)
│
└── ARCH-005 Reverse-Edge            ⚠️ bewusst akzeptierte, dokumentierte
    (metadata → downloader,             Ausnahme, unverändert
     1 Aufrufstelle)
```

**Legende:** ✅ sauber · ⚠️ bewusst akzeptierte/bereits bekannte Ausnahme ·
🔴 echter, noch offener Folgepunkt.

Von den 3 mit 🔴 markierten Punkten sind 2 bereits aus früheren Audits
bekannt (6.1, indirekt 6.2) und 1 ist neu (7.1). Keine 🔴-Markierung
betrifft eine strukturelle Top-Level-Frage — alle liegen auf Datei-/
Funktions-Ebene innerhalb bereits korrekt zugeordneter Bereiche.

---

## 10. Bewertung von ARCH-010/011

**Was wurde durch ARCH-010 tatsächlich verbessert?**
Die zuvor vermischte `services/downloader/utils/`-Struktur (2 Domänen,
17 Dateien, unklare Grenzen) existiert nicht mehr. `services/downloader/`
und `services/metadata/` sind seither über den gesamten Audit hinweg
**durchgängig sauber** gegen ihre jeweilige Zielrichtung geprüfbar — dieser
Audit fand in beiden Bereichen **keine** neuen Schichtverletzungen.

**Was wurde durch ARCH-011 bewusst NICHT verändert?**
`services/downloader/download/` — korrekt, wie dieser Audit bestätigt: kein
externer Konsument, keine Notwendigkeit für eine Migration.

**Welche ursprünglichen Architekturprobleme sind jetzt gelöst?**
Domänenvermischung Downloader/Metadata (ARCH-010), unklare Grenzen des
`download/`-Unterpakets (ARCH-011, Ergebnis: kein Problem). Die
Kernrichtung `Downloader → Metadata` ist repo-weit sauber durchgesetzt,
mit exakt einer dokumentierten, unveränderten Ausnahme (ARCH-005).

**Welche Probleme bestehen weiterhin?**
Die in Abschnitt 6 re-verifizierten historischen Folgepunkte (`handlers/`-
Import in `download_result_reporter.py`, Last.fm-Duplikation in
`cover_processor.py`, DI-Inkonsistenz, Namensfragen) sowie der neue Befund
7.1 (Genre-Logik in Client-Adaptern). Keiner davon ist ein struktureller
Blocker — alle sind lokal begrenzte, klar benannte Einzelpunkte.

**Ist die Zielarchitektur von `services/` jetzt grundsätzlich stabil?**
**Ja.** Es gibt keinen erkennbaren strukturellen Blocker mehr. Die
Top-Level-Aufteilung (`clients/`, `downloader/` inkl. `download/`,
`metadata/`, `statistik/`) entspricht durchgängig den etablierten Regeln.
Die verbleibenden Befunde sind Datei-/Methoden-Ebene, keine
Bereichs-/Grenzen-Fragen mehr. Es besteht **keine** Notwendigkeit für eine
weitere große Struktur-Migration wie ARCH-010.

---

## 11. Empfohlener nächster Schritt

```text
Kandidat:            download_result_reporter.py → DuplicateEntry
Datei(en):           services/downloader/download_result_reporter.py
                      handlers/duplicate_handler.py
Problem:              services/downloader/ importiert eine Dataclass aus
                      handlers/duplicate_handler.py — einzige verbliebene
                      services/*→handlers/*-Schichtverletzung im gesamten
                      services/-Baum.
Ziel:                 DuplicateEntry an eine neutrale, von beiden Seiten
                      importierbare Stelle verschieben (z. B. ein Dataclass-
                      Modul in services/downloader/, analog zum bereits in
                      ARCH-010 etablierten Muster für DownloadResult/
                      PlaylistResult/MetadataResult).
Warum jetzt:          Kleinster sinnvoller Schritt mit direktem
                      Präzedenzfall, keine Verhaltensänderung, schließt die
                      letzte offene Schichtgrenzen-Verletzung in services/.
Risiko:               sehr niedrig — reine Dataclass ohne eigene Logik,
                      1 Verwendungsstelle (build_duplicate_message()).
Erwarteter Nutzen:    services/ ist danach vollständig frei von
                      handlers/-Importen — vollständige Schichtreinheit
                      erreicht.
```

### Nicht jetzt

- Genre-Bestimmungslogik in `lastfm_client.py`/`musicbrainz_client.py`
  (7.1) — echter, aber größerer P0-Domänen-Befund; eigene, dedizierte
  Characterization-Phase nötig, kein sofortiger Schritt.
- Last.fm-Duplikation in `cover_processor.py` (6.2) — erfordert
  Client-Erweiterung, nicht nur Verschiebung.
- DI-Inkonsistenz `album_processor.py` (6.4) — reiner Effizienzpunkt,
  keine Dringlichkeit.
- `spotify_downloader.py` direkte HTTP-Aufrufe (6.3) — kein Duplikations-
  risiko, niedrigste Priorität aller Befunde.
- Namensfragen (`metadata/cache.py`, tote Imports 7.2/7.3) — kosmetisch,
  keine eigene Phase wert.

---

## 12. Entscheidungsgate

**POST-ARCH-010/011 SERVICES-AUDIT — ENTSCHEIDUNGSGATE ERREICHT**

1. **Aktueller Architekturstatus:** `services/` ist strukturell stabil.
   Keine offenen Top-Level-Grenzfragen. Alle etablierten Regeln aus
   ARCH-009/010/011 werden repo-weit eingehalten, mit exakt einer
   bewusst akzeptierten Ausnahme (ARCH-005) und einer Handvoll bekannter,
   lokal begrenzter Folgepunkte.
2. **Wichtigster verbleibender Befund:** Genre-Bestimmungslogik dupliziert
   zwischen `services/clients/` (lastfm_client.py, musicbrainz_client.py)
   und `services/metadata/genre_processor.py` (Abschnitt 7.1) — architektonisch
   der klarste Regel-A-Verstoß, aber zu groß/riskant für einen sofortigen
   Schritt.
3. **Empfohlener nächster Kandidat:** `download_result_reporter.py` →
   `DuplicateEntry` verschieben (Abschnitt 11) — kleinster sinnvoller
   Schritt, schließt die letzte `services/*→handlers/*`-Schichtverletzung.
4. **Alternativen:** Last.fm-Duplikation in `cover_processor.py` (P2,
   größerer Aufwand); Genre-Client-Frage (P1, aber für eigene Folge-Phase);
   DI-Effizienzpunkt in `album_processor.py` (P2, klein aber ohne
   Dringlichkeit).
5. **Bewusst zurückgestellte Punkte:** siehe „Nicht jetzt" (Abschnitt 11).

Keine Umsetzung ohne explizite Freigabe. Wartet auf Entscheidung.
