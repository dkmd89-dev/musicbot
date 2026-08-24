# ARCH-009 Phase 8 — Zielverschiebung `NavidromeAPI` nach `services/clients/`: Analyse

Reine Analysephase. Keine Codeänderung, keine DI-Änderung, keine
Verschiebung von `NavidromeScanTrigger`, `execute_scan()` wird nicht
eigenständig entfernt. Bewertet die noch nicht umgesetzte Verschiebung von
`api/navidrome_api.py` nach `services/clients/navidrome_api.py`
gegenüber der etablierten Regel:

> `services/clients/` = ausschließlich externe Integrationsadapter, keine
> Telegram-Präsentation, keine fachliche Orchestrierung.

Aufbauend auf ARCH-009 Phase 6 (Zielposition/DI-Analyse) und Phase 7
(DI-Umsetzung, abgeschlossen und gemerged).

---

## 1. Welche Teile von `NavidromeAPI` gehören tatsächlich in `services/clients/`?

Nach Phase 7 besitzt `NavidromeAPI` sieben Methoden. Sechs davon sind
reine, instanzbasierte API-Kommunikation und erfüllen die Adapter-Regel
strukturell bereits vollständig:

`__init__`, `_build_url`, `make_request`, `check_connection`,
`get_artists`, `get_now_playing`, `search`.

**`execute_scan()` gehört nicht dazu** — unverändert seit ARCH-009 Phase 3:
delegiert vollständig an `NavidromeScanTrigger.run_scan()` (lokale
Docker-/Subprocess-Steuerung), keine Subsonic-/HTTP-Kommunikation. Bleibt
bewusst ein `@classmethod` (Phase 7), benötigt keinerlei injizierte
Config/Instanz.

**Zusatzfund (bislang nicht gesondert für diese Phase erhoben):**
`api/navidrome_api.py` enthält weiterhin den toten Import
`from telegram.constants import ParseMode` (0 Verwendungen, siehe ARCH-009
Phase 5 Abschnitt 3, dort als „Option 3“ bewusst nicht entfernt). Eine
1:1-Verschiebung der Datei würde diesen `telegram.*`-Import unverändert
mit nach `services/clients/` nehmen — ein sichtbarer, wenn auch
funktional wirkungsloser Verstoß gegen die Regel „keine
Telegram-Präsentation“ direkt auf Import-Ebene. Relevanter Fund für diese
Phase, siehe Abschnitt 9.

---

## 2. Ist `execute_scan()` weiterhin Bestandteil des Adapters, oder muss es vor der Verschiebung vollständig außerhalb bleiben?

Fachlich: **außerhalb**. `execute_scan()` erfüllt keines der Kriterien für
„externer Integrationsadapter“ (keine HTTP-/Subsonic-Kommunikation,
sondern lokale Prozesssteuerung) — das ist seit ARCH-009 Phase 3
mehrfach dokumentiert und durch Phase 5/7 nicht verändert worden.

Technisch: `execute_scan()` **könnte** trotzdem unverändert mitverschoben
werden, da es als zustandsloser `@classmethod` keine Abhängigkeit zu
`self`/`self.config` hat und daher auf jeder Klasse funktionieren würde,
unabhängig vom Speicherort. Die Frage ist rein architektonisch, nicht
technisch erzwungen — siehe Abschnitt 3 für die beiden entstehenden
Optionen.

---

## 3. Umgang mit der bestehenden `execute_scan()`-Bridge

Zwei technisch gleichwertig funktionierende Optionen:

### Option A — `execute_scan()` verschiebt sich unverändert mit

`services/clients/navidrome_api.py` enthält alle sieben Methoden
unverändert, inkl. `execute_scan()`. Einfachster Schritt: eine Datei, eine
Klasse, ein Import pro Consumer.

- **Nachteil:** `services/clients/navidrome_api.py` wäre dann *kein*
  reiner Integrationsadapter mehr (verletzt die Regel strukturell, auch
  wenn `execute_scan()` selbst telegramfrei ist) — genau die Vermischung,
  die die gesamte ARCH-009-Reihe seit Phase 3 auflösen sollte, würde an
  neuer Stelle fortbestehen.

### Option B — `execute_scan()` bleibt als eigenständiger Rest in `api/` zurück (empfohlen, siehe Abschnitt 12)

`api/navidrome_api.py` wird zu einer schlanken Restdatei, die
ausschließlich `execute_scan()` enthält (als eigenständige kleine Klasse
oder Funktion — konkrete Form ist Teil der eigentlichen Umsetzung, nicht
dieser Analyse). Die sechs übrigen Methoden ziehen vollständig nach
`services/clients/navidrome_api.py` um.

- **Vorteil:** `services/clients/navidrome_api.py` wird ein tatsächlich
  reiner Integrationsadapter, ohne Ausnahme.
- **Zusätzlicher Vorteil, konkret verifiziert:** `handlers/menu/rich_menu_handler.py`
  ist der **einzige** Consumer von `execute_scan()` — und verwendet
  **keine** der sechs übrigen Methoden (verifiziert per Grep, siehe
  ARCH-009 Phase 6 Abschnitt 3/4). Bleibt `execute_scan()` in `api/`
  zurück, **muss `handlers/menu/rich_menu_handler.py`s Import überhaupt
  nicht geändert werden** — im Gegensatz zu Option A, wo dieser Consumer
  trotz Nichtnutzung der eigentlichen Adapter-Methoden auf den neuen
  Importpfad umgestellt werden müsste.
- **Nachteil:** zwei Dateien/Konzepte unter dem ehemals einheitlichen
  Namen „NavidromeAPI“ — erfordert klare Dokumentation, welcher Teil wo
  liegt.

**Ausdrücklich nicht Teil dieser Analyse/Option**: die in ARCH-009 Phase 5
bereits diskutierte, aber nicht gewählte Alternative, `execute_scan()`
ersatzlos zu entfernen und `rich_menu_handler.py` direkt
`NavidromeScanTrigger.run_scan()` aufrufen zu lassen — das wäre
„Entfernen“ im Sinne des expliziten Auftragsverbots dieser Phase, nicht
„Verschieben“, und bleibt daher außerhalb des Betrachtungsraums.

---

## 4. Import-Änderungen: `api.navidrome_api` → `services.clients.navidrome_api`

| Datei | Art der Änderung |
|---|---|
| `handlers/navidrome_menu_handler.py` | `from api.navidrome_api import NavidromeAPI` → `from services.clients.navidrome_api import NavidromeAPI` |
| `services/statistik_service.py` | dieselbe Änderung |
| `handlers/menu/rich_menu_handler.py` | **nur falls Option A** (Abschnitt 3) — bei Option B keine Änderung nötig, da einziger Nutzer von `execute_scan()`, welches in `api/` verbleibt |
| `services/clients/__init__.py` | müsste `NavidromeAPI` (bzw. einen ggf. abweichenden Klassennamen, siehe Abschnitt 12 Punkt 4) analog zu `GeniusClient`/`LastFMClient`/`MusicBrainzClient` re-exportieren |
| `tests/test_navidrome_api_characterization.py` | Import-Zeile; bei Option B zusätzlich Aufspaltung nötig (Abschnitt 6) |
| `tests/test_navidrome_api_timeout.py` | Import-Zeile + 3 String-Patch-Ziele (Abschnitt 6) |
| `tests/test_navidrome_api_logging.py` | Import-Zeile + 1 String-Patch-Ziel (Abschnitt 6) |

**Kein Cross-Import von `services/clients/` zurück nach `api/` nötig bei
Option B** — `services/clients/navidrome_api.py` bräuchte in diesem Fall
gar keine Abhängigkeit zu `api/navidrome_scan_trigger.py`, da
`execute_scan()` (der einzige Nutzer von `NavidromeScanTrigger`) nicht
mitzieht. Bei Option A wäre ein Import
`from api.navidrome_scan_trigger import NavidromeScanTrigger, ScanRunResult`
innerhalb von `services/clients/navidrome_api.py` nötig — technisch
unproblematisch (siehe Abschnitt 8), aber eine bislang in `services/clients/`
unübliche Abhängigkeitsrichtung (kein bestehender P-11-Client importiert
aus `api/`).

**Dokumentations-Referenzen** (nicht funktional, aber bei einer echten
Verschiebung veraltend): mindestens 14 bestehende Markdown-Dokumente
referenzieren `api.navidrome_api`/`api/navidrome_api.py` (u. a.
ARCH-006, ARCH-007, ARCH-008, ARCH-009 Phase 1/3/5/6/7,
ENGINEERING_BASELINE, REVERSE_ENGINEERED_DOCUMENTATION) — rein
informativ für eine spätere Umsetzung, keine Codeabhängigkeit.

---

## 5. Produktions-Consumer, die angepasst werden müssten

Bei **Option B** (empfohlen): genau **2** Dateien —
`handlers/navidrome_menu_handler.py`, `services/statistik_service.py`.

Bei **Option A**: **3** Dateien — zusätzlich
`handlers/menu/rich_menu_handler.py`.

Keine weiteren Produktions-Consumer gefunden (repo-weiter Grep über
`NavidromeAPI\.`/`NavidromeAPI(` bestätigt exakt dieselben drei Dateien
wie bereits in ARCH-009 Phase 6/7 dokumentiert — seit Phase 7 keine neuen
hinzugekommen).

---

## 6. Tests und Mock-/Patch-Ziele

Repo-weiter Grep nach `"api.navidrome_api` als String-Patch-Ziel
(entscheidend, da `mock.patch("...")` mit String-Pfaden arbeitet und bei
einer Verschiebung bricht, im Gegensatz zu `patch.object(objekt, ...)` auf
bereits importierten Objekten, das unabhängig vom Ursprungspfad
funktioniert):

| Datei | Betroffen? | Art |
|---|---|---|
| `tests/test_navidrome_api_characterization.py` | ja | Import-Zeile (`from api.navidrome_api import NavidromeAPI`); `TestExecuteScan` nutzt `patch.object(NavidromeScanTrigger, ...)` — unabhängig vom `NavidromeAPI`-Pfad, aber bei Option B müsste die Klasse trotzdem in eine eigene Testdatei wandern (Abschnitt 3) |
| `tests/test_navidrome_api_timeout.py` | ja | Import-Zeile + 3× `patch("api.navidrome_api.requests.get", ...)` |
| `tests/test_navidrome_api_logging.py` | ja | Import-Zeile + 1× `patch("api.navidrome_api.requests.get", ...)` |
| `tests/test_navidrome_menu_handler.py` | ja | 1× `patch("api.navidrome_api.NavidromeAPI.make_request")` (String-Pfad zum **Ursprungsmodul**) |
| `tests/test_rich_menu_handler.py` | **nein** | patcht `"handlers.menu.rich_menu_handler.NavidromeAPI.execute_scan"` — ein String-Pfad zum **konsumierenden Modul**, nicht zum Ursprungsmodul. Da `handlers/menu/rich_menu_handler.py`s eigene `NavidromeAPI`-Bindung (egal woher importiert) patchbar bleibt, ist dieser Test **unabhängig vom tatsächlichen Speicherort von `NavidromeAPI`** — funktioniert bei Option A **und** Option B unverändert. |
| `tests/test_navidrome_scan_trigger.py` | nein | patcht ausschließlich `api.navidrome_scan_trigger.*` — unberührt, da `NavidromeScanTrigger` nicht verschoben wird |
| `tests/test_play_history_poller.py`, `tests/test_mugge_statistik_handler.py`, `tests/test_statistik_service.py` | nein | nutzen bereits injizierte Mock-/Instanz-Objekte, keine Pfad-Patches auf `api.navidrome_api` |

**Konkrete, aus dem Fund in `tests/test_rich_menu_handler.py` abgeleitete
Empfehlung für die Umsetzung:** wo technisch möglich, Patch-Ziele auf das
**konsumierende Modul** umstellen (`patch("handlers.navidrome_menu_handler.NavidromeAPI.make_request")`
statt `patch("api.navidrome_api.NavidromeAPI.make_request")` bzw. nach der
Verschiebung `patch("services.clients.navidrome_api.NavidromeAPI.make_request")`)
— das ist robuster gegenüber künftigen Verschiebungen und entspricht
einem bereits im Repo etablierten, funktionierenden Muster.

---

## 7. Versteckte dynamische Imports oder sonstige Abhängigkeiten

Repo-weiter Grep nach `importlib`/`__import__`/`import_module` in
Verbindung mit Navidrome: **keine Treffer**. Keine dynamischen Imports auf
`api.navidrome_api` gefunden. Die einzigen „dynamischen“ Abhängigkeiten
auf den Modulpfad sind die in Abschnitt 6 aufgeführten String-Patch-Ziele
in Tests (technisch kein `importlib`, aber ebenso pfadabhängig und daher
hier vollständigkeitshalber mit erfasst).

---

## 8. Zirkelimport-Risiko

**Kein Zirkelimport-Risiko festgestellt, unabhängig von Option A/B.**

- `api/navidrome_scan_trigger.py` importiert ausschließlich `asyncio`,
  `dataclasses`, `functools`, `config` — **keine** Abhängigkeit zu
  `services/` oder `api/navidrome_api.py`. Ein Import
  `services.clients.navidrome_api` → `api.navidrome_scan_trigger` (nötig
  nur bei Option A) wäre daher einseitig, kein Zyklus.
- Etabliertes, bereits funktionierendes Präzedenzmuster:
  `services/downloader/utils/enhanced_metadata_processor.py` und
  `services/downloader/utils/metadata/album_processor.py` importieren
  bereits heute aus `services/clients/` (`GeniusClient` u. a.) — die
  Konsumrichtung `services/` → `services/clients/` ist damit bereits
  etabliert und funktioniert. Der neue Import
  `services/statistik_service.py` → `services/clients/navidrome_api`
  folgt exakt demselben, bereits bewährten Muster.
- Bei Option B bräuchte `services/clients/navidrome_api.py` **gar keine**
  Abhängigkeit zu `api/` — noch geringeres Risiko als Option A.

---

## 9. Ist `services/clients/navidrome_api.py` nach der Verschiebung tatsächlich ein reiner externer Integrationsadapter?

| Kriterium | Bei Option A | Bei Option B |
|---|---|---|
| Keine Telegram-Präsentation | ⚠️ funktional ja, aber toter `ParseMode`-Import zieht sichtbar mit (Abschnitt 1) | ⚠️ dasselbe, sofern der tote Import nicht im selben Schritt bereinigt wird (Abschnitt 12 Punkt 3) |
| Keine fachliche Orchestrierung | ✅ erfüllt (unverändert seit Phase 6) | ✅ erfüllt |
| Reiner externer Integrationsadapter (strukturell, alle Methoden) | ❌ `execute_scan()` bleibt struktureller Fremdkörper im Adapter | ✅ vollständig erfüllt — alle verbleibenden Methoden sind reine API-Kommunikation |

**Ergebnis: nur Option B erfüllt die Konvention vollständig.** Option A
verschiebt die in ARCH-009 Phase 3 begonnene Entflechtung an einen neuen
Ort, löst sie aber nicht auf.

---

## 10. `api/__init__.py`, `api/navidrome_scan_trigger.py`, bestehende Imports, Kompatibilitäts-Bridge

- **`api/__init__.py`**: aktuell leer (0 Bytes), keine Re-Exports, keine
  Anpassung nötig unabhängig von der gewählten Option.
- **`api/navidrome_scan_trigger.py`**: bleibt unverändert am Ort (explizite
  Vorgabe dieses Auftrags). Bei Option B bleibt es weiterhin der einzige
  fachliche Nachbar von `execute_scan()` in `api/` — beide zusammen bilden
  dann den "lokale Infrastruktur/Subprocess"-Teil, den ARCH-009 Phase 3
  bereits als eigenständig (nicht `services/clients/`-fähig) eingestuft
  hatte.
- **Folgefrage, nicht Teil dieser Phase**: Falls `api/navidrome_api.py`
  nach Option B nur noch `execute_scan()` enthält, rückt `api/` inhaltlich
  noch näher an ein reines „lokale Navidrome-Infrastruktursteuerung“-Paket
  (zusammen mit `navidrome_scan_trigger.py`) — ob der Name `api/` dafür
  langfristig noch passend ist, ist eine spätere, eigene Entscheidung
  (vgl. ARCH-009 Phase 6 Abschnitt 9, dort bereits als offener Punkt
  vermerkt).
- **Bestehende Imports**: siehe Abschnitt 4/5.
- **Mögliche Kompatibilitäts-Bridge**: `api/navidrome_api.py` könnte
  (unabhängig von Option A/B für `execute_scan()`) übergangsweise einen
  Re-Export `from services.clients.navidrome_api import NavidromeAPI`
  behalten, damit nicht alle Consumer/Tests im selben Schritt angepasst
  werden müssen — analog zum bereits in der ursprünglichen
  ARCH-009-Migrationsplanung genannten „Migration Bridge“-Konzept. Bei
  Option B wäre das kombinierbar: `api/navidrome_api.py` enthält dann
  sowohl den echten `execute_scan()`-Rest als auch übergangsweise einen
  Re-Export-Alias für die verschobene Klasse.

---

## 11. Vergleich mit der etablierten `services/clients/`-Regel

| Regel | Status nach Phase 7 (`api/`) | Status nach Verschiebung, Option A | Status nach Verschiebung, Option B |
|---|---|---|---|
| Ausschließlich externe Integrationsadapter | 6/7 Methoden ja | 6/7 (unverändert) | 7/7 (vollständig) |
| Keine Telegram-Präsentation | funktional ja, toter Import vorhanden | zieht toten Import mit | löst sich nur, wenn Import mitbereinigt wird |
| Keine fachliche Orchestrierung | ✅ | ✅ | ✅ |
| Instanz + DI statt statische Klasse | ✅ (seit Phase 7) | ✅ | ✅ |

---

## 12. Empfehlung, Migrationsschritte, Risiken, Teststrategie, Entscheidungsgate

### A) Empfohlene Zielstruktur

```
services/
└── clients/
    └── navidrome_api.py     — __init__, _build_url, make_request,
                                check_connection, get_artists,
                                get_now_playing, search
                                (Option B: reiner Adapter, 7/7-Konformität)

api/
├── navidrome_api.py         — Rest: ausschließlich execute_scan()
│                               (Option B), ggf. übergangsweise mit
│                               Re-Export-Alias für Kompatibilität
└── navidrome_scan_trigger.py — unverändert
```

**Empfohlen: Option B** (Abschnitt 3) — einzige Variante, die
`services/clients/navidrome_api.py` vollständig konform zur etablierten
Regel macht, und die zusätzlich `handlers/menu/rich_menu_handler.py`
komplett von der Migration ausnimmt (Abschnitt 3/4/5), da dieser Consumer
ausschließlich `execute_scan()` nutzt.

Klassenname/Dateiname `navidrome_api.py`/`NavidromeAPI` wie vom Auftrag
vorgegeben beibehalten (keine Umbenennung zu `NavidromeClient` o. ä. in
dieser Empfehlung) — eine Umbenennung wäre eine zusätzliche, von diesem
Auftrag nicht verlangte Änderung und bleibt eine offene Frage für das
Entscheidungsgate (Punkt 4 unten).

### B) Konkrete Migrationsschritte (spätere Umsetzung, nicht Teil dieser Phase)

1. `services/clients/navidrome_api.py` neu anlegen: sechs Methoden +
   `__init__` 1:1 aus `api/navidrome_api.py` übernehmen.
2. `services/clients/__init__.py` um `NavidromeAPI`-Re-Export ergänzen.
3. `api/navidrome_api.py` auf den `execute_scan()`-Rest reduzieren
   (Option B) — Klassen-/Funktionsform Teil der Umsetzung, nicht dieser
   Analyse.
4. `handlers/navidrome_menu_handler.py`, `services/statistik_service.py`
   auf den neuen Importpfad umstellen (2 Dateien, Abschnitt 5).
   `handlers/menu/rich_menu_handler.py` **unverändert** lassen.
5. `tests/test_navidrome_api_characterization.py` aufspalten: die sechs
   Adapter-Testklassen (inkl. der neuen `TestDependencyInjection` aus
   Phase 7) wandern in eine neue Testdatei parallel zum neuen Speicherort
   (z. B. `tests/test_navidrome_api_client_characterization.py` o. ä.,
   Benennung Teil der Umsetzung), `TestExecuteScan` bleibt bei
   `api/navidrome_api.py` bzw. wandert in eine eigene, kleine Testdatei.
6. `tests/test_navidrome_api_timeout.py`, `tests/test_navidrome_api_logging.py`,
   `tests/test_navidrome_menu_handler.py` auf neue Pfade anpassen — dabei
   nach Möglichkeit auf konsumierende-Modul-Patches umstellen (Abschnitt 6).
7. Optional: temporäre Kompatibilitäts-Bridge in `api/navidrome_api.py`
   für einen gestuften statt atomaren Umbau (Abschnitt 10).
8. Gezielte Tests je Teilschritt, abschließend vollständiger
   Regressionslauf (Vorbild: identische Disziplin wie ARCH-009 Phase 7).
9. Dokumentations-Nachträge (mindestens ENGINEERING_BASELINE.md und die
   ARCH-009-Roadmap; die übrigen 12 historischen ARCH-Dokumente bleiben
   als Zeitpunkt-Snapshots unverändert, wie in dieser Session bereits bei
   früheren Migrationen gehandhabt).

### C) Risiken

1. **Import-Pfad-Fehler an mehreren Stellen** (2 Produktionsdateien + 3-4
   Testdateien bei Option B) — mechanisch, aber fehleranfällig ohne
   systematische Grep-Verifikation nach jedem Schritt.
2. **Fehlentscheidung A vs. B ist architektonisch teurer rückgängig zu
   machen** als ein reiner Datei-Umzug — bei Option A müsste eine spätere
   Korrektur (execute_scan() doch noch heraustrennen) den Adapter ein
   zweites Mal anfassen.
3. **Toter `ParseMode`-Import** landet sichtbar in `services/clients/`,
   falls nicht im selben Schritt bereinigt (Abschnitt 1/9) — geringes
   technisches Risiko, aber ein direkter, vermeidbarer Verstoß gegen die
   gerade erst durchgesetzte Konvention.
4. **Testaufwand bei Aufspaltung** (Option B, Schritt 5) — eine
   bestehende Testdatei wird in zwei geteilt, das ist mehr Aufwand als
   eine reine Pfadanpassung, aber kein neues Risiko (keine
   Verhaltensänderung, nur Umzug/Aufteilung von Testcode).
5. **`api/`-Package-Sinnhaftigkeit** nach der Verschiebung (Abschnitt 10)
   — kein akutes Risiko, aber ein liegen gelassener Folgepunkt, der bei
   einer sehr viel späteren Aufräumaktion nochmal aufgegriffen werden
   müsste.

### D) Teststrategie

- Alle bestehenden Charakterisierungstests bleiben inhaltlich unverändert
  (reine Pfad-/Struktur-Anpassung, keine Verhaltensänderung) — Vorgehen
  wie in ARCH-009 Phase 7 etabliert: Vorher/Nachher-Vergleich, keine
  Tests löschen, bekannte Vorbestand-Fehler separat ausweisen.
- Wo möglich, Patch-Ziele auf das konsumierende Modul umstellen statt auf
  den Ursprungspfad (Abschnitt 6) — reduziert künftige
  Migrationsschmerzen bei einer eventuellen weiteren Verschiebung.
- Nach jedem Teilschritt gezielter Testlauf, abschließend vollständige
  Regression (1012 bestandene Tests als aktuelle Baseline, 15 bekannte
  Vorbestand-Fehler als Vergleichsgröße).
- Import-Smoke-Test nach jedem Teilschritt (Vorbild: alle vorherigen
  ARCH-009-Phasen).

### E) Entscheidungsgate

Diese Analyse ist abgeschlossen. **Keine Codeänderung wurde vorgenommen.**

Offene Entscheidungen:

1. **Option A oder Option B** für `execute_scan()` (Abschnitt 3) — diese
   Analyse empfiehlt B, entscheidet aber nicht selbst.
2. Soll eine **temporäre Kompatibilitäts-Bridge** verwendet werden
   (gestufter Übergang) oder ein **direkter Cutover** (alle
   Consumer/Tests in einem Schritt)?
3. Sollen die bekannten toten Importe (`ParseMode`, `re`, `subprocess`,
   `Path`) **im selben Schritt** bereinigt werden, da die Datei ohnehin
   umgezogen wird, oder strikt getrennt behandelt (eigener, späterer
   Cleanup-Schritt)?
4. Soll die Klasse bei der Verschiebung **umbenannt** werden (z. B.
   `NavidromeClient`, konsistent mit der P-11-Namenskonvention) oder
   bleibt sie `NavidromeAPI` (wie im Auftrag als Dateiname
   `services/clients/navidrome_api.py` vorgegeben)?
5. Sollen die ~14 historischen Dokumentationsverweise auf
   `api.navidrome_api` aktualisiert werden, oder bleiben sie als
   Zeitpunkt-Snapshots unverändert (bisheriges Vorgehen in dieser
   Session)?

**Es wird nicht selbstständig mit einer Umsetzung begonnen.** Nächster
Schritt erst nach expliziter Nutzerentscheidung, in einem eigenen Branch,
mit eigenem PR/Review/Merge-Zyklus wie in allen vorherigen
ARCH-009-Schritten.
