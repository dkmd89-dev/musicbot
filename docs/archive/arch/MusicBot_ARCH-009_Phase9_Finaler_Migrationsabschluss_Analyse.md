# ARCH-009 Phase 9 — Finaler Migrationsabschluss: Zielarchitektur-Analyse

Reine Analysephase. **Keine Codeänderung, keine Verschiebung, keine
Löschung, keine Test-/Importänderung, kein automatisches Aufräumen.**
`docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md` ist verbindliche
Grundlage — Abweichungen zwischen dieser Analyse und der dort
dokumentierten Reihenfolge werden im Entscheidungsgate (Abschnitt 9)
ausgewiesen, nicht eigenmächtig in der Roadmap umnummeriert.

Bestimmt die endgültige Zielarchitektur für die letzten beiden noch nicht
final platzierten Bestandteile: `api/navidrome_api.py::execute_scan()`
und `api/navidrome_scan_trigger.py`, und prüft, ob `api/` danach
vollständig entfallen kann.

---

## 1. Vollständiger Dependency-/Import-Audit

Repo-weit per Grep verifiziert (`api.navidrome_api`, `api.navidrome_scan_trigger`,
`execute_scan`, `NavidromeScanTrigger`, `check_connection`, alle
`patch(...)`-String-Ziele).

| Modul | Verwendung | Typ | Ziel nach Migration |
|---|---|---|---|
| `handlers/menu/rich_menu_handler.py:55` | `from api.navidrome_api import NavidromeAPI` | Import/Consumer | entfällt vollständig, falls `execute_scan()` entfernt wird (Option 2/3) |
| `handlers/menu/rich_menu_handler.py:56` | `from api.navidrome_scan_trigger import ScanTimeoutError` | Import/Consumer | bleibt unverändert (Variante A für `NavidromeScanTrigger`) bzw. Pfad ändert sich (Variante B/C/D) |
| `handlers/menu/rich_menu_handler.py:740` | `result = await NavidromeAPI.execute_scan()` | Aufrufer (einziger Produktions-Call-Site) | ersetzt durch `await NavidromeScanTrigger.run_scan()`, falls Option 2/3 gewählt wird |
| `api/navidrome_api.py` | definiert `NavidromeAPI.execute_scan()` (Rest-Klasse aus Phase 8) | Definition | entfällt vollständig bei Option 2/3 |
| `api/navidrome_scan_trigger.py` | definiert `NavidromeScanTrigger`, `ScanRunResult`, `ScanTimeoutError` | Definition | bleibt (Variante A) bzw. Pfad ändert sich (Variante B/C/D) |
| `services/clients/navidrome_api.py` | Docstring-Erwähnung von `execute_scan()`/`NavidromeScanTrigger` (Begründung für die Trennung) | Doku (Code-Kommentar) | Wortlaut würde bei Umsetzung ggf. leicht anzupassen sein (kein funktionaler Bezug) |
| `tests/test_navidrome_api_execute_scan.py` (4 Tests) | testet `api.navidrome_api.NavidromeAPI.execute_scan()` (Pass-Through-Vertrag) | Test | entfällt vollständig bei Option 2/3 — Inhalt bereits redundant zu `test_navidrome_scan_trigger.py` (testet exakt dasselbe Verhalten von `NavidromeScanTrigger.run_scan()` bereits direkt) |
| `tests/test_navidrome_scan_trigger.py` | 8 String-Patch-Ziele: `"api.navidrome_scan_trigger.asyncio.create_subprocess_shell"` (3×), `"api.navidrome_scan_trigger._get_scan_config"` (3×), `"api.navidrome_scan_trigger.Config"` (1×), `from api.navidrome_scan_trigger import ...` (1×) | Test/Patch-Ziel/Import | bleibt unverändert (Variante A) bzw. alle 8 Ziele + Import ändern sich (Variante B/C/D) |
| `tests/test_rich_menu_handler.py::TestHandleNavidromeScan` (5 Tests) | 5× `patch("handlers.menu.rich_menu_handler.NavidromeAPI.execute_scan", ...)` | Test/Patch-Ziel | Patch-Ziel ändert sich zu `"handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan"` bei Option 2/3 (Patch geht bereits über das konsumierende Modul, nicht den Ursprungspfad — vgl. ARCH-009 Phase 8) |
| `docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md` | Prosa-Erwähnungen in „Bereits abgeschlossen“-Einträgen (Phase 3–8) | Doku (lebend) | müsste bei tatsächlicher Umsetzung ergänzt werden (nicht Teil dieser Analysephase) |
| `docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`, `ARCH-006_P2_Dependency_Graph.md`, `ARCH-008_Navidrome_Adapter_Analyse.md`, `ARCH-009_Phase3/5/6/7/8_*.md`, `ENGINEERING_BASELINE.md` | Prosa-Erwähnungen (Zeitpunkt-Snapshots vergangener Phasen) | Doku (historisch) | unverändert — historische ARCH-Dokumente werden laut etablierter Regel dieser Session nicht nachträglich umgeschrieben |

**Beantwortung der drei Leitfragen:**

- **Ist `api.navidrome_api` ausschließlich noch wegen `execute_scan()` vorhanden?**
  Ja. Seit ARCH-009 Phase 8 enthält `api/navidrome_api.py` ausschließlich
  die `execute_scan()`-Rest-Klasse — keine weitere Definition, kein
  weiterer Zweck.
- **Gibt es außer `rich_menu_handler.py` weitere Consumer?**
  Nein. Repo-weiter Grep bestätigt genau einen Produktions-Call-Site
  (`handlers/menu/rich_menu_handler.py:740`) und keine weiteren Importe
  von `api.navidrome_api` außerhalb dieser Datei und der eigenen
  Testdatei `tests/test_navidrome_api_execute_scan.py`.
- **Gibt es einen Grund, warum `api/` als Verzeichnis danach noch benötigt wird?**
  Nur wegen `api/navidrome_scan_trigger.py` — dessen Zielort ist in
  Abschnitt 3 gesondert zu klären. `api/navidrome_api.py` allein liefert
  keinen Grund mehr, `api/` zu behalten.

---

## 2. `execute_scan()` — endgültige Verantwortlichkeit

```text
NavidromeAPI.execute_scan()   (api/navidrome_api.py, @classmethod)
        ↓
NavidromeScanTrigger.run_scan()   (api/navidrome_scan_trigger.py)
```

Aktueller vollständiger Inhalt von `execute_scan()`:

```python
@classmethod
async def execute_scan(cls) -> ScanRunResult:
    log_handler_info("Starte Navidrome Scan-Prozess.", context="NavidromeAPI")
    return await NavidromeScanTrigger.run_scan()
```

Ein reiner, zustandsloser Pass-Through mit genau einer zusätzlichen
Log-Zeile.

**Ist `execute_scan()` tatsächlich noch Teil eines Navidrome-API-Adapters?**
Nein. Seit ARCH-009 Phase 8 ist die `execute_scan()`-Klasse strukturell
vom eigentlichen Adapter (`services/clients/navidrome_api.py`) getrennt —
sie war nie Teil davon und ist es auch jetzt nicht.

**Oder ist es nur noch eine historische Bridge?**
Ja, exakt das. Entstanden aus der ARCH-009-Phase-5-Entscheidung
(„dünner Pass-Through statt vollständige Entfernung“, damals gewählt, um
`handlers/menu/rich_menu_handler.py` in jenem Schritt unverändert zu
lassen) und in Phase 7/8 jeweils bewusst unangetastet weitergereicht.

**Gibt es einen architektonisch sauberen Grund, diese Bridge beizubehalten?**
Kein zwingender. Die einzige verbleibende Funktion — eine Log-Zeile vor
dem eigentlichen Scan — ließe sich ebenso in `NavidromeScanTrigger.run_scan()`
selbst unterbringen (das ohnehin bereits umfangreich mit
`context="NavidromeAPI"` loggt, siehe ARCH-009 Phase 4) oder ist
verzichtbar.

**Kann der Handler direkt `NavidromeScanTrigger.run_scan()` verwenden?**
Ja, technisch unmittelbar. Bemerkenswerter Fund: `handlers/menu/rich_menu_handler.py`
importiert bereits heute direkt `ScanTimeoutError` aus
`api.navidrome_scan_trigger` (Zeile 56, seit Phase 5) — der Handler hat
also schon jetzt **zwei getrennte Importquellen** für denselben
fachlichen Vorgang (`api.navidrome_api` für die Methode,
`api.navidrome_scan_trigger` für die Exception). Ein direkter Aufruf
würde das auf **eine einzige Importquelle** reduzieren
(`api.navidrome_scan_trigger` liefert dann sowohl `NavidromeScanTrigger`
als auch `ScanTimeoutError`) — eine Vereinfachung, kein zusätzlicher
Aufwand.

**Welche öffentliche Schnittstelle wäre danach sinnvoll?**
Keine neue nötig. `NavidromeScanTrigger.run_scan()` ist bereits die
vollständige, stabile, seit Phase 4 unveränderte öffentliche Schnittstelle
(`async classmethod`, gibt `ScanRunResult` zurück, wirft `ScanTimeoutError`/
`AttributeError`/`TypeError`).

**Welche Rückgabe-/Exception-Semantik entsteht?**
Identisch zur heutigen `execute_scan()`-Semantik — da `execute_scan()`
bereits ein 1:1-Pass-Through ist, ändert ein Entfernen der Indirektion
nichts an Rückgabewerten oder Exceptions.

**Ausdrücklich geprüft:**

- `ScanRunResult` — bleibt unverändert die Erfolgs-/Fehler-Datenstruktur,
  unabhängig von der Entscheidung.
- `ScanTimeoutError` — bleibt unverändert die Timeout-Exception,
  unabhängig von der Entscheidung.
- `tuple[bool, str]` — **bleibt entfernt** (ARCH-009 Phase 7). Keine der
  hier betrachteten Optionen führt dieses Rückgabeformat wieder ein.
- Telegram-Formatierung — bleibt in allen betrachteten Optionen
  ausschließlich in `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()`
  (ARCH-009 Phase 5, unverändert seit dort).

**Keine Umsetzung vorgenommen** — diese Bewertung ist Grundlage für das
Entscheidungsgate (Abschnitt 9), keine Handlungsanweisung.

---

## 3. Endgültige Zielposition für `NavidromeScanTrigger`

Bewertungskriterien je Variante: fachliche Verantwortlichkeit,
Abhängigkeiten, Namenskonvention, Beziehung zu `services/`, Beziehung zu
`services/clients/`, Gefahr falscher Schichtzuordnung, Testbarkeit,
zukünftige Erweiterbarkeit.

### Variante A — `api/navidrome_scan_trigger.py` bleibt bestehen (Status quo)

- **Fachliche Verantwortlichkeit:** lokale Docker-/Subprocess-/Timeout-
  Steuerung — unverändert korrekt beschrieben.
- **Abhängigkeiten:** `asyncio`, `dataclasses`, `functools`, `config` —
  keine Änderung, kein Risiko.
- **Namenskonvention:** `api/` beschreibt den verbleibenden Inhalt nicht
  mehr präzise — nach Entfernung von `execute_scan()` (Option 2/3, siehe
  Abschnitt 2) enthielte `api/` ausschließlich lokale
  Infrastruktursteuerung, keine „API“ im eigentlichen Sinn mehr (die
  echte API-Kommunikation liegt seit Phase 8 vollständig in
  `services/clients/`).
- **Beziehung zu `services/`:** keine — bewusst getrennt, wie seit
  ARCH-009 Phase 3 durchgehend gefordert.
- **Beziehung zu `services/clients/`:** keine — korrekt, da kein externer
  API-Client (bereits in Phase 3/6/8 mehrfach bestätigt).
- **Gefahr falscher Schichtzuordnung:** gering im Sinne von „wird nicht
  fälschlich für einen API-Client gehalten“, aber `api/` ist auch keine
  der drei in der Roadmap definierten Schichten
  (`services/clients/`/`services/`/`handlers/`) — es existiert als
  informelle vierte Kategorie ohne explizite Definition.
- **Testbarkeit:** unverändert gut (5 dedizierte, bereits grüne Tests in
  `tests/test_navidrome_scan_trigger.py`).
- **Zukünftige Erweiterbarkeit:** falls künftig weitere „lokale
  Infrastruktursteuerung“ für andere Dienste hinzukäme (aktuell kein
  zweiter Kandidat im Repo erkennbar), wäre der Name `api/` dafür
  semantisch irreführend.

### Variante B — `services/navidrome_scan_trigger.py`

- **Fachliche Verantwortlichkeit:** unverändert, aber `services/` ist
  laut der in dieser Roadmap dokumentierten „Übergeordneten
  Zielarchitektur“ explizit für „Anwendungs- und Fachlogik,
  Orchestrierung, Verarbeitung strukturierter Daten“ vorgesehen — lokale
  Subprocess-/Docker-Steuerung ist keine Fachlogik im eigentlichen Sinn,
  eher Infrastruktur. Teilweiser Passungskonflikt.
- **Abhängigkeiten:** unverändert, kein technisches Problem.
- **Namenskonvention:** `services/` hat aktuell **keinen Präzedenzfall**
  für eine freistehende Top-Level-Datei mit reiner
  Infrastruktursteuerung — `services/statistik_service.py` ist eine
  Fassade über fachliche Business-Logik, kein Infrastruktur-Modul;
  `services/downloader/` und `services/statistik/` sind thematische
  Unterpakete mit fachlichem Bezug.
- **Beziehung zu `services/`:** würde direkt Teil davon, aber
  thematischer Fremdkörper im Vergleich zu den übrigen Inhalten.
- **Beziehung zu `services/clients/`:** klar getrennt, kein
  Verwechslungsrisiko mit einem externen Client.
- **Gefahr falscher Schichtzuordnung:** mittel — ein künftiger Leser
  könnte `services/` fälschlich als „auch für lokale
  Infrastruktursteuerung geeignet“ interpretieren und damit die Grenze
  zwischen Fachlogik und Infrastruktur verwischen, die diese gesamte
  ARCH-009-Reihe gerade erst gezogen hat.
- **Testbarkeit:** unverändert gut.
- **Zukünftige Erweiterbarkeit:** bei weiterem Bedarf müsste erneut
  geprüft werden, ob lokale Infrastruktursteuerung dauerhaft neben
  Business-Logik in `services/` passt.

### Variante C — `services/downloader/...`

- **Fachliche Verantwortlichkeit:** `services/downloader/` ist
  ausschließlich für Musik-Download-Orchestrierung (yt-dlp, Spotify,
  Playlist-Verarbeitung) zuständig — thematisch vollständig unabhängig
  von Navidrome-Scans. Kein fachlicher Zusammenhang.
- **Abhängigkeiten:** keine Überschneidung mit bestehendem
  Downloader-Code (verifiziert — `NavidromeScanTrigger` hat keinerlei
  Bezug zu `services/downloader/`).
- **Namenskonvention:** „downloader“ im Pfad wäre für einen
  Navidrome-Scan-Trigger irreführend.
- **Beziehung zu `services/`:** technisch Teil davon, aber falsche
  Unterkategorie.
- **Beziehung zu `services/clients/`:** keine.
- **Gefahr falscher Schichtzuordnung:** hoch — würde suggerieren,
  Navidrome-Scans seien Teil der Download-Pipeline, was fachlich falsch
  ist.
- **Testbarkeit:** kein technisches Problem, aber Verzeichniskonvention
  der Tests (`test_downloader_*.py`-Muster) würde nicht passen.
- **Zukünftige Erweiterbarkeit:** keine erkennbare Notwendigkeit.
- **Fazit:** kein technischer Grund gefunden, der diese Variante
  rechtfertigt (die Aufgabenstellung verlangt hierfür ausdrücklich einen
  technischen Grund) — **nicht tragfähig**.

### Variante D — eigene, vierte Schicht (z. B. `infrastructure/`, `system/`, `local/` — Namensfindung nicht Teil dieser Analyse)

Die in dieser Roadmap dokumentierte „Übergeordnete Zielarchitektur“
enthält bereits den Satz: „Lokale Infrastruktur-, Shell- oder
Subprocess-Verantwortlichkeiten werden separat nach ihrer tatsächlichen
Aufgabe bewertet und nicht automatisch einem API-Client zugeordnet.“ Das
ist ein impliziter Hinweis darauf, dass die bestehende
Drei-Schichten-Einteilung (`services/clients/`/`services/`/`handlers/`)
für „lokale Infrastruktursteuerung“ nicht zwingend ausreicht.

- **Fachliche Verantwortlichkeit:** klar von externer API-Kommunikation,
  Business-Logik und Telegram-Präsentation unterschieden — semantisch am
  saubersten.
- **Abhängigkeiten:** unverändert.
- **Namenskonvention:** müsste komplett neu etabliert werden — kein
  Präzedenzfall im Repo, größter Namensfindungsaufwand aller vier
  Varianten.
- **Beziehung zu `services/`/`services/clients/`:** klar getrennt, kein
  Vermischungsrisiko.
- **Gefahr falscher Schichtzuordnung:** am geringsten — genau das Ziel
  der zitierten Roadmap-Aussage.
- **Testbarkeit:** unverändert.
- **Zukünftige Erweiterbarkeit:** am besten vorbereitet, **falls**
  künftig weitere „lokale Infrastruktursteuerung“ entsteht.
- **Spannungspunkt:** Aktuell existiert genau **ein** Kandidat für diese
  neue Kategorie (`NavidromeScanTrigger` selbst) — eine komplett neue
  Top-Level-Schicht für ein einzelnes Modul zu etablieren, wäre eine
  Architekturentscheidung auf Vorrat („YAGNI“-Spannung, vgl. CLAUDE.md
  Regel 18/19 zu unnötiger Vorab-Komplexität). Architektonisch am
  saubersten, aber mit Blick auf den aktuellen Repo-Bestand potenziell
  verfrüht.

---

## 4. Kann `api/` vollständig entfallen?

**Antwort hängt ausschließlich von der Kombination der Entscheidungen aus
Abschnitt 2 und Abschnitt 3 ab — nicht von Abschnitt 2 allein.**

- Wird `execute_scan()` entfernt (Abschnitt 2, Option 2/3), verschwindet
  `api/navidrome_api.py` vollständig — bestätigt durch Abschnitt 1: kein
  weiterer Inhalt, kein weiterer Consumer außer dem einen Call-Site.
- **Aber:** `api/navidrome_scan_trigger.py` bleibt in jedem Fall bestehen,
  in dem Variante A (Abschnitt 3) gewählt wird — dann behält `api/` als
  Verzeichnis weiterhin eine fachliche Berechtigung (als alleiniger
  Ort von `NavidromeScanTrigger`), auch wenn `navidrome_api.py`
  verschwindet.
- `api/` kann **nur dann** vollständig entfallen, wenn **beide**
  Entscheidungen entsprechend ausfallen: `execute_scan()` entfernt
  **und** `NavidromeScanTrigger` nach Variante B, C oder D verschoben.

**Konkret, anhand tatsächlicher Repo-Referenzen (nicht Vermutung):**

```text
Falls execute_scan() entfernt UND NavidromeScanTrigger bleibt in api/ (Variante A):
    api/
    └── navidrome_scan_trigger.py     ← einziger verbleibender Inhalt
    (api/navidrome_api.py entfällt, api/ selbst bleibt als 1-Datei-Paket bestehen)

Falls execute_scan() entfernt UND NavidromeScanTrigger verschoben (Variante B/C/D):
    api/  ← vollständig leer, könnte inkl. api/__init__.py entfallen

Falls execute_scan() NICHT entfernt (Option 1, Status quo):
    api/ bleibt in jedem Fall in der heutigen Form bestehen,
    unabhängig von der NavidromeScanTrigger-Entscheidung.
```

**Noch nichts gelöscht — diese Aussage ist ausschließlich analytisch.**

---

## 5. Zielarchitektur — Vorher-/Nachher-Darstellung

### Ist-Zustand (nach ARCH-009 Phase 8)

```text
handlers/
    ├── navidrome_menu_handler.py
    │        └── services.clients.navidrome_api.NavidromeAPI
    │                 (6 Adapter-Methoden, Instanz+DI)
    │
    └── menu/rich_menu_handler.py
             ├── api.navidrome_api.NavidromeAPI.execute_scan()
             │        └── api.navidrome_scan_trigger.NavidromeScanTrigger.run_scan()
             └── api.navidrome_scan_trigger.ScanTimeoutError  (direkter Zweitimport)

services/
    ├── clients/
    │     └── navidrome_api.py   ← reiner externer Integrationsadapter (Phase 8)
    │
    └── statistik/
          └── play_history_poller.py
                   └── services.clients.navidrome_api.NavidromeAPI (via DI)

api/
    ├── navidrome_api.py          ← nur noch execute_scan() (Bridge-Rest)
    └── navidrome_scan_trigger.py ← lokale Docker-/Subprocess-/Timeout-Steuerung
```

**Zwei separate `NavidromeAPI`-Klassendefinitionen bestehen aktuell
gleichzeitig** (`api.navidrome_api.NavidromeAPI` mit nur `execute_scan()`,
`services.clients.navidrome_api.NavidromeAPI` mit den sechs
Adapter-Methoden) — bewusste, dokumentierte Konsequenz der
Phase-8-Entscheidung (Option B), kein Versehen.

### Empfohlene Zielstruktur (siehe Abschnitt 8 für die vollständige Optionsabwägung)

```text
handlers/
    ├── navidrome_menu_handler.py
    │        └── services.clients.navidrome_api.NavidromeAPI  (unverändert)
    │
    └── menu/rich_menu_handler.py
             └── api.navidrome_scan_trigger.NavidromeScanTrigger.run_scan()
                      (direkter Aufruf statt execute_scan()-Bridge;
                       ScanTimeoutError aus derselben, bereits heute
                       genutzten Importquelle)

services/
    ├── clients/
    │     └── navidrome_api.py   ← unverändert, reiner Integrationsadapter
    │
    └── statistik/
          └── play_history_poller.py   ← unverändert

api/
    └── navidrome_scan_trigger.py   ← einziger verbleibender Inhalt
        (api/navidrome_api.py entfällt vollständig;
         Zielort von navidrome_scan_trigger.py selbst: siehe Abschnitt 8 —
         Empfehlung „vorerst in api/ belassen“, siehe Spannungspunkt
         Variante D in Abschnitt 3)
```

**Schichttrennung:**

```text
services/clients/  → externe API-Integration (Subsonic/HTTP)     ✅ bereits vollständig erreicht (Phase 8)
services/           → interne fachliche/technische Services       ✅ unverändert (statistik/, downloader/)
handlers/           → Telegram-Präsentation und Benutzerinteraktion ✅ unverändert (Phase 5/7/8)
api/ (Rest)         → lokale Infrastruktur-/Subprocess-Steuerung, bewusst außerhalb der drei
                       obigen Schichten (siehe Abschnitt 3, Variante A vs. D)
```

Die Drei-Schichten-Einteilung reicht für `NavidromeScanTrigger` nicht
vollständig aus (Abschnitt 3) — die Roadmap selbst sieht das bereits vor
(„werden separat … bewertet“). Eine vierte, explizit benannte Schicht
(Variante D) wäre die architektonisch konsequenteste Lösung, ist aber
angesichts von aktuell nur einem einzigen Bewohner-Modul möglicherweise
verfrüht (siehe Spannungspunkt in Abschnitt 3).

---

## 6. Verbleibende ARCH-009-Altlasten

| Fund | Muss in Phase 9 behoben werden? | Spätere eigene Aufgabe? | Bewusst behalten? |
|---|---|---|---|
| `_check_connection()`-Altfund (`NavidromeAPI is not None`, strukturell immer `True`, BUG-007) | Nein — unabhängig von `execute_scan()`/`NavidromeScanTrigger`, betrifft nur `handlers/navidrome_menu_handler.py` | Ja, eigenständig | — |
| Historische Docstring-/Kommentarreferenzen auf `api.navidrome_api`/`api.navidrome_scan_trigger` in ~10 ARCH-Dokumenten | Nein | — | Ja, laut etablierter Regel dieser Session (historische Snapshots) |
| Alte Testnamen (`test_navidrome_api_execute_scan.py`, `test_navidrome_scan_trigger.py`) | Nein (Analysephase) | Ja, direkt an die eigentliche Umsetzung gekoppelt | — |
| Alte Patch-Ziele (8× in `test_navidrome_scan_trigger.py`, 5× in `test_rich_menu_handler.py`) | Nein (Analysephase) | Ja, direkt an die eigentliche Umsetzung gekoppelt | — |
| `api.navidrome_api`-Referenzen (Abschnitt 1) | Nein (Analysephase) | Ja, direkt an die eigentliche Umsetzung gekoppelt | — |
| `execute_scan()`-Bridge | Bewertet (Abschnitt 2), nicht behoben | Umsetzung nach Entscheidungsgate | — |
| `NavidromeScanTrigger`-Zielort | Bewertet (Abschnitt 3), nicht behoben | Umsetzung nach Entscheidungsgate | — |
| Doppelte `NavidromeAPI`-Definitionen (`api.navidrome_api.NavidromeAPI` vs. `services.clients.navidrome_api.NavidromeAPI`) | Nein — löst sich automatisch auf, sobald `execute_scan()` entschieden ist (kein eigenständiges Problem) | Gekoppelt an `execute_scan()`-Entscheidung | — |

---

## 7. Test- und Migrationsrisiko (für eine mögliche spätere Umsetzung)

**Falls `execute_scan()` entfernt wird (Option 2/3 aus Abschnitt 8):**

- Anzupassende Tests: `tests/test_rich_menu_handler.py::TestHandleNavidromeScan`
  (5 Tests, Patch-Ziel-Wechsel `NavidromeAPI.execute_scan` →
  `NavidromeScanTrigger.run_scan`).
- Entfallende Tests: `tests/test_navidrome_api_execute_scan.py` (4 Tests) —
  vollständig redundant zu `tests/test_navidrome_scan_trigger.py`, das
  dasselbe Verhalten von `run_scan()` bereits direkt testet.
- Zu ändernde Consumer: genau 1 (`handlers/menu/rich_menu_handler.py`) —
  1 Importzeile entfällt, 1 Importzeile bleibt/ändert sich je nach
  `NavidromeScanTrigger`-Entscheidung, 1 Aufrufzeile ändert sich.
- API-/Vertragsänderungen: keine (Abschnitt 2 — reiner Pass-Through wird
  entfernt, Rückgabe-/Exception-Semantik bleibt identisch).
- Breaking Changes: keine (keine öffentliche, von außen sichtbare
  Schnittstelle betroffen — rein interne Python-Importpfade).

**Zusätzlich falls `NavidromeScanTrigger` verschoben wird (Variante B/C/D):**

- Zu ändernde Tests: `tests/test_navidrome_scan_trigger.py` (8
  String-Patch-Ziele + 1 Importzeile).
- Zu ändernder Consumer: `handlers/menu/rich_menu_handler.py`s
  `ScanTimeoutError`-Import (Pfad ändert sich).
- `api/`-Verzeichnis (inkl. `api/__init__.py`) könnte vollständig
  entfallen (Abschnitt 4).

**Sinnvoller Migrationsweg ohne Bridge:** Ja — bereits im Phase-8-Schritt
etabliertes, funktionierendes Muster (direkter Cutover ohne
Kompatibilitäts-Bridge), hier sogar mit noch kleinerem Blast Radius (1
Consumer, exakt 1 Call-Site).

**Kann die Migration in einem kleinen, isolierten Commit erfolgen?** Ja —
falls nur `execute_scan()` entfernt wird (Option 2), ist dies einer der
kleinsten Migrationsschritte der gesamten ARCH-009-Reihe (kleiner als
Phase 4, 5 oder 8). Wird zusätzlich `NavidromeScanTrigger` verschoben
(Option 3), wächst der Schritt moderat (2 zusätzliche Dateien + 8
Patch-Ziele), bleibt aber deutlich kleiner als Phase 8.

---

## 8. Klare Empfehlung

### Empfohlene Zielarchitektur

- **`execute_scan()`:** entfernen, `handlers/menu/rich_menu_handler.py`
  ruft `NavidromeScanTrigger.run_scan()` direkt auf (Abschnitt 2).
- **`NavidromeScanTrigger`:** vorerst in `api/` belassen (Variante A) —
  architektonisch reinste Lösung wäre Variante D (eigene Schicht), aber
  mit nur einem aktuellen Kandidaten-Modul erscheint das verfrüht
  (Abschnitt 3, Spannungspunkt). Diese Empfehlung ist die einzige in
  diesem Dokument, die bewusst *nicht* die architektonisch „reinste“,
  sondern die pragmatisch angemessenste Variante vorschlägt.
- **`api/navidrome_api.py`:** vollständig entfernen (kein Inhalt mehr
  nach Entfernung von `execute_scan()`).
- **`api/`:** bleibt als Verzeichnis bestehen, reduziert auf die eine
  Datei `navidrome_scan_trigger.py`.
- **Verbleibende Imports:** `handlers/menu/rich_menu_handler.py` bezieht
  `NavidromeScanTrigger` und `ScanTimeoutError` künftig aus derselben,
  bereits heute teilweise genutzten Quelle `api.navidrome_scan_trigger`.
- **Notwendige Consumer-Migration:** ausschließlich
  `handlers/menu/rich_menu_handler.py` (1 Datei).

### Variantenvergleich

| Option | Vorteil | Nachteil | Risiko | Empfehlung |
|---|---|---|---|---|
| **1 — Status quo** (nichts weiter tun) | null Aufwand, null Risiko | doppelte `NavidromeAPI`-Definition bleibt; `api/` bleibt namentlich irreführend (enthält keine „API“ mehr); historische Bridge ohne verbleibenden Zweck bleibt bestehen | keins | nur falls keine weitere Bereinigung gewünscht ist |
| **2 — `execute_scan()` entfernen, `NavidromeScanTrigger` bleibt in `api/`** | löst doppelte `NavidromeAPI`-Definition auf; vereinfacht `rich_menu_handler.py`s Imports auf eine Quelle; kleinster mögliche isolierte Schritt (1 Consumer, 1 Call-Site); `api/navidrome_api.py` entfällt vollständig | `api/` bleibt als Ein-Datei-Paket bestehen, Namensfrage (Abschnitt 3) bleibt offen | gering — kleiner, gut testbarer Schritt, Muster bereits aus Phase 5/8 bekannt | **empfohlen** |
| **3 — `execute_scan()` entfernen UND `NavidromeScanTrigger` verschieben (Variante B/C/D)** | vollständige Auflösung von `api/` als Verzeichnis; sauberste Namensgebung | bündelt zwei unabhängige Entscheidungen in einem Schritt (widerspricht dem in dieser Session durchgehend befolgten Kleinschritt-Prinzip); Namensfindung für neue Kategorie ohne Präzedenzfall nötig | mittel — mehr Dateien/Importe gleichzeitig betroffen | möglich, aber eher als eigener Folgeschritt **nach** Option 2, falls überhaupt gewünscht |

---

## 9. ENTSCHEIDUNGSGATE

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde vorgenommen.**

Es wird **nicht selbstständig** mit einer Umsetzung begonnen. Folgende
Punkte werden ausdrücklich zur Nutzerentscheidung vorgelegt:

1. **Zielposition `NavidromeScanTrigger`:** Variante A (in `api/`
   belassen, empfohlen), B (`services/`), C (`services/downloader/`,
   nicht tragfähig laut Analyse), D (eigene, neu zu benennende Schicht)?
2. **`execute_scan()`:**
   - behalten (Option 1, Status quo), oder
   - direkt durch `NavidromeScanTrigger.run_scan()` ersetzen (Option
     2/3, empfohlen), oder
   - andere Variante?
3. **`api/navidrome_api.py`:** entfernen (folgt zwingend aus Punkt 2,
   falls „ersetzen“ gewählt wird) oder weiterführen (folgt zwingend aus
   Punkt 2, falls „behalten“ gewählt wird)?
4. **`api/`:** vollständig entfernen (nur möglich, falls Punkt 1 = B/C/D
   **und** Punkt 2 = „ersetzen“) oder behalten (in jedem anderen Fall)?
5. **Notwendige Consumer-/Test-Migration:** Zustimmung zum in Abschnitt 7
   beschriebenen Umfang (1 Consumer-Datei, Wegfall von 4 redundanten
   Tests, Anpassung von 5 Patch-Zielen in `test_rich_menu_handler.py`,
   zusätzlich 8 Patch-Ziele + Import in `test_navidrome_scan_trigger.py`
   nur falls Punkt 1 ≠ A)?
6. **Ein Schritt oder mehrere isolierte Schritte?** Falls sowohl Punkt 2
   („ersetzen“) als auch Punkt 1 (B/C/D) gewählt werden — in einem
   kombinierten Schritt oder in zwei getrennten (erst `execute_scan()`
   entfernen, dann `NavidromeScanTrigger` separat verschieben)?

**Abweichung von der bestehenden Roadmap-Reihenfolge:**
`docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md` beschreibt
„Phase 9 — Finaler Navidrome-Migrationsabschluss“ bislang als reine
Abschlussverifikation (Regressionstest, Import-Audit,
Dokumentationsaktualisierung, PR/Merge) **nach** bereits getroffenen
Migrationsentscheidungen — sie sah bislang keinen eigenen
Analyse-/Entscheidungsschritt für `execute_scan()`/`NavidromeScanTrigger`
vor. Diese Phase-9-Analyse liefert genau diese noch fehlende
Entscheidungsgrundlage nachträglich. Kein Widerspruch zur Roadmap, aber
eine Ergänzung, die dort bislang nicht explizit vorgesehen war — wird
hier ausgewiesen, nicht eigenmächtig in der Roadmap umnummeriert oder
umgeschrieben (wie vorgegeben).

**Erst nach ausdrücklicher Nutzerentscheidung darf Code geändert
werden.**

---

## Umsetzung A (2026-08-24, Branch `arch/arch-009-phase9-execute-scan-elimination`)

Nutzerentscheidung: Option 2 aus Abschnitt 8 (`execute_scan()` entfernen,
`NavidromeScanTrigger` vorerst unverändert in `api/` belassen — Punkt 1
des Entscheidungsgates ausdrücklich **nicht** in diesem Schritt
entschieden, bleibt separate Folgeanalyse).

### 1. Consumer migriert

`handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()`:

- Import geändert: `from api.navidrome_api import NavidromeAPI` +
  `from api.navidrome_scan_trigger import ScanTimeoutError` →
  `from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanTimeoutError`
  (eine statt zwei Importquellen, wie in Abschnitt 2 vorhergesagt).
- Aufruf geändert: `await NavidromeAPI.execute_scan()` →
  `await NavidromeScanTrigger.run_scan()`.
- Telegram-Präsentationslogik (Erfolg/Fehlschlag/Timeout/generische
  Exception, Emojis, MarkdownV2-Escaping) **byte-identisch** belassen —
  keine einzige sichtbare Nutzertext-Änderung, keine Logik zurück nach
  `NavidromeScanTrigger` verlagert.

### 2. `api/navidrome_api.py` entfernt

Vollständig gelöscht (`git rm`). Dependency-Audit nach der Änderung
(Abschnitt „Dependency-Audit nach der Umsetzung“ unten) bestätigt: keine
funktionale Referenz auf `api.navidrome_api` mehr im Repo.

### 3. `api/__init__.py` geprüft

War bereits leer (0 Bytes, keine Re-Exports) — keine Änderung nötig.
`api/` bleibt bestehen, enthält jetzt ausschließlich
`navidrome_scan_trigger.py` — wie in Abschnitt 4 der Analyse als einer
der beiden möglichen Zustände vorhergesagt.

### 4. Tests angepasst

- **Entfernt:** `tests/test_navidrome_api_execute_scan.py` (4 Tests) —
  testete ausschließlich die jetzt entfernte Bridge-Klasse
  (`api.navidrome_api.NavidromeAPI.execute_scan()`); Abdeckung war
  bereits laut Abschnitt 7 der Analyse vollständig redundant zu
  `tests/test_navidrome_scan_trigger.py` (testet Erfolg/Fehlschlag/
  Timeout/fehlenden Scan-Befehl von `NavidromeScanTrigger.run_scan()`
  bereits direkt) — keine Nettoabdeckung verloren.
- **Angepasst:** `tests/test_rich_menu_handler.py::TestHandleNavidromeScan`
  (5 Tests, unverändert in der Anzahl) — alle 5 Patch-Ziele von
  `"handlers.menu.rich_menu_handler.NavidromeAPI.execute_scan"` auf
  `"handlers.menu.rich_menu_handler.NavidromeScanTrigger.run_scan"`
  umgestellt (Patch geht weiterhin über das konsumierende Modul, nicht
  den Ursprungspfad — unverändertes Muster seit ARCH-009 Phase 8). Alle
  vier sichtbaren Nachrichtenvarianten weiterhin einzeln verifiziert.
- **Unverändert:** `tests/test_navidrome_scan_trigger.py` (5 Tests) —
  nicht angefasst, wie vorgegeben (`NavidromeScanTrigger` bleibt in
  diesem Schritt unverändert).
- Keine Testabdeckung reduziert, keine unnötigen Tests gelöscht.

### 5. Dependency-Audit nach der Umsetzung

Repo-weit geprüft: `api.navidrome_api` (Import-Statements), `execute_scan(`,
`mock.patch(...)`-Ziele, dynamische Imports (`importlib`/`__import__`),
Testreferenzen.

- **0** verbleibende `from api.navidrome_api import ...`/`import api.navidrome_api`-Statements.
- **0** verbleibende `mock.patch(...)`-Ziele auf die entfernte Klasse.
- **0** dynamische Imports gefunden (weder vorher noch nachher).
- Verbleibende Treffer für den String „api.navidrome_api“/„execute_scan(“
  sind ausschließlich historische Prosa in Docstrings/Kommentaren (u. a.
  in `api/navidrome_scan_trigger.py`s eigenem, unverändert gelassenem
  Docstring, sowie in Testdatei-Kopfkommentaren) — keine funktionale
  Wirkung, bewusst nicht angefasst.
- `python3 -c "import api.navidrome_api"` schlägt jetzt erwartungsgemäß
  mit `ModuleNotFoundError` fehl — bestätigt die vollständige Entfernung.

**Ergebnis: keine funktionale Referenz auf `api.navidrome_api` mehr im
Repo vorhanden.**

### 6. Regression

**Gezielt:** `tests/test_rich_menu_handler.py` + `tests/test_navidrome_scan_trigger.py`
— 38 Tests grün.

**Vollständig:** 1008 bestanden (vorher 1012 — Differenz von 4 entspricht
exakt den 4 entfernten, redundanten Bridge-Tests aus
`tests/test_navidrome_api_execute_scan.py`), unverändert dieselben **15
bekannten Vorbestand-Fehler** (`test_auto_learn.py`,
`test_metadata_modules.py`, `test_suite.py` RichMenuSystem/
MenuIntegration), keine neuen Fehlschläge.

### 7. Import-Smoke-Test

`handlers.menu.rich_menu_handler`, `api.navidrome_scan_trigger`,
`services.clients.navidrome_api` gemeinsam erfolgreich importierbar,
keine Zirkelabhängigkeiten.

### Verbleibender Zustand von `api/`

```text
api/
└── navidrome_scan_trigger.py   ← einziger verbleibender Inhalt
```

`api/navidrome_api.py` existiert nicht mehr. `api/` selbst bleibt
bestehen (wie in Abschnitt 3/4 der Analyse als möglicher Zustand
vorhergesagt) — der endgültige Zielort von `NavidromeScanTrigger` ist
weiterhin offen.

### Offener Folgeentscheid

> **ARCH-009 Folgeanalyse — endgültiger Zielort von `NavidromeScanTrigger`**

Bewusst nicht Teil dieses Schritts (siehe Abschnitt 3 der Analyse:
Varianten A–D, Empfehlung „vorerst in `api/` belassen“, aber ausdrücklich
als eigene, spätere Entscheidung markiert). Wird separat entschieden.

**ARCH-009 Phase 9, Umsetzung A, damit abgeschlossen.**
