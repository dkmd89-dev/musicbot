# MusicBot ARCH-018 — Duplicate Handler Characterization

**Status:** Phase 1 (Characterization) abgeschlossen. Phase 2 (Extraktion
gemäß Variante A) abgeschlossen — fachlicher Kern nach `services/duplicate/`
verschoben, `klassen → handlers`-Reverse-Edge vollständig aufgelöst.

---

## 1. Ausgangslage

Der POST-SERVICES-Audit (`docs/archive/POST-SERVICES_PROJECT-WIDE_ARCHITECTURE_AUDIT.md`,
Abschnitt G.2) hatte `handlers/duplicate_handler.py` als P1-Befund
markiert: Vermischung von P0-Duplicate-Detection-Business-Logik mit
Telegram-Präsentation. Frühere Audits (ARCH-006/007, POST-ARCH-010/011,
POST-DUPLICATEENTRY) hatten ausschließlich die `DuplicateEntry`-
Dataclass und deren Import-Kante untersucht (inzwischen erfolgreich
nach `services/downloader/models.py` migriert, PR #23) — nie die
eigentliche Duplicate-Detection-Logik selbst. Diese Phase schließt
diese Lücke.

Die bekannte `klassen → handlers`-Kante
(`download_handler.py → duplicate_handler.py`) war bisher als
"Orchestrator-Sonderrolle" bewertet, ohne dass genau untersucht wurde,
**welchen Teil** von `duplicate_handler.py` der Orchestrator tatsächlich
benötigt.

---

## 2. Datei-/Verantwortungsanalyse

`handlers/duplicate_handler.py` (834 Zeilen) enthält vier strukturell
unterschiedliche Bereiche:

| Bereich | Zeilen | Klasse/Funktion | Verantwortung |
|---|---|---|---|
| Persistenz-Cache | 28–272 | `DuplicateCache` | Laden/Speichern von URL-/Content-Hash-Caches als JSON, Hashing, Cache-Cleanup |
| Duplicate-Detection-Kern | 275–580 | `EnhancedDuplicateHandler` (Nicht-`async`-Methoden) | Duplicate Detection, Vergleichs-/Matching-Logik, Datenzugriff, Statistik |
| Telegram-Präsentation | 582–759 | `EnhancedDuplicateHandler` (3 `async`-Methoden) | Menü-/Statistik-Anzeige, Bestätigungsdialog, Cache-Leeren-UI |
| Legacy-Kompatibilitätsfunktionen | 762–835 | `find_duplicates`, `clear_duplicate_cache` (Modul-Ebene) | Eigenständige Telegram-Command-Handler, redundant zu den `async`-Methoden oben |

### Klassifikation nach tatsächlicher Verantwortung (nicht nach Dateiname)

| Funktion | Duplicate Detection | Datenzugriff | Matching | Scoring | Persistenz | Orchestrierung | Telegram-Präsentation | Telegram-API | Fehlerbehandlung | Infrastruktur |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `DuplicateCache.__init__`/`_load_*`/`_save_caches` | | ✓ | | | ✓ | | | | ✓ | ✓ |
| `DuplicateCache.get_url_hash`/`get_content_hash` | | | ✓ | | | | | | | ✓ |
| `DuplicateCache.add_entry` | | ✓ | | | ✓ | | | | | |
| `DuplicateCache.check_url_duplicate`/`check_content_duplicate` | ✓ | ✓ | ✓ | | | | | | | |
| `DuplicateCache._normalize_url_for_cache` | | | ✓ | | | | | | ✓ | |
| `DuplicateCache.cleanup_old_entries` | | | | | ✓ | | | | | |
| `EnhancedDuplicateHandler.check_for_duplicates` | ✓ | ✓ | ✓ | | | ✓ (4-stufiger Fallback) | | | | |
| `EnhancedDuplicateHandler.check_library_duplicate` | ✓ | ✓ | ✓ | | | | | | ✓ | ✓ (Dateisystem-Scan) |
| `EnhancedDuplicateHandler.register_download` | | | | | ✓ | | | | | |
| `_normalize_artist_for_comparison`/`_clean_title_for_comparison` | | | ✓ | | | | | | | |
| `_create_metadata_hash`/`_create_file_hash` | | | | | | | | | | ✓ (Hashing) |
| `get_statistics`/`cleanup_cache`/`invalidate_entry` | | ✓ | | ✓ (Rate-Berechnung) | ✓ | | | | | |
| `show_statistics_menu` | | | | | | | ✓ | ✓ | ✓ | |
| `show_clear_cache_confirm` | | | | | | | ✓ | ✓ | | |
| `execute_clear_cache` | | | | | ✓ (Cache leeren) | | ✓ | ✓ | ✓ | |
| `find_duplicates`/`clear_duplicate_cache` (Modul-Ebene) | | | | | | ✓ (Instanziiert Handler) | ✓ | ✓ | ✓ | |

**Keine der Verantwortungen wurde vorausgesetzt** — die Tabelle beruht
auf tatsächlichem Codeverhalten (Imports, aufgerufene Objekte, Rückgabewerte).

---

## 3. Tatsächlicher Datenfluss

### Pfad A — Business-Logik (Konsument: `klassen/download_handler.py`)

```text
url, raw_artist, raw_title, track_metadata (Python-Primitiven)
    ↓
EnhancedDuplicateHandler.check_for_duplicates()
    ↓ Stufe 1: DuplicateCache.check_url_duplicate() [URL-Hash-Vergleich]
    ↓ Stufe 2: _normalize_artist_for_comparison() + _clean_title_for_comparison()
    ↓          → DuplicateCache.check_content_duplicate() [Content-Hash-Vergleich]
    ↓ Stufe 3: parse_youtube_title() (utils/youtube_parser.py)
    ↓          → dieselbe Normalisierung → DuplicateCache.check_content_duplicate()
    ↓ Stufe 4: check_library_duplicate() [Dateisystem-Scan in LIBRARY_DIR]
    ↓
Tuple[bool, Optional[DuplicateEntry], str]  ("url"/"content"/"parsed_content"/"library"/"none")
    ↓
klassen/download_handler.py entscheidet: Download abbrechen oder fortsetzen
```

Kein Telegram-Objekt, keine Präsentationslogik in diesem Pfad.
`register_download()` (separater Aufruf nach erfolgreichem Download,
`download_handler.py:585`) schreibt den `DuplicateEntry` in den Cache.

### Pfad B — Telegram-Präsentation (Konsument: `handlers/menu/rich_menu_system.py` über `rich_menu_handler.py`)

```text
Telegram CallbackQuery (Update, ContextTypes)
    ↓
RichMenuSystem (Callback-Routing, Zeilen 1612–1632)
    ↓
EnhancedDuplicateHandler.show_statistics_menu() /
    .show_clear_cache_confirm() / .execute_clear_cache()
    ↓ ruft INTERN dieselbe get_statistics()/cleanup-Logik wie Pfad A
    ↓
Markdown-formatierter Text + InlineKeyboardMarkup
    ↓
query.edit_message_text(...)  [Telegram-API-Aufruf]
```

**Beide Pfade laufen über dieselbe, EINE Instanz** von
`EnhancedDuplicateHandler` (siehe Abschnitt 4) — Pfad B liest lediglich
den internen Zustand (`self.stats`, `self.duplicate_cache`), den Pfad A
über `check_for_duplicates()`/`register_download()` verändert.

### Pfad C — Legacy-Kompatibilitätsfunktionen (`find_duplicates`, `clear_duplicate_cache`)

```text
Telegram Update/Context
    ↓
find_duplicates() / clear_duplicate_cache()  [Modul-Ebene, NICHT Methode]
    ↓ instanziiert eine EIGENE, neue EnhancedDuplicateHandler-Instanz
    ↓   (config aus context.bot_data.get("config") ODER
    ↓    EnhancedDuplicateHandler()._get_default_config() — LATENTER BUG,
    ↓    siehe Abschnitt 7)
    ↓
formatierter Text
    ↓
update.message.reply_text(...)
```

Dieser dritte Pfad ist **vollständig unabhängig** von den Instanzen aus
Pfad A/B (eigene `EnhancedDuplicateHandler`-Instanz, eigener Cache-Zustand)
— und wird nachweislich nie erreicht (siehe Abschnitt 4).

---

## 4. Aufrufer/Verbraucher

Repo-weit ermittelt (Grep + manuelle Aufrufstellen-Prüfung, keine
dynamischen/verdeckten Referenzen gefunden):

| Symbol | Aufrufer | Kontext | Rolle |
|---|---|---|---|
| `EnhancedDuplicateHandler(...)` (Instanziierung) | `handlers/menu/rich_menu_handler.py:241` | `RichMenuHandler.__init__`, EINZIGE produktive Instanziierung im Live-Betrieb | Erzeugt die geteilte Instanz |
| `EnhancedDuplicateHandler.check_for_duplicates` / `.register_download` | `klassen/download_handler.py:335,585` | erhält die Instanz per Konstruktor-Injection (`duplicate_handler: EnhancedDuplicateHandler`, Pflichtparameter) | **ausschließlich Business-Logik-Aufrufe** |
| `EnhancedDuplicateHandler.show_statistics_menu` / `.show_clear_cache_confirm` / `.execute_clear_cache` | `handlers/menu/rich_menu_system.py:1622,1627,1632` | erhält dieselbe Instanz per `set_duplicate_handler()` von `rich_menu_handler.py` | **ausschließlich Präsentations-Aufrufe** |
| `find_duplicates`, `clear_duplicate_cache` (Modul-Ebene) | — | **0 Treffer** repo-weit außerhalb der eigenen Definition | **toter Code** (nicht als Telegram-`CommandHandler` registriert, siehe Abschnitt 7) |
| `DuplicateCache` (direkt) | nur `EnhancedDuplicateHandler.__init__` | intern gekapselt | kein externer Direktkonsument |

**Bestätigter Injektionspfad:**
`rich_menu_handler.py:241` erzeugt die einzige Instanz →
`rich_menu_handler.py:850` reicht sie an `DownloadHandler` weiter →
`rich_menu_system.py` erhält sie über `set_duplicate_handler()`. **Eine
einzige Objektinstanz bedient beide architektonisch unterschiedlichen
Konsumenten-Rollen.**

Test-Aufrufer: `tests/test_duplicate_handler.py` (14 Tests, ausschließlich
Business-Logik), `tests/test_metadata_processor_happy_path.py`
(instanziiert `EnhancedDuplicateHandler` als Fixture, nutzt
`check_for_duplicates`/`register_download` im End-to-End-Pfad).

Keine dynamische/reflektive Nutzung (`getattr`, `importlib`, Registry-
Pattern) gefunden.

---

## 5. Telegram-Kopplung

Exakte Fundstellen von Telegram-spezifischem Code:

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
```

Verwendet **ausschließlich** in:

- `show_statistics_menu(update, context)` — `query = update.callback_query`, `InlineKeyboardMarkup`, `parse_mode="Markdown"`, `query.edit_message_text(...)`.
- `show_clear_cache_confirm(update, context)` — dieselben Muster, zusätzlich `callback_data`-Strings (`"dup:clear_cache_execute"`, `"menu:admin_duplicates"`).
- `execute_clear_cache(update, context)` — dieselben Muster.
- `find_duplicates(update, context)` / `clear_duplicate_cache(update, context)` — `update.message.reply_text(...)`.

**Nicht vorhanden** in `DuplicateCache` und in den nicht-`async`-Methoden
von `EnhancedDuplicateHandler` (`check_for_duplicates`,
`check_library_duplicate`, `register_download`,
`_normalize_artist_for_comparison`, `_clean_title_for_comparison`,
`_create_metadata_hash`, `_create_file_hash`, `get_statistics`,
`cleanup_cache`, `invalidate_entry`) — **keine einzige dieser Methoden
importiert oder berührt ein Telegram-Objekt.**

Die Trennung zwischen Telegram-Präsentation und fachlicher
Duplicate-Logik ist **im Code bereits klar erkennbar** (unterschiedliche
Methoden, `async` vs. synchron) — sie ist nur **nicht strukturell** (in
Form getrennter Dateien/Module) umgesetzt, sondern liegt als
Konvention innerhalb einer einzigen Klasse vor.

---

## 6. Fachlicher Kern

Der kleinstmögliche, vollständig Telegram-unabhängige fachliche Kern:

| Funktion | Input | Output | Seiteneffekte | Externe Abhängigkeiten | Telegram-Abhängigkeit | Persistenzabhängigkeit | Fachliche Entscheidungslogik |
|---|---|---|---|---|---|---|---|
| `DuplicateCache.check_url_duplicate` | `url: str` | `Optional[DuplicateEntry]` | erhöht `duplicate_count` im Treffer | keine | keine | liest `self.url_cache` (In-Memory, aus JSON geladen) | URL-Normalisierung (YouTube-ID-bewusst) |
| `DuplicateCache.check_content_duplicate` | `artist, title: str` | `Optional[DuplicateEntry]` | keine | keine | keine | liest `self.content_cache` | Hash-basierter Exact-Match nach Normalisierung |
| `EnhancedDuplicateHandler.check_for_duplicates` | `url, raw_artist, raw_title, track_metadata` | `Tuple[bool, Optional[DuplicateEntry], str]` | `self.stats`-Zähler, ggf. `duplicate_cache.add_entry()` (Library-Fallback-Zweig) | `utils.youtube_parser.parse_youtube_title`, `utils.artist_map.ArtistNormalizer` | keine | JSON-Cache + Dateisystem (Library-Scan) | **4-stufige Fallback-Kaskade** (URL → Content → Parsed-Content → Library) — die eigentliche fachliche Kernentscheidung des gesamten Moduls |
| `EnhancedDuplicateHandler.check_library_duplicate` | `artist, title: str` | `Optional[Path]` | keine | `re` (Titel-Bereinigung) | keine | Dateisystem (`LIBRARY_DIR`-Scan) | Fuzzy-Abgleich normalisierter Titel gegen Dateinamen |
| `EnhancedDuplicateHandler.register_download` | `url, artist, title, file_path, metadata` | `None` | schreibt `DuplicateEntry` in Cache, `self.stats` | Hashing (`hashlib`) | keine | JSON-Cache-Schreibzugriff | keine (reine Registrierung) |
| `_normalize_artist_for_comparison` / `_clean_title_for_comparison` | `str` | `str` | keine | `ArtistNormalizer` (optional) | keine | keine | Regelbasierte String-Normalisierung (Suffixe, Klammer-Inhalte, Feat.-Angaben) |

**Dieser Kern (`DuplicateCache` vollständig + die 8 oben genannten
`EnhancedDuplicateHandler`-Methoden) könnte unverändert außerhalb von
`handlers/` existieren** — er hat keine einzige Telegram-Abhängigkeit,
keine Abhängigkeit auf `Update`/`ContextTypes`, und wird bereits heute
von `klassen/download_handler.py` **ausschließlich** über diesen Kern
konsumiert.

Nicht Teil des Kerns: `get_statistics`, `cleanup_cache`,
`invalidate_entry` sind zwar ebenfalls Telegram-frei, werden aber
**ausschließlich von den Präsentationsmethoden** aufgerufen (`get_statistics`
z. B. von `show_statistics_menu`) — sie sind fachlich neutral
("Statistik-Berechnung"), aber ihr einziger heutiger Konsument ist die
Präsentationsschicht.

---

## 7. Dependency-/Layer-Audit

AST-/Import-basiert (nicht nur Grep) über den relevanten Bereich:

```text
handlers/duplicate_handler.py → services/downloader/models.py (DuplicateEntry)   [erwartete Richtung: handlers → services, unproblematisch]
handlers/duplicate_handler.py → utils/metadata_cache.py, utils/artist_map.py,
                                  utils/youtube_parser.py                          [erwartete Richtung: handlers → utils]
handlers/duplicate_handler.py → config.py, logger.py                              [Infrastruktur, unproblematisch]
handlers/duplicate_handler.py → klassen/*                                         [0 Treffer]
handlers/duplicate_handler.py → services/*  (sonstige)                            [0 Treffer außer DuplicateEntry]

klassen/download_handler.py → handlers/duplicate_handler.py (EnhancedDuplicateHandler)  [die bekannte Reverse-Edge]
services/* → handlers/*                                                            [0 Treffer, unverändert]
```

**Kein Importzyklus** gefunden (AST-DFS über `services/`+`handlers/`+`klassen/`,
identisch zum POST-SERVICES-Befund: 0 Zyklen).

### Präzisierung der `klassen → handlers`-Kante

Die frühere Bewertung ("Orchestrator-Sonderrolle, keine
Schichtverletzung", POST-DUPLICATEENTRY-Audit 3.6) bleibt in ihrer
Kernaussage korrekt: `klassen/download_handler.py` hat bewusst direkten
Telegram-Zugriff und ist die einzige Stelle, die Handler-Objekte,
Services und Telegram-I/O zusammenführt.

**Präzisierung durch diese Phase:** Der Import
`from handlers.duplicate_handler import EnhancedDuplicateHandler` in
`download_handler.py` wird **ausschließlich für den unter Abschnitt 6
identifizierten, Telegram-freien fachlichen Kern** verwendet
(`check_for_duplicates`, `register_download`) — **niemals** für die
Präsentationsmethoden. Der Orchestrator benötigt also nicht "einen
Handler", sondern konkret nur fachliche Duplicate-Detection-Logik, die
zufällig in einer `handlers/`-Datei liegt. Das ist ein Unterschied zur
bisherigen Einordnung: es handelt sich nicht um eine Orchestrator-
Kopplung an eine Präsentationskomponente, sondern um eine Kopplung an
Fachlogik, die strukturell in `handlers/` verortet ist. Dies ist genau
das Muster, das in CLAUDE.md §4 als unerwünscht beschrieben wird
("services/ → Fachliche... Orchestrierung" vs. "handlers/ →
Benutzerinteraktion / Telegram-Präsentation"), auch wenn der
*Aufrufer* hier `klassen/`, nicht `services/`, ist.

---

## 8. Test-/Coverage-Analyse

`tests/test_duplicate_handler.py` — **14 Tests**, alle fokussiert auf
den fachlichen Kern:

- `TestUrlDuplicate` (4 Tests): URL-Gleichheit, verschiedene
  YouTube-URL-Formen für dieselbe Video-ID, unterschiedliche IDs.
- `TestUrlHashConsistencyCache001Fix` (2 Tests): Hash-Konsistenz
  zwischen `get_url_hash()` und `check_url_duplicate()`,
  `invalidate_entry()` mit abweichender URL-Form.
- `TestContentDuplicate` (4 Tests): Artist/Titel-Gleichheit,
  Case/Whitespace-Varianten, unterschiedlicher Titel/Artist.
- `TestParserFallback` (1 Test): Duplicate-Erkennung über geparsten
  YouTube-Titel.
- `TestLibraryFallback` (3 Tests): Library-Datei-Fund, End-to-End über
  `check_for_duplicates`, kein Fund.

Zusätzlich `tests/test_metadata_processor_happy_path.py`: nutzt
`EnhancedDuplicateHandler` als Fixture im End-to-End-Metadata-Pfad
(`check_for_duplicates`/`register_download`).

**Vollständig ungetestet:**

- `show_statistics_menu`, `show_clear_cache_confirm`,
  `execute_clear_cache` (alle 3 Präsentationsmethoden) — **0 Treffer**
  in der gesamten Testsuite.
- `find_duplicates`, `clear_duplicate_cache` (Modul-Ebene) — **0
  Treffer**.
- `get_statistics`, `cleanup_cache`, `invalidate_entry` (isoliert,
  außerhalb von `TestUrlHashConsistencyCache001Fix`s indirekter
  `invalidate_entry`-Nutzung) — keine dedizierten Tests für
  `get_statistics`/`cleanup_cache`.

**Wichtige Beobachtung:** Die bestehende Testsuite behandelt — ohne dass
dies je explizit architektonisch entschieden wurde — bereits **genau
den in Abschnitt 6 identifizierten fachlichen Kern** als die zu
schützende Domäne. Die Tests sind damit eine **geeignete
Characterization-Basis** für eine mögliche künftige Extraktion: sie
würden eine Verschiebung des Kerns unverändert weiter absichern, ohne
angepasst werden zu müssen (reiner Import-Pfad-Wechsel wäre die einzige
nötige Änderung, hier nicht durchgeführt).

**Coverage-Lücke (nur dokumentiert, nicht bewertet als Risiko):** die
Präsentationsmethoden und die toten Kompatibilitätsfunktionen sind
ungetestet — bei den Präsentationsmethoden vertretbar geringes Risiko
(reine Formatierung/Anzeige), bei den toten Funktionen irrelevant (nie
erreicht).

---

## 9. Latenter Befund (nur dokumentiert, nicht behoben)

`find_duplicates()`/`clear_duplicate_cache()` (Zeilen 762–835) enthalten:

```python
config = (
    context.bot_data.get("config")
    or EnhancedDuplicateHandler()._get_default_config()
)
```

`EnhancedDuplicateHandler.__init__(self, config: Config, ...)` hat
**keinen Default-Wert für `config`** — `EnhancedDuplicateHandler()`
ohne Argument würde einen `TypeError` auslösen, falls
`context.bot_data.get("config")` jemals `None`/falsy zurückgäbe. Da
diese beiden Funktionen aber nachweislich **nirgends registriert oder
aufgerufen werden** (Abschnitt 4), ist dieser Bug im aktuellen Betrieb
nicht erreichbar — reine Dokumentation des Fundes, keine Bewertung als
aktives Risiko, keine Korrektur in dieser Phase.

---

## 10. Architekturvarianten

### Variante A — Fachlichen Kern aus `handlers/` herauslösen

Verschiebung von `DuplicateCache` + den 8 in Abschnitt 6 identifizierten
`EnhancedDuplicateHandler`-Methoden (`check_for_duplicates`,
`check_library_duplicate`, `register_download`,
`_normalize_artist_for_comparison`, `_clean_title_for_comparison`,
`_create_metadata_hash`, `_create_file_hash`) nach `services/` (z. B.
`services/duplicate/` oder Erweiterung eines bestehenden Bereichs).
`EnhancedDuplicateHandler` selbst würde in `handlers/` verbleiben,
reduziert auf die 3 Präsentationsmethoden + `get_statistics`/
`cleanup_cache`/`invalidate_entry`, und intern eine Instanz des neuen
Service nutzen (Delegation).

- **Vorteile:** löst die `klassen → handlers`-Kante vollständig auf
  (der Orchestrator würde dann `services/` statt `handlers/`
  importieren — konsistent mit der etablierten Downloader→Metadata-
  Richtung). Der bereits saubere Telegram-freie Kern bekommt eine
  strukturell passende Heimat. Bestehende 14+X Tests bleiben
  größtenteils gültig (nur Importpfad ändert sich).
- **Risiken:** `EnhancedDuplicateHandler` und der neue Service teilen
  sich denselben In-Memory-Zustand (`self.stats`, `self.duplicate_cache`)
  — die Aufteilung muss diesen Zustand konsistent halten (z. B. über
  Delegation statt Duplikation), sonst drohen zwei divergierende
  Zustände. Erfordert sorgfältige Migration der Konstruktor-Injection
  in `rich_menu_handler.py`/`download_handler.py`.
- **Dependency-Auswirkung:** `klassen → handlers`-Kante entfällt,
  `klassen → services` (bereits etabliert) wächst um einen Eintrag.
- **Testauswirkung:** gering — bestehende Tests testen bereits
  ausschließlich den zu verschiebenden Kern.
- **Verhaltensänderungsrisiko:** gering bis mittel, abhängig von der
  Umsetzung der Zustandsteilung — keine fachliche Logikänderung
  notwendig, nur Strukturverschiebung.
- **Scope:** mittel — 1 neue Datei/Modul, 2 Konsumenten-Stellen
  (`rich_menu_handler.py`, `download_handler.py`) anzupassen, Tests
  auf neuen Importpfad umzustellen.

### Variante B — Bestehende Struktur beibehalten (Status quo)

- **Vorteile:** kein Risiko, kein Aufwand.
- **Risiken:** die `klassen → handlers`-Kante bleibt architektonisch
  uneindeutig (Orchestrator importiert de facto Fachlogik aus der
  Präsentationsschicht). Kein Fortschritt gegenüber dem bereits
  dreimal (ARCH-006/007, POST-ARCH-010/011, POST-DUPLICATEENTRY)
  dokumentierten Befund.
- **Scope:** keiner.

### Variante C — Kleinere Aufteilung innerhalb bestehender Schichten

Nur `DuplicateCache` (reine Persistenz, klar abgegrenzt, keine
Business-Entscheidung) verschieben, `EnhancedDuplicateHandler`
(inklusive Kern UND Präsentation) bleibt vollständig in `handlers/`.

- **Vorteile:** kleinerer, risikoärmerer erster Schritt als Variante A.
- **Risiken:** löst die eigentliche `klassen → handlers`-Kante
  **nicht** — `check_for_duplicates`/`register_download` (die
  tatsächlich von `download_handler.py` benötigten Methoden) blieben
  weiterhin in `handlers/`. Löst damit den P1-Kernbefund nicht,
  sondern nur einen Teilaspekt.
- **Scope:** klein.
- **Bewertung:** keine echte Alternative zu Variante A für den
  eigentlichen Befund, allenfalls als Zwischenschritt denkbar.

Keine weitere Variante wird durch den Code nahegelegt — insbesondere
gibt es keinen Hinweis auf eine sinnvolle Aufteilung in mehr als zwei
Komponenten (Kern vs. Präsentation); die interne Struktur ist bereits
klar zweigeteilt, nicht mehrfach vermischt.

---

## 11. Risiken

- **Gemeinsamer In-Memory-Zustand** (`self.stats`, `self.duplicate_cache`)
  zwischen Business- und Präsentationsmethoden ist der zentrale
  technische Risikofaktor jeder Aufteilung (Variante A/C) — eine reine
  Dateikopie ohne Delegationsmuster würde den Zustand entzweien.
- **Zwei Produktionskonsumenten** (`download_handler.py`,
  `rich_menu_system.py`) müssen bei jeder Umsetzung synchron angepasst
  werden — kein isolierter Single-Consumer-Fall.
- **Die tote Legacy-Funktionalität** (`find_duplicates`,
  `clear_duplicate_cache`) birgt kein Risiko für eine Umsetzung, sollte
  aber bei einer Migration nicht versehentlich reaktiviert werden.
- Kein Datenverlust-Risiko identifiziert — alle Cache-Dateien
  (`url_duplicates.json`, `content_duplicates.json`) sind formatstabil
  und unabhängig vom Modulpfad.

---

## 12. Empfehlung

**Empfehlung für eine mögliche ARCH-018 Phase 2 (keine Umsetzung in
dieser Phase):** Variante A (fachlichen Kern nach `services/`
herauslösen) ist die einzige Variante, die den ursprünglichen P1-Befund
(Vermischung von Business-Logik und Präsentation, `klassen →
handlers`-Reverse-Edge) tatsächlich auflöst. Die bestehende Testsuite
bietet dafür bereits eine geeignete Characterization-Basis (Abschnitt 8).
Der zentrale, vor einer Umsetzung zu klärende technische Punkt ist das
Zustandsteilungs-Muster zwischen dem neuen Service und der verbleibenden
Präsentationsklasse (Delegation empfohlen, keine Datenduplikation).

Variante C wird **nicht** als eigenständiger nächster Schritt empfohlen,
da sie den Kernbefund nicht löst.

Dies ist eine **Empfehlung, keine Entscheidung** — die eigentliche
Umsetzung (inkl. Wahl des Zielorts innerhalb `services/`) obliegt einer
eigenen, ausdrücklich freigegebenen ARCH-018 Phase 2.

---

## 13. Entscheidungsgate (Phase 1)

**ARCH-018 Phase 1 — Characterization abgeschlossen.**
**Keine Produktionsänderung durchgeführt.**
**Kein Refactoring durchgeführt.**
**Keine Entscheidung über eine Umsetzung erzwungen.**

---

## 14. Phase 2 — Umsetzung (Variante A)

**Status:** abgeschlossen.

### Durchgeführte Extraktion

Neues Paket `services/duplicate/` (analog zur bestehenden Konvention
`services/statistik/`):

- **`services/duplicate/cache.py`** — `DuplicateCache`, unverändert aus
  `handlers/duplicate_handler.py` verschoben (Verhalten, Signaturen,
  Logik byte-identisch).
- **`services/duplicate/detector.py`** — neue Klasse `DuplicateDetector`,
  enthält den in Abschnitt 6 identifizierten fachlichen Kern:
  `check_for_duplicates`, `check_library_duplicate`, `register_download`,
  `_normalize_artist_for_comparison`, `_clean_title_for_comparison`,
  `_create_metadata_hash`, `_create_file_hash`, sowie die fachlich
  neutralen `get_statistics`, `cleanup_cache`, `invalidate_entry`
  (Abschnitt 6: "ihr einziger heutiger Konsument ist die
  Präsentationsschicht" — bleiben daher zusammen mit dem Kern, den sie
  direkt lesen/verändern, nicht in der Präsentationsklasse).

`handlers/duplicate_handler.py::EnhancedDuplicateHandler` reduziert auf
reine Telegram-Präsentation: Konstruktor nimmt jetzt eine injizierte
`DuplicateDetector`-Instanz entgegen (`config, detector, logger_factory`)
statt selbst einen `DuplicateCache` aufzubauen. `error_handler` (extern
gesetzte, nie intern gelesene Handler-Infrastruktur, Abschnitt 9)
bleibt unverändert in `handlers/`. `_get_default_config()` bleibt
unverändert in `handlers/` (kein Kern-Bezug). Die 3
Präsentationsmethoden (`show_statistics_menu`,
`show_clear_cache_confirm`, `execute_clear_cache`) rufen jetzt
`self.detector.get_statistics()`/`self.detector.duplicate_cache` statt
der vorherigen direkten Attribute auf — Verhalten unverändert.

Die bereits als tot charakterisierten Kompatibilitätsfunktionen
(`find_duplicates`, `clear_duplicate_cache`) wurden **nicht entfernt**
(außerhalb des Extraktions-Scopes) und **nicht funktional repariert** —
der in Abschnitt 9 dokumentierte latente `TypeError`-Bug
(`EnhancedDuplicateHandler()._get_default_config()`, zu wenige Pflicht-
Argumente) wurde bewusst **originalgetreu erhalten**, nicht durch die
Umstrukturierung stillschweigend behoben. Lediglich die strukturell
notwendige `DuplicateDetector`-Konstruktion wurde ergänzt, damit die
Datei syntaktisch gültig bleibt — beide Funktionen haben weiterhin
0 Aufrufer und bleiben unverändert unerreichbar.

### Reverse-Edge-Auflösung

`klassen/download_handler.py` importiert nicht mehr aus `handlers/`:

```python
# vorher
from handlers.duplicate_handler import EnhancedDuplicateHandler
def __init__(self, ..., duplicate_handler: EnhancedDuplicateHandler, ...):
    self.duplicate_handler = duplicate_handler
...
self.duplicate_handler.check_for_duplicates(url=url)
self.duplicate_handler.register_download(...)

# nachher
from services.duplicate.detector import DuplicateDetector
def __init__(self, ..., duplicate_detector: DuplicateDetector, ...):
    self.duplicate_detector = duplicate_detector
...
self.duplicate_detector.check_for_duplicates(url=url)
self.duplicate_detector.register_download(...)
```

`handlers/menu/rich_menu_handler.py` (einziger Ort, der beide Instanzen
erzeugt) erstellt jetzt zuerst den `DuplicateDetector`, reicht **dieselbe
Instanz** an `EnhancedDuplicateHandler` (Präsentation, für
`RichMenuSystem`) UND direkt an `DownloadHandler` (Business-Logik,
`klassen/`) weiter — beide Konsumenten teilen sich weiterhin denselben
Cache-/Statistik-Zustand (Delegationsmuster statt Zustandsduplikation,
wie im Risikoabschnitt der Phase 1 gefordert).

### Test-Anpassungen

`tests/test_duplicate_handler.py` (14 Tests) und
`tests/test_metadata_processor_happy_path.py` (5 Tests): Fixtures von
`EnhancedDuplicateHandler(...)` auf `DuplicateDetector(...)` umgestellt
— **reiner Import-Pfad-Wechsel**, wie in Abschnitt 8 der Characterization
vorhergesagt. Kein Testkörper (Assertions, Testlogik) verändert.

`tests/test_rich_menu_handler.py::TestCreateDownloadHandler` (3 Tests):
Mock-Setup und Assertions von `duplicate_handler`/`"duplicate_handler"`
auf `duplicate_detector`/`"duplicate_detector"` umgestellt — notwendige
Folge der Parameter-Umbenennung im `DownloadHandler`-Konstruktor, keine
Verhaltensänderung der getesteten Logik.

Keine Tests gelöscht, keine Testabdeckung geschwächt.

### C. Produktive Aufrufer vor/nachher

| Konsument | Vorher | Nachher |
|---|---|---|
| `klassen/download_handler.py` | `EnhancedDuplicateHandler.check_for_duplicates`/`register_download` (Reverse-Edge `klassen→handlers`) | `DuplicateDetector.check_for_duplicates`/`register_download` (`klassen→services`, erwartete Richtung) |
| `handlers/menu/rich_menu_system.py` | `EnhancedDuplicateHandler.show_statistics_menu`/`.show_clear_cache_confirm`/`.execute_clear_cache` | unverändert |

### Import-/Referenz-Audit (nach der Änderung)

```text
klassen/download_handler.py → handlers/*        : 0 Treffer (Reverse-Edge aufgelöst)
services/duplicate/*        → handlers/*        : 0 Treffer
services/*                  → handlers/*        : weiterhin 0
Importzyklen (repo-weit, AST-basiert)            : 0
```

`AudioEnhancer` bzw. andere zuvor bestehende Cross-Directory-Kanten
unverändert. Keine neue Abstraktion außer der bereits in Phase 1
angekündigten Trennung Kern/Präsentation eingeführt.

### Diff-/Scope-Audit

```text
Neu:      services/duplicate/__init__.py
          services/duplicate/cache.py
          services/duplicate/detector.py
Geändert: handlers/duplicate_handler.py            (Präsentation, Delegation)
          handlers/menu/rich_menu_handler.py        (Wiring: Detector + Handler)
          klassen/download_handler.py               (Import/Attribut-Umbenennung)
          tests/test_duplicate_handler.py            (Fixture-Importpfad)
          tests/test_metadata_processor_happy_path.py (Fixture-Importpfad)
          tests/test_rich_menu_handler.py            (Mock-/Assertion-Umbenennung)
```

Keine Änderung an `services/downloader/models.py` (`DuplicateEntry`
unverändert wiederverwendet), `services/metadata/*`, YAML-Dateien,
`CLAUDE.md`, `README.md`.

### Regression

`pytest tests/ -q` → **1114 passed**, 15 bekannte Vorbestandsfehler,
**identisch zur Baseline** — 0 neue Fehlschläge. Gezielt zusätzlich
geprüft: `test_duplicate_handler.py` + `test_metadata_processor_happy_path.py`
+ `test_autolearn_special_channel_gate.py` (23/23) sowie
`test_rich_menu_handler.py` (33/33).

### Unerwartete Befunde während der Umsetzung

Keine neuen unerwarteten Befunde. Der bereits in Phase 1 dokumentierte
latente `TypeError`-Bug in den toten Kompatibilitätsfunktionen wurde
bewusst nicht repariert (s. o.) — kein neuer Fund, nur erneut bestätigt
weiterhin unreichbar und unverändert.

### Verbleibende ARCH-018-Folgepunkte

- `find_duplicates`/`clear_duplicate_cache` (toter Code) — weiterhin
  nicht entfernt, außerhalb des Extraktions-Scopes.
- Der darin enthaltene latente `TypeError`-Bug — weiterhin nur
  dokumentiert, nicht behoben.

---

## 15. Entscheidungsgate (Phase 2)

**ARCH-018 Phase 2 — Extraktion abgeschlossen.**
**Fachlicher Kern nach `services/duplicate/` verschoben.**
**`klassen → handlers`-Reverse-Edge vollständig aufgelöst.**
**Keine Verhaltensänderung — Regression identisch zur Baseline.**
**STOPP.**
**Keine automatische Folgephase. Warte auf ausdrückliche Freigabe.**
