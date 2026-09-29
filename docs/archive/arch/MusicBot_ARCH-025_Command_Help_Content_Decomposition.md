# ARCH-025 — Command/Help-Content-Dekomposition + ARCH-024 Technical-Debt-Fixes

**Status:** COMPLETE.
**Scope:** `handlers/menu/rich_menu_handler.py` (Command-/Help-Verantwortung),
`handlers/menu/rich_menu_system.py` (Debt-Fix 1+2), `handlers/menu/actions/stats.py`
(Debt-Fix 3), `handlers/menu/definitions.py` (Folgeänderung aus Debt-Fix 3).
**Branch:** `arch-025/command-help-content-decomposition`, PR #206.
**Basis:** `main` @ `d6eadc6` (ARCH-024 P-1–P-4, PR #205, gemergt).

---

## Herkunft

ARCH-024 (Menu-Datei-Dekomposition) dokumentierte drei bewusst
zurückgestellte technische Schulden ("Remaining Technical Debt") sowie
die bewusste Nicht-Extraktion des Onboarding-Clusters aus
`RichMenuHandler` (P-5-Entscheidung: NOT WARRANTED zum damaligen
Zeitpunkt, siehe `docs/MusicBot_ARCH-024_Menu_File_Decomposition.md`).
ARCH-025 greift beides gezielt auf:

- **Teil A:** erneute Bewertung der Command-/Help-Verantwortung in
  `RichMenuHandler` unter einem engeren, gezielteren Auftrag als die
  ursprüngliche ARCH-024/P-5-Prüfung (die den gesamten Onboarding-
  Cluster in einem Zug bewertete) — diesmal mit konkretem
  Struktur-Vorschlag (`content/`-Paket) und expliziten
  Characterization-Vorgaben.
- **Teil B:** die drei ARCH-024-Debt-Punkte tatsächlich beheben, nicht
  nur dokumentieren.

---

## Teil A — Command/Help Decomposition

### A.1 Characterization (Command/Help Dependency Map)

Vollständige Untersuchung von `handlers/menu/rich_menu_handler.py`
(1411 Zeilen zu Beginn dieser Phase) sowie aller zugehörigen Tests.

| Funktion | Called by | Calls | State access | Tests | Patch-Ziele |
|---|---|---|---|---|---|
| `handle_start_command` | `CommandHandler("start", ...)` in `get_telegram_handlers()` | `is_blocked_by_maintenance`, `record_activity`, `_is_new_user`, `_get_user_role`, `_get_available_features`, `update.message.reply_text`, `error_handler.handle_command_error` | `maintenance_store`, `status_handler`, `error_handler`, `config`, `features`, `user_mgmt_handler`, `user_data_file`, `logger` | `test_rich_menu_handler_maintenance_gate.py` (3), `test_rich_menu_handler_activity_tracking.py` (3) — testen ausschließlich Gate/Activity-Tracking + finalen Nachrichtentext | keine |
| `handle_menu_command` | `CommandHandler("menu", ...)` | `is_blocked_by_maintenance`, `record_activity`, `menu_system.show_menu` | `maintenance_store`, `status_handler`, `menu_system` | 2 (Gate + Activity) | keine |
| `handle_help` | `CommandHandler("help", ...)` | `is_blocked_by_maintenance`, `record_activity`, `_get_user_role`, `_get_available_features`, `update.message.reply_text`, `error_handler.handle_command_error` | wie `handle_start_command` (ohne `_is_new_user`) | 2 (Gate + Activity) | keine |
| `handle_help_callback` | `CallbackQueryHandler(self.handle_help_callback, pattern="^help:")` — **direkt registriert, umgeht `RichMenuSystem.handle_callback()` vollständig** | `is_blocked_by_maintenance`, `record_activity`, `_get_user_role`, die 4 `_get_*_help()` | wie oben | 2 (Gate + Activity) | keine |
| `_get_download_help`/`_get_stats_help`/`_get_navidrome_help`/`_get_admin_help` | nur `handle_help_callback` | — (0 `self`-Zugriff, reine statische Strings) | keiner | keine direkten Tests | keine |
| `_get_user_role` | `handle_start_command`, `handle_help`, `handle_help_callback` (3×) | `_get_user_info` → `_load_user_data` | `config.OWNER_USER_ID`/`ADMIN_USER_IDS` | `test_rich_menu_handler.py::TestGetUserRole` (5) | keine — aber Cross-Reference in `permissions.py`-Docstring |
| `_get_available_features` | `handle_start_command`, `handle_help` | — | `features` (FEATURES-Katalog) | `test_rich_menu_handler.py::TestGetAvailableFeatures` (3) | keine |
| `_is_new_user` | `handle_start_command` | `_get_user_info` | — | `test_rich_menu_handler.py::TestIsNewUser` (3) | keine |
| `_get_user_info` | `_is_new_user`, `_get_user_role` | `_load_user_data`, `user_mgmt_handler.user_data_cache` | — | keine direkten Tests | keine |
| `_load_user_data` | `_get_user_info` | — | `user_data_file` | `test_rich_menu_handler.py::TestUserDataFileIsolation` (1) | keine |

**Wichtiger Befund:** `handle_help_callback` wird als eigener
`CallbackQueryHandler(self.handle_help_callback, pattern="^help:")`
registriert — **nicht** über `RichMenuSystem.handle_callback()`'s
zentrales Präfix-Routing. Dies ist die einzige Ausnahme von diesem
Muster im gesamten Menüsystem und bleibt durch die Extraktion
unverändert (die Telegram-Registrierung selbst wurde nicht angefasst).

**Kein Test** inspiziert die interne Struktur dieser Methoden — alle
Tests prüfen ausschließlich (a) ob Maintenance-Gate/Activity-Tracking
korrekt greifen und (b) den am Ende gesendeten Nachrichtentext/
Callback-Answer. Das bedeutet: die eigentliche Content-Erzeugung kann
verschoben werden, ohne einen einzigen Test anzupassen — bestätigt
durch vollständige Prüfung aller Testtreffer vor der Umsetzung.

### A.2 Architekturentscheidung

**Decision:** Neues Paket `handlers/menu/content/` mit drei Modulen:
`user_context.py` (Nutzerkontext-Auflösung + Feature-Katalog),
`greeting.py` (/start-Begrüßung), `help.py` (/help + Help-Callback +
die 4 statischen Hilfetexte). `RichMenuHandler.handle_start_command()`/
`handle_help()`/`handle_help_callback()` werden zu dünnen Delegatoren
(Maintenance-Gate + Activity-Tracking + ein Aufruf in `content/`) —
identisches Muster zu den ARCH-024-Actions. `_load_user_data()`/
`_get_user_info()`/`_is_new_user()`/`_get_user_role()`/
`_get_available_features()` bleiben als dünne Delegator-**Methoden**
auf `RichMenuHandler` erhalten (nicht entfernt), da
`tests/test_rich_menu_handler.py` sie direkt als gebundene Methoden
aufruft.

**Reason:** Die vom Master-Prompt vorgeschlagene Struktur
(`commands/start.py`+`commands/help.py`+`content/greeting.py`+
`content/help.py`, vier Dateien) wurde geprüft und als zu granular
verworfen: `commands/*.py` hätte nur die bereits auf `RichMenuHandler`
vorhandene dünne Delegation dupliziert (Gate-Check + Activity-Tracking
+ ein Funktionsaufruf lässt sich nicht sinnvoll in eine eigene Datei
auslagern, ohne `RichMenuHandler` selbst zur reinen Weiterleitungshülle
zu machen — dafür gibt es hier keinen Bedarf, `handle_menu_command()`
bleibt aus genau diesem Grund ebenfalls unverändert in
`RichMenuHandler`). Ein separates `user_context.py` ist dagegen
gerechtfertigt: `/start` und `/help` teilen sich exakt dieselbe
Rollen-/Feature-Auflösung — ohne dieses gemeinsame Modul müsste entweder
`content/help.py` von `content/greeting.py` importieren (unklare
Abhängigkeitsrichtung zwischen zwei fachlich gleichrangigen Modulen)
oder die Logik würde dupliziert.

**Alternative (verworfen):** 4-Datei-Struktur (`commands/start.py`,
`commands/help.py`, `content/greeting.py`, `content/help.py`) exakt wie
im Master-Prompt als Beispiel skizziert.

**Why rejected:** hätte für ~360 Zeilen tatsächlichen Inhalt 5 neue
Dateien erzeugt (inkl. `user_context.py`), von denen zwei
(`commands/*.py`) nur 5-8 Zeilen dünne Weiterleitung enthalten hätten —
Verstoß gegen CLAUDE.md §18/§21 Regel 1 (kein Refactor nur wegen
Formschönheit) und die im Master-Prompt selbst formulierte Leitlinie
"Architekturvereinfachung ist wichtiger als maximale Modularisierung".

**Consequence:** `handlers/menu/content/` enthält 3 Module (+
`__init__.py`), keine Rückreferenz auf `RichMenuHandler`/
`RichMenuSystem` (AST-verifiziert). `RichMenuHandler` bleibt
Composition Root + Lifecycle + dünne Command-Adapter + Download-
Pipeline-Einstieg + Permission-Delegate — der zuvor dokumentierte
Onboarding-"Inhalt" ist vollständig entfernt.

### A.3 `/menu` — bewusst NICHT extrahiert

`handle_menu_command()` (15 Zeilen: Maintenance-Gate + Activity-
Tracking + Logging + `self.menu_system.show_menu(...)`) erfüllt exakt
die im Master-Prompt genannte Bedingung für "bleibt als dünner Command
Adapter" — unverändert belassen, keine neue Datei für 15 Zeilen reine
Delegation.

### A.4 Alte Struktur → Neue Struktur

```text
Vorher (RichMenuHandler, Auszug):
  __init__(): FEATURES-Katalog inline (42 Zeilen)
  handle_start_command(): Gate + Tracking + volle Begrüßungslogik (105 Zeilen)
  handle_help(): Gate + Tracking + volle Hilfelogik (72 Zeilen)
  handle_help_callback(): Gate + Tracking + volle Callback-Logik (85 Zeilen)
  _get_download_help()/_get_stats_help()/_get_navidrome_help()/_get_admin_help() (44 Zeilen)
  _load_user_data()/_get_user_info()/_is_new_user()/_get_user_role()/_get_available_features() (51 Zeilen)

Nachher:
  handlers/menu/content/
  ├── __init__.py
  ├── user_context.py    FEATURES + load_user_data()/get_user_info()/
  │                       is_new_user()/get_user_role()/get_available_features()
  ├── greeting.py          send_start_message()
  └── help.py              get_download_help()/get_stats_help()/
                            get_navidrome_help()/get_admin_help()/
                            send_help_message()/send_help_callback_response()

  RichMenuHandler:
  __init__(): self.features = user_context.FEATURES (1 Zeile)
  handle_start_command(): Gate + Tracking + 1 Delegationsaufruf (8 Zeilen)
  handle_help(): Gate + Tracking + 1 Delegationsaufruf (9 Zeilen)
  handle_help_callback(): Gate + Tracking + 1 Delegationsaufruf (8 Zeilen)
  _load_user_data()/_get_user_info()/_is_new_user()/_get_user_role()/
  _get_available_features(): je 1 Delegationszeile (dünne Methoden,
  bleiben aus Test-Kompatibilitätsgründen erhalten)
  handle_menu_command(): unverändert (bewusst nicht extrahiert)
```

`rich_menu_handler.py`: 1411 → 1109 Zeilen (-21 %).

### A.5 Extracted

- `/start`-Begrüßungslogik (Neuling-/Wiederkehrer-Text, Rollen-Badge,
  Feature-Liste, Keyboard-Aufbau) → `content/greeting.py`
- `/help`-Themenübersicht + Help-Callback-Routing → `content/help.py`
- Die 4 statischen Hilfetexte → `content/help.py`
- Nutzerkontext-Auflösung (Feature-Katalog, Rollen-/Neuling-Ermittlung,
  JSON-Datei-Fallback) → `content/user_context.py`

### A.6 Intentionally retained (in `RichMenuHandler`)

- `handle_menu_command()` — bereits dünner Adapter, keine Content-Logik
- `handle_start_command()`/`handle_help()`/`handle_help_callback()` als
  dünne Delegatoren (Gate + Tracking + Delegation) — das IST die
  "notwendige Systemintegration", die laut Zielbild in `RichMenuHandler`
  bleiben soll
- `_load_user_data()`/`_get_user_info()`/`_is_new_user()`/
  `_get_user_role()`/`_get_available_features()` als dünne
  Delegator-Methoden — **nicht** entfernt, weil
  `tests/test_rich_menu_handler.py` sie direkt als gebundene Methoden
  aufruft (Patchability-/Bestandstest-Erhalt, siehe harte Regel 17)
- `self.features`-Attribut — als Alias auf `user_context.FEATURES`
  erhalten (kein externer Leser gefunden, aber kostenlos zu erhalten)

---

## Teil B — ARCH-024 Technical-Debt-Fixes

### B.1 Stale Kommentar-Referenz (`rich_menu_system.py`)

**Gefunden:** Kommentarblock über der (nach ARCH-024 leeren)
Download-Control-Center-Sektion verwies auf `_handle_download_new()`
und `_handle_download_history()` als lokale Methoden dieser Klasse.
Beide existieren seit ARCH-024/P-2 nur noch als `handle_download_new()`/
`handle_download_history()` in `handlers/menu/actions/download.py`.

**Verifiziert:** `grep` bestätigte 0 verbleibende `_handle_download_new`/
`_handle_download_history`-Methoden in `rich_menu_system.py`.

**Korrigiert:** Kommentar aktualisiert — verweist jetzt korrekt auf
`handlers/menu/actions/download.py`, historischer Kontext (Nutzer-
Vorgabe vom 2026-09-02, damalige Prioritäten) inhaltlich unverändert
erhalten, nur um einen Hinweis auf die spätere Umsetzung des Download-
Verlaufs (2026-09-03) ergänzt, da der ursprüngliche Text ihn noch als
zukünftig ausstehend beschrieb.

### B.2 Sechs tote Importe (`rich_menu_system.py`)

| Import | Vorkommen vor Fix (gesamte Datei, inkl. Kommentare) | Externe Referenzen (Patch-Ziele, `from...import`) | Entschieden |
|---|---|---|---|
| `Any` | 1 (nur Import) | 0 | entfernt |
| `MenuState` | 1 (nur Import) | 0 | entfernt |
| `Path` | 1 (nur Import) | 0 | entfernt |
| `json` | 1 (nur Import) | 0 | entfernt |
| `timedelta` | 1 (nur Import) | 0 | entfernt |
| `CallbackQueryHandler` | 1 (nur Import) | 0 | entfernt |

Jeder der 6 Namen wurde per Wortgrenzen-Regex gegen den **gesamten**
Dateiinhalt (Code, Docstrings, Kommentare) geprüft — genau 1 Treffer
(die Import-Zeile selbst) für jeden. Zusätzlich repoweit nach
`rich_menu_system.<Name>` (Patch-Ziel-Muster) und
`from handlers.menu.rich_menu_system import <Name>` gesucht — 0
Treffer. Nach Entfernung erneut verifiziert: 0 verbleibende
Referenzen.

**Nicht angefasst (außerhalb des explizit benannten Scopes):**
`List`/`Set` (`typing`) sind ebenfalls bereits tote Importe in
`rich_menu_system.py`, `MenuState`/`Callable` in `rich_menu_handler.py`
— keiner der vier war Teil der ursprünglich benannten „6 tote Importe"
und wird daher hier nicht entfernt (harte Regel 5: keine unrelated
Codeänderungen). Als neuer, unbehobener Fund dokumentiert.

### B.3 Fünf tote Stats-Methoden

**Identifiziert:** `RichMenuSystem._handle_stats_monthly`/`_yearly`/
`_top_songs`/`_top_artists`/`_timeline` sowie die von ihnen
delegierten `stats_actions.handle_stats_monthly_system`/`_yearly_system`/
`_top_songs_system`/`_top_artists_system`/`_timeline_system` in
`handlers/menu/actions/stats.py`.

**Referenzen vor dem Fix:**
- `rich_menu_system.py`: die 5 Methodendefinitionen selbst
- `definitions.py`: `handler=system._handle_stats_monthly` (usw., 5×)
  in `build_menu_tree()`
- `tests/test_menu_definitions.py`: 5 Mock-Attributnamen in
  `_FakeSystem.__init__()` (nur damit `build_menu_tree()` nicht mit
  `AttributeError` abbricht)
- `tests/test_menu_actions_stats.py`: 3 direkte Tests der
  `_system`-Funktionen

**Runtime-Bindungs-Nachvollzug:** `RichMenuHandler.initialize()` ruft
`self.menu_system.initialize_menu_structure()` (setzt die 5 toten
Bindungen) **unmittelbar gefolgt von** `self._register_stats_handlers()`
(überschreibt sie per `register_handler()` mit den echten, live
genutzten `_handle_*_stats_wrapper`-Methoden) — beides synchron
innerhalb derselben `initialize()`-Ausführung, **bevor** der Bot
irgendein Update verarbeiten kann. Es existiert kein Zeitfenster, in
dem ein Nutzer die toten Bindungen erreichen könnte.

**Ausnahme geprüft:** `tests/test_suite.py`'s `menu_system`-Fixture
konstruiert eine **bare** `RichMenuSystem` (`initialize_menu_structure()`
ohne den vollen `RichMenuHandler.initialize()`-Durchlauf) — hier hätte
`stats_monthly.handler` vor dem Fix noch auf die tote Methode gezeigt.
Repoweite Suche bestätigte: **kein** Test in `test_suite.py` oder
anderswo ruft `handle_callback()` mit `"menu:stats_monthly"` o. ä. auf
oder inspiziert deren `.handler`-Attribut — der Fix ist daher auch für
diesen isolierten Konstruktionspfad verhaltensneutral (`item.handler is
not None or item.is_action`-Filter in `test_suite.py::
test_callback_data_uniqueness` bleibt durch `is_action=True` unberührt).

**Fix:**
1. `definitions.py`: `handler=system._handle_stats_monthly` (usw., 5×)
   entfernt — die 5 `MenuItem`s behalten `is_action=True`, bekommen
   aber kein `handler=` mehr. `register_handler()` verdrahtet den
   echten Handler unverändert zur Laufzeit.
2. `rich_menu_system.py`: die 5 toten Methoden entfernt,
   `_handle_stats_library_overview` (einzige weiterhin live gebundene
   Ausnahme) unverändert erhalten.
3. `actions/stats.py`: die 5 toten `_system`-Funktionen entfernt,
   Moduldocstring aktualisiert.
4. `tests/test_menu_definitions.py`: die 5 nicht mehr benötigten
   Mock-Attributnamen aus `_FakeSystem` entfernt, neuer Test
   `test_build_menu_tree_dead_stats_items_have_no_handler_but_stay_actions`
   ergänzt (charakterisiert den neuen Zustand: `handler is None`,
   `is_action is True` für die 5, unveränderte Live-Bindung für
   `stats_library_overview`).
5. `tests/test_menu_actions_stats.py`: die 3 Tests der entfernten
   `_system`-Funktionen entfernt; ein neuer Test
   `test_stats_library_overview_fallback_without_handler` ergänzt
   (bisher ungetesteter Fallback-Zweig von `handle_stats_library_overview`
   selbst — Coverage-Parität statt -Verlust).

**Keine funktionale Regression:** die tatsächlich im Bot sichtbaren
Stats-Buttons (`stats_monthly`/`stats_yearly`/`stats_top_songs`/
`stats_top_artists`/`stats_timeline`/`stats_library_overview`) rufen
vor und nach diesem Fix exakt dieselben Ziel-Handler auf
(`RichMenuHandler._handle_*_stats_wrapper` → `stats_actions.
handle_*_stats_wrapper`, bzw. `_handle_stats_library_overview` →
`stats_actions.handle_stats_library_overview`) — unverändert.

---

## Dependency-Audit

AST-basierte Zyklenprüfung über alle 14 `handlers/menu/*`-Module
(inkl. des neuen `content/`-Pakets): **keine Zyklen**. Neue Kanten:
`rich_menu_handler → content` (erwartet), `content.greeting →
content` / `content.help → content` (beide importieren
`user_context` innerhalb desselben Pakets). **Keine** Rückreferenz von
`content/` auf `rich_menu_handler.py`/`rich_menu_system.py` (repoweit
per `grep` verifiziert — die einzigen Treffer sind Docstring-Prosa,
keine Imports/Codeverweise).

```text
PASS
```

## Registry-Audit

Alle bisherigen `register_handler()`/`add_child_menu_item()`-Aufrufe in
`RichMenuHandler` unverändert (5 `_register_*`-Methoden, keine
Änderung an deren Inhalt). `get_telegram_handlers()` unverändert — alle
`CommandHandler`/`CallbackQueryHandler`-Registrierungen zeigen weiterhin
auf dieselben (jetzt dünneren) gebundenen Methoden. Keine doppelten
Bindungen, keine toten Registry-Einträge, keine überschriebenen
Legacy-Methoden neu entstanden.

```text
PASS
```

## Search-Audit (nach Abschluss)

Repoweit erneut gesucht nach: entfernten Methodennamen
(`_handle_stats_monthly` u. a., `handle_stats_*_system`), alten
Importnamen (`Any`/`MenuState`/`Path`/`json`/`timedelta`/
`CallbackQueryHandler` in `rich_menu_system.py`), alten Help-Methoden
(`self._get_download_help` u. a.), alten Modulpfaden. Alle Treffer sind
ausschließlich erklärende Kommentare/Docstrings, die die Verschiebung/
Entfernung selbst dokumentieren — keine stale Code-Referenzen.

```text
PASS
```

---

## Test-/Verifikationsstatus

**Keine Tests wurden lokal ausgeführt** (Master-Prompt-Vorgabe für
diese Phase). Vor jeder Änderung wurde stattdessen die tatsächliche
Test-Abdeckung/Patch-Ziel-Lage durch vollständiges Lesen der
betroffenen Testdateien und repoweite `grep`-Suche verifiziert (siehe
Abschnitt A.1 und Teil B je Debt-Punkt) — kein bestehender Test
inspiziert die jetzt verschobene interne Struktur, alle prüfen nur
Verhalten am öffentlichen Rand (finaler Nachrichtentext, Callback-
Answer, Gate-/Tracking-Aufrufe, `.handler`/`.is_action`-Attribute).

Zwei Testdateien wurden angepasst, ausschließlich wegen des
Debt-Fixes 3 (nicht wegen der Command/Help-Extraktion, die 0
Testanpassungen benötigte):
- `tests/test_menu_definitions.py` — 5 nicht mehr benötigte
  Mock-Attribute entfernt, 1 neuer Test ergänzt
- `tests/test_menu_actions_stats.py` — 3 Tests entfernter Funktionen
  entfernt, 1 neuer Test ergänzt (Coverage-Parität)

**Bestehende Full-Suite-Baseline (vom Nutzer nach ARCH-024 verifiziert,
nicht erneut ausgeführt):**

```text
3461 passed
1 skipped
11 subtests passed
0 failed
```

Diese Zahl gilt weiterhin als Referenz-Baseline vor ARCH-025 — der
Nutzer führt den nächsten vollständigen Lauf nach eigener Freigabe
dieser Phase durch.

---

## Bekannte verbleibende Punkte

- `List`/`Set` (`typing`) in `rich_menu_system.py` sowie `MenuState`/
  `Callable` in `rich_menu_handler.py` sind bereits vor ARCH-025 tote
  Importe — nicht behoben (außerhalb des explizit benannten Scopes
  dieser Phase, siehe B.2).
- Keine neuen P0/P1-Funde.
- ARCH-021/P-2-Deferred-Findings (`max_sessions`, `MenuSession.state`/
  `.data`/`.message_id`) unverändert, nicht Gegenstand dieser Phase.

---

## Files changed

```text
Neu:
handlers/menu/content/__init__.py
handlers/menu/content/user_context.py
handlers/menu/content/greeting.py
handlers/menu/content/help.py

Geändert:
handlers/menu/rich_menu_handler.py   (1411 → 1173 Zeilen)
handlers/menu/rich_menu_system.py    (Debt-Fix: -6 Importe, -5 Methoden, 1 Kommentar korrigiert)
handlers/menu/actions/stats.py       (Debt-Fix: -5 Funktionen)
handlers/menu/definitions.py         (Debt-Fix: -5 handler=-Bindungen)
handlers/menu/permissions.py         (Docstring-Cross-Reference aktualisiert)
tests/test_menu_definitions.py       (Debt-Fix-Testanpassung)
tests/test_menu_actions_stats.py     (Debt-Fix-Testanpassung)
docs/MusicBot_ARCH-024_Menu_File_Decomposition.md (Remaining-Technical-Debt-Abschnitt als CLOSED markiert)
```

Keine Änderungen an `docs/archive/*`, `README.md`, `CLAUDE.md` oder
`docs/FINDINGS_INDEX.md` (kein durch ARCH-025 geschlossenes/neues
Finding).

---

## Commit-Status

Freigabe erteilt. Code+Tests über Branch
`arch-025/command-help-content-decomposition`, Commit `7249907`
(+ Baseline-/Doku-Nachzug), als **PR #206** eingereicht und gemergt
(Basis `main` @ `d6eadc6`).
