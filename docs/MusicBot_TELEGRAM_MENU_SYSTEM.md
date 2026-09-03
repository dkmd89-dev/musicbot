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

---

## 2. Bestehender Menübaum (Überblick)

Nur zur Orientierung — Detailverhalten der einzelnen Admin-/Statistik-/
Navidrome-Bereiche ist nicht Gegenstand dieses Dokuments, da sie nicht in
dieser Phase entstanden sind.

```text
Hauptmenü
├── 📥 Downloads                    → siehe Abschnitt 3 (diese Phase)
├── 📊 Statistiken
│   ├── Monatsrückblick / Jahresrückblick
│   └── Top Songs / Top Künstler
├── 🛠️ Administration
│   ├── System-Status
│   ├── Benutzerverwaltung
│   ├── System-Logs
│   ├── Duplikat-Verwaltung (Statistiken, Cache leeren)
│   ├── Error-Verwaltung (Statistiken, Gesundheitsbericht, Letzte Fehler, Reset)
│   ├── Logger-Verwaltung (Übersicht, Module, Level, Dateien, Statistiken,
│   │   Handler, Bereinigung)
│   ├── Backup-Verwaltung (Bot/Library sichern, Backup-Listen)
│   ├── Bot neu starten
│   └── Test-System (Unit/Integration/Performance)
└── 🎵 Navidrome Mediathek
    ├── Durchsuchen (Künstler/Alben/Genres/Playlists)
    ├── Suchen (Überall/Künstler/Alben/Songs)
    ├── Meine Playlists / Favoriten / Zuletzt gespielt
    └── Statistiken
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

## 5. Muster für künftige Menü-Erweiterungen

Bei jeder neuen Menüfunktion (neuer Button, neuer Callback-Präfix):

1. `MenuItem` in `RichMenuSystem.initialize_menu_structure()` ergänzen
   (bzw. bestehendes Item mit `handler=`/`is_action=True` versehen).
2. `_handle_*`-Methode(n) in `RichMenuSystem` implementieren — bei
   dynamischen/externen Inhalten (Titel, URLs, Nutzereingaben) **kein**
   `parse_mode="Markdown"` verwenden, sofern der Text nicht nachweislich
   vollständig statisch ist (siehe Bug D, Abschnitt 3.3).
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

## 6. Verwandte Dokumente

- [`docs/FINDINGS_INDEX.md`](FINDINGS_INDEX.md) — Details zu allen vier
  live gefundenen Bugs dieser Phase sowie zum inzwischen geschlossenen
  Download-Verlauf-Punkt (Abschnitt 3.6).
- [`MusicBot_ENGINEERING_BASELINE_v8.md`](MusicBot_ENGINEERING_BASELINE_v8.md)
  — Baseline-Stand vor dieser Phase.

---

**Dateiname:**

```text
docs/MusicBot_TELEGRAM_MENU_SYSTEM.md
```
