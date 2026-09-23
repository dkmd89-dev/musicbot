# MusicBot Engineering Baseline v11

> **Status: 🟡 DRAFT (noch nicht eingefroren).**
>
> Laufender Zwischenstand seit dem v10-Freeze (2026-09-14). Hier werden
> pro ARCH-Phase/PR „ARCH Status", „Recent Major Changes" und Testzahlen
> mitgeschrieben (CLAUDE.md „Baseline-Pflege"). Die Abschnitte 4–6
> (Technical Debt / Security-Baseline / Architecture Freeze) bleiben
> Platzhalter bis zum v11-Freeze — bis dahin ist
> `docs/MusicBot_ENGINEERING_BASELINE_v10.md` der zitierbare eingefrorene
> Referenzpunkt, `docs/FINDINGS_INDEX.md` die laufend gepflegte
> Findings-Quelle.

---

## 1. Metadaten

| Feld | Wert |
|---|---|
| Baseline | v11 (DRAFT) |
| Vorgänger | `docs/MusicBot_ENGINEERING_BASELINE_v10.md` (Freeze 2026-09-14, 4250 passed / 1 skipped / 0 failed / 11 subtests passed) |
| Letzte vom Nutzer gemeldete Full-Suite-Zahl (aktuell, nach CC-AC-10A–D „Control Center Admin API Integration") | **5473 passed, 1 skipped, 11 subtests passed, 0 failed, 5 warnings** (305,85 s), 2026-09-22. +1163 gegenüber der zuletzt hier dokumentierten Zahl (4310, 2026-09-14) — deckt neben CC-AC-10A–D auch mehrere zwischenzeitliche, hier nicht einzeln nachgetragene CC-AC-Phasen (u. a. CC-AC-6/CC-AC-9) ab, deren jeweilige Einzelergebnisse in `docs/FINDINGS_INDEX.md` stehen (dort die laufend gepflegte Quelle, siehe Hinweis oben). Unverändertes Skip-/Subtest-Muster (1/11) seit v9 durchgehend. |
| Zuwachs seit letztem hier dokumentiertem Stand | +1163 passed (4310 → 5473), 0 failed |

---

## 2. ARCH Status seit v10-Freeze

| ARCH-Änderung | Commits | Ergebnis |
|---|---|---|
| **ARCH-033 „Telegram Level-2/Level-3 Repair (Pro-Artist)"** — letzte in ARCH-031 beschlossene, bis v10 noch offene Phase. Macht `METADATA_REPROCESSING` (L2) und `EXTERNAL_METADATA` (L3) über Telegram ausführbar, bewusst NUR pro Artist mit eigener Vorschau/Bestätigung (ADR-0003), nie als globaler Batch. Vier Phasen: (1) Service-Layer `execute_level2_repair()`/`execute_level3_repair()` in `repair_service.py` + Subprozess-Runner `run_level2_repair()`/`run_level3_repair()` in `doctor_runner.py`; (2) `group_candidates_by_artist()`/`ArtistCandidateSummary` in `planner.py`; (3) Telegram-Sub-Flow `l23rep:*` in `repair_musicbot_handler.py` inkl. Dispatcher-Verdrahtung; (4) dokumentierter, inaktiver Erweiterungspunkt für künftige COVER/LOUDNESS/DUPLICATE-Phasen (ARCH-034/035). Details: `docs/LIBRARY_REPAIR.md` §12, `docs/adr/0003` (IMPLEMENTED). | `64a7321`, `d4b1841`, `4e55801`, `d9436ba`, `f01ac9f` | 60 neue Tests, thematische Suite (`-k "repair or maintenance or menu or level or library_repair"`, 1305 Tests) grün, 0 Regressionen |

**Bewusste, nutzerbestätigte Abweichung von der ursprünglichen
Implementierungsvorgabe:** `execute_level2_repair()`/
`execute_level3_repair()` rufen `apply_level2()`/
`apply_external_metadata()` NICHT in-process über `asyncio.to_thread()`
auf (wie ursprünglich spezifiziert), sondern als eigenen Subprozess —
identisch zu `execute_safe_automatic_repair()`. Grund: `Enhanced-
MetadataProcessor` (`SingletonMixin`) wird bereits beim Bot-Start für
die Live-Download-Pipeline konstruiert; ein `asyncio.to_thread()`-Aufruf
hätte denselben Singleton potenziell gleichzeitig aus einem separaten
Thread heraus verwendet, während der Bot-Event-Loop weiterläuft — exakt
das Risiko, das den bestehenden Subprozess-Pfad von
`reprocessing_runner.py` ursprünglich begründet. Per `AskUserQuestion`
geklärt, Nutzer bestätigte „Subprozess statt in-process". Details:
`docs/adr/0003-telegram-level2-level3-per-artist-confirmation.md`,
Abschnitt „Implementierung".

| **CC-AC-10A–D „Control Center Admin API Integration"** — Migration der bestehenden, bisher rein Telegram-basierten Administration auf client-unabhängige Application-Layer-Funktionen + Control-Center-API, gemäß freigegebener Master-Prompt `CC-AC-10.md`. 10A: vollständiges Admin-Inventar (26 Funktionen) + Architecture Contract (`ActorContext`-Vorschlag andockt an bereits Telegram-freie `permissions.py`-Logik). 10B: User Management (Create/Update/Delete) über neuen `services/user_admin.py`. 10C: Backup/Bot-Neustart/Wartungsmodus/Navidrome-Scan über `services/backup_admin.py` + Direktnutzung bereits Telegram-freier Bausteine (`bot_maintenance.py`, `bot_restart_trigger.py`, `navidrome_scan_trigger.py`). 10D: nur System-Status (`services/system_status.py`) — Logger-Konfiguration und Error-Administration bewusst zurückgestellt (Cross-Prozess-Blocker: beide Daten leben nur im Bot-Prozess-Speicher, Control Center läuft separat; Logger-Configs werden zusätzlich nur einmal beim Bot-Start geladen). Telegram-Seite in allen vier Phasen bewusst unverändert (Migration darauf ist eigener, späterer Slice CC-AC-10G). Admin-Web-Parität laut CC-AC-10A-Matrix: von 12/26 auf 24/26 (Artist-Metadata-Reprocessing #25 laut Nutzer-Entscheidung dauerhaft ⚪ ausgeschlossen, keine offene Lücke). Details: `docs/audits/CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md` bis `CC-AC-10D_DIAGNOSTICS_MONITORING_API_2026-09-22.md`. | siehe Einzel-PRs dieser Session | 87 neue/erweiterte Tests über die vier Phasen (Application-Layer-Unit-Tests + HTTP-API-Tests), 0 Regressionen, thematische Suiten je Phase grün |
| **`control-center-navidrome` (Navidrome Full Integration im Control Center)** — Erweiterung der bisherigen Navidrome-Status-Anbindung (2026-09-15) zur vollständigen REST-Parität mit dem Telegram-`NavidromeMenuHandler`. 18 neue Endpunkte (Browse/Detail/Suche/Entdecken/Playlist-CRUD/Cover-Proxy) in `control_center/routers/navidrome.py` (20 gesamt), ~25 neue Pydantic-Schemas in `control_center/schemas/navidrome.py`, neuer `fetch_cover_art()`-Helper in `services/clients/navidrome_api.py` (Subsonic `getCoverArt` liefert Bytes, nicht JSON). Frontend: 7 Tabs, Modal-Stack-Navigation mit Breadcrumb, Cover-Art-Cards. Telegram-Seite bewusst unverändert; beide Consumer teilen weiterhin nur den `NavidromeAPI`-Adapter, keinen gemeinsamen Zustand, keine Business-Logik, keine wechselseitigen Imports. Details: `docs/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`. Volle Suite auf dem Branch: 5445 passed / 1 skipped / 6 warnings / 11 subtests passed (322,78 s, 2026-09-23). | siehe Branch `control-center-navidrome` | 20 Endpunkte (2 → 20), ~25 Schemas (2 → ~25), Frontend-Rewrite mit Modal-Stack; 0 Regressionen (bestehende Navidrome-Status-Tests unverändert grün) |
| **CC-LOGGER-L2 (Logger Read API)** — erster Schritt aus dem Phasenplan `logge.txt` (L1–L7). Reine Read-API für die Klasse-A-Logger-Funktionen (shared filesystem). Neuer Application-Layer `services/logger_admin.py` (Telegram-frei, FastAPI-frei), neuer Router `control_center/routers/logger.py` unter `/api/v1/admin/logger/*`, ADMIN-gated, 3 Endpunkte (Dateiliste/Statistiken/Detail). **Klasse B (Runtime-Control) bewusst DEFERRED** — L1-Analyse ergab prozesslokalen Bot-Zustand ohne Inbound-Kanal (einziger Mechanismus: `systemctl restart`). `module_logger_config.json` bewusst nicht exponiert — L1-Fund: `ModuleLoggerManager._load_module_configs()` wendet die JSON beim Bot-Start nicht an. Route-Reihenfolge kritisch (`/files/stats` vor `/files/{name}`). Limit-Grenzen server-seitig (Default 200, Min 1, Max 2000, HTTP 422 bei Verletzung — kein stilles Clamping; zusätzlich defensiv im App-Layer). Details: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`. Testergebnis: 86 passed (Log-Suiten) + 529 passed (`control_center`-Suite). | `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md` | 3 Endpunkte, 1 neuer Application Layer, 1 neuer Router, 2 neue Schemas; 0 Regressionen (`/api/v1/logs` unverändert) |
| **CC-LOGGER-L3 (Runtime-Control Architecture Decision)** — Analyse-Phase, kein Code. Architektur-Entscheidung für Logger-Runtime-Control im MusicBot. Kernbefund: es existiert heute KEIN Cross-Process-Runtime-Kanal (keine IPC, kein Socket, kein File-Watcher, kein Reload-Trigger); einziger Steuerungs-Mechanismus ist `systemctl restart bot`. Zusätzlich: `ModuleLoggerManager._load_module_configs()` wendet die JSON beim Bot-Start nicht an — persistente Config ist keine Runtime-Wahrheit. Empfohlener Pfad (verbindlich für L4–L6): Stufe 0 (Startup-Apply-Bugfix) → Stufe 1 (E2 Persistent Config über CC, Semantik „nächster Start“) → Stufe 2 (Runtime Snapshot, read-only Observability) → Stufe 3 (kontrollierter Apply/Restart mit Preflight + Rate-Limit). Stufe 4 (Unix-Socket Runtime Write) explizit DEFERRED, nur bei belegtem Bedarf. Verworfen: File-Watcher als dauerhafte Runtime-Infrastruktur, Localhost-HTTP, jeder unnötige neue IPC-Stack. Details: `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`. | `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md` | Docs-only, 0 Code-Änderungen, 0 Regressionen |
| **CC-LOGGER-L4 (Startup Apply + Persistent Logger Configuration)** — erster Umsetzungsschritt nach der L3-Entscheidung. Behebt den Startup-Apply-Bug in `ModuleLoggerManager._load_module_configs()` (JSON wurde geladen, aber nicht angewendet — persistierte Level/Handler waren fuer den laufenden Prozess wirkungslos). Neue Application-Layer-Funktionen in `services/logger_admin.py`: `read_logger_config()`, `validate_logger_config_patch()`, `update_logger_config()` (atomarer Write via .tmp+replace), `LoggerConfigError`. Neue Endpunkte unter `/api/v1/admin/logger/config`: `GET` (persistierte Konfiguration, ADMIN) + `PATCH` (merge-by-module + merge-by-field, ADMIN + CSRF, strikte Validierung). **Semantik ehrlich: „wirksam beim naechsten Bot-Start" — kein Runtime-Control, kein IPC, kein Restart.** Kein Schema-Bruch, keine neue Abhaengigkeit. **Verhaltensaenderung:** ab dem ersten Neustart nach dem Fix werden 40 Module je eine Log-Datei anlegen, 18 davon auf DEBUG. Details: `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`. | `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md` | 2 Endpunkte (GET/PATCH), 1 Bug-Fix, 47 neue Tests (12 Startup-Apply + 35 App-Layer-/HTTP-Config); 131/540/168 passed ueber die drei Regressionssuiten, 0 Regressionen |
| **CC-LOGGER-L5 (Runtime Snapshot + Controlled Apply/Restart)** — Stufe 2 + Stufe 3 aus der L3-Entscheidung. **Stufe 2 (Snapshot):** Bot schreibt beim erfolgreichen Startup `data/logger_runtime_snapshot.json` (atomic write, aus dem tatsaechlichen `logging.getLogger(name).level/handlers/disabled` — NICHT aus der Config). Neuer Endpoint `GET /api/v1/admin/logger/runtime-status` (ADMIN, read-only, 3 Zustaende: available/missing/corrupt, Semantik explizit "state_after_last_successful_bot_start"). **Stufe 3 (Apply):** Neuer Endpoint `POST /api/v1/admin/logger/apply` (ADMIN + CSRF + Rate-Limit 60s, Single-Flight via threading.Lock). Dreistufige Preflight-Semantik: `blocked` (Repair-Lock aktiv → HTTP 409, keine Mutation, kein Restart), `unverified` (Lock frei, aber Downloads/Backups unpruefbar → Restart mit strukturierter Warnung), `clear` (aktuell unerreichbar, da UNVERIFIABLE_ACTIVITY_CATEGORIES nicht leer). Restart ueber bestehenden `BotRestartTrigger.trigger_restart("bot")`, unveraendert. **Kein IPC, kein Socket, keine neue State-Registry.** Bugfix am globalen HTTPException-Handler in `control_center/app.py` (reicht jetzt `exc.headers` durch, betrifft `Retry-After` bei 429). Details: `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md`. | `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md` | 2 neue Endpunkte (runtime-status, apply), 2 neue App-Layer-Funktionen (write_runtime_snapshot/read_runtime_snapshot + evaluate_apply_preflight + LoggerApplyRateLimiter), 35 neue Tests; 103 + 552 + (Logger-Suite) passed, 0 Regressionen |
| **CC-LOGGER-L6 (Logger-Verwaltungs-UI)** — UI-only, keine Backend-Aenderung. Neue Seite `/logger` (eigenes Template + eigene JS-Datei, Stack-Pattern wie /statistics) mit vier Panels: Runtime-Status (KPI + Tabelle, Zustaende available/missing/corrupt), Persistierte Konfiguration (Tabelle, Semantik "wirksam beim naechsten Start"), Desired-vs-Actual-Diff (berechnet aus State, kein neuer API-Call), Apply (einziger POST /api/v1/admin/logger/apply-Call, Antwort bestimmt die Darstellung: unverified/clear/blocked/config_missing/429/403). Rate-Limit-Countdown aus Retry-After-Header. Wiederverwendet: common.js-Helper (apiUrl/checkAuth/_loadInto/_escapeHtml/showOnly), common.css-Klassen, Tabler-Komponenten. Keine Aenderung an common.js/common.css. Kein Config-PATCH-UI (bewusst ausserhalb L6). Details: `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md`. | `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md` | 1 neue Seite, 1 neue JS-Datei, 4 Panels, 6 neue UI-Tests; 218 + 560 passed, 0 Regressionen |
---

## 3. Recent Major Changes (seit v10-Freeze)

- **ARCH-033 Phase 1 (Service-Layer):** `LevelRepairResult`-Dataclass,
  `_execute_level_repair()` (gemeinsame Implementierung für L2/L3,
  Stale-Plan-Schutz identisch zu `execute_safe_automatic_repair()`,
  Verification-Scan nur bei mind. 1 Erfolg, Finding-Resolution nur für
  tatsächlich verifiziert behobene Findings). Während der Umsetzung ein
  echter Architektur-Konflikt entdeckt und per Rückfrage geklärt (siehe
  oben). Dabei zusätzlich ein Late-Binding-Bug gefunden und behoben: ein
  beim Import gebautes `{"l2": run_level2_repair, ...}`-Dict hätte
  `patch.object()` in Tests ignoriert und einen echten Subprozess gegen
  die Produktionslibrary gestartet (in einem Testlauf tatsächlich
  passiert, verifiziert folgenlos — kein Treffer, da der Test-Artist
  nicht real existierte — und sofort gefixt: Namens-Lookup über
  `globals()[...]` zur Aufrufzeit statt eines früh gebundenen Dicts).
  Dasselbe Prinzip wurde in Phase 3 für den Telegram-Handler
  übernommen.
- **ARCH-033 Phase 2 (Artist-Gruppierung):** `group_candidates_by_artist()`
  gruppiert einen `RepairPlan` nach Artist mit getrennten L2-/L3-Zählern,
  sortiert nach Gesamtzahl absteigend, dann alphabetisch, deterministisch.
- **ARCH-033 Phase 3 (Telegram-Flow):** neuer `l23rep:*`-Sub-Flow auf
  `RepairMusicBotHandler` (kein neuer Handler — L2/L3 sind wie
  SAFE_AUTOMATIC Findings-getrieben, ADR-0001): Artist-Liste
  (index-basiert, paginiert, pro Telegram-Session in `context.user_data`
  gecacht, um nicht bei jedem Button-Tap einen vollen Health-Scan
  auszulösen) → Aktionsauswahl → read-only Preview mit
  levelspezifischem Warnhinweis → explizite Bestätigung → Ausführung →
  Ergebnis. Neuer Button „🛠️ L2/L3-Reparaturen (nach Artist)" in den
  bestehenden Reparaturvorschlägen, sichtbar sobald L2/L3-Kandidaten
  vorhanden sind.
- **ARCH-033 Phase 4 (Registry-Vorbereitung):** rein dokumentarischer,
  inaktiver Erweiterungspunkt neben den `_L23REP_*`-Dicts in
  `repair_musicbot_handler.py` — zeigt, wie eine künftige ARCH-034/035
  COVER/LOUDNESS/DUPLICATE an denselben generischen Flow anschließen
  würde, ohne neuen Callback-Namensraum. Kein aktiver Code.
- Dokumentation: `docs/LIBRARY_REPAIR.md` §12 (neu), `docs/adr/0003`
  PROPOSED → IMPLEMENTED (inkl. der zwei dokumentierten Abweichungen —
  Subprozess statt in-process, sowie Verification-Scan library-weit statt
  artist-gescoped, da kein artist-gescopter Scan-Modus existiert und
  ADR-0004 einen zweiten Scan-Mechanismus ausschließt), `docs/FINDINGS_INDEX.md`
  (ARCH-033 CLOSED, neuer OPEN-Eintrag für ARCH-034/035, P3), `docs/INDEX.md`.
- **`control-center-navidrome` (Navidrome Full Integration):** der
  `NavidromeMenuHandler` des Telegram-Bots ist jetzt vollständig auch
  über die Web-API abgebildet — 20 Endpunkte in
  `control_center/routers/navidrome.py`, ~25 Pydantic-Schemas in
  `control_center/schemas/navidrome.py`, ein `fetch_cover_art()`-Helper
  in `services/clients/navidrome_api.py`. Bewusste Architektur-Abgrenzung:
  kein gemeinsamer Zustand, keine gemeinsame Business-Logik, keine
  wechselseitigen Imports zwischen Telegram-Handler und Control-Center-
  Router; beide Consumer teilen weiterhin denselben `NavidromeAPI`-Adapter
  (`services/clients/navidrome_api.py`), wie durch `ARCH-009 Phase 8`
  etabliert. Neue Frontend-Seite mit 7 Tabs und Modal-Stack-Navigation
  (Breadcrumb, Back-Button, ESC). Behebt einen konkreten Navigationsbug
  im Artist-Detail (Root-Cause: `d-none` auf dem Back-Button bei
  Stack-Tiefe 1 plus unsichtbarer `.btn-close` im Dark-Theme).
  Details: `docs/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md`.

- **CC-LOGGER-L2 (Logger Read API):** erster Schritt aus dem Phasenplan
  `logge.txt` (L1–L7). Neuer Application-Layer
  `services/logger_admin.py` (Telegram-frei, FastAPI-frei) + neuer
  Router `control_center/routers/logger.py` unter
  `/api/v1/admin/logger/*` (ADMIN-gated). Drei Endpunkte:
  `/files` (Dateiliste nach mtime), `/files/stats` (Aggregat),
  `/files/{name}` (Detail + Filter + Limit). Ruft ausschließlich
  `services/logs/reader.py` auf — kein zweiter Parser.

  **Klasse B (Runtime-Control: Modul-/Global-Level, Enable/Disable,
  Handler-Manipulation) bewusst DEFERRED.** L1-Analyse ergab:
  `_module_loggers`/`loggerDict`/`Logger.handlers` sind ausschließlich
  prozesslokal im Bot-Prozess; der einzige vorhandene
  Steuerungs-Mechanismus ist `systemctl restart` (voller Neustart,
  kein Skalpell). Kein Inbound-Kanal → keine ehrliche Write-API in L2
  möglich (`logge.txt` §4/§15: keine Runtime-Control vortäuschen).

  **`module_logger_config.json` bewusst nicht exponiert** — L1-Fund:
  `ModuleLoggerManager._load_module_configs()` liest die JSON beim
  Bot-Start, ruft aber `_apply_module_config()` **nicht** auf; die
  Datei ist keine Runtime-Wahrheit. Ein Read-Endpoint würde eine
  Genauigkeit vortäuschen, die die Datenquelle nicht hat.

  **Limit-Grenzen server-seitig** — Default 200, Min 1, Max 2000.
  FastAPI lehnt Werte außerhalb mit HTTP 422 ab (kein stilles
  Clamping); `logger_admin.get_log_file()` validiert denselben Bereich
  defensiv ein zweites Mal, damit direkte Aufrufer ohne HTTP-Durchlauf
  nicht umgangen werden.

  **Route-Reihenfolge kritisch** — `/files/stats` vor `/files/{name}`
  (Starlette-Matching in Deklarations-Reihenfolge).

  Tests: 86 passed (4 Log-Suiten: `test_logger_admin.py`,
  `test_control_center_logger_api.py`, `test_logs_reader.py`,
  `test_logger_menu_path_traversal.py`) + 529 passed (`pytest tests/
  -k control_center`). Keine Telegram-Änderung.
  Details: `docs/audits/CC_LOGGER_L2_READ_API_2026-09-23.md`.
---

## 4. Technical Debt — Snapshot

*(Platzhalter — wird beim v11-Freeze befüllt. Laufender Stand aller
offenen/zurückgestellten Punkte: `docs/FINDINGS_INDEX.md`.)*

---

## 5. Security-Baseline

*(Platzhalter — wird beim v11-Freeze befüllt.)*

---

## 6. Architecture Freeze

*(Platzhalter — Freeze-Gate-Audit noch nicht durchgeführt, kein
GO/NO-GO-Verdikt für v11.)*

- **CC-LOGGER-L3 (Runtime-Control Architecture Decision):** reine
  Analyse-Phase, kein Code. Erstes echtes Architecture Decision Record
  für das Control Center. Zentrale Befunde: (1) es existiert heute
  keine Runtime-Control-Infrastruktur für den Bot (keine IPC, kein
  Socket, kein File-Watcher, kein Reload-Trigger); (2) die persistente
  Logger-Config (`data/module_logger_config.json`) ist keine
  Runtime-Wahrheit, weil `_load_module_configs()` die Werte beim
  Bot-Start nicht über `_apply_module_config()` anwendet.

  Empfohlener Pfad (verbindlich für L4–L6): **Stufe 0** (Startup-Apply-
  Bugfix) → **Stufe 1** (E2: CC darf persistente Config schreiben,
  Semantik „wirksam beim nächsten Bot-Start") → **Stufe 2** (Runtime
  Snapshot, read-only Observability) → **Stufe 3** (kontrollierter
  Apply/Restart mit Preflight + Rate-Limit). **Stufe 4** (Unix-Socket
  Runtime Write) explizit deferred — nur bei belegtem Bedarf, sonst
  kein dauerhafter IPC-Kanal.

  Verworfen: File-Watcher als dauerhafte Runtime-Infrastruktur
  (Race-Risiko, kein Rückkanal), Localhost-HTTP-Control-Server
  (überdimensioniert), jeder unnötige neue IPC-Stack.

  DoD erfüllt (alle Punkte aus `logge.txt` §16 abgehakt). Keine
  Runtime-Implementierung, keine Telegram-Migration, keine UI-Änderung,
  keine L2-Endpunkt-Änderung. Details:
  `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`.

- **CC-LOGGER-L4 (Startup Apply + Persistent Logger Configuration):**
  erster Umsetzungsschritt nach der L3-Entscheidung. Zwei Bausteine:

  **Stufe 0 — Startup-Apply-Bugfix.** `ModuleLoggerManager._load_module_configs()`
  liest die persistente Konfiguration jetzt und wendet sie per
  `_apply_module_config()` auf die realen Logger an. Vor dem Fix galten
  nach jedem Bot-Neustart die Code-Defaults aus `logger.py` — die
  persistierte JSON war wirkungslos für den laufenden Prozess.

  **Stufe 1 — Persistent Config API.** Neue Application-Layer-Funktionen
  in `services/logger_admin.py` (`read_logger_config()`,
  `validate_logger_config_patch()`, `update_logger_config()` mit
  atomarem Write über `.tmp`+`replace()`, `LoggerConfigError` mit
  stabilem `code`). Zwei Endpunkte unter
  `/api/v1/admin/logger/config`:
  - `GET` — persistierte Konfiguration, ADMIN, read-only.
  - `PATCH` — Merge-by-module + merge-by-field, ADMIN + CSRF,
    strikte Validierung (unbekannte Module → 422, unbekannte Felder
    → 422, invalide Level → 422, Nicht-Bool → 422, fehlende Config
    → 409). Kein stilles Schema-Anlegen.

  **Ehrliche Semantik ohne Fake-Live:** die PATCH-Response bestätigt
  ausschließlich „gespeichert, wirksam beim nächsten Bot-Start". Der
  laufende Bot-Prozess wird nicht angefasst — zwei Tests pinnen das
  explizit (App-Layer-Level und HTTP-Level).

  **Verhaltensänderung (quantifiziert im Audit):** ab dem ersten
  Neustart nach dem Fix legen 40 Module je eine Log-Datei an, 18 davon
  schreiben tatsächlich auf DEBUG. Gewollt, im Audit-Dokument
  dokumentiert, kein verstecktes Verhalten.

  **Bewusst NICHT implementiert:** kein Runtime-Snapshot (Stufe 2),
  kein kontrollierter Restart (Stufe 3), kein IPC, keine Socket, keine
  UI, keine Telegram-Migration. Die bleiben L5/L6/L7.

  **Keine Schema-Änderung**, keine neue Abhängigkeit, keine Migration.
  Details:
  `docs/audits/CC-LOGGER-L4_STARTUP_CONFIG_API_2026-09-23.md`.


- **CC-LOGGER-L5 (Runtime Snapshot + Controlled Apply/Restart):**
  Stufe 2 + Stufe 3 aus der L3-Architekturentscheidung.

  **Stufe 2 — Runtime Snapshot.** Bot schreibt beim erfolgreichen
  Startup `data/logger_runtime_snapshot.json` (atomic write via
  `Path.replace`). Der Snapshot wird aus dem tatsaechlichen
  Python-Logger-Zustand gelesen (`logging.getLogger(name).level`,
  `.handlers`, `.disabled`) — NICHT aus der persistenten Config.
  Neuer Endpoint `GET /api/v1/admin/logger/runtime-status` (ADMIN,
  read-only) mit drei Response-Zustaenden: `available` / `missing` /
  `corrupt`. Semantik explizit: `state_after_last_successful_bot_start`
  — kein Live-State, kein Fake-State bei fehlendem Snapshot.

  **Stufe 3 — Controlled Apply/Restart.** Neuer Endpoint
  `POST /api/v1/admin/logger/apply` (ADMIN + CSRF + Rate-Limit).
  Dreistufige Preflight-Semantik:

  - `blocked` — Repair-Lock aktiv → HTTP 409, keine Config-Mutation,
    kein Restart.
  - `unverified` — Lock frei, aber Downloads/Backups sind aus dem
    CC-Prozess strukturell nicht pruefbar → Restart mit strukturierter
    Warnung (`preflight.unverified=["downloads", "backups"]`).
  - `clear` — aktuell nicht erreichbar, da
    `UNVERIFIABLE_ACTIVITY_CATEGORIES` nicht leer ist. Als Status
    definiert, damit Clients sauber differenzieren koennen.

  Restart ueber den bestehenden `BotRestartTrigger.trigger_restart("bot")`
  — unveraendert, fest verdrahteter Service-Name, Response-before-restart
  via `call_later(2.0, ...)` wie `/system/restart`.

  **Rate-Limit:** `LoggerApplyRateLimiter` (in `app.state`, pro
  `create_app()`-Instanz isoliert), 60 s, mit Single-Flight-Semantik
  ueber `threading.Lock` (20 parallele Threads → genau 1 Acquire).

  **Kein IPC, kein Socket, keine neue State-Registry.** Der Preflight
  nutzt ausschliesslich die bestehende, cross-process sichtbare
  `library_repair.lock`.

  **Bugfix am bestehenden globalen HTTPException-Handler**
  (`control_center/app.py`): reicht jetzt `exc.headers` durch. Betrifft
  konkret den neuen `Retry-After`-Header bei HTTP 429, war aber ein
  bestehender Bug (Header wurden bei JEDER HTTPException verworfen).
  Eine Zeile, keine Verhaltensaenderung fuer andere Endpunkte.

  **Bekannte Einschraenkungen** (im Audit-Dokument als §13/§14):
  Race-Fenster zwischen Preflight und Restart (~2s), Stale-Lock nach
  Crash, Restart-Erfolg nicht verifizierbar (BotRestartTrigger
  schluckt Exceptions), laufende Downloads/Backups unpruefbar.
  Alle als Findings dokumentiert, nicht in L5 gefixt.

  Tests: 103 passed (L5-Suiten + Logger-Suiten) + 552 passed
  (`pytest -k control_center`). Details:
  `docs/audits/CC-LOGGER-L5_RUNTIME_SNAPSHOT_CONTROLLED_APPLY_2026-09-23.md`.


- **CC-LOGGER-L6 (Logger-Verwaltungs-UI):** reine UI-Arbeit auf den
  bestehenden L4/L5-Endpunkten. Neue Seite `/logger` (Template +
  eigene JS-Datei, Stack-Pattern analog `statistics.html`) mit vier
  Panels:

  1. **Runtime-Status** — KPI-Kacheln (Root-Level, Modul-Anzahl, letzter
     Startup) + Tabelle aus `GET /runtime-status`, Zustaende
     available/missing/corrupt klar unterschieden. Semantik im UI
     explizit: "Zustand nach letztem Bot-Start".
  2. **Persistierte Konfiguration** — Tabelle aus `GET /config`,
     Semantik "wirksam beim naechsten Bot-Start".
  3. **Desired vs. Actual** — Diff aus den beiden Panels berechnet,
     kein neuer API-Call. Sonderfaelle (nur in Config / nur im Snapshot /
     kein Snapshot) ehrlich benannt. Kein Fake-Diff.
  4. **Apply / Controlled Restart** — einziger Call `POST /apply`,
     Antwort bestimmt Darstellung: unverified (gelb, unverifizierbare
     Kategorien explizit), clear (gruen), blocked (rot, kein Restart),
     config_missing (rot), 429 (orange mit Live-Countdown aus
     `Retry-After`), 403/401 wie bestehende Patterns.

  **Wiederverwendung:** `common.js`-Helper
  (`apiUrl/checkAuth/_loadInto/_escapeHtml/showOnly`),
  `common.css`-Klassen, Tabler-Komponenten. Keine Aenderung an
  `common.js`, `common.css` oder anderen Page-Dateien.
  Kein Config-PATCH-UI — der PATCH-Endpoint bleibt bewusst nicht
  exponiert.

  Tests: 6 neue UI-Tests in `tests/test_control_center_ui.py`.
  Regressionsergebnis: 218 + 560 passed. Details:
  `docs/audits/CC-LOGGER-L6_LOGGER_UI_2026-09-23.md`.


