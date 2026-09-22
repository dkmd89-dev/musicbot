# CC-AC-10D — Diagnostics & Monitoring API

**Datum:** 2026-09-22
**Auftrag:** freigegebene Master-Prompt `CC-AC-10.md`, Slice **CC-AC-10D**
("Diagnostics & Monitoring: Status + Logs + Logger + Error Administration").
Baut auf `docs/audits/CC-AC-10A_ADMIN_INVENTORY_ARCHITECTURE_CONTRACT_2026-09-22.md`
(Zeilen #13–#19) auf.

## Kernbefund: dieser Slice ist deutlich kleiner ausgefallen als geplant

Bei der Analyse wurde ein Architekturproblem entdeckt, das **drei der
vier** ursprünglich in diesem Slice vorgesehenen Bereiche betrifft:
Control Center läuft als **eigener Prozess** neben bot.py (CLAUDE.md §4).
Sowohl `handlers/enhanced_error_handler.py::ExceptionMonitor` (Error-
Statistiken) als auch die Modul-Statistiken hinter
`handlers/enhanced_logger_menu_handler.py` (`_module_loggers` aus
`logger.py`) leben **ausschließlich im Prozessspeicher des Bot-Prozesses**
— ein in Control Center instanzierter gleichnamiger Zähler wäre ein
komplett anderer, fast leerer Zähler des Control-Center-Prozesses selbst,
fälschlich als Bot-Zustand dargestellt.

Zusätzlich, spezifisch für Logger: `ModuleLoggerManager._load_module_configs()`
liest `data/module_logger_config.json` **nur einmal beim Bot-Start**, ohne
Neuladung zur Laufzeit (repoweit verifiziert — keine periodische
Reload-Stelle gefunden). Ein Level-/Modul-Wechsel über die Control-Center-
API würde die Datei zwar korrekt schreiben, aber im laufenden Bot-Prozess
**erst nach einem Neustart** wirken — die API-Antwort sähe "erfolgreich"
aus, obwohl der Bot unverändert weiterläuft.

**Nutzer-Entscheidung (2026-09-22):** Logger-Konfiguration UND
Error-Administration werden **komplett aus CC-AC-10D zurückgestellt** —
kein Endpunkt, der eine Live-Wirkung vortäuscht, wo keine existiert
(CC-AC-10.md §39: "keine Fake-Implementierung, die wie eine fertige
Funktion aussieht"). Beide sind jetzt gemeinsam als ein späterer,
eigenständiger Entscheidungspunkt in `docs/FINDINGS_INDEX.md` erfasst
(benötigt Persistenz-/IPC-Design oder einen Reload-Trigger-Mechanismus,
bevor eine sinnvolle Web-API entstehen kann).

## Implementiert

Nur **System-Status**, und dort bewusst nur der Teil, der echt und
prozessunabhängig ist: Host-Ressourcenmetriken (CPU/RAM/Disk über
`psutil`, identisch aus jedem Prozess derselben Maschine messbar) plus
ein echter, nicht simulierter `systemctl is-active bot`-Check. Bot-eigene
Laufzeitzähler (Operation-Counts, Uptime seit Bot-Start,
`process.cpu_percent()` des Bot-PID) sind bewusst **nicht** enthalten —
dieselbe Cross-Prozess-Falle wie oben, hier von vornherein vermieden statt
erst gebaut und dann entdeckt.

**System-Logs** (#14 der CC-AC-10A-Matrix) war bereits vor diesem Slice
vollständig erledigt (`GET /api/v1/logs`, CC-AC-10A-Befund: "funktional
reichhaltiger" als der Telegram-Pfad) — keine Änderung nötig.

## Application Layer

Neues `services/system_status.py` — bewusst **kein** Port von
`SystemMonitor` (siehe Kernbefund oben zur Vermischung von Host- und
Prozess-Metriken in dieser Klasse). Zwei reine Funktionen:
`get_host_resources()` (psutil, keine Historie/Zähler) und
`get_bot_service_active()` (subprocess `systemctl is-active`, kein
Seiteneffekt — analog zu `utils/bot_restart_trigger.py`, aber lesend).

## API

`GET /api/v1/admin/system/status` in `control_center/routers/
admin_operations.py` (bestehender Router aus CC-AC-10C erweitert, kein
neuer Router nötig). Read-only, kein CSRF-Schutz nötig (keine Mutation).

## Control Center UI

Noch offen — CC-AC-10F.

## Telegram

Unverändert.

## CLI

Nicht Teil dieses Slices.

## Tests

- `tests/test_system_status_service.py` (neu, 5 Tests): `get_host_resources()`
  gegen echtes `psutil` auf dieser Maschine (kein externer Dienst im Sinne
  von CLAUDE.md §8 — es ist genau die reale Metrik, die geliefert werden
  soll), `get_bot_service_active()` gegen gemocktes `subprocess.run()`
  (aktiv/inaktiv/systemctl fehlt/Timeout).
- `tests/test_control_center_admin_operations_api.py` (erweitert, +2
  Tests): HTTP-Ebene für `GET /system/status`.
- Gezielt: 141 passed (neue Tests + admin_operations + navidrome API +
  Layer-Boundary — 0 Regressionen).
- Thematisch (`-k "control_center or system_status"`): 542 passed. Die in
  CC-AC-10B/C dokumentierten 19 vorbestehenden UI-Template-Fehlschläge
  sind **zwischenzeitlich unabhängig vom Nutzer behoben worden**
  (`tests/test_control_center_ui.py`/`test_control_center_subpath_ui.py`:
  184/184 grün) — nicht Teil dieses Slices, hier nur zur Aktualisierung
  des Status vermerkt.
- Vollständige Suite: nicht selbst ausgeführt (CLAUDE.md §8.A) — dem
  Nutzer empfohlen.

## Security

Keine neue Angriffsfläche — reiner Read-Endpunkt, `systemctl is-active`
(kein `sudo`, keine Mutation, 5s-Timeout gegen Hänger).

## Entfernte Duplikation

Keine.

## Noch offen

- **Logger-Konfiguration + Error-Administration (zurückgestellt, s. o.):**
  neuer, eigenständiger Entscheidungspunkt — benötigt entweder (a)
  Persistenz der jeweiligen Statistiken auf Platte (geteilter Zustand
  zwischen Bot- und Control-Center-Prozess) oder (b) einen Reload-
  Trigger-Mechanismus für den Bot-Prozess (z. B. Signal/Datei-Watch),
  bevor eine nicht-täuschende Web-API sinnvoll ist.
- CC-AC-10E (Library Administration) — laut Nutzer-Entscheidung
  (2026-09-22) **entfällt**: Artist-Metadata-Reprocessing wird bewusst
  NICHT in die Control-Center-API integriert (bereits über CLI/Artist-
  Kontext nahezu vollständig abgedeckt), die restliche Library-
  Administration war laut CC-AC-10A bereits vollständig web-fähig. Damit
  ist dieser Bereich der CC-AC-10-Migration abgeschlossen, ohne einen
  eigenen Slice zu benötigen.
- CC-AC-10F (Control Center UI Parity).
- CC-AC-10G (Telegram Migration).

## Read/Write-Parität

System-Status: **1/1** (neue Funktion, war zuvor 🟠 "fragmentiert" laut
CC-AC-10A). System-Logs war bereits vorhanden. Logger (#15) und
Error-Administration (#16–19) bleiben **bewusst 0/5** — keine
Fake-Parität. CC-AC-10A-Gesamtstand: von 23/26 auf **24/26** (nur
System-Status kommt hinzu; Logger/Error-Admin zählen weiterhin als
offene Lücke, jetzt aber mit dokumentierter Begründung statt als reine
Zeitfrage).

**Nachtrag (2026-09-22, Nutzer-Entscheidung):** #25 Artist-Metadata-
Reprocessing wird bewusst NICHT in die Control-Center-API integriert
(CLI/Artist-Kontext bereits nahezu vollständig) — zählt damit wie
Bot-Neustart (alte 09-15-Einschätzung) oder Loudness-Normalisierung
nicht als offene Web-Parität-Lücke, sondern als bewusst ⚪ ausgeschlossen.
Effektiver Gesamtstand der real angestrebten Web-Parität damit **24/25**.

## Regression

Gezielte + thematische Tests grün, 0 durch diesen Slice verursachte
Fehlschläge. Volle Suite dem Nutzer zur Ausführung empfohlen.

---

## ADMIN PARITY MATRIX (Delta zu CC-AC-10A/B/C)

| Funktion | Telegram | CC API | CC UI | CLI | App Command/Query | Tests | Authorization | Status |
|---|---|---|---|---|---|---|---|---|
| System-Status (Host-Ressourcen + Bot-Service) | ✅ (anderer Scope, s. o.) | ✅ (GET) | ❌ | ❌ | ✅ `system_status.get_host_resources`/`get_bot_service_active` | ✅ | ADMIN | 🟢 API fertig (bewusst reduzierter Scope), UI offen (10F) |
| Logger konfigurieren | ✅ | ❌ (bewusst zurückgestellt) | ❌ | ❌ | ❌ | — | — | 🔴 zurückgestellt — Cross-Prozess-Blocker dokumentiert |
| Error Stats/Report/Recent/Reset | ✅ | ❌ (bewusst zurückgestellt) | ❌ | ❌ | ❌ | — | — | 🔴 zurückgestellt — Cross-Prozess-Blocker dokumentiert |

Alle übrigen Zeilen der CC-AC-10A/B/C-ADMIN-PARITY-MATRIX unverändert.
