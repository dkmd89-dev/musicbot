# Navidrome Menu System — API Capability & Architecture

**Status:** CURRENT (lebendes Dokument). Entstanden aus dem read-only
„MASTER PHASE — NAVIDROME MENU SYSTEM"-Audit (2026-09-13). **Alle 16
Bug-Findings (NAV-F1–NAV-F16) sind CLOSED** (NAV-F12–NAV-F16 wurden
erst im Verlauf der Umsetzung bzw. des Architecture Refactoring Audits
entdeckt, siehe Abschnitt 4). **NAV-F17 (Discovery-Erweiterung) ist
CLOSED (2026-09-14)** — auf Nutzerwunsch umgesetzt, siehe Abschnitt 4.
**NAV-F18 (Playlist-CRUD) ist CLOSED (2026-09-14)** — auf Nutzerwunsch
umgesetzt, siehe Abschnitt 4. Damit sind alle 18 Findings dieses
Dokuments geschlossen, keine offenen Punkte mehr.
**Scope:** `handlers/navidrome_menu_handler.py`,
`handlers/menu/actions/navidrome.py`, `services/clients/navidrome_api.py`
und ihre unmittelbaren Kollaborateure (Personal-Statistics-Domain nur
insoweit sie über `nav_recent`/`nav_link_stats` verlinkt wird).
**Verwandtes Dokument:** `docs/MusicBot_TELEGRAM_MENU_SYSTEM.md`
(Gesamtmenü-Architektur, Routing-Ebenen, ARCH-021/023/024/025/029).

---

## 1. Architektur

```text
Telegram Update
   ↓
RichMenuHandler.get_telegram_handlers()  — CallbackQueryHandler(pattern="^nav_")
   ↓
RichMenuSystem.handle_callback()
   ├── 9 statische MenuItem-Blätter (definitions.py)
   │     → dünne _handle_navidrome_*-Delegatoren (rich_menu_system.py)
   │        → handlers/menu/actions/navidrome.py (9 zustandslose Wrapper)
   └── RichMenuSystem._handle_navidrome_callback() — interner Dispatcher
         für dynamisch generierte IDs (nav_artist_<id>, nav_album_<id>,
         nav_song_<id>, nav_genre_<name>, nav_browse_*_<page>, ...),
         da diese nicht als statische MenuItems modellierbar sind
   ↓
handlers.navidrome_menu_handler.NavidromeMenuHandler (1114+ Zeilen)
   ↓
services.clients.navidrome_api.NavidromeAPI (254 Zeilen, schlanker
   externer Integrationsadapter, ARCH-009 abgeschlossen — reine
   Subsonic-HTTP-Kommunikation, keine Telegram-Objekte, keine
   fachliche Orchestrierung)
```

**Bekannte, bewusste Architekturentscheidung:** zwei parallele
Routing-Konzepte für `nav_`-Callbacks (statischer `MenuItem`-Baum +
interner String-Präfix-Dispatcher) sind strukturell notwendig, da
dynamische IDs (Artist-/Album-/Song-/Genre-IDs) nicht als feste
`MenuItem`s modelliert werden können — kein Fehler, aber Ursache der
Verwechslungsgefahr, die zu NAV-F2 (siehe unten) führte.

**HIGH COUPLING (dokumentiert, noch nicht behoben):** `NavidromeMenuHandler`
vereint API-Aufruf, Pagination, MarkdownV2-Rendering und Error-Handling in
einer Klasse — kein Renderer, keine Service-Schicht dazwischen. Siehe
Abschnitt 5 (Zielarchitektur) für die empfohlene, noch nicht umgesetzte
Auflösung.

**Connection-Check-Konzepte (NAV-F6, CLOSED 2026-09-13):**
`enhanced_status_handler.py` (Admin-Diagnose) nutzt den echten
`NavidromeAPI.check_connection()` (`ping`-Request). Der schnelle, rein
lokale `NavidromeMenuHandler._check_connection()`-Vorab-Check (prüft nur,
ob `NAVIDROME_URL`/`NAVIDROME_USER` nicht-leer sind, BUG-007a) bleibt
bewusst unverändert vor den 8 Browse-/Such-Methoden — kein `ping` vor
jedem einzelnen Klick (Latenz-Trade-off). `handle_reconnect()`
(„🔄 Erneut versuchen") führt seit dem NAV-F6-Fix zusätzlich einen echten
`await NavidromeAPI.check_connection()` aus, bevor „✅ Verbindung
wiederhergestellt!" angezeigt wird — nur dieser explizit vom Nutzer
ausgelöste Klick rechtfertigt den echten Netzwerk-Request. Schlägt der
Ping fehl, wird `connection_status` zusätzlich zurückgesetzt, damit der
nächste Klick auf eine andere Navidrome-Funktion wieder korrekt den
Verbindungsfehler-Screen zeigt.

---

## 2. Aktuelle Menüstruktur

```text
🎵 Navidrome Mediathek (id="navidrome", USER-Level, ungegated)
├── 🔍 Durchsuchen (reiner Container)
│   ├── 🎤 Künstler       nav_browse_artists    — IMPLEMENTED
│   ├── 💿 Alben          nav_browse_albums     — IMPLEMENTED
│   └── 🎭 Genres         nav_browse_genres     — IMPLEMENTED
├── 🔎 Suchen (reiner Container)
│   ├── 🔍 Überall        nav_search            — IMPLEMENTED
│   ├── 🎤 Künstler       nav_search_artists    — IMPLEMENTED
│   ├── 💿 Alben          nav_search_albums     — IMPLEMENTED
│   ├── 🎵 Songs          nav_search_songs      — IMPLEMENTED
│   └── 🎭 Genres         nav_search_genres     — IMPLEMENTED (NAV-F7:
│                                                  Teilstring-Filter über
│                                                  getGenres(), keine
│                                                  eigene Such-API)
├── 📋 Meine Playlists    nav_playlists         — IMPLEMENTED (das frühere
│                                                  Duplikat nav_browse_playlists
│                                                  wurde entfernt, NAV-F4);
│                                                  Playlist-Detail (nav_playlist_<id>)
│                                                  seit NAV-F5 implementiert (getPlaylist)
├── ⭐ Favoriten          nav_favorites         — IMPLEMENTED (nur lesend)
├── 🕐 Zuletzt gespielt   nav_recent            — IMPLEMENTED, ruft
│                                                  StatistikHandler.handle_last_played()
│                                                  (Personal-Statistics-Domain, NICHT
│                                                  NavidromeMenuHandler!) — liest den
│                                                  lokalen Play-History-Cache
│                                                  (PlayHistoryPoller), keine Live-API
└── 📊 Statistiken        nav_link_stats        — reiner Cross-Link zu "menu:stats"
                                                    (Personal-Statistics-Domain),
                                                    KEIN eigener Handler
```

**Wichtig — bewusst korrekte, nicht zu ändernde Entscheidungen:**
- „🕘 Zuletzt gespielt" und „📊 Statistiken" verlinken absichtlich auf die
  bereits bestehende Personal-Statistics-Domain, statt eine dritte,
  parallele Implementierung zu bauen. **Nicht neu implementieren.**
- `NavidromeMenuHandler.handle_stats()` (ein `getIndexes`-basierter
  Statistik-Versuch) war unerreichbar (kein Menüpunkt zeigte darauf) und
  wurde daher entfernt — siehe NAV-F3 (CLOSED).
- Zwei dynamische Buttons innerhalb von `handle_browse_genres()`
  ("🔍 Genre suchen" → `nav_search_genres`, "📊 Genre-Stats" →
  `nav_genre_stats`) sind seit NAV-F7/NAV-F8 IMPLEMENTED. Beide erscheinen
  bewusst nicht im obigen Baum (kein eigener Menüpunkt, sondern
  Inline-Buttons innerhalb der Genre-Liste selbst).

---

## 3. API Capability Matrix (Kurzfassung)

Vollständige Dreispalten-Matrix (Navidrome-Fakt / Codebefund / Bewertung)
mit allen 33 geprüften Subsonic-Capabilities: siehe Audit-Transkript
(Session vom 2026-09-13). Kurzfassung:

| Bereich | Implementiert & erreichbar | Implementiert, aber unerreichbar | Fehlt vollständig |
|---|---|---|---|
| Browsing | `getArtists`, `getArtist`, `getAlbumList2` (`alphabeticalByArtist` + `newest`, NAV-F17), `getGenres`, `getSongsByGenre`, `getTopSongs` (NAV-F17, CLOSED) | — | `getMusicFolders`, `getMusicDirectory`, `getArtistInfo(2)`, `getAlbumInfo(2)`, `getSimilarSongs(2)`, `getIndexes` (unbenutzt seit NAV-F3) |
| Album/Song-Detail | `getAlbum`, `getSong` (NAV-F9, CLOSED) | — | — |
| Album/Song-Listen | `getRandomSongs` (NAV-F17, CLOSED) | — | `getAlbumList` (v1), weitere `getAlbumList2`-Typen (`recent`/`frequent`/etc.) |
| Suche | `search3` | — | `search2` |
| Playlists | `getPlaylists` (Liste), `getPlaylist` (Detail, NAV-F5, CLOSED), `createPlaylist`/`updatePlaylist`/`deletePlaylist` (NAV-F18, CLOSED) | — | — |
| Media | — | — | `stream`, `download`, `getCoverArt`, `getLyrics`, `getAvatar` |
| Annotation | — | — | `star`, `unstar`, `setRating`, `scrobble` |
| Favoriten | `getStarred2` (nur lesend) | — | `getStarred` (v1) |
| Now Playing | `getNowPlaying` (nur intern für `PlayHistoryPoller`, kein Live-Menü) | — | — |
| Queue/Bookmarks/Sharing/Radio | — | — | vollständig |
| Scan | *(separater, nicht-Subsonic Docker-/Subprocess-Weg, admin-only, außerhalb dieses Scopes)* | — | `getScanStatus`/`startScan` (Subsonic-Weg) |

**Verification-Hinweis:** alle Navidrome-Fakten basieren auf allgemeiner
Subsonic-/Navidrome-API-Dokumentation, nicht auf einer Live-Prüfung gegen
den produktiv genutzten Server (`Verification: UNVERIFIED` auf
Server-Ebene, nicht gleichbedeutend mit `UNSUPPORTED`).

---

## 4. Findings

| ID | Beschreibung | Finding Type | Priorität | Status |
|---|---|---|---|---|
| **NAV-F1** | Alle „🔙 Zurück"/„❌ Abbrechen"-Buttons im Navidrome-Bereich (12 Vorkommen) nutzten `callback_data="menu_navidrome"`/`"menu_main"` (Unterstrich) statt des seit ARCH-021 verbindlichen `"menu:<id>"`-Formats — weder PTB-Pattern noch `RichMenuSystem`-Routing-Zweig vorhanden, jeder Klick verpuffte stillschweigend. | BROKEN, DEAD_ROUTE | **P0** | **CLOSED** (2026-09-13) |
| **NAV-F2** | `nav_genre_songs_all_<name>` ("➕ N weitere anzeigen") wurde vom generischen `nav_genre_`-Präfix-Zweig fehlerhaft abgefangen, lieferte korrupten Genre-Namen (`"songs_all_<name>"`) an `handle_genre_detail()`. | BROKEN | **P0** | **CLOSED** (2026-09-13) |
| **NAV-F3** | `NavidromeMenuHandler.handle_stats()` (getIndexes-basiert) war unerreichbar (kein Menüpunkt; `nav_link_stats` verlinkt stattdessen korrekt auf die Personal-Statistics-Domain) — toter Code inkl. eigenem Test für unerreichbaren Pfad; Methode und Test vollständig entfernt. | DEAD_ROUTE | P2 | **CLOSED** (2026-09-13) |
| **NAV-F4** | `nav_browse_playlists` (unter „Durchsuchen", STUB) vs. `nav_playlists` („Meine Playlists", Top-Level, real) — zwei Menüpunkte für dasselbe Konzept. Entscheidung: `nav_playlists` bleibt, `nav_browse_playlists` entfernt (MenuItem, Wrapper, Action-Funktion, Tests). | DUPLICATE | P1 | **CLOSED** (2026-09-13) |
| **NAV-F5** | `nav_playlist_<id>`-Buttons wurden in `handle_my_playlists()` erzeugt, aber es existierte kein Dispatcher-Zweig dafür (fiel auf generisches „Funktion nicht implementiert"). Fix: `handle_playlist_detail()` implementiert (`getPlaylist` via `make_request`, analog zu `handle_album_detail()`), Dispatcher-Zweig `nav_playlist_` ergänzt (kollisionsfrei zu `nav_playlists`, da Letzteres nur über `menu:nav_playlists` läuft). | DEAD_ROUTE | P1 | **CLOSED** (2026-09-13) |
| NAV-F6 | `handle_reconnect()` prüfte nie den echten `NavidromeAPI.check_connection()` (`ping`), nur lokale Config-Präsenz — abweichend von `enhanced_status_handler.py`, das den echten Ping bereits nutzt. | ARCHITECTURE_VIOLATION | P1 | **CLOSED** (2026-09-13) |
| **NAV-F7** | `nav_search_genres` — STUB. Fix: eigener Suchpfad `search_type="genres"` in `NavidromeMenuHandler.handle_search()`/`process_search_query()` — Teilstring-Filter über die bereits von `handle_browse_genres()` genutzte `getGenres()`-Liste (keine dedizierte Subsonic-Genre-Such-API, keine neue Pipeline). | — | P3 | **CLOSED** (2026-09-13) |
| **NAV-F8** | `nav_genre_stats` — STUB. Fix: `StatisticsCalculator.generate_genre_stats()` (neu, All-Time Top-10 nach Plays, reine Wiederverwendung von `_parse_history_entries()`/`self.repository`) + `StatistikHandler.handle_genre_stats()`, Dispatcher delegiert analog zu `nav_recent`. Voraussetzung: `PlayHistoryPoller` erfasst seither zusätzlich das strukturierte `"genres"`-Feld pro Play (bevorzugte Datenquelle, `List[str]` aus Navidromes `[{"name": "Hip Hop"}, ...]`-Response — NICHT nur das einfache `"genre"`-Feld). Ein Multi-Genre-Track zählt für jedes zugeordnete Genre einmal (Summe kann `total_plays_with_genre` übersteigen), Duplikate innerhalb desselben Plays werden dedupliziert. Nachtrag: `NavidromeAPI.get_now_playing()` verwarf `genre`/`genres` bisher komplett (Adapter reichte nur `title`/`artist`/`album`/`id` durch) — ohne diesen Fix wäre die Genre-Erfassung im Poller nie tatsächlich befüllt worden; jetzt reiner Pass-Through beider Felder. | — | P3 | **CLOSED** (2026-09-13) |
| NAV-F9 | `nav_album_<id>`/`nav_song_<id>` Detailansichten — STUB, obwohl an 6 Stellen im Code bereits verlinkt (`getAlbum`/`getSong` nicht implementiert). | — | **P1** | **CLOSED** (2026-09-13) |
| NAV-F11 | `nav_artist_albums_all_<id>` (Button „➕ N weitere Alben" in `handle_artist_detail()`) wurde vom generischen `nav_artist_`-Präfix-Zweig fehlerhaft abgefangen, lieferte korrupten Artist-Namen an `handle_artist_detail()` — derselbe Bug-Typ wie NAV-F2, entdeckt bei der NAV-F9-Umsetzung. | BROKEN | P0 | **CLOSED** (2026-09-13) |
| NAV-F10 | `StatistikHandler.handle_last_played()` (erreicht über `nav_recent`) hatte kein `reply_markup` — in der ARCH-029-Phase („Menu Navigation Continuity") übersehen, da die Methode über `nav_recent`, nicht über eine `stats_*`-ID erreichbar ist. | Navigation-Gap (ARCH-029-Nachtrag) | P1 | **CLOSED** (2026-09-13) |
| **NAV-F12** | `nav_genre_stats` wurde vom generischen `nav_genre_`-Präfix-Zweig fehlerhaft abgefangen (`callback_data.startswith("nav_genre_")` matcht auch `"nav_genre_stats"`) — lieferte `handle_genre_detail(..., "stats")` statt den `nav_genre_stats`-Zweig zu erreichen. Derselbe Bug-Typ wie NAV-F2/NAV-F11, bisher unbemerkt, weil der STUB-Platzhaltertext ebenfalls nie erreicht wurde. Entdeckt beim Implementieren von NAV-F8 (per Regressionstest). Fix: eigener Zweig vor dem generischen `nav_genre_`-Check. | BROKEN, DEAD_ROUTE | P0 | **CLOSED** (2026-09-13) |
| **NAV-F13** | `handle_genre_detail()` sendete den statischen Text `"(erste 10 angezeigt)"` unescaped in einer `parse_mode="MarkdownV2"`-Nachricht — Telegram lehnte JEDEN erfolgreichen Genre-Lookup mit Songs mit `"Can't parse entities: character '(' is reserved"` ab (Live-Fund aus den Produktionslogs, reproduzierbar bei jedem Genre). Anders als BUG-007/NAV-F1-artige Findings kein dynamischer, sondern ein statischer String-Literal-Bug. Fix: `\\(erste 10 angezeigt\\)`. | BROKEN | P0 | **CLOSED** (2026-09-13) |
| **NAV-F14** | `handle_browse_genres()`: bei nicht-numerischem `songCount` fing der Sortier-`try/except` die Konvertierung ab und fiel auf alphabetische Sortierung zurück — aber die Anzeige-Schleife nutzte denselben rohen Wert danach ungeprüft in `if song_count > 0:`, was crashte (`TypeError`) und die generische Fehlermeldung statt einer Genre-Liste zeigte. Zusätzlich sortierte der Fallback nach dem falschen Feld (`"name"` statt dem tatsächlich angezeigten `"value"`). Fix: `songCount` wird jetzt einmalig vor Sortierung und Anzeige sicher zu `int` normalisiert (fehlerhafte Werte → 0), Sortierung erfolgt über `(-songCount, name.lower())` mit demselben `value`-bevorzugenden Feld wie die Anzeige. | BROKEN | P3 | **CLOSED** (2026-09-13) |
| **NAV-F15** | Vom Nutzer selbst gefunden+behoben: `render_playlist_detail()`s Tracklist-Overflow-Hinweis (`"_+N weitere Songs nicht angezeigt_"`, bei Playlists mit >25 Songs) enthielt ein rohes `+` in MarkdownV2-Text — `+` ist reserviert, Telegram lehnt die Nachricht mit `BadRequest` ab. Dieselbe Bug-Klasse wie NAV-F13. Fix: `+` entfernt (reines Stilmittel). | BROKEN | P0 | **CLOSED** (2026-09-13) |
| **NAV-F16** | Derselbe Bug wie NAV-F15, in `render_album_detail()` (Alben mit >25 Songs). Fix: `+` entfernt, identisch zu NAV-F15. | BROKEN | P0 | **CLOSED** (2026-09-13) |
| NAV-F17 | Kein Bug: im empfohlenen Zielmenü (Abschnitt 5) skizziertes Untermenü „🎵 Entdecken" implementiert. Umsetzung weicht in einem Punkt bewusst vom ursprünglichen Skizzen-Vorschlag ab (auf Nutzerentscheidung): „🔥 Top Songs je Künstler" (`getTopSongs`) ist KEIN eigener Menüpunkt im „Entdecken"-Menü, sondern ein neuer Button direkt in `render_artist_detail()` — der Artist-Name ist dort bereits bekannt, ein separater Freitext-Prompt (Artist-Name eintippen) wäre unnötiger Umfang. „🎲 Zufällige Songs" (`getRandomSongs`) und „🆕 Neue Alben" (`getAlbumList2 type=newest`) sind reine Inline-Buttons innerhalb der "Entdecken"-Nachricht (kein eigenes MenuItem je Option, analog zu Genre-Suche/-Stats NAV-F7/F8) - nur der Einstieg "nav_discover" ist ein MenuItem. Neuer Dispatcher-Zweig `nav_artist_topsongs_` MUSS (wie bei NAV-F2/F11/F8 bereits etabliert) vor dem generischen `nav_artist_`-Präfix-Check stehen. | — | P2 | **CLOSED (2026-09-14)** |
| NAV-F18 | Kein Bug: Playlist-CRUD implementiert — bewusst reduzierter Zuschnitt (Nutzerentscheidung): Erstellung nur mit Name (leere Playlist, kein Song-Auswahl-Schritt — bräuchte einen im Bot aktuell nirgends vorhandenen Mehrfachauswahl-Song-Picker, eigener Folge-Scope), Umbenennung, Löschung mit Bestätigungsdialog (analog `UserManagementHandler.delete_user_confirm()`). `handle_my_playlists()`s früher Return bei leerer Liste entfernt (der „➕ Neue Playlist"-Button muss auch dort erscheinen, um die erste Playlist zu bootstrappen). Vier neue Dispatcher-Zweige (`nav_playlist_create_prompt`/`_rename_`/`_delete_confirm_`/`_delete_execute_`) MÜSSEN vor dem generischen `nav_playlist_`-Präfix-Check stehen — derselbe Bug-Typ wie NAV-F2/F11/F17. | — | P2 | **CLOSED (2026-09-14)** |

Vollständige Details/Codebelege zu allen Findings: Audit-Transkript
(Session vom 2026-09-13) sowie `docs/FINDINGS_INDEX.md` (repoweite
Findings-Ledger, alle NAV-Findings dort gespiegelt).

---

## 5. Zielarchitektur (P2/P3, teilweise umgesetzt)

**Architecture Refactoring Audit (2026-09-13) — Migrationsstufe 1
✅ IMPLEMENTED:** `handlers/navidrome_renderer.py` existiert jetzt,
bisher **ausschließlich** mit den drei Detail-Render-Funktionen
(`render_album_detail()`/`render_song_detail()`/
`render_playlist_detail()` + `format_track_duration()`) — reine,
zustandslose Funktionen (Dict → `(Text, InlineKeyboardMarkup)`), 1:1
aus `NavidromeMenuHandler.handle_album_detail()`/`handle_song_detail()`/
`handle_playlist_detail()` extrahiert, keine Verhaltensänderung.
`NavidromeMenuHandler` behält vollständig Connection-Check, API-Aufruf
und Error-Handling dieser drei Methoden — nur der Text-/Keyboard-Bau
wanderte. Vollständiger Plan inkl. Audit-Tabelle, Begründung der
Abweichung von der unten dargestellten Ziel-Reihenfolge (Detail statt
Browse zuerst):
`docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md`.

**Migrationsstufe 3 ✅ IMPLEMENTED (2026-09-13):** analog für die drei
Browse-Methoden — `render_browse_artists()`/`render_browse_albums()`/
`render_browse_genres()` neu in `handlers/navidrome_renderer.py`.
Vorbereitet durch eigene Characterization-Tests (17 Tests, eigener PR)
und den dabei entdeckten, in einem separaten PR bereits behobenen
NAV-F14 (siehe Abschnitt 4). `handle_browse_albums()` behält beide
API-Pfade (`getArtist`/`getAlbumList2`) in `NavidromeMenuHandler`, da
sie einen echten Netzwerkaufruf enthalten.

**Detail-View-Familie vervollständigt ✅ IMPLEMENTED (2026-09-13):**
`render_artist_detail()`/`render_genre_detail()` ergänzen die in Stufe 1
extrahierten Album/Song/Playlist-Detail-Funktionen — dieselbe
Vorbereitungs-Logik (Pflichtschritt: fehlende Characterization-Tests für
Erfolgspfad/Overflow-Button/Connection-Error zuerst ergänzt, dann
Extraktion) in einem PR. Damit sind alle 5 Detail-Views
(Artist/Album/Song/Playlist/Genre) konsistent aus `NavidromeMenuHandler`
in den Renderer ausgelagert. `NavidromeMenuHandler` schrumpfte auf
1059 Zeilen (von ursprünglich 1493 vor Stufe 1).

**Migrationsstufe 4 ✅ IMPLEMENTED, bewusst reduzierter Zuschnitt
(2026-09-13):** `services/navidrome/browser_service.py` (NEU) enthält
**ausschließlich** `get_albums_page()` — die zwei-API-Pfad-Verzweigung
(`getArtist` vs. `getAlbumList2`) aus `handle_browse_albums()`, der
einzigen der drei Browse-Methoden mit echter Verzweigungslogik.
`handle_browse_artists()`/`handle_browse_genres()` blieben bewusst
**unangetastet**: nach der Rendering-Extraktion (Stufe 1/3) bestehen
sie nur noch aus 1-2 Zeilen reinem API-Call — eine Service-Extraktion
dort wäre reine Zeremonie ohne Kopplungsgewinn (Anti-Overengineering-
Entscheidung, siehe Nachtrag 6 im Migrationsplan). Damit weicht dieser
Schritt bewusst vom ursprünglich in der Zieldoku skizzierten
4-Funktionen-`browser_service` ab.

```text
NavidromeAPI (unverändert, bereits sauber)
        ↓
services/navidrome/browser_service.py  (✅ IMPLEMENTIERT, reduziert —
        NUR get_albums_page(); Artists/Genres bewusst nicht extrahiert,
        siehe Nachtrag oben)
        ↓
handlers/menu/actions/navidrome.py  (bleibt dünn, unverändert strukturell)
        ↓
handlers/navidrome_renderer.py (✅ IMPLEMENTIERT — alle 5 Detail-Views
        [Artist/Album/Song/Playlist/Genre] + Browse: Artists/Albums/
        Genres [Stufe 3]) — MarkdownV2-Text-/Keyboard-Bau, analog zur
        bestehenden Trennung rendering.py (Menü) vs. definitions.py
        ↓
NavidromeMenuHandler (schlanker: nur noch Orchestrierung +
        Fehlerbehandlung + browse_states)
```

**Anti-Overengineering-Bewertung:** eine vollständige 7-Service-Aufteilung
(`browser/search/playlists/favorites/queue/discovery/metadata`) ist
**aktuell nicht gerechtfertigt** (die meisten Domänen haben 0-1 Methoden
— „ONE FILE PER FUNCTION"). Search/Favorites/Playlists bleiben **KEEP**
als Methoden auf `NavidromeMenuHandler`, bis ihr Umfang wächst (z. B.
durch Playlist-CRUD, aktuell nicht geplant).

**Empfohlenes Zielmenü** (minimal-invasiv, kein Big-Bang):

```text
🎵 Navidrome Mediathek
├── 🔍 Durchsuchen (unverändert)
├── 🔎 Suchen (unverändert)
├── 📋 Meine Playlists  ← ✅ CLOSED (NAV-F4): Duplikat nav_browse_playlists
│   │                       entfernt, nav_playlists bleibt
│   └── [Playlist-Detail — ✅ CLOSED (NAV-F5): getPlaylist implementiert]
├── 💿 Album-/🎵 Song-Detail  ← ✅ CLOSED (NAV-F9): erreichbar aus
│   Durchsuchen/Suche/Favoriten/Genre-Detail, kein eigener Menüpunkt nötig
├── ⭐ Favoriten (unverändert)
├── 🕐 Zuletzt gespielt (unverändert, nur reply_markup-Nachtrag NAV-F10)
├── 🎭 Genre-Suche/-Stats  ← ✅ CLOSED (NAV-F7/NAV-F8): Inline-Buttons in
│   Durchsuchen → Genres, kein eigener Menüpunkt nötig
├── 🎵 Entdecken  ← ✅ CLOSED (NAV-F17): "nav_discover"-MenuItem als
│   │                 Einstieg, die beiden Optionen darunter sind reine
│   │                 Inline-Buttons (kein eigenes MenuItem je Option)
│   ├── 🎲 Zufällige Songs (getRandomSongs)
│   └── 🆕 Neue Alben (getAlbumList2 type=newest)
│       (🔥 Top Songs je Künstler: getTopSongs — abweichend von dieser
│        ursprünglichen Skizze als Button in der Artist-Detail-Ansicht
│        umgesetzt statt als drittem Entdecken-Punkt, siehe Abschnitt 4)
└── 📊 Statistiken (unverändert, Cross-Link)
```

Explizit **NO CHANGE** gegenüber dem im Audit geprüften Vorschlag: keine
„⭐ Meine Musik"-Gruppierungsebene (würde Favoriten/Zuletzt-gespielt
künstlich bündeln, ohne dass Bewertungen fachlich existieren), kein
„▶️ Player/Queue" (kein bestehender Playback-Kontext im Bot), keine
Verschiebung von Serverstatus/Scan aus dem Admin-Bereich hierher.

---

## 6. Migrationsreihenfolge (P1 ff., noch nicht freigegeben)

1. ~~NAV-F1~~ ✅ CLOSED
2. ~~NAV-F2~~ ✅ CLOSED
3. ~~NAV-F10~~ ✅ CLOSED — `reply_markup` für `handle_last_played()` nachgezogen (ARCH-029-Muster wiederverwendet: `RichMenuSystem.get_result_navigation("nav_recent")` → `handlers/menu/actions/navidrome.py::handle_recent()` → `StatistikHandler.handle_last_played(reply_markup=...)`)
4. ~~NAV-F6~~ ✅ CLOSED — `handle_reconnect()` nutzt jetzt einen echten `await NavidromeAPI.check_connection()` (`ping`), bevor Erfolg gemeldet wird; schlägt der Ping fehl, wird `connection_status` zurückgesetzt. Der schnelle lokale `_check_connection()`-Vorab-Check vor den übrigen 8 Browse-/Such-Methoden bleibt bewusst unverändert (kein `ping` vor jedem Klick)
5. ~~NAV-F9~~ ✅ CLOSED — `handle_album_detail()`/`handle_song_detail()` implementiert (`getAlbum`/`getSong` via `make_request`, analog zu `handle_artist_detail()`/`handle_genre_detail()`), Dispatcher-Zweige für `nav_album_`/`nav_song_` auf echte Handler umgestellt. Tracklist bewusst auf 25 Songs gedeckelt (keine neue Pagination-Button-Fehlerquelle).
6. ~~NAV-F11~~ ✅ CLOSED (neuer Fund, entdeckt bei NAV-F9) — `nav_artist_albums_all_<id>` wurde vom generischen `nav_artist_`-Präfix fehlerhaft abgefangen (derselbe Bug-Typ wie NAV-F2); eigener Zweig vor dem generischen Check ergänzt.
7. ~~NAV-F3~~ ✅ CLOSED — toten `handle_stats()`-Code + zugehörigen Test entfernt (triple-grep-verifiziert unerreichbar: keine Aufrufer in `handlers/`, `handlers/menu/`, `tests/`)
8. ~~NAV-F4/NAV-F5~~ ✅ CLOSED — Playlist-Duplikat gemergt (`nav_playlists` bleibt, `nav_browse_playlists`-MenuItem/-Wrapper/-Action entfernt), `handle_playlist_detail()` implementiert (`getPlaylist` via `make_request`, analog `handle_album_detail()`), Dispatcher-Zweig `nav_playlist_` ergänzt
9. ~~NAV-F7/NAV-F8/NAV-F12~~ ✅ CLOSED — Genre-Suche (`nav_search_genres`, Teilstring-Filter über `getGenres()`) + Genre-Statistik (`nav_genre_stats`, `StatisticsCalculator.generate_genre_stats()`, All-Time Top-10 nach Plays, reine Wiederverwendung des bestehenden Statistics-/Scrobble-Systems inkl. additiver `"genres"`-Erfassung — strukturierte Liste, bevorzugte Datenquelle, siehe NAV-F8 in Abschnitt 4 — in `PlayHistoryPoller`, plus notwendiger `NavidromeAPI.get_now_playing()`-Pass-Through-Fix, ohne den die Erfassung nie befüllt worden wäre) implementiert; dabei NAV-F12 entdeckt+behoben (`nav_genre_stats` kollidierte mit dem generischen `nav_genre_`-Präfix, derselbe Bug-Typ wie NAV-F2/NAV-F11)
10. ~~NAV-F13~~ ✅ CLOSED (Live-Fund aus Produktionslogs) — statischer, unescapter `"(erste 10 angezeigt)"`-Text in `handle_genre_detail()` ließ Telegram jede erfolgreiche Genre-Detail-Nachricht ablehnen; Fix: `\\(erste 10 angezeigt\\)`
11. ~~Renderer-Extraktion, Stufe 1 (Detail: Album/Song/Playlist)~~ ✅ IMPLEMENTED (2026-09-13) — `handlers/navidrome_renderer.py` neu, siehe Abschnitt 5.
12. ~~Renderer-Extraktion, Stufe 3 (Browse: Artists/Albums/Genres)~~ ✅ IMPLEMENTED (2026-09-13) — vorbereitet durch eigene Characterization-Test-PR + separat behobenes NAV-F14, dann Extraktion in einem dritten PR. `NavidromeMenuHandler` 1493→1179 Zeilen.
13. ~~Detail-View-Familie vervollständigen (Artist/Genre-Detail)~~ ✅ IMPLEMENTED (2026-09-13) — `render_artist_detail()`/`render_genre_detail()` neu, Pflichtschritt (fehlende Erfolgspfad-/Overflow-/Connection-Error-Tests) + Extraktion in einem PR. Alle 5 Detail-Views konsistent im Renderer. `NavidromeMenuHandler` 1179→1059 Zeilen.
14. ~~Restliche Testlücken geschlossen (Playlists/Favoriten/Such-Erfolgspfad)~~ ✅ IMPLEMENTED (2026-09-13) — reine Testergänzung, kein Produktionscode geändert. 9 neue Tests.
15. ~~Stufe 4, reduziert (`services/navidrome/browser_service.py`)~~ ✅ IMPLEMENTED (2026-09-13) — bewusst nur `get_albums_page()` (einzige Browse-Methode mit echter Verzweigungslogik), Artists/Genres bewusst unangetastet gelassen (Anti-Overengineering-Entscheidung). Stufe 5 (finale Orchestrierungs-Schlankung) — siehe `docs/audits/NAVIDROME_MENU_HANDLER_REFACTORING_MIGRATION_PLAN_2026-09-13.md` — noch nicht freigegeben, aktuell auch kein erkennbarer Zusatznutzen mehr (`NavidromeMenuHandler` ist bereits reine Orchestrierung).
16. ~~NAV-F17~~ ✅ CLOSED (2026-09-14) — Discovery-Erweiterung: neues Menü „🎵 Entdecken" (`nav_discover`), `render_discover_menu()`/`render_random_songs()`/`render_top_songs()`/`render_newest_albums()` in `handlers/navidrome_renderer.py`, `handle_discover_menu()`/`handle_random_songs()`/`handle_top_songs()`/`handle_newest_albums()` in `NavidromeMenuHandler`. „Top Songs je Künstler" als Button in `render_artist_detail()` statt eigenem Menüpunkt (Nutzerentscheidung, siehe Abschnitt 4).
17. ~~NAV-F18~~ ✅ CLOSED (2026-09-14) — Playlist-CRUD: `handle_playlist_create_prompt()`/`process_playlist_name()`/`handle_playlist_rename_prompt()`/`process_playlist_rename()`/`handle_playlist_delete_confirm()`/`handle_playlist_delete_execute()` in `NavidromeMenuHandler`, „➕ Neue Playlist"-Button in `handle_my_playlists()`, „✏️ Umbenennen"/„🗑️ Löschen"-Buttons in `render_playlist_detail()`. Freitext-Workflows (Name-Eingabe) über dasselbe `browse_states`-Flag-Muster wie die bestehende Suche, verdrahtet in `rich_menu_handler.py::handle_text_message()`.

**Damit ist der Migrationsplan vollständig abgeschlossen — keine offenen NAV-Findings mehr.**

Jeder Schritt: eigener Branch/PR, volle Regressionsprüfung, keine
gleichzeitige Bearbeitung mehrerer Schritte (CLAUDE.md Abschnitt 18).

---

## 7. Tests

| Bereich | Datei | Umfang |
|---|---|---|
| `NavidromeMenuHandler` (Connection-Status, Escaping, Error-Routing, alle 5 Detail-Views, Browse, Playlists, Favoriten, Suche, Genre-Suche, NAV-F1, NAV-F6, NAV-F9, NAV-F7, NAV-F13) | `tests/test_navidrome_menu_handler.py` | 73 Tests (BUG-007a/b, NAV-F1, NAV-F2, NAV-F6, NAV-F9, NAV-F7, NAV-F13; toter Test zu `handle_stats()` mit NAV-F3 entfernt; `TestFormatTrackDuration` nach `test_navidrome_renderer.py` verschoben; Erfolgspfad-/Overflow-/Connection-Error-Tests für Artist-/Genre-Detail, alle drei Browse-Methoden, Playlists, Favoriten und den generischen Such-Erfolgspfad ergänzt — Architecture Refactoring Audit) |
| `handlers/navidrome_renderer.py` (reine Render-Funktionen, Architecture Refactoring Audit Stufe 1 + 3 + Detail-View-Familie, NAV-F15/F16) | `tests/test_navidrome_renderer.py` | 34 Tests (ohne Mocks, reine Funktionsaufrufe; 8 neu für Artist-/Genre-Detail, 1 neu für NAV-F16) |
| `handlers/menu/actions/navidrome.py`-Wrapper + interner Dispatcher (NAV-F9, NAV-F10, NAV-F11, NAV-F5, NAV-F7, NAV-F8, NAV-F12) | `tests/test_menu_actions_navidrome.py` | 20 Tests |
| `NavidromeAPI`-Adapter (Logging, Timeout, Characterization, NAV-F8 `genre`/`genres`-Passthrough) | `tests/test_navidrome_api_characterization.py`, `tests/test_navidrome_api_logging.py`, `tests/test_navidrome_api_timeout.py` | `test_navidrome_api_characterization.py` 15 Tests (2 neu für NAV-F8), übrige siehe dort |
| Result-Navigation End-to-End (ARCH-029-Muster, NAV-F10) | `tests/test_menu_navigation_continuity.py::TestLastPlayedResultNavigationEndToEndNavF10` | 2 Tests |
| `handle_last_played()` `reply_markup`-Passthrough (NAV-F10) | `tests/test_mugge_statistik_handler.py::TestHandleLastPlayed` | 1 Test |
| `handle_genre_stats()` (NAV-F8) | `tests/test_mugge_statistik_handler.py::TestHandleGenreStats` | 4 Tests |
| `StatisticsCalculator.generate_genre_stats()` (NAV-F8, strukturiertes `genres`-Feld inkl. Multi-Genre/Dedup-Semantik) | `tests/test_statistics_calculator.py::TestGenerateGenreStats` | 9 Tests |
| `StatistikService.generate_genre_stats()`-Delegator (NAV-F8) | `tests/test_statistik_service.py::TestGenerateGenreStats` | 2 Tests |
| `PlayHistoryPoller`-Genre-Erfassung (NAV-F8, `genre` + strukturiertes `genres` inkl. Dedup/Malformed-Handling) | `tests/test_play_history_poller.py` | 15 Tests (7 neu für NAV-F8) |
| `services/navidrome/browser_service.py::get_albums_page()` (Architecture Refactoring Audit Stufe 4) | `tests/test_navidrome_browser_service.py` | 5 Tests (ohne Telegram-Bezug, `navidrome_api` gemockt) |

**Frühere Testlücken, inzwischen geschlossen:** `handle_browse_artists`/
`handle_browse_albums`/`handle_browse_genres` sind seit dem Architecture
Refactoring Audit (Migrationsstufe 3, Pflichtschritt vor der eigentlichen
Extraktion) durch `TestBrowseArtistsCharacterization`/
`TestBrowseAlbumsCharacterization`/`TestBrowseGenresCharacterization` in
`tests/test_navidrome_menu_handler.py` abgedeckt (17 neue Tests) — dabei
NAV-F14 entdeckt und CLOSED (siehe Abschnitt 4). `handle_my_playlists`/
`handle_favorites` (Erfolgsfall, leere Liste, Connection-Error) sowie
`process_search_query`s generischer `search3`-Ergebnispfad (vorher nur
über Fehlerpfad-Tests indirekt abgedeckt) sind seit einem weiteren
Nachtrag durch `TestMyPlaylistsCharacterization`/
`TestFavoritesCharacterization`/`TestSearchQueryGenericPathCharacterization`
abgedeckt (9 neue Tests) — kein bisher unentdeckter Bug aufgedeckt.

**Verbleibende, bewusst zurückgestellte Lücke:** kein dedizierter
Test für `handle_reconnect()`-Erfolgsfall gegen eine ECHTE
`NavidromeAPI.check_connection()`-Implementierung (nur gegen eine
gemockte Version, korrekt nach CLAUDE.md Regel 7). Die reale
`check_connection()`-Logik selbst ist bereits vollständig in
`tests/test_navidrome_api_characterization.py::TestCheckConnection`
charakterisiert (Ping-Erfolg/-Fehlschlag/Exception) — die Kombination
beider Testsuiten deckt den End-to-End-Pfad bereits ab, ein
zusätzlicher Integrationstest würde nur Regel-7-widrig echten
Netzwerkcode in einem Unit-Test duplizieren. Keine akute Priorität.

---

## 8. Offene Punkte

**Alle 18 Findings dieses Dokuments (NAV-F1–NAV-F18) sind CLOSED.**
Keine offenen Navidrome-Menu-Findings mehr. Bewusst zurückgestellte,
nicht in Findings-Form gegossene Restlücken (kein Bug, keine aktuelle
Priorität):

- Kein dedizierter End-to-End-Test für `handle_reconnect()` gegen eine
  echte `NavidromeAPI.check_connection()`-Implementierung (siehe
  Abschnitt 7).
- Playlist-CRUD (NAV-F18) beschränkt sich bewusst auf Name/Umbenennen/
  Löschen — „Songs zu einer Playlist hinzufügen/entfernen" (bräuchte
  einen im Bot aktuell nirgends vorhandenen Mehrfachauswahl-Song-Picker)
  bleibt ein eigener, separater Folge-Scope ohne aktuellen Auftrag.

- Testlücken aus Abschnitt 7 — nur noch `handle_reconnect()`-Erfolgsfall
  gegen eine echte `check_connection()`, bewusst zurückgestellt (keine
  akute Priorität, siehe Begründung dort).
- Zielarchitektur aus Abschnitt 5: Renderer-Extraktion Stufe 1 (Album/
  Song/Playlist-Detail), Stufe 3 (Browse: Artists/Albums/Genres), die
  Detail-View-Familien-Vervollständigung (Artist-/Genre-Detail) UND
  Stufe 4 (`services/navidrome/browser_service.py`, bewusst reduziert
  auf `get_albums_page()`) sind IMPLEMENTED. Finale Orchestrierungs-
  Schlankung (Stufe 5) bleibt unumgesetzt — aktuell kein erkennbarer
  Zusatznutzen, `NavidromeMenuHandler` ist bereits reine Orchestrierung.
