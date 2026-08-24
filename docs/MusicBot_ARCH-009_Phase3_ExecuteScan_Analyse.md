# ARCH-009 Phase 3 — `execute_scan()` / Subprocess-Verantwortung: Analyse

Reine Analysephase gemäß `docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
Phase 3. Keine Codeänderung, keine Verschiebung, keine DI-Umstellung,
keine Änderung an `check_connection()` oder `execute_scan()` selbst.
Aufbauend auf ARCH-008, ARCH-009 (Migrationsplanung) und ARCH-009 Phase 1/2
(abgeschlossen, siehe `docs/MusicBot_ARCH-009_Phase1_Bestandsaufnahme.md`).

---

## 1. Ist-Zustand

`execute_scan()` (`api/navidrome_api.py:135-221`, `@classmethod async def`)
führt sechs fachlich unterschiedliche Schritte nacheinander in einem
einzigen `try`-Block aus:

1. **Konfigurationsvalidierung**: prüft, ob `Config.NAVIDROME_SCAN_COMMAND`
   existiert und nicht leer ist; wirft sonst `AttributeError` mit
   selbstgebauter Fehlermeldung.
2. **Kommando-Normalisierung**: falls `NAVIDROME_SCAN_COMMAND` eine Liste
   ist, wird sie mit `" ".join(...)` in einen String umgewandelt
   (aktuell in `config.py:397` ohnehin bereits ein String — dieser Zweig
   ist damit produktiv unbenutzt, aber vorhanden).
3. **Typvalidierung**: wirft `TypeError`, falls nach Schritt 2 kein String
   vorliegt.
4. **Subprocess-Ausführung**: `asyncio.create_subprocess_shell(command_to_execute, stdout=PIPE, stderr=PIPE)`
   — startet einen Shell-Prozess auf dem Host, der
   `docker exec navidrome /app/navidrome scan --full` ausführt (echter
   Docker-Container-Zugriff, keine Navidrome-HTTP/Subsonic-Kommunikation).
5. **Timeout-Steuerung**: `asyncio.wait_for(process.communicate(), timeout=timeout)`,
   `timeout = getattr(Config, "NAVIDROME_SCAN_TIMEOUT", 300)`. Der
   `300`-Default in `getattr` ist praktisch irrelevant, da
   `Config.NAVIDROME_SCAN_TIMEOUT = 45` (`config.py:396`) immer gesetzt
   ist — der tatsächlich wirksame Timeout ist **45 Sekunden**. Das ist für
   einen vollständigen Library-Rescan (`--full`) potenziell knapp; ob das
   in der Praxis reicht, wurde hier nicht geprüft (außerhalb des
   Analyseauftrags — reine Beobachtung, kein Fix).
6. **Telegram-MarkdownV2-Nachrichtenbau**: sowohl der Erfolgs- als auch
   **alle drei** Fehlerpfade (`returncode != 0`, `asyncio.TimeoutError`,
   genereller `except Exception`) bauen direkt die fertige, an Telegram
   sendbare Nachricht — inklusive `EMOJI[...]`-Zugriff, MarkdownV2-Code-
   Block-Syntax (```` ``` ````) und `escape_md_v2()`-Escaping.

Rückgabewert ist durchgängig `tuple[bool, str]` — `bool` = Erfolg,
`str` = bereits fertig formatierte MarkdownV2-Telegram-Nachricht (kein
strukturiertes Datenobjekt, kein Roh-`stdout`/`stderr`).

### Logging

Jeder Schritt loggt über `log_handler_info`/`log_handler_debug`/
`log_handler_error` mit `context="NavidromeAPI"` — konsistent mit dem
Rest der Klasse. Keine Secrets im Log-Pfad von `execute_scan()` selbst
(anders als `make_request()`, das explizit `Config.mask_sensitive()` für
Credentials nutzt — hier gibt es keine Credentials im Scan-Pfad, da der
Docker-Befehl statisch ist).

### Fehlerbehandlung

Drei getrennte Fehlerpfade mit je eigener Nutzer-Nachricht:
- `returncode != 0` → `False`, Fehler-Nachricht mit `stderr`.
- `asyncio.TimeoutError` → `False`, Timeout-Hinweistext (referenziert die
  ansonsten nicht mehr sichtbare `timeout`-Variable — funktioniert nur,
  weil `timeout` bereits vor dem inneren `try` zugewiesen wurde und Python
  keinen Block-Scope kennt).
- Alle sonstigen `Exception` (inkl. der beiden selbst geworfenen
  `AttributeError`/`TypeError` aus Schritt 1/3) → `False`, generische
  Fehlermeldung mit `str(e)`.

Kein Pfad lässt eine Exception nach außen durch — `execute_scan()` gibt
**immer** `tuple[bool, str]` zurück, nie eine Exception. Das unterscheidet
es von `get_artists()`/`search()`/`get_now_playing()`, die Exceptions
propagieren lassen (dokumentierte Inkonsistenz, siehe Docstring von
`tests/test_navidrome_api_characterization.py`).

---

## 2. Consumer-/Dependency-Graph

```
handlers/menu/rich_menu_handler.py
  └── _handle_navidrome_scan()  (Zeile 717-731, Callback-Handler)
        │  admin-only (self._is_admin(user_id) davor geprüft)
        │  eigener try/except um den Aufruf
        ▼
      NavidromeAPI.execute_scan()   ← EINZIGER Produktions-Consumer
        │
        ├─▶ Config.NAVIDROME_SCAN_COMMAND / NAVIDROME_SCAN_TIMEOUT
        ├─▶ asyncio.create_subprocess_shell (stdlib)
        ├─▶ EMOJI[...]  (emoji.py)
        └─▶ escape_md_v2()  (helfer/markdown_helfer.py)
```

- **Genau ein Produktions-Call-Site**: `handlers/menu/rich_menu_handler.py:727`,
  innerhalb `_handle_navidrome_scan()`. Repo-weiter Grep bestätigt keine
  weiteren Aufrufer.
- Der Handler ruft `_success, message = await NavidromeAPI.execute_scan()`
  auf, verwendet **nur** `message` (per `query.edit_message_text(message, parse_mode="MarkdownV2")`),
  der `_success`-Boolean wird komplett verworfen (Unterstrich-Präfix,
  bewusst ignoriert) — der Handler verlässt sich vollständig auf die
  bereits fertig formatierte Nachricht aus `execute_scan()`, trifft selbst
  keine Erfolg/Fehler-Unterscheidung.
- Der Handler hat zusätzlich sein **eigenes** `except Exception`, das
  praktisch nie greifen kann, da `execute_scan()` keine Exception nach
  außen lässt (siehe oben) — totes Sicherheitsnetz, aber harmlos.
- **Historischer Fund** (aus dem Docstring von
  `tests/test_rich_menu_handler.py::TestHandleNavidromeScan`, Zeilen
  373-378): früher rief dieselbe Handler-Methode
  `self.navidrome_adapter.trigger_scan()` auf — `navidrome_adapter` wurde
  aber nirgends im Repo instanziiert und war daher immer `None`, jeder
  Klick zeigte nur „Navidrome-Adapter nicht verfügbar“. Der bereits
  vorhandene Fix ruft seitdem `NavidromeAPI.execute_scan()` direkt auf.
  `navidrome_adapter`/`NavidromeAdapter` existiert **nicht mehr** im
  aktuellen Code (verifiziert per Grep, nur noch als Testkommentar
  sichtbar) — es gibt also aktuell **keine** verwaiste Adapter-Abstraktion
  zu berücksichtigen, aber der Fund zeigt: eine frühere Adapter-Idee für
  genau diesen Anwendungsfall existierte bereits einmal und wurde nicht
  zu Ende geführt.
- **Tests**: 4 Charakterisierungstests direkt für `execute_scan()`
  (`tests/test_navidrome_api_characterization.py::TestExecuteScan`,
  Zeilen 159-217: Erfolg, `returncode != 0`, Timeout, fehlendes
  `NAVIDROME_SCAN_COMMAND`) + 4 Tests für den Handler-Call-Site
  (`tests/test_rich_menu_handler.py::TestHandleNavidromeScan`, Zeilen
  371-439: Erfolg, Fehler-Nachricht durchgereicht, Admin-Check, Exception-
  Pfad). **Mock-/Patch-Ziele**: `api.navidrome_api.asyncio.create_subprocess_shell`
  (Klassentests) bzw. `handlers.menu.rich_menu_handler.NavidromeAPI.execute_scan`
  (Handlertests, Modul-Import-Alias) — beide Ebenen sind bereits sauber
  gemockt, keine echten Docker-/Subprocess-Aufrufe in Unit-Tests.
- **Fehlende Charakterisierungstests**: keiner der 4 `execute_scan()`-Tests
  prüft die Kommando-Listen-Normalisierung (Schritt 2) oder die
  Typvalidierung (Schritt 3) — beide Zweige sind produktiv unbenutzt
  (`NAVIDROME_SCAN_COMMAND` ist immer ein String), daher aktuell ohne
  Testlücken-Risiko, aber bei einer Extraktion in eine eigene Klasse wäre
  das eine sinnvolle Ergänzung.

---

## 3. Verantwortlichkeitsanalyse

**Nein, `execute_scan()` besitzt keine einzige Verantwortlichkeit** —
es vermischt mindestens drei fachlich unterschiedliche Aufgaben:

| Verantwortlichkeit | Zeilen (ca.) | Fachliche Kategorie |
|---|---|---|
| Konfigurationsvalidierung/-normalisierung | 140-166 | Infrastruktur-Konfiguration |
| Subprocess-/Docker-Steuerung + Timeout | 168-189, 205-213 | lokale Prozessausführung |
| Telegram-MarkdownV2-Präsentation (Erfolg + 3 Fehlerpfade) | 192, 199, 210-213, 218-221 | Handler-/Präsentationslogik |

Das ist eine **stärkere** Vermischung als ursprünglich in ARCH-008/
ARCH-009 (Migrationsplanung) angenommen: dort wurde `execute_scan()`
primär als „Subprocess-Steuerung, gehört nicht in einen API-Client“
eingeordnet. Die heutige Detailanalyse zeigt zusätzlich, dass
**die Telegram-Präsentationslogik nicht nur in den drei separaten
`format_*`-Methoden steckte (die in Phase 2 bereits entfernt wurden),
sondern zusätzlich direkt in `execute_scan()` selbst** — und zwar in
allen vier Ausgängen (Erfolg, Return-Code-Fehler, Timeout, generische
Exception). Das ist relevant, weil Phase 2 den Eindruck erwecken konnte,
alle Telegram-Formatierung sei mit den sechs entfernten Methoden bereits
verschwunden — das stimmt nicht: `execute_scan()` ist die einzige
verbleibende Methode in `NavidromeAPI` mit eingebauter
Telegram-Formatierung.

Im Vergleich: `get_artists()`, `search()`, `get_now_playing()` geben
ausschließlich Rohdaten (`dict`/`list`) zurück — reine API-Kommunikation
ohne Präsentationsanteil. `execute_scan()` fällt aus diesem Muster heraus
und ist damit die einzige „gemischte“ Methode im heutigen (nach Phase 2
bereinigten) Rest der Klasse.

Der einzige Consumer (`_handle_navidrome_scan()`) verlässt sich vollständig
darauf, dass `execute_scan()` bereits eine sendefertige Nachricht liefert
— das entspricht nicht der in der Roadmap (Abschnitt „Übergeordnete
Zielarchitektur“) festgelegten Schichtung
(`Integrationsadapter → strukturierte Daten → Anwendungslogik/Handler → Telegram-Präsentation`).

---

## 4. Risiken

1. **Shell-Injection-Muster** (dokumentiert, kein akuter Fund): `asyncio.create_subprocess_shell`
   statt `create_subprocess_exec` mit Argumentliste. Aktuell unkritisch,
   da `NAVIDROME_SCAN_COMMAND` ein statischer Config-Fixwert ohne
   Nutzereingabe ist. Risiko steigt nur, falls der Befehl jemals
   konfigurierbar/dynamisch würde — außerhalb des heutigen Scopes, aber
   bei einer Extraktion in eine eigene Klasse leichter isoliert und
   auditierbar zu machen.
2. **45-Sekunden-Timeout bei `--full`-Scan**: `Config.NAVIDROME_SCAN_TIMEOUT = 45`
   ist der einzige wirksame Wert (der `getattr(..., 300)`-Fallback in
   `execute_scan()` selbst greift nie). Ob 45s für einen vollständigen
   Rescan realistisch ausreichend sind, wurde hier nicht verifiziert
   (reine Beobachtung, keine Reproduktion/kein Fix — außerhalb des
   Analyseauftrags).
3. **Vermischte Telegram-Formatierung überlebt in `execute_scan()`**: eine
   spätere Migration, die nur Phase-2-artig „tote Methoden entfernen“
   fortsetzt, ohne diesen Befund zu berücksichtigen, würde die
   Präsentationslogik erneut übersehen (Phase 2 hat sie nur in den sechs
   bereits entfernten `format_*`/Diagnose-Methoden behoben, nicht hier).
4. **Toter `except`-Pfad im Handler**: `_handle_navidrome_scan()`s eigener
   `except Exception` kann praktisch nie erreicht werden, weil
   `execute_scan()` keine Exception propagiert. Kein aktives Risiko
   (harmloser Totcode), aber bei einer künftigen Schnittstellenänderung
   (z. B. strukturierte Rückgabe statt fertiger Nachricht) müsste dieser
   Handler-Pfad ohnehin überarbeitet werden — guter natürlicher Kopplungspunkt
   für Phase 4.
5. **Ungetestete Normalisierungs-/Typzweige** (Schritt 2/3, siehe
   Abschnitt 2): produktiv unbenutzt, aber bei einer Extraktion sollte
   geprüft werden, ob sie überhaupt noch gebraucht werden oder totes
   Gewicht innerhalb der Methode selbst sind (analog zum in dieser Session
   etablierten Muster „erst prüfen, dann entscheiden“ — hier nicht
   entschieden, nur benannt).
6. **Testaufwand bei Extraktion**: 4 Klassentests +4 Handlertests müssten
   bei einer Verschiebung angepasst werden (neue Patch-Pfade). Beide
   Testgruppen sind bereits sauber isoliert (kein echter Subprocess-/
   Docker-Aufruf), daher überschaubarer, aber nicht trivialer Aufwand.

---

## 5. Zielarchitektur-Optionen

### A — `execute_scan()` bleibt beim Navidrome-Integrationskontext

Keine strukturelle Änderung. `execute_scan()` bleibt Teil von
`NavidromeAPI` (bzw. dessen Nachfolger), so wie heute.

### B — Subprocess-/Scan-Steuerung wird von der API-Kommunikation getrennt

Neue, kleine Klasse (z. B. `NavidromeScanTrigger`) ausschließlich für
Konfigurationsvalidierung + Subprocess + Timeout (Schritte 1-5 aus
Abschnitt 1). Verbleibt räumlich nah bei `api/navidrome_api.py`
(z. B. `api/navidrome_scan_trigger.py`), aber als eigene Klasse getrennt
von der reinen HTTP/Subsonic-Kommunikation.

### C — Subprocess-/Scan-Steuerung wird als eigener Service/Infrastruktur-Komponente modelliert

Wie B, aber als `services/`-Baustein (z. B.
`services/infrastructure/navidrome_scan_service.py` o. ä.) statt im
`api/`-Verzeichnis — mit dem Gedanken, dass lokale Docker-/Shell-Steuerung
konzeptionell näher an „Infrastruktur-Orchestrierung“ liegt als an einem
API-Integrationsadapter (passend zur Roadmap-Aussage: „Lokale
Infrastruktur-, Shell- oder Subprocess-Verantwortlichkeiten werden separat
nach ihrer tatsächlichen Aufgabe bewertet und nicht automatisch einem
API-Client zugeordnet“).

### D — B/C plus Trennung der Telegram-Präsentationslogik

Wie B oder C, zusätzlich: die neue Scan-Klasse gibt ein **strukturiertes
Ergebnis** zurück (z. B. `success: bool`, `stdout: str`, `stderr: str`,
`timed_out: bool`, `error: str | None`) statt einer fertigen
MarkdownV2-Nachricht. Die Telegram-Formatierung (EMOJI, `escape_md_v2`,
Code-Block-Syntax) wandert in `_handle_navidrome_scan()` selbst
(`handlers/menu/rich_menu_handler.py`) — passend zur in Abschnitt 3
dokumentierten Vermischung und zur in der Roadmap für Phase 5 ohnehin
vorgesehenen Zielschichtung. Diese Variante zieht einen Teil von
Phase 5 („Verbleibende Präsentations-/Telegram-Verantwortlichkeiten
prüfen“) faktisch in den Umfang von Phase 4 vor, weil der Befund
(Abschnitt 3) zeigt, dass die Vermischung konkret in `execute_scan()`
sitzt und nicht erst nachträglich in einem separaten Schritt entdeckt
werden müsste.

---

## 6. Variantenvergleich

| | A: Unverändert | B: Eigene Klasse (api/) | C: Eigener Service (services/) | D: B/C + Telegram-Trennung |
|---|---|---|---|---|
| **Vorteile** | kein Risiko, kein Aufwand | klare Trennung API-Kommunikation vs. Prozesssteuerung, kleiner Schritt | passt zur Roadmap-Aussage „Infrastruktur ≠ API-Client“, klarer Ort für künftige ähnliche Aufgaben (falls es mehr Docker-/Infra-Steuerung geben sollte) | löst zusätzlich die in Abschnitt 3 gefundene Präsentations-Vermischung, entspricht der Zielschichtung vollständig |
| **Nachteile** | Vermischung bleibt bestehen, widerspricht Roadmap-Zielbild | „api/“ bleibt konzeptionell unscharf (weder reiner Client noch Service) | ein neues `services/`-Unterverzeichnis für aktuell genau einen Anwendungsfall — evtl. übertrieben für eine einzelne Methode | größter Änderungsumfang der vier Varianten, berührt auch den Handler |
| **Abhängigkeiten** | keine neuen | `Config`, `asyncio`, EMOJI/escape_md_v2 bleiben in der neuen Klasse | wie B, zusätzlich Namenskonvention/Ort für `services/`-Infrastruktur-Code muss erst etabliert werden (gibt es noch nicht) | wie B/C, zusätzlich Handler übernimmt EMOJI/escape_md_v2-Import |
| **Änderungsumfang** | keiner | 1 neue Datei/Klasse, 1 Importzeile in `rich_menu_handler.py`, 4 Klassentests migrieren | wie B, plus Entscheidung über neuen `services/`-Pfad | wie B/C, plus Anpassung der 4 Klassentests (neue Rückgabestruktur) **und** der 4 Handlertests (Nachricht wird jetzt im Handler gebaut) |
| **Risiko** | keins (aber Vermischung bleibt „falsch“ dokumentiert) | gering (reine Verschiebung, Verhalten 1:1 erhalten) | gering-mittel (neuer Architektur-Präzedenzfall für `services/`-Infrastruktur) | mittel (Verhaltensänderung der Rückgabe-Struktur, mehr Testanpassung, Handler-Logik wächst) |
| **Testaufwand** | keiner | 4 Tests umziehen (Patch-Pfad ändert sich) | wie B | 4+4 Tests anpassen, ggf. neue Tests für Handler-seitige Formatierung |
| **Auswirkung Zielarchitektur** | keine Annäherung an Roadmap-Zielbild | Teilschritt Richtung Zielbild (API-Kommunikation sauberer) | stärkerer Teilschritt, etabliert erstmals einen Infrastruktur-Ort in `services/` | vollständige Annäherung an die in der Roadmap für den Endzustand beschriebene Schichtung |

---

## 7. Konkrete Empfehlung

**Variante D, umgesetzt in zwei getrennten, nacheinander freigebbaren
Teilschritten**, statt als ein großer Schritt:

1. Zuerst **B** (Subprocess-/Konfigurationslogik in eine eigene Klasse
   auslagern, Rückgabe bleibt vorerst `tuple[bool, str]` wie heute) — das
   ist der risikoärmste, reine Verschiebungsschritt mit 1:1 erhaltenem
   Verhalten, konsistent mit der in dieser Session etablierten
   Vorgehensweise (kleinste sinnvolle Änderung zuerst, CLAUDE.md Regel 18).
2. **Erst danach**, als eigener, separat freizugebender Schritt, die
   Telegram-Formatierung in den Handler verschieben (der „D“-Anteil) —
   das ist die einzige Teiländerung mit echtem Verhaltensrisiko
   (Rückgabestruktur ändert sich, beide Testgruppen müssen angepasst
   werden) und sollte nicht mit der risikoarmen reinen Verschiebung
   vermischt werden.

Zwischen **B (api/)** und **C (services/)** als Zielort: tendenziell **B**
(`api/`), weil es aktuell genau einen einzelnen Anwendungsfall gibt und
kein zweiter Kandidat für „lokale Infrastruktursteuerung“ im Repo
erkennbar ist — ein neues `services/infrastructure/`-artiges Verzeichnis
für einen einzigen Consumer wäre eine Vorratsstruktur ohne aktuellen
zweiten Nutzen. Sollte künftig weitere Docker-/Host-Steuerung hinzukommen,
wäre eine Verschiebung von `api/` nach `services/` zu diesem späteren
Zeitpunkt ein kleiner, klar begründbarer Schritt — keine Entscheidung, die
heute vorweggenommen werden muss.

Diese Empfehlung ist **keine Entscheidung** — sie ist ein Vorschlag für
das Entscheidungsgate in Abschnitt 9.

---

## 8. Offene Architekturentscheidungen

1. Soll Variante D in einem oder in zwei getrennten Schritten (B dann
   Telegram-Trennung) umgesetzt werden — wie in Abschnitt 7 empfohlen,
   oder in einem Rutsch?
2. Zielort der neuen Scan-Klasse: `api/` (näher am Bestehenden) oder
   `services/` (näher an der Roadmap-Formulierung „Infrastruktur-
   Komponente“)?
3. Soll der `_success`-Rückgabewert, den der Handler heute bereits
   ignoriert, in einer neuen Struktur überhaupt noch als einfacher
   `bool` bestehen bleiben, oder direkt in ein kleines strukturiertes
   Ergebnisobjekt überführt werden (z. B. `NamedTuple`/`dataclass` statt
   `tuple[bool, str]`)? Nicht zwingend nötig für Variante B, aber
   naheliegend, falls ohnehin Variante D folgt.
4. Sollen die produktiv unbenutzten Normalisierungs-/Typvalidierungs-
   Zweige (Abschnitt 1, Schritt 2/3) bei der Extraktion unverändert
   mitgenommen oder als eigener kleiner Bereinigungspunkt separat
   angefragt werden?
5. Soll der praktisch tote `except Exception`-Pfad in
   `_handle_navidrome_scan()` (Abschnitt 4, Punkt 4) im Rahmen dieser
   Migration mit angepasst werden, oder unverändert bleiben, bis eine
   eigene Entscheidung dazu vorliegt?
6. Der 45-Sekunden-Timeout (Abschnitt 4, Punkt 2) ist eine reine
   Beobachtung ohne Reproduktion — soll das als eigener, getrennter
   Untersuchungspunkt aufgenommen werden (außerhalb ARCH-009), oder
   bewusst ignoriert werden, da kein konkretes Fehlverhalten vorliegt?

---

## 9. Entscheidungsgate

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde vorgenommen.**

Bevor mit Phase 4 (Umsetzung) begonnen wird, wird um eine Entscheidung zu
den in Abschnitt 8 aufgeführten Punkten gebeten — insbesondere:

- Welche Variante (A/B/C/D) bzw. welche Reihenfolge (B dann D, oder
  direkt D) soll umgesetzt werden?
- Zielort `api/` oder `services/`?

**Es wird nicht selbstständig mit Phase 4 begonnen.** Umsetzung erfolgt
erst nach expliziter Nutzerentscheidung, in einem eigenen Branch, mit
eigenem PR/Review/Merge-Zyklus wie in allen vorherigen ARCH-009-Schritten.
