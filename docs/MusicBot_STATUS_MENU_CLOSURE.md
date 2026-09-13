# MusicBot — Status-Menu Closure

> **Art dieses Dokuments:** gezielte funktionale Closure des bestehenden
> Telegram-System-Status-Menüs (`handlers/enhanced_status_handler.py` +
> zugehöriges Routing). Kein Architektur-Redesign. Statisch geprüft —
> keine Tests ausgeführt (der Implementierungsprozess führt keine
> Testsuite aus, siehe Abschnitt „Tests" unten).
>
> **Update (Master-Phase „Complete Telegram System Status Menu"):** die
> ursprüngliche Phase unten (Abschnitte „Ausgangslage" bis „Änderungen")
> beließ 12 Buttons bewusst als dokumentierten Platzhalter ohne
> Feature-Bau. Die Master-Phase hat für jeden dieser 12 Callbacks
> systematisch nach bereits vorhandenen Datenquellen im Projekt gesucht
> und 11 davon mit echten, kleinen, auf bestehenden Daten basierenden
> Implementierungen versehen (kein „Redesign", sondern zusätzliche
> `show_*`-Methoden nach demselben etablierten Muster). Ein Callback
> (`status_performance_history`) wurde mangels realer Datenbasis
> vollständig aus dem UI entfernt, einer (`status_storage_cleanup`)
> bleibt bewusst `UNAVAILABLE_BY_DESIGN`. Die historischen Abschnitte
> unten bleiben als Protokoll der ersten Phase erhalten; **Abschnitt
> „Final Contract" und „Deferred Findings" sind auf den aktuellen,
> finalen Stand nach der Master-Phase aktualisiert.**

---

## Ausgangslage

Log-Auszug, der diese Phase ausgelöst hat:

```text
EnhancedStatusHandler: ❌ Fehler beim System-Status:
Can't parse entities: can't find end of the entity starting at byte offset 108

[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_services_detail
[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_services_check
[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_users
[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_performance_history
[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_performance_reset

EnhancedStatusHandler: ❌ Fehler beim Performance-Status:
Message is not modified

EnhancedStatusHandler: ❌ Fehler beim Storage-Status:
Can't parse entities: can't find end of the entity starting at byte offset 67

[RICHMENUSYSTEM] ⚠️ Unbekannter Status-Callback: status_trends
```

**Drei unterschiedliche, unabhängige Ursachen** (durch Code-Lesen und
Byte-genaue Rekonstruktion bestätigt, nicht nur vermutet):

1. **Zwei echte Telegram-Markdown-Parse-Fehler.** `parse_mode="Markdown"`
   (Telegrams *Legacy*-Markdown, nicht „MarkdownV2") kennt nur 4
   reservierte Sonderzeichen: `_ * `` [`. Zwei dynamische Werte enthalten
   je einen unpaarigen Unterstrich:
   - `show_system_status()`: `platform.machine()` liefert auf diesem
     System wörtlich `"x86_64"`. Byte-genaue Rekonstruktion des
     tatsächlich gesendeten Texts ergibt exakt **Byte-Offset 108** für
     den Unterstrich in `x86_64` — identisch zum gemeldeten Fehler.
   - `show_storage_status()`/`_build_storage_report()`: `Config.LIBRARY_DIR`
     ist `"/mnt/musik_bilder/library"`. Byte-genaue Rekonstruktion ergibt
     exakt **Byte-Offset 67** für den Unterstrich in `musik_bilder` —
     identisch zum gemeldeten Fehler.
2. **12 Buttons ohne Handler-Implementierung.** `status_services_detail`,
   `status_services_check`, `status_users`, `status_performance_history`,
   `status_performance_reset`, `status_trends` und 6 weitere (vollständige
   Liste unten) sind im Status-Menü als Buttons gerendert, aber für
   keinen existiert irgendwo im Repository eine Handler-Methode — sie
   fielen bisher identisch zu einem tatsächlich unerwarteten/unbekannten
   `callback_data`-Wert auf den generischen „⚠️ Unbekannter
   Status-Callback"-Zweig zurück (WARNING-Log, obwohl es sich um eine
   bekannte, bloß unfertige Funktion handelt, kein Bug).
3. **„Message is not modified" wurde wie ein echter Fehler behandelt.**
   Ein Klick auf „🔄 Aktualisieren" ohne zwischenzeitliche Änderung der
   angezeigten Werte lässt `edit_message_text()` `telegram.error.BadRequest("Message is not modified")`
   werfen — Telegrams dokumentiertes Idempotenz-Verhalten, kein Fehler.
   Der bisherige generische `except Exception`-Zweig in jeder
   `show_*_status()`-Methode loggte das als „❌ Fehler beim
   Performance-Status: Message is not modified" und rief in 5 von 6
   Fällen zusätzlich `_show_error_message()` auf, wodurch dem Nutzer bei
   einem harmlosen Refresh ein „❌ Fehler"-Bildschirm angezeigt worden
   wäre.

---

## Characterization

### Vollständige Callback-Matrix

Alle 19 tatsächlich in `handlers/enhanced_status_handler.py` gerenderten
`status_*`-`callback_data`-Werte (repoweit per `grep`/`re.findall`
verifiziert, keine Annahmen aus früheren Audits übernommen):

| Callback | Button | Handler-Methode | Zentral geroutet | Kategorie | Aktion in dieser Phase |
|---|---|---|---|---|---|
| `status_menu` | ✅ (Haupteinstieg + Zurück/Retry auf jeder Unteransicht) | ✅ `show_status_menu` | ✅ | **A** | Markdown unverändert sicher, „Message is not modified" jetzt No-op |
| `status_system` | ✅ | ✅ `show_system_status` | ✅ | **A** | **Markdown-Fix** (Byte-Offset-108-Bug), „Message is not modified" jetzt No-op |
| `status_bot` | ✅ | ✅ `show_bot_status` | ✅ | **A** | Markdown-Fix (`Config.VERSION`), „Message is not modified" jetzt No-op |
| `status_services` | ✅ | ✅ `show_services_status` | ✅ | **A** | Markdown-Fix (Service-Namen/-Status), „Message is not modified" jetzt No-op |
| `status_performance` | ✅ | ✅ `show_performance_status` | ✅ | **A** | Markdown-Fix (`op_type`), **„Message is not modified"-Fix** (der gemeldete Fall) |
| `status_storage` | ✅ | ✅ `show_storage_status` | ✅ | **A** | **Markdown-Fix** (Byte-Offset-67-Bug, der gemeldete Fall), „Message is not modified" jetzt No-op |
| `status_refresh` | ✅ (nur Hauptmenü) | ✅ (Alias auf `show_status_menu`) | ✅ | **A** | unverändert |
| `status_users` | ✅ (Hauptmenü + Bot-Ansicht) | ❌ keine existiert | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_trends` | ✅ (Hauptmenü) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_system_detail` | ✅ (System-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_system_history` | ✅ (System-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_bot_handlers` | ✅ (Bot-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_bot_logs` | ✅ (Bot-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_services_check` | ✅ (Services-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_services_detail` | ✅ (Services-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_performance_history` | ✅ (Performance-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_performance_reset` | ✅ (Performance-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |
| `status_storage_cleanup` | ✅ (Storage-Ansicht) | ❌ | war identisch zu „unbekannt" (bereits als `TEST-011` bekannt) | **C** | jetzt bekannter Platzhalter |
| `status_storage_detail` | ✅ (Storage-Ansicht) | ❌ | war identisch zu „unbekannt" | **C** | jetzt bekannter Platzhalter |

**Ergebnis: 7× Kategorie A (vollständig funktional), 12× Kategorie C
(Button ohne Handler), 0× Kategorie B, 0× Kategorie D, 0× Kategorie E.**

**Wichtige Korrektur gegenüber dem bisherigen Audit-Stand:** Der
Master-Prompt und die bisherige Testdatei (`tests/test_enhanced_status_handler.py`,
Stand vor dieser Phase) beschrieben die 12 Buttons z. T. als „nicht
verdrahtet" — eine repoweite Suche (nicht nur in
`enhanced_status_handler.py`, sondern im gesamten Repository) bestätigt:
für **keinen** der 12 existiert unter irgendeinem Methodennamen eine
tatsächliche Implementierung. Es handelt sich durchgehend um Kategorie
**C** (Button ohne Handler), nicht um Kategorie **B** (Handler
existiert, nur nicht geroutet). Deshalb wurden — wie vom Master-Prompt
explizit gefordert — **keine** neuen Handler-Methoden für diese 12
Callbacks implementiert.

### Routing-Architektur (unverändert)

```text
Telegram callback (status_*)
        ↓
RichMenuSystem.handle_callback() — Präfix-Routing (_ADMIN_ONLY_PREFIXES
        ↓                          inkl. "status_", dann startswith("status_"))
RichMenuSystem._handle_status_callback() — 3-zeiliger Delegator
        ↓
handlers/menu/actions/admin_diagnostics.py::handle_status_callback()
        ↓                          — EINZIGE routing_map, EINZIGER
        ↓                            Platzhalter-Mechanismus
EnhancedStatusHandler.show_*_status()
        ↓
query.edit_message_text(..., parse_mode="Markdown")
```

Kein paralleler/konkurrierender Router gefunden oder eingeführt. Die
zentrale `RichMenuSystem`-Sicherheits-/Routing-Architektur
(`_ADMIN_ONLY_PREFIXES` inkl. `"status_"`, Admin-Check vor jedem
`status_*`-Callback) ist unverändert.

---

## Änderungen

### `handlers/enhanced_status_handler.py`

- **Neu:** `_escape_markdown(value) -> str` (Modulfunktion) — escaped
  Telegrams 4 Legacy-Markdown-Sonderzeichen (`_ * `` [`) in einem
  dynamischen Wert. Bewusst **nicht** `helfer/markdown_helfer.py::escape_md_v2()`
  wiederverwendet — das ist für `parse_mode="MarkdownV2"` und escaped
  dort zusätzlich u. a. `.` und `-`, was unter dem hier verwendeten
  Legacy-„Markdown"-Modus sichtbare, falsche Backslashes in Versions-/
  Pfadangaben erzeugt hätte (z. B. `7\.0\.0` statt `7.0.0`).
- **Neu:** `_is_message_not_modified_error(exc) -> bool` (Modulfunktion)
  — erkennt ausschließlich `TelegramError`-Instanzen mit „message is not
  modified" in der Fehlermeldung.
- `show_system_status()`: `platform.system()`/`release()`/`python_version()`/`machine()`
  werden vor der Einbettung escaped (behebt den gemeldeten
  Byte-Offset-108-Fehler). `except`-Block: „Message is not modified"
  wird jetzt als No-op behandelt (`return`, kein Log, keine
  Fehleranzeige).
- `show_bot_status()`: `self.config.VERSION` wird escaped.
  Idempotenz-Fix wie oben.
- `show_services_status()`: `service_name.capitalize()` und `status`
  werden escaped (aktuell aus einer festen, sicheren Wertemenge, aber
  strukturell dynamisch — defensiv abgesichert). Idempotenz-Fix.
- `show_performance_status()`: `op_type` (aus `operation_breakdown`,
  aktuell ohne produktiven Aufrufer, siehe „Deferred Findings") wird
  escaped. Idempotenz-Fix (**behebt den konkret gemeldeten
  „Message is not modified"-Fehler**).
- `show_storage_status()`/`_build_storage_report()`: `path` (der reale
  Server-Dateisystempfad) wird escaped (behebt den gemeldeten
  Byte-Offset-67-Fehler). `name` (fixer Schlüssel „Library"/„Downloads"/
  „Cache"/„Logs") bleibt unescaped (kein dynamischer Wert). Idempotenz-Fix.
- `_show_error_message()`: der übergebene `error_message`-Text (enthält
  `str(exception)`, potenziell beliebigen Inhalt) wird escaped, damit
  eine zufällige Exception-Nachricht nicht ihrerseits die
  Fehleranzeige selbst bricht.
- Modul-Docstring am Dateiende („🎨 MENU-STRUKTUR"): korrigiert —
  markiert jetzt explizit, welche Unterpunkte Platzhalter ohne
  Handler sind (vorher irreführend als vollständig implementiert
  dargestellt, u. a. „✅ Vollständige Menu-Integration" entfernt).

### `handlers/menu/actions/admin_diagnostics.py`

- **Neu:** Modulkonstante `_PLACEHOLDER_STATUS_CALLBACKS` (12 Einträge,
  siehe Callback-Matrix oben).
- `handle_status_callback()`: neuer `elif`-Zweig zwischen dem
  bestehenden `routing_map`-Dispatch und dem generischen
  „unbekannt"-Fallback — bekannte Platzhalter erhalten `logger.debug(...)`
  (statt `logger.warning(...)`) und die Nutzer-Rückmeldung „🚧 Diese
  Funktion ist noch nicht implementiert." Der generische Fallback
  (`logger.warning(...)` + „⚠️ Funktion nicht implementiert") bleibt für
  tatsächlich unerwartete `callback_data`-Werte unverändert bestehen —
  **keine globale Unterdrückung**, nur eine gezielte Unterscheidung.
- `routing_map` selbst **unverändert** — keine der 12 Platzhalter-Callbacks
  wurde dorthin verschoben (keine erfundene Implementierung).

### `tests/test_enhanced_status_handler.py`

- Docstring/Charakterisierung korrigiert (19 statt „18" gerenderte
  Callbacks, Kategorie-C- statt Kategorie-B-Klarstellung).
- `TestUnroutedStatusButtonsAreDocumented` → `PLACEHOLDER_STATUS_CALLBACKS`-Set
  ergänzt, Assertion verschärft auf exakte Mengengleichheit
  (`unrouted == PLACEHOLDER_STATUS_CALLBACKS`) statt nur `issubset`.
- Neu: `TestEscapeMarkdown` (11 Tests, inkl. aller Master-Prompt-Beispiele:
  `/mnt/test/path_with_underscores/`, `Linux_6.x`, `value_with_underscores`,
  `foo-bar`, `foo[bar]`, `foo(bar)`).
- Neu: `TestIsMessageNotModifiedError` (4 Tests).
- Neu: `TestShowSystemStatusMarkdownSafety`, `TestShowStorageStatusMarkdownSafety`
  (5 Tests) — Regressionstests exakt gegen die beiden real gemeldeten
  Byte-Offset-Bugs plus eine kombinierte Sonderzeichen-Probe.
- Neu: `TestMessageNotModifiedHandling` (7 Tests) — Idempotenzfall pro
  View sowie explizite Regressionstests, dass ANDERE
  Telegram-/generische Exceptions weiterhin sichtbar behandelt werden
  (keine globale Unterdrückung).

### `tests/test_menu_actions_admin_diagnostics.py`

- Neu: `test_status_callback_unknown_logs_warning` — Gegenprobe zu den
  Platzhalter-Tests (echte unbekannte Werte loggen weiterhin WARNING).
- Neu: `test_status_callback_routes_to_expected_handler_method`
  (parametrisiert, 7 Fälle) — Routing-Contract-Test für jeden aktiven
  Button.
- Neu: `test_status_callback_known_placeholder_shows_friendly_message_without_warning`
  (parametrisiert, 12 Fälle) — verifiziert für jeden Platzhalter: kein
  WARNING-Log, freundliche Meldung, keine der echten Handler-Methoden
  wird aufgerufen (keine erfundene Route).

### `tests/test_rich_menu_system.py`

- Modul-Docstring-Befund und Testklasse `TestStatusStorageCleanupIsUnrouted`
  → `TestStatusStorageCleanupIsKnownPlaceholder` umbenannt/korrigiert
  (Verhalten/Assertions unverändert gültig — die Nachricht enthält
  weiterhin „nicht implementiert", `show_storage_status` wird weiterhin
  nicht aufgerufen).

---

## Master-Phase — „Complete Telegram System Status Menu"

Aufbauend auf der obigen ersten Phase. Ziel: jeder der (ursprünglich 19,
nach Entfernung von `status_performance_history` 18) `status_*`-Callbacks
muss einem eindeutigen Endzustand entsprechen — `IMPLEMENTED`,
`REMOVED` oder `UNAVAILABLE_BY_DESIGN`. Kein Callback darf „unbekannt/
orphaned/unerreichbar" bleiben.

### Fall-Entscheidung je zuvor unimplementiertem Callback

Für jeden der 12 vorherigen Platzhalter wurde zunächst repoweit nach
einer bereits vorhandenen Datenquelle gesucht (Master-Prompt Phase 2),
bevor irgendetwas Neues geschrieben wurde:

| Callback | Gefundene Datenquelle | Fall | Entscheidung |
|---|---|---|---|
| `status_users` | `BotStatusTracker.get_user_activity()` — real befüllt seit `handlers/menu/activity_tracking.py::record_activity()` | A | **IMPLEMENTED** — nur aggregierte Zählwerte, keine User-IDs |
| `status_trends` | `SystemMonitor.cpu_history`/`memory_history`/`disk_history` (bereits gesammelt, bisher nicht ausgewertet) | B | **IMPLEMENTED** — neue `get_history_summary()` (Min/Ø/Max/aktuell) |
| `status_system_detail` | `psutil` (bereits importiert): `getloadavg()`/`swap_memory()`/`cpu_percent(percpu=True)`/`boot_time()` | B | **IMPLEMENTED** — neue `get_extended_system_info()` |
| `status_system_history` | dieselben History-Deques wie Trends, hier als Rohwert-Sequenz statt Aggregat | B | **IMPLEMENTED** — bewusst andere Darstellung als Trends (keine Duplizierung) |
| `status_bot_handlers` | `BotStatusTracker.get_handler_overview()` — real befüllt seit `RichMenuHandler._record_initial_handler_statuses()` (17 benannte Handler) | A | **IMPLEMENTED** |
| `status_bot_logs` | `logger.py::get_logging_stats()` — reine Zähler pro Modul (debug/info/warning/error/critical), kein Loginhalt | A | **IMPLEMENTED** — zusätzlich Fix des „Gesamt-Logs: 0"-Bugs in `show_bot_status()` |
| `status_services_check` | `NavidromeAPI.check_connection()` — echter, read-only „ping"-Request | B | **IMPLEMENTED** — nur Navidrome, `download`/`statistics`/`logger` bleiben ehrlich „unknown" (kein Fake-„healthy") |
| `status_services_detail` | Transparenz, welche Services überhaupt einen automatisierten Check besitzen | B | **IMPLEMENTED** — kleine, nicht-redundante Zusatzinfo |
| `status_performance_history` | **keine** — `operation_counts`/`error_counts` sind reine seit-`last_reset`-Zähler ohne Snapshot-Persistenz über Neustarts hinweg | D | **REMOVED** — Button komplett aus dem UI entfernt (keine Fake-History) |
| `status_performance_reset` | `SystemMonitor.reset_statistics()` — bereits vorhanden, nie aufgerufen | A | **IMPLEMENTED** — Admin-gated via bestehenden `status_`-Präfix, kein neuer Confirm-Flow (siehe Begründung im Docstring von `show_performance_reset()`) |
| `status_storage_cleanup` | **keine** sichere, definierte Cleanup-Aktion — jede echte Implementierung wäre destruktiv auf realen Server-Pfaden | D | **UNAVAILABLE_BY_DESIGN** — bleibt einziger Platzhalter |
| `status_storage_detail` | `psutil.disk_partitions()`/`disk_usage()` — dieselbe Bibliothek wie `SystemMonitor` bereits nutzt | B | **IMPLEMENTED** |

Zusätzlich (Phase 8, minimal, kein Bot-weites Instrumentieren):
`handle_status_callback()` ruft für jeden tatsächlich gerouteten
Callback `system_monitor.record_operation(callback_data)` auf — gibt
der zuvor immer leeren „Top Operationen"-Liste in
`show_performance_status()` erstmals reale Nutzungsdaten, ohne
irgendeinen anderen Teil des Bots zu berühren.

### Neue Methoden in `EnhancedStatusHandler`

`show_users_status()`, `show_trends()`, `show_system_detail()`,
`show_system_history()`, `show_bot_handlers()`, `show_bot_logs()`,
`show_services_check()`, `show_services_detail()`,
`show_performance_reset()`, `show_storage_detail()` — alle nach exakt
demselben etablierten Muster wie die 6 bestehenden `show_*`-Methoden
(`query.answer()` → Daten sammeln → `_escape_markdown()` auf jeden
dynamischen Wert → `edit_message_text(..., parse_mode="Markdown")` →
`except Exception as e: if _is_message_not_modified_error(e): return`
→ `_show_error_message()`). Zwei neue Hilfsmethoden auf `SystemMonitor`
(`get_extended_system_info()`, `get_history_summary()`) und eine neue
Modulfunktion `_find_partition_for_path()` (reine psutil-Auswertung,
kein neuer Zustand).

### Sicherheitsrelevante Entscheidungen

- **`status_services_check`** führt ausschließlich einen lesenden
  „ping"-Request gegen Navidrome aus (`NavidromeAPI.check_connection()`,
  bereits vorhandene Methode) — keine Mutation, kein Neustart, kein
  Container-Eingriff.
- **`status_performance_reset`** setzt ausschließlich ephemere,
  In-Memory-Analytics-Zähler zurück (kein Datenverlust vergleichbar mit
  Library-/Backup-Löschungen — ein Bot-Neustart hätte denselben Effekt).
  Bleibt über den bestehenden `_ADMIN_ONLY_PREFIXES`-Gate
  (`"status_"`-Präfix in `RichMenuSystem.handle_callback()`) admin-gated.
  Kein neuer, separater Bestätigungsschritt eingeführt (bewusste
  Entscheidung angesichts der geringen Tragweite, siehe Docstring).
- **`status_storage_cleanup`** erhält weiterhin **keine** Implementierung
  — jede reale Umsetzung wäre eine destruktive Dateisystem-Operation
  ohne definierten, sicheren Contract.
- **`status_users`** zeigt ausschließlich aggregierte Zählwerte
  (`active_users`, `total_recorded_activities`) — keine Telegram-User-
  IDs, Chat-IDs oder Nachrichteninhalte.
- **`status_bot_logs`** zeigt ausschließlich Zähler (Anzahl Logs/Fehler
  pro Modul) — niemals den eigentlichen Log-Nachrichtentext, keine
  Secrets/Tokens/Credentials.

### Deferred Finding aus der ersten Phase — behoben

Der in der ersten Phase als Deferred Finding #2 dokumentierte
„Gesamt-Logs: 0"-Bug (`show_bot_status()`) ist in dieser Master-Phase
behoben: `total_logs` wird jetzt korrekt über
`sum(m.get("total_logs", 0) for m in logger_stats["modules"].values())`
aggregiert, statt einen nie existierenden Top-Level-Schlüssel zu lesen.

---

## Final Contract

**Aktive, vollständig implementierte Status-Callbacks (17):**
`status_menu`, `status_system`, `status_bot`, `status_services`,
`status_performance`, `status_storage`, `status_refresh`, `status_users`,
`status_trends`, `status_system_detail`, `status_system_history`,
`status_bot_handlers`, `status_bot_logs`, `status_services_check`,
`status_services_detail`, `status_performance_reset`,
`status_storage_detail` — jeweils über `handle_status_callback()`s
`routing_map` auf die entsprechende `EnhancedStatusHandler.show_*`-Methode
geroutet.

**Entfernt (1):** `status_performance_history` — Button vollständig aus
dem UI entfernt (keine reale Datenbasis für eine „Verlauf"-Ansicht ohne
Fake-Daten).

**Bewusst nicht verfügbar (1):** `status_storage_cleanup` — erkennbar
über `_PLACEHOLDER_STATUS_CALLBACKS`, zeigt „🚧 Diese Funktion ist noch
nicht implementiert.", kein WARNING-Log. UNAVAILABLE_BY_DESIGN
(destruktive Aktion ohne definierten Contract).

**Zentraler Routingweg:** unverändert `RichMenuSystem.handle_callback()`
→ `_handle_status_callback()` → `admin_diagnostics_actions.handle_status_callback()`.
Kein zweiter Router, keine neue Dispatcher-Schicht.

**Markdown/Telegram-Rendering-Strategie:** `parse_mode="Markdown"`
(Legacy) bleibt durchgängig erhalten — auch in allen 10 neuen Views.
Jeder dynamische Wert (inkl. neu: Handler-/Modulnamen, Mountpoints,
Dateisystemtypen), der in einen `parse_mode="Markdown"`-Text eingebettet
wird, läuft durch `_escape_markdown()`. Statische `**Token**` bleiben
unverändert funktionsfähig.

**Idempotenzverhalten:** `edit_message_text()`-Aufrufe, die mit
„Message is not modified" fehlschlagen, werden in allen 16
`show_*`-Methoden (die eigene Telegram-Antworten senden) als No-op
behandelt (kein Log, kein Crash, keine Fehleranzeige). Alle anderen
`TelegramError`- und generischen Exceptions durchlaufen weiterhin den
bestehenden Error-Log-/`_show_error_message()`- bzw.
`error_handler`-Pfad unverändert.

### Vollständige Callback-Matrix (finaler Zustand)

| Callback | Final Status | Handler | Router | UI |
|---|---|---|---|---|
| `status_menu` | IMPLEMENTED | `show_status_menu` | routing_map | Hauptmenü + Zurück/Retry überall |
| `status_refresh` | IMPLEMENTED | `show_status_menu` (Alias) | routing_map | Hauptmenü „🔄 Aktualisieren" |
| `status_system` | IMPLEMENTED | `show_system_status` | routing_map | Hauptmenü „💻 System" |
| `status_system_detail` | IMPLEMENTED | `show_system_detail` | routing_map | System-Ansicht „📊 Detailliert" |
| `status_system_history` | IMPLEMENTED | `show_system_history` | routing_map | System-Ansicht „📈 Verlauf" |
| `status_bot` | IMPLEMENTED | `show_bot_status` | routing_map | Hauptmenü „🤖 Bot" |
| `status_bot_handlers` | IMPLEMENTED | `show_bot_handlers` | routing_map | Bot-Ansicht „📦 Handler" |
| `status_bot_logs` | IMPLEMENTED | `show_bot_logs` | routing_map | Bot-Ansicht „📝 Logs" |
| `status_services` | IMPLEMENTED | `show_services_status` | routing_map | Hauptmenü „📦 Services" |
| `status_services_check` | IMPLEMENTED | `show_services_check` | routing_map | Services-Ansicht „🔄 Services prüfen" |
| `status_services_detail` | IMPLEMENTED | `show_services_detail` | routing_map | Services-Ansicht „📊 Details" |
| `status_users` | IMPLEMENTED | `show_users_status` | routing_map | Hauptmenü „👥 Users" |
| `status_performance` | IMPLEMENTED | `show_performance_status` | routing_map | Hauptmenü „📊 Performance" |
| `status_performance_history` | **REMOVED** | — | — | Button entfernt |
| `status_performance_reset` | IMPLEMENTED | `show_performance_reset` | routing_map | Performance-Ansicht „🔄 Reset" |
| `status_storage` | IMPLEMENTED | `show_storage_status` | routing_map | Hauptmenü „📁 Storage" |
| `status_storage_detail` | IMPLEMENTED | `show_storage_detail` | routing_map | Storage-Ansicht „📊 Details" |
| `status_storage_cleanup` | **UNAVAILABLE_BY_DESIGN** | — (Platzhalter-Pfad) | `_PLACEHOLDER_STATUS_CALLBACKS` | Storage-Ansicht „🗑️ Cleanup" (bleibt sichtbar) |
| `status_trends` | IMPLEMENTED | `show_trends` | routing_map | Hauptmenü „📈 Trends" |

**18 Callbacks gesamt (19 minus 1 entfernter) — 17 IMPLEMENTED, 0 REMOVED
im Sinne „noch als Button sichtbar", 1 UNAVAILABLE_BY_DESIGN. Keiner
verbleibt UNKNOWN/ORPHANED/UNREACHABLE.**

---

## Deferred Findings

Punkte, die bei der Analyse auffielen, aber außerhalb des Scopes dieser
Phase(n) liegen (nicht bearbeitet):

1. **`RichMenuHandler`/`definitions.py`: toter Handler-Binding.** Die
   `MenuItem(id="admin_status", callback_data="status_menu",
   handler=system._handle_status_menu)` in `definitions.py` ist real
   unerreichbar — `RichMenuSystem.handle_callback()` prüft
   `callback_data.startswith("status_")` **vor** dem generischen
   `menu:`-Präfix-Dispatch, der `handler=` überhaupt erst aufrufen
   würde. Kein Verhaltensfehler (das Ergebnis ist identisch), aber ein
   irreführendes, ungenutztes Handler-Binding. Architekturthema
   (Reihenfolge der Präfix-Checks in `handle_callback()`), nicht Teil
   dieser Status-Menu-spezifischen Phase.
2. ~~`show_bot_status()`: „Gesamt-Logs" zeigt immer 0.~~ **Behoben in der
   Master-Phase** (siehe oben).
3. ~~`SystemMonitor.record_operation()` hat 0 produktive Aufrufer.~~
   **Teilweise behoben:** die Master-Phase instrumentiert jetzt jeden
   gerouteten `status_*`-Callback minimal (siehe oben) — außerhalb des
   Status-Menüs hat `record_operation()` weiterhin keine Aufrufer
   (bewusst kein bot-weites Instrumentieren, Master-Prompt Phase 8).
4. **`BotStatusTracker.get_user_activity()["recent_activities"]` wird
   berechnet, aber nirgends gerendert.** `show_users_status()` (neu)
   verwendet ebenfalls nur die aggregierten Zählwerte, nicht die
   detaillierte `recent_activities`-Liste (bewusst — Phase 7 verbietet
   ausdrücklich, Einzel-Aktivitäten mit potenziellen User-Bezügen
   anzuzeigen). Die Liste bleibt eine reine, ungenutzte
   Zusatzberechnung — kein Bug, keine Sicherheitsauswirkung, nicht
   bereinigt (unrelated cleanup).
5. **`status_storage_cleanup` bleibt bewusst ohne echte Funktion**
   (UNAVAILABLE_BY_DESIGN, siehe oben) — eine echte Implementierung wäre
   eine eigenständige Produktentscheidung (was genau soll „Cleanup"
   automatisiert löschen dürfen?), kein Bugfix.
6. **`download`/`statistics`/`logger` in `BotStatusTracker.services`
   haben weiterhin keinen automatisierten Check.** Nur Navidrome besitzt
   eine existierende Konnektivitätsprüfung. Ein Health-Check-Konzept für
   In-Prozess-Subsysteme ohne externen „erreichbar/nicht erreichbar"-
   Zustand wäre eine eigene Produktentscheidung, keine mechanische
   Ergänzung — dieser Punkt bleibt daher weiterhin offen. **Final
   Correction (2026-09-13):** `status_services_check` betrachtet diese
   drei Services jetzt jedoch explizit bei jedem Lauf (statt sie
   stillschweigend unverändert zu lassen) und setzt für sie einen
   konkreten, nachvollziehbaren Grund (`"Kein automatisierter
   Health-Check verfügbar"`), der auch in der Services-Ansicht angezeigt
   wird — siehe Abschnitt „Final Correction" unten.

---

## Final Correction — Services-Check & System-Verlauf (2026-09-13)

Zwei konkrete, bei der manuellen/pytest-Validierung der Master-Phase
gefundene Fehler wurden gezielt korrigiert (keine erneute
Research-/Architektur-Phase, keine Änderung an der Routing-Architektur).

### Fix 1 — `status_services_check` berücksichtigt jetzt alle vier Services

**Vorher:** `show_services_check()` prüfte ausschließlich Navidrome;
Download/Statistics/Logger wurden nie verarbeitet.

**Jetzt:** Alle vier Services werden pro Aufruf explizit betrachtet:

| Service       | Verwendeter Check                                             | Ergebnis-Status                          |
|---------------|----------------------------------------------------------------|-------------------------------------------|
| `navidrome`   | `NavidromeAPI.check_connection()` — echter, read-only „ping"   | `healthy` / `error` (unverändert)          |
| `download`    | kein realer, deterministischer Health-Check in der bestehenden Architektur vorhanden | `unknown`, Grund: „Kein automatisierter Health-Check verfügbar" |
| `statistics`  | s. o.                                                           | `unknown`, Grund: „Kein automatisierter Health-Check verfügbar" |
| `logger`      | s. o.                                                           | `unknown`, Grund: „Kein automatisierter Health-Check verfügbar" |

**Wichtig — keine Fake Health Checks:** für `download`/`statistics`/
`logger` wurde kein Ersatz-Check (z. B. Verzeichnis-Schreibbarkeit,
Import-Erfolg, Konfigurationspräsenz) eingeführt, da keiner dieser
Proxys tatsächliche Funktionsfähigkeit belegt. Sie bleiben ehrlich
`unknown` — jetzt aber mit sichtbarem, nachvollziehbarem Grund statt
stillschweigend unverändert.

`BotStatusTracker.update_service_status()` besitzt dafür einen neuen,
optionalen `reason`-Parameter (rückwärtskompatibel, Default `None`);
`show_services_status()` zeigt eine Zeile `Grund: ...` nur, wenn
tatsächlich gesetzt.

**Fehlerisolation:** jeder der vier Services wird in einem eigenen
try/except verarbeitet. Schlägt ein einzelner Service-Check fehl
(Beispiel: Navidrome nicht erreichbar, oder ein unerwarteter Fehler beim
Setzen des Status für einen der anderen drei), werden die übrigen drei
Services trotzdem verarbeitet — der Button bricht nicht als Ganzes ab.

Die zentrale Routing-Kette (`RichMenuSystem.handle_callback()` →
`_handle_status_callback()` → `admin_diagnostics.handle_status_callback()`
→ `EnhancedStatusHandler.show_services_check()`) ist unverändert.

### Fix 2 — `show_system_history()` erzeugt keine neue Messung mehr

**Root Cause:** `show_system_history()` rief zuvor
`SystemMonitor.get_system_metrics()` auf, um an
`cpu_history`/`memory_history`/`disk_history` zu gelangen —
`get_system_metrics()` ist jedoch die SAMPLING-Funktion und hängt dabei
als Seiteneffekt selbst einen neuen Messwert an diese Deques an. Damit
war eine „leere" Historie beim Öffnen der Verlaufs-Ansicht nie wirklich
leer (es wurde vor der Leer-Prüfung bereits ein neuer Wert erzeugt) —
das hatte den Test
`TestShowSystemHistory::test_no_measurements_shows_placeholder_not_crash`
fehlschlagen lassen.

**Fix:** `show_system_history()` liest `self.system_monitor.cpu_history`/
`memory_history`/`disk_history` jetzt direkt (analog zu
`get_history_summary()`, das `show_trends()` bereits unverändert korrekt
so verwendet) — ohne `get_system_metrics()` aufzurufen. Die Methode ist
damit ein reiner, seiteneffektfreier Lesevorgang: SAMPLING (Erzeugen
neuer Messwerte) und HISTORY VIEW (Anzeigen bereits vorhandener
Messwerte) sind strikt getrennt.

Ist die Historie bei allen drei Metriken leer, zeigt die Ansicht jetzt
explizit:

```
📈 **System-Verlauf**

Noch keine Messungen seit Bot-Start.

_Nur In-Memory seit Bot-Start (max. 60 Messungen), kein Langzeit-Archiv._
```

Existiert bereits eine Historie, bleibt die bisherige Darstellung
(Rohwert-Sequenz je Metrik) unverändert — keine UI-Umgestaltung.

### Klarstellung für zukünftige Leser dieser Dokumentation

Diese Dokumentation behauptet **nicht**, dass alle vier Services
automatisch/„echt" geprüft werden — nur Navidrome besitzt einen
tatsächlichen automatisierten Check. Für `download`/`statistics`/
`logger` bedeutet „wird beim Service-Check berücksichtigt" ausdrücklich:
„wird explizit auf einen ehrlichen `unknown`-Status mit Grund gesetzt",
nicht „wird auf Funktionsfähigkeit geprüft".

---

## Tests

**Ausgeführt: NEIN.** Wie vorgegeben, wurden in allen Phasen (inkl.
Final Correction) keine Tests ausgeführt (`pytest`, `pytest -q`,
`python -m pytest`). Alle Tests wurden ausschließlich gelesen,
analysiert, ergänzt bzw. korrigiert. Der vollständige Testlauf obliegt
dem Nutzer.

Geänderte Testdateien (Master-Phase): `tests/test_enhanced_status_handler.py`
(neue Testklassen für `SystemMonitor.get_extended_system_info()`/
`get_history_summary()`, `_find_partition_for_path()`, sowie je eine
Testklasse pro neuer `show_*`-Methode — inkl. Markdown-Sicherheit für
Handler-/Modulnamen mit Unterstrichen und PII-Freiheit für
`status_users`), `tests/test_menu_actions_admin_diagnostics.py`
(Routing-Contract für alle 17 aktiven Callbacks, `record_operation()`-
Instrumentierung, geschrumpfte Platzhalter-Menge auf 1 Eintrag),
`tests/test_rich_menu_system.py` (Docstring-Präzisierung, keine
Verhaltensänderung).

### Final Correction — Testergänzungen

`tests/test_enhanced_status_handler.py`:

- `TestBotStatusTracker`: zwei neue Tests für den `reason`-Parameter von
  `update_service_status()` (wird gespeichert; wird bei Aufruf ohne
  `reason` vollständig zurückgesetzt statt einen alten Grund
  mitzuschleppen).
- `TestShowSystemHistory`: neuer Test
  `test_no_measurements_shows_explicit_empty_placeholder_text` (expliziter
  Platzhaltertext), `test_viewing_history_creates_no_new_measurement`
  (Kern-Regressionstest für den Fix — Historie bleibt bei 0 Einträgen
  nach dem Aufruf), `test_viewing_existing_history_does_not_change_entry_count`
  (Anzahl vorhandener Einträge bleibt beim Anzeigen unverändert). Der
  bereits bestehende, zuvor fehlschlagende Test
  `test_no_measurements_shows_placeholder_not_crash` wurde **nicht**
  verändert oder abgeschwächt — er ist durch die Implementierungskorrektur
  jetzt fachlich korrekt grün.
- `TestShowServicesCheck`: vier neue Tests —
  `test_non_navidrome_services_get_explicit_unknown_reason` (Grund wird
  gesetzt), `test_all_four_services_are_considered_during_check` (alle
  vier Services erhalten ein `last_check`), `test_error_in_one_service_does_not_block_the_others`
  (Fehlerisolation — ein simulierter Fehler bei „statistics" blockiert
  „download"/„navidrome"/„logger" nicht und der Button rendert trotzdem),
  `test_rendered_view_shows_reason_for_unknown_services` und
  `test_check_result_contains_no_pii_or_secrets` (Grund-Text erscheint in
  der gerenderten Ansicht, keine Secrets/PII-Marker enthalten). Die
  bereits bestehenden Tests dieser Klasse (Navidrome healthy/error/
  Exception, „andere Services bleiben ehrlich unknown") blieben
  unverändert gültig.
