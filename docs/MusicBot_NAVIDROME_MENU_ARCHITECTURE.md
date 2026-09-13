# Navidrome Menu System — API Capability & Architecture

**Status:** CURRENT (lebendes Dokument). Entstanden aus dem read-only
„MASTER PHASE — NAVIDROME MENU SYSTEM"-Audit (2026-09-13). P0-Findings
(NAV-F1/NAV-F2), NAV-F10, NAV-F6, NAV-F9, NAV-F11 und NAV-F3 sind CLOSED;
NAV-F4/NAV-F5 sind ebenfalls CLOSED; NAV-F7/F8 bleiben offen/geplant.
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
│   └── 🎵 Songs          nav_search_songs      — IMPLEMENTED
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

---

## 3. API Capability Matrix (Kurzfassung)

Vollständige Dreispalten-Matrix (Navidrome-Fakt / Codebefund / Bewertung)
mit allen 33 geprüften Subsonic-Capabilities: siehe Audit-Transkript
(Session vom 2026-09-13). Kurzfassung:

| Bereich | Implementiert & erreichbar | Implementiert, aber unerreichbar | Fehlt vollständig |
|---|---|---|---|
| Browsing | `getArtists`, `getArtist`, `getAlbumList2` (nur `alphabeticalByArtist`), `getGenres`, `getSongsByGenre` | — | `getMusicFolders`, `getMusicDirectory`, `getArtistInfo(2)`, `getAlbumInfo(2)`, `getTopSongs`, `getSimilarSongs(2)`, `getIndexes` (unbenutzt seit NAV-F3) |
| Album/Song-Detail | `getAlbum`, `getSong` (NAV-F9, CLOSED) | — | — |
| Album/Song-Listen | — | — | `getAlbumList` (v1), `getRandomSongs`, weitere `getAlbumList2`-Typen |
| Suche | `search3` | — | `search2` |
| Playlists | `getPlaylists` (Liste), `getPlaylist` (Detail, NAV-F5, CLOSED) | — | `createPlaylist`/`updatePlaylist`/`deletePlaylist` |
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
| NAV-F7 | `nav_search_genres` — STUB. | — | P3 | OPEN |
| NAV-F8 | `nav_genre_stats` — STUB. | — | P3 | OPEN |
| NAV-F9 | `nav_album_<id>`/`nav_song_<id>` Detailansichten — STUB, obwohl an 6 Stellen im Code bereits verlinkt (`getAlbum`/`getSong` nicht implementiert). | — | **P1** | **CLOSED** (2026-09-13) |
| NAV-F11 | `nav_artist_albums_all_<id>` (Button „➕ N weitere Alben" in `handle_artist_detail()`) wurde vom generischen `nav_artist_`-Präfix-Zweig fehlerhaft abgefangen, lieferte korrupten Artist-Namen an `handle_artist_detail()` — derselbe Bug-Typ wie NAV-F2, entdeckt bei der NAV-F9-Umsetzung. | BROKEN | P0 | **CLOSED** (2026-09-13) |
| NAV-F10 | `StatistikHandler.handle_last_played()` (erreicht über `nav_recent`) hatte kein `reply_markup` — in der ARCH-029-Phase („Menu Navigation Continuity") übersehen, da die Methode über `nav_recent`, nicht über eine `stats_*`-ID erreichbar ist. | Navigation-Gap (ARCH-029-Nachtrag) | P1 | **CLOSED** (2026-09-13) |

Vollständige Details/Codebelege zu NAV-F3–F10: Audit-Transkript
(Session vom 2026-09-13); Übernahme nach `docs/FINDINGS_INDEX.md` steht
noch aus (siehe Offene Punkte).

---

## 5. Zielarchitektur (P2/P3, geplant, noch nicht umgesetzt)

```text
NavidromeAPI (unverändert, bereits sauber)
        ↓
services/navidrome/browser_service.py  (NEU, P2) — Artists/Albums/Genres/
        Songs-by-Genre-Datenextraktion (teilen bereits denselben
        Pagination-Stil)
        ↓
handlers/menu/actions/navidrome.py  (bleibt dünn, unverändert strukturell)
        ↓
handlers/navidrome_renderer.py (NEU, P2) — MarkdownV2-Text-/Keyboard-Bau,
        analog zur bestehenden Trennung rendering.py (Menü) vs.
        definitions.py
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
├── 🎵 Entdecken  ← NEU (P2, nach den P1-Fixes)
│   ├── 🎲 Zufällige Songs (getRandomSongs)
│   ├── 🔥 Top Songs je Künstler (getTopSongs)
│   └── 🆕 Neue Alben (getAlbumList2 type=newest)
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
9. Renderer-Extraktion (`navidrome_renderer.py`)
10. Discovery-Erweiterung (`getRandomSongs`/`getTopSongs`/weitere `getAlbumList2`-Typen)

Jeder Schritt: eigener Branch/PR, volle Regressionsprüfung, keine
gleichzeitige Bearbeitung mehrerer Schritte (CLAUDE.md Abschnitt 18).

---

## 7. Tests

| Bereich | Datei | Umfang |
|---|---|---|
| `NavidromeMenuHandler` (Connection-Status, Escaping, Error-Routing, Album-/Song-/Playlist-Detail, NAV-F1, NAV-F6, NAV-F9) | `tests/test_navidrome_menu_handler.py` | 33 Tests (BUG-007a/b, NAV-F1, NAV-F2, NAV-F6, NAV-F9; toter Test zu `handle_stats()` mit NAV-F3 entfernt; `handle_playlist_detail()` nur indirekt über den Dispatcher-Test in `test_menu_actions_navidrome.py` abgedeckt, kein eigener Unit-Test) |
| `handlers/menu/actions/navidrome.py`-Wrapper + interner Dispatcher (NAV-F9, NAV-F10, NAV-F11, NAV-F5) | `tests/test_menu_actions_navidrome.py` | 16 Tests (toter `handle_browse_playlists`-Test mit NAV-F4 entfernt, 2 neue NAV-F5-Dispatcher-Tests) |
| `NavidromeAPI`-Adapter (Logging, Timeout, Characterization) | `tests/test_navidrome_api_characterization.py`, `tests/test_navidrome_api_logging.py`, `tests/test_navidrome_api_timeout.py` | siehe dort |
| Result-Navigation End-to-End (ARCH-029-Muster, NAV-F10) | `tests/test_menu_navigation_continuity.py::TestLastPlayedResultNavigationEndToEndNavF10` | 2 Tests |
| `handle_last_played()` `reply_markup`-Passthrough (NAV-F10) | `tests/test_mugge_statistik_handler.py::TestHandleLastPlayed` | 1 neuer Test |

**Bekannte Testlücken** (Details: Audit-Transkript): keine Verhaltenstests
für `handle_browse_albums`/`handle_browse_genres`/`handle_my_playlists`/
`handle_favorites` (Erfolgsfall, Pagination, leere Liste), keine Tests für
`process_search_query`-Ergebnisverarbeitung, kein Test für
`handle_reconnect()`-Erfolgsfall gegen einen echten `check_connection()`.

---

## 8. Offene Punkte

- NAV-F7/F8 (siehe Abschnitt 4) — Umsetzung erst nach expliziter
  Freigabe je Schritt (CLAUDE.md Abschnitt 18: kein großer Refactor als
  erste Reaktion).
- Testlücken aus Abschnitt 7 — Priorität analog zur jeweiligen
  Implementierungs-Priorität in Abschnitt 4.
