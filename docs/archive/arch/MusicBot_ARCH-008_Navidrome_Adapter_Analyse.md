# ARCH-008 — `api/navidrome_api.py`: Ist es ein reiner Integrationsadapter?

Reine Analyse, keine Codeänderung. Folgeuntersuchung aus ARCH-006
Abschnitt 3 (dort nur benannt, hier bewertet). Vier Kernfragen des
Nutzers werden beantwortet.

---

## 1. Ist `api/navidrome_api.py` tatsächlich ein reiner externer Integrationsadapter?

**Nein.** Die Klasse `NavidromeAPI` (614 Zeilen) vermischt drei
strukturell unterschiedliche Verantwortlichkeiten:

### 1.1 Reine API-Kommunikation (passt zur `services/clients/`-Konvention)

`make_request()`, `_build_url()`, `check_connection()`,
`get_scan_status()`, `get_full_server_info()`, `get_artists()`,
`get_now_playing()`, `search()` — echte Subsonic/HTTP-API-Kommunikation
gegen den Navidrome-Server.

### 1.2 Telegram-Präsentationslogik (widerspricht der Konvention)

```python
from telegram.constants import ParseMode
```

Drei Methoden bauen MarkdownV2-formatierten Text speziell für Telegram:
`format_full_status_message()`, `format_rescan_status_message()`,
`format_web_interface_url_message()` — nutzen `escape_md_v2()`
(`helfer/markdown_helfer.py`) und `EMOJI` (`emoji.py`). `test_api()`
vermischt API-Aufruf und Telegram-Text-Bau in einer Methode.

Das ist exakt dasselbe Kopplungsmuster, das in ARCH-007/P-2 gerade aus
`services/downloader/utils/{download_result_reporter,progress_tracker}.py`
entfernt wurde — hier besteht es aber bereits länger, unentdeckt, in
`api/`.

### 1.3 Lokale Subprocess-Ausführung (dritte, wesensfremde Verantwortlichkeit)

`execute_scan()` startet einen Shell-Befehl via
`asyncio.create_subprocess_shell(command_to_execute, ...)` — System-Prozess-
Steuerung ist konzeptionell weder API-Adapter noch Präsentationslogik.

### 1.4 Strukturelle Unterschiede zu den P-11-Kandidaten

`GeniusClient`/`LastFMClient`/`MusicBrainzClient` (P-11) sind Instanzen
mit `__init__(self, logger=...)`, echte Dependency Injection, Config wird
lazy beim Konstruieren gelesen. `NavidromeAPI` dagegen:

- reine `@classmethod`/`@staticmethod`-Klasse, **keine Instanz, kein DI**
- `_auth_params` ist ein Klassenattribut, dessen Wert beim **Modul-Import**
  ausgewertet wird (`_get_navidrome_config()` läuft zur
  Klassendefinitionszeit, nicht lazy) — ein Modul-Level-Seiteneffekt, den
  keiner der P-11-Kandidaten hat

---

## 2. Consumer

```
grep -rl "from api.navidrome_api import" --include="*.py" .
```

| Consumer | Art des Zugriffs | Schicht |
|---|---|---|
| `handlers/navidrome_menu_handler.py` | 10+ direkte statische Aufrufe (`NavidromeAPI.make_request/get_artists/search/...`) | `handlers/` |
| `handlers/menu/rich_menu_handler.py` | `NavidromeAPI.execute_scan()` | `handlers/` |
| `services/statistik_service.py` (über `services/statistik/play_history_poller.py`) | bereits per DI injizierbar (`navidrome_api=None`-Parameter, P-6/P-8-Muster) | `services/` |

**Wichtiger Unterschied zu P-11:** die Mehrheit der Nutzung kommt aus
`handlers/`, nicht aus `services/`. Genius/LastFM/MusicBrainz wurden
ausschließlich von `services/`-internem Code (`enhanced_metadata_processor.py`/
`album_processor.py`) konsumiert — bei `NavidromeAPI` ist es umgekehrt: der
einzige `services/`-Consumer ist bereits sauber entkoppelt (DI), während
die Presentation-Schicht (`handlers/`) direkt und wiederholt gegen die
statischen Methoden programmiert.

3 Testdateien: `tests/test_navidrome_api_characterization.py` (18 Tests),
`tests/test_navidrome_api_logging.py` (1 Test),
`tests/test_navidrome_api_timeout.py` (3 Tests) — 22 Tests insgesamt, gute
Ausgangsbasis für eine künftige Entflechtung.

---

## 3. Weitere `api/`-Abhängigkeiten

Keine. `api/` enthält ausschließlich `navidrome_api.py` (614 Zeilen) und
eine leere `__init__.py`. Kein weiteres Modul in diesem Verzeichnis.

---

## 4. Welche Zielposition wäre fachlich korrekt?

**Keine reine 1:1-Verschiebung nach `services/clients/navidrome_api.py`.**
Das würde die Telegram-Kopplung (Abschnitt 1.2) und die Subprocess-Logik
(Abschnitt 1.3) direkt mit in `services/clients/` importieren — im
Widerspruch zur durch P-11 etablierten Regel: „`services/clients/`
enthält ausschließlich externe Integrationsadapter. Fachliche Logik
bleibt außerhalb der Clients.“ Eine unreflektierte Verschiebung würde nur
die Datei umsortieren, ohne die eigentliche Vermischung zu beheben — das
verfehlt den Zweck der Konvention.

**Fachlich richtiger Weg (zweistufig, analog zum P-2-Muster):**

1. Verantwortlichkeiten trennen:
   - reiner API-Adapter (`make_request`, `check_connection`,
     `get_scan_status`, `get_full_server_info`, `get_artists`,
     `get_now_playing`, `search`, `execute_scan()`s Subsonic-Teil, falls
     zutreffend) bleibt als Klasse/Modul
   - Telegram-MarkdownV2-Formatierung (`format_*_message()`) wandert zu
     `handlers/` (den tatsächlichen Konsumenten, die die Nachricht
     versenden) — passt zum bereits in P-2 etablierten Prinzip: `services/`
     bzw. Adapter-Schicht liefert nur Daten, `handlers/` baut/versendet
     Telegram-Text
   - Subprocess-Steuerung (`execute_scan()`) separat bewerten — bleibt sie
     Teil des Adapters (Navidrome-Scan ist funktional eng an die API
     gekoppelt) oder wandert sie ebenfalls woanders hin?
2. Erst danach: den entflochtenen, reinen Adapter-Teil nach
   `services/clients/` verschieben — und dabei ggf. auch die
   strukturelle Diskrepanz (Abschnitt 1.4: statische Klasse ohne DI vs.
   Instanz-Konvention der übrigen drei Clients) adressieren oder bewusst
   als Ausnahme dokumentieren.

Das ist eine wesentlich größere Aufgabe als P-11 (dort waren die drei
Kandidaten bereits sauber getrennt, reine Verschiebung + Import-Update
genügten). Hier ist zusätzlich echte Entflechtungsarbeit nötig, bevor
eine Verschiebung inhaltlich sinnvoll ist.

---

## 5. Zusammenfassung

| Frage | Antwort |
|---|---|
| Reiner Integrationsadapter? | Nein — vermischt API-Kommunikation, Telegram-Formatierung, Subprocess-Ausführung |
| Consumer | `handlers/navidrome_menu_handler.py`, `handlers/menu/rich_menu_handler.py` (direkt, statisch), `services/statistik_service.py` (bereits DI-fähig) |
| Weitere `api/`-Abhängigkeiten | Keine — nur diese eine Datei |
| Zielposition | Nicht sofort `services/clients/` — erst Entflechtung (Telegram-Text raus, Subprocess-Frage klären), dann Verschiebung des reinen Adapter-Rests |

Keine Umsetzung in diesem Schritt. Eigener, unabhängiger Architektur-
Kandidat für eine spätere, separate Entscheidung.
