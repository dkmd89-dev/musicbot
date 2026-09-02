# MusicBot

Privat entwickelter Telegram-Bot für Musik-Download (YouTube), automatische Metadaten-Anreicherung (Artist, Genre, Cover, Lyrics), Library-Organisation und Steuerung eines [Navidrome](https://www.navidrome.org/)-Servers.

Historisch organisch gewachsenes Hobbyprojekt — siehe [`CLAUDE.md`](CLAUDE.md) für die Engineering-Leitlinien und [`docs/MusicBot_ENGINEERING_BASELINE_v8.md`](docs/MusicBot_ENGINEERING_BASELINE_v8.md) für den aktuellen technischen Status (Architektur, Testabdeckung, Security, Technical Debt).

---

## Was der Bot macht

- Nimmt YouTube-Links per Telegram entgegen (auch Playlists; YouTube-Videos aus bekannten Podcast-Kanälen werden automatisch erkannt und gesondert einsortiert)
- Lädt Audio via [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) herunter
- Reichert Metadaten an: Artist-Normalisierung, Genre-Erkennung (MusicBrainz/Last.fm-Tags, Mapping-Regeln, Fuzzy-Matching), Lyrics (Genius), Cover-Art (Cover Art Archive, Fanart.tv, Apple Music, Deezer, YouTube-Thumbnail als Fallback-Kette)
- Erkennt Duplikate über mehrere Ebenen (URL, YouTube-ID, Artist+Titel, Library-Abgleich)
- Organisiert die fertige Datei in der Musik-Library (Dateiname, Verzeichnisstruktur, ID3/MP4-Tags)
- Steuert einen laufenden Navidrome-Server (Scan anstoßen, Status abfragen, Bibliothek durchsuchen) über die Subsonic-API
- Bietet ein Telegram-Menüsystem für Statistiken, Nutzerverwaltung, Logs und Backups (rollenbasiert: Owner/Admin/User), inkl. eines Download-Control-Centers mit Live-Fortschritt und Hard-Cancel für laufende Downloads (Details: [`docs/MusicBot_TELEGRAM_MENU_SYSTEM.md`](docs/MusicBot_TELEGRAM_MENU_SYSTEM.md))

## Architektur (vereinfacht)

```text
Telegram
   ↓
ExtendedBot (bot.py)
   ↓
RichMenuHandler
   ↓
DownloadHandler
   ↓
YouTube (yt-dlp)
           ↓
   Metadata-Pipeline (EnhancedMetadataProcessor)
           ↓
   Artist / Title / Genre
           ↓
   MusicBrainz / Last.fm / Genius (Lyrics) / Cover-Quellen
           ↓
   Audio-Verarbeitung (FFmpeg)
           ↓
   Tags / Dateiname / Library
           ↓
   Navidrome (Subsonic-API)
```

Ausführlicher, mit Datenfluss/Fehlerbehandlung pro Bereich: [`CLAUDE.md`](CLAUDE.md), Abschnitt 4–5.

## Projektstruktur

| Verzeichnis | Inhalt |
|---|---|
| `bot.py` | Einstiegspunkt — initialisiert Telegram-Application, Error-Handler, `RichMenuHandler` |
| `config.py` | Zentrale Konfiguration, lädt Secrets aus `.env` |
| `klassen/` | `download_handler.py` — zentraler Download-Orchestrator (YouTube), einziges verbliebenes Modul in diesem Verzeichnis |
| `services/downloader/` | Download-Pipeline: `downloader.py`, `playlist_processor.py`, `download_utils.py`, `download_result_reporter.py`, `download_artifact_cleanup.py`, `progress_tracker.py`, `errors.py`, `metadata_result_translator.py`, `models.py` (neutrale Datenmodelle, u. a. `DuplicateEntry`), sowie `download/` mit den ausgelagerten Orchestrierungs-Modulen (Cache/Jahr/Channel/Executor/Formatters) |
| `services/metadata/` | Metadaten-Pipeline (ARCH-010): `enhanced_metadata_processor.py` als Facade, sowie die Unterprozessoren `album_processor.py`, `artist_processor.py`, `auto_learn.py`, `cache.py`, `cover_processor.py`, `genre_processor.py`, `lyrics_processor.py`, `tag_writer.py`, `title_cleaner.py`, `models.py` |
| `services/clients/` | Reine externe Integrationsadapter (keine Telegram-Präsentation, keine Fachlogik): `genius_client.py`, `lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py` |
| `services/duplicate/` | Duplicate-Detection-Kern (ARCH-018, Telegram-frei): `detector.py` (URL-/Content-/Parser-/Library-Fallback-Kaskade, nutzt seit P1 denselben `ArtistProcessor`/`ArtistNormalizer`-Pfad wie `services/metadata/`), `cache.py` (JSON-Persistenz-Cache), `classification.py`, `resolution.py`, `execution.py` |
| `services/` (übrige Dateien) | `statistik_service.py` (dünne Fassade) + `services/statistik/` (`play_history_repository.py`, `play_history_poller.py`, `statistics_calculator.py`, `chart_renderer.py`) |
| `handlers/` | Telegram-Handler: Menüsystem (`handlers/menu/`), Admin-Funktionen (`handlers/admin/`), Navidrome-Menü, Statistik, Fehlerbehandlung |
| `utils/` | Wiederverwendbare Bausteine: `genre_map.py`, `artist_map.py`, `filenamefixer.py`, `helpers.py`, Caches (`lyrics_cache.py` u. a.), Singleton-Basisklasse, sowie lokale technische Runner ohne Telegram-/API-Kopplung (`navidrome_scan_trigger.py`, `audio_enhancer.py`) |
| `mapping/` | YAML-/JSON-Dateien mit Fachlogik (Genre-/Artist-Regeln) — **keine belanglose Konfiguration**, siehe unten |
| `scripts/` | Eigenständige Wartungs-Tools, die außerhalb des Bot-Laufzeitbetriebs auf isolierten Testdaten arbeiten, z. B. `reprocess_artist_metadata.py` — bestehende Library-Tracks erneut durch die Metadaten-Pipeline laufen lassen (Tags/Cover/Lyrics/Genre/Multi-Artist/MusicBrainz), ohne Download, ohne Produktionszugriff, ohne Audio-Reencoding. Details: [`docs/METADATA_REPROCESSING.md`](docs/METADATA_REPROCESSING.md) |
| `tests/` | 1908 Tests (pytest), 0 bekannte Fehlschläge, 1 umgebungsbedingt übersprungen (Stand 2026-09-02, nach Telegram-Download-Control-Center-Phase — Baseline v8 selbst bleibt bei ihrem Freeze-Stand 1698/0, aktueller Stand siehe [`docs/FINDINGS_INDEX.md`](docs/FINDINGS_INDEX.md)) — Characterization-Tests für die Produktionsklassen, siehe [`docs/MusicBot_ENGINEERING_BASELINE_v8.md`](docs/MusicBot_ENGINEERING_BASELINE_v8.md) |
| `docs/` | Engineering-Baseline v8 (aktueller Referenzpunkt) + Findings-Audits (P0-Metadata/Duplicate-Detection, Download Pipeline Stability, Metadata Quality, Einzelfunde) + Telegram-Menü-System-Doku + Reprocessing-Tool-Doku + ARCH-Characterization-Dokumente (historisch), siehe [`docs/INDEX.md`](docs/INDEX.md) |

## Setup

**Voraussetzungen:** Python 3.12, `ffmpeg` (Systempaket, für Audio-Konvertierung), ein laufender Navidrome-Server (optional, aber für die Navidrome-Funktionen nötig).

```bash
pip install -r requirements.txt
```

Für Tests zusätzlich:

```bash
pip install -r requirements-dev.txt
```

Konfiguration erfolgt über eine `.env`-Datei im Projektwurzel-Verzeichnis (wird von `config.py` automatisch geladen). Relevante Variablen (siehe `config.py` für die vollständige, kommentierte Liste inkl. Defaults):

```text
BOT_TOKEN=                  # Telegram Bot-Token (erforderlich)
OWNER_USER_ID=               # Telegram-User-ID des Bot-Owners (erforderlich)
ADMIN_USER_IDS=               # Kommagetrennte Liste weiterer Admin-User-IDs
ADMIN_CHAT_ID=

NAVIDROME_URL=
NAVIDROME_USER=
NAVIDROME_PASS=
NAVIDROME_CONTAINER_NAME=

GENIUS_ACCESS_TOKEN=          # optional, für Lyrics
LASTFM_API_KEY=               # optional, für Genre-Tags
LASTFM_API_SECRET=
FANART_API_KEY=               # optional, für Cover-Fallback

AUDIO_FORMAT=                 # z.B. m4a
AUDIO_QUALITY=                # z.B. 192
LOG_LEVEL=
DEBUG_MODE=
```

## Bot starten

```bash
python3 bot.py
```

## Tests ausführen

```bash
python -m pytest tests/ -q
```

`pytest-asyncio` (siehe `requirements-dev.txt`) wird für die `@pytest.mark.asyncio`-Tests in `tests/test_suite.py` benötigt. Aktueller Teststand siehe [`docs/MusicBot_ENGINEERING_BASELINE_v8.md`](docs/MusicBot_ENGINEERING_BASELINE_v8.md).

## Mapping-Dateien

Die YAML-/JSON-Dateien in `mapping/` (Genre-Aliase, Genre-Hierarchie, Genre-Overrides, Genre-Filter, Genre-Regeln, Artist-Genre-Zuordnungen, Artist-Overrides, bekannte Artists, Special-Channels, Channel-Genre) steuern reales fachliches Verhalten — welches Genre ein Track bekommt, wie ein Artist-Name normalisiert wird, ob ein Kanal als Podcast erkannt wird. Änderungen daran werden wie Code-Änderungen behandelt: mit konkreten Vorher/Nachher-Beispielen und Tests, nicht als Bulk-Edit. Details siehe `CLAUDE.md`, Abschnitt 10.

## Entwicklung

Dieses Projekt wird nicht neu geschrieben, sondern kontrolliert weiterentwickelt: bestehendes Verhalten zuerst verstehen und mit Characterization-Tests absichern, dann verbessern. Die verbindlichen Arbeitsregeln stehen in [`CLAUDE.md`](CLAUDE.md); der aktuelle Stand aller bekannten Risiken, offenen Punkte und der Technical-Debt-Liste in [`docs/MusicBot_ENGINEERING_BASELINE_v8.md`](docs/MusicBot_ENGINEERING_BASELINE_v8.md) (löst [`docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md`](docs/archive/MusicBot_ENGINEERING_BASELINE_v7.md), eingefrorener Stand vom 2026-09-01 mit 1673 passed/0 failed, als aktuellen Referenzpunkt ab; ältere Baselines bleiben unter [`docs/archive/`](docs/archive/) unverändert bestehen). Ältere Architektur-Analysen (ARCH-xxx/POST-ARCH-xxx) liegen vollständig erhalten unter [`docs/archive/`](docs/archive/), siehe [`docs/INDEX.md`](docs/INDEX.md).
