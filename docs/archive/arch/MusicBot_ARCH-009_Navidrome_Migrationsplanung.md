# ARCH-009 — `NavidromeAPI`: Entflechtungs-/Migrationsplanung (Entscheidungsvorlage)

Reine Planung, keine Codeänderung, keine Verschiebung nach
`services/clients/`. Vertieft ARCH-008 gezielt in den drei angeforderten
Bereichen: Telegram-Formatierung, `execute_scan()`/Subprocess, spätere
Client-Struktur/DI.

---

## 0. Wichtigster Zusatzbefund: die Hälfte der Klasse ist totes Gewicht

Vor der eigentlichen Entflechtungsfrage ein Fund, der die ganze Planung
prägt. Von 12 öffentlichen Methoden in `NavidromeAPI` (614 Zeilen) haben
**7 keinen einzigen Produktions-Consumer** — nur die Definition selbst
und Charakterisierungstests (per Grep über das gesamte Repo verifiziert):

| Methode | Consumer im Produktionscode |
|---|---|
| `format_full_status_message()` | **keiner** |
| `format_rescan_status_message()` | **keiner** |
| `format_web_interface_url_message()` | **keiner** |
| `test_api()` | **keiner** |
| `get_scan_status()` | **keiner** (auch nicht indirekt über `get_full_server_info()`, siehe unten) |
| `get_full_server_info()` | **keiner** |
| `check_connection()` | **keiner** — mit dokumentiertem Grund, siehe 0.1 |

Aktiv genutzt: `make_request()` (Kern, direkt + indirekt), `get_artists()`,
`search()`, `get_now_playing()` (über `play_history_poller.py`),
`execute_scan()`, `_build_url()` (intern von `make_request()`).

### 0.1 `check_connection()` — bewusst unbenutzt, nicht vergessen

`handlers/navidrome_menu_handler.py::_initialize_api()` enthält einen
bereits dokumentierten Befund aus einer früheren Session (BUG-007-Fix):

> „Ein voller Verbindungstest (`NavidromeAPI.check_connection()`) wäre
> ein größerer, async-basierter Umbau — hier zunächst der kleinere,
> eindeutig richtige Fix: tatsächlich konfigurierte (nicht-leere) Werte
> prüfen.“

D. h. `check_connection()` wurde bewusst zurückgestellt, nicht vergessen
— `_check_connection()` im Handler ist ein simpler synchroner
Config-Wert-Check (`self.connection_status and NavidromeAPI is not None`),
kein Aufruf der echten API-Methode.

### 0.2 Konsequenz für die Planung

Die ursprüngliche ARCH-008-Einschätzung „Telegram-Formatierung muss nach
`handlers/` migriert werden“ ist zu präzisieren: Da diese Methoden **keine
Produktions-Consumer** haben, ist die richtige Frage nicht „wohin
verschieben“, sondern zunächst „behalten (unvollendetes Feature, z. B.
ein geplanter `/navidrome_status`-Admin-Command) oder entfernen (totes
Gewicht, analog ARCH-003/P-1 `FileUtils`)“ — das ist eine Tatsachenfrage,
die nur der Nutzer beantworten kann (Präzedenzfall: P-14
`advanced_podcast_finder.py`, LEGACY-011 `services/organizer.py` — beide
wurden explizit nachgefragt statt automatisch als Legacy eingestuft).

---

## 1. Telegram-Formatierung — Befund und Empfehlung

`format_full_status_message()`, `format_rescan_status_message()`,
`format_web_interface_url_message()`: bauen MarkdownV2-Text
(`escape_md_v2`, `EMOJI`) aus Daten, die von den ebenfalls toten Methoden
`get_full_server_info()`/`get_scan_status()` stammen. `test_api()`
vermischt zusätzlich einen echten API-Call mit Text-Bau.

**Da alle vier Methoden 0 Produktions-Consumer haben, ist eine
„Migration“ im Sinne von Verschieben nach `handlers/` nicht sinnvoll** —
es gibt nichts Aktives zu migrieren. Zwei Möglichkeiten:

- **(a) Entfernen** (falls Nutzer bestätigt: kein geplantes Feature) —
  analog P-1/P-14.
- **(b) Als eigenständiges, noch nicht verdrahtetes Feature behalten**,
  aber dann konsequent aus `NavidromeAPI` heraus in eine eigene
  Formatierungs-Funktion/Modul verschieben (z. B.
  `handlers/navidrome_status_formatting.py` oder Teil von
  `handlers/navidrome_menu_handler.py`), damit `NavidromeAPI` auch für
  dieses Feature telegram-frei bleibt — dann aber nur, wenn/wann das
  Feature tatsächlich verdrahtet wird, nicht vorab auf Vorrat.

**Empfehlung:** zuerst (a) klären. Nur falls der Nutzer sagt „das ist ein
geplantes Feature, will ich behalten“, wird (b) zum eigentlichen
Migrationsschritt.

---

## 2. `execute_scan()`/Subprocess-Verantwortung — Befund und Empfehlung

```python
NAVIDROME_SCAN_COMMAND = f"docker exec navidrome /app/navidrome scan --full"
```

`execute_scan()` ist **kein Subsonic-API-Call** — es führt einen lokalen
Shell-Befehl aus (`asyncio.create_subprocess_shell`), der den
Navidrome-Docker-Container anweist, einen Rescan durchzuführen. Das ist
Infrastruktur-/Prozesssteuerung auf dem Host, nicht Kommunikation mit dem
Navidrome-HTTP-Server. Konzeptionell gehört das nicht in einen „API-Client“
im `services/clients/`-Sinn (der für externe REST/HTTP-Kommunikation
gedacht ist).

**Sicherheitsaspekt (dokumentiert, kein akuter Fund):**
`create_subprocess_shell` statt `create_subprocess_exec` mit Argument-Liste
ist grundsätzlich ein Shell-Injection-anfälliges Muster. Aktuell
unkritisch, da `NAVIDROME_SCAN_COMMAND` ein statischer Config-Fixwert
ohne Nutzereingabe ist — aber eine spätere Trennung macht dieses Risiko
sichtbarer und leichter zu kontrollieren (eigene, kleine, auditierbare
Klasse statt Teil eines großen API-Adapters).

**Empfehlung:** eigene, kleine Klasse/Funktion, getrennt von der reinen
API-Kommunikationsklasse — z. B. `NavidromeScanTrigger` oder
`NavidromeMaintenanceOps` mit einer Methode `run_full_scan()`. Bewusst
**nicht** Teil des künftigen `services/clients/`-Adapters (andere
Fehlerklasse: Subprocess-/Timeout-Fehler statt HTTP-Fehler; andere
Sicherheitsbetrachtung: lokale Prozessausführung statt Netzwerk-Call).
Wo diese Klasse landet, ist Teil der noch nicht getroffenen
Verschiebungsentscheidung — vorerst bleibt sie im bestehenden `api/`-
Verzeichnis oder unmittelbar daneben, bis auch dafür eine bewusste
Zielentscheidung fällt.

---

## 3. Spätere Client-Struktur/DI — Befund und Empfehlung

### 3.1 Aktueller Zustand

`NavidromeAPI` ist eine reine `@classmethod`/`@staticmethod`-Klasse ohne
Instanz, ohne `__init__`, ohne Dependency Injection. `_auth_params` ist
ein Klassenattribut, dessen Wert **beim Modul-Import** ausgewertet wird
(`_get_navidrome_config()` läuft zur Klassendefinitionszeit) — ein
Modul-Level-Seiteneffekt, den keiner der drei P-11-Clients
(`GeniusClient`/`LastFMClient`/`MusicBrainzClient`, alle mit
`__init__(self, logger=...)`, lazy Config-Ladung) hat.

### 3.2 Warum das heute trotzdem funktioniert

`services/statistik/play_history_poller.py` erwartet ein injiziertes
`self.api`-Objekt und ruft `self.api.get_now_playing()` auf
(Duck-Typing) — das funktioniert bereits heute mit der Klasse
`NavidromeAPI` selbst als „Instanz-Ersatz“ (Classmethods sind über die
Klasse aufrufbar, `NavidromeAPI()` erzeugt trivial eine funktionsfähige
Instanz). DI ist hier also bereits pragmatisch gelöst, ohne dass die
Klasse ihre klassische Struktur ändern musste.

### 3.3 Zielbild für eine spätere echte DI-Struktur (nicht Teil dieser Entscheidung)

Nach Entflechtung (Abschnitt 1+2) bliebe ein schlanker Rest:
`make_request`, `_build_url`, `get_artists`, `search`, `get_now_playing`
(+ `check_connection`, falls behalten). Zielstruktur, analog zu den
P-11-Clients:

```python
class NavidromeClient:
    def __init__(self, config=None, logger=None):
        self.config = config or get_config()
        self.logger = logger or get_module_logger("NavidromeClient")
        self._auth_params = {
            "u": self.config.NAVIDROME_USER,
            "p": self.config.NAVIDROME_PASS,
            ...
        }
    def make_request(self, endpoint, params=None): ...
    async def get_artists(self): ...
    async def search(self, query): ...
    async def get_now_playing(self): ...
```

**Größter Blast Radius im gesamten Vorhaben:** `handlers/navidrome_menu_handler.py`
ruft an **12+ Stellen** `NavidromeAPI.make_request(...)`/`.get_artists()`/
`.search(...)` als statische Klassenmethoden auf. Eine Umstellung auf
echte Instanz-DI erfordert dort überall entweder eine injizierte
Instanz (Konstruktor-Parameter) oder eine Kompatibilitäts-Fassade
(analog zum `StatistikService`-Facade-Muster aus P-6). Das ist bewusst
**kein Teil dieser Migrationsplanung** — eigener, separater, künftiger
Schritt.

---

## 4. Entscheidungsvorlage: empfohlenes Zielbild

**Empfohlenes Zielbild (Endzustand nach allen Phasen, nicht auf einmal umgesetzt):**

```
api/
  navidrome_client.py       — reiner API-Adapter (make_request, get_artists,
                               search, get_now_playing, ggf. check_connection),
                               echte Instanz + DI, Config lazy in __init__
  navidrome_scan_trigger.py — execute_scan() (Docker-Subprocess), getrennt
                               von der API-Kommunikation
(Telegram-Formatierungsmethoden: entfernt, falls Nutzer bestätigt totes
 Gewicht — sonst als Feature explizit in handlers/ neu gebaut, wenn
 gebraucht)
```

Verschiebung nach `services/clients/` ist ausdrücklich **nicht** Teil
dieses Zielbilds-Schritts — das bleibt eine eigene, spätere Entscheidung
(wie vom Nutzer vorgegeben), da `NavidromeAPI` primär von `handlers/`
direkt konsumiert wird (anders als die P-11-Kandidaten, die
ausschließlich von `services/`-internem Code genutzt wurden — siehe
ARCH-008 Abschnitt 2).

---

## 5. Alternativen

### Alternative A — Gestufte Entflechtung (empfohlen)

Vier unabhängige Phasen (Abschnitt 6), jede mit eigenem Stop/Nutzer-
entscheidung. Kleinster Blast Radius pro Schritt, jederzeit abbrechbar,
konsistent mit dem in dieser Session etablierten Vorgehen (P-1, P-11,
P-14, P-2).

### Alternative B — Minimal-invasiv (nur Dokumentation)

Keine Code-Änderung. Die Vermischung bleibt bestehen, wird nur explizit
als bekanntes Risiko dokumentiert (dieses Dokument selbst erfüllt das
bereits). Geringstes Risiko, löst aber nichts — die durch P-11 etablierte
`services/clients/`-Konvention bleibt für `NavidromeAPI` unerreichbar,
solange die Vermischung besteht.

### Alternative C — Alles in einem Rutsch

Tote Methoden entfernen + `execute_scan()` auslagern + Verschiebung nach
`services/clients/` + DI-Umstellung + alle 12+ Consumer-Stellen anpassen
in einem einzigen, großen Schritt. **Nicht empfohlen** — widerspricht
CLAUDE.md-Regel 18 („kein großer Refactor als erste Reaktion“), bündelt
mehrere unabhängige Risiken (tote-Code-Fehleinschätzung,
Subprocess-Sicherheit, großflächige Consumer-Anpassung) in einem PR ohne
Zwischen-Stops.

---

## 6. Risiken

1. **Tote-Methoden-Fehleinschätzung**: Eine der 7 als „tot“ identifizierten
   Methoden könnte doch für ein geplantes, noch nicht fertiggestelltes
   Feature gedacht sein (spekulativ, kein Beweis in beide Richtungen
   außer bei `check_connection()`, siehe 0.1). Mitigation: explizite
   Nutzerentscheidung pro Methode/Gruppe vor jeder Entfernung
   (Präzedenzfall P-14/LEGACY-011).
2. **`execute_scan()`-Verschiebung**: Docker-Subprocess-Ausführung ist
   sicherheitsrelevant (Shell-Injection-Muster, siehe Abschnitt 2).
   Mitigation: Timeout-Verhalten und Fehlerbehandlung 1:1 erhalten,
   Regressionstests vor der Verschiebung sichern (bereits 4 Tests in
   `tests/test_navidrome_api_characterization.py` vorhanden).
3. **Spätere DI-Umstellung**: größter Blast Radius (12+ Stellen in
   `handlers/navidrome_menu_handler.py`). Mitigation: eigener,
   nachgelagerter Schritt, ggf. mit Facade-Muster (analog P-6), nicht
   Teil dieser Planung.
4. **Testaufwand**: 22 bestehende Tests
   (`tests/test_navidrome_api_characterization.py`,
   `test_navidrome_api_logging.py`, `test_navidrome_api_timeout.py`)
   müssen je Phase entsprechend angepasst/aufgeteilt werden — gute
   Ausgangsbasis, aber nicht vernachlässigbarer Aufwand.

---

## 7. Schrittweise Migration (vier Phasen, je eigener Stop)

**Phase 1 — Tote-Methoden-Entscheidung** (reine Entscheidung, kein Code):
Nutzer entscheidet für `format_full_status_message()`,
`format_rescan_status_message()`, `format_web_interface_url_message()`,
`test_api()`, `get_scan_status()`, `get_full_server_info()`,
`check_connection()` je einzeln oder gruppiert: behalten oder entfernen.

**Phase 2 — Entfernung** (nur für als „entfernen“ bestätigte Methoden):
Methoden + zugehörige Charakterisierungstests entfernen, Regressionslauf.
Analog zu P-1 (`FileUtils`) — reine Bereinigung, kein neues Verhalten,
da 0 Produktions-Consumer.

**Phase 3 — `execute_scan()`-Auslagerung**: eigene Klasse/Modul für die
Docker-Subprocess-Steuerung, `handlers/menu/rich_menu_handler.py:727`
entsprechend angepasst (Import-Pfad, ggf. Instanzierung). Bestehende
4 Charakterisierungstests dafür migrieren. Regressionslauf.

**Phase 4 — Verbleibender reiner Adapter** (separate, spätere
Entscheidung, **nicht Teil dieser Planung**): erst hier wird über
Zielposition (`services/clients/` oder woanders) und echte DI-Struktur
entschieden — abhängig davon, wie Phase 1-3 ausgefallen sind.

Jede Phase ist unabhängig abbrechbar; nach Phase 1 könnte sich
herausstellen, dass der Umfang kleiner ist als hier angenommen (falls der
Nutzer mehrere der 7 Methoden behalten will).
