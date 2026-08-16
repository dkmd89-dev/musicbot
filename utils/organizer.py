import shutil
from pathlib import Path
import logging

from config import Config
from utils.helpers import sanitize_filename  # optional, falls du sowas hast

logger = logging.getLogger("organizer_logger")


async def move_file_based_on_metadata(file_path: Path, metadata: dict) -> Path:
    """
    Bewegt die Datei basierend auf bereinigtem Artist, Album und Titel.
    Falls Datei bereits korrekt liegt, passiert nichts.
    """
    artist = metadata.get("artist") or "Unknown Artist"
    album = metadata.get("album") or "Unknown Album"
    title = metadata.get("title") or file_path.stem

    # Bereinigen / normalisieren
    artist_dir = sanitize_filename(artist.strip())
    album_dir = sanitize_filename(album.strip())
    title_file = sanitize_filename(title.strip())

    # Zielverzeichnis und Zielpfad
    target_dir = Config.LIBRARY_DIR / artist_dir / album_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    new_path = target_dir / f"{title_file}{file_path.suffix}"

    # Wenn Datei schon am richtigen Ort ist, abbrechen
    if file_path.resolve() == new_path.resolve():
        return new_path

    try:
        shutil.move(str(file_path), str(new_path))
        logger.info(f"📁 Datei verschoben: {file_path} → {new_path}")
    except Exception as e:
        logger.warning(f"⚠️ Fehler beim Verschieben: {file_path} → {new_path}: {e}")
        return file_path

    return new_path
