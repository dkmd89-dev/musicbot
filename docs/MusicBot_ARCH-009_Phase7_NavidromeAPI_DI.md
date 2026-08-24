# ARCH-009 Phase 7 — `NavidromeAPI` auf Dependency Injection umgestellt

Umsetzung von Variante B aus der ARCH-009-Phase-6-Analyse
(`docs/MusicBot_ARCH-009_Phase6_Zielposition_DI_Analyse.md`): `NavidromeAPI`
DI-fähig machen, **keine** Verschiebung nach `services/clients/` in diesem
Schritt. Branch `arch/arch-009-phase7-navidrome-di`.

---

## 1. DI-Design

### Vorher

`NavidromeAPI` war eine reine `@classmethod`/`@staticmethod`-Klasse ohne
`__init__`. `_auth_params` war ein Klassenattribut, dessen Wert **beim
Modul-Import** ausgewertet wurde (`_get_navidrome_config()` lief zur
Klassendefinitionszeit) — ein Modul-Level-Seiteneffekt, der in der
ARCH-009-Migrationsplanung als Unterschied zu den P-11-Clients
dokumentiert wurde.

### Nachher

```python
class NavidromeAPI:
    def __init__(self, config=None):
        self.config = config or _get_navidrome_config()
        self._auth_params = {
            "u": self.config.NAVIDROME_USER,
            "p": self.config.NAVIDROME_PASS,
            "v": "1.16.1",
            "c": "telegram-bot",
            "f": "json",
        }
```

- `NavidromeAPI()` ohne Argumente verhält sich **unverändert** wie zuvor
  (nutzt weiterhin `_get_navidrome_config()`, denselben gecachten
  Singleton-Zugriff auf die globale Config).
- `_auth_params` wird jetzt **pro Instanz** in `__init__()` gebaut statt
  einmalig beim Modul-Import. Da `NAVIDROME_USER`/`NAVIDROME_PASS`
  `@property`s auf `Config` sind (lesen live `os.getenv(...)`, siehe
  `config.py:200-208`), sind die zurückgegebenen Werte identisch — nur
  der Zeitpunkt der Auswertung ändert sich (Instanzierung statt
  Modul-Import), kein beobachtbarer Unterschied in Produktion.
- **Sechs Methoden wurden von `@classmethod`/`@staticmethod` auf echte
  Instanzmethoden umgestellt** (nutzen jetzt `self` statt `cls`):
  `_build_url()`, `make_request()`, `check_connection()`, `get_artists()`,
  `get_now_playing()`, `search()`.
- **`execute_scan()` bleibt bewusst ein `@classmethod`** — reiner,
  zustandsloser Pass-Through zu `NavidromeScanTrigger.run_scan()` (siehe
  ARCH-009 Phase 4/5), benötigt keinerlei injizierte Config/Instanz.
  Unverändert, da die DI-Umstellung hierfür technisch nicht zwingend war
  (Vorgabe: „keine Änderung an `execute_scan()` außer wenn zwingend
  nötig“). Bleibt uneingeschränkt sowohl klassenweise
  (`NavidromeAPI.execute_scan()`) als auch instanzweise
  (`instance.execute_scan()`) aufrufbar, da `@classmethod`s über Python
  auch auf Instanzen zugreifbar sind.
- **Bewusst NICHT instanzspezifisch gemacht**: `NAVIDROME_REQUEST_TIMEOUT`
  (`getattr(Config, "NAVIDROME_REQUEST_TIMEOUT", 15)`) und
  `Config.mask_sensitive(...)` in `make_request()` bleiben an die globale
  `Config`-Klasse gebunden, nicht an `self.config`. Diese beiden Werte
  waren nicht Teil des in Phase 6 identifizierten Problems (Modul-Import-
  Seiteneffekt von `_auth_params`) — eine Umstellung wäre eine
  funktionale Erweiterung über den Auftrag hinaus gewesen („keine
  funktionale Optimierung nebenbei“).

### Wichtiger Fund während der Umsetzung: `config`-Parameter NICHT an
### `NavidromeMenuHandler`s Default-Instanz durchreichen

Ursprünglich geplant war, `NavidromeMenuHandler`s Default-Konstruktion mit
`NavidromeAPI(config)` (dem an den Handler übergebenen `config`-Objekt) zu
bauen. Der gezielte Testlauf deckte dabei einen echten Verhaltensunterschied
auf: `tests/test_navidrome_menu_handler.py::test_partially_configured_navidrome_sets_connection_status_false`
konstruiert `NavidromeMenuHandler` mit einem unvollständigen Test-Double
(`PartialConfig`, besitzt nur `NAVIDROME_URL`/`NAVIDROME_USER`, kein
`NAVIDROME_PASS`). Vor dieser Migration bezog `NavidromeAPI` seine
`_auth_params` **immer** aus der echten globalen Config-Singleton-Instanz,
komplett unabhängig davon, welches `config`-Objekt an den Handler
übergeben wurde. `NavidromeAPI(config)` hätte diese Entkopplung
aufgehoben und wäre bei unvollständigen `config`-Objekten (in Produktion
nicht zu erwarten, aber ein bestehendes Test-Double) mit `AttributeError`
abgestürzt — eine Verhaltensänderung. **Korrektur**: Default bleibt
`NavidromeAPI()` (ohne Argumente, echte globale Config), exakt wie vor der
Migration. Dokumentiert als Inline-Kommentar in
`handlers/navidrome_menu_handler.py`.

---

## 2. Migrierte Consumer

### `services/statistik/play_history_poller.py` / `services/statistik_service.py` (Schritt 3)

**Kein Code geändert.** Verifiziert als bereits konform zum neuen Ansatz:
`StatistikService.__init__()` konstruierte bereits vor dieser Migration
`self.api = navidrome_api if navidrome_api is not None else NavidromeAPI()`
und übergab die Instanz per Konstruktor-Injection an `PlayHistoryPoller`,
der ausschließlich `self.api.get_now_playing()` aufruft (nie eine
`NavidromeAPI`-Klassenmethode direkt). Das ist exakt das Muster, auf das
die DI-Umstellung hinausläuft — hier gab es strukturell nichts zu
migrieren.

**Wichtige Verhaltenspräzisierung**: vor dieser Migration war
`self.api.get_now_playing()` zwar syntaktisch ein Instanzaufruf, `cls`
löste aber intern immer auf die **Klasse** auf (weil `get_now_playing()`
ein `@classmethod` war) — jede `NavidromeAPI()`-Instanz nutzte de facto
dieselben klassenweiten `_auth_params`. Seit dieser Migration verwendet
`self.api.get_now_playing()` echt die `_auth_params` **dieser konkreten
Instanz**. Für den Produktivbetrieb (immer dieselbe globale Config) ist
das Ergebnis identisch — es ist aber die erste tatsächlich wirksame
Instanz-Isolation für diesen Consumer.

Verifiziert über den bestehenden, unveränderten Testlauf
`tests/test_statistik_service.py` (konstruiert `StatistikService()` ohne
injizierten `navidrome_api` — durchläuft damit real den neuen
`NavidromeAPI()`-Konstruktionspfad), `tests/test_play_history_poller.py`
und `tests/test_mugge_statistik_handler.py` — alle 38 Tests weiterhin
grün.

### `handlers/navidrome_menu_handler.py` (Schritt 4)

**11 statische Aufrufe auf 6 Methoden migriert:**

| Vorher | Nachher | Vorkommen |
|---|---|---|
| `NavidromeAPI.get_artists()` | `self.navidrome_api.get_artists()` | 1× (`handle_browse_artists`) |
| `NavidromeAPI.make_request` (als Callable an `asyncio.to_thread`) | `self.navidrome_api.make_request` | 9× (`getArtist` ×2, `getAlbumList2`, `getGenres`, `getSongsByGenre`, `getPlaylists`, `getStarred2`, `getAlbumList`, `getIndexes`) |
| `NavidromeAPI.search(query)` | `self.navidrome_api.search(query)` | 1× (`process_search_query`) |

**Neuer, optionaler Konstruktor-Parameter:**

```python
def __init__(self, config: Config, logger_factory=None, navidrome_api=None):
    ...
    self.navidrome_api = (
        navidrome_api if navidrome_api is not None else NavidromeAPI()
    )
```

Der bestehende Konstruktionsaufruf
`handlers/menu/rich_menu_handler.py:220: NavidromeMenuHandler(self.config, self.logger_factory)`
musste **nicht** angepasst werden — der neue Parameter ist optional mit
sinnvollem Default, positionelle Argumente bleiben unverändert gültig.

**`_check_connection()` bewusst unverändert** — prüft weiterhin
`self.connection_status and NavidromeAPI is not None` (Referenz auf die
importierte Klasse, nicht auf `self.navidrome_api`). Das ist der bereits
dokumentierte BUG-007-Fund (diese Prüfung ist strukturell immer `True`) —
außerhalb des Auftrags, unangetastet gelassen.

### `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()` — **nicht migriert**

`NavidromeAPI.execute_scan()` bleibt ein statischer Aufruf. Nicht Teil der
in der Aufgabenstellung genannten Reihenfolge (dort werden ausschließlich
`play_history_poller.py` und `navidrome_menu_handler.py` genannt), und
technisch auch nicht nötig, da `execute_scan()` bewusst `@classmethod`
geblieben ist (Abschnitt 1) — ein Umstieg auf eine injizierte Instanz
hätte hier keinen Mehrwert, da die Methode ohnehin zustandslos ist. Siehe
Abschnitt 4 (verbleibende statische Aufrufe).

---

## 3. Geänderte Tests

| Datei | Änderung |
|---|---|
| `tests/test_navidrome_api_characterization.py` | `TestCheckConnection`/`TestGetArtists`/`TestGetNowPlaying`/`TestSearch` konstruieren jetzt `api = NavidromeAPI()` und patchen `api.make_request` (Instanz) statt der Klasse. `TestExecuteScan` unverändert. **Neu:** `TestDependencyInjection` (3 Tests) — verifiziert injizierte Config wird für `_auth_params` verwendet, zwei Instanzen mit unterschiedlicher Config sind unabhängig voneinander, `NavidromeAPI()` ohne Argumente nutzt weiterhin die echte globale Config (Bestandsschutz). |
| `tests/test_navidrome_api_timeout.py` | Alle 3 Tests: `api = NavidromeAPI()` konstruiert, `patch.object(api, "_build_url", ...)` statt `patch.object(NavidromeAPI, "_build_url", ...)`, `api.make_request("ping")` statt `NavidromeAPI.make_request("ping")`. `patch.object(Config, "NAVIDROME_REQUEST_TIMEOUT", 7)` unverändert (globale Klasse, siehe Abschnitt 1). |
| `tests/test_navidrome_api_logging.py` | SEC-001-Regressionstest: `api = NavidromeAPI()` konstruiert, `patch.object(api, "_auth_params", fake_auth_params)`/`patch.object(api, "_build_url", ...)` statt Klassen-Patches, `api.make_request("ping")` statt `NavidromeAPI.make_request("ping")`. Testverhalten/-aussage unverändert (Credential-Masking weiterhin verifiziert). |
| `handlers/navidrome_menu_handler.py` | 11 Call-Sites migriert (Abschnitt 2), `__init__`-Signatur erweitert. |
| `tests/test_navidrome_menu_handler.py` | **Keine Änderung nötig** — alle Tests mocken entweder `asyncio.to_thread` komplett (Argumentwert irrelevant) oder prüfen nur `assert_not_called()`. Diente als Regressionsnetz, deckte den in Abschnitt 1 beschriebenen Fund auf. |
| `tests/test_rich_menu_handler.py` | **Keine Änderung** — `execute_scan()` unverändert `@classmethod`. |
| `tests/test_navidrome_scan_trigger.py` | **Keine Änderung** — `NavidromeScanTrigger` nicht Teil dieser Migration. |
| `tests/test_play_history_poller.py`, `tests/test_mugge_statistik_handler.py`, `tests/test_statistik_service.py` | **Keine Änderung** — nutzen bereits vollständig gemockte/injizierte `api`-Objekte bzw. konstruieren `StatistikService()` real (Abschnitt 2). |

Keine Tests wurden gelöscht.

---

## 4. Regressionsergebnis

**Gezielt** (alle Navidrome-/Statistik-relevanten Testdateien): 91 Tests
grün (`test_navidrome_api_characterization.py`,
`test_navidrome_api_timeout.py`, `test_navidrome_api_logging.py`,
`test_navidrome_menu_handler.py`, `test_rich_menu_handler.py`,
`test_navidrome_scan_trigger.py`, `test_play_history_poller.py`,
`test_mugge_statistik_handler.py`), zusätzlich separat
`test_statistik_service.py` (38 Tests zusammen mit den beiden zuletzt
genannten Dateien) grün.

**Vollständig:** 1012 bestanden (vorher 1009 — Differenz von 3 entspricht
exakt den 3 neuen `TestDependencyInjection`-Tests), **unverändert 15
bekannte Vorbestand-Fehler** (separat ausgewiesen, unberührt von dieser
Migration):

- `tests/test_auto_learn.py::TestAutoLearnManager::test_is_artist_known_from_auto_learned`
- `tests/test_auto_learn.py::TestAutoLearnManager::test_is_non_artist_channel` (2 Subtests)
- `tests/test_auto_learn.py::TestAutoLearnManager::test_load_auto_learned_artists_with_data`
- `tests/test_auto_learn.py::TestAutoLearnManager::test_load_auto_learned_genres_with_data`
- `tests/test_auto_learn.py::TestAutoLearnAsync::test_learn_artist_same_as_canonical`
- `tests/test_metadata_modules.py::TestTitleCleaner::test_apply_cleanup_rules` (3 Subtests)
- `tests/test_metadata_modules.py::TestTitleCleaner::test_clean_title_with_explicit`
- `tests/test_metadata_modules.py::TestTitleCleaner::test_clean_youtube_title_basic`
- `tests/test_suite.py::TestRichMenuSystem::test_show_menu`
- `tests/test_suite.py::TestRichMenuSystem::test_handle_callback_close`
- `tests/test_suite.py::TestRichMenuSystem::test_handle_callback_back`
- `tests/test_suite.py::TestMenuIntegration::test_full_navigation_flow`

Keine neuen Fehlschläge. Import-Smoke-Test erfolgreich
(`api.navidrome_api`, `handlers.navidrome_menu_handler`,
`handlers.menu.rich_menu_handler`, `services.statistik_service`,
`services.statistik.play_history_poller`), kein Zirkelimport.

---

## 5. Verbleibende statische Aufrufe

Nach diesem Schritt existiert genau **ein** verbleibender statischer
`NavidromeAPI`-Aufruf in Produktionscode:

```
handlers/menu/rich_menu_handler.py:740  NavidromeAPI.execute_scan()
```

Bewusst nicht migriert (Abschnitt 2) — `execute_scan()` ist ein
zustandsloser `@classmethod`, für den eine Instanz-Injection keinen
technischen Mehrwert hätte, und war nicht Teil der vorgegebenen
Reihenfolge dieses Auftrags.

Alle anderen produktiven `NavidromeAPI`-Zugriffe laufen jetzt über
injizierte bzw. bewusst default-konstruierte Instanzen
(`self.navidrome_api` in `NavidromeMenuHandler`, `self.api` in
`StatistikService`/`PlayHistoryPoller`).

---

## 6. Offene Punkte für die spätere Verschiebung nach `services/clients/`

Diese Punkte sind **nicht** Teil dieser Phase, werden hier nur für die
nächste Entscheidung festgehalten:

1. **Reihenfolge-Klärung in der Roadmap**: `docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md`
   führte DI bisher als „Phase 8“ nach der Zielort-Entscheidung „Phase 7“.
   Diese Migration hat DI vorgezogen (gemäß Phase-6-Empfehlung) — die
   Roadmap-Nummerierung sollte entsprechend angepasst oder zumindest
   explizit kommentiert werden (siehe Abschnitt 7 unten, bereits erledigt).
2. **`execute_scan()` bei einer künftigen Verschiebung**: bleibt als
   `@classmethod`-Kompatibilitätsrest in `api/` zurück, oder wird —
   wie bereits als Option im Phase-5-Entscheidungsgate diskutiert, aber
   nicht gewählt — vollständig entfernt zugunsten eines direkten
   `NavidromeScanTrigger.run_scan()`-Aufrufs im Handler? Weiterhin offen.
3. **`NavidromeScanTrigger`**: bleibt außerhalb von `services/clients/`
   (wie in diesem Auftrag vorgegeben) — endgültiger Zielort weiterhin
   nicht entschieden (ARCH-009 Phase 3 Empfehlung: eigener, von
   `services/clients/` getrennter Ort).
4. **`_check_connection()`**-Inkonsistenz in `handlers/navidrome_menu_handler.py`
   (`NavidromeAPI is not None`, strukturell immer `True`, dokumentierter
   BUG-007-Fund) bleibt unverändert — unabhängig von einer künftigen
   Verschiebung zu betrachten.
5. **`check_connection()`** hat weiterhin 0 Produktions-Consumer
   (dokumentierter BUG-007-Beleg für bewusst zurückgestellte Nutzung) —
   unverändert durch diese Migration, würde bei einer künftigen
   Verschiebung als reguläre Instanzmethode mitwandern.
6. **Import-Pfad-Änderungen bei einer künftigen Verschiebung** beträfen
   jetzt dieselben 3 Consumer-Dateien wie in der Phase-6-Analyse
   beschrieben (`handlers/navidrome_menu_handler.py`,
   `handlers/menu/rich_menu_handler.py`, `services/statistik_service.py`)
   — durch diese Migration nicht verändert, nur die Art des Zugriffs
   (Instanz statt Klasse) hat sich geändert.

---

## 7. Roadmap-Nachtrag

`docs/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md` wurde um einen
Abschluss-Eintrag „ARCH-009 Phase 7 — NavidromeAPI DI-Umstellung“ unter
„Bereits abgeschlossen“ ergänzt. Die dort noch offene „Phase 7 —
Zielstruktur entscheiden“ (Verschiebung nach `services/clients/`) bleibt
als nächster, separat zu entscheidender Schritt bestehen — die DI-Frage
(vormals dort als „Phase 8“ geführt) ist mit dieser Migration erledigt.

**ARCH-009 Phase 7 damit abgeschlossen.** Keine eigenständige Weiterarbeit
an der Verschiebung nach `services/clients/` begonnen.
