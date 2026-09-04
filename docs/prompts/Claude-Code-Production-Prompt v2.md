# Claude-Code-Production-Prompt v2
## Phase 1 — Music Library Health Scanner

### 0. Rolle und Arbeitsmodus

Du arbeitest als **Senior Python Engineer / Software Architect / Code Auditor** innerhalb des bestehenden Projekts.

Repository:

`dkmd89-dev/musicbot`

Ziel dieser Phase ist die Implementierung eines **vollständig read-only arbeitenden Music Library Health Scanners**, der die bestehende Musikbibliothek analysiert und einen strukturierten Health Report erzeugt.

**WICHTIG:**
Die bestehende Architektur ist bereits weit entwickelt und wurde umfangreich auditiert und getestet.

Deine Aufgabe ist **nicht**, die Architektur neu zu erfinden.

Deine Aufgabe ist:

> Bestehende Architektur verstehen → vorhandene Funktionalität wiederverwenden → fehlende Analysefunktionalität gezielt ergänzen → vollständig testen → Read-only-Verhalten technisch nachweisen.

---

# 1. Primäres Ziel

Implementiere Phase 1:

> **Music Library Health Scanner**

Der Scanner soll die komplette konfigurierte Musikbibliothek analysieren und beantworten:

> **„Wie gesund ist meine Musikbibliothek und welche Dateien/Alben/Artists benötigen Aufmerksamkeit?“**

Der Scanner ist ausschließlich diagnostisch.

Er darf keine Reparaturen durchführen.

Die Pipeline lautet:

```text
DISCOVERY
    ↓
FILE ANALYSIS
    ↓
METADATA ANALYSIS
    ↓
STRUCTURAL ANALYSIS
    ↓
GROUP ANALYSIS
    ↓
ISSUE CLASSIFICATION
    ↓
HEALTH SCORING
    ↓
REPORT GENERATION
```

---

# 2. ABSOLUTE READ-ONLY REQUIREMENT

Dies ist die wichtigste technische Anforderung.

Während eines Library Health Scans darf die Musikbibliothek **unter keinen Umständen verändert werden**.

## Erlaubt

- Dateien lesen
- Verzeichnisse lesen
- Dateimetadaten lesen
- Mutagen zum Lesen verwenden
- ffprobe zum Lesen verwenden
- ffmpeg ausschließlich für Analyse/Probe verwenden, falls erforderlich
- eingebettete Cover lesen
- Hashes berechnen
- Metadaten analysieren
- Dateigrößen analysieren
- Dateipfade analysieren
- Reports erzeugen
- Logs erzeugen
- temporäre Analyseartefakte außerhalb der Musikbibliothek erzeugen, sofern notwendig
- interne Analyseobjekte/Caches erzeugen, sofern diese nicht die Library verändern

## Verboten

Der Scanner darf niemals:

- Dateien umbenennen
- Dateien verschieben
- Dateien löschen
- Dateien ersetzen
- Dateien überschreiben
- Dateien kopieren
- Tags schreiben
- Cover schreiben
- Lyrics schreiben
- Dateien re-encoden
- Dateien konvertieren
- Verzeichnisse erstellen/löschen/umbenennen
- Berechtigungen verändern
- bestehende Library-Dateien öffnen und schreibend behandeln
- Reparaturservices ausführen
- Metadata Writer verwenden
- Cover Writer verwenden
- Lyrics Writer verwenden
- Duplicate Resolver ausführen
- Cleanup-Funktionen ausführen
- bestehende Mutationspfade indirekt triggern

Insbesondere darf keine bestehende Service-Funktion verwendet werden, wenn deren interne Implementierung potentiell Schreiboperationen ausführt.

**„Ich rufe nur einen bestehenden Service auf“ ist keine ausreichende Sicherheitsgarantie.**

Der tatsächliche Codepfad muss überprüft werden.

---

# 3. PHASE 0 — VERPFLICHTENDE REPOSITORY-ANALYSE

## STOPPREGEL

**Implementiere noch keinen Code, bevor die bestehende Architektur und die relevanten Services analysiert wurden.**

Zuerst Repository analysieren.

Untersuche mindestens:

```text
services/
scripts/
handlers/
config/
tests/
docs/
```

sowie relevante Root-Dateien.

Besonders untersuchen:

- bestehende Metadata Services
- Tag Reader / Tag Writer
- ArtistNormalizer
- TitleCleaner
- GenreProcessor / GenreMapper
- Multi-Artist-Handling
- MusicBrainz Integration
- CoverProcessor
- LyricsProcessor
- Loudness / ReplayGain
- Duplicate Domain
- Library-/Filesystem-Services
- Logger
- Config
- bestehende Analyse-/Audit-Funktionen
- bestehende Models / DTOs / Value Objects
- bestehende Test-Fixtures
- bestehende Scripts

Referenzscripts:

```text
scripts/reprocess_artist_metadata.py
scripts/normalize_test_library_loudness.py
scripts/resolve_duplicates.py
```

Diese dürfen als Referenz für vorhandene Logik dienen.

Sie dürfen **nicht einfach kopiert oder parallel neu implementiert werden**.

---

# 4. REUSE-FIRST-PRINZIP

Vor jeder neuen Implementierung muss beantwortet werden:

1. Gibt es diese Funktionalität bereits?
2. Gibt es einen bestehenden Service dafür?
3. Gibt es bestehende Models / DTOs?
4. Gibt es bestehende Utilities?
5. Gibt es bestehende Parser?
6. Gibt es bestehende Normalizer?
7. Gibt es bestehende Tests, die das erwartete Verhalten dokumentieren?
8. Kann bestehende Funktionalität sicher read-only verwendet werden?
9. Falls nicht: Warum nicht?

Erstelle vor der Implementierung eine interne Reuse Map.

Beispiel:

```text
Requirement                  Existing Capability              Decision
---------------------------------------------------------------------------
Read audio tags              Existing Tag Reader              REUSE
Artist normalization        ArtistNormalizer                 REUSE
Genre normalization         GenreMapper                      REUSE
Cover inspection             CoverProcessor                  READ-ONLY ADAPTER
Duplicate identity           Duplicate domain                 REUSE
Loudness status              Existing loudness service        REUSE/ADAPTER
Filesystem discovery         Existing library utility         REUSE
Health scoring               None                              NEW
Issue classification         None                              NEW
Report serialization         None / partial                   NEW/REUSE
```

Wenn bestehende Services nicht sicher read-only verwendet werden können:

> Einen kleinen read-only Adapter implementieren.

Nicht den bestehenden Service umbauen, wenn dies unnötigen Blast Radius erzeugt.

---

# 5. ARCHITEKTUR-ENTSCHEIDUNG

Erzeuge **keine neue Verzeichnisstruktur nur aufgrund dieses Prompts**.

Insbesondere:

```text
services/library_health/
```

darf nur angelegt werden, wenn die Repository-Analyse ergibt, dass dies architektonisch tatsächlich sinnvoll ist.

Die Entscheidung muss begründet werden.

Bevorzugt:

```text
bestehende Domain-Struktur
        ↓
gezielte Ergänzung
        ↓
minimale neue Komponenten
```

Nicht:

```text
neues Feature
    ↓
neue komplette Architektur
    ↓
neue Models
    ↓
neue Services
    ↓
neue Utilities
    ↓
neue Abstraktionen
```

Keine unnötigen:

- Globals
- Singletons
- Abstraktionslayer
- Factory-Systeme
- Event-Systeme
- Dependency-Injection-Systeme
- Frameworks
- parallelen Service-Implementierungen

---

# 6. KONFIGURIERTE MUSIC LIBRARY

Der Scanner muss die **tatsächlich konfigurierte Music Library** analysieren.

Nicht hartcodieren.

Unterstütze optional:

```bash
python scripts/library_health_check.py
```

und:

```bash
python scripts/library_health_check.py \
    --library /path/to/music
```

Weitere Optionen:

```text
--output PATH
--json PATH
--verbose
```

Keine Mutationsoptionen implementieren.

Insbesondere NICHT:

```text
--fix
--repair
--delete
--execute
--apply
```

---

# 7. FILE DISCOVERY

Rekursiv alle unterstützten Audio-Dateien erkennen.

Unterstützte Formate müssen sich nach den bereits im Projekt verwendeten/konfigurierten Formaten richten.

Nicht eigenmächtig eine neue Formatpolitik definieren.

Für jede Datei erfassen:

```text
absolute_path
relative_path
filename
filename_stem
extension
file_size
parent_directory
artist_directory
album_directory
is_singles
```

Falls das Projekt eine definierte Library-Struktur besitzt, diese vorhandene Definition verwenden.

---

# 8. METADATA HEALTH

Für jede Audio-Datei analysieren:

```text
Artist
Album Artist
Title
Album
Year
Genre
Track Number
Disc Number
```

Zusätzlich, sofern vorhanden:

```text
MusicBrainz Recording ID
MusicBrainz Release ID
MusicBrainz Artist ID
ISRC
```

Nicht vorhandene Felder nicht automatisch als ERROR behandeln.

Die Severity muss fachlich sinnvoll klassifiziert werden.

---

# 9. ANALYSIS STATES

Unterscheide strikt zwischen:

```text
PRESENT
MISSING
INVALID
PARTIAL
NOT_ANALYZABLE
```

Beispiel:

Wenn ffprobe aufgrund eines defekten Files nicht ausgeführt werden kann:

```text
audio.status = NOT_ANALYZABLE
```

und nicht:

```text
audio.status = MISSING
```

Ebenso:

```text
Permission denied
Unsupported format
Parser failure
Corrupt container
```

müssen als Analysefehler erkennbar bleiben.

**Nicht analysierbar ≠ nicht vorhanden.**

---

# 10. LYRICS HEALTH

Lyrics nur diagnostizieren.

Kategorien:

```text
PRESENT
MISSING
EMPTY
INVALID
NOT_ANALYZABLE
```

Keine Lyrics suchen.

Keine Lyrics herunterladen.

Keine Lyrics schreiben.

---

# 11. ARTWORK HEALTH

Eingebettetes Artwork untersuchen.

Erfassen:

```text
present
mime_type
width
height
file_size
is_square
```

Diagnose unter anderem:

```text
ARTWORK_MISSING
ARTWORK_INVALID
ARTWORK_LOW_RESOLUTION
ARTWORK_NON_SQUARE
ARTWORK_SUSPICIOUS
```

Keine Cover-Suche.

Keine Cover-Ersetzung.

Keine externen APIs.

Keine Dateien schreiben.

---

# 12. MULTI-ARTIST HEALTH

Bestehende Multi-Artist-Konventionen des Projekts verwenden.

Analysiere insbesondere:

```text
Artist
Album Artist
```

sowie:

- mehrere Artists
- Semicolon-Delimitierung
- Komma-Delimitierung
- verdächtige String-Konkatenationen
- doppelte Artists
- inkonsistente Schreibweisen
- Artist ≠ Album Artist
- verdächtige Normalisierung
- offensichtliche Parsing-Probleme

Wichtig:

Nicht jede Abweichung ist automatisch ein Fehler.

Der Scanner diagnostiziert.

Er entscheidet nicht eigenmächtig, was „richtig“ sein muss.

---

# 13. GENRE HEALTH

Bestehende Genre-Konvention des Projekts verwenden.

Analysieren:

```text
missing
empty
single genre
multiple genres
wrong delimiter
inconsistent formatting
invalid values
```

Keine eigene parallele Genre-Normalisierung entwickeln.

Wenn `GenreMapper` oder ein bestehender Genre-Service vorhanden ist, dessen Verhalten analysieren und entsprechend wiederverwenden.

---

# 14. FILENAME / PATH HEALTH

Dateiname und Pfad gegen die bestehende Library-Konvention prüfen.

Analysieren:

- Filename vs Title
- Artist-Verzeichnis
- Album-Verzeichnis
- Singles-Struktur
- erwartete Hierarchie
- problematische Zeichen
- doppelte Leerzeichen
- inkonsistente Benennung
- falsche Dateiendung
- verdächtige Pfade
- Dateien außerhalb der erwarteten Struktur
- Singles-Sonderfälle

Nur diagnostizieren.

Keine automatische Korrektur.

Beispiel:

```text
STRUCTURE_INVALID_PATH
FILENAME_TITLE_MISMATCH
FILENAME_SUSPICIOUS
SINGLE_STRUCTURE_MISMATCH
```

---

# 15. AUDIO HEALTH

Wenn möglich `ffprobe` bevorzugen.

Analysieren:

```text
container
codec
audio_stream
bitrate
sample_rate
channels
duration
```

Zusätzlich:

```text
corrupt
missing_audio_stream
very_short
low_bitrate
```

Keine Re-Encoding-Operation.

Keine Audioänderung.

Wenn ffprobe nicht verfügbar ist:

```text
NOT_ANALYZABLE
```

statt falscher Fehlerdiagnose.

---

# 16. LOUDNESS / REPLAYGAIN

Vorhandene Projektlogik verwenden.

Nicht selbst ein neues Loudness-Schema erfinden.

Analysieren:

```text
MISSING
PRESENT
INVALID
PARTIAL
NOT_ANALYZABLE
```

Falls ReplayGain-/Loudness-Tags bereits vorhanden sind:

- Existenz prüfen
- Format prüfen
- offensichtliche Invalidität erkennen

Falls Berechnung erforderlich wäre:

> NICHT berechnen und NICHT schreiben.

Der Scanner ist Diagnose, kein Normalizer.

---

# 17. DUPLICATE ANALYSIS

Bestehende Duplicate-Domain untersuchen und nach Möglichkeit wiederverwenden.

Der Scanner darf Duplicate-Kandidaten erkennen.

Er darf sie **niemals auflösen**.

Unterscheide mindestens:

```text
EXACT_DUPLICATE
IDENTITY_DUPLICATE
SUSPECTED_DUPLICATE
```

### EXACT_DUPLICATE

Byte-identische Dateien.

Hash-basierte Erkennung.

### IDENTITY_DUPLICATE

Gleiche Musik-Identität, beispielsweise:

```text
MusicBrainz Recording ID
ISRC
```

### SUSPECTED_DUPLICATE

Beispielsweise:

```text
normalized Artist + normalized Title
```

Aber:

Remix / Live / Acoustic / Radio Edit / Extended Version etc. dürfen nicht blind als identisch behandelt werden.

Bestehende Duplicate-Regeln des Projekts haben Vorrang.

---

# 18. ALBUM CONSISTENCY

Dateien zu Alben gruppieren.

Pro Album prüfen:

```text
album name
album artist
year
cover
track count
track numbers
disc numbers
```

Zusätzlich:

```text
missing tracks
duplicate track numbers
gaps
different album artists
different years
different genres
different MusicBrainz Release IDs
cover inconsistencies
```

Beispiele:

```text
ALBUM_TRACK_GAP
ALBUM_DUPLICATE_TRACK_NUMBER
ALBUM_ARTIST_INCONSISTENT
ALBUM_YEAR_INCONSISTENT
ALBUM_RELEASE_ID_INCONSISTENT
ALBUM_COVER_INCONSISTENT
```

Wichtig:

Nicht jede Variation automatisch als ERROR klassifizieren.

Beispielsweise können unterschiedliche Genres innerhalb eines Albums legitim sein.

---

# 19. ARTIST CONSISTENCY

Auf Artist-Ebene diagnostizieren:

- Schreibvarianten
- offensichtliche Duplikate
- inkonsistente Normalisierung
- verdächtige Verzeichnisstrukturen
- unterschiedliche Artist-Namen für wahrscheinlich gleiche Artists

Bestehenden `ArtistNormalizer` analysieren.

Nicht automatisch umbenennen.

---

# 20. ISSUE SYSTEM

Issues benötigen stabile maschinenlesbare Codes.

Beispiele:

```text
META_ARTIST_MISSING
META_ALBUM_MISSING
META_TITLE_MISSING
META_ALBUM_ARTIST_MISSING
META_YEAR_MISSING
META_GENRE_MISSING

META_MB_RECORDING_MISSING
META_MB_RELEASE_MISSING
META_ISRC_MISSING

ARTWORK_MISSING
ARTWORK_INVALID
ARTWORK_LOW_RESOLUTION
ARTWORK_NON_SQUARE

LYRICS_MISSING
LYRICS_EMPTY
LYRICS_INVALID

AUDIO_NO_STREAM
AUDIO_CORRUPT
AUDIO_LOW_BITRATE
AUDIO_VERY_SHORT
AUDIO_NOT_ANALYZABLE

LOUDNESS_MISSING
LOUDNESS_INVALID
LOUDNESS_PARTIAL

STRUCTURE_INVALID_PATH
FILENAME_TITLE_MISMATCH
FILENAME_SUSPICIOUS

MULTI_ARTIST_SUSPICIOUS
MULTI_ARTIST_INCONSISTENT

GENRE_INVALID
GENRE_DELIMITER_INCONSISTENT

DUPLICATE_EXACT
DUPLICATE_RECORDING
DUPLICATE_SUSPECTED

ALBUM_TRACK_GAP
ALBUM_DUPLICATE_TRACK_NUMBER
ALBUM_ARTIST_INCONSISTENT
ALBUM_COVER_INCONSISTENT
ALBUM_RELEASE_ID_INCONSISTENT
```

Die endgültige Liste muss anhand des bestehenden Codes erweitert oder angepasst werden.

Issue-Codes müssen:

- stabil
- eindeutig
- dokumentiert
- testbar

sein.

---

# 21. SEVERITY

Verwende:

```text
INFO
WARNING
ERROR
CRITICAL
```

Grundprinzip:

### INFO

Interessante Beobachtung ohne tatsächliches Qualitätsproblem.

### WARNING

Möglicherweise problematisch.

### ERROR

Klarer Qualitätsmangel.

### CRITICAL

Library-/Dateizustand mit erheblicher funktionaler Bedeutung.

Nicht jede erkannte Abweichung darf automatisch ERROR werden.

---

# 22. OBSERVATION ≠ DEFECT

Sehr wichtig.

Ein Scanner darf zwischen:

```text
Observation
```

und:

```text
Defect
```

unterscheiden.

Beispiele:

```text
Album hat mehrere Genres
```

kann eine Observation sein.

```text
Album enthält Track 1, 2, 4
```

ist wahrscheinlich ein Defect.

```text
Artist != Album Artist
```

kann bei Compilation/Featuring legitim sein.

Keine überaggressive Scoring-Logik.

---

# 23. HEALTH SCORE

Erstelle einen zentral definierten Health Score.

Eigenschaften:

- deterministisch
- reproduzierbar
- dokumentiert
- testbar

Die gleiche Library mit identischem Zustand muss denselben Score ergeben.

Keine versteckten Gewichte.

Keine zufälligen Faktoren.

Keine dynamischen Gewichte.

Empfohlen:

```text
Library Score: 0–100
```

Zusätzlich:

```text
file_health_score
album_health_score
artist_health_score
library_health_score
```

Die Gewichtung muss zentral definiert sein.

Beispielsweise:

```text
CRITICAL → starke Reduktion
ERROR    → deutliche Reduktion
WARNING  → moderate Reduktion
INFO     → keine oder minimale Reduktion
```

INFO sollte grundsätzlich **nicht** als Qualitätsdefekt behandelt werden.

Dokumentiere die genaue Berechnung.

---

# 24. REPORT STRUCTURE

Erzeuge mindestens:

```text
library_health_report.json
```

und einen human-readable Report.

JSON muss eine stabile Schema-Version besitzen.

Beispiel:

```json
{
  "schema_version": "1.0",
  "scanner_version": "1.0",
  "scan": {
    "started_at": "...",
    "completed_at": "...",
    "duration_seconds": 0
  },
  "library": {
    "root": "...",
    "files": 0,
    "artists": 0,
    "albums": 0
  },
  "health": {
    "score": 0,
    "status": "..."
  },
  "statistics": {},
  "issues": [],
  "artists": [],
  "albums": [],
  "files": []
}
```

Die konkrete Struktur darf an die vorhandene Architektur angepasst werden.

Sie muss aber:

- stabil
- maschinenlesbar
- dokumentiert
- versioniert

sein.

---

# 25. ISSUE OBJECT

Ein Issue sollte mindestens ermöglichen:

```text
issue_code
severity
scope
path
artist
album
title
message
details
```

Optional:

```text
confidence
related_files
related_album
related_artist
```

Nicht unnötig duplizieren.

---

# 26. REPORT STATISTICS

Der Report soll mindestens ermöglichen:

```text
total_files
total_artists
total_albums

healthy_files
files_with_warnings
files_with_errors
files_not_analyzable

missing_metadata
missing_artwork
missing_lyrics
missing_loudness

duplicate_groups
album_inconsistencies
structure_problems
audio_problems
```

Zusätzlich:

```text
issues_by_code
issues_by_severity
```

---

# 27. PERFORMANCE

Die komplette Library kann groß sein.

Deshalb:

- keine unnötigen Rescans
- Tags möglichst einmal lesen
- ffprobe nicht mehrfach unnötig auf dieselbe Datei anwenden
- externe APIs vermeiden
- keine Cover-Suche
- keine MusicBrainz-Abfragen
- keine Lyrics-Abfragen
- keine Schreiboperationen
- keine unnötigen Hashes mehrfach berechnen

Hashes nur berechnen, wenn sie für Duplicate Detection tatsächlich benötigt werden.

Caching darf nur eingeführt werden, wenn es architektonisch sinnvoll ist.

Kein Cache-System nur „weil es schneller sein könnte“.

---

# 28. LOGGING

Bestehenden Logger verwenden.

Kein neues paralleles Logging-System.

Logging-Level sinnvoll verwenden.

Beispielsweise:

```text
SCAN START
FILE DISCOVERED
FILE ANALYZED
ISSUE DETECTED
SCAN SUMMARY
SCAN COMPLETE
```

Aber:

**Kein Log Flood.**

Nicht für jede einzelne Kleinigkeit unnötig INFO loggen.

`--verbose` darf zusätzliche Details aktivieren.

---

# 29. CLI

Implementiere:

```bash
python scripts/library_health_check.py
```

Optional:

```bash
python scripts/library_health_check.py --library /path
python scripts/library_health_check.py --output /path/report.txt
python scripts/library_health_check.py --json /path/report.json
python scripts/library_health_check.py --verbose
```

Das Script ist ausschließlich:

```text
CLI
    ↓
Configuration
    ↓
Scanner Orchestration
    ↓
Report Output
```

Keine Business Logic im Script.

Keine komplexe Analyse im Script.

Keine direkten API-Aufrufe.

Keine Writer-Aufrufe.

---

# 30. NAVIDROME

Phase 1 analysiert die **Filesystem Music Library**.

Nicht den Navidrome-Index.

Keine Navidrome API notwendig.

Keine Navidrome-Datenbank analysieren.

Keine Synchronisation implementieren.

Spätere Phase kann:

```text
Filesystem Library
        ↕
Navidrome Index
```

vergleichen.

Das ist NICHT Bestandteil dieser Phase.

---

# 31. TESTING

Tests sind ein zentraler Bestandteil.

Implementiere Tests für:

### Discovery

- unterstützte Dateien
- nicht unterstützte Dateien
- rekursive Verzeichnisse
- Singles
- Sonderpfade

### Metadata

- fehlender Artist
- fehlender Titel
- fehlendes Album
- fehlendes Genre
- fehlendes Jahr
- fehlende MBIDs
- ISRC

### Multi Artist

- einzelner Artist
- mehrere Artists
- bestehende Delimiter
- verdächtige Kombinationen

### Genre

- einzelnes Genre
- mehrere Genres
- falscher Delimiter
- leer
- ungültig

### Artwork

- kein Cover
- gültiges Cover
- falsches MIME
- niedrige Auflösung
- nicht quadratisch

### Audio

- gültige Datei
- fehlender Stream
- niedrige Bitrate
- sehr kurze Datei
- ffprobe failure
- corrupt/unreadable file

### Loudness

- vorhanden
- fehlend
- invalid
- partial

### Duplicate Detection

- exact duplicate
- same recording ID
- same ISRC
- suspected duplicate
- Remix darf nicht blind als Duplicate behandelt werden

### Album

- Track Gap
- Duplicate Track Number
- Disc Number
- Album Artist mismatch
- Release ID mismatch

### Scoring

- deterministisch
- severity weighting
- INFO beeinflusst Score nicht unangemessen
- identischer Input → identischer Score

### Reporting

- valid JSON
- schema version
- statistics
- issue codes
- severity
- deterministic structure

---

# 32. READ-ONLY SAFETY TEST

Dies ist ein Pflichtbestandteil.

Ein isoliertes Test-Library-Verzeichnis erzeugen.

Vor Scan:

```text
SHA256 aller Dateien
mtime
size
relative path
```

aufzeichnen.

Scan durchführen.

Danach erneut erfassen.

Erwartung:

```text
SHA256 vorher == SHA256 nachher
mtime vorher == mtime nachher
size vorher == size nachher
paths vorher == paths nachher
```

Keine Library-Datei darf verändert worden sein.

Wenn technisch möglich, zusätzlich sicherstellen, dass:

```text
keine Datei geöffnet wurde
```

während des Tests schreibend geöffnet.

Der Test muss die Read-only-Eigenschaft tatsächlich beweisen.

Nicht nur behaupten.

---

# 33. WRITER-SAFETY

Überprüfe die Import-/Call-Graph-Beziehungen.

Der Scanner darf nicht versehentlich folgende Komponenten triggern:

```text
Tag Writer
Cover Writer
Lyrics Writer
Metadata Reprocessor
Duplicate Resolver
Cleanup Service
Move/Rename Service
```

Wenn bestehende Services intern sowohl Read als auch Write enthalten:

> Nicht direkt verwenden.

Stattdessen:

```text
Read-only Adapter
```

oder vorhandene reine Read-Funktion verwenden.

---

# 34. ERROR HANDLING

Ein einzelnes defektes File darf den gesamten Scan nicht abbrechen.

Beispiel:

```text
10000 files
1 corrupt
```

Erwartung:

```text
9999 analyzed
1 NOT_ANALYZABLE
scan completes
```

Fehler müssen im Report sichtbar sein.

Keine stillen Exceptions.

Aber auch kein vollständiger Scan-Abbruch wegen eines einzelnen Problems.

---

# 35. DETERMINISMUS

Reports sollen bei gleichem Input möglichst deterministisch sein.

Sortiere:

- Dateien
- Artists
- Alben
- Issues

nach stabilen Schlüsseln.

Zeitstempel dürfen natürlich variieren.

Der eigentliche Analyseinhalt darf nicht zufällig variieren.

---

# 36. KEINE EXTERNEN APIs

Phase 1 verwendet:

```text
NO MusicBrainz API
NO Lyrics API
NO Cover API
NO YouTube API
NO Navidrome API
```

Der Scanner analysiert ausschließlich die vorhandenen Daten.

---

# 37. KEIN SMART REPAIR

Nicht implementieren:

```text
Repair Planner
Auto Fix
Metadata Rewrite
Cover Repair
Lyrics Repair
Duplicate Cleanup
Rename
Move
Delete
```

Diese Funktionen gehören in spätere Phasen.

Der Output dieser Phase soll später als Input für einen:

```text
Smart Repair Planner
```

dienen können.

---

# 38. EMPFOHLENE IMPLEMENTIERUNGSREIHENFOLGE

Nach der Repository-Analyse:

## Phase 1A

```text
Library Discovery
```

↓

## Phase 1B

```text
Read-only File Analysis
```

↓

## Phase 1C

```text
Album / Artist / Library Group Analysis
```

↓

## Phase 1D

```text
Issue Classification
```

↓

## Phase 1E

```text
Health Scoring
```

↓

## Phase 1F

```text
Report Generation
```

↓

## Phase 1G

```text
Safety + Regression Tests
```

Nicht alles gleichzeitig ungeprüft implementieren.

Nach jedem sinnvollen Teil:

```text
Tests
→ Analyse
→ nächster Teil
```

---

# 39. DOKUMENTATION

Dokumentiere mindestens:

```text
Architecture decision
Reuse decisions
Issue codes
Health scoring
JSON schema
Read-only guarantees
Known limitations
```

Falls das Projekt bereits eine entsprechende Dokumentationsstruktur besitzt:

> Diese verwenden.

Keine parallele Dokumentationsstruktur erzeugen.

---

# 40. GIT / CHANGE SCOPE

Arbeite fokussiert.

Keine unrelated refactors.

Keine kosmetischen Großumbauten.

Keine Formatierungsänderungen an fremden Dateien ohne Grund.

Keine „weil ich gerade dabei war“-Optimierungen.

Jede Änderung muss einen direkten Bezug zu Phase 1 haben.

---

# 41. STOP-BEDINGUNGEN

Breche die Implementierung und analysiere zunächst weiter, wenn:

- bestehende Architektur unklar ist
- bestehende Services widersprüchlich sind
- ein Read-only-Pfad nicht sicher gewährleistet werden kann
- eine neue Architektur notwendig erscheint
- ein bestehender Service unerwartete Schreiboperationen ausführt
- bestehende Business Rules nicht eindeutig sind
- Duplicate-Regeln unklar sind
- Genre-/Artist-Konventionen nicht eindeutig sind
- Health Scoring fachlich nicht sauber definierbar ist

In diesen Fällen:

> Problem dokumentieren, Optionen analysieren und erst danach entscheiden.

Nicht einfach raten.

---

# 42. ABSOLUTER ANTI-OVERENGINEERING-GRUNDSATZ

Dieses Feature soll wertvoll sein, nicht maximal komplex.

Bevor du eine neue Abstraktion einführst:

> „Brauche ich diese Abstraktion wirklich, oder kann ich bestehende Architektur direkt verwenden?“

Bevor du einen neuen Service erzeugst:

> „Existiert diese Verantwortung bereits an anderer Stelle?“

Bevor du eine neue Utility-Funktion erzeugst:

> „Existiert diese Funktion bereits?“

Bevor du einen neuen Cache einführst:

> „Ist Performance ohne Cache tatsächlich ein Problem?“

Bevor du Architektur veränderst:

> „Ist die bestehende Architektur wirklich ungeeignet?“

Default:

> **Minimal invasive implementation.**

---

# 43. ERWARTETER OUTPUT

Am Ende muss Claude Code einen strukturierten Abschluss liefern.

## IMPLEMENTED

Was wurde implementiert?

## ARCHITECTURE

Welche bestehenden Services wurden wiederverwendet?

Welche neuen Komponenten wurden eingeführt?

Warum?

## TESTS

Welche Tests wurden hinzugefügt?

Welche Tests wurden ausgeführt?

Ergebnis:

```text
X passed
Y failed
Z skipped
```

## READ-ONLY VERIFICATION

Wie wurde technisch bewiesen, dass die Library unverändert blieb?

Beispielsweise:

```text
Files before: X
Files after: X

SHA256 mismatches: 0
mtime changes: 0
size changes: 0
path changes: 0
```

## REPORT

Wo befindet sich:

```text
library_health_report.json
```

und der human-readable Report?

## FILES CHANGED

Liste aller geänderten/neuen Dateien.

## ARCHITECTURE IMPACT

Bewerte:

```text
NONE
LOW
MEDIUM
HIGH
```

und begründe.

## KNOWN LIMITATIONS

Welche Dinge werden bewusst noch nicht analysiert?

## NEXT PHASE

Welche logisch nächsten Schritte ergeben sich aus dem Report?

Keine automatische Implementierung dieser nächsten Phase.

---

# 44. FINAL QUALITY GATE

Bevor du die Arbeit als abgeschlossen deklarierst, führe folgende Checks durch:

```text
[ ] Repository analysiert
[ ] bestehende Services analysiert
[ ] Reuse Map erstellt
[ ] Architekturentscheidung dokumentiert
[ ] keine unnötige neue Architektur
[ ] vollständige Library Discovery
[ ] Metadata Analysis
[ ] Artwork Analysis
[ ] Lyrics Analysis
[ ] Audio Analysis
[ ] Loudness Analysis
[ ] Multi Artist Analysis
[ ] Genre Analysis
[ ] Filename/Path Analysis
[ ] Duplicate Analysis
[ ] Album Consistency
[ ] Artist Consistency
[ ] Issue Classification
[ ] Severity
[ ] deterministic Health Score
[ ] JSON Report
[ ] Human-readable Report
[ ] stabile Schema-Version
[ ] bestehender Logger verwendet
[ ] keine externen APIs
[ ] keine Repair-Funktionen
[ ] keine Writer aufgerufen
[ ] Read-only Safety Tests
[ ] isolierte Test-Library
[ ] SHA256 vorher/nachher
[ ] mtime vorher/nachher
[ ] size vorher/nachher
[ ] path vorher/nachher
[ ] Full Test Suite
[ ] Regression Tests
[ ] Dokumentation
[ ] Git Diff geprüft
[ ] keine unrelated Änderungen
```

---

# 45. WICHTIGSTE REGEL

Wenn du zwischen:

```text
„mehr Funktionalität“
```

und:

```text
„bestehende Architektur sauber respektieren“
```

wählen musst:

> **Bestehende Architektur respektieren.**

Wenn du zwischen:

```text
„automatisch reparieren“
```

und:

```text
„präzise diagnostizieren“
```

wählen musst:

> **Präzise diagnostizieren.**

Wenn du zwischen:

```text
„schnell etwas implementieren“
```

und:

```text
„erst verstehen, dann implementieren“
```

wählen musst:

> **Erst verstehen, dann implementieren.**

---

# 46. START

Beginne jetzt ausschließlich mit:

## STEP 1 — Repository Analysis

Analysiere:

```text
services/
scripts/
tests/
docs/
config/
```

und alle relevanten bestehenden Komponenten.

Erstelle daraus intern:

```text
1. Architecture Map
2. Reuse Map
3. Read-only Safety Map
4. Gap Analysis
5. Proposed Implementation Plan
```

**Noch keinen Implementierungscode schreiben.**

Erst wenn diese Analyse abgeschlossen ist:

1. bestehende Architektur erklären
2. vorhandene wiederverwendbare Komponenten identifizieren
3. notwendige neue Komponenten identifizieren
4. Architekturimpact bewerten
5. Implementierungsplan festlegen
6. danach erst implementieren

---

# DEFINITION OF DONE

Phase 1 ist nur dann abgeschlossen, wenn:

> Die komplette konfigurierte Music Library deterministisch und vollständig read-only analysiert werden kann, relevante Qualitätsprobleme mit stabilen Issue-Codes klassifiziert werden, ein reproduzierbarer Health Score erzeugt wird, ein maschinenlesbarer JSON Report entsteht und technisch nachgewiesen wurde, dass der Scan keine Library-Dateien verändert.