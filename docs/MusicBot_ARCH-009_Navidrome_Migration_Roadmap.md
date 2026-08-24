Klar — hier ist der Inhalt für **`docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`** zum Copy/Paste:

````md
# MusicBot ARCH-009 — Navidrome Migration Roadmap

## Zweck

Diese Roadmap dokumentiert die schrittweise Entflechtung der aktuellen
`api/navidrome_api.py` und die spätere Entscheidung über die endgültige
Architektur des verbleibenden Navidrome-Integrationskerns.

Die Roadmap ist ein **Architektur-Fahrplan**, kein Gesamtauftrag zur
automatischen Umsetzung aller Phasen.

Jede Phase wird separat analysiert bzw. umgesetzt, getestet, reviewed und
erst danach wird über den nächsten Schritt entschieden.

---

# Ausgangslage

Die Analyse aus ARCH-008 und ARCH-009 hat ergeben, dass die ursprüngliche
`api/navidrome_api.py` mehrere unterschiedliche Verantwortlichkeiten
vermischt:

1. externe Navidrome/Subsonic-API-Kommunikation
2. Telegram-spezifische Präsentations-/Formatierungslogik
3. lokale Subprocess-/Shell-Ausführung für Navidrome-Scans
4. teilweise Diagnose-/Statusfunktionen

Eine direkte 1:1-Verschiebung nach:

```text
services/clients/
````

wäre daher architektonisch nicht korrekt.

Die bestehende Regel bleibt:

```text
services/clients/
    = ausschließlich externe Integrationsadapter
```

Telegram-Präsentationslogik darf dort nicht landen.

Lokale Shell-/Subprocess-Steuerung wird nicht ungeprüft als Teil eines
externen API-Clients behandelt.

---

# Bereits abgeschlossen

## ARCH-008 — Analyse `api/navidrome_api.py`

Abgeschlossen.

Ergebnis:

* `NavidromeAPI` ist kein reiner Integrationsadapter.
* Die Datei vermischte API-Kommunikation, Telegram-Formatierung und
  Subprocess-Steuerung.
* Mehrheit der Consumer liegt in `handlers/`.
* Der einzige bekannte `services/`-Consumer ist bereits über Dependency
  Injection entkoppelbar.
* Eine direkte Verschiebung nach `services/clients/` wurde verworfen.

---

## ARCH-009 Phase 1 — Bestandsaufnahme ungenutzter Methoden

Abgeschlossen.

Sieben ungenutzte Methoden wurden einzeln untersucht.

Entscheidung:

### Entfernen

* `format_full_status_message()`
* `format_rescan_status_message()`
* `format_web_interface_url_message()`
* `get_full_server_info()`
* `get_scan_status()`
* `test_api()`

### Behalten

* `check_connection()`

`check_connection()` bleibt erhalten, da ein dokumentierter zukünftiger
Einsatz aus BUG-007 besteht.

---

## ARCH-009 Phase 2 — Entfernung toter Navidrome-Methoden

Abgeschlossen.

Die sechs freigegebenen ungenutzten Methoden wurden entfernt.

Nicht Bestandteil dieser Phase:

* keine Verschiebung von `api/navidrome_api.py`
* keine DI-Umstellung
* keine Änderung an `check_connection()`
* keine Änderung an `execute_scan()`
* keine Architekturmigration nach `services/clients/`

---

## ARCH-009 Phase 3 — `execute_scan()` / Subprocess-Verantwortung analysieren

Abgeschlossen.

Ergebnis: `execute_scan()` vermischte Konfigurationsvalidierung,
Docker-Subprocess-/Timeout-Steuerung und Telegram-MarkdownV2-Formatierung.
Vier Zielarchitektur-Varianten (A-D) bewertet, empfohlen wurde eine
gestufte Umsetzung (zuerst Subprocess-Extraktion, Telegram-Trennung als
separater, späterer Schritt). Details:
`docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md`.

---

## ARCH-009 Phase 4 — Subprocess-Verantwortung extrahieren

Abgeschlossen.

Die Docker-/Subprocess-/Timeout-Steuerung wurde 1:1 nach
`api/navidrome_scan_trigger.py` (`NavidromeScanTrigger`) ausgelagert.
`NavidromeAPI.execute_scan()` bleibt als öffentliche Schnittstelle
unverändert bestehen und fungiert als Bridge; kein Consumer musste
angepasst werden. Telegram-Formatierung, `check_connection()` und die
Zielposition `services/clients/` blieben bewusst unangetastet. Details:
`docs/MusicBot_ARCH-009_Phase3_ExecuteScan_Analyse.md` (Abschnitt „Phase 4
— Umsetzung“).

---

## ARCH-009 Phase 5 — Verbleibende Präsentations-/Telegram-Verantwortlichkeiten

Abgeschlossen.

Analyse: von sieben verbleibenden `NavidromeAPI`-Methoden verletzte nur
`execute_scan()` den Grundsatz (Telegram-MarkdownV2-Formatierung in allen
vier Ausgängen). Zusatzfund: toter `telegram.constants.ParseMode`-Import
(unabhängige, nicht getroffene Entscheidung).

Umsetzung: `execute_scan()` ist jetzt ein reiner, telegramfreier
Pass-Through zu `NavidromeScanTrigger.run_scan()` (`ScanRunResult`,
Exceptions wie `ScanTimeoutError` werden unverändert durchgereicht).
Die Telegram-MarkdownV2-Formatierung (Erfolg/Fehlschlag/Timeout/generische
Exception, inkl. Emojis und Escaping) liegt jetzt vollständig im einzigen
Consumer `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()`.
`check_connection()`, `NavidromeScanTrigger` und die Zielposition
`services/clients/` blieben unangetastet. Details:
`docs/MusicBot_ARCH-009_Phase5_Telegram_Verantwortlichkeiten_Analyse.md`
(Abschnitte „Optionen“ und „Umsetzung“).

## ARCH-009 Phase 6 — Zielposition und DI von `NavidromeAPI`

Abgeschlossen.

Analyse: 6 von 7 verbleibenden Methoden sind reine API-Kommunikation;
`execute_scan()` ist die einzige Ausnahme (delegiert an
`NavidromeScanTrigger`, keine echte Navidrome-API-Kommunikation). 13
Produktions-Call-Sites über 3 Consumer-Dateien, 92 % davon in `handlers/`
(`navidrome_menu_handler.py`, `rich_menu_handler.py`); der einzige
`services/`-Consumer (`play_history_poller.py` über `statistik_service.py`)
ist bereits DI-bereit. ~30 Testreferenzen über 5 Testdateien hängen an der
statischen Klasse. Drei Varianten bewertet (A: Status quo, B: DI in-place
ohne Verschiebung, C: DI + Verschiebung kombiniert) — empfohlen: Variante
B zuerst, Verschiebung nach `services/clients/` als separater, späterer
Schritt danach (kehrt die Reihenfolge Phase 7/8 unten technisch um, siehe
Entscheidungsgate im Analysedokument). `execute_scan()` und
`NavidromeScanTrigger` sollen in keinem Fall nach `services/clients/`
wandern. Details:
`docs/MusicBot_ARCH-009_Phase6_Zielposition_DI_Analyse.md`.

---

## ARCH-009 Phase 7 — `NavidromeAPI` DI-Umstellung

Abgeschlossen.

Umsetzung von Variante B aus Phase 6: `NavidromeAPI` ist jetzt
instanziierbar mit injizierbarer Config
(`__init__(self, config=None)`, `_auth_params` pro Instanz statt als
Modul-Import-Seiteneffekt). Sechs Methoden von `@classmethod`/
`@staticmethod` auf echte Instanzmethoden umgestellt
(`_build_url`/`make_request`/`check_connection`/`get_artists`/
`get_now_playing`/`search`); `execute_scan()` bleibt bewusst
`@classmethod` (zustandsloser Pass-Through zu `NavidromeScanTrigger`,
keine DI nötig). Consumer migriert: `handlers/navidrome_menu_handler.py`
(11 Call-Sites, neuer optionaler `navidrome_api`-Konstruktor-Parameter),
`services/statistik/play_history_poller.py`/`statistik_service.py`
verifiziert als bereits konform (kein Code geändert). Verbleibender
statischer Aufruf: `handlers/menu/rich_menu_handler.py:740`
(`NavidromeAPI.execute_scan()`, bewusst nicht migriert, siehe
Analysedokument). Noch **keine** Verschiebung nach `services/clients/`.
Details: `docs/MusicBot_ARCH-009_Phase7_NavidromeAPI_DI.md`.

Damit ist die vormals als „Phase 8“ geführte DI-Frage bereits erledigt,
vor der vormals als „Phase 7“ geführten Zielort-Entscheidung (gemäß
Phase-6-Empfehlung, gestufte Reihenfolge). Die verbleibende
Zielort-/Verschiebungsfrage unten trägt zur Vermeidung einer doppelten
„Phase 7“ weiterhin die Nummerierung „Phase 8“.

---

# Nächste Phasen

Phase 3, Phase 4, Phase 5, Phase 6 und Phase 7 sind abgeschlossen (siehe
oben unter „Bereits abgeschlossen“).

---

## Phase 8 — Zielstruktur des Navidrome-Clients entscheiden (vormals „Phase 7“)

### Voraussetzung

Phase 6 bestätigt, dass der verbleibende Code (bis auf `execute_scan()`,
siehe Phase 6/7) ein reiner externer Integrationsadapter ist. Phase 7 hat
die Klasse bereits DI-fähig gemacht — eine Verschiebung ist jetzt ein
reiner Ortswechsel, keine gleichzeitige Strukturumstellung mehr.

### Zu entscheiden

Ob beispielsweise eine Struktur wie folgt sinnvoll ist:

```text
services/
└── clients/
    └── navidrome_client.py
```

Der konkrete Dateiname und die konkrete Klassenstruktur werden erst nach
der Analyse entschieden. Zu klären insbesondere (siehe
`docs/MusicBot_ARCH-009_Phase7_NavidromeAPI_DI.md` Abschnitt 6): Verbleib
von `execute_scan()` (Kompatibilitätsrest vs. Entfernung zugunsten eines
direkten `NavidromeScanTrigger`-Aufrufs im Handler) und von
`NavidromeScanTrigger` selbst (bleibt außerhalb von `services/clients/`).

### Grundsatz

Keine 1:1-Verschiebung einer Reststruktur nur aufgrund des Namens.

Die Zielstruktur muss sich aus den tatsächlichen Verantwortlichkeiten
ergeben.

---

## Phase 9 — Finaler Navidrome-Migrationsabschluss

Nach Abschluss aller entschiedenen Migrationsschritte:

### Prüfen

* keine Telegram-Abhängigkeiten im Integrationsadapter
* keine Präsentationslogik im Client
* keine ungeklärte Subprocess-Verantwortung
* keine Legacy-Importe auf alte Navidrome-Strukturen
* keine unnötigen Migration Bridges
* keine zyklischen Abhängigkeiten
* Consumer verwenden die entschiedene Zielstruktur
* Tests und Mock-Pfade sind konsistent

### Abschlussarbeiten

1. vollständiger Regressionstest
2. Import-Smoke-Test
3. Dependency-/Import-Audit
4. Architektur-Dokumentation aktualisieren
5. PR-Review
6. Merge

---

# Übergeordnete Zielarchitektur

Langfristig gilt:

```text
services/clients/
    │
    ├── externe Systeme ansprechen
    ├── HTTP/API-Kommunikation
    ├── Authentifizierung
    └── strukturierte API-Ergebnisse
```

```text
services/
    │
    ├── Anwendungs- und Fachlogik
    ├── Orchestrierung
    └── Verarbeitung strukturierter Daten
```

```text
handlers/
    │
    ├── Telegram-Interaktion
    ├── User-Input
    ├── Nachrichtenversand
    └── Telegram-spezifische Präsentation
```

Lokale Infrastruktur-, Shell- oder Subprocess-Verantwortlichkeiten werden
separat nach ihrer tatsächlichen Aufgabe bewertet und nicht automatisch
einem API-Client zugeordnet.

---

# Arbeitsprinzip

Die Phasen dieser Roadmap werden ausdrücklich **nicht automatisch
nacheinander implementiert**.

Für jede Phase gilt:

```text
Analyse
   ↓
Entscheidung
   ↓
separater Umsetzungsauftrag
   ↓
eigener Branch
   ↓
Tests
   ↓
Review / PR
   ↓
Merge
   ↓
nächste Phase
```

Eine spätere Phase darf nicht vorweggenommen werden, solange die dafür
notwendige Architekturentscheidung noch offen ist.

Die Roadmap dient der Orientierung und Nachvollziehbarkeit. Die konkreten
Arbeitsaufträge werden weiterhin schrittweise und einzeln erteilt.

```

Ich würde diese Roadmap **erst auf `main` dokumentieren, nachdem Phase 2 gemerged wurde**. Die nächsten Phasen selbst bleiben dann bewusst offen, bis jeweils die vorherige Analyse abgeschlossen und entschieden ist.
```

