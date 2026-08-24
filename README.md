# MusicBot

Privat entwickelter Telegram-Bot für Musik-/Podcast-Download (YouTube & Spotify), automatische Metadaten-Anreicherung (Artist, Genre, Cover, Lyrics), Library-Organisation und Steuerung eines [Navidrome](https://www.navidrome.org/)-Servers.

Historisch organisch gewachsenes Hobbyprojekt — siehe [`CLAUDE.md`](CLAUDE.md) für die Engineering-Leitlinien und [`docs/MusicBot_ENGINEERING_BASELINE.md`](docs/MusicBot_ENGINEERING_BASELINE.md) für den aktuellen technischen Status (Risiken, behobene Bugs, Testabdeckung).

---

## Was der Bot macht

- Nimmt YouTube- und Spotify-Links per Telegram entgegen (auch Playlists, Podcasts/Episodes)
- Lädt Audio via [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) herunter (Spotify-Links werden dafür auf YouTube gesucht, da ohne Premium/API-Key kein direkter Spotify-Download möglich ist)
- Reichert Metadaten an: Artist-Normalisierung, Genre-Erkennung (MusicBrainz/Last.fm-Tags, Mapping-Regeln, Fuzzy-Matching), Lyrics (Genius), Cover-Art (Cover Art Archive, Fanart.tv, Apple Music, Deezer, Last.fm, YouTube-Thumbnail als Fallback-Kette)
- Erkennt Duplikate über mehrere Ebenen (URL, YouTube-ID, Artist+Titel, Library-Abgleich)
- Organisiert die fertige Datei in der Musik-Library (Dateiname, Verzeichnisstruktur, ID3/MP4-Tags)
- Steuert einen laufenden Navidrome-Server (Scan anstoßen, Status abfragen, Bibliothek durchsuchen) über die Subsonic-API
- Bietet ein Telegram-Menüsystem für Statistiken, Nutzerverwaltung, Logs und Backups (rollenbasiert: Owner/Admin/User)

## Architektur (vereinfacht)

```text
Telegram
   ↓
ExtendedBot (bot.py)
   ↓
RichMenuHandler
   ↓
DownloadHandler
   ├── YouTube (yt-dlp)
   └── Spotify (SpotifyDownloader → YouTube-Suche / RSS-Feed für Podcasts)
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
| `klassen/` | `download_handler.py` — zentraler Download-Orchestrator (Dispatch YouTube/Spotify), einziges verbliebenes Modul in diesem Verzeichnis |
| `services/downloader/` | Download-Pipeline: `spotify_downloader.py`, `downloader.py`, `playlist_processor.py`, `download_utils.py`, `download_result_reporter.py`, `download_artifact_cleanup.py`, `progress_tracker.py`, `errors.py`, `metadata_result_translator.py`, sowie `download/` mit den ausgelagerten Orchestrierungs-Modulen (Cache/Jahr/Channel/Executor/Formatters) |
| `services/metadata/` | Metadaten-Pipeline (ARCH-010): `enhanced_metadata_processor.py` als Facade, sowie die Unterprozessoren `album_processor.py`, `artist_processor.py`, `auto_learn.py`, `cache.py`, `cover_processor.py`, `genre_processor.py`, `lyrics_processor.py`, `tag_writer.py`, `title_cleaner.py`, `models.py` |
| `services/clients/` | Reine externe Integrationsadapter (keine Telegram-Präsentation, keine Fachlogik): `genius_client.py`, `lastfm_client.py`, `musicbrainz_client.py`, `navidrome_api.py` |
| `services/` (übrige Dateien) | `statistik_service.py` (dünne Fassade) + `services/statistik/` (`play_history_repository.py`, `play_history_poller.py`, `statistics_calculator.py`, `chart_renderer.py`) |
| `handlers/` | Telegram-Handler: Menüsystem (`handlers/menu/`), Admin-Funktionen (`handlers/admin/`), Navidrome-Menü, Statistik, Fehlerbehandlung |
| `utils/` | Wiederverwendbare Bausteine: `genre_map.py`, `artist_map.py`, `filenamefixer.py`, `helpers.py`, Caches (`lyrics_cache.py` u. a.), Singleton-Basisklasse, sowie lokale technische Runner ohne Telegram-/API-Kopplung (`navidrome_scan_trigger.py`, `audio_enhancer.py`) |
| `mapping/` | YAML-/JSON-Dateien mit Fachlogik (Genre-/Artist-Regeln) — **keine belanglose Konfiguration**, siehe unten |
| `tests/` | ~360 Tests (pytest) — Characterization-Tests für die Produktionsklassen, siehe [`docs/MusicBot_ENGINEERING_BASELINE.md`](docs/MusicBot_ENGINEERING_BASELINE.md) |
| `docs/` | Engineering-Baseline (Risiko-Tabelle, Testabdeckung, Roadmap) |

## Setup

**Voraussetzungen:** Python 3.12, `ffmpeg` (Systempaket, für Audio-Konvertierung), ein laufender Navidrome-Server (optional, aber für die Navidrome-Funktionen nötig).

```bash
pip install -r requirements.txt
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

SPOTIFY_CLIENT_ID=            # optional, nur für Spotify-Metadaten-API-Pfad
SPOTIFY_CLIENT_SECRET=
GENIUS_ACCESS_TOKEN=          # optional, für Lyrics
LASTFM_API_KEY=               # optional, für Genre-Tags/Cover-Fallback
LASTFM_API_SECRET=
FANART_API_KEY=               # optional, für Cover-Fallback
PODCAST_INDEX_API_KEY=        # optional
PODCAST_INDEX_API_SECRET=

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

Stand bei letzter Prüfung: 359 Tests, davon 15 bekannte, vorbestehende Fehlschläge (u. a. weil `pytest-asyncio` in dieser Umgebung nicht installiert ist — `@pytest.mark.asyncio`-Tests in `tests/test_suite.py` laufen dadurch nicht). Details siehe [`docs/MusicBot_ENGINEERING_BASELINE.md`](docs/MusicBot_ENGINEERING_BASELINE.md).

## Mapping-Dateien

Die YAML-/JSON-Dateien in `mapping/` (Genre-Aliase, Genre-Hierarchie, Genre-Overrides, Artist-Genre-Zuordnungen, Artist-Overrides, Podcast-RSS-Feeds, Special-Channels) steuern reales fachliches Verhalten — welches Genre ein Track bekommt, wie ein Artist-Name normalisiert wird, ob ein Kanal als Podcast erkannt wird. Änderungen daran werden wie Code-Änderungen behandelt: mit konkreten Vorher/Nachher-Beispielen und Tests, nicht als Bulk-Edit. Details siehe `CLAUDE.md`, Abschnitt 10.

## Entwicklung

Dieses Projekt wird nicht neu geschrieben, sondern kontrolliert weiterentwickelt: bestehendes Verhalten zuerst verstehen und mit Characterization-Tests absichern, dann verbessern. Die verbindlichen Arbeitsregeln stehen in [`CLAUDE.md`](CLAUDE.md); der aktuelle Stand aller bekannten Risiken, behobenen Bugs und offenen Punkte in [`docs/MusicBot_ENGINEERING_BASELINE.md`](docs/MusicBot_ENGINEERING_BASELINE.md).
