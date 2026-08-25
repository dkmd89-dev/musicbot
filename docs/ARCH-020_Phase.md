@GitHub

# MUSICBOT – ARCH-020
# Download-Pipeline Characterization & Orchestration Boundary

## AUFGABE

Führe jetzt ausschließlich ARCH-020 durch:

> Characterization der aktuellen Download-Pipeline und eindeutige Bestimmung ihrer Orchestrierungs- und Verantwortungsgrenzen.

Das Ziel ist NICHT, die Download-Pipeline jetzt zu refaktorieren.

Das Ziel ist herauszufinden:

1. Wie die Download-Pipeline im aktuellen Code tatsächlich funktioniert.
2. Welche Komponenten welche Verantwortung besitzen.
3. Wo fachliche Logik und technische Infrastruktur vermischt sind.
4. Wer aktuell wirklich orchestriert.
5. Welche Verantwortlichkeiten doppelt oder überlappend vorhanden sind.
6. Welche Teile bereits architektonisch korrekt sind.
7. Welche konkreten Architekturgrenzen für die spätere Migration gelten sollen.

Erst nach dieser Analyse darf ein späterer ARCH-Schritt die eigentliche Migration durchführen.

==================================================
1. ABSOLUTES ARBEITSVERBOT
==================================================

In dieser Aufgabe:

❌ KEINE Codeänderungen
❌ KEINE Refactorings
❌ KEINE Dateien verschieben
❌ KEINE Klassen umbenennen
❌ KEINE neuen Services implementieren
❌ KEINE Interfaces einführen
❌ KEINE Tests verändern
❌ KEINE Legacy-Dateien löschen
❌ KEINE "Verbesserungen nebenbei"
❌ KEINE Architektur automatisch implementieren

Erlaubt:

✅ Repository analysieren
✅ Codepfade verfolgen
✅ Abhängigkeiten analysieren
✅ Tests untersuchen
✅ Dokumentation vergleichen
✅ Architekturdiagramme erstellen
✅ Verantwortlichkeiten bewerten
✅ konkrete Zielgrenzen definieren
✅ Migrationsplan für einen späteren Schritt erstellen

Der Git-Working-Tree muss nach der Analyse unverändert bleiben.

==================================================
2. ARCHITEKTURHISTORIE IST ZU BERÜCKSICHTIGEN
==================================================

Analysiere zuerst:

- README.md
- CLAUDE.md
- docs/
- Download_Pipeline.txt
- sämtliche relevanten ARCH-*.md
- aktuelle Projektstruktur
- aktuelle Implementierung
- relevante Tests

WICHTIG:

ARCH-003 ist NICHT mehr automatisch die aktuelle Architekturgrundlage.

Berücksichtige alle späteren Architekturentscheidungen.

Insbesondere:

- bisherige Orchestrierungsentscheidungen
- ARCH-009 / Service-Grenzen
- ARCH-017 Download-/Audio-Characterization
- ARCH-018 Duplicate-Characterization und Duplicate-Core-Extraction
- ARCH-019 Genre-/Client-Characterization
- alle späteren Entscheidungen im Repository

Wenn Dokumentation und Code voneinander abweichen:

1. Dokumentation identifizieren
2. aktuellen Code prüfen
3. Tests prüfen
4. tatsächlichen Ist-Zustand bestimmen
5. Abweichung dokumentieren

NICHT einfach die Dokumentation als Wahrheit übernehmen.

==================================================
3. ZIEL VON ARCH-020
==================================================

ARCH-020 soll folgende Frage eindeutig beantworten:

> "Wie sieht die tatsächliche Download-Pipeline heute aus und wo soll ihre fachliche Orchestrierungsgrenze zukünftig liegen?"

Nicht:

> "Wie können wir den Downloader schöner strukturieren?"

Nicht:

> "Wie können wir Clean Architecture einführen?"

Nicht:

> "Welche Klassen können wir kleiner machen?"

Sondern:

> Welche bestehenden Verantwortlichkeiten gehören zusammen und welche müssen voneinander getrennt werden?

==================================================
4. ECHTEN END-TO-END-DOWNLOADPFAD REKONSTRUIEREN
==================================================

Verfolge mindestens einen vollständigen Single-Track-Download vom Eingang bis zum finalen Ergebnis.

Ausgangspunkt:

Telegram / YouTube URL

bis:

Library-Datei
+
Metadaten
+
Cover
+
Lyrics
+
Duplicate-Registrierung
+
Telegram-Ergebnis

Rekonstruiere den tatsächlichen Ablauf aus dem Code.

Untersuche insbesondere:

- URL-Eingang
- URL-/Formatvalidierung
- Duplicate Check
- Download
- yt-dlp
- Artifact-Erzeugung
- Download-Ergebnis
- Parsing
- Metadata Matching
- MusicBrainz
- Genre
- Lyrics
- Cover
- Audio Enhancement
- Tagging
- FilenameFixer
- Library-Organisation
- Duplicate Registration
- Result Reporting

WICHTIG:

Der Ablauf aus dem Produktionslog ist nur Runtime-Evidenz.

Der Code entscheidet über die tatsächliche Architektur.

==================================================
5. KOMPONENTEN VOLLSTÄNDIG ANALYSIEREN
==================================================

Untersuche mindestens:

- DownloadHandler
- YoutubeDownloader
- DownloadUtils
- DownloadExecutor
- EnhancedDownloadProcessor
- PlaylistProcessor
- SpotifyDownloader
- DownloadResultReporter
- Download Artifact/Cleanup-Komponenten
- Progress Tracker
- Metadata Result Translator
- DuplicateDetector
- DuplicateCache
- EnhancedDuplicateHandler
- MusicBrainzClient
- GeniusClient
- LastFMClient
- GenreProcessor
- GenreMapper
- LyricsProcessor
- CoverProcessor
- AudioEnhancer
- TagWriter
- FilenameFixerTool
- relevante Cache-Komponenten

Nicht automatisch alle diese Komponenten als "problematisch" betrachten.

Für jede relevante Komponente:

| Komponente | Verantwortung | Wird von aufgerufen | ruft auf | fachlich/technisch | Seiteneffekte | Zielrolle |
|------------|---------------|---------------------|----------|-------------------|---------------|-----------|

==================================================
6. BESONDERS WICHTIG: ORCHESTRIERUNG
==================================================

Bestimme anhand des tatsächlichen Call Graphs:

Wer orchestriert aktuell?

Prüfe insbesondere:

DownloadHandler
YoutubeDownloader
DownloadUtils
EnhancedDownloadProcessor
Metadata Processor

Frage:

- Wer startet den Workflow?
- Wer entscheidet über den nächsten Verarbeitungsschritt?
- Wer besitzt Retry-Logik?
- Wer besitzt Download-Logik?
- Wer besitzt Metadata-Orchestrierung?
- Wer besitzt Library-Organisation?
- Wer besitzt Reporting?
- Wer besitzt Persistence?
- Wo werden Ergebnisse zusammengeführt?

Erstelle anschließend:

## CURRENT ORCHESTRATION GRAPH

mit tatsächlichen Klassen/Methoden.

==================================================
7. WICHTIG: PRODUKTIONSLOG GEGEN CODE PRÜFEN
==================================================

Nutze folgenden beobachteten Produktionsablauf als Hinweis:

Telegram
→ DownloadHandler
→ Duplicate
→ YoutubeDownloader
→ DownloadUtils
→ DownloadExecutor
→ Metadata
→ MusicBrainz
→ Genre
→ Genius
→ Cover
→ Audio Enhancement
→ FilenameFixer
→ Library
→ Duplicate Registration
→ Result Reporter

Der Produktionslog enthält außerdem:

DownloadHandler
→ STEP 4/6 Metadaten anreichern

Prüfe deshalb ausdrücklich:

Existiert tatsächlich eine doppelte Metadata-Verarbeitung?

Oder ist dies nur:

- Übergabe eines bereits erzeugten Ergebnisses?
- Übersetzung eines Result-Objekts?
- historische Kompatibilität?
- Reporting?
- tatsächliche erneute Verarbeitung?

NICHT anhand der Logausgabe spekulieren.

Verfolge den Code.

==================================================
8. FACHLICH VS. TECHNISCH
==================================================

Ordne die Logik in Kategorien ein:

### Application / Orchestration

Beispielsweise:

- Workflow
- Reihenfolge
- Fehlerbehandlung
- Retry
- Ergebniszusammenführung

### Domain / Fachlogik

Beispielsweise:

- Artist/Track-Ermittlung
- Metadata-Entscheidungen
- Genre-Entscheidungen
- Duplicate-Entscheidungen
- Library-Regeln

### Infrastructure

Beispielsweise:

- yt-dlp
- MusicBrainz API
- Genius API
- Last.fm API
- Cover Art Archive
- FFmpeg
- Filesystem
- Telegram
- Navidrome

### Presentation

Beispielsweise:

- Telegram Messages
- Menüs
- Buttons
- Statusmeldungen
- Result Formatting

Für jede Vermischung:

- konkrete Datei
- konkrete Klasse/Methode
- konkrete Abhängigkeit
- Problem
- Priorität

==================================================
9. TELEGRAM-ENTKOPPLUNG
==================================================

Prüfe:

Kann der fachliche Download-Workflow theoretisch ohne Telegram ausgeführt werden?

Oder hängen Services/Fachlogik noch direkt an:

- Update
- Message
- Chat-ID
- CallbackQuery
- Telegram Bot API
- Telegram-specific result objects?

Klassifiziere:

🟢 sauber getrennt
🟡 teilweise gekoppelt
🔴 fachlich abhängig von Telegram

NICHT ändern.

==================================================
10. EXTERNE SYSTEME
==================================================

Prüfe alle Grenzen:

yt-dlp
MusicBrainz
Last.fm
Genius
Cover Art Archive
FFmpeg
Filesystem
Navidrome
Telegram

Für jede Integration:

- Wo beginnt der externe Adapter?
- Wo endet er?
- Welche Fachlogik kennt den Client?
- Gibt der Client rohe API-Daten weiter?
- Werden externe Modelle in der Fachlogik verwendet?

Ziel:

Externe Systeme sollen später austauschbar sein, ohne die zentrale Download-Orchestrierung unnötig zu verändern.

Aber:

KEINE künstlichen Abstraktionen vorschlagen, wenn kein konkretes Problem besteht.

==================================================
11. DOMAIN-MODELLE
==================================================

Analysiere die Daten, die durch die Pipeline fließen.

Insbesondere:

- Download Request
- URL
- Download Artifact
- Track
- Metadata
- Metadata Result
- Processing Result
- Cover
- Lyrics
- Library Result
- Download Result
- Duplicate Result

Prüfe:

Werden Dictionaries oder unstrukturierte Daten über viele Schichten weitergereicht?

Sind Modelle an Telegram gekoppelt?

Sind Modelle an yt-dlp gekoppelt?

Sind Modelle an konkrete APIs gekoppelt?

Welche Modelle sind bereits stabil?

Welche Modelle sollten NICHT verändert werden?

==================================================
12. DUPLICATE-ARCHITEKTUR NICHT ZURÜCKBAUEN
==================================================

ARCH-018 ist bereits umgesetzt.

Berücksichtige die aktuelle Struktur:

services/duplicate/
    cache.py
    detector.py

Der Telegram Duplicate Handler ist Präsentation/Delegation.

Der DownloadHandler verwendet den fachlichen DuplicateDetector.

Diese Architekturentscheidung gilt als Referenz.

Nicht wieder rückgängig machen.

Nutze sie als Beispiel dafür, wie zukünftige Entkopplungen aussehen könnten.

==================================================
13. GENRE-ARCHITEKTUR NICHT UNNÖTIG NEU ERFINDEN
==================================================

ARCH-019 und der aktuelle GenreProcessor/GenreMapper sind zu berücksichtigen.

Prüfe nur:

- Welche Verantwortung liegt im GenreProcessor?
- Welche Verantwortung liegt in externen Clients?
- Gibt es noch Reverse Dependencies?
- Gibt es doppelte Genre-Logik?

Nicht automatisch neu strukturieren.

==================================================
14. TESTARCHITEKTUR
==================================================

Analysiere alle relevanten Tests für die Download-Pipeline.

Erstelle:

| Bereich | vorhandene Tests | Testart | abgesichertes Verhalten | Refactoring-Risiko |
|---------|-------------------|---------|-------------------------|--------------------|

Besonders bestimmen:

Welche Tests sind Characterization Tests?

Welche Tests schützen das bestehende Produktionsverhalten?

Welche Bereiche dürfen später relativ sicher migriert werden?

Welche benötigen zuerst zusätzliche Tests?

==================================================
15. ARCHITEKTUR-ABHÄNGIGKEITEN
==================================================

Erstelle einen Dependency Graph.

Mindestens:

handlers
services
clients
utils
mapping
config
tests

Markiere:

🟢 erlaubte Abhängigkeit
🟡 tolerierte Übergangsabhängigkeit
🔴 Architekturverletzung

Besonders suchen:

services → handlers
domain/fachlogik → Telegram
domain/fachlogik → yt-dlp
domain/fachlogik → konkrete API
clients → handlers
Reverse Dependencies
zyklische Imports

==================================================
16. ZIELARCHITEKTUR – NUR DEFINIEREN, NICHT IMPLEMENTIEREN
==================================================

Nach der Analyse:

Definiere die konkrete Zielarchitektur für die Download-Pipeline.

Die Zielarchitektur soll aus dem bestehenden MusicBot entstehen.

Keine generische Clean-Architecture-Schablone.

Beschreibe:

### Presentation

Telegram Handler

↓

### Application / Workflow

Download Workflow / Orchestrator

↓

### Domain Services

Duplicate
Metadata
Genre
Library Rules
etc.

↓

### Infrastructure

yt-dlp
MusicBrainz
Genius
Last.fm
Cover
FFmpeg
Filesystem
Navidrome

Diese Struktur ist nur eine Hypothese.

Wenn der Code eine bessere Struktur nahelegt, begründe die Abweichung.

==================================================
17. WICHTIGSTE ENTSCHEIDUNG
==================================================

Beantworte ausdrücklich:

## MUSS DIE DOWNLOAD-PIPELINE JETZT REFAKTORIERT WERDEN?

Mögliche Antworten:

A) Ja – sofort

B) Ja – aber erst nach Characterization einzelner Teilbereiche

C) Nein – aktuelle Struktur ist ausreichend

D) Nur gezielte Extraktionen

Begründe anhand konkreter Codebefunde.

Meine Erwartung darf NICHT deine Entscheidung beeinflussen.

==================================================
18. MIGRATION NICHT DURCHFÜHREN
==================================================

Erstelle lediglich einen späteren Migrationsplan.

Beispiel:

ARCH-021
Metadata Boundary

ARCH-022
Download Orchestrator

ARCH-023
Legacy Cleanup

Aber nur wenn die Analyse diese Schritte tatsächlich rechtfertigt.

Für jeden vorgeschlagenen Schritt:

- Problem
- betroffene Dateien
- Ziel
- Risiko
- benötigte Tests
- Abhängigkeiten
- erwartetes Ergebnis

==================================================
19. PRIORISIERUNG
==================================================

Bewerte Befunde:

P0 = Zielarchitektur blockiert
P1 = wichtige Architekturverletzung
P2 = mittelfristige Verbesserung
P3 = optional/kosmetisch

Keine kosmetischen Refactorings als P0/P1.

==================================================
20. ERWARTETER ABSCHLUSSBERICHT
==================================================

Erstelle einen detaillierten Bericht:

# ARCH-020 – Download Pipeline Characterization

## 1. Executive Summary

## 2. Architekturhistorie

Welche Entscheidungen aus früheren ARCH-Dokumenten betreffen die Download-Pipeline?

## 3. Aktuelle Download-Pipeline

End-to-End-Ablauf.

## 4. Current Call Graph

Tatsächlicher Aufrufpfad.

## 5. Komponentenmatrix

Verantwortlichkeiten und Abhängigkeiten.

## 6. Orchestrierungsanalyse

Wer orchestriert tatsächlich?

## 7. Fachlich vs. technisch

Welche Grenzen existieren bereits?

## 8. Telegram-Kopplung

## 9. External-System Boundaries

## 10. Daten-/Domain-Modelle

## 11. Test Coverage / Characterization

## 12. Dependency Violations

## 13. Bereits korrekte Architektur

Ganz wichtig:

Nicht nur Probleme nennen.

Dokumentiere explizit, was NICHT geändert werden sollte.

## 14. Architekturprobleme

P0–P3

## 15. Zielarchitektur

Konkretes Architekturdiagramm.

## 16. Zielrollen der bestehenden Komponenten

Beispiel:

DownloadHandler → Telegram Adapter
YoutubeDownloader → Acquisition Adapter / Service
...
 
Nur wenn die Analyse dies bestätigt.

## 17. Empfohlene Migration

ARCH-021+
 
## 18. Was NICHT migriert werden sollte

## 19. Risiken

## 20. Final Decision

Beantworte:

1. Wer soll künftig orchestrieren?
2. Welche Komponenten gehören in Application?
3. Welche gehören in Domain?
4. Welche gehören in Infrastructure?
5. Welche bleiben im Handler?
6. Welche bestehenden Komponenten sind bereits korrekt?
7. Muss die Download-Pipeline refaktoriert werden?
8. Wenn ja: welcher kleinste sinnvolle nächste Schritt?
9. Welche Tests müssen vor diesem Schritt existieren?
10. Welche Teile dürfen ausdrücklich NICHT gleichzeitig angefasst werden?

==================================================
21. ABSCHLUSSREGEL
==================================================

Nach Abschluss:

- KEINE Codeänderungen
- KEIN Commit
- KEIN Push
- keine Dateien verändern

Nur Analysebericht.

Wenn die Analyse ergibt, dass kein großer Download-Refactor notwendig ist, sage das ausdrücklich.

Ein kleiner notwendiger Architekturfix ist besser als ein großer unnötiger Refactor.

==================================================
ARCHITEKTURPRINZIP

Das MusicBot-Projekt soll nicht "neu gebaut" werden.

Die bestehende funktionierende Software soll kontrolliert in eine klare Architektur überführt werden.

Leitsatz:

> Characterize → Decide → Extract → Audit → Regression

Nicht:

> Rewrite → Hope → Debug