> **⚠️ ABGELÖST:** Dieses Dokument ist veraltet (Stand 2026-08-16) und wurde durch [`MusicBot_ENGINEERING_BASELINE_v2.md`](./MusicBot_ENGINEERING_BASELINE_v2.md) abgelöst. Es bleibt als Historie erhalten, ist aber nicht mehr die maßgebliche Quelle für den aktuellen technischen Zustand.

---

# musicbot – Reverse-Engineered Projektdokumentation

**Repository:** `dkmd89-dev/musicbot`  
**Branch analysiert:** `main`  
**Stand:** 2026-08-16  
**Methode:** Reverse Engineering des Repository-Inhalts; Logs werden als Verhaltens-/Betriebsreferenz betrachtet.

> Diese Dokumentation beschreibt den aktuell erkennbaren Ist-Zustand. Wo eine Aussage nicht durch den inspizierten Quellcode abgesichert ist, ist sie als offen/zu verifizieren markiert.

---

## 1. Projektüberblick

Das Repository beschreibt sich selbst sehr knapp als:

> „Musikdownloader mit Telegram funktion und Navidrome“

Der aktuelle Code ist deutlich umfangreicher als diese Kurzbeschreibung. Er enthält unter anderem:

- Telegram-Bot und Rich-Menu-System
- YouTube-Downloads
- Spotify-Downloads
- Playlist-Verarbeitung
- Podcast-Sonderlogik
- Metadaten-Anreicherung
- Artist-Normalisierung
- YouTube-Titelparser
- Genre-Mapping und Genre-Hierarchie
- MusicBrainz
- Last.fm
- Genius/Lyrics
- Cover-Art
- Metadaten-Caching
- Duplikat-Erkennung
- Dateiorganisation
- FFmpeg/Loudness-Normalisierung
- Navidrome-Anbindung
- Hörstatistiken
- User-/Rollenverwaltung
- Logging-/Error-Management
- Backups
- Bot-Neustart
- Migrationen
- Test-/Performance-Bereich

Die README selbst dokumentiert davon derzeit praktisch nichts.

---

# 2. Architektur auf hoher Ebene

```text
                         Telegram
                            │
                            ▼
                    ┌─────────────────┐
                    │    bot.py       │
                    │ ExtendedBot     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ RichMenuHandler │
                    └────────┬────────┘
                             │
             ┌───────────────┼─────────────────┐
             │               │                 │
             ▼               ▼                 ▼
        RichMenuSystem   DownloadHandler   Admin/System
             │               │                 │
             │               │                 ├─ Backup
             │               │                 ├─ Restart
             │               │                 ├─ User Mgmt
             │               │                 ├─ Logger
             │               │                 └─ Error Handler
             │               │
             │       ┌───────┴────────┐
             │       │                │
             │       ▼                ▼
             │   YouTube          Spotify
             │       │                │
             │       └───────┬────────┘
             │               ▼
             │     EnhancedMetadataProcessor
             │               │
             │     ┌─────────┼──────────┐
             │     │         │          │
             ▼     ▼         ▼          ▼
          Stats  Artist    Genre      Lyrics
                  │         │          │
                  │         │          └─ Genius
                  │         │
                  │         ├─ MusicBrainz
                  │         └─ Last.fm
                  │
                  └─ Artist maps / overrides
                             │
                             ▼
                     Album / Cover Art
                             │
                             ▼
                     Loudness / FFmpeg
                             │
                             ▼
                      FilenameFixerTool
                             │
                             ▼
                       Music Library
                             │
                             ▼
                         Navidrome
```

---

# 3. Einstiegspunkt und Lebenszyklus

## `bot.py`

`ExtendedBot` ist der zentrale Runtime-Einstiegspunkt.

Die Initialisierung erfolgt in dieser Reihenfolge:

1. Telegram `Application` erzeugen
2. Enhanced Error Handler erzeugen
3. Error Handler bei Telegram registrieren
4. `RichMenuHandler` erzeugen
5. `RichMenuHandler.initialize()`
6. Telegram-Handler registrieren
7. optionale Admin-Kommandos für Error Monitoring registrieren
8. Polling starten
9. periodischen Cleanup-Task starten
10. Statistik-History-Polling starten
11. Telegram Updater starten
12. auf Shutdown warten

Beim Shutdown werden unter anderem:

- Cleanup-Task
- Statistik-Polling
- Error-Handler
- RichMenuHandler
- Telegram Updater
- Telegram Application
- aiohttp-Sessions
- Genius-Sessions

beendet bzw. geschlossen.

Es existiert außerdem Signal-Handling für `SIGINT` und `SIGTERM`.

### Wichtig

Das Projekt verwendet bereits bewusst Ressourcen-Cleanup und Dependency Injection an mehreren Stellen. Es ist also kein völlig unstrukturiertes Skript mehr, sondern ein gewachsenes System mit mehreren Architektur-Schichten.

---

# 4. Telegram-/Menüarchitektur

## `handlers/menu/rich_menu_handler.py`

`RichMenuHandler` ist die Integrationsschicht zwischen Telegram und den Fachkomponenten.

Er verwaltet unter anderem:

- `RichMenuSystem`
- `DownloadHandler`
- `StatistikHandler`
- `NavidromeMenuHandler`
- `UserManagementHandler`
- `EnhancedDuplicateHandler`
- `EnhancedStatusHandler`
- `BackupHandler`
- `BotRestartHandler`
- `EnhancedErrorHandler`
- `EnhancedLoggerMenuHandler`
- `EnhancedMetadataProcessor`
- `SpotifyDownloader`

Die Initialisierungsreihenfolge ist absichtlich vorgegeben.

Besonders wichtig ist die gemeinsame Instanz von `SpotifyDownloader`, die an einzelne `DownloadHandler` injiziert wird.

---

# 5. RichMenuSystem

## `handlers/menu/rich_menu_system.py`

Das Menü ist als hierarchische State Machine aufgebaut.

### Zustände

- `IDLE`
- `MAIN_MENU`
- `DOWNLOAD_MENU`
- `STATS_MENU`
- `ADMIN_MENU`
- `SETTINGS_MENU`
- `LOGGER_MENU`
- `PROCESSING`
- `WAITING_INPUT`
- `ERROR`

### Zugriffsebenen

```text
PUBLIC
USER
MODERATOR
ADMIN
OWNER
```

`MenuItem` enthält:

- ID
- Titel
- Emoji
- Callback
- Handler
- Children
- Parent
- Access Level
- Beschreibung
- Aktivstatus
- Metadaten

### Session-System

Pro Telegram User existiert eine `MenuSession`.

Standard:

- Session Timeout: 300 Sekunden
- maximal 100 Sessions

Die Sessions besitzen:

- aktuellen Menüpunkt
- State
- Navigation History
- beliebige Session-Daten
- Message-ID
- Zeitstempel

---

# 6. Downloadarchitektur

## `klassen/download_handler.py`

`DownloadHandler` ist der zentrale Orchestrator.

Er unterstützt:

- YouTube
- Spotify
- Einzeltracks
- Playlists
- Podcasts
- Duplikaterkennung
- Metadaten
- Library-Organisation
- Abschlussstatistiken

### Unified Dispatcher

```text
handle_url()
    │
    ├── Spotify URL
    │      └── handle_spotify_url()
    │
    └── sonst
           └── handle_youtube_links()
```

---

## YouTube-Pipeline

```text
1. URL & Format prüfen
2. Duplikat-Check
3. Audio-Download
4. Metadaten anreichern
5. Bibliothek organisieren
6. Zusammenfassung
```

---

## Spotify-Pipeline

```text
1. Spotify-URL analysieren
2. Duplikat-Check
3. Spotify-Metadaten laden
4. YouTube-Audio suchen/laden
5. Metadaten anreichern
6. Bibliothek organisieren
7. Zusammenfassung
```

Die Logs sind bewusst mit `[STEP X/N]` strukturiert.

---

# 7. Metadaten-Pipeline

## `services/downloader/utils/enhanced_metadata_processor.py`

Dies ist aktuell eine der zentralen Komponenten des gesamten Projekts.

`EnhancedMetadataProcessor` ist als Singleton umgesetzt und delegiert viele Aufgaben an spezialisierte Prozessoren.

### Unterkomponenten

- `ArtistProcessor`
- `GenreProcessor`
- `LyricsProcessor`
- `CoverProcessor`
- `AlbumProcessor`
- `TitleCleaner`
- `MetadataCacheHandler`
- `AutoLearnManager`

Zusätzlich werden verwendet:

- `ArtistNormalizer`
- `GenreMapper`
- YouTube Parser
- Genius Client
- MusicBrainz
- Last.fm
- FilenameFixer
- AudioEnhancer

---

# 8. Exakte Metadaten-Reihenfolge

Die aktuelle Pipeline ist ungefähr:

```text
1   Track prüfen
2   Metadata Cache prüfen
3   Basisdaten extrahieren
4   YouTube-Titel parsen
5   Artist-Map-Fallback
5.5 Spezialkanal erkennen
5.6 Raw Artist bereinigen
6   finalen Artist bestimmen
7   Titel bestimmen
8   interne Duplikaterkennung
9   Genre bestimmen
9b  MusicBrainz-IDs übernehmen
10  Lyrics suchen
11a MusicBrainz-Daten für Album/Cover
11b Cover Art
12  Album/Jahr
13  Tracknummer
14  Quelldatei prüfen
15  Spezialkanal-/Single-Logik
15b Loudness Normalisierung
16  Datei in Library verschieben
17  Metadaten schreiben
18  MetadataResult erzeugen
19  Metadata Cache speichern
19b Auto-Learning
20  Abschluss
```

Das erklärt auch, warum die Logs sehr detailliert aussehen.

---

# 9. Artist-System

Die Artist-Bestimmung kombiniert mehrere Quellen:

1. YouTube-Titelparser
2. Artist-Map-Fallback
3. Raw Artist
4. Uploader/Channel
5. Playlist/Dominant Artist
6. Normalisierung
7. Feature-Splitting

Das System versucht ausdrücklich zu verhindern, dass der YouTube-Kanal als Artist übernommen wird.

Features:

- Artist Normalisierung
- Kollaborations-Erkennung
- Featuring-Aufteilung
- Overrides
- Known Artists
- Auto-Learning

---

# 10. Genre-System

Das Repository besitzt eine ungewöhnlich umfangreiche Mapping-Schicht.

Unter `mapping/` liegen unter anderem:

- `artist_genre.yaml`
- `artist_overrides.json`
- `auto_learned_artists.yaml`
- `auto_learned_genre.yaml`
- `case_preserve.yaml`
- `channel_genre.yaml`
- `genre_aliases.yaml`
- `genre_filters.yaml`
- `genre_hierarchy.yaml`
- `genre_overrides.yaml`
- `genre_rules.yaml`
- `known_artists.yaml`
- `podcast_rss_feeds.yaml`
- `special_channel.yaml`

Das bedeutet:

> Genre-Zuordnung ist nicht ausschließlich im Python-Code implementiert, sondern stark daten-/regelgetrieben.

### GenreResult

Die Pipeline arbeitet mit strukturierten Genre-Ergebnissen, unter anderem:

- `primary`
- `secondary`
- `source`
- `confidence`
- `raw_tags`
- MusicBrainz IDs

Die Genre-Pipeline kann MusicBrainz-IDs erzeugen, die später für Album- und Cover-Art-Verarbeitung wiederverwendet werden.

Dadurch wird ein zweiter MusicBrainz-Aufruf teilweise bewusst vermieden.

---

# 11. Lyrics

Die Konfiguration sieht:

- Genius
- AZLyrics
- Musixmatch

als Fallback-Kette vor.

Lyrics können:

- gesucht
- gecacht
- in die Audiodatei eingebettet

werden.

Für M4A wird `©lyr` verwendet.

---

# 12. Cover Art

Cover können aus mehreren Quellen kommen.

Mindestens erkennbar:

- bereits eingebettetes Cover
- YouTube Thumbnail
- Fanart.tv
- MusicBrainz IDs

Die Metadata-Pipeline versucht zuerst vorhandene Daten wiederzuverwenden.

---

# 13. MusicBrainz

MusicBrainz wird nicht nur für Genre verwendet.

Es liefert bzw. unterstützt:

- Recording ID
- Artist ID
- Release ID
- Release Group ID
- ISRC
- Album
- Jahr

Diese IDs werden anschließend in `MetadataResult` und in die Datei-Tags übernommen.

---

# 14. Audioverarbeitung

Vor dem Verschieben in die Library wird Loudness Normalization versucht.

Das geschieht über:

```text
AudioEnhancer
    ↓
FFmpeg loudnorm
```

Es existieren unterschiedliche Zielwerte für:

- Musik
- Podcasts

Ein Fehler bei der Loudness-Normalisierung ist laut Code nicht kritisch und stoppt die Metadatenpipeline nicht.

---

# 15. Dateiorganisation

`FilenameFixerTool` übernimmt die eigentliche Library-Organisation.

Die Konfiguration definiert:

```text
Single:
{artist} - {title}.{ext}

Album:
{track_num:02d} - {title}.{ext}

Playlist:
{track_num:02d} - {artist} - {title}.{ext}
```

Albumverzeichnis:

```text
{year} - {album}
```

Singles:

```text
Singles
```

Die Standard-Library liegt laut Config unter:

```text
/mnt/4tb/library
```

---

# 16. Duplikaterkennung

## `handlers/duplicate_handler.py`

Das System besitzt mehrere Ebenen.

### URL-Duplikat

URL wird normalisiert und gehasht.

YouTube wird dabei speziell behandelt:

```text
youtube_video:<video_id>
youtube_playlist:<playlist_id>
```

### Content-Duplikat

Artist + Titel werden normalisiert und gehasht.

### Parser-Duplikat

Wenn der Raw-Titel noch nicht ausreicht, wird der YouTube-Titelparser verwendet.

### Library-Fallback

Zusätzlich wird direkt in der Musikbibliothek gesucht.

Damit existieren praktisch vier Erkennungsebenen:

```text
URL
 ↓
Artist + Titel
 ↓
geparster Artist + Titel
 ↓
physische Library-Datei
```

Das ist eine wichtige Schutzschicht nach einem Neustart, weil ein fehlender Cache-Eintrag durch die Library-Suche kompensiert werden kann.

---

# 17. Navidrome

## `api/navidrome_api.py`

Navidrome wird über die Subsonic API angesprochen.

Unterstützt werden unter anderem:

- Connection Check
- Scan
- Scan Status
- Artists
- Genres
- Indexes
- Albums
- Now Playing
- Recently Played
- Top Songs
- Top Artists
- Period Reviews
- Search
- Serverinformationen

Der Navidrome-Scan kann zusätzlich über einen konfigurierten Shell-Befehl gestartet werden.

---

# 18. Statistiken

Das Projekt besitzt einen eigenen Statistik-Service.

Er wird im Bot-Lebenszyklus als Hintergrund-Polling gestartet und beim Shutdown wieder beendet.

Der RichMenu-Bereich bietet:

- Monatsrückblick
- Jahresrückblick
- Top Songs
- Top Künstler
- zuletzt gespielt

---

# 19. Administration

Das RichMenu besitzt einen Admin-Bereich mit:

- System Status
- Benutzerverwaltung
- System Logs
- Duplikat-Verwaltung
- Error-Verwaltung
- Logger-Verwaltung
- Backup-Verwaltung
- Bot-Neustart
- Test-System
- Navidrome Scan

Admin-Rechte basieren auf:

- Owner-ID
- `ADMIN_USER_IDS`
- gespeicherten User-Rollen

---

# 20. Backup-System

Die Config sieht getrennte Backups vor für:

- Bot-Source
- Music Library

Ziel:

```text
/mnt/backup/Musikserver
```

Es werden maximal fünf Backups behalten.

Ausgeschlossen werden unter anderem:

- Library
- `.git`
- `__pycache__`
- `.pyc`
- Downloads
- Temp
- Cache

---

# 21. Konfiguration

## `config.py`

Die Konfiguration ist sehr umfangreich.

### Verzeichnisse

- Library
- Podcasts
- Downloads
- Temp
- Processing
- Fail
- Archive
- Metadata Cache
- Duplicate Cache
- Lyrics Cache
- Logs
- History
- Stats
- Spotify Import

### Secrets

Secrets werden grundsätzlich aus `.env`/Umgebungsvariablen geladen:

- Telegram Bot Token
- Owner ID
- Admin IDs
- Spotify Credentials
- Genius Token
- Last.fm Keys
- Fanart Key
- Navidrome Credentials
- Podcast Index Credentials

### Feature Flags

Unter anderem:

- Enhanced Metadata
- Artist Fallback
- Metadata Cache
- Lyrics
- Duplicate Detection
- YouTube Parser
- Genre Mapping
- Spotify
- Last.fm
- MusicBrainz
- Auto Learning

---

# 22. Cache-Systeme

Es existieren mehrere getrennte Caches:

```text
metadata_cache
duplicate_cache
lyrics_cache
history
```

Das ist architektonisch sinnvoll, erhöht aber die Komplexität und die Anforderungen an Konsistenz/Invalidierung.

---

# 23. Tests – wichtige Überraschung

Entgegen der ursprünglichen Annahme, dass das Projekt keinerlei Tests besitzt, existiert bereits ein `tests/`-Bereich.

Vorhanden sind unter anderem:

- `test_album_processor.py`
- `test_auto_learn.py`
- `test_genre_processor.py`
- `test_metadata_modules.py`
- `test_suite.py`
- `conftest.py`

Außerdem enthält der Testbereich umfangreiche Tests für das RichMenuSystem.

### Aber:

Die Tests sind nicht durchgehend gleichwertig.

Besonders auffällig ist `test_genre_processor.py`.

Dort wird eine eigene `GenreProcessor`-Implementierung innerhalb der Testdatei definiert, statt die Produktionsklasse direkt zu importieren.

Das ist **kein echter Unit-Test der Produktionsimplementierung**.

Damit ist die reale Testabdeckung deutlich geringer, als die Anzahl der Testdateien vermuten lässt.

Das sollte bei einer zukünftigen Teststrategie unbedingt korrigiert werden.

---

# 24. Testarchitektur – Ist-Zustand

Die vorhandenen Tests decken bereits Bereiche ab wie:

- Menüobjekte
- Menü-Hierarchie
- Zugriffskontrolle
- Session Timeout
- Navigation
- Callback Routing
- Performance von Session Cleanup
- Registry Lookups
- Genre-Logik
- Auto-Learning
- Album Processor
- Metadata Module

Es fehlen bzw. sind nach aktueller Inspektion nicht ausreichend abgesichert:

- kompletter YouTube Download Flow
- kompletter Spotify Flow
- echte Metadata Pipeline
- Cache Hit/Miss über die reale Implementierung
- Duplicate Handler Ende-zu-Ende
- File Moving
- Tag Writing
- FFmpeg/Loudness
- Navidrome Integration
- Telegram Handler Integration
- Error Recovery
- Shutdown/Cleanup
- externe API Fehlerfälle

---

# 25. Logging

Das Projekt besitzt ein eigenes erweitertes Logging-System.

Es gibt:

- modulare Logger
- Logger-Verwaltung über Telegram
- unterschiedliche Log-Level
- Log-Dateien
- Cleanup
- Error Monitoring
- strukturierte Pipeline-Step-Logs

Die Logs sind deshalb für Reverse Engineering besonders wertvoll.

Das Projekt besitzt damit bereits eine Art beobachtbare Runtime-Spezifikation.

---

# 26. Auffällige Architekturmerkmale

## Positiv

### 1. Bereits vorhandene Modularisierung

Trotz des Hobby-Ursprungs existieren bereits:

- Services
- Handler
- Prozessoren
- Clients
- Utilities
- Interfaces
- Mapping-Dateien

### 2. Dependency Injection an mehreren Stellen

Beispiel:

`DownloadHandler` bekommt unter anderem:

- DuplicateHandler
- MetadataProcessor
- SpotifyDownloader
- Logger Factory

Das ist eine gute Grundlage für echte Tests.

### 3. Fallback-Strategien

Viele Bereiche haben bewusst mehrere Datenquellen.

### 4. Runtime-Observability

Die detaillierten Logs sind ungewöhnlich hilfreich.

### 5. Rückwärtskompatibilität

Mehrere Legacy-Wrapper sind vorhanden, damit ältere Aufrufer weiter funktionieren.

---

# 27. Kritische technische Risiken

## A. Secrets in Logs

In `api/navidrome_api.py` wird bei einer Anfrage `full_params` geloggt.

Diese Struktur enthält laut Code auch:

- Navidrome User
- Navidrome Password

Das ist ein **echtes Sicherheitsproblem**.

Das Passwort sollte niemals in normalen Logs erscheinen.

**Priorität: SEHR HOCH**

---

## B. Konfiguration wird beim Import initialisiert

`Config.init()` wird direkt beim Import ausgeführt.

Das bedeutet:

```python
import config
```

kann bereits:

- Verzeichnisse anlegen
- externe Clients initialisieren
- Umgebungsvariablen laden
- Logger konfigurieren

Das erschwert Unit Tests und macht Import Side Effects wahrscheinlich.

**Priorität: HOCH**

---

## C. Singleton Metadata Processor

`EnhancedMetadataProcessor` verwendet `SingletonMixin`.

Das erschwert:

- parallele Tests
- isolierte Tests
- unterschiedliche Configs
- reproduzierbare Testzustände

**Priorität: MITTEL**

---

## D. Große Orchestratoren

Besonders:

- `EnhancedMetadataProcessor`
- `RichMenuHandler`
- `RichMenuSystem`
- `DownloadHandler`
- große Handler-Dateien

Diese sind zwar teilweise modularisiert, aber weiterhin stark gekoppelt.

**Priorität: MITTEL**

---

## E. Legacy-Code und Kompatibilitätslayer

Es existieren explizite Legacy-Wrapper und ältere Handlerstrukturen.

Das ist kurzfristig stabilisierend, langfristig aber ein Wartungsrisiko.

**Priorität: MITTEL**

---

## F. Tests testen teilweise nicht die Produktionsimplementierung

Besonders beim Genre-Test ist das klar erkennbar.

**Priorität: HOCH**

---

## G. Unterschiedliche Cache- und Hash-Strategien

URL, Content, Metadata und Files werden unterschiedlich behandelt.

Das funktioniert als Schutzschicht, erhöht aber das Risiko für:

- False Positives
- False Negatives
- stale entries
- unterschiedliche Normalisierungsregeln

**Priorität: MITTEL**

---

# 28. Empfohlene Teststrategie

Nicht sofort alles refactoren.

### Phase 1 – Characterization Tests

Zuerst das bestehende Verhalten einfrieren:

```text
Input
 ↓
aktueller Output
```

Die Tests sollen zunächst nicht „schöneren“ Code erzwingen, sondern das aktuelle Verhalten dokumentieren.

### Phase 2 – Unit Tests

Priorität:

1. YouTube Parser
2. Artist Processor
3. Title Cleaner
4. Genre Processor
5. Album Processor
6. Duplicate Handler
7. Metadata Cache
8. FilenameFixer

### Phase 3 – Integration Tests

Dann:

```text
Download
 → Metadata
 → File
 → Tags
 → Library
```

### Phase 4 – externe Services

Mocks/Fakes für:

- MusicBrainz
- Genius
- Last.fm
- Fanart
- Navidrome
- Spotify

### Phase 5 – End-to-End

Ein kontrollierter Testtrack durchläuft:

```text
Telegram
 → URL
 → Download
 → Metadata
 → File
 → Library
 → Navidrome
```

---

# 29. Empfohlene Refactoring-Reihenfolge

Nicht nach Dateigröße refactoren.

Sondern nach Risiko:

```text
1. Secrets aus Logs entfernen
2. Import Side Effects aus config.py entfernen
3. echte Produktions-Unit-Tests herstellen
4. Duplicate Detection stabilisieren
5. Metadata Pipeline charakterisieren
6. Cache-Verhalten testen
7. File/Tag Processing testen
8. Download Pipelines testen
9. externe API Clients isolieren
10. große Orchestratoren weiter zerlegen
```

---

# 30. Zielarchitektur

Langfristig wäre folgende Struktur sinnvoll:

```text
bot/
├── application/
│   ├── telegram_app.py
│   └── lifecycle.py
│
├── domain/
│   ├── track.py
│   ├── metadata.py
│   ├── genre.py
│   └── duplicate.py
│
├── application_services/
│   ├── download_service.py
│   ├── metadata_service.py
│   └── library_service.py
│
├── infrastructure/
│   ├── youtube/
│   ├── spotify/
│   ├── musicbrainz/
│   ├── genius/
│   ├── lastfm/
│   ├── fanart/
│   └── navidrome/
│
├── telegram/
│   ├── commands/
│   ├── menus/
│   └── callbacks/
│
├── persistence/
│   ├── metadata_cache/
│   ├── duplicate_cache/
│   └── history/
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

**Aber:** Das sollte erst nach einer Charakterisierung des bestehenden Verhaltens umgesetzt werden.

---

# 31. Wichtigste Erkenntnis

Das Projekt ist nicht einfach „chaotischer Hobbycode“.

Es ist eher:

> **Ein über Jahre gewachsenes, inzwischen relativ umfangreiches Musik-Processing-System, bei dem Architektur und Tests der tatsächlichen Komplexität hinterherlaufen.**

Die wichtigste Aufgabe ist deshalb nicht, alles neu zu schreiben.

Die richtige Strategie ist:

```text
IST-Zustand verstehen
        ↓
IST-Verhalten testen
        ↓
kritische Risiken absichern
        ↓
Dokumentation vervollständigen
        ↓
kleine kontrollierte Refactorings
        ↓
Architektur schrittweise verbessern
```

---

# 32. Dokumentationsstatus

| Bereich | Status |
|---|---|
| Bot Lifecycle | analysiert |
| Telegram Routing | analysiert |
| Rich Menu | analysiert |
| Download Orchestration | analysiert |
| YouTube Pipeline | analysiert |
| Spotify Pipeline | analysiert |
| Metadata Pipeline | analysiert |
| Artist System | analysiert |
| Genre System | analysiert |
| Lyrics | analysiert |
| Cover Art | analysiert |
| MusicBrainz | analysiert |
| Loudness | analysiert |
| Duplicate System | analysiert |
| Navidrome API | analysiert |
| Config | analysiert |
| Cache Architektur | analysiert |
| Tests | analysiert |
| Admin System | teilweise analysiert |
| Backup System | strukturell analysiert |
| Migration System | vorhanden, Detailanalyse offen |
| sämtliche kleine Utility-Dateien | noch nicht vollständig line-by-line auditiert |

---

# 33. Nächster sinnvoller Schritt

Die Dokumentation sollte jetzt nicht als „fertig und abgeschlossen“ betrachtet werden.

Der sinnvollste nächste Schritt ist ein **zweiter Audit-Durchlauf**, bei dem wirklich jede verbliebene Python-Datei und jedes Mapping einzeln gegen diese Architektur geprüft wird.

Dabei würde ich eine Tabelle erzeugen:

```text
Datei
│
├── Zweck
├── öffentliche Klassen
├── öffentliche Funktionen
├── Abhängigkeiten
├── wer ruft sie auf?
├── welche Daten kommen hinein?
├── welche Daten gehen heraus?
├── Seiteneffekte
├── Fehlerverhalten
├── Cache
├── externe APIs
├── Tests vorhanden?
├── Tests realistisch?
├── Legacy?
└── Refactoring-Risiko
```

Damit entsteht aus der jetzigen Reverse-Engineering-Dokumentation eine echte **vollständige Entwickler-Dokumentation des Projekts**.
