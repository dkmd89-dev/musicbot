# Architecture Refactoring Audit — Migrationsplan: NavidromeMenuHandler

**Status:** Ursprünglich READ-ONLY AUDIT-ERGEBNIS. **Stufe 1 wurde vom
Nutzer freigegeben und ist seit 2026-09-13 IMPLEMENTED** (siehe
Nachtrag am Ende von Abschnitt 5). Stufen 2–5 bleiben weiterhin reine
Planung, nicht freigegeben, nicht umgesetzt.

**Scope:** `handlers/navidrome_menu_handler.py` (1454 Zeilen Methodencode,
19 Methoden), `handlers/menu/actions/navidrome.py` (258 Zeilen, dünner
Dispatcher), `handlers/menu/rich_menu_system.py` (`nav_`-Routing-Teil),
`handlers/menu/rich_menu_handler.py` (Konstruktion + Freitext-Routing).

**Verbindlicher Kontext:** `docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md`
Abschnitte 1/5/6/8 (Zielarchitektur, Anti-Overengineering-Regel). Alle
NAV-F1–NAV-F13-Findings bleiben unverändert CLOSED — dieser Plan ändert
daran nichts.

---

## 1. Executive Summary

`NavidromeMenuHandler` ist eine 1454-Zeilen-God-Class: jede der 13
Browse-/Detail-/Such-Methoden mischt API-Aufruf, Pagination-/
Filter-Logik, MarkdownV2-Rendering und Error-Handling in sich selbst.
Das ist bereits in Abschnitt 1 des Architekturdokuments als „HIGH
COUPLING" dokumentiert; dieser Plan liefert die dort fehlende
Migrationsreihenfolge.

**Kernbefund des Audits:** die von der Zieldoku für zuerst vorgesehenen
Browse-Methoden (`handle_browse_artists/_albums/_genres`) sind
genau die mit der **schlechtesten** Testabdeckung (0 direkte
Erfolgspfad-Tests, teils verzweigte Pagination-Logik). Die drei
Detail-Methoden (`handle_album_detail`/`handle_song_detail`/
`handle_playlist_detail`) folgen dagegen einem identischen, reinen
Muster (Dict → Keyboard → MarkdownV2-Text) und sind überwiegend gut
getestet — mit einer Ausnahme (siehe unten).

**Empfohlene erste Stufe:** reine **Rendering-Extraktion** (kein
API-Call!) der drei Detail-Methoden in ein neues, schlankes
`handlers/navidrome_renderer.py` — mit `handle_playlist_detail` zuerst
per Characterization-Tests abgesichert, bevor extrahiert wird (siehe
Abschnitt 5). Das ist eine Abweichung von der in Abschnitt 5 der
Zieldoku suggerierten Reihenfolge (die dort browser_service zuerst
nennt), aber ausdrücklich im Rahmen der Vorgabe „Zieldoku ist
Leitplanke, nicht Reihenfolge-Vorgabe" (Auftrag Abschnitt 3).

---

## 2. Audit-Tabelle pro Methode

Alle Zeilenangaben beziehen sich auf den Stand von
`handlers/navidrome_menu_handler.py` zum Zeitpunkt dieses Audits
(2026-09-13, nach NAV-F1–NAV-F13).

| Methode | Zeilen | LOC | Aufrufer | Verantwortlichkeit | `browse_states`? | Tests | Rendering-Anteil | API-Anteil |
|---|---|---|---|---|---|---|---|---|
| `__init__` | 40–70 | 31 | `RichMenuHandler` (1×, Konstruktion) | DI-Setup, State-Init | schreibt (Init) | indirekt (jeder Test) | 0% | 0% |
| `_initialize_api` | 71–98 | 28 | intern: `__init__`, `handle_reconnect` | Config-Präsenzprüfung (kein Netzwerk) | – | `TestInitializeApiBug007aConnectionStatus` (dediziert) | 0% | 0% |
| `handle_browse_artists` | 99–190 | 92 | `actions/navidrome.py` (2× — Wrapper + `nav_browse_artists`-Präfixzweig) | API-Call (`get_artists`), lokale Pagination, 2-Spalten-Keyboard, MarkdownV2-Text | – | 1 echter Erfolgspfad-Test (nur Button-Format), 2 Error-Pfad-Tests | ~55% | ~10% |
| `handle_browse_albums` | 191–326 | **136** (größte Browse-Methode) | `actions/navidrome.py` (2×) | 2 unterschiedliche API-Pfade (`getArtist` vs. `getAlbumList2`) je nach `artist_id`, Pagination, Keyboard, Text | – | **0 direkte Tests** | ~45% | ~15% |
| `handle_browse_genres` | 327–452 | 126 | `actions/navidrome.py` (2×) | API-Call (`getGenres`), Sortierung (songCount, Fallback alphabetisch), Aggregation (`total_songs`/`avg_songs`), Keyboard, Text | – | **0 direkte Tests** (nur indirekt via NAV-F2-Dispatcher-Tests, die `handle_genre_detail` mocken) | ~40% | ~10% |
| `handle_genre_detail` | 453–561 | 109 | `actions/navidrome.py` (`nav_genre_`-Präfixzweig, 1×) | API-Call (`getSongsByGenre`), Set-Aggregation (Künstler/Alben), Keyboard, `escape_md_v2()`-Text | – | 3 Tests (Escaping, leere Liste, **NAV-F13-Regression**) | ~45% | ~10% |
| `handle_artist_detail` | 562–675 | 114 | `actions/navidrome.py` (`nav_artist_`-Präfixzweig, 1×) | API-Call (`getArtist`), Album-Keyboard (Top 15 + „weitere"-Button, NAV-F11-relevant), `escape_md_v2()`-Text | – | 2 Tests (Escaping) | ~45% | ~10% |
| `_format_track_duration` | 676–690 | 15 | intern: 3× (Album-/Song-/Playlist-Detail) | reine Formatierungsfunktion (`@staticmethod`), kein State | – | `TestFormatTrackDuration` (dediziert) | 100% | 0% |
| `handle_album_detail` | 691–794 | 104 | `actions/navidrome.py` (`nav_album_`-Präfixzweig, 1×) | API-Call (`getAlbum`), Tracklist-Keyboard (25 Songs gedeckelt), `escape_md_v2()`-Text | – | **4 Tests** (Erfolg, Escaping, Not-Found, Connection-Error) — beste Coverage der Datei | ~50% | ~10% |
| `handle_song_detail` | 795–877 | 83 | `actions/navidrome.py` (`nav_song_`-Präfixzweig, 1×) | API-Call (`getSong`), Action-Row (Künstler/Album-Link), `escape_md_v2()`-Text | – | 3 Tests (analog Album) | ~50% | ~10% |
| `handle_my_playlists` | 878–943 | 66 | `actions/navidrome.py` (2×) | API-Call (`getPlaylists`), Keyboard (Top 20), statischer Text (keine dyn. Namen im Body) | – | **0 direkte Tests** | ~50% | ~10% |
| `handle_playlist_detail` | 944–1036 | 93 | `actions/navidrome.py` (`nav_playlist_`-Präfixzweig, 1×, NAV-F5) | API-Call (`getPlaylist`), Tracklist-Keyboard, `escape_md_v2()`-Text | – | **0 direkte Unit-Tests** (nur 1 Dispatcher-Test, der die Methode mockt statt ausführt) | ~50% | ~10% |
| `handle_favorites` | 1037–1123 | 87 | `actions/navidrome.py` (2×) | API-Call (`getStarred2`), 3 getrennte Keyboard-Abschnitte (Artist/Album/Song), statischer Text | – | **0 direkte Tests** | ~55% | ~10% |
| `handle_search` | 1124–1172 | 49 | `actions/navidrome.py` (9× über 5 Wrapper + Dispatcher-Zweige) | reiner `browse_states`-Setter + statischer Prompt-Text, **kein API-Call** | **schreibt** | 0 direkte Tests (nur über gemockte Dispatcher-Tests) | ~60% | 0% |
| `process_search_query` | 1173–1313 | **141** (größte Methode) | `RichMenuHandler` (1×, **außerhalb** des `nav_`-Dispatcher-Pfads — siehe Abschnitt 3) | liest/schreibt `browse_states`, verzweigt zu `_process_genre_search_query`, sonst generischer `search3`-Pfad mit 3 Ergebnisabschnitten | **liest+schreibt** | 4 Tests (Error-Handler-Integration ×2, NAV-F7-Genre-Zweig ×2) | ~35% | ~10% |
| `_process_genre_search_query` | 1314–1404 | 91 | intern: `process_search_query` (1×, bei `search_type=="genres"`) | API-Call (`getGenres`), Teilstring-Filter, Keyboard, `escape_md_v2()`-Text | liest `browse_states`-Ergebnis indirekt (Parameter, kein direkter Zugriff) | 4 Tests (`TestGenreSearchQueryNavF7`) | ~45% | ~10% |
| `_check_connection` | 1405–1408 | 4 | intern: 8× (alle Browse-/Detail-Methoden außer Search-Pfad) | reine Bool-Prüfung (`self.connection_status`) | – | indirekt (jeder Connection-Error-Test) | 0% | 0% |
| `_show_connection_error` | 1409–1438 | 30 | intern: 8× (im Paar mit `_check_connection`) + `handle_reconnect` (Fehlerfall) | 100% statisches Rendering (kein dynamischer Inhalt) | – | indirekt, kein isolierter Test | 100% | 0% |
| `handle_reconnect` | 1439–1493 | 55 | `actions/navidrome.py` (`nav_reconnect`, 1×) | `_initialize_api()` + echter `NavidromeAPI.check_connection()`-Netzwerkcall (NAV-F6) + Rendering | – | 4+ Tests (NAV-F6, gut abgedeckt) | ~30% | ~25% |

**Summe Methodencode:** 1454 Zeilen (Datei insgesamt 1493 Zeilen inkl.
Modul-Docstring/Imports).

### Projektweite Zusatzprüfungen

- **Toter Code:** keiner gefunden. Jede der 19 Methoden hat mindestens
  einen echten Aufrufer über `handlers/menu/actions/navidrome.py` oder
  intern. (Der einzige historisch tote Pfad, `handle_stats()`, wurde
  bereits in NAV-F3 entfernt.)
- **Aufrufe außerhalb des dokumentierten `nav_`-Routing-Pfads:**
  **eine gefunden.** `process_search_query()` wird nicht über den
  `nav_`-Callback-Dispatcher erreicht, sondern über den generischen
  Freitext-Nachrichten-Handler in `handlers/menu/rich_menu_handler.py`
  (`RichMenuHandler`, eine andere Klasse als der in Abschnitt 1 der
  Zieldoku beschriebene `RichMenuSystem`-Dispatcher). Diese Klasse
  greift **direkt** auf `self.navidrome_handler.browse_states[user_id]
  ["waiting_for_search"]` zu (Zeile ~1126 in `rich_menu_handler.py`),
  um zu entscheiden, ob eine eingehende Nachricht an
  `process_search_query()` weitergereicht wird. Das ist architektonisch
  notwendig (Telegram-Callback-Buttons können keine Freitext-Antwort
  empfangen), aber im Architekturdokument (Abschnitt 1, Routing-Diagramm)
  nicht abgebildet und stellt einen echten Fremdzugriff auf
  Handler-internen State dar (siehe Abschnitt 3).
- **Geteilte Helfer:** `_check_connection()`/`_show_connection_error()`
  (Paar, 8 interne Aufrufer), `_format_track_duration()` (3 interne
  Aufrufer), `escape_md_v2()`/`md_bold()`/`md_code()` (aus
  `helfer/markdown_helfer.py`, bereits eine eigene, saubere Schicht —
  keine Änderung nötig).
- **Bereits etabliertes Extraktions-Präzedenzmuster im selben Ordner:**
  `handlers/menu/actions/_common.py` enthält bereits einen „kleinen,
  zustandslosen, geteilten Helfer" (`show_handler_not_available()`),
  der nach exakt demselben Muster (reine Funktion, kein State) aus
  `RichMenuSystem` extrahiert wurde (ARCH-024/P-2). Das bestätigt, dass
  eine reine Rendering-/Helfer-Extraktion in diesem Projekt bereits
  ein bewährtes, risikoarmes Muster ist.

---

## 3. Geteilter State

| State | Ort | Schreibt | Liest | Reichweite |
|---|---|---|---|---|
| `self.browse_states: Dict[int, Dict]` | `NavidromeMenuHandler.__init__` | `handle_search()`, `process_search_query()` | `process_search_query()`, **und extern:** `RichMenuHandler.<Freitext-Handler>` (direkter Dict-Zugriff, nicht über eine Methode!) | Nur 2 von 19 Methoden dieser Klasse, aber **1 externe Klasse liest direkt hinein** |
| `self.connection_status: bool` | `NavidromeMenuHandler.__init__` | `_initialize_api()`, `handle_reconnect()` (bei fehlgeschlagenem Ping) | `_check_connection()` (8 interne Aufrufer) | Nur innerhalb der Klasse, sauber gekapselt hinter `_check_connection()` |
| `self.navidrome_api` | `__init__` (DI) | – | alle API-aufrufenden Methoden | Nur Lesezugriff, sauber (ARCH-009) |
| `self.error_handler` | extern gesetzt (`RichMenuHandler`) | extern | alle `try/except`-Blöcke | Bereits als optionales, additives Attribut etabliert |

**Auflösungsvorschlag (nicht Teil von Stufe 1, siehe Abschnitt 4):**
`browse_states` ist der einzige State mit echtem externem Fremdzugriff
und damit der einzige, der eine Migrationsstufe **blockieren** kann,
sobald `handle_search`/`process_search_query` selbst extrahiert werden
sollen. Für die hier vorgeschlagene erste Stufe (reines
Detail-Rendering) ist er irrelevant — keine der drei Zielmethoden
berührt `browse_states`. Empfehlung (Doku-only, kein Code): diesen
Fremdzugriff als eigenen, offenen Punkt in
`docs/FINDINGS_INDEX.md` festhalten, damit er nicht erst bei einer
späteren Search-Extraktions-Stufe überrascht (siehe Abschnitt 7,
offene Frage 2).

---

## 4. Migrationsreihenfolge

Nummeriert nach empfohlener Ausführungsreihenfolge, **nicht** identisch
zur Reihenfolge in Abschnitt 5 der Zieldoku (dort: `browser_service`
zuerst). Jede Stufe ist unabhängig freigebbar; keine Stufe setzt eine
andere als bereits umgesetzt voraus außer explizit vermerkt.

### Stufe 1 — Detail-Rendering-Extraktion (`navidrome_renderer.py`, nur Album/Song/Playlist)
**Ziel:** MarkdownV2-Text-/Keyboard-Bau der drei Detail-Methoden in
reine, API-freie Funktionen auslagern. Siehe Abschnitt 5 für Details.
**Warum zuerst:** höchste Struktur-Uniformität, geringstes
Regressionsrisiko nach Nachbesserung der Testlücke (Playlist),
kein Shared-State-Konflikt, additiv, keine öffentliche
Signaturänderung.

### Stufe 2 — `_check_connection()`/`_show_connection_error()`-Konsolidierung (optional, klein)
**Ziel:** Diese beiden bereits vollständig entkoppelten, reinen Helfer
(kein dynamischer Content, kein API-Call) könnten zusammen mit
`_format_track_duration()` denselben Renderer-Modul-Header teilen,
statt als Instanzmethoden zu verbleiben. **Nicht zwingend nötig** —
sie sind bereits sauber; diese Stufe ist nur sinnvoll, falls Stufe 1
zeigt, dass ein gemeinsamer Renderer-Namespace für alle
„reinen Presentation"-Helfer Vorteile bringt. Kein eigenes Ziel,
sondern eine mögliche Erweiterung von Stufe 1, falls dort weniger
Aufwand als erwartet anfällt.

### Stufe 3 — Browse-Rendering-Extraktion (`handle_browse_artists`/`_albums`/`_genres`)
**Ziel:** Analog zu Stufe 1, aber für die drei Browse-Methoden.
**Warum NICHT zuerst:** 0 direkte Erfolgspfad-Tests für 2 von 3
Methoden, eingebettete Verzweigungslogik (`handle_browse_albums`
hat zwei API-Pfade), höheres Regressionsrisiko. **Voraussetzung:**
Characterization-Tests für alle drei Methoden VOR der Extraktion
(analog zum Playlist-Nachtrag in Stufe 1) — das ist der größte
Einzel-Arbeitsblock dieser Stufe, nicht die Extraktion selbst.

**Nachtrag (2026-09-13) — Voraussetzung erfüllt, Extraktion selbst
noch offen:** die Characterization-Tests wurden freigegeben und
umgesetzt (eigener PR, siehe `docs/MusicBot_ENGINEERING_BASELINE_v10.md`)
als bewusst separater erster Schritt (Nutzerentscheidung: „Zwei PRs:
Tests zuerst" statt Tests+Extraktion in einem PR wie bei Stufe 1) —
17 neue Tests in `TestBrowseArtistsCharacterization`/
`TestBrowseAlbumsCharacterization`/`TestBrowseGenresCharacterization`
(`tests/test_navidrome_menu_handler.py`), reine Testergänzung, keine
Produktionscode-Änderung. Dabei wurde **NAV-F14** entdeckt (`handle_
browse_genres()` crasht bei nicht-numerischem `songCount` statt sauber
auf die alphabetische Sortierung zurückzufallen — Details siehe
`docs/MusicBot_NAVIDROME_MENU_ARCHITECTURE.md` Abschnitt 4) — bewusst
NICHT im selben Schritt gefixt, bleibt OPEN als eigenständige
Entscheidung. Die eigentliche Rendering-Extraktion (zweiter PR) ist
noch nicht freigegeben.

### Stufe 4 — `services/navidrome/browser_service.py` (API-Extraktion)
**Ziel:** Der in der Zieldoku beschriebene `browser_service` — reine
API-Aufruf-/Datenextraktions-Funktionen (`get_artists_page()`,
`get_albums_page()`, `get_genres_sorted()`, `get_songs_by_genre()`),
die die bereits in Stufe 3 extrahierten Renderer-Funktionen füttern.
**Warum danach:** erst wenn Rendering sauber getrennt ist, wird der
verbleibende Rest (API-Call + Pagination-Arithmetik) klar genug, um
ohne Vermischung mit Rendering-Reste extrahiert zu werden. Vor
Stufe 4 wäre die Trennlinie unklar (Pagination-Entscheidungen wie
„hat es eine nächste Seite" hängen von Keyboard-Struktur ab, die erst
nach Stufe 3 vollständig getrennt ist).

### Stufe 5 — `NavidromeMenuHandler` schlank (reine Orchestrierung)
**Ziel:** Nach Stufe 1–4 bleibt `NavidromeMenuHandler` nur noch
Orchestrierung (`_check_connection()`-Vorabcheck → `browser_service`
aufrufen → `navidrome_renderer` aufrufen → `edit_message_text()`) +
Error-Handling + `browse_states`. Kein neues Modul, sondern das
natürliche Ergebnis der vorherigen Stufen — eigene Stufe nur, falls
nach Stufe 4 noch nennenswerter Aufräumbedarf besteht.

**Explizit NICHT geplant** (Search/Favorites/Playlists-Liste bleiben
KEEP laut Zieldoku Abschnitt 5): `handle_search`,
`process_search_query`, `_process_genre_search_query`,
`handle_favorites`, `handle_my_playlists` werden in keiner dieser
Stufen anfassen — sie bleiben Methoden auf `NavidromeMenuHandler`,
bis ihr Umfang tatsächlich wächst (z. B. durch Playlist-CRUD, aktuell
nicht geplant).

---

## 5. Erste Migrationsstufe — Detail

### Ziel

Ein neues Modul `handlers/navidrome_renderer.py` mit **genau drei**
reinen Funktionen für Stufe 1 (bewusst nicht mehr — kein Scope-Creep
zu Browse-Rendering, siehe unten):

```python
def render_album_detail(album: dict) -> tuple[str, InlineKeyboardMarkup]: ...
def render_song_detail(song: dict) -> tuple[str, InlineKeyboardMarkup]: ...
def render_playlist_detail(playlist: dict) -> tuple[str, InlineKeyboardMarkup]: ...
```

Plus der bereits existierende, reine `_format_track_duration()` als
modulweite Funktion (wandert vollständig — verifiziert: **keine**
Aufrufer außerhalb dieser drei Methoden, siehe Audit-Tabelle
Abschnitt 2 und Grep-Befund unten).

`NavidromeMenuHandler.handle_album_detail()` (und analog Song/
Playlist) behält vollständig: `_check_connection()`-Vorabcheck,
`asyncio.to_thread(self.navidrome_api.make_request, ...)`-Aufruf,
`try/except`+`error_handler`-Delegation. Neu ist ausschließlich der
Zwischenschritt: statt Text/Keyboard inline zu bauen, ruft die Methode
`render_album_detail(album)` auf und reicht `(text, keyboard)`
unverändert an `edit_message_text()` durch.

**Wichtige Abgrenzung (Feedback aus dem Architecture-Review, siehe
Abschnitt 8):** `navidrome_renderer.py` enthält in Stufe 1
**ausschließlich** diese drei Detail-Render-Funktionen — keine
Browse-Rendering-Funktionen. Das ist bewusst keine Vorwegnahme von
Stufe 3/4 (CLAUDE.md Abschnitt 3.A: „Eine ARCH-Phase darf nicht
eigenmächtig mehrere zukünftige ARCH-Phasen vorwegnehmen").

### Voraussetzung vor der eigentlichen Extraktion (Pflichtschritt, nicht optional)

`handle_playlist_detail` hat **0 direkte Unit-Tests** — im Gegensatz
zu `handle_album_detail` (4 Tests) und `handle_song_detail` (3 Tests).
Das unterläuft das Kernargument „beste Coverage der Datei" für genau
1 von 3 Zielmethoden. **Vor** der Extraktion werden daher 3–4
Characterization-Tests für `handle_playlist_detail` ergänzt
(Erfolgsfall mit Tracklist, Escaping von Playlist-Name/Owner,
Not-Found, Connection-Error) — analog zu den bereits bestehenden
Album-Tests (`TestAlbumDetailNavF9`). Diese Tests laufen VOR der
Extraktion gegen den aktuellen, unveränderten Code und dienen als
Regressions-Beweis danach.

### Erwartete Änderungen

| Datei | Änderung |
|---|---|
| `handlers/navidrome_renderer.py` | **NEU.** 3 reine Funktionen + `_format_track_duration()`-Äquivalent (als modulweite Funktion, nicht mehr `@staticmethod` auf der Handler-Klasse). |
| `handlers/navidrome_menu_handler.py` | `handle_album_detail`/`handle_song_detail`/`handle_playlist_detail`: Text-/Keyboard-Bau-Code entfernt, durch 1 Funktionsaufruf ersetzt. `_format_track_duration` als `@staticmethod` entfernt (verschoben). Keine Änderung an Methodensignaturen, keine Änderung an `_check_connection`/Error-Handling. |
| `tests/test_navidrome_menu_handler.py` | Bestehende `TestAlbumDetailNavF9`/`TestSongDetailNavF9`/`TestFormatTrackDuration`-Klassen: Erwartung ist, dass sie **unverändert** weiterlaufen (sie prüfen `kwargs["text"]`/`kwargs["reply_markup"]` am Ende von `edit_message_text()`, nicht die interne Struktur). Neue Characterization-Tests für Playlist-Detail (Pflichtschritt oben) werden hier ergänzt, nicht in einer neuen Testdatei. |
| `tests/test_navidrome_renderer.py` | **NEU.** Reine Unit-Tests der 3 Render-Funktionen (kein Mock nötig — reine Funktionen, Input: Dict, Output: Tuple). |

### Risiken

- **MarkdownV2-Escaping-Drift:** die Historie dieser Datei zeigt
  bereits zwei reale Escaping-Bugs (BUG-007b, NAV-F13). Eine
  Verschiebung von Text-Bau-Code ist genau die Art Änderung, bei der
  ein `escape_md_v2()`-Aufruf verloren gehen könnte. Gegenmaßnahme:
  Abbruchkriterium unten + Byte-genauer Vorher/Nachher-Vergleich.
- **`_format_track_duration()`-Verschiebung:** verifiziert per Grep,
  dass es **keine** Aufrufer außerhalb der drei Zielmethoden gibt
  (`grep -n "_format_track_duration" handlers/ tests/` → nur die 3
  internen Aufrufe + `TestFormatTrackDuration`). Kein
  Rückwärtskompatibilitäts-Delegator nötig.
- **Import-Zyklus:** `navidrome_renderer.py` muss `InlineKeyboardButton`/
  `InlineKeyboardMarkup` (telegram) und `escape_md_v2` (helfer) importieren
  — beide bereits unabhängige, zyklusfreie Module. Kein Risiko.

### Test-Auswirkung

- Gezielt: `tests/test_navidrome_menu_handler.py` (bestehende
  Album-/Song-Tests + neue Playlist-Tests) + neue
  `tests/test_navidrome_renderer.py`.
- Thematisch: gleiche Gruppe wie in allen vorherigen NAV-F-PRs dieser
  Session (Navidrome/Menu-Actions/Menu-Router/Navigation-Continuity).
- **Abbruchkriterium (hart, aus dem Architecture-Review übernommen):**
  Muss irgendein bestehender Test aus `TestAlbumDetailNavF9`/
  `TestSongDetailNavF9` nach der Extraktion inhaltlich angepasst
  werden (nicht nur ein Importpfad) — STOPP. Das bedeutet, der
  Rendering/API-Schnitt ist an der falschen Stelle gezogen, nicht dass
  der Test veraltet ist.
- **Zusätzliches Sicherheitsnetz:** vor der Extraktion einen
  Snapshot der drei `edit_message_text()`-Aufrufe (Beispiel-Payload
  pro Methode) festhalten; nach der Extraktion Byte-für-Byte
  vergleichen (`text`, `reply_markup.inline_keyboard`-Callback-Daten
  und -Label).

### Abbruchkriterium der gesamten Stufe

- Größenabbruch: berührt die Umsetzung mehr als die drei Methoden +
  1 neue Datei + Tests (z. B. „während ich dabei bin, räume ich auch
  X auf") → Stufe wird gesplittet, nicht erweitert.
- Wenn die Playlist-Characterization-Tests vor der Extraktion einen
  bestehenden, bisher unentdeckten Bug aufdecken (denkbar, da
  `handle_playlist_detail` nie isoliert getestet wurde) → dieser Bug
  wird als eigenes Finding behandelt (eigener PR, eigene
  `FINDINGS_INDEX.md`-Zeile), NICHT im selben Schritt mit der
  Extraktion vermischt.

### Umsetzungs-Nachtrag (2026-09-13) — Stufe 1 IMPLEMENTED

Vom Nutzer freigegeben und in einem PR umgesetzt (siehe
`docs/MusicBot_ENGINEERING_BASELINE_v10.md`, „Recent Major Changes").

- Pflichtschritt eingehalten: 4 Characterization-Tests für
  `handle_playlist_detail` (`TestPlaylistDetailNavF5`) wurden **vor**
  der Extraktion ergänzt und liefen gegen den unveränderten Code grün
  (Regressionsbeweis) — kein bisher unentdeckter Bug aufgedeckt, daher
  kein separates Finding nötig.
- `handlers/navidrome_renderer.py` neu, exakt wie geplant: 3 reine
  Render-Funktionen (`render_album_detail`/`render_song_detail`/
  `render_playlist_detail`) + `format_track_duration()` (verschoben von
  `NavidromeMenuHandler._format_track_duration()`), kein API-Call,
  kein State, keine Browse-Rendering-Funktionen (Scope wie geplant
  eingehalten).
- **Abbruchkriterium griff NICHT:** `TestAlbumDetailNavF9`,
  `TestSongDetailNavF9` und die neuen `TestPlaylistDetailNavF5`-Tests
  liefen nach der Extraktion **unverändert** grün (0 inhaltliche
  Anpassungen) — der Rendering/API-Schnitt war an der richtigen
  Stelle gezogen.
- Neue, reine Unit-Tests in `tests/test_navidrome_renderer.py` (13
  Tests, ohne Mocks) ergänzen die bestehenden End-to-End-Tests.
- Stufe 2 (Konsolidierung `_check_connection`/`_show_connection_error`)
  weiterhin **nicht** umgesetzt — wie im Plan als optional markiert,
  kein erkennbarer Zusatznutzen während der Stufe-1-Umsetzung
  aufgefallen.
- Offene Fragen 2–4 aus Abschnitt 7 (Doku von `browse_states`-
  Fremdzugriff als Finding, PR-Aufteilung, Stufe-2-Wunsch) bleiben
  unbeantwortet/nicht Teil dieser Freigabe — nur Stufe 1 wurde
  angefragt und umgesetzt.

---

## 6. Explizit ausgeklammert

Gemäß Auftrag Abschnitt 4 (Anti-Overengineering-Regeln), zusätzlich
bestätigt durch das Audit:

- **Keine 7-Service-Aufteilung.** Dieser Plan schlägt für Stufe 1
  genau 1 neues Modul vor (`navidrome_renderer.py`), nicht mehr.
- **Keine Aufspaltung in mehr als zwei neue Module in Stufe 1.**
  Stufe 1 hat genau ein neues Modul.
- **Keine Refactorings an Search/Favorites/Playlists-Liste** (bleiben
  KEEP) — betrifft `handle_search`, `process_search_query`,
  `_process_genre_search_query`, `handle_favorites`,
  `handle_my_playlists`. Nicht Teil irgendeiner Stufe in diesem Plan.
- **Keine Änderung an `NavidromeAPI`** (`services/clients/navidrome_api.py`)
  — bleibt vollständig unangetastet.
- **Keine Änderung am Routing** — `RichMenuSystem`, `MenuItem`-Baum,
  der `nav_`-Präfix-Dispatcher in `handlers/menu/actions/navidrome.py`
  bleiben strukturell unverändert. Die Aufrufe innerhalb dieses
  Dispatchers zeigen nach Stufe 1 weiterhin auf dieselben
  `NavidromeMenuHandler`-Methodennamen mit denselben Signaturen.
- **Keine Änderung an Findings-Status** — alle NAV-F1–NAV-F13 bleiben
  CLOSED, dieser Plan fügt keine neuen CLOSED/OPEN-Statusänderungen
  hinzu (der einzige neue Vorschlag, ein Doku-Eintrag zu
  `browse_states`-Fremdzugriff, ist eine neue OPEN-Zeile, keine
  Statusänderung eines bestehenden Findings — siehe Abschnitt 7).
- **Keine Big-Bang-Umstellung.** Stufen 2–5 sind bewusst nicht
  Gegenstand dieser Freigabe-Anfrage — nur Stufe 1 wird zur
  Entscheidung vorgelegt (Auftrag Abschnitt 7: „Der Plan selbst wird
  nicht implementiert").
- **Keine Umbenennung/Signaturänderung öffentlicher Methoden.**
  `handle_album_detail(update, context, album_id)` etc. bleiben exakt
  wie sie sind — nur der interne Methodenkörper ändert sich.

---

## 7. Offene Fragen an den Nutzer

1. **Reihenfolge-Abweichung von der Zieldoku:** dieser Plan schlägt
   vor, mit Detail-Rendering statt mit `browser_service`
   (Browse-API-Extraktion) zu beginnen — obwohl Abschnitt 5 der
   Zieldoku die Browse-Methoden zuerst nennt. Ist das im Sinne des
   Auftrags akzeptabel, oder soll trotz der schlechteren
   Testabdeckung an der in der Zieldoku suggerierten Reihenfolge
   festgehalten werden (dann müsste Stufe „Browse-Characterization-
   Tests zuerst" vor jede Extraktion geschoben werden — das würde die
   erste Stufe erheblich vergrößern)?
2. **`browse_states`-Fremdzugriff aus `RichMenuHandler`:** soll dieser
   bereits jetzt als neue, offene `docs/FINDINGS_INDEX.md`-Zeile
   dokumentiert werden (reine Doku-Änderung, kein Code) — oder erst
   dann, wenn eine Stufe tatsächlich `browse_states` anfasst (also
   frühestens bei einer künftigen Search-Extraktions-Stufe, die
   dieser Plan aktuell nicht vorschlägt)?
3. **Playlist-Characterization-Tests:** sollen diese als eigener,
   separater PR *vor* der Freigabe der eigentlichen Rendering-
   Extraktion laufen (sauberer Git-History-Schnitt, 2 PRs), oder
   beides in einem PR (Tests + Extraktion zusammen, wie es bei den
   meisten NAV-F-Fixes dieser Session gehandhabt wurde)?
4. **Stufe 2 (Konsolidierung von `_check_connection`/
   `_show_connection_error` in denselben Renderer-Namespace):** ist
   das gewünscht, oder soll dieser bereits saubere Code unangetastet
   bleiben (meine Einschätzung: eher nicht nötig, siehe Abschnitt 4)?

---

## 8. Werkzeuge

- **`senior-software-developer`-Agent** (registrierter Architecture-
  Reviewer-Agent dieses Projekts): genutzt für eine unabhängige
  Zweitmeinung zur abgeleiteten Migrationsstufe 1, nachdem der
  Audit-Teil (Abschnitt 2/3) abgeschlossen war. Konkreter Beitrag:
  - bestätigte die Abweichung von der Zieldoku-Reihenfolge als durch
    CLAUDE.md §18/§6 gedeckt,
  - deckte auf, dass `handle_playlist_detail` **0 direkte Unit-Tests**
    hat und das „beste Coverage"-Argument damit nur für 2 von 3
    Zielmethoden trägt (→ neuer Pflichtschritt „Characterization-Tests
    vor Extraktion" in Abschnitt 5),
  - schlug vor, `navidrome_renderer.py` explizit auf Detail-Funktionen
    zu begrenzen, um Scope-Creep in Richtung Browse-Rendering zu
    vermeiden (→ explizite Abgrenzung in Abschnitt 5 übernommen),
  - lieferte das harte Abbruchkriterium „jede inhaltliche
    Testanpassung nach der Extraktion bedeutet einen falschen Schnitt"
    sowie den Vorschlag eines Byte-genauen Vorher/Nachher-Vergleichs
    (→ beide in Abschnitt 5 „Test-Auswirkung"/„Risiken" übernommen),
  - riet, den `browse_states`-Fremdzugriff aus `RichMenuHandler` als
    eigenständigen, zurückgestellten Finding-Eintrag zu dokumentieren,
    statt ihn zu fixen (→ Abschnitt 7, offene Frage 2).
  Die vollständige Rückmeldung wurde 1:1 in die betroffenen Abschnitte
  eingearbeitet, nicht separat angehängt.
- **Direkte Code-Lektüre (Read/Grep/Bash statt Explore-Agent):** die
  vollständige Audit-Tabelle (Abschnitt 2) wurde durch direktes Lesen
  von `handlers/navidrome_menu_handler.py` (vollständig, alle 1493
  Zeilen), `handlers/menu/actions/navidrome.py` (vollständig),
  relevanten Ausschnitten aus `handlers/menu/rich_menu_system.py` und
  `handlers/menu/rich_menu_handler.py` sowie projektweiten
  `grep`-Läufen (Caller-Suche pro Methode, `browse_states`-Nutzung,
  Dead-Code-Check) erstellt. Ein `Explore`-Subagent wurde bewusst
  **nicht** eingesetzt: der Umfang (2 Kerndateien von zusammen
  <1800 Zeilen plus gezielte Grep-Treffer) war mit direkter Lektüre
  schneller und präziser abzudecken als über eine Subagent-Delegation
  mit anschließender Ergebnis-Interpretation — insbesondere, weil für
  die Zeilen-genaue LOC-/Verantwortlichkeits-Tabelle exaktes,
  nachvollziehbares Wissen über einzelne Codezeilen nötig war, nicht
  nur eine Fundstellen-Liste.
- **`code-reviewer`-Agent:** nicht eingesetzt — dieser Agent ist für
  die Bewertung eines konkreten Diffs/einer Codeänderung ausgelegt;
  in dieser READ-ONLY-Phase existiert kein Diff zu bewerten.
- **`Plan`-Agent:** bewusst nicht eingesetzt, um die eigentliche
  Migrationsreihenfolgen-Ableitung (Auftrag Abschnitt 3: „leitest DU
  SELBST ab") nicht an einen weiteren Agenten zu delegieren — das
  hätte die im Auftrag verlangte eigene Urteilsbildung ersetzt statt
  ergänzt. Der `senior-software-developer`-Einsatz oben ist bewusst
  als nachgelagerte, unabhängige *Prüfung* einer bereits selbst
  getroffenen Entscheidung konzipiert, nicht als deren Herleitung.
