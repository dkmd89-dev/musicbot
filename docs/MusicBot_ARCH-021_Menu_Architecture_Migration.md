# ARCH-021 — Telegram-Menüsystem-Architekturmigration (`handlers/menu/`)

**Status:** LIVING (fortlaufend aktualisiert pro abgeschlossener Phase, CLAUDE.md §30)
**Scope:** `handlers/menu/rich_menu_handler.py`, `handlers/menu/rich_menu_system.py` und die daraus extrahierten Module
**Zweck:** zentrale Referenz für den Fortschritt der ARCH-021-Migration — welche Phase ist abgeschlossen, welche Evidenz belegt das, welche Legacy-Findings sind bewusst zurückgestellt.

---

## Hinweis zur Nummerierung (Kollision, analog zum bereits im Repo etablierten Präzedenzfall bei ARCH-020/021)

`ARCH-021` ist in diesem Repository **bereits einmal vergeben**:
`docs/archive/arch/MusicBot_ARCH-021_Genre_Client_Duplication_Characterization.md`
(2026-08-25, HISTORICAL, Thema: Genre-Client-Duplikation / Last.fm-Cover-Charakterisierung).
`ARCH-022` ist ebenfalls bereits vergeben (`docs/FINDINGS_INDEX.md`, Genre-System
YAML→JSON-Migration + `determine_genre_with_fallbacks()`-Fix, CLOSED 2026-09-03).

Diese Dokumentation hier behandelt ein **inhaltlich vollständig unabhängiges** Thema
(Telegram-Menüsystem-Architektur, nicht Genre/Last.fm) und wurde dennoch unter der
Bezeichnung `ARCH-021` begonnen, bevor die Kollision mit dem historischen Dokument
geprüft wurde. Nach Rücksprache mit dem Nutzer (2026-09-13) wurde entschieden, die
Bezeichnung **beizubehalten** statt rückwirkend umzunummerieren — Branch
(`arch-021/p2-p3-p4-menu-decomposition`), Commit (`69e419e`) und PR (#203) sind unter
diesem Namen bereits veröffentlicht und wären nur per Force-Push/Rebase rückwirkend
änderbar. Diese Kollision wird hier bewusst sichtbar dokumentiert statt verschwiegen
(vgl. den Renaming-Vermerk im o. g. historischen ARCH-021-Dokument für denselben
Vorgang bei einer früheren ARCH-020/021-Kollision). **Zwei unabhängige `ARCH-021` im
Repo — dieses Dokument hier ist die Menü-Architektur, das archivierte ist Genre/
Last.fm.** Der nächste freie, unbenutzte ARCH-Slot für künftige neue Phasen ist
`ARCH-023`.

---

## Phasenstatus

| Phase | Thema | Status | Evidenz |
|---|---|---|---|
| P-1 | Audit — Ist-Zustand, Dependency-Matrix, Zielarchitektur-Entscheidung | ✅ COMPLETE (2026-09-12) | Read-only-Analyse, Ergebnis siehe Abschnitt „P-1 — Kernentscheidungen" unten (Bericht wurde ausschließlich im Gesprächsverlauf geliefert, hier erstmals persistiert) |
| P-2 | Models Extraction (`MenuItem`/`MenuSession`/`AccessLevel`/`MenuState` → `handlers/menu/models.py`) | ✅ COMPLETE | Commit `69e419e`, PR #203 |
| P-3 | Permissions Extraction (`is_admin_or_owner()`/`get_user_access_level()` → `handlers/menu/permissions.py`) | ✅ COMPLETE | Commit `69e419e`, PR #203 |
| P-4 | Session/State Extraction (`SessionManager` → `handlers/menu/session.py`) | ✅ COMPLETE | Commit `69e419e`, PR #203 |
| P-5 | Router-Härtung (deklarative Präfix→AccessLevel-Tabelle statt hartcodierter `if/elif`-Kette + 5-Präfix-Allowlist) | ⏳ NOT STARTED — nächster Schritt ist ein reines READ-ONLY-Audit, kein Code | — |
| P-6+ | Actions-/Definitions-/Rendering-Extraktion | ⏳ NOT STARTED | — |

---

## P-1 — Kernentscheidungen (Audit, 2026-09-12)

Vollständiger, read-only Architekturaudit von `handlers/menu/` (repoweite Dependency-Analyse, Methodencharakterisierung beider Kerndateien, Test-Landschaft). Zentrale Ergebnisse:

- **`handlers/menu/` bleibt bestehen — kein Top-Level `menu/`.** Die Kopplung an Telegram durchdringt praktisch jede Methode (`Update`, `CallbackQuery`, `InlineKeyboardMarkup`); ein UI-Framework-agnostischer „Core" existiert im Code nicht und würde ohne konkreten zweiten Kanal eine Abstraktion auf Vorrat bedeuten (CLAUDE.md §18/§21 Regel 1).
- **`RichMenuSystem` hat null direkte Imports konkreter Handler-/Service-Klassen** — alle Kollaborateure werden über Setter-Injection (Duck-Typing) von `RichMenuHandler` verdrahtet. `RichMenuHandler` ist der einzige echte Composition-Root und der **einzige externe Aufrufer des gesamten Subsystems ist `bot.py`** (ein einziger Import) — sehr geringe Blast-Radius-Fläche für interne Umstrukturierung.
- **Wichtigster struktureller Befund über TGPERM-001 hinaus:** Rollen-/Berechtigungslogik war zweifach, unabhängig implementiert (`RichMenuHandler._is_admin()`/`_get_user_role()` vs. `RichMenuSystem._is_admin_check()`/`_get_user_access_level()`) — genau die Art Duplikation, die Lücken wie TGPERM-001 begünstigt. → adressiert in P-3.
- **Empfohlene Zielstruktur innerhalb `handlers/menu/`** (kein Umzug nach Top-Level): `models.py`, `permissions.py`, `session.py`, `router.py` (gehärtet), `rendering.py`, `definitions.py`, `actions/*.py` (nach Fachdomäne gruppiert: Download, Stats/Family, Admin-Diagnostics, Admin-Operations, Library, Navidrome/Usermgmt) — orientiert an den bereits im Admin-Menü etablierten fachlichen Gruppen, nicht an Zeilenzahl.
- **Empfohlene Reihenfolge:** P-2 Models → P-3 Permissions → P-4 Session/State → P-5 Router-Härtung → P-6 Actions (domänenweise) → P-7 Definitions → P-8 Rendering → P-9 optional Onboarding-Extraktion.

---

## P-2 — Models Extraction ✅ COMPLETE

**Umsetzung:** `handlers/menu/models.py` (neu) — `MenuState`, `AccessLevel`, `MenuItem`, `MenuSession` unverändert (Move, kein Rewrite) aus `rich_menu_system.py` verschoben. `rich_menu_system.py`/`rich_menu_handler.py` importieren die Modelle von dort. Keine Abhängigkeit von `models.py` auf `rich_menu_system.py`/`rich_menu_handler.py`/Telegram.

**Getestet:** `test_rich_menu_system.py`, `test_suite.py`, `test_rich_menu_access_control.py` — 94/94 grün vor und nach der Extraktion (identisch). Vollständige Suite (vom Nutzer ausgeführt, Stand nach P-2 alleine): 3280 passed, 1 skipped, 11 subtests passed.

---

## P-3 — Permissions Extraction ✅ COMPLETE

**Umsetzung:** `handlers/menu/permissions.py` (neu) — `is_admin_or_owner(user_id, config)` ersetzt `RichMenuHandler._is_admin()` **und** `RichMenuSystem._is_admin_check()` (zuvor zwei unabhängige, aber für jede reale Config äquivalente Implementierungen); `get_user_access_level(user_id, config, user_mgmt_handler)` unverändert aus `RichMenuSystem._get_user_access_level()` verschoben. `RichMenuHandler._get_user_role()` (String-Rolle, JSON-Datei-Fallback für Begrüßungstext/Feature-Liste) bewusst **nicht** vereinheitlicht — andere Rückgabesemantik/Konsumenten, kein reiner Permission-Belang.

**Einzige dokumentierte Verhaltensänderung:** `_is_admin()` wirft bei einer Config ohne `OWNER_USER_ID`-Attribut nicht mehr `AttributeError`, sondern verhält sich wie `_is_admin_check()` (defensiv, `getattr(...)`-Fallback) — in Produktion unerreichbarer Randfall (echte `config.Config` setzt das Attribut immer), explizit durch `TestIsAdminOrOwnerEdgeCase` charakterisiert.

**TGPERM-001-Schutz unverändert:** `_ADMIN_ONLY_PREFIXES` und dessen Verwendung in `handle_callback()` wurden nicht angefasst; `TestPrivilegedMenuItemsAreGatedTGPERM001` läuft unverändert grün.

**Getestet:** `tests/test_menu_permissions_characterization.py` (neu, 17 Tests) + `test_rich_menu_access_control.py` (23 Tests) — alle grün.

---

## P-4 — Session/State Extraction ✅ COMPLETE

**Umsetzung:** `handlers/menu/session.py` (neu) — `SessionManager` übernimmt `sessions`/`session_timeout`/`max_sessions`/`get_session()`/`cleanup_expired_sessions()` 1:1 aus `rich_menu_system.py`. `RichMenuSystem` behält eine `sessions`-Property, die das Live-Dict des `SessionManager` zurückgibt (**Dict-Identität, keine Kopie** — explizit getestet: `menu_system.sessions is menu_system.session_manager.sessions`) — bestehende direkte Zugriffe (`_handle_close()`s `del self.sessions[user_id]`, ~11 Bestandstests) funktionieren dadurch unverändert weiter. `get_session()`/`cleanup_expired_sessions()` auf `RichMenuSystem` sind dünne Delegations-Wrapper an denselben Zeilenpositionen wie vorher.

**Getestet:** `tests/test_menu_session_characterization.py` (neu, 13 Tests) — Dict-Identität, isolierte `SessionManager`-Unit-Tests, Config-Wiring. Alle grün.

---

## Gemeinsame Ergebnisse P-2/P-3/P-4

**Commit:** `69e419e` (Branch `arch-021/p2-p3-p4-menu-decomposition`)
**Pull Request:** [#203](https://github.com/dkmd89-dev/musicbot/pull/203) — offen, noch nicht gemergt (Stand dieses Dokuments)

**Architekturprüfung:** `models.py` hat keine interne `handlers.menu.*`-Abhängigkeit (Basis der Schichtung); `permissions.py` und `session.py` hängen je ausschließlich von `handlers.menu.models` ab — keine Abhängigkeit untereinander oder auf `rich_menu_system.py`/`rich_menu_handler.py`/Telegram, exakt wie im P-1-Audit als Zielarchitektur festgelegt. Import-Rundlauf (`models` → `permissions`/`session` → `rich_menu_system` → `rich_menu_handler`) fehlerfrei, keine Zirkularität.

**Testergebnisse (kumulativ, nach P-2+P-3+P-4):**

```
Gezielt: test_rich_menu_access_control.py + test_menu_permissions_characterization.py
         + test_menu_session_characterization.py                          65 passed

Thematische Menu-Gesamtsuite (rich_menu*, suite, permissions-/session-
charakterisierung, activity_tracking, maintenance_gate,
text_workflow_dispatcher, reprocessing, test_menu_handler*,
logger_menu_path_traversal)                                              390 passed

python3 -m compileall handlers/menu/ + neue Testdateien                  fehlerfrei

Vollständige Suite (vom Nutzer selbst ausgeführt, CLAUDE.md §8.A):
3312 passed, 1 skipped, 11 subtests passed, 0 failed  (202,84 s)
```

Keine Regression, kein neuer Testfehlschlag, TGPERM-001 durchgängig geschützt.

---

## Bewusst zurückgestellte Legacy-Findings (nicht Gegenstand von P-2/P-3/P-4)

Während der P-1/P-4-Charakterisierung entdeckt, **bewusst nicht behoben** (Move-Only-Prinzip, keine Verhaltensänderung außerhalb des jeweiligen Extraktions-Scopes) — siehe auch `docs/FINDINGS_INDEX.md`:

- **`max_sessions`/`MAX_CONCURRENT_SESSIONS` ohne Durchsetzung** — wird in `SessionManager` gehalten, aber nirgends geprüft; keine Kapazitätsbegrenzung der Session-Anzahl trotz des Namens. Charakterisiert in `test_max_sessions_is_stored_but_not_enforced`.
- **`MenuSession.state` (`MenuState`-Enum) vollständig ungenutzt** — bleibt dauerhaft auf Default `IDLE`, wird nie gesetzt oder gelesen.
- **`MenuSession.data: Dict[str, Any]` vollständig ungenutzt** — nie gelesen oder geschrieben.
- **`MenuSession.message_id` write-only** — wird in `show_menu()` gesetzt, aber nirgends im Repository gelesen.
- **`RichMenuHandler.user_states: Dict[int, str]`** — eigenständiger, von `MenuSession`/`SessionManager` unabhängiger State-Mechanismus (nur für die laut P-1 bereits als UI-unerreichbar dokumentierten Legacy-Download-Wrapper `download_single`/`download_playlist`). Keine Überschneidung, kein gemeinsamer Code-Pfad.

Keine dieser Beobachtungen stellt eine durch P-2/P-3/P-4 verursachte Regression dar — alle sind vorbestehender, unveränderter Zustand.

---

## Nächster Schritt

**ARCH-021/P-5 — Router-Härtung**, zunächst als reines READ-ONLY-Audit (Ist-Zustand/Characterization/Abhängigkeiten/Zielarchitektur/Risiken/Testplan), erst nach gesonderter Freigabe als Implementierung. Ziel laut P-1-Audit: die heutige `if callback_data.startswith(...)`-Kette plus hartcodierte 5-Präfix-Admin-Allowlist (`_ADMIN_ONLY_PREFIXES`) durch eine deklarative, vollständige Präfix→AccessLevel-Tabelle ersetzen, die zentral vor jedem Dispatch geprüft wird — die strukturelle Antwort auf die TGPERM-001-Fehlerklasse, nicht nur deren punktuellen Fix.
