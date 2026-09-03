# Handler-Methoden-Level-Sweep — 2026-09-03

**Typ:** Read-only Funktions-/Methoden-Level-Sweep der 17 bereits im
`docs/audits/MAIN_CODEBASE_HEALTH_CHECK_2026-09-03.md` als "sauber"
eingestuften Handler-/Adapter-Module (`handlers/` + `services/clients/`) —
dort explizit als eigene, teurere nächste Stufe zurückgestellt.
**Status:** Analyse für 213 von 365 Funktionen/Methoden abgeschlossen. Die
22 bestätigt DEAD-Kandidaten (+ 2 transitiv entdeckte) sind inzwischen
entfernt (Cleanup-PR, 2026-09-03, siehe „Cleanup durchgeführt" unten) und
die Funktionslücke `update_handler_status`/`record_user_activity` ist
separat behoben (siehe `docs/FINDINGS_INDEX.md`, Zeile „BotStatusTracker").
Die 182 `SELF_ONLY?`-Kandidaten sind weiterhin **nicht** einzeln geprüft —
für eine Wiederaufnahme siehe „Offen für die Fortsetzung" unten.

## Methodik

Pro Funktion/Methode: statische Referenzen (repoweit, wortgrenzenbasiert)
→ `callback_data`/`getattr`-Dynamik geprüft (kein `getattr(self, dynamischer_name)`-
Muster in diesen 17 Dateien gefunden — Dispatch läuft ausschließlich über
explizite if/elif-Ketten mit String-Vergleich bzw. `dict`-Routing-Tabellen)
→ Tests → git history (Ersatz-Commit-Evidenz) → Klassifikation.

Werkzeug: AST-basiertes Inventar-Skript, `git`-History-Abgleich manuell pro
Kandidat. Wichtiger Kalibrierungs-Fehler im ersten Lauf (Pfad-Präfix-
Mismatch, `./` von `grep .`) gefunden und korrigiert, bevor die
Klassifikation vertraut wurde (0-von-365-Ergebnis war unplausibel sauber).

## Ergebnis: 213 von 365 nicht eindeutig ACTIVE

- **152 ACTIVE** (nicht weiter geprüft)
- **182 SELF_ONLY?** — nur innerhalb der eigenen Datei aufgerufen. **NICHT
  einzeln geprüft** (zu viele für manuelle Einzelprüfung ohne Reachability-
  Graph). Wichtig: ein `SELF_ONLY`-Aufrufer kann selbst tot sein (siehe
  `install_global_exception_handler` unten) — reine Zählung reicht hier
  nicht, ein echter Reachability-Graph ab `bot.py`/Konstruktoraufrufen wäre
  der saubere nächste Schritt, nicht Einzel-Grep.
- **22 DEAD? → alle 22 einzeln verifiziert, bestätigt DEAD**
- **5 DYNAMICALLY_USED? → alle 5 verifiziert, tatsächlich ACTIVE**
  (String-Treffer stammten ausschließlich aus `mock.patch.object(...)` in
  Tests, keine echte dynamische Dispatch-Nutzung im Produktionscode)
- **4 TEST_ONLY → 3 DEAD, 1 Sonderfall (Funktionslücke, siehe unten)**

## Bestätigt DEAD (22) — Kandidaten für einen künftigen Cleanup-PR

**Alternative Factory-/Integrations-Funktionen** (identisches Muster wie
der bereits gefixte `ErrorHandlerIntegration`-Fall, Commit `8965d87`,
2026-09-02 — die echte Verdrahtung in `bot.py`/`rich_menu_handler.py`
konstruiert die Zielobjekte direkt, nie über diese Funktionen):
- `integrate_enhanced_error_handler` (`handlers/enhanced_error_handler.py:1973`)
  + `install_global_exception_handler` (Zeile 1991, einziger Aufrufer ist
  die vorgenannte tote Funktion)
- `try_catch_decorator` (`handlers/enhanced_error_handler.py:2129`)
- `integrate_enhanced_logger_handler` (`handlers/enhanced_logger_menu_handler.py:1794`)
- `integrate_status_handler` (`handlers/enhanced_status_handler.py:795`)
- `create_statistics_handler` (`handlers/mugge_statistik_handler.py:582`)
- `create_navidrome_handler` (`handlers/navidrome_menu_handler.py:1205`)
- `create_test_handler` (`handlers/test_menu_handler.py:769`)

**Tote Setter + nie befüllte Attribute:**
- `RichMenuHandler.set_download_handler` (Zeile 388) — `self.download_handler`
  wird nirgends sonst gesetzt/gelesen; der echte `DownloadHandler` wird pro
  Update frisch instanziiert (Zeile 810).
- `RichMenuHandler.set_admin_handler` (Zeile 396) — `self.admin_handler`
  ebenso nie sonst gesetzt/gelesen.

**Wrapper, durch Dispatch-Tabelle/inline-Logik ersetzt:**
- `RichMenuSystem._handle_backup_bot_start`/`_handle_backup_lib_start`
  (Zeilen 901/910) — reale Route ist das `routing_map`-Dict (Zeile ~1755),
  ruft `backup_handler.start_bot_backup`/`start_lib_backup` direkt.
- `EnhancedErrorHandler.handle_menu_system_error` (Zeile 1536) — reale
  Fehlerbehandlung nutzt `error_handler.handle_callback_error()`.
- `UserManagementHandler.add_new_user` (Zeile 795) — Button
  `usermgmt_add_user` ist inline in `rich_menu_system.py` (Workflow-
  basiert) implementiert, ruft diese Methode nicht.
- `EnhancedLoggerMenuHandler.handle_log_level_change` (Zeile 1603) — im
  Code selbst als "Legacy-Funktion" dokumentiert.
- `RichMenuSystem._find_menu_by_callback` (Zeile 1855) — keine Aufrufer.
- `EnhancedStatusHandler.format_bytes` (Zeile 770) — `_build_storage_report()`
  formatiert Bytes inline selbst (`size / (1024**3)`), ruft diese Methode
  nicht.
- `NavidromeMenuHandler.handle_recent` (Zeile 846) — implementiert, aber
  nie in ein Menü verdrahtet: kein Button mit passendem `callback_data`
  existiert im gesamten `navidrome_menu_handler.py`.

**Ganze tote Klassen** (nicht nur einzelne Methoden):
- `LoggerModuleManager` (inkl. `create_module_logger`) — nirgends
  instanziiert.
- `LoggerStatsTracker` (inkl. `capture_snapshot`) — im Code selbst
  auskommentiert: `# self.stats_tracker = LoggerStatsTracker() #
  Auskommentiert, da nicht verwendet`.
- `MediaItem` (inkl. `get_display_text`) — nirgends instanziiert.

**Sonstige:**
- `ModuleLoggerManager.get_module_log_file` (Zeile 212) — Klasse selbst
  aktiv genutzt, diese eine Methode nicht.
- `MusicBrainzClient._extract_release_group_id` (Zeile 142) — keine
  Aufrufer.

## Cleanup durchgeführt (2026-09-03)

Vor der Löschung wurden alle 22 Kandidaten nochmals frisch repoweit
gegrept (CLAUDE.md Abschnitt 20 — Wiederholungsnachweis unmittelbar vor
der Löschung, nicht nur Verlass auf den obigen, etwas älteren Audit-
Stand). Dabei 2 zusätzliche, transitiv tote Funde entdeckt und im selben
Zug entfernt:
- `create_enhanced_logger_handler` (`handlers/enhanced_logger_menu_handler.py`)
  — einziger Aufrufer war das bereits oben gelistete
  `integrate_enhanced_logger_handler`.
- `EnhancedErrorHandler._menu_fallback_recovery` — einziger Aufrufer war
  das oben gelistete `handle_menu_system_error`.

Alle 24 (22 + 2) sind entfernt. Zwei Tests, die direkt auf gelöschte
Symbole zeigten, wurden mitentfernt statt umgeschrieben, da sie
ausschließlich die gelöschte Funktion selbst testeten:
`tests/test_test_menu_handler.py::test_create_test_handler_factory`,
`tests/test_enhanced_status_handler.py::TestFormatBytes`.

**Bewusst nicht mit entfernt:** `logger.py::setup_module_logging()` ist
seit dieser Löschung doppelt verwaist (sein einziger Aufrufer
`toggle_module()` in `handlers/enhanced_logger_menu_handler.py` hat ihn
schon vorher real nie aufgerufen — ein pre-existing, vom Nutzer live
gemeldeter Bug: Modul-Logger lassen sich über das Inline-Button-Menü
aktivieren, schreiben dabei aber nicht in eine Log-Datei. Nicht durch
diesen Sweep verursacht, bisher nicht gefixt, noch nicht in
`docs/FINDINGS_INDEX.md` erfasst). `logger.py` liegt außerhalb des
17-Datei-Scopes dieses Sweeps und wird hier nicht mitgeprüft.

Volle Testsuite nach dem Cleanup: 2165 passed, 1 skipped, 0 Regressionen.

## UNCERTAIN (2) — bewusst NICHT als DEAD eingestuft

`RichMenuHandler._initiate_download`/`_handle_regular_url` (Zeilen
1207/1216) — im Code selbst explizit als "Legacy-Wrapper – bleibt für
Rückwärtskompatibilität erhalten, wird von älterem Code ggf. noch
aufgerufen" dokumentiert. CLAUDE.md Abschnitt 20 verlangt hier zusätzliche
Vorsicht vor Entfernung — die Unsicherheit steht bereits im Code selbst,
0 gefundene Aufrufer beweisen nicht automatisch die Abwesenheit externer/
historischer Aufrufer.

## Echter Funktions-Fund, kein Cleanup-Kandidat (2)

`BotStatusTracker.update_handler_status`/`record_user_activity`
(`handlers/enhanced_status_handler.py:214`/`229`) — die Klasse wird
instanziiert (`self.bot_tracker = BotStatusTracker(config)`) und ihre
Daten werden im Admin-Status angezeigt ("Aktive Users: …"), aber die
beiden schreibenden Methoden werden nirgends aufgerufen — das Dashboard
zeigt vermutlich dauerhaft leere/0-Werte. Kein toter Code zum Löschen,
sondern eine vermutlich seit jeher nicht funktionierende Anzeige — eigene
Entscheidung nötig (Feature verdrahten oder Anzeige+Methoden zusammen
entfernen).

## Falsch-positiv, verifiziert ACTIVE (5)

`_build_storage_report`, `_escape_text`, `cached_musicbrainz_search`,
`_get_artist_normalizer`, `_build_url` — String-Treffer stammten
ausschließlich aus `mock.patch.object(instance, "name", ...)` in Tests,
nicht aus echtem dynamischem Dispatch. Alle haben reale interne Aufrufer.

## Offen für die Fortsetzung

1. Die 182 `SELF_ONLY?`-Kandidaten — Reachability-Graph ab den echten
   Einstiegspunkten (`bot.py`, Konstruktoraufrufe) statt Einzel-Grep.
2. ~~Entscheidung zu `update_handler_status`/`record_user_activity`~~ —
   erledigt, siehe `docs/FINDINGS_INDEX.md` (Zeile „BotStatusTracker").
3. ~~Cleanup-PR für die 22 bestätigten DEAD-Funde~~ — erledigt, siehe
   „Cleanup durchgeführt (2026-09-03)" oben.
4. `logger.py::setup_module_logging()` (doppelt verwaist seit dem
   Cleanup) und der zugrundeliegende Logger-Toggle-Bug — separater,
   noch offener Fund, siehe „Cleanup durchgeführt" oben.
