# MusicBot ARCH-028 — Error Handler Closure

> **Status: COMPLETE. Vollständige Testsuite vom Nutzer ausgeführt:
> 3490 passed, 1 skipped, 11 subtests passed, 0 failed (280,76 s) —
> 0 Regressionen.**

Schließt die verbleibenden, in ARCH-026 dokumentierten und in ARCH-027
bewusst zurückgestellten Integrationslücken F4/F5/F6 ab und verifiziert
anschließend gezielt den `FamilyChallengeScheduler` — dabei wurde ein
zusätzlicher, bisher nicht dokumentierter Integrationsfund samt einem
konkreten Live-Bug entdeckt und ebenfalls behoben.

Reihenfolge exakt wie beauftragt: **F6 → F4 → F5 → Scheduler-Verifikation
→ Scheduler-Fix (Fall B) → Tests → Dokumentation.**

---

## 1. F6 — 4 Handler mit ungenutzter Injection

**Betroffene Handler:** `ReprocessingMenuHandler`, `LibraryDoctorHandler`,
`LibraryHealthReviewHandler`, `RepairMusicBotHandler` — alle erhalten den
zentralen `EnhancedErrorHandler` seit ARCH-025/027 injiziert
(`self.<handler>.error_handler = self.error_handler` in
`RichMenuHandler.initialize()`), riefen ihn aber nie auf.

**Tatsächliche Exception-Pfade** (alle als Hintergrund-Task nach dem
etablierten `asyncio.create_task()`-Muster, siehe
`handlers/menu/actions/download.py`):

| Datei | Methode | Bisher | Jetzt |
|---|---|---|---|
| `reprocessing_menu_handler.py` | `_run_and_report()` | nur `logger.error()` | zusätzlich `await self.error_handler.handle_exception(e, context={...})` |
| `library_doctor_handler.py` | `_run_scan_and_report()` | nur `logger.error()` | dito |
| `library_doctor_handler.py` | `_run_repair_and_report()` | nur `logger.error()` | dito |
| `repair_musicbot_handler.py` | `_run_analyze_and_report()` | nur `logger.error()` (generischer `except Exception`, `HealthScanFailedError` bleibt lokal) | dito |
| `repair_musicbot_handler.py` | `_run_execute_and_report()` | nur `logger.error()` (generischer `except Exception`, `RepairAlreadyRunningError` bleibt lokal) | dito |
| `library_health_review_handler.py` | `_load_registry()` (synchron!) | nur `logger.error()` | `asyncio.create_task(self.error_handler.handle_exception(...))` (Fire-and-Forget, da die Methode selbst nicht async ist und 11 Aufrufer hat) |

**Warum `handle_exception()` statt `handle_callback_error()`:** keiner
dieser Pfade hat ein `update`/`context`-Objekt zur Verfügung (reine
Hintergrund-Tasks bzw. ein synchroner Helper) — `handle_exception(e,
context=...)` ist der einzige Entry-Point, der ohne diese Parameter
funktioniert. Mit `update=None` löst `handle_exception()` intern weder
Recovery noch Nutzerbenachrichtigung aus (siehe
`enhanced_error_handler.py::handle_exception()`, Zeilen 432-442) — die
bereits vorhandene lokale Nutzerbenachrichtigung (`message.edit_text(...)`)
bleibt unverändert die einzige, keine Doppel-Benachrichtigung.

**Bewusst NICHT zentral gemeldet:** `HealthScanFailedError` und
`RepairAlreadyRunningError` (beide in `repair_musicbot_handler.py`) sowie
`FindingsRegistryError` (in `library_health_review_handler.py`) — das
sind bereits vollständig mit eigener, spezifischer Nutzer-Nachricht
behandelte, erwartete Betriebszustände (analog zu `StatistikHandler`s
bereits in ARCH-026 dokumentiertem, bewussten Verzicht), keine
"unerwarteten" Fehler im Sinne des zentralen Monitorings — keine
Doppel-Registrierung, kein Vermischen von Bug-Signal und erwarteter
Betriebsmeldung.

**Tests:** 12 neue Tests (je 2 pro Handler-Methode: „wird gemeldet"/„bleibt
lokal ohne Handler" bzw. „erwarteter Fehler bleibt lokal") in
`tests/test_reprocessing_menu_handler.py`,
`tests/test_library_doctor_handler.py`,
`tests/test_library_health_review_handler.py`,
`tests/test_repair_musicbot_handler.py`. Isoliert grün: 125 passed.

---

## 2. F4 — Download-Pipeline ohne Error-Handler-Integration

**Befund (ARCH-026):** `klassen/download_handler.py` (1162 Zeilen) hatte
0 Referenzen auf `EnhancedErrorHandler`. Der Download läuft als
`asyncio.create_task()`-Hintergrund-Task
(`handlers/menu/actions/download.py::process_url()`); dessen einziges
Sicherheitsnetz für wirklich unerwartete, durchrutschende Exceptions
(`_log_background_download_task_exception()`, per `add_done_callback()`)
meldete ausschließlich lokal.

**Implementierung** (minimal-invasiv, 3 Dateien):

1. `klassen/download_handler.py`: `DownloadHandler.__init__()` erhält
   einen neuen optionalen Parameter `error_handler: Optional["EnhancedErrorHandler"] = None`.
   Zusätzlich ein **Klassenattribut** `error_handler = None` (nicht nur
   eine Instanzzuweisung in `__init__`) — notwendig, weil 10 bestehende
   Testdateien `object.__new__(DownloadHandler)` verwenden, um den
   schweren Konstruktor zu umgehen (etabliertes Testmuster dieser
   Session); diese Instanzen erhalten `error_handler` nie über
   `__init__()`, brechen aber dank des Klassenattribut-Fallbacks nicht
   mit `AttributeError`, falls Code `self.error_handler` liest.
2. `handlers/menu/actions/download.py`:
   - `create_download_handler(...)` erhält `error_handler=None` und
     reicht ihn an `DownloadHandler(...)` durch.
   - `_log_background_download_task_exception(task, logger, error_handler=None)`
     meldet bei einer durchgerutschten Exception zusätzlich zum
     bestehenden `logger.error(...)` per `asyncio.create_task(error_handler.handle_exception(...))`
     (Fire-and-Forget, da `add_done_callback()` ein synchroner Callback
     ist — analog zum in F6 etablierten Muster für
     `_load_registry()`). `handle_youtube_links()`s eigene, bereits
     bestehende, breite Fehlerbehandlung (meldet dem Nutzer per
     Telegram) bleibt vollständig unverändert — keine
     Doppel-Registrierung.
   - `process_url()` selbst brauchte **keine** Signaturänderung: der
     `error_handler` wird direkt vom bereits konstruierten `handler`
     (`DownloadHandler`-Instanz) gelesen
     (`getattr(handler, "error_handler", None)`), da dieser die zentrale
     Instanz bereits über `create_download_handler()` erhalten hat.
3. `handlers/menu/rich_menu_handler.py`: `_create_download_handler()`
   übergibt `error_handler=self.error_handler` (die zentrale, seit
   ARCH-027 geteilte Instanz).

**Keine zweite Instanz, keine Architekturänderung an der Download-Pipeline
selbst** — nur die bereits vorhandene, mehrfach dokumentierte
Design-Entscheidung (Hintergrund-Task wegen fehlendem
`concurrent_updates=True`, siehe `process_url()`-Docstring) bleibt
unverändert; es wird lediglich ein zusätzlicher Meldepfad für den
Sicherheitsnetz-Fall ergänzt.

**Tests:** 8 neue Tests in `tests/test_menu_actions_download.py`
(`create_download_handler`-Injection, `_log_background_download_task_exception`
mit/ohne `error_handler`, Cancelled-Task-Fall) + 1 neuer Test in
`tests/test_rich_menu_handler.py::TestCreateDownloadHandler`. Alle 10
bestehenden `object.__new__(DownloadHandler)`-Testdateien (92 Tests)
unverändert grün. Isoliert: 63 passed.

---

## 3. F5 — Decorator-Bug

**Befund (ARCH-026):** `handle_async_exceptions()`/`handle_sync_exceptions()`
haben 0 produktive Verwendungen (repoweit + Tests, unverändert
bestätigt). Bei tatsächlicher Auslösung hätten beide
`self.config.get("SUPPRESS_HANDLED_EXCEPTIONS", False)` aufgerufen —
`config.Config` (reine Attribut-Klasse, kein `__getattr__`, kein
`.get()`) hätte einen `AttributeError` geworfen, der die eigentliche
Exception maskiert hätte.

**Feststellung „aktiv/relevant" vs. „toter Code":** die Decorators sind
zwar produktiv ungenutzt, aber weiterhin **architektonisch relevant** —
sie sind Teil der öffentlichen, dokumentierten API der Klasse
(Verwendungsbeispiel 2 im Modul-Docstring) und wurden in ARCH-026/027
bereits explizit als bewusst beizubehaltende „LEGACY API" eingestuft
(Hard Rule: keine funktionierenden, dokumentierten öffentlichen
Schnittstellen ohne zwingenden Grund entfernen). Ein bekannter, latenter
Bug in weiterhin unterstütztem, dokumentiertem Code wird daher **minimal
korrekt behoben**, nicht als toter Code ignoriert.

**Fix 1 (der dokumentierte Bug):** `self.config.get(...)` →
`getattr(self.config, "SUPPRESS_HANDLED_EXCEPTIONS", False)` an beiden
Stellen (`handle_async_exceptions()` und `handle_sync_exceptions()`),
konsistent mit jedem anderen Config-Zugriff in derselben Datei
(`self.debug_mode`, `self.max_recovery_attempts` etc., alle bereits
`getattr(...)`).

**Fix 2 (beim Testen entdeckter zweiter, verwandter Bug):**
`handle_sync_exceptions()` rief `asyncio.create_task(...)` unbedingt
auf — das erfordert einen bereits laufenden Event-Loop
(`RuntimeError: no running event loop` sonst). Da dieser Decorator
gerade **synchronen** Code dekoriert, der nicht zwingend aus einem
async-Kontext heraus aufgerufen wird, ist das ein echter,
reproduzierbarer zweiter Fehlerpfad — exakt die im ARCH-026-Audit
bereits aufgeworfene, aber unbeantwortete Frage („Kann
`asyncio.create_task()` für Sync-Fehler problematisch sein?").
Reproduziert durch einen direkten Testaufruf ohne umgebenden
`asyncio.run()`. Fix: Coroutine einmalig erzeugen, dann per
`asyncio.get_running_loop()`-Prüfung entweder einplanen
(`asyncio.create_task()`, bestehendes Verhalten bei vorhandenem Loop)
oder synchron zu Ende ausführen (`asyncio.run()`, neuer Fallback ohne
Loop) — keine verworfene, nie awaitete Coroutine (vermeidet die
sonst auftretende „coroutine was never awaited"-Warnung).

**Tests:** 4 neue Tests in `tests/test_enhanced_error_handler.py`
(`TestDecoratorConfigAccessBugFix`): async/sync × „wirft Original-Exception
weiter"/„unterdrückt korrekt bei `SUPPRESS_HANDLED_EXCEPTIONS=True`".
Mit `-W error::RuntimeWarning` verifiziert, dass keine „coroutine was
never awaited"-Warnung mehr auftritt. Isoliert: 26 passed (gesamte
Datei).

---

## 4. Zwischenverifikation — FamilyChallengeScheduler

**Methode:** statische Code-Pfad-Verifikation (deterministisch, siehe
Begründung unten) statt eines Live-Betriebs des Bots — der exakte
Datenfluss wurde bis auf Zeilenebene nachvollzogen, mit demselben
Evidenz-Standard wie in ARCH-026/027 ("Beweise konkret... nicht nur
vermuten").

```text
FamilyChallengeScheduler._run_daily_loop()
        ↓ except Exception as e:
self.logger.error(...)   ← EINZIGER Effekt (vor dieser Phase)
        ↓
KEIN Aufruf von self.error_handler.* — self.error_handler existierte
als Attribut nicht einmal (kein error_handler-Parameter im Konstruktor)
        ↓
bot.py: FamilyChallengeScheduler(self.application.bot,
        family_service=..., challenge_service=...) — KEIN error_handler-
        Argument übergeben, obwohl self.error_handler (die seit ARCH-027
        geteilte, zentrale Instanz) zu diesem Zeitpunkt bereits existiert
        ↓
ERGEBNIS: strukturell unmöglich, dass eine Exception aus
_run_daily_loop()/generate_and_broadcast_all_families()/_broadcast()
jemals EnhancedErrorHandler erreicht — weder Instanz A/B (ARCH-026) noch
die seit ARCH-027 vereinheitlichte Instanz.
```

**Warum statische Verifikation statt Live-Betrieb genügt:** die Frage
„kann Codepfad X jemals Objekt Y erreichen" ist durch vollständige
Aufzählung aller Referenzen und Konstruktionsaufrufe (`grep -rn
"error_handler" handlers/family_challenge_scheduler.py` → 0 Treffer vor
dem Fix; `grep -n "FamilyChallengeScheduler(" bot.py` → exakt 1
Konstruktionsstelle, ohne `error_handler`-Argument) mit derselben
Sicherheit beantwortbar wie durch einen tatsächlichen Lauf — ein Live-Lauf
hätte keine zusätzliche Evidenz geliefert, aber einen produktiven
Telegram-Bot-Prozess mit echten Zugangsdaten gegen die reale Telegram-API
gestartet (eine deutlich schwerere, in ihrer Tragweite über eine reine
Code-Verifikation hinausgehende Aktion).

**Ergebnis: FALL B** — die Exception erscheint weiterhin **nicht** im
zentralen Error Handler. Der Scheduler besitzt eine eigenständige,
bisher unbehandelte Integrationslücke (nicht durch F4/F5/F6 indirekt
mitbehoben, da strukturell komplett getrennt).

**Zusätzlicher, konkreter Live-Bug bei der Verifikation entdeckt:**
`_seconds_until_next_run()` griff auf `Config.FAMILY_CHALLENGE_TIME`
über die **Klasse** `Config` zu (nicht über eine Instanz).
`config.py::Config.FAMILY_CHALLENGE_TIME` ist jedoch eine `@property`
der **Instanz** — ein Zugriff über die bloße Klasse liefert das
`property`-Descriptor-Objekt selbst zurück, nicht den berechneten
String. `.split(":")` darauf wirft exakt
`'property' object has no attribute 'split'` — der vom Nutzer
gemeldete Live-Fehler, jetzt durch Code-Lesen ursächlich erklärt
(bestätigt auch durch `config.py:269-277`).

---

## 5. Scheduler-Fix (Fall B)

Gemäß Master-Prompt-Vorgabe für Fall B umgesetzt:

1. **`FamilyChallengeScheduler.__init__()`** erhält zwei neue optionale
   Parameter:
   - `config: Optional[Config] = None` — fällt ohne Injection auf die
     bereits existierende Singleton-Instanz `get_config()` zurück
     (keine neue `Config()`-Instanz, keine neue Architektur).
   - `error_handler: Optional["EnhancedErrorHandler"] = None`.
2. **`bot.py`** übergibt beim Konstruieren seine bereits existierende
   `self.config`- und `self.error_handler`-Instanz (dieselbe, seit
   ARCH-027 vereinheitlichte zentrale Instanz) — **keine neue
   `EnhancedErrorHandler`-Instanz erzeugt**.
3. **Config-Bug behoben:** `Config.FAMILY_CHALLENGE_TIME` →
   `self.config.FAMILY_CHALLENGE_TIME` (2 Stellen: die eigentliche
   Berechnung in `_seconds_until_next_run()` und eine Log-Zeile in
   `_run_daily_loop()`).
4. **Alle 3 bestehenden `except Exception`-Blöcke** melden zusätzlich
   an `self.error_handler.handle_exception(e, context={...})` — direktes
   `await` (kein Fire-and-Forget nötig, da alle drei Methoden bereits
   async sind und ausschließlich innerhalb des von `start_polling()`
   erzeugten, garantiert laufenden Hintergrund-Tasks ausgeführt werden):
   - `_run_daily_loop()`s eigener Catch-All (`operation:
     "run_daily_loop"`).
   - `generate_and_broadcast_all_families()`s Pro-Familie-Catch
     (`operation: "generate_and_broadcast_all_families"`,
     `family_id`) — **Fehlerisolation zwischen Familien bleibt
     unverändert** (die `for`-Schleife läuft nach dem Logging/der
     Meldung unverändert weiter).
   - `_broadcast()`s Pro-Empfänger-Catch (`operation: "broadcast"`,
     `family_id`, `telegram_id`) — **Fehlerisolation zwischen
     Broadcast-Empfängern bleibt unverändert**.
5. **Keine künstlichen Telegram-Updates:** alle drei Meldungen nutzen
   `handle_exception()` (kein `update`, kein `context`) statt
   `handle_callback_error()`/`handle_command_error()` — exakt die
   tatsächliche, für Background-Fehler vorgesehene API von
   `EnhancedErrorHandler`.

**„Message is not modified" (Abschnitt „MESSAGE IS NOT MODIFIED" des
Master-Prompts):** nicht berührt. Der Scheduler sendet ausschließlich
neue Nachrichten (`bot.send_message(...)`, kein `edit_message_text(...)`)
— dieser Fall tritt hier gar nicht auf. Die bestehende idempotente
Behandlung in `EnhancedErrorHandler._recover_telegram_error()`
(`"message is not modified" in str(exception).lower()` → stille
Behandlung ohne Nutzerbenachrichtigung) wurde in keiner Phase dieses
Auftrags verändert.

**Tests:** 2 bestehende Tests korrigiert (patchten vorher
`Config.FAMILY_CHALLENGE_TIME` auf Klassenebene — funktional weiterhin
richtig, aber jetzt über eine injizierte `FakeConfig`-Instanz statt
Klassen-Patch, passend zum neuen `self.config`-Zugriff). 6 neue Tests:
2 Config-Regressionstests (inkl. eines Tests gegen die **echte**
`config.Config`-Klasse, nicht nur `FakeConfig`, um den exakten
Live-Bug-Pfad abzudecken), 4 Error-Handler-Integrationstests (Familie/
Broadcast/Daily-Loop meldet zentral; Rückwärtskompatibilität ohne
`error_handler`). Isoliert: 16 passed.

---

## 6. Feature Coverage Matrix (Delta zu ARCH-026/027)

| Feature | Vorher | Nachher |
|---|---|---|
| Download-Pipeline (P0) | Keine Integration (F4) | `DownloadHandler` + Hintergrund-Task-Sicherheitsnetz melden an die zentrale Instanz |
| Reprocessing/Doctor/Review/Repair (4 Handler, F6) | Injection vorhanden, ungenutzt | Alle generischen `except Exception`-Pfade melden zentral |
| Decorators (F5) | 0 Verwendung + 2 latente Bugs | 0 Verwendung (unverändert, LEGACY API), beide Bugs behoben |
| `FamilyChallengeScheduler` | Keine Integration, kein `config`/`error_handler` injizierbar | `config`+`error_handler` injizierbar, alle 3 Exception-Pfade melden zentral |

---

## 7. Static Audit

- **Keine zweite `EnhancedErrorHandler`-Instanz eingeführt:** alle neuen
  `error_handler`-Parameter sind `Optional[...] = None` mit Fallback
  „kein zentrales Monitoring" (nicht „neue Instanz erzeugen") — verifiziert
  per `grep -rn "EnhancedErrorHandler(\|create_enhanced_error_handler("`
  (unverändert nur 2 Erzeugungsstellen: `bot.py` Produktion, `rich_menu_handler.py`
  Standalone-Fallback, beide bereits aus ARCH-027 bekannt).
- **Keine Doppel-Registrierung:** an jeder der 4+6 geänderten
  Fundstellen wurde explizit geprüft, ob bereits eine speziellere,
  erwartete Exception-Klasse mit eigener Nutzerbehandlung existiert
  (`HealthScanFailedError`, `RepairAlreadyRunningError`,
  `FindingsRegistryError`) — diese bleiben bewusst lokal.
- **Keine künstlichen Telegram-Updates:** ausschließlich
  `handle_exception(e, context=...)` verwendet, nie
  `handle_callback_error()`/`handle_command_error()` mit
  selbstgebauten `Update`-Objekten.
- **`ast.parse()`** aller 8 geänderten Python-Dateien fehlerfrei.
- **`object.__new__(DownloadHandler)`-Bypass-Muster** (10 Testdateien)
  unverändert lauffähig dank Klassenattribut-Fallback.
- **Keine neuen zirkulären Imports:** `TYPE_CHECKING`-Imports in
  `klassen/download_handler.py` und `handlers/family_challenge_scheduler.py`
  folgen exakt demselben bereits etablierten Muster wie die 11 anderen
  Handler mit `EnhancedErrorHandler`-Type-Hint.

---

## 8. Geänderte Dateien

**Code:**
- `handlers/menu/reprocessing_menu_handler.py` (F6)
- `handlers/library_doctor_handler.py` (F6)
- `handlers/library_health_review_handler.py` (F6)
- `handlers/repair_musicbot_handler.py` (F6)
- `klassen/download_handler.py` (F4)
- `handlers/menu/actions/download.py` (F4)
- `handlers/menu/rich_menu_handler.py` (F4)
- `handlers/enhanced_error_handler.py` (F5)
- `handlers/family_challenge_scheduler.py` (Scheduler-Fix)
- `bot.py` (Scheduler-Fix: `config`+`error_handler`-Injection)

**Tests:**
- `tests/test_reprocessing_menu_handler.py` (+2)
- `tests/test_library_doctor_handler.py` (+6, neue `TestRunRepairAndReport`-Klasse)
- `tests/test_library_health_review_handler.py` (+2)
- `tests/test_repair_musicbot_handler.py` (+4)
- `tests/test_menu_actions_download.py` (+8)
- `tests/test_rich_menu_handler.py` (+1)
- `tests/test_enhanced_error_handler.py` (+4, neue `TestDecoratorConfigAccessBugFix`-Klasse)
- `tests/test_family_challenge_scheduler.py` (2 korrigiert, +6 neu)

**Dokumentation:**
- `docs/MusicBot_ARCH-028_Error_Handler_Closure.md` (neu, dieses Dokument)
- `docs/FINDINGS_INDEX.md` (F4/F5/F6 → CLOSED, neuer Scheduler-Fund → CLOSED)

---

## 9. Test Status

Nach jedem Punkt gezielt getestet (grün): F6 125 passed, F4 63 passed
(inkl. 92 unveränderter Bypass-Tests), F5 26 passed, Scheduler 16
passed.

Anschließend thematischer Sweep (`pytest -q -k "download or error_handler
or menu or family or reprocessing or library_doctor or
library_health_review or repair_musicbot or bot"`): **1323 passed, 0
failed**.

**Vollständige Testsuite vom Nutzer ausgeführt (2026-09-13):**
**3490 passed, 1 skipped, 11 subtests passed, 0 failed** (280,76 s).
Referenz-Baseline vor dieser Phase: 3460 passed, 1 skipped, 11 subtests
passed, 0 failed (Stand ARCH-027, PR #209). Netto-Effekt: **+30** neue
Tests, 0 entfernte Tests, 0 Regressionen — 1 skipped und 11 subtests
unverändert, exakt wie für eine rein additive, verhaltenserhaltende
Änderung erwartet.

---

## 10. Definition of Done — Abgleich

- [x] F6 vollständig implementiert + isoliert getestet
- [x] F4 vollständig implementiert + isoliert getestet
- [x] F5 korrekt behoben (2 Bugs, nicht nur der dokumentierte) + getestet
- [x] Scheduler-Verifikation durchgeführt (statisch, deterministisch)
- [x] Fall B bestätigt, Scheduler-Fix umgesetzt (Config-Injection,
      Error-Handler-Injection, Config-Bug behoben)
- [x] Fehlerisolation (Familie/Broadcast-Empfänger) unverändert erhalten
- [x] Keine künstlichen Telegram-Updates für Background-Fehler
- [x] "Message is not modified" nicht angetastet
- [x] Gezielte Tests nach jedem Punkt grün
- [x] Thematischer Sweep grün (1323 passed)
- [x] Vollständige Testsuite (Nutzer): 3490 passed, 1 skipped, 11 subtests passed, 0 failed
- [x] Dokumentation aktualisiert (dieses Dokument + `docs/FINDINGS_INDEX.md`)
- [x] Keine anderen Architekturaufgaben in diesen Abschluss aufgenommen
      (F7-F12 aus ARCH-026 bewusst unangetastet, kein ARCH-029 eröffnet)
- [x] Isolierter Branch → Commit → Push → PR → CI grün → Merge
