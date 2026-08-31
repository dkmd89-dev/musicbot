# ARCH-009 Phase 6 — Zielposition und DI von `NavidromeAPI`: Analyse

Reine Analysephase gemäß `docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
Phase 6. Keine Codeänderung, keine Verschiebung, keine DI-Umstellung.
Bewertet den nach ARCH-009 Phase 1–5 tatsächlich verbleibenden
`NavidromeAPI`-Kern gegen die etablierte Konvention:

> `services/clients/` = reine externe Integrationsadapter, keine
> Telegram-Präsentation und keine fachliche Orchestrierung.

---

## 1. Welche Methoden sind nach Phase 5 tatsächlich noch in `NavidromeAPI`?

Sieben Methoden (614 Zeilen zu Beginn von ARCH-009 → 223 Zeilen heute):

| Methode | Typ | Zeilen (ca.) |
|---|---|---|
| `_build_url()` | `@staticmethod`, intern | 54-65 |
| `make_request()` | `@classmethod` | 67-114 |
| `check_connection()` | `@classmethod async` | 116-133 |
| `execute_scan()` | `@classmethod async` | 135-151 |
| `get_artists()` | `@classmethod async` | 153-168 |
| `get_now_playing()` | `@classmethod async` | 175-214 |
| `search()` | `@classmethod async` | 216-222 |

Keine `@staticmethod`/`@classmethod`-fremde Struktur, kein `__init__`,
kein Instanzzustand — unverändert seit vor ARCH-009.

---

## 2. Welche davon sind reine Navidrome-API-Kommunikation?

| Methode | Reine API-Kommunikation? | Begründung |
|---|---|---|
| `_build_url()` | ja | reine URL-Konstruktion |
| `make_request()` | ja | HTTP-Kern, einzige Stelle mit echtem `requests.get()` |
| `check_connection()` | ja | reiner Ping-Call über `make_request()` |
| `get_artists()` | ja | ruft `make_request("getArtists")`, transformiert Rohantwort |
| `get_now_playing()` | ja | ruft `make_request("getNowPlaying")`, transformiert Rohantwort |
| `search()` | ja | ruft `make_request("search3")` |
| **`execute_scan()`** | **nein** | delegiert vollständig an `NavidromeScanTrigger.run_scan()` — **kein** Subsonic-/HTTP-Aufruf, sondern lokale Docker-/Subprocess-Steuerung (siehe ARCH-009 Phase 3/4). Bleibt auch nach Phase 5 (Telegram-Formatierung entfernt) strukturell fehl am Platz in einer „API“-Klasse — nicht wegen Telegram, sondern weil es inhaltlich keine Navidrome-API-Kommunikation ist. |

**Ergebnis: sechs von sieben Methoden sind reine API-Kommunikation.**
`execute_scan()` ist die einzige Ausnahme — eine bereits in Phase 3
dokumentierte, durch Phase 5 nicht behobene (und auch nicht zu
behebende) strukturelle Fehlplatzierung, da sie fachlich gar keine
API-Kommunikation ist, sondern nur noch als dünner Pass-Through zu
`NavidromeScanTrigger` in der Klasse verbleibt (Nutzerentscheidung aus
Phase 5: dünner Pass-Through statt Entfernung).

---

## 3. Welche Consumer greifen darauf zu?

Repo-weit per Grep verifiziert (`grep -rn "NavidromeAPI\." handlers/ services/`):

| Methode | Consumer | Call-Sites |
|---|---|---|
| `make_request()` | `handlers/navidrome_menu_handler.py` | 9 direkte Aufrufe (`getArtist`, `getAlbumList2`, `getGenres`, `getSongsByGenre`, `getPlaylists`, `getStarred2`, `getAlbumList`, `getIndexes` u. a.) |
| `get_artists()` | `handlers/navidrome_menu_handler.py:104` | 1 |
| `search()` | `handlers/navidrome_menu_handler.py:965` | 1 |
| `execute_scan()` | `handlers/menu/rich_menu_handler.py:740` | 1 |
| `get_now_playing()` | `services/statistik/play_history_poller.py:97` (über injiziertes `self.api`) | 1 |
| `check_connection()` | **keiner** | 0 — weiterhin unbenutzt, dokumentierter BUG-007-Beleg für bewusst zurückgestellte Nutzung (siehe ARCH-009 Phase 1) |
| `_build_url()` | nur intern von `make_request()` | — |

**Insgesamt 13 Produktions-Call-Sites** über vier Methoden, verteilt auf
drei Consumer-Dateien.

---

## 4. Welche Consumer liegen in `handlers/`, welche in `services/`?

```
handlers/navidrome_menu_handler.py     — 11 Call-Sites (make_request ×9, get_artists, search)
handlers/menu/rich_menu_handler.py     —  1 Call-Site  (execute_scan)
services/statistik/play_history_poller.py — 1 Call-Site (get_now_playing, über self.api)
services/statistik_service.py          — 0 direkte Methodenaufrufe, konstruiert aber
                                          `NavidromeAPI()` und injiziert die Instanz
                                          in PlayHistoryPoller (Zeile 56/61-62)
```

**Deutliches Übergewicht bei `handlers/`** (12 von 13 Call-Sites, 92 %) —
bestätigt exakt den bereits in ARCH-008 dokumentierten Befund. Der
einzige `services/`-Pfad ist funktional schmal (nur `get_now_playing()`),
aber strukturell bereits der am weitesten fortgeschrittene: er verwendet
bereits Konstruktor-Injection (`navidrome_api=None`-Parameter in
`StatistikService.__init__`, ARCH-003/P-8-Muster) und ruft die Methode
über eine **Instanz** auf (`self.api.get_now_playing()`), nicht über die
Klasse direkt.

---

## 5. Welche Abhängigkeiten müsste ein Umzug nach `services/clients/` erzeugen?

- **Import-Anpassung in 3 Dateien**: `handlers/navidrome_menu_handler.py`,
  `handlers/menu/rich_menu_handler.py`, `services/statistik_service.py`
  (jeweils `from api.navidrome_api import NavidromeAPI` →
  `from services.clients.navidrome_client import ...`).
- **`NavidromeScanTrigger`-Frage**: `api/navidrome_scan_trigger.py` liegt
  aktuell neben `navidrome_api.py` in `api/`. Zieht `NavidromeAPI` um,
  entstünde entweder ein Cross-Package-Import
  (`services/clients/navidrome_client.py` → `api.navidrome_scan_trigger`)
  oder `NavidromeScanTrigger` müsste mitziehen — beides unbefriedigend,
  da `NavidromeScanTrigger` selbst kein externer API-Client ist (lokale
  Subprocess-/Docker-Steuerung, siehe Abschnitt 2). Diese Frage ist nicht
  Teil dieser Phase, aber eine direkte Konsequenz einer künftigen
  Verschiebung von `NavidromeAPI` und sollte bei Phase 7 mitentschieden
  werden.
- **Modul-Import-Seiteneffekt**: `_auth_params` wird aktuell als
  Klassenattribut **beim Modul-Import** ausgewertet
  (`_get_navidrome_config()` läuft zur Klassendefinitionszeit,
  `api/navidrome_api.py:46-52`) — ungewöhnlich für `services/clients/`
  (die drei P-11-Clients laden Config lazy in `__init__`). Ein Umzug ohne
  gleichzeitige Strukturänderung würde diesen Seiteneffekt unverändert
  mitnehmen; ein Umzug mit DI-Umstellung (Abschnitt 6) würde ihn beheben.
- **Keine neuen externen Paketabhängigkeiten** — `requests`, `config`,
  `logger` sind bereits repoweit übliche Importe, keine Besonderheit.

---

## 6. Kann `NavidromeAPI` von der statischen Klassenstruktur auf Instanz + DI umgestellt werden?

**Technisch: ja, unkompliziert.** Die interne Umstellung selbst ist eine
kleine, mechanische Änderung — analog zu den drei P-11-Clients
(`GeniusClient`/`LastFMClient`/`MusicBrainzClient`, alle mit
`__init__(self, config=None, logger=None)`, lazy Config-Ladung,
Instanzmethoden statt `@classmethod`). Für `NavidromeAPI` beträfe das
sechs Methoden (alle außer `execute_scan()`, siehe Abschnitt 2).

**Der eigentliche Aufwand liegt nicht in der Klasse selbst, sondern in
den Consumern:**

- `handlers/navidrome_menu_handler.py::__init__(self, config, logger_factory=None)`
  besitzt **aktuell keinerlei DI-Slot** für eine Navidrome-Instanz — alle
  11 Call-Sites rufen `NavidromeAPI.xxx()` direkt auf der Klasse auf.
  Eine echte DI-Umstellung erfordert einen neuen Konstruktor-Parameter
  hier **und** eine Anpassung der Konstruktionsstelle
  (`handlers/menu/rich_menu_handler.py:220`,
  `NavidromeMenuHandler(...)`).
- `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()` ruft
  `NavidromeAPI.execute_scan()` ebenfalls klassenweise auf, ohne
  jegliche Instanzhaltung.
- `services/statistik_service.py`/`play_history_poller.py` sind bereits
  DI-bereit (Konstruktor-Injection, Instanz-Aufruf) — **hier wäre eine
  Umstellung praktisch aufwandsfrei**, da das Muster schon existiert.

**Fazit: DI ist technisch machbar, der Blast Radius liegt fast
vollständig in `handlers/navidrome_menu_handler.py` (11 von 13
Call-Sites) und `handlers/menu/rich_menu_handler.py` (1 Call-Site), nicht
in der Klasse selbst und nicht in `services/`.**

---

## 7. Welche bestehenden Tests hängen an der statischen API?

Repo-weit per Grep (`NavidromeAPI\.` in `tests/`): **~30 Fundstellen über
5 Testdateien**, mindestens 18 dedizierte Testfunktionen allein in den
drei Kern-Testdateien:

| Testdatei | `NavidromeAPI.`-Referenzen | Patch-Stil |
|---|---|---|
| `tests/test_navidrome_api_characterization.py` | 15 | `patch.object(NavidromeAPI, "make_request")` / direkte `asyncio.run(NavidromeAPI.xxx())`-Aufrufe |
| `tests/test_navidrome_api_timeout.py` | 4 | `patch.object(NavidromeAPI, "_build_url")`, direkte `NavidromeAPI.make_request("ping")`-Aufrufe |
| `tests/test_navidrome_api_logging.py` | 2 | `patch(...NavidromeAPI...)` |
| `tests/test_rich_menu_handler.py` | 8 | `patch("handlers.menu.rich_menu_handler.NavidromeAPI.execute_scan", new=AsyncMock(...))` |
| `tests/test_navidrome_menu_handler.py` | 1 | `patch("api.navidrome_api.NavidromeAPI.make_request")` |

Alle Patches sind **klassenweite** Patches (`patch.object(NavidromeAPI, ...)`
oder modulqualifizierte Klassenpfade) — keiner geht über eine injizierte
Instanz. Eine Umstellung auf Instanzmethoden würde **jeden dieser
Patch-Orte** berühren (Patch-Ziel ändert sich von der Klasse auf eine
konkrete Instanz bzw. erfordert Instanz-Fixtures). Das ist der mit
Abstand größte Testaufwand aller bisherigen ARCH-009-Schritte — deutlich
größer als der Testaufwand aus Phase 2 (4 Tests), Phase 4 (5 neue Tests)
oder Phase 5 (Umformulierung von 2 Testklassen).

---

## 8. Gibt es einen sinnvollen Übergang ohne Big-Bang-Umbau?

Ja — drei ergänzende, nicht exklusive Strategien:

1. **Kompatibilitäts-Bridge**: `NavidromeAPI` bekommt echte
   Instanzmethoden (`__init__(self, config=None, logger=None)`,
   lazy `_auth_params`), die bisherigen `@classmethod`s bleiben
   **vorübergehend** als dünne Wrapper bestehen, die intern eine
   modulweite Default-Instanz verwenden — bestehende statische Aufrufe
   (`NavidromeAPI.make_request(...)`) funktionieren unverändert weiter,
   während neuer/migrierter Code bereits injizierte Instanzen nutzen
   kann. Entspricht dem in der ursprünglichen ARCH-009-Migrationsplanung
   bereits benannten „Migration Bridge“-Konzept.
2. **Consumer einzeln migrieren**: `handlers/navidrome_menu_handler.py`
   und `handlers/menu/rich_menu_handler.py` sind zwei unabhängige
   Dateien — könnten in zwei getrennten, kleinen Schritten auf DI
   umgestellt werden, statt in einem gemeinsamen PR (passend zum in
   dieser Session durchgehend befolgten Prinzip kleinstmöglicher
   Schritte, CLAUDE.md Regel 18).
3. **`services/`-Pfad zuerst**: da `services/statistik_service.py`
   bereits DI-bereit ist, wäre die Umstellung dort praktisch aufwandsfrei
   und könnte als risikoärmster erster Schritt vorgezogen werden, um das
   Muster zu verifizieren, bevor die deutlich größeren `handlers/`-
   Call-Sites angegangen werden.

Eine Kombination aus (1) und (2) vermeidet einen Big-Bang vollständig.

---

## 9. Welche Teile gehören eventuell nicht in `services/clients/`?

- **`execute_scan()`** — siehe Abschnitt 2: keine echte API-Kommunikation,
  sondern ein Pass-Through zu lokaler Subprocess-/Docker-Steuerung. Auch
  nach vollständiger DI-Umstellung der übrigen sechs Methoden bliebe
  `execute_scan()` fachlich fehlplatziert in einem künftigen
  `NavidromeClient`. Zwei Optionen für einen späteren Schritt (nicht Teil
  dieser Analyse): (a) `execute_scan()` bleibt als Kompatibilitäts-Rest
  in `api/` zurück, während die übrigen sechs Methoden nach
  `services/clients/` wandern; (b) `execute_scan()` wird — wie bereits
  als „Option 1“ im Phase-5-Entscheidungsgate diskutiert, aber nicht
  gewählt — vollständig entfernt und der Handler ruft
  `NavidromeScanTrigger.run_scan()` direkt auf.
- **`NavidromeScanTrigger`** selbst (aktuell `api/navidrome_scan_trigger.py`)
  gehört ebenfalls nicht nach `services/clients/` — keine externe
  API-Kommunikation, sondern lokale Prozesssteuerung (siehe ARCH-009
  Phase 3, Empfehlung: eigener Ort, kein API-Client).
- **`check_connection()`** ist inhaltlich reine API-Kommunikation und
  gehört technisch in einen künftigen Client — bleibt aber weiterhin ohne
  Produktions-Consumer (BUG-007). Kein struktureller Ausschlussgrund,
  nur ein Nutzungs-Hinweis.

---

## 10. Vergleich mit der Konvention `services/clients/`

> `services/clients/` = reine externe Integrationsadapter, keine
> Telegram-Präsentation, keine fachliche Orchestrierung.

| Kriterium | Status nach Phase 5 |
|---|---|
| Keine Telegram-Präsentation | ✅ erfüllt (seit Phase 5 vollständig) |
| Reine externe Integrationsadapter (Struktur) | ⚠️ 6/7 Methoden ja, `execute_scan()` nein (Abschnitt 2/9) |
| Keine fachliche Orchestrierung | ✅ erfüllt — `NavidromeAPI` enthält keine Business-Logik; Orchestrierung (welche Endpunkte wann, Fehlerbehandlung pro Anwendungsfall) liegt bereits vollständig in `handlers/navidrome_menu_handler.py` bzw. `services/statistik/play_history_poller.py` |
| Instanz + DI statt statische Klasse | ❌ nicht erfüllt (Abschnitt 6) — einziges verbleibendes strukturelles Unterscheidungsmerkmal zu den P-11-Clients |

**Zwischenfazit**: `NavidromeAPI` erfüllt inzwischen zwei von vier
Konventionskriterien vollständig (keine Telegram-Präsentation, keine
Orchestrierung). Die verbleibenden zwei Lücken (`execute_scan()` als
Fremdkörper, statische statt Instanz-Struktur) sind nicht mit Phase 5
zusammenhängend, sondern eigenständige, bereits in ARCH-008/ARCH-009-
Migrationsplanung vorhergesagte Themen.

---

## 11. Varianten

### Variante A — Status quo

Keine Verschiebung, keine DI-Umstellung. `NavidromeAPI` bleibt eine
`@classmethod`/`@staticmethod`-Klasse in `api/`.

- **Risiko:** keins.
- **Aufwand:** keiner.
- **Konsequenz:** die P-11-Konvention bleibt für Navidrome dauerhaft
  unerfüllt; `execute_scan()` bleibt strukturell fehlplatziert.

### Variante B — DI in-place einführen, keine Verschiebung

`NavidromeAPI` bekommt eine echte Instanzstruktur
(`__init__(self, config=None, logger=None)`, lazy `_auth_params`,
Instanzmethoden statt `@classmethod` für die sechs reinen
API-Kommunikationsmethoden). Übergang über Kompatibilitäts-Bridge
(Abschnitt 8, Punkt 1), Consumer-Migration schrittweise je Datei
(Abschnitt 8, Punkt 2/3). `execute_scan()` bewusst außen vor (Abschnitt 9).
Bleibt in `api/`, keine Verschiebung nach `services/clients/`.

- **Risiko:** mittel — 12 Call-Sites in zwei Handlerdateien, ~30
  Testreferenzen in 5 Testdateien betroffen, aber isoliert auf einen
  einzigen strukturellen Aspekt (keine gleichzeitige Ortsänderung).
- **Aufwand:** mittel bis hoch, aber in kleine, unabhängige Schritte
  zerlegbar (z. B. `services/`-Pfad zuerst, dann je ein Handler).
- **Vorteil:** löst den einzigen noch offenen strukturellen
  Konventions-Unterschied zu den P-11-Clients, unabhängig von einer
  Ortsentscheidung.

### Variante C — DI-Umstellung und Verschiebung nach `services/clients/` kombiniert

Wie B, zusätzlich gleichzeitige Verschiebung nach
`services/clients/navidrome_client.py`.

- **Risiko:** hoch — bündelt zwei unabhängige, je für sich bereits
  risikobehaftete Änderungen (Strukturumstellung **und** Ortswechsel,
  inkl. der in Abschnitt 5 beschriebenen `NavidromeScanTrigger`-Frage)
  in einem Schritt.
- **Aufwand:** hoch — identischer Testaufwand wie B, zusätzlich
  Importpfad-Anpassung in 3 Consumer-Dateien, gleichzeitig statt
  nacheinander verifizierbar.
- **Widerspruch zu CLAUDE.md Regel 18** („kein großer Refactor als erste
  Reaktion“) und zum in dieser Session durchgehend befolgten Prinzip
  kleinstmöglicher, einzeln verifizierbarer Schritte.

---

## 12. Empfehlung

**Variante B**, danach — als eigener, separater, kleinerer Folgeschritt
— die Verschiebung nach `services/clients/` (entspricht inhaltlich
Variante C, aber zeitlich entkoppelt statt kombiniert). Begründung:
Ist die Klasse bereits eine saubere Instanzstruktur mit DI, ist der reine
Ortswechsel danach ein sehr kleiner, risikoarmer Schritt — analog zu den
drei P-11-Clients, die bereits vor ihrer Einordnung in `services/clients/`
eine Instanzstruktur besaßen (keiner von ihnen wurde als statische Klasse
verschoben und erst danach umgebaut).

**Offener Punkt für das Entscheidungsgate:** Das kehrt die aktuelle
Reihenfolge in `docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
um (dort steht Phase 7 „Zielstruktur entscheiden“ vor Phase 8 „DI
umsetzen“). Diese Analyse empfiehlt technisch die umgekehrte Reihenfolge
(DI vor Ortswechsel), entscheidet das aber nicht selbst — das bleibt Teil
des folgenden Entscheidungsgates.

`execute_scan()` sollte unabhängig von A/B/C **in keinem Fall** in einen
künftigen `services/clients/`-Client wandern (Abschnitt 9) — diese Frage
ist von der A/B/C-Entscheidung entkoppelt und kann separat entschieden
werden.

---

## 13. Entscheidungsgate

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde vorgenommen.**

Offene Entscheidungen:

1. Variante A (Status quo), B (DI in-place) oder C (DI + Verschiebung
   kombiniert)?
2. Falls B: DI zuerst in `services/statistik_service.py` (aufwandsfrei,
   bereits DI-bereit) oder zuerst in einem der beiden `handlers/`-Consumer?
3. Soll die Reihenfolge in der Roadmap (aktuell Phase 7 vor Phase 8)
   angepasst werden, oder bleibt die bestehende Nummerierung trotz der
   hier empfohlenen umgekehrten technischen Reihenfolge bestehen?
4. Was geschieht mit `execute_scan()` bei einer künftigen Verschiebung —
   Kompatibilitäts-Rest in `api/` oder vollständige Entfernung zugunsten
   eines direkten `NavidromeScanTrigger`-Aufrufs im Handler (Abschnitt 9)?
5. Was geschieht mit `NavidromeScanTrigger` — bleibt es dauerhaft in
   `api/`, oder bekommt lokale Infrastruktur-/Subprocess-Steuerung einen
   eigenen, von `services/clients/` getrennten Ort?

**Es wird nicht selbstständig mit einer Umsetzung begonnen.** Nächster
Schritt erst nach expliziter Nutzerentscheidung, in einem eigenen Branch,
mit eigenem PR/Review/Merge-Zyklus wie in allen vorherigen
ARCH-009-Schritten.
