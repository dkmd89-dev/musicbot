# ARCH-009 Folgeanalyse — Endgültiger Zielort von `NavidromeScanTrigger`

Reine Analysephase. **Keine Codeänderung, keine Verschiebung, keine
Löschung, keine Umbenennung, keine DI-Änderung, keine Test-/Import-
änderung, keine automatische Umsetzung.** Aufbauend auf ARCH-009 Phase 9
(Umsetzung A, abgeschlossen und gemerged: `execute_scan()` und
`api/navidrome_api.py` vollständig entfernt).

Klärt ausschließlich: **Wo gehört `NavidromeScanTrigger` architektonisch
endgültig hin?**

---

## 1. Vollständige Analyse von `NavidromeScanTrigger`

Vollständig gelesen: `api/navidrome_scan_trigger.py` (145 Zeilen).

### Fachliche Verantwortung

Führt einen konfigurierten Navidrome-Scan aus, indem ein Docker-Befehl
(`docker exec navidrome /app/navidrome scan --full`, aus
`Config.NAVIDROME_SCAN_COMMAND`) als lokaler Host-Subprocess gestartet
wird, und liefert ein strukturiertes Ergebnis. Keine Subsonic-/HTTP-
Kommunikation mit Navidrome — der Docker-Befehl selbst spricht mit dem
Navidrome-Container, nicht `NavidromeScanTrigger`.

### Technische Verantwortung

1. Konfigurationsvalidierung (`NAVIDROME_SCAN_COMMAND` vorhanden/nicht
   leer, Typprüfung, Listen-zu-String-Normalisierung).
2. Subprocess-Start (`asyncio.create_subprocess_shell`).
3. Timeout-Überwachung (`asyncio.wait_for`, konfigurierbar über
   `Config.NAVIDROME_SCAN_TIMEOUT`).
4. Ergebnis-Dekodierung (`stdout`/`stderr`, UTF-8, fehlertolerant).
5. Strukturierte Rückgabe (`ScanRunResult`) bzw. typisierte Exceptions.

### Externe Abhängigkeiten

- `asyncio` (Standardbibliothek — Subprocess-/Timeout-Steuerung).
- Betriebssystem-Shell (`create_subprocess_shell`) und darüber
  transitiv `docker` (als externes Kommandozeilenprogramm, nicht als
  Python-Abhängigkeit).

### Interne Abhängigkeiten

- `config.Config`, `config.get_config` — Konfigurationszugriff.
- `logger.log_handler_debug/error/info` — Logging.
- **Keine** Abhängigkeit zu `services/clients/navidrome_api.py` oder
  irgendeinem anderen Navidrome-Modul — bewusst entkoppelt (eigener,
  unabhängiger `@lru_cache`-Config-Getter `_get_scan_config()`, mit
  explizit dokumentierter Begründung im Modul-Docstring: kein Zyklus mit
  dem ehemaligen `api/navidrome_api.py`).

### Konfigurationszugriff

`Config.NAVIDROME_SCAN_COMMAND` (String oder Liste), `Config.NAVIDROME_SCAN_TIMEOUT`
(Sekunden, Default 300 über `getattr`, praktisch aber immer 45 gemäß
`config.py`). Zugriff sowohl über die Klasse (`hasattr(Config, ...)`,
`getattr(Config, ...)`) als auch über die gecachte Instanz
(`_get_scan_config().NAVIDROME_SCAN_COMMAND`) — eine bereits in ARCH-009
Phase 3 dokumentierte, absichtlich beibehaltene Eigenheit.

### Logging

Alle Log-Aufrufe verwenden bewusst `context="NavidromeAPI"` (nicht
`"NavidromeScanTrigger"`) — dokumentierte Design-Entscheidung aus Phase 4:
der Logger für den Kontext `"NavidromeAPI"` wurde historisch auf
ERROR-Level gesetzt; ein neuer Kontextname hätte zusätzliche INFO-/
DEBUG-Ausgabe verursacht. **Wichtig für Abschnitt 9:** Diese Kopplung an
den String `"NavidromeAPI"` ist rein logisch (Log-Kategorie), nicht an
das inzwischen entfernte Modul `api/navidrome_api.py` gebunden — sie
bleibt unabhängig vom tatsächlichen Ablageort von `NavidromeScanTrigger`
technisch funktionsfähig.

### Subprocess-Verwendung

`asyncio.create_subprocess_shell(command_to_execute, stdout=PIPE, stderr=PIPE)`
— Shell-basiert (nicht `create_subprocess_exec` mit Argumentliste). Bereits
in ARCH-009 Phase 3 als grundsätzlich Shell-Injection-anfälliges, aber
aktuell unkritisches Muster dokumentiert (statischer Config-Fixwert, keine
Nutzereingabe).

### Docker-Bezug

Kein direkter Python-Docker-SDK-Zugriff — der Docker-Bezug entsteht
ausschließlich dadurch, dass der konfigurierte Shell-Befehl selbst
`docker exec ...` lautet. `NavidromeScanTrigger` selbst weiß nichts von
Docker im Code — es führt einen beliebigen konfigurierten Shell-Befehl
aus.

### Timeout-Verhalten

`asyncio.wait_for(process.communicate(), timeout=timeout)` — bei
Überschreitung wird `ScanTimeoutError(timeout)` geworfen (nicht
`asyncio.TimeoutError` direkt durchgereicht).

### Exceptions

`AttributeError` (Konfiguration fehlt/leer), `TypeError` (Konfiguration
nach Normalisierung kein String), `ScanTimeoutError` (Timeout
überschritten, eigene Exception-Klasse mit `.timeout_seconds`-Attribut).
Alle anderen Exceptions (z. B. aus `create_subprocess_shell` selbst)
werden nicht gefangen, propagieren unverändert.

### `ScanRunResult`

`@dataclass`: `success: bool`, `returncode: int`, `stdout: str`,
`stderr: str`. Reines Datenobjekt, keine Telegram-/Präsentationslogik
(seit ARCH-009 Phase 4/5 durchgängig so gehalten).

### `ScanTimeoutError`

`Exception`-Unterklasse mit `timeout_seconds`-Attribut, für die
Fehlermeldungsbildung im Handler (siehe Abschnitt 7).

### Testbarkeit

Bereits 5 dedizierte, grüne Charakterisierungstests
(`tests/test_navidrome_scan_trigger.py`): Erfolg, `returncode != 0`,
Timeout (inkl. `timeout_seconds`-Wert), fehlender Scan-Befehl, Listen-
Normalisierung. Alle Netzwerk-/Subprozess-Aufrufe vollständig gemockt
(Regel 7). Keine Testbarkeitsprobleme, unabhängig vom Speicherort.

### Aktuelle Consumer

Genau ein Produktions-Consumer:
`handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()` (seit
ARCH-009 Phase 9 Umsetzung A direkter Aufruf, vorher über die
inzwischen entfernte `execute_scan()`-Bridge).

### Klassifikationsfrage

> Ist `NavidromeScanTrigger` ein Service, ein technischer Runner, ein
> Infrastruktur-Adapter, ein externer Integrationsadapter oder etwas
> anderes?

**Kein externer Integrationsadapter** — keine Netzwerk-/HTTP-Kommunikation
mit einem entfernten System; der Docker-Befehl läuft lokal auf dem
Host, der den Bot betreibt.

**Kein reiner „Service“** im Sinne der in dieser Roadmap definierten
`services/`-Bedeutung („Anwendungs- und Fachlogik, Orchestrierung“) —
`NavidromeScanTrigger` trifft keine fachlichen Entscheidungen, verarbeitet
keine Business-Daten, sondern führt exakt einen konfigurierten externen
Befehl aus und meldet dessen Ergebnis.

**Am treffendsten: ein technischer Runner / lokaler
Infrastruktur-Adapter** — adaptiert eine rohe, fehleranfällige
Low-Level-Schnittstelle (Shell-Subprocess) hinter einer sauberen,
typisierten, asynchronen Python-Schnittstelle (`ScanRunResult`/
`ScanTimeoutError`). Strukturell nicht anders zu bewerten als ein
„Client“ für lokale statt entfernte Systeme — nur eben lokal statt
über HTTP.

---

## 2. Vollständiger Dependency-/Consumer-Audit

Repo-weit per Grep verifiziert (`api.navidrome_scan_trigger`,
`NavidromeScanTrigger`, `ScanRunResult`, `ScanTimeoutError`, `run_scan(`,
alle `patch(...)`-String-Ziele).

| Referenz | Datei | Verwendung | Schicht | Bedeutung |
|---|---|---|---|---|
| `from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError` | `handlers/menu/rich_menu_handler.py:55` | Import | `handlers/` | einziger Produktions-Consumer |
| `await NavidromeScanTrigger.run_scan()` | `handlers/menu/rich_menu_handler.py:741` | Aufruf | `handlers/` | einziger Produktions-Call-Site |
| `except ScanTimeoutError as e:` | `handlers/menu/rich_menu_handler.py:746` | Exception-Behandlung | `handlers/` | Telegram-Fehlermeldung |
| `from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError` | `tests/test_navidrome_scan_trigger.py:22` | Import (Test) | Test | direkte Charakterisierung |
| 5× `asyncio.run(NavidromeScanTrigger.run_scan())` | `tests/test_navidrome_scan_trigger.py` | Aufruf (Test) | Test | Verhaltenstests |
| 8× `patch("api.navidrome_scan_trigger.*")` (`asyncio.create_subprocess_shell` ×3, `_get_scan_config` ×3, `Config` ×1, weitere) | `tests/test_navidrome_scan_trigger.py` | Patch-Ziel (Test) | Test | würde bei Verschiebung brechen |
| `from api.navidrome_scan_trigger import ScanRunResult, ScanTimeoutError` | `tests/test_rich_menu_handler.py:23` | Import (Test) | Test | für Mock-Rückgabewerte |
| 5× `patch("handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan", ...)` | `tests/test_rich_menu_handler.py` | Patch-Ziel (Test) | Test | patcht über das **konsumierende Modul** — unabhängig vom tatsächlichen Speicherort von `NavidromeScanTrigger` (Muster seit ARCH-009 Phase 8) |
| Prosa-Erwähnungen „NavidromeScanTrigger“/„api.navidrome_scan_trigger“ | `docs/MusicBot_ARCH-009_Phase3/5/6/8/9_*.md` | Doku | historisch | Zeitpunkt-Snapshots, keine funktionale Wirkung |
| Prosa-Erwähnung „delegiert an `NavidromeScanTrigger`“ | `services/clients/navidrome_api.py:47` (Docstring) | Doku (Code-Kommentar) | `services/clients/` | erklärt die bewusste Trennung, kein Import |

**Wichtige Unterscheidung (wie gefordert):** Von den insgesamt ~25
Grep-Treffern für „NavidromeScanTrigger“/„api.navidrome_scan_trigger“
repo-weit sind **nur 4 funktional** (1 Import + 1 Aufruf + 1
Exception-Handling in `rich_menu_handler.py`, plus die Testdatei-Importe/
Patch-Ziele) — der Rest ist Prosa in Docstrings/Kommentaren/historischen
ARCH-Dokumenten ohne Laufzeitwirkung.

**Keine dynamischen Imports gefunden** (`importlib`/`__import__` repo-weit
geprüft, keine Treffer im Navidrome-Kontext).

---

## 3. Ist `api/` noch architektonisch begründbar?

Aktueller Zustand: `api/` enthält ausschließlich `navidrome_scan_trigger.py`
(+ leere `__init__.py`, 0 Bytes, keine Re-Exports).

**Ist `api/` im Projekt überhaupt als eigene Architekturschicht
definiert?** Nein. `CLAUDE.md` (die verbindliche Engineering-Baseline
dieses Projekts) erwähnt `api/` an keiner Stelle als definierte Schicht —
im Gegensatz zu `services/clients/`, das dort und in der ARCH-009-Roadmap
explizit definiert ist.

**Welche Bedeutung hatte `api/` ursprünglich?** Laut ARCH-008-Analyse
(vor Beginn der ARCH-009-Reihe) enthielt `api/` **zu jedem Zeitpunkt
ausschließlich Navidrome-bezogenen Code** — nie mehrere unabhängige
API-Client-Module. Es war historisch nie eine echte „alle externen
APIs“-Sammelschicht (das ist heute die Rolle von `services/clients/`,
mit inzwischen 4 Modulen: Genius, LastFM, MusicBrainz, Navidrome),
sondern von Anfang an faktisch ein Navidrome-spezifischer Ordner, dessen
Name zufällig „api“ lautete.

**Passt `NavidromeScanTrigger` zu dieser (Nicht-)Bedeutung?** Nein — es
ist, wie in Abschnitt 1 festgestellt, kein externer API-Client, sondern
ein lokaler Infrastruktur-Runner. Der Name `api/` beschreibt seinen
Inhalt nicht mehr korrekt, seit `api/navidrome_api.py` (der einzige
Grund, der jemals den Namen „api“ gerechtfertigt hätte) in ARCH-009
Phase 9 entfernt wurde.

**Würde das Beibehalten von `api/` nur wegen dieses einen Moduls eine
historische Restschicht konservieren?** Ja — genau das. `api/` ist
nach dem aktuellen Stand kein aktiv genutztes Architekturkonzept mehr,
sondern ein Verzeichnis, das zufällig ein einzelnes Modul beherbergt,
das nicht (mehr) zu seinem Namen passt.

**Zwischenfazit:** `api/` selbst ist architektonisch nicht mehr
begründbar — unabhängig davon, wohin `NavidromeScanTrigger` letztlich
verschoben wird. Das bedeutet nicht automatisch, dass `NavidromeScanTrigger`
verschoben werden muss (Variante A bliebe technisch funktionsfähig), aber
es entkräftet das Argument „bleibt in `api/`, weil `api/` ein sinnvoller
Ort ist“ — dieses Argument existiert nach der Analyse nicht mehr.

---

## 4. Zielvarianten

### Variante A — `api/` beibehalten

```text
api/
└── navidrome_scan_trigger.py
```

Keine Migration nötig. Funktioniert unverändert. Konserviert aber eine
laut Abschnitt 3 nicht mehr begründbare Restschicht.

### Variante B — direkt unter `services/`

```text
services/
└── navidrome_scan_trigger.py
```

Kein bestehender Präzedenzfall für eine freistehende Top-Level-
Infrastrukturdatei in `services/` (siehe ARCH-009 Phase-6-Analyse:
`services/statistik_service.py` ist eine Fassade über Business-Logik,
kein Infrastruktur-Modul). `services/` ist laut Roadmap explizit für
Fachlogik/Orchestrierung reserviert — teilweiser Passungskonflikt.

### Variante C — eigene technische/infrastrukturelle Schicht (`infrastructure/` o. ä.)

Architektonisch am saubersten benannt, aber: kein bestehender
Präzedenzfall im Repo, müsste komplett neu etabliert werden, und —
entscheidend, siehe Abschnitt 6 — **es existiert bereits ein etabliertes
Verzeichnis für genau diesen Zweck** (`utils/`, siehe Variante D). Eine
komplett neue Top-Level-Schicht wäre angesichts dessen unnötige
Vorratsarchitektur für ein einzelnes Modul.

### Variante D — anderer bestehender Zielort: `utils/`

```text
utils/
└── navidrome_scan_trigger.py
```

Ergibt sich **nicht aus einer allgemeinen Vermutung, sondern konkret aus
dem in Abschnitt 6 dokumentierten Dependency-/Verantwortungs-Audit**:
`utils/audio_enhancer.py::AudioEnhancer` ist ein strukturell nahezu
identisches Muster — kapselt `subprocess`-Aufrufe eines externen
Tools, gibt ein `@dataclass`-Ergebnis (`EnhancementResult`, mit
`success: bool` + Fehlerfeld) zurück, hat keinerlei Telegram-Kopplung.
`utils/` ist im Repository bereits die etablierte Kategorie für
„technische Helfer, die weder Fachlogik (`services/`), noch
Telegram-Präsentation (`handlers/`), noch externe API-Kommunikation
(`services/clients/`) sind“ (weitere Beispiele: `cache.py`,
`singleton.py`, `file_ops.py`).

### Variante E — `services/clients/` (ausdrücklich kritisch geprüft)

> `services/clients/` ist für externe Integrationsadapter vorgesehen.

`NavidromeScanTrigger` erfüllt diese Definition **nicht**: keine
Netzwerkkommunikation mit einem externen System, kein HTTP, keine
Authentifizierung gegen einen entfernten Dienst — der Docker-Befehl
läuft lokal auf demselben Host wie der Bot. Eine Ablage dort allein
deshalb, weil „Navidrome“ im Namen steht, würde die in ARCH-009 Phase 6/8
gerade erst etablierte, strenge Definition von `services/clients/`
verwässern (dieselbe Vermischung, die ARCH-009 Phase 3–8 bei
`api/navidrome_api.py` bereits aufgelöst hat). **Klar nicht empfohlen.**

---

## 5. Vergleichsmatrix

| Variante | Verantwortlichkeit passend? | Architekturkonformität | Abhängigkeiten | Testbarkeit | Erweiterbarkeit | Risiko | Empfehlung |
|---|---|---|---|---|---|---|---|
| **A — `api/`** | teilweise (Name passt nicht mehr, Inhalt neutral) | schwach (`api/` ist keine definierte Schicht mehr, Abschnitt 3) | unverändert | unverändert gut | keine Verbesserung, keine Verschlechterung | keins (kein Umzug) | Status-quo-Option, aber konserviert Altlast |
| **B — `services/`** | schwach (kein Fachlogik-/Orchestrierungsbezug) | mittel (Konflikt mit Roadmap-Definition von `services/`) | unverändert | unverändert gut | unklar, kein Präzedenzfall | gering (kleiner Umzug), aber falsches Signal | nicht empfohlen |
| **C — neue Schicht (`infrastructure/`)** | gut (semantisch passend) | hoch in der Theorie, aber kein Repo-Präzedenz | unverändert | unverändert gut | am besten *falls* weitere Kandidaten entstehen | mittel (neue Konvention etablieren, YAGNI-Risiko) | nicht empfohlen (Vorratsarchitektur für 1 Modul, siehe Abschnitt 8) |
| **D — `utils/`** | gut (technischer Helfer, kein Fachlogik-/API-/Telegram-Bezug) | hoch — nutzt bestehende, bereits etablierte Kategorie mit direktem Präzedenzfall (`audio_enhancer.py`) | unverändert | unverändert gut | gut, ohne neue Konvention zu erfinden | gering (kleiner, gut verstandener Umzug) | **empfohlen** |
| **E — `services/clients/`** | nicht passend (kein externer API-Client) | verletzt die gerade etablierte Definition | unverändert | unverändert gut | irreführend für künftige Leser | mittel (semantische Fehlplatzierung) | klar nicht empfohlen |

---

## 6. Vergleich mit bestehender Architektur

Repo-weite Suche nach ähnlichen Verantwortlichkeiten (Subprocess-/Docker-
Steuerung, technische Runner/Worker/Trigger) außerhalb von
`api/navidrome_scan_trigger.py` ergab zwei relevante Treffer:

### `handlers/admin/bot_restart_handler.py::BotRestartHandler`

Führt `subprocess.run(["sudo", "systemctl", "restart", "bot"], ...)` aus,
um den Bot-Prozess neu zu starten (Admin-Feature über Telegram-Button).

- **Gemeinsamkeit:** lokale Subprocess-Ausführung eines Systembefehls,
  ausgelöst durch eine Admin-Aktion.
- **Unterschied:** `BotRestartHandler` vermischt Telegram-Interaktion
  (Bestätigungsdialog, Button-Handling) **und** die Subprocess-Ausführung
  in derselben Klasse — genau die Vermischung, die ARCH-009 für Navidrome
  bereits in Phase 4/5 aufgelöst hat. `NavidromeScanTrigger` ist bereits
  sauberer strukturiert als dieses bestehende Vorbild.
- **Ort:** `handlers/admin/` — passend, *weil* die Telegram-Kopplung dort
  bewusst nicht aufgelöst wurde. Kein übertragbares Vorbild für
  `NavidromeScanTrigger`, das bereits telegramfrei ist.
- **Ableitbare Konvention:** keine direkt anwendbare — eher ein Beleg
  dafür, dass es *noch keine* einheitliche Konvention für „lokale
  Systemsteuerung“ im Repository gibt, sondern historisch gewachsene
  Einzellösungen.

### `utils/audio_enhancer.py::AudioEnhancer`

Führt externe Audio-Tools (ffmpeg-artige Kommandozeilenprogramme) über
`subprocess.run(...)` aus (ReplayGain-Analyse/-Anwendung), Timeout-
Handling inklusive (`subprocess.TimeoutExpired`), gibt ein
`@dataclass`-Ergebnis (`EnhancementResult`: `success: bool`,
Ergebnisfelder, optionales `error`-Feld) zurück.

- **Gemeinsamkeit:** strukturell nahezu identisches Muster —
  Subprocess-Wrapper, typisiertes Dataclass-Ergebnis mit `success`-Flag,
  keine Telegram-/Handler-Kopplung, reine technische Ausführungsklasse.
- **Unterschied:** synchron (`subprocess.run` + `ThreadPoolExecutor`)
  statt `asyncio`-basiert wie `NavidromeScanTrigger` — stilistischer,
  kein architektonischer Unterschied.
- **Ort:** `utils/`.
- **Ableitbare Konvention:** `utils/` ist die im Repository bereits
  etablierte, tatsächlich genutzte Kategorie für „technische
  Subprocess-/Tool-Wrapper mit typisiertem Ergebnis, ohne Fachlogik- oder
  Telegram-Bezug“ — exakt das Profil von `NavidromeScanTrigger`.

**Fazit:** Es gibt keine bestehende, saubere Konvention für „lokale
Infrastruktursteuerung“ als eigene Top-Level-Schicht — aber es gibt einen
direkten strukturellen Zwilling in `utils/`, der bereits funktioniert und
etabliert ist.

---

## 7. Abgrenzung zu `services/clients/navidrome_api.py`

```text
services/clients/navidrome_api.py
        │
        └── externe Navidrome HTTP/API-Kommunikation (Subsonic-Protokoll,
            Netzwerk, Authentifizierung gegen einen entfernten Dienst)
```

```text
NavidromeScanTrigger
        │
        └── lokaler Docker/Subprocess zur Ausführung eines Scans
            (keine Netzwerkkommunikation mit Navidrome selbst - der
            Docker-Befehl übernimmt das, nicht NavidromeScanTrigger)
```

**Sind diese beiden Komponenten fachlich Teil derselben Schicht?** Nein.
Unterschiedliche Fehlerklassen (HTTP-Fehler vs. Subprocess-/Timeout-
Fehler), unterschiedliche Sicherheitsbetrachtung (Netzwerk-Client vs.
lokale Shell-Ausführung, siehe Shell-Injection-Hinweis in Abschnitt 1),
unterschiedliche Testinfrastruktur (bereits heute vollständig getrennte
Testdateien).

**Würde eine gemeinsame Ablage unter `services/clients/` die bestehende
Architekturregel verletzen?** Ja, eindeutig — das ist exakt der in
ARCH-009 Phase 3 identifizierte und seither konsequent vermiedene Fehler
(die ursprüngliche Vermischung in `api/navidrome_api.py`, die zur
gesamten ARCH-009-Reihe geführt hat). Eine gemeinsame Ablage würde die
gerade erst wiederhergestellte Trennung rückgängig machen.

---

## 8. Zukunftsperspektive

**Könnten zukünftig weitere technische Trigger/Runner entstehen?** Kein
konkreter, im Repository erkennbarer Bedarf. `BotRestartHandler`
(Abschnitt 6) existiert bereits, aber als bewusst Telegram-gekoppelte
Einzellösung in `handlers/admin/` — es gibt keinen Hinweis darauf, dass
er in absehbarer Zeit refactored und in eine gemeinsame Infrastruktur-
Schicht überführt würde.

**Würde eine neue eigene Schicht dadurch sinnvoll?** Nicht auf
Grundlage des aktuellen Bestands — aktuell existiert nur ein einziges
Modul (`NavidromeScanTrigger`), das eindeutig in diese Kategorie fällt.

**Oder wäre das für aktuell nur ein Modul Overengineering?** Ja — eine
komplett neue Top-Level-Schicht (Variante C) für ein einzelnes Modul
wäre Architektur auf Vorrat, ohne im Bestand nachweisbaren Bedarf
(CLAUDE.md Regel 18/19: kein Refactoring/keine neue Struktur ohne
konkreten Anlass).

**Gibt es eine sinnvolle Zwischenlösung?** Ja — Variante D (`utils/`)
ist genau das: keine neue Konvention, sondern Wiederverwendung einer
bereits etablierten, bereits mit einem strukturell passenden Beispiel
belegten Kategorie.

**Welche Zielstruktur wäre langfristig stabil, ohne jetzt unnötige
Architektur einzuführen?** `utils/navidrome_scan_trigger.py` — stabil,
weil `utils/` bereits eine dauerhafte, breit genutzte Kategorie ist, und
erweiterbar, falls künftig tatsächlich weitere ähnliche Module entstehen
(dann in derselben Kategorie, ohne dass heute vorab eine neue Schicht
erfunden werden müsste).

---

## 9. Auswirkungen einer späteren Umsetzung (noch NICHT umgesetzt)

Am Beispiel der empfohlenen Variante D (`utils/navidrome_scan_trigger.py`)
— bei anderer Entscheidung entsprechend kleiner (Variante A: keine
Änderung) oder analog (Variante B/C mit anderem Zielpfad):

**Voraussichtlich zu ändernde Dateien:**

- `api/navidrome_scan_trigger.py` → `utils/navidrome_scan_trigger.py`
  (Datei verschieben, Inhalt unverändert — Log-Kontext `"NavidromeAPI"`
  bleibt technisch funktionsfähig, siehe Abschnitt 1, „Logging“).
- `handlers/menu/rich_menu_handler.py` — 1 Importzeile ändert sich
  (`from api.navidrome_scan_trigger import ...` → `from utils.navidrome_scan_trigger import ...`).

**Betroffene Tests:**

- `tests/test_navidrome_scan_trigger.py` — 1 Importzeile + 8
  String-Patch-Ziele (`"api.navidrome_scan_trigger.*"` →
  `"utils.navidrome_scan_trigger.*"`).
- `tests/test_rich_menu_handler.py` — **keine Änderung nötig** (patcht
  bereits über das konsumierende Modul
  `"handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan"` —
  unabhängig vom tatsächlichen Speicherort, Muster seit ARCH-009 Phase 8).

**`api/` danach vollständig entfallen?** Ja — nach Verschiebung von
`NavidromeScanTrigger` enthielte `api/` keinerlei Inhalt mehr
(`navidrome_api.py` bereits in Phase 9 entfernt). `api/__init__.py`
(bereits 0 Bytes) könnte mit entfallen.

**Breaking Changes?** Keine öffentlich sichtbaren — rein interne
Python-Importpfade. `NavidromeScanTrigger`s API (`run_scan()`,
`ScanRunResult`, `ScanTimeoutError`) bleibt vollständig unverändert.

**Umfang:** kleinster oder zweitkleinster Migrationsschritt der
gesamten ARCH-009-Reihe (1 Consumer-Datei, 1 Testdatei mit 8
Patch-Zielen, 1 Dateiverschiebung) — deutlich kleiner als Phase 8.

---

## 10. Klare Empfehlung

> **Der endgültige Zielort von `NavidromeScanTrigger` sollte sein:
> `utils/navidrome_scan_trigger.py`.**

Begründung, ausschließlich anhand des tatsächlichen Repository-Bestands
(nicht „Best Practice“):

1. `api/` hat laut Abschnitt 3 keine begründbare architektonische
   Existenzberechtigung mehr — es war historisch nie eine echte
   Mehrfach-API-Schicht, sondern ausschließlich ein Navidrome-Ordner, der
   zufällig „api“ hieß.
2. `services/clients/` (Variante E) und eine neue Top-Level-Schicht
   (Variante C) scheiden aus fachlichen bzw. Sparsamkeitsgründen aus
   (Abschnitt 4).
3. `services/` (Variante B) hat keinen Präzedenzfall für freistehende
   Infrastrukturdateien und würde die gerade etablierte
   `services/`-Definition (Fachlogik/Orchestrierung) verwässern.
4. `utils/` besitzt bereits ein strukturell nahezu identisches,
   funktionierendes Vorbild (`audio_enhancer.py::AudioEnhancer`,
   Abschnitt 6) — keine neue Konvention nötig, geringstes Risiko, kleinste
   Änderung, größte Konsistenz mit dem, was im Repository bereits
   tatsächlich existiert.

Variante A (Status quo, `api/` beibehalten) bleibt eine legitime,
risikofreie Alternative, falls kein weiterer Aufwand in diese Migration
investiert werden soll — sie konserviert dann aber bewusst eine laut
Abschnitt 3 nicht mehr begründbare Restschicht.

---

## 11. Entscheidungsgate

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde
vorgenommen.**

1. **Empfohlener Zielort:** `utils/navidrome_scan_trigger.py` (Variante
   D).
2. **Begründung:** siehe Abschnitt 10 — einziger Zielort mit direktem,
   bereits existierendem strukturellem Vorbild im Repository
   (`utils/audio_enhancer.py`); `api/` selbst ist nicht mehr begründbar.
3. **Alternativen und deren Nachteile:**
   - A (Status quo, `api/`): konserviert eine architektonisch nicht mehr
     begründbare Restschicht (Abschnitt 3).
   - B (`services/`): kein Präzedenzfall, Konflikt mit der
     `services/`-Definition.
   - C (neue Schicht `infrastructure/`): Vorratsarchitektur für ein
     einzelnes Modul, kein Repo-Präzedenzfall.
   - E (`services/clients/`): verletzt die dortige Definition „externe
     Integrationsadapter“ direkt.
4. **Soll `api/` danach vollständig entfernt werden?** Ja, falls
   Variante D (oder B/C) gewählt wird — `api/` enthielte dann keinerlei
   Inhalt mehr. Bei Variante A bleibt `api/` unverändert bestehen.
5. **Zu ändernde Dateien bei späterer Umsetzung:**
   `api/navidrome_scan_trigger.py` → `utils/navidrome_scan_trigger.py`
   (Verschiebung), `handlers/menu/rich_menu_handler.py` (1 Importzeile).
6. **Anzupassende Tests:** `tests/test_navidrome_scan_trigger.py` (1
   Import + 8 Patch-Ziele). `tests/test_rich_menu_handler.py` unverändert
   (patcht bereits über das konsumierende Modul).
7. **Breaking Changes:** keine — rein interne Importpfade, `NavidromeScanTrigger`s
   öffentliche API bleibt unverändert.
8. **Empfohlene Anzahl der Umsetzungsschritte:** ein einziger, isolierter
   Schritt (kleinster oder zweitkleinster Umfang der gesamten
   ARCH-009-Reihe) — analog zum bereits etablierten Vorgehen ohne
   Kompatibilitäts-Bridge (Phase 8/9).

**STOPP. Keine Umsetzung ohne ausdrückliche Nutzerentscheidung.**
