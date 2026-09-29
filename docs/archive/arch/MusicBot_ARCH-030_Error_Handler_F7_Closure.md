# MusicBot ARCH-030 — Error Handler F7 Closure

> **Status: COMPLETE.** Gezielte Tests grün (90 passed), thematischer
> Sweep grün (1076 passed, 3001 deselected). Vollständige Testsuite vom
> Nutzer ausgeführt: **4076 passed, 1 skipped, 11 subtests passed**
> (252,82 s) — 0 Regressionen.

Schließt das letzte verbleibende, in ARCH-026 dokumentierte und in
ARCH-027/028/029 bewusst zurückgestellte Finding F7 ab. Mit dieser Phase
sind **alle 12 Findings (F1–F12) aus dem ARCH-026-Audit geschlossen**.

---

## 1. Ausgangslage

`docs/MusicBot_ARCH-026_Error_Handler_Integration_Audit.md`, F7:

> `FamilyChatHandler`/`FamilyChallengeHandler`/`BotRestartHandler` haben
> weder `error_handler`-Injection noch einen Docstring-/Findings-Hinweis
> auf einen bewussten Verzicht (anders als `StatistikHandler`/
> `FamilyStatsHandler`). Kein Coverage-Loch (zentraler Catch-All greift),
> aber inkonsistent zur sonstigen Dokumentationspraxis.

Ursprünglich als reine Dokumentationsinkonsistenz eingestuft (P3, kein
funktionaler Fehler).

## 2. Verifikation gegen aktuellen Code

Repoweiter Check aller drei Handler bestätigte den ARCH-026-Befund
(0 `error_handler`-Referenzen in allen drei Dateien), deckte aber einen
**zusätzlichen, bisher unentdeckten echten Monitoring-Gap** auf:

| Handler | Lokale `except`-Blöcke | Erreichbar über |
|---|---|---|
| `BotRestartHandler` | 0 | ausschließlich `restart:`-Callback-Präfix → `RichMenuSystem.handle_callback()`-Catch-All |
| `FamilyChallengeHandler` | 0 (`process_pending_answer()` propagiert ungefangen) | Callback-Pfade → Catch-All; `process_pending_answer()` → globaler PTB-Fallback |
| `FamilyChatHandler` | **1** (`process_pending_message()`, Pro-Empfänger-Broadcast-Schleife) | `process_pending_message()` wird von `RichMenuHandler.handle_text_message()` aufgerufen |

**Kernfund:** `RichMenuHandler.handle_text_message()` hat — anders als
`RichMenuSystem.handle_callback()` — **keinen** eigenen zentralen
`try/except`-Catch-All. Der bestehende `except Exception` in
`process_pending_message()`s Broadcast-Schleife loggt einen
fehlgeschlagenen Zustellversuch nur lokal (`self.logger.error(...)`) und
lässt die Schleife bewusst weiterlaufen (Fehlerisolation zwischen
Empfängern) — dieser Fehler erreichte dadurch **nie** eine
`EnhancedErrorHandler`-Instanz, weder über eine direkte Injection (gab es
nicht) noch über den globalen PTB-Fallback (die Exception wird ja lokal
abgefangen, nicht weitergeworfen). Strukturell identisch zu dem in
ARCH-028 bereits behobenen `FamilyChallengeScheduler._broadcast()`-Fall.

`FamilyChallengeHandler` und `BotRestartHandler` haben dagegen **keinen**
einzigen lokalen `except`-Block — jede dort auftretende Exception
propagiert entweder zum `RichMenuSystem.handle_callback()`-Catch-All
(Callback-Pfade) oder zum globalen PTB-Fallback (`process_pending_answer()`,
kein lokaler `try/except`). Für diese beiden ist eine `error_handler`-
Injection tatsächlich funktionslos (keine lokal verschluckte Exception,
die sie melden könnte) — der richtige Fix ist hier **Dokumentation**,
nicht Code.

## 3. Fix

### `handlers/family_chat_handler.py`

- `TYPE_CHECKING`-Import von `EnhancedErrorHandler`, `self.error_handler:
  "Optional[EnhancedErrorHandler]" = None` in `__init__` — exakt dasselbe
  Muster wie `NavidromeMenuHandler`.
- `process_pending_message()`s Broadcast-`except`-Block ruft zusätzlich
  `await self.error_handler.handle_exception(e, context={"module":
  "FamilyChatHandler", "operation": "broadcast_message", "recipient_id":
  ...})` auf, wenn injiziert — `handle_exception()` statt
  `handle_callback_error()`, da für den jeweiligen Empfänger kein
  `update`/`telegram_context` existiert (nur für den Absender). Analog
  `FamilyChallengeScheduler._broadcast()` (ARCH-028). Fehlerisolation
  zwischen Empfängern bleibt unverändert (Schleife läuft weiter).

### `handlers/menu/rich_menu_handler.py`

- `RichMenuHandler.initialize()`: nach `self.family_chat_handler =
  FamilyChatHandler()` zusätzlich `self.family_chat_handler.error_handler
  = self.error_handler` — dieselbe post-Konstruktions-Zuweisung wie bei
  `NavidromeMenuHandler` und den übrigen ~11 Sub-Handlern, propagiert die
  seit ARCH-027 geteilte zentrale Instanz.

### `handlers/family_challenge_handler.py` / `handlers/admin/bot_restart_handler.py`

- Keine Codeänderung. Jeweils ein Absatz im Modul-Docstring ergänzt, der
  den bewussten Verzicht auf `error_handler`-Injection begründet (analog
  `handlers/mugge_statistik_handler.py`s bereits dokumentiertem Muster):
  0 lokale `except`-Blöcke, volle Coverage bereits über zentralen
  Catch-All bzw. globalen PTB-Fallback.

## 4. Betroffene Dateien

**Code:**
- `handlers/family_chat_handler.py`
- `handlers/menu/rich_menu_handler.py`
- `handlers/family_challenge_handler.py` (nur Docstring)
- `handlers/admin/bot_restart_handler.py` (nur Docstring)

**Tests:**
- `tests/test_family_chat_handler.py` (+3): fehlgeschlagene Zustellung
  ohne injizierten `error_handler` crasht nicht (Rückwärtskompatibilität);
  fehlgeschlagene Zustellung meldet an einen injizierten `error_handler`
  mit korrektem Kontext (`module`/`operation`/`recipient_id`); erfolgreiche
  Zustellung ruft `error_handler` nicht auf.

**Dokumentation:**
- `docs/MusicBot_ARCH-030_Error_Handler_F7_Closure.md` (neu, dieses
  Dokument).
- `docs/FINDINGS_INDEX.md` (F7 → CLOSED).

## 5. Tests

```text
tests/test_family_chat_handler.py
tests/test_family_challenge_handler.py
tests/test_bot_restart_handler.py
tests/test_rich_menu_handler.py                          90 passed

Thematischer Sweep
  (-k "family or bot_restart or rich_menu or error_handler or menu")
                                            1076 passed, 3001 deselected
```

0 failed in allen Läufen durch den Implementierungsprozess (Schritte 1–3
nach CLAUDE.md §8.A). Die vollständige Testsuite (Schritt 4) hat der
Nutzer anschließend selbst ausgeführt:

```text
4076 passed, 1 skipped, 11 subtests passed, 0 failed (252,82 s)
```

+3 gegenüber der ARCH-029-Zahl (4073) — exakt deckungsgleich mit den 3
neuen Tests in `tests/test_family_chat_handler.py`
(`test_broadcast_failure_without_error_handler_does_not_crash`,
`test_broadcast_failure_reports_to_injected_error_handler`,
`test_successful_broadcast_does_not_call_error_handler`). 0
Regressionen.

## 6. Architekturentscheidung

Keine Änderung an der ARCH-027-Single-Shared-Instance-Architektur oder
an ARCH-028/029. `FamilyChatHandler` reiht sich mit seiner Injection in
das bereits etablierte Muster der ~12 anderen Sub-Handler ein (post-
Konstruktions-Attributzuweisung durch `RichMenuHandler.initialize()`).
Keine neue `EnhancedErrorHandler`-Instanz, kein neuer globaler Singleton,
keine neue Debug-API.

## 7. Finaler Status

```text
======================================================================
ARCH-030 — ERROR HANDLER F7 CLOSURE
======================================================================

F7  FamilyChatHandler/FamilyChallengeHandler/          CLOSED — FIXED
    BotRestartHandler undokumentierte Nicht-Integration
    (+ 1 echter Monitoring-Gap in FamilyChatHandler
    gefunden und behoben)

Files changed:
  handlers/family_chat_handler.py
  handlers/menu/rich_menu_handler.py
  handlers/family_challenge_handler.py (Docstring)
  handlers/admin/bot_restart_handler.py (Docstring)
  tests/test_family_chat_handler.py
  docs/MusicBot_ARCH-030_Error_Handler_F7_Closure.md (neu)
  docs/FINDINGS_INDEX.md
  docs/MusicBot_ENGINEERING_BASELINE_v10.md

Tests:
  Gezielt (4 Dateien)                                  90 passed
  Thematischer Sweep                       1076 passed, 3001 deselected

Full pytest (Nutzer, 2026-09-14):
  4076 passed, 1 skipped, 11 subtests passed, 0 failed (252,82 s)

Regressionen: 0 (in allen Läufen, inkl. Vollsuite)

Architecture:
  ARCH-027 shared ErrorHandler instance preserved (unveraendert)
  ARCH-028/029 closure preserved (unveraendert)

Result:
  Alle 12 Findings (F1-F12) aus dem ARCH-026-Audit sind CLOSED.
  Der ARCH-026/027/028/029/030-Error-Handler-Auftragsblock ist
  vollstaendig abgeschlossen.

Documentation:
  ARCH-030 created
  FINDINGS_INDEX updated (F7 CLOSED)
  ENGINEERING_BASELINE_v10 (DRAFT) aktualisiert (ARCH Status, Recent
  Major Changes, Testzahlen)
======================================================================
```

Git: Branch `arch-030/error-handler-f7-closure` erstellt, committet,
gepusht, PR erstellt und nach Nutzerfreigabe gemergt (siehe PR-Link in
der Session).

Git: keine Aktionen in dieser Phase — Arbeitsstand liegt im Working
Tree, Commit/Push/Merge folgt auf explizite Nutzeranweisung (wie bei
ARCH-029).
