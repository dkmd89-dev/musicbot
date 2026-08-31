# POST-ARCH-010/011 — Folgeanalyse: `DuplicateEntry`-Boundary

## Status

**Analyse abgeschlossen (2026-08-24) — Migration umgesetzt (2026-08-24).**
Siehe Abschnitt 13 für den Umsetzungs-/Verifikationsbericht.

Fokus ausschließlich auf die im POST-ARCH-010/011-Audit als empfohlenen
nächsten Schritt benannte Abhängigkeit:

```text
services/downloader/download_result_reporter.py
    ↓
handlers/duplicate_handler.py::DuplicateEntry
```

---

## 1. Definition und tatsächliche Verantwortung von `DuplicateEntry`

```python
# handlers/duplicate_handler.py, Zeile 28–39
@dataclass
class DuplicateEntry:
    """Repräsentiert einen Duplikat-Eintrag im Cache"""

    artist: str
    title: str
    url: str
    file_path: Optional[Path]
    download_date: datetime
    file_hash: Optional[str] = None
    metadata_hash: str = None
    duplicate_count: int = 1
```

- Reines `@dataclass`, **keine** eigenen Methoden, **keine** überschriebenen
  `__eq__`/`__hash__`/`__repr__` (Standard-Dataclass-Verhalten:
  feldweise Gleichheit).
- **Keine** Telegram-Typen, **keine** Handler-spezifischen Felder. Alle 8
  Felder sind reine Stdlib-Typen (`str`, `Path`, `datetime`, `int`) bzw.
  einfache Optionals.
- Tatsächliche Verantwortung: **reiner Datencontainer** für einen
  Duplikat-Cache-Eintrag (Artist/Titel/URL/Datei-Pfad/Download-Datum plus
  Hash-/Zähl-Metadaten für die Duplikat-Erkennung). Trägt selbst keine
  Logik — die eigentliche Duplikat-Erkennungslogik liegt vollständig in
  `DuplicateCache` (URL-/Content-Hash-Lookup, JSON-Persistenz) und
  `EnhancedDuplicateHandler` (Entscheidungsbaum URL → Content → Parser →
  Library, siehe CLAUDE.md §15).

`DuplicateEntry` selbst ist damit **kein** Handler-Objekt im funktionalen
Sinn — es ist derselbe Fall wie `DownloadResult`/`PlaylistResult`
(`services/downloader/download/models.py`) oder `MetadataResult`
(`services/metadata/models.py`): eine reine Datenstruktur, die zufällig in
einer Datei mit Telegram-Code liegt, aber inhaltlich nichts davon
mitbringt.

---

## 2. Produktions-Consumer (repo-weit)

| Datei | Rolle | Details |
|---|---|---|
| `handlers/duplicate_handler.py` | **Ursprungsort + Haupt-Konsument** | `DuplicateCache._load_url_cache()`/`_load_content_cache()` (Deserialisierung aus JSON), `DuplicateCache.add_entry()`/`check_url_duplicate()`/`check_content_duplicate()` (Cache-Operationen), `EnhancedDuplicateHandler.check_for_duplicates()` (Library-Fallback, Zeile 399) und `register_download()` (Zeile 476) — beide konstruieren neue `DuplicateEntry`-Instanzen |
| `services/downloader/download_result_reporter.py` | **Konsument (nur lesend)** | `build_duplicate_message(entry: DuplicateEntry, dup_type: str)` (Zeile 104) — liest ausschließlich `entry.title`, `entry.artist`, `entry.download_date`, `entry.file_path` zur Textformatierung. Konstruiert **nie** selbst eine Instanz, ruft **keine** Methode auf `entry` auf. Dies ist die zu analysierende Boundary |
| `klassen/download_handler.py` | **Konsument + zweiter Konstruktor** | Importiert `DuplicateEntry` **und** `EnhancedDuplicateHandler` aus `handlers/duplicate_handler.py` (Zeile 45). Nutzt `DuplicateEntry` als Typannotation (`_check_duplicates_before_download()`, Zeile 327; `_handle_duplicate_found()`, Zeile 370) **und konstruiert selbst eine zweite, unabhängige Instanz** für den Dateikonflikt-Fall (`conflict_entry = DuplicateEntry(...)`, Zeile 749), die anschließend an `build_duplicate_message()` übergeben wird |

**Wichtiger Befund:** `klassen/download_handler.py` ist ein **zweiter,
eigenständiger Produktions-Consumer** von `DuplicateEntry` — nicht nur
`download_result_reporter.py`. Eine Migration muss diesen mit einbeziehen
(siehe Abschnitt 10).

`klassen/download_handler.py` liegt außerhalb von `services/` (Orchestrator-
Schicht, vgl. CLAUDE.md-Architekturdiagramm `DownloadHandler` zwischen
`RichMenuHandler` und der Download-/Metadaten-Pipeline). Sein Import aus
`handlers/duplicate_handler.py` ist **keine** Schichtverletzung im Sinne
der in CLAUDE.md §4 definierten `services/`-Grenze — die dort verbotene
Richtung ist ausdrücklich `services/* → handlers/*`, nicht `klassen/* →
handlers/*`. `klassen/download_handler.py` bleibt daher unabhängig vom
Ausgang dieser Analyse berechtigt, `EnhancedDuplicateHandler` weiterhin aus
`handlers/duplicate_handler.py` zu importieren.

---

## 3. Test-Consumer

| Datei | Nutzung |
|---|---|
| `tests/test_download_result_reporter.py` | Importiert `DuplicateEntry` (Zeile 34), eigener Test-Helper `_entry()` (Zeile 144) konstruiert Instanzen für `build_duplicate_message()`-Tests (4 Testfälle, Zeilen 147–164) |
| `tests/test_duplicate_handler.py` | Importiert `DuplicateEntry` neben `EnhancedDuplicateHandler` (Zeile 27) — testet primär `EnhancedDuplicateHandler`/`DuplicateCache`-Verhalten; `DuplicateEntry` wird dort nicht direkt neu konstruiert, sondern indirekt über die getesteten Methoden erzeugt |

Kein Test für `klassen/download_handler.py`s direkte `DuplicateEntry`-
Konstruktion (Zeile 749) gefunden — dieser Pfad (`file_conflict`) wird
nicht dediziert getestet (out of scope für diese Analyse, aber als
Testlücke notiert).

---

## 4. Imports und Abhängigkeiten von `DuplicateEntry` selbst

Die Klassendefinition selbst hat **keine** eigenen Imports über die
Modul-Ebene von `handlers/duplicate_handler.py` hinaus nötig:

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
```

Alle vier sind Python-Stdlib. Keine Abhängigkeit zu `telegram`, `config`,
`logger`, `utils/*` oder einer anderen Projektdatei. Die Klasse ist
**vollständig eigenständig verschiebbar**, ohne weitere Importe
mitzuziehen.

---

## 5. Ist `DuplicateEntry` tatsächlich Handler-spezifisch?

**Nein.** Weder die Felder noch die (fehlende) Methodik referenzieren
irgendetwas Telegram-/Presentation-Bezogenes. Die einzige „Handler"-
Eigenschaft ist der **Ort** der Definition, nicht der Inhalt. Das deckt
sich exakt mit dem in Abschnitt 1 gezogenen Vergleich zu
`DownloadResult`/`MetadataResult`.

## 6. Ist die Klasse fachlich neutral?

**Ja, vollständig.** `DuplicateEntry` transportiert reine
Duplikat-Cache-Metadaten (Artist, Titel, URL, Dateipfad, Datum, Hashes,
Zähler) — verwendbar unabhängig davon, ob der Aufrufer ein Telegram-Handler,
ein Downloader-Modul oder ein zukünftiger CLI-Pfad ist.

## 7. Zielort-Bewertung

| Kandidat | Eignung | Begründung |
|---|---|---|
| `services/downloader/` (neue, flache Datei) | **Am besten geeignet** | Beide externen (Nicht-`handlers/duplicate_handler.py`-)Konsumenten liegen im Downloader-Umfeld (`download_result_reporter.py` direkt in `services/downloader/`, `klassen/download_handler.py` als dessen Orchestrator). Entspricht exakt dem ARCH-010-Präzedenzfall (`DownloadResult`/`PlaylistResult` in `services/downloader/download/models.py`, `MetadataResult` in `services/metadata/models.py`) |
| `services/` (Top-Level, ohne Unterordner) | Ungeeignet | Kein Präzedenzfall im Repo für Modelle direkt unter `services/` (nur `statistik_service.py` liegt dort, keine Dataclasses); würde eine neue Konvention einführen ohne Bedarf |
| `utils/` | Ungeeignet | `utils/` ist für technische Querschnitts-Helfer (CLAUDE.md §4), nicht für fachliche Domänen-Datentypen. `DuplicateEntry` ist ein Duplicate-Detection-Fachobjekt, kein technisches Utility |
| bestehender Model-Bereich (`services/downloader/download/models.py` oder `services/metadata/models.py`) | Ungeeignet ohne Weiteres | `download/models.py` wurde in ARCH-011 Phase 1 ausdrücklich als interne Zerlegung von `download_utils.py` charakterisiert (Single-/Dual-Consumer-Fall für `DownloadResult`/`PlaylistResult`) — `DuplicateEntry` gehört fachlich nicht zu dieser Gruppe (andere Domäne: Duplicate Detection, nicht Download-Ergebnis-Repräsentation) und würde diese saubere Charakterisierung verwässern. `services/metadata/models.py` ist erst recht falsch (falsche Domäne) |
| andere bestehende Boundary (`services/clients/`) | Ungeeignet | Kein externer API-Adapter-Bezug |

**Kein Bedarf für eine neue Top-Level-Schicht** (z. B. `services/duplicate/`):
Es gibt aktuell nur diese eine Dataclass zu verschieben, keine
Multi-Datei-Domäne, die eine eigene Schicht rechtfertigen würde. Die
eigentliche Duplicate-Detection-**Logik** (`DuplicateCache`,
`EnhancedDuplicateHandler`) bleibt bewusst außerhalb des Scopes dieser
Analyse (siehe Abschnitt 10) — nur die Datenklasse wird betrachtet.

---

## 8. Auswirkungen einer Verschiebung

**Serialisierung:** `DuplicateCache._save_caches()`/`_load_url_cache()`/
`_load_content_cache()` (de-)serialisieren `DuplicateEntry` manuell
Feld-für-Feld in/aus einfachen JSON-Dicts (kein `dataclasses.asdict()`,
kein `pickle`, keine eingebettete Modulpfad-Information im JSON). Eine
Verschiebung hat **keinerlei** Auswirkung auf das bestehende
`duplicate_cache/*.json`-Dateiformat — die gespeicherten Caches bleiben
byte-identisch lesbar.

**Equality:** Standard-Dataclass-`__eq__` vergleicht Klassenidentität +
Feldwerte. Da bei einer Verschiebung die Klasse nur an einem Ort existiert
(kein Duplikat, echter `git mv`-artiger Umzug der Definition), bleibt das
Verhalten unverändert — es gibt nach der Migration weiterhin nur eine
einzige `DuplicateEntry`-Klasse im Objektgraphen.

**Type Checking:** Drei Dateien mit `DuplicateEntry`-Typannotationen
(`handlers/duplicate_handler.py`, `services/downloader/download_result_reporter.py`,
`klassen/download_handler.py`) benötigen aktualisierte Importpfade. Keine
`isinstance()`-Prüfungen gegen `DuplicateEntry` im gesamten Repo gefunden —
kein Risiko durch Klassenidentitäts-Vergleiche.

**Tests:** 2 Testdateien (Abschnitt 3) benötigen aktualisierte Importpfade.
Keine Testlogik selbst ändert sich (reine Importzeilen-Anpassung).

---

## 9. `mock.patch`-/Monkeypatch-Ziele

Repo-weite Suche nach `mock.patch`/`monkeypatch` mit Bezug auf
`duplicate_handler` oder `DuplicateEntry`: **keine Treffer.** Kein Test
patcht `DuplicateEntry` selbst oder dessen Importpfad. Migrationsrisiko in
diesem Punkt: **keins.**

---

## 10. Sicherstellen: keine weitere Handler-Logik mitverschoben werden muss

**Bestätigt — ausschließlich `DuplicateEntry` betroffen.** Explizit
geprüft, was **nicht** mitverschoben wird:

- `DuplicateCache` (Zeilen 42–286) — bleibt in `handlers/duplicate_handler.py`.
  Reine Cache-/Persistenz-Logik ohne Telegram-Bezug, aber **außerhalb**
  des hier angefragten Scopes (eigener, deutlich größerer Befund — siehe
  Hinweis unten).
- `EnhancedDuplicateHandler` (Zeilen 289–594, inkl. `show_statistics_menu()`,
  `show_clear_cache_confirm()`, `execute_clear_cache()`) — bleibt
  unverändert, enthält echte Telegram-Presentation-Methoden
  (`Update`/`ContextTypes`/`InlineKeyboardMarkup`), gehört korrekt nach
  `handlers/`.
- Modul-Funktionen `find_duplicates()`/`clear_duplicate_cache()`
  (Zeilen 776–849) — reine Telegram-Handler-Funktionen, bleiben
  unverändert.

**Hinweis (nicht Teil dieser Analyse, nur zur Transparenz):** `DuplicateCache`
selbst (Cache-Lookup, JSON-Persistenz, URL-/Content-Hash-Logik) ist
inhaltlich reine, Telegram-freie Business-Logik und liegt strukturell
ähnlich „falsch" in `handlers/` wie es `services/downloader/utils/`
vor ARCH-010 war — das ist jedoch ein **erheblich größerer** Befund
(mehrere hundert Zeilen aktive Logik, P0-Bereich „Duplicate Detection")
und explizit **nicht** Gegenstand dieser auf `DuplicateEntry` begrenzten
Anfrage. Falls gewünscht, wäre das ein eigenständiger, dedizierter
Analyse-Auftrag (analog ARCH-011 Phase 1), keine Erweiterung dieses
Dokuments.

---

## 11. Variantenbewertung

**A — `DuplicateEntry` als neutrales Model extrahieren**
Neue, kleine Datei z. B. `services/downloader/models.py` (flach, analog
zum ARCH-010-Muster). Vorteil: folgt exakt dem dreifach bewährten
Präzedenzfall (`DownloadResult`, `PlaylistResult`, `MetadataResult`), klar
neutraler Name, kein Bezug zu einer falschen Domäne. **Empfohlen.**

**B — bestehende Klasse an einen vorhandenen fachlich passenden Ort
verschieben**
Kein bestehender Ort passt ohne Kompromisse (Abschnitt 7) — `download/models.py`
würde die ARCH-011-Charakterisierung verwässern, `services/metadata/models.py`
ist die falsche Domäne. Nicht empfohlen als Alternative zu A, außer der
Nutzer möchte ausdrücklich keine neue Datei anlegen.

**C — Abhängigkeit anders auflösen** (z. B. `download_result_reporter.py`
verlangt statt der konkreten Dataclass nur ein strukturell kompatibles
Protocol/Duck-Type, ähnlich `services/downloader/download/interfaces.py`)
Technisch möglich, aber unnötiger Umweg: `DuplicateEntry` hat keine
Methoden, ein Protocol würde nur die 4 gelesenen Attribute
(`title`/`artist`/`download_date`/`file_path`) abstrahieren — mehr aufwand
als Nutzen für eine reine Dataclass ohne Verhalten. Nicht empfohlen.

**D — Abhängigkeit bewusst bestehen lassen**
Möglich, aber verfehlt den in der übergeordneten Audit-Empfehlung
benannten Zweck (letzte verbliebene `services/*→handlers/*`-
Schichtverletzung schließen) ohne echten Gegenwert — die Migration ist mit
Variante A risikoarm und klein. Nicht empfohlen.

---

## 12. Entscheidungsgate

**Tatsächliche Verantwortung:** reiner, Telegram-freier Datencontainer für
einen Duplikat-Cache-Eintrag — keine Handler-spezifische Logik, keine
eigene Methodik.

**Alle Consumer:**
- `handlers/duplicate_handler.py` (Ursprung, Haupt-Konsument: `DuplicateCache`,
  `EnhancedDuplicateHandler`)
- `services/downloader/download_result_reporter.py` (nur lesend, die
  ursprünglich angefragte Boundary)
- `klassen/download_handler.py` (Typannotation + eigene Konstruktion,
  zweiter Produktions-Consumer — **muss mitmigriert werden**)
- `tests/test_download_result_reporter.py`, `tests/test_duplicate_handler.py`

**Empfohlener Zielort:** neue, flache Datei `services/downloader/models.py`
(Variante A) — analog zum dreifachen ARCH-010-Präzedenzfall.

**Betroffene Dateien (bei Umsetzung):**
1. `handlers/duplicate_handler.py` — Klassendefinition entfernen, Import
   aus neuem Ort ergänzen (`DuplicateCache`/`EnhancedDuplicateHandler`
   nutzen `DuplicateEntry` weiterhin intern)
2. `services/downloader/download_result_reporter.py` — Importzeile ändern
3. `klassen/download_handler.py` — Importzeile ändern (Import von
   `EnhancedDuplicateHandler` bleibt unverändert aus `handlers/duplicate_handler.py`)
4. `tests/test_download_result_reporter.py` — Importzeile ändern
5. `tests/test_duplicate_handler.py` — Importzeile ändern

**Risiko:** sehr niedrig. Reine Dataclass ohne Methoden, keine
`isinstance()`-Prüfungen, keine `mock.patch`-Ziele, keine Auswirkung auf
das JSON-Cache-Format (Abschnitt 8). 5 Dateien mit je einer Importzeile
betroffen.

**Erwarteter Nutzen:** `services/` wird vollständig frei von
`handlers/*`-Importen — schließt die letzte im POST-ARCH-010/011-Audit
identifizierte `services/*→handlers/*`-Schichtverletzung.

**Vorgeschlagene Migrationsreihenfolge** (falls freigegeben):
1. `services/downloader/models.py` neu anlegen mit `DuplicateEntry`
   (identische Felddefinition, keine Verhaltensänderung).
2. `handlers/duplicate_handler.py`: Klassendefinition entfernen, stattdessen
   `from services.downloader.models import DuplicateEntry` importieren.
3. `services/downloader/download_result_reporter.py`: Import auf
   `services.downloader.models` umstellen.
4. `klassen/download_handler.py`: Import von `DuplicateEntry` auf
   `services.downloader.models` umstellen (Import von
   `EnhancedDuplicateHandler` unverändert lassen).
5. `tests/test_download_result_reporter.py`,
   `tests/test_duplicate_handler.py`: Importzeilen anpassen.
6. Vollständiger Regressionslauf (`pytest tests/ -q`), Vergleich gegen die
   bekannte Baseline.
7. Commit/PR analog zum etablierten ARCH-010/011-Muster.

---

## 13. Umsetzungs-/Verifikationsbericht (2026-08-24)

Migration wie in Abschnitt 12 empfohlen (Variante A) durchgeführt.

### 13.1 Vorprüfung (Phase 1)

Repo-weiter Re-Check unmittelbar vor der Migration bestätigte den Audit
unverändert: identische Definition, identische Consumer-Liste (Abschnitte
1–10), keine `mock.patch`-/`isinstance()`-Treffer, keine `__init__.py`-
Re-Exports. Einziger Zusatzfund: `docs/archive/MusicBot_ENGINEERING_BASELINE.md`
enthielt einen offenen Checklisten-Punkt, der genau diese Abhängigkeit als
unentschieden auflistete — kein architektonischer Neufund, sondern ein
durch die Migration aufzulösender Dokumentationsstand (siehe 13.6). Kein
Scope-Erweiterungsgrund, Migration wie geplant fortgesetzt.

### 13.2 Migration

- Neue Datei `services/downloader/models.py` angelegt mit `DuplicateEntry`
  — Felddefinition byte-identisch zum Original, keine neuen Methoden,
  keine Umbenennung. (Kein `git mv` möglich/sinnvoll, da nur eine von
  mehreren Klassen aus `handlers/duplicate_handler.py` extrahiert wurde,
  nicht die ganze Datei.)
- `handlers/duplicate_handler.py`: Klassendefinition entfernt, Import
  `from services.downloader.models import DuplicateEntry` ergänzt.
  `from dataclasses import dataclass` als Import entfernt (nach Entfernung
  der Klasse einziger Verwendungsort, dadurch tot geworden — direkt an
  dieser Stelle bereinigt, keine separate Aufräum-Aktion). `DuplicateCache`,
  `EnhancedDuplicateHandler` sowie beide Telegram-Modulfunktionen
  vollständig unverändert.
- `services/downloader/download_result_reporter.py`: Importzeile auf
  `services.downloader.models` umgestellt.
- `klassen/download_handler.py`: `DuplicateEntry`-Import auf
  `services.downloader.models` umgestellt, `EnhancedDuplicateHandler`-Import
  aus `handlers.duplicate_handler` unverändert belassen (zwei getrennte
  Importzeilen statt einer kombinierten).
- `tests/test_duplicate_handler.py`,
  `tests/test_download_result_reporter.py`: Importzeilen umgestellt.

### 13.3 Architektur nach Migration

```text
services/downloader/models.py
        ↑
        ├── services/downloader/download_result_reporter.py
        ├── klassen/download_handler.py
        └── handlers/duplicate_handler.py
```

`services/* → handlers/*` für `DuplicateEntry`: **beseitigt.**

### 13.4 Audit nach Migration

- Altpfad (`from handlers.duplicate_handler import ... DuplicateEntry` /
  `handlers.duplicate_handler.DuplicateEntry`): **0 funktionale Treffer**
  repo-weit.
- Neuer Pfad (`services.downloader.models.DuplicateEntry`): 5 Treffer,
  exakt die 5 in Abschnitt 12 gelisteten Dateien.
- Schichtprüfung `services/* → handlers/*` (repo-weit, `^from handlers`/
  `^import handlers` unter `services/`): **0 Treffer.**
- Historische/dokumentarische Erwähnungen des Altpfads in
  `docs/archive/arch/MusicBot_ARCH-003_Services_Phase1_Analyse.md`,
  `docs/archive/arch/MusicBot_ARCH-007_P2_Entkopplungsvorschlag.md` — bewusst
  unverändert gelassen (datierte Analyse-/Vorschlags-Snapshots, keine
  Korrektur historischer Dokumente).

### 13.5 Smoke-Test

```python
import services.downloader.models
import services.downloader.download_result_reporter
import klassen.download_handler
import handlers.duplicate_handler
```

Alle vier Module importieren fehlerfrei, keine Zirkelimporte.
`services.downloader.models.DuplicateEntry is handlers.duplicate_handler.DuplicateEntry`
→ `True` (identische Klassenidentität nach dem Umzug, wie in Abschnitt 8
vorhergesagt).

### 13.6 Tests

- Gezielt: `pytest tests/test_duplicate_handler.py
  tests/test_download_result_reporter.py -q` → **38 passed.**
- Vollständig: `pytest tests/ -q` → **1009 passed, 15 failed** — identisch
  zur bekannten Baseline (`test_auto_learn.py` 5 inkl. Subfails,
  `test_metadata_modules.py::TestTitleCleaner` 3 inkl. Subfails,
  `test_suite.py` 4 — alle wegen fehlendem `pytest-asyncio`, unverändert
  vorbestehend). **Keine neue Regression.**

### 13.7 Dokumentation

- `docs/archive/post-arch/MusicBot_POST-ARCH-010_011_DuplicateEntry_Analyse.md` (dieses
  Dokument) — Status aktualisiert, dieser Abschnitt ergänzt.
- `README.md` — Zeile zu `services/downloader/` um `models.py` ergänzt
  (Projektstruktur-Tabelle war zuvor vollständig, jetzt wieder korrekt).
- `docs/archive/MusicBot_ENGINEERING_BASELINE.md` — offener Checklisten-Punkt zur
  `DuplicateEntry`-Abhängigkeit (Zeile im Abschnitt „Weitere geplante
  Schritte") durch neuen `[x]`-Eintrag ersetzt/aufgelöst.
- `CLAUDE.md` — unverändert (keine Aussage darin wurde durch die Migration
  widersprüchlich).
- Historische ARCH-Dokumente (`ARCH-003`, `ARCH-007`) — bewusst
  unverändert.

### 13.8 Status

**Migration abgeschlossen.** Bereit für Commit/Push/PR.

---

Keine weitere Architekturarbeit als Teil dieses Auftrags. Siehe
Abschlussbericht für Folgepunkte.
