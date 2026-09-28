# Error-Administration — Architekturanalyse (CC-AC-10D Folgephase)

**Datum:** 2026-09-27 · **Typ:** reine Analyse, **kein Code** ·
**Status:** 🟢 ENTSCHIEDEN + UMGESETZT (2026-09-28: Variante E1, siehe Abschnitt 6)

Bezug: offenes Finding „CC-AC-10D, Error-Administration ohne Web-API,
Cross-Prozess-Blocker" (`docs/FINDINGS_INDEX.md`), Nutzer-Entscheidung
2026-09-22 („keine Web-API, die Live-Wirkung vortäuscht",
`docs/audits/CC-AC-10D_DIAGNOSTICS_MONITORING_API_2026-09-22.md`),
Logger-Präzedenz `docs/audits/CC-LOGGER-L3_RUNTIME_CONTROL_ARCHITECTURE_DECISION_2026-09-23.md`.

---

## 1. Ist-Zustand (gegen den Code verifiziert)

### 1.1 Prozesse

| Prozess | systemd-Unit | Start | Restart | Zustand |
|---|---|---|---|---|
| Bot | `bot.service` (`python bot.py`, User `robin`, WD `/mnt/128ssd/musicbot`) | beim Boot | `Restart=always`, 10 s | hält den gesamten Error-State im RAM |
| Control Center | `control-center.service` (`uvicorn control_center.app:app`, 127.0.0.1:8420, gleicher User/WD) | beim Boot | `Restart=on-failure`, 3 s | eigener Prozess, eigene Python-Objekte |

Beide Prozesse teilen **nur das Dateisystem** (`data/`, `logs/`). Es gibt
keinen IPC-Kanal (kein Socket, kein Localhost-Port des Bots, kein
File-Watcher) — repoweit verifiziert, identisch zum L3-Befund. Der einzige
Steuerweg CC → Bot ist `BotRestartTrigger.trigger_restart("bot")`
(`sudo systemctl restart`).

### 1.2 Wo der Error-State entsteht und lebt

| Zustand | Ort | Entsteht durch | Lebensdauer |
|---|---|---|---|
| `ExceptionMonitor.exception_history` (deque, max 1000) | `handlers/enhanced_error_handler.py` | `record_exception()` aus `EnhancedErrorHandler.handle_exception()` und den `handle_*_error()`-/Decorator-Pfaden | RAM des Bot-Prozesses |
| `ExceptionMonitor.stats` (Zähler nach Kategorie/Typ/Modul/Severity/Stunde/Pattern) | dito | dito | RAM |
| `EnhancedErrorHandler.performance_stats`, `recovery_attempts` | dito | `_update_performance_stats()`, `_attempt_recovery()` | RAM |
| `DebugTracker.sessions`/`session_history` | dito | pro behandelter Exception | RAM, `cleanup_old_data()` periodisch in `bot.py` |
| Log-Ausgabe `EXCEPTION DETECTED [EXC_…]` inkl. Typ/Message/Kontext/Stacktrace | `logs/bot.log` (+ Modul-Logs) | `_log_exception_details()` | **Dateisystem, prozessübergreifend lesbar**, Rotation 2 MB × 5 |

Konstruktion: genau eine `EnhancedErrorHandler`-Instanz in `bot.py`, eine
`ErrorHandlerAdminInterface`-Instanz (Telegram) nur bei konfigurierten
`ADMIN_USER_IDS`. Das Control Center konstruiert keinen Error-Handler.

### 1.3 Heutige Administrationsfunktionen (nur Telegram)

| Aktion | Einstieg | liest/schreibt | Prozessbezug |
|---|---|---|---|
| Statistik (`/error_stats`, `erradmin:show_stats`) | `handle_error_stats_command()` | liest `stats` | Bot-RAM |
| Health-Report (`/error_report`, `erradmin:show_report`) | `create_health_report()` | liest `stats` + `performance_stats` | Bot-RAM |
| Letzte Fehler (`/recent_errors`, `erradmin:show_recent`) | `get_recent_exceptions_summary()` | liest `exception_history` | Bot-RAM |
| Statistik zurücksetzen (`/reset_error_stats` → `erradmin:reset_confirm`/`_execute`) | `reset_statistics()` | **schreibt** `stats`/`performance_stats`/`recovery_attempts` | Bot-RAM |

Nebenbeobachtungen (nicht Gegenstand dieser Phase, nur dokumentiert):
`reset_statistics()` leert `exception_history` **nicht** („Letzte Fehler"
zeigt nach einem Reset weiter alte Einträge) und ersetzt
`ExceptionMonitor.stats` ohne `_lock`.

---

## 2. Antworten auf die neun Leitfragen

1. **Wo entsteht der Error-State?** Ausschließlich im Bot-Prozess, in
   `EnhancedErrorHandler.handle_exception()` → `ExceptionMonitor.record_exception()`
   (plus Performance-/Recovery-Zähler).
2. **Wo lebt er aktuell?** Im RAM des Bot-Prozesses. Einzige persistente
   Spur: die Log-Blöcke `EXCEPTION DETECTED [EXC_…]` in `logs/bot.log`.
3. **Was ist prozess-lokal?** Alles aus 1.2 außer den Logzeilen. Ein
   Bot-Neustart setzt Historie und Zähler implizit auf null.
4. **Was muss im Control Center sichtbar sein?** Mindestens: Gesamtzahl,
   Verteilung nach Kategorie/Severity/Modul, die letzten N Fehler (ID,
   Zeitpunkt, Typ, Kategorie, Severity, Modul/Operation, gekürzte
   Message), Recovery-Rate — jeweils **mit Zeitstempel des Datenstands**
   und Bot-Startzeitpunkt, damit kein Live-Zustand vorgetäuscht wird.
   Teilweise bereits heute erfüllt: der CC-Log-Viewer (`/api/v1/logs`,
   Filter `level=ERROR`) zeigt die Exception-Blöcke aus `bot.log` mit
   Secret-Redaction (`services/logs/reader.py::_redact_secrets()`).
5. **Was muss im Control Center ausführbar sein?** Fachlich nur „Statistik
   zurücksetzen". Alles andere ist lesend.
6. **Welche Aktionen verändern Bot-Prozesszustand?** Nur der Reset (und
   implizit jeder Neustart).
7. **Welche Aktionen benötigen Persistenz?** Alle Lese-Ansichten, sobald
   sie aus einem anderen Prozess erfolgen sollen: der Bot muss seinen
   Zustand auf Platte schreiben (heute tut er das nicht).
8. **Welche Aktionen benötigen IPC?** Nur ein *sofort wirksamer* Reset
   aus dem Control Center. Lesen braucht kein IPC, wenn der Bot
   periodisch persistiert.
9. **Welche Aktionen können über Restart + Persistenz gelöst werden?**
   Der Reset: ein Bot-Neustart (bereits heute über
   `POST /api/v1/admin/system/restart` erreichbar) setzt den RAM-State
   ohnehin zurück; ein vom Bot geschriebener Snapshot würde beim
   nächsten Schreibzyklus nach dem Start mit leeren Zählern überschrieben.
   Nachteil: Neustart unterbricht laufende Downloads/Reparaturen — für
   eine reine Statistik-Nullung unverhältnismäßig.

---

## 3. Architekturvarianten

Bewertung: ✅ gut · 🟡 akzeptabel/mit Auflagen · ❌ schlecht.

### A — Persistenter Error-State, CC liest (und ggf. schreibt) Persistenz

Bot schreibt periodisch (z. B. alle 60 s, zusätzlich beim Shutdown)
atomar `data/error_monitor_snapshot.json` (Zähler + letzte N bereinigte
Einträge + `generated_at` + `bot_started_at`); CC liest read-only.
Vorbild: L5-Runtime-Snapshot (`data/logger_runtime_snapshot.json`),
atomarer Write nach INV-02.

| Kriterium | Bewertung |
|---|---|
| Sicherheit | 🟡 Kein neuer Angriffskanal. Auflage: Snapshot darf keine Nutzer-Identifikatoren/Message-Texte/Callback-Daten aus `_extract_update_info()` enthalten und muss dieselbe Secret-Redaction wie der Log-Viewer durchlaufen. |
| Komplexität | ✅ gering (ein Writer, ein Reader, bekanntes Muster) |
| Prozessgrenzen | ✅ sauber: Bot einziger Writer, CC nur Reader |
| Restart-Verhalten | ✅ definiert: nach Neustart leerer Stand mit neuem `bot_started_at`; Snapshot eines abgestürzten Bots bleibt als letzter Stand lesbar (Staleness über `generated_at` sichtbar) |
| Race Conditions | ✅ keine Lese-/Schreib-Races (atomarer Replace); Schreib-Races nur, wenn CC ebenfalls schreibt — deshalb **CC darf nicht schreiben** |
| Failure Modes | 🟡 Datenstand bis zu einem Intervall alt; fehlende/korrupte Datei → CC zeigt „kein Snapshot" (Zustände wie L5: available/missing/corrupt) |
| Testbarkeit | ✅ reine Funktionen (Serialisierung, Redaction, Laden) |
| Wartbarkeit | ✅ |
| Passung MusicBot | ✅ exakt das L3/L5-Muster „ehrlicher Datenstand statt Fake-Live" |
| Aufwand | ✅ klein |

**Wichtige Gegenprobe (neu verifiziert, siehe Abschnitt 5):** Die
Schreibrichtung CC → Datei → Bot funktioniert nur, wenn der Bot die Datei
bei **jedem** Zugriff neu liest. Der bestehende Wartungsmodus zeigt, was
passiert, wenn nicht: Der Bot hält eine beim Start geladene Instanz, ein
CC-Schalter ändert nur die Datei. „CC schreibt Persistenz" ist daher für
den Reset nur mit einem Reload-Mechanismus auf Bot-Seite korrekt — das
ist dann Variante D.

### B — AF_UNIX-IPC (Bot lauscht auf Unix-Socket)

| Kriterium | Bewertung |
|---|---|
| Sicherheit | 🟡 Socket-Dateirechte (0600, gleicher User) + eigenes Protokoll/Validierung nötig; neue Angriffsfläche im Bot-Prozess |
| Komplexität | ❌ neuer Server im Bot-Event-Loop, Protokoll, Timeouts, Versionierung |
| Prozessgrenzen | ✅ echte Live-Abfrage und sofortiger Reset |
| Restart-Verhalten | 🟡 Socket-Datei aufräumen, CC muss „Bot nicht erreichbar" sauber behandeln |
| Race Conditions | 🟡 Handler läuft im Bot-Loop → Zugriff auf `ExceptionMonitor` unter dessen Lock, Reset-Pfad muss gelockt werden (heute nicht) |
| Failure Modes | ❌ hängender Bot-Loop blockiert auch die Diagnose; genau im Fehlerfall ist der Kanal am unzuverlässigsten |
| Testbarkeit | 🟡 Integrationstests mit echtem Socket |
| Wartbarkeit | ❌ erster und einziger IPC-Stack im Projekt nur für Statistiken |
| Passung MusicBot | ❌ L3 hat genau diese Stufe („Stufe 4, Unix-Socket") ausdrücklich zurückgestellt — nur bei belegtem Bedarf |
| Aufwand | ❌ groß |

### C — Localhost-HTTP zwischen CC und Bot

Wie B, zusätzlich Port-Belegung, zweiter Webserver im Bot-Prozess,
Authentisierung zwischen den Prozessen. L3 hat „Localhost-HTTP-Control-
Server" ausdrücklich **verworfen** (überdimensioniert). Bewertung
durchgehend schlechter als B; ❌.

### D — Gemeinsame Job-/State-Persistenz (Request-Datei, Bot pollt)

CC schreibt eine Anforderung (z. B. `data/error_admin_requests/<uuid>.json`
mit `action: "reset"`, Requester, Zeitstempel); der Bot prüft periodisch
(z. B. in dem Loop, der auch den Snapshot schreibt), führt aus, quittiert
per Ergebnisdatei/Snapshot-Feld `last_reset`.

| Kriterium | Bewertung |
|---|---|
| Sicherheit | 🟡 Dateirechte + strikte Whitelist der Aktionen; Autorisierung passiert im CC (bestehende ADMIN-Gates + CSRF), der Bot vertraut dem Dateisystem |
| Komplexität | 🟡 mittel: Queue-Semantik, Idempotenz, Quittierung, Aufräumen |
| Prozessgrenzen | ✅ bleibt bei „nur Dateisystem" |
| Restart-Verhalten | 🟡 offene Requests nach Neustart: verwerfen (Reset ist nach Neustart ohnehin erfüllt) |
| Race Conditions | 🟡 Doppel-Verarbeitung vermeiden (atomares Umbenennen claimed/done) |
| Failure Modes | 🟡 Verzögerung bis zum nächsten Poll; Bot tot → Request bleibt liegen, CC muss „ausstehend" anzeigen |
| Testbarkeit | ✅ deterministisch mit tmp-Verzeichnis |
| Wartbarkeit | 🟡 neues, aber einfaches Muster — wäre projektweit wiederverwendbar (auch für den Wartungsmodus-Befund, Logger-Global-Level, Logger-Introspektion) |
| Passung MusicBot | 🟡 kein Präzedenzfall; L3 hat File-Watcher als *dauerhafte* Runtime-Infrastruktur verworfen — ein Poll im ohnehin vorhandenen Snapshot-Takt ist schwächer, aber verwandt |
| Aufwand | 🟡 mittel |

### E — Hybrid

**E1 = A + Reset bleibt Telegram-only.** CC zeigt den bot-geschriebenen
Snapshot read-only mit Datenstand; Reset weiterhin über Telegram (oder
bewusst über den vorhandenen Neustart). Kein neuer Schreibpfad.

**E2 = A + D nur für Reset.** Wie E1, zusätzlich Reset aus dem CC über
eine Request-Datei, die der Bot im Snapshot-Takt abarbeitet.

| Kriterium | E1 | E2 |
|---|---|---|
| Sicherheit | ✅ | 🟡 |
| Komplexität | ✅ | 🟡 |
| Live-Ehrlichkeit | ✅ (Datenstand sichtbar) | ✅ (Reset „ausstehend" → „ausgeführt um …") |
| Aufwand | ✅ klein | 🟡 mittel |
| CC-Parität | 🟡 nur lesend | ✅ vollständig |

---

## 4. Empfehlung (nicht entschieden)

**E1** als erster Schritt: erfüllt die Leitfragen 4–7 vollständig ohne
neuen Schreib- oder IPC-Kanal, folgt exakt dem L3/L5-Muster und lässt
E2 (bzw. D) als additive Erweiterung offen, sobald ein CC-Reset
tatsächlich gebraucht wird. B/C werden nicht empfohlen (L3-Entscheidung,
Aufwand/Risiko in keinem Verhältnis zu einer Statistik-Ansicht).

Offene Entscheidungen für den Nutzer:

1. Variante: **E1** (empfohlen) / E2 / andere.
2. Snapshot-Intervall (Vorschlag 60 s) und Umfang der Historie im
   Snapshot (Vorschlag: letzte 50 Einträge statt 1000).
3. Datenschutz-Umfang: Vorschlag ohne `user`/`chat`/`text_preview`/
   Callback-Daten, Message gekürzt und redigiert, ohne Stacktrace
   (Stacktraces bleiben im bereits redigierten Log-Viewer).
4. Soll ein Reset künftig auch `exception_history` leeren (heutiges
   Telegram-Verhalten tut es nicht, siehe 1.3)?

Bis zur Entscheidung: **keine Implementierung** (Auftrag Phase 5).

---

## 5. Nebenbefund dieser Analyse (neues Finding)

**Wartungsmodus aus dem Control Center wirkt nicht auf den laufenden
Bot.** `services/bot_maintenance.py::MaintenanceModeStore` lädt den
Zustand nur im Konstruktor (`self._state = self._load()`), `is_active()`
liest den gecachten Wert. Der Bot hält eine langlebige Instanz
(`handlers/menu/rich_menu_handler.py:170`), das Control Center erzeugt
pro Request eine neue (`control_center/routers/admin_operations.py::_maintenance_store()`).
Reproduziert (zwei Instanzen auf derselben Datei, CC-Instanz setzt
`active=True`): frische Instanz liest `True`, die langlebige Bot-Instanz
weiter `False`. Folge: `POST /api/v1/admin/maintenance` meldet
„aktiv", `GET` zeigt „aktiv", der laufende Bot lässt aber weiter alle
Nutzer durch — bis zum nächsten Bot-Neustart. Umgekehrte Richtung
(Telegram schaltet, CC liest) funktioniert. Genau das Anti-Muster, vor
dem Abschnitt 3/A warnt. Als eigenes Finding in `docs/FINDINGS_INDEX.md`
erfasst (P2), in dieser Analysephase bewusst **nicht** behoben.

---

## 6. Entscheidung und Umsetzung (2026-09-28)

**Nutzerentscheidung:** Variante **E1** (Web-Paritäts-Audit, Entscheidung 1). Offene Punkte aus Abschnitt 4: Intervall **60 s**, Historie **50 Einträge**, Datenschutz **streng** (ohne `user`/`chat`/`text_preview`/Callback-Daten, ohne Stacktrace, Message gekürzt + redigiert). Punkt 4 (Reset leert `exception_history`) entfällt, da der Reset unter E1 Telegram-only bleibt — die dortige Eigenheit ist unverändert.

**Umsetzung:**
- `services/bot_runtime_snapshot.py`: `write_bot_runtime_snapshot()` (atomar, Fehler nicht propagiert), `read_bot_runtime_snapshot()` (available/stale/missing/corrupt, stale ab 3 Intervallen), `sanitize_exception_record()` als einzige Stelle, über die Fehler-Einträge in den Snapshot gelangen.
- `handlers/enhanced_error_handler.py::EnhancedErrorHandler.export_snapshot_section()` (liest nur), `services/duplicate/detector.py::DuplicateDetector.snapshot_section()` (Sitzungszähler).
- `bot.py`: `_periodic_runtime_snapshot()` schreibt sofort nach dem Start, dann alle 60 s, letzter Stand beim Shutdown; jeder Abschnitt einzeln abgesichert.
- Control Center: `GET /api/v1/admin/runtime-snapshot` (ADMIN, kein Schreib-Endpunkt), Karte „Fehlerstatistik (Bot)" mit Datenstand, Sitzungszähler in der Duplikat-Karte.

Nicht umgesetzt (bewusst, E1): Reset aus dem Web (wäre E2), Logger-Zähler und Live-Anzeige Telegram-initiierter Downloads (später additiv als weitere Snapshot-Abschnitte möglich).

