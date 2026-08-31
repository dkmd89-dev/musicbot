# POST-ARCH-009 — Architektur-Audit

**Stand:** 2026-08-24
**Basis:** `main` @ `d07cddb` (ARCH-009 Folgeumsetzung, gemergt)
**Methode:** Direkte Repository-Inspektion (Verzeichnis-/Import-Audit, repo-weite Greps auf die in Abschnitt 3 gelisteten Muster, gezielte Dateiprüfung). Kein Rückgriff auf vorhandene Dokumentation als primäre Quelle — der Code ist die Quelle.

---

## 1. Tatsächlicher Repository-Zustand

```text
services/clients/   → genius_client.py, lastfm_client.py, musicbrainz_client.py, navidrome_api.py
services/downloader/→ downloader.py, spotify_downloader.py, playlist_processor.py,
                       download/ (download_executor.py, channel_router.py, cache_manager.py, ...),
                       utils/ (enhanced_metadata_processor.py, metadata/*, ...)
services/statistik/ → play_history_repository.py, play_history_poller.py, statistics_calculator.py, chart_renderer.py
services/           → statistik_service.py (Fassade)
utils/               → artist_map.py, genre_map.py, filenamefixer.py, file_ops.py, helpers.py,
                        cache.py, lyrics_cache.py, metadata_cache.py, navidrome_scan_trigger.py,
                        audio_enhancer.py, podcast_rss_manager.py, regex.py, singleton.py, youtube_parser.py
handlers/            → menu/, admin/, adapters/, sowie Einzel-Handler (navidrome_menu_handler.py,
                        duplicate_handler.py, test_menu_handler.py, mugge_statistik_handler.py, ...)
klassen/             → nur noch download_handler.py (Orchestrator)
api/                 → existiert nicht mehr (verifiziert: kein Verzeichnis, `import api.navidrome_api`
                        und `import api.navidrome_scan_trigger` liefern `ModuleNotFoundError`)
```

`api/` wurde nicht als Schicht angenommen, sondern per `ls`/`find`/Import-Smoke-Test verifiziert entfernt.

---

## 2. Was ARCH-009 tatsächlich verbessert hat

| Kriterium | Vor ARCH-009 | Nach ARCH-009 (verifiziert) |
|---|---|---|
| Trennung externer API-Clients | `api/navidrome_api.py` vermischte Subsonic-API-Kommunikation mit allem Übrigen | `services/clients/navidrome_api.py` enthält ausschließlich die 6 API-Methoden; kein Telegram-Import (einziger Grep-Treffer für `"telegram"` ist der Subsonic-Client-Parameter `"c": "telegram-bot"`, kein Framework-Import) |
| Trennung lokaler Infrastruktur/Subprocess | Subprocess-Steuerung war Teil von `NavidromeAPI.execute_scan()` | `utils/navidrome_scan_trigger.py::NavidromeScanTrigger.run_scan()` — eigenständig, folgt dem `utils/audio_enhancer.py`-Präzedenzfall (Subprocess-Wrapper + `@dataclass`-Ergebnis) |
| Telegram-Abhängigkeiten | Telegram-MarkdownV2-Formatierung lag in `execute_scan()` | Formatierung liegt vollständig in `handlers/menu/rich_menu_handler.py::_handle_navidrome_scan()`; verifiziert 0 Telegram-Importe in `services/clients/navidrome_api.py` und `utils/navidrome_scan_trigger.py` |
| Handler-/Service-Grenzen | `handlers/` und `api/` beide von `NavidromeAPI` abhängig, keine klare Ownership | `handlers/` konsumiert `services.clients.navidrome_api` (API) und `utils.navidrome_scan_trigger` (Subprocess) über getrennte, klar benannte Importe |
| Dependency Injection | `NavidromeAPI` rein statisch, Config als Modul-Import-Seiteneffekt | `NavidromeAPI(config=None)` instanziierbar, `_auth_params` pro Instanz; `NavidromeMenuHandler`/`StatistikService` injizieren optional |
| Statisch vs. instanzbasiert | Alle Methoden `@classmethod`/`@staticmethod` | 6 der 7 ehemaligen Methoden sind Instanzmethoden; `execute_scan()` selbst wurde in Phase 9 vollständig eliminiert (kein Kompromiss mehr nötig) |
| Import-/Dependency-Richtung | `services/statistik_service.py` importierte aus `api.navidrome_api` (Bruch der P-11-Konvention, dokumentiert in ARCH-006) | `services/statistik_service.py` importiert aus `services.clients.navidrome_api` — Bruch behoben |
| Verantwortlichkeiten in `services/` | vermischt (API + Subprocess + teils Präsentation) | `services/clients/` = reine externe Adapter (bestätigt für alle 4 Dateien dort) |
| Verantwortlichkeiten in `utils/` | `NavidromeScanTrigger` lag in `api/`, nicht in `utils/` | liegt jetzt neben dem strukturell identischen `audio_enhancer.py` — Konvention erstmals durch ein zweites Beispiel bestätigt, nicht mehr Einzelfall |
| Entfernung `api/`-Schicht | bestand als undokumentierte historische Restschicht | vollständig entfernt, 0 verbleibende funktionale Referenzen (Code), nur noch historische Docstring-/Doku-Erwähnungen |
| Testbarkeit | ~30 Testreferenzen an einer vermischten statischen Klasse | Patch-Ziele konsequent auf konsumierende Module umgestellt (überlebt künftige Verschiebungen); dedizierte Testdatei je Verantwortlichkeit (`test_navidrome_api_characterization.py` vs. `test_navidrome_scan_trigger.py`) |
| Verbleibende Bridges | `execute_scan()` als Pass-Through-Bridge (Phase 4–8) | vollständig eliminiert (Phase 9), keine Navidrome-Bridge mehr vorhanden |

**Ergebnis:** Alle in Abschnitt 2 verlangten Kriterien sind durch den aktuellen Code belegt, nicht nur behauptet — jede Zeile wurde per Grep/Read gegen den tatsächlichen Stand verifiziert (siehe Abschnitt 1 und die Einzel-Befunde in Abschnitt 3).

---

## 3. Repo-weite Suche nach ähnlichen Mustern

### A — Telegram-Kopplung außerhalb von `handlers/`

Grep nach `telegram`/`ParseMode`/`CallbackQuery`/`EMOJI`/`escape_md_v2` in `services/`, `utils/`, `klassen/`:

| Fund | Bewertung |
|---|---|
| `services/clients/navidrome_api.py` | Falsch-Positiv — Treffer ist der Subsonic-Request-Parameter `"c": "telegram-bot"` (API-Client-Kennung), kein Telegram-Framework-Import. Kein Fund. |
| `klassen/download_handler.py` (`from telegram import ...`, eigene `_MOD_EMOJI`/`_STEP_EMOJI`-Dicts) | Echter Treffer, aber **kein neuer Architekturbruch**: `DownloadHandler` ist laut `CLAUDE.md` Abschnitt 4 explizit Teil der Telegram-Präsentationskette (`Telegram → ExtendedBot → RichMenuHandler → DownloadHandler`) und in Abschnitt 19 als bekannter Orchestrator-Risikobereich benannt. Anders als die alte `NavidromeAPI` ist `DownloadHandler` kein externer API-Adapter mit versehentlicher Präsentationslogik, sondern der vorgesehene Orchestrator selbst. Kein ARCH-009-analoger Fund. |

Kein weiteres Modul in `services/`/`utils/`/`clients/` mit Telegram-Kopplung gefunden.

### B — Externe Integrationslogik außerhalb von `services/clients/`

Grep nach `requests.*/httpx/aiohttp/urllib.request` außerhalb `services/clients/`:

| Fund | Bewertung |
|---|---|
| `services/downloader/spotify_downloader.py` (6 Stellen: `urlopen`/`urlretrieve`, Zeilen 169, 352, 403/447, 456, 499, 730) | Echter Integrationsadapter-Kandidat. `SpotifyDownloader` ruft direkt HTTP-Endpunkte auf: Spotify-oEmbed-API (Metadaten-Auflösung), Spotify-Embed-HTML (Scraping), Cover-Art-Download, RSS-Episode-Download (`urlretrieve`), URL-Redirect-Resolution. Alle Aufrufe laufen bereits sauber über `loop.run_in_executor(...)` (kein Event-Loop-Blocking). Strukturell ähnlich zur alten `NavidromeAPI`: HTTP-Kommunikation vermischt mit Download-Orchestrierung (942 Zeilen, `yt-dlp`-Steuerung + HTTP-Fetches + RSS-Parsing in einer Klasse). **Kein 1:1-Analogon** zu ARCH-009, da `SpotifyDownloader` fundamental ein Downloader/Orchestrator ist (kein reiner API-Client) — eine Extraktion wäre kein einfacher „Verschieben"-Schritt wie bei Navidrome, sondern müsste zuerst die Verantwortlichkeiten dokumentieren (Regel 19). |

Keine weiteren `requests`/`httpx`/`aiohttp`-Direktaufrufe außerhalb `services/clients/` gefunden (alle anderen externen Aufrufe laufen bereits über `GeniusClient`/`LastFMClient`/`MusicBrainzClient`/`NavidromeAPI`).

### C — Subprocess-/lokale Infrastruktur-Wrapper

Grep nach `subprocess.*`/`Popen`/`create_subprocess` in `services/`, `utils/`, `handlers/`:

| Fund | Zeilen | Bewertung |
|---|---|---|
| `handlers/admin/bot_restart_handler.py::_trigger_restart()` | 157–195 (Methode), `subprocess.run(["sudo", "systemctl", "restart", ...])` bei 170 | **Direktes Analogon zum Vor-ARCH-009-Muster.** Kleine (201 Zeilen), private, synchrone Methode auf einer sonst reinen Telegram-Handler-Klasse (`show_restart_confirm`/`execute_restart`/`cancel_restart` sind alle `async def` mit `update`/`context`). Genau die Konstellation, die `utils/navidrome_scan_trigger.py` bereits einmal gelöst hat. |
| `handlers/test_menu_handler.py` (7 Stellen, u. a. `_execute_test_run()`, `show_coverage_report()`, `_run_test_type()`) | 128, 149, 176, 433, 445, 494, 663 | Subprocess-Ausführung (`pytest`, `coverage`) vermischt mit Output-Parsing (`_parse_pytest_output()`) und Telegram-Präsentation (`_show_test_results()`, `show_test_details()`) in einer 685-Zeilen-Klasse — Verantwortlichkeitsvermischung, aber größer/komplexer als der Navidrome-Fall (3 statt 2 Verantwortlichkeiten). |
| `utils/navidrome_scan_trigger.py`, `utils/audio_enhancer.py` | — | Referenz/Präzedenzfälle, bereits korrekt in `utils/` (kein Fund, sondern Vergleichsbasis). |

### D — DI-Probleme

Grep nach modulweiten `get_config()`-Zuweisungen und `@lru_cache` in `services/`, `utils/`, `handlers/`:

| Fund | Bewertung |
|---|---|
| `services/clients/navidrome_api.py::_get_navidrome_config()` (`@lru_cache`, Wrapper um `get_config()`) | Kein neuer Fund — bereits in ARCH-009 Phase 7 bewusst so entschieden (Default `NavidromeAPI()` ohne Argumente nutzt weiterhin die globale Config-Singleton, dokumentiert im Phase-7-Analysedokument, inkl. des dort gefundenen und gefixten Tests). |
| `utils/artist_map.py::_normalize_key()`, `utils/genre_map.py::get_main_genre()`/`normalize_genre_name()` (`@lru_cache` auf Instanzmethoden) | Reines Performance-Caching für Normalisierungsfunktionen (Mapping-Fachlogik), keine Konfigurations-/Singleton-Kopplung, keine konkrete architektonische Auswirkung. Kein Fund im Sinne dieses Audits. |
| `utils/navidrome_scan_trigger.py::_get_scan_config()` | Bereits Gegenstand der ARCH-009-Folgeanalyse (bewusst kein Import aus `services.clients.navidrome_api`, um keinen Zyklus zu erzeugen). Kein neuer Fund. |

Keine neuen, bisher nicht bewerteten DI-Probleme gefunden. Es wurde bewusst **nicht** jede `@lru_cache`-Verwendung als Problem gewertet (Vorgabe aus Abschnitt 3.D des Auftrags).

### E — Verantwortlichkeitsvermischung (große Module)

Zeilen-Ranking der größten Module in `services/`, `handlers/`, `klassen/`, `utils/`:

```text
2506  handlers/enhanced_error_handler.py
1957  handlers/menu/rich_menu_system.py
1753  handlers/enhanced_logger_menu_handler.py
1298  handlers/menu/rich_menu_handler.py
1219  utils/artist_map.py
1149  handlers/navidrome_menu_handler.py
1122  utils/genre_map.py
 977  klassen/download_handler.py
 942  services/downloader/spotify_downloader.py
 870  handlers/enhanced_status_handler.py
 848  handlers/duplicate_handler.py
 793  handlers/admin/user_management_handler.py
 685  handlers/test_menu_handler.py
```

Die vier größten Module liegen alle in `handlers/` und sind bereits in `CLAUDE.md` Abschnitt 19 als bekannte, bewusst nicht automatisch zu zerlegende Orchestratoren benannt (`RichMenuHandler`, `RichMenuSystem`) bzw. strukturell erwartete Präsentationsklassen. Kein neuer Fund. `spotify_downloader.py` (B) und `test_menu_handler.py` (C) sind die einzigen Module, die mehrere der in Abschnitt 3 gelisteten Kategorien (externe Kommunikation/Subprocess + Orchestrierung + Präsentation) tatsächlich gleichzeitig vermischen.

---

## 4. Priorisierung

| Priorität | Modul | Problem | Architekturprinzip | Risiko | Aufwand | Empfehlung |
|---|---|---|---|---|---|---|
| P-1 | `handlers/admin/bot_restart_handler.py::_trigger_restart()` | `subprocess.run()` (lokaler Infrastruktur-Aufruf) liegt in einer sonst reinen Telegram-Handler-Klasse | Trennung lokaler Infrastruktur von Präsentation (identisches Prinzip wie ARCH-009) | niedrig (1 Consumer laut Grep: `rich_menu_system.py`/`rich_menu_handler.py`, 1 Testdatei `tests/test_bot_restart_handler.py` bereits vorhanden) | klein (eine private Methode, ein klarer Präzedenzfall `utils/navidrome_scan_trigger.py`) | **untersuchen** |
| P-2 | `handlers/test_menu_handler.py` | Subprocess (`pytest`/`coverage`) + Output-Parsing + Telegram-Präsentation in einer 685-Zeilen-Klasse | Verantwortlichkeitstrennung (3 statt 2 Verantwortlichkeiten, höherer Aufwand als P-1) | mittel (bereits als praktisch wirkungslos dokumentiert — `docs/archive/MusicBot_ENGINEERING_BASELINE.md` TEST-019: `tests/unit/`/`tests/integration/`/`tests/performance/` existieren nicht — Architekturentscheidung hängt an einer separaten, ungeklärten Feature-Frage) | mittel | beobachten |
| P-2 | `services/downloader/spotify_downloader.py` | 6 direkte HTTP-Aufrufe (oEmbed/Embed-Scraping/Cover/RSS/Redirect-Resolution) vermischt mit `yt-dlp`-Download-Orchestrierung | externe Integrationsadapter vs. Orchestrierung | mittel (942 Zeilen, viele Aufrufer/Tests — `tests/test_spotify_downloader.py` existiert bereits) | groß (keine 1:1-Verschiebung möglich, echte Extraktionsarbeit nötig) | beobachten |
| P-3 | `utils/artist_map.py`/`utils/genre_map.py` (`@lru_cache` auf Instanzmethoden) | rein stilistisch, keine architektonische Auswirkung | — | — | — | kein Handlungsbedarf |
| P-3 | `klassen/download_handler.py` (Telegram-Import) | erwartungsgemäße Präsentations-/Orchestrierungskopplung laut `CLAUDE.md` Abschnitt 4 | — | — | — | kein Handlungsbedarf |
| P-3 | große `handlers/`-Module (`enhanced_error_handler.py`, `rich_menu_system.py`, ...) | bereits dokumentierte, bewusst nicht automatisch zu zerlegende Orchestratoren (Regel 19) | — | — | — | kein Handlungsbedarf |

---

## 5. Nächster Architektur-Kandidat

**P-1 — `handlers/admin/bot_restart_handler.py::_trigger_restart()` nach `utils/` extrahieren.**

**Warum dieser Kandidat:**
- Strukturell nahezu identisch zum bereits zweimal bestätigten Muster (`utils/navidrome_scan_trigger.py` ↔ `utils/audio_enhancer.py`): synchroner `subprocess.run()`-Aufruf mit Timeout, Fehlerbehandlung, Logging — keine Telegram-Objekte in der Methode selbst.
- Kleinster mögliche Schritt: eine einzelne private Methode (`_trigger_restart()`, ca. 40 Zeilen) auf einer 201-Zeilen-Klasse, kein größerer Refactor nötig.

**Konkrete Architekturverletzung:** `BotRestartHandler` ist als Telegram-Handler klassifiziert (`show_restart_confirm`/`execute_restart`/`cancel_restart` sind alle `async def(update, context)`), enthält aber mit `_trigger_restart()` einen reinen, telegramfreien Infrastruktur-Aufruf (`subprocess.run(["sudo", "systemctl", "restart", ...])`).

**Abhängigkeiten:** `_trigger_restart()` liest nur `self.service_name` (aus `__init__`) und schreibt nur ins `self.logger`. Keine Telegram-Objekte, keine weiteren internen Abhängigkeiten.

**Consumer:** Einziger Instanziierungsort ist `handlers/menu/rich_menu_handler.py` (`self.restart_handler = BotRestartHandler(self.config, self.logger_factory)`), verdrahtet über `handlers/menu/rich_menu_system.py`. Kein weiterer Consumer im Repo gefunden.

**Risiko:** Niedrig — kleiner, isolierter, gut getesteter Baustein (`tests/test_bot_restart_handler.py` existiert bereits mit dediziertem Coverage laut `docs/archive/MusicBot_ENGINEERING_BASELINE.md` TEST-015, 12 Tests).

**Tests:** Vorhanden (`tests/test_bot_restart_handler.py`). Bei einer Extraktion müssten die dortigen `subprocess.run`-Patch-Ziele mit umgezogen werden — nach dem in ARCH-009 etablierten Muster idealerweise gleich auf das konsumierende Modul (`handlers.admin.bot_restart_handler.<NeueKlasse>.<Methode>`) statt auf das neue `utils/`-Modul, damit der Test robust gegenüber künftigen Verschiebungen bleibt.

**Ist zuerst eine Analyse nötig:** Ja — auch dieser kleine Schritt sollte, konsistent mit dem gesamten bisherigen Vorgehen dieser Session, zuerst als eigene kurze Analyse (Zielposition, genaue Schnittstelle, Consumer-Migration, Testanpassung) freigegeben werden, bevor Code geändert wird.

**Mögliche Zielarchitektur:** `utils/bot_restart_trigger.py` (Name offen, Analogie zu `NavidromeScanTrigger`), reiner Subprocess-Wrapper mit strukturiertem Ergebnis (`@dataclass`, analog `ScanRunResult`), `BotRestartHandler` bleibt reine Telegram-Präsentationsschicht und ruft den neuen Wrapper auf.

**Ausdrücklich zurückgestellt, kein P-1:** `handlers/test_menu_handler.py` (P-2, höherer Aufwand + ungeklärte Vorfrage zum Testmenü-Feature selbst) und `services/downloader/spotify_downloader.py` (P-2, keine einfache 1:1-Verschiebung möglich).

**Noch keine Umsetzung.** Dies ist ein Entscheidungsgate — der nächste Schritt (Analyse oder Umsetzung von P-1) wird separat beauftragt.
