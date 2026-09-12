# ARCH-023 — Menu-Router- und Permission-Architektur-Härtung

**Status:** COMPLETE (P-1 bis P-7). PR #204 gemergt (2026-09-13), siehe
Abschnitt „Commit-Status" unten. Nachfolgearchitektur `ARCH-024`
(Datei-Dekomposition) ebenfalls COMPLETE, siehe „Nächster Schritt".
**Scope:** `RichMenuSystem.handle_callback()` (Router-Autorisierung), die
fünf privilegierten Fach-Handler (`library_doctor_handler.py`,
`library_health_review_handler.py`, `repair_musicbot_handler.py`,
`admin/bot_restart_handler.py`, `test_menu_handler.py`),
`enhanced_error_handler.py::ErrorHandlerAdminInterface`,
`handlers/menu/maintenance_gate.py`, `utils/` (Discovery-Audit).

---

## Verhältnis zu ARCH-021

`ARCH-021/P-1` (der ursprüngliche Menü-Architekturaudit) schlug als Phase 5
„Router-Härtung" vor. Dieser Schritt wurde begonnen, wuchs aber zu einem
eigenständigen, sicherheitsfokussierten Mini-Projekt mit **eigener,
bei P-1 neu beginnender Phasenzählung** — deshalb unter der Bezeichnung
`ARCH-023` fortgeführt (nächste freie ARCH-Nummer, `ARCH-021`/`ARCH-022`
waren bereits für ein unabhängiges Genre/Last.fm-Thema vergeben, siehe
`docs/MusicBot_ARCH-021_Menu_Architecture_Migration.md` Abschnitt
„Hinweis zur Nummerierung").

**Wichtig:** `ARCH-023/P-6` und `ARCH-023/P-7` sind **inhaltlich nicht**
identisch mit den in `ARCH-021/P-1` ursprünglich skizzierten „P-6
Actions"/„P-7 Definitions" (Datei-Dekomposition von `rich_menu_system.py`).
Diese Datei-Dekomposition ist weiterhin **komplett offen** und wird als
eigener, neuer Block **`ARCH-024`** geführt (siehe dortige Doku).

---

## Phasenstatus

| Phase | Thema | Status |
|---|---|---|
| P-1 | Router-Härtungs-Audit (read-only) | ✅ COMPLETE |
| P-2 | Characterization (read-only, 34 neue Tests) | ✅ COMPLETE |
| P-3 | Menu-Fallback-Gate + `doctor:`/`review:`/`repair:`-Konsolidierung | ✅ COMPLETE |
| P-4 | `admin_navidrome`/`is_action`-Fix, TGPERM-001-Vertiefung, `maintenance_gate.py`-Konsolidierung | ✅ COMPLETE |
| P-5 | `erradmin:` Permission-Architektur (Owner-Fix) | ✅ COMPLETE |
| P-6 | Repoweiter Permission-/Authorization-Audit (inkl. `utils/`) | ✅ COMPLETE |
| P-7 | Handler-Level-Permission-Konsolidierung (5 Dateien) | ✅ COMPLETE |

---

## P-1 — Router-Härtungs-Audit (read-only)

Vollständige Charakterisierung von `RichMenuSystem.handle_callback()`: 12
Präfix-Familien, davon 5 zentral über `_ADMIN_ONLY_PREFIXES` gegatet, 7 mit
eigenem Dispatcher-Check. **Kernbefund:** der generische `menu:`-Fallback
prüfte `MenuItem.access_level` **nie** vor dem Handler-Aufruf — nur
`render_menu()` nutzte es (Button-Sichtbarkeit, keine Autorisierung).
Zusätzlich: `doctor:`/`review:`/`repair:` dupliziert `OWNER_USER_ID or
ADMIN_USER_IDS` dreifach inline statt `self._is_admin_check()` zu nutzen.

---

## P-2 — Characterization (read-only)

34 neue Tests (`tests/test_menu_router_characterization.py`, neu) froren
das Ist-Verhalten der sechs ungetesteten/unvollständig getesteten
`menu:`-Items (`admin_users`/`admin_logs`/`admin_navidrome`/`test_unit`/
`test_integration`/`test_performance`) sowie von `doctor:`/`review:`/
`repair:`/`erradmin:` ein — inkl. der bis dahin unbekannten
`show_alert`-UX-Diskrepanz und der `erradmin:`-Owner-Lücke (siehe P-5).

---

## P-3 — Menu-Fallback-Gate + Konsolidierung

`RichMenuSystem.handle_callback()`: neue zentrale Prüfung vor jedem
`menu:`-Handler-Aufruf —
```python
user_level = self._get_user_access_level(user_id)
if not menu_item.is_accessible(user_level):
    ... "⛔ Keine Berechtigung", show_alert=True
    return
```
Schließt die TGPERM-001-Fehlerklasse **strukturell** für alle
`menu:`-Items, nicht nur die sechs bekannten. `_handle_doctor_callback()`/
`_handle_review_callback()`/`_handle_repair_callback()`: Inline-Duplikate
durch `self._is_admin_check()` ersetzt. `reprocess:` bewusst unverändert
(OWNER-only). **Bewusste, dokumentierte UX-Änderung:** `admin_users`/
`admin_logs`/`admin_navidrome` erhalten bei Ablehnung jetzt `show_alert=True`
(vorher kein Alert) — das zentrale Gate greift vor dem schwächeren
Handler-eigenen Check.

---

## P-4 — admin_navidrome / TGPERM-001 / maintenance_gate

`admin_navidrome`-MenuItem: `is_action=True` ergänzt (war `False` trotz
gesetztem `handler=` — Modellierungsinkonsistenz, `is_action` wird von
keiner Produktionslogik gelesen, nur von Test-Tooling). Neue, **zusätzliche**
verhaltensbasierte TGPERM-001-Testklasse
`TestPrivilegedMenuItemsActuallyDenyNonAdminTGPERM001`
(`tests/test_rich_menu_access_control.py`) — ruft `handle_callback()` echt
mit Nicht-Admin auf, statt nur die Registry-Struktur zu prüfen; ergänzt,
ersetzt nicht die bestehende `TestPrivilegedMenuItemsAreGatedTGPERM001`.
`handlers/menu/maintenance_gate.py`: eigener `is_admin`-Block durch
`permissions.is_admin_or_owner()` ersetzt.

---

## P-5 — erradmin: Permission-Architektur

**Fund:** `ErrorHandlerAdminInterface.is_admin()` prüfte nur `user_id in
self.admin_user_ids` — **kein** `OWNER_USER_ID`-Sonderfall, im Unterschied
zu jedem anderen Admin-Präfix. Da `Config.ADMIN_USER_IDS` ohne eigenes
Env-Var auf `[OWNER_USER_ID]` zurückfällt, blieb das in der Praxis meist
unbemerkt — griff aber, sobald `ADMIN_USER_IDS` explizit auf eine Liste
ohne den Owner gesetzt wurde. **Entscheidung: Fall A (Owner soll Zugriff
haben)** — belegt durch Code-Alter (Initial Commit), Config-Default-Verhalten,
einheitliche Nutzung für Slash-Commands und Menü, fehlende
Doku-Begründung für eine Owner-Ausnahme. Fix: `ErrorHandlerAdminInterface.
__init__()` erhält neuen Pflichtparameter `config`; `is_admin()` delegiert
an `permissions.is_admin_or_owner()`. `bot.py`s Konstruktionsaufruf und
`tests/test_enhanced_error_handler.py`s Fixture entsprechend angepasst.

---

## P-6 — Repoweiter Permission-Audit (inkl. utils/)

Vollständige Discovery: 9 lokale Permission-Methoden identifiziert, davon
5 als historisches Implementierungs-Duplikat klassifiziert (Kategorie C+D
gleichzeitig — architektonisch legitimes Defense-in-Depth, aber
duplizierte Berechnung). `utils/` vollständig auditiert (16 Dateien) —
nur `utils/bot_restart_trigger.py` und `utils/navidrome_scan_trigger.py`
permission-nah, beide **Kategorie E** (reine technische Utilities ohne
eigene Autorisierungsverantwortung, liegen hinter bereits gegateten
Handlern). Kein P0/P1-Fund. Trust-Boundary-Analyse bestätigt: jede
privilegierte Operation hat mindestens eine wirksame Autorisierungsschicht.

---

## P-7 — Handler-Level-Konsolidierung

Datei für Datei (Reihenfolge: LibraryDoctorHandler →
LibraryHealthReviewHandler → RepairMusicBotHandler → BotRestartHandler →
TestMenuHandler), je: Characterization-Test ergänzt → Inline-`_is_admin()`
durch `return is_admin_or_owner(user_id, self.config)` ersetzt → Regression
geprüft. **Defense-in-Depth vollständig erhalten** — nur die Berechnung
ist jetzt zentral, keine Call-Site, kein Control-Flow, keine
Fehlermeldung, kein Logging verändert. `TestMenuHandler`s veralteter
Docstring (behauptete fälschlich, der generische Fallback prüfe nichts —
seit P-3 falsch) korrigiert. `reprocess:`/`ReprocessingMenuHandler.
_is_owner()` und die SEC-005-Owner-Rollenvergabe in
`user_management_handler.py` bewusst unverändert (Kategorie B, eigene
Repository-Evidenz-gestützte Regeln, keine Duplikate).

Abschließende repoweite Discovery: **keine verbleibenden Kategorie-C-Duplikate**
unter den P-6-Kandidaten. Alle 8 aktiven `_is_admin`/`is_admin`/
`_is_admin_check`-Implementierungen nutzen jetzt `permissions.
is_admin_or_owner()`; einzige bewusst abweichende Methode ist
`ReprocessingMenuHandler._is_owner()` (OWNER-only, Kategorie B).

---

## Kumulative Testergebnisse (gezielt/thematisch, keine volle Suite durch Claude)

```
348 passed, 0 failed, 0 skipped
(alle 5 Handler + BotRestartTrigger + Router-Dispatch-Tests für
doctor/review/repair/maintenance + TGPERM-001/Access-Control +
Permissions-Charakterisierung + erradmin + maintenance_gate)
```

---

## Commit-Status

Alle ARCH-023-Änderungen (P-1 bis P-7) wurden über Branch
`arch-023/menu-router-permission-hardening`, Commit `0a908aa`
(+ Baseline-Nachzug `a346a7f`), als **PR #204 gemergt** (Merge-Commit
`2e1bf18`, Basis `2f9f34b`). Enthält u. a.: `bot.py`,
`handlers/enhanced_error_handler.py`, `handlers/menu/maintenance_gate.py`,
`handlers/menu/rich_menu_handler.py`, `handlers/menu/rich_menu_system.py`,
`handlers/library_doctor_handler.py`,
`handlers/library_health_review_handler.py`,
`handlers/repair_musicbot_handler.py`,
`handlers/admin/bot_restart_handler.py`, `handlers/test_menu_handler.py`,
zugehörige Tests, `tests/test_menu_router_characterization.py` (neu).

---

## Nächster Schritt (Historie — Folgearchitektur)

**`ARCH-024`** — Datei-Dekomposition von `handlers/menu/rich_menu_system.py`
(3117 → 1095 Zeilen)/`rich_menu_handler.py` (1608 → 1411 Zeilen): Actions
(9 Domänen-Module unter `handlers/menu/actions/`), Definitions
(`definitions.py`), Rendering (`rendering.py`); Onboarding-Extraktion nach
Kriterien geprüft und als NOT WARRANTED eingestuft — der ursprünglich in
`ARCH-021/P-1` als „P-6 Actions … P-9 Onboarding" skizzierte Teil der
Menü-Migration. **Status: COMPLETE** (P-1–P-4; P-5 NOT WARRANTED). Siehe
`docs/MusicBot_ARCH-024_Menu_File_Decomposition.md`.
