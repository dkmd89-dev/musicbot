# ARCH-021 Phase 1 — Genre-Client-Duplikation / Last.fm-Cover-Charakterisierung

**Datum:** 2026-08-25
**Typ:** Reine Characterization (keine Produktions-/Test-/Mapping-Änderungen)
**Hinweis zur Nummerierung:** Der ursprüngliche Auftragstext bezeichnete diese Phase als
"ARCH-019 Phase 1". `ARCH-019 Phase 1` existiert jedoch bereits (abgeschlossen, PR #46,
`docs/MusicBot_ARCH-019_Genre_Client_Logic_Characterization.md`, andere Fragestellung:
`determine_genre()`-Nutzung in den Clients). Diese neue, inhaltlich breitere Untersuchung
(inkl. Last.fm-Cover-Bezug) wurde zunächst irrtümlich als "ARCH-020 Phase 1" bezeichnet, ohne
vorher zu prüfen, ob diese Nummer bereits reserviert war. Sie war es: `docs/ARCH-020_Phase.md`
(Download-Pipeline-Characterization) existierte bereits vor dieser Session. Nach Klärung dieser
Kollision (siehe `docs/MusicBot_ARCH-020_Download_Pipeline_Characterization.md`) wurde diese
Datei auf ausdrücklichen Nutzerwunsch zu **ARCH-021 Phase 1** umbenannt.

---

## A. Ausgangsstand

`main` @ `659a6f7` (Merge PR #47, ARCH-018 Phase 2 — Duplicate-Detection-Kern-Extraktion).
Working Tree: keine eigenen Änderungen außer der neu erstellten `docs/POST-ARCH-018_...md`
(unversioniert) und dieser Datei. Nutzereigene Working-Tree-Dateien (`mapping/artist_genre.yaml`,
`mapping/artist_overrides.json`, 12 gelöschte `.info.json`) unverändert, zu keinem Zeitpunkt
berührt.

Baseline-Regression (identisch übernommen aus dem unmittelbar vorangegangenen
POST-ARCH-018-Audit, gleicher Codestand — kein erneuter Lauf nötig, da seither keine
Produktions-/Testdatei geändert wurde): **1114 passed, 15 bekannte Vorbestandsfehler.**

---

## B. Betroffene Dateien

| Datei | Verantwortung |
|---|---|
| `services/clients/lastfm_client.py` (149 Zeilen) | `LastFMClient.fetch_metadata()`: holt via `pylast` Artist-/Track-Tags von Last.fm für die **Genre-Bestimmung**. Reiner API-Adapter, keine Genre-Fachlogik (siehe unten). |
| `services/clients/musicbrainz_client.py` (471 Zeilen) | `MusicBrainzClient.fetch_metadata()`: holt Recording/Release/Tags von MusicBrainz für Genre, Album, Jahr, IDs. Reiner API-Adapter, keine Genre-Fachlogik. |
| `services/metadata/cover_processor.py` (955 Zeilen) | `CoverProcessor.get_cover_art()`: Multi-Source-Cover-Beschaffung (10 Quellen inkl. `_fetch_lastfm()`) für **Cover-Art**, nicht für Genre. |
| `services/metadata/genre_processor.py` | `GenreProcessor.determine_genre_with_fallbacks()` / `prioritize_genres()`: alleinige fachliche Entscheidungsinstanz für Genre, konsumiert rohe Tags von MB- und LFM-Client. |
| `services/metadata/enhanced_metadata_processor.py` | Orchestrator: instanziiert und ruft sowohl die Genre-Clients als auch `CoverProcessor` innerhalb derselben Track-Verarbeitung auf. |

---

## C. Produktive Aufrufer

**`LastFMClient` (Genre-Pfad):**
- Instanziiert einmalig (lazy) in `enhanced_metadata_processor.py:1035` (`self._lfm_client = LastFMClient()`).
- Aufgerufen ausschließlich über `GenreProcessor._fetch_genre_from_lastfm()` (`genre_processor.py:666`), die wiederum nur von `determine_genre_with_fallbacks()` (`genre_processor.py:179`) aufgerufen wird.
- Kein anderer produktiver Aufrufer im Repo (repo-weit per Grep verifiziert).

**`MusicBrainzClient` (Genre-/Album-Pfad):**
- Instanziiert einmalig (lazy) in `enhanced_metadata_processor.py:1030`.
- Genutzt sowohl von `GenreProcessor._fetch_genre_from_musicbrainz()` als auch von `AlbumProcessor.fetch_album_from_musicbrainz()` (`_fetch_album_info_from_musicbrainz()`, `enhanced_metadata_processor.py:1056`) — zwei unterschiedliche fachliche Konsumenten desselben Clients, aber jeweils reiner Konsum der zurückgelieferten Rohdaten, keine Duplikation innerhalb des Clients selbst.

**`CoverProcessor` (Cover-Pfad):**
- Einzige produktive Instanziierung: `enhanced_metadata_processor.py:112-115`.
  ```python
  self.cover_processor = CoverProcessor(
      fanart_api_key=_fanart_key or None,
      logger=self.logger_factory("CoverProcessor"),
  )
  ```
  **`lastfm_api_key` wird hier nicht übergeben** — Default bleibt `None`.
- Aufgerufen über `self.cover_processor.get_cover_art(...)` (`enhanced_metadata_processor.py:695`).

Tests instanziieren `CoverProcessor` teils mit `lastfm_api_key="fake-key"`
(`tests/test_cover_processor_validation.py:131`), das ist jedoch ausschließlich zum Testen der
Early-Exit-Orchestrierung (`assert_not_called()`-Prüfung), nicht zum Beweis eines produktiven
Aufrufpfads.

---

## D. Duplikationsmatrix

| Bereich | Implementierung A | Implementierung B | Gleichheit | Produktive Nutzung |
|---|---|---|---|---|
| Last.fm-API-Zugriff | `services/clients/lastfm_client.py::LastFMClient._get_lastfm_data()` — `pylast`-Library, `network.get_artist()`/`get_track()`, holt **Tags** (`get_top_tags()`) | `services/metadata/cover_processor.py::CoverProcessor._fetch_lastfm()` — rohes `requests.get()` gegen `ws.audioscrobbler.com/2.0`, Methode `artist.getinfo`, holt **Bild-URL** aus `artist.image[]` | **Bewusst unterschiedliche Logik.** Unterschiedliche HTTP-Mechanik (pylast-Objektwrapper vs. rohe REST-Response), unterschiedlicher Endpunkt (`get_top_tags` vs. `artist.getinfo`), unterschiedlicher Rückgabetyp (Tag-Liste vs. Bild-Bytes), unterschiedlicher fachlicher Zweck (Genre-Input vs. Cover-Kandidat) | `LastFMClient`: aktiv (Genre-Pipeline). `CoverProcessor._fetch_lastfm()`: **in Produktion unerreichbar** (siehe G) |
| Genre-Verdichtung MusicBrainz | `services/clients/musicbrainz_client.py` — liefert nur rohe `tags` (`release_group.get("tags", [])`), `"genre": "unknown"`-Platzhalter | `services/metadata/genre_processor.py::_fetch_genre_from_musicbrainz()` → `prioritize_genres()` | Keine Duplikation — bereits durch ARCH-012 Phase 3B aufgelöst, hier nur re-verifiziert | Client: Transport, Processor: alleinige Entscheidung |
| Genre-Verdichtung Last.fm | `services/clients/lastfm_client.py` — liefert nur rohe `tags`, `"genre": "unknown"`-Platzhalter | `services/metadata/genre_processor.py::_fetch_genre_from_lastfm()` → `prioritize_genres()` | Keine Duplikation — bereits durch ARCH-012 Phase 2 aufgelöst, hier nur re-verifiziert (identisch zum ARCH-019-Phase-1-Befund) | Client: Transport, Processor: alleinige Entscheidung |

**Kernaussage:** Es gibt **keine doppelte Genre-Fachlogik** zwischen den Clients und
`GenreProcessor` (bereits durch ARCH-012 und ARCH-019 Phase 1 belegt, hier erneut bestätigt).
Die als "Last.fm-Duplikation" bezeichnete Überschneidung zwischen `lastfm_client.py` und
`cover_processor.py` ist bei genauer Prüfung **keine fachliche Duplikation**, sondern zwei
unabhängige Integrationen derselben Drittanbieter-API für vollständig unterschiedliche Zwecke
(Genre-Tags vs. Cover-Bild).

---

## E. Laufzeit-Datenfluss

Beide Pfade laufen innerhalb derselben Track-Verarbeitung in
`EnhancedMetadataProcessor` (Reihenfolge im Code, nicht zwingend identisch mit
Ausführungsreihenfolge zur Laufzeit, aber beide Teil desselben Aufrufs):

```
enhanced_metadata_processor.py (Haupt-Track-Pipeline)
      │
      ├─ Zeile ~508: self._determine_genre_with_stats(...)
      │        └─ genre_processor.determine_genre_with_fallbacks(
      │               mb_client=self._mb_client, lfm_client=self._lfm_client)
      │               ├─ _fetch_genre_from_musicbrainz() → MusicBrainzClient.fetch_metadata()
      │               │      → musicbrainzngs.search_recordings/get_recording_by_id
      │               │      → rohe "tags" zurück
      │               └─ _fetch_genre_from_lastfm() → LastFMClient.fetch_metadata()
      │                      → pylast network.get_artist()/get_track()/get_top_tags()
      │                      → rohe "tags" zurück
      │               beide Tag-Listen → prioritize_genres() → GenreResult (fachliche Entscheidung)
      │
      └─ Zeile ~695: self.cover_processor.get_cover_art(...)
               └─ _build_priority_task_list() reiht u.a. _fetch_lastfm auf,
                  ABER NUR "if self.lastfm_api_key and artist_name" (Zeile 545)
                  → self.lastfm_api_key ist in Produktion IMMER None
                    (Konstruktor-Aufruf ohne lastfm_api_key, s. C)
                  → Last.fm wird in der produktiven Cover-Pipeline NIE als Quelle
                    aufgerufen; aktiv genutzte Quellen: coverartarchive, fanart_album,
                    fanart_artist, apple_music, deezer, youtube (4 Varianten)
```

**Bei einem realen Track-Download läuft für Genre tatsächlich:**
`MusicBrainzClient.fetch_metadata()` **und** `LastFMClient.fetch_metadata()` (beide, als
parallele Quellen für `prioritize_genres()`).

**Bei einem realen Track-Download läuft für Cover-Art tatsächlich:**
`CoverProcessor._fetch_lastfm()` wird aufgrund des fehlenden API-Keys **nie erreicht** — die
Last.fm-Cover-Quelle ist strukturell abgeschaltet, obwohl der Code vollständig vorhanden und
funktionsfähig aussieht.

ARCH-017 berücksichtigt: `utils/audio_enhancer.py` ist an diesem Datenfluss nicht beteiligt
(reine Loudness-Normalisierung nach Audio-Erstellung, kein Netzwerkbezug seit ARCH-017 Phase 2) —
nicht erneut als Netzwerkmodul fehlklassifiziert.

---

## F. Architekturstatus

AST-basierter Scan über `services/`, `handlers/`, `klassen/`, `utils/`, `helfer/`, `mapping/`
(identischer Stand wie POST-ARCH-018-Audit, keine Veränderung seither):

```
services → handlers:  0 Treffer
services → klassen:   0 Treffer
klassen → handlers:   0 Treffer  (durch ARCH-018 beseitigt, weiterhin bestätigt)
```

- `services/clients/*`, `services/metadata/genre_processor.py`,
  `services/metadata/cover_processor.py`: **0 Telegram-Importe** (Grep auf `telegram`, `Update`,
  `ContextTypes`, `InlineKeyboard` — keine Treffer).
- `services/clients/*` bleiben reine externe Integrationsadapter — keine fachlichen
  Genre-Entscheidungen, keine Präsentationslogik.
- Einzige direkte Client-Nutzung durch einen Handler: `handlers/navidrome_menu_handler.py`
  importiert `services.clients.navidrome_api.NavidromeAPI` direkt. Dies ist ein
  **vorbestehendes, von ARCH-021 nicht berührtes Muster** (Navidrome-Suche im Menü ist ein reiner
  Pass-Through-Anwendungsfall) — hier nur zur Vollständigkeit erwähnt, nicht neu bewertet und
  nicht Teil dieser Untersuchung.
- Keine neuen Importzyklen.
- Mögliches Konsolidierungsziel für eine künftige Cover-Last.fm-Anbindung (falls gewünscht):
  `services/clients/lastfm_client.py::LastFMClient` besitzt bereits eine initialisierte
  `pylast.LastFMNetwork`-Instanz — technisch denkbar, dass ein künftiger
  `LastFMClient.fetch_artist_image()` diese wiederverwenden könnte, statt dass
  `cover_processor.py` einen zweiten, unabhängigen Last.fm-HTTP-Zugriff pflegt. Dies ist eine
  rein analytische Beobachtung, keine Empfehlung (siehe I).

---

## G. Tote oder ungenutzte Logik

**`CoverProcessor._fetch_lastfm()` ist in Produktion faktisch tot / unerreichbar:**

- Repo-weit einzige produktive `CoverProcessor`-Instanziierung
  (`enhanced_metadata_processor.py:112`) übergibt keinen `lastfm_api_key`.
- `Config.LASTFM_API_KEY` existiert (`config.py:181`) und wird für `LastFMClient` (Genre-Pfad)
  korrekt aus der Umgebung gelesen — aber nirgends an `CoverProcessor` weitergereicht.
- `_fetch_lastfm()` selbst (Zeile 802-834) ist vollständig implementiert und funktionsfähig
  (Cache-Handling, Score-Integration über `_validate_and_score("lastfm", ...)`), aber der
  Guard `if not self.lastfm_api_key: return None` (Zeile 804-805) sowie der vorgelagerte
  Task-Filter `if self.lastfm_api_key and artist_name` (Zeile 545) verhindern jeden produktiven
  Aufruf.
- Dies ist **kein Bug im Sinne einer falschen Berechnung**, sondern eine fehlende
  Konfigurationsweiterleitung — die Last.fm-Cover-Quelle ist damit strukturell abgeschaltet, ohne
  dass dies im Code sichtbar dokumentiert wäre (kein Kommentar, kein Log-Hinweis über den
  Standard-Debug-Log "Last.fm übersprungen: kein API-Key" hinaus, der nur bei explizitem
  Debug-Logging sichtbar wird).
- Nicht behoben im Rahmen dieser Phase (reine Characterization).

---

## H. Charakterisierte Risiken

| Risiko | Bewertung |
|---|---|
| Doppelte fachliche Regeln | **Nicht vorhanden.** Beide Last.fm-Zugriffe verfolgen unterschiedliche fachliche Ziele (Tags vs. Bild), keine widersprüchliche oder doppelte Entscheidungslogik. |
| Divergierende Ergebnisse | Nicht anwendbar — es gibt keine zwei Implementierungen, die dasselbe fachliche Ergebnis (Genre) berechnen. |
| Wartungsrisiko | Gering bis moderat: zwei unabhängige Last.fm-HTTP-Integrationen (pylast vs. raw requests) bedeuten zwei Stellen, die bei einer Last.fm-API-Änderung angepasst werden müssten. Kein akutes Risiko, aber ein potenzieller Konsolidierungskandidat bei zukünftiger Last.fm-Arbeit. |
| Unnötige API-Aufrufe | Keine — der tote `CoverProcessor._fetch_lastfm()`-Pfad wird nie aufgerufen, verursacht also keine unnötigen Requests. Umgekehrtes Risiko: eine **potenziell nutzbare, aber ungenutzte Cover-Quelle** bleibt inaktiv (Quality-of-Life-Verlust, kein Korrektheitsrisiko). |
| Versteckte Abhängigkeiten | Keine gefunden — beide Pfade sind über Dependency Injection (Konstruktor-Parameter) sauber entkoppelt, das Fehlen ist eine reine Verdrahtungslücke, kein verstecktes Koppeln. |
| Migrationsrisiko | Keines für den aktuellen Zustand (reine Analyse, keine Änderung). Bei einer künftigen Behebung der Config-Lücke (Übergabe von `Config.LASTFM_API_KEY` an `CoverProcessor`) bestünde ein geringes Risiko einer Verhaltensänderung (neue, aktive externe Quelle) — das wäre dann jedoch eine bewusste fachliche Entscheidung, kein Refactoring-Nebeneffekt. |

---

## I. Lösungsvarianten (rein analytisch, keine Umsetzung)

1. **Duplikation bewusst belassen** — da keine echte fachliche Duplikation vorliegt (Abschnitt D),
   ist "Konsolidieren" hier kein Duplikations-, sondern höchstens ein
   HTTP-Client-Wiederverwendungs-Thema. Kein Handlungsdruck.
2. **`Config.LASTFM_API_KEY` an `CoverProcessor` weiterreichen** — würde die tote
   `_fetch_lastfm()`-Quelle in Produktion aktivieren. Reine Konfigurationsänderung
   (`enhanced_metadata_processor.py:112`), keine Logikänderung. Fachliche Entscheidung nötig
   (ist eine zusätzliche externe Cover-Quelle mit Score 80 gewünscht?), keine rein technische.
3. **Tote `_fetch_lastfm()`-Implementierung entfernen** — falls die Last.fm-Cover-Quelle bewusst
   nicht gewünscht ist, könnte der volle Codepfad (Zeilen 544-550, 802-834, `_BASE_SCORES["lastfm"]`,
   `_LASTFM_BASE`) als toter Code entfernt werden (analog ARCH-017-Muster). Erfordert vorherige
   ausdrückliche Entscheidung, ob die Quelle gewünscht ist oder nicht — nicht rein technisch
   ableitbar.
4. **`pylast`-Instanz aus `LastFMClient` für Cover-Bildabruf wiederverwenden** — würde die
   HTTP-Zugriffslogik konsolidieren (ein Last.fm-Client statt zwei), ist aber ein echter
   Architektur-Umbau (Cross-Cutting zwischen `services/clients/` und
   `services/metadata/cover_processor.py`) und keine triviale Änderung.

Keine dieser Varianten wurde umgesetzt.

---

## J. Empfehlung

**ERGEBNIS C — kein sinnvoller Handlungsbedarf im Sinne einer Duplikations-Bereinigung.**

Die ursprünglich vermutete "Last.fm-Duplikation" zwischen `lastfm_client.py` und
`cover_processor.py` ist bei Prüfung **keine Duplikation**, sondern zwei fachlich unabhängige,
korrekt getrennte Integrationen (Genre-Tags vs. Cover-Bild). Die MusicBrainz-/Last.fm-Client-
Genre-Logik-Frage war bereits durch ARCH-019 Phase 1 abschließend geklärt (kein
`determine_genre()`-Aufruf mehr in den Clients) und wird hier nur bestätigt, nicht neu entschieden.

**Der einzige neue, konkrete Befund** ist die in Abschnitt G beschriebene tote
`CoverProcessor._fetch_lastfm()`-Quelle aufgrund fehlender Config-Weiterleitung. Dies ist jedoch
kein Duplikations-, sondern ein separates, isoliertes Konfigurationsthema — für dieses gilt:
weder ERGEBNIS A (klare Regel sofort ableitbar — es fehlt die fachliche Vorentscheidung, ob die
Quelle aktiviert werden soll) noch ERGEBNIS B im ursprünglich adressierten Duplikations-Sinn.
Es wird als eigenständiger, dokumentierter P2/P3-Folgepunkt festgehalten, nicht als Grund für eine
automatische ARCH-021 Phase 2.

---

## K. Regression

Kein Produktions-, Test- oder Mapping-Code wurde in dieser Phase geändert. Der zuletzt im
POST-ARCH-018-Audit auf identischem Codestand (`main` @ `659a6f7`) erfasste Teststand bleibt
gültig: **1114 passed, 15 bekannte Vorbestandsfehler**, unverändert.

---

## L. Diff-/Scope-Audit

```
git diff --stat  →  (keine Treffer außer dieser neuen Doku-Datei und der
                     unversionierten docs/POST-ARCH-018_...md aus dem
                     vorangegangenen Audit)
```

- Produktionsänderungen: **0**
- YAML-/Mapping-Änderungen: **0**
- Teständerungen: **0**
- Neue Dependency-Edges: **0** (AST-Scan identisch zu POST-ARCH-018)
- Nutzereigene Working-Tree-Dateien: unverändert, nicht berührt

---

## M. Entscheidungsgate

**STOPP.** Keine ARCH-021 Phase 2 automatisch starten. Der einzige neue Befund (tote
`CoverProcessor`-Last.fm-Quelle, Abschnitt G/J) erfordert zunächst eine fachliche
Vorentscheidung des Nutzers (Quelle aktivieren, entfernen oder belassen), bevor eine
Umsetzungsphase sinnvoll wäre. Wartet auf ausdrückliche Nutzerentscheidung.

## Nachtrag (2026-08-25): Entscheidung getroffen — tote Quelle entfernt

Nutzerentscheidung (im Rahmen der Freigabe für Baseline-v2-Punkt
LASTFM-COVER-DEAD, siehe `docs/MusicBot_ENGINEERING_BASELINE_v2.md`):
**entfernen**, nicht aktivieren. `CoverProcessor._fetch_lastfm()`, der
zugehörige Task-Eintrag in `_build_priority_task_list()`, der
`lastfm_api_key`-Konstruktorparameter, die `_LASTFM_BASE`-Konstante sowie der
`"lastfm"`-Eintrag in `_BASE_SCORES` wurden entfernt (`services/metadata/cover_processor.py`).

`services/clients/lastfm_client.py` (`LastFMClient`, Genre-Pipeline) ist davon
**nicht** betroffen — bleibt vollständig aktiv, wie in Abschnitt G dieses
Dokuments bereits als unabhängige, aktive Komponente charakterisiert. Diese
historische Characterization oben bleibt inhaltlich unverändert stehen; sie
beschreibt korrekt den Zustand vor dieser Entscheidung.
