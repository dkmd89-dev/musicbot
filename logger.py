# /yt_music_bot/logger.py

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import json
from logging.handlers import RotatingFileHandler
import colorama
from colorama import Fore, Back, Style

# Initialisiere Colorama für Cross-Platform Farb-Support
colorama.init(autoreset=True)

# Globaler Logger-Status
_loggers_initialized = False
_module_loggers: Dict[str, logging.Logger] = {}
_log_config: Dict[str, Any] = {}

# Modul-spezifische Emoji und Farb-Zuordnungen
MODULE_EMOJIS = {
    # Core Handler
    "DownloadHandler": "📤",
    "PlaylistProcessor": "📋",
    "MetadataProcessor": "📝",
    "EnhancedProcessor": "🚀",
    # Downloader Components
    "YoutubeDownloader": "⬇️",
    "download_utils": "🔧",
    "progress_tracker": "⏳",
    # Metadata & Utils
    "statistik": "📊",
    "file_utils": "📂",
    "filenamefixer": "🛠️",
    # External APIs
    "musicbrainz_client": "🎵",
    "genius_client": "🧠",
    "lastfm_client": "📻",
    # Caching & Storage
    "metadata_cache": "💾",
    "lyrics_cache": "📜",
    # Bot Interface
    "telegram_bot": "🤖",
    "CookieHandler": "🍪",
    "DuplicateHandler": "🔍",
    # Utils
    "artist_map": "👤",
    "genre_map": "🎶",
    "yt_utils": "📺",
    "duplicate_checker": "🔍",
    # Enhanced Features
    "error_handler": "⚠️",
    "statistics": "📊",
    "telegram_bot": "🤖",
    "config": "⚙️",
    "test_handler": "🧪",
    "main": "🎯",
    "metadata_utils": "📝",
}

MODULE_COLORS = {
    "DownloadHandler": Fore.CYAN,
    "EnhancedProcessor": Fore.GREEN,
    "download_utils": Fore.BLUE,
    "artist_map": Fore.MAGENTA,
    "youtube_parser": Fore.YELLOW,
    "genre_map": Fore.RED,
    "genius_client": Fore.LIGHTBLUE_EX,
    "metadata_cache": Fore.LIGHTGREEN_EX,
    "duplicate_handler": Fore.LIGHTYELLOW_EX,
    "file_utils": Fore.LIGHTCYAN_EX,
    "filenamefixer": Fore.LIGHTMAGENTA_EX,
    "playlist_processor": Fore.LIGHTRED_EX,
    "progress_tracker": Fore.WHITE,
    "YoutubeDownloader": Fore.BLUE,
    "yt_utils": Fore.YELLOW,
    "error_handler": Fore.RED,
    "statistics": Fore.GREEN,
    "telegram_bot": Fore.CYAN,
    "config": Fore.MAGENTA,
    "main": Fore.WHITE,
}

LOG_LEVEL_EMOJIS = {
    "DEBUG": "🔍",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🚨",
}

LOG_LEVEL_COLORS = {
    "DEBUG": Fore.LIGHTBLACK_EX,
    "INFO": Fore.WHITE,
    "WARNING": Fore.YELLOW,
    "ERROR": Fore.RED,
    "CRITICAL": Fore.RED + Style.BRIGHT,
}


class ColoredFormatter(logging.Formatter):
    """
    Enhanced Formatter mit Farben, Emojis und Modul-spezifischen Formatierungen
    """

    def __init__(self, use_colors=True, use_emojis=True):
        super().__init__()
        self.use_colors = use_colors
        self.use_emojis = use_emojis

    def format(self, record):
        # Script-Namen aus dem Logger-Namen extrahieren
        script_name = record.name.split(".")[-1]

        # Basis-Formatierung
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Level-Formatierung
        level_name = record.levelname
        if self.use_emojis and level_name in LOG_LEVEL_EMOJIS:
            level_display = LOG_LEVEL_EMOJIS[level_name]
        else:
            level_display = level_name

        if self.use_colors and level_name in LOG_LEVEL_COLORS:
            level_display = (
                LOG_LEVEL_COLORS[level_name] + level_display + Style.RESET_ALL
            )

        # Modul-Formatierung
        module_name = script_name
        module_display = module_name

        if self.use_emojis and module_name in MODULE_EMOJIS:
            module_emoji = MODULE_EMOJIS[module_name]
            module_display = f"{module_emoji} [{module_name.upper()}]"
        else:
            module_display = f"[{module_name.upper()}]"

        if self.use_colors and module_name in MODULE_COLORS:
            module_color = MODULE_COLORS[module_name]
            module_display = module_color + module_display + Style.RESET_ALL

        # Nachricht formatieren
        message = record.getMessage()

        # Finale Formatierung
        formatted = f"{timestamp} {level_display} {module_display} {message}"

        # Exception-Informationen hinzufügen falls vorhanden
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


class EnhancedRotatingFileHandler(RotatingFileHandler):
    """
    Erweiterte RotatingFileHandler mit besserer Fehlerbehandlung
    """

    def __init__(
        self,
        filename,
        mode="a",
        maxBytes=0,
        backupCount=0,
        encoding="utf-8",
        delay=False,
    ):
        # Stelle sicher dass das Verzeichnis existiert
        log_path = Path(filename)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)

    def emit(self, record):
        try:
            super().emit(record)
        except Exception as e:
            # Fallback: Schreibe in stderr wenn File-Logging fehlschlägt
            print(f"Logging Error: {e}", file=sys.stderr)
            print(f"Original Message: {record.getMessage()}", file=sys.stderr)


class EnhancedLogger:
    """
    Enhanced Logger-Wrapper mit zusätzlichen Features
    """

    def __init__(self, logger: logging.Logger, module_name: str):
        self.logger = logger
        self.module_name = module_name
        self._stats = {
            "debug_count": 0,
            "info_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "critical_count": 0,
            "start_time": datetime.now(),
        }

    def debug(self, message, *args, **kwargs):
        self._stats["debug_count"] += 1
        self.logger.debug(message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        self._stats["info_count"] += 1
        self.logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._stats["warning_count"] += 1
        self.logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._stats["error_count"] += 1
        self.logger.error(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        self._stats["critical_count"] += 1
        self.logger.critical(message, *args, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        """Gibt Logging-Statistiken zurück"""
        total_logs = sum(
            self._stats[key] for key in self._stats if key.endswith("_count")
        )
        runtime = datetime.now() - self._stats["start_time"]

        return {
            **self._stats,
            "total_logs": total_logs,
            "runtime_seconds": runtime.total_seconds(),
            "logs_per_second": total_logs / max(runtime.total_seconds(), 1),
        }

    def log_performance(
        self, operation: str, duration: float, details: Optional[Dict] = None
    ):
        """Spezielles Performance-Logging"""
        perf_info = f"🚀 PERFORMANCE: {operation} took {duration:.3f}s"
        if details:
            perf_info += f" | Details: {json.dumps(details, default=str)}"
        self.info(perf_info)

    def log_statistics(self, component: str, stats: Dict[str, Any]):
        """Spezielles Statistik-Logging"""
        stats_info = f"📊 STATISTICS [{component}]: {json.dumps(stats, default=str)}"
        self.info(stats_info)

    def log_cache_event(self, event: str, key: str, hit: bool = None):
        """Spezielles Cache-Event-Logging"""
        if hit is not None:
            status = "HIT" if hit else "MISS"
            cache_info = f"💾 CACHE {status}: {event} for '{key}'"
        else:
            cache_info = f"💾 CACHE: {event} for '{key}'"
        self.debug(cache_info)


def setup_enhanced_logging(
    log_file: str = "bot.log",
    level: str = "INFO",
    use_colors: bool = True,
    use_emojis: bool = True,
):
    """
    Richtet das erweiterte Logging-System ein
    """
    global _loggers_initialized

    # Root Logger konfigurieren
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Bestehende Handler entfernen
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Enhanced Formatter
    formatter = ColoredFormatter(use_colors=use_colors, use_emojis=use_emojis)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # File Handler mit Rotation
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = EnhancedRotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    _loggers_initialized = True
    return root_logger


def get_module_logger(module_name: str) -> EnhancedLogger:
    """
    Gibt einen spezifischen EnhancedLogger für ein Modul zurück
    """
    global _module_loggers

    if module_name not in _module_loggers:
        logger = logging.getLogger(module_name)
        enhanced_logger = EnhancedLogger(logger, module_name)
        _module_loggers[module_name] = enhanced_logger

    return _module_loggers[module_name]


# Convenience-Funktionen für die verschiedenen Module
def log_handler_info(msg: str, context: str = "DownloadHandler", **kwargs):
    logger = get_module_logger(context)
    logger.info(msg, **kwargs)


def log_handler_debug(msg: str, context: str = "DownloadHandler", **kwargs):
    logger = get_module_logger(context)
    logger.debug(msg, **kwargs)


def log_handler_warning(msg: str, context: str = "DownloadHandler", **kwargs):
    logger = get_module_logger(context)
    logger.warning(msg, **kwargs)


def log_handler_error(msg: str, context: str = "DownloadHandler", **kwargs):
    logger = get_module_logger(context)
    logger.error(msg, **kwargs)


# Downloader Logger
def log_downloader_info(msg: str, **kwargs):
    logger = get_module_logger("YoutubeDownloader")
    logger.info(msg, **kwargs)


def log_downloader_debug(msg: str, **kwargs):
    logger = get_module_logger("YoutubeDownloader")
    logger.debug(msg, **kwargs)


def log_downloader_error(msg: str, **kwargs):
    logger = get_module_logger("YoutubeDownloader")
    logger.error(msg, **kwargs)


def log_downloader_critical(msg: str, **kwargs):
    logger = get_module_logger("YoutubeDownloader")
    logger.critical(msg, **kwargs)


# Metadata Logger
def log_metadata_info(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.info(msg, **kwargs)


def log_metadata_debug(msg: str, data: dict = None, **kwargs):
    logger = get_module_logger("metadata")
    context = kwargs.pop("context", None)
    if context:
        msg = f"[{context}] {msg}"
    if data:
        logger.debug(f"{msg} | Data: {data}", **kwargs)
    else:
        logger.debug(msg, **kwargs)


def log_metadata_warning(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.warning(msg, **kwargs)


def log_metadata_error(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.error(msg, **kwargs)


# Playlist Logger
def log_playlist_info(msg: str, **kwargs):
    logger = get_module_logger("PlaylistProcessor")
    logger.info(msg, **kwargs)


def log_playlist_debug(msg: str, **kwargs):
    logger = get_module_logger("PlaylistProcessor")
    logger.debug(msg, **kwargs)


def log_playlist_warning(msg: str, **kwargs):
    logger = get_module_logger("PlaylistProcessor")
    logger.warning(msg, **kwargs)


def log_playlist_error(msg: str, **kwargs):
    logger = get_module_logger("PlaylistProcessor")
    logger.error(msg, **kwargs)


# Enhanced Processor Logger
def log_enhanced_info(message: str, **kwargs):
    """Enhanced Processing Info Log"""
    logger = get_module_logger("EnhancedProcessor")
    logger.info(message, **kwargs)


def log_enhanced_debug(message: str, **kwargs):
    """Enhanced Processing Debug Log"""
    logger = get_module_logger("EnhancedProcessor")
    logger.debug(message, **kwargs)


def log_enhanced_warning(message: str, **kwargs):
    """Enhanced Processing Warning Log"""
    logger = get_module_logger("EnhancedProcessor")
    logger.warning(message, **kwargs)


def log_enhanced_error(message: str, **kwargs):
    """Enhanced Processing Error Log"""
    logger = get_module_logger("EnhancedProcessor")
    logger.error(message, **kwargs)


# Duplicate Handler Logger
def log_duplicate_info(message: str, **kwargs):
    """Duplicate Handling Info Log"""
    logger = get_module_logger("DuplicateHandler")
    logger.info(message, **kwargs)


def log_duplicate_debug(message: str, **kwargs):
    """Duplicate Handling Debug Log"""
    logger = get_module_logger("DuplicateHandler")
    logger.debug(message, **kwargs)


def log_duplicate_warning(message: str, **kwargs):
    """Duplicate Handling Warning Log"""
    logger = get_module_logger("DuplicateHandler")
    logger.warning(message, **kwargs)


def log_duplicate_error(message: str, **kwargs):
    """Duplicate Handling Error Log"""
    logger = get_module_logger("DuplicateHandler")
    logger.error(message, **kwargs)


# Cookie Handler Logger
def log_cookie_info(message: str, **kwargs):
    """Cookie Handling Info Log"""
    logger = get_module_logger("CookieHandler")
    logger.info(message, **kwargs)


def log_cookie_debug(message: str, **kwargs):
    """Cookie Handling Debug Log"""
    logger = get_module_logger("CookieHandler")
    logger.debug(message, **kwargs)


def log_cookie_warning(message: str, **kwargs):
    """Cookie Handling Warning Log"""
    logger = get_module_logger("CookieHandler")
    logger.warning(message, **kwargs)


def log_cookie_error(message: str, **kwargs):
    """Cookie Handling Error Log"""
    logger = get_module_logger("CookieHandler")
    logger.error(message, **kwargs)


# Menu Logger (für metadata_utils)
def log_menu_info(msg: str, **kwargs):
    logger = get_module_logger("metadata_utils")
    logger.info(msg, **kwargs)


def log_menu_debug(msg: str, **kwargs):
    logger = get_module_logger("metadata_utils")
    logger.debug(msg, **kwargs)


def log_menu_warning(msg: str, **kwargs):
    logger = get_module_logger("metadata_utils")
    logger.warning(msg, **kwargs)


def log_menu_error(msg: str, **kwargs):
    logger = get_module_logger("metadata_utils")
    logger.error(msg, **kwargs)


# File Utils Logger
def log_file_info(msg: str, **kwargs):
    logger = get_module_logger("file_utils")
    logger.info(msg, **kwargs)


def log_file_debug(msg: str, **kwargs):
    logger = get_module_logger("file_utils")
    logger.debug(msg, **kwargs)


def log_file_warning(msg: str, **kwargs):
    logger = get_module_logger("file_utils")
    logger.warning(msg, **kwargs)


def log_file_error(msg: str, **kwargs):
    logger = get_module_logger("file_utils")
    logger.error(msg, **kwargs)


# Progress Logger
def log_progress_info(msg: str, **kwargs):
    logger = get_module_logger("progress_tracker")
    logger.info(msg, **kwargs)


def log_progress_debug(msg: str, **kwargs):
    logger = get_module_logger("progress_tracker")
    logger.debug(msg, **kwargs)


# Button Logger
def log_button_info(msg: str, **kwargs):
    logger = get_module_logger("button")
    logger.info(msg, **kwargs)


def log_button_debug(msg: str, **kwargs):
    logger = get_module_logger("button")
    logger.debug(msg, **kwargs)


def log_button_warning(msg: str, **kwargs):
    logger = get_module_logger("button")
    logger.warning(msg, **kwargs)


def log_button_error(msg: str, **kwargs):
    logger = get_module_logger("button")
    logger.error(msg, **kwargs)


def log_button_critical(msg: str, **kwargs):
    logger = get_module_logger("button")
    logger.critical(msg, **kwargs)


# Organizer Logger
def log_organizer_info(msg: str, **kwargs):
    logger = get_module_logger("organizer")
    logger.info(msg, **kwargs)


def log_organizer_debug(msg: str, **kwargs):
    logger = get_module_logger("organizer")
    logger.debug(msg, **kwargs)


def log_organizer_warning(msg: str, **kwargs):
    logger = get_module_logger("organizer")
    logger.warning(msg, **kwargs)


def log_organizer_error(msg: str, **kwargs):
    logger = get_module_logger("organizer")
    logger.error(msg, **kwargs)


def log_organizer_critical(msg: str, **kwargs):
    logger = get_module_logger("organizer")
    logger.critical(msg, **kwargs)


# GenreMap Logger
def log_genremap_info(msg: str, **kwargs):
    logger = get_module_logger("genremap")
    logger.info(msg, **kwargs)


def log_genremap_debug(msg: str, **kwargs):
    logger = get_module_logger("genremap")
    logger.debug(msg, **kwargs)


def log_genremap_warning(msg: str, **kwargs):
    logger = get_module_logger("genremap")
    logger.warning(msg, **kwargs)


def log_genremap_error(msg: str, **kwargs):
    logger = get_module_logger("genremap")
    logger.error(msg, **kwargs)


def log_genremap_critical(msg: str, **kwargs):
    logger = get_module_logger("genremap")
    logger.critical(msg, **kwargs)


# Debug Logger
def log_debug_info(msg: str, **kwargs):
    logger = get_module_logger("debug")
    logger.info(msg, **kwargs)


def log_debug_debug(msg: str, **kwargs):
    logger = get_module_logger("debug")
    logger.debug(msg, **kwargs)


def log_debug_warning(msg: str, **kwargs):
    logger = get_module_logger("debug")
    logger.warning(msg, **kwargs)


def log_debug_error(msg: str, **kwargs):
    logger = get_module_logger("debug")
    logger.error(msg, **kwargs)


def log_debug_critical(msg: str, **kwargs):
    logger = get_module_logger("debug")
    logger.critical(msg, **kwargs)


# Main Logger Funktionen
def log_main_info(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.info(msg, **kwargs)


def log_main_debug(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.debug(msg, **kwargs)


def log_main_warning(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.warning(msg, **kwargs)


def log_main_error(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.error(msg, **kwargs)


def log_main_critical(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.critical(msg, **kwargs)


# =============================================================================
# SPEZIFISCHE FUNKTIONEN FÜR BESTEHENDEN CODE
# =============================================================================


# Einfache Log-Funktionen (für backward compatibility)
def log_info(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.info(msg, **kwargs)


def log_error(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.error(msg, **kwargs)


def log_warning(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.warning(msg, **kwargs)


def log_debug(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.debug(msg, **kwargs)


def log_critical(msg: str, **kwargs):
    logger = get_module_logger("main")
    logger.critical(msg, **kwargs)


# Spezielle Funktionen für musicbrainz_client
def log_musicbrainz_info(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.info(msg, **kwargs)


def log_musicbrainz_error(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.error(msg, **kwargs)


def log_musicbrainz_debug(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.debug(msg, **kwargs)


def log_musicbrainz_warning(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.warning(msg, **kwargs)


# Spezielle Funktionen für lastfm_client
def log_lastfm_info(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.info(msg, **kwargs)


def log_lastfm_error(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.error(msg, **kwargs)


def log_lastfm_debug(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.debug(msg, **kwargs)


def log_lastfm_warning(msg: str, **kwargs):
    logger = get_module_logger("metadata")
    logger.warning(msg, **kwargs)


# Funktionen für reprocess_handler
def log_reprocess_info(msg: str, **kwargs):
    logger = get_module_logger("handler")
    logger.info(msg, **kwargs)


def log_reprocess_warning(msg: str, **kwargs):
    logger = get_module_logger("handler")
    logger.warning(msg, **kwargs)


# Neue erweiterte Logging-Funktionen
def log_performance(
    module: str, operation: str, duration: float, details: Optional[Dict] = None
):
    """Performance-Logging für beliebige Module"""
    logger = get_module_logger(module)
    logger.log_performance(operation, duration, details)


def log_statistics(module: str, component: str, stats: Dict[str, Any]):
    """Statistik-Logging für beliebige Module"""
    logger = get_module_logger(module)
    logger.log_statistics(component, stats)


def log_cache_event(module: str, event: str, key: str, hit: bool = None):
    """Cache-Event-Logging für beliebige Module"""
    logger = get_module_logger(module)
    logger.log_cache_event(event, key, hit)


def get_logging_stats(module: str = None) -> Dict[str, Any]:
    """Gibt Logging-Statistiken zurück"""
    if module:
        if module in _module_loggers:
            return _module_loggers[module].get_stats()
        return {}

    # Globale Statistiken
    global_stats = {"total_modules": len(_module_loggers), "modules": {}}

    for module_name, logger in _module_loggers.items():
        global_stats["modules"][module_name] = logger.get_stats()

    return global_stats


def setup_module_logging(
    module_name: str,
    log_file: str = None,
    level: str = "DEBUG",
    use_colors: bool = False,
    use_emojis: bool = True,
):
    """
    Richtet eine separate Log-Datei für ein spezifisches Modul ein
    """
    if log_file is None:
        log_file = f"logs/{module_name.lower()}.log"

    # Stelle sicher, dass das logs-Verzeichnis existiert
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Erstelle einen separaten Logger für das Modul
    logger = logging.getLogger(module_name)
    logger.setLevel(getattr(logging, level.upper()))

    # Entferne bestehende Handler (nur für diesen spezifischen Logger)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # File Handler mit Rotation für separate Datei
    file_handler = EnhancedRotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"  # 2MB
    )

    # Spezieller Formatter für Datei (ohne Farb-Codes)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(getattr(logging, level.upper()))

    # Console Handler für Debug-Ausgabe (optional)
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = ColoredFormatter(use_colors=use_colors, use_emojis=use_emojis)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)  # Zeige ALLES in Console

    # Handler zum Logger hinzufügen
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False  # WICHTIG: Verhindert doppelte Logs im Haupt-Logger

    # Enhanced Logger erstellen
    enhanced_logger = EnhancedLogger(logger, module_name)
    _module_loggers[module_name] = enhanced_logger

    enhanced_logger.info(f"✅ Separate Log-Datei eingerichtet: {log_file}")
    return enhanced_logger


def enable_module_debug(module_name: str, enable: bool = True):
    """
    Aktiviert/Deaktiviert Debug-Modus für ein spezifisches Modul
    """
    logger = logging.getLogger(module_name)
    if enable:
        logger.setLevel(logging.DEBUG)
        print(f"✅ Debug-Modus aktiviert für: {module_name}")
    else:
        logger.setLevel(logging.INFO)
        print(f"ℹ️ Debug-Modus deaktiviert für: {module_name}")


# Beispiel-Ausgabe in der Log-Datei:
"""
14:23:15 ℹ️ 📤 [DOWNLOADHANDLER] 📬 Empfangene Roh-Nachricht: "https://youtube.com/playlist?list=..."
14:23:15 🔍 📤 [DOWNLOADHANDLER] 🔗 URL erfolgreich extrahiert: https://youtube.com/playlist?list=...
14:23:16 ℹ️ ⬇️ [YOUTUBEDOWNLOADER] 1️⃣ 🔥 Starte Download-Prozess – Zugriff auf `downloader.py`
14:23:16 🔍 ⬇️ [YOUTUBEDOWNLOADER] 📁Zielverzeichnis für den Download: /downloads
14:23:17 ℹ️ 📋 [PLAYLISTPROCESSOR] 🔍 📊 Analysiere Playlist für dominanten Artist...
14:23:17 🔍 📋 [PLAYLISTPROCESSOR]    🎤 Track 01: Artist 'Clueso' erkannt
14:23:17 🔍 📋 [PLAYLISTPROCESSOR]    🎤 Track 02: Artist 'Clueso' erkannt
14:23:18 ℹ️ 📋 [PLAYLISTPROCESSOR] ✅ 👑 Dominanter Artist erkannt: 'Clueso' (77.8%)
14:23:18 ℹ️ 📊 [METADATA] 1️⃣ ▶️ Starte Metadaten-Verarbeitung für YouTube-ID: abc123
14:23:19 ℹ️ 📝 [METADATAPROCESSOR] 🎶 Starte Verarbeitung von 'Tanz aus der Reihe' von 'Clueso'...
14:23:20 ℹ️ 🚀 [ENHANCEDPROCESSOR] ✨ Starte erweiterte Verarbeitung...
14:23:21 ℹ️ 🔍 [DUPLICATEHANDLER] 🔎 Prüfe auf Duplikate...
14:23:22 ℹ️ 🍪 [COOKIEHANDLER] 🍪 Cookie-Backup erstellt: /backups/cookies_20231201_142322.txt
"""
