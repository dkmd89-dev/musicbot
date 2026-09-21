📄 Vollständiger Production-Prompt (mit Ergänzungen)

Speichern als: docs/prompts/CONTROL_CENTER_OVERVIEW_V2.md

```markdown
# Claude Code Production Prompt
# MusicBot Control Center — Overview Dashboard v2
# Operational Dashboard / Performance / UX

---

## 0. AUFGABE

Implementiere die nächste gezielte Phase des MusicBot Control Centers:

> **Overview Dashboard v2 — Operational Control Center**

Das bestehende Overview Dashboard soll auf Basis des aktuellen Projektstands technisch und UX-seitig optimiert werden.

Der Fokus liegt auf:

1. schneller Darstellung ohne ungefragten vollständigen Library-Scan
2. sauberer Darstellung des aktuellen Systemzustands
3. sinnvoller Nutzung des bereits vorhandenen persistenten Library-Health-Reports
4. klarer Darstellung von Findings / Attention
5. sinnvoller Darstellung laufender Jobs
6. Verbesserung der Recent-Activity-Darstellung
7. Optimierung der Quick Actions
8. klarer Trennung zwischen Overview, Library, Health, Findings, Repairs und Jobs
9. vollständiger Wahrung der bestehenden Architektur und bereits implementierten Funktionen

---

# 1. WICHTIG: BESTEHENDE ARCHITEKTUR IST BASELINE

Der MusicBot befindet sich bereits auf einer weit fortgeschrittenen Zielarchitektur.

NICHT versuchen:

- die Architektur neu zu entwerfen
- Control Center neu zu strukturieren
- eine neue API-Schicht einzuführen
- eine zweite Library-Health-Pipeline zu bauen
- eine zweite Findings-Registry zu bauen
- eine neue Repair-Engine zu bauen
- bestehende Library-/Maintenance-Flows umzuschreiben
- Telegram-Funktionalität unnötig anzupassen
- die Artist-Centric-Library-Architektur zurückzubauen
- SPA/React/Vue einzuführen
- einen globalen State-Manager einzuführen

Bestehende Architektur und vorhandene Services sind zu verwenden.

**Grundregel:**

> Reuse before rebuild.

Wenn eine benötigte Information bereits über einen bestehenden Service, Endpoint, persistenten Report oder vorhandene Helper verfügbar ist, muss dieser wiederverwendet werden.

---

# 2. ZUERST: AKTUELLEN PROJEKTSTAND PRÜFEN

Bevor Code geändert wird:

1. Repository vollständig untersuchen.
2. `CLAUDE.md` lesen.
3. relevante `docs/` lesen.
4. aktuelle Control-Center-Architektur prüfen.
5. aktuelle Overview-Implementierung prüfen.
6. aktuelle Router/API-Struktur prüfen.
7. bestehende Library-Health-Implementierung prüfen.
8. persistenten Health Report prüfen.
9. aktuelle Findings-API prüfen.
10. aktuelle Jobs-API prüfen.
11. aktuelle Download-History prüfen.
12. aktuelle Navigation/Templates/Styles prüfen.
13. relevante Tests identifizieren.
14. letzten Git-Stand und aktuelle Branch-Situation prüfen.

Besonders berücksichtigen:

- aktuelle Control-Center-Architektur
- `control_center/`
- `control_center/templates/`
- `control_center/static/`
- `control_center/routers/`
- `control_center/schemas/`
- `services/library_health/`
- `docs/LIBRARY_HEALTH.md`
- `docs/LIBRARY_REPAIR.md`
- `docs/FINDINGS_INDEX.md`
- relevante Control-Center-Dokumentation
- bestehende Architecture-/Baseline-Dokumentation

Nicht von älteren Dokumenten ausgehen, wenn aktueller Code bereits weiterentwickelt wurde.

Bei Widersprüchen gilt:

> aktueller Code + aktuelle Tests + aktuelle CLAUDE.md + aktuelle Architektur-Dokumentation

---

# 3. AKTUELLEN OVERVIEW-IST-STAND ANALYSIEREN

Analysiere insbesondere:

- `overview.html`
- Overview-JavaScript
- Overview-CSS
- UI-Router
- verwendete API-Endpunkte
- Datenmodelle / Schemas
- Fehlerbehandlung
- Loading-Verhalten
- Health-Datenquelle
- Findings-Datenquelle
- Jobs-Datenquelle
- Recent Downloads
- Navigation

Dokumentiere intern vor der Implementierung:

### A. Welche Daten werden aktuell geladen?

### B. Welche Requests werden beim Öffnen der Overview ausgeführt?

### C. Welche davon sind teuer?

### D. Führt ein Overview-Aufruf aktuell indirekt einen vollständigen Library Health Scan aus?

### E. Welche Daten liegen bereits persistent vor?

### F. Welche bestehenden Endpoints können wiederverwendet werden?

### G. Welche Informationen fehlen wirklich?

Nur wenn tatsächlich eine Information fehlt, darf eine kleine zusätzliche API-/Schema-Erweiterung vorgenommen werden.

---

# 4. KRITISCHER PERFORMANCE-PUNKT

## Overview darf keinen vollständigen Library Health Scan automatisch auslösen.

Das ist eine zentrale Anforderung.

Wenn der aktuelle Endpoint

```text
GET /api/v1/library/health
```

einen vollständigen Health Scan über run_scan() ausführt, darf dieser Endpoint NICHT mehr automatisch beim Laden der Overview verwendet werden.

Die Overview muss stattdessen den bereits vorhandenen persistenten Library-Health-Report verwenden.

Ziel:

```text
Overview öffnen
      ↓
persistenter Health Report
      ↓
sofortige Darstellung
```

NICHT:

```text
Overview öffnen
      ↓
run_scan()
      ↓
vollständiger Library Scan
      ↓
lange Wartezeit
      ↓
Darstellung
```

Der vollständige Health Scan gehört zu einer expliziten Health-/Scan-Aktion und nicht zum normalen Dashboard-Aufruf.

---

5. PERSISTENTEN HEALTH REPORT WIEDERVERWENDEN

Untersuche die bereits implementierte persistente Health-Report-Struktur.

Verwende vorhandene Daten, insbesondere soweit verfügbar:

· Track-/File-Anzahl
· Artist-Anzahl
· Album-Anzahl
· Health-/Quality-Status
· Findings Summary
· Report Timestamp
· Scan Timestamp
· relevante Summary-Daten

Die Overview muss kenntlich machen, dass Health-Daten aus einem gespeicherten Report stammen können.

Beispiel:

```text
📚 Library

492 Tracks
43 Artists
128 Alben

Health 99.9
Geprüft vor 2 Stunden
```

Bei einem alten Report:

```text
📚 Library

492 Tracks
43 Artists
128 Alben

Health 99.9
⚠️ Report veraltet
```

Keine falsche Darstellung als Live-Scan.

Beispiel-Response-Schema

Falls ein Cache-Endpunkt nötig ist, sollte er sich an diesem Schema orientieren:

```json
GET /api/v1/library/health
{
  "library": {
    "files": 492,
    "artists": 43,
    "albums": 128
  },
  "health": {
    "status": "GOOD",
    "score": 99.9
  },
  "scan": {
    "completed_at": "2026-09-21T04:27:00Z"
  }
}
```

Bestehende Response-Formate haben Vorrang, wenn sie bereits etabliert sind.

---

6. OVERVIEW-ZIELSTRUKTUR

Das Zielbild ist:

```text
🎛️ Overview

Wie geht es dem MusicBot gerade?
Was braucht Aufmerksamkeit?
Was ist zuletzt passiert?
```

Danach:

```text
SYSTEMSTATUS

┌─────────────┬──────────────┬─────────────┐
│ 📚 Library  │ 🌐 Navidrome │ ⚙️ Jobs      │
│             │              │             │
│ Kennzahlen  │ Online       │ 0 aktiv     │
│ Health      │              │             │
└─────────────┴──────────────┴─────────────┘
```

Danach:

```text
⚠️ AUFMERKSAMKEIT

45 offene Findings

P1   ...
P2   ...
P3   ...

→ Findings ansehen
```

Danach:

```text
🕒 ZULETZT

Letzte erfolgreiche Downloads
...
```

Danach:

```text
SCHNELLZUGRIFF

📚 Library       📥 Downloads
⚠️ Findings      ⚙️ Jobs
```

---

7. SYSTEMSTATUS

Der Systemstatus soll eine schnelle Übersicht über den aktuellen Zustand liefern.

Mindestens berücksichtigen:

Library

· Track-/File-Anzahl
· Artist-Anzahl
· Album-Anzahl, sofern vorhanden
· Health-/Quality-Status
· Report-Zeitpunkt

Navidrome

· Online / Offline
· relevante verfügbare Kennzahl, z. B. Artists
· Fehlerzustand bei Nichterreichbarkeit

Jobs

· Anzahl aktiver Jobs
· optional aktueller Job
· optional Fortschritt, falls bereits verfügbar

---

8. LOADING STATE KORREKT MACHEN

Aktuell darf der UI-Status nicht initial fälschlicherweise:

```text
Healthy
```

anzeigen, bevor die Daten geladen wurden.

Verwende einen echten initialen Zustand:

```text
Lädt...
```

oder semantisch:

```text
UNKNOWN / LOADING
```

Erst nach erfolgreicher Datenabfrage:

```text
Healthy
Warning
Critical
```

anzeigen.

Es darf kein kurzer falscher Zustand entstehen:

```text
Healthy
↓
Daten laden
↓
Warning
```

---

9. HEALTH-STATUS

Health darf nicht nur aus einem simplen HTTP-Erfolg abgeleitet werden.

Nutze die bereits vorhandene Health-/Findings-Logik.

Beispiel:

```text
🟢 Systemstatus
Alles betriebsbereit
```

oder:

```text
🟡 Systemstatus
Aufmerksamkeit erforderlich
```

oder:

```text
🔴 Systemstatus
Kritischer Zustand
```

Die genaue Statuslogik muss sich an den vorhandenen Projektdefinitionen orientieren.

Keine neue konkurrierende Health-Logik erfinden.

---

10. FINDINGS / AUFMERKSAMKEIT

Die Overview soll Findings zusammenfassen, nicht die komplette Findings-Seite duplizieren.

Nutze vorhandene:

```text
/api/v1/library/findings/summary
```

bzw. die tatsächlich aktuelle API.

Darstellung beispielsweise:

```text
⚠️ Aufmerksamkeit

45 offene Findings

3 Kategorien betroffen

→ Findings ansehen
```

Wenn Severity-/Priority-Daten bereits sauber verfügbar sind, darf eine kompakte Aufteilung verwendet werden:

```text
P1   0
P2   3
P3  42
```

Aber:

· keine vollständige Findings-Liste
· keine neue Findings-Berechnung
· keine neue Registry
· keine Duplikation der Findings-Logik

---

11. JOBS

Die Jobs-Kachel soll mehr als nur 0 darstellen, wenn bereits aktive Jobs existieren.

Wenn keine Jobs aktiv sind:

```text
⚙️ Jobs

0 aktiv

Keine aktiven Jobs
```

Wenn ein Job aktiv ist:

```text
⚙️ Jobs

1 aktiv

L2 Repair
████████░░ 80 %

→ Jobs ansehen
```

Nur Informationen verwenden, die bereits von der bestehenden Jobs-Infrastruktur geliefert werden.

Keine neue Job-Engine implementieren.

---

12. NAVIDROME

Die Navidrome-Kachel soll den tatsächlichen aktuellen Zustand darstellen.

Beispiel:

```text
🌐 Navidrome

● Online

43 Artists
```

Bei Fehler:

```text
🔴 Navidrome

Nicht erreichbar

→ Navidrome öffnen
```

Vorhandene Navidrome-Service-/API-Logik wiederverwenden.

Keinen zweiten Navidrome-Client bauen.

---

13. RECENT ACTIVITY

Den bestehenden Bereich:

```text
🕒 Zuletzt
```

beibehalten.

Die vorhandene Download-History verwenden.

Ziel:

```text
✓ Ski Aggu, DJ Tö...
  Hardtek Tutorial              12:44

✓ Gebrochene Flügel
  Sido                           12:44

✓ ALLEIN
  Juju                           12:43

✓ wofür ich dich liebe
  XAVI                           12:42

✓ Irgendwer Anders
  Max Giesinger                  12:40

                    Download-Verlauf →
```

Dabei:

· maximal sinnvoll begrenzte Anzahl
· keine neue History-Pipeline
· bestehende Datenquelle verwenden
· Status visuell klar darstellen
· Zeit sauber formatieren
· bestehende Download-History-Seite verlinken

---

14. QUICK ACTIONS NEU ORDNEN

Die aktuellen Quick Actions:

```text
Library
Metadata
Repairs
Jobs
```

sollen auf ihre Rolle als globale Control-Center-Einstiegspunkte geprüft werden.

Zielpräferenz:

```text
📚 Library
📥 Downloads
⚠️ Findings
⚙️ Jobs
```

Die bestehende Navigation muss dabei konsistent bleiben.

Wichtig:

Metadata und Repairs NICHT entfernen.

Sie bleiben über die entsprechenden Library-/Artist-Kontexte erreichbar.

Die Overview soll lediglich die wichtigsten globalen Bereiche priorisieren.

Falls der aktuelle Projektstand eine andere, sachlich bessere Struktur rechtfertigt, diese anhand der tatsächlich vorhandenen Navigation wählen.

---

15. RESPONSIVE UI

Die Overview muss insbesondere auf mobilen Displays funktionieren.

Der aktuelle Screenshot zeigt die mobile Nutzung.

Prüfen:

· Sidebar
· Karten
· Abstände
· Textgrößen
· lange Artist-Namen
· lange Songtitel
· Buttons
· Status-Badges
· Quick Actions
· horizontaler Overflow
· Tabellen-/Listenbreite

Keine Desktop-only-Lösung bauen.

Ziel:

```text
Desktop
Tablet
Mobile
```

ohne separate Architektur.

---

16. VISUELLE PRIORITÄT

Die Seite soll folgende visuelle Hierarchie haben:

1. Systemstatus

Was ist aktuell los?

2. Aufmerksamkeit

Was muss ich prüfen?

3. Aktivität

Was ist zuletzt passiert?

4. Aktionen

Wo kann ich hin?

Nicht alles gleich prominent darstellen.

---

17. OVERVIEW SOLL KEINE LIBRARY-SEITE WERDEN

Die neue Artist-Centric Library UX ist bereits implementiert.

Deshalb:

Overview:

```text
Status
Health
Findings
Jobs
Activity
Navigation
```

Library:

```text
Artists
Albums
Tracks
Artist Detail
Metadata
Maintenance
```

Health:

```text
Health Report
Scan
Detailed Findings
```

Repairs:

```text
Maintenance / Repair Operations
```

Jobs:

```text
Job Execution / History
```

Diese Verantwortlichkeiten strikt beibehalten.

17b. WAS NICHT AUF DIE OVERVIEW GEHÖRT

Explizit NICHT Teil der Overview:

· vollständige Artist-Liste
· vollständige Album-Liste
· Track-Level-Details
· Findings-Detail-Tabelle
· Job-History
· Metadata-Editor
· Repair-Aktionen
· Genre-Revalidierung
· Datei-Mutationen jeder Art
· vollständige Download-History

Wenn eine Information in einen spezialisierten Bereich gehört, dort belassen und nur verlinken.

---

18. API-DESIGN

Bevor ein neuer Endpoint gebaut wird:

1. vorhandene Endpoints prüfen
2. vorhandene Schemas prüfen
3. vorhandene Services prüfen
4. vorhandene Report-Strukturen prüfen

Nur wenn wirklich notwendig, einen kleinen dedizierten Overview-/Summary-Endpoint einführen.

Falls ein neuer Endpoint notwendig ist:

```text
GET /api/v1/overview
```

oder ein vergleichbarer Name darf verwendet werden.

Aber:

· Router enthält keine Business-Logik
· bestehende Services verwenden
· Pydantic Response Model
· keine internen Dataclasses direkt als API Response
· bestehende Access-Level berücksichtigen
· bestehende Error-/request_id-Konvention verwenden
· keine neue globale Cache-Schicht

---

19. PERFORMANCE-ZIEL

Die Overview soll sich wie ein Dashboard anfühlen.

Insbesondere:

Kein vollständiger Library Scan beim normalen Öffnen.

Vermeide unnötige serielle Requests.

Wenn mehrere unabhängige Datenquellen benötigt werden, soll geprüft werden, ob sie parallel geladen werden können.

Aber keine unnötige Komplexität einführen.

Ziel:

```text
Overview öffnen
↓
UI sofort rendern
↓
Daten laden
↓
Karten aktualisieren
```

Nicht:

```text
Overview öffnen
↓
37 Sekunden warten
↓
erst dann UI
```

---

20. ERROR HANDLING

Ein einzelner Fehler darf nicht das gesamte Dashboard zerstören.

Beispiel:

Navidrome offline:

```text
🔴 Navidrome
Nicht erreichbar
```

aber:

```text
Library
Findings
Jobs
Recent Activity
```

bleiben funktionsfähig, sofern deren Daten verfügbar sind.

Ebenso darf ein veralteter Health Report nicht das komplette Overview blockieren.

---

21. ACCESS CONTROL

Bestehende Access-Level-Regeln nicht verändern.

Insbesondere:

· Overview-Zugriff gemäß bestehender Control-Center-Regel
· Findings-Zugriff weiterhin entsprechend bestehender Schwelle
· keine Absenkung bestehender Admin-Grenzen
· keine neuen privilegierten Aktionen auf Overview

Overview bleibt primär read-only.

---

22. READ-ONLY

Diese Phase darf keine neuen mutierenden Overview-Aktionen einführen.

Keine:

· Reparaturen
· Metadata Writes
· Reprocessing
· Genre-Revalidation
· File Changes
· Deletes
· Library Scan automatisch
· Jobs automatisch starten

Links zu bestehenden Funktionen sind erlaubt.

Beispiel:

```text
→ Findings ansehen
→ Jobs ansehen
→ Library öffnen
→ Download-Verlauf ansehen
```

---

23. TESTS

Vor Abschluss:

Backend

Tests für:

· Overview API / bestehende verwendete Endpoints
· Health-Report-Zugriff
· fehlenden Report
· alten Report
· Navidrome offline
· Findings vorhanden
· keine Findings
· aktive Jobs
· keine Jobs

Frontend

Falls vorhandene Teststruktur vorhanden:

· Loading State
· Error State
· Empty State
· Health State
· Findings State
· Jobs State

Regression

Bestehende Tests vollständig ausführen.

Besonders:

· Library Health
· Library Repair
· Findings
· Control Center
· Metadata
· Artist UX
· Security / containment
· API/Auth

Keine bestehenden Tests löschen oder abschwächen.

---

24. PERFORMANCE-REGRESSION TEST

Ganz wichtig:

Stelle sicher, dass das Öffnen der Overview keinen vollständigen Library Health Scan mehr auslöst.

Das muss anhand des tatsächlichen Codes geprüft werden.

Nicht nur anhand der UI.

Suche insbesondere nach:

```text
run_scan()
```

und prüfe den gesamten Call-Path.

---

25. DOKUMENTATION

Nach erfolgreicher Implementierung relevante Dokumentation aktualisieren.

Mindestens prüfen:

· Control-Center-Dokumentation
· Architektur-/Audit-Dokumentation
· ggf. Overview-/UI-Dokumentation

Insbesondere:

· Falls die Overview neue oder geänderte Endpunkte verwendet, muss
  docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
  bzw. die aktuell gültige Control-Center-Architektur-Dokumentation
  entsprechend aktualisiert werden.
· Falls ein neuer Cache-/Summary-Endpunkt eingeführt wurde, muss dieser
  dort dokumentiert sein (Zweck, Datenquelle, Cache-Verhalten,
  Verantwortlichkeit).
· Falls die Overview-Zuständigkeiten gegenüber anderen Seiten verschoben
  wurden (z. B. Attention vs. Findings-Seite), muss das in der
  Architektur-Dokumentation sichtbar sein.

Dokumentieren:

· Overview verwendet persistenten Health Report
· Overview löst keinen vollständigen Health Scan aus
· Verantwortlichkeiten der Dashboard-Bereiche
· verwendete Datenquellen
· relevante Performance-Entscheidung

Keine neue Dokumentation erzeugen, wenn eine bestehende Datei dafür vorgesehen ist.

---

26. GIT WORKFLOW

Arbeite eigenständig und vollständig.

Nach erfolgreicher Implementierung:

1. Änderungen prüfen
2. Tests ausführen
3. Regression prüfen
4. git diff prüfen
5. keine Debug-Reste
6. keine temporären Dateien
7. keine unnötigen Architekturänderungen
8. Commit erstellen

Commit message:

```text
feat(control-center): optimize overview dashboard
```

Danach:

```text
git status
```

prüfen.

Wenn der Workflow des Projekts Push/PR vorsieht und die Umgebung dies erlaubt:

· committen
· pushen
· PR erstellen

Keine fremden Änderungen überschreiben.

---

27. DEFINITION OF DONE

Die Phase ist erst abgeschlossen, wenn alle Punkte erfüllt sind.

Architektur

☐ bestehende Architektur erhalten
☐ bestehende Services wiederverwendet
☐ keine parallele Health-/Findings-/Repair-Logik
☐ keine unnötige API-Schicht

Performance

☐ Overview löst keinen vollständigen Library Scan aus
☐ persistenter Health Report wird verwendet
☐ Loading State ist korrekt
☐ keine unnötigen seriellen Requests

Overview

☐ Systemstatus
☐ Library Summary
☐ Navidrome Status
☐ Jobs Summary
☐ Findings Summary
☐ Recent Downloads
☐ Quick Actions

UX

☐ klare visuelle Hierarchie
☐ mobile Darstellung geprüft
☐ Loading States
☐ Error States
☐ Empty States
☐ veralteter Health Report erkennbar
☐ keine irreführenden Live-Daten

Vorher/Nachher-Nachweis

☐ Screenshot vor der Änderung erstellt
  (docs/audits/assets/overview_before_YYYYMMDD.png oder ähnlich)
☐ Screenshot nach der Änderung erstellt
  (docs/audits/assets/overview_after_YYYYMMDD.png oder ähnlich)
☐ Beide Screenshots zeigen denselben Zustand
  (gleiche Findings-Anzahl, gleiche Jobs, gleiche Recent Activity)
☐ Sichtbare Verbesserungen im Nachher-Screenshot sind klar erkennbar:
  · Systemstatus zeigt korrekten Zustand (kein initiales „Healthy")
  · Library-Kachel zeigt Daten (kein „Lädt…" / „Netzwerkfehler")
  · Health-Report-Zeitpunkt ist sichtbar
  · Recent Activity ist strukturiert
  · Quick Actions sind sinnvoll priorisiert

Wenn keine Screenshot-Möglichkeit besteht (z. B. keine UI-Rendering-Umgebung),
diesen Punkt im Abschlussreport explizit als „nicht möglich" markieren und
die Begründung angeben. Stattdessen:

☐ Curl-/API-Nachweis der Endpunkte mit Zeitmessung vorher/nachher
☐ Nachweis, dass run_scan() im Overview-Call-Path nicht mehr
  erreichbar ist (grep + Call-Path-Analyse)

Sicherheit

☐ bestehende Access-Level erhalten
☐ keine neuen ungeschützten Endpoints
☐ keine neuen Write-Aktionen

Qualität

☐ relevante Tests grün
☐ vollständige Regression grün
☐ keine Debug-Ausgaben
☐ keine temporären Dateien
☐ Dokumentation aktualisiert (inkl. Audit-Doku)
☐ Git sauber

---

28. WICHTIGE ENTSCHEIDUNGSREGEL

Wenn du während der Implementierung auf mehrere mögliche Lösungen stößt:

Priorität:

1. bestehende Architektur
2. bestehende Services
3. bestehende APIs
4. bestehende Datenmodelle
5. bestehende UI-Konventionen
6. minimal-invasive Änderung
7. erst danach neue Abstraktion

Nicht die technisch „schönste“ neue Architektur bauen.

Die Aufgabe ist:

Das bestehende MusicBot Control Center verbessern, nicht neu erfinden.

---

29. ABSCHLUSSREPORT

Nach Abschluss einen kurzen technischen Report ausgeben:

Implementiert

· ...
· ...
· ...

Performance

Vorher:

```text
...
```

Nachher:

```text
...
```

Insbesondere angeben, ob run_scan() beim Overview-Aufruf noch erreicht werden kann.

Verwendete Datenquellen

```text
Library:
...

Navidrome:
...

Findings:
...

Jobs:
...

Downloads:
...
```

Tests

```text
X passed
Y failed
```

Geänderte Dateien

Liste der tatsächlich geänderten Dateien.

Audit-Dokumentation

☐ docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
  (oder gültige aktuelle Fassung) geprüft
☐ Falls relevant: aktualisiert
☐ Falls nicht relevant: im Report begründen

Vorher/Nachher

· Vorher: <Pfad zum Screenshot oder Begründung>
· Nachher: <Pfad zum Screenshot oder Begründung>
· Falls kein Screenshot möglich: Curl-/API-Nachweis mit Zeitmessung

Git

```text
Commit:
Branch:
Status:
PR:
```

---

30. ABSCHLIESSENDE LEITFRAGE

Die fertige Overview muss diese Frage innerhalb weniger Sekunden beantworten:

„Wie geht es meinem MusicBot gerade und worum muss ich mich kümmern?“

Wenn die Antwort auf diese Frage nach dem Öffnen der Seite nicht sofort erkennbar ist, ist die Phase noch nicht abgeschlossen.

```