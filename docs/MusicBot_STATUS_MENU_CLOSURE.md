# MusicBot — Status-Menu Closure

> **Art dieses Dokuments:** gezielte funktionale Closure des bestehenden
> Telegram-System-Status-Menüs (`handlers/enhanced_status_handler.py` +
> zugehöriges Routing). Kein Architektur-Redesign, keine neuen
> Status-Features. Statisch geprüft — keine Tests ausgeführt (der
> Implementierungsprozess führt keine Testsuite aus, siehe Abschnitt
> „Tests" unten).

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

## Final Contract

**Aktive Status-Callbacks (7):** `status_menu`, `status_system`,
`status_bot`, `status_services`, `status_performance`, `status_storage`,
`status_refresh` — jeweils über `handle_status_callback()`s `routing_map`
auf die entsprechende `EnhancedStatusHandler.show_*`-Methode geroutet.

**Bekannte Platzhalter (12):** `status_users`, `status_trends`,
`status_system_detail`, `status_system_history`, `status_bot_handlers`,
`status_bot_logs`, `status_services_check`, `status_services_detail`,
`status_performance_history`, `status_performance_reset`,
`status_storage_cleanup`, `status_storage_detail` — erkennbar über
`_PLACEHOLDER_STATUS_CALLBACKS`, zeigen „🚧 Diese Funktion ist noch nicht
implementiert.", kein WARNING-Log.

**Zentraler Routingweg:** unverändert `RichMenuSystem.handle_callback()`
→ `_handle_status_callback()` → `admin_diagnostics_actions.handle_status_callback()`.
Kein zweiter Router.

**Markdown/Telegram-Rendering-Strategie:** `parse_mode="Markdown"`
(Legacy) bleibt erhalten — keine Umstellung auf `MarkdownV2` oder
Wegfall der Formatierung (visuelle Darstellung bleibt identisch). Jeder
dynamische Wert, der in einen `parse_mode="Markdown"`-Text eingebettet
wird, läuft durch `_escape_markdown()`. Statische `**Token**` bleiben
unverändert funktionsfähig.

**Idempotenzverhalten:** `edit_message_text()`-Aufrufe, die mit
„Message is not modified" fehlschlagen, werden in allen 6
`show_*`-Methoden als No-op behandelt (kein Log, kein Crash, keine
Fehleranzeige). Alle anderen `TelegramError`- und generischen
Exceptions durchlaufen weiterhin den bestehenden
Error-Log-/`_show_error_message()`- bzw. `error_handler`-Pfad
unverändert.

---

## Deferred Findings

Ausschließlich Punkte, die bei der Analyse auffielen, aber außerhalb des
Scopes dieser Phase liegen (nicht bearbeitet):

1. **`RichMenuHandler`/`definitions.py`: toter Handler-Binding.** Die
   `MenuItem(id="admin_status", callback_data="status_menu",
   handler=system._handle_status_menu)` in `definitions.py` ist real
   unerreichbar — `RichMenuSystem.handle_callback()` prüft
   `callback_data.startswith("status_")` **vor** dem generischen
   `menu:`-Präfix-Dispatch, der `handler=` überhaupt erst aufrufen
   würde. `_handle_status_menu()`/`admin_diagnostics_actions.handle_status_menu()`
   sind dadurch zwar korrekt (delegieren ebenfalls an
   `show_status_menu()`), werden aber nie über diesen Pfad erreicht.
   Kein Verhaltensfehler (das Ergebnis ist identisch), aber ein
   irreführendes, ungenutztes Handler-Binding. Architekturthema
   (Reihenfolge der Präfix-Checks in `handle_callback()`), nicht Teil
   dieser Status-Menu-spezifischen Phase.
2. **`show_bot_status()`: „Gesamt-Logs" zeigt immer 0.**
   `logger_stats.get('total_logs', 0)` liest einen Schlüssel, den
   `get_logging_stats()` (ohne `module`-Argument) nie zurückgibt (nur
   `total_modules`/`modules`) — der Wert ist strukturell immer der
   Default `0`. Kein Markdown-/Routing-Bug, sondern ein eigenständiger,
   vorbestehender Anzeigefehler. Fix würde verstehen erfordern, was
   „Gesamt-Logs" tatsächlich aggregieren soll (Bot.py/Logger-Architektur)
   — außerhalb des Scopes dieser Phase.
3. **`SystemMonitor.record_operation()` hat 0 produktive Aufrufer.**
   Die „Top Operationen"-Liste in `show_performance_status()` ist in
   Produktion daher aktuell immer leer. Nicht behoben (kein
   Routing-/Markdown-Bug, sondern unvollständige Instrumentierung) —
   die neue `_escape_markdown(op_type)`-Absicherung bleibt dennoch
   bestehen, da die Datenstruktur grundsätzlich dynamisch ist.
4. **`BotStatusTracker.get_user_activity()["recent_activities"]` wird
   berechnet, aber nirgends gerendert.** `show_bot_status()` verwendet
   nur `active_users`/`total_recorded_activities` (Zählwerte). Reine
   überschüssige Berechnung, kein Bug, keine Sicherheitsauswirkung —
   nicht bereinigt (unrelated cleanup, nicht Teil dieser Phase).
5. **`status_storage_cleanup` bleibt bewusst ohne echte Funktion.**
   Laut vorbestehender Charakterisierung (`tests/test_rich_menu_system.py`)
   wäre eine echte Implementierung eine **destruktive** Aktion auf realen
   Server-Pfaden (SEC-003-Kontext) — die Entscheidung, ob und wie eine
   solche Funktion überhaupt gebaut werden soll, ist eine eigenständige
   Produktentscheidung, kein Bugfix. Bewusst nicht in dieser Phase
   getroffen.

---

## Tests

**Ausgeführt: NEIN.** Wie vom Master-Prompt vorgegeben, wurden in dieser
Phase keine Tests ausgeführt (`pytest`, `pytest -q`, `python -m pytest`).
Alle Tests wurden ausschließlich gelesen, analysiert, ergänzt bzw.
korrigiert. Der vollständige Testlauf obliegt dem Nutzer.

Geänderte/neue Testdateien: `tests/test_enhanced_status_handler.py`,
`tests/test_menu_actions_admin_diagnostics.py`,
`tests/test_rich_menu_system.py`.
