# yt_music_bot/services/downloader/utils/errors.py
"""
Fehler-Taxonomie für die Download-Pipeline (services/downloader/**).

Umbenannt von error_handler.py (ARCH-003, P-4): der Modulname
"error_handler" beschrieb vorher zwei völlig verschiedene Dinge - diese
Fehlerklassen (echt genutzt, z.B. von download_utils.py/file_utils.py) UND
eine komplett separate Telegram-Fehlermeldungs-Funktionsgruppe
(handle_error()/handle_exception()/log_error_event()/... - 0 Aufrufer im
Repo, ersetzt durch handlers/enhanced_error_handler.py, entfernt).
"""

from logger import get_module_logger

# Modul-spezifischen Logger erstellen
logger = get_module_logger("errors")

# ======================
#  FEHLERKLASSEN
# ======================


class DownloadError(Exception):
    """Basis-Fehlerklasse für alle Download-bezogenen Fehler."""

    base_message = "Download-Fehler"

    def __init__(self, details: str = "", code: str = "GENERIC"):
        self.code = code
        self.details = details
        super().__init__(f"{self.base_message} [{code}]: {details}")
        logger.debug(f"DownloadError erstellt: {self}")


class InvalidURLError(DownloadError):
    """Fehler für ungültige YouTube-URLs."""

    base_message = "Ungültige YouTube-URL"
    code = "INVALID_URL"

    def __init__(self, details: str = "", url: str = ""):
        self.url = url
        super().__init__(details=details or url, code=self.code)
        logger.debug(f"InvalidURLError erstellt: {self}")


class FormatNotAvailableError(DownloadError):
    """Fehler, wenn das gewünschte Audioformat nicht verfügbar ist."""

    base_message = "Format nicht verfügbar"
    code = "FORMAT_MISSING"

    def __init__(self, details: str = ""):
        super().__init__(details=details, code=self.code)
        logger.debug(f"FormatNotAvailableError erstellt: {self}")


class MetadataError(DownloadError):
    """Fehler bei der Verarbeitung oder dem Schreiben von Metadaten."""

    base_message = "Metadaten-Fehler"
    code = "METADATA_ERROR"

    def __init__(self, details: str = ""):
        super().__init__(details=details, code=self.code)
        logger.debug(f"MetadataError erstellt: {self}")


class FileProcessingError(DownloadError):
    """Fehler bei Dateioperationen wie Verschieben oder Umbenennen."""

    base_message = "Dateifehler"
    code = "FILE_ERROR"

    def __init__(self, details: str = ""):
        super().__init__(details=details, code=self.code)
        logger.debug(f"FileProcessingError erstellt: {self}")


class NetworkError(DownloadError):
    """Fehler bei Netzwerkverbindungen oder Timeouts."""

    base_message = "Netzwerk-Fehler"
    code = "NETWORK_ERROR"

    def __init__(self, details: str = ""):
        super().__init__(details=details, code=self.code)
        logger.debug(f"NetworkError erstellt: {self}")


class PermissionError(DownloadError):
    """Fehler bei Berechtigungsproblemen."""

    base_message = "Berechtigungs-Fehler"
    code = "PERMISSION_ERROR"

    def __init__(self, details: str = ""):
        super().__init__(details=details, code=self.code)
        logger.debug(f"PermissionError erstellt: {self}")
