# ARCH-024 — Menu-Datei-Dekomposition (Actions/Definitions/Rendering)

**Status:** COMPLETE (P-1 bis P-4; P-5 = NOT WARRANTED, siehe unten).
**Scope:** `handlers/menu/rich_menu_system.py` (3117 → 1095 Zeilen),
`handlers/menu/rich_menu_handler.py` (1608 → 1411 Zeilen).
**Branch:** `arch-024/menu-file-decomposition`, PR #205, siehe Abschnitt
„Commit-Status".
**Basis:** `main` @ `2e1bf18` (ARCH-023 P-1–P-7, PR #204, gemergt).

---

## Herkunft

`ARCH-021/P-1` (2026-09-12) empfahl `P-6 Actions → P-7 Definitions →
P-8 Rendering → P-9 Onboarding`. Diese Nummern wurden von `ARCH-023`
(Router-/Permission-Härtung, inhaltlich anders) belegt. Die Datei-
Dekomposition läuft daher eigenständig als `ARCH-024/P-1`–`P-5`
(siehe `docs/MusicBot_ARCH-023_Menu_Router_Permission_Hardening.md`,
Abschnitt „Verhältnis zu ARCH-021").

---

## Phasenstatus

| Phase | Thema | Status |
|---|---|---|
| P-1 | Audit & Characterization (read-only) | ✅ COMPLETE |
| P-2 | Actions Extraction (9 Domänen) | ✅ COMPLETE |
| P-3 | Definitions Extraction | ✅ COMPLETE |
| P-4 | Rendering Extraction | ✅ COMPLETE |
| P-5 | Onboarding (optional) | ⛔ NOT WARRANTED (begründet, s. u.) |

---

## P-1 — Audit & Characterization

### 1.1 Ausgangslage

`RichMenuSystem` (Router/State-Machine) und `RichMenuHandler`
(Composition Root) wurden vollständig gelesen (100 %, nicht
stichprobenartig). `models.py`/`permissions.py`/`session.py`/
`maintenance_gate.py` sind bereits eigenständige Module (ARCH-021/
ARCH-023) und bleiben unverändert Grundlage.

### 1.2 Zentraler Befund: die drei bestehenden Admin-Gruppen sind die
### tatsächliche fachliche Gliederung

`initialize_menu_structure()` gruppiert das Admin-Menü bereits selbst
in drei Container (`admin_group_library`, `admin_group_operations`,
`admin_group_diagnostics` — UX-Reorg, vor ARCH-024 entstanden). Diese
Gruppierung ist evidenzstärker als die ursprüngliche `ARCH-021/P-1`-
Hypothese („Admin Diagnostics"/„Admin Operations" als grobe Namen ohne
Bezug zum tatsächlichen Code) und wird für die Actions-Extraktion 1:1
übernommen:

```text
admin_group_library      → Reprocessing, Doctor, Review, Repair,
                            Navidrome-Scan (dynamisch registriert)
admin_group_operations   → Backup, Bot-Neustart, Wartungsmodus
admin_group_diagnostics  → System-Status, System-Logs, Error-Verwaltung,
                            Logger-Verwaltung
```

Zusätzlich bestehen fünf weitere, klar eigenständige Domänen:
Download (inkl. Download-Control-Center), Stats (persönlich),
Family (Stats/Chat/Challenge — ein Bereich, drei Untermenüs),
Navidrome (Browse/Suche, User-Facing), Benutzerverwaltung
(`usermgmt_*`), Duplikat-Verwaltung (`dup:*` — CLAUDE.md Abschnitt 15:
eigene P0-Domäne, nicht Teil von „Bibliothek").

### 1.3 Zweiter zentraler Befund: die meisten `_handle_*`-Methoden sind
### bereits dünne Wrapper zu eigenständigen Handler-Klassen

Von den ca. 100 Methoden in `RichMenuSystem`/`RichMenuHandler` enthält
nur eine kleine Minderheit echte, nicht delegierte Geschäftslogik:

- **Download-Control-Center** (`RichMenuSystem`, ~300 Zeilen): einzige
  vollständig inline implementierte Fach-Domäne ohne eigene
  Handler-Klasse (`_handle_download_menu`, `_render_download_menu`,
  `_handle_download_control_callback`, `_handle_download_new/_active/
  _cancel_request/_details/_history/_retry`, plus die
  `_RetryMessageAdapter`/`_RetryUpdateAdapter`/`_dl_progress_bar`-Helfer).
- **Wartungsmodus** (`_handle_maintenance_show`/`_handle_maintenance_
  callback`): bewusst ohne eigene Handler-Klasse (Kommentar im Code),
  liest/schreibt `MaintenanceModeStore` direkt.
- **Navidrome-Scan** (`RichMenuHandler._handle_navidrome_scan`): ruft
  `NavidromeScanTrigger.run_scan()` direkt auf, eigene MarkdownV2-
  Formatierung.
- **System-Logs** (`RichMenuHandler._handle_view_logs`): liest die
  Logdatei direkt.
- **Download-Pipeline** (`RichMenuHandler._process_url`/
  `handle_url_message`/`_create_download_handler`): konstruiert
  `DownloadHandler` und startet den Hintergrund-Task.
- **Benutzerverwaltungs-Callback** (`_handle_usermgmt_callback`, ~120
  Zeilen): eigene Workflow-State-Mutation (`context.user_data`), nicht
  nur Pass-Through.

Alle übrigen `_handle_*`-Methoden (Family ×12, Navidrome-Browse/Suche
×11, Stats ×11, Backup ×5, Doctor/Review/Repair/Reprocessing-Einstiege
×4, Logger-/Status-/ErrorAdmin-/Duplicate-Dispatcher) sind reine
Adapter: „nimm `(update, context)`, rufe die entsprechende Methode auf
einer bereits existierenden, unabhängig getesteten Handler-Klasse auf,
zeige `_show_handler_not_available()` wenn nicht verfügbar". Ihre
Extraktion bringt trotzdem echten Wert: sie sind es, die
`rich_menu_system.py`/`rich_menu_handler.py` aufblähen, und ihre
Gruppierung nach Fachdomäne (statt nach „ist zufällig eine Methode
dieser Gott-Klasse") ist genau das Ziel von ARCH-024.

### 1.4 Architekturentscheidung: Sub-Dispatcher sind Actions, nicht Router

**Entscheidung:** Nur `RichMenuSystem.handle_callback()` selbst (das
zentrale Präfix-Routing, die `_ADMIN_ONLY_PREFIXES`-Prüfung und das
Menu-Fallback-Gate aus ARCH-023/P-3) sowie `_handle_back`/
`_handle_close`/`_find_menu_item_by_id`/`_show_handler_not_available`
zählen als ROUTING und bleiben in `rich_menu_system.py`. Alle
`_handle_<domäne>_callback`-Methoden (z. B. `_handle_doctor_callback`,
`_handle_backup_callback`, `_handle_maintenance_callback`, …), die
`handle_callback()` per Präfix aufruft, wandern **zusammen mit ihrer
Fachdomäne** in die jeweilige `actions/`-Datei.

**Begründung:** Diese Methoden routen ausschließlich *innerhalb* ihrer
eigenen Domäne (z. B. `dl:new` vs. `dl:active` vs. `dl:history` –
alles Download), oft inklusive eigener Defense-in-Depth-Berechtigungs-
prüfung (z. B. `doctor:`/`review:`/`repair:`/`reprocess:`/`maint:`/
`restart:`). Sie sind damit eher eine Feature-eigene Mini-Routing-
Tabelle als Teil der zentralen, sicherheitsrelevanten Cross-Cutting-
Schicht. Das zentrale `handle_callback()` bleibt unverändert die
einzige Stelle mit dem echten, sicherheitskritischen Kern (Menu-
Fallback-Gate, `_ADMIN_ONLY_PREFIXES`).

**Alternative (verworfen):** alle `_handle_*_callback`-Methoden im
Router belassen und nur die inline-Business-Logik (Download-Control-
Center, Wartungsmodus) extrahieren. Verworfen, weil das
`rich_menu_system.py` kaum verkleinert hätte (die Dispatcher-Methoden
machen ca. 1000 der 3117 Zeilen aus) und weil es die im Zielbild
(Abschnitt 37 des Master-Prompts) vorgesehene Struktur „Actions
enthalten domänenspezifische Unter-Routen" nicht abgebildet hätte.

**Konsequenz:** Jede Actions-Datei enthält gelegentlich eine eigene,
kleine `handle_<domäne>_callback(update, context, callback_data, …)`-
Funktion mit Präfix-Sub-Routing – das ist gewollt und kein Rückfall in
„Router im Router".

### 1.5 Methodeninventar (Gruppen; volle Methode-für-Methode-Liste s.
### `grep -n "    def \|    async def " handlers/menu/rich_menu_system.py
### handlers/menu/rich_menu_handler.py`, im Rahmen von P-1 vollständig
### durchgesehen)

| Gruppe | Datei (jetzt) | # Methoden | Klassifikation | Zieldatei |
|---|---|---|---|---|
| Setter (23×) | rich_menu_system.py | 23 | COMPOSITION | bleibt |
| `initialize_menu_structure`/`_build_registry` | rich_menu_system.py | 2 | DEFINITION | `definitions.py` (P-3) |
| Download-Control-Center + Helfer | rich_menu_system.py | 14 | ACTION | `actions/download.py` |
| Wartungsmodus | rich_menu_system.py | 2 | ACTION | `actions/admin_operations.py` |
| Reprocessing (Einstieg+Dispatcher) | rich_menu_system.py | 2 | ACTION | `actions/library.py` |
| Doctor (Einstieg+Dispatcher) | rich_menu_system.py | 2 | ACTION | `actions/library.py` |
| Review (Einstieg+Dispatcher) | rich_menu_system.py | 2 | ACTION | `actions/library.py` |
| Repair (Einstieg+Dispatcher) | rich_menu_system.py | 2 | ACTION | `actions/library.py` |
| Navidrome-Wrapper (Browse×4, Suche×4, Playlists/Favoriten/Recent) | rich_menu_system.py | 11 | ACTION | `actions/navidrome.py` |
| Navidrome-Callback-Dispatcher (`nav_*`) | rich_menu_system.py | 1 | ACTION | `actions/navidrome.py` |
| Stats-Wrapper (inkl. 5 durch `register_handler` überschriebene/tote) | rich_menu_system.py | 7 | ACTION | `actions/stats.py` |
| Family-Stats/-Chat/-Challenge-Wrapper | rich_menu_system.py | 12 | ACTION | `actions/family.py` |
| Logger-Callback-Dispatcher | rich_menu_system.py | 1 | ACTION | `actions/admin_diagnostics.py` |
| UserMgmt-Callback-Dispatcher | rich_menu_system.py | 1 | ACTION | `actions/usermgmt.py` |
| Duplicate-Callback-Dispatcher | rich_menu_system.py | 1 | ACTION | `actions/duplicates.py` |
| ErrorAdmin-Callback-Dispatcher | rich_menu_system.py | 1 | ACTION | `actions/admin_diagnostics.py` |
| Status-Callback-Dispatcher + `_handle_status_menu` | rich_menu_system.py | 2 | ACTION | `actions/admin_diagnostics.py` |
| Backup-Wrapper ×5 + Backup-Callback-Dispatcher | rich_menu_system.py | 6 | ACTION | `actions/admin_operations.py` |
| Restart-Callback-Dispatcher | rich_menu_system.py | 1 | ACTION | `actions/admin_operations.py` |
| Session/Permission-Delegates (`sessions`, `get_session`, `_get_user_access_level`, `_is_admin_check`, `cleanup_expired_sessions`) | rich_menu_system.py | 5 | SESSION/PERMISSION | bleibt (bereits ARCH-021/023) |
| Rendering (`render_menu`/`get_menu_text`/`show_menu`) | rich_menu_system.py | 3 | RENDERING | `rendering.py` (P-4) |
| `handle_callback`, `_handle_back`, `_handle_close`, `_find_menu_item_by_id`, `register_handler`, `add_child_menu_item`, `_show_handler_not_available` | rich_menu_system.py | 7 | ROUTING | bleibt |
| `__init__`/`initialize`/`_register_*`/Setter ×10/`get_telegram_handlers`/`cleanup` | rich_menu_handler.py | ~20 | COMPOSITION | bleibt |
| Download-Wrapper + Pipeline (`_handle_download_*_wrapper`, `handle_url_message`, `_process_url`, `_create_download_handler`, Legacy-Aliase) | rich_menu_handler.py | 8 | ACTION | `actions/download.py` |
| Stats-Wrapper ×5 | rich_menu_handler.py | 5 | ACTION | `actions/stats.py` |
| UserMgmt-Wrapper, View-Logs | rich_menu_handler.py | 2 | ACTION | `actions/usermgmt.py` (UserMgmt) / `actions/admin_diagnostics.py` (Logs) |
| Navidrome-Scan | rich_menu_handler.py | 1 | ACTION | `actions/admin_operations.py` |
| `_is_admin` | rich_menu_handler.py | 1 | PERMISSION | bleibt |
| `_load_user_data`/`_get_user_info`/`_is_new_user`/`_get_user_role`/`_get_available_features` | rich_menu_handler.py | 5 | ONBOARDING-nah | bleibt, s. P-5 |
| `handle_start_command`/`handle_menu_command`/`handle_help`/`handle_help_callback`/Hilfetexte ×4 | rich_menu_handler.py | 8 | ONBOARDING | s. P-5 |
| `handle_text_message` | rich_menu_handler.py | 1 | ROUTING (Text-Dispatch) | bleibt |

### 1.6 Charakterisierte Verhaltensdetails (vor Extraktion eingefroren)

- **Tote Handler-Zuweisungen (bestätigter Bestandsbefund, keine
  ARCH-024-Regression):** `RichMenuHandler._register_stats_handlers()`
  registriert `stats_monthly`/`stats_yearly`/`stats_top_songs`/
  `stats_top_artists`/`stats_timeline` per `register_handler()`
  **nach** `initialize_menu_structure()` und überschreibt dadurch die
  dort gesetzten `RichMenuSystem._handle_stats_*`-Bindings vollständig
  (`register_handler()` schreibt `menu_registry[id].handler` direkt).
  `RichMenuSystem._handle_stats_monthly/_yearly/_top_songs/
  _top_artists/_timeline` sind dadurch im Produktivbetrieb **nie**
  erreichbar (nur `stats_library_overview` bleibt live, da nicht
  registriert). Dasselbe gilt für `download_single`/`download_playlist`
  (durch `RichMenuHandler._handle_download_*_wrapper` überschrieben).
  Diese toten Methoden werden 1:1 mitverschoben (Verhaltensparität),
  nicht gelöscht (kein ARCH-024-Scope, siehe CLAUDE.md Abschnitt 20).
- **Dynamische Registrierung:** `admin_navidrome` existiert NICHT im
  `initialize_menu_structure()`-Baum, sondern wird ausschließlich über
  `RichMenuHandler._register_system_handlers()` →
  `menu_system.add_child_menu_item("admin_group_library", ...)` zur
  Laufzeit ergänzt. `admin_users`/`admin_logs`/`test_unit`/
  `test_integration`/`test_performance` werden im Baum ohne
  `handler=` angelegt und ausschließlich über `register_handler()`
  bestückt.
- **`_handle_download_control_callback` (`dl:*`) und die Wartungs-/
  Doctor-/Review-/Repair-/Reprocess-Callback-Dispatcher besitzen jeweils
  eigene Fehlermeldungen/Log-Texte/`show_alert`-Werte** — bleiben beim
  Verschieben exakt erhalten (keine Vereinheitlichung, das war
  ARCH-023-Scope und ist abgeschlossen).
- **Lazy-Binding-Pattern:** alle Wrapper prüfen `if self.xxx_handler:`
  zur Aufrufzeit, nicht zur Menü-Konstruktionszeit (zu diesem Zeitpunkt
  sind die meisten Handler-Referenzen noch `None`, siehe
  `RichMenuHandler.initialize()`-Reihenfolge: `initialize_menu_
  structure()` läuft vor den `set_*_handler()`-Aufrufen). Dieses Pattern
  muss erhalten bleiben — Actions dürfen keine zum Zeitpunkt ihrer
  Definition kopierte Handler-Referenz halten, sondern müssen sie bei
  jedem Aufruf frisch von der `self`-Quelle lesen.

### 1.7 Extraktionsstrategie: Funktionen mit explizit übergebenen
### Dependencies statt zustandsbehafteter Actions-Klassen

**Entscheidung:** Actions werden als Modul-Funktionen implementiert,
die ihre Abhängigkeiten (Handler-Referenzen, Stores, Logger) als
Parameter erhalten, statt als Klasse mit im Konstruktor kopierten
Referenzen.

**Begründung:** Tests weisen Handler-Referenzen teils direkt zu
(`menu_system.maintenance_store = Mock()`, `menu_system.stats_handler
= None`), nicht nur über die vorhandenen Setter. Eine Actions-Klasse,
die sich ihre Abhängigkeiten beim Konstruieren kopiert, würde nach
einer solchen Nachträglichen Zuweisung veraltete Referenzen halten
(Aufruf ginge am neuen Mock vorbei). Reine Funktionen, denen
`RichMenuSystem`/`RichMenuHandler` bei jedem Aufruf ihre *aktuellen*
`self.xxx`-Attribute übergeben, sind dagegen zustandslos und immer
konsistent mit dem Aufrufer — exakt das heute schon bestehende Lazy-
Binding-Verhalten (Abschnitt 1.6), nur an eine Modulgrenze verschoben.
Das entspricht außerdem der Master-Prompt-Vorgabe „kleinste notwendige
Dependency injizieren, nicht die komplette Instanz weiterreichen":
jede Funktion bekommt referenziert, was sie faktisch braucht (z. B.
`stats_handler`), nie `self`/die ganze `RichMenuSystem`-Instanz.

**Konsequenz:** `RichMenuSystem`/`RichMenuHandler` behalten ihre
bestehenden Attribute (`self.family_stats_handler` usw.) unverändert;
ihre `_handle_*`-Methoden werden zu Ein-/Zweizeilern, die die
gleichnamige Funktion aus `actions/<domäne>.py` mit den aktuellen
Attributwerten aufrufen. Keine Property-Umbauten, keine
Test-Anpassungen an bestehenden Fixtures nötig, sofern die Tests nur
über den öffentlichen Callback-/Attribut-Zugriff gehen (verifiziert für
alle 18 Fundstellen in Abschnitt 1.6/Grep-Audit).

### 1.8 SAFE / RISKY / DO NOT EXTRACT

```text
SAFE TO EXTRACT (reine 1:1-Verschiebung, kein Cross-File-State):
  actions/family.py, actions/navidrome.py (RichMenuSystem-Teil),
  actions/duplicates.py, actions/admin_diagnostics.py
  (RichMenuSystem-Teil), actions/library.py, actions/stats.py
  (RichMenuSystem-Teil), actions/admin_operations.py
  (Wartungsmodus + Backup + Restart-Show, RichMenuSystem-Teil)

RISKY (Cross-File zwischen RichMenuSystem und RichMenuHandler, oder
mutierbarer Shared State):
  actions/download.py (Download-Control-Center in RichMenuSystem UND
    Download-Pipeline in RichMenuHandler; `self.user_states`-Dict wird
    von RichMenuHandler-Wrappern geschrieben und von
    handle_url_message() gelesen — bleibt Attribut auf
    RichMenuHandler, wird als Parameter durchgereicht, nicht verschoben)
  actions/usermgmt.py (RichMenuHandler._handle_user_management_wrapper
    + RichMenuSystem._handle_usermgmt_callback — zwei Klassen, ein
    Modul)
  actions/admin_diagnostics.py (RichMenuHandler._handle_view_logs +
    RichMenuSystem-Dispatcher — zwei Klassen, ein Modul)
  actions/admin_operations.py (RichMenuHandler._handle_navidrome_scan +
    RichMenuSystem-Teile — zwei Klassen, ein Modul)

DO NOT EXTRACT (P-1-Entscheidung, siehe Begründung):
  handle_callback() + _handle_back/_handle_close/
    _find_menu_item_by_id/_show_handler_not_available/
    register_handler/add_child_menu_item (ROUTING-Kern)
  _get_user_access_level/_is_admin_check/_is_admin (bereits
    ARCH-021/023-Ergebnis, PERMISSION-Kern)
  sessions/get_session/cleanup_expired_sessions (bereits
    ARCH-021/P-4-Ergebnis, SESSION-Kern)
  initialize()/_register_*/__init__/Setter/get_telegram_handlers/
    cleanup (COMPOSITION-Kern von RichMenuHandler)
  handle_start_command/handle_help*/_get_user_role/
    _get_available_features (Onboarding — s. P-5-Entscheidung unten)
```

### 1.9 Extraktionsreihenfolge (P-2)

Nach Kopplungsgrad (niedrigste zuerst) und Cross-File-Risiko:

```text
1. actions/family.py           (nur RichMenuSystem, 12 reine Wrapper)
2. actions/duplicates.py       (nur RichMenuSystem, 1 Dispatcher, 3 Fälle)
3. actions/navidrome.py        (nur RichMenuSystem, 12 Methoden)
4. actions/stats.py            (RichMenuSystem 7 + RichMenuHandler 5)
5. actions/admin_diagnostics.py (RichMenuSystem 4 + RichMenuHandler 1)
6. actions/usermgmt.py         (RichMenuSystem 1 + RichMenuHandler 1)
7. actions/library.py          (nur RichMenuSystem, 8 Methoden, 4 Domänen)
8. actions/admin_operations.py (RichMenuSystem 8 + RichMenuHandler 1)
9. actions/download.py         (RichMenuSystem 14 + RichMenuHandler 8 — höchstes Risiko, zuletzt)
```

Nach jeder Datei: `python3 -m compileall handlers/menu`, gezielte
Regressionstests der betroffenen Test-Dateien, `git diff --stat`-
Kontrolle (nur erwartete Dateien geändert).

---

## P-2 — Actions Extraction (COMPLETE)

Alle 9 in Abschnitt 1.9 geplanten Domänen wurden in der geplanten
Reihenfolge extrahiert, jeweils: Extraktion → `compileall` →
gezielte Regressionstests der betroffenen Bestandstests → neue
Characterization-Testdatei für das jeweilige `actions/`-Modul. Kein
Schritt hat eine bestehende Testerwartung wissentlich verändert — zwei
entdeckte Kopplungen an den *alten* Modulpfad wurden bewusst korrigiert
(siehe „Bei der Extraktion gefundene, nicht-triviale Kopplungen" unten),
keine Verhaltensänderung der Produktionslogik selbst.

**Neue Dateien (`handlers/menu/actions/`):**

| Datei | Domäne | Herkunft |
|---|---|---|
| `_common.py` | geteilter Helfer `show_handler_not_available()` | `RichMenuSystem._show_handler_not_available()` |
| `family.py` | Familien-Statistik/-Chat/-Challenge (12 Funktionen) | `RichMenuSystem._handle_family_*` |
| `duplicates.py` | Duplikat-Verwaltung (`dup:*`) | `RichMenuSystem._handle_duplicate_callback` |
| `navidrome.py` | Navidrome Browse/Suche (`nav_*`) | `RichMenuSystem._handle_navidrome_*` |
| `stats.py` | Persönliche Statistiken (inkl. toter Menu-Definition-Bindungen, s. P-1 1.6) | `RichMenuSystem._handle_stats_*` + `RichMenuHandler._handle_*_stats_wrapper` |
| `admin_diagnostics.py` | Admin > Diagnose & Monitoring (Logger/Status/ErrorAdmin/Logs) | `RichMenuSystem._handle_logger_callback`/`_handle_error_admin_callback`/`_handle_status_*` + `RichMenuHandler._handle_view_logs` |
| `usermgmt.py` | Benutzerverwaltung (`usermgmt_*`) | `RichMenuSystem._handle_usermgmt_callback` + `RichMenuHandler._handle_user_management_wrapper` |
| `library.py` | Admin > Bibliothek & Navidrome (Reprocessing/Doctor/Review/Repair) | `RichMenuSystem._handle_reprocessing_*`/`_handle_doctor_*`/`_handle_review_*`/`_handle_repair_*` |
| `admin_operations.py` | Admin > Bot & Betrieb (Backup/Neustart/Wartungsmodus/Navidrome-Scan) | `RichMenuSystem._handle_backup_*`/`_handle_restart_*`/`_handle_maintenance_*` + `RichMenuHandler._handle_navidrome_scan` |
| `download.py` | Download-Control-Center + Download-Pipeline (größte, einzige domänenübergreifende Datei) | `RichMenuSystem`-Download-Control-Center + `RichMenuHandler`-Download-Wrapper/`_process_url`/`_create_download_handler` |

**Extraktionsmuster (konsistent über alle 9 Domänen):** Modul-Funktionen
mit explizit übergebenen Abhängigkeiten (Handler-Referenzen, Stores,
Logger, `config`) statt zustandsbehafteter Actions-Klassen — Begründung
in Abschnitt 1.7. `RichMenuSystem`/`RichMenuHandler` behalten alle
bestehenden Attribute unverändert; ihre `_handle_*`-Methoden wurden zu
Ein-/Zweizeilern, die die gleichnamige Funktion aus dem passenden
`actions/`-Modul mit den aktuellen Attributwerten aufrufen.

**Bei der Extraktion gefundene, nicht-triviale Kopplungen (gefunden über
gezielte Tests, sofort korrigiert, keine Produktionsverhaltensänderung):**

1. **`RichMenuHandler._handle_user_management_wrapper()` bei Bare-Object-
   Konstruktion:** `tests/test_menu_router_characterization.py::
   _make_bare_handler()` umgeht `__init__()` bewusst (nur `config`/
   `logger` gesetzt). Der ursprüngliche Code las `self.user_mgmt_handler`/
   `self.error_handler` erst *nach* dem frühen Admin-Check-Return -
   mein erster Delegator-Entwurf übergab diese Attribute aber eager als
   Funktionsargumente, was einen `AttributeError` auf dem Bare-Object
   auslöste, obwohl der reale Kontrollfluss sie nie gebraucht hätte.
   Fix: `getattr(self, "user_mgmt_handler", None)`/
   `getattr(self, "error_handler", None)` am Call-Standort - dasselbe
   defensive Zugriffsmuster, das an anderer Stelle im Code bereits für
   `status_handler` verwendet wird.
2. **Patch-Ziele in Bestandstests zeigten auf den alten Modulpfad:**
   `tests/test_rich_menu_handler.py`/`test_menu_router_characterization.py`
   patchten `handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan`
   bzw. `handlers.menu.rich_menu_handler.DownloadHandler` - nach der
   Verschiebung der tatsächlichen Konstruktions-/Aufrufstelle nach
   `handlers.menu.actions.admin_operations`/`handlers.menu.actions.download`
   griffen diese Patches ins Leere (der reale Code lief ungemockt gegen
   echte externe Abhängigkeiten). Fix: Patch-Ziele in beiden Testdateien
   auf die neuen Modulpfade aktualisiert (7 Fundstellen) - eine direkte,
   erwartete Konsequenz der Verschiebung, keine Verhaltensänderung der
   Produktionslogik.
3. **`RichMenuHandler._process_url()` musste `self._create_download_handler`
   patchbar halten:** `tests/test_rich_menu_handler.py` patcht
   `patch.object(handler, "_create_download_handler", ...)`, um
   `_process_url()` isoliert zu testen. `actions.download.process_url()`
   nimmt deshalb bewusst ein `create_handler_callback`-Callable entgegen
   statt selbst `create_download_handler()` mit Rohabhängigkeiten
   aufzurufen - `RichMenuHandler._process_url()` übergibt
   `self._create_download_handler` (die gepatchte, gebundene Methode),
   nicht die freie Funktion.
4. **Quelltext-Introspektion in `tests/test_enhanced_status_handler.py`:**
   `TestUnroutedStatusButtonsAreDocumented` extrahierte den Ausschnitt
   zwischen `async def _handle_status_callback`/`_handle_backup_callback`
   direkt aus dem Quelltext von `rich_menu_system.py`, um die dortige
   `routing_map` gegen die tatsächlich in `enhanced_status_handler.py`
   gerenderten Buttons abzugleichen. Nach der Verschiebung der
   `routing_map` nach `actions/admin_diagnostics.py` fand dieser Test
   dort nur noch den dreizeiligen Delegator (leere Menge statt der
   erwarteten 7 Callback-IDs). Fix: Testquelle auf
   `handlers/menu/actions/admin_diagnostics.py` (`handle_status_callback`/
   `handle_status_menu` als neue Grenzen) umgestellt - reine
   Testinfrastruktur-Anpassung, die geprüfte Charakterisierung
   (welche Buttons geroutet/ungeroutet sind) bleibt inhaltlich identisch.

**Nach jeder Domäne verifiziert:** `python3 -m compileall handlers/menu`
fehlerfrei; gezielte + thematische Tests grün (siehe „Tests Executed"
im Completion Report unten); `git diff --stat` zeigte ausschließlich die
erwarteten Dateien.

---

## P-3 — Definitions Extraction (COMPLETE)

`initialize_menu_structure()`/`_build_registry()` 1:1 nach
`handlers/menu/definitions.py` verschoben:

- `build_menu_tree(system) -> MenuItem` erstellt den kompletten
  MenuItem-Baum.
- `populate_registry(registry: dict, menu: MenuItem) -> None` baut die
  flache Registry (mutiert `registry` in place - Dict-Identität mit
  `RichMenuSystem.menu_registry` bleibt erhalten).

**Architekturentscheidung — `build_menu_tree()` nimmt `system` entgegen:**

- **Decision:** `build_menu_tree(system)` erhält die `RichMenuSystem`-
  Instanz selbst, nicht einzeln injizierte Callables (anders als alle
  `actions/`-Module).
- **Reason:** Jede `MenuItem.handler=`-Bindung im Baum verweist auf eine
  der ~55 dünnen `_handle_*`-Delegatoren, die nach P-2 auf
  `RichMenuSystem` verbleiben. Das ist keine neue Kopplung, sondern die
  unveränderte, bereits bestehende Verdrahtung.
- **Alternative (verworfen):** jede der ~55 Handler-Referenzen einzeln
  als benannten Parameter übergeben.
- **Why rejected:** hätte eine Funktionssignatur mit ~55 Parametern
  erzeugt - reine Formsache ohne Kohäsions- oder Testbarkeitsgewinn
  (die Handler-Methoden sind ohnehin nur über `system` erreichbar, da
  sie selbst wieder `self.xxx_handler`-Attribute von `system` lesen).
- **Consequence:** `definitions.py` ist das einzige Modul außerhalb von
  `rich_menu_system.py`/`rich_menu_handler.py`, das eine Instanz-
  Rückreferenz hält - bewusst, dokumentiert, auf die Definitions-Schicht
  begrenzt (Actions bleiben rückreferenzfrei).

**Dynamische Registrierung unverändert verifiziert** (Abschnitt 1.6):
`admin_navidrome`/`admin_users`/`admin_logs`/`test_unit`/
`test_integration`/`test_performance` bleiben nach `build_menu_tree()`
allein außerhalb der Registry (Test `test_admin_navidrome_not_in_static_tree`)
- `RichMenuHandler._register_system_handlers()`/`register_handler()`
ergänzen sie weiterhin zur Laufzeit, unverändert.

---

## P-4 — Rendering Extraction (COMPLETE)

`render_menu()`/`get_menu_text()`/`show_menu()` 1:1 nach
`handlers/menu/rendering.py` verschoben. `render_menu()`/`get_menu_text()`
waren bereits reine Funktionen ihrer Argumente (kein `self.`-Zugriff im
Methodenkörper) - unveränderte Signatur, nur der Ort hat sich geändert.
`show_menu()` benötigt Session-/Registry-/Permission-Zugriff und nimmt
diese explizit als Parameter entgegen (`menu_registry`, `root_menu`,
`get_session`, `get_user_access_level`, `logger`) - **keine**
Rückreferenz auf `RichMenuSystem` selbst, da Rendering laut Zielbild
(Master-Prompt Abschnitt 23) nur beantwortet "wie wird etwas
dargestellt", nicht "darf der Nutzer das"/"wie wird navigiert" - beide
Fragen bleiben in `RichMenuSystem`/`permissions.py`/`session.py`.

`RichMenuSystem.render_menu()`/`get_menu_text()`/`show_menu()` bleiben
als dünne öffentliche Delegatoren bestehen (von
`tests/test_rich_menu_system.py`/`test_suite.py` weiterhin direkt
aufgerufen).

**Nachgezogene Aufräumarbeit (direkte Folge der Extraktion, im Scope):**
`InlineKeyboardButton`-Import in `rich_menu_system.py` wurde nach P-2/P-4
nicht mehr verwendet (jede Tastatur-Konstruktion lebt jetzt in
`actions/`/`rendering.py`) - Import entfernt, `compileall` + volle
Menu-Testsuite grün. `Any`/`MenuState`/`Path`/`json`/`timedelta`/
`CallbackQueryHandler` sind ebenfalls unbenutzte Importe in
`rich_menu_system.py`, waren aber bereits **vor** ARCH-024 tot (per
`git show HEAD:... | grep -c` verifiziert) - nicht angefasst (außerhalb
des Scopes, CLAUDE.md Abschnitt 20).

---

## P-5 — Onboarding-Extraktion: NOT WARRANTED

Geprüfte Kandidaten (`RichMenuHandler`): `handle_start_command`,
`handle_menu_command`, `handle_help`, `handle_help_callback`,
`_get_download_help`/`_get_stats_help`/`_get_navidrome_help`/
`_get_admin_help`, `_is_new_user`, `_get_user_role`,
`_get_available_features`, `_load_user_data`, `_get_user_info`.

Bewertung gegen die 5 Kriterien aus dem Master-Prompt:

1. **Klare fachliche Grenze:** ⚠️ teilweise - Onboarding überschneidet
   sich mit Composition: `_get_available_features()` liest direkt den
   in `RichMenuHandler.__init__()` definierten `self.features`-Katalog
   (Composition-Root-Konfigurationsdaten, keine eigenständige Fachlogik).
2. **Relevante Eigenständigkeit:** ❌ gering - stärker mit dem Rest von
   `RichMenuHandler` verwoben als jede der neun P-2-Domänen: braucht
   `self.features`, `self.error_handler`, `self.maintenance_store`,
   `self.status_handler`, `self.user_mgmt_handler`, `self.menu_system`
   (für `handle_menu_command()`).
3. **Reduzierte Komplexität:** ⚠️ moderat - ca. 280 von 1411 Zeilen,
   spürbar aber nicht dominant.
4. **Bessere Testbarkeit:** ❌ kein Gewinn - alle Methoden sind bereits
   direkt gegen `RichMenuHandler`-Instanzen getestet und grün; es gibt
   keine bestehende Testbarkeitslücke, die eine Extraktion schließen
   würde.
5. **Keine künstliche Abstraktion:** ❌ Risiko - der Feature-Katalog
   (`self.features`) und sein Renderer (`handle_start_command()`/
   `handle_help()`) würden ohne fachlichen Grund auf zwei Dateien
   verteilt, anders als z. B. das vollständig in sich geschlossene
   Download-Control-Center.

3 von 5 Kriterien sind negativ/schwach erfüllt (2, 4, 5) →
**ARCH-024/P-5 = NOT WARRANTED.** Dies ist laut Master-Prompt ein
gültiges, erwünschtes Ergebnis - keine weitere Aktion.

---

## Abschluss-Audit (read-only, nach P-4 + P-5-Entscheidung)

| Frage | Befund |
|---|---|
| **Actions** sauber getrennt? | Ja - 9 kohäsive Module unter `handlers/menu/actions/`, jedes einer realen Fachdomäne zugeordnet (5 davon = die drei bestehenden UI-Admin-Gruppen `admin_group_library`/`_operations`/`_diagnostics`, s. Abschnitt 1.2). |
| **Definitions** eigenständig? | Ja - `definitions.py`, einzige bewusste Ausnahme von der Rückreferenz-Regel (begründet, s. P-3). |
| **Rendering** getrennt? | Ja - `rendering.py`, vollständig rückreferenzfrei. |
| **Router** noch Router? | Ja - `handle_callback()` (zentrales Präfix-Routing + `_ADMIN_ONLY_PREFIXES`-Check + Menu-Fallback-Gate aus ARCH-023) unverändert in `rich_menu_system.py`, ebenso `_handle_back`/`_handle_close`/`_find_menu_item_by_id`/`register_handler`/`add_child_menu_item`. |
| **Permissions** weiterhin zentral? | Ja - unverändert `permissions.is_admin_or_owner()`/`get_user_access_level()` (ARCH-021/ARCH-023-Ergebnis), von `actions/`-Modulen direkt importiert, keine Duplizierung. |
| **Session** weiterhin zentral? | Ja - unverändert `session.SessionManager` (ARCH-021/P-4-Ergebnis), nicht angefasst. |
| **Composition Root** (`RichMenuHandler`) sauber? | Weitgehend - `__init__`/`initialize()`/`_register_*`/10 Setter/`get_telegram_handlers()`/`cleanup()` sind die Composition-/Lifecycle-Schicht; verbleibende ~280 Zeilen Onboarding-Cluster bewusst nicht extrahiert (s. P-5). |
| **`RichMenuSystem`** noch unnötig groß? | Nein mehr - 3117 → 1095 Zeilen (-65 %); verbleibender Inhalt ist zu ca. 90 % Setter (Composition) + 1-3-zeilige Delegatoren (Routing-Glue) + der echte Router-Kern. |
| **Dependency Graph** zyklenfrei? | Ja - per AST-Analyse aller `handlers/menu/*`-Importe verifiziert (siehe Skript-Output, 12 Module, keine Zyklen). Richtung durchgehend `RichMenuHandler`/`RichMenuSystem` → `actions/`/`definitions`/`rendering` → `permissions`/`models` - keine Rückimporte. |
| **Testability** der neuen Komponenten? | Jede der 9 Actions-Dateien + `definitions.py` hat eine eigene, unabhängige Testdatei (`tests/test_menu_actions_*.py`, `tests/test_menu_definitions.py`) - importierbar und testbar ohne Telegram-/RichMenuSystem-Konstruktion. |
| **Telegram-Kopplung sinnvoll verteilt?** | Ja - `Update`/`ContextTypes`/`InlineKeyboardButton`/`InlineKeyboardMarkup` bleiben in `actions/`/`rendering.py` (die Schichten, die tatsächlich mit Telegram-Objekten arbeiten), nicht in `definitions.py` (reine Datenstruktur) oder `permissions.py`/`session.py` (unverändert). |

---

# ARCH-024 COMPLETION REPORT

## P-1
Vollständiger read-only Audit von `rich_menu_system.py`/
`rich_menu_handler.py` (100 %, method-für-Methode). Kernbefund: die
bestehenden UI-Admin-Gruppen (`admin_group_library`/`_operations`/
`_diagnostics`) sind die belastbarere fachliche Gliederung als die
ursprüngliche `ARCH-021/P-1`-Hypothese. Architekturentscheidung: nur
`handle_callback()` + 5 Kernmethoden sind ROUTING; alle
`_handle_<domäne>_callback`-Sub-Dispatcher gehören zu ihrer Domäne
(ACTION). Extraktionsstrategie: zustandslose Modul-Funktionen mit
explizit übergebenen Abhängigkeiten statt Actions-Klassen.

## P-2
9 Domänen extrahiert (family, duplicates, navidrome, stats,
admin_diagnostics, usermgmt, library, admin_operations, download - in
dieser, nach Kopplungsgrad sortierten Reihenfolge). ~2020 Zeilen aus
`rich_menu_system.py`, ~200 Zeilen (netto, da Docstrings/Delegator-
Boilerplate teils erhalten) aus `rich_menu_handler.py` verschoben. 3
nicht-triviale Testkopplungen gefunden und korrigiert (s. o.) - keine
Produktionsverhaltensänderung.

## P-3
`initialize_menu_structure()`/`_build_registry()` (853 Zeilen) nach
`handlers/menu/definitions.py` verschoben. Einzige bewusste Ausnahme von
der "keine Rückreferenz"-Regel, begründet dokumentiert.

## P-4
`render_menu()`/`get_menu_text()`/`show_menu()` nach
`handlers/menu/rendering.py` verschoben, vollständig rückreferenzfrei.

## P-5
Onboarding: **NOT WARRANTED** (3 von 5 Kriterien negativ, begründet
oben).

## Files Added
```
handlers/menu/actions/__init__.py
handlers/menu/actions/_common.py
handlers/menu/actions/family.py
handlers/menu/actions/duplicates.py
handlers/menu/actions/navidrome.py
handlers/menu/actions/stats.py
handlers/menu/actions/admin_diagnostics.py
handlers/menu/actions/usermgmt.py
handlers/menu/actions/library.py
handlers/menu/actions/admin_operations.py
handlers/menu/actions/download.py
handlers/menu/definitions.py
handlers/menu/rendering.py
tests/test_menu_actions_family.py
tests/test_menu_actions_duplicates.py
tests/test_menu_actions_navidrome.py
tests/test_menu_actions_stats.py
tests/test_menu_actions_admin_diagnostics.py
tests/test_menu_actions_usermgmt.py
tests/test_menu_actions_library.py
tests/test_menu_actions_admin_operations.py
tests/test_menu_actions_download.py
tests/test_menu_definitions.py
```

## Files Modified
```
handlers/menu/rich_menu_system.py   (3117 → 1095 Zeilen)
handlers/menu/rich_menu_handler.py  (1608 → 1411 Zeilen)
tests/test_rich_menu_handler.py           (Patch-Ziele aktualisiert, s. P-2)
tests/test_menu_router_characterization.py (Patch-Ziele aktualisiert, s. P-2)
tests/test_rich_menu_download_control_center.py (Import-Pfad aktualisiert)
tests/test_enhanced_status_handler.py     (Quelltext-Introspektion umgestellt, s. P-2)
```

## Files Removed
Keine. Alle bisherigen öffentlichen/privaten Methodennamen auf
`RichMenuSystem`/`RichMenuHandler` bleiben als Delegatoren erhalten
(volle Rückwärtskompatibilität für bestehende Aufrufer/Tests).

## Architecture Before
```
RichMenuHandler (1608 Zeilen: Composition + Onboarding + Download-
Pipeline + Actions + Permission)
  └─ RichMenuSystem (3117 Zeilen: Router + Definitions + Rendering +
     Session/Permission-Delegates + ALLE Actions inline)
```

## Architecture After
```
RichMenuHandler (1411 Zeilen: Composition + Lifecycle + Onboarding +
Download-Pipeline-Einstieg + Permission-Delegate)
  └─ RichMenuSystem (1095 Zeilen: Router-Kern + Composition-Setter +
     dünne Action-Delegatoren + Session/Permission-Delegates)
       ├─ definitions.py   (Menü-Baum + Registry, 880 Zeilen)
       ├─ rendering.py     (Tastatur/Text/show_menu, 145 Zeilen)
       ├─ actions/         (9 Module, 2016 Zeilen gesamt)
       ├─ permissions.py   (unverändert, ARCH-021/ARCH-023)
       ├─ session.py       (unverändert, ARCH-021/P-4)
       └─ models.py        (unverändert, ARCH-021/P-2)
```

## Dependency Graph
Zyklenfrei (AST-verifiziert). `RichMenuHandler`/`RichMenuSystem` →
`actions/`, `definitions`, `rendering` → `permissions`/`models`.
`definitions.py` hält als einzige Ausnahme eine `system`-Rückreferenz
(begründet, P-3). Keine Rückimporte von `actions/`/`definitions`/
`rendering` auf `rich_menu_system.py`/`rich_menu_handler.py`.

## Tests Executed
Ausschließlich gezielte/thematische Suiten (CLAUDE.md §8.A) - keine
volle Suite durch den Implementierungsprozess:
- Nach jeder P-2-Domäne: `tests/test_menu_actions_<domäne>.py` (neu) +
  die jeweils betroffenen Bestandstestdateien.
- Nach P-3: `tests/test_menu_definitions.py` (neu, 6 Tests) + volle
  Menu-Themensuite.
- Nach P-4: volle Menu-Themensuite.
- Abschließend: `python3 -m pytest tests/ -k "menu or rich_menu" -q`
  → **535 passed, 2927 deselected** (kumulativ über alle Phasen).
- Zusätzlicher breiter Abschluss-Sweep über alle von der Extraktion
  potenziell berührten Nachbarthemen (Status/Duplicate/Backup/Restart/
  Download/Reprocessing/Doctor/Review/Repair/Navidrome/Workflow-
  Dispatcher/UserManagement): `python3 -m pytest tests/ -k "menu or
  rich_menu or status_handler or duplicate_handler or backup_handler or
  bot_restart or download or reprocessing or library_doctor or
  library_health or repair_musicbot or navidrome or workflow_dispatcher
  or user_management" -q` → **1428 passed, 2034 deselected** (79,65 s).
  Dabei eine 4. Testkopplung gefunden und korrigiert (Quelltext-
  Introspektion in `test_enhanced_status_handler.py`, s. o.).

## Test Results
1428 passed, 0 failed (breiter thematischer Abschluss-Sweep, s. o. —
umfasst die 535 der reinen Menu-/RichMenu-Suite vollständig).

**Volle Repository-Suite (vom Nutzer selbst ausgeführt, CLAUDE.md §8.A):**
**3461 passed, 1 skipped, 11 subtests passed, 0 failed** (246,20 s).
Gegenprobe gegen die ARCH-023-Baseline (3361 passed, 1 skipped, 11
subtests passed): **+100 passed**, exakt deckungsgleich mit der Summe der
neu hinzugekommenen ARCH-024-Testdateien (family 24 + duplicates 5 +
navidrome 9 + stats 8 + admin_diagnostics 9 + usermgmt 9 + library 11 +
admin_operations 9 + download 10 + definitions 6 = 100) — keine
unerklärten Abweichungen, kein neuer Fehlschlag.

## Static Checks
`python3 -m compileall handlers/menu klassen utils handlers` fehlerfrei
nach jeder Phase. AST-basierte Dead-Import- und Zyklen-Analyse
durchgeführt (s. o.). Ein durch die Extraktion neu entstandener toter
Import (`InlineKeyboardButton` in `rich_menu_system.py`) entfernt;
6 bereits vor ARCH-024 tote Importe identifiziert, nicht angefasst
(außerhalb Scope).

## Regression Assessment
Keine Produktionsverhaltensänderung beabsichtigt oder gefunden. Drei
testinfrastrukturelle Kopplungen an alte Modulpfade/Konstruktions-
reihenfolgen wurden während der Extraktion sichtbar (s. P-2) und
korrigiert - alle drei waren Testartefakte (Patch-Ziele, Bare-Object-
Konstruktionsreihenfolge), keine Produktionslogik-Regressionen.

## Remaining Technical Debt

**Status (ARCH-025, 2026-09-13): alle drei ursprünglich hier gelisteten
Punkte sind CLOSED — siehe
`docs/MusicBot_ARCH-025_Command_Help_Content_Decomposition.md`, Abschnitt
„Technical Debt Fixes". Aus historischer Nachvollziehbarkeit bleibt die
ursprüngliche Formulierung unten erhalten, jeweils mit Schließungsvermerk:**

- ~~`stats.py`s `handle_stats_monthly_system`/`_yearly_system`/
  `_top_songs_system`/`_top_artists_system`/`_timeline_system` bleiben
  im Produktivbetrieb unerreichbar (überschrieben durch
  `RichMenuHandler._register_stats_handlers()`, s. P-1 Abschnitt 1.6) -
  1:1 mitverschoben, nicht bereinigt (außerhalb ARCH-024-Scope).~~
  **CLOSED (ARCH-025):** alle 5 Funktionen nach Verifikation entfernt,
  `definitions.py` setzt für diese 5 MenuItems kein `handler=` mehr,
  `register_handler()` verdrahtet weiterhin unverändert den echten,
  live genutzten Handler.
- ~~6 bereits vor ARCH-024 tote Importe in `rich_menu_system.py`
  (`Any`/`MenuState`/`Path`/`json`/`timedelta`/`CallbackQueryHandler`) -
  nicht angefasst.~~ **CLOSED (ARCH-025):** alle 6 nach erneuter
  Verifikation (0 Verwendungen inkl. Docstrings/Kommentaren/Patch-Zielen)
  entfernt.
- ~~`RichMenuHandler`s Onboarding-Cluster (~280 Zeilen) bleibt
  zusammen mit Composition/Lifecycle in einer Datei (P-5-Entscheidung).~~
  **CLOSED (ARCH-025):** Onboarding-Cluster (Command-Logik + Help-/
  Greeting-Content + Nutzerkontext-Auflösung) nach `handlers/menu/content/`
  extrahiert (`greeting.py`/`help.py`/`user_context.py`).
  `RichMenuHandler` behält nur noch dünne Delegatoren + die bewusst
  nicht extrahierte `handle_menu_command()`.

**Neu während ARCH-025 gefunden, bewusst nicht behoben (außerhalb des
ARCH-025-Scopes, siehe dortiges Dokument Abschnitt „Remaining Technical
Debt"):** `MenuState`/`Callable` sind bereits vor ARCH-025 tote Importe
in `handlers/menu/rich_menu_handler.py` - nicht angefasst (nicht Teil
der explizit benannten 6 `rich_menu_system.py`-Importe).

## Deferred Architecture Issues
Keine neuen. Die vier in ARCH-021/P-2 zurückgestellten Legacy-Findings
(`max_sessions` ohne Durchsetzung, `MenuSession.state`/`.data`/
`.message_id` ungenutzt) sind unverändert und weiterhin in
`docs/FINDINGS_INDEX.md` zu finden, nicht hier dupliziert.

## P0/P1/P2/P3 Findings
Keine P0/P1-Funde. P2/P3 (Remaining Technical Debt oben) - keine davon
sicherheits- oder korrektheitsrelevant, alle bereits vor ARCH-024
bestehend oder rein kosmetisch (Dead Imports).

## Recommendation for Next Architecture Block
Kein unmittelbarer Folgeblock zwingend erforderlich - die Menü-
Architektur ist jetzt in sich kohäsiv (Router/Definitions/Rendering/
Actions/Permissions/Session sauber getrennt, keine Zyklen). Bei Bedarf:
ein optionaler, kleiner ARCH-025 könnte die in „Remaining Technical
Debt" gelistete Cleanup-Arbeit (tote Imports, tote Stats-Menu-Definition-
Bindungen) bündeln - beides niedrige Priorität, kein Sicherheits- oder
Korrektheitsrisiko, daher keine Dringlichkeit.

---

## Commit-Status

Alle ARCH-024-Änderungen (P-1 bis P-4, P-5-Entscheidung) wurden über
Branch `arch-024/menu-file-decomposition`, Commit `617ca8d`
(+ Baseline-/Doku-Nachzug), als **PR #205** eingereicht und nach
erfolgreichem Closure-/Merge-Readiness-Audit gemergt (Basis `main` @
`2e1bf18`). Enthält: `handlers/menu/rich_menu_system.py`,
`handlers/menu/rich_menu_handler.py`, `handlers/menu/definitions.py`
(neu), `handlers/menu/rendering.py` (neu), `handlers/menu/actions/` (neu,
9 Domänen-Module + `_common.py` + `__init__.py`), 10 neue Testdateien,
4 Testinfrastruktur-Korrekturen (Patch-Ziele/Import-Pfade in
Bestandstests) sowie diese Dokumentation.
