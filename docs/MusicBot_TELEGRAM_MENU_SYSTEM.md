# MusicBot – Telegram Inline-Menü-System

**Dokument:** `MusicBot_TELEGRAM_MENU_SYSTEM.md`
**Status:** CURRENT (lebendes Dokument, wird bei jeder weiteren Menü-Erweiterung
aktualisiert)
**Scope:** `handlers/menu/rich_menu_system.py`,
`handlers/menu/rich_menu_handler.py` und ihre unmittelbaren Kollaborateure
**Zweck:** zentrale Referenz — welche Menüs/Buttons existieren, was davon
fertig integriert ist, was noch offen/geplant ist, und nach welchem Muster
künftige Menü-Erweiterungen eingebaut werden.

---

## 1. Architektur in Kürze

```text
Telegram-Update (Message oder CallbackQuery)
   ↓
bot.py / TelegramBot          (Application, registriert Handler)
   ↓
RichMenuHandler                (klassen-artige Orchestrierung, konstruiert
   ↓                            DownloadHandler, hält ActiveDownloadRegistry)
RichMenuSystem                 (Menübaum, Rendering, Callback-Dispatch)
   ↓
MenuItem-Baum / Handler-Methoden (_handle_*)
```

**Zwei getrennte Routing-Ebenen — beide müssen bei einem neuen
Callback-Präfix aktualisiert werden (Bug B, siehe Abschnitt 5):**

1. **PTB-Ebene** (`RichMenuHandler.get_telegram_handlers()`): registriert pro
   Präfix einen eigenen `CallbackQueryHandler(..., pattern="^<präfix>:")`.
   Für Callback-Daten ohne passenden Pattern-Match liefert PTB **keinen
   Fehler und kein Log** — der Klick verpufft stillschweigend. Jeder neue
   Präfix (`menu:`, `dup:`, `backup_`, `status_`, `restart:`, `dl:`, …)
   braucht hier eine eigene Zeile.
2. **`RichMenuSystem.handle_callback()`-Ebene**: interner
   `if callback_data.startswith("<präfix>:")`-Dispatch auf die konkrete
   `_handle_*`-Methode. Nur relevant, wenn die PTB-Ebene den Callback
   überhaupt zugestellt hat.

**Admin-Gating:** `_ADMIN_ONLY_PREFIXES` in `RichMenuSystem` listet
Präfixe, die nur für admin-berechtigte Chats geroutet werden. `dl:` steht
bewusst **nicht** in dieser Liste (Downloads sind eine Nutzerfunktion, keine
Admin-Funktion).

**Menü-Definition:** `RichMenuSystem.initialize_menu_structure()` baut einen
`MenuItem`-Baum (Titel, `id`, Kinder, optional `handler=`/`is_action=True`
für Blätter mit eigener Aktion statt reinem Untermenü-Rendering).

### 1a. Interne Modulstruktur von `handlers/menu/` (seit ARCH-024/ARCH-025, COMPLETE)

Die beiden Kerndateien sind seit `ARCH-024`
([`MusicBot_ARCH-024_Menu_File_Decomposition.md`](MusicBot_ARCH-024_Menu_File_Decomposition.md))
und `ARCH-025`
([`MusicBot_ARCH-025_Command_Help_Content_Decomposition.md`](MusicBot_ARCH-025_Command_Help_Content_Decomposition.md))
in kohäsive Module aufgeteilt — die obige Zwei-Ebenen-Routing-Beschreibung
und der Menübaum in Abschnitt 2 bleiben davon unberührt (reine interne
Umstrukturierung, keine Verhaltensänderung, alle bisherigen öffentlichen/
privaten Methodennamen auf `RichMenuSystem`/`RichMenuHandler` bleiben als
dünne Delegatoren erhalten):

```text
bot.py
  ↓
RichMenuHandler        Composition Root, Lifecycle, dünne Command-
                        Adapter (/start, /menu, /help → je Maintenance-
                        Gate + Activity-Tracking + 1 Delegationsaufruf),
                        Download-Pipeline-Einstieg
  (initialize(), get_telegram_handlers(), Setter, cleanup())
  ├── content/            /start-/Help-Content, zustandslose Funktionen
  │   ├── user_context.py     FEATURES-Katalog + Rollen-/Neuling-
  │   │                       Ermittlung (get_user_role()/
  │   │                       get_available_features()/is_new_user()/
  │   │                       get_user_info()/load_user_data())
  │   ├── greeting.py          send_start_message() — /start-Begrüßung
  │   │                        (Orchestrierung, Texte aus messages.py)
  │   ├── help.py              send_help_message()/
  │   │                        send_help_callback_response() +
  │   │                        get_download_help()/get_stats_help()/
  │   │                        get_navidrome_help()/get_admin_help()
  │   │                        (dünne Wrapper, Texte aus messages.py)
  │   └── messages.py          statischer UI-Content (ARCH-025 Content-
  │                            Separation-Closure): Begrüßungs-/
  │                            Hilfetexte + mehrfach verwendete Button-
  │                            Labels als reine String-Konstanten, keine
  │                            Abhängigkeit auf RichMenuHandler/
  │                            RichMenuSystem/actions
  ↓
RichMenuSystem          zentraler Callback-Router
  (handle_callback(): _ADMIN_ONLY_PREFIXES-Gate + Menu-Fallback-Gate;
   Composition-Setter; dünne Action-Delegatoren; Session-/Permission-
   Delegates; menu:back/menu:close; Registry-Lookup)
  ├── definitions.py    Menübaum-Aufbau (build_menu_tree()) + Registry
  │                     (populate_registry()) — einzige Ausnahme von der
  │                     Rückreferenz-Regel: nimmt die RichMenuSystem-
  │                     Instanz entgegen, da MenuItem.handler-Bindungen
  │                     auf deren dünne Delegatoren zeigen
  ├── rendering.py       render_menu()/get_menu_text()/show_menu() —
  │                     reine Darstellung, keine Permission-/Business-Logik
  ├── actions/           9 fachliche Domänen-Module, zustandslose
  │   ├── family.py           Funktionen mit explizit übergebenen
  │   ├── duplicates.py       Abhängigkeiten (keine Rückreferenz auf
  │   ├── navidrome.py        RichMenuSystem/RichMenuHandler):
  │   ├── stats.py
  │   ├── admin_diagnostics.py   (Logger/Status/ErrorAdmin/System-Logs —
  │   │                           entspricht "🩺 Diagnose & Monitoring")
  │   ├── usermgmt.py
  │   ├── library.py             (Reprocessing/Doctor/Review/Repair —
  │   │                           entspricht "🎵 Bibliothek & Navidrome")
  │   ├── admin_operations.py    (Backup/Neustart/Wartungsmodus/
  │   │                           Navidrome-Scan — entspricht
  │   │                           "🤖 Bot & Betrieb")
  │   └── download.py            (Download-Control-Center + Pipeline-
  │                               Logik — einzige Domäne, die sowohl
  │                               RichMenuSystem als auch RichMenuHandler
  │                               betrifft)
  ├── permissions.py     is_admin_or_owner()/get_user_access_level() —
  │                     zentrale, einzige Quelle für Admin-/Owner-Checks
  │                     (ARCH-021/P-3, ARCH-023)
  ├── session.py          SessionManager — zentrales Session-Management
  │                     (ARCH-021/P-4)
  └── models.py           MenuState/AccessLevel/MenuItem/MenuSession
                        (ARCH-021/P-2)
```

**Wichtig: Duplikat-Verwaltung (`duplicates.py`) ist bewusst eine eigene
Domäne**, nicht Teil von `library.py` — Duplicate Detection ist laut
CLAUDE.md Abschnitt 15 eine eigene P0-Domäne. **`content/` ist bewusst
kein Teil von `actions/`** — Help-/Greeting-Content ist User-Facing
Presentation/Messaging, keine Domain-Action (siehe ARCH-025-Dokument
Abschnitt A.2).

Innerhalb von `content/` trennt die ARCH-025 Content-Separation-Closure
zusätzlich statischen Text (`messages.py`) von Orchestrierung
(`greeting.py`/`help.py`) und Kontext (`user_context.py`) — siehe
[`MusicBot_ARCH-025_Menu_Command_Help_Content_Closure.md`](MusicBot_ARCH-025_Menu_Command_Help_Content_Closure.md).

`permissions.py`/`session.py`/`models.py` sind durch `ARCH-024`/`ARCH-025`
**nicht** verändert worden. `RichMenuHandler` behält aus dem Onboarding-
Cluster bewusst 5 dünne Delegator-Methoden (`_load_user_data()`/
`_get_user_info()`/`_is_new_user()`/`_get_user_role()`/
`_get_available_features()`, delegieren nach `content/user_context.py`)
sowie `handle_menu_command()` (bereits dünner Adapter, kein
Extraktionsbedarf).

---

## 2. Bestehender Menübaum (Überblick)

Nur zur Orientierung — Detailverhalten der einzelnen Admin-/Statistik-/
Navidrome-Bereiche ist nicht Gegenstand dieses Dokuments, da sie nicht in
dieser Phase entstanden sind. **Ausnahme: der Family-Hub-Zweig**
(👨‍👩‍👧‍👦 Familie mit Familien-Statistik, Familien-Chat, Familien-Challenge)
— siehe Abschnitt 6 für die vollständige Doku dieser Phase, Abschnitt 6.13
für die Navigations-Umstrukturierung.

**Admin-Menü-Reorg (UX/Navigation):** Administration wurde von 12
gleichrangigen Einzelpunkten auf 5 Top-Level-Punkte (3 thematische
Gruppen + Duplikate + Benutzerverwaltung) umgebaut, um die
Informationsdichte auf dem Smartphone zu reduzieren. Alle bestehenden
Callback-Daten (`dup:`, `erradmin:`, `backup_`, `logger_`, `status_`,
`restart:`, `maint:`, `reprocess:`, `doctor:`) blieben dabei unverändert
— nur die übergeordneten Menüknoten sind neu. Zuvor war dieser Abschnitt
bereits veraltet (kannte Wartungsmodus/Reprocessing/Doctor/Navidrome-Scan
nicht und listete Test-System fälschlich als Admin-Kind) und wurde hier
zusätzlich korrigiert.

```text
Hauptmenü
├── 📥 Downloads                    → siehe Abschnitt 3
├── 📊 Statistiken                   → siehe Abschnitt 9 (Statistics Menu UX & Architecture Optimization)
│   ├── 📅 Rückblicke (stats_reviews, reiner Navigations-Container)
│   │   ├── Diese Woche (stats_weekly, NEU)
│   │   ├── Dieser Monat (stats_monthly)
│   │   └── Dieses Jahr (stats_yearly)
│   ├── 🏆 Rankings (stats_rankings, reiner Navigations-Container)
│   │   ├── Top Songs (stats_top_songs)
│   │   └── Top Künstler (stats_top_artists)
│   ├── 📈 Music Timeline (stats_timeline)
│   └── 📚 Meine Library (stats_library_overview, USER-Level, kein Admin-Gate)
├── 👨‍👩‍👧‍👦 Familie                     → siehe Abschnitt 6.13 (Family Hub Navigation Restructuring)
│   ├── 📊 Familien-Statistik        → siehe Abschnitt 6 (Family Hub, F2) - fachlich UNVERÄNDERT
│   │   ├── Top Songs Familie / Top Künstler Familie
│   │   ├── Statistik pro Person
│   │   ├── Musik-Champion
│   │   ├── Hör-Aktivität
│   │   └── Monatsentwicklung
│   ├── 💬 Familien-Chat             → siehe Abschnitt 6 (Family Hub, F3) - fachlich UNVERÄNDERT
│   │   ├── Nachricht senden
│   │   ├── Letzte Nachrichten
│   │   └── Benachrichtigungen
│   └── 🎯 Familien-Challenge        → siehe Abschnitt 6 (Family Hub, F4) - fachlich UNVERÄNDERT
│       ├── Heutige Challenge
│       ├── Antworten
│       └── Punktestand
├── ⚙️ Administration                (ADMIN-Level)
│   ├── 🎵 Bibliothek & Navidrome
│   │   ├── MusicBot Doctor (Health-Scan + SAFE_AUTOMATIC-Repair)
│   │   ├── Reprocessing (OWNER-only)
│   │   ├── Navidrome Scan
│   │   ├── 🔎 Library Health Review (Findings nach Kategorie prüfen)
│   │   │      Vokabular seit 2026-09-09: 🔴 Offen / 🟢 Repariert / ⚪ Akzeptiert
│   │   │      (⚪ == Lifecycle-Status FALSE_POSITIVE). Die Übersicht hat einen
│   │   │      „⚪ Akzeptierte Findings"-Einstieg (nur wenn vorhanden) →
│   │   │      Liste nach Code → Detail mit Grund → „↩️ Reaktivieren" (unaccept
│   │   │      → OPEN, Stale-Revalidierung). Rein lesend bis zum Reaktivieren-Tap.
│   │   └── 🛠️ Repair MusicBot (Plan/Preview/Ausführung/Historie/Statistik)
│   ├── 🤖 Bot & Betrieb
│   │   ├── Bot neu starten
│   │   ├── Wartungsmodus
│   │   └── Backup-Verwaltung (Bot/Library sichern, Backup-Listen)
│   ├── 🩺 Diagnose & Monitoring
│   │   ├── System-Status
│   │   ├── System-Logs
│   │   ├── Error-Verwaltung (Statistiken, Gesundheitsbericht, Letzte Fehler, Reset)
│   │   └── Logger-Verwaltung (Übersicht, Module, Level, Dateien, Statistiken,
│   │       Handler, Bereinigung)
│   ├── ♻️ Duplikate (Statistiken, Cache leeren)
│   └── 👥 Benutzerverwaltung
├── 🎵 Navidrome Mediathek
│   ├── Durchsuchen (Künstler/Alben/Genres/Playlists)
│   ├── Suchen (Überall/Künstler/Alben/Songs)
│   ├── Meine Playlists / Favoriten / Zuletzt gespielt
│   └── Statistiken
└── 🧪 Test-System (Unit/Integration/Performance)  → eigenständiges
    Root-Menü, ADMIN-gated, KEIN Kind von Administration
```

---

## 3. Download-Control-Center (diese Phase, 2026-09-02)

### 3.1 Auftrag

Nutzer-Vorgabe: „📥 Downloads" von einer statischen 2-Optionen-Liste
(„Einzelner Track" / „Playlist" — reine Hinweistexte ohne echte Funktion)
zu einem echten Steuerzentrum mit Live-Status und Abbruch-Funktion machen.

Explizit **nicht** Teil dieser Ausbaustufe (Nutzer-Entscheidung):

- Pause/Resume (technisch deutlich anspruchsvoller als Cancel bei
  yt-dlp/Playlist-Orchestrierung, unnötige Komplexität)
- „🔄 Reprocessing" (eigener, künftiger Bereich)
- „📋 Download-Verlauf" / „🔁 Erneut versuchen" mit echtem persistentem
  Speicher — damals zurückgestellt, in einer eigenen Folgephase
  umgesetzt (siehe Abschnitt 3.6)

### 3.2 Fertig integriert

**Menü-Einstieg:** `download`-`MenuItem` hat jetzt einen echten Handler
(`_handle_download_menu`) statt nur seine 2 alten statischen Kinder zu
rendern. Die beiden alten Kinder (`download_single`/`download_playlist`)
bleiben im Baum bestehen, sind aber über die UI nicht mehr erreichbar
(bewusst nicht entfernt, um Blast-Radius klein zu halten).

**Neuer Callback-Präfix `dl:`**, dispatcht über
`_handle_download_control_callback()`:

| Callback | Methode | Verhalten |
|---|---|---|
| `dl:menu` / `menu:download` | `_render_download_menu` | Einstiegsbildschirm: „➕ Neuer Download" / „🔄 Aktive Downloads" / „📋 Download-Verlauf" immer sichtbar; „❌ Abbrechen" nur, wenn für diesen Chat tatsächlich ein Download läuft (keine toten Buttons) |
| `dl:new` | `_handle_download_new` | Statischer Hinweistext: einfach einen YouTube-Link senden |
| `dl:active` | `_handle_download_active` | Live-Status: Titel, Fortschrittsbalken, „⬇️ Aktuell" (aktueller Track), „✅ Abgeschlossen" (letzte 5 fertige Tracks), „⏳ Noch N Tracks"; Buttons „❌ Download abbrechen" / „ℹ️ Details" / „◀️ Zurück" |
| `dl:details` | `_handle_download_details` | URL, Typ (single/playlist), Laufzeit, Fortschritt, aktueller Track |
| `dl:cancel` | `_handle_download_cancel_request` | Setzt `request_cancel()`, sendet Bestätigung |
| `dl:history` | `_handle_download_history` | Download-Verlauf, siehe Abschnitt 3.6 |
| `dl:retry:<position>` | `_handle_download_retry` | „🔁 Erneut versuchen", siehe Abschnitt 3.6 |

**Live-Status-Datenquelle:** derselbe geteilte `ProgressTracker`, den auch
die automatischen Zwischen-Updates während des Downloads verwenden
(`tracker.current_item`, `tracker.completed_items`,
`tracker.processed_items`/`total_items`) — keine zweite Zustandsquelle.

**`ActiveDownloadRegistry`** (`services/downloader/active_downloads.py`,
neu): prozessweite, threadsichere Registry (ein `ActiveDownload` pro
`chat_id`), verankert auf `RichMenuHandler` (langlebig, ein Objekt pro
Bot-Prozess) statt auf `DownloadHandler` (wird pro Telegram-Update neu
konstruiert). Hält `url`, `download_type`, `title`, `started_at`, den
geteilten `tracker`, sowie `cancel_event`/`cancelled`-Flag.
`threading.Lock`/`threading.Event`, bewusst **nicht** `asyncio`-Primitive,
weil der Cancel-Check-Hook in einem `run_in_executor`-Worker-Thread läuft.

**Cancel-Semantik (Nutzer-Entscheidung: Hard Cancel):** bricht den
*gerade laufenden* Track sofort ab, nicht erst den nächsten.

- *Hard-Cancel:* ein Cancel-Check-Hook wird einmalig in
  `ydl_opts["progress_hooks"]` injiziert (`enhanced_download_with_retry()`)
  und dadurch automatisch von **jedem** nachfolgenden yt-dlp-Aufruf
  mitgezogen (Single-Download **und** jeder einzelne Playlist-Track), da
  `download_executor.py` diese Liste nur erweitert, nie ersetzt. Der Hook
  wirft `DownloadCancelledError` (`services/downloader/errors.py`,
  non-retryable — in `_NON_RETRYABLE_ERROR_TYPES` eingetragen).
- *Soft-Cancel:* `_process_playlist_download()` prüft zusätzlich vor jedem
  Track `is_cancel_requested()` und startet dann keine weiteren Tracks.

`DownloadHandler.handle_youtube_links()` registriert/deregistriert
(`finally`-Block) den aktiven Download und unterscheidet „echter
Fehlschlag" von „abgebrochen": bei 0 fertigen Tracks eine kurze eigene
Meldung („🛑 Download abgebrochen"), bei Playlists mit bereits fertigen
Tracks läuft die normale Metadaten-/Bibliotheks-/Zusammenfassungs-Pipeline
weiter — die Zusammenfassung selbst zeigt dann „🛑 Download abgebrochen"
mit „N/M abgebrochen bei" statt des Erfolgs-Headers.

### 3.3 Live gefundene und behobene Bugs

Alle vier Bugs wurden erst durch echte Interaktion über den Test-Bot
sichtbar, nicht durch Unit-Tests allein — jeweils mit Pre-Fix-
Diskriminierung (`git stash`) und vollständiger Testsuite gegengeprüft.
Details siehe `docs/FINDINGS_INDEX.md`.

| # | Symptom (Nutzer-Report) | Ursache | Fix |
|---|---|---|---|
| A (P0) | „sobald Download läuft öffnet sich das Menü nicht" | `_process_url()` awaitete `handler.handle_url()` direkt — PTB (`concurrent_updates=False`) verarbeitete dadurch kein weiteres Update, solange ein Download lief | Download läuft als eigenständiger `asyncio.create_task()` |
| B (P1) | „Downloads lässt sich öffnen aber die restlichen Buttons sind tot außer Hauptmenü" | Fehlender `CallbackQueryHandler(pattern="^dl:")` auf PTB-Ebene — das interne `dl:`-Routing in `RichMenuSystem` wurde nie erreicht | Handler ergänzt |
| C (P2) | Zusammenfassung nach Abbruch zeigte „Beispiel-Track: N/A" trotz erfolgreichem Track 1 | `tracks[-1]` blind für den Pfad verwendet — letzter Eintrag war der neue, abgebrochene Track ohne `library_path` | Sucht `reversed(tracks)` nach erstem Eintrag mit vorhandenem `library_path` |
| D (P1) | `BadRequest: Can't parse entities` beim Klick auf „ℹ️ Details" | `active.url` (echte YouTube-URL mit „_") roh in einer `parse_mode="Markdown"`-Nachricht — Telegrams Legacy-Parser interpretiert einzelnes „_" als unvollständige Kursiv-Formatierung | `parse_mode="Markdown"` aus der gesamten `dl:`-Sektion entfernt (alle 5 Methoden) statt einzelne Felder selektiv zu escapen |

Alle vier Fixes wurden nach dem jeweiligen Fix erneut live gegen den
Test-Bot verifiziert (Bug A/B/C via echter Cancel-Durchlauf, Bug D via
erneutem Download ohne Fehler im Log).

### 3.4 Tests

- `tests/test_active_download_registry.py` (12 Tests)
- `tests/test_download_executor_cancel.py` (3 Tests)
- `tests/test_playlist_download_cancellation.py` (7 Tests)
- `tests/test_download_handler_active_download_lifecycle.py` (11 Tests)
- `tests/test_rich_menu_download_control_center.py` (28 Tests, inkl.
  `TestDlMessagesAvoidMarkdownParseErrors` für Bug D)
- `tests/test_rich_menu_handler.py` (erweitert:
  `TestProcessUrlRunsAsBackgroundTask` für Bug A,
  `TestGetTelegramHandlersRegistersDlPrefix` für Bug B)
- `tests/test_download_result_reporter.py` (erweitert: `TestBuildFinal…Cancelled`
  + N/A-Regressionstest für Bug C)
- `tests/test_youtube_downloader_telegram_decoupling.py` (erweitert:
  `active_download`-Weiterreichung, `cancelled`-Flag)

Vollständige Suite zum Abschluss dieser Phase: **1908 passed, 1 skipped
(umgebungsbedingt), 0 failed.**

### 3.5 Offen / zurückgestellt

**„🔄 Reprocessing"**: bewusst separater, noch nicht begonnener Bereich
(Nutzer-Entscheidung).

### 3.6 Download-Verlauf / Erneut versuchen (Folgephase, 2026-09-03)

Umsetzung des in Abschnitt 3.1/3.5 zurückgestellten Punkts (CLOSED,
`docs/FINDINGS_INDEX.md`).

**Persistenz:** neuer `services/downloader/download_history.py::
DownloadHistoryStore` — struktureller Zwilling zu `duplicate/cache.py`
(atomares Schreiben: write-tmp + `Path.replace()`, analog INV-02). Ein
JSON-Dokument (`chat_id` → Liste von Einträgen), Verzeichnis über
`Config.DOWNLOAD_HISTORY_DIR` (`cache/download_history/`). Deckelung auf
`MAX_ENTRIES_PER_CHAT = 20`, älteste zuerst entfernt. Geteilte,
prozessweite Instanz — auf `RichMenuHandler` verankert (analog
`ActiveDownloadRegistry`, aus demselben Grund: `DownloadHandler` wird pro
Update neu konstruiert), per `set_download_history()` an `RichMenuSystem`
und per Konstruktor-Parameter an jeden neuen `DownloadHandler`
durchgereicht.

**Schreib-Hooks** in `klassen/download_handler.py` (`_record_history_entry()`,
No-op-sicher falls kein Store injiziert):

| Stelle | Status | Besonderheit |
|---|---|---|
| `handle_single_track_success()` | `success` | Nur für echte Einzel-Downloads (`result.get("type") != "playlist"`) — der Playlist-Wrapper delegiert ebenfalls hierher, trägt aber kein echtes `title`/`artist` |
| `_register_playlist_track_duplicates()` | `success` | Ein Eintrag pro tatsächlich erfolgreichem Track, mit dessen eigener Identität — analog zur bereits bestehenden Duplikat-Registrierung dort (dieselben Guards: kein Eintrag bei Fehlschlag/`renamed_due_to_conflict`/Platzhalter-Artist) |
| `handle_download_failure()` | `failed` | URL aus `update.message.text` (kein Track-Titel zu diesem Zeitpunkt bekannt) |
| `_handle_download_cancelled()` | `cancelled` | Ebenso |

**UI (`_handle_download_history()`):** letzte Einträge des Chats, neueste
zuerst, mit Status-Icon (✅/❌/🛑) und Zeitstempel; leer → Hinweistext
statt leerer Liste. Pro Eintrag ein „🔁"-Button
(`callback_data=f"dl:retry:{position}"`, `position` = Index in
`get_recent()`/`get_entry_by_position()`, damit Anzeige und Callback
immer übereinstimmen).

**„🔁 Erneut versuchen" (`_handle_download_retry()`):** `RichMenuSystem`
kann selbst keinen `DownloadHandler` bauen (das kann nur
`RichMenuHandler`, siehe `_create_download_handler()`/`_process_url()`).
Bewusst **kein** Eingriff in `handle_youtube_links()` (in CLAUDE.md
Abschnitt 19 als „große Klasse"/Risikobereich gelistet) — stattdessen
injiziert `RichMenuHandler.initialize()` `self._process_url` als
Callback (`set_url_retry_callback()`). Da PTB-`Update`-/`Message`-Objekte
nach Auslieferung eingefroren sind (keine nachträgliche Mutation
möglich), baut `_handle_download_retry()` ein minimales
Duck-Typing-Objekt (`_RetryUpdateAdapter`/`_RetryMessageAdapter`,
`handlers/menu/rich_menu_system.py`) anstelle eines echten `Update`:
`effective_user`/`effective_chat`/`update_id` 1:1 vom auslösenden
Callback-Query übernommen, `message.text` = gespeicherte URL,
`message.reply_text` = `callback_query.message.reply_text` (sendet in
denselben Chat). Läuft danach durch exakt denselben, bereits produktiv
genutzten Pfad (`_process_url()` → `handler.handle_url()` →
`handle_youtube_links()`) wie ein normaler Text-Download — keine
Parallel-Implementierung der Pipeline.

**Tests:** `tests/test_download_history_store.py` (16, reiner Store),
`tests/test_download_handler_history_recording.py` (12, die vier
Schreib-Hooks), `tests/test_rich_menu_download_history.py` (15,
Menü-/Retry-Dispatch). Volle Suite: 2097 passed, 1 skipped, 0
Regressionen.

---

## 4. Bot-Wartungsmodus (Ein-/Ausschalten, 2026-09-03)

Nutzer-Auftrag: "Ein-/Ausschalten" des Bots über Telegram-Inline-Buttons,
analog zum bestehenden Bot-Neustart (`handlers/admin/bot_restart_handler.py`).

### 4.1 Architektur-Grenze (Klärung vor der Umsetzung)

`BotRestartHandler` funktioniert über `sudo systemctl restart bot` — der
systemd-Service (`/etc/systemd/system/bot.service`, `Restart=always`,
`RestartSec=10`) startet den Prozess automatisch neu, sobald er beendet
wird. Ein echtes "Aus" (`systemctl stop`) würde den Bot-Prozess jedoch
wirklich stoppen — niemand würde mehr auf Telegram-Nachrichten lauschen,
es gäbe **keine Möglichkeit**, ihn per Inline-Button wieder
"einzuschalten" (der Prozess, der den Klick empfangen müsste, liefe gar
nicht mehr). Das ist keine Implementierungslücke, sondern eine harte
technische Grenze.

Nutzer-Entscheidung (nach Darstellung der Grenze): **Wartungsmodus**
statt echtem Prozess-An/Aus — der Prozess läuft immer weiter (bleibt für
Telegram erreichbar), ein persistiertes Feature-Flag schaltet die
eigentliche Funktionalität ab/an. Voll rundum per Telegram-Button
steuerbar, technisch einfach und robust.

### 4.2 Umsetzung

**Persistenz:** neuer `services/bot_maintenance.py::MaintenanceModeStore`
— struktureller Zwilling zu `download_history.py`/`duplicate/cache.py`
(atomares Schreiben, `data/maintenance_mode.json` — folgt derselben
Konvention wie `data/module_logger_config.json`/`data/user_data.json`,
kein eigenes Config-Attribut, da Anwendungszustand statt Cache). Default
bei fehlender/korrupter Datei: **nicht aktiv** (verhindert, dass ein
beschädigter Zustand versehentlich alle Nutzer aussperrt). Geteilte,
prozessweite Instanz auf `RichMenuHandler` verankert (analog
`ActiveDownloadRegistry`/`DownloadHistoryStore`), per `set_maintenance_store()`
an `RichMenuSystem` durchgereicht.

**Admin-Bypass (zentrale Design-Entscheidung):** Admins/Owner nutzen den
Bot im Wartungsmodus **unverändert normal weiter** — sonst gäbe es
keinen Weg zurück zum Ausschalten, da auch der Toggle-Button selbst
hinter demselben Gate stünde. Alle anderen Nutzer bekommen an **jedem**
Einstiegspunkt eine Wartungsmeldung statt der eigentlichen Funktion.

**Durchsetzung an allen 7 Telegram-Einstiegspunkten** über einen
gemeinsamen Helper (`handlers/menu/maintenance_gate.py::
is_blocked_by_maintenance()`, freie Funktion statt Methode, da sowohl
`RichMenuHandler` als auch `RichMenuSystem` sie unabhängig aufrufen):

- `RichMenuSystem.handle_callback()` — deckt zentral ~9 Callback-Präfixe
  auf einmal ab (menu:/dl:/restart:/backup_/status_/usermgmt_/dup:/
  logger_/erradmin:)
- `RichMenuHandler.handle_start_command()` (/start)
- `RichMenuHandler.handle_menu_command()` (/menu)
- `RichMenuHandler.handle_help()` (/help)
- `RichMenuHandler.handle_help_callback()` (`^help:`-Callbacks)
- `RichMenuHandler.handle_url_message()` (YouTube-URLs)
- `RichMenuHandler.handle_text_message()` (sonstiger Freitext)

`maintenance_store` darf `None` sein (bestehende Tests bypassen
`__init__()` über `object.__new__()`, etabliertes Muster dieser Session)
— liefert dann unauffällig "nicht blockiert", kein `AttributeError`.

**UI:** neuer Menüpunkt "🛠️ Wartungsmodus" im Admin-Menü (neben "🔄 Bot
neu starten"), `callback_data="maint:show"`/`"maint:toggle"`. Anders als
beim Neustart bewusst **ohne** Bestätigungsdialog (instant reversibel,
kein Datenverlust/Verbindungsabbruch) und **ohne** eigene Handler-Klasse
(Logik beschränkt sich auf Lesen/Schreiben des einen booleschen
Zustands, direkt auf `RichMenuSystem`). Eigener Admin-Check in
`_handle_maintenance_callback()` (Defense-in-Depth, `maint:` bewusst
nicht in `_ADMIN_ONLY_PREFIXES` aufgenommen — analog zu `restart:`/
`erradmin:`, die aus demselben Grund ebenfalls einen eigenen Check
haben statt den zentralen).

### 4.3 Tests

`tests/test_bot_maintenance_store.py` (9, reiner Store),
`tests/test_maintenance_gate.py` (6, gemeinsamer Gate-Check isoliert),
`tests/test_rich_menu_maintenance_mode.py` (11, Menü-/Toggle-Dispatch +
Admin-Gating), `tests/test_rich_menu_handler_maintenance_gate.py` (9,
end-to-end über alle 6 `RichMenuHandler`-Einstiegspunkte + Admin-Bypass).
Test-Isolation: `MaintenanceModeStore`s `state_file` wird in
`RichMenuHandler.__init__()` bewusst explizit über `Path(...)` **dieses**
Moduls aufgelöst (statt den Default-String durchzureichen) — dasselbe,
bereits etablierte Patching-Muster wie bei `user_data_file` in
`_make_handler()` (`tests/test_rich_menu_handler.py`) greift dadurch
auch hier, ohne ein neues Config-Attribut nur für Tests einzuführen.
Volle Suite: 2146 passed, 1 skipped, 0 Regressionen.

---

## 5. Metadata-Reprocessing (Telegram-Integration, 2026-09-03)

Nutzer-Auftrag: `scripts/reprocess_artist_metadata.py` (bisher reines
CLI-Werkzeug, siehe `docs/METADATA_REPROCESSING.md`) über Telegram-Inline-
Buttons statt Terminal ausführbar machen — vorausgesetzt Härtung des
Skripts vor genau dieser Integration (`docs/FINDINGS_INDEX.md`,
„Härtung vor geplanter Telegram-Menü-Integration").

### 5.1 Architektur-Entscheidung: Subprozess statt In-Process-Import

`EnhancedMetadataProcessor`/`ArtistNormalizer`/`GenreMapper` sind
`SingletonMixin` — würde der Bot das Skript in-process importieren/
aufrufen, bekäme es unbemerkt die längst mit echter `config.Config`
konstruierte Produktivinstanz zurück (Schreibzugriff auf echte
`mapping/auto_learned_*.json` statt der isolierten Testumgebung; siehe
`docs/METADATA_REPROCESSING.md` Abschnitt 2a für die volle Herleitung).
Deshalb: `services/metadata/reprocessing_runner.py::run_reprocessing()`
startet das Skript ausschließlich als eigenständigen Subprozess
(`asyncio.create_subprocess_exec(sys.executable, ...)`), genau wie die
bestehende CLI-Nutzung — nie ein direkter Import. Reine Orchestrierung,
keine Telegram-Importe (Schichtgrenze `services/`, CLAUDE.md Abschnitt 4).

### 5.2 Umsetzung

**Zugriff:** nur Owner (`Config.OWNER_USER_ID`), nicht Owner+Admin wie
beim Wartungsmodus — Nutzer-Entscheidung, da das Tool auf Metadata-/
Auto-Learn-Dateien zugreift. `MenuItem.access_level=AccessLevel.OWNER`
blendet den Button für alle anderen aus; `_handle_reprocessing_callback()`
prüft zusätzlich selbst (Defense-in-Depth, bewusst nicht in
`_ADMIN_ONLY_PREFIXES`, da OWNER strenger als ADMIN ist — analog
`maint:`/`restart:`/`erradmin:`).

**Ablauf:** „🔧 Reprocessing" im Admin-Menü (`reprocess:show`) → Buttons
aus den vorhandenen Verzeichnissen unter `/tmp/musicbot_test/metadaten/`
(`reprocess:pick:<idx>`, Index statt Artist-Name im `callback_data` —
vermeidet Sonderzeichen-/Längenprobleme mit Telegrams 64-Byte-Limit,
Liste wird bei jedem Schritt frisch geglobbt) → Dry-Run läuft, danach
Zusammenfassung mit „🔴 Jetzt LIVE ausführen"-Button
(`reprocess:live:<idx>`) → LIVE-Lauf, danach Abschluss-Zusammenfassung.
Nutzer-Entscheidung: **kein** direkter Live-Einstieg ohne vorherigen
Dry-Run (im Unterschied zum sofort wirksamen Wartungsmodus-Toggle) —
dieses Tool schreibt echte Dateien.

**Kein blockierender Lauf:** jeder Subprozess-Aufruf (kann mehrere Minuten
dauern, externe API-Calls pro Track) läuft als eigenständiger
Hintergrund-Task (`asyncio.create_task()` in
`ReprocessingMenuHandler._start_run()`), identisches Muster zu
`rich_menu_handler.py::_process_url()` (Bug A, Abschnitt 3.3) — ohne
diesen Task würde ein laufendes Reprocessing jedes weitere Telegram-Update
blockieren, da die `Application` ohne `concurrent_updates=True` läuft.

**Neue Dateien:** `services/metadata/reprocessing_runner.py` (Subprozess-
Start, stdout-Parsing des von `main()` ausgegebenen JSON-Summarys,
Timeout-Schutz), `handlers/menu/reprocessing_menu_handler.py`
(`ReprocessingMenuHandler` — Artist-Liste, Dry-Run/Live-Flow,
HTML-escapte Ergebnis-Formatierung).

### 5.3 Tests

`tests/test_reprocessing_runner.py` (11 — reine Parsing-Helfer
deterministisch, `asyncio.create_subprocess_exec`-Fehlerfälle gemockt,
Happy-Path UND `PathSafetyError`-Fall als echter Subprozess gegen das
echte Skript), `tests/test_reprocessing_menu_handler.py` (15 — Owner-
Gating, Artist-Liste, Pick/Live-Flow, Ergebnis-Formatierung inkl.
HTML-Escaping, Hintergrund-Task-Sicherheitsnetz),
`tests/test_rich_menu_reprocessing.py` (8 — Dispatch-/Gating-Ebene in
`RichMenuSystem`, Bug-B-Regressionstest für die `^reprocess:`-Pattern-
Registrierung in `tests/test_rich_menu_handler.py`). Volle Suite: 2216
passed, 1 skipped, 0 Regressionen.

---

## 6. Family Hub — Statistik, Chat & Tägliche Challenge (Phase F1–F5, 2026-09-12/13)

### 6.1 Auftrag

Nutzer-Vorgabe (Master-Prompt „Family Music Hub"): die bestehende
MusicBot-Architektur zu einem privaten Familien-Musikhub erweitern —
Familien-Gesamtstatistik/Statistik pro Person, ein bot-interner
Familien-Chat, sowie eine tägliche Familien-Musik-Challenge. Explizite
Vorgaben: **keine** zweite Statistik-Engine (bestehende
`StatistikService`/`PlayHistoryRepository`/`StatisticsCalculator`
wiederverwenden), **keine** erfundenen Telegram-IDs, **keine**
automatische Familienzuordnung, Downloads und Plays bleiben
konzeptionell getrennt.

Phasenablauf: AUDIT → F1 Family Basis → F2 Family Statistics → F3 Family
Chat → F4 Daily Challenges (+ Scheduler) → F5 Hardening. Jede Phase
einzeln implementiert, gezielt + thematisch getestet, dann per
Nutzer-Freigabe fortgesetzt.

### 6.2 Architektur

Neue, eigenständige Schicht `services/family/` (Konvention wie
`services/duplicate/`/`services/library_health/`) — reine Fachlogik,
keine Telegram-Objekte:

```text
Telegram-Update
   ↓
handlers/family_stats_handler.py       (F2, Präsentation)
handlers/family_chat_handler.py        (F3, Präsentation)
handlers/family_challenge_handler.py   (F4, Präsentation)
handlers/family_challenge_scheduler.py (F4, täglicher Trigger + Broadcast)
   ↓
services/family/family_service.py           (F1 — Berechtigung/Membership)
services/family/family_repository.py        (F1 — Persistenz Familienstruktur)
services/family/family_stats_service.py     (F2 — Aggregation über PlayHistoryRepository)
services/family/family_chat_service.py      (F3 — Fachlogik Chat)
services/family/family_message_repository.py(F3 — Persistenz Nachrichten)
services/family/family_challenge_service.py (F4 — Challenge-Auswahl/Auswertung)
services/family/family_challenge_repository.py(F4 — Persistenz Challenges/Antworten)
   ↓
services/statistik/play_history_repository.py  (WIEDERVERWENDET, unverändert)
services/statistik/statistics_calculator.py    (WIEDERVERWENDET, unverändert)
```

`StatisticsCalculator`/`StatistikService` (persönliche Statistik) wurden
**nicht verändert** — `FamilyStatsService` liest dieselben
Play-History-JSON-Dateien über eine eigene `PlayHistoryRepository`-Instanz
(zustandslos, mehrere Instanzen sind unproblematisch) und aggregiert
zusätzlich über mehrere Navidrome-User hinweg.

### 6.3 Datenmodell

Drei neue, lokale JSON-Dateien (wie `data/user_data.json` durch
`.gitignore` von Git ausgenommen — Laufzeitdaten, keine Codeartefakte):

```text
data/family_data.json
{
  "<family_id>": {
    "name": str,
    "members": {
      "<telegram_id>": {
        "display_name": str,
        "navidrome_user": str,
        "active": bool,
        "notifications": bool
      }
    }
  }
}

data/family_messages.json
{
  "<family_id>": {
    "next_id": int,
    "messages": [
      {"id": int, "family_id": str, "sender_user_id": str,
       "sender_display_name": str, "message": str, "created_at": str}
    ]
  }
}   # Historie pro Familie auf 500 Einträge gedeckelt

data/family_challenges.json
{
  "<family_id>": {
    "next_id": int,
    "challenges": [
      {"id": int, "family_id": str, "date": "YYYY-MM-DD", "type": str,
       "question": str, "correct_answer": Optional[str], "created_at": str}
    ]
  }
}

data/family_challenge_answers.json
{
  "<family_id>": {
    "answers": [
      {"challenge_id": int, "user_id": str, "answer": str,
       "points": int, "answered_at": str}
    ]
  }
}
```

Alle vier Dateien: atomares Schreiben (write-tmp + `Path.replace()`),
identisches Muster zu `UserManagementHandler._save_users()`/
`MetadataCache.store()`. **Bewusst kein separates „Rolle"-Feld** im
Family-Modell — die bestehende Rollen-/Berechtigungswahrheit bleibt
`data/user_data.json`/`UserManagementHandler.ROLES`, um keine zweite,
potenziell abweichende Quelle zu schaffen.

`next_id` läuft **pro Familie unabhängig** (wie bei allen bestehenden
Cache-Dateien mit fortlaufenden IDs) — Challenge-/Nachrichten-IDs
kollidieren also normalerweise zwischen Familien (beide starten bei 1).
Das ist unkritisch, weil jeder Lookup (`get_challenge_by_id`,
`get_recent_messages`, …) strikt über die aufgelöste `family_id` skopiert
ist — regressionsgetestet in `tests/test_family_challenge_service.py::
test_member_cannot_answer_another_familys_colliding_challenge_id`.

### 6.4 Berechtigungsmodell (Datenschutz)

Serverseitige Zugriffsprüfung, identisch in allen drei Handlern:

```text
Telegram User ID → FamilyService.is_active_family_member()? → nein → Zugriff verweigert
                                                              → ja  → FamilyService.get_family_id_for_telegram_user()
                                                                      → Aggregation/Nachricht/Challenge NUR für diese family_id
```

`family_id` wird **niemals** aus Nutzereingaben/Callback-Daten
übernommen — ausschließlich serverseitig aus der Telegram-ID aufgelöst
(repoweit verifiziert, siehe F5-Audit). Ein normaler Bot-Benutzer ohne
Family-Eintrag bekommt an jedem der drei Menüzweige ausschließlich eine
Zugriffsverweigerung (`⛔ Nur für Familienmitglieder verfügbar.`).

Aktuelle Familie „main" (Stand F1, `data/family_data.json`): die zwei
bereits registrierten Telegram-Nutzer `dkmd` und `marina` — explizit vom
Nutzer bestätigt, keine erfundenen IDs. Ein drittes Navidrome-Profil
(„jamie") existiert in der Play-History, hat aber keinen Telegram-Account
und ist deshalb bewusst **kein** Familienmitglied.

### 6.5 F2 — Family Statistics

`FamilyStatsService` aggregiert `PlayHistoryRepository.load()` über alle
aktiven Mitglieder einer Familie. Seit MASTER PHASE B (Abschnitt 6.14)
über eine intern komponierte `StatisticsCalculator`-Instanz (dieselbe
`PlayHistoryRepository`-Quelle) — keine zweite Kalender-/Identity-/
Split-Engine:

| Methode | Liefert |
|---|---|
| `generate_family_stats(family_id, period, now=None)` | echte Kalenderperiode (`period_start`/`period_end`), Gesamt-Plays, Top-10 Songs/Artists (strukturiert, mit Member-Attribution), Plays pro Mitglied, `listening_seconds`/`listening_seconds_reliable` |
| `get_champion(family_id, period, now=None)` | Mitglied mit den meisten Plays (`(telegram_id, display_name, plays)`) — **ausschließlich Plays, keine Downloads** |
| `generate_family_timeline(family_id)` | Heute/Woche/Monat (kalenderbasiert, eigene unveränderte Logik seit F2 — siehe Abschnitt 6.14): Track-Count, Top-Artist, Top-Song, Plays pro Mitglied |
| `generate_listening_times(family_id, period, now=None)` | Verteilung nach Tagesstunde/Wochentag (auf Play-Count, nicht Dauer — siehe unten), echte Kalenderperiode |
| `generate_monthly_trend(family_id, months, now=None)` | Plays pro Kalendermonat, chronologisch |

**Hör-Aktivität statt Hörzeit (bewusste Design-Entscheidung):** `duration`
wird vom bestehenden `PlayHistoryPoller` unverändert aus Navidrome
übernommen und ist in der realen Play-History praktisch immer `null`
(clientabhängig). Jede Sekunden-Summe wird deshalb von einem
`listening_seconds_reliable`-Flag begleitet; „Hörzeit pro Monat" wurde
deshalb bewusst **nicht** umgesetzt (wäre irreführend). Die Funktion
(intern weiterhin `generate_listening_times()`) misst Wiedergabe-
**Zeitpunkte** (Stunde/Wochentag), keine echte Hördauer — seit MASTER
PHASE B heißt der Telegram-Menüpunkt/die Anzeige deshalb konsequent
„⏰ Hör-Aktivität", nicht mehr „Hörzeiten" (Abschnitt 6.14).

Menü: „📊 Familien-Statistik" liegt seit MASTER PHASE A unter
„👨‍👩‍👧‍👦 Familie" (siehe Abschnitt 6.13), nicht mehr unter „📊 Statistiken".

### 6.6 F3 — Family Chat

Bot-interner, privater Chat (kein Telegram-Nachbau) über
`FamilyChatService`/`FamilyMessageRepository`. „📝 Nachricht senden" ist
ein Zwei-Schritt-Ablauf (Klick → Freitext) über ein handler-eigenes
`pending_message_senders`-Set (`FamilyChatHandler`) — bewusst **nicht**
über den generischen `TextWorkflowDispatcher`
(`handlers/menu/text_workflow_dispatcher.py`), dessen `WORKFLOW_METHODS`
fest auf `user_mgmt_handler` verdrahtet ist. Stattdessen exakt dasselbe,
bereits etablierte Muster wie `NavidromeMenuHandler.browse_states`.
`RichMenuHandler.handle_text_message()` prüft dieses Set **vor** dem
generischen Workflow-Dispatch; der bestehende `/cancel`-Block räumt es
mit auf.

Neue Nachricht wird an alle **anderen** aktiven Mitglieder mit
aktivierten Notifications verteilt (`context.bot.send_message()`,
Zustellfehler bei einzelnen Empfängern werden geloggt, nicht geworfen —
kein Abbruch der übrigen Zustellung). „🔔 Benachrichtigungen" ist ein
Toggle bei jedem Klick, persistiert über
`FamilyRepository.update_member()`/`FamilyService.set_notifications()`
(F1-Erweiterung).

### 6.7 F4 — Daily Family Challenges + Scheduler

`FamilyChallengeService` wählt **deterministisch** (`date.toordinal() %
3`, kein `random.choice`) einen von 3 zuverlässig aus der Play-History
berechenbaren Challenge-Typen:

| Typ | Frage | Korrekte Antwort |
|---|---|---|
| `family_top_artist_today` | „Welcher Künstler wurde heute in der Familie am häufigsten gehört?" | family-weit, aus `FamilyStatsService`-Timeline |
| `family_top_song_today` | „Welcher Song wurde heute in der Familie am häufigsten gehört?" | family-weit, aus `FamilyStatsService`-Timeline (additive Erweiterung: `top_song` je Periode) |
| `own_top_song_today` | „Welches Lied hast DU heute am meisten gehört?" | **pro Nutzer verschieden** — live gegen die echte `StatisticsCalculator.generate_timeline_stats()` ausgewertet, kein gespeichertes `correct_answer` |

`get_or_create_todays_challenge(family_id)` ist **idempotent pro Tag**
(sowohl ein manueller Menü-Klick als auch der tägliche Scheduler rufen
dieselbe Methode auf, ohne doppelte Challenges zu erzeugen). Eine
Antwort pro (Challenge, Nutzer) — keine Mehrfachwertung
(`FamilyChallengeRepository.has_answered()`).

**Scheduler** (`handlers/family_challenge_scheduler.py`): täglich um
`Config.FAMILY_CHALLENGE_TIME` (Default `20:00`, env-konfigurierbar).
Kein neuer Scheduling-Mechanismus — exakt dasselbe `asyncio.create_task`
+ `while True`/`asyncio.sleep`-Muster wie das bestehende
`PlayHistoryPoller` (Projekt nutzt kein python-telegram-bot-`JobQueue`
und keinen APScheduler/cron). Konstruiert/gestartet in `bot.py`
(`ExtendedBot.start_polling()`, Schritt 4b) statt in
`RichMenuHandler.initialize()`, weil er die echte `Bot`-Instanz
(`self.application.bot`) braucht. Broadcast **nur**, wenn die
Tages-Challenge durch diesen Lauf tatsächlich neu erzeugt wurde (kein
Doppel-Versand, falls ein Mitglied sie vorher schon manuell aufgerufen
hat).

Menü: neues Top-Level-Menü „🎯 Familien-Challenge" (Geschwister von
„💬 Familien-Chat"), „✅ Antworten" nutzt dasselbe Pending-State-Muster
wie F3 (`pending_answers: Dict[telegram_id, challenge_id]`).

### 6.8 F5 — Hardening

Audit-Ergebnis: die meisten Punkte aus der Hardening-Checkliste
(Berechtigungen, Family Isolation, Notifications, Challenge-Duplikate,
fremde Telegram-ID) waren durch F1–F4 bereits abgedeckt. Gezielt
nachgezogen:

- **Familienmitglieder ohne Plays**: charakterisiert, dass ein Mitglied
  ohne Wiedergaben in `per_member` schlicht fehlt (kein `0`-Eintrag) —
  kein Bug, aber dokumentationspflichtiges Verhalten für Aufrufer.
- **Tagesgrenzen** („Zeitzonen/Tagesgrenzen"): Eintrag exakt um
  Mitternacht zählt zu „heute", eine Mikrosekunde davor zu „gestern"
  (identisch zu `StatisticsCalculator`); eine gestern erzeugte Challenge
  blockiert nicht die heutige Neu-Erzeugung und bleibt selbst
  unverändert. **Kein** neues Zeitzonen-Handling eingeführt — das
  gesamte Projekt rechnet konsequent mit naivem, lokalem
  `datetime.now()`, Family Hub charakterisiert nur dasselbe Verhalten.
- **Isolations-Audit**: Grep-Durchlauf bestätigt, dass jede öffentliche
  `handle_*`-Methode in allen drei Handlern `is_active_family_member()`
  vor jedem Datenzugriff prüft, und `family_id` nie aus Nutzereingaben
  stammt.

### 6.9 Neue Config-Werte

```text
FAMILY_CHALLENGE_TIME=20:00   # optional, HH:MM lokale Bot-Zeit
```

### 6.10 Neue Callback-/Menü-IDs

`family_stats` (+ `family_stats_top_songs`/`_top_artists`/`_member`/
`_champion`/`_listening_times`/`_monthly_trend`), `family_chat` (+
`family_chat_send`/`_recent`/`_notifications`), `family_challenge` (+
`family_challenge_today`/`_answer`/`_leaderboard`) — alle als
`MenuItem`-IDs mit automatisch generiertem `callback_data=f"menu:{id}"`
(Standardmuster, kein neuer Callback-Präfix nötig).

### 6.11 Tests

| Datei | Tests |
|---|---|
| `tests/test_family_repository.py` | 14 (inkl. `update_member`) |
| `tests/test_family_service.py` | 21 (inkl. `set_notifications`, Isolation) |
| `tests/test_family_stats_service.py` | 18 (inkl. `top_song`) |
| `tests/test_family_stats_handler.py` | 10 |
| `tests/test_family_message_repository.py` | 11 |
| `tests/test_family_chat_service.py` | 14 |
| `tests/test_family_chat_handler.py` | 13 |
| `tests/test_family_challenge_repository.py` | 16 |
| `tests/test_family_challenge_service.py` | 25 (inkl. Cross-Family-ID-Kollision) |
| `tests/test_family_challenge_handler.py` | 13 |
| `tests/test_family_challenge_scheduler.py` | 10 |
| `tests/test_family_hardening.py` | 9 (F5, Mitglieder ohne Plays + Tagesgrenzen) |

Thematische Regressionsgruppe (F1–F5 + Statistik + User Management +
Menü + `PlayHistoryPoller`-Muster): **366 passed, 0 Regressionen**. Volle
Suite (Stand vor F4/F5, mit expliziter Nutzer-Freigabe ausgeführt):
**3186 passed, 1 failed (vorbestehend/unabhängig,
`test_artist_overrides_orphan_cleanup.py`), 1 skipped, 11 subtests
passed**. Volle Suite nach F4/F5 steht beim Nutzer aus (§8.A).

### 6.12 Offen / zurückgestellt

Von den 5 im Master-Prompt genannten Challenge-Typ-Beispielen wurden
bewusst nur 3 umgesetzt (siehe 6.7). Zurückgestellt, jeweils P3:

- **„Rate den Song"** — bräuchte eine Audio-/Lyrics-Snippet-Auslieferung
  über Telegram, kein bestehender Baustein dafür vorhanden.
- **„Erstelle eine Playlist mit 5 Songs für [Stimmung]"** — keine
  automatisch prüfbare korrekte Antwort, würde manuelle Bewertung
  erfordern.

Family Chat/Challenge sind aktuell nur für 2 Mitglieder (dkmd, marina)
nutzbar — bei einer Erweiterung der Familie ist ausschließlich
`data/family_data.json` zu pflegen (keine Codeänderung nötig).

### 6.13 Family Hub Navigation Restructuring (MASTER PHASE A, 2026-09-13)

**Auftrag:** F2 (Familien-Statistik), F3 (Familien-Chat) und F4
(Familien-Challenge) waren bislang über drei getrennte Zugriffspfade
erreichbar — F2 als Kind von „📊 Statistiken", F3/F4 als eigenständige
Top-Level-Menüs neben „📊 Statistiken". Master-Vorgabe: alle drei Bereiche
zu EINER Top-Level-Kategorie „👨‍👩‍👧‍👦 Familie" bündeln, ohne die fachliche
Logik von F2/F3/F4 anzufassen.

**Umsetzung:** rein navigatorische Änderung in
`handlers/menu/definitions.py::build_menu_tree()` — neuer, reiner
Navigations-Container `family` (`MenuItem(id="family", ...)`, kein
`handler=`, analog zu `stats_reviews`/`stats_rankings`) wird Kind von
`root_menu`; `family_stats_menu`/`family_chat_menu`/`family_challenge_menu`
werden per `add_child()` auf `family_menu` umgehängt (`.parent`
automatisch aktualisiert). `stats_menu.add_child(family_stats_menu)` und
die beiden `root_menu.add_child(family_chat_menu)`/
`root_menu.add_child(family_challenge_menu)`-Zeilen entfernt.

**Keine der 12 bestehenden Family-Callback-IDs wurde umbenannt** (alle
nutzen weiterhin das Standardmuster `callback_data=f"menu:{id}"`,
automatisch generiert aus der unveränderten ID) — nur ihre Position im
Baum ändert sich. Die Handler-Bindung (`handler=system._handle_family_*`)
ist unabhängig von der Baumposition und bleibt unverändert. Die
Zurück-/Breadcrumb-Navigation (`handlers/menu/rendering.py`) ist
vollständig generisch über `MenuItem.parent` implementiert — keine
Änderung dort nötig. `services/family/*`, alle drei Family-Handler
(`handlers/family_*_handler.py`) und `handlers/menu/actions/family.py`
wurden nicht angefasst.

**Effekt:** `root.children` 7 → 6 Einträge (`family_chat`/
`family_challenge` verschwinden als Root-Geschwister, tauchen jetzt unter
`family` auf); `stats.children` 5 → 4 Einträge (`family_stats` entfernt —
kein zweiter Zugriffspfad „Statistiken → Familien-Statistik" mehr).

**Tests:** `tests/test_menu_definitions.py` — der bisherige Pin-Test
`TestFamilyStatisticsUnchanged` (aus der vorherigen Statistics-UX-Phase,
die F2 explizit als „Kind von stats, nicht anfassen" schützte) wurde
durch `TestFamilyHubStructure` ersetzt, da genau diese Struktur nun
absichtlich geändert wurde — pinnt jetzt die neue Hub-Hierarchie
(`family` → `family_stats`/`family_chat`/`family_challenge`), unveränderte
Handler-Bindung/Titel/Emoji/`callback_data` für alle 12 Blattpunkte, sowie
„kein Family-Punkt mehr auf Root- oder Statistiken-Ebene". Root-
Kinderlisten-Test umbenannt/angepasst (sechs statt sieben Top-Level-Kinder).
Thematische Regressionsgruppe (Menu/Family/Stats, 18 Dateien): **335
passed, 0 Regressionen**.

### 6.14 Family Statistics Attribution, Identity & UX Optimization (MASTER PHASE B, 2026-09-13)

**Auftrag:** baut auf MASTER PHASE A auf (Family Hub bereits etabliert)
und optimiert ausschließlich F2 (die 6 Familien-Statistik-Funktionen):
korrekte Kalenderperioden, kollisionssichere Song-/Artist-Identity, echte
Member-Attribution statt reiner `(name, count)`-Tupel, Wiederverwendung
der kanonischen Statistics-Domain, konsistente Telegram-UX.

**Root-Cause-Befund:** `FamilyStatsService` verwendete bislang ein
Rolling-N-Day-Window (`_PERIOD_DAYS = {"week":7,"month":30,"year":365}`,
entfernt) statt echter Kalenderperioden — derselbe Bug, der in der
Personal-Statistics-„Statistics Menu UX & Architecture Optimization"-
Phase bereits behoben wurde. `top_songs`/`top_artists` gruppierten nur
über den rohen Titel-/Artist-String (Kollisionsrisiko, keine
Member-Attribution).

**Single Source of Truth statt zweiter Engine:** `FamilyStatsService`
hält jetzt intern eine `StatisticsCalculator`-Instanz (Komposition,
dieselbe `PlayHistoryRepository`) und nutzt deren kanonische Bausteine
wieder — `_calendar_period_bounds()`/`_parse_history_entries()`
(Instanzmethoden), `_identity_key()`/`_split_artists()` (statisch).
`StatisticsCalculator` selbst bleibt dabei unverändert (0 Zeilen Diff).

**Neues Datenmodell** (`generate_family_stats()`): `top_songs`/
`top_artists` sind jetzt Listen strukturierter Dicts statt Tupeln —
`{"title", "artists" (roher Artist-String), "total_plays", "members":
[{"telegram_id", "display_name", "plays"}, ...]}` bzw. `{"artist",
"total_plays", "members": [...]}`. Song-Identity über `_identity_key()`
(Artist+Titel, kollisionssicher). Artist-Identity über `_split_artists()`
PLUS eine neue, **familien-spezifische** Case-insensitive-Aggregation
(casefold-Schlüssel, Anzeigewert = häufigste Original-Schreibweise,
Ties → zuerst gesehen) — bewusst NICHT in `_split_artists()` selbst
verortet (das bliebe sonst eine zweite, von der Personal-Statistics-
Verwendung abweichende Regel; Personal Statistics bleibt bewusst
case-sensitiv). `top_albums` entfernt (0 Consumer, kein Menüpunkt,
analog zur Personal-Statistics-„Output Optimization"-Phase). Kein
Cross-Member-Deduplication — jeder reale Play zählt separat.
`period_start`/`period_end` neu im Rückgabewert (Grundlage für die
Datumsbereich-Header, siehe unten).

**Bewusst unverändert:** `generate_family_timeline()` — bereits
kalenderbasiert (eigene, seit F2 etablierte Logik), keine der 6
F2-Menüfunktionen, sondern eine geteilte Abhängigkeit von F4
(`family_challenge_service.py`s `family_top_artist_today`/
`family_top_song_today`-Korrektantwort). Ohne konkrete Regression bleibt
sie unangetastet — verwendet weiterhin ihre eigene
`_load_all_entries()`/`_FamilyEntry`-Infrastruktur.

**Geteiltes Format-Helper-Modul** (`handlers/statistik_format_helpers.py`,
neu): `format_plays()`/`format_rank()`/`format_date_range()`/`SEPARATOR`
1:1 aus `mugge_statistik_handler.py::StatistikHandler` extrahiert — dessen
gleichnamige Instanzmethoden sind jetzt dünne Delegatoren (Call-Sites/
Tests dort unverändert lauffähig). `handlers/family_stats_handler.py`
importiert direkt aus dem geteilten Modul — eine Formatierungsquelle
statt einer zweiten, potenziell abweichenden Kopie.

**UX-Umbau** (`handlers/family_stats_handler.py`): alle 6 Methoden nutzen
jetzt Medaillen (🥇🥈🥉, ab Rang 4 numerisch), Play-Pluralisierung
(„1 Play"/„2 Plays"), Datumsbereich-Header (`format_date_range()`, gleiche
Darstellung wie Personal Statistics — kein zweites Datumsformat) und den
20-Zeichen-Trenner vor der Familien-Gesamtzeile. Top-Songs/-Artists zeigen
Member-Zeilen (`👤 Name · X Plays`); eine zusätzliche „📊 Gesamt · N
Plays"-Zeile erscheint nur, wenn mehr als ein Mitglied beteiligt ist
(kein redundanter Wert bei genau einem Hörer). „Statistik pro Person"
zeigt zusätzlich den Prozentanteil (1 Dezimalstelle, deutsches
Komma-Format). „⏰ Hörzeiten" → „⏰ Hör-Aktivität" (Text UND Menü-Titel in
`definitions.py`, keine Callback-ID-Änderung) — vermeidet den
irreführenden Eindruck einer echten Hördauer-Messung. „📈 Monatsentwicklung"
zeigt jetzt deutsche Monatsnamen (`GERMAN_MONTHS`, kanonische Quelle)
statt roher `"YYYY-MM"`-Schlüssel.

**Tests:** `tests/test_family_stats_service.py` komplett auf injiziertes
`now` umgestellt (Kalenderperioden statt Rolling-Window können sonst an
Monats-/Jahresgrenzen flakey werden) — neue Testgruppen für
Kalenderperioden/Artist-Case-Insensitivität/Song-Identity/Family-
Aggregation/Member-Attribution/Artist-Attribution sowie ein
Konsistenz-Test, der Family-Attribution eines Mitglieds gegen
`StatisticsCalculator.generate_stats()` für denselben Navidrome-User
prüft. `tests/test_family_stats_handler.py` auf neue Datenstruktur
umgestellt, neue UX-Assertions. Neues `tests/test_statistik_format_helpers.py`
für das extrahierte Modul. `tests/test_family_hardening.py`/
`test_family_challenge_*` unverändert grün (keine Kopplung an die
geänderten Felder/mocken `generate_family_timeline()` vollständig).

Thematische Regressionsgruppe (F2/Family/Stats/Menu, 19 Dateien): **509
passed, 0 Regressionen**.

---

## 7. Muster für künftige Menü-Erweiterungen

Bei jeder neuen Menüfunktion (neuer Button, neuer Callback-Präfix):

1. `MenuItem` in `handlers/menu/definitions.py::build_menu_tree()`
   ergänzen (bzw. bestehendes Item mit `handler=`/`is_action=True`
   versehen) — seit ARCH-024 nicht mehr in `RichMenuSystem` selbst.
2. Die eigentliche Fachlogik als Funktion im passenden
   `handlers/menu/actions/<domäne>.py`-Modul implementieren (neue Domäne
   nur bei echter fachlicher Eigenständigkeit, sonst in eine bestehende
   Domäne einordnen), plus einen dünnen `_handle_*`-Delegator in
   `RichMenuSystem`/`RichMenuHandler`, der die aktuellen Abhängigkeiten
   (Handler-Referenzen, Config, Logger) explizit übergibt — keine
   Rückreferenz aus `actions/` auf `RichMenuSystem`/`RichMenuHandler`.
   Bei dynamischen/externen Inhalten (Titel, URLs, Nutzereingaben)
   **kein** `parse_mode="Markdown"` verwenden, sofern der Text nicht
   nachweislich vollständig statisch ist (siehe Bug D, Abschnitt 3.3).
   Handelt es sich stattdessen um reinen Command-/Help-/Begrüßungs-
   Content (User-Facing Presentation ohne fachliche Domain-Aktion, wie
   `/start`/`/help`) statt einer Domain-Action: in
   `handlers/menu/content/` einordnen (seit ARCH-025), nicht in
   `actions/` — `RichMenuHandler` behält dafür einen dünnen
   Command-Adapter (Maintenance-Gate + Activity-Tracking + Delegation).
3. Bei einem **neuen** Callback-Präfix: `CallbackQueryHandler(...,
   pattern="^<präfix>:")` in `RichMenuHandler.get_telegram_handlers()`
   ergänzen — sonst verpufft der Klick stillschweigend (Bug B).
4. Prüfen, ob der Präfix in `_ADMIN_ONLY_PREFIXES` gehört.
5. „Keine toten Buttons": ein Button darf nur angezeigt werden, wenn die
   zugehörige Aktion im aktuellen Zustand tatsächlich sinnvoll ist
   (Vorbild: „❌ Abbrechen" nur bei tatsächlich aktivem Download).
6. Tests: mindestens Rendering (Text/Buttons je nach Zustand), Callback-
   Dispatch, und — falls Blockierung möglich (langlaufende Aktion) —
   Regressionstest analog `TestProcessUrlRunsAsBackgroundTask` (Bug A).
7. Dieses Dokument (Abschnitt 2/3) und ggf. `docs/FINDINGS_INDEX.md`
   aktualisieren.

---

## 8. Telegram Start/Help/Menu UX Finalization v2 (2026-09-13)

### 8.1 Auftrag

Nutzer-Vorgabe: `/start`, `/menu`, `/help` final auf konsistentes Layout
und eine einzige, zentrale Menüarchitektur bringen — explizit **keine**
zweite, parallele Menüimplementierung für `/start`.

### 8.2 Docs↔Code-Delta (vor der Umsetzung festgestellt)

Zwei reale Abweichungen zwischen beabsichtigter Architektur
(„eine zentrale Main-Menu-Definition") und tatsächlichem Code:

1. **`/start` rief nie `RichMenuSystem.show_menu()` auf.**
   `content/greeting.py::send_start_message()` baute stattdessen eine
   eigene, vollständige Feature-Liste (aus
   `user_context.FEATURES`/`get_available_features()`, eigene
   Rollen-Hierarchie-Prüfung) **und** eine eigene Tastatur
   (`InlineKeyboardButton` pro Feature + eigener „🏠 Hauptmenü"-Button,
   der erst per Klick zum echten Hauptmenü führte) — eine zweite,
   inhaltlich redundante Menüdarstellung mit eigener,
   parallel zur `AccessLevel`-Architektur laufender Sichtbarkeitsprüfung.
2. **`user_context.FEATURES` enthielt erfundene Commands.** Jeder
   Eintrag hatte ein `"commands"`-Feld (`/download`, `/stats`, `/month`,
   `/year`, `/navidrome`, `/search`, `/admin`, `/users`, `/tests`) — real
   registriert sind ausschließlich `/start`, `/menu`, `/help`
   (`RichMenuHandler.get_telegram_handlers()`); `/cancel` funktioniert
   als Freitext-Schlüsselwort (`text_workflow_dispatcher.py`), ist aber
   kein `CommandHandler`. Der einzige Konsument dieses Felds
   (`content/help.py::send_help_message()`) zeigte diese erfundenen
   Befehle direkt im `/help`-Text an. `HELP_NAVIDROME` referenzierte
   zusätzlich ein nie existierendes `/search`.

Keine weiteren Abweichungen gefunden — Maintenance Gate, Activity
Tracking, Access-Level-Architektur, Session-/Callback-/`message_id`-
Handling und die Content-/Rendering-/Actions-Trennung (ARCH-024/025)
entsprachen bereits der Dokumentation und wurden **nicht** verändert.

### 8.3 Umsetzung

**`/start` = Begrüßung + zentrales Hauptmenü, eine Nachricht:**
`rendering.show_menu()`/`RichMenuSystem.show_menu()` haben ein neues,
optionales `header_text`-Argument — wird es gesetzt, steht es vor dem
regulären Menütext derselben, unveränderten `render_menu()`/
`get_menu_text()`-Ausgabe. Bei `header_text=None` (z. B. jeder
`/menu`-Aufruf, jede Navigation) ist das Verhalten exakt wie zuvor.

`content/greeting.py::send_start_message()` baut jetzt nur noch einen
kurzen Begrüßungstext (Name + optionale, dezente Rollenzeile bei
moderator/admin/owner + Trennlinie `──────────────`, derselbe
Divider-Stil wie in `handlers/mugge_statistik_handler.py`) und ruft
`menu_system.show_menu(update, context, "main", header_text=welcome_text)`
— keine eigene Feature-Liste, keine eigene Tastatur mehr. `menu_system`
wird dafür als zusätzliche, explizite Abhängigkeit übergeben
(`RichMenuHandler` hält bereits `self.menu_system`). Ergebnis: `/start`
und `/menu` zeigen exakt dieselbe Tastatur, dieselbe
`AccessLevel`-Filterung, denselben Navigationszustand.

`root_menu.description` (`"Willkommen beim Musik-Bot"`) wurde entfernt
— stand zuvor bei **jedem** `/menu`-Aufruf und jedem Klick auf
„🏠 Hauptmenü" im Text, was neben der neuen, personalisierten
`/start`-Begrüßung eine Doppelinformation gewesen wäre.

**Keine Fake-Commands mehr:** `user_context.FEATURES`s `"commands"`-Feld
wurde ersatzlos entfernt (kein Ersatz durch Verzeichnis-/Pseudo-Befehle
— die tatsächliche Bedienung läuft über `/menu`). `help.py`s
Pro-Feature-Zeile zeigt entsprechend keine Befehle mehr an; die
allgemeinen, tatsächlich existierenden Befehle (`/start`/`/menu`/
`/help`/`/cancel`) bleiben unverändert im „⚡ Allgemeine Befehle"-Block.
`HELP_NAVIDROME` verweist jetzt auf `/menu → 🎵 Navidrome Mediathek`
statt auf das nie existierende `/search`. `HELP_CMD_START` beschrieb
`/start` bisher fälschlich als „Bot neu starten" (das tut nur der
separate, admin-only „🔄 Bot neu starten"-Button/`BotRestartHandler`,
via `systemctl restart`) — korrigiert auf „Begrüßung & Hauptmenü
anzeigen".

**`/help`-Gruppierung unverändert belassen:** `send_help_message()`
gruppierte bereits vor dieser Phase nach Feature-Bereich (Downloads/
Statistiken/Navidrome/Administration, rollenabhängig über dieselbe
`get_available_features()`) — entspricht der gewünschten Struktur, kein
Umbau nötig.

**Premium-/Rollen-Darstellung (geprüft, bewusst nicht eingeführt):** die
bestehende Access-Architektur (`AccessLevel` in `models.py`/
`permissions.py`) kennt ausschließlich PUBLIC/USER/MODERATOR/ADMIN/
OWNER — kein „Premium"-Konzept. Ein „⭐ Premium"-Divider wäre reine
Fiktion ohne Rückhalt in der Access-Control gewesen (Master-Prompt
Abschnitt 9 verbietet genau das). Stattdessen wird die bereits
vorhandene, rein dekorative Rollenzeile (`get_user_role()` — ein von
`AccessLevel` bewusst getrennter Begrüßungs-/Hilfetext-Belang, siehe
`user_context.py`-Docstring, ARCH-021/P-3) in der `/start`-Begrüßung
weiterverwendet: eine Zeile, nur für moderator/admin/owner sichtbar,
steuert keinerlei Sichtbarkeit von Menüpunkten.

**Markdown-Robustheit:** der Telegram-Username/Vorname wird vor dem
Einsetzen in den fett formatierten Begrüßungstext escaped
(`content/greeting.py::_escape_markdown()`, dieselbe Legacy-Markdown-
Sonderzeichen-Menge `_ * `` [` wie in `enhanced_status_handler.py`) —
ohne Escaping hätte ein Username wie „john_doe" zu
`BadRequest: Can't parse entities` geführt (dieselbe Fehlerklasse wie
`docs/FINDINGS_INDEX.md`, dl:-Menüs mit dynamischen Inhalten).

### 8.4 Geänderte Dateien

`handlers/menu/rendering.py` (`header_text`-Parameter),
`handlers/menu/rich_menu_system.py` (`show_menu()` reicht `header_text`
durch), `handlers/menu/content/greeting.py` (Neuschreibung: kurze
Begrüßung statt Feature-Liste/eigene Tastatur), `handlers/menu/content/
messages.py` (GREETING_*-Konstanten reduziert, `/search`-Fix in
`HELP_NAVIDROME`), `handlers/menu/content/user_context.py`
(`"commands"`-Feld aus `FEATURES` entfernt), `handlers/menu/content/
help.py` (Pro-Feature-„Befehle:"-Zeile entfernt),
`handlers/menu/rich_menu_handler.py` (`menu_system` an
`send_start_message()` übergeben), `handlers/menu/definitions.py`
(`root_menu.description` entfernt).

### 8.5 Tests

Neu: `tests/test_menu_content_greeting.py` (11), `tests/
test_menu_content_help.py` (9), `tests/test_menu_content_user_context.py`
(2), `TestShowMenuHeaderText` in `tests/test_rich_menu_system.py` (4),
`test_root_menu_has_no_static_welcome_description` in `tests/
test_menu_definitions.py`. Angepasst (Verhaltensänderung, keine
Abschwächung): `tests/test_rich_menu_handler_maintenance_gate.py` (2
Tests prüften bisher `update.message.reply_text` direkt für `/start` —
prüfen jetzt `menu_system.show_menu(header_text=...)`, da `/start` seine
Nachricht nicht mehr selbst verschickt), `tests/
test_rich_menu_handler_activity_tracking.py` (`_make_handler()`:
`menu_system.show_menu` explizit als `AsyncMock` vorbelegt). Thematische
Regressionsgruppe (Menu/Content/Rendering/Permissions/Access-Control):
**234 passed, 0 Regressionen.**

### 8.6 Bewusst nicht verändert

Keine Änderung an: Maintenance Gate, Activity Tracking, Session-
Management, Callback-Routing (`RichMenuSystem.handle_callback()`),
`actions/`-Domänen, Access-Level-Architektur selbst, `/help`-Gruppierung
(bereits korrekt), `handlers/menu/`-Modulstruktur (ARCH-024/025 bleiben
unverändert gültig).

---

## 9. Statistics Menu UX & Architecture Optimization (2026-09-13)

### 9.1 Auftrag

Nutzer-Vorgabe: audit-basierte Optimierung des persönlichen Telegram-
Statistiksystems — Menüstruktur, Kalenderperioden-Logik, Timeline-
Darstellung, Track-Identität. **Explizit außerhalb des Scopes:**
Familien-Statistik (`family_stats`-Zweig, `services/family/`) —
unangetastet, siehe Abschnitt 9.6.

### 9.2 Docs↔Code-Delta (Audit vor der Umsetzung)

**Kritischer Befund:** `StatisticsCalculator.generate_stats()`
(genutzt von `stats_monthly`/`stats_yearly`/`stats_top_songs`/
`stats_top_artists`) filterte über ein reines **Rolling-N-Day-Window**
(`period_map={"week":7,"month":30,"year":365}` +
`datetime.now() - timedelta(days=days)`), keine echte Kalenderperiode —
die Texte bestätigten es explizit ("Monatsrückblick (**30 Tage**)",
"Jahresrückblick (**365 Tage**)"). `generate_timeline_stats()`
(genutzt von `stats_timeline`) war dagegen bereits kalenderbasiert
(Montag-Wochenstart, Monatserster), aber ohne Jahres-Periode, ohne
Datums-Label in der Darstellung und ohne Zukunfts-Timestamp-Schutz.

**Track-Identität:** `song_counts`/`album_counts`/`first_seen` waren in
beiden Funktionen nur nach Titel/Albumname gruppiert — zwei Künstler
mit gleichnamigem Song/Album wurden fälschlich zusammengeführt.

**Menüstruktur:** die 5 Rückblick-/Ranking-Buttons lagen unstrukturiert
direkt unter „Statistiken", ohne Rückblick-/Ranking-Trennung; kein
Wochen-Rückblick vorhanden.

Keine weiteren Abweichungen: User-Isolation (`PlayHistoryRepository`,
strikt pro-Username-Datei) war bereits sauber; die ARCH-024/025-
Registrierungsarchitektur (Callback-IDs ohne `handler=` in
`definitions.py`, Bindung zur Laufzeit über
`RichMenuHandler._register_stats_handlers()`) war bereits korrekt und
wurde unverändert fortgeführt.

### 9.3 Kalenderlogik (Kernänderung)

`StatisticsCalculator._calendar_period_bounds(period, now=None)` ist
jetzt die **einzige** Stelle im Projekt, die Kalendergrenzen berechnet
("today"/"week"/"month"/"year", Montag als Wochenbeginn) — von
`generate_stats()` (week/month/year) **und** `generate_timeline_stats()`
(today/week/month) gemeinsam genutzt. `now` ist optional injizierbar
(deterministische Tests). Kein Rolling-Window mehr:

| Periode | Start | Ende (exklusiv) |
|---|---|---|
| „Diese Woche" | Montag 00:00 der aktuellen Kalenderwoche | folgender Montag 00:00 |
| „Dieser Monat" | 1. des aktuellen Monats, 00:00 | 1. des Folgemonats |
| „Dieses Jahr" | 1.1. des aktuellen Jahres, 00:00 | 1.1. des Folgejahres |

Anzeige (`StatistikHandler._format_period_label()`): „Diese Woche ·
07.09.2026" (Montag-Datum, nicht das heutige Datum), „Diesen Monat ·
September 2026", „Dieses Jahr · 2026" — ersetzt die alten,
irreführenden „(30 Tage)"/„(365 Tage)"-Labels. Deutsche Monatsnamen
über eine einfache lokale Konstante (`_GERMAN_MONTHS`), bewusst kein
`locale.setlocale()` (prozessweiter, nicht-thread-sicherer globaler
Zustand, im Projekt bisher nirgends verwendet).

**Keine Datenverluste:** Kalenderperioden sind ausschließlich Filter-/
Auswertungsgrenzen auf der bereits vorhandenen Play-History. Kein
Löschen, kein Reset, keine Datei-/Eintrags-Mutation — ein neuer Monat/
eine neue Woche entsteht rein durch die Zeitberechnung beim nächsten
Aufruf.

### 9.4 Track-Identität

`StatisticsCalculator._identity_key(track, field)` gruppiert Titel/Album
INTERN immer kombiniert mit dem Artist (`(artist, titel)`-Tupel) -
verhindert, dass „Artist A – Song X" und „Artist B – Song X" als
derselbe Track gelten und ihre Play-Counts vermischt werden (betraf
`top_songs`/`top_albums`/Timeline
`most_replayed_track`/`top_album`/„neue Tracks"-Erkennung). Das im
Track-Dict bereits vorhandene Navidrome-`id`-Feld
(`play_history_poller.py`) identifiziert zwar den konkreten Song
eindeutig, eignet sich aber nicht als Gruppierungsschlüssel über
mehrere Wiedergaben hinweg (kann pro Wiedergabe variieren).

**Korrektur nach Live-Regressionsfund:** die erste Implementierung
dieser Phase gab den kombinierten String (`"Song X – Artist A"`) auch
als sichtbaren Wert zurück. Der volle Testlauf des Nutzers deckte auf,
dass `services/family/family_challenge_service.py` (Family-Challenge-
Typ `own_top_song_today`, **nicht Teil dieser Phase**)
`most_replayed_track[0]` wörtlich mit einer per Telegram eingegebenen
Nutzerantwort vergleicht — der geänderte String brach 3 bestehende
Family-Challenge-Tests. Da Familien-Code laut Auftrag nicht angefasst
werden darf, bleibt der nach außen sichtbare Wert (`top_songs`/
`top_albums`/`most_replayed_track`/`top_album`) jetzt bewusst der reine
Klartext-Titel/Albumname wie vor dieser Phase — nur die interne
Gruppierung ist kollisionssicher. Zwei kollidierende Einträge erscheinen
dadurch als zwei separate Zeilen mit demselben sichtbaren Namen, aber
korrekt getrennten Play-Counts, statt fälschlich zu einer Zeile
vermischt zu werden. `ChartRenderer` benötigte keine Anpassung (erwartet
weiterhin generische `(label: str, count: int)`-Tupel).

**Zusätzlich im selben Regressionsfund korrigiert:** der neue
Zukunfts-Timestamp-Schutz in `_parse_history_entries()` verglich
zunächst sekundengenau gegen `datetime.now()` - das ließ einen
legitimen, „heute Mittag" datierten Test-Fixture-Eintrag
(`tests/test_family_challenge_service.py::_play_entry()`, feste Stunde
12:00 unabhängig von der tatsächlichen Ausführungszeit) fälschlich als
„Zukunft" erscheinen, wenn die Suite vormittags lief. Der Vergleich ist
jetzt tagesgenau (`entry_time.date() > now.date()`) - für die
Kalenderperioden-Zuordnung (today/week/month/year) macht die Uhrzeit
innerhalb desselben Tages ohnehin keinen Unterschied.

### 9.5 Menüstruktur & Wochen-Rückblick

Neue reine Navigations-Container (kein eigener Handler, wie
`family_stats` selbst) unter `stats`: `stats_reviews` („📅 Rückblicke")
und `stats_rankings` („🏆 Rankings"). Die 5 bestehenden Callback-IDs
(`stats_monthly`/`_yearly`/`_top_songs`/`_top_artists`/`_timeline`)
bleiben **unverändert** — nur Position im Baum und sichtbarer
Button-Titel ändern sich (Master-Prompt: „Bestehende Callback-IDs nach
Möglichkeit erhalten"). `stats_timeline`/`stats_library_overview`
bleiben direkte Kinder von `stats` (Timeline ist konzeptionell kein
Rückblick/Ranking).

**Neu: `stats_weekly`** („Diese Woche") — `StatistikHandler.handle_week_review()`,
analog zu `handle_month_review()`/`handle_year_review()` (Top-10
Songs/Künstler/Alben + 2 Chart-Bilder für exakt eine Kalenderperiode).
Alle drei Rückblick-Methoden teilen sich jetzt eine private
`_handle_period_review()`-Implementierung (vermeidet eine dritte
Kopie derselben ~50 Zeilen).

**Entscheidung gegen einen redundanten zweiten Wochen-Handler (Master-
Prompt Phase 14, Option A gewählt):** Music Timeline deckte die
Kalenderwoche bereits ab, aber als verdichtete Übersicht (je ein
Top-Artist/-Album/meistgehörter Track, keine vollständige Top-10-Liste,
keine Chart-Bilder). „Diese Woche" liefert dieselbe Darstellungstiefe
wie die bestehenden Monat-/Jahres-Rückblicke — ein echter fachlicher
Mehrwert, kein Duplikat.

Button-Umbenennungen (IDs unverändert): „Monatsrückblick" →
„Dieser Monat", „Jahresrückblick" → „Dieses Jahr", „Library Übersicht"
→ „Meine Library". Emoji-Korrektur: `stats_timeline` 📅→📈 (behob eine
Kollision mit `stats_monthly`, die beide zuvor 📅 trugen).

### 9.6 Familien-Statistik — UNVERÄNDERT

Keine Datei unter `services/family/`, `handlers/family_*` oder die
`family_stats_menu`-Definition/-Handler-Bindungen in `definitions.py`
wurde angefasst — per Regressionstest gepinnt
(`tests/test_menu_definitions.py::TestFamilyStatisticsUnchanged`).

### 9.7 Geänderte Dateien

`services/statistik/statistics_calculator.py` (Kalenderlogik,
Track-Identität, gemeinsames History-Parsing), `services/statistik_service.py`
(`now`-Parameter durchgereicht), `handlers/mugge_statistik_handler.py`
(`handle_week_review()`, `_format_period_label()`, gemeinsame
`_handle_period_review()`, Timeline-Datumslabels),
`handlers/menu/definitions.py` (Menü-Restrukturierung),
`handlers/menu/actions/stats.py` (`handle_weekly_stats_wrapper`),
`handlers/menu/rich_menu_handler.py` (`_handle_weekly_stats_wrapper` +
Registrierung).

### 9.8 Tests

`tests/test_statistics_calculator.py` (komplett überarbeitet — feste
`now`-Referenzdaten statt real-zeit-relativer `days_ago`-Werte;
`TestCalendarPeriodBounds` deckt Wochenbeginn Montag/Dienstag/Sonntag,
Monats-/Jahreswechsel innerhalb einer Woche, exakte Wochengrenzen,
Monatserster/-letzter, Februar/Schaltjahr, Jahresgrenzen ab;
`TestGenerateTimelineStats` — bisher 0 Tests trotz nicht-trivialer
Logik — deckt heute/Woche/Monat, leere History, Kollisionsschutz, neue
Tracks, Zukunfts-Timestamps, fehlende/0/große Duration ab;
`TestTrackIdentityCollisionSafety`; `TestUserIsolation`),
`tests/test_statistik_service.py`/`tests/test_statistics_calculator_export_atomic_write.py`
(fragile `days_ago`-Werte auf `0` vereinheitlicht — Kalendergrenzen-
Detailtests liegen jetzt ausschließlich in `test_statistics_calculator.py`),
`tests/test_mugge_statistik_handler.py` (+8: `handle_week_review()`,
Kalender-Label-Header, Timeline-Datumslabels), `tests/test_menu_definitions.py`
(+9: `stats_reviews`/`stats_rankings`-Struktur, Family-Statistics-
Unverändert-Pin), `tests/test_menu_actions_stats.py` (+3: Weekly-Wrapper),
`tests/test_rich_menu_handler.py` (+2: alle 6 Stats-IDs korrekt/eindeutig
registriert). `tests/test_family_challenge_service.py` **nicht
geändert** - lief nach der in Abschnitt 9.4 beschriebenen
Produktionscode-Korrektur (Klartext-Werte statt Composite-Label)
unverändert wieder grün, kein Test-Fake/keine Abschwächung nötig.
Thematische Regressionsgruppe (Menu/Stats/gesamter Family Hub F1–F5,
23 Dateien): **428 passed, 0 Regressionen** (nach Korrektur des
zunächst selbst verursachten Regressionsfunds, siehe 9.4).

---

## 10. Statistics Menu UX & Output Optimization (2026-09-13)

Direkte Folgephase auf Abschnitt 9 (kein erneuter Architektur-Audit) -
reine Output-/UX-Optimierung der drei Rückblicke (Woche/Monat/Jahr) und
der beiden Rankings (Top Songs/Top Künstler).

### 10.1 Änderungen

- **Top Alben entfernt.** `generate_stats()` berechnet `album_counts`/
  `top_albums` nicht mehr - einziger Konsument war die Album-Sektion der
  Rückblick-Anzeige, die entfällt.
- **PNG-Charts entfernt.** `_handle_period_review()`/`handle_top_songs()`/
  `handle_top_artists()` senden keine Chart-Bilder mehr - reine
  Text-Antwort, kein Warten auf `matplotlib`-Rendering. Dadurch wurde
  `ChartRenderer`/`create_chart()` beweisbar toter Code (0 verbleibende
  Aufrufer, repoweit verifiziert): `services/statistik/chart_renderer.py`,
  der `StatistikService`-Wrapper, `tests/test_chart_renderer.py`,
  `tests/test_chart_renderer_thread_safety.py` und
  `tests/test_mugge_statistik_handler_event_loop_blocking.py` (testete
  ausschließlich das jetzt entfallene Chart-Routing über
  `asyncio.to_thread()`) entfernt; `matplotlib` aus `requirements.txt`
  (einziger Verwender war `chart_renderer.py`).
- **Top Songs verbessert.** `top_songs` (aus `generate_stats()`) zeigt
  jetzt „Titel — Artist" statt reinem Titel. Anders als
  `generate_timeline_stats()`s `most_replayed_track` (weiterhin
  Klartext, siehe Abschnitt 9.4 - `family_challenge_service.py`
  vergleicht dort wörtlich gegen eine Nutzereingabe) ist `top_songs`
  durch keinen Familien-Code eingeschränkt (repoweit verifiziert) -
  macht kollidierende Einträge (gleicher Titel, verschiedene Artists)
  selbsterklärend statt zweier optisch identischer Zeilen.
- **Top Künstler geprüft.** Ranking nach Play-Count bestätigt als
  korrekter, erwarteter Maßstab - kein struktureller Fehler gefunden,
  keine Änderung nötig außer der Konsistenz-Punkte unten.
- **Woche/Monat/Jahr** bleiben über die gemeinsame
  `_handle_period_review()` vereinheitlicht (jetzt schlanker: nur noch
  Songs + Künstler, kein Alben-/Chart-Code-Pfad).
- **Leere Perioden.** `generate_stats()` liefert bei einem Account MIT
  Verlauf, aber 0 Plays in der angefragten Kalenderperiode, jetzt ein
  gültiges Dict (`total_plays=0`, leere Top-Listen, `period_start`/
  `period_end` gesetzt) statt `None`. `None` bleibt reserviert für
  „Account hat überhaupt keinen Verlauf". Die Handler zeigen dadurch
  eine periodenbezogene Meldung („📅 Diese Woche · 07.09.2026 für dkmd:
  Noch keine Wiedergaben in diesem Zeitraum.") statt der generischen
  „⚠️ Keine Daten verfügbar."-Meldung.
- **Lange Namen.** Neuer `StatistikHandler._truncate()`-Helfer (Kappung
  bei 45 Zeichen + „…") auf allen Song-/Künstler-/Album-Labels in
  Rückblicken, Rankings und Timeline angewendet.

### 10.2 Geänderte/entfernte Dateien

Geändert: `services/statistik/statistics_calculator.py`,
`services/statistik_service.py`, `handlers/mugge_statistik_handler.py`,
`requirements.txt`. Entfernt: `services/statistik/chart_renderer.py`,
`tests/test_chart_renderer.py`,
`tests/test_chart_renderer_thread_safety.py`,
`tests/test_mugge_statistik_handler_event_loop_blocking.py`.

### 10.3 Tests

`tests/test_statistics_calculator.py` (Leer-Perioden-Semantik,
Artist-Suffix bei `top_songs`, `top_albums` entfernt-Regressionstest),
`tests/test_statistik_service.py` (Facade-Ebene analog),
`tests/test_mugge_statistik_handler.py` (+~20: keine PNG-Charts mehr
gesendet, keine Alben-Sektion mehr, Leer-Perioden-Meldung, neue
`TestHandleTopArtists`-Klasse - bisher 0 Tests trotz eigenständiger
Methode, `TestTruncate`). Thematische Regressionsgruppe (Menu/Stats/
gesamter Family Hub): **440 passed, 0 Regressionen.**

### 10.4 Family Statistics — weiterhin UNVERÄNDERT

Keine Datei unter `services/family/`/`handlers/family_*` angefasst
(git status bestätigt). `family_challenge_service.py`s Abhängigkeit von
`most_replayed_track[0]` als Klartext-String war bereits in Abschnitt
9.4 berücksichtigt und bleibt unverändert kompatibel (dort wird nichts
in dieser Phase geändert).

---

## 11. Statistics UX & Architecture (v Final) (2026-09-13)

Direkte Folgephase auf Abschnitt 10 (kein erneuter Architektur-Audit) -
konsistentes, robustes, rückwärtskompatibles Layout für Wochen-/Monats-/
Jahresstatistik. Neuer Jahres-Datensatz mit KPIs/Highlight/
Monatsdiagramm.

### 11.1 Rückwärtskompatibilität (zentrale Leitplanke dieser Phase)

`stats["top_artists"]`/`stats["top_songs"]` (aus `generate_stats()`)
bleiben semantisch **unverändert** - weiterhin von `handle_top_songs()`/
`handle_top_artists()` (Rankings-Menü), `get_play_count_by_artist()`
und `export_stats_to_json()` genutzt. Zwei ADDITIVE Felder ergänzt:

- `top_songs_detailed: List[(title, artists, count)]` - `artists` ist
  der vollständige Roh-Artist-String, KEINE "title — artist"-Kombination
  zum späteren Reparsen.
- `top_artists_split: List[(artist, count)]` - wie `top_artists`, aber
  mit `_split_artists()` VOR der Aggregation (ein Play kann mehreren
  Artists gutgeschrieben werden, die Summe kann daher > `total_plays`
  sein).

Geprüfte Consumer (repoweit gegrept, keiner betroffen): `handlers/
family_stats_handler.py` nutzt eine komplett eigenständige
`FamilyStatsService`, nicht `StatisticsCalculator` - unberührt.
`services/family/family_challenge_service.py`s `most_replayed_track`-
Abhängigkeit (aus `generate_timeline_stats()`, siehe Abschnitt 9.4)
bleibt unverändert, da Timeline in dieser Phase nicht angefasst wurde.

### 11.2 Artist-Splitting

`StatisticsCalculator._split_artists()` (neu) trennt NUR an `" • "` und
`" & "` - explizit NICHT an `"/"`, `","`, `"feat."`, `"ft."` (Beispiele:
"Miksu/Macloud" bleibt ein Artist, "Artist feat. Artist" bleibt
unverändert). Wird VOR jeder Ranking-Auswahl angewendet (Rohdaten-Ebene,
nicht auf bereits gekürzte Top-5-Strings). Bekannter, bewusst
hingenommener Grenzfall: ein Bandname, der selbst " & " enthält (z. B.
"Simon & Garfunkel"), würde nach dieser Regel in zwei Artists zerlegt -
der Master-Prompt definiert die Trenner-Menge explizit und abschließend
ohne Ausnahme für solche Fälle.

### 11.3 Unique Identity (Songs/Artists/Albums)

`total_songs`/`total_artists`/`total_albums` (nur `generate_year_stats()`)
werden aus der VOLLSTÄNDIGEN Jahres-History bestimmt (nicht aus den auf
10 gekappten Top-Listen abgeleitet) - `total_songs`/`total_albums` über
das bestehende `_identity_key()` (Artist+Feld, kollisionssicher, siehe
Abschnitt 9.4), `total_artists` über dieselben `_split_artists()`-Regeln
wie `top_artists_split`. `_identity_key()` wurde zusätzlich gehärtet:
`track.get(field) or "Unbekannt"` statt nur `.get(field, "Unbekannt")` -
fängt jetzt auch einen vorhandenen, aber leeren Artist-/Titel-/
Albumwert ab (nicht nur den fehlenden Schlüssel), an EINER zentralen
Stelle statt dupliziert im Renderer (Master-Prompt Abschnitt 10).

### 11.4 `_format_period_label()` und Music Timeline

Vor jeder Änderung wurden alle Consumer gesucht: `_handle_period_review()`
(Woche/Monat-Rückblick) und `handle_music_timeline()`. Woche/Monat
brauchen jetzt einen echten DatumsBEREICH (`_format_date_range()`, neu,
reine Presentation-Methode) statt eines Einzeldatum-Labels - Timeline
behält ihre bestehende Semantik unverändert bei (Abschnitt 30: "Keine
Scope-Ausweitung", die `Xx`-Darstellung bleibt ebenfalls unverändert).
`_format_period_label()` bleibt bestehen (weiterhin einziger Timeline-
Consumer für "today"/"week"/"month") - der "year"-Zweig wurde entfernt,
da er nach der Jahresrückblick-Umstellung auf einen eigenen Renderer
keinen Aufrufer mehr hatte (Timeline hatte nie eine "year"-Periode).

### 11.5 Datumsbereiche (`period_start`/`period_end`)

Der Calculator liefert weiterhin ausschließlich rohe `datetime`-Objekte
(`period_start`/`period_end`, exklusiv) - keine UI-Datumsstrings. Der
neue `_format_date_range()`-Helper (Handler-Ebene) berechnet
`end_inclusive = period_end - timedelta(days=1)` und formatiert je nach
Fall "07.–13.09.2026" (Woche/Monat im selben Monat/Jahr),
"28.09.–04.10.2026" (Woche über einen Monatswechsel) oder
"28.12.2026–03.01.2027" (Woche über einen Jahreswechsel) - ein
Kalendermonat selbst liegt immer vollständig in einem Monat.
`generate_year_stats()` verwendet für `period_start`/`period_end`
identisch `_calendar_period_bounds("year")` - keine zweite
Zeitraum-Definition.

### 11.6 Jahresdiagramm

`_format_monthly_chart()` (neu) rendert die 12 `monthly_plays`-Rohwerte
als monospace-Balkendiagramm in festen Spaltenbreiten (Monatsname 10,
Balken 16, Plays 5 Zeichen, siehe Master-Prompt Abschnitt 22.1) - der
stärkste Monat = 16 gefüllte Zeichen, alle anderen proportional dazu
(mind. 1 Zeichen bei `plays > 0`), keine Division durch 0 bei
durchgehend 0 Plays. Nur der Monatszeilenblock steckt in `<code>...</code>`,
nicht die gesamte Nachricht - `handle_year_review()` sendet daher mit
`parse_mode=ParseMode.HTML` (einzige Ausnahme von der sonst
durchgängigen Plain-Text-Formatierung dieser Klasse).

### 11.7 `delta_pct`

`highlights.strongest_month.delta_pct` = gerundeter Prozentsatz über dem
Monatsdurchschnitt (`(stärkster - Durchschnitt) / Durchschnitt * 100`),
strukturell nie negativ (stärkster Monat ist per `max()` immer >=
Durchschnitt). `None` bei < 3 aktiven Monaten ODER `total_plays == 0`
(deckt sich automatisch, da `average_monthly_plays` dann 0 ist). Bei
exaktem Gleichstand mit dem Durchschnitt (z. B. alle 12 Monate gleich
viele Plays) `delta_pct == 0`. Tie-Break beim stärksten Monat: `max()`
über eine Jan→Dez geordnete Liste liefert bereits den chronologisch
ersten Treffer bei Gleichstand - kein zusätzlicher Code nötig.

### 11.8 `highlights` strukturell unabhängig

`highlights` enthält in v1 ausschließlich `strongest_month` (`name`/
`plays`/`delta_pct`) - explizit KEIN `top_artist`/`top_song`-Alias auf
`top_artists_split[0]`/`top_songs_detailed[0]` (per Test gepinnt,
`TestHandleYearReview` prüft die exakten Highlight-Keys). Das
Datenmodell selbst bleibt frei von Ranking-Duplikaten, nicht nur die
Anzeige.

### 11.9 Bewusste Layout-Entscheidung: Jahres-Songs/-Künstler einzeilig

Wochen-/Monatsrückblick zeigen Songs zweizeilig (Titel + eingerückt
Artist(s)/Plays, siehe Abschnitt 8 des Master-Prompts). Für den
Jahresrückblick zeigt Abschnitt 24 des Master-Prompts dagegen explizit
einzeilige Einträge ("🥇 Song A · 42 Plays", ohne Artist-Zeile) - bei
bereits umfangreichem Jahres-Text (KPIs + Highlight + 12-Zeilen-Diagramm)
hält das die Nachricht kompakt. Diese konkrete Beispieldarstellung wurde
gegenüber der allgemeineren Aussage "dieselbe visuelle Sprache" (Abschnitt
26) als maßgeblich behandelt - Rang-Symbole/Play-Formatter/Header-Stil
bleiben identisch, nur die Song-Zeilen-Tiefe unterscheidet sich bewusst.

### 11.10 Nicht Teil dieser Phase (Abschnitt 30)

Music Timeline (`Xx`-Darstellung, Kalenderlogik) unverändert. Keine
neuen Rollen-/Access-Level-Systeme. Keine Listening-Time-/Genre-/
Discovery-/Active-Day-Highlights. Keine globale HTML-Escape-Abstraktion
(`html.escape()` lokal im Annual-Renderer verwendet). Keine präventive
`_truncate()`-Anwendung im neuen Song-/Künstler-Layout.

### 11.11 Geänderte Dateien

`services/statistik/statistics_calculator.py` (`_split_artists()`,
`generate_year_stats()`, additive Felder, `_identity_key()`-Härtung,
`GERMAN_MONTHS` als kanonische Quelle), `services/statistik_service.py`
(`generate_year_stats()`-Durchreichung), `handlers/mugge_statistik_handler.py`
(neue Formatter, eigenständiger `handle_year_review()`, neues Woche/
Monat-Layout).

### 11.12 Tests

`tests/test_statistics_calculator.py` (+~30: `_split_artists()`,
additive Felder, `generate_year_stats()` inkl. Invariante
`sum(monthly_plays) == total_plays`, Tie-Break, `delta_pct`-Fälle,
Unique-Identity aus Volltext statt Top-10), `tests/test_mugge_statistik_handler.py`
(+~25: Play-/Rang-/Datumsbereich-Formatter, neues Wochen-/Monats-Layout,
eigenständiger Jahresrückblick inkl. HTML-Escaping/`<code>`-Block/
ParseMode). Thematische Regressionsgruppe (Menu/Stats/gesamter Family
Hub, 22 Dateien): **494 passed, 0 Regressionen.**

---

## 12. Music Timeline Consistency & UX (2026-09-13)

Direkte Folgephase auf Abschnitt 11 - letzte verbliebene Inkonsistenz im
Statistik-System behoben: Timeline zeigte für denselben Zeitraum einen
anderen "Top Artist"-Wert als der Period-Rückblick.

### 12.1 Bug-Fix: Artist-Split-Inkonsistenz

`generate_timeline_stats()` zählte `top_artist` bisher ohne
`_split_artists()` - ein Play mit `"Toobrokeforfiji • SIN Davis • makko"`
zählte als EIN Combo-Artist, während `generate_stats()`s
`top_artists_split` (Abschnitt 11) bereits gesplittet zählte. Fix:
`artist_counts` in `generate_timeline_stats()` iteriert jetzt über
`self._split_artists(...)` (derselbe Helper, kein zweiter Splitting-Code).
`top_album`/`most_replayed_track`/`new_track_count` bewusst NICHT
angefasst - `most_replayed_track` wird von
`services/family/family_challenge_service.py` wörtlich mit einer
Nutzer-Texteingabe verglichen (siehe Abschnitt 9.4), dieser Vertrag
bleibt unverändert (repoweit verifiziert, Family-Challenge-Tests laufen
unverändert grün).

**Garantiert per Test** (`TestTimelineConsistencyWithPeriodReview`):
`generate_timeline_stats(...)["periods"]["week"]["top_artist"]` ==
`generate_stats("week", ...)["top_artists_split"][0]` - identisch für
"week" und "month" (für "today" existiert keine vergleichbare
`generate_stats()`-Periode).

### 12.2 UX-Redesign

`handle_music_timeline()` spricht jetzt dieselbe visuelle Sprache wie
Wochen-/Monats-/Jahresstatistik: `_format_plays()` statt `(Nx)`/
`(N Plays)`, konsistente Emojis (🎤💿🔁🆕🎧), kein `_truncate()` mehr
(analog zur Begründung bei Woche/Monat: Telegram darf normal umbrechen),
20-Zeichen-Trennlinie, sauberer Empty-State ("Keine Wiedergaben heute")
statt einer Null-Sektion, keine `0m`-Zeile mehr (Dauer-Zeile nur bei
`listening_seconds > 0`).

**Periode-Label:** "Heute"/"Diesen Monat" verwenden weiterhin
unverändert `_format_period_label()` (einziger verbleibender Consumer).
"Diese Woche" zeigt neu einen echten Datumsbereich
(`_format_date_range()`, bereits aus Abschnitt 11 vorhanden) statt eines
Einzeldatums - dafür wurde `generate_timeline_stats()`s Rückgabe um ein
additives `period_end`-Feld je Periode ergänzt (`_calendar_period_bounds()`
lieferte dieses Ende bereits, es wurde vorher nur verworfen) - keine
Änderung an `_calendar_period_bounds()`/`generate_stats()` selbst.

### 12.3 Nicht angefasst

`generate_stats()`, `_handle_period_review()`, `handle_year_review()`,
`_calendar_period_bounds()`, `_identity_key()`, `most_replayed_track`,
`top_songs`/`top_artists`, `GERMAN_MONTHS`, Repository-Layout,
Datenmodell, `PlayHistoryPoller` - alle unverändert (per Regressionstests
gepinnt).

### 12.4 Tests

`tests/test_statistics_calculator.py` (+~15: `TestTimelineArtistSplit`,
`TestTimelineConsistencyWithPeriodReview` - der wichtigste Test dieser
Phase -, `period_end`-Feld), `tests/test_mugge_statistik_handler.py`
(Timeline-Testklasse komplett neu: Layout, Empty-State, Dauer-Zeile,
keine Truncation). Thematische Regressionsgruppe (Menu/Stats/gesamter
Family Hub, 22 Dateien): **516 passed, 0 Regressionen.**

---

## 13. ARCH-029 — Menu Navigation Continuity & Result Navigation (2026-09-13)

### 13.1 Problem

Nach einer Menü-Action (z. B. „Diese Woche") wurde zwar das fachliche
Ergebnis angezeigt, aber die Ergebnisnachricht enthielt kein
`reply_markup` — ein Navigations-Dead-End, obwohl der Benutzer aus einem
Menü heraus gestartet war. Betroffen: alle 7 Personal-Statistics-
Ergebnismethoden (`handle_week_review`/`handle_month_review`/
`handle_year_review`/`handle_top_songs`/`handle_top_artists`/
`handle_music_timeline`/`handle_library_overview`) sowie alle 12
Family-Hub-Ergebnismethoden (F2 6, F3 3, F4 3) in
`handlers/mugge_statistik_handler.py`/`handlers/family_stats_handler.py`/
`handlers/family_chat_handler.py`/`handlers/family_challenge_handler.py`.

**Root Cause:** `RichMenuSystem.handle_callback()` ruft für `menu:`-Items
mit gebundenem `handler` diesen direkt auf (`await menu_item.handler(...)`)
— **nie** `show_menu()`/`session.navigate_to()`. `session.current_menu`
bleibt dadurch nach einer Action exakt beim MenuItem stehen, von dem die
Action gestartet wurde. Der Domain-Handler sendet sein Ergebnis über
`msg.edit_text(...)` ohne `reply_markup` — es gab keine Stelle, die
automatisch eine Navigation an das Ergebnis anhängt.

### 13.2 Architekturentscheidung: Result-Navigation aus dem MenuItem-Baum

Keine neue Navigationsarchitektur, keine zweite Back-Mechanik neben
`menu:back`. Stattdessen: `handlers/menu/rendering.py::
render_result_navigation(menu_item)` — eine reine Funktion, die aus der
bereits vorhandenen statischen Parent-Kette eines MenuItem (`.parent`,
`.parent.parent`, `.title`, `.emoji` — dieselbe Struktur, die
`get_breadcrumb()` nutzt) ein `InlineKeyboardMarkup` baut:

```text
Level 1 (Parent):      [⬅️ <Parent-Titel>]
Level 2 (Grandparent):  [<Grandparent-Emoji> <Grandparent-Titel>] [🏠 Hauptmenü]
```

Grandparent wird nur gezeigt, wenn er nicht bereits „main" ist (kein
redundanter Button). Ist der Parent bereits „main", erscheint nur ein
einzelner „🏠 Hauptmenü"-Button.

**Warum NICHT `menu:back` wiederverwendet wird:** da Actions
`session.current_menu` nie verändern, würde ein `menu:back`-Klick auf dem
Ergebnis (history-Pop relativ zum unveränderten `current_menu`) eine
Ebene zu weit zurückspringen (z. B. von „Diese Woche" direkt zu
„Statistiken" statt zu „Rückblicke"). Der literale `menu:<parent.id>`-
Callback (bestehendes, unverändertes Format) referenziert stattdessen
exakt den unmittelbaren Parent — kein neuer Callback-Präfix.

**Selbstreferenz-Guard:** `MenuSession.navigate_to()` überspringt jetzt
den History-Eintrag, wenn das Ziel-MenuItem bereits `current_menu` ist
(Identitätsvergleich) — verhindert einen wirkungslosen ersten „Zurück"-
Klick, nachdem der Nutzer vom Action-Ergebnis zum Parent-Menü navigiert
ist.

### 13.3 Verantwortlichkeit / Verdrahtung

`RichMenuSystem.get_result_navigation(menu_id)` (public) schlägt die ID
in der eigenen Registry nach und liefert `render_result_navigation(item)`
(`None` bei unbekannter ID, defensiv). Aufgerufen von:

- `RichMenuHandler`s 6 Statistik-Wrapper-Methoden (`_handle_*_stats_wrapper`)
  über `self.menu_system.get_result_navigation(...)`.
- `RichMenuSystem`s eigene Family-Delegatoren (`_handle_family_*`) über
  `self.get_result_navigation(...)`.

Das berechnete `InlineKeyboardMarkup` wird als `nav_markup` explizit an
die jeweilige `handlers/menu/actions/{stats,family}.py`-Wrapper-Funktion
übergeben, die es 1:1 als `reply_markup` an die Domain-Handler-Methode
durchreicht — **weder `actions/*.py` noch die Domain-Handler
(`StatistikHandler`/`FamilyStatsHandler`/`FamilyChatHandler`/
`FamilyChallengeHandler`) kennen MenuItem, die Registry oder
Callback-Strings.** `reply_markup` ist überall additiv/optional
(Default `None`) und wird an **jedem** terminalen `edit_text()`/
`reply_text()`-Aufruf angehängt (Erfolg, leere Periode, Fehlerfall) —
kein Zustand bleibt ein Dead End.

```text
Menu Action (RichMenuHandler/RichMenuSystem)
    ↓  get_result_navigation(eigene MenuItem-ID)
Navigation (InlineKeyboardMarkup, aus dem MenuItem-Baum)
    ↓  nav_markup= (explizit übergeben)
Actions-Schicht (handlers/menu/actions/*.py)
    ↓  reply_markup= (1:1 durchgereicht)
Domain-Handler (StatistikHandler/Family*Handler)
    ↓  an JEDEM terminalen edit_text()/reply_text()
Telegram-Ergebnisnachricht (mit Navigation)
```

### 13.4 Was Domain-Handler/Actions NICHT selbst tun

- Keine eigenen Callback-Strings bauen oder kennen.
- Kein Wissen über Parent-/Grandparent-Menüs.
- Keine eigene `InlineKeyboardMarkup`-Konstruktion für Navigation (nur
  für rein fachliche Inline-Buttons, sofern vorhanden — hier nicht der
  Fall).
- Kein Zugriff auf `MenuItem`/die Menü-Registry/`MenuSession`.

### 13.5 Scope dieser Phase

Umgesetzt: alle 7 Personal-Statistics- und alle 12 Family-Hub-
Ergebnismethoden. **Nicht Teil dieser Phase** (bereits vorhandene eigene
Navigation, stichprobenartig verifiziert, siehe ARCH-029-Analyse):
Duplikate, Admin/Diagnose (Logger/Status/ErrorAdmin), Backup,
Library/Doctor/Repair/Health-Review, Navidrome, Test-System,
Download-Control-Center. `handle_last_played()` hat keinen Menüpunkt
(kein Kontext ableitbar) und bleibt unverändert. Keine Änderung an
Callback-IDs, Menüstruktur, `StatisticsCalculator`, `FamilyStatsService`,
F3/F4-Fachlogik, `generate_family_timeline()`.

---

## 14. Music Timeline — Final Closure (2026-09-13)

Direkte Folgephase auf Abschnitt 12 - Music Timeline endgültig auf eine
kompakte, ausschließlich tagesbezogene Daily-Music-Übersicht reduziert.
"Diese Woche"/"Diesen Monat" entfallen ersatzlos aus der Timeline
(Week-/Month-Statistiken bleiben über `generate_stats()`/
`generate_year_stats()` unverändert erreichbar - das sind separate
Konzepte, siehe Abschnitt 9/11).

### 14.1 Contract-Änderung

`StatisticsCalculator.generate_timeline_stats()` liefert seither:

```python
{
    "navidrome_username": str,
    "today": {
        "period_start": datetime, "period_end": datetime,
        "track_count": int, "listening_seconds": int,
        "top_artist": tuple[str, int] | None,
        "top_album": tuple[str, int] | None,
        "top_genre": tuple[str, int] | None,
        "most_replayed_track": tuple[str, int] | None,
        "new_track_count": int,
    },
}
```

Kein `"periods"`-Wrapper mehr, kein `"week"`/`"month"` mehr im Timeline-
Return. `most_replayed_track` bleibt bewusst `(title, plays)` (kein
reiner String-Contract) - `services/family/family_challenge_service.py`s
`own_top_song_today`-Auswertung liest weiterhin `most_replayed_track[0]`,
nur über den neuen Pfad `timeline["today"]["most_replayed_track"]` statt
vormals `timeline["periods"]["today"]["most_replayed_track"]` (einzige
Änderung an dieser Datei - `_compute_family_wide_answer()`/
`generate_family_timeline()` sind eine unabhängige, unverändert eigene
Timeline-Implementierung in `FamilyStatsService` und nicht betroffen).

Neu: `top_genre` (Plays je Genre) - dieselbe Datenquelle/Dedup-Regel wie
`generate_genre_stats()` (strukturiertes `"genres"`-Listenfeld, ein
Genre zählt pro Play höchstens einmal), hier inline auf "today" begrenzt
statt All-Time. Kein eigener `_split_genres()`-Helper (existiert nicht
im Statistics-Code) - dieselbe bereits vorhandene Zähllogik wird direkt
wiederverwendet.

### 14.2 UI-Redesign

`handle_music_timeline()` zeigt jetzt ausschließlich:

```text
📅 Heute · 13.09.2026

🎧 24 Plays
🔥 Clueso · 6 Plays
💿 Stadtrandlichter · 6 Plays
🎸 Hip-Hop · 8 Plays
❤️ Mit dir alleine sein
✨ 18 neue Tracks entdeckt

👤 dkmd
```

Jede Datenzeile außer „neue Tracks" ist optional (fehlt bei fehlendem
Wert ersatzlos, keine Platzhalter wie „N/A"/„Unknown"). Meistgehörter
Track zeigt bewusst KEINE Plays-Zahl (persönlicher Highlight-Eintrag,
kein Ranking). Keine Separator-Linie mehr, keine Hörzeit-Zeile mehr
(`listening_seconds` bleibt intern erhalten, wird aber nicht mehr
gerendert). Empty State bei 0 Wiedergaben heute:

```text
📅 Heute · 13.09.2026

Keine Wiedergaben heute

👤 dkmd
```

Ersetzt `_render_timeline_period()`/`_format_timeline_period_label()`/
`_TIMELINE_SEPARATOR`/`_TIMELINE_EMPTY_LABELS` durch eine einzelne
`_render_timeline_today()` - `_format_period_label()`/`_format_plays()`
(Header-Datum bzw. Play-Pluralisierung) bleiben unverändert
wiederverwendet.

### 14.3 Nicht angefasst

`generate_stats()`, `generate_genre_stats()`, `generate_year_stats()`,
`_handle_period_review()`, `handle_year_review()`,
`_calendar_period_bounds()`, `_identity_key()`, `_split_artists()`,
`FamilyStatsService.generate_family_timeline()`,
`_compute_family_wide_answer()` (Family-weite Challenge-Antworten),
Repository-Layout, Datenmodell, `PlayHistoryPoller` - alle unverändert
(per Regressionstests gepinnt).

### 14.4 Tests

`tests/test_statistics_calculator.py` (`TestGenerateTimelineStats` auf
Today-only-Contract umgebaut + `top_genre`-Fälle neu,
`TestTimelineArtistSplit` auf `timeline["today"]` umgestellt,
`TestTimelineConsistencyWithPeriodReview` auf den verbleibenden
today-Fall reduziert - der bisherige Week-/Month-Cross-Check gegen
`generate_stats()` entfällt, da die Timeline diese Perioden nicht mehr
berechnet), `tests/test_mugge_statistik_handler.py`
(`TestHandleMusicTimelineLayout` komplett neu: exakte Zielausgabe,
optionale Zeilen, Empty State, keine Separator-/Hörzeit-Zeile). Gezielte
+ thematische Regressionsgruppe (Statistics/Timeline/Family, 8 Dateien):
**320 passed, 0 Regressionen.**

---

## 15. Verwandte Dokumente

- [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — Details zu allen vier
  live gefundenen Bugs dieser Phase sowie zum inzwischen geschlossenen
  Download-Verlauf-Punkt (Abschnitt 3.6).
- [`archive/MusicBot_ENGINEERING_BASELINE_v8.md`](archive/MusicBot_ENGINEERING_BASELINE_v8.md)
  — Baseline-Stand vor dieser Phase (mittlerweile über
  [`archive/MusicBot_ENGINEERING_BASELINE_v9.md`](archive/MusicBot_ENGINEERING_BASELINE_v9.md)
  durch [`MusicBot_ENGINEERING_BASELINE_v10.md`](MusicBot_ENGINEERING_BASELINE_v10.md)
  (Freeze 2026-09-14) als aktuelle Baseline abgelöst).
- [`docs/METADATA_REPROCESSING.md`](METADATA_REPROCESSING.md) — vollständige
  Doku des Reprocessing-Tools selbst (Sicherheitsmodell, CLI, Abschnitt 2a
  zum Subprozess-Aufrufmodell).
- [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — die beiden zurückgestellten
  Challenge-Typen aus Abschnitt 6.12 (Family Hub, F4).
- [`docs/MusicBot_ENGINEERING_BASELINE_v10.md`](MusicBot_ENGINEERING_BASELINE_v10.md)
  (eingefrorene Baseline seit 2026-09-14) — Family Hub (F1–F5) in
  „Recent Major Changes" (Abschnitt 3).
- [`docs/MusicBot_ARCH-021_Menu_Architecture_Migration.md`](MusicBot_ARCH-021_Menu_Architecture_Migration.md),
  [`docs/MusicBot_ARCH-023_Menu_Router_Permission_Hardening.md`](MusicBot_ARCH-023_Menu_Router_Permission_Hardening.md),
  [`docs/MusicBot_ARCH-024_Menu_File_Decomposition.md`](MusicBot_ARCH-024_Menu_File_Decomposition.md),
  [`docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md`](MusicBot_ARCH-025_Command_Help_Content_Decomposition.md)
  — die vier Architekturmigrationsphasen der internen `handlers/menu/`-
  Modulstruktur (Models/Permissions/Session → Router-/Permission-Härtung
  → Actions/Definitions/Rendering-Dekomposition → Command/Help-Content-
  Dekomposition + Debt-Fixes), alle COMPLETE. Siehe Abschnitt 1a oben für
  die daraus resultierende aktuelle Modulstruktur.

---

**Dateiname:**

```text
docs/MusicBot_TELEGRAM_MENU_SYSTEM.md
```
