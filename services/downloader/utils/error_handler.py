# yt_music_bot/services/downloader/utils/error_handler.py

import logging
from telegram import Update
from telegram.constants import ParseMode

from helfer.markdown_helfer import format_as_markdown_v2
from logger import get_module_logger

# Modul-spezifischen Logger erstellen
logger = get_module_logger("error_handler")

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


# ======================
#  FUNKTIONEN FÜR FEHLERBEHANDLUNG
# ======================


async def handle_error(
    update: Update, error_messages: dict, error_type: str, context: dict = None
) -> None:
    """
    Zentrale Funktion zur Fehlerbehandlung, die eine Meldung an den Benutzer sendet.
    """
    context = context or {}
    message_template = error_messages.get(error_type, "❌ Unbekannter Fehler")
    formatted_message = message_template.format(**context)

    logger.error(f"Fehlerbehandlung: {error_type}")
    logger.error(f"Fehlernachricht: {formatted_message}")

    if context:
        logger.error(f"Kontext: {context}")

    if update and update.message:
        try:
            markdown_message = format_as_markdown_v2(formatted_message, as_code=True)
            await update.message.reply_text(
                text=markdown_message, parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.debug("Fehlernachricht an Telegram-Benutzer gesendet")
        except Exception as e:
            logger.error(f"Telegram-Sendefehler: {str(e)}", exc_info=True)


async def handle_exception(
    update: Update, error_messages: dict, exception: Exception
) -> dict:
    """
    Erkennt den Typ der Exception, ruft handle_error auf und gibt ein einheitliches Fehlerobjekt zurück.
    """
    logger.debug(
        f"Exception-Verarbeitung gestartet: {type(exception).__name__}: {str(exception)}"
    )

    if isinstance(exception, InvalidURLError):
        await handle_error(
            update,
            error_messages,
            "invalid_url",
            {"url": getattr(exception, "url", str(exception))},
        )
        result = {
            "success": False,
            "error": f"Ungültige URL: {str(exception)}",
            "error_code": "INVALID_URL",
        }
        logger.warning(f"Invalid URL Error verarbeitet: {result}")

    elif isinstance(exception, FormatNotAvailableError):
        await handle_error(
            update, error_messages, "format_not_available", {"details": str(exception)}
        )
        result = {
            "success": False,
            "error": f"Format nicht verfügbar: {str(exception)}",
            "error_code": "FORMAT_MISSING",
        }
        logger.warning(f"Format Not Available Error verarbeitet: {result}")

    elif isinstance(exception, FileProcessingError):
        await handle_error(
            update,
            error_messages,
            "file_processing_error",
            {"details": exception.details},
        )
        result = {
            "success": False,
            "error": f"Verarbeitung fehlgeschlagen: {str(exception)}",
            "error_code": "FILE_ERROR",
        }
        logger.error(f"File Processing Error verarbeitet: {result}")

    elif isinstance(exception, MetadataError):
        await handle_error(
            update, error_messages, "metadata_error", {"details": exception.details}
        )
        result = {
            "success": False,
            "error": f"Metadaten-Fehler: {str(exception)}",
            "error_code": "METADATA_ERROR",
        }
        logger.error(f"Metadata Error verarbeitet: {result}")

    elif isinstance(exception, NetworkError):
        await handle_error(
            update, error_messages, "network_error", {"details": str(exception)}
        )
        result = {
            "success": False,
            "error": f"Netzwerk-Fehler: {str(exception)}",
            "error_code": "NETWORK_ERROR",
        }
        logger.error(f"Network Error verarbeitet: {result}")

    elif isinstance(exception, PermissionError):
        await handle_error(
            update, error_messages, "permission_error", {"details": str(exception)}
        )
        result = {
            "success": False,
            "error": f"Berechtigungs-Fehler: {str(exception)}",
            "error_code": "PERMISSION_ERROR",
        }
        logger.error(f"Permission Error verarbeitet: {result}")

    elif isinstance(exception, DownloadError):
        await handle_error(
            update,
            error_messages,
            "download_error",
            {"error": f"Code: {exception.code}, Details: {exception.details}"},
        )
        result = {
            "success": False,
            "error": f"Download fehlgeschlagen: {str(exception)}",
            "error_code": exception.code,
        }
        logger.error(f"Generic Download Error verarbeitet: {result}")

    else:
        logger.critical(
            f"Unerwarteter kritischer Fehler: {type(exception).__name__}: {str(exception)}",
            exc_info=True,
        )
        await handle_error(
            update, error_messages, "critical_error", {"error": str(exception)}
        )
        result = {
            "success": False,
            "error": f"Kritischer Fehler: {str(exception)}",
            "error_code": "UNKNOWN_ERROR",
        }

    logger.debug(f"Exception-Verarbeitung abgeschlossen: {result}")
    return result


def log_error_event(error_type: str, details: str, context: dict = None):
    """
    Spezielle Funktion zum Loggen von Fehler-Events mit zusätzlichem Kontext.
    """
    context = context or {}
    logger.error(
        f"⚠️ ERROR_EVENT [{error_type}]: {details}", extra={"context": context}
    )


def log_warning_event(warning_type: str, details: str, context: dict = None):
    """
    Spezielle Funktion zum Loggen von Warnungs-Events.
    """
    context = context or {}
    logger.warning(
        f"⚠️ WARNING_EVENT [{warning_type}]: {details}", extra={"context": context}
    )


def get_error_stats() -> dict:
    """
    Gibt Statistiken über die Fehlerbehandlung zurück.
    """
    stats = logger.get_stats()
    return {"error_handler_stats": stats, "module": "error_handler"}


# Convenience-Funktionen für häufige Fehler
async def handle_network_error(
    update: Update, error_messages: dict, details: str = ""
) -> dict:
    """Behandelt Netzwerk-Fehler."""
    exception = NetworkError(details)
    return await handle_exception(update, error_messages, exception)


async def handle_permission_error(
    update: Update, error_messages: dict, details: str = ""
) -> dict:
    """Behandelt Berechtigungs-Fehler."""
    exception = PermissionError(details)
    return await handle_exception(update, error_messages, exception)


async def handle_invalid_url_error(
    update: Update, error_messages: dict, url: str = ""
) -> dict:
    """Behandelt ungültige URL-Fehler."""
    exception = InvalidURLError(url=url)
    return await handle_exception(update, error_messages, exception)
