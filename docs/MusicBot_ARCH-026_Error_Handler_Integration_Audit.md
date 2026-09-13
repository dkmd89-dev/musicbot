# MusicBot ARCH-026 — Enhanced Error Handler Integration & Coverage Audit

> **Status: read-only Audit abgeschlossen. Keine Code-Änderungen in dieser
> Phase** (siehe Abschnitt „Architekturentscheidung" für die Begründung,
> warum die identifizierten Lücken nicht in dieser Phase behoben werden).

---

## Ausgangslage

`handlers/enhanced_error_handler.py` (2016 Zeilen) enthält `ExceptionMonitor`,
`DebugTracker`, `EnhancedErrorHandler`, `ErrorHandlerAdminInterface` sowie
die Factory-Funktion `create_enhanced_error_handler()`. `bot.py` erstellt
einen `EnhancedErrorHandler` und registriert `handle_telegram_error` als
globalen PTB-Error-Handler (`application.add_error_handler(...)`). Diese
Grundintegration existiert bereits und wurde als Ausgangspunkt genommen,
nicht neu implementiert.

Ein früherer Cleanup (`docs/FINDINGS_INDEX.md`, Zeile „Handler-Methoden-
Level-Sweep, 2026-09-03") hat bereits 5 tote Funktionen direkt aus dieser
Datei entfernt: `integrate_enhanced_error_handler`,
`install_global_exception_handler`, `try_catch_decorator`,
`handle_menu_system_error`, `_menu_fallback_recovery`. Das erklärt, warum
`handle_menu_system_error` (im Master-Prompt als zu prüfende Funktion
genannt) im aktuellen Code **nicht mehr existiert** — die Hypothese war
historisch korrekt, ist aber durch diesen bereits abgeschlossenen Cleanup
überholt. Kein neuer Befund, nur Klarstellung.

---

## Aktuelle Integration

Bestätigt (Code-Evidenz, `bot.py:80-172`):

```text
Application.builder().build()
        ↓
create_enhanced_error_handler(config)          → self.error_handler (Bot-Instanz A)
        ↓
application.add_error_handler(self.error_handler.handle_telegram_error)
        ↓
RichMenuHandler(config) + .initialize()
        ↓
application.add_handler(...) für alle RichMenuHandler-Handler
        ↓
ErrorHandlerAdminInterface(self.error_handler, ADMIN_USER_IDS, config)  (wrappt Instanz A)
        ↓
rich_menu_handler.set_error_admin_interface(...)
```

`handle_telegram_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None`
entspricht exakt der von PTB 22.7 erwarteten Callback-Signatur für
`Application.add_error_handler()`
(`Callable[[object, CCT], Coroutine[Any, Any, None]]`, per
`inspect.signature()` verifiziert). **PTB-Integration ist syntaktisch und
semantisch korrekt.**

**Zentraler, bisher nicht dokumentierter Befund:** `RichMenuHandler.initialize()`
(`handlers/menu/rich_menu_handler.py:186-189`) erstellt **eine zweite,
komplett unabhängige** `EnhancedErrorHandler`-Instanz:

```python
self.error_handler = create_enhanced_error_handler(
    self.config, self.logger_factory
)
```

`bot.py` übergibt diese Instanz **niemals** an `RichMenuHandler` — es gibt
keinen Aufruf von `rich_menu_handler.set_error_handler(...)` oder einer
Zuweisung `rich_menu_handler.error_handler = self.error_handler` irgendwo
in `bot.py` (repoweit verifiziert). `RichMenuHandler.set_error_handler()`
(Zeile 573) existiert zwar, hat aber **keinen externen Aufrufer** — nur
sich selbst intern (`self.menu_system.set_error_handler(handler)`, Zeile
578). Instanz A (bot.py, PTB-registriert) und Instanz B
(RichMenuHandler, an fast alle Sub-Handler propagiert) sind zwei separate
Python-Objekte mit vollständig getrenntem State (`ExceptionMonitor`,
`DebugTracker`, `recovery_attempts` — alles Instanzattribute, kein
Klassen-/Modul-Singleton, siehe `EnhancedErrorHandler.__init__`,
`ExceptionMonitor.__init__`, `DebugTracker.__init__`).

Siehe Abschnitt „Duplicate/Error-Handling Paths" für die praktische
Konsequenz.

---

## Factory Functions

| Function | Definition | Aufrufer | Runtime-Status |
|---|---|---|---|
| `create_enhanced_error_handler(config, logger_factory=None)` | Zeile 1899, dünner Konstruktor-Wrapper um `EnhancedErrorHandler(...)` | `bot.py:100` (Instanz A, 1 Arg), `handlers/menu/rich_menu_handler.py:187` (Instanz B, 2 Args) | **ACTIVE** — einzige verbleibende Factory-Funktion nach dem 2026-09-03-Cleanup; wird tatsächlich zweimal aufgerufen und erzeugt dabei die oben beschriebene Instanz-Duplizierung. |

Keine weiteren Factory-Funktionen vorhanden — die im Master-Prompt
genannten weiteren Kandidaten (`integrate_*`, `install_global_exception_handler`,
`try_catch_decorator`) wurden bereits am 2026-09-03 entfernt (siehe
Ausgangslage).

---

## Production Integration

Unterscheidung `DOCUMENTATION EXAMPLE` ≠ `PRODUCTION INTEGRATION`, geprüft
für jedes der 5 Beispiele im Abschnitt „VERWENDUNGSBEISPIELE UND
DOKUMENTATION" (Zeilen 1916-2015, ein reiner String-Literal ohne
Laufzeitwirkung — kein Docstring, keine Funktion):

| # | Beispiel | Entspricht Produktion? | Evidenz |
|---|---|---|---|
| 1 | Basis-Integration (`error_handler = create_enhanced_error_handler(config)`; `command_integration.error_handler = error_handler`) | Teilweise — das Zuweisungsmuster (`x.error_handler = handler`) entspricht real dem, was `RichMenuHandler.initialize()` für ~11 Sub-Handler tut; `command_integration` als Name existiert nirgends, reine Illustration. | `rich_menu_handler.py:200,207,256,267,281,293,302,336,351,367,381` |
| 2 | Decorator-Verwendung (`@error_handler.handle_async_exceptions(...)`, `@error_handler.handle_sync_exceptions(...)`) | **NEIN** — `grep -rn "handle_async_exceptions\|handle_sync_exceptions"` findet außerhalb der Definitionsdatei und der Tests **keinen einzigen Treffer** im gesamten Repository. Reine Dokumentationsvorlage, nie produktiv verwendet. | repoweiter Grep, 0 Treffer |
| 3 | Manuelle Exception-Behandlung (`await error_handler.handle_exception(...)`) | **NEIN** als direkter Aufruf — `grep -rn "\.handle_exception\("` außerhalb der Datei selbst: 0 Treffer. Produktiv wird ausschließlich über die drei höheren Entry-Points `handle_telegram_error`/`handle_command_error`/`handle_callback_error` gegangen, die `handle_exception()` intern aufrufen. | repoweiter Grep, 0 Treffer |
| 4 | Monitoring/Statistiken (`get_comprehensive_statistics`, `create_health_report`, `get_recent_exceptions_summary`) | **JA** — exakt diese drei Methoden sind die Grundlage von `ErrorHandlerAdminInterface.handle_error_stats_command`/`handle_error_report_command`/`handle_recent_errors_command`. | `enhanced_error_handler.py:1644,1707,1758` |
| 5 | Debug-Session-Tracking (direkter Aufruf von `error_handler.debug_tracker.start_session/log_step/end_session` von außen) | **NEIN** — `grep -rn "\.debug_tracker\."` außerhalb der Datei selbst: 0 Treffer. `DebugTracker` wird ausschließlich intern von `EnhancedErrorHandler`s eigenen Methoden verwendet. | repoweiter Grep, 0 Treffer |

**Fazit:** Von 5 dokumentierten Verwendungsbeispielen entspricht nur
Beispiel 4 tatsächlich der produktiven Nutzung. Beispiele 2, 3 und 5 sind
reine Dokumentationsartefakte ohne produktive Entsprechung — Beispiel 3
beschreibt sogar einen Aufrufpfad (direkter `handle_exception()`-Aufruf),
der in der Praxis durch die drei spezialisierten Wrapper ersetzt wurde,
ohne dass die Dokumentation nachgezogen wurde.

---

## PTB Integration

- **Version:** `python-telegram-bot==22.7` (per `pip show`/`telegram.__version__` verifiziert).
- **Signatur:** `Application.add_error_handler(callback: Callable[[object, CCT], Coroutine[Any, Any, None]], block: bool = True)` — `handle_telegram_error` erfüllt dies exakt.
- **`block=True` (Default):** PTB verarbeitet Error-Handler synchron zur laufenden Update-Verarbeitung — während `handle_telegram_error` läuft (inkl. der bis zu `await asyncio.sleep(2)` in `_recover_network_error`), wird kein weiteres Update dieser Application verarbeitet, sofern nicht `concurrent_updates=True` gesetzt ist (bot.py setzt es nicht, siehe `handlers/menu/actions/download.py`-Docstring, der genau diese Einschränkung bereits für die Download-Pipeline dokumentiert und deshalb bewusst einen Hintergrund-Task verwendet). Kein Bug, aber eine Randnotiz: ein sehr seltener Recovery-Pfad mit `asyncio.sleep()` verzögert nachfolgende Updates geringfügig.
- **Update-lose Exceptions:** `handle_telegram_error(update: object, ...)` behandelt `update=None` explizit (`_extract_update_info`/`_build_full_context` sind null-safe, `handle_exception()` prüft `if update:` vor Update-spezifischer Verarbeitung) — Exceptions aus Job-Queue-Callbacks oder anderen update-losen Kontexten werden nicht crashen, laufen aber ohne Recovery/Nutzerbenachrichtigung (da beide an `update`+`telegram_context` gebunden sind, siehe `handle_exception()` Zeilen 432-442).
- **CallbackQuery-Fehler:** laufen über `handle_callback_error()`, das denselben `handle_exception()`-Kern nutzt — funktional konsistent zu Command-Fehlern.

---

## RichMenu Integration

`RichMenuSystem.handle_callback()` (`handlers/menu/rich_menu_system.py`)
wrappt den **gesamten** Callback-Dispatch (Menu-Lookup, Permission-Gate,
Handler-Aufruf) in einen einzigen `try/except Exception`, der bei Fehler
`self.error_handler.handle_callback_error(update, context, callback_data, e)`
aufruft (Zeilen 740-746) — dies ist der zentrale Catch-All für **alle**
`menu:`-Callbacks und alle Domänen ohne eigene lokale Fehlerbehandlung
(Family-Chat, Family-Challenge, Bot-Restart, Doctor/Review/Repair/
Reprocessing — siehe Coverage-Matrix). `self.error_handler` hier ist
**Instanz B** (von `RichMenuHandler.initialize()` gesetzt via
`self.menu_system.error_handler = self.error_handler` UND redundant
zusätzlich `self.menu_system.set_error_handler(self.error_handler)` —
beide Zeilen weisen dieselbe Instanz zu, keine funktionale Doppelwirkung,
nur ein überflüssiger zweiter Zuweisungsweg).

**Verwendet `RichMenuSystem` dieselbe Instanz wie die Telegram
Application?** **Nein.** `RichMenuSystem`/`RichMenuHandler` und alle
daran hängenden Sub-Handler verwenden ausschließlich Instanz B; die
Telegram-`Application`s PTB-Fallback verwendet Instanz A. Bewertung: dies
ist keine erkennbar bewusste, dokumentierte Entscheidung (kein Kommentar,
kein Docstring-Hinweis, keine Findings-Index-Eintragung dazu, anders als
z. B. bei `StatistikHandler`s dokumentiertem Verzicht) — es liegt näher
an **ARCHITECTURAL DUPLICATION** als an `INTENTIONAL`. Wahrscheinlichste
Erklärung: `RichMenuHandler.initialize()` wurde ursprünglich eigenständig
entwickelt/getestet (kann `RichMenuHandler(config)` ohne `bot.py`
instanziieren, z. B. in Tests) und erzeugt deshalb pragmatisch seinen
eigenen Error Handler, statt eine Injection-Schnittstelle von `bot.py`
zu erwarten — seither wurde dies nie vereinheitlicht.

---

## Handler Propagation

Alle Handler mit `TYPE_CHECKING`-Import von `EnhancedErrorHandler` +
`self.error_handler`-Attribut, geprüft auf tatsächliche Injection UND
tatsächliche Verwendung:

| Handler | Type-only Ref | Erhält Instanz B (RichMenuHandler.initialize()) | Ruft `error_handler.handle_*` tatsächlich auf |
|---|---|---|---|
| `NavidromeMenuHandler` | ✅ | ✅ (Zeile 256) | ✅ (8× `handle_callback_error`) |
| `EnhancedDuplicateHandler` | ✅ | ✅ (Zeile 281) | ✅ (2×) |
| `EnhancedStatusHandler` | — (kein TYPE_CHECKING-Import, aber Attribut wird gesetzt) | ✅ (Zeile 293) | ✅ (1×) |
| `BackupHandler` | ✅ | ✅ (Zeile 302) | ✅ (2×) |
| `ReprocessingMenuHandler` | ✅ | ✅ (Zeile 336) | ❌ **kein einziger Aufruf** — nur Deklaration `self.error_handler: Optional["EnhancedErrorHandler"] = None` |
| `LibraryDoctorHandler` | ✅ | ✅ (Zeile 351) | ❌ **kein einziger Aufruf** |
| `LibraryHealthReviewHandler` | ✅ | ✅ (Zeile 367) | ❌ **kein einziger Aufruf** |
| `RepairMusicBotHandler` | ✅ | ✅ (Zeile 381) | ❌ **kein einziger Aufruf** |
| `EnhancedLoggerMenuHandler` | ✅ | ✅ (Zeile 207) | ✅ (13×) |
| `UserManagementHandler` | ✅ | ✅ (Zeile 267) | ✅ (3×) |
| `TestMenuHandler` | ✅ | ✅ (Zeile 200) | ✅ (7×) |
| `StatistikHandler` | — | ❌ nie zugewiesen | n/a — **dokumentierter, bewusster Verzicht** (Klassen-Docstring + `docs/FINDINGS_INDEX.md`, CLOSED won't-fix 2026-09-02) |
| `FamilyStatsHandler` | — | ❌ nie zugewiesen | n/a — Docstring verweist auf dieselbe Begründung wie `StatistikHandler` |
| `FamilyChatHandler` | — | ❌ nie zugewiesen | n/a — **kein Docstring-Hinweis**, kein dokumentierter Verzicht |
| `FamilyChallengeHandler` | — | ❌ nie zugewiesen | n/a — **kein Docstring-Hinweis**, kein dokumentierter Verzicht |
| `BotRestartHandler` | — | ❌ nie zugewiesen | n/a — **kein Docstring-Hinweis**, kein dokumentierter Verzicht |

**Konkreter Befund:** 4 Handler (`ReprocessingMenuHandler`,
`LibraryDoctorHandler`, `LibraryHealthReviewHandler`,
`RepairMusicBotHandler`) deklarieren einen `EnhancedErrorHandler`-Typ,
erhalten die echte Instanz injiziert, rufen sie aber **nirgends** auf —
exakt das im Master-Prompt (Abschnitt 9) beschriebene Zielproblem
("Komponenten, die einen Error Handler typisieren, ohne dass klar ist,
ob sie ihn zur Laufzeit tatsächlich nutzen"). Praktische Konsequenz
gering, da alle vier ausschließlich über `menu:`-artige Callback-Präfixe
(`reprocess:`, `doctor:`, `review:`, `repair:`) laufen, die durch
`RichMenuSystem.handle_callback()`s zentralen Catch-All (s. o.) ohnehin
mit **derselben Instanz B** abgesichert sind — kein Coverage-Loch, aber
eine tote, verwirrende Injection ohne Zweck.

Für `FamilyChatHandler`/`FamilyChallengeHandler`/`BotRestartHandler`
existiert weder Injection noch dokumentierter Verzicht — auch diese drei
sind aber über denselben `RichMenuSystem`-Catch-All abgesichert.

---

## Decorator Usage

`handle_async_exceptions()`/`handle_sync_exceptions()` (Zeilen
1103-1259): **0 produktive Verwendungen** repoweit (auch 0 in Tests).

Zusätzlicher, bisher nicht dokumentierter Befund — ein **latenter Bug in
totem Code**: beide Decorator-Wrapper prüfen bei einer aufgefangenen
Exception `self.config.get("SUPPRESS_HANDLED_EXCEPTIONS", False)`
(Zeilen 1180, 1246). `config: Config` (`config.py:57`) ist eine reine
Attribut-Klasse ohne `.get()`-Methode und ohne `__getattr__` (verifiziert:
`grep -n "def get\b\|__getattr__" config.py` → 0 Treffer). Würde einer
der beiden Decorators produktiv verwendet, würfe dieser Codepfad bei
jeder abgefangenen Exception zusätzlich einen `AttributeError`, der die
ursprüngliche Exception maskiert. Erklärt zusätzlich plausibel, warum
diese Decorators nie produktiv aufgenommen wurden — vermutlich nie gegen
die echte `config.Config` getestet.

**Doppelte Debug-Session-Verwaltung (bestätigt, wie im Master-Prompt
Abschnitt 13 hypothetisiert):** Jeder High-Level-Entry-Point
(`handle_telegram_error`, `handle_command_error`, `handle_callback_error`)
UND beide Decorators rufen `self.debug_tracker.start_session(session_id, {...})`
mit einem **selbst erzeugten** `session_id` auf, loggen 1 Step, und
übergeben denselben `session_id` an `handle_exception(...)`.
`handle_exception()` ruft **unbedingt** (ohne Existenzprüfung) selbst
erneut `self.debug_tracker.start_session(session_id, {...})` auf (Zeile
384) — das überschreibt die vom Aufrufer bereits angelegte Session
(`DebugTracker.start_session()` setzt `self.sessions[session_id] = session`
ohne Merge, Zeile 211) vollständig, inklusive des bereits geloggten
Schritts. Der ursprüngliche, entry-point-spezifische Kontext
(`telegram_error`/`command_name`/`callback_data`) geht damit für die
`DebugTracker`-Session verloren (bleibt aber über den separaten
`context=`-Parameter im Exception-Logging selbst erhalten — kein
Informationsverlust im Log, nur im Debug-Session-Objekt).

Analog am Ende: `handle_exception()`s eigener `finally`-Block ruft
`self.debug_tracker.end_session(session_id)` auf und **entfernt die
Session aus `self.sessions`** (Zeile 260, `del self.sessions[session_id]`).
Kehrt die Kontrolle danach zum Decorator zurück, ruft dessen **eigener**
`finally`-Block **erneut** `end_session(session_id)` auf — `end_session()`
prüft `if session_id in self.sessions:` (Zeile 248) und ist dadurch ein
stiller No-Op. **Bestätigt: doppelter `end_session()`-Aufruf existiert,
ist aber harmlos** (kein Crash, kein doppelter Historieneintrag) — reine
Redundanz, kein funktionaler Bug.

`asyncio.create_task()` in `handle_sync_exceptions()` (Zeile 1242):
feuert `handle_exception()` als Fire-and-Forget-Task ohne
`add_done_callback()`. Träte darin eine weitere Exception auf (z. B.
genau der oben beschriebene `AttributeError` aus
`self.config.get(...)`, falls dieser Codepfad erreicht würde), ginge sie
als unbeobachtete Task-Exception unter (`asyncio`-Warnung "Task exception
was never retrieved", kein Crash des Hauptprozesses) — dasselbe Muster,
gegen das `handlers/menu/actions/download.py::_log_background_download_task_exception()`
bewusst eine Absicherung baut. Da der Decorator ohnehin unbenutzt ist,
rein theoretisch relevant.

---

## Error Coverage Matrix

| Component | Central PTB coverage (Instanz A, Fallback) | Direct handler (Instanz B, lokal) | Decorator | Local try/except (ohne error_handler) | Status |
|---|---|---|---|---|---|
| `bot.py` | ✅ (registriert Instanz A) | — | — | ✅ (Initialisierungs-try/excepts, `critical`+`raise`) | Vollständig, einzige Quelle für Instanz A |
| `RichMenuSystem` | ✅ (Fallback, falls Instanz-B-Aufruf selbst crasht) | ✅ (zentraler Catch-All in `handle_callback()`) | — | — | Vollständig (Instanz B) |
| `RichMenuHandler` | ✅ (Fallback) | ✅ (`greeting.py`/`help.py` via `handle_command_error`) | — | — | Vollständig (Instanz B) |
| Download (`klassen/download_handler.py`) | ⚠️ nur für den `process_url()`-Aufruf selbst, NICHT für den Download-Hintergrund-Task | ❌ **keine einzige Referenz auf `error_handler` in der gesamten Datei (1162 Zeilen)** | — | ✅ (breite eigene try/excepts, eigene Nutzer-Nachrichten) | **Kein Central-Handler-Kontakt** — P0-Domäne läuft vollständig außerhalb beider `EnhancedErrorHandler`-Instanzen; Hintergrund-Task-Exceptions landen nur in `_log_background_download_task_exception()` (reines Logging, keine Nutzerbenachrichtigung, kein Monitoring) |
| Navidrome | ✅ (Fallback) | ✅ (8× `handle_callback_error`) | — | teils | Vollständig (Instanz B) |
| Duplicate | ✅ (Fallback) | ✅ (2×) | — | teils | Vollständig (Instanz B) |
| Library (Doctor/Review/Repair) | ✅ (Fallback über `RichMenuSystem`) | ❌ injiziert, aber ungenutzt | — | teils (lokale Excepts ohne error_handler) | Coverage vorhanden (über zentralen Catch-All), aber tote Injection |
| Backup | ✅ (Fallback) | ✅ (2×) | — | teils | Vollständig (Instanz B) |
| Reprocessing | ✅ (Fallback über `RichMenuSystem`) | ❌ injiziert, aber ungenutzt | — | teils | Coverage vorhanden, tote Injection |
| User Management | ✅ (Fallback) | ✅ (3×) | — | teils | Vollständig (Instanz B) |
| Admin (Logger/Status) | ✅ (Fallback) | ✅ (`EnhancedLoggerMenuHandler` 13×, `EnhancedStatusHandler` 1×) | — | teils | Vollständig (Instanz B) |
| Admin (Error-Monitoring selbst, `ErrorHandlerAdminInterface`) | — (wrapt direkt Instanz A) | n/a | — | ✅ (jede Admin-Methode hat eigenen try/except) | Funktional, aber **zeigt nur Instanz-A-Statistiken** — sieht keine der über Instanz B gelaufenen Exceptions |
| Family-Stats/-Chat/-Challenge, Bot-Restart | ✅ (Fallback über `RichMenuSystem`) | ❌ keine Injection | — | 1 Ausnahme (`FamilyChatHandler`) | Coverage vorhanden (zentraler Catch-All), kein dokumentierter Grund für Nicht-Injection |
| Statistik (`StatistikHandler`) | ✅ (Fallback) | ❌ bewusst nicht integriert (dokumentiert) | — | ✅ (editiert gezielt die eigene Zwischennachricht) | **Vollständig funktional äquivalent**, dokumentierte Ausnahme, CLOSED won't-fix |

---

## Unhandled Paths

Repoweite Suche nach stillen/verschluckten Exceptions in
`enhanced_error_handler.py` selbst (Fokus des Audits; ein repoweiter
Sweep aller `except: pass`/`except Exception: pass` außerhalb dieser
Datei ist expliziter Scope einer eigenen Findings-Kategorie und würde
den Rahmen dieses Integrationsaudits sprengen):

- `_recover_telegram_error()`, Zeilen 982/987: zwei verschachtelte bare
  `except:`-Blöcke beim Best-Effort-Versuch, den Nutzer über einen
  bereits fehlgeschlagenen Recovery-Versuch zu informieren — **bewusst
  und angemessen** (letzter Fallback, würde sonst eine Exception im
  Exception-Handler selbst erzeugen).
- `handle_exception()`, Zeilen 460-471: äußerer `except Exception as
  handler_exception` fängt Meta-Fehler im Error-Handler selbst ab,
  loggt `critical` und gibt `"HANDLER_ERROR"` zurück statt erneut zu
  werfen — bewusstes Design (ein fehlerhafter Error-Handler darf den Bot
  nicht crashen), aber bedeutet: ein Bug **im** `EnhancedErrorHandler`
  selbst wird nie sichtbar an PTB weitergereicht, nur geloggt.
- Download-Hintergrund-Task (`_log_background_download_task_exception`):
  kein Verschlucken (wird geloggt), aber kein Erreichen irgendeiner
  `EnhancedErrorHandler`-Instanz — siehe Coverage-Matrix.

**Kein Fund von unkontrolliert verschluckten Exceptions ohne jegliches
Logging** innerhalb der geprüften Kern-Pfade.

---

## Duplicate/Error-Handling Paths

Die zentrale, bisher nicht dokumentierte Architekturinkonsistenz dieses
Audits: **zwei unabhängige `EnhancedErrorHandler`-Instanzen** (A in
`bot.py`, B in `RichMenuHandler`) mit getrenntem `ExceptionMonitor`
(Exception-Historie, Statistiken), `DebugTracker` (Sessions) und
`recovery_attempts` (Recovery-Rate-Limiting pro `user_id_category`).

Praktische Konsequenzen:

1. **Fragmentierte Statistiken:** `/error_stats`, `/error_report`,
   `/recent_errors` (alle über `ErrorHandlerAdminInterface`, die
   ausschließlich Instanz A kennt) zeigen **nur** Exceptions, die den
   PTB-Fallback tatsächlich erreichen — das sind praktisch nur Bugs
   innerhalb `RichMenuSystem.handle_callback()`s eigener Routing-/
   Permission-Logik selbst oder in Command-Handlern ohne jede lokale
   Absicherung. Die überwältigende Mehrheit der tatsächlich behandelten
   Exceptions (alle `handle_callback_error`/`handle_command_error`-Aufrufe
   aus Navidrome/Duplicate/Backup/Logger/UserMgmt/RichMenuSystem selbst)
   läuft über Instanz B und ist für die Admin-Befehle **unsichtbar**.
2. **`reset_statistics()` (Admin-Befehl `/reset_error_stats`) wirkt nur
   auf Instanz A** — die für die meisten echten Fehler relevante
   Instanz B hat keinen erreichbaren Reset-Mechanismus. `recovery_attempts`
   (ein `defaultdict(int)`, siehe Abschnitt „Recovery-Architektur") wächst
   dort unbegrenzt über die Prozesslaufzeit, ohne je zurückgesetzt zu
   werden können.
3. **`cleanup_old_data()`** wird periodisch (`bot.py::_periodic_cleanup()`,
   alle 5 Minuten) und beim Shutdown ausschließlich auf Instanz A
   aufgerufen — Instanz B (die tatsächlich stark genutzte) hat keinen
   automatischen Cleanup-Zyklus. Da `exception_history`
   (`deque(maxlen=1000)`) und `debug_tracker.session_history`
   (`deque(maxlen=100)`) beide selbstbegrenzend sind, kein
   Speicherleck — aber `recovery_attempts` bei Instanz B ist unbegrenzt
   UND ohne Cleanup-Pfad (siehe Punkt 2).

Bewertung entlang der im Master-Prompt vorgegebenen Alternative
(Abschnitt 8): **ARCHITECTURAL DUPLICATION**, nicht `INTENTIONAL` — es
gibt keinen Kommentar, keinen Docstring-Hinweis und keinen
Findings-Index-Eintrag, der diese Aufspaltung begründet (im Gegensatz zu
`StatistikHandler`s expliziter, dokumentierter Nichtintegration).

---

## Findings

| # | Finding | Schwere | Typ |
|---|---|---|---|
| F1 | Zwei unabhängige `EnhancedErrorHandler`-Instanzen (bot.py „A" vs. RichMenuHandler „B"), nie synchronisiert; `RichMenuHandler.set_error_handler()` hat keinen externen Aufrufer | Hoch (Monitoring-Blindspot) | Architectural Duplication |
| F2 | Admin-Monitoring (`/error_stats`, `/error_report`, `/recent_errors`, `/reset_error_stats`) sieht nur Instanz A — die für ~90% der tatsächlichen `handle_callback_error`/`handle_command_error`-Aufrufe irrelevante Instanz | Hoch | Coverage Gap (Folge von F1) |
| F3 | `recovery_attempts` von Instanz B wächst unbegrenzt (defaultdict, nie zurückgesetzt, da Reset nur Instanz A erreicht) | Mittel | Resource/Recovery-Architektur (Folge von F1) |
| F4 | Download-Pipeline (`klassen/download_handler.py`, P0-Domäne) hat **keine einzige** `error_handler`-Referenz — läuft vollständig außerhalb beider Instanzen; Hintergrund-Task-Exceptions nur geloggt, kein Monitoring/keine Recovery | Hoch (P0-Domäne betroffen) | Coverage Gap |
| F5 | `handle_async_exceptions()`/`handle_sync_exceptions()`: 0 produktive Verwendungen, UND latenter `AttributeError`-Bug bei Auslösung (`self.config.get(...)` auf `Config`-Instanz ohne `.get()`) | Niedrig (totes, aber fehlerhaftes Feature) | Dead Code + Latent Bug |
| F6 | 4 Handler (`ReprocessingMenuHandler`, `LibraryDoctorHandler`, `LibraryHealthReviewHandler`, `RepairMusicBotHandler`) erhalten `error_handler` injiziert, rufen ihn aber nie auf | Niedrig (kein Coverage-Loch dank zentralem Catch-All, aber irreführend) | Dead Injection |
| F7 | `FamilyChatHandler`/`FamilyChallengeHandler`/`BotRestartHandler` haben weder `error_handler`-Injection noch dokumentierten Verzicht (anders als `StatistikHandler`/`FamilyStatsHandler`) | Niedrig (kein Coverage-Loch dank zentralem Catch-All) | Undokumentierte Inkonsistenz |
| F8 | Doppelte `start_session()`/`end_session()`-Aufrufe an allen High-Level-Entry-Points und beiden Decoratoren — überschreibt/verwirft den entry-point-spezifischen `DebugTracker`-Kontext, harmlos (kein Crash, kein doppelter Historieneintrag) | Niedrig | Redundanz (kein funktionaler Bug) |
| F9 | Kompatibilitäts-Wrapper `handle_error()` (Zeile 298) hat 0 Aufrufer außerhalb der eigenen Definition | Niedrig | Dead Code |
| F10 | `export_debug_session()`/direkte `.debug_tracker.*`-Nutzung von außen: 0 produktive Verwendungen (nur Dokumentationsbeispiel 5) | Niedrig | Dead Code (dokumentiert als Beispiel) |
| F11 | `OSError` ist gleichzeitig in `categories["file_system"]` UND `categories["network"]` gelistet (Zeilen 46-47); `categorize_exception()` iteriert die Dict-Reihenfolge und gibt den ersten Treffer zurück → `file_system` gewinnt für jeden bloßen `OSError` immer, auch bei genuinen Netzwerkfehlern, die nicht als spezifischere Klasse (`ConnectionError`/`TimeoutError`) auftreten | Niedrig (nur Recovery-Nachrichtentext betroffen, kein Crash) | Recovery-Architektur, außerhalb Integrations-Scope |
| F12 | `_extract_update_info()`/`_build_full_context()` loggen User-ID/Username/First-Name/Language-Code, Chat-ID/-Titel, Message-Text-Preview (100 Zeichen), Callback-Data sowie `frame_info` mit `locals_keys` (nur Variablennamen, keine Werte) über den Standard-Logger — keine gesonderte Redaktion/Kürzung für Produktionsbetrieb vs. Debug-Modus abgesehen vom Stack-Trace-Detailgrad | Niedrig (kein Secret-Leak — Passwörter/Tokens sind nicht Teil dieser Felder — aber personenbezogene Daten landen unredigiert in Logs) | Datenschutz, außerhalb Integrations-Scope |

---

## Fixes

**In dieser Phase wurden keine Code-Änderungen vorgenommen** — siehe
„Architekturentscheidung" für die Begründung. F1–F4 erfordern einen
eigenen, getesteten Implementierungsschritt (Instanz-Vereinheitlichung
berührt Initialisierungsreihenfolge in `bot.py` UND `rich_menu_handler.py`
sowie zahlreiche bestehende Tests, die `error_handler` gezielt mocken —
Risiko einer unbeabsichtigten Verhaltensänderung ohne begleitende
Testanpassung ist bei einer Prüfung ohne Testausführung zu hoch, siehe
Hard Rule 4/5/6). Vorgeschlagener Implementierungsplan für eine künftige,
eigene Phase (**nicht Teil von ARCH-026**):

```text
Finding F1/F2/F3
→ Datei: bot.py + handlers/menu/rich_menu_handler.py
→ Änderung: RichMenuHandler.initialize() akzeptiert einen optionalen
  bereits erstellten error_handler (z. B. Konstruktor-Parameter oder
  Setter vor initialize()); bot.py übergibt seine Instanz A anstelle
  eines zweiten create_enhanced_error_handler()-Aufrufs.
→ Begründung: eine einzige Instanz vereint Statistik/Recovery/Cleanup,
  behebt F1-F3 strukturell in einem Schritt.
→ Risiko: RichMenuHandler wird in mehreren Tests eigenständig (ohne
  bot.py) instanziiert und verlässt sich auf sein selbst erzeugtes
  self.error_handler - Konstruktor-/Initialize-Signaturänderung
  erfordert Sichtung aller tests/test_rich_menu_handler*.py.
→ Betroffene Tests: tests/test_rich_menu_handler.py und alle
  tests/test_*_error_handler.py, die handler.error_handler direkt mocken.
```

F5 (Decorator-Bug) wäre isoliert und risikoarm behebbar (zwei Zeilen,
`self.config.get(...)` → `getattr(self.config, ...)`), betrifft aber
ausschließlich toten Code ohne produktive Aufrufer — daher nicht
Bestandteil dieser Phase (Hard Rule 12: „Keine unrelated
Technical-Debt-Arbeit"; die Integrationsfrage dieses Audits ist die
Vollständigkeit der Integration, nicht das Debuggen unbenutzten Codes).

F6/F7/F8/F9/F10 sind bewusst nicht bereinigt (Hard Rule 7/8: lokale/tote
Handler-Referenzen nicht entfernen, ohne dass eine eigene Entscheidung
dafür vorliegt) — dokumentiert für eine mögliche künftige, gezielte
Aufräumphase.

F11/F12 sind laut Master-Prompt-Vorgabe („nur dokumentieren, wenn
außerhalb des unmittelbaren Integrations-Scope") reine
Dokumentationsfunde.

---

## Architekturentscheidung

```text
C — DUPLICATED / INCONSISTENT
```

Begründung: Es existiert eine funktionierende, PTB-konforme
Grundintegration (bot.py → Instanz A → `add_error_handler`), und der
überwiegende Teil der Handler-Landschaft ist tatsächlich mit einem
`EnhancedErrorHandler` verbunden (Instanz B, über
`RichMenuSystem.handle_callback()`s zentralen Catch-All UND ~40 direkte
`handle_callback_error`/`handle_command_error`-Aufrufe). Das System ist
also **nicht** grundlegend fehlerhaft integriert (keine Wahl von `E`).
Es ist aber auch nicht `A — FULLY INTEGRATED`, da zwei nie
synchronisierte Instanzen koexistieren, die zu einem echten
Monitoring-Blindspot (F1/F2/F3) und einer komplett unintegrierten P0-
Domäne (F4, Download) führen. `B — INCOMPLETE` würde F4 allein
zutreffend beschreiben, erklärt aber nicht die Kerninkonsistenz F1-F3.
`D — PARTIALLY DEAD` beschreibt zutreffend die Decorators (F5) und
einige Beispiele, ist aber keine Aussage über das Gesamtsystem. Die
Instanz-Duplizierung (F1) ist die Wurzelursache mehrerer anderer Funde
(F2, F3) und damit der bestimmende Architekturbefund → **C**.

---

## Final Status

- Wo wird der Error Handler erzeugt? → Zweimal: `bot.py:100` (Instanz A) und `rich_menu_handler.py:187` (Instanz B).
- Wo wird er registriert? → Nur Instanz A, via `application.add_error_handler()`.
- Welche Telegram-Fehler landen automatisch dort? → Nur Exceptions, die weder von lokalen `try/except`-Blöcken noch von `RichMenuSystem.handle_callback()`s zentralem Catch-All (Instanz B) abgefangen werden — in der Praxis selten (v. a. Bugs innerhalb der Routing-Logik selbst oder in gänzlich unbewachten Command-Handlern).
- Welche Komponenten verwenden ihn direkt? → 8 Handler-Klassen (Navidrome, Duplicate, Status, Backup, Logger, UserMgmt, TestMenu, RichMenuSystem selbst) + `greeting.py`/`help.py`/`actions/usermgmt.py`, alle gegen Instanz B.
- Welche Komponenten erhalten ihn injiziert (aber nutzen ihn nicht)? → `ReprocessingMenuHandler`, `LibraryDoctorHandler`, `LibraryHealthReviewHandler`, `RepairMusicBotHandler`.
- Gibt es mehrere Instanzen? → Ja, zwei (A, B).
- Ist diese Mehrfachinstanzierung gerechtfertigt? → Nein, nicht dokumentiert — als `ARCHITECTURAL DUPLICATION` bewertet.
- Welche Factory Functions sind produktiv? → Nur `create_enhanced_error_handler()` (einzige verbleibende nach dem 2026-09-03-Cleanup).
- Welche Funktionen am Dateiende sind nur Beispiele? → Der gesamte Abschnitt „VERWENDUNGSBEISPIELE UND DOKUMENTATION" (String-Literal, keine Funktionen) — 3 von 5 Beispielen (Decorators, direkter `handle_exception()`, direkter `debug_tracker`-Zugriff) ohne produktive Entsprechung.
- Welche Decorators werden produktiv verwendet? → Keiner.
- Gibt es unhandled error paths? → Der Download-Hintergrund-Task (F4) — geloggt, aber ohne zentrale Behandlung.
- Gibt es verschluckte Exceptions? → Nur bewusste, angemessene Fallback-Stille (`_recover_telegram_error`s innere `except:`-Blöcke).
- Gibt es doppelte Error Handling Paths? → Ja (F1), plus redundante (aber harmlose) `start_session()`/`end_session()`-Doppelaufrufe (F8).
- Ist `RichMenuSystem` korrekt integriert? → Ja, in sich vollständig (gegen Instanz B), aber getrennt von `bot.py`s Instanz A.
- Ist `RichMenuHandler` korrekt integriert? → Ja, analog zu `RichMenuSystem`.
- Ist `bot.py` korrekt integriert? → Ja, PTB-Signatur/Registrierung korrekt — aber isoliert von Instanz B.
- Ist die gesamte Architektur konsistent? → Nein — siehe Architekturentscheidung `C`.
- Sind konkrete Lücken behoben, falls vorhanden? → Nein, bewusst zurückgestellt (siehe „Fixes") — Implementierungsplan dokumentiert für eine künftige, eigene Phase.
- Ist die Dokumentation aktuell? → Nach diesem Dokument ja; `docs/FINDINGS_INDEX.md` wurde um F1-F12 ergänzt.

**ARCH-026 STATUS: AUDIT COMPLETE — Findings dokumentiert, keine
Code-Änderung in dieser Phase, Fix-Plan für F1-F4 vorgeschlagen und
zurückgestellt.**
