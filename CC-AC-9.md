Ja — **genau diese Richtung würde ich jetzt einschlagen**. Und nach der Analyse des aktuellen `main` ist interessant: Ihr habt mit **CC-AC-1 bis CC-AC-7 bereits fast die richtige Grundlage gebaut**. Der nächste Schritt sollte nicht noch mehr einzelne Funktionen auf die Library-Seite packen, sondern die **Interaktionslogik von „Artist → Album → Track → Aktion“ konsequent fertigbauen**.

[Repository / Control Center auf GitHub](https://github.com/dkmd89-dev/musicbot/tree/main/control_center?utm_source=chatgpt.com)

## 1. Aktueller Stand

Die letzten Commits zeigen eine klare Entwicklung:

- **CC-AC-1:** Artist-zentrierte Library eingeführt.
- **CC-AC-2:** manual metadata editing v1 in artist context.
- **CC-AC-3:** manual metadata editing v2 (album/albumartist) in artist context.
- **CC-AC-4:** Library-Wartung in den Artist-Kontext verschoben.
- **CC-AC-Cleanup:** doppelte Wartungs-/Metadata-Formulare aus Admin und Metadata entfernt.
- **CC-AC-7:** Library UI weiter konsolidiert.
- **CC-AC-8:** Library UI library dashboard UX optimiert.

- Zuletzt wurde `library.html` auf eine klarere Informationsarchitektur gebracht: **Library → Artist → Album/Track → gezielte Aktion**. Der Commit `531fb554` beschreibt genau dieses Ziel.

Besonders wichtig: Der aktuelle Code verwendet bereits einen persistenten Health-Report für die normale Library-Anzeige, statt beim Seitenaufruf einen ca. 37-Sekunden-Live-Scan auszulösen. Das ist für eine Enterprise-artige Oberfläche eine wichtige Grundlage.

Auch `MusicBot_ENGINEERING_BASELINE_v11.md` ist inzwischen auf dem Stand von ARCH-033 und beschreibt den aktuellen Architektur-/Repair-Stand. :chatgpt-content-reference{index="1"}
     `MusicBot_ENGINEERING_BASELINE_v11.md`
---

# 2. Was mich an der aktuellen Library noch stört

Auf deinem Screenshot sieht man das eigentliche Problem sehr gut:

### Aktuell ungefähr:

```text
Library
│
├── Artists
│    ├── Artist A
│    ├── Artist B
│    └── ...
│
└── Library-Metadata
     ├── Tracks
     ├── Artists
     ├── Albums
     ├── Mapping
     └── Missing Metadata
```

Und auf der Artist-Seite:

```text
Artist
│
├── Alben
├── Tracks
│
├── Metadaten bearbeiten
│    ├── Artist
│    ├── Titel
│    ├── Album
│    ├── Albuminterpret
│    └── Genre
│
└── Library-Wartung
     ├── Casing
     ├── Legacy Genre
     ├── L2
     └── L3
```

Das ist funktional, aber noch **aktionsorientiert statt objektorientiert**.

Der Benutzer denkt eigentlich:

> „Ich sehe diesen Titel. Was kann ich mit diesem Titel machen?“

und nicht:

> „Ich muss zuerst in den Bereich Metadaten gehen und dort das richtige Formular finden.“

---

# 3. Deine Idee ist deshalb architektonisch sehr sinnvoll

Ich würde die Library auf dieses Modell umstellen:

```text
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
│       └── Tracks
│           │
│           └── Track
│               │
│               ├── Informationen
│               ├── Metadata
│               ├── Health / Findings
│               └── Aktionen
│
└── Library Health
```

Der entscheidende Punkt:

## **Metadata ist kein eigener Navigationsbereich mehr.**

Metadata wird eine **Eigenschaft bzw. Aktion eines Library-Objekts**.

Das ist ein großer UX-Unterschied.

---

# 4. Beispiel für einen Track-Klick

Nehmen wir:

```text
🎵 03 – Sonne
Album: Lieblingsalbum
Artist: Casper
```

Der Track wird anklickbar.

Dann öffnet sich beispielsweise rechts ein **Detail Drawer**:

```text
┌──────────────────────────────────────────────┐
│  🎵 Sonne                              ×     │
│  Casper · XOXO                              │
├──────────────────────────────────────────────┤
│                                              │
│  TRACK                                       │
│  Titel          Sonne                        │
│  Artist         Casper                       │
│  Album          XOXO                         │
│  Album Artist   Casper                       │
│  Genre          Hip-Hop                      │
│  Jahr           2011                         │
│  Track          03                           │
│                                              │
│  ──────────────────────────────────────────  │
│                                              │
│  HEALTH                                      │
│  ✓ Metadata vollständig                     │
│  ✓ Artwork vorhanden                        │
│  ✓ MusicBrainz ID vorhanden                 │
│                                              │
├──────────────────────────────────────────────┤
│  AKTIONEN                                    │
│                                              │
│  ✏️ Titel bearbeiten                         │
│  🎤 Artist bearbeiten                        │
│  💿 Album bearbeiten                         │
│  👤 Albuminterpret bearbeiten               │
│  🎭 Genre bearbeiten                         │
│                                              │
│  🔍 Metadata prüfen                           │
│  🔄 Metadata neu verarbeiten                 │
│                                              │
│  ──────────────────────────────────────────  │
│  🛠 Reparatur                                │
│  🔗 Datei öffnen                             │
└──────────────────────────────────────────────┘
```

**Das wäre für mich die eigentliche nächste Evolutionsstufe.**

---

# 5. Noch besser: Aktionen kontextabhängig machen

Nicht jeder Track sollte dieselben Aktionen anzeigen.

Beispielsweise:

```text
Track
│
├── Titel bearbeiten
├── Artist bearbeiten
├── Album bearbeiten
├── Albuminterpret bearbeiten
├── Genre bearbeiten
│
├── Health
│   ├── Metadata prüfen
│   ├── fehlende Metadata anzeigen
│   └── Finding anzeigen
│
└── Repair
    ├── L2
    └── L3
```

Wenn aber der Track bereits sauber ist:

```text
✓ Metadata vollständig
✓ Artwork vorhanden
✓ IDs vorhanden
```

muss die Oberfläche nicht fünf Warn-/Repair-Buttons zeigen.

Wenn dagegen:

```text
⚠ Genre fehlt
⚠ MusicBrainz Recording ID fehlt
⚠ Artwork fehlt
```

kann das Panel direkt anzeigen:

```text
PROBLEME

⚠ Genre fehlt
   → Genre bearbeiten

⚠ MusicBrainz Recording ID fehlt
   → L3-Reparatur
```

Damit wird das Control Center **diagnostisch statt formularorientiert**.

---

# 6. Der wichtige Architekturpunkt: vorhandene Backend-Funktionen weiterverwenden

Das Schöne an deinem aktuellen Stand:

**Wir müssen dafür nicht die komplette Backend-Architektur neu bauen.**

Die bestehenden Endpunkte existieren bereits.

Zum Beispiel:

```text
admin/maintenance/title-edit
admin/maintenance/artist-rename
admin/maintenance/album-edit
admin/maintenance/albumartist-edit
library/.../set-genre
```

und die Services darunter existieren ebenfalls.

`admin_maintenance.py` delegiert bereits an:

```text
preview_title_edit()
execute_title_edit()

preview_album_edit()
execute_album_edit()

preview_album_artist_edit()
execute_album_artist_edit()

preview_artist_rename()
execute_artist_rename()
```

Das ist sehr gut, weil die UI damit **keine neue Business-Logik bekommen muss**.

Die Architektur sollte also sein:

```text
                 Control Center
                       │
                Track Detail UI
                       │
              ┌────────┴────────┐
              │                 │
          Information        Actions
                                │
                     existing API endpoints
                                │
                     maintenance_service
                                │
                     library_repair services
```

Nicht:

```text
Control Center
     │
     └── eigene Metadata-Logik
```

---

# 7. Ich würde sogar noch einen Schritt weitergehen

Ich würde **nicht für jede Aktion eine neue Seite erstellen**.

Also nicht:

```text
/library/artist/album/track
/library/artist/album/track/edit-title
/library/artist/album/track/edit-artist
...
```

Sondern:

```text
/library
    ↓
/library/{artist}
    ↓
Track auswählen
    ↓
Track Detail Drawer / Modal
    ↓
Aktion
```

Die Aktion öffnet dann beispielsweise ein kleines Preview-Dialogfenster:

```text
Titel bearbeiten

Aktuell:
03 – Sonne

Neu:
[ Sonne (Album Version) ]

        Abbrechen     Vorschau
```

Danach:

```text
Änderungsvorschau

03.m4a

Title:
Sonne
   ↓
Sonne (Album Version)

[ Abbrechen ]     [ Änderung anwenden ]
```

Damit bleibt die Seite selbst ruhig.

---

# 8. Was mit „Metadaten“ auf der Haupt-Library passiert

Hier würde ich deine Idee konsequent durchziehen.

Der aktuelle Block:

```text
Library-Metadata

[Tracks] [Artists] [Albums] [Mapping]

Fehlende Metadata:
[...]
```

ist aus UX-Sicht nicht mehr der primäre Weg.

Ich würde ihn **nicht sofort komplett löschen**.

Denn eure eigene Architektur dokumentiert, dass diese alten Metadata-Routen bewusst erhalten wurden und teilweise einen anderen Scanpfad haben.

Stattdessen:

### Phase 1

```text
Library

[Search...]

Artists
...

Library Health
...
```

### Phase 2

Den alten Metadata-Browser entweder:

```text
Advanced / Diagnostics
```

oder:

```text
Library Diagnostics
```

verschieben.

Dann wäre die Informationsarchitektur:

```text
Library
│
├── Browse
│    ├── Artists
│    ├── Albums
│    └── Tracks
│
└── Diagnostics
     ├── Metadata
     ├── Health
     ├── Findings
     └── Mapping
```

Das ist deutlich sauberer.

---

# 9. Enterprise-Level Library

Ich würde langfristig diese Struktur anstreben:

```text
┌───────────────────────────────────────────────────────────┐
│ Library                                                   │
│                                                           │
│ Search library...                        Filter   Refresh  │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ 500 Tracks       41 Artists       59 Albums       99.9%  │
│                                                           │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ Artists                                                   │
│                                                           │
│ 🔎 Search artists...                 Sort: Health / Name  │
│                                                           │
│ Casper                              97   7 Albums         │
│ Cro                                 100  5 Albums         │
│ ...                                                       │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

Klick:

```text
Casper
    ↓
```

```text
┌───────────────────────────────────────────────────────────┐
│ ← Library / Casper                                       │
│                                                           │
│ Casper                                                    │
│ 97 Health · 100 Tracks · 7 Albums                        │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ Albums                                                    │
│                                                           │
│  XOXO                                      14 tracks      │
│  Hinterland                                 12 tracks      │
│                                                           │
├───────────────────────────────────────────────────────────┤
│ Tracks                                                    │
│                                                           │
│ 01 Auf und davon                         ✓               │
│ 02 XOXO                                   ⚠               │
│ 03 So perfekt                             ✓               │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

Klick:

```text
02 XOXO
```

→ **Drawer**.

---

# 10. Und genau dort würde ich auch die Health-Daten integrieren

Das ist besonders interessant wegen eurer aktuellen Library-Health-Architektur.

Der Track hat bereits:

```text
issue_codes
artist
album
album_artist
title
year
genre
track_number
disc_number
mb_recording_id
mb_release_id
isrc
integrated_lufs
...
```

Das bedeutet:

**Die Daten für einen hochwertigen Track-Inspector existieren bereits.**

Der neue UI-Schritt ist hauptsächlich:

```text
TrackSchema
      ↓
Track Detail View
      ↓
Actions
```

statt neue Scan-/Business-Logik zu bauen.

---

# 11. Ein wichtiger Punkt: „Titel anklicken“ sollte wirklich den Titel bedeuten

Auf deinem Screenshot würde ich die komplette Zeile klickbar machen:

```text
▶ 03 – Sonne
   Casper · XOXO
```

nicht nur einen kleinen Button.

Aber zusätzlich:

- `Enter` öffnet
- `Space` öffnet nicht versehentlich die Seite, falls es kein Button ist
- sichtbarer Fokus
- `Esc` schließt Drawer
- `←` / `→` könnte später zwischen Tracks navigieren

Damit bekommt das Ganze eine richtige **Admin-/Operations-UI-Haptik**.

---

# 12. Meine empfohlene nächste Phase

Ich würde **noch nicht sofort programmieren**.

Da ihr gerade CC-AC-8 abgeschlossen habt, würde ich zuerst einen neuen klar abgegrenzten Architektur-/UX-Schritt definieren:

## **CC-AC-9 – Track-Centric Library Actions**

Ziel:

> Die Library wird von einer Artist-/Metadata-Browser-Oberfläche zu einer hierarchischen Library-Management-Oberfläche weiterentwickelt. Tracks werden direkt auswählbar. Ein Track öffnet einen zentralen Detail-/Action-Kontext. Bestehende Metadata- und Maintenance-Endpunkte werden ausschließlich wiederverwendet. Keine neue Business-Logik.

### Scope

**In Scope**

- Track-Zeilen klickbar machen
- Track Detail Drawer/Modal
- vollständige aktuelle Track-Metadaten anzeigen
- Health-/Issue-Status anzeigen
- vorhandene Aktionen integrieren:
  - Titel bearbeiten
  - Artist bearbeiten
  - Album bearbeiten
  - Albuminterpret bearbeiten
  - Genre
- Preview → Confirmation → Execute beibehalten
- Keyboard-/Accessibility-Verhalten
- vorhandene API-Endpunkte wiederverwenden
- Tests

**Out of Scope**

- neue Metadata-Service-Logik
- neue Repair-Engine
- neue Scan-Engine
- neue Metadata-Felder im Backend
- Änderung der bestehenden Telegram-Flows
- Änderung der Library-Health-Berechnung
- Änderung der bestehenden Sicherheitsmechanismen

---

# 13. Wichtig: Album sollte ebenfalls klickbar werden

Ich würde die Hierarchie nicht nur

```text
Artist → Track
```

machen.

Sondern:

```text
Library
   ↓
Artist
   ↓
Album
   ↓
Track
```

Denn dann können die Aktionen sauber nach Scope unterschieden werden:

| Objekt | mögliche Aktionen |
|---|---|
| **Artist** | Artist umbenennen, Casing, Genre, L2/L3 |
| **Album** | Album bearbeiten, Albuminterpret bearbeiten, Health |
| **Track** | Titel, Genre, Tracknummer, Metadata, Health |
| **Finding** | Diagnose / Reparatur |

Das passt auch sehr gut zu euren bereits vorhandenen `artist_targets()` und `album_targets()`.

---

# 14. Mein konkreter Zielzustand

Ich würde also **nicht**:

> „Metadaten-Funktion entfernen“

sondern:

> **„Metadata aus der Navigation entfernen und in den Library-Objektkontext integrieren.“**

Das ist ein wichtiger Unterschied.

Die Funktion bleibt vollständig erhalten.

Sie wird nur dort angeboten, **wo das Objekt bereits bekannt ist**.

Damit entsteht:

```text
             LIBRARY
                │
             ARTIST
                │
             ALBUM
                │
             TRACK
                │
        ┌───────┴────────┐
        │                │
    INFORMATION       ACTIONS
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Metadata        Health         Repair
          │
    ┌─────┼─────┐
    │     │     │
  Title Artist Album
          │
     Album Artist
     Genre
```

**Das halte ich für die richtige Grundlage, wenn du das Control Center wirklich in Richtung einer professionellen Library-Management-Oberfläche weiterentwickeln willst.**

Und wichtig für euren bisherigen Refactoring-Stil: **CC-AC-9 kann komplett auf der bestehenden Service-/API-Schicht aufsetzen.** Dadurch bleibt der Scope sauber und wir müssen nicht gleichzeitig wieder Architektur im Backend umbauen.

Die aktuelle Codebasis unterstützt diesen Weg bereits ziemlich gut; der CC-AC-7-Commit hat sogar explizit die Zielrichtung **„Library → Artist → Album/Track → gezielte Aktion“** festgelegt. :chatgpt-content-reference{index="2"}

[Aktuellen CC-AC-7-Commit ansehen](https://github.com/dkmd89-dev/musicbot/commit/531fb55435c6161f22f388879a621325befa8ec0?utm_source=chatgpt.com)
