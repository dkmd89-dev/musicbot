# MusicBot — Duplicate Resolution Architecture Decision Audit

**Typ:** Forensischer Architecture Decision Audit (read-only, keine Codeänderung)
**Datum:** 2026-09-01
**Auftrag:** Architekturentscheidung für eine künftige zentrale Duplicate-Resolution-Komponente (Pre-Download-Prevention + Post-Download-/Library-Resolution mit Album-vs-Single-Priorität)
**Ergebnis dieser Phase:** ausschließlich dieses Dokument. Keine Produktionscodeänderung, keine Teständerung, keine Konfigurationsänderung, keine Library-Mutation.

---

## Evidenzstandard

```text
E1 = direkt aus Code ableitbar (gelesen, zitiert, Zeilenangabe)
E2 = durch vorhandene Tests bestätigt
E3 = empirisch reproduziert/gemessen (in dieser Phase: read-only Inspektion realer Testdaten)
E4 = Architekturentscheidung / Empfehlung dieses Dokuments
```

---

## 1. Executive Decision

**ARCHITECTURE CONDITIONALLY APPROVED**

Eine zentrale Duplicate-Resolution-Architektur ist möglich und mit dem bestehenden Repository kompatibel — aber nur unter den in Abschnitt 15 und 18 explizit genannten Bedingungen. Die wichtigste Bedingung: die Album-vs-Single-Priorität lässt sich **heute bereits mit hoher Konfidenz** klassifizieren (E1, Abschnitt 6) — aber ausschließlich über die **Pfadstruktur**, nicht über Metadaten-Tags. Jede Implementierung, die stattdessen dem `©alb`-Tag-Inhalt vertraut, würde beim eigenen Zielbeispiel (Badchieff) falsch klassifizieren (Abschnitt 6.3, E3).

Automatische Löschung wird für die nächste Phase **nicht** freigegeben (Abschnitt 15) — nur Dry-Run-Klassifikation.

---

## 2. Repository State (Phase 0)

```text
pwd:              /mnt/128ssd/musicbot
git toplevel:     /mnt/128ssd/musicbot
Branch:           main
HEAD:             9f8427486e79e4736860273fb45d9e4f02bf5a5c
git status:       clean
git diff --stat:  (leer)
pytest tests/ -q: 1402 passed, 0 failed, 1 warning, 19 subtests passed (111s)
Python:           3.12.3
mutagen:          1.47.0
```

**Testumgebung vs. Repository (E1):** `/tmp/musicbot_test` ist **kein** Git-Repository (kein `.git`) — reiner Datenordner, angelegt/verwaltet über `config_test.Config`. Zwei separate Roots innerhalb dieses Ordners sind relevant und werden von unterschiedlichen bestehenden Tools genutzt:

| Root | Verwendet von | Zweck (E1) |
|---|---|---|
| `/tmp/musicbot_test/library` | `config_test.Config.LIBRARY_DIR` | „echte" isolierte Library, u. a. Ziel von `scripts/normalize_test_library_loudness.py` |
| `/tmp/musicbot_test/metadaten` | `scripts/reprocess_artist_metadata.py::DEFAULT_METADATEN_ROOT` | separater Sandbox-Root für Tag-Reprocessing-Testläufe |

Der im Auftrag genannte Badchieff-Fall liegt unter `metadaten/`, nicht unter `library/` — beide Roots sind nicht automatisch identisch und wurden nicht synchronisiert (Regel 4 des Auftrags: Unterschied dokumentiert, nicht eigenmächtig angeglichen).

---

## 3. Existing Duplicate Architecture (Phase 1–2)

Vollständig gelesen: `services/duplicate/detector.py` (353 Zeilen), `services/duplicate/cache.py` (300 Zeilen), `handlers/duplicate_handler.py` (313 Zeilen), sowie die bereits vorhandene Characterization `docs/archive/arch/MusicBot_ARCH-018_Duplicate_Handler_Characterization.md` (als Zusatzquelle, nicht als Ersatz für Codelesung — jede dortige Aussage wurde gegen den aktuellen Code re-verifiziert, E1).

**Zentraler Befund: es existieren heute DREI unabhängige, nicht miteinander verbundene „Duplicate"-Mechanismen im Repository** — nicht einer. Das war vor diesem Audit nicht vollständig dokumentiert (auch ARCH-018 kennt nur Mechanismus A).

### 3.A `services/duplicate/` — Pre-Download-Prevention (E1)

```text
DuplicateDetector.check_for_duplicates(url, raw_artist, raw_title, track_metadata)
  Stufe 1: DuplicateCache.check_url_duplicate(url)                    [YouTube-ID-bewusste URL-Normalisierung]
  Stufe 2: _normalize_artist_for_comparison + _clean_title_for_comparison
           → DuplicateCache.check_content_duplicate(artist, title)     [Hash exakt normalisierter Strings]
  Stufe 3: parse_youtube_title() → dieselbe Normalisierung             [Parser-Fallback]
  Stufe 4: check_library_duplicate(artist, title)                      [Dateisystem-Scan in LIBRARY_DIR]
→ Tuple[bool, Optional[DuplicateEntry], str]
```

- **Persistenz:** zwei JSON-Dateien (`url_duplicates.json`, `content_duplicates.json`), atomar geschrieben (`_write_json_atomic`, tmp+`Path.replace()`, `services/duplicate/cache.py:164-177`, E1).
- **Wirkung:** blockiert den Download, **bevor** er beginnt (`klassen/download_handler.py:333`, E1). Reine Prevention, keine Post-hoc-Auflösung.
- **`DuplicateEntry`-Datenmodell** (`services/downloader/models.py:21-30`, E1): `artist, title, url, file_path: Optional[Path]` (**Singular**, kein `List[Path]`), `download_date, file_hash, metadata_hash, duplicate_count`. **Kein `album`-Feld.**
- **Kritische Architekturgrenze (Phase 2.C, E1):** `DuplicateCache.add_entry()` (`cache.py:194-211`) überschreibt bei einem zweiten Treffer für denselben `content_hash` **nicht** den `file_path` — es wird nur `duplicate_count` auf dem bereits vorhandenen Eintrag erhöht. **Der Cache kann strukturell niemals mehrere Library-Pfade für denselben Track gleichzeitig repräsentieren.** Das ist keine Design-Lücke, die „übersehen" wurde — es ist die naturgemäße Konsequenz eines Single-Value-Dict, das nie für diesen Zweck (mehrere Kandidaten desselben Tracks) gebaut wurde.
- **`file_hash`/`metadata_hash` sind Write-Only (E1):** Beide werden bei `register_download()` berechnet und gespeichert (`detector.py:236,239`), aber **an keiner einzigen Stelle** in `check_for_duplicates()`/`check_url_duplicate()`/`check_content_duplicate()`/`check_library_duplicate()` gelesen oder verglichen (Grep-verifiziert). Aktuell **kein** Content-Hash-basiertes Erkennungssignal in Betrieb — nur String-Normalisierung.
- **Album ist an keiner Stelle im gesamten Mechanismus 3.A vorhanden** — weder als Feld noch als Vergleichskriterium. `_create_metadata_hash()` nutzt `["title", "artist", "duration", "upload_date"]` — auch `duration` fließt hier nur in einen nie verglichenen Hash ein.

### 3.B `EnhancedMetadataProcessor.processed_titles` — In-Memory, statistisch, non-blocking (E1, **neuer Befund**)

```python
# services/metadata/enhanced_metadata_processor.py:523-528
title_key = f"{final_artist}|{clean_title}".lower()
is_duplicate = title_key in self.processed_titles
if is_duplicate:
    self.processing_stats.duplicate_tracks += 1
self.processed_titles.add(title_key)
```

- **Zustand:** `set`, Instanzattribut, initialisiert `enhanced_metadata_processor.py:159`, nur über explizites `reset_statistics()` (`:202-205`) geleert — sonst **prozesslaufzeit-lang** (der Bot instanziiert `EnhancedMetadataProcessor` einmalig beim Start, bestätigt durch reale Bot-Start-Logs dieser Session).
- **Wirkung:** setzt ausschließlich das `is_duplicate`-Flag auf dem Rückgabeobjekt (`services/metadata/models.py:125`) und einen Statistik-Zähler. Grep-verifiziert (`grep -rn "\.is_duplicate\b"`): das Flag wird nur in `metadata_result_translator.py` und `services/metadata/cache.py`/`download/models.py` als reines Datenfeld weitergereicht — **es existiert kein einziger `if is_duplicate:`-Branch, der Verarbeitung, Move oder Download abbricht.** Rein statistisch/informativ.
- **Kein Bezug zu 3.A:** kein gemeinsamer Zustand, keine Cache-Datei, keine URL-Kenntnis, kein Library-Scan.

### 3.C `renamed_due_to_conflict` — Dateisystem-Kollisionsvermeidung, kein Content-Vergleich (E1)

```python
# utils/filenamefixer.py:324-331 (move_to_library)
final_target = target_path
counter = 1
while final_target.exists():
    final_target = target_path.with_name(f"{target_path.stem} ({counter}){target_path.suffix}")
    counter += 1
renamed_due_to_conflict = final_target != target_path
```

- **Wirkung:** Wenn der berechnete Zielpfad bereits **als Datei** existiert, wird die neue Datei blind mit `(1)`, `(2)`, … Suffix daneben abgelegt — **ohne jeden Inhalts- oder Metadatenvergleich**. Diese Funktion prüft nicht, ob es sich um denselben Track handelt; sie verhindert nur ein versehentliches Überschreiben.
- **Signal-Propagation:** `renamed_due_to_conflict` wird zwar bis zum `DownloadHandler` durchgereicht (`download_handler.py:551,569,767`, E1) — dort laut Code-Kommentar selbst historisch **„nie ausgewertet"** (P1-Fund aus Post-Baseline-v4-Audit, im Code referenziert) bis zu einem späteren Fix; aktuell wird es für Logging/Cleanup-Zwecke gelesen, **nicht** für eine Duplicate-Entscheidung.
- **Sehr wahrscheinliche Root Cause des Mission-Zielbeispiels (E1 für den Mechanismus, E3/Inferenz für diesen konkreten Fall):** Zwei „GUT AUS"-Dateien mit identischem berechnetem Zielpfad (`Singles/2025 - GUT AUS.m4a`) können ausschließlich durch genau diesen Blind-Rename-Mechanismus als `(1)`-Variante nebeneinander existieren. **Wichtige Einschränkung:** Die realen Testdaten unter `/tmp/musicbot_test/metadaten/Badchieff/` stammen nachweislich (Log-Datei `metadata_reprocessing_Badchieff_20260901_045430.log`, Zeile 3-7: „🧪 Test Environment … 📁 Input: …/metadaten/Badchieff … 📄 Dateien gefunden: 41") aus einem `reprocess_artist_metadata.py`-Testlauf gegen eine **kopierte, bereits bestehende Library-Struktur** (41 Dateien, reale Albumlisten) — nicht aus einem live in dieser Session beobachteten Download-Duplicate-Vorfall. `reprocess_artist_metadata.py` ruft `move_to_library()` laut eigenem Modul-Docstring nachweislich **nicht** auf. Die exakte historische Entstehung der `(1)`-Datei kann aus den in diesem Audit verfügbaren Artefakten nicht abschließend zurückverfolgt werden — der Mechanismus selbst (3.C) ist jedoch zweifelsfrei (E1) der einzige Codepfad im Repository, der eine solche Datei erzeugen kann.

### 3.D Zusammenfassung Phase 2.B (existing semantics)

| Frage | Antwort (E1) |
|---|---|
| Was gilt heute als Duplicate? | 3.A: identische URL (normalisiert) ODER identischer normalisierter Artist+Titel ODER Library-Datei mit passendem normalisiertem Artist+Titel — ausschließlich **vor** dem Download |
| Was gilt heute NICHT als Duplicate? | jede bereits abgeschlossene Library-Datei gegen eine andere bereits abgeschlossene Library-Datei — dafür existiert **kein** Vergleichsmechanismus |
| False Positives möglich? | historisch ja (DUP-03, siehe Abschnitt 5), inzwischen behoben — aktuelle `_clean_title_for_comparison()` entfernt bewusst **nicht** `(Live…)`/`(…Version)`/`(Remix)` (E1, E2: `tests/test_duplicate_detector_live_version_false_positive.py`, 7 Tests) |
| False Negatives möglich? | ja, strukturell: unterschiedliche Schreibweise, die durch die Normalisierung nicht auf denselben String fällt |

---

## 4. Current Call Graph (Phase 1)

```text
Telegram Update
    ↓
RichMenuHandler (einzige produktive Instanziierung von DuplicateDetector, handlers/menu/rich_menu_handler.py:241, E1)
    ↓
DownloadHandler (klassen/download_handler.py)
    ↓
_probe_artist_title_for_duplicate_check()  — yt-dlp download=False Probe (E1, :276-319)
    ↓
_check_duplicates_before_download()
    ↓
DuplicateDetector.check_for_duplicates()  [3.A, Stufen 1-4]
    ↓ (kein Duplikat)
Download → EnhancedMetadataProcessor.process_single_track()
    ↓
    ├─ processed_titles-Check (3.B, rein statistisch)
    ↓
move_to_library()  → renamed_due_to_conflict (3.C, blinde Kollisionsvermeidung)
    ↓
handle_single_track_success()
    ↓
DuplicateDetector.register_download()  [schreibt DuplicateEntry, EINER pro content_hash]
```

Bestätigt identisch zu ARCH-018 Abschnitt 3 (Pfad A) sowie zusätzlich präzisiert um 3.B/3.C, die dort nicht erfasst waren.

---

## 5. Duplicate Identity Model (Phase 3)

| Signal | Stärke | False-Positive-Risiko | False-Negative-Risiko | Verfügbarkeit (E1) |
|---|---|---|---|---|
| URL (normalisiert, YouTube-ID-bewusst) | HIGH (authoritative für „identischer Download-Vorgang") | sehr gering | hoch bei Reupload unter neuer ID | in `DuplicateCache`, nur Pre-Download |
| Artist+Titel (normalisiert) | MEDIUM (supporting) | mittel (DUP-03-Klasse: Versions-Suffixe, s. u.) | mittel (Schreibweisen-Varianten) | in `DuplicateCache` **und** `processed_titles`, aber **zwei getrennte, nicht synchronisierte Implementierungen der Normalisierung** — `DuplicateDetector._clean_title_for_comparison()` vs. `TitleCleaner.light_title_cleanup()` (von `EnhancedMetadataProcessor` genutzt) sind **nicht dieselbe Funktion** (E1, Import-Pfade unterschiedlich: `services/duplicate/detector.py` importiert keine `TitleCleaner`-Klasse) |
| `file_hash` (Head+Tail-MD5) | wäre HIGH (authoritative für Byte-Gleichheit) | sehr gering | hoch (jede Neukodierung ändert den Hash) | **berechnet, aber nirgends verglichen** (Abschnitt 3.A) — totes Signal |
| `metadata_hash` | wäre MEDIUM | — | — | **berechnet, aber nirgends verglichen** — totes Signal |
| Audio-Duration | wäre MEDIUM (unterscheidet Radio-Edit/Extended) | gering | — | nur indirekt in `metadata_hash` enthalten, dort ungenutzt — **kein aktiver Duration-Vergleich irgendwo im Repository** (Grep-verifiziert) |
| `©alb`/Album-Tag-Inhalt | LOW als alleiniges Signal (Abschnitt 6.3 beweist warum) | hoch bei Selbsttitel-Alben | — | in Library-Dateien vorhanden (mutagen `©alb`), von 3.A/3.B/3.C **nirgends gelesen** |
| Pfadstruktur (`Singles/` vs. `{Jahr} - {Album}/`) | HIGH für Album-vs-Single-Klassifikation (Abschnitt 6) | gering (etabliertes, konsistent geschriebenes Muster) | — | von `utils/filenamefixer.py::build_final_path()` selbst geschrieben — **die Bibliothek erzeugt ihre eigene, verlässliche Evidenz** |
| Video-ID isoliert (ohne URL-Kontext) | — | — | — | nicht persistiert außerhalb des URL-Strings selbst — kein separates Feld |

**Versions-Varianten (Remix/Live/Acoustic/Edit/Extended/Instrumental/Sped Up/Slowed/Remastered):** DUP-03 (`docs/archive/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE2J_DUP03_AUDIT.md`, E1/E2) belegt einen bereits behobenen historischen Bug: die Muster `r"\(.*?Version\)"`, `r"\(Live.*?\)"`, `r"\(Remix\)"` wurden 2026 ersatzlos aus `patterns_to_remove` entfernt, weil sie „Hello" und „Hello (Live at Glastonbury 2016)" fälschlich auf denselben normalisierten String kollabierten. Aktueller Code (E1, `detector.py:276-290`) entfernt nur noch `(Official…)`, `[…]`, `(feat…)`, `(ft…)` — Versions-Suffixe werden **absichtlich als unterschiedliche Titel behandelt** (konservativ: eher False Negative als False Positive). Für eine künftige Resolution-Engine bedeutet das: „Artist+Titel gleich" ist **nicht automatisch** „gleiche Aufnahme" — ein Remix/Live-Take mit identischem Kern-Titel würde von der reinen Artist+Titel-Normalisierung als eigenständiger Track behandelt, sofern der Klammerzusatz erhalten bleibt (korrekt so) — aber **nicht**, wenn der Klammerzusatz beim Tag-Schreiben bereits verloren ging (außerhalb des hier auditierten Scopes).

---

## 6. Album/Single Classification Model (Phase 4)

### 6.1 Empirisch belegte, bereits produktiv etablierte Konvention

`utils/filenamefixer.py::build_final_path()` (E1, Zeilen 533-568, bereits vollständig gelesen) legt fest:

```text
IF is_single_download OR album.lower() in ["single","singles"]
    → {ArtistDir}/Singles/{Jahr} - {Titel}.ext

ELSE
    → {ArtistDir}/{Jahr} - {Album}/{NN oder "00"} - {Titel}.ext
```

Diese Konvention ist **bereits die Autorität**, die die Library-Struktur erzeugt — keine neue Regel wird hier erfunden, nur als Erkennungssignal für die Rückrichtung (Datei → Klassifikation) wiederverwendet.

### 6.2 Zusätzliche Bestätigung (E2)

`tests/test_reprocess_artist_metadata.py::TestAlbumVsSinglesFilenameConvention` (bereits existierender Test, E2) bestätigt zusätzlich: ein Album-Track **ohne** `trkn`-Tag existiert real (`album_track_without_number`-Fixture) und bleibt trotzdem im `{Jahr} - {Album}`-Ordner — **`trkn` ist damit kein zuverlässiges Alleinkriterium**, nur die Pfadstruktur ist es.

### 6.3 Warum der Album-Tag-Inhalt allein NICHT genügt (E3, reale Testdaten)

Direkte Inspektion der drei realen Badchieff-Dateien (`/tmp/musicbot_test/metadaten/Badchieff/`, mutagen-Read, read-only):

| Datei | Ordner | `©alb`-Tag | `trkn` |
|---|---|---|---|
| `Singles/2025 - GUT AUS (1).m4a` | `Singles/` | `GUT AUS` | — |
| `Singles/2025 - GUT AUS.m4a` | `Singles/` | `GUT AUS` | `(1,0)` |
| `2025 - HEUTE ODER GESTERN/12 - GUT AUS.m4a` | `{Jahr} - {Album}/` | `HEUTE ODER GESTERN` | `(12,0)` |

Der Album-Tag der beiden Single-Dateien (`GUT AUS`) ist ein **Selbsttitel-Platzhalter** — identisch zum Titel, inhaltlich nicht von einem echten Ein-Wort-Albumnamen unterscheidbar. Eine Klassifikation, die sich auf „`©alb` gesetzt und nicht leer" stützt, würde beide Single-Dateien fälschlich als „hat ein Album" werten. **Nur die Ordner-Platzierung** trennt hier korrekt.

### 6.4 Klassifikations-Policy (E4)

```text
Elternordner-Name == "Singles" (case-insensitive)          → SINGLE
Elternordner-Name matcht ^\d{4}\s*-\s*.+ (Jahr-Bindestrich) → ALBUM_LIKE
alles andere (z. B. Spezialkanal-/Compilation-Pfade)        → AMBIGUOUS
```

`trkn`-Präsenz: unterstützendes, nicht entscheidendes Signal (bestätigt bei `ALBUM_LIKE`, negiert nichts bei Fehlen — Abschnitt 6.2).

### 6.5 EP/Compilation — dokumentierte Einschränkung (E1)

Die Mission fordert 4 Stufen (Album > EP/Compilation > Single > Unknown). Grep-Beleg: `release_type`/`release-group`-Daten existieren zwar als **Zwischenwert** in `MusicBrainzClient._build_metadata()` während der Genre-Bestimmung, werden aber nachweislich **nie** in eine Audiodatei persistiert — `tag_writer.py` kennt kein `release_type`-Feld. Es gibt **keine im Repository verfügbare, verlässliche Evidenzquelle**, um EP/Compilation von Album zu unterscheiden, ohne zu raten. **E4-Entscheidung:** 3 Kategorien (`ALBUM_LIKE`, `SINGLE`, `AMBIGUOUS`) statt 4 — EP/Compilation fällt unter `ALBUM_LIKE`. Dies ist eine bewusste, dokumentierte Vereinfachung, kein übersehener Fall.

---

## 7. Resolution Decision Matrix (Phase 5)

| Kandidat A | Kandidat B | Entscheidung (E4) |
|---|---|---|
| ALBUM_LIKE | SINGLE | **KEEP A, REMOVE B** (INV-D02) |
| ALBUM_LIKE | ALBUM_LIKE | Tie-Breaker (Abschnitt 7.1) |
| SINGLE | SINGLE | Tie-Breaker (Abschnitt 7.1) |
| ALBUM_LIKE | AMBIGUOUS | **KEEP ALBUM_LIKE** — AMBIGUOUS wird nicht automatisch entfernt, aber auch nicht bevorzugt behalten, wenn ein eindeutiger Kandidat existiert; REMOVE nur mit MANUAL REVIEW markiert, nie automatisch gelöscht |
| SINGLE | AMBIGUOUS | **KEEP SINGLE**, AMBIGUOUS → MANUAL REVIEW, keine Auto-Löschung |
| AMBIGUOUS | AMBIGUOUS | **KEEP BOTH**, MANUAL REVIEW — niemals automatische Löschung |
| (nur 1 Kandidat gefunden) | — | kein Duplicate-Fall — INV-D01 verhindert, dass hier überhaupt eine Aktion ausgelöst wird |

### 7.1 Tie-Breaker (innerhalb gleicher Kategorie, deterministisch, E4)

```text
1. vollständigere Metadaten (Anzahl belegter Felder aus einem festen Set)
2. höhere Audioqualität (ffprobe-Bitrate)
3. kanonischerer Pfad (kein "(N)"-Kollisions-Suffix)
4. finaler Tie-Breaker: lexikographisch kleinster vollständiger POSIX-Pfad
   (String-Vergleich — NIE Scan-/Dict-Reihenfolge, erfüllt INV-D03)
```

**Wichtig:** „Album schlechtere Audioqualität" (Mission-Testfall 5) — Album-Priorität (Kategorie-Rang) sticht **vor** dem Qualitäts-Tie-Breaker, da der Tie-Breaker nur **innerhalb** derselben Kategorie greift. Diese Entscheidung ist hiermit explizit dokumentiert (E4), nicht implizit.

Ambiguität führt **niemals** zu automatischer Löschung — direkte Umsetzung der Mission-Vorgabe.

---

## 8. Safety Model / Confidence Levels (Phase 6)

```text
Candidate Discovery → Identity Confidence → Classification Confidence → Resolution Decision → Safety Gate → Mutation
```

| Confidence | Kriterium (E4, begründet aus Abschnitt 5/6) |
|---|---|
| HIGH | Artist+Titel normalisiert identisch **und** Klassifikation über Pfadmuster eindeutig (`SINGLE` oder `ALBUM_LIKE`) |
| MEDIUM | Artist+Titel identisch, aber Klassifikation `AMBIGUOUS` (Spezialkanal-Pfad o. ä.) |
| LOW | Artist+Titel nur durch zusätzliche Normalisierungsschritte (z. B. Parser-Fallback) angeglichen, nicht direkt identisch |
| UNKNOWN | keine der obigen Bedingungen erfüllbar (z. B. fehlender Artist/Titel) |

**Safety Gate:** nur `HIGH`-Confidence-Paare dürfen laut diesem Modell jemals einen `REMOVE`-Vorschlag erzeugen — `MEDIUM`/`LOW`/`UNKNOWN` erzwingen `MANUAL REVIEW`. Keine erfundenen numerischen Schwellenwerte (kein „0.85 Score") — die Kriterien sind kategorial, weil die zugrundeliegenden Signale selbst kategorial sind (Pfadmuster trifft zu oder nicht).

---

## 9. Dry-Run Contract (Phase 7)

```text
DUPLICATE FOUND

Track:
  Artist: <normalisiert>
  Title:  <normalisiert>

KEEP:
  path:           <vollständiger Pfad>
  reason:         <Kategorie-Rang | Tie-Breaker-Stufe>
  classification: ALBUM_LIKE | SINGLE | AMBIGUOUS
  confidence:     HIGH | MEDIUM | LOW | UNKNOWN

REMOVE:
  path:           <vollständiger Pfad>
  reason:         <wie oben>
  classification: ...
  confidence:     ...

ACTION: KEEP / REMOVE / REVIEW / KEEP_BOTH
```

Rein lesend, keine Mutation, deterministisch (identischer Input → identischer Output, unabhängig von Scan-Reihenfolge — Voraussetzung: Abschnitt 7.1 Regel 4). Muss **vor** jeder künftigen `--execute`/`--apply`-Fähigkeit stehen.

---

## 10. Download Pipeline Integration Point (Phase 8)

```text
PRE-DOWNLOAD DUPLICATE PREVENTION  (3.A, bestehend, unverändert zu lassen)
        ↓
DOWNLOAD
        ↓
METADATA PROCESSING  (3.B processed_titles — rein statistisch, bleibt unverändert)
        ↓
LIBRARY FINALIZATION  (move_to_library, 3.C — blinde Kollisionsvermeidung, bleibt unverändert)
        ↓
[NEUER, GETRENNTER SCHRITT] POST-DOWNLOAD / LIBRARY DUPLICATE RESOLUTION
```

**E4-Entscheidung:** Die Post-Download-Resolution integriert sich **nicht** in den Live-Download-Pfad (nicht nach jedem einzelnen Download automatisch ausgelöst). Begründung:

1. Artist/Title/Album/Cover sind laut bestehendem Pipeline-Kommentar (`enhanced_metadata_processor.py`, Schritt-Nummerierung „15b"/„17" aus dieser Session bereits bekannter Ablauf) erst **nach** vollständiger Metadata-Verarbeitung final — ein Resolution-Lauf während der Pipeline liefe Gefahr, einen „halbverarbeiteten Track" (Mission-Vorgabe, Phase 8) als endgültigen Kandidaten zu behandeln.
2. Ein synchron in die Pipeline integrierter Resolver würde exakt die Race-Klasse öffnen, vor der die Mission (Phase 12) warnt: gleichzeitige Downloads + gleichzeitige Resolution auf demselben Library-Baum, ohne dass im Repository ein geeignetes Locking-Muster existiert (Grep-verifiziert: kein `fcntl`/`filelock`/Advisory-Lock-Pattern irgendwo im Repository, außer den bereits bekannten atomaren tmp+replace-Schreibmustern für einzelne Dateien).
3. Ein **separater, manuell gestarteter Nachlauf** (wie die beiden bestehenden `scripts/`-Tools dieser Session) vermeidet dieses Race vollständig — er läuft nie parallel zu einem aktiven Download, weil er nicht Teil des Event-Loops/der Download-Coroutine ist.

---

## 11. Single Source of Truth Decision (Phase 9)

**E4-Entscheidung: Option C (zentrale Duplicate Domain + mehrere Adapter), aber mit reduziertem Zuschnitt gegenüber der Mission-Skizze.**

```text
services/duplicate/
    detector.py    (bestehend, UNVERÄNDERT — Pre-Download, 3.A)
    cache.py       (bestehend, UNVERÄNDERT — Pre-Download-Persistenz)
    classification.py   [NEU, künftig] — Album/Single/Ambiguous-Klassifikation (Abschnitt 6), reine Funktion Pfad→Kategorie
    resolution.py        [NEU, künftig] — Decision Matrix (Abschnitt 7) + Confidence Model (Abschnitt 8), reine Funktion (Kandidat, Kandidat)→Entscheidung
```

**Warum keine Verschmelzung mit `detector.py`:** 3.A hat eine vollständig andere Aufrufsemantik (pre-download, blockierend, EIN Kandidat gegen Cache) als die neue Domäne (post-download, nicht-blockierend, N Kandidaten aus der Library). Eine gemeinsame Klasse würde zwei unterschiedliche State-Modelle (JSON-Cache vs. Dateisystem-Scan-Ergebnis) künstlich vermischen — das widerspräche Regel „möglichst kleine Änderung, keine unnötige neue Abstraktionsschicht" eher, als es zu befolgen. **Getrennte Module, gemeinsamer Package-Namespace** (`services/duplicate/`) ist die kleinste Änderung, die trotzdem eine erkennbare fachliche Heimat schafft.

`classification.py`/`resolution.py` würden von genau einem künftigen Konsumenten aufgerufen (Abschnitt 12) — kein „mehrere Adapter"-Bedarf ist heute belegt (kein Hinweis auf eine künftige Admin-UI im Repository, kein offener Issue/TODO dazu gefunden).

---

## 12. CLI/Script Decision (Phase 10)

**E4-Entscheidung:** Ein künftiges `scripts/resolve_duplicates.py` ist gerechtfertigt (konsistent mit dem bereits zweimal in dieser Session etablierten Muster `scripts/reprocess_artist_metadata.py`/`scripts/normalize_test_library_loudness.py`) — **aber erst nach** Freigabe von `services/duplicate/classification.py`/`resolution.py` (Abschnitt 11). Das Script selbst dürfte **keine eigene** Klassifikations-/Entscheidungslogik enthalten, nur:

```text
--dry-run     (Default)
--path        (Teilbereich, weiterhin ALLOWED_ROOT/FORBIDDEN_ROOTS-abgesichert)
--artist      (optional, auf einen Artist-Ordner eingeschränkt)
```

`--album`/`--track` (aus der Mission-Skizze) werden **nicht** als eigene Filter empfohlen — Klassifikation arbeitet ohnehin trackweise über die gesamte Bibliothek; ein artist-scope reicht für kontrollierte Testläufe aus, zusätzliche Filter wären ungenutzte Komplexität ohne belegten Bedarf (Phase 14).

`--apply`/`--execute` explizit **nicht** Teil dieser Phase (Abschnitt 15).

---

## 13. Idempotency Model (Phase 11)

```text
Run 1: Duplicate gefunden → REMOVE-Vorschlag (Dry-Run) → (künftig, nach Freigabe) Datei entfernt
Run 2: Nur noch 1 Kandidat pro Track vorhanden → INV-D01 greift → kein Duplicate-Fall mehr → no-op
Run 3: identisch zu Run 2
```

Da die Klassifikation ausschließlich von Pfad+Metadaten der jeweils vorhandenen Dateien abhängt (kein externer, sich änderender Zustand), ist Wiederholbarkeit strukturell gegeben, **sofern** die Löschung selbst atomar/vollständig war (Abschnitt 8/14).

| Fall | Verhalten (E4) |
|---|---|
| partial failure (Löschung schlägt nach Klassifikation fehl) | Kandidat bleibt unverändert liegen — kein Datenverlust, nächster Lauf klassifiziert erneut identisch |
| process crash zwischen Backup und finalem Remove | Backup-Kopie bleibt bestehen (analog zum bereits etablierten `.lufs_backup`-Muster aus `normalize_test_library_loudness.py`) — kein verlorener Zustand |
| permission error | Kandidat wird als FAILED markiert, nicht als REMOVE gewertet — bleibt für den nächsten Lauf identisch klassifizierbar |
| file disappears zwischen Discovery und Resolution | Re-Check unmittelbar vor jeder Mutation (Existenz-Check), sonst Skip mit Warnung — keine Aktion auf eine nicht mehr vorhandene Datei |
| concurrent resolver (zwei Läufe gleichzeitig) | siehe Abschnitt 14 |
| metadata mismatch (Datei seit Discovery verändert) | Re-Read der Metadaten unmittelbar vor Mutation, nicht nur einmal zu Beginn — verhindert TOCTOU auf Metadatenebene |

---

## 14. Concurrency Model (Phase 12)

**Download läuft + Resolver läuft (E1-gestützte Analyse):** Da der Resolver (Abschnitt 10) explizit **nicht** in die Download-Pipeline integriert wird und **synchron** (kein `asyncio`, kein geteilter Event-Loop) als eigenständiger Batch-Prozess läuft — exakt wie die beiden bestehenden `scripts/`-Tools dieser Session begründet —, gibt es keinen gemeinsamen In-Process-State mit dem Bot. Das verbleibende Risiko ist rein dateisystembasiert: der Resolver könnte eine Datei entfernen, die der Bot gerade in `move_to_library()` als Kollisionsziel prüft (`final_target.exists()`, Abschnitt 3.C).

**TOCTOU-Fenster:** real, aber klein und bereits durch bestehende Muster entschärfbar — `move_to_library()` selbst arbeitet bereits mit tmp+`Path.replace()` (E1, `filenamefixer.py:348-353`), sein `while final_target.exists()`-Loop bleibt aber ohne Lock racy. **E4:** kein neues Lock-Framework einführen (Phase 14 Anti-Overengineering) — stattdessen wird empfohlen, Resolver-Läufe operational (nicht durch Code-Locking) außerhalb aktiver Download-Fenster zu fahren, analog zur bereits etablierten Praxis der beiden bestehenden Wartungs-Scripts.

**Resolver A + Resolver B parallel:** kein Anwendungsfall im aktuellen Betriebsmodell (manuell gestartetes Einzeltool) — nicht weiter vertieft, da nicht durch reale Nutzung belegt (Phase 14-Kriterium).

**Bestehender Cache (3.A) durch Resolver berührt?** Nein — der Resolver liest/schreibt ausschließlich Library-Dateien, nicht `url_duplicates.json`/`content_duplicates.json`. Kein Interferenzpunkt mit dem bestehenden P2-Risiko in `duplicate/cache.py` (ARCH-018/Baseline v5 bereits bekannt, hier nicht neu bewertet — außerhalb des Scopes dieses Audits).

---

## 15. Failure Model (Phase 13)

### Darf niemals passieren (E4, harte Garantie)

```text
❌ beide Kandidaten gelöscht                          → INV-D01 (Gruppengröße-Check vor jeder Aktion)
❌ Album-Version gelöscht, obwohl korrekt klassifiziert → Kategorie-Rang hat Vorrang vor Tie-Breaker (Abschnitt 7)
❌ nicht verwandte Datei gelöscht                      → REMOVE nur innerhalb einer bereits als „gleicher Track" bestätigten HIGH-Confidence-Gruppe (Abschnitt 8)
❌ Ambiguität → Delete                                 → Abschnitt 7, AMBIGUOUS erzwingt MANUAL REVIEW
❌ erfolgreicher Download als Failure gemeldet          → Resolver ist vollständig getrennt vom Download-Result-Pfad (Abschnitt 10) — keine Rückwirkung möglich
❌ Cache-State widerspricht Library                    → Resolver berührt Cache (3.A) nicht (Abschnitt 14)
```

### Darf passieren (E4, akzeptiert)

```text
✔ Resolution skipped (AMBIGUOUS/LOW-Confidence)
✔ Manual review required
✔ stale candidate rejected (Existenz-Recheck vor Mutation)
✔ Duplicate bleibt temporär bestehen (nächster Lauf holt es nach)
```

Grundsatz (aus der Mission übernommen, hier bestätigt als tragfähig): **Safety > Cleanup-Vollständigkeit.**

---

## 16. Anti-Overengineering Gate (Phase 14)

| Option | Bewertung (E4) | Begründung |
|---|---|---|
| Audio Fingerprinting | NOT JUSTIFIED | kein Bedarf belegt — Pfadstruktur + Artist/Titel-Normalisierung lösen den dokumentierten Fall bereits vollständig (Abschnitt 6.3/6.4); Fingerprinting würde eine neue externe Dependency einführen, die nirgends sonst im Repository existiert |
| SQLite Duplicate Database | NOT JUSTIFIED | bestehendes JSON+atomic-replace-Muster (3.A) reicht für die erwartete Größenordnung (Library-Umfang, kein Hochfrequenz-Schreiben); keine Migration eines bestehenden, funktionierenden Musters ohne Befund |
| Background Worker | NOT JUSTIFIED | Resolver ist ein manuell gestarteter Batch-Prozess (Abschnitt 10/12) — kein Dauerbetrieb nötig |
| Event Bus | NOT JUSTIFIED | kein zweiter Konsument der Resolution-Ergebnisse belegt (Abschnitt 11) |
| Distributed Locking | NOT JUSTIFIED | kein Multi-Host-Betrieb im Repository ersichtlich (Single-Bot-Prozess, lokales Dateisystem) |
| Filesystem Watcher | NOT JUSTIFIED | Resolver ist bewusst pull-basiert (manueller Lauf), kein Push-Bedarf |
| ML Classification | NOT JUSTIFIED | Abschnitt 6 zeigt eine regelbasierte Klassifikation mit belegter hoher Konfidenz — kein Fall im Repository, der das nicht abdeckt |
| Microservice | NOT JUSTIFIED | widerspricht direkt der bestehenden Monolith-Skript-Konvention (`scripts/`) |
| Global Result Framework | DEFERRED | falls künftig tatsächlich mehrere Konsumenten (Admin-UI o. ä.) entstehen, wäre eine gemeinsame Result-Struktur sinnvoll — heute nicht belegt, daher nicht vorab bauen |

---

## 17. Open Questions

1. **Root für den künftigen Resolver:** `library/` (config_test-Konvention) oder `metadaten/` (wo der reale Badchieff-Fall liegt) — oder beide über `--path`? Nicht Teil dieses Audits, muss vor Implementierungsfreigabe geklärt werden.
2. **Herkunft der Badchieff-`(1)`-Datei:** Mechanismus (3.C) zweifelsfrei identifiziert, konkreter historischer Entstehungszeitpunkt nicht abschließend rekonstruierbar aus den in diesem Audit verfügbaren Artefakten (Abschnitt 3.C).
3. **Doppelte Normalisierungs-Implementierung** (Abschnitt 5, Artist+Titel-Zeile): `DuplicateDetector._clean_title_for_comparison()` und `TitleCleaner.light_title_cleanup()` sind zwei unabhängige Funktionen mit ähnlichem, aber nicht identischem Zweck. Nicht in diesem Audit vertieft (out of scope: Metadata-Qualität) — als Beobachtung für eine künftige Phase festgehalten.

---

## 18. Implementation Boundary (Phase 16)

**Nächster erlaubter Schritt (nach separater, ausdrücklicher Freigabe):**

```text
1. services/duplicate/classification.py   — reine Funktion Path → {ALBUM_LIKE, SINGLE, AMBIGUOUS}
2. services/duplicate/resolution.py       — reine Funktion (Kandidat, Kandidat) → Decision (Abschnitt 7/8)
3. Dry-Run-Contract-Implementierung (Abschnitt 9) — keine Mutation
4. Regressionstests (adversariale Szenarien wie in der Mission-Skizze Phase 8 gefordert:
   exaktes Duplikat, Album-vs-Single, zwei Singles, zwei Alben, Album schlechtere Qualität,
   unterschiedliche Schreibweise, Feature-Artist, wiederholter Lauf, Ambiguous)
5. scripts/resolve_duplicates.py als dünner CLI-Adapter (Abschnitt 12)
6. ERST DANACH, als separat freizugebender Schritt: --execute/Löschfähigkeit
   mit Backup-vor-Mutation (analog zum bereits etablierten LUFS-Script-Muster)
```

**Kein Schritt aus dieser Liste wurde in diesem Audit umgesetzt.**

---

## 19. Architecture Verdict

```text
ARCHITECTURE CONDITIONALLY APPROVED
```

**Bedingungen:**

1. Klassifikation MUSS über Pfadstruktur erfolgen (Abschnitt 6.4), NICHT über `©alb`-Tag-Inhalt allein (Abschnitt 6.3 beweist, warum das beim eigenen Zielbeispiel falsch klassifizieren würde).
2. `services/duplicate/detector.py`/`cache.py` (3.A) bleiben unverändert — neue Module, keine Erweiterung der bestehenden Klassen (Abschnitt 11).
3. Keine Pipeline-Integration in den Live-Download-Pfad (Abschnitt 10) — separater, manuell gestarteter Prozess.
4. Automatische Löschung ist NICHT Teil der freigegebenen nächsten Phase — nur Dry-Run-Klassifikation (Abschnitt 18, Schritt 6 explizit separiert).
5. AMBIGUOUS-Fälle dürfen niemals automatisch aufgelöst werden (Abschnitt 7/15).

**Wichtigste Evidenz:** drei unabhängige, bisher nicht gemeinsam dokumentierte Duplicate-Mechanismen (3.A/B/C); die Pfadkonvention aus `filenamefixer.py` ist bereits heute eine verlässliche, produktiv etablierte Evidenzquelle für Album-vs-Single; der reale Badchieff-Testfall widerlegt empirisch, dass der Album-Tag-Inhalt als alleiniges Kriterium tauglich wäre.

**Verbleibende Risiken:** TOCTOU-Fenster zwischen Resolver und `move_to_library()` (Abschnitt 14, operational statt durch Code-Locking zu entschärfen); doppelte Normalisierungs-Logik zwischen `DuplicateDetector` und `TitleCleaner` (Abschnitt 17.3, nicht behoben, nur dokumentiert); historische Herkunft der Badchieff-Fixture nicht vollständig rekonstruierbar.

**Nächster exakt definierter Implementierungsschritt:** Abschnitt 18, Schritte 1–5 — nach separater, ausdrücklicher Freigabe.

---

## Final Self-Check (Phase „Final Self-Check")

```text
git status --short  → M docs/MusicBot_DUPLICATE_RESOLUTION_ARCHITECTURE.md (nur dieses Dokument)
git diff --stat      → 1 Datei (dieses Dokument), keine weiteren Änderungen
pytest tests/ -q     → unverändert 1402 passed, 0 failed (kein Testlauf nach diesem Audit nötig, da keine Codeänderung erfolgte — Baseline aus Phase 0 bleibt gültig)
```

**Bestätigt:** keine Produktionscodeänderung, keine Teständerung, keine Library-Datei verändert, keine Datei gelöscht, kein Cache verändert, keine Pipeline verändert, kein Commit, kein Push. Die neue Dokumentationsdatei ist die einzige Änderung.

---

## 20. Phase 2 — Safety-Gate-Addendum

Ausgangspunkt: Phase 1.1 (Real Findings Audit, reiner Audit ohne
Codeänderung) hat anhand der echten Testbibliothek konkret belegt, dass
Confidence.HIGH ("Artist+Titel identisch + eindeutige Pfadklassifikation",
Abschnitt 8) allein NICHT ausreicht, um einen automatischen REMOVE-
Vorschlag zu rechtfertigen. Realer Gegenbeweis: makko — "Nachts wach",
zwei Tracks eines Remix-EPs (`2022 - Nachts wach (Remix EP)/02 -
Nachts wach.m4a` und `.../04 - Nachts wach.m4a`) mit identischem, aber
unbeschriftetem Titel — während zwei ANDERE Tracks desselben Albums
(`01`, `03`) explizit als eigene Remix-/Bootleg-Fassungen benannt sind.
Reale Duration-Abweichung 0.441179s, keine MusicBrainz Recording ID auf
beiden Dateien.

Phase 2 implementiert dazu ein zusätzliches **Evidence Safety Gate**
(`services/duplicate/resolution.py::_evaluate_safety_gate()`), das
JEDEM tentativen REMOVE-Vorschlag zusätzlich zur Confidence.HIGH-Prüfung
vorgeschaltet ist. Confidence.HIGH bleibt Voraussetzung, ist aber nicht
mehr hinreichend.

### 20.1 Neue Evidenz-Signale

| Signal | Herkunft | Quelle |
|---|---|---|
| `duration_seconds` | ffprobe `format=duration` (echte Audiodatei, nicht Dateiname/Tag) | `scripts/resolve_duplicates.py::measure_audio_stream()` |
| `mb_recording_id` | bereits Teil von `METADATA_COMPLETENESS_FIELDS` (Abschnitt 6 alt) | `read_tags()` |
| `isrc` | bereits Teil von `METADATA_COMPLETENESS_FIELDS` | `read_tags()` |
| `cover_sha256` | SHA-256 des eingebetteten Covers — **rein informativ**, siehe 20.4 | `read_tags()` |

### 20.2 Duration-Toleranz (technisch hergeleitet, nicht willkürlich)

`DURATION_CONSISTENT_TOLERANCE_SECONDS = 0.1` (`services/duplicate/classification.py`).

Herleitung: AAC-Frame-Größe 1024 Samples / 44100 Hz ≈ 23 ms; Encoder-
Priming/Padding-Differenzen zwischen zwei Encodes derselben Aufnahme
liegen typischerweise bei ~2–4 Frames (~50–90 ms), auch über
unterschiedliche Sample-Raten hinweg. Ein bereits im Repository
etabliertes Vorbild (`DURATION_WARN_SECONDS = 2.0`,
`scripts/normalize_test_library_loudness.py`) ist für einen anderen
Zweck kalibriert (Re-Encode derselben Datei an Ort und Stelle) und wäre
hier ungeeignet — 2.0s hätte den Nachts-wach-Fund (0.441s) nicht
erkannt.

Empirisch bestätigt an allen real vorgefundenen Fällen:

| Fall | Δ Duration | Bewertung |
|---|---|---|
| makko / Dein Lügner (Album vs. Single) | ≈ 0.000s | PASS |
| makko / Pueblo (Album vs. Single) | ≈ 0.000s | PASS |
| Badchieff / GUT AUS (Single-Kopie, Resample 44100→48000 Hz, identische ISRC/MB-ID) | ≈ 0.06s | PASS |
| makko / Nachts wach (zwei tatsächlich unterschiedliche Aufnahmen) | 0.441179s | FAIL (> 4× Toleranz) |

### 20.3 MusicBrainz-Recording-ID-Verhalten (Abschnitt 6 im Auftrag Phase 2)

- Beide IDs vorhanden + identisch → **starke Identitätsbestätigung**, überstimmt sogar eine sonst blockierende Duration-Abweichung.
- Beide IDs vorhanden + unterschiedlich → **unbedingter Widerspruch**, blockiert IMMER, unabhängig von Duration/Album-Kontext.
- Mindestens eine ID fehlt → kein Signal (`UNKNOWN`), blockiert NICHT von sich aus — sonst wäre der reale Pueblo-Fall (kein MB-ID vorhanden, aber korrektes Duplikat) nicht mehr auflösbar. ISRC verhält sich identisch und wird gleichwertig als starke Bestätigung akzeptiert (im Badchieff-Fall sogar die im Audit stärkste beobachtete Evidenz).

### 20.4 Album-Context-Risk (Abschnitt 5 im Auftrag Phase 2)

Enthält der Albumname ein Wort aus `remix|live|version|edit|acoustic|
bootleg|mix|extended|instrumental` (Wortgrenzen-Regex, kein reiner
Teilstring-Match — verhindert z. B. Fehltreffer auf "Mixtape"), gilt das
**ausschließlich als Risikosignal**, nicht als automatischer Blocker:
Es verhindert eine automatische Auflösung nur dann, wenn zusätzlich
KEINE starke Identitätsbestätigung (MB-ID/ISRC) vorliegt.

**Bewusst nicht als Blocking-Signal aufgenommen** (mit konkreter
Begründung, kein Overengineering-Verstoß gegen Abschnitt 16):

- **ReplayGain**: kann sich bei derselben Aufnahme legitim ändern — `scripts/normalize_test_library_loudness.py` berechnet LUFS/ReplayGain absichtlich neu. Ungeeignet als alleiniges Blocking-Signal.
- **Audio-Stream-Parameter (Sample-Rate/Codec)**: der reale Badchieff-Fall widerlegt die Eignung — zwei Kopien derselben Aufnahme (identische ISRC/MB-ID) unterscheiden sich real in der Sample-Rate (44100 Hz vs. 48000 Hz).
- **Cover-Hash**: nur informativ geführt (`Candidate.cover_sha256`), fließt nicht in die Blocking-Logik ein — ein abweichendes Cover darf allein niemals eine Auflösung verhindern.
- **Audio-Fingerprinting** (Chromaprint/AcoustID/librosa/Essentia): weiterhin DEFERRED, siehe Abschnitt 16 — keine neue Dependency, die o. g. bereits vorhandenen Signale genügen für die real beobachteten Fälle.

### 20.5 Ergebnis: makko / Nachts wach

Mit dem Safety Gate liefert `resolve_group()` für diesen Fall:

```text
Duration:            MISMATCH (Δ 0.441179s)
MusicBrainz:          NOT AVAILABLE (UNKNOWN)
Album context:        HIGH-RISK VERSION CONTEXT ("Remix EP")
Strong identity:       NICHT bestätigt
→ SAFETY GATE:         BLOCKED
→ ACTION:              MANUAL_REVIEW (statt zuvor RESOLVED/REMOVE PROPOSAL)
```

`makko / Dein Lügner` und `makko / Pueblo` bleiben unverändert RESOLVED
(Duration konsistent, kein widersprechendes MB-Signal, kein Risk-Kontext
im Albumnamen).

### 20.6 Rückwärtskompatibilität

Alle vier neuen `Candidate`-Felder (`duration_seconds`,
`mb_recording_id`, `isrc`, `cover_sha256`) haben Default `None`. Ist ein
Feld nicht gesetzt, liefern die zugehörigen Vergleichsfunktionen `None`
(unbekannt) statt `False` (Widerspruch) — das Safety Gate blockiert
dadurch nie allein wegen fehlender Phase-2-Daten. Alle 74 Phase-1-Tests
liefen ohne Änderung unverändert grün gegen die Phase-2-Implementierung
(siehe `tests/test_duplicate_resolution.py`,
`tests/test_duplicate_classification.py`).

---

## 21. Phase 2.2 — False-Negative-Fix (Anführungszeichen-Normalisierung)

**Finding (Phase 2.1, Real Findings Audit):** Zwei reale Duplicate-Paare
(`makko / Bequem`, `makko / Grad mal ein Jahr`) wurden nie als
gemeinsame Gruppe erkannt, weil der Single-Tag ein umschließendes
Anführungszeichen-Paar trägt (`©nam = '"Bequem"'`), der Album-Tag
jedoch nicht (`©nam = 'Bequem'`) — beide Kopien teilen dieselbe
MusicBrainz Recording ID und identische Duration. Reiner False
Negative (kein Safety-Risiko), aber eine Vollständigkeitslücke.

**Fix:** `services/duplicate/classification.py::normalize_title_for_identity()`
entfernt als letzten, unabhängigen Schritt GENAU EIN vollständig
umschließendes, zusammenpassendes Anführungszeichen-Paar
(`_strip_wrapping_quote_pair()`, Paare: `"…"`, `'…'`, `„…“`, `"…"`,
`'…'`). Nur bei exaktem Match von erstem UND letztem Zeichen — keine
Entfernung einzelner/unpaariger Zeichen oder interner Apostrophe
(„Rock 'n' Roll" bleibt unverändert). Die bestehenden DUP-03-Regeln
(Live/Remix/Version werden NICHT gestrippt) sind davon unberührt, da
der neue Schritt komplett unabhängig danach läuft.

**Detector-Parität:** `services/duplicate/detector.py::_clean_title_for_comparison()`
(PRE-DOWNLOAD-Pfad) erhielt dieselbe, identisch implementierte
Ergänzung (`_strip_wrapping_quote_pair()` als neue freie Modulfunktion,
Modul-Docstring dokumentiert die Paritätsbegründung) — Verhaltensänderung
des produktiven Pre-Download-Duplicate-Checks: Titel, die sich nur durch
ein umschließendes Anführungszeichen-Paar unterscheiden, werden ab
sofort auch dort als potenzielles Content-Duplikat erkannt. Keine
sonstige Änderung an `DuplicateDetector`/`DuplicateCache`.

**Ergebnis Library-Dry-Run** (`/tmp/musicbot_test/library`, vorher/nachher):

| | Phase 2.1 | Phase 2.2 |
|---|---|---|
| Duplicate groups | 3 | 5 |
| Auto-resolvable | 2 | 4 |
| Manual review | 1 | 1 (unverändert: Nachts wach) |

Beide neu erkannten Gruppen (Bequem, Grad mal ein Jahr) lösen dank
identischer MusicBrainz Recording ID + konsistenter Duration korrekt
als `RESOLVED` (Album > Single) auf — Safety Gate `PASSED`.

**Tests:** `tests/test_duplicate_title_quote_normalization.py` (30 neue
Tests: Positiv-/Negativfälle, Detector-Parität, reale Regression für
beide Paare, Nichtregression der bekannten kritischen Fälle Dein
Lügner/Pueblo/Nachts wach/Badchieff).

---

## 22. Phase 2.3 — Identity & Classification Robustness Audit

Gezielter Audit der Identity-/Classification-Schicht vor einer möglichen
Execute-Phase (Auftrag: "Gibt es weitere reale Tagging-/Naming-Artefakte,
durch die echte Duplikate derzeit als getrennte Gruppen behandelt werden,
oder durch die unterschiedliche Aufnahmen fälschlich dieselbe Identity
erhalten könnten?").

### 22.1 Kategorie-1-Befund (Safety Problem) — behoben

**Finding:** `_evaluate_safety_gate()` (`services/duplicate/resolution.py`)
prüfte einen MusicBrainz-Recording-ID-Mismatch unbedingt blockierend
(Regel 2), besaß aber KEINE symmetrische Regel für einen ISRC-Mismatch,
obwohl ISRC laut `has_strong_identity_confirmation()` ein zur MB
Recording ID gleichwertiges Identitätssignal ist. Ein reiner
ISRC-Mismatch bei sonst konsistenter Duration und ohne Remix-Album-
Kontext konnte dadurch einen automatischen REMOVE-Vorschlag NICHT
verhindern — nachgewiesener, reproduzierbarer False-Positive-Vektor
(Audit Case E).

Nicht in der aktuellen Testbibliothek aktiv ausgelöst (keine der 5
realen Gruppen hängt an einem ISRC-Mismatch), aber strukturell jederzeit
auslösbar — insbesondere in einer größeren Produktionsbibliothek mit
mehr ISRC-getaggten Tracks.

**Fix (minimal, symmetrisch zur bestehenden MB-ID-Regel):**
`_evaluate_safety_gate()` berechnet zusätzlich `isrc_match =
compare_isrc_identity(keep, candidate)` und blockiert unbedingt bei
`isrc_match is False` — unabhängig von Duration/Album-Kontext, exakt
wie bei der MB-ID-Regel. `CandidateEvidence` erhielt das neue Feld
`isrc_match` (Evidence-Ausgabe/JSON-Report in `scripts/resolve_duplicates.py`
entsprechend erweitert). Keine Änderung an `classification.py` nötig
(`compare_isrc_identity()` existierte bereits seit Phase 2, wurde bisher
nur für `has_strong_identity_confirmation()` verwendet).

**Detector-Parität:** entfällt für diesen Fix — `detector.py` (Pre-
Download-Pfad) kennt kein MusicBrainz-Recording-ID-/ISRC-Konzept
(verifiziert: keine Treffer für „isrc"/„musicbrainz" im gesamten Modul).
Die Parität aus Phase 2.2 (Titel-Normalisierung) bleibt davon unberührt.

**Tests:** `tests/test_duplicate_isrc_mismatch_safety_gate.py` (7 neue
Tests: Kernregression, Blocking ohne Duration-Daten, Evidence-Feld,
Nichtregression bei ISRC-Match/fehlendem ISRC/Pueblo-Realfall,
Kombination MB-Match+ISRC-Mismatch).

### 22.2 Kategorie-4-Befunde (theoretische Risiken, NICHT behoben)

Systematisch geprüft, in der realen Testbibliothek NICHT reproduzierbar,
daher bewusst nicht implementiert (Overengineering-Vermeidung):

- **Deutsche Anführungszeichen-Variante `‚…‘`** (U+201A…U+2018) wird von
  `_strip_wrapping_quote_pair()` nicht erkannt (nur `„…“`/`"…"`/`'…'`/
  `“…”`/`‘…’`). Kein realer Fall in der Testbibliothek gefunden.
- **Case-Insensitivität** (`SONG` vs. `Song`) wird nicht normalisiert.
  Kein realer Kollisionsfall gefunden; bewusst konservativ, da
  Groß-/Kleinschreibung gelegentlich stilistisch bedeutungstragend ist.
- **Unmarkierte `feat.`/`ft.`-Suffixe ohne Klammern** (`Song feat. X`
  statt `Song (feat. X)`) werden nicht gestrippt — nur die bereits
  bestehende, bewusst eng gefasste Klammer-Variante. Kein realer Fall
  gefunden.
- **Multi-Artist-Separator-Inkonsistenz** (`makko feat. X` vs.
  `makko & X` vs. `makko, X`) wird nicht normalisiert — `normalize_
  artist_for_identity()` führt keine Separator-Analyse durch. Für die
  6 real vorgefundenen Multi-Artist-Strings der Testbibliothek bewiesen
  NICHT fälschlich kollabierend (Safety bestätigt), aber potenziell ein
  weiterer False-Negative-Fall bei künftigen inkonsistent getaggten
  Kollaborationen. Kein realer Kollisionsfall gefunden.

### 22.3 False-Positive-Audit (Cases A–H)

Alle 8 adversarialen Fälle aus dem Auftrag gegen die echte
`resolve_group()`-Implementierung geprüft — 8/8 PASS (Case E initial
FAIL, siehe 22.1, nach Fix PASS). Insbesondere Case H bestätigt: ein
Identitäts-Signal (MB-ID/ISRC) überstimmt niemals die grundlegende
Artist/Title-Gruppierung — unterschiedliche Artists mit identischer
MB-ID/ISRC bilden nie eine gemeinsame Gruppe.

### 22.4 Safety Invariants INV-D09 bis INV-D12 (neu)

Alle vier neuen, im Auftrag definierten Invarianten PASS — siehe
`INV-D09`–`INV-D12` im Abschlussbericht der Phase.

### 22.5 Verdict

**SAFE_TO_PROCEED** nach Anwendung des Fixes aus 22.1 — siehe
Abschlussbericht der Phase für die vollständige Begründung.

---

## 23. Phase 3 — SAFE EXECUTE IMPLEMENTATION

Erste Phase mit tatsächlicher Löschfähigkeit. Neues Modul
`services/duplicate/execution.py` (Fingerprinting, Execution Plan/
Manifest, zweistufige Pre-Delete-Revalidierung, gruppenatomares Delete)
+ `--execute`-Flag in `scripts/resolve_duplicates.py` (siehe dortige
Modul-Docstrings für das vollständige Sicherheitsmodell). `--apply`/
`--delete` bleiben weiterhin verbotene Alias-Flags.

### 23.1 Realer Vorfall während der Implementierung (volle Transparenz)

Beim ersten Regressionslauf nach der `--execute`-Implementierung
(`pytest tests/test_resolve_duplicates.py`) enthielt die zu diesem
Zeitpunkt noch nicht angepasste Phase-1-Testklasse `TestNoExecuteFlags`
einen parametrisierten Aufruf `rd.main(["--execute"])` **ohne**
`--path`/`--artist`-Scoping - eine Annahme aus der Zeit, als `--execute`
noch abgelehnt wurde. Da `--execute` durch die Implementierung in
genau diesem Schritt real wurde, lief dieser Testaufruf gegen den
vollen `ALLOWED_ROOT` (die geteilte, reale Testbibliothek
`/tmp/musicbot_test/library`) und löschte dabei tatsächlich 4 Dateien:

| Gruppe | Gelöscht | KEEP (unverändert erhalten) |
|---|---|---|
| Bequem | `makko/Singles/2021 - Bequem.m4a` | `makko/2021 - Leb es oder lass es 2/11 - Bequem.m4a` |
| Dein Lügner | `makko/Singles/2023 - Dein Lügner.m4a` | `makko/2023 - Lieb mich oder lass es, Pt.1+2/15 - Dein Lügner.m4a` |
| Grad mal ein Jahr | `makko/Singles/2021 - Grad mal ein Jahr.m4a` | `makko/2021 - Leb es oder lass es 2/02 - Grad mal ein Jahr.m4a` |
| Pueblo | `makko/Singles/2023 - Pueblo.m4a` | `makko/2023 - Lieb mich oder lass es, Pt.1+2/14 - Pueblo.m4a` |

Verifiziert per Audit-Log (`duplicate_execution_audit_log.jsonl`):
genau diese 4 Dateien, keine weiteren. `makko/2022 - Nachts wach (Remix
EP)/` (MANUAL_REVIEW) vollständig unangetastet. Alle 4 KEEP-Dateien
unverändert. `/mnt/4tb/library` (Produktion) ohne jede mtime-Änderung -
komplett unberührt. Kein Commit, kein Push.

**Einordnung:** Die gelöschten Dateien waren exakt jene, die bereits in
Phase 1.1/2.1/2.2 unabhängig forensisch als echte Duplikate verifiziert
wurden (MB-Recording-ID-Match, identische Duration, Album-Version
behalten) - die Execute-Logik selbst arbeitete in diesem ungeplanten
Lauf nachweislich korrekt (richtige Gruppenauswahl, korrekte
Revalidierung, KEEP/MANUAL_REVIEW/unbeteiligte Dateien unangetastet).
Die Ursache war **prozedural**: die Testsuite wurde ausgeführt, bevor
der veraltete Test angepasst oder eine isolierte Kopie (Auftrag
Abschnitt 21) angelegt war. Nutzer-Entscheidung nach Offenlegung: neue
Baseline (122 statt 126 Dateien) akzeptieren und fortfahren.

**Konsequenz für die Testsuite:** `tests/test_duplicate_execution.py`
und `tests/test_resolve_duplicates_execute.py` verwenden ab sofort
ausschließlich `tmp_path`/isolierte `--path`-gescopte Unterverzeichnisse
für JEDEN `--execute`-Aufruf - dokumentiert als nicht verhandelbare
Sicherheitsregel im jeweiligen Modul-Docstring.

### 23.2 Zweistufiges Sicherheitsmodell

```text
build_execution_plan() — nur GroupAction.RESOLVED, Confidence.HIGH,
                          gruppenatomar (ein nicht fingerprintbarer
                          Kandidat verhindert die GESAMTE Gruppe)
        ↓
revalidate_group() — Stufe 1: Path-Safety + Fingerprint (Größe+SHA-256)
                      für KEEP UND jeden REMOVE-Kandidaten
                      Stufe 2: frische Candidate-Objekte von der Platte,
                      resolve_group() ERNEUT - TOCTOU-/Metadaten-Drift-Schutz
        ↓
execute_group() — nur bei vollständigem PASS: einzelne Path.unlink()-
                   Aufrufe, KEEP-Integrität danach erneut verifiziert
```

### 23.3 Tests

- `tests/test_duplicate_execution.py` (21 Tests): Fingerprinting,
  Plan-Bau (nur RESOLVED), Revalidierung (Fingerprint/Path-Safety/
  semantische Drift/Gruppenatomarität), Execute (Delete, KEEP-Schutz,
  Fehlerbehandlung, defensive Zweitverteidigung).
- `tests/test_resolve_duplicates_execute.py` (13 Tests): CLI-End-to-
  End inkl. aller bekannten Regressionsfälle (Dein Lügner/Pueblo/
  Bequem/Nachts wach/Badchieff), Symlink-Eskalation, Forbidden Root,
  Dry-Run→Execute→Dry-Run, Manifest-/Audit-Log-Inhalt.
- `tests/test_resolve_duplicates.py`: `TestNoExecuteFlags` angepasst
  (`--execute` aus der Verbotsliste entfernt, `--apply`/`--delete`
  bleiben verboten).

### 23.4 Isolierter Real-Test (innerhalb ALLOWED_ROOT, disposable
Unterverzeichnis)

`/tmp/musicbot_test/library_execute/` (außerhalb `ALLOWED_ROOT`) wurde
verworfen, da die bestehende Path-Safety-Architektur bewusst NUR
`ALLOWED_ROOT` selbst und Unterverzeichnisse erlaubt (korrektes
Verhalten, keine Änderung vorgenommen). Stattdessen: disposables
Unterverzeichnis `ALLOWED_ROOT/_manual_execute_demo/` mit real
kopierten (nicht verschobenen) Audiodateien - ein synthetisches
Album/Single-Duplikat (`makko/Coco`, byte-identische Kopie) plus das
reale Nachts-wach-Muster. Vorher: 4 Dateien/2 Gruppen/1 resolvable/1
MANUAL_REVIEW. Nach `--execute`: 3 Dateien, Coco-Single gelöscht,
Nachts wach vollständig unangetastet, `execution_result: SUCCESS`.
Demo-Verzeichnis anschließend vollständig entfernt (Originaldateien an
ihrem eigentlichen Ort dabei nachweislich unangetastet).

### 23.5 Verdict

**EXECUTE_IMPLEMENTED_AND_TESTED** — siehe Abschlussbericht der Phase
für die vollständige Begründung inklusive des Vorfalls aus 23.1.

---

## 24. Production Read-Only Dry-Run Enablement ("Freigabe Schritt 3")

Ziel: reiner Lesezugriff auf die reale Produktionsbibliothek
(`config.py::Config.LIBRARY_DIR`, seit dem Commit "Konfiguration:
library/ Verzeichnis in config.py angepasst" `/mnt/musik_bilder/library`,
vormals `/mnt/4tb/library`), ohne die bestehende Execute-Sperre für
Produktion aufzuweichen.

### 24.1 Architektur

Neue Konstante `ALLOWED_READONLY_ROOTS = [Path("/mnt/musik_bilder/library")]`.
`validate_scan_root(path, allow_execute)`: Testbibliothek (`ALLOWED_ROOT`)
behält vollen Zugriff; ein `ALLOWED_READONLY_ROOTS`-Pfad wird NUR
akzeptiert, wenn `allow_execute` (== `args.execute`) `False` ist -
`--execute` gegen einen Read-Only-Root wird unbedingt und vor jeder
anderen Prüfung mit `PathSafetyError` abgelehnt. `--path` bleibt der
einzige CLI-Zugang - keine neue Flag nötig.

### 24.2 Gefundener und behobener Fehler (vor dem ersten realen Lauf)

Der erste reale Testlauf gegen `/mnt/musik_bilder/library` lieferte
`Files scanned: 0` - `validate_file_within_root()` prüfte `FORBIDDEN_ROOTS`
(worunter weiterhin das gesamte `/mnt/musik_bilder` fällt) VOR der
Zugehörigkeit zum tatsächlich übergebenen `permitted_root`, wodurch
jede Datei fälschlich als "außerhalb erlaubtem Root" übersprungen wurde
- der neue Read-Only-Root liegt bewusst VERSCHACHTELT innerhalb eines
weiterhin verbotenen Mounts, eine Konstellation, die im ursprünglichen,
überlappungsfreien ALLOWED_ROOT-/FORBIDDEN_ROOTS-Design nicht vorkam.
Fix: Root-Zugehörigkeit wird jetzt zuerst geprüft (autoritativ, da
`permitted_root` bereits durch `validate_scan_root()` bestätigt wurde),
`FORBIDDEN_ROOTS` greift nur noch als Verteidigung für Pfade außerhalb
des übergebenen Roots. Vor dem realen Lauf durch 10 gezielte Tests
(gefakte Read-Only-Roots, niemals der echte Produktionspfad in Tests)
sowie den anschließenden realen Nachweis (416/416 Dateien erfolgreich
gescannt) verifiziert.

### 24.3 Realer Dry-Run gegen /mnt/musik_bilder/library

```text
Files scanned:      416
Duplicate groups:   14
Auto-resolvable:    12
Manual review:      2
Single (no dup):    386
Read-only intact:   PASS (zusätzlich verifiziert: Dateianzahl vor/nach
                      unverändert, keine Datei mit mtime nach Scan-Start)
```

Neue, in der kuratierten Testbibliothek bisher nicht vorhandene Muster:

- **2Pac / Changes** → `MANUAL_REVIEW` (Duration-Abweichung 11.34s, kein
  MB-ID) - Safety Gate korrekt ausgelöst, kein automatischer REMOVE.
- **Badchieff / LAUF, MANCHMAL, PARKHAUS** → `RESOLVED` über den
  ALBUM_LIKE-vs-ALBUM_LIKE-Tie-Breaker (nicht Album-vs-Single wie in
  allen bisherigen Fällen) - derselbe MB-ID/ISRC-bestätigte Track
  erscheint auf zwei verschiedenen Alben (`2022 - I SEE YOU WHEN I SEE
  YOU` und `2022 - MANCHMAL`); der Tie-Breaker wählt deterministisch
  eine Version, die andere wird REMOVE-Vorschlag.
- Alle 12 `RESOLVED`-Gruppen mit vorhandener MusicBrainz Recording
  ID/ISRC zeigen durchgehend `mb_match=True`/`isrc_match=True` - keine
  einzige widersprüchliche ID in der gesamten realen Bibliothek
  beobachtet.

Bekannte Fälle (Bequem/Dein Lügner/Grad mal ein Jahr/Nachts wach/Pueblo/
GUT AUS) bestätigen sich 1:1 gegen die reale Produktionsbibliothek.

### 24.4 Sicherheit

Kein `--execute` gegen `/mnt/musik_bilder/library` ausgeführt (strukturell
blockiert, per Test verifiziert). Keine Datei verändert, verschoben oder
gelöscht. Einziger Schreibzugriff: der bestehende Sandbox-JSON-Report
unter `/tmp/musicbot_test/`.

### 24.5 Verdict

Vollständige Rohdaten (14 Gruppen, alle Evidenzfelder) liegen im
Gesprächsverlauf/JSON-Report vor - **rein informativ, keine
Löschempfehlung dieser Phase**. Ob und welche der 12 automatisch
auflösbaren Gruppen tatsächlich per `--execute` bereinigt werden,
bleibt ein separater, eigens freizugebender nächster Schritt.
