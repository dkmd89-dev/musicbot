# MusicBot ARCH-010 – Downloader Utils Migration

## Status

PLANNED

## Typ

Architektur-Analyse und kontrollierte Migration

## Ziel

ARCH-010 untersucht und migriert die historisch gewachsene Struktur unter:

services/downloader/utils/
services/downloader/utils/metadata/

in eine fachlich und architektonisch klarere Zielstruktur.

Dabei darf die aktuelle Verzeichnisverschachtelung **nicht automatisch als Zielarchitektur übernommen werden**.

Insbesondere ist zu prüfen, ob Komponenten aus:

services/downloader/utils/
services/downloader/utils/metadata/

langfristig in eigenständige Top-Level-Bereiche unter `services/` gehören.

Ziel ist nicht lediglich, das bestehende Verzeichnis "aufzuräumen".

Ziel ist:

> Die Komponenten sollen dort liegen, wo ihre tatsächliche fachliche bzw. architektonische Verantwortung liegt.

Dadurch soll verhindert werden, dass zunächst eine vermeintlich saubere Zwischenstruktur geschaffen wird, die später erneut vollständig verschoben werden muss.

---

# 1. Ausgangslage

Die aktuelle Struktur ist historisch gewachsen:

services/
└── downloader/
    └── utils/
        └── metadata/

Diese Verschachtelung darf nicht automatisch als finale Architektur betrachtet werden.

Der aktuelle POST-ARCH-009-Stand strukturiert `services/` zunehmend nach Verantwortlichkeiten und nicht ausschließlich nach historischer Dateihierarchie.

ARCH-010 setzt diese Richtung fort.

---

# 2. Grundprinzip der Zielarchitektur

## Top-Level Service Boundaries

Top-Level-Verzeichnisse unter `services/` sollen echte fachliche oder architektonische Boundaries repräsentieren.

Grundregel:

> Historische Verzeichnisverschachtelung darf nicht als Architekturgrenze übernommen werden.

Daher ist insbesondere zu prüfen, ob Komponenten aus:

services/downloader/utils/
services/downloader/utils/metadata/

eigentlich eigenständige Verantwortungsbereiche darstellen.

---

# 3. Zielarchitektur-Kandidat

Als langfristige Zielarchitektur soll insbesondere folgende Struktur untersucht werden:

services/
├── downloader/
│   ├── downloader.py
│   ├── spotify_downloader.py
│   ├── playlist_processor.py
│   └── ...
│
├── metadata/
│   ├── metadata_service.py
│   ├── album_processor.py
│   ├── track_processor.py
│   ├── result_translator.py
│   └── ...
│
├── library/
│   ├── organizer.py
│   ├── filename_service.py
│   └── ...
│
├── clients/
│   ├── genius_client.py
│   ├── lastfm_client.py
│   ├── musicbrainz_client.py
│   └── navidrome_api.py
│
├── statistics/
│   ├── play_history_repository.py
│   ├── play_history_poller.py
│   ├── statistics_calculator.py
│   └── chart_renderer.py
│
└── utils/
    └── wirklich allgemeine technische Utilities

Diese Struktur ist ausdrücklich:

> ein Zielarchitektur-Kandidat und keine blind vorgegebene Lösung.

Die endgültige Entscheidung muss anhand der tatsächlichen:

- Verantwortlichkeiten
- Dependencies
- Consumer
- Abhängigkeiten zwischen Komponenten
- fachlichen Boundaries

getroffen werden.

---

# 4. Verantwortungsbereiche

## 4.1 services/downloader/

Verantwortung:

> Musik von externen Quellen beschaffen.

Hier soll ausschließlich Logik verbleiben, die tatsächlich Downloader-spezifisch ist.

Beispiele:

services/downloader/
├── downloader.py
├── spotify_downloader.py
├── playlist_processor.py
└── ...

Mögliche Downloader-spezifische Komponenten sind beispielsweise:

- Download-Orchestrierung
- YouTube-Download
- Spotify-Download
- Playlist-Verarbeitung
- Download-spezifische Verarbeitung
- Download-spezifische Status-/Progress-Logik
- Download-spezifische Hilfsfunktionen

Die konkrete Zuordnung muss jedoch durch die Analyse bestätigt werden.

---

# 5. services/metadata/

Verantwortung:

> Musik-Metadaten ermitteln, anreichern, normalisieren und verarbeiten.

Komponenten, die fachlich unabhängig vom eigentlichen Download sind, sollen ausdrücklich auf eine mögliche Verschiebung nach:

services/metadata/

geprüft werden.

Beispielsweise:

services/downloader/utils/metadata/album_processor.py

könnte langfristig zu:

services/metadata/album_processor.py

werden.

Ebenso:

services/downloader/utils/metadata_result_translator.py

könnte langfristig zu:

services/metadata/result_translator.py

werden.

Diese Positionen sind Beispiele.

Die endgültige Zuordnung muss anhand der tatsächlichen Implementierung und Consumer entschieden werden.

---

# 6. services/library/

Verantwortung:

Bibliotheksbezogene Verarbeitung.

Beispielsweise könnten Komponenten wie:

- Library Organizer
- Filename Service
- Dateinamensverarbeitung
- Bibliotheksstruktur
- Pfad-/Dateiverarbeitung mit Library-Fachbezug

hierhin gehören.

Beispiel:

sanitize_filename()

soll nicht automatisch unter `utils/` landen.

Wenn die Funktion fachlich zur Library-/Dateinamensverarbeitung gehört, ist zu prüfen, ob sie beispielsweise nach:

services/library/filename_service.py

gehört.

---

# 7. services/clients/

Verantwortung:

Technische Adapter für externe Dienste.

Beispiele:

services/clients/
├── genius_client.py
├── lastfm_client.py
├── musicbrainz_client.py
└── navidrome_api.py

Die bestehende Architekturentscheidung aus den vorherigen ARCH-Phasen ist hierbei zu berücksichtigen.

ARCH-010 darf bereits abgeschlossene Entscheidungen nicht stillschweigend verändern.

---

# 8. services/statistics/

Verantwortung:

Statistik- und Play-History-bezogene Komponenten.

Beispielsweise:

services/statistics/
├── play_history_repository.py
├── play_history_poller.py
├── statistics_calculator.py
└── chart_renderer.py

Auch hier gilt:

Die konkrete Zuordnung erfolgt anhand der tatsächlichen Verantwortung und Dependencies.

---

# 9. services/utils/

## Wichtig: kleinste Kategorie

Ein allgemeines:

services/utils/

darf nicht zum neuen Sammelbecken für alle Komponenten werden, deren Position unklar ist.

Die Regel lautet:

> `utils/` ist die kleinste Kategorie.

Nicht:

services/utils/
├── metadata_utils.py
├── downloader_utils.py
├── library_utils.py
└── random_helpers.py

sondern ausschließlich:

services/utils/
└── wirklich querschnittliche technische Hilfsfunktionen

Eine Komponente soll nicht nach `utils/` verschoben werden, nur weil keine unmittelbar passende andere Position gefunden wurde.

---

# 10. Beispiele für die Verantwortungsprüfung

## sanitize_filename()

Nicht automatisch:

services/utils/

Prüfen:

> Ist die Funktion fachlich Bestandteil der Library-/Filename-Verarbeitung?

Wenn ja, ist beispielsweise zu prüfen:

services/library/filename_service.py

---

## MetadataNormalizer

Nicht:

services/utils/

Sondern prüfen:

services/metadata/

---

## DownloadProgressTracker

Prüfen:

services/downloader/

oder gegebenenfalls eine klar definierte Application-Komponente.

Die Entscheidung muss anhand der tatsächlichen Consumer und Verantwortlichkeiten getroffen werden.

---

## NavidromeScanTrigger

Die bestehende Architekturentscheidung ist zu berücksichtigen.

Eine technische Infrastrukturkomponente kann weiterhin unter `utils/` liegen, sofern die bereits dokumentierte Architektur dies begründet.

Nicht jede Komponente muss in einen Top-Level-Servicebereich verschoben werden.

---

# 11. Was ausdrücklich vermieden werden soll

Nicht automatisch diese Struktur erzeugen:

services/
├── downloader/
│   ├── metadata/
│   ├── utils/
│   └── download/

nur weil die Dateien momentan so zusammenliegen.

Ebenso soll nicht entstehen:

services/
└── downloader/
    └── utils/
        └── metadata/
            └── providers/
                └── ...

wenn die enthaltenen Komponenten tatsächlich eigenständige fachliche Boundaries bilden.

Die Verzeichnisstruktur soll die Architektur verständlich machen.

---

# 12. Architekturziel

Wenn jemand das Repository öffnet, soll die Struktur möglichst schnell erkennen lassen:

> Das sind die Hauptbereiche des Systems.

Beispielsweise:

services/
├── downloader
├── metadata
├── library
├── clients
├── statistics
└── utils

Die Top-Level-Struktur soll damit fachliche und architektonische Grenzen sichtbar machen.

---

# 13. Scope

ARCH-010 umfasst zunächst insbesondere:

services/downloader/utils/

und:

services/downloader/utils/metadata/

Zusätzlich müssen jedoch die tatsächlichen Consumer repo-weit analysiert werden.

Die Analyse darf deshalb nicht auf diese beiden Verzeichnisse beschränkt bleiben.

---

# 14. Phase 1 – Analyse

In Phase 1 wird ausschließlich analysiert.

Zu untersuchen sind:

### Dateien

- alle Dateien unter `services/downloader/utils/`
- alle Dateien unter `services/downloader/utils/metadata/`

### Consumer

Repo-weite Consumer sämtlicher betroffener Komponenten.

### Dependencies

Für jede Komponente:

- Imports
- Abhängigkeiten
- verwendete Services
- verwendete Clients
- verwendete Config
- verwendete Utilities
- fachliche Abhängigkeiten

### Verantwortlichkeiten

Für jede Komponente:

> Was ist ihre tatsächliche fachliche Verantwortung?

### Consumer

Für jede Komponente:

> Wer verwendet sie tatsächlich?

### Architektur

Für jede Komponente:

> Welche Top-Level-Boundary passt fachlich am besten?

---

# 15. Phase-1-Regel

Während Phase 1 darf kein Code geändert werden.

Insbesondere:

- keine Dateien verschieben
- keine Dateien umbenennen
- keine Imports ändern
- keine Funktionen ändern
- keine Tests verändern
- keine Architekturentscheidungen vorwegnehmen

Phase 1 dient ausschließlich der Analyse.

---

# 16. Phase-1-Ergebnis

Für jede relevante Komponente soll eine Analyse erstellt werden.

Beispiel:

| Komponente | aktuelle Position | Verantwortung | Consumer | Dependencies | möglicher Zielbereich | Begründung | Risiko |
|---|---|---|---|---|---|---|---|

Dabei muss klar zwischen:

- tatsächlicher Feststellung
- Architekturvorschlag
- offener Frage

unterschieden werden.

---

# 17. Phase 2 – Architekturentscheidung

Erst nach Abschluss der Analyse wird entschieden, welche Komponenten tatsächlich wohin gehören.

Mögliche Zielpositionen sind beispielsweise:

services/downloader/
services/metadata/
services/library/
services/clients/
services/statistics/
services/utils/

Diese Struktur ist weiterhin ein Kandidat und keine automatische Vorgabe.

Die Entscheidung muss sich auf:

- Verantwortlichkeiten
- Dependencies
- Consumer
- fachliche Boundaries
- bestehende Architekturentscheidungen

stützen.

---

# 18. Phase-2-Regel

Eine Komponente wird nicht verschoben, nur weil ihr aktueller Pfad "unschön" ist.

Es muss eine fachliche oder architektonische Begründung geben.

Beispiel:

services/downloader/utils/metadata/

→ services/metadata/

nur wenn die Analyse zeigt:

> Die Komponente verarbeitet Metadata unabhängig vom Downloader und bildet damit einen eigenständigen fachlichen Bereich.

---

# 19. Phase 3 – Migration

Die Migration erfolgt erst nach Abschluss und Prüfung der Architekturentscheidung.

Nicht:

> Analyse und Migration gleichzeitig.

Sondern:

Analyse

↓

Architekturentscheidung

↓

Migration

↓

Audit

---

# 20. Migrationsprinzip

Die Migration erfolgt schrittweise.

Für jede Komponente:

1. Zielposition bestimmen
2. Consumer erfassen
3. Tests erfassen
4. Datei verschieben
5. Imports anpassen
6. Tests anpassen
7. relevante Regressionstests ausführen
8. Consumer erneut prüfen
9. Legacy-Referenzen prüfen

Keine unnötige Big-Bang-Migration.

---

# 21. Keine automatische Zwischenarchitektur

Es soll nicht zunächst dauerhaft eine Struktur wie:

services/downloader/
└── utils/
    └── metadata/

"aufgeräumt" werden, wenn bereits absehbar ist, dass die Komponenten fachlich nach:

services/metadata/

gehören könnten.

ARCH-010 soll gerade verhindern, dass eine solche Zwischenarchitektur geschaffen wird.

---

# 22. Dokumentationsregel

`docs/` bildet zunehmend eine nachvollziehbare Architekturhistorie.

ARCH-010 darf deshalb keine bereits abgeschlossenen Architekturentscheidungen überschreiben oder rückwirkend umdeuten.

Wenn während ARCH-010 festgestellt wird, dass eine bestehende Architekturentscheidung tatsächlich revidiert werden müsste, muss dies ausdrücklich als:

> ARCHITECTURE DECISION CHANGE

dokumentiert und begründet werden.

Historische Entscheidungen bleiben nachvollziehbar.

---

# 23. Architekturhistorie

ARCH-010 ist als Fortsetzung der bisherigen Architekturarbeit einzuordnen.

Insbesondere sind die vorhandenen:

- ARCH-Dokumente
- POST-ARCH-009
- bereits abgeschlossenen Architekturentscheidungen

vor Beginn der Analyse zu lesen und zu berücksichtigen.

Die historische Entwicklung darf nicht verloren gehen.

Ziel ist:

ARCH-009
Navidrome Migration
       ↓
POST-ARCH-009
Audit
       ↓
ARCH-010
Downloader Utils
       ↓
Analyse
       ↓
Architekturentscheidung
       ↓
Migration
       ↓
Audit

---

# 24. Claude-Arbeitsauftrag – Phase 1

Claude soll zunächst alle relevanten Architektur-Dokumente lesen.

Danach:

> Führe ausschließlich PHASE 1 – Analyse durch.

Analysiere dabei:

services/downloader/utils/

und:

services/downloader/utils/metadata/

sowie deren tatsächliche Consumer repo-weit.

Ermittle:

- alle betroffenen Dateien
- alle tatsächlichen Consumer
- alle relevanten Imports
- alle Dependencies
- alle fachlichen Verantwortlichkeiten
- mögliche Top-Level-Boundaries
- Risiken
- Migrationseinschätzungen
- offene Fragen

Ändere noch keinen Code.

Stoppe nach Abschluss der Analyse.

---

# 25. Phase-1-Abschluss

Nach Abschluss von Phase 1 muss Claude:

1. die Analyse in dieser ARCH-010-Datei dokumentieren,
2. die tatsächlichen Findings von Annahmen trennen,
3. mögliche Zielpositionen begründen,
4. offene Architekturfragen dokumentieren,
5. noch keine Migration durchführen.

Erst danach erfolgt die gemeinsame Prüfung der Zielstruktur.

---

# 26. Qualitäts-Gates

ARCH-010 darf nicht von Phase zu Phase übergehen, wenn die jeweilige Grundlage fehlt.

## Gate 1 – Analyse

Erforderlich:

- vollständiger Scope
- repo-weite Consumer
- Dependencies
- Verantwortlichkeiten

---

## Gate 2 – Architekturentscheidung

Erforderlich:

- begründete Zielposition
- keine Konflikte mit bestehenden Entscheidungen
- dokumentierte offene Punkte
- klare Boundary-Zuordnung

---

## Gate 3 – Migration

Erforderlich:

- Tests vorhanden bzw. angepasst
- Consumer bekannt
- Migration planbar
- Rollback möglich

---

## Gate 4 – Abschluss

Erforderlich:

- alle Consumer migriert
- Tests grün
- alte Imports geprüft
- alte Struktur geprüft
- keine unbeabsichtigten Legacy-Abhängigkeiten
- Architektur dokumentiert

---

# 27. Ergebnisse

Dieser Abschnitt wird während der Arbeit ausschließlich mit tatsächlich festgestellten Ergebnissen gefüllt.

Nicht:

- ungeprüfte Annahmen
- hypothetische Architektur
- aus anderen Projekten übernommene Strukturen

Sondern ausschließlich:

- tatsächliche Analyseergebnisse
- tatsächliche Migrationsergebnisse
- tatsächliche Tests
- tatsächliche Architekturentscheidungen

---

# 28. Offene Punkte

Alle während ARCH-010 entdeckten, aber nicht für die aktuelle Migration notwendigen Themen werden hier dokumentiert.

Sie werden nicht automatisch Teil des Scopes.

Beispielsweise:

- weitere mögliche Boundary-Verschiebungen
- spätere Refactorings
- technische Schulden
- mögliche Folge-ARCHs

---

# 29. Abschlusskriterien

ARCH-010 gilt erst als abgeschlossen, wenn:

- [ ] `services/downloader/utils/` vollständig analysiert wurde
- [ ] `services/downloader/utils/metadata/` vollständig analysiert wurde
- [ ] tatsächliche Consumer repo-weit ermittelt wurden
- [ ] Dependencies analysiert wurden
- [ ] Verantwortlichkeiten bestimmt wurden
- [ ] Ziel-Boundaries entschieden wurden
- [ ] bestehende Architekturentscheidungen berücksichtigt wurden
- [ ] notwendige Architecture Decision Changes dokumentiert wurden
- [ ] Migration durchgeführt wurde
- [ ] relevante Tests angepasst wurden
- [ ] Regressionstests erfolgreich sind
- [ ] alte Importpfade geprüft wurden
- [ ] Legacy-Strukturen geprüft wurden
- [ ] keine unbeabsichtigten Abhängigkeiten zurückbleiben
- [ ] Dokumentation aktualisiert wurde

---

# 30. Zentrale Architekturregel

Die wichtigste Regel von ARCH-010 lautet:

> **Top-Level-Verzeichnisse in `services/` repräsentieren echte fachliche oder architektonische Boundaries.**

Daraus folgt:

> **Historische Verzeichnisverschachtelung darf nicht als Architekturgrenze übernommen werden.**

Und insbesondere:

> **`services/downloader/utils/metadata/` ist keine automatisch gültige Zielarchitektur.**

Jede Komponente muss anhand ihrer tatsächlichen Verantwortung eingeordnet werden.

---

# 31. Zweite zentrale Regel

Ebenso gilt:

> **`services/utils/` darf kein Sammelbecken werden.**

`utils/` ist die kleinste Kategorie und enthält ausschließlich wirklich querschnittliche technische Hilfsfunktionen.

Wenn eine Komponente eine erkennbare fachliche Verantwortung besitzt, soll sie nach Möglichkeit dort liegen, wo diese Verantwortung architektonisch hingehört.

---

# 32. Endziel

Das langfristige Ziel ist eine verständliche, fachlich orientierte Struktur:

services/
├── downloader/
├── metadata/
├── library/
├── clients/
├── statistics/
└── utils/

Dabei gilt:

- `downloader/` → Musik von externen Quellen beschaffen
- `metadata/` → Metadaten ermitteln, anreichern, normalisieren und verarbeiten
- `library/` → Bibliotheksorganisation und bibliotheksbezogene Dateiverarbeitung
- `clients/` → externe technische Dienste
- `statistics/` → Statistik und Play-History
- `utils/` → nur wirklich querschnittliche technische Utilities

Diese Struktur ist das **langfristige Architekturziel**, aber die konkrete Migration wird erst nach der repo-weiten Analyse entschieden.

---

# 33. Verbindliche Reihenfolge

ARCH-010 wird in folgender Reihenfolge durchgeführt:

```text
Phase 1
Analyse
    ↓
Phase 2
Architekturentscheidung
    ↓
Phase 3
Migration
    ↓
Tests
    ↓
Finaler Audit
    ↓
ARCH-010 Abschluss

34. Aktueller Startpunkt

Status: PLANNED

Aktueller Schritt: PHASE 1 – ANALYSE

Der nächste konkrete Arbeitsauftrag lautet:

Lies zunächst diese ARCH-010-Datei sowie alle darin referenzierten Architektur-Dokumente. Führe ausschließlich PHASE 1 – Analyse durch. Analysiere dabei services/downloader/utils/ und services/downloader/utils/metadata/ sowie deren tatsächliche Consumer repo-weit. Ändere noch keinen Code und stoppe nach Abschluss der Analyse.
