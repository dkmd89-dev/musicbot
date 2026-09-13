# Navidrome Menu System — API Capability & Architecture

**Status:** CURRENT (lebendes Dokument). Entstanden aus dem read-only
„MASTER PHASE — NAVIDROME MENU SYSTEM"-Audit (2026-09-13). P0-Findings
(NAV-F1/NAV-F2) und NAV-F10 sind CLOSED; NAV-F3–F9 bleiben offen/geplant.
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

**Zwei nicht deckungsgleiche „Connection-Check"-Konzepte:**
`enhanced_status_handler.py` (Admin-Diagnose) nutzt den echten
`NavidromeAPI.check_connection()` (`ping`-Request). Der User-facing
Navidrome-Bereich (`NavidromeMenuHandler._check_connection()`) prüft
dagegen nur, ob `NAVIDROME_URL`/`NAVIDROME_USER` nicht-leer sind (BUG-007a,
bereits gefixt) — **niemals** einen echten `ping`. „🔄 Erneut versuchen"
(`nav_reconnect`) testet dadurch keine echte Konnektivität. Bewusst als
kleinerer, bereits im Code dokumentierter Teil-Fix belassen (ein voller
async-Umbau auf den echten Connection-Test ist größer und wurde
zurückgestellt) — siehe NAV-F6 unten.

---

## 2. Aktuelle Menüstruktur

```text
🎵 Navidrome Mediathek (id="navidrome", USER-Level, ungegated)
├── 🔍 Durchsuchen (reiner Container)
│   ├── 🎤 Künstler       nav_browse_artists    — IMPLEMENTED
│   ├── 💿 Alben          nav_browse_albums     — IMPLEMENTED
│   ├── 🎭 Genres         nav_browse_genres     — IMPLEMENTED
│   └── 📋 Playlists      nav_browse_playlists  — STUB (siehe NAV-F4)
├── 🔎 Suchen (reiner Container)
│   ├── 🔍 Überall        nav_search            — IMPLEMENTED
│   ├── 🎤 Künstler       nav_search_artists    — IMPLEMENTED
│   ├── 💿 Alben          nav_search_albums     — IMPLEMENTED
│   └── 🎵 Songs          nav_search_songs      — IMPLEMENTED
├── 📋 Meine Playlists    nav_playlists         — IMPLEMENTED (≠ nav_browse_playlists, NAV-F4)
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
  Statistik-Versuch) existiert zwar noch im Code, ist aber **vollständig
  unerreichbar** (kein Menüpunkt zeigt darauf) — siehe NAV-F3.

---

## 3. API Capability Matrix (Kurzfassung)

Vollständige Dreispalten-Matrix (Navidrome-Fakt / Codebefund / Bewertung)
mit allen 33 geprüften Subsonic-Capabilities: siehe Audit-Transkript
(Session vom 2026-09-13). Kurzfassung:

| Bereich | Implementiert & erreichbar | Implementiert, aber unerreichbar | Fehlt vollständig |
|---|---|---|---|
| Browsing | `getArtists`, `getArtist`, `getAlbumList2` (nur `alphabeticalByArtist`), `getGenres`, `getSongsByGenre` | `getIndexes` (NAV-F3) | `getMusicFolders`, `getMusicDirectory`, `getArtistInfo(2)`, `getAlbumInfo(2)`, `getTopSongs`, `getSimilarSongs(2)` |
| Album/Song-Listen | — | — | `getAlbumList` (v1), `getRandomSongs`, weitere `getAlbumList2`-Typen |
| Suche | `search3` | — | `search2` |
| Playlists | `getPlaylists` (nur Liste) | — | `getPlaylist` (Detail), `createPlaylist`/`updatePlaylist`/`deletePlaylist` |
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
| NAV-F3 | `NavidromeMenuHandler.handle_stats()` (getIndexes-basiert) ist unerreichbar (kein Menüpunkt; `nav_link_stats` verlinkt stattdessen korrekt auf die Personal-Statistics-Domain) — toter Code inkl. eigenem Test für unerreichbaren Pfad. | DEAD_ROUTE | P2 | OPEN |
| NAV-F4 | `nav_browse_playlists` (unter „Durchsuchen", STUB) vs. `nav_playlists` („Meine Playlists", Top-Level, real) — zwei Menüpunkte für dasselbe Konzept. | DUPLICATE | P1 | OPEN |
| NAV-F5 | `nav_playlist_<id>`-Buttons werden in `handle_my_playlists()` erzeugt, aber es existiert kein Dispatcher-Zweig dafür (fällt auf generisches „Funktion nicht implementiert"). | DEAD_ROUTE | P1 | OPEN |
| NAV-F6 | `_check_connection()`/`handle_reconnect()` prüfen nie den echten `NavidromeAPI.check_connection()` (`ping`), nur lokale Config-Präsenz — abweichend von `enhanced_status_handler.py`, das den echten Ping bereits nutzt. | ARCHITECTURE_VIOLATION | P1 | OPEN |
| NAV-F7 | `nav_search_genres` — STUB. | — | P3 | OPEN |
| NAV-F8 | `nav_genre_stats` — STUB. | — | P3 | OPEN |
| NAV-F9 | `nav_album_<id>`/`nav_song_<id>` Detailansichten — STUB, obwohl an 6 Stellen im Code bereits verlinkt (`getAlbum`/`getSong` nicht implementiert). | — | **P1** | OPEN |
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
durch Playlist-CRUD, siehe NAV-F4/F5).

**Empfohlenes Zielmenü** (minimal-invasiv, kein Big-Bang):

```text
🎵 Navidrome Mediathek
├── 🔍 Durchsuchen (unverändert)
├── 🔎 Suchen (unverändert)
├── 📋 Playlists  ← MERGE aus nav_browse_playlists + nav_playlists (NAV-F4)
│   └── [Playlist-Detail — NEU, schließt NAV-F5]
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
4. NAV-F6 — echten `NavidromeAPI.check_connection()` in `_check_connection()`/`handle_reconnect()` nutzen
5. NAV-F4/NAV-F5 — Playlist-Duplikat mergen, `getPlaylist`-Client-Methode + Dispatcher-Zweig ergänzen
6. NAV-F9 — `getAlbum`/`getSong`-Client-Methoden + Detail-Rendering
7. NAV-F3 — toten `handle_stats()`-Code + zugehörigen Test entfernen
8. Renderer-Extraktion (`navidrome_renderer.py`)
9. Discovery-Erweiterung (`getRandomSongs`/`getTopSongs`/weitere `getAlbumList2`-Typen)

Jeder Schritt: eigener Branch/PR, volle Regressionsprüfung, keine
gleichzeitige Bearbeitung mehrerer Schritte (CLAUDE.md Abschnitt 18).

---

## 7. Tests

| Bereich | Datei | Umfang |
|---|---|---|
| `NavidromeMenuHandler` (Connection-Status, Escaping, Error-Routing, NAV-F1) | `tests/test_navidrome_menu_handler.py` | 29 Tests (BUG-007a/b, NAV-F1, NAV-F2) |
| `handlers/menu/actions/navidrome.py`-Wrapper + interner Dispatcher (NAV-F10) | `tests/test_menu_actions_navidrome.py` | 11 Tests |
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

- NAV-F3 bis NAV-F10 (siehe Abschnitt 4) — Umsetzung erst nach expliziter
  Freigabe je Schritt (CLAUDE.md Abschnitt 18: kein großer Refactor als
  erste Reaktion).
- Übernahme von NAV-F3–F10 nach `docs/FINDINGS_INDEX.md` als eigene
  Zeilen steht noch aus.
- Testlücken aus Abschnitt 7 — Priorität analog zur jeweiligen
  Implementierungs-Priorität in Abschnitt 4.
