import os
import re
import asyncio
import time
from contextlib import contextmanager
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Union
import inspect

from config import Config
from utils.regex import (
    ILLEGAL_CHARS_PATTERN,
    FEAT_NOTATION_PATTERN,
    EXTRA_SPACES_PATTERN,
)
from utils.cache import lfu_cache, string_cache
from utils.file_ops import IO_SEMAPHORE, atomic_rename

# Datei-Cache initialisieren
FILE_CACHE = set()

# Define album patterns
ALBUM_PATTERNS = [
    re.compile(r"album[: ]+(.*?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"from the album ['\"](.*?)['\"]", re.IGNORECASE),
    re.compile(r"album name[: ]+(.*?)(?:\n|$)", re.IGNORECASE),
]


def _get_calling_info():
    """Gibt den Namen und die Zeilennummer des aufrufenden Skripts zurück."""
    frame = inspect.currentframe()
    if not frame:
        return "Unbekannt"

    # Durchlaufe den Aufrufstapel, um den Ursprungs-Aufrufer zu finden
    caller_frame = frame.f_back
    while caller_frame:
        module_name = inspect.getmodule(caller_frame).__name__
        if not module_name.startswith(
            "yt_music_bot.logger"
        ) and not module_name.startswith("yt_music_bot.utils.helpers"):
            break
        caller_frame = caller_frame.f_back

    if caller_frame:
        filename = os.path.basename(caller_frame.f_code.co_filename)
        lineno = caller_frame.f_lineno
        return f"{filename}:{lineno}"

    return "Unbekannt"


class MyLogger:
    def debug(self, msg):
        logger.debug(msg)

    def info(self, msg):
        logger.info(msg)

    def warning(self, msg):
        logger.warning(msg)

    def error(self, msg):
        log_error(msg)  # Verwendet die log_error Funktion aus utils


def similarity(a: str, b: str) -> float:
    """Gibt eine Ähnlichkeitsquote zwischen zwei Strings zurück."""
    return SequenceMatcher(
        None,
        sanitize_filename(a).lower().strip(),
        sanitize_filename(b).lower().strip(),
    ).ratio()


@string_cache.decorator
def sanitize_filename(filename: Optional[Any]) -> str:
    """Bereinigt Dateinamen mit Unicode-Normalisierung und Ersetzung unerwünschter Zeichen."""
    try:
        if filename is None:
            return ""

        filename = str(filename)

        if len(filename) > Config.MAX_FILENAME_LENGTH:
            filename = filename[: Config.MAX_FILENAME_LENGTH]

        filename = unicodedata.normalize("NFC", filename)
        filename = ILLEGAL_CHARS_PATTERN.sub(" ", filename)
        filename = FEAT_NOTATION_PATTERN.sub(" feat. \\1", filename)
        filename = EXTRA_SPACES_PATTERN.sub(" ", filename).strip()

        # Sicherheit: ILLEGAL_CHARS_PATTERN entfernt Schrägstriche, aber keine
        # Punkte. Ein Ergebnis, das nur aus Punkten besteht (".", "..", "...")
        # ist als Pfadsegment ein Directory-Traversal-Token und wuerde
        # FilenameFixerTool.build_final_path() aus library_dir/_podcast_dir
        # herausfuehren, wenn es z.B. aus einem Artist-Tag ".." stammt.
        if filename and re.fullmatch(r"\.+", filename):
            filename = "unknown"

        return filename

    except Exception as e:
        log_error(
            f"Dateinamen-Bereinigung fehlgeschlagen: {str(e)}",
            {"filename": str(filename)},
        )
        return "ungueltiger_dateiname"


def sanitize_filename_enhanced(filename: str, max_length: int = 200) -> str:
    """
    Bereinigt einen Dateinamen von ungültigen Zeichen und kürzt ihn bei Bedarf.

    Args:
        filename: Der zu bereinigende Dateiname
        max_length: Maximale Länge des Dateinamens (Standard: 200)

    Returns:
        Bereinigter Dateiname
    """
    if not filename:
        logger.warning("Leerer Dateiname übergeben, verwende Fallback")
        return "unnamed"

    try:
        # Entferne ungültige Zeichen für Dateisysteme
        # Windows verbotene Zeichen: < > : " / \ | ? *
        # Zusätzlich: Steuerzeichen
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", filename)

        # Ersetze mehrfache Leerzeichen durch einzelnes
        sanitized = re.sub(r"\s+", " ", sanitized)

        # Entferne führende/nachfolgende Leerzeichen und Punkte
        sanitized = sanitized.strip(" .")

        # Falls nach Bereinigung leer, verwende Fallback
        if not sanitized:
            logger.warning(f"Dateiname nach Bereinigung leer: '{filename}'")
            return "unnamed"

        # Längenprüfung und -kürzung
        if len(sanitized) > max_length:
            logger.debug(
                f"Dateiname zu lang ({len(sanitized)} Zeichen), kürze auf {max_length}"
            )
            # Behalte Dateiendung falls vorhanden
            if "." in sanitized:
                name, ext = sanitized.rsplit(".", 1)
                # Reserviere Platz für Extension + Punkt
                max_name_length = max_length - len(ext) - 1
                if max_name_length > 10:  # Mindestens 10 Zeichen für Namen
                    sanitized = f"{name[:max_name_length]}.{ext}"
                else:
                    sanitized = sanitized[:max_length]
            else:
                sanitized = sanitized[:max_length]

        return sanitized

    except Exception as e:
        logger.error(f"Fehler bei Dateinamen-Bereinigung: {e}", exc_info=True)
        return "error_unnamed"


def ensure_directory(path: Path) -> bool:
    """
    Stellt sicher, dass ein Verzeichnis existiert.

    Args:
        path: Pfad zum Verzeichnis

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Verzeichnisses {path}: {e}")
        return False


def get_safe_path(base_path: Path, *parts: str) -> Path:
    """
    Erstellt einen sicheren Pfad aus Basis und Teilen mit Bereinigung.

    Args:
        base_path: Basis-Verzeichnis
        *parts: Pfad-Komponenten

    Returns:
        Bereinigter vollständiger Pfad
    """
    sanitized_parts = [sanitize_filename(str(part)) for part in parts if part]
    return base_path.joinpath(*sanitized_parts)


def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Kürzt einen String auf maximale Länge.

    Args:
        text: Zu kürzender Text
        max_length: Maximale Länge
        suffix: Suffix für gekürzte Strings

    Returns:
        Gekürzter String
    """
    if not text or len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


@lfu_cache.decorator
def identify_album_from_video(info: Dict[str, Any]) -> Optional[str]:
    """Versucht, den Albumnamen aus Videoinfos zu extrahieren."""
    info_title = info.get("title", "")
    info_description = info.get("description", "")

    if not info_title and not info_description:
        return None

    for field in [info_title, info_description]:
        for pattern in ALBUM_PATTERNS:
            match = pattern.search(field)
            if match:
                return sanitize_filename(match.group(1).strip())

    return None


async def safe_rename(
    src: Union[str, Path], dest: Union[str, Path], max_retries: int = 3
) -> bool:
    """Robustes Umbenennen mit Wiederholungslogik."""
    src_path = Path(src)
    dest_path = Path(dest)

    if not src_path.exists():
        return False

    async with IO_SEMAPHORE:
        if await atomic_rename(src_path, dest_path):
            return True

        for attempt in range(max_retries):
            try:
                src_path.replace(dest_path)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Umbenennen fehlgeschlagen nach {max_retries} Versuchen: {e}"
                    )
                    raise
                await asyncio.sleep(1)

        return False


async def verify_file(
    filepath: Union[str, Path], max_attempts: int = 10, delay: int = 1
) -> bool:
    """Überprüft asynchron die Existenz und Integrität einer Datei mit Cache-Unterstützung"""
    path = Path(filepath)

    # Prüfe Cache
    if str(path) in FILE_CACHE:
        return True

    async with IO_SEMAPHORE:
        for _ in range(max_attempts):
            if path.exists() and path.stat().st_size > 0:
                if path.stat().st_size < 10 * 1024 * 1024:
                    FILE_CACHE.add(str(path))
                return True
            await asyncio.sleep(delay)
        return False


@contextmanager
def track_performance(name: str):
    """Context Manager zum Tracken der Performance von Codeblöcken."""
    start = time.monotonic()
    try:
        yield
    finally:
        duration = time.monotonic() - start
        logger.debug(f"Performance: {name} took {duration:.2f}s")


def _validate_youtube_url(url: str) -> Optional[str]:
    """Validiert und normalisiert eine YouTube-URL."""
    if not url:
        logger.debug("URL ist leer.")
        return None
    url = url.strip()
    logger.info(f"[DEBUG] Prüfe URL: {url}")
    video_id_pattern = r"[0-9A-Za-z_-]{11}"

    # Playlist-URLs
    playlist_patterns = [
        r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([\w-]+)"
    ]
    for pattern in playlist_patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            logger.debug(f"Playlist-URL erkannt: {url}")
            return f"https://www.youtube.com/playlist?list={match.group(1)}"

    # Video-URLs
    video_patterns = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([\w-]{11})",
        r"(?:https?://)?(?:www\.)?youtu\.be/([\w-]{11})",
    ]
    for pattern in video_patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match and re.match(f"^{video_id_pattern}$", match.group(1)):
            logger.debug(f"Video-URL erkannt: {url}")
            return f"https://www.youtube.com/watch?v={match.group(1)}"

    # Fallback für andere URL-Formate
    fallback = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11})(?:\?|&|/|$)", url)
    if fallback:
        logger.debug(f"Fallback Video-ID gefunden: {fallback.group(1)}")
        return f"https://www.youtube.com/watch?v={fallback.group(1)}"

    logger.warning(f"[DEBUG] URL konnte nicht validiert werden: {url}")
    return None


import re

OFFICIAL_TAG_PATTERN = re.compile(
    r"\(official( video| music video| video clip)?\)", flags=re.IGNORECASE
)


def clean_title(title: str) -> str:
    title = OFFICIAL_TAG_PATTERN.sub("", title)

    patterns = [
        r"\(official( music video| video clip)?\)",  # (Official Music Video), (Official Video Clip)
        r"\(video\)",  # (Video)
        r"\(live[^)]*\)",  # (Live), (Live in Berlin), etc.
        r"\[official[^\]]*\]",  # [official video], [official]
        r"\[video[^\]]*\]",  # [video clip], etc.
        r"\bprod(?:uced)?\.?\s+by\s+[^\-()]+",  # prod. by XYZ, produced by ...
    ]

    for pat in patterns:
        title = re.sub(pat, "", title, flags=re.IGNORECASE)

    # Bindestrich-Abstände normalisieren
    title = re.sub(r"\s*-\s*", " - ", title)
    title = re.sub(r"\s+-\s*$", "", title)  # End-Bindestrich entfernen

    # Mehrfach-Leerzeichen bereinigen
    title = re.sub(r"\s+", " ", title)

    return title.strip()


def extract_artist_title_from_filename(filename: str) -> tuple[str, str]:
    """
    Extrahiert Künstler und Titel aus einem Dateinamen.
    Erwartet Format wie 'Künstler - Titel.ext'
    """
    # Nur Dateiname ohne Pfad/Extension
    name = Path(filename).stem

    # Versuch, am Trennzeichen ' - ' zu splitten
    if " - " in name:
        parts = name.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
        return artist, title

    # Falls kein Trennzeichen, alles als Titel behandeln
    return "", name.strip()
