# MusicBot Engineering Baseline

**Repository:** `dkmd89-dev/musicbot`  
**Branch:** `main`  
**Baseline-Datum:** 2026-08-16

## Zweck

Diese Baseline hält den aktuellen technischen Ausgangszustand fest, bevor weitere Optimierungen oder Refactorings erfolgen.

Grundregel:

> Erst verstehen → dann testen → dann verbessern.

---

## 1. Projektstatus

Die README beschreibt das Projekt aktuell nur als „Musikdownloader mit Telegram funktion und Navidrome“. fileciteturn31file0L2-L2

Die Repository-Struktur zeigt jedoch ein deutlich größeres gewachsenes System mit:

- Telegram-Bot und RichMenu
- YouTube- und Spotify-Verarbeitung
- Metadaten-Pipeline
- Artist- und Genre-System
- Lyrics und Cover-Art
- MusicBrainz / Last.fm
- Caches
- Duplikaterkennung
- Library-Organisation
- FFmpeg/Audioverarbeitung
- Navidrome
- Statistiken
- Administration
- Backup/Restart
- Error Handling und Logging
- Migrationen
- Tests
- YAML-/JSON-basierter Fachlogik

**Einordnung:** Das Projekt ist inzwischen ein echtes Softwaresystem, auch wenn es ursprünglich als Hobbyprojekt gewachsen ist.

---

# 2. Architektur-Baseline

```text
Telegram
   │
   ▼
ExtendedBot / bot.py
   │
   ▼
RichMenuHandler
   │
   ├── Menü / Admin / Statistik
   │
   └── DownloadHandler
          │
          ├── YouTube
          └── Spotify
                  │
                  ▼
        Metadata Pipeline
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Artist    Genre     Lyrics
        │         │         │
        └─────────┼─────────┘
                  ▼
        MusicBrainz / Cover
                  │
                  ▼
          Audio / FFmpeg
                  │
                  ▼
        Library / Metadata
                  │
                  ▼
              Navidrome
```

`bot.py` zeigt die zentrale Initialisierung von Telegram Application, Error Handler, RichMenuHandler und Telegram Handlern. fileciteturn33file0L2-L2

---

# 3. Kritische Geschäftsabläufe

## P0 – Download

```text
URL
 ↓
Erkennung
 ↓
Download
 ↓
Metadaten
 ↓
Library
```

## P0 – Metadata

```text
Track
 ↓
Cache
 ↓
Parsing
 ↓
Artist
 ↓
Title
 ↓
Genre
 ↓
Lyrics
 ↓
MusicBrainz
 ↓
Cover
 ↓
Album/Jahr
 ↓
Audio
 ↓
Tags
```

## P0 – Duplicate Detection

```text
URL
 ↓
Normalisierung
 ↓
URL-Duplikat
 ↓
Artist/Titel
 ↓
Parser
 ↓
Library-Fallback
```

## P1 – Telegram

```text
Update
 ↓
Handler
 ↓
Menu/Command
 ↓
Service
 ↓
Response
```

---

# 4. Risikobaseline

| ID | Risiko | Priorität | Status |
|---|---|---:|---|
| SEC-001 | Sensible Daten in Request-Logs möglich | P0 | offen |
| TEST-001 | Teile der Tests testen nicht direkt Produktionsimplementierungen | P0 | offen |
| E2E-001 | Hauptpfad nicht ausreichend Ende-zu-Ende abgesichert | P0 | offen |
| CFG-001 | Config enthält Import-/Initialisierungslogik | P1 | offen |
| ARCH-001 | Große Orchestrator-Klassen | P1 | offen |
| CACHE-001 | Mehrere Cache-/Normalisierungswege | P1 | offen |
| DOC-001 | README dokumentiert System kaum | P1 | offen |
| LEGACY-001 | Legacy-/Kompatibilitätsschichten | P2 | offen |

---

# 5. Sicherheits-Baseline

`config.py` lädt sensible Werte über `.env` bzw. Umgebungsvariablen. Das ist grundsätzlich die richtige Richtung. fileciteturn32file0L2-L2

### SEC-001

Bei der Navidrome-API muss geprüft werden, ob Request-Parameter mit Credentials vollständig geloggt werden.

**Ziel:**

```text
Passwort / Token
      ↓
niemals normaler Log-Output
```

Geplanter Regressionstest:

```python
def test_navidrome_credentials_are_not_logged():
    ...
```

---

# 6. Test-Baseline

Es existiert bereits ein `tests/`-Bereich. Die vorhandene `conftest.py` stellt beispielsweise eine `Config`-Fixture bereit. fileciteturn34file0L2-L2

Das bedeutet: Wir starten nicht bei null.

### Aber

`tests/test_genre_processor.py` enthält eine eigene `GenreProcessor`-Implementierung sowie Mock-Module. fileciteturn35file0L2-L2

Damit muss dieser Testbereich überprüft werden, bevor daraus echte Produktionsabdeckung abgeleitet wird.

---

# 7. Teststrategie

## Stufe 1 – Characterization Tests

Zuerst wird das aktuelle Verhalten eingefroren.

Beispiele:

```python
def test_artist_parser_current_behavior():
    ...

def test_genre_mapping_current_behavior():
    ...

def test_duplicate_detection_current_behavior():
    ...

def test_filename_generation_current_behavior():
    ...
```

Ziel:

> Der Test beschreibt, was das System heute tatsächlich macht.

Nicht:

> Der Test beschreibt, was wir glauben, dass es machen sollte.

---

# 8. P0-Testumfang

### Metadata

- Artist Extraction
- Title Extraction
- Genre Selection
- MetadataResult
- Cache Hit
- Cache Miss

### Duplicate

- gleiche URL
- gleiche YouTube-ID
- gleicher Artist/Titel
- Parser-Fallback
- vorhandene Library-Datei

### Files

- Filename
- Directory
- Extension
- Metadata Writing
- fehlende Datei
- bereits vorhandene Datei

### Security

- Credentials niemals im Log

---

# 9. P1-Testumfang

- YouTube Download
- Spotify Download
- Lyrics Fallback
- MusicBrainz Fallback
- Cover Fallback
- Loudness Failure
- Navidrome API
- Telegram Handler Routing

# 10. P2-Testumfang

- Admin
- Backup
- Restart
- Statistik
- Logging UI
- Migrationen

---

# 11. Testpyramide

```text
                 /\
                /E2E\
               /----\
              /Integration\
             /------------\
            /  Unit Tests  \
           /----------------\
```

Der Großteil der Tests soll schnell und isoliert sein.

Externe Dienste werden in Unit-Tests nicht real angesprochen.

Stattdessen:

```text
Core Logic
    │
    ├── External Adapter
    │
    └── Fake / Mock
```

---

# 12. Konfigurations-Baseline

`config.py` enthält unter anderem:

- Library
- Downloads
- Processing
- Fail
- Archive
- Metadata Cache
- Duplicate Cache
- Lyrics Cache
- Logs
- History
- Statistics
- Mapping
- Spotify
- Backups
- Secrets
- Feature Flags

Die Konfiguration ist damit ein zentraler Bestandteil des Systems. fileciteturn32file0L2-L2

Langfristiges Ziel:

```text
import config
```

soll möglichst wenige Seiteneffekte verursachen.

**Aber:** Das ist kein erster Refactoring-Schritt.

---

# 13. Mapping-Baseline

Artist- und Genre-YAML/JSON-Dateien beeinflussen das fachliche Verhalten.

Daher behandeln wir Mapping-Änderungen künftig wie Codeänderungen:

```text
Mapping ändern
     ↓
Test
     ↓
Review
```

Besonders relevant:

- Genre Aliases
- Genre Filters
- Genre Hierarchy
- Genre Rules
- Genre Overrides
- Artist Overrides
- Known Artists
- Channel Rules
- Auto-Learning

---

# 14. Cache-Baseline

Wichtige getrennte Cache-Bereiche:

```text
Metadata
Duplicate
Lyrics
History / Stats
```

Bei zukünftigen Änderungen müssen insbesondere diese Fälle getestet werden:

```text
Cache Hit
Cache Miss
Cache Invalid
Cache Stale
Cache Write Failure
```

---

# 15. Observability-Baseline

Das Projekt besitzt bereits umfangreiches Logging.

Das ist ein großer Vorteil für die weitere Entwicklung.

Ziel für kritische Abläufe:

```text
Input
 ↓
Decision
 ↓
Transformation
 ↓
External Call
 ↓
Fallback
 ↓
Output
```

Dabei dürfen keine Secrets in Logs gelangen.

---

# 16. Änderungsregeln

### Regel 1

Kein größerer Refactor ohne vorherige Tests.

### Regel 2

Bestehendes Verhalten nicht „nebenbei“ ändern.

### Regel 3

Mapping-Änderungen sind fachliche Änderungen.

### Regel 4

Fehler möglichst zuerst reproduzieren, dann beheben.

### Regel 5

Jeder kritische Bug-Fix bekommt einen Regressionstest.

### Regel 6

Dokumentation wird aktualisiert, wenn sich beobachtbares Verhalten oder öffentliche Schnittstellen ändern.

---

# 17. Empfohlene Reihenfolge

## Phase 0 – Baseline

**Jetzt abgeschlossen.**

- Architektur
- kritische Abläufe
- Risiken
- Teststrategie
- Dokumentationsgrundlage

## Phase 1 – Sicherheitsnetz

1. Logging-Secrets prüfen/entfernen
2. Produktionslogik-Tests herstellen
3. Metadata Characterization Tests
4. Duplicate Characterization Tests
5. File/Library Characterization Tests
6. erster reproduzierbarer Happy Path

## Phase 2 – Kernsystem

```text
Metadata
Duplicate
Filename
Cache
Genre
Artist
```

## Phase 3 – Integrationen

```text
YouTube
Spotify
MusicBrainz
Lyrics
Cover
Navidrome
Telegram
```

## Phase 4 – Refactoring

Erst danach:

```text
große Klassen
 ↓
kleinere Services
 ↓
klare Schnittstellen
 ↓
weniger Kopplung
```

---

# 18. Definition of Done

Eine Änderung ist grundsätzlich abgeschlossen, wenn:

```text
[ ] Verhalten verstanden
[ ] Änderung implementiert
[ ] Regressionstest vorhanden
[ ] relevante Tests grün
[ ] Logs geprüft
[ ] keine Secrets im Log
[ ] Dokumentation aktualisiert, falls nötig
```

---

# 19. Erfolgsdefinition

Das Ziel ist **nicht** blind 100 % Test-Coverage.

Das Ziel ist:

> **Vertrauen in die kritischen Geschäftsabläufe.**

Wir wollen letztlich sicher ändern können:

```text
Metadata
Genre
Artist
Duplicate Detection
Download
Library
```

ohne befürchten zu müssen, unbemerkt an einer anderen Stelle Funktionalität zu zerstören.

---

# 20. Baseline-Status

**MusicBot Engineering Baseline: ANGELEGT**

### P0
- [ ] SEC-001 prüfen
- [ ] TEST-001 beheben
- [ ] Metadata Characterization Tests
- [ ] Duplicate Characterization Tests
- [ ] File/Library Characterization Tests
- [ ] erster reproduzierbarer End-to-End-Happy-Path

### P1
- [ ] Config Side Effects untersuchen
- [ ] Cache-Verträge dokumentieren
- [ ] externe Adapter inventarisieren
- [ ] Download-Pipelines testen
- [ ] Navidrome Integration testen

### P2
- [ ] Legacy reduzieren
- [ ] große Orchestratoren refactoren
- [ ] Zielarchitektur schrittweise umsetzen

---

## Leitprinzip

> **Erst verstehen → dann testen → dann verbessern.**

Der MusicBot wird nicht neu geschrieben.

Er wird kontrolliert weiterentwickelt.
