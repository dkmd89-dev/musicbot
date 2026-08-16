import os
import shutil
import asyncio
from pathlib import Path
from typing import Union
import logging
from shutil import move

logger = logging.getLogger(__name__)

# Semaphore für begrenzte parallele IO-Operationen
IO_SEMAPHORE = asyncio.Semaphore(5)  # z.B. max. 5 parallele Umbenennungen


async def safe_rename(
    src: Union[str, Path], dest: Union[str, Path], max_retries: int = 3
) -> bool:
    """
    Robustes Umbenennen mit Wiederholungslogik und Semaphore für begrenzte Parallelität.
    """
    src_path = Path(src)
    dest_path = Path(dest)

    if not src_path.exists():
        return False

    async with IO_SEMAPHORE:
        # Versuch atomisches Umbenennen
        if await atomic_rename(src_path, dest_path):
            return True

        # Fallback mit Wiederholungen
        for attempt in range(max_retries):
            try:
                os.rename(str(src_path), str(dest_path))
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Umbenennen fehlgeschlagen nach {max_retries} Versuchen: {e}"
                    )
                    raise
                await asyncio.sleep(1)
        return False


async def atomic_rename(src: Union[str, Path], dest: Union[str, Path]) -> bool:
    """
    Führt ein atomisches Umbenennen durch, falls vom Betriebssystem unterstützt.
    """
    src_path = Path(src)
    dest_path = Path(dest)

    # Sicherstellen, dass das Zielverzeichnis existiert
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if os.name == "posix":
            # Auf POSIX-Systemen ist os.rename atomar
            os.rename(str(src_path), str(dest_path))
        else:
            # Auf Windows versuchen wir es mit shutil.move
            shutil.move(str(src_path), str(dest_path))
        return True
    except Exception as e:
        logger.error(f"Atomisches Umbenennen fehlgeschlagen: {e}")
        return False


async def move_to_processed(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / source.name
    move(str(source), str(destination))
    return destination
