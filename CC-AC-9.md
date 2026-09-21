CC-AC-9 — Track-Centric Library Actions

Auftrag

Entwickle das Control Center der Repository "dkmd89-dev/musicbot" von der bisherigen Artist-/Metadata-orientierten Oberfläche konsequent zu einer objektorientierten Library-Navigation weiter:

Library → Artist → Album → Track → Detail / Health / Action

Der zentrale UX-Schritt dieses Tickets:

«Ein Benutzer soll einen Track direkt aus der Library auswählen können und anschließend einen zentralen Track-Kontext mit Informationen, Health/Findings und den bereits vorhandenen Aktionen erhalten.»

Die bestehende Backend-/Service-Architektur soll dabei nicht neu erfunden oder umgebaut werden.

Dieses Ticket ist primär ein Control-Center-UI/UX- und Integrations-Ticket.

---

1. Zuerst analysieren — noch nichts ändern

Bevor du Code änderst, analysiere das Repository und insbesondere:

control_center/templates/library.html
control_center/templates/library_artist_detail.html
control_center/static/
control_center/routers/
control_center/schemas/
services/
tests/test_control_center_ui.py
tests/test_control_center_admin_maintenance_api.py
tests/test_library_repair_maintenance_service.py
docs/FINDINGS_INDEX.md
docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md
MusicBot_ENGINEERING_BASELINE_v11.md

Zusätzlich gezielt suchen nach:

- Track-Datenmodellen / Schemas
- Album-Datenmodellen / Schemas
- Library-Health-Daten
- "issue_codes"
- Track-IDs / Pfade / Identifikatoren
- bestehenden Track-/Album-Detail-Endpunkten
- bestehenden Metadata-Edit-Endpunkten
- bestehenden Preview-/Execute-Flows
- bestehenden Maintenance-Aktionen
- bestehenden Drawer-/Modal-/Dialog-Komponenten
- bestehenden Accessibility-Mustern
- bestehenden UI-Tests
- vorhandenen Security-/Containment-Checks

Entscheidende Regel

Erfinde keinen neuen API-Endpunkt, bevor du zweifelsfrei festgestellt hast, dass die benötigten Daten über bestehende Endpunkte nicht verfügbar sind.

Wenn ein bestehender Endpunkt die benötigten Daten bereits liefert:

→ diesen verwenden.

Wenn mehrere bestehende Endpunkte benötigt werden:

→ vorhandene Endpunkte verwenden.

Nur wenn eine Information nachweislich nicht verfügbar ist, darf ein neuer Endpoint als Option vorgeschlagen werden.

Ein neuer Backend-Endpunkt darf in diesem Ticket nicht automatisch implementiert werden.

---

2. Ausgangspunkt

CC-AC-7 hat bereits die Zielrichtung etabliert:

Library
   ↓
Artist
   ↓
Album / Track
   ↓
gezielte Aktion

Die Library-Hauptseite besitzt bereits:

- KPI-Kacheln
- Artist-Suche
- Artist-Sortierung
- gecachten Library-Health-Report
- kollabierte Library-Metadata-Funktionen

Die Artist-Detailseite besitzt bereits:

Artist
├── Alben
├── Tracks
├── Metadaten bearbeiten
└── Library-Wartung

Diese vorhandene Struktur soll jetzt nicht zerstört, sondern logisch weiterentwickelt werden.

---

3. Zielarchitektur

Die Zielnavigation lautet:

LIBRARY
│
├── Search
│
├── Artists
│
│   └── Artist
│       │
│       ├── Albums
│       │
│       │   └── Album
│       │
│       └── Tracks
│           │
│           └── Track
│               │
│               ├── Information
│               ├── Metadata
│               ├── Health / Findings
│               └── Actions
│
└── Library Diagnostics

Der wichtigste Grundsatz:

«Metadata ist kein primärer Navigationsbereich mehr, sondern eine Eigenschaft bzw. Aktion eines Library-Objekts.»

Die bestehende Funktionalität bleibt jedoch erhalten.

---

4. Track-Auswahl

Auf der Artist-Detailseite sollen Tracks direkt auswählbar werden.

Beispiel:

Tracks

▶ 01 – Auf und davon
   Casper · XOXO

▶ 02 – XOXO
   Casper · XOXO

▶ 03 – So perfekt
   Casper · XOXO

Die gesamte Track-Zeile soll interaktiv sein.

Nicht nur ein kleiner Button oder ein unsichtbarer Link.

Anforderungen

- sichtbarer Hover-State
- sichtbarer Focus-State
- Tastaturbedienung
- "Enter" öffnet den Track
- "Space" darf nicht zu unerwartetem Seitenverhalten führen
- "Escape" schließt den Detailkontext
- vorhandene Link-/Navigation-Semantik nicht unnötig zerstören
- keine künstliche Keyboard-Implementierung, wenn native HTML-Semantik ausreicht

Wenn die vorhandene Architektur einen echten "<button>" oder "<a>" für die Track-Zeile erlaubt, bevorzuge native Semantik.

Keine "div onclick"-Pseudo-Buttons.

---

5. Track Detail Drawer / Modal

Beim Auswählen eines Tracks soll ein zentraler Detailkontext erscheinen.

Bevorzugt:

Detail Drawer

und nicht eine zusätzliche vollständige Seite.

Ziel:

Artist
  ↓
Track auswählen
  ↓
Track Detail Drawer

Die Artist-Seite bleibt darunter erhalten.

---

6. Drawer-Struktur

Der Drawer soll ungefähr diese Informationsarchitektur besitzen:

┌─────────────────────────────────────────────┐
│ 🎵 Tracktitel                          ×    │
│ Artist · Album                             │
├─────────────────────────────────────────────┤
│                                             │
│ INFORMATION                                 │
│                                             │
│ Titel            ...                        │
│ Artist           ...                        │
│ Album            ...                        │
│ Album Artist     ...                        │
│ Genre            ...                        │
│ Jahr             ...                        │
│ Track            ...                        │
│ Disc             ...                        │
│                                             │
├─────────────────────────────────────────────┤
│ HEALTH                                      │
│                                             │
│ ✓ Metadata vollständig                     │
│ ✓ Artwork vorhanden                        │
│ ⚠ Genre fehlt                              │
│                                             │
├─────────────────────────────────────────────┤
│ AKTIONEN                                    │
│                                             │
│ ✏ Titel bearbeiten                          │
│ 🎤 Artist bearbeiten                        │
│ 💿 Album bearbeiten                          │
│ 👤 Albuminterpret bearbeiten               │
│ 🎭 Genre bearbeiten                         │
│                                             │
│ 🔍 Metadata prüfen                           │
│                                             │
├─────────────────────────────────────────────┤
│ REPAIR                                      │
│                                             │
│ vorhandene Repair-/Maintenance-Aktionen     │
│                                             │
└─────────────────────────────────────────────┘

Dies ist ein UX-Ziel, keine Aufforderung, Daten zu erfinden.

Zeige nur Felder, die tatsächlich verfügbar sind.

---

7. Keine erfundenen Health-Daten

Sehr wichtig:

Die UI darf nicht aus vorhandenen Feldern eigene Health-Behauptungen ableiten, wenn dafür keine bestehende Semantik existiert.

Beispiel:

Nicht einfach:

✓ Metadata vollständig

anzeigen, nur weil einige Felder gefüllt sind.

Stattdessen:

1. vorhandene Health-/Issue-Daten verwenden
2. bestehende "issue_codes" verwenden, falls deren Semantik dafür vorgesehen ist
3. vorhandene Health-Schemas verwenden
4. falls keine belastbare Track-Level-Health-Information vorhanden ist:
   - neutral anzeigen
   - oder Health-Sektion zunächst weglassen

Keine neue Health-Business-Logik in diesem Ticket.

---

8. Track-Metadaten

Wenn die Daten verfügbar sind, sollen mindestens diese Informationen berücksichtigt werden:

Title
Artist
Album
Album Artist
Genre
Year
Track Number
Disc Number
MusicBrainz Recording ID
MusicBrainz Release ID
ISRC

Aber:

«Nur tatsächlich vorhandene und bereits unterstützte Felder anzeigen.»

Keine neuen Backend-Felder nur für die UI einführen.

---

9. Aktionen

Der Track-Kontext soll vorhandene Aktionen bündeln.

Mindestens prüfen und — sofern bestehende Endpunkte bereits dafür existieren — integrieren:

Titel bearbeiten
Artist bearbeiten
Album bearbeiten
Albuminterpret bearbeiten
Genre bearbeiten

Zusätzlich prüfen:

Metadata prüfen
Repair / Maintenance

Nur Aktionen integrieren, die über bestehende, getestete Backend-Flows sauber angebunden werden können.

---

10. Bestehende Preview → Execute Architektur erhalten

Die wichtigste Sicherheits-/UX-Regel:

Keine bestehende Preview-/Execute-Semantik entfernen.

Eine Änderung soll weiterhin beispielsweise so funktionieren:

Track Detail
     ↓
Titel bearbeiten
     ↓
aktueller Wert
     ↓
neuer Wert
     ↓
Preview
     ↓
Änderungsvorschau
     ↓
explizite Bestätigung
     ↓
Execute

Nicht:

Button klicken
↓
Datei sofort ändern

Keine Aktion darf durch die neue UI versehentlich direkt schreibend werden.

---

11. Bestehende Backend-Endpunkte wiederverwenden

Vorhandene Funktionen haben Vorrang.

Gezielt prüfen:

admin/maintenance/title-edit
admin/maintenance/artist-rename
admin/maintenance/album-edit
admin/maintenance/albumartist-edit
library/artists/{artist}/genre-preview
library/artists/{artist}/set-genre

sowie vorhandene:

Preview
Execute
Repair
Health
Metadata

Flows.

Die genaue aktuelle API-Struktur ist aus dem Repository zu ermitteln.

Keine URLs aus diesem Prompt blind übernehmen, wenn der aktuelle Code inzwischen anders strukturiert ist.

---

12. Scope-Trennung Artist / Album / Track

Die Library soll langfristig diese Objektstruktur abbilden:

Artist
│
├── Artist Actions
│   ├── Artist Rename
│   ├── Casing
│   ├── Genre
│   └── vorhandene Artist Maintenance
│
Album
│
├── Album Actions
│   ├── Album Edit
│   ├── Album Artist
│   └── vorhandene Album Maintenance
│
Track
│
├── Track Actions
│   ├── Title
│   ├── Metadata
│   ├── Genre
│   └── vorhandene Track Maintenance
│
Finding
│
└── Diagnose / Repair

Aber:

CC-AC-9 implementiert nur das, was für den Track-zentrierten Einstieg tatsächlich erforderlich ist.

Nicht versuchen, gleichzeitig eine komplette Album-Detailarchitektur zu bauen.

---

13. Album-Klickbarkeit

Prüfe, ob die bestehende Album-Darstellung bereits eine sinnvolle Interaktionsmöglichkeit besitzt.

Wenn eine Album-Auswahl ohne Backend-Änderungen sauber möglich ist:

→ Album klickbar machen bzw. als Objekt kontextualisieren.

Wenn dafür ein größerer neuer Daten-/Routing-Umbau nötig wäre:

→ NICHT in CC-AC-9 erzwingen.

CC-AC-9 ist primär:

Artist → Track → Track Context

Album bleibt ein vorbereiteter nächster Evolutionsschritt.

---

14. Library-Metadata auf "/library"

Den bestehenden Bereich:

Library-Metadata
├── Tracks
├── Artists
├── Albums
├── Mapping
└── Missing Metadata

nicht einfach löschen.

CC-AC-7 hat bewusst festgestellt, dass diese Funktionen unterschiedliche Scanpfade besitzen und teilweise weiterhin eigenständig benötigt werden.

Für CC-AC-9 gilt:

- bestehende Funktion erhalten
- keine API entfernen
- keine Scan-Funktion entfernen
- keine Live-Scan-Funktion entfernen
- keine "/metadata"-Stub-Navigation als Ersatz verwenden

Eine spätere Umbenennung zu:

Library Diagnostics

kann als Folgearbeit dokumentiert werden, darf aber nicht ungeplant in CC-AC-9 mitgezogen werden.

---

15. Drawer technisch sauber implementieren

Bevor du eine eigene Drawer-Komponente erstellst:

Suche nach bestehenden Modal-/Dialog-/Overlay-Mustern im Repository.

Wenn kein geeignetes Pattern existiert:

→ eine kleine, lokale UI-Komponente für den Track-Drawer implementieren.

Keine globale UI-Framework-Einführung.

Keine neue Dependency nur für den Drawer.

---

16. Accessibility

Der Drawer muss vollständig tastaturbedienbar sein.

Mindestens:

Track fokussieren
↓
Enter
↓
Drawer öffnet
↓
Focus sinnvoll setzen
↓
Tab innerhalb des Dialogs
↓
Escape
↓
Drawer schließt
↓
Focus kehrt zum auslösenden Track zurück

Wenn ein echtes "<dialog>" verwendet wird, native Semantik bevorzugen.

Falls "<dialog>" nicht zur bestehenden Browser-/CSS-Architektur passt, darf ein zugänglicher eigener Dialog implementiert werden.

Dann erforderlich:

- "role="dialog""
- "aria-modal="true""
- sinnvoller "aria-labelledby"
- Escape
- Focus Management
- Rückgabe des Fokus
- keine Focus-Traps ohne funktionierende Escape-/Close-Logik

Keine künstliche "aria-expanded"-Logik für Dinge, die native Semantik bereits korrekt abbildet.

---

17. Responsive Verhalten

Prüfen mindestens:

360px
390px
412px
1280px

Anforderungen:

- kein horizontaler Scroll
- Drawer darf auf Mobile nicht breiter als der Viewport werden
- Metadaten müssen umbrechen
- lange Dateipfade/IDs dürfen die UI nicht sprengen
- Buttons müssen erreichbar bleiben
- Tracktitel dürfen nicht unkontrolliert Layout zerstören
- vorhandene ".tiles"-Responsivität erhalten

Keine neue globale Breakpoint-Architektur, wenn sie nicht zwingend notwendig ist.

---

18. Security

Bestehende Security-/Containment-Mechanismen nicht verändern.

Insbesondere nicht anfassen:

_resolve_within
artist_targets
album_targets
_title_edit_targets
safety_check

und die bestehenden Tests:

tests/test_library_repair_maintenance_service.py
tests/test_control_center_admin_maintenance_api.py

nicht verändern, um neue UI-Tests „grün zu machen“.

Das bestehende CC-AC-6 Finding:

album_targets() dead is_symlink() check
P3 / OPEN / DEFERRED

bleibt unangetastet.

---

19. Tests

Vorhandene UI-Tests nicht entfernen oder abschwächen.

Neue Tests in:

tests/test_control_center_ui.py

hinzufügen.

Mindestens abdecken:

Track UI

test_artist_detail_tracks_are_interactive

Track Drawer

test_artist_detail_has_track_detail_context

Metadata

test_track_detail_context_displays_available_metadata

Actions

test_track_detail_context_exposes_existing_actions

Preview/Execute

test_track_action_preserves_preview_execute_flow

Accessibility

test_track_detail_context_has_accessible_dialog_semantics

Security / Regression

Bestehende Security-Tests müssen unverändert grün bleiben.

---

20. Browser-Runtime-Test

Nach den Unit-/UI-Tests unbedingt Playwright bzw. die vorhandene Browser-Testinfrastruktur verwenden.

Manuell prüfen:

Artist

/library/{artist}

Track

- Track sichtbar
- Track fokussierbar
- Track anklicken
- Drawer öffnet

Keyboard

- Tab
- Enter
- Space
- Escape

Drawer

- korrekter Track
- korrekter Artist
- korrekter Albumname
- verfügbare Metadaten
- vorhandene Aktionen

Preview

Mindestens:

Titel bearbeiten → Preview

und falls vorhanden:

Genre / Maintenance → Preview

Nicht Execute ausführen, außer dies ist ausdrücklich beauftragt.

---

21. Tests zuerst analysieren, dann implementieren

Vor Änderungen:

python3 -m pytest tests/test_control_center_ui.py -q

Danach Implementierung.

Anschließend:

python3 -m pytest tests/test_control_center_ui.py -q

python3 -m pytest \
  tests/test_control_center_admin_maintenance_api.py \
  tests/test_library_repair_maintenance_service.py \
  -q

Wenn diese Tests grün sind:

python3 -m pytest tests/ -q

Falls die Full Suite wegen externer Voraussetzungen scheitert:

- exakte Fehlermeldung dokumentieren
- nicht als UI-Regression interpretieren
- nicht durch Test-Manipulation beheben

---

22. Dokumentation

Nach erfolgreicher Implementierung:

docs/audits/CONTROL_CENTER_ARCHITECTURE_2026-09-15.md

um einen Abschnitt ergänzen:

Track-Centric Library Actions — CC-AC-9

Dokumentieren:

- Ausgangsproblem
- neue Objekt-/Navigationsstruktur
- Track-Detail-Kontext
- verwendete bestehende APIs
- Preview/Execute-Erhalt
- Accessibility
- Security-Unverändertheit
- bewusste Nicht-Änderung von CC-AC-6
- offene Folgearbeiten, falls vorhanden

Keine neue Dokumentationsstruktur erfinden.

---

23. Strikte Out-of-Scope-Regeln

NICHT durchführen:

- keine neue Repair Engine
- keine neue Metadata Engine
- keine neue Scan Engine
- keine Änderung der Library-Health-Berechnung
- keine Änderung der Telegram-Flows
- keine Änderung bestehender Security-Mechanismen
- keine Entfernung bestehender Metadata-Scanfunktionen
- keine Entfernung des Artists-Live-Scans
- kein Ersatz von "/metadata" durch eine neue Fake-Navigation
- keine neuen externen Dependencies nur für UI
- keine globale CSS-Neuarchitektur
- keine neuen globalen Breakpoints ohne zwingenden Grund
- keine komplette Album-Detailseite erzwingen
- keine komplette Library-Neuimplementierung
- keine Änderung von CC-AC-6
- keine Änderung an bestehenden Security-Tests
- keine Änderung von "docs/prompts/"-Altänderungen aus vorherigen Sessions
- keine unrelated cleanup commits

---

24. Git-Regeln

Branch:

feature/track-centric-library-actions

Falls bereits ein dafür vorgesehener CC-AC-9-Branch existiert:

→ diesen verwenden.

Nicht auf "main" entwickeln.

Vor Commit:

git status
git diff --check
git diff

Nur CC-AC-9-relevante Dateien committen.

Ein atomarer Commit:

feat(control-center): add track-centric library actions

Nicht pushen und keinen PR erstellen, sofern dies nicht ausdrücklich beauftragt wurde.

---

25. Wichtig: Bestehende uncommittete Änderungen

Es existieren möglicherweise bereits uncommittete Änderungen aus vorherigen Sessions, insbesondere unter:

docs/prompts/

Diese:

- nicht überschreiben
- nicht löschen
- nicht formatieren
- nicht committen

Vor Beginn:

git status --short

prüfen.

---

26. Definition of Done

CC-AC-9 ist erst fertig, wenn:

- [ ] Repository vollständig analysiert
- [ ] bestehende Track-/Album-/Health-Datenquellen identifiziert
- [ ] keine unnötige neue API eingeführt
- [ ] Tracks direkt auswählbar
- [ ] Track Detail Drawer/Context funktioniert
- [ ] relevante Metadaten werden korrekt angezeigt
- [ ] Health/Issues nur aus belastbaren vorhandenen Daten angezeigt
- [ ] bestehende Metadata-Aktionen erreichbar
- [ ] bestehende Maintenance-Aktionen korrekt angebunden
- [ ] Preview → Confirmation → Execute unverändert erhalten
- [ ] keine Aktion versehentlich direkt schreibt
- [ ] Keyboard-Navigation funktioniert
- [ ] Escape funktioniert
- [ ] Focus Management funktioniert
- [ ] Responsive 360/390/412/1280 geprüft
- [ ] bestehende UI-Tests grün
- [ ] neue CC-AC-9-Tests grün
- [ ] Security-Regressionstests grün
- [ ] Full Suite ausgeführt oder sauber dokumentiert, falls extern blockiert
- [ ] Dokumentation aktualisiert
- [ ] CC-AC-6 unverändert offen
- [ ] keine unrelated Änderungen
- [ ] "git diff --check" sauber
- [ ] atomarer Commit erstellt

---

27. Abschlussbericht

Nach der Implementierung NICHT nur „fertig“ melden.

Liefere einen strukturierten Bericht:

CC-AC-9 Ergebnis

1. Analyse

Welche bestehenden Track-/Album-/Health-Datenquellen wurden gefunden?

2. Geänderte Dateien

Tabelle:

Datei| Änderung| Zweck

3. Vorher

Konkrete bisherige UI-Struktur.

4. Nachher

Konkrete neue Struktur:

Library
 ↓
Artist
 ↓
Track
 ↓
Detail
 ↓
Action

5. Datenquellen

Welche bestehenden Endpunkte/Schemas werden verwendet?

6. Neue UI-Komponenten

Drawer/Dialog/etc.

7. Aktionen

Welche bestehenden Aktionen wurden integriert?

8. Preview/Execute

Wie wurde sichergestellt, dass kein direkter Write ohne Bestätigung möglich ist?

9. Accessibility

Keyboard, Focus, Escape, Dialog-Semantik.

10. Security

Bestätigung, dass CC-AC-6 und bestehende Containment-Mechanismen unangetastet sind.

11. Tests

Mit exakten Ergebnissen:

test_control_center_ui.py: X/X
admin maintenance: X/X
library repair service: X/X
Playwright: X/X
Full suite: X/X

12. Responsive

Ergebnisse für:

360px
390px
412px
1280px

13. Dokumentation

Welche Dokumentationsdateien wurden aktualisiert?

14. Open Points

Nur tatsächlich verbleibende Punkte.

15. Git

Branch:
Commit:
Commit message:
Push:
PR:

---

ABSCHLIESSENDE ARBEITSREGEL

Arbeite nach diesem Prinzip:

«Bestehende Architektur verstehen → bestehende Daten/API wiederverwenden → minimale UI-Erweiterung → bestehende Sicherheits-/Preview-/Execute-Mechanismen erhalten → testen → dokumentieren.»

Nicht versuchen, CC-AC-9 größer zu machen als notwendig.

Das Ziel ist nicht, das gesamte Control Center neu zu bauen.

Das Ziel ist:

Library
  ↓
Artist
  ↓
Track
  ↓
ein zentraler, sauberer Track-Kontext
  ↓
bestehende Funktionen gezielt erreichbar

und damit die bisherige Architektur konsequent weiterzuführen.