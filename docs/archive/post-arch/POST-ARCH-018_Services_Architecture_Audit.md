# POST-ARCH-018 Services / Architecture Audit

**Datum:** 2026-08-25
**Typ:** Reine Verifikation (keine Produktions-/Test-/Mapping-Änderungen)
**Basis:** `arch-018/phase2-duplicate-kern-extraction` (Commit `fa8f718`), PR #47 (offen, `base=main`, nicht gemergt)
**Vorgänger:** `docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md` (Phase 1 + Phase 2)

---

## 1. Ausgangsstand

`main` steht auf `bbcb5b5` (Merge PR #46, ARCH-019 Phase 1). ARCH-018 Phase 2 wurde auf dem Branch
`arch-018/phase2-duplicate-kern-extraction` umgesetzt, committet (`fa8f718`) und als PR #47
(`base=main`) zur Prüfung eingestellt — **noch nicht gemergt**. Dieser Audit verifiziert den Stand
des PR-Branches (`git checkout arch-018/phase2-duplicate-kern-extraction`), da dieser den tatsächlich
zu bewertenden Code darstellt. Nach Abschluss wurde zu `main` zurückgewechselt; keine Merge-Aktion
durchgeführt.

Nutzereigene Working-Tree-Dateien (`mapping/artist_genre.yaml`, `mapping/artist_overrides.json`,
12 gelöschte `.info.json` in `import/downloads/`) waren beim Branch-Wechsel hin und zurück
unverändert und wurden zu keinem Zeitpunkt berührt.

---

## 2. ARCH-018-Verifikation

Direkte Lektüre der drei zentralen Dateien (nicht nur Dateinamen-Prüfung):

- **`services/duplicate/detector.py`** — `DuplicateDetector` enthält exakt den in Phase 1
  charakterisierten fachlichen Kern: `check_for_duplicates` (URL → Content → Parser →
  Library-Kaskade), `check_library_duplicate`, `register_download`, Normalisierungs-Helfer,
  Hashing, `get_statistics`/`cleanup_cache`/`invalidate_entry`. Keine Telegram-Importe, keine
  Präsentationslogik.
- **`services/duplicate/cache.py`** — `DuplicateCache` ist reine JSON-Persistenz (Laden/Speichern
  der URL-/Content-Caches). Keine Telegram-Importe.
- **`handlers/duplicate_handler.py`** — `EnhancedDuplicateHandler` enthält nach der Extraktion
  **keine** verbliebene fachliche Duplicate-Detection-Logik mehr. Alle drei verbliebenen Methoden
  (`show_statistics_menu`, `show_clear_cache_confirm`, `execute_clear_cache`) sind reine
  Telegram-Präsentation (Menü-Text, `InlineKeyboardMarkup`, `edit_message_text`) und delegieren
  jede fachliche Operation an `self.detector` (`self.detector.get_statistics()`,
  `self.detector.duplicate_cache.url_cache_file`, etc.).

**Ergebnis:** Die in Phase 2 dokumentierte Trennung ist im Code tatsächlich vorhanden, nicht nur
behauptet.

---

## 3. `services/duplicate/`-Analyse

| Kriterium | Befund |
|---|---|
| Telegram-Abhängigkeit | 0 (verifiziert per Grep auf `telegram`, `Update`, `ContextTypes`, `InlineKeyboard`, `parse_mode`, `reply_*`, `edit_message*` — keine Treffer) |
| Externe Abhängigkeiten | `config.Config`, `logger.get_module_logger` (beide bestehende Cross-Cutting-Infrastruktur, keine neue Kopplung) |
| Utils-Abhängigkeiten | `utils.artist_map.ArtistNormalizer`, `utils.youtube_parser.parse_youtube_title` — beide bereits vor der Extraktion vom fachlichen Kern genutzt, unverändert |
| Klassen-Abhängigkeiten | 0 |
| Persistenz-Verantwortung | sauber getrennt: `DuplicateCache` (Datei-I/O) von `DuplicateDetector` (Entscheidungslogik) — `DuplicateDetector` hält `self.duplicate_cache` als Attribut, keine Vermischung |
| Zyklen | keine (`services/duplicate/detector.py` importiert `services.duplicate.cache`, `services.downloader.models` — keine Rückimporte in umgekehrter Richtung gefunden) |

**Bewertung:** `services/duplicate/` ist eine echte Services-Komponente nach dem etablierten Muster
von `services/statistik/` — keine bloße Dateiverschiebung mit unverändertem Charakter, sondern eine
Struktur mit klarer Verantwortungstrennung (Cache vs. Entscheidungslogik vs. — extern —
Präsentation).

---

## 4. Reverse-Edge-Verifikation

AST-basierter Scan (nicht Grep) über `services/`, `handlers/`, `klassen/`, `utils/`, `helfer/`,
`mapping/`, ausgeführt auf dem PR-Branch:

```
klassen → handlers:  0 Treffer   ✅ (Kernziel von ARCH-018 Phase 2 bestätigt)
services → handlers: 0 Treffer
services → klassen:  0 Treffer
```

`klassen/download_handler.py` importiert den Duplicate-Bezug jetzt ausschließlich aus
`services.duplicate.detector` (`from services.duplicate.detector import DuplicateDetector`) —
der vorherige Import `from handlers.duplicate_handler import EnhancedDuplicateHandler` ist
vollständig entfernt (verifiziert per Diff, siehe Abschnitt 10).

**Die seit ARCH-006/007 bekannte `klassen → handlers`-Reverse-Edge ist vollständig aufgelöst.**

---

## 5. Import-/Dependency-Audit (gesamt)

Vollständiger AST-Scan, alle Cross-Top-Level-Kanten:

```
handlers → helfer    (3)  — Markdown-Escaping, unverändert, legitim (Präsentationshilfe)
handlers → klassen   (1)  — rich_menu_handler.py importiert klassen.download_handler
handlers → services  (7)  — u.a. handlers/duplicate_handler.py → services.duplicate.{cache,detector}
handlers → utils     (2)  — Subprocess-/Shell-Trigger (Konvention laut CLAUDE.md §4)
klassen → services   (8)  — u.a. klassen/download_handler.py → services.duplicate.detector
klassen → utils      (2)
mapping → utils      (1)  — mapping/test_genre_map.py
services → utils     (27) — u.a. services/duplicate/detector.py → utils.artist_map, utils.youtube_parser
```

Keine Importzyklen gefunden. Keine neuen Schichtverletzungen.

Die einzige `handlers → klassen`-Kante (`rich_menu_handler.py` erstellt `DownloadHandler`) ist die
bereits aus früheren Audits bekannte, legitime Orchestrator-Rolle von `RichMenuHandler` — sie war
vor ARCH-018 vorhanden, ist von der Duplicate-Extraktion inhaltlich unberührt und wird hier nur der
Vollständigkeit halber mitgeführt, nicht neu bewertet.

**`services/duplicate/*` → Telegram: 0. `services/duplicate/*` → `handlers/*`: 0.**

---

## 6. Duplicate-Workflow (rekonstruiert)

```
klassen/download_handler.py::_check_and_handle_duplicate()
      ↓ self.duplicate_detector.check_for_duplicates(url=...)
services/duplicate/detector.py::DuplicateDetector.check_for_duplicates()
      ↓ Layer 1: self.duplicate_cache.check_url_duplicate(url)
      ↓ Layer 2: self.duplicate_cache.check_content_duplicate(artist, title)
      ↓ Layer 3: parse_youtube_title() + check_content_duplicate()
      ↓ Layer 4: self.check_library_duplicate() (Dateisystem-Scan)
services/duplicate/cache.py::DuplicateCache
      → JSON-Persistenz (url_duplicates.json / content_duplicates.json)
      ↓ Rückgabe (is_dup, entry, reason) an DownloadHandler
klassen/download_handler.py
      → fachliche Entscheidung (Download abbrechen/fortsetzen) bleibt hier
      → self.duplicate_detector.register_download(...) bei Erfolg

— unabhängig davon —

handlers/duplicate_handler.py::EnhancedDuplicateHandler (nur bei Admin-Menü-Interaktion)
      ↓ self.detector.get_statistics() / self.detector.duplicate_cache.*
      → Telegram-Darstellung (Menütext, InlineKeyboard) beginnt hier, nicht früher
```

Die fachliche Entscheidung fällt vollständig innerhalb von `DuplicateDetector`
(`services/duplicate/`). Der Handler trifft **keine** fachliche Entscheidung mehr — er liest nur
noch bereits berechnete Statistiken/Cache-Metadaten zur Anzeige aus. Keine unnötigen
Datentransformationen zwischen den Schichten (dieselben `DuplicateEntry`-Objekte/Dicts werden
durchgereicht). Dies deckt sich exakt mit der in ARCH-018 Phase 1 charakterisierten Zielstruktur
(Variante A).

---

## 7. Telegram-Entkopplung

Grep über `services/duplicate/*.py` auf: `telegram`, `Update`, `Context`, `reply_*`, `send_*`,
`edit_*`, `ParseMode`, Markdown/HTML, Inline-Keyboards, Callback-Daten.

**Ergebnis: 0 Treffer.** `services/duplicate/detector.py` importiert nur:
`hashlib, json, re, pathlib, typing, datetime, config, logger, utils.artist_map,
utils.youtube_parser, services.downloader.models, services.duplicate.cache`.
`services/duplicate/cache.py` importiert nur:
`hashlib, json, pathlib, typing, datetime, logger, services.downloader.models, urllib.parse`.

---

## 8. Latenter Alt-Befund (`find_duplicates`/`clear_duplicate_cache`)

Beide Funktionen existieren nach Phase 2 **unverändert als tote Module-Level-Funktionen** in
`handlers/duplicate_handler.py` (Zeilen 240–314, gleiche Datei wie vorher, keine Verschiebung).

- **Produktive Aufrufer:** 0 (verifiziert per repo-weitem Grep — einzige Treffer sind die
  Definitionen selbst und zwei Docstring-Verweise "Ersetzt die Logik von …").
- **Test-Aufrufer:** 0.
- **Bug weiterhin vorhanden:** `EnhancedDuplicateHandler()._get_default_config()` — Aufruf ohne
  Argumente, während der Konstruktor jetzt `config` und `detector` als Pflichtparameter verlangt.
  Vor Phase 2 fehlte 1 Pflichtargument (`config`), jetzt fehlen 2 (`config`, `detector`) — same
  Bug-Kategorie (`TypeError`, unerreichbar da 0 Aufrufer), keine fachliche Änderung, nur eine durch
  die Signaturänderung des Konstruktors verschobene Fehlerursache.
- Die Klassifikation "bewusst nicht behoben" aus Phase 1/2 bleibt **weiterhin korrekt**.

Zusätzlich in `services/duplicate/cache.py:31` verifiziert: `Path(DUPLICATE_CACHE_DIR)` referenziert
einen nirgends importierten/definierten Namen — identisch zum vor der Extraktion bestehenden,
bereits dokumentierten latenten Bug, unverändert mitverschoben (unerreichbar, da `cache_dir` in der
Praxis stets einen truthy Default via `getattr(config, "DUPLICATE_CACHE_DIR", "duplicate_cache")`
erhält).

---

## 9. Test-/Regressionsergebnis

Gezielt (Duplicate/Download/Handler):

```
tests/test_duplicate_handler.py
tests/test_metadata_processor_happy_path.py
tests/test_rich_menu_handler.py
→ 52 passed
```

Vollständige Regression:

```
pytest tests/ -q
→ 1114 passed, 15 failed
```

**Identisch zur ARCH-018-Baseline** (1114 passed / 15 bekannte Vorbestandsfehler). Die 15
Fehlschläge sind exakt dieselben wie zuvor bekannt: `test_auto_learn.py` (5), `test_metadata_modules.py`
(3, davon 3 Subtests), `test_suite.py` (4, RichMenuSystem/Menu-Integration, bekannt asyncio-markbezogen).
Keine neuen Fehlschläge, keine still entfernten Tests, keine Testkosmetik als versteckte Regression.

---

## 10. Diff-/Scope-Audit

`git diff main HEAD --name-only` (committeter PR-Diff, Working-Tree-Änderungen bewusst
ausgeklammert):

```
docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md
handlers/duplicate_handler.py
handlers/menu/rich_menu_handler.py
klassen/download_handler.py
services/duplicate/__init__.py
services/duplicate/cache.py
services/duplicate/detector.py
tests/test_duplicate_handler.py
tests/test_metadata_processor_happy_path.py
tests/test_rich_menu_handler.py
```

10 Dateien — exakt der in ARCH-018 Phase 2 angegebene Scope. **Keine YAML-/Mapping-Änderungen im
PR selbst.** (Die separat sichtbaren `mapping/artist_genre.yaml`/`mapping/artist_overrides.json`-
Diffs im Working Tree sind nutzereigene, unversionierte Änderungen außerhalb des PR und wurden zu
keinem Zeitpunkt berührt.) Wiring-Diff (`rich_menu_handler.py`, `download_handler.py`) manuell
gegengelesen — Attribut-Umbenennung (`duplicate_handler`→`duplicate_detector`) konsistent an allen
Call-Sites durchgezogen, `set_duplicate_handler()` bewusst unverändert (verbindet weiterhin korrekt
die Präsentationsschicht mit `menu_system`).

---

## 11. ARCH-013–017-Revalidierung

Gezielt (nicht erneut vollständig analysiert):

```
tests/test_genre_canonical_idempotency_characterization.py
tests/test_genre_specificity_characterization.py
tests/test_genre_canonical_case_acronym_characterization.py
→ 73 passed
```

115/115 kanonische Werte weiterhin idempotent, 0 instabile Werte (`New York Drill`,
`Aggro Deutschrap`, `NDW` eingeschlossen). ARCH-018 hat diese Logik nicht berührt — bestätigt.

---

## 12. Bekannte Folgepunkte (revalidiert, unverändert)

| Befund | Status |
|---|---|
| Genre-Client-Duplikation (`musicbrainz_client.py`/`lastfm_client.py`) | Weiterhin nur Kommentare zu ARCH-012-Entfernung, kein aktiver `determine_genre()`-Aufruf — **bestätigt unverändert**, kein realer Befund (siehe ARCH-019) |
| `mapping/test_genre_map.py` | Weiterhin 7/8 Fehlschläge, weiterhin außerhalb `tests/` und daher nicht in der Regression enthalten — **bestätigt unverändert, weiterhin offener P2-Befund** |
| `handlers/adapters/` | Weiterhin nur `__init__.py` — **bestätigt unverändert** |
| `GenreMapper`-Akronym-Liste | Weiterhin `EDM/R&B/UK/US/DJ/MC`, unverändert seit ARCH-016 Phase 2 — **bestätigt unverändert** |
| Last.fm-Duplikation in `cover_processor.py`, DI-Inkonsistenz `album_processor.py`, README Client-Reinheit, tote Imports | Keine dieser Dateien im ARCH-018-Diff enthalten — **keine Veränderung erwartet, nicht erneut vertieft geprüft** (außerhalb des heutigen Scopes) |

Keines dieser Themen wurde bearbeitet.

---

## 13. Neue Befunde

**Keine neuen Architekturbefunde.** Die beiden in Abschnitt 8 genannten latenten Bugs
(`find_duplicates`/`clear_duplicate_cache`-Konstruktoraufruf, `DUPLICATE_CACHE_DIR`-NameError in
`cache.py`) sind **keine neuen** Befunde — beide waren bereits vor ARCH-018 Phase 2 dokumentiert und
wurden bewusst unverändert mitgeführt (siehe ARCH-018-Doku, Abschnitt 6/14).

---

## 14. Priorisierung

Keine neuen P0/P1-Befunde. Bekannte P2-Punkte (Abschnitt 12) bleiben in ihrer bisherigen Priorität.

---

## 15. Empfehlung

**Ergebnis A: ARCH-018 vollständig korrekt umgesetzt, Architektur verbessert.**

- Fachlicher Kern liegt nachweislich in `services/duplicate/`, telegram-frei, per Dependency
  Injection genutzt.
- `EnhancedDuplicateHandler` ist nachweislich reine Präsentations-/Delegationsschicht.
- `klassen → handlers`-Reverse-Edge nachweislich vollständig aufgelöst (0 Treffer, AST-verifiziert).
- Keine neue Kopplung, keine Zyklen, keine Telegram-Lecks in `services/duplicate/`.
- Regression exakt auf Baseline (1114/15), keine verdeckten Regressionen.
- Diff exakt im angegebenen Scope, keine Mapping-Nebenwirkungen.

**Kein weiterer unmittelbarer Duplicate-/Services-Befund**, der eine neue Phase rechtfertigt. Die
einzigen offenen Punkte sind die bereits bekannten, bewusst nicht behobenen P2-Befunde aus Abschnitt
12 — keiner davon wird durch ARCH-018 verschärft oder neu begründet.

Falls zukünftig gewünscht, käme als möglicher, aber nicht empfohlener nächster Schritt eine
Characterization-Phase für `mapping/test_genre_map.py` (veraltete API-Erwartung) in Frage — dies ist
jedoch ausdrücklich nur als Erwähnung, nicht als Empfehlung zu verstehen; PR #47 bleibt unabhängig
davon zum Merge bereit, sobald der Nutzer dies freigibt.

---

## 16. Entscheidungsgate

**STOPP. Keine automatische Folgephase. PR #47 nicht gemergt, keine Produktions-/Test-/Mapping-
Änderungen in diesem Audit vorgenommen. Wartet auf ausdrückliche Nutzerentscheidung** (Merge von
PR #47 und/oder nächste Phase).
