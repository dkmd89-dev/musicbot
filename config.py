# config.py - SICHERE VERSION MIT .ENV SUPPORT
# -*- coding: utf-8 -*-
"""
⚙️ Konfigurationsklasse für den YT Music Bot
Lädt sensible Daten aus .env oder Umgebungsvariablen
"""

import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

# =============================================================================
# .ENV LADEN
# =============================================================================

# .env Datei aus verschiedenen möglichen Pfaden laden
env_paths = [
    Path(__file__).parent / ".env",
    Path.cwd() / ".env",
    Path("/home/robin/bot/.env"),
]

env_loaded = False
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        env_loaded = True
        print(f"✅ .env geladen von: {env_path}")
        break

if not env_loaded:
    print("⚠️ Keine .env Datei gefunden. Verwende Umgebungsvariablen.")
    load_dotenv()  # Lädt aus Umgebungsvariablen

# Optional: lyricsgenius und musicbrainzngs importieren
try:
    import lyricsgenius

    GENIUS_AVAILABLE = True
except ImportError:
    GENIUS_AVAILABLE = False
    print("⚠️ lyricsgenius nicht installiert")

try:
    import musicbrainzngs

    MUSICBRAINZ_AVAILABLE = True
except ImportError:
    MUSICBRAINZ_AVAILABLE = False
    print("⚠️ musicbrainzngs nicht installiert")


class Config:
    """
    🔧 Vollständig integrierte Konfiguration für Enhanced Music Bot

    Sensible Daten werden NIE im Code gespeichert, sondern:
    1. Aus .env Datei geladen (Entwicklung)
    2. Aus Umgebungsvariablen geladen (Produktion/Systemd)

    PODCAST_DIR:
      Podcasts werden NICHT unter LIBRARY_DIR/Podcast abgelegt,
      sondern in einem eigenen Root-Verzeichnis (PODCAST_DIR).
      Standard: /mnt/musik_bilder/Podcast
      Überschreibbar per .env:  PODCAST_DIR=/dein/wunschpfad
    """

    # =========================================================================
    # BASIS-KONFIGURATION (Pfade)
    # =========================================================================

    BASE_DIR = Path("/home/robin/bot")

    # === DIRECTORY STRUCTURE ===
    LIBRARY_DIR = Path("/mnt/4tb/library")
    PODCAST_DIR = Path("/mnt/musik_bilder/Podcast")
    DOWNLOAD_DIR = BASE_DIR / "import" / "downloads"
    TEMP_DIR = BASE_DIR / "import" / "temp"
    PROCESSED_DIR = BASE_DIR / "import" / "prozess"
    FAIL_DIR = BASE_DIR / "import" / "fail"
    ARCHIVE_DIR = BASE_DIR / "import" / "archiv"

    # === CACHE STRUCTURE ===
    DATA_DIR = BASE_DIR / "cache" / "data"
    ESCAPE_DIR = BASE_DIR / "cache" / "escaped_scripts"
    METADATA_CACHE_DIR = BASE_DIR / "cache" / "metadata_cache"
    DUPLICATE_CACHE_DIR = BASE_DIR / "cache" / "duplicate_cache"
    LYRICS_CACHE_DIR = BASE_DIR / "cache" / "lyrics_cache"  # ← NEU: Lyrics-Cache

    # === LOG STRUCTURE ===
    LOG_DIR = BASE_DIR / "logs"
    LOG_FILE = BASE_DIR / "logs" / "bot.log"

    # === MAPPING & HISTORY ===
    ARTIST_OVERRIDE_FILE = BASE_DIR / "mapping" / "artist_overrides.json"
    ARTIST_OVERRIDE_EXPANDED_FILE = (
        BASE_DIR / "mapping" / "artist_overrides_expanded.json"
    )
    GENRE_MAPPING_DIR = BASE_DIR / "mapping"
    PLAY_HISTORY_FILE = BASE_DIR / "history" / "user_histories"
    STATS_DIR = BASE_DIR / "history" / "stats_charts"

    # === SPOTIFY ===
    SPOTIFY_DOWNLOAD_DIR = BASE_DIR / "import" / "spotify"

    # === BACKUP ===
    BACKUP_BOT_SOURCE_DIR = BASE_DIR
    BACKUP_LIBRARY_SOURCE_DIR = Path("/mnt/4tb/library")
    BACKUP_DEST_DIR = Path("/mnt/backup/Musikserver")
    BACKUP_MAX_KEEP = 5
    BACKUP_EXCLUDE_PATTERNS = [
        "library",
        "__pycache__",
        ".git",
        "*.pyc",
        "import/downloads",
        "import/temp",
        "cache",
    ]

    # =========================================================================
    # SENSIBLE DATEN (aus .env / Umgebungsvariablen)
    # =========================================================================

    @property
    def BOT_TOKEN(self) -> str:
        """Telegram Bot Token (SENSIBEL)"""
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError(
                "❌ BOT_TOKEN nicht in .env oder Umgebungsvariablen gefunden!"
            )
        return token

    @property
    def OWNER_USER_ID(self) -> int:
        """Owner User ID (SENSIBEL)"""
        owner_id = os.getenv("OWNER_USER_ID")
        if not owner_id:
            raise ValueError("❌ OWNER_USER_ID nicht in .env gefunden!")
        return int(owner_id)

    @property
    def ADMIN_USER_IDS(self) -> List[int]:
        """Admin User IDs (SENSIBEL)"""
        admin_ids = os.getenv("ADMIN_USER_IDS", "")
        if admin_ids:
            return [int(x.strip()) for x in admin_ids.split(",") if x.strip()]
        return [self.OWNER_USER_ID]

    @property
    def ADMIN_CHAT_ID(self) -> str:
        """Admin Chat ID (SENSIBEL)"""
        return os.getenv("ADMIN_CHAT_ID", str(self.OWNER_USER_ID))

    @property
    def SPOTIFY_CLIENT_ID(self) -> str:
        """Spotify Client ID (SENSIBEL)"""
        return os.getenv("SPOTIFY_CLIENT_ID", "")

    @property
    def SPOTIFY_CLIENT_SECRET(self) -> str:
        """Spotify Client Secret (SENSIBEL)"""
        return os.getenv("SPOTIFY_CLIENT_SECRET", "")

    @property
    def GENIUS_ACCESS_TOKEN(self) -> str:
        """Genius Access Token (SENSIBEL)"""
        return os.getenv("GENIUS_ACCESS_TOKEN", "")

    # Alias für Kompatibilität
    @property
    def GENIUS_API_TOKEN(self) -> str:
        return self.GENIUS_ACCESS_TOKEN

    @property
    def LASTFM_API_KEY(self) -> str:
        """Last.fm API Key (SENSIBEL)"""
        return os.getenv("LASTFM_API_KEY", "")

    @property
    def LASTFM_API_SECRET(self) -> str:
        """Last.fm API Secret (SENSIBEL)"""
        return os.getenv("LASTFM_API_SECRET", "")

    @property
    def FANART_API_KEY(self) -> str:
        """Fanart.tv API Key für Cover-Art (SENSIBEL)"""
        return os.getenv("FANART_API_KEY", "")

    @property
    def NAVIDROME_URL(self) -> str:
        """Navidrome URL"""
        return os.getenv("NAVIDROME_URL", "")

    @property
    def NAVIDROME_USER(self) -> str:
        """Navidrome Username"""
        return os.getenv("NAVIDROME_USER", "")

    @property
    def NAVIDROME_PASS(self) -> str:
        """Navidrome Password (SENSIBEL)"""
        return os.getenv("NAVIDROME_PASS", "")

    @property
    def NAVIDROME_CONTAINER_NAME(self) -> str:
        """Navidrome Docker Container Name"""
        return os.getenv("NAVIDROME_CONTAINER_NAME", "navidrome")

    @property
    def PODCAST_INDEX_API_KEY(self) -> str:
        """Podcast Index API Key"""
        return os.getenv("PODCAST_INDEX_API_KEY", "")

    @property
    def PODCAST_INDEX_API_SECRET(self) -> str:
        """Podcast Index API Secret"""
        return os.getenv("PODCAST_INDEX_API_SECRET", "")

    # ─────────────────────────────────────────────────────────────────────────
    # PODCAST_DIR als Property (liest .env zur Laufzeit, Vorrang vor Klassenwert)
    # ─────────────────────────────────────────────────────────────────────────
    @property
    def PODCAST_DIR_RESOLVED(self) -> Path:
        """
        Gibt das konfigurierte Podcast-Verzeichnis zurück.

        Priorität:
          1. Umgebungsvariable / .env:  PODCAST_DIR=/dein/pfad
          2. Klassenwert:               Config.PODCAST_DIR  (Fallback)

        Wird von FilenameFixerTool.__init__() genutzt, um self._podcast_dir zu setzen.
        Das Verzeichnis wird automatisch erstellt, falls es nicht existiert.

        Beispiel .env Eintrag:
            PODCAST_DIR=/mnt/nas/Podcasts
        """
        env_val = os.getenv("PODCAST_DIR", "")
        if env_val:
            return Path(env_val)
        return Path(self.__class__.PODCAST_DIR)

    # ─────────────────────────────────────────────────────────────────────────
    # LYRICS_CACHE_DIR als Property (liest .env zur Laufzeit)
    # ─────────────────────────────────────────────────────────────────────────
    @property
    def LYRICS_CACHE_DIR_RESOLVED(self) -> Path:
        """
        Gibt das konfigurierte Lyrics-Cache-Verzeichnis zurück.

        Priorität:
          1. Umgebungsvariable / .env:  LYRICS_CACHE_DIR=/dein/pfad
          2. Klassenwert:               Config.LYRICS_CACHE_DIR  (Fallback)

        Beispiel .env Eintrag:
            LYRICS_CACHE_DIR=/home/robin/bot/cache/lyrics_cache
        """
        env_val = os.getenv("LYRICS_CACHE_DIR", "")
        if env_val:
            return Path(env_val)
        return Path(self.__class__.LYRICS_CACHE_DIR)

    # =========================================================================
    # NICHT-SENSIBLE KONFIGURATION (aus .env oder Defaults)
    # =========================================================================

    @property
    def LOG_LEVEL(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")

    @property
    def DEBUG_MODE(self) -> bool:
        return os.getenv("DEBUG_MODE", "false").lower() == "true"

    @property
    def VERSION(self) -> str:
        return os.getenv("VERSION", "2.0")

    @property
    def DEFAULT_USER_ROLE(self) -> str:
        return os.getenv("DEFAULT_USER_ROLE", "user")

    @property
    def SESSION_TIMEOUT(self) -> int:
        return int(os.getenv("SESSION_TIMEOUT", "300"))

    @property
    def MAX_CONCURRENT_SESSIONS(self) -> int:
        return int(os.getenv("MAX_CONCURRENT_SESSIONS", "100"))

    @property
    def AUDIO_FORMAT(self) -> str:
        return os.getenv("AUDIO_FORMAT", "m4a")

    @property
    def AUDIO_QUALITY(self) -> str:
        return os.getenv("AUDIO_QUALITY", "192")

    # =========================================================================
    # FESTE KONFIGURATION (nicht aus .env)
    # =========================================================================

    # Bot-Status
    TELEGRAM_ENABLED = True
    MENU_SYSTEM_ENABLED = True
    LEGACY_HANDLER_SUPPORT = True

    # YouTube-DLP
    COOKIES_FILE = BASE_DIR / "cookies.txt"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # Enhanced Features
    ENHANCED_METADATA_PROCESSING = True
    ARTIST_MAP_FALLBACK_ENABLED = True
    TITLE_CLEANING_AGGRESSIVE = True
    METADATA_CACHE_ENABLED = True
    METADATA_CACHE_TTL = 86400 * 30
    METADATA_CACHE_MAX_ENTRIES = 10000
    ARTIST_NORMALIZATION_ENABLED = True
    ARTIST_COLLABORATION_DETECTION = True
    ARTIST_OVERRIDE_AUTO_UPDATE = True
    ARTIST_LIBRARY_SCAN = True
    GENRE_MAPPING_ENABLED = True
    GENRE_AUTO_ASSIGNMENT = True
    GENRE_CONFIDENCE_THRESHOLD = 0.7
    GENRE_FALLBACK_ENABLED = True
    GENRE_FUZZY_MATCHING = True
    GENRE_FUZZY_THRESHOLD = 80

    # Lyrics
    LYRICS_ENABLED = True
    LYRICS_CACHE_ENABLED = True
    LYRICS_EMBED_IN_FILES = True
    LYRICS_FALLBACK_SOURCES = ["genius", "azlyrics", "musixmatch"]
    LYRICS_CACHE_TTL = 86400 * 90  # ← NEU: 90 Tage Cache-Gültigkeit

    # Duplicate Handling
    DUPLICATE_DETECTION_ENABLED = True
    DUPLICATE_CACHE_ENABLED = True
    DUPLICATE_SIMILARITY_THRESHOLD = 0.85
    DUPLICATE_AUTO_SKIP = False
    CONTENT_HASH_ENABLED = True
    FINGERPRINT_MATCHING = True
    FUZZY_TITLE_MATCHING = True
    FUZZY_ARTIST_MATCHING = True

    # Limits
    MAX_DURATION = 600
    MAX_PLAYLIST_ITEMS = 50
    MAX_FILENAME_LENGTH = 150
    SUPPORTED_FORMATS = (".mp3", ".m4a", ".ogg", ".opus")
    PLAYLIST_AS_SINGLE_THRESHOLD = 2
    PROCESSING_PARALLEL_TRACKS = 3
    PROCESSING_TIMEOUT = 30

    # File Processing
    EMBED_THUMBNAILS = True
    EXTRACT_METADATA = True
    NORMALIZE_FILENAMES = True
    AUTO_SORT_AFTER_TAGGING = True
    SINGLE_FILENAME_TEMPLATE = "{artist} - {title}.{ext}"
    ALBUM_FILENAME_TEMPLATE = "{track_num:02d} - {title}.{ext}"
    PLAYLIST_FILENAME_TEMPLATE = "{track_num:02d} - {artist} - {title}.{ext}"
    SINGLE_ALBUM_TEMPLATE = "{title}"
    ARTIST_DIR_TEMPLATE = "{artist}"
    ALBUM_DIR_TEMPLATE = "{year} - {album}"
    SINGLE_DIR_TEMPLATE = "Singles"
    DEFAULT_ALBUM_NAME = "Singles"

    # Download Behavior
    MAX_CONCURRENT_DOWNLOADS = 3
    DOWNLOAD_RETRY_COUNT = 3
    DOWNLOAD_RETRY_DELAY = 2
    DOWNLOAD_TIMEOUT = 300
    PROGRESS_UPDATE_INTERVAL = 2
    PROGRESS_DETAILED_LOGGING = True

    # Advanced Features
    PLAYLIST_ANALYSIS_ENHANCED = True
    DOMINANT_ARTIST_DETECTION = True
    YEAR_CONSISTENCY_ANALYSIS = True
    COLLABORATION_PARSING = True
    YOUTUBE_TITLE_PARSING = True
    YOUTUBE_PARSER_ENABLED = True
    YOUTUBE_PARSER_PRIORITY = True

    # Spotify
    SPOTIFY_ENABLED = True

    # Navidrome
    NAVIDROME_SCAN_TIMEOUT = 45
    NAVIDROME_SCAN_COMMAND = f"docker exec navidrome /app/navidrome scan --full"

    # Last.fm
    LASTFM_ENABLED = True
    LASTFM_CACHE_TTL = 3600
    LASTFM_TIMEOUT = 10

    # Cover Art
    MAX_COVER_SIZE = 5 * 1024 * 1024
    COVER_DOWNLOAD_TIMEOUT = 10
    COVER_MIN_RESOLUTION = (300, 300)
    COVER_MAX_RESOLUTION = (1000, 1000)

    # Genius Config
    GENIUS_CONFIG = {
        "fetch_cover_art": True,
        "fetch_lyrics": True,
        "auto_match_threshold": 0.6,
        "rename_files": True,
        "rename_pattern": "{year} - {title}",
        "max_results": 5,
        "retry_attempts": 3,
        "max_retries": 3,
        "timeout": 10,
        "skip_non_songs": True,
        "remove_section_headers": True,
    }

    GENIUS_TIMEOUT = 10
    GENIUS_ENABLED = True

    # MusicBrainz
    MUSICBRAINZ_CONFIG = {
        "user_agent": "yt_music_bot",
        "version": "1.0",
        "contact": "robinmarina070721@gmail.com",
        "title_weight": 0.7,
        "artist_weight": 0.3,
    }

    MUSICBRAINZ_HOSTNAME = "dkmd"
    MUSICBRAINZ_TIMEOUT = 30
    MUSICBRAINZ_ENABLED = True
    MUSICBRAINZ_RETRIES = 4
    MUSICBRAINZ_TITLE_WEIGHT = 0.5
    MUSICBRAINZ_ARTIST_WEIGHT = 0.5
    MUSICBRAINZ_MIN_SIMILARITY = 0.7

    # Interactive Tagging
    INTERACTIVE_TAGGING = {
        "enable_artist_selection": False,
        "enable_album_mode": "auto",
    }

    # Special Channels
    # Hinweis: Neue Kanäle bitte in mapping/special_channel.yaml eintragen –
    # die YAML-Datei hat Vorrang und erfordert keinen Bot-Neustart.
    # Diese Config-Liste dient als Fallback, falls die YAML-Datei fehlt.
    SPECIAL_CHANNELS = {
        "Compilations": [
            "Deep Territory",
            "FitBeatBeats",
            "thesoundofmusique",
            "MrRevillz",
            "Highontracks",
        ],
    }

    # Metadata Defaults
    METADATA_DEFAULTS = {
        "genre": None,
        "album": "Single",
        "album_artist": "Artists",
        "year": str(datetime.now().year),
        "track_number": "01",
    }

    METADATA_CONFIG = {
        "sources": {
            "youtube": {"enabled": True, "priority": 3},
            "musicbrainz": {"enabled": True, "priority": 1},
            "genius": {"enabled": True, "priority": 2},
            "lastfm": {"enabled": True, "priority": 4},
        },
        "fields": {
            "artist": {"required": True, "normalize": True},
            "title": {"required": True, "normalize": True},
            "album": {"required": False, "default": "Single"},
            "album_artist": {"required": False, "use_artist_if_missing": True},
            "genre": {"required": False, "multiple": True},
            "year": {"required": False, "format": "%Y"},
            "track_number": {"required": False, "default": "01"},
            "total_tracks": {"required": False},
            "disc_number": {"required": False},
            "total_discs": {"required": False},
            "composer": {"required": False},
            "lyrics": {"required": False},
            "album_type": {"required": False, "default": "single"},
            "is_single": {"required": False, "default": True},
        },
    }

    # YT-DLP Options
    @property
    def YTDL_BASE_OPTIONS(self) -> Dict[str, Any]:
        return {
            "format": f"bestaudio[ext={self.AUDIO_FORMAT}]/bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.AUDIO_FORMAT,
                    "preferredquality": str(self.AUDIO_QUALITY),
                }
            ],
            "outtmpl": str(self.DOWNLOAD_DIR / "%(title)s.%(ext)s"),
            "writethumbnail": True,
            "max_duration": self.MAX_DURATION,
            "ignoreerrors": False,
            "socket_timeout": 30,
            "retries": self.DOWNLOAD_RETRY_COUNT,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "skip": ["sabr"],
                }
            },
            "audio_multistreams": True,
            "allow_multiple_audio_streams": True,
            "format_sort": [
                f"ext:{self.AUDIO_FORMAT}",
                f"acodec:{self.AUDIO_FORMAT}",
                "abr",
            ],
            "no_resize_buffer": True,
            "http_chunk_size": 1048576,
        }

    # Play History
    PLAY_HISTORY_RETENTION_DAYS = 380
    PLAY_HISTORY_AUTOSAVE_INTERVAL_MIN = 3

    # =========================================================================
    # HILFSMETHODEN
    # =========================================================================

    @classmethod
    def mask_sensitive(cls, value: str, visible_chars: int = 4) -> str:
        """Maskiert sensible Daten für Logging/Anzeige"""
        if not value or len(value) <= visible_chars:
            return "***"
        return "*" * (len(value) - visible_chars) + value[-visible_chars:]

    @classmethod
    def validate_config(cls) -> Dict[str, Any]:
        """Validiert die Konfiguration"""
        validation_results = {"valid": True, "errors": [], "warnings": [], "info": []}

        # Prüfe BOT_TOKEN
        try:
            token = cls().BOT_TOKEN
            if token:
                validation_results["info"].append(
                    f"BOT_TOKEN: {cls.mask_sensitive(token)}"
                )
        except ValueError as e:
            validation_results["errors"].append(str(e))
            validation_results["valid"] = False

        # Prüfe OWNER_USER_ID
        try:
            owner_id = cls().OWNER_USER_ID
            validation_results["info"].append(f"OWNER_USER_ID: {owner_id}")
        except ValueError as e:
            validation_results["errors"].append(str(e))
            validation_results["valid"] = False

        # Erstelle Verzeichnisse (inkl. PODCAST_DIR und LYRICS_CACHE_DIR)
        _inst = cls()
        required_dirs = [
            cls.LIBRARY_DIR,
            cls.DOWNLOAD_DIR,
            cls.TEMP_DIR,
            cls.LOG_DIR,
            _inst.PODCAST_DIR_RESOLVED,  # ← Podcast-Root
            _inst.LYRICS_CACHE_DIR_RESOLVED,  # ← NEU: Lyrics-Cache
        ]
        for directory in required_dirs:
            if not directory.exists():
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    validation_results["info"].append(
                        f"Verzeichnis erstellt: {directory}"
                    )
                except Exception as e:
                    validation_results["errors"].append(f"Fehler bei {directory}: {e}")
                    validation_results["valid"] = False

        return validation_results

    @classmethod
    def get_feature_status(cls) -> Dict[str, bool]:
        """Gibt Status aller Features zurück"""
        return {
            "enhanced_metadata_processing": cls.ENHANCED_METADATA_PROCESSING,
            "artist_map_fallback": cls.ARTIST_MAP_FALLBACK_ENABLED,
            "metadata_cache": cls.METADATA_CACHE_ENABLED,
            "lyrics_integration": cls.LYRICS_ENABLED,
            "lyrics_cache": cls.LYRICS_CACHE_ENABLED,  # ← NEU
            "duplicate_detection": cls.DUPLICATE_DETECTION_ENABLED,
            "youtube_parser": cls.YOUTUBE_PARSER_ENABLED,
            "genre_mapping": cls.GENRE_MAPPING_ENABLED,
            "artist_normalization": cls.ARTIST_NORMALIZATION_ENABLED,
            "playlist_analysis": cls.PLAYLIST_ANALYSIS_ENHANCED,
            "spotify_enabled": cls.SPOTIFY_ENABLED,
            "navidrome_enabled": bool(cls().NAVIDROME_URL),
        }

    @classmethod
    def print_safe_config(cls):
        """Gibt Konfiguration mit maskierten sensiblen Daten aus"""
        print("\n" + "=" * 60)
        print("⚙️ KONFIGURATION (sensible Daten maskiert)")
        print("=" * 60)

        try:
            config = cls()
            print(f"BOT_TOKEN:              {cls.mask_sensitive(config.BOT_TOKEN)}")
            print(f"OWNER_USER_ID:          {config.OWNER_USER_ID}")
            print(f"ADMIN_USER_IDS:         {config.ADMIN_USER_IDS}")
            print(
                f"SPOTIFY_CLIENT_ID:      {cls.mask_sensitive(config.SPOTIFY_CLIENT_ID) if config.SPOTIFY_CLIENT_ID else 'nicht gesetzt'}"
            )
            print(
                f"GENIUS_TOKEN:           {cls.mask_sensitive(config.GENIUS_ACCESS_TOKEN) if config.GENIUS_ACCESS_TOKEN else 'nicht gesetzt'}"
            )
            print(
                f"LASTFM_API_KEY:         {cls.mask_sensitive(config.LASTFM_API_KEY) if config.LASTFM_API_KEY else 'nicht gesetzt'}"
            )
            print(f"NAVIDROME_URL:          {config.NAVIDROME_URL or 'nicht gesetzt'}")
            print(f"LOG_LEVEL:              {config.LOG_LEVEL}")
            print(f"DEBUG_MODE:             {config.DEBUG_MODE}")
            print(f"LIBRARY_DIR:            {cls.LIBRARY_DIR}")
            print(f"PODCAST_DIR:            {config.PODCAST_DIR_RESOLVED}")
            print(
                f"LYRICS_CACHE_DIR:       {config.LYRICS_CACHE_DIR_RESOLVED}"
            )  # ← NEU
            print(f"DOWNLOAD_DIR:           {cls.DOWNLOAD_DIR}")
        except Exception as e:
            print(f"❌ Fehler: {e}")

        print("=" * 60)

    @classmethod
    def create_directory_structure(cls) -> bool:
        """Erstellt die gesamte Verzeichnisstruktur"""
        _inst = cls()
        directories = [
            cls.LIBRARY_DIR,
            _inst.PODCAST_DIR_RESOLVED,
            _inst.LYRICS_CACHE_DIR_RESOLVED,  # ← NEU: Lyrics-Cache anlegen
            cls.DOWNLOAD_DIR,
            cls.TEMP_DIR,
            cls.LOG_DIR,
            cls.METADATA_CACHE_DIR,
            cls.DUPLICATE_CACHE_DIR,
            cls.GENRE_MAPPING_DIR,
            cls.PROCESSED_DIR,
            cls.FAIL_DIR,
            cls.DATA_DIR,
            cls.ESCAPE_DIR,
            cls.ARCHIVE_DIR,
            cls.STATS_DIR,
            cls.SPOTIFY_DOWNLOAD_DIR,
        ]

        success = True
        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"❌ Fehler beim Erstellen von {directory}: {e}")
                success = False

        return success

    @classmethod
    def init(cls):
        """Initialisiert die Konfiguration"""
        # Verzeichnisse erstellen (inkl. PODCAST_DIR und LYRICS_CACHE_DIR)
        cls.create_directory_structure()

        # Genius Client initialisieren (falls verfügbar)
        if GENIUS_AVAILABLE:
            try:
                config = cls()
                if config.GENIUS_ACCESS_TOKEN:
                    cls.genius = lyricsgenius.Genius(
                        config.GENIUS_ACCESS_TOKEN,
                        remove_section_headers=cls.GENIUS_CONFIG[
                            "remove_section_headers"
                        ],
                        skip_non_songs=cls.GENIUS_CONFIG["skip_non_songs"],
                        timeout=cls.GENIUS_CONFIG["timeout"],
                    )
            except Exception as e:
                print(f"⚠️ Genius-Initialisierung fehlgeschlagen: {e}")

        # MusicBrainz User Agent setzen (falls verfügbar)
        if MUSICBRAINZ_AVAILABLE:
            try:
                musicbrainzngs.set_useragent(
                    "YT-Music-Downloader", "1.0", "robinmarina070721@gmail.com"
                )
            except Exception as e:
                print(f"⚠️ MusicBrainz-Initialisierung fehlgeschlagen: {e}")

        # Warnungen reduzieren
        logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("matplotlib").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("telegram.ext").setLevel(logging.WARNING)
        logging.getLogger("aiohttp").setLevel(logging.WARNING)


# =============================================================================
# SINGLETON-INSTANZ
# =============================================================================

_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Gibt die globale Config-Instanz zurück"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


# =============================================================================
# INITIALISIERUNG BEIM IMPORT
# =============================================================================

Config.init()


# =============================================================================
# TEST (bei direkter Ausführung)
# =============================================================================

if __name__ == "__main__":
    print("🔧 Teste Config mit .env Support...\n")

    # Validierung durchführen
    validation = Config.validate_config()

    if validation["errors"]:
        print("❌ FEHLER:")
        for error in validation["errors"]:
            print(f"   • {error}")

    if validation["warnings"]:
        print("\n⚠️ WARNUNGEN:")
        for warning in validation["warnings"]:
            print(f"   • {warning}")

    if validation["info"]:
        print("\nℹ️ INFO:")
        for info in validation["info"]:
            print(f"   • {info}")

    if validation["valid"]:
        print("\n✅ Konfiguration ist gültig!")
        Config.print_safe_config()

        print("\n📊 FEATURE-STATUS:")
        features = Config.get_feature_status()
        for feature, enabled in features.items():
            status = "✅" if enabled else "❌"
            print(f"   {status} {feature}")

        # Podcast- und Lyrics-Cache-Verzeichnis anzeigen
        cfg = Config()
        print(f"\n🎙️ PODCAST_DIR (aktiv): {cfg.PODCAST_DIR_RESOLVED}")
        print(f"   (Überschreibbar mit: PODCAST_DIR=/dein/pfad in .env)")
        print(f"\n📜 LYRICS_CACHE_DIR (aktiv): {cfg.LYRICS_CACHE_DIR_RESOLVED}")
        print(f"   (Überschreibbar mit: LYRICS_CACHE_DIR=/dein/pfad in .env)")
    else:
        print("\n❌ Konfiguration ist ungültig!")
        sys.exit(1)
