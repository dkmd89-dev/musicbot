# CLAUDE.md — MusicBot Engineering Guide

## 1. Projekt

**Repository:** `dkmd89-dev/musicbot`

MusicBot ist ein privat entwickeltes Hobbyprojekt für Musik-Download, Metadatenverarbeitung, Library-Organisation, Telegram-Steuerung und Navidrome.

Das Projekt ist historisch organisch gewachsen. Es soll **nicht** neu geschrieben werden. Ziel ist eine kontrollierte Weiterentwicklung.

> **Erst verstehen → dann testen → dann verbessern.**

Die Engineering Baseline ist die verbindliche Ausgangsbasis für die weitere Entwicklung.

---

# 2. Arbeitsweise

## Grundprinzip

Behandle den vorhandenen Code als **funktionierendes Bestandssystem**, nicht als Greenfield-Projekt.

Vor Änderungen:

1. vorhandenen Code lesen
2. Aufrufer und Datenfluss verstehen
3. vorhandenes Verhalten identifizieren
4. Logs/Tests als Verhaltensquelle prüfen
5. kleinste sinnvolle Änderung planen
6. Änderung implementieren
7. Tests ausführen
8. Regressionen prüfen
9. Dokumentation aktualisieren, wenn sich Verhalten ändert

**Nicht einfach refactoren, nur weil eine andere Struktur schöner aussieht.**

---

# 3. Wichtigste Priorität

MusicBot soll langfristig **sicher weiterentwickelbar** werden.

Nicht die maximale Test-Coverage ist das Ziel.

Das Ziel ist:

> Vertrauen in die kritischen Geschäftsabläufe.

Besonders geschützt werden müssen:

- Metadata
- Artist
- Genre
- Duplicate Detection
- Download
- File/Library Processing
- Cache-Verhalten

---
#3.A Architecture Migration Policy

Das Projekt befindet sich in einer kontrollierten Architekturmigration.

Architekturänderungen erfolgen phasenweise.

Für jede ARCH-Phase gilt:

1. Ist-Zustand analysieren
2. Verantwortlichkeiten bestimmen
3. Zielgrenzen definieren
4. kleinsten sinnvollen Migrationsschritt bestimmen
5. Änderung implementieren
6. Tests ausführen
7. Dependency Audit durchführen
8. Ergebnis dokumentieren

Keine großflächigen Refactorings ohne vorherige Characterization.

Frühere ARCH-Dokumente sind historische Architekturentscheidungen.
Das aktuellste bestätigte Architekturresultat hat Vorrang.

Eine ARCH-Phase darf nicht eigenmächtig mehrere zukünftige ARCH-Phasen vorwegnehmen.

Leitsatz:

Characterize → Decide → Extract → Audit → Regression

---

# 4. Kritische Architektur

Vereinfachter Hauptfluss:

```text
Telegram
   ↓
ExtendedBot
   ↓
RichMenuHandler
   ↓
DownloadHandler
   ↓
YouTube
           ↓
   Metadata Pipeline
           ↓
   Artist / Title / Genre
           ↓
   MusicBrainz / Lyrics / Cover
           ↓
   Audio / FFmpeg
           ↓
   Tags / Filename / Library
           ↓
   Navidrome
```

## Schichtgrenzen (etabliert durch ARCH-009)

```text
handlers/
    → Benutzerinteraktion / Telegram-Präsentation
      (Nachrichtenversand, MarkdownV2-Formatierung, Callback-Handling)

services/
    → Fachliche bzw. technische Orchestrierung

services/clients/
    → externe Integrationsadapter (reine API-/HTTP-Kommunikation)
      keine Telegram-Präsentation, keine fachliche Orchestrierung

utils/
    → wiederverwendbare technische Hilfs-/Runner-Komponenten,
      einschließlich lokaler Subprocess-/Shell-Wrapper ohne externe
      Netzwerkkommunikation (Beispiele: navidrome_scan_trigger.py,
      audio_enhancer.py)

api/
    → keine MusicBot-Schicht mehr (vollständig entfernt, siehe
      docs/archive/arch/MusicBot_ARCH-009_Navidrome_Migration_Roadmap.md)

scripts/
    → keine Laufzeit-Schicht des Bots. Eigenständige, manuell gestartete
      Wartungs-/Reprocessing-Tools, die auf isolierten Testdaten arbeiten
      (Path-Safety-Guards, Produktion strikt read-only) und die
      bestehenden Produktions-Unterprozessoren wiederverwenden statt
      Fachlogik zu duplizieren (Beispiel: reprocess_artist_metadata.py,
      siehe docs/METADATA_REPROCESSING.md)
```

Ein Modul, das externe Netzwerk-/API-Kommunikation durchführt, gehört nach
`services/clients/`. Ein Modul, das nur lokale Prozesse/Shell-Kommandos
steuert (kein Netzwerk), gehört nach `utils/` — nicht automatisch in
`services/clients/`, nur weil es "technisch" ist. Telegram-spezifische
Formatierung/Objekte (`Update`, `CallbackQuery`, `ParseMode`, Emoji-/
MarkdownV2-Helfer) gehören ausschließlich in `handlers/`.

Beim Arbeiten an einem Bereich immer prüfen:

- Wer ruft ihn auf?
- Welche Daten kommen hinein?
- Welche Daten kommen heraus?
- Welche Seiteneffekte entstehen?
- Welche Fallbacks existieren?
- Welche Caches werden benutzt?
- Welche externen APIs werden angesprochen?
- Was passiert bei Fehlern?

---

# 5. Kritische Geschäftsabläufe

## P0 Download

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

## P0 Metadata

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

## P0 Duplicate Detection

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

---

# 6. Tests — wichtigste Regel

## Characterization First

Bei bestehender Logik zunächst **Characterization Tests** schreiben.

Ein Characterization Test dokumentiert das tatsächliche aktuelle Verhalten.

Beispiel:

```python
def test_genre_mapping_current_behavior():
    result = production_genre_processor(...)
    assert result.primary == "..."
```

Nicht sofort das Verhalten ändern, nur weil es fachlich schöner erscheint.

Wenn das bestehende Verhalten falsch ist:

1. Fehler reproduzieren
2. Test schreiben
3. gewünschtes Verhalten festlegen
4. Fix implementieren
5. Regressionstest behalten

---

# 7. Produktionscode wirklich testen

Tests müssen nach Möglichkeit die **echte Produktionsimplementierung** importieren.

Vorsicht bei Tests, die Produktionsklassen innerhalb der Testdatei nachbauen.

Nicht akzeptabel als Ersatz für einen echten Unit-Test:

```python
# eigene Testimplementierung
class GenreProcessor:
    ...
```

Stattdessen:

```python
from services... import GenreProcessor
```

Mocks/Fakes sind für externe Abhängigkeiten erlaubt.

---

# 8. Testpyramide

Bevorzugte Reihenfolge:

```text
        E2E
         ▲
    Integration
         ▲
       Unit
```

Der Großteil der Tests soll schnell und deterministisch sein.

Externe Dienste in Unit-Tests nicht real ansprechen.

Beispiele:

- MusicBrainz → Fake/Mock
- Genius → Fake/Mock
- Last.fm → Fake/Mock
- Navidrome → Fake/Mock
- Telegram → Fake/Mock

Echte externe Aufrufe gehören in gezielte Integrationstests.

---

# 8.A Testausführungsstrategie

Für **jede einzelne Änderung** gilt diese verbindliche Reihenfolge bei der
Testausführung:

```text
1. Gezielte Tests
   → nur die Tests für das aktuell bearbeitete Finding
   → Beispiel: python3 -m pytest tests/test_<aktuelles_finding>.py -q

2. Direkt relevante Regressionstests
   → nur Tests, die unmittelbar von der geänderten Funktionalität betroffen sind
   → Beispiel (DUP-03): python3 -m pytest tests/test_duplicate_detector_hash_consistency.py -q

3. Thematische Testsuite (optional, wenn sinnvoll)
   → die zum Bereich gehörende Testgruppe
   → Beispiel: python3 -m pytest tests/test_duplicate*.py -q

4. Vollständige Suite
   → python3 -m pytest tests/ -q
   → NICHT nach jedem einzelnen Finding
   → erst wenn ALLE Findings der aktuell gemeinsam bearbeiteten
     Arbeitsphase abgeschlossen sind
```

Als Zyklus über mehrere Findings hinweg einer Arbeitsphase:

```text
Finding → gezielte Tests → direkte Regressionstests → thematische Suite
   ↓
nächstes Finding → gezielte Tests → direkte Regressionstests → thematische Suite
   ↓
   ...
   ↓
erst am Ende der Arbeitsphase: vollständige Testsuite
```

Diese Reihenfolge gilt für **jedes** Finding, auch für zukünftige, nicht nur
für die zum Zeitpunkt der Formulierung dieser Regel aktuell bearbeiteten.

**Nach dem Abschlusslauf (Punkt 4):** Ergebnisse unterscheiden zwischen

- durch die aktuelle Arbeitsphase verursachten Fehlern
- bereits vorher bestehenden Fehlern
- unabhängigen Fehlern außerhalb des Scopes

Bereits bestehende, unabhängige Fehler werden **nicht ungefragt behoben**,
auch nicht im Rahmen eines späteren Findings, das zufällig denselben
Testlauf berührt.

**Bei einem fehlschlagenden gezielten Test:**

1. zuerst Root Cause bestimmen
2. prüfen, ob die aktuelle Änderung ursächlich verantwortlich ist
3. keine vorschnellen Folgeänderungen
4. Scope nicht erweitern
5. bei Unsicherheit STOPP und Befund melden statt zu raten

Vor-Fix-Diskriminierung (Reproduktion des Fehlers am ungefixten Stand vor
der Implementierung) bleibt unabhängig davon etabliertes Vorgehen, siehe
Abschnitt 6 (Characterization First) und Abschnitt 26 (Bei Bugs).

---

# 9. P0-Testumfang

Bei Änderungen an Metadata:

- Artist Extraction
- Title Extraction
- Genre Selection
- MetadataResult
- Cache Hit
- Cache Miss

Bei Duplicate Detection:

- gleiche URL
- gleiche YouTube-ID
- gleicher Artist/Titel
- Parser-Fallback
- vorhandene Library-Datei

Bei File Processing:

- Filename
- Directory
- Extension
- Metadata Writing
- fehlende Datei
- bestehende Datei

Bei Security:

- Credentials niemals im Log

---

# 10. Mapping-Dateien sind Fachlogik

YAML-/JSON-Dateien mit Artist-/Genre-Regeln sind nicht als belanglose Konfiguration zu betrachten.

Änderungen können das reale Verhalten von MusicBot verändern.

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

Deshalb:

```text
Mapping ändern
     ↓
betroffene Beispiele identifizieren
     ↓
Tests
     ↓
Änderung
     ↓
Tests erneut
```

Keine unkontrollierten Bulk-Änderungen.

---

# 11. Logs als Engineering-Werkzeug

MusicBot besitzt umfangreiches Logging.

Logs dürfen zur Rekonstruktion des aktuellen Verhaltens verwendet werden.

Besonders wertvoll:

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

Logs sind jedoch **keine dauerhafte Dokumentation**.

Wichtiges Verhalten wird langfristig in:

- Tests
- Code
- Dokumentation

überführt.

---

# 12. Security

## P0: Keine Secrets loggen

Besonders kritisch:

- Passwörter
- Tokens
- API Keys
- Credentials
- Authorization Header
- komplette Request-Parameter mit Secrets

Vor Änderungen an Logging-Code prüfen:

```text
Kann hier ein Secret erscheinen?
```

Wenn ja:

- redigieren
- maskieren
- strukturiertes Logging verwenden

Bevorzugt:

```text
password=***
token=***
api_key=***
```

oder vollständiges Weglassen.

---

# 13. Config

`config.py` ist zentral und enthält unter anderem:

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
- Backups
- Secrets
- Feature Flags

Langfristiges Ziel:

```python
import config
```

soll möglichst wenige Seiteneffekte haben.

**Aber:** Config nicht nebenbei großflächig refactoren.

Erst Tests/Charakterisierung.

---

# 14. Cache

Relevante Cache-Bereiche:

```text
Metadata
Duplicate
Lyrics
History / Stats
```

Bei Cache-Änderungen mindestens betrachten:

```text
Hit
Miss
Invalid
Stale
Write Failure
```

Cache-Änderungen müssen insbesondere auf False Positives und False Negatives geprüft werden.

---

# 15. Duplicate Detection

Duplicate Detection ist ein kritischer Bereich.

Bestehende Schutzschichten können mehrere Ebenen umfassen:

```text
URL
 ↓
YouTube-ID
 ↓
Artist + Titel
 ↓
Parser
 ↓
Library
```

Keine einzelne Ebene als alleinige Wahrheit betrachten, ohne den bestehenden Codefluss zu prüfen.

Änderungen immer mit konkreten Gegenbeispielen testen:

- echtes Duplikat
- kein Duplikat
- gleicher Titel / anderer Artist
- anderer Titel / gleicher Artist
- unterschiedliche URL derselben Quelle
- Parser-Fallback
- vorhandene Datei

---

# 16. Metadata

Metadata ist einer der wichtigsten fachlichen Bereiche.

Bei Änderungen immer prüfen:

```text
Artist
Title
Album
Year
Track Number
Genre
Lyrics
Cover
MusicBrainz IDs
```

Außerdem:

- Cache
- Fallback-Reihenfolge
- Normalisierung
- Feature Artists
- Special Channels
- Podcast-/Sonderlogik

Keine Reihenfolge der Pipeline ohne Tests verändern.

---

# 17. Externe Services

Externe APIs und Tools nicht mit Core-Logik vermischen, wenn dies vermeidbar ist.

Reine externe Integrationsadapter (API-/HTTP-Kommunikation) gehören
strukturell nach `services/clients/` (Konvention seit ARCH-003 P-11 /
ARCH-009, siehe Abschnitt 4 „Schichtgrenzen"). Aktuell dort: `genius_client.py`,
`lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py`. Lokale
Subprocess-/Shell-Steuerung ohne echte Netzwerkkommunikation (z. B. der
Navidrome-Scan-Trigger) gehört dagegen nach `utils/`, nicht nach
`services/clients/`.

Relevante Integrationen:

- YouTube / yt-dlp
- MusicBrainz
- Genius
- Last.fm
- Fanart
- Navidrome
- FFmpeg

Bei Fehlern prüfen:

```text
Timeout
Rate Limit
HTTP Error
leere Antwort
ungültige Antwort
fehlende Daten
Service nicht erreichbar
```

Fallbacks müssen erhalten bleiben, sofern keine bewusste Änderung beschlossen wurde.

---

# 18. Refactoring-Regel

**Kein großer Refactor als erste Reaktion auf ein Problem.**

Bevorzugt:

```text
kleiner Fix
 ↓
Regressionstest
 ↓
beobachten
 ↓
nächster Fix
```

Erst wenn Tests das Verhalten ausreichend schützen:

```text
großer Refactor
 ↓
Tests
 ↓
Vergleich
```

---

# 19. Große Klassen

Bekannte Risikobereiche können große Orchestratoren enthalten.

Dazu gehören insbesondere:

- DownloadHandler
- RichMenuHandler
- RichMenuSystem
- EnhancedMetadataProcessor

Nicht automatisch zerlegen.

Vor einer Aufteilung zuerst:

1. Verantwortlichkeiten dokumentieren
2. öffentliche Schnittstellen identifizieren
3. Aufrufer finden
4. Tests schreiben
5. kleinsten sinnvollen Extraktionsschritt durchführen

---

# 20. Legacy-Code

Legacy-/Kompatibilitätsschichten nicht ohne Beweis entfernen.

Vor Entfernung:

```text
Wer benutzt das?
 ↓
Gibt es externe/alte Aufrufer?
 ↓
Tests?
 ↓
Migration notwendig?
```

Wenn unklar:

> Code zunächst dokumentieren, nicht löschen.

---

# 21. Änderungsregeln

### Regel 1
Kein größerer Refactor ohne Sicherheitsnetz.

### Regel 2
Bestehendes Verhalten nicht unbewusst ändern.

### Regel 3
Mapping-Änderungen wie Codeänderungen behandeln.

### Regel 4
Bug zuerst reproduzieren.

### Regel 5
Jeder kritische Bug-Fix bekommt einen Regressionstest.

### Regel 6
Keine Secrets in Logs.

### Regel 7
Externe Services in Unit-Tests mocken/faken.

### Regel 8
Kleine, nachvollziehbare Commits bevorzugen.

### Regel 9
Bei Unsicherheit zuerst analysieren, nicht raten.

### Regel 10
Keine komplette Neuschreibung ohne ausdrückliche Entscheidung.

---

# 22. Definition of Done

Eine Änderung ist grundsätzlich fertig, wenn:

```text
[ ] Verhalten verstanden
[ ] betroffene Aufrufer geprüft
[ ] Änderung implementiert
[ ] Regressionstest vorhanden
[ ] relevante Tests grün
[ ] Logs geprüft
[ ] keine Secrets im Log
[ ] Mapping-Änderungen geprüft
[ ] Dokumentation aktualisiert, falls Verhalten/API geändert
```

---

# 23. Prioritäten

## P0

- Security
- Metadata
- Duplicate Detection
- Download
- File/Library
- Regressionen

## P1

- Config
- Cache
- externe Adapter
- Navidrome
- Telegram
- Integration Tests

## P2

- Legacy Cleanup
- große Refactorings
- Architekturverbesserungen
- kosmetische Verbesserungen

---

# 24. Aktuelle Engineering-Roadmap

## Phase 0 — Baseline

Abgeschlossen:

- Architektur
- kritische Abläufe
- Risiken
- Teststrategie
- Dokumentationsgrundlage

## Phase 1 — Sicherheitsnetz

1. Logging-Secrets prüfen/entfernen
2. Produktionslogik-Tests herstellen
3. Metadata Characterization Tests
4. Duplicate Characterization Tests
5. File/Library Characterization Tests
6. reproduzierbarer Happy Path

## Phase 2 — Kernsystem

```text
Metadata
Duplicate
Filename
Cache
Genre
Artist
```

## Phase 3 — Integrationen

```text
YouTube
MusicBrainz
Lyrics
Cover
Navidrome
Telegram
```

## Phase 4 — Refactoring

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

# 25. Wenn Claude Code einen Auftrag erhält

Arbeite bevorzugt nach diesem Muster:

### A. ANALYZE

- Repository-Struktur untersuchen
- relevante Dateien identifizieren
- Aufrufer/Abhängigkeiten suchen
- bestehende Tests suchen
- vorhandene Logs/Reports berücksichtigen

### B. PLAN

Kurz erklären:

- Ursache
- betroffene Komponenten
- geplante Änderung
- Risiken
- benötigte Tests

### C. IMPLEMENT

Nur den notwendigen Umfang ändern.

Keine ungefragten Groß-Refactorings.

### D. TEST

Mindestens:

```text
gezielte Tests
+
relevante bestehende Tests
```

Bei kritischen Änderungen möglichst zusätzlich:

```text
Regression Test
```

### E. REPORT

Am Ende:

```text
Geändert:
...

Tests:
...

Ergebnis:
...

Offene Risiken:
...
```

---

# 26. Bei Bugs

Nicht direkt „irgendwo einen Fix einbauen“.

Stattdessen:

```text
Bug
 ↓
Reproduktion
 ↓
Minimaler Test
 ↓
Ursache
 ↓
Fix
 ↓
Regressionstest
 ↓
bestehende Tests
```

Wenn der Fehler nicht reproduzierbar ist:

> Das ausdrücklich sagen und zunächst Instrumentierung/Analyse verbessern.

---

# 27. Bei neuen Features

Vor Implementierung prüfen:

- Wo gehört die Funktion fachlich hin?
- Welche bestehende Komponente besitzt bereits ähnliche Logik?
- Gibt es bereits einen Fallback?
- Gibt es bereits ein Mapping?
- Gibt es bereits einen Cache?
- Welche Tests werden benötigt?
- Welche bestehende Funktion könnte dadurch beeinflusst werden?

Keine neue parallele Logik bauen, wenn vorhandene Logik erweitert werden kann.

---

# 28. Bei Mapping-/Regeländerungen

Immer konkrete Beispiele verwenden.

Bevorzugt:

```text
Input
 ↓
aktuelles Ergebnis
 ↓
gewünschtes Ergebnis
 ↓
Regeländerung
 ↓
Test
```

Nicht:

> „Diese Regel müsste eigentlich besser funktionieren.“

---

# 29. Umgang mit Unsicherheit

Wenn Code oder Verhalten nicht eindeutig verstanden ist:

**nicht raten.**

Stattdessen:

1. weitere Aufrufer suchen
2. Konfiguration prüfen
3. Tests prüfen
4. Logs prüfen
5. Datenfluss nachvollziehen
6. erst dann ändern

Bei widersprüchlichen Quellen ausdrücklich auf den Widerspruch hinweisen.

---

# 30. Dokumentation

Dokumentation soll vor allem erklären:

- Was macht das System?
- Warum existiert eine Komponente?
- Welche Daten fließen?
- Welche Fallbacks gibt es?
- Welche Regeln sind wichtig?
- Welche Seiteneffekte existieren?
- Was darf beim Refactoring nicht kaputtgehen?

Nicht jede einzelne triviale Funktion braucht eine seitenlange Beschreibung.

## Baseline-Pflege

Aktuelle Baseline: `docs/MusicBot_ENGINEERING_BASELINE_v7.md` (Freeze
2026-09-01, 1673 passed / 0 failed, 1 umgebungsbedingt skipped).
Referenziert von `README.md` und `docs/INDEX.md`.

Nach Abschluss jeder ARCH-Phase mit Code-/YAML-Änderung wird die
aktuelle ENGINEERING_BASELINE_vN.md im selben PR aktualisiert
(mindestens: Abschnitt „ARCH Status", „Recent Major Changes",
Testzahlen). Bei größerer Drift (>3 ARCH-Phasen seit letztem Sync)
wird eine neue vN+1 statt eines Nachtrags erstellt.

**Freeze-Abschluss ist selbsttätig, nicht die Freeze-Entscheidung
selbst:** Schließt ein Freeze-Gate-Audit explizit mit 🟢 APPROVED ab
(alle Kriterien PASS, kein offener P0/P1-Befund, mit Evidenz belegt),
gehören das Erstellen der nächsten `ENGINEERING_BASELINE_vN+1.md` und
das Nachziehen der Referenzen in `README.md`, `docs/INDEX.md` und
diesem Abschnitt zum Abschluss dieser Phase dazu — dafür ist keine
gesonderte Nutzeranfrage nötig, sofern nicht ausdrücklich anders
verlangt. Die Freeze-Entscheidung selbst (GO/NO-GO mit Evidenz) bleibt
ein expliziter, eigenständiger Prüfschritt und wird dadurch nicht
automatisiert — nur die mechanische Nacharbeit nach einem bereits
gefällten APPROVED. Commit/Push bleiben wie immer nur nach expliziter
Anweisung.

---

# 31. Zielbild

MusicBot soll sich schrittweise von:

```text
gewachsenes Hobbyprojekt
```

zu:

```text
gut verstandenes
gut getestetes
dokumentiertes
weiterentwickelbares persönliches Softwaresystem
```

entwickeln.

Ohne die Geschichte des Projekts wegzuwerfen.

Ohne Big-Bang-Rewrite.

Ohne unnötige Enterprise-Komplexität.

---

# 32. Engineering-Leitsatz

> **MusicBot wird nicht neu geschrieben. Er wird kontrolliert erwachsen gemacht.**
