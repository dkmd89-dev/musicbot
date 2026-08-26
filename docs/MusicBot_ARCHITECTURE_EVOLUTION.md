# MusicBot — Architecture Evolution

**Art dieses Dokuments:** Forensische Architektur-Entscheidungs- und Evolutions-Analyse.
Keine Implementierung. Kein Refactoring. Keine Baseline v4.

> **⚠️ Nachtrag (Closure-Audit, siehe Abschnitt 26):** Die Closure-Verification hat
> gezeigt, dass die Invarianten-Compliance-Aussagen in Abschnitt 9 und 17 dieses
> Dokuments **nicht repo-weit verifiziert** waren, sondern nur für die durch
> FINDING-1–7 tatsächlich berührten Dateien galten. Ein repo-weiter Sweep deckte
> weitere, bisher nicht dokumentierte INV-01/INV-02-Verletzungen auf — mehrere davon
> in P0-Bereichen (Mapping/Auto-Learn, Duplicate Detection). **Freeze-Status: 🔴 NOT
> READY.** Die ursprüngliche Analyse unten bleibt als historische Argumentation
> erhalten; Korrekturen sind inline markiert und in Abschnitt 26 vollständig
> zusammengefasst.

---

## 1. Purpose

Dieses Dokument bestimmt, welche architektonische Weiterentwicklung durch tatsächliche
Evidenz aus der MusicBot-Implementierung gerechtfertigt ist — nicht, wie die
Architektur "sauberer" gemacht werden könnte. Grundlage sind die sieben in dieser
Engineering-Cycle geschlossenen Findings sowie eine direkte Verifikation der aktuellen
Codebasis (keine Übernahme unverifizierter Altdokumentation).

---

## 2. Current Freeze Point

```
HEAD:   b26166dbc22edeefe453c7ae4161a4e41b33cbff
Branch: main
```

**Verifiziert (dieser Audit):**
```
git status --short   → nur docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md (Freeze-Point-Nachtrag, unkommittiert)
pytest tests/ -q      → 1077 passed, 0 failed
```

**Geschlossene Findings:** FINDING-1 … FINDING-7 (siehe Abschnitt 3).

---

## 3. Evidence Base

| Dokument | Aktueller Pfad | Hinweis |
|---|---|---|
| Engineering Baseline v3 | `docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` | CURRENT, eingefroren |
| Post-Baseline Triage | `docs/archive/MusicBot_POST_BASELINE_TRIAGE.md` | HISTORICAL |
| Phase 4 Failure-Path Audit | `docs/archive/MusicBot_PHASE4_FAILURE_PATH_AUDIT.md` | **Pfad-Korrektur:** liegt nicht mehr unter `docs/`, sondern wurde durch eine zwischenzeitliche Dokumentations-Umstrukturierung (Commits zwischen `ea01c62` und `b26166d`, nicht Teil dieser Session) nach `docs/archive/` verschoben. Inhalt unverändert, hier zitiert. |
| FINDING-4 Forensic Audit | `docs/archive/MusicBot_FINDING_4_FORENSIC_AUDIT.md` | ebenso verschoben |
| Phase 5 Performance Baseline | `docs/archive/MusicBot_PHASE5_PERFORMANCE_BASELINE.md` | CURRENT, inkl. FINDING-7-Nachtrag + Technical-Freeze-Point |
| `docs/INDEX.md` | — | 24 ARCH-\*-Dokumente + 9 POST-ARCH-\*-Audits unter `docs/archive/`, als historische Entscheidungsgrundlage herangezogen, nicht reproduziert |

Zusätzlich direkt gegen den aktuellen Code verifiziert (nicht aus Dokumentation
übernommen): `bot.py`, `klassen/download_handler.py`,
`services/metadata/enhanced_metadata_processor.py`,
`handlers/enhanced_error_handler.py`, `handlers/error_handler.py`, `config.py`,
`services/duplicate/`, `services/metadata/cover_processor.py`,
`tests/test_download_concurrency_semaphore.py`.

---

## 4. Current Architecture

Schichtgrenzen sind bereits durch ARCH-009 etabliert und in `CLAUDE.md` §4
dokumentiert (`handlers/` = Telegram-Präsentation, `services/` = Orchestrierung,
`services/clients/` = externe Integrationsadapter, `utils/` = lokale
Hilfs-/Runner-Komponenten ohne Netzwerk, `api/` = entfernt). Diese Grenzen wurden in
dieser Session nicht verletzt vorgefunden — alle sieben Findings lagen INNERHALB der
erwarteten Schicht ihrer Komponente, keines war eine Schichtgrenzverletzung.

**Hauptkomponenten (verifizierte Größe/Verantwortung):**

| Komponente | Zeilen | Verantwortung | Async-Modell |
|---|---|---|---|
| `klassen/download_handler.py` (`DownloadHandler`) | 720 | Telegram-Eingang → Duplikat-Check → Download-Orchestrierung → Erfolg/Fehler-Reporting (12 öffentliche/private Methoden) | async, `asyncio.Semaphore(3)` global |
| `services/metadata/enhanced_metadata_processor.py` (`EnhancedMetadataProcessor`) | 1252 | 20-Schritte-Pipeline (Cache → Artist → Titel → Genre → Lyrics → Cover → Album → Loudness → Move → Tags → Cache-Store), Singleton | async, delegiert an 9 Sub-Prozessoren |
| `handlers/enhanced_error_handler.py` (`EnhancedErrorHandler` + `ErrorHandlerAdminInterface` + `ErrorHandlerIntegration`) | 2506 | Globales Exception-Handling, Kategorisierung, Recovery-Strategien, Telegram-Fehlerbenachrichtigung | async, aktiv als PTB-`add_error_handler` registriert |
| `services/clients/*` | — | Reine externe Integrationsadapter (MusicBrainz, Genius, Last.fm, Navidrome) | alle via `asyncio.to_thread`/`aiohttp` entkoppelt |
| `services/duplicate/` (`detector.py`, `cache.py`) | — | Duplicate-Detection-Kern (seit ARCH-018 Phase 2 extrahiert) | nicht vertieft geprüft in dieser Session — siehe Abschnitt 25 |
| `config.py` (`Config`) | ~700+ | Eine zentrale Klasse, Klassenattribute + `get_config()`-Factory | rein synchron, keine Seiteneffekte außer Verzeichnis-Erstellung |

Sub-Prozessoren von `EnhancedMetadataProcessor` (jeweils eigene Datei unter
`services/metadata/`): `ArtistProcessor`, `TitleCleaner`, `GenreProcessor`,
`AlbumProcessor`, `LyricsProcessor`, `CoverProcessor`, `AutoLearnManager`,
`TagWriter`, `MetadataCacheHandler` — konsistent mit der in `CLAUDE.md` §19
dokumentierten "nicht automatisch zerlegen, aber Verantwortlichkeiten
dokumentieren"-Regel; die Zerlegung in Sub-Prozessoren ist bereits erfolgt.

---

## 5. Dependency Boundaries

| Grenze | Verantwortung klar? | Failure-Ownership klar? | Concurrency-Ownership klar? | Getestet? | Evidenz aus Findings |
|---|---|---|---|---|---|
| A. Telegram ↔ Application | Ja — `handlers/` vs `klassen/`/`services/` | Teilweise — zwei parallele Systeme, siehe Abschnitt 11 | n/a | Teilweise | FINDING-4 |
| B. Application ↔ Download | Ja | Ja (nach FINDING-4-Fix) | Ja (`Semaphore(3)`, getestet) | Ja | FINDING-4 |
| C. Download ↔ Metadata | Ja (`process_single_track` als klare Grenze) | Ja | n/a (sequenziell je Track) | Teilweise (E2E-Happy-Path) | FINDING-1, FINDING-7 |
| D. Metadata ↔ Tagging | Ja (`TagWriter`) | Ja | n/a | Ja | — |
| E. Application ↔ Filesystem | Ja (`filenamefixer.move_to_library`) | Ja (nach FINDING-6) | n/a | Ja | FINDING-2, FINDING-6 |
| F. Application ↔ External Services | Ja (`services/clients/`) | Uneinheitlich (siehe Abschnitt 12) | Ja (alle via `to_thread`) | Teilweise | FINDING-1 |
| G. Persistence ↔ Business Logic | Ja | Ja für Haupt-Cache/Index/Library; NEIN für Cover-Cache (nicht-atomar) | n/a | Teilweise | FINDING-5, FINDING-6 |
| H. Async ↔ Blocking Work | Ja als Muster, aber nicht strukturell erzwungen | Ja | n/a | Ja (je Fund einzeln) | FINDING-1, FINDING-7 |
| I. Error Handling ↔ Reporting | Zwei parallele, nicht überlappende Systeme (Abschnitt 11) | Ja innerhalb jedes Systems | n/a | Teilweise | FINDING-2, FINDING-3 |
| J. Configuration ↔ Runtime | Ja, zentral | n/a | Ja (`MAX_CONCURRENT_DOWNLOADS` etc. durchgesetzt) | Teilweise | Phase 5 Abschnitt 9 |

Keine zirkulären Abhängigkeiten, keine unzulässigen Aufwärts-Abhängigkeiten und keine
"God-Utility"-Übergriffe wurden im Rahmen der in dieser Session tatsächlich geprüften
Pfade gefunden. Das ist eine Aussage über die geprüften Pfade, nicht über das
gesamte Repository (siehe Abschnitt 25, offene Fragen).

---

## 6. Architectural Strengths

Durch wiederholte, unabhängige Anwendung über mehrere Findings hinweg **bewiesen**,
nicht nur behauptet:

- **Executor-Entkopplungs-Muster** (`await asyncio.to_thread(sync_fn, ...)`):
  unabhängig zweimal als Fix angewendet (FINDING-1 Cover, FINDING-7 Loudness),
  beide Male mit identischem, deterministisch verifiziertem Testmuster
  (Patch-und-Aufzeichnung statt Timing-Race). Bereits vorher konsistent für alle
  externen Client-Bibliotheken (`musicbrainzngs`, `pylast`, `lyricsgenius`)
  angewendet.
- **Atomares-Write-Muster** (`tmp_path` schreiben → `Path.replace()`):
  unabhängig dreimal vorgefunden/angewendet — ursprünglich in
  `utils/metadata_cache.py::store()`, dann repliziert für FINDING-5
  (`_save_video_id_index`) und FINDING-6 (`move_to_library`, dort als
  Copy-zu-Tmp+Rename-Variante für Cross-Filesystem-Fälle).
- **Cache-Check-vor-teuren-Calls**: `process_single_track()` prüft den Cache als
  Schritt 2, vor jedem externen Call — kein einziger unnötiger externer Call bei
  Cache-Hit vorgefunden (Phase 5 Abschnitt 13).
- **Concurrency-Limits werden tatsächlich durchgesetzt UND getestet**
  (`asyncio.Semaphore(3)`, `tests/test_download_concurrency_semaphore.py` mit
  `TestSemaphoreIsAModuleLevelSingleton` und
  `TestSemaphoreActuallyLimitsConcurrency`) — widerlegt eine in dieser Session
  aufgetretene veraltete Fehleinschätzung (Phase 5 Abschnitt 9).
- **Genre-Mapping als Singleton mit Einmal-Load**: YAML-Dateien werden nachweislich
  nicht pro Aufruf neu geladen (`SingletonMixin`, verifiziert Phase 5 Abschnitt 13).

---

## 7. Architectural Pressures

Was die sieben Findings **strukturell** offenlegen, nicht nur einzeln:

- Das Executor-Entkopplungs-Muster ist ein **Konvention, kein erzwungenes
  Invariant**. Es existiert kein Mechanismus (Test, Lint, Code-Review-Checkliste),
  der eine neue synchrone/blockierende Aufrufstelle in einer `async def`-Methode
  automatisch auffängt, bevor sie zu einem weiteren FINDING-N wird. FINDING-1 und
  FINDING-7 sind derselbe Fehler, an zwei verschiedenen Stellen, im Abstand von
  mehreren Engineering-Zyklen unabhängig gefunden — nicht durch Automatisierung,
  sondern durch manuelles Audit.
- Dasselbe gilt für das Atomic-Write-Muster: FINDING-5 und FINDING-6 sind
  strukturell derselbe Fehler (fehlende Crash-Sicherheit) an zwei unabhängigen
  Persistenz-Stellen. Eine dritte, bereits identifizierte, aber nicht behobene
  Instanz existiert im Cover-Cache (Abschnitt 9, AE-03).
- Das Ergebnis-/Fehlersemantik-Modell (FINDING-4) ist historisch gewachsen und
  uneinheitlich (Rückgabewert-Dict an einer Stelle, Exception an anderer) — der
  Fix hat das bewusst NICHT vereinheitlicht, sondern konsumentenseitig repariert,
  um die Regression-Risiken einer Producer-seitigen Änderung zu vermeiden
  (10 bestehende Retry-Tests). Das ist eine bewusste, dokumentierte Entscheidung,
  keine übersehene Inkonsistenz — aber sie bleibt als architektonischer Druck
  bestehen.

---

## 8. Async / Sync Architecture

**Beweis (FINDING-1, FINDING-7):** Das Muster
`blockierende Operation → asyncio.to_thread() → async bleibt responsiv` ist
zweimal unabhängig als korrekter Fix verifiziert (inkl. empirischer Messung: 146
von 147 Heartbeat-Ticks während einer echten 14,7-s-FFmpeg-Blockierung).

**Entscheidung: KEEP + DOCUMENT.** Das Muster wird als INV-01 (Abschnitt 17)
festgeschrieben. Eine automatisierte Erkennung (Lint-Regel, AST-Scan) wird **nicht**
eingeführt — würde False Positives bei absichtlich synchronen Utility-Funktionen
erzeugen und ist durch die Anti-Overengineering-Gate (Abschnitt 24) nicht
gerechtfertigt, solange nur zwei Vorfälle über die gesamte Projekthistorie
dokumentiert sind. Stattdessen: die verbleibenden, bereits in Phase 5 (Abschnitt 8)
gemessenen synchronen Aufrufe im Event-Loop-Kontext
(`shutil.copy2` in `move_to_library`, `mutagen`-Tag-Writing,
`_save_video_id_index`) bleiben bewusst ungewrappt, da ihr gemessener Kostenanteil
(< 20 ms) die Meaningful-Schwelle nicht erreicht — **ADD TEST GUARDRAIL ist für
diese drei Stellen nicht gerechtfertigt**, da kein Fehlerbild vorliegt.

---

## 9. Persistence Architecture

**Prüfung der Kandidaten-Invarianten:**

> Persistenter State darf niemals als teilweise geschriebene Datei sichtbar werden.

**Aktuelle Compliance:**

| Schreiber | Atomar? | Beleg |
|---|---|---|
| `utils/metadata_cache.py::store()` (Haupt-Cache) | ✅ Ja (Original-Implementierung, Vorbild) | tmp+rename |
| `services/metadata/cache.py::_save_video_id_index()` | ✅ Ja (FINDING-5) | tmp+rename |
| `utils/filenamefixer.py::move_to_library()` | ✅ Ja (FINDING-6) | copy-zu-tmp+rename, cross-fs |
| `services/metadata/cover_processor.py::_cache_set()` | ❌ **Nein** | `open(path, "wb")` direkt, kein tmp+rename (verifiziert, Zeile 840-848) |

> Ein Library-File darf erst nach vollständiger Fertigstellung als sichtbar gelten.

**Compliance:** ✅ Ja (FINDING-6-Fix: `tmp_target.replace(final_target)` erst nach
vollständigem `copy2`).

**Bewertung (ursprünglich, Stand vor Closure-Audit):** Der Cover-Cache ist die
einzige noch offene Nicht-Konformität. Blast Radius ist gering (Cover-Bytes sind
verlustfrei neu ladbar, kein Nutzer-sichtbarer Datenverlust wie bei FINDING-5/6) —
daher **kein** eigenständiges FINDING, sondern Evolution-Kandidat AE-03
(Abschnitt 19), Priorität DEFER.

> **⚠️ KORREKTUR (Closure-Audit, Abschnitt 26):** Diese Bewertung war **unvollständig**
> — sie prüfte nur die vier durch FINDING-5/6 bereits bekannten Schreiber, nicht das
> Repository repo-weit. Ein gezielter Sweep fand **mindestens acht weitere**
> nicht-atomare Schreiber kritischen States, u. a. `services/duplicate/cache.py`
> (Duplikat-Erkennungs-Index, P0), `services/metadata/auto_learn.py` (Mapping-Dateien
> — `auto_learned_genre.yaml`, `known_artists.yaml`, `auto_learned_artists.yaml`,
> ebenfalls P0 laut CLAUDE.md §10), `utils/lyrics_cache.py`,
> `services/statistik/play_history_repository.py` (dessen `load()`-Methode bereits
> ein `.corrupt.<timestamp>`-Recovery-Verfahren enthält — ein starkes Indiz, dass
> genau diese Nicht-Atomarität in der Vergangenheit bereits zu echter
> Datenkorruption geführt hat), sowie `handlers/enhanced_logger_menu_handler.py`,
> `handlers/admin/user_management_handler.py`, `utils/artist_map.py`. Details,
> Evidenz-Level und Neubewertung in Abschnitt 26.

Keine Persistenz-Framework-Einführung, keine Datenbank-Migration gerechtfertigt —
das Ein-Datei-pro-Eintrag-JSON-Modell skaliert nachweislich linear-konstant
(Phase 5 Abschnitt 12) bei aktueller/absehbarer Bibliotheksgröße.

---

## 10. Failure / Result Architecture

**Aus FINDING-4 (vollständig forensisch rekonstruiert):** MusicBot hat **kein**
einheitliches Ergebnis-Semantik-Modell. Drei koexistierende Mechanismen:

1. Exceptions für Programmierfehler/unerwartete Zustände (`raise ValueError(...)`
   in `handle_youtube_links()` bei `not download_result`).
2. Rückgabewert-Dicts mit `success`-Flag für erwartete/erschöpfte
   Fehlerzustände (`enhanced_download_with_retry()` gibt
   `{"success": False, "error": ...}` zurück statt zu raisen).
3. Aggregierte Wrapper-Objekte mit strukturell immer-`True`-Success
   (Playlist-Wrapper vor dem FINDING-4-Fix).

**Der FINDING-4-Fix hat dies bewusst NICHT vereinheitlicht** — er repariert
konsumentenseitig (`handle_youtube_links()`, `handle_playlist_success()`), ohne die
Produzentenseite (Retry-Loop-Rückgabewert-Contract) zu ändern, um die 10
bestehenden `RETRY-COVERAGE`-Tests nicht zu gefährden.

**Frage laut Auftrag:** *Hat MusicBot ein verständliches, einheitliches
Ergebnis-Semantik-Modell?* **Nein — und das ist nach Prüfung der Evidenz eine
akzeptable, keine zu behebende Situation.** Eine Vereinheitlichung (z. B. ein
globales `Result`-Objekt für die gesamte Pipeline) würde einen Producer-seitigen
Eingriff in bereits gut getestete, kritische Retry-/Download-Logik erfordern, ohne
dass ein aktuelles Finding dies fordert. **Entscheidung: REJECT** (globales
Result-Framework, siehe Anti-Overengineering-Gate Abschnitt 24) — **DOCUMENT**
stattdessen den bestehenden Dual-Contract explizit als akzeptierte Realität
(INV-04, Abschnitt 17: user-visible success muss tatsächlichen Erfolg
widerspiegeln — das ist die tatsächlich wichtige Garantie, unabhängig vom internen
Mechanismus, mit dem sie erreicht wird).

---

## 11. Error Architecture

**Korrektur einer fehlerhaften Dokumentationsannahme (siehe Abschnitt 15):**
Es existieren **zwei vollständig separate, parallele Error-Reporting-Systeme**,
beide aktiv in Produktion:

**System 1 — Domain-eigenes Reporting (Download-Pfad):**
`DownloadHandler.handle_download_failure()`, `handle_single_track_success()`,
`handle_playlist_success()` — sendet direkt eigene, domänenspezifische
Telegram-Nachrichten. Dieser Pfad kennt `EnhancedErrorHandler` nicht, ruft ihn
nirgends auf. FINDING-2, FINDING-3, FINDING-4 liegen alle in diesem System.

**System 2 — Zentraler Exception-Handler (`EnhancedErrorHandler`):**
in `bot.py:94` instanziiert, als PTB-`add_error_handler` registriert (`bot.py:104`,
fängt alle uncaught Exceptions im gesamten Bot ab), zusätzlich explizit aufgerufen
aus `rich_menu_handler.py` (Command-/Callback-Fehler, Zeile 623, 883, 959),
`rich_menu_system.py:1301` und `enhanced_status_handler.py:364`. Kategorisiert
Exceptions (`file_system`, `network`, `parsing`, ...), versucht Recovery-Strategien,
benachrichtigt den Nutzer mit kategorie-spezifischen Templates.

**Bewertung:** Die zwei Systeme überlappen sich nicht in denselben Codepfaden —
der Download-Flow hat eigene, spezifischere Fehlermeldungen (nötig, siehe
FINDING-4s Anforderung an korrekte Download-Ergebnis-Semantik), das Menü-/
Callback-System nutzt den generischen Handler für alles Nicht-Vorhergesehene.
Das ist **bewusste Schichtung, keine zufällige Duplikation** — technische,
operationale und User-Facing-Anliegen sind für den Download-Pfad domänenspezifisch
gelöst, für alles andere generisch abgefangen. **Keine Vereinheitlichung
gerechtfertigt.**

---

## 12. External Service Architecture

Konsistentes Muster: Timeout-Ownership beim jeweiligen Client, Blocking-Boundary
konsistent via `to_thread`/`aiohttp`, Concurrency-Control zentral im
`Semaphore(3)`. **Uneinheitlich: Retry-Ownership** (Phase 5 Abschnitt 7):

| Client | Retry |
|---|---|
| Genius | 3× `tenacity`, exponentiell |
| Cover-Provider | 2× `urllib3.Retry`, Backoff 0,5 |
| MusicBrainz | **keins** — `MUSICBRAINZ_RETRIES=4` in `config.py` definiert, aber **null Verwendungsstellen im gesamten Repository** (verifiziert per Grep) |
| Last.fm | keins, kein Config-Wert dafür vorhanden |

**Ist Standardisierung gerechtfertigt?** Nicht als generisches
`ExternalService`-Framework (Anti-Overengineering-Gate, Abschnitt 24 — explizit
abgelehnt). Aber der tote `MUSICBRAINZ_RETRIES`-Wert ist ein konkreter, benannter
Widerspruch zwischen Konfigurationsabsicht und Implementierung — Evolution-Kandidat
AE-04 (Abschnitt 19), Entscheidung REQUIRES DECISION (fachliche Frage: will man
MB-Retries, oder soll der tote Wert entfernt werden — keine rein architektonische
Entscheidung).

---

## 13. Cache / State Architecture

| State | Ownership | Lifecycle | Crash-Verhalten |
|---|---|---|---|
| Haupt-Metadata-Cache | `utils/metadata_cache.py` | Lazy pro Key, kein Preload | Atomar (Vorbild) |
| video_id_index | `services/metadata/cache.py` | Einmal-Load im `__init__`, In-Memory-Dict + Full-Rewrite je Store | Atomar seit FINDING-5 |
| Cover-Cache | `cover_processor.py` | Datei pro MD5-Key | **Nicht atomar** (AE-03) |
| Duplicate-Detection-State | `services/duplicate/cache.py` | **Nicht vertieft geprüft in dieser Session** | Unbekannt — siehe Abschnitt 25 |

**Frage laut Auftrag:** *Kann zukünftige Entwicklung dieses State-Modell sicher
erweitern, ohne versteckte Kopplung einzuführen?* Für Haupt-Cache und
video_id_index: **Ja**, beide sind bereits durch FINDING-5 auf ein konsistentes,
crash-sicheres Muster gebracht und durch Regressionstests geschützt. Für den
Duplicate-Detection-State: **nicht beurteilbar ohne weitere Prüfung** — als offene
Frage vermerkt (Abschnitt 25), nicht als Finding, da keine Evidenz für ein Problem
vorliegt.

Keine Datenbank-Migration gerechtfertigt (Anti-Overengineering-Gate).

---

## 14. Configuration Architecture

Zentral (eine `Config`-Klasse, `config.py`), konsistent konsumiert für die aktiv
genutzten Werte (`MAX_CONCURRENT_DOWNLOADS`, `MAX_PLAYLIST_ITEMS`, `MAX_DURATION` —
alle drei durchgesetzt und getestet, Phase 5 Abschnitt 9). Aber: mehrere tote
Konfigurationswerte angesammelt (`DOWNLOAD_TIMEOUT`, `YTDL_BASE_OPTIONS`/
`socket_timeout`, `MUSICBRAINZ_RETRIES`) — dieselbe Kategorie wie bereits in Phase 1
gefundene tote Configs. **Keine Redesign-Rechtfertigung** — Konfiguration ist
strukturell gesund, hat lediglich über die Projekthistorie Karteileichen
angesammelt. Evolution-Kandidat AE-05 (Abschnitt 19), Priorität LATER (P2,
kosmetisch).

---

## 15. Planned Components

### `handlers/enhanced_error_handler.py` — Status-Korrektur

`docs/archive/MusicBot_ENGINEERING_BASELINE_v3.md` (Zeile 64, 145) klassifiziert dieses
Modul als **"PLANNED / NOT INTEGRATED"**. Diese Aussage ist bei direkter
Code-Verifikation **für den überwiegenden Teil des Moduls falsch**:

- `EnhancedErrorHandler` wird in `bot.py:94` instanziiert
  (`create_enhanced_error_handler()`) und in `bot.py:104` als
  PTB-`add_error_handler` **aktiv registriert** — jeder unbehandelte Fehler im
  gesamten Bot läuft real durch dieses System.
- `set_error_handler()` propagiert die Instanz an `duplicate_handler`,
  `status_handler`, `navidrome_handler`, `user_mgmt_handler`, `logger_handler`,
  `test_handler`, `menu_system` (`rich_menu_handler.py:182-280`).
- Konkrete Aufrufe von `handle_callback_error()` (3 Stellen) und
  `handle_command_error()` (2 Stellen) existieren im Menü-/Callback-System.
- `ErrorHandlerAdminInterface` wird ebenfalls instanziiert (`bot.py:147`).

**Tatsächlich ungenutzt (0 Aufrufer außerhalb der eigenen Datei, verifiziert per
Grep) ist ausschließlich `ErrorHandlerIntegration`** — die
Decorator-Wrapper-Klasse (`wrap_command_handler`, `wrap_callback_handler`,
`wrap_menu_handler`).

**Widerspruch explizit benannt** (CLAUDE.md §29-Pflicht): Die Baseline-v3-Aussage
war entweder zum Zeitpunkt ihrer Erstellung bereits ungenau, oder die Integration
lag zu diesem Zeitpunkt bereits vor und wurde übersehen — `git log` zeigt, dass die
zentrale Integrationszeile (`add_error_handler`) bereits seit einem sehr frühen
Commit (`107c5a9`/Vorgänger) im Code steht, also nicht erst kürzlich hinzugefügt
wurde. Diese Session unternimmt keine rückwirkende Ursachenklärung dazu — nur die
Korrektur des aktuellen Zustands.

**Entscheidung: REDEFINE.** In Baseline v4:
- `EnhancedErrorHandler` + `ErrorHandlerAdminInterface` als **ACTIVE / INTEGRATED**
  führen.
- Nur `ErrorHandlerIntegration` bleibt **PLANNED / NOT INTEGRATED** — weiterhin
  NICHT löschen, NICHT als Dead Code klassifizieren (CLAUDE.md §20: kein Beweis für
  "niemand nutzt das mehr", da es sich um einen bewusst bereitgestellten
  Erweiterungspunkt für zukünftiges Decorator-basiertes Error-Wrapping handeln
  könnte, keine verwaiste Altlast).

---

## 16. Test Architecture

**Aktuell:** 1077 passed, 0 failed.

| Architektonisches Invariant | Regressionstest vorhanden? | Beleg |
|---|---|---|
| Event-Loop-Responsivität bei Blocking-Ops | Ja, je Fund einzeln (nicht generisch) | `test_enhanced_metadata_processor_cover_blocking.py`, `test_enhanced_metadata_processor_loudness_blocking.py` |
| Download-Fehler-Reporting-Korrektheit | Ja | `test_enhanced_metadata_processor_youtube_pipeline_failure_reporting.py` (FINDING-4) |
| Atomare Persistenz (Crash-Safety) | Ja, für 3 von 4 Schreibern | `test_metadata_cache_handler.py::TestVideoIdIndexAtomicWrite`, `test_filenamefixer.py::TestMoveToLibraryAtomicity` — **Cover-Cache (AE-03) ungetestet, da nicht-konform** |
| Concurrency-Limit | **Ja** (widerlegt eine anfängliche Fehleinschätzung in dieser Session) | `test_download_concurrency_semaphore.py` |
| Retry-Verhalten | Ja, 10 Tests | `test_download_utils_retry.py` (RETRY-COVERAGE) |

**Bewertung:** Testarchitektur ist auf Ebene einzelner Invarianten solide, aber
**nicht generisch** — jedes neue Blocking-/Atomarity-Finding braucht seinen eigenen,
von Grund auf neu geschriebenen Test nach demselben (bewährten) Muster. Das wird
NICHT als Lücke behandelt, die jetzt geschlossen werden muss (Anti-Overengineering-
Gate: ein generisches Test-Framework für "alle künftigen Blocking-Bugs" wäre
spekulativ) — sondern als dokumentiertes, akzeptiertes Wiederholungsmuster für
künftige Findings gleicher Bauart.

---

## 17. Architectural Invariants

| ID | Regel | Evidenz | Compliance | Enforcement | Regression Risk bei Verletzung |
|---|---|---|---|---|---|
| **INV-01** | Blockierende CPU-/I/O-Arbeit darf nicht direkt im Event-Loop-Thread laufen. | FINDING-1, FINDING-7 | ~~Vollständig~~ **KORRIGIERT (Abschnitt 26): PARTIALLY ENFORCED** — repo-weiter Sweep fand weitere ungewrappte Stellen, u. a. `services/metadata/auto_learn.py` (P0, im Haupt-Pipeline-Pfad) und `handlers/test_menu_handler.py` (bis zu 900s `subprocess.run()`, live im Bot registriert) | Manuelles Audit, kein automatisierter Guard | Bot friert für alle Nutzer ein (empirisch bis zu 14,7s pro Vorfall gemessen; bis zu 900s beim Test-Menu-Fall) |
| **INV-02** | Persistenter State, dessen Teilschreibung schädlich wäre, muss crash-sicher (atomar) geschrieben werden. | FINDING-5, FINDING-6, Vorbild `utils/metadata_cache.py` | ~~3 von 4 bekannten Schreibern konform~~ **KORRIGIERT (Abschnitt 26): VIOLATED** — mindestens 8 weitere nicht-konforme Schreiber gefunden, davon mehrere in P0-Bereichen | Muster-Wiederverwendung, kein automatisierter Guard | Korrupter/leerer State nach Absturz während Schreibvorgang — für `play_history_repository.py` bereits durch vorhandenen Corrupt-Recovery-Code indirekt belegt |
| **INV-03** | Ein Library-File darf erst nach vollständiger Fertigstellung als erfolgreich verschoben gelten. | FINDING-6 | Konform | `move_to_library()`-Regressionstests | Inkonsistenter Library-Zustand (halb kopierte Datei sichtbar) |
| **INV-04** | User-sichtbarer Erfolg muss tatsächlichen Verarbeitungserfolg widerspiegeln, unabhängig vom internen Fehler-Mechanismus (Exception vs. Rückgabewert). | FINDING-4 | Konform seit Fix | `test_..._youtube_pipeline_failure_reporting.py` | Nutzer glaubt an Erfolg, obwohl 0/N Tracks verarbeitet wurden (der ursprüngliche FINDING-4-Zustand) |

---

## 18. Architectural Debt

| Item | Klassifikation | Begründung |
|---|---|---|
| Cover-Cache nicht-atomarer Write | **ACTIVE**, aber niedrige Priorität | Verletzt INV-02, aber geringer Blast-Radius (selbstheilend durch Re-Fetch) |
| `MUSICBRAINZ_RETRIES` toter Config-Wert | **REQUIRES DECISION** | Fachliche, nicht rein technische Entscheidung nötig |
| `DOWNLOAD_TIMEOUT`, `YTDL_BASE_OPTIONS`/`socket_timeout` tote Configs | **ACCEPTABLE** | Kein Schaden, reine Aufräumarbeit, P2 |
| `ErrorHandlerIntegration` ungenutzt | **PLANNED** | Bewusst nicht als Debt klassifiziert — kein Beweis für Verwaisung |
| Baseline-v3-Fehleinschätzung von `enhanced_error_handler.py` | **REQUIRES DECISION → wird hier entschieden (Abschnitt 15, REDEFINE)** | Dokumentations-Debt, nicht Code-Debt |
| Fehlende Executor-/Atomarity-Guardrails als generisches Muster | **ACCEPTABLE** | Zwei bzw. drei Vorfälle über die gesamte Projekthistorie rechtfertigen noch keine Automatisierung |

---

## 19. Evolution Candidates

| AE-ID | Titel | Evidenz | Architektonischer Druck | Vorschlag | Komplexität | Regressionsrisiko | Priorität |
|---|---|---|---|---|---|---|---|
| AE-01 | INV-01/INV-02 explizit als dokumentierte Invarianten festschreiben (dieses Dokument) | FINDING-1, 5, 6, 7 (wiederholtes Muster) | Konvention ohne Erzwingung | Nur Dokumentation, kein Code | Trivial | Keins | **NOW** |
| AE-02 | `enhanced_error_handler.py`-Integrationsstatus in Baseline v4 korrigieren | Abschnitt 15 | Dokumentations-Fehlinformation | Nur Dokumentation | Trivial | Keins | **NOW** |
| AE-03 | Cover-Cache-Write atomar machen (identisches Muster zu FINDING-5) | Abschnitt 9 | INV-02-Verletzung | Kleiner, isolierter Fix analog FINDING-5 | Niedrig | Niedrig | LATER |
| AE-04 | `MUSICBRAINZ_RETRIES` verdrahten oder entfernen | Abschnitt 12 | Config-Implementierungs-Widerspruch | Fachliche Entscheidung nötig, dann kleiner Fix | Niedrig | Niedrig | NEXT (Entscheidung), dann LATER (Umsetzung) |
| AE-05 | Tote Config-Werte bereinigen (`DOWNLOAD_TIMEOUT`, `YTDL_BASE_OPTIONS`) | Abschnitt 14 | Kosmetisch | Löschung nach Bestätigung "kein Aufrufer" | Trivial | Keins | LATER |
| AE-06 | `services/duplicate/` Architektur-Charakterisierung nachholen | Abschnitt 13, 25 | Unbekannte Cache-Crash-Semantik | Eigenständige kleine Charakterisierungs-Session | Mittel (Recherche) | n/a | NEXT |

Kein Kandidat schlägt eine Neuschreibung, ein neues Framework oder eine
Microservice-Aufteilung vor — konsistent mit dem Ergebnis von Abschnitt 24.

---

## 20. Decision Matrix

| ID | Kandidat | Evidenz | Benefit | Komplexität | Risiko | Entscheidung |
|---|---|---|---|---|---|---|
| AE-01 | Invarianten dokumentieren | Stark (4 Findings) | Hoch (verhindert Wiederholung derselben Diskussion) | Trivial | Keins | **EVOLVE** (in diesem Dokument bereits umgesetzt) |
| AE-02 | Fehlerhandler-Status korrigieren | Stark (Code-Verifikation) | Hoch (verhindert falsche zukünftige Annahmen) | Trivial | Keins | **EVOLVE** (in diesem Dokument bereits umgesetzt) |
| AE-03 | Cover-Cache atomar | Mittel (analoge Findings) | Niedrig (geringer Blast-Radius) | Niedrig | Niedrig | **DEFER** |
| AE-04 | MusicBrainz-Retry-Entscheidung | Mittel | Niedrig-Mittel | Niedrig | Niedrig | **DEFER** (Freigabe für fachliche Entscheidung nötig) |
| AE-05 | Config-Cleanup | Schwach-Mittel | Niedrig (kosmetisch) | Trivial | Keins | **DEFER** |
| AE-06 | Duplicate-Detection-Charakterisierung | Schwach (Wissenslücke, kein Fehlerbild) | Unbekannt bis geprüft | Mittel | n/a | **DEFER** |

---

## 21. Architecture Decision Records

### ADR-AE-001 — Executor-Entkopplung als Invariante (INV-01), keine Automatisierung

**Status:** ACCEPTED

**Context:** FINDING-1 und FINDING-7 sind derselbe strukturelle Fehler an zwei
unabhängigen Stellen.

**Evidence:** `services/metadata/enhanced_metadata_processor.py:704-712` (Cover,
FINDING-1), `:811-817` (Loudness, FINDING-7), beide jetzt korrekt via
`asyncio.to_thread`.

**Decision:** Das Muster wird als Invariante dokumentiert (Abschnitt 17), aber
NICHT durch ein automatisiertes Lint/AST-Tool erzwungen.

**Alternatives:** (a) generisches Executor-Framework/Decorator, (b) statische
Analyse aller `async def` auf synchrone Bibliotheksaufrufe. Beide abgelehnt —
Aufwand steht in keinem Verhältnis zu zwei historischen Vorfällen.

**Consequences:** Künftige, ähnliche Bugs werden weiterhin nur durch manuelles
Audit (wie Phase 4/5 dieser Session) gefunden, nicht präventiv verhindert. Das ist
eine bewusst akzeptierte Grenze.

**Implementation Status:** NOT IMPLEMENTED (reine Dokumentationsentscheidung,
nichts zu implementieren).

---

### ADR-AE-002 — Atomare Persistenz als Invariante (INV-02), Cover-Cache als bekannte Ausnahme

**Status:** ACCEPTED (Invariante), Cover-Cache-Konformität DEFERRED

**Context:** FINDING-5 und FINDING-6 sind derselbe strukturelle Fehler an zwei
unabhängigen Persistenz-Stellen; eine dritte (Cover-Cache) ist bekannt, aber nicht
behoben.

**Evidence:** Abschnitt 9.

**Decision:** Invariante gilt repo-weit für State, dessen Teilschreibung schädlich
wäre. Cover-Cache bleibt bewusst non-konform, da selbstheilend (verworfene/korrupte
Cover-Datei wird beim nächsten Versuch einfach neu heruntergeladen — kein
dauerhafter Datenverlust wie bei FINDING-5/6).

**Alternatives:** Sofortiger Fix des Cover-Cache im Rahmen dieser Phase — abgelehnt,
da kein Freigabe-Auftrag für Implementierung in dieser Architektur-Phase vorliegt
(§3 Hard Immutability Rule) und kein demonstrierter Schaden vorliegt.

**Consequences:** AE-03 bleibt als offener, dokumentierter Punkt für eine künftige,
kleine, separat freizugebende Fix-Phase.

**Implementation Status:** NOT IMPLEMENTED.

---

### ADR-AE-003 — Kein einheitliches Result-Framework

**Status:** REJECTED

**Context:** FINDING-4 legte drei koexistierende Fehler-Semantik-Mechanismen offen.

**Evidence:** Abschnitt 10, FINDING-4-Forensic-Audit (5 Fix-Optionen verglichen,
Option A mit Exception-basierter Vereinheitlichung explizit verworfen wegen
Regressionsrisiko für 10 bestehende Tests).

**Decision:** Kein globales `Result`-Objekt/Framework für die gesamte Pipeline.
Stattdessen INV-04 (user-visible success = tatsächlicher Erfolg) als die
eigentlich wichtige, bereits durchgesetzte Garantie.

**Alternatives:** Producer-seitige Vereinheitlichung (abgelehnt, siehe oben),
schrittweise Migration einzelner Komponenten (kein aktueller Bedarf, keine
Evidenz).

**Consequences:** Der Dual-Contract (Exception vs. Rückgabewert) bleibt bestehen.
Künftige neue Komponenten sollten sich am jeweils lokal etablierten Muster
orientieren (Retry-Schicht: Rückgabewert; Programmierfehler: Exception), nicht an
einer nicht-existenten globalen Konvention.

**Implementation Status:** NOT IMPLEMENTED (Ablehnung, keine Umsetzung
vorgesehen).

---

### ADR-AE-004 — Korrektur des `enhanced_error_handler.py`-Integrationsstatus

**Status:** ACCEPTED

**Context:** Baseline v3 klassifiziert das gesamte Modul als PLANNED/NOT
INTEGRATED; Code-Verifikation zeigt aktive Integration für den überwiegenden Teil.

**Evidence:** Abschnitt 15.

**Decision:** Baseline v4 führt `EnhancedErrorHandler` + `ErrorHandlerAdminInterface`
als ACTIVE/INTEGRATED, nur `ErrorHandlerIntegration` bleibt PLANNED/NOT INTEGRATED.

**Alternatives:** Aktuelle (falsche) Klassifikation unverändert übernehmen —
abgelehnt, widerspricht CLAUDE.md §29 (Widersprüche explizit benennen).

**Consequences:** Zukünftige Sessions arbeiten mit einem korrekten Bild dieser
Komponente, statt die falsche Annahme fortzuschreiben.

**Implementation Status:** NOT IMPLEMENTED (reine Dokumentationskorrektur).

---

## 22. Evolution Roadmap

**NOW** (vor der nächsten Baseline, aber ohne Code-Änderung — reine
Dokumentation, in diesem Dokument bereits erledigt):
- AE-01 Invarianten dokumentiert (Abschnitt 17)
- AE-02 Fehlerhandler-Status korrigiert (Abschnitt 15)

**NEXT** (wertvoll, aber nicht dringend):
- AE-04 Fachliche Entscheidung zu `MUSICBRAINZ_RETRIES` einholen
- AE-06 `services/duplicate/` Architektur-Charakterisierung nachholen

**LATER** (valide Richtung, keine aktuelle Dringlichkeit):
- AE-03 Cover-Cache atomar machen
- AE-05 Tote Config-Werte bereinigen

**DEFERRED** (bewusst aktuell nicht gerechtfertigt):
- Alles in Abschnitt 24 (Anti-Overengineering-Gate)
- Producer-seitige Result-Vereinheitlichung (ADR-AE-003)
- Automatisierte Blocking-Call-Erkennung (ADR-AE-001)

---

## 23. Explicit Non-Decisions

- **Kein** globales Result-/Error-Framework (ADR-AE-003).
- **Keine** Vereinheitlichung der zwei parallelen Error-Reporting-Systeme
  (Abschnitt 11) — bewusste Schichtung, keine Duplikation.
- **Keine** automatisierte Executor-/Blocking-Erkennung (ADR-AE-001).
- **Kein** Persistenz-Framework, keine Datenbank-Migration (Abschnitt 9, 13).
- **Keine** Löschung von `ErrorHandlerIntegration` (Abschnitt 15) — bleibt PLANNED.
- **Keine** Löschung/Neuschreibung von `DownloadHandler` — mit 720 Zeilen und 12
  klar abgegrenzten Methoden aktuell kein Beleg für "God Class"-Probleme.
- **Kein** generisches `ExternalService`-Framework (Abschnitt 12, 24).
- **Keine** Microservice-Aufteilung, kein Event-Bus, kein Plugin-Framework, keine
  Dependency-Injection-Framework-Einführung, kein Message-Broker (Abschnitt 24).

---

## 24. Anti-Overengineering Gate

| Idee | Bewertung | Begründung |
|---|---|---|
| Event Bus | **NOT JUSTIFIED** | Kein Hinweis auf Bedarf für lose gekoppelte Publish/Subscribe-Kommunikation |
| Plugin-Framework | **NOT JUSTIFIED** | Keine Anforderung für Drittanbieter-Erweiterbarkeit |
| Dependency-Injection-Framework | **NOT JUSTIFIED** | Bestehende manuelle Konstruktor-Injection (`ArtistProcessor(artist_normalizer=...)` etc.) funktioniert nachweislich, keine Schmerzpunkte gefunden |
| Generic-Repository-Layer | **NOT JUSTIFIED** | Ein-Datei-pro-Eintrag-Cache-Modell ist bereits einfach und performant (Phase 5) |
| Message-Broker | **NOT JUSTIFIED** | Kein Multi-Prozess-/Multi-Service-Bedarf erkennbar |
| Datenbank-Migration | **NOT JUSTIFIED** | JSON-Cache skaliert nachweislich linear-konstant bei aktueller Größenordnung |
| Microservice-Split | **NOT JUSTIFIED** | Monolith mit klaren Schichtgrenzen funktioniert, kein Skalierungs-/Deployment-Problem belegt |
| Globales `Result`-Abstraktion | **NOT JUSTIFIED** | ADR-AE-003 |
| Universelle Downloader-Abstraktion | **NOT JUSTIFIED** | Spotify-Support bereits entfernt (siehe Commit-Historie), nur noch ein Downloader-Pfad aktiv |
| Große Service-Hierarchie | **NOT JUSTIFIED** | Bestehende Sub-Prozessor-Aufteilung in `services/metadata/` ist bereits angemessen granular |

Alle zehn Punkte: **NOT JUSTIFIED**, hiermit bewusst dokumentiert (siehe Abschnitt 23).

---

## 25. Open Architectural Decisions

Fragen, die dieser Audit **nicht** abschließend beantworten konnte — nicht, weil
sie unwichtig sind, sondern weil sie außerhalb der in dieser Session tatsächlich
geprüften Pfade liegen:

1. **`services/duplicate/cache.py` Crash-/Atomaritäts-Verhalten** — nicht
   geprüft. Sollte vor einer eventuellen v4-Freigabe kurz charakterisiert werden
   (AE-06), da Duplicate Detection laut CLAUDE.md §15 P0-kritisch ist.
2. **Vollständiger Repository-weiter Dependency-Graph** — diese Analyse hat sich
   auf die durch die sieben Findings tatsächlich berührten Pfade konzentriert,
   nicht auf jedes Modul im Repository (z. B. `handlers/menu/` im Detail,
   Navidrome-Scan-Trigger-Kette). Kein Hinweis auf Probleme dort, aber auch keine
   positive Verifikation.
3. **Warum wich die Baseline-v3-Aussage zu `enhanced_error_handler.py` von der
   Code-Realität ab?** — nicht rückwirkend untersucht (Abschnitt 15), da für die
   Architektur-Entscheidung selbst nicht erforderlich.

---

## Zusammenfassung

Die MusicBot-Architektur ist **strukturell gesund**. Die sieben in diesem
Engineering-Cycle geschlossenen Findings sind keine Symptome einer fehlerhaften
Architektur, sondern lokale, unabhängig behebbare Verletzungen von zwei zentralen,
mittlerweile explizit dokumentierten Invarianten (INV-01 Async/Blocking,
INV-02 Atomare Persistenz) sowie einer Ergebnis-Semantik-Lücke (INV-04), die
bewusst konsumentenseitig statt architekturweit behoben wurde. Nur eine kleine
Anzahl evidenzbasierter Weiterentwicklungen ist gerechtfertigt (AE-01 bis AE-06),
keine davon dringend, keine davon groß. Die wichtigste Einzelkorrektur dieses
Dokuments ist keine Code-Änderung, sondern eine Dokumentationskorrektur: der
`enhanced_error_handler.py`-Integrationsstatus in Baseline v3 war falsch.

> **Diese Zusammenfassung ist durch den Closure-Audit (Abschnitt 26) überholt.**
> Sie bleibt als historischer Zwischenstand erhalten. Die aktuelle,
> maßgebliche Bewertung ist Abschnitt 26.

---

## 26. Architecture Evolution Closure Verification

**Verification-Commit:** `9946cc8d6445a9537ef4ab18ba129d8f88f984c1` (main)
— weicht vom in der Aufgabenstellung erwarteten `b26166d` ab; Differenz ist der vom
Repository-Owner selbst erstellte und bereits committete Commit
„Isolierte Testumgebung für MusicBot eingerichtet" (`config_test.py`,
`run_test_bot.py`) — kein Produktionscode betroffen, explizit vom Owner als
bekannt/beabsichtigt bestätigt. Kein STOP-Grund.

**Regression:** `pytest tests/ -q` → **1077 passed, 0 failed** (erneut ausgeführt
gegen den Verification-Commit, nicht nur übernommen).

**Verification-Datum:** 2026-08-25.

### Kernfrage

> Ist die Architecture-Evolution-Phase ausreichend charakterisiert,
> evidenzbasiert und in sich konsistent, um ein Architecture Freeze zu erlauben?

**🔴 NOT READY FOR ARCHITECTURE FREEZE.**

Begründung in den folgenden Abschnitten — der Kernbefund: das ursprüngliche
Architecture-Evolution-Dokument hat INV-01/INV-02 nur für die durch FINDING-1–7
tatsächlich berührten Dateien verifiziert, nicht repo-weit, obwohl es implizit den
Eindruck einer (bis auf zwei benannte, bewusst deferrierte Ausnahmen)
weitgehend abgeschlossenen Prüfung erweckte. Der in dieser Closure-Phase erstmals
durchgeführte repo-weite Sweep widerlegt das.

### FINDING-1…7 Closure — erneut verifiziert

| Finding | Fix-Code noch vorhanden? | Test vorhanden? | Testlauf | Später reopened? |
|---|---|---|---|---|
| FINDING-1 (Cover-Blocking) | ✅ `enhanced_metadata_processor.py:704` `asyncio.to_thread` | ✅ `test_enhanced_metadata_processor_cover_blocking.py` | ✅ grün | Nein |
| FINDING-2 (Partial-Failure-Library) | ✅ `enhanced_metadata_processor.py:879` try/except um `write_tags()` nach `move_to_library()` | ✅ `test_metadata_processor_happy_path.py` (6 Tests) | ✅ 6 passed | Nein |
| FINDING-3 (Navidrome-Password-Log-Leak) | ✅ `navidrome_api.py`: `Config.mask_sensitive()` + `_CREDENTIAL_QUERY_PARAM_RE`-Redaction bei HTTPError/ConnectionError | ✅ `test_navidrome_api_logging.py` | ✅ 4 passed | Nein |
| FINDING-4 (Download Failure Reporting) | ✅ `download_handler.py:498,606` beide Fix-Stellen vorhanden | ✅ `test_..._youtube_pipeline_failure_reporting.py` | ✅ (Teil der 1077) | Nein |
| FINDING-5 (video_id_index atomic) | ✅ `services/metadata/cache.py:51` `tmp_path.replace(...)` | ✅ `TestVideoIdIndexAtomicWrite` | ✅ (Teil der 1077) | Nein |
| FINDING-6 (Cross-FS Library Finalization) | ✅ `filenamefixer.py:345` `tmp_target.replace(...)` | ✅ `TestMoveToLibraryAtomicity` | ✅ (Teil der 1077) | Nein |
| FINDING-7 (Loudness Event-Loop Blocking) | ✅ `enhanced_metadata_processor.py:818` `asyncio.to_thread` | ✅ `test_..._loudness_blocking.py` (3 Tests, inkl. Heartbeat-Beweis) | ✅ (Teil der 1077) | Nein |

**Alle sieben Findings bleiben CLOSED.** Kein Reopen. Direkt gegen aktuellen Code
verifiziert, nicht nur aus dem Dokument übernommen.

### INV-01…INV-04 — vollständige Neuverifikation

**INV-01 (Async/Blocking) — Klassifikation: PARTIALLY ENFORCED**

Ursprünglich bekannt/behoben: Cover (FINDING-1), Loudness (FINDING-7), alle
externen Clients (`to_thread`). Repo-weiter Sweep fand zusätzlich, **bisher nicht
dokumentiert**:

| Fund | Datei:Zeile | Kontext | Direkt verifiziert? | Materialität |
|---|---|---|---|---|
| `learn_genre`, `_save_known_artist`, `_save_alias` | `services/metadata/auto_learn.py:45,194,228` | `async def`, synchrones `open()`/`yaml.dump()` ungewrappt, aufgerufen via `await self.auto_learn_manager.learn_genre(...)` aus `process_single_track()` (`enhanced_metadata_processor.py:982,1020`) — **P0-Pfad, läuft bei jedem Track mit Auto-Learning** | ✅ Ja (Datei + Aufrufstelle direkt gelesen) | **Hoch** — regelmäßig ausgeführt, nicht nur Edge-Case |
| 5× `subprocess.run()` | `handlers/test_menu_handler.py:128,149,433,445,663` | `async def`-Methoden (`run_unit_tests`, `run_integration_tests`, `run_performance_tests`), Timeouts bis 900s, **live im Bot registriert** (`rich_menu_handler.py:180,356-371` — Callback-Handler `test_unit`/`test_integration`/`test_performance`) | ✅ Ja (Registrierung direkt verifiziert) | **Hoch bei Auslösung** — bis zu 15 Minuten Bot-weite Blockierung möglich, aber nur admin-getriggert (seltener als Auto-Learning) |
| `atomic_rename()` | `utils/file_ops.py:22,27,30` | `async def`, `mkdir()`/`os.rename()`/`shutil.move()` (Windows-Zweig) ungewrappt | Nicht selbst nachverifiziert (aus Sweep übernommen) | **Niedrig** — `os.rename()` ist eine sehr schnelle Syscall-Operation; kein Hinweis auf meaningful Cost analog Phase-5-Methodik (Abschnitt 4 des Phase-5-Dokuments: gemessener Cost + meaningful Impact nötig, hier keins gemessen) |
| `bot_restart_trigger.py` via `call_later` | `handlers/admin/bot_restart_handler.py:135-139` | `subprocess.run(..., timeout=15)` im Event-Loop-Callback | Nicht selbst nachverifiziert (aus Sweep übernommen) | **Niedrig** — läuft unmittelbar vor einem beabsichtigten Bot-Neustart, praktisch kein Nutzer-Impact |

**Bewertung:** Zwei der vier Funde (`auto_learn.py`, `test_menu_handler.py`) sind
**genuine, materiell relevante Verletzungen** — nicht Sub-20ms-Bagatellen wie die in
Phase 5 bewusst akzeptierten Fälle. Die anderen zwei (`file_ops.py`,
`bot_restart_trigger.py`) werden **nicht** als Blocker gewertet (geringe/keine
demonstrierte Auswirkung, konsistent mit der False-Positive-Gate-Methodik aus
Phase 5) — sie werden dokumentiert, nicht aufgebauscht.

**INV-02 (Atomic Persistence) — Klassifikation: VIOLATED**

Zusätzlich zum bereits bekannten Cover-Cache (AE-03) direkt verifiziert:

| Schreiber | Datei:Zeile | Kritikalität laut CLAUDE.md | Direkt verifiziert? |
|---|---|---|---|
| Duplicate-Detection-Cache (URL + Content) | `services/duplicate/cache.py:122-123,138-139` | **P0** (§15 Duplicate Detection) | ✅ Ja |
| Auto-Learn Mapping-Dateien (`auto_learned_genre.yaml`, `known_artists.yaml`, `auto_learned_artists.yaml`) | `services/metadata/auto_learn.py:136,214,252` | **P0** (§10 Mapping-Dateien sind Fachlogik) | ✅ Ja |
| Play-History | `services/statistik/play_history_repository.py:86-87` | P1 | ✅ Ja — **plus Indiz für bereits eingetretenen Schaden**: `load()` enthält bereits `.corrupt.<timestamp>`-Recovery-Code (Zeile 60-77), der nur Sinn ergibt, wenn genau diese Datei schon einmal korrupt vorgefunden wurde |
| Lyrics-Cache | `utils/lyrics_cache.py:69-70` | P0 (§16 Metadata) | ✅ Ja |
| Modul-Logger-Konfiguration | `handlers/enhanced_logger_menu_handler.py:100-101` | P2 | Nicht selbst nachverifiziert |
| User-Verwaltung (Rollen/Berechtigungen) | `handlers/admin/user_management_handler.py:50-51` | P1 (sicherheitsnah) | Nicht selbst nachverifiziert |
| Artist-Mapping (`case_preserve.yaml`, Override-File, `auto_learned_artists.yaml`) | `utils/artist_map.py:315-316,989-996,1061-1062` | P0 (§10) | Nicht selbst nachverifiziert |
| Statistik-Export | `services/statistik/statistics_calculator.py:217-218` | Niedrig (Einmal-Export, Zeitstempel im Dateinamen) | Nicht selbst nachverifiziert — als unkritisch eingestuft (deckt sich mit Sweep-Einschätzung) |

**Test-Coverage-Check (direkt verifiziert):** `tests/test_lyrics_cache.py` und
`tests/test_auto_learn.py` testen beide nur die **Lese-Seite** (Corrupt-JSON wird
beim Laden erkannt/gelöscht) bzw. reine Funktionskorrektheit — **keine** der
beiden Testdateien enthält einen Schreibunterbrechungs-/Crash-Test analog zu
`TestVideoIdIndexAtomicWrite` (FINDING-5) oder `TestMoveToLibraryAtomicity`
(FINDING-6). `services/duplicate/` hat überhaupt keine dedizierte Cache-Testdatei
für Atomarität (nur `test_duplicate_handler.py`, rein funktional).

**Bewertung:** Dies ist **kein** auf den Cover-Cache begrenztes Randproblem, wie
Abschnitt 9/17 des Originaldokuments nahelegte, sondern ein **repo-weites,
wiederkehrendes Muster** mit mindestens zwei direkt in P0-Bereichen bestätigten
Instanzen (Duplicate Detection, Auto-Learn-Mapping) plus einem Indiz für bereits
eingetretenen realen Schaden (Play-History). **Dies ist der primäre Freeze-Blocker.**

**INV-03 (Library Finalization) — Klassifikation: VERIFIED**

Keine neue Verletzung gefunden. `move_to_library()` bleibt die einzige
Finalisierungs-Stelle; kein alternativer Codepfad identifiziert, der dieselbe
Fehlerklasse unter anderer Route erneut einführen würde.

**INV-04 (User-visible Success) — Klassifikation: VERIFIED**

Zusätzlich zur ursprünglichen FINDING-4-Verifikation direkt nachvollzogen:
`_process_single_download()` (`download_utils.py:801-854`) **raised** bei jedem
internen Fehlschlag (`DownloadError`), statt einen falsch-positiven
`{"success": True, ...}`-Wrapper zu erzeugen — der äußere
`"success": True`-Wrapper (Zeile 320,350) ist dadurch vertrauenswürdig, da er nur
nach tatsächlich erfolgreichem Durchlauf erreicht wird. Kein versteckter zweiter
FINDING-4-artiger Fall gefunden.

### services/duplicate/ — Charakterisierung (Abschnitt 15 der Aufgabenstellung)

Deckt alle fünf in CLAUDE.md §15 geforderten Ebenen ab (URL, YouTube-ID via
URL-Normalisierung, Artist/Titel, Parser-Fallback, Library-Fallback) —
`DuplicateDetector.check_for_duplicates()` (`detector.py:71-156`). Aufrufer:
`klassen/download_handler.py:284` (Prüfung) und `:464` (Registrierung), beide
`async def`, beide ohne `to_thread`. Fehlerbehandlung beim Laden: leeres Dict bei
korrupter JSON-Datei (`cache.py:70-72,102-104`), **ohne** die korrupte Datei zu
löschen (Abweichung vom Haupt-Metadata-Cache-Muster). Keine externen
Abhängigkeiten (rein Dateisystem + lokaler Cache).

**Antwort auf die Kernfrage:** **NEW ARCHITECTURAL FINDING** (nicht "NO NEW
PRESSURE") — die Komponente verletzt sowohl INV-01 als auch INV-02 in einem laut
CLAUDE.md §15 explizit P0-kritischen Bereich, ohne dass dies zuvor dokumentiert war.

### Offene Fragen aus Abschnitt 25 — geschlossen

| Frage | Ergebnis |
|---|---|
| `services/duplicate/cache.py` Crash-/Atomaritäts-Verhalten | **CLOSED — NEW FINDING** (siehe oben; ändert Abschnitt 9/17 des Dokuments) |
| Vollständiger repo-weiter Dependency-Graph | **CLOSED — DEFERRED** (der in dieser Phase durchgeführte Sweep war gezielt auf INV-01/INV-02 beschränkt, kein vollständiger Graph; kein Hinweis auf weitere Probleme außerhalb dieses Scopes, aber auch keine erschöpfende Prüfung) |
| Warum wich Baseline-v3 bei `enhanced_error_handler.py` von der Code-Realität ab? | **CLOSED — DEFERRED** (für die Architekturentscheidung selbst nicht erforderlich, unverändert) |

### AE-01…AE-06 — Revalidierung

| ID | Status laut Original-Dokument | Revalidierung |
|---|---|---|
| AE-01 (Invarianten dokumentieren) | NOW | **IMPLEMENTED/VERIFIED** — bereits in diesem Dokument erledigt, jetzt jedoch inhaltlich korrigiert (Abschnitt 17) |
| AE-02 (Fehlerhandler-Status korrigieren) | NOW | **IMPLEMENTED/VERIFIED** — Abschnitt 15 unverändert korrekt, unabhängig erneut bestätigt (`bot.py:94,104`, `ErrorHandlerIntegration` weiterhin 0 externe Aufrufer) |
| AE-03 (Cover-Cache atomar) | DEFER | **Bleibt DEFER**, aber jetzt als Teilmenge des größeren AE-07 (siehe unten) zu sehen, nicht mehr isoliert |
| AE-04 (MusicBrainz-Retry-Entscheidung) | DEFER | **Bleibt DEFER**, unverändert, kein neuer Befund |
| AE-05 (Config-Cleanup) | DEFER | **Bleibt DEFER**, unverändert |
| AE-06 (`services/duplicate/`-Charakterisierung) | NEXT | **IMPLEMENTED** (in dieser Closure-Phase durchgeführt) — Ergebnis: NEW FINDING, nicht "keine Pressure" |

**Neue, durch diese Closure-Phase entstandene Kandidaten (nur dokumentiert, nicht
implementiert):**

| AE-ID | Titel | Evidenz | Priorität |
|---|---|---|---|
| **AE-07** | Repo-weites INV-02-Nachziehen: mindestens 8 nicht-atomare Schreiber (Duplicate-Cache, Auto-Learn-Mapping, Lyrics-Cache, Play-History, + 4 weitere) auf das FINDING-5/6-Muster (tmp+rename) heben | Abschnitt 26 dieses Dokuments | **HOCH** — insb. Duplicate-Cache und Auto-Learn-Mapping (P0), Play-History hat bereits Korruptions-Indiz |
| **AE-08** | `services/metadata/auto_learn.py` zusätzlich auf `asyncio.to_thread` umstellen (kombinierte INV-01+INV-02-Verletzung im Haupt-Pipeline-Pfad) | Abschnitt 26, `auto_learn.py:45,194,228` | **HOCH** — läuft im P0-Pfad bei jedem Auto-Learning-Track |
| **AE-09** | `handlers/test_menu_handler.py` Subprocess-Aufrufe auf `asyncio.to_thread`/`asyncio.create_subprocess_exec` umstellen | Abschnitt 26, `test_menu_handler.py:128,149,433,445,663` | **MITTEL** — nur admin-getriggert, aber bis zu 900s Blockierungsdauer im schlimmsten Fall |

Diese drei Kandidaten sind **nicht in dieser Phase zu implementieren** — sie
erfordern eine eigene, separat freizugebende Fix-Phase nach demselben Muster wie
FINDING-1–7 (Characterization → Freigabe → Fix → Regressionstest →
`git stash`-Verifikation).

### Anti-Overengineering-Gate — Revalidierung

Alle 10 ursprünglich abgelehnten Punkte (Abschnitt 24) bleiben **NOT JUSTIFIED**.
Die neuen Funde (AE-07/08/09) ändern daran nichts — sie sind Anwendungen
**bestehender, bereits bewährter** Muster (`to_thread`, tmp+rename) auf weitere
Stellen, kein Anlass für neue Abstraktionen/Frameworks.

### Contradiction Scan

| Widerspruch | Klassifikation |
|---|---|
| Baseline v3: `enhanced_error_handler.py` PLANNED/NOT INTEGRATED — Code: aktiv integriert | **DOCUMENTATION ERROR** (bereits in Abschnitt 15 korrigiert) |
| Architecture-Evolution-Dokument (Original): INV-02 "3 von 4 Schreibern konform, nur Cover-Cache offen" — Sweep: mindestens 8 weitere nicht-konforme Schreiber | **DOCUMENTATION ERROR** (Scope-Lücke — Prüfung war nicht repo-weit, obwohl implizit so dargestellt) — korrigiert in Abschnitt 9/17 |
| Architecture-Evolution-Dokument (Original): INV-01 "Vollständig" konform | **DOCUMENTATION ERROR** — korrigiert in Abschnitt 17 |
| AE-06 als "NEXT" mit erwartetem Ergebnis "vermutlich NO NEW PRESSURE" | **FALSE POSITIVE der Erwartung** — tatsächliches Ergebnis: NEW FINDING |

Keine Widersprüche zwischen Code und Tests, zwischen Invariante und
Implementierung außerhalb der oben genannten INV-01/INV-02-Fälle, oder zwischen
Architektur-Dokument-Ownership-Aussagen und tatsächlichen Aufrufern gefunden.

### Freeze Readiness Matrix

| Area | Verified | Finding | Action | Freeze Impact |
|---|---|---|---|---|
| Regression | ✅ | 1077/0 bestätigt gegen aktuellen HEAD | — | Kein Blocker |
| FINDING-1..7 | ✅ | Alle 7 CLOSED, kein Reopen | — | Kein Blocker |
| INV-01 | ✅ (korrigiert) | PARTIALLY ENFORCED — 2 materielle neue Verletzungen (AE-08, AE-09) | Dokumentiert, nicht gefixt | **Blocker** |
| INV-02 | ✅ (korrigiert) | VIOLATED — mind. 8 weitere Schreiber, davon 2 in P0 direkt verifiziert | Dokumentiert, nicht gefixt | **Blocker** |
| INV-03 | ✅ | Weiterhin VERIFIED | — | Kein Blocker |
| INV-04 | ✅ | Weiterhin VERIFIED, zusätzlich nachverifiziert | — | Kein Blocker |
| Architecture Map | ✅ | Grundsätzlich korrekt, aber unvollständig (`services/duplicate/` fehlte) | Ergänzt in Abschnitt 26 | Kein zusätzlicher Blocker (bereits in INV-01/02 enthalten) |
| Dependency Boundaries | ✅ | Keine neuen zirkulären/unzulässigen Abhängigkeiten gefunden | — | Kein Blocker |
| Async/Blocking (repo-weit) | ✅ | 2 materielle + 2 Bagatell-Funde | Siehe INV-01 | **Blocker** (enthalten in INV-01) |
| Persistence (repo-weit) | ✅ | 8 weitere nicht-atomare Schreiber | Siehe INV-02 | **Blocker** (enthalten in INV-02) |
| Library Finalization | ✅ | Keine neue Verletzung | — | Kein Blocker |
| Failure/Result Semantics | ✅ | Keine neue Inkonsistenz | — | Kein Blocker |
| Error Handling | ✅ | Status korrekt (ACTIVE für Kernklasse, PLANNED nur für `ErrorHandlerIntegration`) | — | Kein Blocker |
| External Services | ✅ | Keine neuen Funde | — | Kein Blocker |
| Cache/State | ✅ | Siehe INV-02 | — | **Blocker** (enthalten in INV-02) |
| Configuration | ✅ | Keine neuen Funde | — | Kein Blocker |
| Duplicate Services | ✅ | NEW FINDING (siehe oben) | Dokumentiert | **Blocker** |
| Planned Components | ✅ | Status bestätigt korrekt | — | Kein Blocker |
| Test Architecture | ✅ | Bestätigte Lücke: keine Atomarity-Tests für die 8 neuen Schreiber | Dokumentiert | Kein eigenständiger Blocker (Konsequenz von INV-02) |
| Evolution Candidates | ✅ | AE-01/02/06 IMPLEMENTED/VERIFIED, AE-03/04/05 unverändert DEFER, 3 neue (AE-07/08/09) | — | Kein zusätzlicher Blocker |
| Open Questions | ✅ | Alle 3 geschlossen | — | Kein Blocker |
| Anti-Overengineering | ✅ | Revalidiert, unverändert | — | Kein Blocker |

### 🔴 FINAL FREEZE DECISION: NOT READY FOR ARCHITECTURE FREEZE

**Echte Blocker (nicht aufgebläht — nur diese drei):**

1. **INV-02-Verletzung in P0-Bereichen** (`services/duplicate/cache.py`,
   `services/metadata/auto_learn.py`) — nicht-atomare Schreibvorgänge in
   Duplicate-Detection- und Mapping-Fachlogik, strukturell identisch zum bereits
   behobenen FINDING-5, aber unbehoben. `play_history_repository.py` liefert
   zusätzlich ein konkretes Indiz für bereits eingetretenen realen Schaden.
2. **INV-01-Verletzung im Haupt-Pipeline-Pfad** (`services/metadata/auto_learn.py`)
   — läuft bei jedem Auto-Learning-Track blockierend im Event-Loop, strukturell
   identisch zum bereits behobenen FINDING-7.
3. **Das Architecture-Evolution-Dokument selbst überstated seine eigene
   Vollständigkeit** — die Invarianten-Compliance-Tabellen in Abschnitt 9/17 waren
   nicht repo-weit verifiziert, obwohl sie so dargestellt waren. Ein Freeze auf
   Basis dieser (jetzt korrigierten) Aussagen wäre auf einer falschen
   Vollständigkeitsannahme erfolgt.

**Explizit NICHT als Blocker gewertet** (dokumentiert, aber bewusst nicht
aufgebläht): `utils/file_ops.py::atomic_rename()` (keine gemessene meaningful
Blockierung), `bot_restart_trigger.py` (Pre-Restart-Kontext, praktisch kein
Nutzer-Impact), die 6 nicht selbst nachverifizierten (nur aus dem Sweep
übernommenen) sekundären INV-02-Funde (Logger-Konfiguration, User-Management,
Artist-Mapping, Statistik-Export) — diese sollten vor einem erneuten
Freeze-Versuch zumindest stichprobenartig direkt verifiziert werden, gelten aber
nicht als eigenständige, bereits bestätigte Blocker.

**Weg zu 🟢 READY:** Eine separat freizugebende Fix-Phase für AE-07/AE-08/AE-09
(mindestens die P0-Teile: `services/duplicate/cache.py`,
`services/metadata/auto_learn.py`), nach demselben Characterization → Freigabe →
Fix → Regressionstest → `git stash`-Verifikation-Muster wie FINDING-1–7. Danach
ein erneuter, gezielter Closure-Check (kein vollständiger Re-Audit nötig) auf
INV-01/INV-02 für exakt diese Dateien.

### Deferred Items (bestätigt, unverändert gültig)

- AE-03 (Cover-Cache), AE-04 (MusicBrainz-Retry), AE-05 (Config-Cleanup) — DEFER,
  keine Änderung durch diese Closure-Phase.
- Die 6 nicht selbst nachverifizierten sekundären INV-02-Funde — DEFER bis zur
  Einzelverifikation.
- Vollständiger repo-weiter Dependency-Graph (über INV-01/02 hinaus) — DEFER,
  keine Evidenz für ein Problem, aber auch keine erschöpfende Prüfung.

---

## 27. Invariant Enforcement Audit — INV-01 / INV-02

**Audit-Datum:** 2026-08-25
**Verification-Commit:** `9946cc8d6445a9537ef4ab18ba129d8f88f984c1` (main)
**Regression vor Audit:** 1077 passed, 0 failed
**Regression nach Audit:** 1077 passed, 0 failed (unverändert — Audit hat keine Tests berührt)

Dieser Abschnitt ersetzt die vorläufigen INV-01/INV-02-Aussagen aus Abschnitt 26
durch eine vollständige, repo-weite Nachverifikation aller in Abschnitt 26 nur
teilweise übernommenen Sweep-Funde — plus zwei genuine, bisher unbekannte neue
Funde. Alle unten mit „direkt verifiziert" markierten Aussagen wurden persönlich
gegen den Code gelesen, nicht nur aus einem Recherche-Sweep übernommen.

### INV-01 — Vollständiges Kandidaten-Inventar

| Fund | Datei:Zeile | Caller (async?) | Gewrappt? | Telegram-erreichbar? | Dauer | Klassifikation |
|---|---|---|---|---|---|---|
| Auto-Learn (Genre+Artist, 3 Schreib- + 2 Lese-Helfer) | `services/metadata/auto_learn.py:45,161,194,228,270,319` | `process_single_track()` Z.982,1020 (`async def`) | Nein | Ja — läuft bei der Mehrheit der Tracks (Bedingungen sind Standardfälle, nicht Edge-Cases) | Mehrere synchrone YAML-Read+Write-Zyklen pro Track, nicht einzeln gemessen | **INV-01 VIOLATION** |
| `handlers/test_menu_handler.py` Subprocess (Performance-Tests) | `test_menu_handler.py:149-153` (`timeout=900`) | `_execute_test_run()` (`async def`), erreicht über `run_performance_tests` | Nein | Ja — Telegram-Callback `test_performance`, live registriert (`rich_menu_handler.py:180,366`) | **bis zu 900s** (Timeout-Parameter) | **INV-01 VIOLATION** (hohe Einzel-Severity, seltene Auslösung) |
| `handlers/admin/backup_handler.py::_dir_size()` | `backup_handler.py:521`, aufgerufen Z.98,99,145,173 | `show_main_menu`, `confirm_bot_backup`, `confirm_lib_backup` (alle `async def`) | Nein — **im Gegensatz zu** `_create_archive()` (Z.458), das korrekt via `run_in_executor` läuft (Z.207,259) | Ja — Backup-Menü-Aufruf/-Bestätigung | **9,46s real gemessen** (siehe unten) | **INV-01 VIOLATION** (real gemessen, hohe Severity) |
| `handlers/enhanced_status_handler.py::show_storage_status()` | `enhanced_status_handler.py:657-681` | `async def show_storage_status` | Nein | Ja — Status-Menü-Callback | Traversiert 5 Verzeichnisse **inkl. LIBRARY_DIR** — gleiche Größenordnung wie oben, plus 4 weitere Verzeichnisse | **INV-01 VIOLATION** (real gemessen, hohe Severity) |
| `services/duplicate/cache.py::_save_caches()` (INV-01-Aspekt) | `cache.py:106-141` | `register_download()`/`add_entry()` (sync), aufgerufen aus `handle_single_track_success()` (`async def`, `download_handler.py:464`) | Nein | Ja — nach **jedem** erfolgreichen Download, Kernpfad | Aktuell klein (kleiner Cache), aber siehe INV-02: unbeschränktes Wachstum | **INV-01 VIOLATION** (aktuell geringe Einzeldauer, aber siehe Wachstumsrisiko) |

**Direkt gemessen (read-only, keine Änderung an Produktionsdaten):** echte
`rglob("*")`+`stat()`-Traversierung von `/mnt/4tb/library` (realer, konfigurierter
`LIBRARY_DIR`-Pfad dieser Umgebung) — **2286 Dateien, 9,0 GB, 9,46 Sekunden**. Das
ist dieselbe Größenordnung wie die bereits bestätigte FINDING-7-Blockierung
(14,5s) und bestätigt, dass `_dir_size()` und `show_storage_status()` **keine
Bagatellfälle** sind, sondern reale, meaningful Blockierungen.

**Korrektur eines Fehlers aus Abschnitt 26:** `handlers/admin/bot_restart_handler.py`
wurde dort als „nicht selbst nachverifizierte, niedrig-Risiko INV-01-Verletzung"
geführt. Direkte Nachverifikation in diesem Audit zeigt: **das ist bereits
korrekt gefixt** — `bot_restart_handler.py:135-139` ruft den Subprocess-Call
bereits über `run_in_executor`/`to_thread` auf. **Kein Fund, sondern
Fehl-Klassifikation in Abschnitt 26 — hiermit korrigiert.**

### INV-01 — wichtige Nicht-Funde (explizit, mit Begründung)

| Kandidat | Begründung |
|---|---|
| `utils/file_ops.py::atomic_rename()` | `os.rename()`/`mkdir()` sind Syscalls im Mikrosekundenbereich; keine gemessene meaningful Kosten (False-Positive-Gate) |
| `handlers/admin/bot_restart_handler.py` | Bereits korrekt via `to_thread` gewrappt (s. o., Korrektur) |
| `cookie_handler.py` (`shutil.copy2`) | Nicht `async def`, **nirgends aus einem Handler aufgerufen** — toter Code, keine Telegram-Erreichbarkeit |
| `services/duplicate/detector.py::check_library_duplicate()` (`rglob`) | Der einzige produktive Aufrufer (`download_handler.py:284`) übergibt nur `url=`, nicht `raw_artist`/`raw_title` — Pfad ist im aktuellen Code **strukturell inaktiv**, kein aktiver Risikopfad |
| Alle `services/clients/*.py` (`requests`, `musicbrainzngs`, `pylast`) | Durchgängig korrekt via `to_thread`/`aiohttp` entkoppelt (bereits in Phase 5 verifiziert, hier erneut bestätigt) |
| `cover_processor.py`, `audio_enhancer.py` | Bereits bekannt/gefixt (FINDING-1, FINDING-7) |
| Log-/Cache-Verzeichnis-Globs (`*.log*`, `*.json`, nicht-rekursiv) | Flache Listings, keine Rekursion, kein Risiko vergleichbar zu `rglob` über die Library |
| `hashlib.md5()`-Aufrufe | Ausschließlich auf kurzen Strings oder 2×64KB-Chunks, keine Volldatei-Hashes |
| `move_to_library()`, `tag_writer.py`, `_save_video_id_index()` | Bereits in Phase 5 als Sub-20ms-Bagatellfälle akzeptiert, hier unverändert |

### INV-02 — Vollständiges Kandidaten-Inventar (alle Schreiber, nicht nur bereits bekannte)

| Schreiber | Datei:Zeile | Kritikalität | Schreibfrequenz | Atomar? | Lock? | Klassifikation |
|---|---|---|---|---|---|---|
| Duplicate-Cache (URL+Content) | `services/duplicate/cache.py:122-123,138-139` | **P0** (§15) | Nach jedem Download | Nein | Nein | **VIOLATED, RACE POSSIBLE** |
| Auto-Learn Mapping (3 Dateien) | `services/metadata/auto_learn.py:136,214,252` | **P0** (§10) | Bei jedem neu gelernten Artist/Genre | Nein | Nein | **VIOLATED, RACE POSSIBLE** |
| User-Verwaltung (Rollen/Rechte) | `handlers/admin/user_management_handler.py:50-51` | **P0/sicherheitsrelevant** — höchste Einzelkritikalität im gesamten Sweep (potenzieller Admin-Lockout) | Bei jeder Rollenänderung (5 Call-Sites) | Nein | Nein | **VIOLATED, RACE POSSIBLE** |
| Artist-Mapping (3 Dateien) | `utils/artist_map.py:315-316,988-995,1061-1062` | **P0** (§10) | Häufig im Betrieb | Nein | **Ja** (`threading.Lock`, `_write_lock`) | **VIOLATED (Atomarität), aber THREAD-SAFE WITH EXISTING SERIALIZATION** |
| Play-History | `services/statistik/play_history_repository.py:86-87` | P1 | Pro Wiedergabe-Event | Nein | Nein | **VIOLATED, RACE POSSIBLE** — plus Korruptions-Indiz (s. Abschnitt 26) |
| Lyrics-Cache | `utils/lyrics_cache.py:69-70` | P0-nah (§16 Metadata) | Pro neuem Lyrics-Treffer | Nein | Nein | **VIOLATED, RACE POSSIBLE** |
| Cover-Cache (Bytes + Metadaten-JSON) | `cover_processor.py:845` (`_cache_set`), `:861-862` (`_cache_best_cover`, neu benannt) | Niedrig — regenerierbar | Pro Cover-Fetch | Nein | Nein | VIOLATED, aber **REGENERABLE STATE** |
| Logger-Modul-Konfiguration | `enhanced_logger_menu_handler.py:100-101` | Niedrig | Selten (Admin-Konfiguration) | Nein | Nein | VIOLATED, aber **LOW-RISK NON-CRITICAL STATE** |
| Statistik-Export | `statistics_calculator.py:217-218` | Sehr niedrig | Nur auf Anfrage | Nein | Nein | VIOLATED, aber **NO FINDING** — Zeitstempel im Dateinamen, kein Überschreiben bestehender Daten, kein Datenverlust bei Absturz möglich (nur die eine neue Datei fehlt) |

**Test-Coverage:** Keine der neun Stellen hat einen Schreibunterbrechungs-Test
analog zu `TestVideoIdIndexAtomicWrite`/`TestMoveToLibraryAtomicity`. Klassifikation:
**NO COVERAGE** für alle neun, repo-weit einheitlich.

### Cross-Invariant Interaction — zentraler neuer Befund dieses Audits

**Wichtigste Erkenntnis dieser Phase, nicht in Abschnitt 26 enthalten:**

`auto_learn.py` und `services/duplicate/cache.py` enthalten **keinen einzigen
`await`-Punkt** zwischen dem Lesen und dem Zurückschreiben ihrer YAML-/JSON-Dateien
(direkt verifiziert: die komplette Read-Modify-Write-Sequenz in `learn_genre()`,
`_save_known_artist()`, `_save_alias()` sowie in `_save_caches()` läuft als ein
einziger synchroner Block). Das bedeutet: **aktuell** verhindert die
Single-Thread-Event-Loop-Kooperativität von Python/asyncio *zufällig*, dass zwei
gleichzeitig laufende Track-Verarbeitungen (bis zu 3 parallel dank
`MAX_CONCURRENT_DOWNLOADS=3`) sich bei diesen Schreibvorgängen in die Quere kommen
— es gibt schlicht keinen Punkt, an dem der Event-Loop zur anderen Coroutine
wechseln könnte, während der Block läuft.

**Das ist eine Falle für einen naiven Fix:** Würde man INV-01 für diese beiden
Komponenten nach dem bewährten FINDING-1/7-Muster beheben (`asyncio.to_thread()`
um den Aufruf legen), würde die Funktion in einem **echten OS-Thread** aus dem
Executor-Pool laufen. Bei `MAX_CONCURRENT_DOWNLOADS=3` können dann **echte,
parallele** Thread-Ausführungen entstehen — die aktuelle, zufällige Serialisierung
entfiele, und ein klassisches Lost-Update-Problem würde neu entstehen (Thread A
liest die YAML, Thread B liest dieselbe YAML vor As Schreibvorgang, A schreibt,
B schreibt seine eigene, veraltete Version darüber — As Eintrag geht verloren).

**`utils/artist_map.py` hat dieses Problem bereits vorausschauend gelöst:** Es
nutzt ein `threading.Lock()` (`self._write_lock`, Zeile 192, angewendet an vier
Stellen) um seine Schreibvorgänge — ein `threading.Lock` würde auch bei einer
künftigen `to_thread`-Auslagerung korrekt über echte OS-Threads hinweg
serialisieren. **Das ist das im Repository bereits vorhandene Referenzmuster für
eine korrekte kombinierte INV-01+INV-02-Lösung**, nicht neu zu erfinden.

**Konsequenz:** Ein künftiger Fix für `auto_learn.py`/`services/duplicate/cache.py`
darf **nicht** „nur zu `to_thread` + atomarer Replace" sein — er muss zusätzlich
ein `threading.Lock` nach dem `artist_map.py`-Vorbild einführen, sonst wird eine
Blockierung durch eine neue, subtilere Race Condition ersetzt.

### Thread-Safety-Klassifikation

| Komponente | Klassifikation | Beleg |
|---|---|---|
| `services/duplicate/cache.py` | **RACE POSSIBLE** (bei künftiger `to_thread`-Auslagerung) | Kein Lock, kein `await` im kritischen Abschnitt (aktuell zufällig sicher) |
| `services/metadata/auto_learn.py` | **RACE POSSIBLE** (bei künftiger `to_thread`-Auslagerung) | Kein Lock, gleiche Struktur |
| `utils/artist_map.py` | **THREAD-SAFE WITH EXISTING SERIALIZATION** | `threading.Lock` vorhanden und bereits korrekt angewendet |
| `services/statistik/play_history_repository.py` | **RACE POSSIBLE** (bei künftiger `to_thread`-Auslagerung) | Kein Lock gefunden |
| `handlers/admin/user_management_handler.py` | **RACE POSSIBLE** (bei künftiger `to_thread`-Auslagerung) | Kein Lock gefunden |
| `utils/lyrics_cache.py` | **RACE POSSIBLE** (bei künftiger `to_thread`-Auslagerung) | Kein Lock gefunden |

### Root-Cause-Analyse

**Beide Invarianten zeigen einen Enforcement Gap, keine isolierten
Implementierungsfehler:**

- **INV-01-Enforcement-Gap:** Das `to_thread`-Muster wurde bisher **nur an den
  Stellen angewendet, an denen es durch ein konkretes, spürbares Symptom
  auffiel** (FINDING-1: Nutzer bemerkten Verzögerungen bei Cover; FINDING-7: durch
  gezielte Performance-Charakterisierung gefunden). Es gibt **keinen
  systematischen Mechanismus**, der eine neue Verzeichnis-Traversierung oder einen
  neuen Subprocess-Call in einem Menü-Handler automatisch auffängt — selbst
  innerhalb derselben Datei wurde das Muster inkonsistent angewendet
  (`backup_handler.py`: Archivierung korrekt gewrappt, Größenberechnung direkt
  daneben nicht).
- **INV-02-Enforcement-Gap:** Das atomare Write-Muster (`utils/metadata_cache.py`)
  existiert seit dem ursprünglichen Cache-Design, wurde aber **nicht als
  verbindliche Konvention für neue Persistenz-Schreiber kommuniziert/durchgesetzt**
  — sieben von neun untersuchten Schreibern entstanden, ohne das bereits im
  selben Repository vorhandene Vorbild zu übernehmen. `artist_map.py`s
  `threading.Lock`-Nutzung zeigt: Concurrency-Bewusstsein war stellenweise
  vorhanden, aber ebenfalls nicht konsistent auf Crash-Safety ausgeweitet.

**Schlussfolgerung:** **Beide** Invarianten haben einen echten
Enforcement-Gap — keine Automatisierung/Konvention erzwingt sie. Das ist ein
architektonischer Befund, keine Reihe unabhängiger Coding-Fehler.

### Prioritisierung

| Fund | Severity | Begründung |
|---|---|---|
| `auto_learn.py` (INV-01+INV-02 kombiniert) | **P0** | P0-Bereich (§10 Mapping), hohe Ausführungsfrequenz, Cross-Invariant-Fallstrick bei naivem Fix |
| `services/duplicate/cache.py` (INV-01+INV-02 kombiniert) | **P0** | P0-Bereich (§15 Duplicate Detection), Kernpfad bei jedem Download, gleicher Cross-Invariant-Fallstrick |
| `user_management_handler.py::_save_users()` (INV-02) | **P0** | Sicherheitsrelevant, höchste Einzelkritikalität (Rollen/Rechte, potenzieller Lockout) |
| `handlers/admin/backup_handler.py::_dir_size()` (INV-01) | **P1** | Real gemessen 9,46s, aber nur bei Backup-Menü-Nutzung (seltener als Auto-Learn) |
| `handlers/enhanced_status_handler.py::show_storage_status()` (INV-01) | **P1** | Real gemessen ≥9,46s (+ 4 weitere Verzeichnisse), Status-Menü ist aber häufiger genutzt als Backup |
| `handlers/test_menu_handler.py` (INV-01) | **P1** | Bis zu 900s, aber nur admin-getriggert, seltene Auslösung |
| `utils/artist_map.py` (INV-02, Atomarität) | **P2** | Bereits Lock-geschützt (Concurrency), nur Crash-Safety fehlt |
| `play_history_repository.py`, `lyrics_cache.py` (INV-02) | **P2** | P1-Bereiche, aber kein P0-Fachlogik-Verlust wie bei Mapping/Duplicate |
| Cover-Cache, Logger-Config (INV-02) | **P3** | Regenerierbar/niedrige Kritikalität |
| Statistik-Export | **NO FINDING** | Siehe Begründung oben |

### Fix-Scope-Empfehlung (nur Empfehlung, keine Umsetzung)

| Gruppe | Empfehlung | Begründung |
|---|---|---|
| `auto_learn.py` + `services/duplicate/cache.py` | **FIX SEPARATELY, gemeinsame Phase** | Teilen denselben Root-Cause (fehlendes Lock + fehlende Atomarität) und denselben Fix-Pattern (`to_thread` + `threading.Lock` nach `artist_map.py`-Vorbild + tmp+replace nach `metadata_cache.py`-Vorbild) — sollten in EINER Phase behandelt werden, nicht als Großrefactor, sondern als zwei strukturell identische, kleine Fixes analog FINDING-5/6/7 |
| `user_management_handler.py` | **FIX SEPARATELY** | Höchste Einzelkritikalität, aber anderer Root-Cause-Bereich (Admin/Security, nicht Metadata-Pipeline) — eigene kleine Fix-Phase, gleiches tmp+replace-Muster |
| `backup_handler.py::_dir_size()` + `enhanced_status_handler.py::show_storage_status()` | **FIX SEPARATELY, gemeinsame Phase** | Beide reine INV-01-Fälle (kein INV-02-Aspekt), identischer Fix (`to_thread`/`run_in_executor` um die bestehende Funktion, exakt wie bei `_create_archive()` in derselben Datei bereits vorgemacht) |
| `test_menu_handler.py` | **DOCUMENT / DEFER** | Nur admin-getriggert, geringste Frequenz aller P1-Funde — kann wenn Kapazität da ist mit erledigt werden, ist aber kein eigenständiger Dringlichkeitstreiber |
| `artist_map.py`, `play_history_repository.py`, `lyrics_cache.py` | **FIX IN SAME PHASE wie AE-07** (aus Abschnitt 26) | Reine Atomaritäts-Nachrüstung nach `metadata_cache.py`-Vorbild, kein INV-01-Aspekt |
| Cover-Cache, Logger-Config | **DOCUMENT / DEFER** | Regenerierbar/niedriges Risiko |
| Statistik-Export | **INTENTIONAL EXCEPTION** | Kein Fix nötig — Design ist bereits sicher (Zeitstempel-Einmaldateien) |

**Kein einziger Fund rechtfertigt einen großen Refactor.** Alle Fixes sind
kleine, lokale, nach bereits im Repository bewährten Mustern (`to_thread`,
`threading.Lock`, tmp+`Path.replace()`) — konsistent mit CLAUDE.md §18
(Refactoring-Regel: kein großer Refactor als erste Reaktion).

### Verbleibende Unbekannte

- Ob `handlers/enhanced_logger_menu_handler.py` und
  `services/statistik/statistics_calculator.py` weitere, hier nicht geprüfte
  Aufrufstellen mit höherer Frequenz haben als angenommen — als niedrige
  Priorität eingestuft, aber nicht erschöpfend auf alle Call-Sites geprüft.
- Ob `services/duplicate/detector.py::check_library_duplicate()`'s `rglob`-Pfad
  in einer zukünftigen Erweiterung (z. B. Nutzung von `raw_artist`/`raw_title`)
  aktiviert werden könnte — aktuell strukturell inaktiv, aber nicht durch einen
  Test abgesichert, der ein versehentliches Aktivieren verhindern würde.
- Tatsächliche Traversierungskosten für `DOWNLOAD_DIR`, `DATA_DIR`, `LOG_DIR`,
  `TEMP_DIR` (die 4 weiteren Verzeichnisse in `show_storage_status()`) wurden
  nicht einzeln gemessen — nur `LIBRARY_DIR` wurde real gemessen (9,46s).

### Finaler Status

**🔴 INVARIANT VIOLATIONS REQUIRE FIX PHASE**

Nicht „🟡 PARTIALLY ENFORCED" — die Kombination aus (a) real gemessenen,
mehrsekündigen Blockierungen in zwei zusätzlichen, Telegram-erreichbaren
Menü-Pfaden, (b) zwei P0-Bereichs-Verletzungen von INV-02 mit einem konkreten
Korruptions-Indiz (Play-History) und (c) einem neu identifizierten
Cross-Invariant-Risiko, das einen naiven Fix gefährlich machen würde, übersteigt
die Schwelle für „teilweise durchgesetzt" — es handelt sich um einen bestätigten,
architektonischen Enforcement-Gap für beide Invarianten.

**Empfohlene nächste Phase:** Eine (oder mehrere kleine, thematisch gruppierte)
Fix-Phase(n) nach dem etablierten Characterization → Freigabe → Fix →
Regressionstest → `git stash`-Verifikation-Muster, beginnend mit den drei P0-Funden
(`auto_learn.py`, `services/duplicate/cache.py`, `user_management_handler.py`),
danach die beiden P1-INV-01-Funde (`backup_handler.py`, `enhanced_status_handler.py`).
Kein Baseline v4, kein Architecture Freeze vor Abschluss dieser Fix-Phase(n) und
einem gezielten Re-Check dieses Abschnitts.

---

## 28. INV-01 / INV-02 Enforcement Fix Phase

**Datum:** 2026-08-25
**Verification-Commit (vor der Phase):** `9946cc8` (main)
**Regression vor der Phase:** 1077 passed, 0 failed
**Regression nach der Phase:** **1092 passed, 0 failed** (+15 neue,
genuine Regressionstests: 4 P0-A + 3 P0-B + 4 P0-C + 2 P1-Backup + 2 P1-Status)

Scope: alle in Abschnitt 27 als P0/P1 klassifizierten Kandidaten. P2/P3 wurden
nicht angefasst (Absolute Rules). Jeder Fix folgte dem Muster
Charakterisieren → Regressionstest schreiben → Fehlschlag gegen ungefixten
Code beweisen (`git stash`) → Fix implementieren → Test erneut gruen →
umgebende Tests gruen.

### P0-A — `services/metadata/auto_learn.py` (INV-01 + INV-02)

**Root Cause:** Alle drei Schreibpfade (`learn_genre`, `_save_known_artist`,
`_save_alias`) liefen synchron im Event-Loop-Thread, direktes `open(mode="w")`
ohne Atomaritaet. Kombiniert mit dem Cross-Invariant-Risiko: kein `await`
zwischen Lesen und Schreiben bedeutete, dass asyncios kooperatives Scheduling
zufaellig serialisierte - ein naiver `to_thread()`-Fix ohne Lock haette eine
echte Lost-Update-Race zwischen den bis zu 3 gleichzeitigen Downloads
eingefuehrt.

**Fix:**
- Neue Modul-Klasse `_InlineListDumper` (vorher lokal dupliziert in
  `learn_genre()`, jetzt einmalig).
- `self._write_lock = threading.Lock()` im Konstruktor - Vorbild
  `utils/artist_map.py::_write_lock`.
- Gemeinsame `_write_yaml_atomic()`-Hilfsmethode (tmp-Datei + `Path.replace()`,
  Vorbild `utils/metadata_cache.py::store()`).
- Drei neue private Sync-Methoden (`_write_genre_entry_sync`,
  `_write_known_artist_sync`, `_write_alias_sync`), die je unter
  `self._write_lock` lesen, per Double-Check pruefen (Race-Schutz gegen
  Vorab-Check-vs-Lock-Erwerb-Luecke), modifizieren und atomar schreiben.
- `learn_genre()`/`_save_known_artist()`/`_save_alias()` rufen diese Methoden
  jetzt via `await asyncio.to_thread(...)` auf statt synchron direkt.

**Regressionstests** (`tests/test_auto_learn_invariant_fix.py`, 4 Tests):
1. `test_write_is_routed_through_asyncio_to_thread` - deterministischer
   to_thread-Beweis.
2. `test_interrupted_write_leaves_previous_valid_yaml_untouched` - INV-02,
   Schreibunterbrechung via `monkeypatch` auf `yaml.dump`.
3. `test_concurrent_writes_without_lock_can_lose_an_update` - beweist die
   allgemeine Schwachstellen-Klasse mit `threading.Barrier`-erzwungenem
   Interleaving (2 von 2 Eintraegen ueberleben NICHT).
4. `test_concurrent_writes_through_manager_preserve_all_entries` - beweist,
   dass der tatsaechliche Fix (Lock + to_thread) unter 8 echten parallelen
   `asyncio.gather()`-Aufrufen alle Eintraege erhaelt.

**Pre-Fix-Beweis:** `git stash` auf `services/metadata/auto_learn.py` -> Test 1
und 2 schlugen exakt erwartungsgemaess fehl (`yaml_map` leer,
`assert 0 >= 7.5`-analoge fehlende to_thread-Registrierung). Zusaetzlich wurde
die Diskriminierungskraft von Test 4 direkt bewiesen: mit einem
`_NullLock`-Monkeypatch (Lock deaktiviert, to_thread aktiv) gingen real **5
von 8 Eintraegen** durch eine Lost-Update-Race verloren, plus ein
Tmp-Datei-Kollisionsfehler trat auf - der Lock ist nachweislich notwendig UND
ausreichend.

**Bestehende Tests:** `tests/test_auto_learn.py` (14 Tests) unveraendert
gruen - Verhalten/Signaturen vollstaendig erhalten.

**Status: FIXED, VERIFIED.**

### P0-B — `services/duplicate/cache.py` (INV-02; INV-01 bewusst zurueckgestellt)

**Root Cause:** `_save_caches()` schrieb `url_duplicates.json`/
`content_duplicates.json` per direktem `open(mode="w")`, kein Atomaritaets-
Schutz - P0-kritischer Bereich (CLAUDE.md §15).

**Scope-Entscheidung (dokumentiert statt erzwungen, wie von Abschnitt 11 der
Fix-Phase-Vorgabe erlaubt):** INV-01 wurde fuer diese Komponente **nicht**
behoben. Eine `to_thread()`-Umstellung haette eine Async-Kaskade durch
`DuplicateDetector` (5 Methoden), `EnhancedDuplicateHandler`
(Telegram-Praesentationsschicht) und zwei Aufrufstellen in
`klassen/download_handler.py` erzwungen - eine "mass conversion of
synchronous functions to async", explizit durch die Absolute Rules dieser
Phase verboten. Die tatsaechliche Blockierungsdauer ist bei den hier
typischen Cache-Groessen nicht als meaningful gemessen (im Gegensatz zu
`backup_handler.py`/`enhanced_status_handler.py`, real bei 9,46s gemessen).
Diese Entscheidung ist in einem ausfuehrlichen Docstring an `_save_caches()`
selbst dokumentiert.

**Fix:** `_save_caches()` nutzt jetzt `_write_json_atomic()` (tmp-Datei +
`Path.replace()`) fuer beide Dateien. Da `add_entry()`/`_save_caches()`
weiterhin vollstaendig synchron ohne `await` dazwischen laufen, aendert der
atomare Write nichts an der bestehenden (zufaelligen) Serialisierung - **keine
neue Race Condition eingefuehrt**.

**Regressionstests** (`tests/test_duplicate_cache_atomic_persistence.py`,
3 Tests): Schreibunterbrechung via `monkeypatch` auf `json.dump`, Beweis dass
die vorherige gueltige Datei erhalten bleibt, kein Leftover-Tmp-File,
erfolgreiches Schreiben funktioniert unveraendert. Kein
Concurrent-Update-Test noetig (siehe Scope-Entscheidung oben - keine
Aenderung des Concurrency-Modells).

**Pre-Fix-Beweis:** `git stash` -> `url_duplicates.json` wurde bei simuliertem
Absturz auf leeren String (`''`) truncatet statt den vorherigen Inhalt zu
behalten - Test schlug exakt daran fehl.

**Bestehende Tests:** `tests/test_duplicate_handler.py` (14 Tests) unveraendert
gruen.

**Status: FIXED (INV-02), VERIFIED. INV-01 explizit DEFERRED (siehe
Scope-Entscheidung) - kein neuer Evolution-Kandidat noetig, da bereits als
AE-Punkt in Abschnitt 27 relevant.**

### P0-C — `handlers/admin/user_management_handler.py::_save_users()` (INV-02)

**Root Cause:** `data/user_data.json` (Rollen/Berechtigungen,
sicherheitsrelevant - hoechste Einzelkritikalitaet im gesamten INV-02-Sweep)
wurde per direktem `open(mode="w")` geschrieben. Kein INV-01-Aspekt (Methode
nicht in der INV-01-Tabelle von Abschnitt 27 gelistet - kleine, seltene,
synchrone Schreibvorgaenge ohne meaningful Blockierungskosten).

**Fix:** `_save_users()` nutzt jetzt write-tmp + `Path.replace()`. Bei
Fehlschlag wird die Tmp-Datei bereinigt UND der In-Memory-Cache
(`self.user_data_cache`) bleibt auf dem alten, gueltigen Stand (kein stiller
RAM/Disk-Widerspruch).

**Regressionstests**
(`tests/test_user_management_atomic_persistence.py`, 4 Tests): Owner-Eintrag
bleibt nach simuliertem Absturz erhalten (Lockout-Szenario direkt
nachgestellt), kein Leftover-Tmp-File, In-Memory-Cache bleibt bei
Fehlschlag konsistent zum alten Diskstand, erfolgreicher Schreibvorgang
aktualisiert Datei und Cache korrekt.

**Pre-Fix-Beweis:** `git stash` -> der Owner-Eintrag (`{"111": {"role":
"owner", ...}}`) wurde bei simuliertem Absturz vollstaendig durch einen
leeren String ersetzt - der reale Lockout-Mechanismus, den dieser Fund
beschrieb, wurde damit direkt reproduziert.

**Bestehende Tests:** `tests/test_user_management_handler.py` (27 Tests)
unveraendert gruen.

**Status: FIXED, VERIFIED.**

### P1 — `handlers/admin/backup_handler.py::_dir_size()` (INV-01)

**Root Cause:** `_dir_size()` (rglob+stat) lief an drei Stellen
(`show_main_menu`, `confirm_bot_backup`, `confirm_lib_backup`) ungewrappt
direkt im Event-Loop-Thread - trotz eines irrefuehrenden Kommentars
("nicht-blockierend schaetzen"). Die eigentliche Archivierung
(`_create_archive`) war im selben File bereits korrekt via
`run_in_executor()` gewrappt - ein nur zur Haelfte angewendeter Fix.

**Fix:** Alle drei Aufrufstellen nutzen jetzt
`await asyncio.get_event_loop().run_in_executor(None, self._dir_size, ...)` -
identisches Muster wie das bereits bestehende `_create_archive()`-Vorbild im
selben File.

**Regressionstests** (`tests/test_backup_handler_event_loop_blocking.py`,
2 Tests): deterministischer `run_in_executor`-Routing-Beweis (Patch am
tatsaechlich verwendeten Loop-Objekt, nicht `asyncio.get_event_loop()` vor
`asyncio.run()` - das waere ein anderes Loop-Objekt gewesen), Heartbeat-Test
mit kontrolliertem synchronen Stand-in fuer die reale 9,46s-Blockierung.

**Pre-Fix-Beweis:** `git stash` -> Heartbeat-Test lieferte 0 Ticks (Event-Loop
komplett eingefroren), Routing-Test fand keinen `_dir_size`-Aufruf im
Executor.

**Bestehende Tests:** `tests/test_backup_handler.py` (18 Tests) unveraendert
gruen.

**Status: FIXED, VERIFIED.**

### P1 — `handlers/enhanced_status_handler.py::show_storage_status()` (INV-01)

**Root Cause:** Inline-Traversierung (rglob+stat) ueber 5 Verzeichnisse
inklusive `LIBRARY_DIR` direkt im Event-Loop-Thread - real gemessen 9,46s
allein fuer die Library.

**Fix:** Die Traversierungs- und Text-Aufbau-Logik wurde in eine neue
`@staticmethod _build_storage_report(directories)` extrahiert und ueber
`await asyncio.get_event_loop().run_in_executor(...)` aufgerufen -
konsistent mit dem `backup_handler.py`-Muster.

**Regressionstests**
(`tests/test_enhanced_status_handler_event_loop_blocking.py`, 2 Tests):
identische Methodik wie beim Backup-Handler.

**Pre-Fix-Beweis:** `git stash` -> beide Tests schlugen fehl, da
`_build_storage_report` auf dem ungefixten Code gar nicht existiert
(`AttributeError`) - der Refactor selbst ist Teil des Fixes, eindeutiger
Nicht-Bestehen-Beweis.

**Bestehende Tests:** `tests/test_enhanced_status_handler.py` (14 Tests)
unveraendert gruen (inkl. der bereits bestehenden
`TestShowStorageStatus`-Klasse).

**Status: FIXED, VERIFIED.**

### `handlers/test_menu_handler.py` — bewusst NICHT gefixt (Reklassifikation)

In Abschnitt 27 als P1 gefuehrt (Severity-Tabelle), aber in derselben
Sektion bereits mit "DOCUMENT / DEFER" fuer den Fix-Scope empfohlen. Diese
Fix-Phase bestaetigt diese Entscheidung explizit statt sie stillschweigend zu
uebernehmen: admin-only-getriggert (kein normaler Nutzerpfad), seltenste
Ausloese-Frequenz aller P1-Funde, reines Test-/Dev-Feature. **Reklassifiziert
auf P2 (DEFER)** - kein Fix in dieser Phase, keine neue Kategorie noetig, da
bereits in Abschnitt 27 als niedrigste P1-Prioritaet mit Fix-Scope-Empfehlung
DEFER gefuehrt.

### Cross-Invariant-Verifikation (Abschnitt 17 der Fix-Phase-Vorgabe)

**INV-01:** Alle fuenf P0/P1-INV-01-Aspekte behoben (P0-A, P1-Backup,
P1-Status) bzw. bewusst zurueckgestellt (P0-B, dokumentiert) oder
reklassifiziert (test_menu_handler.py). Keine der Aenderungen hat eine
bestehende, bereits korrekt gewrappte Stelle beruehrt.

**INV-02:** Alle drei P0-INV-02-Schreiber (auto_learn.py x3 Dateien,
duplicate/cache.py x2 Dateien, user_management_handler.py x1 Datei) jetzt
atomar. Kein bestehender atomarer Schreiber wurde veraendert.

**Race-Analyse - zentrale Frage laut Fix-Phase-Vorgabe:** *"Did moving
blocking persistence work off the event loop introduce a race that did not
previously exist?"* **Nein - explizit verifiziert:**
- P0-A (`auto_learn.py`): einzige Komponente, die tatsaechlich zu
  `to_thread()` migriert wurde UND persistente Schreibvorgaenge enthaelt -
  hier wurde das `threading.Lock`-Muster (Vorbild `artist_map.py`) bewusst
  UND nachweislich (Test 3+4, inkl. Lock-Deaktivierungs-Beweis) eingefuehrt,
  um genau diese Race zu verhindern.
- P0-B (`duplicate/cache.py`), P0-C (`user_management_handler.py`): kein
  `to_thread()` eingefuehrt, daher strukturell keine neue Race moeglich -
  Concurrency-Modell unveraendert.
- P1-Backup, P1-Status: `_dir_size()`/`_build_storage_report()` sind reine
  Lesevorgaenge (keine Schreiboperation, kein gemeinsamer mutierbarer
  State) - `to_thread`/`run_in_executor` kann hier strukturell keine
  Race einfuehren, da nichts persistiert oder gemeinsam mutiert wird.

### Tests

**Hinzugefuegt:** 15 neue Tests in 5 neuen Dateien (siehe oben).
**Geaendert:** keine bestehenden Tests geaendert.
**Volle Regression:** `pytest tests/ -q` -> **1092 passed, 0 failed**
(1077 + 15, alle 15 durch `git stash`-Beweis als echte Regressionsw-Guards
verifiziert).

### Verbleibende Findings (nur P2/P3, nicht Teil dieser Phase)

- AE-03 (Cover-Cache atomar) - P3, unveraendert DEFER.
- AE-04 (MusicBrainz-Retry-Entscheidung) - P2, unveraendert DEFER.
- AE-05 (Config-Cleanup) - P3, unveraendert DEFER.
- `utils/artist_map.py` (INV-02, Atomaritaet - bereits Lock-geschuetzt) - P2,
  unveraendert DEFER.
- `play_history_repository.py`, `lyrics_cache.py` (INV-02) - P2, unveraendert
  DEFER.
- Cover-Cache-Metadaten-JSON (`_cache_best_cover`), Logger-Config - P3,
  unveraendert DEFER.
- `handlers/test_menu_handler.py` (INV-01) - reklassifiziert P2, DEFER (siehe
  oben).
- `utils/file_ops.py::atomic_rename()`, `bot_restart_handler.py` (bereits
  korrekt) - keine Aktion.

### Architecture Freeze Status

**⚠️ KORRIGIERT durch Abschnitt 29 — superseded by later evidence.**

Die folgende Aussage war zum Zeitpunkt der Enforcement Fix Phase korrekt,
ist aber durch die in Abschnitt 29 dokumentierten AE-10/AE-11/AE-12-Audits
und -Fixes ueberholt. Historischer Wortlaut unveraendert erhalten:

> NOT YET — CLOSURE AUDIT REQUIRED.
>
> Diese Fix-Phase hat alle bestaetigten P0/P1-Funde aus Abschnitt 27 behoben
> oder mit dokumentierter Begruendung zurueckgestellt. Vor einem erneuten
> Freeze-Versuch ist ein gezielter, forensischer Closure-Audit erforderlich
> (analog zum bereits etablierten Muster), der explizit prueft:
> - Wurden die hier gemachten Fixes korrekt und vollstaendig umgesetzt?
> - Ist die dokumentierte P0-B-Scope-Entscheidung (INV-01 zurueckgestellt)
>   weiterhin gerechtfertigt, oder hat sich die Ausgangslage geaendert?
> - Bestehen nach diesen Aenderungen neue, bisher unentdeckte
>   INV-01/INV-02-Verletzungen?
> - Sind die verbleibenden P2/P3-Funde weiterhin korrekt priorisiert?
>
> Kein Baseline v4 vor Abschluss dieses Closure-Audits.

Der geforderte Closure-Audit wurde durchgefuehrt (Abschnitt 29) und deckte
dabei einen neuen, durch den eigenen Fix verursachten Befund auf (AE-12),
der wiederum in einer eigenen, engen Fix-Phase geschlossen wurde. Aktueller
Stand: **siehe Abschnitt 29, Freeze-Status am Ende dieses Dokuments.**

---

## 29. AE-10 / AE-11 / AE-12 — Closure Summary

Diese Sektion fasst drei aufeinanderfolgende Audit-/Fix-Phasen zusammen,
die auf die Enforcement Fix Phase (Abschnitt 28) folgten. Vollstaendige
forensische Details, Messwerte und Testnachweise stehen in den jeweiligen
eigenstaendigen Reports; hier nur die fuer die Freeze-Entscheidung
relevante Zusammenfassung.

### AE-10 — ChartRenderer Event-Loop-Blocking + Thread-Safety

**Fund:** `services/statistik/chart_renderer.py::create_chart()` lief
synchron im Event-Loop (261-690ms real gemessen), aufgerufen von 6
Call-Sites in `handlers/mugge_statistik_handler.py`. Adversarielle
Vertiefung deckte zusaetzlich zwei bis dahin unbekannte, schwerwiegendere
Befunde auf: (1) ohne festes Backend-Pinning waehlt matplotlib je nach
Laufzeitumgebung ein GUI-Backend (hier TkAgg wegen gesetztem `DISPLAY`) -
ein einzelner Aufruf aus einem Nicht-Haupt-Thread fuehrte zu einem
Prozessabsturz (SIGABRT); (2) selbst mit sicherem Backend teilen sich alle
Aufrufe matplotlib.pyplots globalen "aktuelle Figure"-Zustand - zwei
gleichzeitige Renders konnten sich nachweislich gegenseitig die Figur
unterschieben.

**Fix:** `matplotlib.use("Agg")` fest gepinnt vor dem pyplot-Import, plus
ein prozessweiter `ChartRenderer._render_lock` (Klassenattribut) um den
gesamten pyplot-beruehrenden Codeblock. Alle 6 Call-Sites ueber
`asyncio.to_thread()` geroutet.

**Tests:** `tests/test_chart_renderer_thread_safety.py` (3, STRONG) +
`tests/test_mugge_statistik_handler_event_loop_blocking.py` (2, davon 1
STRONG + 1 ACCEPTABLE/Timing-basiert). Alle 5 per `git stash` als
diskriminierend verifiziert.

**Status: CLOSED.**

### AE-11 — TagWriter Crash-Safety (INV-02) + Exception-Swallowing

**Fund:** `services/metadata/tag_writer.py::write_tags()` schrieb via
`mutagen.audio.save()` direkt in-place in die bereits an ihrem finalen
Library-Pfad liegende Mediendatei (`rb+`, chunk-basiertes Byte-Shifting,
kein Tempfile/Rename - direkt im installierten mutagen-Quellcode
verifiziert). Ein Fehler oder Prozessabbruch waehrend des Schreibens
konnte die zuvor gueltige Datei beschaedigen - empirisch reproduziert
(mutagen/ffprobe meldeten die beschaedigte Datei faelschlich als gesund,
erst ein echter ffmpeg-Decode-Pass deckte die Korruption auf, fuer MP3
UND MP4/M4A). Zusaetzlich verschluckte der bestehende
`except Exception:`-Block in `write_tags()` jede Exception, wodurch der
bereits vorhandene FINDING-2-Cleanup in
`enhanced_metadata_processor.py` fuer diesen Fehlerfall faktisch nie
erreichbar war.

**Fix:** Copy+Tag+Replace-Muster (identisch zum bereits etablierten
Vorbild `utils/filenamefixer.py::move_to_library()`) - Taggen auf einer
temporaeren Sibling-Kopie, atomarer `Path.replace()` erst bei vollem
Erfolg, `target_path` bleibt bei jedem Fehler byteidentisch. Exception
wird jetzt unveraendert weitergereicht statt verschluckt - aktiviert den
FINDING-2-Cleanup zum ersten Mal wie urspruenglich beabsichtigt. Bewusst
OHNE `fsync()` (Begruendung siehe Code-Kommentar in `tag_writer.py` -
zum Zeitpunkt der AE-11-Implementierung noch zutreffend, siehe
Korrektur-Hinweis unter AE-12).

**Tests:** `tests/test_tag_writer_atomic_replace.py` (6, STRONG, echte
`ffmpeg`-Dateien + echter Decode-Pass) + 1 bestehender, korrigierter Test
in `tests/test_tag_writer.py`.

**Status: CLOSED.**

### AE-12 — Von AE-11 selbst verursachte neue INV-01-Regression

**Fund:** Der AE-11-Fix fuegte einen zusaetzlichen `shutil.copy2()`-Schritt
hinzu, aenderte aber nichts an der Tatsache, dass `write_tags()` weiterhin
synchron und ungewrappt direkt im Event-Loop-Thread lief. Real gemessen
(0 von 0 moeglichen Heartbeat-Ticks bei jeder getesteten Groesse 10-100MB):
fuer reguläre Musik-Tracks (3-15MB) blieb die Blockierung unter der
etablierten Sub-20ms-Schwelle, aber fuer Podcast-Klasse-Dateien (>20MB, ein
real unterstuetzter Content-Typ) reproduzierbar bis zu 1,6 Sekunden
vollstaendiges Einfrieren des gesamten Bots. Root-Cause-Praezisierung
gegenueber der ersten Vermutung: nicht `shutil.copy2()`, sondern
`Path.replace()` dominierte die Kosten unter realer Disk-I/O-Kontention.

**Fix:** Einzige Aenderung an `services/metadata/enhanced_metadata_processor.py`
(Zeile ~858-870): `self.tag_writer.write_tags(...)` →
`await asyncio.to_thread(self.tag_writer.write_tags, ...)`. Kein Lock
noetig - `TagWriter` haelt anders als `ChartRenderer` (AE-10) keinen
globalen mutierbaren Zustand, deterministisch mit 5 gleichzeitigen
Threads auf unterschiedlichen Dateien verifiziert. `tag_writer.py` selbst
unveraendert.

**Tests:** `tests/test_enhanced_metadata_processor_event_loop_blocking.py`
(2, STRONG - Heartbeat-Messung praezise auf das `write_tags()`-Zeitfenster
begrenzt, nicht durch den echten Cover-Art-Netzwerkaufruf verfaelscht) +
`tests/test_tag_writer_write_tags_concurrent_safety.py` (2, STRONG).

**Bekannte, unveraendert bestehende Doku-Ungenauigkeit:** der
fsync-Begruendungskommentar in `tag_writer.py` (Zeilen 70-79) verweist
noch darauf, dass `write_tags()` synchron im Event-Loop-Thread laeuft -
das ist seit AE-12 nicht mehr zutreffend (die Funktion laeuft jetzt auf
einem Worker-Thread). Die Entscheidung selbst (kein `fsync()`) bleibt aus
anderen Gruenden weiterhin sinnvoll (Konsistenz mit `move_to_library()`).
Rein dokumentarisch, keine funktionale Auswirkung - zur Kenntnisnahme
fuer eine kuenftige Dokumentationspflege vermerkt.

**Status: CLOSED** (siehe `docs/archive/AE-12_Closure_Audit.md` fuer die
vollstaendige, unabhaengig gegengepruefte Closure-Kriterien-Matrix).

### Verbleibende Findings (P2/P3, unveraendert gegenueber Abschnitt 28)

Alle in Abschnitt 28 gelisteten P2/P3-Findings bleiben unveraendert
DEFER. Zusaetzlich, aus den AE-10/11/12-Audits:
- `utils/filenamefixer.py::move_to_library()` TOCTOU (theoretisches
  Kollisionsfenster in der Zieldatei-Namensvergabe bei zwei zeitgleichen
  Aufrufen) - P2, DEFER, unveraendert durch AE-10/11/12.
- `services/metadata/tag_writer.py` fsync-Kommentar veraltet (siehe AE-12
  oben) - P3, rein dokumentarisch, DEFER.

### Finaler Regressionsstand nach AE-12

```
1107 passed, 0 failed, 19 subtests passed
```

### Architecture Freeze Status (aktuell)

**Siehe `docs/archive/MusicBot_FINAL_ARCHITECTURE_CLOSURE.md` (urspruenglicher
Gate-Audit, damals BLOCKED durch AE-12) und `docs/archive/AE-12_Closure_Audit.md`
(AE-12 selbst: CLOSED — GO). Mit AE-12 geschlossen ist der einzige
damals identifizierte technische Blocker aufgeloest.**
