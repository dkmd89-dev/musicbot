# MusicBot – Download Pipeline & Duplicate Integrity Phase

**Dokument:** `MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md`  
**Phase:** Stability Hardening  
**Scope:** Download Pipeline + Duplicate Detection  
**Status:** PLANNED  
**Architecture Freeze:** APPROVED  
**Basis:** `MusicBot_ENGINEERING_BASELINE_v6.md` (ursprünglich v5, seither per
Post-Baseline-v5 Health & Risk Audit auf v6 aktualisiert; die für diese
Phase relevanten Punkte — DL-03/DL-05/DUP-05 — sind dort unverändert als
zurückgestellt/akzeptiert bestätigt)

---

# 1. Ziel dieser Phase

Der MusicBot befindet sich bereits in einem weit fortgeschrittenen
Entwicklungsstand.

Die aktuelle Engineering-Baseline beschreibt einen verifizierten Stand
mit:

- 1123 Tests
- 0 Fehlern
- freigegebenem Architecture Freeze
- vollständig integriertem `EnhancedErrorHandler`
- integriertem `EnhancedDuplicateHandler`
- verbessertem Duplicate Pre-Download Check
- explizitem `renamed_due_to_conflict`-Signal beim Library Move
- mehreren bereits geschlossenen P1-Findings

Die nächste Phase dient deshalb **nicht** dazu, weitere Features
hinzuzufügen oder die Metadatenqualität zu verbessern.

Das Ziel lautet:

> Die bestehende Download- und Duplicate-Pipeline soll unter normalen
> Bedingungen, Fehlern, Retries, Cancellation, Teilfehlern, parallelen
> Downloads und Neustarts zuverlässig einen konsistenten Zustand
> herstellen.

Der Schwerpunkt liegt auf:

- Stabilität
- Robustheit
- Fehlerbehandlung
- Zustandskonsistenz
- Cleanup
- Duplicate-Integrität
- korrekter Result-/Error-Propagation
- sicherem Verhalten bei Abbruch und Neustart

---

# 2. Verbindliche Scope-Grenze

Diese Phase besteht aus zwei eng verbundenen Bereichen:

1. **Download Pipeline Stability**
2. **Duplicate Detection Integrity**

Der Duplicate-Pfad gehört ausdrücklich zur Phase, da er unmittelbar vor
dem Download ausgeführt wird und verhindert, dass bereits vorhandene
Tracks unnötig erneut heruntergeladen werden.

---

# 3. Out of Scope – Metadata Quality

Die fachliche Qualität der Metadaten ist ausdrücklich **NICHT Bestandteil
dieser Phase**.

Nicht optimieren:

- Artist-Erkennung
- Artist-Normalisierung
- Title Parsing
- Album-Erkennung
- Album Matching
- Year-Erkennung
- Genre-Erkennung
- Genre-Mapping
- Cover-Auswahl
- Cover-Download-Qualität
- Lyrics
- MusicBrainz-Qualität
- Genius-Qualität
- Last.fm-Qualität
- Metadata Ranking
- Metadata Matching
- zusätzliche Metadata Sources
- neue Cover Sources
- neue Lyrics Sources
- neue Metadata Features

Beispiele:

> Genre ist falsch.

→ OUT OF SCOPE

> Artist wurde nicht optimal normalisiert.

→ OUT OF SCOPE

> Titel wurde nicht perfekt geparst.

→ OUT OF SCOPE

> Es wurde nicht das beste Cover gefunden.

→ OUT OF SCOPE

Diese Probleme dürfen dokumentiert, aber nicht ungefragt behoben werden.

---

## 3.1 Ausnahme – Metadata Failure als Stabilitätsproblem

Ein Metadata-Problem ist Bestandteil dieser Phase, wenn es die Stabilität
der Download-Pipeline beeinträchtigt.

Beispiel:

> MusicBrainz ist nicht erreichbar und dadurch schlägt ein ansonsten
> gültiger Download vollständig fehl.

→ IN SCOPE

Beispiel:

> MusicBrainz ist nicht erreichbar, der Track wird aber trotzdem sauber
> verarbeitet und gespeichert.

→ KEIN FIX erforderlich.

Der Fokus liegt ausschließlich auf der **Fehlertoleranz**, nicht auf der
Qualität der gelieferten Metadaten.

---

# 4. Architecture Freeze

Der bestehende Architecture Freeze bleibt vollständig erhalten.

Keine:

- großflächigen Refactorings
- neuen Layer
- neuen Frameworks
- neuen Abstraktionen
- komplette Neugestaltung der Download-Pipeline
- neue Duplicate-Architektur
- unnötigen API-Änderungen
- Clean-Architecture-Umbauten
- kosmetischen Refactorings
- großflächigen Umbenennungen
- Änderungen an stabilen Komponenten ohne konkreten Befund

Bestehende Architektur und etablierte Patterns verwenden.

Grundsatz:

> Minimaler Fix für einen konkret belegten Stabilitäts- oder
> Korrektheitsfehler.

Nicht verändern, nur weil eine andere Lösung theoretisch eleganter
erscheint.

---

# 5. Maßgebliche Quellen

Vor Beginn dieser Phase müssen mindestens gelesen werden:

1. `docs/archive/MusicBot_ENGINEERING_BASELINE_v6.md`
2. `docs/archive/MusicBot_POST_BASELINE_v4_HEALTH_RISK_AUDIT.md`
3. dieses Dokument
4. der aktuelle Repository-Code

Zusätzlich relevante Dokumentation und Tests, soweit vorhanden.

Wichtig:

> Der aktuelle Repository-Code ist die maßgebliche technische Wahrheit.

Dokumentation darf nicht ungeprüft als Beweis für das tatsächliche
Runtime-Verhalten verwendet werden.

Wenn Dokumentation und Code voneinander abweichen:

→ Code analysieren  
→ Abweichung dokumentieren  
→ Dokumentation erst nach Abschluss der Phase korrigieren

---

# 6. PHASE 0 – Read-Only Deep Audit

## 6.1 Grundregel

**Zunächst KEINE Codeänderungen.**

Die gesamte Download- und Duplicate-Pipeline wird zunächst ausschließlich
analysiert.

Es darf kein Refactoring begonnen werden, bevor der tatsächliche
Runtime-Control-Flow verstanden und dokumentiert wurde.

---

# 7. Tatsächlichen Runtime-Control-Flow rekonstruieren

Mindestens folgende Kette untersuchen:

```text
Telegram
   ↓
RichMenuHandler
   ↓
DownloadHandler
   ↓
Duplicate Pre-Check
   ↓
DuplicateDetector
   ↓
Duplicate Cache / Library Fallback
   ↓
YoutubeDownloader
   ↓
download_utils
   ↓
download_executor
   ↓
DownloadResult
   ↓
Result Translation
   ↓
EnhancedMetadataProcessor
   ↓
move_to_library
   ↓
Cleanup
   ↓
Navidrome
```

Die tatsächliche Implementierung kann von dieser Darstellung abweichen.

Deshalb:

> Nicht davon ausgehen, dass diese Reihenfolge korrekt ist.



Den realen Runtime-Pfad aus dem Code rekonstruieren.

Zusätzlich verfolgen:

Exceptions

Retry

Cancellation

Cleanup

Status-Propagation

Result-Propagation

Error-Propagation

Logging

Benutzerbenachrichtigungen



---

8. Single Download Audit

Untersuchen:

URL
 ↓
Duplicate Check
 ↓
Download
 ↓
Validation
 ↓
Processing
 ↓
Library Move
 ↓
Cleanup
 ↓
Result
 ↓
User Notification

Für jeden Schritt prüfen:

Eingabe

Ausgabe

Fehlerverhalten

Exception-Verhalten

Dateisystemzustand

Result-Zustand

nächster Pipeline-Schritt


Zentrale Frage:

> Kann ein normaler erfolgreicher Download einen inkonsistenten Zustand hinterlassen?




---

9. Playlist Download Audit

Untersuchen:

Playlist-Erkennung

Playlist-Metadaten

einzelne Tracks

Track-Reihenfolge

einzelne Track-Fehler

teilweise erfolgreiche Downloads

Playlist-Abbruch

Retry einzelner Tracks

Cleanup

Result-Propagation

Benutzerbenachrichtigung


Besonders wichtig:

> Ein Fehler bei Track N darf nicht unbeabsichtigt bereits erfolgreich verarbeitete Tracks zerstören.



Untersuchen:

Track 1 → SUCCESS
Track 2 → SUCCESS
Track 3 → FAILURE
Track 4 → SUCCESS

und:

Track 1 → SUCCESS
Track 2 → CANCELLATION
Track 3 → nicht ausgeführt

Ermitteln, ob der aktuelle Zustand konsistent bleibt.


---

10. Retry Audit

Analysieren:

welche Fehler Retry auslösen

welche Fehler keinen Retry auslösen

maximale Retry-Anzahl

Backoff

Retry bei Netzwerkfehler

Retry bei yt-dlp Fehler

Retry bei FFmpeg Fehler

Retry bei Processing-Fehler

Verhalten nach letztem Fehlversuch


Zusätzlich prüfen:

können Retries doppelte Dateien erzeugen?

wird derselbe Download mehrfach geschrieben?

werden Processing-Schritte mehrfach ausgeführt?

werden Metadata-Schritte mehrfach ausgeführt?

wird Cleanup zwischen Retries korrekt ausgeführt?

bleibt ein teilweise erfolgreicher Zustand zurück?


Zentrale Frage:

> Kann ein Retry einen bereits teilweise erfolgreichen Zustand verschlechtern oder Duplikate erzeugen?




---

11. Cancellation / Task Cancellation Audit

Dieser Bereich hat hohe Priorität.

Insbesondere untersuchen:

asyncio.CancelledError

und alle relevanten Cancellation-Pfade.

Prüfen:

Cancellation während yt-dlp

Cancellation während Download

Cancellation während FFmpeg

Cancellation während Metadata Processing

Cancellation vor Library Move

Cancellation während Library Move

Cancellation während Cleanup

Cancellation bei Playlist

Cancellation bei Retry


Untersuchen:

Weitergabe von CancelledError

laufende Tasks

Subprocesses

yt-dlp-Prozesse

FFmpeg-Prozesse

temporäre Dateien

.part

.tmp

.ytdl

.info.json

temporäre Cover

sonstige Artefakte


Die aktuelle Baseline nennt bereits ein mögliches P2-Risiko:

download_executor.py::download_single_track()

→ mögliche verwaiste Teildatei bei Task-Cancellation.

Dieses Finding ausdrücklich verifizieren.


---

12. Download-/yt-dlp-/Netzwerk-Fehler

Untersuchen:

Netzwerkfehler

HTTP Fehler

yt-dlp Fehler

Video nicht verfügbar

privates Video

Authentifizierungsfehler

Cookie-Fehler

Rate Limit

Timeout

FFmpeg Fehler

beschädigte Downloads

unvollständige Downloads

Prozessabbruch


Für jeden relevanten Fehler beantworten:

1. Welche Exception / welches Result entsteht?


2. Wer verarbeitet den Fehler?


3. Wird Retry ausgelöst?


4. Was passiert auf dem Dateisystem?


5. Was bekommt der nächste Pipeline-Schritt?


6. Was bekommt der Benutzer?


7. Kann ein inkonsistenter Zustand entstehen?




---

13. Metadata Processing – ausschließlich Fehlertoleranz

Nicht die Metadatenqualität bewerten.

Nur untersuchen:

MusicBrainz nicht erreichbar

Genius nicht erreichbar

Last.fm nicht erreichbar

Cover nicht verfügbar

Lyrics nicht verfügbar

Genre nicht verfügbar

Artist-Normalisierung schlägt fehl

Metadata Processor Exception


Frage:

> Kann ein optionaler Metadata-Schritt einen ansonsten gültigen Download fälschlicherweise als vollständigen Pipelinefehler behandeln?



Wenn ja:

→ als Stabilitätsbefund aufnehmen.

Keine fachliche Metadata-Optimierung durchführen.


---

14. Library Move / Collision Audit

Untersuchen:

existierende Zieldatei

identische Zieldatei

andere Datei mit gleichem Namen

Umbenennung

renamed_due_to_conflict

Move Failure

Permission Error

fehlendes Zielverzeichnis

teilweise erfolgreiches Processing

Cleanup nach Move Failure

Result-Propagation


Das vorhandene:

renamed_due_to_conflict

nicht neu designen.

Prüfen, ob das Signal tatsächlich:

move_to_library()
       ↓
Download Result
       ↓
Download Handler
       ↓
Final Status
       ↓
Cleanup
       ↓
User Notification

korrekt durchläuft.


---

15. DUPLICATE DETECTION INTEGRITY AUDIT

Duplicate Detection ist ein expliziter Kernbestandteil dieser Phase.

Der aktuelle konzeptionelle Ablauf ist:

URL
 ↓
Duplicate Pre-Check
 ↓
Metadata Probe
 ↓
DuplicateDetector
 ↓
URL / Content / Artist+Title / Library Fallback
 ↓
Duplicate Result
 ↓
Download oder Abbruch

Die aktuelle Baseline v5 beschreibt bereits folgende Verbesserungen:

yt-dlp extract_info(download=False) Probe

Artist/Titel können dadurch vor dem Duplicate Check verfügbar sein

Content-/Parser-/Library-Fallbacks können dadurch im Pre-Download-Pfad aktiviert werden

bei Probe-/Playlist-Problemen existiert ein kontrollierter Fallback

move_to_library() liefert renamed_due_to_conflict


Diese Änderungen nicht einfach als korrekt voraussetzen.

Den tatsächlichen Runtime-Pfad unabhängig überprüfen.


---

16. Duplicate Detection – URL

Untersuchen:

identische URL

URL mit unterschiedlichen Parametern

YouTube-ID identisch

unterschiedliche URL-Darstellung

Short URL

normale YouTube URL

relevante URL-Normalisierung


Frage:

> Werden tatsächlich identische Inhalte zuverlässig als Duplicate erkannt?




---

17. Duplicate Detection – Content

Untersuchen:

gleiche Aufnahme unter anderer URL

gleiche Video-ID

Reupload

alternative URL

unterschiedliche URL mit identischem Content

Content-basierte Fallbacks


Nicht ungefragt einen neuen Content-Matching-Algorithmus bauen.

Nur tatsächliches Verhalten analysieren.


---

18. Duplicate Detection – Artist + Title

Untersuchen:

gleicher Artist + gleicher Titel

fehlender Artist

fehlender Titel

unterschiedliche Schreibweisen

normalisierte Schreibweisen

Probe erfolgreich

Probe fehlgeschlagen


Prüfen:

> Wann wird Artist + Title verwendet?



und:

> Wann darf Artist + Title einen Download verhindern?




---

19. Duplicate Detection – Library

Untersuchen:

Track bereits in Library

Library-Datei vorhanden

Library-Datei nicht erreichbar

Library Lookup Fehler

Library-Zustand nach Neustart

Library-Zustand nach vorherigem Fehler



---

20. Duplicate Detection – Playlist

Untersuchen:

vollständig vorhandene Playlist

teilweise vorhandene Playlist

einzelne bereits vorhandene Tracks

gleiche Tracks in unterschiedlichen Playlists

Playlist-Probe erfolgreich

Playlist-Probe fehlerhaft


Zentrale Frage:

> Wird nur das tatsächlich vorhandene Duplikat verhindert oder versehentlich die gesamte Playlist blockiert?




---

21. Duplicate False Positives

Ein False Positive liegt vor, wenn ein Track als Duplicate erkannt wird, obwohl er tatsächlich verarbeitet werden sollte.

Für jeden gefundenen Fall dokumentieren:

Input

vorhandener Library-Zustand

Erkennungsmethode

tatsächliches Ergebnis

erwartetes Ergebnis

Ursache

Priorität


Keine automatische Erweiterung der Erkennungslogik.


---

22. Duplicate False Negatives

Ein False Negative liegt vor, wenn ein bereits vorhandener Track nicht als Duplicate erkannt wird und erneut heruntergeladen wird.

Dokumentieren:

Input

vorhandener Track

Erkennungsmethode

tatsächliches Ergebnis

erwartetes Ergebnis

Ursache

Priorität



---

23. Duplicate Cache Audit

Untersuchen:

Cache Hit

Cache Miss

Cache Read

Cache Write

Cache-Korruption

Cache nicht verfügbar

stale data

Bot-Neustart

parallele Zugriffe

Race Conditions


Die aktuelle Baseline nennt ein bestehendes P2-Risiko in:

duplicate/cache.py

Dieses nicht automatisch verändern.

Bewerten:

> Ist dieses Risiko für die aktuelle Pipeline-Stabilität tatsächlich relevant?




---

24. Parallelität / Race Conditions

Besonders wichtig.

Szenario:

Request A
   ↓
Duplicate Check
   ↓
kein Duplicate
   ↓
Download


Request B
   ↓
Duplicate Check
   ↓
kein Duplicate
   ↓
Download

Prüfen:

können beide Requests denselben Track gleichzeitig downloaden?

kann ein Duplicate entstehen?

kann ein Library Collision entstehen?

wird der Zustand danach korrekt behandelt?

entstehen Race Conditions im Duplicate Cache?

entstehen Race Conditions im Dateisystem?


Keine neue globale Locking-Architektur entwickeln, sofern kein konkreter Fehler dies erforderlich macht.


---

25. Duplicate + Restart

Untersuchen, was passiert, wenn der Bot beendet oder neu gestartet wird:

Duplicate Check
     ↓
Bot Restart
     ↓
Download

sowie:

Download
     ↓
Bot Restart
     ↓
erneuter Request

Prüfen:

Duplicate State

Cache State

Library State

temporäre Dateien

erneuter Download

Library Collision

Cleanup



---

26. CLEANUP AUDIT

Vollständige Liste aller temporären Artefakte erstellen.

Mindestens:

.part

.tmp

.ytdl

.info.json

temporäre Audio-Dateien

temporäre Cover-Dateien

sonstige Pipeline-Artefakte


Für jeden Exit Path prüfen:

SUCCESS
FAILURE
RETRY
CANCELLATION
EXCEPTION
DUPLICATE
PARTIAL PLAYLIST SUCCESS
LIBRARY MOVE FAILURE
BOT RESTART

Frage:

> Welche Dateien bleiben zurück?



und:

> Sind diese Dateien nach diesem Exit Path noch erforderlich?



Bereits bekannte .info.json-Reste ausdrücklich überprüfen.


---

27. RESULT / ERROR PROPAGATION AUDIT

Den vollständigen Fluss verfolgen:

Downloader
 ↓
DownloadExecutor
 ↓
DownloadUtils
 ↓
MetadataProcessor
 ↓
MetadataResultTranslator
 ↓
DownloadHandler
 ↓
Telegram Handler

Prüfen:

geht ein Fehler verloren?

wird ein Fehler als Erfolg interpretiert?

wird Erfolg gemeldet, obwohl ein notwendiger Schritt fehlgeschlagen ist?

werden Exceptions verschluckt?

werden None korrekt behandelt?

sind Single- und Playlist-Resultate konsistent?

ist Duplicate ein sauberer Status?

wird Duplicate als Fehler behandelt?

wird ein echter Fehler als Duplicate behandelt?



---

28. CRASH / RESTART AUDIT

Untersuchen:

> Was passiert, wenn der Bot während eines Downloads abstürzt oder neu gestartet wird?



Prüfen:

temporäre Dateien

laufende Downloads

bereits verschobene Dateien

Duplicate State

Cache State

Result State

erneuter Download

Library Collision

Cleanup


Kein neues Recovery-System entwickeln.

Nur bestehendes Verhalten analysieren und Risiken dokumentieren.


---

29. PHASE 0 – AUDIT REPORT

Nach Abschluss des Read-Only Audits zunächst keine Fixes.

Der Bericht muss mindestens folgende Bereiche enthalten.


---

29.1 Executive Summary

Beantworten:

Ist die Download-Pipeline grundsätzlich stabil?

Ist Duplicate Detection grundsätzlich stabil?

Gibt es P0?

Gibt es P1?

Welche P2 bleiben?

Welche P3 bleiben?

Welche Bereiche sind bereits korrekt gelöst?



---

29.2 Tatsächlicher Runtime Flow

Den realen aktuellen Ablauf dokumentieren.

Nicht die erwartete Architektur beschreiben.


---

29.3 Download Failure Matrix

Szenario	Aktuelles Verhalten	Cleanup	Result	Risiko

Netzwerkfehler				
yt-dlp Fehler				
FFmpeg Fehler				
Timeout				
Cancellation				
Metadata Failure				
Library Move Failure				



---

29.4 Duplicate Detection Matrix

Szenario	Erwartung	Ist-Verhalten	Ergebnis	Risiko

gleiche URL				
gleiche Video-ID				
gleiche Aufnahme andere URL				
Artist + Title				
Library Duplicate				
Playlist Duplicate				
Cache Hit				
Cache Failure				
Parallel Request				



---

29.5 Cleanup Matrix

Exit Path	Artefakte	Cleanup korrekt?	Risiko

SUCCESS			
FAILURE			
RETRY			
CANCELLATION			
EXCEPTION			
DUPLICATE			
PLAYLIST PARTIAL			
MOVE FAILURE			
RESTART			



---

30. Findings

Jedes Finding muss enthalten:

ID

Priorität

Kategorie

Datei

Funktion / Codebereich

konkrete Ursache

tatsächliches Verhalten

erwartetes Verhalten

Reproduzierbarkeit

Auswirkungen

minimaler Fix

benötigter Regressionstest


Keine vagen Aussagen wie:

> "Könnte problematisch sein."



Stattdessen:

> "Wenn X während Y passiert, führt Code Z dazu, dass A zurückbleibt, wodurch B entsteht."




---

31. Out-of-Scope Findings

Metadatenqualitätsprobleme separat dokumentieren.

Beispiele:

Genre nicht optimal

Artist nicht optimal normalisiert

Title Parsing nicht perfekt

Cover nicht optimal

Lyrics fehlen

Album-Matching könnte verbessert werden


Diese Findings dürfen NICHT in den aktuellen Fix-Scope übernommen werden.


---

32. Priorisierung

P0 – Kritisch

Kann verursachen:

Datenverlust

Überschreiben falscher Dateien

Library-Korruption

schwerwiegende Inkonsistenz

nicht kontrollierbare Downloads



---

P1 – Hoch

Kann verursachen:

verlorene Downloads

falsche Erfolgszustände

unkontrollierte Duplikate

kaputte Pipeline-Zustände

unkontrollierte Fehler

wiederholte Downloads mit relevanten Auswirkungen



---

P2 – Mittel

Robustheitsprobleme:

Cancellation Cleanup

Shutdown Edge Cases

Cache Race Conditions

temporäre Artefakte

seltene Fehlerfälle

kleinere Zustandsinkonsistenzen



---

P3 – Niedrig

Dokumentation

Kosmetik

Wartbarkeit ohne aktuelles Fehlverhalten


P3 nicht ungefragt beheben.


---

33. PHASE 1 – FIX PLAN

Nach Abschluss des Audits:

1. Findings priorisieren


2. P0/P1/P2 auswählen


3. konkrete Fix-Reihenfolge festlegen


4. Regressionstests definieren


5. erst danach Änderungen beginnen



Kein Fix ohne nachvollziehbaren Befund.


---

34. PHASE 2 – STABILITY FIXES

Nur reale P0/P1/P2-Probleme beheben.

Für jeden Fix:

1. kleinste sinnvolle Codeänderung


2. Regressionstest schreiben


3. Regressionstest muss den Fehler reproduzieren


4. Fix implementieren


5. Test muss danach bestehen


6. relevante Testsuite ausführen


7. vollständige Testsuite ausführen



Keine unrelated Änderungen.

Keine Metadata-Optimierungen.

Keine neuen Features.

Keine Architekturänderungen ohne zwingenden Befund.


---

35. Teststrategie

Nicht nur Happy Paths testen.

---

Download

Tests für:

erfolgreicher Single Download

erfolgreicher Playlist Download

Netzwerkfehler

yt-dlp Fehler

FFmpeg Fehler

Timeout

Retry Exhaustion

Partial Download

Cancellation

---

Duplicate

Tests für:

identische URL

gleiche Video-ID

gleiche Aufnahme unter anderer URL

Artist + Title Fallback

Library Duplicate

Playlist Duplicate

Cache Hit

Cache Miss

Cache Failure

False Positive

False Negative

paralleler Duplicate Check

Restart

---

Library

Tests für:

normale Datei

existierende Zieldatei

Collision

Move Failure

Cleanup nach Move Failure

---

Metadata

Nur Fehlerisolierung:

Metadata Service unavailable

Cover unavailable

Lyrics unavailable

Genre unavailable

Nicht die fachliche Qualität testen oder verbessern.

---

Cleanup

Tests für:

Success

Failure

Retry

Cancellation

Exception

Duplicate

Partial Playlist

Move Failure

---

36. Bestehende Tests

Bestehende Tests nicht unnötig verändern.

Keine Tests entfernen, nur damit die Suite grün wird.

Keine Assertions abschwächen.

Keine Tests so verändern, dass sie lediglich die Implementierung bestätigen, ohne reales Verhalten abzusichern.

Neue Regressionstests sollen möglichst das reale Problem reproduzieren.

---

37. Vollständige Regression

Nach den Änderungen:

`python3 -m pytest tests/ -q`

Das Ergebnis muss dokumentiert werden:

Anzahl Tests

Passed

Failed

Warnings

Laufzeit

Die Phase gilt nicht als abgeschlossen, solange die vollständige Testsuite nicht grün ist.

---

38. Dokumentation nach Abschluss

Nach erfolgreichen Fixes:

dieses Phase-Dokument aktualisieren

Status von PLANNED auf COMPLETED setzen

Findings als OPEN, FIXED, ACCEPTED oder OUT OF SCOPE kennzeichnen

verbleibende P2/P3-Risiken dokumentieren

relevante Änderungen in der Engineering-Dokumentation festhalten

Die bestehende Baseline v5 nicht rückwirkend verändern.

Falls erforderlich, nach erfolgreichem Abschluss eine neue Baseline erstellen.

---

39. Definition of Done

Diese Phase ist abgeschlossen, wenn:

die komplette Download-Pipeline auditiert wurde

Single Download untersucht wurde

Playlist Download untersucht wurde

Retry untersucht wurde

Cancellation untersucht wurde

Cleanup untersucht wurde

Library Move untersucht wurde

Result/Error Propagation untersucht wurde

Crash/Restart untersucht wurde

Duplicate Detection vollständig untersucht wurde

Duplicate Cache untersucht wurde

URL-Duplicate-Verhalten untersucht wurde

Content-Duplicate-Verhalten untersucht wurde

Artist/Title-Fallback untersucht wurde

Library-Duplicate-Verhalten untersucht wurde

Playlist-Duplicate-Verhalten untersucht wurde

False Positives untersucht wurden

False Negatives untersucht wurden

parallele Duplicate Checks untersucht wurden

bekannte P2-Risiken verifiziert wurden

alle Findings klassifiziert wurden

P0/P1/P2-Fixes umgesetzt wurden, sofern erforderlich

für jeden Fix Regressionstests existieren

vollständige Testsuite grün ist

keine Metadata-Qualitätsbaustellen ungefragt bearbeitet wurden

Architecture Freeze erhalten bleibt

keine unrelated Änderungen vorgenommen wurden

verbleibende Risiken dokumentiert sind

---

40. ABSOLUTER GRUNDSATZ

Diese Phase beantwortet NICHT:

> "Wie bekommen wir bessere Metadaten?"

Diese Phase beantwortet NICHT:

> "Wie bekommen wir bessere Cover?"

Diese Phase beantwortet NICHT:

> "Wie bekommen wir bessere Genres?"

Diese Phase beantwortet NICHT:

> "Wie können wir die Architektur schöner machen?"

Die zentrale Frage lautet:

> Kann die bestehende Download- und Duplicate-Pipeline unter Erfolg, Fehler, Retry, Cancellation, Teilfehlern, parallelen Downloads und Neustarts zuverlässig einen konsistenten Zustand herstellen?

Das gewünschte Ergebnis ist:

```text
Download
   +
Duplicate Detection
        ↓
   STABIL & ROBUST
        ↓
    TESTS GRÜN
        ↓
 PIPELINE FREEZE
        ↓
  spätere Phase:
  Metadata Quality
```

---

41. Arbeitsweise

Strikt in dieser Reihenfolge arbeiten:

```text
PHASE 0
Repository analysieren
        ↓
aktuelle Dokumentation lesen
        ↓
Runtime-Pfade verfolgen
        ↓
Read-Only Deep Audit
        ↓
keine Codeänderungen

PHASE 1
Auditbericht
        ↓
Findings
        ↓
Priorisierung
        ↓
Fixplan
        ↓
noch keine unnötigen Änderungen

PHASE 2
P0/P1/P2 Fixes
        ↓
Regressionstests
        ↓
vollständige Testsuite

PHASE 3
Abschlussaudit
        ↓
verbleibende Risiken
        ↓
Dokumentation
        ↓
Pipeline Freeze
```

Nicht eigenmächtig in die spätere Metadata-Quality-Phase wechseln.

---

42. Entscheidungsregel bei Unsicherheit

Wenn unklar ist, ob eine Änderung notwendig ist:

```text
Analysieren
    ↓
Befund reproduzieren
    ↓
Auswirkung bewerten
    ↓
Priorität vergeben
    ↓
minimalen Fix bestimmen
```

Nicht:

```text
Unsicherheit
    ↓
Refactoring
    ↓
neue Architektur
    ↓
zusätzliche Features
```

---

43. Endziel dieser Phase

Am Ende soll eine belastbare Aussage möglich sein:

> Der MusicBot besitzt eine stabile Download- und Duplicate-Pipeline, die normale Downloads sowie relevante Fehler-, Retry-, Cancellation-, Parallelitäts- und Neustart-Szenarien kontrolliert behandelt und keine unkontrollierten inkonsistenten Zustände erzeugt.

Erst wenn dieses Ziel erreicht oder verbleibende Risiken bewusst akzeptiert und dokumentiert wurden, beginnt die nächste größere Entwicklungsphase:

> Metadata Quality & Enrichment

Diese ist ausdrücklich nicht Bestandteil der aktuellen Phase.

---

**Dateiname:**

```text
docs/MusicBot_DOWNLOAD_PIPELINE_STABILITY_PHASE.md
```
